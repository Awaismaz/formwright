"""Keys, retaining rings, chamfered bearings and keyed Toolbox gears (live gear run 2026-11-19, branch
wip/toolbox-keys). Every expected value is a hand calculation from the standard tables:

* DIN 6885-1, shaft over 17 up to 22 mm: key b x h = 6 x 6, shaft groove t1 = 3.5, hub groove t2 = 2.8.
* DIN 471, d1 = 20: ring s = 1.2, b = 2.6 (approx.), groove d2 = 19.0, m = 1.3 (H13), n min 1.5.
* ISO 15 / ISO 582, 6204: d 20, D 47, B 14, r_s min 1.0.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
from test_office_icd import _prepare
from test_office_orchestrator import office  # noqa: F401  (fixture)
from test_office_shaft_line import _parts

from aicad import toolbox
from aicad.office import conformance, frames, icd, platform_env

# The live run's plan, as Archie wrote it: two sub-assemblies, each with its key and circlips.
LIVE = {"source": "standard", "summary": "Spur gear pair 1:3", "assumptions": [], "subassemblies": [
    {"name": "Pinion shaft assembly", "description": "", "parts": [
        {"name": "Pinion", "family": "gear", "complexity": 2, "qty": 1,
         "description": "Spur pinion module 2, 20 teeth, face width 20, bore 20 with a DIN 6885 keyway, 42CrMo4"},
        {"name": "Pinion shaft", "family": "turned", "complexity": 2, "qty": 1, "description": "shaft 20 mm diameter"},
        {"name": "Pinion key", "family": "standard", "complexity": 1, "qty": 1,
         "description": "Parallel key DIN 6885 A 6x6x18"},
        {"name": "Pinion circlip", "family": "standard", "complexity": 1, "qty": 2,
         "description": "DIN 471 retaining ring for 20 mm shaft, next to the 6204"},
        {"name": "Deep groove ball bearing 6204", "family": "standard", "complexity": 1, "qty": 2,
         "description": "6204"}]},
    {"name": "Gear shaft assembly", "description": "", "parts": [
        {"name": "Gear", "family": "gear", "complexity": 2, "qty": 1,
         "description": "Spur gear module 2, 60 teeth with a keyway, C45"},
        {"name": "Gear shaft", "family": "turned", "complexity": 2, "qty": 1, "description": "shaft 20 mm diameter"},
        {"name": "Gear key", "family": "standard", "complexity": 1, "qty": 1, "description": "Parallel key DIN 6885 A"},
        {"name": "Gear circlip", "family": "standard", "complexity": 1, "qty": 4, "description": "Circlip DIN 471"},
        {"name": "Gear shaft bearing 6204", "family": "standard", "complexity": 1, "qty": 2,
         "description": "6204"}]}]}
P_PIN, P_SH, P_KEY, P_RING, P_BRG = "i_s1_p1", "i_s1_p2", "i_s1_p3", "i_s1_p4", "i_s1_p5"
G_GEAR, G_SH, G_KEY, G_RING, G_BRG = "i_s2_p6", "i_s2_p7", "i_s2_p8", "i_s2_p9", "i_s2_p10"


def _strip(R: float, b: float) -> float:
    """Area of a radius-R disc inside |y| <= b/2 on the x >= 0 side: ∫ sqrt(R² - y²) dy (closed form)."""
    def F(v: float) -> float:
        return v / 2 * math.sqrt(R * R - v * v) + R * R / 2 * math.asin(v / R)
    return F(b / 2) - F(-b / 2)


def _overlap(a: Any, b: Any) -> float:
    """Common volume solid by solid (a boolean on a whole multi-solid compound is not reliable)."""
    out = 0.0
    for x in a.solids():
        for y in b.solids():
            c = x & y
            out += c.volume if c is not None else 0.0
    return out


def test_standard_tables_hand_checked() -> None:
    assert toolbox.key_row(20) == (6, 6, 3.5, 2.8)
    assert toolbox.key_row(22) == (6, 6, 3.5, 2.8)        # "up to 22" includes 22
    assert toolbox.key_row(22.5) == (8, 7, 4.0, 3.3)
    with pytest.raises(toolbox.ToolboxError):
        toolbox.key_row(8)                                   # "over 8": Ø8 is outside the table
    # one standard, two consumers: the ICD's key table is the Toolbox's
    assert [(r, tuple(float(x) for x in v)) for r, v in icd.KEYS] == \
        [(r, tuple(float(x) for x in v)) for r, v in toolbox.KEY_ROWS]
    s, b, d2, m, n = toolbox.ring_row(20)
    assert (s, d2, m, n) == (1.2, 19.0, 1.3, 1.5) and b == 2.6
    assert (20 - d2) / 2 == pytest.approx(0.5)               # groove depth t
    assert toolbox.ring_row(25) == (1.2, 3.0, 23.9, 1.3, 1.7)
    assert toolbox.ring_row(30) == (1.5, 3.5, 28.6, 1.6, 2.1)
    with pytest.raises(toolbox.ToolboxError):
        toolbox.ring_row(23)                                 # not a DIN 471 size
    assert icd.RINGS[20] == (1.2, 2.6, 19.0, 1.3, 1.5)
    assert toolbox.BEARING_RS[6204] == 1.0 and set(toolbox.BEARING_RS) == set(toolbox.BEARING)


def test_key_ring_and_keyed_gear_volumes_hand_checked() -> None:
    key, e = toolbox.build("parallel_key", D=20, L=18)
    # form A: a 6 x 12 rectangle plus two half discs r = 3, times h = 6: 6 (72 + 9 π) = 432 + 54 π
    assert e["volume"] == pytest.approx(432 + 54 * math.pi) and key.volume == pytest.approx(432 + 54 * math.pi)
    assert e["bbox"] == [18, 6, 6]
    assert toolbox.spec("parallel_key").title({"D": 20, "L": 18}) == "Parallel key DIN 6885 A 6×6×18"
    ring, e = toolbox.build("retaining_ring", D=20)
    # as fitted: Ø19 .. Ø19 + 2 x 2.6 = Ø24.2, s 1.2: π / 4 (24.2² - 19²) 1.2 = 67.392 π
    assert e["volume"] == pytest.approx(67.392 * math.pi) and ring.volume == pytest.approx(67.392 * math.pi)
    assert e["bbox"] == pytest.approx([24.2, 24.2, 1.2])
    plain, ep = toolbox.build("spur_gear", M=2, Z=20, B=20, BORE=20)
    keyed, ek = toolbox.build("spur_gear", M=2, Z=20, B=20, BORE=20, KEY_B=6, KEY_T2=2.8, KEY_ANG=-3)
    # the hub keyway removes b (R + t2) minus the disc inside the strip: 6 x 12.8 - 59.0874... = 17.7126 mm², x 20
    removed = (6 * 12.8 - _strip(10, 6)) * 20
    assert removed == pytest.approx(354.2511, abs=1e-3)
    assert ep["volume"] - ek["volume"] == pytest.approx(removed)
    assert plain.volume - keyed.volume == pytest.approx(removed, rel=1e-6)
    assert toolbox.spec("spur_gear").title(toolbox.normalize("spur_gear", {"M": 2, "Z": 20, "B": 20, "BORE": 20,
                                                                           "KEY_B": 6, "KEY_T2": 2.8})) \
        == "Spur gear m2 z20, keyed 6×2.8"
    with pytest.raises(toolbox.ToolboxError):  # the keyway would break into the root: R + t2 >= rf - m / 2
        toolbox.build("spur_gear", M=2, Z=20, B=20, BORE=26, KEY_B=8, KEY_T2=4)  # 13 + 4 >= 17.5 - 1


def test_bearing_rings_carry_their_corner_chamfer() -> None:
    _s, e = toolbox.build("bearing", SERIES=6204)
    d, D, B, c = 20, 47, 14, 1.0
    w = (D - d) / 2 * 0.3
    sharp = math.pi / 4 * B * (((d + 2 * w) ** 2 - d * d) + (D * D - (D - 2 * w) ** 2))
    # Pappus: a 45° chamfer c removes c² / 2 at radius r ± c / 3; two bore corners, two outside corners
    cut = 2 * 2 * math.pi * c * c / 2 * (d / 2 + c / 3) + 2 * 2 * math.pi * c * c / 2 * (D / 2 - c / 3)
    balls = e["volume"] - (sharp - cut)
    assert balls > 0 and toolbox.VERSION >= 2  # v2 added the chamfers; later versions keep them
    _s0, e0 = toolbox.build("bearing", SERIES=6000)  # r_s min 0.3
    assert e0["bbox"] == [26, 26, 8]


@pytest.mark.parametrize("r, clash", [(0.4, False), (1.0, False), (1.5, True)])
def test_shaft_shoulder_fillet_up_to_rs_min_clears_the_bearing(r: float, clash: bool) -> None:
    """A Ø26 shoulder with a fillet r into a Ø20 journal; the 6204 sits on the journal against the shoulder face
    (base face on Z 0). ISO 582: a fillet r <= r_s min (1.0) leaves the ring corner alone: 0 mm³ (the live run had
    2.2 mm³ per bearing with r 0.4 against sharp corners); r 1.5 > r_s min must still clash."""
    from build123d import Align, Cylinder, Pos, fillet

    shaft = Pos(0, 0, -10) * Cylinder(13, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)) + \
        Cylinder(10, 30, align=(Align.CENTER, Align.CENTER, Align.MIN))
    corner = shaft.edges().filter_by(lambda e: e.geom_type.name == "CIRCLE" and abs(e.radius - 10) < 1e-6
                                     and abs(e.center().Z) < 1e-6)
    shaft = fillet(corner, r)
    brg, _e = toolbox.build("bearing", SERIES=6204)
    v = _overlap(shaft, brg)
    assert (v > 1e-3) is clash, v
    if not clash:
        assert v == pytest.approx(0, abs=1e-6)


def test_icd_places_keys_and_rings_and_hex_takes_them() -> None:
    parts = _parts(LIVE)
    sk, ifs = icd.build(parts, "Simple spur gear pair 1:3, m2 20/60, shafts Ø20, four 6204 bearings, no housing")
    assert icd.problems(sk, ifs) == [] and icd.warnings(sk, ifs) == []
    keys = [f for f in ifs if f["kind"] == "key"]
    assert [(f["data"]["key_item"], f["data"]["b"], f["data"]["h"], f["data"]["t1"], f["data"]["t2"],
             f["data"]["length"], f["data"]["z"]) for f in keys] == [
        (P_KEY, 6, 6, 3.5, 2.8, 18, [-9, 9]), (G_KEY, 6, 6, 3.5, 2.8, 18, [-9, 9])]
    # rings: the 20-wide gears span Y -10..10; a ring of each sub-assembly at both gear faces first, then the
    # gear shaft's two spare rings at the outboard faces of its bearings (Y -29 - 1.2 and 29); ids after the mesh
    rings = [f for f in ifs if f["kind"] == "retaining_ring"]
    assert [(f["id"], f["a"]["item"], f["data"]["ring_item"], f["data"]["against"], f["data"]["z"],
             f["data"]["groove_z"]) for f in rings] == [
        ("IF-10", P_SH, P_RING, "hub", [-11.2, -10], [-11.3, -10]),
        ("IF-11", P_SH, P_RING, "hub", [10, 11.2], [10, 11.3]),
        ("IF-12", G_SH, G_RING, "hub", [-11.2, -10], [-11.3, -10]),
        ("IF-13", G_SH, G_RING, "hub", [10, 11.2], [10, 11.3]),
        ("IF-14", G_SH, G_RING, "bearing", [-30.2, -29], [-30.3, -29]),
        ("IF-15", G_SH, G_RING, "bearing", [29, 30.2], [29, 30.3])]
    assert next(f for f in ifs if f["kind"] == "gear_mesh")["id"] == "IF-09"
    d = rings[0]["data"]
    assert (d["d"], d["s"], d["d2"], d["m"], d["n"], d["t"], d["standard"]) == (20, 1.2, 19.0, 1.3, 1.5, 0.5, "DIN 471")
    # seated: the key's underside on the keyseat floor, 10 - 3.5 = 6.5 from the axis along +X (dir), its length
    # along the shaft (+Y), its height out along +X; the rings with their own Z along +Y from the lower face
    k = icd.seated(ifs, P_KEY)
    assert k is not None and k["code"] == "parallel_key" and k["params"] == {"D": 20, "L": 18}
    assert k["at"] == [[6.5, 0, 0]] and frames.apply(k["R"], [1, 0, 0]) == [0, 1, 0] \
        and frames.apply(k["R"], [0, 0, 1]) == [1, 0, 0] and frames.det(k["R"]) == 1
    assert icd.seated(ifs, G_KEY)["at"] == [[86.5, 0, 0]]  # type: ignore[index]
    rg = icd.seated(ifs, G_RING)
    assert rg is not None and rg["params"] == {"D": 20} and rg["R"] == frames.CANON["y"]
    assert rg["at"] == [[80, -11.2, 0], [80, 10, 0], [80, -30.2, 0], [80, 29, 0]]
    # the shaft carries the grooves; the excerpt tells its designer where
    feats = icd.item_features(sk, ifs, P_SH)
    grooves = [f for f in feats if f["type"] == "groove"]
    assert [(g["d"], g["z0"], g["z1"]) for g in grooves] == [(19, -11.3, -10), (19, 10, 11.3)]
    ex = icd.excerpt(sk, {"version": 1, "interfaces": ifs}, P_SH)
    assert "retaining ring groove Ø19 × 1.3 H13 (DIN 471 20)" in ex and "depth 0.5 on the Ø20 shaft" in ex
    # Hex: keys and rings from the ICD; the pinion and the gear as keyed Toolbox gears in the plan's material
    doc = {"items": [{"id": p["id"], "description": p["description"], "toolbox": None} for p in parts],
           "skeleton": sk, "icd": {"interfaces": ifs, "version": 1, "status": "approved"}}
    # the direct builder (office.direct, on by default) builds the keyed gears from the interfaces: Hex leaves them
    assert platform_env.hex_lookup(doc, {"title": "Pinion", "kind": "part", "item_id": P_PIN}, []) is None
    doc["direct_build"] = False  # with it off, the Toolbox gear carries the keyway and the plan's material

    def hex_(iid: str, title: str, kind: str = "standard") -> dict[str, Any] | None:
        return platform_env.hex_lookup(doc, {"title": title, "kind": kind, "item_id": iid}, [])

    assert hex_(P_KEY, "Pinion key")["title"] == "Parallel key DIN 6885 A 6×6×18"  # type: ignore[index]
    assert hex_(G_RING, "Gear circlip")["title"] == "Retaining ring DIN 471 20×1.2"  # type: ignore[index]
    pin = hex_(P_PIN, "Pinion", "part")
    assert pin is not None and pin["params"] == {"M": 2, "Z": 20, "B": 20, "BORE": 20, "KEY_B": 6, "KEY_T2": 2.8,
                                                 "KEY_ANG": 0}
    assert pin["material"] == "42CrMo4" and pin["designed"] is True
    gear = hex_(G_GEAR, "Gear", "part")  # "with a keyway" no longer reads as custom work
    phase = sk["items"][G_GEAR]["phase"]
    assert gear is not None and gear["params"]["KEY_B"] == 6 and gear["material"] == "C45"
    assert gear["params"]["KEY_ANG"] == pytest.approx(-phase, abs=1e-6)  # the program's +X in the turned gear


def test_toolbox_gear_is_never_swapped_in_without_an_icd_feature() -> None:
    parts = _parts(LIVE)
    sk, ifs = icd.build(parts, "")
    doc = {"items": [{"id": p["id"], "description": p["description"], "toolbox": None} for p in parts],
           "skeleton": sk, "icd": {"interfaces": ifs, "version": 1, "status": "approved"}}
    # an extra ICD feature on the gear (a second, off-axis hole) the Toolbox gear can't carry: it stays designed
    extra = {"id": "IF-99", "kind": "dowel", "a": {"item": G_GEAR, "copy": 0, "name": "Gear"},
             "b": {"item": G_SH, "copy": 0, "name": "Gear shaft"}, "datums": [], "edited": [],
             "data": {"d": 4, "fit": "H7/m6", "positions": [[110, 0]], "plane_z": 0, "ax": "y", "length": 8,
                      "position_tol": 0.1, "standard": "ISO 8734"}}
    params, why = platform_env.toolbox_gear_for({**doc, "icd": {"interfaces": [*ifs, extra], "version": 1}},
                                                G_GEAR, {})
    assert params is None and "dowel hole" in why
    hit = platform_env.hex_lookup({**doc, "icd": {"interfaces": [*ifs, extra], "version": 1}},
                                  {"title": "Gear", "kind": "part", "item_id": G_GEAR}, [])
    assert hit is None
    # without an ICD a keyed gear can't be sized: designed too
    bare = {"items": [{"id": "g", "description": "Spur gear module 2, 60 teeth, face width 20, bore 20, keyed"}]}
    assert platform_env.hex_lookup(bare, {"title": "Gear", "kind": "part", "item_id": "g"}, []) is None
    assert platform_env.plan_material("Spur pinion in 18CrNiMo7-6, case hardened") == "18CrNiMo7-6"
    assert platform_env.plan_material("pinion, no material given") is None


def test_keyed_shaft_line_parts_fit_without_interference(tmp_path: Path) -> None:
    """Kernel check of the ICD numbers: the shaft (placeholder with its keyseat and grooves), the keyed Toolbox
    pinion, the key, both rings and both bearings placed where Fitz puts them overlap nowhere (< 1e-6 mm³), and
    the shaft and the keyed gear conform to the ICD (keyway, grooves measured)."""
    import numpy as np
    from build123d import Location, Pos

    from aicad.assembly import placeholder
    from aicad.assembly.geometry import _trsf
    from aicad.office import program_assembly

    parts = _parts(LIVE)
    sk, ifs = icd.build(parts, "")
    doc = {"version": 1, "interfaces": ifs}

    def at(shape: Any, T12: list[float]) -> Any:
        T = np.array(T12 + [0, 0, 0, 1], dtype=float).reshape(4, 4)
        return shape.moved(Location(_trsf(T)))

    shaft_spec = icd.placeholder_spec(sk, ifs, P_SH)
    assert len(shaft_spec["grooves"]) == 2
    shaft0 = placeholder.shape(shaft_spec)
    res = conformance.measure(sk, doc, P_SH, *_prepare(tmp_path, shaft0, "shaft"))
    assert res["ok"], [r for x in res["interfaces"] for r in x["rows"] if not r["ok"]]
    shaft = at(shaft0, program_assembly.place(sk, P_SH, 0))
    full = {"items": [{"id": p["id"], "description": p["description"]} for p in parts], "skeleton": sk,
            "icd": {"interfaces": ifs, "version": 1}}
    gp, _why = platform_env.toolbox_gear_for(full, P_PIN, {})
    assert gp is not None
    g0, _e = toolbox.build("spur_gear", **gp)
    res = conformance.measure(sk, doc, P_PIN, *_prepare(tmp_path, Pos(0, 0, -10) * g0, "gear"))
    assert res["ok"], [r for x in res["interfaces"] for r in x["rows"] if not r["ok"]]
    gear = at(Pos(0, 0, -10) * g0, program_assembly.place(sk, P_PIN, 0))
    placed = {"shaft": shaft, "gear": gear}
    for item, name in ((P_KEY, "key"), (P_RING, "ring"), (P_BRG, "bearing")):
        seat = icd.seated(ifs, item)
        assert seat is not None
        shape, _e = toolbox.build(seat["code"], **seat["params"])
        for n, p in enumerate(seat["at"]):
            placed[f"{name}{n}"] = at(shape, frames.to12(seat.get("R") or frames.IDENT, p))
    names = sorted(placed)
    assert names == ["bearing0", "bearing1", "gear", "key0", "ring0", "ring1", "shaft"]
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            v = _overlap(placed[a], placed[b])
            assert v < 1e-6, (a, b, v)
    # and the parts do touch: the key sits on its keyseat floor, the rings against the gear faces
    assert placed["key0"].distance_to(placed["shaft"]) < 1e-6
    assert placed["ring0"].distance_to(placed["gear"]) < 1e-6 and placed["ring1"].distance_to(placed["gear"]) < 1e-6


def test_bom_lists_a_toolbox_made_gear_as_made_in_the_plan_material() -> None:
    """Live run: the pinion Hex took from the Toolbox was in the BOM as "Steel C45, buy"; it is a designed part
    (sized by the ICD), made in the plan's 42CrMo4. Keys and rings stay bought."""
    from aicad.office import deliverables

    tickets = [
        {"id": "t1", "key": "GP-1", "kind": "part", "item_id": "pin", "title": "Pinion", "qty": 1,
         "reuse": {"source": "toolbox", "code": "spur_gear", "title": "Spur gear m2 z20, keyed 6×2.8",
                   "material": "42CrMo4", "designed": True}},
        {"id": "t2", "key": "GP-2", "kind": "standard", "item_id": "key", "title": "Pinion key", "qty": 1,
         "reuse": {"source": "toolbox", "code": "parallel_key", "title": "Parallel key DIN 6885 A 6×6×18",
                   "standard": "DIN 6885-1 A"}}]
    rows = [{"part": "Spur gear m2 z20, keyed 6×2.8", "kind": "toolbox", "code": "spur_gear", "qty": 1,
             "part_key": "k1", "instances": ["g1"], "designation": "Spur gear m2 z20, keyed 6×2.8",
             "standard": "ISO 53 profile, α = 20°", "material": "Steel C45", "mass_each_g": 140.0},
            {"part": "Parallel key DIN 6885 A 6×6×18", "kind": "toolbox", "code": "parallel_key", "qty": 1,
             "part_key": "k2", "instances": ["e1"], "designation": "Parallel key DIN 6885 A 6×6×18",
             "standard": "DIN 6885-1 A", "material": "Steel C45+C (bright key steel)", "mass_each_g": 4.7}]
    b = deliverables.bom(tickets, rows, {"g1": {"item": "pin"}, "e1": {"item": "key"}}, {}, {})
    assert [(r["part"], r["make_buy"], r["material"]) for r in b["rows"]] == [
        ("Spur gear m2 z20, keyed 6×2.8", "make", "42CrMo4"),
        ("Parallel key DIN 6885 A 6×6×18", "buy", "Steel C45+C (bright key steel)")]
    b0 = deliverables.bom(tickets, None)  # before the assembly: from the tickets
    r0 = b0["rows"][0]
    assert (r0["part"], r0["make_buy"], r0["material"]) == ("Pinion", "make", "42CrMo4")


def test_studio_matching_reads_keys_and_rings_not_their_hosts() -> None:
    assert toolbox.match("Pinion key")[0]["code"] == "parallel_key"
    m = toolbox.match("parallel key DIN 6885 6x6x18")[0]
    assert m["code"] == "parallel_key" and m["params"] == {"D": 22.0, "L": 18.0}
    assert toolbox.match("Gear circlip")[0]["code"] == "retaining_ring"
    assert toolbox.match("DIN 471 retaining ring for a Ø25 shaft")[0]["params"] == {"D": 25}
    assert toolbox.match("spur gear m2 z60 with a keyway")[0]["code"] == "spur_gear"   # a keyway is not custom work
    assert toolbox.match("spur gear m2 z60 with a hub") == []                          # a hub still is
    assert toolbox.match("the key features of this bracket") == []
    with pytest.raises(toolbox.ToolboxError):
        toolbox.build("parallel_key", D=20, L=5)  # not longer than b
    with pytest.raises(toolbox.ToolboxError):
        toolbox.normalize("retaining_ring", {"D": 23})


def test_live_plan_assembles_with_keys_and_rings_seated(office: Any) -> None:  # noqa: F811
    """The live run's plan end to end with simulated agents: Hex takes the keys and circlips from the Toolbox sized
    by the ICD and both gears as keyed Toolbox gears; Fitz seats 4 bearings, 2 keys and 6 rings where the ICD says;
    the final assembly has no clash and nothing is left in the parts bin."""
    from test_office_icd import _asm
    from test_office_orchestrator import _program, _wait

    from aicad.assembly import store as astore

    c = office
    v = _program(c, "keys@x.com", LIVE, brief="Simple spur gear pair 1:3, m2 20/60, Ø20 shafts, four 6204, no housing.")
    pid = v["id"]
    assert v["assembly"]["status"] == "ready" and v["assembly"]["clashes"] == [], v["assembly"].get("summary")
    c.post(f"/api/office/programs/{pid}/run")
    v = _wait(c, pid, lambda v: v["orchestrator"]["state"] in ("complete", "blocked", "stopped"), timeout=1500)
    assert v["status"] == "complete", [(t["title"], t["column"], (t.get("run") or {}).get("status")) for t in v["tickets"]]
    by = {t["title"]: t for t in v["tickets"]}
    assert (by["Pinion key"]["reuse"]["code"], by["Gear circlip"]["reuse"]["code"]) == ("parallel_key", "retaining_ring")
    # the shafts and gears are built from the interfaces (office.direct, no AI): each shaft with its keyseat and the
    # DIN 471 grooves of its rings, each gear with its hub keyway; Gage measured them against the ICD and approved
    summary = {"Pinion shaft": "1 keyseat, 2 circlip grooves", "Gear shaft": "1 keyseat, 4 circlip grooves",
               "Pinion": "with a keyway", "Gear": "with a keyway"}
    for name, want in summary.items():
        d = by[name].get("direct") or {}
        assert d.get("path") == "direct" and d["summary"].endswith(want), (name, d)
        gage = next(cm["text"] for cm in by[name]["comments"] if cm["by"].get("code") == "gage")
        assert gage.startswith("Approved"), (name, gage)
    st = v["assembly"]
    assert st["clashes"] == [], st.get("summary")
    final = astore.load(_asm(c)[0], st["final"])
    seated: dict[str, list[tuple[float, float, float]]] = {}
    for i in final["instances"]:
        o = i.get("office") or {}
        assert not o.get("bin"), i.get("name")
        if o.get("seated"):
            seated.setdefault(i["name"], []).append((round(i["T"][3], 3), round(i["T"][7], 3), round(i["T"][11], 3)))
    assert sorted(seated["Pinion key"]) == [(6.5, 0, 0)] and sorted(seated["Gear key"]) == [(86.5, 0, 0)]
    assert sorted(seated["Pinion circlip"]) == [(0, -11.2, 0), (0, 10, 0)]
    assert sorted(seated["Gear circlip"]) == [(80, -30.2, 0), (80, -11.2, 0), (80, 10, 0), (80, 29, 0)]
    assert sum(len(x) for x in seated.values()) == 4 + 2 + 6
