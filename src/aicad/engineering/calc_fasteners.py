"""Fastener calculators: preloaded bolted joint in tension (Shigley ch. 8 approach) and thread engagement length."""

from __future__ import annotations

import math
from typing import Any

from aicad.engineering import standards as std
from aicad.engineering.core import (
    SHIGLEY_REF,
    Calculator,
    Column,
    InputError,
    Param,
    Work,
    g,
    register,
)

PI = math.pi
TAN30 = math.tan(math.radians(30))

SIZE_OPTIONS = [{"value": k, "label": f"{k} × {p}"} for k, (_, p) in std.COARSE_PITCH.items()] + \
    [{"value": "custom", "label": "Custom d × P"}]
CLASS_OPTIONS = [{"value": k, "label": f"Class {k}"} for k in std.PROPERTY_CLASSES] + \
    [{"value": "custom", "label": "Custom strengths"}]


def thread_params(default: str = "M10") -> list[Param]:
    return [
        Param("size", "Thread size", "enum", default, options=SIZE_OPTIONS, group="Thread", prefill="model",
              help="ISO metric coarse series (ISO 261)."),
        Param("d_custom", "Nominal diameter d", "length", 10.0, min=0, exclusive_min=True, group="Thread",
              show_if={"size": ["custom"]}),
        Param("p_custom", "Pitch P", "length", 1.5, min=0, exclusive_min=True, group="Thread",
              show_if={"size": ["custom"]}),
    ]


def thread(v: dict[str, Any], w: Work) -> tuple[float, float, dict[str, float], float]:
    if v["size"] == "custom":
        d, p = v["d_custom"], v["p_custom"]
    else:
        d, p = std.COARSE_PITCH[v["size"]]
    if p >= d / 2:
        raise InputError("Pitch is too large for the diameter")
    b = std.basic_diameters(d, p)
    w.step("Basic diameters", "d₂ = d − 0.649519P, D₁ = d − 1.082532P, d₃ = d − 1.226869P",
           f"d = {g(d)}, P = {g(p)}", f"d₂ = {g(b['d2'])}, D₁ = {g(b['D1'])}, d₃ = {g(b['d3'])} mm",
           ref="ISO 724")
    As = std.tensile_stress_area(d, p)
    w.step("Tensile stress area", "As = (π/4)·((d₂ + d₃)/2)²", f"(π/4) × (({g(b['d2'])} + {g(b['d3'])})/2)²", As,
           "mm²", ref="ISO 898-1")
    return d, p, b, As


def bolt_strengths(v: dict[str, Any], d: float, w: Work) -> tuple[float, float, float, str]:
    if v["cls"] == "custom":
        Sp, Sut, Sy = v["Sp_custom"], v["Sut_custom"], v["Sy_custom"]
        src = "user input"
    else:
        row = std.property_class(v["cls"], d)
        if row is None:
            raise InputError(f"Property class {v['cls']} is not defined in ISO 898-1 for d = {g(d)} mm; "
                             "choose another class or enter custom strengths")
        Sp, Sut, Sy = row["Sp"], row["Sut"], row["Sy"]
        src = std.PROPERTY_CLASS_SOURCE
    w.step("Bolt strengths", "Sp, Sut, Sy", src, f"Sp = {g(Sp)}, Sut = {g(Sut)}, Sy = {g(Sy)} MPa")
    return Sp, Sut, Sy, src


def frustum_stiffness(E: float, t: float, D: float, d: float) -> float:
    """Shigley Eq. (8-20): one 30° frustum of thickness t, smaller diameter D, hole diameter d (N/mm)."""
    num = 0.5774 * PI * E * d
    den = math.log((1.155 * t + D - d) * (D + d) / ((1.155 * t + D + d) * (D - d)))
    return num / den


def member_stiffness(layers: list[tuple[float, float]], d: float, dw: float) -> tuple[float, list[dict[str, Any]]]:
    """Members as stacked layers [(t, E)], top to bottom. The pressure cone (30°) spreads from both bearing faces to
    the mid-plane of the grip; each layer/half intersection is one frustum (Shigley §8-5, Eqs. (8-18), (8-20))."""
    grip = sum(t for t, _ in layers)
    half = grip / 2
    segs: list[dict[str, Any]] = []
    z = 0.0
    bounds = []
    for t, E in layers:
        bounds.append((z, z + t, E))
        z += t
    for z0, z1, E in bounds:
        for lo, hi, side in ((0.0, half, "top"), (half, grip, "bottom")):
            a, b = max(z0, lo), min(z1, hi)
            if b - a <= 1e-12:
                continue
            x0 = a if side == "top" else grip - b       # distance of the frustum's small end from its bearing face
            D = dw + 2 * x0 * TAN30
            k = frustum_stiffness(E, b - a, D, d)
            segs.append({"t": b - a, "E": E, "D": D, "k": k, "side": side})
    km = 1 / sum(1 / s["k"] for s in segs)
    return km, segs


def _bolt(v: dict[str, Any]) -> Work:
    w = Work()
    d, _p, _b, As = thread(v, w)
    Sp, Sut, _Sy, _ = bolt_strengths(v, d, w)
    layers = [(r["t"], r["E"]) for r in v["layers"]]
    if any(t <= 0 or E <= 0 for t, E in layers):
        raise InputError("Each member layer needs a positive thickness and modulus")
    grip = sum(t for t, _ in layers)
    w.step("Grip length", "l = Σ tᵢ", " + ".join(g(t) for t, _ in layers), grip, "mm")
    L = v["L"]
    if L < grip:
        raise InputError("Bolt length must be at least the grip length")
    LT = std.threaded_length(d, L)
    ld = max(0.0, L - LT)
    ld = min(ld, grip)
    lt = grip - ld
    w.step("Threaded length", "LT = 2d + 6 (L ≤ 125 mm)", f"2 × {g(d)} + …", LT, "mm", ref="Shigley Table 8-7")
    w.step("Unthreaded / threaded length in grip", "ld = L − LT, lt = l − ld", f"{g(L)} − {g(LT)}",
           f"ld = {g(ld)} mm, lt = {g(lt)} mm")
    Ad = PI * d ** 2 / 4
    Eb = v["Eb"]
    kb = Ad * As * Eb / (Ad * lt + As * ld) if (Ad * lt + As * ld) > 0 else math.inf
    w.step("Bolt stiffness", "kb = Ad·At·E / (Ad·lt + At·ld)",
           f"{g(Ad)} × {g(As)} × {g(Eb)} / ({g(Ad)} × {g(lt)} + {g(As)} × {g(ld)})", kb, "N/mm",
           ref="Shigley Eq. (8-17)")
    dw = v["dw"] or 1.5 * d
    km, segs = member_stiffness(layers, d, dw)
    for s in segs:
        w.step(f"Frustum ({s['side']} half), t = {g(s['t'])} mm", "k = 0.5774πEd / ln[(1.155t + D − d)(D + d) / "
               "((1.155t + D + d)(D − d))]", f"E = {g(s['E'])} MPa, D = {g(s['D'])} mm, d = {g(d)} mm", s["k"],
               "N/mm", ref="Shigley Eq. (8-20)")
    w.step("Member stiffness", "1/km = Σ 1/kᵢ", "", km, "N/mm", ref="Shigley Eq. (8-18)")
    C = kb / (kb + km)
    w.step("Joint stiffness constant", "C = kb / (kb + km)", f"{g(kb)} / ({g(kb)} + {g(km)})", C,
           ref="Shigley Eq. (f), §8-7")
    Fp = As * Sp
    w.step("Proof load", "Fp = At·Sp", f"{g(As)} × {g(Sp)}", Fp, "N")
    mode = v["preload_mode"]
    K = v["K"]
    if mode == "proof_fraction":
        Fi = v["proof_fraction"] * Fp
        w.step("Preload", "Fi = f·Fp", f"{g(v['proof_fraction'])} × {g(Fp)}", Fi, "N", ref="Shigley Eq. (8-31)")
        T = K * Fi * d
        w.step("Tightening torque", "T = K·Fi·d", f"{g(K)} × {g(Fi)} × {g(d)}", T, "N·mm", ref="Shigley Eq. (8-27)")
    elif mode == "torque":
        T = v["T"]
        Fi = T / (K * d)
        w.step("Preload from torque", "Fi = T / (K·d)", f"{g(T)} / ({g(K)} × {g(d)})", Fi, "N",
               ref="Shigley Eq. (8-27)")
    else:
        Fi = v["Fi"]
        T = K * Fi * d
        w.step("Tightening torque", "T = K·Fi·d", f"{g(K)} × {g(Fi)} × {g(d)}", T, "N·mm", ref="Shigley Eq. (8-27)")
    if Fi > Fp:
        w.warnings.append(f"Preload {g(Fi / 1000)} kN exceeds the proof load {g(Fp / 1000)} kN: the bolt yields "
                          "during tightening.")
    w.out("As", "Tensile stress area At", As, "area")
    w.out("kb", "Bolt stiffness kb", kb, "stiffness")
    w.out("km", "Member stiffness km", km, "stiffness")
    w.out("C", "Joint constant C", C, primary=True)
    w.out("Fi", "Preload Fi", Fi, "force", primary=True)
    w.out("T", "Tightening torque T", T, "moment", primary=True)
    P = v["P"]
    sf_req, sf_src = v["sf_required"], v["sf_source"]
    if P > 0:
        Fb = C * P + Fi
        w.step("Bolt load under external load", "Fb = C·P + Fi", f"{g(C)} × {g(P)} + {g(Fi)}", Fb, "N",
               ref="Shigley Eq. (8-24)")
        n_p = Sp * As / Fb
        w.step("Yielding factor (proof)", "np = Sp·At / (C·P + Fi)", f"{g(Sp)} × {g(As)} / {g(Fb)}", n_p,
               ref="Shigley Eq. (8-28)")
        n_L = (Sp * As - Fi) / (C * P)
        w.step("Load factor (overload)", "nL = (Sp·At − Fi) / (C·P)", f"({g(Sp * As)} − {g(Fi)}) / ({g(C)} × {g(P)})",
               n_L, ref="Shigley Eq. (8-29)")
        n_0 = Fi / (P * (1 - C))
        w.step("Joint separation factor", "n₀ = Fi / (P·(1 − C))", f"{g(Fi)} / ({g(P)} × (1 − {g(C)}))", n_0,
               ref="Shigley Eq. (8-30)")
        w.out("n_p", "Yielding factor np", n_p, primary=True)
        w.out("n_L", "Load factor nL", n_L)
        w.out("n_0", "Separation factor n₀", n_0, primary=True)
        w.sf_check("Bolt yield under load", n_p, sf_req, sf_src, "np = Sp·At / (C·P + Fi)")
        w.sf_check("Overload", n_L, sf_req, sf_src, "nL = (Sp·At − Fi) / (C·P)")
        w.sf_check("Joint separation", n_0, sf_req, sf_src, "n₀ = Fi / (P(1 − C))")
        # fatigue screening (Goodman, Shigley Eq. 8-38 general fluctuating load)
        if v["fatigue"]:
            if v["se_mode"] == "table":
                if v["cls"] not in std.BOLT_ENDURANCE:
                    raise InputError(f"No tabulated endurance strength for class {v['cls']}; enter Se")
                Se = std.BOLT_ENDURANCE[v["cls"]]
                w.step("Endurance strength", "Se (rolled threads, fully corrected)", std.BOLT_ENDURANCE_SOURCE, Se,
                       "MPa", ref="Shigley Table 8-17")
            else:
                Se = v["Se"]
                if not Se:
                    raise InputError("Enter the bolt endurance strength Se")
                w.step("Endurance strength (given)", "Se", "", Se, "MPa")
            Pmin = v["P_min"] or 0.0
            if Pmin > P:
                raise InputError("Minimum external load must not exceed the maximum")
            si = Fi / As
            sa = C * (P - Pmin) / (2 * As)
            sm = C * (P + Pmin) / (2 * As) + si
            w.step("Preload stress", "σi = Fi / At", f"{g(Fi)} / {g(As)}", si, "MPa")
            w.step("Alternating stress", "σa = C·(Pmax − Pmin) / (2At)", f"{g(C)} × ({g(P)} − {g(Pmin)}) / (2 × {g(As)})",
                   sa, "MPa", ref="Shigley Eq. (8-35)")
            w.step("Mean stress", "σm = C·(Pmax + Pmin) / (2At) + σi", "", sm, "MPa", ref="Shigley Eq. (8-36)")
            if sa <= 0:
                n_f = math.inf
            else:
                n_f = Se * (Sut - si) / (Sut * sa + Se * (sm - si))
            w.step("Fatigue factor (Goodman)", "nf = Se·(Sut − σi) / (Sut·σa + Se·(σm − σi))",
                   f"{g(Se)} × ({g(Sut)} − {g(si)}) / ({g(Sut)} × {g(sa)} + {g(Se)} × ({g(sm)} − {g(si)}))", n_f,
                   ref="Shigley Eq. (8-38)")
            w.out("sigma_a", "Alternating bolt stress σa", sa, "stress")
            w.out("n_f", "Fatigue factor nf (Goodman)", n_f, primary=True)
            w.sf_check("Bolt fatigue (Goodman screening)", n_f, sf_req, sf_src, "nf, Shigley Eq. (8-38)")
    else:
        w.notes.append("No external load given: only stiffness, preload and torque were computed.")
    w.notes.append("Torque-preload scatter with the nut factor K is large (±25 % or more); critical joints need "
                   "preload control (angle, tension or ultrasonic) and VDI 2230-level analysis.")
    return w


LAYER_COLUMNS = [Column("t", "Thickness", "length", "mm", 10.0, min=0),
                 Column("E", "Modulus E", "stress", "GPa", 207000.0, min=0),
                 Column("material", "Material", "text", default="")]

register(Calculator(
    id="bolted_joint", name="Bolted joint (tension, preload, fatigue)", category="Fasteners & joints",
    summary="Preloaded bolt in a tension joint: tensile stress area, bolt and member stiffness, preload and "
            "torque, yield, overload and separation factors, and Goodman fatigue screening.",
    inputs=[
        *thread_params("M10"),
        Param("cls", "Property class", "enum", "8.8", options=CLASS_OPTIONS, group="Bolt",
              help="ISO 898-1 minimum strengths."),
        Param("Sp_custom", "Proof strength Sp", "stress", 600.0, min=0, exclusive_min=True, group="Bolt",
              show_if={"cls": ["custom"]}),
        Param("Sut_custom", "Tensile strength Sut", "stress", 830.0, min=0, exclusive_min=True, group="Bolt",
              show_if={"cls": ["custom"]}),
        Param("Sy_custom", "Yield strength Sy", "stress", 660.0, min=0, exclusive_min=True, group="Bolt",
              show_if={"cls": ["custom"]}),
        Param("L", "Bolt length L", "length", 40.0, min=0, exclusive_min=True, group="Bolt"),
        Param("Eb", "Bolt modulus E", "stress", 207000.0, unit="GPa", min=0, exclusive_min=True, group="Bolt"),
        Param("layers", "Clamped members (top to bottom)", "table", [{"t": 10.0, "E": 207000.0, "material": "Steel"},
                                                                    {"t": 10.0, "E": 207000.0, "material": "Steel"}],
              columns=LAYER_COLUMNS, group="Members", prefill="model",
              help="Include washers as layers. The grip is the sum of the thicknesses."),
        Param("dw", "Washer-face diameter", "length", None, min=0, exclusive_min=True, group="Members",
              optional=True, help="Bearing diameter of head / washer. Empty = 1.5·d."),
        Param("preload_mode", "Preload from", "enum", "proof_fraction", group="Preload",
              options=[{"value": "proof_fraction", "label": "Fraction of proof load"},
                       {"value": "torque", "label": "Tightening torque"},
                       {"value": "preload", "label": "Known preload"}]),
        Param("proof_fraction", "Fraction of proof load", "ratio", 0.75, min=0, max=1, group="Preload",
              show_if={"preload_mode": ["proof_fraction"]},
              help="Shigley Eq. (8-31): 0.75 for reusable joints, 0.90 for permanent joints."),
        Param("T", "Tightening torque T", "moment", 50000.0, unit="N*m", min=0, exclusive_min=True, group="Preload",
              show_if={"preload_mode": ["torque"]}),
        Param("Fi", "Preload Fi", "force", 20000.0, unit="kN", min=0, exclusive_min=True, group="Preload",
              show_if={"preload_mode": ["preload"]}),
        Param("K", "Nut factor K", "ratio", 0.20, min=0.05, max=0.5, group="Preload",
              help="Shigley Table 8-15: 0.30 black finish, 0.20 zinc-plated, 0.18 lubricated, 0.16 cadmium. "
                   "Use the fastener supplier's value when available."),
        Param("P", "External tensile load per bolt P", "force", 0.0, unit="kN", min=0, group="Load",
              help="Share of the separating load carried by one bolt."),
        Param("fatigue", "Fluctuating load (fatigue screening)", "bool", False, group="Load"),
        Param("P_min", "Minimum load per bolt", "force", 0.0, unit="kN", min=0, group="Load",
              show_if={"fatigue": [True]}, optional=True),
        Param("se_mode", "Endurance strength", "enum", "table", group="Load", show_if={"fatigue": [True]},
              options=[{"value": "table", "label": "Tabulated (rolled threads)"},
                       {"value": "user", "label": "Enter Se"}]),
        Param("Se", "Endurance strength Se", "stress", None, min=0, exclusive_min=True, group="Load", optional=True,
              show_if={"se_mode": ["user"]}),
    ],
    func=_bolt, safety_factor=True,
    references=[(f"{SHIGLEY_REF}, ch. 8: Eqs. (8-17), (8-18), (8-20), (8-24), (8-27) to (8-31), (8-35) to (8-38); "
                "Tables 8-7, 8-11, 8-15, 8-17"), "ISO 898-1:2013 (property classes, tensile stress area)",
                "ISO 724 (basic thread dimensions)"],
    assumptions=["Concentric tensile load, no prying", "30° pressure-cone member stiffness (frusta)",
                 "Load introduced at the bearing faces (conservative for C)", ("Nut factor K applies to the "
                 "actual surface condition")],
    verified_against=[("Shigley 11th ed. Prob. 8-33 solution (M12 × 1.75 class 9.8, steel + cast iron): kb = 518.8 "
                      "MN/m, km = 1456 MN/m, C = 0.263, Fi = 41.1 kN, np = 1.29, nL = 11.1, n₀ = 11.8"),
                      "Shigley 11th ed. Prob. 8-52 solution (same joint, Goodman): nf = 7.55",
                      ("Shigley 11th ed. Probs. 8-19 / 8-20 solutions (layered aluminium/steel members): "
                      "km = 692.5 and 623.5 MN/m, kb = 292.1 and 247.6 MN/m"),
                      "Shigley 11th ed. Prob. 8-30 solution: T = K·Fi·d = 115 lbf·ft",
                      "ISO 898-1 tabulated stress areas M3 to M36"],
    keywords=["bolt", "screw", "preload", "torque", "clamp", "joint", "fatigue", "vdi 2230"],
    prefill=["Bolt size from a recognised clearance-hole pattern (ISO 273)", "Grip from the plate thickness",
             "Member modulus from the project material"],
))


# ----------------------------------------------------------------------------- thread engagement
def _engagement(v: dict[str, Any]) -> Work:
    w = Work()
    d, p, b, As = thread(v, w)
    Su_ext, Su_int = v["Sut_ext"], v["Sut_int"]
    D1, d2 = b["D1"], b["d2"]
    # Machinery's Handbook / FED-STD-H28: shear area per mm of engagement at basic limits
    ext_per_mm = PI * D1 * (0.5 + 0.57735 * (d2 - D1) / p)
    int_per_mm = PI * d * (0.5 + 0.57735 * (d - d2) / p)
    w.step("External-thread shear area per mm", "As,ext/Le = π·D₁·[½ + 0.57735·(d₂ − D₁)/P]",
           f"π × {g(D1)} × [0.5 + 0.57735 × ({g(d2)} − {g(D1)}) / {g(p)}]", ext_per_mm, "mm²/mm",
           ref="Machinery's Handbook, strength of screw threads")
    w.step("Internal-thread shear area per mm", "An/Le = π·d·[½ + 0.57735·(d − d₂)/P]",
           f"π × {g(d)} × [0.5 + 0.57735 × ({g(d)} − {g(d2)}) / {g(p)}]", int_per_mm, "mm²/mm")
    Le_ext = 2 * As / ext_per_mm
    w.step("Engagement for bolt to break before its threads strip", "Le = 2·At / (As,ext/Le)",
           f"2 × {g(As)} / {g(ext_per_mm)}", Le_ext, "mm", ref="Machinery's Handbook (shear strength = ½ tensile)")
    J = (ext_per_mm * Su_ext) / (int_per_mm * Su_int)
    w.step("Strength ratio", "J = (As,ext·Su,ext) / (An·Su,int)", f"({g(ext_per_mm)} × {g(Su_ext)}) / "
           f"({g(int_per_mm)} × {g(Su_int)})", J, ref="Machinery's Handbook")
    Le_int = J * Le_ext
    w.step("Engagement for the internal thread", "Le,int = J·Le", f"{g(J)} × {g(Le_ext)}", Le_int, "mm")
    Le_req = max(Le_ext, Le_int)
    w.step("Minimum engagement length", "Le,min = max(Le, J·Le)", "", Le_req, "mm")
    w.out("Le_min", "Minimum engagement length", Le_req, "length", primary=True)
    w.out("Le_over_d", "Minimum engagement / d", Le_req / d, primary=True)
    w.out("J", "Internal/external strength ratio J", J)
    w.out("As", "Tensile stress area At", As, "area")
    F_break = As * Su_ext
    w.step("Bolt tensile break load", "Fu = At·Su,ext", f"{g(As)} × {g(Su_ext)}", F_break, "N")
    w.out("F_break", "Bolt break load", F_break, "force")
    if v.get("Le"):
        Le = v["Le"]
        F_ext = 0.5 * Su_ext * ext_per_mm * Le
        F_int = 0.5 * Su_int * int_per_mm * Le
        w.step("External thread strip load at Le", "F = ½·Su,ext·(As,ext/Le)·Le", "", F_ext, "N")
        w.step("Internal thread strip load at Le", "F = ½·Su,int·(An/Le)·Le", "", F_int, "N")
        w.out("F_strip_ext", "External thread strip load", F_ext, "force")
        w.out("F_strip_int", "Internal thread strip load", F_int, "force")
        w.check("Bolt breaks before threads strip", min(F_ext, F_int) >= F_break,
                f"min strip load {g(min(F_ext, F_int))} N vs break load {g(F_break)} N", min(F_ext, F_int) / F_break)
        if v.get("F_service"):
            n = min(F_ext, F_int) / v["F_service"]
            w.step("Factor against stripping at service load", "n = min(F_strip) / F", "", n)
            w.sf_check("Thread stripping at service load", n, v["sf_required"], v["sf_source"],
                       "n = min strip load / service load")
    w.notes.append("Basic thread dimensions (ISO 724) are used for the limit diameters; tolerance classes "
                   "(6g/6H) slightly reduce the shear areas, so add margin or use the class limits for final design.")
    return w


register(Calculator(
    id="thread_engagement", name="Thread engagement length", category="Fasteners & joints",
    summary="Minimum length of engagement so the bolt breaks in tension before either thread strips, for "
            "internal threads in a weaker material (tapped aluminium, cast iron).",
    inputs=[
        *thread_params("M8"),
        Param("Sut_ext", "Bolt tensile strength Su", "stress", 800.0, min=0, exclusive_min=True, group="Materials"),
        Param("Sut_int", "Tapped material tensile strength", "stress", 310.0, min=0, exclusive_min=True,
              group="Materials", prefill="material"),
        Param("Le", "Actual engagement length", "length", None, min=0, exclusive_min=True, group="Check",
              optional=True, prefill="model"),
        Param("F_service", "Service tensile load", "force", None, min=0, exclusive_min=True, group="Check",
              optional=True),
    ],
    func=_engagement, safety_factor=True,
    references=[("Machinery's Handbook, 30th ed., 'Strength of screw threads' (length of engagement formulas, "
                "after FED-STD-H28)"), "ISO 724 (basic dimensions)", "ISO 898-1 (tensile stress area)"],
    assumptions=["Ultimate shear strength = ½ × ultimate tensile strength (handbook basis)", ("Basic profile "
                 "limit diameters"), ("Uniform load distribution over the engaged threads (real threads load the "
                 "first turns more)")],
    verified_against=[("Independent hand derivation: shear areas recomputed from the ISO 68-1 basic profile "
                      "geometry (no published worked example cited)")],
    keywords=["tapped hole", "thread strip", "engagement", "helicoil", "insert"],
    prefill=["Thread size from a recognised hole", "Engagement from the blind-hole depth"],
))
