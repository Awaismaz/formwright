"""Shop handoff pack, deliverable status and the release gate (no AI).

  GET  /api/projects/{id}/handoff                 what a pack would contain now (stale/missing flags)
  GET  /api/projects/{id}/handoff.zip             the current (draft) pack
  GET  /api/projects/{id}/deliverables            model rev, release state and one status per downstream module
  GET  /api/projects/{id}/release                 the release gate: blocking items, contents, issued revisions
  POST /api/projects/{id}/releases                issue the next revision (editors; frozen pack + issue drawing)
  GET  /api/projects/{id}/releases/{rev}/pack.zip a frozen release pack
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from aicad import deliverables, handoff
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.routers.projects import _project, wait_finalized, workspace_for
from aicad.platform.services import audit, org_modules

router = APIRouter(prefix="/api", tags=["handoff"])
_locks: dict[str, asyncio.Lock] = {}


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


@router.get("/projects/{project_id}/deliverables")
def project_deliverables(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """One staleness rule for every downstream output (``aicad.deliverables``), for the Make tab and module headers."""
    return handoff.deliverables_status(workspace_for(_project(ctx, project_id)))


def _has_drawings(ctx: Ctx) -> bool:
    return "drawings" in org_modules(ctx.db, ctx.require_org()) or ctx.god_on("bypass_paywall")


@router.get("/projects/{project_id}/release")
def release_gate(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    ws = workspace_for(_project(ctx, project_id))
    g = handoff.gate(ws, has_drawings=_has_drawings(ctx))
    g["releases"] = [{k: r.get(k) for k in ("rev", "date", "by", "note", "issued_at", "pack_sha256", "files", "left_out")}
                     | {"model_rev": (r.get("build") or {}).get("model_rev")} for r in reversed(handoff.releases(ws))]
    g["can_issue"] = ctx.role != "viewer"
    return g


class IssueIn(BaseModel):
    note: str = Field("", max_length=300)
    leave_out: list[str] = Field(default_factory=list)
    local_date: str | None = None
    tz: str | None = None


class ReleaseBlocked(ValueError):
    """The release gate has blocking items (``blocking``) or an output could not be frozen (plain message)."""

    def __init__(self, message: str, blocking: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.blocking = blocking or []


async def issue(p: Any, *, by: str, by_id: str | None, note: str = "", leave_out: list[str] | None = None,
                has_drawings: bool = True, day: str | None = None, reuse_current: bool = False) -> dict[str, Any]:
    """Freeze the project's current build as its next revision (the release gate, MAKE-08). Shared by the route
    and the Design Office's program release. ``reuse_current``: when this exact build is already issued, return
    that release instead of refusing. Raises ReleaseBlocked."""
    from aicad.platform.routers import mod_drawings

    leave_out = [x for x in (leave_out or []) if x in handoff.LEAVABLE]
    ws = workspace_for(p)
    lock = _locks.setdefault(p.id, asyncio.Lock())
    async with lock:
        await wait_finalized(p.id)
        g = handoff.gate(ws, has_drawings=has_drawings, leave_out=leave_out)
        if not g["ready"]:
            latest = handoff.latest_release(ws)
            if reuse_current and latest and all(b["kind"] == "release" for b in g["blocking"]):
                return {**latest, "reused": True}
            raise ReleaseBlocked("This revision can't be issued yet: " + " ".join(b["text"] for b in g["blocking"]),
                                 g["blocking"])
        st = deliverables.read_status(ws)
        rev = g["next_rev"]
        note = note.strip() or g["suggested_note"]
        release = {"rev": rev, "build": g["build"], "issued_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                   "date": day or mod_drawings.local_date(None, None), "by": by, "by_id": by_id, "note": note,
                   "params": st.get("params") or {}, "left_out": leave_out}
        rel_dir = ws / "releases" / rev
        shutil.rmtree(rel_dir, ignore_errors=True)  # a half-written earlier attempt of this letter
        drawing_dir = None
        if g["modules"]["drawings"]["state"] == "current":
            drawing_dir = rel_dir / "drawing"
            try:
                await mod_drawings.render_issue(p, ws, drawing_dir, release, release["by"])
            except ValueError as e:
                shutil.rmtree(rel_dir, ignore_errors=True)
                raise ReleaseBlocked(str(e)) from None
        extra: dict[str, bytes] = {}
        name = handoff._safe(p.name)
        eng = g["modules"]["engineering"]
        if eng.get("signed_sets"):
            from aicad.engineering import report as eng_report

            for i, sid in enumerate(eng["signed_sets"], 1):
                extra[f"calculations/{name}_calc_set_{i}.pdf"] = eng_report.build_pdf(ws, sid, p.name)
        for f in g["modules"]["print"].get("current_files") or []:
            fp = ws / "print" / f
            if fp.is_file():
                extra[f"print/{f}"] = fp.read_bytes()
        left = [{"dfm": "manufacturability report (older analysis)",
                 "engineering": "calculation sets signed on an earlier model"}[x] for x in leave_out]
        try:
            pack, manifest = handoff.build_pack(ws, p.name, release["by"], release=release, drawing_dir=drawing_dir,
                                                extra=extra, left_out=left)
        except ValueError as e:
            shutil.rmtree(rel_dir, ignore_errors=True)
            raise ReleaseBlocked(str(e)) from None
        rec = handoff.record_release(ws, release, pack, manifest)
        # the working sheet now carries the letter too (same build, so no new history row)
        drw = handoff._json(ws / "drawings" / "drawing.json")
        if drawing_dir is not None and drw:
            try:
                meta = mod_drawings._meta(p, ws, release["by"], release["date"])
                await mod_drawings._generate(p, ws, drw.get("options") or {}, meta, mod_drawings._edits(ws), ws / "drawings")
            except HTTPException:
                pass  # the frozen issue copy is what counts; the working sheet updates on its next regeneration
    return {**rec, "manifest_files": len(manifest["files"])}


@router.post("/projects/{project_id}/releases")
async def issue_release(project_id: str, body: IssueIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Freeze the current build as the next revision: issue copy of the drawing, DFM report, signed calculation
    packages and print exports, in one hashed pack. Refused (409) while the gate has blocking items."""
    from aicad.platform.routers import mod_drawings

    p = _project(ctx, project_id)
    if ctx.role == "viewer":
        raise HTTPException(403, "Viewers can download releases but can't issue them.")
    leave_out = [x for x in body.leave_out if x in handoff.LEAVABLE]
    try:
        rec = await issue(p, by=ctx.user.name or ctx.user.email, by_id=ctx.user.id, note=body.note,
                          leave_out=leave_out, has_drawings=_has_drawings(ctx),
                          day=mod_drawings.local_date(body.local_date, body.tz))
    except ReleaseBlocked as e:
        raise HTTPException(409, {"message": str(e), "blocking": e.blocking} if e.blocking else str(e)) from None
    audit(ctx.db, "project.release_issued", ctx.user, p.org_id, target=p.id, rev=rec["rev"], files=rec["manifest_files"],
          left_out=leave_out)
    ctx.db.commit()
    return {"release": {k: rec.get(k) for k in ("rev", "date", "by", "note", "issued_at", "pack_sha256", "files", "left_out")},
            "status": handoff.deliverables_status(workspace_for(p))}


@router.get("/projects/{project_id}/releases/{rev}/pack.zip")
def release_pack(project_id: str, rev: str, ctx: Ctx = Depends(verified_ctx)) -> FileResponse:
    p = _project(ctx, project_id)
    f = handoff.release_pack_path(workspace_for(p), rev)
    if f is None:
        raise HTTPException(404, "No such release")
    audit(ctx.db, "project.release_downloaded", ctx.user, p.org_id, target=p.id, rev=rev)
    ctx.db.commit()
    return FileResponse(f, media_type="application/zip",
                        filename=f"{handoff._safe(p.name.removeprefix('Demo · '))}_rev{rev}.zip")
