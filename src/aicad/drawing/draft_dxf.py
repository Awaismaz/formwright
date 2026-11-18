"""DXF export of a 2D drafting document (DRW-017), written the way a CAD drafter would set it up:

- Model space at true size in drawing units ($INSUNITS mm or inch): the geometry on ISO 128 layers, real DIMENSION
  entities (linear / aligned / radius / diameter / angular / ordinate) that measure their own definition points, real
  HATCH entities (ANSI31) on their boundaries, and the annotations (notes, leaders, balloons, symbols, frames).
- Paper space layout "Sheet" at 1:1 paper millimetres: frame, title block and notes, with one viewport onto model space
  at the drawing scale.
- Linetypes ACAD_ISO02W100 (dashed) and ACAD_ISO04W100 (long-dash dotted) with their ISO 128 patterns embedded, scaled
  for 0.25 mm narrow lines; lineweights per layer; the CONSTRUCTION layer does not plot.

ezdxf (MIT). DXF bytes are not deterministic (handles, header times); the values are.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from aicad.drawing.draft import (
    LAYER_STYLE,
    Geo,
    angle_sector,
    chain_loop,
    content_prims,
    frame_prims,
    text_size,
)
from aicad.drawing.render import dxf_text

#: DXF layer: (ACI colour, linetype, lineweight 1/100 mm, plot)
LAYERS = {"VISIBLE": (7, "Continuous", 50, True), "HIDDEN": (3, "ACAD_ISO02W100", 25, True),
          "CENTER": (1, "ACAD_ISO04W100", 25, True), "DIMENSION": (4, "Continuous", 25, True),
          "CONSTRUCTION": (8, "Continuous", 13, False), "HATCH": (8, "Continuous", 25, True),
          "TEXT": (7, "Continuous", 25, True), "SHEET": (7, "Continuous", 35, True),
          "VIEWPORT": (8, "Continuous", 13, False)}
DOC_LAYER = {"visible": "VISIBLE", "hidden": "HIDDEN", "center": "CENTER", "dimension": "DIMENSION",
             "construction": "CONSTRUCTION"}
PRIM_LAYER = {"visible": "VISIBLE", "hidden": "HIDDEN", "center": "CENTER", "center_n": "CENTER",
              "dim_n": "DIMENSION", "hatch_n": "HATCH", "construction": "CONSTRUCTION", "text": "TEXT"}
NARROW = 0.25  # ISO 128 narrow line width the W100 patterns are scaled for


def _dimstyle(doc: Any, size: float, inv_k: float, decimals: int) -> None:
    ds = doc.dimstyles.new("FW-ISO")
    for k, v in {"dimtxt": size, "dimasz": 2.6, "dimexo": 1.0, "dimexe": 2.0, "dimgap": 1.0, "dimtad": 1, "dimtih": 0,
                 "dimtoh": 0, "dimdec": decimals, "dimzin": 8, "dimazin": 2, "dimadec": 1, "dimdsep": ord("."),
                 "dimscale": inv_k, "dimlunit": 2, "dimtxsty": "FW", "dimclrd": 256, "dimclre": 256, "dimclrt": 256,
                 "dimtfac": 0.7, "dimtmove": 2, "dimlwd": 25, "dimlwe": 25}.items():
        ds.set_dxf_attrib(k, v)


def _tolerance(ov: Any, d: dict[str, Any], decimals: int) -> str:
    """Tolerance on a DIMENSION override; returns the text template ('<>' is the measured value)."""
    t = d.get("tol") or {}
    kind = t.get("kind")
    if kind == "sym":
        ov.set_tolerance(t["up"], t["up"], hfactor=1.0, dec=max(decimals, 3), trailing_zeros=False)
    elif kind == "dev":
        ov.set_tolerance(t["up"], -t["lo"], hfactor=0.7, dec=max(decimals, 3), trailing_zeros=False)
    elif kind == "limits":
        ov.set_limits(t["up"], -t["lo"], hfactor=0.7, dec=max(decimals, 3), trailing_zeros=False)
    text = "<>"
    if kind == "fit":
        text = f"<> {t['fit']}"
    if d.get("prefix"):
        text = f"{d['prefix']} {text}"
    if d.get("suffix"):
        text = f"{text} {d['suffix']}"
    return dxf_text(text)


def to_dxf(doc_: dict[str, Any], path: Path) -> None:
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    geo = Geo(doc_)
    k = geo.k
    size = text_size(doc_)
    fp, info = frame_prims(doc_)
    W, H = info["w"], info["h"]
    doc = ezdxf.new("R2010", setup=True)
    inch = doc_["sheet"]["units"] == "in"
    doc.units = ezdxf.units.IN if inch else ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 0 if inch else 1
    doc.header["$LTSCALE"] = NARROW / k
    doc.header["$PSLTSCALE"] = 0
    doc.header["$LWDISPLAY"] = 1
    doc.linetypes.add("ACAD_ISO02W100", pattern=[15.0, 12.0, -3.0], description="ISO dash __ __ __")
    doc.linetypes.add("ACAD_ISO04W100", pattern=[30.0, 24.0, -3.0, 0.0, -3.0], description="ISO long-dash dot ____ . ____")
    for name, (color, lt, lw, plot) in LAYERS.items():
        lay = doc.layers.add(name, color=color, linetype=lt, lineweight=lw)
        lay.dxf.plot = 1 if plot else 0
    if "FW" not in doc.styles:
        doc.styles.new("FW", dxfattribs={"font": "arial.ttf"})
    _dimstyle(doc, size, 1.0 / k, geo.decimals)
    msp = doc.modelspace()

    # geometry
    for e in doc_["geom"]["entities"]:
        at = {"layer": DOC_LAYER[e["layer"]]}
        if e["type"] == "line":
            msp.add_line(geo.pts[e["p1"]], geo.pts[e["p2"]], dxfattribs=at)
        elif e["type"] == "circle":
            msp.add_circle(geo.pts[e["c"]], e["r"], dxfattribs=at)
        else:
            a0, sw = geo.arc_angles(e)
            c, r, _ = geo.circle(e["id"])  # type: ignore[misc]
            msp.add_arc(c, r, a0, a0 + sw, dxfattribs=at)

    # dimensions: true DIMENSION entities measuring their definition points
    dat = {"layer": "DIMENSION"}
    for d in doc_["dims"]:
        t = d["type"]
        ov = None
        if t == "linear":
            if d["a"] not in geo.pts or d["b"] not in geo.pts:
                continue
            a, b = geo.pts[d["a"]], geo.pts[d["b"]]
            ang = {"h": 0.0, "v": 90.0}.get(d["orient"], math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])))
            ov = msp.add_linear_dim(base=d["pos"], p1=a, p2=b, angle=ang, dimstyle="FW-ISO", dxfattribs=dat)
        elif t in ("radius", "diameter"):
            cc = geo.circle(d["ent"])
            if cc is None:
                continue
            c, r, _ = cc
            ang = math.degrees(math.atan2(d["pos"][1] - c[1], d["pos"][0] - c[0]))
            fn = msp.add_radius_dim if t == "radius" else msp.add_diameter_dim
            ov = fn(c, radius=r, angle=ang, location=d["pos"], dimstyle="FW-ISO", override={"dimtoh": 1},
                    dxfattribs=dat)
        elif t == "angle":
            s = angle_sector(geo, d)
            l1, l2 = geo.line(d["l1"]), geo.line(d["l2"])
            if s is None or l1 is None or l2 is None:
                continue
            x = s["x"]
            r = max(s["r"], 1e-6)
            p0 = (x[0] + r * math.cos(math.radians(s["a0"])), x[1] + r * math.sin(math.radians(s["a0"])))
            p1 = (x[0] + r * math.cos(math.radians(s["a0"] + s["sweep"])), x[1] + r * math.sin(math.radians(s["a0"] + s["sweep"])))
            ov = msp.add_angular_dim_2l(base=d["pos"], line1=(x, p0), line2=(x, p1), dimstyle="FW-ISO",
                                        override={"dimadec": 1}, dxfattribs=dat)
        elif t == "ordinate":
            if d["origin"] not in geo.pts or d["pt"] not in geo.pts:
                continue
            f, o = geo.pts[d["pt"]], geo.pts[d["origin"]]
            off = (d["pos"][0] - f[0], d["pos"][1] - f[1])
            fn = msp.add_ordinate_x_dim if d["axis"] == "x" else msp.add_ordinate_y_dim
            ov = fn(feature_location=f, offset=off, origin=o, dimstyle="FW-ISO", dxfattribs=dat)
        if ov is None:
            continue
        ov.dimension.dxf.text = _tolerance(ov, d, geo.decimals)
        ov.render()

    # hatches: real HATCH entities on their boundary loops
    for a in doc_["annos"]:
        if a["type"] != "hatch":
            continue
        loops = [chain_loop(geo, lp) for lp in a["loops"]]
        loops = [lp for lp in loops if lp]
        if not loops:
            continue
        h = msp.add_hatch(color=256, dxfattribs={"layer": "HATCH"})
        h.set_pattern_fill("ANSI31", scale=a["spacing"] / k / 3.175)
        for lp in loops:
            h.paths.add_polyline_path(lp, is_closed=True)

    # annotations (notes, leaders, balloons, symbols, centre marks): their sheet primitives at drawing size
    align = {"start": TextEntityAlignment.LEFT, "middle": TextEntityAlignment.CENTER, "end": TextEntityAlignment.RIGHT}
    for pr in content_prims(doc_):
        if not pr.get("anno") or pr["l"] == "hatch_n":
            continue
        _emit(msp, pr, geo.M, 1.0 / k, PRIM_LAYER.get(pr["l"], "DIMENSION"), align)

    # paper space: the sheet at 1:1 with one viewport at the drawing scale
    doc.layouts.rename("Layout1", "Sheet")
    psp = doc.layouts.get("Sheet")
    psp.page_setup(size=(W, H), margins=(0, 0, 0, 0), units="mm")

    def P(q: tuple[float, float]) -> tuple[float, float]:
        return (q[0], H - q[1])

    for pr in fp:
        lay = "CENTER" if pr["l"] in ("center", "center_n") else ("TEXT" if pr["t"] == "text" else "SHEET")
        _emit(psp, pr, P, 1.0, lay, align)
    cx, cy = geo.M((W / 2, H / 2))
    vp = psp.add_viewport(center=(W / 2, H / 2), size=(W, H), view_center_point=(cx, cy), view_height=H / k,
                          dxfattribs={"layer": "VIEWPORT"})
    vp.dxf.status = 2
    doc.saveas(str(path))


def _emit(space: Any, pr: dict[str, Any], T: Any, f: float, layer: str, align: dict[str, Any]) -> None:
    """One sheet primitive into a DXF space; ``T`` maps paper mm to the space, ``f`` scales lengths."""
    at = {"layer": layer}
    t = pr["t"]
    if t == "line":
        a = pr["p"]
        if math.hypot(a[2] - a[0], a[3] - a[1]) > 1e-6:
            space.add_line(T((a[0], a[1])), T((a[2], a[3])), dxfattribs=at)
    elif t == "poly":
        space.add_lwpolyline([T(tuple(q)) for q in pr["p"]], close=bool(pr.get("closed")), dxfattribs=at)
    elif t == "fill":
        pts = [T(tuple(q)) for q in pr["p"]]
        if len(pts) == 3:
            space.add_solid(pts, dxfattribs=at)
        else:
            h = space.add_hatch(color=256, dxfattribs=at)
            h.paths.add_polyline_path(pts, is_closed=True)
    elif t == "circle":
        cx, cy, r = pr["p"]
        space.add_circle(T((cx, cy)), r * f, dxfattribs=at)
    elif t == "arc":
        cx, cy, r, a0, a1 = pr["p"]
        space.add_arc(T((cx, cy)), r * f, a0, a1, dxfattribs=at)
    elif t == "text":
        e = space.add_text(dxf_text(pr["txt"]), dxfattribs={"height": pr["s"] * 0.72 * f, "layer": layer, "style": "FW",
                                                            "rotation": pr.get("rot") or 0})
        e.set_placement(T((pr["x"], pr["y"])), align=align[pr["anchor"]])


__all__ = ["LAYERS", "LAYER_STYLE", "to_dxf"]
