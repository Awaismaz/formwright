"""Image & Drawing to CAD API (module ``image2cad``): upload a drawing, sketch or photo, review what was read,
answer what is missing, then create a model through the design agent.

Routes (all org-scoped; the module must be unlocked: plan / add-on ``addon_image2cad`` / God-mode bypass, else 402):
  GET    /api/m/image2cad/uploads                    the organisation's uploads, newest first
  POST   /api/m/image2cad/uploads                    {filename, data_b64}; reading starts in the background
  GET    /api/m/image2cad/uploads/{id}               meta + read + review + computed state (needs, readiness)
  POST   /api/m/image2cad/uploads/{id}/review        save edits and answers; returns the recomputed state
  POST   /api/m/image2cad/uploads/{id}/reread        read again (after a failure)
  POST   /api/m/image2cad/uploads/{id}/create        {project_id?, name?}: project + reference + agent hand-off
  POST   /api/m/image2cad/uploads/{id}/roundtrip     draw the built model and check the confirmed values on it
  GET    /api/m/image2cad/estimate                   measured token estimates for a read and a build + balance
  GET    /api/m/image2cad/uploads/{id}/preview.png   preview raster
  GET    /api/m/image2cad/uploads/{id}/source        the original file
  DELETE /api/m/image2cad/uploads/{id}
Viewers can open uploads and reviews; uploading, answering and creating need the engineer role.
Token-metered actions (an AI vision read, the model build) start only when the balance covers the upper measured
estimate (``aicad.image2cad.cost``); God mode's token bypass skips the check.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import logging
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from aicad.drawing import worker as dworker
from aicad.image2cad import InputError, cost, review, roundtrip, store, vision
from aicad.image2cad.extract import extract
from aicad.image2cad.sniff import MAX_PDF_BYTES, TYPES, validate
from aicad.platform import metering
from aicad.platform.config import get_settings
from aicad.platform.db import session_factory
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.models import AgentRun, Organization, Project, User
from aicad.platform.routers import projects as proj
from aicad.platform.routers.billing import tokens_for_cost
from aicad.platform.services import audit, debit, notify, org_modules, track

router = APIRouter(prefix="/api/m/image2cad", tags=["image2cad"])
log = logging.getLogger("aicad.image2cad")

CODE = "image2cad"
_tasks: set[asyncio.Task[None]] = set()
REVIEW_BODY = Body(...)


class UploadIn(BaseModel):
    filename: str = Field(max_length=200)
    data_b64: str


class CreateIn(BaseModel):
    project_id: str | None = None
    name: str | None = Field(default=None, max_length=120)


class _HandoffIn(proj.ChatIn):
    """The hand-off message: ``shown`` is what the Studio chat shows as the user's message (a short summary);
    the structured request with the modelling rules goes to the design agent only. Not accepted from clients."""
    shown: str


BUILD_PENDING_S = 2 * 3600  # stop waiting for a hand-off run's cost after this long


def _access(ctx: Ctx) -> None:
    org = ctx.require_org()
    if CODE not in org_modules(ctx.db, org) and not ctx.god_on("bypass_paywall"):
        raise HTTPException(402, {"message": "Image & Drawing to CAD isn't included in your plan. Unlock the add-on "
                                             "to turn drawings and sketches into models.", "cta": "/app/modules/image2cad"})


def _engineer(ctx: Ctx) -> None:
    if ctx.role == "viewer":
        raise HTTPException(403, "Viewers can open reviews but can't upload, answer or create models.")


def _dir(ctx: Ctx, uid: str) -> Path:
    _access(ctx)
    d = store.upload_dir(get_settings().data_dir, ctx.require_org().id, uid)
    if d is None:
        raise HTTPException(404, "Upload not found")
    return d


def _summary(d: Path, meta: dict[str, Any]) -> dict[str, Any]:
    out = {k: meta.get(k) for k in ("id", "name", "type", "bytes", "created_at", "status", "error", "project_id",
                                    "method", "pages", "step")}
    out["created_at"] = str(out.get("created_at") or "").removesuffix("+00:00")  # naive UTC, like other modules
    out["preview"] = f"/api/m/image2cad/uploads/{meta['id']}/preview.png" if (d / "preview.png").is_file() else None
    read = store.read_json(d, "read.json")
    if read and meta.get("status") in ("review", "created"):
        st = review.state(read, store.read_json(d, "review.json"))
        out["counts"] = {"dims": sum(1 for x in st["dims"] if not x["excluded"]), "open": st["open"]}
    rt = store.read_json(d, "roundtrip.json")
    out["roundtrip"] = {"matched": rt["matched"], "checked": rt["checked"]} if rt else None
    return out


def _full(d: Path, ctx: Ctx) -> dict[str, Any]:
    meta = store.read_json(d, "meta.json") or {}
    read = store.read_json(d, "read.json")
    rv = store.read_json(d, "review.json") or review.empty_review()
    project = None
    if meta.get("project_id"):
        p = ctx.db.get(Project, meta["project_id"])
        if p is not None and p.org_id == ctx.require_org().id:
            ls = p.last_status or {}
            project = {"id": p.id, "name": p.name, "built": bool(ls.get("ok")), "build_id": ls.get("build_id")}
    st = review.state(read, rv) if read else None
    if st is not None and not st.get("name"):
        st["name"] = review.suggested_name(read or {}, meta.get("name"))
    rt = store.read_json(d, "roundtrip.json")
    if rt and project:
        rt["stale"] = rt.get("project_id") != project["id"] or str(rt.get("build_id")) != str(project["build_id"])
    return {"upload": _summary(d, meta), "read": read, "review": rv, "state": st, "project": project,
            "can_edit": ctx.role != "viewer", "estimate": _estimate(ctx), "roundtrip": rt}


# ----------------------------------------------------------------------------- cost (AMI-03)
def _settle_builds(ctx: Ctx) -> None:
    """Record the real cost of finished hand-off runs (the first agent run after Create model) for the estimate."""
    data = get_settings().data_dir
    for d, meta in store.list_uploads(data, ctx.require_org().id):
        pend = meta.get("build_pending")
        if not isinstance(pend, dict):
            continue
        p = ctx.db.get(Project, pend.get("project_id"))
        run = ctx.db.get(AgentRun, pend["run_id"]) if pend.get("run_id") else None
        if run is not None:  # the platform's own record of this run (per-run cost, also kept under God mode)
            state = "pending" if run.status == "running" else "done" if run.status in ("ok", "failed") else "failed"
            usd = run.cost_usd
        else:
            state, usd = ("failed", None) if p is None else \
                cost.first_result_tokens(proj.workspace_for(p) / ".fw" / "chat.jsonl", int(pend.get("line") or 0))
        if state == "done":
            tokens = run.tokens if run is not None and run.tokens else (tokens_for_cost(usd) if usd else None)
            if tokens:
                cost.record(data, "build", tokens, ref=meta.get("id"))
            store.update_meta(d, build_pending=None, build_tokens=tokens)
        elif state == "failed" or time.time() - float(pend.get("at") or 0) > BUILD_PENDING_S:
            store.update_meta(d, build_pending=None)


def _estimate(ctx: Ctx) -> dict[str, Any]:
    """Token estimates for a read and a build, plus what the workspace can spend."""
    _settle_builds(ctx)
    org = ctx.require_org()
    unlimited = ctx.god_on("bypass_tokens")
    return {**cost.estimate(get_settings().data_dir), "balance": None if unlimited else org.token_balance,
            "unlimited": unlimited}


def _cover(ctx: Ctx, kind: str) -> None:
    """402 when the balance can't cover the upper estimate of this run (a run never starts on credit)."""
    if ctx.god_on("bypass_tokens"):
        return
    e = cost.estimate(get_settings().data_dir)[kind]
    bal = ctx.require_org().token_balance
    if bal < e["high"]:
        raise HTTPException(402, {"message": _short(kind, e, bal), "cta": "/app/billing#tokens"})


def _short(kind: str, e: dict[str, Any], bal: int) -> str:
    what = "Reading an image" if kind == "read" else "Building the model"
    about = f"about {e['tokens']}, up to {e['high']}" if e["high"] > e["tokens"] else f"about {e['tokens']}"
    return f"{what} takes {about} tokens. Your workspace has {max(bal, 0)}. Top up to continue."


# ----------------------------------------------------------------------------- background read
async def _read_task(d: Path, org_id: str, user_id: str, god_tokens: bool) -> None:
    try:
        res = await extract(d)
        if not res.get("ok"):
            store.update_meta(d, status="failed", error=res.get("error") or "The file could not be read.", step=None)
            return
        store.update_meta(d, pages=res.get("pages"), preview_px=res.get("preview"))
        if res.get("needs_vision"):
            store.update_meta(d, method="vision", step="Reading the image")
            db = session_factory()()
            try:
                org = db.get(Organization, org_id)
                if org is None:
                    return
                e = cost.estimate(get_settings().data_dir)["read"]
                # hard cap: the read stops before it could spend more than the workspace holds (AMI-03)
                budget = None if god_tokens else max(0, org.token_balance) * metering.USD_PER_TOKEN
                if not god_tokens and org.token_balance < e["high"]:  # scanned PDFs: known only after opening
                    store.update_meta(d, status="failed", step=None,
                                      error="This PDF is a scan, so AI vision has to read it. "
                                            + _short("read", e, org.token_balance))
                    return
            finally:
                db.close()
            try:
                read, usd = await vision.read_image(d, "preview.png", budget_usd=budget)
            except Exception:
                log.exception("vision read failed")
                store.update_meta(d, status="failed", step=None,
                                  error="The image reader stopped before finishing. Try again.")
                return
            _meter(org_id, user_id, god_tokens, usd, d)
            if read is None:
                store.update_meta(d, status="failed", step=None,
                                  error="No values could be read from this image. Try a sharper, straight-on image.")
                return
        else:
            read = res["read"]
            store.update_meta(d, method="vector")
        read["pages"] = res.get("pages") or 1
        read["preview_px"] = res.get("preview")
        store.write_json(d, "read.json", read)
        if store.read_json(d, "review.json") is None:
            store.write_json(d, "review.json", review.empty_review())
        store.update_meta(d, status="review", step=None, error=None)
        if res.get("needs_vision"):
            _notify_read(user_id, d)
    except Exception:
        log.exception("image2cad read failed")
        store.update_meta(d, status="failed", step=None, error="The file could not be read.")


def _notify_read(user_id: str, d: Path) -> None:
    """An image read takes a minute or two: tell the user when the values are ready to review."""
    db = session_factory()()
    try:
        meta = store.read_json(d, "meta.json") or {}
        notify(db, user_id, f"{meta.get('name', 'Your image')} is read",
               "The values are ready to review before modelling.", f"/app/modules/image2cad?upload={meta.get('id', '')}")
        db.commit()
    finally:
        db.close()


def _meter(org_id: str, user_id: str, god_tokens: bool, usd: float | None, d: Path) -> None:
    db = session_factory()()
    try:
        org, user = db.get(Organization, org_id), db.get(User, user_id)
        tokens = tokens_for_cost(usd)
        if usd:  # the real cost, also under God mode, so the estimate shown before a read stays measured
            cost.record(get_settings().data_dir, "read", tokens, ref=d.name)
        meta = store.read_json(d, "meta.json") or {}
        if org is not None and not god_tokens:
            debit(db, org, tokens, "usage", f"Image & Drawing to CAD · read {meta.get('name', 'image')}", user,
                  ref=meta.get("id"))
        store.update_meta(d, tokens_charged=0 if god_tokens else tokens)
        track(db, "image2cad_vision_read", user, org_id, tokens=tokens)
        db.commit()
    finally:
        db.close()


def _start(d: Path, ctx: Ctx) -> None:
    from aicad.platform import metering

    if (ctx.user.email_verified_at is None and not ctx.god_on("skip_verification") and not ctx.god_on("bypass_tokens")
            and metering.unverified_spent(ctx.db, ctx.user) >= metering.UNVERIFIED_TOKEN_CAP - metering.MIN_RUN_TOKENS):
        raise HTTPException(403, "Verify your email to keep using AI reads. We sent you a link.")
    t = asyncio.create_task(_read_task(d, ctx.require_org().id, ctx.user.id, ctx.god_on("bypass_tokens")))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


# ----------------------------------------------------------------------------- routes
@router.get("/uploads")
def list_uploads(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    _access(ctx)
    items = store.list_uploads(get_settings().data_dir, ctx.require_org().id)
    return {"items": [_summary(d, m) for d, m in items], "max_mb": MAX_PDF_BYTES // (1024 * 1024),
            "can_edit": ctx.role != "viewer", "estimate": _estimate(ctx)}


@router.get("/estimate")
def estimate(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    _access(ctx)
    return _estimate(ctx)


@router.post("/uploads")
async def upload(body: UploadIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    _access(ctx)
    _engineer(ctx)
    if len(body.data_b64) > MAX_PDF_BYTES * 4 // 3 + 8:
        raise HTTPException(413, f"The file is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB.")
    try:
        data = base64.b64decode(body.data_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "The upload is not valid base64.") from None
    try:
        if validate(data) != "pdf":  # images always go to AI vision: the balance must cover the read first
            _cover(ctx, "read")
        d, meta = store.create(get_settings().data_dir, ctx.require_org().id, ctx.user.id, body.filename, data)
    except InputError as e:
        raise HTTPException(413 if "larger" in str(e) else 415, str(e)) from None
    audit(ctx.db, "image2cad.uploaded", ctx.user, ctx.require_org().id, target=meta["id"], name=meta["name"],
          type=meta["type"])
    track(ctx.db, "image2cad_upload", ctx.user, ctx.require_org().id, type=meta["type"], bytes=meta["bytes"])
    ctx.db.commit()
    _start(d, ctx)
    return {"upload": _summary(d, meta)}


@router.get("/uploads/{uid}")
def get_upload(uid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    return _full(_dir(ctx, uid), ctx)


@router.post("/uploads/{uid}/review")
def save_review(uid: str, body: dict[str, Any] = REVIEW_BODY, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    d = _dir(ctx, uid)
    _engineer(ctx)
    read = store.read_json(d, "read.json")
    if read is None:
        raise HTTPException(409, "This upload hasn't been read yet.")
    try:
        rv = review.clean_review(body, read)
    except InputError as e:
        raise HTTPException(422, str(e)) from None
    store.write_json(d, "review.json", rv)
    return _full(d, ctx)


@router.post("/uploads/{uid}/reread")
def reread(uid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    d = _dir(ctx, uid)
    _engineer(ctx)
    meta = store.read_json(d, "meta.json") or {}
    if meta.get("status") == "reading":
        raise HTTPException(409, "This file is still being read.")
    if meta.get("type") != "pdf":
        _cover(ctx, "read")
    store.update_meta(d, status="reading", error=None)
    _start(d, ctx)
    return _full(d, ctx)


def _attachment(d: Path) -> proj.Attachment:
    raw = (d / "preview.png").read_bytes()
    if len(raw) <= 5 * 1024 * 1024:
        return proj.Attachment(name="drawing.png", mime="image/png", data_b64=base64.b64encode(raw).decode())
    from PIL import Image

    with Image.open(d / "preview.png") as im:  # our own raster: re-encode as JPEG to stay under the chat limit
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=88)
    return proj.Attachment(name="drawing.jpg", mime="image/jpeg", data_b64=base64.b64encode(buf.getvalue()).decode())


@router.post("/uploads/{uid}/create")
async def create_model(uid: str, body: CreateIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    d = _dir(ctx, uid)
    _engineer(ctx)
    meta = store.read_json(d, "meta.json") or {}
    read = store.read_json(d, "read.json")
    if read is None or meta.get("status") not in ("review", "created"):
        raise HTTPException(409, "This upload hasn't been read yet.")
    rv = store.read_json(d, "review.json") or review.empty_review()
    st = review.state(read, rv)
    try:
        prompt = review.handoff_prompt(meta, read, st, rv)
    except InputError as e:
        raise HTTPException(409, str(e)) from None
    allowed, reason, cta = proj.can_run_agent(ctx)
    if not allowed:
        raise HTTPException(402, {"message": reason, "cta": cta})
    _cover(ctx, "build")
    if body.project_id:
        p = proj._project(ctx, body.project_id)
        s = proj._sessions.get(p.id)
        if s is not None and s.busy:
            raise HTTPException(409, "The design agent is busy on that project. Try again when it has finished.")
    else:
        name = (body.name or "").strip() or review.suggested_name(read, meta.get("name")) or "Drawing"
        no = st.get("drawing_no")
        made = proj.create_project(proj.ProjectIn(
            name=name[:120], description=f"From {meta.get('name')} (Image & Drawing to CAD)"
                                         + (f" · drawing no. {no}" if no else "")), ctx)
        p = ctx.db.get(Project, made["id"])
    assert p is not None
    ws = proj.workspace_for(p)
    out = ws / CODE
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(d / meta["file"], out / f"source{Path(meta['file']).suffix}")
    store.write_json(out, "spec.json", {
        "upload_id": uid, "source": meta.get("name"), "method": read.get("method"),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"), "created_by": ctx.user.id,
        "reference": st["scale"]["reference"], "scale": st["scale"], "assumptions": st["assumptions"],
        "dims": [{k: x.get(k) for k in ("id", "label", "kind", "value", "view", "describes", "source", "edited",
                                        "confirmed")} for x in st["dims"] if not x["excluded"]],
        "prompt": prompt})
    chat = ws / ".fw" / "chat.jsonl"
    try:
        line = len(chat.read_text(encoding="utf-8").splitlines()) if chat.is_file() else 0
    except OSError:
        line = 0
    await proj.agent_chat(p.id, _HandoffIn(prompt=prompt, attachments=[_attachment(d)],
                                           shown=review.handoff_summary(meta, st, rv)), ctx)
    from sqlalchemy import select

    run_id = ctx.db.scalar(select(AgentRun.id).where(AgentRun.project_id == p.id).order_by(AgentRun.created_at.desc()))
    store.update_meta(d, status="created", project_id=p.id,
                      build_pending={"project_id": p.id, "line": line, "at": time.time(), "run_id": run_id})
    store.write_json(d, "handoff.json", {"project_id": p.id, "unit": (st["scale"]["reference"] or {}).get("unit"),
                                         "dims": [{k: x.get(k) for k in ("id", "label", "describes")}
                                                  for x in st["dims"] if not x["excluded"]]})
    (d / "roundtrip.json").unlink(missing_ok=True)  # a new model: an earlier drawing check no longer applies
    audit(ctx.db, "image2cad.model_requested", ctx.user, p.org_id, target=p.id, upload=uid,
          dims=sum(1 for x in st["dims"] if not x["excluded"]))
    track(ctx.db, "image2cad_create", ctx.user, p.org_id, method=read.get("method") or "")
    ctx.db.commit()
    return {"project_id": p.id}


@router.post("/uploads/{uid}/roundtrip")
async def roundtrip_check(uid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """AMI-I1: draw the model built from this upload (Drawing Studio, exact) and look for every confirmed value."""
    d = _dir(ctx, uid)
    _engineer(ctx)
    meta = store.read_json(d, "meta.json") or {}
    handoff = store.read_json(d, "handoff.json")
    if meta.get("status") != "created" or not meta.get("project_id") or not handoff:
        raise HTTPException(409, "Create the model first, then check it against the drawing.")
    p = ctx.db.get(Project, meta["project_id"])
    if p is None or p.org_id != ctx.require_org().id:
        raise HTTPException(409, "The project this model was built in no longer exists.")
    ws = proj.workspace_for(p)
    await proj.wait_finalized(p.id)
    st = store.read_json(ws / "out", "status.json") or {}
    if not st.get("ok") or not (ws / "out" / "part.step").is_file():
        raise HTTPException(409, "The model isn't built yet. Run the check once the design agent has a verified build.")
    res = await dworker.generate(p.org_id, ws / "out", ws / CODE / "roundtrip", {},
                                 {"title": p.name, "drawing_no": "", "drawn_by": "", "date": "", "model_rev": None})
    if not res.get("ok"):
        raise HTTPException(409 if res.get("user_error") else 500,
                            res.get("error") if res.get("user_error") else "The model's drawing could not be generated.")
    out = roundtrip.compare(handoff.get("dims") or [], roundtrip.sheet_values(res["result"]), handoff.get("unit") or "mm")
    out.update(project_id=p.id, build_id=st.get("build_id"),
               at=datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"))
    store.write_json(d, "roundtrip.json", out)
    track(ctx.db, "image2cad_roundtrip", ctx.user, p.org_id, matched=out["matched"], checked=out["checked"])
    ctx.db.commit()
    return _full(d, ctx)


@router.get("/uploads/{uid}/preview.png")
def preview(uid: str, ctx: Ctx = Depends(verified_ctx)) -> FileResponse:
    f = _dir(ctx, uid) / "preview.png"
    if not f.is_file():
        raise HTTPException(404, "No preview yet")
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/uploads/{uid}/source")
def source(uid: str, ctx: Ctx = Depends(verified_ctx)) -> FileResponse:
    d = _dir(ctx, uid)
    meta = store.read_json(d, "meta.json") or {}
    return FileResponse(d / meta["file"], media_type=TYPES[meta["type"]], filename=meta.get("name") or meta["file"])


@router.delete("/uploads/{uid}")
def delete_upload(uid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    d = _dir(ctx, uid)
    _engineer(ctx)
    meta = store.read_json(d, "meta.json") or {}
    if meta.get("status") == "reading":
        raise HTTPException(409, "This file is still being read.")
    shutil.rmtree(d, ignore_errors=True)
    audit(ctx.db, "image2cad.deleted", ctx.user, ctx.require_org().id, target=uid)
    ctx.db.commit()
    return {"ok": True}
