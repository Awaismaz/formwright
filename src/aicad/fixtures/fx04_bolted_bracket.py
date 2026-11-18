"""FX-04 bolted bracket assembly (original design, generated for Formwright).

Design intent: an aluminium angle bracket that carries a sensor or a light fitting on its upright (Ø8.4 hole for an M8
fixing) is bolted to an aluminium base plate with two M6 through bolts: hex bolt ISO 4017 + washer ISO 7089 under the
head, washer + hex nut ISO 4032 under the plate (Toolbox fasteners). The base plate has four Ø9 corner holes to fix
it to a frame with M8 screws (not part of this fixture).

Frames (mm, Z up): the base plate is the assembly frame (Z = 0 its underside, centred in X and Y). The bracket's
frame has its foot underside at Z = 0, centred on its two foot holes. Every fastener's frame is the Toolbox one
(axis Z, bolt head underside / washer and nut bottom at Z = 0).

Hand values: grip = plate T + foot T = 18; ISO through-bolt rule L ≥ 18 + 1.6 + 1.6 + 5.2 + 2 × 1.0 = 28.4 → M6×30;
protrusion past the nut = 30 − (18 + 3.2 + 5.2) = 3.6 mm; radial clearance of the M6 shank in the Ø6.6 holes 0.3 mm.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from aicad import toolbox
from aicad.assembly import xform
from aicad.fixtures.harness import Feat, Fixture, InstDef, PartDef, perturb

ID = "FX-04"
SLUG = "fx04_bolted_bracket"
TITLE = "Bolted bracket assembly"

PARAMS: dict[str, Any] = {
    "plate_L": 120.0, "plate_W": 80.0, "plate_T": 10.0, "bolt_hole_d": 6.6, "bolt_x": 20.0,
    "corner_hole_d": 9.0, "corner_x": 50.0, "corner_y": 30.0,
    "foot_L": 60.0, "foot_W": 40.0, "foot_T": 8.0, "upright_T": 8.0, "upright_H": 50.0,
    "fix_hole_d": 8.4, "fix_hole_z": 40.0,
    "M": 6, "bolt_L": 30.0,
}


def _cyl_z(r: float, h: float, x: float = 0.0, y: float = 0.0, z0: float = 0.0) -> Any:
    from build123d import Align, Cylinder, Pos

    return Pos(x, y, z0) * Cylinder(r, h, align=(Align.CENTER, Align.CENTER, Align.MIN))


# ------------------------------------------------------------------ parts (parametric scripts)
def base_plate(p: dict[str, Any] = PARAMS) -> Any:
    from build123d import Align, Box

    from aicad import fw

    L, W, T = p["plate_L"], p["plate_W"], p["plate_T"]
    part = fw.feature("Plate", Box(L, W, T, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    for sx in (-1, 1):
        part -= _cyl_z(p["bolt_hole_d"] / 2, T + 0.02, sx * p["bolt_x"], 0, -0.01)
    part = fw.feature("Bracket bolt holes", part)
    for sx in (-1, 1):
        for sy in (-1, 1):
            part -= _cyl_z(p["corner_hole_d"] / 2, T + 0.02, sx * p["corner_x"], sy * p["corner_y"], -0.01)
    part = fw.feature("Corner fixing holes", part)
    part.label = "Base plate"
    return part


def base_plate_feats(p: dict[str, Any] = PARAMS) -> list[Feat]:
    L, W, T = p["plate_L"], p["plate_W"], p["plate_T"]
    hole = math.pi / 4 * p["bolt_hole_d"] ** 2 * T
    corner = math.pi / 4 * p["corner_hole_d"] ** 2 * T
    out = [Feat(L * W * T, (0, 0, T / 2))]
    out += [Feat(-hole, (sx * p["bolt_x"], 0, T / 2)) for sx in (-1, 1)]
    out += [Feat(-corner, (sx * p["corner_x"], sy * p["corner_y"], T / 2)) for sx in (-1, 1) for sy in (-1, 1)]
    return out


def _upright_y(p: dict[str, Any]) -> tuple[float, float]:
    y1 = p["foot_W"] / 2
    return y1 - p["upright_T"], y1


def bracket(p: dict[str, Any] = PARAMS) -> Any:
    from build123d import Align, Box, Pos, Rot

    from aicad import fw

    L, W, T = p["foot_L"], p["foot_W"], p["foot_T"]
    y0, _y1 = _upright_y(p)
    al = (Align.CENTER, Align.MIN, Align.MIN)
    foot = Pos(0, -W / 2, 0) * Box(L, W, T, align=al)
    up = Pos(0, y0, T) * Box(L, p["upright_T"], p["upright_H"], align=al)
    part = fw.feature("Angle body", foot + up)
    for sx in (-1, 1):
        part -= _cyl_z(p["bolt_hole_d"] / 2, T + 0.02, sx * p["bolt_x"], 0, -0.01)
    part = fw.feature("Foot holes", part)
    fix = Pos(0, y0 - 0.01, p["fix_hole_z"]) * Rot(-90, 0, 0) * _cyl_z(p["fix_hole_d"] / 2, p["upright_T"] + 0.02)
    part = fw.feature("Fixing hole", part - fix)
    part.label = "Angle bracket"
    return part


def bracket_feats(p: dict[str, Any] = PARAMS) -> list[Feat]:
    L, W, T, H, U = p["foot_L"], p["foot_W"], p["foot_T"], p["upright_H"], p["upright_T"]
    y0, y1 = _upright_y(p)
    yc = (y0 + y1) / 2
    hole = math.pi / 4 * p["bolt_hole_d"] ** 2 * T
    return [Feat(L * W * T, (0, 0, T / 2)), Feat(L * U * H, (0, yc, T + H / 2)),
            *[Feat(-hole, (sx * p["bolt_x"], 0, T / 2)) for sx in (-1, 1)],
            Feat(-math.pi / 4 * p["fix_hole_d"] ** 2 * U, (0, yc, p["fix_hole_z"]))]


def _bolt_feats(D: int, L: float) -> list[Feat]:
    s, k = toolbox.HEX_HEAD[D]
    return [Feat(math.sqrt(3) / 2 * s * s * k, (0, 0, k / 2)), Feat(math.pi / 4 * D * D * L, (0, 0, -L / 2))]


def _washer_feats(D: int) -> list[Feat]:
    d1, d2, h = toolbox.WASHER[D]
    return [Feat(math.pi / 4 * (d2 * d2 - d1 * d1) * h, (0, 0, h / 2))]


def _nut_feats(D: int) -> list[Feat]:
    s, _k = toolbox.HEX_HEAD[D]
    m = toolbox.NUT_M[D]
    return [Feat(math.sqrt(3) / 2 * s * s * m, (0, 0, m / 2)), Feat(-math.pi / 4 * D * D * m, (0, 0, m / 2))]


def _tb(code: str, **v: Any) -> Any:
    shape, _ = toolbox.build(code, **v)
    shape.label = toolbox.spec(code).title(toolbox.normalize(code, v))
    return shape


# ------------------------------------------------------------------ the assembly
def fixture(p: dict[str, Any] = PARAMS) -> Fixture:
    D, Lb = int(p["M"]), float(p["bolt_L"])
    s, k = toolbox.HEX_HEAD[D]
    _d1, d2, h = toolbox.WASHER[D]
    m = toolbox.NUT_M[D]
    PT, FT = p["plate_T"], p["foot_T"]
    tb = lambda code, **v: toolbox.spec(code).title(toolbox.normalize(code, v))
    parts = {
        "plate": PartDef("plate", "FX-04 base plate", "al_6061", lambda: base_plate(p),
                         (p["plate_L"], p["plate_W"], PT), base_plate_feats(p), params={
                             k_: p[k_] for k_ in ("plate_L", "plate_W", "plate_T", "bolt_hole_d", "bolt_x",
                                                  "corner_hole_d", "corner_x", "corner_y")}),
        "bracket": PartDef("bracket", "FX-04 angle bracket", "al_6061", lambda: bracket(p),
                           (p["foot_L"], p["foot_W"], FT + p["upright_H"]), bracket_feats(p), params={
                               k_: p[k_] for k_ in ("foot_L", "foot_W", "foot_T", "upright_T", "upright_H",
                                                    "fix_hole_d", "fix_hole_z", "bolt_hole_d", "bolt_x")}),
        "bolt": PartDef("bolt", tb("hex_bolt", D=D, L=Lb), "steel_1045", lambda: _tb("hex_bolt", D=D, L=Lb),
                        (2 * s / math.sqrt(3), s, Lb + k), _bolt_feats(D, Lb), kind="toolbox", standard="ISO 4017",
                        designation=f"M{D}×{Lb:g}", params={"code": "hex_bolt", "D": D, "L": Lb},
                        meta={"thread": {"d_nom": D, "p": [0, 0, 0], "d": [0, 0, 1]}}),
        "washer": PartDef("washer", tb("washer", D=D), "steel_1045", lambda: _tb("washer", D=D), (d2, d2, h),
                          _washer_feats(D), kind="toolbox", standard="ISO 7089", designation=f"M{D}",
                          params={"code": "washer", "D": D}),
        "nut": PartDef("nut", tb("hex_nut", D=D), "steel_1045", lambda: _tb("hex_nut", D=D),
                       (2 * s / math.sqrt(3), s, m), _nut_feats(D), kind="toolbox", standard="ISO 4032",
                       designation=f"M{D}", params={"code": "hex_nut", "D": D}),
    }
    I = xform.ident()
    tr = xform.translate
    Z = ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    insts = [InstDef("plate", "plate", I, I, fixed=True),
             InstDef("bracket", "bracket", tr((0, 0, PT)), perturb(tr((0, 0, PT)), 1))]
    mates: list[dict[str, Any]] = [
        {"id": "m_foot", "type": "coincident", "a": "plate", "ra": {"kind": "plane", "p": [0, 0, PT], "v": [0, 0, 1]},
         "b": "bracket", "rb": {"kind": "plane", "p": [0, 0, 0], "v": [0, 0, -1]}}]
    contacts: list[tuple[str, str, float, str]] = [
        ("bracket", "plate", 0.0, "bracket foot sits on the plate")]
    threads = []
    for n, sx in enumerate((1, -1), start=1):
        x = sx * p["bolt_x"]
        ax = {"kind": "axis", "p": [x, 0, 0], "v": [0, 0, 1], "r": p["bolt_hole_d"] / 2}
        own = {"kind": "axis", "p": [0, 0, 0], "v": [0, 0, 1]}
        mates.append({"id": f"m_hole{n}", "type": "concentric", "a": "plate", "ra": ax, "b": "bracket",
                      "rb": {**ax}})
        wt, b, wb, nt = f"washer_top{n}", f"bolt{n}", f"washer_nut{n}", f"nut{n}"
        k0 = 2 + 4 * (n - 1)
        poses = {wt: tr((x, 0, PT + FT)), b: tr((x, 0, PT + FT + h)), wb: tr((x, 0, -h)), nt: tr((x, 0, -h - m))}
        insts += [InstDef(wt, "washer", poses[wt], perturb(poses[wt], k0), free_axis=Z),
                  InstDef(b, "bolt", poses[b], perturb(poses[b], k0 + 1), free_axis=Z),
                  InstDef(wb, "washer", poses[wb], perturb(poses[wb], k0 + 2), free_axis=Z),
                  InstDef(nt, "nut", poses[nt], perturb(poses[nt], k0 + 3), free_axis=Z)]
        mates += [
            {"id": f"m_{wt}_axis", "type": "concentric", "a": "bracket", "ra": ax, "b": wt, "rb": own},
            {"id": f"m_{wt}_seat", "type": "coincident", "a": "bracket",
             "ra": {"kind": "plane", "p": [x, 0, FT], "v": [0, 0, 1]}, "b": wt,
             "rb": {"kind": "plane", "p": [0, 0, 0], "v": [0, 0, -1]}},
            {"id": f"m_{b}_axis", "type": "concentric", "a": wt, "ra": own, "b": b, "rb": own},
            {"id": f"m_{b}_head", "type": "coincident", "a": wt, "ra": {"kind": "plane", "p": [0, 0, h], "v": [0, 0, 1]},
             "b": b, "rb": {"kind": "plane", "p": [0, 0, 0], "v": [0, 0, -1]}},
            {"id": f"m_{wb}_axis", "type": "concentric", "a": "plate", "ra": ax, "b": wb, "rb": own},
            {"id": f"m_{wb}_seat", "type": "coincident", "a": "plate",
             "ra": {"kind": "plane", "p": [x, 0, 0], "v": [0, 0, -1]}, "b": wb,
             "rb": {"kind": "plane", "p": [0, 0, h], "v": [0, 0, 1]}},
            {"id": f"m_{nt}_axis", "type": "concentric", "a": b, "ra": own, "b": nt, "rb": own},
            {"id": f"m_{nt}_seat", "type": "coincident", "a": wb, "ra": {"kind": "plane", "p": [0, 0, 0], "v": [0, 0, -1]},
             "b": nt, "rb": {"kind": "plane", "p": [0, 0, m], "v": [0, 0, 1]}},
        ]
        clear = (p["bolt_hole_d"] - D) / 2
        contacts += [(b, "plate", clear, "M6 shank centred in the Ø6.6 hole: (6.6 − 6) / 2"),
                     (b, "bracket", clear, "same clearance in the bracket foot"),
                     (b, wt, 0.0, "head bears on the washer"),
                     (wb, "plate", 0.0, "washer under the plate"),
                     (nt, wb, 0.0, "nut bears on the washer")]
        threads.append((b, nt))
    return Fixture(
        id=ID, title=TITLE, params=dict(p), parts=parts, insts=insts, mates=mates,
        dof=8,  # each washer, bolt and nut keeps its spin about its own axis: 2 × (2 + 1 + 1)
        contacts=contacts, allowed_thread=threads,
        bom=[("FX-04 base plate", 1), ("FX-04 angle bracket", 1), (parts["washer"].name, 4),
             (parts["bolt"].name, 2), (parts["nut"].name, 2)],
        extra=_extra)


def _extra(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Fastener length rule (ASM-013) and the measured protrusion at the solved placements."""
    from aicad.assembly import fasteners
    from aicad.fixtures.harness import _check

    p = ctx["fx"].params
    D, Lb = int(p["M"]), float(p["bolt_L"])
    grip = p["plate_T"] + p["foot_T"]
    rule = fasteners.through_length(D, grip, True, True)
    out = [_check("FX-04/bolt-length", "bolt length = through-joint rule (grip 18 → M6×30)",
                  rule["L"] == Lb and abs(rule["L_min"] - 28.4) < 1e-9, rule_L=rule["L"], L_min=rule["L_min"],
                  chosen=Lb)]
    for n in (1, 2):
        Tb, Tn = ctx["poses"][f"bolt{n}"], ctx["poses"][f"nut{n}"]
        tip = xform.pt(Tb, (0, 0, -Lb))
        nut_face = xform.pt(Tn, (0, 0, 0))
        prot = float(np.dot(nut_face - tip, xform.vec(Tb, (0, 0, 1))))
        out.append(_check(f"FX-04/protrusion{n}", f"bolt {n} protrudes past its nut by 3.6 mm (≥ 2 pitches)",
                          abs(prot - rule["protrusion"]) < 1e-4 and abs(prot - 3.6) < 1e-4
                          and prot >= 2 * fasteners.pitch(D), measured_mm=round(prot, 6),
                          rule_mm=rule["protrusion"]))
    return out
