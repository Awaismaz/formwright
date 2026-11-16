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
from aicad.agent import worker
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
from aicad.platform.services import audit, notify_revision, track

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
    rev = _snapshot(p, ws, cause=note.replace("**", ""), kind="library", by=ctx.user.name)
    notify_revision(ctx.db, p, rev, ctx.user, note.replace("**", ""))
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
    """Import a STEP as an exact solid ("Imported blank") and recognise its features on top of it. The model is
    always geometrically identical to the file; recognised holes/patterns become editable parameters."""
    from aicad.recognize import import_model

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
    stem = f"{_safe_name(body.filename)}_{hashlib.sha256(data).hexdigest()[:8]}"
    rel, rec_rel = f"imports/{stem}.step", f"imports/{stem}.features.json"
    (ws / rel).write_bytes(data)
    name = Path(body.filename).stem[:80] or "Imported part"
    probe = ws / "_fw_import_probe.py"
    probe.write_text(f"from aicad import fw\nresult = fw.import_reference({rel!r})\n", encoding="utf-8")
    try:
        r = await worker.recognize(p.org_id, probe, ws / rec_rel)
    finally:
        probe.unlink(missing_ok=True)
    if not r.get("ok"):
        (ws / rel).unlink(missing_ok=True)
        raise HTTPException(422, "The STEP file could not be read as a solid. Try exporting it again as AP214/AP242 solids.")
    rec = json.loads((ws / rec_rel).read_text(encoding="utf-8"))
    src = import_model(rec, name, rel, rec_rel, Path(body.filename).name)
    n_feat = sum(1 for f in rec["features"] if f["kind"] not in ("body", "unrecognised"))
    try:
        res = await install_model(p, ctx, src, strict=False,
                                  note=f"Imported **{Path(body.filename).name}** with {n_feat} recognised features")
    except HTTPException:
        (ws / rel).unlink(missing_ok=True)
        (ws / rec_rel).unlink(missing_ok=True)
        raise
    audit(ctx.db, "project.step_imported", ctx.user, p.org_id, target=p.id, bytes=len(data))
    track(ctx.db, "step_imported", ctx.user, p.org_id, bytes=len(data))
    ctx.db.commit()
    return {**res, "recognition": _slim(rec)}


def _slim(rec: dict[str, Any]) -> dict[str, Any]:
    """Recognition without the bulky internals (surface keys)."""
    return {**rec, "features": [{k: v for k, v in f.items() if k != "keys"} for f in rec.get("features", [])]}


def _read(f: Path) -> dict[str, Any] | None:
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def _current_recognition(p: Project) -> dict[str, Any] | None:
    ws = workspace_for(p)
    st = _read(ws / "out" / "status.json") or {}
    rec = _read(ws / "out" / "recognition.json")
    if rec is None or rec.get("build_id") != st.get("build_id"):
        return None
    ai = _read(ws / ".fw" / "recognition_ai.json")
    if ai and ai.get("build_id") == st.get("build_id"):
        rec["ai"] = ai
    return rec


@router.get("/projects/{project_id}/recognition")
def get_recognition(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    rec = _current_recognition(_project(ctx, project_id))
    return {"recognition": _slim(rec) if rec else None}


@router.post("/projects/{project_id}/recognition/run")
async def run_recognition(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Geometric feature recognition on the current model (no AI, no tokens). Face ids match the viewer."""
    p = _project(ctx, project_id)
    ws = workspace_for(p)
    if not (ws / "model.py").is_file():
        raise HTTPException(404, "Build a model first")
    await wait_finalized(p.id)
    st = _read(ws / "out" / "status.json") or {}
    r = await worker.recognize(p.org_id, ws / "model.py", ws / "out" / "recognition.json")
    if not r.get("ok"):
        raise HTTPException(422, "Recognition failed on this model")
    rec = json.loads((ws / "out" / "recognition.json").read_text(encoding="utf-8"))
    rec["build_id"] = st.get("build_id")
    (ws / "out" / "recognition.json").write_text(json.dumps(rec), encoding="utf-8")
    track(ctx.db, "recognition_run", ctx.user, p.org_id, faces=rec.get("faces"))
    ctx.db.commit()
    return {"recognition": _slim(rec)}


AI_RECOGNITION_ASK = (
    "Identify what the part is (mechanical component type, standard if any) and name every feature with design intent "
    "and key dimensions; explain any faces listed as not recognised. Do NOT change or rebuild the model. Reply with a "
    "short summary for the engineer and a fenced fw-recognition JSON block: "
    '{"component": {"name", "kind", "standard", "confidence": "high|medium|low", "description"}, '
    '"features": [{"id" (reuse the ids below; new ids for features you find inside unrecognised/body faces), '
    '"name", "kind", "params": {...}, "note"}]}.'
)


@router.post("/projects/{project_id}/recognition/ai")
async def ai_recognition(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """AI recognition: the design agent looks at standard views of the part plus the geometric analysis and
    classifies the component and its features (result arrives as a `recognition` event; uses tokens)."""
    from aicad.platform.routers.projects import ChatIn, agent_chat

    p = _project(ctx, project_id)
    ws = workspace_for(p)
    rec = _current_recognition(p)
    if rec is None:
        rec = (await run_recognition(project_id, ctx))["recognition"]
    await wait_finalized(p.id)
    views = ws / "out" / "views.png"
    refs = ws / "refs"
    refs.mkdir(exist_ok=True)
    img = None
    if views.is_file():
        shutil.copy2(views, refs / "recognition_views.png")
        img = "refs/recognition_views.png"
    feats = [{k: f.get(k) for k in ("id", "name", "kind", "count", "params")} | {"faces": len(f["faces"])}
             for f in rec.get("features", [])]
    data = {k: rec.get(k) for k in ("bbox", "volume_mm3", "faces", "component", "unrecognised")} | {"features": feats}
    where = f" and standard views are in {img} (read the image first)" if img else ""
    prompt = ("Recognise the features of this part.\n\n[Recognition data: the geometric analysis of the current model "
              f"is below{where}. {AI_RECOGNITION_ASK}\n```json\n{json.dumps(data)[:15000]}\n```]")
    res = await agent_chat(project_id, ChatIn(prompt=prompt), ctx)
    return {**res, "build_id": rec.get("build_id")}


@router.post("/projects/{project_id}/recognition/rebuild")
async def rebuild_parametric(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Ask the design agent to rebuild the part as a fully parametric model (CHK-09 compares it to the original)."""
    from aicad.platform.routers.projects import ChatIn, agent_chat
    from aicad.recognize import agent_prompt

    p = _project(ctx, project_id)
    rec = _current_recognition(p) or (await run_recognition(project_id, ctx))["recognition"]
    return await agent_chat(project_id, ChatIn(prompt=agent_prompt(rec)), ctx)
