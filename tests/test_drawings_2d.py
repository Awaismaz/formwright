"""2D drafting without a model (DRW-017): document, associative dimensions, templates, exports and the API.

Expected values are derived by hand from the inputs (no fixtures read back from the code under test)."""

from __future__ import annotations

import base64
import math
import re
import xml.etree.ElementTree as ET
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from aicad.drawing import DrawingInputError, draft, draft_assist
from aicad.drawing import draft_templates as T


def doc_with(frag: dict[str, Any], **sheet: Any) -> dict[str, Any]:
    return draft.normalize_doc({"sheet": {"size": "A3", **sheet}, "title": {"title": "Test"}, **frag})


def plate_doc() -> dict[str, Any]:
    """100 x 60 rectangle, two Ø10 holes 20 from each end on the centre line, a hidden line, a construction line,
    a hatch on a 10 x 10 square, an angle, an ordinate and a toleranced dimension."""
    pts = [("A", -50, -30), ("B", 50, -30), ("C", 50, 30), ("D", -50, 30), ("H1", -30, 0), ("H2", 30, 0),
           ("S1", -5, -25), ("S2", 5, -25), ("S3", 5, -15), ("S4", -5, -15), ("K1", -60, 0), ("K2", 60, 0),
           ("V1", 0, 0), ("V2", 20, 20 * math.tan(math.radians(30)))]
    ents = [("AB", "line", "A", "B", "visible"), ("BC", "line", "B", "C", "visible"), ("CD", "line", "C", "D", "visible"),
            ("DA", "line", "D", "A", "visible"), ("s1", "line", "S1", "S2", "visible"), ("s2", "line", "S2", "S3", "visible"),
            ("s3", "line", "S3", "S4", "visible"), ("s4", "line", "S4", "S1", "visible"),
            ("cons", "line", "K1", "K2", "construction"), ("hid", "line", "V1", "V2", "hidden")]
    ent = [{"id": i, "type": t, "p1": a, "p2": b, "layer": lay} for i, t, a, b, lay in ents]
    ent += [{"id": "c1", "type": "circle", "c": "H1", "r": 5.0, "layer": "visible"},
            {"id": "c2", "type": "circle", "c": "H2", "r": 5.0, "layer": "visible"}]
    dims = [{"id": "dL", "type": "linear", "orient": "h", "a": "A", "b": "B", "pos": [0, -45]},
            {"id": "dW", "type": "linear", "orient": "v", "a": "B", "b": "C", "pos": [65, 0],
             "tol": {"kind": "dev", "up": 0.1, "lo": -0.2}},
            {"id": "dH", "type": "diameter", "ent": "c1", "pos": [-15, 21], "prefix": "2X", "tol": {"kind": "fit", "fit": "H7"}},
            {"id": "dP", "type": "linear", "orient": "aligned", "a": "H1", "b": "H2", "pos": [0, 12],
             "tol": {"kind": "sym", "up": 0.05}},
            {"id": "dA", "type": "angle", "l1": "AB", "l2": "hid", "pos": [10, 3]},
            {"id": "dO", "type": "ordinate", "axis": "x", "origin": "A", "pt": "H2", "pos": [30, 40]},
            {"id": "dLim", "type": "linear", "orient": "v", "a": "A", "b": "D", "pos": [-62, 0],
             "tol": {"kind": "limits", "up": 0.0, "lo": -0.1}}]
    annos = [{"id": "h1", "type": "hatch", "loops": [["s1", "s2", "s3", "s4"]], "spacing": 2.0},
             {"id": "cm1", "type": "centermark", "ent": "c1"},
             {"id": "t1", "type": "text", "pos": [-48, 26], "text": "BREAK EDGES"},
             {"id": "g1", "type": "gdt", "pos": [20, -40], "symbol": "position", "tol": "0.1", "dia": True,
              "datums": ["A", "B"], "tip": [30, -5]},
             {"id": "sf", "type": "surface", "pos": [0, 30], "text": "Ra 1.6", "removal": "required"},
             {"id": "b1", "type": "balloon", "tip": [45, 25], "pos": [60, 40], "text": "1"},
             {"id": "dt", "type": "datum", "pos": [-40, -42], "tip": [-40, -30], "letter": "A"},
             {"id": "ld", "type": "leader", "pts": [[50, 30], [62, 42]], "text": "CHAMFER"}]
    return draft.normalize_doc({"sheet": {"size": "A3", "scale": [1, 1]}, "title": {"title": "Plate"},
                                "geom": {"points": [{"id": i, "x": x, "y": y} for i, x, y in pts], "entities": ent},
                                "dims": dims, "annos": annos, "notes": ["DEBURR ALL EDGES"],
                                "revisions": [{"rev": "A", "change": "First issue", "date": "2026-11-18", "by": "AE"}]})


# ----------------------------------------------------------------------------- document + dimension values
def test_values_are_measured_and_formatted() -> None:
    doc = plate_doc()
    rep = {r["id"]: r for r in draft.dimension_report(doc)}
    assert rep["dL"]["value"] == pytest.approx(100) and rep["dL"]["text"] == "100"
    assert rep["dW"]["text"] == "60 +0.1 -0.2"
    assert rep["dH"]["text"] == "2X Ø10 H7"
    assert rep["dP"]["value"] == pytest.approx(60) and rep["dP"]["text"] == "60 ±0.05"
    assert rep["dA"]["value"] == pytest.approx(30, abs=1e-9) and rep["dA"]["text"] == "30°"
    assert rep["dO"]["value"] == pytest.approx(80)  # H2.x - A.x = 30 - (-50)
    assert rep["dLim"]["text"] == "60 59.9"  # limits: 60 + 0 over 60 - 0.1
    assert draft.fmt(12.5) == "12.5" and draft.fmt(12.0) == "12" and draft.fmt(0.004) == "0"


def test_dimensions_are_associative() -> None:
    doc = plate_doc()
    for p in doc["geom"]["points"]:
        if p["id"] in ("B", "C"):
            p["x"] = 70.0
    rep = {r["id"]: r for r in draft.dimension_report(doc)}
    assert rep["dL"]["value"] == pytest.approx(120)
    doc["geom"]["entities"] = [e for e in doc["geom"]["entities"] if e["id"] != "c1"]
    chk = draft.sheet_check(doc)
    assert "dH" in chk["dangling"] and "cm1" in chk["dangling"] and not chk["passed"]


def test_bad_documents_are_rejected() -> None:
    with pytest.raises(DrawingInputError):
        draft.normalize_doc({"geom": {"points": [{"id": "a", "x": 0, "y": 0}],
                                      "entities": [{"id": "e", "type": "line", "p1": "a", "p2": "zz"}]}})
    with pytest.raises(DrawingInputError, match="fit"):
        draft.normalize_doc({"dims": [{"id": "d", "type": "linear", "a": "a", "b": "b", "pos": [0, 0],
                                       "tol": {"kind": "fit", "fit": "H7; DROP"}}]})
    with pytest.raises(DrawingInputError, match="datum"):
        draft.normalize_doc({"annos": [{"id": "g", "type": "gdt", "pos": [0, 0], "symbol": "parallelism", "tol": "0.1"}]})
    with pytest.raises(DrawingInputError, match="number you enter"):
        draft.normalize_doc({"annos": [{"id": "g", "type": "gdt", "pos": [0, 0], "symbol": "flatness", "tol": "tight"}]})
    with pytest.raises(DrawingInputError):
        draft.normalize_doc({"geom": {"points": [{"id": "a", "x": float("nan"), "y": 0}]}})
    d = draft.new_doc({"size": "ANSI B", "orientation": "portrait", "scale": [1, 2], "units": "in", "projection": "third"})
    assert draft.sheet_wh(d["sheet"]) == (279.4, 431.8) and d["sheet"]["units"] == "in"


def test_sheet_check_passes_and_says_no_model_check() -> None:
    chk = draft.sheet_check(plate_doc())
    assert chk["passed"], chk["problems"]
    assert chk["model_check"] is None and "no model-consistency check" in chk["note"]
    doc = plate_doc()
    doc["dims"][0]["pos"] = [0, -400]  # dimension line far below the frame
    assert draft.sheet_check(doc)["outside"] == ["dL"]


# ----------------------------------------------------------------------------- templates
def test_gasket_template_positions_are_analytic() -> None:
    frag = T.generate("gasket", {"od": 150, "id": 60, "holes": 6, "hole_d": 14, "pcd": 120, "start": 15}, 1.0, "g")
    doc = doc_with(frag)
    geo = draft.Geo(doc)
    holes = [e for e in doc["geom"]["entities"] if e["type"] == "circle" and e["r"] == pytest.approx(7)]
    assert len(holes) == 6
    want = sorted((round(60 * math.cos(math.radians(15 + 60 * i)), 6), round(60 * math.sin(math.radians(15 + 60 * i)), 6)) for i in range(6))
    got = sorted((round(geo.pts[h["c"]][0], 6), round(geo.pts[h["c"]][1], 6)) for h in holes)
    assert got == want
    texts = sorted(r["text"] for r in draft.dimension_report(doc))
    assert texts == sorted(["Ø150", "Ø60", "Ø120", "6X Ø14"])
    assert sum(a["type"] == "centermark" for a in doc["annos"]) == 6
    assert any(e["layer"] == "center" and e["type"] == "circle" and e["r"] == pytest.approx(60) for e in doc["geom"]["entities"])
    with pytest.raises(DrawingInputError, match="between"):
        T.generate("gasket", {"od": 100, "id": 60, "holes": 4, "hole_d": 14, "pcd": 70}, 1.0, "g")


def test_plate_and_washer_templates() -> None:
    frag = T.generate("plate", {"length": 120, "width": 80, "hole_d": 9, "nx": 3, "ny": 2, "edge_x": 15, "edge_y": 12,
                                "corner_r": 5}, 1.0, "p")
    doc = doc_with(frag)
    assert sorted(map(tuple, frag["holes"])) == sorted((-60 + 15 + 45 * i, -40 + 12 + 56 * j) for i in range(3) for j in range(2))
    vals = [(r["text"]) for r in draft.dimension_report(doc)]
    # overall 120 x 80, top row chain 15 + 45 + 45, right column chain 12 + 56, 6X Ø9, R5
    assert vals == ["120", "80", "15", "45", "45", "12", "56", "6X Ø9", "R5"]
    assert draft.sheet_check(doc)["passed"]
    w = doc_with(T.generate("washer", {"od": 24, "id": 13}, 2.0, "w"), scale=[2, 1])
    assert sorted(r["text"] for r in draft.dimension_report(w)) == ["Ø13", "Ø24"]
    with pytest.raises(DrawingInputError):
        T.generate("washer", {"od": 10, "id": 13}, 1.0, "w")


def test_prompt_reader_without_ai() -> None:
    r = T.read_prompt("draw a gasket Ø150 OD, Ø60 ID, 6 × Ø14 on PCD 120")
    assert r == {"template": "gasket", "params": {"od": 150.0, "id": 60.0, "holes": 6, "hole_d": 14.0, "pcd": 120.0}}
    r = T.read_prompt("plate 200 x 100 with 4 holes Ø11, 20 from edges")
    assert r and r["params"]["length"] == 200 and r["params"]["nx"] == 2 and r["params"]["ny"] == 2
    assert r["params"]["hole_d"] == 11 and r["params"]["edge_x"] == 20
    assert T.read_prompt("washer OD 30 ID 13")["params"] == {"od": 30.0, "id": 13.0}  # type: ignore[index]
    assert T.read_prompt("a bracket with a slot") is None
    assert T.fit_scale([150, 150], 420, 297) == [1, 1] and T.fit_scale([150, 150], 297, 210) == [1, 2] and T.fit_scale([400, 200], 420, 297) == [1, 2]


def test_ai_answer_is_validated_and_dimensioned() -> None:
    ans = draft_assist.parse_block('Sure.\n```fw-draft\n{"template": null, "shapes": [{"type": "rect", "c": [0, 0], '
                                   '"w": 80, "h": 40}, {"type": "circle", "c": [20, 0], "d": 12}], "missing": ["thickness"]}\n```')
    assert ans is not None
    frag = draft_assist.interpret(ans, 1.0, "a")
    doc = doc_with(frag)
    assert sorted(r["text"] for r in draft.dimension_report(doc)) == ["40", "80", "Ø12"]
    assert frag["missing"] == ["thickness"]
    with pytest.raises(DrawingInputError):
        draft_assist.interpret({"shapes": [{"type": "circle", "c": [0, 0], "d": "big"}]}, 1.0, "a")
    frag = draft_assist.interpret({"template": "washer", "params": {"od": 20, "id": 8.4, "evil": 1}}, 1.0, "a")
    assert frag["params"] == {"od": 20, "id": 8.4}


# ----------------------------------------------------------------------------- exports
@pytest.fixture(scope="module")
def exports(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from aicad.drawing.draft_dxf import to_dxf
    from aicad.drawing.render import to_pdf, to_svg

    out = tmp_path_factory.mktemp("draft")
    doc = plate_doc()
    sheet = draft.compose(doc)
    (out / "s.svg").write_text(to_svg(sheet, "Plate"), encoding="utf-8")
    to_pdf(sheet, out / "s.pdf", "Plate")
    to_dxf(doc, out / "s.dxf")
    return {"dir": out, "doc": doc, "sheet": sheet}


def test_svg_has_layers_values_and_frame(exports: dict[str, Any]) -> None:
    root = ET.parse(exports["dir"] / "s.svg").getroot()
    ns = "{http://www.w3.org/2000/svg}"
    texts = [t.text for t in root.iter(f"{ns}text")]
    for v in ("100", "Ø10 H7", "60 ±0.05", "30°", "80", "BREAK EDGES", "NOT APPROVED FOR MANUFACTURE", "A",
              "First issue", "DEBURR ALL EDGES", "Ra 1.6"):
        assert any(v in (t or "") for t in texts), v
    classes = {e.get("class") for e in root.iter() if e.get("class")}
    assert {"drw-visible", "drw-hidden", "drw-center_n", "drw-dim_n", "drw-hatch_n", "drw-frame"} <= classes
    assert "drw-construction" not in classes  # construction geometry is never printed
    css = root.find(f"{ns}style").text  # type: ignore[union-attr]
    assert ".drw-hidden{fill:none;stroke:#111111;stroke-width:0.25;stroke-dasharray:3 1.2" in css
    assert ".drw-visible{fill:none;stroke:#111111;stroke-width:0.5;" in css
    # true scale: the 100 mm edge spans 100 paper mm at 1:1
    lines = [p for p in exports["sheet"]["prims"] if p.get("ent") == "AB"]
    assert abs(lines[0]["p"][2] - lines[0]["p"][0]) == pytest.approx(100)
    hatch = [p for p in exports["sheet"]["prims"] if p.get("anno") == "h1"]
    assert hatch and all(p["l"] == "hatch_n" for p in hatch)


def test_pdf_is_valid_and_carries_the_values(exports: dict[str, Any]) -> None:
    data = (exports["dir"] / "s.pdf").read_bytes()
    assert data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF")
    content = b""
    for m in re.finditer(rb"\bstream\r?\n(.*?)endstream", data, re.DOTALL):
        raw = m.group(1).strip()
        try:  # reportlab: /ASCII85Decode /FlateDecode
            content += zlib.decompress(base64.a85decode(raw[:-2] if raw.endswith(b"~>") else raw))
        except (ValueError, zlib.error):
            pass
    for v in (b"(100)", b"(BREAK EDGES)", b"(NOT APPROVED FOR MANUFACTURE)", b"(2D ONLY"):
        assert v in content, v
    assert b"(60 \\2610.05)" in content or b"(60 \xb10.05)" in content  # the ± sign in WinAnsi


def test_dxf_layers_linetypes_dimensions_and_hatch(exports: dict[str, Any]) -> None:
    import ezdxf

    d = ezdxf.readfile(exports["dir"] / "s.dxf")
    audit = d.audit()  # the structural checks CAD readers rely on (handles, owners, table references)
    assert not audit.has_errors, [str(e.message) for e in audit.errors]
    assert d.header["$INSUNITS"] == 4  # millimetres
    lay = {ly.dxf.name: ly for ly in d.layers}
    assert lay["HIDDEN"].dxf.linetype == "ACAD_ISO02W100" and lay["CENTER"].dxf.linetype == "ACAD_ISO04W100"
    assert lay["VISIBLE"].dxf.lineweight == 50 and lay["DIMENSION"].dxf.lineweight == 25
    assert lay["CONSTRUCTION"].dxf.plot == 0
    assert "ACAD_ISO02W100" in d.linetypes and "ACAD_ISO04W100" in d.linetypes
    msp = d.modelspace()
    on = {name: [e for e in msp if e.dxf.layer == name] for name in lay}
    assert len([e for e in on["VISIBLE"] if e.dxftype() == "LINE"]) == 8
    assert sorted(round(e.dxf.radius, 6) for e in on["VISIBLE"] if e.dxftype() == "CIRCLE") == [5.0, 5.0]
    assert len(on["HIDDEN"]) == 1 and len(on["CONSTRUCTION"]) == 1
    ab = next(e for e in on["VISIBLE"] if e.dxftype() == "LINE" and e.dxf.start.y == pytest.approx(-30) and e.dxf.end.y == pytest.approx(-30))
    assert abs(ab.dxf.end.x - ab.dxf.start.x) == pytest.approx(100)  # true size in model space
    dims = msp.query("DIMENSION")
    meas = sorted(round(float(e.get_measurement()), 4) for e in dims if e.dimtype in (0, 1, 3))
    assert meas == sorted([100.0, 60.0, 10.0, 60.0, 60.0])
    texts = {e.dxf.text for e in dims}
    assert "2X <> H7" in texts
    angular = [e for e in dims if e.dimtype in (2, 5)]
    assert len(angular) == 1 and float(angular[0].get_measurement()) == pytest.approx(30, abs=1e-6)
    ordinate = [e for e in dims if (e.dimtype & 7) == 6]
    assert len(ordinate) == 1
    hatches = [e for e in msp.query("HATCH") if e.dxf.layer == "HATCH"]
    assert len(hatches) == 1 and hatches[0].dxf.pattern_name == "ANSI31"
    psp = d.layouts.get("Sheet")
    assert any(e.dxftype() == "TEXT" and "NOT APPROVED" in e.dxf.text for e in psp)
    assert any(e.dxftype() == "VIEWPORT" for e in psp)


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


def _role(email: str, role: str) -> None:
    from sqlalchemy import select

    from aicad.platform.db import session_factory
    from aicad.platform.models import Membership, User

    db = session_factory()()
    me = db.scalar(select(User).where(User.email == email))
    m = db.scalar(select(Membership).where(Membership.user_id == me.id))
    m.role = role
    db.commit()
    db.close()


def test_api_crud_revisions_exports_and_isolation(app_client: Any) -> None:
    from test_platform import signup
    from trial_helpers import set_trial_ended

    c = app_client
    assert c.get("/api/m/drawings/drafts").status_code == 401
    signup(c, "drafter@x.com")
    set_trial_ended("drafter@x.com")
    assert c.get("/api/m/drawings/drafts").status_code == 402
    set_trial_ended("drafter@x.com", False)
    assert c.get("/api/m/drawings/drafts").json() == {"items": []}
    tpl = c.get("/api/m/drawings/drafts/templates").json()
    assert {t["name"] for t in tpl["items"]} == {"gasket", "washer", "plate"} and "A0" in tpl["sheets"]
    r = c.post("/api/m/drawings/drafts", json={"name": "Gasket G1", "sheet": {"size": "A4"}, "template": "gasket",
                                               "params": {"od": 150, "id": 60, "holes": 6, "hole_d": 14, "pcd": 120},
                                               "local_date": "2026-11-18"})
    assert r.status_code == 200, r.text
    st = r.json()
    did = st["id"]
    assert st["rev"] == 1 and st["doc"]["sheet"]["scale"] == [1, 2] and st["doc"]["title"]["drawn_by"] == "Ada Engineer"
    assert st["doc"]["title"]["date"] == "2026-11-18" and st["linked_model"] is None
    assert st["doc"]["title"]["drawing_no"] == f"FW-D{did[:7].upper()}"
    assert "no model-consistency check" in st["check"]["note"] and st["check"]["passed"], st["check"]
    assert sorted(d["text"] for d in st["dimensions"]) == sorted(["Ø150", "Ø60", "Ø120", "6X Ø14"])
    # save a change -> revision 2; stale base -> 409; bad doc -> 422
    doc = st["doc"]
    od = next(e for e in doc["geom"]["entities"] if e["type"] == "circle" and e["r"] == 75)
    od["r"] = 80
    r = c.put(f"/api/m/drawings/drafts/{did}", json={"doc": doc, "base_rev": 1, "note": "OD 160"})
    assert r.status_code == 200 and r.json()["rev"] == 2
    assert "Ø160" in [d["text"] for d in r.json()["dimensions"]]
    assert c.put(f"/api/m/drawings/drafts/{did}", json={"doc": doc, "base_rev": 1}).status_code == 409
    bad = {**doc, "dims": [{"id": "x", "type": "nope", "pos": [0, 0]}]}
    assert c.put(f"/api/m/drawings/drafts/{did}", json={"doc": bad}).status_code == 422
    revs = c.get(f"/api/m/drawings/drafts/{did}").json()["revs"]
    assert [(v["rev"], v["note"]) for v in revs] == [(1, "Created"), (2, "OD 160")]
    old = c.get(f"/api/m/drawings/drafts/{did}/revisions/1").json()["doc"]
    assert any(e.get("r") == 75 for e in old["geom"]["entities"])
    # exports of the latest and of an earlier revision
    svg = c.get(f"/api/m/drawings/drafts/{did}/files/sheet.svg")
    assert svg.status_code == 200 and "Ø160" in svg.text and "2D ONLY · NO MODEL" in svg.text
    assert "Ø150" in c.get(f"/api/m/drawings/drafts/{did}/files/sheet.svg?rev=1").text
    pdf = c.get(f"/api/m/drawings/drafts/{did}/files/sheet.pdf?download=1")
    assert pdf.content.startswith(b"%PDF-") and "Gasket_G1_rev2.pdf" in pdf.headers["content-disposition"]
    dxf = c.get(f"/api/m/drawings/drafts/{did}/files/sheet.dxf")
    assert dxf.status_code == 200 and b"ACAD_ISO04W100" in dxf.content
    assert c.get(f"/api/m/drawings/drafts/{did}/files/..%2Fdraft.json").status_code == 404
    assert c.get(f"/api/m/drawings/drafts/{did}/files/sheet.svg?rev=9").status_code == 404
    # editor helpers
    fr = c.post("/api/m/drawings/drafts/frame", json={"sheet": {"size": "A2"}, "title": {"title": "X"}}).json()
    assert fr["w"] == 594 and any(p.get("txt") == "NOT APPROVED FOR MANUFACTURE" for p in fr["prims"])
    frag = c.post("/api/m/drawings/drafts/templates/washer", json={"params": {"od": 30, "id": 13}, "prefix": "w9"}).json()
    assert all(e["id"].startswith("w9") for e in frag["geom"]["entities"])
    assert c.post("/api/m/drawings/drafts/templates/washer", json={"params": {"od": 10, "id": 13}}).status_code == 422
    # viewers read but don't change
    _role("drafter@x.com", "viewer")
    assert c.get(f"/api/m/drawings/drafts/{did}").json()["can_edit"] is False
    assert c.put(f"/api/m/drawings/drafts/{did}", json={"doc": doc}).status_code == 403
    assert c.post("/api/m/drawings/drafts", json={}).status_code == 403
    _role("drafter@x.com", "owner")
    # another organisation cannot see it
    c.post("/api/auth/logout")
    signup(c, "rival@x.com", workspace="Rival Co")
    assert c.get(f"/api/m/drawings/drafts/{did}").status_code == 404
    assert c.get(f"/api/m/drawings/drafts/{did}/files/sheet.pdf").status_code == 404
    assert c.put(f"/api/m/drawings/drafts/{did}", json={"doc": doc}).status_code == 404
    assert c.delete(f"/api/m/drawings/drafts/{did}").status_code == 404
    assert c.get("/api/m/drawings/drafts").json()["items"] == []
    mine = c.post("/api/m/drawings/drafts", json={"name": "Blank"}).json()
    assert mine["doc"]["geom"]["entities"] == [] and c.delete(f"/api/m/drawings/drafts/{mine['id']}").json()["ok"]


def test_api_assist_template_first_then_mocked_ai(app_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_platform import signup

    c = app_client
    signup(c, "assist@x.com")
    did = c.post("/api/m/drawings/drafts", json={"name": "A"}).json()["id"]
    calls: list[str] = []

    async def fake_agent(request: str, budget_usd: float | None = None) -> tuple[str, float | None]:
        calls.append(request)
        answer = ('```fw-draft\n{"template": "plate", "params": {"length": 90, "width": 50, "hole_d": 6.6, "nx": 2, '
                  '"ny": 1, "edge_x": 10, "edge_y": 25}, "missing": ["plate thickness"]}\n```')
        return answer, 0.002

    monkeypatch.setattr(draft_assist, "run_agent", fake_agent)
    r = c.post(f"/api/m/drawings/drafts/{did}/assist", json={"prompt": "draw a gasket Ø150 OD, Ø60 ID, 6 × Ø14 on PCD 120"})
    assert r.status_code == 200 and r.json()["source"] == "template" and calls == []
    frag = r.json()["fragment"]
    assert frag["params"]["pcd"] == 120 and len(frag["annos"]) == 6
    r = c.post(f"/api/m/drawings/drafts/{did}/assist", json={"prompt": "mounting strip for two M6 screws"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "ai" and calls == ["mounting strip for two M6 screws"]
    assert body["missing"] == ["plate thickness"] and body["fragment"]["params"]["length"] == 90

    async def junk(request: str, budget_usd: float | None = None) -> tuple[str, float | None]:
        return "I can't do that", None

    monkeypatch.setattr(draft_assist, "run_agent", junk)
    assert c.post(f"/api/m/drawings/drafts/{did}/assist", json={"prompt": "a thing"}).status_code == 422
