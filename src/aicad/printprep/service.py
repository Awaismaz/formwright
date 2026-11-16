"""Sources (a project's verified model or an uploaded mesh), caching, analysis runs and exports.

Paths are never taken from the request: projects resolve through the platform's workspace resolver, uploads live
under `<data>/print_uploads/<org_id>/<upload_id>/` with server-generated ids.

Exports carry the build stamp of the model they were made from (`print/exports.json`, MAKE-16): an export of an
older build is listed as outdated, and file names include the model revision (`…_r2_fdm-o1.3mf`).
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from aicad import deliverables, materials
from aicad.printprep import DISCLOSURE, analysis, presets
from aicad.printprep.bvh import BVH
from aicad.printprep.mesh import (
    Mesh,
    load_npz,
    load_step,
    parse_mesh,
    save_npz,
    signed_volume,
    tessellate_shape,
    write_3mf,
    write_stl,
)
from aicad.printprep.repair import repair

UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")
EXPORT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.(stl|3mf)$")
TOL_RANGE = (0.005, 0.5)


@dataclass
class Source:
    kind: str           # "project" | "upload"
    id: str
    name: str
    root: Path          # project workspace or upload folder
    material_hint: str | None = None

    @property
    def out_dir(self) -> Path:
        d = self.root / "print"
        d.mkdir(parents=True, exist_ok=True)
        return d


# ------------------------------------------------------------------ in-memory cache of meshes and ray maps
class _Entry:
    def __init__(self, mesh: Mesh) -> None:
        self.mesh = mesh
        self.bvh = BVH(mesh.v, mesh.f)
        self.cache: dict[str, Any] = {}


_CACHE: OrderedDict[tuple[Any, ...], _Entry] = OrderedDict()
_LOCKS: dict[tuple[Any, ...], threading.Lock] = {}
_GLOBAL = threading.Lock()
_MAX = 6


def _cached(key: tuple[Any, ...], make: Any) -> _Entry:
    with _GLOBAL:
        lock = _LOCKS.setdefault(key, threading.Lock())
    with lock:
        with _GLOBAL:
            hit = _CACHE.get(key)
            if hit is not None:
                _CACHE.move_to_end(key)
                return hit
        entry = _Entry(make())
        with _GLOBAL:
            _CACHE[key] = entry
            while len(_CACHE) > _MAX:
                old, _ = _CACHE.popitem(last=False)
                _LOCKS.pop(old, None)
        return entry


def clear_cache() -> None:
    with _GLOBAL:
        _CACHE.clear()
        _LOCKS.clear()


# ------------------------------------------------------------------ projects
def project_step(src: Source) -> Path:
    p = src.root / "out" / "part.step"
    if not p.is_file():
        raise FileNotFoundError("This project has no verified model yet. Build it in the Design Studio first.")
    return p


def face_names(src: Source, mesh: Mesh) -> list[str | None] | None:
    """Feature names per exact face from the Studio's topology export, when it matches this model face for face."""
    tp = src.root / "out" / "topo.json"
    faces = mesh.meta.get("_faces")
    if not tp.is_file() or not faces:
        return None
    try:
        topo = json.loads(tp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    tf = topo.get("faces") or []
    if len(tf) != len(faces):
        return None
    for rec, fc in zip(tf[:: max(1, len(tf) // 25)], faces[:: max(1, len(tf) // 25)], strict=False):
        if abs(float(rec.get("area", 0)) - fc.area) > 1e-3 * max(1.0, fc.area):
            return None
    return [r.get("feature") for r in tf]


def _project_entry(src: Source, tol: float) -> _Entry:
    step = project_step(src)
    stt = step.stat()
    key = ("project", str(step), stt.st_mtime_ns, stt.st_size, round(tol, 6))
    return _cached(key, lambda: tessellate_shape(load_step(step), tol))


# ------------------------------------------------------------------ uploads
def uploads_root(data_dir: Path, org_id: str) -> Path:
    if not re.fullmatch(r"[0-9A-Za-z_-]{1,64}", org_id):
        raise ValueError("bad org")
    root = (data_dir / "print_uploads" / org_id).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def upload_dir(data_dir: Path, org_id: str, uid: str) -> Path | None:
    if not UPLOAD_ID.fullmatch(uid):
        return None
    d = uploads_root(data_dir, org_id) / uid
    return d if (d / "meta.json").is_file() else None


def read_meta(d: Path) -> dict[str, Any]:
    return json.loads((d / "meta.json").read_text(encoding="utf-8"))


def _write_meta(d: Path, meta: dict[str, Any]) -> None:
    tmp = d / "meta.tmp"
    tmp.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    tmp.replace(d / "meta.json")


def create_upload(data_dir: Path, org_id: str, user_id: str, filename: str, data: bytes, units: str) -> dict[str, Any]:
    mesh = parse_mesh(data, filename, units)  # raises MeshError (user-facing) before anything is stored
    uid = uuid.uuid4().hex
    d = uploads_root(data_dir, org_id) / uid
    d.mkdir()
    ext = {"stl-binary": "stl", "stl-ascii": "stl", "obj": "obj", "3mf": "3mf"}[mesh.meta["format"]]
    (d / f"original.{ext}").write_bytes(data)
    save_npz(mesh, d / "original.npz")
    save_npz(mesh, d / "mesh.npz")
    safe = re.sub(r"[^A-Za-z0-9 ._()-]", "_", Path(filename or "mesh").name)[:120] or "mesh"
    meta = {"id": uid, "name": safe, "format": mesh.meta["format"], "units": mesh.meta["units"],
            "bytes": len(data), "triangles": mesh.n_tri, "vertices": len(mesh.v),
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"), "created_by": user_id,
            "repaired": False, "repair": None, "revision": 0}
    _write_meta(d, meta)
    return meta


def list_uploads(data_dir: Path, org_id: str) -> list[dict[str, Any]]:
    root = uploads_root(data_dir, org_id)
    out = []
    for d in root.iterdir():
        if d.is_dir() and UPLOAD_ID.fullmatch(d.name) and (d / "meta.json").is_file():
            try:
                out.append(read_meta(d))
            except (OSError, ValueError):
                continue
    out.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return out


def _upload_entry(src: Source) -> _Entry:
    p = src.root / "mesh.npz"
    stt = p.stat()
    key = ("upload", str(p), stt.st_mtime_ns, stt.st_size)
    return _cached(key, lambda: load_npz(p))


def repair_upload(src: Source) -> dict[str, Any]:
    base = load_npz(src.root / "original.npz")
    fixed, report = repair(base)
    save_npz(fixed, src.root / "mesh.npz")
    meta = read_meta(src.root)
    meta.update(repaired=True, repair=report, triangles=fixed.n_tri, vertices=len(fixed.v),
                revision=int(meta.get("revision", 0)) + 1)
    _write_meta(src.root, meta)
    return report


def revert_upload(src: Source) -> None:
    base = load_npz(src.root / "original.npz")
    save_npz(base, src.root / "mesh.npz")
    meta = read_meta(src.root)
    meta.update(repaired=False, repair=None, triangles=base.n_tri, vertices=len(base.v),
                revision=int(meta.get("revision", 0)) + 1)
    _write_meta(src.root, meta)


# ------------------------------------------------------------------ analysis
def entry_for(src: Source, tol: float) -> _Entry:
    return _project_entry(src, tol) if src.kind == "project" else _upload_entry(src)


def run_analysis(src: Source, opts: dict[str, Any]) -> dict[str, Any]:
    process = opts.get("process") or "fdm"
    overrides = dict(opts.get("overrides") or {})
    if opts.get("overhang_deg") is not None:
        overrides["overhang_deg"] = opts["overhang_deg"]
    s = presets.process_settings(process, overrides)
    if opts.get("printer_mm"):
        s["printer_mm"] = [float(x) for x in opts["printer_mm"]]
        if s["printer_mm"] != presets.PROCESSES[process]["printer_mm"]:
            s["edited"].append("printer_mm")
    tol = float(opts.get("tolerance") or 0.05)
    if src.kind == "project":
        s["bed_eps_mm"] = max(0.02, 2 * tol)
    mat_code = opts.get("material") or None
    if mat_code not in presets.PROCESSES[process]["materials"]:
        mat_code = s["default_material"]
    material = presets.material(mat_code)
    entry = entry_for(src, tol)
    names = face_names(src, entry.mesh) if src.kind == "project" else None
    rep = analysis.analyse(entry.mesh, entry.bvh, s, material, opts.get("load_dir"), names, entry.cache)
    m = entry.mesh
    rep["source"] = {"kind": src.kind, "id": src.id, "name": src.name, "triangles": m.n_tri,
                     "vertices": len(m.v)}
    if src.kind == "project":
        rep["source"].update(tolerance_mm=tol, deviation=m.meta.get("deviation"),
                             exact_volume_mm3=m.meta.get("exact_volume"),
                             volume_rel_dev=m.meta.get("volume_rel_dev"),
                             mesh_volume_mm3=signed_volume(m.v, m.f))
        stl = studio_stl_check(src, entry)
        if stl:
            rep["checks"].append(stl)
            rep["summary"] = analysis.summary(rep["checks"], rep["orientations"][0] if rep["orientations"] else None)
    else:
        meta = read_meta(src.root)
        rep["source"].update(format=meta["format"], units=meta["units"], repaired=meta["repaired"],
                             repair=meta.get("repair"), revision=meta.get("revision", 0))
    cap = rep["thickness"]["cap_mm"]
    q = f"tol={tol:g}&cap={cap:g}" + (f"&rev={rep['source'].get('revision', 0)}" if src.kind == "upload" else "")
    rep["mesh_query"] = q
    rep["notes"] = presets.NOTES[process]
    rep["presets_source"] = presets.SOURCE
    rep["disclosure"] = DISCLOSURE
    rep["design_material"] = design_material(src)
    return rep


NON_PRINT_GROUPS = {"Aluminium", "Steel", "Stainless", "Cast iron", "Copper alloys", "Titanium"}


def design_material(src: Source) -> dict[str, Any] | None:
    """The material the part is designed in (project only). A metal part printed in a polymer is a form/fit model."""
    if src.kind != "project":
        return None
    code = None
    try:
        code = json.loads((src.root / ".fw" / "project.json").read_text(encoding="utf-8")).get("material")
    except (OSError, ValueError):
        pass
    text = src.material_hint or deliverables.read_status(src.root).get("material")
    m = materials.get(code) if code and code != "custom" else materials.get(materials.guess(text))
    name = (m or {}).get("name") or text
    if not name:
        return None
    metal = bool(m and m.get("group") in NON_PRINT_GROUPS)
    return {"name": name, "metal": metal,
            "note": f"Design material: {name}. A polymer print of this part is a form and fit model, not a "
                    "functional replacement." if metal else None}


def studio_stl_check(src: Source, entry: _Entry) -> dict[str, Any] | None:
    """IO-002: the Design Studio's own STL export (out/part.stl, 0.01 mm) re-read: closed, and close to the exact
    model (vertices projected onto the nearest exact face)."""
    p = src.root / "out" / "part.stl"
    faces = entry.mesh.meta.get("_faces")
    if not p.is_file() or not faces:
        return None
    key = ("stlcheck", p.stat().st_mtime_ns)
    if key in entry.cache:
        return entry.cache[key]
    try:
        stl = parse_mesh(p.read_bytes(), "part.stl", "mm")
    except Exception:  # noqa: BLE001 - reported as a failed check
        res = {"id": "PP-17", "name": "Studio STL export", "status": "fail", "value": None, "limit": None,
               "unit": "", "detail": "The exported STL could not be read back.", "level": analysis.LEVEL_GEOM,
               "limit_is_assumption": False}
        entry.cache[key] = res
        return res
    topo = analysis.topology(stl)
    dev = _deviation_to_faces(stl, entry.mesh, faces)
    ok = topo["boundary_edges"] == 0 and topo["nonmanifold_edges"] == 0 and dev <= 0.01 * 1.05 + 1e-6
    res = {"id": "PP-17", "name": "Design Studio STL export", "status": "pass" if ok else "warn", "value": dev,
           "limit": 0.01, "unit": "mm",
           "detail": (f"Re-read the Studio STL: {topo['triangles']:,} triangles, "
                      f"{'closed' if topo['boundary_edges'] == 0 else str(topo['boundary_edges']) + ' open edges'}"
                      f", max sampled deviation {dev:.4f} mm from the exact model." +
                      ("" if ok else " The Studio STL uses a relative deflection setting, so curved faces can deviate "
                       "by more than 0.01 mm. Export from this module for a controlled tolerance.")),
           "level": analysis.LEVEL_GEOM, "limit_is_assumption": False}
    entry.cache[key] = res
    return res


def _deviation_to_faces(stl: Mesh, ref: Mesh, faces: list[Any], max_samples: int = 3000) -> float:
    from OCP.BRep import BRep_Tool
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.gp import gp_Pnt
    from scipy.spatial import cKDTree

    a, b, c = (stl.v[stl.f[:, k]] for k in range(3))
    pts = np.concatenate([(a + b) / 2, (a + b + c) / 3])
    if len(pts) > max_samples:
        pts = pts[np.linspace(0, len(pts) - 1, max_samples).astype(np.int64)]
    rc, rl = _dense_samples(ref)
    _, near = cKDTree(rc).query(pts, k=min(8, len(rc)))
    near = np.atleast_2d(near)
    surfs: dict[int, Any] = {}
    worst = 0.0
    for p, nb in zip(pts, near, strict=True):
        best = np.inf
        for t in np.unique(rl[nb]).tolist():
            s = surfs.get(t)
            if s is None:
                s = surfs[t] = BRep_Tool.Surface_s(faces[t].wrapped)
            pr = GeomAPI_ProjectPointOnSurf(gp_Pnt(*map(float, p)), s)
            if pr.NbPoints() > 0:
                best = min(best, pr.LowerDistance())
        if np.isfinite(best):
            worst = max(worst, best)
    return float(worst)


def _dense_samples(ref: Mesh, budget: int = 300_000) -> tuple[np.ndarray, np.ndarray]:
    """Points on the reference mesh, labelled with their exact face, spaced so every face is sampled finely.
    Barycentric grid per triangle (interior points only, so each sample sits inside its own face)."""
    tri = ref.v[ref.f]
    edge = np.linalg.norm(tri - np.roll(tri, -1, axis=1), axis=2).max(axis=1)
    diag = float(np.linalg.norm(ref.v.max(axis=0) - ref.v.min(axis=0))) or 1.0
    h = diag / 150
    while True:
        n = np.clip(np.ceil(edge / h).astype(np.int64), 1, 60)
        if int(((n + 1) * (n + 2) // 2).sum()) <= budget or h > diag:
            break
        h *= 1.5
    pts: list[np.ndarray] = []
    lab: list[np.ndarray] = []
    for k in np.unique(n).tolist():
        sel = np.flatnonzero(n == k)
        i, j = np.meshgrid(np.arange(k + 1), np.arange(k + 1), indexing="ij")
        ok = i + j <= k
        a = (i[ok] + 1 / 3) / (k + 1)
        b = (j[ok] + 1 / 3) / (k + 1)
        w = np.stack([1 - a - b, a, b], axis=1)  # strictly inside the triangle
        p = np.einsum("sw,twc->tsc", w, tri[sel])
        pts.append(p.reshape(-1, 3))
        lab.append(np.repeat(ref.region[sel], len(w)))
    return np.concatenate(pts), np.concatenate(lab)


def mesh_binary(src: Source, tol: float, cap: float) -> bytes:
    """Viewer payload: b'FWPM' + u32 nv, nf, 0 + f32 xyz[nv] + u32 tri[nf] + f32 thickness[nf] (-1 = above cap)."""
    entry = entry_for(src, tol)
    key = ("thick", round(cap, 6))
    th = entry.cache.get(key)
    if th is None:
        th = entry.cache[key] = analysis.thickness_map(entry.mesh, entry.bvh, cap)
    m = entry.mesh
    t = np.where(np.isfinite(th), th, -1.0).astype("<f4")
    head = b"FWPM" + np.array([len(m.v), m.n_tri, 0], dtype="<u4").tobytes()
    return head + m.v.astype("<f4").tobytes() + m.f.astype("<u4").tobytes() + t.tobytes()


# ------------------------------------------------------------------ export
def check_rotation(rot: Any) -> np.ndarray:
    r = np.asarray(rot, dtype=float)
    if r.shape != (3, 3) or not np.all(np.isfinite(r)):
        raise ValueError("Rotation must be a 3 × 3 matrix")
    if np.abs(r @ r.T - np.eye(3)).max() > 1e-6 or abs(np.linalg.det(r) - 1) > 1e-6:
        raise ValueError("Rotation must be orthonormal with determinant +1")
    return r


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "part"


def source_stamp(src: Source) -> dict[str, Any]:
    """What an export records about its source: the project's build stamp plus the SHA-256 of the STEP it was
    meshed from, or the upload's revision."""
    if src.kind == "project":
        st = deliverables.build_stamp(src.root)
        step = src.root / "out" / "part.step"
        st["step_file_sha256"] = hashlib.sha256(step.read_bytes()).hexdigest() if step.is_file() else None
        return st
    return {"upload_revision": int(read_meta(src.root).get("revision", 0))}


def _current(stamp: dict[str, Any] | None, cur: dict[str, Any]) -> bool:
    if not stamp:
        return False
    if "upload_revision" in cur:
        return stamp.get("upload_revision") == cur["upload_revision"]
    if cur.get("build_id") and deliverables.same_build(stamp, cur):
        return True
    return bool(stamp.get("step_file_sha256")) and stamp.get("step_file_sha256") == cur.get("step_file_sha256")


def _exports_meta(src: Source) -> dict[str, Any]:
    try:
        return json.loads((src.root / "print" / "exports.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def export(src: Source, fmt: str, rot: np.ndarray, tol: float, printer_mm: list[float], label: str,
           tag: str) -> dict[str, Any]:
    entry = entry_for(src, tol)
    m = entry.mesh.transformed(rot)
    lo, hi = m.v.min(axis=0), m.v.max(axis=0)
    shift = np.array([printer_mm[0] / 2 - (lo[0] + hi[0]) / 2, printer_mm[1] / 2 - (lo[1] + hi[1]) / 2, -lo[2]])
    m.v = m.v + shift
    stamp = source_stamp(src)
    rev = stamp.get("model_rev") if src.kind == "project" else (stamp.get("upload_revision") or None)
    name = f"{slug(src.name)}{f'_r{rev}' if rev else ''}_{slug(tag)}.{fmt}"
    path = src.out_dir / name
    if fmt == "stl":
        write_stl(m, path, header=f"Formwright print prep, mm, {label}"[:80])
    else:
        write_3mf(m, path, title=f"{src.name} ({label})")
    back = parse_mesh(path.read_bytes(), name, "mm")  # reload: units and volume survive the round trip
    v0, v1 = signed_volume(m.v, m.f), signed_volume(back.v, back.f)
    meta = _exports_meta(src)
    meta[name] = {"stamp": stamp, "label": label,
                  "at": datetime.now(UTC).isoformat(timespec="seconds")}
    tmp = src.out_dir / "exports.json.tmp"
    tmp.write_text(json.dumps(meta, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(src.out_dir / "exports.json")
    return {"name": name, "format": fmt, "state": "current", "made_from_rev": rev, "bytes": path.stat().st_size, "triangles": m.n_tri,
            "volume_mm3": v0, "reloaded_volume_mm3": v1, "units": back.meta["units"],
            "volume_match": abs(v1 - v0) <= 1e-4 * max(abs(v0), 1.0), "label": label,
            "bbox_mm": [float(x) for x in (m.v.max(axis=0) - m.v.min(axis=0))]}


def list_exports(src: Source) -> list[dict[str, Any]]:
    """Exports, newest first, each with ``state`` current / outdated (made from another build, or before builds
    were recorded) and the model revision it came from."""
    d = src.root / "print"
    if not d.is_dir():
        return []
    meta = _exports_meta(src)
    cur = source_stamp(src) if (src.kind != "project" or (src.root / "out" / "part.step").is_file()) else {}
    out = []
    for p in d.iterdir():
        if not (p.is_file() and EXPORT_NAME.fullmatch(p.name)):
            continue
        rec = meta.get(p.name) or {}
        stamp = rec.get("stamp")
        rev = (stamp or {}).get("model_rev") if src.kind == "project" else (stamp or {}).get("upload_revision")
        out.append({"name": p.name, "bytes": p.stat().st_size, "format": p.suffix[1:], "label": rec.get("label"),
                    "modified": datetime.fromtimestamp(p.stat().st_mtime, UTC).isoformat(timespec="seconds"),
                    "state": "current" if _current(stamp, cur) else "outdated", "made_from_rev": rev,
                    "current_rev": cur.get("model_rev") if src.kind == "project" else cur.get("upload_revision")})
    out.sort(key=lambda r: r["modified"], reverse=True)
    return out


def export_summary(ws: Path, name: str = "part") -> dict[str, Any]:
    """Print exports of a project workspace for the Studio's Make tab and the release gate.

    ``state``: ``missing`` (no exports), ``stale`` (none made from the current build), else ``current``.
    ``current_files``: names of exports made from the current build (what a release may include)."""
    rows = list_exports(Source("project", "", name, ws))
    cur = [r for r in rows if r["state"] == "current"]
    n_out = len(rows) - len(cur)
    if not rows:
        return {"state": "missing", "exports": 0, "outdated": 0, "label": "No print exports", "current_files": []}
    if cur:
        label = f"{len(cur)} export{'s' if len(cur) > 1 else ''} · current" + (f" · {n_out} outdated" if n_out else "")
    else:
        label = f"Exports from model rev {rows[0]['made_from_rev'] or '—'} · outdated"
    return {"state": "current" if cur else "stale", "exports": len(rows), "outdated": n_out, "label": label,
            "current_files": [r["name"] for r in cur]}


def export_path(src: Source, name: str) -> Path | None:
    if not EXPORT_NAME.fullmatch(name):
        return None
    p = (src.root / "print" / name).resolve()
    if p.parent != (src.root / "print").resolve() or not p.is_file():
        return None
    return p
