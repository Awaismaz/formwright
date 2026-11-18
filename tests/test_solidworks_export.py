"""CAD-070: "Export for SOLIDWORKS" (STEP pathway with disclosure).

The fixture is the IO-008 part (asymmetric, off-origin) so a lost placement, a unit error or a mirror would show.
Every check reads the written file back (OCCT) or parses its text; nothing claims SOLIDWORKS opened it (EVAL-005 is
the founder's manual check).
"""

from __future__ import annotations

import csv
import io
import json
import math
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from io_helpers import shape_top_centre, step_length_unit
from test_platform import admin, app_client, signup  # noqa: F401  (fixture re-export)

from aicad.native import solidworks as sw

MODEL = """from build123d import *
NAME = "IO fixture"
MATERIAL = "6061-T6 anodised blue"
L = 60
W = 30
T = 10
PARAMS = dict(L=L, W=W, T=T)
PARAM_META = {"L": {"min": 20, "max": 200, "unit": "mm", "label": "Length", "group": "Block"}}
part = Pos(10, 20, 5) * Box(L, W, T, align=(Align.MIN, Align.MIN, Align.MIN))
part += Pos(20, 28, 15) * Cylinder(4, 12, align=(Align.CENTER, Align.CENTER, Align.MIN))
part -= Pos(60, 42, 5) * Cylinder(3, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
result = part
EXPECTED = {"bbox": [60, 30, 22], "volume": L * W * T + 102 * 3.141592653589793, "solids": 1}
"""
BMINMAX = [10.0, 20.0, 5.0, 70.0, 50.0, 27.0]
VOLUME = 60 * 30 * 10 + math.pi * 4**2 * 12 - math.pi * 3**2 * 10


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from aicad.agent import runner

    ws = tmp_path_factory.mktemp("sw")
    (ws / "model.py").write_text(MODEL, encoding="utf-8")
    assert runner.main(ws / "model.py", ws / "out", determinism=False) == 0
    return ws / "out"


def _unzip(data: bytes) -> dict[str, bytes]:
    z = zipfile.ZipFile(io.BytesIO(data))
    return {n: z.read(n) for n in z.namelist()}


@pytest.mark.parametrize(("schema", "header"), [("ap214", "AUTOMOTIVE_DESIGN"),
                                                ("ap242", "AP242_MANAGED_MODEL_BASED_3D_ENGINEERING")])
def test_step_is_named_single_part_mm_coloured_and_identical(built: Path, tmp_path: Path, schema: str,
                                                            header: str) -> None:
    from build123d import import_step

    data, facts = sw.build_package(built, "Bracket A-12", schema)
    files = _unzip(data)
    assert sorted(files) == ["Bracket_A-12.step", "Bracket_A-12_parameters.csv", "README_SOLIDWORKS.txt"]
    step = tmp_path / "x.step"
    step.write_bytes(files["Bracket_A-12.step"])
    f = sw.step_facts(step)
    assert f["schema"].startswith(header)  # FILE_SCHEMA matches the schema asked for
    assert step_length_unit(step) == "MILLI.METRE" and f["length_unit_mm"]
    assert f["product_names"] == ["Bracket A-12"]  # one product named after the part: a part, not an assembly
    assert f["assembly"] is False
    assert f["has_colour"] and facts["colour"] == "Anodised aluminium, Blue"
    back = import_step(str(step))
    bb = back.bounding_box(optimal=True)
    assert [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z] == pytest.approx(BMINMAX, abs=1e-6)
    assert back.volume == pytest.approx(VOLUME, rel=1e-6)
    assert shape_top_centre(back) == pytest.approx((20.0, 28.0, 27.0), abs=1e-6)  # placement kept, not mirrored
    assert facts["check"]["matches_build"] is True


def test_readme_discloses_no_history_and_makes_no_claims(built: Path) -> None:
    data, _ = sw.build_package(built, "Bracket", "ap214", revision=4)
    text = _unzip(data)["README_SOLIDWORKS.txt"].decode("utf-8")
    assert "no Formwright feature history" in text
    assert "dumb solid" in text and "Native CAD bridge" in text and "MMGS" in text
    assert "has not been opened in SOLIDWORKS" in text  # EVAL-005 stays a manual check
    assert "revision 4" in text and "5 of 5 passed" in text
    low = text.lower()
    for banned in ("validated", "ready for manufacture", "guaranteed", "certified"):
        assert banned not in low
    assert "L (Length) = 60 mm" in text


def test_parameter_sheet_lists_declared_parameters(built: Path) -> None:
    data, facts = sw.build_package(built, "Bracket")
    rows = list(csv.DictReader(io.StringIO(_unzip(data)["Bracket_parameters.csv"].decode("utf-8"))))
    assert [r["parameter"] for r in rows] == ["L", "W", "T"] and facts["parameters"] == 3
    assert rows[0] == {"parameter": "L", "label": "Length", "value": "60", "unit": "mm",
                       "editable_in_formwright": "yes", "min": "20", "max": "200", "group": "Block"}


def test_package_is_byte_identical_for_the_same_build(built: Path) -> None:
    assert sw.build_package(built, "Bracket", "ap242")[0] == sw.build_package(built, "Bracket", "ap242")[0]


def test_refuses_unbuilt_failed_or_unknown_schema(built: Path, tmp_path: Path) -> None:
    with pytest.raises(sw.ExportRefused, match="no verified model"):
        sw.build_package(tmp_path, "X")
    out = tmp_path / "out"
    out.mkdir()
    st = json.loads((built / "status.json").read_text(encoding="utf-8"))
    (out / "status.json").write_text(json.dumps({**st, "ok": False}), encoding="utf-8")
    (out / "part.step").write_bytes((built / "part.step").read_bytes())
    with pytest.raises(sw.ExportRefused, match="passed its checks"):
        sw.build_package(out, "X")
    with pytest.raises(sw.ExportRefused, match="AP214 or AP242"):
        sw.build_package(built, "X", "iges")


def test_verify_refuses_a_file_that_reads_back_different(built: Path, tmp_path: Path) -> None:
    from build123d import Box, export_step, import_step

    other = tmp_path / "other.step"
    export_step(Box(60, 30, 22), str(other))
    with pytest.raises(sw.ExportRefused):
        sw.verify(import_step(str(built / "part.step")), other)


def test_unspecified_material_gets_no_colour() -> None:
    assert sw.body_colour(None) is None and sw.body_colour("unspecified") is None
    label, rgb = sw.body_colour("Steel C45")
    assert label and all(0 <= c <= 1 for c in rgb)


def test_api_export_scoped_to_the_workspace(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    admin(c)
    c.post("/api/god/seed-demo")
    pid = c.get("/api/projects").json()["items"][0]["id"]
    r = c.get(f"/api/projects/{pid}/export/solidworks?schema=ap242")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert "_SOLIDWORKS.zip" in r.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "README_SOLIDWORKS.txt" in names and any(n.endswith(".step") for n in names)
    assert c.get(f"/api/projects/{pid}/export/solidworks?schema=iges").status_code == 409
    new = c.post("/api/projects", json={"name": "Empty"}).json()
    new_id = new.get("id") or new.get("project", {}).get("id")
    assert c.get(f"/api/projects/{new_id}/export/solidworks").status_code == 409  # nothing built yet
    c.post("/api/auth/logout")
    signup(c, "other@example.com", workspace="Other Co")
    assert c.get(f"/api/projects/{pid}/export/solidworks").status_code == 404  # another workspace's project
