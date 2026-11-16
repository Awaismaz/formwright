"""Mesh Studio module API (`/api/m/mesh`): product renders and visualisation-mesh exports of a project's verified
part, made by Blender running as a separate headless process.

Access needs the `mesh` module (plan or add-on) or God-mode unlock; otherwise 402. Everything is scoped to the
caller's organisation. Viewers may browse the gallery and download; rendering and exporting need the engineer role.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from aicad.meshstudio import DISCLOSURE, jobs, presets, runner, scene, service
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.routers.projects import _project, workspace_for
from aicad.platform.services import audit, org_modules, track

router = APIRouter(prefix="/api/m/mesh", tags=["mesh"])


def mesh_ctx(ctx: Ctx = Depends(verified_ctx)) -> Ctx:
    org = ctx.require_org()
    if "mesh" not in org_modules(ctx.db, org) and not ctx.god_on("bypass_paywall"):
        raise HTTPException(402, {"message": "Mesh Studio isn't included in your plan. Unlock the add-on to make "
                                             "product renders of your parts.", "cta": "/app/modules/mesh"})
    return ctx


class RenderIn(BaseModel):
    finish: str = Field(max_length=40)
    colour: str | None = Field(default=None, max_length=20)
    lighting: str = Field(default="studio", max_length=20)
    camera: str = Field(default="hero", max_length=20)
    quality: Literal["preview", "final", "turntable"] = "preview"
    aspect: str = Field(default="4:3", max_length=8)
    transparent: bool = False
    pose: str = Field(default="auto", max_length=20)
    soften_edges: bool = True

    def options(self) -> scene.Options:
        try:
            return scene.Options(**self.model_dump()).validate()
        except ValueError as e:
            raise HTTPException(422, str(e)) from e


class ExportIn(BaseModel):
    finish: str = Field(max_length=40)
    colour: str | None = Field(default=None, max_length=20)


def _base(pid: str) -> str:
    return f"/api/m/mesh/projects/{pid}/jobs"


def _err(e: Exception) -> HTTPException:
    if isinstance(e, FileNotFoundError):
        return HTTPException(409, str(e))
    if isinstance(e, jobs.QueueFull):
        return HTTPException(429, str(e))
    if isinstance(e, runner.BlenderError):
        return HTTPException(503, str(e))
    if isinstance(e, ValueError):
        return HTTPException(422, str(e))
    return HTTPException(500, "Mesh Studio couldn't process this model")


@router.get("/presets")
def get_presets(ctx: Ctx = Depends(mesh_ctx)) -> dict[str, Any]:
    dev = runner.detect()
    return {**presets.catalog(), "disclosure": DISCLOSURE,
            "renderer": {"available": bool(dev.get("available")), "engine": "Cycles",
                         "device": dev.get("device"), "gpu": dev.get("gpu"), "reason": dev.get("reason")}}


@router.get("/projects/{pid}")
def project(pid: str, ctx: Ctx = Depends(mesh_ctx)) -> dict[str, Any]:
    p = _project(ctx, pid)
    ws = workspace_for(p)
    info = service.build_info(ws)
    try:
        geom = service.geometry_for(ws)
    except FileNotFoundError as e:
        raise _err(e) from e
    except Exception as e:
        raise HTTPException(422, "This model couldn't be tessellated for rendering") from e
    material = info.get("material")
    return {"project": {"id": p.id, "name": p.name, "material": material, "build_id": info["build_id"]},
            "suggested": presets.map_material(material if isinstance(material, str) else None),
            "mesh": {k: geom[k] for k in ("triangles", "vertices", "tolerance_mm", "bbox_mm", "volume_mm3",
                                          "checks")},
            "disclosure": DISCLOSURE, **service.list_jobs(ws, _base(pid))}


@router.get("/projects/{pid}/jobs")
def list_jobs(pid: str, ctx: Ctx = Depends(mesh_ctx)) -> dict[str, Any]:
    ws = workspace_for(_project(ctx, pid))
    return service.list_jobs(ws, _base(pid))


@router.post("/projects/{pid}/renders")
def render(pid: str, body: RenderIn, ctx: Ctx = Depends(mesh_ctx)) -> dict[str, Any]:
    ctx.require_role("engineer")
    p = _project(ctx, pid)
    opts = body.options()
    org = ctx.require_org()
    try:
        out = service.request_render(workspace_for(p), p.name, opts, org.id, ctx.user.id, _base(pid))
    except (FileNotFoundError, jobs.QueueFull, runner.BlenderError, ValueError) as e:
        raise _err(e) from e
    if opts.quality != "preview":
        audit(ctx.db, "mesh.render_requested", ctx.user, org.id, target=pid, job=out["id"], quality=opts.quality)
    track(ctx.db, "mesh_render", ctx.user, org.id, quality=opts.quality, finish=opts.finish,
          cached=bool(out.get("cached")))
    ctx.db.commit()
    return out


@router.post("/projects/{pid}/exports")
def export(pid: str, body: ExportIn, ctx: Ctx = Depends(mesh_ctx)) -> dict[str, Any]:
    ctx.require_role("engineer")
    p = _project(ctx, pid)
    org = ctx.require_org()
    try:
        out = service.request_export(workspace_for(p), p.name, body.finish, body.colour, org.id, ctx.user.id,
                                     _base(pid))
    except (FileNotFoundError, jobs.QueueFull, runner.BlenderError, ValueError) as e:
        raise _err(e) from e
    audit(ctx.db, "mesh.export_requested", ctx.user, org.id, target=pid, job=out["id"])
    ctx.db.commit()
    return out


@router.get("/projects/{pid}/jobs/{jid}")
def job(pid: str, jid: str, ctx: Ctx = Depends(mesh_ctx)) -> dict[str, Any]:
    v = service.job_view(workspace_for(_project(ctx, pid)), jid, _base(pid))
    if v is None:
        raise HTTPException(404, "Render not found")
    return v


@router.delete("/projects/{pid}/jobs/{jid}")
def delete(pid: str, jid: str, ctx: Ctx = Depends(mesh_ctx)) -> dict[str, Any]:
    ctx.require_role("engineer")
    p = _project(ctx, pid)
    try:
        ok = service.delete_job(workspace_for(p), jid)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    if not ok:
        raise HTTPException(404, "Render not found")
    audit(ctx.db, "mesh.render_deleted", ctx.user, ctx.require_org().id, target=pid, job=jid)
    ctx.db.commit()
    return {"ok": True}


@router.get("/projects/{pid}/jobs/{jid}/files/{name}")
def download(pid: str, jid: str, name: str, dl: int = 0, ctx: Ctx = Depends(mesh_ctx)) -> FileResponse:
    p = _project(ctx, pid)
    path = service.file_path(workspace_for(p), jid, name)
    if path is None:
        raise HTTPException(404, "File not found")
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in p.name)[:60] or "part"
    fname = f"{stem}_{jid[:6]}_{name}"
    headers = {"Cache-Control": "private, max-age=3600"}
    if dl:
        return FileResponse(path, media_type=service.FILES[name], filename=fname, headers=headers)
    return FileResponse(path, media_type=service.FILES[name], headers=headers)
