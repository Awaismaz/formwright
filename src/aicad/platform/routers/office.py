"""Design Office API: programs, Archie's plan and the brief gate, the ticket board, roll-up and the live feed.

Org-scoped like assemblies (documents under ``<data>/office/<org_id>/``). Viewers can open everything; changes need
the engineer role. Archie's planning turn is metered like any design-agent run; the standard planner is free.

  GET    /api/office/home                                   programs, roster, reviews inbox, spend vs budget
  GET    /api/office/events                                 live events for the whole office (SSE)
  GET    /api/office/programs
  POST   /api/office/programs                               create; plan with Archie (AI) or the standard planner
  GET    /api/office/programs/{pid}                         full view (items + roll-up, tickets, ETA, gates)
  PATCH  /api/office/programs/{pid}                         rename, concurrency, budget
  DELETE /api/office/programs/{pid}
  POST   /api/office/programs/{pid}/replan                  plan again (optionally with review notes)
  POST   /api/office/programs/{pid}/gates/brief/approve     approve the (edited) plan: items and tickets open
  POST   /api/office/programs/{pid}/tickets/{tid}/move      board column
  PATCH  /api/office/programs/{pid}/tickets/{tid}           title, specialist, complexity
  POST   /api/office/programs/{pid}/tickets/{tid}/milestones
  POST   /api/office/programs/{pid}/tickets/{tid}/comments
  POST   /api/office/programs/{pid}/tickets/{tid}/start     open the part in Design Studio (or the assembly)
  GET    /api/office/programs/{pid}/activity[?after=seq]    event log
  GET    /api/office/programs/{pid}/events[?once=1]         live events (SSE); once: backlog only, then close
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from aicad.office import OfficeInputError, planner, service, store
from aicad.platform import metering
from aicad.platform.config import get_settings
from aicad.platform.db import session_factory
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.models import AgentRun, Organization, Project, User
from aicad.platform.services import audit, debit, org_modules, track

router = APIRouter(prefix="/api/office", tags=["office"])
log = logging.getLogger("aicad.office")
ARCHIE_MAX_TOKENS = 200  # hard cap for one planning turn (a typical plan costs far less)
_tasks: set[asyncio.Task[None]] = set()


class ProgramIn(BaseModel):
    name: str = ""
    brief: str
    planner: str = "archie"  # "archie" (AI) | "standard" (deterministic, free)
    concurrency: int = Field(default=3, ge=1, le=12)
    budget_tokens: int = Field(default=service.DEFAULT_BUDGET_TOKENS, ge=0, le=1_000_000)


class ProgramPatch(BaseModel):
    name: str | None = None
    concurrency: int | None = Field(default=None, ge=1, le=12)
    budget_tokens: int | None = Field(default=None, ge=0, le=1_000_000)


class ReplanIn(BaseModel):
    planner: str = "archie"
    notes: str = ""


class ApproveIn(BaseModel):
    plan: dict[str, Any] | None = None


class MoveIn(BaseModel):
    column: str


class TicketPatch(BaseModel):
    title: str | None = None
    specialist: str | None = None
    complexity: int | None = None


class MilestoneIn(BaseModel):
    code: str
    reached: bool = True


class CommentIn(BaseModel):
    text: str


# ----------------------------------------------------------------------------- access helpers
def _root(ctx: Ctx) -> Path:
    return store.org_root(get_settings().data_dir, ctx.require_org().id)


def _editor(ctx: Ctx) -> None:
    if ctx.role == "viewer":
        raise HTTPException(403, "Viewers can follow programs but can't change them.")


def _load(ctx: Ctx, pid: str) -> dict[str, Any]:
    try:
        d = store.load(_root(ctx), pid)
    except OfficeInputError:
        d = None
    if d is None or d.get("org_id") != ctx.require_org().id:
        raise HTTPException(404, "Program not found")
    return d


def _actor(ctx: Ctx) -> dict[str, Any]:
    return service.user_actor(ctx.user.name or ctx.user.email, ctx.user.id)


def _mutate(ctx: Ctx, pid: str, fn: Any) -> dict[str, Any]:
    """load -> change -> save under the program lock; user errors become 409."""
    _editor(ctx)
    root = _root(ctx)
    with store.lock(pid):
        doc = _load(ctx, pid)
        try:
            fn(root, doc)
        except OfficeInputError as e:
            raise HTTPException(409, str(e)) from e
        store.save(root, doc)
    return doc


def _studio_info(ctx: Ctx, doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    ids = {t["project_id"] for t in doc["tickets"] if t.get("project_id")}
    if not ids:
        return {}
    org_id = ctx.require_org().id
    rows = ctx.db.scalars(select(Project).where(Project.id.in_(ids), Project.org_id == org_id)).all()
    spent = dict(ctx.db.execute(select(AgentRun.project_id, func.coalesce(func.sum(AgentRun.tokens), 0))
                                .where(AgentRun.project_id.in_(ids), AgentRun.org_id == org_id)
                                .group_by(AgentRun.project_id)).all())
    return {p.id: {"builds": p.builds, "ok": (p.last_status or {}).get("ok") if p.builds else None,
                   "tokens": int(spent.get(p.id) or 0)} for p in rows}


def _synced(ctx: Ctx, pid: str) -> dict[str, Any]:
    """The program with build milestones refreshed from its linked Studio projects."""
    doc = _load(ctx, pid)
    info = _studio_info(ctx, doc)
    if info:
        root = _root(ctx)
        with store.lock(pid):
            doc = _load(ctx, pid)
            if service.sync_studio(root, doc, info):
                store.save(root, doc)
    return doc


# ----------------------------------------------------------------------------- Archie's planning turn
async def _plan_task(root: Path, pid: str, org_id: str, user_id: str, god_tokens: bool, notes: str) -> None:
    doc = store.load(root, pid)
    if doc is None:
        return
    db = session_factory()()
    try:
        org = db.get(Organization, org_id)
        balance = org.token_balance if org else 0
    finally:
        db.close()
    budget = None if god_tokens else max(0, min(balance, ARCHIE_MAX_TOKENS)) * metering.USD_PER_TOKEN
    text, usd, failed = "", None, False
    try:
        text, usd = await planner.run_agent(store.program_dir(root, pid) / "archie", doc["name"], doc["brief"],
                                            notes, budget)
    except Exception:  # any agent failure falls back to the standard planner
        log.exception("Archie planning failed")
        failed = True
    plan = planner.parse_plan(text)
    tokens = metering.tokens_for_usd(usd) if usd else 0
    if usd:
        db = session_factory()()
        try:
            org, user = db.get(Organization, org_id), db.get(User, user_id)
            if org is not None and not god_tokens:
                debit(db, org, tokens, "usage", f"Design Office · Archie plan for {doc['name']}", user, ref=pid)
            track(db, "office_archie_plan", user, org_id, tokens=tokens, ok=plan is not None)
            db.commit()
        finally:
            db.close()
    with store.lock(pid):
        doc = store.load(root, pid)
        if doc is None:
            return
        doc["budget"]["planning_tokens"] = int(doc["budget"].get("planning_tokens", 0)) + (0 if god_tokens else tokens)
        archie = service.agent_actor("archie")
        if plan is not None:
            service.set_plan(root, doc, plan, archie, narrative=planner.narrative(text))
        else:
            why = ("Archie stopped before finishing the plan" if failed else
                   "Archie's answer did not contain a plan that could be used")
            service.set_plan(root, doc, planner.standard_plan(doc["name"], doc["brief"]), archie,
                             note=f"{why}, so this is the standard breakdown. Edit it, or ask Archie again.")
        store.save(root, doc)


def _start_planning(ctx: Ctx, root: Path, doc: dict[str, Any], kind: str, notes: str = "") -> None:
    """Archie (async, metered) or the standard planner (immediate). Caller saves ``doc``."""
    if kind == "archie":
        from aicad.platform.routers.projects import can_run_agent

        allowed, reason, cta = can_run_agent(ctx)
        if not allowed:
            raise HTTPException(402, {"message": reason, "cta": cta})
        doc["status"], doc["planner"] = "planning", "archie"
        doc["planning"] = {"started_at": store.now(), "notes": notes[:2000]}
        service.emit(root, doc, "plan.started", f"Archie is reading the brief for {doc['name']}.",
                     service.agent_actor("archie"))
    else:
        doc["planner"] = "standard"
        service.set_plan(root, doc, planner.standard_plan(doc["name"], doc["brief"]), service.agent_actor("archie"))


def _spawn(ctx: Ctx, root: Path, doc: dict[str, Any], notes: str = "") -> None:
    t = asyncio.create_task(_plan_task(root, doc["id"], ctx.require_org().id, ctx.user.id,
                                       ctx.god_on("bypass_tokens"), notes))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


# ----------------------------------------------------------------------------- routes: office
@router.get("/home")
def home(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    docs = store.list_docs(_root(ctx))
    progs = [service.summary(d) for d in docs]
    return {"programs": progs, "roster": service.roster_view(docs), "inbox": service.inbox(docs),
            "budget": {"tokens": sum(p["budget"]["tokens"] for p in progs),
                       "spent": sum(p["budget"]["spent"] for p in progs)},
            "can_edit": ctx.role != "viewer"}


@router.get("/programs")
def list_programs(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    return {"items": [service.summary(d) for d in store.list_docs(_root(ctx))]}


@router.post("/programs")
async def create_program(body: ProgramIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    _editor(ctx)
    org = ctx.require_org()
    brief = body.brief.strip()
    if len(brief) < 20:
        raise HTTPException(422, "Describe the product in a sentence or two (at least 20 characters).")
    if len(brief) > 20000:
        raise HTTPException(413, "The brief is too long (20,000 characters at most).")
    name = " ".join(body.name.split())[:120] or " ".join(brief.split()[:6])[:60]
    kind = "archie" if body.planner == "archie" else "standard"
    root = _root(ctx)
    doc = service.new_program(name, brief, org.id, ctx.user.id, body.concurrency, body.budget_tokens, kind)
    service.emit(root, doc, "program.created", f"{ctx.user.name or 'Someone'} opened the program {name}.",
                 _actor(ctx))
    _start_planning(ctx, root, doc, kind)
    store.save(root, doc)
    if kind == "archie":
        _spawn(ctx, root, doc)
    audit(ctx.db, "office.program_created", ctx.user, org.id, target=doc["id"], planner=kind)
    track(ctx.db, "office_program_created", ctx.user, org.id, planner=kind)
    ctx.db.commit()
    return service.view(doc)


@router.get("/programs/{pid}")
def get_program(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    return {**service.view(_synced(ctx, pid)), "can_edit": ctx.role != "viewer"}


@router.patch("/programs/{pid}")
def patch_program(pid: str, body: ProgramPatch, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    def fn(root: Path, doc: dict[str, Any]) -> None:
        if body.name is not None and body.name.strip():
            doc["name"] = " ".join(body.name.split())[:120]
        if body.concurrency is not None:
            doc["concurrency"] = body.concurrency
        if body.budget_tokens is not None:
            doc["budget"]["tokens"] = body.budget_tokens
        service.emit(root, doc, "program.updated", f"{ctx.user.name or 'Someone'} updated the program settings.",
                     _actor(ctx))
    return service.view(_mutate(ctx, pid, fn))


@router.delete("/programs/{pid}")
def delete_program(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    _editor(ctx)
    doc = _load(ctx, pid)
    store.delete(_root(ctx), pid)
    audit(ctx.db, "office.program_deleted", ctx.user, doc["org_id"], target=pid)
    ctx.db.commit()
    return {"ok": True}


@router.post("/programs/{pid}/replan")
async def replan(pid: str, body: ReplanIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    kind = "archie" if body.planner == "archie" else "standard"

    def fn(root: Path, doc: dict[str, Any]) -> None:
        if doc["status"] == "planning":
            raise OfficeInputError("Archie is still planning.")
        if doc["status"] != "plan_review":
            raise OfficeInputError("The plan is already approved: tickets are open.")
        if body.notes.strip():
            service.emit(root, doc, "gate.changes_requested", f"{ctx.user.name or 'Someone'} asked for changes to "
                         "the plan.", _actor(ctx), notes=body.notes.strip()[:2000])
        _start_planning(ctx, root, doc, kind, body.notes)

    doc = _mutate(ctx, pid, fn)
    if kind == "archie":
        _spawn(ctx, _root(ctx), doc, body.notes)
    return service.view(doc)


@router.post("/programs/{pid}/gates/brief/approve")
def approve_brief(pid: str, body: ApproveIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    doc = _mutate(ctx, pid, lambda root, d: service.approve_plan(root, d, body.plan, _actor(ctx)))
    track(ctx.db, "office_brief_approved", ctx.user, doc["org_id"], tickets=len(doc["tickets"]),
          edited=bool(doc["plan"].get("edited")))
    ctx.db.commit()
    return service.view(doc)


# ----------------------------------------------------------------------------- routes: tickets
@router.post("/programs/{pid}/tickets/{tid}/move")
def move_ticket(pid: str, tid: str, body: MoveIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    return service.view(_mutate(ctx, pid, lambda root, d: service.move(root, d, tid, body.column, _actor(ctx))))


@router.patch("/programs/{pid}/tickets/{tid}")
def patch_ticket(pid: str, tid: str, body: TicketPatch, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    return service.view(_mutate(ctx, pid, lambda root, d: service.update(
        root, d, tid, _actor(ctx), title=body.title, specialist=body.specialist, complexity=body.complexity)))


@router.post("/programs/{pid}/tickets/{tid}/milestones")
def ticket_milestone(pid: str, tid: str, body: MilestoneIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    return service.view(_mutate(ctx, pid, lambda root, d: service.set_milestone(
        root, d, tid, body.code, body.reached, _actor(ctx))))


@router.post("/programs/{pid}/tickets/{tid}/comments")
def ticket_comment(pid: str, tid: str, body: CommentIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    return service.view(_mutate(ctx, pid, lambda root, d: service.comment(root, d, tid, body.text, _actor(ctx))))


@router.post("/programs/{pid}/tickets/{tid}/start")
def start_ticket(pid: str, tid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Open the ticket's work: a Design Studio project with the ticket brief as the starter prompt (parts), or an
    Assembly Studio document (integration). Auto-run by the specialist arrives with the orchestrator."""
    from aicad.platform.routers.projects import workspace_for

    _editor(ctx)
    org = ctx.require_org()
    root = _root(ctx)
    with store.lock(pid):
        doc = _load(ctx, pid)
        if doc["status"] not in ("active", "complete"):
            raise HTTPException(409, "Approve the brief first: tickets open when the plan is approved.")
        try:
            t = service.ticket(doc, tid)
        except OfficeInputError as e:
            raise HTTPException(404, str(e)) from e
        item = next((i for i in doc["items"] if i["id"] == t["item_id"]), {"name": t["title"]})
        starter = None
        if t["kind"] == "integration":
            if not t.get("assembly_id"):
                if "assembly" not in org_modules(ctx.db, org) and not ctx.god_on("bypass_paywall"):
                    raise HTTPException(402, {"message": "Assembly Studio isn't included in your plan. Unlock the "
                                                         "add-on to assemble this program.",
                                              "cta": "/app/modules/assembly"})
                from aicad.assembly import store as astore

                aroot = astore.org_root(get_settings().data_dir, org.id)
                adoc = astore.new_doc(f"{doc['name']} · {item['name']}"[:120], org.id, ctx.user.id, None)
                astore.save(aroot, adoc)
                service.link(root, doc, tid, _actor(ctx), assembly_id=adoc["id"])
                audit(ctx.db, "assembly.created", ctx.user, org.id, target=adoc["id"], office_program=pid)
        else:
            p = ctx.db.get(Project, t["project_id"]) if t.get("project_id") else None
            if p is None or p.org_id != org.id:
                p = Project(org_id=org.id, name=f"{doc['name']} · {t['title']}"[:120], description=t["brief"][:2000],
                            created_by=ctx.user.id)
                ctx.db.add(p)
                ctx.db.flush()
                workspace_for(p).mkdir(parents=True, exist_ok=True)
                audit(ctx.db, "project.created", ctx.user, org.id, target=p.id, name=p.name, office_program=pid)
                service.link(root, doc, tid, _actor(ctx), project_id=p.id)
            if not p.builds:
                starter = t["brief"]
        store.save(root, doc)
    track(ctx.db, "office_ticket_started", ctx.user, org.id, kind=t["kind"])
    ctx.db.commit()
    t = service.ticket(doc, tid)
    return {"ticket": t, "project_id": t.get("project_id"), "assembly_id": t.get("assembly_id"),
            "starter_prompt": starter, "program": service.view(doc)}


# ----------------------------------------------------------------------------- routes: activity + live events
@router.get("/programs/{pid}/activity")
def activity(pid: str, after: int = 0, limit: int = 100, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    _load(ctx, pid)
    return {"items": list(reversed(store.events(_root(ctx), pid, max(1, min(limit, 500)), after)))}


def _sse(key: str, backlog: list[dict[str, Any]], once: bool) -> StreamingResponse:
    async def gen():  # type: ignore[no-untyped-def]
        q = service.bus.subscribe(key)
        try:
            yield f"data: {json.dumps({'type': 'hello'})}\n\n"
            for ev in backlog:
                yield f"data: {json.dumps(ev, default=str)}\n\n"
            if once:
                return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), 15)
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            service.bus.unsubscribe(key, q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


@router.get("/programs/{pid}/events")
async def program_events(pid: str, after: int = 0, once: bool = False,
                         ctx: Ctx = Depends(verified_ctx)) -> StreamingResponse:
    _load(ctx, pid)
    backlog = store.events(_root(ctx), pid, 50, after) if after or once else []
    ctx.db.close()  # do not hold a DB connection for the life of the stream
    return _sse(pid, backlog, once)


@router.get("/events")
async def office_events(ctx: Ctx = Depends(verified_ctx)) -> StreamingResponse:
    key = f"org:{ctx.require_org().id}"
    ctx.db.close()
    return _sse(key, [], False)
