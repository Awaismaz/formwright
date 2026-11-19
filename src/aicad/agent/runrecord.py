"""AGT-009: a complete, server-side record of every design-agent turn (``<workspace>/.fw/runs/<run id>/run.json``).

What one record holds: the prompt (as a SHA-256 hash, plus a redacted excerpt or the raw text only when the policy
allows), the model ids requested and used, app / SDK / agent CLI / kernel / Toolbox versions, token counts and cost
estimates, wall-clock timings per phase, tool-call counts, the build outcomes seen during the turn and the final
check outcome, how the turn ended, and (EVAL-006, advisory) how similar the turn's last review render is to the
render the part had before the turn (``render_similarity``; never part of the verdict).

This is engineering telemetry for the founder and support. It contains agent internals (tool names, model ids), so
it is **never** sent to the Studio UI or included in exports: only the super-admin console reads it
(``/api/admin/projects/{id}/runs``). Writing a record must never break a run: every failure here is swallowed.

Prompt policy (``FW_RUN_RECORD_PROMPTS``):
  ``hash``      only the SHA-256 and the length
  ``redacted``  (default) hash + an excerpt with e-mail addresses, URLs, keys/tokens, long digit runs and attached
                image/recognition payloads removed, capped at 2,000 characters
  ``raw``       hash + the full prompt. Development only: refused in production (falls back to ``redacted``)
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "formwright.agent-run/1"
POLICY_ENV = "FW_RUN_RECORD_PROMPTS"
POLICIES = ("hash", "redacted", "raw")
EXCERPT_CHARS = 2000
RENDER_MAX_BYTES = 20_000_000  # a review sheet is ~0.2 MB; anything bigger is not kept for the comparison
KEEP_RUNS = 200  # per workspace; older records are pruned
_RUN_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")

_REDACT = [
    (re.compile(r"\n\n\[(?:Reference image|Recognition data|Selected)[^\]]*\][\s\S]*$"), " [attachment context removed]"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    (re.compile(r"\bhttps?://\S+", re.IGNORECASE), "[url]"),
    (re.compile(r"\b(?:sk|pk|rk|xox[abp])[-_][A-Za-z0-9_\-]{8,}\b"), "[key]"),
    (re.compile(r"\b[A-Za-z0-9+/_\-]{32,}={0,2}"), "[token]"),
    (re.compile(r"\+?\d(?:[\s\-()]{0,2}\d){8,}"), "[number]"),  # 9+ digits: phone / account numbers
]


def policy() -> str:
    p = (os.environ.get(POLICY_ENV) or "redacted").strip().lower()
    if p not in POLICIES:
        p = "redacted"
    if p == "raw":
        try:
            from aicad.platform.config import get_settings

            if get_settings().production:
                p = "redacted"
        except Exception:  # noqa: BLE001 - no settings: stay on the safe side
            p = "redacted"
    return p


def redact(text: str) -> str:
    """An excerpt safe to keep: contact details, links, secrets, long numbers and attachment payloads removed.
    Engineering numbers (dimensions such as 120 x 80 x 8) are short and stay."""
    for rx, rep in _REDACT:
        text = rx.sub(rep, text)
    return text[:EXCERPT_CHARS]


def prompt_entry(prompt: str, pol: str | None = None) -> dict[str, Any]:
    pol = pol or policy()
    out: dict[str, Any] = {"sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(), "chars": len(prompt),
                           "policy": pol}
    if pol == "redacted":
        out["excerpt"] = redact(prompt)
    elif pol == "raw":
        out["text"] = prompt
    return out


def _ver(*names: str) -> str | None:
    from importlib.metadata import PackageNotFoundError, version

    for n in names:
        try:
            return version(n)
        except PackageNotFoundError:
            continue
    return None


def versions() -> dict[str, Any]:
    try:
        from aicad.toolbox import VERSION as toolbox_version
    except Exception:  # noqa: BLE001
        toolbox_version = None
    return {"app": _ver("aicad") or "0", "python": platform.python_version(),
            "agent_sdk": _ver("claude-agent-sdk", "claude_agent_sdk"), "build123d": _ver("build123d"),
            "ocp": _ver("cadquery-ocp", "cadquery_ocp", "cadquery-ocp-novtk"), "toolbox": toolbox_version}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _usage_ints(u: dict[str, Any] | None) -> dict[str, int]:
    out = {}
    for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        v = (u or {}).get(k)
        out[k] = int(v) if isinstance(v, int | float) else 0
    return out


def _int(v: Any) -> int:
    return int(v) if isinstance(v, int | float) else 0


def _tool_result_size(b: Any) -> dict[str, int]:
    """Characters of text and number of images in one tool result (what the next model call has to read)."""
    c = b.content
    if isinstance(c, str):
        return {"text_chars": len(c), "images": 0}
    text, images = 0, 0
    for x in c or []:
        if isinstance(x, dict):
            if x.get("type") == "image":
                images += 1
            else:
                text += len(str(x.get("text") or ""))
    return {"text_chars": text, "images": images}


class CallLog:
    """Per model call (one API request of the agent harness): tokens by kind, wall time and the tools it asked for.

    Fed from the SDK's partial-message stream (``StreamEvent``: ``message_start`` carries the input and prompt-cache
    usage, ``message_delta`` the final output count, ``message_stop`` the end) and, when a client sends no stream
    events (replay, fakes, older CLIs), from the ``AssistantMessage`` usage snapshots, which miss most of the output.
    The run record and the session's live meter both price these numbers (agent-cost report)."""

    def __init__(self, clock: Any = time.perf_counter, t0: float | None = None) -> None:
        self.clock = clock
        self.t0 = clock() if t0 is None else t0
        self.calls: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self.streamed = False
        self._current: str | None = None

    def _call(self, mid: str, model: str | None) -> dict[str, Any]:
        c = self.calls.get(mid)
        if c is None:
            c = {"n": len(self.order) + 1, "id": mid, "model": model or "", "start_s": round(self.clock() - self.t0, 3),
                 "duration_s": None, "input_tokens": 0, "cache_write_1h": 0, "cache_write_5m": 0,
                 "cache_read_input_tokens": 0, "output_tokens": 0, "tools": [], "tool_results": []}
            self.calls[mid] = c
            self.order.append(mid)
        elif model and not c["model"]:
            c["model"] = model
        return c

    @staticmethod
    def _apply(c: dict[str, Any], u: Any) -> None:
        """Merge one usage report (largest value wins: reports of one call only grow)."""
        if not isinstance(u, dict):
            return
        for k in ("input_tokens", "cache_read_input_tokens", "output_tokens"):
            if k in u:
                c[k] = max(c[k], _int(u.get(k)))
        if "cache_creation_input_tokens" in u:
            cw = _int(u.get("cache_creation_input_tokens"))
            split = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
            one_h = min(_int(split.get("ephemeral_1h_input_tokens")), cw)
            c["cache_write_1h"] = max(c["cache_write_1h"], one_h)
            c["cache_write_5m"] = max(c["cache_write_5m"], cw - one_h)

    def stream(self, ev: dict[str, Any]) -> str | None:
        """One raw API stream event. Returns the id of the call whose usage changed."""
        t = ev.get("type")
        if t == "message_start":
            m = ev.get("message") or {}
            mid = str(m.get("id") or f"call{len(self.order) + 1}")
            self.streamed = True
            self._current = mid
            self._apply(self._call(mid, m.get("model")), m.get("usage"))
            return mid
        if t == "message_delta" and self._current:
            self._apply(self.calls[self._current], ev.get("usage"))
            return self._current
        if t == "message_stop" and self._current:
            c = self.calls[self._current]
            c["duration_s"] = round(self.clock() - self.t0 - c["start_s"], 3)
            self._current = None
        return None

    def message(self, mid: str | None, model: str | None, usage: Any, tools: list[str]) -> str:
        """An ``AssistantMessage`` (one content block of a call). Its usage counts only when no stream events came."""
        key = mid or f"m{len(self.order) + 1}"
        c = self._call(key, model)
        if not self.streamed:
            self._apply(c, usage)
        c["tools"].extend(tools)
        return key

    def tool_result(self, mid: str | None, name: str, size: dict[str, int]) -> None:
        c = self.calls.get(mid or "")
        if c is not None:
            c["tool_results"].append({"tool": name, **size})

    @staticmethod
    def usage_of(c: dict[str, Any]) -> dict[str, Any]:
        """A call's usage in the API's shape (for ``pricing.usage_cost_usd``)."""
        return {"input_tokens": c["input_tokens"], "output_tokens": c["output_tokens"],
                "cache_read_input_tokens": c["cache_read_input_tokens"],
                "cache_creation_input_tokens": c["cache_write_1h"] + c["cache_write_5m"],
                "cache_creation": {"ephemeral_1h_input_tokens": c["cache_write_1h"],
                                   "ephemeral_5m_input_tokens": c["cache_write_5m"]}}

    def cost(self, mid: str) -> float:
        from aicad.agent.pricing import usage_cost_usd

        c = self.calls[mid]
        return usage_cost_usd(c["model"], self.usage_of(c))

    def total_usd(self) -> float:
        return sum(self.cost(m) for m in self.order)

    def rows(self) -> list[dict[str, Any]]:
        out = []
        for mid in self.order:
            c = dict(self.calls[mid])
            c["context_tokens"] = (c["input_tokens"] + c["cache_write_1h"] + c["cache_write_5m"]
                                   + c["cache_read_input_tokens"])
            c["cost_usd"] = round(self.cost(mid), 6)
            out.append(c)
        return out

    def summary(self) -> dict[str, Any]:
        """Where the turn's cost went, by token kind (the agent-cost breakdown)."""
        from aicad.agent.pricing import usage_cost_usd

        rows = self.rows()
        tot = {k: sum(r[k] for r in rows) for k in ("input_tokens", "cache_write_1h", "cache_write_5m",
                                                     "cache_read_input_tokens", "output_tokens")}
        by_kind = {"input": 0.0, "cache_write": 0.0, "cache_read": 0.0, "output": 0.0}
        for r in rows:
            u = self.usage_of(r)
            by_kind["input"] += usage_cost_usd(r["model"], {"input_tokens": r["input_tokens"]})
            by_kind["cache_write"] += usage_cost_usd(r["model"], {k: u[k] for k in ("cache_creation_input_tokens",
                                                                                      "cache_creation")})
            by_kind["cache_read"] += usage_cost_usd(r["model"], {"cache_read_input_tokens": r["cache_read_input_tokens"]})
            by_kind["output"] += usage_cost_usd(r["model"], {"output_tokens": r["output_tokens"]})
        ctx = [r["context_tokens"] for r in rows]
        total_in = sum(ctx)
        return {"model_calls": len(rows), "source": "stream" if self.streamed else "messages", **tot,
                "context_tokens_max": max(ctx) if ctx else 0,
                "cache_hit_ratio": round(tot["cache_read_input_tokens"] / total_in, 4) if total_in else None,
                "cost_usd_by_kind": {k: round(v, 6) for k, v in by_kind.items()},
                "cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
                "tool_result_chars": sum(t["text_chars"] for r in rows for t in r["tool_results"]),
                "tool_result_images": sum(t["images"] for r in rows for t in r["tool_results"])}


class RunRecorder:
    """Collects one agent turn as the SDK messages stream past, then writes run.json."""

    def __init__(self, workspace: Path, *, prompt: str, mode: str, requested_model: str | None,
                 run_id: str | None = None, clock: Any = time.perf_counter, provider: str | None = None) -> None:
        self.workspace = Path(workspace)
        self.run_id = run_id if run_id and _RUN_ID.match(run_id) else uuid.uuid4().hex
        self.clock = clock
        self.t0 = clock()
        self.rec: dict[str, Any] = {
            "schema": SCHEMA, "run_id": self.run_id, "started_at": _now(), "finished_at": None, "mode": mode,
            "prompt": prompt_entry(prompt), "provider": provider,
            "model": {"requested": requested_model, "used": []},
            "versions": versions(), "agent": {}, "tokens": {}, "cost_usd": {}, "timings_s": {},
            "tools": {"calls": 0, "by_name": {}, "errors": 0, "builds": 0}, "builds": [], "checks": None,
            "calls": [], "cost_breakdown": None,
            "outcome": {}, "render_similarity": None}
        self._marks: dict[str, float] = {}
        self._open: dict[str, tuple[str, float]] = {}  # tool_use id -> (name, start)
        self._tool_time: dict[str, float] = {"build": 0.0, "other": 0.0}
        self._usage: dict[str, dict[str, int]] = {}  # message id -> max usage seen
        self._usage_model: dict[str, str] = {}
        self.calls = CallLog(clock, self.t0)  # per model call (agent-cost)
        self._tool_call: dict[str, str] = {}  # tool_use id -> the model call that asked for it
        self._result: dict[str, Any] | None = None
        self._render_before = self._read_render()

    def _read_render(self) -> bytes | None:
        try:
            f = self.workspace / "out" / "views.png"
            return f.read_bytes() if f.is_file() and f.stat().st_size <= RENDER_MAX_BYTES else None
        except OSError:
            return None

    def _render_similarity(self) -> dict[str, Any]:
        """EVAL-006 (advisory, never gating): the review render after the turn vs the one before it."""
        after = self._read_render()
        base = {"advisory": True, "gating": False, "basis": "review render before this turn"}
        if after is None:
            return {**base, "available": False, "reason": "no render after the turn"}
        if self._render_before is None:
            return {**base, "available": False, "reason": "no earlier render to compare with"}
        if after == self._render_before:
            return {**base, "available": True, "unchanged": True, "score": 1.0}
        try:
            import io

            from PIL import Image

            from aicad.eval import render_similarity

            with Image.open(io.BytesIO(self._render_before)) as a, Image.open(io.BytesIO(after)) as b:
                a.load()
                b.load()
                sim = render_similarity.compare_sheets(a, b)
        except Exception:  # noqa: BLE001 - telemetry never breaks a run
            return {**base, "available": False, "reason": "render unreadable"}
        return {**base, "available": True, "unchanged": False, **sim}

    # -------------------------------------------------------------- feeding
    def mark(self, phase: str) -> None:
        self._marks.setdefault(phase, self.clock() - self.t0)

    def observe(self, msg: Any) -> None:
        try:
            self._observe(msg)
        except Exception:  # noqa: BLE001,S110 - telemetry never breaks a run
            pass

    def _observe(self, msg: Any) -> None:
        from claude_agent_sdk import (
            AssistantMessage,
            ResultMessage,
            StreamEvent,
            SystemMessage,
            ToolResultBlock,
            ToolUseBlock,
            UserMessage,
        )

        now = self.clock()
        if isinstance(msg, StreamEvent):
            if msg.parent_tool_use_id is None and isinstance(msg.event, dict):
                self.calls.stream(msg.event)
            return
        if isinstance(msg, SystemMessage) and msg.subtype == "init":
            data = msg.data or {}
            self.rec["agent"] = {k: data.get(k) for k in ("claude_code_version", "apiKeySource", "model",
                                                           "permissionMode") if data.get(k) is not None}
        elif isinstance(msg, AssistantMessage):
            self.mark("first_response")
            if msg.model and msg.model not in self.rec["model"]["used"]:
                self.rec["model"]["used"].append(msg.model)
            if msg.usage:
                key = msg.message_id or f"m{len(self._usage)}"
                u = _usage_ints(msg.usage)
                prev = self._usage.get(key)
                if prev is None or sum(u.values()) >= sum(prev.values()):
                    self._usage[key] = u
                    self._usage_model[key] = msg.model or ""
            uses = [b for b in msg.content if isinstance(b, ToolUseBlock)]
            call = self.calls.message(msg.message_id, msg.model, msg.usage,
                                      [b.name.replace("mcp__cad__", "cad:") for b in uses])
            for b in uses:
                self._tool_call[b.id] = call
            for b in msg.content:
                if isinstance(b, ToolUseBlock):
                    name = b.name.replace("mcp__cad__", "cad:")
                    t = self.rec["tools"]
                    t["calls"] += 1
                    t["by_name"][name] = t["by_name"].get(name, 0) + 1
                    if "build_model" in b.name:
                        t["builds"] += 1
                    self._open[b.id] = (b.name, now)
        elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
            for b in msg.content:
                if not isinstance(b, ToolResultBlock):
                    continue
                name, start = self._open.pop(b.tool_use_id, ("", now))
                self.calls.tool_result(self._tool_call.pop(b.tool_use_id, None), name.replace("mcp__cad__", "cad:"),
                                       _tool_result_size(b))
                kind = "build" if "build_model" in name else "other"
                self._tool_time[kind] += max(0.0, now - start)
                if b.is_error:
                    self.rec["tools"]["errors"] += 1
                if kind == "build":
                    text = b.content if isinstance(b.content, str) else " ".join(
                        c.get("text", "") for c in (b.content or []) if isinstance(c, dict))
                    t = text.strip()
                    verdict = ("pass" if t.startswith("Overall gating checks: PASS") else
                               "fail" if t.startswith("Overall gating checks: FAIL") else
                               "error" if t.startswith("BUILD FAILED") or b.is_error else "unknown")
                    self.rec["builds"].append({"at_s": round(now - self.t0, 3), "result": verdict,
                                               "duration_s": round(max(0.0, now - start), 3)})
        elif isinstance(msg, ResultMessage):
            self.mark("result")
            self._result = {"subtype": msg.subtype, "is_error": bool(msg.is_error), "num_turns": msg.num_turns,
                            "duration_ms": msg.duration_ms, "duration_api_ms": msg.duration_api_ms,
                            "total_cost_usd_cumulative": msg.total_cost_usd, "usage": _usage_ints(msg.usage)
                            if msg.usage else None, "session_id": msg.session_id}

    # -------------------------------------------------------------- closing
    def _status(self) -> dict[str, Any] | None:
        try:
            st = json.loads((self.workspace / "out" / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(st, dict):
            return None
        checks = [c for c in st.get("checks") or [] if isinstance(c, dict)]
        return {"ok": bool(st.get("ok")), "build_id": st.get("build_id"), "error": bool(st.get("error")),
                "gating_failed": sorted(str(c.get("id")) for c in checks if c.get("gating", True) and not c.get("passed")),
                "results": {str(c.get("id")): bool(c.get("passed")) for c in checks},
                "fingerprint": st.get("fingerprint"), "features": len(st.get("features") or [])}

    def finish(self, *, failed: bool = False, budget_stopped: bool = False, run_cost_usd: float | None = None,
               meter_usd: float | None = None, build_id_before: Any = None) -> dict[str, Any]:
        from aicad.agent.pricing import usage_cost_usd

        total = self.clock() - self.t0
        rec = self.rec
        rec["finished_at"] = _now()
        msg_sum = {k: sum(u.get(k, 0) for u in self._usage.values()) for k in
                   ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
        res_usage = (self._result or {}).get("usage")
        rec["tokens"] = {**(res_usage or msg_sum), "source": "result" if res_usage else "messages",
                         "responses": len(self._usage), "per_response_sum": msg_sum}
        est = sum(usage_cost_usd(self._usage_model.get(k, ""), u) for k, u in self._usage.items())
        if self.calls.streamed:  # the stream has each call's final usage; the snapshots miss most of the output
            est = self.calls.total_usd()
        rec["calls"] = self.calls.rows()
        rec["cost_breakdown"] = self.calls.summary()
        rec["cost_usd"] = {"run": None if run_cost_usd is None else round(float(run_cost_usd), 6),
                           "estimate_from_usage": round(est, 6),
                           "meter": None if meter_usd is None else round(float(meter_usd), 6),
                           "note": "run = the agent's own report for this turn; estimate = public list prices"}
        r = self._result or {}
        rec["timings_s"] = {
            "total": round(total, 3), "connect": _r3(self._marks.get("connected")),
            "first_response": _r3(self._marks.get("first_response")), "builds": round(self._tool_time["build"], 3),
            "other_tools": round(self._tool_time["other"], 3),
            "model_api": round(r["duration_api_ms"] / 1000, 3) if r.get("duration_api_ms") else None,
            "agent_reported": round(r["duration_ms"] / 1000, 3) if r.get("duration_ms") else None}
        st = self._status()
        if st is not None:
            st["new_build"] = build_id_before is None or st.get("build_id") != build_id_before
        rec["checks"] = st
        status = ("failed" if failed else "stopped_budget" if budget_stopped else
                  "ok" if self._result and not r.get("is_error") else "error" if self._result else "stopped")
        try:
            rec["render_similarity"] = self._render_similarity()
        except Exception:  # noqa: BLE001 - telemetry never breaks a run
            rec["render_similarity"] = None
        rec["outcome"] = {"status": status, "result_subtype": r.get("subtype"), "is_error": r.get("is_error"),
                          "agent_turns": r.get("num_turns"), "budget_stopped": budget_stopped,
                          "agent_session": r.get("session_id"),
                          "verified": bool(st and st.get("ok") and st.get("new_build"))}
        return rec

    def write(self) -> Path | None:
        try:
            d = runs_dir(self.workspace) / self.run_id
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / "run.json.tmp"
            tmp.write_text(json.dumps(self.rec, indent=1, default=str), encoding="utf-8")
            os.replace(tmp, d / "run.json")
            prune(self.workspace)
            return d / "run.json"
        except OSError:
            return None


def _r3(v: float | None) -> float | None:
    return None if v is None else round(v, 3)


# ------------------------------------------------------------------ reading (admin only)
def runs_dir(workspace: Path) -> Path:
    return Path(workspace) / ".fw" / "runs"


def prune(workspace: Path, keep: int = KEEP_RUNS) -> None:
    import shutil

    d = runs_dir(workspace)
    runs = sorted((p for p in d.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime_ns) if d.is_dir() else []
    for p in runs[:-keep] if len(runs) > keep else []:
        shutil.rmtree(p, ignore_errors=True)


def load(workspace: Path, run_id: str) -> dict[str, Any] | None:
    if not _RUN_ID.match(run_id or ""):
        return None
    try:
        data = json.loads((runs_dir(workspace) / run_id / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def list_runs(workspace: Path, limit: int = 50) -> list[dict[str, Any]]:
    """Newest first, one summary line per run."""
    d = runs_dir(workspace)
    if not d.is_dir():
        return []
    out = []
    for p in d.iterdir():
        rec = load(workspace, p.name) if p.is_dir() else None
        if rec is None:
            continue
        out.append({"run_id": rec.get("run_id"), "started_at": rec.get("started_at"), "mode": rec.get("mode"),
                    "status": (rec.get("outcome") or {}).get("status"),
                    "verified": (rec.get("outcome") or {}).get("verified"),
                    "models": (rec.get("model") or {}).get("used"),
                    "tokens_in": (rec.get("tokens") or {}).get("input_tokens"),
                    "tokens_out": (rec.get("tokens") or {}).get("output_tokens"),
                    "cost_usd": (rec.get("cost_usd") or {}).get("run"),
                    "total_s": (rec.get("timings_s") or {}).get("total"),
                    "tool_calls": (rec.get("tools") or {}).get("calls")})
    out.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return out[:max(1, min(limit, KEEP_RUNS))]
