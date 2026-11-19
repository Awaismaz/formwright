"""Design Office honesty and scheduling fixes from the live gear-pair run (2026-11-19, ``docs/reports/office-polish.md``):
the ICD gate's "keep as separate parts" decision, Archie's words following the verdict, human part names, one clash
count, no "retry 0 parts", plain words about parts the layout never seats, and a budget default no larger than the
wallet. Pure tests (no CAD, no model calls); the orchestrator paths are in ``test_office_orchestrator.py``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aicad.assembly import visual
from aicad.assembly.service import human_names
from aicad.office import (
    archie_chat,
    icd,
    interfaces,
    planner,
    program_assembly,
    service,
    store,
    visual_office,
)

BRIEF = "Two shafts made on their own, no housing"
KIT = {"subassemblies": [{"name": "Shafts", "parts": [
    {"name": "Input shaft", "family": "turned", "complexity": 1, "qty": 1, "description": "Shaft Ø25 x 90 mm."},
    {"name": "Output shaft", "family": "turned", "complexity": 1, "qty": 1, "description": "Shaft Ø32 x 125 mm."}]}]}
ENG = {"name": "Eng"}


def _program(tmp_path: Path, plan: dict[str, Any] = KIT) -> tuple[Path, dict[str, Any]]:
    root = store.org_root(tmp_path, "org1")
    doc = service.new_program("Kit", BRIEF, "org1", "u1", 2, 3000, "standard")
    service.set_plan(root, doc, planner.normalise_plan(plan, "standard"), ENG)
    service.approve_plan(root, doc, None, ENG)
    store.save(root, doc)
    return root, doc


# ============================================================================ 1. the ICD gate: keep as separate parts
def test_unconnected_parts_block_by_default_and_a_recorded_decision_releases_them(tmp_path: Path) -> None:
    root, doc = _program(tmp_path)
    ids = {it["name"]: i for i, it in doc["skeleton"]["items"].items()}
    codes = [(x["code"], x["severity"]) for x in icd.issues(doc["skeleton"], doc["icd"]["interfaces"])]
    assert ("no_interface", "error") in codes and doc["icd"]["problems"]  # PD-85: blocks by default
    assert sorted(interfaces.unconnected(doc)) == sorted(ids.values())
    # one part: the other still blocks, approval is refused
    changed = interfaces.keep_separate(root, doc, [ids["Input shaft"]], True, ENG)
    assert changed == [ids["Input shaft"]]
    assert any("Output shaft" in p for p in doc["icd"]["problems"])
    assert not any("Input shaft" in p for p in doc["icd"]["problems"])
    try:
        interfaces.approve(root, doc, ENG)
        raise AssertionError("approved with a blocking problem")
    except Exception as e:  # noqa: BLE001
        assert "Output shaft" in str(e)
    # all the rest at once (items None): no problem left, both are acknowledged warnings, recorded in the history
    interfaces.keep_separate(root, doc, None, True, ENG)
    assert doc["icd"]["problems"] == []
    warn = icd.warnings(doc["skeleton"], doc["icd"]["interfaces"])
    assert len(warn) == 2 and all("kept as a separate part (your decision" in w for w in warn)
    hist = [h for h in doc["icd"]["history"] if h["kind"] == "separate"]
    assert len(hist) == 2 and hist[0]["by"] == "Eng" and "Input shaft" in hist[0]["text"]
    v = interfaces.view(doc)
    assert {x["name"] for x in v["separate"]} == {"Input shaft", "Output shaft"} and v["separate"][0]["by"] == "Eng"
    # undo: blocks again
    interfaces.keep_separate(root, doc, [ids["Output shaft"]], False, ENG)
    assert any("Output shaft" in p for p in doc["icd"]["problems"])
    assert doc["icd"]["history"][-1]["kind"] == "connect"
    interfaces.keep_separate(root, doc, None, True, ENG)
    interfaces.approve(root, doc, ENG)
    assert doc["icd"]["status"] == "approved" and doc["icd"]["overrides"]["separate"]  # survives the freeze
    sk, _ifs = icd.build(icd.parts_from(doc), doc["brief"], doc["icd"]["overrides"])
    assert sk["separate"] == sorted(ids.values())


def test_a_connected_part_cannot_be_kept_separate(tmp_path: Path) -> None:
    from test_assembly_visual import GEAR_PAIR

    root, doc = _program(tmp_path, GEAR_PAIR)
    some = next(iter(doc["skeleton"]["items"]))
    try:
        interfaces.keep_separate(root, doc, [some], True, ENG)
        raise AssertionError("kept a connected part separate")
    except Exception as e:  # noqa: BLE001
        assert "connected to the program by an interface" in str(e)


def test_archie_stops_raising_kept_parts_and_offers_the_decision(tmp_path: Path) -> None:
    root, doc = _program(tmp_path)
    q = visual.quick_skeleton(doc["skeleton"], doc["icd"]["interfaces"])
    text, acts = visual_office.layout_message(doc, q, None)
    assert "no interface connects them" in text and "keep them separate" in text
    keep = next(a for a in acts if a["type"] == "keep_separate")
    clean = archie_chat.normalise(doc, keep)
    assert clean is not None and set(clean["parts"]) == {"Input shaft", "Output shaft"}
    assert archie_chat.describe(doc, clean).startswith("Keep Input shaft and Output shaft as separate parts")
    interfaces.keep_separate(root, doc, None, True, ENG)
    q = visual.quick_skeleton(doc["skeleton"], doc["icd"]["interfaces"])
    assert q["findings"] == []  # neither a row nor an unconnected part: as the engineer decided
    text, acts = visual_office.layout_message(doc, q, None)
    assert "the placement checks pass" in text and acts == []
    assert archie_chat.normalise(doc, keep) is None  # nothing left to keep separate
    # a level whose parts touch nothing only because they were kept separate is not stopped
    adoc = {"instances": [{"id": "a1", "office": {"item": i}} for i in doc["skeleton"]["items"]]}
    row = [{"code": "row", "severity": "block", "items": ["a1", "a2"], "text": "2 of 2 parts touch nothing."}]
    adoc["instances"][1]["id"] = "a2"
    assert visual_office.known_loose(doc, adoc, row) == []


# ============================================================================ 2a. the heading follows the verdict
def _verdict(overall: str, status: str = "ok") -> dict[str, Any]:
    return {"overall": overall, "relations": [{"id": "R1", "text": "Pinion meshes with Gear", "status": status,
                                               "reason": ""}],
            "problems": [{"kind": "other", "items": [], "labels": [], "text": "an unlisted blue spike"}],
            "summary": "Hard to tell.", "readable": True}


def test_layout_heading_follows_the_verdict(tmp_path: Path) -> None:
    from test_assembly_visual import GEAR_PAIR

    _root, doc = _program(tmp_path, GEAR_PAIR)
    q = visual.quick_skeleton(doc["skeleton"], doc["icd"]["interfaces"])
    assert q["findings"] == []
    text, _ = visual_office.layout_message(doc, q, {"verdict": _verdict("unsure")})
    assert "It doesn't look right" not in text  # live run: said on an "unsure" verdict
    assert "I can't tell from the picture whether it is assembled as intended" in text
    assert "Nothing measured is wrong" in text
    text, _ = visual_office.layout_message(doc, q, {"verdict": _verdict("looks_wrong", "wrong")})
    assert "It doesn't look right:" in text


# ============================================================================ 2b. human names, never "<1>" or "Item 3"
def test_part_names_are_human() -> None:
    doc = {"instances": [{"id": "a", "name": "Gear shaft"}, {"id": "b", "name": "Bearing"},
                         {"id": "c", "name": "Bearing"}]}
    assert human_names(doc) == {"a": "Gear shaft", "b": "Bearing #1", "c": "Bearing #2"}
    assert service.plain_names("Gear shaft<1> and Bearing<2> overlap") == "Gear shaft and Bearing #2 overlap"
    nums = {3: "Pinion key", 1: "Gear"}
    assert visual.named("Item 3 lies on the floor beside Gear (1).", nums) == \
        "Pinion key lies on the floor beside Gear."
    assert visual.named("part 9 is fine at 20 mm", nums) == "part 9 is fine at 20 mm"  # unknown tag: untouched
    reply = ('```json\n{"overall": "looks_wrong", "relations": [], "problems": [{"kind": "floating", "items": [3], '
             '"text": "Item 3 lies apart"}], "summary": "Key (3) lies on the floor."}\n```')
    v = visual.parse_verdict(reply, [], [{"n": 3, "label": "Pinion key"}])
    assert v["problems"][0]["text"] == "Pinion key lies apart" and v["summary"] == "Key lies on the floor."
    m = archie_chat.archie_message("Gear shaft<1> clashes with Bearing<2>.", [], kind="look")
    assert m["text"] == "Gear shaft clashes with Bearing #2."


def test_agent_comments_and_card_lines_use_plain_names(tmp_path: Path) -> None:
    root, doc = _program(tmp_path)
    t = doc["tickets"][0]
    c = service.comment(root, doc, t["id"], "Clash: Gear shaft<1> ↔ Bearing<2>", service.agent_actor("fitz"))
    assert c["text"] == "Clash: Gear shaft ↔ Bearing #2"
    c = service.comment(root, doc, t["id"], "Keep <1> as typed", ENG | {"kind": "user"})
    assert c["text"] == "Keep <1> as typed"  # the engineer's own words are never rewritten
    from aicad.office import orchestrator

    assert orchestrator._set_run(t, line="Stopped: Gear shaft<1>")["line"] == "Stopped: Gear shaft"


# ============================================================================ 2c. one clash count
def test_one_clash_count() -> None:
    two = [{"a": "x", "b": "y", "volume_mm3": 2.2}, {"a": "x", "b": "z", "volume_mm3": 2.2}]
    assert program_assembly.clash_status({"clashes": two, "check": {"status": "running"}})["count"] is None
    done = program_assembly.clash_status({"clashes": two, "check": {"status": "done", "scope": "program", "count": 2}})
    assert done["count"] == 2 and done["text"].startswith("2 clashes in the whole-program check")
    assert program_assembly.clash_status({"clashes": [], "check": {"status": "failed"}})["count"] is None
    assert program_assembly.clash_status({"clashes": []})["text"] == "no clash check yet"
    # the summary line never carries its own count
    assert "clash" not in program_assembly.summarize({"a": {"kind": "real"}}, {"mates": [], "groups": []}, two)


# ============================================================================ 2d. no "Retry the 0 blocked parts"
def test_retry_label_after_apply_and_stale_proposals(tmp_path: Path) -> None:
    _root, doc = _program(tmp_path)
    doc["status"] = "active"
    t = doc["tickets"][0]
    t["run"] = {"status": "blocked"}
    msgs = [{"id": "m1", "role": "archie", "actions": [{"id": "a1", "type": "retry_blocked", "status": "proposed"}]}]
    a = archie_chat.with_labels(doc, msgs)[0]["actions"][0]
    assert a["label"].startswith("Retry the 1 blocked part ") and not a.get("stale")
    t["run"] = {"status": "queued"}  # applied: nothing is blocked any more
    msgs[0]["actions"][0].update(status="applied", count=1)
    a = archie_chat.with_labels(doc, msgs)[0]["actions"][0]
    assert a["label"].startswith("Retried 1 blocked part ")
    msgs[0]["actions"][0] = {"id": "a1", "type": "retry_blocked", "status": "proposed"}
    a = archie_chat.with_labels(doc, msgs)[0]["actions"][0]
    assert a["stale"] and "0 blocked" not in a["label"] and "nothing to retry" in a["label"]


# ============================================================================ 2e. parts the layout never seats
def test_unplaced_parts_are_said_plainly_never_reassured() -> None:
    t = {"key": "GP-3", "title": "Assemble Pinion shaft", "item_id": "s1"}
    adoc = {"instances": [{"id": "k", "name": "Pinion key", "office": {"bin": True}},
                          {"id": "c1", "name": "Circlip", "office": {"bin": True}},
                          {"id": "c2", "name": "Circlip", "office": {"bin": True}},
                          {"id": "s", "name": "Pinion shaft", "office": {}}]}
    names = visual_office.unplaced_names(adoc, {"k", "c1", "c2"})
    assert names == ["Pinion key", "2 × Circlip"]
    line = "Visual check (advisory): it looks wrong. Pinion key lies on the floor."
    text, _ = visual_office.level_message(t, {"unconfirmed": True, "line": line, "unplaced": names, "measured": False})
    assert "found nothing to confirm it" not in text
    assert "Pinion key and 2 × Circlip are not placed" in text and "parts bin" in text
    text, _ = visual_office.level_message(t, {"unconfirmed": True, "line": line, "unplaced": [], "measured": True})
    assert "can't show a part that is loose" in text and "not a confirmation" in text
    text, _ = visual_office.level_message(t, {"line": "", "unplaced": ["Pinion key"]})
    assert text.startswith("Pinion shaft is integrated.") and "Pinion key is not placed" in text


def test_stop_advice_follows_what_confirmed_it() -> None:
    t = {"key": "GP-7", "title": "Assemble Gear shaft", "item_id": "s2"}
    vline = "Visual check (advisory): it looks wrong."
    text, _ = visual_office.level_message(t, {"stop": True, "reason": f"{vline} Measured: A and B overlap by 3.0 mm³.",
                                              "line": vline, "quick": []})
    assert "comes from the layout" not in text and "measured clash" in text
    text, _ = visual_office.level_message(t, {"stop": True, "reason": "x", "line": "",
                                              "quick": [{"severity": "block", "text": "2 of 2 parts touch nothing."}]})
    assert "comes from the layout or the plan" in text


# ============================================================================ 3. budget sanity
def test_default_budget_is_at_most_the_wallet() -> None:
    assert service.default_budget(1000) == 1000  # a trial wallet: not 3,000
    assert service.default_budget(50_000) == service.DEFAULT_BUDGET_TOKENS
    assert service.default_budget(-20) == 0
    assert service.default_budget(10, unlimited=True) == service.DEFAULT_BUDGET_TOKENS


def test_a_budget_stop_is_told_with_its_own_advice() -> None:
    doc = {"status": "active"}
    t = {"key": "GP-5", "title": "Gear shaft", "item_id": "i1"}
    text, acts = visual_office.failure_message(doc, t, "Chuck stopped at its run budget (138 tokens) before finishing.")
    assert "carries on from where it stopped" in text and acts == [{"type": "retry_blocked"}]
