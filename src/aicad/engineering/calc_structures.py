"""Structural calculators: section properties, beams (Euler-Bernoulli, superposition), pin/dowel shear, interference
fits (Lamé thick-walled cylinders)."""

from __future__ import annotations

import math
from typing import Any

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

SECTION_OPTIONS = [{"value": "rect", "label": "Rectangle b × h"}, {"value": "round", "label": "Solid round Ø d"},
                   {"value": "tube", "label": "Round tube Ø D × wall t"},
                   {"value": "custom", "label": "Custom (I and c)"}]


def section_params(group: str = "Section") -> list[Param]:
    return [
        Param("section", "Section", "enum", "rect", options=SECTION_OPTIONS, group=group),
        Param("b", "Width b", "length", 20.0, min=0, exclusive_min=True, group=group, show_if={"section": ["rect"]},
              help="Dimension parallel to the neutral axis.", prefill="model"),
        Param("h", "Depth h", "length", 10.0, min=0, exclusive_min=True, group=group, show_if={"section": ["rect"]},
              help="Dimension in the plane of bending (load direction).", prefill="model"),
        Param("d", "Diameter d", "length", 20.0, min=0, exclusive_min=True, group=group,
              show_if={"section": ["round"]}, prefill="model"),
        Param("D", "Outer diameter D", "length", 30.0, min=0, exclusive_min=True, group=group,
              show_if={"section": ["tube"]}),
        Param("t", "Wall thickness t", "length", 3.0, min=0, exclusive_min=True, group=group,
              show_if={"section": ["tube"]}),
        Param("I_custom", "Second moment of area I", "inertia_area", 1.0e5, min=0, exclusive_min=True, group=group,
              show_if={"section": ["custom"]}),
        Param("c_custom", "Extreme-fibre distance c", "length", 10.0, min=0, exclusive_min=True, group=group,
              show_if={"section": ["custom"]}, help="Distance from the neutral axis to the most stressed fibre."),
    ]


def section_properties(v: dict[str, Any], w: Work) -> dict[str, float]:
    s = v["section"]
    if s == "rect":
        b, h = v["b"], v["h"]
        A = w.step("Area", "A = b·h", f"{g(b)} × {g(h)}", b * h, "mm²")
        I = w.step("Second moment of area", "I = b·h³/12", f"{g(b)} × {g(h)}³ / 12", b * h ** 3 / 12, "mm⁴")
        c = h / 2
    elif s == "round":
        d = v["d"]
        A = w.step("Area", "A = π·d²/4", f"π × {g(d)}² / 4", PI * d ** 2 / 4, "mm²")
        I = w.step("Second moment of area", "I = π·d⁴/64", f"π × {g(d)}⁴ / 64", PI * d ** 4 / 64, "mm⁴")
        c = d / 2
    elif s == "tube":
        D, t = v["D"], v["t"]
        if 2 * t >= D:
            raise InputError("Wall thickness must be less than half the outer diameter")
        di = D - 2 * t
        A = w.step("Area", "A = π·(D² − dᵢ²)/4, dᵢ = D − 2t", f"π × ({g(D)}² − {g(di)}²) / 4",
                   PI * (D ** 2 - di ** 2) / 4, "mm²")
        I = w.step("Second moment of area", "I = π·(D⁴ − dᵢ⁴)/64", f"π × ({g(D)}⁴ − {g(di)}⁴) / 64",
                   PI * (D ** 4 - di ** 4) / 64, "mm⁴")
        c = D / 2
    else:
        I, c, A = v["I_custom"], v["c_custom"], None
        w.step("Second moment of area (given)", "I", "", I, "mm⁴")
    Z = w.step("Section modulus", "Z = I / c", f"{g(I)} / {g(c)}", I / c, "mm³")
    return {"A": A, "I": I, "c": c, "Z": Z}  # type: ignore[dict-item]


# ----------------------------------------------------------------------------- section properties
def _section(v: dict[str, Any]) -> Work:
    w = Work()
    p = section_properties(v, w)
    if p["A"] is not None:
        w.out("A", "Area A", p["A"], "area")
    w.out("I", "Second moment of area I", p["I"], "inertia_area", primary=True)
    w.out("c", "Extreme-fibre distance c", p["c"], "length")
    w.out("Z", "Elastic section modulus Z", p["Z"], "section_modulus", primary=True)
    if v["section"] in ("round", "tube"):
        J = 2 * p["I"]
        w.step("Polar second moment", "J = 2·I (circular sections)", f"2 × {g(p['I'])}", J, "mm⁴")
        w.out("J", "Polar second moment J", J, "inertia_area")
    return w


register(Calculator(
    id="section_properties", name="Section properties", category="Beams & sections",
    summary="Area, second moment of area, section modulus (and polar moment for round sections) from dimensions.",
    inputs=section_params(), func=_section,
    references=[f"{SHIGLEY_REF}, Table A-18 (properties of geometric shapes)",
                "Roark's Formulas for Stress and Strain, 8th ed., Table A.1"],
    assumptions=["Bending about the centroidal axis parallel to b (rectangle)", ("Thin features such as fillets "
                 "and holes in the section are ignored")],
    verified_against=[("Independent check: area and second moment of the same section computed by the CAD kernel "
                      "(OCCT surface properties)")],
    keywords=["inertia", "second moment", "section modulus", "area"],
    prefill=["Rectangle from the part's bounding box"],
))


# ----------------------------------------------------------------------------- beams
SUPPORTS = [{"value": "cantilever", "label": "Cantilever (fixed at x = 0)"},
            {"value": "simply_supported", "label": "Simply supported (pin at 0, roller at L)"}]


def beam_response(support: str, L: float, EI: float, loads: list[tuple[float, float]], w_udl: float,
                  x: float) -> tuple[float, float, float]:
    """(deflection y, bending moment M, shear V) at x by superposition of Shigley Table A-9 cases.
    Downward loads positive; deflection returned positive downward. Units N, mm, N·mm."""
    y = M = V = 0.0
    if support == "cantilever":
        for P, a in loads:                       # Table A-9 beams 1/2 (load at a from the wall)
            if x <= a:
                y += P * x ** 2 * (3 * a - x) / (6 * EI)
                M += -P * (a - x)
                V += P
            else:
                y += P * a ** 2 * (3 * x - a) / (6 * EI)
        if w_udl:                                # Table A-9 beam 3
            y += w_udl * x ** 2 * (6 * L ** 2 - 4 * L * x + x ** 2) / (24 * EI)
            M += -w_udl * (L - x) ** 2 / 2
            V += w_udl * (L - x)
    else:
        for P, a in loads:                       # Table A-9 beam 6
            b = L - a
            if x <= a:
                y += P * b * x * (L ** 2 - b ** 2 - x ** 2) / (6 * EI * L)
                M += P * b * x / L
                V += P * b / L
            else:
                y += P * a * (L - x) * (2 * L * x - x ** 2 - a ** 2) / (6 * EI * L)
                M += P * a * (L - x) / L
                V += -P * a / L
        if w_udl:                                # Table A-9 beam 7
            y += w_udl * x * (L ** 3 - 2 * L * x ** 2 + x ** 3) / (24 * EI)
            M += w_udl * x * (L - x) / 2
            V += w_udl * (L / 2 - x)
    return y, M, V


def _beam(v: dict[str, Any]) -> Work:
    w = Work()
    L, E = v["L"], v["E"]
    sec = section_properties(v, w)
    I, c = sec["I"], sec["c"]
    loads = [(r["P"], r["a"]) for r in (v["loads"] or [])]
    wq = v["w"] or 0.0
    for P, a in loads:
        if a > L + 1e-9:
            raise InputError(f"A point load is placed at {g(a)} mm, beyond the span L = {g(L)} mm")
    if not loads and not wq:
        raise InputError("Add at least one point load or a distributed load")
    EI = E * I
    w.step("Flexural rigidity", "EI = E·I", f"{g(E)} MPa × {g(I)} mm⁴", EI, "N·mm²")
    xs = sorted({*(i * L / 2000 for i in range(2001)), *(a for _, a in loads)})
    resp = [(x, *beam_response(v["support"], L, EI, loads, wq, x)) for x in xs]
    xd, ymax, _, _ = max(resp, key=lambda r: abs(r[1]))
    xm, _, Mmax, _ = max(resp, key=lambda r: abs(r[2]))
    Vmax = max(abs(r[3]) for r in resp)
    if v["support"] == "cantilever":
        R = sum(P for P, _ in loads) + wq * L
        M0 = sum(P * a for P, a in loads) + wq * L ** 2 / 2
        w.step("Wall reaction", "R = ΣP + w·L", f"{' + '.join(g(P) for P, _ in loads) or '0'} + {g(wq)} × {g(L)}",
               R, "N")
        w.step("Wall moment", "M₀ = ΣP·a + w·L²/2",
               f"{' + '.join(f'{g(P)}×{g(a)}' for P, a in loads) or '0'} + {g(wq)} × {g(L)}² / 2", M0, "N·mm",
               ref="Statics")
        tip = beam_response("cantilever", L, EI, loads, wq, L)[0]
        w.step("Tip deflection", "y = Σ P·a²(3L − a)/(6EI) + w·L⁴/(8EI)", "superposition of Table A-9 beams 2 and 3",
               tip, "mm", ref="Shigley Table A-9, beams 1 to 3")
        w.out("R1", "Wall reaction", R, "force")
    else:
        R1 = sum(P * (L - a) / L for P, a in loads) + wq * L / 2
        R2 = sum(P for P, _ in loads) + wq * L - R1
        w.step("Left reaction", "R₁ = Σ P·(L − a)/L + w·L/2", "", R1, "N", ref="Statics")
        w.step("Right reaction", "R₂ = ΣP + w·L − R₁", "", R2, "N")
        w.out("R1", "Left reaction R₁", R1, "force")
        w.out("R2", "Right reaction R₂", R2, "force")
    w.step("Maximum bending moment", "|M|max over the span", f"at x = {g(xm)} mm", abs(Mmax), "N·mm",
           ref="Shigley Table A-9")
    sigma = abs(Mmax) * c / I
    w.step("Maximum bending stress", "σ = M·c / I", f"{g(abs(Mmax))} × {g(c)} / {g(I)}", sigma, "MPa",
           ref="Shigley Eq. (3-24)")
    w.step("Maximum deflection", "|y|max over the span (superposition)", f"at x = {g(xd)} mm", abs(ymax), "mm",
           ref="Shigley Table A-9, beams 1 to 3, 6, 7")
    w.out("y_max", "Maximum deflection", abs(ymax), "length", primary=True)
    w.out("x_ymax", "Position of maximum deflection", xd, "length")
    w.out("M_max", "Maximum bending moment", abs(Mmax), "moment")
    w.out("V_max", "Maximum shear force", Vmax, "force")
    w.out("sigma_max", "Maximum bending stress", sigma, "stress", primary=True)
    if v.get("x_query") is not None:
        xq = v["x_query"]
        if xq > L + 1e-9:
            raise InputError("Query position is beyond the span")
        yq, Mq, _ = beam_response(v["support"], L, EI, loads, wq, xq)
        w.step("Deflection at query point", "y(x) by superposition", f"x = {g(xq)} mm", yq, "mm")
        w.out("y_at_x", "Deflection at query point", yq, "length")
        w.out("M_at_x", "Bending moment at query point", abs(Mq), "moment")
    if v.get("Sy"):
        n = v["Sy"] / sigma if sigma > 0 else math.inf
        w.step("Factor of safety against yield", "n = Sy / σ", f"{g(v['Sy'])} / {g(sigma)}", n)
        w.out("n_yield", "Achieved factor (yield)", n, primary=True)
        w.sf_check("Bending stress vs yield", n, v["sf_required"], v["sf_source"], "n = Sy / σmax")
    if v.get("y_allow"):
        w.check("Deflection within allowable", abs(ymax) <= v["y_allow"],
                f"|y|max = {g(abs(ymax))} mm vs allowable {g(v['y_allow'])} mm", abs(ymax))
    if v["section"] == "rect" and L < 10 * v["h"]:
        w.warnings.append("Span is less than 10× the section depth: shear deflection is no longer negligible "
                          "(Euler-Bernoulli theory under-predicts deflection).")
    w.notes.append("Deflection and stress are for the uniform section given; holes, notches and fillets raise "
                   "local stress (apply Kt separately).")
    return w


LOAD_COLUMNS = [Column("P", "Load P", "force", "N", 100.0), Column("a", "Position a", "length", "mm", 100.0, min=0)]

register(Calculator(
    id="beam", name="Beam deflection and bending stress", category="Beams & sections",
    summary="Cantilever or simply supported beam with any number of point loads and a uniform load: reactions, "
            "maximum moment, bending stress and deflection, by superposition.",
    inputs=[
        Param("support", "Support", "enum", "cantilever", options=SUPPORTS, group="Beam"),
        Param("L", "Span L", "length", 200.0, min=0, exclusive_min=True, group="Beam", prefill="model"),
        Param("E", "Elastic modulus E", "stress", 207000.0, unit="GPa", min=0, exclusive_min=True, group="Material",
              prefill="material"),
        Param("Sy", "Yield strength Sy", "stress", None, min=0, exclusive_min=True, group="Material", optional=True,
              prefill="material", help="Leave empty to skip the stress check."),
        *section_params(),
        Param("loads", "Point loads", "table", [{"P": 100.0, "a": 200.0}], group="Loads",
              columns=LOAD_COLUMNS, help="Downward positive. a is measured from the left end (the wall for a "
                                         "cantilever)."),
        Param("w", "Uniform load w (full span)", "line_load", 0.0, min=0, group="Loads", optional=True),
        Param("x_query", "Report deflection at x", "length", None, min=0, group="Loads", optional=True),
        Param("y_allow", "Allowable deflection", "length", None, min=0, exclusive_min=True, group="Loads",
              optional=True),
    ],
    func=_beam, safety_factor=True,
    references=[f"{SHIGLEY_REF}, Table A-9 (beam deflections and slopes), Eq. (3-24)",
                "Roark's Formulas for Stress and Strain, 8th ed., Table 8.1"],
    assumptions=["Linear-elastic, small deflections (Euler-Bernoulli)", ("Prismatic beam, symmetric section, "
                 "loads in a plane of symmetry"), "Shear deformation neglected", ("Ideal supports (rigid wall, "
                 "frictionless pins)")],
    verified_against=[("Shigley 11th ed. Prob. 4-10 solution (cantilever, point + uniform load): y = 25.4 mm, "
                      "σ = 163 MPa"), ("Shigley 11th ed. Prob. 4-12 solution (simply supported, point + uniform "
                      "load): y = 0.0978 in at the load, 0.1027 in at midspan"),
                      "Independent check: numerical double integration of M/EI"],
    keywords=["deflection", "cantilever", "simply supported", "bending", "udl", "point load"],
    prefill=["Span and section from the bounding box", "E and Sy from the project material"],
))


# ----------------------------------------------------------------------------- pin and dowel shear
def _pin(v: dict[str, Any]) -> Work:
    w = Work()
    d, F, n, planes = v["d"], v["F"], int(v["n_pins"]), int(v["planes"])
    A = w.step("Pin cross-section", "A = π·d²/4", f"π × {g(d)}² / 4", PI * d ** 2 / 4, "mm²")
    As = w.step("Total shear area", "As = n · planes · A", f"{n} × {planes} × {g(A)}", n * planes * A, "mm²")
    tau = w.step("Average shear stress", "τ = F / As", f"{g(F)} / {g(As)}", F / As, "MPa",
                 ref="Shigley §8-12 (shear of bolts and pins)")
    w.out("tau", "Average shear stress τ", tau, "stress", primary=True)
    if v.get("Ssy"):
        Ssy = v["Ssy"]
        w.step("Shear yield strength (given)", "Ssy", "", Ssy, "MPa")
    else:
        Ssy = w.step("Shear yield strength", "Ssy = 0.577·Sy (distortion energy)", f"0.577 × {g(v['Sy'])}",
                     0.577 * v["Sy"], "MPa", ref="Shigley Eq. (5-21)")
    n_s = Ssy / tau
    w.step("Factor against shear yield", "n = Ssy / τ", f"{g(Ssy)} / {g(tau)}", n_s)
    w.out("n_shear", "Achieved factor (pin shear)", n_s, primary=True)
    w.sf_check("Pin shear", n_s, v["sf_required"], v["sf_source"], "n = Ssy / τ")
    if v.get("t"):
        Ab = w.step("Projected bearing area", "Ab = n · d · t", f"{n} × {g(d)} × {g(v['t'])}", n * d * v["t"], "mm²")
        sb = w.step("Bearing stress", "σb = F / Ab", f"{g(F)} / {g(Ab)}", F / Ab, "MPa", ref="Shigley §8-12")
        w.out("sigma_b", "Bearing stress σb", sb, "stress")
        nb_pin = v["Sy"] / sb
        w.step("Factor, bearing on pin", "n = Sy,pin / σb", f"{g(v['Sy'])} / {g(sb)}", nb_pin)
        w.out("n_bearing_pin", "Achieved factor (bearing on pin)", nb_pin)
        w.sf_check("Bearing on pin", nb_pin, v["sf_required"], v["sf_source"], "n = Sy,pin / σb")
        if v.get("Sy_member"):
            nb_m = v["Sy_member"] / sb
            w.step("Factor, bearing on member", "n = Sy,member / σb", f"{g(v['Sy_member'])} / {g(sb)}", nb_m)
            w.out("n_bearing_member", "Achieved factor (bearing on member)", nb_m)
            w.sf_check("Bearing on member", nb_m, v["sf_required"], v["sf_source"], "n = Sy,member / σb")
    w.notes.append("Average shear stress assumes the load shares equally between pins and shear planes; the peak "
                   "shear stress in a solid round pin is 4/3 of the average.")
    return w


register(Calculator(
    id="pin_shear", name="Pin and dowel shear", category="Fasteners & joints",
    summary="Shear stress in pins or dowels in single or double shear, with bearing stress on the pin and the "
            "member.",
    inputs=[
        Param("d", "Pin diameter d", "length", 6.0, min=0, exclusive_min=True, group="Pin", prefill="model"),
        Param("n_pins", "Number of pins", "count", 1, min=1, group="Pin", prefill="model"),
        Param("planes", "Shear planes per pin", "enum", "1",
              options=[{"value": "1", "label": "Single shear"}, {"value": "2", "label": "Double shear"}],
              group="Pin"),
        Param("F", "Total shear load F", "force", 1000.0, min=0, exclusive_min=True, group="Load"),
        Param("Sy", "Pin yield strength Sy", "stress", 640.0, min=0, exclusive_min=True, group="Material"),
        Param("Ssy", "Pin shear yield Ssy", "stress", None, min=0, exclusive_min=True, group="Material",
              optional=True, help="Leave empty to use Ssy = 0.577·Sy."),
        Param("t", "Bearing length t (member thickness)", "length", None, min=0, exclusive_min=True, group="Bearing",
              optional=True, prefill="model"),
        Param("Sy_member", "Member yield strength", "stress", None, min=0, exclusive_min=True, group="Bearing",
              optional=True, prefill="material"),
    ],
    func=_pin, safety_factor=True,
    references=[f"{SHIGLEY_REF}, §8-12 and Eq. (5-21)"],
    assumptions=["Equal load sharing between pins", "Average (not peak) shear stress", ("No bending of the pin "
                 "(close-fitting members)")],
    verified_against=[("Shigley 11th ed. Prob. 8-68 solution (two 5/16 in bolts in shear): τ = 32.6 kpsi, n = 2.30; "
                      "bearing n = 4.06 (bolt) and 1.31 (member)")],
    keywords=["dowel", "pin", "shear", "clevis", "bearing stress"],
    prefill=["Pin diameter and count from a recognised hole pattern", "Member thickness from the hole depth"],
))


# ----------------------------------------------------------------------------- interference fit (Lamé)
def _fit(v: dict[str, Any]) -> Work:
    w = Work()
    d, do, di, dd = v["d"], v["do"], v["di"] or 0.0, v["delta_d"]
    if do <= d:
        raise InputError("Hub outer diameter must be larger than the interface diameter")
    if di >= d:
        raise InputError("Shaft bore must be smaller than the interface diameter")
    R, ro, ri = d / 2, do / 2, di / 2
    delta = w.step("Radial interference", "δ = δd / 2", f"{g(dd)} / 2", dd / 2, "mm")
    Eo, nuo, Ei, nui = v["Eo"], v["nuo"], v["Ei"], v["nui"]
    term_o = (R / Eo) * ((ro ** 2 + R ** 2) / (ro ** 2 - R ** 2) + nuo)
    term_i = (R / Ei) * ((R ** 2 + ri ** 2) / (R ** 2 - ri ** 2) - nui)
    p = delta / (term_o + term_i)
    w.step("Interface pressure", "p = δ / [ (R/Eo)·((ro²+R²)/(ro²−R²) + νo) + (R/Ei)·((R²+ri²)/(R²−ri²) − νi) ]",
           f"{g(delta)} / ({g(term_o)} + {g(term_i)})", p, "MPa", ref="Shigley Eq. (3-56)")
    st_hub = p * (ro ** 2 + R ** 2) / (ro ** 2 - R ** 2)
    st_sh = -p * (R ** 2 + ri ** 2) / (R ** 2 - ri ** 2)
    w.step("Hub tangential stress at bore", "σt,o = p·(ro² + R²)/(ro² − R²)", f"{g(p)} × ({g(ro)}² + {g(R)}²) / "
           f"({g(ro)}² − {g(R)}²)", st_hub, "MPa", ref="Shigley Eq. (3-59)")
    w.step("Shaft tangential stress at interface", "σt,i = −p·(R² + ri²)/(R² − ri²)", "", st_sh, "MPa",
           ref="Shigley Eq. (3-58)")
    vm_hub = math.sqrt(st_hub ** 2 - st_hub * (-p) + p ** 2)
    w.step("Hub von Mises stress at bore", "σ' = √(σt² − σt·σr + σr²), σr = −p", "", vm_hub, "MPa",
           ref="Shigley Eq. (5-13)")
    vm_sh = math.sqrt(st_sh ** 2 - st_sh * (-p) + p ** 2)
    w.step("Shaft von Mises stress at interface", "σ' = √(σt² − σt·σr + σr²), σr = −p", "", vm_sh, "MPa")
    w.out("p", "Interface pressure p", p, "stress", primary=True)
    w.out("sigma_t_hub", "Hub tangential stress (bore)", st_hub, "stress", primary=True)
    w.out("sigma_t_shaft", "Shaft tangential stress (interface)", st_sh, "stress")
    w.out("vm_hub", "Hub von Mises stress (bore)", vm_hub, "stress")
    w.out("vm_shaft", "Shaft von Mises stress", vm_sh, "stress")
    if v.get("L") and v.get("mu"):
        T = PI * v["mu"] * p * d ** 2 * v["L"] / 2
        Fa = PI * v["mu"] * p * d * v["L"]
        w.step("Torque capacity", "T = π·μ·p·d²·L / 2", f"π × {g(v['mu'])} × {g(p)} × {g(d)}² × {g(v['L'])} / 2",
               T, "N·mm")
        w.step("Axial force capacity", "F = π·μ·p·d·L", "", Fa, "N")
        w.out("T_cap", "Torque capacity (slip)", T, "moment")
        w.out("F_cap", "Axial force capacity (slip)", Fa, "force")
    if v.get("Sy_hub"):
        n = v["Sy_hub"] / vm_hub
        w.step("Hub factor against yield", "n = Sy,hub / σ'", f"{g(v['Sy_hub'])} / {g(vm_hub)}", n)
        w.out("n_hub", "Achieved factor (hub yield)", n, primary=True)
        w.sf_check("Hub yield at bore", n, v["sf_required"], v["sf_source"], "n = Sy,hub / σ'hub")
    if v.get("Sy_shaft"):
        n = v["Sy_shaft"] / vm_sh
        w.step("Shaft factor against yield", "n = Sy,shaft / σ'", f"{g(v['Sy_shaft'])} / {g(vm_sh)}", n)
        w.out("n_shaft", "Achieved factor (shaft yield)", n)
        w.sf_check("Shaft yield at interface", n, v["sf_required"], v["sf_source"], "n = Sy,shaft / σ'shaft")
    w.notes.append("Lamé solution for long cylinders; hub ends and short hubs raise the pressure near the edges. "
                   "Use the maximum and minimum interference of the tolerance classes for the limits.")
    return w


register(Calculator(
    id="interference_fit", name="Interference fit (press / shrink fit)", category="Shafts & fits",
    summary="Interface pressure, hub and shaft stresses and slip capacity of a press or shrink fit, from Lamé "
            "thick-walled cylinder theory.",
    inputs=[
        Param("d", "Interface diameter d", "length", 30.0, min=0, exclusive_min=True, group="Geometry",
              prefill="model"),
        Param("delta_d", "Diametral interference δd", "length", 0.03, min=0, exclusive_min=True, group="Geometry",
              help="Shaft diameter minus hub bore (use the limits of the fit's tolerance classes)."),
        Param("do", "Hub outer diameter", "length", 60.0, min=0, exclusive_min=True, group="Geometry",
              prefill="model"),
        Param("di", "Shaft bore (0 = solid)", "length", 0.0, min=0, group="Geometry"),
        Param("L", "Engagement length L", "length", None, min=0, exclusive_min=True, group="Geometry", optional=True),
        Param("Eo", "Hub modulus Eo", "stress", 207000.0, unit="GPa", min=0, exclusive_min=True, group="Hub"),
        Param("nuo", "Hub Poisson's ratio νo", "ratio", 0.292, min=0, max=0.5, group="Hub"),
        Param("Sy_hub", "Hub yield strength", "stress", None, min=0, exclusive_min=True, group="Hub", optional=True,
              prefill="material"),
        Param("Ei", "Shaft modulus Ei", "stress", 207000.0, unit="GPa", min=0, exclusive_min=True, group="Shaft"),
        Param("nui", "Shaft Poisson's ratio νi", "ratio", 0.292, min=0, max=0.5, group="Shaft"),
        Param("Sy_shaft", "Shaft yield strength", "stress", None, min=0, exclusive_min=True, group="Shaft",
              optional=True),
        Param("mu", "Friction coefficient μ", "ratio", None, min=0, max=1, group="Capacity", optional=True,
              help="Needed for the slip torque. Depends strongly on surfaces and assembly method; use a value "
                   "from test or your company standard."),
    ],
    func=_fit, safety_factor=True,
    references=[f"{SHIGLEY_REF}, §3-16 Eqs. (3-56) to (3-59) (press and shrink fits)",
                "Roark's Formulas for Stress and Strain, 8th ed., Table 13.5 (thick-walled cylinders)"],
    assumptions=["Long cylinders, plane stress, linear-elastic", "Uniform interference along the length",
                 "No surface roughness loss of interference (subtract smoothing allowance separately)"],
    verified_against=["Shigley 11th ed. Prob. 3-130 solution (same material): p = 8.33 kpsi, σt,o = 21.7 kpsi",
                      "Shigley 11th ed. Prob. 3-131 solution (steel in cast iron): p = 4599 psi, σt,o = 11 960 psi",
                      "Independent check: Lamé radial displacements close the interference"],
    keywords=["press fit", "shrink fit", "lame", "hub", "interference"],
    prefill=["Interface diameter from a recognised bore or boss"],
))
