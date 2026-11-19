"""Program revision at any stage (``office/revision.py``, ``docs/reports/program-revision.md``, PD-150..).

The founder's TEST Project ("Design a foldable Table", 2026-11-20) stopped at Assemble Legs: the block layout made the
Folding leg (4 off) the base, hung the Table top and all four hinge brackets on leg #1 and laid legs #2 to #4 out loose.
The ICD gate checked ``no_interface`` per item, not per copy, so it passed; the quick check at Assemble Legs found leg
#2 floating; and nothing could revise an approved, partly integrated program, so Archie told the founder to start a
new program. These tests rebuild that program from its plan (no CAD, no model call) and check, by hand, what a
revision keeps, re-places, redesigns, adds and removes; that it is applied end to end with records; that undo works
while nothing was rebuilt; and that Archie proposes it himself and asks with the impact list.

Hand calculations use the block layout's rules (``office/icd.py``): a host's children stand in a row along +X on its
top face, centred, ``GAP`` = max(12, a tenth of the larger part) between neighbours and ``MARGIN`` = 10 mm at the ends
of an unplanned host; a bolted joint's holes sit ``inset`` = 11 mm in from the guest's edges; datum A is the base's top
face (Z = 0)."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Any

import pytest

from aicad.office import (
    archie_chat,
    icd,
    interfaces,
    orchestrator,
    planner,
    revision,
    service,
    store,
    supervisor,
)

ENG = {"kind": "user", "id": "u1", "name": "Eng"}

# the founder's TEST Project plan and design graph, as Archie planned them (data/office/.../program.json, read only)
TABLE_PLAN = {"summary": "Foldable table: wooden top with four steel legs, each on a steel hinge bracket screwed under "
                         "the top so the leg pivots on a bolt and folds flat beneath the top.",
              "subassemblies": [
                  {"name": "Top", "parts": [
                      {"name": "Table top", "family": "machined", "complexity": 2, "qty": 1,
                       "description": "Plate (size assumed), Wood."}]},
                  {"name": "Legs", "parts": [
                      {"name": "Folding leg", "family": "machined", "complexity": 3, "qty": 4,
                       "description": "Folding leg, Steel."},
                      {"name": "Leg hinge bracket", "family": "machined", "complexity": 2, "qty": 4,
                       "description": "Bracket (size assumed), Steel."}]},
                  {"name": "Fasteners", "parts": [
                      {"name": "Bracket wood screw", "family": "standard", "complexity": 1, "qty": 16,
                       "description": "Socket head cap screw.", "toolbox": "shcs"},
                      {"name": "Leg pivot bolt", "family": "standard", "complexity": 1, "qty": 4,
                       "description": "Hex bolt.", "toolbox": "hex_bolt"},
                      {"name": "Pivot washer", "family": "standard", "complexity": 1, "qty": 8,
                       "description": "Washer.", "toolbox": "washer"},
                      {"name": "Pivot lock nut", "family": "standard", "complexity": 1, "qty": 4,
                       "description": "Hex nut.", "toolbox": "hex_nut"}]}]}
TABLE_GRAPH = {"icd_overrides": {}, "components": {
    "table_top": "Table top", "leg": "Folding leg", "hinge_bracket": "Leg hinge bracket",
    "bracket_screw": "Bracket wood screw", "pivot_bolt": "Leg pivot bolt", "pivot_washer": "Pivot washer",
    "pivot_nut": "Pivot lock nut"},
    "data": {"schema": "fw-design-graph", "version": 1, "name": "TEST Project", "brief": "Design a foldable Table",
             "components": [{"id": "table_top", "kind": "plate", "name": "Table top", "qty": 1},
                            {"id": "leg", "kind": "other", "name": "Folding leg", "qty": 4},
                            {"id": "hinge_bracket", "kind": "bracket", "name": "Leg hinge bracket", "qty": 4}],
             "connections": [
                 {"id": "c1", "kind": "bolted_joint", "host": "table_top", "guest": "hinge_bracket",
                  "via": ["bracket_screw"], "params": {}},
                 {"id": "c2", "kind": "bolted_joint", "host": "hinge_bracket", "guest": "leg",
                  "via": ["pivot_bolt", "pivot_washer", "pivot_nut"], "params": {}}]}}
FLOATING = "Folding leg #2 touches nothing in the rest of the assembly (apart, or floating)."
# what Archie proposed live for the table (the founder's own words: the top is the base, a bracket under each corner,
# each leg pivoting on its own bracket), with the sizes he chose
CORRECTED = [{"op": "base", "part": "Table top"}, {"op": "size", "part": "Table top", "envelope": [1200, 600, 18]},
             {"op": "mount", "part": "Leg hinge bracket", "on": "Table top"},
             {"op": "size", "part": "Leg hinge bracket", "envelope": [80, 60, 40]},
             {"op": "mount", "part": "Folding leg", "on": "Leg hinge bracket"},
             {"op": "size", "part": "Folding leg", "envelope": [40, 40, 700]}]


@pytest.fixture(autouse=True)
def _quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FW_OFFICE_SUPERVISOR", "1")
    monkeypatch.setenv("FW_OFFICE_SUPERVISOR_AI", "0")  # the rule-based reading: no model call anywhere here
    monkeypatch.delenv("FW_OFFICE_FAKE_AGENTS", raising=False)
    monkeypatch.setattr(supervisor, "DEBOUNCE_S", 0.0)
    monkeypatch.setattr(supervisor, "wallet_left", lambda org_id: 500)
    monkeypatch.setattr(supervisor, "charge", lambda *a, **k: None)
    supervisor._running.clear()
    supervisor._again.clear()


def _ids(doc: dict[str, Any]) -> dict[str, str]:
    return {it["name"]: it["id"] for it in doc["items"] if it["kind"] in ("part", "subassembly")}


def _t(doc: dict[str, Any], title: str) -> dict[str, Any]:
    return next(t for t in doc["tickets"] if t["title"] == title)


def _done(doc: dict[str, Any], blocked: str | None = None, reason: str = FLOATING) -> None:
    """Every part approved and built, every level integrated, except ``blocked`` (stopped on ``reason``, paused by
    Archie as in the founder's program) and the final assembly waiting for it."""
    for t in doc["tickets"]:
        t["column"] = "integrated"
        t["milestones"] = ["brief_read", "first_build", "gates_pass", "self_review", "approved"]
        t["run"] = {"status": "done", "turns": 1}
        if t["kind"] == "part":
            t["project_id"] = f"p-{t['id']}"
            t["fitted"] = True
    if blocked:
        t = _t(doc, blocked)
        t["column"] = "changes_requested"
        t["run"] = {"status": "blocked", "next": "integrate", "blocked": reason, "line": reason}
        t["paused"] = True
        for x in doc["tickets"]:
            if x["id"] in t["depends_on"]:
                x["column"] = "approved"
        final = next(x for x in doc["tickets"] if x["item_id"] == "root")
        final["column"], final["run"] = "backlog", None
    doc["status"] = "active"
    doc["orchestrator"] = {"state": "running", "user_id": "u1"}


def _table(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    root = store.org_root(tmp_path, "org1")
    doc = service.new_program("TEST Project", "Design a foldable Table", "org1", "u1", 3, 3000, "standard")
    plan = planner.normalise_plan(TABLE_PLAN, "archie")
    plan["graph"] = copy.deepcopy(TABLE_GRAPH)
    service.set_plan(root, doc, plan, ENG)
    service.approve_plan(root, doc, None, ENG)
    interfaces.approve(root, doc, ENG)
    _done(doc, blocked="Assemble Legs")
    # as in the founder's program: he moved the final assembly to Integrated by hand, it stopped on the same floating
    # leg and Archie paused it
    final = next(x for x in doc["tickets"] if x["item_id"] == "root")
    final["column"], final["paused"] = "integrated", True
    final["run"] = {"status": "blocked", "next": "integrate", "blocked": FLOATING, "line": FLOATING}
    store.save(root, doc)
    return root, doc


def _plate(tmp_path: Path, extra: list[dict[str, Any]] | None = None) -> tuple[Path, dict[str, Any]]:
    """A base plate 200 × 80 × 10 with a cover 60 × 40 × 6 bolted on it (4 M5), fully done."""
    root = store.org_root(tmp_path, "org1")
    parts = [{"name": "Base plate", "family": "machined", "complexity": 2, "qty": 1, "description": "Base plate, steel.",
              "envelope": [200, 80, 10]},
             {"name": "Cover", "family": "machined", "complexity": 2, "qty": 1, "description": "Cover, aluminium.",
              "envelope": [60, 40, 6], "mounts_on": "Base plate"}] + (extra or []) + [
             {"name": "Frame bolt", "family": "standard", "complexity": 1, "qty": 4, "description": "Hex bolt M5."}]
    doc = service.new_program("Plate and cover", "A base plate with a cover bolted on it", "org1", "u1", 2, 1000,
                              "standard")
    service.set_plan(root, doc, planner.normalise_plan({"subassemblies": [{"name": "Frame", "parts": parts}]},
                                                       "standard"), ENG)
    service.approve_plan(root, doc, None, ENG)
    assert doc["icd"]["problems"] == []
    interfaces.approve(root, doc, ENG)
    _done(doc)
    doc["status"] = "complete"
    store.save(root, doc)
    return root, doc


def _classes(c: dict[str, Any]) -> dict[str, str]:
    return {r["name"]: r["class"] for r in c["impact"]["parts"]}


def _levels(c: dict[str, Any]) -> dict[str, str]:
    return {x["name"]: x["status"] for x in c["impact"]["levels"]}


# ============================================================================ the founder's table
def test_the_founder_table_block_reproduces_and_the_per_copy_check_sees_it(tmp_path: Path) -> None:
    _root, doc = _table(tmp_path)
    ids = _ids(doc)
    sk, ifs = doc["skeleton"], doc["icd"]["interfaces"]
    assert sk["base"] == ids["Folding leg"] and sk["layout"] == "block"  # the leg (4 off) became the base
    assert len(ifs) == 5 and all(f["a"]["item"] == ids["Folding leg"] and f["a"]["copy"] == 0 for f in ifs)
    assert icd.problems(sk, ifs) == []  # the gate passed: no_interface is per item
    assert revision.loose_copies(sk, ifs) == [(ids["Folding leg"], 1), (ids["Folding leg"], 2),
                                              (ids["Folding leg"], 3)]
    assert revision.placement_blocks(sk, ifs)[0] == "Folding leg #2, #3, #4: no interface places them"


def test_table_revision_archie_proposes_without_ai_keeps_the_kit_and_redesigns_the_three_parts(tmp_path: Path) -> None:
    _root, doc = _table(tmp_path)
    ids = _ids(doc)
    c = revision.propose(doc)
    assert c is not None and c["ok"]
    # the design graph says the top carries the brackets and each bracket a leg: the top (1 off) is the base
    assert c["ops"][:3] == [{"op": "base", "part": "Table top"},
                            {"op": "mount", "part": "Leg hinge bracket", "on": "Table top"},
                            {"op": "mount", "part": "Folding leg", "on": "Leg hinge bracket"}]
    sk = c["skeleton"]
    assert sk["base"] == ids["Table top"]
    it = sk["items"]
    # hand: 4 brackets 100 wide in a row on the top, gap 12, margins 10: 4 × 100 + 3 × 12 + 2 × 10 = 456; 70 + 20 = 90
    assert it[ids["Table top"]]["size"] == [456.0, 90.0, 16.0]
    # brackets centred: start -456 / 2 + 10 = -218, centres -168, -56, 56, 168; on the top face (Z 0), H 16: Z 8
    assert [x[0] for x in it[ids["Leg hinge bracket"]]["copies"]] == [-168.0, -56.0, 56.0, 168.0]
    assert it[ids["Leg hinge bracket"]]["size"] == [100.0, 70.0, 16.0]  # kept as sized, so copy n carries leg n
    # a leg 568 × 90 is wider than its 100 × 70 bracket: it stands on its end, 90 × 20 × 568, centre 16 + 284 = 300
    assert it[ids["Folding leg"]]["size"] == [90.0, 20.0, 568.0]
    assert it[ids["Folding leg"]]["copies"] == [[x, 0.0, 300.0] for x in (-168.0, -56.0, 56.0, 168.0)]
    # per copy: bracket n on the top, leg n on bracket n, nothing loose
    pairs = sorted((f["a"]["item"], f["a"]["copy"], f["b"]["item"], f["b"]["copy"]) for f in c["interfaces"])
    assert pairs == sorted([(ids["Table top"], 0, ids["Leg hinge bracket"], n) for n in range(4)]
                           + [(ids["Leg hinge bracket"], n, ids["Folding leg"], n) for n in range(4)])
    assert c["placement"]["after"] == [] and c["new_problems"] == []
    assert _classes(c) == {"Table top": "redesign", "Folding leg": "redesign", "Leg hinge bracket": "redesign",
                           "Bracket wood screw": "unchanged", "Leg pivot bolt": "unchanged",
                           "Pivot washer": "unchanged", "Pivot lock nut": "unchanged"}
    assert _levels(c) == {"Top": "rerun", "Legs": "rerun", "Fasteners": "kept", "Final assembly": "rerun"}
    rows = {r["name"]: r for r in c["impact"]["parts"]}
    assert rows["Table top"]["why"].startswith("envelope 100 × 70 × 16 → 456 × 90 × 16 mm")
    # the old joint with leg #1 goes from the top: its mounting face and 4 holes (5 features); the bracket keeps its
    # bottom face and holes (same place in its own frame) and gains the top face it carries the leg on
    assert len(rows["Table top"]["remove"]) == 5 and rows["Leg hinge bracket"]["remove"] == []
    assert c["impact"]["estimate"]["tokens"] == 3 * revision.REDESIGN_TOKENS  # three parts the designer redoes
    assert supervisor.classify(doc, {"tool": "revise_program", "impact": revision.view(c)})[0] == "major"


def test_table_revision_with_archies_corrected_plan(tmp_path: Path) -> None:
    _root, doc = _table(tmp_path)
    ids = _ids(doc)
    c = revision.candidate(doc, CORRECTED)
    assert c["ok"], c["why"]
    it = c["skeleton"]["items"]
    assert c["skeleton"]["base"] == ids["Table top"] and it[ids["Table top"]]["size"] == [1200.0, 600.0, 18.0]
    # hand: brackets 80 wide, gap max(12, 8) = 12: 4 × 80 + 3 × 12 = 356, centred: -138, -46, 46, 138; Z 40 / 2 = 20
    assert it[ids["Leg hinge bracket"]]["copies"] == [[x, 0.0, 20.0] for x in (-138.0, -46.0, 46.0, 138.0)]
    # each leg 700 tall stands on its bracket (top at Z 40): centre 40 + 350 = 390
    assert it[ids["Folding leg"]]["copies"] == [[x, 0.0, 390.0] for x in (-138.0, -46.0, 46.0, 138.0)]
    assert revision.loose_copies(c["skeleton"], c["interfaces"]) == []
    assert _classes(c)["Table top"] == _classes(c)["Folding leg"] == _classes(c)["Leg hinge bracket"] == "redesign"
    assert {k: v for k, v in _classes(c).items() if v != "redesign"} == {
        "Bracket wood screw": "unchanged", "Leg pivot bolt": "unchanged", "Pivot washer": "unchanged",
        "Pivot lock nut": "unchanged"}


def test_table_revision_applies_end_to_end_with_records_and_undo(tmp_path: Path) -> None:
    root, doc = _table(tmp_path)
    before = copy.deepcopy(doc)
    c = revision.candidate(doc, CORRECTED)
    rev = revision.apply(root, doc, c, ENG, why="Legs #2 to #4 float: every bracket hung on leg #1")
    assert rev["id"] == "REV-1" and (rev["icd_from"], rev["icd_to"]) == (1, 2)
    ic = doc["icd"]
    assert ic["version"] == 2 and ic["status"] == "approved" and len(ic["interfaces"]) == 8
    assert ic["history"][-1]["kind"] == "revised" and ic["history"][-1]["revision"] == "REV-1"
    assert ic["overrides"]["items"][_ids(doc)["Table top"]]["L"] == 1200.0  # frozen again at the new sizes
    # the three made parts are reopened, approved or integrated as they were, with a precise instruction
    for title in ("Table top", "Folding leg", "Leg hinge bracket"):
        t = _t(doc, title)
        assert t["column"] == "ready" and t["run"]["status"] == "queued" and t["run"]["next"] == "design"
        assert t["revisions"][-1]["revision"] == "REV-1" and t["revisions"][-1]["class"] == "redesign"
        assert t["comments"][-1]["text"].startswith("Program revision REV-1 (ICD v2) changes this part")
        assert t["icd_delta"] and t["fitted"] is False
    assert "Add these interface features" in _t(doc, "Folding leg")["comments"][-1]["text"]
    # the bought-out parts and the fastener kit stay done; the two levels holding a change and the final run again
    assert _t(doc, "Leg pivot bolt")["column"] == "integrated" and _t(doc, "Assemble Fasteners")["column"] == "integrated"
    for title in ("Assemble Top", "Assemble Legs", "Final assembly of TEST Project"):
        t = _t(doc, title)
        assert t["column"] == "backlog" and not t.get("paused") and t["run"]["status"] == "queued"
    assert rev["reset"] == ["TP-2", "TP-5", "TP-11"]
    assert sorted(x["key"] for x in rev["reopened"]) == ["TP-1", "TP-3", "TP-4"]
    evs = [e["type"] for e in store.events(root, doc["id"], limit=500)]
    assert "program.revised" in evs
    store.save(root, doc)
    # undo while nothing was rebuilt: the ICD, the plan and every ticket state are back
    assert revision.undoable(doc, "REV-1") is None
    revision.undo(root, doc, "REV-1", ENG)
    assert doc["icd"]["version"] == 1 and doc["icd"]["interfaces"] == before["icd"]["interfaces"]
    assert doc["skeleton"] == before["skeleton"] and doc["plan"]["subassemblies"] == before["plan"]["subassemblies"]
    assert [(t["key"], t["column"]) for t in doc["tickets"]] == [(t["key"], t["column"]) for t in before["tickets"]]
    assert doc["icd"]["history"][-1]["kind"] == "undone" and doc["revisions"][0]["status"] == "undone"
    # applied again, then a reopened part is rebuilt: the undo is refused
    rev2 = revision.apply(root, doc, revision.candidate(doc, CORRECTED), ENG, why="again")
    assert rev2["id"] == "REV-2"
    orchestrator._set_run(_t(doc, "Folding leg"), turns=int(_t(doc, "Folding leg")["run"].get("turns") or 0) + 1)
    assert revision.undoable(doc, "REV-2") == "TP-3 has been rebuilt for the revision"


# ============================================================================ a part added to a done program
BRACKET = {"name": "Bracket", "family": "machined", "complexity": 2, "qty": 1, "description": "Bracket, steel.",
           "envelope": [40, 30, 20], "mounts_on": "Base plate"}


def test_a_part_added_to_a_done_program(tmp_path: Path) -> None:
    root, doc = _plate(tmp_path)
    c = revision.candidate(doc, [{"op": "add", "sub": "Frame", "part": BRACKET}])
    assert c["ok"], c["why"]
    ids = _ids({"items": c["items"]})
    it = c["skeleton"]["items"]
    # hand: the row on the plate is cover 60, gap 12, bracket 40 = 112, centred: cover -56 + 30 = -26, bracket
    # -56 + 60 + 12 + 20 = 36
    assert it[ids["Cover"]]["copies"] == [[-26.0, 0.0, 3.0]] and it[ids["Bracket"]]["copies"] == [[36.0, 0.0, 10.0]]
    cover_if = next(f for f in c["interfaces"] if f["b"]["item"] == ids["Cover"] or f["a"]["item"] == ids["Cover"])
    # the cover's holes in its own frame: ±(30 - 11) = ±19, ±(20 - 11) = ±9, as before; in the plate's frame they
    # move to -26 ± 19 = -45 and -7
    assert sorted({p[0] for p in cover_if["data"]["positions"]}) == [-45.0, -7.0]
    assert _classes(c) == {"Base plate": "redesign", "Cover": "moved", "Frame bolt": "unchanged", "Bracket": "added"}
    assert _levels(c) == {"Frame": "rerun", "Final assembly": "rerun"}
    rev = revision.apply(root, doc, c, ENG, why="The engineer wants a bracket on the plate")
    assert doc["status"] == "active"
    new = _t(doc, "Bracket")
    assert new["column"] == "ready" and new["kind"] == "part" and new["revisions"][0]["class"] == "added"
    assert new["id"] in _t(doc, "Assemble Frame")["depends_on"]
    assert _t(doc, "Base plate")["column"] == "ready"  # redesigned: a new joint
    cover = _t(doc, "Cover")
    assert cover["column"] == "approved" and cover["revisions"][-1]["class"] == "moved"  # kept, re-placed
    assert _t(doc, "Assemble Frame")["column"] == "backlog" and rev["added"] == [new["id"]]


def test_a_part_removed(tmp_path: Path) -> None:
    root, doc = _plate(tmp_path, extra=[BRACKET])
    ids = _ids(doc)
    assert doc["skeleton"]["items"][ids["Cover"]]["copies"] == [[-26.0, 0.0, 3.0]]
    c = revision.candidate(doc, [{"op": "remove", "part": "Bracket"}])
    assert c["ok"], c["why"]
    # hand: alone on the plate, the cover is centred (X 0); its holes stay ±19 / ±9 in its own frame
    assert c["skeleton"]["items"][ids["Cover"]]["copies"] == [[0.0, 0.0, 3.0]]
    assert _classes(c) == {"Base plate": "redesign", "Cover": "moved", "Bracket": "removed", "Frame bolt": "unchanged"}
    br = _t(doc, "Bracket")
    revision.apply(root, doc, c, ENG, why="No bracket after all")
    assert all(t["id"] != br["id"] for t in doc["tickets"])
    assert all(br["id"] not in (t.get("depends_on") or []) for t in doc["tickets"])
    gone = doc["retired_tickets"][0]
    assert gone["key"] == br["key"] and gone["retired"]["revision"] == "REV-1"  # history kept
    assert gone["comments"] == br["comments"]


def test_a_size_change_reopens_exactly_the_parts_whose_features_change(tmp_path: Path) -> None:
    root, doc = _plate(tmp_path, extra=[BRACKET])
    c = revision.candidate(doc, [{"op": "size", "part": "Cover", "envelope": [60, 40, 8]}])
    assert c["ok"], c["why"]
    # hand: a thicker cover keeps its footprint, so its holes and the plate's stay where they are; only the cover's
    # own mounting face moves (Z -3 → -4 in its frame) and its envelope: the cover alone is redesigned
    assert _classes(c) == {"Base plate": "unchanged", "Cover": "redesign", "Bracket": "unchanged",
                           "Frame bolt": "unchanged"}
    row = next(r for r in c["impact"]["parts"] if r["name"] == "Cover")
    assert row["why"] == "envelope 60 × 40 × 6 → 60 × 40 × 8 mm; interface features: 1 removed, 1 added"
    assert row["remove"] == ["mounting face (bottom) at Z -3"] and row["add"] == ["mounting face (bottom) at Z -4"]
    revision.apply(root, doc, c, ENG, why="A thicker cover")
    reopened = [t["title"] for t in doc["tickets"] if t["kind"] == "part" and t["column"] == "ready"]
    assert reopened == ["Cover"]
    assert _t(doc, "Base plate")["column"] == "approved" and _t(doc, "Bracket")["column"] == "approved"


# ============================================================================ Archie: proposes, asks, applies, undoes
def test_archie_proposes_the_revision_asks_with_the_impact_list_and_applies_it(tmp_path: Path) -> None:
    root, doc = _table(tmp_path)
    pid = doc["id"]

    async def go() -> None:
        supervisor.notify(store.load(root, pid), "blocked", _t(doc, "Assemble Legs"), FLOATING)
        res = await supervisor.run_pass(root, pid, None, force=True)
        assert res["cause"] == "plan" and len(res["asked"]) == 1 and not res["done"]
        d = store.load(root, pid)
        e = next(x for x in d["supervisor"]["log"] if x["id"] == res["asked"][0])
        assert e["tool"] == "revise_program" and e["class"] == "major"
        assert "it reopens parts already worked on" in e["class_why"]
        assert e["title"].startswith("Revise the program to ICD v2 (Table top is the base;")
        msg = archie_chat.history(root, pid)[-1]
        q = msg["questions"][0]
        assert q["options"][0]["label"] == "Yes, revise the program"
        assert any(x.startswith("Redesigned: Table top") for x in q["impact"]["lines"])
        assert "Assemblies kept: Fasteners" in q["impact"]["lines"]
        assert "new program" not in msg["text"].lower()
        out = await supervisor.decide(root, pid, e["id"], "approve", ENG)
        assert out["status"] == "applied" and out["outcome"].startswith("REV-1: ICD v1 → v2.")
        d = store.load(root, pid)
        assert d["icd"]["version"] == 2 and revision.loose_copies(d["skeleton"], d["icd"]["interfaces"]) == []
        assert d["orchestrator"]["state"] == "running"
        assert supervisor.view(d)["log"][0]["undoable"] is True
        supervisor.undo(root, pid, e["id"], ENG)
        d = store.load(root, pid)
        assert d["icd"]["version"] == 1 and d["revisions"][0]["status"] == "undone"

    asyncio.run(go())


def test_adding_or_removing_parts_after_work_started_is_a_revision_not_a_new_program(tmp_path: Path) -> None:
    _root, doc = _plate(tmp_path, extra=[BRACKET])
    n, why = supervisor.check(doc, {"tool": "remove_part", "part": "Bracket", "why": "Not needed"})
    assert n is not None, why
    assert n["tool"] == "revise_program" and n["changes"] == [{"op": "remove", "part": "Bracket"}]
    assert supervisor.classify(doc, n) == ("major", "it adds or removes parts and it reopens parts already worked on")
    # laying it out again with the same layout changes nothing: refused, not asked
    ok, why = supervisor.check(doc, {"tool": "revise_program", "why": "again", "changes": [{"op": "relayout"}]})
    assert ok is None and why == "The revised layout is the same as the one the program has"
    # re-placing only is minor once the engineer asked for the plan change; Archie's own proposal is asked
    rp = {"tool": "revise_program", "impact": {"replace_only": True, "major_why": []}}
    assert supervisor.classify(doc, {**rp, "engineer_asked": True}) == (
        "minor", "it only re-places parts, and you approved the plan change")
    assert supervisor.classify(doc, rp)[0] == "major"
    # the instructions never send the engineer to a new program (only the rule that forbids it names one)
    for txt in (archie_chat.CHAT_INSTRUCTIONS.replace("Never tell the manager to start a new program", ""),
                supervisor.SUPERVISOR_INSTRUCTIONS.replace("Never tell the engineer to start a new program", "")):
        assert "new program" not in txt


def test_the_chat_reader_offers_the_revision_on_a_placement_block(tmp_path: Path) -> None:
    root, doc = _table(tmp_path)
    text, acts, _kind = archie_chat.offline_reply(doc, "Redo what is needed.", root)
    assert acts and acts[0]["type"] == "revise_program"
    assert "new program" not in text.lower() and "I can revise the program (ICD v2)" in text
    n = archie_chat.normalise(doc, acts[0])
    assert n is not None and n["changes"][0] == {"op": "base", "part": "Table top"}
    assert archie_chat.describe(doc, n).startswith("Revise the program to ICD v2: Table top is the base")


def test_a_revision_waits_for_a_step_in_progress_and_refuses_after_release(tmp_path: Path) -> None:
    root, doc = _table(tmp_path)
    c = revision.candidate(doc, CORRECTED)
    orchestrator._set_run(_t(doc, "Folding leg"), status="designing")
    with pytest.raises(Exception, match="TP-3 is in the middle of a step"):
        revision.apply(root, doc, c, ENG, why="x")
    orchestrator._set_run(_t(doc, "Folding leg"), status="done")
    doc["releases"] = [{"rev": "A"}]
    with pytest.raises(Exception, match="change notice"):
        revision.apply(root, doc, c, ENG, why="x")


def test_a_sub_assembly_whose_copies_are_joined_through_another_level_is_not_floating(tmp_path: Path) -> None:
    """After the revision each bracket + leg pair stands on the table top, which is in the Top sub-assembly: in the
    Legs sub-assembly alone the four pairs touch nothing of each other. That is assembled at the final assembly, not
    floating; the founder's original leg #2 (no interface at all) still stops."""
    from aicad.office import visual_office

    root, doc = _table(tmp_path)
    ids = _ids(doc)
    old = copy.deepcopy(doc)
    revision.apply(root, doc, revision.candidate(doc, CORRECTED), ENG, why="x")

    def level(d: dict[str, Any]) -> dict[str, Any]:
        return {"instances": [{"id": f"{n}-{c}", "office": {"item": ids[n], "copy": c}}
                              for n in ("Folding leg", "Leg hinge bracket") for c in range(4)]}

    groups = [{"code": "floating", "severity": "block", "items": [f"Folding leg-{c}", f"Leg hinge bracket-{c}"],
               "text": f"Folding leg #{c + 1} touches nothing"} for c in (1, 2, 3)]
    after = visual_office.known_loose(doc, level(doc), copy.deepcopy(groups))
    assert [f["severity"] for f in after] == ["note"] * 3
    assert after[0]["text"].endswith("It is joined to Table top of another sub-assembly: the final assembly checks it "
                                     "there.")
    before = visual_office.known_loose(old, level(old), [{"code": "floating", "severity": "block",
                                                          "items": ["Folding leg-1"], "text": FLOATING}])
    assert before[0]["severity"] == "block"


# Archie's live reply on the TEST copy (2026-11-20, Opus): the right structure and his own sizes, but no size for the
# brackets, so on today's layout the four legs would all go on bracket #1
LIVE_OPS = [{"op": "base", "part": "Table top"}, {"op": "size", "part": "Table top", "envelope": [800, 600, 20]},
            {"op": "mount", "part": "Leg hinge bracket", "on": "Table top"},
            {"op": "mount", "part": "Folding leg", "on": "Leg hinge bracket"},
            {"op": "size", "part": "Folding leg", "envelope": [90, 20, 568]}]


def test_archies_live_revision_is_completed_so_copy_n_carries_copy_n(tmp_path: Path) -> None:
    _root, doc = _table(tmp_path)
    ids = _ids(doc)
    c = revision.candidate(doc, LIVE_OPS)
    assert c["ok"], c["why"]
    assert c["ops"][-1] == {"op": "size", "part": "Leg hinge bracket", "envelope": [100.0, 70.0, 16.0]}
    pairs = {(f["a"]["copy"], f["b"]["copy"]) for f in c["interfaces"]
             if f["a"]["item"] == ids["Leg hinge bracket"] and f["b"]["item"] == ids["Folding leg"]}
    assert pairs == {(0, 0), (1, 1), (2, 2), (3, 3)}
    assert c["skeleton"]["items"][ids["Table top"]]["size"] == [800.0, 600.0, 20.0]


@pytest.mark.parametrize("actions", [[], [{"tool": "revise_program", "changes": [{"op": "mount", "part": "Folding leg",
                                                                                   "on": "Table top"}]}]])
def test_a_live_reply_that_only_describes_the_fix_still_ends_in_a_one_click_question(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, actions: list[dict[str, Any]]) -> None:
    from aicad import llm
    from aicad.llm.stub import StubProvider

    monkeypatch.setenv("FW_OFFICE_SUPERVISOR_AI", "1")
    root, doc = _table(tmp_path)
    pid = doc["id"]
    reply = {"cause": "plan", "diagnosis": "Everything hangs off leg #1, so the other three legs float.",
             "evidence": ["IF-02 to IF-05 all name Folding leg #1"], "say": "I propose revising to ICD v2.",
             "actions": actions}
    text = "The layout is upside down.\n```fw-supervisor\n" + __import__("json").dumps(reply) + "\n```"

    async def go() -> None:
        supervisor.notify(store.load(root, pid), "blocked", _t(doc, "Assemble Legs"), FLOATING)
        with llm.use_provider(StubProvider(responder=lambda req: text), roles=("supervisor",)):
            res = await supervisor.run_pass(root, pid, None, force=True)
        assert res["mode"] == "ai" and len(res["asked"]) == 1
        e = next(x for x in store.load(root, pid)["supervisor"]["log"] if x["id"] == res["asked"][0])
        assert e["tool"] == "revise_program" and e["action"]["impact"]["placement"]["after"] == []

    asyncio.run(go())
