"""One long-lived Claude Agent SDK session bound to a project workspace.

The model client comes from the LLM provider configured for the ``design_agent`` role (AGT-001, ``aicad.llm``):
by default the Claude Agent SDK. Auth (development): the SDK runs the Claude Code binary, which uses this PC's
Claude Code login when no ANTHROPIC_API_KEY is present. Production must switch to API-key auth (RISKS R-LIC-05).
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from aicad.agent import speed
from aicad.agent.blocks import extract_brief, extract_review
from aicad.agent.deferred import DeferredChecks, failure_note, has_pending
from aicad.agent.edits import extract_edit
from aicad.agent.pricing import usage_cost_usd
from aicad.agent.prompt import CAD_AGENT_INSTRUCTIONS
from aicad.agent.runner import is_verified
from aicad.agent.runrecord import CallLog, RunRecorder
from aicad.agent.tools import make_cad_server

BUILTIN_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "TodoWrite", "WebFetch"]
CAD_TOOLS = ["mcp__cad__build_model"]
WEBFETCH_HOSTS = {"build123d.readthedocs.io"}
PATH_KEYS = ("file_path", "path", "notebook_path")
MAX_TURNS = 80
PRECONNECT_IDLE_S = 600.0  # a pre-connected agent process nobody used is stopped after this
MAX_VERIFY_FOLLOWUPS = 1  # automatic follow-ups per turn when a background check fails (PS-01)
# The agent stream carries attached images (base64) inside single JSON messages; the SDK default of 1 MB
# rejected ordinary photos and drawings. Uploads are capped well below this.
AGENT_BUFFER_BYTES = 32 * 1024 * 1024
# Cost controls (docs/reports/agent-cost.md). A hard ceiling per turn on top of the user's run budget, so a turn can
# never run away even where no budget applies (God mode). 0 turns it off.
TURN_CAP_ENV, CACHE_TTL_ENV, EFFORT_ENV = "FW_AGENT_TURN_CAP_USD", "FW_AGENT_CACHE_TTL", "FW_AGENT_EFFORT"
DEFAULT_TURN_CAP_USD = 2.50
EFFORTS = ("low", "medium", "high", "xhigh", "max")
BUDGET_STOP_NOTE = ("I stopped here because this request reached its cost limit. Everything built so far stays in the "
                    "design, and the checks panel shows where it stands. Ask me to continue if you want me to carry on.")


def turn_cap_usd() -> float | None:
    try:
        v = float(os.environ.get(TURN_CAP_ENV, DEFAULT_TURN_CAP_USD))
    except ValueError:
        v = DEFAULT_TURN_CAP_USD
    return v if v > 0 else None


def harness_env() -> dict[str, str]:
    """Environment for the agent harness process (agent-cost report).

    - ``ENABLE_CLAUDEAI_MCP_SERVERS=false``: the harness otherwise loads the claude.ai connectors of whoever is logged
      in (in development: the founder's Atlassian, Microsoft 365, Vanta, ... tools). Their schemas were about 311k
      tokens of every call after the first, the whole cost of a $3 cold turn, and the in-app agent must never see them.
    - ``CLAUDE_CODE_PROMPT_CACHE_TTL=5m``: a subscription login writes 1-hour cache entries (2x the input price);
      5-minute entries cost 1.25x and cover a design turn, whose calls are seconds apart. API-key auth (production,
      PD-09) already defaults to 5 minutes. ``FW_AGENT_CACHE_TTL=1h`` restores the long entries."""
    env = {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}
    ttl = (os.environ.get(CACHE_TTL_ENV) or "5m").strip().lower()
    if ttl in ("5m", "1h"):
        env["CLAUDE_CODE_PROMPT_CACHE_TTL"] = ttl
    return env


def effort_setting() -> str | None:
    """Opt-in reasoning effort (``FW_AGENT_EFFORT``). Unset: the harness default (``medium`` on the default model)."""
    e = (os.environ.get(EFFORT_ENV) or "").strip().lower()
    return e if e in EFFORTS else None


def _inside(p: str, root: Path) -> bool:
    try:
        rp = (root / p).resolve() if not Path(p).is_absolute() else Path(p).resolve()
    except (OSError, ValueError):
        return False
    return rp == root or root in rp.parents


DISCUSS_PREFIX = (
    "[Discussion mode: the user wants to talk, not build. Do not create, edit or rebuild the model; those tools are "
    "disabled in this mode. You may read the current design to answer. Answer engineering questions directly and "
    "concisely, with numbers, standards and trade-offs where useful. If the user is planning a design, help shape it: "
    "requirements, options with trade-offs, a recommended approach, key dimensions, and a numbered list under a "
    "'Build plan' heading. Use clickable questions for open choices. The user can press 'Build this plan' to switch "
    "to building.]\n\n"
)

BRIEF_PREFIX = (
    "[Brief confirmation: this is a new design. Do not create, edit or build anything yet; those tools are disabled "
    "until the user approves. Reply with one short sentence, then ONE fenced fw-brief block with your interpreted "
    "requirements, the assumptions you would make, and the open questions whose answers would change the design. "
    "The user edits and approves it, then you build.]\n\n"
)
LOCKED_MODES = {"discuss": "Discussion mode: the design must not be changed. Describe the plan instead.",
                "brief": "The brief is awaiting the user's approval: do not build yet. Return the fw-brief block."}


def make_guard(root: Path, mode_of: Any = None) -> Any:
    root = root.resolve()

    async def guard(input_data: Any, tool_use_id: str | None, context: Any) -> dict[str, Any]:
        name = input_data.get("tool_name", "")
        ti = input_data.get("tool_input", {}) or {}
        reason = None
        locked = LOCKED_MODES.get(mode_of()) if mode_of is not None else None
        if locked and (name in ("Write", "Edit") or "build_model" in name):
            reason = locked
        elif name in ("Read", "Write", "Edit", "Glob", "Grep"):
            for k in PATH_KEYS:
                if ti.get(k) and not _inside(str(ti[k]), root):
                    reason = f"{k} outside the project workspace is not allowed"
            pat = str(ti.get("pattern", ""))
            if name == "Glob" and (".." in pat or Path(pat).is_absolute()):
                reason = "glob patterns must stay inside the workspace"
        elif name == "WebFetch":
            host = urlparse(str(ti.get("url", ""))).hostname or ""
            if host not in WEBFETCH_HOSTS:
                reason = f"web access limited to {sorted(WEBFETCH_HOSTS)}"
        if reason:
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                           "permissionDecision": "deny",
                                           "permissionDecisionReason": reason}}
        return {}

    return guard


import re as _re

# ---------------------------------------------------------------- user-facing wording
# Users never see internal file names, tool names, libraries or model identifiers.


def friendly_step(name: str, inp: dict[str, Any]) -> str:
    """Plain-language description of an agent step."""
    n = name.replace("mcp__cad__", "")
    path = str(inp.get("file_path") or inp.get("path") or "")
    is_ref = "refs/" in path.replace("\\", "/")
    if n == "build_model":
        return "Building and verifying the part"
    if n == "Read":
        return "Studying the reference image" if is_ref else "Reviewing the current design"
    if n == "Write":
        return "Drafting the design"
    if n == "Edit":
        return "Updating the design"
    if n in ("Glob", "Grep"):
        return "Looking through the project"
    if n == "TodoWrite":
        return "Planning the design steps"
    if n == "WebFetch":
        return "Checking engineering reference material"
    return "Working on the design"


def friendly_result(name: str, text: str, is_error: bool) -> str:
    n = name.replace("mcp__cad__", "")
    t = text.strip()
    if n == "build_model":
        if t.startswith("Overall gating checks: PASS"):
            return "All checks passed"
        if t.startswith("Overall gating checks: FAIL"):
            return "Some checks failed — revising"
        if t.startswith("BUILD FAILED") or is_error:
            return "Build error — fixing it"
        return ""
    return "Couldn't complete this step — trying another way" if is_error else ""


_SCRUB = [
    (_re.compile(r"`?\bmodel\.py\b`?"), "the design"),
    (_re.compile(r"`?\bbuild_model\b`?"), "the build"),
    (_re.compile(r"`?\bmcp__cad__\w+`?"), "the build"),
    (_re.compile(r"`?\brefs/[\w.-]+`?"), "the reference image"),
    (_re.compile(r"\bbuild123d\b", _re.IGNORECASE), "the CAD kernel"),
    (_re.compile(r"`?\bfw\.(feature|edges_near|faces_near|apply_manual|thread|base_flange|edge_flange|hem|jog|sheet|"
                 r"spur_gear|stepped_shaft|shaft_keyway|bolt_circle|holes_at|hole_spec|hole|din6885|plate|gusset|"
                 r"cross_hole_volume|cross_hole|meta)\b`?"),
     "the design tools"),
    (_re.compile(r"`?\bSUPPRESSED_FEATURES\b`?"), "the suppressed-features list"),
    (_re.compile(r"`?\bMANUAL_FEATURES\b`?"), "the manual features"),
    (_re.compile(r"\bPARAM_META\b"), "parameter limits"),
    (_re.compile(r"\bEXPECTED\b"), "expected values"),
    (_re.compile(r"\bPARAMS\b"), "parameters"),
]


_Q_BLOCK = re.compile(r"```fw-questions\s*\n(.*?)\n?```", re.DOTALL)


_R_BLOCK = re.compile(r"```fw-recognition\s*\n(.*?)\n?```", re.DOTALL)


def extract_recognition(text: str) -> tuple[str, dict[str, Any] | None]:
    """Pull the agent's AI feature-recognition result (```fw-recognition JSON) out of its message."""
    import json as _json

    found: dict[str, Any] | None = None
    for m in _R_BLOCK.finditer(text):
        try:
            raw = _json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(raw, dict):
            comp = raw.get("component") if isinstance(raw.get("component"), dict) else None
            feats = [f for f in (raw.get("features") or []) if isinstance(f, dict) and f.get("name")][:200]
            found = {"component": {k: scrub(str(v))[:300] for k, v in (comp or {}).items()} if comp else None,
                     "features": [{"id": str(f.get("id", ""))[:40], "name": scrub(str(f["name"]))[:160],
                                   "kind": str(f.get("kind", ""))[:60], "note": scrub(str(f.get("note", "")))[:400],
                                   "params": {str(k)[:40]: v for k, v in (f.get("params") or {}).items()
                                              if isinstance(v, (int, float, str, bool))} if isinstance(f.get("params"), dict) else {}}
                                  for f in feats]}
    return _R_BLOCK.sub("", text).strip(), found


def extract_questions(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Pull the agent's structured clarifying questions (a fenced ```fw-questions JSON block) out of its message.
    Returns (text without the block, validated questions). Malformed blocks are dropped from the text, never shown raw."""
    import json as _json

    out: list[dict[str, Any]] = []
    for m in _Q_BLOCK.finditer(text):
        try:
            raw = _json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(raw, dict):
            raw = raw.get("questions", [])
        if not isinstance(raw, list):
            continue
        for i, q in enumerate(raw[:6]):
            if not isinstance(q, dict) or not isinstance(q.get("question"), str):
                continue
            opts = [str(o)[:120] for o in (q.get("options") or []) if isinstance(o, (str, int, float))][:8]
            if not opts:
                continue
            out.append({"id": str(q.get("id") or f"q{len(out) + 1}")[:40], "question": scrub(q["question"][:300]),
                        "options": [scrub(o) for o in opts], "multi": bool(q.get("multi", False)),
                        "other": bool(q.get("other", True)),
                        "default": str(q["default"])[:120] if q.get("default") is not None else None})
            _ = i
    return _Q_BLOCK.sub("", text).strip(), out


def scrub(text: str) -> str:
    for rx, rep_ in _SCRUB:
        text = rx.sub(rep_, text)
    return text


COMPACT_BASE = """You are the design agent inside Formwright, working in one project folder with file tools and a CAD
build tool. Work autonomously and efficiently:
- Read a file before you Edit it; use Edit for changes to existing files and Write for new files; keep edits minimal.
- Use paths inside the working folder only. Never print or paste file contents or code to the user.
- Call independent tools in the same response when you can. Don't repeat a tool call whose result you already have.
- Be concise: short plain sentences, no preamble, no restating the request.
"""


def compact_system_prompt() -> str:
    """PS-04: a compact custom system prompt (every Formwright rule, without the generic coding-assistant preset)."""
    return COMPACT_BASE + CAD_AGENT_INSTRUCTIONS


def system_prompt() -> Any:
    """The agent's system prompt. Default: the Claude Code preset + the CAD instructions (unchanged behaviour).
    ``FW_AGENT_SYSTEM_PROMPT=compact`` switches to the compact prompt (measured in docs/reports/pipeline-speed.md;
    parked as a founder decision before it becomes the default)."""
    if os.environ.get("FW_AGENT_SYSTEM_PROMPT", "").strip().lower() == "compact":
        return compact_system_prompt()
    return {"type": "preset", "preset": "claude_code", "append": CAD_AGENT_INSTRUCTIONS}


def provider_client(options: ClaudeAgentOptions) -> Any:
    """Default client factory: the ``design_agent`` role's provider (AGT-001). For the default Claude Agent SDK
    provider this is the SDK client, or the replay/record client when ``FW_AGENT_REPLAY`` / ``FW_AGENT_RECORD`` is
    set in development (unchanged)."""
    from aicad import llm

    return llm.get_provider("design_agent").agent_client(options)


class AgentSession:
    def __init__(self, workspace: Path, model: str | None = None,
                 on_event: Callable[[dict[str, Any]], None] | None = None, worker_key: str | None = None) -> None:
        self.workspace = workspace.resolve()
        self.out_dir = self.workspace / "out"
        self.model = model
        self.on_event = on_event
        self.worker_key = worker_key
        self.deferred = DeferredChecks(worker_key or str(self.workspace), self.out_dir)  # PS-01 background checks
        self.client: Any = None  # ClaudeSDKClient, or a replay stand-in
        self.history: list[dict[str, Any]] = []
        self.last_prompt: str | None = None  # the request behind the next revision (change notices)
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.busy = False
        self.mode = "build"  # "build" | "discuss" | "brief" (the last two: no model changes, enforced by the guard)
        self.brief_approved = False  # CAD-028: the user approved a brief in this conversation
        self.client_factory: Callable[[ClaudeAgentOptions], Any] = provider_client  # AGT-001 (replay: AGT-002)
        self.session_id: str | None = None
        self.auth: str | None = None
        self.turn_meta: dict[str, Any] = {}
        # Run metering. The agent reports a cost that is cumulative for the connected session, so each run is
        # charged the difference from the previous report; the live meter sums the model's per-response usage.
        self.run_budget_usd: float | None = None  # stop the run when the live meter reaches this
        self._cost_base = 0.0  # cumulative cost already reported on the current connection
        self._run_costs: dict[str, float] = {}  # response id -> estimated cost, this run
        self._budget_hit = False
        self._result_seen = False
        self._calls = CallLog()  # per model call of the current turn: the live meter's source (agent-cost)
        self._connect_lock: asyncio.Lock | None = None
        self._sends = 0  # messages sent (an idle pre-connected agent process is dropped)
        self._idle: asyncio.Task[None] | None = None
        self._held_review: str | None = None  # a self-review written while background checks were pending
        self._tool_names: dict[str, str] = {}  # merged into the next result event (e.g. rev_before for undo)
        self._rec: RunRecorder | None = None  # AGT-009 run record of the current turn (server-side, admin only)
        self._last_run_cost: float | None = None
        self.last_run_record: dict[str, Any] | None = None
        self._state_dir = self.workspace / ".fw"
        self.design_seen: str | None = None  # sha of the design the agent last saw in this conversation (agent-latency)
        self._effort_applied: str | None = None  # the agent process's current effort (None = the harness default)
        self._model_applied: str | None = model
        self.turn_settings: dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------- persistence
    def _load(self) -> None:
        """Restore the visible transcript and the agent session id so a server restart loses nothing."""
        import json

        try:
            st = json.loads((self._state_dir / "agent.json").read_text(encoding="utf-8"))
            self.session_id = st.get("session_id")
            self.brief_approved = bool(st.get("brief_approved"))
            self.design_seen = st.get("design_seen") if self.session_id else None
        except (OSError, ValueError):
            pass
        try:
            for line in (self._state_dir / "chat.jsonl").read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.history.append(json.loads(line))
        except (OSError, ValueError):
            pass

    def _persist_event(self, ev: dict[str, Any]) -> None:
        import json

        if ev.get("type") in ("busy", "hello", "reset", "meter"):
            return
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            with (self._state_dir / "chat.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, default=str) + "\n")
        except OSError:
            pass

    def _persist_session(self) -> None:
        import json

        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            (self._state_dir / "agent.json").write_text(json.dumps({"session_id": self.session_id,
                                                                          "brief_approved": self.brief_approved,
                                                                          "design_seen": self.design_seen}),
                                                              encoding="utf-8")
        except OSError:
            pass

    def options(self) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            cwd=str(self.workspace),
            tools=BUILTIN_TOOLS,
            allowed_tools=BUILTIN_TOOLS + CAD_TOOLS,
            permission_mode="dontAsk",
            mcp_servers={"cad": make_cad_server(self.workspace, self.out_dir, self.worker_key, self.deferred)},
            system_prompt=system_prompt(),
            setting_sources=[],  # isolate from the developer's personal ~/.claude config
            hooks={"PreToolUse": [HookMatcher(matcher="Read|Write|Edit|Glob|Grep|WebFetch|mcp__cad__build_model",
                                              hooks=[make_guard(self.workspace, lambda: self.mode)])]},
            max_turns=MAX_TURNS,
            max_buffer_size=AGENT_BUFFER_BYTES,
            model=self.model,
            resume=self.session_id,  # continue the same agent conversation after a restart
            strict_mcp_config=True,  # only the CAD server: no project, user or plugin MCP servers
            env=harness_env(),  # no claude.ai connectors; 5-minute prompt cache
            include_partial_messages=True,  # per-call usage (input, cache, final output) for the meter and run record
            effort=effort_setting(),
        )

    def publish(self, ev: dict[str, Any]) -> None:
        ev.setdefault("t", time.time())
        if self.on_event is not None:
            self.on_event(ev)  # may enrich ev (e.g. tokens charged) before broadcast
        if ev.get("type") not in ("busy", "hello", "meter"):
            self.history.append(ev)
        self._persist_event(ev)
        for q in list(self.subscribers):
            q.put_nowait(ev)

    async def ensure_connected(self) -> Any:
        if self._connect_lock is None:
            self._connect_lock = asyncio.Lock()
        async with self._connect_lock:  # a pre-connect may still be starting the agent when the first message arrives
            if self.client is None:
                self.workspace.mkdir(parents=True, exist_ok=True)
                opts = self.options()
                client = self.client_factory(opts)
                await client.connect()
                self.client = client
                self._cost_base = 0.0  # a new agent process reports cost from zero
                self._effort_applied, self._model_applied = getattr(opts, "effort", None), self.model
        return self.client

    async def preconnect(self, idle_s: float = PRECONNECT_IDLE_S) -> None:
        """PS-04: start the agent process when the Studio opens a project, so the first message skips the connect
        (no model call, no tokens). Dropped again if no message arrives within ``idle_s``."""
        if self.client is not None or self.busy:
            return
        mark = self._sends
        try:
            await self.ensure_connected()
        except Exception:  # noqa: BLE001 - the first message connects (and reports) as before
            self.client = None
            return

        async def drop() -> None:
            await asyncio.sleep(idle_s)
            if self._sends == mark and not self.busy and self.client is not None:
                client, self.client = self.client, None
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001,S110 - an idle pre-connected process is simply dropped
                    pass

        self._idle = asyncio.get_running_loop().create_task(drop())

    def _provider_name(self) -> str:
        """The provider behind this session's client, for the run record (``custom`` for injected factories)."""
        if self.client_factory is not provider_client:
            return "custom"
        try:
            import os

            from aicad import llm
            from aicad.agent.replay import RECORD_ENV, REPLAY_ENV

            name = llm.get_provider("design_agent").name
            if name == "claude-sdk" and os.environ.get(REPLAY_ENV):
                return "claude-sdk:replay"
            if name == "claude-sdk" and os.environ.get(RECORD_ENV):
                return "claude-sdk:recording"
            return name
        except Exception:  # noqa: BLE001 - telemetry only
            return "unknown"

    @property
    def run_spent_usd(self) -> float:
        return sum(self._run_costs.values())

    async def send(self, prompt: str, shown: str | None = None, mode: str = "build") -> None:
        """One agent turn. ``shown``: what the chat shows as the user's message when ``prompt`` is a structured
        brief a module wrote on the user's behalf (the brief itself is never published)."""
        if self.busy:
            raise RuntimeError("agent is busy")
        self.busy = True
        self._sends += 1
        self.mode = mode if mode in ("discuss", "brief") else "build"
        if self.mode != "build":
            shown, prompt = shown or prompt, (DISCUSS_PREFIX if self.mode == "discuss" else BRIEF_PREFIX) + prompt
        self.publish({"type": "user", "text": shown or prompt, "mode": self.mode})
        self.last_prompt = re.split(r"\n\n\[(?:Selected|Reference image|Recognition data|Design state|Project context|"
                                    r"Designer preferences|Project folder|Current design)",
                                    shown or prompt)[0].strip()[:600]
        full, folder = self._with_folder_note(prompt)  # the run record keeps the caller's prompt
        self.publish({"type": "busy", "value": True})
        self._run_costs, self._budget_hit, self._result_seen = {}, False, False
        self._calls = CallLog()
        self._last_run_cost = None
        started, failed = time.time(), False
        build_before = (self._status() or {}).get("build_id")
        try:
            self._rec = RunRecorder(self.workspace, prompt=prompt, mode=self.mode, requested_model=self.model,
                                    run_id=str(self.turn_meta.get("run_id") or "") or None,
                                    provider=self._provider_name())
        except Exception:  # noqa: BLE001 - telemetry never blocks a run
            self._rec = None
        try:
            try:
                client = await self.ensure_connected()
            except Exception:
                if not self.session_id:
                    raise
                self.session_id, self.client = None, None
                client = await self.ensure_connected()
            if self._rec is not None:
                self._rec.mark("connected")
            await self._apply_turn_settings(client, full, folder)
            await client.query(full)
            stopping = False
            builds_before, followups = self.deferred.started, 0
            while True:
                held = None
                async for msg in client.receive_response():
                    if isinstance(msg, ResultMessage) and self.deferred.started != builds_before:
                        held = msg  # the verdict waits for the build's background checks (PS-01)
                        continue
                    self._handle(msg)
                    if self._budget_hit and not stopping:
                        stopping = True
                        self.publish({"type": "text", "text": BUDGET_STOP_NOTE})
                        await client.interrupt()
                if held is None:
                    break
                follow = await self._settle_builds(followups, stopping)
                if follow:
                    followups += 1
                    builds_before = self.deferred.started
                    await client.query(follow)  # the held result is superseded by the follow-up's (cost is cumulative)
                    continue
                self._handle(held)
                break
        except Exception:
            import logging

            failed = True
            logging.getLogger("aicad.agent").exception("agent run failed")
            self.publish({"type": "error", "text": "The design agent hit a problem and stopped. Your model and files are "
                                                   "unchanged — please try again."})
        finally:
            if not self._result_seen and self.run_spent_usd > 0:
                self._cost_base += self.run_spent_usd  # the next cumulative report includes it
            if not self._result_seen and self.run_spent_usd > 0 and not failed:
                # Stopped before the agent reported its cost: charge what the meter saw (failures are not charged).
                self.publish({"type": "result", "subtype": "stopped", "turns": None,
                              "duration_s": round(time.time() - started, 1), "cost_est_usd": self.run_spent_usd,
                              "budget_stopped": self._budget_hit, **self.turn_meta})
                self.turn_meta = {}
            self._remember_design()
            self._write_run_record(failed, build_before)
            self.busy = False
            self.publish({"type": "busy", "value": False})

    # ------------------------------------------------------------- agent-latency: context and turn settings
    def _with_folder_note(self, prompt: str) -> tuple[str, str]:
        """Append the project folder's state (and the design's text when the agent hasn't seen this version), so the
        agent never spends a call listing the folder or reading a design it is given. Never shown in the chat."""
        try:
            note, h = speed.folder_note(self.workspace, self.design_seen if self.session_id else None, self.mode)
        except Exception:  # noqa: BLE001 - context is an optimisation, never a reason to fail a turn
            return prompt, "none"
        kind = ("new" if h is None else "unchanged" if "unchanged since" in note else
                "inlined" if "[Current design" in note else "read")
        return prompt + "\n\n" + note, kind

    def _remember_design(self) -> None:
        """After a turn the agent has seen the design as it is now (it wrote, edited or was given it)."""
        if self.mode != "build":
            return
        src = speed.design_text(self.workspace)
        self.design_seen = speed.sha(src) if src else None
        if self.session_id:
            self._persist_session()

    async def _apply_turn_settings(self, client: Any, prompt: str, folder: str) -> None:
        """Adaptive effort (and, opt-in, model routing) for this turn, switched on the running agent process with a
        control request (no model call, no reconnect). Clients without it (replays, fakes) keep their settings."""
        has_design = folder not in ("new", "none")
        forced = effort_setting()
        if self.mode == "build":
            effort, why = speed.choose_effort(prompt, has_design, forced)
            model, mwhy = speed.route_model(prompt, has_design, self.model)
        else:
            effort, why, model, mwhy = forced, f"{self.mode} mode", self.model, f"{self.mode} mode"
        q = getattr(client, "_query", None)
        applied_effort = effort
        if effort != self._effort_applied:
            if q is not None and hasattr(q, "_send_control_request"):
                try:
                    await q._send_control_request({"subtype": "apply_flag_settings",
                                                   "settings": {"effortLevel": effort}})
                    self._effort_applied = effort
                except Exception:  # noqa: BLE001 - an older agent CLI: keep its effort
                    applied_effort = self._effort_applied
            else:
                applied_effort = self._effort_applied
        applied_model = model
        if model != self._model_applied:
            try:
                await client.set_model(model)
                self._model_applied = model
            except Exception:  # noqa: BLE001 - replay/fake clients: keep the model
                applied_model = self._model_applied
        self.turn_settings = {"effort": applied_effort or "default", "effort_reason": why,
                              "model": applied_model or "default", "model_reason": mwhy, "folder": folder}
        if self._rec is not None:
            self._rec.rec["turn"] = dict(self.turn_settings)

    async def _settle_builds(self, followups: int, stopping: bool) -> str | None:
        """End of a turn that built: wait until the latest build's deferred checks (exports, CHK-07 round trip, CHK-08
        repeatability) have run, so the verdict, run record and notifications see a complete status. Returns a
        follow-up prompt when one of them failed (once per turn), else None."""
        st = self.deferred.read() if not has_pending(self.deferred.read()) else None
        if st is None:
            vid = f"verify-{time.time_ns()}"
            self.publish({"type": "tool", "id": vid, "name": "step", "brief": "Finishing verification"})
            st = await self.deferred.settle()
            self.publish({"type": "tool_result", "id": vid, "is_error": not is_verified(st), "build": False,
                          "brief": "Verification complete" if is_verified(st) else "Verification found a problem"})
        else:
            st = await self.deferred.settle()
        self.turn_meta["build_verified"] = is_verified(st)
        if self._rec is not None:
            self._rec.mark("verified")
        failed = self.deferred.take_failures()
        if not failed or followups >= MAX_VERIFY_FOLLOWUPS or stopping or self._budget_hit or self.mode != "build":
            held, self._held_review = self._held_review, None
            if held:
                _, review = extract_review(held, st, scrub)
                if review:
                    self.publish({"type": "review", **review})
            return None
        self._held_review = None  # the follow-up writes a new self-review
        return ("[Background verification] " + failure_note(failed, previous=False)
                + "\nFix the design so these checks pass, rebuild, and update your summary and self-review.")

    def _write_run_record(self, failed: bool, build_before: Any) -> None:
        """AGT-009: persist the turn's run record (never published to the chat; read by the admin console only)."""
        rec, self._rec = self._rec, None
        if rec is None:
            return
        try:
            self.last_run_record = rec.finish(failed=failed, budget_stopped=self._budget_hit,
                                              run_cost_usd=self._last_run_cost if self._last_run_cost is not None
                                              else (self.run_spent_usd or None), meter_usd=self.run_spent_usd,
                                              build_id_before=build_before)
            rec.write()
        except Exception:
            import logging

            logging.getLogger("aicad.agent").warning("run record not written", exc_info=True)

    def _handle(self, msg: Any) -> None:
        if self._rec is not None:
            self._rec.observe(msg)
        if isinstance(msg, StreamEvent):
            if msg.parent_tool_use_id is None and isinstance(msg.event, dict):
                mid = self._calls.stream(msg.event)
                if mid is not None:
                    self._charge(mid, self._calls.cost(mid))
            return
        if isinstance(msg, SystemMessage) and msg.subtype == "init":
            self.auth = msg.data.get("apiKeySource")
            self.publish({"type": "system", "model": "Formwright design agent"})
        elif isinstance(msg, AssistantMessage):
            self._meter(msg)
            for b in msg.content:
                if isinstance(b, TextBlock) and b.text.strip():
                    text, recog = extract_recognition(b.text)
                    if recog is not None:
                        self._save_recognition(recog)
                    text, questions = extract_questions(text)
                    text, brief = extract_brief(text, scrub)
                    review = None
                    if "fw-review" in text and has_pending(self._status()):
                        self._held_review = text  # reconciled with the settled checks at the end of the turn
                        text, _ = extract_review(text, None, scrub)
                    else:
                        text, review = extract_review(text, self._status() if "fw-review" in text else None, scrub)
                    edit, edit_note = None, None
                    if "fw-edit" in text:  # DS-035: a small edit handed to the PropertyManager
                        text, edit, edit_note = extract_edit(text, self.workspace, scrub)
                    if text.strip():
                        self.publish({"type": "text", "text": scrub(text)})
                    if questions:
                        self.publish({"type": "questions", "questions": questions})
                    if brief:
                        self.publish({"type": "brief", "brief": brief})
                    if review:
                        self.publish({"type": "review", **review})
                    if edit:
                        self.publish({"type": "edit", "edit": edit})
                    elif edit_note:
                        self.publish({"type": "text", "text": "The proposed change can't open in the PropertyManager: "
                                                              + scrub(edit_note)})
                elif isinstance(b, ToolUseBlock):
                    self._tool_names[b.id] = b.name
                    self.publish({"type": "tool", "id": b.id, "name": "build" if "build_model" in b.name else "step",
                                  "brief": friendly_step(b.name, b.input or {})})
        elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
            for b in msg.content:
                if isinstance(b, ToolResultBlock):
                    text = ""
                    if isinstance(b.content, str):
                        text = b.content
                    elif isinstance(b.content, list):
                        text = " ".join(c.get("text", "") for c in b.content if isinstance(c, dict))
                    name = self._tool_names.get(b.tool_use_id, "")
                    self.publish({"type": "tool_result", "id": b.tool_use_id, "is_error": bool(b.is_error),
                                  "brief": friendly_result(name, text, bool(b.is_error)),
                                  "build": "build_model" in name})
        elif isinstance(msg, ResultMessage):
            self.session_id = msg.session_id
            self._persist_session()
            self._result_seen = True
            self._last_run_cost = self._run_cost(msg.total_cost_usd)
            self.publish({"type": "result", "subtype": msg.subtype, "turns": msg.num_turns,
                          "duration_s": round(msg.duration_ms / 1000, 1),
                          "cost_est_usd": self._last_run_cost, "budget_stopped": self._budget_hit,
                          **self.turn_meta})
            self.turn_meta = {}

    def _run_cost(self, cumulative: float | None) -> float | None:
        """This run's cost from the session's cumulative report (falls back to the live meter)."""
        if cumulative is None:
            return self.run_spent_usd or None
        run = cumulative - self._cost_base if cumulative >= self._cost_base else cumulative
        self._cost_base = cumulative
        return max(run, 0.0)

    def _meter(self, msg: AssistantMessage) -> None:
        """Live cost meter from a response's usage snapshot, for clients without stream events (replay, fakes). With
        stream events the meter follows each call's final usage instead (``_handle``), output included."""
        if not msg.usage or self._calls.streamed:
            return
        self._charge(msg.message_id or f"m{len(self._run_costs)}", usage_cost_usd(msg.model, msg.usage))

    def limit_usd(self) -> float | None:
        """The turn stops at the lower of the run budget and the hard per-turn cap."""
        caps = [c for c in (self.run_budget_usd, turn_cap_usd()) if c is not None]
        return min(caps) if caps else None

    def _charge(self, key: str, cost: float) -> None:
        """One entry per model call (a call arrives as several messages and stream events)."""
        if cost <= self._run_costs.get(key, 0.0):
            return
        self._run_costs[key] = cost
        spent = self.run_spent_usd
        self.publish({"type": "meter", "spent_usd": round(spent, 4),
                      "budget_usd": self.run_budget_usd})
        limit = self.limit_usd()
        if limit is not None and spent >= limit and not self._budget_hit:
            self._budget_hit = True

    def _status(self) -> dict[str, Any] | None:
        """The latest build's status: the gate truth a self-review is reconciled against."""
        import json as _json

        try:
            return _json.loads((self.out_dir / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _save_recognition(self, recog: dict[str, Any]) -> None:
        import json as _json

        try:
            st = _json.loads((self.out_dir / "status.json").read_text(encoding="utf-8"))
            recog["build_id"] = st.get("build_id")
            self._state_dir.mkdir(parents=True, exist_ok=True)
            (self._state_dir / "recognition_ai.json").write_text(_json.dumps(recog), encoding="utf-8")
            self.publish({"type": "recognition", "component": (recog.get("component") or {}).get("name")})
        except (OSError, ValueError):
            pass

    async def interrupt(self) -> None:
        if self.client and self.busy:
            await self.client.interrupt()

    async def reset(self) -> None:
        if self.busy:
            await self.interrupt()
        if self.client:
            try:
                await self.client.disconnect()
            except Exception as e:  # noqa: BLE001 - a dead CLI process must not block reset
                self.publish({"type": "error", "text": f"disconnect: {e}"})
        self.client = None
        self.history.clear()
        self.session_id = None
        self.brief_approved = False
        self.design_seen = None
        for f in ("chat.jsonl", "agent.json"):
            try:
                (self._state_dir / f).unlink()
            except OSError:
                pass
        self.publish({"type": "reset"})
        self.history.clear()
