"""Manufacturing Advisor: DFM rules (CHK-13) on seeded fixtures with hand-checked measurements, turning detection,
process ranking sanity, relative cost model, report and API (auth, entitlement, scoping, roles).

Every rule has a fixture that triggers it and one that doesn't. Expected numbers are hand calculations from the
fixture dimensions, never measured from the built shape.
"""

from __future__ import annotations

import itertools
import json
import math
import runpy
from pathlib import Path
from typing import Any

import pytest
from build123d import (
    Align,
    Box,
    Cylinder,
    Plane,
    Polygon,
    Pos,
    Rectangle,
    RectangleRounded,
    SlotCenterToCenter,
    extrude,
)
from fastapi.testclient import TestClient
from test_platform import _project_with_model, admin, app_client, signup  # noqa: F401  (fixture re-export)

from aicad.manufacturing import standards as S
from aicad.manufacturing.analyze import Inputs, analyse_shape
from aicad.manufacturing.cost import QUANTITIES
from aicad.manufacturing.geometry import PartGeom
from aicad.manufacturing.shop import Machine, ShopProfile

DEMO = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo"
BOT = (Align.CENTER, Align.CENTER, Align.MIN)


def demo(name: str) -> Any:
    return runpy.run_path(str(DEMO / f"{name}.py"))["result"]


def run(shape: Any, material: str = "al_6061", quantity: int = 10, tolerance: str = "general",
        **shop: Any) -> dict[str, Any]:
    return analyse_shape(shape, ShopProfile(**shop), Inputs(quantity=quantity, material=material,
                                                            tolerance=tolerance))  # type: ignore[arg-type]


def rule(a: dict[str, Any], rid: str, severity: str | None = None) -> list[dict[str, Any]]:
    return [f for f in a["findings"] if f["rule"] == rid and (severity is None or f["severity"] == severity)]


def pocket(w: float, h: float, depth: float, r: float | None, block: tuple[float, float, float] = (60, 40, 20),
           at: tuple[float, float] = (0, 0)) -> Any:
    L, W, T = block
    prof = RectangleRounded(w, h, r) if r else Rectangle(w, h)
    return Box(L, W, T, align=BOT) - Pos(at[0], at[1], T - depth) * extrude(prof, amount=depth)


def blind_hole(d: float, depth: float, block: tuple[float, float, float] = (40, 40, 20)) -> Any:
    L, W, T = block
    return Box(L, W, T, align=BOT) - Pos(0, 0, T - depth) * Cylinder(d / 2, depth, align=BOT)


# ----------------------------------------------------------------------------- standards tables
def test_standard_tables() -> None:
    assert S.match_standard_hole(6.6) == ["ISO 273 medium clearance for M6"]
    assert S.match_standard_hole(5.0) == ["tap drill for M6 coarse"]
    assert "ISO 273 fine clearance for M8" in S.match_standard_hole(8.4)
    assert S.is_stock_drill(7.3) and S.is_stock_drill(14.5) and S.is_stock_drill(25.0) and S.is_stock_drill(2.05)
    assert not S.is_stock_drill(6.37) and not S.is_stock_drill(14.2)
    assert S.nearest_stock_drill(6.37) == 6.4 and S.nearest_stock_drill(14.2) == 14.0
    assert S.fmt(90.3, 0) == "90" and S.fmt(3.0) == "3" and S.fmt(6.60) == "6.6"


# ----------------------------------------------------------------------------- geometry basics
def test_edges_and_faces_classified_on_a_pocketed_block() -> None:
    g = PartGeom(pocket(30, 20, 8, 3))
    cyl = [f for f in g.faces if f.kind == "cylinder"]
    assert len(cyl) == 4 and all(f.concave and abs(f.radius - 3) < 1e-9 for f in cyl)
    assert all(abs(f.sweep - math.pi / 2) < 1e-6 for f in cyl)
    # pocket floor: 4 straight + 4 arc concave edges; walls meet corners tangentially (8 smooth)
    assert sum(e.convexity == "concave" for e in g.edges) == 8
    assert sum(e.convexity == "smooth" for e in g.edges) == 8
    assert g.volume == pytest.approx(60 * 40 * 20 - (30 * 20 - (4 - math.pi) * 9) * 8, rel=1e-9)


# ----------------------------------------------------------------------------- DFM-HOLE-01  depth / diameter
def test_hole_ld_flags_10mm_deep_d2_hole_as_ld_5() -> None:
    a = run(blind_hole(2.0, 10.0))
    f = rule(a, "DFM-HOLE-01")
    assert len(f) == 1 and f[0]["severity"] == "warning"
    assert f[0]["value"] == pytest.approx(10.0 / 2.0)  # L/D = 5 > 4 (recommended)
    h = a["signals"]["holes"]
    assert len(h) == 1 and h[0]["d"] == pytest.approx(2.0) and h[0]["depth"] == pytest.approx(10.0)
    assert not h[0]["through"]
    assert rule(a, "DFM-HOLE-03")  # cut with a cylinder: flat bottom noted
    deep = run(blind_hole(1.0, 15.0))
    assert rule(deep, "DFM-HOLE-01", "critical")[0]["value"] == pytest.approx(15.0)  # L/D 15 > 10


def test_hole_ld_passes_shallow_hole_and_follows_shop_limit() -> None:
    assert not rule(run(blind_hole(6.0, 10.0)), "DFM-HOLE-01")  # L/D 1.67
    assert not rule(run(blind_hole(2.0, 10.0), max_drill_ld=6.0), "DFM-HOLE-01")  # shop allows 6 x D


# ----------------------------------------------------------------------------- DFM-HOLE-02  standard diameters
def test_hole_standard_sizes() -> None:
    std = rule(run(blind_hole(6.6, 8.0)), "DFM-HOLE-02")
    assert len(std) == 1 and std[0]["severity"] == "info" and "ISO 273 medium clearance for M6" in std[0]["limit"]
    odd = rule(run(blind_hole(6.37, 8.0)), "DFM-HOLE-02")
    assert len(odd) == 1 and odd[0]["severity"] == "warning" and "6.4" in odd[0]["limit"]
    assert not rule(run(blind_hole(7.3, 8.0)), "DFM-HOLE-02")  # stocked drill, not a fastener size: silent


# ----------------------------------------------------------------------------- DFM-CNC-01  corner radius vs tool
def test_pocket_corner_r1_vs_d6_tool_is_critical() -> None:
    a = run(pocket(30, 20, 8, 1.0), smallest_tool_d_mm=6.0)
    f = rule(a, "DFM-CNC-01", "critical")
    assert len(f) == 1 and f[0]["value"] == pytest.approx(1.0) and len(f[0]["faces"]) == 4
    assert "R3" in f[0]["limit"]  # tool radius 6 / 2


def test_corner_radius_passes_and_depth_rule() -> None:
    assert not rule(run(pocket(30, 20, 8, 4.0), smallest_tool_d_mm=6.0), "DFM-CNC-01")  # R4 >= 3 and >= 8/3
    deep = rule(run(pocket(30, 20, 12, 2.0, block=(60, 40, 20)), smallest_tool_d_mm=3.0), "DFM-CNC-01")
    assert len(deep) == 1 and deep[0]["severity"] == "warning"  # R2 >= 1.5, but < 12 / 3 = 4
    assert "R4" in deep[0]["limit"]


def test_advice_changes_with_shop_profile() -> None:
    plate = demo("mounting_plate")  # pocket corners R3
    assert not rule(run(plate, smallest_tool_d_mm=3.0), "DFM-CNC-01")
    f = rule(run(plate, smallest_tool_d_mm=8.0), "DFM-CNC-01", "critical")
    assert f and f[0]["value"] == pytest.approx(3.0)


# ----------------------------------------------------------------------------- DFM-CNC-02  sharp internal corners
def test_sharp_internal_pocket_corners_flagged_open_step_not() -> None:
    a = run(pocket(30, 20, 8, None))
    f = rule(a, "DFM-CNC-02", "critical")
    assert len(f) == 1 and "4 concave edges" in f[0]["measured"] and len(f[0]["faces"]) == 4
    step = Box(40, 40, 20, align=BOT) - Pos(10, 0, 10) * Box(20, 40, 10, align=BOT)  # open shoulder: floor reachable
    assert not rule(run(step), "DFM-CNC-02")


# ----------------------------------------------------------------------------- DFM-CNC-04  deep / narrow cavity
def test_deep_narrow_slot() -> None:
    slot = Box(40, 30, 30, align=BOT) - Pos(0, 0, 10) * extrude(SlotCenterToCenter(16, 4), amount=20)
    a = run(slot)
    f = rule(a, "DFM-CNC-04", "warning")
    assert len(f) == 1 and f[0]["value"] == pytest.approx(20 / 4, rel=1e-6)  # depth 20 / width 4
    narrow = Box(40, 30, 30, align=BOT) - Pos(0, 0, 25) * extrude(SlotCenterToCenter(16, 2), amount=5)
    assert rule(run(narrow, smallest_tool_d_mm=3.0), "DFM-CNC-04", "critical")[0]["value"] == pytest.approx(2.0)
    assert not rule(run(pocket(30, 20, 8, 4.0)), "DFM-CNC-04")  # 8 / 20 = 0.4


# ----------------------------------------------------------------------------- DFM-CNC-05  thin walls
def test_thin_wall_measured_exactly() -> None:
    # pocket x from -19.5 to 10.5 in a block from -20 to 20: a 0.5 mm wall on the -X side
    a = run(pocket(30, 20, 15, 3.0, block=(40, 30, 20), at=(-4.5, 0)))
    f = rule(a, "DFM-CNC-05")
    assert len(f) == 1 and f[0]["severity"] == "warning" and f[0]["value"] == pytest.approx(0.5, abs=1e-6)
    assert a["signals"]["min_wall_mm"] == pytest.approx(0.5, abs=1e-6)
    ok = run(pocket(30, 20, 15, 3.0, block=(40, 30, 20), at=(-3.0, 0)))  # 2 mm wall
    assert not rule(ok, "DFM-CNC-05")
    assert rule(run(pocket(30, 20, 15, 3.0, block=(40, 30, 20), at=(-3.0, 0)), material="abs",
                    min_wall_plastic_mm=2.5), "DFM-CNC-05")  # plastics limit from the shop profile


# ----------------------------------------------------------------------------- DFM-CNC-06/07  undercuts, setups
def test_t_slot_is_an_undercut_plain_slot_is_not() -> None:
    blk = Box(40, 80, 20, align=BOT)
    tslot = blk - Pos(0, 0, 10) * Box(10, 80, 10, align=BOT) - Pos(0, 0, 6) * Box(20, 80, 4, align=BOT)
    a = run(tslot)
    assert rule(a, "DFM-CNC-06", "warning") and a["signals"]["undercut_faces"]
    plain = blk - Pos(0, 0, 10) * Box(10, 80, 10, align=BOT)
    assert not rule(run(plain), "DFM-CNC-06")


def test_setup_count() -> None:
    a = run(Box(40, 40, 20, align=BOT))
    assert a["signals"]["setups"] == ["+Z", "-Z"] and rule(a, "DFM-CNC-07", "info")
    cube = Box(40, 40, 40, align=BOT) - Pos(0, 0, 32) * Cylinder(3, 8, align=BOT) \
        - Pos(12, 0, 20) * (Plane.YZ * Cylinder(3, 16, align=BOT))  # blind hole in the +X face
    b = run(cube)
    f = rule(b, "DFM-CNC-07", "warning")
    assert len(b["signals"]["setups"]) == 3 and f and f[0]["faces"]


# ----------------------------------------------------------------------------- DFM-CNC-08  envelope
def test_envelope_vs_machine_travel() -> None:
    plate = demo("mounting_plate")  # 120 x 80 x 10
    small = [Machine(name="Small mill", kind="mill3", travel_mm=[100, 100, 100], rate_per_hour=60)]
    assert rule(run(plate, machines=small), "DFM-CNC-08", "critical")
    assert not rule(run(plate), "DFM-CNC-08")


# ----------------------------------------------------------------------------- edges
def test_acute_edge_wedge() -> None:
    wedge = extrude(Polygon((0, 0), (40, 0), (0, 15), align=None), amount=10)  # ~20.6 deg tip
    f = rule(run(wedge), "DFM-EDGE-01", "warning")
    assert f and f[0]["value"] == pytest.approx(math.degrees(math.atan2(15, 40)), abs=1e-6)
    assert not rule(run(Box(20, 20, 20)), "DFM-EDGE-01")


# ----------------------------------------------------------------------------- turning (MFG-010)
def test_turning_detected_on_demo_shaft() -> None:
    a = run(demo("stepped_shaft"), material="steel_1045")
    t = a["signals"]["turning"]
    assert t["turnable"] and t["axis"] == "+Z"
    assert t["max_diameter"] == pytest.approx(25.0) and t["length"] == pytest.approx(150.0)
    assert rule(a, "TRN-01") and rule(a, "TRN-02")[0]["value"] == pytest.approx(150 / 25)
    assert len(rule(a, "TRN-04")[0]["faces"]) == 5  # keyway: floor, two walls, two ends
    assert rule(a, "TRN-03")  # two sharp shoulders Ø20 / Ø25
    assert rule(a, "DFM-CNC-02", "critical")  # keyway ends are sharp: milling leaves the cutter radius
    assert a["process"]["ranking"][0]["process"] == "cnc_turning"


def test_plate_is_not_turnable() -> None:
    a = run(demo("mounting_plate"))
    assert not a["signals"]["turning"]["turnable"]
    assert all(r["status"] == "not applicable" for r in a["chk13"]["rules"] if r["rule"].startswith("TRN"))
    assert a["process"]["ranking"][0]["process"] == "cnc_milling"


# ----------------------------------------------------------------------------- moulding / casting (MFG-013)
def test_draft_check() -> None:
    box = Box(40, 30, 20, align=BOT)
    f = rule(run(box, material="abs"), "MLD-01")
    assert f and len(f[0]["faces"]) == 4 and f[0]["value"] == pytest.approx(0.0)  # 4 vertical walls, 0 deg
    tapered = extrude(Rectangle(40, 30), amount=20, taper=2)
    assert not rule(run(tapered, material="abs"), "MLD-01")


def test_mould_pull_direction_and_undercuts() -> None:
    one = Box(40, 30, 20, align=BOT) - Pos(0, 0, 10) * (Plane.YZ * Cylinder(3, 60))
    a = run(one, material="abs")
    assert a["signals"]["pull_direction"] == "X" and not rule(a, "MLD-02")  # pulling along the hole avoids a core
    two = one - Pos(0, 0, 10) * (Plane.XZ * Cylinder(3, 60))  # a second, crossing side hole along Y
    f = rule(run(two, material="abs"), "MLD-02", "warning")
    assert f and f[0]["faces"]
    assert not rule(run(Box(40, 30, 20, align=BOT), material="abs"), "MLD-02")


# ----------------------------------------------------------------------------- process ranking (MFG-014)
def test_process_ranking_sanity() -> None:
    shell = Box(100, 70, 40, align=BOT) - Pos(0, 0, 2.5) * Box(95, 65, 40, align=BOT)  # 2.5 mm open box
    high = run(shell, material="abs", quantity=20000)
    top2 = [r["process"] for r in high["process"]["ranking"][:2]]
    assert "injection_moulding" in top2
    low = run(shell, material="abs", quantity=2)
    im = next(r for r in low["process"]["ranking"] if r["process"] == "injection_moulding")
    assert im["fit"] in ("Poor fit", "Possible") and low["process"]["ranking"][0]["process"] != "injection_moulding"
    assert all(r["confidence"] in ("low", "medium") for r in high["process"]["ranking"])  # never "high"
    br = run(demo("l_bracket"))
    sm = next(r for r in br["process"]["ranking"] if r["process"] == "sheet_metal")
    assert br["signals"]["sheet"]["sheet_like"] and sm["fit"] == "Possible" and sm["score"] <= 60  # MAKE-11
    steel_im = next(r for r in run(Box(20, 20, 20), material="steel_1045")["process"]["ranking"]
                    if r["process"] == "injection_moulding")
    assert not steel_im["feasible"] and steel_im["score"] == 0


# ----------------------------------------------------------------------------- cost (MFG-016/017)
def test_cost_model_monotonic_in_quantity_and_labelled() -> None:
    a = run(demo("mounting_plate"), quantity=25)
    c = a["cost"]
    assert c["label"] == "Relative estimate, not a quote" and c["advice_level"] == "Preliminary estimate"
    assert sorted(set(QUANTITIES + [25])) == c["quantities"]
    for name, pr in c["processes"].items():
        units = [p["unit"] for p in pr["curve"]]
        assert all(b <= a_ + 1e-9 for a_, b in itertools.pairwise(units)), name
        batch = [p["unit"] * p["q"] for p in pr["curve"]]
        assert all(b > a_ for a_, b in itertools.pairwise(batch)), name
    m = c["processes"]["cnc_milling"]
    # hand check: stock (120+6)(80+6)(10+6) mm, Al 2.70 g/cm3, 6.0 per kg placeholder
    assert m["breakdown"]["material"] == pytest.approx(126 * 86 * 16 * 2.70e-6 * 6.0, abs=0.01)
    assert m["setups"] == 2


def test_cost_drivers_cite_features() -> None:
    a = run(demo("stepped_shaft"), material="steel_1045", tolerance="precision")
    titles = [d["title"] for d in a["drivers"]]
    assert any("Sharp internal corners" in t for t in titles)
    assert any("tolerance" in t for t in titles)
    sharp = next(d for d in a["drivers"] if "Sharp internal" in d["title"])
    assert sharp["faces"] and sharp["advice_level"] == "Preliminary estimate"


def test_every_output_carries_an_advice_level() -> None:
    a = run(demo("mounting_plate"))
    assert all(f["advice_level"] == "Recommended check" for f in a["findings"])
    assert a["chk13"]["id"] == "CHK-13" and a["chk13"]["gate"] is False
    assert a["process"]["advice_level"] and a["cost"]["advice_level"]
    assert "not manufacturing approval" in a["disclaimer"] and "not a quote" in a["disclaimer"]
    mat = a["material"]
    assert set(mat["provenance"]) >= {"density_g_cm3", "price_per_kg"} and mat["library_version"]


def test_material_library_is_additive() -> None:
    from aicad import materials
    from aicad.manufacturing import matlib

    lib = matlib.library()
    assert [m["code"] for m in lib] == [m["code"] for m in materials.MATERIALS]
    assert all(m["provenance"]["price_per_kg"].startswith("Formwright placeholder") for m in lib)
    assert materials.get("al_6061")["density_g_cm3"] == 2.70 and materials.guess("6061") == "al_6061"


# ----------------------------------------------------------------------------- report (MFG-018)
def test_report_html_and_pdf() -> None:
    from aicad.manufacturing import report

    shape = demo("mounting_plate")
    a = run(shape)
    import tempfile

    from aicad.topo import export_topology

    with tempfile.TemporaryDirectory() as td:
        topo = export_topology(shape, Path(td) / "t.json")
    h = report.build_html(a, "Plate", topo)
    assert "NOT APPROVED FOR MANUFACTURE" in h and "not a quote" in h and "Rules run" in h
    assert "Where:" in h and "Faces:" not in h  # findings point at features, never at face ids (MAKE-13)
    assert "ISO 273 medium clearance for M6" in h and h.count("data:image/png") >= 2
    pdf = report.build_pdf(a, "Plate", topo)
    assert pdf.startswith(b"%PDF") and len(pdf) > 20_000


# ----------------------------------------------------------------------------- API
def _buy_addon(c: TestClient) -> None:
    pid = c.post("/api/billing/checkout", json={"product_code": "addon_manufacturing"}).json()["payment_id"]
    assert c.post(f"/api/billing/payments/{pid}/simulate", json={"outcome": "success"}).status_code == 200


def test_api_entitlement_analysis_report_and_scoping(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "mfg@x.com")
    r = c.get("/api/m/manufacturing/shop-profile")
    assert r.status_code == 402 and r.json()["detail"]["cta"] == "/app/modules/manufacturing"
    _buy_addon(c)
    prof = c.get("/api/m/manufacturing/shop-profile").json()
    assert prof["is_default"] and prof["can_edit"] and prof["profile"]["smallest_tool_d_mm"] == 3.0
    pid, ws = _project_with_model(c, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))
    r0 = c.get(f"/api/m/manufacturing/projects/{pid}/analysis")
    assert r0.status_code == 200 and r0.json() is None
    a = c.post(f"/api/m/manufacturing/projects/{pid}/analyse", json={"quantity": 50}).json()
    assert a["material"]["code"] == "al_6061" and a["inputs"]["quantity"] == 50
    topo = json.loads((ws / "out" / "topo.json").read_text(encoding="utf-8"))
    hole_ids = sorted(f["id"] for f in topo["faces"] if f["type"] == "cylinder" and abs(f["radius"] - 3.3) < 1e-9)
    std = next(f for f in a["findings"] if f["rule"] == "DFM-HOLE-02")
    assert std["faces"] == hole_ids  # finding face ids are the viewer's topo ids
    assert (ws / "manufacturing" / "analysis.json").is_file()
    got = c.get(f"/api/m/manufacturing/projects/{pid}/analysis").json()
    assert got["cache_key"] == a["cache_key"] and got["stale"] is False
    # shop profile change -> advice changes
    p2 = {**prof["profile"], "smallest_tool_d_mm": 8.0}
    assert c.put("/api/m/manufacturing/shop-profile", json=p2).status_code == 200
    assert c.put("/api/m/manufacturing/shop-profile", json={**p2, "smallest_tool_d_mm": -1}).status_code == 422
    b = c.post(f"/api/m/manufacturing/projects/{pid}/analyse", json={"quantity": 50}).json()
    assert any(f["rule"] == "DFM-CNC-01" and f["severity"] == "critical" for f in b["findings"])
    assert b["cache_key"] != a["cache_key"]
    html = c.get(f"/api/m/manufacturing/projects/{pid}/report.html")
    assert html.status_code == 200 and "NOT APPROVED FOR MANUFACTURE" in html.text
    pdf = c.get(f"/api/m/manufacturing/projects/{pid}/report.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert c.post(f"/api/m/manufacturing/projects/{pid}/analyse", json={"material": "unobtainium"}).status_code == 422
    items = c.get("/api/m/manufacturing/projects").json()["items"]
    assert any(i["id"] == pid and i["analysed"] for i in items)
    # another organisation can't see the project
    c.post("/api/auth/logout")
    signup(c, "other@x.com", workspace="Other Co")
    _buy_addon(c)
    assert c.post(f"/api/m/manufacturing/projects/{pid}/analyse", json={}).status_code == 404
    assert c.get(f"/api/m/manufacturing/projects/{pid}/report.pdf").status_code == 404
    assert c.get("/api/m/manufacturing/shop-profile").json()["is_default"]  # profiles are per org


def test_api_viewer_is_read_only_and_unbuilt_project_409(app_client: TestClient) -> None:  # noqa: F811
    from aicad.platform.db import session_factory
    from aicad.platform.models import Membership

    c = app_client
    me = signup(c, "view@x.com")
    _buy_addon(c)
    empty = c.post("/api/projects", json={"name": "Empty"}).json()["id"]
    assert c.post(f"/api/m/manufacturing/projects/{empty}/analyse", json={}).status_code == 409
    db = session_factory()()
    m = db.query(Membership).filter(Membership.user_id == me["user"]["id"]).one()
    m.role = "viewer"
    db.commit()
    db.close()
    assert c.post(f"/api/m/manufacturing/projects/{empty}/analyse", json={}).status_code == 403
    assert c.put("/api/m/manufacturing/shop-profile", json={}).status_code == 403
    assert c.get("/api/m/manufacturing/shop-profile").json()["can_edit"] is False


def test_api_god_mode_unlock(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    admin(c)
    assert c.patch("/api/god", json={"enabled": True, "bypass_paywall": False}).status_code == 200
    assert c.get("/api/m/manufacturing/meta").status_code == 402  # superadmin without the bypass: still locked
    assert c.patch("/api/god", json={"bypass_paywall": True}).status_code == 200
    assert c.get("/api/m/manufacturing/meta").status_code == 200


# ----------------------------------------------------------------------------- audit fixes (MAKE-10/11/12/13, IDEA-02)
def _plate(**over: float) -> dict[str, Any]:
    src = (DEMO / "mounting_plate.py").read_text(encoding="utf-8")
    for k, v in over.items():
        src = src.replace(f"\n{k} = ", f"\n{k} = {v!r}  # was ", 1)
    import tempfile

    with tempfile.TemporaryDirectory() as td:  # our own demo script with one value changed
        f = Path(td) / "plate.py"
        f.write_text(src, encoding="utf-8")
        return runpy.run_path(str(f))


def test_iso273_clearance_table_matches_the_standard() -> None:
    # ISO 273:1979 table (fine / medium / coarse), typed against the standard
    for thread, row in {"M3": (3.2, 3.4, 3.6), "M5": (5.3, 5.5, 5.8), "M6": (6.4, 6.6, 7.0), "M8": (8.4, 9.0, 10.0),
                        "M10": (10.5, 11.0, 12.0), "M12": (13.0, 13.5, 14.5), "M16": (17.0, 17.5, 18.5),
                        "M20": (21.0, 22.0, 24.0), "M24": (25.0, 26.0, 28.0)}.items():
        assert S.ISO_273[thread] == row, thread
    assert S.clearance_matches(6.6) == [("M6", "medium")] and S.clearance_thread(14.0) == "M12"
    assert S.clearance_neighbours(14.0) == (("M12", "medium", 13.5), ("M12", "coarse", 14.5))
    assert S.tap_drill_matches(14.0) == ["M16"] and S.min_bend_radius("al_6061", 5.0) == (20.0, 4.0)
    assert S.min_bend_radius("al_5052", 2.0) == (3.0, 1.5) and S.min_bend_radius("pla", 2.0) is None
    assert S.nice_up(1.65) == 2.0 and S.nice_up(3.3) == 3.5 and S.nice_up(3.0) == 3.0


def test_through_holes_are_clearance_holes_blind_holes_tap_drills() -> None:
    fl = rule(run(demo("pipe_flange"), material="steel_1018"), "DFM-HOLE-02")
    assert len(fl) == 1 and fl[0]["severity"] == "warning"  # MAKE-12: no longer "tap drill for M16, no action"
    assert "between M12 medium Ø13.5 and M12 coarse Ø14.5" in fl[0]["measured"] and "No action" not in fl[0]["fix"]
    assert fl[0]["target"]["to"] == 13.5 and fl[0]["where"] == "6× Ø14 through holes"
    pl = rule(run(demo("mounting_plate")), "DFM-HOLE-02")
    assert pl[0]["severity"] == "info" and "ISO 273 medium clearance for M6" in pl[0]["limit"]
    tap = rule(run(blind_hole(5.0, 10.0)), "DFM-HOLE-02")
    assert tap and "tap drill for M6 coarse" in tap[0]["limit"] and "thread" in tap[0]["fix"]


def test_keyway_finding_attaches_to_turning_and_counts_are_never_filtered() -> None:
    a = run(demo("stepped_shaft"), material="steel_1045")
    kw = rule(a, "DFM-CNC-02", "critical")[0]
    assert kw["also"] == ["cnc_turning"]  # MAKE-10: shown under the primary (turning) view
    assert kw["where"] == "keyway 6 × 30 mm on the Ø25 section"  # hand: KW 6, KL 30, D2 25
    assert "R = width / 2 = R3" in kw["fix"]
    assert a["summary"]["critical"] == 1 and a["chk13"]["counts"] == a["summary"]
    assert not a["screens"]["moulding_casting"]["shown"]  # steel at qty 10: casting/moulding not shortlisted
    assert a["screens"]["cnc_turning"]["shown"] and a["process"]["ranking"][0]["process"] == "cnc_turning"


def _formed_l(r_in: float, t: float, w: float = 30.0, leg: float = 40.0) -> Any:
    """An L bent from sheet: quarter-annulus bend (inside r_in, outside r_in + t) plus two flat legs."""
    ro = r_in + t
    ring = Cylinder(ro, w) - Cylinder(r_in, w)
    bend = ring & Box(ro + 1, ro + 1, w, align=(Align.MIN, Align.MIN, Align.CENTER))
    leg1 = Pos(r_in, -leg, -w / 2) * Box(t, leg, w, align=(Align.MIN, Align.MIN, Align.MIN))
    leg2 = Pos(-leg, r_in, -w / 2) * Box(leg, t, w, align=(Align.MIN, Align.MIN, Align.MIN))
    return bend + leg1 + leg2


def test_sheet_metal_rules_and_score_cap() -> None:
    br = run(demo("l_bracket"))  # 6061-T6, t = 5, inside R3, outside sharp
    r1, r2 = rule(br, "SHM-01", "critical"), rule(br, "SHM-02", "critical")
    assert r1 and r1[0]["value"] == pytest.approx(3.0) and "≥ R20" in r1[0]["limit"]  # 4 t = 20 (band 4.8 < t ≤ 6.4)
    assert r1[0]["target"]["to"] == 20.0
    assert r2 and "R8" in r2[0]["limit"]  # outside = 3 + 5
    sm = next(r for r in br["process"]["ranking"] if r["process"] == "sheet_metal")
    assert sm["fit"] != "Good fit" and sm["critical"] == 2 and br["screens"]["sheet_metal"]["shown"]
    ok = run(_formed_l(3.0, 2.0), material="al_5052")  # 5052-H32 at 2 mm: 1.5 t = R3 minimum, outside R5
    assert ok["signals"]["sheet"]["sheet_like"] and rule(ok, "SHM-00")
    assert not rule(ok, "SHM-01") and not rule(ok, "SHM-02")
    hard = run(_formed_l(3.0, 2.0), material="al_6061")  # 6061-T6 at 2 mm: 2 t = R4
    f = rule(hard, "SHM-01", "critical")
    assert f and "≥ R4" in f[0]["limit"] and not rule(hard, "SHM-02")


def test_unanalysed_processes_are_capped() -> None:
    shell = Box(100, 70, 40, align=BOT) - Pos(0, 0, 2.5) * Box(95, 65, 40, align=BOT)
    a = run(shell, material="abs", quantity=2)
    for r in a["process"]["ranking"]:
        if r["process"] in ("fdm", "sla", "sls"):
            assert not r["analysed"] and r["score"] <= 60 and r["fit"] != "Good fit"
    assert "Verified calculation" not in json.dumps(a)  # only a signed calculation set carries that level


def test_parameter_fix_maps_one_compatible_parameter() -> None:
    from aicad.manufacturing import fixes

    ns = _plate(PR=1.0)
    a = run(ns["result"], smallest_tool_d_mm=6.0)
    f = rule(a, "DFM-CNC-01", "critical")[0]
    assert f["target"] == {"kind": "radius", "to": 3.5, "why": "≥ R3.3"}  # hand: 6 / 2 × 1.1 = 3.3, up to 0.5 step
    params, meta = dict(ns["PARAMS"]), ns["PARAM_META"]
    act = fixes.param_fix(f, params, meta)
    assert act and act["param"] == "PR" and act["from"] == 1.0 and act["to"] == 3.5
    assert act["label"] == "Set Corner radius 1 → 3.5 mm"  # CH = 1.0 too, but a chamfer is not a radius
    assert fixes.param_fix(f, {**params, "R_EDGE": 1.0}, meta) is None  # two radius parameters equal 1: ambiguous
    assert fixes.param_fix(f, params, {**meta, "PR": {**meta["PR"], "max": 3}}) is None  # outside its limits
    assert fixes.param_fix(f, {"N_HOLES": 1}, {}) is None
    assert fixes.param_kinds("FILLET_IN") == {"radius"} and fixes.param_kinds("BOLT_D") == {"diameter"}
    out = fixes.attach(a, params, meta)
    acts = {g["rule"]: g["action"] for g in out["findings"]}
    assert acts["DFM-CNC-01"]["kind"] == "param" and acts["DFM-EDGE-02"]["kind"] == "note"
    shaft = fixes.attach(run(demo("stepped_shaft"), material="steel_1045"), {"KW": 6.0, "KL": 30.0}, {})
    kw = next(g for g in shaft["findings"] if g["rule"] == "DFM-CNC-02")["action"]
    assert kw["kind"] == "studio" and "keyway 6 × 30 mm on the Ø25 section" in kw["prompt"]
    assert "F-0" not in kw["prompt"] and "face" not in kw["prompt"].lower()


def test_fix_delta_hand_case() -> None:
    from aicad.manufacturing import fixes

    def an(c: int, w: int, unit: float) -> dict[str, Any]:
        return {"summary": {"critical": c, "warning": w, "info": 3},
                "cost": {"primary": "cnc_milling", "processes": {"cnc_milling": {"unit_cost": unit}}}}

    d = fixes.delta(an(1, 2, 50.0), an(0, 2, 46.0))
    assert d["critical"] == {"before": 1, "after": 0} and d["cost"]["pct"] == -8.0  # (46 - 50) / 50
    assert d["text"] == "critical 1 → 0; unit cost -8.0 %"
    assert fixes.delta(an(0, 0, 10.0), an(0, 0, 10.0))["text"] == "no change in findings or cost"


def test_api_fix_rebuilds_and_reports_the_delta(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "fix@x.com")
    _buy_addon(c)
    src = (DEMO / "mounting_plate.py").read_text(encoding="utf-8").replace("\nPR = 3.0", "\nPR = 1.0", 1)
    pid, _ws = _project_with_model(c, src)
    a = c.post(f"/api/m/manufacturing/projects/{pid}/analyse", json={}).json()
    f = next(x for x in a["findings"] if x["rule"] == "DFM-CNC-01" and x["severity"] == "critical")
    assert a["build"]["build_id"] and a["freshness"]["state"] == "current" and a["summary"]["critical"] >= 1
    act = f["action"]
    assert act["kind"] == "param" and act["param"] == "PR" and act["to"] == 2.0  # 3 / 2 × 1.1 = 1.65 -> 2
    bad = c.post(f"/api/m/manufacturing/projects/{pid}/fix", json={"finding": f["id"], "param": "L", "value": 200})
    assert bad.status_code == 409
    r = c.post(f"/api/m/manufacturing/projects/{pid}/fix", json={"finding": f["id"], "param": "PR", "value": 2.0})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["delta"]["critical"]["after"] == d["delta"]["critical"]["before"] - 1
    assert not any(x["rule"] == "DFM-CNC-01" and x["severity"] == "critical" for x in d["analysis"]["findings"])
    assert c.get(f"/api/projects/{pid}/params").json()["editable"]["PR"] == 2.0
    assert c.get(f"/api/m/manufacturing/projects/{pid}/analysis").json()["stale"] is False
