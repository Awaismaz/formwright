"""Feature recognition for imported (dumb) STEP solids.

Reads the exact B-rep and reports what a mechanical engineer would call features:
base stock (prismatic block or turned/cylindrical), holes (diameter, axis, depth, through/blind, entry point),
hole patterns (linear / circular), cylindrical bosses, fillets and chamfers. The report drives:

- a deterministic *parametric draft* (`draft_model`) — stock minus recognised holes, with every size a PARAM,
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
    return {"r": r, "axis": d, "origin": o, "span_deg": math.degrees(span), "concave": concave,
            "lo": lo, "hi": hi, "area": face.area}


def _line_key(o: Any, d: Any) -> tuple[float, ...]:
    """Key of an infinite line: canonical direction + foot of perpendicular from the world origin."""
    dk = _axis_key(d)
    f = _foot([0.0, 0.0, 0.0], o, dk)
    return dk + (_r(f[0], 2), _r(f[1], 2), _r(f[2], 2))


def recognize(shape: Shape) -> dict[str, Any]:
    bb = shape.bounding_box()
    size = [bb.size.X, bb.size.Y, bb.size.Z]
    solids = shape.solids()
    vol = shape.volume
    faces = shape.faces()

    holes_raw: dict[tuple[Any, ...], dict[str, Any]] = {}
    bosses_raw: dict[tuple[Any, ...], dict[str, Any]] = {}
    fillets: list[dict[str, Any]] = []
    chamfers: list[dict[str, Any]] = []
    unrecognised: dict[str, int] = defaultdict(int)
    planar = 0

    for f in faces:
        s = BRepAdaptor_Surface(f.wrapped)
        t = s.GetType()
        if t == GeomAbs_Plane:
            planar += 1
            n = f.normal_at(f.center())
            comps = sorted(abs(c) for c in (n.X, n.Y, n.Z))
            # a narrow planar face whose normal is not axis-aligned -> chamfer candidate
            if comps[-1] < 0.999 and f.area < 0.02 * shape.area:
                chamfers.append({"normal": [_r(n.X), _r(n.Y), _r(n.Z)], "area_mm2": _r(f.area, 2),
                                 "angle_deg": _r(math.degrees(math.acos(min(1.0, comps[-1]))), 1)})
            continue
        if t == GeomAbs_Cylinder:
            ci = _cyl_info(f)
            assert ci is not None
            key = _line_key(ci["origin"], ci["axis"]) + (_r(ci["r"], 3),)
            if ci["span_deg"] < 179.0:  # partial cylinder: fillet (convex or concave), or slot end
                if ci["span_deg"] <= 95.0 and ci["r"] <= 0.5 * max(size):
                    fillets.append({"r": _r(ci["r"]), "convex": not ci["concave"], "length_mm": _r(ci["hi"] - ci["lo"], 2),
                                    "axis": [_r(c, 4) for c in ci["axis"]]})
                else:
                    unrecognised["partial cylinder"] += 1
                continue
            bucket = holes_raw if ci["concave"] else bosses_raw
            g = bucket.setdefault(key, {"r": ci["r"], "axis": ci["axis"], "origin": ci["origin"], "lo": ci["lo"],
                                        "hi": ci["hi"], "span": 0.0})
            g["lo"], g["hi"] = min(g["lo"], ci["lo"]), max(g["hi"], ci["hi"])
            g["span"] += ci["span_deg"]
            continue
        if t == GeomAbs_Torus:
            fillets.append({"r": _r(s.Torus().MinorRadius()), "convex": None, "length_mm": None, "axis": None,
                            "kind": "toroidal (fillet around a round edge)"})
            continue
        if t == GeomAbs_Cone:
            unrecognised["conical face (countersink / tapered feature)"] += 1
            continue
        unrecognised["freeform face"] += 1

    def finish(g: dict[str, Any]) -> dict[str, Any]:
        d = _axis_key(g["axis"])
        o = g["origin"]
        mid_t = (g["lo"] + g["hi"]) / 2
        f0 = _foot([0.0, 0.0, 0.0], o, d)
        # point on the axis at the middle of the cylinder
        base_t = _dot(_sub(o, f0), d)
        c = [f0[i] + d[i] * (base_t + mid_t) for i in range(3)]
        plo, phi = _extent_along(shape, c, d)
        depth = g["hi"] - g["lo"]
        top = [c[i] + d[i] * (depth / 2) for i in range(3)]
        bot = [c[i] - d[i] * (depth / 2) for i in range(3)]
        through = abs(depth - (phi - plo)) < 0.05 or (abs(depth / 2 - phi) < 0.05 and abs(-depth / 2 - plo) < 0.05)
        return {"d": _r(2 * g["r"]), "axis": [_r(x, 4) for x in d], "center": [_r(x) for x in c],
                "top": [_r(x) for x in top], "bottom": [_r(x) for x in bot], "depth": _r(depth), "through": bool(through),
                "full": g["span"] >= 359.0}

    holes = sorted((finish(g) for g in holes_raw.values()), key=lambda h: (h["d"], h["center"]))
    bosses = sorted((finish(g) for g in bosses_raw.values()), key=lambda h: -h["d"])

    patterns = _patterns(holes)
    stock = _stock(shape, size, bosses, vol)
    rec = {
        "bbox": [_r(x) for x in size], "bbox_min": _v(bb.min), "volume_mm3": _r(vol, 2), "area_mm2": _r(shape.area, 2),
        "solids": len(solids), "faces": len(faces), "planar_faces": planar,
        "stock": stock, "holes": holes, "patterns": patterns, "bosses": bosses[1:] if stock["kind"] == "turned" else bosses,
        "fillets": _group_fillets(fillets), "chamfers": _group_chamfers(chamfers), "unrecognised": dict(unrecognised),
    }
    rec["summary"] = summary(rec)
    return rec


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


def _group_fillets(fs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    g: dict[tuple[Any, ...], dict[str, Any]] = {}
    for f in fs:
        k = (f["r"], f.get("convex"))
        e = g.setdefault(k, {"r": f["r"], "convex": f.get("convex"), "count": 0})
        e["count"] += 1
    return sorted(g.values(), key=lambda e: -e["count"])


def _group_chamfers(cs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    g: dict[float, dict[str, Any]] = {}
    for c in cs:
        e = g.setdefault(c["angle_deg"], {"angle_deg": c["angle_deg"], "count": 0})
        e["count"] += 1
    return list(g.values())


def summary(rec: dict[str, Any]) -> list[str]:
    s = rec["stock"]
    lines = [f"Stock: {'turned Ø' + str(s['d']) + ' × ' + str(s['length']) + ' mm along ' + s['axis'] if s['kind'] == 'turned' else 'prismatic ' + ' × '.join(str(x) for x in s['size']) + ' mm'}"]
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
    for k, n in rec["unrecognised"].items():
        lines.append(f"Not recognised: {n} × {k}")
    return lines


# ------------------------------------------------------------------------------------------------ draft model
def draft_model(rec: dict[str, Any], name: str, reference: str) -> str:
    """Deterministic parametric draft: stock minus recognised holes. Every size is an editable PARAM."""
    s = rec["stock"]
    mn = rec["bbox_min"]
    lines = [
        '"""Parametric rebuild of an imported STEP (Formwright feature recognition draft).',
        "",
        "Recognised: " + "; ".join(rec["summary"][:12]),
        '"""',
        "from build123d import *",
        "from aicad import fw",
        "",
        f"NAME = {name!r}",
        'MATERIAL = "unspecified"',
        f"REFERENCE_STEP = {reference!r}  # CHK-09 compares this model against the imported original",
        "",
    ]
    params: list[str] = []
    meta: list[str] = []
    if s["kind"] == "turned":
        lines += [f"STOCK_D = {s['d']}  # stock diameter", f"STOCK_L = {s['length']}  # stock length", ""]
        params += ["STOCK_D", "STOCK_L"]
        meta += ['"STOCK_D": {"min": 0.1, "unit": "mm", "group": "Stock"}', '"STOCK_L": {"min": 0.1, "unit": "mm", "group": "Stock"}']
        ax = s["axis"]
        rot = {"X": "Rot(0, 90, 0)", "Y": "Rot(-90, 0, 0)", "Z": "Rot(0, 0, 0)"}[ax]
        lo = mn["XYZ".index(ax)]
        bbc = [rec["bbox_min"][k] + rec["bbox"][k] / 2 for k in range(3)]
        pos = [bbc[0], bbc[1], bbc[2]]
        pos["XYZ".index(ax)] = lo
        lines += [f"part = Pos({pos[0]}, {pos[1]}, {pos[2]}) * {rot} * Cylinder(STOCK_D / 2, STOCK_L, align=(Align.CENTER, Align.CENTER, Align.MIN))"]
        exp_vol = "math.pi * STOCK_D ** 2 / 4 * STOCK_L"
    else:
        sx, sy, sz = s["size"]
        lines += [f"STOCK_X = {sx}  # stock length X", f"STOCK_Y = {sy}  # stock width Y", f"STOCK_Z = {sz}  # stock height Z", ""]
        params += ["STOCK_X", "STOCK_Y", "STOCK_Z"]
        meta += [f'"STOCK_{a}": {{"min": 0.1, "unit": "mm", "group": "Stock"}}' for a in "XYZ"]
        lines += [f"part = Pos({mn[0]}, {mn[1]}, {mn[2]}) * Box(STOCK_X, STOCK_Y, STOCK_Z, align=(Align.MIN, Align.MIN, Align.MIN))"]
        exp_vol = "STOCK_X * STOCK_Y * STOCK_Z"
    lines.append('part = fw.feature("Stock", part)')
    hole_terms: list[str] = []
    # one diameter PARAM per distinct hole size
    sizes = sorted({h["d"] for h in rec["holes"]})
    for k, d in enumerate(sizes, 1):
        lines.append(f"HOLE{k}_D = {d}  # hole diameter group {k}")
        params.append(f"HOLE{k}_D")
        meta.append(f'"HOLE{k}_D": {{"min": 0.1, "unit": "mm", "group": "Holes"}}')
    for i, h in enumerate(rec["holes"]):
        k = sizes.index(h["d"]) + 1
        a = h["axis"]
        ext = 0.01 if h["through"] else 0.0  # through holes overshoot so no coplanar boolean faces remain
        b = [_r(h["bottom"][j] - a[j] * ext, 4) for j in range(3)]
        lines.append(f"part -= Pos({b[0]}, {b[1]}, {b[2]}) * Plane(origin=(0, 0, 0), z_dir=({a[0]}, {a[1]}, {a[2]})).location * "
                     f"Cylinder(HOLE{k}_D / 2, {_r(h['depth'] + 2 * ext, 4)}, align=(Align.CENTER, Align.CENTER, Align.MIN))  # hole {i + 1}")
        hole_terms.append(f"math.pi * HOLE{k}_D ** 2 / 4 * {h['depth']}")
    if rec["holes"]:
        lines.append('part = fw.feature("Holes", part)')
    lines += ["", "result = part", "",
              "PARAMS = dict(" + ", ".join(f"{p}={p}" for p in params) + ")",
              "PARAM_META = {" + ", ".join(meta) + "}",
              "# Draft: holes are subtracted from the stock; fillets, chamfers, pockets and anything listed as not",
              "# recognised are NOT in this draft yet (ask the design agent to complete it). Volume tolerance is loose.",
              "EXPECTED = {"
              f'"bbox": [{", ".join(str(x) for x in rec["bbox"])}], '
              f'"volume": {exp_vol}' + ("".join(" - " + t for t in hole_terms)) + ', "volume_tol": 0.5, '
              f'"solids": {rec["solids"]}' + "}"]
    src = "\n".join(lines) + "\n"
    if "math." in src:
        src = src.replace("from aicad import fw\n", "from aicad import fw\nimport math\n", 1)
    return src


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
