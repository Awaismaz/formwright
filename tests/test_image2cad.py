"""Image & Drawing to CAD: token parser, vector-PDF extraction, upload validation, vision parsing, the review
(questions / readiness / hand-off prompt) and the API (auth, entitlement, scoping, agent hand-off).

Fixture FX-I2C-1 (original, generated here with reportlab): an A4 landscape sheet at SCALE 1:2 in mm with a front
view drawn 50 x 20 mm (so 100 x 40 real) and a top view drawn 50 x 30 mm below it (100 x 60 real). Every
expected value and position below comes from the texts and coordinates written into the fixture, never from the
reader's own output. No test calls a model: the design agent and the vision reader are mocked.
"""

from __future__ import annotations

import base64
import io
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from trial_helpers import set_trial_ended

from aicad.image2cad import InputError, review, sniff, tokens, vision
from aicad.image2cad.vector import read_pdf

# ----------------------------------------------------------------------------- token parser
CASES: list[tuple[str, dict[str, Any]]] = [
    ("100", {"kind": "linear", "value": 100.0}),
    ("12.5", {"kind": "linear", "value": 12.5}),
    ("12,5", {"kind": "linear", "value": 12.5}),
    (".5", {"kind": "linear", "value": 0.5}),
    ("Ø12 H7", {"kind": "diameter", "value": 12.0, "fit": "H7"}),
    ("⌀10", {"kind": "diameter", "value": 10.0}),
    ("Ø12 H7/g6", {"kind": "diameter", "value": 12.0, "fit": "H7/g6"}),
    ("R5", {"kind": "radius", "value": 5.0}),
    ("SR10", {"kind": "spherical_radius", "value": 10.0}),
    ("□20", {"kind": "square", "value": 20.0}),
    ("4X Ø6.6 THRU", {"kind": "diameter", "value": 6.6, "count": 4, "through": True}),
    ("4XØ6", {"kind": "diameter", "value": 6.0, "count": 4}),
    ("4 HOLES Ø8", {"kind": "diameter", "value": 8.0, "count": 4}),
    ("Ø6 (4X)", {"kind": "diameter", "value": 6.0, "count": 4}),
    ("2X R5", {"kind": "radius", "value": 5.0, "count": 2}),
    ("R5 TYP 4 PLCS", {"kind": "radius", "value": 5.0, "count": 4, "modifiers": ["typ"]}),
    ("Ø6 DEEP 10", {"kind": "diameter", "value": 6.0, "depth": 10.0}),
    ("Ø6 ↧10", {"kind": "diameter", "value": 6.0, "depth": 10.0}),
    ("M8x1.25", {"kind": "thread", "value": 8.0, "pitch": 1.25}),
    ("M8", {"kind": "thread", "value": 8.0, "pitch": None}),
    ("M8x1.25-6H THRU", {"kind": "thread", "value": 8.0, "pitch": 1.25, "thread_class": "6H", "through": True}),
    ("6 x M5 - 6H", {"kind": "thread", "value": 5.0, "count": 6, "thread_class": "6H"}),
    ("25±0.1", {"kind": "linear", "value": 25.0, "tol": {"plus": 0.1, "minus": 0.1}}),
    ("25 +/- 0.1", {"kind": "linear", "value": 25.0, "tol": {"plus": 0.1, "minus": 0.1}}),
    ("25 +0.1/-0.05", {"kind": "linear", "value": 25.0, "tol": {"plus": 0.1, "minus": 0.05}}),
    ("Ø25 +0.021/0", {"kind": "diameter", "value": 25.0, "tol": {"plus": 0.021, "minus": 0.0}}),
    ("Ø20 h6 +0/-0.013", {"kind": "diameter", "value": 20.0, "fit": "h6", "tol": {"plus": 0.0, "minus": 0.013}}),
    ("45°", {"kind": "angle", "value": 45.0}),
    ("45° ±0.5°", {"kind": "angle", "value": 45.0, "tol": {"plus": 0.5, "minus": 0.5}}),
    ("1 x 45°", {"kind": "chamfer", "value": 1.0, "angle": 45.0}),
    ("C1", {"kind": "chamfer", "value": 1.0, "angle": 45.0}),
    ("1:2", {"kind": "scale", "ratio": [1.0, 2.0]}),
    ("SCALE 1:2", {"kind": "scale", "ratio": [1.0, 2.0]}),
    ("2:1", {"kind": "scale", "ratio": [2.0, 1.0]}),
    ("(10)", {"kind": "linear", "value": 10.0, "reference": True}),
    ("40 REF", {"kind": "linear", "value": 40.0, "reference": True}),
    ("10 TYP", {"kind": "linear", "value": 10.0, "modifiers": ["typ"]}),
    ("Ø50 PCD", {"kind": "diameter", "value": 50.0, "modifiers": ["pcd"]}),
    ('1.250"', {"kind": "linear", "value": 1.25, "unit": "in"}),
    ("100 mm", {"kind": "linear", "value": 100.0, "unit": "mm"}),
]
NOT_DIMS = ["120 SPEC: equals a declared model parameter", "2026-11-16", "FW-TEST0001", "A3 1 / 1", "Model rev 1",
            "ISO 2768-m", "1. DIMENSIONS IN MILLIMETRES", "A", "SECTION A-A", "BREAK SHARP EDGES 0.5 MAX", "",
            "Aluminium 6061-T6", "REV B"]


@pytest.mark.parametrize("text,want", CASES)
def test_token_parser_hand_cases(text: str, want: dict[str, Any]) -> None:
    d = tokens.parse(text)
    assert d is not None, text
    for k, v in want.items():
        assert d[k] == v, (text, k, d[k])


@pytest.mark.parametrize("text", NOT_DIMS)
def test_sentences_and_title_texts_are_not_dimensions(text: str) -> None:
    assert tokens.parse(text) is None


def test_label_round_trips_canonical_callouts() -> None:
    for text in ("4X Ø6.6 THRU", "Ø12 H7", "R5", "M8x1.25-6H", "25 ±0.1", "45°", "(10)", "Ø6 DEEP 10", "1 x 45°",
                 "25 +0.1/-0.05", "□20"):
        d = tokens.parse(text)
        assert d is not None
        assert tokens.label(d) == text
        assert tokens.parse(tokens.label(d))["value"] == d["value"]


# ----------------------------------------------------------------------------- vector PDF fixture
MM = 72 / 25.4
PAGE_W, PAGE_H = 297.0, 210.0
FONT = 3.5  # mm
# (text, x, y, rotated): x, y in mm from the bottom-left (reportlab), text centred on x; rotated texts run upward
TEXTS = [
    ("100", 65.0, 135.0, False),          # front view width (above the front view)
    ("40", 97.0, 120.0, True),            # front view height (right of the front view)
    ("60", 97.0, 75.0, True),             # top view depth (right of the top view)
    ("4X Ø6.6 THRU", 65.0, 53.0, False),  # holes, below the top view
    ("R5", 33.0, 88.0, False),            # corner radius, top view
    ("M8x1.25", 33.0, 64.0, False),       # thread, top view
    ("25±0.1", 65.0, 95.5, False),        # between the views, nearer the top view
]


def _outline(c: Any, x0: float, y0: float, w: float, h: float) -> None:
    c.setLineWidth(0.5 * MM)
    c.rect(x0 * MM, y0 * MM, w * MM, h * MM, stroke=1, fill=0)


def make_pdf(path: Path, with_title: bool = True) -> None:
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=(PAGE_W * MM, PAGE_H * MM), invariant=1)
    c.setLineWidth(0.7 * MM)
    c.rect(10 * MM, 10 * MM, (PAGE_W - 20) * MM, (PAGE_H - 20) * MM)  # frame
    _outline(c, 40, 110, 50, 20)  # front view: 100 x 40 at 1:2
    _outline(c, 40, 60, 50, 30)   # top view: 100 x 60 at 1:2
    c.circle(45 * MM, 65 * MM, 1.65 * MM, stroke=1, fill=0)
    c.setLineWidth(0.18 * MM)  # a thin dimension line
    c.line(40 * MM, 133 * MM, 90 * MM, 133 * MM)
    c.setFont("Helvetica", FONT * MM)
    for txt, x, y, rot in TEXTS:
        c.saveState()
        c.translate(x * MM, y * MM)
        if rot:
            c.rotate(90)
        c.drawCentredString(0, 0, txt)
        c.restoreState()
    c.setFont("Helvetica", 2.5 * MM)
    c.drawString(20 * MM, 30 * MM, "1. BREAK SHARP EDGES 0.5 MAX")
    if with_title:
        c.setLineWidth(0.35 * MM)
        c.rect(190 * MM, 15 * MM, 100 * MM, 30 * MM)
        for lab, val, x, y in (("TITLE", "Test plate", 192, 40), ("SCALE", "1:2", 192, 28), ("UNITS", "mm", 222, 28),
                               ("DRAWN", "QA", 252, 28), ("REV", "3", 272, 28)):
            c.setFont("Helvetica", 1.8 * MM)
            c.drawString(x * MM, y * MM, lab)
            c.setFont("Helvetica", 3.0 * MM)
            c.drawString(x * MM, (y - 4.5) * MM, val)
    c.showPage()
    c.save()


def _expected_centre(x: float, y: float, rot: bool) -> tuple[float, float]:
    """Glyph-box centre (Helvetica ascent 0.718, descent 0.207) in normalised top-left coordinates."""
    off = (0.718 - 0.207) / 2 * FONT
    cx, cy = (x - off, y) if rot else (x, y + off)
    return cx / PAGE_W, 1 - cy / PAGE_H


@pytest.fixture(scope="module")
def pdf_read(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    p = tmp_path_factory.mktemp("i2c") / "plate.pdf"
    make_pdf(p)
    return read_pdf(p)


def test_vector_pdf_values_and_positions(pdf_read: dict[str, Any]) -> None:
    got = {d["text"]: d for d in pdf_read["dims"]}
    assert set(got) == {t for t, *_ in TEXTS}  # nothing missing, no note or title text taken as a dimension
    for txt, x, y, rot in TEXTS:
        d = got[txt]
        ex, ey = _expected_centre(x, y, rot)
        assert abs(d["x"] - ex) * PAGE_W < 1.0 and abs(d["y"] - ey) * PAGE_H < 1.0, (txt, d["x"], d["y"], ex, ey)
        assert d["confidence"] == 1.0 and d["source"] == "text"
    assert got["100"]["dir"] == "horizontal" and got["40"]["dir"] == "vertical" and got["60"]["dir"] == "vertical"
    assert got["4X Ø6.6 THRU"]["count"] == 4 and got["4X Ø6.6 THRU"]["value"] == 6.6 and got["4X Ø6.6 THRU"]["through"]
    assert got["M8x1.25"]["kind"] == "thread" and got["M8x1.25"]["pitch"] == 1.25
    assert got["25±0.1"]["tol"] == {"plus": 0.1, "minus": 0.1}


def test_vector_pdf_views_title_block_and_scale_check(pdf_read: dict[str, Any]) -> None:
    r = pdf_read
    assert r["scale"]["ratio"] == [1.0, 2.0] and "Title block" in r["scale"]["evidence"]
    assert r["units"]["value"] == "mm" and r["title"]["TITLE"] == "Test plate" and r["title"]["REV"] == "3"
    views = sorted(r["views"], key=lambda v: v["box"][1])
    assert len(views) == 2
    front, top = views
    assert front["drawn_mm"] == pytest.approx([50.0, 20.0], abs=0.6)  # outline stroke adds half a line width
    assert top["drawn_mm"] == pytest.approx([50.0, 30.0], abs=0.6)
    got = {d["text"]: d["view"] for d in r["dims"]}
    assert got["100"] == front["id"] and got["40"] == front["id"]
    for t in ("60", "4X Ø6.6 THRU", "R5", "M8x1.25", "25±0.1"):
        assert got[t] == top["id"], t
    # drawn 50 mm at 1:2 = 100: the width dimension is confirmed by the geometry; the height too (20 -> 40)
    checks = {(c["view"], c["axis"]): c for c in r["checks"]}
    assert checks[(front["id"], "width")]["match"] and checks[(front["id"], "height")]["match"]
    assert checks[(top["id"], "height")]["match"] and checks[(top["id"], "height")]["value"] == 60.0
    # two unlabelled orthographic views: the review must ask which one is the front
    st = review.state(r, None)
    q = next(n for n in st["needs"] if n["id"] == "front_view")
    assert {o["value"] for o in q["options"]} == {front["id"], top["id"]}


def test_vector_pdf_without_title_block_has_no_scale(tmp_path: Path) -> None:
    p = tmp_path / "bare.pdf"
    make_pdf(p, with_title=False)
    r = read_pdf(p)
    assert r["scale"] is None and r["title"] == {}
    assert all("implied_scale" in c for c in r["checks"])
    st = review.state(r, None)
    assert st["scale"]["status"] == "undefined" and not st["ready"]


@pytest.fixture(scope="module")
def formwright_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from test_drawings import DRAW_META, write_model

    from aicad.drawing.generate import generate

    ws = tmp_path_factory.mktemp("fwdrw")
    write_model(ws / "out")
    generate(ws / "out", ws / "drawings", {"section": "y"}, DRAW_META)
    return ws / "drawings" / "sheet.pdf"


def test_round_trip_formwright_drawing(formwright_pdf: Path) -> None:
    """A Drawing Studio sheet of FX-DRW-1 (100 x 60 x 20 block, 4 x Ø8 through, Ø6 x 10 blind) reads back."""
    r = read_pdf(formwright_pdf)
    texts = sorted(d["text"] for d in r["dims"])
    for t in ("100", "60", "20", "80", "40", "4X Ø8 THRU", "Ø6 DEEP 10", "(10)"):
        assert t in texts, t
    assert r["scale"]["ratio"] == [1.0, 1.0] and r["units"]["value"] == "mm"
    labels = {v.get("label") for v in r["views"]}
    assert "SECTION A-A" in labels and "ISOMETRIC VIEW" in labels
    front = next(v for v in r["views"] if v.get("suggest_front"))
    assert front["drawn_mm"] == pytest.approx([100.0, 20.0], abs=0.6)
    assert any(c["match"] and c["value"] == 100.0 for c in r["checks"] if c.get("match") is not None)
    # the legend ("120 SPEC: ..."), notes and title block never become dimensions
    assert "120" not in texts and "1" not in texts


# ----------------------------------------------------------------------------- upload validation
def _png(w: int = 64, h: int = 48) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, "PNG")
    return buf.getvalue()


def test_upload_type_sniffing_and_size_limits(tmp_path: Path) -> None:
    assert sniff.validate(b"%PDF-1.7\n...") == "pdf"
    assert sniff.validate(_png()) == "png"
    assert sniff.validate(b"\xff\xd8\xff\xe0" + b"0" * 20) == "jpg"
    assert sniff.validate(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    for bad in (b"GIF89a....", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"PK\x03\x04zip", b"MZ\x90\x00exe"):
        with pytest.raises(InputError, match="Unsupported"):
            sniff.validate(bad)
    with pytest.raises(InputError, match="empty"):
        sniff.validate(b"")
    with pytest.raises(InputError, match="larger than 12 MB"):
        sniff.validate(b"\x89PNG\r\n\x1a\n" + b"\0" * (sniff.MAX_IMAGE_BYTES + 1))
    with pytest.raises(InputError, match="larger than 20 MB"):
        sniff.validate(b"%PDF-1.4" + b"\0" * (sniff.MAX_PDF_BYTES + 1))
    # a truncated PNG (valid signature, broken body) is refused, not crashed on
    (tmp_path / "bad.png").write_bytes(_png()[:40])
    with pytest.raises(InputError, match="could not be read"):
        sniff.normalise_image(tmp_path / "bad.png", tmp_path / "out.png")
    # big images are downscaled for the preview
    (tmp_path / "big.png").write_bytes(_png(4000, 1000))
    info = sniff.normalise_image(tmp_path / "big.png", tmp_path / "out.png")
    assert (info["w"], info["h"]) == (2000, 500) and info["source_px"] == [4000, 1000]


def test_damaged_and_scanned_pdfs(tmp_path: Path) -> None:
    from aicad.image2cad.extract import run

    d = tmp_path / "u"
    d.mkdir()
    (d / "source.pdf").write_bytes(b"%PDF-1.4\nthis is not a real pdf")
    (d / "meta.json").write_text(json.dumps({"type": "pdf", "file": "source.pdf"}))
    with pytest.raises(InputError):
        run(d)
    # a PDF with only an image and no text layer is a scan: it goes to the vision reader
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(d / "source.pdf"), pagesize=(200, 150))
    c.drawImage(ImageReader(io.BytesIO(_png())), 10, 10, 100, 75)
    c.showPage()
    c.save()
    out = run(d)
    assert out["needs_vision"] and out["read"] is None and (d / "preview.png").is_file()


# ----------------------------------------------------------------------------- vision (mocked)
VISION_ANSWER = """Here is what I can read.

```fw-read
{"drawing_kind": "sketch", "part": "L-shaped bracket with two holes", "units": null, "scale": null,
 "views": [{"id": "v1", "label": null, "looks_like": "side", "box": [0.1, 0.2, 0.9, 0.8]}],
 "dimensions": [
   {"text": "120", "x": 0.5, "y": 0.85, "view": "v1", "confidence": 0.92, "describes": "overall length"},
   {"text": "12", "x": 0.3, "y": 0.4, "view": "v1", "confidence": 0.55, "alternatives": ["17"],
    "kind_unclear": ["diameter", "radius"], "describes": "hole"},
   {"text": "about 40ish", "x": 0.8, "y": 0.3, "confidence": 0.4}
 ],
 "unreadable": [{"note": "smudged note near the top right", "x": 0.85, "y": 0.1}],
 "missing": [{"what": "Thickness", "why": "only one view is drawn"}, {"what": "Units", "why": "not written"}]}
```"""


def test_vision_block_parsing_and_questions() -> None:
    raw = vision.parse_block(VISION_ANSWER)
    assert raw is not None
    r = vision.to_read(raw)
    assert [d["text"] for d in r["dims"]] == ["120", "12"]
    assert r["unparsed"][0]["text"] == "about 40ish"
    assert vision.parse_block("no block at all") is None
    st = review.state(r, None)
    ids = {n["id"] for n in st["needs"]}
    assert {"reference", "confirm_d2", "kind_d2", "unparsed_0", "unreadable_0", "missing_0"} <= ids
    assert "confirm_d1" not in ids  # high confidence is listed as read, not asked
    assert "missing_1" not in ids  # units are set with the reference, never a separate guess
    assert st["open"] == len(st["needs"]) and not st["ready"]
    assert st["scale"]["status"] == "undefined"  # never guessed
    # answer everything
    rv = review.clean_review({
        "reference": {"dim": "d1", "value": 120, "unit": "mm"},
        "answers": {"confirm_d2": {"choice": "keep"}, "kind_d2": {"choice": "diameter"},
                    "unparsed_0": {"choice": "note"}, "unreadable_0": {"choice": "ignore"},
                    "missing_0": {"choice": "value", "value": 6, "unit": "mm"}}}, r)
    st = review.state(r, rv)
    assert st["ready"] and st["scale"]["status"] == "confirmed"
    prompt = review.handoff_prompt({"name": "sketch.png"}, r, st, rv)
    assert "120 mm, overall length" in prompt and "Ø12" in prompt and "Thickness = 6 mm" in prompt
    assert "Do not measure any size from the reference image" in prompt
    assert "Note written on the drawing: “about 40ish”" in prompt


def test_handoff_prompt_contains_exactly_the_confirmed_values(pdf_read: dict[str, Any]) -> None:
    r = pdf_read
    by = {d["text"]: d["id"] for d in r["dims"]}
    front = next(v for v in r["views"] if v.get("suggest_front"))
    with pytest.raises(InputError):
        review.clean_review({"dims": {by["R5"]: {"text": "about five"}}}, r)
    rv = review.clean_review({
        "dims": {by["R5"]: {"excluded": True}, by["25±0.1"]: {"text": "25±0.2"}},
        "added": [{"text": "1 x 45°", "describes": "top edges"}],
        "reference": {"dim": by["100"], "value": 100, "unit": "mm"},
        "answers": {"front_view": {"choice": front["id"]}}}, r)
    st = review.state(r, rv)
    assert st["ready"], [n for n in st["needs"] if not n["answered"]]
    p = review.handoff_prompt({"name": "plate.pdf"}, r, st, rv)
    body = p.split("Confirmed dimensions")[1].split("Rules:")[0]
    for t in ("100", "40", "60", "4X Ø6.6 THRU", "M8x1.25", "25 ±0.2", "1 x 45°"):
        assert t in body, t
    assert "R5" not in body and "25 ±0.1" not in body.split("corrected by me from")[0].split("25 ±0.2")[0]
    assert "corrected by me from “25±0.1”" in body and "added by me" in body
    assert "Drawing scale: 1:2" in p and "Front view:" in p
    lines = [ln for ln in body.splitlines() if ln.strip()[:2].rstrip(".").isdigit()]
    assert len(lines) == 7  # exactly the six included read values + the added one


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


def _wait(c: Any, uid: str, timeout: float = 60) -> dict[str, Any]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = c.get(f"/api/m/image2cad/uploads/{uid}").json()
        if r["upload"]["status"] != "reading":
            return r
        time.sleep(0.2)
    raise AssertionError("read did not finish")


def _unlock(c: Any) -> None:
    pay = c.post("/api/billing/checkout", json={"product_code": "addon_image2cad"}).json()["payment_id"]
    c.post(f"/api/billing/payments/{pay}/simulate", json={"outcome": "success"})


def test_api_auth_entitlement_upload_review_and_create(app_client: Any, tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy import select
    from test_platform import signup

    from aicad.agent.session import AgentSession
    from aicad.platform.db import session_factory
    from aicad.platform.models import Membership, Project, User
    from aicad.platform.routers.projects import workspace_for

    sent: list[str] = []
    shown: list[str | None] = []

    async def fake_send(self: AgentSession, prompt: str, shown_text: str | None = None, **kw: Any) -> None:
        sent.append(prompt)
        shown.append(kw.get("shown", shown_text))

    monkeypatch.setattr(AgentSession, "send", fake_send)
    c = app_client
    assert c.get("/api/m/image2cad/uploads").status_code == 401
    signup(c, "i2c@x.com")
    set_trial_ended("i2c@x.com")  # a running trial may use every live module: test the paywall after it
    r = c.get("/api/m/image2cad/uploads")
    assert r.status_code == 402 and "add-on" in r.json()["detail"]["message"]
    pdf = tmp_path / "plate.pdf"
    make_pdf(pdf)
    b64 = base64.b64encode(pdf.read_bytes()).decode()
    assert c.post("/api/m/image2cad/uploads", json={"filename": "plate.pdf", "data_b64": b64}).status_code == 402
    set_trial_ended("i2c@x.com", False)
    _unlock(c)
    # validation
    bad = c.post("/api/m/image2cad/uploads", json={"filename": "x.gif", "data_b64": base64.b64encode(b"GIF89a..").decode()})
    assert bad.status_code == 415
    assert c.post("/api/m/image2cad/uploads", json={"filename": "x.pdf", "data_b64": "@@@"}).status_code == 400
    # upload -> read -> review
    up = c.post("/api/m/image2cad/uploads", json={"filename": "../../plate.pdf", "data_b64": b64})
    assert up.status_code == 200, up.text
    uid = up.json()["upload"]["id"]
    assert up.json()["upload"]["name"] == "plate.pdf"
    full = _wait(c, uid)
    assert full["upload"]["status"] == "review" and full["upload"]["method"] == "vector", full["upload"]
    assert full["state"]["name"] == "Test plate"  # AMI-24: the title block's title, not the file name
    assert len(full["read"]["dims"]) == len(TEXTS) and not full["state"]["ready"]
    assert c.get(f"/api/m/image2cad/uploads/{uid}/preview.png").content.startswith(b"\x89PNG")
    assert c.get(f"/api/m/image2cad/uploads/{uid}/source").content.startswith(b"%PDF-")
    # not ready -> cannot create
    assert c.post(f"/api/m/image2cad/uploads/{uid}/create", json={}).status_code == 409
    by = {d["text"]: d["id"] for d in full["read"]["dims"]}
    assert c.post(f"/api/m/image2cad/uploads/{uid}/review", json={"dims": {by["R5"]: {"text": "nope"}}}).status_code == 422
    front = next(v for v in full["read"]["views"] if v.get("suggest_front"))
    rv = c.post(f"/api/m/image2cad/uploads/{uid}/review", json={
        "reference": {"dim": by["100"], "value": 100, "unit": "mm"}, "answers": {"front_view": {"choice": front["id"]}},
        "dims": {by["R5"]: {"excluded": True}}})
    assert rv.status_code == 200 and rv.json()["state"]["ready"]
    assert c.get("/api/m/image2cad/uploads").json()["items"][0]["counts"] == {"dims": len(TEXTS) - 1, "open": 0}
    # create: new project, reference attached, one structured prompt to the agent
    cr = c.post(f"/api/m/image2cad/uploads/{uid}/create", json={"name": "Plate from drawing"})
    assert cr.status_code == 200, cr.text
    pid = cr.json()["project_id"]
    time.sleep(0.2)
    assert len(sent) == 1 and "100" in sent[0] and "R5" not in sent[0].split("Rules:")[0]
    assert "[Reference image(s) attached by the user: refs/ref_" in sent[0]
    # AMI-16: the chat shows a short summary as the user's message; the brief and its rules go to the agent only
    assert shown[0] is not None and shown[0].startswith("Model from plate.pdf: 6 confirmed values, reference 100 mm")
    assert "Rules:" not in shown[0] and "Do not measure" not in shown[0]
    assert shown[0].endswith("[Reference image attached]") and "Values: 100, 40, 25 ±0.1, 60" in shown[0]
    assert "prompt" not in cr.json()  # the brief is never returned to the browser either
    db = session_factory()()
    p = db.get(Project, pid)
    ws = workspace_for(p)
    assert p.name == "Plate from drawing"
    assert list((ws / "refs").glob("ref_*.png")) and (ws / "image2cad" / "spec.json").is_file()
    assert (ws / "image2cad" / "source.pdf").read_bytes().startswith(b"%PDF-")
    db.close()
    got = c.get(f"/api/m/image2cad/uploads/{uid}").json()
    assert got["upload"]["status"] == "created" and got["project"]["id"] == pid
    # viewers can read but not change
    db = session_factory()()
    me = db.scalar(select(User).where(User.email == "i2c@x.com"))
    m = db.scalar(select(Membership).where(Membership.user_id == me.id))
    m.role = "viewer"
    db.commit()
    db.close()
    assert c.get(f"/api/m/image2cad/uploads/{uid}").json()["can_edit"] is False
    assert c.post(f"/api/m/image2cad/uploads/{uid}/review", json={}).status_code == 403
    assert c.post("/api/m/image2cad/uploads", json={"filename": "p.pdf", "data_b64": b64}).status_code == 403
    assert c.delete(f"/api/m/image2cad/uploads/{uid}").status_code == 403
    # another organisation sees nothing
    c.post("/api/auth/logout")
    signup(c, "other@x.com", workspace="Other Co")
    _unlock(c)
    assert c.get(f"/api/m/image2cad/uploads/{uid}").status_code == 404
    assert c.get(f"/api/m/image2cad/uploads/{uid}/preview.png").status_code == 404
    assert c.get("/api/m/image2cad/uploads").json()["items"] == []
    assert c.get("/api/m/image2cad/uploads/not-an-id").status_code == 404


def test_api_image_goes_through_vision_and_is_metered(app_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_platform import signup

    calls: list[str] = []
    budgets: list[float | None] = []

    async def fake_agent(folder: Path, image: str, budget_usd: float | None = None) -> tuple[str, float]:
        assert (folder / image).is_file()
        budgets.append(budget_usd)
        calls.append(image)
        return VISION_ANSWER, 0.05

    monkeypatch.setattr(vision, "run_agent", fake_agent)
    c = app_client
    signup(c, "img@x.com")
    _unlock(c)
    before = c.get("/api/auth/me").json()["org"]["token_balance"]
    up = c.post("/api/m/image2cad/uploads", json={"filename": "sketch.png", "data_b64": base64.b64encode(_png()).decode()})
    assert up.status_code == 200
    full = _wait(c, up.json()["upload"]["id"])
    assert full["upload"]["method"] == "vision" and full["upload"]["status"] == "review"
    assert calls in (["vision.png"], ["vision.jpg"])  # the compact copy, never the full preview
    needs = {n["id"]: n for n in full["state"]["needs"]}
    assert needs["reference"]["answered"] is False and "kind_d2" in needs and "missing_0" in needs
    assert c.get("/api/auth/me").json()["org"]["token_balance"] == before - 5  # $0.05 at $0.01 per token
    # the read is capped at what the workspace holds, so it can never take the balance below zero (AMI-03)
    assert budgets == [pytest.approx(before * 0.01)]


def test_catalog_marks_image2cad_live_without_claims() -> None:
    from aicad.engineering import wording
    from aicad.platform.catalog import MODULES

    m = MODULES["image2cad"]
    assert m["status"] == "live"
    assert not wording.claims(m["summary"] + " ".join(m["bullets"]))
    # the hand-off never claims the model is verified against the drawing
    assert not wording.claims(review.handoff_prompt.__doc__ or "")


def test_vision_copy_is_compact(tmp_path: Path) -> None:
    """Photos went to the vision read as large PNGs and overflowed the agent stream; the copy must be small."""
    import random

    from PIL import Image, ImageDraw

    from aicad.image2cad.vision import VISION_PX, vision_copy

    rnd = random.Random(7)
    photo = Image.new("RGB", (1800, 1200))
    photo.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(1800 * 1200)])
    photo.save(tmp_path / "preview.png")
    name = vision_copy(tmp_path, "preview.png")
    with Image.open(tmp_path / name) as im:
        assert max(im.size) == VISION_PX
    assert name == "vision.jpg" and (tmp_path / name).stat().st_size < (tmp_path / "preview.png").stat().st_size / 3
    drawing = Image.new("RGB", (1200, 800), "white")
    ImageDraw.Draw(drawing).rectangle((100, 100, 1100, 700), outline="black", width=3)
    drawing.save(tmp_path / "preview.png")
    assert vision_copy(tmp_path, "preview.png") == "vision.png"  # line art: PNG is the smaller, sharper copy
    assert not (tmp_path / "vision.jpg").exists()


# ----------------------------------------------------------------------------- audit fixes (AMI-03, 15, 24, 25, I1)
def test_cost_estimate_starts_from_the_measured_run_and_learns(tmp_path: Path) -> None:
    """AMI-03: with no history the estimate is the measured audit run (read 63, build 275); after 3 measured runs
    it is their median, and the upper figure is the 90th percentile (nearest rank)."""
    from aicad.image2cad import cost

    e = cost.estimate(tmp_path)
    assert e["read"] == {"tokens": 63, "high": 63, "runs": 0, "basis": "seed"}
    assert e["build"]["tokens"] == 275 and e["build"]["basis"] == "seed"
    cost.record(tmp_path, "build", 310)
    e = cost.estimate(tmp_path)["build"]  # pool [310, 275]: median 292.5 -> 293, p90 -> 310
    assert (e["tokens"], e["high"], e["runs"]) == (293, 310, 1)
    for t in (200, 400):
        cost.record(tmp_path, "build", t)
    e = cost.estimate(tmp_path)["build"]  # measured only: [310, 200, 400]
    assert (e["tokens"], e["high"], e["basis"]) == (310, 400, "measured")
    cost.record(tmp_path, "read", 0)  # nothing measured: ignored
    assert cost.estimate(tmp_path)["read"]["runs"] == 0
    assert cost.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9) == 9
    chat = tmp_path / "chat.jsonl"
    chat.write_text("\n".join(json.dumps(e) for e in (
        {"type": "user", "text": "earlier"}, {"type": "result", "cost_est_usd": 0.4},
        {"type": "user", "text": "hand-off"}, {"type": "text", "text": "working"})), encoding="utf-8")
    assert cost.first_result_tokens(chat, 2) == ("pending", None)
    with chat.open("a", encoding="utf-8") as f:
        f.write("\n" + json.dumps({"type": "result", "cost_est_usd": 2.75}))
    assert cost.first_result_tokens(chat, 2) == ("done", 2.75)
    assert cost.first_result_tokens(tmp_path / "none.jsonl", 0) == ("pending", None)


def _set_balance(email: str, tokens: int) -> None:
    from sqlalchemy import select

    from aicad.platform.db import session_factory
    from aicad.platform.models import Membership, Organization, User

    db = session_factory()()
    me = db.scalar(select(User).where(User.email == email))
    org = db.get(Organization, db.scalar(select(Membership).where(Membership.user_id == me.id)).org_id)
    org.token_balance = tokens
    db.commit()
    db.close()


def test_runs_start_only_when_the_balance_covers_the_estimate(app_client: Any, tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """AMI-03: an image read and a model build each need their upper measured estimate in the balance (402 with
    the numbers otherwise); the real build cost is recorded and moves the next estimate; the round-trip check
    draws the built model and finds the confirmed values (AMI-I1)."""
    from test_drawings import write_model
    from test_platform import signup

    from aicad.agent.session import AgentSession
    from aicad.platform.db import session_factory
    from aicad.platform.models import Project
    from aicad.platform.routers.projects import workspace_for

    async def fake_send(self: AgentSession, prompt: str, **kw: Any) -> None:
        return None

    monkeypatch.setattr(AgentSession, "send", fake_send)
    c = app_client
    signup(c, "cost@x.com")
    _unlock(c)
    est = c.get("/api/m/image2cad/estimate").json()
    assert est["read"]["tokens"] == 63 and est["build"]["tokens"] == 275 and est["unlimited"] is False
    assert c.get("/api/m/image2cad/uploads").json()["estimate"]["balance"] == est["balance"]
    _set_balance("cost@x.com", 50)
    png = base64.b64encode(_png()).decode()
    r = c.post("/api/m/image2cad/uploads", json={"filename": "sketch.png", "data_b64": png})
    assert r.status_code == 402 and "Reading an image takes about 63 tokens" in r.json()["detail"]["message"]
    assert "has 50" in r.json()["detail"]["message"] and r.json()["detail"]["cta"] == "/app/billing#tokens"
    assert c.get("/api/m/image2cad/uploads").json()["items"] == []  # nothing stored, nothing read
    pdf = tmp_path / "plate.pdf"
    make_pdf(pdf)
    up = c.post("/api/m/image2cad/uploads", json={"filename": "plate.pdf",
                                                    "data_b64": base64.b64encode(pdf.read_bytes()).decode()})
    assert up.status_code == 200  # a vector PDF is read from its text: no tokens
    uid = up.json()["upload"]["id"]
    full = _wait(c, uid)
    by = {d["text"]: d["id"] for d in full["read"]["dims"]}
    front = next(v for v in full["read"]["views"] if v.get("suggest_front"))
    c.post(f"/api/m/image2cad/uploads/{uid}/review", json={
        "reference": {"dim": by["100"], "value": 100, "unit": "mm"}, "answers": {"front_view": {"choice": front["id"]}}})
    _set_balance("cost@x.com", 200)
    r = c.post(f"/api/m/image2cad/uploads/{uid}/create", json={})
    assert r.status_code == 402 and "Building the model takes about 275 tokens" in r.json()["detail"]["message"]
    assert c.post(f"/api/m/image2cad/uploads/{uid}/roundtrip").status_code == 409  # no model yet
    _set_balance("cost@x.com", 300)
    r = c.post(f"/api/m/image2cad/uploads/{uid}/create", json={})
    assert r.status_code == 200, r.text
    pid = r.json()["project_id"]
    db = session_factory()()
    p = db.get(Project, pid)
    ws = workspace_for(p)
    assert p.name == "Test plate"  # AMI-24: named from the title block
    # the hand-off run finishes: the platform's run record carries its real cost, recorded once into the estimate
    from sqlalchemy import select

    from aicad.platform.models import AgentRun

    run = db.scalar(select(AgentRun).where(AgentRun.project_id == pid))
    assert run is not None and run.status == "running"
    assert c.get("/api/m/image2cad/estimate").json()["build"]["runs"] == 0      # still running: nothing recorded
    run.status, run.cost_usd, run.tokens = "ok", 3.1, 310
    db.commit()
    db.close()
    e = c.get("/api/m/image2cad/estimate").json()["build"]
    assert (e["tokens"], e["high"], e["runs"]) == (293, 310, 1)
    assert c.get("/api/m/image2cad/estimate").json()["build"]["runs"] == 1  # settled once
    # AMI-I1: a verified build of FX-DRW-1 (100 x 60 x 20 block) stands in for the agent's model
    write_model(ws / "out")
    rt = c.post(f"/api/m/image2cad/uploads/{uid}/roundtrip")
    assert rt.status_code == 200, rt.text
    res = rt.json()["roundtrip"]
    rows = {row["label"]: row for row in res["rows"]}
    assert rows["100"]["status"] == "match" and rows["60"]["status"] == "match"
    assert rows["M8x1.25"]["status"] == "skipped" and rows["4X Ø6.6 THRU"]["status"] == "missing"
    assert res["checked"] == res["matched"] + sum(1 for r in res["rows"] if r["status"] in ("missing", "count"))
    assert c.get("/api/m/image2cad/uploads").json()["items"][0]["roundtrip"]["checked"] == res["checked"]


def test_documentation_items_are_notes_not_questions() -> None:
    """AMI-15: approval status, tolerances and finish don't change the model, so they never block Create."""
    raw = vision.parse_block(VISION_ANSWER)
    assert raw is not None
    raw["missing"] = [{"what": "Approved status for manufacture"}, {"what": "Tolerances on all sizes"},
                      {"what": "Surface finish (Ra)"}, {"what": "Material"}, {"what": "Thickness", "why": "one view"},
                      {"what": "Hole positions"}]
    st = review.state(vision.to_read(raw), None)
    missing = [n["question"] for n in st["needs"] if n["kind"] == "missing"]
    assert missing == ["Missing: Thickness", "Missing: Hole positions"]
    assert [m["what"] for m in st["documentation"]] == ["Approved status for manufacture", "Tolerances on all sizes",
                                                        "Surface finish (Ra)", "Material"]
    for geo in ("Leg thickness", "Second hole diameter", "Keyway depth", "Overall width", "Fillet radii"):
        assert not review.is_documentation({"what": geo}), geo


def test_names_drawing_numbers_and_legend_tags() -> None:
    """AMI-24 / AMI-25: the project is named from the title, the drawing number stays out of the name, and colour
    legend tags are stripped from what a dimension measures."""
    assert review.suggested_name({"part": "Stepped Shaft (FW-33A4AF21)"}, "shaft_drawing.png") == "Stepped Shaft"
    assert review.drawing_number({"part": "Stepped Shaft (FW-33A4AF21)"}) == "FW-33A4AF21"
    assert review.suggested_name({"title": {"TITLE": "Bracket", "DRAWING NO.": "B-100"}}, "x.pdf") == "Bracket"
    assert review.drawing_number({"title": {"TITLE": "Bracket", "DRAWING NO.": "B-100"}}) == "B-100"
    assert review.suggested_name({"title_text": "Pump cover", "part": "A cast cover"}, "scan.jpg") == "Pump cover"
    assert review.suggested_name({"part": "A round cast cover with four bolt holes and a spigot"}, "scan.jpg") == "scan"
    assert review.suggested_name({}, None) is None
    assert vision.clean_describes("overall length (red: INFERRED)") == "overall length"
    assert vision.clean_describes("shoulder diameter [blue = SPEC]") == "shoulder diameter"
    assert vision.clean_describes("keyway depth - green: REF") == "keyway depth"
    assert vision.clean_describes("red anodised flange width") == "red anodised flange width"
    raw = vision.parse_block(VISION_ANSWER)
    assert raw is not None
    raw.update(title="Stepped Shaft", drawing_no="FW-33A4AF21", projection="first",
               projection_evidence="ISO first-angle symbol")
    r = vision.to_read(raw)
    assert r["title_text"] == "Stepped Shaft" and r["projection"]["value"] == "first"
    rv = review.clean_review({"reference": {"dim": "d1", "value": 120, "unit": "mm"},
                              "answers": {"confirm_d2": {"choice": "keep"}, "kind_d2": {"choice": "diameter"},
                                          "unparsed_0": {"choice": "ignore"}, "unreadable_0": {"choice": "ignore"},
                                          "missing_0": {"choice": "not_needed"}}}, r)
    st = review.state(r, rv)
    p = review.handoff_prompt({"name": "shaft.png"}, r, st, rv)
    assert "Part name: Stepped Shaft (drawing number FW-33A4AF21: keep it out of the part name)" in p
    assert "Projection: first angle." in p
    s = review.handoff_summary({"name": "shaft.png"}, st, rv)
    assert s.startswith("Model from shaft.png: 2 confirmed values, reference 120 mm (overall length, Side view), "
                        "1 item not needed.")
    assert s.endswith("Values: 120, Ø12.") and "Rules" not in s


def test_roundtrip_compare_hand_cases(formwright_pdf: Path) -> None:
    """AMI-I1 against FX-DRW-1 (100 x 60 x 20 block, 4 x Ø8 through 10 from the edges, Ø6 x 10 blind): its Drawing
    Studio record is the measured side, the confirmed values below are written by hand."""
    from aicad.image2cad import roundtrip

    rec = json.loads((formwright_pdf.parent / "drawing.json").read_text(encoding="utf-8"))
    measured = roundtrip.sheet_values(rec)
    dims = [{"id": str(i), "label": t} for i, t in enumerate(
        ["100", "60", "20", "4X Ø8 THRU", "Ø6 DEEP 10", "55", "R5", "2X Ø8 THRU", "Ø6 DEEP 12", "Ø7"])]
    out = roundtrip.compare(dims, measured)
    st = {r["label"]: r["status"] for r in out["rows"]}
    assert st == {"100": "match", "60": "match", "20": "match", "4X Ø8 THRU": "match", "Ø6 DEEP 10": "match",
                  "55": "missing", "R5": "skipped", "2X Ø8 THRU": "count", "Ø6 DEEP 12": "missing", "Ø7": "missing"}
    assert (out["matched"], out["checked"], out["skipped"], out["ok"]) == (5, 9, 1, False)
    # inches: 3.937 in = 99.9998 mm (within the sheet's 0.01 mm), 0.315 in = 8.001 mm
    inch = roundtrip.compare([{"id": "a", "label": "3.937"}, {"id": "b", "label": "4X Ø.315 THRU"}], measured, "in")
    assert [r["status"] for r in inch["rows"]] == ["match", "match"] and inch["ok"]


def test_long_vision_texts_end_at_a_word() -> None:
    from aicad.image2cad.vision import _s

    t = "ISO projection symbol in the title block PROJECTION field: concentric circles on the left, truncated cone outline"
    assert _s(t, 200) == t
    out = _s(t, 80)
    assert len(out) <= 80 and out.endswith("…") and t.startswith(out[:-1]) and not out[:-1].endswith("concen")
