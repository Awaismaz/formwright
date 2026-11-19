"""Design Office Phase 3 (CD-006..009, CD-016): the orchestrator, specialist part agents, Gage, Fitz, comments and
budget stops. No live AI anywhere: part agents run through the real Studio session with a deterministic fake model
client (``office.fake_agents.FakeClient``) that writes a tiny valid part; Gage's AI note is the fake one; Archie and
the real review call fail the test if reached."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from aicad.office import fake_agents, gage, orchestrator, planner, platform_env, service


# ----------------------------------------------------------------------------- priority (hand calculations)
# A (10 min) and B (20) feed S1 (6); C (5) feeds S2 (4); S1 and S2 feed the final assembly F (3).
#   chain(F) = 3; chain(S1) = 6 + 3 = 9; chain(S2) = 4 + 3 = 7
#   chain(A) = 10 + 9 = 19; chain(B) = 20 + 9 = 29; chain(C) = 5 + 7 = 12
#   dependents: A, B, C -> 2 each (their integration + F); S1, S2 -> 1; F -> 0
def _t(tid: str, est: float, deps: list[str] | None = None, column: str = "ready", **kw: Any) -> dict[str, Any]:
    return {"id": tid, "key": f"K-{tid[1:]}", "title": tid, "kind": kw.pop("kind", "part"), "estimate_min": est,
            "progress": kw.pop("progress", 0), "column": column, "depends_on": deps or [], "item_id": tid,
            "specialist": "mill", "milestones": [], "comments": [], **kw}


def _dag() -> dict[str, Any]:
    return {"tickets": [_t("t1", 10), _t("t2", 20), _t("t3", 5),
                        _t("t4", 6, ["t1", "t2"], "backlog", kind="integration"),
                        _t("t5", 4, ["t3"], "backlog", kind="integration"),
                        _t("t6", 3, ["t4", "t5"], "backlog", kind="integration")],
            "budget": {"tokens": 0}}


def test_critical_path_priority_hand_computed() -> None:
    doc = _dag()
    pr = orchestrator.priority(doc)
    assert {k: v["chain"] for k, v in pr.items()} == {"t1": 19, "t2": 29, "t3": 12, "t4": 9, "t5": 7, "t6": 3}
    assert {k: v["dependents"] for k, v in pr.items()} == {"t1": 2, "t2": 2, "t3": 2, "t4": 1, "t5": 1, "t6": 0}
    q = orchestrator.queue(doc, time.time())
    assert [(t["id"], s) for t, s in q] == [("t2", "hex"), ("t1", "hex"), ("t3", "hex")]  # integrations wait
    # a finished part leaves the chain: A done -> only B still feeds S1
    doc["tickets"][0].update(column="approved", progress=100)
    assert orchestrator.priority(doc)["t1"]["chain"] == 9
    # integration becomes claimable once its children are done
    doc["tickets"][1]["column"] = "approved"
    assert [t["id"] for t, _s in orchestrator.queue(doc, time.time())] == ["t3", "t4"]
    assert orchestrator.claimable(doc, doc["tickets"][3], time.time()) == "integrate"


def test_ties_go_to_most_dependents_then_engineer_priority() -> None:
    # X (5) feeds Y (5): chain(X) = 10 with 1 dependent; Z (10) stands alone: chain 10, 0 dependents.
    doc = {"tickets": [_t("t1", 10), _t("t2", 5), _t("t3", 5, ["t2"], "backlog")], "budget": {"tokens": 0}}
    assert [t["id"] for t, _s in orchestrator.queue(doc, time.time())] == ["t2", "t1"]
    doc["tickets"][0]["priority"] = "high"
    assert [t["id"] for t, _s in orchestrator.queue(doc, time.time())] == ["t1", "t2"]


def test_claimable_states() -> None:
    doc = _dag()
    t = doc["tickets"][0]
    now = time.time()
    assert orchestrator.claimable(doc, t, now) == "hex"
    t["paused"] = True
    assert orchestrator.claimable(doc, t, now) is None
    t["paused"] = False
    t["run"] = {"status": "retry", "next": "design", "next_try_at": now + 30}
    assert orchestrator.claimable(doc, t, now) is None and orchestrator.claimable(doc, t, now + 31) == "design"
    t["run"] = {"status": "designing"}
    assert orchestrator.claimable(doc, t, now) is None  # already being worked: never claimed twice
    t["run"] = {"status": "blocked"}
    assert orchestrator.claimable(doc, t, now) is None
    t["run"], t["column"] = None, "in_design"  # moved by hand (Phase 2 Start): the office leaves it alone
    assert orchestrator.claimable(doc, t, now) is None
    t["column"], t["project_id"] = "in_review", "p1"  # finished by hand: Gage still inspects it
    assert orchestrator.claimable(doc, t, now) == "review"
    assert orchestrator.backoff(1, 20, 300) == 20 and orchestrator.backoff(3, 20, 300) == 80
    assert orchestrator.backoff(9, 20, 300) == 300


def test_budget_levels() -> None:
    doc = {"budget": {"tokens": 100, "planning_tokens": 10},
           "tickets": [{"tokens": 60, "review_tokens": 9}, {"tokens": 0}]}
    assert orchestrator.budget_state(doc)["level"] == "ok" and orchestrator.spent(doc) == 79
    doc["tickets"][1]["tokens"] = 1
    assert orchestrator.budget_state(doc) | {} == {**orchestrator.budget_state(doc), "level": "warn", "pct": 80.0}
    doc["tickets"][1]["tokens"] = 21
    b = orchestrator.budget_state(doc)
    assert b["level"] == "stop" and b["remaining"] == 0
    doc["orchestrator"] = {"god_tokens": True}
    assert orchestrator.budget_state(doc)["bypass"] is True
    assert orchestrator.budget_state({"budget": {"tokens": 0}, "tickets": [{"tokens": 999}]})["level"] == "ok"


def test_gage_deterministic_review() -> None:
    t = {"key": "X-1", "title": "Plate", "brief": "Design the Plate for the Base of X, as a machined part. "
         "Plate 120 x 80 x 10 mm with a Ø25 bore and 4 M6 holes.\n\nProgram brief: 1450 rpm, 3:1, 200 mm wide."}
    assert [v for _l, v in gage.brief_dimensions(gage.ticket_text(t))] == [25, 120, 80, 10]
    good = {"builds": 1, "ok": True, "checks": [], "bbox": [120, 80, 10], "params": {"BORE_R": 12.5}, "source": ""}
    assert gage.deterministic(t, good) == []  # Ø25 found as a radius
    bad = {**good, "params": {}, "bbox": [120, 80, 12]}
    f = gage.deterministic(t, bad)
    assert len(f) == 2 and "Ø25" in f[0] and "10 mm" in f[1]
    failing = {**good, "ok": False, "checks": [{"id": "CHK-09", "name": "reference", "passed": False}]}
    assert "CHK-09" in gage.deterministic(t, failing)[0]
    assert gage.deterministic(t, {"builds": 0}) == ["There is no build of this part yet."]
    r = gage.parse_review('ok\n```fw-gage\n{"verdict": "changes", "findings": ["Hole too close to edge"]}\n```')
    assert r == {"verdict": "changes", "findings": ["Hole too close to edge"], "notes": [], "note": "ok"}
    r = gage.parse_review('ok\n```fw-gage\n{"verdict": "approve", "findings": [], "notes": ["Name the slot"]}\n```')
    assert r is not None and r["verdict"] == "approve" and r["notes"] == ["Name the slot"]
    assert gage.parse_review("no block")is None
    assert gage.parse_review('```fw-gage\n{"verdict": "changes", "findings": []}\n```')["verdict"] == "approve"


def test_hex_reuse_rules() -> None:
    doc = {"items": [{"id": "i1", "description": "Hex bolts M6 x 25 clamping the cover."},
                     {"id": "i2", "description": "Bolted cap that locates the outer bearing ring."},
                     {"id": "i3", "description": "Spur gear module 2, 18 teeth."},
                     {"id": "i4", "description": ""}]}
    bolt = {"title": "Cover bolt", "kind": "standard", "item_id": "i1"}
    hit = platform_env.hex_lookup(doc, bolt, [])
    assert hit["source"] == "toolbox" and hit["code"] == "hex_bolt" and "M6" in hit["found"]
    cap = {"title": "Bearing cap", "kind": "part", "item_id": "i2"}
    assert platform_env.hex_lookup(doc, cap, []) is None  # "bearing" in a designed part's name is not a bearing
    pinion = {"title": "Pinion", "kind": "part", "item_id": "i3"}
    assert platform_env.hex_lookup(doc, pinion, [])["code"] == "spur_gear"
    plate = {"title": "Motor plate", "kind": "part", "item_id": "i4"}
    cands = [{"id": "p1", "name": "Motor plate", "description": ""}, {"id": "p2", "name": "Plate", "description": ""}]
    assert platform_env.hex_lookup(doc, plate, cands)["project_id"] == "p1"
    assert platform_env.hex_lookup(doc, plate, cands[1:]) is None  # only an exact part name is reused


# ----------------------------------------------------------------------------- the running office (fake agents)
@pytest.fixture()
def office(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    from aicad.platform import config
    from aicad.platform.routers import auth as auth_router

    auth_router._attempts.clear()
    monkeypatch.setenv("FW_ADMIN_PASSWORD", "correct horse 42")
    monkeypatch.setenv(fake_agents.ENV, "1")
    monkeypatch.delenv("FW_OFFICE_FAKE_DELAY", raising=False)
    monkeypatch.delenv("FW_OFFICE_FAKE_DEFECTS", raising=False)
    config.override_settings(config.Settings(
        env="development", data_dir=tmp_path / "data", database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
        app_url="http://testserver", superadmin_emails=("boss@example.com",), stripe_secret_key="", trial_tokens=300))

    async def no_live_ai(*a: Any, **k: Any) -> Any:
        raise AssertionError("tests must not call a live model")

    monkeypatch.setattr(planner, "run_agent", no_live_ai)
    monkeypatch.setattr(gage, "run_review", no_live_ai)
    monkeypatch.setattr(orchestrator, "TICK_S", 0.05)
    monkeypatch.setattr(orchestrator, "RETRY_BASE_S", 0.05)
    monkeypatch.setattr(orchestrator, "CAPACITY_BASE_S", 0.05)
    fake_agents.reset()
    from aicad.platform.app import create_app

    app = create_app()
    with TestClient(app) as c:
        c.headers.update({"X-FW-CSRF": "1"})
        c.app_factory = create_app  # type: ignore[attr-defined]
        yield c
    fake_agents.reset()


def _topup(email: str, tokens: int = 100_000) -> None:
    from sqlalchemy import select

    from aicad.platform.db import session_factory
    from aicad.platform.models import Membership, Organization, User

    db = session_factory()()
    try:
        u = db.scalar(select(User).where(User.email == email))
        m = db.scalar(select(Membership).where(Membership.user_id == u.id))
        db.get(Organization, m.org_id).token_balance = tokens
        db.commit()
    finally:
        db.close()


PLAN = {"source": "standard", "summary": "Test rig", "assumptions": [], "subassemblies": [
    {"name": "Base", "description": "", "parts": [
        {"name": "Base plate", "family": "machined", "complexity": 2, "qty": 1,
         "description": "Plate 120 x 80 x 10 mm."},
        {"name": "Cover bolt", "family": "standard", "complexity": 1, "qty": 4,
         "description": "Hex bolts M6 x 25."}]},
    {"name": "Drive", "description": "", "parts": [
        {"name": "Spacer", "family": "turned", "complexity": 1, "qty": 1, "description": "Spacer Ø20 x 15 mm."}]}]}


def _program(c: Any, email: str, plan: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
    from test_platform import signup

    signup(c, email)
    _topup(email)
    r = c.post("/api/office/programs", json={"name": "Test rig", "brief": "A small test rig with a base and a drive.",
                                             "planner": "standard",
                                             "deliverables": False, **kw})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={"plan": plan or PLAN})
    assert r.status_code == 200, r.text
    assert c.post(f"/api/office/programs/{pid}/run").status_code == 409  # parts wait for the ICD gate
    r = c.post(f"/api/office/programs/{pid}/gates/icd/approve")
    assert r.status_code == 200, r.text
    return _wait(c, pid, lambda v: (v.get("assembly") or {}).get("status") not in (None, "building"))


def _wait(c: Any, pid: str, pred: Any, timeout: float = 90) -> dict[str, Any]:
    t0 = time.time()
    v: dict[str, Any] = {}
    while time.time() - t0 < timeout:
        v = c.get(f"/api/office/programs/{pid}").json()
        if pred(v):
            return v
        time.sleep(0.1)
    raise AssertionError(f"timed out: {[(t['key'], t['column'], t.get('run')) for t in v.get('tickets', [])]}")


def _tk(v: dict[str, Any], title: str) -> dict[str, Any]:
    return next(t for t in v["tickets"] if t["title"] == title)


def _events(c: Any, pid: str) -> list[dict[str, Any]]:
    return list(reversed(c.get(f"/api/office/programs/{pid}/activity?limit=500").json()["items"]))


def test_program_runs_end_to_end(office: Any) -> None:
    c = office
    v = _program(c, "run@x.com")
    pid = v["id"]
    assert v["orchestrator"]["state"] == "idle" and v["orchestrator"]["simulated"] is True
    r = c.post(f"/api/office/programs/{pid}/run")
    assert r.status_code == 200, r.text
    assert c.post(f"/api/office/programs/{pid}/run").status_code == 200  # idempotent
    v = _wait(c, pid, lambda v: v["status"] == "complete")
    assert v["orchestrator"]["state"] == "complete"
    assert all(t["column"] == "integrated" for t in v["tickets"])
    # Hex: the bolts came from the Toolbox instantly with zero tokens
    bolt = _tk(v, "Cover bolt")
    assert bolt["reuse"]["source"] == "toolbox" and bolt["reuse"]["code"] == "hex_bolt"
    assert bolt["tokens"] == 0 and bolt["project_id"] is None and "M6" in bolt["reuse"]["found"]
    # the plate was designed in its own Studio project, checked by Gage, and metered
    plate = _tk(v, "Base plate")
    assert plate["project_id"] and plate["tokens"] > 0 and plate["review_tokens"] > 0
    assert plate["milestones"] == ["brief_read", "first_build", "gates_pass", "self_review", "approved"]
    assert any(cm["by"].get("code") == "gage" and cm["text"].startswith("Approved") for cm in plate["comments"])
    # Fitz integrated each level with 0 clashes
    for title in ("Assemble Base", "Assemble Drive", "Final assembly of Test rig"):
        it = _tk(v, title)
        assert it["assembly_id"] and it["integration"]["clashes"] == [], it["integration"]
    ev = _events(c, pid)
    types = [e["type"] for e in ev]
    for want in ("program.run", "ticket.claimed", "ticket.reused", "agent.status", "ticket.handoff",
                 "ticket.integrated", "program.done"):
        assert want in types, want
    # milestones from the agent's real events, in order, for the plate
    ms = [e["data"]["milestone"] for e in ev if e["ticket_id"] == plate["id"] and e["type"] == "ticket.milestone"
          and e["data"].get("reached")]
    assert ms[:2] == ["brief_read", "first_build"] and "self_review" in ms
    hand = [(e["data"]["from"], e["data"]["to"]) for e in ev if e["type"] == "ticket.handoff"
            and e["ticket_id"] == plate["id"]]
    assert hand == [("hex", "mill"), ("mill", "gage"), ("gage", "fitz")]
    # nothing in the event text exposes internals
    blob = " ".join(e["text"] for e in ev)
    for bad in ("model.py", "build_model", "mcp__", "claude", ".json"):
        assert bad not in blob
    # the Studio chat of the part shows a plain request, not the specialist instructions
    from aicad.platform.routers.projects import _sessions

    user_msgs = [e["text"] for e in _sessions[plate["project_id"]].history if e["type"] == "user"]
    assert user_msgs and all("You are Mill" not in m for m in user_msgs)
    assert fake_agents.STATS["max_active"] <= 3
    h = c.get("/api/office/home").json()
    assert h["programs"][0]["orchestrator"]["state"] == "complete"


def test_concurrency_cap_is_never_exceeded(office: Any) -> None:
    c = office
    parts = [{"name": f"Plate {i}", "family": "machined", "complexity": 1, "qty": 1,
              "description": f"Plate {40 + i} x 30 x 5 mm."} for i in range(5)]
    plan = {"source": "standard", "summary": "", "assumptions": [],
            "subassemblies": [{"name": "Stack", "description": "", "parts": parts}]}
    fake_agents.SCRIPT.append((r"Plate", {"delay": 0.05}))
    v = _program(c, "cap@x.com", plan, concurrency=2)
    pid = v["id"]
    c.post(f"/api/office/programs/{pid}/run")
    seen = 0
    t0 = time.time()
    while time.time() - t0 < 90:
        v = c.get(f"/api/office/programs/{pid}").json()
        seen = max(seen, sum(1 for t in v["tickets"] if (t.get("run") or {}).get("status") in orchestrator.ACTIVE))
        if v["status"] == "complete":
            break
        time.sleep(0.03)
    assert v["status"] == "complete"
    assert seen <= 2 and fake_agents.STATS["max_active"] <= 2
    assert orchestrator._runners.get(pid) is None or orchestrator._runners[pid].max_seen <= 2


def test_gage_sends_back_then_approves_and_caps_retries(office: Any) -> None:
    c = office
    plan = {"source": "standard", "summary": "", "assumptions": [], "subassemblies": [
        {"name": "Shafts", "description": "", "parts": [
            {"name": "Good shaft", "family": "turned", "complexity": 1, "qty": 1, "description": "Shaft Ø25 x 90 mm."},
            {"name": "Bad shaft", "family": "turned", "complexity": 1, "qty": 1,
             "description": "Shaft Ø32 x 125 mm."}]}]}
    fake_agents.SCRIPT += [(r"Good shaft", {"icd_grow": 2.0, "omit_turns": 1}),
                           (r"Bad shaft", {"icd_grow": 3.0, "omit_turns": 99})]
    v = _program(c, "gage@x.com", plan)
    pid = v["id"]
    c.post(f"/api/office/programs/{pid}/run")
    v = _wait(c, pid, lambda v: _tk(v, "Good shaft")["column"] == "approved"
              and (_tk(v, "Bad shaft").get("run") or {}).get("status") == "blocked")
    good, bad = _tk(v, "Good shaft"), _tk(v, "Bad shaft")
    g_good = [cm["text"] for cm in good["comments"] if cm["by"].get("code") == "gage"]
    # ICD conformance: the first build is 2 mm too big; Gage gives the measured size against the envelope
    assert len(g_good) == 2 and g_good[0].startswith("Changes requested") and "leaves its envelope" in g_good[0]
    assert "27.00 × 27.00" in g_good[0] and "inside 25 × 25" in g_good[0], g_good[0]
    assert g_good[1].startswith("Approved") and good["run"]["review_round"] == 1
    g_bad = [cm["text"] for cm in bad["comments"] if cm["by"].get("code") == "gage"]
    assert len(g_bad) == gage.MAX_SENDBACKS + 1 and bad["column"] == "changes_requested"
    assert bad["agent_state"] == "blocked" and "sent Bad shaft back 3 times; a measurable check still fails" in bad["line"]
    # the findings went back to the part agent as its next message
    assert any("This part was sent back" in p and "inside 32 × 32" in p for p in fake_agents.STATS["prompts"])
    inbox = c.get("/api/office/home").json()["inbox"]
    assert any(i["kind"] == "blocked" and i["ticket_id"] == bad["id"] for i in inbox)
    # no self-approval: Gage can't be made the designer
    assert c.patch(f"/api/office/programs/{pid}/tickets/{bad['id']}", json={"specialist": "gage"}).status_code == 409
    # the integration waits: one child is not approved
    assert _tk(v, "Assemble Shafts")["column"] == "backlog"


def test_comments_are_queued_and_delivered_and_controls(office: Any) -> None:
    c = office
    gate_ev = threading.Event()
    fake_agents.SCRIPT.append((r"Base plate", {"gate": gate_ev}))
    v = _program(c, "talk@x.com")
    pid = v["id"]
    c.post(f"/api/office/programs/{pid}/run")
    v = _wait(c, pid, lambda v: (_tk(v, "Base plate").get("run") or {}).get("status") == "designing"
              and _tk(v, "Base plate")["project_id"])
    plate = _tk(v, "Base plate")
    assert plate["agent"] == "mill" and plate["agent_state"] == "working" and plate["column"] == "in_design"
    # moving a ticket an agent is working on is refused
    assert c.post(f"/api/office/programs/{pid}/tickets/{plate['id']}/move", json={"column": "approved"}).status_code == 409
    v = c.post(f"/api/office/programs/{pid}/tickets/{plate['id']}/comments",
               json={"text": "Make the plate 12 mm thick please"}).json()
    cm = _tk(v, "Base plate")["comments"][-1]
    assert cm["delivery"] == "queued"
    gate_ev.set()
    v = _wait(c, pid, lambda v: _tk(v, "Base plate")["column"] in ("approved", "integrated"))
    plate = _tk(v, "Base plate")
    assert next(x for x in plate["comments"] if x["id"] == cm["id"])["delivery"] == "delivered"
    assert any("Make the plate 12 mm thick please" in p for p in fake_agents.STATS["prompts"]),         [p[:80].encode("ascii", "replace") for p in fake_agents.STATS["prompts"]]
    assert any(e["type"] == "ticket.comment_delivered" for e in _events(c, pid))
    # reprioritise, reopen, take over, hand back
    r = c.patch(f"/api/office/programs/{pid}/tickets/{plate['id']}", json={"priority": "high"})
    assert r.status_code == 200 and _tk(r.json(), "Base plate")["priority"] == "high"
    v = _wait(c, pid, lambda v: v["status"] == "complete")
    c.post(f"/api/office/programs/{pid}/pause")
    v = c.post(f"/api/office/programs/{pid}/tickets/{plate['id']}/control", json={"action": "reopen"}).json()
    plate = _tk(v, "Base plate")
    assert plate["column"] == "ready" and plate["run"]["next"] == "design" and "approved" not in plate["milestones"]
    v = c.post(f"/api/office/programs/{pid}/tickets/{plate['id']}/control", json={"action": "take_over"}).json()
    assert _tk(v, "Base plate")["run"]["status"] == "manual"
    assert orchestrator.claimable(v, _tk(v, "Base plate"), time.time()) is None
    v = c.post(f"/api/office/programs/{pid}/tickets/{plate['id']}/control", json={"action": "hand_back"}).json()
    assert _tk(v, "Base plate")["run"]["status"] == "queued"
    assert c.post(f"/api/office/programs/{pid}/tickets/{plate['id']}/control",
                  json={"action": "bogus"}).status_code == 409


def test_budget_warns_at_80_and_stops_at_100(office: Any) -> None:
    c = office
    parts = [{"name": f"Block {i}", "family": "machined", "complexity": 1, "qty": 1,
              "description": f"Block {30 + i} x 20 x 10 mm."} for i in range(6)]
    plan = {"source": "standard", "summary": "", "assumptions": [],
            "subassemblies": [{"name": "Blocks", "description": "", "parts": parts}]}
    # each fake turn costs 30 tokens and each review 5: 2 parts = 70 (88 % of 80), the third crosses 100 %
    v = _program(c, "budget@x.com", plan, concurrency=1, budget_tokens=80)
    pid = v["id"]
    c.post(f"/api/office/programs/{pid}/run")
    v = _wait(c, pid, lambda v: v["orchestrator"]["state"] == "stopped" and v["orchestrator"]["working"] == 0)
    assert v["orchestrator"]["reason"] == "budget" and v["budget"]["level"] == "stop"
    types = [e["type"] for e in _events(c, pid)]
    assert types.count("budget.warn") == 1 and types.count("budget.stop") == 1
    assert types.index("budget.warn") < types.index("budget.stop")
    done = [t for t in v["tickets"] if t["column"] == "approved"]
    assert 2 <= len(done) < 6 and any(t["column"] == "ready" for t in v["tickets"])
    assert all(t["spent"] == t["tokens"] + t["review_tokens"] for t in v["tickets"])
    # Run is refused while the budget is used up; raising it lets the office continue
    assert c.post(f"/api/office/programs/{pid}/run").status_code == 409
    c.patch(f"/api/office/programs/{pid}", json={"budget_tokens": 10_000})
    assert c.post(f"/api/office/programs/{pid}/run").status_code == 200
    _wait(c, pid, lambda v: v["status"] == "complete")


def test_rate_limit_waits_for_capacity(office: Any) -> None:
    c = office
    fake_agents.SCRIPT.append((r"Spacer", {"rate_limit_turns": 1}))
    v = _program(c, "rate@x.com")
    pid = v["id"]
    c.post(f"/api/office/programs/{pid}/run")
    _wait(c, pid, lambda v: v["status"] == "complete")
    ev = _events(c, pid)
    assert any(e["type"] == "capacity.wait" and "busy" in e["text"] for e in ev)


def test_restart_resumes_from_stored_state(office: Any) -> None:
    c = office
    gate_ev = threading.Event()
    fake_agents.SCRIPT.append((r"Base plate", {"gate": gate_ev}))
    v = _program(c, "restart@x.com")
    pid = v["id"]
    c.post(f"/api/office/programs/{pid}/run")
    _wait(c, pid, lambda v: (_tk(v, "Base plate").get("run") or {}).get("status") == "designing")
    cookies = dict(c.cookies)
    c.__exit__(None, None, None)  # the server stops mid-run
    from fastapi.testclient import TestClient

    from aicad.platform.routers import projects

    projects._sessions.clear()  # a new process has no live sessions
    gate_ev.set()
    with TestClient(c.app_factory()) as c2:
        c2.headers.update({"X-FW-CSRF": "1"})
        c2.cookies.update(cookies)
        v = _wait(c2, pid, lambda v: v["status"] == "complete")
        assert any(e["type"] == "program.resumed" for e in _events(c2, pid))
        assert _tk(v, "Base plate")["column"] == "integrated"
    c.__enter__()


def test_tenant_isolation(office: Any) -> None:
    from test_platform import signup

    c = office
    v = _program(c, "owner@x.com")
    pid, tid = v["id"], v["tickets"][0]["id"]
    c.post("/api/auth/logout")
    signup(c, "intruder@x.com", workspace="Other Co")
    assert c.get(f"/api/office/programs/{pid}").status_code == 404
    assert c.post(f"/api/office/programs/{pid}/run").status_code == 404
    assert c.post(f"/api/office/programs/{pid}/pause").status_code == 404
    assert c.post(f"/api/office/programs/{pid}/tickets/{tid}/control", json={"action": "pause"}).status_code == 404
    assert orchestrator.runner(pid) is None


def test_ticket_view_states() -> None:
    t = _t("t1", 5, column="in_design", run={"status": "reviewing", "agent": "gage", "agent_label": "Gage",
                                              "line": "Gage is inspecting t1"})
    v = service.ticket_view(t)
    assert v["agent"] == "gage" and v["agent_state"] == "working" and v["line"] == "Gage is inspecting t1"
    t["run"] = {"status": "waiting_capacity", "agent": "mill", "line": "Waiting for capacity"}
    assert service.ticket_view(t)["agent_state"] == "idle" and service.ticket_view(t)["agent"] == "mill"
    t["run"], t["column"] = None, "in_review"
    assert service.ticket_view(t)["agent_state"] == "review"


def test_advisory_review_points_never_block_a_part_that_passes_every_check(office: Any,
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """CD-030: Gage's AI points can send a part back MAX_SENDBACKS times; then a part whose measurable checks and
    interfaces pass is approved by Archie with the points recorded, never left waiting (the F1 dead end)."""
    from aicad.office import archie_chat, store
    from aicad.platform.config import get_settings

    prompts: list[str] = []
    real = fake_agents.fake_review

    async def spy(folder: Any, prompt: str, budget_usd: float | None = None) -> tuple[str, float | None]:
        prompts.append(prompt)
        return await real(folder, prompt, budget_usd)

    monkeypatch.setattr(fake_agents, "fake_review", spy)
    fake_agents.SCRIPT.append((r"Spacer", {"gage_changes": 99}))  # Gage never stops finding something
    c = office
    v = _program(c, "advisory@x.com")
    pid = v["id"]
    c.post(f"/api/office/programs/{pid}/run")
    v = _wait(c, pid, lambda v: _tk(v, "Spacer")["column"] in ("approved", "integrated")
              or (_tk(v, "Spacer").get("run") or {}).get("status") == "blocked")
    sp = _tk(v, "Spacer")
    assert sp["column"] in ("approved", "integrated"), sp["run"]
    g = [cm["text"] for cm in sp["comments"] if cm["by"].get("code") == "gage"]
    assert len(g) == gage.MAX_SENDBACKS + 1 and g[-1].startswith("Approved by Archie after 2 review rounds")
    assert "chamfer" in g[-1] and sp["review_notes"]
    # Gage judged against the approved interfaces and re-checked its earlier findings
    sp_prompts = [p for p in prompts if "Spacer" in p]
    assert all("Approved interfaces for this part" in p for p in sp_prompts)
    assert "Earlier findings" in sp_prompts[-1] and "chamfer" in sp_prompts[-1]
    v = _wait(c, pid, lambda v: v["orchestrator"]["state"] == "complete")
    # a part left blocked by the old rules (the F1 programs) recovers from the Archie chat
    root = store.org_root(get_settings().data_dir, v["org_id"])
    with store.lock(pid):
        d = store.load(root, pid)
        t = next(x for x in d["tickets"] if x["title"] == "Base plate")
        t["column"] = "changes_requested"
        t["run"] = {**t["run"], "status": "blocked", "next": "review", "review_round": 3,
                    "line": "Gage sent Base plate back 3 times."}
        store.save(root, d)
    monkeypatch.setattr(archie_chat, "run_chat", spy)  # never called: the office reader answers
    m = c.post(f"/api/office/programs/{pid}/archie", json={"text": "Parts are stuck after review, resolve it"}).json()
    m = m["messages"][-1]
    assert [a["type"] for a in m["actions"]] == ["retry_blocked"] and "1 blocked part" in m["actions"][0]["label"]
    r = c.post(f"/api/office/programs/{pid}/archie/actions", json={"message": m["id"], "action": "a1"})
    assert r.status_code == 200, r.text
    v = _wait(c, pid, lambda v: _tk(v, "Base plate")["column"] in ("approved", "integrated"))
