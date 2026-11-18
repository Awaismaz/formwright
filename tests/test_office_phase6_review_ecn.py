"""Design Office Phase 6: the optional per-part review gate (CD-023) and engineering change notices after a release
(CD-024). Simulated agents only (no live model: the office fixture fails the test if a live call is reached)."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from test_office_orchestrator import _events, _tk, _wait, office  # noqa: F401  (fixture)
from test_office_phase5 import RIG

from aicad.office import OfficeInputError, ecn, fake_agents, orchestrator, service, store


# ============================================================================ review gate: pure transitions
def _doc(gate: bool) -> dict[str, Any]:
    doc = service.new_program("Gate rig", "A rig to check the review gate transitions.", "org", "u", 2, 1000,
                              "standard")
    doc.update(status="active", review_gate=gate, assembly={"status": "ready"},
               skeleton={"items": {"i1": {}}})
    doc["tickets"] = [{"id": "t1", "key": "GR-1", "item_id": "i1", "kind": "part", "title": "Plate", "family": "machined",
                       "specialist": "mill", "column": "in_review", "milestones": ["brief_read", "first_build",
                                                                                  "gates_pass", "self_review"],
                       "progress": 85, "comments": [], "depends_on": [], "complexity": 2, "estimate_min": 10, "qty": 1,
                       "updated_at": "2026-11-18T00:00:00Z", "project_id": "p1", "assembly_id": None,
                       "run": {"status": "awaiting_review", "agent": "gage"}}]
    return doc


def test_review_gate_transitions(tmp_path: Path) -> None:
    root = tmp_path
    actor = service.user_actor("Eng")
    # waiting for the engineer: never claimed by an agent, shown in the inbox as a review
    doc = _doc(True)
    assert orchestrator.gated(doc, doc["tickets"][0]) and not orchestrator.gated(_doc(False), _doc(False)["tickets"][0])
    doc["gates"][1]["status"] = "approved"
    doc["icd"] = None
    assert orchestrator.claimable(doc, doc["tickets"][0], 0.0) is None
    inbox = service.inbox([doc])
    assert [(i["kind"], i["key"]) for i in inbox] == [("review", "GR-1")]
    assert service.ticket_view(doc["tickets"][0])["agent_state"] == "review"
    # approve: Approved, Fitz swaps it in next (the assembly is ready)
    t = orchestrator.review_decision(root, doc, "t1", "approve", "Looks right.", actor)
    assert t["column"] == "approved" and t["run"]["status"] == "queued" and t["run"]["next"] == "fit"
    assert t["reviewed"]["decision"] == "approved" and "Approved by Eng" in t["comments"][-1]["text"]
    with pytest.raises(OfficeInputError):  # not waiting any more
        orchestrator.review_decision(root, doc, "t1", "approve", "", actor)
    # request changes: a note is required; the ticket reopens with the note as the designer's instruction
    doc = _doc(True)
    with pytest.raises(OfficeInputError):
        orchestrator.review_decision(root, doc, "t1", "changes", "  ", actor)
    t = orchestrator.review_decision(root, doc, "t1", "changes", "Add a 1 mm chamfer on the top edges.", actor)
    assert t["column"] == "changes_requested" and t["run"]["status"] == "queued" and t["run"]["next"] == "design"
    assert t["run"]["feedback"] == ["Engineer review: Add a 1 mm chamfer on the top edges."]
    assert t["comments"][-1]["delivery"] == "queued" and "chamfer" in t["comments"][-1]["text"]
    assert "self_review" not in t["milestones"]
    types = [e["type"] for e in store.events(root, doc["id"], 50, 0)]
    assert "ticket.review_changes" in types


def test_review_gate_end_to_end(office: Any) -> None:  # noqa: F811
    from test_office_orchestrator import _program

    c = office
    v = _program(c, "gate@x.com", RIG, review_gate=True)
    pid = v["id"]
    assert v["review_gate"] is True
    c.post(f"/api/office/programs/{pid}/run")
    v = _wait(c, pid, lambda v: all(t["run_status"] == "awaiting_review" for t in v["tickets"] if t["kind"] == "part"),
              timeout=180)
    parts = [t for t in v["tickets"] if t["kind"] == "part"]
    assert {t["title"] for t in parts} == {"Base plate", "Spacer"}
    assert all(t["column"] == "in_review" and t["agent_state"] == "review" for t in parts)
    assert v["status"] != "complete" and v["orchestrator"]["review"] == 2
    home = c.get("/api/office/home").json()
    assert {i["key"] for i in home["inbox"] if i["kind"] == "review"} == {t["key"] for t in parts}
    plate, spacer = _tk(v, "Base plate"), _tk(v, "Spacer")
    # the integration of the base waits for its approval
    assert all(t["column"] != "integrated" for t in v["tickets"] if t["kind"] == "integration")
    # request changes on the spacer with a note: reopened, the note reaches the designer's next turn
    n0 = len(fake_agents.STATS["prompts"])
    r = c.post(f"/api/office/programs/{pid}/tickets/{spacer['id']}/review",
               json={"decision": "changes", "note": "Break the outer edge with a 0.5 mm chamfer."})
    assert r.status_code == 200, r.text
    assert _tk(r.json(), "Spacer")["column"] == "changes_requested"
    assert c.post(f"/api/office/programs/{pid}/tickets/{spacer['id']}/review",
                  json={"decision": "approve"}).status_code == 409  # not waiting for review now
    r = c.post(f"/api/office/programs/{pid}/tickets/{plate['id']}/review", json={"decision": "approve", "note": "OK"})
    assert r.status_code == 200, r.text
    v = _wait(c, pid, lambda v: _tk(v, "Spacer")["run_status"] == "awaiting_review", timeout=120)
    assert any("0.5 mm chamfer" in p for p in fake_agents.STATS["prompts"][n0:])
    assert _tk(v, "Base plate")["column"] in ("approved", "integrated")
    r = c.post(f"/api/office/programs/{pid}/tickets/{spacer['id']}/review", json={"decision": "approve"})
    assert r.status_code == 200, r.text
    v = _wait(c, pid, lambda v: v["status"] == "complete", timeout=180)
    assert all(t["column"] == "integrated" for t in v["tickets"])
    types = [e["type"] for e in _events(c, pid)]
    assert types.count("ticket.review_requested") == 3 and "ticket.review_approved" in types
    assert "ticket.review_changes" in types
    # switching the gate off is a program setting
    assert c.patch(f"/api/office/programs/{pid}", json={"review_gate": False}).json()["review_gate"] is False


# ============================================================================ ECN: the diff between releases (pure)
def test_release_diff_and_changes_text() -> None:
    prev = {"rev": "A", "parts": [{"ticket": "t1", "key": "TR-1", "title": "Base plate", "rev": "A"},
                                  {"ticket": "t3", "key": "TR-3", "title": "Spacer", "rev": "A"}]}
    parts = [{"ticket": "t1", "key": "TR-1", "title": "Base plate", "rev": "A"},
             {"ticket": "t3", "key": "TR-3", "title": "Spacer", "rev": "B"}]
    prev_bom = ("Item,Qty,Part,Make/Buy,Designation,Standard,Material,Mass each (g),Mass total (g),Ticket,Note\r\n"
                "1,1,Base plate,make,,,Al,10.00,10.00,TR-1,x\r\n2,1,Spacer,make,,,Al,1.00,1.00,TR-3,x\r\n"
                "3,4,Hex bolt,buy,M6x25,ISO 4017,,,,TR-2,x\r\n4,4,Washer,buy,6,ISO 7089,,,,,x\r\n,10,Total,,,,,,11.00,,\r\n")
    after = {"rows": [{"part": "Base plate", "qty": 1, "make_buy": "make", "designation": None},
                      {"part": "Spacer", "qty": 1, "make_buy": "make", "designation": None},
                      {"part": "Hex bolt", "qty": 6, "make_buy": "buy", "designation": "M6x25"},
                      {"part": "Nut", "qty": 4, "make_buy": "buy", "designation": "M6"}]}
    e = {"id": "ECN-001", "reason": "Thicker spacer for the new motor."}
    d = ecn.release_diff(prev, parts, prev_bom, after, None, None, e)
    assert [(p["key"], p["before"], p["after"], p["changed"]) for p in d["parts"]] == [
        ("TR-1", "A", "A", False), ("TR-3", "A", "B", True)]
    assert d["changed"] == 1 and d["unchanged"] == 1 and d["from"] == "A" and d["ecn"]["id"] == "ECN-001"
    assert d["bom"]["added"] == [{"part": "Nut", "designation": "M6", "qty": 4}]
    assert d["bom"]["removed"] == [{"part": "Washer", "designation": "6", "qty": 4}]
    assert d["bom"]["qty_changed"] == [{"part": "Hex bolt", "designation": "M6x25", "before": 4, "after": 6}]
    assert d["bom"]["unchanged"] == 2
    assert d["summary"] == ("1 part revised, 1 unchanged; BOM 1 added / 1 removed / 1 quantity change; "
                            "0 interface changes.")
    txt = ecn.changes_txt({"name": "Test rig"}, "B", d)
    assert "CHANGES IN Test rig REV B AGAINST REV A" in txt and "TR-3  Spacer  rev A -> B  (revised)" in txt
    assert "TR-1  Base plate  rev A -> A  (unchanged)" in txt and "~ Hex bolt  qty 4 -> 6" in txt
    # interfaces: a changed hole Ø between two ICD snapshots (field by field when the skeletons can't be compared)
    i0 = {"version": 1, "skeleton": {}, "interfaces": [{"id": "IF-01", "data": {"d": 6.6}}]}
    i1 = {"version": 2, "skeleton": {}, "interfaces": [{"id": "IF-01", "data": {"d": 7.0}}]}
    assert ecn.icd_diff(i0, i1) == {"before": 1, "after": 2, "changes": ["IF-01 changed"]}


def test_release_pack_is_written_once(tmp_path: Path) -> None:
    from aicad.platform.routers import office as route

    f = tmp_path / "A" / "pack.zip"
    f.parent.mkdir()
    route._write_new(f, b"first")
    with pytest.raises(FileExistsError):
        route._write_new(f, b"second")
    assert f.read_bytes() == b"first"


# ============================================================================ ECN end to end: A -> B -> C
def _pack(c: Any, pid: str, rev: str) -> tuple[bytes, zipfile.ZipFile]:
    r = c.get(f"/api/office/programs/{pid}/releases/{rev}/pack.zip")
    assert r.status_code == 200, (rev, r.status_code)
    return r.content, zipfile.ZipFile(io.BytesIO(r.content))


def _read(zf: zipfile.ZipFile, name: str) -> bytes:
    return zf.read(next(n for n in zf.namelist() if n.split("/", 1)[1] == name))


def test_ecn_revises_only_touched_parts(office: Any) -> None:  # noqa: F811
    from test_office_orchestrator import _program

    c = office
    v = _program(c, "ecn@x.com", RIG, deliverables=True)
    pid = v["id"]
    assert v["review_gate"] is False  # default off: parts pass straight from Gage to assembly
    c.post(f"/api/office/programs/{pid}/run")
    v = _wait(c, pid, lambda v: v["orchestrator"]["state"] == "complete", timeout=300)
    assert "ticket.review_requested" not in [e["type"] for e in _events(c, pid)]
    plate, spacer = _tk(v, "Base plate"), _tk(v, "Spacer")
    # an ECN needs a released program
    assert c.post(f"/api/office/programs/{pid}/ecn", json={"reason": "x", "items": [spacer["item_id"]]}).status_code == 409
    r = c.post(f"/api/office/programs/{pid}/release", json={"note": "First article"})
    assert r.status_code == 200, r.text
    a_bytes, _za = _pack(c, pid, "A")
    a_sha = hashlib.sha256(a_bytes).hexdigest()
    assert r.json()["release"]["pack_sha256"] == a_sha
    # released: a second release needs a change notice
    r = c.post(f"/api/office/programs/{pid}/release")
    assert r.status_code == 409 and "change notice" in r.text
    # bad ECNs
    assert c.post(f"/api/office/programs/{pid}/ecn", json={"reason": "  ", "items": [spacer["item_id"]]}).status_code == 409
    bolt = _tk(v, "Cover bolt")
    assert c.post(f"/api/office/programs/{pid}/ecn", json={"reason": "M8", "items": [bolt["item_id"]]}).status_code == 409
    # ECN-001: only the spacer changes
    r = c.post(f"/api/office/programs/{pid}/ecn", json={"reason": "Spacer face must be ground flat.",
                                                         "items": [spacer["item_id"]]})
    assert r.status_code == 200, r.text
    e = r.json()["ecn"]
    assert e["id"] == "ECN-001" and e["status"] == "in_work" and e["from_rev"] == "A" and e["tickets"] == [spacer["id"]]
    assert [h["status"] for h in e["history"]] == ["open", "in_work"]
    v = r.json()
    assert _tk(v, "Base plate")["column"] == "integrated"  # untouched
    assert _tk(v, "Spacer")["column"] != "integrated"
    assert next(g for g in v["gates"] if g["code"] == "release")["status"] == "locked"
    assert c.post(f"/api/office/programs/{pid}/ecn", json={"reason": "again", "items": [plate["item_id"]]}).status_code == 409
    v = _wait(c, pid, lambda v: v["orchestrator"]["state"] == "complete", timeout=300)
    assert v["ecns"][0]["status"] == "ready"
    d = c.get(f"/api/office/programs/{pid}/deliverables").json()
    sheets = {s["title"]: s for s in d["drawings"]["sheets"]}
    assert sheets["Base plate"].get("kept") is True and not sheets["Spacer"].get("kept")  # only the spacer redrawn
    assert d["drawings"]["redrawn"] == [spacer["id"]]
    dfm = {p["title"]: p for p in d["dfm"]["parts"]}
    assert dfm["Base plate"].get("kept") is True and not dfm["Spacer"].get("kept")
    assert d["gate"]["ready"] and d["gate"]["next_rev"] == "B"
    r = c.post(f"/api/office/programs/{pid}/release", json={"note": "ECN-001"})
    assert r.status_code == 200, r.text
    rel = r.json()["release"]
    revs = {p["title"]: p["rev"] for p in rel["parts"]}
    assert rel["rev"] == "B" and rel["ecn"] == "ECN-001" and revs == {"Base plate": "A", "Spacer": "B"}
    assert rel["diff"]["changed"] == 1 and rel["diff"]["unchanged"] == 1
    assert [(p["title"], p["before"], p["after"]) for p in rel["diff"]["parts"]] == [
        ("Base plate", "A", "A"), ("Spacer", "A", "B")]
    v = r.json()["program"]
    assert v["released"]["rev"] == "B" and v["ecns"][0]["status"] == "released" and v["ecns"][0]["to_rev"] == "B"
    b_bytes, zb = _pack(c, pid, "B")
    names = [n.split("/", 1)[1] for n in zb.namelist()]
    assert "parts/Spacer_revB.step" in names and "parts/Base_plate_revA.step" in names
    txt = _read(zb, "CHANGES.txt").decode()
    assert "AGAINST REV A" in txt and "ECN-001" in txt and "Spacer  rev A -> B  (revised)" in txt
    man = json.loads(_read(zb, "manifest.json"))
    assert hashlib.sha256(_read(zb, "CHANGES.txt")).hexdigest() == man["files"]["CHANGES.txt"]["sha256"]
    # Rev A: still downloadable, byte for byte the same
    a2, _ = _pack(c, pid, "A")
    assert hashlib.sha256(a2).hexdigest() == a_sha
    # ECN-002: an interface change (the spacer's bolt circle holes) reaches both sides through Archie's rule
    f = next(x for x in v["icd"]["interfaces"] if x["kind"] == "hole_pattern" and x["b"]["item"] == spacer["item_id"])
    r = c.post(f"/api/office/programs/{pid}/ecn", json={"reason": "Closer clearance holes for fitted screws.",
                                                         "interface": f["id"], "values": {"d": f["data"]["d"] - 0.2}})
    assert r.status_code == 200, r.text
    e2 = r.json()["ecn"]
    assert e2["id"] == "ECN-002" and set(e2["items"]) == {plate["item_id"], spacer["item_id"]} and e2["cr_id"]
    v = _wait(c, pid, lambda v: v["orchestrator"]["state"] == "complete", timeout=300)
    r = c.post(f"/api/office/programs/{pid}/release", json={"note": "ECN-002"})
    assert r.status_code == 200, r.text
    rel = r.json()["release"]
    assert rel["rev"] == "C" and {p["title"]: p["rev"] for p in rel["parts"]} == {"Base plate": "B", "Spacer": "C"}
    assert rel["diff"]["from"] == "B" and rel["diff"]["changed"] == 2
    assert rel["diff"]["icd"]["after"] == rel["diff"]["icd"]["before"] + 1
    d0 = f["data"]["d"]
    assert f"{f['id']} d: {d0:g} → {round(d0 - 0.2, 4):g}" in rel["diff"]["icd"]["changes"]
    for rev, sha in (("A", a_sha), ("B", hashlib.sha256(b_bytes).hexdigest())):
        assert hashlib.sha256(_pack(c, pid, rev)[0]).hexdigest() == sha  # earlier packs untouched
    types = [e["type"] for e in _events(c, pid)]
    for want in ("ecn.raised", "ecn.in_work", "ecn.ready", "ecn.released", "cr.accepted"):
        assert want in types, want
