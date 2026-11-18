"""GD&T on drawing sheets (DRW-013): feature control frames and datum feature symbols, ISO 1101 / ISO 5459 style.

Never invented: a frame or datum appears only when it is given explicitly, either by the user in Drawing Studio
(``edits["gdt"]``) or by a Design Office interface spec (``meta["spec"]["gdt"]``, CD-021), and every one is traced in
the drawing record with its source. Pure Python; the symbols are drawn as line work (not font glyphs), so SVG, PDF
and DXF show the same thing with any font.

Targets (what a frame or datum is attached to):
  {"kind": "dim" | "callout", "id": ...}           a dimension or callout on the sheet (a feature of size)
  {"kind": "point", "view": ..., "u": .., "v": ..}  a point on a view's geometry (a surface seen edge-on)
Interface-spec items carry model-space targets instead ({"kind": "plane" | "axis", ...}); ``generate`` resolves
them against the exact census and drops (with a note) any that are not found on the model.
"""

from __future__ import annotations

import math
import re
from typing import Any

from aicad.drawing import DrawingInputError

#: characteristic -> (label, datums: "none" | "required" | "optional")
CHARS: dict[str, tuple[str, str]] = {
    "straightness": ("Straightness", "none"), "flatness": ("Flatness", "none"),
    "circularity": ("Circularity (roundness)", "none"), "cylindricity": ("Cylindricity", "none"),
    "profile_line": ("Profile of a line", "optional"), "profile_surface": ("Profile of a surface", "optional"),
    "parallelism": ("Parallelism", "required"), "perpendicularity": ("Perpendicularity", "required"),
    "angularity": ("Angularity", "required"), "position": ("Position", "optional"),
    "concentricity": ("Coaxiality / concentricity", "required"), "symmetry": ("Symmetry", "required"),
    "circular_runout": ("Circular run-out", "required"), "total_runout": ("Total run-out", "required"),
}
DIA_ALLOWED = {"position", "concentricity", "straightness", "perpendicularity", "parallelism", "angularity"}
MODIFIERS = {"M": "maximum material requirement", "L": "least material requirement"}
DATUM_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"  # ISO 5459: I, O and Q are not used
MAX_FRAMES, MAX_DATUMS = 40, 20


def _target(t: Any, what: str) -> dict[str, Any]:
    if not isinstance(t, dict):
        raise DrawingInputError(f"Choose what the {what} is attached to.")
    k = t.get("kind")
    if k in ("dim", "callout"):
        tid = str(t.get("id") or "")
        if not re.fullmatch(r"[a-z]+(-[a-z0-9]+){1,4}", tid):
            raise DrawingInputError(f"The {what} is attached to an unknown dimension.")
        return {"kind": k, "id": tid}
    if k == "point":
        if t.get("view") not in ("front", "top", "right", "section"):
            raise DrawingInputError(f"The {what} must be attached to a front, top, right or section view.")
        try:
            u, v = float(t["u"]), float(t["v"])
        except (KeyError, TypeError, ValueError):
            raise DrawingInputError(f"The {what} needs a point on the view.") from None
        if not (math.isfinite(u) and math.isfinite(v) and abs(u) < 1e6 and abs(v) < 1e6):
            raise DrawingInputError(f"The {what} needs a point on the view.")
        return {"kind": "point", "view": t["view"], "u": round(u, 4), "v": round(v, 4)}
    raise DrawingInputError(f"Choose what the {what} is attached to.")


def normalize(raw: Any) -> dict[str, list[dict[str, Any]]]:
    """User GD&T, sanitised and checked against ISO 1101 rules: form tolerances take no datum, orientation /
    run-out / coaxiality / symmetry need one, every datum a frame names must be defined on the sheet (here or by the
    interface spec, checked in ``generate``), letters are unique."""
    raw = raw if isinstance(raw, dict) else {}
    datums: list[dict[str, Any]] = []
    seen: set[str] = set()
    for d in (raw.get("datums") or [])[:MAX_DATUMS]:
        if not isinstance(d, dict):
            continue
        letter = str(d.get("letter") or "").strip().upper()
        if len(letter) != 1 or letter not in DATUM_LETTERS:
            raise DrawingInputError("A datum letter is one capital letter (I, O and Q are not used).")
        if letter in seen:
            raise DrawingInputError(f"Datum {letter} is defined twice.")
        seen.add(letter)
        datums.append({"letter": letter, "target": _target(d.get("target"), f"datum {letter}")})
    frames: list[dict[str, Any]] = []
    for n, f in enumerate((raw.get("frames") or [])[:MAX_FRAMES]):
        if not isinstance(f, dict):
            continue
        ch = f.get("char")
        if ch not in CHARS:
            raise DrawingInputError("Choose a geometric characteristic (flatness, position, …).")
        try:
            tol = float(f.get("tol"))
        except (TypeError, ValueError):
            raise DrawingInputError("A tolerance value is a number in mm.") from None
        if not (0 < tol <= 100):
            raise DrawingInputError("A geometric tolerance must be between 0 and 100 mm.")
        refs = [str(x).strip().upper() for x in (f.get("datums") or []) if str(x).strip()][:3]
        need = CHARS[ch][1]
        if need == "none" and refs:
            raise DrawingInputError(f"{CHARS[ch][0]} is a form tolerance: it has no datum reference (ISO 1101).")
        if need == "required" and not refs:
            raise DrawingInputError(f"{CHARS[ch][0]} needs at least one datum reference (ISO 1101).")
        if len(set(refs)) != len(refs) or any(len(r) != 1 or r not in DATUM_LETTERS for r in refs):
            raise DrawingInputError("Datum references are distinct capital letters, at most three.")
        mod = f.get("mod") if f.get("mod") in MODIFIERS else None
        dia = bool(f.get("dia")) and ch in DIA_ALLOWED
        frames.append({"id": f"gdt-{n + 1}", "char": ch, "tol": round(tol, 4), "dia": dia, "mod": mod,
                       "datums": refs, "target": _target(f.get("target"), "tolerance frame")})
    return {"datums": datums, "frames": frames}


def tol_text(f: dict[str, Any]) -> str:
    s = f"{f['tol']:.4f}".rstrip("0").rstrip(".")
    return ("Ø" if f.get("dia") else "") + s


def describe(f: dict[str, Any]) -> str:
    """Plain words for the panel: 'Position Ø0.2 (M) | A | B'."""
    mod = f" ({f['mod']})" if f.get("mod") else ""
    return " | ".join([f"{CHARS[f['char']][0]} {tol_text(f)}{mod}", *f.get("datums", [])])


# ----------------------------------------------------------------------------- drawing (into a layout.Group)
def frame_size(f: dict[str, Any], size: float, text_width: Any) -> tuple[float, float, list[float]]:
    """(width, height, cell widths) of a feature control frame for text height ``size``."""
    h = round(size * 2.0, 3)
    tw = text_width(tol_text(f), size) + 2.4 + (size * 1.25 if f.get("mod") else 0.0)
    cells = [h, max(h, tw)] + [h for _ in f.get("datums", [])]
    return sum(cells), h, cells


def draw_symbol(g: Any, ch: str, cx: float, cy: float, h: float, layer: str = "gdt") -> None:
    """The ISO 1101 characteristic symbol centred in a cell of height ``h`` (paper mm, y down)."""
    s = h * 0.32  # half size of the symbol
    if ch == "straightness":
        g.line(layer, cx - s, cy, cx + s, cy)
    elif ch == "flatness":
        g.poly(layer, [[cx - s, cy + s * 0.45], [cx + s * 0.55, cy + s * 0.45], [cx + s, cy - s * 0.45],
                       [cx - s * 0.55, cy - s * 0.45]], closed=True)
    elif ch == "circularity":
        g.circle(layer, cx, cy, s * 0.8)
    elif ch == "cylindricity":
        g.circle(layer, cx, cy, s * 0.6)
        g.line(layer, cx - s * 0.95, cy + s * 0.9, cx - s * 0.25, cy - s * 0.9)
        g.line(layer, cx + s * 0.25, cy + s * 0.9, cx + s * 0.95, cy - s * 0.9)
    elif ch in ("profile_line", "profile_surface"):
        g.arc(layer, cx, cy + s * 0.4, s * 0.9, 0.0, 180.0)
        if ch == "profile_surface":
            g.line(layer, cx - s * 0.9, cy + s * 0.4, cx + s * 0.9, cy + s * 0.4)
    elif ch == "parallelism":
        g.line(layer, cx - s * 0.7, cy + s * 0.9, cx - s * 0.05, cy - s * 0.9)
        g.line(layer, cx + s * 0.05, cy + s * 0.9, cx + s * 0.7, cy - s * 0.9)
    elif ch == "perpendicularity":
        g.line(layer, cx - s * 0.9, cy + s * 0.8, cx + s * 0.9, cy + s * 0.8)
        g.line(layer, cx, cy + s * 0.8, cx, cy - s * 0.9)
    elif ch == "angularity":
        g.line(layer, cx - s * 0.9, cy + s * 0.8, cx + s * 0.9, cy + s * 0.8)
        g.line(layer, cx - s * 0.9, cy + s * 0.8, cx + s * 0.7, cy - s * 0.8)
    elif ch == "position":
        g.circle(layer, cx, cy, s * 0.62)
        g.line(layer, cx - s, cy, cx + s, cy)
        g.line(layer, cx, cy - s, cx, cy + s)
    elif ch == "concentricity":
        g.circle(layer, cx, cy, s * 0.85)
        g.circle(layer, cx, cy, s * 0.42)
    elif ch == "symmetry":
        g.line(layer, cx - s * 0.6, cy - s * 0.55, cx + s * 0.6, cy - s * 0.55)
        g.line(layer, cx - s * 0.95, cy, cx + s * 0.95, cy)
        g.line(layer, cx - s * 0.6, cy + s * 0.55, cx + s * 0.6, cy + s * 0.55)
    elif ch in ("circular_runout", "total_runout"):
        tip = (cx + s * 0.75, cy - s * 0.85)
        base = (cx - s * 0.55, cy + s * 0.85)
        g.line(layer, base[0], base[1], tip[0], tip[1])
        g.arrow(tip, base, layer)
        if ch == "total_runout":
            g.line(layer, cx - s * 0.05, cy + s * 0.85, cx + s * 1.05, cy - s * 0.65)
            g.line(layer, base[0] - s * 0.3, base[1], cx + s * 0.75, base[1])


def draw_frame(g: Any, f: dict[str, Any], x: float, y: float, size: float, text_width: Any,
               ref: str | None = None) -> list[float]:
    """A feature control frame with its top-left corner at (x, y); returns its box."""
    w, h, cells = frame_size(f, size, text_width)
    g.rect("gdt", x, y, w, h)
    cx = x
    for i, cw in enumerate(cells):
        if i:
            g.line("gdt", cx, y, cx, y + h)
        if i == 0:
            draw_symbol(g, f["char"], cx + cw / 2, y + h / 2, h)
        elif i == 1:
            txt = tol_text(f)
            tx = cx + 1.2
            g.text(tx, y + h / 2 + size * 0.36, size, txt, kind="gdt", ref=ref)
            if f.get("mod"):
                mx = tx + text_width(txt, size) + size * 0.6
                g.circle("gdt", mx, y + h / 2, size * 0.55)
                g.text(mx, y + h / 2 + size * 0.27, size * 0.75, f["mod"], anchor="middle", kind="gdt", ref=ref)
        else:
            g.text(cx + cw / 2, y + h / 2 + size * 0.36, size, f["datums"][i - 2], anchor="middle", kind="gdt", ref=ref)
        cx += cw
    return [x, y, x + w, y + h]


def datum_size(size: float) -> tuple[float, float]:
    h = round(size * 2.0, 3)
    return h, h


def draw_datum(g: Any, letter: str, box_xy: tuple[float, float], anchor: tuple[float, float], size: float,
               ref: str | None = None) -> list[float]:
    """Datum feature symbol (ISO 5459): a square with the letter, joined to a filled triangle whose base sits on the
    feature at ``anchor``. Returns the square's box."""
    w, h = datum_size(size)
    x, y = box_xy
    g.rect("gdt", x, y, w, h)
    g.text(x + w / 2, y + h / 2 + size * 0.36, size, letter, anchor="middle", kind="gdt", ref=ref)
    # connector from the nearest edge midpoint of the square to the triangle apex
    mids = [(x + w / 2, y), (x + w / 2, y + h), (x, y + h / 2), (x + w, y + h / 2)]
    m = min(mids, key=lambda p: math.dist(p, anchor))
    dx, dy = anchor[0] - m[0], anchor[1] - m[1]
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    th = size * 0.75  # triangle height
    apex = (anchor[0] - ux * th, anchor[1] - uy * th)
    g.line("gdt", m[0], m[1], apex[0], apex[1])
    half = th * 0.62
    g.fill("gdt", [[apex[0], apex[1]], [anchor[0] - uy * half, anchor[1] + ux * half],
                   [anchor[0] + uy * half, anchor[1] - ux * half]])
    return [x, y, x + w, y + h]


# ----------------------------------------------------------------------------- interface-spec targets (CD-021)
def _principal(d: list[float]) -> str | None:
    for name, i in (("x", 0), ("y", 1), ("z", 2)):
        if abs(abs(d[i]) - 1.0) < 1e-6:
            return name
    return None


def resolve_model_target(t: dict[str, Any], an: dict[str, Any], dims: list[dict[str, Any]],
                         callouts: list[dict[str, Any]]) -> tuple[dict[str, Any], str] | None:
    """A model-space target (an ICD plane or axis, in the part's model coordinates) as a sheet target and its view,
    or None when the model has no such face / hole / cylinder (the item is then left off the sheet and reported)."""
    from aicad.drawing.dims import CIRCLE_VIEW, COORD, _uv
    from aicad.drawing.geometry import to_drawing

    rows = (an.get("part") or {}).get("rows")
    cen = an["census"]
    idx = {"x": 0, "y": 1, "z": 2}
    if t.get("kind") == "plane":
        p, n = to_drawing(rows, t["point"]), to_drawing(rows, t["normal"])
        ax = _principal(n)
        if ax is None:
            return None
        level = p[idx[ax]]
        if not any(abs(level - q) <= 1e-3 for q in cen["levels"].get(ax, [])):
            return None
        for view in ("front", "right", "top"):
            geom = an["views"].get(view)
            if not geom or geom.get("is_section") or ax not in COORD[view]:
                continue
            o = COORD[view][ax]
            k = 1 if o == "v" else 0
            best = None
            for pr in geom.get("visible", []):
                if pr[0] != "line":
                    continue
                a, b = (pr[1], pr[2]), (pr[3], pr[4])
                if abs(a[k] - level) <= 1e-3 and abs(b[k] - level) <= 1e-3:
                    ln = abs(a[1 - k] - b[1 - k])
                    if best is None or ln > best[0] + 1e-9:
                        best = (ln, a, b)
            if best is None:
                continue
            _ln, a, b = best
            q = 0.3  # a third of the way along the edge: clear of the centre lines
            u = a[0] + (b[0] - a[0]) * q
            v = a[1] + (b[1] - a[1]) * q
            return {"kind": "point", "view": view, "u": round(u, 4), "v": round(v, 4)}, view
        return None
    if t.get("kind") == "axis":
        p, d = to_drawing(rows, t["point"]), to_drawing(rows, t["dir"])
        ax = _principal(d)
        if ax is None:
            return None
        i = idx[ax]
        perp = [p[j] for j in range(3) if j != i]
        dia = float(t["d"])
        for h in cen["holes"]:
            if h["axis"] == ax and abs(h["dia"] - dia) <= 0.2 and all(abs(h["centre"][k] - perp[k]) <= 0.2 for k in (0, 1)):
                view = CIRCLE_VIEW[ax]
                p3 = [0.0, 0.0, 0.0]
                others = [j for j in range(3) if j != i]
                p3[others[0]], p3[others[1]] = h["centre"]
                uv = _uv(view, p3, COORD) if view in COORD else None
                for c in callouts:
                    if c.get("type", "hole") != "hole" or c["view"] != view or uv is None:
                        continue
                    if any(abs(q[0] - uv[0]) <= 1e-3 and abs(q[1] - uv[1]) <= 1e-3 for q in c["holes"]):
                        return {"kind": "callout", "id": c["id"]}, view
        for c in cen["outer"]:
            if c["axis"] == ax and abs(c["dia"] - dia) <= 0.2 and all(abs(c["centre"][k] - perp[k]) <= 0.2 for k in (0, 1)):
                for dd in dims:
                    if dd["kind"] == "diameter" and abs(dd["value"] - c["dia"]) <= 1e-6:
                        return {"kind": "dim", "id": dd["id"]}, dd["view"]
        return None
    return None
