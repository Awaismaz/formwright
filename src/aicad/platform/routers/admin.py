"""Super-admin console: metrics, funnel, users, organizations, catalog, audit, outbox, impersonation."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from aicad.platform.catalog import MODULES, product_dict
from aicad.platform.config import get_settings
from aicad.platform.db import utcnow
from aicad.platform.deps import Ctx, auth_ctx, superadmin_ctx
from aicad.platform.models import (
    AgentRun,
    AuditLog,
    AuthSession,
    Entitlement,
    Feedback,
    JourneyEvent,
    Membership,
    Organization,
    Outbox,
    Payment,
    Product,
    Project,
    TokenLedger,
    User,
)
from aicad.platform.services import audit, credit, debit, public_org

router = APIRouter(prefix="/api/admin", tags=["admin"])

FUNNEL = [("signup", "Signed up"), ("email_verified", "Verified email"), ("onboarding_completed", "Onboarded"),
          ("project_created", "Created project"), ("first_build", "First verified part"),
          ("checkout_started", "Started checkout"), ("purchase", "Purchased")]


class UserPatch(BaseModel):
    disabled: bool | None = None
    is_superadmin: bool | None = None
    verify_email: bool | None = None


class OrgPatch(BaseModel):
    plan_code: str | None = None
    plan_status: str | None = None
    name: str | None = None


class TokensIn(BaseModel):
    amount: int
    note: str = ""


class ModuleIn(BaseModel):
    module: str
    enabled: bool


class ProductPatch(BaseModel):
    name: str | None = None
    tagline: str | None = None
    price_cents: int | None = None
    tokens: int | None = None
    seats: int | None = None
    active: bool | None = None
    highlight: bool | None = None
    features: list[str] | None = None


@router.get("/overview")
def overview(ctx: Ctx = Depends(superadmin_ctx)) -> dict[str, Any]:
    db = ctx.db
    now = utcnow()
    d30 = now - timedelta(days=30)

    def count(model: Any, *where: Any) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    # Funnel over a real cohort: people who signed up in the last 90 days, without founders/admins or demo accounts.
    cohort = set(db.scalars(select(User.id).where(User.is_superadmin.is_(False), User.created_at >= now - timedelta(days=90),
                                                  ~User.email.like("%@demo.formwright.dev"))))
    funnel = []
    for ev, label in FUNNEL:
        n = db.scalar(select(func.count(func.distinct(JourneyEvent.user_id))).where(
            JourneyEvent.event == ev, JourneyEvent.user_id.in_(cohort))) or 0 if cohort else 0
        funnel.append({"event": ev, "label": label, "users": n})
    runs = db.scalars(select(AgentRun).where(AgentRun.created_at >= d30, AgentRun.status != "running")).all()
    firsts = sorted(r.tokens for r in runs if r.kind == "new" and r.verified)
    changes = sorted(r.tokens for r in runs if r.kind == "change" and r.status == "ok")
    economics = {
        "runs_30d": len(runs),
        "median_first_part_tokens": firsts[len(firsts) // 2] if firsts else None,
        "median_change_tokens": changes[len(changes) // 2] if changes else None,
        "over_estimate": sum(1 for r in runs if r.est_high and r.tokens > r.est_high),
        "budget_stops": sum(1 for r in runs if r.status == "stopped_budget"),
        "failed": sum(1 for r in runs if r.status == "failed" or r.verified is False),
        "cost_usd_30d": round(sum(r.cost_usd or 0 for r in runs), 2),
    }
    signups: dict[str, int] = defaultdict(int)
    for (created,) in db.execute(select(User.created_at).where(User.created_at >= d30)):
        signups[created.date().isoformat()] += 1
    days = [(now - timedelta(days=i)).date().isoformat() for i in range(29, -1, -1)]
    prices = {p.code: p for p in db.scalars(select(Product))}
    mrr = 0
    plans: dict[str, int] = defaultdict(int)
    for o in db.scalars(select(Organization)):
        plans[o.plan_code] += 1
        if o.plan_status == "active" and o.plan_code in prices:
            mrr += prices[o.plan_code].price_cents
    for e in db.scalars(select(Entitlement).where(Entitlement.source == "purchase")):
        addon = next((p for p in prices.values() if p.kind == "addon" and e.module in (p.modules or [])), None)
        if addon:
            mrr += addon.price_cents
    revenue = db.scalar(select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(Payment.status == "paid")) or 0
    tokens_used = -(db.scalar(select(func.coalesce(func.sum(TokenLedger.delta), 0)).where(
        TokenLedger.reason == "usage", TokenLedger.created_at >= d30)) or 0)
    s = get_settings()
    return {
        "kpis": {"users": count(User), "orgs": count(Organization),
                 "active_7d": count(User, User.last_login_at >= now - timedelta(days=7)),
                 "projects": count(Project), "builds": db.scalar(select(func.coalesce(func.sum(Project.builds), 0))) or 0,
                 "mrr_cents": mrr, "revenue_cents": revenue, "tokens_used_30d": tokens_used,
                 "paid_orgs": count(Organization, Organization.plan_status == "active",
                                    Organization.plan_code != "trial")},
        "funnel": funnel, "funnel_cohort": len(cohort), "economics": economics, "signups_30d": [{"date": d, "count": signups.get(d, 0)} for d in days],
        "plans": dict(plans),
        "payments_mode": s.stripe_mode,
        "note": "Revenue/MRR include simulated payments when Stripe is not configured." if s.stripe_mode == "simulated"
        else None,
    }


@router.get("/users")
def users(q: str = "", ctx: Ctx = Depends(superadmin_ctx)) -> dict[str, Any]:
    stmt = select(User).order_by(User.created_at.desc()).limit(200)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.email).like(like), func.lower(User.name).like(like)))
    out = []
    for u in ctx.db.scalars(stmt):
        ms = ctx.db.scalars(select(Membership).where(Membership.user_id == u.id)).all()
        orgs = [{"id": m.org_id, "role": m.role, "name": (o.name if (o := ctx.db.get(Organization, m.org_id)) else "?"),
                 "plan": o.plan_code if o else None} for m in ms]
        out.append({"id": u.id, "name": u.name, "email": u.email, "verified": u.email_verified_at is not None,
                    "superadmin": u.is_superadmin, "disabled": u.disabled, "orgs": orgs,
                    "onboarded": u.onboarding_completed_at is not None, "onboarding": u.onboarding,
                    "created_at": u.created_at.isoformat(),
                    "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None})
    return {"items": out}


@router.patch("/users/{user_id}")
def patch_user(user_id: str, body: UserPatch, ctx: Ctx = Depends(superadmin_ctx)) -> dict[str, Any]:
    u = ctx.db.get(User, user_id)
    if u is None:
        raise HTTPException(404)
    if u.id == ctx.actor.id and (body.disabled or body.is_superadmin is False):
        raise HTTPException(409, "You cannot disable or demote yourself")
    if body.disabled is not None:
        u.disabled = body.disabled
        if body.disabled:
            for s in ctx.db.scalars(select(AuthSession).where(AuthSession.user_id == u.id)):
                ctx.db.delete(s)
    if body.is_superadmin is not None:
        u.is_superadmin = body.is_superadmin
    if body.verify_email:
        u.email_verified_at = u.email_verified_at or utcnow()
    audit(ctx.db, "admin.user_updated", ctx.actor, target=u.id, **body.model_dump(exclude_none=True))
    ctx.db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/impersonate")
def impersonate(user_id: str, request: Request, response: Response, ctx: Ctx = Depends(superadmin_ctx)) -> dict[str, Any]:
    from aicad.platform.routers.auth import start_session

    target = ctx.db.get(User, user_id)
    if target is None or target.disabled:
        raise HTTPException(404)
    if ctx.impersonating:
        raise HTTPException(409, "Stop the current impersonation first")
    ctx.db.delete(ctx.session)
    start_session(ctx.db, response, target, request, impersonator=ctx.actor)
    audit(ctx.db, "admin.impersonate", ctx.actor, target=target.id, email=target.email)
    ctx.db.commit()
    return {"ok": True}


@router.post("/stop-impersonation")
def stop_impersonation(request: Request, response: Response, ctx: Ctx = Depends(auth_ctx)) -> dict[str, Any]:
    from aicad.platform.routers.auth import start_session

    if not ctx.impersonating:
        raise HTTPException(409, "Not impersonating")
    actor = ctx.actor
    ctx.db.delete(ctx.session)
    start_session(ctx.db, response, actor, request)
    audit(ctx.db, "admin.impersonate_stop", actor, target=ctx.user.id)
    ctx.db.commit()
    return {"ok": True}


@router.get("/orgs")
def orgs(ctx: Ctx = Depends(superadmin_ctx)) -> dict[str, Any]:
    items = []
    for o in ctx.db.scalars(select(Organization).order_by(Organization.created_at.desc()).limit(300)):
        po = public_org(ctx.db, o)
        po["projects"] = ctx.db.scalar(select(func.count()).select_from(Project).where(Project.org_id == o.id)) or 0
        po["created_at"] = o.created_at.isoformat()
        items.append(po)
    return {"items": items, "modules": list(MODULES)}


@router.patch("/orgs/{org_id}")
def patch_org(org_id: str, body: OrgPatch, ctx: Ctx = Depends(superadmin_ctx)) -> dict[str, Any]:
    o = ctx.db.get(Organization, org_id)
    if o is None:
        raise HTTPException(404)
    if body.plan_code is not None:
        if ctx.db.get(Product, body.plan_code) is None:
            raise HTTPException(422, "Unknown plan")
        o.plan_code = body.plan_code
    if body.plan_status is not None:
        if body.plan_status not in ("trialing", "active", "past_due", "canceled"):
            raise HTTPException(422, "Bad status")
        o.plan_status = body.plan_status
    if body.name:
        o.name = body.name[:120]
    audit(ctx.db, "admin.org_updated", ctx.actor, o.id, **body.model_dump(exclude_none=True))
    ctx.db.commit()
    return {"ok": True}


@router.post("/orgs/{org_id}/tokens")
def grant_tokens(org_id: str, body: TokensIn, ctx: Ctx = Depends(superadmin_ctx)) -> dict[str, Any]:
    o = ctx.db.get(Organization, org_id)
    if o is None or body.amount == 0 or abs(body.amount) > 10_000_000:
        raise HTTPException(422, "Invalid")
    if body.amount > 0:
        credit(ctx.db, o, body.amount, "grant", body.note or "Admin grant", ctx.actor)
    else:
        debit(ctx.db, o, -body.amount, "adjust", body.note or "Admin adjustment", ctx.actor)
    audit(ctx.db, "admin.tokens", ctx.actor, o.id, amount=body.amount, note=body.note)
    ctx.db.commit()
    return {"ok": True, "balance": o.token_balance}


@router.post("/orgs/{org_id}/modules")
def set_module(org_id: str, body: ModuleIn, ctx: Ctx = Depends(superadmin_ctx)) -> dict[str, Any]:
    if body.module not in MODULES:
        raise HTTPException(422, "Unknown module")
    e = ctx.db.scalar(select(Entitlement).where(Entitlement.org_id == org_id, Entitlement.module == body.module))
    if body.enabled and e is None:
        ctx.db.add(Entitlement(org_id=org_id, module=body.module, source="grant"))
    elif not body.enabled and e is not None:
        ctx.db.delete(e)
    audit(ctx.db, "admin.module", ctx.actor, org_id, module=body.module, enabled=body.enabled)
    ctx.db.commit()
    return {"ok": True}


@router.get("/catalog")
def catalog(ctx: Ctx = Depends(superadmin_ctx)) -> dict[str, Any]:
    return {"items": [product_dict(p) for p in ctx.db.scalars(select(Product).order_by(Product.sort))]}


@router.patch("/catalog/{code}")
def patch_product(code: str, body: ProductPatch, ctx: Ctx = Depends(superadmin_ctx)) -> dict[str, Any]:
    p = ctx.db.get(Product, code)
    if p is None:
        raise HTTPException(404)
    data = body.model_dump(exclude_none=True)
    if "price_cents" in data and not 0 <= data["price_cents"] <= 10_000_000:
        raise HTTPException(422, "Bad price")
    for k, v in data.items():
        setattr(p, k, v)
    audit(ctx.db, "admin.catalog_updated", ctx.actor, target=code, **data)
    ctx.db.commit()
    return product_dict(p)


@router.get("/audit")
def audit_log(limit: int = 200, ctx: Ctx = Depends(superadmin_ctx)) -> dict[str, Any]:
    rows = ctx.db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 1000))).all()
    names = {u.id: u.email for u in ctx.db.scalars(select(User).where(User.id.in_({r.actor_id for r in rows})))}
    return {"items": [{"id": r.id, "actor": names.get(r.actor_id or "", "system"), "org_id": r.org_id,
                       "action": r.action, "target": r.target, "meta": r.meta, "ip": r.ip,
                       "created_at": r.created_at.isoformat()} for r in rows]}


@router.get("/outbox")
def outbox(ctx: Ctx = Depends(superadmin_ctx)) -> dict[str, Any]:
    rows = ctx.db.scalars(select(Outbox).order_by(Outbox.created_at.desc()).limit(200)).all()
    return {"items": [{"id": r.id, "to": r.to, "subject": r.subject, "body": r.body, "link": r.link,
                       "delivered": r.delivered, "created_at": r.created_at.isoformat()} for r in rows]}


@router.get("/feedback")
def feedback(ctx: Ctx = Depends(superadmin_ctx)) -> dict[str, Any]:
    rows = ctx.db.scalars(select(Feedback).order_by(Feedback.created_at.desc()).limit(300)).all()
    emails = {u.id: u.email for u in ctx.db.scalars(select(User).where(User.id.in_({r.user_id for r in rows})))}
    return {"items": [{"id": r.id, "user": emails.get(r.user_id or ""), "kind": r.kind, "topic": r.topic,
                       "message": r.message, "rating": r.rating, "created_at": r.created_at.isoformat()} for r in rows]}


@router.get("/payments")
def payments(ctx: Ctx = Depends(superadmin_ctx)) -> dict[str, Any]:
    rows = ctx.db.scalars(select(Payment).order_by(Payment.created_at.desc()).limit(300)).all()
    orgs_ = {o.id: o.name for o in ctx.db.scalars(select(Organization).where(Organization.id.in_({r.org_id for r in rows})))}
    return {"items": [{"id": r.id, "org": orgs_.get(r.org_id), "product_code": r.product_code, "kind": r.kind,
                       "amount_cents": r.amount_cents, "status": r.status, "provider": r.provider,
                       "created_at": r.created_at.isoformat()} for r in rows]}


@router.get("/system")
def system(ctx: Ctx = Depends(superadmin_ctx)) -> dict[str, Any]:
    import os
    import platform
    from importlib.metadata import version

    s = get_settings()
    return {"env": s.env, "payments": s.stripe_mode, "god_mode_enabled": s.god_mode_enabled,
            "smtp": bool(s.smtp_host), "database": s.db_url.split("://")[0],
            "agent_auth": "API key" if os.environ.get("ANTHROPIC_API_KEY") else "local Claude Code login (dev only)",
            "python": platform.python_version(), "build123d": version("build123d"),
            "claude_agent_sdk": version("claude-agent-sdk"), "superadmins": list(s.superadmin_emails)}
