"""Manufacturing Advisor API (`/api/m/manufacturing`): DFM analysis of a project's verified build, shop profile,
material library and the manufacturability report. Org-scoped; locked workspaces get 402."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from aicad import deliverables
from aicad.manufacturing import ADVICE_LEVELS, ANALYSER_VERSION, fixes, matlib
from aicad.manufacturing import shop as shop_mod
from aicad.manufacturing.analyze import DISCLAIMER, Inputs, analyse_workspace
from aicad.manufacturing.cost import LABEL as COST_LABEL
from aicad.platform.collab import permissions
from aicad.platform.config import get_settings
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.models import Project
from aicad.platform.routers.projects import (
    ParamsIn,
    _project,
    _read_status,
    _thumb,
    current_editable,
    set_params,
    wait_finalized,
    workspace_for,
)
from aicad.platform.services import audit, org_modules

CODE = "manufacturing"
router = APIRouter(prefix=f"/api/m/{CODE}", tags=["manufacturing"])
_lock = threading.Lock()  # one OCCT analysis / report at a time per server process


def module_ctx(ctx: Ctx = Depends(verified_ctx)) -> Ctx:
    org = ctx.require_org()
    if CODE not in org_modules(ctx.db, org) and not ctx.god_on("bypass_paywall"):
        raise HTTPException(402, {"message": "Manufacturing Advisor isn't included in your plan. Unlock the add-on "
                                             "to analyse your parts.", "cta": f"/app/modules/{CODE}"})
    return ctx


def _org_dir(ctx: Ctx) -> Path:
    root = get_settings().workspaces_dir.resolve()
    d = (root / ctx.require_org().id).resolve()
    if root not in d.parents:
        raise HTTPException(400, "bad workspace")
    return d


def _can_edit(ctx: Ctx) -> bool:
    return ctx.role in ("owner", "admin", "engineer")


def _built(ws: Path) -> dict[str, Any]:
    st = _read_status(ws)
    if not st.get("ok") or not (ws / "out" / "part.step").is_file():
        raise HTTPException(409, "This project has no verified build yet. Build it in the Design Studio first.")
    return st


def _project_material(ws: Path) -> str | None:
    try:
        st = json.loads((ws / ".fw" / "project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    code = st.get("material")
    return code if code and matlib.get(code) else None


def _saved(ws: Path) -> dict[str, Any] | None:
    f = ws / CODE / "analysis.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except ValueError:
        return None


def _fresh(ws: Path, a: dict[str, Any]) -> bool:
    return deliverables.freshness(a.get("build"), ws)["state"] == "current"


def _out(p: Project, ws: Path, a: dict[str, Any]) -> dict[str, Any]:
    """The analysis as served: project, staleness (one rule for every module) and a fix action per finding."""
    fresh = _fresh(ws, a)
    st = _read_status(ws)
    res = fixes.attach(a, current_editable(ws) if fresh else {}, st.get("param_meta") or {}, fresh=fresh)
    if "summary" not in res:  # analyses saved before mfg-1.1 carry only the CHK-13 counts
        res["summary"] = (res.get("chk13") or {}).get("counts")
    return {**res, "project": {"id": p.id, "name": p.name}, "stale": not fresh,
            "freshness": deliverables.freshness(a.get("build"), ws)}


# ----------------------------------------------------------------------------- catalogue data
@router.get("/meta")
def meta(ctx: Ctx = Depends(module_ctx)) -> dict[str, Any]:
    return {"analyser": ANALYSER_VERSION, "advice_levels": ADVICE_LEVELS, "cost_label": COST_LABEL,
            "disclaimer": DISCLAIMER, "can_edit": _can_edit(ctx)}


@router.get("/materials")
def materials(ctx: Ctx = Depends(module_ctx)) -> dict[str, Any]:
    return {"version": matlib.LIBRARY_VERSION, "items": matlib.library()}


@router.get("/projects")
def projects(ctx: Ctx = Depends(module_ctx)) -> dict[str, Any]:
    org = ctx.require_org()
    rows = permissions.visible(ctx.db, ctx.user, ctx.db.scalars(
        select(Project).where(Project.org_id == org.id, Project.archived.is_(False))
        .order_by(Project.updated_at.desc())).all())
    items = []
    for p in rows:
        ws = workspace_for(p)
        st = p.last_status or {}
        a = _saved(ws)
        items.append({"id": p.id, "name": p.name, "thumbnail": _thumb(p), "built": bool(st.get("ok")),
                      "material": st.get("material"), "updated_at": p.updated_at.isoformat(),
                      "analysed": bool(a),
                      "counts": (a or {}).get("summary") or (a or {}).get("chk13", {}).get("counts"),
                      "stale": bool(a) and not _fresh(ws, a)})
    return {"items": items}


# ----------------------------------------------------------------------------- shop profile
@router.get("/shop-profile")
def get_profile(ctx: Ctx = Depends(module_ctx)) -> dict[str, Any]:
    prof, is_default = shop_mod.load(_org_dir(ctx))
    return {"profile": prof.model_dump(), "is_default": is_default, "can_edit": _can_edit(ctx),
            "note": shop_mod.defaults_note()["text"], "fingerprint": prof.fingerprint()}


@router.api_route("/shop-profile", methods=["PUT", "POST"])
def put_profile(body: dict[str, Any], ctx: Ctx = Depends(module_ctx)) -> dict[str, Any]:
    if not _can_edit(ctx):
        raise HTTPException(403, "Viewers can't change the shop profile")
    try:
        prof = shop_mod.ShopProfile.model_validate(body)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first.get("loc", ()))
        raise HTTPException(422, f"Shop profile: {where}: {first.get('msg')}") from None
    shop_mod.save(_org_dir(ctx), prof)
    audit(ctx.db, "manufacturing.shop_profile", ctx.actor, ctx.require_org().id, fingerprint=prof.fingerprint())
    ctx.db.commit()
    return get_profile(ctx)


@router.delete("/shop-profile")
def reset_profile(ctx: Ctx = Depends(module_ctx)) -> dict[str, Any]:
    if not _can_edit(ctx):
        raise HTTPException(403, "Viewers can't change the shop profile")
    shop_mod.profile_path(_org_dir(ctx)).unlink(missing_ok=True)
    return get_profile(ctx)


# ----------------------------------------------------------------------------- analysis
@router.post("/projects/{project_id}/analyse")
def analyse(project_id: str, body: Inputs, ctx: Ctx = Depends(module_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    if not _can_edit(ctx):
        raise HTTPException(403, "Viewers can open saved analyses but can't run new ones")
    ws = workspace_for(p)
    _built(ws)
    if body.material and not matlib.get(body.material):
        raise HTTPException(422, "Unknown material")
    prof, _ = shop_mod.load(_org_dir(ctx))
    with _lock:
        try:
            a = analyse_workspace(ws, prof, body, _project_material(ws))
        except (OSError, ValueError) as e:
            raise HTTPException(422, f"The model could not be analysed: {e}") from None
    return _out(p, ws, a)


@router.get("/projects/{project_id}/analysis")
def last_analysis(project_id: str, ctx: Ctx = Depends(module_ctx)) -> dict[str, Any] | None:
    """The last saved analysis, or null when the project hasn't been analysed yet."""
    p = _project(ctx, project_id)
    ws = workspace_for(p)
    a = _saved(ws)
    if a is None:
        return None
    return _out(p, ws, a)


class FixIn(BaseModel):
    finding: str = Field(max_length=16)
    param: str = Field(max_length=64)
    value: float
    quantity: int = Field(default=10, ge=1, le=1_000_000)
    material: str | None = None
    tolerance: str = "general"


@router.post("/projects/{project_id}/fix")
async def apply_fix(project_id: str, body: FixIn, ctx: Ctx = Depends(module_ctx)) -> dict[str, Any]:
    """Apply an offered parameter fix (deterministic rebuild, no AI), re-run the analysis, return the delta."""
    p = _project(ctx, project_id)
    if not _can_edit(ctx):
        raise HTTPException(403, "Viewers can't change the design")
    ws = workspace_for(p)
    _built(ws)
    prev = _saved(ws)
    if prev is None:
        raise HTTPException(409, "Run the analysis first")
    before = _out(p, ws, prev)
    f = next((x for x in before["findings"] if x["id"] == body.finding), None)
    act = (f or {}).get("action") or {}
    if act.get("kind") != "param" or act.get("param") != body.param or abs(float(act["to"]) - body.value) > 1e-9:
        raise HTTPException(409, "This fix is no longer offered for the current model. Re-analyse and try again.")
    inputs = Inputs.model_validate({"quantity": body.quantity, "material": body.material,
                                    "tolerance": body.tolerance})
    res = await set_params(project_id, ParamsIn(values={body.param: body.value}), ctx)
    await wait_finalized(p.id)  # the analysis reads the exported STEP
    prof, _ = shop_mod.load(_org_dir(ctx))
    with _lock:
        try:
            a = analyse_workspace(ws, prof, inputs, _project_material(ws))
        except (OSError, ValueError) as e:
            raise HTTPException(422, f"The model could not be analysed: {e}") from None
    after = _out(p, ws, a)
    audit(ctx.db, "manufacturing.fix_applied", ctx.user, p.org_id, target=p.id, finding=f["rule"],  # type: ignore[index]
          param=body.param, value=body.value)
    ctx.db.commit()
    return {"applied": {"param": body.param, "label": act.get("label"), "from": act.get("from"), "to": body.value,
                        "revision": res.get("revision"), "finding": f["title"]},  # type: ignore[index]
            "delta": fixes.delta(before, after), "analysis": after}


def _report_inputs(project_id: str, ctx: Ctx) -> tuple[Project, dict[str, Any], dict[str, Any] | None]:
    p = _project(ctx, project_id)
    ws = workspace_for(p)
    a = _saved(ws)
    if a is None:
        raise HTTPException(404, "Run the analysis first")
    topo = None
    tp = ws / "out" / "topo.json"
    if tp.is_file():
        topo = json.loads(tp.read_text(encoding="utf-8"))
    return p, a, topo


def _fname(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")[:60] or "part"


@router.get("/projects/{project_id}/report.html", response_class=HTMLResponse)
def report_html(project_id: str, ctx: Ctx = Depends(module_ctx)) -> HTMLResponse:
    from aicad.manufacturing import report

    p, a, topo = _report_inputs(project_id, ctx)
    with _lock:
        body = report.build_html(a, p.name, topo)
    return HTMLResponse(body, headers={"Content-Disposition": f'inline; filename="{_fname(p.name)}_dfm.html"'})


@router.get("/projects/{project_id}/report.pdf")
def report_pdf(project_id: str, ctx: Ctx = Depends(module_ctx)) -> Response:
    from aicad.manufacturing import report

    p, a, topo = _report_inputs(project_id, ctx)
    with _lock:
        pdf = report.build_pdf(a, p.name, topo)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{_fname(p.name)}_dfm.pdf"'})
