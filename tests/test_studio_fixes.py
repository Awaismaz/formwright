"""Design Studio audit fixes (docs/reports/audit/studio.md): one-edge picks (STU-01), picks that follow dimension
changes and the rebuild-failure assistant (STU-03 / IDEA 1), worker reply correlation (STU-04), plain errors
(STU-05), source view (STU-06), undo information (STU-10) and the fastener-aware Hole Wizard (STU-08 / IDEA 3)."""

from __future__ import annotations

import asyncio
import math
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_platform import _project_with_model, admin, app_client, signup  # noqa: F401  (fixture re-export)

DEMO = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo"
CORNER_R3 = (9 - 9 * math.pi / 4) * 10  # material a R3 round removes along a 10 mm long 90° edge: (R² - πR²/4)·h

BLOCK = textwrap.dedent('''\
    from build123d import *
    from aicad import fw

    NAME = "Block"
    MATERIAL = "Aluminium 6061-T6"
    L = 50.0
    W = 20.0
    T = 10.0
    PARAMS = dict(L=L, W=W, T=T)
    PARAM_META = {"L": {"min": 10, "max": 200, "unit": "mm", "label": "Length"},
                  "T": {"min": 1, "max": 50, "unit": "mm", "label": "Thickness"}}
    result = fw.feature("Block", Box(L, W, T, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    EXPECTED = {"bbox": [L, W, T], "volume": L * W * T, "solids": 1}
''')
VERTICAL = {"kind": "line", "dir": [0, 0, 1]}


def _st(c: TestClient, pid: str) -> dict:
    return c.get(f"/api/projects/{pid}/files/status.json").json()


def test_one_picked_edge_fillets_only_that_edge() -> None:
    """STU-01: the audit's case, 50 x 20 x 10 box, R3 on one vertical edge = 10000 - (9 - 9π/4)·10 = 9980.6858."""
    from build123d import Align, Box

    from aicad import fw

    box = Box(50, 20, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    one = {"id": "f", "op": "fillet", "name": "F", "r": 3}
    fw.reset()
    v = fw.apply_manual(box, [{**one, "edges": [[-25, -10, 5]], "edge_refs": [VERTICAL]}]).volume
    assert v == pytest.approx(9980.6858, abs=1e-4) and v == pytest.approx(10000 - CORNER_R3, rel=1e-12)
    # the old app sent the edge's end vertex; with the picked edge's kind and direction it is still one edge
    fw.reset()
    assert fw.apply_manual(box, [{**one, "edges": [[-25, -10, 0]], "edge_refs": [VERTICAL]}]).volume == pytest.approx(v)
    # edges_near: a point on an edge's middle selects that edge only, a corner still selects all edges meeting there
    assert len(fw.edges_near(box, [(-25, -10, 5)])) == 1
    assert len(fw.edges_near(box, [(-25, -10, 0)])) == 3


def test_manual_fillet_survives_a_length_change(app_client: TestClient) -> None:  # noqa: F811
    """STU-03: a fillet picked by hand follows the body when Length changes (no 422, no repick)."""
    c = app_client
    signup(c, "follow@x.com")
    pid, _ws = _project_with_model(c, BLOCK)
    fil = {"op": "fillet", "name": "Corner round", "edges": [[25, 10, 5]], "edge_refs": [VERTICAL], "r": 3}
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": fil})
    assert r.status_code == 200, r.text
    assert r.json()["features"][0]["ref_bbox"] == [-25, -10, 0, 25, 10, 10]
    assert _st(c, pid)["fingerprint"]["volume"] == pytest.approx(50 * 20 * 10 - CORNER_R3, rel=1e-9)
    r = c.post(f"/api/projects/{pid}/params", json={"values": {"L": 70}})
    assert r.status_code == 200, r.text
    assert r.json()["repairs"] == []
    st = _st(c, pid)
    assert st["fingerprint"]["volume"] == pytest.approx(70 * 20 * 10 - CORNER_R3, rel=1e-9)
    assert st["manual_errors"] == []
    # and in thickness: the edge is longer, so the round removes proportionally more
    assert c.post(f"/api/projects/{pid}/params", json={"values": {"T": 15}}).status_code == 200
    assert _st(c, pid)["fingerprint"]["volume"] == pytest.approx(70 * 20 * 15 - CORNER_R3 * 1.5, rel=1e-9)


def test_demo_plate_fillet_then_length_120_to_140(app_client: TestClient) -> None:  # noqa: F811
    """The audit's exact repro: demo plate + one manual fillet on the corner edges, then Length 120 → 140."""
    c = app_client
    signup(c, "plate@x.com")
    pid, _ws = _project_with_model(c, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))
    v120 = _st(c, pid)["fingerprint"]["volume"]
    fil = {"op": "fillet", "name": "Corner fillets", "edges": [[60, 40, 4.5], [60, -40, 4.5]],
           "edge_refs": [VERTICAL, VERTICAL], "r": 3}
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": fil}).status_code == 200
    removed = v120 - _st(c, pid)["fingerprint"]["volume"]
    assert removed > 0
    r = c.post(f"/api/projects/{pid}/params", json={"values": {"L": 140}})
    assert r.status_code == 200, r.text
    assert r.json()["repairs"] == []
    st = _st(c, pid)
    # the plate grows by 20 x 80 x 10 minus the top chamfer along the extra length (2 x 20 x CH²/2); corners identical
    assert st["fingerprint"]["volume"] == pytest.approx(v120 + 20 * 80 * 10 - 20 * 1.0 - removed, rel=1e-9)
    assert st["fingerprint"]["bbox"][0] == pytest.approx(140)


def test_rebuild_error_is_flagged_not_blocking_then_repaired(app_client: TestClient) -> None:  # noqa: F811
    """IDEA 1: a parameter change that breaks a hand feature is kept; the feature is flagged with a plain reason."""
    c = app_client
    signup(c, "repair@x.com")
    pid, _ws = _project_with_model(c, BLOCK)
    top_edge = {"op": "fillet", "name": "Top round", "edges": [[0, -10, 10]], "edge_refs": [{"kind": "line", "dir": [1, 0, 0]}],
                "r": 4}
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": top_edge})
    assert r.status_code == 200, r.text
    fid = r.json()["features"][0]["id"]
    r = c.post(f"/api/projects/{pid}/params", json={"values": {"T": 3}})  # R4 can't fit on a 3 mm thick block
    assert r.status_code == 200, r.text
    rep = r.json()["repairs"]
    assert [x["name"] for x in rep] == ["Top round"] and "too large" in rep[0]["error"]
    assert "Error" not in rep[0]["error"] and "fillet()" not in rep[0]["error"]
    st = _st(c, pid)
    assert st["ok"] and st["fingerprint"]["volume"] == pytest.approx(50 * 20 * 3)  # the rest still builds
    assert next(f for f in st["features"] if f["name"] == "Top round")["error"]
    # repair by editing the radius: accepted, flag cleared
    r = c.patch(f"/api/projects/{pid}/manual/{fid}", json={"feature": {"r": 1}})
    assert r.status_code == 200, r.text
    assert _st(c, pid)["manual_errors"] == []
    # adding a feature that can't be built is still refused, in plain words with the size that fits
    big = {**top_edge, "name": "Huge round", "edges": [[0, 10, 3]], "r": 23}
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": big})
    assert r.status_code == 422
    msg = r.json()["detail"]
    assert "largest radius that fits is about" in msg and "restored" in msg
    assert "ValueError" not in msg and "max_fillet" not in msg


def test_plain_error_mapping() -> None:
    from aicad.platform.plain import build_error

    raw = ("ValueError: manual feature 'Fillet' failed: Failed creating a fillet with radius of 23.0, try a smaller "
           "value or use max_fillet() to find the largest valid fillet radius")
    m = build_error(raw)
    assert m.startswith("“Fillet” couldn't be built") and "R23 mm" in m and "max_fillet" not in m and "ValueError" not in m
    assert build_error("rejected: the part has no solid yet: add a boss") == "The part has no solid yet: add a boss"
    assert build_error("NameError: name 'X' is not defined") == "The design couldn't be rebuilt with these values"
    assert "geometry kernel" in build_error("StdFail_NotDone: BRep_API: command not done")
    assert build_error(None, [{"id": "CHK-03", "gating": True, "passed": False}]).startswith("The result has open")


def test_worker_drops_late_ready_and_stale_replies(tmp_path: Path) -> None:
    """STU-04: a worker that starts too slowly is killed (its late "ready" is never read as a reply), and replies
    are matched to requests by id."""
    from aicad.agent import worker

    slow = tmp_path / "slow.py"
    slow.write_text("import sys, time\ntime.sleep(3)\nprint('{\"ready\": true}', flush=True)\n"
                    "for line in sys.stdin: print('{\"id\": 1, \"ok\": true, \"rc\": 0}', flush=True)\n", encoding="utf-8")
    fake = tmp_path / "fake.py"
    fake.write_text(textwrap.dedent('''\
        import json, sys
        print(json.dumps({"ready": True}), flush=True)
        for line in sys.stdin:
            req = json.loads(line)
            print(json.dumps({"ready": True}), flush=True)                        # a stray late ready line
            print(json.dumps({"id": req["id"] - 1, "ok": True, "rc": 0, "op": "stale"}), flush=True)
            print(json.dumps({"id": req["id"], "ok": True, "rc": 0, "op": req["op"]}), flush=True)
    '''), encoding="utf-8")

    async def run() -> None:
        w = worker.Worker(cmd=[sys.executable, str(slow)])
        w.START_TIMEOUT_S = 0.5
        r = await w.request({"op": "build"}, timeout=5)
        assert r["rc"] == -1 and r.get("starting") and w.proc is None  # killed, not kept for the next request
        w.cmd = [sys.executable, str(fake)]
        for op in ("build", "finalize", "render"):
            r = await w.request({"op": op}, timeout=10)
            assert r["ok"] and r["op"] == op  # each reply is the one for this request
        await w.stop()

    asyncio.run(run())


def test_source_view_is_superadmin_only_and_undo_info(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "src@x.com")
    pid, _ws = _project_with_model(c, BLOCK)
    assert c.get(f"/api/projects/{pid}/source").status_code == 404  # users never see the model script (STU-06)
    hole = {"op": "hole", "name": "H1", "point": [0, 0, 10], "normal": [0, 0, 1], "d": 5}
    r1 = c.post(f"/api/projects/{pid}/manual", json={"feature": hole}).json()
    r2 = c.post(f"/api/projects/{pid}/manual", json={"feature": {**hole, "name": "H2", "point": [10, 0, 10]}}).json()
    assert r2["rev_before"] == r1["revision"] and r2["revision"] > r1["revision"]
    # undo = restore the revision before; the restore reports where it came from (for redo)
    r = c.post(f"/api/projects/{pid}/revisions/{r2['rev_before']}/restore").json()
    assert r["rev_before"] == r2["revision"] and r["revision"] == r1["revision"]
    assert _st(c, pid)["fingerprint"]["volume"] == pytest.approx(10000 - math.pi * 6.25 * 10)
    c.post("/api/auth/logout")
    admin(c)
    assert c.post(f"/api/projects/{pid}/warm").status_code == 404  # other org's project


def test_hole_wizard_tables_match_the_standards_module() -> None:
    from aicad import holes
    from aicad.engineering.standards import CLEARANCE_ISO273, COARSE_PITCH

    for d, row in holes.CLEARANCE.items():
        assert CLEARANCE_ISO273[f"M{d}"] == row
        assert COARSE_PITCH[f"M{d}"][1] == holes.PITCH[d]
    assert holes.resolve({"type": "clearance", "size": 6})["d"] == 6.6  # ISO 273 medium
    cb = holes.resolve({"type": "cbore", "size": 6, "fit": "fine"})
    assert cb["d"] == 6.4 and cb["cbore"] == {"d": 11.0, "depth": 6.4}
    with pytest.raises(holes.HoleError):
        holes.resolve({"type": "csk", "size": 24})


def test_hole_wizard_corner_holes_by_edge_distance(app_client: TestClient) -> None:  # noqa: F811
    """IDEA 3: 4 x M6 clearance holes 10 mm from the edges of the top face; they follow the face when it grows."""
    c = app_client
    signup(c, "wizard@x.com")
    pid, _ws = _project_with_model(c, BLOCK.replace("L = 50.0", "L = 100.0").replace("W = 20.0", "W = 60.0"))
    hw = {"op": "hole", "name": "M6 clearance (4x)", "point": [0, 0, 10], "normal": [0, 0, 1], "d": 1,
          "spec": {"type": "clearance", "size": 6, "fit": "medium"},
          "place": {"mode": "corners", "face": {"point": [3, 2, 10]}, "dx": 10, "dy": 10}}
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": hw})
    assert r.status_code == 200, r.text
    f = r.json()["features"][0]
    assert f["d"] == 6.6 and f["spec"]["label"] == "M6 clearance Ø6.6 (medium)"  # from the table, not the client
    hole = math.pi * 3.3 ** 2 * 10
    assert _st(c, pid)["fingerprint"]["volume"] == pytest.approx(100 * 60 * 10 - 4 * hole, rel=1e-9)
    topo = c.get(f"/api/projects/{pid}/files/topo.json").json()
    centres = sorted((round(x["axis_point"][0], 6), round(x["axis_point"][1], 6)) for x in topo["faces"]
                     if x["type"] == "cylinder")
    assert centres == [(-40, -20), (-40, 20), (40, -20), (40, 20)]
    # counterbored (ISO 4762 / DIN 974-1): Ø11 x 6.4 deep over the Ø6.6 hole
    r = c.patch(f"/api/projects/{pid}/manual/{f['id']}", json={"feature": {"spec": {"type": "cbore", "size": 6}}})
    assert r.status_code == 200, r.text
    cb = math.pi * 5.5 ** 2 * 6.4 + math.pi * 3.3 ** 2 * (10 - 6.4)
    assert _st(c, pid)["fingerprint"]["volume"] == pytest.approx(100 * 60 * 10 - 4 * cb, rel=1e-9)
    # countersunk (ISO 10642, 90°): cone frustum from Ø13.44 down to Ø6.6, then the hole
    r = c.patch(f"/api/projects/{pid}/manual/{f['id']}", json={"feature": {"spec": {"type": "csk", "size": 6}}})
    assert r.status_code == 200, r.text
    R, rr = 13.44 / 2, 3.3
    h = R - rr  # 90° included angle: depth = radial step
    csk = math.pi * h * (R * R + R * rr + rr * rr) / 3 + math.pi * rr * rr * (10 - h)
    assert _st(c, pid)["fingerprint"]["volume"] == pytest.approx(100 * 60 * 10 - 4 * csk, rel=1e-9)
    # the plate gets longer: the holes stay 10 mm from the (moved) edges
    assert c.post(f"/api/projects/{pid}/params", json={"values": {"L": 140}}).status_code == 200
    topo = c.get(f"/api/projects/{pid}/files/topo.json").json()
    xs = sorted({round(x["axis_point"][0], 6) for x in topo["faces"] if x["type"] == "cylinder"})
    assert xs == [-60, 60]
    # holes that can't fit are refused with the face size
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": {**hw, "name": "Too far", "place": {**hw["place"], "dx": 80}}})
    assert r.status_code == 422 and "don't fit" in r.json()["detail"]
    # a size outside the tables is refused
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": {**hw, "spec": {"type": "clearance", "size": 7}}})
    assert r.status_code == 422 and "M7" in r.json()["detail"]


def test_undo_redo_walks_the_revisions(app_client: TestClient) -> None:  # noqa: F811
    """STU-10: Ctrl+Z goes back to the revision an edit was made from, Ctrl+Y re-applies it (no AI)."""
    c = app_client
    signup(c, "undo@x.com")
    pid, _ws = _project_with_model(c, BLOCK)
    first = {"op": "hole", "name": "H0", "point": [-15, 0, 10], "normal": [0, 0, 1], "d": 4}
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": first}).status_code == 200
    v0 = 50 * 20 * 10 - math.pi * 4 * 10
    hole = {"op": "hole", "name": "H1", "point": [0, 0, 10], "normal": [0, 0, 1], "d": 4}
    r1 = c.post(f"/api/projects/{pid}/manual", json={"feature": hole}).json()
    assert _st(c, pid)["fingerprint"]["volume"] == pytest.approx(v0 - math.pi * 4 * 10)
    u = c.post(f"/api/projects/{pid}/undo")
    assert u.status_code == 200, u.text
    assert u.json()["undone"] == r1["revision"] and "H1" in u.json()["why"]
    assert _st(c, pid)["fingerprint"]["volume"] == pytest.approx(v0)
    assert [f["name"] for f in c.get(f"/api/projects/{pid}/manual").json()["features"]] == ["H0"]
    r = c.post(f"/api/projects/{pid}/redo", json={"to": r1["revision"]})
    assert r.status_code == 200, r.text
    assert _st(c, pid)["fingerprint"]["volume"] == pytest.approx(v0 - math.pi * 4 * 10)
    # a redo that no longer follows from the current model is refused
    assert c.post(f"/api/projects/{pid}/redo", json={"to": r1["revision"]}).status_code == 409
