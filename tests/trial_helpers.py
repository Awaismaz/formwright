"""Test helper: a trial workspace may use every live module, so paywall tests end the trial first."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from aicad.platform.db import session_factory, utcnow
from aicad.platform.models import Membership, Organization, User


def set_trial_ended(email: str, ended: bool = True) -> None:
    """End (or restart) the trial of every trial workspace the user belongs to."""
    db = session_factory()()
    try:
        u = db.scalar(select(User).where(User.email == email))
        assert u is not None
        for m in db.scalars(select(Membership).where(Membership.user_id == u.id)):
            org = db.get(Organization, m.org_id)
            if org is not None and org.plan_code == "trial":
                org.trial_ends_at = utcnow() + (timedelta(days=-1) if ended else timedelta(days=14))
        db.commit()
    finally:
        db.close()
