"""Formwright helper library for model scripts (`from aicad import fw`).

- feature(name, part)      record a named design feature (feature tree + face provenance)
- edges_near / faces_near  select topology by location (stable across rebuilds, unlike indices)
- apply_manual(part, ops)  apply user-authored manual features (fillet, chamfer, hole, sketch extrude/cut)

State is per build: the runner calls reset() before executing a script.
"""

from __future__ import annotations

import math
from typing import Any

from build123d import (
    Align,
    Axis,
    Circle,
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

_STATE: dict[str, Any] = {"log": [], "manual": 0, "base": None}


def reset() -> None:
    _STATE["log"] = []
    _STATE["manual"] = 0
    _STATE["last"] = None
    _STATE["suppressed"] = set()


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
        n = f.normal_at(f.center())
        d = n.dot(f.center())
        return ("plane", r(n.X), r(n.Y), r(n.Z), r(d))
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
    """Edges passing within `tol` mm of any of the given points (e.g. picked in the viewer)."""
    pts = [_v(p) for p in points]
    out = []
    for e in part.edges():
        if any(e.distance_to(p) <= tol for p in pts):
            out.append(e)
    return out


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
BASE_OPS = {"sketch", "extrude", "revolve", "sweep", "loft"}  # can create the first solid of a hand-modelled part
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
        plane = Plane(origin=_v(f["point"]), z_dir=n)
        tool = plane * Cylinder(float(f["d"]) / 2, depth, align=(Align.CENTER, Align.CENTER, Align.MAX))
        count = int(f.get("count", 1))
        if count > 1 and f.get("pattern") == "circular":
            ax = Axis(_v(f["center"]), n)
            return [tool.rotate(ax, 360.0 * i / count) for i in range(count)]
        if count > 1:
            step = _v(f.get("step", (0, 0, 0)))
            return [Location(step * i) * tool for i in range(count)]
        return tool
    raise ValueError(f"operation {op!r} has no tool body")


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
        found = faces_near(solid, fc["point"], normal=fc.get("normal"))
        if not found:
            raise ValueError("a face to draft was not found (geometry changed?)")
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
        return _apply_tool(part, _tool(f, diag), _is_cut(f))
    if op == "pattern":
        for src in _sources(f, done, "patterned"):
            for inst in pattern_instances(_tool(src, diag), f):
                part = _apply_tool(part, inst, _is_cut(src))
        return part
    if op == "fillet":
        edges = edges_near(part, f["edges"])
        if not edges:
            raise ValueError("no edges found at the picked locations (geometry changed?)")
        return fillet(edges, float(f["r"]))
    if op == "chamfer":
        edges = edges_near(part, f["edges"])
        if not edges:
            raise ValueError("no edges found at the picked locations (geometry changed?)")
        return chamfer(edges, float(f["d"]))
    if op == "shell":
        openings = []
        for fc in f["faces"]:
            found = faces_near(part, fc["point"], normal=fc.get("normal"))
            if not found:
                raise ValueError("a face to remove was not found (geometry changed?)")
            openings += found
        return offset(part, amount=-float(f["t"]), openings=openings)
    if op == "draft":
        return _draft(part, f)
    if op == "rib":
        return _rib(part, f, diag)
    if op == "mirror":
        pl = Plane(origin=_v(f["plane"]["origin"]), z_dir=_v(f["plane"]["normal"]))
        if f.get("source"):  # mirror features: each source's tool body, reflected, added or cut like the original
            for src in _sources(f, done, "mirrored"):
                part = _apply_tool(part, _moved(_tool(src, diag), lambda t: t.mirror(pl)), _is_cut(src))
            return part
        return part + mirror(part, about=pl)
    raise ValueError(f"unknown manual operation {op!r}")


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
        if f.get("suppressed"):
            continue
        if f["op"] in NON_GEOMETRIC:
            continue
        if f.get("plane_ref") in planes:
            f = {**f, "plane": planes[str(f["plane_ref"])]}
        try:
            if f["op"] in SKETCH_USERS:
                f = _with_sketches(f, sketches)
            part = _op(part, f, diag, done)
        except Exception as e:
            raise ValueError(f"manual feature '{f.get('name', f.get('op'))}' failed: {e}") from e
        done[str(f.get("id", ""))] = f
        feature(str(f.get("name") or f["op"]), part, kind="manual", op=f["op"], id=str(f.get("id", "")))
        _STATE["manual"] += 1
    return part
