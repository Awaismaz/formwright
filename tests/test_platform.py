"""Platform tests: auth journey, onboarding, billing (simulated), team, permissions, God mode, admin.

No AI calls are made: agent runs are only exercised up to the paywall/preflight decision.
"""

from __future__ import annotations

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
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from aicad.platform.routers import auth as auth_router

    auth_router._attempts.clear()
    monkeypatch.setenv("FW_ADMIN_PASSWORD", PW)
    config.override_settings(config.Settings(
        env="development", data_dir=tmp_path / "data", database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
        app_url="http://testserver", superadmin_emails=(ADMIN,), stripe_secret_key="", trial_tokens=300))
    from aicad.platform.app import create_app

    c = TestClient(create_app())
    c.headers.update({"X-FW-CSRF": "1"})
    return c


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
    assert c.get("/api/auth/me").json()["next_step"] == "verify_email"
    assert c.get("/api/projects").status_code == 403  # unverified
    c.post("/api/auth/verify-email", json={"token": _link_token("ada@x.com", "Verify")})
    me = c.get("/api/auth/me").json()
    assert me["next_step"] == "onboarding" and me["org"] is None
    c.post("/api/onboarding", json={"role": "Engineer", "workspace_name": "Ada Co"})
    me = c.get("/api/auth/me").json()
    assert me["next_step"] == "app"
    assert me["org"]["plan_code"] == "trial" and me["org"]["token_balance"] == 300
    assert me["org"]["modules"] == ["design"] and me["org"]["role"] == "owner"
    cl = c.get("/api/checklist").json()
    assert cl["total"] == 8 and cl["done"] >= 2
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
    assert c.get(f"/api/projects/{pid}").json()["agent"]["allowed"] is True  # 12 >= preflight 10
    c.post("/api/god/scenario", json={"scenario": "trial_expired"})
    assert c.get(f"/api/projects/{pid}").json()["agent"]["allowed"] is False
    c.patch("/api/god", json={"enabled": True, "bypass_paywall": True, "bypass_tokens": True})
    assert c.get(f"/api/projects/{pid}").json()["agent"]["allowed"] is True
    c.post("/api/god/scenario", json={"scenario": "all_modules"})
    assert len(c.get("/api/auth/me").json()["org"]["modules"]) == 8
    c.post("/api/god/scenario", json={"scenario": "fresh_signup"})
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
    return pid, ws


def test_param_edit_rebuilds_without_ai_and_rolls_back_on_failure(app_client: TestClient) -> None:
    c = app_client
    signup(c, "params@x.com")
    demo = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo" / "mounting_plate.py"
    pid, ws = _project_with_model(c, demo.read_text(encoding="utf-8"))
    editable = c.get(f"/api/projects/{pid}/params").json()["editable"]
    assert editable["L"] == 120.0 and editable["CH"] == 1.0 and "PL" in editable
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
