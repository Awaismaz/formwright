"""ASM-011 motion range check and the interference screening (analytic fixtures, kernel in-process)."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from aicad.assembly import AssemblyInputError, geometry, motion, xform


def _write(tmp: Path, name: str, shape: Any) -> dict[str, Any]:
    from build123d import export_step

    p = tmp / f"{name}.step"
    export_step(shape, str(p))
    s = geometry.load(p)
    bb = s.bounding_box()
    return {"id": name, "step": str(p), "T": xform.to12(xform.ident()),
            "bbox": [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z]}


@pytest.fixture(scope="module")
def arm(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """An arm 100 long, 10 wide on a revolute about Z through the origin, and a Ø10 pin at radius 70 on +Y."""
    from build123d import Align, Box, Cylinder, Pos

    tmp = tmp_path_factory.mktemp("arm")
    a = _write(tmp, "arm", Box(100, 10, 10, align=(Align.MIN, Align.CENTER, Align.MIN)))
    p = _write(tmp, "pin", Pos(0, 70, 0) * Cylinder(5, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    hub = _write(tmp, "hub", Cylinder(4, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    j = {"id": "j1", "type": "revolute", "name": "Arm", "p": [0, 0, 0], "dir": [0, 0, 1], "insts": ["arm", "hub"],
         "limits": None}
    return {"insts": [a, p, hub], "joints": [j]}


def test_values_follow_gear_chains() -> None:
    js = [{"id": "a", "type": "revolute"}, {"id": "b", "type": "revolute"}, {"id": "c", "type": "revolute"},
          {"id": "g1", "type": "gear", "a": "a", "b": "b", "ratio": -18 / 54},
          {"id": "g2", "type": "gear", "a": "c", "b": "b", "ratio": -30 / 54}]
    v = motion.values(js, "a", 90.0)
    assert v["b"] == pytest.approx(-30.0)
    assert v["c"] == pytest.approx(-30.0 / (-30 / 54))  # c drives b: c = b / ratio = 54°
    v2 = motion.values(js, "b", 10.0)
    assert v2["a"] == pytest.approx(10.0 / (-18 / 54)) and v2["c"] == pytest.approx(-18.0)


def test_gear_ratio_poses() -> None:
    """The driven gear's placement after the pinion turns θ is the rotation by −θ·za/zb about its own axis."""
    za, zb, m = 18, 54, 2.0
    a = m * (za + zb) / 2
    T0 = xform.to12(xform.translate((a, 0, 5)))
    js = [{"id": "p", "type": "revolute", "p": [0, 0, 0], "dir": [0, 0, 1], "insts": ["pin"]},
          {"id": "g", "type": "revolute", "p": [a, 0, 0], "dir": [0, 0, 1], "insts": ["gear"]},
          {"id": "m", "type": "gear", "a": "p", "b": "g", "ratio": -za / zb}]
    pl = motion.plan({"pin": xform.to12(xform.ident()), "gear": T0}, js, "p", 0, 360, 12)
    assert len(pl["steps"]) == 12 and pl["steps"][-1]["value"] == pytest.approx(330.0)
    for s in pl["steps"]:
        th = s["value"]
        Tg = xform.from12(s["T"]["gear"])
        want = xform.about(xform.rot([0, 0, 1], math.radians(-th * za / zb)), [a, 0, 0]) @ xform.from12(T0)
        assert np.allclose(Tg, want, atol=1e-6)
        # a point on the gear's pitch circle moved by the same arc length as the pinion's
        assert abs(math.radians(th) * m * za / 2 - abs(math.radians(s["values"]["g"])) * m * zb / 2) < 1e-6


def test_clean_joint_rules() -> None:
    ids = {"i1", "i2"}
    j = motion.clean_joint({"type": "revolute", "p": [0, 0, 0], "dir": [0, 0, 2], "insts": ["i1"]}, ids, [])
    assert j["dir"] == [0, 0, 1] and j["limits"] is None
    j["id"] = "j1"
    with pytest.raises(AssemblyInputError):
        motion.clean_joint({"type": "revolute", "p": [0, 0, 0], "dir": [0, 0, 1], "insts": ["i1"]}, ids, [j])
    with pytest.raises(AssemblyInputError):
        motion.clean_joint({"type": "slider", "dir": [1, 0, 0], "insts": ["i2"]}, ids, [j])
    with pytest.raises(AssemblyInputError):
        motion.clean_joint({"type": "gear", "a": "j1", "b": "j1", "teeth": [10, 20]}, ids, [j])
    k = motion.clean_joint({"type": "revolute", "p": [0, 0, 0], "dir": [1, 0, 0], "insts": ["i2"]}, ids, [j])
    k["id"] = "j2"
    g = motion.clean_joint({"type": "gear", "a": "j1", "b": "j2", "teeth": [18, 54]}, ids, [j, k])
    assert g["ratio"] == pytest.approx(-1 / 3)


def test_arm_hits_pin_between_known_angles(arm: dict[str, Any]) -> None:
    """The arm's centre line passes the pin centre (radius 70, at 90°) closer than 5 + 5 mm when
    |θ − 90°| < asin(10 / 70) = 8.21°: in 5° steps the colliding steps are 85°, 90°, 95° exactly."""
    pl = motion.plan({i["id"]: i["T"] for i in arm["insts"]}, arm["joints"], None, 0, 360, 72)
    res = motion.sweep(arm["insts"], motion.bodies(arm["joints"]), [{"i": s["i"], "T": s["T"]} for s in pl["steps"]])
    out = motion.summarize(pl, res, {"arm": "Arm<1>", "pin": "Pin<1>", "hub": "Hub<1>"})
    hit = [s["value"] for s in out["steps"] if s["collisions"]]
    lim = math.degrees(math.asin(10 / 70))
    want = [s["value"] for s in out["steps"] if abs(s["value"] - 90) < lim]
    assert hit == want == [85.0, 90.0, 95.0]
    assert out["worst"] == 18 and {c["b"] for c in out["steps"][18]["collisions"]} == {"pin"}
    # the hub overlaps the arm's root but turns with it: never re-checked by the sweep
    assert not any(c["b"] == "hub" or c["a"] == "hub" for s in out["steps"] for c in s["collisions"])
    assert out["steps"][18]["collisions"][0]["mesh"]["pos"]
    assert "Collisions in" in out["summary"] and "Arm<1> ↔ Pin<1>" in out["summary"]


def test_prefilter_never_drops_a_collision(arm: dict[str, Any]) -> None:
    """Brute force (every pair, exact boolean, no screening) gives the same colliding pairs at every step."""
    pl = motion.plan({i["id"]: i["T"] for i in arm["insts"]}, arm["joints"], None, 0, 360, 24)
    res = motion.sweep(arm["insts"], motion.bodies(arm["joints"]), [{"i": s["i"], "T": s["T"]} for s in pl["steps"]],
                       worst_mesh=False)
    for s, r in zip(pl["steps"], res["steps"], strict=True):
        brute = set()
        for a, b in (("arm", "pin"), ("hub", "pin")):
            ia = next(i for i in arm["insts"] if i["id"] == a)
            ib = next(i for i in arm["insts"] if i["id"] == b)
            sa = geometry.load(ia["step"]).moved(geometry._loc(xform.from12(s["T"].get(a, ia["T"]))))
            sb = geometry.load(ib["step"]).moved(geometry._loc(xform.from12(s["T"].get(b, ib["T"]))))
            c = geometry._common(sa, sb)
            if c is not None and geometry._volume(c) > motion.VOL_TOL:
                brute.add((a, b))
        assert {(c["a"], c["b"]) for c in r["collisions"]} == brute
    assert res["stats"]["box_skips"] > 0  # the boxes did screen pairs out


def _bearing_case(tmp: Path, seat_d: float) -> list[dict[str, Any]]:
    """A housing with a 6205 seat of Ø seat_d (25 deep), the bearing in it, a Ø25 shaft through both."""
    from build123d import Align, Box, Cylinder, Pos

    from aicad import toolbox

    d, D, B = toolbox.BEARING[6205]
    al = (Align.CENTER, Align.CENTER, Align.MIN)
    housing = Box(90, 90, 30, align=al) - Pos(0, 0, 30 - B) * Cylinder(seat_d / 2, B + 1, align=al) \
        - Pos(0, 0, -1) * Cylinder(d / 2 + 1, 40, align=al)
    h = _write(tmp, f"housing_{seat_d}", housing)
    shape, _ = toolbox.build("bearing", SERIES=6205)
    b = _write(tmp, f"bearing_{seat_d}", shape)
    b["T"] = xform.to12(xform.translate((0, 0, 30 - B)))
    b["envelope"] = {"kind": "annulus", "r0": d / 2, "r1": D / 2, "z0": 0.0, "z1": float(B)}
    s = _write(tmp, f"shaft_{seat_d}", Cylinder(d / 2, 60, align=al))
    return [h, b, s]


@pytest.mark.parametrize("seat_d", [52.0, 51.0])
def test_bearing_screening_is_exact(tmp_path: Path, seat_d: float) -> None:
    """Same pairs and volumes with and without the bearing envelope; the screen saves the per-ball booleans."""
    insts = _bearing_case(tmp_path, seat_d)
    geometry.STATS.update(screened=0, booleans=0)
    t0 = time.perf_counter()
    fast = geometry.interference(insts)
    t_fast = time.perf_counter() - t0
    n_fast = geometry.STATS["booleans"]
    plain = [{k: v for k, v in i.items() if k != "envelope"} for i in insts]
    geometry.STATS.update(screened=0, booleans=0)
    t0 = time.perf_counter()
    slow = geometry.interference(plain)
    t_slow = time.perf_counter() - t0
    n_slow = geometry.STATS["booleans"]
    key = [(p["a"], p["b"], round(p["volume_mm3"], 3)) for p in fast["pairs"]]
    assert key == [(p["a"], p["b"], round(p["volume_mm3"], 3)) for p in slow["pairs"]]
    if seat_d == 52.0:
        assert not [p for p in fast["pairs"] if p["kind"] == "interference"]
        assert n_fast < n_slow
    else:  # an undersized seat: the outer ring clashes, found exactly as before
        assert [(p["a"][:7], p["b"][:7]) for p in fast["pairs"]] == [("housing", "bearing")]
        # the annulus Ø51..52 x 15 less the outer ring's ISO 582 corner chamfers (Toolbox v2, 45° x r_s min c = 1.0 for
        # 6205) inside the band: per end 2 pi int_0^w (R - u)(c - u) du, R 26, w 0.5
        from aicad import toolbox

        R, w, c = 26.0, 0.5, toolbox.BEARING_RS[6205]
        want = math.pi / 4 * (52.0 ** 2 - 51.0 ** 2) * 15.0 - 2 * 2 * math.pi * (
            R * c * w - (R + c) * w * w / 2 + w ** 3 / 3)
        assert fast["pairs"][0]["volume_mm3"] == pytest.approx(want, rel=1e-3)
    print(f"seat Ø{seat_d}: screened {t_fast:.2f} s / {n_fast} booleans, plain {t_slow:.2f} s / {n_slow} booleans")


def test_meshing_gears_turn_without_collision(tmp_path: Path) -> None:
    """Two Toolbox spur gears (m2, 18 / 36) at the exact centre distance, the second phased as the ICD does:
    turned by the ratio they never collide; with the driven gear held still they do."""
    from aicad import toolbox

    za, zb, m, b = 18, 36, 2.0, 10.0
    a = m * (za + zb) / 2
    ga, _ = toolbox.build("spur_gear", M=m, Z=za, B=b, BORE=8)
    gb, _ = toolbox.build("spur_gear", M=m, Z=zb, B=b, BORE=10)
    ia, ib = _write(tmp_path, "pinion", ga), _write(tmp_path, "wheel", gb)
    pb = 360.0 / zb
    phase_b = (180.0 - 0.5 * pb) % pb  # icd.build: u = 0 (a tooth of a faces b), v = 0.5
    ib["T"] = xform.to12(xform.make(xform.rot([0, 0, 1], math.radians(phase_b)), [a, 0, 0]))
    js = [{"id": "p", "type": "revolute", "p": [0, 0, 0], "dir": [0, 0, 1], "insts": ["pinion"], "limits": None},
          {"id": "w", "type": "revolute", "p": [a, 0, 0], "dir": [0, 0, 1], "insts": ["wheel"], "limits": None},
          {"id": "m", "type": "gear", "a": "p", "b": "w", "ratio": -za / zb}]
    insts = {i["id"]: i["T"] for i in (ia, ib)}
    pl = motion.plan(insts, js, "p", 0, 40, 4)  # 0, 10, 20, 30, 40° of the pinion (two tooth pitches)
    res = motion.sweep([ia, ib], motion.bodies(js), [{"i": s["i"], "T": s["T"]} for s in pl["steps"]])
    assert all(not s["collisions"] for s in res["steps"]), res["steps"]
    held = [j for j in js if j["id"] != "m"]
    pl2 = motion.plan(insts, held, "p", 0, 40, 4)
    res2 = motion.sweep([ia, ib], motion.bodies(held), [{"i": s["i"], "T": s["T"]} for s in pl2["steps"]])
    assert any(s["collisions"] for s in res2["steps"])


def test_program_joints_from_icd() -> None:
    """Shafts in bearing seats turn, the gears on them ride along, the mesh couples them by −za/zb; axes come from
    the ICD (a shaft along Y here) mapped through the instance placement."""
    from aicad.office import motion_joints

    sk = {"items": {"H": {"role": "block", "copies": [[0, 0, -20]]}, "S1": {"role": "shaft", "copies": [[0, 0, -30]]},
                    "S2": {"role": "shaft", "copies": [[72, 0, -30]]}, "G1": {"role": "gear", "copies": [[0, 0, -30]]},
                    "G2": {"role": "gear", "copies": [[72, 0, -30]]}}}
    def f(i: str, kind: str, a: str, b: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"id": i, "kind": kind, "name": i, "a": {"item": a, "copy": 0, "name": a}, "b": {"item": b, "copy": 0, "name": b},
                "data": data}
    ifs = [f("IF-01", "bearing_seat", "H", "S1", {"ax": "y", "axis": [0, -30], "z": [-40, 40]}),
           f("IF-02", "bearing_seat", "H", "S2", {"ax": "y", "axis": [72, -30], "z": [-40, 40]}),
           f("IF-03", "shaft_bore", "G1", "S1", {"ax": "y", "axis": [0, -30], "z": [-10, 10]}),
           f("IF-04", "shaft_bore", "G2", "S2", {"ax": "y", "axis": [72, -30], "z": [-10, 10]}),
           f("IF-05", "gear_mesh", "G1", "G2", {"teeth_a": 18, "teeth_b": 54})]
    adoc = {"instances": [{"id": f"i{k}", "T": xform.to12(xform.translate(sk["items"][it]["copies"][0])),
                           "office": {"item": it, "copy": 0}} for k, it in enumerate(["H", "S1", "S2", "G1", "G2"])]}
    out = motion_joints.program_joints({"skeleton": sk, "icd": {"interfaces": ifs}}, adoc)
    rev = [j for j in out["joints"] if j["type"] == "revolute"]
    assert [(j["insts"], j["dir"]) for j in rev] == [(["i1", "i3"], [0, 1, 0]), (["i2", "i4"], [0, 1, 0])]
    assert rev[0]["p"][0] == 0 and rev[0]["p"][2] == -30 and rev[1]["p"][0] == 72
    g = next(j for j in out["joints"] if j["type"] == "gear")
    assert g["ratio"] == pytest.approx(-1 / 3) and out["driver"] == rev[0]["id"]


def test_clearance_near_faces_matches_whole_shapes(tmp_path: Path, arm: dict[str, Any]) -> None:
    """The face-pair branch and bound gives the exact BRepExtrema distance of the whole shapes: meshing gears
    (nearly touching flanks), a seated bearing (touching) and a plain gap."""
    from aicad import toolbox

    za, zb, m = 12, 13, 1.0
    ga, _ = toolbox.build("spur_gear", M=m, Z=za, B=2, BORE=3)
    gb, _ = toolbox.build("spur_gear", M=m, Z=zb, B=2, BORE=3)
    ia, ib = _write(tmp_path, "ga", ga), _write(tmp_path, "gb", gb)
    pb = 360.0 / zb
    ib["T"] = xform.to12(xform.make(xform.rot([0, 0, 1], math.radians((180.0 - 0.5 * pb) % pb)), [m * (za + zb) / 2, 0, 0]))
    cases = [(ia, ib)]
    h, b, s = _bearing_case(tmp_path, 52.0)
    cases += [(h, b), (b, s)]
    p = next(i for i in arm["insts"] if i["id"] == "pin")
    a = next(i for i in arm["insts"] if i["id"] == "arm")
    cases.append((a, p))
    for x, y in cases:
        wx, wy = geometry._world(x), geometry._world(y)
        t0 = time.perf_counter()
        whole = geometry.min_distance(wx, wy)[0]
        t1 = time.perf_counter()
        near = geometry.min_distance_near(wx, wy)[0]
        print(f"{x['id']} / {y['id']}: whole {t1 - t0:.2f} s, near faces {time.perf_counter() - t1:.2f} s, {near:.6f} mm")
        assert near == pytest.approx(whole, abs=1e-7), (x["id"], y["id"])
    insts = [h, b, s, a, p]
    res = geometry.interference(insts)
    hits = {(q["a"], q["b"]): q["center"] for q in res["pairs"]}
    fast = geometry.clearance(insts, [], 10.0, overlaps=hits)
    slow = geometry.clearance(insts, [], 10.0)
    assert [(r["a"], r["b"], round(r["distance_mm"], 6)) for r in fast["rows"]] == \
        [(r["a"], r["b"], round(r["distance_mm"], 6)) for r in slow["rows"]]
