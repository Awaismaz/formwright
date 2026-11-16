"""Design variants: named, pinned revisions of one part, compared side by side (trade studies without overwriting).

A variant points at a revision snapshot (model.py, status, STEP, views), so restore and 3D compare reuse the
revision machinery. Whether a variant is the current design is decided by comparing model sources exactly.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from aicad.change_notice import mass_g
from aicad.platform.db import utcnow
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.routers.projects import _project, workspace_for
from aicad.platform.services import audit

router = APIRouter(prefix="/api", tags=["variants"])
MAX_VARIANTS = 12


def _file(ws: Path) -> Path:
    return ws / "variants.json"


def _load(ws: Path) -> list[dict[str, Any]]:
    try:
        return list(json.loads(_file(ws).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def _save(ws: Path, items: list[dict[str, Any]]) -> None:
    _file(ws).write_text(json.dumps(items, indent=1), encoding="utf-8")


def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def _summary(st: dict[str, Any]) -> dict[str, Any]:
    fp = st.get("fingerprint") or {}
    return {"ok": bool(st.get("ok")), "material": st.get("material"), "params": st.get("params") or {},
            "volume": fp.get("volume"), "bbox": fp.get("bbox"), "faces": fp.get("faces"), "mass_g": mass_g(st)}


def _json(p: Path) -> dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _current_rev(ws: Path) -> int | None:
    """Newest revision whose model source equals the current design."""
    cur = _read(ws / "model.py")
    root = ws / "revisions"
    if cur is None or not root.is_dir():
        return None
    for d in sorted((d for d in root.iterdir() if d.name.isdigit()), key=lambda d: -int(d.name)):
        if _read(d / "model.py") == cur:
            return int(d.name)
    return None


@router.get("/projects/{project_id}/variants")
def list_variants(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    ws = workspace_for(_project(ctx, project_id))
    cur_src = _read(ws / "model.py")
    items = []
    for v in _load(ws):
        d = ws / "revisions" / str(v["rev"])
        if not d.is_dir():
            continue
        items.append({**v, **_summary(_json(d / "status.json")), "views": (d / "views.png").is_file(),
                      "current": cur_src is not None and _read(d / "model.py") == cur_src})
    return {"items": items, "current_rev": _current_rev(ws), "current": _summary(_json(ws / "out" / "status.json")),
            "current_is_variant": any(i["current"] for i in items)}


class VariantIn(BaseModel):
    name: str
    rev: int | None = None
    note: str = ""


class VariantPatch(BaseModel):
    name: str | None = None
    note: str | None = None


def _clean_name(name: str, items: list[dict[str, Any]], skip: str | None = None) -> str:
    n = " ".join(name.split())[:40]
    if not n:
        raise HTTPException(422, "Give the variant a name")
    if any(i["name"].lower() == n.lower() and i["id"] != skip for i in items):
        raise HTTPException(409, f"A variant called “{n}” already exists")
    return n


@router.post("/projects/{project_id}/variants")
def create_variant(project_id: str, body: VariantIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    if ctx.role == "viewer":
        raise HTTPException(403)
    ws = workspace_for(p)
    items = _load(ws)
    if len(items) >= MAX_VARIANTS:
        raise HTTPException(409, f"Up to {MAX_VARIANTS} variants per part; delete one first")
    rev = body.rev if body.rev is not None else _current_rev(ws)
    if rev is None or not (ws / "revisions" / str(rev) / "model.py").is_file():
        raise HTTPException(409, "Build and verify the current design first, then save it as a variant")
    if any(i["rev"] == rev for i in items):
        raise HTTPException(409, f"Revision {rev} is already the variant “{next(i['name'] for i in items if i['rev'] == rev)}”")
    v = {"id": uuid.uuid4().hex[:8], "name": _clean_name(body.name, items), "rev": rev, "note": body.note[:300],
         "by": ctx.user.name, "created_at": utcnow().isoformat(timespec="minutes")}
    _save(ws, [*items, v])
    audit(ctx.db, "project.variant_saved", ctx.user, p.org_id, target=p.id, variant=v["name"], revision=rev)
    ctx.db.commit()
    return v


@router.patch("/projects/{project_id}/variants/{vid}")
def update_variant(project_id: str, vid: str, body: VariantPatch, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    if ctx.role == "viewer":
        raise HTTPException(403)
    ws = workspace_for(p)
    items = _load(ws)
    v = next((i for i in items if i["id"] == vid), None)
    if v is None:
        raise HTTPException(404)
    if body.name is not None:
        v["name"] = _clean_name(body.name, items, skip=vid)
    if body.note is not None:
        v["note"] = body.note[:300]
    _save(ws, items)
    return v


@router.delete("/projects/{project_id}/variants/{vid}")
def delete_variant(project_id: str, vid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    if ctx.role == "viewer":
        raise HTTPException(403)
    ws = workspace_for(p)
    items = _load(ws)
    if not any(i["id"] == vid for i in items):
        raise HTTPException(404)
    _save(ws, [i for i in items if i["id"] != vid])
    return {"ok": True}
