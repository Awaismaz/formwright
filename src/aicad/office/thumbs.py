"""Board thumbnails (web side, pure Python): which part snapshot a card shows, the view, and the disk cache.

A thumbnail is the line-art projection of one immutable part snapshot (``assembly.store`` part cache), so it is drawn
once per (snapshot key, view, ``thumb.VERSION``) and kept next to the snapshot as ``thumb_v<V>_<hash>.svg``. The
drawing worker draws it (the web process never loads the kernel); requests never wait for it: the endpoint answers
202 while it is being drawn, and a card shows a neutral silhouette meanwhile.

``ghost`` is the item's placeholder (the envelope with its interface features), ``real`` the approved part. Both
are framed by the item's envelope from the skeleton and seen from the same direction, in the ICD part frame (a real
part modelled in another frame is turned through the frame Gage found), so the two line up for the cross-fade.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

from aicad.drawing.thumb import VERSION

ISO = (1.0, -1.0, 1.0)
TILT_DEG = 35.0  # a disc (gear, flange) is seen 35 degrees off its axis: teeth and holes read, the face width shows
RETRY_FAILED_S = 300.0
_inflight: dict[str, asyncio.Task[Any]] = {}
_failed: dict[str, float] = {}


def _unit(v: list[float] | tuple[float, ...]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [round(x / n, 6) for x in v]


def view_for(size: list[float] | None) -> dict[str, Any]:
    """Iso, except a disc (one short side, the other two about equal): 35 degrees off its axis."""
    if size and len(size) == 3 and all(float(x) > 0 for x in size):
        dims = [float(x) for x in size]
        i = min(range(3), key=lambda k: dims[k])
        others = [dims[k] for k in range(3) if k != i]
        if dims[i] < 0.6 * min(others) and max(others) <= 1.25 * min(others):
            e = [0.0, 0.0, 0.0]
            e[i] = 1.0
            k = sum(a * b for a, b in zip(ISO, e, strict=True))
            perp = _unit([a - k * b for a, b in zip(ISO, e, strict=True)])
            c, s = math.cos(math.radians(TILT_DEG)), math.sin(math.radians(TILT_DEG))
            d = _unit([c * (ISO[j] if j == i else 0.0) + s * perp[j] for j in range(3)])
            up = [0.0, 0.0, 1.0] if i != 2 else [0.0, 1.0, 0.0] if abs(d[2]) > 0.999 else [0.0, 0.0, 1.0]
            return {"name": "axial", "dir": d, "up": up}
    return {"name": "iso", "dir": _unit(ISO), "up": [0.0, 0.0, 1.0]}


def _ticket(doc: dict[str, Any], item: str) -> dict[str, Any] | None:
    return next((t for t in doc.get("tickets") or [] if t.get("item_id") == item and t.get("kind") in ("part", "standard")),
                None)


def _frame(doc: dict[str, Any], item: str) -> dict[str, Any] | None:
    f = ((_ticket(doc, item) or {}).get("icd_check") or {}).get("frame") or None
    if not f or f.get("identity") or not f.get("R") or f.get("t") is None:
        return None
    return {"R": [[float(x) for x in row] for row in f["R"]], "t": [float(x) for x in f["t"]]}


def ghost_key(aroot: Path, doc: dict[str, Any], item: str) -> str | None:
    """The item's placeholder snapshot: the current key, the one a real part replaced, or the one the current
    interfaces make (when it is still in the part cache)."""
    from aicad.assembly import store as astore

    p = ((doc.get("assembly") or {}).get("parts") or {}).get(item) or {}
    key = p.get("key") if p.get("kind") == "placeholder" else p.get("ghost")
    if not key and p:
        try:
            from aicad.office import icd, program_assembly

            spec = icd.placeholder_spec(doc["skeleton"], doc["icd"]["interfaces"], item)
            key = program_assembly.placeholder_key(doc["id"], item, spec)
        except (KeyError, TypeError, ValueError):
            key = None
    if not key:
        return None
    try:
        return key if (astore.part_dir(aroot, key) / "part.step").is_file() else None
    except Exception:  # noqa: BLE001 - a malformed key is simply no thumbnail
        return None


def resolve(aroot: Path, doc: dict[str, Any], item: str, state: str) -> dict[str, Any] | None:
    """{key, opts, hash} of the thumbnail a card asks for, or None (no such snapshot yet)."""
    from aicad.assembly import store as astore

    p = ((doc.get("assembly") or {}).get("parts") or {}).get(item)
    if not p:
        return None
    frame = None
    if state == "real":
        if p.get("kind") != "real":
            return None
        key = p.get("key")
        frame = _frame(doc, item)
        try:
            if not key or not (astore.part_dir(aroot, key) / "part.step").is_file():
                return None
        except Exception:  # noqa: BLE001
            return None
    else:
        key = ghost_key(aroot, doc, item)
        if not key:
            return None
    it = ((doc.get("skeleton") or {}).get("items") or {}).get(item) or {}
    size = [float(x) for x in it.get("size") or []][:3] or None
    box = [-size[0] / 2, -size[1] / 2, -size[2] / 2, size[0] / 2, size[1] / 2, size[2] / 2] if size and len(size) == 3 \
        else None
    opts = {**view_for(size), "box": [round(x, 4) for x in box] if box else None, "frame": frame}
    h = hashlib.sha1(json.dumps(opts, sort_keys=True).encode()).hexdigest()[:12]
    return {"key": key, "opts": opts, "hash": h}


def path(aroot: Path, r: dict[str, Any]) -> Path:
    from aicad.assembly import store as astore

    return astore.part_dir(aroot, r["key"]) / f"thumb_v{VERSION}_{r['hash']}.svg"


def cached(aroot: Path, r: dict[str, Any]) -> str | None:
    f = path(aroot, r)
    try:
        return f.read_text(encoding="utf-8") if f.is_file() else None
    except OSError:
        return None


async def draw(aroot: Path, org_id: str, r: dict[str, Any]) -> bool:
    """Draw one thumbnail in the organisation's drawing worker (cache file written by the worker)."""
    from aicad.assembly import store as astore
    from aicad.drawing import worker as dworker

    d = astore.part_dir(aroot, r["key"])
    info = (astore.part(aroot, r["key"]) or {}).get("info") or {}
    res = await dworker.thumb(org_id, d / "part.step", info, r["opts"], path(aroot, r))
    return bool(res.get("ok"))


def ensure(aroot: Path, org_id: str, r: dict[str, Any]) -> str:
    """Start drawing a missing thumbnail in the background (once). Returns "pending" or "failed" (a drawing that
    failed is not retried for a while: the card keeps its neutral silhouette)."""
    k = str(path(aroot, r))
    if k in _inflight:
        return "pending"
    if time.monotonic() - _failed.get(k, -1e9) < RETRY_FAILED_S:
        return "failed"

    async def run() -> None:
        try:
            if not await draw(aroot, org_id, r):
                _failed[k] = time.monotonic()
        except Exception:  # noqa: BLE001 - a thumbnail never breaks the office
            _failed[k] = time.monotonic()
        finally:
            _inflight.pop(k, None)

    _inflight[k] = asyncio.get_running_loop().create_task(run())
    return "pending"
