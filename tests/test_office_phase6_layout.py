"""Design Office Phase 6, layout (CD-022): gearbox-like programs lay their shafts horizontally (along +Y) in the side
walls of the housing, bearing caps sit over their seats (coaxial) and the cover becomes the lid. Positions are hand
checked; placeholders, conformance (features along Y measured in their canonical frame), Fitz's mates and seated
bearings follow; the simulated gearbox assembles with no clash. No live AI (fake agents, PD-41 / PD-48)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from test_office_icd import _prepare
from test_office_orchestrator import _tk, _wait, office  # noqa: F401  (fixture)

from aicad.office import conformance, frames, icd, planner

BRIEF = "A spur gear reducer, 3:1, 1450 rpm input."


def _gearbox(brief: str = BRIEF) -> tuple[list[dict[str, Any]], dict[str, str]]:
    plan = planner.standard_plan("Gear reducer", brief)
    parts = [{"id": f"i_{s['id']}_{p['id']}", "name": p["name"], "family": p["family"], "qty": p["qty"],
              "description": p["description"], "complexity": p["complexity"], "sub": f"i_{s['id']}"}
             for s in plan["subassemblies"] for p in s["parts"]]
    return parts, {p["name"]: p["id"] for p in parts}


def test_gearbox_layout_hand_checked() -> None:
    parts, ids = _gearbox()
    sk, ifs = icd.build(parts, BRIEF)
    assert icd.problems(sk, ifs) == []
    it = sk["items"]
    H, CV, CAP = ids["Housing base"], ids["Housing cover"], ids["Bearing cap"]
    S_IN, S_OUT, PIN, GEAR = ids["Input shaft"], ids["Output shaft"], ids["Pinion"], ids["Output gear"]
    # 3:1 -> pinion 18, gear 54, m2: centres a = 2 (18 + 54) / 2 = 72 mm. Tip radii 20 / 56. Cavity in X:
    # [-54 - 20 - 6, 18 + 56 + 6] = [-80, 80] (centred: the pinion axis at X -54, the gear axis at X +18).
    # 6205 bearings (d 25, D 52, B 15): side walls 15 + 4 = 19 (the M6 lid screws need 2.5 x 6.6 + 1.5 = 18).
    # L = 2 (80 + 19) = 198. Stacks: one 20 wide gear each, centred on Y 0; cavity Y +-(10 + 12) = +-22, W = 82.
    # Z: above the axis 6 + 56 = 62, below 10 + 6 + 56 = 72 -> H 134, top on datum A -> axis at Z -62.
    assert it[H]["size"] == [198, 82, 134] and it[H]["copies"] == [[0, 0, -67]]
    assert it[H]["cavity"]["min"] == [-80, -22, -57] and it[H]["cavity"]["max"] == [80, 22, 67]
    assert (it[H]["cavity"]["wall"], it[H]["cavity"]["end_wall"], it[H]["cavity"]["floor"]) == (19, 19, 10)
    assert it[S_IN]["ax"] == it[S_OUT]["ax"] == it[PIN]["ax"] == it[GEAR]["ax"] == it[CAP]["ax"] == "y"
    assert it[PIN]["copies"] == [[-54, 0, -62]] and it[GEAR]["copies"] == [[18, 0, -62]]
    # shafts: flush with the -Y outer face (Y -41), out through the +Y wall and its 13 mm cap by max(15, d 25):
    # length 82 + 13 + 25 = 120, centre at Y -41 + 60 = 19
    assert it[S_IN]["size"] == [25, 25, 120] and it[S_IN]["copies"] == [[-54, 19, -62]]
    assert it[S_OUT]["copies"] == [[18, 19, -62]]
    # caps (4 off) over the 4 seats: M4 from 0.6 D; PCD = 52 + 4.5 + 2 = 58.5, OD = 58.5 + washer 9 = 67.5
    # (67.5 + 1 <= 72: they fit side by side), thickness max(8, D / 4) = 13, bore 25 + 2; on the outer faces
    assert it[CAP]["size"] == [67.5, 67.5, 13] and it[CAP]["bore"] == 27
    assert it[CAP]["copies"] == [[-54, -47.5, -62], [-54, 47.5, -62], [18, -47.5, -62], [18, 47.5, -62]]
    # the cover is the lid: the housing's footprint, on top of it
    assert it[CV]["size"][:2] == [198, 82] and it[CV]["copies"] == [[0, 0, 10]]
    kinds = [(f["id"], f["kind"]) for f in ifs]
    assert kinds == [("IF-01", "hole_pattern"), ("IF-02", "bearing_seat"), ("IF-03", "shaft_bore"),
                     ("IF-04", "bearing_seat"), ("IF-05", "shaft_bore"), ("IF-06", "key"), ("IF-07", "hole_pattern"),
                     ("IF-08", "hole_pattern"), ("IF-09", "hole_pattern"), ("IF-10", "hole_pattern"),
                     ("IF-11", "gear_mesh")]
    seat = ifs[1]["data"]
    assert (seat["ax"], seat["axis"], seat["z"], seat["flush_z"], seat["count"]) == ("y", [-54, -62], [-41, 41], -41, 2)
    assert seat["seats"] == [{"face": "+Y wall", "open": 1, "z": [26, 41]}, {"face": "-Y wall", "open": -1, "z": [-41, -26]}]
    lid = ifs[0]["data"]  # M6 (span 82 < 150): tapped Ø5 x (2.5 x 6 + 3) = 18 into the rim, at 2 d from the edges
    assert lid["tapped"] == {"d": 5.0, "depth": 18.0, "thread": "M6"} and lid["through"] is False
    assert lid["positions"] == [[-85.8, -27.8], [85.8, -27.8], [-85.8, 27.8], [85.8, 27.8]]
    cap = ifs[6]["data"]  # the -Y cap of the input shaft: holes on PCD 58.5 at 45 deg, M4 tapped 3.3 x 13
    r = 58.5 / 2 / math.sqrt(2)
    assert (cap["ax"], cap["plane_z"], cap["normal"], cap["centre"]) == ("y", -41, [0, -1, 0], [-54, -62])
    assert cap["positions"][0] == [round(-54 + r, 2), round(-62 + r, 2)]
    assert cap["tapped"] == {"d": 3.3, "depth": 13.0, "thread": "M4"}
    mesh = ifs[10]["data"]
    assert (mesh["ax"], mesh["axis_a"], mesh["axis_b"], mesh["centre_distance"]) == ("y", [-54, -62], [18, -62], 72)
    assert abs(it[GEAR]["phase"] - 10 / 3) < 1e-5  # same tooth phasing as Phase 5 (the mesh runs along +X)
    # the housing's features, in its part frame (centre at Z -67): seats along Y written in the Y canonical frame
    # (canonical c = (X, -Z_part), z = Y): axis (-54, -(-62 + 67)) = (-54, -5)
    hf = [f for f in icd.item_features(sk, ifs, H) if f["if"] == "IF-02"]
    assert [(f["type"], f.get("ax"), f.get("c"), f.get("z0"), f.get("z1"), f.get("z"), f.get("n")) for f in hf] == [
        ("seat", "y", [-54, -5], 26, 41, None, None), ("face", "y", None, None, None, 26, 1),
        ("seat", "y", [-54, -5], -41, -26, None, None), ("face", "y", None, None, None, -26, -1),
        ("seat", "y", [-54, -5], -26, 26, None, None), ("face", "y", None, None, None, -41, -1)]
    # the shaft is modelled along its own Z (from -60 to +60): journals at Y -41..-26 and 26..41 -> Z -60..-45, 7..22
    sf = icd.item_features(sk, ifs, S_IN)
    j = [(f["c"], f["z0"], f["z1"]) for f in sf if f["type"] == "boss" and f.get("z0") is not None]
    assert j == [([0, 0], -60, 22)] and not any(f.get("ax") for f in sf)
    # Fitz seats the bearings at the seat bases, their own Z along +Y
    st = icd.seated(ifs, ids["Input bearing"])
    assert st["at"] == [[-54, 26, -62], [-54, -41, -62]] and st["R"] == frames.CANON["y"]
    # assembly placement: part Z along program +Y
    T = frames.placed(it[S_IN]["copies"][0], 0, None, "y")
    assert [T[2], T[6], T[10]] == [0, 1, 0] and [T[3], T[7], T[11]] == [-54, 19, -62]
    ex = icd.excerpt(sk, {"version": 1, "interfaces": ifs}, H)
    assert "bearing seat Ø52 H7 (-Y wall) on the axis along Y at (X, Z) (-54, 5), from Y -41 to -26" in ex
    assert "4 × M4 tapped holes (tap drill Ø3.3, blind, 13 deep from the mounting face, along Y)" in ex
    assert "Gear cavity (keep clear" in ex and "Gearbox layout" in " ".join(sk["notes"])
    assert "laid along program +Y" in icd.excerpt(sk, {"version": 1, "interfaces": ifs}, S_IN)
    # drawings: tapped holes become one thread note per size (not a hole Ø to tag); found in the walkthrough, where a
    # note per interface crowded the sheet and failed CHK-12
    from aicad.office import deliverables

    spec = deliverables.icd_spec(sk, {"version": 1, "interfaces": ifs}, H)
    assert spec["notes"][:2] == ["TAPPED HOLES M4, 13 DRILLED (IF-07, IF-08, IF-09, IF-10).",
                                 "TAPPED HOLES M6, 18 DRILLED (IF-01)."]
    assert not any(k.startswith("ICD_IF01_D") for k in spec["params"])
    # an engineer can keep the Phase 5 row: layout override "row" -> vertical shafts on the housing's top face
    sk2, ifs2 = icd.build(parts, BRIEF, {"items": {H: {"layout": "row"}}, "interfaces": {}})
    assert not any(x.get("ax") for x in sk2["items"].values()) and icd.problems(sk2, ifs2) == []


def test_gearbox_caps_that_cannot_fit_stay_on_the_housing() -> None:
    # 2:1 (no ratio in the brief): 18 / 36 teeth, centres 54 mm. Even M3 caps need OD 52 + 3.4 + 2 + 7 = 64.4 > 53:
    # no coaxial caps; the shafts still run in the walls, the cover is still the lid, the caps go beside the program
    # (the casing is open at the top: nothing but the lid can bolt there) for the engineer to place
    parts, ids = _gearbox("A spur gear reducer.")
    sk, ifs = icd.build(parts, "")
    # a part with no interface would lie beside the program: the ICD gate shows it as a problem (not silent)
    assert [(x["code"], x["items"]) for x in icd.issues(sk, ifs)] == [("no_interface", [ids["Bearing cap"]])]
    assert sk["items"][ids["Input shaft"]].get("ax") == "y" and not sk["items"][ids["Bearing cap"]].get("ax")
    assert any("no cap fits over the bearing seats" in n for n in sk["notes"])
    assert any(n.startswith("Bearing cap has no interface") for n in sk["notes"])
    assert not any(ids["Bearing cap"] in (f["a"]["item"], f["b"]["item"]) for f in ifs)
    assert sk["items"][ids["Housing cover"]]["copies"] == [[0, 0, 10]]  # still the lid


def test_gearbox_placeholders_conform_and_y_defects_fail(tmp_path: Path) -> None:
    from build123d import Pos

    from aicad import toolbox
    from aicad.assembly import placeholder

    parts, ids = _gearbox()
    sk, ifs = icd.build(parts, BRIEF)
    doc = {"version": 1, "interfaces": ifs}
    for n in ("Housing base", "Housing cover", "Bearing cap", "Input shaft", "Output shaft"):
        info, refs = _prepare(tmp_path, placeholder.shape(icd.placeholder_spec(sk, ifs, ids[n])), n.replace(" ", "_"))
        res = conformance.measure(sk, doc, ids[n], info, refs)
        assert res["ok"] and res["frame"]["identity"], (n, [r for x in res["interfaces"] for r in x["rows"] if not r["ok"]])
    H = ids["Housing base"]
    # seeded defects on the Y features: the -Y seat of the input shaft 0.1 mm over, one cap hole drilled through
    spec = icd.placeholder_spec(sk, ifs, H)
    k = next(i for i, s in enumerate(spec["seats"]) if s["d"] == 52 and s["c"] == [-54, -5] and s["z0"] == -41)
    spec["seats"][k]["d"] = 52.1
    tap = next(i for i, h in enumerate(spec["holes"]) if h.get("ax") == "y" and h["z0"] == -41)
    spec["holes"][tap] = {k2: v for k2, v in spec["holes"][tap].items() if k2 not in ("z0", "z1")}
    info, refs = _prepare(tmp_path, placeholder.shape(spec), "bad_housing")
    rows = [(x["interface"], r["feature"], r["measured"]) for x in conformance.measure(sk, doc, H, info, refs)["interfaces"]
            for r in x["rows"] if not r["ok"]]
    assert ("IF-02", "bearing seat Ø52 H7 (-Y wall)", "Ø52.100, axis 0.000 mm from position") in rows
    assert any(f == "tapped hole 1 M4 × 13 deep" and "through, the ICD says blind" in m for _i, f, m in rows)
    # the real Toolbox gears, keyed and bored to the ICD, conform in their own (horizontal) part frames
    for name, z in (("Pinion", 18), ("Output gear", 54)):
        g, _e = toolbox.build("spur_gear", M=2, Z=z, B=20, BORE=25)
        body = placeholder.cut(Pos(0, 0, -10) * g, icd.placeholder_spec(sk, ifs, ids[name]))
        res = conformance.measure(sk, doc, ids[name], *_prepare(tmp_path, body, name.replace(" ", "_")))
        assert res["ok"], (name, [r for x in res["interfaces"] for r in x["rows"] if not r["ok"]])


def test_gearbox_program_assembles_with_no_clash(office: Any) -> None:  # noqa: F811
    """The simulated gearbox end to end: placeholders mated by interface name in the new layout, every real part
    swapped in, bearings seated by Fitz in the wall seats (their Z along +Y), the final assembly has no clash."""
    from test_office_orchestrator import _program

    from aicad.assembly import store as astore

    c = office
    plan = planner.standard_plan("Gear reducer", BRIEF)
    v = _program(c, "gearbox6@x.com", plan, brief=BRIEF)
    pid = v["id"]
    st = v["assembly"]
    assert st["status"] == "ready" and st["clashes"] == [], st.get("summary")
    c.post(f"/api/office/programs/{pid}/run")
    v = _wait(c, pid, lambda v: v["orchestrator"]["state"] in ("complete", "blocked", "stopped"), timeout=1500)
    assert v["status"] == "complete", [(t["title"], t["column"], (t.get("run") or {}).get("status")) for t in v["tickets"]]
    st = v["assembly"]
    assert st["clashes"] == [] and not any(p["kind"] == "placeholder" for p in st["parts"].values()), st.get("summary")
    # the clash count has one source (program_assembly.clash_status), never the integration summary
    assert st["summary"].startswith("7 real parts and 0 placeholders") and "clash" not in st["summary"]
    aroot = _aroot(c)
    final = astore.load(aroot, st["final"])
    # every instance of the final assembly, its own sub-assemblies' included, in the program frame
    insts = list(final["instances"])
    bearings = [i for i in insts if (i.get("office") or {}).get("seated") in ("IF-02", "IF-04")]
    assert len(bearings) == 4, [i.get("name") for i in insts]
    for b in bearings:  # each bearing's own Z runs along +Y, on a shaft axis (X -54 or 18, Z -62)
        T = b["T"]
        assert [round(T[2], 6), round(T[6], 6), round(T[10], 6)] == [0, 1, 0]
        assert (round(T[3], 3), round(T[11], 3)) in ((-54, -62), (18, -62))
    tags = {(m["icd"], m["type"]) for m in final["mates"] if m.get("icd")}
    assert ("IF-02", "concentric") in tags and ("IF-02", "flush") in tags, tags


def _aroot(c: Any) -> Path:
    from test_office_icd import _asm

    return _asm(c)[0]


def test_revision_table_moves_when_it_would_cover_the_views() -> None:
    """Found releasing the gearbox: the revision table stacked over the title block met the housing's top view at
    every scale. The layout may put it in the top-right or (narrower) top-left corner instead."""
    from aicad.drawing import layout

    W, H = layout.SHEETS["A3"]
    revs = [{"rev": "A", "change": "Initial release", "date": "2026-11-18", "by": "E2E"}]
    g, box = layout._info_blocks(W, H, {"title": "T"}, "1:2", True, revs, "A3")
    g2, box2 = layout._info_blocks(W, H, {"title": "T"}, "1:2", True, revs, "A3", "topleft")
    assert g.rev_box is None and box[1] < box2[1]  # stacked: the bottom-right block grows upwards
    assert box2 == [W - layout.FRAME["right"] - layout.TB_W, box2[1], W - layout.FRAME["right"], H - layout.FRAME["bottom"]]
    rb = g2.rev_box
    assert rb[0] == layout.FRAME["left"] + 2 and rb[1] == layout.FRAME["top"] + 2 and rb[2] - rb[0] == 90
