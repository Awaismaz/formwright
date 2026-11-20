"""Sheet layout: frame, scale, view placement, dimensions, callouts, title block, legend and revision table.

Pure Python (no CAD kernel). Paper coordinates are millimetres with the origin at the top-left corner and y down.
Every primitive is a plain dict so the SVG, PDF and DXF renderers draw exactly the same sheet:

  {"t": "line", "l": layer, "p": [x1, y1, x2, y2]}
  {"t": "poly", "l": layer, "p": [[x, y], ...], "closed": bool}
  {"t": "circle", "l": layer, "p": [cx, cy, r]}
  {"t": "arc", "l": layer, "p": [cx, cy, r, a0, a1]}      degrees, counter-clockwise as seen on paper
  {"t": "fill", "l": layer, "p": [[x, y], ...]}            filled polygon (arrowheads)
  {"t": "text", "l": layer, "x", "y" (baseline), "s" (cap size), "txt", "anchor", "rot" (0 or 90),
   "font" ("regular" | "bold" | "italic"), "tag", "param", "kind", "box" [x0, y0, x1, y1],
   "dl" (dimension texts only): {"o": "h" | "v", "line": [a, b] between the extension lines, "at": dimension-line
   coordinate, "drawn": [a, b] extent of the drawn dimension line (a leader under an outside text)}}

Dimension text placement (MAKE-01, ISO 129-1): a value sits inside its own span when it fits. Otherwise it sits
outside, on the dimension line extended under it as a leader, and never over the span of another dimension on the
same dimension line (a chain): the first and last members of a chain go beyond the chain's ends, inner members move
to a row of their own. CHK-12 checks exactly this rule on the finished sheet.
"""

from __future__ import annotations

import math
from typing import Any

SHEETS = {"A4": (297.0, 210.0), "A3": (420.0, 297.0)}
SCALES = [(10, 1), (5, 1), (2, 1), (1, 1), (1, 2), (1, 5), (1, 10), (1, 20), (1, 50), (1, 100)]
FRAME = {"left": 20.0, "top": 10.0, "right": 10.0, "bottom": 10.0}  # ISO 5457 margins (filing edge left)
TB_W = 180.0  # ISO 7200 title block width
ARROW, ARROW_W = 2.6, 0.42
GAP, OVERSHOOT = 1.0, 2.0  # extension line: gap from the feature, overshoot past the dimension line
FIRST_ROW, ROW = 9.0, 7.0  # first dimension line from the view, spacing between rows
VIEW_GAP = 6.0
FONTS = {"regular": "Helvetica", "bold": "Helvetica-Bold", "italic": "Helvetica-Oblique"}
#: line layers: (stroke width mm, dash pattern mm or None, colour)
LAYERS: dict[str, tuple[float, list[float] | None, str]] = {
    "visible": (0.5, None, "#111111"),
    "hidden": (0.25, [3.0, 1.2], "#111111"),
    "center": (0.18, [8.0, 1.5, 1.0, 1.5], "#333333"),
    "hatch": (0.18, None, "#333333"),
    "dim": (0.18, None, "#222222"),
    "cut": (0.25, [8.0, 1.5, 1.0, 1.5], "#111111"),
    "cutthick": (0.7, None, "#111111"),
    "frame": (0.7, None, "#111111"),
    "tb": (0.35, None, "#111111"),
    "tbthin": (0.18, None, "#444444"),
    "banner": (0.6, None, "#b91c1c"),
    # 2D drafting (DRW-017): ISO 128-2 narrow lines at 0.25 with the 0.5 wide line, construction never printed
    "center_n": (0.25, [8.0, 1.5, 1.0, 1.5], "#333333"),
    "dim_n": (0.25, None, "#222222"),
    "hatch_n": (0.25, None, "#333333"),
    "construction": (0.13, [1.0, 1.0], "#5b7db1"),
    # ISO 6410-1 cosmetic thread (thin continuous), detail-view boundary circles and GD&T frames / datum symbols
    "thread": (0.25, None, "#111111"),
    "detail": (0.25, None, "#111111"),
    "gdt": (0.25, None, "#111111"),
}
LEGEND = [("120", "regular", "spec", "SPEC: equals a declared model parameter"),
          ("120", "italic", "inferred", "INFERRED: measured from the model geometry"),
          ("(40)", "italic", "aux", "REFERENCE dimension")]
TEXT_COLORS = {"spec": "#0b3d91", "inferred": "#9a3412", "normal": "#111111", "label": "#555555",
               "banner": "#b91c1c", "aux": "#9a3412"}


# ----------------------------------------------------------------------------- text metrics
def text_width(txt: str, size: float, font: str = "regular") -> float:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    return stringWidth(txt, FONTS[font], 1.0) * size


def text_box(x: float, y: float, size: float, txt: str, anchor: str = "start", rot: int = 0,
             font: str = "regular") -> list[float]:
    """Paper bbox of a text: Helvetica metrics (descender 0.21, cap/ascender 0.73 of the size)."""
    w = text_width(txt, size, font)
    off = {"start": 0.0, "middle": -w / 2, "end": -w}[anchor]
    if rot == 0:
        return [x + off, y - 0.73 * size, x + off + w, y + 0.21 * size]
    return [x - 0.73 * size, y - off - w, x + 0.21 * size, y - off]  # reads bottom-to-top


def boxes_overlap(a: list[float], b: list[float], pad: float = 0.0) -> bool:
    return a[0] < b[2] + pad and b[0] < a[2] + pad and a[1] < b[3] + pad and b[1] < a[3] + pad


def _seg_hits_box(p: tuple[float, float], q: tuple[float, float], b: list[float], pad: float = 0.0) -> bool:
    """Does the segment p-q pass through the (padded) box? Liang-Barsky clipping."""
    x0, y0, x1, y1 = b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
        if abs(pp) < 1e-12:
            if qq < 0:
                return False
            continue
        r = qq / pp
        if pp < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return False
    return True


def _segs_cross(p1: tuple[float, float], p2: tuple[float, float], q1: tuple[float, float],
                q2: tuple[float, float]) -> bool:
    """Proper crossing of two segments (touching end points do not count)."""
    def orient(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return d1 * d2 < -1e-9 and d3 * d4 < -1e-9


class Group:
    """Primitives in a local frame; ``place`` translates them onto the sheet."""

    def __init__(self) -> None:
        self.prims: list[dict[str, Any]] = []

    def line(self, layer: str, x1: float, y1: float, x2: float, y2: float) -> None:
        self.prims.append({"t": "line", "l": layer, "p": [x1, y1, x2, y2]})

    def poly(self, layer: str, pts: list[list[float]], closed: bool = False) -> None:
        self.prims.append({"t": "poly", "l": layer, "p": [list(p) for p in pts], "closed": closed})

    def rect(self, layer: str, x: float, y: float, w: float, h: float) -> None:
        self.poly(layer, [[x, y], [x + w, y], [x + w, y + h], [x, y + h]], closed=True)

    def circle(self, layer: str, cx: float, cy: float, r: float) -> None:
        self.prims.append({"t": "circle", "l": layer, "p": [cx, cy, r]})

    def arc(self, layer: str, cx: float, cy: float, r: float, a0: float, a1: float) -> None:
        self.prims.append({"t": "arc", "l": layer, "p": [cx, cy, r, a0, a1]})

    def fill(self, layer: str, pts: list[list[float]]) -> None:
        self.prims.append({"t": "fill", "l": layer, "p": [list(p) for p in pts]})

    def text(self, x: float, y: float, size: float, txt: str, *, anchor: str = "start", rot: int = 0,
             font: str = "regular", color: str = "normal", kind: str = "label", tag: str | None = None,
             param: str | None = None, ref: str | None = None, dl: dict[str, Any] | None = None,
             params: list[str] | None = None) -> dict[str, Any]:
        t = {"t": "text", "l": "text", "x": x, "y": y, "s": size, "txt": txt, "anchor": anchor, "rot": rot,
             "font": font, "color": color, "kind": kind, "tag": tag, "param": param, "ref": ref,
             "box": text_box(x, y, size, txt, anchor, rot, font)}
        if dl is not None:
            t["dl"] = dl
        if params:
            t["params"] = params
        self.prims.append(t)
        return t

    def arrow(self, tip: tuple[float, float], frm: tuple[float, float], layer: str = "dim") -> None:
        dx, dy = tip[0] - frm[0], tip[1] - frm[1]
        n = math.hypot(dx, dy) or 1.0
        ux, uy = dx / n, dy / n
        bx, by = tip[0] - ux * ARROW, tip[1] - uy * ARROW
        self.fill(layer, [[tip[0], tip[1]], [bx - uy * ARROW_W, by + ux * ARROW_W], [bx + uy * ARROW_W, by - ux * ARROW_W]])

    def texts(self) -> list[dict[str, Any]]:
        return [p for p in self.prims if p["t"] == "text"]

    def bounds(self) -> list[float] | None:
        xs: list[float] = []
        ys: list[float] = []
        for p in self.prims:
            if p["t"] == "text":
                b = p["box"]
                xs += [b[0], b[2]]
                ys += [b[1], b[3]]
            elif p["t"] == "line":
                xs += [p["p"][0], p["p"][2]]
                ys += [p["p"][1], p["p"][3]]
            elif p["t"] in ("poly", "fill"):
                xs += [q[0] for q in p["p"]]
                ys += [q[1] for q in p["p"]]
            elif p["t"] in ("circle", "arc"):
                cx, cy, r = p["p"][:3]
                xs += [cx - r, cx + r]
                ys += [cy - r, cy + r]
        return [min(xs), min(ys), max(xs), max(ys)] if xs else None

    def placed(self, dx: float, dy: float) -> list[dict[str, Any]]:
        out = []
        for p in self.prims:
            q = dict(p)
            if p["t"] == "line":
                a = p["p"]
                q["p"] = [a[0] + dx, a[1] + dy, a[2] + dx, a[3] + dy]
            elif p["t"] in ("poly", "fill"):
                q["p"] = [[x + dx, y + dy] for x, y in p["p"]]
            elif p["t"] in ("circle", "arc"):
                q["p"] = [p["p"][0] + dx, p["p"][1] + dy, *p["p"][2:]]
            elif p["t"] == "text":
                q["x"], q["y"] = p["x"] + dx, p["y"] + dy
                b = p["box"]
                q["box"] = [b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy]
                if "dl" in p:
                    d = p["dl"]
                    along, across = (dx, dy) if d["o"] == "h" else (dy, dx)
                    q["dl"] = {**d, "line": [d["line"][0] + along, d["line"][1] + along], "at": d["at"] + across,
                               "drawn": [d["drawn"][0] + along, d["drawn"][1] + along]}
            out.append(q)
        return out


# ----------------------------------------------------------------------------- view geometry helpers
def _extreme(prims: list[list[Any]], coord: str, value: float, want_max: bool) -> float | None:
    """Extreme of the other coordinate over geometry points lying at U (coord 'u') or V (coord 'v') = value."""
    i = 0 if coord == "u" else 1
    found: list[float] = []
    eps = 1e-6

    def seg(p: tuple[float, float], q: tuple[float, float]) -> None:
        a, b = p[i], q[i]
        if abs(a - value) < eps:
            found.append(p[1 - i])
        if abs(b - value) < eps:
            found.append(q[1 - i])
        if (a - value) * (b - value) < 0:
            t = (value - a) / (b - a)
            found.append(p[1 - i] + t * (q[1 - i] - p[1 - i]))

    for pr in prims:
        k = pr[0]
        if k == "line":
            seg((pr[1], pr[2]), (pr[3], pr[4]))
        elif k == "poly":
            for a, b in zip(pr[1], pr[1][1:]):
                seg((a[0], a[1]), (b[0], b[1]))
        elif k in ("circle", "arc"):
            cx, cy, r = pr[1], pr[2], pr[3]
            c = (cx, cy)
            d = (value - c[i]) / r if r > 0 else 2.0
            if abs(d) > 1 + 1e-9:
                continue
            d = max(-1.0, min(1.0, d))
            base = math.degrees(math.acos(d)) if i == 0 else math.degrees(math.asin(d))
            angs = [base, -base] if i == 0 else [base, 180.0 - base]
            for a in angs:
                if k == "arc":
                    a0, a1 = pr[4], pr[5]
                    if not ((a - a0) % 360.0 <= (a1 - a0) + 1e-6):
                        continue
                pt = (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
                found.append(pt[1 - i])
    if not found:
        return None
    return max(found) if want_max else min(found)


def _hatch(loops: list[list[list[float]]], spacing: float) -> list[list[float]]:
    """45° hatch lines clipped to the even-odd region of the loops (paper coordinates)."""
    c, s = math.cos(math.radians(-45)), math.sin(math.radians(-45))

    def rot(p: list[float], sgn: float = 1.0) -> tuple[float, float]:
        return (p[0] * c - sgn * p[1] * s, sgn * p[0] * s + p[1] * c)

    rloops = [[rot(p) for p in lp] for lp in loops]
    ys = [p[1] for lp in rloops for p in lp]
    if not ys:
        return []
    out = []
    y = math.floor(min(ys) / spacing) * spacing + spacing / 2
    while y < max(ys):
        xs = []
        for lp in rloops:
            for a, b in zip(lp, lp[1:] + lp[:1]):
                if (a[1] - y) * (b[1] - y) < 0:
                    xs.append(a[0] + (y - a[1]) / (b[1] - a[1]) * (b[0] - a[0]))
        xs.sort()
        for x0, x1 in zip(xs[::2], xs[1::2]):
            p0, p1 = rot([x0, y], -1.0), rot([x1, y], -1.0)
            out.append([p0[0], p0[1], p1[0], p1[1]])
        y += spacing
    return out


# ----------------------------------------------------------------------------- one view, local frame
class ViewLayout:
    """A view drawn in its local frame: the geometry rectangle is (0, 0)-(w, h); annotations sit around it."""

    def __init__(self, name: str, geom: dict[str, Any], scale: float, *, hidden: bool = True,
                 label: str | None = None) -> None:
        self.name = name
        self.geom = geom
        self.s = scale
        ext = geom["extents"]
        self.umin, self.umax, self.vmin, self.vmax = ext
        self.w = (self.umax - self.umin) * scale
        self.h = (self.vmax - self.vmin) * scale
        self.g = Group()
        self.reserved: list[list[float]] = []  # local boxes (cutting-plane letters ...) dims must avoid
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self.label = label
        self._draw_geometry(hidden)

    def xy(self, u: float, v: float) -> tuple[float, float]:
        return ((u - self.umin) * self.s, (self.vmax - v) * self.s)

    def _draw_prim(self, layer: str, p: list[Any]) -> None:
        if p[0] == "line":
            a, b = self.xy(p[1], p[2]), self.xy(p[3], p[4])
            self.g.line(layer, a[0], a[1], b[0], b[1])
        elif p[0] == "circle":
            c = self.xy(p[1], p[2])
            self.g.circle(layer, c[0], c[1], p[3] * self.s)
        elif p[0] == "arc":
            c = self.xy(p[1], p[2])
            self.g.arc(layer, c[0], c[1], p[3] * self.s, p[4], p[5])
        elif p[0] == "poly":
            self.g.poly(layer, [list(self.xy(q[0], q[1])) for q in p[1]])

    def _draw_geometry(self, hidden: bool) -> None:
        if hidden:
            for p in self.geom.get("hidden", []):
                self._draw_prim("hidden", p)
        for p in self.geom.get("visible", []):
            self._draw_prim("visible", p)

    def hatch(self, loops: list[list[list[float]]], spacing: float) -> None:
        paper = [[list(self.xy(q[0], q[1])) for q in lp] for lp in loops]
        for ln in _hatch(paper, spacing):
            self.g.line("hatch", *ln)

    def centre_lines(self, callouts: list[dict[str, Any]], axes: list[tuple[str, float, float, float]]) -> None:
        """Centre marks on holes seen end-on, PCD circles, and axis lines for cylinders seen side-on.

        ``axes``: (orientation 'h' | 'v', coordinate across, from, to) in view coordinates."""
        for c in callouts:
            for u, v, r in c["holes"]:
                x, y = self.xy(u, v)
                rp = r * self.s
                e = rp + 2.0 if rp > 1.0 else 1.5
                self.g.line("center", x - e, y, x + e, y)
                self.g.line("center", x, y - e, x, y + e)
            if c.get("pcd"):
                cu, cv, rr = c["pcd"]
                x, y = self.xy(cu, cv)
                self.g.circle("center", x, y, rr * self.s)
        for orient, across, a, b in axes:
            if orient == "h":  # axis along U at V = across
                p, q = self.xy(a, across), self.xy(b, across)
                self.g.line("center", p[0] - 2.5, p[1], q[0] + 2.5, q[1])
            else:
                p, q = self.xy(across, a), self.xy(across, b)
                self.g.line("center", p[0], p[1] + 2.5, q[0], q[1] - 2.5)

    # -------------------------------------------------------------- dimensions
    def _origin(self, d: dict[str, Any], end: str, side_sign: int) -> float:
        """Coordinate (V for horizontal dims, U for vertical) where the extension line starts."""
        ext = d["ext_a" if end == "a" else "ext_b"]
        if ext is not None:
            return ext[1] if side_sign > 0 else ext[0]
        coord = "u" if d["orient"] == "h" else "v"
        val = d[end]
        prims = self.geom.get("visible", [])
        e = _extreme(prims, coord, val, side_sign > 0)
        if e is None:
            e = _extreme(self.geom.get("hidden", []), coord, val, side_sign > 0)
        if e is None:
            lo, hi = (self.vmin, self.vmax) if d["orient"] == "h" else (self.umin, self.umax)
            e = hi if side_sign > 0 else lo
        return e

    def place_dims(self, dims: list[dict[str, Any]], sides: dict[str, str], size: float) -> None:
        by_side: dict[str, list[dict[str, Any]]] = {}
        for d in dims:
            by_side.setdefault(sides[d["orient"]], []).append(d)
        for side, ds in sorted(by_side.items()):
            ds.sort(key=lambda d: (d["order"], round(d["b"] - d["a"], 6), d["a"], d["id"]))
            hull: dict[str, tuple[float, float]] = {}
            for d in ds:
                lo_, hi_ = hull.get(d["family"], (d["a"], d["b"]))
                hull[d["family"]] = (min(lo_, d["a"]), max(hi_, d["b"]))
            rows: list[list[dict[str, Any]]] = []
            fam_row: dict[str, int] = {}
            for d in ds:
                placed = False
                start = fam_row.get(d["family"], 0)
                # an empty row must still keep clear of texts already placed on other sides (``reserved``), e.g. an
                # outside value at the end of a vertical chain landing on a horizontal row below the view
                for strict in (True, False):
                    for r in range(start, len(rows) + (6 if strict else 1)):
                        for c in self._dim_geometry(d, side, r, size, hull[d["family"]]):
                            ok = self._fits(c, rows[r]) if r < len(rows) else (
                                not strict or not any(boxes_overlap(c["tbox"], q, 0.5) for q in self.reserved))
                            if ok:
                                while len(rows) <= r:
                                    rows.append([])
                                rows[r].append(c)
                                fam_row.setdefault(d["family"], r)
                                placed = True
                                break
                        if placed:
                            break
                    if placed:
                        break
            self.rows[side] = [c for row in rows for c in row]
            self.reserved += [c["tbox"] for row in rows for c in row]  # later sides avoid these texts
            for row in rows:
                for c in row:
                    self._emit(c)

    @staticmethod
    def _proj(c: dict[str, Any]) -> tuple[float, float]:
        """The text's extent along the dimension's measuring direction (paper)."""
        b = c["tbox"]
        return (b[0], b[2]) if c["orient"] == "h" else (b[1], b[3])

    def _fits(self, c: dict[str, Any], row: list[dict[str, Any]]) -> bool:
        def over(p: tuple[float, float] | list[float], q: tuple[float, float] | list[float]) -> bool:
            return p[0] < q[1] - 0.05 and q[0] + 0.05 < p[1]

        for o in row:
            if boxes_overlap(c["tbox"], o["tbox"], 0.8):
                return False
            if c["family"] != o["family"] and over(c["span"], o["span"]):
                return False
            # one dimension line: an outside value must never sit over a neighbour's span (MAKE-01)
            if c["outside"] and over(self._proj(c), o["line"]):
                return False
            if o["outside"] and over(self._proj(o), c["line"]):
                return False
            if over(c["drawn"], self._proj(o)) or over(o["drawn"], self._proj(c)):
                return False
        return not any(boxes_overlap(c["tbox"], r, 0.5) for r in self.reserved)

    def _dim_geometry(self, d: dict[str, Any], side: str, row: int, size: float,
                      hull: tuple[float, float]) -> list[dict[str, Any]]:
        """Candidate drawings of one dimension in a row: the value inside its span when it fits, else outside
        (beyond the chain's end first) on a leader."""
        sign = {"top": 1, "right": 1, "bottom": -1, "left": -1}[side]
        off = FIRST_ROW + ROW * row
        txt = d["text"]
        font = "italic" if d["tag"] == "inferred" else "regular"
        tw = text_width(txt, size, font)
        at_lo, at_hi = abs(d["a"] - hull[0]) < 1e-6, abs(d["b"] - hull[1]) < 1e-6
        out = []
        if d["orient"] == "h":
            xa, xb = self.xy(d["a"], 0)[0], self.xy(d["b"], 0)[0]
            yd = -off if sign > 0 else self.h + off
            fits = xb - xa >= tw + 2 * ARROW + 1.5
            places = ["in"] if fits else (["left", "right"] if at_lo and not at_hi else ["right", "left"])
            for pl in places:
                if pl == "in":
                    tx, anchor = (xa + xb) / 2, "middle"
                elif pl == "right":
                    tx, anchor = xb + ARROW + 1.2, "start"
                else:
                    tx, anchor = xa - ARROW - 1.2, "end"
                ty = yd - 1.0
                tb = text_box(tx, ty, size, txt, anchor, 0, font)
                if pl == "in":
                    drawn = [xa, xb]
                else:
                    drawn = [min(xa - ARROW - 2.5, tb[0] - 0.3), max(xb + ARROW + 2.5, tb[2] + 0.3)]
                out.append({**d, "side": side, "sign": sign, "row": row, "yd": yd, "xa": xa, "xb": xb,
                            "tx": tx, "ty": ty, "anchor": anchor, "font": font, "size": size, "tbox": tb,
                            "span": [min(drawn[0], tb[0]), max(drawn[1], tb[2])], "inside": pl == "in",
                            "outside": pl != "in", "line": [xa, xb], "drawn": drawn, "family": d["family"]})
        else:
            ya, yb = self.xy(0, d["a"])[1], self.xy(0, d["b"])[1]  # ya > yb on paper (V up)
            xd = self.w + off if sign > 0 else -off
            fits = ya - yb >= tw + 2 * ARROW + 1.5
            places = ["in"] if fits else (["down", "up"] if at_lo and not at_hi else ["up", "down"])
            for pl in places:
                if pl == "in":
                    ty, anchor = (ya + yb) / 2, "middle"
                elif pl == "up":
                    ty, anchor = yb - ARROW - 1.2, "start"
                else:
                    ty, anchor = ya + ARROW + 1.2, "end"
                tx = xd - 1.0
                tb = text_box(tx, ty, size, txt, anchor, 90, font)
                if pl == "in":
                    drawn = [yb, ya]
                else:
                    drawn = [min(yb - ARROW - 2.5, tb[1] - 0.3), max(ya + ARROW + 2.5, tb[3] + 0.3)]
                out.append({**d, "side": side, "sign": sign, "row": row, "xd": xd, "ya": ya, "yb": yb,
                            "tx": tx, "ty": ty, "anchor": anchor, "font": font, "size": size, "tbox": tb,
                            "span": [min(drawn[0], tb[1]), max(drawn[1], tb[3])], "inside": pl == "in",
                            "outside": pl != "in", "line": [yb, ya], "drawn": drawn, "family": d["family"]})
        return out

    def _emit(self, c: dict[str, Any]) -> None:
        g = self.g
        color = "aux" if c.get("aux") else c["tag"]
        dl = {"o": c["orient"], "line": list(c["line"]), "drawn": list(c["drawn"]),
              "at": c["yd"] if c["orient"] == "h" else c["xd"]}
        if c["orient"] == "h":
            yd = c["yd"]
            for end, x in (("a", c["xa"]), ("b", c["xb"])):
                v0 = self._origin(c, end, c["sign"])
                y0 = (self.vmax - v0) * self.s
                if c["sign"] > 0:
                    g.line("dim", x, y0 - GAP, x, yd - OVERSHOOT)
                else:
                    g.line("dim", x, y0 + GAP, x, yd + OVERSHOOT)
            xa, xb = c["xa"], c["xb"]
            g.line("dim", c["drawn"][0], yd, c["drawn"][1], yd)
            if c["inside"]:
                g.arrow((xa, yd), (xb, yd))
                g.arrow((xb, yd), (xa, yd))
            else:
                g.arrow((xa, yd), (xa - 5, yd))
                g.arrow((xb, yd), (xb + 5, yd))
            g.text(c["tx"], c["ty"], c["size"], c["text"], anchor=c["anchor"], font=c["font"], color=color,
                   kind="dim", tag=c["tag"], param=c["param"], ref=c["id"], dl=dl)
        else:
            xd = c["xd"]
            for end, y in (("a", c["ya"]), ("b", c["yb"])):
                u0 = self._origin(c, end, c["sign"])
                x0 = (u0 - self.umin) * self.s
                if c["sign"] > 0:
                    g.line("dim", x0 + GAP, y, xd + OVERSHOOT, y)
                else:
                    g.line("dim", x0 - GAP, y, xd - OVERSHOOT, y)
            ya, yb = c["ya"], c["yb"]
            g.line("dim", xd, c["drawn"][0], xd, c["drawn"][1])
            if c["inside"]:
                g.arrow((xd, ya), (xd, yb))
                g.arrow((xd, yb), (xd, ya))
            else:
                g.arrow((xd, ya), (xd, ya + 5))
                g.arrow((xd, yb), (xd, yb - 5))
            g.text(c["tx"], c["ty"], c["size"], c["text"], anchor=c["anchor"], rot=90, font=c["font"],
                   color=color, kind="dim", tag=c["tag"], param=c["param"], ref=c["id"], dl=dl)

    def side_extent(self, side: str) -> float:
        """How far (mm) the dimension rows on a side reach beyond the geometry."""
        rows = self.rows.get(side, [])
        return 0.0 if not rows else FIRST_ROW + ROW * max(c["row"] for c in rows) + 4.5

    def place_callouts(self, callouts: list[dict[str, Any]], side: str, size: float) -> None:
        """Leader + text for each hole group or radius/chamfer, beyond the dimension rows above or below the view.

        ``side`` is the default; a callout whose feature sits in the far half of the view goes to the other side, so
        its leader stays short instead of running diagonally across the view."""
        placed: list[list[float]] = [c["tbox"] for sd in ("top", "bottom") for c in self.rows.get(sd, [])] + list(self.reserved)
        leaders: list[tuple[tuple[float, float], tuple[float, float]]] = []

        def feature_y(c: dict[str, Any]) -> float:
            pts = c.get("tips") or ([c["tip"]] if c.get("tip") is not None else [(h[0], h[1]) for h in c.get("holes") or []])
            ys = [self.xy(u, v)[1] for u, v in pts]
            return sum(ys) / len(ys) if ys else 0.0

        groups: dict[str, list[dict[str, Any]]] = {"top": [], "bottom": []}
        for c in callouts:
            near = "top" if feature_y(c) < self.h / 2 else "bottom"
            mid = abs(feature_y(c) - self.h / 2) < 0.1 * self.h  # near the middle: keep the default side
            groups[side if mid else near].append(c)
        for sd in ("top", "bottom"):
            if groups[sd]:
                self._place_callouts_side(groups[sd], sd, size, placed, leaders)

    def _place_callouts_side(self, callouts: list[dict[str, Any]], side: str, size: float, placed: list[list[float]],
                             leaders: list[tuple[tuple[float, float], tuple[float, float]]]) -> None:
        sign = 1 if side == "top" else -1
        base = self.side_extent(side) + (4.0 if self.rows.get(side) else 6.0)
        row_y = base
        for c in sorted(callouts, key=lambda c: c["id"]):
            if c.get("tip") is not None:  # radius / chamfer: any of the arcs, nearest the text side first
                tips = [self.xy(u, v) for u, v in sorted(c.get("tips") or [c["tip"]], key=lambda q: (-sign * q[1], -q[0]))]
            else:  # representative hole: the one nearest the annotation side, then the right-most
                holes = sorted(c["holes"], key=lambda h: (-sign * h[1], -h[0]))
                u, v, r = holes[0]
                px, py = self.xy(u, v)
                rp = r * self.s
                ang = math.radians(45.0)
                tips = [(px + rp * math.cos(ang), py - sign * rp * math.sin(ang))]
            lines = c["lines"]
            lh = size * 1.45
            chosen = None
            start_y = row_y
            for attempt in range(24):  # first 12 rows avoid crossing other leaders; then accept a crossing
                strict = attempt < 12
                if attempt == 12:
                    row_y = start_y
                ky = -row_y if sign > 0 else self.h + row_y
                ky_first = ky if sign < 0 else ky - lh * (len(lines) - 1)
                for tip in tips:
                    for dirn in (1, -1):  # leader to the right, else to the left, never across another value
                        kx = tip[0] + dirn * abs(tip[1] - ky)
                        tx, anchor = (kx + 4.0, "start") if dirn > 0 else (kx - 4.0, "end")
                        boxes = []
                        for i, ln in enumerate(lines):
                            font = "italic" if ln["tag"] == "inferred" else "regular"
                            boxes.append(text_box(tx, ky_first + i * lh + 0.26 * size, size, ln["text"], anchor, 0, font))
                        if any(boxes_overlap(bx, q, 0.8) for bx in boxes for q in placed):
                            continue
                        if any(_seg_hits_box(tip, (kx, ky), q, 0.4) for q in placed):
                            continue
                        if strict and any(_segs_cross(tip, (kx, ky), a0, b0) for a0, b0 in leaders):
                            continue
                        chosen = (tip, kx, ky, ky_first, dirn, tx, anchor)
                        break
                    if chosen:
                        break
                if chosen:
                    break
                row_y += lh * len(lines) + 1.5
            if chosen is None:
                tip = tips[0]
                kx = tip[0] + abs(tip[1] - ky)
                chosen = (tip, kx, ky, ky_first, 1, kx + 4.0, "start")
            tip, kx, ky, ky_first, dirn, tx, anchor = chosen
            leaders.append((tip, (kx, ky)))
            g = self.g
            g.line("dim", tip[0], tip[1], kx, ky)
            g.line("dim", kx, ky, kx + 3.0 * dirn, ky)
            g.arrow(tip, (kx, ky))
            for i, ln in enumerate(lines):
                font = "italic" if ln["tag"] == "inferred" else "regular"
                t = g.text(tx, ky_first + i * lh + 0.26 * size, size, ln["text"], anchor=anchor, font=font,
                           color=ln["tag"], kind="callout", tag=ln["tag"], param=ln["param"], ref=c["id"],
                           params=ln.get("params"))
                placed.append(t["box"])
            row_y += lh * len(lines) + 1.5

    def cutting_plane(self, orient: str, at: float, arrow_dir: tuple[int, int], letter: str = "A") -> None:
        """Section cutting-plane line (chain, thick ends), view arrows and letters, ISO 128-40 style."""
        g = self.g
        if orient == "h":
            y = (self.vmax - at) * self.s
            p0, p1 = (-6.0, y), (self.w + 6.0, y)
        else:
            x = (at - self.umin) * self.s
            p0, p1 = (x, self.h + 6.0), (x, -6.0)
        g.line("cut", *p0, *p1)
        ux, uy = p1[0] - p0[0], p1[1] - p0[1]
        n = math.hypot(ux, uy)
        ux, uy = ux / n, uy / n
        for p, s in ((p0, 1), (p1, -1)):
            g.line("cutthick", p[0], p[1], p[0] + s * ux * 5.0, p[1] + s * uy * 5.0)
            tip = (p[0] + arrow_dir[0] * 7.0, p[1] + arrow_dir[1] * 7.0)
            g.line("dim", p[0], p[1], tip[0], tip[1])
            g.arrow(tip, p)
            self.reserved.append([min(p[0], tip[0]) - 1.2, min(p[1], tip[1]) - 1.2,
                                  max(p[0], tip[0]) + 1.2, max(p[1], tip[1]) + 1.2])
            lx, ly = tip[0] + arrow_dir[0] * 3.0, tip[1] + arrow_dir[1] * 3.0
            if arrow_dir[0] != 0:
                lx += arrow_dir[0] * 0.5
                t = g.text(lx, ly + 1.8, 5.0, letter, anchor="start" if arrow_dir[0] > 0 else "end", font="bold",
                           kind="label")
            else:
                t = g.text(lx, ly + (5.0 if arrow_dir[1] > 0 else 0.0), 5.0, letter, anchor="middle", font="bold",
                           kind="label")
            self.reserved.append(t["box"])

    def thread_marks(self, callouts: list[dict[str, Any]], side: list[tuple[Any, ...]],
                     ends: list[tuple[Any, ...]] | None = None) -> None:
        """ISO 6410-1 cosmetic threads. End views: a thin 3/4 circle at the thread root (the major Ø of a tapped
        hole, the minor Ø of an external thread). Side views of external threads: thin root lines over the thread
        length and a thick thread-limit line when the thread stops short. ``side``: (orientation, across, t0, t1,
        root radius, crest radius when the thread stops short / None) in view coordinates."""
        for c in callouts:
            th = c.get("thread")
            if not th:
                continue
            r = (th["major"] if th.get("internal") else th["minor"]) / 2 * self.s
            for u, v, *_ in c.get("holes") or []:
                x, y = self.xy(u, v)
                self.g.arc("thread", x, y, r, 100.0, 370.0)
        for u, v, rr in ends or []:  # external thread seen end-on (a turned diameter): root circle
            x, y = self.xy(u, v)
            self.g.arc("thread", x, y, rr * self.s, 100.0, 370.0)
        for orient, across, t0, t1, rr, crest in side:
            for sgn in (1, -1):
                if orient == "h":
                    a, b = self.xy(t0, across + sgn * rr), self.xy(t1, across + sgn * rr)
                else:
                    a, b = self.xy(across + sgn * rr, t0), self.xy(across + sgn * rr, t1)
                self.g.line("thread", a[0], a[1], b[0], b[1])
            if crest is not None:  # the thread stops short of the end: thick thread-limit line across the crest
                if orient == "h":
                    a, b = self.xy(t1, across - crest), self.xy(t1, across + crest)
                else:
                    a, b = self.xy(across - crest, t1), self.xy(across + crest, t1)
                self.g.line("visible", a[0], a[1], b[0], b[1])

    def detail_circle(self, u: float, v: float, r: float, letter: str) -> None:
        """The detail boundary on the parent view (thin circle) and its letter outside it, up and to the right."""
        x, y = self.xy(u, v)
        rp = r * self.s
        self.g.circle("detail", x, y, rp)
        # drawn after the dimensions and callouts: the letter takes the first diagonal clear of their texts
        taken = [t["box"] for t in self.g.texts()] + list(self.reserved)
        best = None
        for ang in (45, 135, 315, 225, 90, 270, 0, 180):
            ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            lx, ly = x + (rp + 1.8) * ca, y - (rp + 1.8) * sa
            anchor = "start" if ca > 0.3 else "end" if ca < -0.3 else "middle"
            by = ly + (1.8 if sa > 0.3 else 3.6 if sa < -0.3 else 1.8) if abs(sa) > 0.3 else ly + 1.8
            box = text_box(lx, by, 5.0, letter, anchor, 0, "bold")
            if not any(boxes_overlap(box, q, 0.6) for q in taken):
                best = (lx, by, anchor)
                break
        if best is None:
            best = (x + rp * 0.7071 + 1.2, y - rp * 0.7071 - 1.2, "start")
        t = self.g.text(best[0], best[1], 5.0, letter, anchor=best[2], font="bold", kind="label")
        self.reserved.append([t["box"][0] - 0.6, t["box"][1] - 0.6, t["box"][2] + 0.6, t["box"][3] + 0.6])

    def place_gdt(self, items: list[dict[str, Any]], size: float) -> list[dict[str, Any]]:
        """Feature control frames and datum symbols next to their dimension / callout, or on a leader to a point of
        the view, clear of every text already on the view and of the view's geometry. Returns the items it could
        not attach (their dimension is hidden or not on this view)."""
        from aicad.drawing import gdt

        placed = [t["box"] for t in self.g.texts()] + list(self.reserved)
        geom = [0.0, 0.0, self.w, self.h]
        missing: list[dict[str, Any]] = []

        def free(b: list[float]) -> bool:
            return not any(boxes_overlap(b, q, 0.6) for q in placed) and not boxes_overlap(b, geom, 0.8)

        for it in items:
            rec, tgt = it["rec"], it["target"]
            if it["type"] == "frame":
                w, h, _ = gdt.frame_size(rec, size, text_width)
            else:
                w, h = gdt.datum_size(size)
            chosen: tuple[float, float] | None = None
            anchor: tuple[float, float]
            if tgt["kind"] in ("dim", "callout"):
                boxes = [t["box"] for t in self.g.texts() if t.get("ref") == tgt["id"] and t.get("kind") in ("dim", "callout")]
                if not boxes:
                    missing.append(it)
                    continue
                ab = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
                midy = (ab[1] + ab[3]) / 2
                cands = [(ab[0], ab[3] + 1.0), (ab[0], ab[1] - 1.0 - h), (ab[2] + 1.5, midy - h / 2),
                         (ab[0] - 1.5 - w, midy - h / 2)]
                for k in range(1, 7):
                    cands += [(ab[0], ab[3] + 1.0 + k * (h + 1.2)), (ab[0], ab[1] - 1.0 - h - k * (h + 1.2)),
                              (ab[2] + 1.5 + k * 6.0, midy - h / 2)]
                for x, y in cands:
                    if free([x, y, x + w, y + h]):
                        chosen = (x, y)
                        break
                if chosen is None:
                    chosen = cands[0]
                bx = [chosen[0], chosen[1], chosen[0] + w, chosen[1] + h]
                # the anchor: the point of the text block nearest the symbol
                anchor = (min(max((bx[0] + bx[2]) / 2, ab[0]), ab[2]), min(max((bx[1] + bx[3]) / 2, ab[1]), ab[3]))
            else:
                anchor = self.xy(tgt["u"], tgt["v"])
                px, py = anchor
                sides = sorted([("top", py), ("bottom", self.h - py), ("left", px), ("right", self.w - px)],
                               key=lambda q: (q[1], q[0]))
                for k in range(8):
                    for side, _d in sides:
                        off = self.side_extent(side) + 6.0 + k * (h + 2.0)
                        for dx in (-w / 2, 4.0, -w - 4.0, 12.0, -w - 12.0):
                            if side == "top":
                                x, y = px + dx, -off - h
                            elif side == "bottom":
                                x, y = px + dx, self.h + off
                            elif side == "left":
                                x, y = -off - w, py + dx * h / max(w, 1e-6)
                            else:
                                x, y = self.w + off, py + dx * h / max(w, 1e-6)
                            if free([x, y, x + w, y + h]):
                                chosen = (x, y)
                                break
                        if chosen:
                            break
                    if chosen:
                        break
                if chosen is None:
                    chosen = (px - w / 2, -self.side_extent("top") - 6.0 - h)
                bx = [chosen[0], chosen[1], chosen[0] + w, chosen[1] + h]
            ref = it.get("ref")
            if it["type"] == "frame":
                gdt.draw_frame(self.g, rec, chosen[0], chosen[1], size * 0.9, text_width, ref=ref)
                if tgt["kind"] == "point" or not boxes_overlap(bx, [anchor[0], anchor[1], anchor[0], anchor[1]], 1.3):
                    mids = [((bx[0] + bx[2]) / 2, bx[1]), ((bx[0] + bx[2]) / 2, bx[3]), (bx[0], (bx[1] + bx[3]) / 2),
                            (bx[2], (bx[1] + bx[3]) / 2)]
                    m = min(mids, key=lambda q: math.dist(q, anchor))
                    if math.dist(m, anchor) > 0.5:
                        self.g.line("dim", m[0], m[1], anchor[0], anchor[1])
                        if tgt["kind"] == "point":
                            self.g.arrow(anchor, m)
            else:
                gdt.draw_datum(self.g, rec["letter"], (chosen[0], chosen[1]), anchor, size * 0.9, ref=ref)
            placed.append(bx)
            self.reserved.append(bx)
        return missing

    def caption(self, size: float) -> None:
        if not self.label:
            return
        below = self.side_extent("bottom")
        self.g.text(self.w / 2, self.h + below + 6.5 + size * 0.73, size, self.label, anchor="middle", font="bold",
                    kind="label")

    def bounds(self) -> list[float]:
        b = self.g.bounds() or [0.0, 0.0, self.w, self.h]
        return [min(b[0], 0.0), min(b[1], 0.0), max(b[2], self.w), max(b[3], self.h)]


# ----------------------------------------------------------------------------- the sheet
GRID = {"first": {"front": (0, 1), "top": (1, 1), "right": (0, 0), "_free": (1, 0)},
        "third": {"front": (1, 0), "top": (0, 0), "right": (1, 1), "_free": (0, 1)}}
SIDES = {"first": {"front": {"h": "top", "v": "right"}, "top": {"h": "bottom", "v": "right"},
                   "right": {"h": "top", "v": "left"}},
         "third": {"front": {"h": "bottom", "v": "left"}, "top": {"h": "top", "v": "left"},
                   "right": {"h": "bottom", "v": "right"}}}


def scale_label(sc: tuple[int, int]) -> str:
    return f"{sc[0]}:{sc[1]}"


def _wrap(txt: str, width: float, size: float, font: str = "regular") -> list[str]:
    words, lines, cur = txt.split(), [], ""
    for w in words:
        nxt = f"{cur} {w}".strip()
        if cur and text_width(nxt, size, font) > width:
            lines.append(cur)
            cur = w
        else:
            cur = nxt
    if cur:
        lines.append(cur)
    return lines


def _projection_symbol(g: Group, x: float, y: float, first_angle: bool) -> None:
    """ISO 5456-2 projection symbol inside a 30 x 7 mm area (top-left x, y)."""
    h1, h2, ln = 5.0, 2.6, 7.0  # large and small diameter, cone length
    cy = y + 3.5
    if first_angle:  # circles left, cone right with its large end towards the circles
        ccx, tx0 = x + 4.0, x + 10.0
        g.poly("tb", [[tx0, cy - h1 / 2], [tx0 + ln, cy - h2 / 2], [tx0 + ln, cy + h2 / 2], [tx0, cy + h1 / 2]], True)
    else:  # third angle: cone left with its small end towards the circles on the right
        tx0, ccx = x + 1.0, x + 14.0
        g.poly("tb", [[tx0, cy - h1 / 2], [tx0 + ln, cy - h2 / 2], [tx0 + ln, cy + h2 / 2], [tx0, cy + h1 / 2]], True)
    g.circle("tb", ccx, cy, h1 / 2)
    g.circle("tb", ccx, cy, h2 / 2)
    g.line("center", ccx - 3.4, cy, ccx + 3.4, cy)
    g.line("center", ccx, cy - 3.1, ccx, cy + 3.1)


def _info_blocks(W: float, H: float, meta: dict[str, Any], scale_txt: str, first_angle: bool,
                 revisions: list[dict[str, Any]], size: str, rev_at: str = "above") -> tuple[Group, list[float]]:
    """Title block (ISO 7200 fields) and the revision table of issued revisions, in the bottom-right corner.
    A4 uses a compact block so the views keep a sensible scale (MAKE-07). ``rev_at="top"`` puts the revision table
    in the top-right corner of the frame instead of over the title block (ASME Y14.35 practice; "topleft": a narrower
    table in the top-left corner), for sheets whose
    views need the space beside the title block; its box is then ``g.rev_box`` and the returned box is the title
    block's alone."""
    g = Group()
    g.rev_box = None  # type: ignore[attr-defined]
    compact = size in ("A4", "ANSI A")
    x0 = W - FRAME["right"] - TB_W
    yb = H - FRAME["bottom"]
    hb, h1, h2, h3, h4 = (6.0, 9.5, 7.5, 7.5, 6.5) if compact else (8.0, 12.0, 9.0, 9.0, 8.0)
    lab, val, tsz = (1.6, 2.8, 3.9) if compact else (1.8, 3.2, 4.6)
    tb_h = hb + h1 + h2 + h3 + h4
    y0 = yb - tb_h
    # banner
    g.fill("bannerfill", [[x0, y0], [x0 + TB_W, y0], [x0 + TB_W, y0 + hb], [x0, y0 + hb]])
    g.rect("banner", x0, y0, TB_W, hb)
    bsz = 3.4 if compact else 4.2
    g.text(x0 + TB_W / 2, y0 + hb / 2 + bsz * 0.36, bsz, "NOT APPROVED FOR MANUFACTURE", anchor="middle",
           font="bold", color="banner", kind="banner")
    g.rect("tb", x0, y0, TB_W, tb_h)
    r1 = y0 + hb
    r2, r3, r4 = r1 + h1, r1 + h1 + h2, r1 + h1 + h2 + h3
    for ry in (r1, r2, r3, r4):
        g.line("tb", x0, ry, x0 + TB_W, ry)

    def cell(cx: float, cy: float, w: float, h: float, label: str, value: str, vsize: float = val,
             font: str = "regular", kind: str = "title") -> None:
        g.line("tbthin", cx, cy, cx, cy + h)
        g.text(cx + 1.2, cy + lab + 0.7, lab, label, color="label", kind="title")
        avail = w - 3.0
        v = value
        while v and text_width(v, vsize, font) > avail:
            v = v[:-2] + "…" if len(v) > 2 else ""
        if v:
            g.text(cx + 1.5, cy + h - (1.6 if compact else 2.0), vsize, v, font=font, kind=kind)

    cell(x0, r1, 120, h1, "TITLE", meta.get("title", ""), tsz, "bold")
    cell(x0 + 120, r1, 60, h1, "DRAWING NO.", meta.get("drawing_no", ""), val + 0.2)
    src = meta.get("source", "")
    if src:
        g.text(x0 + TB_W - 1.2, r1 + lab + 0.7, lab, src, anchor="end", color="label", kind="title")
    cell(x0, r2, 62, h2, "MATERIAL", meta.get("material") or "Not specified")
    cell(x0 + 62, r2, 20, h2, "UNITS", meta.get("units") or "mm")
    cell(x0 + 82, r2, 22, h2, "SCALE", scale_txt)
    g.line("tbthin", x0 + 104, r2, x0 + 104, r2 + h2)
    g.text(x0 + 105.2, r2 + lab + 0.7, lab, "PROJECTION", color="label", kind="title")
    _projection_symbol(g, x0 + 119, r2 + h2 / 2 - 3.5 + (0.6 if compact else 1.0), first_angle)
    cell(x0 + 140, r2, 40, h2, "SHEET", f"{size}   1 / 1")
    cell(x0, r3, 48, h3, "DRAWN BY", meta.get("drawn_by", ""))
    cell(x0 + 48, r3, 30, h3, "DATE", meta.get("date", ""))
    cell(x0 + 78, r3, 18, h3, "REV", meta.get("rev", "-"), font="bold")
    cell(x0 + 96, r3, 84, h3, "GENERAL TOLERANCES", meta.get("tolerance", "Not specified"), val - 0.4)
    cell(x0, r4, 48, h4, "CHECKED", meta.get("checked_by") or "-", val - 0.4)
    cell(x0 + 48, r4, 48, h4, "APPROVED", "- (not approved)", val - 0.4)
    cell(x0 + 96, r4, 84, h4, "COMPANY", meta.get("company") or "-", val - 0.4)

    top = y0
    # revision table: issued revisions only (ISO 7200 / ASME Y14.35), newest last, at most 3 rows
    rows_h = revisions[-3:]
    if rows_h:
        rt_h = 5.0 + 4.6 * len(rows_h)
        ry = y0 - 2.0 - rt_h if rev_at == "above" else FRAME["top"] + 2.0
        rw = TB_W if rev_at != "topleft" else 90.0
        rx = x0 if rev_at != "topleft" else FRAME["left"] + 2.0
        g.rect("tbthin", rx, ry, rw, rt_h)
        cols = ([(0, 14, "REV"), (14, 104, "DESCRIPTION"), (118, 26, "DATE"), (144, 36, "BY")] if rev_at != "topleft"
                else [(0, 9, "REV"), (9, 41, "DESCRIPTION"), (50, 21, "DATE"), (71, 19, "BY")])
        for cx, _w, lab_ in cols:
            if cx:
                g.line("tbthin", rx + cx, ry, rx + cx, ry + rt_h)
            g.text(rx + cx + 1.2, ry + 3.6, 2.0, lab_, font="bold", color="label", kind="rev")
        g.line("tbthin", rx, ry + 5.0, rx + rw, ry + 5.0)
        for i, h in enumerate(rows_h):
            yy = ry + 5.0 + 4.6 * i + 3.4
            vals = [str(h.get("rev", "")), str(h.get("change", "")), str(h.get("date", "")), str(h.get("by", ""))]
            for (cx, w, _lab), v in zip(cols, vals, strict=True):
                while v and text_width(v, 2.3) > w - 2.4:
                    v = v[:-2] + "…"
                g.text(rx + cx + 1.2, yy, 2.3, v, kind="rev")
        if rev_at != "above":
            g.rev_box = [rx, ry, rx + rw, ry + rt_h]  # type: ignore[attr-defined]
        else:
            top = ry
    return g, [x0, top, x0 + TB_W, yb]


def _notes_block(W: float, H: float, notes: list[str], right: float) -> tuple[Group, list[float] | None]:
    """Dimension-tag legend (review copy only: its prims are ``kind == "legend"``) and numbered notes, bottom-left
    of the frame. The legend's space is reserved in both copies so they share one layout and scale."""
    g = Group()
    x0 = FRAME["left"] + 4.0
    width = right - x0 - 6.0
    entries: list[list[tuple[float, tuple[str, str, str, str]]]] = [[]]
    x = 0.0
    for e in LEGEND:
        w = text_width(e[0], 3.0, e[1]) + 1.6 + text_width(e[3], 2.1) + 5.0
        if x and x + w > width:
            entries.append([])
            x = 0.0
        entries[-1].append((x, e))
        x += w
    lines: list[tuple[str, str]] = []
    for i, n in enumerate(notes, 1):
        wrapped = _wrap(n, width - 6.0, 2.5)
        for j, w in enumerate(wrapped):
            lines.append((f"{i}." if j == 0 else "", w))
    lh = 3.6
    leg_h = 4.4 * len(entries) + 2.5
    h = leg_h + 5.5 + lh * len(lines) + 1.5
    yb = H - FRAME["bottom"] - 3.0
    y0 = yb - h
    for r, row in enumerate(entries):
        yy = y0 + 4.4 * (r + 1) - 0.6
        for ex, (txt, font, color, label) in row:
            g.text(x0 + ex, yy, 3.0, txt, font=font, color=color, kind="legend",
                   tag=color if color in ("spec", "inferred") else None)
            g.text(x0 + ex + text_width(txt, 3.0, font) + 1.6, yy, 2.1, label, kind="legend")
    ny = y0 + leg_h
    g.text(x0, ny + 3.6, 2.6, "NOTES", font="bold", kind="note")
    for i, (num, ln) in enumerate(lines):
        yy = ny + 5.5 + lh * (i + 1) - 0.8
        if num:
            g.text(x0, yy, 2.5, num, kind="note")
        g.text(x0 + 5.0, yy, 2.5, ln, kind="note")
    return g, [x0 - 1.0, y0, x0 + width, yb]


SECTION_SIDES = {"h": "top", "v": "right"}


def compose(an: dict[str, Any], dims: list[dict[str, Any]], callouts: list[dict[str, Any]], notes: list[str],
            opts: dict[str, Any], meta: dict[str, Any], revisions: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose the largest standard scale at which everything fits, and build the sheet. At each scale the
    isometric view may shrink (up to three steps) before the principal views are drawn smaller; as a last resort at
    a scale the isometric view is left out rather than shrinking the views that carry the dimensions."""
    size = opts.get("sheet", "A3")
    W, H = SHEETS[size]
    has_iso = "iso" in an["views"]
    for sc in SCALES:
        for iso_step in ((0, 1, 2, 3) if has_iso else (0,)):
            sheet = _try(an, dims, callouts, notes, opts, meta, revisions, sc, iso_step, W, H, size)
            if sheet is not None:
                return sheet
        if has_iso and sc[1] > 1:  # below 1:1: rather drop the iso than shrink the dimensioned views
            sheet = _try(an, dims, callouts, notes, opts, meta, revisions, sc, None, W, H, size)
            if sheet is not None:
                sheet["iso_dropped"] = True
                return sheet
    best = _try(an, dims, callouts, notes, opts, meta, revisions, SCALES[-1], None, W, H, size, force=True)
    assert best is not None
    return best


def _try(an: dict[str, Any], dims: list[dict[str, Any]], callouts: list[dict[str, Any]], notes: list[str],
         opts: dict[str, Any], meta: dict[str, Any], revisions: list[dict[str, Any]], sc: tuple[int, int],
         iso_step: int | None, W: float, H: float, size: str, force: bool = False) -> dict[str, Any] | None:
    from aicad.drawing.dims import COORD

    s = sc[0] / sc[1]
    proj = opts.get("projection", "first")
    views_on = [v for v in ("front", "top", "right") if v in an["views"]]
    dim_size = 3.5 if size == "A3" else 3.0
    vls: dict[str, ViewLayout] = {}
    sec_opt = an.get("section")
    front_section = bool(an["views"].get("front", {}).get("is_section"))
    sec_ref = None
    if sec_opt:
        prefs = {"y": ["top", "right"], "x": ["top", "front"], "z": ["front", "right"]}[sec_opt["axis"]]
        sec_ref = next((v for v in prefs if v in views_on), None)
    for v in views_on:
        geom = an["views"][v]
        if v == "front" and front_section:
            vl = ViewLayout(v, geom, s, hidden=False, label="SECTION A-A")
            vl.hatch(geom["loops"], 2.5 if size == "A3" else 2.0)
        else:
            vl = ViewLayout(v, geom, s, hidden=opts.get("hidden", True))
        vls[v] = vl
    # centre lines for holes and cylinder axes
    for v, vl in vls.items():
        cos = [c for c in callouts if c["view"] == v]
        axes: list[tuple[str, float, float, float]] = []
        for h in an["census"]["holes"] + an["census"]["outer"]:
            ax = h["axis"]
            cm = COORD[v]
            if ax not in cm:
                continue
            other = next(a for a in cm if a != ax)
            oi = [a for a in ("x", "y", "z") if a != ax].index(other)
            across = h["centre"][oi]
            orient = "h" if cm[ax] == "u" else "v"
            key = (orient, across)
            if any((a[0], a[1]) == key for a in axes):
                lo_, hi_ = next((a[2], a[3]) for a in axes if (a[0], a[1]) == key)
                axes = [a for a in axes if (a[0], a[1]) != key]
                axes.append((orient, across, min(lo_, h["t0"]), max(hi_, h["t1"])))
            else:
                axes.append((orient, across, h["t0"], h["t1"]))
        vl.centre_lines(cos, sorted(axes))
        tl = [t for t in an.get("thread_lines") or [] if t[0] == v]
        vl.thread_marks(cos, [t[2:] for t in tl if t[1] == "side"], [t[2:] for t in tl if t[1] == "end"])
    details = an.get("details") or []
    if sec_opt and sec_ref:
        cm = {"top": {"x": "u", "y": "v"}, "front": {"x": "u", "z": "v"}, "right": {"y": "u", "z": "v"}}[sec_ref]
        o = cm[sec_opt["axis"]]
        # arrows show the direction of sight of the section view
        look = {"y": (0, 1, 0), "x": (-1, 0, 0), "z": (0, 0, -1)}[sec_opt["axis"]]
        axis_vec: dict[str, str] = {}
        for a, c in cm.items():
            axis_vec[c] = a
        ai = {"x": 0, "y": 1, "z": 2}
        du = look[ai[axis_vec["u"]]]
        dv = look[ai[axis_vec["v"]]]
        vls[sec_ref].cutting_plane("v" if o == "u" else "h", sec_opt["plane"], (int(du), int(-dv)))
    gdt_items = an.get("gdt_items") or []
    gdt_missing: list[dict[str, Any]] = []
    for v, vl in vls.items():
        sides = SIDES[proj][v]
        vl.place_dims([d for d in dims if d["view"] == v], sides, dim_size)
        vl.place_callouts([c for c in callouts if c["view"] == v], sides["h"], dim_size)
        for dd in details:
            if dd["parent"] == v:
                vl.detail_circle(dd["u"], dd["v"], dd["r"], dd["letter"])
        gdt_missing += vl.place_gdt([g for g in gdt_items if g["view"] == v], dim_size)
        if vl.label:
            vl.caption(3.5)
    extras: list[ViewLayout] = []
    iso_scale = s
    if "iso" in an["views"] and iso_step is not None:
        idx = SCALES.index(sc) + iso_step
        if idx >= len(SCALES):
            return None
        iso_sc = SCALES[idx]
        iso_scale = iso_sc[0] / iso_sc[1]
        label = "ISOMETRIC VIEW" + (f"  SCALE {scale_label(iso_sc)}" if iso_step else "")
        iso = ViewLayout("iso", an["views"]["iso"], iso_scale, hidden=False, label=label)
        iso.caption(3.5)
        extras.append(iso)
    elif iso_step:
        return None
    if sec_opt and not front_section:
        sv = ViewLayout("section", sec_opt, s, hidden=False, label="SECTION A-A")
        sv.hatch(sec_opt["loops"], 2.5 if size == "A3" else 2.0)
        sv.place_dims([d for d in dims if d["view"] == "section"], SECTION_SIDES, dim_size)
        for dd in details:
            if dd["parent"] == "section":
                sv.detail_circle(dd["u"], dd["v"], dd["r"], dd["letter"])
        gdt_missing += sv.place_gdt([g for g in gdt_items if g["view"] == "section"], dim_size)
        sv.caption(3.5)
        extras.insert(0, sv)
    gdt_missing += [g for g in gdt_items if g["view"] not in vls and not (g["view"] == "section" and sec_opt
                                                                          and not front_section)]
    from aicad.drawing.detail import STANDARD, _seg_t, choose_scale

    def build_detail(dd: dict[str, Any], dsc: tuple[int, int]) -> ViewLayout:
        ds = dsc[0] / dsc[1]
        dv = ViewLayout(f"detail-{dd['letter']}", dd["geom"], ds, hidden=opts.get("hidden", True),
                        label=f"DETAIL {dd['letter']} ({scale_label(dsc)})")
        dv.detail_scale = dsc  # type: ignore[attr-defined]
        cx, cy = dv.xy(dd["u"], dd["v"])
        if dd["geom"].get("loops"):  # detail of a section: the hatch, clipped to the detail circle
            paper = [[list(dv.xy(q[0], q[1])) for q in lp] for lp in dd["geom"]["loops"]]
            for ln in _hatch(paper, 2.5 if size == "A3" else 2.0):
                t = _seg_t((ln[0], ln[1]), (ln[2], ln[3]), (cx, cy), dd["r"] * ds)
                if t:
                    dv.g.line("hatch", ln[0] + (ln[2] - ln[0]) * t[0], ln[1] + (ln[3] - ln[1]) * t[0],
                              ln[0] + (ln[2] - ln[0]) * t[1], ln[1] + (ln[3] - ln[1]) * t[1])
        dv.g.circle("detail", cx, cy, dd["r"] * ds)
        dv.caption(3.5)
        return dv

    detail_info: list[dict[str, Any]] = []
    alts: dict[int, list[ViewLayout]] = {}  # smaller enlargements to try when a detail does not fit
    detail_of: dict[int, dict[str, Any]] = {}
    for dd in details:
        if dd["parent"] not in vls and not (dd["parent"] == "section" and sec_opt and not front_section):
            continue
        dsc = choose_scale(dd.get("scale"), s, dd["r"])
        dv = build_detail(dd, dsc)
        smaller = [q for q in STANDARD if s + 1e-9 < q[0] / q[1] < dsc[0] / dsc[1] - 1e-9]
        alts[id(dv)] = [build_detail(dd, q) for q in smaller]
        detail_of[id(dv)] = dd
        extras.append(dv)

    frame = [FRAME["left"], FRAME["top"], W - FRAME["right"], H - FRAME["bottom"]]

    def info_layout(rev_at: str) -> tuple[Group, list[float], Group, list[float] | None, list[list[float]]]:
        g, box = _info_blocks(W, H, meta, scale_label(sc), proj == "first", revisions, size, rev_at)
        ng, nbox = _notes_block(W, H, notes, box[0])
        rb = getattr(g, "rev_box", None)
        return g, box, ng, nbox, [box] + ([rb] if rb else []) + ([nbox] if nbox else [])

    info, _box, notes_g, notes_box, blocked = info_layout("above")

    # grid of principal views, aligned by projection
    cells = GRID[proj]
    col_l: dict[int, float] = {}
    col_r: dict[int, float] = {}
    row_t: dict[int, float] = {}
    row_b: dict[int, float] = {}
    for v, vl in vls.items():
        r, c = cells[v]
        b = vl.bounds()
        col_l[c] = max(col_l.get(c, 0.0), vl.w / 2 - b[0])
        col_r[c] = max(col_r.get(c, 0.0), b[2] - vl.w / 2)
        row_t[r] = max(row_t.get(r, 0.0), vl.h / 2 - b[1])
        row_b[r] = max(row_b.get(r, 0.0), b[3] - vl.h / 2)
    x = frame[0] + 6.0
    col_cx = {}
    for c in (0, 1):
        if c in col_l:
            col_cx[c] = x + col_l[c]
            x = col_cx[c] + col_r[c] + VIEW_GAP
    y = frame[1] + 6.0
    row_cy = {}
    for r in (0, 1):
        if r in row_t:
            row_cy[r] = y + row_t[r]
            y = row_cy[r] + row_b[r] + VIEW_GAP
    pos: dict[Any, tuple[float, float]] = {}
    for v, vl in vls.items():
        r, c = cells[v]
        pos[v] = (col_cx[c] - vl.w / 2, row_cy[r] - vl.h / 2)

    def abs_box(vl: ViewLayout, p: tuple[float, float]) -> list[float]:
        b = vl.bounds()
        return [b[0] + p[0], b[1] + p[1], b[2] + p[0], b[3] + p[1]]

    def ok(box: list[float], others: list[list[float]]) -> bool:
        if box[0] < frame[0] + 2 or box[1] < frame[1] + 2 or box[2] > frame[2] - 2 or box[3] > frame[3] - 2:
            return False
        return not any(boxes_overlap(box, o, 2.0) for o in others)

    occupied = [abs_box(vls[v], pos[v]) for v in vls]
    if not force and not all(ok(b, blocked) for b in occupied) and revisions:
        # the revision table over the title block is in the way: try it in the top-right corner of the frame
        for where in ("top", "topleft"):
            alt = info_layout(where)
            if all(ok(b, alt[4]) for b in occupied):
                info, _box, notes_g, notes_box, blocked = alt
                break
    if not force and not all(ok(b, blocked) for b in occupied):
        return None
    grid_box = [min(b[0] for b in occupied), min(b[1] for b in occupied),
                max(b[2] for b in occupied), max(b[3] for b in occupied)] if occupied else [frame[0] + 6] * 2 + [frame[0] + 6] * 2
    fr, fc = cells["_free"]
    def place_extra(ex: ViewLayout, last: bool) -> bool:
        b = ex.bounds()
        bw, bh = b[2] - b[0], b[3] - b[1]
        cands: list[tuple[float, float]] = []
        if fc in col_cx and fr in row_cy:  # the empty quadrant of the grid
            cands.append((col_cx[fc] - bw / 2, row_cy[fr] - bh / 2))
            qx0 = col_cx[fc] - col_l[fc]
            qy0 = row_cy[fr] - row_t[fr]
            cands.append((qx0, qy0))
        right = max(o[2] for o in occupied) + VIEW_GAP + 2.0
        for r in sorted(row_cy):
            cands.append((right, row_cy[r] - bh / 2))
        cands.append((right, grid_box[1]))
        below = max(o[3] for o in occupied) + VIEW_GAP + 2.0
        cands.append((grid_box[0], below))
        for o in occupied:
            cands.append((o[2] + VIEW_GAP + 2.0, o[1]))
            cands.append((o[0], o[3] + VIEW_GAP + 2.0))
        cands.append((frame[2] - 4 - bw, frame[1] + 4))  # top-right corner
        cands.append((frame[0] + 4, frame[3] - 4 - bh - (notes_box[3] - notes_box[1] if notes_box else 0)))
        chosen = None
        for cx, cy in cands:
            p = (cx - b[0], cy - b[1])
            box = [cx, cy, cx + bw, cy + bh]
            if ok(box, occupied + blocked):
                chosen = p
                break
        if chosen is None:
            if not force or not last:
                return False
            chosen = (right - b[0], grid_box[1] - b[1])
        pos[id(ex)] = chosen
        occupied.append(abs_box(ex, chosen))
        return True

    for i0, ex0 in enumerate(list(extras)):
        options = [ex0, *alts.get(id(ex0), [])]
        for k, ex in enumerate(options):
            if place_extra(ex, k == len(options) - 1):
                if ex is not ex0:
                    extras[i0] = ex
                break
        else:
            return None
        if id(ex0) in detail_of:
            dd = detail_of[id(ex0)]
            detail_info.append({"letter": dd["letter"], "parent": dd["parent"],
                                "scale": scale_label(extras[i0].detail_scale),  # type: ignore[attr-defined]
                                "u": dd["u"], "v": dd["v"], "r": dd["r"]})

    # centre the composition horizontally where the space allows
    content = [min(b[0] for b in occupied), min(b[1] for b in occupied),
               max(b[2] for b in occupied), max(b[3] for b in occupied)]
    dx_full = ((frame[0] + frame[2]) / 2) - (content[0] + content[2]) / 2
    dy_full = max(0.0, ((frame[1] + frame[3] - 50) / 2) - (content[1] + content[3]) / 2)
    shift = (0.0, 0.0)
    for f in (1.0, 0.75, 0.5, 0.25, 0.0):
        for fy in (1.0, 0.5, 0.0):
            moved = [[b[0] + dx_full * f, b[1] + dy_full * fy, b[2] + dx_full * f, b[3] + dy_full * fy]
                     for b in occupied]
            if all(ok(b, blocked) for b in moved):
                shift = (dx_full * f, dy_full * fy)
                break
        else:
            continue
        break

    prims: list[dict[str, Any]] = []
    fg = Group()
    fg.rect("frame", frame[0], frame[1], frame[2] - frame[0], frame[3] - frame[1])
    prims += fg.placed(0, 0)
    view_rects: dict[str, list[float]] = {}
    view_info: dict[str, dict[str, Any]] = {}
    for vl in [*vls.values(), *extras]:
        p = pos[vl.name] if vl.name in pos else pos[id(vl)]
        p = (p[0] + shift[0], p[1] + shift[1])
        for q in vl.g.placed(p[0], p[1]):
            q["view"] = vl.name
            prims.append(q)
        view_rects[vl.name] = [p[0], p[1], p[0] + vl.w, p[1] + vl.h]
        view_info[vl.name] = {"rect": view_rects[vl.name], "extents": vl.geom["extents"],
                              "scale": vl.s, "origin": [vl.umin, vl.vmax]}
    prims += info.placed(0, 0)
    prims += notes_g.placed(0, 0)
    return {"size": size, "w": W, "h": H, "scale": list(sc), "scale_txt": scale_label(sc), "iso_scale": iso_scale,
            "projection": proj, "frame": frame, "prims": prims, "views": view_info, "blocked": blocked,
            "iso_dropped": False, "details": detail_info,
            "gdt_missing": [{"type": g["type"], "ref": g.get("ref")} for g in gdt_missing]}
