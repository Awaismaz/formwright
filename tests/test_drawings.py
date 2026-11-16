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

from aicad.drawing import geometry
from aicad.drawing.check import chk12, placement_problems
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
    return geometry.analyse(str(model / "out" / "part.step"), {"views": ["front", "top", "right", "iso"], "section": "y"})


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
    assert param_kind("FILLET_IN") == "radius" and param_kind("N_BOLTS") == "count" and param_kind("KW") == "any"
    assert param_kind("PR", {"label": "Corner radius"}) == "radius" and param_kind("CH", {"label": "Top chamfer"}) == "chamfer"
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

    an = geometry.analyse(str(model / "out" / "part.step"), {"views": ["front", "top", "right"], "section": None})
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
    assert 'data-tag="spec"' in svg and 'data-tag="inferred"' in svg and 'data-ref="ext-x"' in svg
    assert "data-param" not in svg  # parameter names are model internals, never on the sheet (MAKE-05)
    pdf = (d / "sheet.pdf").read_bytes()
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF") and len(pdf) > 3000
    import ezdxf

    doc = ezdxf.readfile(str(d / "sheet.dxf"))
    msp = doc.modelspace()
    assert {e.dxf.layer for e in msp} <= {"VISIBLE", "HIDDEN", "CENTER", "HATCH"}  # model space: geometry only
    # true size (IO-007): the front view outline has a 100 mm horizontal edge at scale 1:1
    lengths = sorted({round(e.dxf.start.distance(e.dxf.end), 6) for e in msp.query("LINE[layer=='VISIBLE']")})
    assert L in lengths and T in lengths
    sheet_layout = doc.layouts.get("Sheet")
    assert {"DIM", "TEXT", "SHEET"} <= {e.dxf.layer for e in sheet_layout}
    texts = [e.dxf.text for e in sheet_layout.query("TEXT")]
    assert any("NOT APPROVED" in t for t in texts)
    assert any(t.startswith("4X %%c8") for t in texts) and not any("Ø" in t for t in texts)  # %%c, any CAD font
    vps = [v for v in sheet_layout.query("VIEWPORT") if v.dxf.status > 1]
    assert len(vps) == 1 and vps[0].dxf.view_height == pytest.approx(297.0)  # 1:1: model height = paper height
    assert doc.layers.get("HIDDEN").dxf.linetype == "HIDDEN" and doc.layers.get("CENTER").color == 1
    assert drawing["files"]["sheet.svg"] > 10000


def test_same_model_gives_identical_svg(model: Path, tmp_path: Path, drawing: dict[str, Any]) -> None:
    first = (model / "drawings" / "sheet.svg").read_bytes()
    generate(model / "out", model / "drawings", {"section": "y"}, {**DRAW_META, "date": "2027-01-01"})
    assert (model / "drawings" / "sheet.svg").read_bytes() == first  # same build: same revision row and bytes
    other = tmp_path / "drawings"
    generate(model / "out", other, {"section": "y"}, DRAW_META)
    assert (other / "sheet.svg").read_bytes() == first


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
    # no release yet: every build is a draft; the sheet's revision table lists issued revisions only (MAKE-08)
    assert r1["sheet_rev"] == r2["sheet_rev"] == "DRAFT" and r2["revisions"] == []
    svg = (ws / "drawings" / "sheet.svg").read_text(encoding="utf-8")
    assert "Regenerated" not in svg and ">DRAFT<" in svg


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
    r = c.get("/api/m/drawings/projects")
    assert r.status_code == 402 and "add-on" in r.json()["detail"]["message"]
    pid = c.post("/api/projects", json={"name": "Block"}).json()["id"]
    db = session_factory()()
    ws = workspace_for(db.get(Project, pid))
    db.close()
    assert c.post(f"/api/m/drawings/projects/{pid}/generate", json={}).status_code == 402
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


# ----------------------------------------------------------------------------- demo parts (audit fixes MAKE-01..27)
# Expected values below come from the demo scripts' declared constants (src/aicad/demo/*.py), not from the drawing.
DEMO_DIR = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo"


def build_demo(name: str, out: Path, build_id: str = "d1", overrides: dict[str, float] | None = None) -> dict[str, Any]:
    """Run an original demo script and leave what a verified build leaves in ``out/``."""
    import re

    from build123d import export_step

    src = (DEMO_DIR / f"{name}.py").read_text(encoding="utf-8")
    for k, v in (overrides or {}).items():
        src = re.sub(rf"^{k} = .*$", f"{k} = {v!r}", src, count=1, flags=re.MULTILINE)
    ns: dict[str, Any] = {}
    exec(compile(src, name, "exec"), ns)  # noqa: S102 - our own demo script
    out.mkdir(parents=True, exist_ok=True)
    export_step(ns["result"], str(out / "part.step"))
    (out / "status.json").write_text(json.dumps({
        "ok": True, "part": ns["NAME"], "material": ns["MATERIAL"], "params": ns["PARAMS"],
        "param_meta": ns.get("PARAM_META", {}), "build_id": build_id, "step_sha256": f"sha-{build_id}"}),
        encoding="utf-8")
    return ns


@pytest.fixture(scope="module")
def demos(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("demos")
    out = {}
    for n in ("l_bracket", "stepped_shaft", "pipe_flange", "mounting_plate"):
        build_demo(n, root / n / "out")
        out[n] = root / n
    return out


def _pipeline(ws: Path, options: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """The generate() pipeline up to the composed sheet, so tests can read every placed primitive."""
    from aicad.drawing.layout import compose

    st = json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
    opts = normalize_options(options)
    an = geometry.analyse(str(ws / "out" / "part.step"), {"views": opts["views"], "section": opts["section"]})
    enabled = set(an["views"])
    sec = an.get("section")
    cross = sec is not None and not an["plan"].get("front_section")
    if cross:
        enabled.add("section")
    dims, callouts, notes = candidates(an["census"], enabled, {"axis": sec["axis"], "at": sec["plane"]} if cross else None)
    tag(dims, callouts, st["params"], st.get("param_meta") or {})
    sheet = compose(an, dims, callouts, notes, opts, {"title": "t"}, [])
    return sheet, dims, an


def _paper_span(sheet: dict[str, Any], d: dict[str, Any]) -> tuple[float, float]:
    """A dimension's span on paper, from the view's placement and scale (independent of the layout's own record)."""
    v = sheet["views"][d["view"]]
    s, (u0, v0), rect = v["scale"], v["origin"], v["rect"]
    if d["orient"] == "h":
        return rect[0] + (d["a"] - u0) * s, rect[0] + (d["b"] - u0) * s
    return rect[1] + (v0 - d["b"]) * s, rect[1] + (v0 - d["a"]) * s


def _misread_values(sheet: dict[str, Any], dims: list[dict[str, Any]]) -> list[str]:
    """MAKE-01, checked from first principles: a value that is not inside its own span must not lie inside the span
    of another dimension whose value sits on the same dimension line (same view, direction and text baseline)."""
    texts = {p["ref"]: p for p in sheet["prims"] if p["t"] == "text" and p.get("kind") == "dim"}
    rows = []
    for d in dims:
        t = texts.get(d["id"])
        if t is None:
            continue
        b = t["box"]
        proj = (b[0], b[2]) if d["orient"] == "h" else (b[1], b[3])
        line = t["y"] if d["orient"] == "h" else t["x"]
        rows.append((d, proj, line, _paper_span(sheet, d)))
    bad = []
    for d, proj, line, span in rows:
        if proj[0] >= span[0] - 0.3 and proj[1] <= span[1] + 0.3:
            continue
        for e, _p, line_e, span_e in rows:
            if e is d or e["view"] != d["view"] or e["orient"] != d["orient"] or abs(line - line_e) > 0.01:
                continue
            if proj[0] < span_e[1] - 0.05 and span_e[0] + 0.05 < proj[1]:
                bad.append(f"{d['text']} ({d['view']}) sits in the span of {e['text']}")
    return bad


def test_chained_values_sit_against_their_own_span(demos: dict[str, Path]) -> None:
    """MAKE-01 regression: on the L-bracket the hole chain 12.5 + 25 put "12.5" inside the 25 span (and "25" in the
    undimensioned gap). Every demo part, both sheet sizes."""
    for name in ("l_bracket", "stepped_shaft", "pipe_flange", "mounting_plate"):
        for size in ("A3", "A4"):
            sheet, dims, _an = _pipeline(demos[name], {"sheet": size})
            assert _misread_values(sheet, dims) == [], (name, size)
            assert placement_problems([p for p in sheet["prims"] if p["t"] == "text"]) == [], (name, size)
    # the bracket's chain: 12.5 (edge to hole, LEG W/4) does not fit inside its span at 1:1, so it goes beyond the
    # chain's first extension line; 25 (hole pitch, W/2) sits inside its own span
    sheet, dims, _an = _pipeline(demos["l_bracket"], {"sheet": "A3"})
    texts = {p["ref"]: p for p in sheet["prims"] if p["t"] == "text" and p.get("kind") == "dim"}
    chain = sorted((d for d in dims if d["kind"] == "position" and d["view"] == "right"), key=lambda d: d["a"])
    assert [d["value"] for d in chain if d["orient"] == "h"] == [12.5, 25.0]
    first, pitch = [d for d in chain if d["orient"] == "h"]
    lo, _hi = _paper_span(sheet, first)
    assert texts[first["id"]]["box"][2] <= lo  # wholly before the chain's first extension line
    p0, p1 = _paper_span(sheet, pitch)
    assert p0 <= texts[pitch["id"]]["box"][0] and texts[pitch["id"]]["box"][2] <= p1


def test_chk12_rejects_a_value_in_its_neighbours_span(demos: dict[str, Path]) -> None:
    """The strengthened CHK-12 fails the old placement: a chain value moved into the next span on the same line."""
    sheet, dims, an = _pipeline(demos["l_bracket"], {"sheet": "A3"})
    texts = [p for p in sheet["prims"] if p["t"] == "text"]
    assert placement_problems(texts) == []
    by = {p["ref"]: p for p in texts if p.get("kind") == "dim"}
    chain = sorted((d for d in dims if d["kind"] == "position" and d["view"] == "right" and d["orient"] == "h"),
                   key=lambda d: d["a"])
    first, pitch = by[chain[0]["id"]], by[chain[1]["id"]]
    assert first["dl"]["at"] == pitch["dl"]["at"]  # one dimension line
    bad = copy.deepcopy(sheet)
    t = next(p for p in bad["prims"] if p["t"] == "text" and p.get("ref") == chain[0]["id"])
    # the pre-fix layout: "12.5" pushed past its right arrow, into the 25 mm span, with no leader under it
    x0 = t["dl"]["line"][1] + 3.8
    w = t["box"][2] - t["box"][0]
    t["box"] = [x0, t["box"][1], x0 + w, t["box"][3]]
    res = placement_problems([p for p in bad["prims"] if p["t"] == "text"])
    assert res and res[0]["why"] == "outside its span with no leader"
    t["dl"]["drawn"] = [t["dl"]["drawn"][0], x0 + w + 0.3]  # even with a leader it reads as the 25 span's value
    res = placement_problems([p for p in bad["prims"] if p["t"] == "text"])
    assert res and "same dimension line" in res[0]["why"]
    exp = {v: geometry.bbox_extents(an["census"]["bbox"], v) for v in ("front", "top", "right")}
    mapping = tag(copy.deepcopy(dims), [], {}, {})
    chk = chk12(bad, dims, [], mapping, {"holes": []}, exp)
    assert not chk["passed"] and any("own span" in p for p in chk["problems"])


def test_turned_parts_are_drawn_axis_horizontal(demos: dict[str, Path], tmp_path: Path) -> None:
    """MAKE-07 / MAKE-27, stepped shaft (D1 20, L1 40, D2 25, L2 70, KW 6, KD 3.5, KL 30)."""
    rec = generate(demos["stepped_shaft"] / "out", tmp_path / "shaft", {"sheet": "A4"}, DRAW_META)
    assert rec["plan"]["turned"] and rec["plan"]["views"] == ["front", "right", "iso"]  # no duplicate top view
    assert rec["sheet"]["scale"] == "1:1"  # was 1:5 axis-vertical on A4 (150 mm along the sheet's long side)
    assert rec["check"]["passed"], rec["check"]["problems"]
    _sheet, _dims, an = _pipeline(demos["stepped_shaft"], {"sheet": "A4"})
    ext = an["views"]["front"]["extents"]
    assert ext[1] - ext[0] == pytest.approx(2 * 40 + 70, abs=0.01) and ext[3] - ext[2] == pytest.approx(25, abs=0.01)
    # no lengthwise hatching of a solid shaft: a cross-section through the keyway, seen end-on
    assert rec["plan"]["section"] == "cross" and an["section"]["like"] == "right"
    assert an["section"]["plane"] == pytest.approx(40 + 70 / 2)  # keyway centred on the Ø25 section
    sec_ext = an["section"]["extents"]
    assert sec_ext[1] - sec_ext[0] == pytest.approx(25, abs=0.01)
    by = {(d["text"].strip("()"), d["param"]) for d in rec["dimensions"]}
    # L2 = 70 now dimensioned as one value between the shoulders (the keyway no longer splits the chain)
    assert ("70", "L2") in by and ("30", "KL") in by and ("6", "KW") in by and ("3.5", "KD") in by
    assert ("Ø20", "D1") in by and ("Ø25", "D2") in by
    assert ("20", None) in by  # keyway located from the shoulder: (L2 - KL) / 2 = 20
    # forcing a lengthwise section on a solid shaft gives the cross-section and says why
    rec2 = generate(demos["stepped_shaft"] / "out", tmp_path / "shaft2", {"section": "y"}, DRAW_META)
    assert rec2["plan"]["section"] == "cross" and "ISO 128-50" in rec2["plan"]["note"]


def test_flange_section_replaces_the_duplicate_elevation(demos: dict[str, Path], tmp_path: Path) -> None:
    """MAKE-07 / MAKE-05, pipe flange (OD 150, T 16, BORE 60.3, RF 100 × 2, 6 × Ø14 on PCD 120)."""
    rec = generate(demos["pipe_flange"] / "out", tmp_path / "flange", {}, DRAW_META)
    assert rec["plan"]["turned"] and rec["plan"]["front_section"] and rec["plan"]["views"] == ["front", "right", "iso"]
    assert rec["sheet"]["scale"] == "1:1" and rec["check"]["passed"], rec["check"]["problems"]
    lines = [ln for c in rec["callouts"] for ln in c["lines"]]
    bolt = next(c for c in rec["callouts"] if c["dia"] == 14.0)
    assert bolt["lines"][0]["text"] == "6X Ø14 THRU" and bolt["lines"][0]["params"] == ["N_BOLTS"]
    assert rec["mapping"]["unmapped"] == []  # N_BOLTS is carried by "6X" (the old sheet claimed it was missing)
    assert any(ln["text"] == "EQ SP ON PCD Ø120" and ln["param"] == "PCD" for ln in lines)
    by = {(d["text"].strip("()"), d["param"]) for d in rec["dimensions"]}
    assert ("Ø150", "OD") in by and ("Ø100", "RF_D") in by and ("16", "T") in by and ("2", "RF_H") in by
    svg = (tmp_path / "flange" / "sheet.svg").read_text(encoding="utf-8")
    assert "SECTION A-A" in svg


def test_radius_and_chamfer_callouts_and_no_parameter_names(demos: dict[str, Path], tmp_path: Path) -> None:
    """MAKE-05: plate (4 pocket corners PR = 3, top chamfer CH = 1 on 4 edges), bracket (inside fillet R3)."""
    rec = generate(demos["mounting_plate"] / "out", tmp_path / "plate", {}, DRAW_META)
    assert rec["check"]["passed"], rec["check"]["problems"]
    texts = {c["lines"][0]["text"]: c["lines"][0] for c in rec["callouts"]}
    assert texts["4X R3"]["param"] == "PR" and texts["4X 1 × 45°"]["param"] == "CH"
    assert texts["4X Ø6.6 THRU"]["param"] == "HOLE_D"
    # PL = 40 coincides with both end segments of the 40 + 40 + 40 chain: placed (inferred), never claimed as spec
    assert rec["mapping"]["unmapped"] == ["PL"]
    assert sum(1 for d in rec["dimensions"] if d["value"] == 40.0) == 3
    for f in ("sheet.svg", "sheet_issue.svg"):
        svg = (tmp_path / "plate" / f).read_text(encoding="utf-8")
        assert "NOT DIMENSIONED" not in svg and ">PL" not in svg and "PL," not in svg
    rec = generate(demos["l_bracket"] / "out", tmp_path / "bracket", {}, DRAW_META)
    r3 = next(c for c in rec["callouts"] if c["type"] == "radius")
    assert r3["lines"][0]["text"] == "R3" and r3["lines"][0]["param"] == "FILLET_IN" and r3["view"] == "front"
    assert rec["mapping"]["unmapped"] == [] and rec["check"]["passed"]


def test_user_edits_are_applied_and_checked(model: Path, tmp_path: Path) -> None:
    """MAKE-06: hidden dimension, per-dimension tolerance, title-block fields and a note, kept across rebuilds."""
    from aicad.drawing import DrawingInputError
    from aicad.drawing.generate import normalize_edits

    edits = {"dims": {"ext-x": {"tol": "±0.1"}, "dia-z-1": {"tol": "H7"}, "pos-0-x-1": {"hidden": True}},
             "title": {"company": "Acme Tooling", "checked_by": "R. Checker", "drawing_no": "AC-1001"},
             "notes": ["Break sharp edges 0.2 to 0.5 mm"]}
    rec = generate(model / "out", tmp_path / "e", {}, DRAW_META, edits)
    assert rec["check"]["passed"], rec["check"]["problems"]
    ext = next(d for d in rec["dimensions"] if d["id"] == "ext-x")
    assert ext["text"] == "100 ±0.1" and ext["tol"] == "±0.1"
    hidden = next(d for d in rec["dimensions"] if d["id"] == "pos-0-x-1")
    assert hidden["hidden"] and rec["check"]["detail"]["spec_once"]["hidden_by_user"] == ["pos-0-x-1"]
    svg = (tmp_path / "e" / "sheet.svg").read_text(encoding="utf-8")
    assert 'data-ref="pos-0-x-1"' not in svg and "100 ±0.1" in svg
    assert "Acme Tooling" in svg and "R. Checker" in svg and "AC-1001" in svg
    assert "Break sharp edges 0.2 to 0.5 mm" in svg and "ENTERED BY THE USER" in svg
    assert rec["title"]["drawing_no"] == "AC-1001"
    with pytest.raises(DrawingInputError, match="can't print"):
        normalize_edits({"dims": {"ext-x": {"tol": "<script>"}}})
    assert normalize_edits({"dims": {"../x": {"hidden": True}}})["dims"] == {}


def test_revision_is_draft_until_issued(model: Path, tmp_path: Path) -> None:
    """MAKE-08: the sheet carries issued letters only; a changed model is a draft against the last issue."""
    ws = tmp_path / "ws"
    write_model(ws / "out", build_id="b1")
    stamp = {"build_id": "b1", "step_sha256": None, "material": "Aluminium 6061-T6", "model_rev": None}
    r = generate(ws / "out", ws / "drawings", {}, DRAW_META)
    assert r["sheet_rev"] == "DRAFT" and r["build"]["build_id"] == "b1"
    rel_a = {"rev": "A", "build": stamp, "date": "2026-11-17", "by": "Ada", "note": "First issue"}
    r = generate(ws / "out", ws / "drawings", {}, {**DRAW_META, "releases": [rel_a]})
    assert r["sheet_rev"] == "A" and r["revisions"] == [{"rev": "A", "date": "2026-11-17", "change": "First issue",
                                                         "by": "Ada"}]
    write_model(ws / "out", length=110.0, build_id="b2")
    r = generate(ws / "out", ws / "drawings", {}, {**DRAW_META, "releases": [rel_a]})
    svg = (ws / "drawings" / "sheet.svg").read_text(encoding="utf-8")
    assert r["sheet_rev"] == "DRAFT" and "CHANGES SINCE REV A ARE NOT ISSUED" in svg
    hist = (ws / "drawings" / "history.json").read_bytes()
    issue = {"rev": "B", "build": {**stamp, "build_id": "b2"}, "date": "2026-11-18", "by": "Ada", "note": "L 110"}
    rel = generate(ws / "out", tmp_path / "rel" / "B", {}, {**DRAW_META, "releases": [rel_a], "issue": issue})
    assert rel["sheet_rev"] == "B" and rel["issued"] and [x["rev"] for x in rel["revisions"]] == ["A", "B"]
    assert rel["title"]["date"] == "2026-11-18"
    assert (ws / "drawings" / "history.json").read_bytes() == hist  # issuing never touches the working history
    files = {f.name for f in (tmp_path / "rel" / "B").iterdir()}
    assert {"sheet.svg", "sheet.pdf", "sheet.dxf"} <= files and "sheet_review.pdf" not in files
    assert "DIMENSION TAGS" not in (tmp_path / "rel" / "B" / "sheet.svg").read_text(encoding="utf-8")


def test_issue_copy_is_monochrome_and_shares_the_layout(drawing: dict[str, Any], model: Path) -> None:
    """MAKE-09: review copy has tag colours and the legend; the issue copy (export default) has neither."""
    d = model / "drawings"
    review = (d / "sheet.svg").read_text(encoding="utf-8")
    issue = (d / "sheet_issue.svg").read_text(encoding="utf-8")
    assert "SPEC: equals a declared model parameter" in review and "#0b3d91" in review
    assert "SPEC:" not in issue and "#0b3d91" not in issue and "#9a3412" not in issue
    assert 'font-style="italic"' not in issue and "data-tag" not in issue
    # same layout: the 100 mm overall dimension sits at the same place in both copies
    import re as _re

    pos = [_re.search(r'<text x="([\d.]+)" y="([\d.]+)"[^>]*>(?:<title>[^<]*</title>)?100<', s) for s in (review, issue)]
    assert pos[0] and pos[1] and pos[0].groups() == pos[1].groups()
    assert (d / "sheet_review.pdf").read_bytes() != (d / "sheet.pdf").read_bytes()


def test_api_edits_copies_and_local_date(app_client: Any) -> None:
    from sqlalchemy import select
    from test_platform import signup

    from aicad.platform.db import session_factory
    from aicad.platform.models import Membership, Project, User
    from aicad.platform.routers.projects import workspace_for

    c = app_client
    signup(c, "drwed@x.com")
    c.post("/api/billing/payments/" + c.post("/api/billing/checkout", json={"product_code": "addon_drawings"})
           .json()["payment_id"] + "/simulate", json={"outcome": "success"})
    pid = c.post("/api/projects", json={"name": "Block"}).json()["id"]
    db = session_factory()()
    ws = workspace_for(db.get(Project, pid))
    db.close()
    write_model(ws / "out")
    r = c.post(f"/api/m/drawings/projects/{pid}/generate", json={"local_date": "2026-11-17", "tz": "Asia/Karachi"})
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["drawing"]["title"]["date"] == "2026-11-17" and st["drawing"]["sheet_rev"] == "DRAFT"
    assert st["edits"] == {"dims": {}, "title": {}, "notes": []} and st["release"] is None
    r = c.put(f"/api/m/drawings/projects/{pid}/edits", json={"dims": {"ext-y": {"tol": "±0.2"}},
                                                             "title": {"company": "Acme"}, "notes": ["Deburr"]})
    assert r.status_code == 200, r.text
    assert next(d for d in r.json()["drawing"]["dimensions"] if d["id"] == "ext-y")["text"] == "60 ±0.2"
    assert c.get(f"/api/m/drawings/projects/{pid}/edits").json()["title"] == {"company": "Acme"}
    assert c.put(f"/api/m/drawings/projects/{pid}/edits", json={"dims": {"ext-y": {"tol": "<b>"}}}).status_code == 422
    review = c.get(f"/api/m/drawings/projects/{pid}/files/sheet.pdf?copy=review&download=1")
    issue = c.get(f"/api/m/drawings/projects/{pid}/files/sheet.pdf?download=1")
    assert review.status_code == issue.status_code == 200 and review.content != issue.content
    assert "_review.pdf" in review.headers["content-disposition"]
    assert "SPEC:" not in c.get(f"/api/m/drawings/projects/{pid}/files/sheet.svg?download=1").text
    assert "SPEC:" in c.get(f"/api/m/drawings/projects/{pid}/files/sheet.svg").text
    # the model changes: stale, and opening the drawing does not replace it
    write_model(ws / "out", length=110.0, build_id="1002")
    got = c.get(f"/api/m/drawings/projects/{pid}").json()
    assert got["stale"] is True and got["drawing"]["build_id"] == "1001"
    db = session_factory()()
    me = db.scalar(select(User).where(User.email == "drwed@x.com"))
    db.scalar(select(Membership).where(Membership.user_id == me.id)).role = "viewer"
    db.commit()
    db.close()
    assert c.put(f"/api/m/drawings/projects/{pid}/edits", json={}).status_code == 403


def test_render_issue_freezes_an_issue_copy(tmp_path: Path) -> None:
    """The release gate's hook: an issue copy (REV = release letter) in its own folder; the working sheet untouched."""
    import asyncio
    from types import SimpleNamespace

    from aicad.drawing import worker as dworker
    from aicad.platform.routers.mod_drawings import render_issue

    ws = tmp_path / "ws"
    write_model(ws / "out", build_id="b9")
    generate(ws / "out", ws / "drawings", {"sheet": "A4"}, DRAW_META, {"title": {"company": "Acme"}})
    (ws / "drawings" / "edits.json").write_text(json.dumps({"title": {"company": "Acme"}}), encoding="utf-8")
    before = {f.name: f.read_bytes() for f in (ws / "drawings").iterdir()}
    proj = SimpleNamespace(id="p-issue", org_id="org-issue", name="Demo · Block")
    rel = {"rev": "A", "date": "2026-11-20", "by": "Ada Engineer", "note": "First issue",
           "build": {"build_id": "b9", "step_sha256": None, "material": "Aluminium 6061-T6"}}

    async def run() -> dict[str, Any]:
        try:
            return await render_issue(proj, ws, ws / "releases" / "A" / "drawing", rel, "Ada Engineer")  # type: ignore[arg-type]
        finally:
            await dworker.shutdown_all()

    out = asyncio.run(run())
    assert out["sheet_rev"] == "A" and out["issued"] and out["title"]["date"] == "2026-11-20"
    assert out["sheet"]["size"] == "A4" and out["title"]["company"] == "Acme"  # saved options and edits re-applied
    svg = (ws / "releases" / "A" / "drawing" / "sheet.svg").read_text(encoding="utf-8")
    assert "First issue" in svg and "SPEC:" not in svg and ">A<" in svg
    assert {f.name: f.read_bytes() for f in (ws / "drawings").iterdir()} == before

    async def missing() -> None:
        try:
            await render_issue(proj, tmp_path / "empty", tmp_path / "x", rel, "Ada")  # type: ignore[arg-type]
        finally:
            await dworker.shutdown_all()

    with pytest.raises(ValueError, match="no verified build"):
        asyncio.run(missing())
