"""Design Office Phase 4 (CD-010..CD-013): skeleton + ICD, conformance measurement, placeholders, mates by interface
name, swap-in, change requests, nested sub-assemblies and the live assembly view. No live AI: part agents are the
deterministic fake client (``office.fake_agents``), Archie's planning turn and the real review / change-request calls
fail the test if reached (fixture from test_office_orchestrator)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest
from test_office_orchestrator import _events, _program, _tk, _wait, office  # noqa: F401  (fixture)

from aicad.office import conformance, fake_agents, icd, interfaces, planner, service

# The hand-checked program: a 200 x 100 x 10 base plate carrying a 60 x 40 x 8 bracket (bolted, M6 from the
# standard bolt of the same sub-assembly) and, from a second sub-assembly, a Ø20 x 15 spacer ring (bolted, M3).
PLAN = {"source": "standard", "summary": "ICD rig", "assumptions": [], "subassemblies": [
    {"name": "Base", "description": "", "parts": [
        {"name": "Base plate", "family": "machined", "complexity": 2, "qty": 1, "description": "Plate 200 x 100 x 10 mm."},
        {"name": "Bracket", "family": "machined", "complexity": 2, "qty": 1, "description": "Bracket 60 x 40 x 8 mm."},
        {"name": "Cover bolt", "family": "standard", "complexity": 1, "qty": 4, "description": "Hex bolts M6 x 25."}]},
    {"name": "Drive", "description": "", "parts": [
        {"name": "Spacer", "family": "turned", "complexity": 1, "qty": 1, "description": "Spacer Ø20 x 15 mm."}]}]}


def _parts(plan: dict[str, Any] = PLAN) -> list[dict[str, Any]]:
    p = planner.normalise_plan(plan, "standard")
    assert p is not None
    return [{"id": f"i_{s['id']}_{q['id']}", "name": q["name"], "family": q["family"], "qty": q["qty"],
             "description": q["description"], "complexity": q["complexity"], "sub": f"i_{s['id']}"}
            for s in p["subassemblies"] for q in s["parts"]]


BASE, BRACKET, SPACER = "i_s1_p1", "i_s1_p2", "i_s2_p4"


# ----------------------------------------------------------------------------- skeleton + ICD (hand calculations)
def test_icd_layout_and_interfaces_hand_checked() -> None:
    sk, ifs = icd.build(_parts(), "A test rig.")
    # row on the base top face: margin 10 + bracket 60 + gap 12 + spacer 20 + margin 10 = 112 mm, centred:
    # starts at -56 + 10 = -46 -> bracket centre x = -16, spacer centre x = -46 + 60 + 12 + 10 = 36
    assert sk["base"] == BASE and sk["items"][BASE]["size"] == [200, 100, 10]
    assert sk["items"][BASE]["copies"] == [[0, 0, -5]]                         # top face on datum A (Z = 0)
    assert sk["items"][BRACKET]["copies"] == [[-16, 0, 4]]
    assert sk["items"][SPACER]["copies"] == [[36, 0, 7.5]] and sk["items"][SPACER]["role"] == "hub"
    assert sk["envelope"] == {"min": [-100, -50, -10], "max": [100, 50, 15], "size": [200, 100, 25]}
    assert [f["id"] for f in ifs] == ["IF-01", "IF-02"] and [f["kind"] for f in ifs] == ["hole_pattern"] * 2
    j = ifs[0]["data"]
    # M6 from "Hex bolts M6 x 25" (same sub-assembly): ISO 273 medium Ø6.6, edge distance 2 x 6.6 = 13.2,
    # holes at (-16 +/- (30 - 13.2), +/-(20 - 13.2)) = (-32.8 | 0.8, -6.8 | 6.8), mounting plane Z = 0
    assert j["fastener"] == "M6" and j["d"] == 6.6 and j["inset"] == 13.2 and j["plane_z"] == 0
    assert j["positions"] == [[-32.8, -6.8], [0.8, -6.8], [-32.8, 6.8], [0.8, 6.8]]
    assert (ifs[0]["a"]["item"], ifs[0]["b"]["item"]) == (BASE, BRACKET) and ifs[0]["datums"] == ["A", "B", "C"]
    # the spacer ring is bolted on a bolt circle: no fastener in its sub-assembly -> by size: 0.6 x Ø20 = 12 -> M3
    # (Ø3.4); PCD = max(0.65 x 20, 3 x 3.4) = 13; first hole at 45 deg: 36 + 6.5 cos 45 = 40.596 -> 40.6
    s = ifs[1]["data"]
    assert s["pattern"] == "circular" and s["fastener"] == "M3" and s["d"] == 3.4 and s["pcd"] == 13
    assert s["positions"] == [[40.6, 4.6], [31.4, 4.6], [31.4, -4.6], [40.6, -4.6]]
    # local features in each part frame (origin at the envelope centre)
    fb = icd.item_features(sk, ifs, BRACKET)
    assert fb[0] == {"type": "face", "z": -4, "n": -1, "tol": 0.1, "label": "mounting face (bottom)", "if": "IF-01"}
    assert [h["c"] for h in fb[1:]] == [[-16.8, -6.8], [16.8, -6.8], [-16.8, 6.8], [16.8, 6.8]]
    fa = icd.item_features(sk, ifs, BASE)
    assert fa[0]["z"] == 5 and fa[0]["n"] == 1 and len([f for f in fa if f["type"] == "hole"]) == 8
    assert icd.problems(sk, ifs) == []
    # deterministic: the same input gives the same skeleton and ICD
    assert json.dumps(icd.build(_parts(), "A test rig."), sort_keys=True) == json.dumps((sk, ifs), sort_keys=True)
    # the excerpt a part agent gets
    ex = icd.excerpt(sk, {"version": 1, "interfaces": ifs}, BRACKET)
    assert "IF-01 Bracket ↔ Base plate: bolted joint" in ex and "4 × Ø6.6 through (M6 clearance)" in ex
    assert "(-16.8, -6.8)" in ex and "```fw-icd" in ex and "fw-change-request" in ex


@pytest.mark.parametrize("name,brief", [("Gear reducer", "A spur gear reducer, 3:1, 1450 rpm input."),
                                        ("Conveyor", "A belt conveyor."), ("Gripper", "A robot gripper."),
                                        ("Enclosure", "An electronics enclosure."), ("Fixture", "A milling fixture."),
                                        ("Linear stage", "A linear stage with a lead screw."),
                                        ("Widget", "Some machine.")])
def test_icd_templates_are_valid(name: str, brief: str) -> None:
    plan = planner.standard_plan(name, brief)
    parts = [{"id": f"i_{s['id']}_{p['id']}", "name": p["name"], "family": p["family"], "qty": p["qty"],
              "description": p["description"], "complexity": p["complexity"], "sub": f"i_{s['id']}"}
             for s in plan["subassemblies"] for p in s["parts"]]
    sk, ifs = icd.build(parts, brief)
    assert icd.problems(sk, ifs) == []
    assert len({f["id"] for f in ifs}) == len(ifs) >= 2
    for f in ifs:
        assert f["a"]["item"] in sk["items"] and f["b"]["item"] in sk["items"] and f["a"]["item"] != f["b"]["item"]
    designed = [p for p in parts if p["family"] != "standard"]
    assert set(sk["items"]) == {p["id"] for p in designed}
    if name == "Gear reducer":
        mesh = next(f for f in ifs if f["kind"] == "gear_mesh")["data"]
        # 3:1 from the brief: pinion 18 teeth, gear 54; module 2 -> a = 2 x (18 + 54) / 2 = 72 mm
        assert (mesh["module"], mesh["teeth_a"], mesh["teeth_b"], mesh["centre_distance"]) == (2.0, 18, 54, 72)
        dx = abs(mesh["axis_a"][0] - mesh["axis_b"][0])
        assert abs(dx - 72) < 1e-9 and mesh["axis_a"][1] == mesh["axis_b"][1]
        assert sum(1 for f in ifs if f["kind"] == "shaft_bore") == 4  # 2 shafts in the housing, 2 gears on them


def test_fit_zones_iso286() -> None:
    assert icd.zone(20, "H7") == (20, 20.021)
    assert icd.zone(20, "h6") == (19.987, 20.0)
    lo, hi = icd.zone(20, "k6")  # type: ignore[misc]
    assert abs(lo - 20.002) < 1e-9 and abs(hi - 20.015) < 1e-9
    lo, hi = icd.zone(20, "g6")  # type: ignore[misc]
    assert abs(lo - 19.980) < 1e-9 and abs(hi - 19.993) < 1e-9
    lo, hi = icd.zone(50, "p6")  # type: ignore[misc]  # 30-50 range: ei +26, IT6 16
    assert abs(lo - 50.026) < 1e-9 and abs(hi - 50.042) < 1e-9
    assert icd.zone(20, "Z9") is None


def test_edit_values_validation() -> None:
    from aicad.office import OfficeInputError

    sk, ifs = icd.build(_parts(), "")
    f = ifs[0]
    assert icd.clean_values(f, {"fastener": "M8", "count": 4}) == {"fastener": 8, "count": 4}
    for bad in ({"fit": "H7/h6"}, {"count": 5}, {"d": -1}, {"fastener": "M7"}, {}):
        with pytest.raises(OfficeInputError):
            icd.clean_values(f, bad)
    # at the gate, M8 -> Ø9 holes with the edge distance 2 x 9 = 18: 40 mm of bracket width can't take two rows
    # (2 x 18 + 9 = 45 > 40), so the pattern becomes 2 holes on the centre line at -16 +/- (30 - 18)
    sk2, ifs2 = icd.build(_parts(), "", icd.apply_values({}, f, {"fastener": 8}))
    assert ifs2[0]["data"]["d"] == 9.0 and ifs2[0]["data"]["inset"] == 18.0 and ifs2[0]["data"]["count"] == 2
    assert ifs2[0]["data"]["positions"] == [[-28.0, 0.0], [-4.0, 0.0]] and icd.problems(sk2, ifs2) == []
    # after approval the pattern is frozen: Ø9 stays on the same four positions (13.6 - 9 = 4.6 mm between holes)
    frozen = icd.freeze(sk, ifs, {})
    sk3, ifs3 = icd.build(_parts(), "", icd.apply_values(frozen, f, {"d": 7.0}))
    assert ifs3[0]["data"]["positions"] == ifs[0]["data"]["positions"] and ifs3[0]["data"]["d"] == 7.0
    assert icd.problems(sk3, ifs3) == []
    # Ø9 takes M8 bolts: their Ø16 washers overlap at 13.6 mm centres; Ø16 holes overlap outright (13.6 - 16 < 1)
    sk4, ifs4 = icd.build(_parts(), "", icd.apply_values(frozen, f, {"d": 9.0}))
    assert icd.problems(sk4, ifs4) == [("IF-01: Ø9 holes take M8 bolts, whose washers (Ø16) overlap at 13.6 mm "
                                        "between hole centres.")]
    sk5, ifs5 = icd.build(_parts(), "", icd.apply_values(frozen, f, {"d": 16.0}))
    assert any("apart" in p for p in icd.problems(sk5, ifs5))


# ----------------------------------------------------------------------------- conformance on fixture parts
def _prepare(tmp: Path, shape: Any, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    from build123d import export_step

    from aicad.assembly import geometry

    d = tmp / name
    d.mkdir(parents=True)
    export_step(shape, str(d / "src.step"))
    info = geometry.prepare(d, step=str(d / "src.step"))
    return info, json.loads((d / "refs.json").read_text())


def test_conformance_measures_features(tmp_path: Path) -> None:
    from build123d import Box, Cylinder, Pos

    from aicad import toolbox

    sk, ifs = icd.build(_parts(), "")
    doc_icd = {"version": 1, "interfaces": ifs}
    holes = [(-16.8, -6.8), (16.8, -6.8), (-16.8, 6.8), (16.8, 6.8)]

    def bracket(first: tuple[float, float], d0: float) -> Any:
        b = Box(60, 40, 8)
        for k, (x, y) in enumerate([first, *holes[1:]]):
            b = b - Pos(x, y, 0) * Cylinder((d0 if k == 0 else 6.6) / 2, 10)
        return b

    info, refs = _prepare(tmp_path, bracket(holes[0], 6.6), "good")
    res = conformance.measure(sk, doc_icd, BRACKET, info, refs)
    assert res["ok"] and res["envelope"]["ok"] and [r["interface"] for r in res["interfaces"]] == ["IF-01"]
    rows = res["interfaces"][0]["rows"]
    assert rows[0]["measured"] == "Z -4.000" and all(r["ok"] for r in rows) and len(rows) == 5
    assert rows[1]["d_mm"] == 6.6 and rows[1]["delta_mm"] == 0
    # hole 1 built 0.5 mm off in X and at Ø6.0: measured against specified, hand values
    info, refs = _prepare(tmp_path, bracket((-16.3, -6.8), 6.0), "bad")
    res = conformance.measure(sk, doc_icd, BRACKET, info, refs)
    assert not res["ok"]
    bad = [r for r in res["interfaces"][0]["rows"] if not r["ok"]]
    assert len(bad) == 1 and bad[0]["measured"] == "Ø6.000 at (-16.30, -6.80), 0.50 mm off position (±0.1)"
    assert bad[0]["spec"] == "Ø6.6 ±0.05 at (-16.80, -6.80)"
    f = conformance.findings(res)
    assert f == [("IF-01 Bracket ↔ Base plate: bolted joint: hole 1 specified Ø6.6 ±0.05 at (-16.80, -6.80), measured "
                  "Ø6.000 at (-16.30, -6.80), 0.50 mm off position (±0.1).")]
    # a part too big for its envelope
    info, refs = _prepare(tmp_path, Box(62, 40, 8), "big")
    res = conformance.measure(sk, doc_icd, BRACKET, info, refs)
    assert not res["envelope"]["ok"] and "outside in X" in res["envelope"]["measured"]
    # shaft / bore fits and gear teeth (a two-shaft gear pair)
    gplan = {"source": "standard", "summary": "", "assumptions": [], "subassemblies": [
        {"name": "Case", "description": "", "parts": [
            {"name": "Housing", "family": "machined", "complexity": 3, "qty": 1, "description": ""}]},
        {"name": "In", "description": "", "parts": [
            {"name": "Input shaft", "family": "turned", "complexity": 2, "qty": 1, "description": "Shaft Ø20 x 80 mm."},
            {"name": "Pinion", "family": "gear", "complexity": 2, "qty": 1, "description": "module 2, 18 teeth"}]},
        {"name": "Out", "description": "", "parts": [
            {"name": "Output shaft", "family": "turned", "complexity": 2, "qty": 1, "description": "Shaft Ø20 x 80 mm."},
            {"name": "Gear", "family": "gear", "complexity": 2, "qty": 1, "description": "module 2, 36 teeth"}]}]}
    gsk, gifs = icd.build(_parts(gplan), "")
    gd = {"version": 1, "interfaces": gifs}
    shaft, pinion = "i_s2_p2", "i_s2_p3"
    L = gsk["items"][shaft]["size"][2]
    for d, ok in ((20.0, True), (19.99, True), (20.05, False)):
        info, refs = _prepare(tmp_path, Cylinder(d / 2, L), f"shaft{d}")
        res = conformance.measure(gsk, gd, shaft, info, refs)
        boss = [r for x in res["interfaces"] for r in x["rows"] if r["feature"].startswith("shaft")]
        assert boss and all(r["ok"] == ok for r in boss), boss  # h6: 19.987 .. 20.000 (or nominal)
    for z, ok in ((18, True), (19, False)):
        g, _e = toolbox.build("spur_gear", M=2, Z=z, B=20, BORE=20)
        info, refs = _prepare(tmp_path, Pos(0, 0, -10) * g, f"gear{z}")
        res = conformance.measure(gsk, gd, pinion, info, refs)
        teeth = [r for x in res["interfaces"] for r in x["rows"] if "teeth" in r["feature"]]
        assert teeth and teeth[0]["ok"] == ok and f"× {z} teeth" in teeth[0]["measured"]


# ----------------------------------------------------------------------------- the running office (fake agents)
def _asm(c: Any) -> tuple[Path, Any]:
    from aicad.assembly import store as astore
    from aicad.platform.config import get_settings

    org = c.get("/api/auth/me").json()["org"]["id"]
    return astore.org_root(get_settings().data_dir, org), astore


def test_gate_placeholders_and_assembly_from_minute_one(office: Any) -> None:  # noqa: F811
    from test_platform import signup

    from aicad.assembly import store as astore

    c = office
    signup(c, "icd@x.com")
    r = c.post("/api/office/programs", json={"name": "ICD rig", "brief": "A test rig with a base and a drive.",
                                             "planner": "standard"})
    pid = r.json()["id"]
    v = c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={"plan": PLAN}).json()
    g = next(x for x in v["gates"] if x["code"] == "icd")
    assert g["status"] == "pending" and v["icd"]["status"] == "draft" and len(v["icd"]["interfaces"]) == 2
    assert any(i["kind"] == "icd" and i["program_id"] == pid for i in c.get("/api/office/home").json()["inbox"])
    r = c.post(f"/api/office/programs/{pid}/run")
    assert r.status_code == 409 and "interfaces" in r.json()["detail"]
    # edit at the gate: fewer, bigger holes on the spacer's bolt circle
    r = c.patch(f"/api/office/programs/{pid}/icd/interfaces/IF-02", json={"values": {"count": 3}})
    assert r.status_code == 200, r.text
    assert next(f for f in r.json()["icd"]["interfaces"] if f["id"] == "IF-02")["data"]["count"] == 3
    assert r.json()["icd"]["history"][-1]["kind"] == "edited"
    assert c.patch(f"/api/office/programs/{pid}/icd/interfaces/IF-02", json={"values": {"d": 40}}).status_code == 409
    assert c.post(f"/api/office/programs/{pid}/change-requests",
                  json={"interface": "IF-01", "values": {"d": 9}, "reason": "x"}).status_code == 409  # draft: edit
    v = c.post(f"/api/office/programs/{pid}/gates/icd/approve").json()
    assert next(x for x in v["gates"] if x["code"] == "icd")["status"] == "approved"
    assert c.patch(f"/api/office/programs/{pid}/icd/interfaces/IF-02", json={"values": {"count": 4}}).status_code == 409
    v = _wait(c, pid, lambda v: (v.get("assembly") or {}).get("status") == "ready")
    st = v["assembly"]
    assert st["clashes"] == [] and all(p["kind"] == "placeholder" for p in st["parts"].values())
    aroot, _ = _asm(c)
    # placeholder bodies carry their interface holes at the ICD positions (part frame)
    sk_bracket = astore.part(aroot, st["parts"][BRACKET]["key"])
    assert sk_bracket["kind"] == "placeholder" and sk_bracket["icd_version"] == 1
    hs = sorted((round(h["center"][0], 3), round(h["center"][1], 3), round(h["d"], 3)) for h in sk_bracket["info"]["holes"])
    assert hs == [(-16.8, -6.8, 6.6), (-16.8, 6.8, 6.6), (16.8, -6.8, 6.6), (16.8, 6.8, 6.6)]
    bb = sk_bracket["info"]["bbox"]
    assert [round(x, 6) for x in bb] == [-30, -20, -4, 30, 20, 4]
    # nested: one document per sub-assembly, the final one holds them as sub-assemblies
    final = astore.load(aroot, st["final"])
    assert [g["name"] for g in final["subassemblies"]] == ["Base", "Drive"]
    assert {g["assembly_id"] for g in final["subassemblies"]} == set(st["subs"].values())
    by_item = {i["office"]["item"]: i for i in final["instances"]}
    assert set(by_item) == {BASE, BRACKET, SPACER} and by_item[BASE]["fixed"]
    assert by_item[BASE]["sub"] != by_item[SPACER]["sub"]
    # mates by interface name: IF-01 (coincident + 2 concentric, inside "Base"), IF-02 (coincident + 2 concentric)
    tags = sorted((m["icd"], m["icd_role"], m["type"]) for m in final["mates"])
    assert tags == [("IF-01", "face", "coincident"), ("IF-01", "hole1", "concentric"), ("IF-01", "hole4", "concentric"),
                    ("IF-02", "face", "coincident"), ("IF-02", "hole1", "concentric"), ("IF-02", "hole3", "concentric")]
    assert all(not m.get("broken") for m in final["mates"]) and final["solve"]["conflicts"] == []
    assert all(final["solve"]["mates"][m["id"]]["ok"] for m in final["mates"])
    base_doc = astore.load(aroot, st["subs"]["i_s1"])
    assert len(base_doc["mates"]) == 3 and len(base_doc["instances"]) == 2
    # integration tickets open the level's document
    assert _tk(v, "Assemble Base")["assembly_id"] == st["subs"]["i_s1"]
    assert _tk(v, "Final assembly of ICD rig")["assembly_id"] == st["final"]
    # the live view: placeholders, parts with topology, exploded offsets, item states
    a = c.get(f"/api/office/programs/{pid}/assembly").json()
    assert a["status"] == "ready" and {i["kind"] for i in a["view"]["instances"]} == {"placeholder"}
    assert set(a["view"]["explode"]) == {i["id"] for i in a["view"]["instances"]}
    assert a["items"][BRACKET]["state"] == "placeholder" and a["items"]["i_s1_p3"]["state"] == "toolbox"
    assert c.get(a["view"]["instances"][0] and f"/api/m/assembly/parts/{a['view']['instances'][0]['part']}/topo").status_code == 200
    ev = [e["type"] for e in _events(c, pid)]
    assert "icd.drafted" in ev and "icd.edited" in ev and "assembly.updated" in ev
    # nested STEP export: two sub-assembly nodes, re-import verified
    r = c.post(f"/api/m/assembly/assemblies/{st['final']}/export")
    assert r.status_code == 200, r.text
    exp = r.json()["export"]
    assert exp["ok"] and exp["subassemblies"] == 2 and exp["instances"] == 3
    # Assembly Studio: insert a sub-assembly into a new assembly, refresh, remove
    new = c.post("/api/m/assembly/assemblies", json={"name": "Bench"}).json()["assembly"]["id"]
    r = c.post(f"/api/m/assembly/assemblies/{new}/subassemblies", json={"assembly_id": st["subs"]["i_s1"]})
    assert r.status_code == 200, r.text
    view = r.json()
    assert len(view["subassemblies"]) == 1 and not view["subassemblies"][0]["stale"]
    assert len(view["instances"]) == 2 and all(i["sub"] for i in view["instances"]) and len(view["mates"]) == 3
    assert any(i["fixed"] for i in view["instances"])
    gid = view["subassemblies"][0]["id"]
    ids = sorted(i["id"] for i in view["instances"])
    r = c.post(f"/api/m/assembly/assemblies/{new}/subassemblies/{gid}/refresh").json()
    assert sorted(i["id"] for i in r["instances"]) == ids  # same instances after a refresh
    assert c.post(f"/api/m/assembly/assemblies/{new}/subassemblies", json={"assembly_id": new}).status_code == 409
    r = c.delete(f"/api/m/assembly/assemblies/{new}/subassemblies/{gid}").json()
    assert r["instances"] == [] and r["subassemblies"] == []


def test_parts_swap_in_and_keep_every_mate(office: Any) -> None:  # noqa: F811
    from aicad.assembly import store as astore

    c = office
    fake_agents.SCRIPT.append((r"Design the Bracket", {"icd_shift": 0.5, "omit_turns": 1}))
    v = _program(c, "swap@x.com", PLAN)
    pid = v["id"]
    aroot, _ = _asm(c)
    before = astore.load(aroot, v["assembly"]["final"])
    ids_before = {i["office"]["item"]: i["id"] for i in before["instances"]}
    tags_before = sorted((m["icd"], m["icd_role"]) for m in before["mates"])
    c.post(f"/api/office/programs/{pid}/run")
    v = _wait(c, pid, lambda v: v["status"] == "complete", timeout=150)
    st = v["assembly"]
    assert all(p["kind"] == "real" for p in st["parts"].values()) and st["clashes"] == []
    final = astore.load(aroot, st["final"])
    parts_ = {i["office"]["item"]: i for i in final["instances"] if (i.get("office") or {}).get("item") in ids_before}
    assert {k: i["id"] for k, i in parts_.items()} == ids_before            # same instances
    assert all(i["source"]["kind"] == "project" for i in parts_.values())     # now the real parts
    tags_after = sorted((m["icd"], m["icd_role"]) for m in final["mates"] if m.get("icd"))
    assert tags_after == tags_before                                          # every mate re-attached by name
    assert all(not m.get("broken") and final["solve"]["mates"][m["id"]]["ok"] for m in final["mates"])
    # Gage measured the interfaces: the bracket's first build had hole 1 0.5 mm off, so it went back once
    br = _tk(v, "Bracket")
    gage_c = [cm["text"] for cm in br["comments"] if cm["by"].get("code") == "gage"]
    assert gage_c[0].startswith("Changes requested") and "measured Ø6.600 at (-16.30, -6.80), 0.50 mm off" in gage_c[0]
    assert gage_c[-1].startswith("Approved") and "match ICD v1" in gage_c[-1]
    assert br["icd_check"]["ok"] and br["fitted"] and br["column"] == "integrated"
    # Fitz fitted the four M6 bolts through the bracket joint (inside the Base sub-assembly)
    base_doc = astore.load(aroot, st["subs"]["i_s1"])
    assert sum(1 for g in base_doc["groups"] if g.get("kind") == "fastener") == 4
    assert sum(1 for g in final["groups"] if g.get("kind") == "fastener") >= 4
    ev = _events(c, pid)
    fitted = [e for e in ev if e["type"] == "ticket.fitted"]
    assert {e["data"]["item"] for e in fitted} == {BASE, BRACKET, SPACER}
    # the agents got their ICD excerpt; the Studio chat did not show it
    assert any("IF-01 Bracket ↔ Base plate" in p and "```fw-icd" in p for p in fake_agents.STATS["prompts"])
    from aicad.platform.routers.projects import _sessions

    shown = [e["text"] for e in _sessions[br["project_id"]].history if e["type"] == "user"]
    assert shown and all("fw-icd" not in m for m in shown)
    blob = " ".join(e["text"] for e in ev)
    for bad in ("model.py", "mcp__", "claude", ".json", "fw-icd"):
        assert bad not in blob


def test_change_request_accepted_updates_icd_reopens_and_regenerates(office: Any) -> None:  # noqa: F811
    from aicad.assembly import store as astore

    c = office
    # the bracket's designer asks for coarse clearance holes (Ø7, ISO 273 coarse for M6) at the same positions
    fake_agents.SCRIPT.append((r"Design the Bracket", {"cr": {"interface": "IF-01", "values": {"d": 7.0},
                                                              "reason": "The bracket is cast: coarse clearance."}}))
    v = _program(c, "cr@x.com", PLAN)
    pid = v["id"]
    c.post(f"/api/office/programs/{pid}/run")
    v = _wait(c, pid, lambda v: v["status"] == "complete", timeout=180)
    assert v["icd"]["version"] == 2
    cr = v["change_requests"][0]
    assert cr["id"] == "CR-1" and cr["status"] == "accepted" and cr["ticket_id"] == _tk(v, "Bracket")["id"]
    assert cr["before"] == {"d": 6.6} and cr["values"] == {"d": 7.0} and cr["version_after"] == 2
    assert sorted(cr["affected"]) == [BASE, BRACKET]
    h = v["icd"]["history"][-1]
    assert h["kind"] == "cr_accepted" and h["cr"] == "CR-1" and h["version"] == 2
    assert {"interface": "IF-01", "name": h["changes"][0]["name"], "field": "d", "before": 6.6, "after": 7.0} in h["changes"]
    f1 = next(f for f in v["icd"]["interfaces"] if f["id"] == "IF-01")
    assert f1["data"]["d"] == 7.0 and f1["crs"] == ["CR-1"]
    # both sides were measured against v2 at the end
    for title in ("Bracket", "Base plate"):
        t = _tk(v, title)
        assert t["icd_check"]["version"] == 2 and t["icd_check"]["ok"]
        holes = [r for x in t["icd_check"]["interfaces"] if x["interface"] == "IF-01" for r in x["rows"]
                 if r["feature"].startswith("hole")]
        assert holes and all(r["d_mm"] == 7.0 for r in holes)
    base = _tk(v, "Base plate")
    assert any("ICD v2 (CR-1)" in cm["text"] for cm in base["comments"] if cm["by"].get("code") == "archie")
    ev = _events(c, pid)
    types = [e["type"] for e in ev]
    assert "cr.raised" in types and "cr.accepted" in types
    regen = [e for e in ev if e["type"] == "assembly.updated" and "regenerated" in e["text"]]
    assert regen and "ICD v2 (CR-1)" in regen[0]["text"]
    # the delta reached the agents
    assert any("ICD v2 (CR-1)" in p and "IF-01 d: 6.6 → 7" in p for p in fake_agents.STATS["prompts"])
    aroot, _ = _asm(c)
    final = astore.load(aroot, v["assembly"]["final"])
    assert all(not m.get("broken") for m in final["mates"]) and v["assembly"]["clashes"] == []


def test_change_request_rejections(office: Any) -> None:  # noqa: F811
    c = office
    v = _program(c, "rej@x.com", PLAN)
    pid = v["id"]
    # holes that don't fit inside the frozen envelope: rejected by the rule, ICD unchanged
    r = c.post(f"/api/office/programs/{pid}/change-requests",
               json={"interface": "IF-01", "values": {"d": 30}, "reason": "Bigger bolts."})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["cr"]["status"] == "rejected" and v["icd"]["version"] == 1
    cr = v["change_requests"][0]
    assert "can't be built inside the frozen envelopes" in cr["decision"]["reason"]
    assert c.post(f"/api/office/programs/{pid}/change-requests",
                  json={"interface": "IF-09", "values": {"d": 9}, "reason": "x"}).status_code == 409
    assert c.post(f"/api/office/programs/{pid}/change-requests",
                  json={"interface": "IF-01", "values": {"fit": "H7/h6"}, "reason": "x"}).status_code == 409
    # an Archie-planned program: the rule accepts, Archie's note rejects (simulated, metered)
    from aicad.office import store
    from aicad.platform.config import get_settings

    org = c.get("/api/auth/me").json()["org"]["id"]
    root = store.org_root(get_settings().data_dir, org)
    with store.lock(pid):
        doc = store.load(root, pid)
        doc["planner"] = "archie"
        store.save(root, doc)
    # M8 holes (Ø9) at 13.6 mm centres: the M8 washers (Ø16) would overlap, so the rule says no
    v = c.post(f"/api/office/programs/{pid}/change-requests",
               json={"interface": "IF-01", "values": {"d": 9}, "reason": "M8 please."}).json()
    assert v["cr"]["status"] == "rejected"
    assert "washers (Ø16) overlap at 13.6 mm" in v["change_requests"][1]["decision"]["reason"]
    fake_agents.SCRIPT.append((r"CR-3", {"cr_reject": True}))
    v = c.post(f"/api/office/programs/{pid}/change-requests",
               json={"interface": "IF-01", "values": {"d": 7}, "reason": "Coarse clearance."}).json()
    cr2 = v["change_requests"][2]
    assert cr2["status"] == "rejected" and cr2["decision"]["reason"].startswith("Archie's review:")
    assert cr2["decision"]["tokens"] > 0 and v["icd"]["version"] == 1
    # the same change without Archie's objection is accepted: v2, both parts' placeholders regenerated
    fake_agents.SCRIPT.clear()
    v = c.post(f"/api/office/programs/{pid}/change-requests",
               json={"interface": "IF-01", "values": {"d": 7}, "reason": "Coarse clearance."}).json()
    assert v["cr"]["status"] == "accepted" and v["icd"]["version"] == 2
    keys = v["assembly"]["parts"]
    assert keys[BRACKET]["icd_version"] == 2 and keys[BASE]["icd_version"] == 2 and keys[SPACER]["icd_version"] == 1
    ev = [e["type"] for e in _events(c, pid)]
    assert ev.count("cr.rejected") == 3 and ev.count("cr.accepted") == 1


def test_interfaces_rule_unit(tmp_path: Path) -> None:
    """Archie's deterministic rule without the server: an integrated side refuses the change."""
    doc = service.new_program("Rig", "A test rig.", "org1", "u1", 3, 3000, "standard")
    doc["plan"] = {**planner.normalise_plan(PLAN, "standard"), "narrative": "", "note": None}  # type: ignore[dict-item]
    doc["status"] = "plan_review"
    (tmp_path / doc["id"]).mkdir()
    service.approve_plan(tmp_path, doc, None, service.user_actor("Eng"))
    interfaces.approve(tmp_path, doc, service.user_actor("Eng"))
    c = interfaces.raise_cr(tmp_path, doc, "IF-01", {"d": 7}, "coarse", service.user_actor("Eng"))
    assert interfaces.evaluate(doc, c)["ok"]
    next(t for t in doc["tickets"] if t["item_id"] == BRACKET)["column"] = "integrated"
    ev = interfaces.evaluate(doc, c)
    assert not ev["ok"] and "already integrated" in ev["reason"]
    out = interfaces.decide(tmp_path, doc, c["id"], service.agent_actor("archie"))
    assert not out["accepted"] and doc["icd"]["version"] == 1 and c["status"] == "rejected"
    # values equal to the ICD are not a change
    c2 = interfaces.raise_cr(tmp_path, doc, "IF-02", {"count": 4}, "same", service.user_actor("Eng"))
    assert "already says" in interfaces.evaluate(doc, c2)["reason"]


def test_icd_tenant_isolation(office: Any) -> None:  # noqa: F811
    from test_platform import signup

    c = office
    v = _program(c, "own4@x.com", PLAN)
    pid = v["id"]
    c.post("/api/auth/logout")
    signup(c, "intruder4@x.com", workspace="Other Co")
    assert c.get(f"/api/office/programs/{pid}/assembly").status_code == 404
    assert c.patch(f"/api/office/programs/{pid}/icd/interfaces/IF-01", json={"values": {"d": 9}}).status_code == 404
    assert c.post(f"/api/office/programs/{pid}/gates/icd/approve").status_code == 404
    assert c.post(f"/api/office/programs/{pid}/change-requests",
                  json={"interface": "IF-01", "values": {"d": 9}, "reason": "x"}).status_code == 404
    assert c.post(f"/api/office/programs/{pid}/assembly/rebuild").status_code == 404
    # nor the other org's assembly documents
    assert c.get(f"/api/m/assembly/assemblies/{v['assembly']['final']}").status_code == 404


def test_hole_pattern_math() -> None:
    """Bolt circle positions are on the PCD (hand: radius 6.5 at 45 deg, 135 deg ...)."""
    _sk, ifs = icd.build(_parts(), "")
    c = ifs[1]["data"]["centre"]
    for x, y in ifs[1]["data"]["positions"]:
        assert abs(math.hypot(x - c[0], y - c[1]) - 6.5) < 0.01
