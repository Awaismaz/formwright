"""Smart assembly of housing-less mechanisms (ASM-010 / ASM-019): gear trains and shaft-and-bearing lines.

The founder's test case (2026-11-19): a 1:3 spur pair m2 z20 / z60, two Ø20 shafts, four 6204 bearings, no housing.

Hand values (from the inputs, never measured from the built shapes):
- centre distance a = m (z1 + z2) / 2 = 2 × (20 + 60) / 2 = 80 mm; ratio -z1/z2 = -1/3;
- Toolbox shaft Ø20 × 120 (z 0..120, 1 mm end chamfers, keyway centred at z = 60): the base, axis along +Y, the
  pinion's mid-plane on Y = 0, so the shaft runs y = -60..60 and its local origin sits at (0, -60, 0);
- Toolbox gears B = 15 (default) centred on the keyway: z 52.5..67.5 on their shaft = y -7.5..7.5;
- 6204 = 20 × 47 × 14; no shoulders on a plain shaft, so flush with the shaft ends: y -60..-46 and 46..60;
- tooth phase of the z60 at the line of centres (+X): the pinion shows a tooth (phase 0, u = 0), so the wheel
  shows a space: v = 1/2, phase = (180° - 0.5 × 6°) mod 6° = 3° (half its 6° pitch);
- stepped shaft Ø20 × 30 + Ø30 × 60 + Ø20 × 30: gears bored Ø30 sit on the Ø30 seat (z 52.5..67.5), the
  bearings against the shoulders: z 16..30 and 90..104.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from test_assembly import app_client  # noqa: F401  (fixture)
from test_assembly_ai import _project, _setup, stepped_shaft

from aicad.assembly import fitz, geometry, solver, trains, xform

PAIR = "a spur gear m2 20 teeth, a spur gear m2 60 teeth, two Ø20 shafts and four 6204 bearings"


def _T(v: dict[str, Any], iid: str) -> np.ndarray:
    return xform.from12(next(i for i in v["instances"] if i["id"] == iid)["T"])


def _named(v: dict[str, Any], prefix: str) -> list[str]:
    return [i["id"] for i in v["instances"] if i["name"].startswith(prefix)]


def _run(c: Any, aid: str, text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    pl = c.post(f"/api/m/assembly/assemblies/{aid}/smart/plan", json={"text": text})
    assert pl.status_code == 200, pl.text
    v = c.post(f"/api/m/assembly/assemblies/{aid}/smart/run", json={"items": pl.json()["items"]})
    assert v.status_code == 200, v.text
    return pl.json(), v.json()


# ----------------------------------------------------------------------------- pure
def test_tooth_phase_rolls_with_the_mesh() -> None:
    assert trains.phase(0.0, 0.0, 20, 60) == pytest.approx(3.0)          # half of the wheel's 6° pitch
    assert trains.phase(0.0, 0.0, 20, 20) == pytest.approx(9.0)          # 18° pitch: (180 - 9) mod 18 = 9
    # rolling contact: turning the pinion by α turns the wheel by -α z1/z2, and the phase rule follows it
    za, zb = 18, 41
    for alpha in (0.0, 3.3, 7.0, 13.9, 19.99):
        got = trains.phase(25.0, alpha, za, zb)
        want = (trains.phase(25.0, 0.0, za, zb) - alpha * za / zb) % (360 / zb)
        assert min(abs(got - want), 360 / zb - abs(got - want)) < 1e-9


def test_gear_mesh_mate_residual_jacobian_prealign() -> None:
    a = solver.Ref("axis", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 10.0)
    b = solver.Ref("axis", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 10.0)
    m = solver.MateSpec("m1", "gear", "A", a, "B", b, value=80.0)
    Ta = xform.ident()
    Tb = xform.translate([80 * math.cos(0.4), 80 * math.sin(0.4), 5.0])     # parallel, 80 apart: satisfied
    assert np.allclose(solver.residual(m, Ta, Tb, 100.0), 0, atol=1e-12) and m.eqs() == 3
    assert solver.mate_error(m, Ta, Tb) == pytest.approx((0.0, 0.0), abs=1e-9)
    # off by 7 mm and tilted: prealign moves b the smallest way back onto the 80 mm cylinder
    Tb2 = xform.make(xform.rot([1, 0, 0], 0.05), [87.0, 0.0, 0.0])
    poses = {"A": Ta, "B": Tb2}
    T = solver.prealign(m, poses, "B")
    assert solver.mate_error(m, Ta, T) == pytest.approx((0.0, 0.0), abs=1e-9)
    # the analytic Jacobian rows match finite differences
    insts = {"A": solver.Inst("A", Ta), "B": solver.Inst("B", Tb2, ref_point=(0.0, 0.0, 0.0))}
    J = solver._mate_blocks(m, poses, insts, 100.0)["B"]
    r0 = solver.residual(m, Ta, Tb2, 100.0)
    for k in range(6):
        x = np.zeros(6)
        x[k] = 1e-6
        Tp = solver._delta(x, xform.pt(Tb2, (0, 0, 0)), 100.0) @ Tb2
        col = (solver.residual(m, Ta, Tp, 100.0) - r0) / 1e-6
        assert np.allclose(col[[0, 1, 2]], J[[0, 1, 2], k], atol=1e-4)
        assert col[3] == pytest.approx(J[3, k], abs=1e-4)


def _toolbox_shaft_geom(L: float = 120.0) -> dict[str, Any]:
    ends = {"lo": {"face": 7, "shoulder": False, "t": 0.0, "chamfer": 1.0},
            "hi": {"face": 8, "shoulder": False, "t": L, "chamfer": 1.0}}
    seat = {"faces": [0], "d": 20.0, "r": 10.0, "lo": 1.0, "hi": L - 1, "length": L - 2, "ends": ends}
    return {"p": np.zeros(3), "v": np.array([0.0, 0.0, 1.0]), "seats": [seat], "lo_end": (0.0, 7), "hi_end": (L, 8),
            "key_c": L / 2, "t_lo": 0.0, "t_hi": L, "d": 20.0}


def test_stack_plain_shaft_stepped_shaft_and_no_room() -> None:
    st = trains.stack(_toolbox_shaft_geom(), [{"w": 15.0, "bore": 20.0}], 2, {"w": 14.0, "bore": 20.0})
    assert st["hubs"][0]["t0"] == pytest.approx(52.5)                   # centred on the keyway at 60
    assert [(b["t0"], b["how"], b["side"]) for b in st["bearings"]] == [(0.0, "end", "lo"), (106.0, "end", "hi")]
    assert st["problems"] == []
    # a gear and a pulley side by side, 2 mm apart, centred together: 15 + 2 + 20 = 37 → 41.5..56.5, 58.5..78.5
    st = trains.stack(_toolbox_shaft_geom(), [{"w": 15.0, "bore": 20.0}, {"w": 20.0, "bore": 20.0}], 2,
                      {"w": 14.0, "bore": 20.0})
    assert [h["t0"] for h in st["hubs"]] == pytest.approx([41.5, 58.5])
    # stepped: Ø20 0..30 | Ø30 30..90 | Ø20 90..120; shoulders face the Ø20 journals
    j1 = {"faces": [1], "d": 20.0, "r": 10.0, "lo": 0.0, "hi": 30.0, "length": 30.0,
          "ends": {"lo": {"face": 10, "shoulder": False, "t": 0.0}, "hi": {"face": 11, "shoulder": True, "t": 30.0}}}
    mid = {"faces": [2], "d": 30.0, "r": 15.0, "lo": 30.0, "hi": 90.0, "length": 60.0,
           "ends": {"lo": {"face": 11, "shoulder": False, "t": 30.0}, "hi": {"face": 12, "shoulder": False, "t": 90.0}}}
    j2 = {"faces": [3], "d": 20.0, "r": 10.0, "lo": 90.0, "hi": 120.0, "length": 30.0,
          "ends": {"lo": {"face": 12, "shoulder": True, "t": 90.0}, "hi": {"face": 13, "shoulder": False, "t": 120.0}}}
    sg = {"p": np.zeros(3), "v": np.array([0.0, 0.0, 1.0]), "seats": [mid, j1, j2], "lo_end": (0.0, 10),
          "hi_end": (120.0, 13), "key_c": None, "t_lo": 0.0, "t_hi": 120.0, "d": 30.0}
    st = trains.stack(sg, [{"w": 15.0, "bore": 30.0}], 2, {"w": 14.0, "bore": 20.0})
    assert st["hubs"][0]["t0"] == pytest.approx(52.5)
    assert [(b["t0"], b["how"], b["face"]) for b in st["bearings"]] == [(16.0, "shoulder", 11), (90.0, "shoulder", 12)]
    # a 40 mm shaft: the gear takes 12.5..27.5, a 14 mm bearing can't fit 1 mm clear of it on either side
    st = trains.stack(_toolbox_shaft_geom(40.0), [{"w": 15.0, "bore": 20.0}], 2, {"w": 14.0, "bore": 20.0})
    assert st["bearings"] == [] and [p[0] for p in st["problems"]] == ["no_room_for_bearing"] * 2


def test_plan_reads_the_gear_pair_as_a_train(tmp_path: Path) -> None:
    doc = {"instances": [], "mates": [], "groups": []}
    pl = fitz.plan(tmp_path, doc, "a spur gear m2 20 teeth, a spur gear m2 60 teeth, two Ø20 shafts, four bearings", [])
    by = {i["title"]: i for i in pl["items"]}
    assert [i["action"] for i in pl["items"]] == ["train", "train", "train", "seat"]
    pin, wheel = by["Spur gear m2 z20"], by["Spur gear m2 z60"]
    assert pin["params"]["BORE"] == 20 and wheel["params"]["BORE"] == 20             # bored to the Ø20 shafts
    assert "at 80 mm = m(z1+z2)/2" in wheel["plan"] and "shaft 2" in wheel["plan"]
    br = by["Ball bearing 6204"]                                                      # sized from the Ø20 shafts
    assert br["params"] == {"SERIES": 6204} and br["qty"] == 4 and br["codes"] == []
    assert "Input shaft: the base" in by["Shaft Ø20×120 with keyway"]["plan"]
    # an odd count is flagged before anything is inserted
    pl = fitz.plan(tmp_path, doc, "a spur gear m2 20 teeth, a spur gear m3 30 teeth, two Ø20 shafts, five 6204 bearings", [])
    codes = {c for i in pl["items"] for c in i.get("codes") or []}
    assert codes == {"module_mismatch", "bearing_spare"}


def test_phase_rule_meshes_off_axis_where_the_old_rule_clashes(tmp_path: Path) -> None:
    """Two Toolbox gears meshing along 40° (not on +X) with the first turned by 0.3 of a pitch: the phase rule
    gives zero interference; the previous rule (v = u + 1/2) puts teeth into teeth."""
    from build123d import export_step

    from aicad import toolbox

    za, zb, m, b = 20, 30, 2.0, 4.0
    a = m * (za + zb) / 2
    rows = []
    for name, z in (("p", za), ("w", zb)):
        s, _ = toolbox.build("spur_gear", M=m, Z=z, B=b, BORE=8)
        f = tmp_path / f"{name}.step"
        export_step(s, str(f))
        bb = geometry.load(f).bounding_box()
        rows.append({"id": name, "step": str(f), "bbox": [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z]})
    th, pa = 40.0, 0.3 * 360 / za
    c = [a * math.cos(math.radians(th)), a * math.sin(math.radians(th)), 0.0]

    def clash(phase_b: float) -> float:
        rows[0]["T"] = xform.to12(xform.make(xform.rot([0, 0, 1], math.radians(pa)), [0, 0, 0]))
        rows[1]["T"] = xform.to12(xform.make(xform.rot([0, 0, 1], math.radians(phase_b)), c))
        res = geometry.interference(rows)
        return sum(p["volume_mm3"] for p in res["pairs"] if p["kind"] == "interference")

    assert clash(trains.phase(th, pa, za, zb)) == 0
    u = ((th - pa) % (360 / za)) / (360 / za)
    old = ((th + 180) - ((u + 0.5) % 1.0) * 360 / zb) % (360 / zb)
    assert clash(old) > 1.0


# ----------------------------------------------------------------------------- kernel (app, worker)
def test_gear_pair_with_shafts_and_bearings(app_client: Any) -> None:  # noqa: F811
    c = app_client
    _setup(c, "pair@x.com")
    aid = c.post("/api/m/assembly/assemblies", json={"name": "1:3 pair"}).json()["assembly"]["id"]
    _pl, v = _run(c, aid, PAIR)
    res = v["result"]
    assert res["placed_loose"] == 0 and res["clashes"] == [], res["log"]
    assert [o["code"] for o in res["outcomes"]] == ["shafts_not_held"]
    assert set(res["timings"]) == {"total_s", "train_s", "solve_s", "interference_s"}
    s1, s2 = _named(v, "Shaft")
    g1, g2 = _named(v, "Spur gear m2 z20")[0], _named(v, "Spur gear m2 z60")[0]
    bearings = _named(v, "Ball bearing 6204")
    assert len(v["instances"]) == 8 and len(bearings) == 4
    base = next(i for i in v["instances"] if i["id"] == s1)
    assert base["fixed"] and not any(i["fixed"] for i in v["instances"] if i["id"] != s1)
    Y = np.array([0.0, 1.0, 0.0])
    for iid in (s1, s2, g1, g2, *bearings):
        assert xform.vec(_T(v, iid), (0, 0, 1)) == pytest.approx(Y, abs=1e-9)        # every axis along +Y
    assert xform.pt(_T(v, s1), (0, 0, 0)) == pytest.approx([0, -60, 0], abs=1e-9)
    assert xform.pt(_T(v, s2), (0, 0, 0)) == pytest.approx([80, -60, 0], abs=1e-9)   # parallel, 80 mm apart
    assert xform.pt(_T(v, g1), (0, 0, 0)) == pytest.approx([0, -7.5, 0], abs=1e-9)   # mid-plane on Y = 0
    assert xform.pt(_T(v, g2), (0, 0, 0)) == pytest.approx([80, -7.5, 0], abs=1e-9)  # coplanar with the pinion
    x2 = xform.vec(_T(v, g2), (1, 0, 0))
    assert math.degrees(math.atan2(-x2[2], x2[0])) == pytest.approx(3.0, abs=1e-9)   # half a pitch about +Y
    lows = sorted((round(float(xform.pt(_T(v, b), (0, 0, 0))[0]), 6), round(float(xform.pt(_T(v, b), (0, 0, 0))[1]), 6))
                  for b in bearings)
    assert lows == [(0, -60), (0, 46), (80, -60), (80, 46)]                         # y -60..-46 and 46..60
    assert all(m["status"] == "ok" for m in v["mates"])
    gm = [m for m in v["mates"] if m["type"] == "gear"]
    assert len(gm) == 1 and gm[0]["value"] == pytest.approx(80.0) and gm[0]["label"] == "Gear mesh"
    assert v["analysis"]["interference"]["count"] == 0
    # motion: two revolute joints (shaft + its gear) and the mesh at -1/3; two pinion pitches turn clean
    js = v["joints"]
    rev = [j for j in js if j["type"] == "revolute"]
    assert sorted(len(j["insts"]) for j in rev) == [2, 2]
    gj = next(j for j in js if j["type"] == "gear")
    assert gj["ratio"] == pytest.approx(-1 / 3) and gj["teeth"] == [20, 60]
    mo = c.post(f"/api/m/assembly/assemblies/{aid}/motion", json={"start": 0, "end": 36, "steps": 6}).json()["motion"]
    assert mo["colliding_steps"] == [], mo["summary"]
    last = mo["steps"][-1]
    assert last["values"][gj["b"]] == pytest.approx(-12.0)                          # 36° × -20/60


def test_three_gear_train_and_honest_codes(app_client: Any) -> None:  # noqa: F811
    c = app_client
    _setup(c, "train3@x.com")
    aid = c.post("/api/m/assembly/assemblies", json={"name": "3 gears"}).json()["assembly"]["id"]
    _pl, v = _run(c, aid, "a spur gear m2 20 teeth, a spur gear m2 40 teeth, a spur gear m2 30 teeth, three Ø20 "
                          "shafts and six 6204 bearings")
    res = v["result"]
    assert res["placed_loose"] == 0 and res["clashes"] == [], res["log"]
    shafts = _named(v, "Shaft")
    xs = sorted(round(float(xform.pt(_T(v, s), (0, 0, 0))[0]), 6) for s in shafts)
    assert xs == [0, 60, 130]                                    # 2(20+40)/2 = 60, then 2(40+30)/2 = 70
    ratios = sorted(round(j["ratio"], 9) for j in v["joints"] if j["type"] == "gear")
    assert ratios == sorted([round(-20 / 40, 9), round(-40 / 30, 9)])
    assert v["analysis"]["interference"]["count"] == 0
    # one gear for two shafts, a module 3 gear that can't mesh, five bearings: each named with its code
    aid = c.post("/api/m/assembly/assemblies", json={"name": "odd"}).json()["assembly"]["id"]
    _pl, v = _run(c, aid, "a spur gear m2 20 teeth, a spur gear m3 30 teeth, two Ø20 shafts, five 6204 bearings")
    codes = [o["code"] for o in v["result"]["outcomes"]]
    assert codes.count("module_mismatch") == 4                 # the m3 gear, shaft 2 and its two bearings
    assert codes.count("bearing_spare") == 1
    assert all(o["inst"] and o["text"] for o in v["result"]["outcomes"] if o["code"] != "shafts_not_held")
    # five loose parts are a measured placement problem: the clash check measures those parts at once (targeted,
    # PD-73) and the whole check follows in the background, so the response carries Fitz's clashes, not an analysis
    assert v["result"]["placed_loose"] == 5 and v["result"]["clashes"] == []
    assert v["result"]["checks"]["policy"]["exact"] == "targeted"


def pulley(out: Path) -> None:
    from build123d import Align, Cylinder, Pos
    from test_assembly_ai import _write

    rim = Cylinder(40, 20, align=(Align.CENTER, Align.CENTER, Align.MIN)) - \
        Pos(0, 0, 4) * Cylinder(32, 12, align=(Align.CENTER, Align.CENTER, Align.MIN))
    hub = Cylinder(18, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))
    p = (rim + hub) - Pos(0, 0, -1) * Cylinder(10, 22, align=(Align.CENTER, Align.CENTER, Align.MIN))
    _write(out, p, "Pulley", "Aluminium 6061-T6", "7001")


def test_shaft_line_with_a_pulley_and_stepped_user_shafts(app_client: Any) -> None:  # noqa: F811
    c = app_client
    _setup(c, "line@x.com")
    _project(c, "Pulley", pulley)
    aid = c.post("/api/m/assembly/assemblies", json={"name": "line"}).json()["assembly"]["id"]
    _pl, v = _run(c, aid, "the pulley from my projects, a Ø20 shaft and two 6204 bearings")
    res = v["result"]
    assert res["placed_loose"] == 0 and res["clashes"] == [], res["log"]
    (_s,), (p,), bs = _named(v, "Shaft"), _named(v, "Pulley"), _named(v, "Ball bearing 6204")
    # the pulley (20 wide, bore Ø20) centred on the keyway: z 50..70 of the shaft = y -10..10
    lo_p = xform.pt(_T(v, p), (0, 0, 0))
    assert abs(lo_p[1]) == pytest.approx(10.0, abs=1e-6) and lo_p[0] == pytest.approx(0, abs=1e-9)
    ys = sorted(round(float(xform.pt(_T(v, b), (0, 0, 0))[1]), 6) for b in bs)
    assert ys == [-60, 46]
    assert v["analysis"]["interference"]["count"] == 0 and all(m["status"] == "ok" for m in v["mates"])
    # the founder's pair on shafts the user designed: stepped Ø20 / Ø30 / Ø20
    _project(c, "Stepped Shaft", stepped_shaft)
    aid = c.post("/api/m/assembly/assemblies", json={"name": "stepped"}).json()["assembly"]["id"]
    _pl, v = _run(c, aid, "a spur gear m2 20 teeth, a spur gear m2 60 teeth, two stepped shafts from my projects, "
                          "four 6204 bearings")
    res = v["result"]
    # the gears are bored Ø30 for the Ø30 middle seat at run time (a Ø20 bore there would be a clash below)
    assert res["placed_loose"] == 0 and res["clashes"] == [], res["log"]
    s1, s2 = _named(v, "Stepped Shaft")
    assert np.linalg.norm(xform.pt(_T(v, s2), (0, 0, 0)) - xform.pt(_T(v, s1), (0, 0, 0))) == pytest.approx(80.0)
    T1 = _T(v, s1)
    ts = sorted(round(float((xform.inv(T1) @ np.append(xform.pt(_T(v, b), (0, 0, 0)), 1))[2]), 6)
                for b in _named(v, "Ball bearing 6204")
                if np.linalg.norm(xform.pt(_T(v, b), (0, 0, 0))[[0, 2]] - xform.pt(T1, (0, 0, 0))[[0, 2]]) < 1e-6)
    assert ts == [16, 90]                                        # against the shoulders at z = 30 and z = 90
    assert v["analysis"]["interference"]["count"] == 0 and all(m["status"] == "ok" for m in v["mates"])
