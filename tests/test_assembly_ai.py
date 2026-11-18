"""Smart assembly (ASM-010 / ASM-019): Hex reads a description into Toolbox components or the company's own parts,
Fitz plans, inserts, places and mates them. No model is called in these tests: the deterministic path makes none,
and the opt-in AI fallback is replaced by a stub.

Hand values (from the fixture inputs, never measured from the built shapes):
- plate 160 × 80 × 10 (z 0..10) with 4 × Ø6.6 at (±50, ±30) and 2 × Ø8 at (±70, 0); bracket base 120 × 80 × 6 with
  the same 4 × Ø6.6 pattern: mounted face to face its base bottom sits at z = 10, the upright untouched;
- bolts through bracket + plate: grip 6 + 10 = 16, M6 (Ø6.6 = ISO 273 medium); L ≥ 16 + 2 × 1.6 + 5.2 + 2 × 1.0
  = 26.4 → M6 × 30;
- dowel Ø8 × 20 (2.5 d → 20) half in its hole: the pin end 10 mm above the plate top (z = 20);
- stepped shaft Ø20 × 30 (z 0..30) + Ø30 × 60 (z 30..90) + Ø20 × 30 (z 90..120): a 6204 (20 × 47 × 14) against
  the shoulder at z = 30 occupies z 16..30, against the one at z = 90 it occupies z 90..104 (turned over); a third
  one finds no free shoulder and goes flush with a free shaft end (z 0..14 or 106..120).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_assembly import app_client  # noqa: F401  (fixture)

from aicad.assembly import fitz, librarian, xform

CANDS = [{"id": "p1", "name": "Motor Bracket", "description": "NEMA 17 motor mount"},
         {"id": "p2", "name": "Demo · Mounting Plate", "description": "base plate"},
         {"id": "p3", "name": "Stepped Shaft", "description": ""},
         {"id": "p4", "name": "Bracket", "description": ""}]


def _one(text: str) -> dict[str, Any]:
    cl = librarian.parse(text)
    assert len(cl) == 1, [c.text for c in cl]
    return librarian.resolve(cl[0], CANDS)


# ----------------------------------------------------------------------------- Hex: deterministic reading
@pytest.mark.parametrize("text,code,params,qty", [
    ("4 M6x25 bolts with washers and nuts for the plate holes", "hex_bolt", {"D": 6, "L": 25}, 4),
    ("four M8 x 30 hex bolts", "hex_bolt", {"D": 8, "L": 30}, 4),
    ("6 M5 socket head cap screws 20 mm long", "shcs", {"D": 5, "L": 20}, 6),
    ("a 6204 bearing on the shaft", "bearing", {"SERIES": 6204}, 1),
    ("bearing 6001", "bearing", {"SERIES": 6001}, 1),
    ("two Ø8 dowel pins", "dowel", {"D": 8, "L": 20}, 2),
    ("2 dowel pins Ø6x16 into the plate", "dowel", {"D": 6, "L": 16}, 2),
    ("M10 nuts x6", "hex_nut", {"D": 10}, 6),
    ("6 x M5 washers", "washer", {"D": 5}, 6),
    ("a Ø20 shaft 150 long", "shaft", {"D": 20, "L": 150}, 1),
    ("spur gear m2 24 teeth", "spur_gear", {"M": 2, "Z": 24}, 1),
    ("a pair of M3 standoffs 10 mm long", "standoff", {"D": 3, "L": 10}, 2),
])
def test_hex_reads_toolbox_components(text: str, code: str, params: dict[str, float], qty: int) -> None:
    r = _one(text)
    assert r["source"] == "toolbox" and r["code"] == code and r["qty"] == qty
    for k, v in params.items():
        assert r["params"][k] == pytest.approx(v)
    assert r["found"].startswith("Hex found") and "Toolbox" in r["found"]


def test_fastener_clause_keeps_accessories_and_target() -> None:
    cl = librarian.parse("4 M6x25 bolts with washers and nuts for the plate holes")
    assert len(cl) == 1 and cl[0].target == "the plate holes" and cl[0].qty == 4
    r = librarian.resolve(cl[0], CANDS)
    assert r["fasten"] == {"style": "hex_bolt", "washers": "both", "size": 6, "length": 25.0}
    assert librarian.resolve(librarian.parse_clause("4 M6 bolts without washers"), CANDS)["fasten"]["washers"] == "none"


def test_description_splits_into_items() -> None:
    cl = librarian.parse("Mount the motor bracket on the plate with 4 M6 bolts, washers and nuts, "
                         "a 6204 bearing on the shaft; two Ø8 dowel pins")
    assert [c.core for c in cl] == ["motor bracket", "M6 bolts and washers and nuts", "6204 bearing", "ø8 dowel pins"]
    assert cl[0].mount and cl[0].target == "the plate" and cl[1].qty == 4 and cl[3].qty == 2


def test_hex_finds_company_parts_before_new_design() -> None:
    r = _one("the motor bracket from my projects")
    assert r["source"] == "project" and r["project_id"] == "p1" and r["confidence"] == "high"
    assert r["found"] == "Hex found Motor Bracket in your parts"
    r = _one("our stepped shafts")
    assert r["source"] == "project" and r["project_id"] == "p3"
    # a designation always means the Toolbox, even when a project has the same noun
    assert _one("an M8 bolt")["source"] == "toolbox"
    # nothing anywhere: new design, not enabled for insertion
    r = _one("a gearbox housing with ribs")
    assert r["source"] == "new" and "couldn't find" in r["found"]


def test_ai_answer_is_validated_never_trusted() -> None:
    text = ('```fw-items\n[{"line": 0, "code": "hex_bolt", "params": {"D": 6, "L": 25}, "qty": 4},'
            ' {"line": 1, "code": "hex_bolt", "params": {"D": 7}},'            # M7 is not a supported size
            ' {"line": 2, "code": "rocket", "params": {}},'                    # not a Toolbox component
            ' {"line": 3, "part": "Motor Bracket"}, {"line": 9, "code": "washer"}]\n```')
    got = librarian.read_ai(text, 4, CANDS)
    assert set(got) == {0, 3}
    assert got[0]["code"] == "hex_bolt" and got[0]["params"] == {"D": 6, "L": 25.0} and got[0]["qty"] == 4
    assert got[3]["source"] == "project" and got[3]["project_id"] == "p1"
    assert librarian.read_ai("no block at all", 2, CANDS) == {}


def test_bearing_for_seat() -> None:
    assert fitz.bearing_for(20) == 6204 and fitz.bearing_for(10) == 6200 and fitz.bearing_for(21) is None


# ----------------------------------------------------------------------------- fixtures (project builds)
def _write(out: Path, shape: Any, name: str, material: str, build_id: str) -> None:
    from build123d import export_step

    out.mkdir(parents=True, exist_ok=True)
    export_step(shape, str(out / "part.step"))
    (out / "status.json").write_text(json.dumps({"ok": True, "part": name, "material": material,
                                                 "build_id": build_id}), encoding="utf-8")


def _holes(part: Any, pts: list[tuple[float, float, float]], h: float) -> Any:
    from build123d import Align, Cylinder, Pos

    for x, y, d in pts:
        part -= Pos(x, y, -1) * Cylinder(d / 2, h + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return part


def plate(out: Path) -> None:
    from build123d import Align, Box

    p = Box(160, 80, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    p = _holes(p, [(sx * 50, sy * 30, 6.6) for sx in (-1, 1) for sy in (-1, 1)] + [(-70, 0, 8), (70, 0, 8)], 10)
    _write(out, p, "Base Plate", "Aluminium 6061-T6", "4001")


def bracket(out: Path) -> None:
    from build123d import Align, Box, Pos

    base = _holes(Box(120, 80, 6, align=(Align.CENTER, Align.CENTER, Align.MIN)),
                  [(sx * 50, sy * 30, 6.6) for sx in (-1, 1) for sy in (-1, 1)], 6)
    up = Pos(0, 0, 6) * Box(120, 6, 40, align=(Align.CENTER, Align.CENTER, Align.MIN))
    _write(out, base + up, "Motor Bracket", "Steel S235", "5001")


def stepped_shaft(out: Path) -> None:
    from build123d import Align, Cylinder, Pos

    a = Cylinder(10, 30, align=(Align.CENTER, Align.CENTER, Align.MIN))
    b = Pos(0, 0, 30) * Cylinder(15, 60, align=(Align.CENTER, Align.CENTER, Align.MIN))
    c = Pos(0, 0, 90) * Cylinder(10, 30, align=(Align.CENTER, Align.CENTER, Align.MIN))
    _write(out, a + b + c, "Stepped Shaft", "Steel C45", "6001")


def _setup(c: Any, email: str) -> None:
    from test_platform import signup

    signup(c, email)
    pay = c.post("/api/billing/checkout", json={"product_code": "addon_assembly"}).json()["payment_id"]
    c.post(f"/api/billing/payments/{pay}/simulate", json={"outcome": "success"})


def _project(c: Any, name: str, writer: Any) -> str:
    from aicad.platform.db import session_factory
    from aicad.platform.models import Project
    from aicad.platform.routers.projects import workspace_for

    pid = c.post("/api/projects", json={"name": name}).json()["id"]
    db = session_factory()()
    ws = workspace_for(db.get(Project, pid))
    db.close()
    writer(ws / "out")
    return pid


def _origin(v: dict[str, Any], iid: str) -> list[float]:
    T = xform.from12(next(i for i in v["instances"] if i["id"] == iid)["T"])
    return [float(x) for x in xform.pt(T, (0, 0, 0))]


def _z(v: dict[str, Any], iid: str) -> list[float]:
    T = xform.from12(next(i for i in v["instances"] if i["id"] == iid)["T"])
    return [float(x) for x in xform.vec(T, (0, 0, 1))]


# ----------------------------------------------------------------------------- Fitz: plan, insert, mate (kernel)
def test_plate_bracket_bolts_and_dowels_from_text(app_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    async def no_ai(*a: Any, **k: Any) -> Any:
        raise AssertionError("the deterministic path must not call the AI")

    monkeypatch.setattr(librarian, "ask_ai", no_ai)
    c = app_client
    _setup(c, "smart@x.com")
    plate_id = _project(c, "Base Plate", plate)
    br_id = _project(c, "Motor Bracket", bracket)
    v = c.post("/api/m/assembly/assemblies", json={"project_id": plate_id}).json()
    aid, plate_iid = v["assembly"]["id"], v["instances"][0]["id"]
    text = ("Mount the motor bracket from my projects on the plate with 4 M6 bolts, washers and nuts, "
            "and two Ø8 dowel pins into the plate")
    r = c.post(f"/api/m/assembly/assemblies/{aid}/smart/plan", json={"text": text})
    assert r.status_code == 200, r.text
    pl = r.json()
    assert pl["tokens"] == 0 and not pl["ai_used"] and pl["unresolved"] == []
    items = pl["items"]
    assert [i["action"] for i in items] == ["mount", "dowel", "fasten"]          # insertion order
    mnt, dwl, fst = items
    assert mnt["source"] == "project" and mnt["project_id"] == br_id and mnt["target"] == {"inst": plate_iid}
    assert dwl["code"] == "dowel" and dwl["params"] == {"D": 8.0, "L": 20.0} and dwl["qty"] == 2
    assert fst["code"] == "hex_bolt" and fst["fasten"]["size"] == 6 and fst["qty"] == 4
    assert all(i["found"].startswith("Hex found") for i in items)
    # nothing changed yet
    assert len(c.get(f"/api/m/assembly/assemblies/{aid}").json()["instances"]) == 1
    v = c.post(f"/api/m/assembly/assemblies/{aid}/smart/run", json={"items": items}).json()
    res = v["result"]
    assert res["fastener_stacks"] == 4 and res["clashes"] == [], res["log"]
    assert res["summary"] == "Fitz mated 4/4 bolts, placed and mated 3 parts, 0 clashes"
    br = next(i for i in v["instances"] if i["source"]["kind"] == "project" and i["id"] != plate_iid)
    o = _origin(v, br["id"])
    assert o[2] == pytest.approx(10.0, abs=1e-6) and abs(o[0]) < 1e-6 and abs(o[1]) < 1e-6   # base on the plate top
    assert any("mounted Motor Bracket<1> on Base Plate<1>: 4 of 4 holes" in ln["text"] for ln in res["log"])
    bolts = [i for i in v["instances"] if i["name"] == "Hex bolt ISO 4017 M6×30"]
    assert len(bolts) == 4                                                       # grip 16 → L ≥ 26.4 → 30
    for b in bolts:
        assert _origin(v, b["id"])[2] == pytest.approx(16 + 1.6, abs=1e-6)       # head on the washer on the bracket
    dowels = [i for i in v["instances"] if i["name"] == "Dowel pin Ø8×20"]
    assert len(dowels) == 2
    for d in dowels:
        o = _origin(v, d["id"])
        assert abs(abs(o[0]) - 70) < 1e-6 and o[1] == pytest.approx(0, abs=1e-6)
        assert o[2] + 20 * _z(v, d["id"])[2] == pytest.approx(20.0, abs=1e-6)  # pin end 10 above the top
    assert not v["solve"]["conflicts"] and v["solve"]["status"] != "over_defined"
    an = v["analysis"]
    assert an and not an["stale"] and an["interference"]["count"] == 0
    # what Fitz did is visible: every mate satisfied
    assert all(m["status"] == "ok" for m in v["mates"])


def test_bearing_on_shaft_against_shoulder(app_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c = app_client
    _setup(c, "shaft@x.com")
    sid = _project(c, "Stepped Shaft", stepped_shaft)
    v = c.post("/api/m/assembly/assemblies", json={"project_id": sid}).json()
    aid, shaft = v["assembly"]["id"], v["instances"][0]["id"]
    # "a bearing" without a size: Hex sizes it from the Ø20 seat
    pl = c.post(f"/api/m/assembly/assemblies/{aid}/smart/plan", json={"text": "a bearing on the shaft"}).json()
    it = pl["items"][0]
    assert it["code"] == "bearing" and it["params"] == {"SERIES": 6204} and it["action"] == "seat"
    assert it["target"] == {"inst": shaft} and "against the shoulder" in it["plan"]
    pl = c.post(f"/api/m/assembly/assemblies/{aid}/smart/plan", json={"text": "2 6204 bearings on the shaft"}).json()
    assert pl["items"][0]["qty"] == 2
    v = c.post(f"/api/m/assembly/assemblies/{aid}/smart/run", json={"items": pl["items"]}).json()
    b1, b2 = [i["id"] for i in v["instances"] if i["name"] == "Ball bearing 6204"]
    assert _origin(v, b1) == pytest.approx([0, 0, 16], abs=1e-6) and _z(v, b1) == pytest.approx([0, 0, 1])
    assert _origin(v, b2) == pytest.approx([0, 0, 104], abs=1e-6) and _z(v, b2) == pytest.approx([0, 0, -1])
    assert {m["type"] for m in v["mates"]} == {"concentric", "coincident"} and all(m["status"] == "ok" for m in v["mates"])
    assert v["result"]["clashes"] == [] and v["analysis"]["interference"]["count"] == 0
    assert all("against the shoulder" in ln["text"] for ln in v["result"]["log"][:2])
    # one more: no free shoulder left, so flush with a free shaft end
    pl = c.post(f"/api/m/assembly/assemblies/{aid}/smart/plan", json={"text": "a 6204 bearing on the shaft"}).json()
    v = c.post(f"/api/m/assembly/assemblies/{aid}/smart/run", json={"items": pl["items"]}).json()
    b3 = [i["id"] for i in v["instances"] if i["name"] == "Ball bearing 6204"][2]
    assert _origin(v, b3)[2] in (pytest.approx(14, abs=1e-6), pytest.approx(106, abs=1e-6))
    assert "flush with the shaft end" in v["result"]["log"][0]["text"] and v["result"]["clashes"] == []


def test_ai_fallback_only_on_request_and_metered(app_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    calls: list[list[str]] = []

    async def stub(clauses: list[str], parts: list[str], budget: Any = None) -> tuple[str, float]:
        calls.append(clauses)
        return ('```fw-items\n[{"line": 0, "code": "hex_nut", "params": {"D": 8}, "qty": 3}]\n```', 0.02)

    monkeypatch.setattr(librarian, "ask_ai", stub)
    c = app_client
    _setup(c, "hexai@x.com")
    pid = _project(c, "Base Plate", plate)
    aid = c.post("/api/m/assembly/assemblies", json={"project_id": pid}).json()["assembly"]["id"]
    text = "4 M6 washers; three of those six-sided M8 thingies"
    pl = c.post(f"/api/m/assembly/assemblies/{aid}/smart/plan", json={"text": text}).json()
    assert calls == [] and pl["tokens"] == 0 and len(pl["unresolved"]) == 1
    bal = c.get("/api/auth/me").json()["org"]["token_balance"]
    pl = c.post(f"/api/m/assembly/assemblies/{aid}/smart/plan", json={"text": text, "ai": True}).json()
    assert calls == [["three of those six-sided M8 thingies"]]                   # only the unread line
    assert pl["tokens"] > 0 and pl["ai_used"] and pl["unresolved"] == []
    nut = next(i for i in pl["items"] if i.get("ai"))
    assert nut["code"] == "hex_nut" and nut["params"] == {"D": 8} and nut["qty"] == 3
    assert c.get("/api/auth/me").json()["org"]["token_balance"] == bal - pl["tokens"]
    # a bad edit is refused with a plain message
    bad = [{**pl["items"][0], "params": {"D": 7}}]
    r = c.post(f"/api/m/assembly/assemblies/{aid}/smart/run", json={"items": bad})
    assert r.status_code == 422 and "choose one of" in r.json()["detail"]


def test_assembly_plan_from_text_and_existing_parts(app_client: Any) -> None:  # noqa: F811
    """ASM-010: an empty assembly, a short text naming two of the user's parts: Hex adds the base part the text
    names, Fitz orders base → mount → fasten and builds it."""
    c = app_client
    _setup(c, "plan@x.com")
    plate_id = _project(c, "Base Plate", plate)
    br_id = _project(c, "Motor Bracket", bracket)
    aid = c.post("/api/m/assembly/assemblies", json={"name": "Drive"}).json()["assembly"]["id"]
    pl = c.post(f"/api/m/assembly/assemblies/{aid}/smart/plan",
                json={"text": "bolt the motor bracket onto the base plate with 4 M6 bolts"}).json()
    acts = [(i["action"], i.get("project_id") or i.get("code")) for i in pl["items"]]
    assert acts == [("base", plate_id), ("mount", br_id), ("fasten", "hex_bolt")]
    base, mnt, _f = pl["items"]
    assert base["auto"] and mnt["target"] == {"item": base["id"]} and "Fixed at the origin" in base["plan"]
    v = c.post(f"/api/m/assembly/assemblies/{aid}/smart/run", json={"items": pl["items"]}).json()
    res = v["result"]
    assert res["fastener_stacks"] == 4 and res["clashes"] == [] and res["placed_loose"] == 0
    p = next(i for i in v["instances"] if i["source"].get("project_id") == plate_id)
    b = next(i for i in v["instances"] if i["source"].get("project_id") == br_id)
    assert p["fixed"] and _origin(v, p["id"]) == pytest.approx([0, 0, 0], abs=1e-9)
    assert _origin(v, b["id"]) == pytest.approx([0, 0, 10], abs=1e-6)
    assert v["analysis"]["interference"]["count"] == 0
