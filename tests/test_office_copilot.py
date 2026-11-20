"""Archie as the whole-app copilot and his agentic loop (founder 2026-11-20, PD-226..PD-228)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from test_office import _create, app_client  # noqa: F401  (fixture)

from aicad.office import archie_chat, copilot, supervisor

KNOWN = {"programs": {"prog1": {"name": "Planetary Gearbox", "state": "active"}},
         "projects": {"proj1": {"name": "Motor bracket"}}, "modules": {"drawings": "Drawings"}}
PAGE = {"path": "/app/office/programs/prog1", "title": "Program",
        "targets": [{"id": "talk-archie", "label": "Talk to Archie"}, {"id": "t:Run", "label": "Run"}]}


# ------------------------------------------------------------------ app actions are checked strictly
def test_app_actions_are_checked_against_the_pages_ids_and_controls() -> None:
    ok = copilot.normalise({"type": "navigate", "to": "/app/office/programs/prog1?tab=interfaces&x=1"}, KNOWN)
    assert ok == {"type": "navigate", "to": "/app/office/programs/prog1?tab=interfaces"}
    assert copilot.normalise({"type": "navigate", "to": "/app/office/programs/nope"}, KNOWN) is None
    assert copilot.normalise({"type": "navigate", "to": "https://evil.example"}, KNOWN) is None
    assert copilot.normalise({"type": "navigate", "to": "/app/billing"}, KNOWN) == {"type": "navigate",
                                                                                   "to": "/app/billing"}
    p = copilot.normalise({"type": "point", "target": "run"}, KNOWN, copilot.clean_page(PAGE))
    assert p is not None and p["target"] == "t:Run"
    assert copilot.normalise({"type": "point", "target": "Delete all"}, KNOWN, copilot.clean_page(PAGE)) is None
    h = copilot.normalise({"type": "heal_program", "program": "Planetary Gearbox"}, KNOWN)
    assert h == {"type": "heal_program", "program": "prog1"}
    r = copilot.normalise({"type": "restart_program", "program": "prog1", "brief": "short"}, KNOWN)
    assert r is None and "brief" in copilot.why_not({"type": "restart_program", "program": "prog1"}, KNOWN)
    s = copilot.normalise({"type": "studio_request", "project": "Motor bracket", "text": "add a 6 mm fillet"}, KNOWN)
    assert s is not None and copilot.studio_path(s["project"], s["text"]).startswith("/app/projects/proj1?ask=add%20a")


def test_offline_copilot_opens_named_things_and_pages() -> None:
    t, acts = copilot.offline_reply("open the planetary gearbox please", KNOWN)
    assert acts == [{"type": "navigate", "to": "/app/office/programs/prog1"}]
    t, acts = copilot.offline_reply("where do I top up tokens?", KNOWN)
    assert acts[0]["to"] == "/app/billing" and "Billing" in t


# ------------------------------------------------------------------ the agentic loop
def test_agentic_turn_feeds_rejections_back_until_the_proposal_holds() -> None:
    prompts: list[str] = []
    replies = iter([
        'Open it.\n```fw-office-actions\n[{"type": "navigate", "to": "/app/office/programs/zzz"}]\n```',
        'Opening it.\n```fw-office-actions\n[{"type": "navigate", "to": "/app/office/programs/prog1"}]\n```',
    ])

    async def call(folder: Any, prompt: str, budget: float | None) -> tuple[str, float | None]:
        prompts.append(prompt)
        return next(replies), 0.01

    prose, acts, usd, n = asyncio.run(archie_chat.agentic_turn(call, None, "Engineer: open the gearbox", 1.0,
                                                               lambda o: archie_chat.review(None, o, KNOWN, None)))
    assert n == 2 and acts[0]["to"] == "/app/office/programs/prog1" and prose == "Opening it."
    assert "is not an app page" in prompts[1] and "Your draft answer" in prompts[1]
    assert usd == pytest.approx(0.02)


def test_a_described_change_without_an_action_goes_back() -> None:
    prompts: list[str] = []

    async def call(folder: Any, prompt: str, budget: float | None) -> tuple[str, float | None]:
        prompts.append(prompt)
        return ("I propose revising the layout." if len(prompts) == 1 else
                'Here.\n```fw-office-actions\n[{"type": "heal_program", "program": "prog1"}]\n```'), None

    _p, acts, _u, n = asyncio.run(archie_chat.agentic_turn(call, None, "x", None,
                                                           lambda o: archie_chat.review(None, o, KNOWN, None)))
    assert n == 2 and acts[0]["type"] == "heal_program" and "proposed no action" in prompts[1]


# ------------------------------------------------------------------ the brief is the reference (founder 2026-11-20)
def test_plan_revisions_within_the_brief_are_minor_rework_or_a_named_part_is_major() -> None:
    doc = {"brief": "A planetary gearbox with a sun gear, three planets and a ring gear."}
    a = {"tool": "revise_program", "impact": {"parts": [{"name": "Carrier", "class": "replace", "started": False},
                                                        {"name": "Spacer", "class": "removed", "started": False}]}}
    assert supervisor.classify(doc, a)[0] == "minor"
    a["impact"]["parts"].append({"name": "Sun gear", "class": "redesign", "started": True})
    assert supervisor.classify(doc, a)[0] == "major"
    b = {"tool": "revise_program", "impact": {"parts": [{"name": "Ring gear", "class": "removed", "started": False}]}}
    assert supervisor.classify(doc, b)[0] == "major"
    assert "original brief is a requirement" in archie_chat.CHAT_INSTRUCTIONS
    assert "original brief" in supervisor.SUPERVISOR_INSTRUCTIONS


def test_amend_brief_needs_a_reason_and_is_applied_by_the_engineer(app_client: Any,  # noqa: F811
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    from test_platform import signup

    async def fake_chat(folder: Any, prompt: str, budget_usd: float | None = None) -> tuple[str, float | None]:
        return ('A 20:1 ratio in one planetary stage can\'t work.\n```fw-office-actions\n[{"type": "amend_brief", '
                '"change": "Ratio 20:1 in two planetary stages", "reason": "one stage tops out near 10:1"}, '
                '{"type": "point", "target": "Run", "note": "then run"}]\n```'), 0.02

    monkeypatch.setattr(archie_chat, "run_chat", fake_chat)
    c = app_client
    signup(c, "brief@x.com")
    pid = _create(c)["id"]
    c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={})
    r = c.post(f"/api/office/programs/{pid}/archie", json={"text": "Can it do 20:1?", "page": {
        "path": f"/app/office/programs/{pid}", "targets": [{"id": "run-office", "label": "Run"}]}})
    assert r.status_code == 200, r.text
    m = r.json()["messages"][-1]
    assert [a["type"] for a in m["actions"]] == ["amend_brief", "point"]
    assert m["actions"][1]["target"] == "run-office"
    before = c.get(f"/api/office/programs/{pid}").json()["brief"]
    out = c.post(f"/api/office/programs/{pid}/archie/actions", json={"message": m["id"], "action": "a1"})
    assert out.status_code == 200, out.text
    brief = out.json()["program"]["brief"]
    assert brief.startswith(before.rstrip()) and "Ratio 20:1 in two planetary stages" in brief


# ------------------------------------------------------------------ the global copilot thread
def test_copilot_outside_a_program_navigates_and_starts_a_program(app_client: Any,  # noqa: F811
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    from test_platform import signup

    from aicad.platform.routers import copilot as routes

    async def fake(folder: Any, prompt: str, budget_usd: float | None = None) -> tuple[str, float | None]:
        assert "Pages:" in prompt and "The engineer is on: /app/projects" in prompt
        return ('Billing is where tokens live; I can also start the program.\n```fw-office-actions\n'
                '[{"type": "navigate", "to": "/app/billing", "highlight": "Buy tokens"}, '
                '{"type": "new_program", "name": "Winch", "brief": "A hand winch for 200 kg with a ratchet and a '
                'drum of 80 mm"}]\n```'), 0.01

    monkeypatch.setattr(routes, "run_copilot", fake)
    c = app_client
    signup(c, "copilot@x.com")
    r = c.post("/api/copilot", json={"text": "tokens? and start a winch", "page": {"path": "/app/projects"}})
    assert r.status_code == 200, r.text
    m = r.json()["messages"][-1]
    assert [a["type"] for a in m["actions"]] == ["navigate", "new_program"]
    assert m["actions"][0]["label"] == "Open /app/billing and show Buy tokens"
    out = c.post("/api/copilot/actions", json={"message": m["id"], "action": "a2"})
    assert out.status_code == 200, out.text
    assert out.json()["navigate"].startswith("/app/office/programs/")
    assert c.get("/api/copilot").json()["messages"][-1]["actions"][1]["status"] == "applied"


def test_archie_runs_the_design_agent_only_when_the_engineer_applies(app_client: Any,  # noqa: F811
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    from test_platform import signup

    from aicad.platform.routers import copilot as routes
    from aicad.platform.routers import projects

    runs: list[tuple[str, str]] = []

    async def fake_agent(project_id: str, body: Any, ctx: Any) -> dict[str, Any]:
        runs.append((project_id, body.prompt))
        return {"accepted": True}

    monkeypatch.setattr(projects, "agent_chat", fake_agent)
    c = app_client
    signup(c, "runagent@x.com")
    pid = c.post("/api/projects", json={"name": "Motor bracket"}).json()["id"]

    async def fake(folder: Any, prompt: str, budget_usd: float | None = None) -> tuple[str, float | None]:
        return (f'I will thicken it.\n```fw-office-actions\n[{{"type": "studio_request", "project": "{pid}", '
                '"text": "Make the base 8 mm thick"}]\n```'), 0.01

    monkeypatch.setattr(routes, "run_copilot", fake)
    m = c.post("/api/copilot", json={"text": "make the bracket stiffer"}).json()["messages"][-1]
    assert m["actions"][0]["label"] == "Run the design agent on Motor bracket: Make the base 8 mm thick"
    assert not runs  # proposed, not run
    out = c.post("/api/copilot/actions", json={"message": m["id"], "action": "a1"}).json()
    assert runs == [(pid, "Make the base 8 mm thick")] and out["navigate"] == f"/app/projects/{pid}"
