"""Library: Toolbox generators, STEP import, feature recognition, parametric rebuild (CHK-09), agent questions."""

from __future__ import annotations

import base64
import math
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_platform import app_client, signup  # noqa: F401  (fixture re-export)

from aicad import toolbox
from aicad.agent.session import extract_questions
from aicad.recognize import recognize


def _plate():
    from build123d import Align, Box, Cylinder, Pos

    part = Box(100, 60, 10, align=(Align.MIN, Align.MIN, Align.MIN))
    for x in (10, 90):
        for y in (10, 50):
            part -= Pos(x, y, 0) * Cylinder(3.3, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    for i in range(6):
        a = math.radians(60 * i)
        part -= Pos(50 + 15 * math.cos(a), 30 + 15 * math.sin(a), 4) * Cylinder(2, 6, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return part


def _plate_step() -> bytes:
    from build123d import export_step

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "plate.step"
        export_step(_plate(), str(p))
        return p.read_bytes()


def test_recognition_finds_stock_holes_and_patterns() -> None:
    rec = recognize(_plate())
    assert rec["stock"] == {"kind": "prismatic", "size": [100.0, 60.0, 10.0], "fill_ratio": pytest.approx(rec["stock"]["fill_ratio"])}
    kinds = {(p["kind"], p["d"], p["count"]) for p in rec["patterns"]}
    assert ("grid", 6.6, 4) in kinds and ("circular", 4.0, 6) in kinds
    circ = next(p for p in rec["patterns"] if p["kind"] == "circular")
    assert circ["pcd"] == pytest.approx(30.0, abs=1e-3)
    blind = [h for h in rec["holes"] if h["d"] == 4.0]
    assert all(not h["through"] and h["depth"] == pytest.approx(6.0) for h in blind)
    assert all(h["through"] for h in rec["holes"] if h["d"] == 6.6)


def test_every_toolbox_component_is_deterministic_and_matches_expected() -> None:
    from build123d import export_step

    from aicad.agent import runner

    for code in toolbox.COMPONENTS:
        shape, exp = toolbox.build(code)
        assert shape.is_valid, code
        bb = shape.bounding_box().size
        assert [bb.X, bb.Y, bb.Z] == pytest.approx(exp["bbox"], abs=0.01), code
        assert shape.volume == pytest.approx(exp["volume"], rel=1e-3), code
        assert len(shape.solids()) == exp["solids"], code
    with tempfile.TemporaryDirectory() as td:  # byte-identical STEP, also for assemblies on a warm process
        outs = []
        for i in range(2):
            p = Path(td) / f"{i}.step"
            export_step(toolbox.build("bearing", SERIES=6204)[0], str(p), timestamp=runner.STEP_TIMESTAMP)
            runner.normalize_step(p)
            outs.append(p.read_bytes())
        assert outs[0] == outs[1]


def test_toolbox_validation_and_matching() -> None:
    with pytest.raises(toolbox.ToolboxError):
        toolbox.build("hex_bolt", D=7, L=30)
    with pytest.raises(toolbox.ToolboxError):
        toolbox.build("spur_gear", M=2, Z=24, B=10, BORE=60)
    m = toolbox.match("I need an M10x50 hex bolt")
    assert m[0]["code"] == "hex_bolt" and m[0]["params"] == {"D": 10, "L": 50.0}
    assert toolbox.match("spur gear module 1.5 with 40 teeth")[0]["params"]["Z"] == 40
    assert toolbox.match("6205 bearing")[0]["params"] == {"SERIES": 6205}
    assert toolbox.match("electronics enclosure with a pocket and four bolt bosses") == []


def test_agent_questions_block_is_parsed_and_stripped() -> None:
    text = 'Two choices needed.\n```fw-questions\n[{"question": "Material?", "options": ["6061", "S355"], "default": "6061"}]\n```'
    clean, qs = extract_questions(text)
    assert clean == "Two choices needed."
    assert qs == [{"id": "q1", "question": "Material?", "options": ["6061", "S355"], "multi": False, "other": True, "default": "6061"}]
    clean, qs = extract_questions("Hi\n```fw-questions\nnot json\n```")
    assert clean == "Hi" and qs == []


def test_toolbox_insert_creates_verified_editable_model(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "tb@x.com")
    assert len(c.get("/api/toolbox").json()["items"]) == len(toolbox.COMPONENTS)
    pid = c.post("/api/projects", json={"name": "Bolt"}).json()["id"]
    r = c.post(f"/api/projects/{pid}/toolbox", json={"code": "hex_bolt", "params": {"D": 8, "L": 40}})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Hex bolt ISO 4017 M8×40" and r.json()["status_ok"]
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["ok"] and st["editable_params"] == {"D": 8, "L": 40.0}
    # parameter edit without AI regenerates through the same generator
    r = c.post(f"/api/projects/{pid}/params", json={"values": {"L": 60}})
    assert r.status_code == 200, r.text
    assert c.get(f"/api/projects/{pid}/files/status.json").json()["fingerprint"]["bbox"][2] == pytest.approx(60 + 5.3)
    bad = c.post(f"/api/projects/{pid}/toolbox", json={"code": "hex_bolt", "params": {"D": 7}})
    assert bad.status_code == 422


def test_step_import_recognition_and_parametric_draft(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "step@x.com")
    pid = c.post("/api/projects", json={"name": "Imported plate"}).json()["id"]
    assert c.post(f"/api/projects/{pid}/import-step", json={"filename": "x.step", "data_b64": base64.b64encode(b"hello").decode()}).status_code == 415
    data = _plate_step()
    r = c.post(f"/api/projects/{pid}/import-step", json={"filename": "plate.step", "data_b64": base64.b64encode(data).decode()})
    assert r.status_code == 200, r.text
    rec = r.json()["recognition"]
    assert any("2 × 2 grid" in line for line in rec["summary"])
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["imported"] and st["fingerprint"]["volume"] == pytest.approx(_plate().volume, rel=1e-6)
    assert c.get(f"/api/projects/{pid}/recognition").json()["stock"]["kind"] == "prismatic"
    # manual feature on the imported (history-less) body
    top = {"point": [5, 5, 10], "normal": [0, 0, 1]}
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": {"op": "hole", "name": "Extra hole", "point": [30, 30, 10], "normal": [0, 0, 1], "d": 5, "depth": None}})
    assert r.status_code == 200, r.text
    _ = top
    # deterministic parametric draft, verified against the original by CHK-09
    r = c.post(f"/api/projects/{pid}/recognition/rebuild", json={"mode": "draft"})
    assert r.status_code == 200, r.text
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    chk9 = next(x for x in st["checks"] if x["id"] == "CHK-09")
    assert chk9["passed"] and chk9["detail"]["rel_err"] < 1e-5  # base vs original; manual hole kept on top
    assert st["manual_features"] == 1
    assert {"STOCK_X", "STOCK_Y", "STOCK_Z", "HOLE1_D", "HOLE2_D"} <= set(st["editable_params"])
    prompt = c.post(f"/api/projects/{pid}/recognition/rebuild", json={"mode": "prompt"}).json()["prompt"]
    assert "REFERENCE_STEP" in prompt and "pitch circle" in prompt


@pytest.mark.parametrize("clockwise", [False, True])
def test_sketch_boss_always_extrudes_out_of_the_face(clockwise: bool) -> None:
    from aicad import fw

    part, _ = toolbox.build("flange")
    pts = [(11, -3), (33, -3), (33, 11), (11, 11)]
    if clockwise:
        pts = pts[::-1]
    segs = [{"type": "line", "a": pts[i], "b": pts[(i + 1) % 4]} for i in range(4)]
    f = {"op": "sketch", "plane": {"origin": [0, 0, 16], "normal": [0, 0, 1], "x_dir": [1, 0, 0]},
         "profiles": [{"kind": "loop", "segs": segs}], "distance": 10, "mode": "add"}
    r = fw._op(part, f, 200)
    assert r.bounding_box().max.Z == pytest.approx(26)
    assert r.volume - part.volume == pytest.approx(22 * 14 * 10)
