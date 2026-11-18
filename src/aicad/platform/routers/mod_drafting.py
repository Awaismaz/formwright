"""Drawing Studio · 2D drafting without a model (DRW-017). Part of the ``drawings`` module (same entitlement).

Routes (all org-scoped; 402 when the module is locked; viewers can open and download but not change):
  GET    /api/m/drawings/drafts                        the organisation's 2D drawings
  POST   /api/m/drawings/drafts                        new 2D drawing (sheet, title; optional template + params)
  GET    /api/m/drawings/drafts/templates              deterministic templates (gasket, washer, plate with holes)
  POST   /api/m/drawings/drafts/templates/{name}       a template's entities and dimensions, for the editor to insert
  POST   /api/m/drawings/drafts/frame                  sheet frame, title block, revision table and notes primitives
  GET    /api/m/drawings/drafts/{id}                   the drawing (latest revision), its revisions and sheet check
  PUT    /api/m/drawings/drafts/{id}                   save the document as the next revision (409 on a stale base)
  DELETE /api/m/drawings/drafts/{id}
  GET    /api/m/drawings/drafts/{id}/revisions/{rev}   the document as saved in a revision
  POST   /api/m/drawings/drafts/{id}/assist            plain request -> entities + dimensions (template first, AI after)
  GET    /api/m/drawings/drafts/{id}/files/{name}      sheet.svg | sheet.pdf | sheet.dxf (?rev=, ?download=1)

The document is never linked to a model, so no model-consistency check (CHK-12) runs on it; the API says so.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from aicad.drawing import DrawingInputError, draft, draft_assist, draft_store
from aicad.drawing import draft_templates as T
from aicad.platform.config import get_settings
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.routers.mod_drawings import _access, local_date
from aicad.platform.services import audit, debit, track

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/m/drawings/drafts", tags=["drawings"])
FILES = {"sheet.svg": "image/svg+xml", "sheet.pdf": "application/pdf", "sheet.dxf": "application/dxf"}
_alocks: dict[str, asyncio.Lock] = {}


def _ctx(ctx: Ctx = Depends(verified_ctx)) -> Ctx:
    _access(ctx)
    return ctx


def _editor(ctx: Ctx) -> None:
    if ctx.role == "viewer":
        raise HTTPException(403, "Viewers can open 2D drawings but can't change them.")


def _root(ctx: Ctx) -> Path:
    return draft_store.org_root(get_settings().data_dir, ctx.require_org().id)


def _rec(ctx: Ctx, did: str) -> dict[str, Any]:
    try:
        rec = draft_store.load(_root(ctx), did)
    except DrawingInputError:
        rec = None
    if rec is None or rec.get("org_id") != ctx.require_org().id:
        raise HTTPException(404, "Drawing not found")
    return rec


def _bad(e: DrawingInputError) -> HTTPException:
    return HTTPException(422, str(e))


def _lock(did: str) -> asyncio.Lock:
    lk = _alocks.get(did)
    if lk is None:
        lk = _alocks[did] = asyncio.Lock()
    return lk


def _item(rec: dict[str, Any]) -> dict[str, Any]:
    return {"id": rec["id"], "name": rec["name"], "rev": rec["rev"], "updated_at": rec["updated_at"],
            "created_at": rec["created_at"], "summary": draft.summary(rec["doc"])}


def _state(ctx: Ctx, rec: dict[str, Any]) -> dict[str, Any]:
    doc = rec["doc"]
    return {**_item(rec), "doc": doc, "revs": rec.get("revs", []), "can_edit": ctx.role != "viewer",
            "check": draft.sheet_check(doc), "dimensions": draft.dimension_report(doc), "linked_model": None}


class SheetIn(BaseModel):
    size: str = "A3"
    orientation: str = "landscape"
    scale: list[int] = [1, 1]
    projection: str = "first"
    units: str = "mm"
    origin: list[float] | None = None


class CreateIn(BaseModel):
    name: str = ""
    sheet: SheetIn = SheetIn()
    title: dict[str, str] = {}
    template: str | None = None
    params: dict[str, Any] = {}
    auto_scale: bool = True
    local_date: str | None = None
    tz: str | None = None


class SaveIn(BaseModel):
    doc: dict[str, Any]
    name: str | None = None
    note: str = ""
    base_rev: int | None = None


class FrameIn(BaseModel):
    sheet: SheetIn = SheetIn()
    title: dict[str, str] = {}
    revisions: list[dict[str, Any]] = []
    notes: list[str] = []


class TemplateIn(BaseModel):
    params: dict[str, Any] = {}
    scale: list[int] = [1, 1]
    units: str = "mm"
    prefix: str = "t"


class AssistIn(BaseModel):
    prompt: str
    prefix: str = "a"


@router.get("")
def list_drafts(ctx: Ctx = Depends(_ctx)) -> dict[str, Any]:
    return {"items": [_item(r) for r in draft_store.list_drafts(_root(ctx)) if r.get("org_id") == ctx.require_org().id]}


@router.get("/templates")
def templates(ctx: Ctx = Depends(_ctx)) -> dict[str, Any]:
    return {"items": [{"name": n, "label": t["label"],
                       "params": [{"key": k, "label": v[0], "default": v[1], "integer": isinstance(v[1], int)}
                                  for k, v in t["params"].items()]} for n, t in T.TEMPLATES.items()],
            "sheets": list(draft.SHEETS), "scales": [f"{n}:{d}" for n, d in draft.SCALES],
            "layers": [{"key": k, "iso": v[0], "label": v[1], "width": v[2]} for k, v in draft.ISO128.items()]}


def _k(scale: list[int], units: str) -> float:
    return draft.UNITS.get(units, 1.0) * scale[0] / scale[1]


@router.post("/templates/{name}")
def template_fragment(name: str, body: TemplateIn, ctx: Ctx = Depends(_ctx)) -> dict[str, Any]:
    if name not in T.TEMPLATES:
        raise HTTPException(404, "Unknown template")
    try:
        sh = draft.normalize_sheet({"scale": body.scale, "units": body.units})
        return T.generate(name, body.params, _k(sh["scale"], sh["units"]), body.prefix)
    except DrawingInputError as e:
        raise _bad(e) from None


@router.post("/frame")
def frame(body: FrameIn, ctx: Ctx = Depends(_ctx)) -> dict[str, Any]:
    try:
        doc = draft.normalize_doc({"sheet": body.sheet.model_dump(), "title": body.title, "revisions": body.revisions,
                                   "notes": body.notes})
    except DrawingInputError as e:
        raise _bad(e) from None
    prims, info = draft.frame_prims(doc)
    return {"prims": prims, "w": info["w"], "h": info["h"], "frame": info["frame"], "blocked": info["blocked"],
            "origin": doc["sheet"]["origin"]}


@router.post("")
def create(body: CreateIn, ctx: Ctx = Depends(_ctx)) -> dict[str, Any]:
    _editor(ctx)
    name = " ".join(body.name.split())[:80] or "Untitled 2D drawing"
    did = draft_store.new_id()
    title = {"title": name, "drawing_no": f"FW-D{did[:7].upper()}", "drawn_by": ctx.user.name or ctx.user.email,
             "date": local_date(body.local_date, body.tz),
             **{k: v for k, v in body.title.items() if v}}
    try:
        sheet = body.sheet.model_dump()
        frag: dict[str, Any] = {}
        if body.template:
            if body.template not in T.TEMPLATES:
                raise HTTPException(404, "Unknown template")
            if body.auto_scale:
                probe = T.generate(body.template, body.params, 1.0, "t")
                w, h = draft.sheet_wh(draft.normalize_sheet(sheet))
                sheet["scale"] = T.fit_scale(probe["extent"], w, h, draft.UNITS.get(sheet["units"], 1.0))
            sh = draft.normalize_sheet(sheet)
            frag = T.generate(body.template, body.params, _k(sh["scale"], sh["units"]), "t")
        doc = draft.normalize_doc({"sheet": sheet, "title": title, "geom": frag.get("geom", {}),
                                   "dims": frag.get("dims", []), "annos": frag.get("annos", [])})
    except DrawingInputError as e:
        raise _bad(e) from None
    rec = draft_store.create(_root(ctx), ctx.require_org().id, ctx.user.name or ctx.user.email, name, doc, did)
    audit(ctx.db, "draft.created", ctx.user, ctx.require_org().id, target=rec["id"], template=body.template)
    track(ctx.db, "draft_created", ctx.user, ctx.require_org().id, template=body.template or "blank",
          sheet=doc["sheet"]["size"])
    ctx.db.commit()
    return _state(ctx, rec)


@router.get("/{did}")
def get_draft(did: str, ctx: Ctx = Depends(_ctx)) -> dict[str, Any]:
    return _state(ctx, _rec(ctx, did))


@router.put("/{did}")
@router.post("/{did}")
async def save(did: str, body: SaveIn, ctx: Ctx = Depends(_ctx)) -> dict[str, Any]:
    _editor(ctx)
    async with _lock(did):
        rec = _rec(ctx, did)
        if body.base_rev is not None and body.base_rev != rec["rev"]:
            raise HTTPException(409, f"This drawing was saved elsewhere (now revision {rec['rev']}). Reload it to "
                                     "continue; your changes are still in the editor.")
        try:
            doc = draft.normalize_doc(body.doc)
        except DrawingInputError as e:
            raise _bad(e) from None
        if body.name is not None and body.name.strip():
            rec["name"] = " ".join(body.name.split())[:80]
        rec = draft_store.save(_root(ctx), rec, doc, ctx.user.name or ctx.user.email, " ".join(body.note.split()))
    audit(ctx.db, "draft.saved", ctx.user, ctx.require_org().id, target=did, rev=rec["rev"])
    ctx.db.commit()
    return _state(ctx, rec)


@router.delete("/{did}")
def delete(did: str, ctx: Ctx = Depends(_ctx)) -> dict[str, Any]:
    _editor(ctx)
    _rec(ctx, did)
    draft_store.delete(_root(ctx), did)
    audit(ctx.db, "draft.deleted", ctx.user, ctx.require_org().id, target=did)
    ctx.db.commit()
    return {"ok": True}


@router.get("/{did}/revisions/{rev}")
def get_revision(did: str, rev: int, ctx: Ctx = Depends(_ctx)) -> dict[str, Any]:
    _rec(ctx, did)
    doc = draft_store.load_rev(_root(ctx), did, rev)
    if doc is None:
        raise HTTPException(404, "Revision not found")
    return {"rev": rev, "doc": doc}


@router.post("/{did}/assist")
async def assist(did: str, body: AssistIn, ctx: Ctx = Depends(_ctx)) -> dict[str, Any]:
    """Entities and dimensions for a plain request, placed for the user to edit (not saved)."""
    _editor(ctx)
    rec = _rec(ctx, did)
    sh = rec["doc"]["sheet"]
    k = _k(sh["scale"], sh["units"])
    request = " ".join(body.prompt.split())[:400]
    if not request:
        raise HTTPException(422, "Describe the part to draw")
    try:
        frag = draft_assist.deterministic(request, k, body.prefix)
    except DrawingInputError as e:
        raise _bad(e) from None
    if frag is not None:
        track(ctx.db, "draft_assist", ctx.user, ctx.require_org().id, source="template")
        ctx.db.commit()
        return {"source": "template", "fragment": frag, "missing": [],
                "message": f"Drawn from the {T.TEMPLATES[frag['template']]['label'].lower()} template. "
                           "Check every size before you save."}
    from aicad.platform import metering
    from aicad.platform.routers import projects as proj
    from aicad.platform.routers.billing import tokens_for_cost

    allowed, reason, cta = proj.can_run_agent(ctx)
    if not allowed:
        raise HTTPException(402, {"message": reason, "cta": cta})
    org = ctx.require_org()
    god_tokens = ctx.god_on("bypass_tokens")
    budget = None if god_tokens else max(0, org.token_balance) * metering.USD_PER_TOKEN
    try:
        text, usd = await draft_assist.run_agent(request, budget)
    except Exception:
        log.exception("draft assist failed")
        raise HTTPException(502, "The drafting assistant stopped before finishing. Try again, or start from a "
                                 "template.") from None
    tokens = tokens_for_cost(usd) if usd else 0
    if tokens and not god_tokens:
        debit(ctx.db, org, tokens, "usage", "Drawing Studio · 2D drafting assist", ctx.user, ref=did)
    track(ctx.db, "draft_assist", ctx.user, org.id, source="ai", tokens=tokens)
    ctx.db.commit()
    answer = draft_assist.parse_block(text)
    if answer is None:
        raise HTTPException(422, "The request could not be turned into a drawing. Try a gasket, washer or plate, or "
                                 "describe the shapes with their sizes.")
    try:
        frag = draft_assist.interpret(answer, k, body.prefix)
    except DrawingInputError as e:
        raise _bad(e) from None
    return {"source": "ai", "fragment": frag, "missing": frag.get("missing", []), "tokens": 0 if god_tokens else tokens,
            "message": "Drafted by the assistant from your request. Every size is shown as a dimension measured from "
                       "the geometry: check them before you save."}


def _render(doc: dict[str, Any], dest: Path, title: str) -> None:
    from aicad.drawing.draft_dxf import to_dxf
    from aicad.drawing.render import to_pdf, to_svg

    dest.mkdir(parents=True, exist_ok=True)
    sheet = draft.compose(doc)
    (dest / "sheet.svg").write_text(to_svg(sheet, title), encoding="utf-8")
    to_pdf(sheet, dest / "sheet.pdf", title)
    to_dxf(doc, dest / "sheet.dxf")


@router.get("/{did}/files/{name}")
async def draft_file(did: str, name: str, rev: int | None = None, download: bool = False,
                     ctx: Ctx = Depends(_ctx)) -> FileResponse:
    rec = _rec(ctx, did)
    if name not in FILES:
        raise HTTPException(404)
    r = rec["rev"] if rev is None else rev
    doc = rec["doc"] if r == rec["rev"] else draft_store.load_rev(_root(ctx), did, r)
    if doc is None:
        raise HTTPException(404, "Revision not found")
    dest = draft_store.export_dir(_root(ctx), did, r)
    async with _lock(did):
        if not (dest / name).is_file():
            await asyncio.to_thread(_render, doc, dest, rec["name"])
    headers = {"Cache-Control": "no-store"}
    if download or name != "sheet.svg":
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in rec["name"])[:60] or "drawing"
        headers["Content-Disposition"] = f'attachment; filename="{safe}_rev{r}{Path(name).suffix}"'
        track(ctx.db, "download", ctx.user, ctx.require_org().id, file=f"draft/{name}")
        ctx.db.commit()
    return FileResponse(dest / name, media_type=FILES[name], headers=headers)
