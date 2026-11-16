"""Build -> export -> reimport -> check -> publish artifacts for the live viewer.

The viewer mesh (model.glb) is tessellated from the *re-imported STEP file*, so what you
see is what the STEP contains, not the in-memory model.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import tempfile
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from build123d import Shape, export_gltf, export_step, export_stl, import_step

from aicad import checks
from aicad.parts.plate import PlateSpec, SpecError, build_plate, expected_volume

STEP_TIMESTAMP = "2000-01-01T00:00:00"  # fixed => byte-identical STEP for identical geometry


def _ver(*names: str) -> str:
    for n in names:
        try:
            return version(n)
        except PackageNotFoundError:
            continue
    return "unknown"


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _export_atomic(fn: Any, shape: Shape, path: Path, **kw: Any) -> None:
    tmp = path.with_name(path.stem + ".tmp" + path.suffix)
    if not fn(shape, str(tmp), **kw):
        raise RuntimeError(f"export failed: {path.name}")
    os.replace(tmp, path)


def load_spec(spec_path: Path) -> PlateSpec:
    data = json.loads(spec_path.read_text(encoding="utf-8"))
    if data.get("part") != "plate":
        raise SpecError(f"unsupported part type {data.get('part')!r} (spike supports 'plate')")
    unknown = set(data.get("params", {})) - set(PlateSpec.__dataclass_fields__)
    if unknown:
        raise SpecError(f"unknown params: {sorted(unknown)}")
    return PlateSpec(**data.get("params", {}))


def run(spec_path: Path, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    t: dict[str, float] = {}
    t0 = time.perf_counter()
    status: dict[str, Any] = {"spec": str(spec_path), "ok": False}
    try:
        spec = load_spec(spec_path)
        spec.validate()
    except (SpecError, TypeError, ValueError) as e:
        status.update(error=f"spec error: {e}", checks=[])
        publish_status(out_dir, status)
        return status

    part = build_plate(spec)
    t["build_s"] = time.perf_counter() - t0

    step = out_dir / "part.step"
    _export_atomic(export_step, part, step, timestamp=STEP_TIMESTAMP)
    _export_atomic(export_stl, part, out_dir / "part.stl", tolerance=0.01)
    t["export_s"] = time.perf_counter() - t0 - sum(t.values())

    t1 = time.perf_counter()
    reimported = import_step(str(step))
    t["reimport_s"] = time.perf_counter() - t1

    t1 = time.perf_counter()
    results: list[checks.CheckResult] = []
    results += checks.check_solid(part)
    results.append(checks.check_bbox(part, (spec.length, spec.width, spec.thickness)))
    results.append(checks.check_volume(part, expected_volume(spec)))
    expected_cyl = {round(spec.hole_diameter / 2, 4): 4}
    if spec.pocket_corner_radius > 0:
        expected_cyl[round(spec.pocket_corner_radius, 4)] = 4
    results.append(checks.check_cylinders(part, expected_cyl))
    results.append(checks.check_roundtrip(part, reimported))

    # CHK-08 determinism: rebuild from same spec, compare fingerprint and STEP bytes
    part2 = build_plate(spec)
    with tempfile.TemporaryDirectory() as td:
        step2 = Path(td) / "p2.step"
        export_step(part2, str(step2), timestamp=STEP_TIMESTAMP)
        same_step = _sha256(step2) == _sha256(step)
    same_fp = checks.fingerprint(part) == checks.fingerprint(part2)
    results.append(checks.CheckResult("CHK-08", "deterministic regeneration",
                                      same_fp and same_step,
                                      detail={"fingerprint_equal": same_fp,
                                              "step_bytes_equal": same_step}))
    t["checks_s"] = time.perf_counter() - t1

    t1 = time.perf_counter()
    _export_atomic(export_gltf, reimported, out_dir / "model.glb", binary=True,
                   linear_deflection=0.01, angular_deflection=0.1)
    t["glb_s"] = time.perf_counter() - t1
    t["total_s"] = time.perf_counter() - t0

    status.update(
        ok=all(r.passed for r in results if r.gating),
        part=spec.name,
        material=spec.material,
        params=spec.to_dict(),
        fingerprint=checks.fingerprint(part),
        step_sha256=_sha256(step),
        checks=checks.as_dicts(results),
        timings_s={k: round(v, 4) for k, v in t.items()},
        env={"python": platform.python_version(), "build123d": _ver("build123d"),
             "cadquery-ocp": _ver("cadquery-ocp", "cadquery_ocp"),
             "platform": platform.platform()},
        viewer_mesh_source="re-imported part.step",
    )
    publish_status(out_dir, status)
    return status


def publish_status(out_dir: Path, status: dict[str, Any]) -> None:
    status["build_id"] = time.time_ns()
    _atomic_write_text(out_dir / "status.json", json.dumps(status, indent=2, default=str))
