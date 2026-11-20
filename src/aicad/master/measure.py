"""Deterministic measurement of a master model (WORKLIST 50): what each body is, where it sits, what it touches.

Input: the labelled solids of a master script (``aicad.master.kit.master``). Output (JSON-safe, rounded):

  bodies    name, base name and copy number, envelope (min, max, size, centre), volume, axis-aligned planar faces,
            full cylindrical faces (bores and pins) and concave half turns (half bores), one per stretch along the
            line; holes (Ø, axis, extent, through or blind, ``full`` false for a half bore), and the open pocket of a
            non-convex body (an L bracket's inside corner) when it is a clean box
  contacts  planar: two faces coplanar with opposite normals and overlapping (the joint plane, which side faces
            which way, the overlap), with the holes that cross it in both bodies paired by position (the bolts);
            coaxial: a bore of one body on a pin of the other (radial gap at most ``FIT_GAP``), or a bore split
            across a joint (``splits``: a half bore in each of two bodies, the line in their joint plane) on a pin
            of a third body (``split``, ``split_with`` the other half); tangent: two pitch circles touching on
            parallel axes (a gear mesh, external or internal)
  passes    a pin through a larger bore (a shaft through a bearing bore: the bearing is bought out, not modelled)
  findings  never silent: bodies that overlap (shared volume), touch nothing, touch only along an edge or at a
            point (unclassified), faces or holes off the three axes, a fastener-size hole on a joint with nothing
            across it

Run as ``python -m aicad.master.measure <model.py> <out.json>`` (the script runs behind the model-script tripwire,
exactly as a Studio build). Nothing here calls a model.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Any

TOL = 0.05          # mm: coplanar faces, coaxial lines, touching boxes
FIT_GAP = 0.5       # mm: largest radial gap between a bore and a pin that still counts as a fit
MESH_TOL = 0.1      # mm: two pitch circles touch when their centre distance is within this of the sum (or difference)
VERSION = 2         # 2: half bores, bores split across a joint, tangent pitch circles, pins only through empty lines
MIN_AREA = 0.5      # mm²: a planar contact smaller than this is an edge or point touch
OVERLAP_MM3 = 0.5   # mm³: shared volume above this is an overlap (a clash in the master)
POCKET_CLEAN = 0.995  # the empty part of a body's envelope is a pocket when it fills this much of its own box
POCKET_MIN = 0.05     # ... and is at least this share of the envelope
PLANE = {"z": (0, 1), "y": (0, 2), "x": (1, 2)}
AX = "xyz"


def _r(x: float, n: int = 3) -> float:
    v = round(float(x), n)
    return 0.0 if v == 0 else v


def _split(label: str) -> tuple[str, int]:
    name = str(label or "").strip()
    if "#" in name:
        head, _, tail = name.rpartition("#")
        if tail.strip().isdigit():
            return head.strip(), int(tail.strip()) - 1
    return name, 0


def axial_clusters(segs: list[tuple[float, float, float]], tol: float = TOL) -> list[tuple[float, float, float]]:
    """Faces of one cylinder line grouped by where they lie along it: (lo, hi, angle covered) per group of faces that
    overlap axially. Two half bores at the two ends of a split housing are two groups of 180 degrees, not one full
    turn (golden A4: summed over the line they made 360, a "hole" centred on the split line); the two halves of one
    full bore overlap and make 360."""
    out: list[list[float]] = []
    for lo, hi, span in sorted(segs):
        if out and lo < out[-1][1] - tol:
            out[-1][1] = max(out[-1][1], hi)
            out[-1][2] += span
        else:
            out.append([lo, hi, span])
    return [(a, b, c) for a, b, c in out]


def bodies_of(result: Any) -> list[tuple[str, Any]]:
    """The labelled solids of a master compound, in order."""
    kids = list(getattr(result, "children", None) or [])
    if not kids:
        kids = list(result.solids()) if hasattr(result, "solids") else []
    out = []
    for k, c in enumerate(kids):
        sols = c.solids() if hasattr(c, "solids") else []
        if len(sols) != 1:
            raise ValueError(f"master body {getattr(c, 'label', k)!r} is {len(sols)} solids, not one")
        out.append((str(getattr(c, "label", "") or f"Body {k + 1}"), sols[0]))
    return out


# ----------------------------------------------------------------------------- one body
def _axis_of(v: Any) -> tuple[str, int] | None:
    k = max(range(3), key=lambda i: abs(v[i]))
    if abs(v[k]) < 0.9999:
        return None
    return AX[k], 1 if v[k] > 0 else -1


def _pocket(solid: Any, holes: list[dict[str, Any]], bb: Any) -> dict[str, Any] | None:
    """The empty part of the body's envelope when it is one clean box (an L bracket's inside corner, a clevis slot),
    else None. The box is spanned by the empty region's large flat faces (at least a tenth of its surface: the faces of the part around it), so a hole
    that opens into it (a tapped hole, a pin bore through the lugs) doesn't spoil it; it must then be empty to
    ``POCKET_CLEAN`` (bosses standing in an enclosure's cavity make it not a pocket)."""
    from build123d import Box, Pos

    vb = bb.size.X * bb.size.Y * bb.size.Z
    if vb <= 0 or solid.volume >= 0.97 * vb:
        return None

    def box(lo: list[float], hi: list[float]) -> Any:
        return Pos(*[(lo[k] + hi[k]) / 2 for k in range(3)]) * Box(*[hi[k] - lo[k] for k in range(3)])

    blo, bhi = [bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]
    try:
        sols = sorted((box(blo, bhi) - solid).solids(), key=lambda x: -x.volume)
        if not sols:
            return None
        e = sols[0]
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Plane

        flats = [f for f in e.faces() if BRepAdaptor_Surface(f.wrapped).GetType() == GeomAbs_Plane]
        big = [f for f in flats if f.area >= 0.1 * e.area] or flats
        if not big:
            return None
        lo = [min(getattr(f.bounding_box().min, c) for f in big) for c in "XYZ"]
        hi = [max(getattr(f.bounding_box().max, c) for f in big) for c in "XYZ"]
        eb = e.bounding_box()
        for k, c in enumerate("XYZ"):  # an open side has no face: the empty region's own extent there
            if hi[k] - lo[k] <= TOL:
                lo[k], hi[k] = getattr(eb.min, c), getattr(eb.max, c)
        vc = (hi[0] - lo[0]) * (hi[1] - lo[1]) * (hi[2] - lo[2])
        if vc < POCKET_MIN * vb:
            return None
        inside = e & box(lo, hi)
        if inside is None or inside.volume < POCKET_CLEAN * vc:
            return None
    except Exception:  # noqa: BLE001 - a failed boolean: no pocket (the envelope is kept whole)
        return None
    open_ = [f"{'-' if s < 0 else '+'}{AX[k]}" for k in range(3) for s in (-1, 1)
             if (s < 0 and abs(lo[k] - blo[k]) < TOL) or (s > 0 and abs(hi[k] - bhi[k]) < TOL)]
    return {"min": [_r(x) for x in lo], "max": [_r(x) for x in hi], "open": open_}


def body_info(label: str, solid: Any) -> dict[str, Any]:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane

    from aicad import recognize as rz

    bb = solid.bounding_box()
    base, copy = _split(label)
    planes: list[dict[str, Any]] = []
    cyls: dict[tuple[Any, ...], dict[str, Any]] = {}
    off_axis = 0
    for f in solid.faces():
        s = BRepAdaptor_Surface(f.wrapped)
        t = s.GetType()
        if t == GeomAbs_Plane:
            c = f.center()
            n = f.normal_at(c)
            a = _axis_of((n.X, n.Y, n.Z))
            if a is None:
                off_axis += 1
                continue
            k = AX.index(a[0])
            fb = f.bounding_box()
            i, j = PLANE[a[0]]
            lo = [fb.min.X, fb.min.Y, fb.min.Z]
            hi = [fb.max.X, fb.max.Y, fb.max.Z]
            planes.append({"axis": a[0], "sign": a[1], "t": _r([c.X, c.Y, c.Z][k]),
                           "rect": [_r(lo[i]), _r(hi[i]), _r(lo[j]), _r(hi[j])], "area": _r(f.area, 2)})
        elif t == GeomAbs_Cylinder:
            ci = rz._cyl_info(f)
            if ci is None:
                continue
            a = _axis_of(ci["axis"])
            if a is None:
                off_axis += 1
                continue
            key = rz._line_key(ci["origin"], ci["axis"]) + (_r(ci["r"], 3), bool(ci["concave"]))
            g = cyls.setdefault(key, {"axis": a[0], "r": ci["r"], "concave": bool(ci["concave"]), "segs": [],
                                      "line": None})
            k = AX.index(a[0])
            o = list(ci["origin"])
            base_t = o[k]
            i, j = PLANE[a[0]]
            g["line"] = [_r(o[i]), _r(o[j])]
            g["segs"].append((base_t + ci["lo"], base_t + ci["hi"], ci["span_deg"]))
    rec = rz.recognize(solid)
    # one entry per stretch of a cylinder along its line (faces that overlap axially): a full turn is a bore or a pin;
    # a concave half turn is a half bore, the half of a bore split across a joint (a split housing's bearing bore).
    # Holes are these stretches too: two tapped holes on one line at the two ends of a housing are two holes, each
    # with its own depth, and a half bore is a hole that is not ``full``.
    full: list[dict[str, Any]] = []
    halves: list[dict[str, Any]] = []
    holes: list[dict[str, Any]] = []
    for g in cyls.values():
        for lo, hi, span in axial_clusters(g["segs"]):
            row = {"axis": g["axis"], "d": _r(2 * g["r"]), "concave": g["concave"], "line": g["line"], "lo": _r(lo),
                   "hi": _r(hi)}
            if span >= 359.0:
                full.append(row)
            elif g["concave"] and span >= 179.0:
                halves.append({**row, "span": _r(span, 1)})
            else:
                continue
            if not g["concave"]:
                continue
            k = AX.index(g["axis"])
            i, j = PLANE[g["axis"]]
            dv = [0.0, 0.0, 0.0]
            dv[k] = 1.0
            top, bot = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
            top[i] = bot[i] = g["line"][0]
            top[j] = bot[j] = g["line"][1]
            top[k], bot[k] = hi, lo
            holes.append({"d": row["d"], "axis": g["axis"], "at": list(g["line"]), "lo": row["lo"], "hi": row["hi"],
                          "depth": _r(hi - lo), "through": bool(rz._open_both_ends(solid, top, bot, dv, g["r"])),
                          "center": [_r((top[n] + bot[n]) / 2) for n in range(3)], "full": span >= 359.0})
    holes.sort(key=lambda h: (h["d"], h["center"]))
    out = {"label": label, "name": base, "copy": copy,
           "min": [_r(bb.min.X), _r(bb.min.Y), _r(bb.min.Z)], "max": [_r(bb.max.X), _r(bb.max.Y), _r(bb.max.Z)],
           "size": [_r(bb.size.X), _r(bb.size.Y), _r(bb.size.Z)],
           "centre": [_r((bb.min.X + bb.max.X) / 2), _r((bb.min.Y + bb.max.Y) / 2), _r((bb.min.Z + bb.max.Z) / 2)],
           "volume": _r(solid.volume, 2), "planes": planes, "cylinders": full, "halves": halves,
           "holes": [{k: v for k, v in h.items() if k != "center"} for h in holes], "off_axis": off_axis,
           "stock": (rec.get("stock") or {}).get("kind")}
    pk = _pocket(solid, holes, bb)
    if pk:
        out["pocket"] = pk
    return out


# ----------------------------------------------------------------------------- pairs
def _box_gap(a: dict[str, Any], b: dict[str, Any]) -> float:
    d = [max(0.0, a["min"][k] - b["max"][k], b["min"][k] - a["max"][k]) for k in range(3)]
    return math.sqrt(sum(x * x for x in d))


def _penetration(a: dict[str, Any], b: dict[str, Any]) -> float:
    return min(min(a["max"][k], b["max"][k]) - max(a["min"][k], b["min"][k]) for k in range(3))


def _rect_overlap(r: list[float], s: list[float]) -> list[float] | None:
    u0, u1, v0, v1 = max(r[0], s[0]), min(r[1], s[1]), max(r[2], s[2]), min(r[3], s[3])
    if u1 - u0 <= TOL or v1 - v0 <= TOL:
        return None
    return [u0, u1, v0, v1]


def _inside(p: list[float], rect: list[float], m: float = TOL) -> bool:
    return rect[0] - m <= p[0] <= rect[1] + m and rect[2] - m <= p[1] <= rect[3] + m


def _fastener_size_hole(d: float) -> bool:
    from aicad.office.icd import CLEARANCE, TAP_DRILL

    return any(abs(d - v) <= 0.15 for v in (*CLEARANCE.values(), *TAP_DRILL.values()))


def _planar(A: dict[str, Any], B: dict[str, Any]) -> list[dict[str, Any]]:
    """Coplanar, opposed, overlapping faces of A and B, merged per plane; with the holes that cross each plane."""
    found: dict[tuple[str, float, int], dict[str, Any]] = {}
    for pa in A["planes"]:
        for pb in B["planes"]:
            if pa["axis"] != pb["axis"] or pa["sign"] != -pb["sign"] or abs(pa["t"] - pb["t"]) > TOL:
                continue
            ov = _rect_overlap(pa["rect"], pb["rect"])
            if ov is None:
                continue
            key = (pa["axis"], round(pa["t"], 2), pa["sign"])
            c = found.setdefault(key, {"axis": pa["axis"], "t": pa["t"], "sign_a": pa["sign"], "rect": ov, "area": 0.0})
            c["rect"] = [min(c["rect"][0], ov[0]), max(c["rect"][1], ov[1]), min(c["rect"][2], ov[2]),
                         max(c["rect"][3], ov[3])]
            c["area"] += (ov[1] - ov[0]) * (ov[3] - ov[2])
    out = []
    for c in found.values():
        if c["area"] < MIN_AREA:
            continue
        t = c["t"]

        def at_plane(body: dict[str, Any], ax: str = c["axis"], t0: float = t, rect: list[float] = c["rect"]
                     ) -> list[dict[str, Any]]:
            return [h for h in body["holes"] if h["axis"] == ax and (abs(h["lo"] - t0) <= TOL or abs(h["hi"] - t0) <= TOL)
                    and _inside(h["at"], rect)]

        ha, hb = at_plane(A), at_plane(B)
        bolts, ways, used = [], [], set()
        for x in ha:
            for n, y in enumerate(hb):
                if n not in used and math.dist(x["at"], y["at"]) <= TOL:
                    used.add(n)
                    # a fastener hole on both sides is a bolt; a larger coaxial pair (a pilot bore in a window, a
                    # shaft passage) is a way through the joint, recorded but not a bolt
                    row = {"at": x["at"], "a": x, "b": y}
                    if _fastener_size_hole(x["d"]) and _fastener_size_hole(y["d"]):
                        bolts.append(row)
                    elif x["through"] and y["through"]:  # (a blind recess on both sides, a shell's inside, is neither)
                        ways.append(row)
                    break
        paired_a = {id(b["a"]) for b in bolts + ways}
        lone = [("a", x) for x in ha if id(x) not in paired_a] + [("b", y) for n, y in enumerate(hb) if n not in used]
        out.append({"kind": "planar", "axis": c["axis"], "t": _r(t), "sign_a": c["sign_a"],
                    "rect": [_r(x) for x in c["rect"]], "area": _r(c["area"], 1), "bolts": bolts,
                    "ways": [{"at": w["at"], "d_a": w["a"]["d"], "d_b": w["b"]["d"],
                              **({"split_a": True} if not w["a"].get("full", True) else {}),
                              **({"split_b": True} if not w["b"].get("full", True) else {})} for w in ways],
                    "lone": [{"side": s, "d": h["d"], "at": h["at"]} for s, h in lone]})
    return out


def _coaxial(A: dict[str, Any], B: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Bores of one body on pins of the other: fits (radial gap <= FIT_GAP) and clearances (a shaft through a
    larger hole, recorded, not an interface)."""
    fits, passes = [], []
    for bore_side, X, Y in (("a", A, B), ("b", B, A)):
        for h in X["cylinders"]:
            if not h["concave"]:
                continue
            for p in Y["cylinders"]:
                if p["concave"] or p["axis"] != h["axis"] or math.dist(p["line"], h["line"]) > TOL:
                    continue
                lo, hi = max(h["lo"], p["lo"]), min(h["hi"], p["hi"])
                if hi - lo <= TOL:
                    continue
                gap = (h["d"] - p["d"]) / 2
                row = {"kind": "coaxial", "axis": h["axis"], "line": h["line"], "bore": bore_side, "d_bore": h["d"],
                       "d_pin": p["d"], "span": [_r(lo), _r(hi)], "gap": _r(gap)}
                if -TOL <= gap <= FIT_GAP:
                    fits.append(row)
                elif gap > FIT_GAP:
                    passes.append(row)
    return fits, passes


def _splits(A: dict[str, Any], B: dict[str, Any], planar: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bores split across a joint (a split housing's bearing bore, its gear cavity): a half bore in A and one in B on
    the same line, of the same Ø, the line lying in a joint plane between them. Each half alone is a hole with its
    centre on the edge of its body; together they are one bore."""
    out: list[dict[str, Any]] = []
    for c in planar:
        k = AX.index(c["axis"])
        for ha in A.get("halves") or []:
            if ha["axis"] == c["axis"]:
                continue
            i, j = PLANE[ha["axis"]]
            if k not in (i, j) or abs(ha["line"][0 if k == i else 1] - c["t"]) > TOL:
                continue
            for hb in B.get("halves") or []:
                if hb["axis"] != ha["axis"] or abs(hb["d"] - ha["d"]) > TOL or math.dist(hb["line"], ha["line"]) > TOL:
                    continue
                lo, hi = max(ha["lo"], hb["lo"]), min(ha["hi"], hb["hi"])
                if hi - lo <= TOL:
                    continue
                row = {"axis": ha["axis"], "line": ha["line"], "d": ha["d"], "lo": _r(lo), "hi": _r(hi),
                       "joint": {"axis": c["axis"], "t": c["t"]}}
                if row not in out:
                    out.append(row)
    return out


def _split_coaxial(sp: dict[str, Any], Y: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A split bore (both halves together) on a pin of body Y: fits and passes, as ``_coaxial`` for one bore."""
    fits, passes = [], []
    for p in Y["cylinders"]:
        if p["concave"] or p["axis"] != sp["axis"] or math.dist(p["line"], sp["line"]) > TOL:
            continue
        lo, hi = max(sp["lo"], p["lo"]), min(sp["hi"], p["hi"])
        if hi - lo <= TOL:
            continue
        gap = (sp["d"] - p["d"]) / 2
        row = {"kind": "coaxial", "axis": sp["axis"], "line": sp["line"], "bore": "a", "d_bore": sp["d"],
               "d_pin": p["d"], "span": [_r(lo), _r(hi)], "gap": _r(gap), "split": True}
        if -TOL <= gap <= FIT_GAP:
            fits.append(row)
        elif gap > FIT_GAP:
            passes.append(row)
    return fits, passes


def _tangent(A: dict[str, Any], B: dict[str, Any]) -> list[dict[str, Any]]:
    """Round faces of A and B that touch along a line on parallel axes: two pitch circles side by side (an external
    mesh, centre distance (d1 + d2) / 2) or one inside the other (an internal mesh, (D - d) / 2). A master models a gear
    as its pitch circle, so this is how a mesh shows in it."""
    out: list[dict[str, Any]] = []
    for first, X, Y in (("a", A, B), ("b", B, A)):
        for p in X["cylinders"]:
            if p["concave"]:
                continue
            for q in Y["cylinders"]:
                if q["axis"] != p["axis"] or (not q["concave"] and first == "b"):
                    continue  # (an external pair is found once, from A)
                dist = math.dist(p["line"], q["line"])
                want = (q["d"] - p["d"]) / 2 if q["concave"] else (q["d"] + p["d"]) / 2
                if dist <= TOL or abs(dist - want) > MESH_TOL:
                    continue
                lo, hi = max(p["lo"], q["lo"]), min(p["hi"], q["hi"])
                if hi - lo <= TOL:
                    continue
                out.append({"kind": "tangent", "axis": p["axis"], "inner": first, "internal": bool(q["concave"]),
                            "line_a": p["line"] if first == "a" else q["line"],
                            "line_b": q["line"] if first == "a" else p["line"],
                            "d_a": p["d"] if first == "a" else q["d"], "d_b": q["d"] if first == "a" else p["d"],
                            "span": [_r(lo), _r(hi)], "centre_distance": _r(dist)})
    return out


def _solid_at(solid: Any, ax: str, at: list[float], t: float) -> bool:
    from build123d import Vector

    p = [0.0, 0.0, 0.0]
    i, j = PLANE[ax]
    p[i], p[j], p[AX.index(ax)] = float(at[0]), float(at[1]), float(t)
    try:
        return bool(solid.is_inside(Vector(*p)))
    except Exception:  # noqa: BLE001 - a classifier failure: say it (conservative)
        return True


def _overlap(sa: Any, sb: Any) -> float:
    try:
        x = sa & sb
        return float(x.volume) if x is not None else 0.0
    except Exception:  # noqa: BLE001 - a failed boolean: report the box penetration instead (caller)
        return -1.0


def _touch(sa: Any, sb: Any) -> float:
    from aicad.assembly.geometry import min_distance

    try:
        return float(min_distance(sa, sb)[0])
    except Exception:  # noqa: BLE001
        return math.inf


def measure(bodies: list[tuple[str, Any]]) -> dict[str, Any]:
    t0 = time.perf_counter()
    infos = [body_info(label, s) for label, s in bodies]
    contacts: list[dict[str, Any]] = []
    passes: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    touched = [False] * len(infos)

    def find(code: str, severity: str, names: list[str], text: str, **kw: Any) -> None:
        findings.append({"code": code, "severity": severity, "bodies": names, "text": text, **kw})

    planar: dict[tuple[int, int], list[dict[str, Any]]] = {}
    splits: list[dict[str, Any]] = []
    for i in range(len(infos)):
        for j in range(i + 1, len(infos)):
            if _box_gap(infos[i], infos[j]) > TOL:
                continue
            planar[(i, j)] = _planar(infos[i], infos[j])
            splits += [{"a": i, "b": j, **sp} for sp in _splits(infos[i], infos[j], planar[(i, j)])]
    # a split bore on a pin of a third body: one row per half (each half carries its half of the bore)
    split_rows: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for sp in splits:
        for y, Y in enumerate(infos):
            if y in (sp["a"], sp["b"]):
                continue
            fits, through = _split_coaxial(sp, Y)
            for half, other in ((sp["a"], sp["b"]), (sp["b"], sp["a"])):
                key = (min(half, y), max(half, y))
                split_rows.setdefault(key, []).extend({**c, "a": half, "b": y, "split_with": other} for c in fits)
                passes += [{**c, "a": half, "b": y, "split_with": other} for c in through]

    for i in range(len(infos)):
        A = infos[i]
        if A["off_axis"]:
            find("off_axis", "warning", [A["label"]], f"{A['label']}: {A['off_axis']} face(s) are not square to the "
                 "axes; the master is read as axis-aligned, so those faces are not measured as joints.")
        for j in range(i + 1, len(infos)):
            B = infos[j]
            if (i, j) not in planar:
                continue
            row: list[dict[str, Any]] = []
            for c in planar[(i, j)]:
                row.append({"a": i, "b": j, **c})
            fits, through = _coaxial(A, B)
            row += [{"a": i, "b": j, **c} for c in fits]
            row += split_rows.get((i, j), [])
            row += [{"a": i, "b": j, **c} for c in _tangent(A, B)]
            passes += [{"a": i, "b": j, **c} for c in through]
            if _penetration(A, B) > TOL:
                v = _overlap(bodies[i][1], bodies[j][1])
                if v > OVERLAP_MM3 or v < 0:
                    find("overlap", "error", [A["label"], B["label"]],
                         f"{A['label']} and {B['label']} overlap" + (f" by {v:.0f} mm³" if v > 0 else "")
                         + " in the master model: one of them is in the wrong place or too large.", volume=_r(v, 1))
            if not row:
                d = _touch(bodies[i][1], bodies[j][1])
                if d <= TOL:
                    find("unclassified", "warning", [A["label"], B["label"]],
                         f"{A['label']} and {B['label']} touch only along an edge or at a point: not a joint the "
                         "office can read (a face against a face, a bore on a pin, or two pitch circles).")
                    touched[i] = touched[j] = True
            if row:
                touched[i] = touched[j] = True
            contacts += row
            for c in row:
                for lone in c.get("lone") or []:
                    if not _fastener_size_hole(lone["d"]):
                        continue
                    # material across the joint at the hole? (a window or a counterbore there is not a problem)
                    across = bodies[j][1] if lone["side"] == "a" else bodies[i][1]
                    step = 0.1 * (c["sign_a"] if lone["side"] == "a" else -c["sign_a"])
                    if not _solid_at(across, c["axis"], lone["at"], c["t"] + step):
                        continue
                    who = A if lone["side"] == "a" else B
                    other = B if lone["side"] == "a" else A
                    find("lone_hole", "warning", [who["label"], other["label"]],
                         f"{who['label']}: the Ø{lone['d']:g} hole at {lone['at']} opens onto the joint with "
                         f"{other['label']} but nothing on {other['label']} matches it.")
    # pivot axes: the same hole (axis, position, Ø) through two or more bodies that is not a bolt of a planar joint
    # (a hinge pin through the lugs and the arm; the pin itself is bought out, so the master only has its bores)
    bolted = {(c["axis"], round(b["at"][0], 1), round(b["at"][1], 1)) for c in contacts if c["kind"] == "planar"
              for b in c.get("bolts") or []}
    # A half bore is not a pin hole (it is half of a split bore), and a line a modelled shaft or pin runs in is a shaft
    # line, not a bought-out pin's (golden A4: the sun's and the carrier's bores on the two shafts read as a pivot).
    lines: dict[tuple[Any, ...], list[tuple[int, dict[str, Any]]]] = {}
    for k, A in enumerate(infos):
        for h in A["holes"]:
            if not h.get("full", True):
                continue
            lines.setdefault((h["axis"], round(h["at"][0], 1), round(h["at"][1], 1), round(h["d"], 1)), []).append((k, h))
    pins = []
    for key, hs in lines.items():
        ks = sorted({k for k, _h in hs})
        if len(ks) < 2 or key[:3] in bolted:
            continue
        lo_l, hi_l = min(h["lo"] for _k, h in hs), max(h["hi"] for _k, h in hs)
        if any(not p["concave"] and p["axis"] == key[0] and math.dist(p["line"], key[1:3]) <= 0.1 + TOL
               and p["d"] <= key[3] + TOL and min(p["hi"], hi_l) - max(p["lo"], lo_l) > TOL
               for X in infos for p in X["cylinders"]):
            continue
        pins.append({"kind": "pin", "axis": key[0], "at": [key[1], key[2]], "d": key[3], "bodies": ks,
                     "span": [_r(min(h["lo"] for _k, h in hs)), _r(max(h["hi"] for _k, h in hs))]})
        for k in ks:
            touched[k] = True
    for k, A in enumerate(infos):
        if not touched[k] and len(infos) > 1:
            find("touches_nothing", "error", [A["label"]], f"{A['label']} touches nothing in the master model: it "
                 "would float beside the assembly. Place it against what carries it.")
    return {"version": VERSION, "bodies": infos, "contacts": contacts, "pins": pins, "passes": passes,
            "splits": splits, "findings": findings, "seconds": round(time.perf_counter() - t0, 3)}


def measure_script(script: Path) -> dict[str, Any]:
    """Run a master script (tripwired, as a Studio build) and measure its bodies."""
    from aicad.agent import runner

    t0 = time.perf_counter()
    ns = runner._exec(script, store=False)
    t_build = time.perf_counter() - t0
    out = measure(bodies_of(ns["result"]))
    out["build_seconds"] = round(t_build, 3)
    return out


def main(argv: list[str] | None = None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) != 2:
        print("usage: python -m aicad.master.measure <model.py> <out.json>")
        return 2
    try:
        out: dict[str, Any] = measure_script(Path(a[0]))
    except Exception as e:  # noqa: BLE001 - the caller reads the error from the file
        out = {"error": f"{type(e).__name__}: {e}"[:600]}
    Path(a[1]).write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0 if "error" not in out else 1


if __name__ == "__main__":
    raise SystemExit(main())
