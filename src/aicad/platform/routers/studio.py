"""Design Studio endpoints: materials & mass, settings, token estimate, manual features, revision compare."""

from __future__ import annotations

import ast
import json
import math
import pprint
import shutil
import uuid
from pathlib import Path
from statistics import median
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from aicad import materials
from aicad.agent import worker
from aicad.platform.db import utcnow
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.models import TokenLedger
from aicad.platform.routers.projects import (
    _project,
    _read_status,
    _rebuild,
    _sessions,
    _snapshot,
    _status_summary,
    schedule_finalize,
    wait_finalized,
    workspace_for,
)
from aicad.platform.services import audit

router = APIRouter(prefix="/api", tags=["studio"])

# ----------------------------------------------------------------------------- materials & settings


@router.get("/materials")
def list_materials() -> dict[str, Any]:
    return {"items": materials.MATERIALS, "source_note": materials.SOURCE_NOTE}


def _settings_path(ws: Path) -> Path:
    return ws / ".fw" / "project.json"


def read_settings(ws: Path) -> dict[str, Any]:
    try:
        return json.loads(_settings_path(ws).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class SettingsIn(BaseModel):
    material: str | None = None
    custom_density_g_cm3: float | None = None


@router.get("/projects/{project_id}/settings")
def get_settings_(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    ws = workspace_for(_project(ctx, project_id))
    st = read_settings(ws)
    if not st.get("material"):
        st["material_guess"] = materials.guess(_read_status(ws).get("material"))
    return st


@router.patch("/projects/{project_id}/settings")
def patch_settings(project_id: str, body: SettingsIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    if ctx.role == "viewer":
        raise HTTPException(403)
    ws = workspace_for(p)
    st = read_settings(ws)
    if body.material is not None:
        if body.material != "custom" and materials.get(body.material) is None:
            raise HTTPException(422, "Unknown material")
        st["material"] = body.material
    if body.custom_density_g_cm3 is not None:
        if not 0.01 <= body.custom_density_g_cm3 <= 30:
            raise HTTPException(422, "Density must be between 0.01 and 30 g/cm³")
        st["custom_density_g_cm3"] = body.custom_density_g_cm3
    _settings_path(ws).parent.mkdir(parents=True, exist_ok=True)
    _settings_path(ws).write_text(json.dumps(st), encoding="utf-8")
    return st


# ----------------------------------------------------------------------------- token estimate


@router.get("/projects/{project_id}/estimate")
def estimate(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    _project(ctx, project_id)
    org = ctx.require_org()
    rows = ctx.db.scalars(select(TokenLedger).where(TokenLedger.org_id == org.id, TokenLedger.reason == "usage")
                          .order_by(TokenLedger.created_at.desc()).limit(30)).all()
    vals = sorted(-r.delta for r in rows if r.delta < 0)
    if len(vals) < 3:
        return {"basis": "default", "typical": 40, "low": 20, "high": 80, "samples": len(vals)}
    q = lambda f: vals[min(len(vals) - 1, int(f * (len(vals) - 1)))]
    return {"basis": "your recent runs", "typical": int(median(vals)), "low": q(0.25), "high": q(0.75),
            "samples": len(vals)}


# ----------------------------------------------------------------------------- manual features

BLOCK_START = "# --- Formwright manual features (managed by the app; edit them in the feature tree) ---"
BLOCK_END = "# --- end manual features ---"
OPS = {"fillet", "chamfer", "hole", "extrude", "shell", "mirror", "sketch", "revolve", "pattern"}
BLANK_MODEL = '''"""{name}: part modelled by hand in Formwright (features live in the feature tree)."""

NAME = {name!r}
MATERIAL = "Aluminium 6061-T6"
PARAMS = {{}}

result = None  # the first boss or revolve in the feature tree creates the body
'''


def read_manual(src: str) -> list[dict[str, Any]]:
    if BLOCK_START not in src:
        return []
    block = src[src.index(BLOCK_START):src.index(BLOCK_END)] if BLOCK_END in src else src[src.index(BLOCK_START):]
    for node in ast.parse(block).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "MANUAL_FEATURES":
            return list(ast.literal_eval(node.value))
    return []


def write_manual(src: str, feats: list[dict[str, Any]]) -> str:
    if BLOCK_START in src:
        end = src.index(BLOCK_END) + len(BLOCK_END) if BLOCK_END in src else len(src)
        src = src[:src.index(BLOCK_START)].rstrip("\n") + "\n" + src[end:].lstrip("\n")
    if not feats:
        return src.rstrip("\n") + "\n"
    block = (f"\n\n{BLOCK_START}\nfrom aicad import fw as _fw\n\n"
             f"MANUAL_FEATURES = {pprint.pformat(feats, width=100, sort_dicts=False)}\n"
             f"result = _fw.apply_manual(result, MANUAL_FEATURES)\n{BLOCK_END}\n")
    return src.rstrip("\n") + block


def _num(v: Any, name: str, lo: float = -1e6, hi: float = 1e6) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise HTTPException(422, f"{name}: invalid number") from None
    if not math.isfinite(x) or not lo <= x <= hi:
        raise HTTPException(422, f"{name}: out of range")
    return x


def _pt(v: Any, name: str) -> list[float]:
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise HTTPException(422, f"{name}: expected [x, y, z]")
    return [_num(c, name) for c in v]


def _pt2(v: Any, name: str) -> list[float]:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise HTTPException(422, f"{name}: expected [u, v]")
    return [_num(c, name) for c in v]


def _sketch_plane(pl: dict[str, Any]) -> dict[str, Any]:
    out = {"origin": _pt(pl.get("origin"), "plane origin"), "normal": _pt(pl.get("normal"), "plane normal"),
           "x_dir": _pt(pl.get("x_dir"), "plane x direction")}
    n, x = out["normal"], out["x_dir"]
    if math.hypot(*n) < 1e-9 or math.hypot(*x) < 1e-9 or abs(sum(a * b for a, b in zip(n, x, strict=True))) > 1e-6 * math.hypot(*n) * math.hypot(*x):
        raise HTTPException(422, "sketch plane: normal and x direction must be non-zero and perpendicular")
    return out


def _profiles(profs: list[Any]) -> list[dict[str, Any]]:
    if not 1 <= len(profs) <= 100:
        raise HTTPException(422, "The sketch needs 1–100 closed profiles")
    clean: list[dict[str, Any]] = []
    for pr in profs:
        if pr.get("kind") == "circle":
            clean.append({"kind": "circle", "cx": _num(pr.get("cx"), "cx"), "cy": _num(pr.get("cy"), "cy"),
                          "r": _num(pr.get("r"), "radius", 0.001, 1e5)})
        elif pr.get("kind") == "loop":
            segs = pr.get("segs") or []
            if not 1 <= len(segs) <= 2000:
                raise HTTPException(422, "Profile has too many segments")
            cs = []
            for sg in segs:
                t = "arc" if sg.get("type") == "arc" else "line"
                item = {"type": t, "a": _pt2(sg.get("a"), "point"), "b": _pt2(sg.get("b"), "point")}
                if t == "arc":
                    item["m"] = _pt2(sg.get("m"), "arc mid")
                cs.append(item)
            clean.append({"kind": "loop", "segs": cs})
        else:
            raise HTTPException(422, "Unknown profile")
    return clean


def _end_condition(f: dict[str, Any], out: dict[str, Any]) -> None:
    """Extrude end condition: blind (distance), mid-plane (distance split both ways) or through all (cuts)."""
    end = f.get("end", "blind")
    if end not in ("blind", "mid", "through"):
        raise HTTPException(422, "End condition must be blind, mid-plane or through all")
    if end == "through" and out["mode"] != "cut":
        raise HTTPException(422, "Through all applies to cuts only")
    out["end"] = end
    out["distance"] = _num(f.get("distance") or 1, "distance", 0.001, 1e5) if end == "through" \
        else _num(f.get("distance"), "distance", 0.001, 1e5)
    out["reverse"] = bool(f.get("reverse"))


def validate_feature(f: dict[str, Any]) -> dict[str, Any]:
    op = f.get("op")
    if op not in OPS:
        raise HTTPException(422, f"Unsupported operation {op!r}")
    out: dict[str, Any] = {"id": str(f.get("id") or uuid.uuid4().hex[:8]), "op": op,
                           "name": str(f.get("name") or op.title())[:60], "suppressed": bool(f.get("suppressed"))}
    if op in ("fillet", "chamfer"):
        edges = f.get("edges") or []
        if not edges or len(edges) > 200:
            raise HTTPException(422, "Select 1–200 edges")
        out["edges"] = [_pt(e, "edge") for e in edges]
        key = "r" if op == "fillet" else "d"
        out[key] = _num(f.get(key), key, 0.001, 1e4)
    elif op == "hole":
        out.update(point=_pt(f.get("point"), "point"), normal=_pt(f.get("normal"), "normal"),
                   d=_num(f.get("d"), "diameter", 0.01, 1e4))
        out["depth"] = _num(f["depth"], "depth", 0.01, 1e5) if f.get("depth") else None
        if f.get("count") and int(f["count"]) > 1:
            out["count"] = min(int(f["count"]), 100)
            if f.get("pattern") == "circular":
                out["pattern"] = "circular"
                out["center"] = _pt(f.get("center"), "pattern centre")
            else:
                out["step"] = _pt(f.get("step"), "step")
    elif op == "shell":
        faces = f.get("faces") or []
        if not 1 <= len(faces) <= 50:
            raise HTTPException(422, "Select 1–50 faces to remove")
        out["faces"] = [{"point": _pt(x.get("point"), "face point"), "normal": _pt(x.get("normal"), "face normal")}
                        for x in faces]
        out["t"] = _num(f.get("t"), "thickness", 0.01, 1e4)
    elif op in ("sketch", "revolve"):
        out["plane"] = _sketch_plane(f.get("plane") or {})
        out["profiles"] = _profiles(f.get("profiles") or [])
        out["mode"] = "cut" if f.get("mode") == "cut" else "add"
        if op == "sketch":
            _end_condition(f, out)
        else:
            ax = f.get("axis") or {}
            out["axis"] = {"a": _pt2(ax.get("a"), "axis start"), "b": _pt2(ax.get("b"), "axis end")}
            if math.dist(out["axis"]["a"], out["axis"]["b"]) < 1e-6:
                raise HTTPException(422, "Draw a centerline in the sketch to revolve about")
            out["angle"] = _num(f.get("angle", 360), "angle", 0.01, 360)
        editor = f.get("editor")
        if isinstance(editor, dict) and len(json.dumps(editor)) < 200_000:
            out["editor"] = json.loads(json.dumps(editor))  # full sketch (constraints, dimensions) for re-editing
    elif op == "pattern":
        src = f.get("source") or []
        if not isinstance(src, list) or not 1 <= len(src) <= 20:
            raise HTTPException(422, "Choose 1–20 features to pattern")
        out["source"] = [str(s)[:40] for s in src]
        out["count"] = int(_num(f.get("count"), "instances", 2, 200))
        if f.get("kind") == "circular":
            ax = f.get("axis") or {}
            out.update(kind="circular", axis={"origin": _pt(ax.get("origin"), "axis point"), "dir": _pt(ax.get("dir"), "axis direction")},
                       angle=_num(f.get("angle", 360), "total angle", 0.01, 360))
            if math.hypot(*out["axis"]["dir"]) < 1e-9:
                raise HTTPException(422, "axis direction: must not be zero")
        else:
            out.update(kind="linear", step=_pt(f.get("step"), "spacing"))
            if math.hypot(*out["step"]) < 1e-6:
                raise HTTPException(422, "spacing: must not be zero")
    elif op == "mirror":
        pl = f.get("plane") or {}
        out["plane"] = {"origin": _pt(pl.get("origin"), "plane origin"), "normal": _pt(pl.get("normal"), "plane normal")}
    elif op == "extrude":
        pl = f.get("plane") or {}
        out["plane"] = {"origin": _pt(pl.get("origin"), "plane origin"), "normal": _pt(pl.get("normal"), "plane normal")}
        if pl.get("x_dir"):
            out["plane"]["x_dir"] = _pt(pl["x_dir"], "plane x_dir")
        sk = f.get("sketch") or {}
        kind = sk.get("kind")
        if kind == "rect":
            out["sketch"] = {"kind": "rect", "w": _num(sk.get("w"), "width", 0.001, 1e5),
                             "h": _num(sk.get("h"), "height", 0.001, 1e5), "cx": _num(sk.get("cx", 0), "cx"),
                             "cy": _num(sk.get("cy", 0), "cy")}
        elif kind == "circle":
            out["sketch"] = {"kind": "circle", "r": _num(sk.get("r"), "radius", 0.001, 1e5),
                             "cx": _num(sk.get("cx", 0), "cx"), "cy": _num(sk.get("cy", 0), "cy")}
        elif kind == "poly":
            pts = sk.get("pts") or []
            if not 3 <= len(pts) <= 200:
                raise HTTPException(422, "Polygon needs 3–200 points")
            out["sketch"] = {"kind": "poly", "pts": [[_num(a, "u"), _num(b, "v")] for a, b in pts]}
        else:
            raise HTTPException(422, "Sketch must be rect, circle or poly")
        out["mode"] = "cut" if f.get("mode") == "cut" else "add"
        _end_condition(f, out)
    return out


async def _apply_manual(ctx: Ctx, project_id: str, mutate: Any, action: str) -> dict[str, Any]:
    p = _project(ctx, project_id)
    if ctx.role == "viewer":
        raise HTTPException(403)
    s = _sessions.get(p.id)
    if s and s.busy:
        raise HTTPException(409, "The agent is working — try again when it finishes")
    ws = workspace_for(p)
    f = ws / "model.py"
    fresh = not f.is_file()
    if fresh:  # modelling from scratch: start a blank hand-modelled part
        ws.mkdir(parents=True, exist_ok=True)
        f.write_text(BLANK_MODEL.format(name=p.name), encoding="utf-8")
    src = f.read_text(encoding="utf-8")
    feats = read_manual(src)
    new_feats = mutate([dict(x) for x in feats])
    await wait_finalized(p.id)  # never snapshot while background exports are writing
    backup = ws / ".out_backup"
    shutil.rmtree(backup, ignore_errors=True)
    if (ws / "out").is_dir():
        shutil.copytree(ws / "out", backup)
    f.write_text(write_manual(src, new_feats), encoding="utf-8")
    st = await _rebuild(p, ws, determinism=False, fast=True)
    if st.get("error") or not st.get("fingerprint"):
        f.unlink() if fresh else f.write_text(src, encoding="utf-8")
        if backup.is_dir():
            shutil.rmtree(ws / "out", ignore_errors=True)
            backup.rename(ws / "out")
        raise HTTPException(422, f"{st.get('error') or 'Build failed'} — the previous model was restored.")
    # Manual edits are gated on geometric validity only; size/volume vs the agent's estimate stay informational.
    gating_fail = [c["id"] for c in st.get("checks", []) if c["id"] in ("CHK-02", "CHK-03") and not c["passed"]]
    if gating_fail:
        f.unlink() if fresh else f.write_text(src, encoding="utf-8")
        if backup.is_dir():
            shutil.rmtree(ws / "out", ignore_errors=True)
            backup.rename(ws / "out")
        raise HTTPException(422, f"The result failed checks ({', '.join(gating_fail)}) — the previous model was restored.")
    shutil.rmtree(backup, ignore_errors=True)
    p.last_status = _status_summary(st)
    p.builds += 1
    p.updated_at = utcnow()
    rev = _snapshot(p, ws)
    schedule_finalize(p, ws, rev)
    audit(ctx.db, f"project.manual_{action}", ctx.user, p.org_id, target=p.id)
    ctx.db.commit()
    if s:
        s.publish({"type": "text", "text": f"Manual feature {action} without AI (revision {rev})."})
    return {"ok": True, "features": new_feats, "revision": rev, "build_s": (st.get("timings_s") or {}).get("total_s")}


class FeatureIn(BaseModel):
    feature: dict[str, Any]


class ReorderIn(BaseModel):
    ids: list[str]


@router.get("/projects/{project_id}/manual")
def list_manual(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    f = workspace_for(_project(ctx, project_id)) / "model.py"
    return {"features": read_manual(f.read_text(encoding="utf-8")) if f.is_file() else []}


@router.post("/projects/{project_id}/manual")
async def add_manual(project_id: str, body: FeatureIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    feat = validate_feature(body.feature)
    return await _apply_manual(ctx, project_id, lambda fs: [*fs, feat], "added")


@router.patch("/projects/{project_id}/manual/{fid}")
async def edit_manual(project_id: str, fid: str, body: FeatureIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    def mutate(fs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for i, f in enumerate(fs):
            if f["id"] == fid:
                fs[i] = validate_feature({**f, **body.feature, "id": fid})
                return fs
        raise HTTPException(404, "Feature not found")
    return await _apply_manual(ctx, project_id, mutate, "edited")


@router.delete("/projects/{project_id}/manual/{fid}")
async def delete_manual(project_id: str, fid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    def mutate(fs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not any(f["id"] == fid for f in fs):
            raise HTTPException(404, "Feature not found")
        return [f for f in fs if f["id"] != fid]
    return await _apply_manual(ctx, project_id, mutate, "deleted")


@router.post("/projects/{project_id}/manual/reorder")
async def reorder_manual(project_id: str, body: ReorderIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    def mutate(fs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by = {f["id"]: f for f in fs}
        if sorted(body.ids) != sorted(by):
            raise HTTPException(422, "Reorder must list every feature exactly once")
        return [by[i] for i in body.ids]
    return await _apply_manual(ctx, project_id, mutate, "reordered")


# ----------------------------------------------------------------------------- revisions: files & compare

REV_FILES = {"topo.json": "application/json", "status.json": "application/json", "views.png": "image/png"}


@router.get("/projects/{project_id}/revisions/{n}/files/{name}")
def revision_file(project_id: str, n: int, name: str, ctx: Ctx = Depends(verified_ctx)) -> FileResponse:
    if name not in REV_FILES:
        raise HTTPException(404)
    f = workspace_for(_project(ctx, project_id)) / "revisions" / str(n) / name
    if not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, media_type=REV_FILES[name], headers={"Cache-Control": "no-store"})


class CompareIn(BaseModel):
    base: int
    target: int | None = None  # None = current model


@router.post("/projects/{project_id}/compare")
async def compare(project_id: str, body: CompareIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _project(ctx, project_id)
    ws = workspace_for(p)
    await wait_finalized(p.id)
    a = ws / "revisions" / str(body.base) / "part.step"
    b = (ws / "revisions" / str(body.target) / "part.step") if body.target else ws / "out" / "part.step"
    if not a.is_file() or not b.is_file():
        raise HTTPException(404, "That revision has no STEP snapshot (revisions before this feature can't be compared)")
    key = f"{body.base}_{body.target or 'current'}"
    out = ws / ".fw" / "compare" / key
    shutil.rmtree(out, ignore_errors=True)
    r = await worker.diff(p.org_id, a, b, out)
    if not r.get("ok"):
        raise HTTPException(422, f"Compare failed: {r.get('error')}")

    def params_of(n: int | None) -> dict[str, Any]:
        f = (ws / "revisions" / str(n) / "status.json") if n else ws / "out" / "status.json"
        try:
            return json.loads(f.read_text(encoding="utf-8")).get("params") or {}
        except (OSError, ValueError):
            return {}
    pa, pb = params_of(body.base), params_of(body.target)
    changed = {k: {"from": pa.get(k), "to": pb.get(k)} for k in sorted(set(pa) | set(pb)) if pa.get(k) != pb.get(k)}
    base_url = f"/api/projects/{p.id}/compare-files/{key}"
    return {"added_mm3": r.get("added_mm3"), "removed_mm3": r.get("removed_mm3"), "params_changed": changed,
            "added_url": f"{base_url}/added.json" if (out / "added.json").is_file() else None,
            "removed_url": f"{base_url}/removed.json" if (out / "removed.json").is_file() else None}


@router.get("/projects/{project_id}/compare-files/{key}/{name}")
def compare_file(project_id: str, key: str, name: str, ctx: Ctx = Depends(verified_ctx)) -> FileResponse:
    if name not in ("added.json", "removed.json") or not all(c.isalnum() or c == "_" for c in key):
        raise HTTPException(404)
    f = workspace_for(_project(ctx, project_id)) / ".fw" / "compare" / key / name
    if not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, media_type="application/json", headers={"Cache-Control": "no-store"})
