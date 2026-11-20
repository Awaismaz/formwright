"""2D drafting without a model (DRW-017): a drawing document drawn directly in 2D, rendered on the same sheet
(frame, ISO 7200 title block, revision table, NOT APPROVED banner) as the model drawings.

Pure Python, no CAD kernel. The document (JSON) is:

  sheet   {size, orientation, scale [n, d], projection, units "mm" | "in", origin [x, y] paper mm}
  title   {title, drawing_no, material, company, drawn_by, checked_by, date, tolerance}
  geom    {points [{id, x, y}], entities [{id, type line|circle|arc, p1/p2 | c/r | c/p1/p2, layer}]}
          the same model as the Design Studio sketcher (web/src/sketch), drawing units, y up; arcs run
          counter-clockwise from p1 to p2 about c
  dims    associative dimensions: they reference point / entity ids, and their values are always measured from
          the geometry (never typed): linear (h | v | aligned), radius, diameter, angle, ordinate (x | y)
  annos   text, leader, balloon, surface (ISO 21920 symbol), gdt (ISO 1101 frame), datum, centermark, hatch
  notes   general notes (list of strings); revisions: the revision table rows the user enters

Layers follow ISO 128-2 line types: visible 01.2 (wide 0.5), hidden 02.1, centre 04.1, dimension 01.1 (narrow
0.25), construction (drafting aid, never printed). ``compose`` turns a document into the same primitive list the
model drawings use, so ``render.to_svg`` / ``render.to_pdf`` draw it; ``draft_dxf.to_dxf`` writes a CAD-native DXF.
"""

from __future__ import annotations

import math
import re
from typing import Any

from aicad.drawing import DrawingInputError
from aicad.drawing.layout import FRAME, _hatch, _info_blocks, _wrap, text_width

SCHEMA = 1
SHEETS: dict[str, tuple[float, float]] = {
    "A4": (297.0, 210.0), "A3": (420.0, 297.0), "A2": (594.0, 420.0), "A1": (841.0, 594.0), "A0": (1189.0, 841.0),
    "ANSI A": (279.4, 215.9), "ANSI B": (431.8, 279.4), "ANSI C": (558.8, 431.8), "ANSI D": (863.6, 558.8),
    "ANSI E": (1117.6, 863.6)}
#: ISO 5455 recommended scales
SCALES = [(50, 1), (20, 1), (10, 1), (5, 1), (2, 1), (1, 1), (1, 2), (1, 5), (1, 10), (1, 20), (1, 50), (1, 100),
          (1, 200), (1, 500), (1, 1000)]
UNITS = {"mm": 1.0, "in": 25.4}
#: drawing layer -> sheet line style (layout.LAYERS key)
LAYER_STYLE = {"visible": "visible", "hidden": "hidden", "center": "center_n", "dimension": "dim_n",
               "construction": "construction"}
LAYER_ORDER = ("visible", "hidden", "center", "dimension", "construction")
#: ISO 128-2 line type and width (mm) per layer, shown in the layer panel and used for the DXF layers
ISO128 = {"visible": ("01.2", "Continuous wide", 0.5), "hidden": ("02.1", "Dashed narrow", 0.25),
          "center": ("04.1", "Long-dashed dotted narrow", 0.25), "dimension": ("01.1", "Continuous narrow", 0.25),
          "construction": ("-", "Construction (not printed)", 0.13)}
GDT_SYMBOLS = ("straightness", "flatness", "circularity", "cylindricity", "profile_line", "profile_surface",
               "parallelism", "perpendicularity", "angularity", "position", "concentricity", "symmetry",
               "circular_runout", "total_runout")
#: characteristics that take a datum reference (ISO 1101)
GDT_NEEDS_DATUM = {"parallelism", "perpendicularity", "angularity", "concentricity", "symmetry", "circular_runout",
                   "total_runout"}
ARROW, ARROW_W = 2.6, 0.42
EXT_GAP, EXT_OVER, TXT_GAP = 1.0, 2.0, 1.0
LIMITS = {"points": 20000, "entities": 10000, "dims": 2000, "annos": 2000}

_ID = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
_FIT = re.compile(r"^[A-Za-z]{1,2}\d{1,2}(/[A-Za-z]{1,2}\d{1,2})?$")


# ----------------------------------------------------------------------------- formatting
def fmt(v: float, decimals: int = 2) -> str:
    """Drawing number format: at most ``decimals`` places, no trailing zeros (ISO 129-1)."""
    s = f"{round(v + 0.0, decimals):.{decimals}f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def fmt_dev(v: float, decimals: int) -> str:
    """Signed deviation: +0.1, -0.05, 0 (zero carries no sign, ISO 129-1)."""
    s = fmt(v, max(decimals, 3))
    return s if s == "0" or s.startswith("-") else f"+{s}"


def tol_parts(value: float, tol: dict[str, Any] | None, decimals: int) -> tuple[str, list[str]]:
    """Main text and stacked deviation lines (upper, lower) for a value with its tolerance."""
    main = fmt(value, decimals)
    t = tol or {}
    kind = t.get("kind", "none")
    if kind == "sym":
        return f"{main} ±{fmt(abs(t.get('up', 0.0)), max(decimals, 3))}", []
    if kind == "dev":
        return main, [fmt_dev(t.get("up", 0.0), decimals), fmt_dev(t.get("lo", 0.0), decimals)]
    if kind == "limits":
        d = max(decimals, 3)
        return "", [fmt(value + t.get("up", 0.0), d), fmt(value + t.get("lo", 0.0), d)]
    if kind == "fit" and t.get("fit"):
        return f"{main} {t['fit']}", []
    return main, []


# ----------------------------------------------------------------------------- sanitising
def _num(v: Any, lo: float = -1e7, hi: float = 1e7) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise DrawingInputError("A coordinate in the drawing is not a number") from None
    if not math.isfinite(f) or f < lo or f > hi:
        raise DrawingInputError("A coordinate in the drawing is out of range")
    return f


def _pt(v: Any) -> list[float]:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise DrawingInputError("A position in the drawing is malformed")
    return [_num(v[0]), _num(v[1])]


def _id(v: Any) -> str:
    s = str(v or "")
    if not _ID.fullmatch(s):
        raise DrawingInputError("An element id in the drawing is malformed")
    return s


def _txt(v: Any, n: int = 200) -> str:
    return "".join(ch for ch in str(v or "") if ch == "\n" or ch >= " ")[:n].strip()


def _tol(t: Any) -> dict[str, Any] | None:
    if not isinstance(t, dict):
        return None
    kind = t.get("kind") if t.get("kind") in ("sym", "dev", "limits", "fit") else None
    if kind is None:
        return None
    if kind == "fit":
        fit = str(t.get("fit") or "").strip()
        if not _FIT.fullmatch(fit):
            raise DrawingInputError("A fit must look like H7, g6 or H7/g6")
        return {"kind": "fit", "fit": fit}
    up = _num(t.get("up", 0.0), -100, 100)
    lo = _num(t.get("lo", 0.0), -100, 100)
    if kind == "sym":
        if up <= 0:
            raise DrawingInputError("A ± tolerance must be greater than zero")
        return {"kind": "sym", "up": up}
    if up < lo:
        raise DrawingInputError("The upper deviation must not be below the lower one")
    return {"kind": kind, "up": up, "lo": lo}


def default_origin(sheet: dict[str, Any]) -> list[float]:
    W, H = sheet_wh(sheet)
    return [round((FRAME["left"] + W - FRAME["right"]) / 2, 2), round((FRAME["top"] + H - FRAME["bottom"] - 50) / 2, 2)]


def sheet_wh(sheet: dict[str, Any]) -> tuple[float, float]:
    w, h = SHEETS[sheet["size"]]
    return (w, h) if sheet.get("orientation", "landscape") == "landscape" else (h, w)


def normalize_sheet(s: Any) -> dict[str, Any]:
    s = dict(s or {})
    size = s.get("size") if s.get("size") in SHEETS else "A3"
    orient = "portrait" if s.get("orientation") == "portrait" else "landscape"
    sc = s.get("scale") or [1, 1]
    try:
        n, d = int(sc[0]), int(sc[1])
    except (TypeError, ValueError, IndexError):
        n, d = 1, 1
    if not (1 <= n <= 100 and 1 <= d <= 10000):
        raise DrawingInputError("The scale must be a ratio like 1:2 or 5:1")
    out = {"size": size, "orientation": orient, "scale": [n, d],
           "projection": "third" if s.get("projection") == "third" else "first",
           "units": "in" if s.get("units") == "in" else "mm"}
    out["origin"] = _pt(s["origin"]) if s.get("origin") is not None else default_origin(out)
    return out


TITLE_KEYS = ("title", "drawing_no", "material", "company", "drawn_by", "checked_by", "date", "tolerance")


def normalize_doc(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and clean a drafting document from the client. Raises DrawingInputError with a plain message."""
    if not isinstance(raw, dict):
        raise DrawingInputError("The drawing is malformed")
    sheet = normalize_sheet(raw.get("sheet"))
    title = {k: _txt((raw.get("title") or {}).get(k), 60) for k in TITLE_KEYS}
    g = raw.get("geom") or {}
    pts_in, ents_in = list(g.get("points") or []), list(g.get("entities") or [])
    if len(pts_in) > LIMITS["points"] or len(ents_in) > LIMITS["entities"]:
        raise DrawingInputError("The drawing has too many elements")
    points, pid = [], set()
    for p in pts_in:
        i = _id(p.get("id"))
        if i in pid:
            continue
        pid.add(i)
        points.append({"id": i, "x": _num(p.get("x")), "y": _num(p.get("y"))})
    entities, eid = [], set()
    for e in ents_in:
        i, t = _id(e.get("id")), e.get("type")
        layer = e.get("layer") if e.get("layer") in LAYER_STYLE else ("construction" if e.get("construction") else "visible")
        if i in eid:
            continue
        if t == "line" and e.get("p1") in pid and e.get("p2") in pid and e["p1"] != e["p2"]:
            entities.append({"id": i, "type": "line", "p1": e["p1"], "p2": e["p2"], "layer": layer})
        elif t == "circle" and e.get("c") in pid:
            entities.append({"id": i, "type": "circle", "c": e["c"], "r": _num(e.get("r"), 1e-6, 1e6), "layer": layer})
        elif t == "arc" and all(e.get(k) in pid for k in ("c", "p1", "p2")) and e["p1"] != e["p2"]:
            entities.append({"id": i, "type": "arc", "c": e["c"], "p1": e["p1"], "p2": e["p2"], "layer": layer})
        else:
            raise DrawingInputError("A drawing entity refers to a point that does not exist")
        eid.add(i)
    dims_in, annos_in = list(raw.get("dims") or []), list(raw.get("annos") or [])
    if len(dims_in) > LIMITS["dims"] or len(annos_in) > LIMITS["annos"]:
        raise DrawingInputError("The drawing has too many annotations")
    dims = []
    for d in dims_in:
        t = d.get("type")
        rec: dict[str, Any] = {"id": _id(d.get("id")), "type": t, "pos": _pt(d.get("pos"))}
        if t == "linear":
            rec |= {"orient": d.get("orient") if d.get("orient") in ("h", "v", "aligned") else "aligned",
                    "a": _id(d.get("a")), "b": _id(d.get("b"))}
        elif t in ("radius", "diameter"):
            rec["ent"] = _id(d.get("ent"))
        elif t == "angle":
            rec |= {"l1": _id(d.get("l1")), "l2": _id(d.get("l2"))}
        elif t == "ordinate":
            rec |= {"axis": "y" if d.get("axis") == "y" else "x", "origin": _id(d.get("origin")), "pt": _id(d.get("pt"))}
        else:
            raise DrawingInputError("Unknown dimension type")
        for k in ("prefix", "suffix"):
            if d.get(k):
                rec[k] = _txt(d[k], 24)
        tl = _tol(d.get("tol"))
        if tl:
            rec["tol"] = tl
        dims.append(rec)
    annos = [_anno(a) for a in annos_in]
    notes = [_txt(n, 300) for n in (raw.get("notes") or [])[:40] if _txt(n, 300)]
    revs = []
    for r in (raw.get("revisions") or [])[:20]:
        if isinstance(r, dict):
            revs.append({"rev": _txt(r.get("rev"), 6), "change": _txt(r.get("change"), 120),
                         "date": _txt(r.get("date"), 12), "by": _txt(r.get("by"), 30)})
    return {"schema": SCHEMA, "sheet": sheet, "title": title,
            "geom": {"points": points, "entities": entities, "constraints": []}, "dims": dims, "annos": annos,
            "notes": notes, "revisions": revs}


def _anno(a: dict[str, Any]) -> dict[str, Any]:
    t = a.get("type")
    rec: dict[str, Any] = {"id": _id(a.get("id")), "type": t}
    if t == "text":
        rec |= {"pos": _pt(a.get("pos")), "text": _txt(a.get("text"), 500) or "TEXT",
                "size": _num(a.get("size", 3.5), 1.8, 20)}
    elif t == "leader":
        pts = [_pt(p) for p in (a.get("pts") or [])[:6]]
        if len(pts) < 2:
            raise DrawingInputError("A leader needs at least two points")
        rec |= {"pts": pts, "text": _txt(a.get("text"), 120)}
    elif t == "balloon":
        rec |= {"tip": _pt(a.get("tip")), "pos": _pt(a.get("pos")), "text": _txt(a.get("text"), 4) or "1"}
    elif t == "surface":
        rec |= {"pos": _pt(a.get("pos")), "text": _txt(a.get("text"), 24),
                "removal": a.get("removal") if a.get("removal") in ("any", "required", "prohibited") else "required"}
        if a.get("tip") is not None:
            rec["tip"] = _pt(a["tip"])
    elif t == "gdt":
        sym = a.get("symbol")
        if sym not in GDT_SYMBOLS:
            raise DrawingInputError("Unknown geometric tolerance symbol")
        tol = _txt(a.get("tol"), 10)
        if not re.fullmatch(r"\d+(\.\d+)?", tol):
            raise DrawingInputError("A geometric tolerance value must be a number you enter, e.g. 0.05")
        datums = [d for d in (str(x).strip().upper() for x in (a.get("datums") or [])[:3]) if re.fullmatch(r"[A-Z]{1,2}", d)]
        if sym in GDT_NEEDS_DATUM and not datums:
            raise DrawingInputError("This geometric tolerance needs a datum reference (ISO 1101)")
        rec |= {"pos": _pt(a.get("pos")), "symbol": sym, "tol": tol, "dia": bool(a.get("dia")),
                "mod": a.get("mod") if a.get("mod") in ("M", "L") else "", "datums": datums}
        if a.get("tip") is not None:
            rec["tip"] = _pt(a["tip"])
    elif t == "datum":
        letter = str(a.get("letter") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{1,2}", letter):
            raise DrawingInputError("A datum letter must be A to Z")
        rec |= {"pos": _pt(a.get("pos")), "tip": _pt(a.get("tip")), "letter": letter}
    elif t == "centermark":
        rec["ent"] = _id(a.get("ent"))
    elif t == "hatch":
        loops = [[_id(x) for x in lp][:400] for lp in (a.get("loops") or [])[:40] if lp]
        if not loops:
            raise DrawingInputError("A hatch needs a closed boundary")
        rec |= {"loops": loops, "spacing": _num(a.get("spacing", 3.0), 0.5, 20)}
    else:
        raise DrawingInputError("Unknown annotation type")
    return rec


def new_doc(sheet: dict[str, Any] | None = None, title: dict[str, Any] | None = None) -> dict[str, Any]:
    return normalize_doc({"sheet": sheet or {}, "title": title or {}, "geom": {}, "dims": [], "annos": []})


# ----------------------------------------------------------------------------- geometry
class Geo:
    """Read access to a document's geometry in drawing units (y up) and paper millimetres (y down)."""

    def __init__(self, doc: dict[str, Any]) -> None:
        sh = doc["sheet"]
        self.k = UNITS[sh["units"]] * sh["scale"][0] / sh["scale"][1]  # paper mm per drawing unit
        self.ox, self.oy = sh["origin"]
        self.pts = {p["id"]: (p["x"], p["y"]) for p in doc["geom"]["points"]}
        self.ents = {e["id"]: e for e in doc["geom"]["entities"]}
        self.decimals = 3 if sh["units"] == "in" else 2

    def P(self, p: tuple[float, float] | list[float]) -> tuple[float, float]:
        return (self.ox + p[0] * self.k, self.oy - p[1] * self.k)

    def M(self, q: tuple[float, float]) -> tuple[float, float]:
        """Paper -> drawing units."""
        return ((q[0] - self.ox) / self.k, (self.oy - q[1]) / self.k)

    def circle(self, eid: str) -> tuple[tuple[float, float], float, dict[str, Any]] | None:
        e = self.ents.get(eid)
        if e is None or e["type"] == "line" or e["c"] not in self.pts:
            return None
        c = self.pts[e["c"]]
        if e["type"] == "circle":
            return c, e["r"], e
        p1 = self.pts[e["p1"]]
        return c, math.hypot(p1[0] - c[0], p1[1] - c[1]), e

    def line(self, eid: str) -> tuple[tuple[float, float], tuple[float, float]] | None:
        e = self.ents.get(eid)
        if e is None or e["type"] != "line":
            return None
        return self.pts[e["p1"]], self.pts[e["p2"]]

    def arc_angles(self, e: dict[str, Any]) -> tuple[float, float]:
        """Start angle and sweep (degrees, CCW) of an arc entity."""
        c, a, b = self.pts[e["c"]], self.pts[e["p1"]], self.pts[e["p2"]]
        a0 = math.degrees(math.atan2(a[1] - c[1], a[0] - c[0]))
        sw = (math.degrees(math.atan2(b[1] - c[1], b[0] - c[0])) - a0) % 360.0
        return a0, sw or 360.0

    def tess(self, eid: str, n_arc: int = 48) -> list[tuple[float, float]]:
        """Polyline of an entity in drawing units (start to end)."""
        e = self.ents[eid]
        if e["type"] == "line":
            return [self.pts[e["p1"]], self.pts[e["p2"]]]
        c = self.pts[e["c"]]
        if e["type"] == "circle":
            r = e["r"]
            return [(c[0] + r * math.cos(2 * math.pi * i / n_arc), c[1] + r * math.sin(2 * math.pi * i / n_arc))
                    for i in range(n_arc + 1)]
        a0, sw = self.arc_angles(e)
        _, r, _ = self.circle(eid)  # type: ignore[misc]
        n = max(4, int(n_arc * sw / 360) + 1)
        return [(c[0] + r * math.cos(math.radians(a0 + sw * i / n)), c[1] + r * math.sin(math.radians(a0 + sw * i / n)))
                for i in range(n + 1)]


def chain_loop(geo: Geo, ids: list[str]) -> list[tuple[float, float]] | None:
    """Join the entities of one closed boundary into a polygon (drawing units); None when they don't close."""
    ids = [i for i in ids if i in geo.ents]
    if not ids:
        return None
    if len(ids) == 1 and geo.ents[ids[0]]["type"] == "circle":
        return geo.tess(ids[0])[:-1]
    segs = [geo.tess(i) for i in ids if geo.ents[i]["type"] != "circle"]
    if not segs:
        return None
    tol = 1e-6 * max(1.0, max(abs(v) for s in segs for p in s for v in p))
    out = list(segs.pop(0))
    while segs:
        end = out[-1]
        for j, s in enumerate(segs):
            if math.dist(s[0], end) <= tol * 10:
                out += s[1:]
                break
            if math.dist(s[-1], end) <= tol * 10:
                out += s[::-1][1:]
                break
        else:
            return None
        segs.pop(j)
    if math.dist(out[0], out[-1]) > tol * 10:
        return None
    return out[:-1]


def line_dir(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    d = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)


def _intersect(a1: tuple[float, float], a2: tuple[float, float], b1: tuple[float, float],
               b2: tuple[float, float]) -> tuple[float, float] | None:
    d1 = (a2[0] - a1[0], a2[1] - a1[1])
    d2 = (b2[0] - b1[0], b2[1] - b1[1])
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-12 * (math.hypot(*d1) * math.hypot(*d2) or 1):
        return None
    t = ((b1[0] - a1[0]) * d2[1] - (b1[1] - a1[1]) * d2[0]) / den
    return (a1[0] + d1[0] * t, a1[1] + d1[1] * t)


def angle_sector(geo: Geo, d: dict[str, Any]) -> dict[str, Any] | None:
    """The angle between two lines in the sector that contains the dimension's position (drawing units)."""
    l1, l2 = geo.line(d["l1"]), geo.line(d["l2"])
    if l1 is None or l2 is None:
        return None
    x = _intersect(l1[0], l1[1], l2[0], l2[1])
    if x is None:
        return None
    q = d["pos"]
    aq = math.degrees(math.atan2(q[1] - x[1], q[0] - x[0])) % 360
    u1, u2 = line_dir(*l1), line_dir(*l2)
    best = None
    for s1 in (1, -1):
        for s2 in (1, -1):
            a = math.degrees(math.atan2(s1 * u1[1], s1 * u1[0])) % 360
            b = math.degrees(math.atan2(s2 * u2[1], s2 * u2[0])) % 360
            lo, sw = (a, (b - a) % 360) if (b - a) % 360 <= 180 else (b, (a - b) % 360)
            if sw < 1e-9:
                continue
            if (aq - lo) % 360 <= sw + 1e-9 and (best is None or sw < best["sweep"]):
                best = {"x": x, "a0": lo, "sweep": sw, "r": math.dist(q, x)}
    return best


def measure(geo: Geo, d: dict[str, Any]) -> float | None:
    """The value of a dimension, measured from the geometry (None when a reference is missing)."""
    t = d["type"]
    if t == "linear":
        if d["a"] not in geo.pts or d["b"] not in geo.pts:
            return None
        a, b = geo.pts[d["a"]], geo.pts[d["b"]]
        if d["orient"] == "h":
            return abs(b[0] - a[0])
        if d["orient"] == "v":
            return abs(b[1] - a[1])
        return math.dist(a, b)
    if t in ("radius", "diameter"):
        c = geo.circle(d["ent"])
        if c is None:
            return None
        return c[1] if t == "radius" else 2 * c[1]
    if t == "angle":
        s = angle_sector(geo, d)
        return None if s is None else s["sweep"]
    if t == "ordinate":
        if d["origin"] not in geo.pts or d["pt"] not in geo.pts:
            return None
        i = 0 if d["axis"] == "x" else 1
        return geo.pts[d["pt"]][i] - geo.pts[d["origin"]][i]
    return None


def dim_text(geo: Geo, d: dict[str, Any], value: float) -> tuple[str, list[str]]:
    """The printed value: prefix (Ø, R, 2X …), measured value, tolerance or fit, suffix."""
    dec = geo.decimals
    if d["type"] == "angle":
        main = f"{fmt(value, 1)}°"
        stack: list[str] = []
        t = d.get("tol") or {}
        if t.get("kind") == "sym":
            main += f" ±{fmt(t['up'], 2)}°"
        elif t.get("kind") in ("dev", "limits"):
            stack = [fmt_dev(t["up"], 2) + "°", fmt_dev(t["lo"], 2) + "°"]
    else:
        main, stack = tol_parts(abs(value) if d["type"] != "ordinate" else value, d.get("tol"), dec)
        sym = {"diameter": "Ø", "radius": "R"}.get(d["type"], "")
        if main:
            main = sym + main
        elif stack and sym:
            stack = [sym + s for s in stack]
    pre, suf = d.get("prefix", ""), d.get("suffix", "")
    if pre:
        main = f"{pre} {main}".strip() if not pre.endswith(" ") else pre + main
    if suf:
        main = f"{main} {suf}".strip()
    return main, stack


# ----------------------------------------------------------------------------- primitives
class Prims:
    def __init__(self) -> None:
        self.out: list[dict[str, Any]] = []

    def line(self, layer: str, a: tuple[float, float], b: tuple[float, float], **kw: Any) -> None:
        if math.dist(a, b) > 1e-9:
            self.out.append({"t": "line", "l": layer, "p": [a[0], a[1], b[0], b[1]], **kw})

    def poly(self, layer: str, pts: list[tuple[float, float]], closed: bool = False, **kw: Any) -> None:
        self.out.append({"t": "poly", "l": layer, "p": [list(p) for p in pts], "closed": closed, **kw})

    def circle(self, layer: str, c: tuple[float, float], r: float, **kw: Any) -> None:
        self.out.append({"t": "circle", "l": layer, "p": [c[0], c[1], r], **kw})

    def arc(self, layer: str, c: tuple[float, float], r: float, a0: float, a1: float, **kw: Any) -> None:
        self.out.append({"t": "arc", "l": layer, "p": [c[0], c[1], r, a0, a1], **kw})

    def fill(self, layer: str, pts: list[tuple[float, float]], **kw: Any) -> None:
        self.out.append({"t": "fill", "l": layer, "p": [list(p) for p in pts], **kw})

    def arrow(self, tip: tuple[float, float], frm: tuple[float, float], layer: str = "dim_n", **kw: Any) -> None:
        dx, dy = tip[0] - frm[0], tip[1] - frm[1]
        n = math.hypot(dx, dy) or 1.0
        ux, uy = dx / n, dy / n
        bx, by = tip[0] - ux * ARROW, tip[1] - uy * ARROW
        self.fill(layer, [tip, (bx - uy * ARROW_W, by + ux * ARROW_W), (bx + uy * ARROW_W, by - ux * ARROW_W)], **kw)

    def text(self, x: float, y: float, size: float, txt: str, anchor: str = "middle", rot: float = 0.0,
             font: str = "regular", kind: str = "anno", **kw: Any) -> dict[str, Any]:
        t = {"t": "text", "l": "text", "x": x, "y": y, "s": size, "txt": txt, "anchor": anchor, "rot": round(rot, 4),
             "font": font, "color": "normal", "kind": kind, "tag": None, "param": None, "ref": None,
             "box": rot_text_box(x, y, size, txt, anchor, rot, font), **kw}
        self.out.append(t)
        return t


def rot_text_box(x: float, y: float, size: float, txt: str, anchor: str = "start", rot: float = 0.0,
                 font: str = "regular") -> list[float]:
    """Axis-aligned paper bbox of a text rotated ``rot`` degrees counter-clockwise about its anchor."""
    w = text_width(txt, size, font)
    off = {"start": 0.0, "middle": -w / 2, "end": -w}[anchor]
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    xs, ys = [], []
    for u, v in ((off, -0.21 * size), (off + w, -0.21 * size), (off, 0.73 * size), (off + w, 0.73 * size)):
        xs.append(x + u * c - v * s)
        ys.append(y - (u * s + v * c))
    return [min(xs), min(ys), max(xs), max(ys)]


def _readable(theta: float) -> float:
    """Text angle (degrees CCW) readable from the bottom or the right of the sheet (ISO 129-1 method 1)."""
    t = (theta + 180) % 360 - 180
    if t > 90.0001:
        t -= 180
    elif t <= -90.0001:
        t += 180
    return t


def _up(theta: float) -> tuple[float, float]:
    """Paper (y down) unit vector pointing 'up' for text at angle theta."""
    return (-math.sin(math.radians(theta)), -math.cos(math.radians(theta)))


def _along(theta: float) -> tuple[float, float]:
    return (math.cos(math.radians(theta)), -math.sin(math.radians(theta)))


def _stack_w(stack: list[str], size: float) -> float:
    return max((text_width(t, size * 0.7) for t in stack), default=0.0)


def value_width(main: str, stack: list[str], size: float) -> float:
    """Paper width of a value with its stacked deviations."""
    if not main:
        return _stack_w(stack, size)
    return text_width(main, size) + (_stack_w(stack, size) + 0.6 if stack else 0.0)


def _value_text(pr: Prims, x: float, y: float, theta: float, size: float, main: str, stack: list[str],
                dim_id: str, value: float) -> None:
    """Value on its dimension line: main text centred at (x, y) (baseline), deviations stacked after it."""
    kw = {"kind": "dim", "dim": dim_id, "value": round(value, 6)}
    if main:
        pr.text(x, y, size, main, "middle", theta, **kw)
    if stack:
        sz = size * 0.7
        ax, ay = _along(theta)
        ux, uy = _up(theta)
        wm = text_width(main, size) if main else 0.0
        if main:
            sx, sy = x + ax * (wm / 2 + 0.6), y + ay * (wm / 2 + 0.6)
            anchor = "start"
        else:
            sx, sy = x, y
            anchor = "middle"
        pr.text(sx + ux * (sz * 0.75), sy + uy * (sz * 0.75), sz, stack[0], anchor, theta, **kw)
        pr.text(sx - ux * (sz * 0.45), sy - uy * (sz * 0.45), sz, stack[1], anchor, theta, **kw)


def text_size(doc: dict[str, Any]) -> float:
    return 3.0 if doc["sheet"]["size"] in ("A4", "ANSI A") else 3.5


def _linear(pr: Prims, geo: Geo, d: dict[str, Any], size: float) -> None:
    value = measure(geo, d)
    if value is None:
        return
    A, B = geo.P(geo.pts[d["a"]]), geo.P(geo.pts[d["b"]])
    Q = geo.P(d["pos"])
    if d["orient"] == "h":
        u = (1.0, 0.0)
    elif d["orient"] == "v":
        u = (0.0, 1.0)
    else:
        u = line_dir(A, B)
        if math.dist(A, B) < 1e-9:
            return
    n = (-u[1], u[0])
    dq = (Q[0] - A[0]) * n[0] + (Q[1] - A[1]) * n[1]
    db = (A[0] - B[0]) * n[0] + (A[1] - B[1]) * n[1] + dq
    A2 = (A[0] + n[0] * dq, A[1] + n[1] * dq)
    B2 = (B[0] + n[0] * db, B[1] + n[1] * db)
    lay = "dim_n"
    kw = {"dim": d["id"]}
    for P0, P1, off in ((A, A2, dq), (B, B2, db)):
        if abs(off) > EXT_GAP:
            sg = 1.0 if off > 0 else -1.0
            pr.line(lay, (P0[0] + n[0] * sg * EXT_GAP, P0[1] + n[1] * sg * EXT_GAP),
                    (P1[0] + n[0] * sg * EXT_OVER, P1[1] + n[1] * sg * EXT_OVER), **kw)
    # dimension line along u from A2 to B2, text at Q's position along the line
    span = (B2[0] - A2[0]) * u[0] + (B2[1] - A2[1]) * u[1]
    if span < 0:
        A2, B2, span = B2, A2, -span
    tq = (Q[0] - A2[0]) * u[0] + (Q[1] - A2[1]) * u[1]
    main, stack = dim_text(geo, d, value)
    theta = _readable(math.degrees(math.atan2(-u[1], u[0])))
    tw = value_width(main, stack, size)
    inside = span >= 2 * ARROW + 1.0
    lo, hi = 0.0, span
    if tq - tw / 2 < 0:
        lo = tq - tw / 2 - 1.0
    if tq + tw / 2 > span:
        hi = tq + tw / 2 + 1.0
    if not inside:
        lo, hi = min(lo, -ARROW - 3.0), max(hi, span + ARROW + 3.0)
    pr.line(lay, (A2[0] + u[0] * lo, A2[1] + u[1] * lo), (A2[0] + u[0] * hi, A2[1] + u[1] * hi), **kw)
    if inside:
        pr.arrow(A2, (A2[0] + u[0], A2[1] + u[1]), lay, **kw)
        pr.arrow(B2, (B2[0] - u[0], B2[1] - u[1]), lay, **kw)
    else:
        pr.arrow(A2, (A2[0] - u[0], A2[1] - u[1]), lay, **kw)
        pr.arrow(B2, (B2[0] + u[0], B2[1] + u[1]), lay, **kw)
    ux, uy = _up(theta)
    cx, cy = A2[0] + u[0] * tq, A2[1] + u[1] * tq
    _value_text(pr, cx + ux * TXT_GAP, cy + uy * TXT_GAP, theta, size, main, stack, d["id"], value)


def _shoulder_text(pr: Prims, Q: tuple[float, float], from_x: float, size: float, main: str, stack: list[str],
                   d_id: str, value: float, lay: str = "dim_n") -> None:
    """Horizontal shoulder at Q (on the side away from ``from_x``) with the value above it."""
    w = value_width(main, stack, size)
    sg = 1.0 if Q[0] >= from_x else -1.0
    end = (Q[0] + sg * (w + 2.0), Q[1])
    pr.line(lay, Q, end, dim=d_id)
    mid = (Q[0] + end[0]) / 2 - ((_stack_w(stack, size) + 0.6) / 2 if stack and main else 0.0)
    _value_text(pr, mid, Q[1] - TXT_GAP, 0.0, size, main, stack, d_id, value)


def _radial(pr: Prims, geo: Geo, d: dict[str, Any], size: float) -> None:
    c = geo.circle(d["ent"])
    if c is None:
        return
    value = measure(geo, d)
    assert value is not None
    C = geo.P(c[0])
    r = c[1] * geo.k
    Q = geo.P(d["pos"])
    dq = math.dist(C, Q)
    w = ((Q[0] - C[0]) / dq, (Q[1] - C[1]) / dq) if dq > 1e-9 else (math.sqrt(0.5), -math.sqrt(0.5))
    P = (C[0] + w[0] * r, C[1] + w[1] * r)
    main, stack = dim_text(geo, d, value)
    lay, kw = "dim_n", {"dim": d["id"]}
    if dq <= r - 1e-6:  # inside: along the radius / diameter, value aligned with the line
        start = C if d["type"] == "radius" else (C[0] - w[0] * r, C[1] - w[1] * r)
        pr.line(lay, start, P, **kw)
        pr.arrow(P, C, lay, **kw)
        if d["type"] == "diameter":
            pr.arrow(start, C, lay, **kw)
        theta = _readable(math.degrees(math.atan2(-w[1], w[0])))
        ux, uy = _up(theta)
        _value_text(pr, Q[0] + ux * TXT_GAP, Q[1] + uy * TXT_GAP, theta, size, main, stack, d["id"], value)
        return
    # outside: leader pointing at the centre, arrow on the circle from outside, horizontal shoulder with the value
    if d["type"] == "radius":
        pr.line(lay, C, Q, **kw)
        pr.arrow(P, C, lay, **kw)
    else:
        pr.line(lay, (C[0] - w[0] * r, C[1] - w[1] * r), Q, **kw)
        pr.arrow(P, Q, lay, **kw)
        pr.arrow((C[0] - w[0] * r, C[1] - w[1] * r), C, lay, **kw)
    _shoulder_text(pr, Q, C[0], size, main, stack, d["id"], value)


def _angular(pr: Prims, geo: Geo, d: dict[str, Any], size: float) -> None:
    s = angle_sector(geo, d)
    if s is None:
        return
    X = geo.P(s["x"])
    R = s["r"] * geo.k
    if R < 1e-6:
        return
    lay, kw = "dim_n", {"dim": d["id"]}
    a0, a1 = s["a0"], s["a0"] + s["sweep"]
    pr.arc(lay, X, R, a0, a1, **kw)
    for ang, sg in ((a0, 1), (a1, -1)):
        tip = (X[0] + R * math.cos(math.radians(ang)), X[1] - R * math.sin(math.radians(ang)))
        tang = (-math.sin(math.radians(ang)) * sg, -math.cos(math.radians(ang)) * sg)  # paper: towards the arc interior
        pr.arrow(tip, (tip[0] + tang[0], tip[1] + tang[1]), lay, **kw)
        # extension line from the nearer end of the line if it doesn't reach the arc
        lid = d["l1"] if ang == a0 else d["l2"]
        ln = geo.line(lid)
        if ln:
            far = max((geo.P(p) for p in ln), key=lambda p: (p[0] - X[0]) * math.cos(math.radians(ang)) - (p[1] - X[1]) * math.sin(math.radians(ang)))
            reach = (far[0] - X[0]) * math.cos(math.radians(ang)) - (far[1] - X[1]) * math.sin(math.radians(ang))
            if reach < R - EXT_GAP:
                st = max(reach, 0.0) + EXT_GAP
                pr.line(lay, (X[0] + st * math.cos(math.radians(ang)), X[1] - st * math.sin(math.radians(ang))),
                        (X[0] + (R + EXT_OVER) * math.cos(math.radians(ang)), X[1] - (R + EXT_OVER) * math.sin(math.radians(ang))), **kw)
    mid = math.radians(a0 + s["sweep"] / 2)
    main, stack = dim_text(geo, d, s["sweep"])
    tx, ty = X[0] + (R + TXT_GAP + size * 0.6) * math.cos(mid), X[1] - (R + TXT_GAP + size * 0.6) * math.sin(mid)
    _value_text(pr, tx, ty + size * 0.36, 0.0, size, main, stack, d["id"], s["sweep"])


def _ordinate(pr: Prims, geo: Geo, d: dict[str, Any], size: float) -> None:
    value = measure(geo, d)
    if value is None:
        return
    F = geo.P(geo.pts[d["pt"]])
    Q = geo.P(d["pos"])
    lay, kw = "dim_n", {"dim": d["id"]}
    main, stack = dim_text(geo, d, value)
    if d["axis"] == "x":  # leader runs vertically, value reads along it
        sg = -1.0 if Q[1] < F[1] else 1.0
        pr.line(lay, (F[0], F[1] + sg * EXT_GAP), (F[0], Q[1]), **kw)
        _value_text(pr, F[0] - TXT_GAP, Q[1] + sg * (text_width(main, size) / 2 + 1.0), 90.0, size, main, stack, d["id"], value)
    else:
        sg = -1.0 if Q[0] < F[0] else 1.0
        pr.line(lay, (F[0] + sg * EXT_GAP, F[1]), (Q[0], F[1]), **kw)
        _value_text(pr, Q[0] + sg * (text_width(main, size) / 2 + 1.0), F[1] - TXT_GAP, 0.0, size, main, stack, d["id"], value)


# ----------------------------------------------------------------------------- annotations
def _gdt_symbol(pr: Prims, sym: str, cx: float, cy: float, h: float, **kw: Any) -> None:
    """ISO 1101 characteristic symbols drawn as vectors (fonts rarely carry them), centred in an h x h cell."""
    L, s = "dim_n", h * 0.32
    if sym == "straightness":
        pr.line(L, (cx - s, cy), (cx + s, cy), **kw)
    elif sym == "flatness":
        pr.poly(L, [(cx - s, cy + s * 0.5), (cx + s * 0.5, cy + s * 0.5), (cx + s, cy - s * 0.5), (cx - s * 0.5, cy - s * 0.5)], True, **kw)
    elif sym == "circularity":
        pr.circle(L, (cx, cy), s * 0.8, **kw)
    elif sym == "cylindricity":
        pr.circle(L, (cx, cy), s * 0.6, **kw)
        pr.line(L, (cx - s * 0.95, cy + s), (cx - s * 0.25, cy - s), **kw)
        pr.line(L, (cx + s * 0.25, cy + s), (cx + s * 0.95, cy - s), **kw)
    elif sym == "profile_line":
        pr.arc(L, (cx, cy + s * 0.5), s, 0, 180, **kw)
    elif sym == "profile_surface":
        pr.arc(L, (cx, cy + s * 0.5), s, 0, 180, **kw)
        pr.line(L, (cx - s, cy + s * 0.5), (cx + s, cy + s * 0.5), **kw)
    elif sym == "parallelism":
        pr.line(L, (cx - s, cy + s), (cx - s * 0.2, cy - s), **kw)
        pr.line(L, (cx + s * 0.2, cy + s), (cx + s, cy - s), **kw)
    elif sym == "perpendicularity":
        pr.line(L, (cx - s, cy + s), (cx + s, cy + s), **kw)
        pr.line(L, (cx, cy + s), (cx, cy - s), **kw)
    elif sym == "angularity":
        pr.line(L, (cx - s, cy + s), (cx + s, cy + s), **kw)
        pr.line(L, (cx - s, cy + s), (cx + s, cy - s * 0.6), **kw)
    elif sym == "position":
        pr.circle(L, (cx, cy), s * 0.6, **kw)
        pr.line(L, (cx - s, cy), (cx + s, cy), **kw)
        pr.line(L, (cx, cy - s), (cx, cy + s), **kw)
    elif sym == "concentricity":
        pr.circle(L, (cx, cy), s * 0.85, **kw)
        pr.circle(L, (cx, cy), s * 0.45, **kw)
    elif sym == "symmetry":
        pr.line(L, (cx - s, cy), (cx + s, cy), **kw)
        pr.line(L, (cx - s * 0.6, cy - s * 0.6), (cx + s * 0.6, cy - s * 0.6), **kw)
        pr.line(L, (cx - s * 0.6, cy + s * 0.6), (cx + s * 0.6, cy + s * 0.6), **kw)
    elif sym in ("circular_runout", "total_runout"):
        tip = (cx + s * 0.6, cy - s)
        pr.line(L, (cx - s * 0.6, cy + s), tip, **kw)
        pr.arrow(tip, (cx - s * 0.6, cy + s), L, **kw)
        if sym == "total_runout":
            tip2 = (cx + s * 1.1, cy - s * 0.4)
            pr.line(L, (cx - s * 0.1, cy + s), tip2, **kw)
            pr.line(L, (cx - s * 0.6, cy + s), (cx + s * 0.4, cy + s), **kw)


def gdt_cells(a: dict[str, Any], size: float) -> list[tuple[str, float]]:
    """(content, width) of the frame cells: symbol, tolerance, datums."""
    h = 2 * size
    tol = ("Ø" if a["dia"] else "") + a["tol"] + (f" {a['mod']}" if a["mod"] else "")
    cells = [("@sym", h), (tol, text_width(tol, size) + 2.4)]
    cells += [(dt, max(h, text_width(dt, size) + 2.4)) for dt in a["datums"]]
    return cells


def _annotation(pr: Prims, geo: Geo, a: dict[str, Any], size: float) -> None:
    t, kw, L = a["type"], {"anno": a["id"]}, "dim_n"
    if t == "text":
        P = geo.P(a["pos"])
        for i, ln in enumerate(a["text"].split("\n")):
            pr.text(P[0], P[1] + i * a["size"] * 1.5, a["size"], ln, "start", **kw)
    elif t == "leader":
        pts = [geo.P(p) for p in a["pts"]]
        pr.poly(L, pts, **kw)
        pr.arrow(pts[0], pts[1], L, **kw)
        if a["text"]:
            end = pts[-1]
            sg = 1.0 if end[0] >= pts[-2][0] else -1.0
            w = text_width(a["text"], size)
            pr.line(L, end, (end[0] + sg * (w + 2.0), end[1]), **kw)
            pr.text(end[0] + sg * (w / 2 + 1.0), end[1] - TXT_GAP, size, a["text"], "middle", **kw)
    elif t == "balloon":
        tip, P = geo.P(a["tip"]), geo.P(a["pos"])
        r = size * 1.45
        dd = math.dist(tip, P)
        if dd > r:
            e = (P[0] + (tip[0] - P[0]) / dd * r, P[1] + (tip[1] - P[1]) / dd * r)
            pr.line(L, e, tip, **kw)
        pr.circle(L, P, r, **kw)
        pr.fill(L, [(tip[0] + 0.7 * math.cos(i * math.pi / 4), tip[1] + 0.7 * math.sin(i * math.pi / 4)) for i in range(8)], **kw)
        pr.text(P[0], P[1] + size * 0.36, size, a["text"], "middle", **kw)
    elif t == "surface":
        P = geo.P(a["pos"])
        if a.get("tip") is not None:
            tip = geo.P(a["tip"])
            pr.line(L, tip, P, **kw)
            pr.arrow(tip, P, L, **kw)
        h1, h2 = 1.4 * size, 2.8 * size
        tan60 = math.tan(math.radians(60))
        left = (P[0] - h1 / tan60, P[1] - h1)
        right = (P[0] + h2 / tan60, P[1] - h2)
        pr.line(L, left, P, **kw)
        pr.line(L, P, right, **kw)
        if a["removal"] == "required":
            pr.line(L, left, (P[0] + h1 / tan60, P[1] - h1), **kw)
        elif a["removal"] == "prohibited":
            pr.circle(L, (P[0], P[1] - h1 * 0.62), h1 * 0.36, **kw)
        if a["text"]:
            w = text_width(a["text"], size)
            pr.line(L, right, (right[0] + w + 2.0, right[1]), **kw)
            pr.text(right[0] + 1.0, right[1] + size + 1.2, size, a["text"], "start", **kw)
    elif t == "gdt":
        P = geo.P(a["pos"])
        h = 2 * size
        x = P[0]
        y0 = P[1] - h / 2
        if a.get("tip") is not None:
            tip = geo.P(a["tip"])
            pr.poly(L, [tip, (tip[0], P[1]), P] if abs(tip[0] - P[0]) > 1 and abs(tip[1] - P[1]) > 1 else [tip, P], **kw)
            pr.arrow(tip, (tip[0], P[1]) if abs(tip[1] - P[1]) > 1 else P, L, **kw)
        for content, w in gdt_cells(a, size):
            pr.poly(L, [(x, y0), (x + w, y0), (x + w, y0 + h), (x, y0 + h)], True, **kw)
            if content == "@sym":
                _gdt_symbol(pr, a["symbol"], x + w / 2, P[1], h, **kw)
            else:
                pr.text(x + w / 2, P[1] + size * 0.36, size, content, "middle", kind="gdt", **kw)
            x += w
    elif t == "datum":
        tip, P = geo.P(a["tip"]), geo.P(a["pos"])
        h = 2 * size
        pr.poly(L, [(P[0] - h / 2, P[1] - h / 2), (P[0] + h / 2, P[1] - h / 2), (P[0] + h / 2, P[1] + h / 2),
                    (P[0] - h / 2, P[1] + h / 2)], True, **kw)
        pr.text(P[0], P[1] + size * 0.36, size, a["letter"], "middle", **kw)
        dd = math.dist(tip, P)
        if dd > h / 2 + 1:
            u = ((tip[0] - P[0]) / dd, (tip[1] - P[1]) / dd)
            start = (P[0] + u[0] * h / 2, P[1] + u[1] * h / 2) if abs(u[1]) >= abs(u[0]) else (P[0] + math.copysign(h / 2, u[0]), P[1])
            pr.line(L, start, tip, **kw)
            n = (-u[1], u[0])
            b = (tip[0] - u[0] * 2.6, tip[1] - u[1] * 2.6)
            pr.fill(L, [(tip[0] + n[0] * 1.5, tip[1] + n[1] * 1.5), (tip[0] - n[0] * 1.5, tip[1] - n[1] * 1.5), b], **kw)
    elif t == "centermark":
        c = geo.circle(a["ent"])
        if c is None:
            return
        C = geo.P(c[0])
        r = c[1] * geo.k + 2.5  # ISO 128: centre lines extend a short distance beyond the outline
        pr.line("center_n", (C[0] - r, C[1]), (C[0] + r, C[1]), **kw)
        pr.line("center_n", (C[0], C[1] - r), (C[0], C[1] + r), **kw)
    elif t == "hatch":
        loops = [chain_loop(geo, lp) for lp in a["loops"]]
        paper = [[list(geo.P(p)) for p in lp] for lp in loops if lp]
        for seg in _hatch(paper, a["spacing"]):
            pr.line("hatch_n", (seg[0], seg[1]), (seg[2], seg[3]), **kw)


# ----------------------------------------------------------------------------- sheet
def meta_of(doc: dict[str, Any]) -> dict[str, Any]:
    t = doc["title"]
    tol = t.get("tolerance") or "Not specified"
    return {"title": t.get("title") or "Untitled 2D drawing", "drawing_no": t.get("drawing_no") or "",
            "material": t.get("material") or "", "drawn_by": t.get("drawn_by") or "", "date": t.get("date") or "",
            "rev": (doc["revisions"][-1]["rev"] if doc.get("revisions") else "DRAFT") or "DRAFT",
            "tolerance": tol, "checked_by": t.get("checked_by") or "", "company": t.get("company") or "",
            "source": "2D ONLY · NO MODEL", "units": doc["sheet"]["units"]}


def frame_prims(doc: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Frame, title block, revision table and notes (paper millimetres) plus the sheet facts the editor needs."""
    sh = doc["sheet"]
    W, H = sheet_wh(sh)
    sc = sh["scale"]
    scale_txt = f"{sc[0]}:{sc[1]}"
    info, tb_box = _info_blocks(W, H, meta_of(doc), scale_txt, sh["projection"] == "first", doc.get("revisions") or [],
                                sh["size"])
    frame = [FRAME["left"], FRAME["top"], W - FRAME["right"], H - FRAME["bottom"]]
    pr = Prims()
    pr.poly("frame", [(frame[0], frame[1]), (frame[2], frame[1]), (frame[2], frame[3]), (frame[0], frame[3])], True)
    # ISO 5457 centring marks
    for x, y, dx, dy in ((W / 2, frame[1], 0, -1), (W / 2, frame[3], 0, 1), (frame[0], H / 2, -1, 0), (frame[2], H / 2, 1, 0)):
        pr.line("frame", (x, y), (x + dx * 5, y + dy * 5))
    prims = pr.out + info.placed(0, 0)
    blocked = [tb_box]
    notes = doc.get("notes") or []
    if notes:
        x0 = FRAME["left"] + 4.0
        width = min(tb_box[0] - x0 - 8.0, 200.0)
        lines: list[tuple[str, str]] = []
        for i, n in enumerate(notes, 1):
            for j, w in enumerate(_wrap(n, width - 6.0, 2.5)):
                lines.append((f"{i}." if j == 0 else "", w))
        nh = 5.5 + 3.6 * len(lines) + 1.5
        yb = H - FRAME["bottom"] - 3.0
        y0 = yb - nh
        np_ = Prims()
        np_.text(x0, y0 + 3.6, 2.6, "NOTES", "start", font="bold", kind="note")
        for i, (num, ln) in enumerate(lines):
            yy = y0 + 5.5 + 3.6 * (i + 1) - 0.8
            if num:
                np_.text(x0, yy, 2.5, num, "start", kind="note")
            np_.text(x0 + 5.0, yy, 2.5, ln, "start", kind="note")
        prims += np_.out
        blocked.append([x0 - 1.0, y0, x0 + width, yb])
    return prims, {"w": W, "h": H, "frame": frame, "blocked": blocked, "scale_txt": scale_txt}


def content_prims(doc: dict[str, Any], *, construction: bool = False) -> list[dict[str, Any]]:
    """Geometry, dimensions and annotations in paper millimetres. Construction geometry only when asked (editor)."""
    geo = Geo(doc)
    pr = Prims()
    size = text_size(doc)
    for e in doc["geom"]["entities"]:
        if e["layer"] == "construction" and not construction:
            continue
        lay, kw = LAYER_STYLE[e["layer"]], {"ent": e["id"], "dlayer": e["layer"]}
        if e["type"] == "line":
            pr.line(lay, geo.P(geo.pts[e["p1"]]), geo.P(geo.pts[e["p2"]]), **kw)
        elif e["type"] == "circle":
            pr.circle(lay, geo.P(geo.pts[e["c"]]), e["r"] * geo.k, **kw)
        else:
            a0, sw = geo.arc_angles(e)
            c, r, _ = geo.circle(e["id"])  # type: ignore[misc]
            pr.arc(lay, geo.P(c), r * geo.k, a0, a0 + sw, **kw)
    for a in doc["annos"]:
        if a["type"] in ("hatch", "centermark"):
            _annotation(pr, geo, a, size)
    for d in doc["dims"]:
        {"linear": _linear, "radius": _radial, "diameter": _radial, "angle": _angular, "ordinate": _ordinate}[d["type"]](pr, geo, d, size)
    for a in doc["annos"]:
        if a["type"] not in ("hatch", "centermark"):
            _annotation(pr, geo, a, size)
    return pr.out


def compose(doc: dict[str, Any]) -> dict[str, Any]:
    """The printable sheet: same structure as the model drawings' sheets, so render.to_svg / to_pdf draw it."""
    fp, info = frame_prims(doc)
    sc = doc["sheet"]["scale"]
    return {"size": doc["sheet"]["size"], "w": info["w"], "h": info["h"], "scale": list(sc), "scale_txt": info["scale_txt"],
            "projection": doc["sheet"]["projection"], "frame": info["frame"], "blocked": info["blocked"],
            "prims": fp + content_prims(doc), "copy": "issue", "kind": "draft"}


# ----------------------------------------------------------------------------- report and checks
def dimension_report(doc: dict[str, Any]) -> list[dict[str, Any]]:
    geo = Geo(doc)
    out = []
    for d in doc["dims"]:
        v = measure(geo, d)
        rec = {"id": d["id"], "type": d["type"], "value": None if v is None else round(v, 6), "ok": v is not None}
        if v is not None:
            main, stack = dim_text(geo, d, v)
            rec["text"] = " ".join([main, *stack]).strip()
        out.append(rec)
    return out


def sheet_check(doc: dict[str, Any]) -> dict[str, Any]:
    """Layout checks for a 2D-only sheet. There is no model, so nothing here says the part is right: only that every
    dimension still references geometry (associative), the drawing sits inside the frame clear of the title block,
    and no two dimension texts overlap."""
    sheet = compose(doc)
    fr = sheet["frame"]
    dangling = [r["id"] for r in dimension_report(doc) if not r["ok"]]
    geo = Geo(doc)
    for a in doc["annos"]:
        if a["type"] == "centermark" and geo.circle(a["ent"]) is None:
            dangling.append(a["id"])
        if a["type"] == "hatch" and not all(chain_loop(geo, lp) for lp in a["loops"]):
            dangling.append(a["id"])
    content = [p for p in sheet["prims"] if p.get("dim") or p.get("ent") or p.get("anno")]
    outside, over_tb = set(), set()
    for p in content:
        b = _prim_box(p)
        key = p.get("dim") or p.get("ent") or p.get("anno")
        if b[0] < fr[0] or b[1] < fr[1] or b[2] > fr[2] or b[3] > fr[3]:
            outside.add(key)
        elif any(b[0] < q[2] and q[0] < b[2] and b[1] < q[3] and q[1] < b[3] for q in sheet["blocked"]):
            over_tb.add(key)
    texts = [p for p in content if p["t"] == "text" and p.get("dim")]
    overlaps = []
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            if a["dim"] != b["dim"] and a["box"][0] < b["box"][2] and b["box"][0] < a["box"][2] \
                    and a["box"][1] < b["box"][3] and b["box"][1] < a["box"][3]:
                overlaps.append([a["dim"], b["dim"]])
    problems = []
    if dangling:
        problems.append(f"{len(dangling)} annotation(s) lost the geometry they referenced")
    if outside:
        problems.append(f"{len(outside)} item(s) outside the drawing frame")
    if over_tb:
        problems.append(f"{len(over_tb)} item(s) over the title block or notes")
    if overlaps:
        problems.append(f"{len(overlaps)} overlapping dimension value(s)")
    return {"passed": not problems, "problems": problems, "dangling": sorted(dangling), "outside": sorted(outside),
            "over_title_block": sorted(over_tb), "overlaps": overlaps, "model_check": None,
            "note": "Not linked to a model: no model-consistency check (CHK-12) runs on a 2D-only drawing. "
                    "Dimension values are measured from the drawn geometry."}


def _prim_box(p: dict[str, Any]) -> list[float]:
    if p["t"] == "text":
        return p["box"]
    if p["t"] == "line":
        a = p["p"]
        return [min(a[0], a[2]), min(a[1], a[3]), max(a[0], a[2]), max(a[1], a[3])]
    if p["t"] in ("poly", "fill"):
        xs, ys = [q[0] for q in p["p"]], [q[1] for q in p["p"]]
        return [min(xs), min(ys), max(xs), max(ys)]
    cx, cy, r = p["p"][:3]
    return [cx - r, cy - r, cx + r, cy + r]


def summary(doc: dict[str, Any]) -> dict[str, Any]:
    g = doc["geom"]
    return {"entities": len(g["entities"]), "dims": len(doc["dims"]), "annos": len(doc["annos"]),
            "sheet": f"{doc['sheet']['size']} {doc['sheet']['orientation']}",
            "scale": f"{doc['sheet']['scale'][0]}:{doc['sheet']['scale'][1]}"}
