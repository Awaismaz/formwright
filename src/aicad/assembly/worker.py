"""Warm assembly worker: a long-lived process with the CAD kernel loaded (the web process never imports it).

Only Formwright's own assembly code runs here, on verified part snapshots; no user script is executed.

Protocol (one JSON object per line):
  parent -> worker  {"op": "prepare" | "interference" | "clearance" | "probe" | "export", ...}
  worker -> parent  {"ok": bool, "rc": int, "error": str | None, "result": {...}, "elapsed_s": float}
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from aicad.agent.worker import Worker, child_env


def _handle(req: dict[str, Any]) -> Any:
    from aicad.assembly import geometry

    op = req.get("op")
    if op == "prepare":
        return geometry.prepare(Path(req["dest"]), step=req.get("step"), toolbox_spec=req.get("toolbox"))
    if op == "interference":
        return geometry.interference(req["instances"])
    if op == "clearance":
        return geometry.clearance(req["instances"], [tuple(p) for p in req.get("pairs", [])],
                                  float(req.get("near_mm", 10.0)))
    if op == "analyse":
        inter = geometry.interference(req["instances"])
        clear = geometry.clearance(req["instances"], [tuple(p) for p in req.get("pairs", [])],
                                   float(req.get("near_mm", 10.0)))
        return {"interference": inter, "clearance": clear}
    if op == "probe":
        return [geometry.probe(req["instances"], t) for t in req["targets"]]
    if op == "export":
        return geometry.export(Path(req["dest"]), req["name"], req["nodes"])
    raise ValueError(f"unknown op {op}")


def serve() -> None:
    proto = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    import build123d  # noqa: F401  (warm the kernel)

    from aicad.assembly import geometry  # noqa: F401

    proto.write(json.dumps({"ready": True}) + "\n")
    for line in sys.stdin:
        t0 = time.perf_counter()
        try:
            resp: dict[str, Any] = {"ok": True, "rc": 0, "result": _handle(json.loads(line))}
        except Exception as e:  # noqa: BLE001 - report, keep serving
            resp = {"ok": False, "rc": 1, "error": f"{type(e).__name__}: {e}"}
        resp["elapsed_s"] = round(time.perf_counter() - t0, 3)
        proto.write(json.dumps(resp) + "\n")


class AssemblyWorker(Worker):
    async def _start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-m", "aicad.assembly.worker", env=child_env(),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=64 * 1024 * 1024)
        self.jobs = 0
        assert self.proc.stdout is not None
        line = await asyncio.wait_for(self.proc.stdout.readline(), 120)
        if not line:
            raise RuntimeError("assembly worker failed to start")


_workers: dict[str, AssemblyWorker] = {}


def get_worker(key: str) -> AssemblyWorker:
    w = _workers.get(key)
    if w is None:
        w = _workers[key] = AssemblyWorker()
    return w


async def call(key: str, req: dict[str, Any], timeout: float = 180) -> dict[str, Any]:
    return await get_worker(key).request(req, timeout)


async def shutdown_all() -> None:
    """Stop every worker from inside the event loop that started it (clean pipe shutdown)."""
    for w in list(_workers.values()):
        await w.stop()
    _workers.clear()


def kill_all() -> None:
    for w in list(_workers.values()):
        if w.proc is not None and w.proc.returncode is None:
            try:
                w.proc.kill()
            except ProcessLookupError:
                pass
        w.proc = None
    _workers.clear()


if __name__ == "__main__":
    serve()
