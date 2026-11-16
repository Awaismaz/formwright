"""Subprocess entry point: execute an AI-written build123d script, export, check, publish.

    python -I -m aicad.agent.runner <script.py> <out_dir>

Script contract (also stated in the agent's instructions):
    result   : build123d Shape (Part / Compound / Solid) - required
    EXPECTED : optional dict, values derived from the *requirements* (hand calculation),
               not measured from the model: {"bbox": [x, y, z], "volume": mm3,
               "solids": n, "volume_tol": 0.001}
    NAME, MATERIAL, PARAMS : optional metadata

Runs in a separate process with a timeout imposed by the caller. This is NOT a security
sandbox (see RISKS R-SEC-01); the import tripwire below only catches obvious misuse.
"""

from __future__ import annotations

import ast
import json
import runpy
import sys
import time
import traceback
from pathlib import Path
from typing import Any

BLOCKED_MODULES = {
    "os", "subprocess", "socket", "shutil", "ctypes", "requests", "urllib", "http",
    "importlib", "multiprocessing", "asyncio", "ftplib", "smtplib", "pickle", "webbrowser",
}
BLOCKED_CALLS = {"eval", "exec", "__import__", "open", "compile", "input"}
STEP_TIMESTAMP = "2000-01-01T00:00:00"


class ScriptRejected(Exception):
    pass


def tripwire(source: str) -> None:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in BLOCKED_MODULES:
                    raise ScriptRejected(f"import of '{a.name}' is not allowed in model scripts")
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in BLOCKED_MODULES:
            raise ScriptRejected(f"import from '{node.module}' is not allowed in model scripts")
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in BLOCKED_CALLS):
            raise ScriptRejected(f"call to '{node.func.id}()' is not allowed in model scripts")


def _exec(script: Path) -> dict[str, Any]:
    ns = runpy.run_path(str(script), run_name="__aicad_model__")
    if "result" not in ns:
        raise ScriptRejected("script must assign the final build123d shape to a variable named `result`")
    return ns


def _write(out: Path, status: dict[str, Any]) -> None:
    import os
    import tempfile

    status["build_id"] = time.time_ns()
    fd, tmp = tempfile.mkstemp(dir=out, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, default=str)
    os.replace(tmp, out / "status.json")


def main(script: Path, out: Path) -> int:
    import hashlib
    import os
    import tempfile

    from build123d import Shape, export_gltf, export_step, export_stl, import_step

    from aicad import checks

    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    status: dict[str, Any] = {"ok": False, "script": script.name, "checks": []}
    try:
        tripwire(script.read_text(encoding="utf-8"))
        ns = _exec(script)
        shape = ns["result"]
        if not isinstance(shape, Shape):
            raise ScriptRejected(f"`result` is {type(shape).__name__}, expected a build123d Shape")
        t_build = time.perf_counter() - t0
        exp: dict[str, Any] = dict(ns.get("EXPECTED") or {})

        def export_atomic(fn: Any, s: Shape, name: str, **kw: Any) -> Path:
            p = out / name
            tmp = out / (p.stem + ".tmp" + p.suffix)
            if not fn(s, str(tmp), **kw):
                raise RuntimeError(f"export failed: {name}")
            os.replace(tmp, p)
            return p

        step = export_atomic(export_step, shape, "part.step", timestamp=STEP_TIMESTAMP)
        reimported = import_step(str(step))
        export_atomic(export_stl, reimported, "part.stl", tolerance=0.01)

        results: list[checks.CheckResult] = []
        n_solids = len(shape.solids())
        exp_solids = exp.get("solids")
        results.append(checks.CheckResult(
            "CHK-02", "valid B-rep, solid count",
            bool(shape.is_valid) and n_solids > 0 and (exp_solids is None or n_solids == exp_solids),
            detail={"is_valid": shape.is_valid, "solids": n_solids, "expected": exp_solids}))
        fe = checks.free_edge_count(shape)
        results.append(checks.CheckResult("CHK-03", "closed manifold (no free edges)", fe == 0,
                                          detail={"free_or_nonmanifold_edges": fe}))
        if "bbox" in exp:
            results.append(checks.check_bbox(shape, tuple(exp["bbox"])))  # type: ignore[arg-type]
        else:
            results.append(checks.CheckResult("CHK-04", "bounding box (no expectation given)",
                                              False, gating=False,
                                              detail={"got_mm": checks.bbox_size(shape)}))
        if "volume" in exp:
            r = checks.check_volume(shape, float(exp["volume"]))
            tol = float(exp.get("volume_tol", checks.VOLUME_REL_TOL))
            r.passed = r.detail["rel_err"] <= tol
            r.detail["tol"] = tol
            results.append(r)
        else:
            results.append(checks.CheckResult("CHK-05", "volume (no expectation given)", False,
                                              gating=False, detail={"got_mm3": shape.volume}))
        results.append(checks.check_roundtrip(shape, reimported))

        ns2 = _exec(script)
        same_fp = checks.fingerprint(ns2["result"]) == checks.fingerprint(shape)
        with tempfile.TemporaryDirectory() as td:
            p2 = Path(td) / "p2.step"
            export_step(ns2["result"], str(p2), timestamp=STEP_TIMESTAMP)
            same_step = p2.read_bytes() == step.read_bytes()
        results.append(checks.CheckResult("CHK-08", "deterministic regeneration",
                                          same_fp and same_step,
                                          detail={"fingerprint_equal": same_fp,
                                                  "step_bytes_equal": same_step}))

        export_atomic(export_gltf, reimported, "model.glb", binary=True,
                      linear_deflection=0.01, angular_deflection=0.1)
        status.update(
            ok=all(r.passed for r in results if r.gating),
            part=ns.get("NAME", script.stem), material=ns.get("MATERIAL", "unspecified"),
            params=ns.get("PARAMS", {}), expected=exp,
            fingerprint=checks.fingerprint(shape),
            step_sha256=hashlib.sha256(step.read_bytes()).hexdigest(),
            checks=checks.as_dicts(results),
            timings_s={"build_s": round(t_build, 3), "total_s": round(time.perf_counter() - t0, 3)},
            viewer_mesh_source="re-imported part.step",
            env={"build123d": _ver("build123d"), "cadquery-ocp": _ver("cadquery-ocp", "cadquery_ocp")},
        )
    except ScriptRejected as e:
        status.update(error=f"rejected: {e}")
    except Exception as e:  # noqa: BLE001 - report any script/kernel failure to the agent
        tb = traceback.format_exc(limit=6)
        status.update(error=f"{type(e).__name__}: {e}", traceback=tb[-3000:])
    _write(out, status)
    return 0 if status.get("ok") else 1


def _ver(*names: str) -> str:
    from importlib.metadata import PackageNotFoundError, version

    for n in names:
        try:
            return version(n)
        except PackageNotFoundError:
            continue
    return "unknown"


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()))
