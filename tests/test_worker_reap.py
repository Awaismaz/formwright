"""CAD worker housekeeping: idle eviction never touches busy or recently used workers (no real processes)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from aicad.agent import worker


class _Proc:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.killed = False

    def kill(self) -> None:
        self.killed, self.returncode = True, -9


class _W:
    def __init__(self, idle_s: float, busy: bool = False) -> None:
        self.proc: Any = _Proc()
        self.lock = asyncio.Lock()
        self.last_used = time.monotonic() - idle_s
        if busy:
            self.lock._locked = True  # type: ignore[attr-defined]  # held by a build in progress


def test_evicts_oldest_idle_down_to_the_cap() -> None:
    ws = {"a": _W(3600), "b": _W(1200), "c": _W(30), "d": _W(900)}
    # 4 alive, keep 2: the two longest idle beyond 600 s go (a: 3600 s, b: 1200 s); c and d stay
    assert worker.evict_idle(ws, keep=2, idle_s=600) == ["a", "b"]
    assert ws["a"].proc is None and ws["b"].proc is None
    assert ws["c"].proc is not None and ws["d"].proc is not None


def test_never_evicts_busy_or_recent_workers() -> None:
    # a has pending background verification (lock held); b and c were used within the idle floor
    ws = {"a": _W(5000, busy=True), "b": _W(100), "c": _W(10)}
    assert worker.evict_idle(ws, keep=0, idle_s=600) == []
    assert all(w.proc is not None for w in ws.values())


def test_under_the_cap_nothing_happens() -> None:
    ws = {"a": _W(9999), "b": _W(9999)}
    assert worker.evict_idle(ws, keep=2, idle_s=600) == []
