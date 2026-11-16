"""Mesh Studio jobs on a project: renders (preview / final / turntable) and mesh exports, cached by
(verified build content, preset hash), run in the background queue, stored under `<workspace>/mesh/`.

Layout:  mesh/geom/<sha>.npz|json        visualisation mesh + checks, one per verified STEP content
         mesh/previews/<id>/               quick previews (pruned to the newest few)
         mesh/renders/<id>/                gallery: final stills and turntables (+ editable .blend)
         mesh/exports/<id>/                GLB / OBJ / STL visualisation meshes
Paths never come from the request: ids are hex hashes we generate, file names are checked against a fixed list.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from aicad.meshstudio import DISCLOSURE, VERSION, geometry, jobs, post, presets, runner, scene

KIND_DIR = {"preview": "previews", "final": "renders", "turntable": "renders", "export": "exports"}
TIMEOUTS = {"preview": 420.0, "final": 1200.0, "turntable": 3600.0, "export": 300.0}
KEEP_PREVIEWS = 12
JOB_ID = re.compile(r"^[0-9a-f]{16}$")
FILES = {"render.png": "image/png", "thumb.jpg": "image/jpeg", "scene.blend": "application/x-blender",
         "turntable.gif": "image/gif", "turntable.mp4": "video/mp4", "part.glb": "model/gltf-binary",
         "part_obj.zip": "application/zip", "part.stl": "model/stl"}
_GEOM_LOCK = threading.Lock()


def mesh_root(ws: Path) -> Path:
    d = ws / "mesh"
    d.mkdir(parents=True, exist_ok=True)
    return d


def project_step(ws: Path) -> Path:
    p = ws / "out" / "part.step"
    if not p.is_file():
        raise FileNotFoundError("This project has no verified model yet. Build it in the Design Studio first.")
    return p


def build_info(ws: Path) -> dict[str, Any]:
    try:
        st = json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    return {"build_id": st.get("build_id"), "material": st.get("material"), "ok": st.get("ok")}


def geometry_for(ws: Path) -> dict[str, Any]:
    step = project_step(ws)
    with _GEOM_LOCK:
        return geometry.build_geometry(step, mesh_root(ws) / "geom")


def _hull_mm(npz: Path) -> np.ndarray:
    return geometry.hull_points(npz, np.eye(3), np.zeros(3)) * 1000.0


# ------------------------------------------------------------------ job records
def _find(ws: Path, jid: str) -> Path | None:
    if not JOB_ID.fullmatch(jid or ""):
        return None
    for sub in ("renders", "previews", "exports"):
        d = ws / "mesh" / sub / jid
        if (d / "job.json").is_file():
            return d
    return None


def view(ws: Path, d: Path, job: dict[str, Any] | None = None, base_url: str = "") -> dict[str, Any]:
    """The client view of a job: no paths, plus download URLs and queue position."""
    job = job or jobs.read_job(d) or {}
    state = job.get("state", "failed")
    if state in jobs.ACTIVE and not jobs.QUEUE.is_live(job.get("id", "")):
        state = "failed"
        job["error"] = job.get("error") or "Interrupted (the server restarted). Render it again."
    files = {}
    for name in FILES:
        if (d / name).is_file():
            files[name] = {"url": f"{base_url}/{job.get('id')}/files/{name}", "bytes": (d / name).stat().st_size}
    out = {k: job.get(k) for k in ("id", "kind", "options", "created_at", "started_at", "finished_at", "seconds",
                                   "render_seconds", "progress", "phase", "error", "device", "label", "size",
                                   "build_id", "cached", "triangles")}
    out.update(state=state, files=files, disclosure=DISCLOSURE)
    if state == "queued":
        out["queue_position"] = jobs.QUEUE.position(job.get("id", ""))
    return out


def label_for(opts: scene.Options) -> str:
    f = presets.FINISHES[opts.finish]
    colour = opts.key()["colour"]
    cname = f["colours"][colour][0] if colour and f.get("colours") else None
    finish = f["label"] + (f", {cname.lower()}" if cname else "")
    return f"{finish} · {presets.LIGHTING[opts.lighting]['label']} · {presets.CAMERAS[opts.camera]['label']}"


def request_render(ws: Path, name: str, opts: scene.Options, org_id: str, user_id: str,
                   base_url: str = "") -> dict[str, Any]:
    """Queue a render (or return the cached / in-flight one with the same build and presets)."""
    opts.validate()
    dev = runner.detect()
    if not dev.get("available"):
        raise runner.BlenderError("Rendering isn't available on this server (Blender is not installed).")
    step = project_step(ws)
    sha = geometry.file_sha(step)[:20]
    kind = opts.quality
    key = scene.spec_hash({"v": VERSION, "geom": sha, "opts": opts.key(), "dev": dev["device"]})[:16]
    return _enqueue(ws, kind, key, {"options": opts.key(), "label": label_for(opts)}, org_id, user_id, base_url,
                    lambda d, j: _execute_render(ws, d, j, name, opts, dev))


def request_export(ws: Path, name: str, finish: str, colour: str | None, org_id: str, user_id: str,
                   base_url: str = "") -> dict[str, Any]:
    opts = scene.Options(finish=finish, colour=colour).validate()
    dev = runner.detect()
    if not dev.get("available"):
        raise runner.BlenderError("Exports aren't available on this server (Blender is not installed).")
    sha = geometry.file_sha(project_step(ws))[:20]
    colour = opts.key()["colour"]
    key = scene.spec_hash({"v": VERSION, "geom": sha, "export": [finish, colour]})[:16]
    label = presets.FINISHES[finish]["label"] + (f", {presets.FINISHES[finish]['colours'][colour][0].lower()}"
                                                 if colour else "")
    return _enqueue(ws, "export", key, {"options": {"finish": finish, "colour": colour}, "label": label}, org_id,
                    user_id, base_url, lambda d, j: _execute_export(ws, d, j, name, finish, colour))


def _enqueue(ws: Path, kind: str, key: str, extra: dict[str, Any], org_id: str, user_id: str, base_url: str,
             run: Any) -> dict[str, Any]:
    d = mesh_root(ws) / KIND_DIR[kind] / key
    old = jobs.read_job(d) if d.is_dir() else None
    if old and old.get("state") == "done" and all((d / f).is_file() for f in old.get("outputs", [])):
        old["cached"] = True
        return view(ws, d, old, base_url)
    if old and old.get("state") in jobs.ACTIVE and jobs.QUEUE.is_live(key):
        return view(ws, d, old, base_url)
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    job = {"id": key, "kind": kind, "state": "queued", "progress": 0.0, "phase": "Waiting in the queue",
           "created_at": jobs.now(), "created_by": user_id, "org": org_id, "build_id": build_info(ws)["build_id"],
           **extra}
    jobs.write_job(d, job)
    try:
        jobs.QUEUE.submit(d, job, run)
    except jobs.QueueFull:
        shutil.rmtree(d, ignore_errors=True)
        raise
    if kind == "preview":
        _prune(mesh_root(ws) / "previews", keep=KEEP_PREVIEWS, protect=key)
    return view(ws, d, job, base_url)


def _prune(root: Path, keep: int, protect: str) -> None:
    items = []
    for d in root.iterdir() if root.is_dir() else []:
        j = jobs.read_job(d)
        if j and j.get("state") not in jobs.ACTIVE and d.name != protect:
            items.append((j.get("created_at", ""), d))
    items.sort(reverse=True)
    for _, d in items[max(0, keep - 1):]:
        shutil.rmtree(d, ignore_errors=True)


class _Progress:
    """Throttled job.json progress writer (Blender reports many sample lines per second)."""

    def __init__(self, d: Path, job: dict[str, Any], lo: float, hi: float) -> None:
        self.d, self.job, self.lo, self.hi, self.t = d, job, lo, hi, 0.0

    def __call__(self, frac: float, phase: str) -> None:
        now = time.monotonic()
        if now - self.t < 0.4 and frac < 1:
            return
        self.t = now
        self.job["progress"] = round(self.lo + (self.hi - self.lo) * frac, 4)
        self.job["phase"] = "Rendering"
        jobs.write_job(self.d, self.job)


def _update(d: Path, job: dict[str, Any], **kw: Any) -> None:
    job.update(kw)
    jobs.write_job(d, job)


def _fail(d: Path, job: dict[str, Any], e: Exception) -> None:
    msg = str(e) if isinstance(e, runner.BlenderError | FileNotFoundError | ValueError) else \
        "The render failed on this model."
    _update(d, job, state="failed", error=msg, finished_at=jobs.now())


def _meta(job: dict[str, Any], name: str, geom: dict[str, Any]) -> dict[str, Any]:
    return {"Title": f"{name} (visualisation render)", "Formwright-Finish": job.get("label", ""),
            "Formwright-Mesh": f"{geom['triangles']} triangles, chordal tolerance {geom['tolerance_mm']} mm"}


def _execute_render(ws: Path, d: Path, job: dict[str, Any], name: str, opts: scene.Options,
                    dev: dict[str, Any]) -> None:
    t0 = time.monotonic()
    try:
        _update(d, job, state="running", phase="Preparing the visualisation mesh", started_at=jobs.now(),
                progress=0.01)
        geom = geometry_for(ws)
        npz = mesh_root(ws) / "geom" / geom["file"]
        kind = opts.quality
        outputs: dict[str, Any] = {"image": "raw.png"}
        if kind == "final":
            outputs["blend"] = "scene.blend"
        if kind == "turntable":
            outputs = {"frames_dir": "frames", "blend": "scene.blend"}
        spec = scene.build_spec(geom, _hull_mm(npz), opts, dev, name, outputs)
        (d / "spec.json").write_text(json.dumps(spec, indent=1, sort_keys=True), encoding="utf-8")
        (d / "scene.py").write_text(scene.build_script(spec), encoding="utf-8")
        _update(d, job, phase="Starting the renderer", progress=0.03, triangles=geom["triangles"],
                device={"engine": "Cycles", "device": spec["render"]["device"], "backend": spec["render"]["backend"],
                        "gpu": dev.get("gpu") if spec["render"]["device"] == "GPU" else None,
                        "samples": spec["render"]["samples"]}, size=spec["render"]["res"])
        hi = 0.85 if kind == "turntable" else 0.97
        res = runner.run(d / "scene.py", d, mesh_root(ws), [str(d), str(npz)], TIMEOUTS[kind],
                         on_progress=_Progress(d, job, 0.04, hi))
        meta = _meta(job, name, geom)
        bg = spec["post"]["background"]
        made = ["render.png", "thumb.jpg"]
        if kind == "turntable":
            _update(d, job, phase="Encoding the turntable", progress=0.87)
            frames = sorted((d / "frames").glob("f_*.png"))
            for f in frames:
                post.finish_frame(f, f, bg, meta)
            post.gif(frames, d / "turntable.gif", spec["turntable"]["fps"])
            shutil.copyfile(frames[0], d / "render.png")
            made += ["turntable.gif", "scene.blend"]
            try:
                _encode_mp4(ws, d, spec["turntable"]["fps"])
                made.append("turntable.mp4")
            except runner.BlenderError:
                pass  # the GIF and frames still stand; MP4 is a convenience
        else:
            post.finish_frame(d / "raw.png", d / "render.png", bg, meta)
            (d / "raw.png").unlink(missing_ok=True)
            if kind == "final":
                made.append("scene.blend")
        post.thumbnail(d / "render.png", d / "thumb.jpg")
        _update(d, job, state="done", progress=1.0, phase="Done", finished_at=jobs.now(),
                seconds=round(time.monotonic() - t0, 2), render_seconds=res["seconds"], outputs=made)
    except Exception as e:  # noqa: BLE001
        _fail(d, job, e)


def _encode_mp4(ws: Path, d: Path, fps: int) -> None:
    shutil.copyfile(scene.TEMPLATE.with_name("blender_encode.py"), d / "encode.py")
    runner.run(d / "encode.py", d, mesh_root(ws), [str(d), str(fps)], 300, log_name="encode.log")
    vids = sorted(d.glob("turntable_*.mp4"))
    if not vids:
        raise runner.BlenderError("No video was written")
    vids[0].replace(d / "turntable.mp4")


def _execute_export(ws: Path, d: Path, job: dict[str, Any], name: str, finish: str, colour: str | None) -> None:
    t0 = time.monotonic()
    try:
        _update(d, job, state="running", phase="Preparing the visualisation mesh", started_at=jobs.now(),
                progress=0.05)
        geom = geometry_for(ws)
        npz = mesh_root(ws) / "geom" / geom["file"]
        spec = scene.export_spec(name, finish, colour, {"glb": "part.glb", "obj": "part.obj", "stl": "part.stl"})
        (d / "spec.json").write_text(json.dumps(spec, indent=1, sort_keys=True), encoding="utf-8")
        (d / "scene.py").write_text(scene.build_script(spec), encoding="utf-8")
        _update(d, job, phase="Exporting meshes", progress=0.3, triangles=geom["triangles"])
        res = runner.run(d / "scene.py", d, mesh_root(ws), [str(d), str(npz)], TIMEOUTS["export"])
        _label_stl(d / "part.stl")
        note = f"# Formwright Mesh Studio: {DISCLOSURE}\n# Units: millimetres. Z up.\n"
        objp = d / "part.obj"
        objp.write_text(note + objp.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        with zipfile.ZipFile(d / "part_obj.zip", "w", zipfile.ZIP_DEFLATED) as zf:
            for f in ("part.obj", "part.mtl"):
                if (d / f).is_file():
                    zi = zipfile.ZipInfo(f, date_time=(2020, 1, 1, 0, 0, 0))
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    zf.writestr(zi, (d / f).read_bytes())
        (d / "README.txt").write_text(
            f"{name}: visualisation meshes from Formwright Mesh Studio.\n\n{DISCLOSURE}\n\n"
            f"part.glb  glTF 2.0 binary, metres, Y up (glTF convention), flat PBR material\n"
            f"part_obj.zip  OBJ + MTL, millimetres, Z up\npart.stl  binary STL, millimetres, Z up\n"
            f"Tessellation: {geom['triangles']:,} triangles, chordal tolerance {geom['tolerance_mm']} mm.\n",
            encoding="utf-8")
        _update(d, job, state="done", progress=1.0, phase="Done", finished_at=jobs.now(),
                seconds=round(time.monotonic() - t0, 2), render_seconds=res["seconds"],
                outputs=["part.glb", "part_obj.zip", "part.stl"])
    except Exception as e:  # noqa: BLE001
        _fail(d, job, e)


def _label_stl(p: Path) -> None:
    """Replace the binary STL's 80-byte header with our labelling (binary STL headers are free text)."""
    if not p.is_file():
        raise runner.BlenderError("The STL export was not written")
    data = bytearray(p.read_bytes())
    head = b"Formwright Mesh Studio visualisation mesh, mm. Not the exact model."[:80].ljust(80, b" ")
    data[:80] = head
    p.write_bytes(bytes(data))


# ------------------------------------------------------------------ listing, files, delete
def list_jobs(ws: Path, base_url: str) -> dict[str, Any]:
    out: dict[str, list[dict[str, Any]]] = {"renders": [], "exports": [], "previews": []}
    for sub, items in out.items():
        root = ws / "mesh" / sub
        if not root.is_dir():
            continue
        for d in root.iterdir():
            j = jobs.read_job(d)
            if j:
                items.append(view(ws, d, j, base_url))
        items.sort(key=lambda v: v.get("created_at") or "", reverse=True)
    return out


def job_view(ws: Path, jid: str, base_url: str) -> dict[str, Any] | None:
    d = _find(ws, jid)
    return view(ws, d, None, base_url) if d else None


def file_path(ws: Path, jid: str, name: str) -> Path | None:
    if name not in FILES:
        return None
    d = _find(ws, jid)
    if d is None:
        return None
    p = d / name
    if not p.is_file():
        return None
    return runner.guard_inside(p, ws / "mesh")


def delete_job(ws: Path, jid: str) -> bool:
    d = _find(ws, jid)
    if d is None:
        return False
    j = jobs.read_job(d) or {}
    if j.get("state") in jobs.ACTIVE and jobs.QUEUE.is_live(jid) and not jobs.QUEUE.cancel(jid):
        raise RuntimeError("This render is running; wait for it to finish.")
    shutil.rmtree(d, ignore_errors=True)
    return True
