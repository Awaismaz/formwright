"""Hole recognition is independent of which way the modelling cylinder points (founder's Gear Reducer, 2026-11-19).

A blind M8 tap drill in a gearbox side wall, modelled with a cylinder pointing -Y, came back mirrored about its
origin (centre and ends in the gear cavity) and so "through": Gage sent the Housing base back 3 times for a hole that
was correct. Hand values below: block 100 x 60 x 40 centred on the origin, so the -Y face is at Y = -30.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from build123d import Box, Cylinder, Pos, Rot

from aicad import recognize
from aicad.assembly import store


def _y_cyl(x: float, z: float, r: float, y0: float, y1: float, sign: int) -> object:
    # sign -1: Rot(90, 0, 0) turns the cylinder's +Z axis to -Y (as in the founder's model); +1: to +Y
    rot = Rot(90, 0, 0) if sign < 0 else Rot(-90, 0, 0)
    return Pos(x, (y0 + y1) / 2, z) * rot * Cylinder(r, abs(y1 - y0))


def _hole(shape: object, d: float) -> dict:
    hs = [h for h in recognize.recognize(shape)["holes"] if abs(h["d"] - d) < 1e-3]
    assert len(hs) == 1, hs
    return hs[0]


@pytest.mark.parametrize("sign", [-1, 1])
def test_blind_wall_hole_either_axis_direction(sign: int) -> None:
    # Ø6.8 x 23 deep from the -Y face (Y = -30) inward: ends at Y = -7, centre Y = -30 + 23/2 = -18.5
    part = Box(100, 60, 40) - _y_cyl(20, 5, 3.4, -30, -7, sign)
    h = _hole(part, 6.8)
    assert h["axis"] == [0.0, 1.0, 0.0]
    assert h["center"] == pytest.approx([20, -18.5, 5], abs=1e-3)
    assert h["depth"] == pytest.approx(23, abs=1e-3)
    assert h["through"] is False
    assert sorted([h["top"][1], h["bottom"][1]]) == pytest.approx([-30, -7], abs=1e-3)


@pytest.mark.parametrize("sign", [-1, 1])
def test_through_wall_hole_either_axis_direction(sign: int) -> None:
    # a 26 mm wall (Y -30..-4) in front of a cavity (Y -4..30): a Ø9 hole through the wall only is through
    part = Box(100, 60, 40) - Pos(0, 13, 0) * Box(80, 34, 30) - _y_cyl(0, 0, 4.5, -30, -4, sign)
    h = _hole(part, 9.0)
    assert h["center"] == pytest.approx([0, -17, 0], abs=1e-3)   # (-30 + -4) / 2
    assert h["through"] is True


def test_blind_hole_from_below_pointing_down() -> None:
    # Ø5 x 12 deep from the bottom face (Z = -20) up, cylinder axis -Z (Rot(180, 0, 0)): centre Z = -20 + 6 = -14
    part = Box(100, 60, 40) - Pos(-30, 0, -14) * Rot(180, 0, 0) * Cylinder(2.5, 12)
    h = _hole(part, 5.0)
    assert h["center"] == pytest.approx([-30, 0, -14], abs=1e-3)
    assert h["through"] is False


def test_old_snapshots_are_made_again(tmp_path: Path) -> None:
    d = store.part_dir(tmp_path, "p_x_1")
    d.mkdir(parents=True)
    for f in ("part.step", "topo.json", "refs.json", "meta.json"):
        (d / f).write_text("{}", encoding="utf-8")
    (d / "info.json").write_text(json.dumps({"holes": []}), encoding="utf-8")   # recognised before VERSION 2
    assert store.part_ready(tmp_path, "p_x_1") is False
    (d / "info.json").write_text(json.dumps({"holes": [], "recognize_version": recognize.VERSION}), encoding="utf-8")
    assert store.part_ready(tmp_path, "p_x_1") is True
