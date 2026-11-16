"""3D Print Prep: mesh checks, wall thickness, overhangs, orientation ranking, repair, exports and the API.

Expected values are hand calculations from the fixture dimensions (never measured from the built shape).
"""

from __future__ import annotations

import base64
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest
from build123d import Align, Box, Cylinder, Pos, Rot, export_step
from fastapi.testclient import TestClient
from test_platform import admin, app_client, signup  # noqa: F401  (fixture re-export)

from aicad.printprep import analysis, presets, service
from aicad.printprep.bvh import BVH
from aicad.printprep.mesh import (
    Mesh,
    MeshError,
    parse_mesh,
    signed_volume,
    tessellate_shape,
    write_3mf,
    write_stl,
)
from aicad.printprep.repair import repair

MIN = (Align.CENTER, Align.CENTER, Align.MIN)


def _box_mesh(a: float = 20.0, b: float = 10.0, c: float = 5.0) -> Mesh:
    v = np.array([[x, y, z] for z in (0, c) for y in (0, b) for x in (0, a)], dtype=float)
    f = np.array([[0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6], [0, 1, 4], [1, 5, 4],
                  [2, 6, 3], [3, 6, 7], [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5]])
    return Mesh(v, f)


def _report(mesh: Mesh, process: str = "fdm", **over: float) -> dict:
    return analysis.analyse(mesh, BVH(mesh.v, mesh.f), presets.process_settings(process, over),
                            presets.material(presets.PROCESSES[process]["default_material"]))


def _check(rep: dict, cid: str) -> dict:
    return next(c for c in rep["checks"] if c["id"] == cid)


def _t_shape():
    """Stem 10 × 20 × 30 mm under a 50 × 20 × 8 mm bar. Overhang under the bar = (50 - 10) × 20 = 800 mm²."""
    return Box(10, 20, 30, align=MIN) + Pos(0, 0, 30) * Box(50, 20, 8, align=MIN)


# ------------------------------------------------------------------ PRN-001 watertight / manifold
def test_watertight_box_passes_and_box_with_removed_face_fails() -> None:
    m = _box_mesh()
    assert signed_volume(m.v, m.f) == pytest.approx(20 * 10 * 5)
    rep = _report(m)
    for cid in ("PP-01", "PP-02", "PP-03", "PP-05"):
        assert _check(rep, cid)["status"] == "pass", cid
    holed = Mesh(m.v, m.f[2:])  # bottom face (two triangles) removed
    rep = _report(holed)
    wt = _check(rep, "PP-01")
    assert wt["status"] == "fail" and wt["value"] == 4 and rep["topology"]["holes"] == 1
    assert rep["summary"]["status"] == "fail"


def test_inconsistent_winding_and_nonmanifold_are_detected() -> None:
    m = _box_mesh()
    f = m.f.copy()
    f[0] = f[0][[0, 2, 1]]
    assert _check(_report(Mesh(m.v, f)), "PP-03")["status"] == "fail"
    inv = Mesh(m.v, m.f[:, [0, 2, 1]])  # all normals inward: consistent but negative volume
    assert _check(_report(inv), "PP-03")["status"] == "fail"
    fin = Mesh(np.vstack([m.v, [[10, 5, 9]]]), np.vstack([m.f, [[4, 5, 8]]]))  # third face on edge 4-5
    assert _check(_report(fin), "PP-02")["value"] == 1


def test_self_intersection_of_two_overlapping_boxes() -> None:
    a = tessellate_shape(Box(10, 10, 10), 0.05)
    b = tessellate_shape(Pos(3.3, 4.1, 2.7) * Rot(10, 20, 30) * Box(10, 10, 10), 0.05)
    both = Mesh(np.vstack([a.v, b.v]), np.vstack([a.f, b.f + len(a.v)]))
    sx = analysis.self_intersections(both, BVH(both.v, both.f))
    assert sx["run"] and sx["pairs"] > 0
    assert analysis.self_intersections(a, BVH(a.v, a.f))["pairs"] == 0


# ------------------------------------------------------------------ PRN-002 wall thickness
def test_wall_thickness_of_shelled_box_equals_the_wall() -> None:
    t = 1.5  # open-top cup 40 × 30 × 20 with 1.5 mm walls and floor
    cup = Box(40, 30, 20, align=MIN) - Pos(0, 0, t) * Box(40 - 2 * t, 30 - 2 * t, 20, align=MIN)
    m = tessellate_shape(cup, 0.05)
    rep = _report(m)  # FDM: min wall 0.8, warn below 1.2 -> 1.5 mm walls pass
    w = _check(rep, "PP-08")
    assert w["value"] == pytest.approx(t, abs=1e-6) and w["status"] == "pass"
    th = analysis.thickness_map(m, BVH(m.v, m.f), cap=10.0)
    n, _areas, _ = analysis.tri_vectors(m.v, m.f)
    side = np.abs(n[:, 2]) < 1e-9
    assert np.median(th[side]) == pytest.approx(t, abs=1e-6)
    # a stricter process flags the same walls: thin-wall area = all wall faces below the limit
    rep2 = _report(m, min_wall_mm=2.0, warn_wall_mm=3.0)
    assert _check(rep2, "PP-08")["status"] == "fail" and rep2["thickness"]["below_min_mm2"] > 0


# ------------------------------------------------------------------ PRN-003 overhangs
def test_overhang_area_of_t_shape_is_analytic() -> None:
    m = tessellate_shape(_t_shape(), 0.05)
    rep = _report(m)
    asm = next(o for o in rep["orientations"] if o["kind"] == "as_modelled")
    assert asm["overhang_area_mm2"] == pytest.approx((50 - 10) * 20, rel=1e-9)
    assert asm["support_area_mm2"] == pytest.approx(800, rel=1e-9)
    # support envelope: the bar underside sits 30 mm above the bed -> 800 × 30 mm³
    assert asm["support_volume_mm3"] == pytest.approx(800 * 30, rel=1e-6)
    pp14 = next(c for c in asm["checks"] if c["id"] == "PP-14")
    assert pp14["status"] == "warn"
    # bridges: two 20 × 20 mm wings, span 20 mm > 10 mm FDM bridge limit
    assert asm["bridges"]["count"] == 2 and asm["bridges"]["max_span_mm"] == pytest.approx(20)


def test_overhang_angle_threshold_on_a_chamfered_underside() -> None:
    # an underside sloping 30° from horizontal (60° from vertical): needs support at a 45° limit, not at 70°
    from build123d import Plane, Polyline, extrude, make_face

    prof = make_face(Polyline((0, 0), (20, 0), (20, 10), (20 + 10 / np.tan(np.radians(30)), 20), (0, 20),
                              close=True))
    part = extrude(Plane.XZ * prof, amount=-10)
    m = tessellate_shape(part, 0.05)
    slope_area = 10 * (10 / np.sin(np.radians(30)))  # width 10 × slant length
    for ang, expect in ((45.0, slope_area), (70.0, 0.0)):
        rep = _report(m, overhang_deg=ang)
        asm = next(o for o in rep["orientations"] if o["kind"] == "as_modelled")
        assert asm["overhang_area_mm2"] == pytest.approx(expect, rel=1e-9, abs=1e-9), ang


# ------------------------------------------------------------------ PRN-004 orientation
def test_flat_face_down_ranks_above_orientation_needing_supports() -> None:
    m = tessellate_shape(_t_shape(), 0.05)
    rep = _report(m)
    rows = rep["orientations"]
    bar_down = next(o for o in rows if o["down"] == pytest.approx([0, 0, 1]))   # bar top face on the bed
    upright = next(o for o in rows if o["kind"] == "as_modelled")               # stem on the bed, bar overhangs
    assert bar_down["support_area_mm2"] == pytest.approx(0, abs=1e-9)
    assert bar_down["contact_area_mm2"] == pytest.approx(50 * 20)
    assert bar_down["rank"] < upright["rank"]
    assert all(o["support_area_mm2"] < 0.5 for o in rows[:3])
    r = np.array(bar_down["rotation"])
    assert np.allclose(r @ r.T, np.eye(3)) and np.linalg.det(r) == pytest.approx(1)
    assert r @ np.array([0, 0, 1.0]) == pytest.approx([0, 0, -1])
    assert bar_down["height_mm"] == pytest.approx(38)
    assert rows[0]["rationale"] and rows[0]["strength_note"]


def test_build_volume_fit_and_load_direction_note() -> None:
    m = _box_mesh(300, 20, 10)
    rep = _report(m)
    asm = next(o for o in rep["orientations"] if o["kind"] == "as_modelled")
    assert not asm["fits"] and next(c for c in asm["checks"] if c["id"] == "PP-13")["status"] == "fail"
    s = presets.process_settings("fdm")
    note, pen = analysis.strength_note(np.eye(3), s, np.array([0, 0, 1.0]))
    assert pen > 0 and "across layers" in note
    assert analysis.strength_note(np.eye(3), s, np.array([1.0, 0, 0]))[1] == 0


# ------------------------------------------------------------------ PRN-005 repair
def test_repair_fills_a_seeded_hole_and_fixes_normals() -> None:
    m = _box_mesh()
    seeded = Mesh(m.v, np.vstack([m.f[2:], m.f[2:3]]))  # bottom face removed + a duplicate triangle
    seeded.f[3] = seeded.f[3][[0, 2, 1]]               # and one flipped triangle
    fixed, rep = repair(seeded)
    assert rep["before"]["boundary_edges"] == 4 and rep["after"]["boundary_edges"] == 0
    assert rep["after"]["inconsistent_edges"] == 0 and rep["after"]["nonmanifold_edges"] == 0
    assert signed_volume(fixed.v, fixed.f) == pytest.approx(20 * 10 * 5)
    assert any("Filled 1 hole" in a for a in rep["actions"])
    assert any("duplicate" in a for a in rep["actions"])
    inward, rep2 = repair(Mesh(m.v, m.f[:, [0, 2, 1]]))
    assert signed_volume(inward.v, inward.f) == pytest.approx(1000) and "Reversed 1" in " ".join(rep2["actions"])


def test_repair_fills_a_non_convex_planar_hole() -> None:
    m = tessellate_shape(_t_shape(), 0.05)
    n, _, _ = analysis.tri_vectors(m.v, m.f)
    front = n[:, 1] < -0.999  # the T-shaped front face (non-convex, area 10 × 30 + 50 × 8 = 700)
    fixed, rep = repair(Mesh(m.v, m.f[~front]))
    assert rep["after"]["boundary_edges"] == 0
    exact = 10 * 20 * 30 + 50 * 20 * 8
    assert signed_volume(fixed.v, fixed.f) == pytest.approx(exact, rel=1e-9)


# ------------------------------------------------------------------ IO-002 / IO-004 exports
def test_stl_and_3mf_exports_reload_with_the_same_volume(tmp_path: Path) -> None:
    r = 10.0
    shape = Cylinder(r, 20)
    tol = 0.02
    m = tessellate_shape(shape, tol)
    exact = np.pi * r * r * 20
    assert m.meta["deviation"]["max_mm"] <= tol * 1.05
    assert abs(signed_volume(m.v, m.f) - exact) / exact < 2 * tol / r  # chordal error bound ~ 2·sag/r
    for name, writer in (("a.stl", write_stl), ("a.3mf", write_3mf)):
        p = tmp_path / name
        writer(m, p)
        back = parse_mesh(p.read_bytes(), name, "mm")
        assert back.meta["units"] == "mm"
        assert signed_volume(back.v, back.f) == pytest.approx(signed_volume(m.v, m.f), rel=1e-5)
        assert analysis.topology(back)["boundary_edges"] == 0
    with zipfile.ZipFile(tmp_path / "a.3mf") as zf:
        model = zf.read("3D/3dmodel.model").decode()
        assert 'unit="millimeter"' in model
    write_3mf(m, tmp_path / "b.3mf")
    assert (tmp_path / "a.3mf").read_bytes() == (tmp_path / "b.3mf").read_bytes()  # deterministic


def test_parsers_sniff_types_and_respect_units() -> None:
    m = _box_mesh()
    ascii_stl = "solid t\n" + "".join(
        "facet normal 0 0 0\nouter loop\n" + "".join(f"vertex {x} {y} {z}\n" for x, y, z in m.v[t]) +
        "endloop\nendfacet\n" for t in m.f) + "endsolid t\n"
    a = parse_mesh(ascii_stl.encode(), "x.stl", "in")
    assert a.meta["format"] == "stl-ascii" and signed_volume(a.v, a.f) == pytest.approx(1000 * 25.4 ** 3)
    obj = "".join(f"v {x} {y} {z}\n" for x, y, z in m.v) + "".join(f"f {a + 1} {b + 1} {c + 1}\n" for a, b, c in m.f)
    o = parse_mesh(obj.encode(), "x.obj", "mm")
    assert o.meta["format"] == "obj" and signed_volume(o.v, o.f) == pytest.approx(1000)
    with pytest.raises(MeshError):
        parse_mesh(b"\x00\x01binary junk" * 20, "x.stl", "mm")
    with pytest.raises(MeshError):
        parse_mesh(b"hello world", "x.obj", "mm")
    bad = b"\x00" * 80 + struct.pack("<I", 10 ** 7)  # claims 10M triangles but is not that long
    with pytest.raises(MeshError):
        parse_mesh(bad, "x.stl", "mm")


# ------------------------------------------------------------------ API
def _grant(c: TestClient) -> None:
    from aicad.platform.db import session_factory
    from aicad.platform.models import Entitlement

    me = c.get("/api/auth/me").json()
    db = session_factory()()
    db.add(Entitlement(org_id=me["org"]["id"], module="print", source="grant"))
    db.commit()
    db.close()


def _stl_bytes(m: Mesh, tmp: Path) -> bytes:
    p = tmp / "u.stl"
    write_stl(m, p)
    return p.read_bytes()


def test_api_auth_scoping_upload_limits_and_flow(app_client: TestClient, tmp_path: Path) -> None:  # noqa: F811
    c = app_client
    assert c.get("/api/m/print/presets").status_code == 401
    signup(c, "print@x.com")
    pid = c.post("/api/projects", json={"name": "Tee"}).json()["id"]
    r = c.post(f"/api/m/print/projects/{pid}/analyse", json={})
    assert r.status_code == 402 and "3D Print Prep" in r.json()["detail"]["message"]
    _grant(c)
    assert c.get("/api/m/print/presets").json()["processes"]["fdm"]["min_wall_mm"] == 0.8
    assert c.post(f"/api/m/print/projects/{pid}/analyse", json={}).status_code == 409  # not built yet
    # write a verified model into the workspace (as a Studio build would)
    from aicad.platform.db import session_factory
    from aicad.platform.models import Project
    from aicad.platform.routers.projects import workspace_for

    db = session_factory()()
    ws = workspace_for(db.get(Project, pid))
    db.close()
    (ws / "out").mkdir(parents=True, exist_ok=True)
    export_step(_t_shape(), str(ws / "out" / "part.step"))
    r = c.post(f"/api/m/print/projects/{pid}/analyse", json={"process": "fdm", "tolerance": 0.05})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["disclosure"].startswith("Not slicer-verified")
    assert rep["source"]["exact_volume_mm3"] == pytest.approx(10 * 20 * 30 + 50 * 20 * 8)
    best = rep["orientations"][0]
    assert best["support_area_mm2"] < 0.5
    mesh = c.get(f"/api/m/print/projects/{pid}/mesh?{rep['mesh_query']}")
    assert mesh.status_code == 200 and mesh.content[:4] == b"FWPM"
    nv, nf = struct.unpack_from("<II", mesh.content, 4)
    assert len(mesh.content) == 16 + nv * 12 + nf * 12 + nf * 4
    ex = c.post(f"/api/m/print/projects/{pid}/export", json={"format": "3mf", "rotation": best["rotation"],
                                                              "tag": best["id"], "label": best["label"]})
    assert ex.status_code == 200, ex.text
    assert ex.json()["volume_match"] and ex.json()["units"] == "mm" and ex.json()["bbox_mm"][2] == pytest.approx(best["height_mm"])
    dl = c.get(ex.json()["url"])
    assert dl.status_code == 200 and dl.content[:2] == b"PK"
    assert (ws / "print" / ex.json()["name"]).is_file()
    bad_rot = c.post(f"/api/m/print/projects/{pid}/export", json={"rotation": [[2, 0, 0], [0, 1, 0], [0, 0, 1]]})
    assert bad_rot.status_code == 422
    assert c.get(f"/api/m/print/projects/{pid}/files/..%2Fmodel.py").status_code == 404
    assert c.post(f"/api/m/print/projects/{pid}/analyse", json={"tolerance": 5}).status_code == 422
    assert c.post(f"/api/m/print/projects/{pid}/analyse", json={"overrides": {"evil": 1}}).status_code == 422

    # uploads: sniffing, size limit, repair flow
    junk = base64.b64encode(b"\x00\x01\x02" * 100).decode()
    assert c.post("/api/m/print/uploads", json={"filename": "x.stl", "data_b64": junk}).status_code == 415
    assert c.post("/api/m/print/uploads", json={"filename": "x.stl", "data_b64": "!!notb64"}).status_code == 400
    from aicad.printprep import mesh as mesh_mod

    big = base64.b64encode(b"0" * 64).decode()
    old = mesh_mod.MAX_UPLOAD_BYTES
    import aicad.platform.routers.mod_print as mp

    mp.MAX_UPLOAD_BYTES = 32
    try:
        assert c.post("/api/m/print/uploads", json={"filename": "x.stl", "data_b64": big}).status_code == 413
    finally:
        mp.MAX_UPLOAD_BYTES = old
    holed = _box_mesh()
    holed = Mesh(holed.v, holed.f[2:])
    data = base64.b64encode(_stl_bytes(holed, tmp_path)).decode()
    up = c.post("/api/m/print/uploads", json={"filename": "broken box.stl", "data_b64": data, "units": "mm"})
    assert up.status_code == 200, up.text
    uid = up.json()["id"]
    assert [u["id"] for u in c.get("/api/m/print/uploads").json()["items"]] == [uid]
    rep = c.post(f"/api/m/print/uploads/{uid}/analyse", json={}).json()
    assert next(x for x in rep["checks"] if x["id"] == "PP-01")["status"] == "fail"
    fx = c.post(f"/api/m/print/uploads/{uid}/repair").json()
    assert fx["repair"]["after"]["boundary_edges"] == 0 and fx["upload"]["repaired"]
    rep = c.post(f"/api/m/print/uploads/{uid}/analyse", json={}).json()
    assert next(x for x in rep["checks"] if x["id"] == "PP-01")["status"] == "pass"
    assert rep["estimates"]["volume_mm3"] == pytest.approx(1000)
    ex = c.post(f"/api/m/print/uploads/{uid}/export", json={"format": "stl"})
    assert ex.status_code == 200 and ex.json()["volume_match"]

    # another workspace cannot see either the project or the upload
    c.post("/api/auth/logout")
    signup(c, "other@x.com", workspace="Other Co")
    _grant(c)
    assert c.post(f"/api/m/print/projects/{pid}/analyse", json={}).status_code == 404
    assert c.post(f"/api/m/print/uploads/{uid}/analyse", json={}).status_code == 404
    assert c.get(f"/api/m/print/uploads/{uid}/files/{ex.json()['name']}").status_code == 404
    assert c.get("/api/m/print/uploads").json()["items"] == []
    service.clear_cache()


def test_catalog_marks_print_live() -> None:
    from aicad.platform.catalog import MODULES

    assert MODULES["print"]["status"] == "live"
