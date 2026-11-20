"""The instant, dimensioned 3D layout preview at plan time (WORKLIST 47; ``graph/preview.py``).

Every expected number is a hand calculation from the layout rules the connection-layout tests already check
(tests/test_connection_layout.py), never a measurement of the output:

1. Keyed gear on a stepped shaft: the shaft (80 long) along +Y with its centre at Y 18 (Y -22 .. 58), a Ø20 seat from
   Y -22 to the shoulder at Y 0 and the Ø26 step behind it: in the shaft's own frame (centred, Z along its axis)
   segments Z -40 .. -18 Ø20 and -18 .. 40 Ø26. The gear m2 x 30 at Y -20 .. 0 (centre -10), tip Ø m (z + 2) = 64,
   face 20, bore 20. The DIN 6885 6 x 6 x 18 key: underside on the keyseat floor 10 - 3.5 = 6.5 off the axis, so its
   centre is 6.5 + 6 / 2 = 9.5 along +X, at Y -10. Envelope: X and Z +-32 (the tip circle), Y -22 .. 58.
2. 1:3 pair m2 20 / 60: a = m (z1 + z2) / 2 = 80; four 6204 (20 x 47 x 14) at Y 15 .. 29 and -29 .. -15, centres
   Y +-22 on X 0 and 80; envelope X -23.5 (the 6204's Ø47 / 2) .. 80 + 62 (the 60-tooth tip Ø124 / 2) = 142, Y +-39
   (the 78 shafts), Z +-62.
3. The founder's foldable table (R3): legs 40 x 20 x 700 at (+-540, +-280, -370), brackets 60 x 30 x 60 at
   (+-540, +-305, -48); each M8 pivot bolt runs through bracket (30) and leg (20): 50 long, head on the bracket side
   (Y -320 for copy 1), tip at the leg's inner face (Y -270); 16 M5 wood screws; envelope 1200 x 700 x 720.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import pytest
from test_office_orchestrator import _topup, _wait, office  # noqa: F401  (fixture)

from aicad import llm
from aicad.graph import intent, preview, questions
from aicad.graph import office as goffice
from aicad.llm.stub import StubProvider
from aicad.office import OfficeInputError

G1 = Path(__file__).parent / "golden" / "design_graph"
GC = Path(__file__).parent.parent / "src" / "aicad" / "eval" / "golden_cases"


def _doc(path: Path) -> dict[str, Any]:
    """A program in plan review whose plan came from a recorded intent reply (as the office's graph planner makes it)."""
    d = json.loads(path.read_text(encoding="utf-8"))
    g, iss, _qs = intent.compile_reply(d["reply"], d["name"], d["brief"])
    out = goffice.finish(goffice.OfficePlan(None), g, iss)
    assert out.plan is not None, out.error
    return {"name": d["name"], "brief": d["brief"], "plan": out.plan, "status": "plan_review"}


def _by_name(pv: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for b in pv["bodies"]:
        out.setdefault(b["name"].split(" #")[0], []).append(b)
    return out


def _at(b: dict[str, Any]) -> list[float]:
    return [round(b["T"][3], 6) + 0.0, round(b["T"][7], 6) + 0.0, round(b["T"][11], 6) + 0.0]


def _axis(b: dict[str, Any]) -> list[float]:
    return [round(b["T"][2], 6) + 0.0, round(b["T"][6], 6) + 0.0, round(b["T"][10], 6) + 0.0]


def _dim(pv: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    return [d for d in pv["dims"] if d["id"].startswith(prefix)]


# ----------------------------------------------------------------------------- 1. the keyed gear
def test_keyed_gear_preview_hand_checked() -> None:
    pv = preview.for_program(_doc(G1 / "keyed_gear.json"))
    assert pv["state"] == "plan" and pv["solver"] == "graph" and pv["version"] == preview.VERSION
    b = _by_name(pv)
    (shaft,), (gear,), (key,) = b["Stepped shaft"], b["Spur gear"], b["Parallel key"]
    assert shaft["kind"] == "shaft" and _at(shaft) == [0, 18, 0] and _axis(shaft) == [0, 1, 0]
    assert shaft["g"]["segs"] == [[-40, -18, 20], [-18, 40, 26]]
    assert gear["kind"] == "gear" and _at(gear) == [0, -10, 0] and _axis(gear) == [0, 1, 0]
    assert (gear["g"]["tip"], gear["g"]["pitch"], gear["g"]["width"], gear["g"]["bore"]) == (64, 60, 20, 20)
    assert key["kind"] == "key" and key["g"]["s"] == [18, 6, 6] and _at(key) == [9.5, -10, 0]
    assert _axis(key) == [1, 0, 0]  # the key's Z (its height) points out of the keyseat, along +X
    # how each part will be made: both designed parts from the spec (no AI), the key from the Toolbox
    assert (shaft["path"], gear["path"], key["path"]) == ("spec", "spec", "toolbox")
    assert pv["paths"] == {"spec": 2, "toolbox": 1, "template": 0, "ai": 0}
    assert pv["envelope"] == {"min": [-32, -22, -32], "max": [32, 58, 32]}
    env = {d["id"]: d["value"] for d in _dim(pv, "env:")}
    assert env == {"env:X": 64, "env:Y": 80, "env:Z": 64}
    (seat,) = _dim(pv, "dia:")
    assert seat["r"] == 10 and seat["text"] == "Ø20 k6" and seat["c"] == [0, -11, 0]  # the seat Y -22 .. 0
    # where the numbers came from: the seat Ø and the gear size were assumed (the brief gives none), a = rule
    assert seat["sources"][0]["word"] == "assumed"
    size = next(d for d in pv["dims"] if d["id"] == "size:" + gear["item"])
    words = {s["what"]: s["word"] for s in size["sources"]}
    assert words == {"Module": "assumed", "Teeth": "assumed", "Face width": "design rule", "Tip circle": "standard"}
    assert pv["counts"]["errors"] == 0 and not any(x.get("flag") for x in pv["bodies"])
    # the shaft delivered as a sub-assembly is a note, not a red part
    assert [x["code"] for x in pv["issues"]] == ["shaft_support"] and pv["issues"][0]["severity"] == "warning"


# ----------------------------------------------------------------------------- 2. the 1:3 gear pair
def test_gear_pair_preview_hand_checked() -> None:
    pv = preview.for_program(_doc(G1 / "gear_pair.json"))
    b = _by_name(pv)
    (pin,), (gear,) = b["Pinion"], b["Gear"]
    assert _at(pin) == [0, 0, 0] and _at(gear) == [80, 0, 0]
    assert pin["g"]["tip"] == 44 and gear["g"]["tip"] == 124
    bearings = next(v for k, v in b.items() if "6204" in k)
    assert sorted(_at(x) for x in bearings) == [[0, -22, 0], [0, 22, 0], [80, -22, 0], [80, 22, 0]]
    assert all(x["kind"] == "bearing" and x["g"] == {"d": 20, "D": 47, "B": 14} for x in bearings)
    (cd,) = _dim(pv, "cd:")
    assert cd["kind"] == "linear" and cd["a"] == [0, 0, 0] and cd["b"] == [80, 0, 0] and cd["value"] == 80
    assert cd["text"] == "80" and cd["prio"] == 1
    assert cd["sources"][0]["what"] == "Centre distance" and cd["sources"][0]["word"] in ("design rule", "standard")
    assert pv["envelope"] == {"min": [-23.5, -39, -62], "max": [142, 39, 62]}
    assert pv["paths"]["spec"] == 4 and pv["paths"]["ai"] == 0
    assert {d["text"] for d in _dim(pv, "dia:")} == {"Ø20 k6"}  # the journals, one per shaft
    assert pv["counts"]["errors"] == 0


# ----------------------------------------------------------------------------- 3. the table (corners)
def test_table_preview_corners_and_pivot_bolts() -> None:
    pv = preview.for_program(_doc(GC / "r_table.intent.json"))
    b = _by_name(pv)
    assert sorted(_at(x) for x in b["Folding leg"]) == [[-540, -280, -370], [-540, 280, -370], [540, -280, -370],
                                                        [540, 280, -370]]
    assert sorted(_at(x) for x in b["Leg hinge bracket"]) == [[-540, -305, -48], [-540, 305, -48], [540, -305, -48],
                                                              [540, 305, -48]]
    assert all(x["g"]["s"] == [40, 20, 700] for x in b["Folding leg"])
    pivots = b["Leg pivot bolt"]
    assert len(pivots) == 4 and all(x["kind"] == "screw" and x["g"]["L"] == 50 and x["g"]["d"] == 8 for x in pivots)
    first = min(pivots, key=lambda x: (_at(x)[0], _at(x)[1]))
    # tip at the leg's inner face (Y -270), shank along -Y towards the head on the bracket's outer face (Y -320)
    assert _at(first) == [-540, -270, -40] and _axis(first) == [0, -1, 0]
    assert len(b["Bracket wood screw"]) == 16 and all(x["g"]["d"] == 5 for x in b["Bracket wood screw"])
    assert pv["envelope"]["min"][:2] == [-600, -350] and pv["envelope"]["max"] == [600, 350, 0]
    assert pv["envelope"]["min"][2] == -720
    assert {d["id"]: d["value"] for d in _dim(pv, "env:")} == {"env:X": 1200, "env:Y": 700, "env:Z": 720}
    assert pv["counts"]["errors"] == 0


# ----------------------------------------------------------------------------- problems drawn in red
def _pair_doc(extra_c: list[dict[str, Any]], extra_x: list[dict[str, Any]]) -> dict[str, Any]:
    reply = {"components": [
        {"id": "s1", "kind": "shaft", "name": "Input shaft", "params": {"d": 20, "role": "input"}},
        {"id": "s2", "kind": "shaft", "name": "Output shaft", "params": {"d": 20, "role": "output"}},
        {"id": "g1", "kind": "spur_gear", "name": "Pinion", "params": {"module": 2, "teeth": 20}},
        {"id": "g2", "kind": "spur_gear", "name": "Gear", "params": {"module": 2, "teeth": 60}},
        {"id": "b", "kind": "bearing", "name": "Bearing 6204", "qty": 4, "params": {"designation": 6204}}] + extra_c,
        "connections": [{"kind": "hub_fit", "host": "s1", "guest": "g1"}, {"kind": "hub_fit", "host": "s2", "guest": "g2"},
                        {"kind": "gear_mesh", "host": "g1", "guest": "g2"},
                        {"kind": "bearing_journal", "host": "s1", "guest": "b", "params": {"count": 2}},
                        {"kind": "bearing_journal", "host": "s2", "guest": "b", "params": {"count": 2}}] + extra_x}
    g, iss, _qs = intent.compile_reply(reply, "Pair", "A spur pair, no housing.")
    out = goffice.finish(goffice.OfficePlan(None), g, iss)
    assert out.plan is not None
    return {"name": "Pair", "brief": "A spur pair, no housing.", "plan": out.plan, "status": "plan_review"}


def test_a_layout_conflict_and_an_unconnected_part_are_red_with_their_text() -> None:
    pv = preview.for_program(_pair_doc([], [{"kind": "hub_fit", "host": "s1", "guest": "g2"}]))
    conf = [x for x in pv["issues"] if x["code"] == "layout_conflict"]
    assert len(conf) == 1 and conf[0]["severity"] == "error" and "fitted on two shafts" in conf[0]["text"]
    red = {b["name"] for b in pv["bodies"] if b.get("flag") == "error"}
    assert {"Gear", "Input shaft", "Output shaft"} <= red
    assert pv["counts"]["errors"] >= 1
    pv = preview.for_program(_pair_doc([{"id": "sp", "kind": "spacer", "name": "Spacer", "params": {"od": 30,
                                                                                                  "length": 5}}], []))
    codes = {x["code"] for x in pv["issues"] if x["severity"] == "error"}
    assert {"layout_conflict", "no_interface"} <= codes
    assert next(b for b in pv["bodies"] if b["name"] == "Spacer")["flag"] == "error"


def test_an_unconnected_copy_is_red_alone() -> None:
    """Per copy (the founder's TEST Project): leg #2 of two with no interface is red, leg #1 is not."""
    skel = {"layout": "block", "base": "top", "items": {
        "top": {"name": "Top", "role": "block", "shape": "box", "size": [400, 200, 20], "copies": [[0, 0, -10]]},
        "leg": {"name": "Leg", "role": "block", "shape": "box", "size": [30, 30, 300],
                "copies": [[-150, 0, -170], [150, 0, -170]]}}, "standard": []}
    ifs = [{"id": "IF-01", "kind": "face", "a": {"item": "top", "copy": 0, "name": "Top"},
            "b": {"item": "leg", "copy": 0, "name": "Leg #1"}, "data": {"plane_z": -20, "flatness": 0.05}}]
    pv = preview.scene(skel, ifs)
    flags = {b["id"]: b.get("flag") for b in pv["bodies"]}
    assert flags == {"top#0": None, "leg#0": None, "leg#1": "error"}
    (x,) = [i for i in pv["issues"] if i["code"] == "no_interface"]
    assert x["bodies"] == ["leg#1"] and x["text"].startswith("Leg #2: no interface connects this copy")


def test_an_unplaced_bought_out_part_is_listed() -> None:
    """A pin nothing places has no position: it is listed with its text (never silently dropped)."""
    skel = {"layout": "block", "items": {"a": {"name": "Plate", "role": "block", "shape": "box", "size": [50, 50, 10],
                                               "copies": [[0, 0, 0]]}},
            "standard": [{"item": "pin", "name": "Locating pin", "qty": 2}]}
    pv = preview.scene(skel, [])
    assert pv["unplaced"] == ["pin"]
    (x,) = [i for i in pv["issues"] if i["code"] == "part_unplaced"]
    assert "Locating pin" in x["text"] and x["bodies"] == []


# ----------------------------------------------------------------------------- edits, master path, timing
def test_edited_plan_is_laid_out_without_saving_and_rows_keep_their_place() -> None:
    doc = _doc(G1 / "gear_pair.json")
    before = json.dumps(doc, sort_keys=True)
    plan = json.loads(json.dumps(doc["plan"]))
    sub = plan["subassemblies"][0]
    sub["parts"] = [p for p in sub["parts"] if p["name"] != "Gear"]  # the engineer deletes the wheel
    pv = preview.for_program(doc, plan)
    assert pv["state"] == "edited" and json.dumps(doc, sort_keys=True) == before
    assert not any(b["name"] == "Gear" for b in pv["bodies"]) and any(b["name"] == "Pinion" for b in pv["bodies"])
    at = {r["name"]: r.get("at") for r in pv["rows"].values()}
    assert all(at[p["name"]] == [0, i] for i, p in enumerate(sub["parts"]) if p["name"] in at)
    assert at["Output shaft"] is not None
    with pytest.raises(OfficeInputError):
        preview.for_program(doc, {"subassemblies": []})


def test_master_path_numbers_are_tagged_as_measured() -> None:
    skel = {"layout": "master", "solver": "master", "items": {
        "lo": {"name": "Lower shell", "role": "block", "shape": "box", "size": [150, 95, 18], "copies": [[0, 0, -9]]},
        "up": {"name": "Upper shell", "role": "block", "shape": "box", "size": [150, 95, 14], "copies": [[0, 0, 7]]}},
        "standard": [{"item": "scr", "name": "Shell screw", "qty": 4}]}
    ifs = [{"id": "IF-01", "kind": "hole_pattern", "a": {"item": "up", "copy": 0, "name": "Upper shell"},
            "b": {"item": "lo", "copy": 0, "name": "Lower shell"},
            "data": {"fastener": "M3", "fastener_size": 3, "fastener_item": "scr", "count": 4, "d": 3.4, "pattern": "grid",
                     "inset": 8, "plane_z": 0, "normal": [0, 0, -1],
                     "positions": [[-53.5, -33.5], [53.5, -33.5], [-53.5, 33.5], [53.5, 33.5]],
                     "tapped": {"d": 2.5, "depth": 8, "thread": "M3"}}}]
    pv = preview.scene(skel, ifs)
    assert pv["master"] and {s["word"] for d in pv["dims"] for s in d["sources"]} == {"measured from the master model"}
    screws = [b for b in pv["bodies"] if b["kind"] == "screw"]
    # tapped into the upper shell (side a) 8 deep, head under the lower shell: the screw's own Z runs from its tip
    # (8 up in the tapped hole) down to the head
    assert len(screws) == 4 and all(_axis(s) == [0, 0, -1] for s in screws)
    assert sorted(_at(s)[:2] for s in screws) == [[-53.5, -33.5], [-53.5, 33.5], [53.5, -33.5], [53.5, 33.5]]
    assert all(_at(s)[2] == 8 for s in screws)          # the tip 8 mm up in the tapped hole
    assert all(s["g"]["L"] == 8 + 9 for s in screws)    # + min(18 deep lower shell, 3 d = 9) of clamp


def test_reducer_and_table_are_fast() -> None:
    """Target: endpoint plus client render under 1 s together. The server side (layout, build paths, scene) is
    measured here warm; the browser walkthrough measures the endpoint and the render on the real page."""
    for path in (G1 / "reducer.json", GC / "r_table.intent.json"):
        doc = _doc(path)
        preview.for_program(doc)  # imports and caches warm
        t0 = time.perf_counter()
        pv = preview.for_program(doc)
        dt = time.perf_counter() - t0
        assert dt < 0.5, (path.name, dt, pv["ms"])
        assert len(json.dumps(pv)) < 60_000


def test_reducer_preview_shows_caps_screws_and_bolt_circles() -> None:
    pv = preview.for_program(_doc(G1 / "reducer.json"))
    b = _by_name(pv)
    housing = b["Housing base"][0]
    assert housing["g"].get("open") and housing["path"] in ("spec", "ai")
    caps = [x for k, v in b.items() if "cap" in k.lower() and "screw" not in k.lower() for x in v]
    assert len(caps) == 4
    pcds = sorted(d["value"] for d in _dim(pv, "pcd:"))
    assert len(pcds) == 2 and pcds[0] < pcds[1]  # one bolt circle per bearing size (both caps of a seat share it)
    (cd,) = _dim(pv, "cd:")
    assert math.isclose(cd["value"], 80)
    assert len([x for x in pv["bodies"] if x["kind"] == "screw"]) == 16 + 4


# ----------------------------------------------------------------------------- the API, live update
def test_api_preview_updates_when_a_question_is_answered(office: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Plan review shows the preview at once; answering Archie's housing question changes it (the housing, cover and
    caps appear); the review's unsaved edits are laid out without saving; after approval it shows the interfaces."""
    from test_platform import signup

    monkeypatch.setenv(goffice.ENV, "1")
    reply = {"components": [
        {"id": "s1", "kind": "shaft", "name": "Input shaft"}, {"id": "s2", "kind": "shaft", "name": "Output shaft"},
        {"id": "p", "kind": "spur_gear", "name": "Pinion", "params": {"module": 2, "teeth": 20}},
        {"id": "w", "kind": "spur_gear", "name": "Gear", "params": {"module": 2, "teeth": 40}},
        {"id": "b", "kind": "bearing", "name": "Bearing 6204", "qty": 4, "params": {"designation": 6204}}],
        "connections": [{"kind": "keyed_hub", "host": "s1", "guest": "p"}, {"kind": "keyed_hub", "host": "s2", "guest": "w"},
                        {"kind": "gear_mesh", "host": "p", "guest": "w"},
                        {"kind": "bearing_journal", "host": "s1", "guest": "b", "params": {"count": 2}},
                        {"kind": "bearing_journal", "host": "s2", "guest": "b", "params": {"count": 2}}]}
    stub = StubProvider(lambda req: "```json\n" + json.dumps(reply) + "\n```" if req.role == "intent" else None)
    c = office
    signup(c, "preview@x.com")
    _topup("preview@x.com")
    with llm.use_provider(stub, roles=("intent",)):
        pid = c.post("/api/office/programs", json={"name": "Pair", "brief": "A 1:2 spur pair m2 20/40 on two shafts "
                                                   "with 6204 bearings", "planner": "archie"}).json()["id"]
        _wait(c, pid, lambda v: v["status"] == "plan_review")
        r = c.get(f"/api/office/programs/{pid}/preview")
        assert r.status_code == 200, r.text
        p1 = r.json()
        assert p1["state"] == "plan" and not any("Housing" in b["name"] for b in p1["bodies"])
        (cd,) = [d for d in p1["dims"] if d["id"].startswith("cd:")]
        assert cd["value"] == 60  # a = 2 (20 + 40) / 2
        r = c.post(f"/api/office/programs/{pid}/plan/answers", json={"answers": {"housing": questions.HOUSING_YES}})
        assert r.status_code == 200, r.text
    p2 = c.get(f"/api/office/programs/{pid}/preview").json()
    names = {b["name"].split(" #")[0] for b in p2["bodies"]}
    assert {"Housing base", "Housing cover"} <= names and any("cap" in n.lower() for n in names)
    # a = 60 is too close for two Ø60 bearing caps side by side: the solver says so, and the preview draws the caps
    # in red with that text before anyone approves (the engineer can change the module, the ratio or the caps)
    conf = [x for x in p2["issues"] if x["code"] == "layout_conflict"]
    assert conf and any("no cap fits over the seats" in x["text"] for x in conf)
    caps = [b for b in p2["bodies"] if "cap" in b["name"].lower() and b["kind"] != "screw"]
    assert len(caps) == 4 and all(b["flag"] == "error" for b in caps)
    assert not any(b.get("flag") for b in p2["bodies"] if b["name"].startswith(("Pinion", "Gear", "Input shaft")))
    assert p2["counts"]["errors"] >= 4
    # unsaved edits: the cover removed from the plan is laid out, nothing saved
    plan = json.loads(json.dumps(r.json()["plan"]))
    for s in plan["subassemblies"]:
        s["parts"] = [p for p in s["parts"] if p["name"] != "Housing cover"]
    p3 = c.post(f"/api/office/programs/{pid}/preview", json={"plan": plan}).json()
    assert p3["state"] == "edited" and not any(b["name"] == "Housing cover" for b in p3["bodies"])
    assert c.get(f"/api/office/programs/{pid}").json()["plan"]["subassemblies"] == r.json()["plan"]["subassemblies"]
    text = json.dumps(p2).lower()
    assert "claude" not in text and "model.py" not in text and ".py" not in text
    assert c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={}).status_code == 200
    p4 = c.get(f"/api/office/programs/{pid}/preview").json()
    assert p4["state"] == "icd" and p4["icd_version"] == 1
    assert {b["id"] for b in p4["bodies"]} == {b["id"] for b in p2["bodies"]}  # the gate shows what was previewed
    assert c.get(f"/api/office/programs/{pid}/preview/compare/R-9").status_code == 409


# ----------------------------------------------------------------------------- revisions: before and after
def test_revision_before_and_after() -> None:
    """A revision Archie proposes (the candidate, not applied) and one that was applied (its snapshot, then the
    program now). Two legs on two brackets instead of four: the brackets go to the ends of the top's long sides,
    centred across it (X +-(600 - 30 - 30) = +-540, Y 0; Y -15 .. 15 for a 30 wide bracket), each leg inboard of its
    bracket (20 wide: Y 15 .. 35, centre 25)."""
    import copy

    from aicad.office import revision

    ops = [{"op": "qty", "part": "Folding leg", "qty": 2}, {"op": "qty", "part": "Leg hinge bracket", "qty": 2}]
    prog, _sk, _ifs, _notes = preview.plan_layout(_doc(GC / "r_table.intent.json"))
    prog.update(status="active", key="P", supervisor={"log": [{
        "id": "S-1", "status": "asking", "title": "Two legs", "action": {"tool": "revise_program", "changes": ops}}]})

    def place(pv: dict[str, Any], name: str) -> list[list[float]]:
        return sorted(_at(b) for b in pv["bodies"] if b["name"].startswith(name))

    out = preview.compare(prog, "S-1")
    assert place(out["before"], "Folding leg") == [[-540, -280, -370], [-540, 280, -370], [540, -280, -370],
                                                   [540, 280, -370]]
    assert place(out["after"], "Folding leg") == [[-540, 25, -370], [540, 25, -370]]
    assert place(out["after"], "Leg hinge bracket") == [[-540, 0, -48], [540, 0, -48]]
    assert out["after"]["counts"]["errors"] == 0
    # applied: the snapshot is the before, the program now the after
    cand = revision.candidate(prog, ops)
    now = {**copy.deepcopy(prog), "plan": cand["plan"], "items": cand["items"], "skeleton": cand["skeleton"],
           "icd": {**prog["icd"], "interfaces": cand["interfaces"], "version": 2},
           "revisions": [{"id": "R-1", "status": "applied", "icd_from": 1, "icd_to": 2, "snapshot": copy.deepcopy(prog)}]}
    out = preview.compare(now, "R-1")
    assert len(place(out["before"], "Folding leg")) == 4 and place(out["after"], "Folding leg") == [[-540, 25, -370],
                                                                                                  [540, 25, -370]]
    assert out["after"]["icd_version"] == 2 and out["title"].startswith("R-1")
    with pytest.raises(OfficeInputError):
        preview.compare(now, "R-7")
