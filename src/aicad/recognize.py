"""Feature recognition for imported (dumb) STEP solids.

Reads the exact B-rep and reports what a mechanical engineer would call features:
base stock (prismatic block or turned/cylindrical), holes (diameter, axis, depth, through/blind, entry point),
hole patterns (linear / circular), cylindrical bosses, fillets and chamfers. The report drives:

- a deterministic *parametric draft* (`draft_model`): stock minus recognised holes, with every size a PARAM,
  verified against the reference by CHK-09 (symmetric-difference volume);
- a structured prompt for the design agent to rebuild the remaining features faithfully.

Recognition is heuristic and conservative: anything it cannot classify is listed under `unrecognised` so the
engineer (or the agent) knows the draft is incomplete instead of silently dropping geometry.
"""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from typing import Any

from build123d import Shape
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Torus

TOL = 1e-3


def _r(x: float, n: int = 3) -> float:
    return round(float(x), n) + 0.0


def _v(p: Any) -> list[float]:
    return [_r(p.X), _r(p.Y), _r(p.Z)]


# Bump when recognised results change for the same geometry: cached part snapshots (assembly.store) are re-made.
# 2: cylinder extents along the canonical axis (negative-axis holes were mirrored: wrong centre and through flag).
# 3: internal (ring) gears recognised (component kind "internal_gear"); the bounding-box axes are always tried.
VERSION = 3


def _axis_key(d: tuple[float, float, float]) -> tuple[float, float, float]:
    """Direction with a canonical sign (so +Z and -Z holes group together)."""
    x, y, z = d
    for c in (x, y, z):
        if abs(c) > 1e-6:
            if c < 0:
                x, y, z = -x, -y, -z
            break
    return (_r(x, 4), _r(y, 4), _r(z, 4))


def _dot(a: Any, b: Any) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a: Any, b: Any) -> list[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _norm(a: Any) -> float:
    return math.sqrt(_dot(a, a))


def _foot(p: Any, origin: Any, d: Any) -> list[float]:
    """Projection of point p onto the line (origin, d)."""
    t = _dot(_sub(p, origin), d)
    return [origin[i] + t * d[i] for i in range(3)]


def _extent_along(shape: Shape, origin: Any, d: Any) -> tuple[float, float]:
    vals = [_dot(_sub([v.X, v.Y, v.Z], origin), d) for v in shape.vertices()]
    if not vals:
        bb = shape.bounding_box()
        corners = [[x, y, z] for x in (bb.min.X, bb.max.X) for y in (bb.min.Y, bb.max.Y) for z in (bb.min.Z, bb.max.Z)]
        vals = [_dot(_sub(c, origin), d) for c in corners]
    return min(vals), max(vals)


def _open_both_ends(shape: Shape, top: Any, bot: Any, d: Any, r: float) -> bool:
    """True when the material just beyond *both* ends of a hole is air: on the axis and at 0.7 r around it (so a
    counterbore's floor or a blind bottom counts as closed, while a smaller coaxial hole beyond does not open it)."""
    from build123d import Vector

    ref = [1.0, 0.0, 0.0] if abs(d[0]) < 0.9 else [0.0, 1.0, 0.0]
    e1 = _sub(ref, [d[k] * _dot(ref, d) for k in range(3)])
    n1 = _norm(e1)
    e1 = [x / n1 for x in e1]
    e2 = [d[1] * e1[2] - d[2] * e1[1], d[2] * e1[0] - d[0] * e1[2], d[0] * e1[1] - d[1] * e1[0]]
    eps = max(0.05, 0.02 * r)
    offs = [[0.0, 0.0, 0.0]] + [[0.7 * r * (math.cos(a) * e1[k] + math.sin(a) * e2[k]) for k in range(3)]
                                for a in (0.0, math.pi / 2, math.pi, 3 * math.pi / 2)]
    for end, sgn in ((top, 1.0), (bot, -1.0)):
        for o in offs:
            p = [end[k] + sgn * d[k] * eps + o[k] for k in range(3)]
            try:
                if shape.is_inside(Vector(*p)):
                    return False
            except Exception:  # noqa: BLE001 - classifier failure: be conservative (blind)
                return False
    return True


def _cyl_info(face: Any) -> dict[str, Any] | None:
    s = BRepAdaptor_Surface(face.wrapped)
    t = s.GetType()
    if t != GeomAbs_Cylinder:
        return None
    cyl = s.Cylinder()
    ax = cyl.Axis()
    d = (ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z())
    o = (ax.Location().X(), ax.Location().Y(), ax.Location().Z())
    r = cyl.Radius()
    span = abs(s.LastUParameter() - s.FirstUParameter())
    c = face.center()
    n = face.normal_at(c)
    foot = _foot([c.X, c.Y, c.Z], o, d)
    radial = _sub([c.X, c.Y, c.Z], foot)
    concave = _dot([n.X, n.Y, n.Z], radial) < 0  # normal points toward the axis -> material outside -> hole
    lo, hi = _extent_along(face, o, d)
    # Report the extent along the canonical direction (the one holes are keyed and measured by): a cylinder built
    # pointing -Y (e.g. Rot(90, 0, 0) * Cylinder) otherwise came back mirrored about its origin, so a blind tapped
    # hole in a gearbox wall read as ending in the cavity and "through" (founder's Gear Reducer, 2026-11-19)
    dk = _axis_key(d)
    if _dot(dk, d) < 0:
        d, lo, hi = (-d[0], -d[1], -d[2]), -hi, -lo
    return {"r": r, "axis": d, "origin": o, "span_deg": math.degrees(span), "concave": concave,
            "lo": lo, "hi": hi, "area": face.area}


def _line_key(o: Any, d: Any) -> tuple[float, ...]:
    """Key of an infinite line: canonical direction + foot of perpendicular from the world origin."""
    dk = _axis_key(d)
    f = _foot([0.0, 0.0, 0.0], o, dk)
    return dk + (_r(f[0], 2), _r(f[1], 2), _r(f[2], 2))


STD_MODULES = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0, 4.5, 5.0,
               5.5, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 14.0, 16.0, 18.0, 20.0]


def topo_faces(shape: Shape) -> list[Any]:
    """Faces in exactly the order topo.json numbers them (so recognised features can be highlighted)."""
    kids = [c for c in (getattr(shape, "children", None) or ()) if c.solids()]
    bodies = kids if kids else (list(shape.solids()) or [shape])
    return [f for b in bodies for f in b.faces()]


def _surface_kind(t: Any) -> str:
    return {GeomAbs_Plane: "plane", GeomAbs_Cylinder: "cylinder", GeomAbs_Cone: "cone", GeomAbs_Torus: "torus"}.get(t, "freeform")


def _rotational(faces: list[Any], cand: list[int], axes: list[tuple[list[float], list[float]]]) -> dict[str, Any] | None:
    """Find the axis about which the most faces repeat in an evenly spaced circular arrangement.
    Returns {axis, origin, n, faces:[fid], groups:[[fid...]...]} for the dominant repetition count."""
    best: dict[str, Any] | None = None
    info = []
    for fid in cand:
        f = faces[fid]
        c = f.center()
        try:
            nv = f.normal_at(c)
            nrm = [nv.X, nv.Y, nv.Z]
        except Exception:  # noqa: BLE001
            nrm = [0.0, 0.0, 0.0]
        info.append((fid, _surface_kind(BRepAdaptor_Surface(f.wrapped).GetType()), f.area, [c.X, c.Y, c.Z], nrm))
    for o, d in axes:
        # in-plane basis
        ref = [1.0, 0.0, 0.0] if abs(d[0]) < 0.9 else [0.0, 1.0, 0.0]
        u = _sub(ref, [d[k] * _dot(ref, d) for k in range(3)])
        un = _norm(u)
        u = [x / un for x in u]
        v = [d[1] * u[2] - d[2] * u[1], d[2] * u[0] - d[0] * u[2], d[0] * u[1] - d[1] * u[0]]
        rows = []
        for fid, kind, area, c, nrm in info:
            rel = _sub(c, o)
            t = _dot(rel, d)
            radial = _sub(rel, [d[k] * t for k in range(3)])
            r = _norm(radial)
            if r < 1e-3:
                continue
            ang = math.degrees(math.atan2(_dot(radial, v), _dot(radial, u))) % 360
            ru = [x / r for x in radial]
            tu = [d[1] * ru[2] - d[2] * ru[1], d[2] * ru[0] - d[0] * ru[2], d[0] * ru[1] - d[1] * ru[0]]
            # orientation of the face relative to the axis: separates mirrored flanks (left/right of a tooth)
            orient = (_dot(nrm, ru), _dot(nrm, tu), _dot(nrm, d))
            rows.append((kind, area, r, t, fid, ang, orient))
        # cluster with tolerances (not rounding: identical faces must never straddle a rounding boundary)
        rows.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
        groups: dict[int, list[tuple[int, float]]] = defaultdict(list)
        reps: list[tuple[Any, ...]] = []
        for kind, area, r, t, fid, ang, orient in rows:
            tol_a = 1e-4 * max(area, 1.0)
            k = next((i for i in range(len(reps) - 1, max(-1, len(reps) - 60), -1)
                      if reps[i][0] == kind and abs(reps[i][1] - area) <= tol_a and abs(reps[i][2] - r) <= 1e-3
                      and abs(reps[i][3] - t) <= 1e-3 and all(abs(a - b) <= 1e-3 for a, b in zip(reps[i][4], orient, strict=True))), None)
            if k is None:
                reps.append((kind, area, r, t, orient))
                k = len(reps) - 1
            groups[k].append((fid, ang))
        by_n: dict[int, list[list[int]]] = defaultdict(list)
        for g in groups.values():
            n = len(g)
            if n < 3:
                continue
            angs = sorted(a for _, a in g)
            gaps = [b - a for a, b in itertools.pairwise(angs)] + [angs[0] + 360 - angs[-1]]
            if max(gaps) - min(gaps) < 0.5:
                by_n[n].append([fid for fid, _ in sorted(g, key=lambda x: x[1])])
        for n, gl in by_n.items():
            covered = sum(len(g) for g in gl)
            if best is None or covered > best["covered"]:
                best = {"axis": [_r(x, 4) for x in d], "origin": [_r(x, 4) for x in o], "n": n, "groups": gl,
                        "faces": sorted(f for g in gl for f in g), "covered": covered}
    return best


def _radii(faces: list[Any], fids: list[int], o: list[float], d: list[float]) -> tuple[float, float]:
    rs = []
    for fid in fids:
        for vx in faces[fid].vertices():
            rel = _sub([vx.X, vx.Y, vx.Z], o)
            t = _dot(rel, d)
            rs.append(_norm(_sub(rel, [d[k] * t for k in range(3)])))
    return (min(rs), max(rs)) if rs else (0.0, 0.0)


def _internal_band(shape: Shape, faces: list[Any], fids: list[int], o: list[float], d: list[float], rmin: float,
                   rmax: float) -> bool:
    """The repeated band is an internal gear's teeth: across the band's axial middle, just inside its inner radius
    is air and just outside its outer radius is material (the rim). An external gear is the other way round."""
    from build123d import Vector

    ts = []
    for fid in fids:
        c = faces[fid].center()
        ts.append(_dot(_sub([c.X, c.Y, c.Z], o), d))
    if not ts or rmax - rmin < 1e-3:
        return False
    t = (min(ts) + max(ts)) / 2
    ref = [1.0, 0.0, 0.0] if abs(d[0]) < 0.9 else [0.0, 1.0, 0.0]
    u = _sub(ref, [d[k] * _dot(ref, d) for k in range(3)])
    un = _norm(u)
    u = [x / un for x in u]
    v = [d[1] * u[2] - d[2] * u[1], d[2] * u[0] - d[0] * u[2], d[0] * u[1] - d[1] * u[0]]
    eps = 0.05 * (rmax - rmin)

    def solid_at(r: float) -> list[bool]:
        out = []
        for k in range(6):  # several angles: one probe could land on a hole
            a = 2 * math.pi * (k + 0.37) / 6
            p = [o[i] + d[i] * t + r * (math.cos(a) * u[i] + math.sin(a) * v[i]) for i in range(3)]
            try:
                out.append(bool(shape.is_inside(Vector(*p))))
            except Exception:  # noqa: BLE001
                out.append(False)
        return out

    inside, outside = solid_at(rmin - eps), solid_at(rmax + eps)
    return not any(inside) and sum(outside) >= 4


def recognize(shape: Shape) -> dict[str, Any]:
    bb = shape.bounding_box()
    size = [bb.size.X, bb.size.Y, bb.size.Z]
    solids = shape.solids()
    vol = shape.volume
    faces = topo_faces(shape)
    total_area = shape.area
    cls: dict[int, str] = {}  # fid -> feature id (assigned faces)

    holes_raw: dict[tuple[Any, ...], dict[str, Any]] = {}
    bosses_raw: dict[tuple[Any, ...], dict[str, Any]] = {}
    fillet_faces: list[tuple[int, dict[str, Any]]] = []
    chamfer_faces: list[tuple[int, dict[str, Any]]] = []
    planar_faces: list[int] = []
    other: dict[int, str] = {}
    axes: list[tuple[list[float], list[float]]] = []
    planar = 0

    for fid, f in enumerate(faces):
        s = BRepAdaptor_Surface(f.wrapped)
        t = s.GetType()
        if t == GeomAbs_Plane:
            planar += 1
            n = f.normal_at(f.center())
            comps = sorted(abs(c) for c in (n.X, n.Y, n.Z))
            if comps[-1] < 0.999 and f.area < 0.02 * total_area:
                chamfer_faces.append((fid, {"normal": [_r(n.X), _r(n.Y), _r(n.Z)], "area_mm2": _r(f.area, 2),
                                            "angle_deg": _r(math.degrees(math.acos(min(1.0, comps[-1]))), 1)}))
            else:
                planar_faces.append(fid)
            continue
        if t == GeomAbs_Cylinder:
            ci = _cyl_info(f)
            assert ci is not None
            axes.append((list(ci["origin"]), list(_axis_key(ci["axis"]))))
            key = _line_key(ci["origin"], ci["axis"]) + (_r(ci["r"], 3),)
            if ci["span_deg"] < 179.0:
                if ci["span_deg"] <= 95.0 and ci["r"] <= 0.5 * max(size):
                    fillet_faces.append((fid, {"r": _r(ci["r"]), "convex": not ci["concave"]}))
                else:
                    other[fid] = "partial cylinder"
                continue
            bucket = holes_raw if ci["concave"] else bosses_raw
            g = bucket.setdefault(key, {"r": ci["r"], "axis": ci["axis"], "origin": ci["origin"], "lo": ci["lo"],
                                        "hi": ci["hi"], "span": 0.0, "fids": []})
            g["lo"], g["hi"] = min(g["lo"], ci["lo"]), max(g["hi"], ci["hi"])
            g["span"] += ci["span_deg"]
            g["fids"].append(fid)
            continue
        if t == GeomAbs_Torus:
            fillet_faces.append((fid, {"r": _r(s.Torus().MinorRadius()), "convex": None}))
            continue
        if t == GeomAbs_Cone:
            other[fid] = "conical face (countersink / tapered feature)"
            continue
        other[fid] = "freeform face"

    def finish(g: dict[str, Any], hole: bool = True) -> dict[str, Any]:
        d = _axis_key(g["axis"])
        o = g["origin"]
        mid_t = (g["lo"] + g["hi"]) / 2
        f0 = _foot([0.0, 0.0, 0.0], o, d)
        base_t = _dot(_sub(o, f0), d)
        c = [f0[i] + d[i] * (base_t + mid_t) for i in range(3)]
        depth = g["hi"] - g["lo"]
        top = [c[i] + d[i] * (depth / 2) for i in range(3)]
        bot = [c[i] - d[i] * (depth / 2) for i in range(3)]
        from build123d import Vector

        if hole:
            # through = both ends of this hole open to air *locally* (AMI-02): a hole through a 5 mm bracket leg is
            # through even though the part is 40 mm tall along that axis
            through = _open_both_ends(shape, top, bot, d, g["r"])
        else:
            plo, phi = _extent_along(shape, c, d)
            through = abs(depth - (phi - plo)) < 0.05

        if through:
            open_end, into = bot, list(d)
        else:
            beyond = [top[i] + d[i] * 0.05 for i in range(3)]
            try:
                top_closed = shape.is_inside(Vector(*beyond))
            except Exception:  # noqa: BLE001
                top_closed = False
            open_end, into = (bot, list(d)) if top_closed else (top, [-x for x in d])
        return {"d": _r(2 * g["r"], 4), "axis": [_r(x, 4) for x in d], "center": [_r(x) for x in c],
                "top": [_r(x) for x in top], "bottom": [_r(x) for x in bot], "depth": _r(depth, 4), "through": bool(through),
                "full": g["span"] >= 359.0, "faces": g["fids"], "open": [_r(x, 4) for x in open_end],
                "dir": [_r(x, 6) for x in into]}

    holes = sorted((finish(g) for g in holes_raw.values()), key=lambda h: (h["d"], h["center"]))
    bosses = sorted((finish(g, hole=False) for g in bosses_raw.values()), key=lambda h: -h["d"])
    hole_fids = {f for h in holes for f in h["faces"]}

    # ---- rotational repetition (gear teeth, splines, spokes, slots around an axis)
    bc = [(bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2, (bb.min.Z + bb.max.Z) / 2]
    cand_axes = [*axes, (bc, [1.0, 0.0, 0.0]), (bc, [0.0, 1.0, 0.0]), (bc, [0.0, 0.0, 1.0])]
    seen: set[tuple[float, ...]] = set()
    uniq = []
    for o, d in cand_axes:
        k = _line_key(o, d)
        if k not in seen:
            seen.add(k)
            uniq.append((o, d))
    # the first 12 axes, and always the bounding box's three (a ring gear with many bolt holes has more than 12 axes
    # before them: its own axis must still be tried)
    tried = uniq[:12] + [a for a in uniq[12:] if a[0] is bc]
    rot = _rotational(faces, [i for i in range(len(faces)) if i not in hole_fids], tried) if len(faces) >= 12 else None
    component: dict[str, Any] | None = None
    features: list[dict[str, Any]] = []
    if rot and rot["n"] >= 3 and rot["covered"] >= max(6, 2 * rot["n"]):
        o, d, n = rot["origin"], rot["axis"], rot["n"]
        rmin, rmax = _radii(faces, rot["faces"], o, d)
        lo, hi = _extent_along(shape, o, d)
        part_rmax = _radii(faces, list(range(len(faces))), o, d)[1]
        outer = abs(rmax - part_rmax) < 0.01 * part_rmax + 1e-6
        internal = not outer and n >= 8 and _internal_band(shape, faces, rot["faces"], o, d, rmin, rmax)
        if internal:
            # an internal (ring) gear: tip circle inside (Ø m (z - 2)), root outside (Ø m (z + 2.5)); the module from
            # both (tip + root = m (2z + 0.5)), so a modified tip alone doesn't throw it off
            m_est = 2 * (rmin + rmax) / (2 * n + 0.5)
            m_std = min(STD_MODULES, key=lambda m: abs(m - m_est))
            params = {"teeth": n, "tip_d": _r(2 * rmin), "root_d": _r(2 * rmax), "module_est": _r(m_est, 3),
                      "module": m_std if abs(m_std - m_est) / m_est < 0.03 else _r(m_est, 3),
                      "face_width": _r(hi - lo), "rim_d": _r(2 * part_rmax), "internal": True, "bore_d": None}
            component = {"kind": "internal_gear", "name": f"Internal gear, {n} teeth, module ≈ {params['module']}",
                         "confidence": "geometric", "params": params, "axis": d, "origin": o}
            feat = {"id": "teeth", "name": f"Internal teeth ({n} × circular pattern)", "kind": "gear_teeth",
                    "count": n, "params": {k: params[k] for k in ("teeth", "tip_d", "root_d", "module", "internal")},
                    "faces": rot["faces"]}
        elif outer and n >= 8:
            m_est = 2 * rmax / (n + 2)
            m_std = min(STD_MODULES, key=lambda m: abs(m - m_est))
            bore = min((h for h in holes if h["full"] and _norm(_sub(_foot(o, h["center"], h["axis"]), o)) < 0.05),
                       key=lambda h: h["d"], default=None)
            params = {"teeth": n, "tip_d": _r(2 * rmax), "root_d": _r(2 * rmin), "module_est": _r(m_est, 3),
                      "module": m_std if abs(m_std - m_est) / m_est < 0.03 else _r(m_est, 3),
                      "face_width": _r(hi - lo), "bore_d": bore["d"] if bore else None}
            component = {"kind": "spur_gear", "name": f"Spur gear, {n} teeth, module ≈ {params['module']}",
                         "confidence": "geometric", "params": params, "axis": d, "origin": o}
            feat = {"id": "teeth", "name": f"Teeth ({n} × circular pattern)", "kind": "gear_teeth", "count": n,
                    "params": {k: params[k] for k in ("teeth", "tip_d", "root_d", "module")}, "faces": rot["faces"]}
        else:
            feat = {"id": "rot", "name": f"Circular pattern ({n} ×)", "kind": "circular_pattern", "count": n,
                    "params": {"r_min": _r(rmin), "r_max": _r(rmax)}, "faces": rot["faces"]}
        # faces lying entirely in the patterned band (root fillets, land segments) belong to the same feature
        band = set(rot["faces"])
        for fid in range(len(faces)):
            if fid in band or fid in hole_fids:
                continue
            a_lo, a_hi = _radii(faces, [fid], o, d)
            if a_lo >= rmin - 1e-3 and a_hi <= rmax + 1e-3:
                band.add(fid)
        feat["faces"] = sorted(band)
        features.append(feat)
        for fid in band:
            cls[fid] = feat["id"]

    # ---- holes and hole patterns
    patterns = _patterns(holes)
    in_pat = set()
    for k, p in enumerate(patterns):
        fids = [f for i in p["holes"] for f in holes[i]["faces"]]
        in_pat |= set(p["holes"])
        label = {"circular": f"{p['count']} × Ø{p['d']} holes on Ø{p.get('pcd')} PCD", "grid": f"{p['count']} × Ø{p['d']} holes ({p.get('cols')} × {p.get('rows')} grid)",
                 "linear": f"{p['count']} × Ø{p['d']} holes in line"}.get(p["kind"], f"{p['count']} × Ø{p['d']} holes")
        features.append({"id": f"hp{k + 1}", "name": label, "kind": f"hole_pattern_{p['kind']}", "count": p["count"],
                         "params": {x: p[x] for x in ("d", "pcd", "pitch", "center") if x in p}, "faces": fids,
                         "holes": [_hole_entry(holes[i]) for i in p["holes"]]})
        for f in fids:
            cls[f] = f"hp{k + 1}"
    for i, h in enumerate(holes):
        if i in in_pat:
            continue
        is_bore = component is not None and component["params"].get("bore_d") == h["d"]
        fid = "bore" if is_bore else f"h{i + 1}"
        features.append({"id": fid, "name": f"{'Bore' if is_bore else 'Hole'} Ø{h['d']} {'through' if h['through'] else 'blind ' + str(h['depth'])}",
                         "kind": "bore" if is_bore else "hole", "params": {"d": h["d"], "depth": h["depth"], "through": h["through"]},
                         "faces": h["faces"], "holes": [_hole_entry(h)]})
        for f in h["faces"]:
            cls.setdefault(f, fid)
    for i, b in enumerate(bosses):
        features.append({"id": f"b{i + 1}", "name": f"Cylindrical face Ø{b['d']}", "kind": "boss", "params": {"d": b["d"], "length": b["depth"]},
                         "faces": b["faces"]})
        for f in b["faces"]:
            cls.setdefault(f, f"b{i + 1}")

    # ---- remaining fillets / chamfers / planar body faces (not already part of a pattern)
    fil = [(fid, x) for fid, x in fillet_faces if fid not in cls]
    for r in sorted({x["r"] for _, x in fil}):
        fids = [fid for fid, x in fil if x["r"] == r]
        features.append({"id": f"fil{r}", "name": f"Fillet R{r} ({len(fids)} faces)", "kind": "fillet", "params": {"r": r}, "faces": fids})
        for f in fids:
            cls[f] = f"fil{r}"
    ch = [fid for fid, _ in chamfer_faces if fid not in cls]
    if ch:
        features.append({"id": "chamfers", "name": f"Chamfers ({len(ch)} faces)", "kind": "chamfer", "params": {}, "faces": ch})
        for f in ch:
            cls[f] = "chamfers"
    body = [fid for fid in planar_faces if fid not in cls]
    if body:
        features.append({"id": "body", "name": "Body faces (planar)", "kind": "body", "params": {}, "faces": body})
        for f in body:
            cls[f] = "body"
    unrec_ids = [i for i in range(len(faces)) if i not in cls]
    unrecognised: dict[str, int] = defaultdict(int)
    for i in unrec_ids:
        unrecognised[other.get(i, "face")] += 1
    if unrec_ids:
        features.append({"id": "unrecognised", "name": f"Not recognised ({len(unrec_ids)} faces)", "kind": "unrecognised",
                         "params": {}, "faces": unrec_ids})

    from aicad.fw import face_key

    for feat in features:
        ks: list[list[Any]] = []
        seen_k: set[tuple[Any, ...]] = set()
        for fid in feat["faces"]:
            try:
                k = face_key(faces[fid])
            except Exception:  # noqa: BLE001,S112
                continue
            if k not in seen_k:
                seen_k.add(k)
                ks.append(list(k))
        feat["keys"] = ks

    fillets_g: dict[tuple[Any, ...], dict[str, Any]] = {}
    for fid, x in fillet_faces:
        if cls.get(fid, "").startswith("fil"):
            e = fillets_g.setdefault((x["r"], x["convex"]), {"r": x["r"], "convex": x["convex"], "count": 0})
            e["count"] += 1
    chamfer_g: dict[float, dict[str, Any]] = {}
    for fid, x in chamfer_faces:
        if cls.get(fid) == "chamfers":
            e = chamfer_g.setdefault(x["angle_deg"], {"angle_deg": x["angle_deg"], "count": 0})
            e["count"] += 1

    stock = _stock(shape, size, bosses, vol)
    rec = {
        "bbox": [_r(x) for x in size], "bbox_min": _v(bb.min), "volume_mm3": _r(vol, 2), "area_mm2": _r(total_area, 2),
        "solids": len(solids), "faces": len(faces), "planar_faces": planar,
        "stock": stock, "holes": [{k: v for k, v in h.items() if k != "faces"} for h in holes], "patterns": patterns,
        "bosses": [{k: v for k, v in b.items() if k != "faces"} for b in (bosses[1:] if stock["kind"] == "turned" else bosses)],
        "fillets": sorted(fillets_g.values(), key=lambda e: -e["count"]), "chamfers": list(chamfer_g.values()),
        "unrecognised": dict(unrecognised), "component": component, "features": features,
    }
    rec["summary"] = summary(rec)
    return rec


def _hole_entry(h: dict[str, Any]) -> dict[str, Any]:
    return {k: h[k] for k in ("d", "depth", "through", "open", "dir", "center")}


def _stock(shape: Shape, size: list[float], bosses: list[dict[str, Any]], vol: float) -> dict[str, Any]:
    if bosses:
        b = bosses[0]
        ax = b["axis"]
        i = max(range(3), key=lambda k: abs(ax[k]))
        others = [size[k] for k in range(3) if k != i]
        if abs(ax[i]) > 0.999 and all(abs(o - b["d"]) < 0.05 for o in others):
            return {"kind": "turned", "d": b["d"], "length": _r(size[i]), "axis": "XYZ"[i]}
    fill = vol / max(size[0] * size[1] * size[2], 1e-9)
    return {"kind": "prismatic", "size": [_r(x) for x in size], "fill_ratio": _r(fill, 3)}


def _patterns(holes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group equal holes (same Ø, axis, depth) and classify as circular or linear patterns."""
    groups: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    for i, h in enumerate(holes):
        groups[(h["d"], tuple(h["axis"]), h["depth"], h["through"])].append(i)
    out: list[dict[str, Any]] = []
    for (d, axis, _depth, _thr), idx in groups.items():
        if len(idx) < 2:
            continue
        pts = [holes[i]["center"] for i in idx]
        cen = [sum(p[k] for p in pts) / len(pts) for k in range(3)]
        # rectangular grid in an axis-aligned plane (checked first: a 2x2 grid is also concyclic)
        ai = max(range(3), key=lambda k: abs(axis[k]))
        if abs(axis[ai]) > 0.999:
            u_i, v_i = [k for k in range(3) if k != ai]
            us = sorted({_r(p[u_i], 2) for p in pts})
            vs = sorted({_r(p[v_i], 2) for p in pts})
            if len(us) >= 2 and len(vs) >= 2 and len(us) * len(vs) == len(pts):
                du = [b - a for a, b in itertools.pairwise(us)]
                dv = [b - a for a, b in itertools.pairwise(vs)]
                if max(du) - min(du) < 0.02 and max(dv) - min(dv) < 0.02:
                    out.append({"kind": "grid", "d": d, "count": len(pts), "rows": len(vs), "cols": len(us),
                                "pitch": [_r(du[0]), _r(dv[0])], "axes": ["XYZ"[u_i], "XYZ"[v_i]], "axis": list(axis), "holes": idx})
                    continue
        rads = [_norm(_sub(p, cen)) for p in pts]
        if len(pts) >= 3 and max(rads) - min(rads) < 0.02 and min(rads) > 1e-3:
            out.append({"kind": "circular", "d": d, "count": len(pts), "pcd": _r(2 * rads[0]), "center": [_r(x) for x in cen],
                        "axis": list(axis), "holes": idx})
            continue
        # linear: all collinear and equally spaced
        p0 = pts[0]
        far = max(pts, key=lambda p: _norm(_sub(p, p0)))
        dirv = _sub(far, p0)
        L = _norm(dirv)
        if L > 1e-6:
            u = [x / L for x in dirv]
            ts = sorted(_dot(_sub(p, p0), u) for p in pts)
            off = max(_norm(_sub(_sub(p, p0), [u[k] * _dot(_sub(p, p0), u) for k in range(3)])) for p in pts)
            gaps = [b - a for a, b in itertools.pairwise(ts)]
            if off < 0.02 and max(gaps) - min(gaps) < 0.02:
                out.append({"kind": "linear", "d": d, "count": len(pts), "pitch": _r(gaps[0]), "direction": [_r(x, 4) for x in u],
                            "axis": list(axis), "holes": idx})
                continue
        # rectangular grid / arbitrary set of equal holes
        out.append({"kind": "set", "d": d, "count": len(pts), "axis": list(axis), "holes": idx})
    return out


def summary(rec: dict[str, Any]) -> list[str]:
    s = rec["stock"]
    comp = rec.get("component")
    head = [f"Component: {comp['name']}"] if comp else []
    lines = head + [f"Stock: {'turned Ø' + str(s['d']) + ' × ' + str(s['length']) + ' mm along ' + s['axis'] if s['kind'] == 'turned' else 'prismatic ' + ' × '.join(str(x) for x in s['size']) + ' mm'}"]
    in_pat = {i for p in rec["patterns"] for i in p["holes"]}
    for p in rec["patterns"]:
        if p["kind"] == "circular":
            lines.append(f"{p['count']} × Ø{p['d']} holes on a Ø{p['pcd']} pitch circle")
        elif p["kind"] == "grid":
            lines.append(f"{p['count']} × Ø{p['d']} holes in a {p['cols']} × {p['rows']} grid, pitch {p['pitch'][0]} × {p['pitch'][1]} mm")
        elif p["kind"] == "linear":
            lines.append(f"{p['count']} × Ø{p['d']} holes in a line, pitch {p['pitch']} mm")
        else:
            lines.append(f"{p['count']} × Ø{p['d']} holes")
    for i, h in enumerate(rec["holes"]):
        if i not in in_pat:
            lines.append(f"Ø{h['d']} {'through' if h['through'] else 'blind ' + str(h['depth']) + ' mm deep'} hole at {h['center']}")
    for b in rec["bosses"]:
        lines.append(f"Cylindrical boss/feature Ø{b['d']} × {b['depth']} mm")
    for f in rec["fillets"]:
        lines.append(f"{f['count']} × R{f['r']} {'external ' if f['convex'] else 'internal ' if f['convex'] is False else ''}fillet face(s)")
    for c in rec["chamfers"]:
        lines.append(f"{c['count']} × chamfer face(s) at {c['angle_deg']}°")
    for f in rec.get("features", []):
        if f["kind"] in ("gear_teeth", "circular_pattern"):
            lines.append(f["name"] + ": " + ", ".join(f"{k} {v}" for k, v in f["params"].items()))
    for k, n in rec["unrecognised"].items():
        lines.append(f"Not recognised: {n} × {k}")
    return lines


def agent_prompt(rec: dict[str, Any]) -> str:
    import json

    return (
        "Rebuild the imported STEP part as a clean parametric model. The original is kept at the path in "
        "REFERENCE_STEP (do not delete it; keep `REFERENCE_STEP = ...` in model.py so check CHK-09 compares your "
        "model against it). Feature recognition found:\n- " + "\n- ".join(rec["summary"]) +
        "\n\nFull recognition data (mm):\n```json\n" + json.dumps(
            {k: rec[k] for k in ("bbox", "bbox_min", "volume_mm3", "stock", "holes", "patterns", "bosses", "fillets",
                                 "chamfers", "unrecognised")}, indent=1)[:12000] + "\n```\n"
        "Model it with real design intent (stock, pockets, hole patterns as patterns, fillets/chamfers last), "
        "expose the driving dimensions as PARAMS with PARAM_META, record each feature with fw.feature, and iterate "
        "until CHK-09 shows the symmetric difference with the reference is ~0. Report anything you could not match."
    )


def _pid(fid: str) -> str:
    return "".join(c for c in fid.upper() if c.isalnum()) or "F"


def import_model(rec: dict[str, Any], name: str, reference: str, recognition: str, filename: str = "") -> str:
    """model.py for an imported STEP: the exact imported solid ("Imported blank") + recognised features as
    annotated tree entries; recognised holes/patterns are editable parameters (fill-and-recut on the exact body).
    At default values the result is exactly the imported solid."""
    comp = rec.get("component")
    lines = [f'"""Imported STEP{": " + filename if filename else ""}, exact solid with recognised features.',
             "",
             "The imported body is kept exactly (\"Imported blank\"); geometry that was not recognised stays part of it.",
             "Recognised: " + "; ".join(rec.get("summary", [])[:10]),
             '"""',
             "import math",
             "",
             "from aicad import fw",
             "",
             f"NAME = {name!r}",
             'MATERIAL = "unspecified"',
             "IMPORTED = True",
             f"REFERENCE_STEP = {reference!r}",
             f"RECOGNITION = {recognition!r}  # recognised features (faces, parameters) for the tree and the design agent",
             ]
    if comp:
        lines.append(f"COMPONENT = {{'kind': {comp['kind']!r}, " + ", ".join(f"{k!r}: {v!r}" for k, v in comp['params'].items()) + "}")
    lines.append("")
    params: list[str] = []
    meta: list[str] = []
    edits: list[str] = []
    vol_terms: list[str] = []
    for f in rec.get("features", []):
        if not f.get("holes"):
            continue
        pid = _pid(f["id"])
        d0 = f["holes"][0]["d"]
        lines.append(f"{pid}_D = {d0}  # {f['name']}: diameter")
        params.append(f"{pid}_D")
        meta.append(f'"{pid}_D": {{"min": 0.1, "unit": "mm", "group": "Recognised features", "label": "{f["name"]} Ø"}}')
        args = f"d={pid}_D"
        pcd = f.get("params", {}).get("pcd")
        if pcd:
            lines.append(f"{pid}_PCD = {pcd}  # {f['name']}: pitch circle diameter")
            params.append(f"{pid}_PCD")
            meta.append(f'"{pid}_PCD": {{"min": 0.1, "unit": "mm", "group": "Recognised features", "label": "{f["name"]} PCD"}}')
            args += f", pcd={pid}_PCD"
        edits.append(f"part = fw.redefine_holes(part, RECOGNITION, {f['id']!r}, {args})")
        depth_sum = sum(h["depth"] for h in f["holes"])
        vol_terms.append(f"math.pi / 4 * ({d0} ** 2 - {pid}_D ** 2) * {round(depth_sum, 4)}")
    lines += ["", "part = fw.imported_blank(REFERENCE_STEP, RECOGNITION)", *edits, "", "result = part", "",
              "PARAMS = dict(" + ", ".join(f"{p}={p}" for p in params) + ")",
              "PARAM_META = {" + ", ".join(meta) + "}",
              "EXPECTED = {" + f'"bbox": {rec["bbox"]}, "volume": {rec["volume_mm3"]}' + "".join(" + " + t for t in vol_terms)
              + f', "volume_tol": 0.001, "solids": {rec["solids"]}' + "}", ""]
    return "\n".join(lines)
