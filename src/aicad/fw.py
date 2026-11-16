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
    Face,
    Line,
    Location,
    Plane,
    Polygon,
    Pos,
    Rectangle,
    ThreePointArc,
    Vector,
    Wire,
    chamfer,
    extrude,
    fillet,
    mirror,
    offset,
    revolve,
)

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


TOOL_OPS = {"sketch", "extrude", "revolve", "hole"}
BASE_OPS = {"sketch", "extrude", "revolve"}  # can create the first solid of a hand-modelled part


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


def _op(part: Any, f: dict[str, Any], diag: float, done: dict[str, dict[str, Any]] | None = None) -> Any:
    op = f["op"]
    if part is None and op not in BASE_OPS:
        raise ValueError("this feature needs an existing solid; start the part with a boss or revolve")
    if op in TOOL_OPS:
        return _apply_tool(part, _tool(f, diag), _is_cut(f))
    if op == "pattern":
        sources = [(done or {}).get(str(i)) for i in f.get("source", [])]
        if not sources or any(s is None for s in sources):
            raise ValueError("a patterned feature is missing, suppressed or comes later in the tree")
        for src in sources:
            if src["op"] not in TOOL_OPS:
                raise ValueError(f"'{src.get('name', src['op'])}' can't be patterned (bosses, cuts, revolves, holes)")
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
    if op == "mirror":
        pl = Plane(origin=_v(f["plane"]["origin"]), z_dir=_v(f["plane"]["normal"]))
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
    for f in features:
        if f.get("suppressed"):
            continue
        try:
            part = _op(part, f, diag, done)
        except Exception as e:
            raise ValueError(f"manual feature '{f.get('name', f.get('op'))}' failed: {e}") from e
        done[str(f.get("id", ""))] = f
        feature(str(f.get("name") or f["op"]), part, kind="manual", op=f["op"], id=str(f.get("id", "")))
        _STATE["manual"] += 1
    return part
