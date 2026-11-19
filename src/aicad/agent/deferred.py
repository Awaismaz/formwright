"""Deferred verification of agent builds (PS-01): the slow half of the checks runs off the agent's critical path.

An agent build returns as soon as the part is built and CHK-02..05 + topology + render are ready (a few seconds).
The STEP/STL/GLB exports, the CHK-07 STEP round trip and the CHK-08 determinism rebuild then run on the same warm
worker in the background, while the agent reads the report and writes its next step. Rules that keep the verdict
honest:

- A newer build supersedes the background work of the previous one (it is cancelled if not yet running).
- If a deferred check of a build fails, the agent is told in the report of its next build.
- At the end of a turn the session awaits ``settle()``: the turn's verdict, the run record and notifications only
  see the build once every deferred check has run. A failed deferred check gets one automatic follow-up turn.
- ``status["verified"]`` (runner.recompute_ok) is False while anything is pending; ``runner.is_verified`` is the
  one function callers use to decide whether a build counts as verified.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aicad.agent import worker

FINALIZE_TIMEOUT_S = 300
DEFERRED_IDS = ("CHK-07", "CHK-08")
log = logging.getLogger("aicad.agent")


def read_status(out: Path) -> dict[str, Any] | None:
    try:
        return json.loads((out / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def failed_deferred(status: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Deferred checks that ran and failed (gating)."""
    return [c for c in (status or {}).get("checks", [])
            if c.get("id") in DEFERRED_IDS and c.get("gating") and not c.get("passed")
            and not (c.get("detail") or {}).get("pending")]


def has_pending(status: dict[str, Any] | None) -> bool:
    if not status or status.get("error"):
        return False
    return bool(status.get("exports_pending") or status.get("pending_checks"))


class DeferredChecks:
    """Background verification for one build folder on one warm worker."""

    def __init__(self, key: str, out: Path) -> None:
        self.key, self.out = key, out
        self.task: asyncio.Task[None] | None = None
        self.build_id: Any = None
        self.started = 0  # builds handed over (a turn compares before/after)
        self._failed: list[dict[str, Any]] = []  # failures not yet reported to the agent
        self._callbacks: list[tuple[Any, Callable[[], None]]] = []
        self._exported: asyncio.Event | None = None  # set when the running chain has written the files

    # ---------------------------------------------------------------- agent build loop
    async def before_build(self) -> list[dict[str, Any]]:
        """A new build is about to start: drop the previous build's background work that hasn't run yet and return
        its deferred-check failures the agent hasn't heard about."""
        t = self.task
        if t is not None and not t.done():
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self.task = None
        notes, self._failed = self._failed, []
        return notes

    def start(self, build_id: Any) -> None:
        """Hand a fresh fast build over to the background."""
        self.build_id = build_id
        self.started += 1
        self._exported = asyncio.Event()
        self.task = asyncio.get_running_loop().create_task(self._run(build_id, self._exported))

    async def _run(self, build_id: Any, exported: asyncio.Event) -> None:
        try:
            for stage in ("exports", "determinism"):
                res = await worker.finalize(self.key, self.out, timeout=FINALIZE_TIMEOUT_S, stage=stage)
                if stage == "exports":
                    exported.set()
                if res.get("rc") not in (0,):
                    break  # superseded (3), nothing to do (2), or the worker failed: settle() handles what is left
        finally:
            exported.set()
        st = read_status(self.out)
        if st is None or st.get("build_id") != build_id:
            return
        self._failed = failed_deferred(st)
        self._fire(build_id)

    def when_verified(self, build_id: Any, fn: Callable[[], None]) -> None:
        """Run ``fn`` once the background checks of ``build_id`` are done (now, if they already are)."""
        st = read_status(self.out)
        if st is not None and st.get("build_id") == build_id and not has_pending(st):
            self._safe(fn)
            return
        self._callbacks.append((build_id, fn))

    def _fire(self, build_id: Any) -> None:
        keep = []
        for bid, fn in self._callbacks:
            if bid == build_id:
                self._safe(fn)
            elif bid == self.build_id:
                keep.append((bid, fn))
        self._callbacks = keep  # callbacks of superseded builds are dropped

    @staticmethod
    def _safe(fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:  # a bookkeeping callback never breaks verification
            log.exception("deferred-check callback failed")

    # ---------------------------------------------------------------- turn end / modules
    async def settle(self, exports_only: bool = False) -> dict[str, Any] | None:
        """Wait until the latest build in the folder is completely verified, and return its status. If the background
        work was cancelled or lost (worker recycled or crashed), it is run now; as a last resort the build is redone
        in full. ``exports_only``: return as soon as the files exist (modules reading part.step; CHK-08 may still be
        running). Never raises."""
        t = self.task
        if t is not None and not t.done():
            with contextlib.suppress(asyncio.CancelledError, Exception):
                if exports_only and self._exported is not None:
                    await asyncio.shield(asyncio.ensure_future(self._exported.wait()))
                else:
                    await asyncio.shield(t)
        st = read_status(self.out)
        if exports_only and st is not None and not st.get("exports_pending"):
            return st
        if not has_pending(st):
            return st
        try:
            res = await worker.finalize(self.key, self.out, timeout=FINALIZE_TIMEOUT_S,
                                        stage="exports" if exports_only else "all")
            st = read_status(self.out)
            if res.get("rc") == 2 and has_pending(st) and st and st.get("script"):
                # the worker no longer holds the built shape: rebuild in full (same script, every check inline)
                script = self.out.parent / str(st["script"])
                if script.is_file():
                    await worker.build(self.key, script, self.out, determinism=True, fast=False,
                                       timeout=FINALIZE_TIMEOUT_S)
                    st = read_status(self.out)
        except Exception:
            log.exception("settling deferred checks failed")
            st = read_status(self.out)
        if st is not None:
            if st.get("build_id") == self.build_id:
                self._failed = failed_deferred(st)
            self._fire(st.get("build_id"))
        return st

    def read(self) -> dict[str, Any] | None:
        return read_status(self.out)

    def take_failures(self) -> list[dict[str, Any]]:
        notes, self._failed = self._failed, []
        return notes


def failure_note(failed: list[dict[str, Any]], previous: bool = True) -> str:
    """What the agent is told about deferred checks that failed."""
    if not failed:
        return ""
    lines = [("BACKGROUND CHECKS ON YOUR PREVIOUS BUILD FAILED:" if previous else
              "BACKGROUND CHECKS ON YOUR LAST BUILD FAILED:")]
    for c in failed:
        d = {k: v for k, v in (c.get("detail") or {}).items() if k not in ("original", "reimported")}
        lines.append(f"[FAIL] {c['id']} {c['name']}: {json.dumps(d, default=str)}")
        if c["id"] == "CHK-08":
            lines.append("  The design did not rebuild identically: remove anything order- or time-dependent "
                         "(random numbers, set iteration, clock), then rebuild.")
        if c["id"] == "CHK-07":
            lines.append("  The exported STEP did not read back identically: look for tiny or degenerate faces, "
                         "self-touching geometry or near-coincident booleans, then rebuild.")
    return "\n".join(lines)
