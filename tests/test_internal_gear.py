"""Internal (ring) gears and planets on their bearings: the geometry, recognition and conformance a single-stage
planetary gearbox needs (founder's benchmark "Build a single stage planetary Gearbox", attempt A1: the ring went to the
designer because there was no internal gear generator, and Gage could never pass it because internal teeth were not
recognised; the planet went to the designer over its bearing seat).

Hand values (ISO 53 basic rack, profile shift 0, α = 20°; ISO 15 bearings):

* ring m2 z90: pitch Ø m z = 180, tip Ø m (z - 2) = 176 (inside), root Ø m (z + 2.5) = 185 (outside), base Ø
  180 cos 20° = 169.145; rim Ø197 (the A1 envelope) x 26 long.
* sun and planets m2 z30: pitch Ø 60, tip Ø 64, root Ø 55. Centre distances: sun / planet m (30 + 30) / 2 = 60;
  planet / ring (internal) m (90 - 30) / 2 = 60. Assembly condition (30 + 90) / 3 = 40, whole.
* phasing, angles in degrees, pitches 360 / z (sun and planet 12, ring 4): with the sun's tooth on +X and a planet at
  θ, the external mesh needs v = 1/2 - u in pitches (u the line of centres measured from a sun tooth, v from a
  planet tooth, each about its own centre), so the planet turns φp = θ + 180 - (1/2 - θ / 12) x 12. For θ = 90, 210,
  330 that is 6 (mod 12) for all three. The internal mesh: both gears look outward along θ, so the line measured
  from a ring tooth space equals the line measured from a planet tooth: φr = θ - (θ - φp) x 4 / 12 (mod 4) = 2, the
  same for all three planets (the assembly condition). Equivalently, measured from a ring tooth (u = that + 1/2),
  v = 1/2 - u in the opposite angle sense.
* working backlash 0.04 m at the pitch circle on each member (Toolbox gears): 0.04 x 2 = 0.08 circumferential per
  flank pair, a normal gap of 0.08 cos 20° = 0.0752 mm.
* planet bearing: the rim rule (graph/planetary.py, benchmark A1) gives the default set a 6004; the 6204 case is
  the same ICD with the bearing swapped. 6204: d 20, D 47, B 14 (ISO 15); the seat Ø47 H7 bored from the -Z face to the shoulder at Z 7 (the
  ICD's), depth 7 + 20 / 2 = 17; shoulder bore D - (D - d) / 4 = 40.25, rounded down to 0.5: Ø40. 6004: d 20, D 42,
  B 12; shoulder 42 - 22 / 4 = 36.5.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import pytest

from aicad import fw_std, recognize, toolbox
from aicad.graph import compile as gc
from aicad.graph import intent
from aicad.office import conformance, direct, icd

A20 = math.radians(20.0)


def _inv(x: float) -> float:
    return math.tan(x) - x


def _integral(f: Any, a: float, b: float, n: int = 20000) -> float:
    """Trapezoid rule (independent of fw_std's Simpson)."""
    h = (b - a) / n
    return h * (0.5 * f(a) + sum(f(a + i * h) for i in range(1, n)) + 0.5 * f(b))


def ring_volume(m: float, z: int, od: float, length: float, backlash: float) -> float:
    """Rim disc less the toothed bore: the tip disc plus z tooth spaces, each 2 sigma(r) r dr from the tip circle to
    the root circle (the tip is outside the base circle here, so the whole flank is involute)."""
    rp, rb = m * z / 2, m * z / 2 * math.cos(A20)
    ri, ro = rp - m, rp + 1.25 * m
    assert ri >= rb

    def sigma(r: float) -> float:
        return math.pi / (2 * z) + _inv(A20) - _inv(math.acos(rb / r)) + backlash / 2 / rp

    bore = math.pi * ri ** 2 + z * _integral(lambda r: 2 * sigma(r) * r, ri, ro)
    return (math.pi * od ** 2 / 4 - bore) * length


def spur_area(m: float, z: int, backlash: float) -> float:
    """External gear profile: root disc + z teeth (radial flank from the root to the base circle, involute above)."""
    rp, rb = m * z / 2, m * z / 2 * math.cos(A20)
    ra, rf = rp + m, rp - 1.25 * m
    r0 = max(rb, rf)

    def psi(r: float) -> float:
        return math.pi / (2 * z) + _inv(A20) - _inv(math.acos(min(1.0, rb / r))) - backlash / 2 / rp

    return math.pi * rf ** 2 + z * (_integral(lambda r: 2 * psi(r) * r, r0, ra) + psi(r0) * (r0 ** 2 - rf ** 2))


def _overlap(a: Any, b: Any) -> float:
    """Solid by solid (booleans on a compound are not reliable)."""
    tot = 0.0
    for x in a.solids():
        for y in b.solids():
            r = x & y
            if r is not None:
                tot += sum(s.volume for s in r.solids())
    return tot


# ---------------------------------------------------------------------------- the internal gear itself
def test_internal_gear_hand_sizes_volume_and_recognition() -> None:
    ring, e = fw_std.internal_gear(2, 90, 26, rim_od=197, backlash=0.08)
    g = e["gear"]
    assert (g["pitch_d"], g["tip_d"], g["root_d"]) == pytest.approx((180, 176, 185))
    assert g["base_d"] == pytest.approx(180 * math.cos(A20)) and g["internal"] is True
    assert e["bbox"] == pytest.approx([197, 197, 26]) and e["solids"] == 1
    hand = ring_volume(2, 90, 197, 26, 0.08)
    # bounds: more than the rim behind the root, less than the rim behind the tip circle
    assert math.pi / 4 * (197 ** 2 - 185 ** 2) * 26 < hand < math.pi / 4 * (197 ** 2 - 176 ** 2) * 26
    assert e["volume"] == pytest.approx(hand, rel=1e-7)
    assert ring.is_valid and ring.volume == pytest.approx(hand, rel=1e-5)  # spline flanks vs the exact involute
    bb = ring.bounding_box()
    assert [bb.size.X, bb.size.Y, bb.size.Z] == pytest.approx([197, 197, 26], abs=1e-6)
    # recognised on the exact B-rep: 90 internal teeth, module 2, on the Z axis
    rec = recognize.recognize(ring)
    c = rec["component"]
    assert c["kind"] == "internal_gear", rec["summary"]
    p = c["params"]
    assert (p["teeth"], p["module"], p["internal"]) == (90, 2.0, True)
    assert p["tip_d"] == pytest.approx(176, abs=1e-3) and p["root_d"] == pytest.approx(185, abs=1e-3)
    assert p["rim_d"] == pytest.approx(197, abs=1e-3) and abs(abs(c["axis"][2]) - 1) < 1e-6
    assert abs(c["origin"][0]) < 1e-6 and abs(c["origin"][1]) < 1e-6
    assert not rec["unrecognised"], rec["unrecognised"]
    # an external gear is still an external gear
    sun, _es = fw_std.spur_gear(2, 30, 20, bore=20)
    assert recognize.recognize(sun)["component"]["kind"] == "spur_gear"


def test_ring_gear_options_holes_flange_and_refusals() -> None:
    # 12 x Ø4 through the rim on PCD 191 (93.5 .. 97.5 from the axis, inside the 92.5 .. 98.5 rim band less 0.5)
    ring, e = fw_std.internal_gear(2, 90, 20, rim_od=197, backlash=0.08, holes=(12, 191, 4))
    hand = ring_volume(2, 90, 197, 20, 0.08) - 12 * math.pi / 4 * 4 ** 2 * 20
    assert e["volume"] == pytest.approx(hand, rel=1e-7) and ring.volume == pytest.approx(hand, rel=1e-5)
    rec = recognize.recognize(ring)  # more than 12 hole axes: the ring's own axis is still tried
    assert rec["component"]["kind"] == "internal_gear" and rec["component"]["params"]["teeth"] == 90
    assert any(pt["kind"] == "circular" and pt["count"] == 12 for pt in rec["patterns"])
    # a flange Ø230 x 8 on the -Z face with 8 x Ø9 on PCD 215 through the flange only
    fl, ef = fw_std.internal_gear(2, 90, 20, rim_od=197, backlash=0.08, flange_od=230, flange_t=8,
                                  holes=(8, 215, 9))
    hand = ring_volume(2, 90, 197, 20, 0.08) + math.pi / 4 * (230 ** 2 - 197 ** 2) * 8 - 8 * math.pi / 4 * 81 * 8
    assert ef["volume"] == pytest.approx(hand, rel=1e-7) and fl.volume == pytest.approx(hand, rel=1e-5)
    assert ef["bbox"] == pytest.approx([230, 230, 20])
    with pytest.raises(ValueError, match="rim"):
        fw_std.internal_gear(2, 90, 20, rim_od=185.5)  # behind the Ø185 root: less than half a module
    with pytest.raises(ValueError, match="fit neither"):
        fw_std.internal_gear(2, 90, 20, rim_od=197, holes=(6, 186, 6))  # breaks into the tooth roots
    with pytest.raises(ValueError, match="teeth"):
        fw_std.internal_gear(2, 12, 20, rim_od=60)


# ---------------------------------------------------------------------------- the planetary set, phased
def test_planetary_set_built_through_the_toolbox_has_no_overlap() -> None:
    from build123d import Pos, Rot

    sun, _es = toolbox.build("spur_gear", M=2, Z=30, B=20, BORE=20)
    planet, _ep = toolbox.build("spur_gear", M=2, Z=30, B=20, BORE=20)
    ring, er = toolbox.build("internal_gear", M=2, Z=90, B=26, OD=197)
    assert er["volume"] == pytest.approx(ring_volume(2, 90, 197, 26, 0.08), rel=1e-7)
    assert er["bbox"] == pytest.approx([197, 197, 26])
    ps, pp, pr = 12.0, 12.0, 4.0
    a = 2 * (30 + 30) / 2
    assert a == 2 * (90 - 30) / 2 == 60.0 and (30 + 90) % 3 == 0
    sun = Pos(0, 0, 3) * sun  # gears 20 wide in the middle of the 26 long ring
    planets, rphases = [], []
    for th in (90.0, 210.0, 330.0):
        u = th / ps                          # the line of centres from a sun tooth (sun phase 0)
        phi_p = th + 180 - (0.5 - u) * pp    # v = 1/2 - u
        assert phi_p % pp == pytest.approx(6.0)
        rphases.append((th - (th - phi_p) * pr / pp) % pr)
        c = (a * math.cos(math.radians(th)), a * math.sin(math.radians(th)), 3)
        planets.append(Pos(*c) * Rot(0, 0, phi_p) * planet)
    assert rphases == pytest.approx([2.0, 2.0, 2.0])  # one ring position fits all three planets
    placed = Rot(0, 0, rphases[0]) * ring
    for p in planets:
        assert _overlap(sun, p) == 0.0
        assert _overlap(placed, p) == 0.0
    for p, q in ((planets[0], planets[1]), (planets[1], planets[2]), (planets[0], planets[2])):
        assert _overlap(p, q) == 0.0
    # the flanks clear by the working backlash: 0.04 m on each member, 0.08 cos 20° normal
    assert placed.distance(planets[0]) == pytest.approx(0.08 * math.cos(A20), abs=0.004)
    assert sun.distance(planets[0]) == pytest.approx(0.08 * math.cos(A20), abs=0.004)
    # half a ring pitch out of phase, ring teeth sit on planet teeth: a clash (the check sees it)
    assert _overlap(ring, planets[0]) > 100


# ---------------------------------------------------------------------------- the Design Office: direct, gate, conformance
REPLY: dict[str, Any] = {
    "summary": "Single-stage planetary gearbox: a keyed sun on the input shaft drives three planets.",
    "components": [
        {"id": "housing", "kind": "housing", "name": "Gearbox base", "params": {"style": "split"}},
        {"id": "cover", "kind": "cover", "name": "Gearbox cover"},
        {"id": "input_shaft", "kind": "shaft", "name": "Input shaft", "params": {"role": "input"}},
        {"id": "output_shaft", "kind": "shaft", "name": "Output shaft", "params": {"role": "output"}},
        {"id": "sun_gear", "kind": "spur_gear", "name": "Sun gear", "params": {"module": 2, "teeth": 30}},
        {"id": "planet_gear", "kind": "spur_gear", "name": "Planet gear", "qty": 3, "params": {"module": 2, "teeth": 30}},
        {"id": "ring_gear", "kind": "spur_gear", "name": "Ring gear", "params": {"module": 2, "teeth": 90,
                                                                                "internal": True}},
        {"id": "carrier", "kind": "hub", "name": "Planet carrier"},
        {"id": "planet_pin", "kind": "shaft", "name": "Planet pin", "qty": 3, "params": {"stepped": False}},
        {"id": "planet_bearing", "kind": "bearing", "name": "Planet bearing", "qty": 3},
        {"id": "sun_key", "kind": "key", "name": "Sun gear key"},
        {"id": "carrier_key", "kind": "key", "name": "Carrier key"},
        {"id": "input_bearing", "kind": "bearing", "name": "Input shaft bearing", "qty": 2},
        {"id": "output_bearing", "kind": "bearing", "name": "Output shaft bearing", "qty": 2},
        {"id": "cover_bolt", "kind": "fastener", "name": "Cover bolt", "qty": 6}],
    "connections": [
        {"kind": "keyed_hub", "host": "input_shaft", "guest": "sun_gear", "via": ["sun_key"]},
        {"kind": "gear_mesh", "host": "sun_gear", "guest": "planet_gear"},
        {"kind": "gear_mesh", "host": "planet_gear", "guest": "ring_gear"},
        {"kind": "mounted_on", "host": "housing", "guest": "ring_gear"},
        {"kind": "bearing_journal", "host": "planet_pin", "guest": "planet_bearing", "params": {"count": 1}},
        {"kind": "mounted_on", "host": "planet_bearing", "guest": "planet_gear"},
        {"kind": "mounted_on", "host": "carrier", "guest": "planet_pin"},
        {"kind": "keyed_hub", "host": "output_shaft", "guest": "carrier", "via": ["carrier_key"]},
        {"kind": "bearing_journal", "host": "input_shaft", "guest": "input_bearing", "params": {"count": 2}},
        {"kind": "bearing_journal", "host": "output_shaft", "guest": "output_bearing", "params": {"count": 2}},
        {"kind": "bearing_seat", "host": "housing", "guest": "input_bearing"},
        {"kind": "bearing_seat", "host": "housing", "guest": "output_bearing"},
        {"kind": "bolted_joint", "host": "housing", "guest": "cover", "via": ["cover_bolt"]}],
}
BRIEF = "Build a single stage planetary Gearbox"
ISO15 = {"6204": (20.0, 47.0, 14.0), "6004": (20.0, 42.0, 12.0)}  # d, D, B


@pytest.fixture(scope="module")
def pdoc() -> dict[str, Any]:
    g, iss, _qs = intent.compile_reply(copy.deepcopy(REPLY), "Planetary Gearbox", BRIEF)
    assert not [i for i in iss if i["severity"] == "error"], iss
    plan = gc.to_plan(g, resolved=True)
    sk, ifs = gc.to_icd(g, plan)
    parts = gc.plan_parts(plan)
    return {"id": "pg", "name": "Planetary", "skeleton": sk, "icd": {"version": 1, "status": "approved",
                                                                     "interfaces": ifs},
            "brief": BRIEF, "plan": {**plan, "graph": {"data": g.dump()}},
            "items": [{"id": p["id"], "name": p["name"], "description": p["description"]} for p in parts]}


def _item(doc: dict[str, Any], name: str) -> str:
    return next(i["id"] for i in doc["items"] if i["name"] == name)


def _t(doc: dict[str, Any], name: str) -> dict[str, Any]:
    return {"kind": "part", "item_id": _item(doc, name), "title": name, "qty": 1, "id": f"t_{_item(doc, name)}"}


def _num(src: str, name: str) -> float:
    import re

    m = re.search(rf"^{name} = (-?\d+(?:\.\d+)?)", src, re.MULTILINE)
    assert m, f"{name} not in the script"
    return float(m.group(1))


def _gate(tmp: Path, doc: dict[str, Any], name: str, script: str) -> tuple[dict[str, Any], dict[str, Any],
                                                                           dict[str, Any]]:
    from aicad.agent import runner
    from aicad.assembly import geometry

    ws = tmp / f"{name.replace(' ', '_')}_{direct.sha(script)}"
    (ws / "out").mkdir(parents=True)
    (ws / "model.py").write_text(script, encoding="utf-8")
    runner.main(ws / "model.py", ws / "out", determinism=True, fast=False)
    st = json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
    assert runner.is_verified(st), [c for c in st["checks"] if not c["passed"]]
    assert {c["id"] for c in st["checks"] if c["passed"]} >= {"CHK-02", "CHK-03", "CHK-04", "CHK-05", "CHK-07",
                                                               "CHK-08"}
    info = geometry.prepare(ws / "snap", step=str(ws / "out" / "part.step"))
    res = conformance.measure(doc["skeleton"], doc["icd"], _item(doc, name), info,
                              json.loads((ws / "snap" / "refs.json").read_text()))
    return st, res, info


def test_the_ring_goes_direct_builds_and_conforms(pdoc: dict[str, Any], tmp_path: Path) -> None:
    ring_id = _item(pdoc, "Ring gear")
    it = pdoc["skeleton"]["items"][ring_id]
    assert it["internal"] is True and (it["module"], it["teeth"]) == (2.0, 90)
    feats = icd.item_features(pdoc["skeleton"], pdoc["icd"]["interfaces"], ring_id)
    gear = next(f for f in feats if f["type"] == "gear")
    assert gear["internal"] is True and "internal" in gear["label"]
    # the planets' own gear feature stays external (they are the pinion of the internal mesh)
    pf = icd.item_features(pdoc["skeleton"], pdoc["icd"]["interfaces"], _item(pdoc, "Planet gear"))
    assert not next(f for f in pf if f["type"] == "gear").get("internal")
    p = direct.plan(pdoc, _t(pdoc, "Ring gear"))
    assert p["path"] == "direct", p.get("reasons")
    assert p["kind"] == "ring_gear" and "fw_std.internal_gear(" in p["script"]
    src = p["script"]
    OD, H = float(it["size"][0]), float(it["size"][2])
    assert (_num(src, "MODULE"), _num(src, "TEETH"), _num(src, "LENGTH"), _num(src, "RIM_OD")) == (2, 90, H, OD)
    assert "backlash=0.04 * MODULE" in src and "PARAM_META" in src
    st, res, info = _gate(tmp_path, pdoc, "Ring gear", src)
    assert st["fingerprint"]["volume"] == pytest.approx(ring_volume(2, 90, OD, H, 0.08), rel=1e-5)
    assert res["ok"] and res["envelope"]["ok"], [r for x in res["interfaces"] for r in x["rows"] if not r["ok"]]
    rows = [r for x in res["interfaces"] for r in x["rows"]]
    g = next(r for r in rows if "internal teeth" in r["feature"])
    assert g["ok"] and g["measured"].startswith("m2 × 90 teeth")
    assert info["component"]["kind"] == "internal_gear"
    # the same feature on an external gear fails, saying why
    sun, _e = fw_std.spur_gear(2, 90, 20, bore=40)
    row = conformance._gear(gear, {"component": recognize.recognize(sun)["component"]})
    assert not row["ok"] and "external gear teeth" in row["measured"]


def test_the_program_layout_phases_the_ring_and_the_placed_set_has_no_overlap(pdoc: dict[str, Any]) -> None:
    """The layout turns the ring so its tooth spaces meet the planets' teeth (u_ring = v_planet, see the module
    docstring); the ring, sun and planets as the program assembly places them (the direct parts' geometry, 0.04 m
    backlash each) intersect nowhere, solid by solid."""
    import numpy as np

    from aicad.assembly import geometry
    from aicad.office import program_assembly

    sk = pdoc["skeleton"]
    ids = {n: _item(pdoc, n) for n in ("Ring gear", "Planet gear", "Sun gear")}
    ring_it, pl_it = sk["items"][ids["Ring gear"]], sk["items"][ids["Planet gear"]]
    # hand: the ring's phase from planet copy 0, in the canonical frame of their common axis
    ax = ring_it["ax"]
    q = [pl_it["copies"][0][k] - ring_it["copies"][0][k] for k in range(3)]
    c = icd.to_canon(ax, q)
    th = math.degrees(math.atan2(c[1], c[0]))
    vp = ((th - float(pl_it.get("phase") or 0)) % 12) / 12
    assert float(ring_it.get("phase") or 0) == pytest.approx((th - vp * 4) % 4, abs=1e-6)

    def at(shape: Any, item: str, copy: int) -> Any:
        T = np.eye(4)
        T[:3, :] = np.array(program_assembly.place(sk, item, copy)).reshape(3, 4)
        return geometry._loc(T) * shape

    H = float(ring_it["size"][2])
    ring, _e = fw_std.internal_gear(2, 90, H, rim_od=float(ring_it["size"][0]), backlash=0.08, z0=-H / 2)
    planet, _e = fw_std.spur_gear(2, 30, 20, bore=40, seats=[(47, 17, -1)], backlash=0.08, z0=-10)
    sun, _e = fw_std.spur_gear(2, 30, 20, bore=20, keyway=True, backlash=0.08, z0=-10)
    R = at(ring, ids["Ring gear"], 0)
    S = at(sun, ids["Sun gear"], 0)
    for k in range(len(pl_it["copies"])):
        P = at(planet, ids["Planet gear"], k)
        assert _overlap(R, P) == 0.0, f"ring / planet {k + 1}"
        assert _overlap(S, P) == 0.0, f"sun / planet {k + 1}"
        assert R.distance(P) == pytest.approx(0.08 * math.cos(A20), abs=0.004)


def test_the_ring_excerpt_says_internal_and_the_scripted_designer_builds_a_ring(pdoc: dict[str, Any],
                                                                                tmp_path: Path) -> None:
    """The designer's ICD excerpt carries internal: true with tip Ø m (z - 2) = 176 and root Ø m (z + 2.5) = 185,
    and the simulated designer (fake agents, used when the direct path is off) builds a ring from it, not an
    external gear."""
    import re

    from aicad.office import fake_agents

    ring = _item(pdoc, "Ring gear")
    text = icd.excerpt(pdoc["skeleton"], pdoc["icd"], ring)
    data = json.loads(re.search(r"```fw-icd\n(.*?)\n```", text, re.DOTALL).group(1))
    assert data["gear"]["internal"] is True and (data["gear"]["tip_d"], data["gear"]["root_d"]) == (176.0, 185.0)
    assert "internal teeth" in text
    sun = json.loads(re.search(r"```fw-icd\n(.*?)\n```", icd.excerpt(pdoc["skeleton"], pdoc["icd"],
                                                                         _item(pdoc, "Sun gear")), re.DOTALL).group(1))
    assert "internal" not in sun["gear"]
    fake_agents._write_icd_part(tmp_path, "Ring gear", data)
    from build123d import import_step

    rec = recognize.recognize(import_step(str(tmp_path / "out" / "part.step")))
    assert rec["component"]["kind"] == "internal_gear" and rec["component"]["params"]["teeth"] == 90


def test_a_ring_screwed_to_the_housing_carries_the_icd_holes(pdoc: dict[str, Any], tmp_path: Path) -> None:
    """Six Ø4.5 holes on PCD 191 through the 6 mm rim (93.25 .. 97.75 from the axis, inside 92.5 + 0.5 ..
    98.5 - 0.5): the ring generator cuts each where the ICD puts it; hand volume less 6 x π/4 x 4.5² x 26."""
    doc = copy.deepcopy(pdoc)
    sk, ifs = doc["skeleton"], doc["icd"]["interfaces"]
    ring = _item(doc, "Ring gear")
    face = next(f for f in ifs if f["kind"] == "face" and f["b"]["item"] == ring)
    c = sk["items"][ring]["copies"][0]
    i, j = icd.PLANE[icd.ax_of(face["data"])]
    pos = [[round(c[i] + 95.5 * math.cos(math.radians(30 + 60 * k)), 4),
            round(c[j] + 95.5 * math.sin(math.radians(30 + 60 * k)), 4)] for k in range(6)]
    ifs.append({"id": "IF-99", "kind": "hole_pattern", "name": "Ring gear to Gearbox base: ring screws",
                "a": dict(face["a"]), "b": dict(face["b"]), "datums": ["A"],
                "data": {**face["data"], "positions": pos, "d": 4.5, "fastener_size": 4}, "edited": []})
    p = direct.plan(doc, _t(doc, "Ring gear"))
    assert p["path"] == "direct", p.get("reasons")
    assert p["script"].count('"d": 4.5') == 6 and "6 holes" in p["summary"]
    OD, H = float(sk["items"][ring]["size"][0]), float(sk["items"][ring]["size"][2])
    st, res, _info = _gate(tmp_path, doc, "Ring gear", p["script"])
    hand = ring_volume(2, 90, OD, H, 0.08) - 6 * math.pi / 4 * 4.5 ** 2 * H
    assert st["fingerprint"]["volume"] == pytest.approx(hand, rel=1e-5)
    assert res["ok"], [r for x in res["interfaces"] for r in x["rows"] if not r["ok"]]
    assert len([r for x in res["interfaces"] for r in x["rows"] if r["feature"].startswith("hole ")]) == 6
    # a brief asking for helical teeth or a flange is more than the interfaces give: the designer
    for extra in ("Helical ring gear, module 2, 90 teeth.", "Flanged ring gear, module 2, 90 teeth."):
        for it in doc["items"]:
            if it["id"] == ring:
                it["description"] = extra
        q = direct.plan(doc, _t(doc, "Ring gear"))
        assert q["path"] == "agent" and q.get("seed"), q


def _seat_doc(doc: dict[str, Any], designation: str) -> dict[str, Any]:
    """The planet bearings swapped for another ISO 15 size, the shoulder kept at the same end of the seat."""
    d2 = copy.deepcopy(doc)
    d, D, B = ISO15[designation]
    for f in d2["icd"]["interfaces"]:
        dd = f["data"]
        if f["kind"] == "bearing_seat" and dd.get("planet"):
            z0, z1 = dd["z"]
            keep = z1 if any(s.get("open", -1) < 0 for s in dd.get("seats") or []) else z0
            nz = [keep - B, keep] if keep == z1 else [keep, keep + B]
            dd.update(designation=designation, d=d, D=D, B=B, z=nz, journals=[nz])
            for s in dd.get("seats") or []:
                s["z"] = nz
    for it in d2["items"]:  # the plan's words follow the bearing
        it["description"] = it["description"].replace(f"{ISO15['6004'][1]:g} mm", f"{D:g} mm")
    return d2


@pytest.mark.parametrize("designation", ["6204", "6004"])
def test_the_planet_goes_direct_with_its_bearing_seat(pdoc: dict[str, Any], designation: str, tmp_path: Path) -> None:
    # the fixture's own bearing is the 6004 (the rim rule: a 6204 leaves (55 - 47) / 2 = 4 mm = 2 m < 2.7 m)
    doc = pdoc if designation == "6004" else _seat_doc(pdoc, designation)
    pid = _item(doc, "Planet gear")
    sk, ifs = doc["skeleton"], doc["icd"]["interfaces"]
    seat_if = next(f for f in ifs if f["kind"] == "bearing_seat" and f["a"]["item"] == pid)
    d, D, B = ISO15[designation]
    assert (seat_if["data"]["d"], seat_if["data"]["D"], seat_if["data"]["B"]) == (d, D, B)
    feats = icd.item_features(sk, ifs, pid)
    seat = next(f for f in feats if f["type"] == "seat")
    shoulder = next(f for f in feats if f["type"] == "face" and abs(f["z"]) < 10 - 0.01)
    assert seat["d"] == D and seat["z1"] - seat["z0"] == pytest.approx(B)
    assert shoulder["n"] == -1 and shoulder["z"] == pytest.approx(seat["z1"])  # bored from -Z, shoulder at its end
    p = direct.plan(doc, _t(doc, "Planet gear"))
    assert p["path"] == "direct", p.get("reasons")
    src = p["script"]
    depth = shoulder["z"] + 20 / 2
    bore = math.floor(2 * (D - (D - d) / 4)) / 2
    assert (_num(src, "SEAT_D"), _num(src, "SEAT_DEPTH"), _num(src, "BORE")) == (D, depth, bore)
    assert bore > (d + D) / 2  # the shoulder clears the turning inner ring
    assert {"6204": 40.0, "6004": 36.5}[designation] == bore
    assert "seats=[(SEAT_D, SEAT_DEPTH, -1)]" in src and "backlash=0.04 * MODULE" in src
    # hand volume: the involute profile x face width, less the through shoulder bore and the seat counterbore
    hand = spur_area(2, 30, 0.08) * 20 - math.pi / 4 * bore ** 2 * 20 - math.pi / 4 * (D ** 2 - bore ** 2) * depth
    gear, e = fw_std.spur_gear(2, 30, 20, bore=bore, seats=[(D, depth, -1)], backlash=0.08, z0=-10)
    assert e["volume"] == pytest.approx(hand, rel=1e-6)
    if designation == "6204":
        assert gear.volume == pytest.approx(hand, rel=1e-5)
        return
    st, res, info = _gate(tmp_path, doc, "Planet gear", src)
    assert st["fingerprint"]["volume"] == pytest.approx(hand, rel=1e-5)
    assert res["ok"] and res["envelope"]["ok"], [r for x in res["interfaces"] for r in x["rows"] if not r["ok"]]
    rows = {r["feature"]: r for x in res["interfaces"] for r in x["rows"]}
    assert rows[seat["label"]]["ok"] and rows[seat["label"]]["d_mm"] == pytest.approx(D, abs=1e-6)
    assert rows[shoulder["label"]]["ok"]
    assert info["component"]["kind"] == "spur_gear" and info["component"]["params"]["teeth"] == 30


def test_seat_refusals_send_the_gear_to_the_designer(pdoc: dict[str, Any]) -> None:
    pid = _item(pdoc, "Planet gear")
    d2 = copy.deepcopy(pdoc)
    for f in d2["icd"]["interfaces"]:  # no shoulder: the seat runs from face to face
        if f["kind"] == "bearing_seat" and f["a"]["item"] == pid:
            mid = (f["data"]["z"][0] + f["data"]["z"][1]) / 2  # the 20 mm face, whatever bearing (6004 since the rim rule)
            f["data"]["z"] = [mid - 10, mid + 10]
            for s in f["data"].get("seats") or []:
                s["z"] = f["data"]["z"]
    p = direct.plan(d2, _t(d2, "Planet gear"))
    assert p["path"] == "agent" and p["reasons"], p
    with pytest.raises(ValueError, match="shoulder"):
        fw_std.spur_gear(2, 30, 20, bore=40, seats=[(47, 10, -1), (47, 10, 1)])
    with pytest.raises(ValueError, match="rim"):
        fw_std.spur_gear(2, 30, 20, bore=40, seats=[(54, 10, -1)])


def test_toolbox_ring_gear_matching_and_limits() -> None:
    m = toolbox.match("ring gear m2 z90")
    assert m and m[0]["code"] == "internal_gear" and (m[0]["params"]["M"], m[0]["params"]["Z"]) == (2, 90)
    assert toolbox.match("spur gear m2 z30")[0]["code"] == "spur_gear"
    with pytest.raises(toolbox.ToolboxError, match="rim OD"):
        toolbox.build("internal_gear", M=2, Z=90, B=20, OD=186)
    assert "internal_gear" in {c["code"] for c in toolbox.catalog()}
