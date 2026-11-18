"""IO-008: coordinate system + unit round-trip matrix across every format the app writes.

Fixture FX-IO-1 (original, asymmetric, off-origin), all numbers in mm:
  block  X 10..70, Y 20..50, Z 5..15                      (60 x 30 x 10)
  boss   Ø8 (r 4), 12 high, axis at (20, 28), Z 15..27    (near the -X/-Y corner: breaks every mirror symmetry)
  hole   Ø6 (r 3) through the block, axis at (60, 42)
Hand formulas (never measured from the built shape):
  bbox   min (10, 20, 5), max (70, 50, 27)
  volume 60*30*10 + pi*4^2*12 - pi*3^2*10 = 18000 + 102*pi
  boss top-face centre (20, 28, 27); hole centre minus boss centre in the top view = (40, 14)
A swapped axis, a mirror, an inch/metre/mm scale error or a lost placement changes at least one of these.
Readers in ``io_helpers.py`` are written from the format specs, not from the exporters.

Matrix and results: docs/reports/io-roundtrip.md.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from io_helpers import (
    bbox_minmax,
    gltf_to_cad_mm,
    read_glb,
    read_stl,
    shape_top_centre,
    signed_volume,
    step_length_unit,
    top_cap_centre,
)

BMIN, BMAX = (10.0, 20.0, 5.0), (70.0, 50.0, 27.0)
VOLUME = 60 * 30 * 10 + math.pi * 4**2 * 12 - math.pi * 3**2 * 10
BOSS_TOP = (20.0, 28.0, 27.0)
HOLE_MINUS_BOSS_XY = (60.0 - 20.0, 42.0 - 28.0)
MESH_REL_VOL = 2e-4   # 0.01 mm chordal deviation on a Ø6 hole / Ø8 boss: well under 0.02 % of the volume
EXACT_REL_VOL = 1e-6

MODEL = """from build123d import *
from math import pi
NAME = "IO fixture"
MATERIAL = "6061-T6"
part = Pos(10, 20, 5) * Box(60, 30, 10, align=(Align.MIN, Align.MIN, Align.MIN))
part += Pos(20, 28, 15) * Cylinder(4, 12, align=(Align.CENTER, Align.CENTER, Align.MIN))
part -= Pos(60, 42, 5) * Cylinder(3, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
result = part
EXPECTED = {"bbox": [60, 30, 22], "volume": 18000 + 102 * pi, "solids": 1}
"""


def _assert_mesh(tris: np.ndarray, label: str, tol: float = 1e-4) -> None:
    bb = bbox_minmax(tris)
    assert bb == pytest.approx([*BMIN, *BMAX], abs=tol), f"{label}: bbox {bb}"
    v = signed_volume(tris)
    assert v > 0, f"{label}: negative signed volume (mirrored / inside-out)"
    assert v == pytest.approx(VOLUME, rel=MESH_REL_VOL), f"{label}: volume {v}"
    assert top_cap_centre(tris, tol=max(tol, 1e-6)) == pytest.approx(BOSS_TOP, abs=max(tol, 1e-4)), label


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The fixture built by the real build pipeline (the same path every Studio build takes)."""
    from aicad.agent import runner

    ws = tmp_path_factory.mktemp("io")
    (ws / "model.py").write_text(MODEL, encoding="utf-8")
    assert runner.main(ws / "model.py", ws / "out", determinism=False) == 0
    st = json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
    assert st["ok"], st
    return ws


# ------------------------------------------------------------------ part STEP (AP214, mm)
def test_step_part_units_bbox_volume_feature(built: Path) -> None:
    from build123d import import_step

    step = built / "out" / "part.step"
    assert step_length_unit(step) == "MILLI.METRE"
    s = import_step(str(step))
    bb = s.bounding_box(optimal=True)
    assert [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z] == pytest.approx([*BMIN, *BMAX], abs=1e-6)
    assert s.volume == pytest.approx(VOLUME, rel=EXACT_REL_VOL)
    assert shape_top_centre(s) == pytest.approx(BOSS_TOP, abs=1e-6)


def test_status_records_placement_not_just_size(built: Path) -> None:
    st = json.loads((built / "out" / "status.json").read_text(encoding="utf-8"))
    assert st["bbox_minmax"] == pytest.approx([*BMIN, *BMAX], abs=1e-3)  # OCCT's loose box: tolerance-enlarged
    assert st["fingerprint"]["bbox"] == pytest.approx([60, 30, 22], abs=1e-6)


# ------------------------------------------------------------------ meshes
def test_stl_mm_same_frame(built: Path) -> None:
    _assert_mesh(read_stl(built / "out" / "part.stl"), "STL")


def test_3mf_declares_millimetre_and_keeps_frame(built: Path) -> None:
    from aicad.printprep.mesh import parse_3mf

    tris, scale = parse_3mf((built / "out" / "part.3mf").read_bytes())
    assert scale == 1.0  # unit="millimeter"
    _assert_mesh(tris, "3MF")


def test_glb_is_metres_y_up_and_maps_back_exactly(built: Path) -> None:
    tris_gl, js = read_glb(built / "out" / "model.glb")
    assert js["asset"]["version"] == "2.0"
    # glTF frame: +Y up, metres. The fixture's tallest point (Z = 27 mm) must be the largest Y = 0.027.
    assert float(tris_gl[..., 1].max()) == pytest.approx(BMAX[2] / 1000, abs=1e-6)
    # the -Y side of the CAD part (Y = 20) is the +Z side in glTF (z_gl = -Y)
    assert float(tris_gl[..., 2].max()) == pytest.approx(-BMIN[1] / 1000, abs=1e-6)
    _assert_mesh(gltf_to_cad_mm(tris_gl), "GLB", tol=1e-3)  # float32 metres: ~1e-4 mm resolution


# ------------------------------------------------------------------ 2D drawing DXF
def test_dxf_true_size_mm_and_not_mirrored(built: Path, tmp_path: Path) -> None:
    import ezdxf

    from aicad.drawing.generate import generate

    generate(built / "out", tmp_path, {"views": ["front", "top", "right"], "section": None},
             {"title": "IO fixture", "drawing_no": "FW-IO-1", "drawn_by": "Test", "date": "2026-11-18",
              "model_rev": "1"})
    doc = ezdxf.readfile(str(tmp_path / "sheet.dxf"))
    assert doc.header["$INSUNITS"] == 4  # millimetres
    circles = [e for e in doc.modelspace().query("CIRCLE")]
    boss = [e for e in circles if abs(e.dxf.radius - 4.0) < 1e-6]
    hole = [e for e in circles if abs(e.dxf.radius - 3.0) < 1e-6]
    # only the top view shows the vertical axes as circles: one boss circle, one hole circle, at true size
    assert len(boss) == 1 and len(hole) == 1, sorted(round(e.dxf.radius, 4) for e in circles)
    d = hole[0].dxf.center - boss[0].dxf.center
    assert (d.x, d.y) == pytest.approx(HOLE_MINUS_BOSS_XY, abs=1e-6)  # +X right, +Y up: no mirror, no rotation
    lengths = {round(e.dxf.start.distance(e.dxf.end), 6) for e in doc.modelspace().query("LINE")}
    assert {60.0, 30.0} <= lengths


# ------------------------------------------------------------------ native .fwpart
def test_fwpart_round_trip_keeps_frame_and_units(built: Path, tmp_path: Path) -> None:
    from build123d import import_step

    from aicad.agent import runner
    from aicad.native import container as c
    from aicad.native import part as fpart

    data = fpart.export_part(built, name="IO fixture", description="", project_id="p1", org_id="o1",
                             data_dir=tmp_path / "data")
    pkg = c.read_package(data, "fwpart")
    assert pkg.manifest["part"]["units"] == "mm"
    assert pkg.manifest["geometry"]["bbox_minmax"] == pytest.approx([*BMIN, *BMAX], abs=1e-3)
    fpart.validate(pkg, strict=True)
    ws2 = tmp_path / "ws2"
    fpart.install(pkg, ws2)
    assert runner.main(ws2 / "model.py", ws2 / "out", determinism=False) == 0
    st2 = json.loads((ws2 / "out" / "status.json").read_text(encoding="utf-8"))
    geo = pkg.manifest["geometry"]
    assert fpart.compare(geo["fingerprint"], st2["fingerprint"], expected_place=fpart.placement(geo),
                         got_place=fpart.placement(st2)) == []
    s = import_step(str(ws2 / fpart.ORIGINAL_STEP))  # the exact geometry carried in the file
    assert shape_top_centre(s) == pytest.approx(BOSS_TOP, abs=1e-6)


def test_fwpart_verification_catches_moved_or_mirrored_rebuild(built: Path) -> None:
    """Bug found by IO-008: the import check compared sizes only, so a rebuild that came back translated or mirrored
    (same size, volume and topology counts) was reported 'identical'. Placement now takes part in the comparison."""
    from build123d import Plane, mirror

    from aicad import checks
    from aicad.native import part as fpart
    from aicad.topo import mass_properties

    st = json.loads((built / "out" / "status.json").read_text(encoding="utf-8"))
    ns: dict[str, Any] = {}
    exec(compile(MODEL, "fixture", "exec"), ns)  # noqa: S102 - the fixture above, test only
    shape = ns["result"]
    moved = shape.translate((5, 0, 0))
    mirrored = mirror(shape, Plane.YZ.offset(40.0))  # X -> 80 - X: same bbox_minmax, same counts
    want = fpart.placement(st)
    for label, s in (("moved", moved), ("mirrored", mirrored)):
        fp = checks.fingerprint(s)
        assert fpart.compare(st["fingerprint"], fp) == [], f"{label}: sizes and counts alone cannot see it"
        bb = s.bounding_box()
        got = {"bbox_minmax": [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z],
               "mass": mass_properties(s)}
        diffs = fpart.compare(st["fingerprint"], fp, expected_place=want, got_place=fpart.placement(got))
        assert any("position" in d for d in diffs), (label, diffs)


# ------------------------------------------------------------------ assembly STEP
def test_assembly_step_keeps_instance_placements(built: Path, tmp_path: Path) -> None:
    from build123d import import_step

    from aicad.assembly import geometry, xform

    step = str(built / "out" / "part.step")
    R = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])  # +90 deg about Z
    t = (100.0, -50.0, 0.0)
    nodes = [{"id": "a", "part_label": "Fixture A", "step": step, "T": xform.to12(xform.ident()), "group": None},
             {"id": "b", "part_label": "Fixture B", "step": step, "T": xform.to12(xform.make(R, t)), "group": None}]
    res = geometry.export(tmp_path / "asm.step", "IO assembly", nodes)
    assert step_length_unit(tmp_path / "asm.step") == "MILLI.METRE"
    back = import_step(str(tmp_path / "asm.step"))
    leaves: list[Any] = []

    def walk(s: Any) -> None:
        kids = list(getattr(s, "children", ()) or ())
        if not kids:
            leaves.append(s)
        for k in kids:
            walk(k)

    walk(back)
    # instances of one part share one STEP product, so leaf names follow the product; match them by export order
    assert len(leaves) == 2 and res["ok"], res
    by = dict(zip(("Fixture A", "Fixture B"), leaves, strict=True))
    # hand-transformed expectations for B: x' = -y + 100, y' = x - 50, z' = z
    want = {"Fixture A": ([*BMIN, *BMAX], BOSS_TOP),
            "Fixture B": ([-BMAX[1] + 100, BMIN[0] - 50, BMIN[2], -BMIN[1] + 100, BMAX[0] - 50, BMAX[2]],
                          (-BOSS_TOP[1] + 100, BOSS_TOP[0] - 50, BOSS_TOP[2]))}
    for label, (bb_want, top_want) in want.items():
        s = by[label]
        bb = s.bounding_box(optimal=True)
        assert [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z] == pytest.approx(bb_want, abs=1e-6), label
        assert s.volume == pytest.approx(VOLUME, rel=EXACT_REL_VOL), label
        assert shape_top_centre(s) == pytest.approx(top_want, abs=1e-6), label


# ------------------------------------------------------------------ 3D Print Prep exports (STL / 3MF writers)
def test_print_prep_writers_keep_mm_and_frame(built: Path, tmp_path: Path) -> None:
    from aicad.printprep.mesh import Mesh, parse_mesh, write_3mf, write_stl

    tris = read_stl(built / "out" / "part.stl")
    v, inv = np.unique(tris.reshape(-1, 3), axis=0, return_inverse=True)
    mesh = Mesh(v, inv.reshape(-1, 3), None, {})
    write_stl(mesh, tmp_path / "pp.stl")
    write_3mf(mesh, tmp_path / "pp.3mf")
    _assert_mesh(read_stl(tmp_path / "pp.stl"), "print STL", tol=1e-4)  # float32
    back = parse_mesh((tmp_path / "pp.3mf").read_bytes(), "pp.3mf")
    assert back.meta["units"] == "mm" and back.meta["scale_to_mm"] == 1.0
    _assert_mesh(back.v[back.f], "print 3MF", tol=1e-5)
    # an upload declared in inches is scaled to mm on the way in (the user picks the unit for STL)
    inch = parse_mesh((tmp_path / "pp.stl").read_bytes(), "pp.stl", units="in")
    assert bbox_minmax(inch.v[inch.f])[3] == pytest.approx(BMAX[0] * 25.4, rel=1e-6)


# ------------------------------------------------------------------ Mesh Studio (Blender) exports (IO-008b)
def _blender() -> Path | None:
    from aicad.meshstudio import runner as mrunner

    return mrunner.find_blender()


@pytest.mark.skipif(_blender() is None, reason="Blender is not installed (set FW_BLENDER to run the IO-008b rows)")
def test_mesh_studio_blender_exports_keep_units_axes_and_frame(built: Path, tmp_path: Path) -> None:
    """Mesh Studio's GLB / OBJ / STL are written by Blender (a separate GPL process), not by our exporters. Run the
    real export job on FX-IO-1 and read each file back with the spec readers: GLB metres +Y up, OBJ and STL
    millimetres +Z up, all in the model's own frame (no recentring, no mirror)."""
    import shutil

    from io_helpers import read_obj

    from aicad.meshstudio import service

    ws = tmp_path / "ws"
    (ws / "out").mkdir(parents=True)
    shutil.copy2(built / "out" / "part.step", ws / "out" / "part.step")
    d = service.mesh_root(ws) / "exports" / "io008b"
    d.mkdir(parents=True)
    job: dict[str, Any] = {"id": "io008b", "kind": "export"}
    service._execute_export(ws, d, job, "IO fixture", "anodised", "blue")
    assert job["state"] == "done", job
    tol = 1e-3  # float32 metres in the mesh hand-off and GLB; OBJ text keeps 6 decimals
    # GLB: glTF convention, metres and +Y up
    tris_gl, js = read_glb(d / "part.glb")
    assert js["asset"]["version"] == "2.0"
    assert float(tris_gl[..., 1].max()) == pytest.approx(BMAX[2] / 1000, abs=1e-6)  # tallest point is +Y
    assert float(tris_gl[..., 2].max()) == pytest.approx(-BMIN[1] / 1000, abs=1e-6)  # CAD -Y side is glTF +Z
    _assert_mesh(gltf_to_cad_mm(tris_gl), "Mesh Studio GLB", tol=tol)
    # OBJ: millimetres, Z up (global_scale 1000, forward Y, up Z); the header says so
    obj = d / "part.obj"
    assert "Units: millimetres. Z up." in obj.read_text(encoding="utf-8")[:400]
    _assert_mesh(read_obj(obj), "Mesh Studio OBJ", tol=tol)
    # STL: millimetres, Z up, labelled as a visualisation mesh
    stl = d / "part.stl"
    assert stl.read_bytes()[:22] == b"Formwright Mesh Studio"
    _assert_mesh(read_stl(stl), "Mesh Studio STL", tol=tol)
