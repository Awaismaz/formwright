"""Renderers: one sheet (layout.py primitives) to SVG, PDF and DXF. All three draw the same primitives.

- SVG: written directly (deterministic text, mm user units).
- PDF: reportlab (BSD licence) with ``invariant=1`` so the same sheet gives the same bytes.
- DXF (ezdxf, MIT): the view geometry in model space at true size (paper / drawing scale), the sheet (frame, title
  block, dimensions, notes) in a paper-space layout "Sheet" with one viewport at the drawing scale. Layers
  VISIBLE / HIDDEN / CENTER / HATCH / DIM / TEXT / SHEET / CUT with colours by type; the diameter sign is written as
  ``%%c`` so every CAD font shows it; view outlines that are curves (ellipses in the isometric view) are single
  polylines, circles and arcs are true CIRCLE / ARC entities.

``issue_sheet`` turns the review copy (spec / inferred tag colours, italics and the tag legend) into the issue copy
(monochrome, upright, no legend) without changing any position, so both copies share one layout.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from aicad.drawing.layout import LAYERS, TEXT_COLORS

# Layer classes are prefixed (drw-*) so an inline SVG cannot clash with page CSS (e.g. a "hidden" utility).
FILLS = {"dim": "#222222", "dim_n": "#222222", "bannerfill": "#fdecec", "visible": "#111111", "cutthick": "#111111",
         "gdt": "#111111"}
ORDER = ["bannerfill", "construction", "hatch", "hatch_n", "hidden", "center", "center_n", "thread", "visible", "cut",
         "cutthick", "detail", "dim", "dim_n", "gdt", "frame", "tb", "tbthin", "banner", "text"]
DEPTH = "▽"  # depth symbol in hole / thread callouts: drawn as a triangle in PDF and DXF (no font has it there)


def depth_pieces(txt: str, size: float, font: str = "regular") -> list[tuple[str, float]]:
    """A callout text split around depth symbols: [(text, x offset from the text start)], with "" marking a
    symbol at that offset. Widths use the layout's metrics, so the pieces land where the layout measured them."""
    from aicad.drawing.layout import text_width

    out: list[tuple[str, float]] = []
    x = 0.0
    for i, part in enumerate(txt.split(DEPTH)):
        if i:
            out.append(("", x))
            x += text_width(DEPTH, size, font)
        if part:
            out.append((part, x))
            x += text_width(part, size, font)
    return out


def depth_triangle(x: float, y: float, size: float) -> list[tuple[float, float]]:
    """The ▽ symbol at text start x, baseline y (paper mm, y down): a downward triangle of cap height."""
    from aicad.drawing.layout import text_width

    w = text_width(DEPTH, size)
    top = y - 0.70 * size
    return [(x + 0.1 * w, top), (x + 0.9 * w, top), (x + 0.5 * w, y)]
SVG_FONT = "Helvetica, Arial, 'Liberation Sans', sans-serif"


def _n(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _arc_pt(cx: float, cy: float, r: float, a: float) -> tuple[float, float]:
    return cx + r * math.cos(math.radians(a)), cy - r * math.sin(math.radians(a))


# ----------------------------------------------------------------------------- issue copy
def issue_sheet(sheet: dict[str, Any]) -> dict[str, Any]:
    """Monochrome issue copy: no tag legend, no tag colours or italics (MAKE-09). Same layout as the review copy."""
    prims = []
    for p in sheet["prims"]:
        if p["t"] == "text":
            if p.get("kind") == "legend":
                continue
            if p.get("kind") in ("dim", "callout"):
                p = {**p, "color": "normal", "font": "regular" if p["font"] == "italic" else p["font"]}
        prims.append(p)
    return {**sheet, "prims": prims, "copy": "issue"}


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
    order = ORDER
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
                attrs.append(f'transform="rotate({_n(-p["rot"])} {_n(p["x"])} {_n(p["y"])})"')
            tip = ""
            if p.get("kind") in ("dim", "callout") and sheet.get("copy") != "issue":
                attrs.append(f'data-kind="{p["kind"]}" data-tag="{p.get("tag") or ""}"')
                if p.get("ref"):
                    attrs.append(f'data-ref="{escape(p["ref"])}"')
                what = "spec: equals a model parameter" if p.get("tag") == "spec" else "inferred: measured from the model"
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

    order = ORDER
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
        elif t == "text" and DEPTH in p["txt"] and not p["rot"]:
            col = HexColor(TEXT_COLORS.get(p.get("color") or "normal", "#111111"))
            c.setFillColor(col)
            c.setFont(FONTS[p["font"]], p["s"] * mm)
            x0 = p["box"][0]
            for piece, off in depth_pieces(p["txt"], p["s"], p["font"]):
                if piece:
                    c.drawString(X(x0 + off), Y(p["y"]), piece)
                else:
                    tri = depth_triangle(x0 + off, p["y"], p["s"])
                    c.setStrokeColor(col)
                    c.setLineWidth(0.09 * p["s"] * mm)
                    c.setDash([])
                    pa = c.beginPath()
                    pa.moveTo(X(tri[0][0]), Y(tri[0][1]))
                    for qx, qy in tri[1:]:
                        pa.lineTo(X(qx), Y(qy))
                    pa.close()
                    c.drawPath(pa, stroke=1, fill=0)
        elif t == "text":
            c.setFillColor(HexColor(TEXT_COLORS.get(p.get("color") or "normal", "#111111")))
            c.setFont(FONTS[p["font"]], p["s"] * mm)
            c.saveState()
            c.translate(X(p["x"]), Y(p["y"]))
            if p["rot"]:
                c.rotate(p["rot"])
            draw = {"start": c.drawString, "middle": c.drawCentredString, "end": c.drawRightString}[p["anchor"]]
            draw(0, 0, p["txt"])
            c.restoreState()
    c.showPage()
    c.save()


# ----------------------------------------------------------------------------- DXF
GEOMETRY_LAYERS = {"visible": "VISIBLE", "hidden": "HIDDEN", "center": "CENTER", "hatch": "HATCH"}
PAPER_LAYERS = {"dim": "DIM", "cut": "CUT", "cutthick": "CUT", "text": "TEXT", "thread": "THREAD", "detail": "DETAIL",
                "gdt": "GDT"}
#: name: (ACI colour, linetype, lineweight in 1/100 mm)
DXF_LAYER_STYLE = {"VISIBLE": (7, "Continuous", 50), "HIDDEN": (3, "HIDDEN", 25), "CENTER": (1, "CENTER", 18),
                   "HATCH": (8, "Continuous", 18), "DIM": (4, "Continuous", 18), "TEXT": (7, "Continuous", 18),
                   "SHEET": (7, "Continuous", 35), "CUT": (1, "CENTER", 25), "VIEWPORT": (8, "Continuous", 13),
                   "THREAD": (3, "Continuous", 25), "DETAIL": (6, "Continuous", 25), "GDT": (7, "Continuous", 25)}


def dxf_text(txt: str) -> str:
    """CAD fonts (txt.shx and friends) lack Ø: use the %%c control code, shown as a diameter sign everywhere."""
    return txt.replace("Ø", "%%c").replace("±", "%%p").replace("°", "%%d")


def to_dxf(sheet: dict[str, Any], path: Path) -> None:
    """Model space: view geometry at true size (paper mm × scale denominator). Paper space layout "Sheet": the
    sheet at 1:1 paper millimetres with one viewport onto model space at the drawing scale."""
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    num, den = sheet["scale"]
    k = den / num  # paper mm -> model mm
    W, H = sheet["w"], sheet["h"]
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    for name, (color, lt, lw) in DXF_LAYER_STYLE.items():
        doc.layers.add(name, color=color, linetype=lt, lineweight=lw)
    doc.layers.get("VIEWPORT").dxf.plot = 0
    if "FW" not in doc.styles:
        doc.styles.new("FW", dxfattribs={"font": "arial.ttf"})
    msp = doc.modelspace()
    doc.layouts.rename("Layout1", "Sheet")
    psp = doc.layouts.get("Sheet")
    psp.page_setup(size=(W, H), margins=(0, 0, 0, 0), units="mm")

    def M(x: float, y: float) -> tuple[float, float]:
        return (x * k, (H - y) * k)

    def P(x: float, y: float) -> tuple[float, float]:
        return (x, H - y)

    for pr in sheet["prims"]:
        t, layer = pr["t"], pr["l"]
        if t == "text":
            continue
        # a detail view has its own scale: its geometry goes to paper space, as drawn (DRW-011)
        geom = pr.get("view") is not None and layer in GEOMETRY_LAYERS and not str(pr["view"]).startswith("detail-")
        space, T, f = (msp, M, k) if geom else (psp, P, 1.0)
        lname = GEOMETRY_LAYERS[layer] if geom else PAPER_LAYERS.get(layer) or GEOMETRY_LAYERS.get(layer, "SHEET")
        attrs = {"layer": lname}
        if t == "line":
            a = pr["p"]
            if math.hypot(a[2] - a[0], a[3] - a[1]) > 1e-6:
                space.add_line(T(a[0], a[1]), T(a[2], a[3]), dxfattribs=attrs)
        elif t == "poly":
            pts = [T(x, y) for x, y in pr["p"]]
            space.add_lwpolyline(pts, close=bool(pr.get("closed")), dxfattribs=attrs)
        elif t == "fill":
            pts = [T(x, y) for x, y in pr["p"]]
            if len(pts) == 3:
                space.add_solid(pts, dxfattribs=attrs)
            else:
                space.add_lwpolyline(pts, close=True, dxfattribs=attrs)
        elif t == "circle":
            cx, cy, r = pr["p"]
            space.add_circle(T(cx, cy), r * f, dxfattribs=attrs)
        elif t == "arc":
            cx, cy, r, a0, a1 = pr["p"]
            space.add_arc(T(cx, cy), r * f, a0, a1, dxfattribs=attrs)
    align = {"start": TextEntityAlignment.LEFT, "middle": TextEntityAlignment.CENTER,
             "end": TextEntityAlignment.RIGHT}
    for pr in sheet["prims"]:
        if pr["t"] != "text":
            continue
        if DEPTH in pr["txt"] and not pr["rot"]:  # text pieces and a drawn depth symbol, left-aligned at the box
            x0 = pr["box"][0]
            for piece, off in depth_pieces(pr["txt"], pr["s"], pr["font"]):
                if piece:
                    e = psp.add_text(dxf_text(piece), dxfattribs={"height": pr["s"] * 0.72, "layer": "TEXT",
                                                                  "style": "FW"})
                    e.set_placement(P(x0 + off, pr["y"]), align=TextEntityAlignment.LEFT)
                else:
                    psp.add_lwpolyline([P(qx, qy) for qx, qy in depth_triangle(x0 + off, pr["y"], pr["s"])], close=True,
                                       dxfattribs={"layer": "TEXT"})
            continue
        e = psp.add_text(dxf_text(pr["txt"]), dxfattribs={"height": pr["s"] * 0.72, "layer": "TEXT", "style": "FW",
                                                         "rotation": 90 if pr["rot"] else 0})
        e.set_placement(P(pr["x"], pr["y"]), align=align[pr["anchor"]])
    vp = psp.add_viewport(center=(W / 2, H / 2), size=(W, H), view_center_point=(W / 2 * k, H / 2 * k),
                          view_height=H * k, dxfattribs={"layer": "VIEWPORT"})
    vp.dxf.status = 2
    doc.saveas(str(path))
