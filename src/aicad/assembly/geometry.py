"""Kernel-side assembly geometry (runs in the assembly worker process only).

- ``prepare``: snapshot a part (a project's verified STEP or a Toolbox component) into the org part cache:
  ``part.step``, ``topo.json`` (exact faces for the viewer and mate references) and ``info.json`` (volume, bbox,
  recognised holes and hole patterns, with face ids matching topo.json).
- ``interference``: exact OCCT boolean common between instance pairs (volumes in mm³).
- ``clearance``: exact minimum distance between instance pairs (BRepExtrema).
- ``probe``: grip measurement along a hole axis for fastener auto-fit (line / solid intersections).
- ``export``: assembly STEP with hierarchy, names and placements, re-imported to verify the tree.
"""

from __future__ import annotations

import itertools
import json
import math
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np

from aicad.assembly import xform

_CACHE: OrderedDict[str, Any] = OrderedDict()
_CACHE_MAX = 64


# ----------------------------------------------------------------------------- helpers
def _trsf(T: np.ndarray) -> Any:
    from OCP.gp import gp_Trsf

    t = gp_Trsf()
    m = T
    t.SetValues(m[0, 0], m[0, 1], m[0, 2], m[0, 3], m[1, 0], m[1, 1], m[1, 2], m[1, 3],
                m[2, 0], m[2, 1], m[2, 2], m[2, 3])
    return t


def _loc(T: np.ndarray) -> Any:
    from build123d import Location

    return Location(_trsf(T))


def load(step: str | Path) -> Any:
    """Cached import of a part snapshot (snapshots are immutable: the key is the file path + size + mtime)."""
    from build123d import import_step

    p = Path(step)
    st = p.stat()
    key = f"{p.resolve()}|{st.st_size}|{st.st_mtime_ns}"
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    shape = import_step(str(p))
    _CACHE[key] = shape
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return shape


def _solids(shape: Any) -> list[Any]:
    return list(shape.solids()) or [shape]


def _world(inst: dict[str, Any]) -> Any:
    return load(inst["step"]).moved(_loc(xform.from12(inst["T"])))


def _aabb(inst: dict[str, Any], info_bbox: list[float]) -> tuple[np.ndarray, np.ndarray]:
    T = xform.from12(inst["T"])
    x0, y0, z0, x1, y1, z1 = info_bbox
    pts = np.array([xform.pt(T, (x, y, z)) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)])
    return pts.min(axis=0), pts.max(axis=0)


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


# ----------------------------------------------------------------------------- prepare
def prepare(dest: Path, step: str | None = None, toolbox_spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Snapshot one part into ``dest`` (part.step, topo.json, info.json). Returns info."""
    from build123d import export_step, import_step

    from aicad.agent.runner import STEP_TIMESTAMP, normalize_step
    from aicad.recognize import recognize
    from aicad.topo import export_topology

    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "part.step"
    if toolbox_spec is not None:
        from aicad import toolbox

        shape, _exp = toolbox.build(toolbox_spec["code"], **toolbox_spec.get("params", {}))
        tmp = dest / "part.tmp.step"
        export_step(shape, str(tmp), timestamp=STEP_TIMESTAMP)
        normalize_step(tmp)
        os.replace(tmp, target)
    elif step is not None:
        data = Path(step).read_bytes()
        tmp = dest / "part.tmp.step"
        tmp.write_bytes(data)
        os.replace(tmp, target)
    else:
        raise ValueError("nothing to prepare")
    shape = import_step(str(target))
    export_topology(shape, dest / "topo.json")
    bb = shape.bounding_box()
    try:
        rec = recognize(shape)
        holes = rec.get("holes", [])
        patterns = rec.get("patterns", [])
        component = rec.get("component")
    except Exception:  # noqa: BLE001 - recognition is a convenience; the part stays usable without it
        holes, patterns, component = [], [], None
    refs = exact_refs(shape)
    _write_json(dest / "refs.json", refs)
    out_holes = []
    for i, h in enumerate(holes):
        fids = _hole_face_ids(shape, h)
        hole = {"id": i, "d": h["d"], "axis": h["axis"], "center": h["center"], "depth": h["depth"],
                "through": h["through"], "open": h.get("open"), "dir": h.get("dir"), "faces": fids}
        if fids:
            ax = refs["faces"][str(fids[0])]
            c = np.array(h["center"], dtype=float)
            p0, v = np.array(ax["p"]), np.array(ax["v"])
            foot = p0 + v * float((c - p0) @ v)
            hole["exact"] = {"p": [float(x) for x in foot], "v": ax["v"], "r": ax["r"]}
        out_holes.append(hole)
    info = {"volume": float(shape.volume), "solids": len(shape.solids()),
            "bbox": [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z],
            "center": [(bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2, (bb.min.Z + bb.max.Z) / 2],
            "holes": out_holes,
            "patterns": [{"kind": p["kind"], "d": p["d"], "count": p["count"], "holes": p["holes"]} for p in patterns]}
    if component:  # a recognised gear: teeth, module, axis (ICD conformance, CD-010)
        info["component"] = {k: component.get(k) for k in ("kind", "params", "axis", "origin")}
    _write_json(dest / "info.json", info)
    return info


def exact_refs(shape: Any) -> dict[str, dict[str, dict[str, Any]]]:
    """Unrounded mate geometry for every planar / cylindrical face and circular / straight edge, keyed by the same
    ids topo.json uses (faces in body order; edges numbered on first appearance while walking the faces)."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cylinder, GeomAbs_Line, GeomAbs_Plane

    from aicad.recognize import topo_faces

    faces: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    edge_ids: dict[Any, int] = {}
    for fid, f in enumerate(topo_faces(shape)):
        s = BRepAdaptor_Surface(f.wrapped)
        t = s.GetType()
        if t == GeomAbs_Plane:
            c = f.center()
            n = f.normal_at(c)
            faces[str(fid)] = {"kind": "plane", "p": [c.X, c.Y, c.Z], "v": [n.X, n.Y, n.Z]}
        elif t == GeomAbs_Cylinder:
            cyl = s.Cylinder()
            ax = cyl.Axis()
            faces[str(fid)] = {"kind": "axis", "p": [ax.Location().X(), ax.Location().Y(), ax.Location().Z()],
                               "v": [ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()], "r": cyl.Radius()}
        for e in f.edges():
            if e in edge_ids:
                continue
            eid = edge_ids[e] = len(edge_ids)
            cv = BRepAdaptor_Curve(e.wrapped)
            ct = cv.GetType()
            if ct == GeomAbs_Circle:
                circ = cv.Circle()
                ax = circ.Axis()
                edges[str(eid)] = {"kind": "axis", "p": [ax.Location().X(), ax.Location().Y(), ax.Location().Z()],
                                   "v": [ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()],
                                   "r": circ.Radius()}
            elif ct == GeomAbs_Line:
                a, b = e.position_at(0), e.position_at(1)
                v = np.array([b.X - a.X, b.Y - a.Y, b.Z - a.Z])
                if float(np.linalg.norm(v)) > 1e-12:
                    v = v / np.linalg.norm(v)
                    edges[str(eid)] = {"kind": "axis", "p": [a.X, a.Y, a.Z], "v": [float(x) for x in v], "r": None}
    return {"faces": faces, "edges": edges}


def _hole_face_ids(shape: Any, h: dict[str, Any]) -> list[int]:
    """topo.json face ids of the cylindrical faces of a recognised hole (coaxial, same radius)."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder

    from aicad.recognize import topo_faces

    r = h["d"] / 2
    c = np.array(h["center"], dtype=float)
    d = xform.unit(h["axis"])
    ids = []
    for i, f in enumerate(topo_faces(shape)):
        s = BRepAdaptor_Surface(f.wrapped)
        if s.GetType() != GeomAbs_Cylinder:
            continue
        cyl = s.Cylinder()
        if abs(cyl.Radius() - r) > 1e-3:
            continue
        ax = cyl.Axis()
        dd = np.array([ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()])
        o = np.array([ax.Location().X(), ax.Location().Y(), ax.Location().Z()])
        if abs(abs(float(dd @ d)) - 1) > 1e-6:
            continue
        w = o - c
        if float(np.linalg.norm(w - d * float(w @ d))) > 1e-3:
            continue
        ids.append(i)
    return ids


# ----------------------------------------------------------------------------- interference
def _volume(shape: Any) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, g)
    return float(g.Mass())


def _common(sa: Any, sb: Any) -> Any | None:
    """Exact boolean common of two solids (None when empty)."""
    from build123d import Compound
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common

    op = BRepAlgoAPI_Common(sa.wrapped, sb.wrapped)
    op.Build()
    if not op.IsDone():
        raise RuntimeError("boolean common failed")
    res = Compound(op.Shape())
    return res if res.solids() else None


def _mesh(shape: Any, tol: float) -> dict[str, list[float] | list[int]]:
    pos: list[float] = []
    idx: list[int] = []
    for f in shape.faces():
        vs, tris = f.tessellate(tol, 0.3)
        b = len(pos) // 3
        for v in vs:
            pos += [round(v.X, 4), round(v.Y, 4), round(v.Z, 4)]
        for t in tris:
            idx += [b + t[0], b + t[1], b + t[2]]
    return {"pos": pos, "idx": idx}


def _thread_axis(inst: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, float] | None:
    th = inst.get("thread")
    if not th:
        return None
    T = xform.from12(inst["T"])
    return xform.pt(T, th.get("p", (0, 0, 0))), xform.unit(xform.vec(T, th.get("d", (0, 0, 1)))), float(th["d_nom"]) / 2


def _within_thread(shape: Any, ax: tuple[np.ndarray, np.ndarray, float]) -> bool:
    """True when the whole overlap lies inside the fastener's nominal thread cylinder (threads are cosmetic: a
    shank at nominal Ø overlapping a tap-drill hole is thread engagement, not a clash)."""
    p, d, r = ax
    pos = np.asarray(_mesh(shape, max(r / 50, 0.002))["pos"], dtype=float).reshape(-1, 3)
    if not len(pos):
        return False
    w = pos - p
    radial = np.linalg.norm(w - np.outer(w @ d, d), axis=1)
    return bool(np.max(radial) <= r + 2e-3)


def _envelope(inst: dict[str, Any]) -> Any | None:
    """A simple solid that contains every solid of a multi-solid part (a ball bearing: the ring from bore to OD
    over its width), placed in the world; None when the part declares none. Used to screen pairs: when the other
    part does not overlap the envelope it cannot overlap any of the solids inside it (exact, not an estimate)."""
    env = inst.get("envelope")
    if not env or env.get("kind") != "annulus":
        return None
    key = "env|" + json.dumps([round(float(env[k]), 6) for k in ("r0", "r1", "z0", "z1")])
    if key not in _CACHE:
        from build123d import Align, Cylinder, Pos

        h = float(env["z1"]) - float(env["z0"])
        al = (Align.CENTER, Align.CENTER, Align.MIN)
        ring = Pos(0, 0, float(env["z0"])) * Cylinder(float(env["r1"]), h, align=al)
        if float(env["r0"]) > 0:
            ring = ring - Pos(0, 0, float(env["z0"]) - 0.01) * Cylinder(float(env["r0"]), h + 0.02, align=al)
        _CACHE[key] = ring
    return _CACHE[key].moved(_loc(xform.from12(inst["T"])))


def _sbox(shape: Any) -> tuple[np.ndarray, np.ndarray]:
    bb = shape.bounding_box()
    return np.array([bb.min.X, bb.min.Y, bb.min.Z]), np.array([bb.max.X, bb.max.Y, bb.max.Z])


def _apart(a: tuple[np.ndarray, np.ndarray], b: tuple[np.ndarray, np.ndarray], gap: float = 1e-6) -> bool:
    return bool(np.any(a[0] > b[1] + gap) or np.any(b[0] > a[1] + gap))


class _Shapes:
    """World shapes of instances, split into solids with their bounding boxes (computed once per check)."""

    def __init__(self, instances: list[dict[str, Any]]) -> None:
        self.instances = instances
        self._solids: dict[int, list[tuple[Any, tuple[np.ndarray, np.ndarray]]]] = {}
        self._env: dict[int, Any] = {}

    def solids(self, k: int) -> list[tuple[Any, tuple[np.ndarray, np.ndarray]]]:
        if k not in self._solids:
            self._solids[k] = [(s, _sbox(s)) for s in _solids(_world(self.instances[k]))]
        return self._solids[k]

    def envelope(self, k: int) -> Any | None:
        if k not in self._env:
            self._env[k] = _envelope(self.instances[k]) if len(self.solids(k)) > 2 else None
        return self._env[k]


STATS = {"screened": 0, "booleans": 0}


def overlap(sh: _Shapes, a: int, b: int, vol_tol: float = 1e-6) -> tuple[float, list[Any]]:
    """Exact overlap volume of two instances and the common solids. Solid pairs whose boxes are apart are skipped;
    a multi-solid part with an envelope (a bearing) is screened first: no overlap with the envelope = none at all."""
    for k, o in ((a, b), (b, a)):
        env = sh.envelope(k)
        if env is None:
            continue
        eb = _sbox(env)
        v = 0.0
        for so, bo in sh.solids(o):
            if _apart(eb, bo):
                continue
            STATS["booleans"] += 1
            c = _common(env, so)
            if c is not None:
                v += _volume(c)
        if v <= vol_tol:
            STATS["screened"] += 1
            return 0.0, []
    vol = 0.0
    commons = []
    for sa, ba in sh.solids(a):
        for sb, bb_ in sh.solids(b):
            if _apart(ba, bb_):
                continue
            STATS["booleans"] += 1
            c = _common(sa, sb)
            if c is None:
                continue
            v = _volume(c)
            if v > vol_tol:
                vol += v
                commons.append(c)
    return vol, commons


def interference(instances: list[dict[str, Any]], vol_tol: float = 1e-6,
                 only: list[str] | None = None) -> dict[str, Any]:
    """Pairwise exact interference. Each instance: {id, step, T, bbox, thread?, envelope?}. Returns pairs with
    overlap. ``only``: check just the pairs that involve one of these instance ids (e.g. a stack just inserted).
    Screening (exact, never drops an overlap): instance boxes, then solid boxes, then a declared envelope."""
    n = len(instances)
    focus = set(only) if only is not None else None
    boxes = [_aabb(i, i["bbox"]) for i in instances]
    sh = _Shapes(instances)
    out = []
    checked = 0
    for a in range(n):
        for b in range(a + 1, n):
            if focus is not None and instances[a]["id"] not in focus and instances[b]["id"] not in focus:
                continue
            if _apart(boxes[a], boxes[b]):
                continue
            checked += 1
            ia, ib = instances[a], instances[b]
            vol, commons = overlap(sh, a, b, vol_tol)
            if vol <= vol_tol:
                continue
            out.append(_pair_row(ia, ib, vol, commons))
    out.sort(key=lambda r: (-r["volume_mm3"], r["a"], r["b"]))
    return {"pairs": out, "checked_pairs": checked, "instances": n}


def _pair_row(ia: dict[str, Any], ib: dict[str, Any], vol: float, commons: list[Any], mesh: bool = True) -> dict[str, Any]:
    from build123d import Compound

    common = commons[0] if len(commons) == 1 else Compound(children=commons)
    kind = "interference"
    for one in (ia, ib):
        ax = _thread_axis(one)
        if ax is not None and _within_thread(common, ax):
            kind = "thread"
            break
    bb = common.bounding_box()
    size = max(bb.size.X, bb.size.Y, bb.size.Z, 1e-3)
    c = common.center()
    return {"a": ia["id"], "b": ib["id"], "volume_mm3": round(vol, 9), "kind": kind,
            "center": [round(c.X, 4), round(c.Y, 4), round(c.Z, 4)],
            "bbox": [round(bb.min.X, 4), round(bb.min.Y, 4), round(bb.min.Z, 4), round(bb.max.X, 4),
                     round(bb.max.Y, 4), round(bb.max.Z, 4)],
            "mesh": _mesh(common, max(size / 200, 0.005)) if kind == "interference" and mesh else None}


# ----------------------------------------------------------------------------- clearance
def min_distance(sa: Any, sb: Any) -> tuple[float, list[float], list[float]]:
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    d = BRepExtrema_DistShapeShape(sa.wrapped, sb.wrapped)
    d.Perform()
    if not d.IsDone() or d.NbSolution() < 1:
        raise RuntimeError("distance computation failed")
    p1, p2 = d.PointOnShape1(1), d.PointOnShape2(1)
    return float(d.Value()), [p1.X(), p1.Y(), p1.Z()], [p2.X(), p2.Y(), p2.Z()]


def _face_data(shape: Any) -> tuple[list[Any], np.ndarray, np.ndarray]:
    """Faces of a (world) shape, their boxes (N x 6) and its vertices (points on its surface)."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    faces = list(shape.faces())
    boxes = np.empty((len(faces), 6))
    for k, f in enumerate(faces):
        bx = Bnd_Box()
        BRepBndLib.Add_s(f.wrapped, bx, False)
        lo, hi = bx.CornerMin(), bx.CornerMax()
        boxes[k] = (lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z())
    pts = np.asarray([(v.X, v.Y, v.Z) for v in shape.vertices()], dtype=float).reshape(-1, 3)
    return faces, boxes, pts


def _upper(pa: np.ndarray, pb: np.ndarray) -> float:
    """Smallest distance between two point sets (points on both surfaces: an upper bound of their distance)."""
    if not len(pa) or not len(pb):
        return math.inf
    best = math.inf
    for k in range(0, len(pa), 512):
        d = np.sqrt(((pa[k:k + 512, None, :] - pb[None, :, :]) ** 2).sum(axis=2)).min()
        best = min(best, float(d))
    return best


def _box_gap(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    """Pairwise gap between boxes (N x 6, M x 6) -> N x M distances (0 when they overlap)."""
    lo = np.maximum(0.0, np.maximum(A[:, None, :3] - B[None, :, 3:], B[None, :, :3] - A[:, None, 3:]))
    return np.sqrt((lo ** 2).sum(axis=2))


MAX_FACE_PAIRS = 20000


def min_distance_near(sa: Any, sb: Any) -> tuple[float, list[float], list[float]]:
    """``min_distance`` for two solids known not to overlap, by branch and bound over face pairs: an upper bound U
    from the vertices of both, the face pairs whose boxes come within U sorted by box gap, the exact distance of
    each pair until the next box gap is no smaller than the best distance found (a pair can't be closer than its
    boxes). Same value as on the whole shapes (no containment without an overlap); much faster on many-faced parts
    such as meshing gears. Falls back to the whole shapes when the search would be too large."""
    fa, ba, pa = _face_data(sa)
    fb, bb, pb = _face_data(sb)
    if not fa or not fb or len(fa) * len(fb) > 4_000_000:
        return min_distance(sa, sb)
    U = _upper(pa, pb)
    gaps = _box_gap(ba, bb)
    ia, ib = np.nonzero(gaps <= (U if math.isfinite(U) else np.inf) + 1e-6)
    if len(ia) > MAX_FACE_PAIRS:
        return min_distance(sa, sb)
    order = np.argsort(gaps[ia, ib], kind="stable")
    best: tuple[float, list[float], list[float]] | None = None
    for k in order:
        g = float(gaps[ia[k], ib[k]])
        if best is not None and g >= best[0]:
            break
        d = min_distance(fa[int(ia[k])], fb[int(ib[k])])
        if best is None or d[0] < best[0]:
            best = d
    return best if best is not None else min_distance(sa, sb)


def clearance(instances: list[dict[str, Any]], pairs: list[tuple[str, str, str]], near_mm: float,
              overlaps: dict[tuple[str, str], list[float]] | None = None) -> dict[str, Any]:
    """Minimum distance for the requested pairs (with their reason) plus every other pair whose bounding boxes
    come within ``near_mm``. Returns one row per pair. ``overlaps`` (pair -> a point in the overlap), from the
    interference check just run: those pairs are at distance 0 by definition, and every other pair is known not
    to overlap, so its distance is computed on the nearby faces only (``min_distance_near``)."""
    by_id = {i["id"]: i for i in instances}
    boxes = {i["id"]: _aabb(i, i["bbox"]) for i in instances}
    want: dict[tuple[str, str], set[str]] = {}
    for a, b, why in pairs:
        if a in by_id and b in by_id and a != b:
            key = (a, b) if a < b else (b, a)
            want.setdefault(key, set()).add(why)
    ids = [i["id"] for i in instances]
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            a, b = ids[x], ids[y]
            (amin, amax), (bmin, bmax) = boxes[a], boxes[b]
            gap = np.maximum(0, np.maximum(amin - bmax, bmin - amax))
            if float(np.linalg.norm(gap)) <= near_mm:
                key = (a, b) if a < b else (b, a)
                want.setdefault(key, set()).add("near")
    world: dict[str, Any] = {}
    rows = []
    for (a, b), why in sorted(want.items()):
        hit = None if overlaps is None else overlaps.get((a, b)) or overlaps.get((b, a))
        if hit is not None:
            d, p1, p2 = 0.0, list(hit), list(hit)
        else:
            for k in (a, b):
                if k not in world:
                    world[k] = _world(by_id[k])
            d, p1, p2 = (min_distance(world[a], world[b]) if overlaps is None
                         else min_distance_near(world[a], world[b]))
        rows.append({"a": a, "b": b, "distance_mm": round(d, 10), "pa": [round(x, 4) for x in p1],
                     "pb": [round(x, 4) for x in p2], "why": sorted(why)})
    return {"rows": rows}


# ----------------------------------------------------------------------------- probe (fastener auto-fit)
def _line_intervals(shape: Any, p: np.ndarray, u: np.ndarray, t0: float, t1: float) -> list[tuple[float, float]]:
    """Parameter intervals [a, b] (along unit u from p) where the line is inside the material of ``shape``."""
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    from OCP.TopAbs import TopAbs_IN

    out: list[tuple[float, float]] = []
    lin = gp_Lin(gp_Pnt(*p), gp_Dir(*u))
    for sol in _solids(shape):
        inter = BRepIntCurveSurface_Inter()
        inter.Init(sol.wrapped, lin, 1e-7)
        ws = []
        while inter.More():
            ws.append(inter.W())
            inter.Next()
        ws = sorted(w for w in ws if t0 - 1e-9 <= w <= t1 + 1e-9)
        pts = [t0, *ws, t1]
        uniq = [pts[0]]
        for w in pts[1:]:
            if w - uniq[-1] > 1e-7:
                uniq.append(w)
        for a, b in itertools.pairwise(uniq):
            m = p + u * ((a + b) / 2)
            cl = BRepClass3d_SolidClassifier(sol.wrapped, gp_Pnt(*m), 1e-7)
            if cl.State() == TopAbs_IN:
                if out and abs(out[-1][1] - a) < 1e-7:
                    out[-1] = (out[-1][0], b)
                else:
                    out.append((a, b))
    out.sort()
    merged: list[tuple[float, float]] = []
    for a, b in out:
        if merged and a <= merged[-1][1] + 1e-7:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _face_at(shape: Any, p: np.ndarray, u: np.ndarray, t: float) -> int | None:
    """topo.json id of the face the line (p, u) crosses at parameter t."""
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt

    from aicad.recognize import topo_faces

    inter = BRepIntCurveSurface_Inter()
    inter.Init(shape.wrapped, gp_Lin(gp_Pnt(*p), gp_Dir(*u)), 1e-7)
    best = None
    while inter.More():
        if abs(inter.W() - t) < 1e-5:
            best = inter.Face()
            break
        inter.Next()
    if best is None:
        return None
    for i, f in enumerate(topo_faces(shape)):
        if f.wrapped.IsSame(best):
            return i
    return None


def probe(instances: list[dict[str, Any]], target: dict[str, Any]) -> dict[str, Any]:
    """Measure the clamped stack along one hole's axis.

    instances: [{id, name, step, T, bbox, material, holes}] (holes in part-local coordinates, from info.json).
    target: {inst, hole} — the picked hole (index into that instance's holes).
    Returns the probe dict consumed by ``fasteners.propose`` plus world placement data for inserting the stack.
    """
    by_id = {i["id"]: i for i in instances}
    tgt = by_id[target["inst"]]
    hole = tgt["holes"][int(target["hole"])]
    Tt = xform.from12(tgt["T"])
    ex = hole.get("exact") or {"p": hole["center"], "v": hole["axis"]}
    c = xform.pt(Tt, ex["p"])
    u = xform.unit(xform.vec(Tt, ex["v"]))
    if float(u @ xform.unit(xform.vec(Tt, hole["axis"]))) < 0:
        u = -u
    r_hole = hole["d"] / 2
    # assembly extent along the axis
    corners = []
    for i in instances:
        lo, hi = _aabb(i, i["bbox"])
        corners += [lo, hi]
    allpts = np.array(corners)
    span = float(np.linalg.norm(allpts.max(axis=0) - allpts.min(axis=0))) + 10.0
    t0, t1 = -span, span
    e1 = xform.perp(u)
    e2 = np.cross(u, e1)
    angles = [k * math.pi / 4 for k in range(8)]

    def ring(radius: float) -> list[np.ndarray]:
        return [c + radius * (math.cos(a) * e1 + math.sin(a) * e2) for a in angles]

    def intervals(inst: dict[str, Any], starts: list[np.ndarray]) -> list[list[tuple[float, float]]]:
        T = xform.from12(inst["T"])
        Ti = xform.inv(T)
        shape = load(inst["step"])
        ul = xform.unit(xform.vec(Ti, u))
        res = []
        for s in starts:
            pl = xform.pt(Ti, s)
            res.append(_line_intervals(shape, pl, ul, t0, t1))
        return res

    def margin(r: float) -> float:
        return max(0.15, 0.08 * r)

    seat_r = r_hole + margin(r_hole)
    # a washer seats on material up to about its outer radius (ISO 7089 OD ≈ 2 d), so a member whose own coaxial
    # hole is larger than the picked one (Ø6.6 plate under a Ø5.5 bracket) is still clamped: probe it there (AMI-01)
    r_cap = 1.9 * r_hole + 1.0

    def coaxial_holes(inst: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
        T = xform.from12(inst["T"])
        out = []
        for k, h in enumerate(inst.get("holes") or []):
            hp = (h.get("exact") or {}).get("p") or h["center"]
            hc = xform.pt(T, hp)
            hd = xform.unit(xform.vec(T, h["axis"]))
            w = hc - c
            if abs(abs(float(hd @ u)) - 1) < 1e-6 and float(np.linalg.norm(w - u * float(w @ u))) < 0.01:
                out.append((k, h))
        return out

    def seat_radii(inst: dict[str, Any]) -> list[float]:
        rs = {round(h["d"] / 2, 6) for _k, h in coaxial_holes(inst) if h["d"] / 2 > r_hole + 1e-6}
        rs |= {round(f * r_hole, 6) for f in (1.25, 1.5)}          # unrecognised larger holes (fallback)
        return [seat_r] + [r + margin(r) for r in sorted(rs) if r + margin(r) <= r_cap]

    def full_ring(per_angle: list[list[tuple[float, float]]]) -> list[tuple[float, float]]:
        spans = []
        for a, b in per_angle[0]:
            if all(any(oa <= a + 0.02 and ob >= b - 0.02 for oa, ob in other) for other in per_angle[1:]):
                spans.append((a, b))
        return spans

    warnings: list[str] = []
    seat: dict[str, list[tuple[float, float]]] = {}
    seat_rad: dict[str, float] = {}
    for inst in instances:
        lo, hi = _aabb(inst, inst["bbox"])
        # skip parts far from the axis (cheap reject: distance from the axis to the box)
        ctr = (lo + hi) / 2
        rad = float(np.linalg.norm(hi - lo)) / 2
        w = ctr - c
        if float(np.linalg.norm(w - u * float(w @ u))) > rad + 3 * r_hole + 1:
            continue
        # material present at every angle around the axis = a seat / clamped member. Try the picked hole's ring
        # first, then the rings just outside this part's own larger coaxial holes.
        spans: list[tuple[float, float]] = []
        touched = False
        for rr in (seat_radii(inst) if inst["id"] != tgt["id"] else [seat_r]):
            per_angle = intervals(inst, ring(rr))
            if all(not x for x in per_angle):
                continue
            touched = True
            spans = full_ring(per_angle)
            if spans:
                seat_rad[inst["id"]] = rr
                break
        if not touched:
            continue
        if not spans and inst["id"] == tgt["id"]:
            warnings.append("The material around the hole is not continuous (hole near an edge?).")
        seat[inst["id"]] = spans
    # start: the target's own span around the hole
    lo_h = -hole["depth"] / 2
    hi_h = hole["depth"] / 2
    own = [s for s in seat.get(tgt["id"], []) if s[1] >= lo_h - 1e-3 and s[0] <= hi_h + 1e-3]
    if not own:
        return {"kind": "blocked", "hole_d": hole["d"], "grip": 0.0, "members": [], "warnings": warnings,
                "reason": "No material found around this hole along its axis."}
    s0, s1 = own[0][0], own[-1][1]
    members = [{"inst": tgt["id"], "name": tgt["name"], "from": s0, "to": s1}]
    gap_tol = 0.01
    changed = True
    used = {tgt["id"]}
    while changed:
        changed = False
        for inst in instances:
            if inst["id"] in used:
                continue
            for a, b in seat.get(inst["id"], []):
                if abs(a - s1) <= gap_tol and b > s1:
                    members.append({"inst": inst["id"], "name": inst["name"], "from": a, "to": b})
                    s1 = b
                    used.add(inst["id"])
                    changed = True
                    break
                if abs(b - s0) <= gap_tol and a < s0:
                    members.insert(0, {"inst": inst["id"], "name": inst["name"], "from": a, "to": b})
                    s0 = a
                    used.add(inst["id"])
                    changed = True
                    break
    # overlapping (interfering) parts on the axis are a problem worth stating
    for inst in instances:
        if inst["id"] in used:
            continue
        for a, b in seat.get(inst["id"], []):
            if a < s1 - gap_tol and b > s0 + gap_tol:
                warnings.append(f"{inst['name']} overlaps the clamped parts on this axis (interference?).")
    # shank probe: which members restrict a shank of the clearance-derived size
    from aicad.assembly import fasteners

    size = fasteners.size_for_clearance(hole["d"])
    D = size["d"] if size else hole["d"]
    shank_r = 0.95 * D / 2
    restrict: list[dict[str, Any]] = []
    for mem in members:
        inst = by_id[mem["inst"]]
        per = intervals(inst, ring(shank_r)) + intervals(inst, [c])
        inside = 0.0
        for iv in per:
            for a, b in iv:
                lo2, hi2 = max(a, mem["from"]), min(b, mem["to"])
                inside = max(inside, hi2 - lo2)
        if inside > 1e-3:
            restrict.append(mem)
    tapped = None
    kind = "through"
    if len(restrict) > 1:
        return {"kind": "blocked", "hole_d": hole["d"], "grip": 0.0, "members": _clean(members), "warnings": warnings,
                "reason": "The axis is blocked by " + " and ".join(m["name"] for m in restrict) + "."}
    head_at = "end"  # head at s1 (outward +u) or "start" (outward -u)
    if restrict:
        rm = restrict[0]
        idx = members.index(rm)
        if 0 < idx < len(members) - 1:
            return {"kind": "blocked", "hole_d": hole["d"], "grip": 0.0, "members": _clean(members),
                    "warnings": warnings, "reason": f"{rm['name']} blocks the hole in the middle of the stack."}
        inst = by_id[rm["inst"]]
        Ti = xform.from12(inst["T"])
        th = None
        for h in inst.get("holes") or []:
            hc = xform.pt(Ti, h["center"])
            hd = xform.unit(xform.vec(Ti, h["axis"]))
            w = hc - c
            ts = fasteners.tap_size(h["d"])
            coaxial = abs(abs(float(hd @ u)) - 1) < 1e-6 and float(np.linalg.norm(w - u * float(w @ u))) < 0.01
            if coaxial and ts is not None and ts["d"] == D:
                th = (h, float((hc - c) @ u))
        if th is None:
            # a smaller coaxial *clearance* hole is the common real case (Ø6.6 picked over a Ø5.5 hole): say so and
            # offer the smaller size through both (AMI-17)
            smaller = None
            for k, h in coaxial_holes(inst):
                sz = fasteners.size_for_clearance(h["d"])
                if sz is not None and sz["d"] < D and h.get("through"):
                    smaller = (k, h, sz)
                    break
            if smaller is not None:
                k, h, sz = smaller
                return {"kind": "blocked", "hole_d": hole["d"], "grip": 0.0, "members": _clean(members),
                        "warnings": warnings, "mismatch": {"inst": rm["inst"], "name": rm["name"], "hole": k,
                                                           "d": h["d"], "size": sz["d"]},
                        "reason": f"The {rm['name']} hole is Ø{h['d']:g} (M{sz['d']} clearance), smaller than this "
                                  f"Ø{hole['d']:g} hole (M{D}). Fit M{sz['d']} through both from the {rm['name']} "
                                  f"hole, or open that hole to Ø{hole['d']:g}."}
            return {"kind": "blocked", "hole_d": hole["d"], "grip": 0.0, "members": _clean(members),
                    "warnings": warnings,
                    "reason": f"{rm['name']} has no M{D} tapped hole on this axis (the screw would hit solid material)."}
        h, hmid = th
        kind = "tapped"
        if idx == 0:
            head_at = "end"
            members = members[1:]
            entry = rm["to"]
            depth = entry - max(rm["from"], hmid - h["depth"] / 2)
        else:
            head_at = "start"
            members = members[:-1]
            entry = rm["from"]
            depth = min(rm["to"], hmid + h["depth"] / 2) - entry
        tapped = {"inst": rm["inst"], "name": rm["name"], "d": h["d"], "depth": round(depth, 4),
                  "blind": not h["through"], "material": inst.get("material")}
        if not members:
            return {"kind": "blocked", "hole_d": hole["d"], "grip": 0.0, "members": [], "warnings": warnings,
                    "reason": "Nothing is clamped: pick the clearance hole in the part on top."}
        s0, s1 = members[0]["from"], members[-1]["to"]
    else:
        up = np.array([0.0, 0.0, 1.0])
        head_at = "end" if float(u @ up) >= -1e-9 else "start"
        if target.get("flip"):
            head_at = "start" if head_at == "end" else "end"
    grip = s1 - s0
    out_dir = u if head_at == "end" else -u
    head_t = s1 if head_at == "end" else s0
    nut_t = s0 if head_at == "end" else s1
    head_pt = c + u * head_t
    nut_pt = c + u * nut_t
    # free space beyond each end (other parts in the way of head, washer and nut)
    obs_r = [seat_r, 1.9 * r_hole + 1.0]

    def space(from_t: float, sign: float) -> float:
        best = math.inf
        for inst in instances:
            ivs = intervals(inst, ring(obs_r[0]) + ring(obs_r[1]))
            for iv in ivs:
                for a, b in iv:
                    if sign > 0 and b > from_t + 1e-6:
                        best = min(best, max(0.0, a - from_t))
                    if sign < 0 and a < from_t - 1e-6:
                        best = min(best, max(0.0, from_t - b))
        return best

    sp_head = space(head_t, 1.0 if head_at == "end" else -1.0)
    if tapped is not None:
        far = by_id[tapped["inst"]]
        rm_iv = [s for s in seat.get(far["id"], [])]
        if rm_iv:
            far_t = rm_iv[0][0] if head_at == "end" else rm_iv[-1][1]
            tapped["beyond"] = _fin(space(far_t, -1.0 if head_at == "end" else 1.0))
    sp_nut = space(nut_t, -1.0 if head_at == "end" else 1.0) if kind == "through" else math.inf
    # seat faces (planar faces crossed by the seat ring at the stack ends) for mating the stack
    def seat_face(mem: dict[str, Any], t: float) -> int | None:
        inst = by_id[mem["inst"]]
        T = xform.from12(inst["T"])
        Ti = xform.inv(T)
        s = ring(seat_rad.get(mem["inst"], seat_r))[0]
        return _face_at(load(inst["step"]), xform.pt(Ti, s), xform.unit(xform.vec(Ti, u)), t)

    head_mem = members[-1] if head_at == "end" else members[0]
    nut_mem = members[0] if head_at == "end" else members[-1]
    order = members if head_at == "start" else list(reversed(members))
    return {
        "kind": kind, "hole_d": hole["d"], "grip": round(grip, 4), "warnings": warnings,
        "members": [{"inst": m["inst"], "name": m["name"], "t": round(m["to"] - m["from"], 4)} for m in order],
        "tapped": tapped,
        "axis": {"p": [float(x) for x in c], "u": [float(x) for x in u]},
        "head": {"point": [float(x) for x in head_pt], "out": [float(x) for x in out_dir],
                 "inst": head_mem["inst"], "face": seat_face(head_mem, head_t), "space": _fin(sp_head)},
        "nut": {"point": [float(x) for x in nut_pt], "out": [float(x) for x in -out_dir],
                "inst": nut_mem["inst"], "face": seat_face(nut_mem, nut_t) if kind == "through" else None,
                "space": _fin(sp_nut)},
        "hole": {"inst": tgt["id"], "index": int(target["hole"]), "faces": hole.get("faces", [])},
    }


def _fin(x: float) -> float | None:
    return None if math.isinf(x) else round(x, 4)


def _clean(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"inst": m["inst"], "name": m["name"], "t": round(m["to"] - m["from"], 4)} for m in members]


# ----------------------------------------------------------------------------- STEP export
def export(dest: Path, name: str, nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Write an assembly STEP. nodes: [{id, part_label, step, T, group, group_label}] (group None = top level).
    Instances of one part share one STEP product (its geometry is written once). The file is re-imported to
    verify the tree: instance count, sub-assembly membership and every placement."""
    from build123d import Compound, export_step

    from aicad.agent.runner import STEP_TIMESTAMP, normalize_step

    dest.parent.mkdir(parents=True, exist_ok=True)
    leaf_of: dict[str, Any] = {}
    order: list[dict[str, Any]] = []

    def level(ns: list[dict[str, Any]], nested: bool) -> list[Any]:
        """Children of one tree level, in first-seen order: plain leaves, one compound per fastener stack, and (top
        level only) one compound per sub-assembly holding its own leaves and stacks."""
        top: list[tuple[str, Any]] = []
        buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
        labels: dict[tuple[str, str], str] = {}
        for n in ns:
            k = ("sub", n["sub"]) if nested and n.get("sub") else ("grp", n["group"]) if n.get("group") else None
            if k is None:
                top.append(("s", n))
                continue
            if k not in buckets:
                buckets[k] = []
                top.append(("g", k))
            buckets[k].append(n)
            labels[k] = n.get("sub_label" if k[0] == "sub" else "group_label") or k[1]
        out: list[Any] = []
        for kind, v in top:
            if kind == "s":
                out.append(leaf_of[v["id"]])
                order.append(v)
                continue
            if v[0] == "sub":
                kids = level(buckets[v], False)
            else:
                order.extend(buckets[v])
                kids = [leaf_of[n["id"]] for n in buckets[v]]
            comp = Compound(children=kids)
            comp.label = labels[v]
            out.append(comp)
        return out

    for n in nodes:
        leaf = load(n["step"]).moved(_loc(xform.from12(n["T"])))
        leaf.label = n["part_label"]
        leaf_of[n["id"]] = leaf
    root = Compound(children=level(nodes, True))
    root.label = name
    tmp = dest.with_name(dest.stem + ".tmp.step")
    export_step(root, str(tmp), timestamp=STEP_TIMESTAMP)
    normalize_step(tmp)
    os.replace(tmp, dest)
    return {"file": dest.name, "bytes": dest.stat().st_size, **verify_export(dest, order)}


def verify_export(path: Path, order: list[dict[str, Any]]) -> dict[str, Any]:
    """Re-import an exported assembly and compare it with the instances it should hold (in export order)."""
    from build123d import import_step

    back = import_step(str(path))
    leaves: list[tuple[list[str], Any]] = []

    def walk(s: Any, path_: list[str]) -> None:
        kids = list(getattr(s, "children", ()) or ())
        if kids:
            for k in kids:
                walk(k, [*path_, s.label or ""])
        else:
            leaves.append((path_, s))

    walk(back, [])
    max_dev = 0.0
    ok = len(leaves) == len(order)
    if ok:
        for (path_, leaf), n in zip(leaves, order, strict=True):
            T = xform.from12(n["T"])
            local = list(load(n["step"]).vertices())[:24]
            got = list(leaf.vertices())[:24]
            if len(local) != len(got):
                ok = False
                continue
            for a, b in zip(local, got, strict=True):
                e = xform.pt(T, (a.X, a.Y, a.Z))
                max_dev = max(max_dev, float(np.linalg.norm(e - np.array([b.X, b.Y, b.Z]))))
            if len(path_) != 1 + bool(n.get("sub")) + bool(n.get("group")):
                ok = False
    return {"instances": len(order), "reimported": len(leaves),
            "groups": len({n["group"] for n in order if n.get("group")}),
            "subassemblies": len({n["sub"] for n in order if n.get("sub")}),
            "placement_dev_mm": round(max_dev, 9), "ok": bool(ok and max_dev < 1e-6)}
