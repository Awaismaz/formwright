"""3D Print Prep module API (`/api/m/print`): analyse a project's verified model or an uploaded mesh, rank print
orientations, repair uploaded meshes, export oriented STL / 3MF.

Access needs the `print` module (plan or add-on) or God-mode unlock; otherwise 402. Everything is scoped to the
caller's organisation. Viewers may analyse and download; uploads, repairs and exports need the engineer role.
"""

from __future__ import annotations

import base64
import binascii
import shutil
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from aicad.platform.config import get_settings
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.routers.projects import _project, workspace_for
from aicad.platform.services import audit, org_modules, track
from aicad.printprep import presets, service
from aicad.printprep.mesh import MAX_UPLOAD_BYTES, UNITS_TO_MM, MeshError

router = APIRouter(prefix="/api/m/print", tags=["print"])

Kind = Literal["projects", "uploads"]


def print_ctx(ctx: Ctx = Depends(verified_ctx)) -> Ctx:
    org = ctx.require_org()
    if "print" not in org_modules(ctx.db, org) and not ctx.god_on("bypass_paywall"):
        raise HTTPException(402, {"message": "3D Print Prep isn't included in your plan. Unlock the add-on or "
                                             "upgrade to use it.", "cta": "/app/modules/print"})
    return ctx


class Options(BaseModel):
    process: Literal["fdm", "sla", "sls"] = "fdm"
    material: str | None = Field(default=None, max_length=40)
    tolerance: float = Field(default=0.05, ge=service.TOL_RANGE[0], le=service.TOL_RANGE[1])
    overhang_deg: float | None = Field(default=None, ge=0, le=89)
    printer_mm: list[float] | None = Field(default=None, min_length=3, max_length=3)
    load_dir: Literal["X", "Y", "Z"] | None = None
    overrides: dict[str, float] = Field(default_factory=dict)

    def checked(self) -> dict[str, Any]:
        if self.printer_mm and not all(10 <= x <= 3000 for x in self.printer_mm):
            raise HTTPException(422, "Build volume sides must be between 10 and 3000 mm")
        bounds = {"layer_mm": (0.005, 1.0), "min_wall_mm": (0.05, 20), "warn_wall_mm": (0.05, 20),
                  "min_hole_mm": (0.05, 50), "min_pin_mm": (0.05, 50), "min_gap_mm": (0.02, 10),
                  "overhang_deg": (0, 89), "max_bridge_mm": (0, 200), "infill": (0, 1), "flow_mm3_s": (0.1, 200),
                  "layer_overhead_s": (0, 600), "nozzle_mm": (0.05, 2)}
        for k, v in self.overrides.items():
            if k not in bounds:
                raise HTTPException(422, f"Unknown setting: {k}")
            lo, hi = bounds[k]
            if not lo <= v <= hi:
                raise HTTPException(422, f"{k} must be between {lo:g} and {hi:g}")
        return self.model_dump()


class ExportIn(BaseModel):
    format: Literal["stl", "3mf"] = "3mf"
    rotation: list[list[float]] = Field(default_factory=lambda: [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    tolerance: float = Field(default=0.05, ge=service.TOL_RANGE[0], le=service.TOL_RANGE[1])
    printer_mm: list[float] = Field(default_factory=lambda: [220.0, 220.0, 250.0], min_length=3, max_length=3)
    label: str = Field(default="As modelled", max_length=80)
    tag: str = Field(default="as-modelled", max_length=40)
    process: Literal["fdm", "sla", "sls"] = "fdm"


class UploadIn(BaseModel):
    filename: str = Field(max_length=200)
    data_b64: str
    units: Literal["mm", "cm", "m", "in"] = "mm"


def _source(ctx: Ctx, kind: str, sid: str) -> service.Source:
    if kind == "projects":
        p = _project(ctx, sid)
        return service.Source("project", p.id, p.name, workspace_for(p),
                              (p.last_status or {}).get("material"))
    if kind == "uploads":
        d = service.upload_dir(get_settings().data_dir, ctx.require_org().id, sid)
        if d is None:
            raise HTTPException(404, "Upload not found")
        meta = service.read_meta(d)
        return service.Source("upload", sid, meta["name"], d)
    raise HTTPException(404, "Not found")


def _err(e: Exception) -> HTTPException:
    if isinstance(e, FileNotFoundError):
        return HTTPException(409, str(e))
    if isinstance(e, MeshError):
        return HTTPException(422, str(e))
    if isinstance(e, ValueError):
        return HTTPException(422, str(e))
    return HTTPException(500, "The print analysis failed on this geometry")


@router.get("/presets")
def get_presets(ctx: Ctx = Depends(print_ctx)) -> dict[str, Any]:
    return {**presets.catalog(), "units": list(UNITS_TO_MM), "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
            "tolerance_range": list(service.TOL_RANGE)}


@router.post("/{kind}/{sid}/analyse")
def analyse(kind: Kind, sid: str, body: Options, ctx: Ctx = Depends(print_ctx)) -> dict[str, Any]:
    src = _source(ctx, kind, sid)
    opts = body.checked()
    try:
        rep = service.run_analysis(src, opts)
    except (FileNotFoundError, MeshError, ValueError) as e:
        raise _err(e) from e
    rep["exports"] = service.list_exports(src)
    track(ctx.db, "print_analysed", ctx.user, ctx.require_org().id, kind=kind, process=body.process,
          status=rep["summary"]["status"])
    ctx.db.commit()
    return rep


@router.get("/{kind}/{sid}/mesh")
def mesh(kind: Kind, sid: str, tol: float = 0.05, cap: float = 5.0, rev: int = 0,
         ctx: Ctx = Depends(print_ctx)) -> Response:
    del rev  # cache-buster only
    if not service.TOL_RANGE[0] <= tol <= service.TOL_RANGE[1] or not 0.1 <= cap <= 100:
        raise HTTPException(422, "Out of range")
    src = _source(ctx, kind, sid)
    try:
        data = service.mesh_binary(src, tol, cap)
    except (FileNotFoundError, MeshError, ValueError) as e:
        raise _err(e) from e
    return Response(data, media_type="application/octet-stream", headers={"Cache-Control": "private, max-age=300"})


@router.post("/{kind}/{sid}/export")
def export(kind: Kind, sid: str, body: ExportIn, ctx: Ctx = Depends(print_ctx)) -> dict[str, Any]:
    ctx.require_role("engineer")
    src = _source(ctx, kind, sid)
    if not all(10 <= x <= 3000 for x in body.printer_mm):
        raise HTTPException(422, "Build volume sides must be between 10 and 3000 mm")
    try:
        rot = service.check_rotation(body.rotation)
        res = service.export(src, body.format, rot, body.tolerance, body.printer_mm, body.label,
                             f"{body.process}-{body.tag}")
    except (FileNotFoundError, MeshError, ValueError) as e:
        raise _err(e) from e
    audit(ctx.db, "print.exported", ctx.user, ctx.require_org().id, target=sid, kind=kind, file=res["name"])
    track(ctx.db, "print_exported", ctx.user, ctx.require_org().id, format=body.format)
    ctx.db.commit()
    res["url"] = f"/api/m/print/{kind}/{sid}/files/{res['name']}"
    return res


@router.get("/{kind}/{sid}/files/{name}")
def download(kind: Kind, sid: str, name: str, ctx: Ctx = Depends(print_ctx)) -> FileResponse:
    src = _source(ctx, kind, sid)
    p = service.export_path(src, name)
    if p is None:
        raise HTTPException(404, "File not found")
    media = "model/3mf" if name.endswith(".3mf") else "model/stl"
    return FileResponse(p, media_type=media, filename=name)


# ------------------------------------------------------------------ uploads
@router.get("/uploads")
def uploads(ctx: Ctx = Depends(print_ctx)) -> dict[str, Any]:
    return {"items": service.list_uploads(get_settings().data_dir, ctx.require_org().id)}


@router.post("/uploads")
def upload(body: UploadIn, ctx: Ctx = Depends(print_ctx)) -> dict[str, Any]:
    ctx.require_role("engineer")
    if len(body.data_b64) > MAX_UPLOAD_BYTES * 4 // 3 + 8:
        raise HTTPException(413, f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    try:
        data = base64.b64decode(body.data_b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(400, "The upload is not valid base64") from e
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    try:
        meta = service.create_upload(get_settings().data_dir, ctx.require_org().id, ctx.user.id, body.filename,
                                     data, body.units)
    except MeshError as e:
        raise HTTPException(415 if "Unrecognised" in str(e) else 422, str(e)) from e
    audit(ctx.db, "print.mesh_uploaded", ctx.user, ctx.require_org().id, target=meta["id"], name=meta["name"])
    ctx.db.commit()
    return meta


@router.delete("/uploads/{uid}")
def delete_upload(uid: str, ctx: Ctx = Depends(print_ctx)) -> dict[str, Any]:
    ctx.require_role("engineer")
    src = _source(ctx, "uploads", uid)
    shutil.rmtree(src.root, ignore_errors=True)
    audit(ctx.db, "print.mesh_deleted", ctx.user, ctx.require_org().id, target=uid)
    ctx.db.commit()
    return {"ok": True}


@router.post("/uploads/{uid}/repair")
def repair_upload(uid: str, ctx: Ctx = Depends(print_ctx)) -> dict[str, Any]:
    ctx.require_role("engineer")
    src = _source(ctx, "uploads", uid)
    try:
        report = service.repair_upload(src)
    except (MeshError, ValueError) as e:
        raise _err(e) from e
    audit(ctx.db, "print.mesh_repaired", ctx.user, ctx.require_org().id, target=uid, actions=report["actions"])
    ctx.db.commit()
    return {"repair": report, "upload": service.read_meta(src.root)}


@router.post("/uploads/{uid}/revert")
def revert_upload(uid: str, ctx: Ctx = Depends(print_ctx)) -> dict[str, Any]:
    ctx.require_role("engineer")
    src = _source(ctx, "uploads", uid)
    service.revert_upload(src)
    ctx.db.commit()
    return {"upload": service.read_meta(src.root)}
