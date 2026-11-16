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
    Circle,
    Cylinder,
    Location,
    Plane,
    Polygon,
    Pos,
    Rectangle,
    Vector,
    chamfer,
    extrude,
    fillet,
)

_STATE: dict[str, Any] = {"log": [], "manual": 0}


def reset() -> None:
    _STATE["log"] = []
    _STATE["manual"] = 0


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


def feature(name: str, part: Any, kind: str = "feature", **params: Any) -> Any:
    """Record that `part` is the state after feature `name`. Returns `part` unchanged."""
    try:
        keys = {face_key(f) for f in part.faces()}
    except Exception:  # noqa: BLE001 - never break a model because of bookkeeping
        keys = set()
    clean = {k: v for k, v in params.items() if isinstance(v, (int, float, str, bool))}
    _STATE["log"].append({"name": str(name), "kind": kind, "keys": keys, "params": clean})
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


def _op(part: Any, f: dict[str, Any], diag: float) -> Any:
    op = f["op"]
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
    if op == "hole":
        n = _v(f["normal"]).normalized()
        depth = float(f["depth"]) if f.get("depth") else diag * 2
        plane = Plane(origin=_v(f["point"]), z_dir=n)
        tool = plane * Cylinder(float(f["d"]) / 2, depth, align=(Align.CENTER, Align.CENTER, Align.MAX))
        count = int(f.get("count", 1))
        if count > 1:
            step = _v(f.get("step", (0, 0, 0)))
            tools = [Location(step * i) * tool for i in range(count)]
            for t in tools:
                part = part - t
            return part
        return part - tool
    if op == "extrude":
        plane = _plane(f["plane"])
        sk = plane * _sketch(f["sketch"])
        d = float(f["distance"])
        if f.get("mode", "add") == "cut":
            return part - extrude(sk, amount=-d)
        return part + extrude(sk, amount=d)
    raise ValueError(f"unknown manual operation {op!r}")


def apply_manual(part: Any, features: list[dict[str, Any]]) -> Any:
    """Apply user-authored manual features in order. Suppressed features are skipped."""
    if not features:
        return part
    bb = part.bounding_box()
    diag = math.sqrt(bb.size.X ** 2 + bb.size.Y ** 2 + bb.size.Z ** 2) or 100.0
    for f in features:
        if f.get("suppressed"):
            continue
        try:
            part = _op(part, f, diag)
        except Exception as e:
            raise ValueError(f"manual feature '{f.get('name', f.get('op'))}' failed: {e}") from e
        feature(str(f.get("name") or f["op"]), part, kind="manual", op=f["op"], id=str(f.get("id", "")))
        _STATE["manual"] += 1
    return part
