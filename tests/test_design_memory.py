"""Projects that hold related parts, the agent's project brief, and personal design memory (no live model calls).

Hand checks used below:
- mounting plate demo (`demo/mounting_plate.py`): 120 × 80 × 10 mm, Aluminium 6061-T6, four Ø6.6 (M6 medium,
  ISO 273) through holes 10 mm in from each edge -> a 100 × 60 mm grid centred on the origin;
- pipe flange demo (`demo/pipe_flange.py`): Ø150 × 18 mm (16 + 2 raised face), carbon steel, six Ø14 holes on a
  Ø120 mm pitch circle, bore Ø60.3 mm.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_collab import _member, _org_id
from test_platform import app_client, signup  # noqa: F401  (fixture re-export)

from aicad import recognize
from aicad.memory import context as mctx
from aicad.memory import extract, learn
from aicad.memory import facts as F
from aicad.memory.tables import DesignProject, DesignProjectPart, MemoryEvent, MemoryFact
from aicad.platform.collab import merge
from aicad.platform.db import session_factory, utcnow
from aicad.platform.models import Organization, Project, User

DEMO = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo"
INTERNAL = ("model.py", ".py", "mcp__", "build_model", "claude", "Read(", "Write(", "session_id", "prompt")


# ----------------------------------------------------------------------------- helpers
def _part(c: TestClient, name: str, dp: str | None = None, script: str | None = None) -> tuple[str, Path]:
    from aicad.platform.routers.projects import workspace_for

    r = c.post("/api/projects", json={"name": name, **({"design_project_id": dp} if dp else {})})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    db = session_factory()()
    ws = workspace_for(db.get(Project, pid))
    db.close()
    if script:
        (ws / "model.py").write_text(script, encoding="utf-8")
        subprocess.run([sys.executable, "-I", "-m", "aicad.agent.runner", str(ws / "model.py"), str(ws / "out")],
                       cwd=ws, timeout=240, check=True)
        st = json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
        db = session_factory()()
        p = db.get(Project, pid)
        p.last_status = {k: st.get(k) for k in ("ok", "part", "material", "fingerprint", "build_id")}  # type: ignore[union-attr]
        p.builds = 1  # type: ignore[union-attr]
        db.commit()
        db.close()
    return pid, ws


def _ctx_for(email: str) -> tuple[Any, Any]:
    db = session_factory()()
    u = db.scalar(select(User).where(User.email == email))
    return db, u


# ============================================================================= pure functions
def test_statement_capture_is_explicit_only() -> None:
    s = extract.statements("Make the cover 3 mm thick. All fasteners M6 ISO 4762. Always add 0.5 mm chamfers to "
                           "outside edges. Should I use M5? I prefer counterbored holes.\n\n[Design state: x]",
                           in_project=True)
    assert [(x.scope, x.text, x.category) for x in s] == [
        ("project", "All fasteners M6 ISO 4762", "fastener"),
        ("personal", "Always add 0.5 mm chamfers to outside edges", "other"),
        ("personal", "I prefer counterbored holes", "other")]
    # outside a project, "all fasteners ..." is about this part only: nothing is kept
    assert extract.statements("All fasteners M6 ISO 4762.", in_project=False) == []
    assert extract.statements("Use 6061-T6 for every part in this project.", True)[0].category == "material"
    assert extract.statements("make it 10 mm longer", True) == []
    assert extract.statements("Can you always use M6?", True) == []  # a question is never a rule


def test_topo_census_matches_hand_values_and_skips_rounded_corners(tmp_path: Path) -> None:
    """Interfaces from the faces alone: the plate's pocket corners (R3 quarter cylinders) are not holes."""
    for name in ("mounting_plate", "pipe_flange"):
        ws = tmp_path / name
        ws.mkdir()
        (ws / "model.py").write_text((DEMO / f"{name}.py").read_text(encoding="utf-8"), encoding="utf-8")
        subprocess.run([sys.executable, "-I", "-m", "aicad.agent.runner", "model.py", "out"], cwd=ws, timeout=240,
                       check=True)
    plate = F.part_facts(tmp_path / "mounting_plate", "Plate")
    assert plate["size"] == [120.0, 80.0, 10.0] and plate["material"] == "Aluminium 6061-T6"
    assert plate["interfaces"] == ["4× Ø6.6 round, axis Z on 100 × 60 grid centred (X0, Y0)"]
    flange = F.part_facts(tmp_path / "pipe_flange", "Flange")
    assert flange["size"] == [150.0, 150.0, 18.0]
    assert "6× Ø14 round, axis Z on Ø120 PCD centred (X0, Y0)" in flange["interfaces"]
    assert "Ø60.3 round, axis Z at (X0, Y0)" in flange["interfaces"]
    assert "outer Ø150 along Z" in flange["interfaces"]
    line = F.fact_line(flange, 300)
    assert len(line) <= 300 and line.startswith("Flange (Carbon steel): 150 × 150 × 18 mm")
    # recognition, when current for the build, is preferred and says "thru"
    rec = {"version": recognize.VERSION,
           "build_id": json.loads((tmp_path / "pipe_flange" / "out" / "status.json").read_text())["build_id"],
           "stock": {"kind": "prismatic"}, "holes": [{"d": 14.0, "through": True, "depth": 18, "center": [60, 0, 9],
                                                      "axis": [0, 0, 1]}] * 6,
           "patterns": [{"kind": "circular", "d": 14.0, "count": 6, "pcd": 120.0, "axis": [0, 0, 1],
                         "holes": list(range(6))}], "bosses": []}
    (tmp_path / "pipe_flange" / "out" / "recognition.json").write_text(json.dumps(rec))
    f2 = F.part_facts(tmp_path / "pipe_flange", "Flange")
    assert f2["interfaces_from"] == "recognition" and f2["interfaces"][0].startswith("6× Ø14 thru on Ø120 PCD, axis Z")


# ============================================================================= migration
def test_existing_database_gains_memory_tables_parts_stay_unsorted(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import Session

    from aicad.memory import tables as mt
    from aicad.platform import config
    from aicad.platform.db import Base
    from aicad.platform.models import Membership
    from aicad.platform.security import hash_password

    url = f"sqlite:///{(tmp_path / 'old.sqlite').as_posix()}"
    eng = create_engine(url)
    new = {m.__tablename__ for m in (mt.DesignProject, mt.DesignProjectPart, mt.ProjectDecision, mt.MemoryFact,
                                     mt.MemoryEvent)}
    Base.metadata.create_all(eng, tables=[t for t in Base.metadata.sorted_tables if t.name not in new])
    with Session(eng) as db:
        u = User(email="old@x.com", name="Old Timer", password_hash=hash_password("correct horse 42"),
                 email_verified_at=utcnow(), onboarding_completed_at=utcnow())
        o = Organization(name="Old Co", plan_code="trial", plan_status="trialing",
                         trial_ends_at=utcnow() + timedelta(days=10))
        db.add_all([u, o])
        db.flush()
        u.default_org_id = o.id
        db.add(Membership(user_id=u.id, org_id=o.id, role="owner"))
        db.add(Project(org_id=o.id, name="Legacy bracket", created_by=u.id))
        db.commit()
    eng.dispose()
    monkeypatch.setenv("FW_ADMIN_PASSWORD", "correct horse 42")
    config.override_settings(config.Settings(env="development", data_dir=tmp_path / "data", database_url=url,
                                             app_url="http://testserver", superadmin_emails=("boss@x.com",),
                                             stripe_secret_key=""))
    from aicad.platform.app import create_app

    with TestClient(create_app()) as c:
        c.headers.update({"X-FW-CSRF": "1"})
        eng2 = create_engine(url)
        with eng2.begin() as cx:
            assert new <= set(inspect(cx).get_table_names())
        eng2.dispose()
        assert c.post("/api/auth/login", json={"email": "old@x.com", "password": "correct horse 42"}).status_code == 200
        items = c.get("/api/projects").json()["items"]
        assert [(i["name"], i["design_project"]) for i in items] == [("Legacy bracket", None)]  # unsorted
        assert c.get("/api/design-projects").json()["items"] == []
        assert c.get(f"/api/projects/{items[0]['id']}/agent-context").json()["in_use"] is False
        assert c.get("/api/memory").json()["facts"] == []


# ============================================================================= project brief
def test_three_part_project_brief_is_hand_checked_and_bounded(app_client: TestClient,  # noqa: F811
                                                             tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = app_client
    signup(c, "brief@x.com")
    dp = c.post("/api/design-projects", json={"name": "Pump skid PS-1",
                                              "purpose": "Base plate, flange and cover of a small pump skid"}).json()
    assert dp["parts"] == 0
    did = c.post(f"/api/design-projects/{dp['id']}/decisions", json={"text": "All fasteners M6 ISO 4762"}).json()
    assert did["category"] == "fastener"
    _part(c, "Housing plate", dp["id"], (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))
    _part(c, "Outlet flange", dp["id"], (DEMO / "pipe_flange.py").read_text(encoding="utf-8"))
    cover, _ = _part(c, "Cover", dp["id"])
    page = c.get(f"/api/design-projects/{dp['id']}").json()
    assert [i["name"] for i in page["items"]] == ["Housing plate", "Outlet flange", "Cover"]
    assert page["items"][0]["facts"]["interfaces"] == ["4× Ø6.6 round, axis Z on 100 × 60 grid centred (X0, Y0)"]
    lst = {i["id"]: i for i in c.get("/api/projects").json()["items"]}
    assert lst[cover]["design_project"] == {"id": dp["id"], "name": "Pump skid PS-1"}

    db, u = _ctx_for("brief@x.com")
    tc = mctx.turn_context(db, u, db.get(Project, cover), "make the cover for the housing plate, 3 mm aluminium")
    db.close()
    t = tc.text
    assert t.startswith("[Project context: this part (“Cover”) belongs to the project “Pump skid PS-1” with 2 other")
    assert "Purpose: Base plate, flange and cover of a small pump skid" in t
    assert "Project decisions (follow them unless this request says otherwise): All fasteners M6 ISO 4762" in t
    plate_line = ("- Housing plate (Aluminium 6061-T6): 120 × 80 × 10 mm; 4× Ø6.6 round, axis Z on 100 × 60 grid "
                  "centred (X0, Y0); params L=120 (Length), W=80 (Width), T=10 (Thickness)")
    assert plate_line in t
    assert "- Outlet flange (Carbon steel): 150 × 150 × 18 mm" in t and "6× Ø14 round, axis Z on Ø120 PCD" in t
    assert t.index("Housing plate (") < t.index("Outlet flange (")  # the order parts joined the project
    assert len(t) <= mctx.PROJECT_LIMIT + mctx.PREFS_LIMIT + 2 and tc.tokens_est <= 700
    view = c.get(f"/api/projects/{cover}/agent-context").json()
    assert view["in_use"] and view["project"]["name"] == "Pump skid PS-1"
    assert [p["name"] for p in view["parts"]] == ["Housing plate", "Outlet flange"]
    assert view["decisions"] == ["All fasteners M6 ISO 4762"]
    blob = json.dumps(view)
    assert not any(w in blob for w in INTERNAL)

    # token bound holds for a big project: 25 more parts, the overflow is named only
    for i in range(25):
        _part(c, f"Spacer {i:02d} with a deliberately long descriptive name for the bound", dp["id"])
    db, u = _ctx_for("brief@x.com")
    big = mctx.turn_context(db, u, db.get(Project, cover), "cover")
    db.close()
    assert len(big.text) <= mctx.PROJECT_LIMIT + mctx.PREFS_LIMIT + 2 and big.tokens_est <= 700
    assert "Housing plate (Aluminium 6061-T6)" in big.text and "Outlet flange (Carbon steel)" in big.text
    assert "Not built yet: Spacer 00 with" in big.text and big.text.endswith("only if the user asks.]")

    # the agent turn carries the brief once per conversation (replay client: zero model calls)
    reply = {"messages": [{"type": "system", "subtype": "init", "data": {}},
                          {"type": "assistant", "model": "replay", "content": [{"type": "text", "text": "Noted."}]},
                          {"type": "result", "subtype": "success", "num_turns": 1, "session_id": "rp-ctx",
                           "total_cost_usd": 0.0}]}
    cas = tmp_path / "cassette.json"
    cas.write_text(json.dumps({"turns": [{**reply, "match": r"Housing plate \(Aluminium 6061-T6\): 120 × 80 × 10 mm; "
                                                           r"4× Ø6\.6 round, axis Z on 100 × 60 grid"}, reply]}))
    monkeypatch.setenv("FW_AGENT_REPLAY", str(cas))

    async def no_recognition(parts: Any, timeout: float = 0) -> None:  # keep the face census (deterministic)
        return None

    monkeypatch.setattr("aicad.platform.routers.design_projects.refresh_recognition", no_recognition)
    from aicad.platform.routers.projects import _sessions

    r = c.post(f"/api/projects/{cover}/agent/chat", json={"prompt": "Make the cover for the housing plate. "
                                                                    "Always deburr outside edges 0.5 mm.",
                                                          "skip_brief": True, "mode": "discuss"})
    assert r.status_code == 200, r.text
    assert r.json()["remembered"] == [{"scope": "personal", "text": "Always deburr outside edges 0.5 mm"}]
    _wait(cover)
    s = _sessions[cover]
    first = s.client.prompts[0]
    assert "[Project context:" in first and "Housing plate (Aluminium 6061-T6)" in first
    assert "[Designer preferences" in first and "Always deburr outside edges 0.5 mm" in first
    user_ev = next(e for e in s.history if e["type"] == "user")
    assert "Project context" not in user_ev["text"] and "Designer preferences" not in user_ev["text"]
    assert s.last_prompt == "Make the cover for the housing plate. Always deburr outside edges 0.5 mm."
    c.post(f"/api/projects/{cover}/agent/chat", json={"prompt": "and the lid?", "mode": "discuss"})
    _wait(cover, n=2)
    assert "[Project context:" not in s.client.prompts[1]  # already in this conversation, unchanged


def _wait(pid: str, n: int = 1, timeout: float = 90) -> None:
    from aicad.platform.routers.projects import _sessions

    t0 = time.time()
    while time.time() - t0 < timeout:
        s = _sessions.get(pid)
        if s is not None and not s.busy and sum(e["type"] == "result" for e in s.history) >= n:
            return
        time.sleep(0.2)
    raise AssertionError("agent turn did not finish")


# ============================================================================= scoping and permissions
def test_project_scoping_permissions_and_private_parts(app_client: TestClient) -> None:  # noqa: F811
    owner = app_client
    signup(owner, "own@x.com", name="Olive Owner")
    eng = _member(owner, "own@x.com", "eng@x.com", "Eve Engineer", "engineer")
    eng2 = _member(owner, "own@x.com", "eng2@x.com", "Ed Engineer", "engineer")
    viewer = _member(owner, "own@x.com", "view@x.com", "Vi Viewer", "viewer")
    dp = eng.post("/api/design-projects", json={"name": "Gearbox"}).json()["id"]
    assert viewer.post("/api/design-projects", json={"name": "Nope"}).status_code == 403
    assert viewer.get(f"/api/design-projects/{dp}").status_code == 200  # viewers can look
    assert viewer.patch(f"/api/design-projects/{dp}", json={"notes": "x"}).status_code == 403
    secret, _ = _part(eng, "Secret housing", dp)
    assert eng.patch(f"/api/projects/{secret}/access", json={"general": "none"}).status_code == 200
    open_p, _ = _part(eng2, "Open shaft", dp)
    # the private part is invisible to others: not listed, not described to their agent
    assert [i["name"] for i in eng2.get(f"/api/design-projects/{dp}").json()["items"]] == ["Open shaft"]
    assert eng2.get(f"/api/design-projects/{dp}").json()["hidden_parts"] == 1
    assert [p["name"] for p in eng2.get(f"/api/projects/{open_p}/agent-context").json()["parts"]] == []
    assert [p["name"] for p in eng.get(f"/api/projects/{open_p}/agent-context").json()["parts"]] == ["Secret housing"]
    # moving a part needs edit access to it
    other, _ = _part(eng, "Eve's bracket")
    assert eng.patch(f"/api/projects/{other}/access", json={"general": "read"}).status_code == 200
    assert eng2.post(f"/api/design-projects/{dp}/parts", json={"part_id": other}).status_code == 403
    assert eng2.post(f"/api/design-projects/{dp}/parts", json={"part_id": secret}).status_code == 404
    assert eng.post(f"/api/design-projects/{dp}/parts", json={"part_id": other}).status_code == 200
    # a part belongs to at most one project: adding it elsewhere moves it
    dp2 = eng.post("/api/design-projects", json={"name": "Spares"}).json()["id"]
    assert eng.post(f"/api/design-projects/{dp2}/parts", json={"part_id": other}).status_code == 200
    db = session_factory()()
    assert db.get(DesignProjectPart, other).project_id == dp2  # type: ignore[union-attr]
    db.close()
    # deleting needs the creator or an admin, and never deletes parts
    assert eng2.delete(f"/api/design-projects/{dp2}").status_code == 403
    assert owner.delete(f"/api/design-projects/{dp2}").status_code == 200
    assert eng.get(f"/api/projects/{other}").json()["design_project"] is None
    # another workspace's project is never visible, even by id, and can't pull this workspace's parts in
    outsider = _member(owner, "own@x.com", "out@x.com", "Out", "engineer")
    db = session_factory()()
    o2 = Organization(name="Other Co", plan_code="trial", plan_status="trialing")
    db.add(o2)
    db.flush()
    foreign = DesignProject(org_id=o2.id, name="Theirs")
    db.add(foreign)
    db.commit()
    fid = foreign.id
    db.close()
    assert outsider.get(f"/api/design-projects/{fid}").status_code == 404
    assert outsider.post(f"/api/design-projects/{fid}/parts", json={"part_id": open_p}).status_code == 404


# ============================================================================= learning
def _rev(ws: Path, n: int, parent: int | None, kind: str, feats: list[dict[str, Any]], params: dict[str, float],
         age_s: float = 60) -> None:
    import os

    d = ws / "revisions" / str(n)
    d.mkdir(parents=True)
    src = f"L = {params['L']}\nT = {params['T']}\nresult = None\n"
    (d / "model.py").write_text(merge.write_manual(src, feats) if feats else src, encoding="utf-8")
    (d / "status.json").write_text(json.dumps({"build_id": n, "editable_params": params,
                                               "param_meta": {"T": {"label": "Thickness"}}}), encoding="utf-8")
    (d / "cause.json").write_text(json.dumps({"kind": kind, "parent": parent}), encoding="utf-8")
    t = time.time() - age_s
    os.utime(d / "status.json", (t, t))


FIL = {"id": "f1", "op": "fillet", "name": "Fillet", "r": 2.0, "edges": []}


def test_preferences_learned_from_a_recorded_sequence_of_edits(app_client: TestClient,  # noqa: F811
                                                               tmp_path: Path) -> None:
    c = app_client
    signup(c, "learn@x.com")
    org = _org_id("learn@x.com")
    db, u = _ctx_for("learn@x.com")
    ctx = SimpleNamespace(user=u, impersonating=False)
    parts = []
    for i in range(3):
        p = Project(org_id=org, name=f"GB-00{i + 1} Bracket", created_by=u.id,
                    last_status={"material": "Aluminium 6061-T6", "ok": True})
        db.add(p)
        db.flush()
        parts.append(p)
    db.commit()
    root = tmp_path / "ws"
    hole = {"id": "h1", "op": "hole", "name": "Hole", "d": 6.6, "spec": {"type": "cbore", "size": 6, "fit": "medium"},
            "point": [0, 0, 0], "normal": [0, 0, 1]}
    # each part: the agent builds (rev 1), then within minutes the person adds an R2 fillet by hand (rev 2)
    for i, p in enumerate(parts):
        ws = root / p.id
        _rev(ws, 1, None, "agent", [], {"L": 100, "T": 5})
        _rev(ws, 2, 1, "manual", [FIL], {"L": 100, "T": 5})
        learn.observe_revision(db, ctx, p, ws, 2)
        if i < 2:  # two parts also get an M6 counterbore later (not right after the agent)
            _rev(ws, 3, 2, "manual", [FIL, hole], {"L": 100, "T": 5}, age_s=60)
            learn.observe_revision(db, ctx, p, ws, 3)
    # one part: thickness raised by hand right after a second agent build
    ws = root / parts[0].id
    _rev(ws, 4, 3, "agent", [FIL, hole], {"L": 100, "T": 5})
    _rev(ws, 5, 4, "params", [FIL, hole], {"L": 100, "T": 6})
    learn.observe_revision(db, ctx, parts[0], ws, 5)
    db.commit()
    facts = {f.key: f for f in db.scalars(select(MemoryFact).where(MemoryFact.user_id == u.id))}
    assert facts["material"].text == "Usually specifies Aluminium 6061-T6" and facts["material"].evidence == 3
    assert facts["fillet_size"].text == "Typical hand fillet R2 mm" and facts["fillet_size"].evidence == 3
    assert facts["after:fillet"].text.startswith("Adds fillets (R2) by hand after the agent builds")
    assert facts["hole_std"].text == "Most-used hole: M6 counterbored"
    assert facts["hole_fit"].text == "Clearance holes in the medium fit (ISO 273)"
    assert facts["naming"].text.startswith("Names parts with a code and number first")
    assert "after:param:thickness" not in facts  # one occurrence is not a habit
    # rev 3 was made on top of a hand revision: its hole is a habit, not a correction of the agent
    assert all(e.data.get("what") != "hole" for e in db.scalars(select(MemoryEvent).where(
        MemoryEvent.kind == "after_agent")))
    block, shown = mctx.preferences_block(db, u, org, "add the mounting holes")
    assert block.startswith("[Designer preferences") and len(block) <= mctx.PREFS_LIMIT
    assert {"Most-used hole: M6 counterbored", "Clearance holes in the medium fit (ISO 273)"} <= set(shown)
    assert mctx.preferences_block(db, u, org, "add the mounting holes")[0] == block  # same facts, same block
    db.close()

    # the Memory panel: see, edit, pin, delete; deleted learned facts stay deleted
    mem = c.get("/api/memory").json()
    byk = {f["text"]: f for f in mem["facts"]}
    assert mem["learning"] and mem["use"] and "Typical hand fillet R2 mm" in byk
    assert not any(w in json.dumps(mem) for w in INTERNAL)
    fid = byk["Typical hand fillet R2 mm"]["id"]
    assert c.delete(f"/api/memory/facts/{fid}").status_code == 200
    after_id = byk[next(t for t in byk if t.startswith("Adds fillets"))]["id"]
    r = c.patch(f"/api/memory/facts/{after_id}", json={"text": "Put R2 fillets on all outside edges", "pinned": True})
    assert r.json()["origin"] == "user" and r.json()["pinned"]
    texts = [f["text"] for f in c.get("/api/memory").json()["facts"]]  # recomputes: tombstone + edit hold
    assert "Typical hand fillet R2 mm" not in texts and texts[0] == "Put R2 fillets on all outside edges"
    added = c.post("/api/memory/facts", json={"text": "Drawings to ISO 128, first-angle"}).json()
    assert added["origin"] == "user"
    # turning learning off records nothing; turning use off empties the block
    c.patch("/api/memory/settings", json={"learning": False})
    db, u = _ctx_for("learn@x.com")
    n0 = len(db.scalars(select(MemoryEvent)).all())
    learn.observe_revision(db, SimpleNamespace(user=u, impersonating=False), db.get(Project, parts[1].id),
                           root / parts[1].id, 2)
    assert learn.observe_prompt(db, SimpleNamespace(user=u, impersonating=False), db.get(Project, parts[1].id),
                                "Always use M5.", None) == []
    assert len(db.scalars(select(MemoryEvent)).all()) == n0
    db.close()
    c.patch("/api/memory/settings", json={"learning": True, "use": False})
    db, u = _ctx_for("learn@x.com")
    assert mctx.preferences_block(db, u, org)[0] == ""
    # an impersonating admin never trains the person's memory
    assert learn.may_learn(SimpleNamespace(user=u, impersonating=True)) is False
    db.close()
    # private: another person in the same workspace sees none of it
    other = _member(c, "learn@x.com", "peer@x.com", "Pat Peer", "engineer")
    assert other.get("/api/memory").json()["facts"] == []
    assert other.delete(f"/api/memory/facts/{added['id']}").status_code == 404
    # forget everything (this workspace)
    assert c.post("/api/memory/forget").status_code == 200
    assert c.get("/api/memory").json()["facts"] == []  # parts made before "forget" teach nothing


def test_share_a_preference_to_a_project_and_chat_decisions(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "share@x.com")
    dp = c.post("/api/design-projects", json={"name": "Frame"}).json()["id"]
    f = c.post("/api/memory/facts", json={"text": "Material 6061-T6 unless told otherwise"}).json()
    assert c.post(f"/api/memory/facts/{f['id']}/share", json={"project_id": dp}).status_code == 200
    c.post(f"/api/memory/facts/{f['id']}/share", json={"project_id": dp})  # idempotent
    page = c.get(f"/api/design-projects/{dp}").json()
    assert [(d["text"], d["source"]) for d in page["decisions"]] == [("Material 6061-T6 unless told otherwise", "memory")]
    # a decision captured from a chat on a part of the project
    pid, _ = _part(c, "Side rail", dp)
    db, u = _ctx_for("share@x.com")
    got = learn.observe_prompt(db, SimpleNamespace(user=u, impersonating=False), db.get(Project, pid),
                               "Make it 300 long. Across this project, tolerances to ISO 2768-m.", dp)
    db.commit()
    db.close()
    assert got == [{"scope": "project", "text": "Across this project, tolerances to ISO 2768-m"}]
    dec = c.get(f"/api/design-projects/{dp}").json()["decisions"]
    assert dec[-1]["source_label"] == "From a design chat on “Side rail”" and dec[-1]["category"] == "tolerance"
    assert c.delete(f"/api/design-projects/{dp}/decisions/{dec[-1]['id']}").status_code == 200


def test_design_office_program_maps_onto_a_project(app_client: TestClient) -> None:  # noqa: F811
    from aicad.office import store
    from aicad.platform.config import get_settings

    c = app_client
    signup(c, "office@x.com")
    org = _org_id("office@x.com")
    a, _ = _part(c, "Gear housing")
    b, _ = _part(c, "Input shaft")
    root = store.org_root(get_settings().data_dir, org)
    doc = {"id": store.new_id(), "org_id": org, "name": "Gearbox G-2", "brief": "Two-stage spur gearbox",
           "tickets": [{"id": "t1", "project_id": a}, {"id": "t2", "project_id": b}, {"id": "t3", "project_id": None}]}
    (root / doc["id"]).mkdir(parents=True)
    store.save(root, doc)
    items = c.get("/api/design-projects").json()["items"]
    assert [(i["name"], i["parts"], i["program_id"]) for i in items] == [("Gearbox G-2", 2, doc["id"])]
    page = c.get(f"/api/design-projects/{items[0]['id']}").json()
    assert page["program"]["name"] == "Gearbox G-2" and page["purpose"] == "Two-stage spur gearbox"
    assert len(c.get("/api/design-projects").json()["items"]) == 1  # mapped once
