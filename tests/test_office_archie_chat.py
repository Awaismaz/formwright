"""Talking to Archie during a program (CD-026) and per-agent threads (CD-027)."""

from __future__ import annotations

from typing import Any

import pytest
from test_office import _create, app_client  # noqa: F401  (fixture)

from aicad.office import archie_chat, estimates, timeline


def _t(i: int, spec: str, est: float = 4.0, deps: list[str] | None = None) -> dict[str, Any]:
    return {"id": f"t{i}", "key": f"P-{i}", "item_id": f"p{i}", "specialist": spec, "estimate_min": est, "progress": 0,
            "depends_on": deps or [], "kind": "part"}


# ------------------------------------------------------------------ per-agent threads: ETA and planned schedule
def test_threads_shape_the_eta_and_none_keeps_the_old_pool() -> None:
    items = [{"id": "x", "parent_id": None, "kind": "program", "name": "P"}] + [
        {"id": f"p{i}", "parent_id": "x", "kind": "part", "name": f"P{i}"} for i in range(1, 9)]
    six = [_t(i, "molly") for i in range(1, 7)]
    pool = estimates.eta(items, six, "x", 3)
    assert pool == estimates.eta(items, six, "x", 3, None)  # programs from before threads: unchanged
    one = estimates.eta(items, six, "x", 3, {"molly": 1})
    three = estimates.eta(items, six, "x", 3, {"molly": 3})
    assert one["low_min"] == pytest.approx(0.8 * 24) and one["high_min"] == pytest.approx(1.3 * (4 + 24))
    assert three["low_min"] == pytest.approx(0.8 * 8) and three == {**pool, "concurrency": 3}
    # threads above the office cap don't help; another agent without a thread count shares the pool
    assert estimates.eta(items, six, "x", 2, {"molly": 6})["low_min"] == pytest.approx(0.8 * 12)
    mixed = six + [_t(7, "mill"), _t(8, "mill")]
    assert estimates.eta(items, mixed, "x", 3, {"molly": 1})["low_min"] == pytest.approx(0.8 * 24)
    assert estimates.clean_threads({"molly": 40, "mill": 0, "x": "2", "y": True}) == {"molly": 12, "mill": 1}


def test_planned_schedule_runs_an_agent_at_most_its_threads() -> None:
    six = [_t(i, "molly") for i in range(1, 7)]
    seq = timeline.planned(six, 3, {"molly": 1})
    assert max(p["end"] for p in seq.values()) == pytest.approx(24)
    par = timeline.planned(six, 3, {"molly": 3})
    assert max(p["end"] for p in par.values()) == pytest.approx(8)
    assert timeline.planned(six, 3) == timeline.planned(six, 3, None)


# ------------------------------------------------------------------ API: threads, concurrency and budget any time
def test_threads_concurrency_and_budget_change_in_plan_review_and_in_work(app_client: Any) -> None:  # noqa: F811
    from test_platform import signup

    c = app_client
    signup(c, "threads@x.com")
    v = _create(c)
    pid = v["id"]
    assert v["status"] == "plan_review" and v["threads"] == {"mill": 1, "chuck": 1, "axel": 1, "benny": 1, "molly": 1}
    slow = v["plan_estimate"]["eta"]
    v = c.patch(f"/api/office/programs/{pid}", json={"concurrency": 8, "threads": {"mill": 4, "chuck": 4,
                                                                                    "nobody": 3}}).json()
    assert v["threads"]["mill"] == 4 and "nobody" not in v["threads"] and v["concurrency"] == 8
    fast = v["plan_estimate"]["eta"]
    assert fast["low_min"] < slow["low_min"] and fast["high_min"] < slow["high_min"]
    v = c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={}).json()
    assert v["status"] == "active" and v["threads"]["mill"] == 4
    v = c.patch(f"/api/office/programs/{pid}", json={"threads": {"mill": 1}, "budget_tokens": 5000}).json()
    assert v["threads"]["mill"] == 1 and v["threads"]["chuck"] == 4 and v["budget"]["tokens"] == 5000
    acts = c.get(f"/api/office/programs/{pid}/activity").json()["items"]
    assert any(a["type"] == "program.threads" and "Mill 1" in a["text"] for a in acts)


# ------------------------------------------------------------------ API: talk to Archie
def test_talk_to_archie_status_and_proposals_need_the_engineer(app_client: Any,  # noqa: F811
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    from test_platform import signup

    async def no_ai(*a: Any, **k: Any) -> tuple[str, float | None]:
        raise AssertionError("status and the office reader must not call the AI")

    monkeypatch.setattr(archie_chat, "run_chat", no_ai)
    from aicad.office import fake_agents

    monkeypatch.setattr(fake_agents, "enabled", lambda: True)  # simulated office: the deterministic reader
    c = app_client
    signup(c, "chat@x.com")
    pid = _create(c)["id"]
    base = f"/api/office/programs/{pid}/archie"
    r = c.get(base).json()
    assert r["messages"] == [] and r["ai"] is False
    r = c.post(base, json={"text": "What's the status?"}).json()
    m = r["messages"][-1]
    assert m["role"] == "archie" and m["kind"] == "status" and "waits for your approval" in m["text"]
    r = c.post(base, json={"text": "Make the housing cast iron instead of aluminium."}).json()
    m = r["messages"][-1]
    assert [a["type"] for a in m["actions"]] == ["replan"] and m["actions"][0]["status"] == "proposed"
    v = c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={}).json()
    # the plan is approved: the old re-plan proposal no longer applies
    r = c.post(base + "/actions", json={"message": m["id"], "action": "a1"})
    assert r.status_code == 409 and "moved on" in r.json()["detail"]
    part = next(t for t in v["tickets"] if t["kind"] == "part")
    r = c.post(base, json={"text": "Status report please"}).json()
    s = r["messages"][-1]["text"]
    assert r["messages"][-1]["kind"] == "status" and f"of {len(v['tickets'])} tickets finished" in s
    assert "not started (press Run)" in s
    r = c.post(base, json={"text": f"{part['key']}: break all outer edges 0.5 mm"}).json()
    m = r["messages"][-1]
    assert m["actions"][0]["type"] == "instruct" and m["actions"][0]["ticket"] == part["key"]
    assert part["title"] in m["actions"][0]["label"]
    # nothing changed until the engineer applies it
    t = next(x for x in c.get(f"/api/office/programs/{pid}").json()["tickets"] if x["id"] == part["id"])
    assert t["comments"] == []
    r = c.post(base + "/actions", json={"message": m["id"], "action": "a1"})
    assert r.status_code == 200, r.text
    out = r.json()
    t = next(x for x in out["program"]["tickets"] if x["id"] == part["id"])
    assert t["comments"][-1]["text"].endswith("break all outer edges 0.5 mm")
    assert out["messages"][-1]["actions"][0]["status"] == "applied"
    assert c.post(base + "/actions", json={"message": m["id"], "action": "a1"}).status_code == 409
    r = c.post(base, json={"text": "pause"}).json()
    assert r["messages"][-1]["actions"] == []  # the office isn't running


def test_archie_ai_turn_is_metered_and_only_valid_actions_survive(app_client: Any,  # noqa: F811
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    from test_platform import signup

    seen: list[str] = []

    async def fake_chat(folder: Any, prompt: str, budget_usd: float | None = None) -> tuple[str, float | None]:
        seen.append(prompt)
        return ('Molly has most of the work; give her two more threads and raise the budget.\n'
                '```fw-office-actions\n[{"type": "budget", "tokens": 6000, "threads": {"molly": 3}}, '
                '{"type": "delete_everything"}, {"type": "instruct", "ticket": "NOPE-9", "text": "x"}]\n```'), 0.05

    monkeypatch.setattr(archie_chat, "run_chat", fake_chat)
    c = app_client
    signup(c, "chatai@x.com")
    pid = _create(c)["id"]
    c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={})
    r = c.post(f"/api/office/programs/{pid}/archie", json={"text": "Can we finish sooner?"})
    assert r.status_code == 200, r.text
    m = r.json()["messages"][-1]
    assert m["kind"] == "ai" and m["tokens"] > 0 and "fw-office-actions" not in m["text"]
    assert [a["type"] for a in m["actions"]] == ["budget"]
    assert m["actions"][0]["label"] == "Set token budget 6,000 and Molly 3 threads"
    assert "Can we finish sooner?" in seen[0] and "Tickets (key, title" in seen[0]
    v = c.get(f"/api/office/programs/{pid}").json()
    assert v["budget"]["planning_tokens"] == m["tokens"]
    out = c.post(f"/api/office/programs/{pid}/archie/actions", json={"message": m["id"], "action": "a1"}).json()
    assert out["program"]["threads"]["molly"] == 3 and out["program"]["budget"]["tokens"] == 6000
    # a status question never spends tokens, even with AI available
    r = c.post(f"/api/office/programs/{pid}/archie", json={"text": "status?"}).json()
    assert r["messages"][-1]["kind"] == "status" and len(seen) == 1


# ------------------------------------------------------------------ the ICD gate is never a dead end (CD-028)
# A 1:8 display-model plan whose layout used to come out unbuildable: a 4 mm endplate carrying M3 holes, a 10 mm
# mirror with two M3 washers, a 3 mm push rod hosting an 8 mm stub axle.
CROWDED = {"summary": "Display model", "assumptions": [], "subassemblies": [
    {"id": "s1", "name": "Body", "description": "", "parts": [
        {"id": "p1", "name": "Tub", "family": "plastic", "complexity": 4, "qty": 1, "description": "Shell.",
         "envelope": [380.0, 110.0, 85.0]},
        {"id": "p2", "name": "Sidepod left", "family": "plastic", "complexity": 3, "qty": 1, "description": "Pod.",
         "envelope": [220.0, 60.0, 55.0], "mounts_on": "Tub"},
        {"id": "p3", "name": "Mirror", "family": "plastic", "complexity": 2, "qty": 2, "description": "Mirror.",
         "envelope": [20.0, 10.0, 15.0], "mounts_on": "Sidepod left"}]},
    {"id": "s2", "name": "Front wing", "description": "", "parts": [
        {"id": "p4", "name": "Front wing main plane", "family": "plastic", "complexity": 3, "qty": 1,
         "description": "Aerofoil.", "envelope": [250.0, 40.0, 8.0]},
        {"id": "p5", "name": "Front wing endplate", "family": "plastic", "complexity": 2, "qty": 2,
         "description": "Endplate.", "envelope": [45.0, 4.0, 25.0], "mounts_on": "Front wing main plane"}]},
    {"id": "s3", "name": "Corner", "description": "", "parts": [
        {"id": "p6", "name": "Stub axle", "family": "turned", "complexity": 2, "qty": 1, "description": "Axle.",
         "envelope": [8.0, 8.0, 22.0]},
        {"id": "p7", "name": "Push rod", "family": "turned", "complexity": 1, "qty": 2, "description": "Rod.",
         "envelope": [3.0, 3.0, 60.0], "mounts_on": "Stub axle"}]}]}


def test_a_crowded_layout_corrects_itself_before_the_engineer_sees_it(app_client: Any) -> None:  # noqa: F811
    from test_platform import signup

    c = app_client
    signup(c, "selffix@x.com")
    pid = _create(c)["id"]
    v = c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={"plan": CROWDED})
    assert v.status_code == 200, v.text
    ic = v.json()["icd"]
    assert ic["problems"] == []
    fixed = [h for h in ic["history"] if h["kind"] == "fixed"]
    assert fixed and "so every part can be made" in fixed[0]["text"]
    assert c.post(f"/api/office/programs/{pid}/gates/icd/approve").status_code == 200


def test_left_over_icd_problems_are_fixed_from_the_archie_chat(app_client: Any,  # noqa: F811
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    from test_platform import signup

    from aicad.office import fake_agents, interfaces

    real = interfaces.autofix
    monkeypatch.setattr(interfaces, "autofix", lambda doc, ov: (ov, [], []))  # as before CD-028: no self-fix
    monkeypatch.setattr(fake_agents, "enabled", lambda: True)  # the office reader, no AI
    c = app_client
    signup(c, "chatfix@x.com")
    pid = _create(c)["id"]
    v = c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={"plan": CROWDED}).json()
    probs = v["icd"]["problems"]
    assert len(probs) >= 2
    assert c.post(f"/api/office/programs/{pid}/gates/icd/approve").status_code == 409
    monkeypatch.setattr(interfaces, "autofix", real)
    # a status report says what blocks the program and what to do
    s = c.post(f"/api/office/programs/{pid}/archie", json={"text": "status"}).json()["messages"][-1]["text"]
    assert "interface problem" in s and "Fix with Archie" in s
    # the engineer says what they'd say to a person; Archie proposes the fix, the engineer applies it
    m = c.post(f"/api/office/programs/{pid}/archie", json={"text": "It shows interferences and I don't know how to "
                                                                  "proceed"}).json()["messages"][-1]
    assert [a["type"] for a in m["actions"]] == ["fix_icd"]
    out = c.post(f"/api/office/programs/{pid}/archie/actions", json={"message": m["id"], "action": "a1"})
    assert out.status_code == 200, out.text
    p = out.json()["program"]
    assert p["icd"]["problems"] == [] and p["icd"]["history"][-1]["kind"] == "fixed"
    assert c.post(f"/api/office/programs/{pid}/icd/fix").json()["fix"] == {"steps": [], "problems": []}
    assert c.post(f"/api/office/programs/{pid}/gates/icd/approve").status_code == 200


def test_draft_icd_edits_are_allowed_while_other_problems_remain(app_client: Any,  # noqa: F811
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    from test_platform import signup

    from aicad.office import interfaces

    monkeypatch.setattr(interfaces, "autofix", lambda doc, ov: (ov, [], []))
    c = app_client
    signup(c, "oneatatime@x.com")
    pid = _create(c)["id"]
    v = c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={"plan": CROWDED}).json()
    n = len(v["icd"]["problems"])
    f = next(x for x in v["icd"]["interfaces"] if x["kind"] == "face")
    r = c.patch(f"/api/office/programs/{pid}/icd/interfaces/{f['id']}", json={"values": {"flatness": 0.08}})
    assert r.status_code == 200, r.text
    assert len(r.json()["icd"]["problems"]) == n
