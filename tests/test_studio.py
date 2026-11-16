"""Design Studio: topology export, mass properties, features, manual features, compare, settings, persistence."""

from __future__ import annotations

import base64
import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_platform import _project_with_model, app_client, signup  # noqa: F401  (fixture re-export)

from aicad.topo import export_topology, mass_properties

DEMO = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo"


def test_topology_is_exact_brep() -> None:
    from build123d import Align, Box, Cylinder, Pos

    part = Box(40, 20, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)) - Pos(0, 0, 5) * Cylinder(3, 12)
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        t = export_topology(part, Path(td) / "t.json")
    types = sorted(f["type"] for f in t["faces"])
    assert types.count("plane") == 6 and types.count("cylinder") == 1
    circles = [e for e in t["edges"] if e["type"] == "circle"]
    assert len(circles) == 2 and all(abs(e["radius"] - 3.0) < 1e-9 for e in circles)
    assert all(abs(e["length"] - 2 * math.pi * 3) < 1e-6 for e in circles)
    lines = [e for e in t["edges"] if e["type"] == "line"]
    assert sorted({round(e["length"], 6) for e in lines}) == [10.0, 20.0, 40.0]
    assert len(t["vertices"]) >= 8 and t["bbox"] == [-20.0, -10.0, 0.0, 20.0, 10.0, 10.0]
    hole = next(f for f in t["faces"] if f["type"] == "cylinder")
    assert abs(hole["radius"] - 3.0) < 1e-9 and abs(abs(hole["axis"][2]) - 1) < 1e-9
    assert all(len(f["idx"]) % 3 == 0 and f["edges"] for f in t["faces"])


def test_mass_properties_match_analytic_box() -> None:
    from build123d import Box

    a, b, c = 40.0, 20.0, 10.0
    m = mass_properties(Box(a, b, c))
    assert m["volume_mm3"] == pytest.approx(a * b * c)
    assert m["area_mm2"] == pytest.approx(2 * (a * b + b * c + a * c))
    assert m["com_mm"] == pytest.approx([0, 0, 0], abs=1e-9)
    ixx = a * b * c * (b * b + c * c) / 12  # density 1
    assert m["inertia_com_mm5"][0][0] == pytest.approx(ixx, rel=1e-6)
    assert m["inertia_com_mm5"][2][2] == pytest.approx(a * b * c * (a * a + b * b) / 12, rel=1e-6)


def test_runner_exports_features_meta_mass_and_topology(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "topo@x.com")
    pid, _ws = _project_with_model(c, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert [f["name"] for f in st["features"]] == ["Base plate", "Top chamfer", "Mounting holes (4x)", "Centre pocket"]
    assert st["param_meta"]["L"] == {"min": 60, "max": 400, "step": 1, "unit": "mm", "group": "Plate", "label": "Length"}
    assert st["mass"]["volume_mm3"] == pytest.approx(st["fingerprint"]["volume"], rel=1e-9)
    topo = c.get(f"/api/projects/{pid}/files/topo.json").json()
    feats = {f.get("feature") for f in topo["faces"]}
    assert {"Mounting holes (4x)", "Centre pocket", "Base plate"} <= feats
    holes = [f for f in topo["faces"] if f["type"] == "cylinder" and abs(f["radius"] - 3.3) < 1e-9]
    assert len(holes) == 4 and all(f["feature"] == "Mounting holes (4x)" for f in holes)
    assert c.get(f"/api/projects/{pid}/files/part.3mf").status_code == 200
    r = c.post(f"/api/projects/{pid}/params", json={"values": {"L": 500}})
    assert r.status_code == 422 and "between 60 and 400" in r.json()["detail"]


def test_manual_feature_lifecycle(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "manual@x.com")
    pid, ws = _project_with_model(c, (DEMO / "l_bracket.py").read_text(encoding="utf-8"))
    v0 = c.get(f"/api/projects/{pid}/files/status.json").json()["fingerprint"]["volume"]
    # hole through the horizontal leg, picked at a point on its top face (z = T = 5)
    hole = {"op": "hole", "name": "Extra hole", "point": [30, 25, 5], "normal": [0, 0, 1], "d": 6}
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": hole})
    assert r.status_code == 200, r.text
    fid = r.json()["features"][0]["id"]
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["ok"] and st["manual_features"] == 1
    assert st["fingerprint"]["volume"] == pytest.approx(v0 - math.pi * 9 * 5, rel=1e-6)
    chk5 = next(x for x in st["checks"] if x["id"] == "CHK-05")
    assert chk5["gating"] is False and "manual" in chk5["name"]
    assert "Extra hole" in [f["name"] for f in st["features"]]
    # outer vertical edge of the horizontal leg end: fillet it
    fil = {"op": "fillet", "name": "Edge round", "edges": [[60, 25, 0]], "r": 2}
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": fil}).status_code == 200
    # extrude a boss on the top face, then cut a pocket
    boss = {"op": "extrude", "name": "Boss", "plane": {"origin": [45, 25, 5], "normal": [0, 0, 1]},
            "sketch": {"kind": "circle", "r": 4}, "distance": 3, "mode": "add"}
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": boss}).status_code == 200
    v_boss = c.get(f"/api/projects/{pid}/files/status.json").json()["fingerprint"]["volume"]
    feats = c.get(f"/api/projects/{pid}/manual").json()["features"]
    assert [f["name"] for f in feats] == ["Extra hole", "Edge round", "Boss"]
    # suppress the boss -> volume drops by the boss volume
    bid = feats[2]["id"]
    assert c.patch(f"/api/projects/{pid}/manual/{bid}", json={"feature": {"suppressed": True}}).status_code == 200
    v_sup = c.get(f"/api/projects/{pid}/files/status.json").json()["fingerprint"]["volume"]
    assert v_boss - v_sup == pytest.approx(math.pi * 16 * 3, rel=1e-4)
    # edit the hole diameter
    assert c.patch(f"/api/projects/{pid}/manual/{fid}", json={"feature": {"d": 8}}).status_code == 200
    # an impossible feature is rejected and the model is restored
    bad = {"op": "fillet", "edges": [[999, 999, 999]], "r": 1}
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": bad})
    assert r.status_code == 422 and "restored" in r.json()["detail"]
    assert len(c.get(f"/api/projects/{pid}/manual").json()["features"]) == 3
    # reorder + delete
    ids = [f["id"] for f in c.get(f"/api/projects/{pid}/manual").json()["features"]]
    assert c.post(f"/api/projects/{pid}/manual/reorder", json={"ids": ids[::-1]}).status_code == 200
    assert c.delete(f"/api/projects/{pid}/manual/{fid}").status_code == 200
    src = (ws / "model.py").read_text(encoding="utf-8")
    assert src.count("MANUAL_FEATURES =") == 1 and "Extra hole" not in src
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": {"op": "explode"}}).status_code == 422


def test_compare_revisions_reports_added_and_removed(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "cmp@x.com")
    pid, _ws = _project_with_model(c, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))
    # revision 1 = after a parameter edit (snapshot includes STEP)
    assert c.post(f"/api/projects/{pid}/params", json={"values": {"L": 130}}).status_code == 200
    assert c.post(f"/api/projects/{pid}/params", json={"values": {"PD": 6}}).status_code == 200
    revs = [r["n"] for r in c.get(f"/api/projects/{pid}/revisions").json()["items"]]
    r = c.post(f"/api/projects/{pid}/compare", json={"base": min(revs)})
    assert r.status_code == 200, r.text
    d = r.json()
    # deeper pocket removes 40x30 (minus rounded corners) x 2 mm
    assert d["removed_mm3"] == pytest.approx((40 * 30 - (4 - math.pi) * 9) * 2, rel=1e-4)
    assert d["added_mm3"] == pytest.approx(0, abs=1e-3)
    assert d["params_changed"] == {"PD": {"from": 4.0, "to": 6.0}}
    assert c.get(d["removed_url"]).json()["faces"]
    assert c.get(f"/api/projects/{pid}/revisions/{min(revs)}/files/topo.json").status_code == 200


def test_settings_materials_estimate(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "mat@x.com")
    pid, _ = _project_with_model(c, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))
    mats = c.get("/api/materials").json()
    assert any(m["code"] == "al_6061" and m["density_g_cm3"] == 2.70 for m in mats["items"])
    assert "Verify" in mats["source_note"]
    assert c.get(f"/api/projects/{pid}/settings").json()["material_guess"] == "al_6061"
    assert c.patch(f"/api/projects/{pid}/settings", json={"material": "ss_304"}).json()["material"] == "ss_304"
    assert c.patch(f"/api/projects/{pid}/settings", json={"material": "unobtanium"}).status_code == 422
    assert c.get(f"/api/projects/{pid}/estimate").json()["basis"] == "default"


def test_attachment_validation(app_client: TestClient) -> None:  # noqa: F811
    from aicad.platform.routers.projects import Attachment, save_attachments

    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 100).decode()
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        saved = save_attachments(Path(td), [Attachment(name="a.png", mime="image/png", data_b64=png)])
        assert saved[0].startswith("refs/") and (Path(td) / saved[0]).is_file()
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            save_attachments(Path(td), [Attachment(name="x.png", mime="image/png",
                                                   data_b64=base64.b64encode(b"MZ evil").decode())])
        with pytest.raises(HTTPException):
            save_attachments(Path(td), [Attachment(name="x.svg", mime="image/svg+xml", data_b64=png)])


def test_chat_history_and_session_persist(tmp_path: Path) -> None:
    from aicad.agent.session import AgentSession

    s = AgentSession(tmp_path)
    s.publish({"type": "user", "text": "make a plate"})
    s.publish({"type": "busy", "value": True})
    s.publish({"type": "text", "text": "done"})
    s.session_id = "abc"
    s._persist_session()
    s2 = AgentSession(tmp_path)
    assert [e["type"] for e in s2.history] == ["user", "text"] and s2.session_id == "abc"
    assert s2.options().resume == "abc"
    import asyncio

    asyncio.run(s2.reset())
    s3 = AgentSession(tmp_path)
    assert s3.history == [] and s3.session_id is None
    assert json.loads(json.dumps(s3.history)) == []
