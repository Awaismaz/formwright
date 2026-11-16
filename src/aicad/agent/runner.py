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
import sys
import tempfile
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


MANUAL_START = "# --- Formwright manual features"
_BASE_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_MAX = 6
_LAST: dict[str, dict[str, Any]] = {}  # out dir -> {"shape", "ns_meta"} for deferred finalize


def _manual_block(source: str) -> tuple[str, list[dict[str, Any]]]:
    """Split model source into (agent base source, manual feature list)."""
    if MANUAL_START not in source:
        return source, []
    i = source.index(MANUAL_START)
    block = source[i:]
    feats: list[dict[str, Any]] = []
    for node in ast.parse(block).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "MANUAL_FEATURES":
            feats = list(ast.literal_eval(node.value))
    return source[:i], feats


def _exec(script: Path, use_cache: bool = False) -> dict[str, Any]:
    """Run a model script. Its folder is importable (helper modules), and anything imported from that
    folder is purged afterwards so a warm worker never serves stale helpers to the next build.
    With use_cache, the agent-authored base geometry is reused when only manual features changed."""
    import hashlib

    folder = str(script.parent.resolve())
    source = script.read_text(encoding="utf-8")
    base_src, manual = _manual_block(source)
    helpers = sorted(f for f in script.parent.glob("*.py") if f.resolve() != script.resolve())
    for f in helpers:
        tripwire(f.read_text(encoding="utf-8"))
    from aicad import fw

    fw.reset()
    fw.set_base(script.parent)
    key = hashlib.sha256((folder + "\0" + base_src + "".join(f.read_text(encoding="utf-8") for f in helpers))
                         .encode()).hexdigest()
    cached = _BASE_CACHE.get(key) if use_cache else None
    if cached is not None:
        ns = dict(cached["ns"])
        fw._STATE["log"] = list(cached["log"])
    else:
        sys.path.insert(0, folder)
        try:
            ns = {"__name__": "__aicad_model__", "__file__": str(script), "__builtins__": __builtins__}
            exec(compile(base_src, str(script), "exec"), ns)  # noqa: S102 - model scripts are tripwired above
        finally:
            if sys.path and sys.path[0] == folder:
                sys.path.pop(0)
            for name, mod in list(sys.modules.items()):
                f = getattr(mod, "__file__", None)
                if f and str(Path(f).resolve()).startswith(folder):
                    del sys.modules[name]
        if "result" not in ns:
            raise ScriptRejected("script must assign the final build123d shape to a variable named `result`")
        _BASE_CACHE[key] = {"ns": dict(ns), "log": fw.log()}
        while len(_BASE_CACHE) > _CACHE_MAX:
            _BASE_CACHE.pop(next(iter(_BASE_CACHE)))
    ns["__fw_base__"] = ns["result"]
    if manual:
        ns["result"] = fw.apply_manual(ns["result"], manual)
        ns["MANUAL_FEATURES"] = manual
    ns["__fw_log__"] = fw.log()
    ns["__fw_manual__"] = fw.manual_count()
    ns["__cache_hit__"] = cached is not None
    return ns


def _write(out: Path, status: dict[str, Any]) -> None:
    import os
    import tempfile

    status["build_id"] = time.time_ns()
    fd, tmp = tempfile.mkstemp(dir=out, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, default=str)
    os.replace(tmp, out / "status.json")


def param_meta(raw: Any, params: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Optional PARAM_META = {"NAME": {"min": .., "max": .., "step": .., "unit": "mm", "group": "..", "label": ".."}}."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for k, m in raw.items():
        if k not in params or not isinstance(m, dict):
            continue
        clean: dict[str, Any] = {}
        for f in ("min", "max", "step"):
            if isinstance(m.get(f), (int, float)) and not isinstance(m.get(f), bool):
                clean[f] = m[f]
        for f in ("unit", "group", "label", "help"):
            if isinstance(m.get(f), str):
                clean[f] = m[f][:80]
        out[str(k)] = clean
    return out


def editable_params(source: str, declared: dict[str, Any]) -> dict[str, float | int]:
    """Parameters a user may edit without the AI: names the script declares in PARAMS *and* that are
    assigned exactly once at module level as a plain numeric literal (`NAME = 12.5`). Internal, derived,
    loop or computed variables are never editable."""
    tree = ast.parse(source)
    counts: dict[str, int] = {}
    literal: dict[str, float | int] = {}
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(
            node, (ast.AnnAssign, ast.AugAssign)) else []
        for t in targets:
            for n in ast.walk(t):
                if isinstance(n, ast.Name):
                    counts[n.id] = counts.get(n.id, 0) + 1
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            v = node.value
            neg = isinstance(v, ast.UnaryOp) and isinstance(v.op, ast.USub)
            c = v.operand if neg else v  # type: ignore[union-attr]
            if isinstance(c, ast.Constant) and type(c.value) in (int, float):
                literal[node.targets[0].id] = -c.value if neg else c.value
    return {k: literal[k] for k in declared if k in literal and counts.get(k) == 1}


def normalize_step(path: Path) -> None:
    """OCCT numbers assembly occurrences (NEXT_ASSEMBLY_USAGE_OCCURRENCE ids) with a process-wide counter, so a
    warm worker would write different bytes for the same assembly. Renumber them in order of appearance."""
    import re

    data = path.read_bytes()
    n = iter(range(1, 1_000_000))
    new = re.sub(rb"NEXT_ASSEMBLY_USAGE_OCCURRENCE\('\d+'", lambda _m: b"NEXT_ASSEMBLY_USAGE_OCCURRENCE('%d'" % next(n), data)
    if new != data:
        path.write_bytes(new)


def _export_atomic(fn: Any, shape: Any, out: Path, name: str, **kw: Any) -> Path:
    import os

    p = out / name
    tmp = out / (p.stem + ".tmp" + p.suffix)
    if not fn(shape, str(tmp), **kw):
        raise RuntimeError(f"export failed: {name}")
    if p.suffix == ".step":
        normalize_step(tmp)
    os.replace(tmp, p)
    return p


def _exports(shape: Any, out: Path) -> tuple[Any, Path]:
    """STEP (+ re-import for round-trip check), STL, GLB, 3MF. Returns (reimported shape, step path)."""
    import os

    from build123d import export_gltf, export_step, export_stl, import_step

    step = _export_atomic(export_step, shape, out, "part.step", timestamp=STEP_TIMESTAMP)
    reimported = import_step(str(step))
    _export_atomic(export_stl, reimported, out, "part.stl", tolerance=0.01)
    _export_atomic(export_gltf, reimported, out, "model.glb", binary=True, linear_deflection=0.01,
                   angular_deflection=0.1)
    try:
        from build123d import Mesher

        mesher = Mesher()
        mesher.add_shape(reimported, linear_deflection=0.01, angular_deflection=0.1)
        tmp3 = out / "part.tmp.3mf"
        mesher.write(str(tmp3))
        os.replace(tmp3, out / "part.3mf")
    except Exception:  # noqa: BLE001,S110 - 3MF is optional
        pass
    return reimported, step


_REF_CACHE: dict[str, Any] = {}


def check_reference(shape: Any, rel: str) -> Any:
    """CHK-09: how closely a rebuilt model matches the imported original (symmetric-difference volume)."""
    from aicad import checks, fw

    path = Path(fw.project_file(rel))
    key = f"{path}:{path.stat().st_mtime_ns}"
    ref = _REF_CACHE.get(key)
    if ref is None:
        ref = fw.import_reference(rel)
        _REF_CACHE.clear()
        _REF_CACHE[key] = ref
    try:
        extra = (shape - ref).volume
        missing = (ref - shape).volume
    except Exception as e:  # noqa: BLE001 - boolean failure is reported, never fatal
        return checks.CheckResult("CHK-09", "matches imported reference", False, gating=False,
                                  detail={"error": f"{type(e).__name__}: {e}"})
    rel_err = (extra + missing) / max(ref.volume, 1e-9)
    return checks.CheckResult("CHK-09", "matches imported reference (symmetric difference)", rel_err <= 1e-3,
                              gating=False, detail={"extra_mm3": round(extra, 3), "missing_mm3": round(missing, 3),
                                                    "rel_err": rel_err, "tol": 1e-3, "reference": rel})


def main(script: Path, out: Path, determinism: bool = True, fast: bool = False) -> int:
    """Build + verify. fast=True (interactive edits): geometry, validity, topology and mass are written
    immediately; file exports and the STEP round-trip check are deferred to finalize()."""
    import hashlib

    from build123d import Shape, export_step

    from aicad import checks
    from aicad.topo import export_topology, mass_properties

    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    status: dict[str, Any] = {"ok": False, "script": script.name, "checks": []}
    try:
        source = script.read_text(encoding="utf-8")
        tripwire(source)
        ns = _exec(script, use_cache=fast)
        shape = ns["result"]
        if not isinstance(shape, Shape):
            raise ScriptRejected(f"`result` is {type(shape).__name__}, expected a build123d Shape")
        t_build = time.perf_counter() - t0
        exp: dict[str, Any] = dict(ns.get("EXPECTED") or {})
        manual = int(ns.get("__fw_manual__", 0) or 0)

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
            results.append(checks.CheckResult("CHK-04", "bounding box (no expectation given)", False, gating=False,
                                              detail={"got_mm": checks.bbox_size(shape)}))
        if "volume" in exp:
            r = checks.check_volume(shape, float(exp["volume"]))
            tol = float(exp.get("volume_tol", checks.VOLUME_REL_TOL))
            r.passed = r.detail["rel_err"] <= tol
            r.detail["tol"] = tol
            results.append(r)
        else:
            results.append(checks.CheckResult("CHK-05", "volume (no expectation given)", False, gating=False,
                                              detail={"got_mm3": shape.volume}))
        if ns.get("REFERENCE_STEP") and not ns.get("IMPORTED"):
            results.append(check_reference(ns.get("__fw_base__", shape), str(ns["REFERENCE_STEP"])))
        if manual:
            for r in results:
                if r.id in ("CHK-04", "CHK-05") and r.gating:
                    r.gating = False
                    r.name += " (informational: manual features not in EXPECTED)"
                    r.detail["manual_features"] = manual

        declared = ns.get("PARAMS") if isinstance(ns.get("PARAMS"), dict) else {}
        params = {str(k): v for k, v in declared.items() if isinstance(v, (int, float, str, bool))}
        export_topology(shape, out / "topo.json", ns.get("__fw_log__"))
        mass = mass_properties(shape)
        status.update(
            part=ns.get("NAME", script.stem), material=ns.get("MATERIAL", "unspecified"),
            params=params, editable_params=editable_params(source, params), expected=exp,
            param_meta=param_meta(ns.get("PARAM_META"), params), mass=mass, manual_features=manual,
            features=[{"name": e["name"], "kind": e["kind"], "params": e["params"]} for e in ns.get("__fw_log__", [])],
            fingerprint=checks.fingerprint(shape), imported=bool(ns.get("IMPORTED")),
            env={"build123d": _ver("build123d"), "cadquery-ocp": _ver("cadquery-ocp", "cadquery_ocp")},
        )

        if fast:
            results.append(checks.CheckResult("CHK-07", "STEP export -> reimport (running in background)", False,
                                              gating=False, detail={"pending": True}))
            results.append(checks.CheckResult(
                "CHK-08", "deterministic regeneration (skipped for interactive edit)", False, gating=False,
                detail={"note": "design structure verified at the last agent build"}))
            _LAST[str(out)] = {"shape": shape}
            status.update(exports_pending=True, cache_hit=bool(ns.get("__cache_hit__")))
        else:
            reimported, step = _exports(shape, out)
            results.append(checks.check_roundtrip(shape, reimported))
            if determinism:
                ns2 = _exec(script)
                same_fp = checks.fingerprint(ns2["result"]) == checks.fingerprint(shape)
                with tempfile.TemporaryDirectory() as td:
                    p2 = Path(td) / "p2.step"
                    export_step(ns2["result"], str(p2), timestamp=STEP_TIMESTAMP)
                    normalize_step(p2)
                    same_step = p2.read_bytes() == step.read_bytes()
                results.append(checks.CheckResult("CHK-08", "deterministic regeneration", same_fp and same_step,
                                                  detail={"fingerprint_equal": same_fp, "step_bytes_equal": same_step}))
            else:
                results.append(checks.CheckResult(
                    "CHK-08", "deterministic regeneration (skipped for parameter edit)", False, gating=False,
                    detail={"note": "script structure unchanged since the agent build that verified it"}))
            status.update(exports_pending=False, step_sha256=hashlib.sha256(step.read_bytes()).hexdigest())
        status.update(ok=all(r.passed for r in results if r.gating), checks=checks.as_dicts(results),
                      timings_s={"build_s": round(t_build, 3), "total_s": round(time.perf_counter() - t0, 3)})
    except ScriptRejected as e:
        status.update(error=f"rejected: {e}")
    except Exception as e:  # noqa: BLE001 - report any script/kernel failure to the agent
        tb = traceback.format_exc(limit=6)
        status.update(error=f"{type(e).__name__}: {e}", traceback=tb[-3000:])
    _write(out, status)
    return 0 if status.get("ok") else 1


def finalize(out: Path) -> int:
    """Complete a fast build: file exports + STEP round-trip check, merged into status.json."""
    import hashlib

    from aicad import checks

    last = _LAST.pop(str(out), None)
    status_p = out / "status.json"
    if last is None or not status_p.is_file():
        return 2
    status = json.loads(status_p.read_text(encoding="utf-8"))
    if not status.get("exports_pending"):
        return 0
    t0 = time.perf_counter()
    reimported, step = _exports(last["shape"], out)
    rt = checks.as_dicts([checks.check_roundtrip(last["shape"], reimported)])[0]
    status["checks"] = [rt if c["id"] == "CHK-07" else c for c in status.get("checks", [])]
    status["ok"] = all(c["passed"] for c in status["checks"] if c["gating"])
    status["exports_pending"] = False
    status["step_sha256"] = hashlib.sha256(step.read_bytes()).hexdigest()
    status.setdefault("timings_s", {})["finalize_s"] = round(time.perf_counter() - t0, 3)
    build_id = status.get("build_id")
    _write(out, status)
    # keep the original build id so the viewer doesn't reload identical geometry
    st2 = json.loads(status_p.read_text(encoding="utf-8"))
    st2["build_id"] = build_id
    status_p.write_text(json.dumps(st2, indent=2, default=str), encoding="utf-8")
    return 0


def _ver(*names: str) -> str:
    from importlib.metadata import PackageNotFoundError, version

    for n in names:
        try:
            return version(n)
        except PackageNotFoundError:
            continue
    return "unknown"


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(),
                  determinism="--no-determinism" not in sys.argv))  # CLI: always full (non-fast) build
