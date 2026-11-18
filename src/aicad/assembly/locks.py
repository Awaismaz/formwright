"""One lock per assembly document, shared by Assembly Studio (hand edits) and the Design Office (Fitz).

Assembly Studio's routes edit a document under ``lock(aid)``; the Design Office's program assembly (build, swap-in,
integration, placeholder regeneration) takes the same lock around every edit of a document it owns, through
``hold(aid, who)``, so a hand edit and an office edit can never interleave (one waits for the other). ``holder(aid)``
says who holds a document right now, so Assembly Studio can show "The Design Office is updating this assembly".

In memory, one web process (PD-53: needs a shared lock service before the app runs on more than one server).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

_locks: dict[str, asyncio.Lock] = {}
_holders: dict[str, str] = {}


def lock(aid: str) -> asyncio.Lock:
    lk = _locks.get(aid)
    if lk is None:
        lk = _locks[aid] = asyncio.Lock()
    return lk


@contextlib.asynccontextmanager
async def hold(aid: str, who: str) -> AsyncIterator[None]:
    """Hold a document's lock and say who holds it (shown in Assembly Studio while it is held)."""
    async with lock(aid):
        _holders[aid] = who
        try:
            yield
        finally:
            _holders.pop(aid, None)


def holder(aid: str) -> str | None:
    """Who holds the document now: "Design Office" while the office edits it, None when nobody (or a hand edit)."""
    return _holders.get(aid) if lock(aid).locked() else None


OFFICE = "Design Office"
