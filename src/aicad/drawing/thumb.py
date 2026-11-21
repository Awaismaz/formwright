"""Blueprint line-art thumbnails of a part snapshot (the Design Office board). Kernel side: the drawing worker.

One view of the real geometry at that moment: the exact hidden-line projection (OCCT HLR, ``geometry.project``'s
convention), visible edges solid, hidden edges dashed. Every projected edge is grouped by the feature its source faces
belong to, so the board can light features up as the part is made and tick them against Gage's measurements:

  bore      a recognised hole or partial bore, or any other concave full cylinder (seats, counterbores)
  teeth     the flanks and lands of recognised gear teeth
  keyway    flat faces along the axis of a round part, inside its outer diameter (keyways, flats)
  groove    a short turned diameter below its neighbours (a ring groove)
  chamfer   small cones and small oblique flat faces (edge breaks)
  profile   the turned diameters (convex full cylinders) and tapers
  envelope  everything else (the body's flat faces, fillets)

Grouping is honest and approximate: a projected edge is matched back to the 3D edges it was projected from (an edge
takes the most specific group of its two faces); a silhouette line of a curved face (no 3D edge) takes the group its
two ends share. An edge that can't be placed stays with the envelope. No line is ever added or moved.

The SVG uses ``currentColor`` so it themes with the page; each group is ``<g data-feature=... data-g=...>`` with an
optional ``data-d`` (diameter, mm) for cylindrical features.
"""

from __future__ import annotations

import itertools
import math
import os
from pathlib import Path
from typing import Any

VERSION = 1
KINDS = ("envelope", "profile", "chamfer", "bore", "groove", "keyway", "teeth")
PRIORITY = {k: i for i, k in enumerate(KINDS)}
VIEWBOX = 100.0
PAD = 6.0
MAX_BYTES = 90_000  # beyond this the hidden lines are left out (never the visible ones)

Vec = tuple[float, float, float]


# ----------------------------------------------------------------------------- small vector helpers
def _t3(a: Any) -> Vec:
    return (float(a.X), float(a.Y), float(a.Z)) if hasattr(a, "X") else (float(a[0]), float(a[1]), float(a[2]))


def _dot(a: Any, b: Any) -> float:
    a, b = _t3(a), _t3(b)
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Any, b: Any) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a: Any) -> Vec:
    a = _t3(a)
    n = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def _mat_t(R: list[list[float]], v: Any) -> Vec:
    """R^T v (the inverse of a rotation)."""
    return (R[0][0] * v[0] + R[1][0] * v[1] + R[2][0] * v[2], R[0][1] * v[0] + R[1][1] * v[1] + R[2][1] * v[2],
            R[0][2] * v[0] + R[1][2] * v[1] + R[2][2] * v[2])


def axes(view_dir: Any, up: Any) -> tuple[Vec, Vec, Vec]:
    """(right, up, toward-viewer) unit vectors, as ``geometry.view_axes`` (paper right = up x toward-viewer)."""
    d = _unit(view_dir)
    k = _dot(up, d)
    u = _unit((up[0] - k * d[0], up[1] - k * d[1], up[2] - k * d[2]))
    return _cross(u, d), u, d


# ----------------------------------------------------------------------------- face classification
def _cyl_data(face: Any) -> tuple[Vec, Vec, float, bool, float, float] | None:
    """(axis point, axis dir, radius, concave, angular span, axial length) of a cylindrical face."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.TopAbs import TopAbs_REVERSED

    ad = BRepAdaptor_Surface(face.wrapped)
    if ad.GetType() != GeomAbs_Cylinder:
        return None
    cyl = ad.Cylinder()
    a1 = cyl.Axis()
    dv = (a1.Direction().X(), a1.Direction().Y(), a1.Direction().Z())
    loc = (a1.Location().X(), a1.Location().Y(), a1.Location().Z())
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face.wrapped)
    p, du, dvv = gp_Pnt(), gp_Vec(), gp_Vec()
    ad.D1((u0 + u1) / 2, (v0 + v1) / 2, p, du, dvv)
    nrm = du.Crossed(dvv)
    if face.wrapped.Orientation() == TopAbs_REVERSED:
        nrm.Reverse()
    pv = (p.X(), p.Y(), p.Z())
    t = _dot((pv[0] - loc[0], pv[1] - loc[1], pv[2] - loc[2]), dv)
    radial = (pv[0] - loc[0] - t * dv[0], pv[1] - loc[1] - t * dv[1], pv[2] - loc[2] - t * dv[2])
    concave = (nrm.X() * radial[0] + nrm.Y() * radial[1] + nrm.Z() * radial[2]) < 0
    return loc, dv, cyl.Radius(), concave, u1 - u0, abs(v1 - v0)


def _line_key(p: Vec, d: Vec, r: float) -> tuple[Any, ...]:
    """A cylinder's axis line and radius, rounded, so coaxial faces of one diameter share a group."""
    d = _unit(d)
    if (d[0], d[1], d[2]) < (0.0, 0.0, 0.0):
        d = (-d[0], -d[1], -d[2])
    t = _dot(p, d)
    foot = (p[0] - t * d[0], p[1] - t * d[1], p[2] - t * d[2])
    return (tuple(round(x, 2) for x in d), tuple(round(x, 2) for x in foot), round(r, 3))


def _radial(v: Any, o: Vec, a: Vec) -> float:
    w = (v[0] - o[0], v[1] - o[1], v[2] - o[2])
    t = _dot(w, a)
    return math.sqrt(max(0.0, _dot(w, w) - t * t))


def classify(shape: Any, info: dict[str, Any]) -> tuple[list[int], list[dict[str, Any]]]:
    """Per face (``recognize.topo_faces`` order) the index of its feature group, and the groups
    ``{kind, d?}``. Group 0 is the envelope."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Plane

    from aicad.recognize import topo_faces

    faces = topo_faces(shape)
    groups: list[dict[str, Any]] = [{"kind": "envelope"}]
    by_key: dict[tuple[Any, ...], int] = {}

    def group(kind: str, key: tuple[Any, ...] | None = None, d: float | None = None) -> int:
        k = (kind, key) if key is not None else None
        if k is not None and k in by_key:
            return by_key[k]
        groups.append({"kind": kind, **({"d": round(float(d), 3)} if d is not None else {})})
        if k is not None:
            by_key[k] = len(groups) - 1
        return len(groups) - 1

    of = [0] * len(faces)
    known: set[int] = set()
    # recognised holes and partial bores (``info.json``, the same face ids)
    for h in list(info.get("holes") or []) + list(info.get("partials") or []):
        fids = [int(f) for f in h.get("faces") or [] if 0 <= int(f) < len(faces)]
        if not fids:
            continue
        g = group("bore", ("rec", tuple(round(float(x), 2) for x in h.get("center") or []), round(float(h["d"]), 3)),
                  float(h["d"]))
        for f in fids:
            of[f] = g
            known.add(f)
    bb = shape.bounding_box()
    size = max(bb.diagonal, 1e-6)
    # gear teeth: faces wholly between the root and tip circles of a recognised gear
    comp = info.get("component") or {}
    gear_axis: tuple[Vec, Vec] | None = None
    if comp.get("kind") in ("spur_gear", "internal_gear"):
        p = comp.get("params") or {}
        m, z = float(p.get("module") or p.get("module_est") or 0), int(p.get("teeth") or 0)
        if m > 0 and z > 0 and comp.get("axis") and comp.get("origin"):
            a, o = _unit(comp["axis"]), tuple(float(x) for x in comp["origin"])
            gear_axis = (o, a)  # type: ignore[assignment]
            if comp["kind"] == "spur_gear":
                lo, hi = m * (z - 2.5) / 2 - 0.1 * m, m * (z + 2) / 2 + 0.1 * m
            else:
                lo, hi = m * (z - 2) / 2 - 0.1 * m, m * (z + 2.5) / 2 + 0.1 * m
            tg = None
            for i, f in enumerate(faces):
                if i in known:
                    continue
                vs = [(v.X, v.Y, v.Z) for v in f.vertices()]
                if not vs:
                    continue
                rs = [_radial(v, o, a) for v in vs]  # type: ignore[arg-type]
                if min(rs) >= lo and max(rs) <= hi:
                    if BRepAdaptor_Surface(f.wrapped).GetType() == GeomAbs_Plane and \
                            abs(_dot(f.normal_at(f.center()), a)) > 0.99:
                        continue  # a side face of the rim between root and tip: not a tooth
                    tg = tg if tg is not None else group("teeth")
                    of[i] = tg
                    known.add(i)
    # the turned body's axis (round parts): the largest convex full cylinder whose diameter spans the bounding box
    cyls: dict[int, tuple[Vec, Vec, float, bool, float, float]] = {}
    for i, f in enumerate(faces):
        if i not in known:
            c = _cyl_data(f)
            if c is not None:
                cyls[i] = c
    axis = gear_axis
    r_out = 0.0
    if axis is None:
        ext = [bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z]
        for c in cyls.values():
            loc, dv, r, concave, span, _ln = c
            if concave or span < 2 * math.pi - 1e-6 or r <= r_out:
                continue
            ax = max(range(3), key=lambda j: abs(dv[j]))
            if abs(abs(dv[ax]) - 1) > 1e-6:
                continue
            if all(abs(2 * r - ext[j]) < 1e-3 for j in range(3) if j != ax):
                axis, r_out = (loc, _unit(dv)), r
    if axis is not None and r_out == 0.0:
        r_out = max((_radial((v.X, v.Y, v.Z), axis[0], axis[1]) for v in shape.vertices()), default=0.0)
    profile_r: dict[tuple[Any, ...], float] = {}
    for i, c in cyls.items():
        loc, dv, r, concave, span, ln = c
        key = _line_key(loc, dv, r)
        if concave and span >= math.pi - 1e-6:
            of[i] = group("bore", key, 2 * r)
        elif not concave and span >= math.pi - 1e-6:
            profile_r[key] = max(profile_r.get(key, 0.0), ln)
        # fillets and rounds (under half a turn) stay with the envelope
    # ring grooves: a short turned diameter with a larger coaxial diameter on both sides
    for i, c in cyls.items():
        loc, dv, r, concave, span, ln = c
        if concave or span < math.pi - 1e-6:
            continue
        key = _line_key(loc, dv, r)
        line = key[:2]
        bigger = [k for k in profile_r if k[:2] == line and k[2] > r + 0.05]
        if ln <= 3.5 and bigger and r < r_out - 0.05:
            of[i] = group("groove", key, 2 * r)
        else:
            of[i] = group("profile", key, 2 * r)
    for i, f in enumerate(faces):
        if i in known or i in cyls:
            continue
        ad = BRepAdaptor_Surface(f.wrapped)
        t = ad.GetType()
        fb = f.bounding_box()
        small = fb.diagonal <= max(0.25 * size, 1e-6)  # an oblique flat face this small is an edge break
        if t == GeomAbs_Cone:
            ext_ = sorted([fb.max.X - fb.min.X, fb.max.Y - fb.min.Y, fb.max.Z - fb.min.Z])
            of[i] = group("chamfer", ("ch",)) if ext_[0] <= max(0.08 * size, 0.5) else group("profile", ("taper",))
        elif t == GeomAbs_Plane:
            n = _unit(f.normal_at(f.center()))
            principal = max(abs(x) for x in n) > 1 - 1e-6
            if axis is not None and abs(_dot(n, axis[1])) < 1e-6:
                c = f.center()
                if _radial((c.X, c.Y, c.Z), axis[0], axis[1]) < r_out - 0.05:
                    of[i] = group("keyway", ("kw",))
                    continue
            if not principal and small and min(fb.max.X - fb.min.X, fb.max.Y - fb.min.Y, fb.max.Z - fb.min.Z) < 0.1 * size \
                    and (axis is None or abs(abs(_dot(n, axis[1])) - 1) > 1e-6):
                of[i] = group("chamfer", ("ch",))
    return of, groups


# ----------------------------------------------------------------------------- projection + grouping
def _edge_points(edge: Any, n_curve: int = 24) -> list[tuple[float, float, float]]:
    from build123d import GeomType

    if edge.geom_type == GeomType.LINE:
        n = 2
    elif edge.geom_type == GeomType.CIRCLE:
        n = max(8, min(72, int(abs(edge.length) / max(edge.radius, 1e-9) / (2 * math.pi) * 48) + 2))
    else:
        n = n_curve
    out = []
    for k in range(n):
        p = edge.position_at(k / (n - 1))
        out.append((p.X, p.Y, p.Z))
    return out


def _simplify(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Drop points within ``tol`` of the chord of their neighbours (Ramer-Douglas-Peucker)."""
    if len(pts) <= 2:
        return pts
    ax, ay = pts[0]
    bx, by = pts[-1]
    lx, ly = bx - ax, by - ay
    ln = math.hypot(lx, ly)
    best, bi = -1.0, 0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        d = abs((px - ax) * ly - (py - ay) * lx) / ln if ln > 1e-12 else math.hypot(px - ax, py - ay)
        if d > best:
            best, bi = d, i
    if best <= tol:
        return [pts[0], pts[-1]]
    return _simplify(pts[: bi + 1], tol)[:-1] + _simplify(pts[bi:], tol)


def render(step: str, info: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any]:
    """The thumbnail SVG of one part snapshot. ``opts``: ``dir`` / ``up`` (the view, ICD part frame), ``box``
    ([x0, y0, z0, x1, y1, z1], the region framed: the item's envelope, so the placeholder and the real part line
    up), ``frame`` ({R, t}: the part as modelled -> the ICD part frame, or None). Returns {svg, groups, edges}."""
    import numpy as np
    from build123d import Vector

    from aicad.drawing.geometry import load_solid
    from aicad.recognize import topo_faces

    shape = load_solid(step)
    of, groups = classify(shape, info)
    xi, ui, di = axes(opts.get("dir") or (1, -1, 1), opts.get("up") or (0, 0, 1))
    fr = opts.get("frame") or None
    R = fr["R"] if fr else [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    t = fr["t"] if fr else [0.0, 0.0, 0.0]
    xm, um, dm = _mat_t(R, xi), _mat_t(R, ui), _mat_t(R, di)  # the same view, seen from the part as modelled
    ou, ov = _dot(t, xi), _dot(t, ui)

    # 3D edges with the group of their most specific face, projected (the same orthographic map as HLR)
    edge_group: dict[Any, int] = {}
    face_groups_of_edge: dict[Any, set[int]] = {}
    for fi, f in enumerate(topo_faces(shape)):
        g = of[fi]
        for e in f.edges():
            cur = edge_group.get(e)
            if cur is None or PRIORITY[groups[g]["kind"]] > PRIORITY[groups[cur]["kind"]]:
                edge_group[e] = g
            face_groups_of_edge.setdefault(e, set()).add(g)
    seg_a: list[tuple[float, float]] = []
    seg_b: list[tuple[float, float]] = []
    seg_e: list[int] = []
    edges = list(edge_group)
    for k, e in enumerate(edges):
        pts = [(_dot(p, xm) + ou, _dot(p, um) + ov) for p in _edge_points(e)]
        for a, b in itertools.pairwise(pts):
            seg_a.append(a)
            seg_b.append(b)
            seg_e.append(k)
    A = np.array(seg_a or [(0.0, 0.0)], dtype=float)
    B = np.array(seg_b or [(0.0, 0.0)], dtype=float)
    E = np.array(seg_e or [-1], dtype=int)
    AB = B - A
    L2 = np.maximum((AB * AB).sum(axis=1), 1e-18)

    box = opts.get("box")
    if box:
        corners = [(box[i], box[j], box[k]) for i in (0, 3) for j in (1, 4) for k in (2, 5)]
    else:
        bb = shape.bounding_box()
        corners = [(_dot(p, R[0]) + t[0], _dot(p, R[1]) + t[1], _dot(p, R[2]) + t[2])
                   for p in [(x, y, z) for x in (bb.min.X, bb.max.X) for y in (bb.min.Y, bb.max.Y)
                             for z in (bb.min.Z, bb.max.Z)]]
    us = [_dot(c, xi) for c in corners]
    vs = [_dot(c, ui) for c in corners]
    span = max(max(us) - min(us), max(vs) - min(vs), 1e-6)
    tol = max(span * 0.004, 1e-4)

    def near(p: tuple[float, float]) -> np.ndarray:
        P = np.array(p, dtype=float)
        w = np.clip(((P - A) * AB).sum(axis=1) / L2, 0.0, 1.0)
        q = A + AB * w[:, None]
        return np.hypot(q[:, 0] - P[0], q[:, 1] - P[1])

    def faces_at(p: tuple[float, float]) -> set[int]:
        dist = near(p)
        out: set[int] = set()
        for k in {int(x) for x in E[dist <= tol * 1.5] if x >= 0}:
            out |= face_groups_of_edge[edges[k]]
        return out

    # the hidden-line projection of the part as modelled (look-at its centre), shifted to absolute view coordinates
    bbm = shape.bounding_box()
    c = bbm.center()
    dist = 10.0 * max(bbm.diagonal, 1.0)
    origin = Vector(c.X + dm[0] * dist, c.Y + dm[1] * dist, c.Z + dm[2] * dist)
    vis, hid = shape.project_to_viewport(origin, Vector(*um), c)
    du, dv = _dot((c.X, c.Y, c.Z), xm) + ou, _dot((c.X, c.Y, c.Z), um) + ov

    s = (VIEWBOX - 2 * PAD) / span
    uc, vc = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2

    def to_svg(u: float, v: float) -> tuple[float, float]:
        return (round(VIEWBOX / 2 + (u - uc) * s, 1), round(VIEWBOX / 2 - (v - vc) * s, 1))

    paths: dict[tuple[int, bool], list[str]] = {}
    placed = unplaced = 0
    for hidden, es in ((False, vis), (True, hid)):
        for e in es:
            pts3 = _edge_points(e, 32)
            pts = [(p[0] + du, p[1] + dv) for p in pts3]
            if len(pts) < 2:
                continue
            votes: dict[int, int] = {}
            for fr_ in (0.25, 0.5, 0.75):
                q = pts[min(len(pts) - 1, round(fr_ * (len(pts) - 1)))]
                dist_ = near(q)
                k = int(np.argmin(dist_))
                if dist_[k] <= tol and E[k] >= 0:
                    g = edge_group[edges[int(E[k])]]
                    votes[g] = votes.get(g, 0) + 1
            g_: int | None = None
            if votes and max(votes.values()) >= 2:
                g_ = max(votes, key=lambda g: (votes[g], PRIORITY[groups[g]["kind"]], -g))
            else:  # a silhouette of a curved face: the group its two ends share
                common = faces_at(pts[0]) & faces_at(pts[-1])
                if common:
                    g_ = max(common, key=lambda g: (PRIORITY[groups[g]["kind"]], -g))
            if g_ is None:
                g_ = 0
                unplaced += 1
            else:
                placed += 1
            sv = _simplify([to_svg(*p) for p in pts], 0.12)
            d = "M" + " L".join(f"{x:g} {y:g}" for x, y in sv)
            paths.setdefault((g_, hidden), []).append(d)
    svg = _compose(groups, paths, opts, hidden=True)
    if len(svg) > MAX_BYTES:
        svg = _compose(groups, paths, opts, hidden=False)
    return {"svg": svg, "groups": len(groups), "placed": placed, "unplaced": unplaced}


def _compose(groups: list[dict[str, Any]], paths: dict[tuple[int, bool], list[str]], opts: dict[str, Any],
             hidden: bool) -> str:
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEWBOX:g} {VIEWBOX:g}" data-fw-thumb="{VERSION}"'
            f' data-view="{_attr(opts.get("name") or "iso")}" fill="none" stroke="currentColor" stroke-width="1.2"'
            ' stroke-linecap="round" stroke-linejoin="round">')
    out = [head]
    order = sorted(range(len(groups)), key=lambda g: (PRIORITY[groups[g]["kind"]], g))
    for g in order:
        vis, hid = paths.get((g, False)) or [], (paths.get((g, True)) or []) if hidden else []
        if not vis and not hid:
            continue
        d = f' data-d="{groups[g]["d"]:g}"' if groups[g].get("d") is not None else ""
        out.append(f'<g data-feature="{groups[g]["kind"]}" data-g="{g}"{d}>')
        if hid:
            out.append(f'<path data-hidden="1" stroke-width=".7" stroke-opacity=".45" stroke-dasharray="2 1.6"'
                       f' vector-effect="non-scaling-stroke" d="{" ".join(sorted(hid))}"/>')
        if vis:
            out.append(f'<path vector-effect="non-scaling-stroke" d="{" ".join(sorted(vis))}"/>')
        out.append("</g>")
    out.append("</svg>")
    return "".join(out)


def _attr(s: str) -> str:
    return "".join(ch for ch in str(s) if ch.isalnum() or ch in "-_")[:24]


def write(step: str, info: dict[str, Any], opts: dict[str, Any], dest: str) -> dict[str, Any]:
    """Render and write the SVG atomically (the cache file is complete or absent)."""
    res = render(step, info, opts)
    p = Path(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(res["svg"], encoding="utf-8")
    os.replace(tmp, p)
    return {k: v for k, v in res.items() if k != "svg"} | {"bytes": len(res["svg"])}
