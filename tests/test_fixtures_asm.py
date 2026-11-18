"""ASM-012 golden assembly fixtures FX-04/05/06: rebuild each from its parametric scripts and assert every check.

Every expected value is a hand formula over the fixture's parameters (see the fixture modules' docstrings); the
numbers repeated here are those formulas worked out by hand."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from aicad.fixtures import FIXTURES, MODULES
from aicad.fixtures import fx04_bolted_bracket as fx04
from aicad.fixtures import fx06_hinged_arm as fx06
from aicad.fixtures.harness import definition_json, run

SPECS = Path(__file__).resolve().parents[1] / "specs" / "fixtures"
_REPORTS: dict[str, dict[str, Any]] = {}


def _report(fid: str, tmp: Path) -> dict[str, Any]:
    if fid not in _REPORTS:
        _REPORTS[fid] = run(FIXTURES[fid](), tmp / fid)
    return _REPORTS[fid]


def _by_id(rep: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["id"]: c for c in rep["checks"]}


@pytest.mark.parametrize("fid", ["FX-04", "FX-05", "FX-06"])
def test_fixture_rebuilds_and_every_check_passes(fid: str, tmp_path_factory: pytest.TempPathFactory) -> None:
    rep = _report(fid, tmp_path_factory.mktemp("fx"))
    failed = [(c["id"], c["detail"]) for c in rep["checks"] if not c["passed"]]
    assert not failed, failed
    ids = _by_id(rep)
    for must in ("ASM/mates", "ASM/dof", "ASM/poses", "ASM/interference", "ASM/contacts", "ASM/mass", "ASM/com",
                 "ASM/bom"):
        assert must in ids
    assert rep["interference"]["pairs"] == []  # touching faces are contacts, never overlaps


def test_fx04_hand_values(tmp_path_factory: pytest.TempPathFactory) -> None:
    rep = _report("FX-04", tmp_path_factory.mktemp("fx"))
    c = _by_id(rep)
    assert c["ASM/dof"]["detail"]["freedoms"] == 8  # 4 washers + 2 bolts + 2 nuts spin
    # 0.3 mm = (6.6 − 6) / 2 radial clearance of the shank in both clamped parts
    gaps = {(p["a"], p["b"]): p["got_mm"] for p in c["ASM/contacts"]["detail"]["pairs"]}
    assert gaps[("bolt1", "plate")] == pytest.approx(0.3, abs=1e-6) and gaps[("bracket", "plate")] == 0
    # grip 18 + washers 2 × 1.6 + nut 5.2 + 2 × P 1.0 = 28.4 → M6×30, protrusion 30 − 26.4 = 3.6
    assert c["FX-04/bolt-length"]["detail"]["L_min"] == pytest.approx(28.4)
    assert c["FX-04/protrusion1"]["detail"]["measured_mm"] == pytest.approx(3.6, abs=1e-6)
    # mass by hand: plate 120·80·10 − 2·π/4·6.6²·10 − 4·π/4·9²·10, bracket 60·40·8 + 60·8·50 − 2·π/4·6.6²·8 −
    # π/4·8.4²·8 (Al 2.70 g/cm³); fasteners from the ISO tables (steel 7.85 g/cm³)
    plate = 120 * 80 * 10 - 2 * math.pi / 4 * 6.6 ** 2 * 10 - 4 * math.pi / 4 * 81 * 10
    bracket = 60 * 40 * 8 + 60 * 8 * 50 - 2 * math.pi / 4 * 6.6 ** 2 * 8 - math.pi / 4 * 8.4 ** 2 * 8
    bolt = math.sqrt(3) / 2 * 10 ** 2 * 4 + math.pi / 4 * 36 * 30
    washer = math.pi / 4 * (12 ** 2 - 6.4 ** 2) * 1.6
    nut = (math.sqrt(3) / 2 * 10 ** 2 - math.pi / 4 * 36) * 5.2
    want = (plate + bracket) * 2.70e-3 + (2 * bolt + 4 * washer + 2 * nut) * 7.85e-3
    assert rep["mass"]["kernel_g"] == pytest.approx(want, rel=1e-6)
    assert rep["mass"]["com_hand_mm"][0] == pytest.approx(0, abs=1e-9)  # symmetric about X = 0
    assert [(r["part"], r["qty"]) for r in rep["bom"]] == [
        ("FX-04 base plate", 1), ("FX-04 angle bracket", 1), ("Washer ISO 7089 M6", 4),
        ("Hex bolt ISO 4017 M6×30", 2), ("Hex nut ISO 4032 M6", 2)]


def test_fx05_hand_values(tmp_path_factory: pytest.TempPathFactory) -> None:
    rep = _report("FX-05", tmp_path_factory.mktemp("fx"))
    c = _by_id(rep)
    d = c["ASM/dof"]["detail"]
    assert d["freedoms"] == 3  # two bearing spins + the shaft/key/gear spin
    gaps = {(p["a"], p["b"]): p["got_mm"] for p in c["ASM/contacts"]["detail"]["pairs"]}
    assert gaps[("shaft", "housing")] == pytest.approx(2.0, abs=1e-6)   # (30 − 26) / 2
    assert gaps[("gear", "housing")] == pytest.approx(11.0, abs=1e-6)   # gear face 69 − housing top 58
    assert gaps[("key", "gear")] == 0 and gaps[("bearing_a", "housing")] == 0
    # the keyed gear stayed on the shoulder: shaft frame at z = 14 − 30 = −16, gear at −16 + 85 = 69
    assert c["ASM/poses"]["detail"]["worst"] < 1e-4
    assert rep["motion"][0]["colliding_values"] == []  # the keyed group turns clash-free
    # shaft volume: Ø20×30 + Ø26×30 + Ø20×25 + Ø18×30 − keyway (b 6, t1 3.5, L 18)
    R, h = 9.0, 3.0
    seg = (h * math.sqrt(R * R - h * h) + R * R * math.asin(h / R)) - 6 * (R - 3.5)
    shaft = math.pi / 4 * (400 * 30 + 676 * 30 + 400 * 25 + 324 * 30) - seg * 18
    part = c["shaft/CHK-05"]["detail"]
    assert part["hand_mm3"] == pytest.approx(shaft, rel=1e-12) and part["got_mm3"] == pytest.approx(shaft, rel=1e-6)


def test_fx06_motion_range_matches_hand_formula(tmp_path_factory: pytest.TempPathFactory) -> None:
    rep = _report("FX-06", tmp_path_factory.mktemp("fx"))
    lo, hi = fx06.contact_angles()
    want_lo = math.degrees(math.asin(6 / math.sqrt(656)) - math.atan2(16, 20))
    assert lo == pytest.approx(want_lo) and lo == pytest.approx(-25.1118, abs=1e-4) and hi == pytest.approx(180 - lo)
    m = {x["name"]: x for x in rep["motion"]}
    assert m["within limits"]["colliding_values"] == []
    # 10° steps from −40 to 220: only −40, −30 (below −25.11) and 210, 220 (above 205.11) collide
    assert m["beyond limits"]["colliding_values"] == [-40.0, -30.0, 210.0, 220.0]
    assert m["beyond limits"]["pairs"] == [("base", "arm")]
    gap = {r["theta"]: r["got_mm"] for r in _by_id(rep)["FX-06/edge-gap"]["detail"]["rows"]}
    t = math.radians(-25)
    assert gap[-25.0] == pytest.approx(20 * math.sin(t) + 16 * math.cos(t) - 6, abs=1e-6)
    assert _by_id(rep)["ASM/dof"]["detail"]["freedoms"] == 2  # pin spin + hinge


@pytest.mark.parametrize("fid", ["FX-04", "FX-05", "FX-06"])
def test_definition_and_provenance_files_are_current(fid: str) -> None:
    mod = MODULES[fid]
    d = SPECS / mod.SLUG
    assert (d / "assembly.json").read_text(encoding="utf-8") == definition_json(mod.fixture()), \
        "stale: run `uv run python -m aicad.fixtures --write`"
    prov = json.loads((d / "provenance.json").read_text(encoding="utf-8"))
    assert prov["fixture"] == fid and prov["author"] == "Generated for Formwright" and prov["date"]
    assert "original" in prov["licence"].lower() and prov["design_intent"] and "Not a copy" in prov["originality"]
    assert (SPECS / "README.md").is_file()


def test_checks_catch_a_broken_fixture(tmp_path: Path) -> None:
    """The harness is not a rubber stamp: a too-short bolt, a wrong mate and a wrong motion prediction all fail."""
    p = dict(fx04.PARAMS, bolt_L=25.0)  # grip 18 + 8.4 > 25: the bolt ends inside the nut
    rep = run(fx04.fixture(p), tmp_path / "short", motion=False)
    bad = {c["id"] for c in rep["checks"] if not c["passed"]}
    assert {"FX-04/bolt-length", "FX-04/protrusion1", "FX-04/protrusion2"} <= bad

    f = fx06.fixture()
    next(m for m in f.mates if m["id"] == "m_arm_gap")["value"] = 0.5  # the arm is placed 0.5 mm off its hand pose
    f.motion[1]["collide"] = []                                            # and a wrong collision prediction
    rep = run(f, tmp_path / "wrong")
    bad = {c["id"] for c in rep["checks"] if not c["passed"]}
    assert {"ASM/poses", "ASM/contacts", "ASM/motion/beyond limits"} <= bad
    assert "ASM/mates" not in bad  # the wrong mate itself is satisfiable: the hand placement is what catches it
