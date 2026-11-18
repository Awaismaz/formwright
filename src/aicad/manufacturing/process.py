"""Process recommendation (MFG-014): a transparent, rule-of-thumb ranking of candidate processes.

Scores start at 50 and move with quantity, material, size, geometry signals, tolerance and the relative cost
estimate. Every adjustment is listed as a reason, so the ranking can be argued with. Confidence is never "high":
this is screening advice for a conversation with a supplier.

Two caps keep the ranking honest (MAKE-11): a process whose own rules were not run here (polymer printing) is never
better than "Possible: not analysed", and a process with an open critical finding is never better than "Possible".
"""

from __future__ import annotations

from typing import Any

from aicad.manufacturing import ADVICE_LEVELS
from aicad.manufacturing import features as F
from aicad.manufacturing.geometry import PartGeom
from aicad.manufacturing.shop import ShopProfile

NAMES = {"cnc_milling": "CNC milling", "cnc_turning": "CNC turning", "sheet_metal": "Sheet metal",
         "fdm": "3D printing (FDM)", "sla": "3D printing (SLA)", "sls": "3D printing (SLS)",
         "casting": "Casting", "injection_moulding": "Injection moulding"}

# Quantity rules of thumb: list of (max quantity, score delta, note). Typical industry ranges, not data.
QTY: dict[str, list[tuple[float, int, str]]] = {
    "cnc_milling": [(1000, 20, "suits one-offs to about 1,000 parts"), (5000, 5, "workable at this volume"),
                    (1e12, -15, "high volumes usually move to near-net processes")],
    "cnc_turning": [(10000, 20, "suits prototypes to high volume (bar-fed)"), (1e12, 10, "automatic lathes")],
    "sheet_metal": [(10000, 20, "laser and press brake suit low to mid volume"), (1e12, 10, "stamping at volume")],
    "fdm": [(10, 20, "ideal for prototypes and a handful of parts"), (50, 5, "workable for small batches"),
            (200, -10, "slow per part at this volume"), (1e12, -30, "not economic at volume")],
    "sla": [(20, 15, "prototypes and small batches"), (100, 0, "small batches"), (1e12, -25, "not economic at volume")],
    "sls": [(100, 15, "prototypes and small batches"), (1000, 0, "short production runs"),
            (1e12, -20, "costly at high volume")],
    "casting": [(50, -30, "tooling is hard to amortise below ~50 parts"), (500, -5, "tooling partly amortised"),
                (5000, 15, "good once tooling is amortised"), (1e12, 20, "suits volume production")],
    "injection_moulding": [(500, -35, "mould cost dominates below ~500 parts"), (2000, 0, "break-even region"),
                           (10000, 20, "economic at this volume"), (1e12, 30, "best at high volume")],
}
TOL: dict[str, dict[str, int]] = {
    "fine": {"cnc_milling": 0, "cnc_turning": 0, "sheet_metal": -15, "fdm": -20, "sla": -5, "sls": -15,
             "casting": -15, "injection_moulding": -5},
    "precision": {"cnc_milling": -5, "cnc_turning": -5, "sheet_metal": -40, "fdm": -40, "sla": -30, "sls": -40,
                  "casting": -30, "injection_moulding": -25},
}
# Processes whose DFM rules run in this module (rules.PROCESS_LABEL keys). Printing is checked in 3D Print Prep.
RULES_FOR = {"cnc_milling": "cnc_milling", "cnc_turning": "cnc_turning", "sheet_metal": "sheet_metal",
             "casting": "moulding_casting", "injection_moulding": "moulding_casting"}
CAP = 60  # best score while a process is not analysed or has an open critical finding ("Possible")
MAT_PROC = {"cnc_milling": "mill", "cnc_turning": "turn", "sheet_metal": "sheet", "fdm": "fdm", "sla": "sla",
            "sls": "sls", "casting": "cast", "injection_moulding": "mould"}


def _fits(dims: list[float], box: list[float] | None) -> bool:
    return bool(box) and all(a <= b + 1e-6 for a, b in zip(sorted(dims, reverse=True), sorted(box or [], reverse=True)))


def rank(g: PartGeom, shop: ShopProfile, mat: dict[str, Any], quantity: int, tolerance: str, acc: F.Access,
         turn: F.Turning, sheet: F.Sheet, findings: list[dict[str, Any]], unit_costs: dict[str, float],
         draft_faces: int, mould_undercuts: int, thick_for_moulding: bool) -> dict[str, Any]:
    dims = g.size.tolist()
    procs = set(mat["processes"])
    crit = {p: sum(1 for f in findings if f["process"] == p and f["severity"] == "critical")
            for p in ("cnc_milling", "cnc_turning", "sheet_metal", "moulding_casting")}
    crit_secondary = {p: sum(1 for f in findings if p in (f.get("also") or []) and f["severity"] == "critical")
                      for p in crit}
    cheapest = min(unit_costs.values()) if unit_costs else None
    out = []
    for p, pname in NAMES.items():
        score, pros, cons, feasible, conf = 50, [], [], True, "low"
        if MAT_PROC[p] not in procs:
            if p in ("fdm", "sla", "sls") and mat["metal"]:
                cons.append(f"{mat['name']} is a metal: polymer printing gives a form/fit prototype only "
                            "(metal AM is not modelled)")
                score -= 40
            else:
                feasible = False
                cons.append(f"{mat['name']} is not normally processed this way")
        for qmax, delta, note in QTY[p]:
            if quantity <= qmax:
                score += delta
                (pros if delta > 0 else cons if delta < 0 else pros).append(f"Quantity {quantity:,}: {note}")
                break
        d = TOL.get(tolerance, {}).get(p, 0)
        if d:
            score += d
            cons.append(f"{tolerance.capitalize()} tolerances usually need secondary machining or tight process "
                        "control here")
        if p == "cnc_milling":
            if acc.undercut:
                score -= 15
                cons.append(f"{len(acc.undercut)} undercut face(s) need special cutters or 5-axis")
            if len(acc.setups) > 2:
                score -= 5 * (len(acc.setups) - 2)
                cons.append(f"{len(acc.setups)} setups estimated")
            else:
                pros.append(f"{len(acc.setups)} setup(s) estimated")
            if crit["cnc_milling"]:
                score -= min(30, 10 * crit["cnc_milling"])
                cons.append(f"{crit['cnc_milling']} critical milling finding(s) to resolve")
            mills = shop.mills()
            if mills and not any(_fits(dims, m.travel_mm) for m in mills):
                score -= 40
                cons.append("Larger than every milling machine in your shop profile")
            if turn.turnable:
                cons.append("Rotational part: turning is usually quicker for the revolved faces")
                score -= 10
        elif p == "cnc_turning":
            if not turn.turnable:
                feasible = False
                cons.append("Not a rotational part (no dominant revolution axis)")
            else:
                score += 15
                conf = "medium"
                pros.append(f"{100 * turn.revolved_frac:.0f} % of the surface is revolved about one axis")
                if turn.secondary:
                    score -= 5
                    cons.append(f"{len(turn.secondary)} face(s) need a secondary milling or drilling operation")
                lathes = shop.lathes()
                if lathes and not any((m.max_diameter_mm or 0) >= turn.max_d and (m.max_length_mm or 0) >= turn.length
                                      for m in lathes):
                    score -= 40
                    cons.append("Exceeds every lathe in your shop profile")
                if crit_secondary["cnc_turning"]:
                    score -= 5
                    cons.append(f"{crit_secondary['cnc_turning']} critical finding(s) in the secondary milling "
                                "operation to resolve")
        elif p == "sheet_metal":
            if not sheet.sheet_like:
                feasible = False
                cons.append("Not a constant-thickness shell" + (f" (dominant thickness {sheet.thickness:g} mm)"
                                                                 if sheet.thickness else ""))
            else:
                score += 15
                conf = "medium"
                pros.append(f"Constant {sheet.thickness:g} mm thickness over {100 * sheet.frac:.0f} % of the surface")
                cons.append("Flat pattern and bends come from the sheet-metal model; bend reliefs and hole-to-bend "
                            "distances are not analysed" if sheet.model else
                            "Bend radius and outer radius are checked; the flat pattern, bend reliefs and "
                            "hole-to-bend distances are not analysed")
        elif p in ("fdm", "sla", "sls"):
            pr = shop.printers(p)
            if pr and not any(_fits(dims, m.travel_mm) for m in pr):
                score -= 30
                cons.append("Larger than the printer build volume in your shop profile")
            elif not pr:
                cons.append("No printer of this type in your shop profile (outsourced)")
                score -= 5
            else:
                pros.append("Fits the printer build volume")
            pros.append("No tooling; geometry complexity costs little")
        elif p in ("casting", "injection_moulding"):
            if draft_faces:
                score -= 5 if p == "casting" else 10
                cons.append(f"{draft_faces} face(s) need draft added")
            if mould_undercuts:
                score -= 10 if p == "casting" else 15
                cons.append(f"{mould_undercuts} undercut face(s) need cores or side actions")
            if p == "injection_moulding" and thick_for_moulding:
                score -= 15
                cons.append("Thick sections: core out to uniform walls before moulding")
            if p == "casting":
                cons.append("Machined datums and holes still need secondary machining")
        if feasible and cheapest and p in unit_costs:
            rel = cheapest / unit_costs[p] if unit_costs[p] > 0 else 1.0
            bonus = round(10 * rel)
            score += bonus
            if rel > 0.999:
                pros.append(f"Lowest relative unit cost at {quantity:,} parts (estimate)")
        analysed = p in RULES_FOR
        n_crit = crit.get(RULES_FOR.get(p, ""), 0)
        if feasible and not analysed:
            cons.append("Printability is not analysed here: open 3D Print Prep for wall, overhang and support checks")
            score = min(score, CAP)
            conf = "low"
        if feasible and n_crit:
            cons.append(f"{n_crit} critical finding{'s' if n_crit > 1 else ''} to resolve before this process fits")
            score = min(score, CAP)
            conf = "low"
        score = max(0, min(100, score)) if feasible else 0
        fit = "Not suitable" if not feasible else "Possible: not analysed" if not analysed and score >= 45 \
            else "Good fit" if score >= 70 else "Possible" if score >= 45 \
            else "Poor fit"
        out.append({"process": p, "name": pname, "score": score, "fit": fit, "feasible": feasible, "analysed": analysed,
                    "critical": n_crit if feasible else 0,
                    "confidence": conf, "pros": pros, "cons": cons, "unit_cost": unit_costs.get(p)})
    out.sort(key=lambda r: (-r["score"], list(NAMES).index(r["process"])))
    return {"advice_level": ADVICE_LEVELS["check"], "ranking": out, "assumptions": [
        f"Quantity {quantity:,}, material {mat['name']}, tolerance class '{tolerance}'.",
        ("Scores are rules of thumb from typical industry practice, adjusted by your shop profile and the measured "
        "geometry; they are a starting point for a supplier conversation, not a decision."),
        "Surface finish, certification, lead time and supplier capacity are not considered.",
    ]}
