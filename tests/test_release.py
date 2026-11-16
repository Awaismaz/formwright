"""Release gate ("Issue Rev A", IDEA-01): one staleness rule across the downstream modules, frozen hashed packs,
letter revisions (ASME Y14.35 letters), drafts after a change, and the deliverables endpoint behind the Make tab."""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from test_platform import _project_with_model, app_client, signup  # noqa: F401  (fixture re-export)

from aicad import deliverables, handoff

DEMO = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo"


def test_revision_letters_skip_ambiguous_ones() -> None:
    assert [handoff.rev_letter(i) for i in range(10)] == list("ABCDEFGHJK")  # no I
    assert "".join(handoff.REV_LETTERS) == "ABCDEFGHJKLMNPRTUVWY"  # I O Q S X Z are not used
    assert handoff.rev_letter(19) == "Y" and handoff.rev_letter(20) == "AA" and handoff.rev_letter(21) == "AB"


def test_same_build_rule() -> None:
    cur = {"build_id": "2", "step_sha256": "abc", "material": "Steel"}
    assert deliverables.same_build({"build_id": "2"}, cur)
    assert deliverables.same_build({"build_id": 2}, cur)  # ints and strings compare as ids
    assert deliverables.same_build({"build_id": "1", "step_sha256": "abc", "material": "Steel"}, cur)  # identical rebuild
    assert not deliverables.same_build({"build_id": "1", "step_sha256": "abc", "material": "Brass"}, cur)
    assert not deliverables.same_build({"build_id": "1", "step_sha256": None}, cur)
    assert not deliverables.same_build(None, cur)


def _unlock(c: TestClient, code: str) -> None:
    pay = c.post("/api/billing/checkout", json={"product_code": code}).json()["payment_id"]
    c.post(f"/api/billing/payments/{pay}/simulate", json={"outcome": "success"})


def test_issue_rev_a_then_draft_then_rev_b(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "release@x.com")
    _unlock(c, "addon_drawings")
    pid, ws = _project_with_model(c, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))

    d = c.get(f"/api/projects/{pid}/deliverables").json()
    assert d["verified"] and d["release"] is None and d["next_rev"] == "A"
    assert {k: v["state"] for k, v in d["modules"].items()} == {
        "drawings": "missing", "manufacturing": "missing", "engineering": "missing", "print": "missing"}
    g = c.get(f"/api/projects/{pid}/release").json()
    assert not g["ready"] and [b["kind"] for b in g["blocking"]] == ["drawings"] and g["suggested_note"] == "Initial issue"
    r = c.post(f"/api/projects/{pid}/releases", json={})
    assert r.status_code == 409 and "Drawing Studio" in r.json()["detail"]["message"]

    assert c.post(f"/api/m/drawings/projects/{pid}/generate", json={}).status_code == 200
    assert json.loads((ws / "drawings" / "drawing.json").read_text(encoding="utf-8"))["sheet_rev"] == "DRAFT"
    d = c.get(f"/api/projects/{pid}/deliverables").json()
    assert d["modules"]["drawings"]["state"] == "current" and d["modules"]["drawings"]["label"] == "Draft"
    # an analysis from an earlier build is stale, and blocks until re-run or left out
    (ws / "manufacturing").mkdir()
    (ws / "manufacturing" / "analysis.json").write_text(json.dumps(
        {"build": {"build_id": "old", "model_rev": "0"}, "summary": {"critical": 1, "warning": 0, "info": 0}}), encoding="utf-8")
    g = c.get(f"/api/projects/{pid}/release").json()
    assert [b["kind"] for b in g["blocking"]] == ["manufacturing"] and g["blocking"][0]["leavable"] == "dfm"
    assert c.get(f"/api/projects/{pid}/deliverables").json()["modules"]["manufacturing"]["label"] == "Model changed · re-analyse"

    r = c.post(f"/api/projects/{pid}/releases", json={"leave_out": ["dfm"], "local_date": "2026-11-17"})
    assert r.status_code == 200, r.text
    rel = r.json()["release"]
    assert rel["rev"] == "A" and rel["note"] == "Initial issue" and rel["date"] == "2026-11-17" and rel["by"] == "Ada Engineer"
    st = r.json()["status"]
    assert st["release"]["current"] and not st["changed_since_release"] and st["next_rev"] == "B"
    assert st["modules"]["drawings"]["label"] == "Rev A"  # the working sheet now carries the letter
    # the frozen pack: issue copy of the drawing stamped A, model files, manifest hashes, left-out note
    pack = ws / "releases" / "A" / "pack.zip"
    assert hashlib.sha256(pack.read_bytes()).hexdigest() == rel["pack_sha256"]
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/projects/{pid}/releases/A/pack.zip").content))
    root = z.namelist()[0].split("/")[0]
    assert root == "Plate_revA"
    names = {n.split("/", 1)[1] for n in z.namelist()}
    assert {"model/Plate.step", "drawing/Plate_drawing.pdf", "drawing/Plate_drawing.dxf", "README.txt", "manifest.json"} <= names
    assert not any(n.startswith("dfm/") for n in names)
    manifest = json.loads(z.read(f"{root}/manifest.json"))
    assert manifest["release"]["rev"] == "A" and manifest["release"]["left_out"] == ["manufacturability report (older analysis)"]
    for name, meta in manifest["files"].items():
        assert hashlib.sha256(z.read(f"{root}/{name}")).hexdigest() == meta["sha256"]
    readme = z.read(f"{root}/README.txt").decode()
    assert "REV A" in readme and "Left out of this release" in readme and "not a manufacturing approval" in readme
    issued = json.loads((ws / "releases" / "A" / "drawing" / "drawing.json").read_text(encoding="utf-8"))
    assert issued["sheet_rev"] == "A" and issued["issued"] is True
    # the same build can't be issued twice
    r = c.post(f"/api/projects/{pid}/releases", json={"leave_out": ["dfm"]})
    assert r.status_code == 409 and "already is this exact model" in r.json()["detail"]["message"]

    # change the part: every module compares itself with the issued build
    assert c.post(f"/api/projects/{pid}/params", json={"values": {"L": 130}}).status_code == 200
    for _ in range(600):  # the fast rebuild writes its STEP export in the background
        if deliverables.read_status(ws).get("step_sha256"):
            break
        time.sleep(0.1)
    d =c.get(f"/api/projects/{pid}/deliverables").json()
    assert d["changed_since_release"] and d["release"]["rev"] == "A" and not d["release"]["current"]
    assert d["modules"]["drawings"]["state"] == "stale" and d["modules"]["drawings"]["label"] == "Model changed · update"
    g = c.get(f"/api/projects/{pid}/release").json()
    assert {b["kind"] for b in g["blocking"]} == {"drawings", "manufacturing"} and g["next_rev"] == "B"
    assert g["suggested_note"] == "L 120 → 130"
    assert c.post(f"/api/m/drawings/projects/{pid}/generate", json={}).status_code == 200
    assert json.loads((ws / "drawings" / "drawing.json").read_text(encoding="utf-8"))["sheet_rev"] == "DRAFT"
    r = c.post(f"/api/projects/{pid}/releases", json={"leave_out": ["dfm"], "note": "Longer plate for the new frame"})
    assert r.status_code == 200, r.text
    assert r.json()["release"]["rev"] == "B" and r.json()["status"]["modules"]["drawings"]["label"] == "Rev B"
    g = c.get(f"/api/projects/{pid}/release").json()
    assert [x["rev"] for x in g["releases"]] == ["B", "A"] and g["releases"][0]["note"] == "Longer plate for the new frame"
    assert (ws / "releases" / "A" / "pack.zip").is_file()  # Rev A stays frozen as sent
    # the draft handoff plan reports the release too
    plan = c.get(f"/api/projects/{pid}/handoff").json()
    assert plan["release"]["rev"] == "B" and plan["release"]["current"]

    # viewers can download but not issue
    from aicad.platform.db import session_factory
    from aicad.platform.models import Membership, User

    db = session_factory()()
    me = db.scalar(select(User).where(User.email == "release@x.com"))
    m = db.scalar(select(Membership).where(Membership.user_id == me.id))
    m.role = "viewer"
    db.commit()
    db.close()
    assert c.post(f"/api/projects/{pid}/releases", json={}).status_code == 403
    assert c.get(f"/api/projects/{pid}/releases/A/pack.zip").status_code == 200
    assert c.get(f"/api/projects/{pid}/releases/..%2F..%2Fout/pack.zip").status_code == 404
    assert c.get(f"/api/projects/{pid}/release").json()["can_issue"] is False
