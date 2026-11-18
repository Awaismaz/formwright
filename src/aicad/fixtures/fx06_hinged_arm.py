"""FX-06 hinged arm on a clevis base (original design, generated for Formwright).

Design intent: an inspection arm (a flap or lever) swings about a Ø8 hardened pin in a two-lug clevis base that is
screwed down through two Ø6.6 holes; the arm's far end has a Ø8.4 hole to hang a load or a gas spring. The arm is
22 wide between lugs 24 apart (1 mm side clearance each side). The usable swing is limited by the arm meeting the
base plate's top edges: hand values below.

Frames (mm, Z up): the base is the assembly frame (Z = 0 its underside, centred in X and Y); the pin axis runs along X
at Y = 0, Z = 24. The arm's frame has its origin on the pivot, the pin axis along X and the arm along +Y (θ = 0:
horizontal). The pin is a Toolbox dowel (frame: axis Z, one end at Z = 0) turned to lie along X.

Motion range (hand): turning the arm by θ about +X (θ > 0 lifts it), a plate top edge at (Δy, Δz) = (±20, −16) from
the pivot is inside the arm's band (|z_arm| < 6 and 0 < y_arm < 100) when it touches. The arm's lower face meets the
front edge when 20 sin θ + 16 cos θ = 6, θ = asin(6 / √656) − atan2(16, 20) = −25.11°, and (top face, back edge) at
180° − (−25.11°) = 205.11°. Usable range −25.11° .. 205.11° (230.2°); the joint is limited to −20° .. 200°.
Distance from the front edge to the arm's lower face for θ near the limit: 20 sin θ + 16 cos θ − 6.
"""

from __future__ import annotations

import math
from typing import Any

from aicad import toolbox
from aicad.assembly import xform
from aicad.fixtures.harness import Feat, Fixture, InstDef, PartDef, perturb

ID = "FX-06"
SLUG = "fx06_hinged_arm"
TITLE = "Hinged arm with a revolute joint and motion range"

PARAMS: dict[str, Any] = {
    "base_L": 80.0, "base_W": 40.0, "base_T": 8.0, "mount_hole_d": 6.6, "mount_x": 30.0,
    "lug_T": 8.0, "lug_gap": 24.0, "lug_W": 20.0, "lug_top": 30.0, "pivot_z": 24.0,
    "pin_d": 8.0, "pin_L": 40.0,
    "arm_W": 22.0, "arm_L": 100.0, "arm_H": 12.0, "hub_r": 8.0, "end_hole_d": 8.4, "end_hole_y": 90.0,
    "limits": [-20.0, 200.0],
}


def _cyl_x(r: float, L: float, x0: float, y: float, z: float) -> Any:
    from build123d import Align, Cylinder, Pos, Rot

    return Pos(x0, y, z) * Rot(0, 90, 0) * Cylinder(r, L, align=(Align.CENTER, Align.CENTER, Align.MIN))


def _cyl_z(r: float, h: float, x: float = 0.0, y: float = 0.0, z0: float = 0.0) -> Any:
    from build123d import Align, Cylinder, Pos

    return Pos(x, y, z0) * Cylinder(r, h, align=(Align.CENTER, Align.CENTER, Align.MIN))


# ------------------------------------------------------------------ base (plate + two lugs)
def _lug_x(p: dict[str, Any]) -> tuple[float, float]:
    x0 = p["lug_gap"] / 2
    return x0, x0 + p["lug_T"]


def base(p: dict[str, Any] = PARAMS) -> Any:
    from build123d import Align, Box, Pos

    from aicad import fw

    L, W, T = p["base_L"], p["base_W"], p["base_T"]
    part = fw.feature("Base plate", Box(L, W, T, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    x0, x1 = _lug_x(p)
    h = p["lug_top"] - T
    for sx in (-1, 1):
        part += Pos(sx * (x0 + x1) / 2, 0, T) * Box(p["lug_T"], p["lug_W"], h,
                                                    align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = fw.feature("Clevis lugs", part)
    part = fw.feature("Pin hole", part - _cyl_x(p["pin_d"] / 2, 2 * x1 + 2, -x1 - 1, 0, p["pivot_z"]))
    for sx in (-1, 1):
        part -= _cyl_z(p["mount_hole_d"] / 2, T + 0.02, sx * p["mount_x"], 0, -0.01)
    part = fw.feature("Mounting holes", part)
    part.label = "Clevis base"
    return part


def base_feats(p: dict[str, Any] = PARAMS) -> list[Feat]:
    L, W, T = p["base_L"], p["base_W"], p["base_T"]
    x0, x1 = _lug_x(p)
    h = p["lug_top"] - T
    xc = (x0 + x1) / 2
    lug = p["lug_T"] * p["lug_W"] * h
    pin = math.pi / 4 * p["pin_d"] ** 2 * p["lug_T"]
    mount = math.pi / 4 * p["mount_hole_d"] ** 2 * T
    return [Feat(L * W * T, (0, 0, T / 2)),
            *[Feat(lug, (sx * xc, 0, T + h / 2)) for sx in (-1, 1)],
            *[Feat(-pin, (sx * xc, 0, p["pivot_z"])) for sx in (-1, 1)],
            *[Feat(-mount, (sx * p["mount_x"], 0, T / 2)) for sx in (-1, 1)]]


# ------------------------------------------------------------------ arm
def arm(p: dict[str, Any] = PARAMS) -> Any:
    from build123d import Align, Box

    from aicad import fw

    W, L, H, r = p["arm_W"], p["arm_L"], p["arm_H"], p["hub_r"]
    body = Box(W, L, H, align=(Align.CENTER, Align.MIN, Align.CENTER))
    part = fw.feature("Arm and hub", body + _cyl_x(r, W, -W / 2, 0, 0))
    part = fw.feature("Pivot bore", part - _cyl_x(p["pin_d"] / 2, W + 0.02, -W / 2 - 0.01, 0, 0))
    part = fw.feature("End hole", part - _cyl_z(p["end_hole_d"] / 2, H + 0.02, 0, p["end_hole_y"], -H / 2 - 0.01))
    part.label = "Arm"
    return part


def arm_feats(p: dict[str, Any] = PARAMS) -> list[Feat]:
    W, L, H, r = p["arm_W"], p["arm_L"], p["arm_H"], p["hub_r"]
    h = H / 2
    ov_area = (h * math.sqrt(r * r - h * h) + r * r * math.asin(h / r))   # ∫_{-h}^{h} sqrt(r² − z²) dz
    ov_ymom = (r * r * H - 2 * h ** 3 / 3) / 2                            # ∫ (r² − z²) / 2 dz
    return [Feat(W * L * H, (0, L / 2, 0)), Feat(W * math.pi * r * r, (0, 0, 0)),
            Feat(-W * ov_area, (0, ov_ymom / ov_area, 0)),
            Feat(-W * math.pi / 4 * p["pin_d"] ** 2, (0, 0, 0)),
            Feat(-H * math.pi / 4 * p["end_hole_d"] ** 2, (0, p["end_hole_y"], 0))]


def _pin_feats(D: float, L: float) -> list[Feat]:
    c = round(min(0.2 * D, 1.0), 3)  # Toolbox dowel end chamfer
    ring = 2 * math.pi * (c * c / 2) * (D / 2 - c / 3)
    return [Feat(math.pi / 4 * D * D * L - 2 * ring, (0, 0, L / 2))]


def contact_angles(p: dict[str, Any] = PARAMS) -> tuple[float, float]:
    """(lowest, highest) arm angle in degrees before it touches the base plate's top edges (hand formula)."""
    dy = p["base_W"] / 2
    dz = p["base_T"] - p["pivot_z"]
    R = math.hypot(dy, dz)
    lo = math.degrees(math.asin((p["arm_H"] / 2) / R) - math.atan2(-dz, dy))
    return lo, 180.0 - lo


def edge_inside_arm(theta_deg: float, p: dict[str, Any] = PARAMS) -> bool:
    """Hand collision predicate: a plate top edge strictly inside the arm's band at angle θ."""
    th = math.radians(theta_deg)
    dz = p["base_T"] - p["pivot_z"]
    for dy in (p["base_W"] / 2, -p["base_W"] / 2):
        y = dy * math.cos(th) + dz * math.sin(th)
        z = -dy * math.sin(th) + dz * math.cos(th)
        if abs(z) < p["arm_H"] / 2 and 0 < y < p["arm_L"]:
            return True
    return False


# ------------------------------------------------------------------ the assembly
def fixture(p: dict[str, Any] = PARAMS) -> Fixture:
    D, Lp = p["pin_d"], p["pin_L"]
    x0, x1 = _lug_x(p)
    zp = p["pivot_z"]
    W, L, _H, r = p["arm_W"], p["arm_L"], p["arm_H"], p["hub_r"]

    def build_pin() -> Any:
        s, _ = toolbox.build("dowel", D=D, L=Lp)
        s.label = toolbox.spec("dowel").title({"D": D, "L": Lp})
        return s

    parts = {
        "base": PartDef("base", "FX-06 clevis base", "al_6061", lambda: base(p), (p["base_L"], p["base_W"],
                                                                                  p["lug_top"]),
                        base_feats(p), params={k: p[k] for k in ("base_L", "base_W", "base_T", "mount_hole_d",
                                                                   "mount_x", "lug_T", "lug_gap", "lug_W", "lug_top",
                                                                   "pivot_z", "pin_d")}),
        "arm": PartDef("arm", "FX-06 arm", "al_6061", lambda: arm(p), (W, L + r, 2 * r), arm_feats(p),
                       params={k: p[k] for k in ("arm_W", "arm_L", "arm_H", "hub_r", "pin_d", "end_hole_d",
                                                 "end_hole_y")}),
        "pin": PartDef("pin", toolbox.spec("dowel").title({"D": D, "L": Lp}), "steel_1045", build_pin, (D, D, Lp),
                       _pin_feats(D, Lp), kind="toolbox", standard="ISO 8734 (envelope)", designation=f"Ø{D:g}×{Lp:g}",
                       params={"code": "dowel", "D": D, "L": Lp}),
    }
    I = xform.ident()
    T_arm = xform.translate((0, 0, zp))
    T_pin = xform.translate((-Lp / 2, 0, zp)) @ xform.make(xform.rot([0, 1, 0], math.pi / 2), (0, 0, 0))
    insts = [InstDef("base", "base", I, I, fixed=True),
             InstDef("pin", "pin", T_pin, perturb(T_pin, 1), free_axis=((0, 0, 0), (0, 0, 1))),
             InstDef("arm", "arm", T_arm, perturb(T_arm, 2), free_axis=((0, 0, 0), (1, 0, 0)))]
    pin_axis = {"kind": "axis", "p": [0, 0, zp], "v": [1, 0, 0], "r": D / 2}
    mates = [
        {"id": "m_pin_axis", "type": "concentric", "a": "base", "ra": pin_axis, "b": "pin",
         "rb": {"kind": "axis", "p": [0, 0, 0], "v": [0, 0, 1]}},
        {"id": "m_pin_flush", "type": "flush", "a": "base", "ra": {"kind": "plane", "p": [-x1, 0, zp], "v": [-1, 0, 0]},
         "b": "pin", "rb": {"kind": "plane", "p": [0, 0, 0], "v": [0, 0, -1]}},
        {"id": "m_arm_axis", "type": "concentric", "a": "base", "ra": pin_axis, "b": "arm",
         "rb": {"kind": "axis", "p": [0, 0, 0], "v": [1, 0, 0]}},
        {"id": "m_arm_gap", "type": "distance", "a": "base", "ra": {"kind": "plane", "p": [-x0, 0, zp], "v": [1, 0, 0]},
         "b": "arm", "rb": {"kind": "plane", "p": [-W / 2, L / 2, 0], "v": [-1, 0, 0]}, "value": x0 - W / 2},
    ]
    side = x0 - W / 2
    contacts = [("pin", "base", 0.0, "pin in the lug bores"), ("arm", "pin", 0.0, "arm bore on the pin"),
                ("arm", "base", side, "side clearance between the arm and a lug: (24 − 22) / 2")]
    lo_lim, hi_lim = p["limits"]
    joints = [{"id": "j_hinge", "type": "revolute", "name": "Hinge", "p": [0, 0, zp], "dir": [1, 0, 0],
               "insts": ["arm"], "limits": [lo_lim, hi_lim]}]
    within = {"name": "within limits", "driver": "j_hinge", "start": lo_lim, "end": hi_lim, "steps": 22}
    beyond = {"name": "beyond limits", "driver": "j_hinge", "start": -40.0, "end": 220.0, "steps": 26}
    for case in (within, beyond):
        n = case["steps"]
        vals = [case["start"] + (case["end"] - case["start"]) * k / n for k in range(n + 1)]
        case["collide"] = [round(v, 6) for v in vals if edge_inside_arm(v, p)]
    return Fixture(
        id=ID, title=TITLE, params=dict(p), parts=parts, insts=insts, mates=mates,
        dof=2,  # the pin's spin in its bores and the arm's swing (the hinge)
        contacts=contacts, joints=joints, motion=[within, beyond],
        bom=[("FX-06 clevis base", 1), (parts["pin"].name, 1), ("FX-06 arm", 1)], extra=_extra)


def _extra(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Measured gap between the arm and the plate's front edge near the lower limit = the hand formula."""
    from aicad.assembly import geometry
    from aicad.fixtures.harness import _check, _world

    fx = ctx["fx"]
    p = fx.params
    by = {i.id: i for i in fx.insts}
    lo, hi = contact_angles(p)
    out = [_check("FX-06/range", "usable swing from the hand formula covers the joint limits",
                  lo < p["limits"][0] and hi > p["limits"][1], contact_lo_deg=round(lo, 4), contact_hi_deg=round(hi, 4),
                  limits=p["limits"])]
    base_w = _world(ctx["shapes"]["base"], by["base"].T)
    rows = []
    for th in (-24.0, -25.0):
        M = xform.about(xform.rot([1, 0, 0], math.radians(th)), [0, 0, p["pivot_z"]])
        arm_w = _world(ctx["shapes"]["arm"], M @ by["arm"].T)
        got, _, _ = geometry.min_distance(arm_w, base_w)
        t = math.radians(th)
        want = p["base_W"] / 2 * math.sin(t) + (p["pivot_z"] - p["base_T"]) * math.cos(t) - p["arm_H"] / 2
        rows.append({"theta": th, "got_mm": round(got, 9), "hand_mm": round(want, 9), "ok": abs(got - want) < 1e-4})
    out.append(_check("FX-06/edge-gap", "arm-to-plate-edge gap near the lower limit = 20 sin θ + 16 cos θ − 6",
                      all(r["ok"] for r in rows), rows=rows))
    return out
