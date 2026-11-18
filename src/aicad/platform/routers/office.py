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
  POST   /api/office/programs/{pid}/gates/brief/approve     approve the (edited) plan: items and tickets open,
                                                            Archie drafts the skeleton and the ICD
  PATCH  /api/office/programs/{pid}/icd/interfaces/{iid}    edit an interface's numbers (ICD draft, at the gate)
  POST   /api/office/programs/{pid}/gates/icd/approve       approve the ICD: tickets released, placeholder assembly
  POST   /api/office/programs/{pid}/change-requests         raise an interface change request (Archie decides)
  GET    /api/office/programs/{pid}/assembly                the live program assembly (placeholders / real parts)
  POST   /api/office/programs/{pid}/assembly/rebuild        rebuild it from the skeleton (keeps approved parts)
  POST   /api/office/programs/{pid}/tickets/{tid}/move      board column
  PATCH  /api/office/programs/{pid}/tickets/{tid}           title, specialist, complexity
  POST   /api/office/programs/{pid}/tickets/{tid}/milestones
  POST   /api/office/programs/{pid}/tickets/{tid}/comments
  POST   /api/office/programs/{pid}/tickets/{tid}/start     open the part in Design Studio (or the assembly)
  POST   /api/office/programs/{pid}/run | /pause            the orchestrator: agents work the tickets (CD-006)
  POST   /api/office/programs/{pid}/tickets/{tid}/control   pause, resume, take_over, hand_back, reopen, retry
  GET    /api/office/programs/{pid}/activity[?after=seq]    event log
  GET    /api/office/programs/{pid}/events[?once=1]         live events (SSE); once: backlog only, then close
  GET    /api/office/programs/{pid}/timeline                 planned vs actual, agent lanes, critical path (CD-015)
  GET    /api/office/calibration                             the workspace's calibrated estimating rates (CD-015)
  GET    /api/office/programs/{pid}/deliverables             drawings, BOM, DFM summary, release gate (CD-014)
  POST   /api/office/programs/{pid}/deliverables             open Ortho's and Smithy's tickets now
  GET    /api/office/programs/{pid}/bom.csv                  the program BOM
  GET    /api/office/programs/{pid}/deliverables/assembly.{svg|pdf|dxf}   the assembly drawing (DRW-014)
  POST   /api/office/programs/{pid}/release                  release the program: one pack, every part tagged
  GET    /api/office/programs/{pid}/releases/{rev}/pack.zip  a program release pack
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from aicad.office import (
    OfficeInputError,
    calibration,
    deliverables,
    interfaces,
    orchestrator,
    planner,
    program_assembly,
    service,
    store,
    timeline,
)
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
    deliverables: bool = True  # Ortho and Smithy make the drawings, BOM and DFM summary after integration


class ProgramPatch(BaseModel):
    name: str | None = None
    concurrency: int | None = Field(default=None, ge=1, le=12)
    budget_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    deliverables: bool | None = None


class ReleaseIn(BaseModel):
    note: str = Field("", max_length=300)
    local_date: str | None = None
    tz: str | None = None


class ReplanIn(BaseModel):
    planner: str = "archie"
    notes: str = ""


class ApproveIn(BaseModel):
    plan: dict[str, Any] | None = None


class IcdEditIn(BaseModel):
    values: dict[str, Any]


class CrIn(BaseModel):
    interface: str
    values: dict[str, Any]
    reason: str = ""


class MoveIn(BaseModel):
    column: str


class TicketPatch(BaseModel):
    title: str | None = None
    specialist: str | None = None
    complexity: int | None = None
    priority: str | None = None


class ControlIn(BaseModel):
    action: str


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
    doc["deliverables_auto"] = body.deliverables
    service.emit(root, doc, "program.created", f"{ctx.user.name or 'Someone'} opened the program {name}.",
                 _actor(ctx))
    _start_planning(ctx, root, doc, kind)
    store.save(root, doc)
    if kind == "archie":
        _spawn(ctx, root, doc)
    audit(ctx.db, "office.program_created", ctx.user, org.id, target=doc["id"], planner=kind)
    track(ctx.db, "office_program_created", ctx.user, org.id, planner=kind)
    ctx.db.commit()
    return _view(doc)


@router.get("/programs/{pid}")
async def get_program(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    doc = _synced(ctx, pid)
    if (doc.get("orchestrator") or {}).get("state") == "running" and orchestrator.runner(pid) is None:
        orchestrator.ensure(_root(ctx), pid)  # resume after a restart (also done at startup)
    return {**_view(doc), "can_edit": ctx.role != "viewer"}


def _view(doc: dict[str, Any]) -> dict[str, Any]:
    from aicad.office import fake_agents

    v = service.view(doc)
    r = orchestrator.runner(doc["id"])
    v["orchestrator"] = {**v["orchestrator"], "active": len(r.tasks) if r else 0,
                         "simulated": fake_agents.enabled()}
    return v


@router.patch("/programs/{pid}")
def patch_program(pid: str, body: ProgramPatch, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    def fn(root: Path, doc: dict[str, Any]) -> None:
        if body.name is not None and body.name.strip():
            doc["name"] = " ".join(body.name.split())[:120]
        if body.concurrency is not None:
            doc["concurrency"] = body.concurrency
        if body.deliverables is not None:
            doc["deliverables_auto"] = body.deliverables
        if body.budget_tokens is not None:
            doc["budget"]["tokens"] = body.budget_tokens
            o = doc.get("orchestrator") or {}
            if o.get("warned") and orchestrator.budget_state(doc)["level"] == "ok":
                o["warned"] = False  # warn again at 80 % of the new budget
        service.emit(root, doc, "program.updated", f"{ctx.user.name or 'Someone'} updated the program settings.",
                     _actor(ctx))
    return _view(_mutate(ctx, pid, fn))


@router.delete("/programs/{pid}")
def delete_program(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    _editor(ctx)
    doc = _load(ctx, pid)
    orchestrator.forget(pid)
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
    return _view(doc)


@router.post("/programs/{pid}/gates/brief/approve")
def approve_brief(pid: str, body: ApproveIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    doc = _mutate(ctx, pid, lambda root, d: service.approve_plan(root, d, body.plan, _actor(ctx)))
    track(ctx.db, "office_brief_approved", ctx.user, doc["org_id"], tickets=len(doc["tickets"]),
          edited=bool(doc["plan"].get("edited")))
    ctx.db.commit()
    return _view(doc)


# ----------------------------------------------------------------------------- routes: interfaces (CD-010..013)
def _spawn_task(coro: Any) -> None:
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


@router.patch("/programs/{pid}/icd/interfaces/{iid}")
def edit_interface(pid: str, iid: str, body: IcdEditIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    return _view(_mutate(ctx, pid, lambda root, d: interfaces.edit(root, d, iid, body.values, _actor(ctx))))


@router.post("/programs/{pid}/gates/icd/approve")
async def approve_icd(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    from aicad.office import platform_env

    doc = _mutate(ctx, pid, lambda root, d: interfaces.approve(root, d, _actor(ctx)))
    _spawn_task(platform_env.build_program_assembly(_root(ctx), pid, ctx.require_org().id, ctx.user.id,
                                                    ctx.god_on("bypass_paywall")))
    audit(ctx.db, "office.icd_approved", ctx.user, doc["org_id"], target=pid, version=doc["icd"]["version"])
    track(ctx.db, "office_icd_approved", ctx.user, doc["org_id"], interfaces=len(doc["icd"]["interfaces"]))
    ctx.db.commit()
    orchestrator.poke(pid)
    return _view(doc)


@router.post("/programs/{pid}/change-requests")
async def change_request(pid: str, body: CrIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """The engineer raises an interface change request; Archie decides at once (rule + optional AI note)."""
    from aicad.office import platform_env

    cid: list[str] = []

    def fn(root: Path, d: dict[str, Any]) -> None:
        cid.append(interfaces.raise_cr(root, d, body.interface, body.values, body.reason, _actor(ctx))["id"])
    doc = _mutate(ctx, pid, fn)
    env = orchestrator.make_env(_root(ctx), {**doc, "orchestrator": {**(doc.get("orchestrator") or {}),
                                                                      "user_id": ctx.user.id,
                                                                      "god_tokens": ctx.god_on("bypass_tokens")}})
    res = await platform_env.decide_cr(_root(ctx), pid, cid[0], env if isinstance(env, platform_env.PlatformEnv)
                                       else None)
    audit(ctx.db, "office.change_request", ctx.user, doc["org_id"], target=pid, cr=cid[0], status=res.get("status"))
    ctx.db.commit()
    return {**_view(_load(ctx, pid)), "cr": res}


@router.get("/programs/{pid}/assembly")
def program_assembly_view(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    from aicad.assembly import store as astore

    doc = _load(ctx, pid)
    state = doc.get("assembly") or {}
    v = program_assembly.view(astore.org_root(get_settings().data_dir, ctx.require_org().id), doc) \
        if state.get("status") == "ready" else None
    items = {}
    for t in doc["tickets"]:
        if t["kind"] == "integration":
            continue
        p = (state.get("parts") or {}).get(t["item_id"]) or {}
        items[t["item_id"]] = {"ticket_id": t["id"], "key": t["key"], "title": t["title"], "column": t["column"],
                               "specialist": t["specialist"], "line": (t.get("run") or {}).get("line"),
                               "state": p.get("kind") or ("toolbox" if t["kind"] == "standard" else None),
                               "progress": t["progress"]}
    return {"status": state.get("status"), "summary": state.get("summary"), "clashes": state.get("clashes") or [],
            "at": state.get("at"), "view": v, "items": items, "can_edit": ctx.role != "viewer"}


@router.post("/programs/{pid}/assembly/rebuild")
async def rebuild_assembly(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    from aicad.office import platform_env

    def fn(root: Path, d: dict[str, Any]) -> None:
        if not interfaces.has_icd(d) or not interfaces.gate_open(d):
            raise OfficeInputError("Approve the interfaces (ICD) first: the program assembly is built from them.")
        d["assembly"] = {**(d.get("assembly") or {}), "status": "building"}
        service.emit(root, d, "assembly.rebuild", f"{ctx.user.name or 'Someone'} asked Fitz to rebuild the program "
                     "assembly.", _actor(ctx))
    doc = _mutate(ctx, pid, fn)
    _spawn_task(platform_env.build_program_assembly(_root(ctx), pid, ctx.require_org().id, ctx.user.id,
                                                    ctx.god_on("bypass_paywall")))
    return _view(doc)


# ----------------------------------------------------------------------------- routes: tickets
@router.post("/programs/{pid}/tickets/{tid}/move")
def move_ticket(pid: str, tid: str, body: MoveIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    def fn(root: Path, d: dict[str, Any]) -> None:
        t = service.ticket(d, tid)
        if orchestrator.run_of(t).get("status") in orchestrator.ACTIVE:
            who = orchestrator.run_of(t).get("agent_label") or "An agent"
            raise OfficeInputError(f"{who} is working on this ticket. Pause it or take over first.")
        service.move(root, d, tid, body.column, _actor(ctx))
        if body.column in ("ready", "backlog") and t.get("run"):
            t["run"] = None  # the engineer put it back in the queue: the office starts it afresh
            t["taken_over"] = False
    doc = _mutate(ctx, pid, fn)
    orchestrator.poke(pid)
    return _view(doc)


@router.patch("/programs/{pid}/tickets/{tid}")
def patch_ticket(pid: str, tid: str, body: TicketPatch, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    def fn(root: Path, d: dict[str, Any]) -> None:
        service.update(root, d, tid, _actor(ctx), title=body.title, specialist=body.specialist,
                       complexity=body.complexity)
        if body.priority is not None:
            orchestrator.set_priority(root, d, tid, body.priority, _actor(ctx))
    doc = _mutate(ctx, pid, fn)
    orchestrator.poke(pid)
    return _view(doc)


@router.post("/programs/{pid}/tickets/{tid}/milestones")
def ticket_milestone(pid: str, tid: str, body: MilestoneIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    return _view(_mutate(ctx, pid, lambda root, d: service.set_milestone(
        root, d, tid, body.code, body.reached, _actor(ctx))))


@router.post("/programs/{pid}/tickets/{tid}/comments")
def ticket_comment(pid: str, tid: str, body: CommentIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    def fn(root: Path, d: dict[str, Any]) -> None:
        c = service.comment(root, d, tid, body.text, _actor(ctx))
        orchestrator.on_comment(root, d, tid, c)
    doc = _mutate(ctx, pid, fn)
    orchestrator.poke(pid)
    return _view(doc)


@router.post("/programs/{pid}/tickets/{tid}/control")
async def ticket_control(pid: str, tid: str, body: ControlIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """The engineer's controls on one ticket (CD-009). Pause and take over stop a working agent at once."""
    stop = [False]

    def fn(root: Path, d: dict[str, Any]) -> None:
        stop[0] = orchestrator.control(root, d, tid, body.action, _actor(ctx))
    doc = _mutate(ctx, pid, fn)
    if stop[0]:
        await orchestrator.interrupt(pid, tid)
    orchestrator.poke(pid)
    return _view(doc)


@router.post("/programs/{pid}/run")
async def run_program(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Run: the orchestrator keeps up to ``concurrency`` agents working the tickets, by critical-path priority."""
    from aicad.platform.routers.projects import can_run_agent

    _editor(ctx)
    allowed, reason, cta = can_run_agent(ctx)
    if not allowed:
        raise HTTPException(402, {"message": reason, "cta": cta})
    doc = _mutate(ctx, pid, lambda root, d: orchestrator.start(
        root, d, _actor(ctx), user_id=ctx.user.id, god_tokens=ctx.god_on("bypass_tokens"),
        god_paywall=ctx.god_on("bypass_paywall")))
    orchestrator.ensure(_root(ctx), pid)
    track(ctx.db, "office_run", ctx.user, doc["org_id"], tickets=len(doc["tickets"]))
    ctx.db.commit()
    return _view(doc)


@router.post("/programs/{pid}/pause")
async def pause_program(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    doc = _mutate(ctx, pid, lambda root, d: orchestrator.pause(root, d, _actor(ctx)))
    orchestrator.poke(pid)
    return _view(doc)


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
        if t["kind"] == "deliverable":
            raise HTTPException(409, "Ortho and Smithy make the deliverables: see the Deliverables tab.")
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
            if not p.builds and not t.get("run"):
                starter = t["brief"]
        store.save(root, doc)
    track(ctx.db, "office_ticket_started", ctx.user, org.id, kind=t["kind"])
    ctx.db.commit()
    t = service.ticket(doc, tid)
    return {"ticket": t, "project_id": t.get("project_id"), "assembly_id": t.get("assembly_id"),
            "starter_prompt": starter, "program": _view(doc)}


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


# ----------------------------------------------------------------------------- routes: timeline + calibration
@router.get("/programs/{pid}/timeline")
def program_timeline(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Planned against actual (Gantt-lite): ticket rows, agent lanes, the critical path, waits, CR markers."""
    doc = _load(ctx, pid)
    return timeline.build(doc, store.events(_root(ctx), pid, limit=5000))


@router.get("/calibration")
def office_calibration(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """The workspace's estimating rates per specialist, how they were learned, and the accuracy trend."""
    return calibration.view(_root(ctx), service.profile())


# ----------------------------------------------------------------------------- routes: deliverables + release
ASM_FILES = {"assembly.svg": "image/svg+xml", "assembly.pdf": "application/pdf", "assembly.dxf": "application/dxf"}


def _gate_release(doc: dict[str, Any]) -> dict[str, Any]:
    """Can the program be released now? Blocking items in plain words."""
    blocking: list[str] = []
    core = [t for t in doc["tickets"] if t["kind"] != "deliverable"]
    if not core or any(t["column"] != "integrated" for t in core):
        n = sum(1 for t in core if t["column"] != "integrated")
        blocking.append(f"{n} ticket{'s are' if n != 1 else ' is'} not integrated yet: the first article must be "
                        "assembled before a release.")
    deliv = {t.get("deliverable"): t for t in doc["tickets"] if t["kind"] == "deliverable"}
    for code, what in (("drawings", "Ortho's drawings"), ("dfm", "Smithy's manufacturing review")):
        t = deliv.get(code)
        if t is None:
            blocking.append(f"{what} haven't been made yet." if code == "drawings" else f"{what} hasn't run yet.")
        elif t["column"] not in service.DONE_COLUMNS:
            blocking.append(f"{what} {'are' if code == 'drawings' else 'is'} not finished ({t['key']}).")
    if any((t.get("run") or {}).get("status") in orchestrator.ACTIVE for t in doc["tickets"]):
        blocking.append("An agent is still working on the program.")
    rels = doc.get("releases") or []
    from aicad import handoff

    return {"ready": not blocking, "blocking": blocking, "next_rev": handoff.REV_LETTERS[len(rels)]
            if len(rels) < len(handoff.REV_LETTERS) else None, "releases": list(reversed(rels)),
            "released": doc.get("released")}


@router.get("/programs/{pid}/deliverables")
def program_deliverables(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    from aicad.office import platform_env

    doc = _load(ctx, pid)
    dv = doc.get("deliverables") or {}
    drw = dv.get("drawings")
    asm_dir = store.program_dir(_root(ctx), pid) / "deliverables" / "assembly"
    return {"bom": platform_env.program_bom(doc), "dfm": dv.get("dfm"),
            "drawings": drw and {**drw, "assembly": {**(drw.get("assembly") or {}),
                                                     "urls": {n: f"/api/office/programs/{pid}/deliverables/{n}"
                                                              for n in ASM_FILES if (asm_dir / n).is_file()}}},
            "tickets": [service.ticket_view(t) for t in doc["tickets"] if t["kind"] == "deliverable"],
            "auto": doc.get("deliverables_auto", True), "gate": _gate_release(doc), "can_edit": ctx.role != "viewer"}


@router.post("/programs/{pid}/deliverables")
def open_deliverables(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Open Ortho's and Smithy's tickets now (when the program runs without automatic deliverables), or reopen them
    to make the deliverables again after a change."""
    def fn(root: Path, d: dict[str, Any]) -> None:
        core = [t for t in d["tickets"] if t["kind"] != "deliverable"]
        if not core or any(t["column"] != "integrated" for t in core):
            raise OfficeInputError("Deliverables are made from the integrated program: finish the integration first.")
        deliv = [t for t in d["tickets"] if t["kind"] == "deliverable"]
        if not deliv:
            service.add_deliverables(root, d)
        else:
            for t in deliv:
                if t["column"] in service.DONE_COLUMNS or (t.get("run") or {}).get("status") == "blocked":
                    orchestrator.control(root, d, t["id"], "reopen", _actor(ctx))
        o = orchestrator.orch(d)
        if o.get("state") == "complete":
            o["state"] = "idle"  # Run picks the deliverables up
    doc = _mutate(ctx, pid, fn)
    orchestrator.poke(pid)
    return _view(doc)


@router.get("/programs/{pid}/bom.csv")
def program_bom_csv(pid: str, ctx: Ctx = Depends(verified_ctx)) -> Response:
    from aicad.office import platform_env

    doc = _load(ctx, pid)
    data = deliverables.bom_csv(platform_env.program_bom(doc))
    track(ctx.db, "download", ctx.user, doc["org_id"], file="office/bom.csv")
    ctx.db.commit()
    return Response(data, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{_fname(doc["name"])}_BOM.csv"'})


@router.get("/programs/{pid}/deliverables/{name}")
def assembly_drawing_file(pid: str, name: str, download: bool = False, ctx: Ctx = Depends(verified_ctx)) -> FileResponse:
    doc = _load(ctx, pid)
    if name not in ASM_FILES:
        raise HTTPException(404)
    f = store.program_dir(_root(ctx), pid) / "deliverables" / "assembly" / name
    if not f.is_file():
        raise HTTPException(404, "Ortho hasn't drawn the assembly yet.")
    headers = {"Cache-Control": "no-store"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{_fname(doc["name"])}_assembly.{name.split(".")[-1]}"'
    return FileResponse(f, media_type=ASM_FILES[name], headers=headers)


def _fname(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:60] or "program"


_release_locks: dict[str, asyncio.Lock] = {}


@router.post("/programs/{pid}/release")
async def release_program(pid: str, body: ReleaseIn | None = None, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Release the program: every part it makes is issued at its next revision through the release gate (frozen
    issue drawing, DFM report) and tagged in its project; one pack holds the parts' STEP, the assembly STEP, the
    drawings (PDF, DXF), the BOM, the DFM summary, the ICD and the program file (.fwprog)."""
    from aicad import handoff as hand
    from aicad.assembly import locks
    from aicad.assembly import service as aservice
    from aicad.assembly import store as astore
    from aicad.office import platform_env
    from aicad.platform.collab.tables import Tag
    from aicad.platform.routers import handoff as hroute
    from aicad.platform.routers import mod_drawings, mod_native
    from aicad.platform.routers import projects as prj

    _editor(ctx)
    org = ctx.require_org()
    root = _root(ctx)
    lock = _release_locks.setdefault(pid, asyncio.Lock())
    async with lock:
        doc = _load(ctx, pid)
        gate = _gate_release(doc)
        if not gate["ready"]:
            raise HTTPException(409, {"message": "The program can't be released yet: " + " ".join(gate["blocking"]),
                                      "blocking": gate["blocking"]})
        rev = gate["next_rev"]
        by = ctx.user.name or ctx.user.email
        day = mod_drawings.local_date(body.local_date, body.tz)
        note = body.note.strip() or ("Initial release" if not doc.get("releases") else "Program changed")
        has_drawings = "drawings" in org_modules(ctx.db, org) or ctx.god_on("bypass_paywall")
        files: dict[str, bytes] = {}
        released: list[dict[str, Any]] = []
        for mp in deliverables.make_parts(doc):
            t = mp["ticket"]
            p = ctx.db.get(Project, mp["project_id"])
            if p is None or p.org_id != org.id:
                raise HTTPException(409, f"{t['title']}: its Design Studio project is gone.")
            try:
                rec = await hroute.issue(p, by=by, by_id=ctx.user.id, note=f"{doc['name']} rev {rev}: {note}",
                                         has_drawings=has_drawings, day=day, reuse_current=True)
            except hroute.ReleaseBlocked as e:
                raise HTTPException(409, {"message": f"{t['key']} {t['title']}: {e}", "blocking": e.blocking}) from None
            ws = prj.workspace_for(p)
            name = hand._safe(t["title"])
            files[f"parts/{name}_rev{rec['rev']}.step"] = (ws / "out" / "part.step").read_bytes()
            ddir = ws / "releases" / rec["rev"] / "drawing"
            for ext in ("pdf", "dxf"):
                f = ddir / f"sheet.{ext}"
                if f.is_file():
                    files[f"drawings/{name}_rev{rec['rev']}.{ext}"] = f.read_bytes()
            main_ws = prj.main_workspace(p)
            mrev = prj.current_revision(main_ws)
            tag = f"{doc['key']} Rev {rev}"
            if mrev is not None and not ctx.db.scalar(select(Tag).where(Tag.project_id == p.id, Tag.name == tag)):
                ctx.db.add(Tag(project_id=p.id, name=tag, revision=mrev, created_by=ctx.user.id,
                               note=f"Released with the Design Office program {doc['name']} (rev {rev}) as part rev "
                                    f"{rec['rev']}."))
                audit(ctx.db, "tag.created", ctx.user, org.id, target=p.id, name=tag, revision=mrev, office_program=pid)
            released.append({"ticket": t["id"], "key": t["key"], "title": t["title"], "project_id": p.id,
                             "rev": rec["rev"], "reused": bool(rec.get("reused")), "model_rev": mrev, "tag": tag,
                             "pack_sha256": rec.get("pack_sha256")})
        ctx.db.commit()
        # the assembly STEP (the final assembly as it is now) and the assembly drawing stamped with the letter
        aroot = astore.org_root(get_settings().data_dir, org.id)
        fid = (doc.get("assembly") or {}).get("final")
        rel_dir = store.program_dir(root, pid) / "releases" / rev
        if fid:
            async with locks.hold(fid, locks.OFFICE):
                final = astore.load(aroot, fid)
                if final is not None and final["instances"]:
                    try:
                        await aservice.export_step(aroot, org.id, final)
                    except Exception as e:  # noqa: BLE001
                        raise HTTPException(409, f"The assembly STEP could not be exported: {e}") from None
            f = astore.doc_dir(aroot, fid) / "assembly.step"
            if f.is_file():
                files[f"assembly/{_fname(doc['name'])}_rev{rev}.step"] = f.read_bytes()
            asm = await platform_env.assembly_drawing(root, pid, org.id, by, rev, rel_dir / "assembly", has_drawings)
            for ext in ("pdf", "dxf"):
                f = rel_dir / "assembly" / f"assembly.{ext}"
                if asm.get("ok") and f.is_file():
                    files[f"drawings/{_fname(doc['name'])}_assembly_rev{rev}.{ext}"] = f.read_bytes()
        b = platform_env.program_bom(doc)
        files["bom.csv"] = deliverables.bom_csv(b).encode("utf-8")
        dfm = (doc.get("deliverables") or {}).get("dfm")
        if dfm:
            files["dfm/dfm_summary.csv"] = deliverables.dfm_csv(dfm).encode("utf-8")
            files["dfm/dfm_summary.json"] = json.dumps(dfm, indent=1, ensure_ascii=False).encode("utf-8")
        if doc.get("icd"):
            files["icd/icd.json"] = json.dumps({"version": doc["icd"]["version"], "units": "mm",
                                                "skeleton": {k: v for k, v in doc["skeleton"].items()
                                                             if k in ("csys", "datums", "axes", "envelope", "items")},
                                                "interfaces": doc["icd"]["interfaces"]},
                                               indent=1, ensure_ascii=False).encode("utf-8")
        try:
            prog, _d = await mod_native.program_bytes(ctx, pid)
            files[f"{_fname(doc['name'])}.fwprog"] = prog
        except HTTPException as e:
            raise HTTPException(409, f"The program file could not be written: {e.detail}") from None
        record = {"rev": rev, "date": day, "by": by, "by_id": ctx.user.id, "note": note,
                  "issued_at": datetime.now(UTC).replace(microsecond=0).isoformat(), "parts": released,
                  "icd_version": (doc.get("icd") or {}).get("version"), "bom_lines": len(b["rows"])}
        files["README.txt"] = deliverables.readme(doc, record, list(files) + ["README.txt", "manifest.json"],
                                                  released, b, dfm).encode("utf-8")
        manifest = {"program": doc["name"], "release": {k: record[k] for k in ("rev", "date", "by", "note", "issued_at")},
                    "parts": released, "note": deliverables.PACK_NOTE,
                    "files": {k: {"sha256": hashlib.sha256(v).hexdigest(), "bytes": len(v)} for k, v in sorted(files.items())}}
        files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
        buf = io.BytesIO()
        rootname = f"{_fname(doc['name'])}_rev{rev}"
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for k in sorted(files):
                info = zipfile.ZipInfo(f"{rootname}/{k}", hand.ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, files[k])
        pack = buf.getvalue()
        rel_dir.mkdir(parents=True, exist_ok=True)
        (rel_dir / "pack.zip").write_bytes(pack)
        record.update(pack_sha256=hashlib.sha256(pack).hexdigest(), pack_bytes=len(pack), files=sorted(files))

        def fn(r: Path, d: dict[str, Any]) -> None:
            d.setdefault("releases", []).append(record)
            d["released"] = {k: record[k] for k in ("rev", "date", "by", "issued_at")}
            g = service.gate(d, "release")
            g.update(status="approved", by=by, at=store.now(), rev=rev, note=f"Released rev {rev}")
            service.emit(r, d, "program.released", f"{by} released {d['name']} rev {rev}: {len(released)} part"
                         f"{'s' if len(released) != 1 else ''} issued and tagged, drawings, BOM, DFM summary, ICD and "
                         "the program file in one pack.", _actor(ctx), rev=rev)
        doc = _mutate(ctx, pid, fn)
    audit(ctx.db, "office.program_released", ctx.user, org.id, target=pid, rev=rev, parts=len(released),
          files=len(files))
    track(ctx.db, "office_program_released", ctx.user, org.id, parts=len(released))
    ctx.db.commit()
    return {"release": {k: v for k, v in record.items() if k != "by_id"}, "program": _view(doc)}


@router.get("/programs/{pid}/releases/{rev}/pack.zip")
def program_release_pack(pid: str, rev: str, ctx: Ctx = Depends(verified_ctx)) -> FileResponse:
    import re

    doc = _load(ctx, pid)
    if not re.fullmatch(r"[A-Z]{1,3}", rev or ""):
        raise HTTPException(404)
    f = store.program_dir(_root(ctx), pid) / "releases" / rev / "pack.zip"
    if not f.is_file():
        raise HTTPException(404, "No such release")
    audit(ctx.db, "office.release_downloaded", ctx.user, doc["org_id"], target=pid, rev=rev)
    ctx.db.commit()
    return FileResponse(f, media_type="application/zip", filename=f"{_fname(doc['name'])}_rev{rev}.zip")


# ----------------------------------------------------------------------------- orchestrator lifecycle
async def _resume_on_startup() -> None:
    orchestrator.resume_all(get_settings().data_dir)


router.on_startup.append(_resume_on_startup)
router.on_shutdown.append(orchestrator.shutdown)
