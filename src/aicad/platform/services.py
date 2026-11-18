"""Domain services shared by routers: audit, events, email, notifications, tokens, entitlements."""

from __future__ import annotations

import smtplib
from datetime import timedelta
from email.message import EmailMessage
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aicad.platform.catalog import MODULES
from aicad.platform.config import get_settings
from aicad.platform.db import utcnow
from aicad.platform.models import (
    AuditLog,
    Entitlement,
    JourneyEvent,
    Membership,
    Notification,
    Organization,
    Outbox,
    Product,
    TokenLedger,
    User,
)

ROLES = ("owner", "admin", "engineer", "viewer")
ROLE_RANK = {r: i for i, r in enumerate(reversed(ROLES))}  # viewer 0 ... owner 3


class InsufficientTokens(Exception):
    pass


def audit(db: Session, action: str, actor: User | None = None, org_id: str | None = None,
          target: str | None = None, ip: str | None = None, **meta: Any) -> None:
    db.add(AuditLog(actor_id=actor.id if actor else None, org_id=org_id, action=action, target=target,
                    meta=meta, ip=ip))


def track(db: Session, event: str, user: User | None = None, org_id: str | None = None, **meta: Any) -> None:
    db.add(JourneyEvent(user_id=user.id if user else None, org_id=org_id, event=event, meta=meta))


def notify(db: Session, user_id: str, title: str, body: str = "", link: str | None = None) -> None:
    db.add(Notification(user_id=user_id, title=title[:160], body=body, link=link))


def notify_revision(db: Session, project: Any, rev: int | None, actor: User | None, what: str) -> None:
    """Tell a project's creator when someone else makes a new revision of it."""
    owner = project.created_by
    if not rev or not owner or actor is None or owner == actor.id:
        return
    if db.scalar(select(Membership).where(Membership.user_id == owner, Membership.org_id == project.org_id)) is None:
        return
    what = " ".join(what.split())
    notify(db, owner, f"{actor.name} changed {project.name}",
           f"Revision {rev}: {what[:140]}{'…' if len(what) > 140 else ''}", f"/app/projects/{project.id}")


def send_email(db: Session, to: str, subject: str, body: str, link: str | None = None) -> Outbox:
    """Always recorded in the outbox (visible in admin/dev); delivered via SMTP when configured."""
    s = get_settings()
    msg = Outbox(to=to, subject=subject, body=body, link=link)
    if s.smtp_host:
        try:
            em = EmailMessage()
            em["From"], em["To"], em["Subject"] = s.smtp_from, to, subject
            em.set_content(body + (f"\n\n{link}" if link else ""))
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
                smtp.starttls()
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(em)
            msg.delivered = "smtp"
        except (OSError, smtplib.SMTPException):
            msg.delivered = "failed"
    db.add(msg)
    return msg


# ---------------------------------------------------------------- tokens
def credit(db: Session, org: Organization, amount: int, reason: str, detail: str = "",
           user: User | None = None, ref: str | None = None) -> TokenLedger:
    org.token_balance += amount
    row = TokenLedger(org_id=org.id, user_id=user.id if user else None, delta=amount,
                      balance_after=org.token_balance, reason=reason, detail=detail, ref=ref)
    db.add(row)
    return row


def debit(db: Session, org: Organization, amount: int, reason: str, detail: str = "",
          user: User | None = None, ref: str | None = None, allow_negative: bool = True) -> TokenLedger:
    if amount < 0:
        raise ValueError("debit amount must be >= 0")
    if not allow_negative and org.token_balance < amount:
        raise InsufficientTokens(f"needs {amount} tokens, balance {org.token_balance}")
    org.token_balance -= amount
    row = TokenLedger(org_id=org.id, user_id=user.id if user else None, delta=-amount,
                      balance_after=org.token_balance, reason=reason, detail=detail, ref=ref)
    db.add(row)
    return row


# ---------------------------------------------------------------- entitlements
def plan_product(db: Session, org: Organization) -> Product | None:
    return db.get(Product, org.plan_code)


def org_modules(db: Session, org: Organization) -> set[str]:
    mods: set[str] = set()
    plan = plan_product(db, org)
    if org.plan_code == "trial" and org.plan_status == "trialing":
        # A running trial can use every live module on its own parts; once it ends, parts and the Design Studio
        # stay open (edits, exports) and the other modules lock until a plan or add-on includes them.
        mods |= {"design"} if trial_state(org).get("expired") else {c for c, m in MODULES.items()
                                                                     if m["status"] == "live"}
    elif plan and org.plan_status in ("trialing", "active", "past_due"):
        mods |= set(plan.modules or [])
        if "design" in mods:  # bring-your-own-key modules cost the platform nothing to run: every plan has them
            mods |= {c for c, m in MODULES.items() if m.get("byo_key") and m["status"] == "live"}
    mods |= {e.module for e in db.scalars(select(Entitlement).where(Entitlement.org_id == org.id))}
    return mods


def seats_used(db: Session, org: Organization) -> int:
    return len(db.scalars(select(Membership).where(Membership.org_id == org.id)).all())


def seat_limit(db: Session, org: Organization) -> int:
    from aicad.platform.models import OrgPrefs

    plan = plan_product(db, org)
    if not (plan and plan.seats):
        return 1000
    row = db.get(OrgPrefs, org.id)
    extra = (row.data or {}).get("extra_seats", 0) if row else 0
    return plan.seats + (int(extra) if isinstance(extra, int) and plan.code == "team" else 0)


def trial_state(org: Organization) -> dict[str, Any]:
    if org.plan_code != "trial":
        return {"on_trial": False}
    now = utcnow()
    ends = org.trial_ends_at or now
    import math

    days_left = max(0, math.ceil((ends - now).total_seconds() / 86400))
    return {"on_trial": True, "trial_ends_at": ends.isoformat(), "days_left": days_left,
            "expired": ends < now}


def start_trial(db: Session, org: Organization, user: User | None) -> None:
    s = get_settings()
    org.plan_code, org.plan_status = "trial", "trialing"
    org.trial_ends_at = utcnow() + timedelta(days=s.trial_days)
    credit(db, org, s.trial_tokens, "trial", "Welcome trial tokens", user=user)


def module_catalog(db: Session, org: Organization, god_unlock: bool = False) -> list[dict[str, Any]]:
    owned = org_modules(db, org)
    out = []
    for code, m in MODULES.items():
        out.append({"code": code, **m, "unlocked": god_unlock or code in owned, "owned": code in owned})
    return out


def public_user(u: User) -> dict[str, Any]:
    from aicad.platform.deps import VERIFY_GRACE

    grace = (u.created_at + VERIFY_GRACE).isoformat() if u.email_verified_at is None else None
    return {"id": u.id, "email": u.email, "name": u.name, "email_verified": u.email_verified_at is not None,
            "verify_by": grace,
            "is_superadmin": u.is_superadmin, "onboarding": u.onboarding or {},
            "onboarding_completed": u.onboarding_completed_at is not None,
            "tour_completed": u.tour_completed_at is not None, "preferences": u.preferences or {},
            "created_at": u.created_at.isoformat()}


def public_org(db: Session, org: Organization, role: str | None = None, god_unlock: bool = False) -> dict[str, Any]:
    plan = plan_product(db, org)
    return {"id": org.id, "name": org.name, "role": role, "plan_code": org.plan_code,
            "plan_name": plan.name if plan else org.plan_code, "plan_status": org.plan_status,
            "token_balance": org.token_balance, "plan_tokens": plan.tokens if plan else 0,
            "current_period_end": org.current_period_end.isoformat() if org.current_period_end else None,
            "seats_used": seats_used(db, org), "seat_limit": seat_limit(db, org),
            "modules": sorted(org_modules(db, org)), "god_unlock": god_unlock, **trial_state(org)}
