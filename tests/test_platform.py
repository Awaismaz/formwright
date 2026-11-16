"""Platform tests: auth journey, onboarding, billing (simulated), team, permissions, God mode, admin.

No AI calls are made: agent runs are only exercised up to the paywall/preflight decision.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from aicad.platform import config
from aicad.platform.db import session_factory
from aicad.platform.models import EmailToken, Organization, Outbox, User

ADMIN = "boss@example.com"
PW = "correct horse 42"


@pytest.fixture()
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from aicad.platform.routers import auth as auth_router

    auth_router._attempts.clear()
    monkeypatch.setenv("FW_ADMIN_PASSWORD", PW)
    config.override_settings(config.Settings(
        env="development", data_dir=tmp_path / "data", database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
        app_url="http://testserver", superadmin_emails=(ADMIN,), stripe_secret_key="", trial_tokens=300))
    from aicad.platform.app import create_app

    with TestClient(create_app()) as c:  # one persistent event loop, like the real server (background tasks run)
        c.headers.update({"X-FW-CSRF": "1"})
        yield c
    from aicad.agent import worker

    for w in worker._workers.values():  # test-only cleanup: event loops of TestClient are short-lived
        if w.proc is not None and w.proc.returncode is None:
            w.proc.kill()
        w.proc = None
    worker._workers.clear()


def _link_token(email: str, subject_part: str) -> str:
    db = session_factory()()
    try:
        row = db.scalars(select(Outbox).where(Outbox.to == email, Outbox.subject.contains(subject_part))
                         .order_by(Outbox.created_at.desc())).first()
        assert row is not None and row.link
        return row.link.split("token=")[1]
    finally:
        db.close()


def signup(c: TestClient, email: str, name: str = "Ada Engineer", verify: bool = True,
           workspace: str | None = "Ada Design Co") -> dict[str, Any]:
    r = c.post("/api/auth/signup", json={"name": name, "email": email, "password": PW})
    assert r.status_code == 200, r.text
    if verify:
        assert c.post("/api/auth/verify-email", json={"token": _link_token(email, "Verify")}).status_code == 200
    if workspace:
        r = c.post("/api/onboarding", json={"role": "Design engineer", "company_size": "2-10",
                                            "cad_tools": ["SOLIDWORKS"], "goals": ["faster concepts"],
                                            "units": "mm", "workspace_name": workspace})
        assert r.status_code == 200, r.text
    return c.get("/api/auth/me").json()


def admin(c: TestClient, workspace: str = "Founder Labs") -> dict[str, Any]:
    """The founder super-admin is auto-created at startup; sign in and set up a workspace."""
    assert c.post("/api/auth/login", json={"email": ADMIN, "password": PW}).status_code == 200
    c.post("/api/onboarding", json={"role": "Founder", "workspace_name": workspace})
    return c.get("/api/auth/me").json()


def test_csrf_header_required(app_client: TestClient) -> None:
    r = app_client.post("/api/auth/login", json={"email": "x@y.com", "password": "x"}, headers={"X-FW-CSRF": ""})
    assert r.status_code == 403


def test_security_headers(app_client: TestClient) -> None:
    r = app_client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY" and "default-src 'self'" in r.headers["content-security-policy"]


def test_signup_journey_steps(app_client: TestClient) -> None:
    c = app_client
    assert c.post("/api/auth/signup", json={"name": "A", "email": "bad", "password": PW}).status_code == 422
    assert c.post("/api/auth/signup", json={"name": "A", "email": "a@x.com", "password": "short"}).status_code == 422
    c.post("/api/auth/signup", json={"name": "Ada", "email": "ada@x.com", "password": PW})
    me = c.get("/api/auth/me").json()
    assert me["next_step"] == "onboarding" and me["user"]["verify_by"]  # first-day grace, with a reminder
    assert c.get("/api/projects").status_code == 409  # no workspace yet (not 403: unverified is allowed in)
    c.post("/api/auth/verify-email", json={"token": _link_token("ada@x.com", "Verify")})
    me = c.get("/api/auth/me").json()
    assert me["next_step"] == "onboarding" and me["org"] is None
    c.post("/api/onboarding", json={"role": "Engineer", "workspace_name": "Ada Co"})
    me = c.get("/api/auth/me").json()
    assert me["next_step"] == "app"
    assert me["org"]["plan_code"] == "trial" and me["org"]["token_balance"] == 300
    live = {k for k, m in __import__("aicad.platform.catalog", fromlist=["MODULES"]).MODULES.items()
            if m["status"] == "live"}
    assert set(me["org"]["modules"]) == live and me["org"]["role"] == "owner"  # the trial tries every module
    cl = c.get("/api/checklist").json()
    keys = [i["key"] for i in cl["items"]]
    assert "plan" not in keys and "team" not in keys  # no sales item; no invite on a one-seat trial
    assert cl["done"] >= 1 and cl["hidden"] is False
    assert c.post("/api/auth/signup", json={"name": "Ada", "email": "ada@x.com", "password": PW}).status_code == 409


def test_login_logout_and_password_reset(app_client: TestClient) -> None:
    c = app_client
    signup(c, "bob@x.com")
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").json()["user"] is None
    assert c.post("/api/auth/login", json={"email": "bob@x.com", "password": "wrong password 1"}).status_code == 401
    c.post("/api/auth/forgot-password", json={"email": "bob@x.com"})
    tok = _link_token("bob@x.com", "Reset")
    assert c.post("/api/auth/reset-password", json={"token": tok, "password": "new password 99"}).status_code == 200
    assert c.post("/api/auth/reset-password", json={"token": tok, "password": "new password 98"}).status_code == 400
    assert c.post("/api/auth/login", json={"email": "bob@x.com", "password": "new password 99"}).status_code == 200


def test_simulated_billing_plan_addon_topup(app_client: TestClient) -> None:
    c = app_client
    signup(c, "pay@x.com")
    cat = c.get("/api/billing/catalog").json()
    assert {p["code"] for p in cat["plans"]} >= {"trial", "pro", "team", "enterprise"}
    assert cat["stripe_mode"] == "simulated"
    r = c.post("/api/billing/checkout", json={"product_code": "pro"}).json()
    assert r["provider"] == "simulated" and r["url"].startswith("/app/checkout/")
    pid = r["payment_id"]
    assert c.get(f"/api/billing/payments/{pid}").json()["status"] == "pending"
    assert c.post(f"/api/billing/payments/{pid}/simulate", json={"outcome": "success"}).json()["status"] == "paid"
    assert c.post(f"/api/billing/payments/{pid}/simulate", json={"outcome": "success"}).status_code == 409
    org = c.get("/api/auth/me").json()["org"]
    assert org["plan_code"] == "pro" and org["plan_status"] == "active" and org["token_balance"] == 1800
    assert "drawings" in org["modules"]
    pid = c.post("/api/billing/checkout", json={"product_code": "addon_manufacturing"}).json()["payment_id"]
    c.post(f"/api/billing/payments/{pid}/simulate", json={"outcome": "success"})
    assert "manufacturing" in c.get("/api/auth/me").json()["org"]["modules"]
    assert c.post("/api/billing/checkout", json={"product_code": "addon_manufacturing"}).status_code == 409
    pid = c.post("/api/billing/checkout", json={"product_code": "tokens_500"}).json()["payment_id"]
    c.post(f"/api/billing/payments/{pid}/simulate", json={"outcome": "fail"})
    assert c.get("/api/auth/me").json()["org"]["token_balance"] == 1800
    pid = c.post("/api/billing/checkout", json={"product_code": "tokens_500"}).json()["payment_id"]
    c.post(f"/api/billing/payments/{pid}/simulate", json={"outcome": "success"})
    ov = c.get("/api/billing").json()
    assert ov["org"]["token_balance"] == 2300
    assert [p["status"] for p in ov["payments"]].count("paid") == 3
    assert c.post("/api/billing/checkout", json={"product_code": "enterprise"}).status_code == 404
    assert c.post("/api/billing/checkout", json={"product_code": "trial"}).status_code == 404


def test_team_invites_seats_and_roles(app_client: TestClient, tmp_path: Path) -> None:
    owner = app_client
    signup(owner, "owner@x.com")
    assert owner.post("/api/team/invites", json={"email": "eng@x.com", "role": "engineer"}).status_code == 402
    pid = owner.post("/api/billing/checkout", json={"product_code": "team"}).json()["payment_id"]
    owner.post(f"/api/billing/payments/{pid}/simulate", json={"outcome": "success"})
    assert owner.post("/api/team/invites", json={"email": "eng@x.com", "role": "owner"}).status_code == 422
    assert owner.post("/api/team/invites", json={"email": "eng@x.com", "role": "viewer"}).status_code == 200
    tok = _link_token("eng@x.com", "invited you")
    from aicad.platform.app import create_app  # noqa: F401  (same app instance via app_client)

    guest = TestClient(owner.app)
    guest.headers.update({"X-FW-CSRF": "1"})
    guest.post("/api/auth/signup", json={"name": "Eve", "email": "eng@x.com", "password": PW})
    me = guest.post("/api/team/invites/accept", json={"token": tok}).json()
    assert me["org"]["role"] == "viewer" and me["next_step"] == "app"
    assert guest.post("/api/billing/checkout", json={"product_code": "tokens_500"}).status_code == 403
    assert guest.post("/api/projects", json={"name": "x"}).status_code == 403
    assert guest.post("/api/team/invites", json={"email": "z@x.com"}).status_code == 403
    members = owner.get("/api/team").json()["members"]
    assert len(members) == 2
    eve = next(m for m in members if m["email"] == "eng@x.com")
    assert owner.patch(f"/api/team/members/{eve['id']}", json={"role": "engineer"}).status_code == 200
    me_owner = next(m for m in members if m["email"] == "owner@x.com")
    assert owner.delete(f"/api/team/members/{me_owner['id']}").status_code == 409  # last owner


def test_projects_crud_and_paywall(app_client: TestClient) -> None:
    c = app_client
    signup(c, "proj@x.com")
    r = c.post("/api/projects", json={"name": "Bracket", "template": "bracket"}).json()
    assert r["starter_prompt"] and r["template"] == "bracket"
    pid = r["id"]
    assert len(c.get("/api/projects").json()["items"]) == 1
    detail = c.get(f"/api/projects/{pid}").json()
    assert detail["agent"]["allowed"] is True
    assert c.get(f"/api/projects/{pid}/files/model.py").status_code == 404
    assert c.get(f"/api/projects/{pid}/files/..%2F..%2Fdb.sqlite").status_code == 404
    db = session_factory()()
    org = db.scalar(select(Organization))
    org.token_balance = 3
    db.commit()
    db.close()
    r = c.post(f"/api/projects/{pid}/agent/chat", json={"prompt": "make it"})
    assert r.status_code == 402 and "tokens" in r.json()["detail"]["message"]
    assert c.patch(f"/api/projects/{pid}", json={"archived": True}).status_code == 200
    assert c.get("/api/projects").json()["items"] == []
    assert c.delete(f"/api/projects/{pid}").status_code == 200


def test_god_mode_requires_superadmin(app_client: TestClient) -> None:
    c = app_client
    signup(c, "normal@x.com")
    assert c.get("/api/god").status_code == 404
    assert c.get("/api/auth/me").json()["god"] == {}
    assert c.get("/api/admin/overview").status_code == 403


def test_god_mode_scenarios_and_bypass(app_client: TestClient) -> None:
    c = app_client
    admin(c)
    g = c.get("/api/god").json()
    assert "trial_low_tokens" in {s["code"] for s in g["scenarios"]}
    c.post("/api/god/scenario", json={"scenario": "trial_low_tokens"})
    assert c.get("/api/auth/me").json()["org"]["token_balance"] == 12
    pid = c.post("/api/projects", json={"name": "P"}).json()["id"]
    assert c.get(f"/api/projects/{pid}").json()["agent"]["allowed"] is False  # 12 < the 20-token minimum
    c.post("/api/god/scenario", json={"scenario": "trial_expired"})
    assert c.get(f"/api/projects/{pid}").json()["agent"]["allowed"] is False
    c.patch("/api/god", json={"enabled": True, "bypass_paywall": True, "bypass_tokens": True})
    assert c.get(f"/api/projects/{pid}").json()["agent"]["allowed"] is True
    c.post("/api/god/scenario", json={"scenario": "all_modules"})
    assert len(c.get("/api/auth/me").json()["org"]["modules"]) == 8
    c.post("/api/god/scenario", json={"scenario": "fresh_signup"})
    assert c.get("/api/auth/me").json()["next_step"] == "onboarding"  # unverified, inside the first-day grace
    c.post("/api/god/scenario", json={"scenario": "verify_overdue"})
    assert c.get("/api/auth/me").json()["next_step"] == "verify_email"
    c.patch("/api/god", json={"skip_verification": True})
    assert c.get("/api/auth/me").json()["next_step"] == "onboarding"
    c.patch("/api/god", json={"skip_onboarding": True})
    assert c.get("/api/auth/me").json()["next_step"] == "app"


def test_god_mode_disabled_in_production(app_client: TestClient, tmp_path: Path) -> None:
    admin(app_client)
    s = config.get_settings()
    config.override_settings(config.Settings(**{**s.__dict__, "env": "production", "stripe_secret_key": "sk_test_x"}))
    try:
        assert app_client.get("/api/god").status_code == 404
        assert app_client.get("/api/auth/me").json()["god"] == {}
    finally:
        config.override_settings(s)


def test_admin_console_and_impersonation(app_client: TestClient) -> None:
    c = app_client
    admin(c)
    other = TestClient(c.app)
    other.headers.update({"X-FW-CSRF": "1"})
    signup(other, "cust@x.com", name="Customer", workspace="Cust Co")
    ov = c.get("/api/admin/overview").json()
    assert ov["kpis"]["users"] == 2 and ov["funnel"][0]["users"] == 1  # founder was auto-created, not signed up
    users = c.get("/api/admin/users", params={"q": "cust"}).json()["items"]
    assert len(users) == 1
    uid = users[0]["id"]
    org_id = users[0]["orgs"][0]["id"]
    assert c.post(f"/api/admin/orgs/{org_id}/tokens", json={"amount": 1000, "note": "pilot"}).json()["balance"] == 1300
    c.post(f"/api/admin/orgs/{org_id}/modules", json={"module": "assembly", "enabled": True})
    assert "assembly" in other.get("/api/auth/me").json()["org"]["modules"]
    c.patch("/api/admin/catalog/pro", json={"price_cents": 5900})
    assert next(p for p in c.get("/api/billing/catalog").json()["plans"] if p["code"] == "pro")["price_cents"] == 5900
    c.post(f"/api/admin/users/{uid}/impersonate")
    me = c.get("/api/auth/me").json()
    assert me["user"]["email"] == "cust@x.com" and me["impersonating"]["actor_email"] == ADMIN
    c.post("/api/admin/stop-impersonation")
    assert c.get("/api/auth/me").json()["user"]["email"] == ADMIN
    assert any(a["action"] == "admin.impersonate" for a in c.get("/api/admin/audit").json()["items"])
    assert c.get("/api/admin/outbox").json()["items"]
    c.patch(f"/api/admin/users/{uid}", json={"disabled": True})
    assert other.get("/api/auth/me").json()["user"] is None


def test_seed_demo_builds_real_parts(app_client: TestClient) -> None:
    c = app_client
    admin(c)
    r = c.post("/api/god/seed-demo").json()
    assert r["projects_created"] == 4
    items = c.get("/api/projects").json()["items"]
    assert len(items) == 4
    assert all(p["last_status"].get("ok") for p in items), [(p["name"], p["last_status"]) for p in items]
    assert len(c.get("/api/team").json()["members"]) == 4
    pid = items[0]["id"]
    assert c.get(f"/api/projects/{pid}/files/part.step").status_code == 200
    assert c.get(f"/api/projects/{pid}/revisions").json()["items"][0]["n"] == 1
    assert c.post("/api/god/reset-demo").json()["projects_removed"] == 4


def test_email_tokens_are_hashed(app_client: TestClient) -> None:
    signup(app_client, "hash@x.com", verify=False, workspace=None)
    tok = _link_token("hash@x.com", "Verify")
    db = session_factory()()
    rows = db.scalars(select(EmailToken)).all()
    assert rows and all(r.token_hash != tok for r in rows)
    assert db.scalar(select(User).where(User.email == "hash@x.com")).password_hash.startswith("$argon2")
    db.close()


def _project_with_model(c: TestClient, script: str) -> tuple[str, Path]:
    from aicad.platform.models import Project
    from aicad.platform.routers.projects import workspace_for

    pid = c.post("/api/projects", json={"name": "Plate"}).json()["id"]
    db = session_factory()()
    ws = workspace_for(db.get(Project, pid))
    db.close()
    (ws / "model.py").write_text(script, encoding="utf-8")
    import subprocess
    import sys

    subprocess.run([sys.executable, "-I", "-m", "aicad.agent.runner", str(ws / "model.py"), str(ws / "out")],
                   cwd=ws, timeout=180, check=True)  # first build records the declared PARAMS
    return pid, ws


def test_param_edit_rebuilds_without_ai_and_rolls_back_on_failure(app_client: TestClient) -> None:
    c = app_client
    signup(c, "params@x.com")
    demo = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo" / "mounting_plate.py"
    pid, ws = _project_with_model(c, demo.read_text(encoding="utf-8"))
    editable = c.get(f"/api/projects/{pid}/params").json()["editable"]
    assert editable["L"] == 120.0 and editable["CH"] == 1.0 and "PL" in editable
    assert "math" not in editable and len(editable) == 10
    before = c.get("/api/auth/me").json()["org"]["token_balance"]
    r = c.post(f"/api/projects/{pid}/params", json={"values": {"L": 150}})
    assert r.status_code == 200, r.text
    assert r.json()["changed"]["L"] == {"from": 120.0, "to": 150.0}
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["ok"] and st["fingerprint"]["bbox"][0] == 150.0
    assert c.get("/api/auth/me").json()["org"]["token_balance"] == before  # no tokens spent
    # pocket deeper than the plate -> geometry/check failure -> restored
    r = c.post(f"/api/projects/{pid}/params", json={"values": {"PD": 12}})
    assert r.status_code == 422 and "restored" in r.json()["detail"]
    assert "L = 150.0" in (ws / "model.py").read_text(encoding="utf-8")
    assert c.post(f"/api/projects/{pid}/params", json={"values": {"NOPE": 1}}).status_code == 422
    assert c.get(f"/api/projects/{pid}/revisions").json()["items"][0]["n"] >= 1


def test_agent_result_event_debits_tokens(app_client: TestClient) -> None:
    from aicad.platform.routers.projects import _on_event

    c = app_client
    me = signup(c, "meter@x.com")
    pid = c.post("/api/projects", json={"name": "Meter"}).json()["id"]
    ev = {"type": "result", "subtype": "success", "turns": 3, "cost_est_usd": 0.2401}
    _on_event(pid, me["user"]["id"], god_tokens=False)(ev)
    assert ev["tokens_charged"] == 25
    assert c.get("/api/auth/me").json()["org"]["token_balance"] == 275
    ledger = c.get("/api/billing").json()["ledger"]
    assert ledger[0]["reason"] == "usage" and ledger[0]["delta"] == -25
    ev2 = {"type": "result", "subtype": "success", "turns": 1, "cost_est_usd": 0.5}
    _on_event(pid, me["user"]["id"], god_tokens=True)(ev2)
    assert ev2["tokens_charged"] == 0 and c.get("/api/auth/me").json()["org"]["token_balance"] == 275


def test_param_edit_keeps_integers(app_client: TestClient) -> None:
    c = app_client
    signup(c, "ints@x.com")
    demo = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo" / "pipe_flange.py"
    pid, ws = _project_with_model(c, demo.read_text(encoding="utf-8"))
    assert c.post(f"/api/projects/{pid}/params", json={"values": {"N_BOLTS": 6.5}}).status_code == 422
    r = c.post(f"/api/projects/{pid}/params", json={"values": {"N_BOLTS": 8}})
    assert r.status_code == 200, r.text
    assert "N_BOLTS = 8\n" in (ws / "model.py").read_text(encoding="utf-8")


# ------------------------------------------------------------------ platform polish: metering, budgets, trial,
# grace, notifications, plan switches, seats, duplicate, catalog upgrades


def _org_id() -> str:
    db = session_factory()()
    try:
        return db.scalars(select(Organization)).all()[-1].id
    finally:
        db.close()


def test_usage_pricing_and_token_rounding() -> None:
    from aicad.agent.pricing import usage_cost_usd
    from aicad.platform.metering import tokens_for_usd

    assert usage_cost_usd("claude-opus-5-5", {"input_tokens": 1_000_000}) == pytest.approx(4.0)
    assert usage_cost_usd("claude-sonnet-4-6", {"output_tokens": 1_000_000}) == pytest.approx(15.0)
    # cache writes cost 1.25x input; cache reads are cheap; an unknown model is priced like Opus (stops early)
    assert usage_cost_usd("claude-opus-4-7", {"cache_creation_input_tokens": 1_000_000}) == pytest.approx(6.25)
    assert usage_cost_usd("mystery-model", {"input_tokens": 1_000_000}) == pytest.approx(5.0)
    assert tokens_for_usd(2.5981674) == 260 and tokens_for_usd(0.0) == 1 and tokens_for_usd(0.30) == 30


def test_session_charges_each_run_not_the_cumulative_cost(tmp_path: Path) -> None:
    """The agent's cost report is cumulative over a connected session: run 2 must be charged its own cost."""
    from claude_agent_sdk import AssistantMessage, ResultMessage

    from aicad.agent.session import AgentSession

    events: list[dict[str, Any]] = []
    s = AgentSession(tmp_path / "ws", on_event=events.append)

    def result(total: float) -> ResultMessage:
        return ResultMessage(subtype="success", duration_ms=1000, duration_api_ms=900, is_error=False, num_turns=2,
                             session_id="s1", total_cost_usd=total)

    s._handle(result(2.60))
    s._handle(result(3.50))
    costs = [e["cost_est_usd"] for e in events if e["type"] == "result"]
    assert costs[0] == pytest.approx(2.60) and costs[1] == pytest.approx(0.90)

    # live meter: one entry per model response (repeated messages of a response are not double counted)
    s.run_budget_usd, s._run_costs, s._budget_hit = 0.05, {}, False
    usage = {"input_tokens": 2000, "output_tokens": 500, "cache_read_input_tokens": 30000}
    for _ in range(2):
        s._handle(AssistantMessage(content=[], model="claude-opus-4-7", usage=usage, message_id="r1"))
    meters = [e for e in events if e["type"] == "meter"]
    assert len(meters) == 1 and meters[0]["spent_usd"] == pytest.approx(0.0375) and not s._budget_hit
    s._handle(AssistantMessage(content=[], model="claude-opus-4-7", usage=usage, message_id="r2"))
    assert s._budget_hit  # 0.075 >= 0.05: the run loop interrupts the agent
    assert not any(e["type"] == "meter" for e in s.history)  # the meter is live-only, never persisted


def test_run_budget_caps_the_charge_and_never_overdraws(app_client: TestClient) -> None:
    from aicad.platform import metering
    from aicad.platform.routers.projects import _on_event

    c = app_client
    me = signup(c, "budget@x.com")
    pid = c.post("/api/projects", json={"name": "Budget"}).json()["id"]
    assert c.get("/api/billing").json()["run_budget"]["tokens"] == metering.DEFAULT_RUN_BUDGET
    assert c.patch("/api/billing/run-budget", json={"tokens": 10}).status_code == 422
    assert c.patch("/api/billing/run-budget", json={"tokens": 120}).status_code == 200
    est = c.get(f"/api/projects/{pid}/estimate").json()
    assert est["budget"] == 120 and est["kind"] == "new" and est["typical"] == metering.DEFAULT_ESTIMATE["new"]["typical"]
    # a run that would cost 2.6 USD (260 tokens) is charged at most its 120-token budget
    ev = {"type": "result", "subtype": "success", "turns": 3, "cost_est_usd": 2.6, "budget_tokens": 120,
          "budget_stopped": True}
    _on_event(pid, me["user"]["id"], god_tokens=False)(ev)
    assert ev["tokens_charged"] == 120 and c.get("/api/auth/me").json()["org"]["token_balance"] == 180
    # the budget never exceeds the balance that other running runs have not reserved
    oid = _org_id()
    metering.reserve(oid, "other-run", 170)
    try:
        assert c.get(f"/api/projects/{pid}/estimate").json()["budget"] is None  # 180 - 170 < 20
        r = c.post(f"/api/projects/{pid}/agent/chat", json={"prompt": "make it"})
        assert r.status_code == 402 and "Another design run" in r.json()["detail"]["message"]
    finally:
        metering.release(oid, "other-run")
    assert c.get(f"/api/projects/{pid}/estimate").json()["budget"] == 120
    notes = c.get("/api/notifications").json()["items"]
    assert any("stopped at the run budget" in n["title"] for n in notes)


def test_estimate_learns_from_the_workspace(app_client: TestClient) -> None:
    from aicad.platform.models import AgentRun, Project

    c = app_client
    signup(c, "learn@x.com")
    pid = c.post("/api/projects", json={"name": "Learn"}).json()["id"]
    oid = _org_id()
    db = session_factory()()
    for t in (90, 110, 130):
        db.add(AgentRun(org_id=oid, project_id=pid, kind="new", brief_chars=200, tokens=t, status="ok"))
    db.commit()
    est = c.get(f"/api/projects/{pid}/estimate?chars=200").json()
    assert est["basis"] == "workspace" and est["typical"] == 110 and est["samples"] == 3
    p = db.get(Project, pid)
    p.builds = 1  # an existing part: the next run is a change, still on the default until it has history
    db.commit()
    db.close()
    est = c.get(f"/api/projects/{pid}/estimate").json()
    assert est["kind"] == "change" and est["basis"] == "typical"


def test_trial_uses_every_live_module_until_it_ends(app_client: TestClient) -> None:
    c = app_client
    signup(c, "trial@x.com")
    assert c.get("/api/m/mesh/presets").status_code == 200  # a trial can open any live module
    me = c.get("/api/auth/me").json()
    assert "drawings" in me["org"]["modules"] and "mesh" in me["org"]["modules"]
    db = session_factory()()
    org = db.get(Organization, me["org"]["id"])
    from datetime import timedelta

    from aicad.platform.db import utcnow
    org.trial_ends_at = utcnow() - timedelta(days=1)
    db.commit()
    db.close()
    me = c.get("/api/auth/me").json()
    assert me["org"]["modules"] == ["design"]  # parts and the Studio stay open; other modules lock
    assert c.get("/api/m/mesh/presets").status_code == 402


def test_unverified_grace_then_wall(app_client: TestClient) -> None:
    from datetime import timedelta

    from aicad.platform.db import utcnow

    c = app_client
    me = signup(c, "grace@x.com", verify=False)
    assert me["next_step"] == "app" and me["user"]["email_verified"] is False
    pid = c.post("/api/projects", json={"name": "Grace"}).json()["id"]
    assert c.get(f"/api/projects/{pid}").json()["agent"]["allowed"] is True
    est = c.get(f"/api/projects/{pid}/estimate").json()
    assert est["budget"] == 300  # an unconfirmed account may spend about one first part
    assert c.post("/api/billing/checkout", json={"product_code": "tokens_500"}).status_code == 403
    assert c.post("/api/team/invites", json={"email": "t@x.com"}).status_code == 403
    db = session_factory()()
    u = db.scalar(select(User).where(User.email == "grace@x.com"))
    u.created_at = utcnow() - timedelta(hours=25)
    db.commit()
    db.close()
    assert c.get("/api/auth/me").json()["next_step"] == "verify_email"
    assert c.get("/api/projects").status_code == 403


def test_revision_by_someone_else_notifies_the_creator(app_client: TestClient) -> None:
    from aicad.platform.models import Membership, Notification, Project
    from aicad.platform.services import notify_revision

    c = app_client
    signup(c, "owner@x.com")
    pid = c.post("/api/projects", json={"name": "Shared bracket"}).json()["id"]
    db = session_factory()()
    p = db.get(Project, pid)
    owner = db.get(User, p.created_by)
    other = User(email="mate@x.com", name="Mate", password_hash="x")
    db.add(other)
    db.flush()
    db.add(Membership(user_id=other.id, org_id=p.org_id, role="engineer"))
    notify_revision(db, p, 3, owner, "own change")  # your own change: no notification
    notify_revision(db, p, 4, other, "Parameters changed: THICKNESS 6 → 8")
    db.commit()
    rows = db.scalars(select(Notification).where(Notification.user_id == owner.id)).all()
    db.close()
    hits = [n for n in rows if "Mate changed Shared bracket" in n.title]
    assert len(hits) == 1 and hits[0].link == f"/app/projects/{pid}" and "Revision 4" in hits[0].body


def test_plan_switch_prorates_cancels_included_addons_and_warns_on_seats(app_client: TestClient) -> None:
    c = app_client
    signup(c, "switch@x.com")

    def pay(code: str) -> dict[str, Any]:
        r = c.post("/api/billing/checkout", json={"product_code": code}).json()
        if r["provider"] == "simulated":
            assert c.post(f"/api/billing/payments/{r['payment_id']}/simulate",
                          json={"outcome": "success"}).status_code == 200
        return r

    pay("pro")
    pay("addon_assembly")
    pv = c.post("/api/billing/preview", json={"product_code": "team"}).json()
    assert pv["direction"] == "up" and 4800 <= pv["unused_credit_cents"] <= 4900
    assert pv["charge_cents"] == 19900 - pv["unused_credit_cents"]
    assert [a["module"] for a in pv["cancels_addons"]] == ["assembly"]
    r = pay("team")
    bill = c.get("/api/billing").json()
    paid = next(p for p in bill["payments"] if p["product_code"] == "team")
    assert paid["amount_cents"] == pv["charge_cents"]
    assert "assembly" not in bill["addons"] and "assembly" in bill["org"]["modules"]  # now via the plan
    receipt = c.get(f"/api/billing/payments/{r['payment_id']}/receipt")
    assert receipt.status_code == 200 and "Simulated payment" in receipt.text and "Team" in receipt.text
    # downgrading with more members than the new plan's seats is allowed, with a warning
    db = session_factory()()
    from aicad.platform.models import Membership

    oid = c.get("/api/auth/me").json()["org"]["id"]
    for i in range(2):
        u = User(email=f"m{i}@x.com", name=f"M{i}", password_hash="x")
        db.add(u)
        db.flush()
        db.add(Membership(user_id=u.id, org_id=oid, role="engineer"))
    db.commit()
    db.close()
    down = c.post("/api/billing/preview", json={"product_code": "pro"}).json()
    assert down["direction"] == "down" and down["seats"]["over"] == 2 and down["charge_cents"] == 0
    assert down["leftover_credit_cents"] > 0  # unused Team time beyond the Pro price stays as account credit


def test_extra_seat_addon_on_team_only(app_client: TestClient) -> None:
    c = app_client
    signup(c, "seats@x.com")
    cat = c.get("/api/billing/catalog").json()
    assert cat["seats"][0]["code"] == "seat_team" and cat["seats"][0]["price_cents"] == 3900
    assert c.post("/api/billing/checkout", json={"product_code": "seat_team"}).status_code == 409
    r = c.post("/api/billing/checkout", json={"product_code": "team"}).json()
    c.post(f"/api/billing/payments/{r['payment_id']}/simulate", json={"outcome": "success"})
    r = c.post("/api/billing/checkout", json={"product_code": "seat_team"}).json()
    c.post(f"/api/billing/payments/{r['payment_id']}/simulate", json={"outcome": "success"})
    assert c.get("/api/auth/me").json()["org"]["seat_limit"] == 6
    assert c.delete("/api/billing/seats").status_code == 200
    assert c.get("/api/auth/me").json()["org"]["seat_limit"] == 5


def test_duplicate_project_copies_the_model_not_the_conversation(app_client: TestClient) -> None:
    from aicad.platform.models import Project
    from aicad.platform.routers.projects import workspace_for

    c = app_client
    signup(c, "dup@x.com")
    pid = c.post("/api/projects", json={"name": "Bracket"}).json()["id"]
    db = session_factory()()
    ws = workspace_for(db.get(Project, pid))
    db.close()
    (ws / "model.py").write_text("result = None\n", encoding="utf-8")
    (ws / ".fw").mkdir()
    (ws / ".fw" / "chat.jsonl").write_text("{}\n", encoding="utf-8")
    d = c.post(f"/api/projects/{pid}/duplicate").json()
    assert d["name"] == "Bracket (copy)" and d["id"] != pid
    assert c.post(f"/api/projects/{pid}/duplicate").json()["name"] == "Bracket (copy 2)"
    db = session_factory()()
    ws2 = workspace_for(db.get(Project, d["id"]))
    db.close()
    assert (ws2 / "model.py").read_text(encoding="utf-8") == "result = None\n" and not (ws2 / ".fw").exists()


def test_catalog_upgrades_old_defaults_but_keeps_admin_edits(app_client: TestClient) -> None:
    from aicad.platform.catalog import MODULES, seed_catalog
    from aicad.platform.models import Product

    db = session_factory()()
    trial = db.get(Product, "trial")
    trial.tokens, trial.modules = 300, ["design"]
    trial.tagline = "Try the full design loop"
    addon = db.get(Product, "addon_drawings")
    addon.tagline = MODULES["drawings"]["summary"][:190]  # the old mid-word cut
    pro = db.get(Product, "pro")
    pro.tagline = "Edited by the founder"
    db.commit()
    seed_catalog(db)
    assert trial.tokens == 1000 and "drawings" in trial.modules and trial.tagline != "Try the full design loop"
    assert addon.tagline.endswith(".") and not MODULES["drawings"]["summary"].startswith(addon.tagline)
    assert pro.tagline == "Edited by the founder"
    trial.tokens = 777  # an admin edit is kept on the next start
    db.commit()
    seed_catalog(db)
    assert trial.tokens == 777
    db.close()


def test_checklist_dismiss_and_size_search_in_inches(app_client: TestClient) -> None:
    c = app_client
    signup(c, "cl@x.com")
    assert c.get("/api/checklist").json()["hidden"] is False
    assert c.post("/api/checklist/dismiss").status_code == 200
    assert c.get("/api/checklist").json()["hidden"] is True
    r = c.get("/api/search/size", params={"q": "4.7 x 3.1 in"}).json()
    assert r["unit"] == "in" and r["dims"] == pytest.approx([119.38, 78.74])
    assert c.get("/api/search/size", params={"q": "120x80x10"}).json()["unit"] == "mm"


def test_admin_funnel_cohort_and_unit_economics(app_client: TestClient) -> None:
    c = app_client
    signup(c, "cohort@x.com")
    c.post("/api/auth/logout")
    admin(c)
    ov = c.get("/api/admin/overview").json()
    signed = next(f for f in ov["funnel"] if f["event"] == "signup")
    assert ov["funnel_cohort"] == 1 and signed["users"] == 1  # the founder is not counted
    assert {"runs_30d", "median_first_part_tokens", "over_estimate", "budget_stops"} <= set(ov["economics"])
