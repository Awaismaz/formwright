"""Studio intelligence: the agent fills the PropertyManager (DS-035) and change impact preview (ASM-018).

No model calls: agent turns are replayed cassettes. Hand values:
- fw-edit on a 60 × 40 × 10 box: the top face has 4 edges whose true midpoints are (0, ±20, 10) and (±30, 0, 10).
  A 2 mm chamfer of those 4 edges removes (L + W) d² − 4 d³ / 3 = 100 · 4 − 32 / 3 mm³ (the mounting-plate formula),
  so the box keeps 24000 − 400 + 32 / 3 mm³.
- Impact fixture: a 120 × 80 × 10 plate (fixed) with 4 Ø6.6 holes at (±50, ±30); a 40 × 30 × 20 block coincident on
  its top face; a Ø6 × 30 pin (centred on its origin) concentric with the hole at (50, 30), placed at z = 5 so
  it spans z −10..20.
  * HOLES 4 → 0 (breaking): the pin's concentric mate loses its hole (1 mate breaks) and the pin now sits inside
    solid plate: new clash = π · 3² · 10 = 90 π mm³.
  * T 10 → 12: the block's coincident mate follows the top face, the block moves up exactly 2 mm, no clash.
  * a 10 × 10 × 3 boss on the top face under the block (a manual feature): the block stays on z = 10, so the new
    clash is the whole boss, 300 mm³.
"""

from __future__ import annotations

import asyncio
import json
import math
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_platform import signup

from aicad.agent.edits import EditError, design_state, extract_edit, parse_edit, side_edges
from aicad.agent.replay import ReplayClient
from aicad.agent.session import AgentSession, scrub

BOX = """from build123d import *
NAME = "Box"
MATERIAL = "Aluminium 6061-T6"
L = 60.0  # length
W = 40.0  # width
H = 10.0  # height
PARAMS = dict(L=L, W=W, H=H)
PARAM_META = {"H": {"min": 2, "max": 50, "unit": "mm", "label": "Height"}}
result = Box(L, W, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
EXPECTED = {"bbox": [L, W, H], "volume": L * W * H, "solids": 1}
"""

PLATE = """from build123d import *
NAME = "Base plate"
MATERIAL = "Aluminium 6061-T6"
L = 120.0  # length
W = 80.0  # width
T = 10.0  # thickness
HOLES = 4  # mounting holes (0 or 4)
HOLE_D = 6.6  # clearance hole
PARAMS = dict(L=L, W=W, T=T, HOLES=HOLES, HOLE_D=HOLE_D)
part = Box(L, W, T, align=(Align.CENTER, Align.CENTER, Align.MIN))
for x, y in [(50, 30), (-50, 30), (-50, -30), (50, -30)][:HOLES]:
    part -= Pos(x, y, T / 2) * Cylinder(HOLE_D / 2, T + 2)
result = part
EXPECTED = {"bbox": [L, W, T], "solids": 1}
"""

BLOCK = """from build123d import *
NAME = "Block"
MATERIAL = "Steel 1045"
result = Box(40, 30, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))
EXPECTED = {"bbox": [40, 30, 20], "volume": 24000, "solids": 1}
"""

PIN = """from build123d import *
NAME = "Pin"
MATERIAL = "Steel 1045"
result = Cylinder(3, 30)
EXPECTED = {"bbox": [6, 6, 30], "solids": 1}
"""


def _build(ws: Path, src: str) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "model.py").write_text(src, encoding="utf-8")
    subprocess.run([sys.executable, "-I", "-m", "aicad.agent.runner", str(ws / "model.py"), str(ws / "out")],
                   cwd=ws, timeout=240, check=True)


def _fence(obj: Any) -> str:
    return "```fw-edit\n" + json.dumps(obj) + "\n```"


@pytest.fixture(scope="module")
def box_ws(tmp_path_factory: pytest.TempPathFactory) -> Path:
    ws = tmp_path_factory.mktemp("box")
    _build(ws, BOX)
    return ws


# ------------------------------------------------------------------ fw-edit block (DS-035)
def test_side_keyword_resolves_the_top_face_edges(box_ws: Path) -> None:
    topo = json.loads((box_ws / "out" / "topo.json").read_text())
    assert len(side_edges(topo, "top")) == 4
    e = parse_edit({"op": "chamfer", "d": 2, "edges": "top"}, box_ws)
    mids = sorted(tuple(round(c, 6) for c in p["point"]) for p in e["targets"]["picks"])
    assert mids == sorted([(0.0, -20.0, 10.0), (0.0, 20.0, 10.0), (-30.0, 0.0, 10.0), (30.0, 0.0, 10.0)])
    assert e["targets"]["kind"] == "edge" and e["feature"]["op"] == "chamfer" and e["feature"]["d"] == 2
    assert all(r["kind"] == "line" for r in e["feature"]["edge_refs"])
    assert e["summary"] == "Add Chamfer 2 mm on 4 edges" and e["feature_id"] is None


def test_top_edges_are_the_outer_loop_not_the_hole_rims(tmp_path: Path) -> None:
    """The plate's top face has 4 straight outer edges and 4 hole rims: "the top edges" are the 4 outer ones."""
    _build(tmp_path / "plate", PLATE)
    topo = json.loads((tmp_path / "plate" / "out" / "topo.json").read_text())
    ids = side_edges(topo, "top")
    assert len(ids) == 4 and all(topo["edges"][i]["type"] == "line" for i in ids)
    assert sorted(round(topo["edges"][i]["length"], 6) for i in ids) == [80.0, 80.0, 120.0, 120.0]


def test_points_from_a_selection_and_validation(box_ws: Path) -> None:
    from aicad.platform.routers.studio import validate_feature

    e = parse_edit({"op": "fillet", "r": 1.5, "edges": [[0, -20, 10], [30, 0, 10]], "summary": "Round two edges"},
                   box_ws, validate=validate_feature)
    assert len(e["targets"]["picks"]) == 2 and e["feature"]["r"] == 1.5 and e["summary"] == "Round two edges"
    f = parse_edit({"op": "shell", "t": 2, "faces": "top"}, box_ws, validate=validate_feature)
    assert f["targets"]["kind"] == "face" and f["feature"]["faces"][0]["normal"] == [0.0, 0.0, 1.0]
    h = parse_edit({"op": "hole", "type": "clearance", "size": 6, "dx": 10, "faces": "top"}, box_ws,
                   validate=validate_feature)
    assert h["feature"]["d"] == 6.6 and h["feature"]["place"]["mode"] == "corners"  # ISO 273 medium M6
    assert h["values"]["hole"] == {"type": "clearance", "size": 6.0, "mode": "corners", "dx": 10.0, "dy": 10.0}
    for bad, why in [({"op": "fillet", "r": 2, "edges": [[0, 0, 99]]}, "wasn't found"),
                     ({"op": "fillet", "r": -1, "edges": "top"}, "Radius"),
                     ({"op": "loft"}, "Only fillets"),
                     ({"op": "fillet", "r": 2, "edges": "upward"}, "can't tell"),
                     ({"op": "params", "params": {"NOPE": 3}}, "isn't an editable"),
                     ({"op": "params", "params": {"H": 99}}, "between 2 and 50"),
                     ({"op": "fillet", "r": 2, "feature": "Nothing"}, "no hand-made feature")]:
        with pytest.raises(EditError, match=why):
            parse_edit(bad, box_ws, validate=validate_feature)


def test_params_edit_and_block_extraction(box_ws: Path) -> None:
    e = parse_edit({"op": "params", "params": {"H": 12}}, box_ws)
    assert e["params"] == {"H": {"from": 10.0, "to": 12.0, "label": "Height", "unit": "mm"}}
    assert e["summary"] == "Change Height to 12 mm"
    text, edit, note = extract_edit("Opening it for you.\n" + _fence({"op": "params", "params": {"H": 12}}), box_ws, scrub)
    assert text == "Opening it for you." and edit and edit["op"] == "params" and note is None
    text, edit, note = extract_edit("x\n```fw-edit\n{not json\n```", box_ws, scrub)
    assert text == "x" and edit is None and note == "The proposed edit wasn't readable."
    text, edit, note = extract_edit(_fence({"op": "params", "params": {"H": 1}}), box_ws, scrub)
    assert edit is None and "between 2 and 50" in (note or "") and "fw-edit" not in text
    st = design_state(box_ws)
    assert st and st.startswith("[Design state for quick edits: size 60 × 40 × 10 mm; parameters L=60, W=40, H=10 (Height)")


def test_editing_an_existing_hand_made_feature(tmp_path: Path) -> None:
    from aicad.platform.routers.studio import validate_feature, write_manual

    ws = tmp_path / "ws"
    feat = {"id": "f1", "op": "fillet", "name": "Top fillet", "suppressed": False, "r": 1.0,
            "edges": [[0.0, -20.0, 10.0]], "edge_refs": [{"kind": "line", "dir": [1.0, 0.0, 0.0]}]}
    _build(ws, write_manual(BOX, [feat]))
    e = parse_edit({"op": "fillet", "feature": "top fillet", "r": 3}, ws, validate=validate_feature)
    assert e["feature_id"] == "f1" and e["feature"]["r"] == 3 and e["feature"]["edges"] == feat["edges"]
    assert e["targets"] is None and e["summary"] == "Edit Fillet R3"
    with pytest.raises(EditError, match="is a fillet, not a chamfer"):
        parse_edit({"op": "chamfer", "feature": "f1", "d": 1}, ws)
    assert "f1 “Top fillet” fillet r=1" in (design_state(ws) or "")


def _cassette_turn(text: str) -> dict[str, Any]:
    return {"messages": [
        {"type": "system", "subtype": "init", "data": {}},
        {"type": "assistant", "model": "replay", "usage": {"input_tokens": 40, "output_tokens": 30},
         "content": [{"type": "text", "text": text}]},
        {"type": "result", "subtype": "success", "num_turns": 1, "duration_ms": 900, "session_id": "rp-edit",
         "total_cost_usd": 0.0}]}


def test_replayed_small_edit_is_one_short_turn(box_ws: Path, tmp_path: Path) -> None:
    """The measure for DS-035: "add a 2 mm chamfer to the top edges" resolves in ONE turn with no tool call and no
    rebuild by the agent; the PropertyManager gets the exact edges."""
    import shutil

    ws = tmp_path / "ws"
    shutil.copytree(box_ws, ws)
    events: list[dict[str, Any]] = []
    s = AgentSession(ws, on_event=events.append)
    reply = "I'll open a 2 mm chamfer on the four top edges.\n" + _fence(
        {"summary": "Chamfer the top edges 2 mm", "op": "chamfer", "d": 2, "edges": "top"})
    s.client_factory = lambda o: ReplayClient(o, {"turns": [_cassette_turn(reply)]})
    before = (ws / "model.py").read_text()
    asyncio.run(s.send("add a 2 mm chamfer to the top edges"))
    kinds = [e["type"] for e in events]
    assert "tool" not in kinds and "tool_result" not in kinds  # no reading, no writing, no build
    res = next(e for e in events if e["type"] == "result")
    assert res["turns"] == 1
    edit = next(e for e in events if e["type"] == "edit")["edit"]
    assert edit["op"] == "chamfer" and len(edit["targets"]["picks"]) == 4 and edit["summary"] == "Chamfer the top edges 2 mm"
    shown = " ".join(e["text"] for e in events if e["type"] == "text")
    assert "fw-edit" not in shown and "```" not in shown
    assert (ws / "model.py").read_text() == before  # the agent changed nothing


# ------------------------------------------------------------------ through the app (impact + apply)
@pytest.fixture()
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from aicad.platform import config
    from aicad.platform.routers import auth as auth_router

    auth_router._attempts.clear()
    monkeypatch.setenv("FW_ADMIN_PASSWORD", "correct horse 42")
    config.override_settings(config.Settings(
        env="development", data_dir=tmp_path / "data", database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
        app_url="http://testserver", superadmin_emails=("boss@example.com",), stripe_secret_key="", trial_tokens=300))
    from aicad.agent import worker
    from aicad.assembly import worker as aworker
    from aicad.platform.app import create_app

    with TestClient(create_app()) as c:
        c.headers.update({"X-FW-CSRF": "1"})
        yield c
        c.portal.call(aworker.shutdown_all)  # type: ignore[union-attr]
    aworker.kill_all()
    for w in worker._workers.values():
        if w.proc is not None and w.proc.returncode is None:
            w.proc.kill()
        w.proc = None
    worker._workers.clear()


def _project(c: TestClient, name: str, src: str) -> tuple[str, Path]:
    from aicad.platform.db import session_factory
    from aicad.platform.models import Project
    from aicad.platform.routers.projects import workspace_for

    pid = c.post("/api/projects", json={"name": name}).json()["id"]
    db = session_factory()()
    proj = db.get(Project, pid)
    ws = workspace_for(proj)
    proj.builds = 1  # built once (as by the agent): the next request is a change, not a new design
    db.commit()
    db.close()
    _build(ws, src)
    return pid, ws


def test_small_edit_applies_through_the_manual_path(app: TestClient, tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end: the replayed agent proposes, the PropertyManager payload goes through the normal manual-feature
    endpoint, and the volume is the analytic one. The design state rides along with the short request."""
    from test_ai_quality import _wait_idle

    reply = "Opening a 2 mm chamfer on the top edges.\n" + _fence({"op": "chamfer", "d": 2, "edges": "top"})
    f = tmp_path / "cassette.json"
    f.write_text(json.dumps({"turns": [_cassette_turn(reply)]}))
    monkeypatch.setenv("FW_AGENT_REPLAY", str(f))
    c = app
    signup(c, "edit@x.com")
    pid, ws = _project(c, "Box", BOX)
    assert c.post(f"/api/projects/{pid}/agent/chat", json={"prompt": "chamfer the top edges 2 mm"}).status_code == 200
    hist = _wait_idle(pid)
    user = next(e for e in hist if e["type"] == "user")
    assert user["text"] == "chamfer the top edges 2 mm"  # the design-state line is never shown
    from aicad.platform.routers.projects import _sessions

    assert "[Design state for quick edits:" in _sessions[pid].client.prompts[0]
    edit = next(e for e in hist if e["type"] == "edit")["edit"]
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": edit["feature"]})
    assert r.status_code == 200, r.text
    st = json.loads((ws / "out" / "status.json").read_text())
    assert st["fingerprint"]["volume"] == pytest.approx(24000 - (100 * 4 - 4 * 8 / 3), rel=1e-6)
    # no assembly uses the box: the impact preview answers without a trial build
    pay = c.post("/api/billing/checkout", json={"product_code": "addon_assembly"}).json()["payment_id"]
    c.post(f"/api/billing/payments/{pay}/simulate", json={"outcome": "success"})
    r = c.post(f"/api/m/assembly/impact/{pid}", json={"kind": "params", "values": {"H": 12}}).json()
    assert r["assemblies"] == [] and r["checked"] is False and r["headline"] == "This part isn't used in any assembly."


def _plane(c: TestClient, aid: str, iid: str, nz: float, z: float, data: Path, org: str) -> int:
    v = c.get(f"/api/m/assembly/assemblies/{aid}").json()
    inst = next(i for i in v["instances"] if i["id"] == iid)
    refs = json.loads((data / "assemblies" / org / "_parts" / inst["part"] / "refs.json").read_text())
    return next(int(k) for k, f in refs["faces"].items()
                if f["kind"] == "plane" and abs(f["v"][2] - nz) < 1e-9 and abs(f["p"][2] - z) < 1e-9)


def _axis(c: TestClient, aid: str, iid: str, x: float, y: float, r: float, data: Path, org: str) -> int:
    v = c.get(f"/api/m/assembly/assemblies/{aid}").json()
    inst = next(i for i in v["instances"] if i["id"] == iid)
    refs = json.loads((data / "assemblies" / org / "_parts" / inst["part"] / "refs.json").read_text())
    return next(int(k) for k, f in refs["faces"].items() if f["kind"] == "axis" and abs(f["r"] - r) < 1e-6
                and abs(f["p"][0] - x) < 1e-6 and abs(f["p"][1] - y) < 1e-6)


def test_impact_preview_on_a_fixture_assembly(app: TestClient, tmp_path: Path) -> None:
    from aicad.assembly import xform

    c = app
    signup(c, "impact@x.com")
    pay = c.post("/api/billing/checkout", json={"product_code": "addon_assembly"}).json()["payment_id"]
    c.post(f"/api/billing/payments/{pay}/simulate", json={"outcome": "success"})
    plate_pid, plate_ws = _project(c, "Base plate", PLATE)
    block_pid, _ = _project(c, "Block", BLOCK)
    pin_pid, _ = _project(c, "Pin", PIN)
    v = c.post("/api/m/assembly/assemblies", json={"project_id": plate_pid}).json()
    aid, plate = v["assembly"]["id"], v["instances"][0]["id"]
    block = c.post(f"/api/m/assembly/assemblies/{aid}/instances", json={"project_id": block_pid}).json()["result"]["instance"]
    pin = c.post(f"/api/m/assembly/assemblies/{aid}/instances", json={"project_id": pin_pid}).json()["result"]["instance"]
    c.patch(f"/api/m/assembly/assemblies/{aid}/instances/{block}", json={"T": xform.to12(xform.translate((0, 0, 10)))})
    c.patch(f"/api/m/assembly/assemblies/{aid}/instances/{pin}", json={"T": xform.to12(xform.translate((50, 30, 5)))})
    data, org = tmp_path / "data", c.get("/api/auth/me").json()["org"]["id"]
    r = c.post(f"/api/m/assembly/assemblies/{aid}/mates", json={
        "type": "coincident", "a": {"inst": plate, "kind": "face", "id": _plane(c, aid, plate, 1, 10, data, org)},
        "b": {"inst": block, "kind": "face", "id": _plane(c, aid, block, -1, 0, data, org)}})
    assert r.status_code == 200, r.text
    r = c.post(f"/api/m/assembly/assemblies/{aid}/mates", json={
        "type": "concentric", "a": {"inst": plate, "kind": "face", "id": _axis(c, aid, plate, 50, 30, 3.3, data, org)},
        "b": {"inst": pin, "kind": "face", "id": _axis(c, aid, pin, 0, 0, 3, data, org)}})
    assert r.status_code == 200, r.text
    doc_before = (data / "assemblies" / org / aid / "assembly.json").read_text()
    an = c.post(f"/api/m/assembly/assemblies/{aid}/analyse").json()["analysis"]
    assert an["interference"]["count"] == 0
    doc_before = (data / "assemblies" / org / aid / "assembly.json").read_text()
    model_before = (plate_ws / "model.py").read_text()

    # where-used without a change: the Studio chip
    assert c.get(f"/api/m/assembly/where-used/{plate_pid}").json()["items"][0]["instances"] == 1

    # 1) a known breaking change: HOLES 4 -> 0
    r = c.post(f"/api/m/assembly/impact/{plate_pid}", json={"kind": "params", "values": {"HOLES": 0}})
    assert r.status_code == 200, r.text
    imp = r.json()
    a = imp["assemblies"][0]
    assert imp["checked"] and a["id"] == aid and a["instances"] == 1
    assert [m["status"] for m in a["mates"]] == ["breaks"] and a["breaks"] == 1
    assert a["mates"][0]["text"].startswith("Concentric: Base plate<1> Ø6.6 hole ↔ Pin<1>")
    assert len(a["clashes"]) == 1 and {a["clashes"][0]["a"], a["clashes"][0]["b"]} == {plate, pin}
    assert a["clashes"][0]["volume_mm3"] == pytest.approx(90 * math.pi, rel=1e-4) and a["clashes"][0]["was_mm3"] == 0
    assert a["moved"] == []
    assert imp["headline"] == "This change affects 1 assembly: 1 mate breaks, 1 new clash"
    assert imp["issues"] == 2

    # 2) a following change: T 10 -> 12 moves the block up 2 mm, nothing breaks, no clash
    imp = c.post(f"/api/m/assembly/impact/{plate_pid}", json={"kind": "params", "values": {"T": 12}}).json()
    a = imp["assemblies"][0]
    assert a["breaks"] == 0 and a["clashes"] == [] and {m["status"] for m in a["mates"]} == {"follows"}
    assert [(m["id"], m["mm"]) for m in a["moved"]] == [(block, pytest.approx(2.0, abs=1e-6))]
    assert imp["headline"] == "This change affects 1 assembly: 1 part moves"

    # 3) a manual feature (the PropertyManager path): a 10 x 10 x 3 boss under the block
    boss = {"op": "extrude", "name": "Boss", "plane": {"origin": [0, 0, 10], "normal": [0, 0, 1]},
            "sketch": {"kind": "rect", "w": 10, "h": 10, "cx": 0, "cy": 0}, "distance": 3, "mode": "add"}
    imp = c.post(f"/api/m/assembly/impact/{plate_pid}", json={"kind": "feature", "feature": boss}).json()
    a = imp["assemblies"][0]
    assert a["breaks"] == 0 and len(a["clashes"]) == 1 and a["moved"] == []
    assert {a["clashes"][0]["a"], a["clashes"][0]["b"]} == {plate, block}
    assert a["clashes"][0]["volume_mm3"] == pytest.approx(300.0, rel=1e-6)

    # nothing was committed: the model, the assembly and the part cache are as before
    assert (plate_ws / "model.py").read_text() == model_before
    assert (data / "assemblies" / org / aid / "assembly.json").read_text() == doc_before
    assert not [d for d in (data / "assemblies" / org / "_parts").iterdir() if d.name.startswith("x_")]
    assert not list((plate_ws / ".fw" / "impact").iterdir())
    # a change that can't be built is refused with a plain reason
    r = c.post(f"/api/m/assembly/impact/{plate_pid}", json={"kind": "params", "values": {"NOPE": 1}})
    assert r.status_code == 422 and "not an editable design parameter" in r.json()["detail"]


def test_datasheet_shots_go_stale_and_requeue(app: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Living datasheet pack: a saved shot is stale until rendered on the current build; one click queues every stale
    shot (the render itself is faked: no Blender needed)."""
    from aicad.meshstudio import scene
    from aicad.meshstudio import service as ms

    calls: list[dict[str, Any]] = []

    def fake_request(ws: Path, name: str, opts: scene.Options, org: str, user: str, base: str = "") -> dict[str, Any]:
        calls.append(opts.key())
        return {"id": f"{len(calls):016x}", "state": "queued"}

    monkeypatch.setattr(ms, "request_render", fake_request)
    c = app
    signup(c, "shots@x.com")
    pay = c.post("/api/billing/checkout", json={"product_code": "addon_mesh"}).json()["payment_id"]
    c.post(f"/api/billing/payments/{pay}/simulate", json={"outcome": "success"})
    pid, _ws = _project(c, "Box", BOX)
    r = c.post(f"/api/m/mesh/projects/{pid}/shots", json={"finish": "clay", "quality": "final", "camera": "hero"})
    assert r.status_code == 200, r.text
    sh = r.json()
    assert len(sh["shots"]) == 1 and sh["stale"] == 1  # never rendered yet
    assert c.post(f"/api/m/mesh/projects/{pid}/shots", json={"finish": "clay", "quality": "final"}).status_code == 422
    r = c.post(f"/api/m/mesh/projects/{pid}/shots/rerender").json()
    assert len(r["queued"]) == 1 and r["stale"] == 0 and calls[0]["quality"] == "final"
    # the part revises (a parameter edit): the shot is stale again, and one click queues it again
    assert c.post(f"/api/projects/{pid}/params", json={"values": {"H": 12}}).status_code == 200
    sh = c.get(f"/api/m/mesh/projects/{pid}/shots").json()
    assert sh["stale"] == 1 and sh["shots"][0]["stale"] is True
    assert len(c.post(f"/api/m/mesh/projects/{pid}/shots/rerender").json()["queued"]) == 1 and len(calls) == 2
    assert c.post(f"/api/m/mesh/projects/{pid}/shots/rerender").json()["queued"] == []  # nothing stale: nothing queued
    sid = sh["shots"][0]["id"]
    assert c.delete(f"/api/m/mesh/projects/{pid}/shots/{sid}").json()["shots"] == []
