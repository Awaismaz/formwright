"""WORKLIST 50: the hybrid master model (recorded master scripts, no live tokens).

Hand values are in the recorded scripts' headers (``src/aicad/eval/golden_cases/*.master.py``) and repeated here.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from aicad.master import decide, measure, run, skeleton
from aicad.office import icd, planner, service

CASES = Path(__file__).resolve().parents[1] / "src" / "aicad" / "eval" / "golden_cases"


def _plan(case: str) -> dict[str, Any]:
    raw = json.loads((CASES / f"{case}.plan.json").read_text(encoding="utf-8"))
    p = planner.normalise_plan(raw, "archie")
    assert p is not None
    return p


def _parts(plan: dict[str, Any], brief: str = "") -> list[dict[str, Any]]:
    return icd.parts_from(decide.pseudo_doc(plan, brief))


@pytest.fixture(scope="module")
def measured() -> dict[str, dict[str, Any]]:
    return {c: measure.measure_script(CASES / f"{c}.master.py") for c in ("h_enclosure", "i_motor_adapter",
                                                                             "j_controller")}


def _built(measured: dict[str, Any], case: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    plan = _plan(case)
    parts = _parts(plan)
    skel, ifs = skeleton.build(measured[case], parts)
    ids = {p["name"]: p["id"] for p in parts}
    return skel, ifs, ids


# ----------------------------------------------------------------------------- measuring
def test_enclosure_measured_by_hand(measured: dict[str, Any]) -> None:
    m = measured["h_enclosure"]
    assert [b["label"] for b in m["bodies"]] == ["Enclosure base", "Enclosure lid"]
    base, lid = m["bodies"]
    assert base["min"] == [-60.0, -40.0, 0.0] and base["max"] == [60.0, 40.0, 40.0]
    assert lid["min"] == [-60.0, -40.0, 40.0] and lid["max"] == [60.0, 40.0, 43.0]
    # bosses Ø8 touching both 2.5 walls: ±(60 - 2.5 - 4), ±(40 - 2.5 - 4); M3 tap drill Ø2.5 x 8 from the rim
    taps = sorted((h["at"], h["d"], h["lo"], h["hi"], h["through"]) for h in base["holes"])
    assert taps == sorted(([x, y], 2.5, 32.0, 40.0, False) for x in (-53.5, 53.5) for y in (-33.5, 33.5))
    assert all(h["d"] == 3.4 and h["through"] for h in lid["holes"])
    (c,) = m["contacts"]
    assert (c["kind"], c["axis"], c["t"], c["sign_a"]) == ("planar", "z", 40.0, 1)
    assert sorted(b["at"] for b in c["bolts"]) == sorted([x, y] for x in (-53.5, 53.5) for y in (-33.5, 33.5))
    assert m["findings"] == []
    assert "pocket" not in base  # bosses in the cavity: not a clean box, so the envelope stays whole


def test_bracket_pocket_and_window_passage(measured: dict[str, Any]) -> None:
    m = measured["i_motor_adapter"]
    br = m["bodies"][0]
    # the L bracket's inside corner: above the 6 mm foot, in front of the 14 mm upright (Y -30 .. 16, Z 6 .. 76)
    assert br["pocket"]["min"] == [-40.0, -30.0, 6.0] and br["pocket"]["max"] == [40.0, 16.0, 76.0]
    assert set(br["pocket"]["open"]) >= {"-y", "+z", "-x", "+x"}
    joint = next(c for c in m["contacts"] if c["kind"] == "planar" and c["axis"] == "y" and c["t"] == 16.0)
    assert len(joint["bolts"]) == 4
    assert joint["ways"] == [{"at": [0.0, 36.0], "d_a": 52.0, "d_b": 23.0}]  # window over the pilot bore
    assert m["findings"] == []  # the M3 heads open into the window: no lone hole


# ----------------------------------------------------------------------------- the skeleton and ICD
def test_enclosure_skeleton_and_icd(measured: dict[str, Any]) -> None:
    skel, ifs, ids = _built(measured, "h_enclosure")
    base, lid = ids["Enclosure base"], ids["Enclosure lid"]
    assert skel["solver"] == "master" and skel["base"] == base
    assert skel["items"][base]["copies"] == [[0.0, 0.0, -20.0]]   # datum A on the top of the base envelope
    assert skel["items"][lid]["copies"] == [[0.0, 0.0, 1.5]]
    assert skel["items"][lid]["parent"] == base
    (f,) = ifs
    d = f["data"]
    assert f["kind"] == "hole_pattern" and f["a"]["item"] == base and f["b"]["item"] == lid
    assert (d["fastener"], d["d"], d["plane_z"], d["normal"], d["through"]) == ("M3", 3.4, 0.0, [0.0, 0.0, 1.0], False)
    assert d["tapped"] == {"d": 2.5, "depth": 8.0, "thread": "M3"}
    assert d["fastener_item"] == ids["Lid screw M3x10"] and "counterbore" not in d
    assert sorted(d["positions"]) == sorted([x, y] for x in (-53.5, 53.5) for y in (-33.5, 33.5))
    assert icd.problems(skel, ifs) == [] and icd.warnings(skel, ifs) == []


def test_motor_adapter_skeleton(measured: dict[str, Any]) -> None:
    skel, ifs, ids = _built(measured, "i_motor_adapter")
    br, pl, mo = ids["Mounting bracket"], ids["Motor adapter plate"], ids["Stepper motor NEMA 17"]
    # datum A at Z 76 (top of the upright): plate Z 6 .. 66 -> centre -40; Y 11 .. 16 -> 13.5; motor Y -37 .. 11
    assert skel["items"][pl]["copies"] == [[0.0, 13.5, -40.0]]
    assert skel["items"][mo]["copies"] == [[0.0, -13.0, -40.0]]
    assert skel["items"][br]["cavity"]["open_through"] is True
    by = {(f["a"]["item"], f["b"]["item"], f["kind"]): f for f in ifs}
    m4 = by[(br, pl, "hole_pattern")]["data"]
    assert (m4["fastener"], m4["ax"], m4["plane_z"], m4["normal"]) == ("M4", "y", 16.0, [0.0, -1.0, 0.0])
    assert m4["tapped"]["depth"] == 12.0 and m4["fastener_item"] == ids["Plate screw M4x16"]
    assert sorted(m4["positions"]) == sorted([x, z] for x in (-30.0, 30.0) for z in (-60.0, -20.0))
    assert m4["passages"] == [{"at": [0.0, -40.0], "d_a": 52.0, "d_b": 23.0}]
    m3 = by[(mo, pl, "hole_pattern")]["data"]  # the motor carries the tapped holes: side a, its face looks +Y
    assert (m3["fastener"], m3["plane_z"], m3["normal"], m3["tapped"]["depth"]) == ("M3", 11.0, [0.0, 1.0, 0.0], 8.0)
    seat = by[(br, pl, "face")]["data"]  # the plate stands on the foot
    assert (seat["plane_z"], seat["normal"]) == (-70.0, [0.0, 0.0, 1.0])
    assert icd.problems(skel, ifs) == []


def test_controller_screws_from_below(measured: dict[str, Any]) -> None:
    skel, ifs, ids = _built(measured, "j_controller")
    lo, up = ids["Lower shell"], ids["Upper shell"]
    assert skel["base"] == lo
    (f,) = ifs
    assert f["a"]["item"] == up and f["b"]["item"] == lo  # tapped bosses in the upper shell: side a
    assert f["data"]["normal"] == [0.0, 0.0, -1.0] and f["data"]["plane_z"] == 0.0
    assert sorted(f["data"]["positions"]) == sorted([x, y] for x in (-40.0, 40.0) for y in (-30.0, 30.0))
    assert skel["items"][up]["copies"] == [[0.0, 0.0, 7.0]] and skel["items"][lo]["copies"] == [[0.0, 0.0, -9.0]]
    # Ø8 x 9 counterbores from below: the screws clamp 9 mm, so M3 x 16 fits (9 + 0.5 washer + 6 .. 9 + 0.5 + 7)
    assert f["data"]["counterbore"] == {"d": 8.0, "depth": 9.0, "length": 18.0}
    seats = [x for x in icd.side_features(skel, f, "b") if x["type"] == "seat"]
    assert len(seats) == 4 and all((x["d"], x["z0"], x["z1"]) == (8.0, -9.0, 0.0) for x in seats)  # part frame
    assert icd.problems(skel, ifs) == [] and icd.warnings(skel, ifs) == []


def test_live_master_screws_that_cannot_fit_are_said() -> None:
    """The live master turn's controller (docs/reports/master-model): Ø6 x 9 counterbores and 7 mm tapped bosses
    leave 15.5 mm for an M3 screw (9 + 0.5 + 6 at least, 9 + 0.5 + 6 usable at most): no ISO length; said at the gate."""
    live = Path(__file__).resolve().parents[1] / "docs" / "reports" / "master-model" / "live-j_controller.master.py"
    m = measure.measure_script(live)
    skel, ifs = skeleton.build(m, _parts(_plan("j_controller")))
    w = icd.warnings(skel, ifs)
    assert len(w) == 1 and "no standard M3 length fits a 9 mm clamp into 7 mm of tapped thread" in w[0]
    assert icd.problems(skel, ifs) == []


def test_measured_graph(measured: dict[str, Any]) -> None:
    plan = _plan("i_motor_adapter")
    parts = _parts(plan)
    skel, ifs = skeleton.build(measured["i_motor_adapter"], parts)
    g = skeleton.graph(skel, ifs, parts, "Motor", "")
    kinds = sorted((x.kind, len(x.via)) for x in g.connections)
    assert kinds == [("bolted_joint", 1), ("bolted_joint", 1), ("mounted_on", 0)]
    plate = next(c for c in g.components if c.name == "Motor adapter plate")
    assert plate.v("L") == 80.0 and plate.params["L"].note == "measured from the master model"


# ----------------------------------------------------------------------------- honesty: never silent
BAD = """
from build123d import *
from aicad.master import kit as mk
base = mk.box(100, 60, 10, (0, 0, 5))
lid = mk.box(100, 60, 4, (0, 0, 11))           # 1 mm into the base: an overlap
loose = mk.box(20, 20, 20, (200, 0, 10))      # touches nothing
stray = mk.box(10, 10, 10, (0, 0, -5))         # no planned part has this name
lid = mk.drill(lid, (30, 0, 13), 3.4, 4, "z", -1)
result = mk.master({"Base": base, "Lid": lid, "Bracket": loose, "Stray block": stray})
EXPECTED = {"solids": mk.count()}
"""


def test_findings_reach_the_gate(tmp_path: Path) -> None:
    f = tmp_path / "model.py"
    f.write_text(BAD, encoding="utf-8")
    m = measure.measure_script(f)
    codes = {x["code"] for x in m["findings"]}
    assert {"overlap", "touches_nothing"} <= codes
    plan = {"source": "archie", "summary": "", "assumptions": [], "subassemblies": [{"name": "A", "description": "",
            "parts": [{"name": n, "family": "machined", "complexity": 2, "qty": 1, "description": ""}
                      for n in ("Base", "Lid", "Bracket", "Cover")]}]}
    p2 = planner.normalise_plan(plan, "archie")
    assert p2 is not None
    skel, ifs = skeleton.build(m, _parts(p2))
    probs = icd.problems(skel, ifs)
    text = " ".join(probs)
    assert "overlap" in text and "touches nothing" in text
    assert "matches no part of the plan" in text and "Cover is planned but has no body" in text
    assert all(p.startswith("Layout conflict") or "Master model" in p or "no interface" in p for p in probs)


def test_copies_must_match(tmp_path: Path) -> None:
    f = tmp_path / "model.py"
    f.write_text("from aicad.master import kit as mk\n"
                 "a = mk.box(100, 100, 10, (0, 0, 5))\n"
                 "l1 = mk.box(10, 10, 50, (-30, 0, 35))\nl2 = mk.box(12, 10, 50, (30, 0, 35))\n"
                 "result = mk.master({'Top': a, 'Leg': [l1, l2]})\n", encoding="utf-8")
    m = measure.measure_script(f)
    assert [b["label"] for b in m["bodies"]] == ["Top", "Leg #1", "Leg #2"]
    plan = planner.normalise_plan({"source": "archie", "summary": "", "assumptions": [], "subassemblies": [
        {"name": "A", "description": "", "parts": [
            {"name": "Top", "family": "machined", "complexity": 2, "qty": 1, "description": ""},
            {"name": "Leg", "family": "machined", "complexity": 2, "qty": 2, "description": ""}]}]}, "archie")
    assert plan is not None
    skel, ifs = skeleton.build(m, _parts(plan))
    assert any("copies of Leg differ in size" in p for p in icd.problems(skel, ifs))
    assert len([f for f in ifs if f["kind"] == "face"]) == 2  # each leg seated on the top: one face per copy


# ----------------------------------------------------------------------------- the decision
def test_decision_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(decide.ENV, raising=False)
    d = decide.decide(_plan("h_enclosure"), "A small electronics enclosure with a lid.")
    assert d["path"] == "master" and d["reasons"][0]["code"] == "product"
    assert d["words"] == "Laid out from a master model (free-form product)"
    d = decide.decide(_plan("i_motor_adapter"), "A NEMA 17 stepper on a custom adapter plate.")
    assert d["path"] == "master" and d["reasons"][0]["code"] == "adapter"
    d = decide.decide(_plan("b_gear_pair"), "A 1:3 spur gear pair on two shafts in four 6204 bearings.")
    assert d["path"] == "fast" and d["trial"]["problems"] == []
    d = decide.decide(_plan("d_bracket"), "An aluminium angle bracket bolted to a base plate.")
    assert d["path"] == "fast"
    monkeypatch.setenv(decide.ENV, "0")
    assert decide.decide(_plan("h_enclosure"), "An enclosure.")["path"] == "fast"
    monkeypatch.setenv(decide.ENV, "force")
    d = decide.decide(_plan("d_bracket"), "An aluminium angle bracket bolted to a base plate.")
    assert d["path"] == "master" and d["reasons"][0]["code"] == "forced"


def test_decision_on_a_fast_layout_that_fails_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The old golden case (e): bearings in two side plates, which the standard layout can't connect."""
    monkeypatch.delenv(decide.ENV, raising=False)
    d = decide.decide(_plan("e_roller"), "A conveyor roller on a shaft in two bearings in side plates.")
    assert d["path"] == "master" and "gate" in {r["code"] for r in d["reasons"]}
    assert d["trial"]["problems"]


# ----------------------------------------------------------------------------- the office hooks
def _doc(case: str, brief: str) -> dict[str, Any]:
    plan = _plan(case)
    return {"id": "p1", "name": case, "brief": brief, "plan": plan, "status": "plan_review", "events": [],
            "event_seq": 0, "gates": [{"code": "brief", "status": "pending"}, {"code": "icd", "status": "pending"}]}


def test_route_attach_and_layout(measured: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from aicad.office import interfaces, store

    monkeypatch.delenv(decide.ENV, raising=False)
    monkeypatch.setattr(service, "emit", lambda *a, **k: None)
    doc = _doc("h_enclosure", "A small electronics enclosure with a lid held by four M3 screws.")
    assert run.route(tmp_path, doc) is True
    assert doc["status"] == "planning" and doc["planning"]["stage"] == "master"
    assert doc["plan"]["layout_path"]["state"] == "modelling"
    run.attach(doc, {"ok": True, "measure": measured["h_enclosure"], "seconds": {"total": 1.0}, "via": "replay"}, 0)
    mm = doc["plan"]["master"]
    assert mm["ok"] and mm["summary"] == {"bodies": 2, "interfaces": 1, "bolted": 1, "faces": 0, "fits": 0,
                                         "bearings": 0, "meshes": 0}
    assert mm["graph"]["view"]["connections"][0]["text"].startswith("Enclosure lid bolted to Enclosure base")
    # approval: items from the plan, then the interfaces gate lays it out from the master (measured, not solved)
    items, tickets = service._build(doc["plan"], doc["name"], "P", doc["brief"])
    doc.update(items=items, tickets=tickets)
    skel, ifs = interfaces._rebuild(doc, {})
    assert skel["solver"] == "master" and len(ifs) == 1
    # a frozen ICD (approval) rebuilds to the same layout
    ov = icd.freeze(skel, ifs, {})
    s2, i2 = interfaces._rebuild(doc, ov)
    assert s2["items"] == skel["items"] and [f["data"] for f in i2] == [f["data"] for f in ifs]
    assert store.now()


def test_failed_master_falls_back_said(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(decide.ENV, raising=False)
    monkeypatch.setattr(service, "emit", lambda *a, **k: None)
    doc = _doc("h_enclosure", "An enclosure.")
    run.route(tmp_path, doc)
    run.attach(doc, {"ok": False, "error": "the master model did not build (boom)"}, 0)
    lp = doc["plan"]["layout_path"]
    assert lp["path"] == "fast" and "could not be made" in lp["words"] and "boom" in lp["words"]
    from aicad.master.skeleton import build_for_doc

    assert build_for_doc(doc, {}) is None


def test_run_replays_a_recorded_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The master step end to end (turn replaced by the recorded script, measured in its own process)."""
    src = (CASES / "j_controller.master.py").read_text(encoding="utf-8")

    async def turn(*_a: Any, **_k: Any) -> run.Turn:
        return run.Turn(src, via="replay")

    monkeypatch.setattr(run, "agent_turn", turn)
    res = asyncio.run(run.run(tmp_path / "master", "Controller", "A handheld controller housing.",
                              _plan("j_controller")))
    assert res["ok"], res.get("error")
    assert [b["label"] for b in res["measure"]["bodies"]] == ["Lower shell", "Upper shell"]
    assert res["seconds"]["measure"] > 0 and res["cost_usd"] is None


def test_replay_folder_matches_by_designed_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(run.REPLAY_ENV, str(CASES))
    assert "Enclosure base" in (run.replay_source(_plan("h_enclosure")) or "")
    assert run.replay_source(_plan("b_gear_pair")) is None


def test_switched_off_by_default_in_tests() -> None:
    """(conftest) Tests never get a master turn unless they ask: the switch is off, and the rule says so."""
    d = decide.decide(_plan("h_enclosure"), "An electronics enclosure.")
    assert d["path"] == "fast" and d["mode"] == "off"


def test_golden_cases_load_the_master() -> None:
    from aicad.eval import golden

    cases = {c["id"]: c for c in golden.load_cases()}
    for cid in ("enclosure", "motor-adapter", "controller"):
        assert cases[cid]["expect"]["path"] == "master"
        assert "mk.master(" in cases[cid]["sim"]["master_src"]


def test_hinge_pivot_axis_becomes_the_pin() -> None:
    """Golden (g): the pin is bought out, so the master has only its bores; the arm hangs 1 mm clear of each lug."""
    m = measure.measure_script(CASES / "g_hinge_arm.master.py")
    assert m["pins"] == [{"kind": "pin", "axis": "y", "at": [-25.0, 24.0], "d": 8.0, "bodies": [0, 1],
                          "span": [-20.0, 20.0]}]
    assert m["findings"] == []  # joined by its pivot axis: not "touches nothing"
    plan = _plan("g_hinge_arm")
    parts = _parts(plan)
    ids = {p["name"]: p["id"] for p in parts}
    skel, ifs = skeleton.build(m, parts)
    (f,) = ifs
    assert f["kind"] == "dowel" and f["a"]["item"] == ids["Clevis base"] and f["b"]["item"] == ids["Hinge arm"]
    # datum A at Z 30 (the top of the lugs): the pivot at X -25, Z 24 - 30 = -6; the pin centred on Y 0, 40 long
    d = f["data"]
    assert (d["positions"], d["plane_z"], d["length"], d["d"]) == ([[-25.0, -6.0]], 0.0, 40.0, 8.0)
    assert d["pin_item"] == ids["Hinge pin"]
    # the slot between the lugs (Y ±12, Z 8 .. 30 in the master; the clevis centred at Z 15): kept open
    cav = skel["items"][ids["Clevis base"]]["cavity"]
    assert cav["min"] == [-40.0, -12.0, -7.0] and cav["max"] == [40.0, 12.0, 15.0] and cav["open_through"]
    assert icd.problems(skel, ifs) == []


def test_decision_catches_the_vanishing_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(decide.ENV, raising=False)
    d = decide.decide(_plan("g_hinge_arm"), "A hinged arm on a Ø8 pin between the lugs of a clevis base.")
    assert d["path"] == "master" and d["reasons"][0]["code"] == "unreachable"
    assert d["words"] == "Laid out from a master model (a part no connection reaches)"


def test_too_large_for_one_master(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(decide.ENV, raising=False)
    plan = _plan("h_enclosure")
    lid = plan["subassemblies"][0]["parts"][1]
    plan["subassemblies"][0]["parts"] += [{**lid, "id": f"x{k}", "name": f"Panel {k}", "qty": 8} for k in range(5)]
    d = decide.decide(plan, "An electronics enclosure with forty panels.")
    assert d["path"] == "fast" and d["too_large"] == 42 and "more than one master model takes" in d["words"]


def test_an_unplaced_accessory_keeps_the_fast_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reducer (c) plans an oil plug no interface places: an accessory, not a joint, so no master turn is spent."""
    monkeypatch.delenv(decide.ENV, raising=False)
    plan = _plan("c_reducer")
    d = decide.decide(plan, "A single-stage 3:1 spur gear reducer with a split housing and bearing caps.")
    assert d["path"] == "fast" and d["reasons"] == []
