"""Per-call metering for every model call (AGT-001 (d), INF-005 seed).

Each finished call emits one ``Metering`` record:

* a structured log line on ``aicad.llm`` (provider, role, model id, tokens, cost, latency; never prompt text),
* every registered listener (the platform's token ledger keeps charging from the cost the call sites return; a
  listener is how a future per-call ledger or the admin console subscribes),
* a small in-process ring buffer of recent calls (super-admin ``/api/admin/system``).

Design-agent sessions are metered by ``AgentSession`` (live meter + ``ResultMessage`` cost) and recorded per turn in
the AGT-009 run record, which now also names the provider.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from aicad.llm.base import Metering

log = logging.getLogger("aicad.llm")
_listeners: list[Callable[[Metering], None]] = []
_recent: deque[dict[str, Any]] = deque(maxlen=200)
_lock = threading.Lock()


def add_listener(fn: Callable[[Metering], None]) -> None:
    with _lock:
        _listeners.append(fn)


def remove_listener(fn: Callable[[Metering], None]) -> None:
    with _lock:
        if fn in _listeners:
            _listeners.remove(fn)


def emit(m: Metering) -> None:
    """Record one call. Never raises: metering must not break the product path."""
    d = m.as_dict()
    try:
        log.info("llm_call %s", json.dumps(d, sort_keys=True, default=str))
    except Exception:  # noqa: BLE001,S110
        pass
    with _lock:
        _recent.append(d)
        listeners = list(_listeners)
    for fn in listeners:
        try:
            fn(m)
        except Exception:
            log.warning("metering listener failed", exc_info=True)


def recent(limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        return list(_recent)[-limit:]


@contextmanager
def capture() -> Iterator[list[Metering]]:
    """Collect the records emitted inside the block (tests, benchmarks)."""
    got: list[Metering] = []
    add_listener(got.append)
    try:
        yield got
    finally:
        remove_listener(got.append)
