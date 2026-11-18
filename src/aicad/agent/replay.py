"""Recorded / replayed design-agent turns (AGT-002): CI and demos with zero paid model calls.

A *cassette* is a JSON file holding agent turns::

    {"version": 1, "note": "...", "turns": [
       {"match": "regex on the prompt (optional)",
        "messages": [{"type": "system" | "assistant" | "user" | "result", ...}],
        "files": {"model.py": "<text>", "out/status.json": {"b64": "..."}},
        "rebuild": true}]}

- ``RecordingClient`` wraps the real SDK client, stores every message of each turn (rendered images dropped) plus the
  workspace's design files afterwards. Enable with ``FW_AGENT_RECORD=<file or folder>``.
- ``ReplayClient`` stands in for the SDK client: ``query`` picks the first unused turn whose ``match`` fits the prompt
  (turns without ``match`` are used in order), ``receive_response`` yields the recorded messages as real SDK objects.
  When a recorded build result arrives, the turn's files are written into the workspace; with ``rebuild`` the real
  build runs on them and its fresh check report replaces the recorded one, so a replay still exercises the geometry
  pipeline. Enable with ``FW_AGENT_REPLAY=<file or folder>`` (development only; refused in production).

Nothing here talks to a model.
"""

from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

RECORD_ENV, REPLAY_ENV = "FW_AGENT_RECORD", "FW_AGENT_REPLAY"
DESIGN_FILES = ("*.py", "out/status.json")


# ------------------------------------------------------------------ (de)serialisation
def _block_to_dict(b: Any) -> dict[str, Any] | None:
    if isinstance(b, TextBlock):
        return {"type": "text", "text": b.text}
    if isinstance(b, ToolUseBlock):
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    if isinstance(b, ToolResultBlock):
        c = b.content
        if isinstance(c, list):  # keep the text, drop rendered images (large, and re-made on rebuild)
            c = [x if not (isinstance(x, dict) and x.get("type") == "image") else {"type": "text", "text": "(image)"}
                 for x in c]
        return {"type": "tool_result", "tool_use_id": b.tool_use_id, "content": c, "is_error": b.is_error}
    return None  # thinking blocks etc. are not replayed


def message_to_dict(msg: Any) -> dict[str, Any] | None:
    if isinstance(msg, SystemMessage):
        return {"type": "system", "subtype": msg.subtype,
                "data": {"apiKeySource": (msg.data or {}).get("apiKeySource")}}  # no paths or tool lists
    if isinstance(msg, AssistantMessage):
        return {"type": "assistant", "model": msg.model, "usage": msg.usage, "message_id": msg.message_id,
                "content": [d for d in map(_block_to_dict, msg.content) if d]}
    if isinstance(msg, UserMessage):
        c = msg.content if isinstance(msg.content, str) else [d for d in map(_block_to_dict, msg.content) if d]
        return {"type": "user", "content": c}
    if isinstance(msg, ResultMessage):
        return {"type": "result", "subtype": msg.subtype, "duration_ms": msg.duration_ms,
                "duration_api_ms": msg.duration_api_ms, "is_error": msg.is_error, "num_turns": msg.num_turns,
                "session_id": msg.session_id, "total_cost_usd": msg.total_cost_usd, "usage": msg.usage}
    return None


def _block_from_dict(d: dict[str, Any]) -> Any:
    t = d.get("type")
    if t == "text":
        return TextBlock(text=d.get("text", ""))
    if t == "tool_use":
        return ToolUseBlock(id=d["id"], name=d["name"], input=d.get("input") or {})
    if t == "tool_result":
        return ToolResultBlock(tool_use_id=d["tool_use_id"], content=d.get("content"), is_error=d.get("is_error"))
    raise ValueError(f"unknown block type {t!r}")


def message_from_dict(d: dict[str, Any]) -> Any:
    t = d.get("type")
    if t == "system":
        return SystemMessage(subtype=d.get("subtype", "init"), data=d.get("data") or {})
    if t == "assistant":
        return AssistantMessage(content=[_block_from_dict(b) for b in d.get("content", [])],
                                model=d.get("model") or "replay", usage=d.get("usage"),
                                message_id=d.get("message_id"))
    if t == "user":
        c = d.get("content")
        return UserMessage(content=c if isinstance(c, str) else [_block_from_dict(b) for b in c or []])
    if t == "result":
        return ResultMessage(subtype=d.get("subtype", "success"), duration_ms=int(d.get("duration_ms") or 0),
                             duration_api_ms=int(d.get("duration_api_ms") or 0), is_error=bool(d.get("is_error")),
                             num_turns=int(d.get("num_turns") or 1), session_id=d.get("session_id") or "replay",
                             total_cost_usd=d.get("total_cost_usd"), usage=d.get("usage"))
    raise ValueError(f"unknown message type {t!r}")


def load_cassette(path: Path) -> dict[str, Any]:
    """A cassette file, or every ``*.json`` cassette in a folder (turns concatenated in name order)."""
    path = Path(path)
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    turns: list[dict[str, Any]] = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        turns += data.get("turns", []) if isinstance(data, dict) else []
    return {"version": 1, "turns": turns, "render": bool(os.environ.get("FW_AGENT_REPLAY_RENDER"))}


def snapshot_files(workspace: Path, patterns: tuple[str, ...] = DESIGN_FILES) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for pat in patterns:
        for p in sorted(workspace.glob(pat)):
            if p.is_file():
                rel = p.relative_to(workspace).as_posix()
                try:
                    out[rel] = p.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    out[rel] = {"b64": base64.b64encode(p.read_bytes()).decode("ascii")}
    return out


def write_files(workspace: Path, files: dict[str, Any]) -> list[str]:
    """Write a turn's files into the workspace (paths must stay inside it)."""
    root = workspace.resolve()
    written: list[str] = []
    for rel, content in (files or {}).items():
        dest = (root / rel).resolve()
        if root not in dest.parents:
            raise ValueError(f"cassette file outside the workspace: {rel}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, dict) and "b64" in content:
            dest.write_bytes(base64.b64decode(content["b64"]))
        else:
            dest.write_text(str(content), encoding="utf-8")
        written.append(rel)
    return written


# ------------------------------------------------------------------ clients
class ReplayClient:
    """Drop-in for ``ClaudeSDKClient`` that plays recorded turns. Zero model calls."""

    def __init__(self, options: Any, cassette: dict[str, Any] | Path | str, worker_key: str = "replay") -> None:
        self.options = options
        self.worker_key = worker_key  # one warm build worker shared by all replays
        self.workspace = Path(getattr(options, "cwd", None) or ".").resolve()
        self.cassette = cassette if isinstance(cassette, dict) else load_cassette(Path(cassette))
        self.used: set[int] = set()
        self.prompts: list[str] = []
        self._turn: dict[str, Any] | None = None
        self._stop = False

    async def connect(self, prompt: Any = None) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def interrupt(self) -> None:
        self._stop = True

    def _pick(self, prompt: str) -> dict[str, Any]:
        turns = self.cassette.get("turns", [])
        for want_match in (True, False):
            for i, t in enumerate(turns):
                if i in self.used or bool(t.get("match")) is not want_match:
                    continue
                if want_match and not re.search(t["match"], prompt, re.DOTALL | re.IGNORECASE):
                    continue
                self.used.add(i)
                return t
        return {"messages": [
            {"type": "assistant", "model": "replay",
             "content": [{"type": "text", "text": "No recorded response matches this request (replay mode)."}]},
            {"type": "result", "subtype": "success", "num_turns": 1, "session_id": "replay", "total_cost_usd": 0.0}]}

    async def query(self, prompt: str, session_id: str = "default") -> None:
        self.prompts.append(prompt)
        self._turn, self._stop = self._pick(prompt), False

    async def _build(self) -> str | None:
        """Run the real build on the replayed design (fresh checks). Returns the check report, or None."""
        from aicad.agent import worker
        from aicad.agent.tools import BUILD_TIMEOUT_S, summarize

        script, out = self.workspace / "model.py", self.workspace / "out"
        if not script.is_file():
            return None
        out.mkdir(parents=True, exist_ok=True)
        await worker.build(self.worker_key, script, out, determinism=True, timeout=BUILD_TIMEOUT_S)
        try:
            status = json.loads((out / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if self.cassette.get("render") and (out / "part.stl").is_file():  # thumbnails for demos (slower)
            await worker.render(self.worker_key, out / "part.stl", out / "views.png", str(status.get("part", "")))
        return summarize(status)

    async def receive_response(self) -> AsyncIterator[Any]:
        turn = self._turn or {"messages": []}
        builds: set[str] = set()
        wrote = False
        for d in turn.get("messages", []):
            if self._stop and d.get("type") != "result":
                continue
            if d.get("type") == "assistant":
                builds |= {b["id"] for b in d.get("content", []) if b.get("type") == "tool_use"
                           and "build_model" in b.get("name", "")}
            if d.get("type") == "user" and isinstance(d.get("content"), list):
                for b in d["content"]:
                    if b.get("type") == "tool_result" and b.get("tool_use_id") in builds:
                        if not wrote:
                            write_files(self.workspace, turn.get("files") or {})
                            wrote = True
                        if turn.get("rebuild"):
                            report = await self._build()
                            if report is not None:
                                b = dict(b, content=[{"type": "text", "text": report}],
                                         is_error=report.startswith("BUILD FAILED"))
                                d = dict(d, content=[b if x.get("tool_use_id") == b["tool_use_id"] else x
                                                     for x in d["content"]])
            yield message_from_dict(d)
        if not wrote and turn.get("files"):
            write_files(self.workspace, turn["files"])


class RecordingClient:
    """Wraps the real SDK client and appends each turn to a cassette file."""

    def __init__(self, options: Any, path: Path | str) -> None:
        from claude_agent_sdk import ClaudeSDKClient

        self.inner = ClaudeSDKClient(options=options)
        self.workspace = Path(getattr(options, "cwd", None) or ".").resolve()
        p = Path(path)
        self.path = p / f"{self.workspace.name}.json" if p.is_dir() or not p.suffix else p
        self._prompt = ""

    async def connect(self, prompt: Any = None) -> None:
        await self.inner.connect()

    async def disconnect(self) -> None:
        await self.inner.disconnect()

    async def interrupt(self) -> None:
        await self.inner.interrupt()

    async def query(self, prompt: str, session_id: str = "default") -> None:
        self._prompt = prompt
        await self.inner.query(prompt)

    async def receive_response(self) -> AsyncIterator[Any]:
        msgs: list[dict[str, Any]] = []
        try:
            async for m in self.inner.receive_response():
                d = message_to_dict(m)
                if d:
                    msgs.append(d)
                yield m
        finally:
            self._save(msgs)

    def _save(self, msgs: list[dict[str, Any]]) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {"version": 1}
        except (OSError, ValueError):
            data = {"version": 1}
        data.setdefault("turns", []).append({"prompt": self._prompt[:2000], "messages": msgs,
                                             "files": snapshot_files(self.workspace), "rebuild": True})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")


def make_client(options: Any) -> Any:
    """The agent client for a session: replay or record when asked (development only), else the real SDK client."""
    from claude_agent_sdk import ClaudeSDKClient

    replay, record = os.environ.get(REPLAY_ENV), os.environ.get(RECORD_ENV)
    if replay or record:
        from aicad.platform.config import get_settings

        if get_settings().production:
            raise RuntimeError("agent replay/recording is development-only")
        if replay:
            return ReplayClient(options, Path(replay))
        return RecordingClient(options, Path(record or "."))
    return ClaudeSDKClient(options=options)


ClientFactory = Callable[[Any], Any]
