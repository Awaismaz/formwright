"""Geometry review: stress-concentration hint regions (ENG-010), the failure-mode checklist tied to model features
(ENG-002) and recommended analyses / tests (ENG-006).

Everything here is a **heuristic** at the *Recommended check* level: it points an engineer at regions and failure
modes worth checking. It computes no stresses and never declares a region acceptable.
"""

from __future__ import annotations

import math
from typing import Any

HEURISTIC_NOTE = ("Heuristic from geometry only (no loads, no stresses computed). It points at likely stress "
                  "raisers; it does not rank them by actual stress.")


def _v(p: Any) -> list[float]:
    return [round(float(p.X), 3), round(float(p.Y), 3), round(float(p.Z), 3)]


def sharp_reentrant_edges(shape: Any, eps: float = 0.05) -> list[dict[str, Any]]:
    """Concave (re-entrant) edges with no fillet: two faces meeting at an internal corner.

    For an edge shared by faces F1, F2 with outward normals n1, n2 and in-face directions t1, t2 (perpendicular to
    the edge, pointing into each face), the edge is re-entrant when the point mid + ε(t1 + t2) lies outside the
    solid. Tangent (smooth) junctions are skipped."""
    from build123d import Vector

    solids = shape.solids()
    if not solids:
        return []
    out: list[dict[str, Any]] = []
    faces = list(shape.faces())
    edge_faces: dict[int, list[Any]] = {}
    edges: dict[int, Any] = {}
    for f in faces:
        for e in f.edges():
            h = hash(e)
            edges[h] = e
            lst = edge_faces.setdefault(h, [])
            if not any(x.is_same(f) for x in lst):
                lst.append(f)
    for h, fl in edge_faces.items():
        if len(fl) != 2:
            continue
        e = edges[h]
        if e.length < 1e-3:
            continue
        mid = e.position_at(0.5)
        tan = e.tangent_at(0.5)
        try:
            n1, n2 = fl[0].normal_at(mid), fl[1].normal_at(mid)
        except Exception:  # noqa: BLE001, S112 - degenerate face parametrisation: skip the edge
            continue
        if n1.dot(n2) > 0.985:      # tangent junction (fillet run-out)
            continue
        ts = []
        for f, n in ((fl[0], n1), (fl[1], n2)):
            t = tan.cross(n).normalized()
            if f.distance_to(mid + t * eps) > eps * 0.2:
                t = t * -1
            ts.append(t)
        probe = mid + (ts[0] + ts[1]).normalized() * eps
        inside = any(s.is_inside(probe) for s in solids)
        if not inside:
            ang = math.degrees(math.acos(max(-1.0, min(1.0, n1.dot(n2)))))
            out.append({"center": _v(mid), "length": round(e.length, 3), "type": e.geom_type.name.lower()
                        if hasattr(e.geom_type, "name") else str(e.geom_type), "angle_deg": round(180 - ang, 1),
                        "dir": _v(Vector(tan))})
    return out


def stress_hints(rec: dict[str, Any], sharp: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hint regions from the recognition record + sharp re-entrant edges. Each hint: id, kind, title, detail,
    severity (relative, heuristic), location, suggestion."""
    hints: list[dict[str, Any]] = []
    stock = rec.get("stock", {})
    size = rec.get("bbox") or stock.get("size") or [0, 0, 0]
    bmin = rec.get("bbox_min") or [0, 0, 0]
    bmax = [bmin[i] + size[i] for i in range(3)]

    # 1. section changes on turned parts (shoulders)
    if stock.get("kind") == "turned":
        D = stock["d"]
        internal_fillets = [f for f in rec.get("fillets", []) if f.get("convex") is False]
        for b in rec.get("bosses", []):
            d = b["d"]
            if d >= D:
                continue
            r = min((f["r"] for f in internal_fillets), default=0.0)
            if r == 0:
                sev, txt = "high", "no shoulder fillet was found (sharp corner)"
            elif r / d < 0.05:
                sev, txt = "high", f"the smallest internal fillet is R{r} (r/d = {r / d:.3f})"
            elif r / d < 0.1:
                sev, txt = "medium", f"the smallest internal fillet is R{r} (r/d = {r / d:.3f})"
            else:
                continue
            hints.append({"id": f"shoulder-{d}-{D}", "kind": "shoulder", "severity": sev,
                          "title": f"Shoulder Ø{D:g} → Ø{d:g} (D/d = {D / d:.2f})",
                          "detail": f"Section change at a shoulder; {txt}. Kt rises steeply as r/d falls below about "
                                    "0.1 (stepped round bar charts, e.g. Shigley Fig. A-15-9 and A-15-8).",
                          "location": b.get("top") or b.get("center"),
                          "suggestion": "Add or enlarge the shoulder fillet, or use a relief groove; check fatigue "
                                        "at this section with the shaft calculator using Kt from the chart.",
                          "calc": "shaft_fatigue", "prefill": {"d": d}})
    # 2. holes close to an edge (grouped by diameter and edge distance)
    edge_groups: dict[tuple[float, float], dict[str, Any]] = {}
    for h in rec.get("holes", []):
        d = h["d"]
        c = h["center"]
        ax = h.get("axis") or [0, 0, 1]
        k = max(range(3), key=lambda j: abs(ax[j]))
        if stock.get("kind") == "turned":
            ka = "XYZ".index(stock.get("axis", "Z")) if stock.get("axis") in ("X", "Y", "Z") else 2
            if k != ka:
                continue
            others = [j for j in range(3) if j != ka]
            r = math.hypot(c[others[0]] - (bmin[others[0]] + size[others[0]] / 2),
                           c[others[1]] - (bmin[others[1]] + size[others[1]] / 2))
            if r < 1e-6:
                continue            # the central bore
            e = stock["d"] / 2 - r
        else:
            others = [j for j in range(3) if j != k]
            e = min(min(c[j] - bmin[j], bmax[j] - c[j]) for j in others)
        if e <= 0:
            continue
        ratio = e / d
        if ratio >= 2.0:
            continue
        key = (d, round(e, 1))
        g = edge_groups.setdefault(key, {"d": d, "e": e, "ratio": ratio, "locations": []})
        g["locations"].append(c)
    for (d, _), g in sorted(edge_groups.items()):
        n, e, ratio = len(g["locations"]), g["e"], g["ratio"]
        hints.append({"id": f"hole-edge-{d:g}-{e:.1f}", "kind": "hole_edge", "severity": "high" if ratio < 1.5 else "medium",
                      "title": f"{n} × Ø{d:g} {'hole' if n == 1 else 'holes'} near an edge (edge distance {e:.1f} mm "
                               f"= {ratio:.2f} × d)",
                      "detail": "A hole close to a free edge concentrates stress in the ligament and can tear out "
                                "under bolt or pin load. Common practice keeps the edge distance at 1.5 to 2 × d or more "
                                "(heuristic threshold used here: 2 × d).",
                      "location": g["locations"][0], "locations": g["locations"], "count": n,
                      "suggestion": "Check bearing and tear-out of the ligament (pin/bolt calculators), or move the "
                                    "hole inward.", "calc": "pin_shear", "prefill": {"d": d}})
    # 3. internal fillets and sharp re-entrant edges
    for f in rec.get("fillets", []):
        if f.get("convex") is False and f["r"] <= 1.0:
            hints.append({"id": f"fillet-{f['r']}", "kind": "small_fillet", "severity": "medium",
                          "title": f"{f['count']} × small internal fillet R{f['r']:g}",
                          "detail": "Small internal radii at section changes raise local stress (Kt) and are a "
                                    "common fatigue crack origin.",
                          "location": None, "suggestion": "Use the largest radius the design allows at loaded "
                                                          "corners."})
    groups: dict[str, list[dict[str, Any]]] = {}
    for s in sharp:
        groups.setdefault("line" if s["type"] == "line" else "curve", []).append(s)
    for kind, lst in groups.items():
        total = sum(s["length"] for s in lst)
        worst = max(lst, key=lambda s: s["length"])
        hints.append({"id": f"sharp-{kind}", "kind": "sharp_corner", "severity": "high" if kind == "curve" else "medium",
                      "title": f"{len(lst)} sharp internal {'edge' if len(lst) == 1 else 'edges'} "
                               f"({'curved' if kind == 'curve' else 'straight'}, {total:.0f} mm total)",
                      "detail": "Re-entrant corners with no fillet are theoretical stress singularities: the real "
                                "peak depends on the tool radius. Loaded internal corners need a defined radius.",
                      "location": worst["center"], "edges": lst[:20],
                      "suggestion": "Specify a fillet at loaded internal corners (or confirm the corner is "
                                    "unloaded)."})
    return hints


# ----------------------------------------------------------------------------- failure-mode checklist (ENG-002/006)
def checklist(model: dict[str, Any], hints: list[dict[str, Any]], load_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rec = model.get("recognition") or {}
    stock = rec.get("stock", {})
    mech = model.get("mechanical") or {}
    mat_group = (model.get("material") or {}).get("group", "")
    size = rec.get("bbox") or (model.get("bbox") or [0, 0, 0])
    holes = rec.get("holes", [])
    patterns = rec.get("patterns", [])
    turned = stock.get("kind") == "turned"
    polymer = mat_group == "Plastics"
    fatigue_lc = any(lc.get("kind") == "fatigue" or (lc.get("cycles") or 0) > 1000 for lc in load_cases)
    thermal_lc = any(lc.get("kind") == "thermal" or lc.get("temperature_c") not in (None, "") for lc in load_cases)
    slender = bool(size) and min(size) > 0 and max(size) / min(size) >= 10
    items: list[dict[str, Any]] = []

    def add(iid: str, mode: str, title: str, why: str, calcs: list[str], analyses: list[dict[str, str]],
            features: list[str] | None = None) -> None:
        items.append({"id": iid, "mode": mode, "title": title, "why": why, "calculators": calcs,
                      "analyses": analyses, "features": features or [], "level": "recommended_check"})

    add("static", "Static strength", "Yield / fracture under the maximum load case",
        "Every load-bearing part needs a strength check at its critical section for the worst load case." +
        ("" if load_cases else " No load case is recorded yet: add one."),
        ["beam", "shaft_fatigue" if turned else "section_properties"],
        [{"what": "Hand calculation at the critical section", "why": "Fast bound on stress; shows the governing "
          "dimension."},
         {"what": "Linear static FEA of the part with the recorded load case",
          "why": "Local stresses at holes, fillets and section changes are not covered by beam theory."}],
        [model.get("part") or "Part"])
    sc = [h for h in hints if h["severity"] in ("high", "medium")]
    if sc:
        add("stress_conc", "Stress concentration", f"Stress raisers at {len(sc)} region(s)",
            "Geometry review found: " + "; ".join(h["title"] for h in sc[:4]) + (" …" if len(sc) > 4 else "") + ".",
            ["shaft_fatigue" if turned else "beam"],
            [{"what": "Apply Kt from a chart (Peterson's / Shigley App. A-15) in the hand calc",
              "why": "Nominal stress under-predicts the peak at the raiser."},
             {"what": "FEA with a mesh-convergence study at the raiser",
              "why": "Peak stress at a fillet is mesh sensitive; sharp corners never converge."}],
            [h["title"] for h in sc])
    add("fatigue", "Fatigue", "Fatigue under fluctuating or rotating load",
        ("A load case is marked as cyclic. " if fatigue_lc else "") +
        ("Rotating shafts see fully reversed bending every revolution. " if turned else "") +
        "Fatigue governs most machine failures; endurance depends on surface finish, size and Kf.",
        ["shaft_fatigue"] + (["bolted_joint"] if patterns else []),
        [{"what": "Goodman screening with Marin factors", "why": "Infinite-life check against the endurance limit."},
         {"what": "Strain-gauge or fatigue test of a prototype for safety-critical parts",
          "why": "Material and surface scatter are large; tests anchor the estimate."}])
    if patterns or holes:
        add("joint", "Bolted / pinned joints", f"Fastener joints at {len(patterns) or len(holes)} hole group(s)",
            "Recognised holes: " + "; ".join(
                f"{p['count']} × Ø{p['d']}" for p in patterns[:4]) + "." if patterns else "Recognised holes.",
            ["bolted_joint", "pin_shear", "thread_engagement"],
            [{"what": "Preload, separation and bearing checks per bolt", "why": "Joint separation and slip are the "
              "usual failure modes of bolted joints."},
             {"what": "Torque-tension test on the actual fasteners and finish",
              "why": "The nut factor scatters ±25 % or more."}],
            [f"{p['count']} × Ø{p['d']} {p['kind']}" for p in patterns])
    if slender:
        add("buckling", "Buckling / stability", "Slender geometry (length/width ≥ 10)",
            f"Bounding box {' × '.join(f'{x:g}' for x in size)} mm: slender members under compression can buckle "
            "below their yield load.", ["beam"],
            [{"what": "Euler / Johnson column check for compressive members", "why": "Stability can govern before "
              "strength."},
             {"what": "Linear buckling (eigenvalue) FEA", "why": "Covers plates and non-uniform sections."}])
    add("vibration", "Vibration / resonance",
        "Natural frequency vs excitation" + (" (critical speed of the shaft)" if turned else ""),
        "Resonance amplifies stress and deflection. " + ("Shafts need their first critical speed well above the "
                                                          "operating speed." if turned else
                                                          "Cantilevered or slender features have low natural "
                                                          "frequencies."), ["beam"],
        [{"what": "Modal analysis (FEA) or Rayleigh estimate from the static deflection",
          "why": "Compares the first natural frequency to the excitation spectrum."}])
    if thermal_lc or polymer:
        add("thermal", "Thermal / creep",
            "Temperature effects" + (" and creep of the polymer" if polymer else ""),
            ("A load case includes temperature. " if thermal_lc else "") +
            ("Polymers lose stiffness and creep under sustained load, even at room temperature." if polymer else ""),
            [], [{"what": "Use properties at temperature; creep data for sustained loads",
                  "why": "Room-temperature datasheet values are not conservative."}])
    if turned or any(h.get("through") for h in holes):
        add("fit", "Fits and clearances", "Fits, clearances and tolerance stack-ups",
            "Bores, shafts and hole patterns must assemble and keep their function across the tolerance range.",
            ["tolerance_stack", "interference_fit"],
            [{"what": "1D worst-case / RSS stack-up of the functional gaps", "why": "Shows which tolerance drives "
              "the gap."},
             {"what": "First-article inspection of the critical fits", "why": "Confirms the made part, not the model."}])
    if not mech:
        add("material", "Material data", "Material strength values are not on record",
            "The project material has no cited strength values in the library. Enter values from the supplier "
            "certificate in each calculator.", [],
            [{"what": "Obtain the mill/supplier certificate", "why": "Calculators need Sy, Sut and E."}])
    return items


def recommended_analyses(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for it in items:
        for a in it["analyses"]:
            e = seen.setdefault(a["what"], {"what": a["what"], "why": a["why"], "for": []})
            e["for"].append(it["mode"])
    return list(seen.values())
