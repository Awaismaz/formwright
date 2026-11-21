"""Thread engagement by the tapped part's material, and a tapped depth that always takes a standard screw (PD-285).

Golden reducer (c): M6 cap screws, washer 1.6 (ISO 7089), input cap flange 12 into an aluminium housing. Fitz's window
is L from 12 + 1.6 + 2 x 6 = 25.6 to 12 + 1.6 + (depth - 2 x 1.0). With the old 18 mm tap that was 29.6: no ISO 888
length (25, 30). The tap is now max(2.5 x 6 + 3, 2 x 6 + 2 x 1.0 + 5) = 19, so the top is 30.6 and M6 x 30 fits.
"""

from __future__ import annotations

import pytest

from aicad.assembly import fasteners
from aicad.office import icd
from aicad.office import program_assembly as pa


@pytest.mark.parametrize(("material", "k"), [
    ("Steel 1045 (medium carbon)", 1.5), ("Stainless steel 304", 1.5), ("Cast iron EN-GJL-250", 1.5),
    ("Bronze CuSn8", 1.5), ("Aluminium 6061-T6", 2.0), ("Magnesium AZ91", 2.0), ("Nylon PA6", 2.0),
    (None, 2.0), ("", 2.0), ("Unobtainium", 2.0)])
def test_engagement_by_material(material: str | None, k: float) -> None:
    assert fasteners.engagement_factor(material)[0] == k


def test_tap_depth_window_spans_one_length_step() -> None:
    # depth - 2 P - 2 d >= 5 for every size, and never shallower than the old 2.5 d + 3
    for m, P in fasteners.PITCH.items():
        if m > 16:
            continue
        t = icd.tap_depth(m)
        assert t >= 2.5 * m + 3.0
        assert t - 2 * P - 2 * m >= icd.LENGTH_STEP - 1e-9
    assert icd.tap_depth(6) == 19.0      # max(18, 12 + 2 + 5)
    assert icd.tap_depth(4) == 14.5      # max(13, 8 + 1.4 + 5 = 14.4), up to 0.5
    assert icd.tap_depth(10) == 28.0     # max(28, 20 + 3 + 5)


def test_reducer_input_cap_now_takes_a_standard_screw() -> None:
    old = fasteners.tapped_length(6, 12.0, True, 18.0, True, "Aluminium 6061-T6")
    assert old["L"] is None and old["L_min"] == pytest.approx(25.6) and old["L_max"] == pytest.approx(29.6)
    new = fasteners.tapped_length(6, 12.0, True, icd.tap_depth(6), True, "Aluminium 6061-T6")
    assert new["L"] == 30 and new["L_max"] == pytest.approx(30.6)
    # in cast iron the same 18 mm tap would have done: 12 + 1.6 + 1.5 x 6 = 22.6 to 29.6 -> 25
    assert fasteners.tapped_length(6, 12.0, True, 18.0, True, "Cast iron")["L"] == 25
    pr = {"kind": "tapped", "hole_d": 6.6, "grip": 12.0, "members": [],
          "tapped": {"name": "Base", "d": 5.0, "depth": 18.0, "blind": True, "material": "Aluminium 6061-T6"}}
    err = fasteners.propose(pr, "shcs", "head")["error"]
    assert err.startswith("No standard M6 length fits between 25.6 and 29.6 mm")


def test_unknown_tapped_material_takes_the_program_housing_material() -> None:
    prog = {"plan": {"graph": {"data": {"components": [{"kind": "shaft", "material": "Steel"},
                                                       {"kind": "housing", "material": "Cast iron"}]}}}}
    assert pa.program_material(prog) == "Cast iron"
    assert pa.program_material({"plan": {"graph": {"data": {"answers": {"material": "Cast iron"}}}}}) == "Cast iron"
    assert pa.program_material({"plan": {}}) is None
    assert pa._tapped_material(None, "Cast iron") == "Cast iron"
    assert pa._tapped_material("Aluminium 6061-T6", "Cast iron") == "Aluminium 6061-T6"   # the part's own wins
    assert pa._tapped_material(None, None) is None
