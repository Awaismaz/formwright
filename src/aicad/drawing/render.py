"""Renderers: one sheet (layout.py primitives) to SVG, PDF and DXF. All three draw the same primitives.

- SVG: written directly (deterministic text, mm user units).
- PDF: reportlab (BSD licence) with ``invariant=1`` so the same sheet gives the same bytes.
- DXF: build123d ``ExportDXF`` (ezdxf, MIT) for the linework, at true model size (paper / drawing scale), with
  layers VISIBLE / HIDDEN / CENTER / DIM / HATCH / SHEET; texts are added to the same ezdxf document.
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from aicad.drawing.layout import LAYERS, TEXT_COLORS

# Layer classes are prefixed (drw-*) so an inline SVG cannot clash with page CSS (e.g. a "hidden" utility).
FILLS = {"dim": "#222222", "bannerfill": "#fdecec", "visible": "#111111", "cutthick": "#111111"}
SVG_FONT = "Helvetica, Arial, 'Liberation Sans', sans-serif"


def _n(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _arc_pt(cx: float, cy: float, r: float, a: float) -> tuple[float, float]:
    return cx + r * math.cos(math.radians(a)), cy - r * math.sin(math.radians(a))


# ----------------------------------------------------------------------------- SVG
def to_svg(sheet: dict[str, Any], title: str = "") -> str:
    W, H = sheet["w"], sheet["h"]
    out = [(f'<svg xmlns="http://www.w3.org/2000/svg" width="{_n(W)}mm" height="{_n(H)}mm" '
           f'viewBox="0 0 {_n(W)} {_n(H)}" font-family="{SVG_FONT}" data-scale="{sheet["scale_txt"]}">'),
           f"<title>{escape(title)}</title>", "<style>"]
    for name, (w, dash, col) in LAYERS.items():
        d = f"stroke-dasharray:{' '.join(_n(x) for x in dash)};" if dash else ""
        cap = "round" if name in ("visible", "frame") else "butt"
        out.append(f".drw-{name}{{fill:none;stroke:{col};stroke-width:{_n(w)};{d}stroke-linecap:{cap};"
                   f"stroke-linejoin:round}}")
    out.append("</style>")
    out.append(f'<rect x="0" y="0" width="{_n(W)}" height="{_n(H)}" fill="#ffffff"/>')
    order = ["bannerfill", "hatch", "hidden", "center", "visible", "cut", "cutthick", "dim", "frame", "tb",
             "tbthin", "banner", "text"]
    prims = sorted(sheet["prims"], key=lambda p: order.index(p["l"]) if p["l"] in order else 99)
    for p in prims:
        t, layer = p["t"], p["l"]
        if t == "line":
            a = p["p"]
            out.append(f'<line class="drw-{layer}" x1="{_n(a[0])}" y1="{_n(a[1])}" x2="{_n(a[2])}" y2="{_n(a[3])}"/>')
        elif t == "poly":
            pts = " ".join(f"{_n(x)},{_n(y)}" for x, y in p["p"])
            tag = "polygon" if p.get("closed") else "polyline"
            out.append(f'<{tag} class="drw-{layer}" points="{pts}"/>')
        elif t == "circle":
            cx, cy, r = p["p"]
            out.append(f'<circle class="drw-{layer}" cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r)}"/>')
        elif t == "arc":
            cx, cy, r, a0, a1 = p["p"]
            x0, y0 = _arc_pt(cx, cy, r, a0)
            x1, y1 = _arc_pt(cx, cy, r, a1)
            large = 1 if (a1 - a0) > 180 else 0
            out.append(f'<path class="drw-{layer}" d="M{_n(x0)} {_n(y0)} A{_n(r)} {_n(r)} 0 {large} 0 {_n(x1)} {_n(y1)}"/>')
        elif t == "fill":
            pts = " ".join(f"{_n(x)},{_n(y)}" for x, y in p["p"])
            out.append(f'<polygon points="{pts}" fill="{FILLS.get(layer, "#222222")}" stroke="none"/>')
        elif t == "text":
            col = TEXT_COLORS.get(p.get("color") or "normal", "#111111")
            attrs = [f'x="{_n(p["x"])}"', f'y="{_n(p["y"])}"', f'font-size="{_n(p["s"])}"', f'fill="{col}"']
            if p["anchor"] != "start":
                attrs.append(f'text-anchor="{p["anchor"]}"')
            if p["font"] == "bold":
                attrs.append('font-weight="bold"')
            elif p["font"] == "italic":
                attrs.append('font-style="italic"')
            if p["rot"]:
                attrs.append(f'transform="rotate(-90 {_n(p["x"])} {_n(p["y"])})"')
            if p.get("kind") in ("dim", "callout"):
                attrs.append(f'data-kind="{p["kind"]}" data-tag="{p.get("tag") or ""}"')
                if p.get("param"):
                    attrs.append(f'data-param="{escape(p["param"])}"')
            tip = ""
            if p.get("kind") in ("dim", "callout"):
                what = f"spec: parameter {p['param']}" if p.get("tag") == "spec" else "inferred: measured from geometry"
                tip = f"<title>{escape(p['txt'])} ({escape(what)})</title>"
            out.append(f"<text {' '.join(attrs)}>{tip}{escape(p['txt'])}</text>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------------------- PDF
def to_pdf(sheet: dict[str, Any], path: Path, title: str = "") -> None:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    from aicad.drawing.layout import FONTS

    W, H = sheet["w"], sheet["h"]
    c = canvas.Canvas(str(path), pagesize=(W * mm, H * mm), invariant=1, pageCompression=1)
    c.setTitle(title)
    c.setCreator("Formwright Drawing Studio")
    c.setAuthor("")

    def X(x: float) -> float:
        return x * mm

    def Y(y: float) -> float:
        return (H - y) * mm

    def stroke(layer: str) -> None:
        w, dash, col = LAYERS.get(layer, LAYERS["dim"])
        c.setLineWidth(w * mm)
        c.setStrokeColor(HexColor(col))
        c.setDash([d * mm for d in dash] if dash else [])
        c.setLineCap(1 if layer in ("visible", "frame") else 0)
        c.setLineJoin(1)

    order = ["bannerfill", "hatch", "hidden", "center", "visible", "cut", "cutthick", "dim", "frame", "tb",
             "tbthin", "banner", "text"]
    prims = sorted(sheet["prims"], key=lambda p: order.index(p["l"]) if p["l"] in order else 99)
    for p in prims:
        t, layer = p["t"], p["l"]
        if t == "line":
            stroke(layer)
            a = p["p"]
            c.line(X(a[0]), Y(a[1]), X(a[2]), Y(a[3]))
        elif t == "poly":
            stroke(layer)
            pa = c.beginPath()
            pts = p["p"]
            pa.moveTo(X(pts[0][0]), Y(pts[0][1]))
            for x, y in pts[1:]:
                pa.lineTo(X(x), Y(y))
            if p.get("closed"):
                pa.close()
            c.drawPath(pa, stroke=1, fill=0)
        elif t == "circle":
            stroke(layer)
            cx, cy, r = p["p"]
            c.circle(X(cx), Y(cy), r * mm, stroke=1, fill=0)
        elif t == "arc":
            stroke(layer)
            cx, cy, r, a0, a1 = p["p"]
            pa = c.beginPath()
            pa.arc(X(cx - r), Y(cy + r), X(cx + r), Y(cy - r), startAng=a0, extent=a1 - a0)
            c.drawPath(pa, stroke=1, fill=0)
        elif t == "fill":
            c.setFillColor(HexColor(FILLS.get(layer, "#222222")))
            pa = c.beginPath()
            pts = p["p"]
            pa.moveTo(X(pts[0][0]), Y(pts[0][1]))
            for x, y in pts[1:]:
                pa.lineTo(X(x), Y(y))
            pa.close()
            c.drawPath(pa, stroke=0, fill=1)
        elif t == "text":
            c.setFillColor(HexColor(TEXT_COLORS.get(p.get("color") or "normal", "#111111")))
            c.setFont(FONTS[p["font"]], p["s"] * mm)
            c.saveState()
            c.translate(X(p["x"]), Y(p["y"]))
            if p["rot"]:
                c.rotate(90)
            draw = {"start": c.drawString, "middle": c.drawCentredString, "end": c.drawRightString}[p["anchor"]]
            draw(0, 0, p["txt"])
            c.restoreState()
    c.showPage()
    c.save()


# ----------------------------------------------------------------------------- DXF
DXF_LAYERS = {"visible": "VISIBLE", "hidden": "HIDDEN", "center": "CENTER", "cut": "CENTER", "hatch": "HATCH",
              "dim": "DIM", "cutthick": "VISIBLE"}


def to_dxf(sheet: dict[str, Any], path: Path) -> None:
    """True-size DXF: paper millimetres divided by the drawing scale, y up."""
    from build123d import Edge, ExportDXF, LineType, Plane, Unit, Vector
    from ezdxf.enums import TextEntityAlignment

    num, den = sheet["scale"]
    k = den / num  # paper mm -> model mm
    H = sheet["h"]
    exp = ExportDXF(unit=Unit.MM)
    exp.add_layer("VISIBLE", line_weight=0.5)
    exp.add_layer("HIDDEN", line_weight=0.25, line_type=LineType.HIDDEN)
    exp.add_layer("CENTER", line_weight=0.18, line_type=LineType.CENTER)
    exp.add_layer("HATCH", line_weight=0.18)
    exp.add_layer("DIM", line_weight=0.18)
    exp.add_layer("SHEET", line_weight=0.35)
    exp.add_layer("TEXT", line_weight=0.18)

    def P(x: float, y: float) -> Vector:
        return Vector(x * k, (H - y) * k, 0)

    buckets: dict[str, list[Any]] = {}
    for p in sheet["prims"]:
        layer = DXF_LAYERS.get(p["l"], "SHEET")
        t = p["t"]
        edges: list[Any] = []
        if t == "line":
            a = p["p"]
            if math.hypot(a[2] - a[0], a[3] - a[1]) > 1e-6:
                edges.append(Edge.make_line(P(a[0], a[1]), P(a[2], a[3])))
        elif t in ("poly", "fill"):
            pts = p["p"] + ([p["p"][0]] if (p.get("closed") or t == "fill") else [])
            for a, b in itertools.pairwise(pts):
                if math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-6:
                    edges.append(Edge.make_line(P(*a), P(*b)))
        elif t == "circle":
            cx, cy, r = p["p"]
            edges.append(Edge.make_circle(r * k, Plane(origin=P(cx, cy))))
        elif t == "arc":
            cx, cy, r, a0, a1 = p["p"]
            edges.append(Edge.make_circle(r * k, Plane(origin=P(cx, cy)), start_angle=a0, end_angle=a1))
        buckets.setdefault(layer, []).extend(edges)
    for layer in sorted(buckets):
        if buckets[layer]:
            exp.add_shape(buckets[layer], layer=layer)
    msp = exp._modelspace  # build123d keeps the ezdxf modelspace here; texts are not shapes
    align = {"start": TextEntityAlignment.LEFT, "middle": TextEntityAlignment.CENTER,
             "end": TextEntityAlignment.RIGHT}
    for p in sheet["prims"]:
        if p["t"] != "text":
            continue
        e = msp.add_text(p["txt"], dxfattribs={"height": p["s"] * 0.72 * k, "layer": "TEXT",
                                               "rotation": 90 if p["rot"] else 0})
        q = P(p["x"], p["y"])
        e.set_placement((q.X, q.Y), align=align[p["anchor"]])
    exp.write(str(path))

