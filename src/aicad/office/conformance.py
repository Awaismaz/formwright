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
  envelope  the part's bounding box inside its envelope (+0.1 mm)
"""

from __future__ import annotations

import math
from typing import Any

from aicad.office import icd

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
    thr_ok = bool(near.get("through", True))
    bits = [f"Ø{md:.3f} at {_fmt(m)}"]
    if not pos_ok:
        bits.append(f"{dist(near):.2f} mm off position (±{tol:g})")
    if not thr_ok:
        bits.append("blind, the ICD says through")
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


def measure(skel: dict[str, Any], doc_icd: dict[str, Any], item: str, info: dict[str, Any],
            refs: dict[str, Any]) -> dict[str, Any]:
    """Per-interface pass / fail with measured against specified. ``ok`` = every interface and the envelope pass."""
    it = skel["items"][item]
    by_if: dict[str, list[dict[str, Any]]] = {}
    for f in icd.item_features(skel, doc_icd["interfaces"], item):
        if f["type"] == "hole":
            row = _hole(f, info)
        elif f["type"] == "boss":
            row = _boss(f, info, refs)
        elif f["type"] == "face":
            row = _face(f, refs)
        else:
            row = _gear(f, info)
        for iid in [f["if"], *f.get("also", [])]:
            by_if.setdefault(iid, []).append(row)
    names = {f["id"]: f["name"] for f in doc_icd["interfaces"]}
    results = [{"interface": iid, "name": names.get(iid, iid), "ok": all(r["ok"] for r in rows), "rows": rows}
               for iid, rows in by_if.items()]
    env = envelope(it, info)
    return {"version": doc_icd["version"], "ok": env["ok"] and all(r["ok"] for r in results), "envelope": env,
            "interfaces": results}


def findings(res: dict[str, Any]) -> list[str]:
    """Gage's findings: one sentence per failed feature, measured against specified."""
    out = []
    if not res["envelope"]["ok"]:
        e = res["envelope"]
        out.append(f"The part leaves its envelope: {e['measured']}; the ICD gives {e['spec']}.")
    for r in res["interfaces"]:
        for row in r["rows"]:
            if not row["ok"]:
                out.append(f"{r['interface']} {r['name']}: {row['feature']} specified {row['spec']}, measured "
                           f"{row['measured']}.")
    seen: list[str] = []
    for f in out:  # a feature shared by two interfaces is reported once
        if f.split(": ", 1)[-1] not in [s.split(": ", 1)[-1] for s in seen]:
            seen.append(f)
    return seen[:12]
