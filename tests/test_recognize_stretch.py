"""Cylinders are recognised per stretch along their line (PD-276).

The recogniser used to sum cylindrical face angles over a whole axis line. A housing split on its shaft axis has a
180 degree half bore at each end of each half: summed over the line they made 360, so each half "had" a full hole
centred on its split face, and two separate coaxial bores of one diameter read as a single hole (the second one
lost, its extent mixed with the first's frame). Hand values below, all from the modelling numbers:

- housing 120 x 80 x 40 per half, end walls 15 thick (cavity 90 long), bore Ø40 on X at the split plane: a half
  bore per end wall, 15 long, centred at X = +-(60 - 15 / 2) = +-52.5;
- block 100 long on X, two Ø10 x 30 blind bores from the two ends on one line: centres at X = +-(50 - 15) = +-35.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from build123d import Box, Compound, Cylinder, Pos, Rot

from aicad import recognize
from aicad.assembly import geometry, store
from aicad.memory import facts
from aicad.office import conformance

L, W, H, WALL, R = 120.0, 80.0, 40.0, 15.0, 20.0
X_END = L / 2 - WALL / 2   # 52.5


def _bore() -> object:
    return Rot(0, 90, 0) * Cylinder(R, L + 2)


def _lower() -> object:
    return Pos(0, 0, -H / 2) * Box(L, W, H) - Pos(0, 0, -H / 2 + 5) * Box(L - 2 * WALL, W - 20, H) - _bore()


def _upper() -> object:
    return Pos(0, 0, H / 2) * Box(L, W, H) - Pos(0, 0, H / 2 - 5) * Box(L - 2 * WALL, W - 20, H) - _bore()


def _two_bores() -> object:
    blk = Box(100, 60, 40)
    cut = Rot(0, 90, 0) * Cylinder(5, 30)
    return blk - Pos(-35, 0, 0) * cut - Pos(35, 0, 0) * cut


def test_split_housing_half_has_half_bores_not_a_hole() -> None:
    rec = recognize.recognize(_lower())
    assert [h for h in rec["holes"] if abs(h["d"] - 2 * R) < 1e-3] == []   # was one Ø40 x 120 "hole" at X 0
    ps = rec["partials"]
    assert len(ps) == 2
    for p, x in zip(ps, (-X_END, X_END), strict=True):
        assert p["d"] == pytest.approx(2 * R)
        assert p["angle"] == pytest.approx(180.0, abs=0.1)
        assert p["axis"] == [1.0, 0.0, 0.0]
        assert p["center"] == pytest.approx([x, 0, 0], abs=1e-3)
        assert p["depth"] == pytest.approx(WALL, abs=1e-3)
        assert p["full"] is False
    feats = [f for f in rec["features"] if f["kind"] == "partial_bore"]
    assert len(feats) == 2 and all(f["name"].startswith("Half bore Ø40.0") for f in feats)
    assert all(not f.get("holes") for f in feats)   # never offered for hole edits
    assert any("half bore" in s for s in rec["summary"])


def test_split_housing_pair_keeps_each_half_to_itself() -> None:
    # both halves in one compound: a hole belongs to one body, so four half bores and no hole
    rec = recognize.recognize(Compound(children=[_lower(), _upper()]))
    assert not [h for h in rec["holes"] if abs(h["d"] - 2 * R) < 1e-3]
    assert sorted(p["center"][0] for p in rec["partials"]) == pytest.approx([-X_END, -X_END, X_END, X_END])


def test_assembled_housing_has_two_bores_with_their_own_extents() -> None:
    # the same housing as one solid: a full Ø40 bore in each end wall, the cavity between them
    rec = recognize.recognize(_lower().fuse(_upper()))
    hs = [h for h in rec["holes"] if abs(h["d"] - 2 * R) < 1e-3]
    assert len(hs) == 2   # was one Ø40 x 122 hole centred at X 0
    for h, x in zip(hs, (-X_END, X_END), strict=True):
        assert h["center"] == pytest.approx([x, 0, 0], abs=1e-3)
        assert h["depth"] == pytest.approx(WALL, abs=1e-3)
        assert h["through"] is True and h["full"] is True
    assert rec["partials"] == []


def test_two_coaxial_bores_with_a_gap_are_two_holes() -> None:
    rec = recognize.recognize(_two_bores())
    hs = [h for h in rec["holes"] if abs(h["d"] - 10) < 1e-3]
    assert len(hs) == 2   # was one hole at X -35: the second was lost
    for h, x in zip(hs, (-35.0, 35.0), strict=True):
        assert h["center"] == pytest.approx([x, 0, 0], abs=1e-3)
        assert h["depth"] == pytest.approx(30, abs=1e-3)
        assert h["through"] is False
    # each opens on its own end face, pointing into the block
    by_x = {round(h["center"][0]): h for h in hs}
    assert by_x[-35]["open"] == pytest.approx([-50, 0, 0], abs=1e-3) and by_x[-35]["dir"] == pytest.approx([1, 0, 0])
    assert by_x[35]["open"] == pytest.approx([50, 0, 0], abs=1e-3) and by_x[35]["dir"] == pytest.approx([-1, 0, 0])


def test_assembly_snapshot_gives_each_hole_its_own_faces() -> None:
    shape = _two_bores()
    hs = [h for h in recognize.recognize(shape)["holes"] if abs(h["d"] - 10) < 1e-3]
    ids = [geometry._hole_face_ids(shape, h) for h in hs]
    assert all(len(x) == 1 for x in ids) and ids[0] != ids[1]


def test_stretches_join_overlapping_and_touching_faces_only() -> None:
    # rows (lo, hi, span, fid): two halves of one bore overlap -> one full turn; a face that touches the end of a
    # stretch continues it; a face beyond a gap is a stretch of its own
    st = recognize._stretches([(0.0, 10.0, 180.0, 1), (0.0, 10.0, 180.0, 2), (10.0, 18.0, 360.0, 3),
                               (30.0, 40.0, 180.0, 4)])
    assert [(s["lo"], s["hi"], s["fids"]) for s in st] == [(0.0, 18.0, [1, 2, 3]), (30.0, 40.0, [4])]
    assert st[0]["span"] == pytest.approx(360.0) and st[1]["span"] == pytest.approx(180.0)
    # a half bore split along its length stays half a turn (the angle is the most covered at one point, not a sum)
    st = recognize._stretches([(0.0, 5.0, 180.0, 1), (5.0, 12.0, 180.0, 2)])
    assert len(st) == 1 and st[0]["span"] == pytest.approx(180.0)


def test_keyed_bore_stays_a_bore() -> None:
    # a DIN 6885 hub keyway leaves about 325 degrees of the bore: still a hole (not full), not a partial bore
    from aicad import fw_std

    part, _g = fw_std.spur_gear(2, 30, 20, bore=20, keyway=True)
    rec = recognize.recognize(part)
    assert [(h["d"], h["full"]) for h in rec["holes"]] == [(20.0, False)]
    assert rec["partials"] == []
    assert rec["component"]["kind"] == "spur_gear" and rec["component"]["params"]["teeth"] == 30


def test_slot_ends_are_partial_bores() -> None:
    # an obround slot 30 x 10 through a plate: its two round ends are half turns, not two Ø10 holes
    from build123d import SlotOverall, extrude

    part = Box(80, 40, 6) - extrude(SlotOverall(30, 10), 6, both=True)
    rec = recognize.recognize(part)
    assert not [h for h in rec["holes"] if abs(h["d"] - 10) < 1e-3]
    assert sorted(p["center"][0] for p in rec["partials"]) == pytest.approx([-10, 10], abs=1e-3)


def test_office_takes_the_hole_nearest_the_joint() -> None:
    # a housing's tapped holes in both end walls on one line (Y -46..-28 and 28..46 in the canonical frame of Y, read
    # as Z here): each cap's screw goes into the wall it sits on
    from aicad.office import program_assembly as pa

    info = {"holes": [{"d": 5.0, "axis": [0.0, 0.0, 1.0], "center": [-80.5, -15.5, -37.0], "depth": 18.0},
                      {"d": 5.0, "axis": [0.0, 0.0, 1.0], "center": [-80.5, -15.5, 37.0], "depth": 18.0}]}
    assert pa._hole_index(info, [-80.5, -15.5], None, -46.0) == 0
    assert pa._hole_index(info, [-80.5, -15.5], None, 46.0) == 1
    assert pa._hole_index(info, [-80.5, -15.5]) == 0   # no joint plane: the first, as before


def test_split_hole_in_conformance_finds_the_half_bore() -> None:
    info = {"holes": [], "partials": [{"d": 40.0, "axis": [0.0, 0.0, 1.0], "center": [0.0, 52.5, 0.0], "depth": 15.0,
                                       "through": True, "angle": 180.0}]}
    f = {"type": "hole", "c": [0.0, 52.5], "d": 40.0, "tol": 0.1, "label": "opening", "split": True}
    row = conformance._row(f, info, {})
    assert row["ok"] is True, row
    assert conformance._row({**f, "split": False}, info, {})["ok"] is False   # a whole hole is not a half bore


def test_version_bump_re_reads_old_recognitions(tmp_path: Path) -> None:
    assert recognize.VERSION >= 4
    d = store.part_dir(tmp_path, "p_x_1")
    d.mkdir(parents=True)
    for f in ("part.step", "topo.json", "refs.json", "meta.json"):
        (d / f).write_text("{}", encoding="utf-8")
    (d / "info.json").write_text(json.dumps({"holes": [], "recognize_version": 3}), encoding="utf-8")
    assert store.part_ready(tmp_path, "p_x_1") is False   # an assembly snapshot read by v3 is made again
    ws = tmp_path / "ws"
    (ws / "out").mkdir(parents=True)
    (ws / "out" / "recognition.json").write_text(json.dumps({"build_id": "b1"}), encoding="utf-8")
    assert facts.recognition_current(ws, {"build_id": "b1"}) is None   # the Studio's reading too
    (ws / "out" / "recognition.json").write_text(json.dumps({"build_id": "b1", "version": recognize.VERSION}),
                                                 encoding="utf-8")
    assert facts.recognition_current(ws, {"build_id": "b1"}) is not None
