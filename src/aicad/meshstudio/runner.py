"""Run Blender as a separate, headless, offline process (MSH-001).

Licence boundary (GPL): Formwright never imports, links or bundles Blender. We start the user-installed
`blender` executable with a generated Python script and exchange only files (inputs: a numpy array file; outputs:
PNG / .blend / GLB / OBJ / STL). This is the "separate program communicating at arm's length" use pattern; the
final legal view is pending counsel (LEG-004).

Limits: wall-clock timeout (process killed), factory settings (no user add-ons or startup files), auto-run of
scripts in .blend files disabled, Blender's offline mode (no online access), proxy variables pointed at a dead
port, a per-job working folder, and an output guard: every file Blender produced must resolve inside the job
folder, which itself must be inside the project's mesh folder.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_PATHS = [
    r"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "/usr/bin/blender",
]
_SAMPLE = re.compile(r"Sample (\d+)/(\d+)")
_FRAME = re.compile(r"FW_FRAME (\d+)/(\d+)")


class BlenderError(RuntimeError):
    """A Blender run that failed; the message is user-facing and plain."""


class BlenderTimeout(BlenderError):
    pass


def find_blender() -> Path | None:
    env = os.environ.get("FW_BLENDER")
    if env:
        return Path(env) if Path(env).is_file() else None
    for p in DEFAULT_PATHS:
        if Path(p).is_file():
            return Path(p)
    w = shutil.which("blender")
    return Path(w) if w else None


def guard_inside(path: Path, root: Path) -> Path:
    """Resolve `path` and require it to be `root` or inside it (raises ValueError otherwise)."""
    rp, rr = Path(path).resolve(), Path(root).resolve()
    if rp != rr and rr not in rp.parents:
        raise ValueError(f"Path escapes the allowed folder: {path}")
    return rp


def _env() -> dict[str, str]:
    keep = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "PATH", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
            "PROGRAMDATA", "PROGRAMFILES", "COMMONPROGRAMFILES", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
            "HOME", "LANG", "CUDA_PATH")
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    dead = "http://127.0.0.1:9"  # discard port: any stray HTTP attempt fails immediately
    env.update(HTTP_PROXY=dead, HTTPS_PROXY=dead, ALL_PROXY=dead, NO_PROXY="", PYTHONNOUSERSITE="1")
    return env


def command(blender: Path, script: Path, args: list[str]) -> list[str]:
    return [str(blender), "-b", "--factory-startup", "--disable-autoexec", "--offline-mode", "-noaudio",
            "--log", "render", "--log-level", "info",  # Cycles "Sample i/n" progress lines on stdout
            "--python-exit-code", "3", "--python", str(script), "--", *args]


def run(script: Path, job_dir: Path, allowed_root: Path, args: list[str], timeout_s: float,
        on_progress: Callable[[float, str], None] | None = None, log_name: str = "blender.log",
        blender: Path | None = None) -> dict[str, Any]:
    """Run `script` in Blender with cwd = job_dir. Returns {"seconds", "files"}; raises BlenderError/Timeout.

    Progress: Cycles "Sample i/n" lines and the script's own "FW_FRAME k/n" markers -> on_progress(0..1, phase).
    """
    job = guard_inside(job_dir, allowed_root)
    guard_inside(script, job)
    blender = blender or find_blender()
    if blender is None:
        raise BlenderError("Blender is not installed on this server, so renders are unavailable.")
    before = {p.resolve() for p in job.rglob("*")}
    t0 = time.monotonic()
    log = open(job / log_name, "w", encoding="utf-8", errors="replace")  # noqa: SIM115
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(command(blender, script, args), cwd=str(job), env=_env(), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                            errors="replace", creationflags=flags)
    timed_out = threading.Event()

    def killer() -> None:
        timed_out.set()
        try:
            proc.kill()
        except OSError:
            pass

    timer = threading.Timer(timeout_s, killer)
    timer.daemon = True
    timer.start()
    frame, frames, err = 0, 1, None
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            log.write(line)
            m = _FRAME.search(line)
            if m:
                frame, frames = int(m.group(1)), int(m.group(2))
                if on_progress:
                    on_progress(frame / frames, "rendering")
                continue
            m = _SAMPLE.search(line)
            if m and on_progress:
                s, n = int(m.group(1)), int(m.group(2))
                on_progress(min(0.999, (frame + s / max(1, n)) / frames), "rendering")
            if line.startswith("FW_ERROR"):
                err = line.strip()
        code = proc.wait()
    finally:
        timer.cancel()
        log.close()
    secs = time.monotonic() - t0
    if timed_out.is_set():
        raise BlenderTimeout(f"The render took longer than {timeout_s:.0f} s and was stopped.")
    if code != 0 or err:
        raise BlenderError("The render engine stopped with an error." + (" (output path refused)"
                                                                         if err and "output path" in err else ""))
    made = []
    for p in job.rglob("*"):
        rp = p.resolve()
        if rp in before:
            continue
        guard_inside(rp, job)  # symlinks or junctions pointing outside the job folder are refused
        made.append(rp)
    return {"seconds": round(secs, 2), "files": sorted(str(p.relative_to(job)) for p in made if p.is_file())}


_PROBE = r'''
import bpy, json
out = {"version": bpy.app.version_string, "devices": [], "backends": []}
prefs = bpy.context.preferences.addons["cycles"].preferences
for t in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
    try:
        prefs.compute_device_type = t
    except Exception:
        continue
    prefs.refresh_devices()
    devs = [d for d in prefs.devices if d.type == t]
    if devs:
        out["backends"].append(t)
        out["devices"] += [{"name": d.name, "type": d.type} for d in devs]
print("FW_PROBE " + json.dumps(out))
'''


@lru_cache(maxsize=4)
def _probe(blender: str, mtime: float) -> dict[str, Any]:
    del mtime  # cache key only (re-probe after an upgrade)
    import tempfile

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        sp = Path(td) / "probe.py"
        sp.write_text(_PROBE, encoding="utf-8")
        try:
            r = subprocess.run(command(Path(blender), sp, []), capture_output=True, text=True, timeout=90, check=False,
                               env=_env(), cwd=td, encoding="utf-8", errors="replace",
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except (OSError, subprocess.TimeoutExpired):
            return {"available": False, "reason": "Blender did not start"}
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("FW_PROBE ")), None)
    if line is None:
        return {"available": False, "reason": "Blender did not report its devices"}
    info = json.loads(line[len("FW_PROBE "):])
    backend = next((b for b in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI") if b in info["backends"]), None)
    gpu = next((d["name"] for d in info["devices"] if d["type"] == backend), None)
    return {"available": True, "version": info["version"], "backend": backend, "gpu": gpu,
            "device": "GPU" if backend else "CPU", "engine": "Cycles", "devices": info["devices"]}


def detect() -> dict[str, Any]:
    """What Blender can use here (MSH-012): Cycles on the best GPU backend (OptiX > CUDA > HIP > Metal > oneAPI),
    else Cycles on the CPU. `FW_MESH_DEVICE=CPU` forces the CPU path. Cached per Blender binary."""
    b = find_blender()
    if b is None:
        return {"available": False, "reason": "Blender is not installed on this server"}
    info = dict(_probe(str(b), b.stat().st_mtime))
    if os.environ.get("FW_MESH_DEVICE", "").upper() == "CPU" and info.get("available"):
        info.update(device="CPU", backend=None)
    return info
