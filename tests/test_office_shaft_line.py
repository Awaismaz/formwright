"""Shaft lines (assembly reliability wave, 2026-11-19): a mechanism with no housing or base plate is carried by its
own shafts and bearings. The founder's test case: a 1:3 spur pair (m2, 20 / 60 teeth), two Ø20 shafts, four 6204
bearings, nothing else. Before this the layout fell back to "a row of parts, no interfaces" and the ICD gate passed
it with no problem. Positions are hand checked; degenerate layouts are ICD problems with stable codes; placeholders
conform, bearings are seated and mated, the shafts turn, and the simulated program assembles with no clash. No live
AI (fake agents)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from test_office_icd import _prepare
from test_office_orchestrator import _wait, office  # noqa: F401  (fixture)

from aicad.office import conformance, frames, icd, planner

PAIR = {"source": "standard", "summary": "Spur gear pair 1:3", "assumptions": [], "subassemblies": [
    {"name": "Gear pair", "description": "", "parts": [
        {"name": "Pinion", "family": "gear", "complexity": 2, "qty": 1, "description": "spur pinion module 2, 20 teeth"},
        {"name": "Gear", "family": "gear", "complexity": 2, "qty": 1, "description": "spur gear module 2, 60 teeth"},
        {"name": "Input shaft", "family": "turned", "complexity": 2, "qty": 1,
         "description": "shaft 20 mm diameter, 120 long"},
        {"name": "Output shaft", "family": "turned", "complexity": 2, "qty": 1,
         "description": "shaft 20 mm diameter, 120 long"},
        {"name": "Deep groove ball bearing 6204", "family": "standard", "complexity": 1, "qty": 4,
         "description": "6204 ball bearing"}]}]}
PIN, GEAR, S_IN, S_OUT, BRG = "i_s1_p1", "i_s1_p2", "i_s1_p3", "i_s1_p4", "i_s1_p5"


def _parts(plan: dict[str, Any]) -> list[dict[str, Any]]:
    p = planner.normalise_plan(plan, "standard")
    assert p is not None
    return [{"id": f"i_{s['id']}_{q['id']}", "name": q["name"], "family": q["family"], "qty": q["qty"],
             "description": q["description"], "complexity": q["complexity"], "sub": f"i_{s['id']}"}
            for s in p["subassemblies"] for q in s["parts"]]


def _plan(*parts: dict[str, Any]) -> dict[str, Any]:
    return {"source": "standard", "summary": "x", "assumptions": [],
            "subassemblies": [{"name": "A", "description": "", "parts": list(parts)}]}


def _g(name: str, desc: str) -> dict[str, Any]:
    return {"name": name, "family": "gear", "complexity": 2, "qty": 1, "description": desc}


def _s(name: str) -> dict[str, Any]:
    return {"name": name, "family": "turned", "complexity": 2, "qty": 1, "description": "Shaft Ø20 x 100"}


def _b(qty: int) -> dict[str, Any]:
    return {"name": "Deep groove ball bearing 6204", "family": "standard", "complexity": 1, "qty": qty,
            "description": "6204"}


def _by_name(sk: dict[str, Any]) -> dict[str, str]:
    return {it["name"]: i for i, it in sk["items"].items()}


def test_spur_pair_on_its_own_shafts_hand_checked() -> None:
    sk, ifs = icd.build(_parts(PAIR), "Simple spur gear pair 1:3 with shafts and bearings")
    it = sk["items"]
    assert sk["layout"] == "shaft_line" and sk["base"] == S_IN and icd.problems(sk, ifs) == []
    assert icd.warnings(sk, ifs) == []
    # gears on their own shafts: the pinion (input by name) on the input shaft, the gear on the other one
    assert (it[PIN]["parent"], it[GEAR]["parent"], it[S_IN]["parent"], it[S_OUT]["parent"]) == (S_IN, S_OUT, None, None)
    # centre distance a = m (z1 + z2) / 2 = 2 (20 + 60) / 2 = 80; input shaft axis on X = 0, both axes on Z = 0
    # (datum A, the plane of the shaft axes), the mesh on Y = 0 (datum B)
    assert it[PIN]["copies"] == [[0, 0, 0]] and it[GEAR]["copies"] == [[80, 0, 0]]
    assert all(it[i].get("ax") == "y" for i in (PIN, GEAR, S_IN, S_OUT))
    # envelopes: tip circles m (z + 2) = 44 / 124, face width 10 m = 20; shafts Ø20 (the 6204 bore, and written)
    # x 120 (written); the 6204 is 20 x 47 x 14
    assert it[PIN]["size"] == [44, 44, 20] and it[GEAR]["size"] == [124, 124, 20]
    assert it[S_IN]["size"] == [20, 20, 120] and it[S_IN]["copies"] == [[0, 0, 0]]
    assert it[S_OUT]["size"] == [20, 20, 120] and it[S_OUT]["copies"] == [[80, 0, 0]]
    assert [d["name"] for d in sk["datums"]] == ["Plane of the shaft axes", "Mesh plane (first gear pair)",
                                                 "Input shaft axis plane (YZ)"]
    assert [(a["origin"], a["dir"]) for a in sk["axes"]] == [([0, 0, 0], [0, 1, 0]), ([80, 0, 0], [0, 1, 0])]
    kinds = [(f["id"], f["kind"], f["a"]["item"], f["b"]["item"], f["b"]["copy"]) for f in ifs]
    assert kinds == [("IF-01", "bearing_journal", S_IN, BRG, 0), ("IF-02", "bearing_journal", S_IN, BRG, 1),
                     ("IF-03", "shaft_bore", PIN, S_IN, 0), ("IF-04", "bearing_journal", S_OUT, BRG, 2),
                     ("IF-05", "bearing_journal", S_OUT, BRG, 3), ("IF-06", "shaft_bore", GEAR, S_OUT, 0),
                     ("IF-07", "gear_mesh", PIN, GEAR, 0)]
    # bearings one either side of everything that turns near the shaft: the gears span Y -10..10 (the big gear's tip
    # circle r 62 reaches over the input shaft's bearings, r 23.5, at 80 mm), 5 mm clear, 14 wide:
    # -Y bearing on Y -29..-15, +Y bearing on Y 15..29 (inner faces 5 mm from the gear faces)
    for iid, x in (("IF-01", 0), ("IF-02", 0), ("IF-04", 80), ("IF-05", 80)):
        d = next(f for f in ifs if f["id"] == iid)["data"]
        assert (d["designation"], d["d"], d["D"], d["B"], d["shaft_fit"], d["ax"]) == ("6204", 20, 47, 14, "k6", "y")
        assert d["axis"] == [x, 0] and d["shoulder_z"] is None  # Ø20 shaft = the bearing bore: a plain journal
        assert d["z"] == ([-29, -15] if d["side"] < 0 else [15, 29])
    mesh = ifs[6]["data"]
    assert (mesh["centre_distance"], mesh["ratio"], mesh["axis_a"], mesh["axis_b"], mesh["plane_a"], mesh["plane_b"]) \
        == (80, 3, [0, 0], [80, 0], 0, 0)
    # tooth phasing: the pinion has a tooth on +X (towards the gear), so the 60-tooth gear (pitch 6 deg) shows a
    # space towards it: a tooth half a pitch off its -X direction, 3 deg
    assert it[GEAR]["phase"] == 3.0 and mesh["phase_b"] == 3.0
    # the shaft in its own part frame (modelled along Z, 120 long, centred): journals Z -29..-15 and 15..29
    sf = icd.item_features(sk, ifs, S_IN)
    j = [(f["c"], f["z0"], f["z1"], f["d"], f["fit"]) for f in sf if f["type"] == "boss" and f.get("z0") is not None]
    assert j == [([0, 0], -29, -15, 20, "k6"), ([0, 0], 15, 29, 20, "k6")] and not any(f.get("ax") for f in sf)
    # Fitz seats the four bearings at their base faces (Y -29 / 15), the bearing's own Z along +Y
    st = icd.seated(ifs, BRG)
    assert st["at"] == [[0, -29, 0], [0, 15, 0], [80, -29, 0], [80, 15, 0]] and st["R"] == frames.CANON["y"]
    assert st["interfaces"] == ["IF-01", "IF-02", "IF-04", "IF-05"]
    # the bearing side of a journal, in the bearing's own frame: its bore Ø20 over its width
    assert icd.side_features(sk, ifs[0], "b")[0] == {"type": "seat", "c": [0.0, 0.0], "z0": 0.0, "z1": 14.0, "d": 20,
                                                     "tol": 0.1, "label": "bearing bore Ø20 (6204)", "if": "IF-01"}
    # excerpts: journals with their positions, where the gear sits, the gear bore
    ex = icd.excerpt(sk, {"version": 1, "interfaces": ifs}, S_IN)
    assert "1 × Deep-groove ball bearing 6204 (bore 20, OD 47, width 14); bearing journal Ø20 k6 (6204, -Z end) on " \
           "the axis at (X, Y) (0, 0) from Z -29 to -15" in ex
    assert "from Z 15 to 29" in ex and "where Pinion sits from Z -10 to 10" in ex
    assert "bore Ø20 H7 through" in icd.excerpt(sk, {"version": 1, "interfaces": ifs}, PIN)
    # placeholders: shafts Ø20 x 120, gears at their pitch circles (Ø40 / Ø120, they touch, never clash) bored Ø20
    assert icd.placeholder_spec(sk, ifs, S_IN)["size"] == [20, 20, 120]
    gp = icd.placeholder_spec(sk, ifs, GEAR)
    assert gp["size"] == [120, 120, 20] and gp["holes"] == [{"c": [0.0, 0.0], "d": 20}]
    # assembly placement of the output shaft: part Z along program +Y, at (80, 0, 0)
    T = frames.placed(it[S_OUT]["copies"][0], 0, None, "y")
    assert [T[2], T[6], T[10]] == [0, 1, 0] and [T[3], T[7], T[11]] == [80, 0, 0]
    assert any(n.startswith("Shaft line:") for n in sk["notes"])


def test_shaft_lines_generalise() -> None:
    # a single shaft with two bearings and a pulley between them (an idler roller): bearings 5 mm clear of its faces
    sk, ifs = icd.build(_parts(_plan(_s("Shaft"), {"name": "Pulley", "family": "turned", "complexity": 2, "qty": 1,
                                                   "description": "Pulley Ø80 x 30"}, _b(2))), "")
    n = _by_name(sk)
    assert sk["layout"] == "shaft_line" and icd.problems(sk, ifs) == []
    h = sk["items"][n["Pulley"]]["size"][2]
    jz = [f["data"]["z"] for f in ifs if f["kind"] == "bearing_journal"]
    assert jz == [[-h / 2 - 5 - 14, -h / 2 - 5], [h / 2 + 5, h / 2 + 5 + 14]]
    # a compound train, 3 shafts: 18/54 then 18/54 (m2): centres 72 apart; the intermediate pinion stacked 5 mm
    # after the intermediate gear (Y 15..35, centre 25) and the output gear on that plane
    sk, ifs = icd.build(_parts(_plan(_g("Input pinion", "m2 18 teeth"), _g("Intermediate gear", "m2 54 teeth"),
                                     _g("Intermediate pinion", "m2 18 teeth"), _g("Output gear", "m2 54 teeth"),
                                     _s("Input shaft"), _s("Intermediate shaft"), _s("Output shaft"), _b(6))), "")
    n, it = _by_name(sk), sk["items"]
    assert icd.problems(sk, ifs) == []
    assert [it[n[k]]["copies"][0] for k in ("Input pinion", "Intermediate gear", "Intermediate pinion", "Output gear")] \
        == [[0, 0, 0], [72, 0, 0], [72, 25, 0], [144, 25, 0]]
    meshes = [(f["a"]["name"], f["b"]["name"], f["data"]["plane_a"]) for f in ifs if f["kind"] == "gear_mesh"]
    assert meshes == [("Input pinion", "Intermediate gear", 0), ("Intermediate pinion", "Output gear", 25)]
    # the intermediate shaft's bearings clear both its gears (Y -10..35): -29..-15 and 40..54
    mid = [f["data"]["z"] for f in ifs if f["kind"] == "bearing_journal" and f["a"]["name"] == "Intermediate shaft"]
    assert mid == [[-29, -15], [40, 54]]
    # the same train with no names: the compound rule (1, 2, 1 gears on 3 shafts) gives the same layout
    sk2, _ifs2 = icd.build(_parts(_plan(_g("Gear 1", "m2 18 teeth"), _g("Gear 2", "m2 54 teeth"),
                                       _g("Gear 3", "m2 18 teeth"), _g("Gear 4", "m2 54 teeth"),
                                       _s("Shaft A"), _s("Shaft B"), _s("Shaft C"), _b(6))), "")
    assert [v["copies"][0] for v in sk2["items"].values()][:4] == [[0, 0, 0], [72, 0, 0], [72, 25, 0], [144, 25, 0]]
    # an idler train 20 / 30 / 40 (m2): centres 50 and 70, all on one plane; the idler turned half a pitch (6 deg)
    sk, ifs = icd.build(_parts(_plan(_g("Pinion", "m2 20 teeth"), _g("Idler gear", "m2 30 teeth"),
                                     _g("Output gear", "m2 40 teeth"), _s("Input shaft"), _s("Idler shaft"),
                                     _s("Output shaft"), _b(6))), "")
    n, it = _by_name(sk), sk["items"]
    assert icd.problems(sk, ifs) == []
    assert [it[n[k]]["copies"][0][0] for k in ("Pinion", "Idler gear", "Output gear")] == [0, 50, 120]
    assert it[n["Idler gear"]]["phase"] == 6.0 and sum(f["kind"] == "gear_mesh" for f in ifs) == 2
    # a gear pair Archie planned on a base plate keeps the block layout: vertical shafts in bearing seats in the plate
    # (not a gearbox casing), now each with its own gear, meshing at a = 80 on the plate's top face
    sk, ifs = icd.build(_parts(_plan({"name": "Base plate", "family": "machined", "complexity": 2, "qty": 1,
                                      "description": "Plate 300 x 150 x 15"}, _g("Pinion", "m2 20 teeth"),
                                     _g("Gear", "m2 60 teeth"), _s("Input shaft"), _s("Output shaft"), _b(4))), "")
    n, it = _by_name(sk), sk["items"]
    assert sk["layout"] == "block" and icd.problems(sk, ifs) == []
    assert not any(v.get("ax") for v in it.values())
    assert (it[n["Pinion"]]["parent"], it[n["Gear"]]["parent"]) == (n["Input shaft"], n["Output shaft"])
    mesh = next(f["data"] for f in ifs if f["kind"] == "gear_mesh")
    assert abs(mesh["axis_b"][0] - mesh["axis_a"][0]) == 80 and sum(f["kind"] == "bearing_seat" for f in ifs) == 2


def test_degenerate_layouts_are_icd_problems() -> None:
    # gears and bearings, nothing to mount them on and no shaft: the old silent "row" is now blocking problems
    sk, ifs = icd.build(_parts(_plan(_g("Pinion", "m2 20 teeth"), _g("Gear", "m2 60 teeth"), _b(4))), "")
    iss = icd.issues(sk, ifs)
    assert sk["layout"] == "row" and ifs == []
    assert [(x["code"], x["severity"]) for x in iss] == [("row_layout", "error"), ("no_interface", "error"),
                                                         ("no_interface", "error"), ("bearing_unplaced", "warning")]
    assert iss[1]["items"] == ["i_s1_p1"] and iss[3]["items"] == ["i_s1_p3"]
    assert len(icd.problems(sk, ifs)) == 3 and icd.warnings(sk, ifs)[0].startswith("Deep groove ball bearing 6204: 4 of 4")
    # three bearings for two shafts: the output shaft runs in one (a shaft line needs two per shaft)
    sk, ifs = icd.build(_parts(_plan(_g("Pinion", "m2 20 teeth"), _g("Gear", "m2 60 teeth"), _s("Input shaft"),
                                     _s("Output shaft"), _b(3))), "")
    assert [(x["code"], x["items"]) for x in icd.issues(sk, ifs)] == [("shaft_support", ["i_s1_p4"])]
    # m1 20 / 20: a = 20, but the 6204s are Ø47: they overlap across the shafts (47 - 20 = 27 mm); the gears' Ø20
    # bores also leave no rim inside a Ø20 pitch circle
    sk, ifs = icd.build(_parts(_plan(_g("Pinion", "m1 20 teeth"), _g("Gear", "m1 20 teeth"), _s("Input shaft"),
                                     _s("Output shaft"), _b(4))), "")
    codes = [x["code"] for x in icd.issues(sk, ifs)]
    assert "line_clash" in codes and "rim" in codes
    clash = next(x for x in icd.issues(sk, ifs) if x["code"] == "line_clash" and "bearing 6204 #1 and" in x["text"])
    assert "overlap by 27.0 mm" in clash["text"]
    # a frozen shaft too short for its bearings
    sk, ifs = icd.build(_parts(PAIR), "", {"items": {S_IN: {"length": 50.0}}, "interfaces": {}})
    assert [(x["code"], x["interfaces"]) for x in icd.issues(sk, ifs)] == [("journal_off_shaft", ["IF-01"]),
                                                                           ("journal_off_shaft", ["IF-02"])]


def test_shaft_line_placeholders_conform_and_the_shafts_turn(tmp_path: Path) -> None:
    from build123d import Pos

    from aicad import toolbox
    from aicad.assembly import placeholder
    from aicad.office import motion_joints, program_assembly

    sk, ifs = icd.build(_parts(PAIR), "")
    doc = {"version": 1, "interfaces": ifs}
    for i in (S_IN, S_OUT):  # (gear placeholders are pitch cylinders: no teeth to measure)
        info, refs = _prepare(tmp_path, placeholder.shape(icd.placeholder_spec(sk, ifs, i)), i)
        res = conformance.measure(sk, doc, i, info, refs)
        assert res["ok"] and res["frame"]["identity"], (i, [r for x in res["interfaces"] for r in x["rows"] if not r["ok"]])
    # the real Toolbox gears bored to the ICD conform in their own (horizontal) part frames
    for i, z in ((PIN, 20), (GEAR, 60)):
        g, _e = toolbox.build("spur_gear", M=2, Z=z, B=20, BORE=20)
        res = conformance.measure(sk, doc, i, *_prepare(tmp_path, Pos(0, 0, -10) * g, f"real_{i}"))
        assert res["ok"], (i, [r for x in res["interfaces"] for r in x["rows"] if not r["ok"]])
    # motion: each shaft turns on its bearings with its gear; the mesh couples them -20 / 60
    prog = {"skeleton": sk, "icd": doc}
    insts = [{"id": f"x{n}", "T": program_assembly.place(sk, i, 0), "office": {"item": i, "copy": 0}}
             for n, i in enumerate((S_IN, S_OUT, PIN, GEAR))]
    pj = motion_joints.program_joints(prog, {"instances": insts})
    rev = [j for j in pj["joints"] if j["type"] == "revolute"]
    assert [(j["name"], j["p"], j["dir"], j["insts"]) for j in rev] == [
        ("Input shaft rotation", [0, -29, 0], [0, 1, 0], ["x0", "x2"]),
        ("Output shaft rotation", [80, -29, 0], [0, 1, 0], ["x1", "x3"])]
    gear = next(j for j in pj["joints"] if j["type"] == "gear")
    assert gear["ratio"] == round(-20 / 60, 9) and pj["driver"] == "j1" and pj["notes"] == []
    # interface label of the new kind and an edit of its bearing (on the shaft item)
    assert icd.KIND_LABEL["bearing_journal"] == "bearing on journal"
    ov = icd.apply_values({}, ifs[0], icd.clean_values(ifs[0], {"designation": 6004}))
    assert ov["items"][S_IN]["designation"] == 6004
    _sk2, ifs2 = icd.build(_parts(PAIR), "", ov)
    d = next(f for f in ifs2 if f["kind"] == "bearing_journal")["data"]
    assert (d["designation"], d["D"], d["B"]) == ("6004", 42, 12)
    assert math.isclose(d["z"][1] - d["z"][0], 12)


def test_spur_pair_program_assembles_on_its_shafts(office: Any) -> None:  # noqa: F811
    """The founder's test case end to end with simulated agents: the ICD gate passes on real interfaces, every
    part is built to its excerpt and swapped in, Fitz seats the four bearings on the shaft journals and mates them,
    and the final assembly has no clash."""
    from test_office_icd import _asm
    from test_office_orchestrator import _program

    from aicad.assembly import store as astore

    c = office
    v = _program(c, "shaftline@x.com", PAIR, brief="Simple spur gear pair 1:3 with shafts and bearings, no housing.")
    pid = v["id"]
    assert v["assembly"]["status"] == "ready" and v["assembly"]["clashes"] == [], v["assembly"].get("summary")
    c.post(f"/api/office/programs/{pid}/run")
    v = _wait(c, pid, lambda v: v["orchestrator"]["state"] in ("complete", "blocked", "stopped"), timeout=1500)
    assert v["status"] == "complete", [(t["title"], t["column"], (t.get("run") or {}).get("status")) for t in v["tickets"]]
    st = v["assembly"]
    assert st["clashes"] == [] and not any(p["kind"] == "placeholder" for p in st["parts"].values()), st.get("summary")
    final = astore.load(_asm(c)[0], st["final"])
    bearings = [i for i in final["instances"] if (i.get("office") or {}).get("seated")]
    assert len(bearings) == 4, [i.get("name") for i in final["instances"]]
    at = sorted((round(b["T"][3], 3), round(b["T"][7], 3), round(b["T"][11], 3)) for b in bearings)
    assert at == [(0, -29, 0), (0, 15, 0), (80, -29, 0), (80, 15, 0)]
    for b in bearings:  # each bearing's own Z along +Y
        assert [round(b["T"][2], 6), round(b["T"][6], 6), round(b["T"][10], 6)] == [0, 1, 0]
    tags = {(m["icd"], m["type"]) for m in final["mates"] if m.get("icd")}
    assert {("IF-01", "concentric"), ("IF-03", "concentric"), ("IF-05", "concentric")} <= tags, tags
