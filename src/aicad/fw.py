"""Formwright helper library for model scripts (`from aicad import fw`).

- feature(name, part)      record a named design feature (feature tree + face provenance)
- edges_near / faces_near  select topology by location (stable across rebuilds, unlike indices)
- apply_manual(part, ops)  apply user-authored manual features (fillet, chamfer, hole, sketch extrude/cut)
- thread(part, point, ...) cosmetic thread on a hole or cylinder (metadata only; the geometry is unchanged)
- base_flange / edge_flange / hem   sheet metal (CAD-026); the flat pattern is made by the runner

State is per build: the runner calls reset() before executing a script.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from build123d import (
    Align,
    Axis,
    Circle,
    Cone,
    Cylinder,
    Edge,
    Face,
    Line,
    Location,
    Plane,
    Polygon,
    Pos,
    Rectangle,
    ThreePointArc,
    Transition,
    Vector,
    Wire,
    chamfer,
    extrude,
    fillet,
    loft,
    mirror,
    offset,
    revolve,
    sweep,
)

from aicad import refplane as _refplane
from aicad import sheetmetal as _sm

_STATE: dict[str, Any] = {"log": [], "manual": 0, "base": None, "manual_errors": [], "threads": [], "sheet": None}


def reset() -> None:
    _STATE["log"] = []
    _STATE["manual"] = 0
    _STATE["last"] = None
    _STATE["suppressed"] = set()
    _STATE["manual_errors"] = []
    _STATE["threads"] = []
    _STATE["sheet"] = None


def set_base(folder: Any) -> None:
    """Project folder of the running model (set by the runner)."""
    from pathlib import Path

    _STATE["base"] = Path(folder).resolve()


def project_file(rel: str) -> str:
    """Absolute path of a file inside the project (e.g. an imported STEP under imports/). Cannot escape it."""
    from pathlib import Path

    base = _STATE.get("base") or Path.cwd()
    p = (Path(base) / rel).resolve()
    if base not in p.parents:
        raise ValueError("file must be inside the project")
    return str(p)


def import_reference(rel: str) -> Any:
    """Load an imported STEP file from the project as a solid (no feature history)."""
    from build123d import import_step

    return import_step(project_file(rel))


def _load_json(rel: str) -> Any:
    import json
    from pathlib import Path

    return json.loads(Path(project_file(rel)).read_text(encoding="utf-8"))


def imported_blank(ref: str, recognition: str | None = None) -> Any:
    """The exact imported solid ("Imported blank") plus the recognised features as annotated, highlightable
    entries of the feature tree. Geometry is never approximated: unrecognised faces simply stay in the blank."""
    part = import_reference(ref)
    if recognition:
        try:
            data = _load_json(recognition)
        except (OSError, ValueError):
            data = {}
        for feat in data.get("features", []):
            if feat.get("kind") in ("body", "unrecognised"):
                continue
            keys = {tuple(k) for k in feat.get("keys", [])}
            clean = {k: v for k, v in (feat.get("params") or {}).items() if isinstance(v, (int, float, str, bool))}
            _STATE["log"].append({"name": str(feat.get("name", "Feature")), "kind": str(feat.get("kind", "recognised")),
                                  "keys": keys, "params": clean})
    return feature("Imported blank", part, kind="blank")


def redefine_holes(part: Any, recognition: str, feature_id: str, d: float | None = None, pcd: float | None = None) -> Any:
    """Edit a recognised hole / hole pattern on the exact imported body: the original holes are filled and recut
    at the new diameter (and pitch-circle diameter for circular patterns). Unchanged values leave the body untouched."""
    data = _load_json(recognition)
    feat = next((f for f in data.get("features", []) if f.get("id") == feature_id), None)
    if feat is None or not feat.get("holes"):
        raise ValueError(f"recognised feature '{feature_id}' not found")
    holes = feat["holes"]
    d0 = float(holes[0]["d"])
    pcd0 = feat.get("params", {}).get("pcd")
    new_d = d0 if d is None else float(d)
    new_pcd = pcd0 if pcd is None or pcd0 is None else float(pcd)
    if abs(new_d - d0) < 1e-9 and (pcd0 is None or abs(new_pcd - pcd0) < 1e-9):
        return part
    if new_d <= 0:
        raise ValueError("hole diameter must be positive")
    centre = feat.get("params", {}).get("center")

    def cyl(r: float, h: float, start: Any, direction: Any) -> Any:
        from build123d import Align

        loc = Plane(origin=_v(start), z_dir=_v(direction)).location
        return loc * Cylinder(r, h, align=(Align.CENTER, Align.CENTER, Align.MIN))

    for h in holes:  # fill the originals exactly
        part = part + cyl(d0 / 2, float(h["depth"]), h["open"], h["dir"])
    for h in holes:
        start = _v(h["open"])
        if pcd0 and centre is not None and abs(new_pcd - pcd0) > 1e-9:
            c = _v(centre)
            ax = _v(h["dir"]).normalized()
            rel = start - c
            radial = rel - ax * rel.dot(ax)
            start = start + radial * (new_pcd / pcd0 - 1)
        ext = 0.01 if h.get("through") else 0.0
        direction = _v(h["dir"]).normalized()
        part = part - cyl(new_d / 2, float(h["depth"]) + 2 * ext, start - direction * ext, direction)
    return feature(f"{feat.get('name', 'Holes')} (edited)", part, kind="edit", d=new_d)


def plane_eq(face: Any) -> tuple[float, float, float, float]:
    """Outward normal n and offset d = n . p of a planar TopoDS_Face, read from its plane: no surface integral (the
    old normal_at(center()) path ran two per face, and fw.feature keys every face of the part at every step)."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.TopAbs import TopAbs_REVERSED

    pos = BRepAdaptor_Surface(face).Plane().Position()
    dv, p = pos.Direction(), pos.Location()
    k = 1.0 if pos.Direct() else -1.0  # the surface normal is XDir x YDir
    if face.Orientation() == TopAbs_REVERSED:
        k = -k
    nx, ny, nz = k * dv.X(), k * dv.Y(), k * dv.Z()
    return nx, ny, nz, nx * p.X() + ny * p.Y() + nz * p.Z()


def face_key(f: Any) -> tuple[Any, ...]:
    """Identity of a face's *underlying surface* (plane equation, cylinder axis + radius ...), so a face that a
    later boolean merely trims is still attributed to the feature that created its surface."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Sphere

    s = BRepAdaptor_Surface(f.wrapped)
    t = s.GetType()

    def r(x: float) -> float:
        return round(x, 3) + 0.0

    if t == GeomAbs_Plane:
        nx, ny, nz, d = plane_eq(f.wrapped)
        return ("plane", r(nx), r(ny), r(nz), r(d))
    if t in (GeomAbs_Cylinder, GeomAbs_Cone):
        ax = (s.Cylinder() if t == GeomAbs_Cylinder else s.Cone()).Axis()
        dv, p = ax.Direction(), ax.Location()
        if dv.Z() < -1e-9 or (abs(dv.Z()) < 1e-9 and (dv.Y() < -1e-9 or (abs(dv.Y()) < 1e-9 and dv.X() < 0))):
            dv = dv.Reversed()
        # point on axis closest to origin, so different axis locations along the same line compare equal
        px, py, pz = p.X(), p.Y(), p.Z()
        k = px * dv.X() + py * dv.Y() + pz * dv.Z()
        q = (px - k * dv.X(), py - k * dv.Y(), pz - k * dv.Z())
        rad = s.Cylinder().Radius() if t == GeomAbs_Cylinder else s.Cone().SemiAngle()
        return ("cyl" if t == GeomAbs_Cylinder else "cone", r(dv.X()), r(dv.Y()), r(dv.Z()), *map(r, q), r(rad))
    if t == GeomAbs_Sphere:
        sp = s.Sphere()
        c = sp.Location()
        return ("sphere", r(c.X()), r(c.Y()), r(c.Z()), r(sp.Radius()))
    c = f.center()
    return (str(f.geom_type), r(c.X), r(c.Y), r(c.Z), r(f.area))


def set_suppressed(names: Any) -> None:
    """Design features the user suppressed in the feature tree (set by the runner before the script runs)."""
    _STATE["suppressed"] = {str(n) for n in (names or [])}


def _keys(part: Any) -> set[tuple[Any, ...]]:
    try:
        return {face_key(f) for f in part.faces()}
    except Exception:  # noqa: BLE001 - never break a model because of bookkeeping
        return set()


def feature(name: str, part: Any, kind: str = "feature", **params: Any) -> Any:
    """Record that `part` is the state after feature `name` and return it.

    `chain` marks a step built on the previous recorded state (they share surfaces), the usual
    `part = fw.feature("Pocket", part - pocket)` pattern. Such a step can be suppressed from the feature tree:
    `feature` then returns the previous state instead, so the step has no effect on the result."""
    keys = _keys(part)
    prev = _STATE.get("last")
    chain = prev is not None and bool(keys & prev[1])
    clean = {k: v for k, v in params.items() if isinstance(v, (int, float, str, bool))}
    if kind == "feature" and str(name) in _STATE.get("suppressed", set()):
        if not chain:
            raise ValueError(f"'{name}' can't be suppressed: it is the first feature or isn't built on the previous one")
        _STATE["log"].append({"name": str(name), "kind": kind, "keys": set(), "params": clean, "chain": True,
                              "suppressed": True})
        return prev[0]
    _STATE["log"].append({"name": str(name), "kind": kind, "keys": keys, "params": clean, "chain": chain})
    _STATE["last"] = (part, keys)
    return part


def log() -> list[dict[str, Any]]:
    return list(_STATE["log"])


def manual_count() -> int:
    return int(_STATE["manual"])


def _v(p: Any) -> Vector:
    return Vector(*p) if not isinstance(p, Vector) else p


def edges_near(part: Any, points: list[Any], tol: float = 0.05) -> list[Any]:
    """For each point (e.g. picked in the viewer), the edge passing nearest to it within `tol` mm. A point that is
    equally near several edges (a corner vertex) selects all of them, as before; a point on an edge's middle selects
    that edge only."""
    pts = [_v(p) for p in points]
    out: list[Any] = []
    for p in pts:
        near = [(e.distance_to(p), e) for e in part.edges()]
        near = [(d, e) for d, e in near if d <= tol]
        if not near:
            continue
        best = min(d for d, _ in near)
        for d, e in near:
            if d <= best + 1e-7 and not any(e.is_same(x) for x in out):
                out.append(e)
    return out


def _edge_sig(e: Any) -> tuple[str, Vector | None]:
    """("line", direction) / ("circle", axis) / ("other", None): what kind of edge was picked, for re-finding it."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line

    c = BRepAdaptor_Curve(e.wrapped)
    t = c.GetType()
    if t == GeomAbs_Line:
        d = c.Line().Direction()
        return "line", Vector(d.X(), d.Y(), d.Z())
    if t == GeomAbs_Circle:
        d = c.Circle().Axis().Direction()
        return "circle", Vector(d.X(), d.Y(), d.Z())
    return "other", None


def _sig_matches(e: Any, ref: dict[str, Any] | None) -> bool:
    if not ref or not ref.get("kind"):
        return True
    kind, d = _edge_sig(e)
    if kind != ref["kind"]:
        return False
    if d is None or not ref.get("dir"):
        return True
    return abs(d.normalized().dot(_v(ref["dir"]).normalized())) > 0.999


def _bbox6(part: Any) -> list[float]:
    bb = part.bounding_box()
    return [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z]


def _remaps(p: Vector, ref: list[float], now: list[float]) -> list[Vector]:
    """Where a point picked on the body when it had bounding box `ref` most likely is now (box `now`): per axis, a
    point on the box boundary keeps its offset from that side; any other point is tried at the same offset from the
    centre, at the same fraction of the size, then at the same offset from either side."""
    axes = []
    for i in range(3):
        a0, a1, b0, b1, x = ref[i], ref[i + 3], now[i], now[i + 3], (p.X, p.Y, p.Z)[i]
        eps = 1e-6 * max(1.0, a1 - a0)
        if abs(x - a0) <= eps:
            c = [b0 + (x - a0)]
        elif abs(x - a1) <= eps:
            c = [b1 + (x - a1)]
        else:
            c = [(b0 + b1) / 2 + x - (a0 + a1) / 2]
            if a1 - a0 > 1e-9:
                c.append(b0 + (x - a0) / (a1 - a0) * (b1 - b0))
            c += [b0 + (x - a0), b1 + (x - a1)]
        uniq: list[float] = []
        for v in c:
            if all(abs(v - u) > 1e-9 for u in uniq):
                uniq.append(v)
        axes.append(uniq)
    return [Vector(*xyz) for xyz in itertools.product(*axes)]


def _near_box(shape: Any, p: Vector, tol: float) -> bool:
    bb = shape.bounding_box()
    return (bb.min.X - tol <= p.X <= bb.max.X + tol and bb.min.Y - tol <= p.Y <= bb.max.Y + tol
            and bb.min.Z - tol <= p.Z <= bb.max.Z + tol)


def _resolve_edges(part: Any, f: dict[str, Any], tol: float = 0.05) -> list[Any]:
    """The edges a fillet/chamfer was picked on. Each stored point selects the nearest edge of the picked kind and
    direction (`edge_refs`). If the body changed size so the point no longer lies on such an edge, the point is
    carried along with the body's bounding box (`ref_bbox`, the box when it was picked) and the edge found there."""
    pts = [_v(p) for p in f["edges"]]
    refs = list(f.get("edge_refs") or [])
    refs += [None] * (len(pts) - len(refs))
    edges = list(part.edges())
    now = _bbox6(part) if f.get("ref_bbox") else None
    out: list[Any] = []
    for i, (p, ref) in enumerate(zip(pts, refs, strict=True)):
        found: list[Any] = []
        for q in [p, *(_remaps(p, f["ref_bbox"], now) if now else [])]:
            near = [(e.distance_to(q), e) for e in edges if _near_box(e, q, tol) and _sig_matches(e, ref)]
            near = [(d, e) for d, e in near if d <= tol]
            if near:
                best = min(d for d, _ in near)
                found = [e for d, e in near if d <= best + 1e-7]
                if ref:  # a picked edge is one edge, even where several meet at the stored point
                    found = found[:1]
                break
        if not found:
            what = "edge" if len(pts) == 1 else f"edge {i + 1} of {len(pts)}"
            raise ValueError(f"the picked {what} was not found (the geometry changed)")
        out += [e for e in found if not any(e.is_same(x) for x in out)]
    return out


def _resolve_face(part: Any, fc: dict[str, Any], ref_bbox: list[float] | None, what: str) -> list[Any]:
    """Faces at a picked point (and outward normal), carried along with the body's size like `_resolve_edges`."""
    p = _v(fc["point"])
    found = faces_near(part, p, normal=fc.get("normal"))
    if not found and ref_bbox:
        for q in _remaps(p, ref_bbox, _bbox6(part)):
            found = faces_near(part, q, normal=fc.get("normal"))
            if found:
                break
    if not found:
        raise ValueError(f"{what} was not found (the geometry changed)")
    return found


def faces_near(part: Any, point: Any, normal: Any | None = None, tol: float = 0.05) -> list[Any]:
    """Faces containing (within tol) the point; optionally with a matching outward normal (planar faces)."""
    p = _v(point)
    n = _v(normal).normalized() if normal is not None else None
    out = []
    for f in part.faces():
        if f.distance_to(p) > tol:
            continue
        if n is not None:
            try:
                fn = f.normal_at(p)
                if fn.dot(n) < 0.99:
                    continue
            except Exception:  # noqa: BLE001,S112 - non-planar faces have no single normal
                continue
        out.append(f)
    return out


def _plane(spec: dict[str, Any]) -> Plane:
    return Plane(origin=_v(spec["origin"]), x_dir=_v(spec.get("x_dir", (1, 0, 0))) if spec.get("x_dir") else None,
                 z_dir=_v(spec["normal"]))


def _sketch(spec: dict[str, Any]) -> Any:
    k = spec["kind"]
    cx, cy = float(spec.get("cx", 0)), float(spec.get("cy", 0))
    if k == "rect":
        return Pos(cx, cy) * Rectangle(float(spec["w"]), float(spec["h"]))
    if k == "circle":
        return Pos(cx, cy) * Circle(float(spec["r"]))
    if k == "poly":
        return Polygon(*[(float(u), float(v)) for u, v in spec["pts"]], align=None)
    raise ValueError(f"unknown sketch kind {k!r}")


def _profile_face(prof: dict[str, Any]) -> Any:
    if prof["kind"] == "circle":
        return Pos(float(prof["cx"]), float(prof["cy"])) * Circle(float(prof["r"]))
    segs = list(prof["segs"])
    # Orient the loop counter-clockwise so the face normal is the sketch plane's +Z (extrude direction is
    # then always "out of the face", whatever direction the user drew the loop in).
    area2 = sum(float(segs[i]["a"][0]) * float(segs[i]["b"][1]) - float(segs[i]["b"][0]) * float(segs[i]["a"][1])
                for i in range(len(segs)))
    for s in segs:
        if s["type"] == "arc":  # add the arc's bulge (triangle a-m-b) to the signed area
            (ax, ay), (mx, my), (bx, by) = s["a"], s["m"], s["b"]
            area2 += (float(ax) * float(my) - float(mx) * float(ay)) + (float(mx) * float(by) - float(bx) * float(my)) \
                - (float(ax) * float(by) - float(bx) * float(ay))
    if area2 < 0:
        segs = [{**s, "a": s["b"], "b": s["a"]} for s in reversed(segs)]
    edges = []
    for sg in segs:
        a = (float(sg["a"][0]), float(sg["a"][1]))
        b = (float(sg["b"][0]), float(sg["b"][1]))
        if sg["type"] == "arc":
            edges.append(ThreePointArc(a, (float(sg["m"][0]), float(sg["m"][1])), b))
        else:
            edges.append(Line(a, b))
    return Face(Wire(edges))


def sketch_region(profiles: list[dict[str, Any]]) -> Any:
    """Faces from closed profiles; loops nested an odd number of times are holes (even-odd rule)."""
    faces = [_profile_face(p) for p in profiles]
    faces.sort(key=lambda f: -f.area)
    depth = []
    for i, f in enumerate(faces):
        c = f.center()
        depth.append(sum(1 for g in faces[:i] if g.area > f.area and g.distance_to(c) < 1e-9))
    region = None
    for f, d in zip(faces, depth, strict=True):
        if d % 2 == 0:
            region = f if region is None else region + f
    for f, d in zip(faces, depth, strict=True):
        if d % 2 == 1 and region is not None:
            region = region - f
    if region is None:
        raise ValueError("sketch has no closed profile")
    return region


TOOL_OPS = {"sketch", "extrude", "revolve", "hole", "sweep", "loft"}
BASE_OPS = {"sketch", "extrude", "revolve", "sweep", "loft", "sm_base"}  # can create the first solid of a hand-modelled part
SKETCH_USERS = {"sweep": ("profile", "path"), "loft": ("sections",)}  # features that consume sketch nodes (by id)
NON_GEOMETRIC = _refplane.NON_GEOMETRIC
ref_plane = _refplane.ref_plane


def _sketch_axis(plane: Plane, axis: dict[str, Any]) -> Axis:
    """Axis through two points given in sketch (u, v) coordinates of `plane`."""
    a = plane.from_local_coords((float(axis["a"][0]), float(axis["a"][1])))
    b = plane.from_local_coords((float(axis["b"][0]), float(axis["b"][1])))
    d = Vector(b) - Vector(a)
    if d.length < 1e-9:
        raise ValueError("the revolve axis has zero length")
    return Axis(Vector(a), d)


def _extrude_region(region: Any, f: dict[str, Any], diag: float) -> Any:
    """Solid swept from a placed region with the feature's end condition (blind, mid-plane, through all)."""
    d = float(f.get("distance") or 0)
    end = f.get("end", "blind")
    sign = -1.0 if f.get("mode", "add") == "cut" else 1.0
    if f.get("reverse"):
        sign = -sign
    if end == "through":
        return extrude(region, amount=sign * diag * 2)
    if d <= 0:
        raise ValueError("distance must be positive")
    if end == "mid":
        return extrude(region, amount=d / 2, both=True)
    return extrude(region, amount=sign * d)


def _tool(f: dict[str, Any], diag: float) -> Any:
    """The solid(s) a sketch / extrude / revolve / hole feature adds or removes, independent of the body."""
    op = f["op"]
    if op == "sketch":
        plane = _plane(f["plane"])
        return _extrude_region(plane * sketch_region(f["profiles"]), f, diag)
    if op == "extrude":
        plane = _plane(f["plane"])
        return _extrude_region(plane * _sketch(f["sketch"]), f, diag)
    if op == "revolve":
        plane = _plane(f["plane"])
        region = plane * sketch_region(f["profiles"])
        angle = float(f.get("angle", 360))
        if not 0 < angle <= 360:
            raise ValueError("revolve angle must be between 0 and 360 degrees")
        return revolve(region, axis=_sketch_axis(plane, f["axis"]), revolution_arc=angle)
    if op == "sweep":
        prof, path = f["_profile"], f["_path"]
        face = _plane(prof["plane"]) * _sketch_face(prof, "sweep profile")
        return sweep(face, path=_path_wire(path), transition=Transition.RIGHT)
    if op == "loft":
        sections = [_plane(s["plane"]) * _sketch_face(s, "loft section", single=True) for s in f["_sections"]]
        return loft(sections, ruled=bool(f.get("ruled")))
    if op == "hole":
        n = _v(f["normal"]).normalized()
        depth = float(f["depth"]) if f.get("depth") else diag * 2
        if f.get("place"):
            return [_hole_tool(c, n, f, depth) for c in hole_centres(f["_part"], f)]
        point = _v(f["point"])
        if f.get("ref_bbox") and f.get("_part") is not None and not faces_near(f["_part"], point, normal=n):
            # the body changed size: carry the hole with it (if no face is found, keep the stored point)
            for q in _remaps(point, f["ref_bbox"], _bbox6(f["_part"])):
                if faces_near(f["_part"], q, normal=n):
                    f = {**f, "center": list(_v(f["center"]) + (q - point)) if f.get("center") else None}
                    point = q
                    break
        tool = _hole_tool(point, n, f, depth)
        count = int(f.get("count", 1))
        if count > 1 and f.get("pattern") == "circular":
            ax = Axis(_v(f["center"]), n)
            return [tool.rotate(ax, 360.0 * i / count) for i in range(count)]
        if count > 1:
            step = _v(f.get("step", (0, 0, 0)))
            return [Location(step * i) * tool for i in range(count)]
        return tool
    raise ValueError(f"operation {op!r} has no tool body")


def _hole_tool(centre: Vector, n: Vector, f: dict[str, Any], depth: float) -> Any:
    """Drill body of one hole whose top centre is on the face: plain, counterbored or countersunk."""
    plane = Plane(origin=centre, z_dir=n)
    top = (Align.CENTER, Align.CENTER, Align.MAX)
    d = float(f["d"])
    tool = plane * Cylinder(d / 2, depth, align=top)
    if f.get("cbore"):
        tool = tool + plane * Cylinder(float(f["cbore"]["d"]) / 2, float(f["cbore"]["depth"]), align=top)
    elif f.get("csk"):
        dk, ang = float(f["csk"]["d"]), math.radians(float(f["csk"].get("angle", 90)))
        h = (dk - d) / 2 / math.tan(ang / 2)
        tool = tool + plane * Cone(d / 2, dk / 2, h, align=top)
    return tool


def _xdir_for(n: Vector) -> Vector:
    """Sketch x direction for a face normal (same convention as the app's sketcher)."""
    if abs(n.Z) > 0.9:
        return Vector(1, 0, 0)
    return Vector(n.Y, -n.X, 0).normalized()


def hole_centres(part: Any, f: dict[str, Any]) -> list[Vector]:
    """Hole Wizard placement on a face, measured from the face's boundary (its extent along the sketch x/y
    directions): `corners` = four holes `dx` from the left/right and `dy` from the bottom/top edges; `points` =
    holes at (x, y) from the face's lower-left corner. Re-evaluated on every rebuild, so the holes follow the face."""
    if part is None:
        raise ValueError("holes need an existing solid")
    pl = f["place"]
    n = _v(f["normal"]).normalized()
    face = _resolve_face(part, pl["face"], f.get("ref_bbox"), "the face the holes are placed on")[0]
    frame = Plane(origin=_v(pl["face"]["point"]), x_dir=_v(pl["x_dir"]) if pl.get("x_dir") else _xdir_for(n), z_dir=n)
    local = frame.to_local_coords(face).bounding_box()
    x0, y0, x1, y1 = local.min.X, local.min.Y, local.max.X, local.max.Y
    if pl["mode"] == "corners":
        dx, dy = float(pl["dx"]), float(pl["dy"])
        if 2 * dx >= x1 - x0 or 2 * dy >= y1 - y0:
            raise ValueError(f"the holes don't fit: the face is {x1 - x0:.1f} × {y1 - y0:.1f} mm, so the edge distances "
                             f"must be under {(x1 - x0) / 2:.1f} and {(y1 - y0) / 2:.1f} mm")
        uv = [(x0 + dx, y0 + dy), (x1 - dx, y0 + dy), (x1 - dx, y1 - dy), (x0 + dx, y1 - dy)]
    else:
        uv = [(x0 + float(u), y0 + float(v)) for u, v in pl["pts"]]
    # the face plane may sit at a different height than the stored pick (the body changed): project onto it
    origin = _v(face.center())
    z_shift = (origin - frame.origin).dot(n)
    return [Vector(frame.from_local_coords(p)) + n * z_shift for p in uv]


def _sketch_face(sk: dict[str, Any], what: str, single: bool = False) -> Any:
    """Region of a sketch node's closed profiles (holes allowed unless `single`)."""
    if not sk.get("profiles"):
        raise ValueError(f"the {what} sketch '{sk.get('name', '')}' has no closed profile")
    region = sketch_region(sk["profiles"])
    if single and len(region.faces()) != 1:
        raise ValueError(f"each {what} must be one closed profile ('{sk.get('name', '')}' has several)")
    return region


def _path_wire(sk: dict[str, Any]) -> Any:
    """Sweep path: the sketch's one open chain of lines/arcs, or its one closed loop."""
    plane = _plane(sk["plane"])
    chains = sk.get("chains") or []
    if len(chains) > 1:
        raise ValueError(f"the path sketch '{sk.get('name', '')}' must be one connected chain of lines/arcs")
    if chains:
        return plane * Wire(_seg_edges(chains[0])[0])
    loops = sk.get("profiles") or []
    if len(loops) != 1:
        raise ValueError(f"the path sketch '{sk.get('name', '')}' needs one connected chain or one closed loop")
    lp = loops[0]
    if lp["kind"] == "circle":
        return plane * Wire([Pos(float(lp["cx"]), float(lp["cy"])) * Edge.make_circle(float(lp["r"]))])
    return plane * Wire(_seg_edges(lp["segs"])[0])


def _with_sketches(f: dict[str, Any], sketches: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Attach the sketch nodes a sweep/loft uses (resolved, on their current planes) for this build."""
    def get(i: Any, role: str) -> dict[str, Any]:
        sk = sketches.get(str(i))
        if sk is None:
            raise ValueError(f"its {role} sketch is missing (deleted?)")
        return sk
    if f["op"] == "sweep":
        return {**f, "_profile": get(f.get("profile"), "profile"), "_path": get(f.get("path"), "path")}
    secs = f.get("sections") or []
    if len(secs) < 2:
        raise ValueError("a loft needs at least two section sketches")
    return {**f, "_sections": [get(i, "section") for i in secs]}


def _is_cut(f: dict[str, Any]) -> bool:
    return f["op"] == "hole" or f.get("mode") == "cut"


def _apply_tool(part: Any, tool: Any, cut: bool) -> Any:
    for t in tool if isinstance(tool, list) else [tool]:
        if part is None:
            if cut:
                raise ValueError("a cut needs an existing solid; start the part with a boss or revolve")
            part = t
        else:
            part = part - t if cut else part + t
    return part


def _moved(tool: Any, fn: Any) -> Any:
    return [fn(t) for t in tool] if isinstance(tool, list) else fn(tool)


def pattern_instances(tool: Any, f: dict[str, Any]) -> list[Any]:
    """Copies 1..count-1 of a tool body for a linear or circular feature pattern (the original is copy 0)."""
    count = int(f["count"])
    out = []
    if f.get("kind") == "circular":
        ax = Axis(_v(f["axis"]["origin"]), _v(f["axis"]["dir"]))
        total = float(f.get("angle", 360))
        step = total / count if abs(total - 360) < 1e-9 else total / max(count - 1, 1)
        for i in range(1, count):
            out.append(_moved(tool, lambda t, a=step * i: t.rotate(ax, a)))
    else:
        step = _v(f["step"])
        for i in range(1, count):
            out.append(_moved(tool, lambda t, k=i: Location(step * k) * t))
    return out


def _single_solid(part: Any, what: str) -> Any:
    sols = list(part.solids())
    if len(sols) != 1:
        raise ValueError(f"{what} works on a single solid body")
    return sols[0]


def _draft(part: Any, f: dict[str, Any]) -> Any:
    """Draft the picked faces by `angle` degrees about the neutral plane. The pull direction points into the part
    from the neutral face (so a positive angle narrows the part away from it); `reverse` flips it."""
    solid = _single_solid(part, "Draft")
    n = _v(f["neutral"]["normal"]).normalized() * (1.0 if f.get("reverse") else -1.0)
    neutral = Plane(origin=_v(f["neutral"]["point"]), z_dir=n)
    faces = []
    for fc in f["faces"]:
        found = _resolve_face(solid, fc, f.get("ref_bbox"), "a face to draft")
        faces += [x for x in found if x not in faces]
    try:
        return solid.draft(faces, neutral, float(f["angle"]))
    except Exception as e:  # OCCT reports a failed draft with a bare exception
        raise ValueError("the draft could not be applied to these faces (try a smaller angle, or planar/cylindrical "
                         "faces that meet the neutral plane)") from e


def _xy(v: Vector) -> tuple[float, float]:
    return (v.X, v.Y)


def _seg_edges(segs: list[dict[str, Any]]) -> tuple[list[Any], Vector, Vector, Vector, Vector]:
    """2D edges of an ordered open chain plus its start point/tangent (pointing backwards) and end point/tangent."""
    def tangent(s: dict[str, Any], at_end: bool) -> Vector:
        a, b = Vector(*s["a"], 0), Vector(*s["b"], 0)
        if s["type"] != "arc":
            return (b - a).normalized()
        m = Vector(*s["m"], 0)
        ax, ay, mx, my, bx, by = a.X, a.Y, m.X, m.Y, b.X, b.Y
        d = 2 * (ax * (my - by) + mx * (by - ay) + bx * (ay - my))
        ux = ((ax * ax + ay * ay) * (my - by) + (mx * mx + my * my) * (by - ay) + (bx * bx + by * by) * (ay - my)) / d
        uy = ((ax * ax + ay * ay) * (bx - mx) + (mx * mx + my * my) * (ax - bx) + (bx * bx + by * by) * (mx - ax)) / d
        c = Vector(ux, uy, 0)
        ccw = (m - a).cross(b - m).Z > 0
        p = b if at_end else a
        r = p - c
        t = Vector(-r.Y, r.X, 0) if ccw else Vector(r.Y, -r.X, 0)
        return t.normalized()
    edges = []
    for s in segs:
        a, b = (float(s["a"][0]), float(s["a"][1])), (float(s["b"][0]), float(s["b"][1]))
        edges.append(ThreePointArc(a, (float(s["m"][0]), float(s["m"][1])), b) if s["type"] == "arc" else Line(a, b))
    return (edges, Vector(*segs[0]["a"], 0), tangent(segs[0], False), Vector(*segs[-1]["b"], 0), tangent(segs[-1], True))


def _rib(part: Any, f: dict[str, Any], diag: float) -> Any:
    """Rib from an open sketch profile: the region between the profile (extended along its end tangents) and the body,
    `t` thick symmetric about the sketch plane, in the sketch plane. The side that is closed off by the body is used
    (`flip` tries the other side first)."""
    plane = _plane(f["plane"])
    t = float(f["t"])
    bb = part.bounding_box()
    big = diag * 4
    for chain in f["chains"]:
        edges, p0, t0, p1, t1 = _seg_edges(chain)
        e0, e1 = p0 - t0 * big, p1 + t1 * big
        chord = (e1 - e0).normalized()
        left = Vector(-chord.Y, chord.X, 0)
        mid_seg = chain[len(chain) // 2]
        mid = Vector(*mid_seg["m"], 0) if mid_seg["type"] == "arc" else (Vector(*mid_seg["a"], 0) + Vector(*mid_seg["b"], 0)) * 0.5
        added = None
        for side in ((-1.0, 1.0) if f.get("flip") else (1.0, -1.0)):
            n = left * side
            loop = [Line(_xy(e0), _xy(p0)), *edges, Line(_xy(p1), _xy(e1)),
                    Line(_xy(e1), _xy(e1 + n * big)),
                    Line(_xy(e1 + n * big), _xy(e0 + n * big)),
                    Line(_xy(e0 + n * big), _xy(e0))]
            try:
                region = Face(Wire(loop))
            except Exception:  # noqa: BLE001,S112 - a self-crossing closure on this side; try the other one
                continue
            slab = extrude(plane * region, amount=t / 2, both=True)
            probe = plane.from_local_coords(_xy(mid + n * min(t, 0.05)))
            pieces = sorted((slab - part).solids(), key=lambda s: s.distance_to(Vector(probe)))
            if not pieces or pieces[0].distance_to(Vector(probe)) > 1e-6:
                continue
            pb = pieces[0].bounding_box()
            tol = t + 1e-6
            inside = (pb.min.X >= bb.min.X - tol and pb.min.Y >= bb.min.Y - tol and pb.min.Z >= bb.min.Z - tol
                      and pb.max.X <= bb.max.X + tol and pb.max.Y <= bb.max.Y + tol and pb.max.Z <= bb.max.Z + tol)
            if inside:
                added = pieces[0]
                break
        if added is None:
            raise ValueError("the rib profile isn't closed off by the body on either side (the profile, extended along "
                             "its ends, must run between walls of the part)")
        part = part + added
    return part


def _sources(f: dict[str, Any], done: dict[str, dict[str, Any]] | None, verb: str) -> list[dict[str, Any]]:
    """Earlier, unsuppressed tool features a pattern or mirror refers to (by id)."""
    sources = [(done or {}).get(str(i)) for i in f.get("source", [])]
    if not sources or any(s is None for s in sources):
        raise ValueError(f"a {verb} feature is missing, suppressed or comes later in the tree")
    for src in sources:
        if src["op"] not in TOOL_OPS:
            raise ValueError(f"'{src.get('name', src['op'])}' can't be {verb} (bosses, cuts, revolves, sweeps, lofts, holes)")
    return [s for s in sources if s is not None]


def _op(part: Any, f: dict[str, Any], diag: float, done: dict[str, dict[str, Any]] | None = None) -> Any:
    op = f["op"]
    if op in NON_GEOMETRIC:
        return part
    if part is None and op not in BASE_OPS:
        raise ValueError("this feature needs an existing solid; start the part with a boss or revolve")
    if op in TOOL_OPS:
        axes = _hole_axes(part, f) if op == "hole" and f.get("thread") else None
        part = _apply_tool(part, _tool({**f, "_part": part} if op == "hole" else f, diag), _is_cut(f))
        if axes:
            _record_thread(f, f["thread"], axes)
        return part
    if op == "thread":
        return _cosmetic_thread(part, f)
    if op in SHEET_OPS:
        return _sheet_op(part, f)
    if op == "pattern":
        for src in _sources(f, done, "patterned"):
            axes = _hole_axes(part, src) if src["op"] == "hole" and src.get("thread") else None
            for inst in pattern_instances(_tool({**src, "_part": part} if src["op"] == "hole" else src, diag), f):
                part = _apply_tool(part, inst, _is_cut(src))
            if axes:
                _record_thread(f, src["thread"],
                               [a for k in range(1, int(f["count"])) for a in _pattern_axes(axes, f, k)])
        return part
    if op == "fillet":
        edges = _resolve_edges(part, f)
        r = float(f["r"])
        try:
            return fillet(edges, r)
        except Exception as e:  # OCCT: "Failed creating a fillet ..." — say what fits instead
            raise ValueError(_too_large(part, edges, r)) from e
    if op == "chamfer":
        edges = _resolve_edges(part, f)
        try:
            return chamfer(edges, float(f["d"]))
        except Exception as e:
            raise ValueError(f"a {float(f['d']):g} mm chamfer doesn't fit on the selected edge(s); try a smaller "
                             "distance or fewer edges") from e
    if op == "shell":
        openings = []
        for fc in f["faces"]:
            openings += _resolve_face(part, fc, f.get("ref_bbox"), "a face to remove")
        try:
            return offset(part, amount=-float(f["t"]), openings=openings)
        except Exception as e:
            raise ValueError(f"a {float(f['t']):g} mm wall can't be made here; try a thinner wall") from e
    if op == "draft":
        return _draft(part, f)
    if op == "rib":
        return _rib(part, f, diag)
    if op == "mirror":
        pl = Plane(origin=_v(f["plane"]["origin"]), z_dir=_v(f["plane"]["normal"]))
        if f.get("source"):  # mirror features: each source's tool body, reflected, added or cut like the original
            for src in _sources(f, done, "mirrored"):
                axes = _hole_axes(part, src) if src["op"] == "hole" and src.get("thread") else None
                part = _apply_tool(part, _moved(_tool({**src, "_part": part} if src["op"] == "hole" else src, diag),
                                                lambda t: t.mirror(pl)), _is_cut(src))
                if axes:
                    _record_thread(f, src["thread"], [_mirror_axis(a, pl) for a in axes])
            return part
        return part + mirror(part, about=pl)
    raise ValueError(f"unknown manual operation {op!r}")


def _too_large(part: Any, edges: list[Any], r: float) -> str:
    """Plain message for a fillet that doesn't fit, with the largest radius that does (when it can be found)."""
    msg = f"R{r:g} mm is too large for the selected edge(s)"
    try:
        sols = list(part.solids())
        if len(sols) == 1:
            m = sols[0].max_fillet(edges, tolerance=0.05, max_iterations=12)
            if m > 0.01:
                return f"{msg}; the largest radius that fits is about {math.floor(m * 10) / 10:g} mm"
    except Exception:  # noqa: BLE001,S110 - the hint is optional
        pass
    return f"{msg}; try a smaller radius"


def plain(e: BaseException) -> str:
    """A kernel or validation failure in plain engineering words (never exception or function names)."""
    if isinstance(e, ValueError) and str(e):
        return str(e)
    return "the geometry kernel could not compute this feature with these values; try a smaller size or another selection"


def _diag(part: Any, features: list[dict[str, Any]]) -> float:
    """Length that is 'through all' for this part."""
    if part is not None:
        bb = part.bounding_box()
        return math.sqrt(bb.size.X ** 2 + bb.size.Y ** 2 + bb.size.Z ** 2) or 100.0
    ext = 0.0  # hand-modelled part: size from the sketches' extent
    for f in features:
        for c in (f.get("plane") or {}).get("origin") or f.get("point") or []:
            ext = max(ext, abs(float(c)))
        for ch in f.get("chains", []) or []:
            for sg in ch:
                for u, v in (sg["a"], sg["b"]):
                    ext = max(ext, abs(float(u)), abs(float(v)))
        for pr in f.get("profiles", []):
            r = float(pr.get("r", 0))
            pts = [(pr.get("cx", 0), pr.get("cy", 0))] if pr.get("kind") == "circle" else [sg["a"] for sg in pr.get("segs", [])]
            for u, v in pts:
                ext = max(ext, abs(float(u)) + r, abs(float(v)) + r)
        ext = max(ext, float(f.get("distance") or 0))
    return max(4 * ext, 100.0)


def apply_manual(part: Any, features: list[dict[str, Any]]) -> Any:
    """Apply user-authored manual features in order; suppressed ones are skipped. `part` may be None for a part
    modelled entirely by hand: the first boss or revolve then creates the body."""
    if not features:
        return part
    diag = _diag(part, features)
    done: dict[str, dict[str, Any]] = {}
    # Reference planes resolve from their own numbers, independent of tree order. A sketch attached to one
    # (plane_ref) follows it; if the plane was deleted, the sketch keeps the placement it had.
    planes = {str(f.get("id", "")): ref_plane(f) for f in features if f["op"] == "plane"}
    sketches = {str(f.get("id", "")): ({**f, "plane": planes[str(f["plane_ref"])]} if f.get("plane_ref") in planes else f)
                for f in features if f["op"] == "sketch2d"}
    for f in features:
        if f.get("suppressed") or f.get("rolled_back"):  # rolled back: below the rollback bar
            continue
        if f["op"] in NON_GEOMETRIC:
            continue
        if f.get("plane_ref") in planes:
            f = {**f, "plane": planes[str(f["plane_ref"])]}
        name = str(f.get("name") or f["op"])
        try:
            if f["op"] in SKETCH_USERS:
                f = _with_sketches(f, sketches)
            part = _op(part, f, diag, done)
        except Exception as e:  # noqa: BLE001 - a rebuild error flags the feature; the rest of the tree still builds
            msg = plain(e)
            _STATE["manual_errors"].append({"id": str(f.get("id", "")), "name": name, "op": f["op"], "error": msg})
            _STATE["log"].append({"name": name, "kind": "manual", "keys": set(), "error": msg,
                                  "params": {"op": f["op"], "id": str(f.get("id", ""))}})
            continue
        done[str(f.get("id", ""))] = f
        th = f.get("thread") if isinstance(f.get("thread"), dict) else {}
        extra = {"thread": str(th["designation"])} if th.get("designation") else {}
        feature(name, part, kind="manual", op=f["op"], id=str(f.get("id", "")), **extra)
        _STATE["manual"] += 1
    if part is None and _STATE["manual_errors"]:  # nothing could be built: report why
        first = _STATE["manual_errors"][0]
        raise ValueError(f"manual feature '{first['name']}' failed: {first['error']}")
    return part


# ----------------------------------------------------------------------------- cosmetic threads (CAD-027)
def _rotate(p: Vector, origin: Vector, axis: Vector, deg: float) -> Vector:
    """Rodrigues rotation of a point about an axis through ``origin``."""
    k = axis.normalized()
    v = p - origin
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return origin + v * c + k.cross(v) * s + k * (k.dot(v) * (1 - c))


def _hole_axes(part: Any, f: dict[str, Any]) -> list[tuple[Vector, Vector]]:
    """(opening centre, drill direction into the material) of every hole a hole feature drills (before the cut)."""
    n = _v(f["normal"]).normalized()
    if f.get("place"):
        return [(c, -n) for c in hole_centres(part, f)]
    point = _v(f["point"])
    if f.get("ref_bbox") and part is not None and not faces_near(part, point, normal=n):
        for q in _remaps(point, f["ref_bbox"], _bbox6(part)):
            if faces_near(part, q, normal=n):
                point = q
                break
    count = int(f.get("count", 1))
    if count > 1 and f.get("pattern") == "circular":
        c0 = _v(f["center"])
        return [(_rotate(point, c0, n, 360.0 * i / count), -n) for i in range(count)]
    if count > 1:
        step = _v(f.get("step", (0, 0, 0)))
        return [(point + step * i, -n) for i in range(count)]
    return [(point, -n)]


def _pattern_axes(axes: list[tuple[Vector, Vector]], f: dict[str, Any], k: int) -> list[tuple[Vector, Vector]]:
    """Copy ``k`` of a feature pattern applied to hole axes (the same transforms as ``pattern_instances``)."""
    count = int(f["count"])
    if f.get("kind") == "circular":
        o, d = _v(f["axis"]["origin"]), _v(f["axis"]["dir"])
        total = float(f.get("angle", 360))
        a = (total / count if abs(total - 360) < 1e-9 else total / max(count - 1, 1)) * k
        return [(_rotate(p, o, d, a), _rotate(p + n, o, d, a) - _rotate(p, o, d, a)) for p, n in axes]
    step = _v(f["step"])
    return [(p + step * k, n) for p, n in axes]


def _mirror_axis(a: tuple[Vector, Vector], pl: Plane) -> tuple[Vector, Vector]:
    p, n = a
    z = pl.z_dir.normalized()

    def refl(v: Vector) -> Vector:
        return v - z * (2 * (v - pl.origin).dot(z))

    return refl(p), refl(p + n) - refl(p)


def _r6(x: float) -> float:
    v = round(float(x), 6)
    return 0.0 if v == 0 else v


def _record_thread(f: dict[str, Any], t: dict[str, Any], axes: list[tuple[Vector, Vector]]) -> None:
    """One thread record per feature: the designation and every instance (opening point + direction into it)."""
    if not axes:
        return
    _STATE["threads"].append({
        "feature": str(f.get("id", "")), "name": str(f.get("name") or f["op"]),
        **{k: t[k] for k in ("size", "pitch", "cls", "internal", "depth", "designation", "series", "major", "minor")
           if k in t},
        "instances": [{"p": [_r6(p.X), _r6(p.Y), _r6(p.Z)], "dir": [_r6(n.X), _r6(n.Y), _r6(n.Z)]} for p, n in axes]})


def _cosmetic_thread(part: Any, f: dict[str, Any]) -> Any:
    """Cosmetic thread on a picked cylindrical face (a hole: internal; a shaft or boss: external). It starts at the
    end of the face nearest the pick and runs ``depth`` (default: the whole face). The solid is unchanged."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_Cylinder

    from aicad import threads as _threads

    pick = _v(f["face"]["point"])
    cyl = None
    for fc in _resolve_face(part, {"point": f["face"]["point"]}, f.get("ref_bbox"), "the cylindrical face"):
        ad = BRepAdaptor_Surface(fc.wrapped)
        if ad.GetType() == GeomAbs_Cylinder:
            cyl = (fc, ad)
            break
    if cyl is None:
        raise ValueError("a cosmetic thread goes on a cylindrical face (a hole or a shaft)")
    fc, ad = cyl
    c = ad.Cylinder()
    loc, d = c.Axis().Location(), c.Axis().Direction()
    o, dv = Vector(loc.X(), loc.Y(), loc.Z()), Vector(d.X(), d.Y(), d.Z())
    _u0, _u1, v0, v1 = BRepTools.UVBounds_s(fc.wrapped)
    a, b = o + dv * v0, o + dv * v1
    start, end = (b, a) if abs((pick - b).dot(dv)) < abs((pick - a).dot(dv)) else (a, b)
    radius = c.Radius()
    # internal when the material lies outside the cylinder: a point just beyond the radius is inside the solid
    x = dv.cross(Vector(1, 0, 0)) if abs(dv.X) < 0.9 else dv.cross(Vector(0, 1, 0))
    probe = (start + end) * 0.5 + x.normalized() * (radius + min(0.05, radius * 0.1))
    internal = bool(part.is_inside(probe))
    t = _threads.resolve(f["thread"], internal=internal, bore=round(2 * radius, 6),
                         length=round((end - start).length, 6))
    _record_thread(f, t, [(start, (end - start).normalized())])
    return part


def thread(part: Any, point: Any, designation: str, depth: float | None = None, cls: str | None = None,
           name: str = "Cosmetic thread") -> Any:
    """Model-script helper: a cosmetic thread on the cylindrical face at ``point`` (hole or shaft). Returns ``part``
    unchanged; the thread is metadata for drawings and the STEP export."""
    _cosmetic_thread(part, {"op": "thread", "id": name, "name": name, "face": {"point": list(_v(point))},
                            "thread": {"designation": designation, "depth": depth, "cls": cls}})
    return part


def threads() -> list[dict[str, Any]]:
    """Cosmetic threads recorded in the last build, in feature order."""
    return [dict(t) for t in _STATE.get("threads") or []]


def manual_errors() -> list[dict[str, Any]]:
    """Manual features that failed to rebuild in the last build (rebuild errors shown in the feature tree)."""
    return list(_STATE.get("manual_errors") or [])


# ----------------------------------------------------------------------------- sheet metal (CAD-026)
SHEET_OPS = {"sm_base", "sm_flange", "sm_hem", "sm_jog"}


def sheet() -> Any:
    """The sheet-metal model of the last build (None for a part that is not sheet metal)."""
    return _STATE.get("sheet")


def _sheet_frame(spec: dict[str, Any], t: float, reverse: bool) -> Location:
    loc = Location(_plane(spec))
    return loc * Pos(0, 0, -t) if reverse else loc


def _sheet_edge(part: Any, f: dict[str, Any]) -> dict[str, Any]:
    """The sheet edge a flange or hem was picked on, carried along with the body's size like other picks."""
    sh = _STATE.get("sheet")
    if sh is None:
        raise ValueError("an edge flange needs a sheet-metal part: start it with a Base Flange")
    ref = f.get("edge_ref") or {}
    direction = ref.get("dir") if ref.get("kind") == "line" else None
    p = _v(f["edge"])
    e = _sm.find_edge(sh, p, direction)
    if e is None and f.get("ref_bbox") and part is not None:
        for q in _remaps(p, f["ref_bbox"], _bbox6(part)):
            e = _sm.find_edge(sh, q, direction)
            if e is not None:
                break
    if e is None:
        raise ValueError("the picked edge was not found: pick a long edge on the top or bottom face of the sheet "
                         "(the geometry may have changed)")
    return e


def _sheet_op(part: Any, f: dict[str, Any]) -> Any:
    op = f["op"]
    name = str(f.get("name") or op)
    if op == "sm_base":
        if part is not None:
            raise ValueError("a base flange starts a sheet-metal part, so it must be the first solid feature")
        t = float(f["t"])
        region = sketch_region(f["profiles"])
        rel = f.get("relief") or {}
        cor = f.get("corner") or {}
        sh, solid = _sm.base(region, _sheet_frame(f["plane"], t, bool(f.get("reverse"))), t,
                             float(f["r"]) if f.get("r") is not None else None, float(f.get("k", 0.44)),
                             str(rel.get("type", "rect")), float(rel.get("ratio", 0.5)), name,
                             str(cor.get("type", "closed")), float(cor.get("gap", 0.2)))
        _STATE["sheet"] = sh
        return solid
    e = _sheet_edge(part, f)
    if op == "sm_jog":
        sh, part = _sm.jog(_STATE["sheet"], part, f["edge"], float(f["distance"]), float(f["offset"]),
                           float(f.get("angle", 90)), float(f["r"]) if f.get("r") is not None else None,
                           bool(f.get("flip")), name, edge=e)
        _STATE["sheet"] = sh
        return part
    if op == "sm_hem":
        gap = float(f.get("gap") or _STATE["sheet"].t)
        sh, part = _sm.flange(_STATE["sheet"], part, f["edge"], float(f["length"]), 180.0, gap / 2,
                              bool(f.get("flip")), str(f.get("position", "inside")), "tangent", (0.0, 0.0), name,
                              kind="hem", edge=e)
    else:
        ins = f.get("inset") or [0, 0]
        sh, part = _sm.flange(_STATE["sheet"], part, f["edge"], float(f["length"]), float(f.get("angle", 90)),
                              float(f["r"]) if f.get("r") is not None else None, bool(f.get("flip")),
                              str(f.get("position", "inside")), str(f.get("length_ref", "outer")),
                              (float(ins[0]), float(ins[1])), name, edge=e)
    _STATE["sheet"] = sh
    return part


def base_flange(points: list[Any] | None = None, *, thickness: float, width: float | None = None,
                height: float | None = None, radius: float | None = None, k: float = 0.44, plane: Any = None,
                relief: str = "rect", relief_ratio: float = 0.5, reverse: bool = False,
                name: str = "Base-Flange", corner: str = "closed", corner_gap: float = 0.2) -> Any:
    """Model-script helper: start a sheet-metal part. The profile is a polygon ``points`` [(u, v), ...] or a
    ``width`` × ``height`` rectangle centred on the plane origin, on ``plane`` (a build123d Plane, default XY),
    thickened by ``thickness`` along the plane normal (``reverse`` = the other way). ``radius`` is the default
    inside bend radius (default = thickness), ``k`` the K-factor. ``corner`` ("closed" / "open") and
    ``corner_gap`` say how flanges on adjacent edges meet (corner reliefs are cut automatically). Returns the part
    (recorded as a feature)."""
    pl = plane if plane is not None else Plane.XY
    if points:
        region = Polygon(*[(float(u), float(v)) for u, v in points], align=None)
    elif width and height:
        region = Rectangle(float(width), float(height))
    else:
        raise ValueError("base_flange needs points or width and height")
    loc = Location(pl) * Pos(0, 0, -float(thickness)) if reverse else Location(pl)
    sh, solid = _sm.base(region.faces()[0] if len(region.faces()) == 1 else region, loc, float(thickness), radius,
                         k, relief, relief_ratio, name, corner, corner_gap)
    _STATE["sheet"] = sh
    return feature(name, solid)


def edge_flange(part: Any, edge_point: Any, length: float, angle: float = 90.0, radius: float | None = None,
                flip: bool = False, position: str = "inside", length_ref: str = "outer",
                inset: tuple[float, float] = (0.0, 0.0), name: str = "Edge-Flange") -> Any:
    """Model-script helper: an edge flange on the straight sheet edge through ``edge_point`` (a point on a top or
    bottom edge of the sheet). It bends towards that face's side (``flip`` reverses it). ``position``: "inside"
    (material inside), "outside" or "bend_outside"; ``length_ref``: "outer" (from the outer virtual sharp) or
    "tangent"; ``inset`` shortens it from the edge ends (reliefs are cut)."""
    if name in _STATE.get("suppressed", set()):
        return feature(name, part)
    sh, part = _sm.flange(_STATE["sheet"] if _STATE.get("sheet") else _no_sheet(), part, edge_point, length, angle,
                          radius, flip, position, length_ref, inset, name)
    _STATE["sheet"] = sh
    return feature(name, part)


def hem(part: Any, edge_point: Any, length: float, gap: float | None = None, flip: bool = False,
        position: str = "inside", name: str = "Hem") -> Any:
    """Model-script helper: an open hem (180° bend, inside radius gap/2, default gap = thickness) of straight
    ``length`` on the sheet edge through ``edge_point``."""
    if name in _STATE.get("suppressed", set()):
        return feature(name, part)
    sh = _STATE["sheet"] if _STATE.get("sheet") else _no_sheet()
    g = float(gap) if gap is not None else sh.t
    sh, part = _sm.flange(sh, part, edge_point, length, 180.0, g / 2, flip, position, "tangent", (0.0, 0.0), name,
                          kind="hem")
    _STATE["sheet"] = sh
    return feature(name, part)


def jog(part: Any, edge_point: Any, distance: float, offset: float, angle: float = 90.0,
        radius: float | None = None, flip: bool = False, name: str = "Jog") -> Any:
    """Model-script helper: a jog. The sheet between the straight edge through ``edge_point`` and a line
    ``distance`` in from it is raised by ``offset`` (bottom face to bottom face; ``flip`` lowers it) through two
    opposite bends of ``angle`` (≤ 90°). Add jogs before flanges on the end that moves."""
    if name in _STATE.get("suppressed", set()):
        return feature(name, part)
    sh, part = _sm.jog(_STATE["sheet"] if _STATE.get("sheet") else _no_sheet(), part, edge_point, distance, offset,
                       angle, radius, flip, name)
    _STATE["sheet"] = sh
    return feature(name, part)


def _no_sheet() -> Any:
    raise ValueError("an edge flange or hem needs a sheet-metal part: start it with base_flange")


# High-level standard features (PS-03): gears, stepped shafts, keyways, Hole Wizard holes and bolt circles.
from aicad.fw_std import (  # noqa: F401  (fw_std uses fw.feature, so it is imported once fw is defined)
    DIN6885_SOURCE,
    bolt_circle,
    cross_hole,
    cross_hole_volume,
    din6885,
    gusset,
    hole,
    hole_spec,
    holes_at,
    hub_keyway,
    machined,
    machined_volume,
    meta,
    plate,
    revolved,
    revolved_volume,
    shaft_keyway,
    spur_gear,
    stepped_shaft,
)
