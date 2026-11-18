"""Design Studio endpoints: materials & mass, settings, token estimate, manual features, revision compare."""

from __future__ import annotations

import ast
import json
import math
import pprint
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from aicad import holes, materials, refplane, threads
from aicad.agent import worker
from aicad.platform.db import utcnow
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.plain import build_error
from aicad.platform.routers.projects import (
    _project,
    _read_status,
    _rebuild,
    _sessions,
    _snapshot,
    _status_summary,
    current_revision,
    schedule_finalize,
    wait_finalized,
    workspace_for,
)
from aicad.platform.services import audit, notify_revision

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
def estimate(project_id: str, chars: int = 0, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Expected tokens for the next agent run on this part, and the budget it would run with."""
    from aicad.platform import metering

    p = _project(ctx, project_id)
    org = ctx.require_org()
    est = metering.estimate(ctx.db, org, "change" if p.builds else "new", chars)
    budget, _ = metering.run_budget(ctx.db, org, ctx.user, None, ctx.god_on("bypass_tokens"))
    return {**est, "budget": budget, "default_budget": metering.default_budget(ctx.db, org),
            "budget_min": metering.BUDGET_MIN, "budget_max": metering.BUDGET_MAX}


# ----------------------------------------------------------------------------- manual features

BLOCK_START = "# --- Formwright manual features (managed by the app; edit them in the feature tree) ---"
BLOCK_END = "# --- end manual features ---"
OPS = {"fillet", "chamfer", "hole", "extrude", "shell", "mirror", "sketch", "revolve", "pattern", "plane", "draft", "rib",
       "sketch2d", "sweep", "loft", "thread", "sm_base", "sm_flange", "sm_hem", "sm_jog"}
BLANK_MODEL = '''"""{name}: part modelled by hand in Formwright (features live in the feature tree)."""

NAME = {name!r}
MATERIAL = "unspecified"
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


def _segs(segs: Any) -> list[dict[str, Any]]:
    """Line/arc segments of a sketch chain (arcs through a mid point)."""
    if not isinstance(segs, list) or not 1 <= len(segs) <= 2000:
        raise HTTPException(422, "Profile has too many segments")
    cs = []
    for sg in segs:
        t = "arc" if sg.get("type") == "arc" else "line"
        item = {"type": t, "a": _pt2(sg.get("a"), "point"), "b": _pt2(sg.get("b"), "point")}
        if t == "arc":
            item["m"] = _pt2(sg.get("m"), "arc mid")
        cs.append(item)
    return cs


def _face_refs(faces: Any, what: str) -> list[dict[str, Any]]:
    if not isinstance(faces, list) or not 1 <= len(faces) <= 50:
        raise HTTPException(422, f"Select 1–50 {what}")
    out = []
    for x in faces:
        item = {"point": _pt(x.get("point"), "face point")}
        if x.get("normal") is not None:
            item["normal"] = _pt(x["normal"], "face normal")
        out.append(item)
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
            clean.append({"kind": "loop", "segs": _segs(pr.get("segs") or [])})
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


REF_OPS = {"fillet", "chamfer", "hole", "shell", "draft", "thread", "sm_flange", "sm_hem", "sm_jog"}  # picks stored with the body's box, to follow size changes


def _edge_ref(r: Any) -> dict[str, Any]:
    if not isinstance(r, dict) or r.get("kind") not in ("line", "circle", "other"):
        raise HTTPException(422, "edge reference: unknown edge kind")
    out: dict[str, Any] = {"kind": r["kind"]}
    if r.get("dir") is not None:
        out["dir"] = _pt(r["dir"], "edge direction")
    return out


def _place(pl: Any, normal: list[float]) -> dict[str, Any]:
    """Hole Wizard placement: on a picked face, by distance from its edges."""
    if not isinstance(pl, dict) or pl.get("mode") not in ("corners", "points"):
        raise HTTPException(422, "Hole position: choose corners or positions")
    face = pl.get("face") or {}
    out: dict[str, Any] = {"mode": pl["mode"], "face": {"point": _pt(face.get("point"), "face point"), "normal": list(normal)}}
    if pl.get("x_dir") is not None:
        out["x_dir"] = _pt(pl["x_dir"], "face x direction")
    if pl["mode"] == "corners":
        out["dx"] = _num(pl.get("dx"), "edge distance X", 0.01, 1e5)
        out["dy"] = _num(pl.get("dy"), "edge distance Y", 0.01, 1e5)
    else:
        pts = pl.get("pts") or []
        if not isinstance(pts, list) or not 1 <= len(pts) <= 100:
            raise HTTPException(422, "Place 1–100 holes")
        out["pts"] = [_pt2(q, "hole position") for q in pts]
    return out


def validate_feature(f: dict[str, Any]) -> dict[str, Any]:
    op = f.get("op")
    if op not in OPS:
        raise HTTPException(422, f"Unsupported operation {op!r}")
    out: dict[str, Any] = {"id": str(f.get("id") or uuid.uuid4().hex[:8]), "op": op,
                           "name": str(f.get("name") or op.title())[:60], "suppressed": bool(f.get("suppressed"))}
    if f.get("rolled_back"):  # below the rollback bar: kept in the tree, not built
        out["rolled_back"] = True
    if op in ("fillet", "chamfer"):
        edges = f.get("edges") or []
        if not edges or len(edges) > 200:
            raise HTTPException(422, "Select 1–200 edges")
        out["edges"] = [_pt(e, "edge") for e in edges]
        refs = f.get("edge_refs")
        if isinstance(refs, list) and len(refs) == len(edges):
            out["edge_refs"] = [_edge_ref(r) for r in refs]
        key = "r" if op == "fillet" else "d"
        out[key] = _num(f.get(key), "radius" if op == "fillet" else "distance", 0.001, 1e4)
    elif op == "hole":
        out.update(point=_pt(f.get("point"), "point"), normal=_pt(f.get("normal"), "normal"),
                   d=_num(f.get("d"), "diameter", 0.01, 1e4))
        out["depth"] = _num(f["depth"], "depth", 0.01, 1e5) if f.get("depth") else None
        if f.get("spec"):  # Hole Wizard: sizes come from the standard tables, never from the client
            try:
                out.update(holes.resolve(f["spec"]))
            except holes.HoleError as e:
                raise HTTPException(422, str(e)) from None
        if f.get("thread"):  # cosmetic thread (CAD-027): from the ISO 261 table, checked against the drill
            try:
                out["thread"] = threads.resolve(f["thread"], internal=True, bore=out["d"], length=out["depth"])
            except threads.ThreadError as e:
                raise HTTPException(422, str(e)) from None
        if f.get("place"):
            out["place"] = _place(f["place"], out["normal"])
        elif f.get("count") and int(f["count"]) > 1:
            out["count"] = min(int(f["count"]), 100)
            if f.get("pattern") == "circular":
                out["pattern"] = "circular"
                out["center"] = _pt(f.get("center"), "pattern centre")
            else:
                out["step"] = _pt(f.get("step"), "step")
    if op in REF_OPS and isinstance(f.get("ref_bbox"), list) and len(f["ref_bbox"]) == 6:
        out["ref_bbox"] = [_num(v, "reference box") for v in f["ref_bbox"]]
    if op == "shell":
        faces = f.get("faces") or []
        if not 1 <= len(faces) <= 50:
            raise HTTPException(422, "Select 1–50 faces to remove")
        out["faces"] = [{"point": _pt(x.get("point"), "face point"), "normal": _pt(x.get("normal"), "face normal")}
                        for x in faces]
        out["t"] = _num(f.get("t"), "thickness", 0.01, 1e4)
    elif op in ("fillet", "chamfer", "hole"):
        pass
    elif op == "thread":  # cosmetic thread on a picked cylindrical face; size checked against it at build time
        face = f.get("face") or {}
        out["face"] = {"point": _pt(face.get("point"), "face point")}
        th = f.get("thread") or {}
        if not isinstance(th, dict):
            raise HTTPException(422, "Choose a thread size")
        try:  # table checks now (size, pitch); the class and the fit to the cylinder are checked when it builds
            base = threads.parse(th["designation"]) if th.get("designation") else {
                "size": th.get("size"), "pitch": th.get("pitch"), "cls": None}
            threads.resolve({**base, "cls": None, "depth": th.get("depth")}, internal=True)
        except (threads.ThreadError, KeyError, TypeError, ValueError) as e:
            raise HTTPException(422, str(e) if isinstance(e, threads.ThreadError) else "Choose a thread size") from None
        cls = str(th.get("cls") or base.get("cls") or "")[:3]
        out["thread"] = {"size": float(base["size"]), "pitch": float(base["pitch"] or threads.COARSE[float(base["size"])]),
                         "depth": _num(th["depth"], "thread depth", 0.01, 1e5) if th.get("depth") else None,
                         **({"cls": cls} if cls else {})}
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
        if f.get("plane_ref"):  # attached to a reference plane feature: follows it when the plane is edited
            out["plane_ref"] = str(f["plane_ref"])[:40]
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
    elif op == "draft":
        nf = f.get("neutral") or {}
        out["neutral"] = {"point": _pt(nf.get("point"), "neutral plane point"), "normal": _pt(nf.get("normal"), "neutral plane normal")}
        if math.hypot(*out["neutral"]["normal"]) < 1e-9:
            raise HTTPException(422, "Pick a planar face as the neutral plane")
        out["faces"] = _face_refs(f.get("faces"), "faces to draft")
        out["angle"] = _num(f.get("angle"), "draft angle", 0.01, 45)
        out["reverse"] = bool(f.get("reverse"))
    elif op == "rib":
        out["plane"] = _sketch_plane(f.get("plane") or {})
        if f.get("plane_ref"):
            out["plane_ref"] = str(f["plane_ref"])[:40]
        chains = f.get("chains") or []
        if not isinstance(chains, list) or not 1 <= len(chains) <= 20:
            raise HTTPException(422, "A rib needs an open sketch profile (lines or arcs that don't close)")
        out["chains"] = [_segs(c) for c in chains]
        out["t"] = _num(f.get("t"), "rib thickness", 0.01, 1e4)
        out["flip"] = bool(f.get("flip"))
        editor = f.get("editor")
        if isinstance(editor, dict) and len(json.dumps(editor)) < 200_000:
            out["editor"] = json.loads(json.dumps(editor))
    elif op == "sketch2d":  # a sketch kept as a tree node (no feature): consumed by sweeps and lofts
        out["plane"] = _sketch_plane(f.get("plane") or {})
        if f.get("plane_ref"):
            out["plane_ref"] = str(f["plane_ref"])[:40]
        profs, chains = f.get("profiles") or [], f.get("chains") or []
        if not profs and not chains:
            raise HTTPException(422, "The sketch is empty")
        out["profiles"] = _profiles(profs) if profs else []
        if not isinstance(chains, list) or len(chains) > 20:
            raise HTTPException(422, "The sketch has too many open chains")
        out["chains"] = [_segs(ch) for ch in chains]
        editor = f.get("editor")
        if isinstance(editor, dict) and len(json.dumps(editor)) < 200_000:
            out["editor"] = json.loads(json.dumps(editor))
    elif op == "sm_base":  # sheet metal (CAD-026): a closed sketch thickened into a sheet, plus the sheet parameters
        out["plane"] = _sketch_plane(f.get("plane") or {})
        out["profiles"] = _profiles(f.get("profiles") or [])
        if f.get("plane_ref"):
            out["plane_ref"] = str(f["plane_ref"])[:40]
        out["t"] = _num(f.get("t"), "sheet thickness", 0.05, 50)
        out["r"] = _num(f["r"], "bend radius", 0, 1e3) if f.get("r") is not None else out["t"]
        out["k"] = _num(f.get("k", 0.44), "K-factor", 0, 1)
        rel = f.get("relief") or {}
        if rel.get("type", "rect") not in ("rect", "obround", "none"):
            raise HTTPException(422, "Relief type must be rectangular, obround or none")
        out["relief"] = {"type": str(rel.get("type", "rect")), "ratio": _num(rel.get("ratio", 0.5), "relief ratio", 0.05, 5)}
        cor = f.get("corner") or {}
        if cor.get("type", "closed") not in ("closed", "open"):
            raise HTTPException(422, "Corner type must be closed or open")
        out["corner"] = {"type": str(cor.get("type", "closed")), "gap": _num(cor.get("gap", 0.2), "corner gap", 0, 50)}
        out["reverse"] = bool(f.get("reverse"))
        editor = f.get("editor")
        if isinstance(editor, dict) and len(json.dumps(editor)) < 200_000:
            out["editor"] = json.loads(json.dumps(editor))
    elif op == "sm_jog":  # two opposite bends that raise the end of the sheet at the picked edge
        out["edge"] = _pt(f.get("edge"), "edge")
        if f.get("edge_ref") is not None:
            out["edge_ref"] = _edge_ref(f["edge_ref"])
        out["distance"] = _num(f.get("distance"), "jog distance from the edge", 0.01, 1e5)
        out["offset"] = _num(f.get("offset"), "jog offset", 0.01, 1e5)
        out["angle"] = _num(f.get("angle", 90), "jog angle", 1, 90)
        out["r"] = _num(f["r"], "bend radius", 0, 1e3) if f.get("r") is not None else None
        out["flip"] = bool(f.get("flip"))
    elif op in ("sm_flange", "sm_hem"):
        out["edge"] = _pt(f.get("edge"), "edge")
        if f.get("edge_ref") is not None:
            out["edge_ref"] = _edge_ref(f["edge_ref"])
        out["length"] = _num(f.get("length"), "flange length" if op == "sm_flange" else "hem length", 0.01, 1e5)
        out["flip"] = bool(f.get("flip"))
        if op == "sm_flange":
            out["angle"] = _num(f.get("angle", 90), "flange angle", 0.1, 180)
            out["r"] = _num(f["r"], "bend radius", 0, 1e3) if f.get("r") is not None else None
            if f.get("position", "inside") not in ("inside", "outside", "bend_outside"):
                raise HTTPException(422, "Position must be material inside, material outside or bend outside")
            out["position"] = str(f.get("position", "inside"))
            if f.get("length_ref", "outer") not in ("outer", "tangent"):
                raise HTTPException(422, "Flange length is measured to the outer virtual sharp or the bend tangent")
            out["length_ref"] = str(f.get("length_ref", "outer"))
            ins = f.get("inset") or [0, 0]
            if not isinstance(ins, (list, tuple)) or len(ins) != 2:
                raise HTTPException(422, "End offsets: expected [start, end]")
            out["inset"] = [_num(v, "end offset", 0, 1e5) for v in ins]
        else:
            if f.get("position", "inside") not in ("inside", "outside"):
                raise HTTPException(422, "A hem sits material inside or material outside")
            out["position"] = str(f.get("position", "inside"))
            out["gap"] = _num(f["gap"], "hem gap", 0.01, 1e3) if f.get("gap") is not None else None
    elif op == "sweep":
        out["profile"], out["path"] = str(f.get("profile") or "")[:40], str(f.get("path") or "")[:40]
        if not out["profile"] or not out["path"]:
            raise HTTPException(422, "Choose a profile sketch and a path sketch")
        if out["profile"] == out["path"]:
            raise HTTPException(422, "The profile and the path must be different sketches")
        out["mode"] = "cut" if f.get("mode") == "cut" else "add"
    elif op == "loft":
        secs = f.get("sections") or []
        if not isinstance(secs, list) or not 2 <= len(secs) <= 20 or len(set(map(str, secs))) != len(secs):
            raise HTTPException(422, "Choose 2–20 different section sketches, in order")
        out["sections"] = [str(s)[:40] for s in secs]
        out["ruled"] = bool(f.get("ruled"))
        out["mode"] = "cut" if f.get("mode") == "cut" else "add"
    elif op == "plane":
        out["base"] = _sketch_plane(f.get("base") or {})
        out["base_name"] = str(f.get("base_name") or "")[:60]
        out["offset"] = _num(f.get("offset") or 0, "offset", -1e5, 1e5)
        out["angle"] = _num(f.get("angle") or 0, "angle", -180, 180)
        out["rot_axis"] = "y" if f.get("rot_axis") == "y" else "x"
        out["plane"] = refplane.ref_plane(out)  # resolved placement, for the app and for attached sketches
    elif op == "mirror":
        pl = f.get("plane") or {}
        out["plane"] = {"origin": _pt(pl.get("origin"), "plane origin"), "normal": _pt(pl.get("normal"), "plane normal")}
        if math.hypot(*out["plane"]["normal"]) < 1e-9:
            raise HTTPException(422, "mirror plane: normal must not be zero")
        src = f.get("source")
        if src:  # mirror features (otherwise the whole body)
            if not isinstance(src, list) or len(src) > 20:
                raise HTTPException(422, "Choose 1–20 features to mirror")
            out["source"] = [str(s)[:40] for s in src]
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


def _current_bbox(ws: Path) -> list[float] | None:
    st = _read_status(ws)
    if st.get("bbox_minmax"):
        return list(st["bbox_minmax"])
    try:  # builds from before bbox_minmax was recorded
        return list(json.loads((ws / "out" / "topo.json").read_text(encoding="utf-8"))["bbox"])
    except (OSError, ValueError, KeyError):
        return None


def stamp_refs(feats: list[dict[str, Any]], bbox: list[float] | None, ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Record the body's box with hand-picked edges/faces (all features lacking one, or the given ids), so the
    picks can follow the body when a dimension changes (STU-03)."""
    if bbox is None:
        return feats
    for x in feats:
        if x["op"] in REF_OPS and (x["id"] in ids if ids is not None else "ref_bbox" not in x):
            x["ref_bbox"] = [round(float(v), 6) for v in bbox]
    return feats


def stamp_manual_refs(src: str, ws: Path) -> str:
    """Before a parameter change: give older manual features (made before refs were stored) the current box."""
    feats = read_manual(src)
    if not feats or not any(x["op"] in REF_OPS and "ref_bbox" not in x for x in feats):
        return src
    return write_manual(src, stamp_refs(feats, _current_bbox(ws)))


def _restore(f: Path, src: str, fresh: bool, ws: Path, backup: Path) -> None:
    f.unlink() if fresh else f.write_text(src, encoding="utf-8")
    if backup.is_dir():
        shutil.rmtree(ws / "out", ignore_errors=True)
        backup.rename(ws / "out")


async def _apply_manual(ctx: Ctx, project_id: str, mutate: Any, action: str, transform: Any = None,
                        cause: str | None = None, strict: set[str] | str | None = None) -> dict[str, Any]:
    """Apply a feature-tree change and rebuild (no AI). A failure of a feature in `strict` (the one just added or
    edited; "new" = any feature that built before) rejects the change. Otherwise a feature that no longer rebuilds
    is kept, flagged in the tree with its reason (a rebuild error to repair), and the rest of the model still builds."""
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
    new_feats = normalize_rollback(sync_planes(mutate([dict(x) for x in feats])))
    if transform is not None and fresh:
        f.unlink()
        raise HTTPException(404, "There is no design to change yet")
    if transform is None and _blank(src) and all(x["op"] in refplane.NON_GEOMETRIC for x in new_feats):
        # a hand-modelled part with only reference geometry so far: nothing to build yet
        f.write_text(write_manual(src, new_feats), encoding="utf-8")
        p.updated_at = utcnow()
        audit(ctx.db, f"project.manual_{action}", ctx.user, p.org_id, target=p.id)
        ctx.db.commit()
        return {"ok": True, "features": new_feats, "revision": None, "build_s": None}
    await wait_finalized(p.id)  # never snapshot while background exports are writing
    backup = ws / ".out_backup"
    shutil.rmtree(backup, ignore_errors=True)
    if (ws / "out").is_dir():
        shutil.copytree(ws / "out", backup)
    f.write_text(transform(src) if transform is not None else write_manual(src, new_feats), encoding="utf-8")
    before = current_revision(ws)
    prev_errors = {m["id"] for m in _read_status(ws).get("manual_errors") or []}
    try:
        st = await _rebuild(p, ws, determinism=False, fast=True)
    except HTTPException:
        _restore(f, src, fresh, ws, backup)
        raise
    if st.get("error") or not st.get("fingerprint"):
        _restore(f, src, fresh, ws, backup)
        raise HTTPException(422, f"{build_error(st.get('error'))}. The previous model was restored.")
    bad = next((m for m in st.get("manual_errors") or [] if (strict == "new" and m["id"] not in prev_errors)
                or (isinstance(strict, set) and m["id"] in strict)), None)
    if bad:
        _restore(f, src, fresh, ws, backup)
        raise HTTPException(422, f"“{bad['name']}” couldn't be built: {bad['error']}. The previous model was restored.")
    # Manual edits are gated on geometric validity only; size/volume vs the agent's estimate stay informational.
    gating_fail = [c for c in st.get("checks", []) if c["id"] in ("CHK-02", "CHK-03") and not c["passed"]]
    if gating_fail:
        _restore(f, src, fresh, ws, backup)
        raise HTTPException(422, f"{build_error(None, [{**c, 'gating': True} for c in gating_fail])}. "
                                 "The previous model was restored.")
    shutil.rmtree(backup, ignore_errors=True)
    p.last_status = _status_summary(st)
    p.builds += 1
    p.updated_at = utcnow()
    if cause is None:
        names = ([f.get("name", f.get("op")) for f in new_feats if f not in feats]
                 or [f.get("name", f.get("op")) for f in feats if f not in new_feats])
        cause = f"Manual feature {action}" + (f": {', '.join(names)}" if names else "")
    rev = _snapshot(p, ws, cause=cause, kind="manual", by=ctx.user.name)
    notify_revision(ctx.db, p, rev, ctx.user, cause)
    schedule_finalize(p, ws, rev)
    audit(ctx.db, f"project.manual_{action}", ctx.user, p.org_id, target=p.id)
    ctx.db.commit()
    if s:
        what = (f"Feature tree {action[5:].replace('_', ' ')}" if action.startswith("tree_")
                else f"{'Feature' if transform is not None else 'Manual feature'} {action}")
        s.publish({"type": "text", "text": f"{what} without AI (revision {rev})."})
    return {"ok": True, "features": new_feats, "revision": rev, "rev_before": before, "repairs": st.get("manual_errors") or [],
            "build_s": (st.get("timings_s") or {}).get("total_s")}


def trial_source(src: str, ws: Path, change: dict[str, Any]) -> tuple[str, set[str]]:
    """The model source as it would be after a pending Studio change, without touching the workspace (ASM-018 trial
    builds). ``change``: {"kind": "feature", "feature"} (a new manual feature), {"kind": "edit", "id", "feature"}
    (changed fields of one), or {"kind": "params", "values"}. Returns (source, ids whose failure rejects it)."""
    from aicad.platform.routers.projects import current_editable, rewrite_params

    kind = change.get("kind")
    if kind == "params":
        values = change.get("values")
        if not isinstance(values, dict) or not values:
            raise HTTPException(422, "Which parameter changes?")
        new, changes = rewrite_params(src, current_editable(ws), _read_status(ws).get("param_meta") or {},
                                      {str(k): float(v) for k, v in values.items()})
        if not changes:
            raise HTTPException(422, "Those are the current values: nothing changes")
        return stamp_manual_refs(new, ws), set()
    feats = read_manual(src)
    bbox = _current_bbox(ws)
    raw = change.get("feature")
    if not isinstance(raw, dict):
        raise HTTPException(422, "Which feature?")
    if kind == "feature":
        feat = validate_feature({**raw, "rolled_back": False})
        bar = next((i for i, x in enumerate(feats) if x.get("rolled_back")), len(feats))
        new_feats = [*feats[:bar], *stamp_refs([feat], bbox, {feat["id"]}), *feats[bar:]]
        fid = feat["id"]
    elif kind == "edit":
        fid = str(change.get("id") or "")
        i = next((k for k, x in enumerate(feats) if x["id"] == fid), None)
        if i is None:
            raise HTTPException(404, "Feature not found")
        merged = {**feats[i], **raw, "id": fid}
        repicked = bool({"edges", "point", "faces", "place", "neutral"} & set(raw))
        if repicked and "edges" in raw and "edge_refs" not in raw:
            merged.pop("edge_refs", None)
        new = validate_feature(merged)
        new_feats = list(feats)
        new_feats[i] = stamp_refs([new], bbox, {fid})[0] if repicked else new
    else:
        raise HTTPException(422, "Unknown change")
    return write_manual(src, normalize_rollback(sync_planes(new_feats))), {fid}


SUP_START = "# --- Formwright suppressed features (managed by the app; toggle them in the feature tree) ---"
SUP_END = "# --- end suppressed features ---"


def write_managed(src: str, suppressed: list[str], deleted: list[str] | None = None) -> str:
    """Set the app-managed SUPPRESSED_FEATURES / DELETED_FEATURES lists. The block sits just before the
    manual-features block (or at the end). DELETED_FEATURES records steps removed without AI, so the size and
    volume checks stay informational until the design's expected values are updated."""
    nl = "\n"
    if SUP_START in src:
        end = src.index(SUP_END) + len(SUP_END) if SUP_END in src else len(src)
        src = src[:src.index(SUP_START)].rstrip(nl) + nl + src[end:].lstrip(nl)
    lines = []
    if suppressed:
        lines.append(f"SUPPRESSED_FEATURES = {sorted(set(suppressed))!r}")
    if deleted:
        lines.append(f"DELETED_FEATURES = {sorted(set(deleted))!r}")
    if not lines:
        return src if src.endswith(nl) else src + nl
    block = SUP_START + nl + nl.join(lines) + nl + SUP_END + nl
    if BLOCK_START in src:
        i = src.index(BLOCK_START)
        return src[:i].rstrip(nl) + nl + nl + block + nl + src[i:]
    return src.rstrip(nl) + nl + nl + block


def write_suppressed(src: str, names: list[str]) -> str:
    from aicad.agent.runner import managed_list

    return write_managed(src, names, managed_list(src, "DELETED_FEATURES"))


class SuppressIn(BaseModel):
    name: str
    suppressed: bool


@router.post("/projects/{project_id}/design-features/suppress")
async def suppress_design_feature(project_id: str, body: SuppressIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Suppress or restore a feature the design agent built (no AI): the model is rebuilt without that step."""
    from aicad.agent.runner import suppressed_features

    p = _project(ctx, project_id)
    ws = workspace_for(p)
    mf = ws / "model.py"
    if not mf.is_file():
        raise HTTPException(404, "There is no design to change yet")
    current = suppressed_features(mf.read_text(encoding="utf-8"))
    if body.suppressed:
        st = _read_status(ws) or {}
        feats = [f for f in st.get("features") or [] if f.get("kind") == "feature"]
        target = next((f for f in feats if f.get("name") == body.name), None)
        if target is None:
            raise HTTPException(404, "Feature not found in the current design")
        if not target.get("chain"):
            raise HTTPException(422, f"“{body.name}” can't be suppressed: it is the base feature or a separate body. "
                                     "Ask the design agent to change it instead.")
        names = [*current, body.name]
    else:
        names = [n for n in current if n != body.name]
    res = await _apply_manual(ctx, project_id, lambda fs: fs, "suppressed" if body.suppressed else "restored",
                              transform=lambda src: write_suppressed(src, names),
                              cause=f"{'Suppressed' if body.suppressed else 'Restored'} “{body.name}” (no AI)")
    return {**res, "suppressed": sorted(set(names))}


class NameIn(BaseModel):
    name: str


def _same_geometry(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    if not a or not b:
        return False
    va, vb = float(a.get("volume", 0)), float(b.get("volume", 0))
    return (abs(va - vb) <= 1e-9 * max(abs(vb), 1.0)
            and all(abs(float(x) - float(y)) <= 1e-6 for x, y in zip(a.get("bbox", []), b.get("bbox", []), strict=False))
            and all(a.get(k) == b.get(k) for k in ("faces", "edges", "solids")))


@router.post("/projects/{project_id}/design-features/delete")
async def delete_design_feature(project_id: str, body: NameIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Delete a design step without AI: remove its code, then verify the result is identical to the model with that
    step suppressed. If it isn't, nothing is deleted and the feature stays suppressed."""
    from aicad.agent.runner import managed_list, suppressed_features
    from aicad.design_edit import DesignEditError, delete_step

    p = _project(ctx, project_id)
    ws = workspace_for(p)
    mf = ws / "model.py"
    if not mf.is_file():
        raise HTTPException(404, "There is no design to change yet")
    src = mf.read_text(encoding="utf-8")
    try:
        delete_step(src, body.name)  # dry run: can this step be removed on its own?
    except DesignEditError as e:
        raise HTTPException(422, f"Can't delete without AI: {e}. Suppress it, or ask the design agent to remove it.") from None
    sup = suppressed_features(src)
    if body.name not in sup:  # reference: the same design with the step suppressed
        await _apply_manual(ctx, project_id, lambda fs: fs, "suppressed",
                            transform=lambda s: write_suppressed(s, [*sup, body.name]),
                            cause=f"Suppressed “{body.name}” (no AI), before deleting it")
    reference = (_read_status(ws) or {}).get("fingerprint")
    src_sup = mf.read_text(encoding="utf-8")
    remaining = [n for n in suppressed_features(src_sup) if n != body.name]
    deleted = [*managed_list(src_sup, "DELETED_FEATURES"), body.name]
    new_src = write_managed(delete_step(src_sup, body.name), remaining, deleted)
    try:
        res = await _apply_manual(ctx, project_id, lambda fs: fs, "deleted", transform=lambda s: new_src,
                                  cause=f"Deleted “{body.name}” (no AI; verified identical to suppressing it)")
    except HTTPException:
        raise HTTPException(409, f"“{body.name}” couldn't be removed cleanly, so it stays suppressed. "
                                 "Ask the design agent to remove it.") from None
    if not _same_geometry((_read_status(ws) or {}).get("fingerprint"), reference):
        await _apply_manual(ctx, project_id, lambda fs: fs, "kept suppressed", transform=lambda s: src_sup)
        raise HTTPException(409, f"Removing “{body.name}” changed other geometry, so it stays suppressed. "
                                 "Ask the design agent to remove it.")
    return {**res, "deleted": body.name}




def _blank(src: str) -> bool:
    """A part modelled only by hand (no design code before the manual block)."""
    head = src.split(BLOCK_START)[0]
    return "result = None  # the first boss or revolve" in head and "fw.feature(" not in head


def normalize_rollback(fs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Everything below the rollback bar (the first rolled-back feature) is rolled back."""
    bar = next((i for i, x in enumerate(fs) if x.get("rolled_back")), None)
    if bar is not None:
        for x in fs[bar:]:
            x["rolled_back"] = True
    return fs


def sync_planes(fs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep each attached sketch's stored placement equal to its reference plane's. A sketch whose plane was
    deleted keeps the last placement and is detached."""
    planes = {x["id"]: x.get("plane") for x in fs if x["op"] == "plane" and x.get("plane")}
    for x in fs:
        ref = x.get("plane_ref")
        if not ref:
            continue
        if ref in planes:
            x["plane"] = dict(planes[ref])
        else:
            x.pop("plane_ref", None)
    return fs


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
    feat = validate_feature({**body.feature, "rolled_back": False})
    bbox = _current_bbox(workspace_for(_project(ctx, project_id)))

    def mutate(fs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        bar = next((i for i, x in enumerate(fs) if x.get("rolled_back")), len(fs))
        return [*fs[:bar], *stamp_refs([feat], bbox, {feat["id"]}), *fs[bar:]]  # new features go in at the bar
    return await _apply_manual(ctx, project_id, mutate, "added", strict={feat["id"]})


class RollbackIn(BaseModel):
    before: str | None = None  # roll back to just before this feature; None = roll forward to the end


@router.post("/projects/{project_id}/manual/rollback")
async def rollback_manual(project_id: str, body: RollbackIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Move the rollback bar: features from `before` down stay in the tree but are not built (as in SOLIDWORKS).
    New features are inserted at the bar. `before = None` rolls forward to the end."""
    model = workspace_for(_project(ctx, project_id)) / "model.py"
    blank = model.is_file() and _blank(model.read_text(encoding="utf-8"))

    def mutate(fs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ids = [x["id"] for x in fs]
        if body.before is not None and body.before not in ids:
            raise HTTPException(404, "Feature not found")
        bar = ids.index(body.before) if body.before is not None else len(fs)
        if blank and not any(x["op"] not in refplane.NON_GEOMETRIC and not x.get("suppressed") for x in fs[:bar]):
            raise HTTPException(422, "This part is modelled by hand: keep its first boss above the rollback bar")
        for i, x in enumerate(fs):
            if i >= bar:
                x["rolled_back"] = True
            else:
                x.pop("rolled_back", None)
        return fs
    rolled = body.before is not None
    return await _apply_manual(ctx, project_id, mutate, "tree_rolled_back" if rolled else "tree_rolled_forward",
                               cause="Moved the rollback bar (no AI)" if rolled else "Rolled the feature tree forward to the end (no AI)")


@router.patch("/projects/{project_id}/manual/{fid}")
async def edit_manual(project_id: str, fid: str, body: FeatureIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    repicked = bool({"edges", "point", "faces", "place", "neutral"} & set(body.feature))
    bbox = _current_bbox(workspace_for(_project(ctx, project_id))) if repicked else None
    only_tree = set(body.feature) <= {"name", "suppressed"}  # rename / suppress: never reject for the feature itself

    def mutate(fs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for i, f in enumerate(fs):
            if f["id"] == fid:
                merged = {**f, **body.feature, "id": fid}
                if repicked and "edges" in body.feature and "edge_refs" not in body.feature:
                    merged.pop("edge_refs", None)  # new picks without kinds: don't keep the old ones
                new = validate_feature(merged)
                if new["name"] != f["name"] and any(x["name"] == new["name"] for x in fs if x["id"] != fid):
                    raise HTTPException(422, f"A feature named “{new['name']}” already exists")
                fs[i] = stamp_refs([new], bbox, {fid})[0] if repicked else new
                return fs
        raise HTTPException(404, "Feature not found")
    unsuppress = body.feature.get("suppressed") is False
    return await _apply_manual(ctx, project_id, mutate, "edited",  # suppressing must not break features that use it
                               strict="new" if only_tree and not unsuppress else {fid})


@router.delete("/projects/{project_id}/manual/{fid}")
async def delete_manual(project_id: str, fid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    def mutate(fs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not any(f["id"] == fid for f in fs):
            raise HTTPException(404, "Feature not found")
        users = [f["name"] for f in fs if fid in (f.get("profile"), f.get("path"), *(f.get("sections") or []))]
        if users:
            name = next(f["name"] for f in fs if f["id"] == fid)
            raise HTTPException(422, f"“{name}” is used by {', '.join(users)}. Delete or edit {users[0]} first.")
        return [f for f in fs if f["id"] != fid]
    return await _apply_manual(ctx, project_id, mutate, "deleted", strict="new")


@router.post("/projects/{project_id}/manual/reorder")
async def reorder_manual(project_id: str, body: ReorderIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    def mutate(fs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by = {f["id"]: f for f in fs}
        if sorted(body.ids) != sorted(by):
            raise HTTPException(422, "Reorder must list every feature exactly once")
        return [by[i] for i in body.ids]
    return await _apply_manual(ctx, project_id, mutate, "reordered")


@router.post("/projects/{project_id}/warm")
async def warm(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Start the project's geometry engine ahead of the first build (called when the Studio opens)."""
    import asyncio

    p = _project(ctx, project_id, "read")
    t = asyncio.create_task(worker.warm(p.org_id))
    _WARMING.add(t)
    t.add_done_callback(_WARMING.discard)
    return {"ok": True}


_WARMING: set[Any] = set()


@router.get("/holes/standards")
def hole_standards() -> dict[str, Any]:
    """Hole Wizard tables (ISO 273 clearance, tap drills, counterbores, countersinks, washers), with sources, and the
    ISO 261 thread table for cosmetic threads."""
    return {**holes.tables(), "threads": threads.tables()}


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
    p = _project(ctx, project_id, "read")
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
