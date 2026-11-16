"""AI CAD Studio: chat-driven agent + live viewer, served on 127.0.0.1 only."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from aicad.agent.session import AgentSession

STATIC = Path(__file__).resolve().parents[1] / "viewer" / "static"
ALLOWED = {"model.glb": "model/gltf-binary", "status.json": "application/json",
           "part.step": "application/step", "part.stl": "model/stl", "views.png": "image/png"}
DOWNLOADS = {"part.step", "part.stl"}


def use_subscription_auth() -> list[str]:
    """Development mode: strip API credentials so the Claude Code login is used (no API billing)."""
    removed = [k for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN") if os.environ.pop(k, None)]
    return removed


class Chat(BaseModel):
    prompt: str


def create_app(session: AgentSession) -> FastAPI:
    app = FastAPI(title="AI CAD Studio", docs_url=None, redoc_url=None)
    tasks: set[asyncio.Task[None]] = set()

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/files/{name}")
    async def files(name: str) -> FileResponse:
        if name not in ALLOWED:
            raise HTTPException(404)
        f = session.out_dir / name
        if not f.is_file():
            raise HTTPException(404)
        headers = {"Cache-Control": "no-store"}
        if name in DOWNLOADS:
            headers["Content-Disposition"] = f'attachment; filename="{name}"'
        return FileResponse(f, media_type=ALLOWED[name], headers=headers)

    @app.get("/api/state")
    async def state() -> dict[str, Any]:
        return {"agent": True, "busy": session.busy, "workspace": session.workspace.name,
                "auth": session.auth}

    @app.post("/api/chat")
    async def chat(body: Chat) -> dict[str, Any]:
        text = body.prompt.strip()
        if not text:
            raise HTTPException(400, "empty prompt")
        if len(text) > 20000:
            raise HTTPException(413, "prompt too long")
        if session.busy:
            raise HTTPException(409, "agent is busy")
        t = asyncio.create_task(session.send(text))
        tasks.add(t)
        t.add_done_callback(tasks.discard)
        return {"accepted": True}

    @app.post("/api/interrupt")
    async def interrupt() -> dict[str, Any]:
        await session.interrupt()
        return {"ok": True}

    @app.post("/api/reset")
    async def reset() -> dict[str, Any]:
        await session.reset()
        return {"ok": True}

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        backlog = list(session.history)
        session.subscribers.add(q)

        async def gen():  # type: ignore[no-untyped-def]
            try:
                yield f"data: {json.dumps({'type': 'hello', 'busy': session.busy})}\n\n"
                for ev in backlog:
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
                while True:
                    try:
                        ev = await asyncio.wait_for(q.get(), 15)
                        yield f"data: {json.dumps(ev, default=str)}\n\n"
                    except TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                session.subscribers.discard(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store"})

    return app
