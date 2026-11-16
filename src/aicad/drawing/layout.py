"""Sheet layout: frame, scale, view placement, dimensions, callouts, title block, legend and revision table.

Pure Python (no CAD kernel). Paper coordinates are millimetres with the origin at the top-left corner and y down.
Every primitive is a plain dict so the SVG, PDF and DXF renderers draw exactly the same sheet:

  {"t": "line", "l": layer, "p": [x1, y1, x2, y2]}
  {"t": "poly", "l": layer, "p": [[x, y], ...], "closed": bool}
  {"t": "circle", "l": layer, "p": [cx, cy, r]}
  {"t": "arc", "l": layer, "p": [cx, cy, r, a0, a1]}      degrees, counter-clockwise as seen on paper
  {"t": "fill", "l": layer, "p": [[x, y], ...]}            filled polygon (arrowheads)
  {"t": "text", "l": layer, "x", "y" (baseline), "s" (cap size), "txt", "anchor", "rot" (0 or 90),
   "font" ("regular" | "bold" | "italic"), "tag", "param", "kind", "box" [x0, y0, x1, y1]}
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
             param: str | None = None, ref: str | None = None) -> dict[str, Any]:
        t = {"t": "text", "l": "text", "x": x, "y": y, "s": size, "txt": txt, "anchor": anchor, "rot": rot,
             "font": font, "color": color, "kind": kind, "tag": tag, "param": param, "ref": ref,
             "box": text_box(x, y, size, txt, anchor, rot, font)}
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
            rows: list[list[dict[str, Any]]] = []
            fam_row: dict[str, int] = {}
            for d in ds:
                placed = False
                start = fam_row.get(d["family"], 0)
                for r in [start, *range(len(rows) + 1)]:
                    if r < start and d["family"] in fam_row:
                        continue
                    cand = self._dim_geometry(d, side, r, size)
                    for c in cand:
                        if r >= len(rows) or self._fits(c, rows[r]):
                            while len(rows) <= r:
                                rows.append([])
                            rows[r].append(c)
                            fam_row.setdefault(d["family"], r)
                            placed = True
                            break
                    if placed:
                        break
                if not placed:  # cannot happen (a new row is always free) but keep the dimension anyway
                    c = self._dim_geometry(d, side, len(rows), size)[0]
                    rows.append([c])
            self.rows[side] = [c for row in rows for c in row]
            self.reserved += [c["tbox"] for row in rows for c in row]  # later sides avoid these texts
            for row in rows:
                for c in row:
                    self._emit(c)

    def _fits(self, c: dict[str, Any], row: list[dict[str, Any]]) -> bool:
        for o in row:
            if boxes_overlap(c["tbox"], o["tbox"], 0.8):
                return False
            if c["family"] != o["family"] and c["span"][0] < o["span"][1] - 0.01 and o["span"][0] < c["span"][1] - 0.01:
                return False
        return not any(boxes_overlap(c["tbox"], r, 0.5) for r in self.reserved)

    def _dim_geometry(self, d: dict[str, Any], side: str, row: int, size: float) -> list[dict[str, Any]]:
        """Candidate drawings of one dimension in a row: text inside, then outside right / left."""
        sign = {"top": 1, "right": 1, "bottom": -1, "left": -1}[side]
        off = FIRST_ROW + ROW * row
        txt = d["text"]
        font = "italic" if d["tag"] == "inferred" else "regular"
        tw = text_width(txt, size, font)
        out = []
        if d["orient"] == "h":
            xa, xb = self.xy(d["a"], 0)[0], self.xy(d["b"], 0)[0]
            yd = -off if sign > 0 else self.h + off
            fits = xb - xa >= tw + 2 * ARROW + 1.5
            places = (["in"] if fits else []) + ["right", "left"]
            for pl in places:
                if pl == "in":
                    tx, anchor = (xa + xb) / 2, "middle"
                elif pl == "right":
                    tx, anchor = xb + ARROW + 1.2, "start"
                else:
                    tx, anchor = xa - ARROW - 1.2, "end"
                ty = yd - 1.0
                tb = text_box(tx, ty, size, txt, anchor, 0, font)
                span = [xa - (0 if fits else ARROW + 1), xb + (0 if fits else ARROW + 1)]
                out.append({**d, "side": side, "sign": sign, "row": row, "yd": yd, "xa": xa, "xb": xb,
                            "tx": tx, "ty": ty, "anchor": anchor, "font": font, "size": size, "tbox": tb,
                            "span": [min(span[0], tb[0]), max(span[1], tb[2])], "inside": fits,
                            "family": d["family"]})
        else:
            ya, yb = self.xy(0, d["a"])[1], self.xy(0, d["b"])[1]  # ya > yb on paper (V up)
            xd = self.w + off if sign > 0 else -off
            fits = ya - yb >= tw + 2 * ARROW + 1.5
            places = (["in"] if fits else []) + ["up", "down"]
            for pl in places:
                if pl == "in":
                    ty, anchor = (ya + yb) / 2, "middle"
                elif pl == "up":
                    ty, anchor = yb - ARROW - 1.2, "start"
                else:
                    ty, anchor = ya + ARROW + 1.2, "end"
                tx = xd - 1.0
                tb = text_box(tx, ty, size, txt, anchor, 90, font)
                span = [yb - (0 if fits else ARROW + 1), ya + (0 if fits else ARROW + 1)]
                out.append({**d, "side": side, "sign": sign, "row": row, "xd": xd, "ya": ya, "yb": yb,
                            "tx": tx, "ty": ty, "anchor": anchor, "font": font, "size": size, "tbox": tb,
                            "span": [min(span[0], tb[1]), max(span[1], tb[3])], "inside": fits,
                            "family": d["family"]})
        return out

    def _emit(self, c: dict[str, Any]) -> None:
        g = self.g
        color = "aux" if c.get("aux") else c["tag"]
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
            if c["inside"]:
                g.line("dim", xa, yd, xb, yd)
                g.arrow((xa, yd), (xb, yd))
                g.arrow((xb, yd), (xa, yd))
            else:
                g.line("dim", xa - ARROW - 2.5, yd, xb + ARROW + 2.5, yd)
                g.arrow((xa, yd), (xa - 5, yd))
                g.arrow((xb, yd), (xb + 5, yd))
            g.text(c["tx"], c["ty"], c["size"], c["text"], anchor=c["anchor"], font=c["font"], color=color,
                   kind="dim", tag=c["tag"], param=c["param"], ref=c["id"])
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
            if c["inside"]:
                g.line("dim", xd, ya, xd, yb)
                g.arrow((xd, ya), (xd, yb))
                g.arrow((xd, yb), (xd, ya))
            else:
                g.line("dim", xd, ya + ARROW + 2.5, xd, yb - ARROW - 2.5)
                g.arrow((xd, ya), (xd, ya + 5))
                g.arrow((xd, yb), (xd, yb - 5))
            g.text(c["tx"], c["ty"], c["size"], c["text"], anchor=c["anchor"], rot=90, font=c["font"],
                   color=color, kind="dim", tag=c["tag"], param=c["param"], ref=c["id"])

    def side_extent(self, side: str) -> float:
        """How far (mm) the dimension rows on a side reach beyond the geometry."""
        rows = self.rows.get(side, [])
        return 0.0 if not rows else FIRST_ROW + ROW * max(c["row"] for c in rows) + 4.5

    def place_callouts(self, callouts: list[dict[str, Any]], side: str, size: float) -> None:
        """Leader + text for each hole group, beyond the dimension rows on ``side`` ('top' or 'bottom')."""
        sign = 1 if side == "top" else -1
        base = self.side_extent(side) + (4.0 if self.rows.get(side) else 6.0)
        placed: list[list[float]] = [c["tbox"] for c in self.rows.get(side, [])] + list(self.reserved)
        row_y = base
        for c in sorted(callouts, key=lambda c: c["id"]):
            # representative hole: the one nearest the annotation side, then the right-most
            holes = sorted(c["holes"], key=lambda h: (-sign * h[1], -h[0]))
            u, v, r = holes[0]
            px, py = self.xy(u, v)
            rp = r * self.s
            ang = math.radians(45.0)
            tip = (px + rp * math.cos(ang), py - sign * rp * math.sin(ang))
            lines = c["lines"]
            lh = size * 1.45
            for _ in range(12):
                ky = -row_y if sign > 0 else self.h + row_y
                if sign < 0:
                    ky_first = ky
                else:
                    ky_first = ky - lh * (len(lines) - 1)
                kx = tip[0] + abs(tip[1] - ky)
                boxes = []
                for i, ln in enumerate(lines):
                    font = "italic" if ln["tag"] == "inferred" else "regular"
                    boxes.append(text_box(kx + 4.0, ky_first + i * lh + 0.26 * size, size, ln["text"], "start", 0, font))
                if not any(boxes_overlap(b, p, 0.8) for b in boxes for p in placed):
                    break
                row_y += lh * len(lines) + 1.5
            g = self.g
            g.line("dim", tip[0], tip[1], kx, ky)
            g.line("dim", kx, ky, kx + 3.0, ky)
            g.arrow(tip, (kx, ky))
            for i, ln in enumerate(lines):
                font = "italic" if ln["tag"] == "inferred" else "regular"
                t = g.text(kx + 4.0, ky_first + i * lh + 0.26 * size, size, ln["text"], font=font, color=ln["tag"],
                           kind="callout", tag=ln["tag"], param=ln["param"], ref=c["id"])
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
                 history: list[dict[str, Any]], size: str, legend: bool = False) -> tuple[Group, list[float]]:
    """Title block, tag legend and revision table stacked in the bottom-right corner."""
    g = Group()
    x0 = W - FRAME["right"] - TB_W
    yb = H - FRAME["bottom"]
    tb_h = 46.0
    y0 = yb - tb_h
    # banner
    g.fill("bannerfill", [[x0, y0], [x0 + TB_W, y0], [x0 + TB_W, y0 + 8], [x0, y0 + 8]])
    g.rect("banner", x0, y0, TB_W, 8.0)
    g.text(x0 + TB_W / 2, y0 + 5.6, 4.2, "NOT APPROVED FOR MANUFACTURE", anchor="middle", font="bold",
           color="banner", kind="banner")
    g.rect("tb", x0, y0, TB_W, tb_h)
    rows = [(y0 + 8, 12.0), (y0 + 20, 9.0), (y0 + 29, 9.0), (y0 + 38, 8.0)]
    for ry, _rh in rows:
        g.line("tb", x0, ry, x0 + TB_W, ry)

    def cell(cx: float, cy: float, w: float, h: float, label: str, value: str, vsize: float = 3.2,
             font: str = "regular") -> None:
        g.line("tbthin", cx, cy, cx, cy + h)
        g.text(cx + 1.2, cy + 2.5, 1.8, label, color="label", kind="title")
        avail = w - 3.0
        v = value
        while v and text_width(v, vsize, font) > avail:
            v = v[:-2] + "…" if len(v) > 2 else ""
        if v:
            g.text(cx + 1.5, cy + h - 2.0, vsize, v, font=font, kind="title")

    r1, r2, r3, r4 = rows
    cell(x0, r1[0], 120, 12, "TITLE", meta.get("title", ""), 4.6, "bold")
    cell(x0 + 120, r1[0], 60, 12, "DRAWING NO.", meta.get("drawing_no", ""), 3.4)
    cell(x0, r2[0], 62, 9, "MATERIAL", meta.get("material") or "Not specified")
    cell(x0 + 62, r2[0], 20, 9, "UNITS", "mm")
    cell(x0 + 82, r2[0], 22, 9, "SCALE", scale_txt)
    g.line("tbthin", x0 + 104, r2[0], x0 + 104, r2[0] + 9)
    g.text(x0 + 105.2, r2[0] + 2.5, 1.8, "PROJECTION", color="label", kind="title")
    _projection_symbol(g, x0 + 119, r2[0] + 2.2, first_angle)
    cell(x0 + 140, r2[0], 40, 9, "SHEET", f"{size}   1 / 1")
    cell(x0, r3[0], 48, 9, "DRAWN BY", meta.get("drawn_by", ""))
    cell(x0 + 48, r3[0], 30, 9, "DATE", meta.get("date", ""))
    cell(x0 + 78, r3[0], 18, 9, "REV", meta.get("rev", "—"))
    cell(x0 + 96, r3[0], 84, 9, "GENERAL TOLERANCES", meta.get("tolerance", "Not specified"), 2.8)
    cell(x0, r4[0], 48, 8, "CHECKED", "—", 2.8)
    cell(x0 + 48, r4[0], 48, 8, "APPROVED", "— (not approved)", 2.8)
    g.line("tbthin", x0 + 96, r4[0], x0 + 96, r4[0] + 8)
    g.text(x0 + 97.2, r4[0] + 3.2, 2.0, meta.get("source", ""), color="label", kind="title")
    g.text(x0 + 97.2, r4[0] + 6.4, 2.0, "Formwright Drawing Studio", color="label", kind="title")

    ly = y0
    if legend:  # one-row tag legend above the title block (A4: the notes column is too narrow for it)
        lg_h = 9.0
        ly = y0 - 2.0 - lg_h
        g.rect("tbthin", x0, ly, TB_W, lg_h)
        x = x0 + 2.0
        for txt, font, color, label in LEGEND:
            g.text(x, ly + 6.0, 3.2, txt, font=font, color=color, kind="legend",
                   tag=color if color in ("spec", "inferred") else None)
            x += text_width(txt, 3.2, font) + 1.5
            g.text(x, ly + 6.0, 2.1, label, kind="legend")
            x += text_width(label, 2.1) + 5.0
    top = ly
    # revision table (last 3 drawing revisions)
    rows_h = history[-3:]
    if rows_h:
        rt_h = 5.0 + 4.6 * len(rows_h)
        ry = ly - 2.0 - rt_h
        g.rect("tbthin", x0, ry, TB_W, rt_h)
        cols = [(0, 14, "REV"), (14, 104, "DESCRIPTION"), (118, 26, "DATE"), (144, 36, "BY")]
        for cx, _w, lab in cols:
            if cx:
                g.line("tbthin", x0 + cx, ry, x0 + cx, ry + rt_h)
            g.text(x0 + cx + 1.2, ry + 3.6, 2.0, lab, font="bold", color="label", kind="rev")
        g.line("tbthin", x0, ry + 5.0, x0 + TB_W, ry + 5.0)
        for i, h in enumerate(rows_h):
            yy = ry + 5.0 + 4.6 * i + 3.4
            vals = [str(h.get("rev", "")), str(h.get("change", "")), str(h.get("date", "")), str(h.get("by", ""))]
            for (cx, w, _lab), v in zip(cols, vals):
                while v and text_width(v, 2.3) > w - 2.4:
                    v = v[:-2] + "…"
                g.text(x0 + cx + 1.2, yy, 2.3, v, kind="rev")
        top = ry
    return g, [x0, top, x0 + TB_W, yb]


def _notes_block(W: float, H: float, notes: list[str], right: float,
                 legend: bool = True) -> tuple[Group, list[float] | None]:
    """Dimension-tag legend and numbered notes, bottom-left of the frame (left of the title block)."""
    g = Group()
    x0 = FRAME["left"] + 4.0
    width = right - x0 - 6.0
    # legend entries flow left to right, wrapping to the available width
    entries: list[list[tuple[float, tuple[str, str, str, str]]]] = [[]] if legend else []
    x = 0.0
    for e in LEGEND if legend else []:
        w = text_width(e[0], 3.2, e[1]) + 1.8 + text_width(e[3], 2.3) + 6.0
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
    leg_h = 5.0 + 4.6 * len(entries) + 2.0 if entries else 0.0
    h = leg_h + 5.5 + lh * len(lines) + 1.5
    yb = H - FRAME["bottom"] - 3.0
    y0 = yb - h
    if entries:
        g.text(x0, y0 + 3.6, 2.6, "DIMENSION TAGS", font="bold", kind="legend")
    for r, row in enumerate(entries):
        yy = y0 + 5.0 + 4.6 * (r + 1) - 0.6
        for ex, (txt, font, color, label) in row:
            g.text(x0 + ex, yy, 3.2, txt, font=font, color=color, kind="legend",
                   tag=color if color in ("spec", "inferred") else None)
            g.text(x0 + ex + text_width(txt, 3.2, font) + 1.8, yy, 2.3, label, kind="legend")
    ny = y0 + leg_h
    g.text(x0, ny + 3.6, 2.6, "NOTES", font="bold", kind="note")
    for i, (num, ln) in enumerate(lines):
        yy = ny + 5.5 + lh * (i + 1) - 0.8
        if num:
            g.text(x0, yy, 2.5, num, kind="note")
        g.text(x0 + 5.0, yy, 2.5, ln, kind="note")
    return g, [x0 - 1.0, y0, x0 + width, yb]


def compose(an: dict[str, Any], dims: list[dict[str, Any]], callouts: list[dict[str, Any]], notes: list[str],
            opts: dict[str, Any], meta: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose the largest standard scale at which everything fits, and build the sheet."""
    size = opts.get("sheet", "A3")
    W, H = SHEETS[size]
    best = None
    for sc in SCALES:
        for iso_step in (0, 1, 2):
            sheet = _try(an, dims, callouts, notes, opts, meta, history, sc, iso_step, W, H, size)
            if sheet is not None:
                best = sheet
                break
        if best is not None:
            break
    if best is None:  # nothing fits: smallest scale, report through CHK-12
        best = _try(an, dims, callouts, notes, opts, meta, history, SCALES[-1], 2, W, H, size, force=True)
    assert best is not None
    return best


def _try(an: dict[str, Any], dims: list[dict[str, Any]], callouts: list[dict[str, Any]], notes: list[str],
         opts: dict[str, Any], meta: dict[str, Any], history: list[dict[str, Any]], sc: tuple[int, int],
         iso_step: int, W: float, H: float, size: str, force: bool = False) -> dict[str, Any] | None:
    s = sc[0] / sc[1]
    proj = opts.get("projection", "first")
    views_on = [v for v in ("front", "top", "right") if v in an["views"]]
    dim_size = 3.5 if size == "A3" else 3.0
    vls: dict[str, ViewLayout] = {}
    sec_opt = an.get("section")
    sec_ref = None
    if sec_opt:
        prefs = {"y": ["top", "right"], "x": ["top", "front"], "z": ["front", "right"]}[sec_opt["axis"]]
        sec_ref = next((v for v in prefs if v in views_on), None)
    for v in views_on:
        vl = ViewLayout(v, an["views"][v], s, hidden=opts.get("hidden", True))
        vls[v] = vl
    # centre lines for holes and cylinder axes
    for v, vl in vls.items():
        cos = [c for c in callouts if c["view"] == v]
        axes = []
        for h in an["census"]["holes"] + an["census"]["outer"]:
            ax = h["axis"]
            from aicad.drawing.dims import COORD

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
    if sec_opt and sec_ref:
        cm = {"top": {"x": "u", "y": "v"}, "front": {"x": "u", "z": "v"}, "right": {"y": "u", "z": "v"}}[sec_ref]
        o = cm[sec_opt["axis"]]
        # arrows show the direction of sight of the section view
        look = {"y": (0, 1, 0), "x": (-1, 0, 0), "z": (0, 0, -1)}[sec_opt["axis"]]
        axis_vec = {"u": None, "v": None}
        for a, c in cm.items():
            axis_vec[c] = a
        ai = {"x": 0, "y": 1, "z": 2}
        du = look[ai[axis_vec["u"]]]
        dv = look[ai[axis_vec["v"]]]
        vls[sec_ref].cutting_plane("v" if o == "u" else "h", sec_opt["plane"], (int(du), int(-dv)))
    for v, vl in vls.items():
        sides = SIDES[proj][v]
        vl.place_dims([d for d in dims if d["view"] == v], sides, dim_size)
        vl.place_callouts([c for c in callouts if c["view"] == v], sides["h"], dim_size)
    extras: list[ViewLayout] = []
    iso_scale = s
    if "iso" in an["views"]:
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
    if sec_opt:
        sv = ViewLayout("section", sec_opt, s, hidden=False, label="SECTION A-A")
        sv.hatch(sec_opt["loops"], 2.5 if size == "A3" else 2.0)
        sv.caption(3.5)
        extras.insert(0, sv)

    info, info_box = _info_blocks(W, H, meta, scale_label(sc), proj == "first", history, size, legend=size != "A3")
    notes_g, notes_box = _notes_block(W, H, notes, info_box[0], legend=size == "A3")
    frame = [FRAME["left"], FRAME["top"], W - FRAME["right"], H - FRAME["bottom"]]
    blocked = [info_box] + ([notes_box] if notes_box else [])

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
    pos: dict[str, tuple[float, float]] = {}
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
    if not force and not all(ok(b, blocked) for b in occupied):
        return None
    grid_box = [min(b[0] for b in occupied), min(b[1] for b in occupied),
                max(b[2] for b in occupied), max(b[3] for b in occupied)] if occupied else [frame[0] + 6] * 2 + [frame[0] + 6] * 2
    fr, fc = cells["_free"]
    for ex in extras:
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
        cands.append((frame[2] - 4 - bw, frame[1] + 4))
        chosen = None
        for cx, cy in cands:
            p = (cx - b[0], cy - b[1])
            box = [cx, cy, cx + bw, cy + bh]
            if ok(box, occupied + blocked):
                chosen = p
                break
        if chosen is None:
            if not force:
                return None
            chosen = (right - b[0], grid_box[1] - b[1])
        pos[id(ex)] = chosen  # type: ignore[index]
        occupied.append(abs_box(ex, chosen))

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
        p = pos[vl.name] if vl.name in pos else pos[id(vl)]  # type: ignore[index]
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
            "projection": proj, "frame": frame, "prims": prims, "views": view_info, "blocked": blocked}
