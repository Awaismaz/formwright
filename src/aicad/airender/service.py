"""AI Render jobs on a project: reference-image choice, background generation, gallery, files.

Layout:  <workspace>/airender/<job id>/job.json     settings, prompt sent, reference used, usage, state
                                        ref.png      the reference image actually sent (resized copy)
                                        out_<n>.png  results (PNG text chunks carry the caption)
                                        thumb_<n>.jpg
The API key is handed to the worker in memory and never written to job.json. Paths never come from the request:
job ids are generated hex, reference ids are looked up from the candidate list, file names match a fixed pattern.
"""

from __future__ import annotations

import io
import re
import secrets
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PIL import Image, PngImagePlugin

from aicad.airender import CAPTION, options, provider, refine
from aicad.meshstudio import jobs as mesh_jobs

JOB_ID = re.compile(r"^[0-9a-f]{16}$")
FILE_RE = re.compile(r"^(?:out_[1-9]\.png|thumb_[1-9]\.jpg|ref\.png)$")
REF_MAX_PX = 1536
MAX_ACTIVE_PER_ORG = 3
KEEP_JOBS = 60

_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="airender")
_LIVE: dict[str, str] = {}  # job id -> org id, while queued or running
_LOCK = threading.Lock()


class Busy(RuntimeError):
    pass


def root(ws: Path) -> Path:
    d = ws / "airender"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------ reference images
def references(ws: Path) -> list[dict[str, Any]]:
    """Candidate references, best first: Mesh Studio final renders, then previews (both Cycles renders of the exact
    model), then the build's own thumbnail, then the 2x2 views sheet."""
    out: list[dict[str, Any]] = []
    for sub, label, kind in (("renders", "Mesh Studio render", "mesh_final"),
                             ("previews", "Mesh Studio preview", "mesh_preview")):
        base = ws / "mesh" / sub
        rows = []
        for d in base.iterdir() if base.is_dir() else []:
            j = mesh_jobs.read_job(d) or {}
            if j.get("state") == "done" and (d / "render.png").is_file() and JOB_ID.fullmatch(d.name):
                rows.append((j.get("finished_at") or "", d, j))
        for fin, d, j in sorted(rows, key=lambda r: r[0], reverse=True)[:3]:
            out.append({"id": f"{kind}-{d.name}", "kind": kind, "label": label,
                        "detail": j.get("label") or "", "at": fin, "path": d / "render.png",
                        "build_id": j.get("build_id")})
    for name, label in (("thumb.png", "Model thumbnail"), ("views.png", "Model views sheet")):
        f = ws / "out" / name
        if f.is_file():
            out.append({"id": name.split(".")[0], "kind": "model", "label": label, "detail": "From the verified build",
                        "at": None, "path": f, "build_id": None})
    return out


def reference(ws: Path, ref_id: str | None) -> dict[str, Any] | None:
    refs = references(ws)
    if ref_id:
        return next((r for r in refs if r["id"] == ref_id), None)
    return refs[0] if refs else None


def public_ref(r: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in r.items() if k != "path"}


def _prepare_ref(src: Path, dst: Path, transparent: bool) -> None:
    """Resize to at most REF_MAX_PX and save as PNG (keep alpha only for transparent output)."""
    with Image.open(src) as im:
        im.load()
        im = im.convert("RGBA")
        if not transparent:
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            bg.alpha_composite(im)
            im = bg.convert("RGB")
        im.thumbnail((REF_MAX_PX, REF_MAX_PX), Image.Resampling.LANCZOS)
        im.save(dst, "PNG", optimize=True)


# ------------------------------------------------------------------ jobs
def _find(ws: Path, jid: str) -> Path | None:
    if not JOB_ID.fullmatch(jid or ""):
        return None
    d = ws / "airender" / jid
    return d if (d / "job.json").is_file() else None


def view(d: Path, job: dict[str, Any] | None = None, base_url: str = "") -> dict[str, Any]:
    job = job or mesh_jobs.read_job(d) or {}
    jid = job.get("id", d.name)
    state = job.get("state", "failed")
    if state in ("queued", "running") and jid not in _LIVE:
        state = "failed"
        job["error"] = job.get("error") or "Interrupted (the server restarted). Generate it again."
    images = []
    for i, name in enumerate(job.get("outputs") or [], start=1):
        if (d / name).is_file():
            images.append({"index": i, "url": f"{base_url}/{jid}/files/{name}",
                           "thumb": f"{base_url}/{jid}/files/thumb_{i}.jpg" if (d / f"thumb_{i}.jpg").is_file()
                           else f"{base_url}/{jid}/files/{name}"})
    out = {k: job.get(k) for k in ("id", "created_at", "started_at", "finished_at", "seconds", "settings", "prompt", "sent_prompt",
                                   "negative", "engine", "reference", "model", "usage", "error", "error_code",
                                   "variation_of", "eta_s", "build_id")}
    out.update(state=state, images=images, caption=CAPTION,
               reference_url=f"{base_url}/{jid}/files/ref.png" if (d / "ref.png").is_file() else None)
    return out


def list_jobs(ws: Path, base_url: str = "") -> list[dict[str, Any]]:
    base = ws / "airender"
    rows = []
    for d in base.iterdir() if base.is_dir() else []:
        j = mesh_jobs.read_job(d) if JOB_ID.fullmatch(d.name) else None
        if j:
            rows.append((j.get("created_at") or "", d, j))
    return [view(d, j, base_url) for _, d, j in sorted(rows, key=lambda r: r[0], reverse=True)]


def job_view(ws: Path, jid: str, base_url: str = "") -> dict[str, Any] | None:
    d = _find(ws, jid)
    return view(d, None, base_url) if d else None


def file_path(ws: Path, jid: str, name: str) -> Path | None:
    d = _find(ws, jid)
    if d is None or not FILE_RE.fullmatch(name or ""):
        return None
    f = d / name
    return f if f.is_file() else None


def delete_job(ws: Path, jid: str) -> bool:
    d = _find(ws, jid)
    if d is None:
        return False
    if jid in _LIVE:
        raise RuntimeError("This render is still being generated.")
    shutil.rmtree(d, ignore_errors=True)
    return True


def _prune(ws: Path) -> None:
    base = ws / "airender"
    rows = []
    for d in base.iterdir() if base.is_dir() else []:
        j = mesh_jobs.read_job(d) if JOB_ID.fullmatch(d.name) else None
        if j and d.name not in _LIVE:
            rows.append((j.get("created_at") or "", d))
    for _, d in sorted(rows, reverse=True)[KEEP_JOBS:]:
        shutil.rmtree(d, ignore_errors=True)


def submit(ws: Path, *, key: str, settings: options.Settings, prompt: str, negative: list[str], engine: str,
           ref: dict[str, Any], org_id: str, user_id: str, build_id: Any = None,
           variation_of: dict[str, Any] | None = None, base_url: str = "") -> dict[str, Any]:
    """Queue one generation (n = settings.variants images). Raises Busy when the workspace has too many running."""
    with _LOCK:
        if sum(1 for o in _LIVE.values() if o == org_id) >= MAX_ACTIVE_PER_ORG:
            raise Busy(f"Your workspace already has {MAX_ACTIVE_PER_ORG} AI renders in progress. Wait for one to "
                       "finish.")
        jid = secrets.token_hex(8)
        _LIVE[jid] = org_id
    try:
        d = root(ws) / jid
        d.mkdir(parents=True)
        _prepare_ref(ref["path"], d / "ref.png", settings.background == "transparent")
        extra: list[Path] = []
        if variation_of:
            prev = file_path(ws, variation_of["job"], f"out_{int(variation_of['index'])}.png")
            if prev is not None:
                shutil.copy2(prev, d / "var.png")
                extra.append(d / "var.png")
        sent = refine.guarded(prompt, negative)
        if variation_of and extra:
            sent += ("\n\nThe second image is an earlier AI render of this part: make a variation of it (new "
                     "composition details), while the first image remains the authority for the geometry.")
        job = {"id": jid, "org": org_id, "created_by": user_id, "state": "queued", "created_at": mesh_jobs.now(),
               "settings": settings.dict(), "prompt": prompt, "negative": negative, "sent_prompt": sent,
               "engine": engine, "reference": public_ref(ref), "model": options.model(),
               "variation_of": variation_of if extra else None, "build_id": build_id,
               "eta_s": options.QUALITIES[settings.quality]["eta_s"] * (1 + 0.35 * (settings.variants - 1))}
        mesh_jobs.write_job(d, job)
    except Exception:
        with _LOCK:
            _LIVE.pop(jid, None)
        raise
    images = [d / "ref.png", *extra]
    _POOL.submit(_run, ws, d, key, images, user_id)
    _prune(ws)
    return view(d, job, base_url)


def _save_png(data: bytes, dst: Path, thumb: Path, model: str) -> None:
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        info = PngImagePlugin.PngInfo()
        info.add_text("Description", CAPTION)
        info.add_text("Software", f"Formwright AI Render Studio ({model} via the workspace's OpenAI key)")
        im.save(dst, "PNG", pnginfo=info)
        t = im.convert("RGBA")
        bg = Image.new("RGBA", t.size, (255, 255, 255, 255))
        bg.alpha_composite(t)
        t = bg.convert("RGB")
        t.thumbnail((512, 512), Image.Resampling.LANCZOS)
        t.save(thumb, "JPEG", quality=85)


def _run(ws: Path, d: Path, key: str, images: list[Path], user_id: str) -> None:
    job = mesh_jobs.read_job(d) or {}
    t0 = time.monotonic()
    try:
        job.update(state="running", started_at=mesh_jobs.now())
        mesh_jobs.write_job(d, job)
        s = job["settings"]
        datas, meta = provider.edit(key, images, job["sent_prompt"], model=job["model"], size=s["size"],
                                    quality=s["quality"], background=s["background"], n=int(s["variants"]),
                                    user_tag=user_id)
        outs = []
        for i, data in enumerate(datas[:options.MAX_VARIANTS], start=1):
            _save_png(data, d / f"out_{i}.png", d / f"thumb_{i}.jpg", job["model"])
            outs.append(f"out_{i}.png")
        job.update(state="done", outputs=outs, usage=meta.get("usage"), revised_prompts=meta.get("revised_prompts"),
                   size=meta.get("size"))
    except provider.RenderError as e:
        job.update(state="failed", error=e.message, error_code=e.code)
    except Exception:  # noqa: BLE001
        job.update(state="failed", error="The AI render failed unexpectedly. Try again.", error_code="unknown")
    finally:
        job.update(finished_at=mesh_jobs.now(), seconds=round(time.monotonic() - t0, 1))
        (d / "var.png").unlink(missing_ok=True)
        mesh_jobs.write_job(d, job)
        with _LOCK:
            _LIVE.pop(job.get("id", d.name), None)


def wait_idle(timeout: float = 10.0) -> None:
    """Tests: block until no job is queued or running."""
    end = time.monotonic() + timeout
    while _LIVE and time.monotonic() < end:
        time.sleep(0.02)
