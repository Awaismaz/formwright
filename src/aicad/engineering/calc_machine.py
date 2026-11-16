"""Machine-element calculators: shaft under combined bending + torsion (static and fatigue), rolling bearing life
(ISO 281), helical compression spring, and 1D tolerance stack-up (worst case and RSS)."""

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


# ----------------------------------------------------------------------------- shaft
def marin_se(v: dict[str, Any], w: Work) -> float:
    Sut, d = v["Sut"], v["d"]
    Se_p = 0.5 * Sut if Sut <= 1400 else 700.0
    w.step("Rotating-beam endurance limit", "Se' = 0.5·Sut (Sut ≤ 1400 MPa), else 700 MPa", f"0.5 × {g(Sut)}", Se_p,
           "MPa", ref="Shigley Eq. (6-8)")
    a, b = std.SURFACE_FACTOR[v["finish"]]
    ka = a * Sut ** b
    w.step("Surface factor", "ka = a·Sut^b", f"{g(a)} × {g(Sut)}^{g(b)} ({v['finish']})", ka,
           ref="Shigley Eq. (6-19), Table 6-2")
    if d <= 51:
        kb = (d / 7.62) ** -0.107 if d >= 2.79 else 1.0
        eq = "kb = (d/7.62)^−0.107 (2.79 ≤ d ≤ 51 mm)"
    elif d <= 254:
        kb = 1.51 * d ** -0.157
        eq = "kb = 1.51·d^−0.157 (51 < d ≤ 254 mm)"
    else:
        raise InputError("Size factor is defined up to d = 254 mm")
    w.step("Size factor", eq, f"d = {g(d)} mm", kb, ref="Shigley Eq. (6-20)")
    ke = std.RELIABILITY_KE[v["reliability"]]
    w.step("Reliability factor", "ke", f"R = {v['reliability']} %", ke, ref="Shigley Table 6-5")
    kd, kf = v["kd"], v["kf_misc"]
    Se = ka * kb * kd * ke * kf * Se_p
    w.step("Endurance limit at the critical location", "Se = ka·kb·kc·kd·ke·kf·Se' (kc = 1, bending)",
           f"{g(ka)} × {g(kb)} × 1 × {g(kd)} × {g(ke)} × {g(kf)} × {g(Se_p)}", Se, "MPa", ref="Shigley Eq. (6-18)")
    return Se


def _shaft(v: dict[str, Any]) -> Work:
    w = Work()
    d = v["d"]
    Ma, Mm, Ta, Tm = v["Ma"], v["Mm"], v["Ta"], v["Tm"]
    if v["kf_mode"] == "kt_q":
        Kf = 1 + v["q"] * (v["Kt"] - 1)
        Kfs = 1 + v["qs"] * (v["Kts"] - 1)
        w.step("Fatigue stress-concentration factors", "Kf = 1 + q(Kt − 1), Kfs = 1 + qs(Kts − 1)",
               f"1 + {g(v['q'])}({g(v['Kt'])} − 1), 1 + {g(v['qs'])}({g(v['Kts'])} − 1)",
               f"Kf = {g(Kf)}, Kfs = {g(Kfs)}", ref="Shigley Eq. (6-32)")
    else:
        Kf, Kfs = v["Kf"], v["Kfs"]
        w.step("Fatigue stress-concentration factors (given)", "Kf, Kfs", "", f"Kf = {g(Kf)}, Kfs = {g(Kfs)}")
    Sut, Sy = v["Sut"], v["Sy"]
    if Sy > Sut:
        raise InputError("Yield strength cannot exceed the ultimate strength")
    if v["se_mode"] == "given":
        Se = v["Se"]
        if not Se:
            raise InputError("Enter the endurance limit Se, or choose 'Estimate (Marin factors)'")
        w.step("Endurance limit (given)", "Se", "", Se, "MPa")
    else:
        Se = marin_se(v, w)
    k = 32 / (PI * d ** 3)
    ks = 16 / (PI * d ** 3)
    sa, sm = Kf * Ma * k, Kf * Mm * k
    ta, tm = Kfs * Ta * ks, Kfs * Tm * ks
    w.step("Bending stresses", "σa,m = Kf·32·Ma,m / (π·d³)", f"Kf = {g(Kf)}, d = {g(d)}",
           f"σa = {g(sa)}, σm = {g(sm)} MPa", ref="Shigley Eqs. (7-3), (7-4)")
    w.step("Torsional stresses", "τa,m = Kfs·16·Ta,m / (π·d³)", f"Kfs = {g(Kfs)}", f"τa = {g(ta)}, τm = {g(tm)} MPa")
    va = math.sqrt(sa ** 2 + 3 * ta ** 2)
    vm = math.sqrt(sm ** 2 + 3 * tm ** 2)
    w.step("von Mises alternating stress", "σ'a = √(σa² + 3τa²)", "", va, "MPa", ref="Shigley Eq. (7-5)")
    w.step("von Mises mean stress", "σ'm = √(σm² + 3τm²)", "", vm, "MPa", ref="Shigley Eq. (7-6)")
    inv = va / Se + vm / Sut
    nf = 1 / inv if inv > 0 else math.inf
    w.step("Fatigue factor (DE-Goodman)", "1/n = σ'a/Se + σ'm/Sut", f"{g(va)}/{g(Se)} + {g(vm)}/{g(Sut)}", nf,
           ref="Shigley Eq. (7-7)")
    vmax = math.sqrt((sm + sa) ** 2 + 3 * (tm + ta) ** 2)
    w.step("Maximum von Mises stress (first-cycle yield)", "σ'max = √((σm + σa)² + 3(τm + τa)²)", "", vmax, "MPa",
           ref="Shigley Eq. (7-15)")
    ny = Sy / vmax if vmax > 0 else math.inf
    w.step("Yield factor", "ny = Sy / σ'max", f"{g(Sy)} / {g(vmax)}", ny, ref="Shigley Eq. (7-16)")
    w.out("Se", "Endurance limit Se", Se, "stress")
    w.out("sigma_a_vm", "von Mises alternating σ'a", va, "stress")
    w.out("sigma_m_vm", "von Mises mean σ'm", vm, "stress")
    w.out("sigma_max_vm", "Maximum von Mises σ'max", vmax, "stress")
    w.out("n_f", "Fatigue factor nf (DE-Goodman)", nf, primary=True)
    w.out("n_y", "Yield factor ny", ny, primary=True)
    sf_req, sf_src = v["sf_required"], v["sf_source"]
    w.sf_check("Fatigue (DE-Goodman, infinite life)", nf, sf_req, sf_src, "Shigley Eq. (7-7)")
    w.sf_check("First-cycle yield (von Mises)", ny, sf_req, sf_src, "ny = Sy / σ'max")
    if sf_req:
        A = math.sqrt(4 * (Kf * Ma) ** 2 + 3 * (Kfs * Ta) ** 2)
        B = math.sqrt(4 * (Kf * Mm) ** 2 + 3 * (Kfs * Tm) ** 2)
        dmin = (16 * sf_req / PI * (A / Se + B / Sut)) ** (1 / 3)
        w.step("Minimum diameter for the required factor (DE-Goodman)",
               "d = [16n/π · (√(4(KfMa)² + 3(KfsTa)²)/Se + √(4(KfMm)² + 3(KfsTm)²)/Sut)]^(1/3)",
               f"n = {g(sf_req)}", dmin, "mm", ref="Shigley Eq. (7-8)")
        w.out("d_min", "Minimum diameter for required factor", dmin, "length", primary=True)
        if v["se_mode"] != "given":
            w.notes.append("Se depends on d through the size factor kb; the minimum diameter uses Se at the "
                           "entered d (iterate if they differ much).")
    w.notes.append("Kt values come from charts (e.g. Shigley Fig. A-15) or Peterson's Stress Concentration "
                   "Factors; they are inputs here, not computed from the geometry.")
    return w


register(Calculator(
    id="shaft_fatigue", name="Shaft: bending + torsion (static and fatigue)", category="Shafts & fits",
    summary="Combined bending and torsion at a shaft section: von Mises stresses, DE-Goodman fatigue factor, "
            "first-cycle yield factor, and the minimum diameter for a required factor.",
    inputs=[
        Param("d", "Diameter at the section d", "length", 25.0, min=0, exclusive_min=True, group="Section",
              prefill="model"),
        Param("Ma", "Alternating bending moment Ma", "moment", 70000.0, unit="N*m", min=0, group="Loads",
              help="A rotating shaft under a steady transverse load sees fully reversed bending: Ma = M, Mm = 0."),
        Param("Mm", "Mean bending moment Mm", "moment", 0.0, unit="N*m", min=0, group="Loads"),
        Param("Ta", "Alternating torque Ta", "moment", 0.0, unit="N*m", min=0, group="Loads"),
        Param("Tm", "Mean torque Tm", "moment", 45000.0, unit="N*m", min=0, group="Loads"),
        Param("kf_mode", "Stress concentration", "enum", "direct", group="Stress concentration",
              options=[{"value": "direct", "label": "Enter Kf and Kfs"}, {"value": "kt_q", "label": "From Kt and q"}]),
        Param("Kf", "Kf (bending)", "ratio", 1.0, min=1, group="Stress concentration", show_if={"kf_mode": ["direct"]}),
        Param("Kfs", "Kfs (torsion)", "ratio", 1.0, min=1, group="Stress concentration",
              show_if={"kf_mode": ["direct"]}),
        Param("Kt", "Kt (bending)", "ratio", 1.7, min=1, group="Stress concentration", show_if={"kf_mode": ["kt_q"]}),
        Param("q", "Notch sensitivity q", "ratio", 0.8, min=0, max=1, group="Stress concentration",
              show_if={"kf_mode": ["kt_q"]}),
        Param("Kts", "Kts (torsion)", "ratio", 1.4, min=1, group="Stress concentration",
              show_if={"kf_mode": ["kt_q"]}),
        Param("qs", "Notch sensitivity qs", "ratio", 0.9, min=0, max=1, group="Stress concentration",
              show_if={"kf_mode": ["kt_q"]}),
        Param("Sut", "Ultimate strength Sut", "stress", 630.0, min=0, exclusive_min=True, group="Material",
              prefill="material"),
        Param("Sy", "Yield strength Sy", "stress", 530.0, min=0, exclusive_min=True, group="Material",
              prefill="material"),
        Param("se_mode", "Endurance limit", "enum", "estimate", group="Material",
              options=[{"value": "estimate", "label": "Estimate (Marin factors)"},
                       {"value": "given", "label": "Enter Se"}]),
        Param("Se", "Endurance limit Se", "stress", None, min=0, exclusive_min=True, group="Material", optional=True,
              show_if={"se_mode": ["given"]}),
        Param("finish", "Surface finish", "enum", "machined", group="Material", show_if={"se_mode": ["estimate"]},
              options=[{"value": k, "label": k.capitalize()} for k in std.SURFACE_FACTOR]),
        Param("reliability", "Reliability", "enum", "99", group="Material", show_if={"se_mode": ["estimate"]},
              options=[{"value": k, "label": f"{k} %"} for k in std.RELIABILITY_KE]),
        Param("kd", "Temperature factor kd", "ratio", 1.0, min=0, max=1.1, group="Material",
              show_if={"se_mode": ["estimate"]}),
        Param("kf_misc", "Miscellaneous factor kf", "ratio", 1.0, min=0, max=1.1, group="Material",
              show_if={"se_mode": ["estimate"]}),
    ],
    func=_shaft, safety_factor=True,
    references=[(f"{SHIGLEY_REF}, §7-4 Eqs. (7-3)–(7-8), (7-15), (7-16); §6-9 Marin factors (Eqs. 6-8, 6-18–6-20, "
                "Tables 6-2, 6-5); Eq. (6-32)")],
    assumptions=["Steel shaft, infinite-life (endurance-limit) approach", "Solid round section", ("Axial load "
                 "neglected"), "Kt and q taken from charts by the user", "Distortion-energy (von Mises) combination"],
    verified_against=["Shigley 10th ed. Prob. 7-1 solution (DE-Goodman, n = 2): d = 27.27 mm",
                      ("Shigley 10th ed. Prob. 7-2 solution (Marin factors, 175 kpsi, machined, d = 0.75 in): "
                      "ka = 0.69, kb = 0.91, Se = 54.9 kpsi")],
    keywords=["shaft", "goodman", "fatigue", "von mises", "torsion", "bending", "endurance"],
    prefill=["Diameter from the smallest turned diameter", "Sut and Sy from the project material"],
))


# ----------------------------------------------------------------------------- bearing life
def _bearing(v: dict[str, Any]) -> Work:
    w = Work()
    p_exp = 3.0 if v["type"] == "ball" else 10 / 3
    w.step("Life exponent", "p = 3 (ball), 10/3 (roller)", v["type"], p_exp, ref="ISO 281:2007")
    if v["load_mode"] == "xy":
        P = v["X"] * v["Fr"] + v["Y"] * v["Fa"]
        w.step("Equivalent dynamic load", "P = X·Fr + Y·Fa", f"{g(v['X'])} × {g(v['Fr'])} + {g(v['Y'])} × {g(v['Fa'])}",
               P, "N", ref="ISO 281:2007 / bearing catalogue X, Y")
    else:
        P = v["P"]
    af = v["af"]
    if af != 1:
        w.step("Design load with application factor", "Fd = af·P", f"{g(af)} × {g(P)}", af * P, "N",
               ref="Shigley Table 11-5")
        P = af * P
    if P <= 0:
        raise InputError("Equivalent load must be positive")
    w.out("P", "Equivalent dynamic load P", P, "force")
    n = v["n"]
    if v.get("C"):
        C = v["C"]
        L10 = (C / P) ** p_exp
        w.step("Basic rating life", "L10 = (C/P)^p", f"({g(C)} / {g(P)})^{g(p_exp)}", L10, "million rev",
               ref="ISO 281:2007 Eq. (1)")
        L10h = L10 * 1e6 / (60 * n)
        w.step("Basic rating life in hours", "L10h = 10⁶·L10 / (60·n)", f"10⁶ × {g(L10)} / (60 × {g(n)})", L10h, "h")
        a1 = std.BEARING_A1[v["reliability"]]
        aiso = v["aiso"]
        w.step("Life modification factors", "a1 (reliability), aISO (lubrication, contamination, fatigue limit)",
               f"R = {v['reliability']} %", f"a1 = {g(a1)}, aISO = {g(aiso)}", ref="ISO 281:2007 Table 12, §9")
        Lnm = a1 * aiso * L10
        w.step("Modified rating life", "Lnm = a1·aISO·L10", f"{g(a1)} × {g(aiso)} × {g(L10)}", Lnm, "million rev",
               ref="ISO 281:2007 Eq. (2)")
        Lnmh = Lnm * 1e6 / (60 * n)
        w.step("Modified rating life in hours", "Lnmh = 10⁶·Lnm / (60·n)", "", Lnmh, "h")
        w.out("L10", "Basic rating life L10", L10, "megarev")
        w.out("L10h", "Basic rating life L10h", L10h, "time", primary=True)
        w.out("Lnm", "Modified life Lnm", Lnm, "megarev")
        w.out("Lnmh", "Modified life Lnmh", Lnmh, "time", primary=True)
        if v.get("target_h"):
            w.check("Modified life meets the target", Lnmh >= v["target_h"],
                    f"Lnmh = {g(Lnmh)} h vs target {g(v['target_h'])} h", Lnmh / v["target_h"])
        if v.get("C0") and P > v["C0"] * 0.5:
            w.warnings.append("Equivalent load exceeds half the static rating C0: check static safety s0 = C0/P0.")
    if v.get("target_h"):
        LD = v["target_h"] * 60 * n / 1e6
        a1 = std.BEARING_A1[v["reliability"]]
        Creq = P * (LD / (a1 * v["aiso"])) ** (1 / p_exp)
        w.step("Required design life", "LD = 60·n·Lh / 10⁶", f"60 × {g(n)} × {g(v['target_h'])} / 10⁶", LD,
               "million rev")
        w.step("Required dynamic rating", "Creq = P·(LD / (a1·aISO))^(1/p)", f"{g(P)} × ({g(LD)} / "
               f"({g(a1)} × {g(v['aiso'])}))^(1/{g(p_exp)})", Creq, "N", ref="ISO 281 rearranged; Shigley Eq. (11-3)")
        w.out("C_req", "Required dynamic rating C", Creq, "force", primary=True)
    if not v.get("C") and not v.get("target_h"):
        raise InputError("Enter the bearing's dynamic rating C, a target life, or both")
    w.notes.append("C, X, Y and aISO come from the bearing manufacturer's catalogue (aISO per ISO 281 §9 needs "
                   "lubricant viscosity, contamination and fatigue load limit). Rating life is a statistical "
                   "fatigue life, not a guaranteed life.")
    return w


register(Calculator(
    id="bearing_life", name="Rolling bearing life (ISO 281)", category="Bearings & springs",
    summary="Basic rating life L10 and modified life Lnm = a1·aISO·L10 of a ball or roller bearing, in "
            "revolutions and hours, or the dynamic rating needed for a target life.",
    inputs=[
        Param("type", "Bearing type", "enum", "ball", group="Bearing",
              options=[{"value": "ball", "label": "Ball (p = 3)"}, {"value": "roller", "label": "Roller (p = 10/3)"}]),
        Param("C", "Basic dynamic load rating C", "force", None, unit="kN", min=0, exclusive_min=True,
              group="Bearing", optional=True, help="From the manufacturer's catalogue."),
        Param("C0", "Static load rating C0", "force", None, unit="kN", min=0, exclusive_min=True, group="Bearing",
              optional=True),
        Param("load_mode", "Load", "enum", "p", group="Load",
              options=[{"value": "p", "label": "Equivalent load P"}, {"value": "xy", "label": "From Fr, Fa, X, Y"}]),
        Param("P", "Equivalent dynamic load P", "force", 2000.0, unit="kN", min=0, exclusive_min=True, group="Load",
              show_if={"load_mode": ["p"]}),
        Param("Fr", "Radial load Fr", "force", 2000.0, min=0, group="Load", show_if={"load_mode": ["xy"]}),
        Param("Fa", "Axial load Fa", "force", 0.0, min=0, group="Load", show_if={"load_mode": ["xy"]}),
        Param("X", "Radial factor X", "ratio", 1.0, min=0, group="Load", show_if={"load_mode": ["xy"]}),
        Param("Y", "Axial factor Y", "ratio", 0.0, min=0, group="Load", show_if={"load_mode": ["xy"]}),
        Param("af", "Application factor af", "ratio", 1.0, min=1, max=3, group="Load",
              help="Load-application factor (Shigley Table 11-5): 1.0–1.1 precision gearing, 1.2–1.3 "
                   "commercial gearing, 1.0–1.2 rotating machinery without impact."),
        Param("n", "Speed n", "speed", 1500.0, min=0, exclusive_min=True, group="Operation"),
        Param("reliability", "Reliability", "enum", "90", group="Operation",
              options=[{"value": k, "label": f"{k} %"} for k in std.BEARING_A1]),
        Param("aiso", "Life modification factor aISO", "ratio", 1.0, min=0.1, max=50, group="Operation",
              help="1 = not considered. Compute per ISO 281 §9 / manufacturer's method."),
        Param("target_h", "Target life", "time", 20000.0, min=0, exclusive_min=True, group="Operation", optional=True),
    ],
    func=_bearing,
    references=["ISO 281:2007 Rolling bearings — Dynamic load ratings and rating life, Eqs. (1), (2), Table 12",
                f"{SHIGLEY_REF}, §11-3, §11-4 Eq. (11-3), Table 11-5"],
    assumptions=["Constant load and speed (use a cubic-mean equivalent for duty cycles)", ("Standard bearing "
                 "steel and conventional operating conditions per ISO 281")],
    verified_against=["Shigley 10th ed. Prob. 11-8 solution: FD = 2 kN, LD = 10⁹ rev → C10 = 20 kN",
                      "Shigley 10th ed. Prob. 11-9 solution: 800 lbf, 12 000 h, 350 rev/min → C10 = 5050 lbf",
                      "Shigley 10th ed. Prob. 11-10 solution: 4 kN, 8000 h, 500 rev/min → C10 = 24.9 kN"],
    keywords=["bearing", "l10", "iso 281", "ball bearing", "roller", "life", "skf"],
    prefill=["Bore diameter from a recognised bearing seat (for catalogue lookup)"],
))


# ----------------------------------------------------------------------------- helical compression spring
END_TYPES = {
    "plain": ("Plain", lambda nt: nt, lambda d, nt: d * (nt + 1)),
    "plain_ground": ("Plain and ground", lambda nt: nt - 1, lambda d, nt: d * nt),
    "squared": ("Squared (closed)", lambda nt: nt - 2, lambda d, nt: d * (nt + 1)),
    "squared_ground": ("Squared and ground", lambda nt: nt - 2, lambda d, nt: d * nt),
}
ALPHA = {"0.5": "Both ends on flat parallel surfaces (fixed)", "0.707": "One end fixed, one end pivoted",
         "1": "Both ends pivoted", "2": "One end clamped, other end free"}


def _spring(v: dict[str, Any]) -> Work:
    w = Work()
    d, OD, Nt, G = v["d"], v["OD"], v["Nt"], v["G"]
    D = OD - d
    w.step("Mean coil diameter", "D = OD − d", f"{g(OD)} − {g(d)}", D, "mm")
    if D <= d:
        raise InputError("Outside diameter must exceed twice the wire diameter")
    C = D / d
    w.step("Spring index", "C = D / d", f"{g(D)} / {g(d)}", C, ref="Shigley Eq. (10-1)")
    name, na_f, ls_f = END_TYPES[v["ends"]]
    Na = na_f(Nt)
    if Na <= 0:
        raise InputError("Too few coils for this end type")
    Ls = ls_f(d, Nt)
    w.step("Active coils", f"Na ({name})", f"Nt = {g(Nt)}", Na, ref="Shigley Table 10-1")
    w.step("Solid length", f"Ls ({name})", "", Ls, "mm", ref="Shigley Table 10-1")
    k = d ** 4 * G / (8 * D ** 3 * Na)
    w.step("Spring rate", "k = d⁴·G / (8·D³·Na)", f"{g(d)}⁴ × {g(G)} / (8 × {g(D)}³ × {g(Na)})", k, "N/mm",
           ref="Shigley Eq. (10-9)")
    KB = (4 * C + 2) / (4 * C - 3)
    w.step("Bergsträsser factor", "KB = (4C + 2) / (4C − 3)", f"(4 × {g(C)} + 2) / (4 × {g(C)} − 3)", KB,
           ref="Shigley Eq. (10-5)")
    w.out("k", "Spring rate k", k, "stiffness", primary=True)
    w.out("C", "Spring index C", C)
    w.out("Na", "Active coils Na", Na, "count")
    w.out("Ls", "Solid length Ls", Ls, "length")
    if C < 4 or C > 12:
        w.warnings.append(f"Spring index C = {g(C)} is outside the preferred 4–12 range (Shigley §10-5).")
    if v["wire"] == "custom":
        Sut = v["Sut"]
        if not Sut:
            raise InputError("Enter the wire tensile strength Sut")
        ssy_f = v["ssy_fraction"]
        w.step("Wire tensile strength (given)", "Sut", "", Sut, "MPa")
    else:
        mat = std.SPRING_WIRE[v["wire"]]
        lo, hi = mat["d_range"]
        if not lo <= d <= hi:
            w.warnings.append(f"d = {g(d)} mm is outside the {mat['name']} range {lo}–{hi} mm of Table 10-4.")
        Sut = mat["A"] / d ** mat["m"]
        ssy_f = mat["ssy"]
        w.step("Wire tensile strength", "Sut = A / d^m", f"{g(mat['A'])} / {g(d)}^{g(mat['m'])} ({mat['name']})", Sut,
               "MPa", ref="Shigley Eq. (10-14), Table 10-4")
    Ssy = ssy_f * Sut
    w.step("Torsional yield strength", "Ssy = f·Sut", f"{g(ssy_f)} × {g(Sut)}", Ssy, "MPa", ref="Shigley Table 10-6")
    Fs = PI * d ** 3 * Ssy / (8 * KB * D)
    w.step("Load at torsional yield", "Fs = π·d³·Ssy / (8·KB·D)", f"π × {g(d)}³ × {g(Ssy)} / (8 × {g(KB)} × {g(D)})",
           Fs, "N", ref="Shigley Eq. (10-7)")
    L0_set = Fs / k + Ls
    w.step("Free length that can close solid without set", "L0 = Fs/k + Ls", f"{g(Fs)} / {g(k)} + {g(Ls)}", L0_set,
           "mm")
    w.out("Sut", "Wire tensile strength Sut", Sut, "stress")
    w.out("Ssy", "Torsional yield Ssy", Ssy, "stress")
    w.out("Fs", "Load at torsional yield", Fs, "force", primary=True)
    w.out("L0_no_set", "Max free length closing solid without set", L0_set, "length")
    alpha = float(v["alpha"])
    L0cr = 2.63 * D / alpha
    w.step("Critical free length (steel, buckling)", "L0,cr = 2.63·D / α", f"2.63 × {g(D)} / {g(alpha)}", L0cr, "mm",
           ref="Shigley Eq. (10-13), Table 10-2")
    w.out("L0_cr", "Critical free length for buckling", L0cr, "length")
    sf_req, sf_src = v["sf_required"], v["sf_source"]
    if v.get("L0"):
        L0 = v["L0"]
        if L0 <= Ls:
            raise InputError("Free length must exceed the solid length")
        ys = L0 - Ls
        Fsol = k * ys
        tau_s = KB * 8 * Fsol * D / (PI * d ** 3)
        w.step("Force at solid", "F = k·(L0 − Ls)", f"{g(k)} × ({g(L0)} − {g(Ls)})", Fsol, "N")
        w.step("Stress at solid", "τs = KB·8FD / (πd³)", "", tau_s, "MPa", ref="Shigley Eq. (10-7)")
        ns = Ssy / tau_s
        w.step("Factor at solid", "ns = Ssy / τs", f"{g(Ssy)} / {g(tau_s)}", ns)
        w.out("n_solid", "Achieved factor at solid", ns, primary=True)
        w.sf_check("Torsional yield when closed solid", ns, sf_req, sf_src, "ns = Ssy / τs")
        w.check("No buckling (free length below critical)", L0 < L0cr, f"L0 = {g(L0)} mm vs L0,cr = {g(L0cr)} mm")
    if v.get("F"):
        F = v["F"]
        tau = KB * 8 * F * D / (PI * d ** 3)
        w.step("Deflection at working load", "y = F / k", f"{g(F)} / {g(k)}", F / k, "mm")
        w.step("Stress at working load", "τ = KB·8FD / (πd³)", "", tau, "MPa")
        n = Ssy / tau
        w.out("y_work", "Deflection at working load", F / k, "length")
        w.out("n_work", "Achieved factor at working load", n)
        w.sf_check("Torsional yield at working load", n, sf_req, sf_src, "n = Ssy / τ")
    w.notes.append("Static design only. Fatigue of springs needs the load range and Zimmerli/Goodman data "
                   "(Shigley §10-9).")
    return w


register(Calculator(
    id="compression_spring", name="Helical compression spring", category="Bearings & springs",
    summary="Rate, solid length, stress correction, load at yield, free-length limits and buckling of a round-wire "
            "helical compression spring (static).",
    inputs=[
        Param("d", "Wire diameter d", "length", 2.5, min=0, exclusive_min=True, group="Geometry"),
        Param("OD", "Outside diameter OD", "length", 31.0, min=0, exclusive_min=True, group="Geometry"),
        Param("Nt", "Total coils Nt", "count", 14, min=1, group="Geometry"),
        Param("ends", "End type", "enum", "squared_ground", group="Geometry",
              options=[{"value": k, "label": e[0]} for k, e in END_TYPES.items()]),
        Param("L0", "Free length L0", "length", None, min=0, exclusive_min=True, group="Geometry", optional=True),
        Param("wire", "Wire material", "enum", "A228", group="Material",
              options=[{"value": k, "label": m["name"]} for k, m in std.SPRING_WIRE.items()] +
              [{"value": "custom", "label": "Custom (enter Sut)"}]),
        Param("Sut", "Wire tensile strength Sut", "stress", None, min=0, exclusive_min=True, group="Material",
              optional=True, show_if={"wire": ["custom"]}),
        Param("ssy_fraction", "Ssy / Sut", "ratio", 0.45, min=0.2, max=0.7, group="Material",
              show_if={"wire": ["custom"]}),
        Param("G", "Shear modulus G", "stress", 81000.0, unit="GPa", min=0, exclusive_min=True, group="Material",
              help="Shigley Table 10-5: music wire ≈ 81 GPa, hard-drawn ≈ 80 GPa, oil-tempered / Cr-V / Cr-Si "
                   "≈ 77.2 GPa, stainless ≈ 69 GPa."),
        Param("alpha", "End condition for buckling", "enum", "0.5", group="Stability",
              options=[{"value": k, "label": f"α = {k}: {t}"} for k, t in ALPHA.items()]),
        Param("F", "Working load", "force", None, min=0, exclusive_min=True, group="Load", optional=True),
    ],
    func=_spring, safety_factor=True,
    references=[(f"{SHIGLEY_REF}, §10-2 – §10-8: Eqs. (10-1), (10-5), (10-7), (10-9), (10-13), (10-14); "
                "Tables 10-1, 10-2, 10-4, 10-5, 10-6")],
    assumptions=["Round wire, constant pitch, static load", "Set not removed (Ssy fractions of Table 10-6)",
                 "Buckling criterion for steel springs"],
    verified_against=[("Shigley 11th ed. Prob. 10-3 solution (music wire 2.5 mm, OD 31 mm, 14 coils, plain-ground): "
                      "k = 1.314 N/mm, Sut = 1936 MPa, KB = 1.117, Fs = 167.9 N, L0 = 162.8 mm, L0,cr = 149.9 mm")],
    keywords=["spring", "coil", "compression spring", "spring rate", "music wire"],
))


# ----------------------------------------------------------------------------- tolerance stack-up (ENG-011)
def stack(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """1D stack: each row nominal +tol/−tol, direction ±1 and sensitivity. Returns worst-case and RSS results."""
    nominal = mean = wc = var = 0.0
    contrib = []
    for r in rows:
        a = r["sens"] * (1 if r["dir"] == "+" else -1)
        up, lo = r["plus"], r["minus"]          # +up / −lo (both ≥ 0)
        mid = r["nominal"] + (up - lo) / 2      # mean of the tolerance band
        half = (up + lo) / 2
        nominal += a * r["nominal"]
        mean += a * mid
        wc += abs(a) * half
        var += (a * half) ** 2
        contrib.append({"name": r["name"], "half_tol": half, "coeff": a, "wc": abs(a) * half, "var": (a * half) ** 2})
    rss = math.sqrt(var)
    for c in contrib:
        c["pct_wc"] = 100 * c["wc"] / wc if wc else 0.0
        c["pct_rss"] = 100 * c["var"] / var if var else 0.0
    return {"nominal": nominal, "mean": mean, "wc": wc, "rss": rss, "contrib": contrib}


def _stack(v: dict[str, Any]) -> Work:
    w = Work()
    rows = []
    for r in v["rows"]:
        if r["plus"] < 0 or r["minus"] < 0:
            raise InputError("Tolerances are entered as positive magnitudes (+upper, −lower)")
        rows.append({**r, "dir": r["dir"], "sens": r["sens"]})
    s = stack(rows)
    terms = " ".join(f"{'+' if r['dir'] == '+' else '−'} {g(r['sens']) + '×' if r['sens'] != 1 else ''}{g(r['nominal'])}"
                     for r in rows)
    w.step("Nominal result", "X = Σ aᵢ·xᵢ", terms.lstrip("+ "), s["nominal"], "mm", ref="Shigley §1-14")
    w.step("Mean result (centred tolerance bands)", "X̄ = Σ aᵢ·x̄ᵢ", "", s["mean"], "mm")
    w.step("Worst-case tolerance", "t_wc = Σ |aᵢ|·tᵢ", " + ".join(g(c["wc"]) for c in s["contrib"]), s["wc"], "mm",
           ref="Shigley Eq. (1-11)")
    w.step("Statistical tolerance (RSS)", "t_rss = √(Σ (aᵢ·tᵢ)²)", " + ".join(f"{g(c['half_tol'])}²" for c in s["contrib"]),
           s["rss"], "mm", ref="Shigley Eq. (1-12)")
    w.out("nominal", "Nominal", s["nominal"], "length")
    w.out("mean", "Mean", s["mean"], "length", primary=True)
    w.out("wc", "Worst-case ± tolerance", s["wc"], "length", primary=True)
    w.out("wc_min", "Worst-case minimum", s["mean"] - s["wc"], "length")
    w.out("wc_max", "Worst-case maximum", s["mean"] + s["wc"], "length")
    w.out("rss", "RSS ± tolerance", s["rss"], "length", primary=True)
    w.out("rss_min", "RSS minimum", s["mean"] - s["rss"], "length")
    w.out("rss_max", "RSS maximum", s["mean"] + s["rss"], "length")
    for c in s["contrib"]:
        w.step(f"Contribution: {c['name'] or 'dimension'}", "share of t_wc / share of variance", "",
               f"{g(c['pct_wc'], 3)} % / {g(c['pct_rss'], 3)} %")
    lo, hi = v.get("spec_min"), v.get("spec_max")
    if lo is not None:
        w.check("Worst case ≥ required minimum", s["mean"] - s["wc"] >= lo - 1e-12,
                f"{g(s['mean'] - s['wc'])} vs {g(lo)} mm", s["mean"] - s["wc"])
        w.check("RSS ≥ required minimum", s["mean"] - s["rss"] >= lo - 1e-12,
                f"{g(s['mean'] - s['rss'])} vs {g(lo)} mm", s["mean"] - s["rss"])
    if hi is not None:
        w.check("Worst case ≤ allowed maximum", s["mean"] + s["wc"] <= hi + 1e-12,
                f"{g(s['mean'] + s['wc'])} vs {g(hi)} mm", s["mean"] + s["wc"])
        w.check("RSS ≤ allowed maximum", s["mean"] + s["rss"] <= hi + 1e-12,
                f"{g(s['mean'] + s['rss'])} vs {g(hi)} mm", s["mean"] + s["rss"])
    w.notes.append("RSS assumes independent, centred, normally distributed dimensions with the tolerance at the "
                   "same sigma level for every part; it is not appropriate for few-part stacks or uncontrolled "
                   "processes. Worst case is guaranteed for in-tolerance parts.")
    return w


STACK_COLUMNS = [Column("name", "Dimension", "text", default=""),
                 Column("dir", "Direction", "enum", default="+",
                        options=[{"value": "+", "label": "+ (adds)"}, {"value": "-", "label": "− (subtracts)"}]),
                 Column("nominal", "Nominal", "length", "mm", 10.0),
                 Column("plus", "+ Tol", "length", "mm", 0.1, min=0),
                 Column("minus", "− Tol", "length", "mm", 0.1, min=0),
                 Column("sens", "Sensitivity", "ratio", "", 1.0)]

register(Calculator(
    id="tolerance_stack", name="1D tolerance stack-up", category="Tolerances & fits",
    summary="Linear dimension chain: nominal, mean, worst-case and RSS (statistical) limits with each "
            "dimension's contribution, checked against a required gap or interference.",
    inputs=[
        Param("rows", "Dimension chain", "table",
              [{"name": "a", "dir": "+", "nominal": 50.0, "plus": 0.1, "minus": 0.1, "sens": 1.0},
               {"name": "b", "dir": "-", "nominal": 49.8, "plus": 0.05, "minus": 0.05, "sens": 1.0}],
              columns=STACK_COLUMNS, group="Chain"),
        Param("spec_min", "Required minimum (e.g. gap ≥)", "length", None, group="Requirement", optional=True),
        Param("spec_max", "Allowed maximum", "length", None, group="Requirement", optional=True),
    ],
    func=_stack,
    references=[f"{SHIGLEY_REF}, §1-14 'Dimensions and tolerances', Eqs. (1-11), (1-12)",
                "ASME Y14.5-2018 (dimensioning conventions)"],
    assumptions=["1D chain, linear sensitivities", ("RSS: independent normal distributions, tolerances at equal "
                 "sigma levels")],
    verified_against=["Shigley 10th ed. Prob. 1-21 solution: w = 0.020 ± 0.018 in (worst case)",
                      "Shigley 10th ed. Prob. 1-24 solution (sensitivity 2): Do = 4.012 ± 0.036 in",
                      "Independent hand derivation of the RSS values"],
    keywords=["tolerance", "stack", "rss", "worst case", "gap", "clearance", "fit"],
))
