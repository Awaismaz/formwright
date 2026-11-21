"""Fastener auto-fit: choose an ISO metric fastener stack for a hole from its clearance diameter and the measured grip.

Pure functions (no CAD kernel). The geometry side (``geometry.probe_hole``) measures the clamped stack along the hole
axis; this module turns that into a proposal: size from the clearance diameter (ISO 273), bolt or socket head cap
screw + washers + nut, and a bolt length picked from the standard nominal length series so the thread protrudes
properly (through joints) or engages enough thread (tapped joints).

Every proposal states the rule it used, the sources, and is flagged "verify": the tables are nominal catalogue
values and the rules are common design practice, not a joint calculation (preload, strength and fatigue are an
engineering check: see the Engineering Advisor's bolted-joint calculator).
"""

from __future__ import annotations

import math
from typing import Any

from aicad import toolbox

# ISO 261 coarse pitch, P (mm)
PITCH = {3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75, 16: 2.0, 20: 2.5, 24: 3.0}
# ISO 273 clearance holes: d -> (fine, medium, coarse) hole Ø
CLEARANCE = {3: (3.2, 3.4, 3.6), 4: (4.3, 4.5, 4.8), 5: (5.3, 5.5, 5.8), 6: (6.4, 6.6, 7.0), 8: (8.4, 9.0, 10.0),
             10: (10.5, 11.0, 12.0), 12: (13.0, 13.5, 14.5), 16: (17.0, 17.5, 18.5), 20: (21.0, 22.0, 24.0),
             24: (25.0, 26.0, 28.0)}
CLASSES = ("fine", "medium", "coarse")
# ISO 888 preferred nominal lengths for bolts and screws (mm); supplier ranges per size vary: verify stock
LENGTHS = (3, 4, 5, 6, 8, 10, 12, 16, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80, 90, 100, 110, 120, 130, 140,
           150, 160, 180, 200, 220, 240, 260, 280, 300)
MIN_PROTRUSION_PITCHES = 2.0
STYLES = {"hex_bolt": "ISO 4017", "shcs": "ISO 4762"}
SOURCES = [
    "ISO 273: clearance holes for bolts and screws (fine / medium / coarse series)",
    "ISO 261: coarse thread pitch",
    "ISO 888: nominal lengths for bolts, screws and studs",
    ("ISO 4017 hex head screw, ISO 4762 socket head cap screw, ISO 7089 washer, ISO 4032 hex nut "
     "(head, washer and nut dimensions from the Formwright Toolbox tables)"),
]
THROUGH_RULE = ("Through joint: L ≥ grip + washers + nut height m + 2 × pitch, so at least two full threads "
                "protrude beyond the nut; then the next length in the ISO 888 series. Common design practice: verify "
                "against your company standard.")
TAPPED_RULE = ("Tapped joint: thread engagement ≥ 1.5 × d in steel, cast iron and copper alloys, 2.0 × d in "
               "aluminium, other light alloys and plastics (common practice, e.g. Machinery's Handbook / VDI 2230 "
               "guidance; VDI 2230 gives the calculated value), and the screw stays 2 × pitch clear of the bottom of a "
               "blind hole; then a length from the ISO 888 series. Verify.")


def pitch(d: int) -> float:
    return PITCH[d]


def size_for_clearance(hole_d: float) -> dict[str, Any] | None:
    """Thread size for a clearance hole. Exact ISO 273 match (±0.05 mm) first; otherwise the largest size whose
    fine clearance fits the hole, with a warning."""
    for d, row in CLEARANCE.items():
        for cls, h in zip(CLASSES, row, strict=True):
            if abs(hole_d - h) <= 0.05:
                return {"d": d, "class": cls, "exact": True, "nominal_hole": h}
    fits = [d for d, row in CLEARANCE.items() if row[0] <= hole_d + 0.05]
    if not fits:
        return None
    d = max(fits)
    return {"d": d, "class": None, "exact": False, "nominal_hole": None}


def tap_size(hole_d: float) -> dict[str, Any] | None:
    """Thread size for a tapped hole: a tap-drill-sized hole (between d − 1.25 P and d − 0.75 P, which brackets the
    usual d − P drill), or a hole modelled at the nominal thread diameter."""
    for d, P in PITCH.items():
        if d - 1.25 * P <= hole_d <= d - 0.75 * P:
            return {"d": d, "modelled": "tap drill", "drill": round(d - P, 2)}
    for d, P in PITCH.items():
        if abs(hole_d - d) <= 0.02:
            return {"d": d, "modelled": "nominal", "drill": round(d - P, 2)}
    return None


def next_length(L_min: float, lo: float = 0.0, hi: float = math.inf) -> int | None:
    """Smallest ISO 888 length ≥ L_min (1 µm tolerance) inside [lo, hi]."""
    for L in LENGTHS:
        if L + 1e-6 >= L_min and lo - 1e-6 <= L <= hi + 1e-6:
            return L
    return None


UNKNOWN_MATERIAL = "unknown material (conservative)"


def engagement_factor(material: str | None) -> tuple[float, str]:
    """Minimum thread engagement in the tapped part, as a multiple of d, by that part's material (PD-285): 1.5 d in
    steel, cast iron and copper alloys (cast iron is often 1.5 d, steel 1 to 1.5 d), 2 d in aluminium, other light
    alloys and plastics, 2 d when the material is unknown. Common practice (e.g. Machinery's Handbook / VDI 2230
    guidance), verify."""
    t = (material or "").lower()
    if any(k in t for k in ("cast iron", "grey iron", "gray iron", "ductile iron", "brass", "bronze", "copper")):
        return 1.5, "cast iron / copper alloy"
    if any(k in t for k in ("steel", "stainless", "titanium")) and "alumin" not in t:
        return 1.5, "steel"
    if any(k in t for k in ("alumin", "magnesium", "zinc", "zamak", "abs", "pla", "petg", "nylon", "pa1", "pa6",
                            "pom", "acetal", "delrin", "polycarb", "peek", "uhmw", "plastic")):
        return 2.0, "aluminium / light alloy / plastic"
    return 2.0, UNKNOWN_MATERIAL


def through_length(d: int, grip: float, washer_head: bool, washer_nut: bool) -> dict[str, Any]:
    """Bolt length for a through joint (head + washers + clamped parts + nut)."""
    P = PITCH[d]
    wh = toolbox.WASHER[d][2] if washer_head else 0.0
    wn = toolbox.WASHER[d][2] if washer_nut else 0.0
    m = toolbox.NUT_M[d]
    prot = MIN_PROTRUSION_PITCHES * P
    L_min = grip + wh + wn + m + prot
    L = next_length(L_min, lo=d, hi=min(300.0, 20.0 * d))
    terms = [{"label": "Grip (clamped parts)", "mm": round(grip, 3)}]
    if washer_head:
        terms.append({"label": "Washer under head (ISO 7089)", "mm": wh})
    if washer_nut:
        terms.append({"label": "Washer under nut (ISO 7089)", "mm": wn})
    terms += [{"label": "Nut height m (ISO 4032)", "mm": m},
              {"label": f"Protrusion 2 × P (P = {P:g})", "mm": prot}]
    out: dict[str, Any] = {"L": L, "L_min": round(L_min, 3), "terms": terms, "rule": THROUGH_RULE}
    if L is not None:
        out["protrusion"] = round(L - (grip + wh + wn + m), 3)
        out["protrusion_threads"] = round(out["protrusion"] / P, 1)
    return out


def tapped_length(d: int, grip: float, washer_head: bool, depth: float, blind: bool, material: str | None,
                  beyond: float | None = None) -> dict[str, Any]:
    """Screw length for a tapped joint: engagement between the material minimum and the usable thread depth. A
    through tapped hole lets the screw protrude out of the far side, by up to 1 × d (less when another part is
    closer than that)."""
    P = PITCH[d]
    wh = toolbox.WASHER[d][2] if washer_head else 0.0
    k, mat_label = engagement_factor(material)
    e_min = k * d
    usable = depth - (2 * P if blind else 0.0)  # blind: keep clear of the hole bottom (thread run-out)
    lo = grip + wh + e_min
    out_allow = 0.0 if blind else min(float(d), beyond if beyond is not None else float(d))
    hi = grip + wh + usable + out_allow
    L = next_length(lo, lo=d, hi=min(hi, 300.0, 20.0 * d))
    terms = [{"label": "Clamped parts", "mm": round(grip, 3)}]
    if washer_head:
        terms.append({"label": "Washer under head (ISO 7089)", "mm": wh})
    terms.append({"label": f"Min. engagement {k:g} × d ({mat_label})", "mm": round(e_min, 3)})
    out: dict[str, Any] = {"L": L, "L_min": round(lo, 3), "L_max": round(hi, 3), "terms": terms, "rule": TAPPED_RULE,
                           "usable_thread": round(usable, 3)}
    if L is not None:
        out["engagement"] = round(min(L - grip - wh, depth), 3)
        out["protrudes"] = round(max(0.0, L - grip - wh - depth), 3) if not blind else 0.0
    return out


def _item(role: str, code: str, params: dict[str, float]) -> dict[str, Any]:
    c = toolbox.spec(code)
    p = toolbox.normalize(code, params)
    return {"role": role, "code": code, "params": p, "title": c.title(p), "standard": c.standard,
            "material": c.material}


def propose(probe: dict[str, Any], style: str = "hex_bolt", washers: str = "both") -> dict[str, Any]:
    """A fastener stack for one probed hole. ``style``: hex_bolt | shcs; ``washers``: both | head | none."""
    if style not in STYLES:
        raise ValueError("unknown fastener style")
    if washers not in ("both", "head", "none"):
        raise ValueError("unknown washer option")
    warnings = list(probe.get("warnings") or [])
    base: dict[str, Any] = {"ok": False, "verify": True, "sources": SOURCES, "warnings": warnings,
                            "kind": probe.get("kind"), "grip": probe.get("grip"), "members": probe.get("members", [])}
    kind = probe.get("kind")
    if kind == "blocked":
        base["error"] = probe.get("reason") or "The hole is blocked by another part."
        return base
    size = size_for_clearance(float(probe["hole_d"]))
    if size is None:
        base["error"] = f"Ø{probe['hole_d']:g} is smaller than any supported clearance hole (M3 and up)."
        return base
    d = int(size["d"])
    if kind == "tapped":
        tap = probe.get("tapped") or {}
        ts = tap_size(float(tap.get("d", 0)))
        if ts is None:
            base["error"] = f"The hole in {tap.get('name', 'the mating part')} (Ø{tap.get('d', 0):g}) is not a tap-drill size."
            return base
        if ts["d"] != d:
            warnings.append(f"The tapped hole suits M{ts['d']} but the clearance hole suits M{d}; M{ts['d']} used.")
            d = int(ts["d"])
        if ts["modelled"] == "nominal":
            warnings.append(f"The hole in {tap.get('name', 'the mating part')} is modelled at the nominal thread Ø; "
                            "assumed to be tapped M%d." % d)
    base["size"] = d
    base["designation"] = f"M{d}"
    base["pitch"] = PITCH[d]
    if size["exact"] and size["d"] == d:
        base["clearance"] = {"class": size["class"], "nominal": size["nominal_hole"],
                             "text": f"Ø{size['nominal_hole']:g} is the ISO 273 {size['class']} clearance hole for M{d}"}
    else:
        base["clearance"] = {"class": None, "nominal": None,
                             "text": f"Ø{probe['hole_d']:g} is not an ISO 273 clearance hole; M{d} is the largest size that passes"}
        if not size["exact"]:
            warnings.append(base["clearance"]["text"] + ".")
    w_head = washers in ("both", "head")
    if kind == "tapped":
        tap = probe["tapped"]
        ln = tapped_length(d, float(probe["grip"]), w_head, float(tap["depth"]), bool(tap.get("blind")),
                           tap.get("material"), tap.get("beyond"))
        w_nut = False
    else:
        w_nut = washers == "both"
        ln = through_length(d, float(probe["grip"]), w_head, w_nut)
    base["length"] = ln
    base["rule"] = ln["rule"]
    if ln["L"] is None:
        lim = min(300.0, 20.0 * d)
        if kind == "tapped" and ln.get("L_max") is not None and ln["L_max"] < ln["L_min"]:
            base["error"] = (f"The tapped hole is too shallow: it gives {ln['usable_thread']:g} mm of usable thread, "
                             f"M{d} needs at least {ln['terms'][-1]['mm']:g} mm of engagement.")
        else:
            top = ln.get("L_max")
            if kind == "tapped" and probe["tapped"].get("blind") and top is not None and top < lim:  # the bottom limits
                base["error"] = (f"No standard M{d} length fits between {ln['L_min']:g} and {top:g} mm (the engagement "
                                 "the material needs, and the bottom of the tapped hole).")
            else:
                base["error"] = f"No standard M{d} length fits (needs ≥ {ln['L_min']:g} mm; Toolbox range up to {lim:g} mm)."
        return base
    L = ln["L"]
    items = [_item("screw", style, {"D": d, "L": L})]
    if w_head:
        items.append(_item("washer_head", "washer", {"D": d}))
    if kind != "tapped":
        if w_nut:
            items.append(_item("washer_nut", "washer", {"D": d}))
        items.append(_item("nut", "hex_nut", {"D": d}))
    base["items"] = items
    base["ok"] = True
    nw = sum(1 for i in items if i["code"] == "washer")
    base["summary"] = (items[0]["title"] + ({0: "", 1: " + washer", 2: " + 2 washers"}[nw]) +
                       ("" if kind == "tapped" else " + nut"))
    return base
