"""Assembly Studio: mate solver, interference, clearance, BOM, assembly STEP, fastener auto-fit and the API.

Every expected number is worked by hand from the fixture inputs (never measured from the built shapes):
- solver: a 100 x 100 x 10 base (top face z = 10, a vertical hole axis at (30, 20)) and a 20 mm cube block with a
  vertical axis through its centre; mates must put the block's bottom-centre at (30, 20, 10) exactly.
- interference: two 20 mm cubes offset by (5, 3, 2) overlap in a 15 x 17 x 18 box = 4590 mm³; a Ø10 pin through an
  Ø8 hole in a 12 mm plate overlaps by π (5² − 4²) 12 = 108 π mm³.
- clearance: 10 mm cubes offset by (14, 14, 0) are √(4² + 4²) = 5.656854… mm apart.
- fastener lengths: L ≥ grip + washers + nut height + 2 P, next ISO 888 length (cases below).
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from aicad.assembly import fasteners, solver, xform

# ----------------------------------------------------------------------------- solver (pure)
BASE_TOP = solver.Ref("plane", (0.0, 0.0, 10.0), (0.0, 0.0, 1.0))
BASE_AXIS = solver.Ref("axis", (30.0, 20.0, 0.0), (0.0, 0.0, 1.0), 4.0)
BASE_SIDE = solver.Ref("plane", (50.0, 0.0, 5.0), (1.0, 0.0, 0.0))
BLOCK_BOTTOM = solver.Ref("plane", (0.0, 0.0, 0.0), (0.0, 0.0, -1.0))
BLOCK_AXIS = solver.Ref("axis", (0.0, 0.0, 10.0), (0.0, 0.0, 1.0), 4.0)
BLOCK_SIDE = solver.Ref("plane", (10.0, 0.0, 10.0), (1.0, 0.0, 0.0))


def _insts(T_block: np.ndarray | None = None) -> dict[str, solver.Inst]:
    if T_block is None:  # deliberately far off: rotated 25° about X and 40° about Z, moved away
        T_block = xform.make(xform.rot((0, 0, 1), math.radians(40)) @ xform.rot((1, 0, 0), math.radians(25)),
                             (-70.0, 55.0, 33.0))
    return {"base": solver.Inst("base", xform.ident(), fixed=True, ref_point=(0, 0, 5)),
            "block": solver.Inst("block", T_block, ref_point=(0, 0, 10))}


def _m(mid: str, t: str, ra: solver.Ref, rb: solver.Ref, value: float = 0.0, flip: bool = False) -> solver.MateSpec:
    return solver.MateSpec(mid, t, "base", ra, "block", rb, value, flip)


def test_coincident_and_concentric_place_block_exactly() -> None:
    mates = [_m("m1", "coincident", BASE_TOP, BLOCK_BOTTOM), _m("m2", "concentric", BASE_AXIS, BLOCK_AXIS)]
    res = solver.solve(_insts(), mates, L=60, prealign_ids=["m1"])
    T = res.poses["block"]
    assert np.allclose(xform.pt(T, (0, 0, 0)), (30, 20, 10), atol=1e-9)      # bottom centre on the axis, on the top
    assert np.allclose(xform.vec(T, (0, 0, 1)), (0, 0, 1), atol=1e-9)        # block upright
    assert all(m.ok for m in res.mates.values()) and not res.conflicts
    st = res.insts["block"]
    assert (st.dof, st.rot, st.trans, st.spin) == (1, 1, 0, True)            # only the spin about the axis is free
    # 3 + 4 equations, rank 5: the axis parallelism repeats the face-normal alignment (2 redundant, consistent)
    assert res.status == "under_defined" and res.dof == 1 and res.redundant == 2


def test_angle_zero_fixes_the_spin_fully_defined() -> None:
    mates = [_m("m1", "coincident", BASE_TOP, BLOCK_BOTTOM), _m("m2", "concentric", BASE_AXIS, BLOCK_AXIS),
             _m("m3", "angle", BASE_SIDE, BLOCK_SIDE, 0.0)]
    res = solver.solve(_insts(), mates, L=60, prealign_ids=["m1"])
    T = res.poses["block"]
    assert np.allclose(T[:3, :3], np.eye(3), atol=1e-9)                       # side faces parallel → no rotation
    assert np.allclose(T[:3, 3], (30, 20, 10), atol=1e-9)
    assert res.status == "fully_defined" and res.dof == 0


def test_distance_and_angle_values() -> None:
    res = solver.solve(_insts(), [_m("m1", "distance", BASE_TOP, BLOCK_BOTTOM, 5.0),
                                  _m("m2", "concentric", BASE_AXIS, BLOCK_AXIS)], L=60, prealign_ids=["m1"])
    assert np.allclose(xform.pt(res.poses["block"], (0, 0, 0)), (30, 20, 15), atol=1e-9)
    res = solver.solve(_insts(), [_m("m1", "coincident", BASE_TOP, BLOCK_BOTTOM),
                                  _m("m2", "concentric", BASE_AXIS, BLOCK_AXIS),
                                  _m("m3", "angle", BASE_SIDE, BLOCK_SIDE, 30.0)], L=60, prealign_ids=["m1"])
    n = xform.vec(res.poses["block"], BLOCK_SIDE.v)
    assert math.degrees(math.acos(float(n @ np.array(BASE_SIDE.v)))) == pytest.approx(30.0, abs=1e-7)
    assert abs(n[2]) < 1e-9 and res.status == "fully_defined"


def test_conflict_is_isolated_and_reported() -> None:
    mates = [_m("m1", "coincident", BASE_TOP, BLOCK_BOTTOM), _m("m2", "concentric", BASE_AXIS, BLOCK_AXIS),
             _m("m3", "distance", BASE_TOP, BLOCK_BOTTOM, 5.0)]   # contradicts m1
    res = solver.solve(_insts(), mates, L=60, prealign_ids=["m1"])
    assert res.status == "over_defined" and res.conflicts == ["m3"]
    assert res.mates["m1"].ok and res.mates["m2"].ok and not res.mates["m3"].ok and res.mates["m3"].conflict
    assert res.mates["m3"].residual_mm == pytest.approx(5.0, abs=1e-9)      # the consistent mates still hold
    assert res.insts["block"].over and np.allclose(xform.pt(res.poses["block"], (0, 0, 0)), (30, 20, 10), atol=1e-9)


def test_redundant_but_consistent_mate_is_not_a_conflict() -> None:
    mates = [_m("m1", "coincident", BASE_TOP, BLOCK_BOTTOM), _m("m2", "concentric", BASE_AXIS, BLOCK_AXIS),
             _m("m3", "flush", BASE_TOP, solver.Ref("plane", (0, 0, 0), (0, 0, 1)))]   # same plane, aligned normal
    res = solver.solve(_insts(), mates, L=60, prealign_ids=["m1"])
    assert not res.conflicts and res.redundant == 2 + 3 and res.insts["block"].dof == 1


def test_unmated_part_has_six_dof_and_fixed_has_none() -> None:
    res = solver.solve(_insts(), [], L=60)
    assert res.insts["block"].dof == 6 and res.insts["base"].dof == 0 and res.insts["base"].fixed


# ----------------------------------------------------------------------------- fastener selection (pure)
def test_clearance_and_tap_sizes() -> None:
    assert fasteners.size_for_clearance(6.6) == {"d": 6, "class": "medium", "exact": True, "nominal_hole": 6.6}
    assert fasteners.size_for_clearance(9.0)["d"] == 8 and fasteners.size_for_clearance(5.5)["d"] == 5
    assert fasteners.size_for_clearance(13.0)["class"] == "fine"
    inexact = fasteners.size_for_clearance(7.5)
    assert inexact["d"] == 6 and not inexact["exact"]
    assert fasteners.size_for_clearance(3.0) is None
    assert fasteners.tap_size(5.0)["d"] == 6 and fasteners.tap_size(6.8)["d"] == 8
    assert fasteners.tap_size(6.0) == {"d": 6, "modelled": "nominal", "drill": 5.0}
    assert fasteners.tap_size(7.6) is None


@pytest.mark.parametrize("d,grip,washers,L_min,L,protrusion", [
    (6, 10.0, "both", 10 + 1.6 + 1.6 + 5.2 + 2 * 1.0, 25, 25 - (10 + 1.6 + 1.6 + 5.2)),      # 20.4 → 25
    (8, 15.0, "both", 15 + 1.6 + 1.6 + 6.8 + 2 * 1.25, 30, 30 - (15 + 1.6 + 1.6 + 6.8)),     # 27.5 → 30
    (6, 9.6, "both", 9.6 + 1.6 + 1.6 + 5.2 + 2.0, 20, 20 - (9.6 + 1.6 + 1.6 + 5.2)),         # exactly 20.0 → 20
    (10, 40.0, "none", 40 + 8.4 + 2 * 1.5, 55, 55 - (40 + 8.4)),                             # 51.4 → 55
    (12, 22.0, "head", 22 + 2.5 + 10.8 + 2 * 1.75, 40, 40 - (22 + 2.5 + 10.8)),              # 38.8 → 40
])
def test_through_bolt_length_hand_cases(d: int, grip: float, washers: str, L_min: float, L: int, protrusion: float) -> None:
    hole = fasteners.CLEARANCE[d][1]
    p = fasteners.propose({"kind": "through", "hole_d": hole, "grip": grip, "members": []}, "hex_bolt", washers)
    assert p["ok"] and p["verify"] is True and p["size"] == d
    assert p["length"]["L_min"] == pytest.approx(L_min, abs=1e-9) and p["length"]["L"] == L
    assert p["length"]["protrusion"] == pytest.approx(protrusion, abs=1e-9)
    assert p["length"]["protrusion"] >= 2 * fasteners.PITCH[d] - 1e-9
    roles = [i["role"] for i in p["items"]]
    assert roles[0] == "screw" and roles[-1] == "nut" and roles.count("washer_head") == (washers != "none")
    assert p["items"][0]["title"] == f"Hex bolt ISO 4017 M{d}×{L}"
    assert "ISO 888" in " ".join(p["sources"]) and "verify" in p["rule"].lower()


def test_tapped_lengths_hand_cases() -> None:
    # M5 SHCS + washer clamping 5 mm into a 10 mm through-tapped steel plate: L ≥ 5 + 1.0 + 1.0 × 5 = 11 → 12
    pr = {"kind": "tapped", "hole_d": 5.5, "grip": 5.0, "members": [],
          "tapped": {"name": "Base", "d": 4.2, "depth": 10.0, "blind": False, "material": "Steel 1045"}}
    p = fasteners.propose(pr, "shcs", "head")
    assert p["ok"] and p["length"]["L_min"] == pytest.approx(11.0) and p["length"]["L"] == 12
    assert p["length"]["engagement"] == pytest.approx(6.0) and [i["role"] for i in p["items"]] == ["screw", "washer_head"]
    assert p["items"][0]["title"] == "Socket head cap screw ISO 4762 M5×12"
    # M6 into a 15 mm blind tapped hole in aluminium: engagement ≥ 2 × 6 = 12, usable thread 15 − 2 × 1.0 = 13,
    # clamped 10 + washer 1.6 → L in [23.6, 24.6]: no ISO 888 length there → honest failure
    pr = {"kind": "tapped", "hole_d": 6.6, "grip": 10.0, "members": [],
          "tapped": {"name": "Base", "d": 5.0, "depth": 15.0, "blind": True, "material": "Aluminium 6061"}}
    p = fasteners.propose(pr, "shcs", "head")
    assert not p["ok"] and p["length"]["L_min"] == pytest.approx(23.6) and p["length"]["L_max"] == pytest.approx(24.6)
    assert "No standard M6 length" in p["error"]
    blocked = fasteners.propose({"kind": "blocked", "hole_d": 6.6, "grip": 0, "reason": "Blocked by X."})
    assert not blocked["ok"] and blocked["error"] == "Blocked by X."


# ----------------------------------------------------------------------------- kernel: fixtures
def _box_step(path: Path, sx: float, sy: float, sz: float, holes: list[tuple[float, float, float]] = ()) -> Path:
    from build123d import Align, Box, Cylinder, Pos, export_step

    part = Box(sx, sy, sz, align=(Align.MIN, Align.MIN, Align.MIN))
    for x, y, d in holes:
        part -= Pos(x, y, -1) * Cylinder(d / 2, sz + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    path.parent.mkdir(parents=True, exist_ok=True)
    export_step(part, str(path))
    return path


def _inst(iid: str, d: Path, info: dict[str, Any], T: np.ndarray, **kw: Any) -> dict[str, Any]:
    return {"id": iid, "name": iid, "step": str(d / "part.step"), "T": xform.to12(T), "bbox": info["bbox"],
            "holes": info["holes"], "material": kw.pop("material", "Steel"), **kw}


@pytest.fixture(scope="module")
def cube20(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    from aicad.assembly import geometry

    root = tmp_path_factory.mktemp("asm_cube")
    info = geometry.prepare(root / "c20", step=str(_box_step(root / "c20.step", 20, 20, 20)))
    return root / "c20", info


def test_prepare_writes_exact_refs_and_holes(tmp_path: Path) -> None:
    from aicad.assembly import geometry

    info = geometry.prepare(tmp_path / "p", step=str(_box_step(tmp_path / "p.step", 60, 40, 12,
                                                               [(10, 10, 6.6), (50, 10, 6.6)])))
    assert info["volume"] == pytest.approx(60 * 40 * 12 - 2 * math.pi * 3.3 ** 2 * 12, rel=1e-9)
    assert [h["d"] for h in info["holes"]] == [6.6, 6.6] and info["patterns"][0]["count"] == 2
    refs = json.loads((tmp_path / "p" / "refs.json").read_text(encoding="utf-8"))
    topo = json.loads((tmp_path / "p" / "topo.json").read_text(encoding="utf-8"))
    for h in info["holes"]:
        f = refs["faces"][str(h["faces"][0])]
        assert f["kind"] == "axis" and f["r"] == pytest.approx(3.3, abs=1e-12)
        assert topo["faces"][h["faces"][0]]["type"] == "cylinder"
    top = [f for f in refs["faces"].values() if f["kind"] == "plane" and f["v"] == pytest.approx([0, 0, 1])]
    assert len(top) == 1 and top[0]["p"][2] == pytest.approx(12.0, abs=1e-12)   # outward normal, exact plane


def test_interference_volume_equals_analytic_overlap(tmp_path: Path, cube20: tuple[Path, dict[str, Any]]) -> None:
    from aicad.assembly import geometry

    d, info = cube20
    a = _inst("a", d, info, xform.ident())
    b = _inst("b", d, info, xform.translate((5, 3, 2)))
    c = _inst("c", d, info, xform.translate((60, 0, 0)))                     # far away: not even a candidate
    touching = _inst("t", d, info, xform.translate((0, 0, -20)))             # face contact only: no volume
    res = geometry.interference([a, b, c, touching])
    pairs = {(p["a"], p["b"]): p for p in res["pairs"]}
    assert pairs[("a", "b")]["volume_mm3"] == pytest.approx(15 * 17 * 18, rel=1e-9)
    assert pairs[("a", "b")]["kind"] == "interference" and pairs[("a", "b")]["mesh"]["idx"]
    assert ("a", "t") not in pairs and ("a", "c") not in pairs and len(pairs) == 1
    # pin Ø10 through an Ø8 hole in a 12 mm plate: overlap = π (5² − 4²) × 12
    plate = geometry.prepare(tmp_path / "pl", step=str(_box_step(tmp_path / "pl.step", 30, 30, 12, [(15, 15, 8)])))
    from build123d import Align, Cylinder, export_step

    export_step(Cylinder(5, 40, align=(Align.CENTER, Align.CENTER, Align.MIN)), str(tmp_path / "pin.step"))
    pin = geometry.prepare(tmp_path / "pin", step=str(tmp_path / "pin.step"))
    res = geometry.interference([_inst("plate", tmp_path / "pl", plate, xform.ident()),
                                 _inst("pin", tmp_path / "pin", pin, xform.translate((15, 15, -10)))])
    assert res["pairs"][0]["volume_mm3"] == pytest.approx(math.pi * (25 - 16) * 12, rel=1e-9)
    # the same overlap inside a fastener's nominal thread Ø is thread engagement, not a clash
    res = geometry.interference([_inst("plate", tmp_path / "pl", plate, xform.ident()),
                                 _inst("pin", tmp_path / "pin", pin, xform.translate((15, 15, -10)),
                                       thread={"d_nom": 10, "p": [0, 0, 0], "d": [0, 0, 1]})])
    assert res["pairs"][0]["kind"] == "thread" and res["pairs"][0]["mesh"] is None


def test_clearance_of_offset_boxes_is_exact(tmp_path: Path) -> None:
    from aicad.assembly import geometry

    info = geometry.prepare(tmp_path / "c10", step=str(_box_step(tmp_path / "c10.step", 10, 10, 10)))
    a = _inst("a", tmp_path / "c10", info, xform.ident())
    b = _inst("b", tmp_path / "c10", info, xform.translate((14, 14, 0)))
    c = _inst("c", tmp_path / "c10", info, xform.make(xform.rot((0, 0, 1), math.radians(90)), (0, 0, 12.5)))
    res = geometry.clearance([a, b, c], [("a", "b", "mate")], near_mm=3.0)
    rows = {(r["a"], r["b"]): r for r in res["rows"]}
    assert rows[("a", "b")]["distance_mm"] == pytest.approx(math.hypot(4, 4), abs=1e-9)
    assert rows[("a", "b")]["why"] == ["mate"]
    # c is rotated 90° about Z about the origin: it spans x ∈ [-10, 0], z ∈ [12.5, 22.5] → 2.5 mm above a's edge
    assert rows[("a", "c")]["distance_mm"] == pytest.approx(2.5, abs=1e-9) and rows[("a", "c")]["why"] == ["near"]
    assert ("b", "c") not in rows                                               # farther than near_mm


def test_step_export_reimport_preserves_tree_and_placements(tmp_path: Path, cube20: tuple[Path, dict[str, Any]]) -> None:
    from build123d import import_step

    from aicad.assembly import geometry

    d, _info = cube20
    T2 = xform.make(xform.rot((1, 1, 0), math.radians(33)), (40, -5, 7))
    nodes = [{"id": "i1", "part_label": "Cube", "step": str(d / "part.step"), "T": xform.to12(xform.ident())},
             {"id": "i2", "part_label": "Cube", "step": str(d / "part.step"), "T": xform.to12(T2),
              "group": "g1", "group_label": "Sub one"},
             {"id": "i3", "part_label": "Cube", "step": str(d / "part.step"),
              "T": xform.to12(xform.translate((0, 50, 0))), "group": "g1", "group_label": "Sub one"}]
    res = geometry.export(tmp_path / "a.step", "Test assembly", nodes)
    assert res["ok"] and res["instances"] == 3 and res["reimported"] == 3 and res["groups"] == 1
    assert res["placement_dev_mm"] < 1e-9
    back = import_step(str(tmp_path / "a.step"))
    kids = list(back.children)
    assert len(kids) == 2 and len(list(kids[1].children)) == 2 and kids[1].label == "Sub_one"
    p = kids[1].children[0].location.position
    got = np.array([p.X, p.Y, p.Z])
    assert np.allclose(got, T2[:3, 3], atol=1e-9)
    txt = (tmp_path / "a.step").read_text(encoding="utf-8", errors="replace")
    assert txt.count("MANIFOLD_SOLID_BREP") == 1                               # one product, three instances


# ----------------------------------------------------------------------------- API (worker process)
PLATE = {"L": 120.0, "W": 80.0, "T": 10.0, "HOLE_D": 6.6, "EDGE": 10.0}


def write_plate(out: Path, build_id: str = "2001", T: float = 10.0) -> None:
    from build123d import Align, Box, Cylinder, Pos, export_step

    L, W = PLATE["L"], PLATE["W"]
    part = Box(L, W, T, align=(Align.CENTER, Align.CENTER, Align.MIN))
    for sx in (-1, 1):
        for sy in (-1, 1):
            part -= Pos(sx * (L / 2 - 10), sy * (W / 2 - 10), -1) * Cylinder(3.3, T + 2,
                                                                              align=(Align.CENTER, Align.CENTER, Align.MIN))
    out.mkdir(parents=True, exist_ok=True)
    export_step(part, str(out / "part.step"))
    (out / "status.json").write_text(json.dumps({"ok": True, "part": "Plate", "material": "Aluminium 6061-T6",
                                                 "build_id": build_id}), encoding="utf-8")


def write_block(out: Path) -> None:
    from build123d import Align, Box, export_step

    out.mkdir(parents=True, exist_ok=True)
    export_step(Box(40, 30, 20, align=(Align.CENTER, Align.CENTER, Align.MIN)), str(out / "part.step"))
    (out / "status.json").write_text(json.dumps({"ok": True, "part": "Block", "material": "Steel 1045",
                                                 "build_id": "3001"}), encoding="utf-8")


@pytest.fixture()
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    from aicad.platform import config
    from aicad.platform.routers import auth as auth_router

    auth_router._attempts.clear()
    monkeypatch.setenv("FW_ADMIN_PASSWORD", "correct horse 42")
    config.override_settings(config.Settings(
        env="development", data_dir=tmp_path / "data", database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
        app_url="http://testserver", superadmin_emails=("boss@example.com",), stripe_secret_key="", trial_tokens=300))
    from aicad.assembly import worker as aworker
    from aicad.platform.app import create_app

    with TestClient(create_app()) as c:
        c.headers.update({"X-FW-CSRF": "1"})
        yield c
        c.portal.call(aworker.shutdown_all)  # type: ignore[union-attr]
    aworker.kill_all()


def _plane_face(view: dict[str, Any], data_dir: Path, org: str, iid: str, nz: float, z: float) -> int:
    inst = next(i for i in view["instances"] if i["id"] == iid)
    refs = json.loads((data_dir / "assemblies" / org / "_parts" / inst["part"] / "refs.json").read_text(encoding="utf-8"))
    return next(int(k) for k, f in refs["faces"].items()
                if f["kind"] == "plane" and abs(f["v"][2] - nz) < 1e-9 and abs(f["p"][2] - z) < 1e-9)


def test_api_full_flow(app_client: Any, tmp_path: Path) -> None:
    from sqlalchemy import select
    from test_platform import signup

    from aicad.platform.db import session_factory
    from aicad.platform.models import Membership, Project, User
    from aicad.platform.routers.projects import workspace_for

    c = app_client
    assert c.get("/api/m/assembly/assemblies").status_code == 401
    signup(c, "asm@x.com")
    r = c.get("/api/m/assembly/assemblies")
    assert r.status_code == 402 and "add-on" in r.json()["detail"]["message"]
    plate_id = c.post("/api/projects", json={"name": "Plate"}).json()["id"]
    block_id = c.post("/api/projects", json={"name": "Block"}).json()["id"]
    db = session_factory()()
    ws_plate = workspace_for(db.get(Project, plate_id))
    ws_block = workspace_for(db.get(Project, block_id))
    org = db.get(Project, plate_id).org_id
    db.close()
    pay = c.post("/api/billing/checkout", json={"product_code": "addon_assembly"}).json()["payment_id"]
    c.post(f"/api/billing/payments/{pay}/simulate", json={"outcome": "success"})
    assert c.get("/api/m/assembly/assemblies").json()["items"] == []
    # not built yet → honest 409
    r = c.post("/api/m/assembly/assemblies", json={"project_id": plate_id})
    assert r.status_code == 409 and "no verified build" in r.json()["detail"]
    write_plate(ws_plate / "out")
    write_block(ws_block / "out")
    v = c.post("/api/m/assembly/assemblies", json={"project_id": plate_id}).json()
    aid = v["assembly"]["id"]
    assert v["assembly"]["name"] == "Plate assembly" and len(v["instances"]) == 1 and v["instances"][0]["fixed"]
    assert c.get(f"/api/m/assembly/for-project/{plate_id}").json()["assembly"]["id"] == aid
    plate_iid = v["instances"][0]["id"]
    part = v["parts"][v["instances"][0]["part"]]
    assert [h["d"] for h in part["holes"]] == [6.6] * 4 and part["patterns"][0]["count"] == 4
    assert c.get(part["topo_url"]).status_code == 200
    # insert the block, move it over the plate centre (clear of the holes) and mate its bottom onto the plate top
    v = c.post(f"/api/m/assembly/assemblies/{aid}/instances", json={"project_id": block_id}).json()
    block_iid = v["result"]["instance"]
    v = c.patch(f"/api/m/assembly/assemblies/{aid}/instances/{block_iid}",
                json={"T": xform.to12(xform.translate((0, 0, 30)))}).json()   # over the plate centre
    data_dir = tmp_path / "data"
    top = _plane_face(v, data_dir, org, plate_iid, 1.0, 10.0)
    bottom = _plane_face(v, data_dir, org, block_iid, -1.0, 0.0)
    v = c.post(f"/api/m/assembly/assemblies/{aid}/mates", json={
        "type": "auto", "a": {"inst": plate_iid, "kind": "face", "id": top},
        "b": {"inst": block_iid, "kind": "face", "id": bottom}}).json()
    blk = next(i for i in v["instances"] if i["id"] == block_iid)
    T = xform.from12(blk["T"])
    assert xform.pt(T, (0, 0, 0))[2] == pytest.approx(10.0, abs=1e-9)   # block bottom on the plate top
    assert v["mates"][0]["label"] == "Coincident" and v["mates"][0]["status"] == "ok"
    assert blk["dof"]["dof"] == 3 and v["solve"]["status"] == "under_defined"   # slides and spins on the plate
    # bad mate pick → clear 409
    r = c.post(f"/api/m/assembly/assemblies/{aid}/mates", json={
        "type": "concentric", "a": {"inst": plate_iid, "kind": "face", "id": top},
        "b": {"inst": block_iid, "kind": "face", "id": bottom}})
    assert r.status_code == 409 and "Concentric needs" in r.json()["detail"]
    # fastener auto-fit on the plate's 4-hole pattern: grip = 10 → M6 × 25 + 2 washers + nut (hand case 1)
    plan = c.post(f"/api/m/assembly/assemblies/{aid}/fasteners/propose",
                  json={"inst": plate_iid, "hole": 0, "pattern": True}).json()
    assert plan["ok"] == 4 and plan["stacks"] == [{"summary": "Hex bolt ISO 4017 M6×25 + 2 washers + nut", "count": 4}]
    h0 = plan["holes"][0]
    assert h0["probe"]["kind"] == "through" and h0["probe"]["grip"] == pytest.approx(10.0, abs=1e-9)
    assert h0["proposal"]["length"]["L"] == 25 and h0["proposal"]["verify"]
    assert "ISO 273 medium clearance hole for M6" in h0["proposal"]["clearance"]["text"]
    v = c.post(f"/api/m/assembly/assemblies/{aid}/fasteners/accept",
               json={"inst": plate_iid, "hole": 0, "pattern": True}).json()
    assert v["result"]["inserted"] == 4 and len(v["instances"]) == 2 + 4 * 4
    assert len([g for g in v["groups"] if g["kind"] == "fastener"]) == 4
    assert v["solve"]["status"] == "under_defined" and not v["solve"]["conflicts"]
    assert v["solve"]["free_spins"] == 16                                      # every fastener only spins
    bolts = [i for i in v["instances"] if i["name"] == "Hex bolt ISO 4017 M6×25"]
    for b in bolts:                                                            # head on the head washer (z = 11.6)
        Tb = xform.from12(b["T"])
        assert xform.pt(Tb, (0, 0, 0))[2] == pytest.approx(10 + 1.6, abs=1e-9)
        assert xform.vec(Tb, (0, 0, 1))[2] == pytest.approx(1.0, abs=1e-12)
    nuts = [i for i in v["instances"] if i["name"] == "Hex nut ISO 4032 M6"]
    assert all(xform.pt(xform.from12(n["T"]), (0, 0, 0))[2] == pytest.approx(-1.6, abs=1e-9) for n in nuts)
    # BOM quantities
    bom = c.get(f"/api/m/assembly/assemblies/{aid}/bom").json()
    q = {r["part"]: r["qty"] for r in bom["rows"]}
    assert q == {"Plate": 1, "Block": 1, "Hex bolt ISO 4017 M6×25": 4, "Washer ISO 7089 M6": 8, "Hex nut ISO 4032 M6": 4}
    assert bom["total_qty"] == 18
    row = next(r for r in bom["rows"] if r["part"] == "Hex bolt ISO 4017 M6×25")
    assert row["standard"] == "ISO 4017" and row["material"] == "Steel 8.8"
    plate_row = next(r for r in bom["rows"] if r["part"] == "Plate")
    plate_vol = 120 * 80 * 10 - 4 * math.pi * 3.3 ** 2 * 10
    assert plate_row["mass_each_g"] == pytest.approx(plate_vol * 2.70 / 1000, abs=0.01)
    csv_text = c.get(f"/api/m/assembly/assemblies/{aid}/bom?format=csv").text
    assert csv_text.splitlines()[0].startswith("Item,Qty,Part") and "Washer ISO 7089 M6" in csv_text
    # interference / clearance: nothing clashes; bolt shank to plate = (6.6 − 6) / 2 = 0.3 mm radial clearance
    an = c.post(f"/api/m/assembly/assemblies/{aid}/analyse").json()["analysis"]
    assert an["interference"]["count"] == 0
    shank = [r for r in an["clearance"]["rows"] if {r["a"], r["b"]} == {bolts[0]["id"], plate_iid}]
    assert shank and shank[0]["distance_mm"] == pytest.approx(0.3, abs=1e-6) and shank[0]["status"] == "clear"
    # explode: washers lift off the plate, bolts further up, nuts down
    ex = v["explode"]
    wid = next(i["id"] for i in v["instances"] if i["group"] == bolts[0]["group"] and i["name"].startswith("Washer")
               and xform.pt(xform.from12(i["T"]), (0, 0, 0))[2] > 5)
    assert ex[plate_iid] == [0, 0, 0] and ex[wid][2] > 0 and ex[bolts[0]["id"]][2] > ex[wid][2]
    assert ex[nuts[0]["id"]][2] < 0
    # STEP export with hierarchy; re-import verified
    e = c.post(f"/api/m/assembly/assemblies/{aid}/export").json()["export"]
    assert e["ok"] and e["instances"] == 18 and e["reimported"] == 18 and e["groups"] == 4
    f = c.get(e["url"])
    assert f.status_code == 200 and f.content.startswith(b"ISO-10303-21")
    # seeded interference: push the block 2 mm into the plate (distance mates can't go negative: move it)
    v = c.patch(f"/api/m/assembly/assemblies/{aid}/mates/{v['mates'][0]['id']}", json={"suppressed": True}).json()
    v = c.patch(f"/api/m/assembly/assemblies/{aid}/instances/{block_iid}", json={"translate": [0, 0, -2]}).json()
    an = c.post(f"/api/m/assembly/assemblies/{aid}/analyse").json()["analysis"]
    assert an["interference"]["count"] == 1
    assert an["interference"]["pairs"][0]["volume_mm3"] == pytest.approx(40 * 30 * 2, rel=1e-9)
    # part updated in the Design Studio → instance flagged, refresh keeps the mates
    v = c.patch(f"/api/m/assembly/assemblies/{aid}/mates/{v['mates'][0]['id']}", json={"suppressed": False}).json()
    write_plate(ws_plate / "out", build_id="2002", T=10.0)
    v = c.get(f"/api/m/assembly/assemblies/{aid}").json()
    assert next(i for i in v["instances"] if i["id"] == plate_iid)["stale"] is True
    v = c.post(f"/api/m/assembly/assemblies/{aid}/instances/{plate_iid}/refresh").json()
    assert v["result"]["refreshed"] == 1 and v["result"]["references_lost"] == 0
    assert next(i for i in v["instances"] if i["id"] == plate_iid)["stale"] is False
    # list thumbnail: PNG only
    import base64

    png = base64.b64encode(bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + b"\0" * 32).decode()
    assert c.post(f"/api/m/assembly/assemblies/{aid}/thumbnail", json={"png_b64": "aGVsbG8=", "rev": 1}).status_code == 400
    assert c.post(f"/api/m/assembly/assemblies/{aid}/thumbnail", json={"png_b64": png, "rev": 7}).status_code == 200
    item = c.get("/api/m/assembly/assemblies").json()["items"][0]
    assert item["own_thumbnail"] and item["thumbnail"].endswith("?v=7") and c.get(item["thumbnail"]).status_code == 200
    # viewers read only
    db = session_factory()()
    me = db.scalar(select(User).where(User.email == "asm@x.com"))
    m = db.scalar(select(Membership).where(Membership.user_id == me.id))
    m.role = "viewer"
    db.commit()
    db.close()
    assert c.get(f"/api/m/assembly/assemblies/{aid}").json()["can_edit"] is False
    assert c.post(f"/api/m/assembly/assemblies/{aid}/analyse").status_code == 403
    assert c.delete(f"/api/m/assembly/assemblies/{aid}/instances/{block_iid}").status_code == 403
    assert c.get(f"/api/m/assembly/assemblies/{aid}/files/assembly.step").status_code == 200
    # another organisation cannot see it
    c.post("/api/auth/logout")
    signup(c, "other@x.com", workspace="Other Co")
    pay = c.post("/api/billing/checkout", json={"product_code": "addon_assembly"}).json()["payment_id"]
    c.post(f"/api/billing/payments/{pay}/simulate", json={"outcome": "success"})
    assert c.get(f"/api/m/assembly/assemblies/{aid}").status_code == 404
    assert c.get(f"/api/m/assembly/assemblies/{aid}/files/assembly.step").status_code == 404
    assert c.get(f"/api/m/assembly/parts/{v['instances'][0]['part']}/topo").status_code == 404
    assert c.get("/api/m/assembly/assemblies").json()["items"] == []


def test_catalog_marks_assembly_live(app_client: Any) -> None:
    cat = app_client.get("/api/billing/catalog").json()
    m = next(x for x in cat["modules"] if x["code"] == "assembly")
    assert m["status"] == "live"
