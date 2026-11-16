"""Projects (design workspaces) and the per-project AI design agent."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from aicad.agent.session import AgentSession
from aicad.platform.catalog import TOKEN_COSTS
from aicad.platform.config import get_settings
from aicad.platform.db import session_factory, utcnow
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.models import Organization, Project, User
from aicad.platform.routers.billing import tokens_for_cost
from aicad.platform.services import audit, debit, notify, org_modules, track, trial_state

router = APIRouter(prefix="/api", tags=["projects"])

FILES = {"model.glb": "model/gltf-binary", "status.json": "application/json", "part.step": "application/step",
         "part.stl": "model/stl", "views.png": "image/png"}
DOWNLOADS = {"part.step", "part.stl"}

TEMPLATES = [
    {"code": "plate", "name": "Mounting plate", "icon": "square",
     "prompt": "6061 aluminium mounting plate, 120 × 80 × 10 mm. Four M6 clearance holes 10 mm in from each "
               "corner, a centred 40 × 30 × 4 mm deep pocket with 3 mm corner radii, and a 1 mm chamfer on the top "
               "outer edges."},
    {"code": "bracket", "name": "L-bracket", "icon": "corner-down-right",
     "prompt": "Steel L-bracket: horizontal leg 80 mm, vertical leg 60 mm, 40 mm wide, 6 mm thick, 4 mm inside "
               "fillet. Two M8 clearance holes in each leg, centred across the width, 20 mm from each leg end."},
    {"code": "shaft", "name": "Stepped shaft", "icon": "minus",
     "prompt": "Stepped shaft, total length 150 mm: Ø20 × 40 mm, then Ø25 × 70 mm, then Ø20 × 40 mm. 1 mm × 45° "
               "chamfers on both ends, and a 6 × 6 mm keyway 30 mm long centred on the Ø25 section."},
    {"code": "enclosure", "name": "Electronics enclosure", "icon": "package",
     "prompt": "Two-part ABS electronics enclosure, outside 100 × 70 × 40 mm, 2.5 mm walls, split 30 mm / 10 mm "
               "(base / lid), 2 mm outside edge fillets, four M3 screw bosses Ø7 mm in the base corners."},
    {"code": "flange", "name": "Pipe flange", "icon": "circle-dot",
     "prompt": "Slip-on pipe flange: outside Ø150 mm, 16 mm thick, bore Ø60.3 mm, raised face Ø100 × 2 mm, six "
               "Ø14 mm bolt holes equally spaced on a Ø120 mm pitch circle."},
    {"code": "motor_mount", "name": "NEMA 17 motor mount", "icon": "cog",
     "prompt": "Aluminium right-angle mount for a NEMA 17 stepper: 5 mm plate, motor face 42.3 × 42.3 mm with "
               "Ø22.5 mm pilot hole and four M3 clearance holes on a 31 mm square, base flange 60 × 42 mm with two "
               "M5 slots 10 mm long, two triangular gussets."},
]


class ProjectIn(BaseModel):
    name: str
    description: str = ""
    template: str | None = None


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    archived: bool | None = None


class ChatIn(BaseModel):
    prompt: str


# ------------------------------------------------------------------ agent sessions
_sessions: dict[str, AgentSession] = {}
_tasks: set[asyncio.Task[None]] = set()


def workspace_for(p: Project) -> Path:
    root = get_settings().workspaces_dir.resolve()
    ws = (root / p.org_id / p.id).resolve()
    if root not in ws.parents:
        raise HTTPException(400, "bad workspace")
    return ws


def _snapshot(p: Project, ws: Path) -> int | None:
    """Copy model.py + status into revisions/<n> after a build; returns revision number."""
    status_p, model_p = ws / "out" / "status.json", ws / "model.py"
    if not status_p.is_file() or not model_p.is_file():
        return None
    rev_root = ws / "revisions"
    rev_root.mkdir(exist_ok=True)
    nums = sorted(int(d.name) for d in rev_root.iterdir() if d.is_dir() and d.name.isdigit())
    if nums:
        last = rev_root / str(nums[-1]) / "status.json"
        if last.is_file() and json.loads(last.read_text())["build_id"] == json.loads(status_p.read_text())["build_id"]:
            return None
    n = (nums[-1] + 1) if nums else 1
    d = rev_root / str(n)
    d.mkdir()
    shutil.copy2(model_p, d / "model.py")
    shutil.copy2(status_p, d / "status.json")
    if (ws / "out" / "views.png").is_file():
        shutil.copy2(ws / "out" / "views.png", d / "views.png")
    return n


def _on_event(project_id: str, user_id: str, god_tokens: bool) -> Any:
    def handle(ev: dict[str, Any]) -> None:
        if ev.get("type") not in ("result", "tool_result"):
            return
        db = session_factory()()
        try:
            p = db.get(Project, project_id)
            if p is None:
                return
            ws = workspace_for(p)
            if ev["type"] == "tool_result":
                sp = ws / "out" / "status.json"
                if sp.is_file() and ev.get("brief", "").startswith(("Overall", "BUILD")):
                    st = json.loads(sp.read_text(encoding="utf-8"))
                    p.last_status = {k: st.get(k) for k in ("ok", "part", "material", "fingerprint", "error",
                                                            "build_id", "params")}
                    p.builds += 1
                    p.updated_at = utcnow()
                    rev = _snapshot(p, ws)
                    if rev:
                        ev["revision"] = rev
                    if p.builds == 1:
                        user = db.get(User, user_id)
                        track(db, "first_build", user, p.org_id, ok=bool(st.get("ok")))
                db.commit()
                return
            org = db.get(Organization, p.org_id)
            user = db.get(User, user_id)
            cost = ev.get("cost_est_usd")
            tokens = tokens_for_cost(cost)
            ev["tokens_charged"] = 0 if god_tokens else tokens
            if org is not None and not god_tokens:
                debit(db, org, tokens, "usage", f"Design agent · {p.name}", user, ref=project_id)
                ev["token_balance"] = org.token_balance
                if org.token_balance < 50:
                    for uid in {user_id}:
                        notify(db, uid, "Tokens running low",
                               f"{max(org.token_balance, 0)} tokens left. Top up or upgrade to keep designing.",
                               "/app/billing")
            track(db, "agent_run", user, p.org_id, subtype=ev.get("subtype"), tokens=tokens, turns=ev.get("turns"))
            db.commit()
        finally:
            db.close()
    return handle


def get_session(p: Project, ctx: Ctx) -> AgentSession:
    s = _sessions.get(p.id)
    if s is None:
        s = AgentSession(workspace_for(p), on_event=_on_event(p.id, ctx.user.id, ctx.god_on("bypass_tokens")))
        _sessions[p.id] = s
    else:  # refresh who is driving (token attribution, god flags)
        s.on_event = _on_event(p.id, ctx.user.id, ctx.god_on("bypass_tokens"))
    return s


def _project(ctx: Ctx, project_id: str) -> Project:
    p = ctx.db.get(Project, project_id)
    if p is None or p.org_id != ctx.require_org().id:
        raise HTTPException(404, "Project not found")
    return p


def _thumb(p: Project) -> str | None:
    ws = workspace_for(p)
    return f"/api/projects/{p.id}/files/views.png" if (ws / "out" / "views.png").is_file() else None


def project_dict(p: Project, creator: str | None = None) -> dict[str, Any]:
    return {"id": p.id, "name": p.name, "description": p.description, "template": p.template,
            "created_at": p.created_at.isoformat(), "updated_at": p.updated_at.isoformat(), "archived": p.archived,
            "builds": p.builds, "last_status": p.last_status or {}, "thumbnail": _thumb(p), "created_by": creator}


def can_run_agent(ctx: Ctx) -> tuple[bool, str | None, str | None]:
    """(allowed, reason, cta) for starting a design-agent run."""
    org = ctx.require_org()
    if ctx.role == "viewer":
        return False, "Viewers can't run the design agent. Ask an admin for engineer access.", None
    if "design" not in org_modules(ctx.db, org) and not ctx.god_on("bypass_paywall"):
        if org.plan_code == "trial" or org.plan_status == "canceled":
            return False, "Your plan doesn't include Design Studio. Choose a plan to continue.", "/app/billing"
        return False, "Design Studio is not part of your plan.", "/app/billing"
    ts = trial_state(org)
    if ts.get("expired") and not ctx.god_on("bypass_paywall"):
        return False, "Your free trial has ended. Choose a plan to keep designing.", "/app/billing"
    if org.token_balance < TOKEN_COSTS["design_run_preflight"] and not ctx.god_on("bypass_tokens"):
        return False, f"You need at least {TOKEN_COSTS['design_run_preflight']} tokens to run the agent.", \
            "/app/billing#tokens"
    return True, None, None


# ------------------------------------------------------------------ routes
@router.get("/templates")
def templates() -> dict[str, Any]:
    return {"items": TEMPLATES}


@router.get("/projects")
def list_projects(archived: bool = False, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    org = ctx.require_org()
    rows = ctx.db.scalars(select(Project).where(Project.org_id == org.id, Project.archived.is_(archived))
                          .order_by(Project.updated_at.desc())).all()
    names = {u.id: u.name for u in ctx.db.scalars(select(User).where(User.id.in_({r.created_by for r in rows})))}
    return {"items": [project_dict(p, names.get(p.created_by or "")) for p in rows]}


@router.post("/projects")
def create_project(body: ProjectIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    org = ctx.require_org()
    if ctx.role == "viewer":
        raise HTTPException(403, "Viewers can't create projects")
    name = body.name.strip()
    if not name or len(name) > 120:
        raise HTTPException(422, "Project name is required")
    tpl = next((t for t in TEMPLATES if t["code"] == body.template), None)
    p = Project(org_id=org.id, name=name, description=body.description[:2000], template=tpl["code"] if tpl else None,
                created_by=ctx.user.id)
    ctx.db.add(p)
    ctx.db.flush()
    workspace_for(p).mkdir(parents=True, exist_ok=True)
    audit(ctx.db, "project.created", ctx.user, org.id, target=p.id, name=name)
    track(ctx.db, "project_created", ctx.user, org.id, template=p.template or "")
    ctx.db.commit()
    return {**project_dict(p, ctx.user.name), "starter_prompt": tpl["prompt"] if tpl else None}


@router.get("/projects/{project_id}")
def get_project(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    allowed, reason, cta = can_run_agent(ctx)
    s = _sessions.get(p.id)
    return {**project_dict(p), "agent": {"busy": bool(s and s.busy), "allowed": allowed, "reason": reason,
                                         "cta": cta, "has_history": bool(s and s.history)}}


@router.patch("/projects/{project_id}")
def patch_project(project_id: str, body: ProjectPatch, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    if ctx.role == "viewer":
        raise HTTPException(403)
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(422, "Name required")
        p.name = body.name.strip()[:120]
    if body.description is not None:
        p.description = body.description[:2000]
    if body.archived is not None:
        p.archived = body.archived
    p.updated_at = utcnow()
    ctx.db.commit()
    return project_dict(p)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    if p.created_by != ctx.user.id:
        ctx.require_role("admin")
    s = _sessions.pop(p.id, None)
    if s and s.busy:
        raise HTTPException(409, "Stop the agent before deleting")
    ws = workspace_for(p)
    ctx.db.delete(p)
    audit(ctx.db, "project.deleted", ctx.user, p.org_id, target=p.id, name=p.name)
    ctx.db.commit()
    if ws.is_dir():
        shutil.rmtree(ws, ignore_errors=True)
    return {"ok": True}


@router.get("/projects/{project_id}/files/{name}")
def project_file(project_id: str, name: str, ctx: Ctx = Depends(verified_ctx)) -> FileResponse:
    p = _project(ctx, project_id)
    if name not in FILES:
        raise HTTPException(404)
    f = workspace_for(p) / "out" / name
    if not f.is_file():
        raise HTTPException(404)
    headers = {"Cache-Control": "no-store"}
    if name in DOWNLOADS:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in p.name)[:60] or "part"
        headers["Content-Disposition"] = f'attachment; filename="{safe}{Path(name).suffix}"'
        track(ctx.db, "download", ctx.user, p.org_id, file=name)
        ctx.db.commit()
    return FileResponse(f, media_type=FILES[name], headers=headers)


@router.get("/projects/{project_id}/source", response_class=PlainTextResponse)
def project_source(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> str:
    f = workspace_for(_project(ctx, project_id)) / "model.py"
    return f.read_text(encoding="utf-8") if f.is_file() else ""


@router.get("/projects/{project_id}/revisions")
def revisions(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    root = workspace_for(_project(ctx, project_id)) / "revisions"
    items = []
    if root.is_dir():
        for d in sorted((d for d in root.iterdir() if d.name.isdigit()), key=lambda d: -int(d.name)):
            st = json.loads((d / "status.json").read_text(encoding="utf-8")) if (d / "status.json").is_file() else {}
            items.append({"n": int(d.name), "ok": st.get("ok"), "error": st.get("error"),
                          "fingerprint": st.get("fingerprint"), "params": st.get("params"),
                          "created_at": datetime.fromtimestamp(d.stat().st_mtime, UTC).replace(tzinfo=None).isoformat()})
    return {"items": items}


@router.post("/projects/{project_id}/revisions/{n}/restore")
async def restore_revision(project_id: str, n: int, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Restore a revision's model.py and rebuild it deterministically (no AI call, no tokens)."""
    p = _project(ctx, project_id)
    if ctx.role == "viewer":
        raise HTTPException(403)
    s = _sessions.get(p.id)
    if s and s.busy:
        raise HTTPException(409, "Agent is busy")
    ws = workspace_for(p)
    src = ws / "revisions" / str(n) / "model.py"
    if not src.is_file():
        raise HTTPException(404)
    shutil.copy2(src, ws / "model.py")
    proc = await asyncio.create_subprocess_exec(sys.executable, "-I", "-m", "aicad.agent.runner",
                                                str(ws / "model.py"), str(ws / "out"), cwd=str(ws))
    try:
        await asyncio.wait_for(proc.wait(), 180)
    except TimeoutError:
        proc.kill()
        raise HTTPException(504, "Rebuild timed out") from None
    stl = ws / "out" / "part.stl"
    if stl.is_file():
        r = await asyncio.create_subprocess_exec(sys.executable, "-m", "aicad.agent.render", str(stl),
                                                 str(ws / "out" / "views.png"), p.name, cwd=str(ws))
        await asyncio.wait_for(r.wait(), 60)
    st = json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
    p.last_status = {k: st.get(k) for k in ("ok", "part", "material", "fingerprint", "error", "build_id", "params")}
    p.updated_at = utcnow()
    audit(ctx.db, "project.revision_restored", ctx.user, p.org_id, target=p.id, revision=n)
    ctx.db.commit()
    if s:
        s.publish({"type": "text", "text": f"Restored revision {n} and rebuilt it (no AI call)."})
    return {"ok": True, "status_ok": st.get("ok")}


class ParamsIn(BaseModel):
    values: dict[str, float]


_ASSIGN = r"^(?P<name>{name})(?P<sp>\s*=\s*)(?P<val>-?\d+(?:\.\d+)?)(?P<rest>\s*(?:#.*)?)$"


def editable_params(source: str) -> dict[str, float]:
    """Top-level `NAME = <number>` assignments that can be edited without the AI."""
    import re

    out: dict[str, float] = {}
    for m in re.finditer(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(-?\d+(?:\.\d+)?)\s*(?:#.*)?$", source, re.MULTILINE):
        out[m.group(1)] = float(m.group(2))
    return out


async def _rebuild(p: Project, ws: Path) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(sys.executable, "-I", "-m", "aicad.agent.runner",
                                                str(ws / "model.py"), str(ws / "out"), cwd=str(ws))
    try:
        await asyncio.wait_for(proc.wait(), 180)
    except TimeoutError:
        proc.kill()
        raise HTTPException(504, "Rebuild timed out") from None
    stl = ws / "out" / "part.stl"
    if stl.is_file():
        r = await asyncio.create_subprocess_exec(sys.executable, "-m", "aicad.agent.render", str(stl),
                                                 str(ws / "out" / "views.png"), p.name, cwd=str(ws))
        await asyncio.wait_for(r.wait(), 60)
    return json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))


@router.get("/projects/{project_id}/params")
def get_params(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    f = workspace_for(_project(ctx, project_id)) / "model.py"
    return {"editable": editable_params(f.read_text(encoding="utf-8")) if f.is_file() else {}}


@router.post("/projects/{project_id}/params")
async def set_params(project_id: str, body: ParamsIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Deterministic parameter edit: rewrite simple numeric assignments in model.py and rebuild (no AI, no tokens).
    The edit is kept only if the rebuilt part passes its checks; otherwise model.py is restored."""
    import math
    import re

    p = _project(ctx, project_id)
    if ctx.role == "viewer":
        raise HTTPException(403)
    s = _sessions.get(p.id)
    if s and s.busy:
        raise HTTPException(409, "Agent is busy")
    ws = workspace_for(p)
    f = ws / "model.py"
    if not f.is_file():
        raise HTTPException(404, "No model yet")
    src = f.read_text(encoding="utf-8")
    editable = editable_params(src)
    new = src
    changes = {}
    for name, val in body.values.items():
        if name not in editable:
            raise HTTPException(422, f"{name} is not a simple editable parameter. Ask the design agent instead.")
        if not math.isfinite(val):
            raise HTTPException(422, f"{name}: invalid number")
        raw = re.search(_ASSIGN.format(name=re.escape(name)), new, re.MULTILINE)
        was_int = raw is not None and "." not in raw["val"]
        if was_int and not float(val).is_integer():
            raise HTTPException(422, f"{name} must be a whole number")
        lit = str(int(val)) if was_int else (repr(float(val)) if not float(val).is_integer() else f"{float(val):.1f}")
        new, n = re.subn(_ASSIGN.format(name=re.escape(name)), lambda m, lit=lit: f"{m['name']}{m['sp']}{lit}{m['rest']}", new,
                         count=1, flags=re.MULTILINE)
        if n:
            changes[name] = {"from": editable[name], "to": val}
    if not changes:
        return {"ok": True, "changed": {}}
    f.write_text(new, encoding="utf-8")
    st = await _rebuild(p, ws)
    if not st.get("ok"):
        f.write_text(src, encoding="utf-8")
        await _rebuild(p, ws)
        reason = st.get("error") or ", ".join(c["id"] for c in st.get("checks", []) if c["gating"] and not c["passed"])
        raise HTTPException(422, f"That change failed the geometry checks ({reason}); the previous model was restored. "
                                 "Ask the design agent if the change needs a design update (e.g. EXPECTED values).")
    p.last_status = {k: st.get(k) for k in ("ok", "part", "material", "fingerprint", "error", "build_id", "params")}
    p.builds += 1
    p.updated_at = utcnow()
    rev = _snapshot(p, ws)
    audit(ctx.db, "project.params_edited", ctx.user, p.org_id, target=p.id, changes=changes)
    ctx.db.commit()
    if s:
        s.publish({"type": "text", "text": "Parameters updated without AI: " + ", ".join(
            f"`{k}` {v['from']:g} → {v['to']:g}" for k, v in changes.items()) + f" (revision {rev})."})
    return {"ok": True, "changed": changes, "revision": rev}


@router.post("/projects/{project_id}/agent/chat")
async def agent_chat(project_id: str, body: ChatIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    text = body.prompt.strip()
    if not text:
        raise HTTPException(400, "Empty prompt")
    if len(text) > 20000:
        raise HTTPException(413, "Prompt too long")
    allowed, reason, cta = can_run_agent(ctx)
    if not allowed:
        track(ctx.db, "paywall_shown", ctx.user, p.org_id, reason=reason or "")
        ctx.db.commit()
        raise HTTPException(402, {"message": reason, "cta": cta})
    s = get_session(p, ctx)
    if s.busy:
        raise HTTPException(409, "The agent is still working on the previous request")
    t = asyncio.create_task(s.send(text))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    track(ctx.db, "prompt_sent", ctx.user, p.org_id, chars=len(text))
    p.updated_at = utcnow()
    ctx.db.commit()
    return {"accepted": True}


@router.post("/projects/{project_id}/agent/interrupt")
async def agent_interrupt(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    s = _sessions.get(p.id)
    if s:
        await s.interrupt()
    return {"ok": True}


@router.post("/projects/{project_id}/agent/reset")
async def agent_reset(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    s = _sessions.get(p.id)
    if s:
        await s.reset()
    return {"ok": True}


@router.get("/projects/{project_id}/agent/events")
async def agent_events(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> StreamingResponse:
    p = _project(ctx, project_id)
    s = get_session(p, ctx)
    ctx.db.close()  # do not hold a DB connection for the life of the stream
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    backlog = list(s.history)
    s.subscribers.add(q)

    async def gen():  # type: ignore[no-untyped-def]
        try:
            yield f"data: {json.dumps({'type': 'hello', 'busy': s.busy})}\n\n"
            for ev in backlog:
                yield f"data: {json.dumps(ev, default=str)}\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), 15)
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            s.subscribers.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})
