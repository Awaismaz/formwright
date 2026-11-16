"""One long-lived Claude Agent SDK session bound to a project workspace.

Auth (development): the SDK runs the Claude Code binary, which uses this PC's Claude Code login
when no ANTHROPIC_API_KEY is present. Production must switch to API-key auth (RISKS R-LIC-05).
"""

from __future__ import annotations

import asyncio
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


def _brief(d: dict[str, Any], limit: int = 160) -> str:
    if "file_path" in d:
        return Path(str(d["file_path"])).name
    s = ", ".join(f"{k}={str(v)[:60]}" for k, v in d.items() if k not in ("content", "new_string", "old_string"))
    return s[:limit]


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
        )

    def publish(self, ev: dict[str, Any]) -> None:
        ev.setdefault("t", time.time())
        if self.on_event is not None:
            self.on_event(ev)  # may enrich ev (e.g. tokens charged) before broadcast
        self.history.append(ev)
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
            client = await self.ensure_connected()
            await client.query(prompt)
            async for msg in client.receive_response():
                self._handle(msg)
        except Exception as e:  # noqa: BLE001 - surface every agent failure in the UI
            self.publish({"type": "error", "text": f"{type(e).__name__}: {e}"})
        finally:
            self.busy = False
            self.publish({"type": "busy", "value": False})

    def _handle(self, msg: Any) -> None:
        if isinstance(msg, SystemMessage) and msg.subtype == "init":
            self.auth = msg.data.get("apiKeySource")
            self.publish({"type": "system", "model": msg.data.get("model"),
                          "auth": "subscription login" if self.auth == "none" else f"API key ({self.auth})"})
        elif isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock) and b.text.strip():
                    self.publish({"type": "text", "text": b.text})
                elif isinstance(b, ToolUseBlock):
                    self.publish({"type": "tool", "id": b.id, "name": b.name.replace("mcp__cad__", ""),
                                  "brief": _brief(b.input)})
        elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
            for b in msg.content:
                if isinstance(b, ToolResultBlock):
                    text = ""
                    if isinstance(b.content, str):
                        text = b.content
                    elif isinstance(b.content, list):
                        text = " ".join(c.get("text", "") for c in b.content if isinstance(c, dict))
                    first = text.strip().splitlines()[0][:200] if text.strip() else ""
                    self.publish({"type": "tool_result", "id": b.tool_use_id,
                                  "is_error": bool(b.is_error), "brief": first})
        elif isinstance(msg, ResultMessage):
            self.session_id = msg.session_id
            self.publish({"type": "result", "subtype": msg.subtype, "turns": msg.num_turns,
                          "duration_s": round(msg.duration_ms / 1000, 1),
                          "cost_est_usd": msg.total_cost_usd, "auth": self.auth})

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
        self.publish({"type": "reset"})
