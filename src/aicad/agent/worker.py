"""Warm build worker: a long-lived process with build123d/OCCT (and VTK, lazily) already loaded.

Removes ~3-5 s of interpreter + CAD-kernel start-up from every build. One worker per key (workspace /
organization), recycled every MAX_JOBS builds, on timeout and on crash. Requests are serialized per worker.

This is a performance measure, NOT a security boundary: model scripts still run as Python in this
process (same guarantees as before: secret-free env, import tripwire, timeout). See RISKS R-SEC-05.

Protocol (one JSON object per line; every request carries an "id" that its reply echoes):
  worker -> parent  {"ready": true}                                       once, after start-up
  parent -> worker  {"id": int, "op": "build", "script": str, "out": str, "determinism": bool}
                    {"id": int, "op": "render", "stl": str, "png": str, "title": str}
                    {"id": int, "op": "finalize", "out": str, "stage": "exports" | "determinism" | "all"}
  worker -> parent  {"id": int, "ok": bool, "rc": int, "error": str | None, "elapsed_s": float}

The parent drops any line whose id doesn't match the request it is waiting for (a late "ready", or the reply to a
request that already timed out), and a worker that is slow to start or times out is killed, never reused (STU-04).
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
            elif req["op"] == "dims_base":  # viewport dimensions (aicad.dims): face table + plan of nudges
                from aicad import dims

                prev = None
                if req.get("prev") and Path(req["prev"]).is_file():
                    try:
                        prev = json.loads(Path(req["prev"]).read_text(encoding="utf-8"))
                    except ValueError:
                        prev = None
                resp = {"ok": True, "rc": 0, **dims.base(Path(req["script"]), prev)}
            elif req["op"] == "dims_step":  # one parameter's nudged rebuild, classified
                from aicad import dims

                resp = {"ok": True, "rc": 0, "dim": dims.step(Path(req["script"]), req["key"], req["param"],
                                                               float(req["value"]), bool(req["is_int"]),
                                                               [float(d) for d in req["deltas"]])}
            elif req["op"] == "finalize":
                resp = {"ok": True, "rc": runner.finalize(Path(req["out"]), str(req.get("stage") or "all"))}
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
        try:
            resp["id"] = json.loads(line).get("id")
        except (ValueError, AttributeError):
            resp["id"] = None
        proto.write(json.dumps(resp) + "\n")


# ----------------------------------------------------------------------------- parent side
STARTING = "The geometry engine is starting up. Try again in a moment."


class WorkerUnavailable(RuntimeError):
    """The build worker could not be started (slow machine, crash). Plain message, safe to show."""


class Worker:
    START_TIMEOUT_S = 180.0  # a cold start on a loaded machine can take minutes
    max_jobs = MAX_JOBS

    def __init__(self, cmd: list[str] | None = None) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.jobs: float = 0
        self.lock = asyncio.Lock()
        self.cmd = cmd or [sys.executable, "-I", "-m", "aicad.agent.worker"]
        self._seq = 0

    async def _start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            *self.cmd, env=child_env(),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        self.jobs = 0
        assert self.proc.stdout is not None
        try:
            line = await asyncio.wait_for(self.proc.stdout.readline(), self.START_TIMEOUT_S)
            if not line or not json.loads(line).get("ready"):
                raise WorkerUnavailable(STARTING)
        except (TimeoutError, ValueError, WorkerUnavailable):
            await self.stop()  # never reuse a half-started worker: its late "ready" would be read as a reply
            raise WorkerUnavailable(STARTING) from None

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
            await self.proc.wait()
        self.proc = None

    async def warm(self) -> None:
        """Start the worker ahead of the first build (the Studio calls this when a project opens)."""
        async with self._guard():
            if self.proc is None or self.proc.returncode is not None:
                await self._start()

    def _guard(self) -> asyncio.Lock:
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
        return self.lock

    async def request(self, req: dict[str, Any], timeout: float, weight: float = 1.0) -> dict[str, Any]:
        """weight: how much the request counts towards recycling the worker (a dimension-mapping nudge is a
        fraction of a build: counting it fully would restart the warm worker every few edits)."""
        async with self._guard():
            try:
                # a finalize needs the shape the previous build left in this process: never recycle right before it
                recycle = self.jobs >= self.max_jobs and req.get("op") != "finalize"
                if self.proc is None or self.proc.returncode is not None or recycle:
                    await self.stop()
                    await self._start()
            except (WorkerUnavailable, OSError, RuntimeError, TimeoutError):
                await self.stop()  # also for subclasses with their own _start: never keep a half-started worker
                return {"ok": False, "rc": -1, "error": STARTING, "starting": True}
            assert self.proc and self.proc.stdin and self.proc.stdout
            self.jobs += weight
            self._seq += 1
            rid = self._seq
            deadline = time.monotonic() + timeout
            try:
                self.proc.stdin.write((json.dumps({**req, "id": rid}) + "\n").encode())
                await self.proc.stdin.drain()
                while True:
                    line = await asyncio.wait_for(self.proc.stdout.readline(), max(0.0, deadline - time.monotonic()))
                    if not line:
                        await self.stop()
                        return {"ok": False, "rc": -1, "error": "build worker crashed"}
                    try:
                        resp = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(resp, dict) or resp.get("ready"):
                        continue
                    # module workers (drawing, assembly) don't echo ids; their replies carry no "id" at all
                    if resp.get("id") == rid or "id" not in resp:
                        return resp
                    # anything else (a late "ready", a reply to a request that already timed out) is dropped
            except (TimeoutError, ConnectionError, BrokenPipeError):
                await self.stop()
                return {"ok": False, "rc": -1, "error": f"timed out after {timeout:.0f} s"}


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


async def finalize(key: str, out: Path, timeout: float = 180, stage: str = "all") -> dict[str, Any]:
    """Complete a fast build (runner.finalize): stage "exports" (files + CHK-07), "determinism" (CHK-08) or "all"."""
    return await get_worker(key).request({"op": "finalize", "out": str(out), "stage": stage}, timeout)


async def render(key: str, stl: Path, png: Path, title: str = "", timeout: float = 60) -> dict[str, Any]:
    return await get_worker(key).request({"op": "render", "stl": str(stl), "png": str(png), "title": title}, timeout)


async def diff(key: str, a_step: Path, b_step: Path, out: Path, timeout: float = 180) -> dict[str, Any]:
    return await get_worker(key).request({"op": "diff", "a": str(a_step), "b": str(b_step), "out": str(out)}, timeout)


async def dims_base(key: str, script: Path, prev: Path | None, timeout: float = 120) -> dict[str, Any]:
    return await get_worker(key).request({"op": "dims_base", "script": str(script),
                                          "prev": str(prev) if prev else None}, timeout, weight=0.25)


async def dims_step(key: str, script: Path, item: dict[str, Any], base_key: str, timeout: float = 60) -> dict[str, Any]:
    return await get_worker(key).request({"op": "dims_step", "script": str(script), "key": base_key, **item}, timeout,
                                         weight=0.1)


async def warm(key: str) -> None:
    try:
        await get_worker(key).warm()
    except (WorkerUnavailable, OSError):
        pass


async def shutdown_all() -> None:
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


if __name__ == "__main__":
    serve()
