"""Design parameters on the model (viewport dimensions): sensitivity mapping, no AI.

Expected kinds and anchors are stated by hand from each script's construction (which planes / axes a value sets),
never read back from the mapping.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_platform import _project_with_model, app_client, signup  # noqa: F401  (fixture re-export)

from aicad import dims

DEMO = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo"

BLOCK = '''from build123d import *

L = 80.0
W = 50.0
H = 20.0
PARAMS = dict(L=L, W=W, H=H)
result = Box(L, W, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
'''

PLATE = '''from build123d import *

N = 4
D = 8.0
P = 20.0
T = 6.0
PARAMS = dict(N=N, D=D, P=P, T=T)
PARAM_META = {"N": {"min": 1, "max": 6, "step": 1}, "D": {"min": 3, "max": 15}}
part = Box(140, 40, T, align=(Align.CENTER, Align.CENTER, Align.MIN))
x0 = -(N - 1) * P / 2
for i in range(N):
    part -= Pos(x0 + i * P, 0, T / 2) * Cylinder(D / 2, T + 2)
result = part
'''

SHAFT = '''from build123d import *

D1 = 30.0
L1 = 40.0
D2 = 20.0
L2 = 25.0
PARAMS = dict(D1=D1, L1=L1, D2=D2, L2=L2)
pts = [(0, 0), (D1 / 2, 0), (D1 / 2, L1), (D2 / 2, L1), (D2 / 2, L1 + L2), (0, L1 + L2)]
profile = Plane.XZ * Polygon(*pts, align=None)
result = revolve(profile, Axis.Z, 360)
'''


def _map(tmp_path: Path, src: str) -> tuple[dict, list[dict]]:
    f = tmp_path / "model.py"
    f.write_text(src, encoding="utf-8")
    doc = dims.map_script(f)
    return {d["param"]: d for d in doc["dims"]}, dims._STATE[str(f)]["rows"]


def _plane_at(rows: list[dict], i: int, normal: tuple[float, float, float], offset: float) -> bool:
    r = rows[i]
    return r["t"] == "plane" and dims._dot(r["n"], normal) > 1 - 1e-9 and r["d"] == pytest.approx(offset, abs=1e-6)


def test_block_length_width_height_are_distances_between_opposite_faces(tmp_path: Path) -> None:
    m, rows = _map(tmp_path, BLOCK)
    # L: the faces x = -L/2 (normal -X) and x = +L/2 (normal +X); W the same in Y; H: z = 0 (normal -Z) and z = H
    for name, axis, lo, hi in (("L", 0, -40.0, 40.0), ("W", 1, -25.0, 25.0), ("H", 2, 0.0, 20.0)):
        d = m[name]
        assert d["kind"] == "linear" and d["a"]["ref"] == d["b"]["ref"] == "plane"
        assert d["s"] == pytest.approx(hi - lo)
        e = [0.0, 0.0, 0.0]
        e[axis] = 1.0
        assert abs(d["u"][axis]) == pytest.approx(1.0)
        ends = {d["a"]["face"], d["b"]["face"]}
        neg = tuple(-x for x in e)
        assert any(_plane_at(rows, i, neg, -lo) for i in ends)  # outward normal -e at coordinate lo: d = -lo
        assert any(_plane_at(rows, i, tuple(e), hi) for i in ends)


def test_plate_hole_diameter_pattern_count_and_pitch(tmp_path: Path) -> None:
    m, rows = _map(tmp_path, PLATE)
    assert m["D"]["kind"] == "diameter" and m["D"]["count"] == 4
    assert all(rows[i]["t"] == "cylinder" and rows[i]["r"] == pytest.approx(4.0) for i in m["D"]["faces"])
    assert m["N"]["kind"] == "count" and m["N"]["count"] == 4 and m["N"]["per"] == 1
    assert sorted(rows[i]["p"][0] for i in m["N"]["faces"]) == pytest.approx([-30, -10, 10, 30])
    # pitch: two neighbouring hole axes P apart along X
    p = m["P"]
    assert p["kind"] == "linear" and p["a"]["ref"] == p["b"]["ref"] == "axis" and p["s"] == pytest.approx(20.0)
    assert abs(rows[p["a"]["face"]]["p"][0] - rows[p["b"]["face"]]["p"][0]) == pytest.approx(20.0)
    assert m["T"]["kind"] == "linear" and m["T"]["s"] == pytest.approx(6.0)


def test_revolved_shaft_with_a_step(tmp_path: Path) -> None:
    m, rows = _map(tmp_path, SHAFT)
    for name, r in (("D1", 15.0), ("D2", 10.0)):
        assert m[name]["kind"] == "diameter" and m[name]["count"] == 1
        assert all(rows[i]["r"] == pytest.approx(r) for i in m[name]["faces"])
    # L1: end face z = 0 to the shoulder z = L1; L2: shoulder z = L1 to the end z = L1 + L2 (both normal along Z)
    for name, z0, z1 in (("L1", 0.0, 40.0), ("L2", 40.0, 65.0)):
        d = m[name]
        assert d["kind"] == "linear" and d["s"] == pytest.approx(z1 - z0)
        zs = sorted(dims._plane_x(rows[d[k]["face"]], (0, 0, 1)) for k in ("a", "b"))
        assert zs == pytest.approx([z0, z1])


def test_mapping_is_reused_after_a_value_edit_and_redone_when_the_structure_changes(tmp_path: Path) -> None:
    f = tmp_path / "model.py"
    f.write_text(PLATE, encoding="utf-8")
    doc = dims.map_script(f)
    f.write_text(PLATE.replace("D = 8.0", "D = 10.0").replace("T = 6.0", "T = 9.5"), encoding="utf-8")
    assert dims.base(f, doc)["valid"] is True  # same structure, same topology: still true at the new values
    f.write_text(PLATE.replace("N = 4", "N = 5"), encoding="utf-8")
    assert dims.base(f, doc)["valid"] is False  # one more hole: the count no longer holds, so map again
    f.write_text(PLATE.replace("result = part", "part -= Box(5, 5, 50)\nresult = part"), encoding="utf-8")
    assert dims.base(f, doc)["valid"] is False  # script changed


def test_demo_parts_map_every_dimension_parameter(tmp_path: Path) -> None:
    expected = {
        "mounting_plate": {"L": "linear", "W": "linear", "T": "linear", "HOLE_D": "diameter", "EDGE": "linear",
                           "PL": "linear", "PW": "linear", "PD": "linear", "PR": "radius", "CH": "none"},
        "stepped_shaft": {"D1": "diameter", "L1": "linear", "D2": "diameter", "L2": "linear", "KW": "linear",
                          "KD": "linear", "KL": "linear"},
        "pipe_flange": {"OD": "diameter", "T": "linear", "BORE": "diameter", "RF_D": "diameter", "RF_H": "linear",
                        "N_BOLTS": "count", "BOLT_D": "diameter", "PCD": "linear"},
    }
    for name, kinds in expected.items():
        d = tmp_path / name
        d.mkdir()
        m, _ = _map(d, (DEMO / f"{name}.py").read_text(encoding="utf-8"))
        assert {k: v["kind"] for k, v in m.items()} == kinds, name
    # the flange's six bolt holes, all of them, even though OCCT renumbers faces after a nudge
    assert m["BOLT_D"]["count"] == 6 and m["N_BOLTS"]["count"] == 6
    assert m["PCD"]["circle"] is True and m["PCD"]["s"] == pytest.approx(120.0)


def test_explicit_override_and_failed_nudge(tmp_path: Path) -> None:
    src = BLOCK.replace("PARAMS = dict(L=L, W=W, H=H)", 'PARAMS = dict(L=L, W=W, H=H)\nPARAM_META = {"W": {"dim": {"kind": "none"}}, '
                        '"H": {"dim": {"kind": "linear", "a": (0, 0, 0), "b": (0, 0, H)}}}\n'
                        'assert L <= 80.0, "too long"')
    m, _ = _map(tmp_path, src)
    assert m["W"]["kind"] == "hidden"
    assert m["H"]["kind"] == "linear" and m["H"]["pb"] == [0.0, 0.0, 20.0]
    assert m["L"]["kind"] == "linear"  # +1 % fails the script's own assert: the nudge goes the other way


def test_match_pairs_faces_by_least_movement() -> None:
    hole = lambda x, r: {"t": "cylinder", "a": (0, 0, 1), "p": (x, 0, 0), "r": r}
    B = [hole(0, 50), hole(60, 7), hole(-60, 7)]
    P = [hole(-60, 7.07), hole(60, 7.07), hole(0, 50)]  # renumbered after the nudge
    M = dims.match(B, P)
    assert [r["p"][0] for r in M] == [0, 60, -60] and [r["r"] for r in M] == [50, 7.07, 7.07]
    assert dims.match(B, P[:2]) is None


def test_dims_endpoint_maps_in_the_background_and_rechecks_after_a_param_edit(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "dims@x.com")
    pid, _ws = _project_with_model(c, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))

    def ready() -> dict:
        for _ in range(240):
            r = c.get(f"/api/projects/{pid}/dims").json()
            if r["state"] == "ready":
                return r
            time.sleep(0.5)
        raise AssertionError("dimension mapping did not finish")

    from aicad.platform import dims_service

    budget = dims_service.BUDGET_S
    dims_service.BUDGET_S = 0.0  # a machine so slow that every pass runs out of time after one parameter
    try:
        r = ready()
    finally:
        dims_service.BUDGET_S = budget
    assert dims_service.read(_ws).get("partial") is None  # finished over several passes
    m = {d["param"]: d for d in r["dims"]}
    assert m["L"]["kind"] == "linear" and m["HOLE_D"]["kind"] == "diameter" and "reason" not in m["CH"]
    t_map = r["timings"]["total_s"]
    assert c.post(f"/api/projects/{pid}/params", json={"values": {"L": 150}}).status_code == 200
    r2 = ready()
    assert r2["build_id"] != r["build_id"]
    assert {d["param"]: d["kind"] for d in r2["dims"]} == {k: v["kind"] for k, v in m.items()}
    assert r2["timings"] == r["timings"] and t_map  # reused (checked, not re-mapped): same structure, same topology


def test_agent_style_part_without_hints(tmp_path: Path) -> None:
    """A script as the design agent writes it (docs/reports/viewport-dims/motor_mount.py, also the replayed build of
    the walkthrough): every value that is one measurable size gets a dimension, with no dimension hints."""
    src = (Path(__file__).resolve().parents[1] / "docs" / "reports" / "viewport-dims" / "motor_mount.py").read_text(
        encoding="utf-8")
    m, rows = _map(tmp_path, src)
    assert {k: v["kind"] for k, v in m.items()} == {
        "BASE_L": "linear", "BASE_W": "linear", "BASE_T": "linear", "WALL_H": "linear", "WALL_T": "linear",
        "MOTOR_BORE": "diameter", "BOLT_N": "count", "BOLT_PCD": "linear", "BOLT_D": "diameter", "SLOT_L": "linear",
        "SLOT_W": "linear", "FILLET_R": "radius"}
    # hand values: wall height from the base top (z = 8) to the wall top (z = 68); slot length over its round ends
    assert sorted(dims._plane_x(rows[m["WALL_H"][k]["face"]], (0, 0, 1)) for k in ("a", "b")) == pytest.approx([8, 68])
    assert m["SLOT_L"]["a"]["ref"] == m["SLOT_L"]["b"]["ref"] == "tangent" and m["SLOT_L"]["s"] == pytest.approx(30)
    assert m["BOLT_PCD"]["circle"] and m["BOLT_D"]["count"] == 4 and m["FILLET_R"]["count"] == 1
