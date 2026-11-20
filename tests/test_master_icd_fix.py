"""The master-model ICD on split housings (benchmark attempts A3 and A4, 2026-11-21): the masters were sound but the
ICD drafted from them could never pass the interfaces gate, and "Fix with Archie" changed nothing.

Root causes, each pinned here on the two recorded masters (``tests/golden/master_icd``, anonymised: the plan's parts,
the master script, the old measurement):
  * two half bores at the two ends of a split housing were summed into one "full" hole, so each half carried a
    Ø47 "clearance opening" centred on its own edge (less than 1 mm of wall) and the bores read as a pivot pin;
  * the bearings are bought out (never in the master), so a shaft in its bearing bore was only a "pass", and nothing
    carried the shafts, the gears on them, the carrier and the pins: "not connected to the Housing base";
  * pitch circles touching (the meshes) and the ring gear in the split cavity were not joints at all.
And "Fix with Archie" had nothing to work with: the stored measurement was the old one. It now measures the master
again first (deterministic, no tokens).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from aicad.master import decide, measure, run, skeleton
from aicad.office import icd, interfaces, planner, service, store, supervisor

G = Path(__file__).resolve().parent / "golden" / "master_icd"


def _plan(case: str) -> dict[str, Any]:
    p = planner.normalise_plan(json.loads((G / f"{case}.plan.json").read_text(encoding="utf-8")), "archie")
    assert p is not None
    return p


def _legacy(case: str) -> dict[str, Any]:
    return json.loads((G / f"{case}.legacy.json").read_text(encoding="utf-8"))


def _parts(plan: dict[str, Any], brief: str) -> list[dict[str, Any]]:
    return icd.parts_from(decide.pseudo_doc(plan, brief))


@pytest.fixture(scope="module")
def measured() -> dict[str, dict[str, Any]]:
    return {c: measure.measure_script(G / f"{c}.master.py") for c in ("planetary", "two_shaft")}


def _layout(case: str, m: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    plan, brief = _plan(case), _legacy(case)["brief"]
    parts = _parts(plan, brief)
    skel, ifs = skeleton.build(m, parts, brief, None, plan)
    return skel, ifs, {p["name"]: p["id"] for p in parts}


def _label(m: dict[str, Any], k: int) -> str:
    return m["bodies"][k]["label"]


# ----------------------------------------------------------------------------- the old reading (reproduction)
def test_old_reading_blocked_the_gate() -> None:
    """What the founder saw (recorded with the fixture), and what the old measurement still gives today."""
    for case, d in (("planetary", 47), ("two_shaft", 52)):
        old = _legacy(case)
        assert any(f"clearance opening 1 Ø{d} through (across the joint)" in p and "less than 1 mm of wall" in p
                   for p in old["problems"])
        assert any("is not connected to the Housing base through any joint" in p for p in old["problems"])
        m = old["measure"]
        assert m["version"] == 1 and "splits" not in m
        # the half bores at both ends read as one full hole, so they made a "pivot pin" through base and cover
        assert any(pn["d"] == d and {_label(m, k) for k in pn["bodies"]} == {"Housing base", "Housing cover"}
                   for pn in m["pins"])
        skel, ifs, _ids = _layout(case, m)
        assert any("clearance opening" in p and "less than 1 mm of wall" in p for p in icd.problems(skel, ifs))


# ----------------------------------------------------------------------------- the measurement now
def test_planetary_measured_as_a_split_housing(measured: dict[str, Any]) -> None:
    m = measured["planetary"]
    assert m["version"] == measure.VERSION == 2
    lab = {b["label"]: k for k, b in enumerate(m["bodies"])}
    base, cover = m["bodies"][lab["Housing base"]], m["bodies"][lab["Housing cover"]]
    # the Ø47 bearing bores: a half turn at each end of each half (X -38 .. -10 and 62 .. 90), never a full hole
    for b in (base, cover):
        assert sorted((h["d"], h["lo"], h["hi"]) for h in b["halves"]) == [(47.0, -38.0, -10.0), (47.0, 62.0, 90.0),
                                                                          (210.0, -10.0, 62.0)]
        assert not any(c["d"] in (47.0, 210.0) for c in b["cylinders"])
        assert all(not h["full"] for h in b["holes"] if h["d"] in (47.0, 210.0))
        # the cap screws' tapped holes at the two ends are two holes, 9 deep each (one line, two stretches)
        assert sorted((h["lo"], h["hi"]) for h in b["holes"] if h["d"] == 5.0 and h["at"][0] == -24.75) == \
            [(-38.0, -29.0), (81.0, 90.0)]
    # one bore of both halves, its line in the joint plane Z 135
    assert sorted((s["d"], s["lo"], s["hi"]) for s in m["splits"]) == [(47.0, -38.0, -10.0), (47.0, 62.0, 90.0),
                                                                     (210.0, -10.0, 62.0)]
    assert all(s["joint"] == {"axis": "z", "t": 135.0} for s in m["splits"])
    assert m["pins"] == []  # no pivot: the bores are split bores and the shaft lines carry modelled shafts
    # the ring gear sits in the split cavity (Ø210 on Ø210, no gap): a fit in each half
    ring = [c for c in m["contacts"] if c["kind"] == "coaxial" and c.get("split")]
    assert sorted((_label(m, c["a"]), _label(m, c["b"]), c["d_bore"], c["gap"]) for c in ring) == [
        ("Housing base", "Ring gear", 210.0, 0.0), ("Housing cover", "Ring gear", 210.0, 0.0)]
    # the meshes: sun / planet external (60 = 30 + 30), planet / ring internal (60 = 90 - 30), at the pitch circles
    tang = [c for c in m["contacts"] if c["kind"] == "tangent"]
    assert sorted((c["internal"], c["centre_distance"]) for c in tang) == [(False, 60.0)] * 3 + [(True, 60.0)] * 3
    # the input shaft in the split Ø47 bore: a pass of each half (the 6204 is bought out)
    assert sorted((_label(m, c["a"]), c["d_bore"], c["d_pin"], tuple(c["span"])) for c in m["passes"]
                  if _label(m, c["b"]) == "Input shaft" and c["d_bore"] == 47.0) == [
        ("Housing base", 47.0, 20.0, (-38.0, -10.0)), ("Housing cover", 47.0, 20.0, (-38.0, -10.0))]
    assert not [f for f in m["findings"] if f["code"] == "unclassified"]


# ----------------------------------------------------------------------------- the ICD now
def test_planetary_icd_is_clean(measured: dict[str, Any]) -> None:
    skel, ifs, ids = _layout("planetary", measured["planetary"])
    assert icd.problems(skel, ifs) == []
    base, cover = ids["Housing base"], ids["Housing cover"]
    # every designed part reaches the base through its joints (the parents chain ends at the base)
    for i, it in skel["items"].items():
        seen, cur = set(), i
        while skel["items"][cur]["parent"] is not None and cur not in seen:
            seen.add(cur)
            cur = skel["items"][cur]["parent"]
        assert cur == base, it["name"]
    assert skel["items"][ids["Input shaft"]]["parent"] == base
    assert skel["items"][ids["Planet gear"]]["parent"] == ids["Planet pin"]
    seats = [f for f in ifs if f["kind"] == "bearing_seat"]
    # 6204 x 2 side by side from the outer end of each split bore (14 wide, the 28 mm bore full), base half places
    # the bearings, the cover half carries its half seat
    inp = [f for f in seats if f["b"]["item"] == ids["Input shaft"]]
    assert [(f["a"]["item"], f["data"]["designation"], f["data"]["count"], bool(f["data"]["bearing_item"]))
            for f in inp] == [(base, "6204", 2, True), (cover, "6204", 2, False)]
    assert inp[0]["data"]["split"] and inp[0]["data"]["no_shoulder"]
    # datum A on the top of the base (Z 135), X from the base centre (26): the seats at X -38 .. -24 .. -10
    assert [s["z"] for s in inp[0]["data"]["seats"]] == [[-64.0, -50.0], [-50.0, -36.0]]
    planet = [f for f in seats if f["a"]["item"] == ids["Planet gear"]]
    assert sorted((f["a"]["copy"], f["data"]["designation"], f["data"]["count"]) for f in planet) == [
        (0, "6004", 1), (1, "6004", 1), (2, "6004", 1)]
    # every planned bearing is placed (no "parts bin" warning)
    for name, qty in (("Input shaft bearing", 2), ("Output shaft bearing", 2), ("Planet bearing", 3)):
        assert len(icd.seated(ifs, ids[name])["at"]) == qty
    assert not [x for x in icd.issues(skel, ifs) if x["code"] == "bearing_unplaced"]
    # the meshes from the plan's module and teeth; the ring is the internal member
    mesh = [f for f in ifs if f["kind"] == "gear_mesh"]
    assert len(mesh) == 6 and all(f["data"]["module"] == 2.0 for f in mesh)
    internal = [f for f in mesh if f["data"].get("internal")]
    assert {(f["a"]["item"], f["b"]["item"], f["data"]["teeth_b"]) for f in internal} == {
        (ids["Planet gear"], ids["Ring gear"], 90)}
    # the ring in the split cavity: a bore fit in each half, its bore marked split (centred on the joint by design)
    fits = [f for f in ifs if f["kind"] == "shaft_bore" and f["b"]["item"] == ids["Ring gear"]]
    assert sorted(f["a"]["item"] for f in fits) == sorted([base, cover]) and all(f["data"]["split"] for f in fits)
    feats = icd.item_features(skel, ifs, base)
    on_edge = [x for x in feats if x["type"] in ("hole", "seat") and x.get("split")]
    assert {x["d"] for x in on_edge} >= {47.0, 210.0}
    assert not [x for x in feats if x["type"] in ("hole", "seat") and x["d"] in (47.0, 210.0) and not x.get("split")]


def test_two_shaft_icd_is_clean(measured: dict[str, Any]) -> None:
    skel, ifs, ids = _layout("two_shaft", measured["two_shaft"])
    assert icd.problems(skel, ifs) == []
    # the plan names no designation: the bores and journals say it (25 x 52 and 35 x 72: 6205, 6207, ISO 15)
    seats = {(f["b"]["item"], f["data"]["designation"]) for f in ifs if f["kind"] == "bearing_seat"
             and f["data"]["bearing_item"]}
    assert seats == {(ids["Input shaft"], "6205"), (ids["Output shaft"], "6207")}
    for name in ("Input bearing", "Output bearing"):
        assert len(icd.seated(ifs, ids[name])["at"]) == 2  # one per side wall
    # each 15 wide bearing at the outer end of its bore in the 32 mm wall, as far out as the journal goes (the input
    # shaft ends at Y 70, 2 short of the wall face: Y 55 .. 70); the rest of the bore as modelled
    out = next(f for f in ifs if f["kind"] == "bearing_seat" and f["b"]["item"] == ids["Input shaft"]
               and f["data"]["bearing_item"] and f["data"]["seats"][0]["open"] > 0)
    assert out["data"]["seats"][0]["z"] == [55.0, 70.0]
    assert out["data"]["passes"] == [{"z": [40.0, 55.0], "d": 52.0, "what": "bore beyond the bearing seat (as modelled)"}]
    assert skel["items"][ids["Pinion"]]["parent"] == ids["Input shaft"]
    assert skel["items"][ids["Input shaft"]]["parent"] == ids["Housing base"]
    # the pinion and gear touch on their pitch circles, but the plan gives no module and teeth: said, not guessed
    assert any("Pinion and Output gear touch on their pitch circles" in n for n in skel["notes"])


def test_unborne_shaft_says_what_to_change(measured: dict[str, Any]) -> None:
    """A shaft in a bore no planned bearing fits stays unconnected, and the gate says what the master shows and what
    to change (founder: "Fix with Archie must really fix", or say exactly what the engineer should change)."""
    plan = _plan("two_shaft")
    for s in plan["subassemblies"]:
        s["parts"] = [p for p in s["parts"] if p["name"] != "Input bearing"]
    brief = _legacy("two_shaft")["brief"]
    parts = _parts(plan, brief)
    skel, ifs = skeleton.build(measured["two_shaft"], parts, brief, None, plan)
    probs = icd.problems(skel, ifs)
    text = next(p for p in probs if "Input shaft is not connected" in p)
    assert "runs on Ø25 in a Ø52 bore of Housing base / Housing cover" in text
    assert "a 6205 (25 x 52) would fit it" in text and "What to change: plan that bearing" in text
    doc = {"brief": brief, "plan": plan, "skeleton": skel, "icd": {"interfaces": ifs, "problems": probs}}
    open_ = supervisor.gate_plan(doc)["open"]
    assert any(o.startswith("Master model: Input shaft is not connected") and "no safe number change" not in o
               for o in open_)


def test_internal_mesh_reads_planet_inside_ring() -> None:
    """Analytic: a Ø60 pitch circle inside a Ø180 one, 60 apart (= (180 - 60) / 2), is an internal mesh, the planet
    the inner member; 59.85 apart is not (outside MESH_TOL)."""
    planet = {"cylinders": [{"axis": "x", "d": 60.0, "concave": False, "line": [0.0, 60.0], "lo": 0.0, "hi": 20.0}]}
    ring = {"cylinders": [{"axis": "x", "d": 180.0, "concave": True, "line": [0.0, 0.0], "lo": 0.0, "hi": 20.0}]}
    (t,) = measure._tangent(ring, planet)
    assert (t["internal"], t["inner"], t["centre_distance"], t["d_a"], t["d_b"]) == (True, "b", 60.0, 180.0, 60.0)
    planet["cylinders"][0]["line"] = [0.0, 59.85]
    assert measure._tangent(ring, planet) == []


def test_axial_clusters() -> None:
    # two half bores at the two ends of a line: two half turns; the two halves of one bore: one full turn
    assert measure.axial_clusters([(-38, -10, 180), (62, 90, 180)]) == [(-38, -10, 180), (62, 90, 180)]
    assert measure.axial_clusters([(0, 20, 180), (0, 20, 180)]) == [(0, 20, 360)]


def test_hole_edge_says_the_size_that_clears_it() -> None:
    """A real opening too near the edge (not a split bore): the gate gives the envelope that leaves the wall, and
    Fix with Archie tries that size first (the old steps of 2 to 8 mm could never reach a Ø47 opening)."""
    it = {"name": "Block", "role": "block", "shape": "box", "size": [100.0, 60.0, 40.0], "parent": None,
          "copies": [[0.0, 0.0, -20.0]], "qty": 1, "sub": "s"}
    skel = {"items": {"b": it, "c": {**it, "name": "Plate", "size": [100.0, 60.0, 10.0], "copies": [[0, 0, 5.0]]}}}
    f = {"id": "IF-01", "kind": "face", "a": {"item": "b", "copy": 0, "name": "Block"},
         "b": {"item": "c", "copy": 0, "name": "Plate"},
         "data": {"plane_z": 0.0, "normal": [0, 0, 1], "flatness": 0.05, "position_tol": 0.1,
                  "passages": [{"at": [0.0, 20.0], "d_a": 30.0, "d_b": 30.0}]}}
    edge = [x for x in icd.issues(skel, [f]) if x["code"] == "hole_edge" and x["items"] == ["b"]]
    assert edge and edge[0]["grow"] == {"W": 73.0}  # 2 x (20 + 15 + 1.5)
    assert interfaces._grow(it, edge[0]["grow"])[0] == {"W": 73.0}
    # a split half on its joint face is not "on the edge"
    f["data"]["passages"][0].update(at=[0.0, 30.0], split_a=True, split_b=True)
    assert not [x for x in icd.issues(skel, [f]) if x["code"] == "hole_edge"]


# ----------------------------------------------------------------------------- Fix with Archie on a stale program
def test_fix_with_archie_measures_a_stale_master_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The program as the founder had it (the A4 plan, its old measurement, its ICD draft blocked): Fix with Archie
    measures the master again from its script (no tokens), lays the interfaces out from it, and the gate is clear."""
    monkeypatch.setattr(service, "emit", lambda *a, **k: None)
    monkeypatch.setattr(supervisor, "enabled", lambda: False)
    old = _legacy("planetary")
    plan = _plan("planetary")
    plan["layout_path"] = {"path": "master", "reasons": [], "words": "Laid out from a master model", "state": "done"}
    plan["master"] = {"ok": True, "measure": old["measure"], "via": "agent"}
    items, tickets = service._build(plan, "Planetary", "P", old["brief"])
    pid = "a1b2c3d4e5f6"
    doc: dict[str, Any] = {"id": pid, "name": "Planetary", "brief": old["brief"], "plan": plan, "items": items,
                           "tickets": tickets, "status": "active", "event_seq": 0, "change_requests": [],
                           "gates": [{"code": "brief", "status": "approved"}, {"code": "icd", "status": "pending"}]}
    interfaces.create(tmp_path, doc, {"name": "Archie"})
    # the old reading still blocks the gate (the ring gear in the split cavity is no joint in it), and Archie's
    # automatic fix grew both housing halves to clear the "openings on the edge" (a split bore read as a hole)
    assert doc["icd"]["problems"]
    assert {k: v["H"] for k, v in doc["icd"]["overrides"]["items"].items()} == {"i_s1_p3": 185.0, "i_s1_p4": 170.0}
    assert run.stale(doc)
    ws = store.program_dir(tmp_path, pid) / "master" / "ws"
    ws.mkdir(parents=True)
    (ws / "model.py").write_text((G / "planetary.master.py").read_text(encoding="utf-8"), encoding="utf-8")
    store.save(tmp_path, doc)

    res = asyncio.run(supervisor.fix_gate(tmp_path, pid, {"name": "Engineer"}))
    assert res["remeasured"]["ok"] and res["problems"] == [], res
    assert "laid the interfaces out from it" in res["remeasured"]["text"]
    doc2 = store.load(tmp_path, pid)
    assert doc2 is not None and doc2["icd"]["problems"] == [] and not run.stale(doc2)
    assert doc2["plan"]["master"]["measure"]["version"] == measure.VERSION
    assert doc2["plan"]["master"]["summary"]["bearings"] == 5 and doc2["plan"]["master"]["errors"] == []
    # the base keeps its measured envelope (an automatic growth made for the old reading does not stay)
    base = next(i for i, it in doc2["skeleton"]["items"].items() if it["name"] == "Housing base")
    assert doc2["skeleton"]["items"][base]["size"] == [128.0, 320.0, 135.0]
    assert any(h["kind"] == "fixed" and "measured the master model again" in h["text"]
               for h in doc2["icd"]["history"])
    # a second click has nothing to measure again
    assert asyncio.run(run.remeasure(tmp_path, pid)) is None
