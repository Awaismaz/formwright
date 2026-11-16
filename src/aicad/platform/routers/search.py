"""Search across a workspace's parts: similar shapes and parts of a given size (deterministic, no AI)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from aicad import similarity
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.models import Project
from aicad.platform.routers.projects import _project, project_dict, workspace_for

router = APIRouter(prefix="/api/search", tags=["search"])
MIN_SCORE = 35.0


def _candidates(ctx: Ctx, exclude: str | None = None) -> list[tuple[Project, dict[str, Any]]]:
    org = ctx.require_org()
    rows = ctx.db.scalars(select(Project).where(Project.org_id == org.id)).all()
    out = []
    for p in rows:
        if p.id == exclude:
            continue
        sig = similarity.signature(workspace_for(p))
        if sig is not None:
            out.append((p, sig))
    return out


@router.get("/similar/{project_id}")
def similar_parts(project_id: str, limit: int = Query(8, ge=1, le=30), ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Parts in this workspace that look like the project's current part, best first, each with reasons."""
    p = _project(ctx, project_id)
    ref = similarity.signature(workspace_for(p))
    if ref is None:
        raise HTTPException(409, "Build and verify this part first, then search for similar ones")
    hits = []
    for q, sig in _candidates(ctx, exclude=p.id):
        c = similarity.compare(ref, sig)
        if c["score"] >= MIN_SCORE:
            hits.append({"project": project_dict(q), **c})
    hits.sort(key=lambda h: -h["score"])
    return {"reference": {"dims": ref["dims"], "volume": ref["volume"]}, "items": hits[:limit]}


@router.get("/size")
def parts_by_size(q: str = Query(..., min_length=3, max_length=80), ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Parts whose envelope matches a size such as `120x80x10`, `120 x 80` or `Ø50 x 200`."""
    dims = similarity.parse_size_query(q)
    if dims is None:
        return {"dims": None, "items": []}
    hits = []
    for p, sig in _candidates(ctx):
        m = similarity.size_match(dims, sig)
        if m["score"] >= 50:
            hits.append({"project": project_dict(p), **m})
    hits.sort(key=lambda h: -h["score"])
    return {"dims": dims, "items": hits[:12]}
