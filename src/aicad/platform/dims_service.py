"""Background mapping of design parameters to on-model dimensions (``aicad.dims``), per workspace.

Runs after a build, one worker request per parameter, so the build itself is never slower and an interactive edit
waits for at most one nudge. The result is ``out/dims.json`` stamped with the build it was made (or checked) for.
A newer build, or the design agent starting work, stops a pass; the next build or the viewer's request starts a
fresh one. The whole pass is bounded (``BUDGET_S``); parameters left over are reported as not mapped.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aicad import dims
from aicad.agent import worker

log = logging.getLogger("aicad.dims")
BUDGET_S = 90.0
_running: dict[str, asyncio.Task[None]] = {}
_again: set[str] = set()
_tasks: set[asyncio.Task[None]] = set()


def read(ws: Path) -> dict[str, Any] | None:
    f = ws / "out" / "dims.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except (OSError, ValueError):
        return None


def _status(ws: Path) -> dict[str, Any]:
    try:
        return json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(ws: Path, doc: dict[str, Any]) -> None:
    out = ws / "out"
    if not out.is_dir():
        return
    fd, tmp = tempfile.mkstemp(dir=out, suffix=".dims.tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), default=str)
    os.replace(tmp, out / "dims.json")


def running(ws: Path) -> bool:
    t = _running.get(str(ws))
    return t is not None and not t.done()


def schedule(org_id: str, ws: Path, busy: Callable[[], bool] | None = None) -> None:
    """Start a pass for this workspace's current build (or note that one is wanted after the running pass)."""
    key = str(ws)
    if running(ws):
        _again.add(key)
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    t = loop.create_task(_run(org_id, ws, busy or (lambda: False)))
    _running[key] = t
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def _run(org_id: str, ws: Path, busy: Callable[[], bool]) -> None:
    key = str(ws)
    try:
        for _ in range(3):  # a newer build during the pass: map that one instead (bounded)
            _again.discard(key)
            done = await run_pass(org_id, ws, busy)
            if done and key not in _again:
                break
    except Exception:
        log.exception("dimension mapping failed")
    finally:
        _running.pop(key, None)


async def run_pass(org_id: str, ws: Path, busy: Callable[[], bool]) -> bool:
    """Map (or re-check) the current build. False when it was stopped by a newer build or the agent."""
    st = _status(ws)
    build_id = st.get("build_id")
    script = ws / "model.py"
    if not st.get("fingerprint") or not script.is_file() or busy():
        return True
    prev = read(ws)
    if prev and prev.get("build_id") == build_id:
        return True
    t0 = time.perf_counter()
    b = await worker.dims_base(org_id, script, ws / "out" / "dims.json" if prev else None)
    if not b.get("ok"):
        if b.get("starting"):
            return True  # the engine is starting: the viewer's next request tries again
        _write(ws, {"format": dims.FORMAT, "build_id": build_id, "dims": [], "error": "mapping failed"})
        return True
    if _status(ws).get("build_id") != build_id:
        return False
    if b.get("valid"):
        _write(ws, {**(prev or {}), "build_id": build_id, "checked_s": round(time.perf_counter() - t0, 3)})
        return True
    records: list[dict[str, Any]] = []
    for item in b.get("plan") or []:
        if busy() or _status(ws).get("build_id") != build_id:
            return False
        if time.perf_counter() - t0 > BUDGET_S:
            records.append({"param": item["param"], "kind": "none", "reason": "time"})
            continue
        r = await worker.dims_step(org_id, script, item, b["key"])
        records.append(r.get("dim") or {"param": item["param"], "kind": "none", "reason": "rebuild"})
    if _status(ws).get("build_id") != build_id:
        return False
    _write(ws, dims.document(b, records, build_id, t0))
    return True
