"""Warm assembly worker: a long-lived process with the CAD kernel loaded (the web process never imports it).

Only Formwright's own assembly code runs here, on verified part snapshots; no user script is executed.

Protocol (one JSON object per line):
  parent -> worker  {"op": "prepare" | "interference" | "clearance" | "motion" | "probe" | "export", ...}
  worker -> parent  {"ok": bool, "rc": int, "error": str | None, "result": {...}, "elapsed_s": float}
"""

from __future__ import annotations

import asyncio
import atexit
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from aicad.agent.worker import MAX_LIVE, Worker, child_env, evict_idle


def _handle(req: dict[str, Any]) -> Any:
    from aicad.assembly import geometry

    op = req.get("op")
    if op == "prepare":
        return geometry.prepare(Path(req["dest"]), step=req.get("step"), toolbox_spec=req.get("toolbox"))
    if op == "placeholder":  # CD-011: envelope solid with interface features, then the usual snapshot
        from aicad.assembly import placeholder

        dest = Path(req["dest"])
        src = placeholder.write(dest / "source.step", req["spec"])
        return geometry.prepare(dest, step=str(src))
    if op == "ping":
        return {"warm": True}
    if op == "interference":
        return geometry.interference(req["instances"], only=req.get("only"))
    if op == "clearance":
        return geometry.clearance(req["instances"], [tuple(p) for p in req.get("pairs", [])],
                                  float(req.get("near_mm", 10.0)))
    if op == "analyse":
        inter = geometry.interference(req["instances"])
        hits = {(p["a"], p["b"]): p["center"] for p in inter["pairs"]}  # overlapping pairs: distance 0
        clear = geometry.clearance(req["instances"], [tuple(p) for p in req.get("pairs", [])],
                                   float(req.get("near_mm", 10.0)), overlaps=hits)
        return {"interference": inter, "clearance": clear}
    if op == "pairs":  # ASM-023: uncached pairs only, each in its own frame (the caller caches the results)
        return geometry.pair_jobs(req["jobs"], float(req.get("vol_tol", 1e-6)))
    if op == "motion":  # ASM-011: collisions per step of a joint sweep
        from aicad.assembly import motion

        return motion.sweep(req["instances"], req.get("body") or {}, req["steps"],
                            float(req.get("vol_tol", motion.VOL_TOL)))
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
    # the warm process keeps imported snapshots (bounded LRU); pair checks come in chunks, so don't recycle it as
    # often as a build worker that runs user scripts
    max_jobs = 400

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
        evict_idle(_workers, keep=max(0, MAX_LIVE - 1))
        w = _workers[key] = AssemblyWorker()
    return w


async def call(key: str, req: dict[str, Any], timeout: float = 180) -> dict[str, Any]:
    return await get_worker(key).request(req, timeout)


async def shutdown_all() -> None:
    """Stop every worker from inside the event loop that started it (clean pipe shutdown)."""
    loop = asyncio.get_running_loop()
    for w in list(_workers.values()):
        if getattr(w, "_loop", None) in (None, loop):
            await w.stop()
        elif w.proc is not None and w.proc.returncode is None:  # started by another (possibly closed) loop
            try:
                w.proc.kill()
            except ProcessLookupError:
                pass
            w.proc = None
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


atexit.register(kill_all)


if __name__ == "__main__":
    serve()
