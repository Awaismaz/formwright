"""Design Office Phase 5 (CD-014, CD-015, DRW-014 + the Phase 4 follow-ups): program deliverables (Ortho's drawings,
Smithy's DFM summary, the program BOM, the program release), estimate calibration and the timeline, the new interface
kinds (bearing seats, DIN 6885 keys, ISO 8734 dowels, quarter-turn part frames), frame-tolerant measurement and the
assembly lock shared with Assembly Studio. No live AI: part agents are the deterministic fake client; Archie and the
real review calls fail the test if reached (fixture from test_office_orchestrator)."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import math
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest
from test_office_icd import _prepare
from test_office_orchestrator import _events, _tk, _wait, office  # noqa: F401  (fixture)

from aicad.office import calibration, conformance, deliverables, frames, icd, planner, timeline


def _parts(plan: dict[str, Any]) -> list[dict[str, Any]]:
    p = planner.normalise_plan(plan, "standard")
    assert p is not None
    rot = {q["name"]: q["rotate"] for s in plan["subassemblies"] for q in s["parts"] if q.get("rotate")}
    return [{"id": f"i_{s['id']}_{q['id']}", "name": q["name"], "family": q["family"], "qty": q["qty"],
             "description": q["description"], "complexity": q["complexity"], "sub": f"i_{s['id']}",
             **({"rotate": rot[q["name"]]} if q["name"] in rot else {})}
            for s in p["subassemblies"] for q in s["parts"]]


def _plan(*subs: tuple[str, list[tuple[str, str, int, int, str]]]) -> dict[str, Any]:
    return {"source": "standard", "summary": "", "assumptions": [], "subassemblies": [
        {"name": n, "description": "", "parts": [{"name": a, "family": f, "complexity": c, "qty": q, "description": d}
                                                 for a, f, c, q, d in parts]} for n, parts in subs]}


# ============================================================================ CD-015: calibration (hand computed)
def test_calibration_ema_with_clamps_hand_computed(tmp_path: Path) -> None:
    # rate 4.0 min/unit; a complexity-2 ticket took 2 min -> observed 1.0, clamped to 4 x 0.5 = 2.0,
    # after = 4 + 0.3 x (2 - 4) = 3.4
    assert calibration.update(4.0, 2.0, 2) == {"before": 4.0, "observed": 1.0, "clamped": 2.0, "after": 3.4}
    # 30 min on complexity 3 -> observed 10, clamped to 4 x 2 = 8, after = 4 + 0.3 x 4 = 5.2
    assert calibration.update(4.0, 30.0, 3) == {"before": 4.0, "observed": 10.0, "clamped": 8.0, "after": 5.2}
    # inside the step: 3.5 min on complexity 1 -> 4 + 0.3 x (3.5 - 4) = 3.85
    assert calibration.update(4.0, 3.5, 1)["after"] == 3.85
    # absolute floor: 0.05 x 0.5 = 0.025 -> 0.05 - 0.0075 = 0.0425 -> bounded to 0.05
    assert calibration.update(0.05, 0.0, 1)["after"] == 0.05
    # ceiling: 50 -> 100 clamp -> 65 -> bounded to 60
    assert calibration.update(50.0, 500.0, 1)["after"] == 60.0
    assert calibration.error_pct(8.0, 6.0) == -25.0 and calibration.error_pct(0, 3) is None
    # rolling mean absolute error over the last 5: |50|, |-20|, |10| -> 50, 35, 26.7
    acc = [{"error_pct": 50.0}, {"error_pct": -20.0}, {"error_pct": 10.0}]
    assert calibration.trend(acc) == [{"n": 1, "mape": 50.0}, {"n": 2, "mape": 35.0}, {"n": 3, "mape": 26.7}]
    # persisted per organisation and per profile: simulated runs never move the live constants
    t = {"key": "TR-1", "title": "Plate"}
    e = calibration.record(tmp_path, "simulated", family="machined", complexity=2, estimate_min=8.0, actual_min=2.0,
                           ticket=t, program={"id": "p", "name": "Rig"})
    assert (e["before"], e["after"], e["error_pct"]) == (4.0, 3.4, -75.0)
    e = calibration.record(tmp_path, "simulated", family="machined", complexity=2, estimate_min=6.8, actual_min=2.0,
                           ticket=t, program={"id": "p", "name": "Rig"})
    assert (e["before"], e["after"]) == (3.4, 2.89)  # 3.4 x 0.5 = 1.7 clamp; 3.4 + 0.3 x (1.7 - 3.4) = 2.89
    assert calibration.rates(tmp_path, "simulated")["machined"] == 2.89
    assert calibration.rates(tmp_path, "live")["machined"] == 4.0
    v = calibration.view(tmp_path, "simulated")
    mach = next(f for f in v["families"] if f["family"] == "machined")
    assert (mach["rate"], mach["default"], mach["n"], mach["specialist"]) == (2.89, 4.0, 2, "mill")
    assert [h["after"] for h in v["history"]] == [2.89, 3.4] and len(v["trend"]) == 2
    assert v["rule"] == {"alpha": 0.3, "step": [0.5, 2.0], "bounds": [0.05, 60.0], "window": 5}


# ============================================================================ CD-015: timeline (hand computed)
def _t(tid: str, est: float, deps: list[str] | None = None, kind: str = "part", **kw: Any) -> dict[str, Any]:
    return {"id": tid, "key": f"K-{tid[1:]}", "title": tid, "kind": kind, "estimate_min": est, "progress": 0,
            "column": kw.pop("column", "ready"), "depends_on": deps or [], "item_id": tid, "specialist": "mill", **kw}


def test_timeline_planned_schedule_and_critical_path() -> None:
    # A (10), B (20), C (5); D (6) waits for A and B; E (4) for C; F (3) for D and E. Two agents.
    # chains: A 19, B 29, C 12, D 9, E 7, F 3.  t=0: B and A start (highest chains); A ends at 10 -> C 10..15;
    # C ends -> E 15..19; B ends at 20 -> D 20..26 -> F 26..29.
    tickets = [_t("t1", 10), _t("t2", 20), _t("t3", 5), _t("t4", 6, ["t1", "t2"], "integration"),
               _t("t5", 4, ["t3"], "integration"), _t("t6", 3, ["t4", "t5"], "integration")]
    plan = timeline.planned(tickets, 2)
    assert {k: (v["start"], v["end"]) for k, v in plan.items()} == {
        "t2": (0, 20), "t1": (0, 10), "t3": (10, 15), "t5": (15, 19), "t4": (20, 26), "t6": (26, 29)}
    assert timeline.critical_path(tickets) == ["t2", "t4", "t6"]
    assert timeline.planned(tickets, 1)["t6"]["end"] == 48  # one agent: everything in a row
    # actual: Mill designed t1 from 100 s to 160 s and Gage reviewed it until 190 s, after a capacity wait 50..100 s;
    # the program first ran at 40 s
    tickets[0].update(column="approved", segments=[
        {"stage": "capacity", "kind": "capacity", "agent": None, "label": None, "start": 50.0, "end": 100.0},
        {"stage": "design", "kind": "work", "agent": "mill", "label": "Mill", "start": 100.0, "end": 160.0},
        {"stage": "review", "kind": "work", "agent": "gage", "label": "Gage", "start": 160.0, "end": 190.0}])
    tickets[1].update(wait_since={"kind": "blocked", "t": 220.0}, segments=[
        {"stage": "design", "kind": "work", "agent": "mill", "label": "Mill #2", "start": 100.0, "end": 220.0}])
    doc = {"tickets": tickets, "concurrency": 2, "orchestrator": {"state": "running", "first_run_at": 40.0}}
    ev = [{"type": "cr.raised", "t": "1970-01-01T00:04:00Z", "text": "CR-1 raised", "data": {"cr": "CR-1"},
           "ticket_id": "t2"}]
    tl = timeline.build(doc, ev, now=280.0)
    assert tl["origin"] == 40.0 and tl["now"] == 4.0 and tl["critical"] == ["t2", "t4", "t6"]
    r1 = next(r for r in tl["rows"] if r["id"] == "t1")
    assert r1["actual_min"] == 1.5 and r1["error_pct"] == -85.0 and r1["rounds"] == {"design": 1, "review": 1}
    assert [(s["stage"], s["start"], s["end"]) for s in r1["segments"]] == [
        ("capacity", 0.1667, 1.0), ("design", 1.0, 2.0), ("review", 2.0, 2.5)]
    r2 = next(r for r in tl["rows"] if r["id"] == "t2")
    assert r2["critical"] and r2["segments"][-1] == {"stage": "blocked", "kind": "blocked", "agent": None,
                                                    "label": None, "start": 3.0, "end": 4.0, "open": True,
                                                    "what": "Needs the engineer"}
    assert [ln["label"] for ln in tl["lanes"]] == ["Mill", "Mill #2", "Gage"]
    assert tl["markers"] == [{"t": 3.3333, "type": "cr.raised", "text": "CR-1 raised", "cr": "CR-1", "ticket": "t2"}]
    assert tl["planned_end"] == 29 and tl["totals"] == {"estimate_min": 10.0, "actual_min": 1.5, "done": 1}


# ============================================================================ CD-014: BOM and DFM (fixture rows)
def test_program_bom_rows_and_dfm_summary() -> None:
    tickets = [
        {"id": "t1", "key": "TR-1", "kind": "part", "item_id": "a", "title": "Base plate", "qty": 1, "project_id": "p1"},
        {"id": "t2", "key": "TR-2", "kind": "part", "item_id": "b", "title": "Spacer", "qty": 2, "project_id": "p2"},
        {"id": "t3", "key": "TR-3", "kind": "standard", "item_id": "c", "title": "Cover bolt", "qty": 4,
         "reuse": {"source": "toolbox", "code": "hex_bolt", "title": "Hex bolt ISO 4017 M6×25", "standard": "ISO 4017"}},
        {"id": "t4", "key": "TR-4", "kind": "standard", "item_id": "d", "title": "Locating dowel", "qty": 6,
         "reuse": {"source": "toolbox", "code": "dowel", "title": "Dowel pin ISO 8734 Ø6×16", "standard": "ISO 8734"}},
        {"id": "t5", "key": "TR-5", "kind": "integration", "item_id": "root", "title": "Final", "qty": 1}]
    rows = [
        {"part": "Base plate", "kind": "project", "qty": 1, "part_key": "k1", "instances": ["i1"], "material": "Al",
         "mass_each_g": 100.0, "designation": None, "standard": None},
        {"part": "Spacer", "kind": "project", "qty": 1, "part_key": "k2", "instances": ["i2"], "material": "Steel",
         "mass_each_g": 20.0, "designation": None, "standard": None},
        {"part": "Hex bolt ISO 4017 M6×30", "kind": "toolbox", "code": "hex_bolt", "qty": 4, "part_key": "k3",
         "instances": ["b1", "b2", "b3", "b4"], "designation": "Hex bolt ISO 4017 M6×30", "standard": "ISO 4017",
         "material": "Steel 8.8", "mass_each_g": 8.0},
        {"part": "Washer ISO 7089 6", "kind": "toolbox", "code": "washer", "qty": 8, "part_key": "k4",
         "instances": [f"w{i}" for i in range(8)], "designation": "Washer ISO 7089 6", "standard": "ISO 7089",
         "material": "Steel", "mass_each_g": 1.0},
        {"part": "Dowel pin ISO 8734 Ø6×16", "kind": "toolbox", "code": "dowel", "qty": 4, "part_key": "k5",
         "instances": ["d1", "d2", "d3", "d4"], "designation": "Dowel pin ISO 8734 Ø6×16", "standard": "ISO 8734",
         "material": "Steel", "mass_each_g": 3.5}]
    inst = {"i1": {"item": "a"}, "i2": {"item": "b"}, **{f"d{i}": {"item": "d", "bin": True} for i in range(1, 5)}}
    b = deliverables.bom(tickets, rows, inst, {"k1": "p1", "k2": "p2"}, {})
    got = [(r["item"], r["qty"], r["part"], r["make_buy"], r["key"]) for r in b["rows"]]
    # made parts first (plan order, the plan's quantity), then bought parts; the bolt Fitz fitted (M6x30) is the
    # plan's cover bolt; washers were added by Fitz; the parts bin holds 4 dowels but the plan says 6
    assert got == [(1, 1, "Base plate", "make", "TR-1"), (2, 2, "Spacer", "make", "TR-2"),
                   (3, 4, "Hex bolt ISO 4017 M6×30", "buy", "TR-3"), (4, 6, "Dowel pin ISO 8734 Ø6×16", "buy", "TR-4"),
                   (5, 8, "Washer ISO 7089 6", "buy", None)]
    assert b["rows"][4]["description"] == "Added by Fitz for the bolted joints"
    assert (b["make"], b["buy"], b["total_qty"]) == (2, 3, 21)
    assert b["total_mass_g"] == 100 + 2 * 20 + 4 * 8 + 6 * 3.5 + 8 * 1  # 201.0
    csv = deliverables.bom_csv(b)
    assert csv.splitlines()[0].startswith("Item,Qty,Part,Make/Buy,Designation") and "TR-3" in csv
    # before the program assembly: from the tickets
    b0 = deliverables.bom(tickets, None, project_info={"p1": {"name": "Base plate", "material": "Al", "mass_g": 50.0}})
    assert [(r["part"], r["qty"], r["make_buy"]) for r in b0["rows"]] == [
        ("Base plate", 1, "make"), ("Spacer", 2, "make"), ("Hex bolt ISO 4017 M6×25", 4, "buy"),
        ("Dowel pin ISO 8734 Ø6×16", 6, "buy")]
    # Smithy's summary: relative cost index against the cheapest part
    a1 = {"process": {"ranking": [{"process": "cnc_milling", "name": "CNC milling", "feasible": True, "fit": "good",
                                   "score": 80}]}, "cost": {"primary": "cnc_milling", "currency": "EUR",
                                                            "processes": {"cnc_milling": {"unit_cost": 30.0}}},
          "summary": {"critical": 1, "warning": 2, "info": 0}, "inputs": {"quantity": 10},
          "findings": [{"rule": "DFM-CNC-02", "severity": "critical", "title": "Sharp internal corner",
                        "measured": "R0", "limit": "R1", "fix": "Add a radius"}]}
    a2 = {"process": {"ranking": [{"process": "cnc_turning", "feasible": True}]},
          "cost": {"primary": "cnc_turning", "processes": {"cnc_turning": {"unit_cost": 12.0}}, "currency": "EUR"},
          "summary": {"critical": 0, "warning": 0, "info": 3}, "findings": []}
    s = deliverables.dfm_summary([deliverables.dfm_part(tickets[0], a1), deliverables.dfm_part(tickets[1], a2),
                                  deliverables.dfm_part(tickets[2], None, "No verified build")])
    p1, p2, p3 = s["parts"]
    assert (p1["process_name"], p1["relative_cost"], p1["critical"]) == ("CNC milling", 2.5, 1)
    assert (p2["process_name"], p2["relative_cost"]) == ("CNC turning", 1.0) and not p3["ok"]
    assert s["program_cost"] == 30 + 2 * 12 and s["attention"] == ["TR-1"] and s["analysed"] == 2
    assert p1["cost_share_pct"] == round(100 * 30 / 54, 1)


# ============================================================================ Phase 4 follow-ups: interface kinds
GEARBOX = _plan(("Case", [("Housing", "machined", 3, 1, "Housing 120 x 80 x 40 mm.")]),
                ("Drive", [("Drive shaft", "turned", 2, 1, "Shaft Ø20 x 100 mm."),
                           ("Drive gear", "gear", 2, 1, "Spur gear module 2, 30 teeth, keyed to the shaft."),
                           ("Shaft bearing", "standard", 1, 2, "Deep-groove ball bearings 6204.")]))
DOWELED = _plan(("Base", [("Base plate", "machined", 2, 1, "Plate 200 x 100 x 10 mm."),
                          ("Bracket", "machined", 2, 1, "Bracket 60 x 40 x 8 mm."),
                          ("Cover bolt", "standard", 1, 4, "Hex bolts M6 x 25."),
                          ("Locating dowel", "standard", 1, 2, "Dowel pins locating the bracket.")]),
                ("Drive", [("Spacer", "turned", 1, 1, "Spacer Ø20 x 15 mm.")]))
HOUSING, SHAFT, GEAR, BEARING = "i_s1_p1", "i_s2_p2", "i_s2_p3", "i_s2_p4"
BASE, BRACKET, DOWEL = "i_s1_p1", "i_s1_p2", "i_s1_p4"


def test_bearing_seats_keys_dowels_and_rotation_layout() -> None:
    sk, ifs = icd.build(_parts(GEARBOX), "")
    assert icd.problems(sk, ifs) == []
    kinds = [(f["id"], f["kind"]) for f in ifs]
    assert kinds == [("IF-01", "bearing_seat"), ("IF-02", "shaft_bore"), ("IF-03", "key"), ("IF-04", "face")]
    # 6204 written in the plan and its bore (20) fits the Ø20 shaft: d 20, D 47, B 14; two bearings -> two seats.
    # The housing (40 deep, top on datum A) carries them at Z -14..0 and -40..-26; the shaft sits at the centre of
    # the 80 mm row (margin 10 + gear Ø60 + margin 10, centred) -> axis (0, 0)
    seat = ifs[0]["data"]
    assert (seat["designation"], seat["d"], seat["D"], seat["B"], seat["housing_fit"], seat["shaft_fit"]) == \
        ("6204", 20, 47, 14, "H7", "k6")
    assert seat["seats"] == [{"face": "top", "z": [-14, 0]}, {"face": "bottom", "z": [-40, -26]}]
    assert seat["axis"] == [0, 0] and seat["clearance_d"] == 22 and seat["bearing_item"] == BEARING
    hf = [f for f in icd.item_features(sk, ifs, HOUSING) if f["if"] == "IF-01"]
    assert [(f["type"], f.get("d"), f.get("z0"), f.get("z1"), f.get("z")) for f in hf] == [
        ("seat", 47, 6, 20, None), ("face", None, None, None, 6), ("seat", 47, -20, -6, None),
        ("face", None, None, None, -6), ("seat", 22, -6, 6, None), ("face", None, None, None, -20)]
    # DIN 6885-1 for Ø20 (17 < d <= 22): key 6 x 6, shaft groove 3.5, hub groove 2.8; gear face 20 -> key 18 long,
    # centred on the hub (Z 0..20 above the housing) -> Z 1..19
    key = ifs[2]["data"]
    assert (key["b"], key["h"], key["t1"], key["t2"], key["length"], key["z"]) == (6, 6, 3.5, 2.8, 18, [1, 19])
    kf = {f["on"]: f for f in icd.item_features(sk, ifs, SHAFT) + icd.item_features(sk, ifs, GEAR)
          if f["type"] == "keyway"}
    assert kf["shaft"]["depth"] == 3.5 and kf["hub"]["depth"] == 2.8 and kf["hub"]["dir"] == [1, 0]
    # Fitz seats the two bearings at the seat bottoms; Hex takes exactly that bearing
    assert icd.seated(ifs, BEARING) == {"code": "bearing", "params": {"SERIES": 6204}, "at": [[0, 0, -14], [0, 0, -40]],
                                        "interface": "IF-01", "title": "Ball bearing 6204", "standard": "ISO 15",
                                        "what": "bearing seats"}
    ex = icd.excerpt(sk, {"version": 1, "interfaces": ifs}, HOUSING)
    assert "2 × Deep-groove ball bearing 6204 (bore 20, OD 47, width 14)" in ex and "bearing seat Ø47 H7 (top)" in ex
    # ISO 8734 dowels on the bolted bracket: clear of the M6 bolts (holes at -16 +/- 16.8, +/- 6.8) -> on the centre
    # line at -16 +/- 8.4; pins Ø6 (the bolt size), length min(3 x 6, 8 + 10 - 2) = 16 -> 16, holes H7 both sides
    sk2, ifs2 = icd.build(_parts(DOWELED), "")
    assert icd.problems(sk2, ifs2) == []
    dw = next(f for f in ifs2 if f["kind"] == "dowel")
    assert (dw["id"], dw["data"]["positions"], dw["data"]["d"], dw["data"]["length"], dw["data"]["joint"]) == \
        ("IF-02", [[-24.4, 0], [-7.6, 0]], 6, 16, "IF-01")
    bh = [f for f in icd.item_features(sk2, ifs2, BRACKET) if f["if"] == "IF-02"]
    assert [(f["c"], f["fit"]) for f in bh] == [([-8.4, 0], "H7"), ([8.4, 0], "H7")]
    assert icd.seated(ifs2, DOWEL)["at"] == [[-24.4, 0, -8], [-7.6, 0, -8]]
    # a quarter turn of the bracket's part frame: it stands 40 along the row now (row 10 + 40 + 12 + 20 + 10 = 92,
    # centred: bracket at -36 + 20 = -16, spacer at -36 + 40 + 12 + 10 = 26); its own features are unchanged
    rot = json.loads(json.dumps(DOWELED))
    rot["subassemblies"][0]["parts"][1]["rotate"] = 90
    sk3, ifs3 = icd.build(_parts(rot), "")
    assert sk3["items"][BRACKET]["rot"] == 90 and sk3["items"][BRACKET]["copies"] == [[-16, 0, 4]]
    assert sk3["items"]["i_s2_p5"]["copies"][0][0] == 26
    j = ifs3[0]["data"]
    assert j["positions"] == [[-22.8, -16.8], [-9.2, -16.8], [-22.8, 16.8], [-9.2, 16.8]]

    def holes(s: Any, f: Any) -> list[Any]:
        return sorted(tuple(x["c"]) for x in icd.item_features(s, f, BRACKET) if x["type"] == "hole")
    assert holes(sk3, ifs3[:1]) == holes(sk2, ifs2[:1])  # same part, turned: same local features
    assert "turned 90° about +Z" in icd.excerpt(sk3, {"version": 1, "interfaces": ifs3}, BRACKET)


def test_new_kinds_placeholders_conform_and_defects_fail(tmp_path: Path) -> None:
    from aicad.assembly import placeholder

    sk, ifs = icd.build(_parts(GEARBOX), "")
    sk2, ifs2 = icd.build(_parts(DOWELED), "")
    d1, d2 = {"version": 1, "interfaces": ifs}, {"version": 1, "interfaces": ifs2}
    # every placeholder carries its interface features exactly (gear teeth aside: placeholders are pitch cylinders)
    for n, (s_, d_, item) in enumerate(((sk, d1, HOUSING), (sk, d1, SHAFT), (sk2, d2, BRACKET), (sk2, d2, BASE))):
        info, refs = _prepare(tmp_path, placeholder.shape(icd.placeholder_spec(s_, d_["interfaces"], item)), f"ph{n}")
        res = conformance.measure(s_, d_, item, info, refs)
        assert res["ok"] and res["frame"]["identity"], (item, [r for x in res["interfaces"] for r in x["rows"]
                                                               if not r["ok"]])
    # defects, measured against specified: a seat 0.1 mm over (H7 at Ø47: 47.000..47.025), a keyway 5 wide, a
    # dowel hole at Ø6.2
    spec = icd.placeholder_spec(sk, ifs, HOUSING)
    spec["seats"][0]["d"] = 47.1
    info, refs = _prepare(tmp_path, placeholder.shape(spec), "seat")
    rows = [r for x in conformance.measure(sk, d1, HOUSING, info, refs)["interfaces"] for r in x["rows"] if not r["ok"]]
    assert [(r["feature"], r["spec"], r["measured"][:6]) for r in rows] == [
        ("bearing seat Ø47 H7 (top)", "Ø47 H7 (47.000…47.025) on the axis at (0.00, 0.00)", "Ø47.10")]
    spec = icd.placeholder_spec(sk, ifs, SHAFT)
    spec["keyways"][0]["b"] = 5.0
    info, refs = _prepare(tmp_path, placeholder.shape(spec), "key")
    res = conformance.measure(sk, d1, SHAFT, info, refs, frame_tolerant=False)
    kr = next(r for x in res["interfaces"] for r in x["rows"] if r["feature"].startswith("keyway"))
    assert not kr["ok"] and kr["measured"] == "5.000 wide, 3.500 deep" and kr["spec"].startswith("6 wide (±0.05), 3.5 deep")
    # a gear's envelope holds its teeth (tip circle m (z + 2) = 64), its placeholder is the pitch cylinder (60): a
    # real Toolbox gear with the keyway conforms (found in the walkthrough: the envelope was the pitch circle)
    assert sk["items"][GEAR]["size"] == [64, 64, 20] and icd.placeholder_spec(sk, ifs, GEAR)["size"] == [60, 60, 20]
    from build123d import Pos

    from aicad import toolbox

    gspec = icd.placeholder_spec(sk, ifs, GEAR)
    g, _e = toolbox.build("spur_gear", M=2, Z=30, B=20, BORE=20)
    res = conformance.measure(sk, d1, GEAR, *_prepare(tmp_path, placeholder.cut(Pos(0, 0, -10) * g, gspec), "realgear"))
    assert res["ok"] and res["envelope"]["ok"], [r for x in res["interfaces"] for r in x["rows"] if not r["ok"]]
    good = next(r for x in conformance.measure(sk, d1, GEAR, *_prepare(tmp_path, placeholder.shape(
        icd.placeholder_spec(sk, ifs, GEAR)), "hub"))["interfaces"] for r in x["rows"] if r["feature"].startswith("keyway"))
    assert good["ok"] and good["measured"] == "6.000 wide, 2.800 deep"
    spec = icd.placeholder_spec(sk2, ifs2, BRACKET)
    spec["holes"] = [h if abs(h["d"] - 6) > 1e-6 or h["c"][0] > 0 else {**h, "d": 6.2} for h in spec["holes"]]
    info, refs = _prepare(tmp_path, placeholder.shape(spec), "dowel")
    rows = [r for x in conformance.measure(sk2, d2, BRACKET, info, refs)["interfaces"] for r in x["rows"] if not r["ok"]]
    assert [(r["feature"], r["measured"]) for r in rows] == [("dowel hole 1 Ø6 H7", "Ø6.200 at (-8.40, 0.00)")]


def test_frame_tolerant_measurement(tmp_path: Path) -> None:
    from build123d import Pos, Rot

    from aicad.assembly import placeholder

    sk, ifs = icd.build(_parts(GEARBOX), "")
    d1 = {"version": 1, "interfaces": ifs}
    shaft = placeholder.shape(icd.placeholder_spec(sk, ifs, SHAFT))
    # the right shaft, modelled turned 90° about Z (keyway on +Y) with its origin at its bottom end
    L = sk["items"][SHAFT]["size"][2]
    moved = Pos(0, 0, L / 2) * Rot(0, 0, 90) * shaft
    info, refs = _prepare(tmp_path, moved, "moved")
    res = conformance.measure(sk, d1, SHAFT, info, refs)
    assert res["ok"] and not res["frame"]["identity"]
    assert res["frame"]["label"] == f"rotated 270° about Z, moved by (0, 0, {-L / 2:g}) mm"
    assert res["frame"]["R"] == frames.rot_z(270) and res["frame"]["t"] == [0, 0, -L / 2]
    assert not conformance.measure(sk, d1, SHAFT, info, refs, frame_tolerant=False)["ok"]
    # placed through that frame, the part lands exactly where the ICD frame would put it
    T = frames.placed(sk["items"][SHAFT]["copies"][0], 0, res["frame"])
    R = [T[0:3], T[4:7], T[8:11]]
    p = frames.apply(R, [0, 6, L / 2])  # the keyway side of the modelled part ...
    assert [round(a + b, 6) for a, b in zip(p, [T[3], T[7], T[11]], strict=True)] == [
        round(sk["items"][SHAFT]["copies"][0][0] + 6, 6), 0, round(sk["items"][SHAFT]["copies"][0][2], 6)]
    # a wrong part stays wrong in any frame: the keyway too narrow
    spec = icd.placeholder_spec(sk, ifs, SHAFT)
    spec["keyways"][0]["b"] = 5.0
    info, refs = _prepare(tmp_path, Pos(3, 4, 0) * Rot(0, 0, 180) * placeholder.shape(spec), "bad")
    res = conformance.measure(sk, d1, SHAFT, info, refs)
    assert not res["ok"] and any("keyway" in f for f in conformance.findings(res))


def test_meshing_gears_are_tooth_phased() -> None:
    """Found in the walkthrough: two real gears at the exact centre distance collided (both have a tooth on +X).
    Pinion 18 teeth at the left, gear 54 teeth 72 mm to the right: the pinion's tooth faces the gear (theta = 0, u = 0),
    so the gear shows a space at 180 deg: phase = (180 - 0.5 x 360/54) mod (360/54) = 3.3333 deg (half a tooth)."""
    from build123d import Pos, Rot

    from aicad import toolbox

    plan = planner.standard_plan("Gear reducer", "A spur gear reducer, 3:1, 1450 rpm input.")
    parts = [{"id": f"i_{s['id']}_{p['id']}", "name": p["name"], "family": p["family"], "qty": p["qty"],
              "description": p["description"], "complexity": p["complexity"], "sub": f"i_{s['id']}"}
             for s in plan["subassemblies"] for p in s["parts"]]
    sk, ifs = icd.build(parts, "3:1")
    mesh = next(f for f in ifs if f["kind"] == "gear_mesh")
    gear = mesh["b"]["item"]
    assert abs(mesh["data"]["phase_b"] - 10 / 3) < 1e-5 and abs(sk["items"][gear]["phase"] - 10 / 3) < 1e-5
    assert "phase" not in sk["items"][mesh["a"]["item"]]
    # the output gear's keyway turns with its frame, so in the assembly it still lines up with the shaft's (+X)
    key = next(f for f in ifs if f["kind"] == "key")
    hub = next(x for x in icd.side_features(sk, key, "a") if x["type"] == "keyway")
    assert [round(v, 4) for v in hub["dir"]] == [round(math.cos(math.radians(10 / 3)), 2), round(-math.sin(math.radians(10 / 3)), 2)]
    pin, _e = toolbox.build("spur_gear", M=2, Z=18, B=20, BORE=10)
    big, _e = toolbox.build("spur_gear", M=2, Z=54, B=20, BORE=20)
    clash = (pin & (Pos(72, 0, 0) * big)).volume
    phased = (pin & (Pos(72, 0, 0) * Rot(0, 0, 10 / 3) * big)).volume
    assert clash > 50 and phased < 1e-3, (clash, phased)


# ============================================================================ the assembly lock (shared)
def test_assembly_lock_is_shared_with_assembly_studio() -> None:
    from aicad.assembly import locks
    from aicad.platform.routers import mod_assembly

    assert mod_assembly._lock("a1") is locks.lock("a1")
    order: list[str] = []

    async def main() -> None:
        async def hand_edit() -> None:
            async with mod_assembly._lock("a1"):
                order.append("hand edit")

        async with locks.hold("a1", locks.OFFICE):
            assert locks.holder("a1") == "Design Office"
            task = asyncio.create_task(hand_edit())
            await asyncio.sleep(0.05)
            assert not task.done()  # the hand edit waits for the office
            order.append("office edit")
        await task
        assert locks.holder("a1") is None
    asyncio.run(main())
    assert order == ["office edit", "hand edit"]


# ============================================================================ end to end: deliverables + release
RIG = {"source": "standard", "summary": "Test rig", "assumptions": [], "subassemblies": [
    {"name": "Base", "description": "", "parts": [
        {"name": "Base plate", "family": "machined", "complexity": 2, "qty": 1, "description": "Plate 120 x 80 x 10 mm."},
        {"name": "Cover bolt", "family": "standard", "complexity": 1, "qty": 4, "description": "Hex bolts M6 x 25."}]},
    {"name": "Drive", "description": "", "parts": [
        {"name": "Spacer", "family": "turned", "complexity": 1, "qty": 1, "description": "Spacer Ø20 x 15 mm."}]}]}


def test_deliverables_release_timeline_and_calibration(office: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from test_office_orchestrator import _program

    from aicad.assembly import locks

    held: list[str] = []
    real_hold = locks.hold

    def spy(aid: str, who: str) -> Any:
        held.append(aid)
        return real_hold(aid, who)
    monkeypatch.setattr(locks, "hold", spy)
    c = office
    v = _program(c, "deliver@x.com", RIG, deliverables=True)
    pid = v["id"]
    subs = set((v.get("assembly") or {}).get("subs", {}).values())
    assert subs and subs <= set(held)  # every program assembly document was built under the shared lock
    assert c.post(f"/api/office/programs/{pid}/release").status_code == 409  # nothing to release yet
    c.post(f"/api/office/programs/{pid}/run")
    v = _wait(c, pid, lambda v: v["orchestrator"]["state"] == "complete", timeout=300)
    assert v["status"] == "complete"
    deliv = [t for t in v["tickets"] if t["kind"] == "deliverable"]
    assert [(t["specialist"], t["column"], t["deliverable"]) for t in deliv] == [
        ("ortho", "approved", "drawings"), ("smithy", "approved", "dfm")]
    assert all(t["agent"] in ("ortho", "smithy") and t["progress"] == 100 for t in deliv)
    gate = next(g for g in v["gates"] if g["code"] == "release")
    assert gate["status"] == "pending"
    types = [e["type"] for e in _events(c, pid)]
    for want in ("deliverables.opened", "deliverable.done", "estimate.calibrated", "program.done"):
        assert want in types, want
    # Ortho: a sheet per part made, the ICD numbers tagged spec where they map, CHK-12 passes; the assembly drawing
    d = c.get(f"/api/office/programs/{pid}/deliverables").json()
    sheets = d["drawings"]["sheets"]
    assert [s["title"] for s in sheets] == ["Base plate", "Spacer"] and all(s["ok"] and s["check_passed"] for s in sheets)
    assert all(s["icd_offered"] >= 1 for s in sheets)
    asm = d["drawings"]["assembly"]
    assert asm["ok"] and asm["rows"] == len(d["bom"]["rows"]) and len(asm["balloons"]) >= 3
    for n in ("assembly.svg", "assembly.pdf", "assembly.dxf"):
        r = c.get(asm["urls"][n])
        assert r.status_code == 200 and len(r.content) > 500, n
    svg = c.get(asm["urls"]["assembly.svg"]).text
    assert "NOT APPROVED FOR MANUFACTURE" in svg and "MAKE/BUY" in svg and "Base plate" in svg
    # the program BOM: made parts with mass, the Toolbox bolts with their designation, washers / nuts Fitz added
    rows = d["bom"]["rows"]
    assert [(r["part"], r["qty"], r["make_buy"]) for r in rows[:2]] == [("Base plate", 1, "make"), ("Spacer", 1, "make")]
    assert all(r["mass_each_g"] and r["material"] for r in rows[:2])
    bolts = [r for r in rows if r["make_buy"] == "buy" and r["key"]]
    assert bolts and "ISO 4017" in (bolts[0]["standard"] or "") and bolts[0]["qty"] == 4
    csv = c.get(f"/api/office/programs/{pid}/bom.csv")
    assert csv.status_code == 200 and csv.text.startswith("Item,Qty,Part,Make/Buy")
    # Smithy: every part analysed, a process each, relative cost against the cheapest
    dfm = d["dfm"]
    assert dfm["analysed"] == 2 and [p["title"] for p in dfm["parts"]] == ["Base plate", "Spacer"]
    assert all(p["process_name"] for p in dfm["parts"]) and min(p["relative_cost"] for p in dfm["parts"]) == 1.0
    assert dfm["label"] == "Relative estimate, not a quote"
    # the timeline: planned for every ticket, actual segments by agent lane, the critical path ends at the deliverables
    tl = c.get(f"/api/office/programs/{pid}/timeline").json()
    assert all(r["planned"] for r in tl["rows"]) and tl["critical"]
    plate = next(r for r in tl["rows"] if r["title"] == "Base plate")
    assert [s["stage"] for s in plate["segments"] if s["kind"] == "work"][:3] == ["hex", "design", "review"]
    assert plate["actual_min"] > 0 and plate["error_pct"] is not None
    lanes = {ln["agent"] for ln in tl["lanes"]}
    assert {"hex", "mill", "chuck", "gage", "fitz", "ortho", "smithy"} <= lanes
    # calibration learned from every finished ticket (simulated profile: never the live constants)
    cal = c.get("/api/office/calibration").json()
    assert cal["profile"] == "simulated"
    mach = next(f for f in cal["families"] if f["family"] == "machined")
    assert mach["n"] >= 1 and mach["rate"] < mach["default"]  # simulated agents are far faster than the estimate
    t_plate = _tk(v, "Base plate")
    assert t_plate["calibrated"]["learned"] and t_plate["actual_min"] > 0
    # a new plan takes the calibrated rate
    c2 = c.post("/api/office/programs", json={"name": "Second", "brief": "A second small rig with a base plate.",
                                              "planner": "standard"}).json()
    assert c2["calibration"]["rates"]["machined"] == mach["rate"]
    # the release: every part issued and tagged at its revision, one pack with everything
    r = c.post(f"/api/office/programs/{pid}/release", json={"note": "First article"})
    assert r.status_code == 200, r.text
    rel = r.json()["release"]
    assert rel["rev"] == "A" and [p["rev"] for p in rel["parts"]] == ["A", "A"]
    assert all(p["tag"] == "TR Rev A" for p in rel["parts"])
    for p in rel["parts"]:
        tags = c.get(f"/api/projects/{p['project_id']}/tags").json()["items"]
        assert [(t["name"], t["revision"]) for t in tags] == [("TR Rev A", p["model_rev"])]
        assert c.get(f"/api/projects/{p['project_id']}/release").json()["releases"][0]["rev"] == "A"
    v = r.json()["program"]
    assert next(g for g in v["gates"] if g["code"] == "release")["status"] == "approved"
    assert v["released"]["rev"] == "A"
    z = c.get(f"/api/office/programs/{pid}/releases/A/pack.zip")
    assert z.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(z.content))
    names = [n.split("/", 1)[1] for n in zf.namelist()]
    for want in ("parts/Base_plate_revA.step", "parts/Spacer_revA.step", "assembly/Test_rig_revA.step",
                 "drawings/Base_plate_revA.pdf", "drawings/Base_plate_revA.dxf", "drawings/Spacer_revA.pdf",
                 "drawings/Test_rig_assembly_revA.pdf", "drawings/Test_rig_assembly_revA.dxf", "bom.csv",
                 "dfm/dfm_summary.csv", "dfm/dfm_summary.json", "icd/icd.json", "Test_rig.fwprog", "README.txt",
                 "manifest.json"):
        assert want in names, (want, names)
    man = json.loads(zf.read(next(n for n in zf.namelist() if n.endswith("manifest.json"))))
    for n in zf.namelist():
        k = n.split("/", 1)[1]
        if k != "manifest.json":
            assert hashlib.sha256(zf.read(n)).hexdigest() == man["files"][k]["sha256"], k
    assert zf.read(next(n for n in zf.namelist() if n.endswith(".fwprog")))[:2] == b"PK"
    readme = zf.read(next(n for n in zf.namelist() if n.endswith("README.txt"))).decode()
    assert "REV A" in readme and "not a quote" in readme and "tag \"TR Rev A\"" in readme
    assert "program.released" in [e["type"] for e in _events(c, pid)]
    # the assembly STEP holds the real parts (no placeholder left)
    assert b"placeholder" not in zf.read(next(n for n in zf.namelist() if n.endswith("Test_rig_revA.step"))).lower()
    assert time.time() > 0
