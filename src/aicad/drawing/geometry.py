"""Exact CAD-kernel work for drawings: hidden-line projection, section cut and the feature census.

Everything here reads the verified model (``out/part.step``) and returns plain JSON-able data, so the layout,
renderers and CHK-12 can run (and be tested) without the kernel. Coordinates are model millimetres.

View convention (Formwright: Z up, the front view looks along +Y):
  front  viewer at -Y, paper right = +X, paper up = +Z
  top    viewer at +Z, paper right = +X, paper up = +Y
  right  viewer at +X, paper right = +Y, paper up = +Z
  iso    viewer at (+X, -Y, +Z), paper up = projection of +Z
A view point (U, V) is the dot product of the model point with the view's right / up axes, so U and V are true
model coordinates in the principal views (front U = X, V = Z, and so on).
"""

from __future__ import annotations

import math
from typing import Any

from aicad.drawing import DrawingInputError

Vec = tuple[float, float, float]

VIEWS: dict[str, dict[str, Vec]] = {
    "front": {"dir": (0.0, -1.0, 0.0), "up": (0.0, 0.0, 1.0)},
    "top": {"dir": (0.0, 0.0, 1.0), "up": (0.0, 1.0, 0.0)},
    "right": {"dir": (1.0, 0.0, 0.0), "up": (0.0, 0.0, 1.0)},
    "iso": {"dir": (1.0, -1.0, 1.0), "up": (0.0, 0.0, 1.0)},
}
AXIS_INDEX = {"x": 0, "y": 1, "z": 2}
#: Section A-A: plane normal axis -> (view it is seen like, side of the centre that is kept: +1 / -1)
SECTION_LIKE = {"x": ("right", -1), "y": ("front", 1), "z": ("top", -1)}
ROUND = 6  # model coordinates are rounded to 1e-6 mm (STEP round-trip noise is ~1e-12)
EPS = 1e-6


# ----------------------------------------------------------------------------- small vector helpers
def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a: Vec) -> Vec:
    n = math.sqrt(_dot(a, a))
    return (a[0] / n, a[1] / n, a[2] / n)


def view_axes(view: str) -> tuple[Vec, Vec, Vec]:
    """(right, up, toward-viewer) unit vectors of a view."""
    d = _norm(VIEWS[view]["dir"])
    up = VIEWS[view]["up"]
    k = _dot(up, d)
    up = _norm((up[0] - k * d[0], up[1] - k * d[1], up[2] - k * d[2]))
    return _cross(up, d), up, d


def r6(x: float) -> float:
    v = round(float(x), ROUND)
    return 0.0 if v == 0 else v


# ----------------------------------------------------------------------------- loading
def load_solid(step_path: str) -> Any:
    from build123d import import_step

    shape = import_step(step_path)
    solids = shape.solids()
    if not solids:
        raise DrawingInputError("The model has no solid body to draw.")
    return shape if len(solids) > 1 else solids[0]


def bbox(shape: Any) -> list[float]:
    b = shape.bounding_box(optimal=True)
    return [r6(b.min.X), r6(b.min.Y), r6(b.min.Z), r6(b.max.X), r6(b.max.Y), r6(b.max.Z)]


# ----------------------------------------------------------------------------- projection (HLR)
def _edge_prims(edge: Any, du: float, dv: float) -> list[list[Any]]:
    """One projected edge as drawing primitives in view coordinates: line, circle, arc or polyline."""
    from build123d import GeomType

    gt = edge.geom_type
    s, e = edge.start_point(), edge.end_point()
    if gt == GeomType.LINE:
        return [["line", r6(s.X + du), r6(s.Y + dv), r6(e.X + du), r6(e.Y + dv)]]
    if gt == GeomType.CIRCLE:
        c, r = edge.arc_center, edge.radius
        cx, cy = r6(c.X + du), r6(c.Y + dv)
        if (s - e).length < 1e-9:
            return [["circle", cx, cy, r6(r)]]
        m = edge.position_at(0.5)
        a0 = math.degrees(math.atan2(s.Y - c.Y, s.X - c.X))
        a1 = math.degrees(math.atan2(e.Y - c.Y, e.X - c.X))
        am = math.degrees(math.atan2(m.Y - c.Y, m.X - c.X))

        def ccw(a: float, b: float) -> float:
            return (b - a) % 360.0

        if ccw(a0, am) > ccw(a0, a1):  # the edge runs clockwise: store it counter-clockwise
            a0, a1 = a1, a0
        a0 %= 360.0
        sweep = ccw(a0, a1)
        return [["arc", cx, cy, r6(r), r6(a0), r6(a0 + sweep)]]
    pts = [(p.X + du, p.Y + dv) for p in edge.positions(deflection=0.002)]
    pts = _simplify(pts)
    if len(pts) == 2:
        return [["line", r6(pts[0][0]), r6(pts[0][1]), r6(pts[1][0]), r6(pts[1][1])]]
    return [["poly", [[r6(x), r6(y)] for x, y in pts]]]


def _simplify(pts: list[tuple[float, float]], tol: float = 1e-5) -> list[tuple[float, float]]:
    """Drop points that are collinear with their neighbours (edge-on circles project to straight lines)."""
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        ax, ay = out[-1]
        bx, by = pts[i]
        cx, cy = pts[i + 1]
        lx, ly = cx - ax, cy - ay
        ln = math.hypot(lx, ly)
        if ln < 1e-12:
            continue
        if abs((bx - ax) * ly - (by - ay) * lx) / ln > tol:
            out.append(pts[i])
    out.append(pts[-1])
    return out


def _prim_key(p: list[Any]) -> tuple[Any, ...]:
    if p[0] == "line":
        a, b = (p[1], p[2]), (p[3], p[4])
        return ("line", *min(a, b), *max(a, b))
    if p[0] == "poly":
        pts = [tuple(q) for q in p[1]]
        return ("poly", *min(pts, pts[::-1]))
    return tuple(p)


def _canonical(prims: list[list[Any]]) -> list[list[Any]]:
    """Deterministic order and no duplicates (HLR output order can depend on memory addresses)."""
    seen: dict[tuple[Any, ...], list[Any]] = {}
    for p in prims:
        if p[0] == "line" and (p[1], p[2]) > (p[3], p[4]):
            p = ["line", p[3], p[4], p[1], p[2]]
        k = _prim_key(p)
        seen.setdefault(k, p)
    return [seen[k] for k in sorted(seen, key=lambda k: tuple(str(x) for x in k))]


def _extents(edges: list[Any], du: float, dv: float) -> list[float] | None:
    if not edges:
        return None
    xs, ys = [], []
    for e in edges:
        b = e.bounding_box(optimal=True)
        xs += [b.min.X + du, b.max.X + du]
        ys += [b.min.Y + dv, b.max.Y + dv]
    return [r6(min(xs)), r6(max(xs)), r6(min(ys)), r6(max(ys))]


def project(shape: Any, view: str, hidden: bool = True) -> dict[str, Any]:
    """Exact hidden-line projection (OCCT HLRBRep via build123d ``project_to_viewport``)."""
    from build123d import Vector

    x, up, d = view_axes(view)
    bb = shape.bounding_box(optimal=True)
    c = bb.center()
    dist = 10.0 * max(bb.diagonal, 1.0)
    origin = Vector(c.X + d[0] * dist, c.Y + d[1] * dist, c.Z + d[2] * dist)
    vis, hid = shape.project_to_viewport(origin, Vector(*up), c)
    cc = (c.X, c.Y, c.Z)
    du, dv = _dot(cc, x), _dot(cc, up)  # HLR returns coordinates relative to the look-at point
    visible = _canonical([p for e in vis for p in _edge_prims(e, du, dv)])
    hidden_p = _canonical([p for e in hid for p in _edge_prims(e, du, dv)]) if hidden else []
    vkeys = {_prim_key(p) for p in visible}
    hidden_p = [p for p in hidden_p if _prim_key(p) not in vkeys]
    return {"view": view, "visible": visible, "hidden": hidden_p,
            "extents": _extents(list(vis) + (list(hid) if hidden else []), du, dv)}


def bbox_extents(bb: list[float], view: str) -> list[float]:
    """The model bounding box projected on a view: [umin, umax, vmin, vmax] (exact for the principal views)."""
    x, up, _ = view_axes(view)
    corners = [(bb[i], bb[j], bb[k]) for i in (0, 3) for j in (1, 4) for k in (2, 5)]
    us = [_dot(p, x) for p in corners]
    vs = [_dot(p, up) for p in corners]
    return [r6(min(us)), r6(max(us)), r6(min(vs)), r6(max(vs))]


# ----------------------------------------------------------------------------- section A-A
def _wire_points(wire: Any, face: Any) -> list[tuple[float, float, float]]:
    from build123d import Edge
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.TopAbs import TopAbs_REVERSED

    pts: list[tuple[float, float, float]] = []
    ex = BRepTools_WireExplorer(wire.wrapped, face.wrapped)
    while ex.More():
        e = Edge(ex.Current())
        seg = [(p.X, p.Y, p.Z) for p in e.positions(deflection=0.002)]
        if ex.Orientation() == TopAbs_REVERSED:
            seg.reverse()
        if pts and seg and math.dist(pts[-1], seg[0]) < 1e-7:
            seg = seg[1:]
        pts += seg
        ex.Next()
    return pts


def section(shape: Any, axis: str, at: float | None = None) -> dict[str, Any]:
    """Cut normal to ``axis`` at ``at`` (default: the bounding-box centre); keep the part away from the viewer,
    project it (visible lines only, as section views are drawn) and return the cut faces as hatch loops."""
    from build123d import Box, Pos
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane

    like, keep = SECTION_LIKE[axis]
    k = AXIS_INDEX[axis]
    bb = bbox(shape)
    lo, hi = bb[:3], bb[3:]
    c = [(lo[i] + hi[i]) / 2 for i in range(3)]
    if at is not None:
        c[k] = float(at)
    size = [hi[i] - lo[i] + 2.0 for i in range(3)]
    centre = list(c)
    size[k] = hi[k] - lo[k] + 2.0
    centre[k] = c[k] + keep * size[k] / 2
    cutter = Pos(*centre) * Box(*size)
    half = shape & cutter
    if not half.solids():
        raise DrawingInputError("The section plane does not cut the part. Choose another axis.")
    proj = project(half, like, hidden=False)
    x, up, _ = view_axes(like)
    loops: list[list[list[float]]] = []
    for f in half.faces():
        ad = BRepAdaptor_Surface(f.wrapped)
        if ad.GetType() != GeomAbs_Plane:
            continue
        n = ad.Plane().Axis().Direction()
        nv = (n.X(), n.Y(), n.Z())
        if abs(abs(nv[k]) - 1.0) > 1e-9:
            continue
        p = ad.Plane().Location()
        if abs((p.X(), p.Y(), p.Z())[k] - c[k]) > 1e-6:
            continue
        for w in [f.outer_wire(), *f.inner_wires()]:
            pts = _wire_points(w, f)
            loop = _simplify([(_dot(q, x), _dot(q, up)) for q in pts])
            if len(loop) >= 3:
                loops.append([[r6(a), r6(b)] for a, b in loop])
    loops.sort(key=lambda lp: (min(q[0] for q in lp), min(q[1] for q in lp), len(lp)))
    return {**proj, "axis": axis, "like": like, "keep": keep, "plane": r6(c[k]), "loops": loops}


# ----------------------------------------------------------------------------- feature census
def _principal(d: Vec) -> str | None:
    for name, i in AXIS_INDEX.items():
        if abs(abs(d[i]) - 1.0) < 1e-9:
            return name
    return None


def _merge(intervals: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    """Merge overlapping axial intervals; the third value accumulates the angular span (radians)."""
    out: list[list[float]] = []
    for a, b, span in sorted(intervals):
        if out and a <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], b)
            out[-1][2] += span
        else:
            out.append([a, b, span])
    return [(a, b, s) for a, b, s in out]


def census(shape: Any) -> dict[str, Any]:
    """Holes (full concave cylinders), outer cylinders (full convex) and planar levels per principal axis.

    Exact B-rep data: radii and axes from the cylinder surfaces, levels from plane equations, through/blind from
    a point-in-solid test just beyond each end of a hole.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.TopAbs import TopAbs_IN, TopAbs_REVERSED

    bb = bbox(shape)
    levels: dict[str, set[float]] = {a: set() for a in AXIS_INDEX}
    groups: dict[tuple[Any, ...], list[tuple[float, float, float]]] = {}
    mids: dict[tuple[Any, ...], list[float]] = {}
    chamfers: list[dict[str, Any]] = []
    unsupported = 0
    for f in shape.faces():
        ad = BRepAdaptor_Surface(f.wrapped)
        t = ad.GetType()
        if t == GeomAbs_Plane:
            pl = ad.Plane()
            n = pl.Axis().Direction()
            nv = (n.X(), n.Y(), n.Z())
            ax = _principal(nv)
            if ax:
                loc = pl.Location()
                levels[ax].add(r6((loc.X(), loc.Y(), loc.Z())[AXIS_INDEX[ax]]))
            else:
                ch = _chamfer(f, nv)
                if ch is not None:
                    chamfers.append(ch)
            continue
        if t != GeomAbs_Cylinder:
            continue
        cyl = ad.Cylinder()
        a1 = cyl.Axis()
        dvec = (a1.Direction().X(), a1.Direction().Y(), a1.Direction().Z())
        loc = (a1.Location().X(), a1.Location().Y(), a1.Location().Z())
        u0, u1, v0, v1 = BRepTools.UVBounds_s(f.wrapped)
        p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
        ad.D1((u0 + u1) / 2, (v0 + v1) / 2, p, du, dv)
        nrm = du.Crossed(dv)
        if f.wrapped.Orientation() == TopAbs_REVERSED:
            nrm.Reverse()
        pv = (p.X(), p.Y(), p.Z())
        tpar = _dot((pv[0] - loc[0], pv[1] - loc[1], pv[2] - loc[2]), dvec)
        foot = (loc[0] + tpar * dvec[0], loc[1] + tpar * dvec[1], loc[2] + tpar * dvec[2])
        radial = (pv[0] - foot[0], pv[1] - foot[1], pv[2] - foot[2])
        concave = (nrm.X() * radial[0] + nrm.Y() * radial[1] + nrm.Z() * radial[2]) < 0
        ax = _principal(dvec)
        if ax is None:
            if concave and (u1 - u0) > 2 * math.pi - 1e-6:
                unsupported += 1
            continue
        i = AXIS_INDEX[ax]
        sign = 1.0 if dvec[i] > 0 else -1.0
        ta, tb = sorted((loc[i] + sign * v0, loc[i] + sign * v1))
        perp = tuple(r6(loc[j]) for j in range(3) if j != i)
        key = (concave, ax, perp, r6(cyl.Radius()))
        groups.setdefault(key, []).append((ta, tb, u1 - u0))
        mids.setdefault(key, [r6(v) for v in pv])

    solid_cls = BRepClass3d_SolidClassifier()
    solid_cls.Load(shape.wrapped)

    def inside(pt: list[float]) -> bool:
        solid_cls.Perform(gp_Pnt(*pt), 1e-7)
        return solid_cls.State() == TopAbs_IN

    holes: list[dict[str, Any]] = []
    outer: list[dict[str, Any]] = []
    arcs: list[dict[str, Any]] = []
    for (concave, ax, perp, r), ivs in sorted(groups.items(), key=lambda kv: str(kv[0])):
        i = AXIS_INDEX[ax]
        others = [j for j in range(3) if j != i]
        for ta, tb, span in _merge(ivs):
            if span < 2 * math.pi - 1e-6:
                # fillets, rounds and partial cylinders: radius callouts (never holes / turned diameters)
                if span < math.pi + 1e-6:
                    arcs.append({"axis": ax, "centre": list(perp), "r": r6(r), "t0": r6(ta), "t1": r6(tb),
                                 "concave": concave, "mid": mids[(concave, ax, perp, r6(r))]})
                continue
            rec = {"axis": ax, "centre": list(perp), "dia": r6(2 * r), "t0": r6(ta), "t1": r6(tb)}
            if not concave:
                outer.append(rec)
                continue
            ends = []
            for t_end, s in ((ta, -1.0), (tb, 1.0)):
                n_in = 0
                for ang in (45.0, 135.0, 225.0, 315.0):
                    q = [0.0, 0.0, 0.0]
                    q[i] = t_end + s * 0.05
                    q[others[0]] = perp[0] + 0.75 * r * math.cos(math.radians(ang))
                    q[others[1]] = perp[1] + 0.75 * r * math.sin(math.radians(ang))
                    n_in += inside(q)
                ends.append(n_in >= 2)
            if ends[0] and ends[1]:
                unsupported += 1  # internal cavity: no open end to call out
                continue
            thru = not ends[0] and not ends[1]
            rec.update({"thru": thru, "depth": r6(tb - ta),
                        "open": 0 if thru else (-1 if not ends[0] else 1)})
            holes.append(rec)
    chamfers.sort(key=lambda c: (c["edge"], c["legs"], c["mid"]))
    # a faceted curved profile (an involute gear flank, a polyline cam) reads as dozens of "chamfers" of different
    # sizes; real edge breaks come in a few sizes. More than 6 sizes: none of them is dimensioned as a chamfer.
    if len({tuple(round(x, 2) for x in c["legs"]) for c in chamfers}) > 6:
        chamfers = []
    return {"bbox": bb, "holes": holes, "outer": outer, "unsupported_holes": unsupported,
            "levels": {a: sorted(v) for a, v in levels.items()}, "arcs": arcs, "chamfers": chamfers}


def _chamfer(face: Any, n: Vec) -> dict[str, Any] | None:
    """A flat chamfer: a planar face whose normal lies in a principal plane (one zero component), running along a
    principal axis. Its legs are the face extents along the two axes of the normal (exact for a straight chamfer)."""
    zero = [i for i in range(3) if abs(n[i]) < 1e-9]
    if len(zero) != 1:
        return None
    e = zero[0]
    b = face.bounding_box(optimal=True)
    ext = [b.max.X - b.min.X, b.max.Y - b.min.Y, b.max.Z - b.min.Z]
    legs = [r6(ext[i]) for i in range(3) if i != e]
    # a sloped wall is not an edge break; a leg under 0.1 mm is a facet of a curved profile (an involute flank)
    if min(legs) < 0.1 or max(legs) > 25.0 or ext[e] < 2 * max(legs):
        return None
    c = b.center()
    names = ["x", "y", "z"]
    return {"edge": names[e], "legs": legs, "normal": [r6(v) for v in n], "length": r6(ext[e]),
            "mid": [r6(c.X), r6(c.Y), r6(c.Z)]}


# ----------------------------------------------------------------------------- part type and orientation
def turned(cen: dict[str, Any]) -> tuple[str, list[float], float] | None:
    """Axis, centre and envelope diameter when the outer envelope is a turned (coaxial cylinder) body."""
    bb = cen["bbox"]
    for ax in ("x", "z", "y"):
        i = AXIS_INDEX[ax]
        others = [j for j in range(3) if j != i]
        centre = [round((bb[j] + bb[j + 3]) / 2, 6) for j in others]
        ext = [bb[j + 3] - bb[j] for j in others]
        cyl = [c for c in cen["outer"]
               if c["axis"] == ax and all(abs(c["centre"][k] - centre[k]) < EPS for k in (0, 1))]
        if cyl:
            d = max(c["dia"] for c in cyl)
            if all(abs(d - e) < EPS for e in ext):
                return ax, centre, d
    return None


def _feature_dir(cen: dict[str, Any], ax: str, centre: list[float]) -> tuple[float, float, float] | None:
    """Direction (perpendicular to the turning axis) of a one-sided flat feature such as a keyway floor."""
    others = [a for a in ("x", "y", "z") if a != ax]
    best: tuple[str, float] | None = None
    for k, a in enumerate(others):
        c0 = centre[k]
        offs = [v - c0 for v in cen["levels"][a]]
        for o in offs:
            if abs(o) < EPS or any(abs(o + q) < EPS for q in offs):
                continue  # on the axis, or mirrored (keyway side walls): not one-sided
            if best is None or abs(o) > abs(best[1]):
                best = (a, o)
    if best is None:
        return None
    v = [0.0, 0.0, 0.0]
    v[AXIS_INDEX[best[0]]] = 1.0 if best[1] > 0 else -1.0
    return (v[0], v[1], v[2])


def orient(shape: Any, cen: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    """Drawing orientation (MAKE-07): a turned part is drawn with its axis horizontal (along drawing X) and a
    one-sided feature (keyway) facing up; prismatic parts keep the model orientation. Returns the shape to draw
    and the rotation rows (drawing X, Y, Z expressed in model coordinates)."""
    tr = turned(cen)
    if tr is None:
        return shape, {"turned": False, "hollow": False, "rows": None}
    ax, centre, dia = tr
    a = [0.0, 0.0, 0.0]
    a[AXIS_INDEX[ax]] = 1.0
    av = (a[0], a[1], a[2])
    f = _feature_dir(cen, ax, centre)
    if f is None:
        f = {"x": (0.0, 0.0, 1.0), "y": (0.0, 0.0, 1.0), "z": (-1.0, 0.0, 0.0)}[ax]
    yv = _cross(f, av)
    rows = [av, yv, f]
    hollow = any(h["axis"] == ax and h["thru"] and all(abs(h["centre"][k] - centre[k]) < EPS for k in (0, 1))
                 for h in cen["holes"])
    ident = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    info = {"turned": True, "hollow": hollow, "axis_model": ax, "dia": dia,
            "rows": None if [tuple(r) for r in rows] == ident else [[r6(v) for v in r] for r in rows]}
    if info["rows"] is None:
        return shape, info
    from build123d import Location
    from OCP.gp import gp_Trsf

    t = gp_Trsf()
    t.SetValues(*rows[0], 0.0, *rows[1], 0.0, *rows[2], 0.0)
    return shape.moved(Location(t)), info


def _feature_span(cen: dict[str, Any]) -> tuple[float, float] | None:
    """Axial span of the first non-turned feature (keyway) of a part drawn axis-along-X."""
    steps = {cen["bbox"][0], cen["bbox"][3]}
    for c in cen["outer"]:
        if c["axis"] == "x":
            steps |= {c["t0"], c["t1"]}
    feat = sorted(v for v in cen["levels"]["x"] if all(abs(v - s) > EPS for s in steps))
    return (feat[0], feat[1]) if len(feat) >= 2 else None


def plan(cen: dict[str, Any], info: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any]:
    """Views and section from the part type and the user's options (``views`` None = automatic,
    ``section`` "auto" | None | "x" | "y" | "z" | "axial" | "cross")."""
    turned_part = info["turned"]
    views = opts.get("views")
    if views is None:
        # a turned part looks the same from the top as from the front: one elevation and the end view
        views = ["front", "right", "iso"] if turned_part else ["front", "top", "right", "iso"]
    sec = opts.get("section", "auto")
    note = None
    out: dict[str, Any] = {"views": list(views), "section": None, "at": None, "front_section": False,
                           "turned": turned_part, "hollow": info["hollow"]}
    if turned_part:
        if sec in ("x", "cross"):
            kind = "cross"
        elif sec in ("y", "z", "axial"):
            kind = "axial"
        elif sec == "auto":
            kind = "axial" if info["hollow"] else ("cross" if _feature_span(cen) else None)
        else:
            kind = None
        if kind == "axial" and not info["hollow"]:
            # ISO 128-50: solid shafts, pins and keys are not sectioned lengthwise
            kind = "cross" if _feature_span(cen) else None
            note = ("Solid turned parts are not sectioned lengthwise (ISO 128-50): a cross-section at the feature is "
                    "shown instead.") if kind else "Solid turned parts are not sectioned lengthwise (ISO 128-50)."
        if kind == "axial":
            out.update(section="y", front_section="front" in views, kind="axial")
        elif kind == "cross":
            span = _feature_span(cen)
            out.update(section="x", at=r6((span[0] + span[1]) / 2) if span else None, kind="cross")
    elif sec in ("x", "y", "z"):
        out["section"] = sec
    out["note"] = note
    return out


def to_drawing(rows: list[list[float]] | None, p: Any) -> list[float]:
    """A model point or direction in drawing orientation (``orient`` rows: drawing X, Y, Z in model coordinates)."""
    if not rows:
        return [float(p[0]), float(p[1]), float(p[2])]
    return [rows[i][0] * p[0] + rows[i][1] * p[1] + rows[i][2] * p[2] for i in range(3)]


def attach_threads(cen: dict[str, Any], rows: list[list[float]] | None, threads: list[dict[str, Any]]
                   ) -> dict[str, Any]:
    """Cosmetic threads (CAD-027) on the census: a tapped hole carries ``thread`` when a recorded instance lies on
    its axis and its Ø is a tap drill for it; a threaded cylinder when its Ø is the major Ø. Returns counts."""
    matched = unmatched = 0
    for t in threads or []:
        lite = {k: t.get(k) for k in ("designation", "size", "pitch", "cls", "internal", "depth", "major", "minor",
                                      "feature", "name")}
        for inst in t.get("instances") or []:
            p = to_drawing(rows, inst["p"])
            d = to_drawing(rows, inst["dir"])
            ax = _principal((d[0], d[1], d[2]))
            if ax is None:
                unmatched += 1
                continue
            i = AXIS_INDEX[ax]
            perp = [p[j] for j in range(3) if j != i]
            pool = cen["holes"] if t.get("internal") else cen["outer"]
            hit = None
            for h in pool:
                if h["axis"] != ax or any(abs(h["centre"][k] - perp[k]) > 1e-3 for k in (0, 1)):
                    continue
                ok = (t["minor"] - 0.6 <= h["dia"] < t["major"]) if t.get("internal") else \
                    abs(h["dia"] - t["major"]) <= max(0.3, 0.02 * t["major"])
                if ok and h["t0"] - 1e-3 <= p[i] <= h["t1"] + 1e-3:
                    hit = h
                    break
            if hit is None:
                unmatched += 1
                continue
            hit["thread"] = {**lite, "start": r6(p[i]), "sign": 1.0 if d[i] > 0 else -1.0}
            matched += 1
    return {"matched": matched, "unmatched": unmatched}


def analyse(step_path: str, opts: dict[str, Any]) -> dict[str, Any]:
    """Everything the layout needs from the kernel, as plain data (in drawing orientation)."""
    shape = load_solid(step_path)
    cen0 = census(shape)
    shape, info = orient(shape, cen0)
    cen = census(shape) if info["rows"] else cen0
    thr = attach_threads(cen, info["rows"], opts.get("threads") or [])
    pl = plan(cen, info, opts)
    out: dict[str, Any] = {"census": cen, "views": {}, "part": info, "plan": pl, "threads": thr}
    for v in pl["views"]:
        if v == "front" and pl["front_section"]:
            continue
        out["views"][v] = project(shape, v)
    if pl["section"]:
        out["section"] = section(shape, pl["section"], pl["at"])
        if pl["front_section"]:
            out["views"]["front"] = {**out["section"], "view": "front", "is_section": True}
    return out
