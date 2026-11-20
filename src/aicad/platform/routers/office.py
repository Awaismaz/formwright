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
  POST   /api/office/programs/{pid}/plan/answers            answer Archie's questions on a design-graph plan
  POST   /api/office/programs/{pid}/gates/brief/approve     approve the (edited) plan: items and tickets open,
                                                            Archie drafts the skeleton and the ICD
  POST   /api/office/programs/{pid}/gates/express           small program: plan + interfaces in one step, then Run
  PATCH  /api/office/programs/{pid}/icd/interfaces/{iid}    edit an interface's numbers (ICD draft, at the gate)
  POST   /api/office/programs/{pid}/icd/separate            keep unconnected parts separate (or connect them again)
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
  GET    /api/office/programs/{pid}/releases/{rev}/pack.zip  a program release pack (immutable once written)
  POST   /api/office/programs/{pid}/tickets/{tid}/review     the per-part review gate: approve / request changes
  POST   /api/office/programs/{pid}/ecn                      raise a change notice on a released program (CD-024)
  GET    /api/office/programs/{pid}/supervisor               Archie's log, rule overrides, relaxed checks (WORKLIST 49)
  POST   /api/office/programs/{pid}/supervisor/run           ask Archie to look at the program now
  POST   /api/office/programs/{pid}/supervisor/actions/{aid}/decide   yes / no to one of Archie's major proposals
  POST   /api/office/programs/{pid}/supervisor/actions/{aid}/undo     undo one of Archie's actions
  POST   /api/office/programs/{pid}/revision/preview         what a program revision keeps, re-places, redesigns,
                                                             adds and removes (nothing changes)
  GET    /api/office/programs/{pid}/preview                  the dimensioned 3D preview of the layout (WORKLIST 47)
  POST   /api/office/programs/{pid}/preview                  the same for the plan review's unsaved edits
  GET    /api/office/programs/{pid}/preview/compare/{key}    before / after previews of a revision
  POST   /api/office/programs/{pid}/revision                 revise the program (ICD v+1) at any stage
  POST   /api/office/programs/{pid}/revisions/{rid}/undo     undo the latest revision while nothing was rebuilt
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

from aicad.master import run as master_run
from aicad.office import (
    OfficeInputError,
    archie_chat,
    calibration,
    deliverables,
    interfaces,
    orchestrator,
    planner,
    program_assembly,
    roster,
    service,
    store,
    supervisor,
    timeline,
)
from aicad.office import ecn as ecn_mod
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
    # None: the default, at most the workspace's remaining wallet (a trial wallet is smaller than 3,000)
    budget_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    # Ortho and Smithy make the drawings, BOM and DFM summary after integration: True always, False only when asked,
    # None (default) automatic: on, except for a small program whose brief doesn't ask for them (PD-93)
    deliverables: bool | None = None
    review_gate: bool = False  # every part waits for the engineer's approval after Gage passes it (CD-023)
    threads: dict[str, int] | None = None  # per-agent threads (CD-027); default one per designer (PD-66)


class ProgramPatch(BaseModel):
    name: str | None = None
    concurrency: int | None = Field(default=None, ge=1, le=12)
    budget_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    threads: dict[str, int] | None = None
    deliverables: bool | None = None
    review_gate: bool | None = None


class ReviewIn(BaseModel):
    decision: str  # "approve" | "changes"
    note: str = Field("", max_length=2000)


class EcnIn(BaseModel):
    reason: str = Field(..., max_length=600)
    items: list[str] = Field(default_factory=list, max_length=200)
    interface: str | None = None
    values: dict[str, Any] | None = None


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


class SeparateIn(BaseModel):
    items: list[str] | None = None  # None: every part the layout flags as unconnected now
    keep: bool = True               # False: undo (the part blocks again until an interface connects it)


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


class ArchieIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class ArchieActIn(BaseModel):
    message: str
    action: str
    decision: str = "apply"  # "apply" | "dismiss"


class RevisionIn(BaseModel):
    changes: list[dict[str, Any]]
    reason: str = ""


class SupervisorDecideIn(BaseModel):
    choice: str  # "approve" | "decline"


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
    from aicad.graph import office as design_graph

    graphed = None  # FW_DESIGN_GRAPH=1: intent -> design graph -> plan (architecture v2, PD-110)
    try:
        if design_graph.enabled():
            graphed = await design_graph.plan(store.program_dir(root, pid) / "archie", doc["name"], doc["brief"],
                                              notes, budget)
            text, usd, failed = graphed.narrative, graphed.cost_usd, graphed.plan is None
        else:
            text, usd = await planner.run_agent(store.program_dir(root, pid) / "archie", doc["name"], doc["brief"],
                                                notes, budget)
    except Exception:  # any agent failure falls back to the standard planner
        log.exception("Archie planning failed")
        failed = True
    plan = graphed.plan if graphed is not None else planner.parse_plan(text)
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
            plan, scope_note = planner.finish(plan, doc["name"], doc["brief"])
            if graphed is not None:
                design_graph.attach(plan, graphed)
            service.set_plan(root, doc, plan, archie, narrative=planner.narrative(text), note=scope_note)
        else:
            why = ("Archie stopped before finishing the plan" if failed else
                   "Archie's answer did not contain a plan that could be used")
            std, scope_note = planner.finish(planner.standard_plan(doc["name"], doc["brief"]), doc["name"],
                                             doc["brief"])
            service.set_plan(root, doc, std, archie,
                             note=f"{why}, so this is the standard breakdown. Edit it, or ask Archie again."
                             + (f" {scope_note}" if scope_note else ""))
        need_master = master_run.route(root, doc)  # WORKLIST 50: the layout path, decided and recorded
        store.save(root, doc)
    if need_master:
        _spawn_master(root, pid, org_id, user_id, god_tokens)


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
        std, scope_note = planner.finish(planner.standard_plan(doc["name"], doc["brief"]), doc["name"], doc["brief"])
        service.set_plan(root, doc, std, service.agent_actor("archie"), note=scope_note)
        doc["_master_spawn"] = master_run.route(root, doc)


def _spawn_master(root: Path, pid: str, org_id: str, user_id: str, god_tokens: bool) -> None:
    """The master turn of the planning phase (WORKLIST 50), in the background."""
    t = asyncio.create_task(master_run.task(root, pid, org_id, user_id, god_tokens))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def _master_after(ctx: Ctx, root: Path, doc: dict[str, Any]) -> None:
    """After a request saved a plan the master path needs: start the master turn."""
    if doc.pop("_master_spawn", False):
        _spawn_master(root, doc["id"], ctx.require_org().id, ctx.user.id, ctx.god_on("bypass_tokens"))


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
    budget = body.budget_tokens
    if budget is None:
        budget = service.default_budget(org.token_balance - metering.reserved(org.id), ctx.god_on("bypass_tokens"))
    doc = service.new_program(name, brief, org.id, ctx.user.id, body.concurrency, budget, kind)
    doc["deliverables_auto"] = True if body.deliverables is None else body.deliverables
    doc["deliverables_mode"] = "auto" if body.deliverables is None else ("on" if body.deliverables else "off")
    doc["review_gate"] = body.review_gate
    service.set_threads(doc, body.threads if body.threads is not None else service.default_threads())
    service.emit(root, doc, "program.created", f"{ctx.user.name or 'Someone'} opened the program {name}.",
                 _actor(ctx))
    _start_planning(ctx, root, doc, kind)
    spawn_master = bool(doc.pop("_master_spawn", False))
    store.save(root, doc)
    if kind == "archie":
        _spawn(ctx, root, doc)
    elif spawn_master:
        _spawn_master(root, doc["id"], org.id, ctx.user.id, ctx.god_on("bypass_tokens"))
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
    mm = (v.get("plan") or {}).get("master")
    if isinstance(mm, dict) and "measure" in mm:  # the raw measurement stays server-side (it can be large)
        v["plan"] = {**v["plan"], "master": {k: x for k, x in mm.items() if k != "measure"}}
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
            doc["deliverables_mode"] = "on" if body.deliverables else "off"
            doc["deliverables_why"] = None
        if body.review_gate is not None and bool(body.review_gate) != bool(doc.get("review_gate")):
            doc["review_gate"] = bool(body.review_gate)
            if not body.review_gate:  # switched off: parts waiting for review go on as Gage approved them
                for t in doc["tickets"]:
                    if (t.get("run") or {}).get("status") == "awaiting_review":
                        orchestrator.review_decision(root, doc, t["id"], "approve", "Review gate switched off.",
                                                     _actor(ctx))
            service.emit(root, doc, "program.review_gate", f"{ctx.user.name or 'Someone'} switched the per-part review "
                         f"gate {'on: every part waits for your approval after Gage' if body.review_gate else 'off'}.",
                         _actor(ctx), on=bool(body.review_gate))
        if body.threads is not None:
            before = service.threads_of(doc) or {}
            after = service.set_threads(doc, {**before, **body.threads})
            changed = [f"{roster.agent(k)['name']} {v}" for k, v in after.items() if before.get(k) != v]
            if changed:
                service.emit(root, doc, "program.threads", f"{ctx.user.name or 'Someone'} set agent threads: "
                             f"{', '.join(changed)}.", _actor(ctx), threads=after)
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
        flag["master"] = bool(doc.pop("_master_spawn", False))

    flag: dict[str, bool] = {}
    doc = _mutate(ctx, pid, fn)
    if kind == "archie":
        _spawn(ctx, _root(ctx), doc, body.notes)
    elif flag.get("master"):
        doc["_master_spawn"] = True
        _master_after(ctx, _root(ctx), doc)
    return _view(doc)


class PlanAnswersIn(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


@router.post("/programs/{pid}/plan/answers")
async def answer_plan_questions(pid: str, body: PlanAnswersIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Answers to Archie's clarifying questions on a design-graph plan (PD-110). Questions about the housing, the
    bearings or the material are applied by code at once; any other answer goes back to Archie with the brief."""
    from aicad.graph import office as design_graph

    again: dict[str, str] = {}

    def fn(root: Path, doc: dict[str, Any]) -> None:
        if doc["status"] != "plan_review":
            raise OfficeInputError("There is no plan waiting for answers.")
        out, notes = design_graph.answer(doc, body.answers)
        archie = service.agent_actor("archie")
        if out is not None:
            if out.plan is None:
                raise OfficeInputError("That answer can't be built: " + (out.error or "the design is incomplete"))
            p, note = planner.finish(out.plan, doc["name"], doc["brief"])
            design_graph.attach(p, out)
            service.set_plan(root, doc, p, archie, narrative=out.narrative, note=note)
            again["master"] = "1" if master_run.route(root, doc) else ""
        elif notes:
            _start_planning(ctx, root, doc, "archie", notes)
            again["notes"] = notes
        else:
            raise OfficeInputError("Choose an answer for at least one question.")
        service.emit(root, doc, "plan.answered", f"{ctx.user.name or 'Someone'} answered Archie's questions.",
                     _actor(ctx), answers={k: str(v)[:120] for k, v in body.answers.items()})

    doc = _mutate(ctx, pid, fn)
    if again.get("notes"):
        _spawn(ctx, _root(ctx), doc, again["notes"])
    elif again.get("master"):
        doc["_master_spawn"] = True
        _master_after(ctx, _root(ctx), doc)
    return _view(doc)


@router.post("/programs/{pid}/gates/brief/approve")
async def approve_brief(pid: str, body: ApproveIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    doc = _mutate(ctx, pid, lambda root, d: service.approve_plan(root, d, body.plan, _actor(ctx)))
    track(ctx.db, "office_brief_approved", ctx.user, doc["org_id"], tickets=len(doc["tickets"]),
          edited=bool(doc["plan"].get("edited")))
    ctx.db.commit()
    _look_at_layout(ctx, pid, doc)
    return _view(doc)


@router.post("/programs/{pid}/gates/express")
async def approve_express(pid: str, body: ApproveIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """The light path for a small program (PD-93): one click approves the plan and, when Archie's interfaces have no
    problem, the interfaces too, and the office starts building. With a problem it stops at the interfaces gate as
    usual (nothing is skipped). What was approved is recorded on the program (``express``) and in the activity."""
    from aicad.office import icd as icd_mod
    from aicad.office import platform_env
    from aicad.platform.routers.projects import can_run_agent

    actor = _actor(ctx)

    def fn(root: Path, d: dict[str, Any]) -> None:
        if not service.express_ok(d):
            raise OfficeInputError("One-step approval is for a small program whose plan waits for approval.")
        service.approve_plan(root, d, body.plan, actor)
        ic = d.get("icd") or {}
        parts = [p["name"] for s in d["plan"]["subassemblies"] for p in s["parts"]]
        rec: dict[str, Any] = {"at": store.now(), "by": actor.get("name"), "parts": parts,
                               "tickets": len(d["tickets"]), "approved": False, "run": False}
        if ic and service.gate(d, "icd")["status"] == "pending" and not ic.get("problems"):
            interfaces.approve(root, d, actor, with_plan=True)
            notes = icd_mod.warnings(d["skeleton"], ic["interfaces"])
            rec.update(approved=True, icd_version=ic["version"], interfaces=len(ic["interfaces"]),
                       kinds=sorted({icd_mod.KIND_LABEL.get(f["kind"], f["kind"]) for f in ic["interfaces"]}),
                       warnings=notes)
            service.emit(root, d, "gate.express", f"{actor.get('name', 'Someone')} approved the plan ({len(parts)} "
                         f"parts: {', '.join(parts)}) and the interfaces (ICD v{ic['version']}, "
                         f"{len(ic['interfaces'])} interfaces, 0 problems"
                         + (f"; note: {notes[0]}" if notes else "") + ") in one step.", actor)
        elif ic:
            rec["problems"] = len(ic.get("problems") or [])
        d["express"] = rec

    doc = _mutate(ctx, pid, fn)
    track(ctx.db, "office_express", ctx.user, doc["org_id"], tickets=len(doc["tickets"]),
          approved=bool(doc["express"]["approved"]))
    ctx.db.commit()
    if not doc["express"]["approved"]:  # stops at the interfaces gate: Archie looks at the layout as usual
        _look_at_layout(ctx, pid, doc)
        return _view(doc)
    root = _root(ctx)
    _spawn_task(platform_env.build_program_assembly(root, pid, ctx.require_org().id, ctx.user.id,
                                                    ctx.god_on("bypass_paywall")))
    allowed, reason, _cta = can_run_agent(ctx)

    def run(r: Path, d: dict[str, Any]) -> None:
        if not allowed:
            d["express"]["run_blocked"] = reason
            return
        try:
            orchestrator.start(r, d, actor, user_id=ctx.user.id, god_tokens=ctx.god_on("bypass_tokens"),
                               god_paywall=ctx.god_on("bypass_paywall"))
            d["express"]["run"] = True
        except OfficeInputError as e:  # e.g. the budget: approved, but Run waits for the engineer
            d["express"]["run_blocked"] = str(e)

    doc = _mutate(ctx, pid, run)
    if doc["express"].get("run"):
        orchestrator.ensure(root, pid)
    return _view(doc)


def _look_at_layout(ctx: Ctx, pid: str, doc: dict[str, Any]) -> None:
    """Archie looks at the drafted layout and tells the engineer in the program chat (founder 2026-11-19, PD-73)."""
    from aicad.office import fake_agents, visual_office

    if (doc.get("icd") or {}).get("status") != "draft" or ctx.role == "viewer":
        return
    from aicad.platform.routers.projects import can_run_agent

    mode = "simulated" if fake_agents.enabled() else "ai" if can_run_agent(ctx)[0] else "none"
    _spawn_task(visual_office.layout_look(_root(ctx), pid, org_id=ctx.require_org().id, user_id=ctx.user.id,
                                          god=ctx.god_on("bypass_tokens"), mode=mode))


# ----------------------------------------------------------------------------- routes: interfaces (CD-010..013)
def _spawn_task(coro: Any) -> None:
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


@router.patch("/programs/{pid}/icd/interfaces/{iid}")
def edit_interface(pid: str, iid: str, body: IcdEditIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    return _view(_mutate(ctx, pid, lambda root, d: interfaces.edit(root, d, iid, body.values, _actor(ctx))))


@router.post("/programs/{pid}/icd/fix")
async def fix_icd(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """"Fix with Archie" at the interfaces gate. Step 1: the smallest safe number changes (deterministic, no AI, no
    tokens; CD-028). Step 2, when problems remain: Archie supervising (WORKLIST 49) diagnoses what numbers can't fix
    and acts (minor: done and logged; major: plan changes asked in the program chat with clickable choices). The answer
    says what was fixed, what he did or proposes, and what is still open and why."""
    _editor(ctx)
    doc = _load(ctx, pid)
    try:
        res = await supervisor.fix_gate(_root(ctx), pid, _actor(ctx), _sup_env(ctx, doc))
    except OfficeInputError as e:
        raise HTTPException(409, str(e)) from e
    doc = _load(ctx, pid)
    if res.get("archie") and not (doc.get("icd") or {}).get("problems"):
        _look_at_layout(ctx, pid, doc)  # cleared: Archie looks at the new layout once
    return {**_view(doc), "fix": res}


@router.post("/programs/{pid}/icd/separate")
async def keep_separate(pid: str, body: SeparateIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """The engineer's decision at the ICD gate: parts with no interface are meant to be separate (a kit, shafts made
    on their own). Recorded in the ICD history; those parts become an acknowledged warning instead of blocking."""
    out: list[list[str]] = []
    doc = _mutate(ctx, pid, lambda root, d: out.append(interfaces.keep_separate(root, d, body.items, body.keep,
                                                                                _actor(ctx))))
    audit(ctx.db, "office.icd_separate" if body.keep else "office.icd_connect", ctx.user, doc["org_id"], target=pid,
          items=out[0])
    ctx.db.commit()
    if body.keep and not doc["icd"].get("problems"):  # the gate can now be approved: Archie looks again, once
        _look_at_layout(ctx, pid, doc)
    return _view(doc)


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
    clash = program_assembly.clash_status(state)  # the one clash count every view shows
    summary = state.get("summary")
    if summary and state.get("status") == "ready":
        summary = summary.rstrip(".") + "; " + clash["text"] + "."
    return {"status": state.get("status"), "summary": summary, "clashes": state.get("clashes") or [], "clash": clash,
            "at": state.get("at"), "view": v, "items": items, "can_edit": ctx.role != "viewer",
            "check": state.get("check"),  # PD-71: the advisory whole-program clash check
            "looks": _looks(ctx, pid, doc)}  # PD-73: the visual checks (layout, each level), advisory


def _looks(ctx: Ctx, pid: str, doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The latest visual check of the layout and of each integrated level (advisory), newest level last."""
    from aicad.assembly import store as astore
    from aicad.assembly import visual

    out: list[dict[str, Any]] = []
    lay = visual.public(visual.load_record(store.program_dir(_root(ctx), pid) / "visual" / "layout"))
    if lay:
        out.append({**lay, "level": "layout", "name": "Layout (interfaces gate)",
                    "image": f"/api/office/programs/{pid}/visual/layout.png" if lay.get("status") == "done" else None})
    aroot = astore.org_root(get_settings().data_dir, ctx.require_org().id)
    for t in doc["tickets"]:
        if t["kind"] != "integration" or not t.get("assembly_id"):
            continue
        rec = visual.public(visual.load_record(astore.doc_dir(aroot, t["assembly_id"]) / "visual"))
        if rec:
            out.append({**rec, "level": t["item_id"], "name": t["title"],
                        "image": f"/api/m/assembly/assemblies/{t['assembly_id']}/visual.png"
                        if rec.get("status") == "done" else None})
    return out


@router.post("/programs/{pid}/visual/layout")
async def look_at_layout(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Archie looks at the drafted layout again (quick checks, the visual check) and says what he sees in the chat."""
    from aicad.office import fake_agents, visual_office
    from aicad.platform.routers.projects import can_run_agent

    _editor(ctx)
    doc = _load(ctx, pid)
    if (doc.get("icd") or {}).get("status") != "draft":
        raise HTTPException(409, "Archie looks at the layout while the interfaces wait for your approval.")
    mode = "simulated" if fake_agents.enabled() else "ai" if can_run_agent(ctx)[0] else "none"
    await visual_office.layout_look(_root(ctx), pid, org_id=ctx.require_org().id, user_id=ctx.user.id,
                                    god=ctx.god_on("bypass_tokens"), mode=mode)
    return _view(_load(ctx, pid))


@router.get("/programs/{pid}/visual/layout.png")
def layout_png(pid: str, ctx: Ctx = Depends(verified_ctx)) -> Any:
    from fastapi.responses import FileResponse

    _load(ctx, pid)
    f = store.program_dir(_root(ctx), pid) / "visual" / "layout" / "assembly.png"
    if not f.is_file():
        raise HTTPException(404, "No picture yet")
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "no-cache"})


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
        if orchestrator.run_of(t).get("status") == "awaiting_review" and body.column in ("approved", "changes_requested"):
            if body.column == "changes_requested":  # the review gate needs the note that goes to the designer
                raise OfficeInputError("Request changes from the ticket with a note for the designer.")
            orchestrator.review_decision(root, d, tid, "approve", "", _actor(ctx))
            return
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


@router.post("/programs/{pid}/tickets/{tid}/review")
def ticket_review(pid: str, tid: str, body: ReviewIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """The per-part review gate (CD-023): approve (the part goes on to assembly) or request changes with a note
    (the ticket reopens and the note is the designer's next instruction)."""
    doc = _mutate(ctx, pid, lambda root, d: orchestrator.review_decision(root, d, tid, body.decision, body.note,
                                                                         _actor(ctx)))
    orchestrator.poke(pid)
    return _view(doc)


@router.post("/programs/{pid}/ecn")
async def raise_ecn(pid: str, body: EcnIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Raise an engineering change notice on a released program (CD-024): the affected parts reopen with the
    reason, the office reworks them, and the next release issues only them at a new letter."""
    from aicad.office import platform_env
    from aicad.platform.routers.projects import can_run_agent

    _editor(ctx)
    allowed, reason, cta = can_run_agent(ctx)
    if not allowed:
        raise HTTPException(402, {"message": reason, "cta": cta})
    out: list[dict[str, Any]] = []

    def fn(root: Path, d: dict[str, Any]) -> None:
        out.append(ecn_mod.open_ecn(root, d, body.reason, body.items, _actor(ctx), body.interface, body.values))
    doc = _mutate(ctx, pid, fn)
    e = out[0]
    if e.get("cr_id"):
        env = orchestrator.make_env(_root(ctx), {**doc, "orchestrator": {**(doc.get("orchestrator") or {}),
                                                                          "user_id": ctx.user.id,
                                                                          "god_tokens": ctx.god_on("bypass_tokens")}})
        await platform_env.decide_cr(_root(ctx), pid, e["cr_id"], env if isinstance(env, platform_env.PlatformEnv)
                                     else None)
    doc = _mutate(ctx, pid, lambda root, d: orchestrator.start(
        root, d, _actor(ctx), user_id=ctx.user.id, god_tokens=ctx.god_on("bypass_tokens"),
        god_paywall=ctx.god_on("bypass_paywall")))
    orchestrator.ensure(_root(ctx), pid)
    audit(ctx.db, "office.ecn_raised", ctx.user, doc["org_id"], target=pid, ecn=e["id"], parts=len(e["items"]))
    track(ctx.db, "office_ecn_raised", ctx.user, doc["org_id"], parts=len(e["items"]))
    ctx.db.commit()
    return {**_view(doc), "ecn": e}


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
    cur = ecn_mod.current(doc)
    if rels and cur is None:
        blocking.append(f"Rev {rels[-1]['rev']} is released: raise a change notice (ECN) to change the program.")
    from aicad import handoff

    return {"ready": not blocking, "blocking": blocking, "next_rev": handoff.REV_LETTERS[len(rels)]
            if len(rels) < len(handoff.REV_LETTERS) else None, "releases": list(reversed(rels)),
            "released": doc.get("released"), "ecn": cur, "ecns": list(reversed(doc.get("ecns") or []))}


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
async def open_deliverables(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
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
        if o.get("state") == "idle":  # asked for now: Ortho and Smithy start straight away (they cost no tokens)
            try:
                orchestrator.start(root, d, _actor(ctx), user_id=ctx.user.id, god_tokens=ctx.god_on("bypass_tokens"),
                                   god_paywall=ctx.god_on("bypass_paywall"))
            except OfficeInputError:
                pass  # Run stays the engineer's (the budget): the tickets wait on the board
    doc = _mutate(ctx, pid, fn)
    if (doc.get("orchestrator") or {}).get("state") == "running":
        orchestrator.ensure(_root(ctx), pid)
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
    body = body or ReleaseIn()  # a release without a body: no note, the server's date
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
        rel_dir = store.program_dir(root, pid) / "releases" / rev
        if (rel_dir / "pack.zip").exists() or any(r["rev"] == rev for r in doc.get("releases") or []):
            raise HTTPException(409, f"Rev {rev} is already released: a release pack is never overwritten.")
        cur_ecn = ecn_mod.current(doc)
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
                  "icd_version": (doc.get("icd") or {}).get("version"), "bom_lines": len(b["rows"]),
                  "ecn": cur_ecn["id"] if cur_ecn else None}
        if doc.get("releases"):  # the diff summary against the previous release (its pack is the record)
            prev = doc["releases"][-1]
            prev_bom = _pack_text(root, pid, prev["rev"], "bom.csv")
            prev_icd = _pack_text(root, pid, prev["rev"], "icd/icd.json")
            diff = ecn_mod.release_diff(
                prev, released, prev_bom, b, json.loads(prev_icd) if prev_icd else None,
                {"version": doc["icd"]["version"], "skeleton": doc["skeleton"], "interfaces": doc["icd"]["interfaces"]}
                if doc.get("icd") else None, cur_ecn)
            record["diff"] = diff
            files["CHANGES.txt"] = ecn_mod.changes_txt(doc, rev, diff).encode("utf-8")
            files["changes.json"] = json.dumps(diff, indent=1, ensure_ascii=False).encode("utf-8")
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
        try:
            _write_new(rel_dir / "pack.zip", pack)
        except FileExistsError:
            raise HTTPException(409, f"Rev {rev} is already released: a release pack is never overwritten.") from None
        record.update(pack_sha256=hashlib.sha256(pack).hexdigest(), pack_bytes=len(pack), files=sorted(files))

        def fn(r: Path, d: dict[str, Any]) -> None:
            d.setdefault("releases", []).append(record)
            d["released"] = {k: record[k] for k in ("rev", "date", "by", "issued_at")}
            g = service.gate(d, "release")
            g.update(status="approved", by=by, at=store.now(), rev=rev, note=f"Released rev {rev}")
            done = ecn_mod.mark_released(d, rev, by)
            if done:
                service.emit(r, d, "ecn.released", f"{done['id']} released as rev {rev}: "
                             f"{(record.get('diff') or {}).get('summary', '')}", _actor(ctx), ecn=done["id"], rev=rev)
            service.emit(r, d, "program.released", f"{by} released {d['name']} rev {rev}: {len(released)} part"
                         f"{'s' if len(released) != 1 else ''} issued and tagged, drawings, BOM, DFM summary, ICD and "
                         "the program file in one pack.", _actor(ctx), rev=rev)
        doc = _mutate(ctx, pid, fn)
    audit(ctx.db, "office.program_released", ctx.user, org.id, target=pid, rev=rev, parts=len(released),
          files=len(files))
    track(ctx.db, "office_program_released", ctx.user, org.id, parts=len(released))
    ctx.db.commit()
    return {"release": {k: v for k, v in record.items() if k != "by_id"}, "program": _view(doc)}


def _write_new(f: Path, data: bytes) -> None:
    """Exclusive create: a released pack is never rewritten (FileExistsError when it exists)."""
    with open(f, "xb") as fh:
        fh.write(data)


def _pack_text(root: Path, pid: str, rev: str, name: str) -> str | None:
    """One file of a released pack, as text (None when missing)."""
    f = store.program_dir(root, pid) / "releases" / rev / "pack.zip"
    if not f.is_file():
        return None
    with zipfile.ZipFile(f) as z:
        hit = next((n for n in z.namelist() if n.split("/", 1)[-1] == name), None)
        return z.read(hit).decode("utf-8") if hit else None


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


_heartbeat: list[asyncio.Task[None]] = []


async def _supervisor_heartbeat() -> None:
    """Archie's heartbeat for programs that wait without a runner (WORKLIST 49); runners beat on their own."""
    if supervisor.enabled():
        _heartbeat.append(asyncio.create_task(supervisor.heartbeat_loop(get_settings().data_dir)))


async def _stop_heartbeat() -> None:
    while _heartbeat:
        t = _heartbeat.pop()
        t.cancel()


router.on_startup.append(_resume_on_startup)
router.on_startup.append(_supervisor_heartbeat)
router.on_shutdown.append(orchestrator.shutdown)
router.on_shutdown.append(_stop_heartbeat)


# ----------------------------------------------------------------------------- motion range check (ASM-011)
class ProgramMotionIn(BaseModel):
    steps: int = 24
    start: float | None = None
    end: float | None = None


@router.post("/programs/{pid}/assembly/motion")
async def program_motion(pid: str, body: ProgramMotionIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Turn the program's shafts through a range (gear meshes by their ratios, joints from the ICD) and check
    collisions at every step of the final assembly. Nothing is saved to the assembly itself."""
    from aicad.assembly import AssemblyInputError, locks
    from aicad.assembly import service as aservice
    from aicad.assembly import store as astore
    from aicad.office import motion_joints

    doc = _load(ctx, pid)
    state = doc.get("assembly") or {}
    if state.get("status") != "ready" or not state.get("final"):
        raise HTTPException(409, "The program assembly isn't ready yet.")
    aroot = astore.org_root(get_settings().data_dir, ctx.require_org().id)
    steps = max(2, min(int(body.steps or 24), 72))
    async with locks.hold(state["final"], locks.OFFICE):
        adoc = astore.load(aroot, state["final"])
        if adoc is None:
            raise HTTPException(409, "The final assembly is missing. Rebuild the program assembly.")
        pj = motion_joints.program_joints(doc, adoc)
        if not pj["driver"]:
            raise HTTPException(409, "No shaft in this program turns in a bearing or a bore, so there is no motion "
                                     "to check.")
        try:
            res = await aservice.motion_check(aroot, ctx.require_org().id, adoc, pj["joints"], pj["driver"],
                                              body.start, body.end, steps, save=False)
        except (AssemblyInputError, aservice.WorkerError) as e:
            raise HTTPException(400, str(e)) from e
    res["notes"] = pj["notes"]
    astore.write_json(astore.doc_dir(aroot, adoc["id"]) / "motion_program.json", res)
    audit(ctx.db, "office.motion_checked", ctx.user, doc["org_id"], target=pid, steps=len(res["steps"]),
          colliding=len(res["colliding_steps"]))
    ctx.db.commit()
    return {"motion": {**res, "stale": False}}


@router.get("/programs/{pid}/assembly/motion")
def program_motion_last(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    from aicad.assembly import service as aservice
    from aicad.assembly import store as astore

    doc = _load(ctx, pid)
    fid = (doc.get("assembly") or {}).get("final")
    if not fid:
        return {"motion": None}
    aroot = astore.org_root(get_settings().data_dir, ctx.require_org().id)
    adoc = astore.load(aroot, fid)
    res = astore.read_json(astore.doc_dir(aroot, fid) / "motion_program.json") if adoc else None
    if res:
        res["stale"] = res.get("signature") != aservice.geometry_signature(adoc)
    return {"motion": res or None}


# ----------------------------------------------------------------------------- routes: talk to Archie (CD-026)
def _chat_ai(ctx: Ctx, doc: dict[str, Any]) -> tuple[bool, int]:
    """(AI turn available, token cap). Status reports never need it; without it the office reader answers."""
    from aicad.office import fake_agents
    from aicad.platform.routers.projects import can_run_agent

    if fake_agents.enabled() or ctx.role == "viewer":
        return False, 0
    allowed, _, _ = can_run_agent(ctx)
    if not allowed:
        return False, 0
    if ctx.god_on("bypass_tokens"):
        return True, archie_chat.CHAT_MAX_TOKENS
    org = ctx.require_org()
    cap = min(archie_chat.CHAT_MAX_TOKENS, max(0, org.token_balance - metering.reserved(org.id)))
    return cap >= 5, cap


def _chat_view(ctx: Ctx, pid: str, doc: dict[str, Any] | None = None) -> dict[str, Any]:
    doc = doc or _load(ctx, pid)
    ai, _ = _chat_ai(ctx, doc)
    return {"messages": archie_chat.with_labels(doc, archie_chat.history(_root(ctx), pid)), "ai": ai,
            "can_edit": ctx.role != "viewer"}


@router.get("/programs/{pid}/archie")
def archie_history(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    return _chat_view(ctx, pid)


@router.post("/programs/{pid}/archie")
async def archie_say(pid: str, body: ArchieIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """The engineer talks to Archie at any stage. Status questions are answered from the program itself (no AI);
    change requests come back as proposed actions that run only when the engineer applies them."""
    _editor(ctx)
    root = _root(ctx)
    doc = _load(ctx, pid)
    text = body.text.strip()
    if not text:
        raise HTTPException(409, "Write a message first.")
    with archie_chat.chat_lock(pid):
        hist = archie_chat.history(root, pid)
        hist.append(archie_chat.user_message(text, _actor(ctx)))
        archie_chat.save_history(root, pid, hist)
    reply = None
    ai, cap = (False, 0) if archie_chat.is_status(text) else _chat_ai(ctx, doc)
    if ai:
        god = ctx.god_on("bypass_tokens")
        out, usd = "", None
        try:
            out, usd = await archie_chat.run_chat(store.program_dir(root, pid) / "archie",
                                                  archie_chat.chat_prompt(root, doc, hist[:-1], text),
                                                  None if god else cap * metering.USD_PER_TOKEN)
        except Exception:  # any failure: the office reader answers instead
            log.exception("Archie chat turn failed")
        tokens = min(cap, metering.tokens_for_usd(usd)) if usd else 0
        if tokens and not god:
            debit(ctx.db, ctx.require_org(), tokens, "usage", f"Design Office · Archie on {doc['name']}", ctx.user,
                  ref=pid)
        track(ctx.db, "office_archie_chat", ctx.user, doc["org_id"], tokens=tokens, ok=bool(out))
        ctx.db.commit()
        if tokens and not god:
            with store.lock(pid):
                d = _load(ctx, pid)
                d["budget"]["planning_tokens"] = int(d["budget"].get("planning_tokens", 0)) + tokens
                store.save(root, d)
                doc = d
        prose, acts = archie_chat.parse_actions(doc, out)
        if prose or acts:
            reply = archie_chat.archie_message(prose or "Here is what I would do.", acts, kind="ai", tokens=tokens)
    if reply is None:
        t, acts, kind = archie_chat.offline_reply(doc, text, root)
        reply = archie_chat.archie_message(t, acts, kind=kind)
    with archie_chat.chat_lock(pid):
        hist = archie_chat.history(root, pid)
        hist.append(reply)
        archie_chat.save_history(root, pid, hist)
    return _chat_view(ctx, pid, doc)


async def _apply_action(ctx: Ctx, pid: str, doc: dict[str, Any], a: dict[str, Any]) -> None:
    """Run one proposed action through the same route as its button on the board."""
    typ = a["type"]
    t = archie_chat.find_ticket(doc, a.get("ticket", "")) if a.get("ticket") else None
    if a.get("ticket") and t is None:
        raise HTTPException(409, "That ticket is no longer on the program.")
    if typ == "instruct":
        ticket_comment(pid, t["id"], CommentIn(text=a["text"]), ctx)
    elif typ == "reopen":
        await ticket_control(pid, t["id"], ControlIn(action="reopen"), ctx)
        ticket_comment(pid, t["id"], CommentIn(text=a["text"]), ctx)
    elif typ in ("pause_ticket", "resume_ticket"):
        await ticket_control(pid, t["id"], ControlIn(action=typ.split("_")[0]), ctx)
    elif typ == "priority":
        patch_ticket(pid, t["id"], TicketPatch(priority=a["priority"]), ctx)
    elif typ == "pause_program":
        await pause_program(pid, ctx)
    elif typ == "resume_program":
        await run_program(pid, ctx)
    elif typ == "interface_change":
        if (doc.get("icd") or {}).get("status") == "draft":
            edit_interface(pid, a["interface"], IcdEditIn(values=a["values"]), ctx)
        else:
            await change_request(pid, CrIn(interface=a["interface"], values=a["values"], reason=a["reason"]), ctx)
    elif typ == "resize_part":
        _mutate(ctx, pid, lambda root, d: interfaces.resize(root, d, a["item"], a["size"], _actor(ctx)))
    elif typ == "budget":
        patch_program(pid, ProgramPatch(budget_tokens=a.get("tokens"), concurrency=a.get("concurrency"),
                                        threads=a.get("threads")), ctx)
    elif typ == "replan":
        await replan(pid, ReplanIn(planner="archie", notes=a["notes"]), ctx)
    elif typ == "fix_icd":
        await fix_icd(pid, ctx)
    elif typ == "keep_separate":
        await keep_separate(pid, SeparateIn(items=a["items"], keep=True), ctx)
    elif typ == "revise_plan":
        _mutate(ctx, pid, lambda root, d: service.revise_plan(root, d, a, _actor(ctx)))
    elif typ == "revise_program":
        await _revise(ctx, pid, a["changes"], a.get("reason") or "", "chat")
    elif typ == "retry_blocked":
        for t in archie_chat.blocked(_load(ctx, pid)):
            try:
                await ticket_control(pid, t["id"], ControlIn(action="retry"), ctx)
            except HTTPException:
                continue  # an agent picked it up meanwhile
        if (_load(ctx, pid).get("orchestrator") or {}).get("state") != "running":
            await run_program(pid, ctx)
    elif typ == "ecn":
        items = [x["item_id"] for k in a["tickets"] if (x := archie_chat.find_ticket(doc, k)) is not None]
        await raise_ecn(pid, EcnIn(reason=a["reason"], items=items), ctx)
    else:
        raise HTTPException(409, "Unknown action")


# ----------------------------------------------------------------------------- program revisions (PD-100, PD-150..)
async def _revise(ctx: Ctx, pid: str, changes: list[dict[str, Any]], reason: str, source: str) -> dict[str, Any]:
    """The engineer revises the program (their Apply is the approval): applied, logged, audited, the program
    assembly laid out again and the office run on to completion."""
    from aicad.office import revision

    _editor(ctx)
    root = _root(ctx)
    actor = _actor(ctx)
    with store.lock(pid):
        doc = _load(ctx, pid)
        o = doc.setdefault("orchestrator", {"state": "idle"})
        o.setdefault("user_id", ctx.user.id)
        try:
            rev = supervisor.revise_now(root, doc, changes, actor, " ".join(reason.split())[:400] or
                                        "the engineer's revision", source="engineer")
        except OfficeInputError as e:
            raise HTTPException(409, str(e)) from e
        e = supervisor.log_revision(doc, rev, actor, source)
        rev["log"] = e["id"]
        store.save(root, doc)
    audit(ctx.db, "office.revision", ctx.user, doc["org_id"], target=pid, revision=rev["id"],
          icd_from=rev["icd_from"], icd_to=rev["icd_to"], counts=(rev.get("impact") or {}).get("counts"),
          source=source)
    ctx.db.commit()
    revision.spawn_rebuild(root, pid, _sup_env(ctx, doc))
    if (doc.get("orchestrator") or {}).get("state") == "running":
        orchestrator.ensure(root, pid)
    return rev


@router.post("/programs/{pid}/revision/preview")
def revision_preview(pid: str, body: RevisionIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """What a revision would do, per part and per level, with the estimate. Nothing changes."""
    from aicad.office import revision

    doc = _load(ctx, pid)
    try:
        cand = revision.candidate(doc, body.changes)
    except OfficeInputError as e:
        raise HTTPException(409, str(e)) from e
    return {"revision": revision.view(cand), "title": revision.title(cand, doc)}


# ----------------------------------------------------------------------------- the instant 3D preview (WORKLIST 47)
class PreviewIn(BaseModel):
    plan: dict[str, Any] | None = None   # the plan review's unsaved edits (laid out, never saved)


@router.get("/programs/{pid}/preview")
def program_preview(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """The dimensioned 3D preview of the program's layout: its interfaces once they exist, else its plan laid out
    exactly as approval will lay it out (no CAD build). Read-only."""
    from aicad.graph import preview

    try:
        return preview.for_program(_load(ctx, pid))
    except OfficeInputError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/programs/{pid}/preview")
def program_preview_edited(pid: str, body: PreviewIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """The preview of the plan review's unsaved edits (nothing is saved; viewers may look too)."""
    from aicad.graph import preview

    doc = _load(ctx, pid)
    try:
        return preview.for_program(doc, body.plan if doc.get("status") == "plan_review" else None)
    except OfficeInputError as e:
        raise HTTPException(409, str(e)) from e


@router.get("/programs/{pid}/preview/compare/{key}")
def program_preview_compare(pid: str, key: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Before / after previews of a program revision (applied: its snapshots; proposed by Archie: the candidate)."""
    from aicad.graph import preview

    try:
        return preview.compare(_load(ctx, pid), key)
    except OfficeInputError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/programs/{pid}/revision")
async def revise_program(pid: str, body: RevisionIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    rev = await _revise(ctx, pid, body.changes, body.reason, "api")
    return {"revision": {k: v for k, v in rev.items() if k not in ("snapshot", "ops")}, "program": _view(_load(ctx, pid))}


@router.post("/programs/{pid}/revisions/{rid}/undo")
async def undo_revision(pid: str, rid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Undo the latest revision while none of the parts it reopened has been rebuilt (the Archie log entry of the
    revision is marked undone too)."""
    from aicad.office import revision

    _editor(ctx)
    root = _root(ctx)
    with store.lock(pid):
        doc = _load(ctx, pid)
        e = next((x for x in (doc.get("supervisor") or {}).get("log") or []
                  if (x.get("undo") or {}).get("kind") == "revision" and x["undo"].get("id") == rid
                  and x.get("status") == "applied"), None)
    if e is not None:  # one path: the Archie log's undo (it restores the program and marks the entry)
        try:
            supervisor.undo(root, pid, e["id"], _actor(ctx))
        except OfficeInputError as ex:
            raise HTTPException(409, str(ex)) from ex
    else:
        def fn(r: Path, d: dict[str, Any]) -> None:
            revision.undo(r, d, rid, _actor(ctx))
        _mutate(ctx, pid, fn)
        revision.spawn_rebuild(root, pid)
    doc = _load(ctx, pid)
    audit(ctx.db, "office.revision_undo", ctx.user, doc["org_id"], target=pid, revision=rid)
    ctx.db.commit()
    orchestrator.poke(pid)
    return {"program": _view(doc)}


# ----------------------------------------------------------------------------- Archie supervises (WORKLIST 49)
def _sup_env(ctx: Ctx, doc: dict[str, Any]) -> Any:
    return orchestrator.make_env(_root(ctx), {**doc, "orchestrator": {**(doc.get("orchestrator") or {}),
                                                                      "user_id": ctx.user.id,
                                                                      "god_tokens": ctx.god_on("bypass_tokens")}})


def _sup_view(ctx: Ctx, pid: str) -> dict[str, Any]:
    doc = _load(ctx, pid)
    return {"supervisor": supervisor.view(doc), "program": _view(doc), **_chat_view(ctx, pid, doc)}


@router.get("/programs/{pid}/supervisor")
def supervisor_log(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Every action Archie took or proposed while supervising: when, what, why, the evidence and the outcome."""
    return {"supervisor": supervisor.view(_load(ctx, pid))}


@router.post("/programs/{pid}/supervisor/run")
async def supervisor_run(pid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """The engineer asks Archie to look now: one pass over what needs attention (a model call only when something
    does and the hourly cap allows; otherwise the rule-based reading)."""
    _editor(ctx)
    doc = _load(ctx, pid)
    res = await supervisor.run_pass(_root(ctx), pid, _sup_env(ctx, doc), force=True)
    audit(ctx.db, "office.supervisor_run", ctx.user, doc["org_id"], target=pid, ran=bool(res.get("ran")))
    ctx.db.commit()
    return {**_sup_view(ctx, pid), "result": res}


@router.post("/programs/{pid}/supervisor/actions/{aid}/decide")
async def supervisor_decide(pid: str, aid: str, body: SupervisorDecideIn,
                            ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Yes or no to a major change Archie proposed (re-checked against the program as it is now)."""
    _editor(ctx)
    doc = _load(ctx, pid)
    try:
        e = await supervisor.decide(_root(ctx), pid, aid, body.choice, _actor(ctx), _sup_env(ctx, doc))
    except OfficeInputError as ex:
        raise HTTPException(409, str(ex)) from ex
    audit(ctx.db, "office.supervisor_decision", ctx.user, doc["org_id"], target=pid, step=aid,
          choice=body.choice, status=e.get("status"), tool=e.get("tool"))
    if e.get("tool") == "revise_program" and e.get("status") == "applied":
        audit(ctx.db, "office.revision", ctx.user, doc["org_id"], target=pid, revision=(e.get("undo") or {}).get("id"),
              source="archie", counts=((e.get("action") or {}).get("impact") or {}).get("counts"))
    ctx.db.commit()
    doc = _load(ctx, pid)
    if e.get("status") == "applied" and (doc.get("icd") or {}).get("status") == "draft":
        _look_at_layout(ctx, pid, doc)  # the plan changed at the gate: Archie looks at the new layout
    return _sup_view(ctx, pid)


@router.post("/programs/{pid}/supervisor/actions/{aid}/undo")
async def supervisor_undo(pid: str, aid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    _editor(ctx)
    doc = _load(ctx, pid)
    try:
        e = supervisor.undo(_root(ctx), pid, aid, _actor(ctx))
    except OfficeInputError as ex:
        raise HTTPException(409, str(ex)) from ex
    audit(ctx.db, "office.supervisor_undo", ctx.user, doc["org_id"], target=pid, step=aid, tool=e.get("tool"))
    ctx.db.commit()
    orchestrator.poke(pid)
    return _sup_view(ctx, pid)


@router.post("/programs/{pid}/archie/actions")
async def archie_act(pid: str, body: ArchieActIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Apply or dismiss one of Archie's proposed actions. Applying re-checks it against the program as it is now."""
    _editor(ctx)
    root = _root(ctx)
    doc = _load(ctx, pid)
    hist = archie_chat.history(root, pid)
    m = next((x for x in hist if x["id"] == body.message and x["role"] == "archie"), None)
    a = next((x for x in (m or {}).get("actions", []) if x["id"] == body.action), None)
    if a is None:
        raise HTTPException(404, "That proposal is gone.")
    if a["status"] != "proposed":
        raise HTTPException(409, "That proposal was already handled.")
    if body.decision not in ("apply", "dismiss"):
        raise HTTPException(409, "Apply or dismiss.")
    status = "dismissed"
    done: dict[str, Any] = {}
    if body.decision == "apply":
        cur = archie_chat.normalise(doc, {k: v for k, v in a.items() if k not in ("id", "status", "label")})
        if cur is None:
            raise HTTPException(409, "The program has moved on: this proposal no longer applies. Ask Archie again.")
        if cur["type"] == "retry_blocked":  # the label says what was done, not what is blocked afterwards
            done["count"] = len(archie_chat.blocked(doc))
        await _apply_action(ctx, pid, doc, cur)
        status = "applied"
    with archie_chat.chat_lock(pid):
        hist = archie_chat.history(root, pid)
        for x in hist:
            if x["id"] == body.message:
                for y in x.get("actions", []):
                    if y["id"] == body.action:
                        y.update(status=status, by=_actor(ctx), at=store.now(), **done)
        archie_chat.save_history(root, pid, hist)
    return {**_chat_view(ctx, pid), "program": _view(_load(ctx, pid))}


# ----------------------------------------------------------------------------- workspace templates (WORKLIST 48)
@router.get("/templates")
def list_templates(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """The workspace's part templates (kept from AI-designed parts), newest last. Tenant scoped by the org root."""
    from aicad.office import templates

    return {"items": [templates.public(r) for r in templates.load_all(_root(ctx))], "can_edit": ctx.role != "viewer"}


@router.post("/programs/{pid}/tickets/{tid}/template")
def keep_template(pid: str, tid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Keep this ticket's AI-designed, approved, parametric part as a workspace template."""
    from aicad.office import templates
    from aicad.platform.models import Project
    from aicad.platform.routers.projects import workspace_for

    _editor(ctx)
    root = _root(ctx)
    doc = _load(ctx, pid)
    t = next((x for x in doc.get("tickets") or [] if x["id"] == tid), None)
    if t is None:
        raise HTTPException(404, "Ticket not found")
    p = ctx.db.get(Project, t.get("project_id")) if t.get("project_id") else None
    if p is None or p.org_id != ctx.require_org().id:
        raise HTTPException(409, "This part has no design in the Studio yet.")
    ws = workspace_for(p)
    try:
        st = json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    try:
        src = (ws / "model.py").read_text(encoding="utf-8")
    except OSError:
        src = ""
    state = {"ok": bool(st.get("ok")) and not st.get("error"), "source": src}
    try:
        rec = templates.harvest(root, doc, t, state, ctx.user.name or ctx.user.email)
    except templates.TemplateError as e:
        raise HTTPException(422, str(e)) from e

    def fn(r: Path, d: dict[str, Any]) -> None:
        tt = service.ticket(d, tid)
        tt["template_kept"] = {"id": rec["id"], "at": store.now()}
        service.emit(r, d, "ticket.template", f"{service._label(tt)} kept as the workspace template {rec['name']} "
                     f"({rec['family']}, {rec['mapped']} of {rec['params']} parameters mapped to its interfaces).",
                     _actor(ctx), tid)
    _mutate(ctx, pid, fn)
    return rec


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    from aicad.office import templates

    _editor(ctx)
    if not templates.delete(_root(ctx), template_id):
        raise HTTPException(404, "Template not found")
    return {"ok": True}
