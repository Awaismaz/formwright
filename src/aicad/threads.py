"""ISO metric screw threads for cosmetic threads (CAD-027): designation, pitch table, basic sizes, callout text.

A cosmetic thread is metadata on a plain hole or cylinder: the geometry stays the tap-drill hole (internal) or the
major-diameter cylinder (external); no helix is modelled. The thread travels with the model (``status.json``
``threads``, the STEP header and ``part.threads.json``) and is drawn as an ISO 6410-1 thread representation with a
standard callout ("4X M6×1-6H ▽12").

Sources (numbers are table values, never fitted):
  * ISO 261:1998 ISO general purpose metric screw threads, general plan: the coarse pitch and the fine pitches per
    nominal diameter (``COARSE`` / ``FINE`` below: the first- and second-choice sizes of ISO 262:1998 "selected
    sizes for screws, bolts and nuts", which is what workshops stock taps and dies for).
  * ISO 724:1993 basic dimensions: D1 = d1 = D - 1.082532 P (internal minor), d3 = d - 1.226869 P (external root).
  * ISO 965-1:2013 tolerance classes: internal 4H 5H 6H 7H 5G 6G 7G (6H medium, the default); external 4h 6h 4g 6g
    8g 6f 6e (6g medium, the default).
  * Tap drill ≈ d - P: common workshop practice (cf. ISO 2306 for 6H): verify for your tap.
"""

from __future__ import annotations

import re
from typing import Any

#: ISO 261 / ISO 262 coarse pitch per nominal diameter d (mm)
COARSE: dict[float, float] = {
    1.0: 0.25, 1.2: 0.25, 1.6: 0.35, 2.0: 0.4, 2.5: 0.45, 3.0: 0.5, 3.5: 0.6, 4.0: 0.7, 5.0: 0.8, 6.0: 1.0,
    8.0: 1.25, 10.0: 1.5, 12.0: 1.75, 14.0: 2.0, 16.0: 2.0, 18.0: 2.5, 20.0: 2.5, 22.0: 2.5, 24.0: 3.0, 27.0: 3.0,
    30.0: 3.5, 33.0: 3.5, 36.0: 4.0, 39.0: 4.0, 42.0: 4.5, 45.0: 4.5, 48.0: 5.0, 52.0: 5.0, 56.0: 5.5, 60.0: 5.5,
    64.0: 6.0,
}
#: ISO 261 / ISO 262 fine pitches per nominal diameter (selected sizes, first and second choice)
FINE: dict[float, tuple[float, ...]] = {
    8.0: (1.0,), 10.0: (1.25, 1.0), 12.0: (1.5, 1.25), 14.0: (1.5,), 16.0: (1.5,), 18.0: (2.0, 1.5),
    20.0: (2.0, 1.5), 22.0: (2.0, 1.5), 24.0: (2.0,), 27.0: (2.0,), 30.0: (2.0,), 33.0: (2.0,), 36.0: (3.0,),
    39.0: (3.0,), 42.0: (3.0,), 45.0: (3.0,), 48.0: (3.0,), 52.0: (4.0,), 56.0: (4.0,), 60.0: (4.0,), 64.0: (4.0,),
}
INTERNAL_CLASSES = ("6H", "4H", "5H", "7H", "5G", "6G", "7G")
EXTERNAL_CLASSES = ("6g", "4h", "6h", "4g", "8g", "6f", "6e")
SOURCES = {
    "pitch": "ISO 261 / ISO 262 (coarse and fine pitches, selected sizes)",
    "basic": "ISO 724 basic dimensions (D1 = D − 1.082532 P, d3 = d − 1.226869 P)",
    "classes": "ISO 965-1 tolerance classes (6H / 6g medium)",
    "tap_drill": "Tap drill ≈ d − P: common practice (cf. ISO 2306); verify for your tap",
    "drawing": "ISO 6410-1 thread representation: thin 3/4 circle at the root, thick line at the crest",
}


class ThreadError(ValueError):
    """A thread the tables don't hold, or one that doesn't fit the hole / cylinder (message shown as is)."""


def _num(v: Any) -> float:
    return float(f"{float(v):g}")


def pitches(d: float) -> list[float]:
    """ISO 261 pitches for a nominal size: coarse first, then the fine pitches."""
    d = _num(d)
    if d not in COARSE:
        return []
    return [COARSE[d], *FINE.get(d, ())]


def designation(size: float, pitch: float, cls: str | None = None, ascii_only: bool = False) -> str:
    """'M6×1-6H' (the pitch is always written, so a fine thread is never mistaken for the coarse one)."""
    x = "x" if ascii_only else "×"
    s = f"M{_num(size):g}{x}{_num(pitch):g}"
    return f"{s}-{cls}" if cls else s


_DES = re.compile(r"^\s*M\s*(\d+(?:\.\d+)?)\s*(?:[x×X*]\s*(\d+(?:\.\d+)?))?\s*(?:-\s*([0-9][A-Za-z]))?\s*$")


def parse(text: str) -> dict[str, Any]:
    """'M6', 'M6x1', 'M10×1.25-6H' -> {size, pitch, cls}. The pitch defaults to the coarse pitch."""
    m = _DES.match(str(text or ""))
    if not m:
        raise ThreadError(f"“{str(text)[:20]}” isn't an ISO metric thread designation (write it like M6, M6x1 or "
                          "M10x1.25-6H)")
    size = _num(m.group(1))
    if size not in COARSE:
        raise ThreadError(f"M{size:g} isn't in the ISO 262 thread table; choose M1 to M64")
    pitch = _num(m.group(2)) if m.group(2) else COARSE[size]
    return {"size": size, "pitch": pitch, "cls": m.group(3)}


def basic(size: float, pitch: float) -> dict[str, float]:
    """ISO 724 basic diameters (mm, rounded to 0.001) and the usual tap drill."""
    d, p = _num(size), _num(pitch)
    return {"major": d, "minor_int": round(d - 1.082532 * p, 3), "minor_ext": round(d - 1.226869 * p, 3),
            "pitch_dia": round(d - 0.649519 * p, 3), "tap_drill": round(d - p, 2)}


def resolve(spec: Any, *, internal: bool, bore: float | None = None, length: float | None = None) -> dict[str, Any]:
    """A validated thread record for a hole (``internal``, ``bore`` = drilled Ø, ``length`` = hole depth, None when
    through) or a cylinder (external, ``bore`` = cylinder Ø).

    ``spec``: {"size", "pitch"?, "cls"?, "depth"?} or {"designation": "M6x1-6H", "depth"?}. ``depth`` None = the
    full hole / cylinder length."""
    if not isinstance(spec, dict):
        raise ThreadError("Thread must be an object with a size")
    if spec.get("designation"):
        base = parse(str(spec["designation"]))
    else:
        try:
            size = _num(spec.get("size"))
        except (TypeError, ValueError):
            raise ThreadError("Choose a thread size (M1 to M64)") from None
        if size not in COARSE:
            raise ThreadError(f"M{size:g} isn't in the ISO 262 thread table; choose M1 to M64")
        base = {"size": size, "pitch": _num(spec["pitch"]) if spec.get("pitch") else COARSE[size], "cls": None}
    size, pitch = base["size"], base["pitch"]
    if pitch not in pitches(size):
        ok = " or ".join(f"{p:g}" for p in pitches(size))
        raise ThreadError(f"{pitch:g} mm isn't an ISO 261 pitch for M{size:g} (choose {ok})")
    cls = str(spec.get("cls") or base.get("cls") or ("6H" if internal else "6g"))
    allowed = INTERNAL_CLASSES if internal else EXTERNAL_CLASSES
    if cls not in allowed:
        kind = "an internal" if internal else "an external"
        raise ThreadError(f"{cls} isn't {kind} thread tolerance class (ISO 965-1: {', '.join(allowed)})")
    b = basic(size, pitch)
    if bore is not None:
        if internal and not (b["minor_int"] - 0.5 <= bore < size):
            raise ThreadError(f"A Ø{bore:g} hole can't carry an M{size:g}×{pitch:g} thread: the drill must be under "
                              f"Ø{size:g} and about Ø{b['tap_drill']:g} (tap drill)")
        if not internal and abs(bore - size) > max(0.3, 0.02 * size):
            raise ThreadError(f"A Ø{bore:g} cylinder can't carry an M{size:g}×{pitch:g} thread: the major diameter "
                              f"is Ø{size:g}")
    depth = spec.get("depth")
    if depth in (None, "", 0):
        depth = None
    else:
        try:
            depth = _num(depth)
        except (TypeError, ValueError):
            raise ThreadError("Thread depth must be a number in mm") from None
        if not 0 < depth <= 1e4:
            raise ThreadError("Thread depth must be positive")
        if length is not None and depth > length + 1e-6:
            raise ThreadError(f"The thread ({depth:g} mm) is deeper than the {'hole' if internal else 'cylinder'} "
                              f"({length:g} mm)")
        if length is not None and abs(depth - length) <= 1e-6:
            depth = None
    return {"size": size, "pitch": pitch, "cls": cls, "internal": bool(internal), "depth": depth,
            "designation": designation(size, pitch, cls), "series": "coarse" if pitch == COARSE[size] else "fine",
            "major": b["major"], "minor": b["minor_int"] if internal else b["minor_ext"]}


def fmt(v: float) -> str:
    s = f"{round(float(v) + 0.0, 2):.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def callout(t: dict[str, Any], qty: int = 1, length: float | None = None) -> str:
    """Drawing callout for a thread group: '4X M6×1-6H ▽12' (blind), 'M6×1-6H THRU' (full length of a through
    hole), 'M20×1.5-6g' (external, full length). ``length``: the thread length to print when it is not the full
    feature (``t["depth"]``, or ``length`` given by the caller)."""
    q = f"{qty}X " if qty > 1 else ""
    depth = t.get("depth") if length is None else length
    s = f"{q}{designation(t['size'], t['pitch'], t['cls'])}"
    if depth is not None:
        return f"{s} ▽{fmt(depth)}"
    return f"{s} THRU" if t.get("internal") and t.get("thru") else s


def step_text(t: dict[str, Any]) -> str:
    """ASCII line for the STEP header (ISO 10303-21 strings are ASCII)."""
    inst = t.get("instances") or []
    dirs = {tuple(i["dir"]) for i in inst}

    def xyz(v: Any) -> str:
        return ",".join(f"{c:g}" for c in v)

    same = len(dirs) == 1
    pts = ";".join(xyz(i["p"]) + ("" if same else f">{xyz(i['dir'])}") for i in inst)
    d = "FULL" if t.get("depth") is None else f"{t['depth']:g}"
    return (f"FW-THREAD {len(inst)}X {designation(t['size'], t['pitch'], t['cls'], ascii_only=True)} "
            f"{'INTERNAL' if t['internal'] else 'EXTERNAL'} DEPTH {d} DIR {xyz(next(iter(dirs))) if same else 'EACH'} AT {pts}")


def tables() -> dict[str, Any]:
    """Everything the thread pickers show (one source of truth for the app)."""
    sizes = sorted(COARSE)
    return {"sizes": sizes, "pitches": {f"{s:g}": pitches(s) for s in sizes},
            "tap_drill": {f"{s:g}": {f"{p:g}": basic(s, p)["tap_drill"] for p in pitches(s)} for s in sizes},
            "internal_classes": list(INTERNAL_CLASSES), "external_classes": list(EXTERNAL_CLASSES), "sources": SOURCES}
