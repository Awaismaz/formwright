"""Assembly Studio API (module ``assembly``): assemblies of verified project parts and Toolbox components, with
mates, interference and clearance checks, exploded view, BOM, fastener auto-fit and assembly STEP export.

All routes are org-scoped and need the module (plan / add-on ``addon_assembly`` / God-mode bypass), else 402.
Viewers can open assemblies, the BOM and the last exported STEP; changes need the engineer role.

  GET    /api/m/assembly/assemblies                          list
  POST   /api/m/assembly/assemblies                          create (optionally from a project: its part, fixed)
  GET    /api/m/assembly/for-project/{project_id}            the assembly opened from that project (or null)
  GET    /api/m/assembly/sources                             verified projects + Toolbox catalogue to insert
  GET    /api/m/assembly/assemblies/{id}                     full view (instances, parts, mates, solve, explode, BOM)
  PATCH  /api/m/assembly/assemblies/{id}                     rename
  DELETE /api/m/assembly/assemblies/{id}
  POST   /api/m/assembly/assemblies/{id}/instances           insert a project part or a Toolbox component
  PATCH  /api/m/assembly/assemblies/{id}/instances/{iid}     rename / show / fix / move
  DELETE /api/m/assembly/assemblies/{id}/instances/{iid}
  POST   /api/m/assembly/assemblies/{id}/instances/{iid}/refresh   "Part updated: refresh"
  POST   /api/m/assembly/assemblies/{id}/mates               add a mate (solved immediately)
  PATCH  /api/m/assembly/assemblies/{id}/mates/{mid}         value / flip / suppress
  DELETE /api/m/assembly/assemblies/{id}/mates/{mid}
  DELETE /api/m/assembly/assemblies/{id}/groups/{gid}        remove a fastener stack
  POST   /api/m/assembly/assemblies/{id}/analyse             interference + clearance (exact)
  GET    /api/m/assembly/assemblies/{id}/bom[?format=csv]
  POST   /api/m/assembly/assemblies/{id}/export              assembly STEP (re-import verified)
  GET    /api/m/assembly/assemblies/{id}/files/assembly.step
  POST   /api/m/assembly/assemblies/{id}/fasteners/propose   fastener auto-fit proposal for a hole / pattern
  POST   /api/m/assembly/assemblies/{id}/fasteners/accept    insert the proposed stacks
  POST   /api/m/assembly/assemblies/{id}/smart/plan          Hex + Fitz: description -> components + placement plan
  POST   /api/m/assembly/assemblies/{id}/smart/run           Fitz inserts, places and mates the approved plan
  GET    /api/m/assembly/parts/{key}/topo                    exact topology of a part snapshot (viewer)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from aicad import similarity, toolbox
from aicad.assembly import AssemblyInputError, fitz, librarian, service, solver, store
from aicad.platform.collab import permissions
from aicad.platform.config import get_settings
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.models import Project
from aicad.platform.routers.projects import _thumb, wait_finalized, workspace_for
from aicad.platform.services import audit, debit, org_modules, track

router = APIRouter(prefix="/api/m/assembly", tags=["assembly"])
CODE = "assembly"
PNG_MAGIC = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
_locks: dict[str, asyncio.Lock] = {}


# ----------------------------------------------------------------------------- access
def asm_ctx(ctx: Ctx = Depends(verified_ctx)) -> Ctx:
    org = ctx.require_org()
    if CODE not in org_modules(ctx.db, org) and not ctx.god_on("bypass_paywall"):
        raise HTTPException(402, {"message": "Assembly Studio isn't included in your plan. Unlock the add-on to "
                                             "assemble your parts.", "cta": "/app/modules/assembly"})
    return ctx


def _editor(ctx: Ctx) -> None:
    if ctx.role == "viewer":
        raise HTTPException(403, "Viewers can open assemblies but can't change them.")


def _root(ctx: Ctx) -> Path:
    return store.org_root(get_settings().data_dir, ctx.require_org().id)


def _doc(ctx: Ctx, aid: str) -> dict[str, Any]:
    try:
        d = store.load(_root(ctx), aid)
    except AssemblyInputError:
        d = None
    if d is None or d.get("org_id") != ctx.require_org().id:
        raise HTTPException(404, "Assembly not found")
    return d


def _lock(aid: str) -> asyncio.Lock:
    lk = _locks.get(aid)
    if lk is None:
        lk = _locks[aid] = asyncio.Lock()
    return lk


def _err(e: Exception) -> HTTPException:
    if isinstance(e, AssemblyInputError):
        return HTTPException(409, str(e))
    if isinstance(e, toolbox.ToolboxError):
        return HTTPException(422, str(e))
    if isinstance(e, service.WorkerError):
        return HTTPException(500, "The geometry operation failed on this assembly. Try again, or remove the part "
                                  "that was just added.")
    raise e


def _project(ctx: Ctx, pid: str) -> Project:
    """A part used in an assembly: reading it is enough (the assembly is what changes)."""
    return permissions.require_project(ctx, pid, "read")


def _status(ws: Path) -> dict[str, Any]:
    f = ws / "out" / "status.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    except (OSError, ValueError):
        return {}


def _model_rev(ws: Path, build_id: Any) -> str | None:
    root = ws / "revisions"
    if not root.is_dir():
        return None
    for d in sorted((d for d in root.iterdir() if d.is_dir() and d.name.isdigit()), key=lambda d: -int(d.name)):
        st = store.read_json(d / "status.json") or {}
        if build_id is not None and str(st.get("build_id")) == str(build_id):
            return d.name
    return None


async def _project_part(ctx: Ctx, p: Project) -> str:
    ws = workspace_for(p)
    await wait_finalized(p.id)
    st = _status(ws)
    return await service.ensure_project_part(_root(ctx), p.org_id, p.id, p.name, ws, st,
                                             _model_rev(ws, st.get("build_id")))


# ----------------------------------------------------------------------------- views
def _projects_for(ctx: Ctx, doc: dict[str, Any]) -> dict[str, Project]:
    ids = {i["source"]["project_id"] for i in doc["instances"] if i["source"]["kind"] == "project"}
    if doc.get("project_id"):
        ids.add(doc["project_id"])
    if not ids:
        return {}
    rows = ctx.db.scalars(select(Project).where(Project.id.in_(ids), Project.org_id == ctx.require_org().id)).all()
    return {p.id: p for p in rows}


def _view(ctx: Ctx, doc: dict[str, Any]) -> dict[str, Any]:
    root = _root(ctx)
    parts = service._parts(root, doc)
    projects = _projects_for(ctx, doc)
    current: dict[str, str | None] = {pid: str(_status(workspace_for(p)).get("build_id")) for pid, p in projects.items()}
    names = service.display_names(doc)
    solve = doc.get("solve") or {}
    sinst = solve.get("instances", {})
    smates = solve.get("mates", {})
    instances = []
    for i in doc["instances"]:
        src = i["source"]
        stale = missing = False
        if src["kind"] == "project":
            pid = src["project_id"]
            if pid not in projects:
                missing = True
            else:
                stale = current.get(pid) not in (None, "None") and current.get(pid) != str(src["build_id"])
        instances.append({**i, "display": names[i["id"]], "stale": stale, "source_missing": missing,
                          "dof": sinst.get(i["id"])})
    mates = []
    for m in doc["mates"]:
        st = smates.get(m["id"], {})
        if m.get("broken"):
            status = "broken"
        elif m.get("suppressed"):
            status = "suppressed"
        elif st.get("conflict"):
            status = "conflict"
        elif st and not st.get("ok"):
            status = "unsatisfied"
        else:
            status = "ok"
        mates.append({"id": m["id"], "type": m["type"], "label": solver.LABEL[m["type"]], "value": m.get("value"),
                      "flip": m.get("flip", False), "suppressed": m.get("suppressed", False), "group": m.get("group"),
                      "a": {k: m["a"][k] for k in ("inst", "kind", "id")}, "b": {k: m["b"][k] for k in ("inst", "kind", "id")},
                      "a_name": names.get(m["a"]["inst"]), "b_name": names.get(m["b"]["inst"]), "status": status,
                      "a_desc": _ref_desc(doc, parts, m["a"]), "b_desc": _ref_desc(doc, parts, m["b"]),
                      "a_lost": bool(m["a"].get("lost")), "b_lost": bool(m["b"].get("lost")),
                      "residual_mm": st.get("residual_mm"), "residual_deg": st.get("residual_deg")})
    pview = {}
    for k, p in parts.items():
        info = p["info"]
        pview[k] = {"key": k, "name": p["name"], "kind": p["kind"], "material": p.get("material"),
                    "standard": p.get("standard"), "code": p.get("code"), "params": p.get("params"),
                    "bbox": info["bbox"], "center": info["center"], "volume": info["volume"],
                    "holes": [{kk: h.get(kk) for kk in ("id", "d", "axis", "center", "depth", "through", "faces")}
                              for h in info.get("holes", [])],
                    "patterns": info.get("patterns", []), "topo_url": f"/api/m/assembly/parts/{k}/topo"}
    ddir = store.doc_dir(root, doc["id"])
    sig = service.geometry_signature(doc)
    analysis = store.read_json(ddir / "analysis.json")
    if analysis:
        analysis["stale"] = analysis.get("signature") != sig
    exp = store.read_json(ddir / "export.json")
    if exp:
        exp["stale"] = exp.get("signature") != sig
        exp["url"] = f"/api/m/assembly/assemblies/{doc['id']}/files/assembly.step"
    home = projects.get(doc.get("project_id") or "")
    return {
        "assembly": {k: doc.get(k) for k in ("id", "name", "project_id", "rev", "created_at", "updated_at")},
        "home_project": {"id": home.id, "name": home.name} if home else None,
        "instances": instances, "parts": pview, "mates": mates, "groups": doc["groups"], "solve": solve or None,
        "explode": service.explode(root, doc), "analysis": analysis, "export": exp,
        "bom": service.bom(root, doc, {pid: p.name for pid, p in projects.items()}),
        "can_edit": ctx.role != "viewer",
        "thumb_rev": (store.read_json(ddir / "thumb.json") or {}).get("rev"),
    }


_AXES = (("+X", (1, 0, 0)), ("−X", (-1, 0, 0)), ("+Y", (0, 1, 0)), ("−Y", (0, -1, 0)), ("+Z", (0, 0, 1)),
         ("−Z", (0, 0, -1)))


def _ref_desc(doc: dict[str, Any], parts: dict[str, dict[str, Any]], side: dict[str, Any]) -> str:
    """Plain description of a mate reference, so two mates of one type can be told apart (AMI-20):
    "Ø6.6 hole", "Ø20 cylinder", "Ø5.5 edge", "+Z face" (world direction of the outward normal)."""
    import numpy as np

    from aicad.assembly import xform

    r = side.get("ref") or {}
    try:
        inst = service._inst(doc, side["inst"])
    except AssemblyInputError:
        return "reference"
    if r.get("kind") == "plane":
        v = xform.vec(xform.from12(inst["T"]), r["v"])
        for name, ax in _AXES:
            if float(np.dot(v, ax)) > 1 - 1e-6:
                return f"{name} face"
        return "flat face"
    if r.get("r") is None:
        return "straight edge"
    d = f"Ø{2 * float(r['r']):.4g}"
    if side["kind"] == "edge":
        return f"{d} edge"
    holes = (parts.get(inst["part"]) or {}).get("info", {}).get("holes", [])
    return f"{d} hole" if any(side["id"] in h.get("faces", []) for h in holes) else f"{d} cylinder"


def _thumb_url(ctx: Ctx, doc: dict[str, Any]) -> str | None:
    meta = store.read_json(store.doc_dir(_root(ctx), doc["id"]) / "thumb.json")
    if not meta or not (store.doc_dir(_root(ctx), doc["id"]) / "thumb.png").is_file():
        return None
    return f"/api/m/assembly/assemblies/{doc['id']}/thumbnail?v={meta.get('rev', 0)}"


def _summary(ctx: Ctx, doc: dict[str, Any]) -> dict[str, Any]:
    s = doc.get("solve") or {}
    projects = _projects_for(ctx, doc)
    current = {pid: str(_status(workspace_for(p)).get("build_id")) for pid, p in projects.items()}
    stale = sum(1 for i in doc["instances"] if i["source"]["kind"] == "project"
                and current.get(i["source"]["project_id"]) not in (None, "None")
                and current.get(i["source"]["project_id"]) != str(i["source"]["build_id"]))
    out = {"id": doc["id"], "name": doc["name"], "project_id": doc.get("project_id"), "updated_at": doc["updated_at"],
           "instances": len(doc["instances"]), "mates": len(doc["mates"]),
           "fasteners": sum(1 for g in doc["groups"] if g.get("kind") == "fastener"),
           "status": s.get("status"), "dof": s.get("dof"), "free_spins": s.get("free_spins"),
           "broken_mates": sum(1 for m in doc["mates"] if m.get("broken")), "stale_parts": stale,
           "stacks_to_check": sum(1 for g in doc["groups"] if g.get("check"))}
    own = _thumb_url(ctx, doc)
    if own:
        return {**out, "thumbnail": own, "own_thumbnail": True}
    thumb = None
    pid = doc.get("project_id") or next((i["source"]["project_id"] for i in doc["instances"]
                                         if i["source"]["kind"] == "project"), None)
    if pid and pid in projects:
        thumb = _thumb(projects[pid])
    return {**out, "thumbnail": thumb, "own_thumbnail": False}


# ----------------------------------------------------------------------------- bodies
class CreateIn(BaseModel):
    name: str | None = Field(None, max_length=120)
    project_id: str | None = None


class RenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ToolboxIn(BaseModel):
    code: str
    params: dict[str, float] = Field(default_factory=dict)


class InsertIn(BaseModel):
    project_id: str | None = None
    toolbox: ToolboxIn | None = None


class RotateIn(BaseModel):
    axis: Literal["X", "Y", "Z"]
    deg: float = Field(ge=-360, le=360)


class InstancePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    visible: bool | None = None
    fixed: bool | None = None
    translate: list[float] | None = Field(None, min_length=3, max_length=3)
    rotate: RotateIn | None = None
    T: list[float] | None = Field(None, min_length=12, max_length=12)


class Sel(BaseModel):
    inst: str
    kind: Literal["face", "edge"]
    id: int


class MateIn(BaseModel):
    type: Literal["auto", "coincident", "flush", "distance", "angle", "concentric"] = "auto"
    a: Sel
    b: Sel
    value: float = 0.0
    flip: bool = False


class MatePatch(BaseModel):
    type: Literal["coincident", "flush", "distance", "angle", "concentric"] | None = None
    a: Sel | None = None
    b: Sel | None = None
    value: float | None = None
    flip: bool | None = None
    suppressed: bool | None = None


class ThumbIn(BaseModel):
    png_b64: str = Field(max_length=2_000_000)
    rev: int = Field(ge=0)


class HoleRef(BaseModel):
    inst: str
    hole: int = Field(ge=0)


class FitIn(BaseModel):
    inst: str | None = None
    hole: int = Field(0, ge=0)
    pattern: bool = True
    targets: list[HoleRef] | None = Field(None, max_length=64)   # several holes at once ("Fasten these two parts")
    style: Literal["hex_bolt", "shcs"] = "hex_bolt"
    washers: Literal["both", "head", "none"] = "both"
    flip: bool = False


class PairIn(BaseModel):
    a: str
    b: str
    style: Literal["hex_bolt", "shcs"] = "hex_bolt"
    washers: Literal["both", "head", "none"] = "both"


class FixHoleIn(BaseModel):
    inst: str
    param: str = Field(min_length=1, max_length=80)
    value: float


def _targets(root: Path, doc: dict[str, Any], body: FitIn) -> list[dict[str, Any]]:
    if body.targets:
        out = []
        for t in body.targets:
            inst = service._inst(doc, t.inst)
            if inst.get("group"):
                raise AssemblyInputError("Pick a hole in a part, not in a fastener.")
            if not 0 <= t.hole < len((store.part(root, inst["part"]) or {}).get("info", {}).get("holes", [])):
                raise AssemblyInputError("Hole not found")
            out.append({"inst": t.inst, "hole": t.hole})
        return out
    if body.inst is None:
        raise AssemblyInputError("Pick a hole first.")
    return service.fastener_targets(root, doc, body.inst, body.hole, body.pattern)


def _hole_param(ctx: Ctx, doc: dict[str, Any], iid: str, d: float, to_d: float) -> dict[str, Any] | None:
    """The one editable design parameter of a project part that sets this hole's Ø (value equal to the Ø, or to
    its radius). None when there is no such parameter or more than one candidate: then the fix is left to the
    Design Studio, never guessed."""
    from aicad.platform.routers.projects import current_editable

    inst = service._inst(doc, iid)
    if inst["source"]["kind"] != "project":
        return None
    try:
        p = _project(ctx, inst["source"]["project_id"])
    except HTTPException:
        return None
    ws = workspace_for(p)
    if str(_status(ws).get("build_id")) != str(inst["source"]["build_id"]):
        return None  # the assembly shows an older build: refresh first
    meta = _status(ws).get("param_meta") or {}
    hits = []
    for name, val in current_editable(ws).items():
        if isinstance(val, bool):
            continue
        for scale in (1.0, 0.5):
            if abs(float(val) - d * scale) < 1e-9:
                hits.append({"project_id": p.id, "project": service.clean_name(p.name), "param": name,
                             "label": (meta.get(name) or {}).get("label") or name, "from": float(val),
                             "to": round(to_d * scale, 6), "radius": scale == 0.5})
    return hits[0] if len(hits) == 1 else None


# ----------------------------------------------------------------------------- routes
@router.get("/assemblies")
def list_assemblies(ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    return {"items": [_summary(ctx, d) for d in store.list_docs(_root(ctx)) if d.get("org_id") == ctx.require_org().id]}


@router.get("/for-project/{project_id}")
def for_project(project_id: str, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    _project(ctx, project_id)
    for d in store.list_docs(_root(ctx)):
        if d.get("project_id") == project_id and d.get("org_id") == ctx.require_org().id:
            return {"assembly": _summary(ctx, d)}
    return {"assembly": None}


@router.get("/sources")
def sources(ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    org = ctx.require_org()
    rows = permissions.visible(ctx.db, ctx.user, ctx.db.scalars(
        select(Project).where(Project.org_id == org.id, Project.archived.is_(False))
        .order_by(Project.updated_at.desc())).all())
    projects = []
    for p in rows:
        ws = workspace_for(p)
        st = _status(ws)
        projects.append({"id": p.id, "name": p.name, "thumbnail": _thumb(p), "material": st.get("material"),
                         "verified": bool(st.get("ok")) and (ws / "out" / "part.step").is_file(),
                         "part": st.get("part")})
    tb = [c for c in toolbox.catalog()]
    return {"projects": projects, "toolbox": tb, "mate_types": [{"type": t, "label": solver.LABEL[t],
                                                                  "needs": solver.NEEDS[t]} for t in solver.MATE_TYPES]}


@router.post("/assemblies")
async def create(body: CreateIn, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    _editor(ctx)
    org = ctx.require_org()
    root = _root(ctx)
    p = _project(ctx, body.project_id) if body.project_id else None
    name = (body.name or "").strip() or (f"{service.clean_name(p.name)} assembly" if p else "New assembly")
    doc = store.new_doc(name, org.id, ctx.user.id, p.id if p else None)
    if p is not None:
        try:
            key = await _project_part(ctx, p)
        except (AssemblyInputError, service.WorkerError) as e:
            raise _err(e) from e
        service.add_instance(root, doc, key)
        service.run_solve(root, doc)
    store.save(root, doc)
    audit(ctx.db, "assembly.created", ctx.user, org.id, target=doc["id"], project=doc.get("project_id"))
    track(ctx.db, "assembly_created", ctx.user, org.id, from_project=bool(p))
    ctx.db.commit()
    return _view(ctx, doc)


@router.get("/assemblies/{aid}")
def get_assembly(aid: str, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    try:
        return _view(ctx, _doc(ctx, aid))
    except AssemblyInputError as e:
        raise _err(e) from e


@router.patch("/assemblies/{aid}")
async def rename(aid: str, body: RenameIn, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    _editor(ctx)
    async with _lock(aid):
        doc = _doc(ctx, aid)
        doc["name"] = body.name.strip()
        store.save(_root(ctx), doc)
    return _view(ctx, doc)


@router.delete("/assemblies/{aid}")
async def delete(aid: str, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    _editor(ctx)
    async with _lock(aid):
        _doc(ctx, aid)
        store.delete(_root(ctx), aid)
    audit(ctx.db, "assembly.deleted", ctx.user, ctx.require_org().id, target=aid)
    ctx.db.commit()
    return {"ok": True}


async def _mutate(ctx: Ctx, aid: str, fn: Any, solve: bool = True, prealign: Any = None) -> dict[str, Any]:
    _editor(ctx)
    async with _lock(aid):
        doc = _doc(ctx, aid)
        root = _root(ctx)
        try:
            r = fn(doc, root)
            if asyncio.iscoroutine(r):
                r = await r
            if solve:
                service.run_solve(root, doc, prealign(doc, r) if prealign else ())
        except (AssemblyInputError, toolbox.ToolboxError, service.WorkerError) as e:
            raise _err(e) from e
        store.save(root, doc)
    view = _view(ctx, doc)
    if isinstance(r, dict) and r.get("_extra"):
        view["result"] = r["_extra"]
    return view


@router.post("/assemblies/{aid}/instances")
async def insert(aid: str, body: InsertIn, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    if (body.project_id is None) == (body.toolbox is None):
        raise HTTPException(422, "Insert either a project part or a Toolbox component.")

    async def fn(doc: dict[str, Any], root: Path) -> dict[str, Any]:
        if body.project_id:
            key = await _project_part(ctx, _project(ctx, body.project_id))
        else:
            assert body.toolbox is not None
            key = await service.ensure_toolbox_part(root, ctx.require_org().id, body.toolbox.code, body.toolbox.params)
        inst = service.add_instance(root, doc, key)
        return {"_extra": {"instance": inst["id"]}}

    view = await _mutate(ctx, aid, fn)
    track(ctx.db, "assembly_part_inserted", ctx.user, ctx.require_org().id,
          kind="project" if body.project_id else "toolbox")
    ctx.db.commit()
    return view


@router.patch("/assemblies/{aid}/instances/{iid}")
async def patch_instance(aid: str, iid: str, body: InstancePatch, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    def fn(doc: dict[str, Any], root: Path) -> None:
        inst = service._inst(doc, iid)
        if body.name is not None:
            inst["name"] = body.name.strip()
        if body.visible is not None:
            inst["visible"] = body.visible
        if body.fixed is not None:
            inst["fixed"] = body.fixed
        if body.translate is not None or body.rotate is not None or body.T is not None:
            service.move_instance(root, doc, iid, {"translate": body.translate, "T": body.T,
                                                   "rotate": body.rotate.model_dump() if body.rotate else None})

    geometric = body.fixed is not None or body.translate is not None or body.rotate is not None or body.T is not None
    return await _mutate(ctx, aid, fn, solve=geometric)


@router.delete("/assemblies/{aid}/instances/{iid}")
async def delete_instance(aid: str, iid: str, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    return await _mutate(ctx, aid, lambda doc, root: service.remove_instance(doc, iid))


async def _refresh_project(ctx: Ctx, doc: dict[str, Any], root: Path, project_id: str) -> dict[str, Any]:
    """Re-point every instance of a project at its latest verified build: mate references follow by role and
    topology (AMI-05), and every fastener stack is re-checked against the updated holes and grips (AMI-07)."""
    p = _project(ctx, project_id)
    key = await _project_part(ctx, p)
    new_part = store.part(root, key)
    counts = {"kept": 0, "followed": 0, "lost": 0}
    old_infos: dict[str, dict[str, Any]] = {}
    n = 0
    for i in doc["instances"]:
        if i["source"]["kind"] != "project" or i["source"]["project_id"] != project_id or i["part"] == key:
            continue
        old = i["part"]
        old_infos[i["id"]] = (store.part(root, old) or {}).get("info") or {}
        c = service.remap_refs(root, doc, i["id"], key, old)
        for k in counts:
            counts[k] += c[k]
        i["part"] = key
        i["source"] = service._source(new_part)  # type: ignore[arg-type]
        n += 1
    service.run_solve(root, doc)
    stacks = await service.recheck_stacks(root, ctx.require_org().id, doc, old_infos) if n else 0
    broken = [m["id"] for m in doc["mates"] if m.get("broken")]
    return {"refreshed": n, "references_kept": counts["kept"], "references_followed": counts["followed"],
            "references_lost": counts["lost"], "broken_mates": broken, "stacks_to_check": stacks}


@router.post("/assemblies/{aid}/instances/{iid}/refresh")
async def refresh(aid: str, iid: str, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    async def fn(doc: dict[str, Any], root: Path) -> dict[str, Any]:
        inst = service._inst(doc, iid)
        if inst["source"]["kind"] != "project":
            raise AssemblyInputError("Toolbox parts don't change.")
        return {"_extra": await _refresh_project(ctx, doc, root, inst["source"]["project_id"])}

    return await _mutate(ctx, aid, fn, solve=False)


@router.post("/warm")
async def warm(ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    """Start this workspace's geometry engine ahead of the first operation (AMI-08). Cheap when already warm."""
    import time

    t0 = time.perf_counter()
    try:
        await service._call(ctx.require_org().id, {"op": "ping"}, timeout=180)
    except service.WorkerError as e:
        raise _err(e) from e
    return {"ok": True, "s": round(time.perf_counter() - t0, 2)}


@router.get("/where-used/{project_id}")
def where_used(project_id: str, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    """Assemblies that use a project's part, with how many of its instances are behind the latest build and how
    many mates are broken (AMI-10)."""
    p = _project(ctx, project_id)
    current = str(_status(workspace_for(p)).get("build_id"))
    out = []
    for d in store.list_docs(_root(ctx)):
        if d.get("org_id") != ctx.require_org().id:
            continue
        mine = [i for i in d["instances"] if i["source"]["kind"] == "project" and i["source"]["project_id"] == p.id]
        if not mine:
            continue
        out.append({"id": d["id"], "name": d["name"], "instances": len(mine),
                    "stale": sum(1 for i in mine if current not in ("None",) and str(i["source"]["build_id"]) != current),
                    "broken_mates": sum(1 for m in d["mates"] if m.get("broken"))})
    return {"items": out}


@router.post("/assemblies/{aid}/mates")
async def add_mate(aid: str, body: MateIn, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    def fn(doc: dict[str, Any], root: Path) -> dict[str, Any]:
        m = service.make_mate(root, doc, body.model_dump())
        return {"_extra": {"mate": m["id"]}, "id": m["id"]}

    return await _mutate(ctx, aid, fn, prealign=lambda doc, r: [r["id"]])


@router.patch("/assemblies/{aid}/mates/{mid}")
async def patch_mate(aid: str, mid: str, body: MatePatch, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    def fn(doc: dict[str, Any], root: Path) -> dict[str, Any] | None:
        m = next((x for x in doc["mates"] if x["id"] == mid), None)
        if m is None:
            raise AssemblyInputError("Mate not found")
        geometric = service.edit_mate(root, doc, m, body.model_dump(exclude_none=True))
        return {"id": mid} if geometric else None

    return await _mutate(ctx, aid, fn, prealign=lambda doc, r: [r["id"]] if r else [])


@router.delete("/assemblies/{aid}/mates/{mid}")
async def delete_mate(aid: str, mid: str, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    def fn(doc: dict[str, Any], root: Path) -> None:
        if not any(m["id"] == mid for m in doc["mates"]):
            raise AssemblyInputError("Mate not found")
        doc["mates"] = [m for m in doc["mates"] if m["id"] != mid]

    return await _mutate(ctx, aid, fn)


@router.delete("/assemblies/{aid}/groups/{gid}")
async def delete_group(aid: str, gid: str, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    return await _mutate(ctx, aid, lambda doc, root: service.remove_group(doc, gid))


@router.post("/assemblies/{aid}/analyse")
async def analyse(aid: str, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    _editor(ctx)
    async with _lock(aid):
        doc = _doc(ctx, aid)
        try:
            res = await service.analyse(_root(ctx), ctx.require_org().id, doc)
        except (AssemblyInputError, service.WorkerError) as e:
            raise _err(e) from e
    track(ctx.db, "assembly_analysed", ctx.user, ctx.require_org().id, interferences=res["interference"]["count"])
    ctx.db.commit()
    return {"analysis": {**res, "stale": False}}


@router.get("/assemblies/{aid}/bom")
def get_bom(aid: str, format: Literal["json", "csv"] = "json", ctx: Ctx = Depends(asm_ctx)) -> Any:
    doc = _doc(ctx, aid)
    projects = _projects_for(ctx, doc)
    try:
        b = service.bom(_root(ctx), doc, {pid: p.name for pid, p in projects.items()})
    except AssemblyInputError as e:
        raise _err(e) from e
    if format == "csv":
        track(ctx.db, "download", ctx.user, ctx.require_org().id, file="assembly/bom.csv")
        ctx.db.commit()
        return Response(service.bom_csv(b), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{_safe(doc["name"])}_BOM.csv"'})
    return {"assembly": {"id": doc["id"], "name": doc["name"]}, **b}


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:60] or "assembly"


@router.post("/assemblies/{aid}/export")
async def export(aid: str, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    _editor(ctx)
    async with _lock(aid):
        doc = _doc(ctx, aid)
        try:
            res = await service.export_step(_root(ctx), ctx.require_org().id, doc)
        except (AssemblyInputError, service.WorkerError) as e:
            raise _err(e) from e
    audit(ctx.db, "assembly.exported", ctx.user, ctx.require_org().id, target=aid, instances=res["instances"])
    track(ctx.db, "assembly_exported", ctx.user, ctx.require_org().id, ok=res["ok"])
    ctx.db.commit()
    return {"export": {**res, "stale": False, "url": f"/api/m/assembly/assemblies/{aid}/files/assembly.step"}}


@router.get("/assemblies/{aid}/files/assembly.step")
def download(aid: str, ctx: Ctx = Depends(asm_ctx)) -> FileResponse:
    doc = _doc(ctx, aid)
    f = store.doc_dir(_root(ctx), aid) / "assembly.step"
    if not f.is_file():
        raise HTTPException(404, "Export the assembly first")
    track(ctx.db, "download", ctx.user, ctx.require_org().id, file="assembly/assembly.step")
    ctx.db.commit()
    return FileResponse(f, media_type="application/step",
                        headers={"Content-Disposition": f'attachment; filename="{_safe(doc["name"])}.step"',
                                 "Cache-Control": "no-store"})


@router.post("/assemblies/{aid}/fasteners/propose")
async def fit_propose(aid: str, body: FitIn, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    async with _lock(aid):
        doc = _doc(ctx, aid)
        root = _root(ctx)
        try:
            targets = _targets(root, doc, body)
            plan = await service.propose(root, ctx.require_org().id, doc, targets, body.style, body.washers, body.flip)
        except (AssemblyInputError, service.WorkerError) as e:
            raise _err(e) from e
    names = service.display_names(doc)
    for h in plan["holes"]:
        h["inst_name"] = names.get(h["inst"])
    return plan


@router.post("/assemblies/{aid}/fasteners/accept")
async def fit_accept(aid: str, body: FitIn, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    async def fn(doc: dict[str, Any], root: Path) -> dict[str, Any]:
        targets = _targets(root, doc, body)
        res = await service.accept(root, ctx.require_org().id, doc, targets, body.style, body.washers, body.flip)
        return {"_extra": {"inserted": res["inserted"], "clashes": res["clashes"]}}

    view = await _mutate(ctx, aid, fn, solve=False)
    audit(ctx.db, "assembly.fasteners_inserted", ctx.user, ctx.require_org().id, target=aid,
          stacks=(view.get("result") or {}).get("inserted"))
    track(ctx.db, "assembly_fasteners_inserted", ctx.user, ctx.require_org().id,
          stacks=(view.get("result") or {}).get("inserted"))
    ctx.db.commit()
    return view


@router.post("/assemblies/{aid}/fasteners/pairs")
async def fit_pairs(aid: str, body: PairIn, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    """"Fasten these two parts" (AMI-I2): every coaxial hole pair between two parts with its proposed stack, fitted
    from the smaller hole. A mismatched pair (Ø6.6 over Ø5.5) also carries the one-click part fix when one design
    parameter of the smaller hole's project sets that Ø."""
    async with _lock(aid):
        doc = _doc(ctx, aid)
        root = _root(ctx)
        try:
            pairs = service.coaxial_hole_pairs(root, doc, body.a, body.b)
            plan = await service.propose(root, ctx.require_org().id, doc, [p["target"] for p in pairs],
                                         body.style, body.washers, False) if pairs else {"holes": []}
        except (AssemblyInputError, service.WorkerError) as e:
            raise _err(e) from e
    names = service.display_names(doc)
    fixes: dict[str, Any] = {}
    for p, h in zip(pairs, plan["holes"], strict=True):
        p["proposal"] = h["proposal"]
        p["grip"] = h["probe"].get("grip")
        mm = p["mismatch"]
        if mm:
            k = f"{mm['inst']}:{mm['d']}:{mm['to_d']}"
            if k not in fixes:
                fixes[k] = _hole_param(ctx, doc, mm["inst"], float(mm["d"]), float(mm["to_d"]))
            mm["fix"] = fixes[k]
            mm["name"] = names.get(mm["inst"])
    return {"a": body.a, "b": body.b, "a_name": names.get(body.a), "b_name": names.get(body.b), "pairs": pairs,
            "ok": sum(1 for p in pairs if p["proposal"]["ok"])}


@router.post("/assemblies/{aid}/fix-hole")
async def fix_hole(aid: str, body: FixHoleIn, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    """One-click part fix: a deterministic parameter edit on the part's Design Studio project (no AI, no tokens;
    the Studio keeps it only if the rebuilt part passes its checks), then refresh of every instance of that part
    in this assembly with mate re-mapping and stack re-checks."""
    from aicad.platform.routers.projects import ParamsIn, set_params

    async def fn(doc: dict[str, Any], root: Path) -> dict[str, Any]:
        inst = service._inst(doc, body.inst)
        if inst["source"]["kind"] != "project":
            raise AssemblyInputError("Toolbox parts can't be edited here.")
        pid = inst["source"]["project_id"]
        res = await set_params(pid, ParamsIn(values={body.param: body.value}), ctx)
        out = await _refresh_project(ctx, doc, root, pid)
        return {"_extra": {**out, "param": body.param, "changed": res.get("changed"), "revision": res.get("revision")}}

    view = await _mutate(ctx, aid, fn, solve=False)
    audit(ctx.db, "assembly.part_fixed", ctx.user, ctx.require_org().id, target=aid, param=body.param)
    ctx.db.commit()
    return view


@router.post("/assemblies/{aid}/groups/{gid}/refit")
async def refit_group(aid: str, gid: str, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    """Replace a fastener stack with a fresh proposal for its hole ("Update stack" after a part change, AMI-07)."""
    async def fn(doc: dict[str, Any], root: Path) -> dict[str, Any]:
        g = next((x for x in doc["groups"] if x["id"] == gid and x.get("kind") == "fastener"), None)
        if g is None or not g.get("hole"):
            raise AssemblyInputError("Fastener stack not found")
        spec = g.get("spec") or {}
        target = {"inst": g["hole"]["inst"], "hole": int(g["hole"]["hole"])}
        service._inst(doc, target["inst"])
        plan = await service.propose(root, ctx.require_org().id, doc, [target], spec.get("style", "hex_bolt"),
                                     spec.get("washers", "both"), bool(spec.get("flip")))
        if not plan["holes"][0]["proposal"]["ok"]:
            raise AssemblyInputError(plan["holes"][0]["proposal"].get("error") or "No fastener fits this hole now.")
        service.remove_group(doc, gid)
        res = await service.accept(root, ctx.require_org().id, doc, [target], spec.get("style", "hex_bolt"),
                                   spec.get("washers", "both"), bool(spec.get("flip")))
        return {"_extra": {"inserted": res["inserted"], "clashes": res["clashes"],
                           "summary": plan["holes"][0]["proposal"]["summary"]}}

    return await _mutate(ctx, aid, fn, solve=False)


@router.post("/assemblies/{aid}/thumbnail")
async def put_thumbnail(aid: str, body: ThumbIn, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    """The workspace uploads an isometric snapshot of the assembly for the list (PNG, at most 1.4 MB)."""
    _editor(ctx)
    import base64
    import binascii

    try:
        data = base64.b64decode(body.png_b64.split(",", 1)[-1], validate=True)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(400, "Not a PNG image") from e
    if not data.startswith(PNG_MAGIC) or len(data) > 1_400_000:
        raise HTTPException(400, "Not a PNG image")
    async with _lock(aid):
        _doc(ctx, aid)
        d = store.doc_dir(_root(ctx), aid)
        tmp = d / "thumb.tmp"
        tmp.write_bytes(data)
        tmp.replace(d / "thumb.png")
        store.write_json(d / "thumb.json", {"rev": body.rev, "at": store.now()})
    return {"ok": True}


@router.get("/assemblies/{aid}/thumbnail")
def get_thumbnail(aid: str, ctx: Ctx = Depends(asm_ctx)) -> FileResponse:
    _doc(ctx, aid)
    f = store.doc_dir(_root(ctx), aid) / "thumb.png"
    if not f.is_file():
        raise HTTPException(404, "No thumbnail")
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/parts/{key}/topo")
def part_topo(key: str, ctx: Ctx = Depends(asm_ctx)) -> FileResponse:
    try:
        f = store.part_dir(_root(ctx), key) / "topo.json"
    except AssemblyInputError as e:
        raise HTTPException(404, "Part not found") from e
    if not f.is_file():
        raise HTTPException(404, "Part not found")
    return FileResponse(f, media_type="application/json", headers={"Cache-Control": "private, max-age=86400"})


# ----------------------------------------------------------------------------- smart assembly (ASM-010 / ASM-019)
class SmartPlanIn(BaseModel):
    text: str = Field(min_length=2, max_length=2000)
    ai: bool = False      # let Hex ask the AI about the lines it could not read (metered)


class SmartRunIn(BaseModel):
    items: list[dict[str, Any]] = Field(min_length=1, max_length=40)


def _part_candidates(ctx: Ctx) -> list[dict[str, Any]]:
    """The workspace's own parts Hex may reuse: projects with a verified build (shape signature when available)."""
    rows = permissions.visible(ctx.db, ctx.user, ctx.db.scalars(
        select(Project).where(Project.org_id == ctx.require_org().id, Project.archived.is_(False))
        .order_by(Project.updated_at.desc())).all())
    out = []
    for p in rows:
        ws = workspace_for(p)
        st = _status(ws)
        if not st.get("ok") or not (ws / "out" / "part.step").is_file():
            continue
        out.append({"id": p.id, "name": p.name, "description": p.description or "", "sig": similarity.signature(ws)})
    return out


@router.post("/assemblies/{aid}/smart/plan")
async def smart_plan(aid: str, body: SmartPlanIn, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    """Hex reads the description (Toolbox first, then your parts, zero tokens) and Fitz proposes where each item goes
    and in which order. Nothing is changed; the plan is shown for approval. With ``ai`` Hex asks the AI only about
    the lines it could not read; the tokens used are returned and charged like any other AI step."""
    _editor(ctx)
    doc = _doc(ctx, aid)
    root = _root(ctx)
    cands = _part_candidates(ctx)
    try:
        res = fitz.plan(root, doc, body.text, cands)
    except (AssemblyInputError, toolbox.ToolboxError) as e:
        raise _err(e) from e
    if not res["items"]:
        raise HTTPException(409, "Describe at least one component, e.g. “4 M6x25 bolts with washers and nuts”.")
    tokens = 0
    if body.ai and res["unresolved"]:
        from aicad.platform import metering
        from aicad.platform.routers.billing import tokens_for_cost

        org = ctx.require_org()
        unlimited = ctx.god_on("bypass_tokens")
        if not unlimited and org.token_balance <= 0:
            raise HTTPException(402, {"message": "Your workspace has no tokens left for an AI reading. Top up, or "
                                                 "edit the line so Hex can read it.", "cta": "/app/billing#tokens"})
        clauses = librarian.split(body.text)
        idx = [int(i[1:]) - 1 for i in res["unresolved"] if i[1:].isdigit()]
        idx = [k for k in idx if 0 <= k < len(clauses)]
        budget = None if unlimited else max(0, org.token_balance) * metering.USD_PER_TOKEN
        try:
            text, usd = await librarian.ask_ai([clauses[k] for k in idx],
                                               [service.clean_name(c["name"]) for c in cands], budget)
        except Exception as e:
            raise HTTPException(503, "The AI reading isn't available right now. Edit the line so Hex can read it, "
                                     "or design the part in the Studio.") from e
        tokens = tokens_for_cost(usd) if usd else 0
        got = librarian.read_ai(text, len(idx), cands)
        res = fitz.plan(root, doc, body.text, cands, ai={idx[j]: v for j, v in got.items()})
        if tokens and not unlimited:
            debit(ctx.db, org, tokens, "usage", "Assembly Studio · Hex AI reading", ctx.user, ref=aid)
        track(ctx.db, "assembly_smart_ai", ctx.user, org.id, tokens=tokens, lines=len(idx), read=len(got))
        ctx.db.commit()
        res["ai_lines"] = len(idx)
        res["ai_read"] = len(got)
    res["tokens"] = tokens
    names = service.display_names(doc)
    res["parts_in_assembly"] = [{"id": i["id"], "name": names[i["id"]]} for i in doc["instances"] if not i.get("group")]
    return res


_ACTIONS = set(fitz.ORDER)


def _clean_items(ctx: Ctx, doc: dict[str, Any], raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-validate an edited plan: Toolbox parameters through normalize, projects in this workspace, instances in
    this assembly. Anything else is a 409 with a plain message."""
    ids = {i["id"] for i in doc["instances"]}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in raw:
        iid = str(r.get("id") or "")[:12]
        if not iid or iid in seen:
            raise AssemblyInputError("Each plan item needs its own id.")
        seen.add(iid)
        action = r.get("action")
        source = r.get("source")
        if action not in _ACTIONS or source not in ("toolbox", "project", "new"):
            raise AssemblyInputError("Unknown plan item.")
        try:
            qty = int(r.get("qty") or 1)
            order = int(r.get("order") or 0)
        except (TypeError, ValueError):
            raise AssemblyInputError("Quantity must be a whole number.") from None
        if not 1 <= qty <= librarian.MAX_QTY:
            raise AssemblyInputError(f"Quantity must be between 1 and {librarian.MAX_QTY}.")
        it: dict[str, Any] = {"id": iid, "action": action, "source": source, "qty": qty,
                              "qty_explicit": bool(r.get("qty_explicit", True)), "enabled": bool(r.get("enabled", True)),
                              "order": order, "title": str(r.get("title") or "Component")[:200]}
        if source == "toolbox":
            code = r.get("code")
            if code not in toolbox.COMPONENTS:
                raise AssemblyInputError("Unknown Toolbox component.")
            it["code"] = code
            it["params"] = toolbox.normalize(code, r.get("params") or {})
            if action != "fasten":
                it["title"] = toolbox.spec(code).title(it["params"])
            else:
                f = r.get("fasten") or {}
                size = f.get("size")
                length = f.get("length")
                if size is not None and (not isinstance(size, int | float) or int(size) not in toolbox.METRIC):
                    raise AssemblyInputError("Unsupported thread size.")
                it["fasten"] = {"style": f.get("style") if f.get("style") in ("hex_bolt", "shcs") else "hex_bolt",
                                "washers": f.get("washers") if f.get("washers") in ("both", "head", "none") else "both",
                                "size": int(size) if size is not None else None,
                                "length": float(length) if isinstance(length, int | float) else None}
        elif source == "project":
            it["project_id"] = _project(ctx, str(r.get("project_id") or "")).id
        if r.get("inst"):
            if r["inst"] not in ids:
                raise AssemblyInputError("A part of this plan is no longer in the assembly. Plan again.")
            it["inst"] = r["inst"]
        t = r.get("target") or None
        if isinstance(t, dict) and t.get("inst") in ids:
            it["target"] = {"inst": t["inst"]}
        elif isinstance(t, dict) and isinstance(t.get("item"), str):
            it["target"] = {"item": t["item"][:12]}
        out.append(it)
    return out


@router.post("/assemblies/{aid}/smart/run")
async def smart_run(aid: str, body: SmartRunIn, ctx: Ctx = Depends(asm_ctx)) -> dict[str, Any]:
    """Fitz inserts the approved items in order, places and mates them, then runs the exact interference check."""
    org_id = ctx.require_org().id

    async def project_part(pid: str) -> str:
        return await _project_part(ctx, _project(ctx, pid))

    async def fn(doc: dict[str, Any], root: Path) -> dict[str, Any]:
        items = _clean_items(ctx, doc, body.items)
        return {"_extra": await fitz.execute(root, org_id, doc, items, project_part)}

    view = await _mutate(ctx, aid, fn, solve=False)
    r = view.get("result") or {}
    audit(ctx.db, "assembly.smart_assembled", ctx.user, org_id, target=aid, inserted=r.get("inserted"),
          stacks=r.get("fastener_stacks"))
    track(ctx.db, "assembly_smart_run", ctx.user, org_id, inserted=r.get("inserted"),
          clashes=len(r.get("clashes") or []))
    ctx.db.commit()
    return view
