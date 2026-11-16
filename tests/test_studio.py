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


def test_shell_mirror_and_circular_pattern(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "ops@x.com")
    box = ("from build123d import *\nfrom aicad import fw\nL = 40.0\nPARAMS = dict(L=L)\n"
           "result = fw.feature('Block', Box(L, 30, 20, align=(Align.CENTER, Align.CENTER, Align.MIN)))\n"
           "EXPECTED = {'bbox': [L, 30, 20], 'volume': L * 30 * 20, 'solids': 1}\n")
    pid, _ = _project_with_model(c, box)
    shell = {"op": "shell", "name": "Shell", "faces": [{"point": [0, 0, 20], "normal": [0, 0, 1]}], "t": 2}
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": shell}).status_code == 200
    v = c.get(f"/api/projects/{pid}/files/status.json").json()["fingerprint"]["volume"]
    assert v == pytest.approx(40 * 30 * 20 - 36 * 26 * 18, rel=1e-3)
    sid = c.get(f"/api/projects/{pid}/manual").json()["features"][0]["id"]
    assert c.delete(f"/api/projects/{pid}/manual/{sid}").status_code == 200
    pat = {"op": "hole", "name": "Bolt circle", "point": [10, 0, 20], "normal": [0, 0, 1], "d": 3,
           "count": 6, "pattern": "circular", "center": [0, 0, 20]}
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": pat}).status_code == 200
    v2 = c.get(f"/api/projects/{pid}/files/status.json").json()["fingerprint"]["volume"]
    assert v2 == pytest.approx(40 * 30 * 20 - 6 * math.pi * 1.5 ** 2 * 20, rel=1e-6)
    mir = {"op": "mirror", "name": "Mirror", "plane": {"origin": [20, 0, 0], "normal": [1, 0, 0]}}
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": mir}).status_code == 200
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["fingerprint"]["bbox"][0] == pytest.approx(80, abs=1e-6) and st["ok"]


def test_sketch_feature_with_hole_and_arc(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "sketch@x.com")
    box = ("from build123d import *\nfrom aicad import fw\nL = 60.0\nPARAMS = dict(L=L)\n"
           "result = fw.feature('Block', Box(L, 40, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)))\n"
           "EXPECTED = {'bbox': [L, 40, 10], 'volume': L * 40 * 10, 'solids': 1}\n")
    pid, _ = _project_with_model(c, box)
    # 20 x 10 rectangle with a semicircular end (R5) and a Ø4 hole inside, extruded 5 mm on the top face
    loop = {"kind": "loop", "segs": [
        {"type": "line", "a": [-10, -5], "b": [10, -5]},
        {"type": "arc", "a": [10, -5], "m": [15, 0], "b": [10, 5]},
        {"type": "line", "a": [10, 5], "b": [-10, 5]},
        {"type": "line", "a": [-10, 5], "b": [-10, -5]}]}
    hole = {"kind": "circle", "cx": 0, "cy": 0, "r": 2}
    feat = {"op": "sketch", "name": "Boss sketch", "distance": 5, "mode": "add",
            "plane": {"origin": [0, 0, 10], "normal": [0, 0, 1], "x_dir": [1, 0, 0]},
            "profiles": [loop, hole], "editor": {"points": [], "entities": [], "constraints": []}}
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": feat})
    assert r.status_code == 200, r.text
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    area = 20 * 10 + math.pi * 25 / 2 - math.pi * 4
    assert st["ok"] and st["fingerprint"]["volume"] == pytest.approx(60 * 40 * 10 + area * 5, rel=1e-6)
    assert st["fingerprint"]["bbox"][2] == pytest.approx(15)
    saved = c.get(f"/api/projects/{pid}/manual").json()["features"][0]
    assert saved["editor"] == {"points": [], "entities": [], "constraints": []}


# ----------------------------------------------------------------------------- modelling from scratch (DS-024)

TOP = {"origin": [0, 0, 0], "normal": [0, 0, 1], "x_dir": [1, 0, 0]}
FRONT = {"origin": [0, 0, 0], "normal": [0, -1, 0], "x_dir": [1, 0, 0]}


def _rect(x0: float, y0: float, x1: float, y1: float) -> dict:
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return {"kind": "loop", "segs": [{"type": "line", "a": list(pts[i]), "b": list(pts[(i + 1) % 4])} for i in range(4)]}


def test_part_modelled_from_scratch_with_pattern(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "scratch@x.com")
    pid = c.post("/api/projects", json={"name": "Hand flange"}).json()["id"]
    # a cut cannot start a part; the project stays empty
    cut0 = {"op": "sketch", "plane": TOP, "profiles": [{"kind": "circle", "cx": 0, "cy": 0, "r": 5}], "distance": 5, "mode": "cut"}
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": cut0})
    assert r.status_code == 422 and "start the part with a boss" in r.json()["detail"]
    assert c.get(f"/api/projects/{pid}/manual").json()["features"] == []
    # base boss on the Top plane, mid-plane: disc R50 x 10 centred on Z=0
    base = {"op": "sketch", "name": "Base", "plane": TOP, "profiles": [{"kind": "circle", "cx": 0, "cy": 0, "r": 50}],
            "distance": 10, "mode": "add", "end": "mid"}
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": base}).status_code == 200
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["ok"] and st["fingerprint"]["volume"] == pytest.approx(math.pi * 2500 * 10, rel=1e-9)
    assert st["fingerprint"]["bbox"] == pytest.approx([100, 100, 10], abs=1e-6)
    # through-all cut, then a circular pattern of it (6 holes)
    top = {"origin": [0, 0, 5], "normal": [0, 0, 1], "x_dir": [1, 0, 0]}
    hole = {"op": "sketch", "name": "Bolt hole", "plane": top, "profiles": [{"kind": "circle", "cx": 35, "cy": 0, "r": 4}],
            "mode": "cut", "end": "through"}
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": hole})
    assert r.status_code == 200, r.text
    hid = r.json()["features"][-1]["id"]
    pat = {"op": "pattern", "name": "Bolt circle", "source": [hid], "kind": "circular", "count": 6,
           "axis": {"origin": [0, 0, 0], "dir": [0, 0, 1]}}
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": pat}).status_code == 200
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["fingerprint"]["volume"] == pytest.approx(math.pi * 2500 * 10 - 6 * math.pi * 16 * 10, rel=1e-9)
    assert [f["name"] for f in st["features"]][-3:] == ["Base", "Bolt hole", "Bolt circle"]
    # suppressing the source hole makes the pattern fail cleanly and restores the model
    feats = c.get(f"/api/projects/{pid}/manual").json()["features"]
    r = c.patch(f"/api/projects/{pid}/manual/{feats[1]['id']}", json={"feature": {"suppressed": True}})
    assert r.status_code == 422 and "patterned feature" in r.json()["detail"]
    # invalid inputs
    bad = [{**pat, "count": 1}, {**pat, "axis": {"origin": [0, 0, 0], "dir": [0, 0, 0]}},
           {**base, "end": "through"}, {**base, "plane": {**TOP, "x_dir": [0, 0, 1]}}]
    for b in bad:
        assert c.post(f"/api/projects/{pid}/manual", json={"feature": b}).status_code == 422


def test_revolved_part_from_scratch(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "revolve@x.com")
    pid = c.post("/api/projects", json={"name": "Bushing"}).json()["id"]
    # tube r 10..20, h 30 revolved about the sketch Y axis of the Front plane (world Z), plus a 90 degree segment
    rev = {"op": "revolve", "name": "Bushing", "plane": FRONT, "profiles": [_rect(10, 0, 20, 30)],
           "axis": {"a": [0, 0], "b": [0, 1]}, "angle": 360, "mode": "add"}
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": rev}).status_code == 200
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["ok"] and st["fingerprint"]["volume"] == pytest.approx(math.pi * (400 - 100) * 30, rel=1e-9)
    assert st["fingerprint"]["bbox"] == pytest.approx([40, 40, 30], abs=1e-6)
    groove = {"op": "revolve", "name": "Groove", "plane": FRONT, "profiles": [_rect(18, 10, 20, 14)],
              "axis": {"a": [0, 0], "b": [0, 1]}, "angle": 360, "mode": "cut"}
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": groove}).status_code == 200
    v = c.get(f"/api/projects/{pid}/files/status.json").json()["fingerprint"]["volume"]
    assert v == pytest.approx(math.pi * 300 * 30 - math.pi * (400 - 324) * 4, rel=1e-9)
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": {**rev, "axis": {"a": [0, 0], "b": [0, 0]}}})
    assert r.status_code == 422 and "centerline" in r.json()["detail"]


# ----------------------------------------------------------------------------- DS-026 mirror, planes, draft, rib, sweep, loft

TOP10 = {"origin": [0, 0, 10], "normal": [0, 0, 1], "x_dir": [1, 0, 0]}


def _block(c: TestClient, email: str, name: str) -> str:
    """Hand-modelled 60 x 40 x 10 block on the Top plane (x -30..30, y -20..20, z 0..10)."""
    signup(c, email)
    pid = c.post("/api/projects", json={"name": name}).json()["id"]
    base = {"op": "sketch", "name": "Base", "plane": TOP, "profiles": [_rect(-30, -20, 30, 20)], "distance": 10, "mode": "add"}
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": base}).status_code == 200
    return pid


def _vol(c: TestClient, pid: str) -> float:
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["ok"], st
    return st["fingerprint"]["volume"]


def test_mirror_features_about_a_principal_plane(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    pid = _block(c, "mirrorfeat@x.com", "Mirror features")
    ids = []
    for f in ({"op": "sketch", "name": "Hole", "plane": TOP10, "profiles": [{"kind": "circle", "cx": 15, "cy": 5, "r": 3}],
               "mode": "cut", "end": "through"},
              {"op": "sketch", "name": "Lug", "plane": TOP10, "profiles": [_rect(18, -15, 26, -5)], "distance": 5, "mode": "add"},
              {"op": "hole", "name": "Pin hole", "point": [20, 12, 10], "normal": [0, 0, 1], "d": 4, "depth": 6}):
        r = c.post(f"/api/projects/{pid}/manual", json={"feature": f})
        assert r.status_code == 200, r.text
        ids.append(r.json()["features"][-1]["id"])
    one_side = -math.pi * 9 * 10 + 8 * 10 * 5 - math.pi * 4 * 6
    assert _vol(c, pid) == pytest.approx(24000 + one_side, rel=1e-9)
    mir = {"op": "mirror", "name": "Mirror1", "source": ids, "plane": {"origin": [0, 0, 0], "normal": [1, 0, 0]}}
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": mir})
    assert r.status_code == 200, r.text
    assert _vol(c, pid) == pytest.approx(24000 + 2 * one_side, rel=1e-9)
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["fingerprint"]["bbox"] == pytest.approx([60, 40, 15], abs=1e-6)
    feats = c.get(f"/api/projects/{pid}/manual").json()["features"]
    assert feats[-1]["source"] == ids
    # editing it into a body mirror drops the feature list
    mid = feats[-1]["id"]
    r = c.patch(f"/api/projects/{pid}/manual/{mid}", json={"feature": {"source": None, "plane": {"origin": [30, 0, 0], "normal": [1, 0, 0]}}})
    assert r.status_code == 200, r.text
    assert "source" not in c.get(f"/api/projects/{pid}/manual").json()["features"][-1]
    assert _vol(c, pid) == pytest.approx(2 * (24000 + one_side), rel=1e-9)
    c.patch(f"/api/projects/{pid}/manual/{mid}", json={"feature": {"source": ids[:1], "plane": {"origin": [0, 0, 0], "normal": [1, 0, 0]}}})
    assert _vol(c, pid) == pytest.approx(24000 + one_side - math.pi * 9 * 10, rel=1e-9)
    # suppressing a mirrored feature fails cleanly and restores the model; non-tool features can't be mirrored
    r = c.patch(f"/api/projects/{pid}/manual/{ids[0]}", json={"feature": {"suppressed": True}})
    assert r.status_code == 422 and "mirrored feature" in r.json()["detail"]
    ch = {"op": "chamfer", "name": "Edge break", "edges": [[30, 0, 10]], "d": 1}
    chid = c.post(f"/api/projects/{pid}/manual", json={"feature": ch}).json()["features"][-1]["id"]
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": {**mir, "source": [chid]}})
    assert r.status_code == 422 and "can't be mirrored" in r.json()["detail"]
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": {**mir, "plane": {"origin": [0, 0, 0], "normal": [0, 0, 0]}}})
    assert r.status_code == 422


def test_suppress_design_agent_features(app_client: TestClient) -> None:  # noqa: F811
    """Features the agent recorded with fw.feature can be suppressed and restored from the tree, without AI."""
    c = app_client
    signup(c, "suppress@x.com")
    pid, ws = _project_with_model(c, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    v0 = st["fingerprint"]["volume"]
    chain = {f["name"]: f["chain"] for f in st["features"]}
    assert chain == {"Base plate": False, "Top chamfer": True, "Mounting holes (4x)": True, "Centre pocket": True}
    url = f"/api/projects/{pid}/design-features/suppress"
    # the base feature can't be suppressed
    r = c.post(url, json={"name": "Base plate", "suppressed": True})
    assert r.status_code == 422 and "base feature" in r.json()["detail"]
    # suppress the holes: their volume comes back, the rest of the design rebuilds on the earlier state
    r = c.post(url, json={"name": "Mounting holes (4x)", "suppressed": True})
    assert r.status_code == 200, r.text
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    holes = 4 * math.pi * 3.3 ** 2 * 10
    assert st["ok"] and st["fingerprint"]["volume"] == pytest.approx(v0 + holes, rel=1e-9)
    assert next(f for f in st["features"] if f["name"] == "Mounting holes (4x)")["suppressed"] is True
    assert "SUPPRESSED_FEATURES = ['Mounting holes (4x)']" in (ws / "model.py").read_text(encoding="utf-8")
    chk5 = next(x for x in st["checks"] if x["id"] == "CHK-05")
    assert chk5["gating"] is False and "suppressed" in chk5["name"]
    # suppress the chamfer too, then restore both
    assert c.post(url, json={"name": "Top chamfer", "suppressed": True}).status_code == 200
    v2 = c.get(f"/api/projects/{pid}/files/status.json").json()["fingerprint"]["volume"]
    assert v2 == pytest.approx(v0 + holes + (120 + 80) * 1.0 - 4 / 3, rel=1e-9)
    for n in ("Top chamfer", "Mounting holes (4x)"):
        assert c.post(url, json={"name": n, "suppressed": False}).status_code == 200
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["fingerprint"]["volume"] == pytest.approx(v0, rel=1e-12)
    assert "SUPPRESSED_FEATURES" not in (ws / "model.py").read_text(encoding="utf-8")
    assert c.post(url, json={"name": "Nope", "suppressed": True}).status_code == 404


def test_delete_step_source_edit_rules() -> None:
    from aicad.design_edit import DesignEditError, delete_step

    src = (DEMO / "mounting_plate.py").read_text(encoding="utf-8")
    out = delete_step(src, "Mounting holes (4x)")
    assert 'fw.feature("Mounting holes (4x)"' not in out and "for sx in" not in out
    assert 'fw.feature("Top chamfer"' in out and 'fw.feature("Centre pocket"' in out
    compile(out, "model.py", "exec")
    with pytest.raises(DesignEditError, match="base feature"):
        delete_step(src, "Base plate")
    with pytest.raises(DesignEditError, match="isn't a separate step"):
        delete_step(src, "Nope")
    entangled = (
        "from build123d import *\nfrom aicad import fw\n"
        "part = fw.feature('Block', Box(10, 10, 10))\n"
        "r = 2\npart = fw.feature('Hole', part - Cylinder(r, 20))\n"
        "part = fw.feature('Boss', part + Pos(0, 0, 5) * Cylinder(r + 1, 4))\nresult = part\n")
    with pytest.raises(DesignEditError, match=r"later features use values defined in “Hole” \(r\)"):
        delete_step(entangled, "Hole")
    no_boss = delete_step(entangled, "Boss")  # the last step only reads earlier values, so it can go
    assert "'Boss'" not in no_boss and "'Hole'" in no_boss and "result = part" in no_boss


def test_delete_design_feature_without_ai(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "delete@x.com")
    pid, ws = _project_with_model(c, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))
    v0 = c.get(f"/api/projects/{pid}/files/status.json").json()["fingerprint"]["volume"]
    url = f"/api/projects/{pid}/design-features/delete"
    r = c.post(url, json={"name": "Base plate"})
    assert r.status_code == 422 and "base feature" in r.json()["detail"]
    r = c.post(url, json={"name": "Mounting holes (4x)"})
    assert r.status_code == 200, r.text
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["ok"] and st["fingerprint"]["volume"] == pytest.approx(v0 + 4 * math.pi * 3.3 ** 2 * 10, rel=1e-9)
    assert [f["name"] for f in st["features"]] == ["Base plate", "Top chamfer", "Centre pocket"]
    src = (ws / "model.py").read_text(encoding="utf-8")
    assert "Mounting holes (4x)" not in src.split("SUPPRESSED")[0].split("# --- Formwright suppressed")[0]
    assert "DELETED_FEATURES = ['Mounting holes (4x)']" in src and "SUPPRESSED_FEATURES" not in src
    chk5 = next(x for x in st["checks"] if x["id"] == "CHK-05")
    assert chk5["gating"] is False and "deleted" in chk5["name"]


def test_reference_plane_features(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    pid = _block(c, "planes@x.com", "Planes")
    # Top plane turned 90 degrees about its X axis is a Front-facing plane (normal -Y); offset -10 puts it at y = +10
    pl = {"op": "plane", "name": "Plane1", "base": TOP, "base_name": "Top Plane", "angle": 90, "rot_axis": "x", "offset": -10}
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": pl})
    assert r.status_code == 200, r.text
    plane = r.json()["features"][-1]
    assert plane["plane"] == {"origin": [0, 10, 0], "normal": [0, -1, 0], "x_dir": [1, 0, 0]}
    assert _vol(c, pid) == pytest.approx(24000, rel=1e-12)  # reference geometry never changes the solid
    # a through-all cut sketched on it (stored placement is stale on purpose: the plane wins)
    cut = {"op": "sketch", "name": "Cross hole", "plane": TOP, "plane_ref": plane["id"], "mode": "cut", "end": "through",
           "profiles": [{"kind": "circle", "cx": 0, "cy": 5, "r": 3}]}
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": cut})
    assert r.status_code == 200, r.text
    assert r.json()["features"][-1]["plane"] == plane["plane"]
    assert _vol(c, pid) == pytest.approx(24000 - math.pi * 9 * 10, rel=1e-9)  # y = 10..20
    # moving the plane moves the attached sketch
    assert c.patch(f"/api/projects/{pid}/manual/{plane['id']}", json={"feature": {"offset": 0}}).status_code == 200
    feats = c.get(f"/api/projects/{pid}/manual").json()["features"]
    assert feats[-1]["plane"]["origin"] == [0, 0, 0]
    assert _vol(c, pid) == pytest.approx(24000 - math.pi * 9 * 20, rel=1e-9)  # y = 0..20
    # order and suppression of the plane don't matter; deleting it leaves the sketch where it was
    ids = [f["id"] for f in feats]
    assert c.post(f"/api/projects/{pid}/manual/reorder", json={"ids": [ids[0], ids[2], ids[1]]}).status_code == 200
    assert _vol(c, pid) == pytest.approx(24000 - math.pi * 9 * 20, rel=1e-9)
    assert c.patch(f"/api/projects/{pid}/manual/{plane['id']}", json={"feature": {"suppressed": True}}).status_code == 200
    assert _vol(c, pid) == pytest.approx(24000 - math.pi * 9 * 20, rel=1e-9)
    assert c.delete(f"/api/projects/{pid}/manual/{plane['id']}").status_code == 200
    left = c.get(f"/api/projects/{pid}/manual").json()["features"]
    assert [f["op"] for f in left] == ["sketch", "sketch"] and "plane_ref" not in left[-1]
    assert left[-1]["plane"]["origin"] == [0, 0, 0]
    assert _vol(c, pid) == pytest.approx(24000 - math.pi * 9 * 20, rel=1e-9)
    for bad in ({**pl, "base": {**TOP, "normal": [0, 0, 0]}}, {**pl, "angle": 200}):
        assert c.post(f"/api/projects/{pid}/manual", json={"feature": bad}).status_code == 422


def test_reference_plane_before_any_solid(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "planefirst@x.com")
    pid = c.post("/api/projects", json={"name": "Plane first"}).json()["id"]
    pl = {"op": "plane", "name": "Plane1", "base": TOP, "offset": 5}
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": pl})
    assert r.status_code == 200 and r.json()["revision"] is None, r.text
    pid_plane = r.json()["features"][0]["id"]
    boss = {"op": "sketch", "name": "Boss", "plane": TOP, "plane_ref": pid_plane, "mode": "add", "distance": 10,
            "profiles": [_rect(-10, -5, 10, 5)]}
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": boss})
    assert r.status_code == 200, r.text
    assert _vol(c, pid) == pytest.approx(20 * 10 * 10, rel=1e-12)
    topo = c.get(f"/api/projects/{pid}/files/topo.json").json()
    assert topo["bbox"] == pytest.approx([-10, -5, 5, 10, 5, 15], abs=1e-9)
