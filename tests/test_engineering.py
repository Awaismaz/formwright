"""Engineering Advisor: calculators verified against published worked examples, unit safety, the ENG-012 wording
guard, geometry heuristics on the demo parts, and the API (entitlement, project link, sign-off invalidation).

Published examples are the end-of-chapter problem solutions of Budynas & Nisbett, *Shigley's Mechanical
Engineering Design* (10th ed. solutions for chapters 1, 7 and 11; 11th ed. solutions for chapters 3, 4, 8 and 10),
and the ISO 898-1 tabulated tensile stress areas. Each test cites the problem and matches the solution to the
precision it states (the solutions round intermediate values, so a tolerance of half a unit in the last stated digit,
or about 0.5 % where the solution rounds factors, is used and noted). Where no published example is cited, the test
is an independent hand derivation and says so.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_platform import _project_with_model, app_client, signup  # noqa: F401  (fixture re-export)
from trial_helpers import set_trial_ended

from aicad.engineering import REGISTRY, InputError, output, run, units, wording
from aicad.engineering import standards as std
from aicad.engineering.calc_structures import beam_response

SF = {"sf_required": 2.0, "sf_source": "Test: company standard ES-001 §4"}
PSI = 0.00689475729  # MPa
KSI = 6.89475729
IN = 25.4
DEMO = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo"


def q(v: float, u: str) -> dict[str, Any]:
    return {"value": v, "unit": u}


def out(cid: str, inputs: dict[str, Any]) -> dict[str, Any]:
    r = run(cid, inputs)
    return {o["key"]: o["value"] for o in r["outputs"]} | {"_r": r}


# ----------------------------------------------------------------------------- units
def test_units_convert_and_reject_wrong_dimensions() -> None:
    assert units.to_canonical("length", 1, "in") == pytest.approx(25.4)
    assert units.to_canonical("force", 1, "kip") == pytest.approx(4448.2216, rel=1e-6)
    assert units.to_canonical("stress", 1, "ksi") == pytest.approx(6.894757, rel=1e-6)
    assert units.to_canonical("stress", 30, "Mpsi") == pytest.approx(206842.7, rel=1e-6)
    assert units.to_canonical("moment", 1, "lbf*ft") == pytest.approx(1355.818, rel=1e-6)
    assert units.to_canonical("stiffness", 1, "MN/m") == pytest.approx(1000.0)
    assert units.from_canonical("length", 25.4, "in") == pytest.approx(1.0)
    with pytest.raises(units.UnitError):
        units.to_canonical("force", 10, "mm")
    with pytest.raises(units.UnitError):
        units.to_canonical("length", 10, "furlongs-per-banana")
    with pytest.raises(InputError, match="Span L"):
        run("beam", {"L": q(1, "N"), "loads": [{"P": 1, "a": 1}], **SF})


def test_safety_factor_source_is_mandatory() -> None:
    """ENG-005: a calculator with a strength check refuses to run without the SF source."""
    base = {"d": 6, "n_pins": 1, "planes": "1", "F": 1000, "Sy": 640, "sf_required": 2.0}
    with pytest.raises(InputError, match="Safety factor source is required"):
        run("pin_shear", base)
    with pytest.raises(InputError, match="Safety factor source is required"):
        run("pin_shear", {**base, "sf_source": "   "})
    r = run("pin_shear", {**base, "sf_source": "Customer spec CS-12"})
    assert all(c["source"] == "Customer spec CS-12" and c["required"] == 2.0 for c in r["checks"])
    assert r["safety_factor"] == {"required": 2.0, "source": "Customer spec CS-12"}
    assert r["level"] == "preliminary_estimate"


# ----------------------------------------------------------------------------- threads (ISO 898-1)
def test_tensile_stress_area_matches_iso_898_1_table() -> None:
    """ISO 898-1 tabulated nominal stress areas As (mm²), coarse threads (also Shigley Table 8-1)."""
    table = {"M3": 5.03, "M4": 8.78, "M5": 14.2, "M6": 20.1, "M8": 36.6, "M10": 58.0, "M12": 84.3, "M14": 115,
             "M16": 157, "M20": 245, "M24": 353, "M30": 561, "M36": 817}
    for size, As in table.items():
        d, p = std.COARSE_PITCH[size]
        assert std.tensile_stress_area(d, p) == pytest.approx(As, rel=5e-3), size  # table is 3 significant figures
    assert std.bolt_from_clearance(6.6)["size"] == "M6" and std.bolt_from_clearance(5.5)["size"] == "M5"
    assert std.bolt_from_clearance(7.7) is None


# ----------------------------------------------------------------------------- beams + sections
def test_beam_cantilever_shigley_4_10() -> None:
    """Shigley 11th ed. Prob. 4-10: cantilever l = 3 m, two angles I = 4.14e6 mm⁴ (c = 71 mm to the bottom fibre),
    F = 2500 N at a = 2 m plus w = 1 N/mm, E = 207 GPa → ymax = 25.4 mm, M0 = 9.5e6 N·mm, σmax = 163 MPa."""
    o = out("beam", {"support": "cantilever", "L": q(3, "m"), "E": q(207, "GPa"), "section": "custom",
                     "I_custom": 4.14e6, "c_custom": 71, "loads": [{"P": 2500, "a": 2000}], "w": 1.0, **SF})
    assert o["y_max"] == pytest.approx(25.4, abs=0.05)
    assert o["M_max"] == pytest.approx(9.5e6, rel=1e-9)
    assert o["sigma_max"] == pytest.approx(163, abs=0.5)
    assert o["x_ymax"] == pytest.approx(3000)


def test_beam_simply_supported_shigley_4_12() -> None:
    """Shigley 11th ed. Prob. 4-12: simply supported l = 39 in, Ø1.5 in steel (E = 30 Mpsi), F = 340 lbf at
    a = 15 in, w = 150 lbf/ft → y = 0.0978 in at the load and 0.1027 in at midspan."""
    base = {"support": "simply_supported", "L": q(39, "in"), "E": q(30, "Mpsi"), "section": "round", "d": q(1.5, "in"),
            "loads": [{"P": q(340, "lbf"), "a": q(15, "in")}], "w": q(150 / 12, "lbf/in"), **SF}
    assert out("beam", {**base, "x_query": q(15, "in")})["y_at_x"] / IN == pytest.approx(0.0978, abs=5e-5)
    assert out("beam", {**base, "x_query": q(19.5, "in")})["y_at_x"] / IN == pytest.approx(0.1027, abs=5e-5)


@pytest.mark.parametrize("support", ["cantilever", "simply_supported"])
def test_beam_superposition_matches_numerical_integration(support: str) -> None:
    """Independent check: integrate EI·y'' = M(x) numerically (trapezoid, 20 000 steps) with the support
    conditions, and compare to the closed-form superposition used by the calculator."""
    L, EI = 1000.0, 2.0e11
    loads, w = [(1200.0, 300.0), (800.0, 750.0)], 0.9
    n = 20000
    xs = [i * L / n for i in range(n + 1)]
    M = [beam_response(support, L, EI, loads, w, x)[1] for x in xs]
    # cantilever: M from the calculator is hogging (negative), deflection positive downward → y'' = -M/EI
    curv = [-m / EI if support == "cantilever" else m / EI for m in M]
    slope = [0.0]
    for i in range(n):
        slope.append(slope[-1] + (curv[i] + curv[i + 1]) / 2 * (L / n))
    y = [0.0]
    for i in range(n):
        y.append(y[-1] + (slope[i] + slope[i + 1]) / 2 * (L / n))
    if support == "simply_supported":  # add the rigid rotation that makes y(L) = 0 (downward positive: y'' = M/EI)
        y = [-(yi - y[-1] * x / L) for yi, x in zip(y, xs, strict=True)]
    for i in (n // 4, n // 2, 3 * n // 4, n):
        exact = beam_response(support, L, EI, loads, w, xs[i])[0]
        assert y[i] == pytest.approx(exact, rel=1e-4, abs=1e-9), (support, xs[i])


def test_section_properties_match_cad_kernel() -> None:
    """Independent check: area and second moment of the same section from OCCT surface properties."""
    from build123d import Circle, Rectangle
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    def occ(face: Any) -> tuple[float, float]:
        p = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face.wrapped, p)
        return p.Mass(), p.MatrixOfInertia().Value(1, 1)  # about the X axis through the centroid

    A, Ixx = occ(Rectangle(20, 10).faces()[0])         # b along X, h along Y → bending about X uses h³
    o = out("section_properties", {"section": "rect", "b": 20, "h": 10})
    assert o["A"] == pytest.approx(A, rel=1e-9) and o["I"] == pytest.approx(Ixx, rel=1e-9)
    tube = (Circle(15) - Circle(12)).faces()[0]
    A, Ixx = occ(tube)
    o = out("section_properties", {"section": "tube", "D": 30, "t": 3})
    assert o["A"] == pytest.approx(A, rel=1e-6) and o["I"] == pytest.approx(Ixx, rel=1e-6)
    assert o["J"] == pytest.approx(2 * Ixx, rel=1e-6)


# ----------------------------------------------------------------------------- pin shear
def test_pin_shear_shigley_8_68() -> None:
    """Shigley 11th ed. Prob. 8-68: two 5/16 in bolts in single shear carry 5 kip, Sy = 130 kpsi (Ssy = 0.577 Sy),
    member t = 0.25 in, Sy,member = 42 kpsi → τ = 32.6 kpsi, n = 2.30; bearing σb = 32.0 kpsi, n = 4.06 (bolt) and
    1.31 (member)."""
    o = out("pin_shear", {"d": q(5 / 16, "in"), "n_pins": 2, "planes": "1", "F": q(5, "kip"), "Sy": q(130, "ksi"),
                          "t": q(0.25, "in"), "Sy_member": q(42, "ksi"), **SF})
    assert o["tau"] / KSI == pytest.approx(32.6, abs=0.05)
    assert o["n_shear"] == pytest.approx(2.30, abs=0.005)
    assert o["sigma_b"] / KSI == pytest.approx(32.0, abs=0.05)
    assert o["n_bearing_pin"] == pytest.approx(4.06, abs=0.005)
    assert o["n_bearing_member"] == pytest.approx(1.31, abs=0.005)
    # double shear halves the stress
    o2 = out("pin_shear", {"d": q(5 / 16, "in"), "n_pins": 2, "planes": "2", "F": q(5, "kip"), "Sy": q(130, "ksi"), **SF})
    assert o2["tau"] == pytest.approx(o["tau"] / 2)


# ----------------------------------------------------------------------------- bolted joint
def test_bolted_joint_shigley_8_33_and_8_52() -> None:
    """Shigley 11th ed. Prob. 8-33: M12 × 1.75 class 9.8, L = 55 mm, grip 20 mm steel (207 GPa) + 20 mm cast iron
    (100 GPa), dw = 1.5d, Fi = 0.75·Fp, P = 4.712 kN/bolt → kb = 518.8 MN/m, km = 1456 MN/m, C = 0.263,
    Fi = 41.1 kN, np = 1.29, nL = 11.1, n0 = 11.8. Prob. 8-52 (same joint, Pmin = 0, Se = 140 MPa): Goodman
    nf = 7.55 (solution uses At = 84.3 and C = 0.263; ±0.2 %)."""
    o = out("bolted_joint", {"size": "M12", "cls": "9.8", "L": 55, "Eb": q(207, "GPa"),
                             "layers": [{"t": 20, "E": q(207, "GPa")}, {"t": 20, "E": q(100, "GPa")}],
                             "preload_mode": "proof_fraction", "proof_fraction": 0.75, "K": 0.2, "P": q(4.712, "kN"),
                             "fatigue": True, "se_mode": "table", **SF})
    assert o["kb"] / 1000 == pytest.approx(518.8, abs=0.1)
    assert o["km"] / 1000 == pytest.approx(1456, abs=1)
    assert o["C"] == pytest.approx(0.263, abs=5e-4)
    assert o["Fi"] / 1000 == pytest.approx(41.1, abs=0.05)
    assert o["n_p"] == pytest.approx(1.29, abs=0.005)
    assert o["n_L"] == pytest.approx(11.1, abs=0.05)
    assert o["n_0"] == pytest.approx(11.8, abs=0.05)
    assert o["n_f"] == pytest.approx(7.55, rel=2e-3)
    labels = [c["label"] for c in o["_r"]["checks"]]
    assert labels == ["Bolt yield under load", "Overload", "Joint separation", "Bolt fatigue (Goodman screening)"]
    assert next(c for c in o["_r"]["checks"] if c["label"] == "Bolt yield under load")["passed"] is False  # 1.29 < 2


@pytest.mark.parametrize(("L", "layers", "kb", "km"), [
    (60, [(10, 71), (30, 207), (10, 71)], 292.1, 692.5),   # Prob. 8-19: Al 10 / steel 30 / Al 10, M10, L = 60
    (70, [(10, 71), (30, 207), (20, 71)], 247.6, 623.5),   # Prob. 8-20: Al 10 / steel 30 / Al 20, M10, L = 70
])
def test_layered_member_stiffness_shigley_8_19_8_20(L: float, layers: list[tuple[float, float]], kb: float,
                                                    km: float) -> None:
    """Shigley 11th ed. Probs. 8-19 and 8-20: M10 bolt through aluminium/steel stacks; frusta split at mid-grip
    (MN/m = kN/mm)."""
    o = out("bolted_joint", {"size": "M10", "cls": "8.8", "L": L, "Eb": q(207, "GPa"),
                             "layers": [{"t": t, "E": q(E, "GPa")} for t, E in layers], "preload_mode": "proof_fraction",
                             "proof_fraction": 0.75, "K": 0.2, "P": 0, **SF})
    assert o["kb"] / 1000 == pytest.approx(kb, abs=0.1)
    assert o["km"] / 1000 == pytest.approx(km, abs=0.5)


def test_torque_preload_shigley_8_30() -> None:
    """Shigley 11th ed. Prob. 8-30: ½ in bolt, K = 0.20, Fi = 13.8 kip → T = K·Fi·d = 115 lbf·ft. The calculator's
    preload mode reproduces it with a custom ½-13 UNC thread and the ISO strengths replaced by SAE grade 8 values."""
    o = out("bolted_joint", {"size": "custom", "d_custom": q(0.5, "in"), "p_custom": q(1 / 13, "in"), "cls": "custom",
                             "Sp_custom": q(120, "ksi"), "Sut_custom": q(150, "ksi"), "Sy_custom": q(130, "ksi"),
                             "L": q(2, "in"), "Eb": q(30, "Mpsi"), "layers": [{"t": q(1.5, "in"), "E": q(30, "Mpsi")}],
                             "preload_mode": "preload", "Fi": q(13.8, "kip"), "K": 0.2, "P": 0, **SF})
    assert units.from_canonical("moment", o["T"], "lbf*ft") == pytest.approx(115, abs=0.5)
    # torque mode inverts it
    o2 = out("bolted_joint", {**o["_r"]["inputs"], "size": "custom", "cls": "custom", "preload_mode": "torque",
                              "T": q(115, "lbf*ft"), "layers": [{"t": q(1.5, "in"), "E": q(30, "Mpsi")}], **SF})
    assert o2["Fi"] / 4448.2216 == pytest.approx(13.8, abs=0.05)


def test_property_class_size_limits() -> None:
    with pytest.raises(InputError, match="not defined in ISO 898-1"):
        run("bolted_joint", {"size": "M20", "cls": "9.8", "L": 60, "Eb": 207000,
                             "layers": [{"t": 30, "E": 207000}], "P": 0, **SF})


# ----------------------------------------------------------------------------- thread engagement
def test_thread_engagement_hand_derivation() -> None:
    """Independent hand derivation (no published example cited). M10 × 1.5 at basic ISO 724 dimensions:
    D1 = 8.376 mm, d2 = 9.026 mm. External shear area per mm = π·D1·(½ + (d2 − D1)/(√3·P)) = π·8.376·0.75;
    internal = π·d·(½ + (d − d2)/(√3·P)) = π·10·0.875. Bolt-break engagement Le = 2·At / (π·8.376·0.75)."""
    At = math.pi / 4 * (10 - 0.938194 * 1.5) ** 2
    ext = math.pi * (10 - 1.082532 * 1.5) * 0.75
    inn = math.pi * 10 * 0.875
    Le = 2 * At / ext
    J = ext * 800 / (inn * 310)
    o = out("thread_engagement", {"size": "M10", "Sut_ext": 800, "Sut_int": 310, "Le": 15, "F_service": 10000, **SF})
    assert o["Le_min"] == pytest.approx(max(Le, J * Le), rel=1e-4)
    assert o["J"] == pytest.approx(J, rel=1e-4)
    assert Le == pytest.approx(5.88, abs=0.01)        # the bolt-side result in round numbers
    assert o["F_strip_int"] == pytest.approx(0.5 * 310 * inn * 15, rel=1e-6)
    assert o["_r"]["checks"][0]["passed"] is True       # 15 mm > Le_min


# ----------------------------------------------------------------------------- interference fit
def test_press_fit_shigley_3_130_and_3_131() -> None:
    """Shigley 11th ed. Prob. 3-130: steel in steel, R = 1 in, ro = 1.5 in, radial δ = 0.001 in → p = 8.33 kpsi,
    σt,i = −8.33 kpsi, σt,o = 21.7 kpsi. Prob. 3-131: steel shaft (30 Mpsi, ν 0.292) in cast iron hub
    (14.5 Mpsi, ν 0.211) → p = 4599 psi, σt,o = 11 960 psi."""
    base = {"d": q(2, "in"), "delta_d": q(0.002, "in"), "do": q(3, "in"), "di": 0, "Ei": q(30, "Mpsi"), "nui": 0.292, **SF}
    o = out("interference_fit", {**base, "Eo": q(30, "Mpsi"), "nuo": 0.292})
    assert o["p"] / PSI == pytest.approx(8333, abs=1)
    assert o["sigma_t_shaft"] / PSI == pytest.approx(-8333, abs=1)
    assert o["sigma_t_hub"] / PSI == pytest.approx(21670, abs=10)
    o = out("interference_fit", {**base, "Eo": q(14.5, "Mpsi"), "nuo": 0.211})
    assert o["p"] / PSI == pytest.approx(4599, abs=1)
    assert o["sigma_t_hub"] / PSI == pytest.approx(11960, abs=5)


def test_press_fit_displacements_close_the_interference() -> None:
    """Independent check: Lamé radial displacements u = (r/E)(σt − ν·σr) of hub (outward) and hollow shaft
    (inward) at the interface sum to the radial interference."""
    R, ro, ri, dd = 20.0, 45.0, 8.0, 0.05
    Eo, nuo, Ei, nui = 71000.0, 0.33, 207000.0, 0.29
    o = out("interference_fit", {"d": 2 * R, "delta_d": dd, "do": 2 * ro, "di": 2 * ri, "Eo": Eo, "nuo": nuo,
                                 "Ei": Ei, "nui": nui, "L": 30, "mu": 0.15, **SF})
    p = o["p"]
    u_hub = R / Eo * (o["sigma_t_hub"] + nuo * p)
    u_shaft = R / Ei * (o["sigma_t_shaft"] + nui * p)
    assert u_hub - u_shaft == pytest.approx(dd / 2, rel=1e-9)
    assert o["T_cap"] == pytest.approx(math.pi * 0.15 * p * (2 * R) ** 2 * 30 / 2, rel=1e-12)


# ----------------------------------------------------------------------------- shaft
def test_shaft_de_goodman_shigley_7_1() -> None:
    """Shigley 10th ed. Prob. 7-1(d): Kf = 2.2, Kfs = 1.8, Ma = 70, Ta = 45, Mm = 55, Tm = 35 N·m, Se = 210 MPa,
    Sut = 700 MPa, n = 2 → DE-Goodman d = 27.27 mm."""
    o = out("shaft_fatigue", {"d": 27.27, "Ma": q(70, "N*m"), "Mm": q(55, "N*m"), "Ta": q(45, "N*m"),
                              "Tm": q(35, "N*m"), "kf_mode": "direct", "Kf": 2.2, "Kfs": 1.8, "Sut": 700, "Sy": 560,
                              "se_mode": "given", "Se": 210, **SF})
    assert o["d_min"] == pytest.approx(27.27, abs=0.005)
    assert o["n_f"] == pytest.approx(2.0, abs=1e-3)


def test_shaft_marin_factors_shigley_7_2() -> None:
    """Shigley 10th ed. Prob. 7-2 trial 1: SAE 2340, Sut = 175 kpsi, machined, d = 0.75 in → ka = 0.69, kb = 0.91,
    Se = 0.69·0.91·87.5 = 54.9 kpsi. The solution rounds ka and kb to two figures, so Se agrees within 1 %."""
    r = run("shaft_fatigue", {"d": q(0.75, "in"), "Ma": q(600, "lbf*in"), "Mm": 0, "Ta": 0, "Tm": q(400, "lbf*in"),
                              "kf_mode": "kt_q", "Kt": 1.9, "q": 0.9, "Kts": 1.5, "qs": 0.92, "Sut": q(175, "ksi"),
                              "Sy": q(160, "ksi"), "se_mode": "estimate", "finish": "machined", "reliability": "50",
                              "kd": 1, "kf_misc": 1, **SF})
    steps = {s["label"]: s["value"] for s in r["steps"]}
    assert steps["Surface factor"] == pytest.approx(0.69, abs=0.005)
    assert steps["Size factor"] == pytest.approx(0.91, abs=0.005)
    assert output(r, "Se") / KSI == pytest.approx(54.9, rel=0.01)
    assert "Kf = 1.81, Kfs = 1.46" in steps["Fatigue stress-concentration factors"]


# ----------------------------------------------------------------------------- bearing life
@pytest.mark.parametrize(("P", "hours", "rpm", "expected"), [
    (q(2, "kN"), 1e9 / (60 * 1000), 1000, q(20, "kN")),       # Prob. 11-8: LD = 10⁹ rev
    (q(800, "lbf"), 12000, 350, q(5050, "lbf")),              # Prob. 11-9
    (q(4, "kN"), 8000, 500, q(24.9, "kN")),                   # Prob. 11-10
])
def test_bearing_required_rating_shigley_11(P: dict[str, Any], hours: float, rpm: float,
                                             expected: dict[str, Any]) -> None:
    """Shigley 10th ed. Probs. 11-8, 11-9, 11-10 (R = 0.90, ball bearing): C10 = FD·(LD/LR)^(1/3)."""
    o = out("bearing_life", {"type": "ball", "load_mode": "p", "P": P, "af": 1, "n": rpm, "reliability": "90",
                             "aiso": 1, "target_h": hours})
    exp = units.to_canonical("force", expected["value"], expected["unit"])
    assert o["C_req"] == pytest.approx(exp, rel=2e-3)


def test_bearing_life_iso_281_hand_derivation() -> None:
    """Independent hand derivation of ISO 281: roller p = 10/3, C = 50 kN, P = 5 kN → L10 = 10^(10/3) = 2154.4
    million rev; at 1200 rev/min L10h = 2154.4e6 / 72 000 = 29 922 h; R = 99 % → a1 = 0.25 (Table 12), aISO = 1.5 →
    Lnm = 0.375·L10."""
    o = out("bearing_life", {"type": "roller", "C": q(50, "kN"), "load_mode": "p", "P": q(5, "kN"), "af": 1,
                             "n": 1200, "reliability": "99", "aiso": 1.5})
    assert o["L10"] == pytest.approx(10 ** (10 / 3), rel=1e-12)
    assert o["L10h"] == pytest.approx(10 ** (10 / 3) * 1e6 / 72000, rel=1e-12)
    assert o["Lnm"] == pytest.approx(0.375 * 10 ** (10 / 3), rel=1e-12)


# ----------------------------------------------------------------------------- spring
def test_compression_spring_shigley_10_3() -> None:
    """Shigley 11th ed. Prob. 10-3: music wire d = 2.5 mm, OD = 31 mm, plain-ground ends, Nt = 14, G = 81.0 GPa →
    Na = 13, k = 1.314 N/mm, Ls = 35 mm, Sut = 1936 MPa, Ssy = 871.2 MPa, KB = 1.117, Fs = 167.9 N,
    L0 = 162.8 mm, L0,cr = 149.9 mm (α = 0.5)."""
    r = run("compression_spring", {"d": 2.5, "OD": 31, "Nt": 14, "ends": "plain_ground", "wire": "A228",
                                   "G": q(81.0, "GPa"), "alpha": "0.5", "L0": 162.8, **SF})
    o = {x["key"]: x["value"] for x in r["outputs"]}
    assert o["Na"] == 13 and o["Ls"] == pytest.approx(35)
    assert o["k"] == pytest.approx(1.314, abs=5e-4)
    assert o["Sut"] == pytest.approx(1936, abs=0.5)
    assert o["Ssy"] == pytest.approx(871.2, abs=0.1)
    assert o["Fs"] == pytest.approx(167.9, abs=0.1)
    assert o["L0_no_set"] == pytest.approx(162.8, abs=0.1)
    assert o["L0_cr"] == pytest.approx(149.9, abs=0.05)
    kb = next(s for s in r["steps"] if s["label"] == "Bergsträsser factor")["value"]
    assert kb == pytest.approx(1.117, abs=5e-4)
    assert o["n_solid"] == pytest.approx(1.0, abs=2e-3)   # L0 chosen so the spring just reaches Ssy at solid


# ----------------------------------------------------------------------------- tolerance stack
def test_tolerance_stack_shigley_1_21_and_rss() -> None:
    """Shigley 10th ed. Prob. 1-21: w = d − a − b − c with a = 1.500 ± 0.001, b = 2.000 ± 0.003, c = 3.000 ± 0.004,
    d = 6.520 ± 0.010 in → w = 0.020 ± 0.018 in (worst case). RSS by independent hand derivation:
    √(0.001² + 0.003² + 0.004² + 0.010²) = 0.011225 in."""
    rows = [("d", "+", 6.520, 0.010), ("a", "-", 1.500, 0.001), ("b", "-", 2.000, 0.003), ("c", "-", 3.000, 0.004)]
    o = out("tolerance_stack", {"rows": [{"name": n, "dir": s, "nominal": q(x, "in"), "plus": q(t, "in"),
                                          "minus": q(t, "in"), "sens": 1} for n, s, x, t in rows],
                                "spec_min": q(0.0, "in")})
    assert o["mean"] / IN == pytest.approx(0.020, abs=1e-9)
    assert o["wc"] / IN == pytest.approx(0.018, abs=1e-9)
    assert o["rss"] / IN == pytest.approx(math.sqrt(0.001 ** 2 + 0.003 ** 2 + 0.004 ** 2 + 0.010 ** 2), rel=1e-9)
    assert all(c["passed"] for c in o["_r"]["checks"])   # wmin = 0.002 in ≥ 0


def test_tolerance_stack_sensitivity_and_asymmetric_shigley_1_24() -> None:
    """Shigley 10th ed. Prob. 1-24: Do = Di + 2d, Di = 3.734 ± 0.028, d = 0.139 ± 0.004 in → Do = 4.012 ± 0.036 in
    (sensitivity 2 on d). Plus an asymmetric band (hand derivation): 10 +0.2/−0 has mean 10.1 ± 0.1."""
    o = out("tolerance_stack", {"rows": [
        {"name": "Di", "dir": "+", "nominal": q(3.734, "in"), "plus": q(0.028, "in"), "minus": q(0.028, "in"), "sens": 1},
        {"name": "d", "dir": "+", "nominal": q(0.139, "in"), "plus": q(0.004, "in"), "minus": q(0.004, "in"), "sens": 2}]})
    assert o["mean"] / IN == pytest.approx(4.012, abs=1e-9) and o["wc"] / IN == pytest.approx(0.036, abs=1e-9)
    o = out("tolerance_stack", {"rows": [{"name": "x", "dir": "+", "nominal": 10, "plus": 0.2, "minus": 0, "sens": 1}],
                                "spec_max": 10.15})
    assert o["mean"] == pytest.approx(10.1) and o["wc"] == pytest.approx(0.1) and o["wc_max"] == pytest.approx(10.2)
    assert [c["passed"] for c in o["_r"]["checks"]] == [False, False]


# ----------------------------------------------------------------------------- ENG-012 wording guard + labels
def test_claim_guard() -> None:
    for bad in ["Design validated by FEA", "The bracket is safe for use", "Certified to ISO 9001",
                "Approved for production", "This part is safe.", "FEA-validated design", "validation passed"]:
        assert wording.claims(bad), bad
    for ok in ["Not validated", "Validated simulation: not performed", "unvalidated estimate", ("meets the required "
               "factor 2.0 per ES-001"), "never claims validation", "without validated evidence"]:
        assert not wording.claims(ok), ok
    with pytest.raises(wording.ClaimError):
        wording.require_no_claim("Shaft validated", "Conclusion")


def test_every_calculator_is_cited_labelled_and_free_of_claims() -> None:
    """ENG-004/007/012: each calculator cites sources and its verification, carries an advice level, and none of
    its generated text (schema, steps, notes, warnings) makes a validation or safety claim."""
    from aicad.engineering import review
    from aicad.platform.catalog import MODULES

    assert len(REGISTRY) >= 10
    for c in REGISTRY.values():
        s = c.schema()
        assert s["references"] and s["verified_against"] and s["assumptions"], c.id
        assert s["level"] == "preliminary_estimate"
        text = " ".join(map(str, [s["name"], s["summary"], s["references"], s["assumptions"], s["verified_against"],
                                  [p["help"] for p in s["inputs"]]]))
        assert not wording.claims(text), (c.id, wording.claims(text))
    m = MODULES["engineering"]
    assert m["status"] == "live" and not wording.claims(m["summary"] + " ".join(m["bullets"]))
    assert not wording.claims(review.HEURISTIC_NOTE)


# ----------------------------------------------------------------------------- geometry heuristics (ENG-010)
def _review_of(script: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    import runpy

    from aicad.engineering import review
    from aicad.recognize import recognize

    shape = runpy.run_path(str(DEMO / script))["result"]
    rec = recognize(shape)
    sharp = review.sharp_reentrant_edges(shape)
    return rec, sharp, review.stress_hints(rec, sharp)


def test_stress_hints_on_demo_parts() -> None:
    # stepped shaft: sharp Ø25 → Ø20 shoulders (no fillet) and the keyway's internal corners
    _, sharp, hints = _review_of("stepped_shaft.py")
    sh = [h for h in hints if h["kind"] == "shoulder"]
    assert sh and sh[0]["severity"] == "high" and "D/d = 1.25" in sh[0]["title"]
    curved = [s for s in sharp if s["type"] != "line"]
    assert len(curved) >= 2   # two circular shoulder edges
    # mounting plate: holes 10 mm from the edges (Ø6.6 → 1.52 d) and the unfilleted pocket floor
    _, sharp, hints = _review_of("mounting_plate.py")
    edge = [h for h in hints if h["kind"] == "hole_edge"]
    assert len(edge) == 1 and edge[0]["count"] == 4 and edge[0]["severity"] == "medium"
    assert "4 × Ø6.6 holes" in edge[0]["title"] and "1.52 × d" in edge[0]["title"]
    assert any(h["kind"] == "sharp_corner" for h in hints)
    assert all(abs(s["center"][2] - 6.0) < 1e-6 for s in sharp)  # every sharp internal edge is on the pocket floor
    # L-bracket: the R3 inner fillet means its leg junction is NOT flagged as sharp
    _rec, sharp, hints = _review_of("l_bracket.py")
    assert not sharp
    # every hint is phrased as a heuristic, never as a verdict
    for h in hints:
        assert not wording.claims(h["title"] + h["detail"] + h["suggestion"])


# ----------------------------------------------------------------------------- API
def _unlock(c: TestClient) -> None:
    pid = c.post("/api/billing/checkout", json={"product_code": "addon_engineering"}).json()["payment_id"]
    assert c.post(f"/api/billing/payments/{pid}/simulate", json={"outcome": "success"}).status_code == 200


def test_api_entitlement_catalog_and_run(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "eng@x.com")
    set_trial_ended("eng@x.com")  # a running trial may use every live module: test the paywall after it
    r = c.get("/api/m/engineering/catalog")
    assert r.status_code == 402 and r.json()["detail"]["cta"] == "/app/modules/engineering"
    set_trial_ended("eng@x.com", False)
    _unlock(c)
    cat = c.get("/api/m/engineering/catalog").json()
    ids = {x["id"] for x in cat["calculators"]}
    assert {"beam", "bolted_joint", "pin_shear", "bearing_life", "thread_engagement", "interference_fit",
            "shaft_fatigue", "compression_spring", "tolerance_stack", "section_properties"} <= ids
    assert set(cat["levels"]) == {"recommended_check", "preliminary_estimate", "verified_calculation",
                                  "validated_simulation"}
    assert cat["library"]["materials"] and all("verify" in m["note"].lower() for m in cat["library"]["materials"])
    r = c.post("/api/m/engineering/run", json={"calc_id": "pin_shear", "inputs": {"d": 6, "n_pins": 1, "planes": "1",
                                                                                  "F": 1000, "Sy": 640, "sf_required": 2}})
    assert r.status_code == 422 and "Safety factor source" in r.json()["detail"]
    r = c.post("/api/m/engineering/run", json={"calc_id": "beam", "inputs": {"L": {"value": 1, "unit": "kg"}}})
    assert r.status_code == 422


def test_api_project_link_signoff_and_invalidation(app_client: TestClient) -> None:  # noqa: F811
    from sqlalchemy import select

    from aicad.platform.db import session_factory
    from aicad.platform.models import Membership

    c = app_client
    me = signup(c, "signer@x.com", name="Grace Hopper")
    _unlock(c)
    pid, ws = _project_with_model(c, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))
    m = c.get(f"/api/m/engineering/projects/{pid}/model").json()
    assert m["available"] and m["material"]["code"] == "al_6061" and m["mechanical"]["Sy_MPa"] == 276
    assert m["mass"]["mass_kg"] == pytest.approx(m["mass"]["volume_mm3"] * 2.70e-6, rel=1e-9)
    assert m["mass"]["com_mm"] and m["mass"]["inertia_kg_mm2"]
    bolt = next(s for s in m["suggestions"] if s["calc_id"] == "bolted_joint")
    assert bolt["inputs"]["size"] == "M6" and "ISO 273" in bolt["provenance"]["size"]
    assert any(h["kind"] == "hole_edge" for h in m["hints"])
    assert (ws / "engineering" / "geometry.json").is_file()
    # review checklist tied to features
    rv = c.get(f"/api/m/engineering/projects/{pid}/review").json()
    modes = {i["mode"] for i in rv["items"]}
    assert {"Static strength", "Stress concentration", "Bolted / pinned joints", "Fatigue"} <= modes
    assert all(i["level"] == "recommended_check" for i in rv["items"]) and rv["analyses"]
    assert c.patch(f"/api/m/engineering/projects/{pid}/review/items/joint",
                   json={"status": "addressed", "note": "See set 1"}).status_code == 200
    # load case + set from the model suggestion
    lc = c.post(f"/api/m/engineering/projects/{pid}/loadcases", json={
        "name": "Lift", "kind": "static", "loads": [{"name": "Hoist", "type": "force", "value": 2, "unit": "kN",
                                                     "basis": "specified", "source": "Customer spec"}],
        "supports": [{"type": "bolted", "location": "4 × Ø6.6"}]}).json()
    assert lc["loads"][0]["value_canonical"] == pytest.approx(2000)
    cs = c.post(f"/api/m/engineering/projects/{pid}/sets", json={"name": "Mounting joint", "load_case_ids": [lc["id"]]}).json()
    assert cs["status"]["state"] == "unsigned" and cs["status"]["label"] == "Unsigned: not for release"
    inputs = {**bolt["inputs"], "P": {"value": 500, "unit": "N"}, "preload_mode": "proof_fraction", "proof_fraction": 0.75,
              "K": 0.2, "cls": "8.8", "Eb": {"value": 207, "unit": "GPa"}, **SF}
    cs = c.post(f"/api/m/engineering/projects/{pid}/sets/{cs['id']}/items",
                json={"calc_id": "bolted_joint", "inputs": inputs, "source": bolt["provenance"]}).json()
    item = cs["items"][0]
    assert item["result"]["level"] == "preliminary_estimate"
    # validation wording is refused; sign-off needs confirmation
    r = c.patch(f"/api/m/engineering/projects/{pid}/sets/{cs['id']}", json={"conclusion": "Joint validated by FEA"})
    assert r.status_code == 422 and "validated" in r.json()["detail"]
    sign = {"statement": "Reviewed inputs, assumptions and results against the load case.", "confirm": True}
    assert c.post(f"/api/m/engineering/projects/{pid}/sets/{cs['id']}/signoff",
                  json={**sign, "confirm": False}).status_code == 422
    cs = c.post(f"/api/m/engineering/projects/{pid}/sets/{cs['id']}/signoff", json=sign).json()
    assert cs["status"]["state"] == "signed" and cs["status"]["for_release"]
    so = cs["signoff"]
    assert so["name"] == "Grace Hopper" and so["email"] == me["user"]["email"] and len(so["hash"]) == 64
    assert so["self_check"] is True and cs["items"][0]["result"]["level"] == "verified_calculation"
    # editing an input invalidates the signature
    cs2 = c.patch(f"/api/m/engineering/projects/{pid}/sets/{cs['id']}/items/{item['id']}",
                json={"calc_id": "bolted_joint", "inputs": {**inputs, "P": {"value": 600, "unit": "N"}}}).json()
    assert cs2["status"]["state"] == "invalidated" and not cs2["status"]["for_release"]
    assert cs2["items"][0]["result"]["level"] == "preliminary_estimate"
    assert any(h["event"] == "signature_invalidated" for h in cs2["history"])
    # re-sign, then edit the linked load case: also invalidates
    cs3 = c.post(f"/api/m/engineering/projects/{pid}/sets/{cs['id']}/signoff", json=sign).json()
    assert cs3["status"]["state"] == "signed"
    body = {k: lc[k] for k in ("name", "kind", "description", "loads", "supports", "cycles", "temperature_c",
                               "environment", "source")}
    body["loads"] = [{**body["loads"][0], "value": 3}]
    assert c.patch(f"/api/m/engineering/projects/{pid}/loadcases/{lc['id']}", json=body).status_code == 200
    cs4 = c.get(f"/api/m/engineering/projects/{pid}/sets/{cs['id']}").json()
    assert cs4["status"]["state"] == "invalidated"
    assert c.delete(f"/api/m/engineering/projects/{pid}/loadcases/{lc['id']}").status_code == 409
    # stack-ups
    st = c.post(f"/api/m/engineering/projects/{pid}/stackups", json={
        "name": "Lid gap", "unit": "in", "spec_min": 0, "rows": [
            {"name": "d", "dir": "+", "nominal": 6.52, "plus": 0.01, "minus": 0.01},
            {"name": "a", "dir": "-", "nominal": 1.5, "plus": 0.001, "minus": 0.001},
            {"name": "b", "dir": "-", "nominal": 2, "plus": 0.003, "minus": 0.003},
            {"name": "c", "dir": "-", "nominal": 3, "plus": 0.004, "minus": 0.004}]}).json()
    assert output(st["result"], "wc") / IN == pytest.approx(0.018)
    assert len(c.get(f"/api/m/engineering/projects/{pid}/stackups").json()["items"]) == 1
    listing = c.get("/api/m/engineering/projects").json()["items"]
    assert listing[0]["id"] == pid and listing[0]["sets"] == 1 and listing[0]["signed"] == 0
    # viewers are read-only and cannot sign
    db = session_factory()()
    mem = db.scalar(select(Membership).where(Membership.user_id == me["user"]["id"]))
    mem.role = "viewer"
    db.commit()
    db.close()
    assert c.get(f"/api/m/engineering/projects/{pid}/sets").status_code == 200
    assert c.post(f"/api/m/engineering/projects/{pid}/sets", json={"name": "x"}).status_code == 403
    assert c.post(f"/api/m/engineering/projects/{pid}/sets/{cs['id']}/signoff", json=sign).status_code == 403
    assert c.post(f"/api/m/engineering/projects/{pid}/stackups", json={
        "name": "x", "rows": [{"nominal": 1, "plus": 0, "minus": 0}]}).status_code == 403
    # another workspace cannot see the project
    c.cookies.clear()
    signup(c, "other@x.com", workspace="Other Co")
    _unlock(c)
    assert c.get(f"/api/m/engineering/projects/{pid}/sets").status_code == 404
