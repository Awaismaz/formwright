"""Background render queue: a small pool of worker threads, each driving one external Blender process at a time.

Priorities: previews jump ahead of exports, finals and turntables. Caps: per-workspace pending jobs and a global
queue length (callers get a clear "queue full" error). Job state lives in `job.json` inside the job folder, so the
gallery survives restarts; jobs that were running when the server stopped are reported as interrupted.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import queue
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PRIORITY = {"preview": 0, "export": 1, "final": 2, "turntable": 3}
MAX_PENDING_PER_ORG = 6
MAX_PENDING_TOTAL = 30
ACTIVE = ("queued", "running")


class QueueFull(RuntimeError):
    pass


def now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")  # naive UTC, like the platform


def read_job(d: Path) -> dict[str, Any] | None:
    try:
        return json.loads((d / "job.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_job(d: Path, job: dict[str, Any]) -> None:
    tmp = d / "job.tmp"
    tmp.write_text(json.dumps(job, indent=1), encoding="utf-8")
    for _ in range(5):  # Windows: a concurrent reader can briefly hold the target open
        try:
            tmp.replace(d / "job.json")
            return
        except PermissionError:
            time.sleep(0.05)
    tmp.replace(d / "job.json")


class RenderQueue:
    def __init__(self, workers: int | None = None) -> None:
        self.workers = workers or max(1, int(os.environ.get("FW_MESH_WORKERS", "1")))
        self._q: queue.PriorityQueue[tuple[int, int, str]] = queue.PriorityQueue()
        self._seq = itertools.count()
        self._lock = threading.Lock()
        self._live: dict[str, dict[str, Any]] = {}   # job id -> {"dir", "org", "run", "state"}
        self._threads: list[threading.Thread] = []

    def _ensure_threads(self) -> None:
        while len(self._threads) < self.workers:
            t = threading.Thread(target=self._loop, name=f"mesh-render-{len(self._threads)}", daemon=True)
            t.start()
            self._threads.append(t)

    def is_live(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._live

    def pending(self, org: str | None = None) -> int:
        with self._lock:
            return sum(1 for j in self._live.values() if org is None or j["org"] == org)

    def position(self, job_id: str) -> int | None:
        """1-based place among queued jobs (by priority, then arrival), or None when not queued."""
        with self._lock:
            items = sorted(self._q.queue)
            ids = [i for _, _, i in items if self._live.get(i, {}).get("state") == "queued"]
        return ids.index(job_id) + 1 if job_id in ids else None

    def submit(self, job_dir: Path, job: dict[str, Any], run: Callable[[Path, dict[str, Any]], None]) -> None:
        """Queue `run(job_dir, job)`; it must update job.json itself. Raises QueueFull."""
        with self._lock:
            if job["id"] in self._live:
                return
            if sum(1 for j in self._live.values() if j["org"] == job["org"]) >= MAX_PENDING_PER_ORG:
                raise QueueFull(f"Your workspace already has {MAX_PENDING_PER_ORG} renders waiting. Let them finish "
                                "or cancel one first.")
            if len(self._live) >= MAX_PENDING_TOTAL:
                raise QueueFull("The render queue is full right now. Try again in a few minutes.")
            self._live[job["id"]] = {"dir": job_dir, "org": job["org"], "run": run, "state": "queued"}
            self._q.put((PRIORITY.get(job["kind"], 5), next(self._seq), job["id"]))
        self._ensure_threads()

    def _loop(self) -> None:
        while True:
            _, _, jid = self._q.get()
            with self._lock:
                rec = self._live.get(jid)
                if rec is None:  # cancelled while queued
                    continue
                rec["state"] = "running"
            try:
                job = read_job(rec["dir"]) or {}
                if job.get("state") == "queued":
                    rec["run"](rec["dir"], job)
            except Exception:
                log.exception("mesh render job %s crashed", jid)
            finally:
                with self._lock:
                    self._live.pop(jid, None)

    def cancel(self, job_id: str) -> bool:
        """Drop a queued job (running ones finish or time out). True when it was removed."""
        with self._lock:
            rec = self._live.get(job_id)
            if rec is None or rec["state"] != "queued":
                return False
            self._live.pop(job_id)
            return True


QUEUE = RenderQueue()
