from __future__ import annotations

import json
import random
from dataclasses import replace
from pathlib import Path

import pytest
from build123d import Box, Pos

from aicad import checks
from aicad.parts.plate import PlateSpec, SpecError, build_plate, expected_volume
from aicad.pipeline import run

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "specs" / "fx01_plate.json"


def test_golden_pipeline_all_gates_pass(tmp_path: Path) -> None:
    s = run(GOLDEN, tmp_path)
    failed = [c["id"] for c in s["checks"] if not c["passed"]]
    assert s["ok"], failed
    ids = {c["id"] for c in s["checks"]}
    assert {"CHK-02", "CHK-03", "CHK-04", "CHK-05", "CHK-06", "CHK-07", "CHK-08"} <= ids
    for f in ("part.step", "part.stl", "model.glb", "status.json"):
        assert (tmp_path / f).stat().st_size > 0
    assert json.loads((tmp_path / "status.json").read_text())["ok"] is True


def test_golden_volume_matches_hand_calc() -> None:
    # Hand calculation, independent of expected_volume():
    # 120*80*10 - (200*1 - 4/3) - 4*pi*3.3^2*10 - (40*30 - (4-pi)*9)*4
    import math

    hand = 96000 - (200 - 4 / 3) - 4 * math.pi * 3.3**2 * 10 - (1200 - (4 - math.pi) * 9) * 4
    part = build_plate(PlateSpec())
    assert part.volume == pytest.approx(hand, rel=1e-9)


def test_step_bytes_deterministic(tmp_path: Path) -> None:
    a = run(GOLDEN, tmp_path / "a")
    b = run(GOLDEN, tmp_path / "b")
    assert a["step_sha256"] == b["step_sha256"]


def test_metamorphic_length_increase() -> None:
    base = PlateSpec()
    longer = replace(base, length=base.length + 10)
    pa, pb = build_plate(base), build_plate(longer)
    # +10 mm in X adds a 10 x W x T slab minus the extra chamfer strip along both long edges
    c = base.top_chamfer
    expected_delta = 10 * base.width * base.thickness - 10 * c**2
    assert pb.volume - pa.volume == pytest.approx(expected_delta, rel=1e-9)
    assert checks.bbox_size(pb)[0] == pytest.approx(base.length + 10, abs=1e-6)


def _random_spec(rng: random.Random) -> PlateSpec:
    L = rng.uniform(60, 300)
    W = rng.uniform(40, 200)
    T = rng.uniform(4, 30)
    return PlateSpec(
        length=L, width=W, thickness=T,
        hole_diameter=rng.choice([3.4, 4.5, 5.5, 6.6, 9.0, 11.0]),
        hole_edge_offset=rng.uniform(6, 20),
        pocket_length=rng.uniform(5, L * 0.6), pocket_width=rng.uniform(5, W * 0.6),
        pocket_depth=rng.uniform(0.5, T * 0.8),
        pocket_corner_radius=rng.choice([0.0, 0.5, 1.0, 2.0, 3.0]),
        top_chamfer=rng.choice([0.0, 0.3, 0.5, 1.0]),
    )


def test_random_specs_build_valid_or_fail_cleanly() -> None:
    """VALIDATION VS-1 criterion 4: >=50 random param sets, no crashes."""
    rng = random.Random(1234)
    built = rejected = 0
    for _ in range(80):
        spec = _random_spec(rng)
        try:
            spec.validate()
        except SpecError:
            rejected += 1
            continue
        part = build_plate(spec)
        assert part.is_valid
        assert len(part.solids()) == 1
        assert checks.free_edge_count(part) == 0
        assert part.volume == pytest.approx(expected_volume(spec), rel=1e-6)
        assert checks.bbox_size(part) == pytest.approx(
            (spec.length, spec.width, spec.thickness), abs=0.01)
        built += 1
    assert built >= 50, (built, rejected)


@pytest.mark.parametrize("bad", [
    {"pocket_depth": 10.0},
    {"thickness": -1.0},
    {"hole_edge_offset": 2.0},
    {"pocket_corner_radius": 20.0},
    {"pocket_length": 119.0},  # reaches into top chamfer / side wall
    {"pocket_length": 100.0, "pocket_width": 60.0},  # intersects corner holes
])
def test_invalid_specs_rejected_with_message(bad: dict[str, float]) -> None:
    with pytest.raises(SpecError) as e:
        build_plate(replace(PlateSpec(), **bad))
    assert str(e.value)


def test_checks_detect_failures() -> None:
    two = Box(10, 10, 10) + Pos(50, 0, 0) * Box(10, 10, 10)
    assert not checks.check_solid(two)[0].passed  # 2 solids
    assert not checks.check_bbox(Box(10, 10, 10), (10, 10, 11)).passed
    assert not checks.check_volume(Box(10, 10, 10), 1100).passed
    assert not checks.check_cylinders(Box(10, 10, 10), {3.3: 4}).passed


def test_unknown_param_rejected(tmp_path: Path) -> None:
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps({"part": "plate", "params": {"lenght": 100}}))
    s = run(spec, tmp_path / "out")
    assert not s["ok"] and "unknown params" in s["error"]
