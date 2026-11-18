from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from aicad.platform.config import get_settings
from aicad.platform.db import utcnow
from aicad.platform.deps import Ctx, auth_ctx, confirmed_ctx, verified_ctx
from aicad.platform.models import Invite, Membership, User
from aicad.platform.security import hash_token, new_token, normalize_email, valid_email
from aicad.platform.services import (
    ROLES,
    audit,
    notify,
    public_org,
    seat_limit,
    seats_used,
    send_email,
    track,
)

router = APIRouter(prefix="/api/team", tags=["team"])


class InviteIn(BaseModel):
    email: str
    role: str = "engineer"


class RoleIn(BaseModel):
    role: str


class OrgIn(BaseModel):
    name: str


class TokenIn(BaseModel):
    token: str


@router.get("")
def team(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    org = ctx.require_org()
    members = []
    for m in ctx.db.scalars(select(Membership).where(Membership.org_id == org.id)):
        u = ctx.db.get(User, m.user_id)
        if u:
            members.append({"id": m.id, "user_id": u.id, "name": u.name, "email": u.email, "role": m.role,
                            "joined_at": m.created_at.isoformat(),
                            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None})
    invites = [{"id": i.id, "email": i.email, "role": i.role, "created_at": i.created_at.isoformat(),
                "expires_at": i.expires_at.isoformat()}
               for i in ctx.db.scalars(select(Invite).where(Invite.org_id == org.id, Invite.accepted_at.is_(None),
                                                            Invite.revoked.is_(False), Invite.role != "guest"))]
    return {"org": public_org(ctx.db, org, ctx.role), "members": members, "invites": invites,
            "roles": list(ROLES), "my_role": ctx.role}


@router.post("/invites")
def invite(body: InviteIn, ctx: Ctx = Depends(confirmed_ctx)) -> dict[str, Any]:
    ctx.require_role("admin")
    org = ctx.require_org()
    email = normalize_email(body.email)
    if not valid_email(email):
        raise HTTPException(422, "Invalid email")
    if body.role not in ROLES or body.role == "owner":
        raise HTTPException(422, "Invalid role")
    pending = len(ctx.db.scalars(select(Invite).where(Invite.org_id == org.id, Invite.accepted_at.is_(None),
                                                      Invite.revoked.is_(False), Invite.role != "guest")).all())
    if seats_used(ctx.db, org) + pending >= seat_limit(ctx.db, org) and not ctx.god_on("bypass_paywall"):
        raise HTTPException(402, "All seats are in use. Add a seat in Billing to invite more teammates."
                            if org.plan_code == "team" else
                            "All seats are in use. Upgrade to the Team plan to add teammates.")
    existing = ctx.db.scalar(select(User).where(User.email == email))
    if existing and ctx.db.scalar(select(Membership).where(Membership.user_id == existing.id,
                                                           Membership.org_id == org.id)):
        raise HTTPException(409, "Already a member")
    token = new_token()
    ctx.db.add(Invite(org_id=org.id, email=email, role=body.role, token_hash=hash_token(token),
                      invited_by=ctx.user.id, expires_at=utcnow() + timedelta(days=7)))
    send_email(ctx.db, email, f"{ctx.user.name} invited you to {org.name} on Formwright",
               f"{ctx.user.name} invited you to join the {org.name} workspace as {body.role}.",
               f"{get_settings().app_url}/invite?token={token}")
    audit(ctx.db, "team.invite", ctx.user, org.id, target=email, role=body.role)
    track(ctx.db, "teammate_invited", ctx.user, org.id)
    ctx.db.commit()
    return {"ok": True}


@router.delete("/invites/{invite_id}")
def revoke(invite_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    ctx.require_role("admin")
    inv = ctx.db.get(Invite, invite_id)
    if inv is None or inv.org_id != ctx.require_org().id:
        raise HTTPException(404)
    inv.revoked = True
    audit(ctx.db, "team.invite_revoked", ctx.user, inv.org_id, target=inv.email)
    ctx.db.commit()
    return {"ok": True}


@router.post("/invites/accept")
def accept(body: TokenIn, ctx: Ctx = Depends(auth_ctx)) -> dict[str, Any]:
    from aicad.platform.routers.auth import me_payload

    inv = ctx.db.scalar(select(Invite).where(Invite.token_hash == hash_token(body.token)))
    if inv is None or inv.revoked or inv.accepted_at or inv.expires_at < utcnow():
        raise HTTPException(400, "This invitation is invalid or has expired.")
    if inv.email != ctx.user.email:
        raise HTTPException(403, f"This invitation was sent to {inv.email}. Sign in with that account.")
    if inv.role == "guest":  # a guest invite opens one project, without a workspace seat (PLT-022)
        from aicad.platform.routers.collab import accept_guest_invite

        pid = accept_guest_invite(ctx.db, inv, ctx.user)
        inv.accepted_at = utcnow()
        ctx.user.email_verified_at = ctx.user.email_verified_at or utcnow()
        ctx.user.onboarding_completed_at = ctx.user.onboarding_completed_at or utcnow()
        if inv.invited_by:
            notify(ctx.db, inv.invited_by, f"{ctx.user.name} opened the project you shared",
                   link=f"/app/projects/{pid}" if pid else None)
        ctx.db.commit()
        ctx.db.refresh(ctx.user)
        return {**me_payload(ctx), "project_id": pid}
    if not ctx.db.scalar(select(Membership).where(Membership.user_id == ctx.user.id,
                                                  Membership.org_id == inv.org_id)):
        ctx.db.add(Membership(user_id=ctx.user.id, org_id=inv.org_id, role=inv.role))
    inv.accepted_at = utcnow()
    ctx.user.email_verified_at = ctx.user.email_verified_at or utcnow()  # invite link proves mailbox control
    ctx.user.default_org_id = inv.org_id
    ctx.user.onboarding_completed_at = ctx.user.onboarding_completed_at or utcnow()
    if inv.invited_by:
        notify(ctx.db, inv.invited_by, f"{ctx.user.name} joined your workspace", link="/app/team")
    audit(ctx.db, "team.invite_accepted", ctx.user, inv.org_id)
    track(ctx.db, "invite_accepted", ctx.user, inv.org_id)
    ctx.db.commit()
    ctx.db.refresh(ctx.user)
    from aicad.platform.models import Organization

    ctx.org, ctx.role = ctx.db.get(Organization, inv.org_id), inv.role
    return me_payload(ctx)


@router.patch("/members/{membership_id}")
def change_role(membership_id: str, body: RoleIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    ctx.require_role("admin")
    m = ctx.db.get(Membership, membership_id)
    if m is None or m.org_id != ctx.require_org().id:
        raise HTTPException(404)
    if body.role not in ROLES:
        raise HTTPException(422, "Invalid role")
    if (m.role == "owner" or body.role == "owner") and ctx.role != "owner":
        raise HTTPException(403, "Only the owner can transfer or change ownership")
    if m.role == "owner" and body.role != "owner":
        owners = ctx.db.scalars(select(Membership).where(Membership.org_id == m.org_id, Membership.role == "owner")).all()
        if len(owners) <= 1:
            raise HTTPException(409, "A workspace needs at least one owner")
    m.role = body.role
    audit(ctx.db, "team.role_changed", ctx.user, m.org_id, target=m.user_id, role=body.role)
    ctx.db.commit()
    return {"ok": True}


@router.delete("/members/{membership_id}")
def remove(membership_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    m = ctx.db.get(Membership, membership_id)
    if m is None or m.org_id != ctx.require_org().id:
        raise HTTPException(404)
    if m.user_id != ctx.user.id:
        ctx.require_role("admin")
    if m.role == "owner":
        owners = ctx.db.scalars(select(Membership).where(Membership.org_id == m.org_id, Membership.role == "owner")).all()
        if len(owners) <= 1:
            raise HTTPException(409, "Transfer ownership before removing the last owner")
    ctx.db.delete(m)
    audit(ctx.db, "team.member_removed", ctx.user, m.org_id, target=m.user_id)
    ctx.db.commit()
    return {"ok": True}


@router.patch("/org")
def rename(body: OrgIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    ctx.require_role("admin")
    org = ctx.require_org()
    if not body.name.strip() or len(body.name) > 120:
        raise HTTPException(422, "Invalid name")
    org.name = body.name.strip()
    audit(ctx.db, "org.renamed", ctx.user, org.id, target=org.name)
    ctx.db.commit()
    return {"ok": True}
