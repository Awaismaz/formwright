"""Projects that hold related parts (``/api/design-projects``), the agent context indicator, and design memory.

Access:
- a project is a workspace object: every member of its workspace sees it (guests never do; they only hold grants on
  single parts). Viewers can look; engineers and above create and edit projects, notes and decisions; deleting a
  project (never its parts) needs its creator or a workspace admin;
- the parts listed (and described to the agent) are only those the person can read (``permissions.visible``);
- adding a part needs edit access to that part;
- design memory is private: rows are read and written only for (the signed-in person, the selected workspace).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from aicad.memory import context as mctx
from aicad.memory import facts as F
from aicad.memory import learn, service
from aicad.memory.tables import (
    DesignProject,
    DesignProjectPart,
    MemoryEvent,
    MemoryFact,
    ProjectDecision,
)
from aicad.platform.collab import permissions
from aicad.platform.config import get_settings
from aicad.platform.db import utcnow
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.models import Project, User
from aicad.platform.routers.projects import _project, _thumb, project_dict, workspace_for
from aicad.platform.services import audit, track

router = APIRouter(prefix="/api", tags=["design-projects"])

CATEGORIES = ("fastener", "material", "units", "tolerance", "standard", "other")


class DesignProjectIn(BaseModel):
    name: str
    purpose: str = ""


class DesignProjectPatch(BaseModel):
    name: str | None = None
    purpose: str | None = None
    notes: str | None = None
    archived: bool | None = None


class PartIn(BaseModel):
    part_id: str


class DecisionIn(BaseModel):
    text: str
    category: str | None = None


class DecisionPatch(BaseModel):
    text: str | None = None
    status: str | None = None


# ------------------------------------------------------------------ helpers
def _dp(ctx: Ctx, dp_id: str, edit: bool = False) -> DesignProject:
    org = ctx.require_org()
    dp = ctx.db.get(DesignProject, dp_id) if isinstance(dp_id, str) and len(dp_id) <= 64 else None
    if dp is None or dp.org_id != org.id:
        raise HTTPException(404, "Project not found")
    if edit and ctx.role == "viewer":
        raise HTTPException(403, "Viewers can look but not change. Ask an admin for engineer access.")
    return dp


def _parts(ctx: Ctx, dp: DesignProject) -> tuple[list[Project], int]:
    ids = service.part_ids(ctx.db, dp.id)
    rows = list(ctx.db.scalars(select(Project).where(Project.id.in_(ids), Project.org_id == dp.org_id))) if ids else []
    order = {pid: i for i, pid in enumerate(ids)}
    rows.sort(key=lambda p: order[p.id])
    seen = permissions.visible(ctx.db, ctx.user, rows)
    return seen, len(rows) - len(seen)


def _decision(d: ProjectDecision, names: dict[str, str]) -> dict[str, Any]:
    src = {"manual": "Added by hand", "chat": "From a design chat", "memory": "Shared from personal memory",
           "program": "From the Design Office"}.get(d.source, "")
    if d.source_part_id and names.get(d.source_part_id):
        src += f" on “{names[d.source_part_id]}”"
    return {"id": d.id, "text": d.text, "category": d.category, "source": d.source, "source_label": src,
            "status": d.status, "created_by": names.get(d.created_by or ""), "created_at": d.created_at.isoformat()}


def _summary(ctx: Ctx, dp: DesignProject, parts: list[Project], hidden: int) -> dict[str, Any]:
    return {"id": dp.id, "name": dp.name, "purpose": dp.purpose, "archived": dp.archived,
            "program_id": dp.program_id, "parts": len(parts), "hidden_parts": hidden,
            "thumbnails": [t for p in parts if p.builds and (t := _thumb(p))][:4],
            "can_edit": ctx.role != "viewer", "updated_at": dp.updated_at.isoformat(),
            "created_at": dp.created_at.isoformat()}


def _names(ctx: Ctx, ids: set[str | None]) -> dict[str, str]:
    ids = {i for i in ids if i}
    return {u.id: u.name for u in ctx.db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


# ------------------------------------------------------------------ projects
@router.get("/design-projects")
def list_design_projects(archived: bool = False, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    org = ctx.require_org()
    service.sync_programs(ctx.db, org.id, get_settings().data_dir)
    ctx.db.commit()
    rows = ctx.db.scalars(select(DesignProject).where(DesignProject.org_id == org.id,
                                                      DesignProject.archived.is_(archived))
                          .order_by(DesignProject.updated_at.desc())).all()
    out = []
    for dp in rows:
        parts, hidden = _parts(ctx, dp)
        out.append(_summary(ctx, dp, parts, hidden))
    return {"items": out}


@router.post("/design-projects")
def create_design_project(body: DesignProjectIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    org = ctx.require_org()
    if ctx.role == "viewer":
        raise HTTPException(403, "Viewers can't create projects")
    name = body.name.strip()
    if not name or len(name) > 120:
        raise HTTPException(422, "Project name is required")
    dp = DesignProject(org_id=org.id, name=name, purpose=body.purpose.strip()[:2000], created_by=ctx.user.id)
    ctx.db.add(dp)
    ctx.db.flush()
    audit(ctx.db, "design_project.created", ctx.user, org.id, target=dp.id, name=name)
    track(ctx.db, "design_project_created", ctx.user, org.id)
    ctx.db.commit()
    return _summary(ctx, dp, [], 0)


@router.get("/design-projects/{dp_id}")
def get_design_project(dp_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    dp = _dp(ctx, dp_id)
    parts, hidden = _parts(ctx, dp)
    acc = permissions.access_map(ctx.db, ctx.user, parts)
    decisions = list(ctx.db.scalars(select(ProjectDecision).where(ProjectDecision.project_id == dp.id,
                                                                  ProjectDecision.status != "dismissed")
                                    .order_by(ProjectDecision.created_at)))
    names = _names(ctx, {d.created_by for d in decisions} | {p.created_by for p in parts} | {dp.created_by})
    names.update({p.id: p.name for p in parts})
    items = []
    for p in parts:
        f = F.part_facts(workspace_for(p), p.name)
        items.append({**project_dict(p, names.get(p.created_by or "")), "access": acc[p.id].as_dict(),
                      "facts": {"size": f.get("size"), "material": f.get("material"), "revision": f.get("revision"),
                                "interfaces": f.get("interfaces") or [], "built": f.get("built", False)}})
    program = None
    if dp.program_id:
        try:
            from aicad.office import store

            doc = store.load(store.org_root(get_settings().data_dir, dp.org_id), dp.program_id)
            program = {"id": dp.program_id, "name": doc.get("name")} if doc else None
        except Exception:  # noqa: BLE001
            program = None
    return {**_summary(ctx, dp, parts, hidden), "notes": dp.notes, "created_by": names.get(dp.created_by or ""),
            "items": items, "decisions": [_decision(d, names) for d in decisions], "program": program,
            "activity": service.activity(ctx.db, dp, parts, workspace_for),
            "can_delete": ctx.role in ("owner", "admin") or dp.created_by == ctx.user.id}


@router.patch("/design-projects/{dp_id}")
def patch_design_project(dp_id: str, body: DesignProjectPatch, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    dp = _dp(ctx, dp_id, edit=True)
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(422, "Name required")
        dp.name = body.name.strip()[:120]
    if body.purpose is not None:
        dp.purpose = body.purpose.strip()[:2000]
    if body.notes is not None:
        dp.notes = body.notes[:8000]
    if body.archived is not None:
        dp.archived = body.archived
    dp.updated_at = utcnow()
    ctx.db.commit()
    parts, hidden = _parts(ctx, dp)
    return _summary(ctx, dp, parts, hidden)


@router.delete("/design-projects/{dp_id}")
def delete_design_project(dp_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    dp = _dp(ctx, dp_id, edit=True)
    if not (ctx.role in ("owner", "admin") or dp.created_by == ctx.user.id):
        raise HTTPException(403, "Only the project's creator or a workspace admin can delete it")
    ctx.db.execute(delete(DesignProjectPart).where(DesignProjectPart.project_id == dp.id))
    ctx.db.delete(dp)
    audit(ctx.db, "design_project.deleted", ctx.user, dp.org_id, target=dp.id, name=dp.name)
    ctx.db.commit()
    return {"ok": True}


@router.post("/design-projects/{dp_id}/parts")
def add_part(dp_id: str, body: PartIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    dp = _dp(ctx, dp_id, edit=True)
    p = ctx.db.get(Project, body.part_id) if len(body.part_id) <= 64 else None
    if p is None or p.org_id != dp.org_id or not permissions.project_access(ctx.db, ctx.user, p).at_least("read"):
        raise HTTPException(404, "Part not found")
    if not permissions.project_access(ctx.db, ctx.user, p).at_least("edit"):
        raise HTTPException(403, "You need edit access to this part to move it into a project")
    service.link(ctx.db, p, dp, ctx.user.id)
    audit(ctx.db, "design_project.part_added", ctx.user, dp.org_id, target=dp.id, part=p.id)
    ctx.db.commit()
    return {"ok": True, "project": {"id": dp.id, "name": dp.name}}


@router.delete("/design-projects/{dp_id}/parts/{part_id}")
def remove_part(dp_id: str, part_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    dp = _dp(ctx, dp_id, edit=True)
    row = ctx.db.get(DesignProjectPart, part_id)
    p = ctx.db.get(Project, part_id)
    if row is None or row.project_id != dp.id or p is None:
        raise HTTPException(404, "Part not found in this project")
    if not permissions.project_access(ctx.db, ctx.user, p).at_least("edit"):
        raise HTTPException(403, "You need edit access to this part to take it out of the project")
    service.unlink(ctx.db, part_id)
    ctx.db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ decisions
@router.post("/design-projects/{dp_id}/decisions")
def add_decision(dp_id: str, body: DecisionIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    from aicad.memory import extract

    dp = _dp(ctx, dp_id, edit=True)
    text = " ".join(body.text.split())[:240]
    if len(text) < 3:
        raise HTTPException(422, "Write the decision, e.g. “All fasteners M6 ISO 4762”")
    cat = body.category if body.category in CATEGORIES else extract.category(text)
    d = ProjectDecision(project_id=dp.id, text=text, category=cat, source="manual", created_by=ctx.user.id)
    ctx.db.add(d)
    dp.updated_at = utcnow()
    ctx.db.commit()
    return _decision(d, {ctx.user.id: ctx.user.name})


@router.patch("/design-projects/{dp_id}/decisions/{did}")
def patch_decision(dp_id: str, did: str, body: DecisionPatch, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    dp = _dp(ctx, dp_id, edit=True)
    d = ctx.db.get(ProjectDecision, did)
    if d is None or d.project_id != dp.id:
        raise HTTPException(404, "Decision not found")
    if body.text is not None:
        t = " ".join(body.text.split())[:240]
        if len(t) < 3:
            raise HTTPException(422, "Decision text is required")
        d.text = t
    if body.status in ("active", "dismissed"):
        d.status = body.status
    ctx.db.commit()
    return _decision(d, _names(ctx, {d.created_by}))


@router.delete("/design-projects/{dp_id}/decisions/{did}")
def delete_decision(dp_id: str, did: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    dp = _dp(ctx, dp_id, edit=True)
    d = ctx.db.get(ProjectDecision, did)
    if d is None or d.project_id != dp.id:
        raise HTTPException(404, "Decision not found")
    ctx.db.delete(d)
    ctx.db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ what the agent knows (Studio indicator)
async def refresh_recognition(parts: list[Project], timeout: float = 6.0) -> None:
    """Geometric recognition (no AI) for sibling parts whose recognition is older than their build, so the brief
    carries real hole patterns and bores. Waits at most ``timeout``; slower ones finish in the background."""
    from aicad.agent import worker

    async def one(p: Project) -> None:
        ws = workspace_for(p)
        st = F._read(ws / "out" / "status.json") or {}
        if not st.get("ok") or not (ws / "model.py").is_file() or F.recognition_current(ws, st):
            return
        out = ws / "out" / "recognition.json"
        try:
            r = await worker.recognize(p.org_id, ws / "model.py", out, timeout=120)
            if r.get("ok"):
                rec = json.loads(out.read_text(encoding="utf-8"))
                rec["build_id"] = st.get("build_id")
                out.write_text(json.dumps(rec), encoding="utf-8")
        except Exception:  # noqa: BLE001 - the brief falls back to the face census
            return

    jobs = [asyncio.ensure_future(one(p)) for p in parts[:8]]
    if jobs:
        await asyncio.wait(jobs, timeout=timeout)


@router.get("/projects/{project_id}/agent-context")
def agent_context(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id, "read")
    if ctx.project_access.guest:  # guests hold one part, never its project, and never run the agent
        return {"project": None, "parts": [], "decisions": [], "preferences": [], "in_use": False,
                "learning": False, "use": False}
    tc = mctx.turn_context(ctx.db, ctx.user, p)
    dp = mctx.design_project_of(ctx.db, p.id)
    return {**tc.view(), "project": {"id": dp.id, "name": dp.name} if dp else None,
            "learning": learn.learning_on(ctx.user), "use": learn.use_on(ctx.user)}


# ------------------------------------------------------------------ design memory
class MemorySettings(BaseModel):
    learning: bool | None = None
    use: bool | None = None


class FactIn(BaseModel):
    text: str


class FactPatch(BaseModel):
    text: str | None = None
    pinned: bool | None = None


class ShareIn(BaseModel):
    project_id: str


def _fact(f: MemoryFact) -> dict[str, Any]:
    return {"id": f.id, "kind": f.kind, "text": f.text, "source": f.source, "evidence": f.evidence,
            "confidence": f.confidence, "origin": f.origin, "pinned": f.pinned,
            "updated_at": f.updated_at.isoformat()}


def _my_fact(ctx: Ctx, fid: str) -> MemoryFact:
    org = ctx.require_org()
    f = ctx.db.get(MemoryFact, fid) if len(fid) <= 64 else None
    if f is None or f.user_id != ctx.user.id or f.org_id != org.id or f.status != "active":
        raise HTTPException(404, "Not found")
    return f


@router.get("/memory")
def get_memory(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    org = ctx.require_org()
    if learn.may_learn(ctx):
        learn.recompute(ctx.db, ctx.user.id, org.id)
        ctx.db.commit()
    rows = list(ctx.db.scalars(select(MemoryFact).where(MemoryFact.user_id == ctx.user.id,
                                                        MemoryFact.org_id == org.id, MemoryFact.status == "active")
                               .order_by(MemoryFact.pinned.desc(), MemoryFact.updated_at.desc())))
    in_prompt = {f.id for f in mctx.preference_facts(ctx.db, ctx.user, org.id)}
    n_events = len(ctx.db.scalars(select(MemoryEvent.id).where(MemoryEvent.user_id == ctx.user.id,
                                                               MemoryEvent.org_id == org.id)).all())
    return {"learning": learn.learning_on(ctx.user), "use": learn.use_on(ctx.user), "workspace": org.name,
            "facts": [{**_fact(f), "used": f.id in in_prompt} for f in rows], "observations": n_events,
            "limits": {"facts_used": mctx.MAX_PREFS, "observations_kept": learn.MAX_EVENTS}}


@router.patch("/memory/settings")
def memory_settings(body: MemorySettings, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    prefs = dict(ctx.user.preferences or {})
    if body.learning is not None:
        prefs["memory_learning"] = bool(body.learning)
    if body.use is not None:
        prefs["memory_use"] = bool(body.use)
    ctx.user.preferences = prefs
    ctx.db.commit()
    return {"learning": learn.learning_on(ctx.user), "use": learn.use_on(ctx.user)}


@router.post("/memory/facts")
def add_fact(body: FactIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    import uuid

    org = ctx.require_org()
    text = " ".join(body.text.split())[:200]
    if len(text) < 3:
        raise HTTPException(422, "Write the preference, e.g. “Outside edges get 0.5 mm chamfers”")
    f = MemoryFact(user_id=ctx.user.id, org_id=org.id, key=f"user:{uuid.uuid4().hex[:12]}", kind="rule", text=text,
                   origin="user", confidence=1.0, evidence=1, source="Added by you")
    ctx.db.add(f)
    ctx.db.commit()
    return _fact(f)


@router.patch("/memory/facts/{fid}")
def patch_fact(fid: str, body: FactPatch, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    f = _my_fact(ctx, fid)
    if body.text is not None:
        t = " ".join(body.text.split())[:200]
        if len(t) < 3:
            raise HTTPException(422, "Text is required")
        if t != f.text:
            f.text, f.origin = t, "user"  # an edited fact is the person's own: learning never overwrites it
            f.source = (f.source + " · edited by you")[:200] if "edited by you" not in f.source else f.source
    if body.pinned is not None:
        f.pinned = body.pinned
    f.updated_at = utcnow()
    ctx.db.commit()
    return _fact(f)


@router.delete("/memory/facts/{fid}")
def delete_fact(fid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    f = _my_fact(ctx, fid)
    if f.origin == "learned":
        f.status, f.updated_at = "dismissed", utcnow()  # tombstone: not learned again
    else:
        ctx.db.delete(f)
    ctx.db.commit()
    return {"ok": True}


@router.post("/memory/facts/{fid}/share")
def share_fact(fid: str, body: ShareIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Copy a personal preference into a project's decisions (everyone working on the project then follows it)."""
    from aicad.memory import extract

    f = _my_fact(ctx, fid)
    dp = _dp(ctx, body.project_id, edit=True)
    have = {extract.normalise(t) for t in ctx.db.scalars(select(ProjectDecision.text).where(
        ProjectDecision.project_id == dp.id, ProjectDecision.status == "active"))}
    if extract.normalise(f.text) not in have:
        ctx.db.add(ProjectDecision(project_id=dp.id, text=f.text[:240], category=extract.category(f.text),
                                   source="memory", created_by=ctx.user.id))
        dp.updated_at = utcnow()
    ctx.db.commit()
    return {"ok": True, "project": {"id": dp.id, "name": dp.name}}


@router.post("/memory/forget")
def forget(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Delete everything remembered about this person in this workspace (facts, tombstones, observations)."""
    org = ctx.require_org()
    ctx.db.execute(delete(MemoryFact).where(MemoryFact.user_id == ctx.user.id, MemoryFact.org_id == org.id))
    ctx.db.execute(delete(MemoryEvent).where(MemoryEvent.user_id == ctx.user.id, MemoryEvent.org_id == org.id))
    prefs = dict(ctx.user.preferences or {})
    since = prefs.get("memory_since") if isinstance(prefs.get("memory_since"), dict) else {}
    prefs["memory_since"] = {**since, org.id: utcnow().isoformat()}
    ctx.user.preferences = prefs
    ctx.db.commit()
    return {"ok": True}
