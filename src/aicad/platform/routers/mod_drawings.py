"""Drawing Studio API (module ``drawings``): manufacturing drawing sheets from a project's verified model.

Routes (all org-scoped; the module must be unlocked: plan / add-on ``addon_drawings`` / God-mode bypass, else 402):
  GET  /api/m/drawings/projects                     projects with a verified build, plus their drawing state
  GET  /api/m/drawings/projects/{id}                latest drawing record (or null) and whether it is stale
  POST /api/m/drawings/projects/{id}/generate       generate / regenerate from the latest build (not viewers)
  GET  /api/m/drawings/projects/{id}/files/{name}   sheet.svg | sheet.pdf | sheet.dxf (?download=1 to save)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from aicad.drawing import worker as dworker
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.models import Project
from aicad.platform.routers.projects import _thumb, wait_finalized, workspace_for
from aicad.platform.services import audit, org_modules, track

router = APIRouter(prefix="/api/m/drawings", tags=["drawings"])

CODE = "drawings"
FILES = {"sheet.svg": "image/svg+xml", "sheet.pdf": "application/pdf", "sheet.dxf": "application/dxf"}


class Tolerance(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    mode: str = "none"  # none | iso2768 | custom
    tclass: str | None = Field(None, alias="class")  # ISO 2768-1 class f | m | c | v
    text: str | None = None


class GenerateIn(BaseModel):
    sheet: str = "A3"
    projection: str = "first"
    views: list[str] = ["front", "top", "right", "iso"]
    section: str | None = None
    hidden: bool = True
    tolerance: Tolerance = Tolerance()


def _access(ctx: Ctx) -> None:
    org = ctx.require_org()
    if CODE not in org_modules(ctx.db, org) and not ctx.god_on("bypass_paywall"):
        raise HTTPException(402, {"message": "Drawing Studio isn't included in your plan. Unlock the add-on to "
                                             "generate drawings from your models.", "cta": "/app/modules/drawings"})


def _project(ctx: Ctx, project_id: str) -> Project:
    _access(ctx)
    p = ctx.db.get(Project, project_id)
    if p is None or p.org_id != ctx.require_org().id:
        raise HTTPException(404, "Project not found")
    return p


def _status(ws: Path) -> dict[str, Any]:
    f = ws / "out" / "status.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    except (OSError, ValueError):
        return {}


def _verified(ws: Path, st: dict[str, Any]) -> bool:
    return bool(st.get("ok")) and (ws / "out" / "part.step").is_file()


def _record(ws: Path) -> dict[str, Any] | None:
    f = ws / "drawings" / "drawing.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except (OSError, ValueError):
        return None


def _model_rev(ws: Path, build_id: Any) -> str | None:
    """Revision number of the current build (revisions/<n> holding the same build), else the latest one."""
    root = ws / "revisions"
    if not root.is_dir():
        return None
    nums = sorted((int(d.name) for d in root.iterdir() if d.is_dir() and d.name.isdigit()), reverse=True)
    for n in nums:
        f = root / str(n) / "status.json"
        try:
            st = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        except (OSError, ValueError):
            st = {}
        if build_id is not None and st.get("build_id") == build_id:
            return str(n)
    return str(nums[0]) if nums else None


def _summary(p: Project, ws: Path) -> dict[str, Any]:
    st = _status(ws)
    rec = _record(ws)
    drawing = None
    if rec:
        drawing = {"model_rev": rec.get("model_rev"), "scale": rec["sheet"]["scale"], "sheet": rec["sheet"]["size"],
                   "chk12": rec["check"]["passed"], "stale": rec.get("build_id") != str(st.get("build_id"))}
    return {"id": p.id, "name": p.name, "thumbnail": _thumb(p), "updated_at": p.updated_at.isoformat(),
            "verified": _verified(ws, st), "part": st.get("part"), "material": st.get("material"),
            "drawing": drawing}


@router.get("/projects")
def list_projects(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    _access(ctx)
    org = ctx.require_org()
    rows = ctx.db.scalars(select(Project).where(Project.org_id == org.id, Project.archived.is_(False))
                          .order_by(Project.updated_at.desc())).all()
    return {"items": [_summary(p, workspace_for(p)) for p in rows]}


@router.get("/projects/{project_id}")
def get_drawing(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    ws = workspace_for(p)
    st = _status(ws)
    rec = _record(ws)
    return {"project": _summary(p, ws), "drawing": rec, "can_edit": ctx.role != "viewer",
            "stale": bool(rec) and rec.get("build_id") != str(st.get("build_id")),
            "current_rev": _model_rev(ws, st.get("build_id"))}


@router.post("/projects/{project_id}/generate")
async def generate(project_id: str, body: GenerateIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    if ctx.role == "viewer":
        raise HTTPException(403, "Viewers can open drawings but can't generate them.")
    ws = workspace_for(p)
    await wait_finalized(p.id)  # a fast Studio build exports part.step in the background
    st = _status(ws)
    if not _verified(ws, st):
        raise HTTPException(409, "This project has no verified build yet. Build the model in the Design Studio first.")
    opts = body.model_dump()
    opts["tolerance"] = {"mode": body.tolerance.mode, "class": body.tolerance.tclass, "text": body.tolerance.text}
    meta = {"title": p.name.removeprefix("Demo · "), "drawing_no": f"FW-{p.id[:8].upper()}",
            "drawn_by": ctx.user.name or ctx.user.email, "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "model_rev": _model_rev(ws, st.get("build_id"))}
    res = await dworker.generate(p.org_id, ws / "out", ws / "drawings", opts, meta)
    if not res.get("ok"):
        if res.get("user_error"):
            raise HTTPException(409, res.get("error") or "Drawing failed")
        raise HTTPException(500, "The drawing could not be generated for this model. Check the model in the Design Studio and try again.")
    rec = res["result"]
    audit(ctx.db, "drawing.generated", ctx.user, p.org_id, target=p.id, rev=rec.get("model_rev"),
          chk12=rec["check"]["passed"])
    track(ctx.db, "drawing_generated", ctx.user, p.org_id, chk12=rec["check"]["passed"], sheet=rec["sheet"]["size"])
    ctx.db.commit()
    return {"project": _summary(p, ws), "drawing": rec, "can_edit": True, "stale": False,
            "current_rev": rec.get("model_rev"), "elapsed_s": res.get("elapsed_s")}


@router.get("/projects/{project_id}/files/{name}")
def drawing_file(project_id: str, name: str, download: bool = False, ctx: Ctx = Depends(verified_ctx)) -> FileResponse:
    p = _project(ctx, project_id)
    if name not in FILES:
        raise HTTPException(404)
    f = workspace_for(p) / "drawings" / name
    if not f.is_file():
        raise HTTPException(404, "Generate the drawing first")
    headers = {"Cache-Control": "no-store"}
    if download or name != "sheet.svg":
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in p.name.removeprefix("Demo · "))[:60] or "part"
        headers["Content-Disposition"] = f'attachment; filename="{safe}_drawing{Path(name).suffix}"'
        track(ctx.db, "download", ctx.user, p.org_id, file=f"drawing/{name}")
        ctx.db.commit()
    return FileResponse(f, media_type=FILES[name], headers=headers)
