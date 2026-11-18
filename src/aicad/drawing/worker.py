"""Warm drawing worker: a long-lived process with the CAD kernel loaded, so regeneration feels interactive.

The web process never imports the kernel (same rule as the build worker). Only Formwright's own drawing code runs
here; no user script is executed (the worker reads the verified ``part.step`` / ``status.json``).

Protocol (one JSON object per line):
  parent -> worker  {"op": "generate", "out": str, "dest": str, "options": {...}, "meta": {...}, "edits": {...}}
                    {"op": "assembly", "nodes": [...], "rows": [...], "dest": str, "meta": {...}}  (DRW-014)
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
from aicad.drawing import DrawingInputError


def serve() -> None:
    proto = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    import build123d  # noqa: F401  (warm the kernel)
    import reportlab.pdfgen.canvas  # noqa: F401

    from aicad.drawing.generate import generate

    proto.write(json.dumps({"ready": True}) + "\n")
    for line in sys.stdin:
        t0 = time.perf_counter()
        try:
            req = json.loads(line)
            if req.get("op") == "assembly":  # DRW-014: assembly drawing with its BOM and balloons
                from aicad.drawing import assembly_sheet

                res = assembly_sheet.generate(req["nodes"], req["rows"], Path(req["dest"]), req.get("meta") or {},
                                              req.get("size") or "A3")
                resp = {"ok": True, "rc": 0, "result": res}
            elif req.get("op") != "generate":
                resp: dict[str, Any] = {"ok": False, "rc": 2, "error": f"unknown op {req.get('op')}"}
            else:
                res = generate(Path(req["out"]), Path(req["dest"]), req.get("options") or {}, req.get("meta") or {},
                               req.get("edits"))
                resp = {"ok": True, "rc": 0, "result": res}
        except DrawingInputError as e:
            resp = {"ok": False, "rc": 1, "error": str(e), "user_error": True}
        except Exception as e:  # noqa: BLE001 - report, keep serving
            resp = {"ok": False, "rc": 1, "error": f"{type(e).__name__}: {e}"}
        resp["elapsed_s"] = round(time.perf_counter() - t0, 3)
        proto.write(json.dumps(resp) + "\n")


class DrawingWorker(Worker):
    async def _start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-m", "aicad.drawing.worker", env=child_env(),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=16 * 1024 * 1024)
        self.jobs = 0
        assert self.proc.stdout is not None
        line = await asyncio.wait_for(self.proc.stdout.readline(), 120)
        if not line:
            raise RuntimeError("drawing worker failed to start")


_workers: dict[str, DrawingWorker] = {}


def get_worker(key: str) -> DrawingWorker:
    w = _workers.get(key)
    if w is None:
        w = _workers[key] = DrawingWorker()
    return w


async def generate(key: str, out: Path, dest: Path, options: dict[str, Any], meta: dict[str, Any],
                   edits: dict[str, Any] | None = None, timeout: float = 120) -> dict[str, Any]:
    return await get_worker(key).request({"op": "generate", "out": str(out), "dest": str(dest), "options": options,
                                          "meta": meta, "edits": edits}, timeout)


async def assembly(key: str, nodes: list[dict[str, Any]], rows: list[dict[str, Any]], dest: Path,
                   meta: dict[str, Any], size: str = "A3", timeout: float = 300) -> dict[str, Any]:
    return await get_worker(key).request({"op": "assembly", "nodes": nodes, "rows": rows, "dest": str(dest),
                                          "meta": meta, "size": size}, timeout)


async def shutdown_all() -> None:
    for w in list(_workers.values()):
        await w.stop()
    _workers.clear()


if __name__ == "__main__":
    serve()
