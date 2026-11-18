"""Deterministic 2D templates (DRW-017) for common flat parts, and the prompt reader that maps a plain request
("draw a gasket Ø150 OD, Ø60 ID, 6 × Ø14 on PCD 120") onto one, so drafting assist works without AI.

Every template returns a document *fragment* (points, entities, dimensions, annotations) in drawing units centred on
the origin. Positions are analytic (e.g. hole i of a gasket sits at PCD/2 · (cos, sin)(start + 360·i/n)) and every
dimension is associative: it references the points / circles it measures, so it is never typed in.
"""

from __future__ import annotations

import math
import re
from typing import Any

from aicad.drawing import DrawingInputError

TEMPLATES: dict[str, dict[str, Any]] = {
    "gasket": {"label": "Flange gasket", "params": {
        "od": ("Outside diameter", 150.0), "id": ("Inside diameter", 60.0), "holes": ("Number of holes", 6),
        "hole_d": ("Hole diameter", 14.0), "pcd": ("Pitch circle diameter", 120.0),
        "start": ("First hole angle (°)", 0.0)}},
    "washer": {"label": "Plain washer", "params": {"od": ("Outside diameter", 30.0), "id": ("Inside diameter", 13.0)}},
    "plate": {"label": "Plate with holes", "params": {
        "length": ("Length", 120.0), "width": ("Width", 80.0), "hole_d": ("Hole diameter", 9.0),
        "nx": ("Holes along the length", 2), "ny": ("Holes along the width", 2), "edge_x": ("Hole centre from end", 15.0),
        "edge_y": ("Hole centre from side", 15.0), "corner_r": ("Corner radius", 0.0)}},
}


class Frag:
    def __init__(self, prefix: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_]{1,12}", prefix):
            raise DrawingInputError("bad id prefix")
        self.prefix = prefix
        self.n = 0
        self.points: list[dict[str, Any]] = []
        self.entities: list[dict[str, Any]] = []
        self.dims: list[dict[str, Any]] = []
        self.annos: list[dict[str, Any]] = []

    def _id(self, kind: str) -> str:
        self.n += 1
        return f"{self.prefix}{kind}{self.n}"

    def pt(self, x: float, y: float) -> str:
        i = self._id("p")
        self.points.append({"id": i, "x": round(x, 9), "y": round(y, 9)})
        return i

    def line(self, a: str, b: str, layer: str = "visible") -> str:
        i = self._id("e")
        self.entities.append({"id": i, "type": "line", "p1": a, "p2": b, "layer": layer})
        return i

    def circle(self, c: str, r: float, layer: str = "visible") -> str:
        i = self._id("e")
        self.entities.append({"id": i, "type": "circle", "c": c, "r": r, "layer": layer})
        return i

    def arc(self, c: str, a: str, b: str, layer: str = "visible") -> str:
        i = self._id("e")
        self.entities.append({"id": i, "type": "arc", "c": c, "p1": a, "p2": b, "layer": layer})
        return i

    def dim(self, **kw: Any) -> str:
        i = self._id("d")
        self.dims.append({"id": i, **kw})
        return i

    def anno(self, **kw: Any) -> str:
        i = self._id("a")
        self.annos.append({"id": i, **kw})
        return i

    def centre_lines(self, c: tuple[float, float], half: float) -> None:
        """Horizontal and vertical centre lines through c, ``half`` long each side."""
        self.line(self.pt(c[0] - half, c[1]), self.pt(c[0] + half, c[1]), "center")
        self.line(self.pt(c[0], c[1] - half), self.pt(c[0], c[1] + half), "center")

    def out(self, **extra: Any) -> dict[str, Any]:
        return {"geom": {"points": self.points, "entities": self.entities}, "dims": self.dims, "annos": self.annos,
                **extra}


def _pos(v: Any, name: str, lo: float = 1e-3, hi: float = 1e5) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise DrawingInputError(f"{name} must be a number") from None
    if not (lo <= f <= hi) or not math.isfinite(f):
        raise DrawingInputError(f"{name} is out of range")
    return f


def _int(v: Any, name: str, lo: int = 0, hi: int = 200) -> int:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise DrawingInputError(f"{name} must be a whole number") from None
    if f != int(f) or not (lo <= f <= hi):
        raise DrawingInputError(f"{name} must be a whole number from {lo} to {hi}")
    return int(f)


def params_of(name: str, given: dict[str, Any] | None) -> dict[str, Any]:
    if name not in TEMPLATES:
        raise DrawingInputError("Unknown template")
    p = {k: v[1] for k, v in TEMPLATES[name]["params"].items()}
    p.update({k: v for k, v in (given or {}).items() if k in p and v is not None})
    return p


def gasket(p: dict[str, Any], k: float = 1.0, prefix: str = "t") -> dict[str, Any]:
    od, idd = _pos(p["od"], "Outside diameter"), _pos(p["id"], "Inside diameter")
    n, hd, pcd = _int(p["holes"], "Number of holes", 0, 72), _pos(p["hole_d"], "Hole diameter"), _pos(p["pcd"], "Pitch circle diameter")
    start = float(p.get("start") or 0.0)
    if idd >= od:
        raise DrawingInputError("The inside diameter must be smaller than the outside diameter")
    if n and not (idd / 2 + hd / 2 < pcd / 2 < od / 2 - hd / 2):
        raise DrawingInputError("The holes must sit between the inside and outside diameters")
    if n > 1 and pcd * math.sin(math.pi / n) <= hd:
        raise DrawingInputError("The holes overlap at that pitch circle diameter")
    f = Frag(prefix)
    c = f.pt(0, 0)
    e_od = f.circle(c, od / 2)
    e_id = f.circle(c, idd / 2)
    f.centre_lines((0.0, 0.0), od / 2 + 3.0 / k)
    off = 10.0 / k  # paper mm -> drawing units
    hole_ids = []
    if n:
        e_pcd = f.circle(c, pcd / 2, "center")
        for i in range(n):
            a = math.radians(start + 360.0 * i / n)
            hc = f.pt(pcd / 2 * math.cos(a), pcd / 2 * math.sin(a))
            h = f.circle(hc, hd / 2)
            hole_ids.append(h)
            f.anno(type="centermark", ent=h)
        f.dim(type="diameter", ent=e_pcd, pos=[pcd / 2 * math.cos(math.radians(150)), pcd / 2 * math.sin(math.radians(150))])
        hx, hy = pcd / 2 * math.cos(math.radians(start)), pcd / 2 * math.sin(math.radians(start))
        f.dim(type="diameter", ent=hole_ids[0], pos=[hx + hd / 2 + off * 1.6, hy + hd / 2 + off * 1.6],
              **({"prefix": f"{n}X"} if n > 1 else {}))
    f.dim(type="diameter", ent=e_od, pos=[(od / 2 + off * 2) * math.cos(math.radians(45)), (od / 2 + off * 2) * math.sin(math.radians(45))])
    f.dim(type="diameter", ent=e_id, pos=[-idd / 2 * 0.35, -idd / 2 * 0.35])
    return f.out(extent=[od, od])


def washer(p: dict[str, Any], k: float = 1.0, prefix: str = "t") -> dict[str, Any]:
    od, idd = _pos(p["od"], "Outside diameter"), _pos(p["id"], "Inside diameter")
    if idd >= od:
        raise DrawingInputError("The inside diameter must be smaller than the outside diameter")
    f = Frag(prefix)
    c = f.pt(0, 0)
    e_od = f.circle(c, od / 2)
    e_id = f.circle(c, idd / 2)
    f.centre_lines((0.0, 0.0), od / 2 + 3.0 / k)
    off = 10.0 / k
    f.dim(type="diameter", ent=e_od, pos=[(od / 2 + off * 1.5) * math.cos(math.radians(45)), (od / 2 + off * 1.5) * math.sin(math.radians(45))])
    f.dim(type="diameter", ent=e_id, pos=[(od / 2 + off * 1.5) * math.cos(math.radians(225)), (od / 2 + off * 1.5) * math.sin(math.radians(225))])
    return f.out(extent=[od, od])


def plate(p: dict[str, Any], k: float = 1.0, prefix: str = "t") -> dict[str, Any]:
    L, W = _pos(p["length"], "Length"), _pos(p["width"], "Width")
    hd = _pos(p["hole_d"], "Hole diameter")
    nx, ny = _int(p["nx"], "Holes along the length", 0, 50), _int(p["ny"], "Holes along the width", 0, 50)
    ex, ey = _pos(p["edge_x"], "Hole centre from end", 0), _pos(p["edge_y"], "Hole centre from side", 0)
    r = _pos(p.get("corner_r") or 0.0, "Corner radius", 0)
    if r * 2 >= min(L, W):
        raise DrawingInputError("The corner radius is too large for the plate")
    if (nx and ny) and (ex < hd / 2 or ey < hd / 2 or ex > L / 2 or ey > W / 2):
        raise DrawingInputError("The holes must sit inside the plate")
    px = (L - 2 * ex) / (nx - 1) if nx > 1 else 0.0
    py = (W - 2 * ey) / (ny - 1) if ny > 1 else 0.0
    if (nx > 1 and px <= hd) or (ny > 1 and py <= hd):
        raise DrawingInputError("The holes overlap at that spacing")
    f = Frag(prefix)
    x0, y0, x1, y1 = -L / 2, -W / 2, L / 2, W / 2
    if r > 0:
        a1, a2 = f.pt(x0 + r, y0), f.pt(x1 - r, y0)
        b1, b2 = f.pt(x1, y0 + r), f.pt(x1, y1 - r)
        c1, c2 = f.pt(x1 - r, y1), f.pt(x0 + r, y1)
        d1, d2 = f.pt(x0, y1 - r), f.pt(x0, y0 + r)
        for a, b in ((a1, a2), (b1, b2), (c1, c2), (d1, d2)):
            f.line(a, b)
        corners = [f.arc(f.pt(x1 - r, y0 + r), a2, b1), f.arc(f.pt(x1 - r, y1 - r), b2, c1),
                   f.arc(f.pt(x0 + r, y1 - r), c2, d1), f.arc(f.pt(x0 + r, y0 + r), d2, a1)]
        left_pts = (d2, b1)  # on the left and right edges (overall length)
        side_pts = (a1, c2)  # on the bottom and top edges (overall width)
        ref_x, ref_y = d1, c2  # a point on the left edge, a point on the top edge
    else:
        A, B, C, D = f.pt(x0, y0), f.pt(x1, y0), f.pt(x1, y1), f.pt(x0, y1)
        for a, b in ((A, B), (B, C), (C, D), (D, A)):
            f.line(a, b)
        corners = []
        left_pts, side_pts, ref_x, ref_y = (A, B), (A, D), D, D
    off = 10.0 / k  # paper mm -> drawing units
    holes: list[list[float]] = []
    hole_pts: dict[tuple[int, int], str] = {}
    first_hole = None
    for i in range(nx):
        for j in range(ny):
            hx, hy = x0 + ex + px * i, y0 + ey + py * j
            hp = f.pt(hx, hy)
            hole_pts[(i, j)] = hp
            h = f.circle(hp, hd / 2)
            first_hole = first_hole or h
            f.anno(type="centermark", ent=h)
            holes.append([hx, hy])
    # overall size: length below, width on the left
    f.dim(type="linear", orient="h", a=left_pts[0], b=left_pts[1], pos=[0.0, y0 - off * 2])
    f.dim(type="linear", orient="v", a=side_pts[0], b=side_pts[1], pos=[x0 - off * 2, 0.0])
    if holes:
        # hole positions: from the left end along the top row, from the top side down the right column (chains)
        prev = ref_x
        for i in range(nx):
            hp = hole_pts[(i, ny - 1)]
            f.dim(type="linear", orient="h", a=prev, b=hp, pos=[x0 + ex + px * (i - 0.5) if i else x0 + ex / 2, y1 + off * 1.5])
            prev = hp
        prev = ref_y
        for j in range(ny - 1, -1, -1):
            hp = hole_pts[(nx - 1, j)]
            ypos = y1 - ey / 2 if j == ny - 1 else y0 + ey + py * (j + 0.5)
            f.dim(type="linear", orient="v", a=prev, b=hp, pos=[x1 + off * 1.5, ypos])
            prev = hp
        n_h = nx * ny
        hx0, hy0 = holes[0]
        f.dim(type="diameter", ent=first_hole, pos=[hx0 + hd / 2 + off * 1.2, hy0 - hd / 2 - off * 1.2],
              **({"prefix": f"{n_h}X"} if n_h > 1 else {}))
    if corners:
        f.dim(type="radius", ent=corners[0], pos=[x1 + off, y0 - off])
    return f.out(extent=[L, W], holes=holes)


GENERATORS = {"gasket": gasket, "washer": washer, "plate": plate}


def generate(name: str, given: dict[str, Any] | None, k: float = 1.0, prefix: str = "t") -> dict[str, Any]:
    p = params_of(name, given)
    out = GENERATORS[name](p, k, prefix)
    out["template"] = name
    out["params"] = p
    return out


# ----------------------------------------------------------------------------- prompt reader (no AI)
_NUM = r"(\d+(?:\.\d+)?)"
_DIA = r"(?:Ø|ø|⌀|dia\.?|diameter|d)?\s*"


def _find(pat: str, s: str) -> float | None:
    m = re.search(pat, s, re.IGNORECASE)
    return float(m.group(1)) if m else None


_OD = r"(?:od|o\.d\.|outer diameter|outside diameter|outer|outside)"
_ID = r"(?:id|i\.d\.|inner diameter|inside diameter|inner|inside|bore)"


def _labelled(s: str, label: str) -> float | None:
    """The number written next to a label: "Ø150 OD" (value first) or "OD 150" / "OD of Ø150" (label first). The
    style is the request's: label-first when a diameter label comes before the first number."""
    first_num = re.search(r"\d", s)
    first_lab = re.search(r"\b(?:" + _OD + "|" + _ID + r")\b", s, re.IGNORECASE)
    label_first = bool(first_lab and first_num and first_lab.start() < first_num.start())
    after = _find(r"\b" + label + r"\b\s*(?:of\s*|=\s*|:\s*)?" + _DIA + _NUM, s)
    before = _find(_DIA + _NUM + r"\s*(?:mm)?\s*" + label + r"\b", s)
    return (after if after is not None else before) if label_first else (before if before is not None else after)


def read_prompt(text: str) -> dict[str, Any] | None:
    """Map a plain drafting request onto a template and parameters, or None when it isn't one we know."""
    s = " ".join(str(text or "").split())[:400]
    low = s.lower()
    holes = re.search(r"(\d+)\s*(?:x|×|\*|off)\s*" + _DIA + _NUM, s, re.IGNORECASE)
    if "gasket" in low or "flange" in low:
        od, idd = _labelled(s, _OD), _labelled(s, _ID)
        pcd = _find(r"(?:pcd|p\.c\.d\.|bcd|pitch circle(?: diameter)?|bolt circle)\s*(?:of\s*)?" + _DIA + _NUM, s)
        if od is None or idd is None:
            return None
        p: dict[str, Any] = {"od": od, "id": idd, "holes": 0, "hole_d": 14.0, "pcd": (od + idd) / 2}
        if holes:
            p["holes"], p["hole_d"] = int(holes.group(1)), float(holes.group(2))
            p["pcd"] = pcd if pcd is not None else (od + idd) / 2
        return {"template": "gasket", "params": p}
    if "washer" in low:
        od, idd = _labelled(s, _OD), _labelled(s, _ID)
        if od is None or idd is None:
            return None
        return {"template": "washer", "params": {"od": od, "id": idd}}
    if "plate" in low:
        m = re.search(_NUM + r"\s*(?:mm)?\s*(?:x|×|by)\s*" + _NUM, s, re.IGNORECASE)
        if not m:
            return None
        L, W = float(m.group(1)), float(m.group(2))
        L, W = max(L, W), min(L, W)
        p = {"length": L, "width": W, "nx": 0, "ny": 0, "hole_d": 9.0, "edge_x": 15.0, "edge_y": 15.0, "corner_r": 0.0}
        rest = s[m.end():]
        hm = re.search(r"(\d+)\s*(?:x|×|\*)?\s*(?:holes?)?\s*(?:of\s*)?" + r"(?:Ø|ø|⌀|dia\.?\s*)" + _NUM, rest, re.IGNORECASE) \
            or re.search(r"(\d+)\s*holes?\s*(?:of\s*)?" + _DIA + _NUM, rest, re.IGNORECASE)
        if hm:
            n, p["hole_d"] = int(hm.group(1)), float(hm.group(2))
            p["nx"], p["ny"] = {1: (1, 1), 2: (2, 1), 3: (3, 1), 4: (2, 2), 6: (3, 2), 8: (4, 2), 9: (3, 3)}.get(n, (n, 1))
        e = _find(_NUM + r"\s*(?:mm)?\s*from\s*(?:the\s*)?(?:edges?|sides?|ends?)", rest)
        if e is not None:
            p["edge_x"] = p["edge_y"] = e
        cr = _find(r"(?:corner radius|corners?\s*r|r)\s*" + _NUM + r"\s*(?:mm)?\s*corners?", rest) or _find(r"corner radius\s*(?:of\s*)?" + _NUM, rest)
        if cr is not None:
            p["corner_r"] = cr
        return {"template": "plate", "params": p}
    return None


def fit_scale(extent: list[float], sheet_w: float, sheet_h: float, k_unit: float = 1.0) -> list[int]:
    """Largest ISO 5455 scale at which a part of this extent (drawing units) fits the free sheet area with room for
    dimensions (about 45 mm each side, title block kept clear)."""
    from aicad.drawing.draft import SCALES

    free_w, free_h = sheet_w - 30 - 90, sheet_h - 20 - 95
    for n, d in SCALES:
        k = k_unit * n / d
        if extent[0] * k <= free_w and extent[1] * k <= free_h:
            return [n, d]
    return [1, 1000]
