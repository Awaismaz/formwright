"""Drawing Studio API (module ``drawings``): manufacturing drawing sheets from a project's verified model.

Routes (all org-scoped; the module must be unlocked: plan / add-on ``addon_drawings`` / God-mode bypass, else 402):
  GET  /api/m/drawings/projects                     projects with a verified build, plus their drawing state
  GET  /api/m/drawings/projects/{id}                latest drawing record (or null) and whether it is stale
  POST /api/m/drawings/projects/{id}/generate       generate / regenerate from the latest build (not viewers)
  GET  /api/m/drawings/projects/{id}/edits          the user's edits (hidden dimensions, tolerances, title, notes)
  PUT  /api/m/drawings/projects/{id}/edits          (or POST) save edits and regenerate the sheet with them (not viewers)
  GET  /api/m/drawings/projects/{id}/files/{name}   sheet.svg | sheet.pdf | sheet.dxf (?download=1 to save,
                                                    ?copy=issue|review; downloads default to the issue copy)

Staleness follows the one rule in ``aicad.deliverables``: a sheet records the build it was drawn from; when the model
changes the API reports ``stale`` and the sheet is *not* replaced until the user updates it.
``render_issue`` writes the frozen issue copy for the release gate (``aicad.handoff``).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from aicad import deliverables
from aicad.drawing import DrawingInputError
from aicad.drawing import worker as dworker
from aicad.drawing.generate import normalize_edits
from aicad.platform.collab import permissions
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.models import Project
from aicad.platform.routers.projects import _thumb, wait_finalized, workspace_for
from aicad.platform.services import audit, org_modules, track

router = APIRouter(prefix="/api/m/drawings", tags=["drawings"])

CODE = "drawings"
FILES = {"sheet.svg": "image/svg+xml", "sheet.pdf": "application/pdf", "sheet.dxf": "application/dxf"}
#: (file, copy) -> stored file. The issue copy (monochrome, no tag legend) is the export default (MAKE-09).
COPIES = {("sheet.svg", "review"): "sheet.svg", ("sheet.svg", "issue"): "sheet_issue.svg",
          ("sheet.pdf", "review"): "sheet_review.pdf", ("sheet.pdf", "issue"): "sheet.pdf",
          ("sheet.dxf", "review"): "sheet.dxf", ("sheet.dxf", "issue"): "sheet.dxf"}


class Tolerance(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    mode: str = "none"  # none | iso2768 | custom
    tclass: str | None = Field(None, alias="class")  # ISO 2768-1 class f | m | c | v
    text: str | None = None


class GenerateIn(BaseModel):
    sheet: str = "A3"
    projection: str = "first"
    views: list[str] | None = None  # None: chosen from the part type
    section: str | None = "auto"  # auto | None (off) | x | y | z | axial | cross
    hidden: bool = True
    tolerance: Tolerance = Tolerance()
    local_date: str | None = None  # the user's calendar date (YYYY-MM-DD), so the sheet carries their day
    tz: str | None = None  # IANA zone name, used when local_date is absent


class EditsIn(BaseModel):
    dims: dict[str, dict[str, Any]] = {}
    title: dict[str, str] = {}
    notes: list[str] = []
    local_date: str | None = None
    tz: str | None = None
    regenerate: bool = True  # False: save only (e.g. a note added from another module while the sheet is out of date)


def _access(ctx: Ctx) -> None:
    org = ctx.require_org()
    if CODE not in org_modules(ctx.db, org) and not ctx.god_on("bypass_paywall"):
        raise HTTPException(402, {"message": "Drawing Studio isn't included in your plan. Unlock the add-on to "
                                             "generate drawings from your models.", "cta": "/app/modules/drawings"})


def _project(ctx: Ctx, project_id: str) -> Project:
    _access(ctx)
    return permissions.require_project(ctx, project_id)  # drawings live in the part's workspace


def _status(ws: Path) -> dict[str, Any]:
    return deliverables.read_status(ws)


def _verified(ws: Path, st: dict[str, Any]) -> bool:
    return bool(st.get("ok")) and (ws / "out" / "part.step").is_file()


def _record(ws: Path) -> dict[str, Any] | None:
    f = ws / "drawings" / "drawing.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except (OSError, ValueError):
        return None


def _edits(ws: Path) -> dict[str, Any]:
    f = ws / "drawings" / "edits.json"
    try:
        return normalize_edits(json.loads(f.read_text(encoding="utf-8"))) if f.is_file() else normalize_edits({})
    except (OSError, ValueError):
        return normalize_edits({})


def releases(ws: Path) -> list[dict[str, Any]]:
    """Issued revisions from the release gate (oldest first)."""
    try:
        from aicad import handoff

        fn = getattr(handoff, "releases", None)
        if fn is not None:
            return list(fn(ws))
    except ImportError:  # pragma: no cover
        pass
    f = ws / "releases" / "releases.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else []
    except (OSError, ValueError):
        data = []
    return data if isinstance(data, list) else []


def _model_rev(ws: Path, build_id: Any) -> str | None:
    return deliverables.model_rev(ws, build_id)


def _stamp(rec: dict[str, Any]) -> dict[str, Any]:
    return rec.get("build") or {"build_id": rec.get("build_id"), "model_rev": rec.get("model_rev")}


def _freshness(ws: Path, rec: dict[str, Any] | None) -> dict[str, Any]:
    return deliverables.freshness(_stamp(rec) if rec else None, ws)


def _summary(p: Project, ws: Path) -> dict[str, Any]:
    st = _status(ws)
    rec = _record(ws)
    drawing = None
    if rec:
        drawing = {"model_rev": rec.get("model_rev"), "sheet_rev": rec.get("sheet_rev"), "scale": rec["sheet"]["scale"],
                   "sheet": rec["sheet"]["size"], "chk12": rec["check"]["passed"],
                   "stale": _freshness(ws, rec)["state"] == "stale"}
    return {"id": p.id, "name": p.name, "thumbnail": _thumb(p), "updated_at": p.updated_at.isoformat(),
            "verified": _verified(ws, st), "part": st.get("part"), "material": st.get("material"),
            "drawing": drawing}


def _state(p: Project, ws: Path, can_edit: bool, rec: dict[str, Any] | None = None) -> dict[str, Any]:
    rec = rec if rec is not None else _record(ws)
    fr = _freshness(ws, rec)
    rels = releases(ws)
    latest = rels[-1] if rels else None
    return {"project": _summary(p, ws), "drawing": rec, "can_edit": can_edit, "stale": fr["state"] == "stale",
            "current_rev": fr["current_rev"], "made_from_rev": fr["made_from_rev"], "edits": _edits(ws),
            "release": None if latest is None else
            {"rev": latest.get("rev"), "date": latest.get("date"), "by": latest.get("by"),
             "current": deliverables.same_build(latest.get("build"), deliverables.build_stamp(ws))}}


def local_date(day: str | None, tz: str | None) -> str:
    """The user's calendar date (MAKE-26): the browser's own date, else today in their IANA zone, else UTC."""
    if day and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        try:
            datetime.strptime(day, "%Y-%m-%d")
            return day
        except ValueError:
            pass
    if tz:
        try:
            from zoneinfo import ZoneInfo

            return datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")
        except (KeyError, ValueError, OSError):
            pass
    return datetime.now(UTC).strftime("%Y-%m-%d")


@router.get("/projects")
def list_projects(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    _access(ctx)
    org = ctx.require_org()
    rows = permissions.visible(ctx.db, ctx.user, ctx.db.scalars(
        select(Project).where(Project.org_id == org.id, Project.archived.is_(False))
        .order_by(Project.updated_at.desc())).all())
    return {"items": [_summary(p, workspace_for(p)) for p in rows]}


@router.get("/projects/{project_id}")
def get_drawing(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    return _state(p, workspace_for(p), ctx.role != "viewer")


def _meta(p: Project, ws: Path, user_name: str, day: str) -> dict[str, Any]:
    st = _status(ws)
    return {"title": p.name.removeprefix("Demo · "), "drawing_no": f"FW-{p.id[:8].upper()}", "drawn_by": user_name,
            "date": day, "model_rev": _model_rev(ws, st.get("build_id")), "releases": releases(ws)}


async def _generate(p: Project, ws: Path, opts: dict[str, Any], meta: dict[str, Any], edits: dict[str, Any],
                    dest: Path) -> dict[str, Any]:
    await wait_finalized(p.id)  # a fast Studio build exports part.step in the background
    st = _status(ws)
    if not _verified(ws, st):
        raise HTTPException(409, "This project has no verified build yet. Build the model in the Design Studio first.")
    res = await dworker.generate(p.org_id, ws / "out", dest, opts, meta, edits)
    if not res.get("ok"):
        if res.get("user_error"):
            raise HTTPException(409, res.get("error") or "Drawing failed")
        raise HTTPException(500, "The drawing could not be generated for this model. Check the model in the Design Studio and try again.")
    return res


@router.post("/projects/{project_id}/generate")
async def generate(project_id: str, body: GenerateIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    if ctx.role == "viewer":
        raise HTTPException(403, "Viewers can open drawings but can't generate them.")
    ws = workspace_for(p)
    opts = body.model_dump(exclude={"local_date", "tz"})
    opts["tolerance"] = {"mode": body.tolerance.mode, "class": body.tolerance.tclass, "text": body.tolerance.text}
    meta = _meta(p, ws, ctx.user.name or ctx.user.email, local_date(body.local_date, body.tz))
    res = await _generate(p, ws, opts, meta, _edits(ws), ws / "drawings")
    rec = res["result"]
    audit(ctx.db, "drawing.generated", ctx.user, p.org_id, target=p.id, rev=rec.get("model_rev"),
          chk12=rec["check"]["passed"])
    track(ctx.db, "drawing_generated", ctx.user, p.org_id, chk12=rec["check"]["passed"], sheet=rec["sheet"]["size"])
    ctx.db.commit()
    return {**_state(p, ws, True, rec), "elapsed_s": res.get("elapsed_s")}


@router.get("/projects/{project_id}/edits")
def get_edits(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    return _edits(workspace_for(p))


@router.put("/projects/{project_id}/edits")
@router.post("/projects/{project_id}/edits")
async def put_edits(project_id: str, body: EditsIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Save the user's edits (keyed by dimension id, re-applied on every regeneration) and redraw the sheet."""
    p = _project(ctx, project_id)
    if ctx.role == "viewer":
        raise HTTPException(403, "Viewers can open drawings but can't edit them.")
    try:
        ed = normalize_edits(body.model_dump(exclude={"local_date", "tz", "regenerate"}))
    except DrawingInputError as e:
        raise HTTPException(422, str(e)) from None
    ws = workspace_for(p)
    d = ws / "drawings"
    d.mkdir(parents=True, exist_ok=True)
    (d / "edits.json").write_text(json.dumps(ed, indent=1, sort_keys=True), encoding="utf-8")
    rec = _record(ws)
    audit(ctx.db, "drawing.edited", ctx.user, p.org_id, target=p.id, dims=len(ed["dims"]), notes=len(ed["notes"]))
    ctx.db.commit()
    if rec is None or not body.regenerate or not _verified(ws, _status(ws)):
        return _state(p, ws, True)
    meta = _meta(p, ws, ctx.user.name or ctx.user.email, local_date(body.local_date, body.tz))
    res = await _generate(p, ws, rec.get("options") or {}, meta, ed, d)
    return {**_state(p, ws, True, res["result"]), "elapsed_s": res.get("elapsed_s")}


async def render_issue(project: Project, ws: Path, dest: Path, release: dict[str, Any], user_name: str) -> dict[str, Any]:
    """Frozen issue copy for the release gate: the current saved options and edits, drawn from the current build in
    the issue style, REV = ``release["rev"]``, revision table = earlier releases + this one, dated by the release.
    Writes sheet.pdf / sheet.dxf / sheet.svg / drawing.json into ``dest``; never touches the working sheet or its
    history. Raises ValueError (plain message) when there is no verified build or CHK-12 fails."""
    rec = _record(ws) or {}
    meta = _meta(project, ws, user_name, release.get("date") or local_date(None, None))
    meta["releases"] = [r for r in releases(ws) if r.get("rev") != release.get("rev")]
    meta["issue"] = {"rev": release["rev"], "date": release.get("date") or meta["date"],
                     "by": release.get("by") or user_name, "note": release.get("note") or "Issued",
                     "build": release.get("build")}
    try:
        res = await _generate(project, ws, rec.get("options") or {}, meta, _edits(ws), dest)
    except HTTPException as e:
        raise ValueError(e.detail if isinstance(e.detail, str) else "The drawing could not be generated") from None
    out = res["result"]
    if not out["check"]["passed"]:
        raise ValueError("The drawing fails its consistency check (CHK-12): " + "; ".join(out["check"]["problems"])
                         + ". Fix it in Drawing Studio before issuing.")
    return out


@router.get("/projects/{project_id}/files/{name}")
def drawing_file(project_id: str, name: str, download: bool = False, copy: str | None = None,
                 ctx: Ctx = Depends(verified_ctx)) -> FileResponse:
    p = _project(ctx, project_id)
    if name not in FILES:
        raise HTTPException(404)
    if copy not in (None, "issue", "review"):
        raise HTTPException(422, "copy must be issue or review")
    which = copy or ("review" if name == "sheet.svg" and not download else "issue")
    f = workspace_for(p) / "drawings" / COPIES[(name, which)]
    if not f.is_file():
        raise HTTPException(404, "Generate the drawing first")
    headers = {"Cache-Control": "no-store"}
    if download or name != "sheet.svg":
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in p.name.removeprefix("Demo · "))[:60] or "part"
        suffix = "_review" if which == "review" and name != "sheet.dxf" else ""
        headers["Content-Disposition"] = f'attachment; filename="{safe}_drawing{suffix}{Path(name).suffix}"'
        track(ctx.db, "download", ctx.user, p.org_id, file=f"drawing/{name}")
        ctx.db.commit()
    return FileResponse(f, media_type=FILES[name], headers=headers)
