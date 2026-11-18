"""FX-05 keyed shaft in a bearing housing (original design, generated for Formwright).

Design intent: an output shaft of a small drive. A grey-iron housing block carries two 6204 deep-groove ball
bearings in Ø47 seats against internal shoulders; a stepped C45 shaft is located axially by its Ø26 collar against
bearing A's inner ring; a spur gear (Toolbox m2 z30 profile with a DIN 6885 hub keyway) sits on the Ø18 end against
the Ø20/Ø18 shoulder and is driven by a 6 × 6 × 18 parallel key. Four Ø9 holes fix the housing.

Frames (mm, Z up): the housing is the assembly frame (Z = 0 its underside, centred in X and Y, bore along Z).
The shaft's frame starts at its lower end (Z = 0) on the axis; its keyway is on +Y. The key's frame: x ∈ [−3, 3],
y ∈ [0, 6] (bottom at y = 0), z ∈ [0, 18]. The gear's frame is the Toolbox one (bottom face at Z = 0) with the hub
keyway on +Y. Bearings use the Toolbox frame (axis Z, bottom face at Z = 0).

Hand placements: bearing A z 0..14 (against the shoulder at z = 14), bearing B z 44..58; the shaft collar (shaft z
30..60) spans z 14..44, so the shaft frame is at z = −16; gear on the shoulder at shaft z 85 (world 69); key in the
shaft keyway at shaft y 5.5, z 86. Freedoms left: the two bearings' spins and the spin of the shaft + key + gear.
"""

from __future__ import annotations

import math
from typing import Any

from aicad import toolbox
from aicad.assembly import xform
from aicad.fixtures.harness import Feat, Fixture, InstDef, PartDef, perturb

ID = "FX-05"
SLUG = "fx05_keyed_shaft"
TITLE = "Keyed shaft, bearings, housing and gear"

PARAMS: dict[str, Any] = {
    "bearing": 6204,
    "housing_W": 80.0, "housing_H": 58.0, "bore_d": 30.0, "fix_hole_d": 9.0, "fix_xy": 30.0,
    # shaft steps from the lower end: (length, diameter)
    "steps": [[30.0, 20.0], [30.0, 26.0], [25.0, 20.0], [30.0, 18.0]],
    "key_b": 6.0, "key_h": 6.0, "key_L": 18.0, "key_t1": 3.5, "key_t2": 2.8, "key_z0": 86.0,
    "gear_m": 2.0, "gear_z": 30, "gear_B": 20.0,
}


def _f(R: float, v: float) -> float:
    """∫ sqrt(R² − x²) dx (antiderivative)."""
    return v / 2 * math.sqrt(R * R - v * v) + R * R / 2 * math.asin(v / R)


def _cyl_z(r: float, h: float, x: float = 0.0, y: float = 0.0, z0: float = 0.0) -> Any:
    from build123d import Align, Cylinder, Pos

    return Pos(x, y, z0) * Cylinder(r, h, align=(Align.CENTER, Align.CENTER, Align.MIN))


def _bearing_dims(p: dict[str, Any]) -> tuple[float, float, float]:
    d, D, B = toolbox.BEARING[int(p["bearing"])]
    return float(d), float(D), float(B)


# ------------------------------------------------------------------ housing
def housing(p: dict[str, Any] = PARAMS) -> Any:
    from build123d import Align, Box

    from aicad import fw

    _d, D, B = _bearing_dims(p)
    W, H = p["housing_W"], p["housing_H"]
    part = fw.feature("Block", Box(W, W, H, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    part = fw.feature("Bearing seats", part - _cyl_z(D / 2, B + 0.01, z0=-0.01) - _cyl_z(D / 2, B + 0.01, z0=H - B))
    part = fw.feature("Shaft bore", part - _cyl_z(p["bore_d"] / 2, H + 0.02, z0=-0.01))
    for sx in (-1, 1):
        for sy in (-1, 1):
            part -= _cyl_z(p["fix_hole_d"] / 2, H + 0.02, sx * p["fix_xy"], sy * p["fix_xy"], -0.01)
    part = fw.feature("Fixing holes", part)
    part.label = "Bearing housing"
    return part


def housing_feats(p: dict[str, Any] = PARAMS) -> list[Feat]:
    _d, D, B = _bearing_dims(p)
    W, H = p["housing_W"], p["housing_H"]
    seat = math.pi / 4 * D * D * B
    bore = math.pi / 4 * p["bore_d"] ** 2 * (H - 2 * B)
    fix = math.pi / 4 * p["fix_hole_d"] ** 2 * H
    return [Feat(W * W * H, (0, 0, H / 2)), Feat(-seat, (0, 0, B / 2)), Feat(-seat, (0, 0, H - B / 2)),
            Feat(-bore, (0, 0, H / 2)),
            *[Feat(-fix, (sx * p["fix_xy"], sy * p["fix_xy"], H / 2)) for sx in (-1, 1) for sy in (-1, 1)]]


# ------------------------------------------------------------------ shaft
def _keyway_area(R: float, b: float, t1: float) -> float:
    """Cross-section removed by a flat-bottomed keyway of width b and depth t1 (from the top of the circle)."""
    return _f(R, b / 2) - _f(R, -b / 2) - b * (R - t1)


def _keyway_ymoment(R: float, b: float, t1: float) -> float:
    """∫∫ y dA over that cross-section: ∫ ((R² − x²) − (R − t1)²) / 2 dx over |x| ≤ b/2."""
    h = b / 2
    return ((R * R - (R - t1) ** 2) * b - 2 * h ** 3 / 3) / 2


def shaft(p: dict[str, Any] = PARAMS) -> Any:
    from build123d import Align, Box, Pos

    from aicad import fw

    z = 0.0
    part = None
    for L, d in p["steps"]:
        seg = _cyl_z(d / 2, L, z0=z)
        part = seg if part is None else part + seg
        z += L
    part = fw.feature("Stepped shaft", part)
    R = p["steps"][-1][1] / 2
    b, t1, kL = p["key_b"], p["key_t1"], p["key_L"]
    slot = Pos(0, R - t1, p["key_z0"]) * Box(b, t1 + 1, kL, align=(Align.CENTER, Align.MIN, Align.MIN))
    part = fw.feature(f"Keyway {b:g}×{t1:g} (DIN 6885)", part - slot)
    part.label = "Output shaft"
    return part


def shaft_feats(p: dict[str, Any] = PARAMS) -> list[Feat]:
    out = []
    z = 0.0
    for L, d in p["steps"]:
        out.append(Feat(math.pi / 4 * d * d * L, (0, 0, z + L / 2)))
        z += L
    R = p["steps"][-1][1] / 2
    b, t1, kL = p["key_b"], p["key_t1"], p["key_L"]
    A = _keyway_area(R, b, t1)
    out.append(Feat(-A * kL, (0, _keyway_ymoment(R, b, t1) / A, p["key_z0"] + kL / 2)))
    return out


def shaft_len(p: dict[str, Any]) -> float:
    return sum(L for L, _ in p["steps"])


# ------------------------------------------------------------------ key
def key(p: dict[str, Any] = PARAMS) -> Any:
    from build123d import Align, Box

    from aicad import fw

    part = fw.feature("Parallel key", Box(p["key_b"], p["key_h"], p["key_L"], align=(Align.CENTER, Align.MIN, Align.MIN)))
    part.label = f"Parallel key {p['key_b']:g}×{p['key_h']:g}×{p['key_L']:g}"
    return part


# ------------------------------------------------------------------ gear (Toolbox profile + hub keyway)
def gear(p: dict[str, Any] = PARAMS) -> Any:
    from build123d import Align, Box, Pos

    from aicad import fw

    bore = p["steps"][-1][1]
    g, _ = toolbox.build("spur_gear", M=p["gear_m"], Z=p["gear_z"], B=p["gear_B"], BORE=bore)
    b = p["key_b"]
    top = bore / 2 + p["key_t2"]
    slot = Pos(0, 0, -0.01) * Box(b, top, p["gear_B"] + 0.02, align=(Align.CENTER, Align.MIN, Align.MIN))
    part = fw.feature(f"Hub keyway {b:g}×{p['key_t2']:g} (DIN 6885)", g - slot)
    part.label = f"Spur gear m{p['gear_m']:g} z{p['gear_z']}, keyed"
    return part


def gear_feats(p: dict[str, Any] = PARAMS) -> list[Feat]:
    bore = p["steps"][-1][1]
    _s, exp = toolbox.build("spur_gear", M=p["gear_m"], Z=p["gear_z"], B=p["gear_B"], BORE=bore)
    R, b, B = bore / 2, p["key_b"], p["gear_B"]
    top = R + p["key_t2"]
    h = b / 2
    area = b * top - (_f(R, h) - _f(R, -h))                 # slot outside the bore
    ymom = ((top * top - R * R) * b + 2 * h ** 3 / 3) / 2   # ∫ (top² − (R² − x²)) / 2 dx
    return [Feat(exp["volume"], (0, 0, B / 2)), Feat(-area * B, (0, ymom / area, B / 2))]


def gear_bbox(p: dict[str, Any] = PARAMS) -> tuple[float, float, float]:
    _s, exp = toolbox.build("spur_gear", M=p["gear_m"], Z=p["gear_z"], B=p["gear_B"], BORE=p["steps"][-1][1])
    return tuple(exp["bbox"])  # type: ignore[return-value]


def _bearing_part(p: dict[str, Any]) -> PartDef:
    series = int(p["bearing"])
    _shape, exp = toolbox.build("bearing", SERIES=series)
    d, D, B = _bearing_dims(p)

    def build() -> Any:
        s, _ = toolbox.build("bearing", SERIES=series)
        s.label = f"Ball bearing {series}"
        return s

    return PartDef("bearing", f"Ball bearing {series}", "steel_4140", build, (D, D, B),
                   [Feat(exp["volume"], (0, 0, B / 2))], solids=exp["solids"], kind="toolbox",
                   standard="ISO 15 (envelope)", designation=str(series), params={"code": "bearing", "SERIES": series},
                   meta={"envelope": {"kind": "annulus", "r0": d / 2, "r1": D / 2, "z0": 0.0, "z1": B}})


# ------------------------------------------------------------------ the assembly
def fixture(p: dict[str, Any] = PARAMS) -> Fixture:
    _d, _D, B = _bearing_dims(p)
    H, L = p["housing_H"], shaft_len(p)
    steps = p["steps"]
    collar_lo = steps[0][0]                      # shaft z of the collar's lower face
    shoulder = steps[0][0] + steps[1][0] + steps[2][0]   # shaft z of the Ø20/Ø18 step (gear seat)
    R_seat = steps[-1][1] / 2
    z_shaft = B - collar_lo                      # shaft frame in the housing: collar on bearing A (top at z = B)
    parts = {
        "housing": PartDef("housing", "FX-05 bearing housing", "cast_iron_gray", lambda: housing(p),
                           (p["housing_W"], p["housing_W"], H), housing_feats(p),
                           params={k: p[k] for k in ("housing_W", "housing_H", "bore_d", "fix_hole_d", "fix_xy",
                                                     "bearing")}),
        "bearing": _bearing_part(p),
        "shaft": PartDef("shaft", "FX-05 output shaft", "steel_1045", lambda: shaft(p),
                         (max(dd for _, dd in steps), max(dd for _, dd in steps), L), shaft_feats(p),
                         params={k: p[k] for k in ("steps", "key_b", "key_t1", "key_L", "key_z0")}),
        "key": PartDef("key", f"Parallel key {p['key_b']:g}×{p['key_h']:g}×{p['key_L']:g}", "steel_1045",
                       lambda: key(p), (p["key_b"], p["key_h"], p["key_L"]),
                       [Feat(p["key_b"] * p["key_h"] * p["key_L"], (0, p["key_h"] / 2, p["key_L"] / 2))],
                       standard="DIN 6885-1 form B", params={k: p[k] for k in ("key_b", "key_h", "key_L")}),
        "gear": PartDef("gear", f"FX-05 spur gear m{p['gear_m']:g} z{p['gear_z']}, keyed", "steel_1045",
                        lambda: gear(p), gear_bbox(p), gear_feats(p), standard="ISO 53 profile (Toolbox)",
                        params={k: p[k] for k in ("gear_m", "gear_z", "gear_B", "key_b", "key_t2")}),
    }
    I = xform.ident()
    tr = xform.translate
    Z = ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    T_shaft = tr((0, 0, z_shaft))
    T_key = T_shaft @ tr((0, R_seat - p["key_t1"], p["key_z0"]))
    T_gear = T_shaft @ tr((0, 0, shoulder))
    insts = [InstDef("housing", "housing", I, I, fixed=True),
             InstDef("bearing_a", "bearing", I, perturb(I, 1), free_axis=Z),
             InstDef("bearing_b", "bearing", tr((0, 0, H - B)), perturb(tr((0, 0, H - B)), 2), free_axis=Z),
             InstDef("shaft", "shaft", T_shaft, perturb(T_shaft, 3), free_axis=Z),
             InstDef("key", "key", T_key, perturb(T_key, 4), rel_to="shaft"),
             InstDef("gear", "gear", T_gear, perturb(T_gear, 5), rel_to="shaft")]
    axis = {"kind": "axis", "p": [0, 0, 0], "v": [0, 0, 1]}

    def plane(pt: list[float], v: list[float]) -> dict[str, Any]:
        return {"kind": "plane", "p": pt, "v": v}

    b2, kh = p["key_b"] / 2, p["key_h"]
    floor_y = R_seat - p["key_t1"]
    kz = p["key_z0"]
    mates = [
        {"id": "m_bearing_a_axis", "type": "concentric", "a": "housing", "ra": axis, "b": "bearing_a", "rb": axis},
        {"id": "m_bearing_a_shoulder", "type": "coincident", "a": "housing", "ra": plane([0, 0, B], [0, 0, -1]),
         "b": "bearing_a", "rb": plane([0, 0, B], [0, 0, 1])},
        {"id": "m_bearing_b_axis", "type": "concentric", "a": "housing", "ra": axis, "b": "bearing_b", "rb": axis},
        {"id": "m_bearing_b_shoulder", "type": "coincident", "a": "housing", "ra": plane([0, 0, H - B], [0, 0, 1]),
         "b": "bearing_b", "rb": plane([0, 0, 0], [0, 0, -1])},
        {"id": "m_shaft_axis", "type": "concentric", "a": "housing", "ra": axis, "b": "shaft", "rb": axis},
        {"id": "m_shaft_collar", "type": "coincident", "a": "bearing_a", "ra": plane([0, 0, B], [0, 0, 1]),
         "b": "shaft", "rb": plane([0, 0, collar_lo], [0, 0, -1])},
        {"id": "m_key_floor", "type": "coincident", "a": "shaft", "ra": plane([0, floor_y, kz + 9], [0, 1, 0]),
         "b": "key", "rb": plane([0, 0, 9], [0, -1, 0])},
        {"id": "m_key_side", "type": "coincident", "a": "shaft", "ra": plane([-b2, floor_y + 1, kz + 9], [1, 0, 0]),
         "b": "key", "rb": plane([-b2, 1, 9], [-1, 0, 0])},
        {"id": "m_key_end", "type": "coincident", "a": "shaft", "ra": plane([0, floor_y + 1, kz], [0, 0, 1]),
         "b": "key", "rb": plane([0, 1, 0], [0, 0, -1])},
        {"id": "m_gear_axis", "type": "concentric", "a": "shaft", "ra": {"kind": "axis", "p": [0, 0, shoulder],
                                                                          "v": [0, 0, 1]},
         "b": "gear", "rb": axis},
        {"id": "m_gear_shoulder", "type": "coincident", "a": "shaft", "ra": plane([0, 0, shoulder], [0, 0, 1]),
         "b": "gear", "rb": plane([0, 0, 0], [0, 0, -1])},
        {"id": "m_gear_key", "type": "coincident", "a": "key", "ra": plane([b2, kh / 2, 9], [1, 0, 0]),
         "b": "gear", "rb": plane([b2, R_seat + 1, 10], [-1, 0, 0])},
    ]
    seat_gap = (p["bore_d"] - steps[1][1]) / 2
    gear_gap = (z_shaft + shoulder) - H
    contacts = [
        ("bearing_a", "housing", 0.0, "outer ring in its Ø47 seat"),
        ("bearing_b", "housing", 0.0, "outer ring in its Ø47 seat"),
        ("shaft", "bearing_a", 0.0, "journal in the inner ring, collar against it"),
        ("shaft", "bearing_b", 0.0, "journal in the inner ring"),
        ("shaft", "housing", seat_gap, "Ø26 collar in the Ø30 bore: (30 − 26) / 2"),
        ("key", "shaft", 0.0, "key in its keyway"),
        ("key", "gear", 0.0, "key drives the hub keyway side"),
        ("gear", "housing", gear_gap, "gear face above the housing top: 69 − 58"),
    ]
    joints = [{"id": "j_shaft", "type": "revolute", "name": "Output shaft", "p": [0, 0, 0], "dir": [0, 0, 1],
               "insts": ["shaft", "key", "gear"], "limits": None}]
    motion = [{"name": "full turn", "driver": "j_shaft", "start": 0.0, "end": 360.0, "steps": 6, "collide": []}]
    return Fixture(
        id=ID, title=TITLE, params=dict(p), parts=parts, insts=insts, mates=mates,
        dof=3,  # bearing A spin, bearing B spin, shaft + key + gear spin
        contacts=contacts, joints=joints, motion=motion,
        bom=[("FX-05 bearing housing", 1), (parts["bearing"].name, 2), ("FX-05 output shaft", 1),
             (parts["key"].name, 1), (parts["gear"].name, 1)])
