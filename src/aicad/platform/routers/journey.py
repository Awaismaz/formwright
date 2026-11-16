from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from aicad.platform.db import utcnow
from aicad.platform.deps import Ctx, auth_ctx
from aicad.platform.models import (
    Feedback,
    Invite,
    JourneyEvent,
    Membership,
    Notification,
    Organization,
    Project,
)
from aicad.platform.services import audit, notify, start_trial, track

router = APIRouter(prefix="/api", tags=["journey"])

CLIENT_EVENTS = {"tour_started", "tour_step", "tour_skipped", "module_viewed", "pricing_viewed", "upgrade_clicked",
                 "template_used", "checkout_started", "paywall_shown", "help_opened", "download"}


class OnboardingIn(BaseModel):
    role: str | None = None
    company_size: str | None = None
    cad_tools: list[str] = []
    goals: list[str] = []
    units: str | None = None
    workspace_name: str | None = None


class EventIn(BaseModel):
    event: str
    meta: dict[str, Any] = {}


class FeedbackIn(BaseModel):
    kind: str = "general"
    topic: str | None = None
    message: str = ""
    rating: int | None = None


@router.post("/onboarding")
def save_onboarding(body: OnboardingIn, ctx: Ctx = Depends(auth_ctx)) -> dict[str, Any]:
    """Save answers; on the final step create the workspace (organization) and start the trial."""
    from aicad.platform.routers.auth import me_payload

    u = ctx.user
    data = dict(u.onboarding or {})
    data.update({k: v for k, v in body.model_dump().items() if v not in (None, [], "")})
    u.onboarding = data
    if body.units in ("mm", "in"):
        u.preferences = {**(u.preferences or {}), "units": body.units}
    if body.workspace_name is not None:
        name = body.workspace_name.strip()
        if not name or len(name) > 120:
            raise HTTPException(422, "Workspace name is required")
        if ctx.org is None:
            org = Organization(name=name)
            ctx.db.add(org)
            ctx.db.flush()
            ctx.db.add(Membership(user_id=u.id, org_id=org.id, role="owner"))
            u.default_org_id = org.id
            start_trial(ctx.db, org, u)
            audit(ctx.db, "org.created", u, org.id, target=name)
            notify(ctx.db, u.id, "Your 14-day trial has started",
                   "You have trial tokens to design with. Start with a template project.", "/app/projects")
            ctx.org, ctx.role = org, "owner"
        elif ctx.role in ("owner", "admin"):
            ctx.org.name = name
        u.onboarding_completed_at = u.onboarding_completed_at or utcnow()
        track(ctx.db, "onboarding_completed", u, ctx.org.id, **{k: data.get(k) for k in ("role", "company_size")})
    ctx.db.commit()
    return me_payload(ctx)


@router.post("/tour/complete")
def tour_complete(ctx: Ctx = Depends(auth_ctx)) -> dict[str, Any]:
    ctx.user.tour_completed_at = utcnow()
    track(ctx.db, "tour_completed", ctx.user, ctx.org.id if ctx.org else None)
    ctx.db.commit()
    return {"ok": True}


@router.post("/tour/reset")
def tour_reset(ctx: Ctx = Depends(auth_ctx)) -> dict[str, Any]:
    ctx.user.tour_completed_at = None
    ctx.db.commit()
    return {"ok": True}


@router.post("/events")
def client_event(body: EventIn, ctx: Ctx = Depends(auth_ctx)) -> dict[str, Any]:
    if body.event not in CLIENT_EVENTS:
        raise HTTPException(422, "unknown event")
    meta = {k: str(v)[:200] for k, v in list(body.meta.items())[:10]}
    track(ctx.db, body.event, ctx.user, ctx.org.id if ctx.org else None, **meta)
    ctx.db.commit()
    return {"ok": True}


@router.get("/checklist")
def checklist(ctx: Ctx = Depends(auth_ctx)) -> dict[str, Any]:
    db, u, org = ctx.db, ctx.user, ctx.org

    def has(event: str) -> bool:
        return db.scalar(select(func.count()).select_from(JourneyEvent).where(
            JourneyEvent.user_id == u.id, JourneyEvent.event == event)) > 0

    projects = db.scalar(select(func.count()).select_from(Project).where(Project.org_id == org.id)) if org else 0
    built = db.scalar(select(func.count()).select_from(Project).where(
        Project.org_id == org.id, Project.builds > 0)) if org else 0
    team = (db.scalar(select(func.count()).select_from(Membership).where(Membership.org_id == org.id)) or 0) + (
        db.scalar(select(func.count()).select_from(Invite).where(Invite.org_id == org.id)) or 0) if org else 0
    items = [
        {"key": "verify", "title": "Verify your email", "done": u.email_verified_at is not None, "link": "/verify-email"},
        {"key": "workspace", "title": "Set up your workspace", "done": org is not None, "link": "/onboarding"},
        {"key": "tour", "title": "Take the 2-minute tour", "done": u.tour_completed_at is not None, "link": "?tour=1"},
        {"key": "project", "title": "Create your first project", "done": projects > 0, "link": "/app/projects?new=1"},
        {"key": "build", "title": "Generate and verify a part", "done": built > 0, "link": "/app/projects"},
        {"key": "explore", "title": "Explore the module roadmap", "done": has("module_viewed"), "link": "/app/modules"},
        {"key": "team", "title": "Invite a teammate", "done": team > 1, "link": "/app/team"},
        {"key": "plan", "title": "Choose a plan", "done": bool(org and org.plan_code != "trial"), "link": "/app/billing"},
    ]
    return {"items": items, "done": sum(i["done"] for i in items), "total": len(items)}


@router.get("/notifications")
def notifications(ctx: Ctx = Depends(auth_ctx)) -> dict[str, Any]:
    rows = ctx.db.scalars(select(Notification).where(Notification.user_id == ctx.user.id)
                          .order_by(Notification.created_at.desc()).limit(30)).all()
    return {"items": [{"id": n.id, "title": n.title, "body": n.body, "link": n.link, "read": n.read,
                       "created_at": n.created_at.isoformat()} for n in rows],
            "unread": sum(not n.read for n in rows)}


@router.post("/notifications/read-all")
def notifications_read(ctx: Ctx = Depends(auth_ctx)) -> dict[str, Any]:
    for n in ctx.db.scalars(select(Notification).where(Notification.user_id == ctx.user.id,
                                                       Notification.read.is_(False))):
        n.read = True
    ctx.db.commit()
    return {"ok": True}


@router.post("/feedback")
def feedback(body: FeedbackIn, ctx: Ctx = Depends(auth_ctx)) -> dict[str, Any]:
    if body.kind not in ("general", "bug", "feature", "waitlist"):
        raise HTTPException(422, "invalid kind")
    if body.rating is not None and not 1 <= body.rating <= 5:
        raise HTTPException(422, "rating 1-5")
    ctx.db.add(Feedback(user_id=ctx.user.id, org_id=ctx.org.id if ctx.org else None, kind=body.kind,
                        topic=(body.topic or "")[:60] or None, message=body.message[:5000], rating=body.rating))
    track(ctx.db, f"feedback_{body.kind}", ctx.user, ctx.org.id if ctx.org else None, topic=body.topic or "")
    ctx.db.commit()
    return {"ok": True}


@router.get("/waitlist")
def my_waitlist(ctx: Ctx = Depends(auth_ctx)) -> dict[str, Any]:
    rows = ctx.db.scalars(select(Feedback.topic).where(Feedback.user_id == ctx.user.id,
                                                       Feedback.kind == "waitlist")).all()
    return {"modules": sorted({r for r in rows if r})}
