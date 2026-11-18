"""Collaboration: teams, permissions, sharing, share links, presence, comments, branches and merge requests.

No live agent calls: the design-agent reconcile step is replaced by a fake; builds are real (mounting-plate demo).
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_platform import _link_token, _project_with_model, app_client, signup  # noqa: F401  (fixture re-export)

from aicad.platform.collab import merge
from aicad.platform.db import session_factory, utcnow
from aicad.platform.models import Membership, Organization, User

DEMO = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo" / "mounting_plate.py"


# ----------------------------------------------------------------------------- helpers
def _client(app: Any, like: TestClient | None = None) -> TestClient:
    """Another person's browser on the same server (same event loop as `like`, so background builds are shared)."""
    c = TestClient(app)
    c.headers.update({"X-FW-CSRF": "1"})
    if like is not None:
        c.portal = like.portal
    return c


def _org_id(email: str) -> str:
    db = session_factory()()
    try:
        u = db.scalar(select(User).where(User.email == email))
        return db.scalar(select(Membership.org_id).where(Membership.user_id == u.id))  # type: ignore[union-attr,return-value]
    finally:
        db.close()


def _member(owner: TestClient, owner_email: str, email: str, name: str, role: str) -> TestClient:
    """A second person in the owner's workspace, signed in on their own client."""
    c = _client(owner.app, owner)
    signup(c, email, name=name, workspace=None)
    db = session_factory()()
    try:
        u = db.scalar(select(User).where(User.email == email))
        org = _org_id(owner_email)
        db.add(Membership(user_id=u.id, org_id=org, role=role))  # type: ignore[union-attr]
        u.default_org_id, u.onboarding_completed_at = org, utcnow()  # type: ignore[union-attr]
        db.commit()
    finally:
        db.close()
    return c


def _uid(email: str) -> str:
    db = session_factory()()
    try:
        return db.scalar(select(User.id).where(User.email == email))  # type: ignore[return-value]
    finally:
        db.close()


# ============================================================================= merge engine (pure)
BASE = '''NAME = "Plate"
L = 120.0
W = 80.0
T = 10.0
part = box(L, W, T)
part = fillet(part, 2)
'''


def _with(src: str, feats: list[dict[str, Any]]) -> str:
    return merge.write_manual(src, feats)


def test_merge3_lines_and_conflicts() -> None:
    base = ["a", "b", "c", "d"]
    chunks = merge.merge3(base, ["a", "B", "c", "d"], ["a", "b", "c", "D"])
    assert [c["kind"] for c in chunks if c["kind"] != "same"] == ["ours", "theirs"]
    chunks = merge.merge3(base, ["a", "X", "c", "d"], ["a", "Y", "c", "d"])
    assert next(c for c in chunks if c["kind"] == "conflict")["ours"] == ["X"]
    assert all(c["kind"] == "same" or c["kind"] == "both" for c in merge.merge3(base, ["a", "Q"], ["a", "Q"]))


def test_adjacent_parameter_edits_merge_without_conflict() -> None:
    ours = BASE.replace("L = 120.0", "L = 150.0")  # main: length
    theirs = BASE.replace("W = 80.0", "W = 90.0")  # branch: width, on the very next line
    r = merge.merge_model(BASE, ours, theirs)
    assert r["conflicts"] == [] and r["source"] is not None
    assert merge.read_params(r["source"]) == {"L": 150.0, "W": 90.0, "T": 10.0}


def test_parameter_conflict_and_resolutions() -> None:
    ours, theirs = BASE.replace("T = 10.0", "T = 8.0"), BASE.replace("T = 10.0", "T = 12.0")
    r = merge.merge_model(BASE, ours, theirs)
    assert r["source"] is None and [c["id"] for c in r["conflicts"]] == ["param:T"]
    assert merge.read_params(merge.merge_model(BASE, ours, theirs, {"param:T": "theirs"})["source"])["T"] == 12.0
    assert merge.read_params(merge.merge_model(BASE, ours, theirs, {"param:T": "ours"})["source"])["T"] == 8.0
    assert merge.read_params(merge.merge_model(BASE, ours, theirs, {"param:T": {"value": 9.5}})["source"])["T"] == 9.5


def test_manual_features_three_way() -> None:
    f1 = {"id": "f1", "op": "fillet", "name": "Fillet1", "radius": 1.0}
    f2 = {"id": "f2", "op": "chamfer", "name": "Chamfer1", "distance": 0.5}
    f3 = {"id": "f3", "op": "hole", "name": "Hole1", "diameter": 6.0}
    base = _with(BASE, [f1, f2])
    ours = _with(BASE, [{**f1, "radius": 2.0}, f2])  # main edits f1
    theirs = _with(BASE, [f1, f3])  # branch deletes f2 and adds f3
    r = merge.merge_model(base, ours, theirs)
    assert r["conflicts"] == []
    feats = merge.read_manual(r["source"])
    assert [f["id"] for f in feats] == ["f1", "f3"] and feats[0]["radius"] == 2.0
    # edited on both sides -> conflict; edited vs deleted -> conflict
    r = merge.merge_model(base, _with(BASE, [{**f1, "radius": 3.0}, f2]), _with(BASE, [{**f1, "radius": 4.0}]))
    assert sorted(c["id"] for c in r["conflicts"]) == ["feature:f1"]
    r = merge.merge_model(base, _with(BASE, [f1, {**f2, "distance": 1.0}]), _with(BASE, [f1]))
    assert [c["id"] for c in r["conflicts"]] == ["feature:f2"]
    out = merge.merge_model(base, _with(BASE, [f1, {**f2, "distance": 1.0}]), _with(BASE, [f1]),
                            {"feature:f2": "theirs"})["source"]
    assert [f["id"] for f in merge.read_manual(out)] == ["f1"]


def test_source_conflict_detected_and_resolved() -> None:
    ours = BASE.replace("fillet(part, 2)", "fillet(part, 3)")
    theirs = BASE.replace("fillet(part, 2)", "chamfer(part, 1)")
    r = merge.merge_model(BASE, ours, theirs)
    assert [c["kind"] for c in r["conflicts"]] == ["source"] and "chamfer" in r["conflicts"][0]["theirs"]
    assert "chamfer(part, 1)" in merge.merge_model(BASE, ours, theirs, {"source:1": "theirs"})["source"]
    assert "fillet(part, 3)" in merge.merge_model(BASE, ours, theirs, {"source:1": "ours"})["source"]
    txt = merge.merge_model(BASE, ours, theirs, {"source:1": {"text": "part = chamfer(fillet(part, 3), 1)"}})["source"]
    assert "chamfer(fillet(part, 3), 1)" in txt


def test_write_manual_matches_the_studio() -> None:
    from aicad.platform.routers.studio import read_manual, write_manual

    feats = [{"id": "a1", "op": "fillet", "name": "Fillet1", "radius": 1.0}]
    assert merge.write_manual(BASE, feats) == write_manual(BASE, feats)
    assert merge.read_manual(write_manual(BASE, feats)) == read_manual(write_manual(BASE, feats)) == feats


# ============================================================================= additive migration
def test_existing_database_gains_collab_tables_and_keeps_working(tmp_path: Path,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """A database made before collaboration (no new tables) upgrades in place; its projects behave as before."""
    from sqlalchemy import create_engine, inspect

    from aicad.platform import config
    from aicad.platform.collab import tables as ct
    from aicad.platform.db import Base
    from aicad.platform.models import Project
    from aicad.platform.security import hash_password

    url = f"sqlite:///{(tmp_path / 'old.sqlite').as_posix()}"
    eng = create_engine(url)
    new = {t.name for t in Base.metadata.sorted_tables if t.name in {m.__tablename__ for m in (
        ct.Team, ct.TeamMember, ct.ProjectAccess, ct.ProjectGrant, ct.GuestInvite, ct.ShareLink, ct.Comment,
        ct.Branch, ct.MergeRequest, ct.Review, ct.Tag)}}
    Base.metadata.create_all(eng, tables=[t for t in Base.metadata.sorted_tables if t.name not in new])
    with eng.begin() as cx:
        assert not new & set(inspect(cx).get_table_names())
    from sqlalchemy.orm import Session

    with Session(eng) as db:
        u = User(email="old@x.com", name="Old Timer", password_hash=hash_password("correct horse 42"),
                 email_verified_at=utcnow(), onboarding_completed_at=utcnow())
        o = Organization(name="Old Co", plan_code="trial", plan_status="trialing",
                         trial_ends_at=utcnow() + timedelta(days=10))
        db.add_all([u, o])
        db.flush()
        e = User(email="eng@x.com", name="Eng", password_hash=hash_password("correct horse 42"),
                 email_verified_at=utcnow(), onboarding_completed_at=utcnow(), default_org_id=o.id)
        db.add(e)
        db.flush()
        u.default_org_id = o.id
        db.add_all([Membership(user_id=u.id, org_id=o.id, role="owner"),
                    Membership(user_id=e.id, org_id=o.id, role="engineer")])
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
            assert new <= set(inspect(cx).get_table_names())  # created on start-up, nothing else touched
        eng2.dispose()
        assert c.post("/api/auth/login", json={"email": "eng@x.com", "password": "correct horse 42"}).status_code == 200
        items = c.get("/api/projects").json()["items"]
        assert [i["name"] for i in items] == ["Legacy bracket"] and items[0]["access"]["level"] == "edit"
        pid = items[0]["id"]
        assert c.patch(f"/api/projects/{pid}", json={"name": "Legacy bracket 2"}).status_code == 200
        br = c.get(f"/api/projects/{pid}/branches").json()
        assert br["current"] == "main" and [b["id"] for b in br["items"]] == ["main"]


# ============================================================================= teams
def test_team_crud_and_roles(app_client: TestClient) -> None:  # noqa: F811
    owner = app_client
    signup(owner, "own@x.com", name="Olga Owner")
    eng = _member(owner, "own@x.com", "eng@x.com", "Ed Engineer", "engineer")
    view = _member(owner, "own@x.com", "view@x.com", "Vic Viewer", "viewer")
    assert view.post("/api/teams", json={"name": "Nope"}).status_code == 403
    tid = eng.post("/api/teams", json={"name": "Gearbox", "description": "Drivetrain parts", "color": "#059669"}).json()["id"]
    assert eng.post("/api/teams", json={"name": "Gearbox"}).status_code == 409
    teams = owner.get("/api/teams").json()
    t = teams["items"][0]
    assert t["name"] == "Gearbox" and t["color"] == "#059669" and t["members"][0]["role"] == "admin"
    assert len(teams["members"]) == 3 and t["can_manage"] is True  # workspace owner manages every team
    # the team admin (eng) adds the viewer; the viewer can't manage
    assert eng.post(f"/api/teams/{tid}/members", json={"user_id": _uid("view@x.com"), "role": "editor"}).status_code == 200
    assert view.post(f"/api/teams/{tid}/members", json={"user_id": _uid("own@x.com")}).status_code == 403
    assert eng.post(f"/api/teams/{tid}/members", json={"user_id": "nobody", "role": "editor"}).status_code == 422
    assert eng.patch(f"/api/teams/{tid}/members/{_uid('view@x.com')}", json={"role": "boss"}).status_code == 422
    assert eng.patch(f"/api/teams/{tid}/members/{_uid('eng@x.com')}", json={"role": "editor"}).status_code == 409  # last admin
    assert view.delete(f"/api/teams/{tid}/members/{_uid('view@x.com')}").status_code == 200  # leave
    assert eng.patch(f"/api/teams/{tid}", json={"name": "Drivetrain"}).status_code == 200
    assert owner.get("/api/teams").json()["items"][0]["name"] == "Drivetrain"
    assert view.delete(f"/api/teams/{tid}").status_code == 403
    assert eng.delete(f"/api/teams/{tid}").status_code == 200
    assert owner.get("/api/teams").json()["items"] == []


# ============================================================================= permission matrix
def test_permission_matrix(app_client: TestClient) -> None:  # noqa: F811
    """Workspace roles x team roles x grants x guests x share links, on representative endpoints."""
    owner = app_client
    signup(owner, "own@x.com", name="Olga Owner")
    adm = _member(owner, "own@x.com", "adm@x.com", "Ada Admin", "admin")
    eng = _member(owner, "own@x.com", "eng@x.com", "Ed Engineer", "engineer")
    eng2 = _member(owner, "own@x.com", "eng2@x.com", "Erin Engineer", "engineer")
    view = _member(owner, "own@x.com", "view@x.com", "Vic Viewer", "viewer")
    tid = owner.post("/api/teams", json={"name": "Chassis"}).json()["id"]
    owner.post(f"/api/teams/{tid}/members", json={"user_id": _uid("eng2@x.com"), "role": "editor"})
    owner.post(f"/api/teams/{tid}/members", json={"user_id": _uid("view@x.com"), "role": "admin"})

    open_p = eng.post("/api/projects", json={"name": "Open part"}).json()["id"]  # workspace default (edit)
    team_p = owner.post("/api/projects", json={"name": "Team part"}).json()["id"]
    assert owner.patch(f"/api/projects/{team_p}/access", json={"team_id": tid}).json()["general"] == "read"
    priv_p = eng.post("/api/projects", json={"name": "Private part"}).json()["id"]
    assert eng.patch(f"/api/projects/{priv_p}/access", json={"general": "none"}).status_code == 200

    def level(c: TestClient, pid: str) -> str:
        r = c.get(f"/api/projects/{pid}")
        return r.json()["access"]["level"] if r.status_code == 200 else str(r.status_code)

    expect = {  # (client, project) -> effective level
        (owner, open_p): "admin", (adm, open_p): "admin", (eng, open_p): "admin",  # eng created it
        (eng2, open_p): "edit", (view, open_p): "read",
        (owner, team_p): "admin", (eng, team_p): "read", (eng2, team_p): "edit",  # team editor
        (view, team_p): "comment",  # team admin, but viewers are capped at comment
        (owner, priv_p): "admin", (adm, priv_p): "admin", (eng, priv_p): "admin", (eng2, priv_p): "404",
        (view, priv_p): "404",
    }
    for (c, pid), lv in expect.items():
        assert level(c, pid) == lv, (c, pid, lv)
    # list shows only readable projects
    assert {i["name"] for i in eng2.get("/api/projects").json()["items"]} == {"Open part", "Team part"}
    assert {i["name"] for i in owner.get("/api/projects").json()["items"]} == {"Open part", "Team part", "Private part"}
    # read endpoints need read, edits need edit, delete/share need admin
    assert eng.get(f"/api/projects/{team_p}/revisions").status_code == 200
    assert eng.patch(f"/api/projects/{team_p}", json={"name": "x"}).status_code == 403
    assert eng2.patch(f"/api/projects/{team_p}", json={"name": "Team part"}).status_code == 200
    assert view.patch(f"/api/projects/{open_p}", json={"name": "x"}).status_code == 403
    assert view.post(f"/api/projects/{open_p}/params", json={"values": {"L": 1}}).status_code == 403
    assert eng2.delete(f"/api/projects/{open_p}").status_code == 403
    assert eng2.post(f"/api/projects/{open_p}/share-links", json={}).status_code == 403
    assert eng2.post(f"/api/projects/{open_p}/agent/chat", json={"prompt": "hi"}).status_code != 403
    assert eng.post(f"/api/projects/{team_p}/agent/chat", json={"prompt": "hi"}).status_code == 403
    assert eng2.get(f"/api/projects/{priv_p}/files/status.json").status_code == 404
    # explicit grants raise access (person and team); viewers stay capped
    eng_id = _uid("eng2@x.com")
    g = eng.post(f"/api/projects/{priv_p}/grants", json={"subject_type": "user", "subject_id": eng_id, "level": "comment"})
    assert g.status_code == 200 and level(eng2, priv_p) == "comment"
    assert eng.post(f"/api/projects/{priv_p}/grants", json={"subject_type": "team", "subject_id": tid,
                                                             "level": "edit"}).status_code == 200
    assert level(eng2, priv_p) == "edit" and level(view, priv_p) == "comment"
    assert eng2.post(f"/api/projects/{priv_p}/grants", json={"subject_type": "user", "subject_id": eng_id,
                                                              "level": "edit"}).status_code == 403
    assert eng.post(f"/api/projects/{priv_p}/grants", json={"subject_type": "user", "subject_id": "outsider",
                                                             "level": "read"}).status_code == 422
    assert eng.post(f"/api/projects/{priv_p}/grants", json={"subject_type": "team", "subject_id": tid,
                                                             "level": "admin"}).status_code == 422
    shared = eng2.get("/api/shared-with-me").json()["items"]
    assert [s["name"] for s in shared] == ["Private part"]
    # revoking removes access again
    acc = eng.get(f"/api/projects/{priv_p}/access").json()
    for gr in acc["grants"]:
        assert eng.delete(f"/api/projects/{priv_p}/grants/{gr['id']}").status_code == 200
    assert level(eng2, priv_p) == "404"
    # permission changes are audited
    from aicad.platform.models import AuditLog

    db = session_factory()()
    try:
        acts = {a.action for a in db.scalars(select(AuditLog).where(AuditLog.target == priv_p))}
    finally:
        db.close()
    assert {"access.changed", "access.granted", "access.revoked"} <= acts


def test_guest_invite_link_and_expiry(app_client: TestClient) -> None:  # noqa: F811
    owner = app_client
    signup(owner, "own@x.com", name="Olga Owner")
    pid = owner.post("/api/projects", json={"name": "Shared bracket"}).json()["id"]
    other = owner.post("/api/projects", json={"name": "Not shared"}).json()["id"]
    # a guest by email: no seat, only this project
    seats = owner.get("/api/auth/me").json()["org"]["seats_used"]
    assert owner.post(f"/api/projects/{pid}/guests", json={"email": "gus@client.com", "level": "comment"}).json()["invited"]
    assert owner.get(f"/api/projects/{pid}/access").json()["pending_guests"][0]["email"] == "gus@client.com"
    assert owner.get("/api/team").json()["invites"] == []  # guest invites aren't workspace invites
    tok = _link_token("gus@client.com", "shared Shared bracket")
    guest = _client(owner.app)
    guest.post("/api/auth/signup", json={"name": "Gus Guest", "email": "gus@client.com", "password": "correct horse 42"})
    me = guest.post("/api/team/invites/accept", json={"token": tok}).json()
    assert me["project_id"] == pid and me["next_step"] == "app" and me["org"] is None
    assert owner.get("/api/auth/me").json()["org"]["seats_used"] == seats
    r = guest.get(f"/api/projects/{pid}").json()
    assert r["access"]["level"] == "comment" and r["access"]["guest"] and r["agent"]["allowed"] is False
    assert guest.get(f"/api/projects/{other}").status_code == 404
    assert guest.patch(f"/api/projects/{pid}", json={"name": "x"}).status_code == 403
    assert guest.post(f"/api/projects/{pid}/comments", json={"body": "Looks good"}).status_code == 200
    assert [s["id"] for s in guest.get("/api/shared-with-me").json()["items"]] == [pid]
    # even with edit, a guest never runs the agent nor copies the project into the workspace
    gr = next(g for g in owner.get(f"/api/projects/{pid}/access").json()["grants"] if g["guest"])
    owner.patch(f"/api/projects/{pid}/grants/{gr['id']}", json={"level": "edit"})
    assert guest.get(f"/api/projects/{pid}").json()["access"]["can_edit"] is True
    assert guest.post(f"/api/projects/{pid}/agent/chat", json={"prompt": "make it"}).status_code == 403
    assert guest.post(f"/api/projects/{pid}/duplicate", json={}).status_code == 403

    # read-only share link: opens without signing in; every write is refused; revocable; optional expiry
    link = owner.post(f"/api/projects/{pid}/share-links", json={"label": "Supplier"}).json()
    anon = _client(owner.app)
    v = anon.get(f"/api/share/{link['token']}")
    assert v.status_code == 200 and v.json()["read_only"] and v.json()["project"]["name"] == "Shared bracket"
    assert anon.get(f"/api/share/{link['token']}x").status_code == 404  # signature checked
    assert anon.post(f"/api/share/{link['token']}/params", json={}).status_code == 403
    assert anon.patch(f"/api/projects/{pid}", json={"name": "x"}).status_code == 401
    assert anon.get(f"/api/projects/{pid}").status_code == 401
    assert owner.get(f"/api/projects/{pid}/access").json()["links"][0]["uses"] == 1
    assert owner.delete(f"/api/projects/{pid}/share-links/{link['id']}").status_code == 200
    assert anon.get(f"/api/share/{link['token']}").status_code == 404
    short = owner.post(f"/api/projects/{pid}/share-links", json={"expires_days": 1}).json()
    assert anon.get(f"/api/share/{short['token']}").status_code == 200
    from aicad.platform.collab.tables import ShareLink

    db = session_factory()()
    try:
        db.get(ShareLink, short["id"]).expires_at = utcnow() - timedelta(minutes=1)  # type: ignore[union-attr]
        db.commit()
    finally:
        db.close()
    assert anon.get(f"/api/share/{short['token']}").status_code == 410


def test_presence_comments_mentions_activity(app_client: TestClient) -> None:  # noqa: F811
    owner = app_client
    signup(owner, "own@x.com", name="Olga Owner")
    ada = _member(owner, "own@x.com", "ada@x.com", "Ada Lovelace", "engineer")
    pid = owner.post("/api/projects", json={"name": "Gear housing"}).json()["id"]
    owner.post(f"/api/projects/{pid}/presence")
    snap = ada.post(f"/api/projects/{pid}/presence").json()
    assert {u["name"] for u in snap["users"]} == {"Olga Owner", "Ada Lovelace"}
    body = ada.get(f"/api/projects/{pid}/presence/stream?once=1").text
    evs = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert evs[0]["type"] == "presence" and any(u["name"] == "Ada Lovelace" for u in evs[0]["users"])
    # comments with an @mention notify; activity lists what happened
    r = owner.post(f"/api/projects/{pid}/comments", json={"body": "@Ada can you check the wall thickness?"})
    assert r.status_code == 200 and r.json()["mentions"] == [_uid("ada@x.com")]
    notes = ada.get("/api/notifications").json()
    assert any("mentioned you" in n["title"] for n in notes.get("items", notes if isinstance(notes, list) else []))
    reply = ada.post(f"/api/projects/{pid}/comments", json={"body": "On it", "parent_id": r.json()["id"]}).json()
    assert reply["parent_id"] == r.json()["id"]
    cs = owner.get(f"/api/projects/{pid}/comments").json()
    assert [c["body"] for c in cs["items"]] == ["@Ada can you check the wall thickness?", "On it"]
    assert {p["name"] for p in cs["people"]} == {"Olga Owner", "Ada Lovelace"}
    assert ada.delete(f"/api/projects/{pid}/comments/{r.json()['id']}").status_code == 403
    assert owner.patch(f"/api/projects/{pid}/comments/{r.json()['id']}", json={"resolved": True}).status_code == 200
    acts = owner.get(f"/api/projects/{pid}/activity").json()["items"]
    assert [a["kind"] for a in acts][:2] == ["comment.added", "comment.added"] and acts[-1]["kind"] == "project.created"
    st = owner.get(f"/api/projects/{pid}/collab").json()
    assert st["branch"]["id"] == "main" and st["comments"] == 1


# ============================================================================= branches and merge requests
def _set_session_busy(pid: str, branch: str, user_id: str, name: str, busy: bool) -> None:
    from aicad.platform.routers.projects import _sessions

    key = pid if branch == "main" else f"{pid}@{branch}"

    class Fake:
        pass

    if busy:
        s = Fake()
        s.busy, s.driver, s.driver_name, s.history = True, user_id, name, []  # type: ignore[attr-defined]
        dict.__setitem__(_sessions, key, s)
    else:
        dict.pop(_sessions, key, None)


def _main_src(ws: Path) -> str:
    return (ws / "model.py").read_text(encoding="utf-8")


def test_branch_isolation_fast_forward_three_way_and_refusal(app_client: TestClient) -> None:  # noqa: F811
    owner = app_client
    signup(owner, "own@x.com", name="Olga Owner")
    ada = _member(owner, "own@x.com", "ada@x.com", "Ada Lovelace", "engineer")
    pid, ws = _project_with_model(owner, DEMO.read_text(encoding="utf-8"))
    assert owner.post(f"/api/projects/{pid}/params", json={"values": {"CH": 1.5}}).status_code == 200  # main r1

    # soft edit lock: Olga's agent run on main blocks Ada's edits on main, not a branch of her own
    _set_session_busy(pid, "main", _uid("own@x.com"), "Olga Owner", True)
    r = ada.post(f"/api/projects/{pid}/params", json={"values": {"L": 130}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "edit_locked"
    assert "Olga Owner is editing main" in r.json()["detail"]["message"]
    locks = ada.get(f"/api/projects/{pid}/collab").json()["locks"]
    assert locks[0]["name"] == "Olga Owner" and locks[0]["branch"] == "main"
    b = ada.post(f"/api/projects/{pid}/branches", json={"name": "wider plate"})
    assert b.status_code == 200, b.text
    bid = b.json()["id"]
    _set_session_busy(pid, "main", "", "", False)

    # Ada is now on her branch (cookie); Olga stays on main
    assert ada.get(f"/api/projects/{pid}/branches").json()["current"] == bid
    assert owner.get(f"/api/projects/{pid}/branches").json()["current"] == "main"
    r = ada.post(f"/api/projects/{pid}/params", json={"values": {"W": 90}})
    assert r.status_code == 200, r.text
    assert "W = 90.0" not in _main_src(ws)  # main untouched
    bws = ws.parent / f"{ws.name}.branches" / bid
    assert "W = 90.0" in _main_src(bws) and "CH = 1.5" in _main_src(bws)
    assert owner.get(f"/api/projects/{pid}/files/status.json").json()["fingerprint"]["bbox"][1] == 80.0
    assert ada.get(f"/api/projects/{pid}/files/status.json").json()["fingerprint"]["bbox"][1] == 90.0
    main_revs = [x["n"] for x in owner.get(f"/api/projects/{pid}/revisions").json()["items"]]
    br_revs = ada.get(f"/api/projects/{pid}/revisions").json()["items"]
    assert main_revs == [1] and [x["kind"] for x in br_revs] == ["params", "branch"]
    acts = owner.get(f"/api/projects/{pid}/activity").json()["items"]
    assert any(a["kind"] == "project.params_edited" and a["branch"] == "wider plate" for a in acts)

    # merge request: fast-forward (main hasn't moved)
    mr = ada.post(f"/api/projects/{pid}/merge-requests", json={"branch_id": bid, "title": "Widen to 90"}).json()
    st = owner.get(f"/api/projects/{pid}/merge-requests/{mr['id']}").json()
    assert st["fast_forward"] and st["conflicts"] == [] and st["can_merge"] and st["checks"]["ok"]
    assert st["params"]["branch"] == {"W": {"from": 80.0, "to": 90.0}}
    cmp = owner.post(f"/api/projects/{pid}/merge-requests/{mr['id']}/compare")
    assert cmp.status_code == 200 and cmp.json()["added_mm3"] > 0
    m = owner.post(f"/api/projects/{pid}/merge-requests/{mr['id']}/merge", json={})
    assert m.status_code == 200 and m.json()["fast_forward"] is True
    assert "W = 90.0" in _main_src(ws)
    assert owner.get(f"/api/projects/{pid}/revisions").json()["items"][0]["kind"] == "merge"
    assert ada.get(f"/api/projects/{pid}/merge-requests/{mr['id']}").json()["status"] == "merged"

    # 3-way: main changes L while a branch changes T -> both kept
    owner_b = owner.post(f"/api/projects/{pid}/branches", json={"name": "thinner", "switch": False}).json()["id"]
    assert owner.post(f"/api/projects/{pid}/params", json={"values": {"L": 140}}).status_code == 200  # on main
    assert owner.post(f"/api/projects/{pid}/branches/{owner_b}/checkout").status_code == 200
    assert owner.post(f"/api/projects/{pid}/params", json={"values": {"T": 8}}).status_code == 200  # on branch
    mr2 = owner.post(f"/api/projects/{pid}/merge-requests", json={"branch_id": owner_b, "title": "Thinner"}).json()
    st = owner.get(f"/api/projects/{pid}/merge-requests/{mr2['id']}").json()
    assert not st["fast_forward"] and st["conflicts"] == [] and st["params"]["main"] == {"L": {"from": 120.0, "to": 140.0}}
    m = owner.post(f"/api/projects/{pid}/merge-requests/{mr2['id']}/merge", json={})
    assert m.status_code == 200, m.text
    src = _main_src(ws)
    assert "L = 140.0" in src and "T = 8.0" in src and "W = 90.0" in src
    assert owner.get(f"/api/projects/{pid}/branches").json()["current"] == "main"  # merging switched back

    # refused: each side builds, the combination doesn't (pocket deeper than the plate)
    bad = owner.post(f"/api/projects/{pid}/branches", json={"name": "deep pocket", "switch": True}).json()["id"]
    assert owner.post(f"/api/projects/{pid}/params", json={"values": {"PD": 7}}).status_code == 200  # 7 < T 8
    owner.post(f"/api/projects/{pid}/branches/main/checkout")
    assert owner.post(f"/api/projects/{pid}/params", json={"values": {"T": 6}}).status_code == 200  # 4 < 6
    before = _main_src(ws)
    mr3 = owner.post(f"/api/projects/{pid}/merge-requests", json={"branch_id": bad, "title": "Deeper"}).json()
    m = owner.post(f"/api/projects/{pid}/merge-requests/{mr3['id']}/merge", json={})
    assert m.status_code == 422 and m.json()["detail"]["code"] == "checks_failed"
    assert "Main was not changed" in m.json()["detail"]["message"]
    assert _main_src(ws) == before and owner.get(f"/api/projects/{pid}/files/status.json").json()["ok"]


def test_conflicts_reconcile_and_protected_main(app_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from aicad.platform.collab import reconcile

    owner = app_client
    signup(owner, "own@x.com", name="Olga Owner")
    ada = _member(owner, "own@x.com", "ada@x.com", "Ada Lovelace", "engineer")
    bob = _member(owner, "own@x.com", "bob@x.com", "Bob Builder", "engineer")
    pid, ws = _project_with_model(owner, DEMO.read_text(encoding="utf-8"))
    assert owner.patch(f"/api/projects/{pid}/access", json={"protected_main": True}).status_code == 200
    # protected main: engineers can't change main directly, but can branch
    r = ada.post(f"/api/projects/{pid}/params", json={"values": {"L": 130}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "protected_main"
    bid = ada.post(f"/api/projects/{pid}/branches", json={"name": "ada/thicker"}).json()["id"]
    assert ada.post(f"/api/projects/{pid}/params", json={"values": {"T": 12}}).status_code == 200
    # meanwhile the owner (project admin) changes the same parameter on main
    assert owner.post(f"/api/projects/{pid}/params", json={"values": {"T": 11}}).status_code == 200
    mr = ada.post(f"/api/projects/{pid}/merge-requests", json={"branch_id": bid, "title": "Thicker plate",
                                                              "description": "Stiffer"}).json()
    st = ada.get(f"/api/projects/{pid}/merge-requests/{mr['id']}").json()
    assert [c["id"] for c in st["conflicts"]] == ["param:T"] and st["conflicts"][0]["label"] == "Thickness"
    assert not st["can_merge"] and "approval" in " ".join(st["blockers"])
    assert ada.post(f"/api/projects/{pid}/merge-requests/{mr['id']}/reviews", json={"state": "approve"}).status_code == 403
    assert bob.post(f"/api/projects/{pid}/merge-requests/{mr['id']}/reviews",
                    json={"state": "request_changes", "body": "@Ada why 12?"}).status_code == 200
    assert "A reviewer requested changes." in ada.get(f"/api/projects/{pid}/merge-requests/{mr['id']}").json()["blockers"]
    assert bob.post(f"/api/projects/{pid}/merge-requests/{mr['id']}/reviews", json={"state": "approve"}).status_code == 200
    st = ada.get(f"/api/projects/{pid}/merge-requests/{mr['id']}").json()
    assert st["approvals"] == 1 and st["can_merge"]
    # unresolved conflict -> 409 with the conflict; the design agent (fake) proposes 11.5, metered in tokens
    m = ada.post(f"/api/projects/{pid}/merge-requests/{mr['id']}/merge", json={})
    assert m.status_code == 409 and m.json()["detail"]["code"] == "conflicts"
    calls: list[Any] = []

    async def fake_propose(folder: Path, conflicts: list[dict[str, Any]], context: dict[str, Any],
                           budget_usd: float | None = None) -> tuple[dict[str, Any], float]:
        calls.append(conflicts)
        return {"resolutions": {"param:T": {"value": 11.5}}, "note": "Kept the thicker plate, halfway."}, 0.05

    monkeypatch.setattr(reconcile, "propose", fake_propose)
    tokens_before = owner.get("/api/auth/me").json()["org"]["token_balance"]
    rc = ada.post(f"/api/projects/{pid}/merge-requests/{mr['id']}/reconcile").json()
    assert rc["ids"] == ["param:T"] and rc["tokens"] > 0 and calls[0][0]["key"] == "T"
    assert owner.get("/api/auth/me").json()["org"]["token_balance"] == tokens_before - rc["tokens"]
    m = ada.post(f"/api/projects/{pid}/merge-requests/{mr['id']}/merge", json={"resolutions": {"param:T": "agent"}})
    assert m.status_code == 200, m.text
    assert "T = 11.5" in _main_src(ws)
    assert ada.post(f"/api/projects/{pid}/merge-requests/{mr['id']}/merge", json={}).status_code == 409  # merged

    # a design-source conflict (both sides rename the part) is detected and resolved by picking a side
    b2 = owner.post(f"/api/projects/{pid}/branches", json={"name": "rename"}).json()["id"]
    bws = ws.parent / f"{ws.name}.branches" / b2
    (bws / "model.py").write_text(_main_src(bws).replace('NAME = "Mounting plate"', 'NAME = "Base plate"'),
                                  encoding="utf-8")
    (ws / "model.py").write_text(_main_src(ws).replace('NAME = "Mounting plate"', 'NAME = "Main plate"'),
                                 encoding="utf-8")
    mr2 = owner.post(f"/api/projects/{pid}/merge-requests", json={"branch_id": b2, "title": "Rename"}).json()
    bob.post(f"/api/projects/{pid}/merge-requests/{mr2['id']}/reviews", json={"state": "approve"})
    st = owner.get(f"/api/projects/{pid}/merge-requests/{mr2['id']}").json()
    src_conf = [c for c in st["conflicts"] if c["kind"] == "source"]
    assert len(src_conf) == 1 and "code" not in src_conf[0]  # the script stays internal (superadmins only)
    m = owner.post(f"/api/projects/{pid}/merge-requests/{mr2['id']}/merge",
                   json={"resolutions": {src_conf[0]["id"]: "theirs"}})
    assert m.status_code == 200, m.text
    assert 'NAME = "Base plate"' in _main_src(ws)
    # tags mark main's revisions (releases)
    t = owner.post(f"/api/projects/{pid}/tags", json={"name": "v1.0", "note": "First release"}).json()
    assert t["revision"] == m.json()["revision"]
    assert owner.get(f"/api/projects/{pid}/tags").json()["items"][0]["name"] == "v1.0"
    assert ada.delete(f"/api/projects/{pid}/tags/{t['id']}").status_code == 403
