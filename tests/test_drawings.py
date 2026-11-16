"""Drawing Studio: views, dimensions, callouts, CHK-12, exports, determinism, associativity and the API.

Fixture FX-DRW-1 (original): a 100 x 60 x 20 mm block (centred on X/Y, sitting on Z = 0) with four Ø8 through
holes at (±40, ±20) and one Ø6 blind hole 10 mm deep from the top at the centre. Every expected number below is
derived by hand from those inputs, never measured from the built shape.
"""

from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from trial_helpers import set_trial_ended

from aicad.drawing import geometry
from aicad.drawing.check import chk12
from aicad.drawing.dims import candidates, fmt, param_kind, tag
from aicad.drawing.generate import generate, normalize_options

L, W, T = 100.0, 60.0, 20.0
HOLE_D, EDGE, BLIND_D, BLIND_DEPTH = 8.0, 10.0, 6.0, 10.0
PARAMS = {"L": L, "W": W, "T": T, "HOLE_D": HOLE_D, "EDGE": EDGE, "BLIND_D": BLIND_D, "BLIND_DEPTH": BLIND_DEPTH}
META = {"L": {"label": "Length"}, "W": {"label": "Width"}, "T": {"label": "Thickness"},
        "HOLE_D": {"label": "Hole Ø"}, "EDGE": {"label": "Edge distance"}, "BLIND_D": {"label": "Blind hole Ø"},
        "BLIND_DEPTH": {"label": "Blind hole depth"}}
DRAW_META = {"title": "Test block", "drawing_no": "FW-TEST0001", "drawn_by": "Test Engineer", "date": "2026-11-16",
             "model_rev": "1"}


def write_model(out: Path, length: float = L, build_id: str = "1001") -> None:
    """Build the fixture with build123d and write the files a verified build leaves in ``out/``."""
    from build123d import Align, Box, Cylinder, Pos, export_step

    part = Box(length, W, T, align=(Align.CENTER, Align.CENTER, Align.MIN))
    for sx in (-1, 1):
        for sy in (-1, 1):
            x = sx * (length / 2 - EDGE)
            part -= Pos(x, sy * (W / 2 - EDGE), -1) * Cylinder(HOLE_D / 2, T + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part -= Pos(0, 0, T - BLIND_DEPTH) * Cylinder(BLIND_D / 2, BLIND_DEPTH + 1, align=(Align.CENTER, Align.CENTER, Align.MIN))
    out.mkdir(parents=True, exist_ok=True)
    export_step(part, str(out / "part.step"))
    params = {**PARAMS, "L": length}
    (out / "status.json").write_text(json.dumps({
        "ok": True, "part": "Test block", "material": "Aluminium 6061-T6", "params": params, "param_meta": META,
        "build_id": build_id, "fingerprint": {"bbox": [length, W, T]}}), encoding="utf-8")


@pytest.fixture(scope="module")
def model(tmp_path_factory: pytest.TempPathFactory) -> Path:
    ws = tmp_path_factory.mktemp("drw")
    write_model(ws / "out")
    return ws


@pytest.fixture(scope="module")
def analysis(model: Path) -> dict[str, Any]:
    return geometry.analyse(str(model / "out" / "part.step"), ["front", "top", "right", "iso"], "y")


@pytest.fixture(scope="module")
def drawing(model: Path) -> dict[str, Any]:
    return generate(model / "out", model / "drawings", {"section": "y"}, DRAW_META)


# ----------------------------------------------------------------------------- geometry
def test_view_extents_equal_bbox_projections(analysis: dict[str, Any]) -> None:
    bb = analysis["census"]["bbox"]
    assert bb == pytest.approx([-L / 2, -W / 2, 0, L / 2, W / 2, T], abs=1e-6)
    hand = {"front": [-L / 2, L / 2, 0, T], "top": [-L / 2, L / 2, -W / 2, W / 2], "right": [-W / 2, W / 2, 0, T]}
    for view, exp in hand.items():
        assert analysis["views"][view]["extents"] == pytest.approx(exp, abs=0.01), view
        assert geometry.bbox_extents(bb, view) == pytest.approx(exp, abs=1e-9)
    # isometric: half-width of a box seen along (1,-1,1) is (L + W) / (2 * sqrt 2)
    iso = analysis["views"]["iso"]["extents"]
    assert iso[1] - iso[0] == pytest.approx((L + W) / 2 ** 0.5, abs=0.01)


def test_hidden_lines_present_for_holes(analysis: dict[str, Any]) -> None:
    front = analysis["views"]["front"]
    assert front["visible"] and front["hidden"]
    # hole walls seen side-on in the front view: hidden vertical lines at x = ±40 ± 4 (and ±3 for the blind hole)
    xs = {round(p[1], 6) for p in front["hidden"] if p[0] == "line" and abs(p[1] - p[3]) < 1e-9}
    assert {-44.0, -36.0, 36.0, 44.0, -3.0, 3.0} <= xs
    top = analysis["views"]["top"]
    circles = [p for p in top["visible"] if p[0] == "circle"]
    assert sorted(round(p[3] * 2, 6) for p in circles) == [BLIND_D] + [HOLE_D] * 4


def test_census_holes_match_hand_values(analysis: dict[str, Any]) -> None:
    holes = analysis["census"]["holes"]
    thru = [h for h in holes if h["thru"]]
    blind = [h for h in holes if not h["thru"]]
    assert len(thru) == 4 and all(h["dia"] == HOLE_D and h["axis"] == "z" for h in thru)
    assert sorted(tuple(h["centre"]) for h in thru) == [(-40.0, -20.0), (-40.0, 20.0), (40.0, -20.0), (40.0, 20.0)]
    assert len(blind) == 1 and blind[0]["dia"] == BLIND_D and blind[0]["depth"] == pytest.approx(BLIND_DEPTH)
    assert blind[0]["open"] == 1  # open towards +Z (drilled from the top)
    assert analysis["census"]["levels"]["z"] == [0.0, T - BLIND_DEPTH, T]


def test_section_cuts_through_centre(analysis: dict[str, Any]) -> None:
    sec = analysis["section"]
    assert sec["like"] == "front" and sec["plane"] == 0.0
    ext = sec["extents"]
    assert ext == pytest.approx([-L / 2, L / 2, 0, T], abs=0.01)
    assert sec["loops"], "cut face loops for hatching"
    # the cut face area (shoelace) = L*T minus the blind hole slot (BLIND_D x BLIND_DEPTH); the Ø8 holes at y=±20
    # are not on the plane y = 0
    area = 0.0
    for lp in sec["loops"]:
        a = sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(lp, lp[1:] + lp[:1], strict=True)) / 2
        area += a
    assert abs(area) == pytest.approx(L * T - BLIND_D * BLIND_DEPTH, rel=1e-6)


# ----------------------------------------------------------------------------- dimensions and callouts
def test_param_kinds_and_format() -> None:
    assert param_kind("HOLE_D") == "dia" and param_kind("BORE") == "dia" and param_kind("D2") == "dia"
    assert param_kind("PCD") == "pcd" and param_kind("EDGE", {"label": "Edge distance"}) == "position"
    assert param_kind("T", {"label": "Thickness"}) == "linear" and param_kind("L1") == "linear"
    assert param_kind("FILLET_IN") == "other" and param_kind("N_BOLTS") == "count" and param_kind("KW") == "any"
    assert fmt(120.0) == "120" and fmt(6.6) == "6.6" and fmt(60.30000001) == "60.3" and fmt(0.25) == "0.25"


def test_dimensions_tagged_and_callouts_match_census(analysis: dict[str, Any]) -> None:
    dims, callouts, _notes = candidates(analysis["census"], {"front", "top", "right"})
    mapping = tag(dims, callouts, PARAMS, META)
    assert all(d["tag"] in ("spec", "inferred") for d in dims)
    by_id = {d["id"]: d for d in dims}
    assert (by_id["ext-x"]["value"], by_id["ext-x"]["tag"], by_id["ext-x"]["param"]) == (L, "spec", "L")
    assert (by_id["ext-y"]["value"], by_id["ext-y"]["param"]) == (W, "W")
    assert (by_id["ext-z"]["value"], by_id["ext-z"]["param"]) == (T, "T")
    lines = {c["lines"][0]["text"]: c["lines"][0] for c in callouts}
    assert set(lines) == {"4X Ø8 THRU", "Ø6 DEEP 10"}
    assert lines["4X Ø8 THRU"]["param"] == "HOLE_D"
    assert lines["Ø6 DEEP 10"]["param"] == "BLIND_D"
    assert sum(c["qty"] for c in callouts) == len(analysis["census"]["holes"]) == 5
    # hole locations from the nearest edge: 10 (EDGE) along X and Y, spacing 80 and 40 inferred
    pos = sorted((d["value"], d["tag"]) for d in dims if d["kind"] == "position")
    assert pos == [(EDGE, "spec"), (EDGE, "spec"), (40.0, "inferred"), (80.0, "inferred")]
    assert {"L", "W", "T", "HOLE_D", "EDGE", "BLIND_D"} <= set(mapping["mapped"])
    # the blind-hole level splits Z into 10 + 10: one segment becomes the reference dimension (no spec claim)
    z = [d for d in dims if d["family"] == "step-z"]
    assert len(z) == 2 and sum(d["aux"] for d in z) == 1
    assert all(d["tag"] == "inferred" for d in z if d["aux"])


def test_coincident_values_are_not_claimed_as_spec() -> None:
    """A parameter that matches two segments of one chain is ambiguous: neither segment is tagged spec."""
    cen = {"bbox": [0, 0, 0, 120, 10, 10], "holes": [], "outer": [], "unsupported_holes": 0,
           "levels": {"x": [0, 40, 80, 120], "y": [], "z": []}}
    dims, callouts, _ = candidates(cen, {"front", "top", "right"})
    tag(dims, callouts, {"PL": 40.0, "L": 120.0}, {"PL": {"label": "Pocket length"}})
    seg = [d for d in dims if d["family"] == "step-x"]
    assert [d["value"] for d in seg] == [40.0, 40.0, 40.0]
    assert all(d["tag"] == "inferred" for d in seg)
    assert next(d for d in dims if d["id"] == "ext-x")["param"] == "L"


# ----------------------------------------------------------------------------- sheet, CHK-12, exports
def test_sheet_passes_chk12(drawing: dict[str, Any]) -> None:
    chk = drawing["check"]
    assert chk["id"] == "CHK-12" and chk["gating"] is True
    assert chk["passed"], chk["problems"]
    assert chk["detail"]["overlap"]["text_overlaps"] == []
    assert all(v["passed"] for v in chk["detail"]["extents"].values())
    assert chk["detail"]["holes"]["mismatch"] == {}
    assert drawing["sheet"]["size"] == "A3" and drawing["sheet"]["scale"] == "1:1"
    assert drawing["title"]["material"] == "Aluminium 6061-T6"


def _sheet_inputs(model: Path) -> tuple[dict[str, Any], ...]:
    from aicad.drawing.layout import compose

    an = geometry.analyse(str(model / "out" / "part.step"), ["front", "top", "right"], None)
    dims, callouts, notes = candidates(an["census"], {"front", "top", "right"})
    mapping = tag(dims, callouts, PARAMS, META)
    opts = normalize_options({"views": ["front", "top", "right"]})
    sheet = compose(an, dims, callouts, notes, opts, {"title": "t"}, [])
    exp = {v: geometry.bbox_extents(an["census"]["bbox"], v) for v in ("front", "top", "right")}
    return sheet, dims, callouts, mapping, an["census"], exp


def test_chk12_fails_on_seeded_overlap_and_extent_error(model: Path) -> None:
    sheet, dims, callouts, mapping, census, exp = _sheet_inputs(model)
    assert chk12(sheet, dims, callouts, mapping, census, exp)["passed"]
    # seeded overlap: move one dimension text onto another
    bad = copy.deepcopy(sheet)
    texts = [p for p in bad["prims"] if p["t"] == "text" and p.get("kind") == "dim"]
    a, b = texts[0], texts[1]
    a["box"] = list(b["box"])
    res = chk12(bad, dims, callouts, mapping, census, exp)
    assert not res["passed"] and any("overlapping" in p for p in res["problems"])
    # seeded extent error: a view 0.5 mm too long
    bad = copy.deepcopy(sheet)
    bad["views"]["front"]["extents"][1] += 0.5
    res = chk12(bad, dims, callouts, mapping, census, exp)
    assert not res["passed"] and not res["detail"]["extents"]["front"]["passed"]
    # seeded untagged dimension and a hole callout removed from the sheet
    bad_dims = copy.deepcopy(dims)
    bad_dims[0]["tag"] = None
    bad = copy.deepcopy(sheet)
    bad["prims"] = [p for p in bad["prims"] if not (p["t"] == "text" and p.get("kind") == "callout")]
    res = chk12(bad, bad_dims, callouts, mapping, census, exp)
    assert not res["passed"] and res["detail"]["tags"]["untagged"] and res["detail"]["holes"]["mismatch"]


def test_exports_are_valid(model: Path, drawing: dict[str, Any]) -> None:
    d = model / "drawings"
    svg = (d / "sheet.svg").read_text(encoding="utf-8")
    root = ET.fromstring(svg)
    assert root.get("viewBox") == "0 0 420 297"
    assert "NOT APPROVED FOR MANUFACTURE" in svg and "SECTION A-A" in svg
    # layer classes are namespaced: an inline SVG must not pick up page utilities such as .hidden {display:none}
    assert 'class="hidden"' not in svg and 'class="drw-hidden"' in svg
    assert 'data-tag="spec" data-param="HOLE_D"' in svg and 'data-tag="inferred"' in svg
    pdf = (d / "sheet.pdf").read_bytes()
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF") and len(pdf) > 3000
    import ezdxf

    doc = ezdxf.readfile(str(d / "sheet.dxf"))
    msp = doc.modelspace()
    layers = {e.dxf.layer for e in msp}
    assert {"VISIBLE", "HIDDEN", "CENTER", "DIM", "TEXT", "HATCH"} <= layers
    # true size (IO-007): the front view outline has a 100 mm horizontal edge at scale 1:1
    lengths = sorted({round(e.dxf.start.distance(e.dxf.end), 6) for e in msp.query("LINE[layer=='VISIBLE']")})
    assert L in lengths and T in lengths
    assert any("NOT APPROVED" in e.dxf.text for e in msp.query("TEXT"))
    assert drawing["files"]["sheet.svg"] > 10000


def test_same_model_gives_identical_svg(model: Path, tmp_path: Path, drawing: dict[str, Any]) -> None:
    first = (model / "drawings" / "sheet.svg").read_bytes()
    generate(model / "out", model / "drawings", {"section": "y"}, {**DRAW_META, "date": "2027-01-01"})
    assert (model / "drawings" / "sheet.svg").read_bytes() == first  # same build: same revision row and bytes
    other = tmp_path / "drawings"
    generate(model / "out", other, {"section": "y"}, DRAW_META)
    assert (other / "sheet.svg").read_bytes() == first


def test_unmapped_parameter_names_stay_off_the_sheet(tmp_path: Path) -> None:
    """AMI-28: a parameter with no match in the geometry is listed in the record (the Drawing Studio panel shows
    it), but its name is never printed on the sheet, where readers took "L1, L2" for missing sizes."""
    ws = tmp_path / "ws"
    write_model(ws / "out")
    st = json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
    st["params"] = {**st["params"], "L1": 37.25, "L2": 41.75}
    (ws / "out" / "status.json").write_text(json.dumps(st), encoding="utf-8")
    rec = generate(ws / "out", ws / "drawings", {"section": "y"}, DRAW_META)
    assert {"L1", "L2"} <= set(rec["mapping"]["unmapped"])
    svg = (ws / "drawings" / "sheet.svg").read_text(encoding="utf-8")
    assert "NOT DIMENSIONED" not in svg and ">L1" not in svg and "L1, L2" not in svg
    assert rec["check"]["passed"], rec["check"]["problems"]


def test_options_change_sheet_and_projection(model: Path, tmp_path: Path) -> None:
    rec = generate(model / "out", tmp_path / "a4", {"sheet": "A4", "projection": "third",
                                                    "tolerance": {"mode": "iso2768", "class": "m"}}, DRAW_META)
    assert rec["sheet"]["size"] == "A4" and rec["sheet"]["projection"] == "third"
    assert rec["check"]["passed"], rec["check"]["problems"]
    assert rec["title"]["tolerance"] == "ISO 2768-m (medium)"
    svg = (tmp_path / "a4" / "sheet.svg").read_text(encoding="utf-8")
    assert 'viewBox="0 0 297 210"' in svg and "ISO 2768-m" in svg
    assert normalize_options({"tolerance": {"mode": "custom", "text": "  ±0.1  unless   stated "}})["tolerance"] == \
        {"mode": "custom", "class": None, "text": "±0.1 unless stated"}
    assert normalize_options({"views": ["iso"]})["views"] == ["front", "iso"]


def test_associative_regeneration_adds_revision(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    write_model(ws / "out", length=L, build_id="1")
    r1 = generate(ws / "out", ws / "drawings", {}, {**DRAW_META, "model_rev": "1"})
    write_model(ws / "out", length=120.0, build_id="2")
    r2 = generate(ws / "out", ws / "drawings", {}, {**DRAW_META, "model_rev": "2", "date": "2026-11-17"})
    assert [h["rev"] for h in r2["history"]] == ["1", "2"]
    assert r2["history"][-1]["change"] == "Regenerated: L 100→120"
    assert next(d for d in r2["dimensions"] if d["id"] == "ext-x")["value"] == 120.0
    assert r1["build_id"] == "1" and r2["build_id"] == "2"
    svg = (ws / "drawings" / "sheet.svg").read_text(encoding="utf-8")
    assert "Regenerated: L 100→120" in svg and "Initial issue" in svg


# ----------------------------------------------------------------------------- API
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
    from aicad.platform.app import create_app

    with TestClient(create_app()) as c:
        c.headers.update({"X-FW-CSRF": "1"})
        yield c
    from aicad.drawing import worker as dworker

    for w in dworker._workers.values():
        if w.proc is not None and w.proc.returncode is None:
            w.proc.kill()
        w.proc = None
    dworker._workers.clear()


def test_api_auth_entitlement_scoping_and_files(app_client: Any) -> None:
    from sqlalchemy import select
    from test_platform import signup

    from aicad.platform.db import session_factory
    from aicad.platform.models import Membership, Project, User
    from aicad.platform.routers.projects import workspace_for

    c = app_client
    assert c.get("/api/m/drawings/projects").status_code == 401
    signup(c, "drw@x.com")
    set_trial_ended("drw@x.com")  # a running trial may use every live module: test the paywall after it
    r = c.get("/api/m/drawings/projects")
    assert r.status_code == 402 and "add-on" in r.json()["detail"]["message"]
    pid = c.post("/api/projects", json={"name": "Block"}).json()["id"]
    db = session_factory()()
    ws = workspace_for(db.get(Project, pid))
    db.close()
    assert c.post(f"/api/m/drawings/projects/{pid}/generate", json={}).status_code == 402
    set_trial_ended("drw@x.com", False)
    # unlock the add-on (simulated payment)
    pay = c.post("/api/billing/checkout", json={"product_code": "addon_drawings"}).json()["payment_id"]
    c.post(f"/api/billing/payments/{pay}/simulate", json={"outcome": "success"})
    items = c.get("/api/m/drawings/projects").json()["items"]
    assert [(i["id"], i["verified"], i["drawing"]) for i in items] == [(pid, False, None)]
    assert c.post(f"/api/m/drawings/projects/{pid}/generate", json={}).status_code == 409  # no verified build
    write_model(ws / "out")
    r = c.post(f"/api/m/drawings/projects/{pid}/generate", json={"sheet": "A3", "section": "y",
                                                                  "tolerance": {"mode": "iso2768", "class": "f"}})
    assert r.status_code == 200, r.text
    rec = r.json()["drawing"]
    assert rec["check"]["passed"] and rec["title"]["tolerance"] == "ISO 2768-f (fine)"
    assert rec["title"]["drawn_by"] == "Ada Engineer" and rec["title"]["drawing_no"].startswith("FW-")
    got = c.get(f"/api/m/drawings/projects/{pid}").json()
    assert got["drawing"]["build_id"] == "1001" and got["stale"] is False
    svg = c.get(f"/api/m/drawings/projects/{pid}/files/sheet.svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    pdf = c.get(f"/api/m/drawings/projects/{pid}/files/sheet.pdf")
    assert pdf.content.startswith(b"%PDF-") and "attachment" in pdf.headers["content-disposition"]
    assert c.get(f"/api/m/drawings/projects/{pid}/files/sheet.dxf").status_code == 200
    assert c.get(f"/api/m/drawings/projects/{pid}/files/..%2Fout%2Fstatus.json").status_code == 404
    # model changes -> stale until regenerated
    write_model(ws / "out", length=110.0, build_id="1002")
    assert c.get(f"/api/m/drawings/projects/{pid}").json()["stale"] is True
    # viewers can read but not generate
    db = session_factory()()
    me = db.scalar(select(User).where(User.email == "drw@x.com"))
    m = db.scalar(select(Membership).where(Membership.user_id == me.id))
    m.role = "viewer"
    db.commit()
    db.close()
    assert c.get(f"/api/m/drawings/projects/{pid}").json()["can_edit"] is False
    assert c.post(f"/api/m/drawings/projects/{pid}/generate", json={}).status_code == 403
    # another organization cannot see the project
    c.post("/api/auth/logout")
    signup(c, "other@x.com", workspace="Other Co")
    c.post("/api/god/scenario", json={"scenario": "all_modules"})  # not a superadmin: no effect
    pay = c.post("/api/billing/checkout", json={"product_code": "addon_drawings"}).json()["payment_id"]
    c.post(f"/api/billing/payments/{pay}/simulate", json={"outcome": "success"})
    assert c.get(f"/api/m/drawings/projects/{pid}").status_code == 404
    assert c.get(f"/api/m/drawings/projects/{pid}/files/sheet.svg").status_code == 404
    assert c.get("/api/m/drawings/projects").json()["items"] == []


def test_catalog_marks_drawings_live(app_client: Any) -> None:
    cat = app_client.get("/api/billing/catalog").json()
    m = next(x for x in cat["modules"] if x["code"] == "drawings")
    assert m["status"] == "live"


def test_failed_build_is_a_user_error(tmp_path: Path) -> None:
    from aicad.drawing import DrawingInputError

    write_model(tmp_path / "out")
    st = json.loads((tmp_path / "out" / "status.json").read_text(encoding="utf-8"))
    (tmp_path / "out" / "status.json").write_text(json.dumps({**st, "ok": False}), encoding="utf-8")
    with pytest.raises(DrawingInputError, match="did not pass its checks"):
        generate(tmp_path / "out", tmp_path / "drawings", {}, DRAW_META)
    with pytest.raises(DrawingInputError, match="no verified build"):
        generate(tmp_path / "missing", tmp_path / "drawings", {}, DRAW_META)
