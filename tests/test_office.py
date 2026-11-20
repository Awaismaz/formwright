"""Design Office (CD-001..005): estimates and roll-up worked by hand, Archie's plan block parsing and the standard
planner, and the program API (tenant isolation, brief gate, ticket moves, events, Studio links). No live AI: Archie's
planning turn is always replaced by a fake."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from aicad.office import estimates, planner, roster, service

# ----------------------------------------------------------------------------- estimates (hand calculations)
# Fixture program: root -> S1 (parts A, B) and S2 (part C). One ticket per item.
ITEMS = [
    {"id": "root", "parent_id": None, "kind": "program"},
    {"id": "S1", "parent_id": "root", "kind": "subassembly"},
    {"id": "A", "parent_id": "S1", "kind": "part"},
    {"id": "B", "parent_id": "S1", "kind": "part"},
    {"id": "S2", "parent_id": "root", "kind": "subassembly"},
    {"id": "C", "parent_id": "S2", "kind": "part"},
]
TICKETS = [
    {"id": "tA", "item_id": "A", "estimate_min": 10, "progress": 100},
    {"id": "tB", "item_id": "B", "estimate_min": 20, "progress": 35},
    {"id": "tS1", "item_id": "S1", "estimate_min": 6, "progress": 0},
    {"id": "tC", "item_id": "C", "estimate_min": 8, "progress": 70},
    {"id": "tS2", "item_id": "S2", "estimate_min": 3, "progress": 0},
    {"id": "tR", "item_id": "root", "estimate_min": 6, "progress": 0},
]


def test_estimate_constants_and_milestones() -> None:
    # the AI designer's rates per complexity unit, from measured turns (60 to 100 s each, PD-190)
    assert estimates.estimate_minutes("machined", 3) == 3.6  # 3 x 1.2
    assert estimates.estimate_minutes("turned", 2) == 2.2  # 2 x 1.1
    assert estimates.estimate_minutes("standard", 1) == 0.05
    assert estimates.estimate_minutes("machined", 9) == 6.0  # complexity clamps to 5
    assert estimates.integration_complexity(2) == 1 and estimates.integration_complexity(7) == 3
    assert estimates.progress_of([]) == 0
    assert estimates.progress_of(["brief_read"]) == 5
    assert estimates.progress_of(["brief_read", "first_build"]) == 35
    assert estimates.progress_of(["gates_pass"]) == 70
    assert estimates.progress_of(["self_review", "first_build"]) == 85
    assert estimates.progress_of(["approved"]) == 100


def test_rollup_matches_hand_calculation() -> None:
    ru = estimates.rollup(ITEMS, TICKETS)
    # S1: estimate 10 + 20 + 6 = 36; done 10 x 1 + 20 x 0.35 + 0 = 17 -> 47.2 %
    assert ru["S1"] == {"estimate_min": 36, "done_min": 17, "remaining_min": 19, "progress": 47.2}
    # S2: 8 + 3 = 11; done 8 x 0.7 = 5.6 -> 50.9 %
    assert ru["S2"]["estimate_min"] == 11 and ru["S2"]["done_min"] == 5.6 and ru["S2"]["progress"] == 50.9
    # program: 36 + 11 + 6 = 53; done 17 + 5.6 = 22.6 -> 42.6 %
    assert ru["root"]["estimate_min"] == 53 and ru["root"]["done_min"] == 22.6 and ru["root"]["progress"] == 42.6
    assert ru["A"]["progress"] == 100.0 and ru["B"]["progress"] == 35.0


def test_critical_path_and_eta_match_hand_calculation() -> None:
    # remaining: tA 0, tB 13, tS1 6, tC 2.4, tS2 3, tR 6 -> W = 30.4
    # CP(S1) = 6 + max(0, 13) = 19; CP(S2) = 3 + 2.4 = 5.4; CP(root) = 6 + max(19, 5.4) = 25
    assert estimates.critical_path(ITEMS, TICKETS, "S1") == 19
    assert estimates.critical_path(ITEMS, TICKETS, "root") == 25
    e = estimates.eta(ITEMS, TICKETS, "root", 3)
    assert e["remaining_min"] == 30.4 and e["critical_path_min"] == 25
    assert e["low_min"] == 20.0  # 0.8 x max(25, 30.4 / 3)
    assert e["high_min"] == 45.7  # 1.3 x (25 + 10.133)
    s1 = estimates.eta(ITEMS, TICKETS, "S1", 3)
    assert s1["low_min"] == 15.2 and s1["high_min"] == 32.9  # 0.8 x 19; 1.3 x (19 + 19 / 3)
    one = estimates.eta(ITEMS, TICKETS, "root", 1)
    assert one["low_min"] == round(0.8 * 30.4, 1)  # one agent: all the work in series
    done = [{**t, "progress": 100} for t in TICKETS]
    assert estimates.eta(ITEMS, done, "root")["high_min"] == 0


# ----------------------------------------------------------------------------- Archie's plan block
ARCHIE_TEXT = """I split the winch into a drum and a frame.

```fw-plan
{"summary": "Hand winch, 2 sub-assemblies", "assumptions": ["Rope Ø6, 200 kg line pull"],
 "subassemblies": [
  {"name": "Drum", "description": "Rope drum on its shaft",
   "parts": [{"name": "Drum", "family": "turned", "complexity": 3, "qty": 1, "description": "Ø80 drum written in model.py"},
             {"name": "Drum shaft", "family": "lathe", "complexity": 9, "qty": 1},
             {"name": "Bearing 6204", "family": "purchased", "complexity": 4, "qty": 2},
             {"family": "machined"}]},
  {"name": "Frame", "parts": [{"name": "Side plate", "family": "laser-cut", "complexity": 2, "qty": "2"}]},
  {"name": "Empty", "parts": []}]}
```"""


def test_parse_plan_valid_block_is_validated() -> None:
    plan = planner.parse_plan(ARCHIE_TEXT)
    assert plan is not None and plan["source"] == "archie"
    assert [s["name"] for s in plan["subassemblies"]] == ["Drum", "Frame"]  # the empty sub-assembly is dropped
    drum = plan["subassemblies"][0]["parts"]
    assert [p["name"] for p in drum] == ["Drum", "Drum shaft", "Bearing 6204"]  # nameless part dropped
    assert drum[1]["family"] == "turned" and drum[1]["complexity"] == 5  # alias + clamp
    assert drum[2]["family"] == "standard" and drum[2]["complexity"] == 1 and drum[2]["toolbox"] == "bearing"
    assert "model.py" not in drum[0]["description"]  # internals are scrubbed
    side = plan["subassemblies"][1]["parts"][0]
    assert side["family"] == "machined" and side["qty"] == 2  # unknown family -> machined
    assert planner.narrative(ARCHIE_TEXT) == "I split the winch into a drum and a frame."


@pytest.mark.parametrize("text", [
    "no block at all",
    "```fw-plan\n{not json}\n```",
    "```fw-plan\n[1, 2, 3]\n```",
    '```fw-plan\n{"subassemblies": []}\n```',
    '```fw-plan\n{"subassemblies": [{"name": "X", "parts": [{"family": "turned"}]}]}\n```',
    '```json\n{"subassemblies": [{"name": "X", "parts": [{"name": "Y"}]}]}\n```',  # wrong fence
])
def test_parse_plan_rejects_invalid_blocks(text: str) -> None:
    assert planner.parse_plan(text) is None


def test_parse_plan_takes_last_valid_block() -> None:
    bad = "```fw-plan\n{oops}\n```"
    good = '```fw-plan\n{"subassemblies": [{"name": "Only", "parts": [{"name": "Plate"}]}]}\n```'
    assert planner.parse_plan(good + "\n" + bad)["subassemblies"][0]["name"] == "Only"  # type: ignore[index]


def test_standard_planner_is_deterministic_and_keyword_aware() -> None:
    brief = "Single-stage spur gearbox, 3:1 reduction, 1.5 kW input, NEMA motor flange, precision bearings seats h6"
    a, b = planner.standard_plan("Reducer", brief), planner.standard_plan("Reducer", brief)
    assert a == b and a["source"] == "standard"
    names = [s["name"] for s in a["subassemblies"]]
    assert names == ["Housing", "Input stage", "Output stage"]
    parts = {p["name"]: p for s in a["subassemblies"] for p in s["parts"]}
    assert parts["Input shaft"]["family"] == "turned" and parts["Input shaft"]["complexity"] == 4  # precision bump
    assert parts["Input bearing"]["family"] == "standard" and parts["Input bearing"]["toolbox"] == "bearing"
    assert "Motor mount" in parts  # motor mentioned
    gen = planner.standard_plan("Thing", "A device that does something useful for the lab bench")
    assert gen["subassemblies"][0]["name"] == "Frame" and "no product template" in gen["summary"]
    plastic = planner.standard_plan("Box", "Moulded ABS electronics enclosure with a lid")
    assert {p["family"] for s in plastic["subassemblies"] for p in s["parts"]} <= {"plastic", "machined", "standard"}


def test_specialist_by_family() -> None:
    assert [roster.specialist_for(f) for f in ("machined", "turned", "gear", "sheet", "plastic", "standard",
                                               "integration")] == ["mill", "chuck", "axel", "benny", "molly", "hex",
                                                                   "fitz"]
    assert len(roster.AGENTS) == 11 and {a["code"] for a in roster.AGENTS} >= {"archie", "gage", "ortho", "smithy"}


def test_build_tickets_from_plan() -> None:
    plan = planner.standard_plan("Reducer", "spur gearbox 3:1")
    items, tickets = service._build(plan, "Reducer", "RE", "spur gearbox 3:1")
    n_parts = sum(len(s["parts"]) for s in plan["subassemblies"])
    assert len(items) == 1 + len(plan["subassemblies"]) + n_parts
    assert len(tickets) == n_parts + len(plan["subassemblies"]) + 1  # parts + one integration per level
    final = tickets[-1]
    assert final["item_id"] == "root" and final["kind"] == "integration" and final["specialist"] == "fitz"
    assert len(final["depends_on"]) == len(plan["subassemblies"])
    shaft = next(t for t in tickets if t["title"] == "Input shaft")
    # on the path it will take: the drafted layout fixes the shaft (built from the interfaces, 3 to 9 s) or the AI
    # designer takes it (0.6 to 1.5 x complexity x 1.1 min)
    lo, hi = estimates.estimate_range("turned", 3, shaft["estimate_path"])
    assert shaft["specialist"] == "chuck" and (shaft["estimate_lo"], shaft["estimate_hi"]) == (lo, hi)         and shaft["estimate_min"] == round((lo + hi) / 2, 3) and shaft["column"] == "ready"
    assert "Design the Input shaft" in shaft["brief"] and "spur gearbox 3:1" in shaft["brief"]
    assert service.key_prefix("Gear reducer") == "GR" and service.key_prefix("winch") == "WIN"


# ----------------------------------------------------------------------------- API
@pytest.fixture()
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    from aicad.platform import config
    from aicad.platform.routers import auth as auth_router

    auth_router._attempts.clear()
    monkeypatch.setenv("FW_ADMIN_PASSWORD", "correct horse 42")
    config.override_settings(config.Settings(
        env="development", data_dir=tmp_path / "data", database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
        app_url="http://testserver", superadmin_emails=("boss@example.com",), stripe_secret_key="", trial_tokens=300))

    async def no_live_ai(*a: Any, **k: Any) -> tuple[str, float | None]:
        raise AssertionError("tests must not call the live agent")

    monkeypatch.setattr(planner, "run_agent", no_live_ai)
    from aicad.platform.app import create_app

    with TestClient(create_app()) as c:
        c.headers.update({"X-FW-CSRF": "1"})
        yield c


BRIEF = "Single-stage spur gear reducer, 3:1, 1.5 kW input at 1450 rpm, foot mounted, cast housing."


def _wait_plan(c: Any, pid: str, timeout: float = 20) -> dict[str, Any]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = c.get(f"/api/office/programs/{pid}").json()
        if r["status"] != "planning":
            return r
        time.sleep(0.1)
    raise AssertionError("planning did not finish")


def _create(c: Any, **kw: Any) -> dict[str, Any]:
    r = c.post("/api/office/programs", json={"name": "Gear reducer", "brief": BRIEF, "planner": "standard", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_api_program_crud_and_brief_gate(app_client: Any) -> None:
    from test_platform import signup

    c = app_client
    signup(c, "office@x.com")
    assert c.get("/api/office/home").json()["programs"] == []
    assert c.post("/api/office/programs", json={"brief": "too short", "planner": "standard"}).status_code == 422
    p = _create(c)
    pid = p["id"]
    assert p["status"] == "plan_review" and p["plan"]["source"] == "standard" and p["tickets"] == []
    assert p["plan_estimate"]["tickets"] > 0 and p["key"] == "GR"
    # tickets can't move before the gate
    assert c.post(f"/api/office/programs/{pid}/tickets/t1/move", json={"column": "in_design"}).status_code == 409
    # the reviewer edits the plan: drop the Output stage, raise a complexity, add a part
    plan = p["plan"]
    plan["subassemblies"] = plan["subassemblies"][:2]
    plan["subassemblies"][1]["parts"][0]["complexity"] = 5
    plan["subassemblies"][1]["parts"].append({"name": "Oil seal carrier", "family": "turned", "complexity": 2,
                                              "qty": 1, "description": "Holds the input oil seal."})
    r = c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={"plan": plan})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["status"] == "active" and v["plan"]["edited"] is True
    assert next(g for g in v["gates"] if g["code"] == "brief")["status"] == "approved"
    n_parts = sum(len(s["parts"]) for s in v["plan"]["subassemblies"])
    assert len(v["tickets"]) == n_parts + 2 + 1
    assert any(t["title"] == "Oil seal carrier" and t["specialist"] == "chuck" for t in v["tickets"])
    assert v["rollup"]["progress"] == 0 and v["eta"]["low_min"] > 0
    assert sum(v["counts"].values()) == len(v["tickets"])
    # approving twice is refused
    assert c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={}).status_code == 409
    # rename + settings
    v = c.patch(f"/api/office/programs/{pid}", json={"name": "Reducer R1", "concurrency": 5,
                                                       "budget_tokens": 900}).json()
    assert v["name"] == "Reducer R1" and v["concurrency"] == 5 and v["budget"]["tokens"] == 900
    home = c.get("/api/office/home").json()
    assert [x["id"] for x in home["programs"]] == [pid] and len(home["roster"]) == 11
    assert c.delete(f"/api/office/programs/{pid}").status_code == 200
    assert c.get(f"/api/office/programs/{pid}").status_code == 404


def test_api_ticket_moves_milestones_comments_and_events(app_client: Any) -> None:
    from test_platform import signup

    c = app_client
    signup(c, "board@x.com", name="Ada Engineer")
    pid = _create(c)["id"]
    v = c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={}).json()
    part = next(t for t in v["tickets"] if t["kind"] == "part")
    tid = part["id"]
    base = f"/api/office/programs/{pid}/tickets/{tid}"
    assert c.post(base + "/move", json={"column": "nowhere"}).status_code == 409
    v = c.post(base + "/move", json={"column": "in_design"}).json()
    t = next(x for x in v["tickets"] if x["id"] == tid)
    assert t["column"] == "in_design" and t["agent_state"] == "working" and t["progress"] == 0
    for code in ("brief_read", "first_build"):
        v = c.post(base + "/milestones", json={"code": code}).json()
    t = next(x for x in v["tickets"] if x["id"] == tid)
    assert t["progress"] == 35 and t["milestones"] == ["brief_read", "first_build"]
    assert c.post(base + "/milestones", json={"code": "bogus"}).status_code == 409
    v = c.post(base + "/move", json={"column": "approved"}).json()
    t = next(x for x in v["tickets"] if x["id"] == tid)
    assert t["progress"] == 100 and t["agent_state"] == "done"
    # roll-up: exactly this ticket's estimate is done
    total = sum(x["estimate_min"] for x in v["tickets"])
    assert v["rollup"]["done_min"] == pytest.approx(part["estimate_min"])
    assert v["rollup"]["progress"] == round(100 * part["estimate_min"] / total, 1)
    v = c.post(base + "/move", json={"column": "changes_requested"}).json()
    t = next(x for x in v["tickets"] if x["id"] == tid)
    assert t["progress"] == 35 and t["agent_state"] == "blocked"
    v = c.patch(base, json={"complexity": 5, "specialist": "mill"}).json()
    t = next(x for x in v["tickets"] if x["id"] == tid)
    lo, hi = estimates.estimate_range(t["family"], 5, t.get("estimate_path"))
    assert t["specialist"] == "mill" and t["estimate_min"] == round((lo + hi) / 2, 3)
    assert c.patch(base, json={"specialist": "nobody"}).status_code == 409
    assert c.post(base + "/comments", json={"text": "  "}).status_code == 409
    v = c.post(base + "/comments", json={"text": "Keep the bore H7."}).json()
    assert next(x for x in v["tickets"] if x["id"] == tid)["comments"][0]["text"] == "Keep the bore H7."
    # the event log, newest first, in plain language
    acts = c.get(f"/api/office/programs/{pid}/activity").json()["items"]
    types = [a["type"] for a in acts]
    assert types[0] == "ticket.comment" and "ticket.moved" in types and "gate.approved" in types
    moved = next(a for a in acts if a["type"] == "ticket.moved")
    assert moved["actor"] == {"kind": "user", "id": moved["actor"]["id"], "name": "Ada Engineer"}
    assert "Changes requested" in moved["text"] and moved["ticket_id"] == tid
    seqs = [a["seq"] for a in acts]
    assert seqs == sorted(seqs, reverse=True) and len(set(seqs)) == len(seqs)
    newer = c.get(f"/api/office/programs/{pid}/activity?after={seqs[1]}").json()["items"]
    assert [a["seq"] for a in newer] == [seqs[0]]
    # the SSE stream (once: backlog, then close)
    with c.stream("GET", f"/api/office/programs/{pid}/events?once=1") as r:
        body = "".join(r.iter_text())
    evs = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert evs[0]["type"] == "hello" and evs[-1]["type"] == "ticket.comment"
    # reviews inbox and roster
    c.post(base + "/move", json={"column": "in_review"})
    home = c.get("/api/office/home").json()
    assert any(i["kind"] == "ticket" and i["ticket_id"] == tid for i in home["inbox"])
    mill = next(a for a in home["roster"] if a["code"] == "mill")
    assert mill["state"] == "review"
    # all integrated -> the program completes with a milestone event
    for x in c.get(f"/api/office/programs/{pid}").json()["tickets"]:
        v = c.post(f"/api/office/programs/{pid}/tickets/{x['id']}/move", json={"column": "integrated"}).json()
    assert v["status"] == "complete" and v["rollup"]["progress"] == 100.0 and v["eta"]["high_min"] == 0
    assert c.get(f"/api/office/programs/{pid}/activity").json()["items"][0]["type"] == "program.milestone"


def test_api_tenant_isolation_and_viewer(app_client: Any) -> None:
    from sqlalchemy import select
    from test_platform import signup

    from aicad.platform.db import session_factory
    from aicad.platform.models import Membership, User

    c = app_client
    signup(c, "a@x.com", workspace="Org A")
    pid = _create(c)["id"]
    c.post("/api/auth/logout")
    signup(c, "b@x.com", workspace="Org B")
    assert c.get(f"/api/office/programs/{pid}").status_code == 404
    assert c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={}).status_code == 404
    assert c.get(f"/api/office/programs/{pid}/activity").status_code == 404
    assert c.get("/api/office/home").json()["programs"] == []
    assert c.get("/api/office/programs/../../x").status_code == 404
    # a viewer can look but not change
    pid_b = _create(c)["id"]
    db = session_factory()()
    try:
        u = db.scalar(select(User).where(User.email == "b@x.com"))
        m = db.scalar(select(Membership).where(Membership.user_id == u.id))  # type: ignore[union-attr]
        m.role = "viewer"  # type: ignore[union-attr]
        db.commit()
    finally:
        db.close()
    assert c.get(f"/api/office/programs/{pid_b}").json()["can_edit"] is False
    assert c.post(f"/api/office/programs/{pid_b}/gates/brief/approve", json={}).status_code == 403
    assert c.post("/api/office/programs", json={"brief": BRIEF, "planner": "standard"}).status_code == 403


def test_api_archie_plan_is_parsed_metered_or_falls_back(app_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_platform import signup

    calls: list[dict[str, Any]] = []

    async def fake_archie(folder: Path, name: str, brief: str, notes: str = "",
                          budget_usd: float | None = None) -> tuple[str, float | None]:
        calls.append({"folder": folder, "name": name, "notes": notes, "budget": budget_usd})
        return (ARCHIE_TEXT if not notes else "Sorry, no plan this time."), 0.07

    monkeypatch.setattr(planner, "run_agent", fake_archie)
    c = app_client
    signup(c, "archie@x.com")
    before = c.get("/api/auth/me").json()["org"]["token_balance"]
    r = c.post("/api/office/programs", json={"name": "Hand winch", "brief": "Hand winch for 200 kg, wall mounted.",
                                             "planner": "archie"})
    assert r.status_code == 200 and r.json()["status"] == "planning"
    v = _wait_plan(c, r.json()["id"])
    pid = v["id"]
    assert v["status"] == "plan_review" and v["plan"]["source"] == "archie"
    assert [s["name"] for s in v["plan"]["subassemblies"]] == ["Drum", "Frame"]
    assert v["plan"]["narrative"].startswith("I split the winch")
    assert calls[0]["folder"].name == "archie" and calls[0]["budget"] == pytest.approx(2.0)  # 200-token cap
    assert c.get("/api/auth/me").json()["org"]["token_balance"] == before - 7  # $0.07 at $0.01 per token
    assert v["budget"]["planning_tokens"] == 7 and v["budget"]["spent"] == 7
    roster_now = c.get("/api/office/home").json()
    assert any(i["kind"] == "brief" and i["program_id"] == pid for i in roster_now["inbox"])
    # ask for changes: Archie's answer has no usable block -> the standard breakdown, said plainly
    v = c.post(f"/api/office/programs/{pid}/replan", json={"planner": "archie", "notes": "Add a ratchet."}).json()
    assert v["status"] == "planning"
    v = _wait_plan(c, pid)
    assert calls[-1]["notes"] == "Add a ratchet."
    assert v["plan"]["source"] == "standard" and "standard breakdown" in v["plan"]["note"]
    acts = [a["type"] for a in c.get(f"/api/office/programs/{pid}/activity").json()["items"]]
    assert "gate.changes_requested" in acts and acts.count("plan.ready") == 2


def test_api_archie_failure_falls_back(app_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_platform import signup

    async def broken(*a: Any, **k: Any) -> tuple[str, float | None]:
        raise RuntimeError("cli exited")

    monkeypatch.setattr(planner, "run_agent", broken)
    c = app_client
    signup(c, "broken@x.com")
    before = c.get("/api/auth/me").json()["org"]["token_balance"]
    pid = c.post("/api/office/programs", json={"brief": BRIEF, "planner": "archie"}).json()["id"]
    v = _wait_plan(c, pid)
    assert v["plan"]["source"] == "standard" and v["plan"]["note"].startswith("Archie stopped")
    assert c.get("/api/auth/me").json()["org"]["token_balance"] == before  # failures are not charged


def test_api_start_opens_studio_project_and_syncs_milestones(app_client: Any) -> None:
    from test_platform import signup

    from aicad.platform.db import session_factory
    from aicad.platform.models import AgentRun, Project

    c = app_client
    me = signup(c, "start@x.com")
    pid = _create(c)["id"]
    v = c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={}).json()
    part = next(t for t in v["tickets"] if t["kind"] == "part")
    r = c.post(f"/api/office/programs/{pid}/tickets/{part['id']}/start").json()
    proj = r["project_id"]
    assert proj and r["starter_prompt"] == part["brief"] and r["ticket"]["column"] == "in_design"
    p = c.get(f"/api/projects/{proj}").json()
    assert p["name"] == "Gear reducer · " + part["title"]
    again = c.post(f"/api/office/programs/{pid}/tickets/{part['id']}/start").json()
    assert again["project_id"] == proj  # one project per ticket
    # a build in the Studio: first build + checks pass are derived, and the tokens show on the card
    db = session_factory()()
    try:
        row = db.get(Project, proj)
        row.builds, row.last_status = 1, {"ok": True}  # type: ignore[union-attr]
        db.add(AgentRun(org_id=me["org"]["id"], project_id=proj, user_id=me["user"]["id"], kind="new", tokens=42))
        db.commit()
    finally:
        db.close()
    v = c.get(f"/api/office/programs/{pid}").json()
    t = next(x for x in v["tickets"] if x["id"] == part["id"])
    assert t["milestones"] == ["first_build", "gates_pass"] and t["progress"] == 70
    assert t["checks"] == {"ok": True} and t["tokens"] == 42 and v["budget"]["spent"] == 42
    acts = c.get(f"/api/office/programs/{pid}/activity").json()["items"]
    assert acts[0]["actor"]["kind"] == "studio" and "gating checks" in acts[0]["text"]
    # the next build fails a gating check: progress drops back honestly
    db = session_factory()()
    try:
        row = db.get(Project, proj)
        row.builds, row.last_status = 2, {"ok": False}  # type: ignore[union-attr]
        db.commit()
    finally:
        db.close()
    t = next(x for x in c.get(f"/api/office/programs/{pid}").json()["tickets"] if x["id"] == part["id"])
    assert t["progress"] == 35 and t["checks"] == {"ok": False}
    # an integration ticket opens an Assembly Studio document (a trial includes Assembly Studio)
    integ = next(x for x in v["tickets"] if x["kind"] == "integration")
    r = c.post(f"/api/office/programs/{pid}/tickets/{integ['id']}/start").json()
    assert r["assembly_id"] and r["project_id"] is None
    assert c.get(f"/api/m/assembly/assemblies/{r['assembly_id']}").status_code == 200
