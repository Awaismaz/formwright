"""Project link: read the latest verified build of a project (status.json, PARAMS, part.step), turn it into model
data the calculators can use (mass, centre of gravity, inertia, material, recognised holes and sections), and
suggest pre-filled calculator inputs with the provenance of every value.

Reads only. The user's model is never modified; module output goes to ``<workspace>/engineering/``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from aicad import materials
from aicad.engineering import review
from aicad.engineering import standards as std

GEOMETRY_VERSION = "geo-1.0.2"   # bump when recognition/hint logic changes (invalidates the cache)
G_ACCEL = 9.80665               # standard gravity, m/s² (ISO 80000-3)


def _read_json(p: Path) -> dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def eng_dir(ws: Path) -> Path:
    d = ws / "engineering"
    d.mkdir(parents=True, exist_ok=True)
    return d


def material_for(ws: Path, status: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Material chosen in the Studio settings, else guessed from the model's MATERIAL text."""
    st = _read_json(ws / ".fw" / "project.json")
    code = st.get("material")
    how = "Project material (Studio settings)"
    if not code or code == "custom":
        code = materials.guess(status.get("material"))
        how = f"Guessed from the model's material note '{status.get('material')}'"
    m = materials.get(code)
    return (dict(m) if m else None), how


def geometry(ws: Path, status: dict[str, Any]) -> dict[str, Any]:
    """Recognition + sharp-edge scan of out/part.step, cached by the STEP hash."""
    step = ws / "out" / "part.step"
    if not step.is_file():
        return {}
    from aicad.recognize import VERSION as RECOGNIZE_VERSION

    # recognize.VERSION in the key too: a recogniser change re-reads the part (PD-276 half bores)
    key = f"{status.get('step_sha256') or step.stat().st_mtime_ns}:{GEOMETRY_VERSION}:r{RECOGNIZE_VERSION}"
    cache = eng_dir(ws) / "geometry.json"
    c = _read_json(cache)
    if c.get("key") == key:
        return c["data"]
    from build123d import import_step

    from aicad.recognize import recognize

    shape = import_step(str(step))
    rec = recognize(shape)
    rec.pop("features", None)
    sharp = review.sharp_reentrant_edges(shape)
    data = {"recognition": rec, "sharp_edges": sharp}
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps({"key": key, "data": data}), encoding="utf-8")
    tmp.replace(cache)
    return data


def model_info(ws: Path) -> dict[str, Any]:
    status = _read_json(ws / "out" / "status.json")
    if not status or not status.get("fingerprint"):
        return {"available": False, "reason": "This project has no successful build yet. Build the part in the "
                                              "Design Studio first."}
    mat, mat_how = material_for(ws, status)
    mech = materials.mechanical(mat["code"]) if mat else None
    m = status.get("mass") or {}
    vol = m.get("volume_mm3") or status["fingerprint"].get("volume")
    rho = float(mat["density_g_cm3"]) if mat else None
    mass_kg = vol * rho * 1e-6 if (vol and rho) else None
    inertia = None
    if rho and m.get("inertia_com_mm5"):
        inertia = [[x * rho * 1e-6 for x in row] for row in m["inertia_com_mm5"]]
    geo = {}
    geo_error = None
    try:
        geo = geometry(ws, status)
    except Exception as e:  # noqa: BLE001 - geometry review is best effort; calculators still work
        geo_error = f"Geometry review unavailable ({type(e).__name__})"
    rec = geo.get("recognition") or {}
    info = {
        "available": True, "ok": bool(status.get("ok")), "part": status.get("part"),
        "build_id": status.get("build_id"), "step_sha256": status.get("step_sha256"),
        "bbox": status["fingerprint"].get("bbox"), "params": status.get("params") or {},
        "param_meta": status.get("param_meta") or {},
        "features": [f.get("name") for f in status.get("features") or []],
        "material": mat, "material_source": mat_how, "mechanical": mech,
        "mass": {"volume_mm3": vol, "mass_kg": mass_kg, "com_mm": m.get("com_mm"), "inertia_kg_mm2": inertia,
                 "weight_N": mass_kg * G_ACCEL if mass_kg else None,
                 "density_source": materials.SOURCE_NOTE if mat else "No material set: mass unavailable"},
        "recognition": rec, "sharp_edges": geo.get("sharp_edges", []), "geometry_error": geo_error,
    }
    info["hints"] = review.stress_hints(rec, geo.get("sharp_edges", [])) if rec else []
    info["suggestions"] = suggestions(info)
    return info


def _q(value: float, unit: str = "mm") -> dict[str, Any]:
    return {"value": round(float(value), 4), "unit": unit}


def keyway(rec: dict[str, Any], sharp: list[dict[str, Any]]) -> dict[str, float] | None:
    """A keyseat on a turned part, from its sharp internal edges running along the axis: two parallel edges at the
    keyseat floor corners. Returns the section diameter, width, depth and length, or None."""
    stock = rec.get("stock") or {}
    if stock.get("kind") != "turned" or stock.get("axis") not in ("X", "Y", "Z"):
        return None
    ka = "XYZ".index(stock["axis"])
    bmin, size = rec.get("bbox_min") or [0, 0, 0], rec.get("bbox") or [0, 0, 0]
    ctr = [bmin[i] + size[i] / 2 for i in range(3)]
    o = [j for j in range(3) if j != ka]
    axial = [s for s in sharp if s.get("type") == "line" and abs(abs(s["dir"][ka]) - 1) < 1e-6]
    if len(axial) < 2:
        return None
    a, b = sorted(axial, key=lambda s: -s["length"])[:2]
    if abs(a["length"] - b["length"]) > 1e-3 or abs(a["center"][ka] - b["center"][ka]) > 1e-3:
        return None
    pa = [a["center"][j] - ctr[j] for j in o]
    pb = [b["center"][j] - ctr[j] for j in o]
    w = math.dist(pa, pb)
    r_floor = math.hypot((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
    z = a["center"][ka]
    d = float(stock["d"])
    for bo in rec.get("bosses", []):     # a smaller section covering the keyseat's axial position
        lo, hi = sorted([(bo.get("bottom") or [0, 0, 0])[ka], (bo.get("top") or [0, 0, 0])[ka]])
        if lo - 1e-6 <= z <= hi + 1e-6:
            d = float(bo["d"])
    depth = d / 2 - r_floor
    if w <= 0 or depth <= 0 or depth >= d / 2:
        return None
    return {"d": d, "w": round(w, 3), "depth": round(depth, 3), "length": round(a["length"], 3)}


def suggestions(info: dict[str, Any]) -> list[dict[str, Any]]:
    """Pre-filled calculator inputs from the model. Every value carries a provenance line."""
    out: list[dict[str, Any]] = []
    rec = info.get("recognition") or {}
    mech = info.get("mechanical") or {}
    stock = rec.get("stock", {})
    size = rec.get("bbox") or info.get("bbox") or []
    E = mech.get("E_GPa")
    Sy, Sut = mech.get("Sy_MPa"), mech.get("Sut_MPa")
    mname = (info.get("material") or {}).get("name", "")
    msrc = f"{mname}: {mech.get('source')} ({mech.get('basis')}, verify)" if mech else ""
    holes = rec.get("holes", [])

    def hole_depth(d: float) -> float | None:
        ds = [h["depth"] for h in holes if abs(h["d"] - d) < 1e-6]
        return ds[0] if ds else None

    # bolted joints from clearance-hole patterns (ISO 273)
    groups = rec.get("patterns", []) or []
    singles = [{"kind": "single", "d": h["d"], "count": 1} for i, h in enumerate(holes)
               if not any(i in p.get("holes", []) for p in groups)]
    for p in [*groups, *singles][:6]:
        bolt = std.bolt_from_clearance(p["d"])
        t = hole_depth(p["d"])
        label = f"{p['count']} × Ø{p['d']:g} {'holes (' + p['kind'] + ')' if p['count'] > 1 else 'hole'}"
        if bolt and t:
            d_nom, pitch = std.COARSE_PITCH[bolt["size"]]
            grip = 2 * t
            L = 5 * math.ceil((grip + 0.9 * d_nom) / 5)
            layer = {"t": _q(t), "E": _q(E, "GPa") if E else _q(207, "GPa"), "material": mname or "Steel"}
            mate = {"t": _q(t), "E": _q(E, "GPa") if E else _q(207, "GPa"), "material": "Mating part (assumed)"}
            prov = {"size": f"{label}: Ø{p['d']:g} is the ISO 273 {bolt['series']} clearance for {bolt['size']}",
                    "layers": f"Layer 1 = this part, thickness {t:g} mm from the hole depth; layer 2 = mating part "
                              "ASSUMED identical; edit it",
                    "L": f"Grip {grip:g} mm + nut height ≈ 0.9·d, rounded up to 5 mm (edit to the bolt you use)"}
            if E:
                prov["E"] = f"Member modulus from {msrc}"
            out.append({"calc_id": "bolted_joint", "title": f"Check the {bolt['size']} bolts in {label}",
                        "inputs": {"size": bolt["size"], "layers": [layer, mate], "L": _q(L)}, "provenance": prov})
        if t:
            prov = {"d": f"{label}: hole Ø{p['d']:g} (pin assumed to fill the hole)",
                    "n_pins": f"{p['count']} holes in the group", "t": f"Bearing length {t:g} mm = hole depth"}
            inp: dict[str, Any] = {"d": _q(p["d"]), "n_pins": p["count"], "t": _q(t)}
            if Sy:
                inp["Sy_member"] = _q(Sy, "MPa")
                prov["Sy_member"] = f"Member yield from {msrc}"
            out.append({"calc_id": "pin_shear", "title": f"Pin / dowel shear in {label}", "inputs": inp,
                        "provenance": prov})
    # tapped holes: blind holes whose diameter is a tap drill (d − P) of a coarse thread
    for h in holes:
        if h.get("through"):
            continue
        for size_, (d_nom, pitch) in std.COARSE_PITCH.items():
            if abs(h["d"] - (d_nom - pitch)) <= 0.06:
                inp = {"size": size_, "Le": _q(h["depth"])}
                prov = {"size": f"Blind Ø{h['d']:g} hole = tap drill d − P for {size_}",
                        "Le": f"Engagement ≤ hole depth {h['depth']:g} mm (subtract the drill point and thread run-out)"}
                if Sut:
                    inp["Sut_int"] = _q(Sut, "MPa")
                    prov["Sut_int"] = f"Tapped material from {msrc}"
                out.append({"calc_id": "thread_engagement", "title": f"Thread engagement in the {size_} tapped hole",
                            "inputs": inp, "provenance": prov})
                break
    # turned parts: shaft section, press fit in a bore
    if stock.get("kind") == "turned":
        ds = sorted({stock["d"], *(b["d"] for b in rec.get("bosses", []))})
        d = ds[0]

        def shaft(title: str, d: float, dprov: str, kt: tuple[float, float] | None = None, ktprov: str = "") -> None:
            inp: dict[str, Any] = {"d": _q(d)}
            prov = {"d": dprov}
            if kt:
                inp.update(kf_mode="kt_q", Kt=kt[0], Kts=kt[1])
                prov.update(Kt=ktprov, Kts=ktprov)
            if Sut and Sy:
                inp.update(Sut=_q(Sut, "MPa"), Sy=_q(Sy, "MPa"))
                prov.update(Sut=f"From {msrc}", Sy=f"From {msrc}")
            out.append({"calc_id": "shaft_fatigue", "title": title, "inputs": inp, "provenance": prov,
                        "section": True})

        shaft(f"Shaft section Ø{d:g}", d, f"Smallest turned diameter Ø{d:g} (recognised)")
        for h in info.get("hints") or []:     # critical sections: shoulders (Kt from Shigley Table 7-1)
            if h.get("kind") == "shoulder" and (h.get("prefill") or {}).get("d"):
                ds_ = float(h["prefill"]["d"])
                kt = std.KT_FIRST_ITERATION["shoulder_sharp"]
                shaft(f"Shoulder at Ø{ds_:g} ({h['title'].split('(')[-1].rstrip(')')})", ds_,
                      f"Smaller diameter at the shoulder: {h['title']}", kt,
                      f"Sharp shoulder fillet, first-iteration estimate ({std.KT_FIRST_ITERATION_SOURCE})")
        kw = keyway(rec, info.get("sharp_edges") or [])
        if kw:
            kt = std.KT_FIRST_ITERATION["keyseat_end_mill"]
            shaft(f"Keyway section Ø{kw['d']:g} ({kw['w']:g} × {kw['depth']:g} keyseat)", kw["d"],
                  f"Ø{kw['d']:g} section carrying the {kw['w']:g} mm wide, {kw['depth']:g} mm deep, {kw['length']:g} mm "
                  "long keyseat (from its sharp internal edges); use the gross diameter per Shigley §7-4", kt,
                  f"End-mill keyseat, first-iteration estimate ({std.KT_FIRST_ITERATION_SOURCE})")
        bores = [h for h in holes if h.get("through") and h["d"] > 0.3 * stock["d"]]
        if bores:
            b = max(bores, key=lambda h: h["d"])
            inp = {"d": _q(b["d"]), "do": _q(stock["d"]), "L": _q(b["depth"])}
            prov = {"d": f"Central bore Ø{b['d']:g}", "do": f"Outer diameter Ø{stock['d']:g}",
                    "L": f"Bore length {b['depth']:g} mm"}
            if E:
                inp["Eo"] = _q(E, "GPa")
                prov["Eo"] = f"Hub modulus from {msrc}"
            if mech.get("nu"):
                inp["nuo"] = mech["nu"]
                prov["nuo"] = f"From {msrc}"
            if Sy:
                inp["Sy_hub"] = _q(Sy, "MPa")
                prov["Sy_hub"] = f"From {msrc}"
            out.append({"calc_id": "interference_fit", "title": f"Press fit of a shaft in the Ø{b['d']:g} bore",
                        "inputs": inp, "provenance": prov})
    # prismatic: beam / section from the bounding box
    if stock.get("kind") == "prismatic" and len(size) == 3:
        s = sorted(size)
        h, b, L = s[0], s[1], s[2]
        inp = {"support": "cantilever", "L": _q(L), "section": "rect", "b": _q(b), "h": _q(h)}
        prov = {"L": f"Longest bounding-box dimension {L:g} mm", "b": f"Bounding box {b:g} mm",
                "h": f"Thinnest bounding-box dimension {h:g} mm (approximation: uniform solid section, holes "
                     "and pockets ignored)"}
        if E:
            inp["E"] = _q(E, "GPa")
            prov["E"] = f"From {msrc}"
        if Sy:
            inp["Sy"] = _q(Sy, "MPa")
            prov["Sy"] = f"From {msrc}"
        out.append({"calc_id": "beam", "title": f"Part as a {L:g} mm cantilever, {b:g} × {h:g} section",
                    "inputs": inp, "provenance": prov})
        out.append({"calc_id": "section_properties", "title": f"Section {b:g} × {h:g} mm",
                    "inputs": {"section": "rect", "b": _q(b), "h": _q(h)},
                    "provenance": {"b": "Bounding box", "h": "Bounding box (thinnest)"}})
    return out
