"""ICD conformance measurement (CD-010): the built part's interface features, measured on its exact B-rep, against
the ICD numbers. Deterministic, pure Python: it reads the part snapshot Fitz uses anyway (``info.json`` = the
recognised holes / gear from ``aicad.recognize``, ``refs.json`` = exact planes and cylinders, see
``aicad.assembly.geometry.prepare``), in the part frame the ICD states (origin at the envelope centre).

Per feature:
  hole   a recognised hole along Z whose axis is within the position tolerance of the stated (X, Y); Ø within
         ±0.05 mm, or inside the ISO 286 zone for a fitted bore (a model at nominal size conforms: fits are a drawing
         callout); through when the ICD says through
  boss   an exact cylinder along Z (not a hole) on the stated axis; Ø inside the fit zone or at nominal
  face   an exact plane with the stated normal at the stated Z (± position tolerance)
  gear   a recognised spur gear: tooth count equal, module within 1 %, axis on the part axis
  seat   an exact cylinder along Z (a bearing seat or the shaft clearance under it) on the stated axis, Ø in the
         housing fit's zone (or nominal); the seat depth is the shoulder face next to it
  keyway two exact side planes at ±b/2 from the keyway's centre line (width ±0.05) and the groove bottom (shaft) or
         the keyway top (hub) at the stated depth (±0.1), on the stated side of the axis
  groove a DIN 471 ring groove: circular edges of radius d2 / 2 on the axis at both groove ends (Ø, ends ±0.1)
  envelope  the part's bounding box inside its envelope (+0.1 mm)
Features along X or Y (``ax``, Phase 6: a gearbox housing's wall seats and cap screw holes) are measured with the
same code after the part data is turned into the feature's canonical frame (``frames.CANON``). A ``blind`` hole (a
tapped hole) must not go through.

Frame (Gage, frame tolerant): a part modelled in another frame than the ICD's (rotated by quarter turns, moved) is
matched first: ``best_frame`` tries the 24 axis-aligned rotations with translations that pair the part's features
with the ICD's, keeps the one under which the most features conform (the ICD frame wins ties) and reports it; the
measurement then runs in that frame and Fitz places the part through it.
"""

from __future__ import annotations

import math
from typing import Any

from aicad.office import frames, icd

DIM_TOL = 0.05     # mm for clearance holes and plain diameters
NOMINAL = 0.001    # a diameter this close to nominal conforms to any fit (CAD models are nominal)
ENV_TOL = 0.1


def _xy(c: Any) -> tuple[float, float]:
    return float(c[0]), float(c[1])


def _fmt(c: tuple[float, float]) -> str:
    return f"({c[0]:.2f}, {c[1]:.2f})"


def _along_z(v: Any) -> bool:
    return abs(abs(float(v[2])) - 1.0) < 1e-3


def _dia_ok(measured: float, spec: float, fit: str | None) -> tuple[bool, str]:
    if fit:
        z = icd.zone(spec, fit)
        if abs(measured - spec) <= NOMINAL:
            return True, f"Ø{spec:g} {fit}" + (f" ({z[0]:.3f}…{z[1]:.3f})" if z else "")
        if z is None:
            return abs(measured - spec) <= DIM_TOL, f"Ø{spec:g} {fit}"
        return z[0] - 1e-6 <= measured <= z[1] + 1e-6, f"Ø{spec:g} {fit} ({z[0]:.3f}…{z[1]:.3f})"
    return abs(measured - spec) <= DIM_TOL, f"Ø{spec:g} ±{DIM_TOL:g}"


def _hole(f: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    c = _xy(f["c"])
    tol = float(f.get("tol") or icd.POS_TOL)
    cands = [h for h in info.get("holes") or [] if _along_z(h["axis"])]
    spec_txt = f"Ø{f['d']:g}{' ' + f['fit'] if f.get('fit') else ''} at {_fmt(c)}"
    if not cands:
        return {"feature": f["label"], "spec": spec_txt, "measured": "no hole along Z", "ok": False}
    # nearest hole of a similar size first, else nearest
    def dist(h: dict[str, Any]) -> float:
        return math.hypot(float(h["center"][0]) - c[0], float(h["center"][1]) - c[1])
    near = min(cands, key=lambda h: (dist(h) > tol, abs(float(h["d"]) - f["d"]) > 1.0, dist(h)))
    m = (float(near["center"][0]), float(near["center"][1]))
    md = float(near["d"])
    pos_ok = dist(near) <= tol
    d_ok, d_txt = _dia_ok(md, float(f["d"]), f.get("fit"))
    blind = bool(f.get("blind"))
    thr_ok = (not near.get("through", True)) if blind else bool(near.get("through", True))
    bits = [f"Ø{md:.3f} at {_fmt(m)}"]
    if not pos_ok:
        bits.append(f"{dist(near):.2f} mm off position (±{tol:g})")
    if not thr_ok:
        bits.append("through, the ICD says blind (tapped)" if blind else "blind, the ICD says through")
    return {"feature": f["label"], "spec": f"{d_txt} at {_fmt(c)}", "measured": ", ".join(bits),
            "ok": pos_ok and d_ok and thr_ok, "delta_mm": round(dist(near), 4), "d_mm": round(md, 4)}


def _boss(f: dict[str, Any], info: dict[str, Any], refs: dict[str, Any]) -> dict[str, Any]:
    c = _xy(f["c"])
    tol = float(f.get("tol") or icd.POS_TOL)
    hole_faces = {fid for h in info.get("holes") or [] for fid in h.get("faces") or []}
    best = None
    for fid, r in (refs.get("faces") or {}).items():
        if r.get("kind") != "axis" or r.get("r") is None or int(fid) in hole_faces or not _along_z(r["v"]):
            continue
        off = math.hypot(float(r["p"][0]) - c[0], float(r["p"][1]) - c[1])
        if off > tol:
            continue
        dd = 2 * float(r["r"])
        if best is None or abs(dd - f["d"]) < abs(best[0] - f["d"]):
            best = (dd, off)
    spec_txt = f"Ø{f['d']:g} {f.get('fit') or ''} on the axis at {_fmt(c)}".replace("  ", " ")
    if best is None:
        return {"feature": f["label"], "spec": spec_txt, "measured": "no cylinder on that axis", "ok": False}
    d_ok, d_txt = _dia_ok(best[0], float(f["d"]), f.get("fit"))
    return {"feature": f["label"], "spec": f"{d_txt} on the axis at {_fmt(c)}", "measured":
            f"Ø{best[0]:.3f}, axis {best[1]:.3f} mm from position", "ok": d_ok, "d_mm": round(best[0], 4)}


def _face(f: dict[str, Any], refs: dict[str, Any]) -> dict[str, Any]:
    tol = float(f.get("tol") or icd.POS_TOL)
    n = float(f["n"])
    zs = [float(r["p"][2]) for r in (refs.get("faces") or {}).values()
          if r.get("kind") == "plane" and float(r["v"][2]) * n > 1 - 1e-6]
    spec_txt = f"plane Z {f['z']:g} (normal {'+' if n > 0 else '−'}Z, ±{tol:g})"
    if not zs:
        return {"feature": f["label"], "spec": spec_txt, "measured": f"no face with normal {'+' if n > 0 else '−'}Z",
                "ok": False}
    z = min(zs, key=lambda x: abs(x - f["z"]))
    return {"feature": f["label"], "spec": spec_txt, "measured": f"Z {z:.3f}", "ok": abs(z - f["z"]) <= tol,
            "delta_mm": round(abs(z - f["z"]), 4)}


def _gear(f: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    comp = info.get("component") or {}
    spec_txt = f"spur gear m{f['module']:g} × {f['teeth']} teeth on the part axis"
    if comp.get("kind") != "spur_gear":
        return {"feature": f["label"], "spec": spec_txt, "measured": "no gear teeth recognised", "ok": False}
    p = comp.get("params") or {}
    teeth, mod = int(p.get("teeth") or 0), float(p.get("module") or p.get("module_est") or 0)
    o = comp.get("origin") or [0, 0, 0]
    off = math.hypot(float(o[0]) - f["c"][0], float(o[1]) - f["c"][1])
    ok = teeth == int(f["teeth"]) and abs(mod - f["module"]) <= 0.01 * f["module"] and off <= float(f.get("tol") or icd.POS_TOL) \
        and _along_z(comp.get("axis") or [0, 0, 1])
    return {"feature": f["label"], "spec": spec_txt, "measured": f"m{mod:g} × {teeth} teeth, axis {off:.3f} mm off",
            "ok": ok}


def _in_range(refs: dict[str, Any], c: tuple[float, float], r: float, z0: float, z1: float, tol: float) -> bool:
    """A circular edge of radius ``r`` on the axis at ``c`` between Z z0 and z1: the bore ends inside that range
    (a seat's opening or its shoulder), so two bores of one size at different depths are told apart."""
    for e in (refs.get("edges") or {}).values():
        if e.get("kind") != "axis" or e.get("r") is None or not _along_z(e["v"]):
            continue
        if abs(float(e["r"]) - r) > 1e-3 or math.hypot(float(e["p"][0]) - c[0], float(e["p"][1]) - c[1]) > tol:
            continue
        if z0 - 0.5 <= float(e["p"][2]) <= z1 + 0.5:
            return True
    return False


def _seat(f: dict[str, Any], refs: dict[str, Any]) -> dict[str, Any]:
    c = _xy(f["c"])
    tol = float(f.get("tol") or icd.POS_TOL)
    best = None
    z0, z1 = float(f.get("z0", -1e9)), float(f.get("z1", 1e9))
    for r in (refs.get("faces") or {}).values():
        if r.get("kind") != "axis" or r.get("r") is None or not _along_z(r["v"]):
            continue
        off = math.hypot(float(r["p"][0]) - c[0], float(r["p"][1]) - c[1])
        if off > tol:
            continue
        if refs.get("edges") and not _in_range(refs, c, float(r["r"]), z0, z1, tol):
            continue
        dd = 2 * float(r["r"])
        if best is None or abs(dd - f["d"]) < abs(best[0] - f["d"]):
            best = (dd, off)
    spec_txt = f"Ø{f['d']:g} {f.get('fit') or ''} on the axis at {_fmt(c)}".replace("  ", " ")
    if best is None or abs(best[0] - f["d"]) > 1.0:
        return {"feature": f["label"], "spec": spec_txt, "measured": "no bore of that size on that axis" if best is None
                else f"nearest bore Ø{best[0]:.3f}", "ok": False}
    d_ok, d_txt = _dia_ok(best[0], float(f["d"]), f.get("fit"))
    return {"feature": f["label"], "spec": f"{d_txt} on the axis at {_fmt(c)}",
            "measured": f"Ø{best[0]:.3f}, axis {best[1]:.3f} mm from position", "ok": d_ok, "d_mm": round(best[0], 4)}


def _keyway(f: dict[str, Any], refs: dict[str, Any]) -> dict[str, Any]:
    """Width between the two side planes and depth to the groove bottom (shaft) / keyway top (hub)."""
    c = _xy(f["c"])
    dx, dy = float(f["dir"][0]), float(f["dir"][1])
    n = math.hypot(dx, dy) or 1.0
    dx, dy = dx / n, dy / n
    px, py = -dy, dx
    r = float(f["d"]) / 2
    b, depth = float(f["b"]), float(f["depth"])
    hub = f["on"] == "hub"
    sides: list[float] = []
    bottoms: list[float] = []
    for q in (refs.get("faces") or {}).values():
        if q.get("kind") != "plane" or abs(float(q["v"][2])) > 1e-3:
            continue
        vx, vy = float(q["v"][0]), float(q["v"][1])
        ox, oy = float(q["p"][0]) - c[0], float(q["p"][1]) - c[1]
        along = ox * dx + oy * dy
        across = ox * px + oy * py
        if abs(abs(vx * px + vy * py) - 1) < 1e-3 and along > 0 and abs(abs(across) - b / 2) < 1.0:
            sides.append(across)
        elif abs(vx * dx + vy * dy - (-1 if hub else 1)) < 1e-3 and abs(across) < b / 2 + 1e-6:
            bottoms.append(along)
    spec_txt = (f"{b:g} wide (±{icd.KEY_TOL:g}), {depth:g} deep (±{icd.DEPTH_TOL:g}) from the "
                f"{'bore' if hub else 'shaft surface'}")
    plus = [x for x in sides if x > 0]
    minus = [x for x in sides if x < 0]
    if not plus or not minus:
        return {"feature": f["label"], "spec": spec_txt, "measured": "no keyway on that side of the axis", "ok": False}
    width = min(plus, key=lambda x: abs(x - b / 2)) - max(minus, key=lambda x: -abs(x + b / 2))
    want = r + depth if hub else r - depth
    if not bottoms:
        return {"feature": f["label"], "spec": spec_txt, "measured": f"{width:.3f} wide, no keyway "
                f"{'top' if hub else 'bottom'} face", "ok": False}
    t = min(bottoms, key=lambda x: abs(x - want))
    got = t - r if hub else r - t
    ok = abs(width - b) <= icd.KEY_TOL + 1e-9 and abs(got - depth) <= icd.DEPTH_TOL + 1e-9
    return {"feature": f["label"], "spec": spec_txt, "measured": f"{width:.3f} wide, {got:.3f} deep", "ok": ok,
            "width_mm": round(width, 4), "depth_mm": round(got, 4)}


def _groove(f: dict[str, Any], refs: dict[str, Any]) -> dict[str, Any]:
    """A DIN 471 ring groove: circular edges of radius d2 / 2 on the axis at the groove's two ends."""
    c = _xy(f["c"])
    tol = float(f.get("tol") or icd.POS_TOL)
    z0, z1, r = float(f["z0"]), float(f["z1"]), float(f["d"]) / 2
    spec_txt = f"Ø{f['d']:g}, {z1 - z0:g} wide, from {(f.get('ax') or 'z').upper()} {z0:g} to {z1:g}"
    found: list[tuple[float, float]] = []
    for e in (refs.get("edges") or {}).values():
        if e.get("kind") != "axis" or e.get("r") is None or not _along_z(e["v"]):
            continue
        if abs(float(e["r"]) - r) > icd.DEPTH_TOL / 2 or \
                math.hypot(float(e["p"][0]) - c[0], float(e["p"][1]) - c[1]) > tol:
            continue
        if z0 - 0.5 <= float(e["p"][2]) <= z1 + 0.5:
            found.append((float(e["p"][2]), 2 * float(e["r"])))
    if len(found) < 2:
        return {"feature": f["label"], "spec": spec_txt, "measured": "no groove of that size there", "ok": False}
    lo, hi = min(found)[0], max(found)[0]
    dd = min(found, key=lambda x: abs(x[1] - float(f["d"])))[1]
    ok = abs(lo - z0) <= icd.DEPTH_TOL and abs(hi - z1) <= icd.DEPTH_TOL and abs(dd - float(f["d"])) <= icd.DEPTH_TOL
    return {"feature": f["label"], "spec": spec_txt, "measured": f"Ø{dd:.3f} from {lo:.3f} to {hi:.3f}", "ok": ok}


def envelope(item: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    L, W, H = item["size"]
    bb = info.get("bbox") or [0, 0, 0, 0, 0, 0]
    lim = [L / 2 + ENV_TOL, W / 2 + ENV_TOL, H / 2 + ENV_TOL]
    out = [k for k in range(3) if bb[k] < -lim[k] or bb[k + 3] > lim[k]]
    size = [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]]
    return {"feature": "envelope", "spec": f"inside {L:g} × {W:g} × {H:g} mm, centred on the part origin",
            "measured": f"{size[0]:.2f} × {size[1]:.2f} × {size[2]:.2f} mm, X {bb[0]:.2f}…{bb[3]:.2f}, "
                        f"Y {bb[1]:.2f}…{bb[4]:.2f}, Z {bb[2]:.2f}…{bb[5]:.2f}"
                        + (f" (outside in {', '.join('XYZ'[k] for k in out)})" if out else ""),
            "ok": not out}


_CANON_CACHE: dict[tuple[int, int, str], tuple[Any, Any, dict[str, Any], dict[str, Any]]] = {}


def in_canon(lax: str | None, info: dict[str, Any], refs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The part data turned into the canonical frame of part axis ``lax`` (cached per data and axis)."""
    if not lax or lax == "z":
        return info, refs
    key = (id(info), id(refs), lax)
    hit = _CANON_CACHE.get(key)
    if hit is not None and hit[0] is info and hit[1] is refs:
        return hit[2], hit[3]
    Rt = frames.transpose(frames.CANON[lax])
    out = (frames.info_in(info, Rt, [0.0, 0.0, 0.0]), frames.refs_in(refs, Rt, [0.0, 0.0, 0.0]))
    if len(_CANON_CACHE) > 256:
        _CANON_CACHE.clear()
    _CANON_CACHE[key] = (info, refs, *out)
    return out


def _row(f: dict[str, Any], info: dict[str, Any], refs: dict[str, Any]) -> dict[str, Any]:
    info, refs = in_canon(f.get("ax"), info, refs)
    if f["type"] == "hole" and f.get("span"):  # a bore over its own span (one step of a stepped bore): measured
        return _seat(f, refs)                      # like a seat, Ø with its fit and an end inside the span
    if f["type"] == "hole":
        return _hole(f, info)
    if f["type"] == "boss":
        return _boss(f, info, refs)
    if f["type"] == "face":
        return _face(f, refs)
    if f["type"] == "seat":
        return _seat(f, refs)
    if f["type"] == "keyway":
        return _keyway(f, refs)
    if f["type"] == "groove":
        return _groove(f, refs)
    return _gear(f, info)


def _measure(skel: dict[str, Any], doc_icd: dict[str, Any], item: str, info: dict[str, Any],
             refs: dict[str, Any]) -> dict[str, Any]:
    it = skel["items"][item]
    by_if: dict[str, list[dict[str, Any]]] = {}
    for f in icd.item_features(skel, doc_icd["interfaces"], item):
        row = _row(f, info, refs)
        for iid in [f["if"], *f.get("also", [])]:
            by_if.setdefault(iid, []).append(row)
    names = {f["id"]: f["name"] for f in doc_icd["interfaces"]}
    results = [{"interface": iid, "name": names.get(iid, iid), "ok": all(r["ok"] for r in rows), "rows": rows}
               for iid, rows in by_if.items()]
    env = envelope(it, info)
    return {"version": doc_icd["version"], "ok": env["ok"] and all(r["ok"] for r in results), "envelope": env,
            "interfaces": results}


def _score(res: dict[str, Any]) -> tuple[int, float]:
    rows = [r for x in res["interfaces"] for r in x["rows"]]
    good = sum(1 for r in rows if r["ok"]) + (1 if res["envelope"]["ok"] else 0)
    resid = sum(float(r.get("delta_mm") or 0) for r in rows)
    return good, -resid


def _candidates(feats: list[dict[str, Any]], info: dict[str, Any], refs: dict[str, Any]
                ) -> tuple[list[tuple[float, float]], list[float]]:
    """Translations (X, Y) and Z that pair the part's features (already rotated) with the ICD's."""
    axes = [(float(h["center"][0]), float(h["center"][1]), float(h["d"])) for h in info.get("holes") or []
            if _along_z(h["axis"])]
    axes += [(float(r["p"][0]), float(r["p"][1]), 2 * float(r["r"])) for r in (refs.get("faces") or {}).values()
             if r.get("kind") == "axis" and r.get("r") is not None and _along_z(r["v"])]
    planes = [(float(r["p"][2]), 1 if float(r["v"][2]) > 0 else -1) for r in (refs.get("faces") or {}).values()
              if r.get("kind") == "plane" and abs(abs(float(r["v"][2])) - 1) < 1e-3]
    xy: list[tuple[float, float]] = []
    zs: list[float] = []
    bb = info.get("bbox")
    if bb:
        xy.append((-(bb[0] + bb[3]) / 2, -(bb[1] + bb[4]) / 2))
        zs.append(-(bb[2] + bb[5]) / 2)
    for f in feats:
        if f["type"] in ("hole", "boss", "seat"):
            for x, y, d in axes:
                if abs(d - float(f["d"])) <= 0.5:
                    xy.append((float(f["c"][0]) - x, float(f["c"][1]) - y))
        elif f["type"] == "face":
            zs += [float(f["z"]) - z for z, n in planes if n == f["n"]]
    def dedupe(vals: list[Any], key: Any) -> list[Any]:
        out, seen = [], set()
        for v in vals:
            k = key(v)
            if k not in seen:
                seen.add(k)
                out.append(v)
        return out
    return (dedupe(xy, lambda v: (round(v[0], 3), round(v[1], 3)))[:24],
            dedupe(zs, lambda v: round(v, 3))[:12])


def _rows_ok(feats: list[dict[str, Any]], info: dict[str, Any], refs: dict[str, Any]) -> tuple[int, float]:
    rows = [_row(f, info, refs) for f in feats]
    return sum(1 for r in rows if r["ok"]), -sum(float(r.get("delta_mm") or 0) for r in rows)


def best_frame(skel: dict[str, Any], doc_icd: dict[str, Any], item: str, info: dict[str, Any],
               refs: dict[str, Any]) -> dict[str, Any]:
    """The frame that maps the part as modelled onto its ICD part frame: the identity when the part conforms (or
    nothing fits better), else the quarter-turn rotation + translation under which the most features conform.
    X/Y is fitted on the axial features (holes, bores, seats, keyways, gear), then Z on the faces and envelope."""
    base = _measure(skel, doc_icd, item, info, refs)
    if base["ok"]:
        return frames.frame(frames.IDENT, [0.0, 0.0, 0.0])
    feats = icd.item_features(skel, doc_icd["interfaces"], item)
    fxy = [f for f in feats if f["type"] != "face"]
    fz = [f for f in feats if f["type"] == "face"]
    it = skel["items"][item]
    best = (_score(base), frames.IDENT, [0.0, 0.0, 0.0])
    for R in frames.quarter_turns():
        ri, rr = frames.info_in(info, R, [0.0, 0.0, 0.0]), frames.refs_in(refs, R, [0.0, 0.0, 0.0])
        xy, zs = _candidates(feats, ri, rr)
        scored = []
        for tx, ty in xy:
            t = [tx, ty, 0.0]
            scored.append((_rows_ok(fxy, frames.info_in(ri, frames.IDENT, t), frames.refs_in(rr, frames.IDENT, t)),
                           (tx, ty)))
        scored.sort(key=lambda x: x[0], reverse=True)
        for (sxy, (tx, ty)) in scored[:2]:
            for tz in zs:
                t = [tx, ty, tz]
                ti, tr = frames.info_in(ri, frames.IDENT, t), frames.refs_in(rr, frames.IDENT, t)
                sz = _rows_ok(fz, ti, tr)
                env = 1 if envelope(it, ti)["ok"] else 0
                sc = (sxy[0] + sz[0] + env, sxy[1] + sz[1])
                if sc > best[0]:
                    best = (sc, R, t)
    return frames.frame(best[1], best[2])


def measure(skel: dict[str, Any], doc_icd: dict[str, Any], item: str, info: dict[str, Any],
            refs: dict[str, Any], frame_tolerant: bool = True) -> dict[str, Any]:
    """Per-interface pass / fail with measured against specified. ``ok`` = every interface and the envelope pass.
    Frame tolerant (default): the part is matched to its ICD frame first (``best_frame``) and ``frame`` reports
    the transform used (the identity for a part modelled in the ICD frame)."""
    fr = best_frame(skel, doc_icd, item, info, refs) if frame_tolerant else frames.frame(frames.IDENT, [0, 0, 0])
    if not fr["identity"]:
        info = frames.info_in(info, fr["R"], fr["t"])
        refs = frames.refs_in(refs, fr["R"], fr["t"])
    return {**_measure(skel, doc_icd, item, info, refs), "frame": fr}


def finding_items(res: dict[str, Any]) -> list[dict[str, Any]]:
    """Gage's findings with what each one measures: ``{"rule", "key", "text"}``. ``rule`` is ``conformance`` (an
    interface feature, ``key`` = "IF-n:feature", or the part frame) or ``envelope``; Archie's rule overrides name a
    feature by its key (``office.supervisor``)."""
    out: list[dict[str, Any]] = []
    fr = res.get("frame") or {}
    if fr and not fr.get("identity") and not res.get("ok"):
        out.append({"rule": "conformance", "key": "frame",
                    "text": f"Measured in the part's own frame ({fr['label']}): model it in the ICD part frame, or fix "
                            "the features below."})
    if not res["envelope"]["ok"]:
        e = res["envelope"]
        out.append({"rule": "envelope", "key": "envelope",
                    "text": f"The part leaves its envelope: {e['measured']}; the ICD gives {e['spec']}."})
    for r in res["interfaces"]:
        for row in r["rows"]:
            if not row["ok"]:
                out.append({"rule": "conformance", "key": f"{r['interface']}:{row['feature']}",
                            "text": f"{r['interface']} {r['name']}: {row['feature']} specified {row['spec']}, measured "
                                    f"{row['measured']}."})
    seen: list[dict[str, Any]] = []
    for f in out:  # a feature shared by two interfaces is reported once
        if f["text"].split(": ", 1)[-1] not in [s["text"].split(": ", 1)[-1] for s in seen]:
            seen.append(f)
    return seen[:12]


def findings(res: dict[str, Any]) -> list[str]:
    """Gage's findings: one sentence per failed feature, measured against specified."""
    return [f["text"] for f in finding_items(res)]
