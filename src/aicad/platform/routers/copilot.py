"""Archie, the whole-app copilot (founder 2026-11-20): one conversation per engineer outside programs, the app
actions applied through the same routes as their buttons. On a program page the program's own chat is used
(``office.archie_say``), with the same app context and actions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from aicad.office import archie_chat, copilot, orchestrator, store
from aicad.platform import metering
from aicad.platform.config import get_settings
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.models import Project
from aicad.platform.services import audit, debit

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/copilot", tags=["copilot"])


class CopilotIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    page: dict[str, Any] | None = None


class CopilotActIn(BaseModel):
    message: str
    action: str
    decision: str = "apply"


def _root(ctx: Ctx) -> Path:
    return store.org_root(get_settings().data_dir, ctx.require_org().id)


def known(ctx: Ctx) -> dict[str, Any]:
    """What Archie may refer to: the engineer's programs, part projects and the modules."""
    from aicad.platform.catalog import MODULES
    from aicad.platform.collab import permissions

    root = _root(ctx)
    progs: dict[str, Any] = {}
    for d in sorted(store.list_docs(root), key=lambda d: d.get("updated_at") or "", reverse=True)[:40]:
        o = d.get("orchestrator") or {}
        blocked = sum(1 for t in d.get("tickets") or [] if (t.get("run") or {}).get("status") == "blocked")
        icd = d.get("icd") or {}
        state = d.get("status", "")
        if icd.get("status") == "draft" and icd.get("problems"):
            state += f", interfaces wait with {len(icd['problems'])} problems"
        if o.get("state"):
            state += f", office {o['state']}"
        if blocked:
            state += f", {blocked} blocked"
        progs[d["id"]] = {"name": d.get("name") or d["id"], "state": state}
    rows = ctx.db.scalars(select(Project).where(Project.org_id == ctx.require_org().id, Project.archived.is_(False))
                          .order_by(Project.updated_at.desc()).limit(60)).all()
    acc = permissions.access_map(ctx.db, ctx.user, rows)
    projs = {p.id: {"name": p.name} for p in rows if acc[p.id].at_least("read")}
    mods = {c: m["name"] for c, m in MODULES.items() if c != "design"}
    return {"programs": progs, "projects": projs, "modules": mods}


def _view(ctx: Ctx, k: dict[str, Any] | None = None) -> dict[str, Any]:
    from aicad.platform.routers.office import _chat_ai

    k = k or known(ctx)
    msgs = copilot.history(_root(ctx), ctx.user.id)
    out = [{**m, "actions": [{**a, "label": copilot.describe(a, k)} for a in m.get("actions", [])]} for m in msgs]
    ai, _ = _chat_ai(ctx, {})
    return {"messages": out, "ai": ai, "can_edit": ctx.role != "viewer"}


async def run_copilot(folder: Path, prompt: str, budget_usd: float | None = None) -> tuple[str, float | None]:
    """One text turn as the copilot. Tests and simulated mode replace it."""
    from aicad import llm

    res = await llm.complete(llm.CallRequest(role="office_chat", system=copilot.system(False), prompt=prompt,
                                             budget_usd=budget_usd, cwd=folder))
    return res.text, res.metering.cost_usd


@router.get("")
def copilot_history(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    return _view(ctx)


@router.post("")
async def copilot_say(body: CopilotIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Talk to Archie from any page. Navigation runs at once on the screen; changes come back as proposals."""
    from aicad.platform.routers.office import _chat_ai

    root = _root(ctx)
    text = body.text.strip()
    if not text:
        raise HTTPException(409, "Write a message first.")
    page = copilot.clean_page(body.page)
    k = known(ctx)
    hist = copilot.history(root, ctx.user.id)
    prior = list(hist)
    hist.append(archie_chat.user_message(text, {"id": ctx.user.id, "name": ctx.user.name}))
    copilot.save_history(root, ctx.user.id, hist)
    reply = None
    ai, cap = _chat_ai(ctx, {})
    if ai:
        god = ctx.god_on("bypass_tokens")
        folder = root / "_copilot" / "work"
        folder.mkdir(parents=True, exist_ok=True)
        prose, acts, usd = "", [], None
        try:
            prose, acts, usd, _n = await archie_chat.agentic_turn(
                run_copilot, folder, copilot.prompt(page, k, prior, text),
                None if god else cap * metering.USD_PER_TOKEN, lambda out: archie_chat.review(None, out, k, page))
        except Exception:  # any failure: the offline reader answers
            log.exception("Copilot turn failed")
        tokens = min(cap, metering.tokens_for_usd(usd)) if usd else 0
        if tokens and not god:
            debit(ctx.db, ctx.require_org(), tokens, "usage", "Archie copilot", ctx.user)
            ctx.db.commit()
        if prose or acts:
            reply = archie_chat.archie_message(prose or "Here is what I would do.", acts, kind="ai", tokens=tokens)
    if reply is None:
        t, acts = copilot.offline_reply(text, k)
        acts = [x for a in acts if (x := copilot.normalise(a, k, page)) is not None]
        reply = archie_chat.archie_message(t, acts, kind="office")
    hist = copilot.history(root, ctx.user.id)
    hist.append(reply)
    copilot.save_history(root, ctx.user.id, hist)
    return _view(ctx, k)


@router.post("/actions")
async def copilot_act(body: CopilotActIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    root = _root(ctx)
    hist = copilot.history(root, ctx.user.id)
    m = next((x for x in hist if x["id"] == body.message and x["role"] == "archie"), None)
    a = next((x for x in (m or {}).get("actions", []) if x["id"] == body.action), None)
    if a is None:
        raise HTTPException(404, "That proposal is gone.")
    if a["status"] != "proposed":
        raise HTTPException(409, "That proposal was already handled.")
    out: dict[str, Any] = {}
    status = "dismissed"
    if body.decision == "apply":
        k = known(ctx)
        cur = copilot.normalise({x: v for x, v in a.items() if x not in ("id", "status", "label")}, k)
        if cur is None:
            raise HTTPException(409, "Things have moved on: this proposal no longer applies. Ask Archie again.")
        out = await apply(ctx, cur)
        status = "applied"
    hist = copilot.history(root, ctx.user.id)
    for x in hist:
        if x["id"] == body.message:
            for y in x.get("actions", []):
                if y["id"] == body.action:
                    y.update(status=status, at=store.now(), by={"id": ctx.user.id, "name": ctx.user.name}, **out)
    copilot.save_history(root, ctx.user.id, hist)
    return {**_view(ctx), **out}


async def apply(ctx: Ctx, a: dict[str, Any]) -> dict[str, Any]:
    """Run one app action through the route behind its button. Returns {"navigate": path} when the engineer
    should be taken somewhere next."""
    from aicad.platform.routers import office, projects

    typ = a["type"]
    if typ in copilot.CLIENT_ACTIONS:
        return {"navigate": a["to"]} if typ == "navigate" else (
            {"navigate": copilot.studio_path(a["project"], a["text"])} if typ == "studio_request" else {})
    if ctx.role == "viewer":
        raise HTTPException(403, "Viewers can look around but not change things.")
    if typ == "new_part":
        p = projects.create_project(projects.ProjectIn(name=a["name"], description=a["brief"][:2000]), ctx)
        return {"navigate": copilot.studio_path(p["id"], a["brief"])}
    if typ == "stop_studio_agent":
        await projects.agent_interrupt(a["project"], ctx)
        return {"navigate": f"/app/projects/{a['project']}"}
    if typ == "new_program":
        v = await office.create_program(office.ProgramIn(name=a["name"], brief=a["brief"]), ctx)
        return {"navigate": f"/app/office/programs/{v['id']}"}
    pid = a["program"]
    if typ == "restart_program":
        old = office._load(ctx, pid)
        v = await office.create_program(office.ProgramIn(
            name=a.get("name") or old["name"], brief=a["brief"], concurrency=int(old.get("concurrency") or 3),
            threads=old.get("threads")), ctx)
        if (old.get("orchestrator") or {}).get("state") == "running":
            await office.pause_program(pid, ctx)
        audit(ctx.db, "office.program_restarted", ctx.user, ctx.require_org().id, target=pid, new=v["id"])
        ctx.db.commit()
        return {"navigate": f"/app/office/programs/{v['id']}", "program_id": v["id"]}
    if typ == "heal_program":
        return await heal(ctx, pid)
    if typ == "rebuild_assembly":
        await office.rebuild_assembly(pid, ctx)
        return {"navigate": f"/app/office/programs/{pid}?tab=assembly"}
    if typ == "run_program":
        await office.run_program(pid, ctx)
        return {"navigate": f"/app/office/programs/{pid}"}
    raise HTTPException(409, "Unknown action")


async def heal(ctx: Ctx, pid: str) -> dict[str, Any]:
    """The office repairs a program in place: half-done work is queued again (only when no runner holds it),
    review blocks healed, blocked parts retried, then the office runs."""
    from aicad.platform.routers import office

    office._editor(ctx)
    root = _root(ctx)
    n = 0
    with store.lock(pid):
        doc = office._load(ctx, pid)
        if orchestrator.runner(pid) is None:
            n += orchestrator.recover(root, doc)
        else:
            n += orchestrator.heal_review_blocks(root, doc)
        store.save(root, doc)
    retried = 0
    for t in archie_chat.blocked(office._load(ctx, pid)):
        try:
            await office.ticket_control(pid, t["id"], office.ControlIn(action="retry"), ctx)
            retried += 1
        except HTTPException:
            continue
    ran = False
    doc = office._load(ctx, pid)
    if doc["status"] == "active" and (doc.get("orchestrator") or {}).get("state") != "running":
        try:
            await office.run_program(pid, ctx)
            ran = True
        except HTTPException:
            pass
    audit(ctx.db, "office.program_healed", ctx.user, doc["org_id"], target=pid, requeued=n, retried=retried)
    ctx.db.commit()
    return {"navigate": f"/app/office/programs/{pid}", "healed": n, "retried": retried, "ran": ran}
