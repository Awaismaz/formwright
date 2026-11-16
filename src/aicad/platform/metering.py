"""Design-agent metering: honest run estimates, per-run budgets and the live cost meter.

Tokens are the platform's unit (1 token = $0.01 of estimated AI compute, PD-03). Three rules:
- The estimate shown before a run is measured: a default per run kind ("new" part vs "change" to an existing part)
  from real runs, replaced by the workspace's own history once it has `MIN_SAMPLES` runs of that kind.
- Every run has a budget: the workspace default (or the user's choice for that run), never more than the balance
  that is not already reserved by other running runs. The run stops cleanly when the live meter reaches it, and it
  is never charged more than its budget, so a run can't push the balance below zero.
- The live meter is an estimate from the model's reported usage; the charge uses the agent's own cost report.
"""

from __future__ import annotations

import math
import threading
from datetime import timedelta
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aicad.platform.catalog import TOKEN_COSTS
from aicad.platform.db import utcnow
from aicad.platform.models import AgentRun, Organization, OrgPrefs, TokenLedger, User

USD_PER_TOKEN: float = TOKEN_COSTS["usd_per_token"]

# Measured (Nov 2026, isolated test workspaces: ledger rows and the agent's own cost reports).
#   New part, agent starting cold:  260 (Mounting plate template, 203-character brief), 281 (from a PDF drawing,
#                                   1,941 characters), 275 (from a drawing image, 3,075 characters)
#   New part, context already warm: 45 (Mounting plate template, 46 s)
#   Change to that part:            26 (pocket depth + edge fillets, same session, 46 s)
# Brief length barely moved the cost; whether the design context was already loaded moved it 6x. So the default is a
# wide, honest range, replaced by the workspace's own history after MIN_SAMPLES runs of each kind.
DEFAULT_ESTIMATE: dict[str, dict[str, int]] = {
    "new": {"typical": 250, "low": 40, "high": 400},
    "change": {"typical": 60, "low": 20, "high": 280},
}
MIN_SAMPLES = 3
LONG_BRIEF_CHARS = 1200  # learned estimates split short and long briefs once there is enough history
DEFAULT_RUN_BUDGET = 500
BUDGET_MIN, BUDGET_MAX = 50, 5000
MIN_RUN_TOKENS: int = TOKEN_COSTS["design_run_preflight"]  # below this a run can't do useful work
UNVERIFIED_TOKEN_CAP = 300  # an account with an unconfirmed email may spend this much (about one first part)
LOW_TOKENS = 150  # "running low": less than about one more part


def tokens_for_usd(usd: float | None) -> int:
    if not usd:
        return TOKEN_COSTS["design_run_min"]
    return max(TOKEN_COSTS["design_run_min"], math.ceil(usd / USD_PER_TOKEN - 1e-9))


# ------------------------------------------------------------------ workspace settings
def prefs(db: Session, org: Organization) -> dict[str, Any]:
    row = db.get(OrgPrefs, org.id)
    return dict(row.data or {}) if row else {}


def set_prefs(db: Session, org: Organization, **kv: Any) -> dict[str, Any]:
    row = db.get(OrgPrefs, org.id)
    if row is None:
        row = OrgPrefs(org_id=org.id, data={})
        db.add(row)
    row.data = {**(row.data or {}), **kv}
    return dict(row.data)


def default_budget(db: Session, org: Organization) -> int:
    v = prefs(db, org).get("run_budget_tokens")
    return int(v) if isinstance(v, int) and BUDGET_MIN <= v <= BUDGET_MAX else DEFAULT_RUN_BUDGET


# ------------------------------------------------------------------ reservations (in-flight runs)
_lock = threading.Lock()
_reserved: dict[str, dict[str, int]] = {}  # org_id -> {run_id: budget}


def reserved(org_id: str) -> int:
    with _lock:
        return sum(_reserved.get(org_id, {}).values())


def reserve(org_id: str, run_id: str, tokens: int) -> None:
    with _lock:
        _reserved.setdefault(org_id, {})[run_id] = tokens


def release(org_id: str, run_id: str) -> None:
    with _lock:
        _reserved.get(org_id, {}).pop(run_id, None)


def unverified_spent(db: Session, user: User) -> int:
    rows = db.scalars(select(TokenLedger).where(TokenLedger.user_id == user.id, TokenLedger.reason == "usage")).all()
    return sum(-r.delta for r in rows if r.delta < 0)


def run_budget(db: Session, org: Organization, user: User, requested: int | None,
               unlimited: bool = False) -> tuple[int | None, str | None]:
    """(budget in tokens, reason it is too small). None budget = unlimited (God mode)."""
    if unlimited:
        return None, None
    want = requested if requested is not None else default_budget(db, org)
    want = max(BUDGET_MIN, min(BUDGET_MAX, int(want)))
    available = org.token_balance - reserved(org.id)
    budget = min(want, available)
    if user.email_verified_at is None:
        budget = min(budget, UNVERIFIED_TOKEN_CAP - unverified_spent(db, user))
        if budget < MIN_RUN_TOKENS:
            return None, "verify"
    if budget < MIN_RUN_TOKENS:
        if reserved(org.id) and org.token_balance >= MIN_RUN_TOKENS:
            return None, "Another design run in this workspace is using the rest of the balance. Wait for it to finish."
        return None, f"You need at least {MIN_RUN_TOKENS} tokens to run the design agent."
    return budget, None


# ------------------------------------------------------------------ estimates
def _bucket(chars: int) -> str:
    return "long" if chars >= LONG_BRIEF_CHARS else "short"


def estimate(db: Session, org: Organization, kind: str, brief_chars: int = 0) -> dict[str, Any]:
    """Typical / low / high tokens for a run of this kind. Learned from the workspace once it has enough runs."""
    kind = kind if kind in DEFAULT_ESTIMATE else "new"
    since = utcnow() - timedelta(days=90)
    rows = db.scalars(select(AgentRun).where(AgentRun.org_id == org.id, AgentRun.kind == kind,
                                             AgentRun.status.in_(("ok", "failed")), AgentRun.tokens > 0,
                                             AgentRun.created_at >= since)
                      .order_by(AgentRun.created_at.desc()).limit(40)).all()
    same = [r.tokens for r in rows if _bucket(r.brief_chars) == _bucket(brief_chars)]
    vals = sorted(same if len(same) >= MIN_SAMPLES else [r.tokens for r in rows])
    if len(vals) < MIN_SAMPLES:
        d = DEFAULT_ESTIMATE[kind]
        return {"kind": kind, **d, "basis": "typical", "samples": len(vals)}

    def q(f: float) -> int:
        return vals[min(len(vals) - 1, round(f * (len(vals) - 1)))]

    return {"kind": kind, "typical": int(median(vals)), "low": q(0.1), "high": q(0.9), "basis": "workspace",
            "samples": len(vals)}
