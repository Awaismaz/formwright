"""God mode: founder/demo controls. Super-admin only, and the whole router 404s in production."""

from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from aicad.platform.catalog import MODULES
from aicad.platform.config import get_settings
from aicad.platform.db import utcnow
from aicad.platform.deps import GOD_KEYS, Ctx, auth_ctx
from aicad.platform.models import Entitlement, Membership, Project, User
from aicad.platform.security import hash_password, new_token
from aicad.platform.services import audit, credit, debit, notify

router = APIRouter(prefix="/api/god", tags=["god"])

SCENARIOS = {
    "fresh_signup": "Brand-new account: email unverified (first-day grace), onboarding and tour not done",
    "verify_overdue": "Signed up over a day ago and email still unverified (verification wall)",
    "needs_onboarding": "Verified, but onboarding not completed",
    "first_tour": "Onboarded, guided tour not yet taken",
    "trial_active": "Trial with the full trial tokens and 14 days left",
    "trial_low_tokens": "Trial with 12 tokens left (paywall on next run)",
    "trial_expired": "Trial ended yesterday",
    "pro_active": "Pro subscriber with 1,500 tokens",
    "team_active": "Team subscriber with 7,500 tokens",
    "past_due": "Subscription payment failed (past due)",
    "all_modules": "Unlock every module via grants",
    "no_modules": "Remove all add-on grants and purchases",
}

DEMO_DOMAIN = "demo.formwright.dev"
DEMO_SCRIPTS = Path(__file__).resolve().parents[2] / "demo"


class GodPatch(BaseModel):
    enabled: bool | None = None
    bypass_paywall: bool | None = None
    bypass_tokens: bool | None = None
    skip_verification: bool | None = None
    skip_onboarding: bool | None = None


class ScenarioIn(BaseModel):
    scenario: str


def god_ctx(ctx: Ctx = Depends(auth_ctx)) -> Ctx:
    if not get_settings().god_mode_enabled or not ctx.actor.is_superadmin:
        raise HTTPException(404)
    return ctx


@router.get("")
def state(ctx: Ctx = Depends(god_ctx)) -> dict[str, Any]:
    g = ctx.actor.god or {}
    return {"flags": {"enabled": bool(g.get("enabled")), **{k: bool(g.get(k)) for k in GOD_KEYS}},
            "scenarios": [{"code": k, "label": v} for k, v in SCENARIOS.items()],
            "impersonating": ctx.impersonating}


@router.patch("")
def patch(body: GodPatch, ctx: Ctx = Depends(god_ctx)) -> dict[str, Any]:
    g = dict(ctx.actor.god or {})
    g.update(body.model_dump(exclude_none=True))
    ctx.actor.god = g
    audit(ctx.db, "god.flags", ctx.actor, **body.model_dump(exclude_none=True))
    ctx.db.commit()
    return state(ctx)


@router.post("/scenario")
def scenario(body: ScenarioIn, ctx: Ctx = Depends(god_ctx)) -> dict[str, Any]:
    """Put the *current* user/workspace into a journey state so any step can be demoed instantly."""
    sc = body.scenario
    if sc not in SCENARIOS:
        raise HTTPException(422, "Unknown scenario")
    u, db, now = ctx.user, ctx.db, utcnow()
    org = ctx.org

    def set_tokens(n: int) -> None:
        if org is None:
            return
        diff = n - org.token_balance
        if diff > 0:
            credit(db, org, diff, "adjust", f"God mode scenario: {sc}", ctx.actor)
        elif diff < 0:
            debit(db, org, -diff, "adjust", f"God mode scenario: {sc}", ctx.actor)

    if sc == "fresh_signup":
        u.email_verified_at = None
        u.created_at = now
        u.onboarding_completed_at = None
        u.tour_completed_at = None
    elif sc == "verify_overdue":
        u.email_verified_at = None
        u.created_at = now - timedelta(days=2)
    elif sc == "needs_onboarding":
        u.email_verified_at = u.email_verified_at or now
        u.onboarding_completed_at = None
    elif sc == "first_tour":
        u.email_verified_at = u.email_verified_at or now
        u.onboarding_completed_at = u.onboarding_completed_at or now
        u.tour_completed_at = None
    elif org is None:
        raise HTTPException(409, "Create a workspace first (complete onboarding)")
    elif sc in ("trial_active", "trial_low_tokens", "trial_expired"):
        org.plan_code, org.plan_status = "trial", "trialing"
        org.trial_ends_at = now - timedelta(days=1) if sc == "trial_expired" else now + timedelta(days=14)
        set_tokens({"trial_active": get_settings().trial_tokens, "trial_low_tokens": 12, "trial_expired": 140}[sc])
    elif sc in ("pro_active", "team_active"):
        plan = sc.split("_")[0]
        org.plan_code, org.plan_status = plan, "active"
        org.current_period_end = now + timedelta(days=30)
        set_tokens(1500 if plan == "pro" else 7500)
    elif sc == "past_due":
        if org.plan_code == "trial":
            org.plan_code = "pro"
        org.plan_status = "past_due"
        notify(db, u.id, "Payment failed", "We couldn't charge your card. Update billing to avoid interruption.",
               "/app/billing")
    elif sc == "all_modules":
        for m in MODULES:
            if not db.scalar(select(Entitlement).where(Entitlement.org_id == org.id, Entitlement.module == m)):
                db.add(Entitlement(org_id=org.id, module=m, source="grant"))
    elif sc == "no_modules":
        for e in db.scalars(select(Entitlement).where(Entitlement.org_id == org.id)):
            db.delete(e)
    audit(db, "god.scenario", ctx.actor, org.id if org else None, scenario=sc)
    db.commit()
    return {"ok": True}


async def _build(ws: Path, title: str, key: str) -> None:
    from aicad.agent import worker

    await worker.build(key, ws / "model.py", ws / "out", determinism=True)
    stl = ws / "out" / "part.stl"
    if stl.is_file():
        await worker.render(key, stl, ws / "out" / "views.png", title)


@router.post("/seed-demo")
async def seed_demo(ctx: Ctx = Depends(god_ctx)) -> dict[str, Any]:
    """Create demo projects (real builds of our own original scripts) and demo teammates in this workspace."""
    import json

    from aicad.platform.routers.projects import _snapshot, workspace_for

    org = ctx.require_org()
    db = ctx.db
    made = 0
    for script in sorted(DEMO_SCRIPTS.glob("*.py")):
        title = script.stem.replace("_", " ").title()
        if db.scalar(select(Project).where(Project.org_id == org.id, Project.name == f"Demo · {title}")):
            continue
        p = Project(org_id=org.id, name=f"Demo · {title}", description="Demo project (seeded by God mode)",
                    template="demo", created_by=ctx.user.id)
        db.add(p)
        db.flush()
        ws = workspace_for(p)
        ws.mkdir(parents=True, exist_ok=True)
        shutil.copy2(script, ws / "model.py")
        await _build(ws, title, org.id)
        sp = ws / "out" / "status.json"
        if sp.is_file():
            st = json.loads(sp.read_text(encoding="utf-8"))
            p.last_status = {k: st.get(k) for k in ("ok", "part", "material", "fingerprint", "error", "build_id",
                                                    "params")}
            p.builds = 1
            _snapshot(p, ws, cause="Demo part created", kind="library")
        made += 1
    for name, role in (("Priya Natarajan", "admin"), ("Marcus Reid", "engineer"), ("Elena Kowalski", "viewer")):
        email = f"{name.split()[0].lower()}@{DEMO_DOMAIN}"
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, name=name, password_hash=hash_password(new_token()),
                        email_verified_at=utcnow(), onboarding_completed_at=utcnow(), tour_completed_at=utcnow())
            db.add(user)
            db.flush()
        if not db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.org_id == org.id)):
            db.add(Membership(user_id=user.id, org_id=org.id, role=role))
    audit(db, "god.seed_demo", ctx.actor, org.id, projects=made)
    db.commit()
    return {"ok": True, "projects_created": made}


@router.post("/reset-demo")
def reset_demo(ctx: Ctx = Depends(god_ctx)) -> dict[str, Any]:
    from aicad.platform.routers.projects import workspace_for

    org = ctx.require_org()
    db = ctx.db
    removed = 0
    for p in db.scalars(select(Project).where(Project.org_id == org.id, Project.template == "demo")):
        ws = workspace_for(p)
        db.delete(p)
        if ws.is_dir():
            shutil.rmtree(ws, ignore_errors=True)
        removed += 1
    for m in db.scalars(select(Membership).where(Membership.org_id == org.id)):
        u = db.get(User, m.user_id)
        if u and u.email.endswith("@" + DEMO_DOMAIN):
            db.delete(m)
    audit(db, "god.reset_demo", ctx.actor, org.id, projects=removed)
    db.commit()
    return {"ok": True, "projects_removed": removed}

