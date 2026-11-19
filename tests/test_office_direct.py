"""Direct design (no AI): Design Office parts the approved ICD fixes completely are built from it, through the same
build and check gate as an agent's build. The founder's test case is a 1:3 spur pair (m2, 20 / 60 teeth) on two Ø20
shafts in four 6204 bearings, no housing. Every expected value below is a hand calculation from the ICD and the
standards, never a measurement of the built part. No live AI (fake agents)."""

from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path
from typing import Any

import pytest
from test_office_orchestrator import _wait, office  # noqa: F401  (fixture)
from test_office_shaft_line import PAIR, PIN, S_IN, S_OUT, _b, _g, _parts, _plan

from aicad.office import conformance, direct, icd

BRIEF = "Simple spur gear pair 1:3 with shafts and bearings, no housing."


def _doc(plan: dict[str, Any], brief: str = BRIEF, status: str = "approved") -> dict[str, Any]:
    parts = _parts(plan)
    sk, ifs = icd.build(parts, brief)
    return {"skeleton": sk, "icd": {"version": 1, "status": status, "interfaces": ifs}, "brief": brief,
            "items": [{"id": p["id"], "name": p["name"], "description": p["description"]} for p in parts]}


def _t(doc: dict[str, Any], item: str) -> dict[str, Any]:
    it = next(i for i in doc["items"] if i["id"] == item)
    return {"kind": "part", "item_id": item, "title": it["name"], "qty": 1}


def _s(name: str, desc: str) -> dict[str, Any]:
    return {"name": name, "family": "turned", "complexity": 2, "qty": 1, "description": desc}


def _num(src: str, name: str) -> float:
    m = re.search(rf"^{name} = (-?\d+(?:\.\d+)?)", src, re.MULTILINE)
    assert m, f"{name} not in the script"
    return float(m.group(1))


KEYED = _plan(_g("Pinion", "spur pinion m2 20 teeth, keyed"), _g("Gear", "m2 60 teeth keyed"),
              _s("Input shaft", "shaft 20 mm diameter, 120 long"), _s("Output shaft", "shaft 20 mm diameter, 120 long"),
              _b(4))
STEPPED = _plan(_g("Pinion", "spur pinion m2 20 teeth, keyed"), _g("Gear", "m2 60 teeth keyed"),
                _s("Input shaft", "shaft 25 mm diameter, 140 long"), _s("Output shaft", "shaft 25 mm diameter, 140 long"),
                _s("Spacer", "spacer sleeve"), _b(4))


# ---------------------------------------------------------------------------- the decision, hand checked
def test_founders_case_is_built_from_the_interfaces() -> None:
    doc = _doc(PAIR)
    p = direct.plan(doc, _t(doc, S_IN))
    assert p["path"] == "direct" and p["kind"] == "shaft", p
    src = p["script"]
    # Ø20 = the 6204's bore (ISO 15: d 20, D 47, B 14), so the journals are plain: one Ø20 diameter end to end;
    # 120 long as written and as the skeleton keeps it (journals Z -29..-15 / 15..29 inside -60..60)
    assert (_num(src, "LENGTH"), _num(src, "D")) == (120, 20)
    assert "D_JOURNAL" not in src and "fw.shaft_keyway" not in src
    # every interface it carries is named in the header, with its span
    assert "IF-01  bearing journal for the 6204: Ø20 k6, Z -29 to -15" in src
    assert "IF-02  bearing journal for the 6204: Ø20 k6, Z 15 to 29" in src
    assert "IF-03  seat for the Pinion: Ø20 k6, Z -10 to 10" in src
    # a normal Studio script: driving dimensions as plain literals, PARAMS, PARAM_META, EXPECTED from fw helpers
    assert 'NAME = "Input shaft"' in src and 'MATERIAL = "Steel 1045 (medium carbon)"' in src
    assert "PARAMS = dict(LENGTH=LENGTH, D=D, CHAMFER=CHAMFER)" in src and "PARAM_META = {" in src
    assert 'EXPECTED = {"bbox": shaft["bbox"]' in src and "z0=-LENGTH / 2" in src
    # never an agent internal in what the engineer reads
    assert not re.search(r"office|direct|agent|claude|model id|\.py\b", src, re.IGNORECASE)
    # the gears: module 2, 20 / 60 teeth, face width 10 m = 20, bore Ø20; tip Ø m (z + 2) = 44 / 124 fits the envelope
    g = direct.plan(doc, _t(doc, PIN))
    assert g["path"] == "direct" and g["kind"] == "gear"
    assert [_num(g["script"], k) for k in ("MODULE", "TEETH", "FACE_WIDTH", "BORE", "PRESSURE_ANGLE")] == [2, 20, 20, 20, 20]
    assert doc["skeleton"]["items"][PIN]["size"][0] == 2 * (20 + 2)


def test_keyways_and_shoulders_hand_checked() -> None:
    # keyed gears on Ø20 shafts: DIN 6885-1 for d over 17 up to 22 is b 6, h 6, t1 3.5 (shaft), t2 2.8 (hub)
    doc = _doc(KEYED)
    p = direct.plan(doc, _t(doc, S_IN))
    assert p["path"] == "direct"
    sp = direct._shaft_spec(doc["skeleton"], doc["icd"]["interfaces"], S_IN, doc["skeleton"]["items"][S_IN])
    (k,) = sp["keyways"]
    assert (k["b"], k["t1"], k["din"]) == (6, 3.5, True)
    # the key is 2 mm shorter than the 20 mm hub, rounded down: 18, centred on the hub (Z -9..9); its side is +X
    # (the program's +X, the shaft frame is not turned)
    assert (k["z0"], k["z1"], k["angle"]) == (-9, 9, 0)
    assert "fw.shaft_keyway(part, d=D, z_center=-LENGTH / 2 + KEY_START + KEY_LENGTH / 2, length=KEY_LENGTH, angle=0)" \
        in p["script"] and _num(p["script"], "KEY_START") == 60 - 9 and _num(p["script"], "KEY_LENGTH") == 18
    gp = direct._gear_spec(doc["skeleton"], doc["icd"]["interfaces"], PIN, doc["skeleton"]["items"][PIN])
    assert (gp["keyway"]["b"], gp["keyway"]["t2"], gp["keyway"]["din"]) == (6, 2.8, True)
    # the output gear is turned half a pitch for its mesh (360 / 60 / 2 = 3 deg): its keyway, at program +X, sits at
    # -3 deg in the gear's own frame
    gear = next(i for i, v in doc["skeleton"]["items"].items() if v["name"] == "Gear")
    gg = direct._gear_spec(doc["skeleton"], doc["icd"]["interfaces"], gear, doc["skeleton"]["items"][gear])
    assert gg["keyway"]["angle"] == -3.0
    # a Ø25 shaft in 6204s (bore 20): journals turned down to Ø20 from each end to the bearing's inner face, with
    # shoulders there. Input shaft 140 long centred on Y 9 (program -61..79), bearings' inner faces at Y -15 and 33:
    # each journal is 46 long, the Ø25 body 140 - 2 x 46 = 48
    doc = _doc(STEPPED)
    p = direct.plan(doc, _t(doc, S_IN))
    src = p["script"]
    assert [_num(src, k) for k in ("LENGTH", "D", "D_JOURNAL", "L_JOURNAL_1", "L_JOURNAL_2")] == [140, 25, 20, 46, 46]
    assert "body = LENGTH - L_JOURNAL_1 - L_JOURNAL_2" in src and _num(src, "FILLET") == 0.5
    sp = direct._shaft_spec(doc["skeleton"], doc["icd"]["interfaces"], S_IN, doc["skeleton"]["items"][S_IN])
    assert [(s["d"], s["z1"] - s["z0"]) for s in sp["segments"]] == [(20, 46), (25, 48), (20, 46)]
    # DIN 6885 for d over 22 up to 30: b 8, t1 4
    assert [(k["b"], k["t1"]) for k in sp["keyways"]] == [(8, 4)]
    spacer = next(i for i, v in doc["skeleton"]["items"].items() if v["name"] == "Spacer")
    s2 = direct.plan(doc, _t(doc, spacer))
    assert s2["path"] == "direct" and s2["kind"] == "spacer" and _num(s2["script"], "BORE") == 25


def test_what_goes_to_the_agent() -> None:
    doc = _doc(PAIR)
    # no approved interfaces: nothing is fixed yet
    d0 = _doc(PAIR, status="draft")
    assert direct.plan(d0, _t(d0, S_IN)) == {"path": "agent", "reasons": ["the program has no approved interfaces"]}
    # standard parts never (Hex / the Toolbox), and parts this path doesn't build
    assert direct.plan(doc, {**_t(doc, S_IN), "kind": "standard"})["path"] == "agent"

    def with_desc(item: str, desc: str, d: dict[str, Any] = doc) -> dict[str, Any]:
        dd = copy.deepcopy(d)
        next(i for i in dd["items"] if i["id"] == item)["description"] = desc
        return direct.plan(dd, _t(dd, item))

    # a brief asking for more than the interfaces: the agent, starting from the interface model (seed)
    r = with_desc(S_IN, "shaft 20 mm diameter, 120 long, M12 thread on the output end")
    assert r["path"] == "agent" and r["reasons"] == ["the brief asks for a thread"] and r["seed"]["kind"] == "shaft"
    r = with_desc(S_IN, "shaft 20 mm diameter, 120 long with a circlip groove")
    assert r["reasons"] == ["the brief asks for a groove or circlip"]
    r = with_desc(S_IN, "Shaft Ø20 x 120 with a collar Ø30 x 10")
    assert "the brief gives a size the interfaces don't explain (Ø30)" in r["reasons"]
    r = with_desc(PIN, "spur pinion m2 20 teeth with a hub Ø36 x 15")
    assert "the brief asks for a hub the interfaces don't size" in r["reasons"]
    r = with_desc(PIN, "spur pinion m2 20 teeth, keyed")  # the ICD has no key (built before "keyed" was written)
    assert r["reasons"] == ["the brief asks for a key the interfaces don't size"]
    # a module is not a thread, and the planned size the layout superseded is not an extra
    assert with_desc(PIN, "spur pinion M2, 20 teeth")["path"] == "direct"
    assert with_desc(S_IN, "Shaft Ø20 x 100")["path"] == "direct"
    # a material in the brief is used (word-bounded: "plate" is not PLA)
    assert with_desc(S_IN, "shaft 20 mm diameter, 120 long, stainless")["material"] == "Stainless 304"
    # program-brief sentences about shafts count for the shafts only
    dd = copy.deepcopy(doc)
    dd["brief"] = "A spur gear pair 1:3. The shafts have splined ends."
    assert direct.plan(dd, _t(dd, S_IN))["reasons"] == ["the brief asks for a spline"]
    assert direct.plan(dd, _t(dd, PIN))["path"] == "direct"
    # an incomplete ICD (the gear seat without its position along the shaft): the agent, without a seed
    dd = copy.deepcopy(doc)
    next(f for f in dd["icd"]["interfaces"] if f["id"] == "IF-03")["data"]["z"] = None
    r = direct.plan(dd, _t(dd, S_IN))
    assert r == {"path": "agent", "reasons": ["the interfaces of this part are incomplete"]}
    dd = copy.deepcopy(doc)  # a journal without its bearing data
    del next(f for f in dd["icd"]["interfaces"] if f["id"] == "IF-01")["data"]["journal_z"]
    assert direct.plan(dd, _t(dd, S_IN))["reasons"] == ["the interfaces of this part are incomplete"]
    # a block, a pulley: the designer
    db = _doc(_plan({"name": "Base plate", "family": "machined", "complexity": 2, "qty": 1,
                     "description": "Plate 300 x 150 x 15"}, _g("Pinion", "m2 20 teeth"), _g("Gear", "m2 60 teeth"),
                    _s("Input shaft", "Shaft Ø20 x 100"), _s("Output shaft", "Shaft Ø20 x 100"), _b(4)))
    plate = next(i for i, v in db["skeleton"]["items"].items() if v["name"] == "Base plate")
    assert direct.plan(db, _t(db, plate))["reasons"][0].startswith("a block or plate needs the designer")
    # the block layout's vertical shafts are built direct too (end face flush with the plate's bottom)
    shaft = next(i for i, v in db["skeleton"]["items"].items() if v["name"] == "Input shaft")
    assert direct.plan(db, _t(db, shaft))["path"] == "direct"


def test_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    assert direct.enabled({}) and not direct.enabled({"direct_build": False})
    monkeypatch.setenv(direct.ENV, "0")
    assert not direct.enabled({})


# ---------------------------------------------------------------------------- the build gate, hand checked
def _gate(tmp: Path, doc: dict[str, Any], item: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    from aicad.agent import runner
    from aicad.assembly import geometry

    p = direct.plan(doc, _t(doc, item))
    script = p.get("script") or p["seed"]["script"]
    ws = tmp / f"{item}_{direct.sha(script)}"
    (ws / "out").mkdir(parents=True)
    (ws / "model.py").write_text(script, encoding="utf-8")
    runner.main(ws / "model.py", ws / "out", determinism=True, fast=False)
    st = json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
    info = geometry.prepare(ws / "snap", step=str(ws / "out" / "part.step"))
    res = conformance.measure(doc["skeleton"], doc["icd"], item, info, json.loads((ws / "snap" / "refs.json").read_text()))
    return st, res, script


def test_built_parts_pass_the_gate_and_conform(tmp_path: Path) -> None:
    from aicad.agent import runner

    doc = _doc(PAIR)
    st, res, _src = _gate(tmp_path, doc, S_IN)
    assert runner.is_verified(st), [c for c in st["checks"] if not c["passed"]]
    assert {c["id"] for c in st["checks"] if c["passed"]} >= {"CHK-02", "CHK-03", "CHK-04", "CHK-05", "CHK-07", "CHK-08"}
    assert res["ok"] and res["envelope"]["ok"], [r for x in res["interfaces"] for r in x["rows"] if not r["ok"]]
    # hand: Ø20 x 120 less two 1 x 45 deg end chamfers (Pappus: triangle 1/2 at r 10 - 1/3)
    v = math.pi * 10 ** 2 * 120 - 2 * 0.5 * 2 * math.pi * (10 - 1 / 3)
    assert st["fingerprint"]["volume"] == pytest.approx(v, rel=1e-6)
    assert st["fingerprint"]["bbox"] == pytest.approx([20, 20, 120], abs=1e-6)
    assert st["editable_params"] == {"LENGTH": 120.0, "D": 20.0, "CHAMFER": 1.0}
    assert st["param_meta"]["LENGTH"]["unit"] == "mm" and st["param_meta"]["LENGTH"]["min"] <= 120
    # the keyed pinion: tip Ø m (z + 2) = 44, Ø20 bore with a DIN 6885 6 x 2.8 hub keyway, a tooth on +X
    kd = _doc(KEYED)
    st, res, _src = _gate(tmp_path, kd, PIN)
    assert runner.is_verified(st) and res["ok"], [r for x in res["interfaces"] for r in x["rows"] if not r["ok"]]
    assert st["fingerprint"]["bbox"][0] == pytest.approx(44, abs=1e-6)  # 20 teeth: tooth tips on +X and -X
    rows = {r["feature"]: r for x in res["interfaces"] for r in x["rows"]}
    kw = next(r for k, r in rows.items() if k.startswith("keyway"))
    assert kw["width_mm"] == pytest.approx(6, abs=1e-6) and kw["depth_mm"] == pytest.approx(2.8, abs=1e-6)
    # the keyed shaft: DIN 6885 keyseat 6 wide, 3.5 deep (t1) for d = 20
    st, res, _src = _gate(tmp_path, kd, S_OUT)
    assert runner.is_verified(st) and res["ok"]
    kw = next(r for x in res["interfaces"] for r in x["rows"] if r["feature"].startswith("keyway"))
    assert kw["width_mm"] == pytest.approx(6, abs=1e-6) and kw["depth_mm"] == pytest.approx(3.5, abs=1e-6)
    # the stepped shaft with shoulders and the spacer
    sd = _doc(STEPPED)
    st, res, _src = _gate(tmp_path, sd, S_IN)
    assert runner.is_verified(st) and res["ok"], [r for x in res["interfaces"] for r in x["rows"] if not r["ok"]]
    spacer = next(i for i, v in sd["skeleton"]["items"].items() if v["name"] == "Spacer")
    st, res, _src = _gate(tmp_path, sd, spacer)
    it = sd["skeleton"]["items"][spacer]
    OD, H, c = it["size"][0], it["size"][2], 0.5
    v = math.pi / 4 * (OD ** 2 - 25 ** 2) * H - 2 * c * c / 2 * 2 * math.pi * (OD / 2 - c / 3)
    assert runner.is_verified(st) and res["ok"] and st["fingerprint"]["volume"] == pytest.approx(v, rel=1e-6)


def test_fw_std_placement_options(tmp_path: Path) -> None:
    """The new keyword options keep the hand formulas: z0 moves, keyway angles turn, volumes are unchanged."""
    from aicad import fw_std

    _a, ea = fw_std.stepped_shaft([(20, 30), (25, 40)], chamfer=1, fillet=0.5)
    b, eb = fw_std.stepped_shaft([(20, 30), (25, 40)], chamfer=1, fillet=0.5, z0=-35)
    assert ea["volume"] == eb["volume"] and b.bounding_box().min.Z == pytest.approx(-35, abs=1e-6)
    assert b.volume == pytest.approx(eb["volume"], rel=1e-6)
    p, cut = fw_std.shaft_keyway(b, d=25, z_center=15, length=20, angle=0)  # Z 5..25, all on the Ø25 (Z -5..35)
    bb = p.bounding_box()
    assert cut > 0 and p.volume == pytest.approx(eb["volume"] - cut, rel=1e-5)
    assert bb.max.X == pytest.approx(12.5, abs=1e-6)  # the keyseat is on +X: the Ø25 still reaches X 12.5 elsewhere
    g, eg = fw_std.spur_gear(2, 20, 20, bore=20, keyway=True, keyway_angle=0, z0=-10)
    assert g.bounding_box().min.Z == pytest.approx(-10, abs=1e-6) and g.volume == pytest.approx(eg["volume"], rel=1e-4)


# ---------------------------------------------------------------------------- the program (simulated agents)
def test_founders_program_needs_no_ai(office: Any) -> None:  # noqa: F811
    from test_office_orchestrator import _program

    from aicad.office import fake_agents

    c = office
    v = _program(c, "direct@x.com", PAIR, brief=BRIEF)
    pid = v["id"]
    c.post(f"/api/office/programs/{pid}/run")
    v = _wait(c, pid, lambda v: v["orchestrator"]["state"] in ("complete", "blocked", "stopped"), timeout=1500)
    assert v["status"] == "complete", [(t["title"], t["column"], (t.get("run") or {}).get("status")) for t in v["tickets"]]
    by = {t["title"]: t for t in v["tickets"]}
    summary = {"Input shaft": "shaft Ø20 × 120, 2 bearing journals, 1 seat",
               "Output shaft": "shaft Ø20 × 120, 2 bearing journals, 1 seat",
               "Pinion": "spur gear m2 × 20 teeth, face 20, bore Ø20", "Gear": "spur gear m2 × 60 teeth, face 20, bore Ø20"}
    for name in ("Input shaft", "Output shaft", "Pinion", "Gear"):
        t = by[name]
        d = t["direct"]
        assert d["path"] == "direct" and d["label"] == "Built from the interface spec (no AI)", d
        assert t["tokens"] == 0 and (t.get("review_tokens") or 0) == 0 and not t.get("reuse")
        assert d["seconds"] < 120 and d["summary"] == summary[name]
        gage_note = next(cm["text"] for cm in t["comments"] if cm["by"].get("code") == "gage")
        assert gage_note.startswith("Approved") and "built from the interface spec (no AI)" in gage_note
        assert t["calibrated"]["learned"] is False  # seconds of building don't teach the designer's rate
    # not one design agent turn: the shafts and gears were built from the ICD, the bearings came from the Toolbox
    assert fake_agents.STATS["prompts"] == []
    assert by["Deep groove ball bearing 6204"]["reuse"]["source"] == "toolbox"
    # the Studio part is a normal, editable model: tune it without tokens (DS-003 parameter edit)
    pj = by["Input shaft"]["project_id"]
    assert c.get(f"/api/projects/{pj}/params").json()["editable"] == {"LENGTH": 120.0, "D": 20.0, "CHAMFER": 1.0}
    r = c.post(f"/api/projects/{pj}/params", json={"values": {"CHAMFER": 0.5}})
    assert r.status_code == 200 and r.json()["changed"] == {"CHAMFER": {"from": 1.0, "to": 0.5}}, r.text
    revs = c.get(f"/api/projects/{pj}/revisions").json()["items"]
    assert [(r["n"], r["kind"]) for r in revs] == [(2, "params"), (1, "interface")], revs
    assert revs[1]["why"].startswith("Design Office: built from the interface spec (no AI): shaft Ø20 × 120")
    assert revs[1]["ok"]
    # the assembly holds the real shafts and gears with the four bearings on their journals, no clash
    st = v["assembly"]
    assert st["clashes"] == [] and not any(p["kind"] == "placeholder" for p in st["parts"].values())


def test_viewport_dimensions_map_the_shaft_parameters(tmp_path: Path) -> None:
    """DS-038: the generated parameters are real on-model dimensions (no AI): the stepped shaft's length, both
    diameters, the journal lengths (46 each, hand: shaft end to the bearing's inner face) and the keyseat."""
    from aicad import dims

    doc = _doc(STEPPED)
    f = tmp_path / "model.py"
    f.write_text(direct.plan(doc, _t(doc, S_IN))["script"], encoding="utf-8")
    m = {d["param"]: d for d in dims.map_script(f)["dims"]}
    assert (m["D"]["kind"], m["D_JOURNAL"]["kind"]) == ("diameter", "diameter")
    assert [(m[k]["kind"], m[k]["s"]) for k in ("LENGTH", "L_JOURNAL_1", "L_JOURNAL_2", "KEY_LENGTH", "KEY_START")] == [
        ("linear", pytest.approx(140)), ("linear", pytest.approx(46)), ("linear", pytest.approx(46)),
        ("linear", pytest.approx(18)), ("linear", pytest.approx(52))]


def test_the_plan_s_gear_keeps_its_keyway_and_material() -> None:
    """Live run 2026-11-19 (master): the plan's pinion was swapped for a plain Toolbox gear and lost its ICD keyway
    and its 42CrMo4. A designed gear the ICD fixes is built from it instead (Hex leaves it to the designer)."""
    from aicad.office import platform_env

    doc = _doc(_plan(_g("Pinion", "spur pinion m2 20 teeth, keyed, 42CrMo4"), _g("Gear", "m2 60 teeth keyed"),
                     _s("Input shaft", "shaft 20 mm diameter, 120 long"),
                     _s("Output shaft", "shaft 20 mm diameter, 120 long"), _b(4)))
    t = _t(doc, PIN)
    assert platform_env.hex_lookup(doc, t, []) is None
    p = direct.plan(doc, t)
    assert p["path"] == "direct" and p["material"] == "Steel 4140 (alloy)"
    assert "keyway=True" in p["script"] and "IF-04  hub keyway 6 × 2.8 (DIN 6885-1 A) through the bore" in p["script"]


def test_circlip_grooves_and_bearing_corner_from_interface_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Grooves and bearing corner chamfers are read generically from the interface data (a parallel branch adds DIN
    471 circlips to the ICD): a groove for a circlip just outside the +Z bearing, DIN 471 for d1 = 20: d2 19.0,
    m 1.3 (verify against the standard). Removed: pi / 4 (20^2 - 19^2) x 1.3."""
    from aicad.agent import runner

    doc = _doc(PAIR)
    real = icd.item_features

    def with_groove(skel: Any, ifs: Any, item: str) -> list[dict[str, Any]]:
        out = real(skel, ifs, item)
        if item == S_IN:
            out.append({"type": "groove", "on": "shaft", "c": [0.0, 0.0], "z": 29.65, "m": 1.3, "d2": 19.0,
                        "label": "circlip groove (DIN 471, 20 x 1.2)", "if": "IF-02"})
        return out
    monkeypatch.setattr(icd, "item_features", with_groove)
    p = direct.plan(doc, _t(doc, S_IN))
    assert p["path"] == "direct" and "1 circlip groove" in p["summary"]
    src = p["script"]
    assert (_num(src, "GROOVE_D"), _num(src, "GROOVE_WIDTH"), _num(src, "GROOVE_START")) == (19, 1.3, 60 + 29)
    ws = tmp_path / "g"
    (ws / "out").mkdir(parents=True)
    (ws / "model.py").write_text(src, encoding="utf-8")
    runner.main(ws / "model.py", ws / "out", determinism=False, fast=False)
    st = json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
    v = math.pi * 10 ** 2 * 120 - 2 * 0.5 * 2 * math.pi * (10 - 1 / 3) - math.pi / 4 * (20 ** 2 - 19 ** 2) * 1.3
    assert st["ok"] and st["fingerprint"]["volume"] == pytest.approx(v, rel=1e-6)
    # a brief that says "circlip" is no extra when the interfaces place the groove
    dd = copy.deepcopy(doc)
    next(i for i in dd["items"] if i["id"] == S_IN)["description"] = "shaft 20 mm diameter, 120 long, circlips"
    assert direct.plan(dd, _t(dd, S_IN))["path"] == "direct"
    # the shoulder fillet stays under the bearing's corner chamfer when the interface gives it (r_s min 0.6 -> 0.48)
    monkeypatch.setattr(icd, "item_features", real)
    sd = _doc(STEPPED)
    for f in sd["icd"]["interfaces"]:
        if f["kind"] == "bearing_journal":
            f["data"]["r_s_min"] = 0.6
    assert _num(direct.plan(sd, _t(sd, S_IN))["script"], "FILLET") == 0.48
