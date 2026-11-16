"""Exact B-rep analysis helpers for the Manufacturing Advisor.

`PartGeom` re-imports a verified `part.step` (or wraps a build123d shape), maps every B-rep face to its `topo.json`
face id, samples each face (exact surface points and outward normals), classifies edges convex / concave / smooth,
and answers exact ray queries against the B-rep (`IntCurvesFace_ShapeIntersector`). All results are deterministic:
no randomness, sampling follows the kernel's tessellation order.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from build123d import Face, Shape, import_step
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import (
    GeomAbs_Circle,
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Line,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_Torus,
)
from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
from OCP.gp import gp_Dir, gp_Lin, gp_Pnt, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.TopAbs import TopAbs_IN, TopAbs_ON

SURF = {GeomAbs_Plane: "plane", GeomAbs_Cylinder: "cylinder", GeomAbs_Cone: "cone", GeomAbs_Sphere: "sphere",
        GeomAbs_Torus: "torus"}

# The six principal setup / pull directions, in a fixed order (ties resolve to the earlier one).
DIRS: list[tuple[str, np.ndarray]] = [
    ("+Z", np.array([0.0, 0.0, 1.0])), ("-Z", np.array([0.0, 0.0, -1.0])),
    ("+X", np.array([1.0, 0.0, 0.0])), ("-X", np.array([-1.0, 0.0, 0.0])),
    ("+Y", np.array([0.0, 1.0, 0.0])), ("-Y", np.array([0.0, -1.0, 0.0])),
]

SAMPLE_BUDGET = 2400  # total face samples (exact surface points) per part
_BARY = [(1 / 3, 1 / 3), (2 / 3, 1 / 6), (1 / 6, 2 / 3), (1 / 6, 1 / 6)]  # interior barycentric points
PER_FACE_MAX = 24
PER_FACE_MIN = 3


def unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-15 else v


def principal(v: np.ndarray, tol: float = 1e-6) -> str | None:
    """Name of the principal direction `v` is parallel to (+X ... -Z), or None."""
    for name, d in DIRS:
        if float(np.dot(v, d)) > 1 - tol:
            return name
    return None


@dataclass
class Sample:
    p: np.ndarray
    n: np.ndarray
    w: float  # area represented (mm^2)


@dataclass
class FaceG:
    i: int  # index in B-rep order
    fid: int  # topo.json face id (viewer highlight id)
    face: Face
    kind: str
    area: float
    center: np.ndarray
    normal: np.ndarray | None = None  # planes: outward normal
    axis: np.ndarray | None = None  # cylinders/cones
    axis_point: np.ndarray | None = None
    radius: float | None = None
    concave: bool | None = None  # cylinders/cones: material outside the surface (hole-like)
    sweep: float | None = None  # cylinders: angular extent (rad)
    vrange: tuple[float, float] | None = None  # cylinders: extent along the axis, measured from axis_point
    samples: list[Sample] = field(default_factory=list)
    verts: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    feature: str | None = None
    edges: list[int] = field(default_factory=list)

    def extent_along(self, d: np.ndarray) -> tuple[float, float]:
        if not len(self.verts):
            c = float(np.dot(self.center, d))
            return c, c
        s = self.verts @ d
        return float(s.min()), float(s.max())


@dataclass
class EdgeG:
    i: int
    kind: str  # line | circle | curve
    length: float
    faces: tuple[int, ...]
    mid: np.ndarray
    tangent: np.ndarray
    convexity: str = "boundary"  # convex | concave | smooth | boundary | unknown
    angle_deg: float = 0.0  # angle between the two face normals at the midpoint
    radius: float | None = None


def _pnt(p: Any) -> np.ndarray:
    return np.array([p.X(), p.Y(), p.Z()])


class PartGeom:
    """Exact B-rep of one part with face samples, edge convexity and ray queries."""

    def __init__(self, shape: Shape, topo: dict[str, Any] | None = None):
        self.shape = shape
        bb = shape.bounding_box()
        self.bmin = np.array([bb.min.X, bb.min.Y, bb.min.Z])
        self.bmax = np.array([bb.max.X, bb.max.Y, bb.max.Z])
        self.size = self.bmax - self.bmin
        self.diag = float(np.linalg.norm(self.size)) or 1.0
        vp = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape.wrapped, vp)
        self.volume = float(vp.Mass())
        sp = GProp_GProps()
        BRepGProp.SurfaceProperties_s(shape.wrapped, sp)
        self.area = float(sp.Mass())
        self.n_solids = len(shape.solids())
        self._inter = IntCurvesFace_ShapeIntersector()
        self._inter.Load(shape.wrapped, 1e-7)
        self._classifier = BRepClass3d_SolidClassifier(shape.wrapped)
        self.faces: list[FaceG] = []
        self._face_index: dict[Face, int] = {}
        self.edges: list[EdgeG] = []
        self._build_faces()
        self._map_topo(topo)
        self._build_edges()

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_step(cls, step: Path, topo: dict[str, Any] | None = None) -> PartGeom:
        return cls(import_step(str(step)), topo)

    def _body_faces(self) -> list[Face]:
        """Faces in the same order as `topo.export_topology` (per solid, then per face)."""
        kids = [c for c in (getattr(self.shape, "children", None) or ()) if c.solids()]
        bodies = kids if kids else (list(self.shape.solids()) or [self.shape])
        out: list[Face] = []
        for b in bodies:
            out += list(b.faces())
        return out

    def _build_faces(self) -> None:
        faces = self._body_faces()
        nf = max(1, len(faces))
        per_face = max(PER_FACE_MIN, min(PER_FACE_MAX, SAMPLE_BUDGET // nf))
        defl = max(self.diag * 0.002, 0.01)
        for i, f in enumerate(faces):
            self._face_index[f] = i
            s = BRepAdaptor_Surface(f.wrapped)
            t = s.GetType()
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(f.wrapped, props)
            g = FaceG(i=i, fid=i, face=f, kind=SURF.get(t, "freeform"), area=float(props.Mass()),
                      center=_pnt(props.CentreOfMass()))
            if t == GeomAbs_Cylinder:
                c = s.Cylinder()
                g.radius = float(c.Radius())
                g.axis = unit(_pnt(c.Axis().Direction()))
                g.axis_point = _pnt(c.Axis().Location())
                u0, u1, v0, v1 = BRepTools.UVBounds_s(f.wrapped)
                g.sweep = float(u1 - u0)
                g.vrange = (float(v0), float(v1))
            elif t == GeomAbs_Cone:
                c = s.Cone()
                g.axis = unit(_pnt(c.Axis().Direction()))
                g.axis_point = _pnt(c.Axis().Location())
                g.radius = float(c.RefRadius())
            elif t == GeomAbs_Sphere:
                g.radius = float(s.Sphere().Radius())
                g.axis_point = _pnt(s.Sphere().Location())
            elif t == GeomAbs_Torus:
                tor = s.Torus()
                g.axis = unit(_pnt(tor.Axis().Direction()))
                g.axis_point = _pnt(tor.Axis().Location())
                g.radius = float(tor.MinorRadius())
            self._sample_face(g, defl, per_face)
            if t == GeomAbs_Plane and g.samples:
                g.normal = g.samples[0].n
            if g.kind in ("cylinder", "cone") and g.samples and g.axis is not None and g.axis_point is not None:
                votes = 0.0
                for sm in g.samples:
                    r = sm.p - g.axis_point
                    r = r - np.dot(r, g.axis) * g.axis
                    votes += sm.w * float(np.sign(np.dot(sm.n, r)))
                g.concave = votes < 0
            self.faces.append(g)

    def _sample_face(self, g: FaceG, defl: float, per_face: int) -> None:
        f = g.face
        try:
            verts, tris = f.tessellate(defl, 0.3)
        except Exception:  # noqa: BLE001 - a face the mesher can't handle just gets no samples
            verts, tris = [], []
        V = np.array([[v.X, v.Y, v.Z] for v in verts]) if verts else np.zeros((0, 3))
        g.verts = V
        if not len(tris):
            return
        T = np.array(tris, dtype=int)
        P = V[T]  # (k, 3, 3) triangle corners
        tri_area = 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1)
        total = float(tri_area.sum())
        if total <= 0:
            return
        # Area-uniform, deterministic sample points: walk the cumulative triangle area at (j + 0.5) / n and use
        # a fixed barycentric pattern inside each triangle.
        n = max(PER_FACE_MIN, min(per_face, len(T) * 4))
        cum = np.cumsum(tri_area)
        pts: list[np.ndarray] = []
        for j in range(n):
            pos = (j + 0.5) / n * total
            t = int(min(np.searchsorted(cum, pos), len(T) - 1))
            start = cum[t] - tri_area[t]
            phi = (pos - start) / tri_area[t] if tri_area[t] > 0 else 0.0
            a, b = _BARY[min(int(phi * len(_BARY)), len(_BARY) - 1)]
            pts.append(P[t, 0] * (1 - a - b) + P[t, 1] * a + P[t, 2] * b)
        surf = BRep_surface(f)
        w = g.area / n
        gface = BRepGProp_Face(f.wrapped)
        for c in pts:
            proj = GeomAPI_ProjectPointOnSurf(gp_Pnt(*c), surf)
            if proj.NbPoints() == 0:
                continue
            u, v = proj.LowerDistanceParameters()
            p, nv = gp_Pnt(), gp_Vec()
            gface.Normal(u, v, p, nv)
            if nv.Magnitude() < 1e-12:
                continue
            g.samples.append(Sample(_pnt(p), unit(np.array([nv.X(), nv.Y(), nv.Z()])), w))

    def _map_topo(self, topo: dict[str, Any] | None) -> None:
        """Map each B-rep face to the topo.json face id (exact match on type, area and centre)."""
        if not topo or not topo.get("faces"):
            return
        tf = topo["faces"]

        def match(g: FaceG, t: dict[str, Any]) -> bool:
            if t.get("type") != g.kind:
                return False
            if abs(float(t["area"]) - g.area) > 1e-3 * max(1.0, g.area):
                return False
            return float(np.linalg.norm(np.array(t["center"]) - g.center)) < 2e-3 * max(1.0, self.diag)

        if len(tf) == len(self.faces) and all(match(g, tf[g.i]) for g in self.faces):
            for g in self.faces:
                g.feature = tf[g.i].get("feature")
            return
        used: set[int] = set()
        for g in self.faces:
            best, bd = None, math.inf
            for t in tf:
                if t["id"] in used or not match(g, t):
                    continue
                d = float(np.linalg.norm(np.array(t["center"]) - g.center))
                if d < bd:
                    best, bd = t, d
            if best is not None:
                used.add(best["id"])
                g.fid = int(best["id"])
                g.feature = best.get("feature")

    def _build_edges(self) -> None:
        emap: dict[Any, int] = {}
        owners: list[list[int]] = []
        objs: list[Any] = []
        for g in self.faces:
            for e in g.face.edges():
                if e not in emap:
                    emap[e] = len(objs)
                    objs.append(e)
                    owners.append([])
                ei = emap[e]
                if g.i not in owners[ei]:
                    owners[ei].append(g.i)
                if ei not in g.edges:
                    g.edges.append(ei)
        for ei, e in enumerate(objs):
            c = BRepAdaptor_Curve(e.wrapped)
            t = c.GetType()
            kind = "line" if t == GeomAbs_Line else "circle" if t == GeomAbs_Circle else "curve"
            u0, u1 = c.FirstParameter(), c.LastParameter()
            p, v = gp_Pnt(), gp_Vec()
            c.D1(0.5 * (u0 + u1), p, v)
            tan = unit(np.array([v.X(), v.Y(), v.Z()]))
            eg = EdgeG(i=ei, kind=kind, length=float(e.length), faces=tuple(owners[ei]), mid=_pnt(p), tangent=tan,
                       radius=float(c.Circle().Radius()) if t == GeomAbs_Circle else None)
            if len(eg.faces) == 2 and float(np.linalg.norm(tan)) > 0.5:
                self._classify_edge(eg)
            self.edges.append(eg)

    def normal_at(self, g: FaceG, p: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
        """(exact surface point, outward normal) of face g nearest to p."""
        surf = BRep_surface(g.face)
        proj = GeomAPI_ProjectPointOnSurf(gp_Pnt(*p), surf)
        if proj.NbPoints() == 0:
            return None
        u, v = proj.LowerDistanceParameters()
        q, nv = gp_Pnt(), gp_Vec()
        BRepGProp_Face(g.face.wrapped).Normal(u, v, q, nv)
        if nv.Magnitude() < 1e-12:
            return None
        return _pnt(q), unit(np.array([nv.X(), nv.Y(), nv.Z()]))

    def _in_face(self, g: FaceG, p: np.ndarray) -> bool:
        cl = BRepClass_FaceClassifier(g.face.wrapped, gp_Pnt(*p), 1e-6)
        return cl.State() == TopAbs_IN

    def _inward(self, g: FaceG, p: np.ndarray, n: np.ndarray, t: np.ndarray) -> np.ndarray | None:
        c = unit(np.cross(n, t))
        for delta in (0.01, 0.002, 0.05):
            if self._in_face(g, p + delta * c):
                return c
            if self._in_face(g, p - delta * c):
                return -c
        return None

    def _classify_edge(self, eg: EdgeG) -> None:
        a, b = (self.faces[k] for k in eg.faces)
        na_ = self.normal_at(a, eg.mid)
        nb_ = self.normal_at(b, eg.mid)
        if na_ is None or nb_ is None:
            eg.convexity = "unknown"
            return
        na, nb = na_[1], nb_[1]
        cosang = float(np.clip(np.dot(na, nb), -1.0, 1.0))
        eg.angle_deg = math.degrees(math.acos(cosang))
        if eg.angle_deg < 3.0:
            eg.convexity = "smooth"
            return
        ia = self._inward(a, eg.mid, na, eg.tangent)
        if ia is None:
            ib = self._inward(b, eg.mid, nb, eg.tangent)
            if ib is None:
                eg.convexity = "unknown"
                return
            eg.convexity = "concave" if float(np.dot(ib, na)) > 0 else "convex"
            return
        eg.convexity = "concave" if float(np.dot(ia, nb)) > 0 else "convex"

    # ------------------------------------------------------------------ queries
    def face_by_shape(self, f: Any) -> int | None:
        return self._face_index.get(Face(f))

    def ray(self, p: np.ndarray, d: np.ndarray, tmin: float = 0.0, tmax: float = 1e9) -> tuple[float, int | None] | None:
        """First intersection of the ray p + t·d (tmin < t < tmax) with the B-rep: (t, face index)."""
        self._inter.Perform(gp_Lin(gp_Pnt(*p), gp_Dir(*d)), tmin, tmax)
        if not self._inter.IsDone() or self._inter.NbPnt() == 0:
            return None
        best, bi = math.inf, 0
        for k in range(1, self._inter.NbPnt() + 1):
            w = self._inter.WParameter(k)
            if tmin < w < best:
                best, bi = w, k
        if bi == 0:
            return None
        return best, self.face_by_shape(self._inter.Face(bi))

    def blocked(self, p: np.ndarray, d: np.ndarray, tmax: float = 1e9) -> bool:
        return self.ray(p, d, 1e-6, tmax) is not None

    def inside(self, p: np.ndarray) -> bool:
        self._classifier.Perform(gp_Pnt(*p), 1e-6)
        st = self._classifier.State()
        return st == TopAbs_IN or st == TopAbs_ON

    def fids(self, idx: list[int] | set[int]) -> list[int]:
        return sorted({self.faces[i].fid for i in idx})

    def features(self, idx: list[int] | set[int]) -> list[str]:
        return sorted({self.faces[i].feature for i in idx if self.faces[i].feature})

    def neighbours(self, i: int, convexity: str | None = None) -> list[int]:
        out: list[int] = []
        for ei in self.faces[i].edges:
            e = self.edges[ei]
            if convexity and e.convexity != convexity:
                continue
            for k in e.faces:
                if k != i and k not in out:
                    out.append(k)
        return out


def BRep_surface(f: Face) -> Any:
    from OCP.BRep import BRep_Tool

    return BRep_Tool.Surface_s(f.wrapped)
