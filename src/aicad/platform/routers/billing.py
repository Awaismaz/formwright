"""Billing: plans (subscriptions), add-ons (module unlocks), token packs.

Two payment providers behind one flow:
- stripe:    real Stripe Checkout (test or live keys via STRIPE_SECRET_KEY) + signed webhooks
- simulated: in-app checkout page for development/demos; clearly labelled; impossible in production
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from aicad.platform.catalog import MODULES, TOKEN_COSTS, product_dict
from aicad.platform.config import get_settings
from aicad.platform.db import get_db, utcnow
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.models import Entitlement, Organization, Payment, Product, TokenLedger, User
from aicad.platform.services import audit, credit, notify, public_org, track

router = APIRouter(prefix="/api/billing", tags=["billing"])


class CheckoutIn(BaseModel):
    product_code: str


class SimulateIn(BaseModel):
    outcome: str  # success|fail


def _catalog(db: Session) -> dict[str, Any]:
    prods = db.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.sort)).all()
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in prods:
        by[p.kind].append(product_dict(p))
    return {"plans": by["plan"], "addons": by["addon"], "topups": by["topup"],
            "modules": [{"code": k, **v} for k, v in MODULES.items()],
            "token_costs": TOKEN_COSTS, "stripe_mode": get_settings().stripe_mode}


@router.get("/catalog")
def catalog(db: Session = Depends(get_db)) -> dict[str, Any]:
    return _catalog(db)


@router.get("")
def overview(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    org = ctx.require_org()
    db = ctx.db
    ledger = db.scalars(select(TokenLedger).where(TokenLedger.org_id == org.id)
                        .order_by(TokenLedger.created_at.desc()).limit(100)).all()
    users = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_({r.user_id for r in ledger if r.user_id})))}
    payments = db.scalars(select(Payment).where(Payment.org_id == org.id).order_by(Payment.created_at.desc())
                          .limit(50)).all()
    since = utcnow() - timedelta(days=30)
    usage: dict[str, int] = defaultdict(int)
    for r in ledger:
        if r.reason == "usage" and r.created_at >= since:
            usage[r.created_at.date().isoformat()] += -r.delta
    days = [(utcnow() - timedelta(days=i)).date().isoformat() for i in range(29, -1, -1)]
    addons = [e.module for e in db.scalars(select(Entitlement).where(Entitlement.org_id == org.id))]
    return {
        "org": public_org(db, org, ctx.role, ctx.god_on("bypass_paywall")),
        "ledger": [{"id": r.id, "delta": r.delta, "balance_after": r.balance_after, "reason": r.reason,
                    "detail": r.detail, "user": users.get(r.user_id or ""), "created_at": r.created_at.isoformat()}
                   for r in ledger],
        "payments": [{"id": p.id, "product_code": p.product_code, "kind": p.kind, "amount_cents": p.amount_cents,
                      "currency": p.currency, "status": p.status, "provider": p.provider,
                      "created_at": p.created_at.isoformat(), "paid_at": p.paid_at.isoformat() if p.paid_at else None}
                     for p in payments],
        "usage_30d": [{"date": d, "tokens": usage.get(d, 0)} for d in days],
        "addons": addons, "catalog": _catalog(db), "can_purchase": ctx.role in ("owner", "admin"),
    }


def fulfil(db: Session, pay: Payment, provider_ref: str | None = None) -> None:
    """Idempotent: apply a paid purchase to the organization."""
    if pay.status == "paid":
        return
    org = db.get(Organization, pay.org_id)
    prod = db.get(Product, pay.product_code)
    if org is None or prod is None:
        return
    pay.status, pay.paid_at = "paid", utcnow()
    if provider_ref:
        pay.provider_ref = provider_ref
    user = db.get(User, pay.user_id) if pay.user_id else None
    if prod.kind == "plan":
        org.plan_code, org.plan_status = prod.code, "active"
        org.current_period_end = utcnow() + timedelta(days=30 if prod.interval == "month" else 365)
        if prod.tokens:
            credit(db, org, prod.tokens, "plan", f"{prod.name} plan allowance", user, ref=pay.id)
    elif prod.kind == "addon":
        for m in prod.modules:
            if not db.scalar(select(Entitlement).where(Entitlement.org_id == org.id, Entitlement.module == m)):
                db.add(Entitlement(org_id=org.id, module=m, source="purchase"))
    elif prod.kind == "topup":
        credit(db, org, prod.tokens, "topup", prod.name, user, ref=pay.id)
    audit(db, "billing.paid", user, org.id, target=prod.code, amount_cents=pay.amount_cents, provider=pay.provider)
    track(db, "purchase", user, org.id, product=prod.code, kind=prod.kind, amount_cents=pay.amount_cents)
    if user:
        notify(db, user.id, f"Payment received: {prod.name}",
               f"${pay.amount_cents / 100:,.2f} — thank you. Your workspace has been updated.", "/app/billing")


@router.post("/checkout")
def checkout(body: CheckoutIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    ctx.require_role("admin")
    org = ctx.require_org()
    s = get_settings()
    prod = ctx.db.get(Product, body.product_code)
    if prod is None or not prod.active or not prod.purchasable or prod.contact_sales:
        raise HTTPException(404, "Not available for purchase")
    if prod.kind == "plan" and org.plan_code == prod.code and org.plan_status == "active":
        raise HTTPException(409, "You are already on this plan")
    if prod.kind == "addon" and all(
            ctx.db.scalar(select(Entitlement).where(Entitlement.org_id == org.id, Entitlement.module == m))
            for m in prod.modules):
        raise HTTPException(409, "You already own this add-on")
    pay = Payment(org_id=org.id, user_id=ctx.user.id, product_code=prod.code, kind=prod.kind,
                  amount_cents=prod.price_cents, provider="stripe" if s.stripe_live else "simulated")
    ctx.db.add(pay)
    ctx.db.flush()
    track(ctx.db, "checkout_started", ctx.user, org.id, product=prod.code)
    if not s.stripe_live:
        ctx.db.commit()
        return {"provider": "simulated", "payment_id": pay.id, "url": f"/app/checkout/{pay.id}"}
    import stripe

    stripe.api_key = s.stripe_secret_key
    recurring = prod.kind in ("plan", "addon") and prod.interval
    price_data: dict[str, Any] = {"currency": "usd", "unit_amount": prod.price_cents,
                                  "product_data": {"name": f"Formwright {prod.name}"}}
    if recurring:
        price_data["recurring"] = {"interval": prod.interval}
    if not org.stripe_customer_id:
        cust = stripe.Customer.create(email=ctx.user.email, name=org.name, metadata={"org_id": org.id})
        org.stripe_customer_id = cust.id
    sess = stripe.checkout.Session.create(
        mode="subscription" if recurring else "payment", customer=org.stripe_customer_id,
        client_reference_id=pay.id,
        line_items=[{"price": prod.stripe_price_id, "quantity": 1} if prod.stripe_price_id
                    else {"price_data": price_data, "quantity": 1}],
        metadata={"payment_id": pay.id, "org_id": org.id, "product": prod.code},
        success_url=f"{s.app_url}/app/billing?checkout=success&payment={pay.id}",
        cancel_url=f"{s.app_url}/app/billing?checkout=canceled&payment={pay.id}",
    )
    pay.provider_ref = sess.id
    ctx.db.commit()
    return {"provider": "stripe", "payment_id": pay.id, "url": sess.url}


@router.get("/payments/{payment_id}")
def payment(payment_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    pay = ctx.db.get(Payment, payment_id)
    if pay is None or pay.org_id != ctx.require_org().id:
        raise HTTPException(404)
    prod = ctx.db.get(Product, pay.product_code)
    return {"id": pay.id, "status": pay.status, "provider": pay.provider, "amount_cents": pay.amount_cents,
            "product": product_dict(prod) if prod else None, "created_at": pay.created_at.isoformat()}


@router.post("/payments/{payment_id}/simulate")
def simulate(payment_id: str, body: SimulateIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    if get_settings().production:
        raise HTTPException(404)
    pay = ctx.db.get(Payment, payment_id)
    if pay is None or pay.org_id != ctx.require_org().id or pay.provider != "simulated":
        raise HTTPException(404)
    if pay.status != "pending":
        raise HTTPException(409, f"Payment already {pay.status}")
    if body.outcome == "success":
        fulfil(ctx.db, pay, provider_ref=f"sim_{pay.id[:12]}")
    elif body.outcome == "fail":
        pay.status = "failed"
        track(ctx.db, "payment_failed", ctx.user, pay.org_id, product=pay.product_code)
    else:
        raise HTTPException(422, "outcome must be success or fail")
    ctx.db.commit()
    return {"ok": True, "status": pay.status}


@router.post("/cancel")
def cancel_plan(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    ctx.require_role("owner")
    org = ctx.require_org()
    s = get_settings()
    if org.plan_code in ("trial",):
        raise HTTPException(409, "No paid plan to cancel")
    if s.stripe_live and org.stripe_subscription_id:
        import stripe

        stripe.api_key = s.stripe_secret_key
        stripe.Subscription.modify(org.stripe_subscription_id, cancel_at_period_end=True)
        org.plan_status = "active"  # remains active until period end; webhook finalises
    else:
        org.plan_status = "canceled"
    audit(ctx.db, "billing.cancel", ctx.user, org.id, target=org.plan_code)
    track(ctx.db, "plan_canceled", ctx.user, org.id, plan=org.plan_code)
    ctx.db.commit()
    return {"ok": True}


@router.delete("/addons/{module}")
def remove_addon(module: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    ctx.require_role("owner")
    org = ctx.require_org()
    e = ctx.db.scalar(select(Entitlement).where(Entitlement.org_id == org.id, Entitlement.module == module))
    if e is None:
        raise HTTPException(404)
    ctx.db.delete(e)
    audit(ctx.db, "billing.addon_removed", ctx.user, org.id, target=module)
    ctx.db.commit()
    return {"ok": True}


@router.post("/portal")
def portal(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    ctx.require_role("admin")
    org = ctx.require_org()
    s = get_settings()
    if not s.stripe_live or not org.stripe_customer_id:
        return {"url": None, "message": "Billing is managed in-app in this environment."}
    import stripe

    stripe.api_key = s.stripe_secret_key
    sess = stripe.billing_portal.Session.create(customer=org.stripe_customer_id, return_url=f"{s.app_url}/app/billing")
    return {"url": sess.url}


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    s = get_settings()
    if not s.stripe_live or not s.stripe_webhook_secret:
        raise HTTPException(404)
    import stripe

    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, request.headers.get("stripe-signature", ""),
                                               s.stripe_webhook_secret)
    except (ValueError, stripe.SignatureVerificationError) as e:
        raise HTTPException(400, "invalid signature") from e
    obj = event["data"]["object"]
    etype = event["type"]
    if etype == "checkout.session.completed":
        pay = db.get(Payment, obj.get("client_reference_id") or "")
        if pay:
            fulfil(db, pay, provider_ref=obj.get("id"))
            if obj.get("subscription") and pay.kind == "plan":
                org = db.get(Organization, pay.org_id)
                if org:
                    org.stripe_subscription_id = obj["subscription"]
    elif etype == "invoice.paid" and obj.get("billing_reason") == "subscription_cycle":
        org = db.scalar(select(Organization).where(Organization.stripe_customer_id == obj.get("customer")))
        prod = db.get(Product, org.plan_code) if org else None
        if org and prod and prod.tokens:
            org.current_period_end = utcnow() + timedelta(days=30)
            credit(db, org, prod.tokens, "plan", f"{prod.name} monthly allowance", ref=obj.get("id"))
    elif etype == "customer.subscription.deleted":
        org = db.scalar(select(Organization).where(Organization.stripe_subscription_id == obj.get("id")))
        if org:
            org.plan_status = "canceled"
    elif etype == "invoice.payment_failed":
        org = db.scalar(select(Organization).where(Organization.stripe_customer_id == obj.get("customer")))
        if org:
            org.plan_status = "past_due"
    db.commit()
    return {"received": True}


def tokens_for_cost(cost_usd: float | None) -> int:
    if not cost_usd:
        return TOKEN_COSTS["design_run_min"]
    return max(TOKEN_COSTS["design_run_min"], math.ceil(cost_usd / TOKEN_COSTS["usd_per_token"]))
