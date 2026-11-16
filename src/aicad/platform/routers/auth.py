from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from aicad.platform.config import get_settings
from aicad.platform.db import get_db, utcnow
from aicad.platform.deps import COOKIE, Ctx, auth_ctx, client_ip, optional_ctx
from aicad.platform.models import AuthSession, EmailToken, Membership, Organization, User
from aicad.platform.security import (
    hash_password,
    hash_token,
    new_token,
    normalize_email,
    password_problem,
    valid_email,
    verify_password,
)
from aicad.platform.services import audit, public_org, public_user, send_email, track

router = APIRouter(prefix="/api/auth", tags=["auth"])

_attempts: dict[str, deque[float]] = defaultdict(deque)
RATE_WINDOW_S, RATE_MAX = 300, 10


def _rate_limit(key: str) -> None:
    now = time.monotonic()
    q = _attempts[key]
    while q and now - q[0] > RATE_WINDOW_S:
        q.popleft()
    if len(q) >= RATE_MAX:
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    q.append(now)


class SignupIn(BaseModel):
    name: str
    email: str
    password: str
    invite_token: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class TokenIn(BaseModel):
    token: str


class EmailIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    token: str
    password: str


class ChangePwIn(BaseModel):
    current_password: str
    new_password: str


class ProfileIn(BaseModel):
    name: str | None = None
    preferences: dict[str, Any] | None = None


def start_session(db: Session, response: Response, user: User, request: Request,
                  impersonator: User | None = None) -> None:
    s = get_settings()
    token = new_token()
    db.add(AuthSession(token_hash=hash_token(token), user_id=user.id,
                       impersonator_id=impersonator.id if impersonator else None,
                       expires_at=utcnow() + timedelta(days=s.session_days), ip=client_ip(request),
                       user_agent=(request.headers.get("user-agent") or "")[:300]))
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=s.cookie_secure,
                        max_age=s.session_days * 86400, path="/")


def issue_email_token(db: Session, user: User, kind: str, hours: int) -> str:
    token = new_token()
    db.add(EmailToken(user_id=user.id, kind=kind, token_hash=hash_token(token),
                      expires_at=utcnow() + timedelta(hours=hours)))
    return token


def send_verification(db: Session, user: User) -> None:
    s = get_settings()
    token = issue_email_token(db, user, "verify", 48)
    link = f"{s.app_url}/verify-email?token={token}"
    send_email(db, user.email, "Verify your Formwright email",
               f"Hi {user.name},\n\nConfirm your email to activate your Formwright workspace.", link)


def consume_email_token(db: Session, token: str, kind: str) -> User:
    row = db.scalar(select(EmailToken).where(EmailToken.token_hash == hash_token(token),
                                             EmailToken.kind == kind))
    if row is None or row.used_at is not None or row.expires_at < utcnow():
        raise HTTPException(400, "This link is invalid or has expired.")
    row.used_at = utcnow()
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(400, "This link is invalid or has expired.")
    return user


def next_step(ctx: Ctx) -> str:
    u = ctx.user
    if u.email_verified_at is None and not ctx.god_on("skip_verification"):
        return "verify_email"
    if ctx.org is None or (u.onboarding_completed_at is None and not ctx.god_on("skip_onboarding")):
        return "onboarding"
    return "app"


def me_payload(ctx: Ctx) -> dict[str, Any]:
    s = get_settings()
    db = ctx.db
    orgs = []
    for m in db.scalars(select(Membership).where(Membership.user_id == ctx.user.id)):
        o = db.get(Organization, m.org_id)
        if o:
            orgs.append({"id": o.id, "name": o.name, "role": m.role, "plan_code": o.plan_code})
    return {
        "user": public_user(ctx.user),
        "org": public_org(db, ctx.org, ctx.role, ctx.god_on("bypass_paywall")) if ctx.org else None,
        "orgs": orgs,
        "next_step": next_step(ctx),
        "god": ctx.god,
        "impersonating": {"actor_email": ctx.actor.email, "actor_name": ctx.actor.name} if ctx.impersonating else None,
        "system": {"stripe_mode": s.stripe_mode, "env": s.env, "god_mode_enabled": s.god_mode_enabled},
    }


@router.post("/signup")
def signup(body: SignupIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict[str, Any]:
    _rate_limit(f"signup:{client_ip(request)}")
    s = get_settings()
    email = normalize_email(body.email)
    name = body.name.strip()
    if not name or len(name) > 120:
        raise HTTPException(422, "Please enter your name.")
    if not valid_email(email):
        raise HTTPException(422, "Please enter a valid email address.")
    if (p := password_problem(body.password)) is not None:
        raise HTTPException(422, p)
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    user = User(email=email, name=name, password_hash=hash_password(body.password),
                is_superadmin=email in s.superadmin_emails, preferences={"units": "mm", "theme": "light"})
    db.add(user)
    db.flush()
    audit(db, "user.signup", user, ip=client_ip(request))
    track(db, "signup", user, invited=bool(body.invite_token))
    send_verification(db, user)
    user.last_login_at = utcnow()
    start_session(db, response, user, request)
    db.commit()
    return {"ok": True}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict[str, Any]:
    email = normalize_email(body.email)
    _rate_limit(f"login:{email}")
    _rate_limit(f"login-ip:{client_ip(request)}")
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Email or password is incorrect.")
    if user.disabled:
        raise HTTPException(403, "This account is disabled. Contact support.")
    user.last_login_at = utcnow()
    start_session(db, response, user, request)
    audit(db, "user.login", user, ip=client_ip(request))
    track(db, "login", user)
    db.commit()
    return {"ok": True}


@router.post("/logout")
def logout(response: Response, ctx: Ctx | None = Depends(optional_ctx)) -> dict[str, Any]:
    if ctx is not None:
        ctx.db.delete(ctx.session)
        ctx.db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(ctx: Ctx | None = Depends(optional_ctx)) -> dict[str, Any]:
    if ctx is None:
        s = get_settings()
        return {"user": None, "system": {"stripe_mode": s.stripe_mode, "env": s.env,
                                         "god_mode_enabled": s.god_mode_enabled}}
    return me_payload(ctx)


@router.post("/verify-email")
def verify_email(body: TokenIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = consume_email_token(db, body.token, "verify")
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
        track(db, "email_verified", user)
        audit(db, "user.verify_email", user)
    db.commit()
    return {"ok": True}


@router.post("/resend-verification")
def resend(request: Request, ctx: Ctx = Depends(auth_ctx)) -> dict[str, Any]:
    _rate_limit(f"resend:{ctx.user.id}")
    if ctx.user.email_verified_at is None:
        send_verification(ctx.db, ctx.user)
        ctx.db.commit()
    return {"ok": True}


@router.get("/dev-mailbox")
def dev_mailbox(ctx: Ctx = Depends(auth_ctx)) -> dict[str, Any]:
    """Development only: show the signed-in user's latest emails, so the journey works without SMTP."""
    s = get_settings()
    if s.production or s.smtp_host:
        raise HTTPException(404)
    from aicad.platform.models import Outbox

    rows = ctx.db.scalars(select(Outbox).where(Outbox.to == ctx.user.email).order_by(Outbox.created_at.desc())
                          .limit(5)).all()
    return {"items": [{"subject": r.subject, "body": r.body, "link": r.link, "created_at": r.created_at.isoformat()}
                      for r in rows]}


@router.post("/forgot-password")
def forgot(body: EmailIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    _rate_limit(f"forgot:{client_ip(request)}")
    user = db.scalar(select(User).where(User.email == normalize_email(body.email)))
    if user is not None and not user.disabled:
        token = issue_email_token(db, user, "reset", 2)
        send_email(db, user.email, "Reset your Formwright password",
                   "Someone (hopefully you) asked to reset your password. The link is valid for 2 hours.",
                   f"{get_settings().app_url}/reset-password?token={token}")
        audit(db, "user.password_reset_requested", user)
        db.commit()
    return {"ok": True}  # never reveal whether the email exists


@router.post("/reset-password")
def reset_password(body: ResetIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    if (p := password_problem(body.password)) is not None:
        raise HTTPException(422, p)
    user = consume_email_token(db, body.token, "reset")
    user.password_hash = hash_password(body.password)
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()  # proved control of the mailbox
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)):
        db.delete(s)
    audit(db, "user.password_reset", user)
    db.commit()
    return {"ok": True}


@router.post("/change-password")
def change_password(body: ChangePwIn, ctx: Ctx = Depends(auth_ctx)) -> dict[str, Any]:
    if ctx.impersonating:
        raise HTTPException(403, "Not allowed while impersonating")
    if not verify_password(body.current_password, ctx.user.password_hash):
        raise HTTPException(400, "Current password is incorrect.")
    if (p := password_problem(body.new_password)) is not None:
        raise HTTPException(422, p)
    ctx.user.password_hash = hash_password(body.new_password)
    for s in ctx.db.scalars(select(AuthSession).where(AuthSession.user_id == ctx.user.id,
                                                      AuthSession.id != ctx.session.id)):
        ctx.db.delete(s)
    audit(ctx.db, "user.password_changed", ctx.user)
    ctx.db.commit()
    return {"ok": True}


@router.patch("/profile")
def update_profile(body: ProfileIn, ctx: Ctx = Depends(auth_ctx)) -> dict[str, Any]:
    if body.name is not None:
        if not body.name.strip() or len(body.name) > 120:
            raise HTTPException(422, "Invalid name")
        ctx.user.name = body.name.strip()
    if body.preferences is not None:
        allowed = {"units", "theme", "notifications_email", "viewer_edges"}
        prefs = dict(ctx.user.preferences or {})
        prefs.update({k: v for k, v in body.preferences.items() if k in allowed})
        ctx.user.preferences = prefs
    ctx.db.commit()
    return me_payload(ctx)
