"""PS-03: high-level standard features for model scripts (fw.spur_gear, stepped_shaft, shaft_keyway, holes)."""

from __future__ import annotations

import math

import pytest
from build123d import Align, Box, Cylinder

from aicad import checks, fw


def test_spur_gear_matches_its_hand_formulas_with_clean_brep() -> None:
    part, exp = fw.spur_gear(2, 60, 20, bore=20, hub_d=40, hub_l=30, keyway=True)
    assert part.is_valid and len(part.solids()) == 1 and checks.free_edge_count(part) == 0
    assert exp["volume"] == pytest.approx(part.volume, rel=1e-5)  # spline flanks vs the exact involute integral
    assert checks.bbox_size(part) == pytest.approx(tuple(exp["bbox"]), abs=0.01)
    assert exp["bbox"] == pytest.approx([124, 124, 50], abs=1e-6)  # tip Ø = m (z + 2); 60 teeth reach every axis
    assert len(part.faces()) < 300  # ~4 faces per tooth (polygon teeth gave 2048 faces)
    g = exp["gear"]
    assert g["pitch_d"] == pytest.approx(120) and g["root_d"] == pytest.approx(115)
    assert g["base_d"] == pytest.approx(120 * math.cos(math.radians(20)))
    names = [e["name"] for e in fw.log()]
    assert names[-1] == "Keyway 6×2.8 (DIN 6885)" and names[0].startswith("Gear teeth (m2, z60")


def test_gear_without_extras_and_helical_keep_the_profile_area() -> None:
    fw.reset()
    plain, e1 = fw.spur_gear(1.5, 31, 12)
    helical, e2 = fw.spur_gear(1.5, 31, 12, helix_angle=15)
    assert plain.volume == pytest.approx(e1["volume"], rel=1e-5)
    assert helical.volume == pytest.approx(e2["volume"], rel=1e-4)  # a twisted extrusion keeps the section area
    assert e2["gear"]["twist_deg"] == pytest.approx(math.degrees(12 * math.tan(math.radians(15)) / (1.5 * 31 / 2)))
    # odd tooth count: the tip circle is not reached on the -X side, the hand bbox says so
    assert checks.bbox_size(plain)[0] == pytest.approx(e1["bbox"][0], abs=0.01) and e1["bbox"][0] < 1.5 * 33


def test_gear_rejects_impossible_inputs() -> None:
    with pytest.raises(ValueError):
        fw.spur_gear(2, 20.5, 10)
    with pytest.raises(ValueError):
        fw.spur_gear(2, 20, 10, bore=40)  # no rim left
    with pytest.raises(ValueError):
        fw.spur_gear(2, 60, 10, keyway=True)  # keyway without a bore


def test_stepped_shaft_hand_volume() -> None:
    fw.reset()
    part, exp = fw.stepped_shaft([(20, 30), (30, 40)])
    assert exp["volume"] == pytest.approx(math.pi * (100 * 30 + 225 * 40))  # hand calculation
    assert part.volume == pytest.approx(exp["volume"], rel=1e-9) and exp["bbox"] == [30, 30, 70]
    part, exp = fw.stepped_shaft([(20, 30), (30, 40), (20, 25)], chamfer=1, fillet=1.5)
    assert part.is_valid and part.volume == pytest.approx(exp["volume"], rel=1e-6)  # Pappus for chamfers + fillets
    assert any(e["name"] == "Shoulder fillets R1.5" for e in fw.log())


def test_shaft_keyway_removed_volume() -> None:
    fw.reset()
    shaft, _ = fw.stepped_shaft([(25, 100)])
    for rounded in (True, False):
        part, v = fw.shaft_keyway(shaft, d=25, z_center=50, length=40, rounded=rounded)
        assert part.volume == pytest.approx(shaft.volume - v, rel=1e-6)  # GProp's own error is ~1e-7 of the shaft
    assert fw.din6885(25) == {"b": 8, "h": 7, "t1": 4.0, "t2": 3.3}
    with pytest.raises(ValueError):
        fw.din6885(100)


def test_helper_names_never_reach_the_user() -> None:
    from aicad.agent.session import scrub

    assert scrub("I used fw.spur_gear and fw.bolt_circle") == "I used the design tools and the design tools"


def test_holes_bolt_circle_and_tapped_threads() -> None:
    fw.reset()
    plate = Box(100, 100, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part, info = fw.bolt_circle(plate, 6, 80, "M8 clearance", depth=10)
    assert info["d"] == 9.0 and info["count"] == 6  # ISO 273 medium
    assert plate.volume - part.volume == pytest.approx(info["volume"], rel=1e-9)
    assert info["volume"] == pytest.approx(6 * math.pi * 81 / 4 * 10)
    part2, h = fw.hole(part, (0, 0, 10), "M6 tapped", depth=12 - 2)
    assert h["d"] == 5.0 and part.volume - part2.volume == pytest.approx(h["volume"], rel=1e-9)
    assert fw.threads() and fw.threads()[-1]["designation"].startswith("M6")
    part3, h3 = fw.hole(Cylinder(30, 20, align=(Align.CENTER, Align.CENTER, Align.MIN)), (10, 0, 20), "M10 cbore",
                        depth=20)
    assert h3["volume"] == pytest.approx(math.pi * 11 ** 2 / 4 * 20 + math.pi * (18 ** 2 - 11 ** 2) / 4 * 10.4)
    assert Cylinder(30, 20).volume - part3.volume == pytest.approx(h3["volume"], rel=1e-9)
