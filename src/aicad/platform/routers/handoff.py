"""Shop handoff pack: preview what's current, download one verified zip (no AI)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from aicad import handoff
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.routers.projects import _project, workspace_for
from aicad.platform.services import audit

router = APIRouter(prefix="/api", tags=["handoff"])


@router.get("/projects/{project_id}/handoff")
def handoff_plan(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """What the pack would contain now: model files, drawing, DFM report, change notice, with stale/missing flags."""
    return handoff.plan(workspace_for(_project(ctx, project_id)))


@router.get("/projects/{project_id}/handoff.zip")
def handoff_zip(project_id: str, include_stale: bool = False, ctx: Ctx = Depends(verified_ctx)) -> Response:
    p = _project(ctx, project_id)
    try:
        data, manifest = handoff.build_pack(workspace_for(p), p.name, ctx.user.name, include_stale=include_stale)
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    audit(ctx.db, "project.handoff", ctx.user, p.org_id, target=p.id, revision=manifest.get("revision"),
          files=len(manifest["files"]))
    ctx.db.commit()
    fname = f"{handoff._safe(p.name)}_rev{manifest.get('revision') or 0}_handoff.zip"
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{fname}"'})
