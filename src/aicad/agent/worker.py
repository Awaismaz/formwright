"""Warm build worker: a long-lived process with build123d/OCCT (and VTK, lazily) already loaded.

Removes ~3-5 s of interpreter + CAD-kernel start-up from every build. One worker per key (workspace /
organization), recycled every MAX_JOBS builds, on timeout and on crash. Requests are serialized per worker.

This is a performance measure, NOT a security boundary: model scripts still run as Python in this
process (same guarantees as before: secret-free env, import tripwire, timeout). See RISKS R-SEC-05.

Protocol (one JSON object per line):
  parent -> worker  {"op": "build", "script": str, "out": str, "determinism": bool}
                    {"op": "render", "stl": str, "png": str, "title": str}
  worker -> parent  {"ok": bool, "rc": int, "error": str | None, "elapsed_s": float}
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

MAX_JOBS = 25
_SAFE_ENV_KEYS = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE",
                  "HOMEPATH", "LOCALAPPDATA", "APPDATA", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE")


def child_env() -> dict[str, str]:
    return {k: os.environ[k] for k in _SAFE_ENV_KEYS if k in os.environ}


# ----------------------------------------------------------------------------- worker side
def _diff(a_step: Path, b_step: Path, out: Path) -> dict[str, Any]:
    """Material added (b - a) and removed (a - b) between two STEP files, exported as topology for the viewer."""
    from build123d import import_step

    from aicad.topo import export_topology

    out.mkdir(parents=True, exist_ok=True)
    a, b = import_step(str(a_step)), import_step(str(b_step))
    res: dict[str, Any] = {}
    for name, shape in (("added", b - a), ("removed", a - b)):
        vol = float(getattr(shape, "volume", 0.0) or 0.0)
        f = out / f"{name}.json"
        if vol > 1e-6 and shape.solids():
            export_topology(shape, f)
        elif f.exists():
            f.unlink()
        res[f"{name}_mm3"] = round(vol, 3)
    return res


def serve() -> None:
    proto = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)  # anything a model script prints goes to stderr, never into the protocol stream
    sys.stdout = sys.stderr
    import build123d  # noqa: F401  (warm the CAD kernel once)

    from aicad.agent import runner

    proto.write(json.dumps({"ready": True}) + "\n")
    for line in sys.stdin:
        try:
            req = json.loads(line)
            t0 = time.perf_counter()
            if req["op"] == "build":
                rc = runner.main(Path(req["script"]), Path(req["out"]), determinism=bool(req.get("determinism", True)),
                                 fast=bool(req.get("fast", False)))
                resp: dict[str, Any] = {"ok": True, "rc": rc}
            elif req["op"] == "recognize":
                from aicad.recognize import recognize

                ns = runner._exec(Path(req["script"]), use_cache=True)
                rec = recognize(ns["result"])
                Path(req["out"]).write_text(json.dumps(rec), encoding="utf-8")
                resp = {"ok": True, "rc": 0}
            elif req["op"] == "finalize":
                resp = {"ok": True, "rc": runner.finalize(Path(req["out"]))}
            elif req["op"] == "diff":
                resp = {"ok": True, "rc": 0, **_diff(Path(req["a"]), Path(req["b"]), Path(req["out"]))}
            elif req["op"] == "render":
                from aicad.agent.render import render

                render(Path(req["stl"]), Path(req["png"]), req.get("title", ""))
                resp = {"ok": True, "rc": 0}
            else:
                resp = {"ok": False, "rc": 2, "error": f"unknown op {req.get('op')}"}
            resp["elapsed_s"] = round(time.perf_counter() - t0, 3)
        except Exception as e:  # noqa: BLE001 - report, keep serving
            resp = {"ok": False, "rc": 1, "error": f"{type(e).__name__}: {e}"}
        proto.write(json.dumps(resp) + "\n")


# ----------------------------------------------------------------------------- parent side
class Worker:
    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.jobs = 0
        self.lock = asyncio.Lock()

    async def _start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-m", "aicad.agent.worker", env=child_env(),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        self.jobs = 0
        assert self.proc.stdout is not None
        line = await asyncio.wait_for(self.proc.stdout.readline(), 120)
        if not line:
            raise RuntimeError("build worker failed to start")

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()
        self.proc = None

    async def request(self, req: dict[str, Any], timeout: float) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        if getattr(self, "_loop", None) is not loop:  # process pipes are bound to the loop that created them
            self._loop = loop
            self.lock = asyncio.Lock()
            if self.proc is not None and self.proc.returncode is None:
                try:
                    self.proc.kill()
                except ProcessLookupError:
                    pass
            self.proc = None
        async with self.lock:
            if self.proc is None or self.proc.returncode is not None or self.jobs >= MAX_JOBS:
                await self.stop()
                await self._start()
            assert self.proc and self.proc.stdin and self.proc.stdout
            self.jobs += 1
            try:
                self.proc.stdin.write((json.dumps(req) + "\n").encode())
                await self.proc.stdin.drain()
                line = await asyncio.wait_for(self.proc.stdout.readline(), timeout)
            except (TimeoutError, ConnectionError, BrokenPipeError):
                await self.stop()
                return {"ok": False, "rc": -1, "error": f"timed out after {timeout:.0f} s"}
            if not line:
                await self.stop()
                return {"ok": False, "rc": -1, "error": "build worker crashed"}
            return json.loads(line)


_workers: dict[str, Worker] = {}


def get_worker(key: str) -> Worker:
    w = _workers.get(key)
    if w is None:
        w = _workers[key] = Worker()
    return w


async def build(key: str, script: Path, out: Path, determinism: bool = True, timeout: float = 180,
                fast: bool = False) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    return await get_worker(key).request({"op": "build", "script": str(script), "out": str(out),
                                          "determinism": determinism, "fast": fast}, timeout)


async def recognize(key: str, script: Path, out: Path, timeout: float = 300) -> dict[str, Any]:
    return await get_worker(key).request({"op": "recognize", "script": str(script), "out": str(out)}, timeout)


async def finalize(key: str, out: Path, timeout: float = 180) -> dict[str, Any]:
    return await get_worker(key).request({"op": "finalize", "out": str(out)}, timeout)


async def render(key: str, stl: Path, png: Path, title: str = "", timeout: float = 60) -> dict[str, Any]:
    return await get_worker(key).request({"op": "render", "stl": str(stl), "png": str(png), "title": title}, timeout)


async def diff(key: str, a_step: Path, b_step: Path, out: Path, timeout: float = 180) -> dict[str, Any]:
    return await get_worker(key).request({"op": "diff", "a": str(a_step), "b": str(b_step), "out": str(out)}, timeout)


async def shutdown_all() -> None:
    for w in list(_workers.values()):
        await w.stop()
    _workers.clear()


if __name__ == "__main__":
    serve()
