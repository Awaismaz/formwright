"""Library: Toolbox components (deterministic generators), STEP import and feature recognition."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from aicad import toolbox
from aicad.platform.db import utcnow
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.models import Project
from aicad.platform.routers.projects import (
    _project,
    _rebuild,
    _sessions,
    _snapshot,
    _status_summary,
    schedule_finalize,
    wait_finalized,
    workspace_for,
)
from aicad.platform.services import audit, track

router = APIRouter(prefix="/api", tags=["library"])

MAX_STEP_BYTES = 50 * 1024 * 1024


class InsertIn(BaseModel):
    code: str
    params: dict[str, float] = {}


class MatchIn(BaseModel):
    prompt: str


class StepIn(BaseModel):
    filename: str
    data_b64: str


class RebuildIn(BaseModel):
    mode: str = "draft"  # "draft" (deterministic, no AI) | "prompt" (returns the agent prompt)


@router.get("/toolbox")
def toolbox_catalog(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    return {"items": toolbox.catalog(), "version": toolbox.VERSION}


@router.post("/toolbox/match")
def toolbox_match(body: MatchIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    return {"matches": toolbox.match(body.prompt[:4000])}


async def install_model(p: Project, ctx: Ctx, source: str, strict: bool, note: str) -> dict[str, Any]:
    """Replace model.py with generated source and rebuild (no AI). The previous model stays in the revision
    history. strict=True rolls back unless all gating checks pass; imports only need to build."""
    if ctx.role == "viewer":
        raise HTTPException(403)
    s = _sessions.get(p.id)
    if s and s.busy:
        raise HTTPException(409, "The design agent is working on this project — wait for it to finish")
    ws = workspace_for(p)
    ws.mkdir(parents=True, exist_ok=True)
    await wait_finalized(p.id)
    f = ws / "model.py"
    old = f.read_text(encoding="utf-8") if f.is_file() else None
    backup = ws / ".out_backup"
    shutil.rmtree(backup, ignore_errors=True)
    if (ws / "out").is_dir():
        shutil.copytree(ws / "out", backup)
    f.write_text(source, encoding="utf-8")
    st = await _rebuild(p, ws, determinism=False, fast=True)
    failed = st.get("error") or (strict and not st.get("ok"))
    if failed:
        if old is None:
            f.unlink(missing_ok=True)
        else:
            f.write_text(old, encoding="utf-8")
        shutil.rmtree(ws / "out", ignore_errors=True)
        if backup.is_dir():
            backup.rename(ws / "out")
        reason = st.get("error") or ", ".join(c["id"] for c in st.get("checks", []) if c["gating"] and not c["passed"])
        raise HTTPException(422, f"The model could not be built ({reason}). Nothing was changed.")
    shutil.rmtree(backup, ignore_errors=True)
    p.last_status = _status_summary(st)
    p.builds += 1
    p.updated_at = utcnow()
    rev = _snapshot(p, ws)
    schedule_finalize(p, ws, rev)
    if s:
        s.publish({"type": "text", "text": f"{note} (revision {rev}, no AI used)."})
    return {"ok": True, "status_ok": st.get("ok"), "revision": rev, "build_s": st.get("timings_s", {}).get("total_s"),
            "checks": st.get("checks", [])}


@router.post("/projects/{project_id}/toolbox")
async def insert_toolbox(project_id: str, body: InsertIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    try:
        src = toolbox.model_source(body.code, body.params)
        title = toolbox.spec(body.code).title(toolbox.normalize(body.code, body.params))
    except toolbox.ToolboxError as e:
        raise HTTPException(422, str(e)) from None
    res = await install_model(p, ctx, src, strict=True, note=f"Created **{title}** from the Toolbox")
    audit(ctx.db, "project.toolbox_inserted", ctx.user, p.org_id, target=p.id, code=body.code)
    track(ctx.db, "toolbox_used", ctx.user, p.org_id, code=body.code)
    ctx.db.commit()
    return {**res, "title": title}


def _safe_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(name).stem)[:60].strip("_") or "part"
    return stem


@router.post("/projects/{project_id}/import-step")
async def import_step(project_id: str, body: StepIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    try:
        data = base64.b64decode(body.data_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "File data is not valid base64") from None
    if len(data) > MAX_STEP_BYTES:
        raise HTTPException(413, "STEP files up to 50 MB are supported")
    if not data.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"ISO-10303-21"):
        raise HTTPException(415, "That doesn't look like a STEP file (ISO-10303-21 header missing)")
    ws = workspace_for(p)
    imp = ws / "imports"
    imp.mkdir(parents=True, exist_ok=True)
    rel = f"imports/{_safe_name(body.filename)}_{hashlib.sha256(data).hexdigest()[:8]}.step"
    (ws / rel).write_bytes(data)
    name = Path(body.filename).stem[:80] or "Imported part"
    src = (f'"""Imported STEP: {Path(body.filename).name} (no feature history).\n\n'
           "Edit it with manual features (Features tab), ask the design agent to modify it, or use\n"
           '"Rebuild as parametric" to turn the recognised features into an editable model.\n"""\n'
           "from aicad import fw\n\n"
           f"NAME = {name!r}\nMATERIAL = \"unspecified\"\nIMPORTED = True\nREFERENCE_STEP = {rel!r}\n\n"
           'result = fw.feature("Imported body", fw.import_reference(REFERENCE_STEP))\n\nPARAMS = {}\n')
    try:
        res = await install_model(p, ctx, src, strict=False, note=f"Imported **{Path(body.filename).name}**")
    except HTTPException:
        (ws / rel).unlink(missing_ok=True)
        raise
    rec_p = ws / "out" / "recognition.json"
    rec = json.loads(rec_p.read_text(encoding="utf-8")) if rec_p.is_file() else {}
    if rec_p.is_file():
        shutil.copy2(rec_p, imp / "recognition.json")
    audit(ctx.db, "project.step_imported", ctx.user, p.org_id, target=p.id, bytes=len(data))
    track(ctx.db, "step_imported", ctx.user, p.org_id, bytes=len(data))
    ctx.db.commit()
    return {**res, "recognition": rec}


def _recognition(p: Project) -> dict[str, Any]:
    ws = workspace_for(p)
    for f in (ws / "imports" / "recognition.json", ws / "out" / "recognition.json"):
        if f.is_file():
            return json.loads(f.read_text(encoding="utf-8"))
    raise HTTPException(404, "No imported STEP in this project")


@router.get("/projects/{project_id}/recognition")
def get_recognition(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    return _recognition(_project(ctx, project_id))


@router.post("/projects/{project_id}/recognition/rebuild")
async def rebuild_parametric(project_id: str, body: RebuildIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    from aicad.recognize import agent_prompt, draft_model

    p = _project(ctx, project_id)
    rec = _recognition(p)
    if rec.get("error"):
        raise HTTPException(422, f"Feature recognition failed on this file: {rec['error']}")
    if body.mode == "prompt":
        return {"prompt": agent_prompt(rec)}
    src = draft_model(rec, p.name, rec.get("reference") or "")
    cur = workspace_for(p) / "model.py"
    if cur.is_file():  # keep the user's manual features (same coordinate frame as the original)
        from aicad.agent.runner import MANUAL_START

        old = cur.read_text(encoding="utf-8")
        if MANUAL_START in old:
            src = src.rstrip() + "\n\n\n" + old[old.index(MANUAL_START):]
    res = await install_model(p, ctx, src, strict=False, note="Rebuilt the import as a parametric draft from recognised features")
    audit(ctx.db, "project.recognition_rebuild", ctx.user, p.org_id, target=p.id)
    ctx.db.commit()
    return res
