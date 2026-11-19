"""Archie supervises a running program (WORKLIST 49, ``docs/reports/archie-supervisor.md``).

The scenarios are the real ones from 2026-11-19/20: a measurement loop the no-progress guard stopped (the founder's
Gear Reducer: a tapped hole measured "through" while the ICD says blind, three rounds), a part the brief excluded
(Test 5's housing), a ticket held by a procedural round cap with only advisory notes left, and the undo of a rule
override. Archie's model turn goes through the provider layer with the stub provider and recorded replies; no CAD,
no paid model call. The gate code (Gage's review) runs for real on a fake platform boundary."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from aicad import llm
from aicad.llm.stub import StubProvider
from aicad.office import (
    archie_chat,
    deliverables,
    icd,
    interfaces,
    orchestrator,
    planner,
    service,
    store,
    supervisor,
)

ENG = {"kind": "user", "id": "u1", "name": "Eng"}
KIT = {"subassemblies": [{"name": "Shafts", "parts": [
    {"name": "Input shaft", "family": "turned", "complexity": 1, "qty": 1, "description": "Shaft Ø25 x 90 mm."},
    {"name": "Output shaft", "family": "turned", "complexity": 1, "qty": 1, "description": "Shaft Ø32 x 125 mm."}]}]}
FEATURE = "IF-1:tapped hole 1"
FINDING_ROW = {"feature": "tapped hole 1", "spec": "Ø6.8 ±0.05 at (-39.49, -25.51), blind (tapped)",
               "measured": "Ø6.800 at (-39.49, -25.51), through, the ICD says blind (tapped)", "ok": False}


@pytest.fixture(autouse=True)
def _on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FW_OFFICE_SUPERVISOR", "1")
    monkeypatch.delenv("FW_OFFICE_FAKE_AGENTS", raising=False)
    monkeypatch.setattr(supervisor, "DEBOUNCE_S", 0.0)
    monkeypatch.setattr(supervisor, "wallet_left", lambda org_id: 500)
    monkeypatch.setattr(supervisor, "charge", lambda *a, **k: None)
    supervisor._running.clear()
    supervisor._again.clear()
    supervisor._flags.clear()


class FakeEnv(orchestrator.Env):
    """The platform boundary for Gage's review: a part that builds and passes its gating checks, one interface
    feature that measures the same way whatever the designer does (the founder's tapped hole)."""

    def __init__(self) -> None:
        self.builds = 3
        self.conforms = False

    async def part_state(self, project_id: str) -> dict[str, Any]:
        return {"builds": self.builds, "ok": True, "checks": [], "bbox": [25, 25, 90], "params": {}, "source": "x"}

    async def conformance(self, doc: dict[str, Any], t: dict[str, Any]) -> dict[str, Any] | None:
        rows = [{**FINDING_ROW, "ok": self.conforms}]
        return {"version": doc["icd"]["version"], "ok": self.conforms, "frame": {}, "envelope": {"ok": True},
                "interfaces": [{"interface": "IF-1", "name": "Input shaft ↔ Output shaft", "rows": rows}]}

    async def review_ai(self, doc: dict[str, Any], t: dict[str, Any], state: dict[str, Any], budget: int | None,
                        previous: list[str] | None = None) -> dict[str, Any] | None:
        return None


def _program(tmp_path: Path, org: str = "org1", brief: str = "Two shafts made on their own, no housing",
             plan: dict[str, Any] = KIT) -> tuple[Path, dict[str, Any]]:
    root = store.org_root(tmp_path, org)
    doc = service.new_program("Kit", brief, org, "u1", 2, 1000, "standard")
    service.set_plan(root, doc, planner.normalise_plan(plan, "standard"), ENG)
    service.approve_plan(root, doc, None, ENG)
    interfaces.keep_separate(root, doc, None, True, ENG)
    interfaces.approve(root, doc, ENG)
    doc["orchestrator"] = {"state": "paused", "user_id": "u1"}
    for t in doc["tickets"]:
        if t["kind"] == "part":
            t["project_id"] = f"p-{t['id']}"
    store.save(root, doc)
    return root, doc


def _ticket(root: Path, pid: str, title: str) -> dict[str, Any]:
    doc = store.load(root, pid)
    assert doc is not None
    return next(t for t in doc["tickets"] if t["title"] == title)


def _set(root: Path, pid: str, title: str, **run: Any) -> None:
    with store.lock(pid):
        doc = store.load(root, pid)
        assert doc is not None
        t = next(x for x in doc["tickets"] if x["title"] == title)
        orchestrator._set_run(t, **run)
        store.save(root, doc)


def _reply(obj: dict[str, Any], prose: str = "Here is what I see.") -> str:
    return f"{prose}\n```fw-supervisor\n{json.dumps(obj)}\n```"


async def _review(root: Path, pid: str, env: FakeEnv, title: str) -> str | None:
    r = orchestrator.Runner(root, pid, env)
    return await r._review(_ticket(root, pid, title)["id"])


async def _stuck_by_no_progress(root: Path, pid: str, env: FakeEnv) -> None:
    """Gage's round 1 sends the part back; the designer rebuilds; round 2 measures the same: the guard stops it."""
    _set(root, pid, "Input shaft", status="reviewing", next="review")
    assert await _review(root, pid, env, "Input shaft") == "design"
    env.builds += 1
    _set(root, pid, "Input shaft", status="reviewing", next="review")
    assert await _review(root, pid, env, "Input shaft") is None


# ============================================================================ (a) the measurement loop
MEASUREMENT_REPLY = {
    "cause": "measurement",
    "diagnosis": "Input shaft was rebuilt and the tapped hole measured exactly the same: through, while the ICD "
                 "says blind. A redesign that doesn't move the measurement points at the measurement or the spec, "
                 "not at the part.",
    "evidence": ["IF-1 tapped hole 1 measured the same in rounds 1 and 2", "the latest build passes its gating checks"],
    "say": "I'd relax the conformance check for that one hole on Input shaft until its next rebuild, and record it "
           "as relaxed, not passed.",
    "actions": [{"tool": "relax_rule", "rule": "conformance", "ticket": "K-1", "feature": FEATURE,
                 "expiry": "rebuild", "why": "The redesign did not move the measurement; the hole is modelled as "
                 "specified, so the reading or the spec is at fault."}]}


def test_a_measurement_loop_is_diagnosed_asked_and_proceeds_relaxed(tmp_path: Path) -> None:
    root, doc = _program(tmp_path)
    pid = doc["id"]
    env = FakeEnv()
    key = _ticket(root, pid, "Input shaft")["key"]
    reply = {**MEASUREMENT_REPLY, "actions": [{**MEASUREMENT_REPLY["actions"][0], "ticket": key}]}
    stub = StubProvider(responder=lambda req: _reply(reply))

    async def go() -> None:
        await _stuck_by_no_progress(root, pid, env)
        t = _ticket(root, pid, "Input shaft")
        assert t["run"]["status"] == "blocked" and "came back exactly the same" in t["run"]["blocked"]
        assert [x["key"] for x in t["run"]["last_items"]] == [FEATURE]
        assert store.load(root, pid)["supervisor"]["pending"][-1]["kind"] == "blocked"  # the orchestrator told him
        with llm.use_provider(stub, roles=("supervisor",)):
            res = await supervisor.run_pass(root, pid, env)
        assert res["mode"] == "ai" and res["cause"] == "measurement" and len(res["asked"]) == 1 and not res["done"]
        # Archie read a compact view: the trigger, the measured finding, its feature key, the build facts
        req = stub.calls[0]
        assert req.role == "supervisor" and req.standalone_system and req.model == supervisor.MODEL
        assert "came back exactly the same" in req.prompt and FEATURE in req.prompt
        assert "latest build: passes its gating checks" in req.prompt and "measures geometry" in req.prompt
        d = store.load(root, pid)
        e = d["supervisor"]["log"][-1]
        assert e["tool"] == "relax_rule" and e["class"] == "major" and e["status"] == "asking"
        assert e["class_why"] == "it relaxes a check that measures geometry" and e["cause"] == "measurement"
        assert not d["supervisor"]["overrides"]  # nothing changed before the engineer says yes
        assert _ticket(root, pid, "Input shaft")["run"]["status"] == "blocked"
        msg = archie_chat.history(root, pid)[-1]
        # one message: his diagnosis replaces the generic "retry the blocked part" note (no two different proposals)
        assert [m["kind"] for m in archie_chat.history(root, pid)] == ["supervisor"]
        assert msg["kind"] == "supervisor" and msg["questions"][0]["action"] == e["id"]
        assert [o["id"] for o in msg["questions"][0]["options"]] == ["approve", "decline"]
        assert "needs your decision" in msg["text"] and "relaxed, not passed" in msg["text"]
        assert any("proposal" in x for x in archie_chat.needs_you(d))
        # the engineer says yes: the override is created and the ticket goes back to Gage
        x = await supervisor.decide(root, pid, e["id"], "approve", ENG, env)
        assert x["status"] == "applied" and x["decided"]["by"] == "Eng"
        d = store.load(root, pid)
        o = d["supervisor"]["overrides"][0]
        assert o["status"] == "active" and o["rule"] == "conformance" and o["feature"] == FEATURE
        assert o["approved_by"] == "Eng" and o["expiry"] == {"kind": "rebuild"} and o["builds"] == {t["id"]: 4}
        t = _ticket(root, pid, "Input shaft")
        assert t["run"]["status"] == "queued" and t["run"]["next"] == "review"
        assert archie_chat.history(root, pid)[-1]["questions"][0]["answered"] == "approve"
        # Gage reviews again: the relaxed feature no longer blocks, and the part is approved AS RELAXED
        assert await _review(root, pid, env, "Input shaft") is None
        t = _ticket(root, pid, "Input shaft")
        assert t["column"] == "approved" and "relaxed by Archie (not passed)" in t["run"]["line"]
        assert t["relaxed"][0]["feature"] == FEATURE and t["relaxed"][0]["reason"].startswith("The redesign")
        note = next(c["text"] for c in reversed(t["comments"]) if (c.get("by") or {}).get("code") == "gage")
        assert note.startswith("Approved with checks relaxed by Archie (not passed):")
        assert "0 of 1 interface feature measured on the part match" in note and "relaxed, not passed" in note
        assert "Relaxed by Archie, not passed:" in note
        # visible in the summary, the BOM and the release README; never as a pass
        d = store.load(root, pid)
        lines = supervisor.relaxed_summary(d)
        assert len(lines) == 1 and "relaxed by Archie, not passed" in lines[0]
        assert "Relaxed by me, not passed (1)" in archie_chat.status_report(root, d)
        b = deliverables.bom(d["tickets"], None)
        row = next(r for r in b["rows"] if r["key"] == t["key"])
        assert row["relaxed"] and "relaxed by Archie, not passed" in row["description"] and b["relaxed"]
        assert "Relaxed check" in deliverables.bom_csv(b)
        readme = deliverables.readme(d, {"rev": "A"}, [], [], b, None)
        assert "relaxed, NOT passed" in readme and t["title"] in readme
        # until the next rebuild only: after a rebuild the same feature blocks again and the override ends
        doc2 = store.load(root, pid)
        items = [{"rule": "conformance", "key": FEATURE, "text": "x"}]
        assert supervisor.split(doc2, t, items, 4)[1] and not supervisor.split(doc2, t, items, 5)[1]
        supervisor.consume(root, doc2, t, [], 5)
        assert doc2["supervisor"]["overrides"][0]["status"] == "expired"

    asyncio.run(go())


def test_a_the_rule_based_reading_finds_the_same_cause_without_ai(tmp_path: Path, monkeypatch: pytest.MonkeyPatch
                                                                    ) -> None:
    """No AI (simulated agents, no tokens, the hourly cap): the known pattern is read deterministically."""
    monkeypatch.setenv("FW_OFFICE_SUPERVISOR_AI", "0")
    root, doc = _program(tmp_path)
    pid = doc["id"]
    env = FakeEnv()

    async def go() -> None:
        await _stuck_by_no_progress(root, pid, env)
        res = await supervisor.run_pass(root, pid, env)
        assert res["mode"] == "rules" and res["cause"] == "measurement"
        e = store.load(root, pid)["supervisor"]["log"][-1]
        assert e["action"]["rule"] == "conformance" and e["action"]["feature"] == FEATURE
        assert e["status"] == "asking" and e["action"]["expiry"] == {"kind": "rebuild"}
        # nothing new: the next pass (a heartbeat) leaves it alone and makes no call
        again = await supervisor.run_pass(root, pid, env)
        assert again["ran"] is False

    asyncio.run(go())


# ============================================================================ (b) a part the brief excluded
def test_b_a_part_the_brief_excluded_is_proposed_for_removal_and_asked(tmp_path: Path) -> None:
    brief = "Build a spur gear mounted on a shaft and locked with a key. No housing, no bearings."
    plan = {"subassemblies": [{"name": "Keyed shaft", "parts": [
        {"name": "Stepped shaft", "family": "turned", "complexity": 2, "qty": 1, "description": "Ø20 seat."},
        {"name": "Spur gear", "family": "gear", "complexity": 2, "qty": 1, "description": "m2 x 30 teeth."},
        {"name": "Parallel key", "family": "machined", "complexity": 1, "qty": 1, "description": "6 x 6 x 18."},
        {"name": "Shaft support housing", "family": "machined", "complexity": 3, "qty": 1,
         "description": "Only to satisfy the shaft support rule."}]}]}
    root = store.org_root(tmp_path, "org1")
    doc = service.new_program("Test 5", brief, "org1", "u1", 2, 1000, "standard")
    service.set_plan(root, doc, planner.normalise_plan(plan, "standard"), ENG)  # the engineer's own plan: untouched
    store.save(root, doc)
    pid = doc["id"]
    trig = supervisor.detect(doc)
    assert [(x["kind"], x["part"]) for x in trig] == [("scope", "Shaft support housing")]
    reply = {"cause": "plan", "diagnosis": "The plan has a Shaft support housing, but the brief says no housing.",
             "evidence": ["brief: No housing"], "say": "I'd take the housing out of the plan.",
             "actions": [{"tool": "remove_part", "part": "Shaft support housing",
                          "why": "The brief rules a housing out; it was added only to satisfy a rule."}]}
    stub = StubProvider(responder=lambda req: _reply(reply))

    async def go() -> None:
        with llm.use_provider(stub, roles=("supervisor",)):
            res = await supervisor.run_pass(root, pid, None)
        assert res["cause"] == "plan" and len(res["asked"]) == 1
        e = store.load(root, pid)["supervisor"]["log"][-1]
        assert e["tool"] == "remove_part" and e["class"] == "major" and e["class_why"] == "it adds or removes a part"
        assert "Shaft support housing" in [p["name"] for _s, p in supervisor._plan_parts(store.load(root, pid))]
        assert archie_chat.history(root, pid)[-1]["questions"][0]["question"] == \
            "Remove Shaft support housing from the plan?"
        x = await supervisor.decide(root, pid, e["id"], "approve", ENG)
        assert x["status"] == "applied"
        d = store.load(root, pid)
        assert d["status"] == "plan_review"
        assert [p["name"] for _s, p in supervisor._plan_parts(d)] == ["Stepped shaft", "Spur gear", "Parallel key"]
        assert "Archie removed Shaft support housing" in d["plan"]["note"]
        assert supervisor.view(d)["log"][0]["undoable"] is True  # a plan edit not yet built
        supervisor.undo(root, pid, e["id"], ENG)
        d = store.load(root, pid)
        assert "Shaft support housing" in [p["name"] for _s, p in supervisor._plan_parts(d)]
        assert d["supervisor"]["log"][-1]["status"] == "undone"

    asyncio.run(go())


def test_b_declined_changes_nothing_and_a_stale_yes_lapses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FW_OFFICE_SUPERVISOR_AI", "0")
    brief = "Just a gear and a shaft. No housing."
    plan = {"subassemblies": [{"name": "Unit", "parts": [
        {"name": "Shaft", "family": "turned", "complexity": 1, "qty": 1, "description": "Ø20 x 80."},
        {"name": "Gear", "family": "gear", "complexity": 2, "qty": 1, "description": "m2 x 30."},
        {"name": "Housing", "family": "machined", "complexity": 3, "qty": 1, "description": "box."}]}]}
    root = store.org_root(tmp_path, "org1")
    doc = service.new_program("G", brief, "org1", "u1", 2, 1000, "standard")
    service.set_plan(root, doc, planner.normalise_plan(plan, "standard"), ENG)
    store.save(root, doc)
    pid = doc["id"]

    async def go() -> None:
        await supervisor.run_pass(root, pid, None)
        e = store.load(root, pid)["supervisor"]["log"][-1]
        assert e["tool"] == "remove_part" and e["action"]["part"] == "Housing"
        x = await supervisor.decide(root, pid, e["id"], "decline", ENG)
        assert x["status"] == "declined" and len(supervisor._plan_parts(store.load(root, pid))) == 3
        with pytest.raises(Exception, match="already answered"):
            await supervisor.decide(root, pid, e["id"], "approve", ENG)

    asyncio.run(go())


# ============================================================================ (c) a procedural round cap, advisory notes
def test_c_round_cap_with_only_advisory_notes_is_approved_by_archie_and_logged(tmp_path: Path,
                                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FW_OFFICE_SUPERVISOR_AI", "0")
    root, doc = _program(tmp_path)
    pid = doc["id"]
    env = FakeEnv()
    with store.lock(pid):
        d = store.load(root, pid)
        t = next(x for x in d["tickets"] if x["title"] == "Output shaft")
        orchestrator._set_run(t, status="review", next="review", review_round=3, last_findings=None,
                              ai_findings=["Name the chamfer at the shoulder", "Add a centre hole note"])
        r = orchestrator.Runner.__new__(orchestrator.Runner)
        r.root, r.pid = root, pid
        r._fail(d, t["id"], "Gage sent Output shaft back 3 times; the review rounds are used up.")
        store.save(root, d)

    async def go() -> None:
        res = await supervisor.run_pass(root, pid, env)
        assert res["cause"] == "rule" and len(res["done"]) == 1 and not res["asked"]
        d = store.load(root, pid)
        e = d["supervisor"]["log"][-1]
        assert e["tool"] == "approve_with_notes" and e["class"] == "minor" and e["status"] == "applied"
        assert e["class_why"] == "every measurable check passes; only advisory notes remain"
        t = _ticket(root, pid, "Output shaft")
        assert t["column"] == "approved" and t["run"]["status"] in ("done", "queued")  # queued: Fitz swaps it in
        assert t["review_notes"] == ["Name the chamfer at the shoulder", "Add a centre hole note"]
        assert t["run"]["line"].startswith("Approved by Archie with 2 open review notes")
        last = archie_chat.history(root, pid)[-1]
        assert last["kind"] == "supervisor" and "Done: Approve" in last["text"] and not last.get("questions")
        v = supervisor.view(d)["log"][0]
        assert v["status"] == "applied" and v["undoable"] is False and "approval stays done" in v["undo_why"]
        assert "action" not in v and "undo" not in v  # internals stay on the server

    asyncio.run(go())


def test_c_archie_never_approves_a_part_with_a_measurable_failure(tmp_path: Path) -> None:
    _root, doc = _program(tmp_path)
    t = next(x for x in doc["tickets"] if x["title"] == "Output shaft")
    orchestrator._set_run(t, status="blocked", last_findings=["IF-1: bore Ø20 measured Ø21."])
    facts = {t["id"]: {"builds": 2, "ok": True}}
    norm, why = supervisor.check(doc, {"tool": "approve_with_notes", "ticket": t["key"]}, facts)
    assert norm is None and "a measurable check still fails" in why
    orchestrator._set_run(t, last_findings=None)
    assert supervisor.check(doc, {"tool": "approve_with_notes", "ticket": t["key"]}, {t["id"]: {"builds": 2,
                                                                                                "ok": False}})[0] is None
    assert supervisor.check(doc, {"tool": "approve_with_notes", "ticket": t["key"]}, facts)[0] is not None


# ============================================================================ (d) undo of a rule override
def test_d_undo_of_a_rule_override_makes_the_gate_block_again(tmp_path: Path) -> None:
    root, doc = _program(tmp_path)
    pid = doc["id"]
    env = FakeEnv()
    key = _ticket(root, pid, "Input shaft")["key"]
    reply = {**MEASUREMENT_REPLY, "actions": [{**MEASUREMENT_REPLY["actions"][0], "ticket": key}]}

    async def go() -> None:
        await _stuck_by_no_progress(root, pid, env)
        with llm.use_provider(StubProvider(responder=lambda req: _reply(reply)), roles=("supervisor",)):
            await supervisor.run_pass(root, pid, env)
        e = store.load(root, pid)["supervisor"]["log"][-1]
        await supervisor.decide(root, pid, e["id"], "approve", ENG, env)
        assert await _review(root, pid, env, "Input shaft") is None
        assert _ticket(root, pid, "Input shaft")["column"] == "approved"
        v = supervisor.view(store.load(root, pid))
        assert v["log"][0]["undoable"] is True and v["overrides"][0]["status"] == "active"
        assert v["overrides"][0]["measures"] is True and v["overrides"][0]["scope_text"].endswith("Input shaft")
        u = supervisor.undo(root, pid, e["id"], ENG)
        assert u["status"] == "undone" and "went back to Gage" in u["undone"]["outcome"]
        d = store.load(root, pid)
        assert d["supervisor"]["overrides"][0]["status"] == "undone"
        t = _ticket(root, pid, "Input shaft")
        assert not t.get("relaxed") and t["column"] == "in_review" and t["run"]["next"] == "review"
        # the gate measures the hole again and blocks the part: sent back, not approved
        assert await _review(root, pid, env, "Input shaft") == "design"
        t = _ticket(root, pid, "Input shaft")
        assert t["column"] == "changes_requested" and "tapped hole 1" in t["run"]["line"]
        assert supervisor.relaxed_summary(store.load(root, pid)) == []
        with pytest.raises(Exception, match="can't be undone"):
            supervisor.undo(root, pid, e["id"], ENG)

    asyncio.run(go())


# ============================================================================ the deterministic split and the limits
def test_minor_and_major_are_decided_by_code() -> None:
    doc = {"brief": "A gearbox", "status": "active", "tickets": []}
    c = supervisor.classify
    for tool in ("retry", "pause", "reassign", "send_back", "approve_with_notes"):
        assert c(doc, {"tool": tool})[0] == "minor"
    assert c(doc, {"tool": "relax_rule", "rule": "review_rounds"})[0] == "minor"   # measures nothing
    assert c(doc, {"tool": "relax_rule", "rule": "no_progress"})[0] == "minor"
    for rule in ("conformance", "envelope", "clash", "brief_size"):
        assert c(doc, {"tool": "relax_rule", "rule": rule}) == ("major", "it relaxes a check that measures geometry")
    assert c(doc, {"tool": "remove_part"})[0] == c(doc, {"tool": "add_part"})[0] == "major"
    assert c(doc, {"tool": "budget", "tokens": 900, "before": 500}) == ("major", "it raises the budget")
    assert c(doc, {"tool": "change_interface", "icd_status": "approved"}) == ("major", "it changes an approved interface")
    assert c(doc, {"tool": "keep_separate"})[0] == "major"
    assert c({**doc, "brief": "A kit of two shafts made on their own"}, {"tool": "keep_separate"})[0] == "minor"


def test_gating_checks_are_never_relaxed_and_measured_checks_stay_scoped(tmp_path: Path) -> None:
    _root, doc = _program(tmp_path)
    t = next(x for x in doc["tickets"] if x["title"] == "Input shaft")
    n, why = supervisor.check(doc, {"tool": "relax_rule", "rule": "CHK-02", "ticket": t["key"], "why": "x"})
    assert n is None and "never relaxed" in why
    n, why = supervisor.check(doc, {"tool": "relax_rule", "rule": "conformance", "scope": "program", "why": "x"})
    assert n is None and "one part or one interface" in why
    n, why = supervisor.check(doc, {"tool": "relax_rule", "rule": "conformance", "ticket": t["key"]})
    assert n is None and "reason" in why
    n, _ = supervisor.check(doc, {"tool": "relax_rule", "rule": "review_rounds", "scope": "program", "why": "x"})
    assert n is not None and n["expiry"] == {"kind": "rounds", "n": 2, "left": 2}
    # a gating finding is never split off as relaxed, even under a program-wide override
    doc["supervisor"] = {"overrides": [{"id": "RO-1", "rule": "conformance", "scope": {"kind": "program"},
                                        "status": "active", "reason": "r", "expiry": {"kind": "rebuild"}}]}
    keep, relaxed = supervisor.split(doc, t, [{"rule": "gate", "key": None, "text": "Gating check CHK-02 fails."}])
    assert keep == ["Gating check CHK-02 fails."] and relaxed == []


def test_budget_is_never_raised_past_the_wallet(tmp_path: Path) -> None:
    _root, doc = _program(tmp_path)
    doc["tickets"][0]["tokens"] = 400  # spent 400 of 1,000
    n, why = supervisor.check(doc, {"tool": "budget", "tokens": 2000, "why": "x"}, wallet=300)
    assert n is None and "at most 700" in why
    n, _ = supervisor.check(doc, {"tool": "budget", "tokens": 700, "why": "x"}, wallet=300)
    assert n is not None and n["tokens"] == 700  # a cut is allowed, and still the engineer's call
    assert supervisor.classify(doc, n) == ("major", "program settings are yours to change")
    n, _ = supervisor.check(doc, {"tool": "budget", "tokens": 1200, "why": "x"}, wallet=900)
    assert n is not None and n["tokens"] == 1200 and n["before"] == 1000
    assert supervisor.classify(doc, n)[0] == "major"
    # the rule-based reading never proposes more than the wallet allows
    doc["budget"]["tokens"] = 420
    plan = supervisor.rule_plan(doc, [{"kind": "budget", "ticket": None, "text": ""}], {}, 50)
    assert plan["actions"][0]["tokens"] <= 400 + 50


def test_the_hourly_call_cap_falls_back_to_the_rules(tmp_path: Path) -> None:
    import time as _time

    root, doc = _program(tmp_path)
    pid = doc["id"]
    env = FakeEnv()
    stub = StubProvider(responder=lambda req: _reply(MEASUREMENT_REPLY))

    async def go() -> None:
        await _stuck_by_no_progress(root, pid, env)
        with store.lock(pid):
            d = store.load(root, pid)
            supervisor.sup(d)["calls"] = [_time.time() - 60] * supervisor.MAX_CALLS_PER_HOUR
            store.save(root, d)
        with llm.use_provider(stub, roles=("supervisor",)):
            res = await supervisor.run_pass(root, pid, env)
        assert res["mode"] == "rules" and stub.calls == []  # no model call past the cap
        assert supervisor.view(store.load(root, pid))["calls_hour"] == supervisor.MAX_CALLS_PER_HOUR

    asyncio.run(go())


def test_another_workspace_is_out_of_reach(tmp_path: Path) -> None:
    _root, doc = _program(tmp_path, org="org1")
    other = store.org_root(tmp_path, "org2")
    other.mkdir(parents=True, exist_ok=True)
    # a program document copied into another organisation's folder is not acted on
    d2 = {**doc, "id": doc["id"]}
    (store.program_dir(other, doc["id"])).mkdir(parents=True, exist_ok=True)
    store.save(other, d2)
    res = asyncio.run(supervisor.run_pass(other, doc["id"], None, force=True))
    assert res["ran"] is False
    with pytest.raises(Exception, match="not found|Program"):
        supervisor.undo(other, doc["id"], "SA-1", ENG)


def test_a_repeat_of_the_same_block_escalates_instead_of_retrying_again(tmp_path: Path,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FW_OFFICE_SUPERVISOR_AI", "0")
    root, doc = _program(tmp_path)
    pid = doc["id"]
    why = "Fitz couldn't place Output shaft: the assembly worker stopped."

    def block() -> None:
        with store.lock(pid):
            d = store.load(root, pid)
            t = next(x for x in d["tickets"] if x["title"] == "Output shaft")
            orchestrator._set_run(t, status="fitting", next="fit")
            r = orchestrator.Runner.__new__(orchestrator.Runner)
            r.root, r.pid = root, pid
            r._fail(d, t["id"], why)
            store.save(root, d)

    async def go() -> None:
        block()
        res = await supervisor.run_pass(root, pid, None)
        e = store.load(root, pid)["supervisor"]["log"][-1]
        assert e["tool"] == "retry" and e["status"] == "applied" and len(res["done"]) == 1
        assert _ticket(root, pid, "Output shaft")["run"]["status"] == "queued"
        block()  # the same way again
        res = await supervisor.run_pass(root, pid, None)
        assert not res.get("done") and not res.get("asked")
        assert "failed the same way again after I acted" in archie_chat.history(root, pid)[-1]["text"]
        block()  # and a third time: he has said it, he stays quiet
        assert (await supervisor.run_pass(root, pid, None))["ran"] is False

    asyncio.run(go())


def test_passes_are_debounced_and_never_two_at_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, doc = _program(tmp_path)
    pid = doc["id"]
    calls: list[int] = []
    live = [0, 0]  # passes running now, the most ever at once

    async def slow(root_: Path, pid_: str, env: Any = None, **kw: Any) -> dict[str, Any]:
        calls.append(1)
        live[0] += 1
        live[1] = max(live[1], live[0])
        await asyncio.sleep(0.05)
        live[0] -= 1
        return {"ran": True}

    monkeypatch.setattr(supervisor, "run_pass", slow)
    monkeypatch.setattr(supervisor, "DEBOUNCE_S", 0.02)

    async def go() -> None:
        t1 = supervisor.kick(root, pid)
        assert supervisor.kick(root, pid) is t1  # triggers that arrive together: one pass
        await asyncio.sleep(0.04)                # now inside the pass
        assert supervisor.kick(root, pid) is t1  # a trigger during the pass: one more pass afterwards, not a second
        await t1
        assert len(calls) == 2 and live[1] == 1
        t3 = supervisor.kick(root, pid)
        assert t3 is not t1
        await t3
        assert len(calls) == 3 and live[1] == 1

    asyncio.run(go())


def test_the_runner_notifies_and_ticks_the_supervisor(tmp_path: Path) -> None:
    root, doc = _program(tmp_path)
    pid = doc["id"]
    with store.lock(pid):
        d = store.load(root, pid)
        t = d["tickets"][0]
        supervisor.notify(d, "blocked", t, "x")
        store.save(root, d)
    assert pid in supervisor._flags
    seen: list[str] = []
    orig = supervisor.kick

    def fake_kick(root_: Path, pid_: str, env: Any = None) -> None:
        seen.append(pid_)

    supervisor.kick = fake_kick  # type: ignore[assignment]
    try:
        supervisor.tick(root, pid, None, now=1000.0)
        assert seen == [pid] and pid not in supervisor._flags
        supervisor.tick(root, pid, None, now=1001.0)  # first heartbeat clock starts
        supervisor.tick(root, pid, None, now=1001.0 + supervisor.HEARTBEAT_S + 1)
        assert seen == [pid, pid]
    finally:
        supervisor.kick = orig  # type: ignore[assignment]
        supervisor._last_beat.pop(pid, None)


def test_reply_parsing_drops_unknown_tools_and_scrubs_internals() -> None:
    text = _reply({"cause": "weird", "diagnosis": "Read model.py and the build_model tool output",
                   "say": "ok", "actions": [{"tool": "exec_python", "code": "x"}, {"tool": "retry", "ticket": "A-1"}]})
    p = supervisor.parse_reply(text)
    assert p is not None and p["cause"] == "none" and [a["tool"] for a in p["actions"]] == ["retry"]
    assert "model.py" not in p["diagnosis"]
    assert supervisor.parse_reply("no block here") is None


# ============================================================================ recorded from the live run (2026-11-20)
LIVE_REPLY = {  # Archie's first live answer on the stuck Cover (Opus), actions as he gave them
    "cause": "part",
    "diagnosis": "Only hole 1 is flagged: it sits 3 mm off in x while y matches. A single hole off by a clean 3 mm, with "
                 "the other holes passing, points to a misplaced feature that the rebuild did not move, not a misread "
                 "datum.",
    "evidence": ["Same reading after 2 builds; review rounds 2 of 2 used", "the rest of the pattern passes"],
    "say": "I'm not relaxing the hole check: it would not line up with its mating part. One more round with the exact "
           "coordinates.",
    "actions": [
        {"tool": "relax_rule", "rule": "review_rounds", "ticket": "KEY", "expiry": 1,
         "why": "The round cap is procedural; one more round with a precise instruction is honest work on a fixable part"},
        {"tool": "relax_rule", "rule": "no_progress", "ticket": "KEY", "expiry": 1,
         "why": "The rebuild didn't move the hole because the instruction wasn't specific enough"},
        {"tool": "send_back", "ticket": "KEY", "instruction": "Move the tapped hole so it is blind, 12 mm deep, as the "
         "ICD says. Change no other feature.", "why": "The feature must match its mating part"}]}


def test_live_reply_procedural_relaxations_and_a_precise_instruction_are_done_without_asking(tmp_path: Path) -> None:
    root, doc = _program(tmp_path)
    pid = doc["id"]
    env = FakeEnv()
    key = _ticket(root, pid, "Input shaft")["key"]
    reply = json.loads(json.dumps(LIVE_REPLY).replace('"KEY"', json.dumps(key)))

    async def go() -> None:
        await _stuck_by_no_progress(root, pid, env)
        with llm.use_provider(StubProvider(responder=lambda req: _reply(reply)), roles=("supervisor",)):
            res = await supervisor.run_pass(root, pid, env)
        assert len(res["done"]) == 3 and not res["asked"]  # all minor: procedural rules and an instruction
        d = store.load(root, pid)
        log_ = d["supervisor"]["log"]
        assert [e["class"] for e in log_] == ["minor"] * 3 and all(e["status"] == "applied" for e in log_)
        ovs = {o["rule"]: o for o in d["supervisor"]["overrides"]}
        assert set(ovs) == {"review_rounds", "no_progress"} and ovs["review_rounds"]["extra"] == 1
        assert log_[0]["outcome"].startswith("The review-round cap is relaxed for 1 more round")
        t = _ticket(root, pid, "Input shaft")
        assert t["run"]["next"] == "design" and t["run"]["feedback"][0].startswith("Archie (Chief Designer): Move")
        assert not t.get("relaxed")  # nothing measured was relaxed
        msg = archie_chat.history(root, pid)[-1]
        assert "I'm not relaxing the hole check" in msg["text"] and not msg.get("questions")

    asyncio.run(go())


def test_an_interface_change_on_an_approved_icd_is_major(tmp_path: Path) -> None:
    brief = "Mounting plate 120 x 80 x 10 mm and a cover plate 120 x 80 x 6 mm, joined by 4 M6 bolts. Nothing else."
    root = store.org_root(tmp_path, "org1")
    doc = service.new_program("Plate", brief, "org1", "u1", 2, 1000, "standard")
    service.set_plan(root, doc, planner.finish(planner.standard_plan("Plate", brief), "Plate", brief)[0], ENG)
    service.approve_plan(root, doc, None, ENG)
    interfaces.approve(root, doc, ENG)
    i = next(x for x in doc["icd"]["interfaces"] if x["kind"] == "hole_pattern")
    n, why = supervisor.check(doc, {"tool": "change_interface", "interface": i["id"], "values": {"fastener": "M6"},
                                    "why": "The brief asks for M6 bolts"})
    assert n is not None, why
    assert supervisor.classify(doc, n) == ("major", "it changes an approved interface")
    assert supervisor.describe(doc, n).startswith(f"Change request on interface {i['id']}: fastener → M6")


def test_a_stale_interfaces_gate_with_standalone_parts_is_cleared_by_archie(tmp_path: Path,
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate waits with two unconnected shafts; the brief says they are made on their own: keep-separate is minor."""
    monkeypatch.setenv("FW_OFFICE_SUPERVISOR_AI", "0")
    root = store.org_root(tmp_path, "org1")
    doc = service.new_program("Kit", "Two shafts made on their own, no housing", "org1", "u1", 2, 1000, "standard")
    service.set_plan(root, doc, planner.normalise_plan(KIT, "standard"), ENG)
    service.approve_plan(root, doc, None, ENG)
    store.save(root, doc)
    pid = doc["id"]
    assert doc["icd"]["problems"] and not supervisor.detect(doc)  # fresh: not stale yet
    later = supervisor._ts(doc["updated_at"]) + supervisor.GATE_STALE_MIN * 60 + 5
    assert [x["kind"] for x in supervisor.detect(doc, later)] == ["gate"]

    async def go() -> None:
        res = await supervisor.run_pass(root, pid, None, now=later)
        assert len(res["done"]) == 1 and not res["asked"]
        d = store.load(root, pid)
        e = d["supervisor"]["log"][-1]
        assert e["tool"] == "keep_separate" and e["class"] == "minor" and e["status"] == "applied"
        assert d["icd"]["problems"] == [] and d["icd"]["history"][-1]["by"] == "Archie"
        assert supervisor.view(d)["log"][0]["undoable"] is True
        supervisor.undo(root, pid, e["id"], ENG)
        assert store.load(root, pid)["icd"]["problems"]  # blocks again until connected or kept separate
        # a heartbeat that finds nothing new writes nothing
        rev = store.load(root, pid)["rev"]
        assert (await supervisor.run_pass(root, pid, None, now=later))["ran"] is False
        assert store.load(root, pid)["rev"] == rev

    asyncio.run(go())


# ============================================================================ "Fix with Archie" at the interfaces gate
ONE_BEARING = {"subassemblies": [{"name": "Shaft unit", "parts": [
    {"name": "Shaft", "family": "turned", "complexity": 2, "qty": 1, "description": "Ø20 x 100"},
    {"name": "Spur gear", "family": "gear", "complexity": 2, "qty": 1, "description": "m2 30 teeth"},
    {"name": "Ball bearing 6204", "family": "standard", "complexity": 1, "qty": 1, "description": "6204"}]}]}


def _at_gate(tmp_path: Path, brief: str, plan: dict[str, Any]) -> tuple[Path, str]:
    root = store.org_root(tmp_path, "org1")
    doc = service.new_program("Gate", brief, "org1", "u1", 2, 1000, "standard")
    service.set_plan(root, doc, planner.normalise_plan(plan, "standard"), ENG)
    service.approve_plan(root, doc, None, ENG)
    store.save(root, doc)
    return root, doc["id"]


def test_fix_with_archie_clears_shaft_support_with_a_plan_change_the_engineer_picks(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The founder's question: "If you can tell me how to fix it, why can't Archie?" The number fix can't make a
    bearing; Archie proposes the plan changes that clear it (alternatives), applies the one picked, and the gate is
    checked again on the new layout."""
    monkeypatch.setenv("FW_OFFICE_SUPERVISOR_AI", "0")
    root, pid = _at_gate(tmp_path, "A shaft carrying a spur gear, on one 6204 ball bearing.", ONE_BEARING)
    d = store.load(root, pid)
    assert [x["code"] for x in icd.issues(d["skeleton"], d["icd"]["interfaces"]) if x["severity"] == "error"] == [
        "shaft_support"]

    async def go() -> None:
        res = await supervisor.fix_gate(root, pid, ENG)
        assert res["steps"] == [] and res["problems"]  # step 1: no number change can make a bearing
        a = res["archie"]
        assert a["ran"] and a["done"] == [] and len(a["asked"]) == 2
        assert a["asked"][0] == "Plan 2 × Ball bearing 6204 instead of 1" and a["asked"][1].startswith("Add Housing")
        assert any("fewer than two bearings" in x for x in a["open"])
        q = archie_chat.history(root, pid)[-1]["questions"]
        assert len(q) == 1 and q[0]["question"] == "Which change should I make?"  # alternatives: one question
        opts = q[0]["options"]
        assert [o["id"] for o in opts] == ["approve", "approve", "decline"] and opts[-1]["label"] == "None of these"
        x = await supervisor.decide(root, pid, opts[0]["action"], "approve", ENG)
        assert x["status"] == "applied" and "no problem left" in x["outcome"]
        d = store.load(root, pid)
        assert d["icd"]["problems"] == [] and d["status"] == "active"  # laid out again, the gate checked again
        assert [p["qty"] for _s, p in supervisor._plan_parts(d) if p["name"] == "Ball bearing 6204"] == [2]
        other = next(e for e in d["supervisor"]["log"] if e["id"] == opts[1]["action"])
        assert other["status"] == "declined" and other["outcome"] == "You chose another option"
        assert archie_chat.history(root, pid)[-1]["questions"][0]["chosen"] == opts[0]["action"]
        supervisor.undo(root, pid, x["id"], ENG)  # a plan edit not yet built: undone, the problem is back
        assert store.load(root, pid)["icd"]["problems"]

    asyncio.run(go())


def test_fix_with_archie_on_unconnected_parts_asks_and_never_looks_idle(tmp_path: Path,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FW_OFFICE_SUPERVISOR_AI", "0")
    root, pid = _at_gate(tmp_path, "Two shafts for the pump", KIT)
    assert len(interfaces.unconnected(store.load(root, pid))) == 2

    async def go() -> None:
        res = await supervisor.fix_gate(root, pid, ENG)
        a = res["archie"]
        assert res["steps"] == [] and a["ran"] and a["asked"] == ["Keep Input shaft and Output shaft as separate parts"]
        assert "no number change can make one" in a["open"][0]
        e = store.load(root, pid)["supervisor"]["log"][-1]
        assert e["class"] == "major" and e["class_why"] == "only you can say a part is meant to have no interface"
        await supervisor.decide(root, pid, e["id"], "approve", ENG)
        assert store.load(root, pid)["icd"]["problems"] == []
        # with the supervisor off the button still says what is open and why (no silent click)
        monkeypatch.setenv("FW_OFFICE_SUPERVISOR", "0")
        root2, pid2 = _at_gate(tmp_path / "b", "Two shafts for the pump", KIT)
        r2 = await supervisor.fix_gate(root2, pid2, ENG)
        assert r2["archie"]["ran"] is False and r2["archie"]["open"]

    asyncio.run(go())
