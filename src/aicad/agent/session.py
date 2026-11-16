"""One long-lived Claude Agent SDK session bound to a project workspace.

Auth (development): the SDK runs the Claude Code binary, which uses this PC's Claude Code login
when no ANTHROPIC_API_KEY is present. Production must switch to API-key auth (RISKS R-LIC-05).
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from aicad.agent.prompt import CAD_AGENT_INSTRUCTIONS
from aicad.agent.tools import make_cad_server

BUILTIN_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "TodoWrite", "WebFetch"]
CAD_TOOLS = ["mcp__cad__build_model"]
WEBFETCH_HOSTS = {"build123d.readthedocs.io"}
PATH_KEYS = ("file_path", "path", "notebook_path")
MAX_TURNS = 80


def _inside(p: str, root: Path) -> bool:
    try:
        rp = (root / p).resolve() if not Path(p).is_absolute() else Path(p).resolve()
    except (OSError, ValueError):
        return False
    return rp == root or root in rp.parents


def make_guard(root: Path) -> Any:
    root = root.resolve()

    async def guard(input_data: Any, tool_use_id: str | None, context: Any) -> dict[str, Any]:
        name = input_data.get("tool_name", "")
        ti = input_data.get("tool_input", {}) or {}
        reason = None
        if name in ("Read", "Write", "Edit", "Glob", "Grep"):
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
    (_re.compile(r"`?\bfw\.(feature|edges_near|faces_near|apply_manual)\b`?"), "the design tools"),
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


class AgentSession:
    def __init__(self, workspace: Path, model: str | None = None,
                 on_event: Callable[[dict[str, Any]], None] | None = None, worker_key: str | None = None) -> None:
        self.workspace = workspace.resolve()
        self.out_dir = self.workspace / "out"
        self.model = model
        self.on_event = on_event
        self.worker_key = worker_key
        self.client: ClaudeSDKClient | None = None
        self.history: list[dict[str, Any]] = []
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.busy = False
        self.session_id: str | None = None
        self.auth: str | None = None
        self.turn_meta: dict[str, Any] = {}
        self._tool_names: dict[str, str] = {}  # merged into the next result event (e.g. rev_before for undo)
        self._state_dir = self.workspace / ".fw"
        self._load()

    # ------------------------------------------------------------- persistence
    def _load(self) -> None:
        """Restore the visible transcript and the agent session id so a server restart loses nothing."""
        import json

        try:
            st = json.loads((self._state_dir / "agent.json").read_text(encoding="utf-8"))
            self.session_id = st.get("session_id")
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

        if ev.get("type") in ("busy", "hello", "reset"):
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
            (self._state_dir / "agent.json").write_text(json.dumps({"session_id": self.session_id}), encoding="utf-8")
        except OSError:
            pass

    def options(self) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            cwd=str(self.workspace),
            tools=BUILTIN_TOOLS,
            allowed_tools=BUILTIN_TOOLS + CAD_TOOLS,
            permission_mode="dontAsk",
            mcp_servers={"cad": make_cad_server(self.workspace, self.out_dir, self.worker_key)},
            system_prompt={"type": "preset", "preset": "claude_code", "append": CAD_AGENT_INSTRUCTIONS},
            setting_sources=[],  # isolate from the developer's personal ~/.claude config
            hooks={"PreToolUse": [HookMatcher(matcher="Read|Write|Edit|Glob|Grep|WebFetch",
                                              hooks=[make_guard(self.workspace)])]},
            max_turns=MAX_TURNS,
            model=self.model,
            resume=self.session_id,  # continue the same agent conversation after a restart
        )

    def publish(self, ev: dict[str, Any]) -> None:
        ev.setdefault("t", time.time())
        if self.on_event is not None:
            self.on_event(ev)  # may enrich ev (e.g. tokens charged) before broadcast
        if ev.get("type") not in ("busy", "hello"):
            self.history.append(ev)
        self._persist_event(ev)
        for q in list(self.subscribers):
            q.put_nowait(ev)

    async def ensure_connected(self) -> ClaudeSDKClient:
        if self.client is None:
            self.workspace.mkdir(parents=True, exist_ok=True)
            self.client = ClaudeSDKClient(options=self.options())
            await self.client.connect()
        return self.client

    async def send(self, prompt: str) -> None:
        if self.busy:
            raise RuntimeError("agent is busy")
        self.busy = True
        self.publish({"type": "user", "text": prompt})
        self.publish({"type": "busy", "value": True})
        try:
            try:
                client = await self.ensure_connected()
            except Exception:
                if not self.session_id:
                    raise
                self.session_id, self.client = None, None
                client = await self.ensure_connected()
            await client.query(prompt)
            async for msg in client.receive_response():
                self._handle(msg)
        except Exception:
            import logging

            logging.getLogger("aicad.agent").exception("agent run failed")
            self.publish({"type": "error", "text": "The design agent hit a problem and stopped. Your model and files are "
                                                   "unchanged — please try again."})
        finally:
            self.busy = False
            self.publish({"type": "busy", "value": False})

    def _handle(self, msg: Any) -> None:
        if isinstance(msg, SystemMessage) and msg.subtype == "init":
            self.auth = msg.data.get("apiKeySource")
            self.publish({"type": "system", "model": "Formwright design agent"})
        elif isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock) and b.text.strip():
                    text, recog = extract_recognition(b.text)
                    if recog is not None:
                        self._save_recognition(recog)
                    text, questions = extract_questions(text)
                    if text.strip():
                        self.publish({"type": "text", "text": scrub(text)})
                    if questions:
                        self.publish({"type": "questions", "questions": questions})
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
            self.publish({"type": "result", "subtype": msg.subtype, "turns": msg.num_turns,
                          "duration_s": round(msg.duration_ms / 1000, 1),
                          "cost_est_usd": msg.total_cost_usd, **self.turn_meta})
            self.turn_meta = {}

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
        for f in ("chat.jsonl", "agent.json"):
            try:
                (self._state_dir / f).unlink()
            except OSError:
                pass
        self.publish({"type": "reset"})
        self.history.clear()
