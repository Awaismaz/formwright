"""Projects (design workspaces) and the per-project AI design agent."""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from aicad.agent import worker
from aicad.agent.runner import editable_params
from aicad.agent.session import AgentSession
from aicad.platform import metering
from aicad.platform.collab import branches, permissions
from aicad.platform.config import get_settings
from aicad.platform.db import session_factory, utcnow
from aicad.platform.deps import Ctx, in_grace, verified_ctx
from aicad.platform.models import AgentRun, Organization, Project, User
from aicad.platform.services import (
    audit,
    debit,
    notify,
    notify_revision,
    org_modules,
    track,
    trial_state,
)

router = APIRouter(prefix="/api", tags=["projects"])

FILES = {"model.glb": "model/gltf-binary", "status.json": "application/json", "part.step": "application/step",
         "part.stl": "model/stl", "views.png": "image/png", "thumb.png": "image/png",
         "topo.json": "application/json",
         "part.3mf": "model/3mf", "recognition.json": "application/json"}
DOWNLOADS = {"part.step", "part.stl", "part.3mf"}

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


class Attachment(BaseModel):
    name: str
    mime: str
    data_b64: str


class ChatIn(BaseModel):
    prompt: str
    attachments: list[Attachment] = []
    budget_tokens: int | None = None  # stop this run at N tokens (default: the workspace's run budget)
    mode: str = "build"  # "build" or "discuss" (talk/plan only: the agent cannot change the model)
    skip_brief: bool = False  # CAD-028: build a new design straight away this once
    brief_approved: bool = False  # this message is the user's confirmed brief: build it


def brief_gate(p: Project, user: User, s: AgentSession, body: ChatIn, mode: str, shown: str | None) -> bool:
    """CAD-028: a new design (no builds yet, Build mode) first returns its interpreted brief for approval, unless the
    user turned the setting off, skipped it for this message, or already approved a brief in this conversation.
    Module hand-offs (``shown``) carry a brief the user already reviewed."""
    if mode != "build" or p.builds or shown or body.skip_brief or body.brief_approved or s.brief_approved:
        return False
    return (user.preferences or {}).get("confirm_brief", True) is not False


ALLOWED_ATTACH = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
MAX_ATTACH_BYTES = 6 * 1024 * 1024


def save_attachments(ws: Path, atts: list[Attachment]) -> list[str]:
    import base64
    import uuid as _uuid

    if len(atts) > 4:
        raise HTTPException(422, "Attach at most 4 images")
    saved = []
    refs = ws / "refs"
    for a in atts:
        ext = ALLOWED_ATTACH.get(a.mime)
        if not ext:
            raise HTTPException(422, f"{a.name}: only PNG, JPEG, WebP or GIF images are supported")
        try:
            raw = base64.b64decode(a.data_b64, validate=True)
        except ValueError:
            raise HTTPException(422, f"{a.name}: invalid image data") from None
        if len(raw) > MAX_ATTACH_BYTES:
            raise HTTPException(413, f"{a.name}: image larger than 6 MB")
        sig = {".png": b"\x89PNG", ".jpg": b"\xff\xd8", ".gif": b"GIF8", ".webp": b"RIFF"}[ext]
        if not raw.startswith(sig):
            raise HTTPException(422, f"{a.name}: file content doesn't match its type")
        refs.mkdir(exist_ok=True)
        fname = f"ref_{_uuid.uuid4().hex[:8]}{ext}"
        (refs / fname).write_bytes(raw)
        saved.append(f"refs/{fname}")
    return saved


def latest_revision(ws: Path) -> int | None:
    root = ws / "revisions"
    nums = [int(d.name) for d in root.iterdir() if d.is_dir() and d.name.isdigit()] if root.is_dir() else []
    return max(nums) if nums else None


def current_revision(ws: Path) -> int | None:
    """The revision the model currently matches (after a restore it is not the latest one); used for undo."""
    try:
        n = int((ws / ".fw" / "current_rev").read_text(encoding="utf-8"))
        return n if (ws / "revisions" / str(n)).is_dir() else latest_revision(ws)
    except (OSError, ValueError):
        return latest_revision(ws)


def set_current_revision(ws: Path, n: int | None) -> None:
    if n is None:
        return
    (ws / ".fw").mkdir(parents=True, exist_ok=True)
    (ws / ".fw" / "current_rev").write_text(str(n), encoding="utf-8")


# ------------------------------------------------------------------ agent sessions
_sessions: dict[str, AgentSession] = branches.BranchKeyed()  # one agent session per project branch
_tasks: set[asyncio.Task[None]] = set()


def main_workspace(p: Project) -> Path:
    root = get_settings().workspaces_dir.resolve()
    ws = (root / p.org_id / p.id).resolve()
    if root not in ws.parents:
        raise HTTPException(400, "bad workspace")
    return ws


def workspace_for(p: Project) -> Path:
    """The workspace of the branch this request works on (main unless the person switched branch)."""
    return branches.resolve_workspace(main_workspace(p), p.id)


def _snapshot(p: Project, ws: Path, cause: str | None = None, kind: str | None = None, by: str | None = None) -> int | None:
    """Copy model.py + status into revisions/<n> after a build; returns revision number. `cause` records why the
    revision exists (the request or action), for change notices."""
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
    parent = current_revision(ws)  # the state this revision was made from (undo goes back to it)
    d = rev_root / str(n)
    d.mkdir()
    shutil.copy2(model_p, d / "model.py")
    shutil.copy2(status_p, d / "status.json")
    for extra in ("topo.json", "part.step"):  # needed for revision overlay and compare
        if (ws / "out" / extra).is_file():
            shutil.copy2(ws / "out" / extra, d / extra)
    if (ws / "out" / "views.png").is_file():
        shutil.copy2(ws / "out" / "views.png", d / "views.png")
    (d / "cause.json").write_text(json.dumps({"cause": (cause or "")[:600] or None, "kind": kind or "edit", "by": by,
                                              "parent": parent}), encoding="utf-8")
    set_current_revision(ws, n)
    return n


def _on_event(project_id: str, user_id: str, god_tokens: bool) -> Any:
    branch = branches.active_branch(project_id)  # a run's events always belong to the branch it started on

    def handle(ev: dict[str, Any]) -> None:
        with branches.use_branch(project_id, branch):
            _handle(ev)

    def _handle(ev: dict[str, Any]) -> None:
        if ev.get("type") == "meter":
            spent = ev.get("spent_usd") or 0.0
            ev["tokens"] = metering.tokens_for_usd(spent) if spent else 0
            b = ev.get("budget_usd")
            ev["budget_tokens"] = round(b / metering.USD_PER_TOKEN) if b else None
            return
        if ev.get("type") == "busy" and ev.get("value") is False:
            _finish_run(project_id)  # no-op when the result already closed the run
            return
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
                if sp.is_file() and ev.get("build"):
                    st = json.loads(sp.read_text(encoding="utf-8"))
                    p.last_status = {k: st.get(k) for k in ("ok", "part", "material", "fingerprint", "error",
                                                            "build_id", "params")}
                    p.builds += 1
                    p.updated_at = utcnow()
                    s = _sessions.get(project_id)
                    who = db.get(User, user_id)
                    why = getattr(s, "last_prompt", None) or "Design agent build"
                    rev = _snapshot(p, ws, cause=why, kind="agent", by=who.name if who else None)
                    if rev:
                        ev["revision"] = rev
                        notify_revision(db, p, rev, who, why)
                    if p.builds == 1:
                        track(db, "first_build", who, p.org_id, ok=bool(st.get("ok")))
                db.commit()
                return
            org = db.get(Organization, p.org_id)
            user = db.get(User, user_id)
            tokens = metering.tokens_for_usd(ev.get("cost_est_usd"))
            budget = ev.get("budget_tokens")
            if isinstance(budget, int):
                tokens = min(tokens, budget)  # a run is never charged more than its budget
            ev["tokens_charged"] = 0 if god_tokens else tokens
            if org is not None and not god_tokens:
                before = org.token_balance
                debit(db, org, tokens, "usage", f"Design agent · {p.name}", user, ref=project_id)
                ev["token_balance"] = org.token_balance
                if org.token_balance < metering.LOW_TOKENS <= before:
                    notify(db, user_id, "Tokens running low",
                           f"{max(org.token_balance, 0)} tokens left, less than a typical new part. Top up or "
                           "upgrade to keep designing.", "/app/billing#tokens")
            track(db, "agent_run", user, p.org_id, subtype=ev.get("subtype"), tokens=tokens, turns=ev.get("turns"))
            built = (latest_revision(ws) or 0) > (ev.get("rev_before") or 0)
            verified = bool((p.last_status or {}).get("ok")) if built else None
            status = ("stopped_budget" if ev.get("budget_stopped") else "ok" if ev.get("subtype") == "success"
                      else "stopped" if ev.get("subtype") == "stopped" else "failed")
            run = db.get(AgentRun, ev.get("run_id") or "")
            if run is not None:
                run.tokens, run.cost_usd, run.status = ev["tokens_charged"], ev.get("cost_est_usd"), status
                run.verified, run.turns, run.duration_s = verified, ev.get("turns"), ev.get("duration_s")
                run.finished_at = utcnow()
                metering.release(run.org_id, run.id)
            if (ev.get("duration_s") or 0) >= 20 or status == "stopped_budget":
                _notify_run(db, p, user_id, status, verified, ev["tokens_charged"], budget)
            db.commit()
        finally:
            db.close()
    return handle


def _notify_run(db: Any, p: Project, user_id: str, status: str, verified: bool | None, tokens: int,
                budget: int | None) -> None:
    """Agent runs take minutes and people tab away: say how the run ended, linked to the part."""
    link = f"/app/projects/{p.id}"
    if status == "stopped_budget":
        notify(db, user_id, f"{p.name}: stopped at the run budget",
               f"The run used its {budget}-token budget and stopped. The last verified build is kept.", link)
    elif verified:
        notify(db, user_id, f"{p.name} is ready", f"Built and verified: all geometry checks passed · {tokens} tokens.",
               link)
    elif verified is False:
        notify(db, user_id, f"{p.name}: checks failing", "The agent finished, but the latest build does not pass "
               "its checks. Open the project to review.", link)
    elif status in ("stopped", "failed"):
        notify(db, user_id, f"{p.name}: the design agent stopped", "No new build was made. Open the project to "
               "continue.", link)
    else:
        notify(db, user_id, f"{p.name}: the design agent replied", "No geometry changed. Open the project to read "
               "the answer.", link)


def _finish_run(project_id: str) -> None:
    """Close a run that ended without a result (a crash or lost connection): release its reserved budget."""
    s = _sessions.get(project_id)
    run_id = getattr(s, "run_id", None)
    if s is None or not run_id:
        return
    s.run_id = None  # type: ignore[attr-defined]
    db = session_factory()()
    try:
        run = db.get(AgentRun, run_id)
        if run is not None:
            metering.release(run.org_id, run.id)
            if run.status == "running":
                run.status, run.finished_at = "failed", utcnow()
                db.commit()
    finally:
        db.close()


def get_session(p: Project, ctx: Ctx, drive: bool = True) -> AgentSession:
    s = _sessions.get(p.id)
    if s is None:
        s = AgentSession(workspace_for(p), on_event=_on_event(p.id, ctx.user.id, ctx.god_on("bypass_tokens")),
                         worker_key=p.org_id)
        s.run_id = None  # type: ignore[attr-defined]
        _sessions[p.id] = s
    elif drive:  # refresh who is driving (token attribution, god flags); watching the stream doesn't drive
        s.on_event = _on_event(p.id, ctx.user.id, ctx.god_on("bypass_tokens"))
    return s


def _project(ctx: Ctx, project_id: str, need: str | None = None) -> Project:
    """Every project endpoint goes through here: `permissions.require_project` (level by HTTP method unless given)."""
    return permissions.require_project(ctx, project_id, need)


def _thumb(p: Project) -> str | None:
    out = workspace_for(p) / "out"
    for name in ("thumb.png", "views.png"):  # thumb.png: one clean view; older builds only have the 2x2 sheet
        if (out / name).is_file():
            return f"/api/projects/{p.id}/files/{name}"
    return None


def project_dict(p: Project, creator: str | None = None) -> dict[str, Any]:
    return {"id": p.id, "name": p.name, "description": p.description, "template": p.template,
            "created_at": p.created_at.isoformat(), "updated_at": p.updated_at.isoformat(), "archived": p.archived,
            "builds": p.builds, "last_status": p.last_status or {}, "thumbnail": _thumb(p), "created_by": creator}


def can_run_agent(ctx: Ctx) -> tuple[bool, str | None, str | None]:
    """(allowed, reason, cta) for starting a design-agent run."""
    org = ctx.require_org()
    if ctx.role == "viewer":
        return False, "Viewers can't run the design agent. Ask an admin for engineer access.", None
    if ctx.user.email_verified_at is None and not ctx.god_on("skip_verification") and not in_grace(ctx.user):
        return False, "Verify your email to keep designing.", "/verify-email"
    if "design" not in org_modules(ctx.db, org) and not ctx.god_on("bypass_paywall"):
        if org.plan_code == "trial" or org.plan_status == "canceled":
            return False, "Your plan doesn't include Design Studio. Choose a plan to continue.", "/app/billing"
        return False, "Design Studio is not part of your plan.", "/app/billing"
    ts = trial_state(org)
    if ts.get("expired") and not ctx.god_on("bypass_paywall"):
        return False, "Your free trial has ended. Choose a plan to keep designing.", "/app/billing"
    if not ctx.god_on("bypass_tokens"):
        budget, why = metering.run_budget(ctx.db, org, ctx.user, None)
        if budget is None:
            if why == "verify":
                return False, (f"Verify your email to keep designing. Until then an account can use "
                               f"{metering.UNVERIFIED_TOKEN_CAP} tokens."), "/verify-email"
            return False, why, "/app/billing#tokens"
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
    acc = permissions.access_map(ctx.db, ctx.user, rows)  # only what you can read
    rows = [p for p in rows if acc[p.id].at_least("read")]
    names = {u.id: u.name for u in ctx.db.scalars(select(User).where(User.id.in_({r.created_by for r in rows})))}
    return {"items": [{**project_dict(p, names.get(p.created_by or "")), "access": acc[p.id].as_dict()} for p in rows]}


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
    allowed, reason, cta = permissions.agent_gate(ctx, p) or can_run_agent(ctx)
    s = _sessions.get(p.id)
    return {**project_dict(p), "access": ctx.project_access.as_dict(), "branch": branches.active_branch(p.id),
            "agent": {"busy": bool(s and s.busy), "allowed": allowed, "reason": reason,
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


class DuplicateIn(BaseModel):
    name: str | None = None


def _copy_name(ctx: Ctx, base: str) -> str:
    """"Bracket (copy)", then "Bracket (copy 2)"... unique among the workspace's projects."""
    names = set(ctx.db.scalars(select(Project.name).where(Project.org_id == ctx.require_org().id)))
    stem = f"{base} (copy)"[:120]
    n, name = 2, stem
    while name in names:
        name, n = f"{base} (copy {n})"[:120], n + 1
    return name


@router.post("/projects/{project_id}/duplicate")
def duplicate_project(project_id: str, body: DuplicateIn | None = None,
                      ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Save as: a new project with the same model, verified outputs, settings and revision history (no AI, no
    tokens). The design conversation is not copied; the copy starts a fresh one."""
    src = _project(ctx, project_id, "read")
    if ctx.role == "viewer" or ctx.project_access.guest:
        raise HTTPException(403, "Viewers can't create projects")
    s = _sessions.get(src.id)
    if s and s.busy:
        raise HTTPException(409, "The design agent is working on this part. Duplicate it when the run has finished.")
    name = ((body.name if body else None) or "").strip()[:120] or _copy_name(ctx, src.name)
    p = Project(org_id=src.org_id, name=name, description=src.description, template=src.template,
                created_by=ctx.user.id, last_status=dict(src.last_status or {}), builds=src.builds)
    ctx.db.add(p)
    ctx.db.flush()
    a, b = workspace_for(src), workspace_for(p)
    if a.is_dir():
        shutil.copytree(a, b, ignore=shutil.ignore_patterns(".fw", ".out_backup"))
    else:
        b.mkdir(parents=True, exist_ok=True)
    audit(ctx.db, "project.duplicated", ctx.user, p.org_id, target=p.id, source=src.id)
    track(ctx.db, "project_duplicated", ctx.user, p.org_id)
    ctx.db.commit()
    return project_dict(p, ctx.user.name)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id, "admin")
    s = _sessions.pop(p.id, None)
    if s and s.busy:
        raise HTTPException(409, "Stop the agent before deleting")
    ws = main_workspace(p)
    branches.remove_all(ws)
    ctx.db.delete(p)
    audit(ctx.db, "project.deleted", ctx.user, p.org_id, target=p.id, name=p.name)
    ctx.db.commit()
    if ws.is_dir():
        shutil.rmtree(ws, ignore_errors=True)
    return {"ok": True}


@router.get("/projects/{project_id}/files/{name}")
async def project_file(project_id: str, name: str, ctx: Ctx = Depends(verified_ctx)) -> FileResponse:
    p = _project(ctx, project_id)
    if name not in FILES:
        raise HTTPException(404)
    ws = workspace_for(p)
    if name in DOWNLOADS or name in ("model.glb", "views.png"):
        await wait_finalized(p.id)
    f = ws / "out" / name
    if not f.is_file() and name in ("topo.json", "part.3mf") and (ws / "model.py").is_file()             and (ws / "out" / "status.json").is_file() and not (_sessions.get(p.id) and _sessions[p.id].busy):
        await _rebuild(p, ws, determinism=False)  # one-time upgrade of projects built before these outputs existed
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
    """The model script, for superadmin support/debugging only (users never see internals; PD parked)."""
    if not ctx.actor.is_superadmin:
        raise HTTPException(404)
    f = workspace_for(_project(ctx, project_id)) / "model.py"
    return f.read_text(encoding="utf-8") if f.is_file() else ""


@router.get("/projects/{project_id}/revisions")
def revisions(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    root = workspace_for(_project(ctx, project_id)) / "revisions"
    items = []
    if root.is_dir():
        for d in sorted((d for d in root.iterdir() if d.name.isdigit()), key=lambda d: -int(d.name)):
            st = json.loads((d / "status.json").read_text(encoding="utf-8")) if (d / "status.json").is_file() else {}
            cause = json.loads((d / "cause.json").read_text(encoding="utf-8")) if (d / "cause.json").is_file() else {}
            items.append({"n": int(d.name), "ok": st.get("ok"), "error": st.get("error"), "why": cause.get("cause"),
                          "kind": cause.get("kind"), "by": cause.get("by"),
                          "fingerprint": st.get("fingerprint"), "params": st.get("params"),
                          "created_at": datetime.fromtimestamp(d.stat().st_mtime, UTC).replace(tzinfo=None).isoformat()})
    return {"items": items}


@router.get("/revisions/recent")
def recent_revisions(limit: int = 6, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Latest revisions across the workspace with why/who: the team's change feed."""
    org = ctx.require_org()
    rows = permissions.visible(ctx.db, ctx.user, ctx.db.scalars(
        select(Project).where(Project.org_id == org.id, Project.archived.is_(False))
        .order_by(Project.updated_at.desc()).limit(40)).all())
    out = []
    for p in rows:
        root = workspace_for(p) / "revisions"
        if not root.is_dir():
            continue
        for d in sorted((d for d in root.iterdir() if d.name.isdigit()), key=lambda d: -int(d.name))[:3]:
            cause = json.loads((d / "cause.json").read_text(encoding="utf-8")) if (d / "cause.json").is_file() else {}
            out.append({"project": {"id": p.id, "name": p.name}, "n": int(d.name), "why": cause.get("cause"),
                        "kind": cause.get("kind"), "by": cause.get("by"), "mtime": d.stat().st_mtime})
    out.sort(key=lambda r: -r["mtime"])
    items = out[:max(1, min(limit, 20))]
    for r in items:
        r["created_at"] = datetime.fromtimestamp(r.pop("mtime"), UTC).replace(tzinfo=None).isoformat()
    return {"items": items}


@router.get("/projects/{project_id}/revisions/{n}/notice")
def change_notice(project_id: str, n: int, base: int | None = None, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """What changed in revision n (vs. the previous one, or `base`) and why: deterministic, for the shop floor."""
    from aicad import change_notice as cn

    p = _project(ctx, project_id)
    root = workspace_for(p) / "revisions"
    try:
        out = cn.notice(root, n, base)
    except FileNotFoundError:
        raise HTTPException(404, "Revision not found") from None
    newer = sorted(int(d.name) for d in root.iterdir() if d.name.isdigit() and int(d.name) > n) if root.is_dir() else []
    return {**out, "project": {"id": p.id, "name": p.name}, "superseded_by": newer[0] if newer else None,
            "latest": not newer}


def _read_status(ws: Path) -> dict[str, Any]:
    f = ws / "out" / "status.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}


def _status_summary(st: dict[str, Any]) -> dict[str, Any]:
    return {k: st.get(k) for k in ("ok", "part", "material", "fingerprint", "error", "build_id", "params")}


_finalizing: dict[str, asyncio.Task[None]] = branches.BranchKeyed()


async def _render_later(p: Project, ws: Path) -> None:
    stl = ws / "out" / "part.stl"
    if stl.is_file():
        await worker.render(p.org_id, stl, ws / "out" / "views.png", p.name)
        _attach_view_to_revision(ws)


def _attach_view_to_revision(ws: Path) -> None:
    """The 4-view render finishes after the revision snapshot; give that revision its picture (change notices,
    revision compare). Matches by build id, so a newer build can never lend its image to an older revision."""
    view, status = ws / "out" / "views.png", ws / "out" / "status.json"
    root = ws / "revisions"
    if not view.is_file() or not status.is_file() or not root.is_dir():
        return
    try:
        build = json.loads(status.read_text(encoding="utf-8")).get("build_id")
        for d in sorted((d for d in root.iterdir() if d.name.isdigit()), key=lambda d: -int(d.name))[:3]:
            st = d / "status.json"
            if st.is_file() and json.loads(st.read_text(encoding="utf-8")).get("build_id") == build:
                if not (d / "views.png").is_file():
                    shutil.copy2(view, d / "views.png")
                return
    except (OSError, ValueError):
        return


async def _finalize_later(p: Project, ws: Path, rev: int | None = None) -> None:
    """Exports + STEP round-trip for a fast build, then render; completes the revision snapshot."""
    try:
        await worker.finalize(p.org_id, ws / "out")
        if rev is not None:
            d = ws / "revisions" / str(rev)
            if d.is_dir():
                for f in ("part.step", "status.json"):
                    if (ws / "out" / f).is_file():
                        shutil.copy2(ws / "out" / f, d / f)
        await _render_later(p, ws)
    except Exception:
        import logging

        logging.getLogger("aicad.projects").exception("finalize failed")


def schedule_finalize(p: Project, ws: Path, rev: int | None = None) -> None:
    t = asyncio.create_task(_finalize_later(p, ws, rev))
    _finalizing[p.id] = t
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def wait_finalized(project_id: str) -> None:
    t = _finalizing.get(project_id)
    if t is not None and not t.done():
        await asyncio.shield(t)


async def _rebuild(p: Project, ws: Path, determinism: bool, fast: bool = False) -> dict[str, Any]:
    """Build on the warm worker. fast=True returns as soon as geometry/topology/validity are ready; exports,
    round-trip check and the 4-view render complete in the background (call schedule_finalize after snapshot)."""
    await wait_finalized(p.id)
    res = await worker.build(p.org_id, ws / "model.py", ws / "out", determinism=determinism, fast=fast)
    if res.get("starting"):
        raise HTTPException(503, worker.STARTING)
    if res.get("rc") == -1:
        raise HTTPException(504, "The rebuild took too long and was stopped. Nothing was changed; try again, or "
                                 "simplify the change." if "timed out" in str(res.get("error"))
                            else "The geometry engine stopped unexpectedly. Nothing was changed; try again.")
    if not fast:
        t = asyncio.create_task(_render_later(p, ws))
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)
    return _read_status(ws)


def current_editable(ws: Path) -> dict[str, float | int]:
    """Editable = declared in the script's PARAMS *and* a plain single numeric assignment
    (runner.editable_params). Never internal, derived or loop variables."""
    st = _read_status(ws)
    if "editable_params" in st:
        return dict(st["editable_params"] or {})
    f = ws / "model.py"
    if not f.is_file() or not st.get("params"):
        return {}
    return editable_params(f.read_text(encoding="utf-8"), st["params"])


@router.post("/projects/{project_id}/revisions/{n}/restore")
async def restore_revision(project_id: str, n: int, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Restore a revision's model.py and rebuild it (no AI call, no tokens)."""
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
    before = current_revision(ws)
    shutil.copy2(src, ws / "model.py")
    st = await _rebuild(p, ws, determinism=False, fast=True)  # the revision was verified when first built
    schedule_finalize(p, ws)
    set_current_revision(ws, n)
    p.last_status = _status_summary(st)
    p.updated_at = utcnow()
    audit(ctx.db, "project.revision_restored", ctx.user, p.org_id, target=p.id, revision=n)
    ctx.db.commit()
    if s:
        s.publish({"type": "text", "text": f"Restored revision {n} and rebuilt it (no AI call)."})
    return {"ok": True, "status_ok": st.get("ok"), "revision": n, "rev_before": before}


def _cause(ws: Path, n: int) -> dict[str, Any]:
    try:
        return json.loads((ws / "revisions" / str(n) / "cause.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _parent(ws: Path, n: int) -> int | None:
    par = _cause(ws, n).get("parent", n - 1)
    return par if isinstance(par, int) and par >= 1 and (ws / "revisions" / str(par)).is_dir() else None


async def _go_to(p: Project, ws: Path, ctx: Ctx, n: int, note: str) -> dict[str, Any]:
    s = _sessions.get(p.id)
    if s and s.busy:
        raise HTTPException(409, "The agent is working — try again when it finishes")
    await wait_finalized(p.id)
    shutil.copy2(ws / "revisions" / str(n) / "model.py", ws / "model.py")
    st = await _rebuild(p, ws, determinism=False, fast=True)
    schedule_finalize(p, ws)
    set_current_revision(ws, n)
    p.last_status = _status_summary(st)
    p.updated_at = utcnow()
    audit(ctx.db, "project.undo_redo", ctx.user, p.org_id, target=p.id, revision=n)
    ctx.db.commit()
    if s:
        s.publish({"type": "text", "text": f"{note} (back to revision {n}, no AI call)."})
    return st


@router.post("/projects/{project_id}/undo")
async def undo(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Ctrl+Z: go back to the revision the current one was made from (no AI, no tokens)."""
    p = _project(ctx, project_id)
    if ctx.role == "viewer":
        raise HTTPException(403)
    ws = workspace_for(p)
    cur = current_revision(ws)
    back = _parent(ws, cur) if cur else None
    if back is None:
        raise HTTPException(409, "Nothing to undo")
    why = _cause(ws, cur).get("cause") or f"revision {cur}"
    await _go_to(p, ws, ctx, back, f"Undone: {why}")
    return {"ok": True, "revision": back, "undone": cur, "why": why}


class RedoIn(BaseModel):
    to: int


@router.post("/projects/{project_id}/redo")
async def redo(project_id: str, body: RedoIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Ctrl+Y: re-apply a revision that was undone, if the model is still where the undo left it."""
    p = _project(ctx, project_id)
    if ctx.role == "viewer":
        raise HTTPException(403)
    ws = workspace_for(p)
    if not (ws / "revisions" / str(body.to)).is_dir() or _parent(ws, body.to) != current_revision(ws):
        raise HTTPException(409, "Nothing to redo: the model changed since the undo")
    why = _cause(ws, body.to).get("cause") or f"revision {body.to}"
    await _go_to(p, ws, ctx, body.to, f"Redone: {why}")
    return {"ok": True, "revision": body.to, "why": why}


class ParamsIn(BaseModel):
    values: dict[str, float]


_ASSIGN = r"^(?P<name>{name})(?P<sp>\s*=\s*)(?P<val>-?\d+(?:\.\d+)?)(?P<rest>\s*(?:#.*)?)$"


@router.get("/projects/{project_id}/params")
def get_params(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    return {"editable": current_editable(workspace_for(_project(ctx, project_id)))}


@router.post("/projects/{project_id}/params")
async def set_params(project_id: str, body: ParamsIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Deterministic parameter edit: rewrite declared parameters in model.py and rebuild (no AI, no tokens).
    The edit is kept only if the rebuilt part passes its checks; otherwise the previous model and outputs
    are restored from a snapshot."""
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
    editable = current_editable(ws)
    new = src
    changes = {}
    for name, val in body.values.items():
        if name not in editable:
            raise HTTPException(422, f"{name} is not an editable design parameter. Ask the design agent instead.")
        if not math.isfinite(val):
            raise HTTPException(422, f"{name}: invalid number")
        was_int = isinstance(editable[name], int) and not isinstance(editable[name], bool)
        if was_int and not float(val).is_integer():
            raise HTTPException(422, f"{name} must be a whole number")
        meta = (_read_status(ws).get("param_meta") or {}).get(name) or {}
        if "min" in meta and val < meta["min"] or "max" in meta and val > meta["max"]:
            raise HTTPException(422, f"{meta.get('label') or name} must be between {meta.get('min', '−∞')} and "
                                     f"{meta.get('max', '∞')}{' ' + meta['unit'] if meta.get('unit') else ''} "
                                     "(limit set by the design)")
        if float(val) == float(editable[name]):
            continue
        lit = str(int(val)) if was_int else (repr(float(val)) if not float(val).is_integer() else f"{float(val):.1f}")
        new, n = re.subn(_ASSIGN.format(name=re.escape(name)),
                         lambda m, lit=lit: f"{m['name']}{m['sp']}{lit}{m['rest']}", new, count=1, flags=re.MULTILINE)
        if not n:
            raise HTTPException(422, f"{name} is written in a form that can't be edited here. Ask the design agent.")
        changes[name] = {"from": editable[name], "to": val}
    if not changes:
        return {"ok": True, "changed": {}}
    from aicad.platform.plain import build_error
    from aicad.platform.routers.studio import stamp_manual_refs

    await wait_finalized(p.id)  # never snapshot while background exports are writing
    before = current_revision(ws)
    backup = ws / ".out_backup"
    shutil.rmtree(backup, ignore_errors=True)
    if (ws / "out").is_dir():
        shutil.copytree(ws / "out", backup)
    new = stamp_manual_refs(new, ws)  # hand-picked edges/faces follow the body when it changes size
    f.write_text(new, encoding="utf-8")
    st = await _rebuild(p, ws, determinism=False, fast=True)
    if not st.get("ok"):
        f.write_text(src, encoding="utf-8")
        if backup.is_dir():
            shutil.rmtree(ws / "out", ignore_errors=True)
            backup.rename(ws / "out")
        reason = build_error(st.get("error"), st.get("checks"))
        raise HTTPException(422, f"That change couldn't be built: {reason}. The previous model was restored. "
                                 "Ask the design agent if the change needs a design update.")
    shutil.rmtree(backup, ignore_errors=True)
    p.last_status = _status_summary(st)
    p.builds += 1
    p.updated_at = utcnow()
    rev = _snapshot(p, ws, cause="Parameters changed: " + ", ".join(f"{k} {v['from']:g} → {v['to']:g}" for k, v in changes.items()),
                    kind="params", by=ctx.user.name)
    notify_revision(ctx.db, p, rev, ctx.user, "Parameters changed")
    schedule_finalize(p, ws, rev)
    audit(ctx.db, "project.params_edited", ctx.user, p.org_id, target=p.id, changes=changes)
    ctx.db.commit()
    meta_all = st.get("param_meta") or {}
    repairs = st.get("manual_errors") or []
    if s:
        s.publish({"type": "text", "text": "Parameters updated without AI: " + ", ".join(
            f"{(meta_all.get(k) or {}).get('label') or k} {v['from']:g} → {v['to']:g}" for k, v in changes.items())
            + f" (revision {rev})." + (f" {len(repairs)} feature(s) need repair in the feature tree." if repairs else "")})
    return {"ok": True, "changed": changes, "revision": rev, "rev_before": before, "repairs": repairs,
            "build_s": st.get("timings_s", {}).get("total_s")}


@router.post("/projects/{project_id}/agent/chat")
async def agent_chat(project_id: str, body: ChatIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id, "agent")
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
    s.driver, s.driver_name = ctx.user.id, ctx.user.name  # type: ignore[attr-defined]  (soft edit lock)
    org = ctx.require_org()
    unlimited = ctx.god_on("bypass_tokens")
    budget, why = metering.run_budget(ctx.db, org, ctx.user, body.budget_tokens, unlimited)
    if budget is None and not unlimited:
        raise HTTPException(402, {"message": why if why != "verify" else "Verify your email to keep designing.",
                                  "cta": "/verify-email" if why == "verify" else "/app/billing#tokens"})
    ws = workspace_for(p)
    files = save_attachments(ws, body.attachments)
    if files:
        text += ("\n\n[Reference image(s) attached by the user: " + ", ".join(files) +
                 ". Read them before modelling. Treat them as references: do not assume a scale — ask for at least "
                 "one real dimension if none is given, and state what you inferred versus what you were told.]")
    mode = "discuss" if body.mode == "discuss" else "build"
    shown = getattr(body, "shown", None)  # module hand-offs only (image2cad): the chat shows a summary, not the brief
    gate = brief_gate(p, ctx.user, s, body, mode, shown)
    kind = "change" if p.builds else "new"
    est = metering.estimate(ctx.db, org, kind, len(body.prompt))
    run = AgentRun(org_id=org.id, project_id=p.id, user_id=ctx.user.id, kind="brief" if gate else kind, template=p.template,
                   brief_chars=len(body.prompt), budget_tokens=budget, est_tokens=est["typical"], est_high=est["high"])
    ctx.db.add(run)
    ctx.db.flush()
    if budget is not None:
        metering.reserve(org.id, run.id, budget)
    s.run_id = run.id  # type: ignore[attr-defined]
    s.run_budget_usd = budget * metering.USD_PER_TOKEN if budget is not None else None
    if gate:  # brief runs are their own kind so they don't skew the learned "new part" estimate
        mode = "brief"
    elif mode == "build" and body.brief_approved and not s.brief_approved:
        s.brief_approved = True
        s._persist_session()
    s.turn_meta = {"rev_before": latest_revision(ws), "attachments": files, "run_id": run.id, "budget_tokens": budget,
                   "mode": mode}
    if shown and files:
        shown += "\n\n[Reference image attached]"
    t = asyncio.create_task(s.send(text, shown=shown, mode=mode))
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
    s = get_session(p, ctx, drive=False)
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
