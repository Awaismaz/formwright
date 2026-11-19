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

from build123d import Face, Shape
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.GeomAbs import (
    GeomAbs_Circle,
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Line,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_Torus,
)
from OCP.gp import gp_Pnt, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

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


_CAST = {TopAbs_FACE: TopoDS.Face, TopAbs_EDGE: TopoDS.Edge, TopAbs_VERTEX: TopoDS.Vertex}


def _subs(shape: Any, kind: Any) -> list[Any]:
    """Unique TopoDS sub-shapes in explorer order, exactly as build123d's faces()/edges()/vertices() list them (first
    position, last occurrence), without wrapping each one in a Python object."""
    out: dict[int, Any] = {}
    cast = _CAST[kind]
    exp = TopExp_Explorer(shape, kind)
    while exp.More():
        item = exp.Current()
        out[hash(item)] = cast(item)
        exp.Next()
    return list(out.values())


def _face_info(f: Any, s: Any, t: Any) -> dict[str, Any]:
    info: dict[str, Any] = {"type": SURF.get(t, "freeform")}
    if t == GeomAbs_Plane:
        from aicad.fw import plane_eq

        nx, ny, nz, _ = plane_eq(f)
        info["normal"] = [_r(nx), _r(ny), _r(nz)]
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


def _face_area_center(f: Any, planar: bool) -> tuple[float, Any]:
    """Area and build123d's Face.center(): the centroid for a planar face, the mid-(u, v) point otherwise."""
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(f, props)
    if planar:
        return props.Mass(), props.CentreOfMass()
    u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
    p, n = gp_Pnt(), gp_Vec()
    BRepGProp_Face(f).Normal(0.5 * (u0 + u1), 0.5 * (v0 + v1), p, n)
    return props.Mass(), p


def _edge_info(e: Any, defl: float) -> dict[str, Any]:
    c = BRepAdaptor_Curve(e)
    t = c.GetType()
    props = GProp_GProps()
    BRepGProp.LinearProperties_s(e, props)
    L = props.Mass()
    info: dict[str, Any] = {"length": _r(L, 6)}
    if t == GeomAbs_Line:
        info["type"] = "line"
        n = 1
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
    # Edge.position_at(u): arc-length fraction along the curve, from the end the edge starts at. Lines and circles are
    # parametrised by length already, so their points are evaluated directly (no abscissa solve per point).
    forward = e.Orientation() != TopAbs_REVERSED
    u0, u1 = c.FirstParameter(), c.LastParameter()
    pts: list[float] = []
    if t in (GeomAbs_Line, GeomAbs_Circle):
        for i in range(n + 1):
            u = i / n if forward else 1 - i / n
            pts += _pnt(c.Value(u0 + (u1 - u0) * u))
    else:
        clen = GCPnts_AbscissaPoint.Length_s(c)
        for i in range(n + 1):
            u = i / n if forward else 1 - i / n
            pts += _pnt(c.Value(GCPnts_AbscissaPoint(c, clen * u, u0).Parameter()))
    info["pts"] = pts
    return info


def _triangles(f: Any) -> tuple[list[float], list[int]]:
    """The face's stored triangulation (the whole shape is meshed once, in parallel, before the face loop)."""
    loc = TopLoc_Location()
    poly = BRep_Tool.Triangulation_s(f, loc)
    if poly is None:
        return [], []
    trsf = loc.Transformation()
    ident = loc.IsIdentity()
    pos: list[float] = []
    for i in range(1, poly.NbNodes() + 1):
        p = poly.Node(i) if ident else poly.Node(i).Transformed(trsf)
        pos += _pnt(p)
    rev = f.Orientation() == TopAbs_REVERSED
    idx: list[int] = []
    for i in range(1, poly.NbTriangles() + 1):
        a, b, c = poly.Triangle(i).Get()
        idx += (a - 1, c - 1, b - 1) if rev else (a - 1, b - 1, c - 1)
    return pos, idx


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
    edge_ids: dict[int, int] = {}  # hash of the TopoDS edge: the identity build123d's Edge hash/eq use (IsSame)
    vert_ids: dict[int, int] = {}
    verts_out: list[list[float]] = []
    solids_out: list[dict[str, Any]] = []
    if not BRepTools.Triangulation_s(shape.wrapped, defl):
        BRepMesh_IncrementalMesh(shape.wrapped, defl, True, 0.2, True)  # Face.tessellate's settings, all faces at once
    key_of = None
    if first_feature:
        from aicad.fw import face_key

        def key_of(f: Any) -> Any:
            return first_feature.get(face_key(Face(f)))

    for si, (body_label, sol) in enumerate(bodies):
        fids = []
        for f in _subs(sol.wrapped, TopAbs_FACE):
            fid = len(faces_out)
            fids.append(fid)
            s = BRepAdaptor_Surface(f)
            t = s.GetType()
            info = _face_info(f, s, t)
            area, ctr = _face_area_center(f, t == GeomAbs_Plane)
            pos, idx = _triangles(f)
            rec = {"id": fid, "solid": si, "area": _r(area, 4), "center": _pnt(ctr), **info,
                   "pos": pos, "idx": idx, "edges": []}
            if key_of is not None:
                rec["feature"] = key_of(f)
            for e in _subs(f, TopAbs_EDGE):
                if BRep_Tool.Degenerated_s(e):  # poles and apexes: build123d's edges() skips them too
                    continue
                h = hash(e)
                if h not in edge_ids:
                    edge_ids[h] = len(edges_out)
                    er = {"id": edge_ids[h], **_edge_info(e, defl), "faces": []}
                    ends = []
                    for v in _subs(e, TopAbs_VERTEX):
                        hv = hash(v)
                        if hv not in vert_ids:
                            vert_ids[hv] = len(verts_out)
                            verts_out.append(_pnt(BRep_Tool.Pnt_s(v)))
                        ends.append(vert_ids[hv])
                    er["verts"] = ends
                    edges_out.append(er)
                eid = edge_ids[h]
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


def write_preview_stl(topo: dict[str, Any], path: Path) -> None:
    """Binary STL of the viewer tessellation in topo.json: the mesh the 4-view render of a fast build reads (the
    exported part.stl, at 0.01 mm, comes later with the other exports)."""
    import struct

    tris: list[bytes] = []
    for f in topo.get("faces", []):
        pos, idx = f.get("pos") or [], f.get("idx") or []
        for k in range(0, len(idx) - 2, 3):
            a, b, c = idx[k] * 3, idx[k + 1] * 3, idx[k + 2] * 3
            tris.append(struct.pack("<12fH", 0.0, 0.0, 0.0, *pos[a:a + 3], *pos[b:b + 3], *pos[c:c + 3], 0))
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as fh:
        fh.write(b"Formwright preview mesh".ljust(80, b"\0"))
        fh.write(struct.pack("<I", len(tris)))
        fh.write(b"".join(tris))
    tmp.replace(path)
