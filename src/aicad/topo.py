"""Exact B-rep topology export for the viewer + mass properties.

topo.json (CAD coordinates, millimetres, Z up):
  solids:   [{id, label, faces, volume, center}]
  faces:    [{id, solid, type, area, center, normal?, axis?, radius?, feature?, pos: [x,y,z,...], idx: [i,j,k,...]}]
  edges:    [{id, type, length, pts: [x,y,z,...], faces: [..], center?, radius?, axis?, a?, b?}]
  vertices: [[x,y,z], ...]
Faces carry their own tessellation so the viewer can pick, highlight and section *real* faces, and edges are the
true model edges (used for CAD wireframe and snapping), not mesh triangles.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from build123d import Edge, Face, Shape, Vertex
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp
from OCP.GeomAbs import (
    GeomAbs_Circle,
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Line,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_Torus,
)
from OCP.GProp import GProp_GProps

R = 4  # decimals for coordinates


def _r(v: float, n: int = R) -> float:
    return round(float(v), n)


def _vec(v: Any) -> list[float]:
    return [_r(v.X), _r(v.Y), _r(v.Z)]


def _dir(d: Any) -> list[float]:
    return [_r(d.X(), 6), _r(d.Y(), 6), _r(d.Z(), 6)]


def _pnt(p: Any) -> list[float]:
    return [_r(p.X()), _r(p.Y()), _r(p.Z())]


SURF = {GeomAbs_Plane: "plane", GeomAbs_Cylinder: "cylinder", GeomAbs_Cone: "cone", GeomAbs_Sphere: "sphere",
        GeomAbs_Torus: "torus"}


def _face_info(f: Face) -> dict[str, Any]:
    s = BRepAdaptor_Surface(f.wrapped)
    t = s.GetType()
    info: dict[str, Any] = {"type": SURF.get(t, "freeform")}
    if t == GeomAbs_Plane:
        n = f.normal_at(f.center())
        info["normal"] = _vec(n)
    elif t == GeomAbs_Cylinder:
        c = s.Cylinder()
        info["radius"] = _r(c.Radius(), 6)
        info["axis"] = _dir(c.Axis().Direction())
        info["axis_point"] = _pnt(c.Axis().Location())
    elif t == GeomAbs_Cone:
        c = s.Cone()
        info["axis"] = _dir(c.Axis().Direction())
        info["semi_angle_deg"] = _r(math.degrees(c.SemiAngle()), 4)
    elif t == GeomAbs_Sphere:
        info["radius"] = _r(s.Sphere().Radius(), 6)
    return info


def _edge_info(e: Edge, defl: float) -> dict[str, Any]:
    c = BRepAdaptor_Curve(e.wrapped)
    t = c.GetType()
    L = e.length
    info: dict[str, Any] = {"length": _r(L, 6)}
    if t == GeomAbs_Line:
        info["type"] = "line"
        n = 2
    elif t == GeomAbs_Circle:
        circ = c.Circle()
        r = circ.Radius()
        info.update(type="circle", radius=_r(r, 6), center=_pnt(circ.Location()), axis=_dir(circ.Axis().Direction()))
        sweep = L / max(r, 1e-9)
        info["full"] = abs(sweep - 2 * math.pi) < 1e-6
        n = max(8, math.ceil(sweep / (2 * math.pi) * 64))
    else:
        info["type"] = "curve"
        n = max(8, min(400, math.ceil(L / max(defl * 20, 1e-6))))
    pts: list[float] = []
    for i in range(n + 1 if t != GeomAbs_Line else 2):
        u = i / (n if t != GeomAbs_Line else 1)
        pts += _vec(e.position_at(u))
    info["pts"] = pts
    return info


def mass_properties(shape: Shape) -> dict[str, Any]:
    """Volume, surface area, centre of mass and inertia tensor about the centre of mass (density = 1).
    Multiply inertia by density (kg/mm^3) to get kg*mm^2."""
    vp = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, vp)
    sp = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape.wrapped, sp)
    m = vp.MatrixOfInertia()
    inertia = [[_r(m.Value(i, j), 3) for j in (1, 2, 3)] for i in (1, 2, 3)]
    pp = vp.PrincipalProperties()
    i1, i2, i3 = pp.Moments()
    return {"volume_mm3": _r(vp.Mass(), 4), "area_mm2": _r(sp.Mass(), 4), "com_mm": _pnt(vp.CentreOfMass()),
            "inertia_com_mm5": inertia, "principal_mm5": [_r(i1, 3), _r(i2, 3), _r(i3, 3)]}


def body_list(shape: Shape) -> list[tuple[str, Any]]:
    """The bodies of a shape in the order topo.json numbers them (labelled children of an assembly compound, else its
    solids). Face ids in topo.json are positions in ``[f for _, b in body_list(s) for f in b.faces()]``."""
    kids = [c for c in (getattr(shape, "children", None) or ()) if c.solids()]
    return ([(getattr(c, "label", "") or f"Part {i + 1}", c) for i, c in enumerate(kids)]
            if kids else [("", s) for s in (list(shape.solids()) or [shape])])


def export_topology(shape: Shape, path: Path, feature_log: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    bb = shape.bounding_box()
    diag = math.sqrt(bb.size.X ** 2 + bb.size.Y ** 2 + bb.size.Z ** 2) or 1.0
    defl = max(diag * 0.0008, 0.002)

    # face provenance: earliest logged feature whose snapshot contains the face key
    first_feature: dict[tuple[Any, ...], str] = {}
    if feature_log:
        for entry in sorted(feature_log, key=lambda e: e.get("kind") == "blank"):  # blank = residual, lowest priority
            for k in entry["keys"]:
                first_feature.setdefault(k, entry["name"])

    bodies = body_list(shape)
    faces_out: list[dict[str, Any]] = []
    edges_out: list[dict[str, Any]] = []
    edge_ids: dict[Edge, int] = {}
    vert_ids: dict[Vertex, int] = {}
    verts_out: list[list[float]] = []
    solids_out: list[dict[str, Any]] = []
    for si, (body_label, sol) in enumerate(bodies):
        fids = []
        for f in sol.faces():
            fid = len(faces_out)
            fids.append(fid)
            info = _face_info(f)
            vs, tris = f.tessellate(defl, 0.2)
            pos: list[float] = []
            for v in vs:
                pos += _vec(v)
            idx = [i for t in tris for i in t]
            rec = {"id": fid, "solid": si, "area": _r(f.area, 4), "center": _vec(f.center()), **info,
                   "pos": pos, "idx": idx, "edges": []}
            if first_feature:
                from aicad.fw import face_key

                rec["feature"] = first_feature.get(face_key(f))
            for e in f.edges():
                if e not in edge_ids:
                    edge_ids[e] = len(edges_out)
                    er = {"id": edge_ids[e], **_edge_info(e, defl), "faces": []}
                    ends = []
                    for v in e.vertices():
                        if v not in vert_ids:
                            vert_ids[v] = len(verts_out)
                            verts_out.append([_r(v.X), _r(v.Y), _r(v.Z)])
                        ends.append(vert_ids[v])
                    er["verts"] = ends
                    edges_out.append(er)
                eid = edge_ids[e]
                if fid not in edges_out[eid]["faces"]:
                    edges_out[eid]["faces"].append(fid)
                rec["edges"].append(eid)
            faces_out.append(rec)
        label = body_label or getattr(sol, "label", "") or f"Body {si + 1}"
        solids_out.append({"id": si, "label": label, "faces": fids, "volume": _r(sol.volume, 4),
                           "center": _vec(sol.center())})
    data = {"units": "mm", "up": "Z",
            "bbox": [_r(bb.min.X), _r(bb.min.Y), _r(bb.min.Z), _r(bb.max.X), _r(bb.max.Y), _r(bb.max.Z)],
            "solids": solids_out, "faces": faces_out, "edges": edges_out, "vertices": verts_out,
            "features": [{"name": e["name"], "kind": e["kind"], "params": e["params"]} for e in (feature_log or [])]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
    return data
