"""Request context: authenticated user, active organization, role checks, God mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from aicad.platform.config import get_settings
from aicad.platform.db import get_db, utcnow
from aicad.platform.models import AuthSession, Membership, Organization, User
from aicad.platform.security import hash_token
from aicad.platform.services import ROLE_RANK

COOKIE = "fw_session"
VERIFY_GRACE = timedelta(hours=24)  # a new account may use the app this long before confirming its email
GOD_KEYS = ("bypass_paywall", "bypass_tokens", "skip_verification", "skip_onboarding")


@dataclass
class Ctx:
    db: Session
    user: User
    session: AuthSession
    actor: User  # == user unless impersonating
    org: Organization | None = None
    role: str | None = None
    ip: str | None = None
    god: dict[str, bool] = field(default_factory=dict)

    @property
    def impersonating(self) -> bool:
        return self.actor.id != self.user.id

    def god_on(self, key: str) -> bool:
        return bool(self.god.get(key))

    def require_role(self, minimum: str) -> None:
        if self.org is None or self.role is None:
            raise HTTPException(403, "No organization selected")
        if ROLE_RANK[self.role] < ROLE_RANK[minimum]:
            raise HTTPException(403, f"Requires {minimum} role or higher")

    def require_org(self) -> Organization:
        if self.org is None:
            raise HTTPException(409, "Create a workspace first")
        return self.org


def god_flags(actor: User) -> dict[str, bool]:
    s = get_settings()
    if not (s.god_mode_enabled and actor.is_superadmin):
        return {}
    g: dict[str, Any] = actor.god or {}
    if not g.get("enabled"):
        return {"available": True}
    return {"available": True, "enabled": True, **{k: bool(g.get(k)) for k in GOD_KEYS}}


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _load(request: Request, db: Session) -> Ctx | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if sess is None or sess.expires_at < utcnow():
        return None
    user = db.get(User, sess.user_id)
    if user is None or user.disabled:
        return None
    actor = db.get(User, sess.impersonator_id) if sess.impersonator_id else user
    if actor is None:
        return None
    ctx = Ctx(db=db, user=user, session=sess, actor=actor, ip=client_ip(request), god=god_flags(actor))
    org_id = request.headers.get("X-Org") or user.default_org_id
    if org_id:
        m = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.org_id == org_id))
        if m is None and user.default_org_id and org_id != user.default_org_id:
            m = db.scalar(select(Membership).where(Membership.user_id == user.id,
                                                   Membership.org_id == user.default_org_id))
        if m is not None:
            ctx.org, ctx.role = db.get(Organization, m.org_id), m.role
    if ctx.org is None:
        m = db.scalar(select(Membership).where(Membership.user_id == user.id))
        if m is not None:
            ctx.org, ctx.role = db.get(Organization, m.org_id), m.role
    return ctx


def optional_ctx(request: Request, db: Session = Depends(get_db)) -> Ctx | None:
    return _load(request, db)


def auth_ctx(request: Request, db: Session = Depends(get_db)) -> Ctx:
    ctx = _load(request, db)
    if ctx is None:
        raise HTTPException(401, "Not signed in")
    return ctx


def in_grace(user: User) -> bool:
    """Unverified, but signed up less than `VERIFY_GRACE` ago: may use the app with a reminder banner."""
    return user.email_verified_at is None and utcnow() - user.created_at < VERIFY_GRACE


def verified_ctx(ctx: Ctx = Depends(auth_ctx)) -> Ctx:
    """Signed in and email verified, or still inside the first-day grace (God mode may skip verification)."""
    if ctx.user.email_verified_at is None and not ctx.god_on("skip_verification") and not in_grace(ctx.user):
        raise HTTPException(403, "Verify your email to continue")
    return ctx


def confirmed_ctx(ctx: Ctx = Depends(verified_ctx)) -> Ctx:
    """Email actually confirmed: required for money and for inviting people (no grace)."""
    if ctx.user.email_verified_at is None and not ctx.god_on("skip_verification"):
        raise HTTPException(403, "Confirm your email address first. We sent you a link.")
    return ctx


def superadmin_ctx(ctx: Ctx = Depends(auth_ctx)) -> Ctx:
    if not ctx.actor.is_superadmin:
        raise HTTPException(403, "Super-admin only")
    return ctx
