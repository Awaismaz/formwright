"""Parametric generators for the Design Office's direct path (WORKLIST 45) and workspace templates (WORKLIST 48).

Every expected value is a hand calculation from the ICD and the standards, never a measurement of the built part:

* reducer (golden case c, the founder's plan): m2, 20 / 60 teeth: a = m (z1 + z2) / 2 = 80; 6204 (d 20, D 47, B 14),
  6205 (d 25, D 52, B 15) (ISO 15). Cap screws M6: tap drill 5.0 (ISO 2306), clearance 6.6 (ISO 273); ligament
  max(3, 0.5 x 6) = 3, so PCD = D + 5 + 2 x 3 = 58 (input) and 63 (output). Wall rule: max(B + 4, cap screw depth
  2.5 x 6 + 3 = 18, + 3, 12) = max(19, 21, 12) = 21 <= the ICD's 24.
* open input cap: Ø70 x 18, the Ø25 shaft passes a Ø27 bore; DIN 3760 seal for d 25: 25 x 40 x 7.
* pulley (connection-layout golden "pulley pair"): Ø60 x 20, bore Ø20, DIN 6885 keyway b 6, t2 2.8.
* timing pulley: HTD 5M, 24 teeth: pitch Ø = z p / π = 24 x 5 / π = 38.197.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import pytest

from aicad import fw_std
from aicad.graph import compile as gc
from aicad.graph import intent
from aicad.office import direct, icd, templates

GC = Path(__file__).resolve().parents[1] / "src" / "aicad" / "eval" / "golden_cases"
G2 = Path(__file__).parent / "golden" / "connection_layout"


def _plan_doc(case: str, brief: str) -> dict[str, Any]:
    plan = json.loads((GC / f"{case}.plan.json").read_text(encoding="utf-8"))
    parts = []
    for si, s in enumerate(plan["subassemblies"], start=1):
        for p in s["parts"]:
            n = len(parts) + 1
            parts.append({"id": f"i_s{si}_p{n}", "name": p["name"], "family": p["family"], "qty": p.get("qty", 1),
                          "description": p.get("description", ""), "complexity": p.get("complexity", 2),
                          "sub": f"i_s{si}", **{k: p[k] for k in ("envelope", "mounts_on", "module", "teeth") if k in p}})
    sk, ifs = icd.build(parts, brief)
    return {"id": "prog1", "name": "Golden", "skeleton": sk, "icd": {"version": 1, "status": "approved", "interfaces": ifs},
            "brief": brief, "plan": plan,
            "items": [{"id": p["id"], "name": p["name"], "description": p["description"]} for p in parts]}


def _graph_doc(path: Path) -> dict[str, Any]:
    d = json.loads(path.read_text(encoding="utf-8"))
    g, _iss, _qs = intent.compile_reply(d["reply"], d["name"], d["brief"])
    plan = gc.to_plan(g, resolved=True)
    sk, ifs = gc.to_icd(g, plan)
    parts = gc.plan_parts(plan)
    return {"id": "prog2", "name": d["name"], "skeleton": sk, "icd": {"version": 1, "status": "approved", "interfaces": ifs},
            "brief": d["brief"], "plan": {**plan, "graph": {"data": g.dump()}},
            "items": [{"id": p["id"], "name": p["name"], "description": p["description"]} for p in parts]}


REDUCER_BRIEF = "Build a Single stage 3:1 reducer with Spur Gears"


def _id(doc: dict[str, Any], name: str) -> str:
    return next(i["id"] for i in doc["items"] if i["name"] == name)


def _t(doc: dict[str, Any], name: str) -> dict[str, Any]:
    return {"kind": "part", "item_id": _id(doc, name), "title": name, "qty": 1, "id": f"t_{_id(doc, name)}"}


def _num(src: str, name: str) -> float:
    m = re.search(rf"^{name} = (-?\d+(?:\.\d+)?)", src, re.MULTILINE)
    assert m, f"{name} not in the script"
    return float(m.group(1))


def _gate(tmp: Path, doc: dict[str, Any], name: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    from aicad.agent import runner
    from aicad.assembly import geometry
    from aicad.office import conformance

    p = direct.plan(doc, _t(doc, name))
    script = p.get("script") or p["seed"]["script"]
    ws = tmp / f"{name.replace(' ', '_')}_{direct.sha(script)}"
    (ws / "out").mkdir(parents=True)
    (ws / "model.py").write_text(script, encoding="utf-8")
    runner.main(ws / "model.py", ws / "out", determinism=True, fast=False)
    st = json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
    assert runner.is_verified(st), [c for c in st["checks"] if not c["passed"]]
    info = geometry.prepare(ws / "snap", step=str(ws / "out" / "part.step"))
    res = conformance.measure(doc["skeleton"], doc["icd"], _id(doc, name), info,
                              json.loads((ws / "snap" / "refs.json").read_text()))
    assert res["ok"] and res["envelope"]["ok"], [r for x in res["interfaces"] for r in x["rows"] if not r["ok"]]
    return st, res, script


# ---------------------------------------------------------------------------- the hand volume
def test_machined_volume_by_hand() -> None:
    """A 100 x 60 x 20 box, a 40 x 20 x 10 pocket from the top, a Ø10 hole through outside it, a Ø8 hole through
    the pocket floor (only 10 of material), a Ø20 x 5 counterbore coaxial with a Ø10 hole (united by length)."""
    cuts = [{"ax": "z", "c": (40, 20), "d": 10, "span": None},
            {"ax": "z", "c": (0, 0), "d": 8, "span": None},
            {"ax": "z", "c": (-35, 0), "d": 10, "span": None},
            {"ax": "z", "c": (-35, 0), "d": 20, "span": (5, 10)}]
    pk = [{"name": "Pocket", "min": (-20, -10, 0), "max": (20, 10, 10)}]
    v = fw_std.machined_volume(("box", 100, 60, 20), pk, cuts)
    a = math.pi / 4
    want = 100 * 60 * 20 - 40 * 20 * 10 - a * 100 * 20 - a * 64 * 10 - a * 100 * 15 - a * 400 * 5
    assert v["problems"] == [] and v["volume"] == pytest.approx(want, rel=1e-12)
    # what the formula can't sum is refused, with the reason
    bad = fw_std.machined_volume(("box", 100, 60, 20), pk, [{"name": "Edge hole", "ax": "z", "c": (-20, 0), "d": 6,
                                                              "span": None}])
    assert bad["problems"] == ["Edge hole half enters Pocket"]
    bad = fw_std.machined_volume(("box", 100, 60, 20), [], [{"name": "A", "ax": "z", "c": (0, 0), "d": 10, "span": None},
                                                            {"name": "B", "ax": "x", "c": (0, 0), "d": 6, "span": None}])
    assert bad["problems"] == ["A and B cross"]
    # a disc with pads: Pappus rim chamfer c² / 2 x 2π (R - c / 3)
    v = fw_std.machined_volume(("disc", 70, 18), [], [{"ax": "z", "c": (0, 0), "d": 27, "span": None}], [{"z": 9, "c": 1}])
    assert v["volume"] == pytest.approx(a * (70 ** 2 - 27 ** 2) * 18 - 0.5 * 2 * math.pi * (35 - 1 / 3), rel=1e-12)
    # revolved profile: a Ø40 x 10 ring with a Ø20 bore by Pappus
    assert fw_std.revolved_volume([(10, 0), (20, 0), (20, 10), (10, 10)]) == pytest.approx(a * (40 ** 2 - 20 ** 2) * 10)


# ---------------------------------------------------------------------------- the reducer, hand checked
def test_reducer_housing_cover_and_caps_go_direct_with_hand_values() -> None:
    doc = _plan_doc("c_reducer", REDUCER_BRIEF)
    paths = {n: direct.plan(doc, _t(doc, n)) for n in ("Housing base", "Housing cover", "Input open cap",
                                                        "Input blind cap", "Output open cap", "Output blind cap")}
    assert {n: p["path"] for n, p in paths.items()} == dict.fromkeys(paths, "direct"), \
        {n: p.get("reasons") for n, p in paths.items()}
    h = paths["Housing base"]["script"]
    assert _num(h, "SEAT_2_X") - _num(h, "SEAT_1_X") == 80  # a = m (z1 + z2) / 2 = 2 (20 + 60) / 2
    assert (_num(h, "SEAT_1_D"), _num(h, "SEAT_1_DEPTH"), _num(h, "SEAT_2_D"), _num(h, "SEAT_2_DEPTH")) == (47, 14, 52, 15)
    assert (_num(h, "CAP_1_PCD"), _num(h, "CAP_2_PCD")) == (58, 63)  # D + tap drill 5 + 2 x 3
    # M6: ISO 2306 drill 5; depth max(2.5 d + 3, 2 d + 2 P + 5) = max(18, 12 + 2 + 5) = 19 (PD-285)
    assert (_num(h, "CAP_TAP_D"), _num(h, "CAP_TAP_DEPTH")) == (5, 19)
    assert _num(h, "WALL") == 24 and '"WALL": {"min": 22.0' in h  # wall rule max(19, 19 + 3, 12) = 22 <= 24
    assert (_num(h, "FOOT_TAP_D"), _num(h, "FOOT_EDGE")) == (6.8, 12)  # M8 for a 224 long footprint, 1.5 d
    assert paths["Housing base"]["summary"].startswith("gearbox housing 224 × 110 × 146: 2 bearing bores (6204 / 6205) "
                                                       "at 80 centre distance")
    o = paths["Input open cap"]["script"]
    assert (_num(o, "OD"), _num(o, "HOLE_PCD"), _num(o, "HOLE_D"), _num(o, "BORE")) == (70, 58, 6.6, 27)
    assert (_num(o, "SEAL_D"), _num(o, "SEAL_WIDTH")) == (40, 7)  # DIN 3760 for the Ø25 shaft (the plan's 20 x 35 x 7
    assert "approved ICD passes Ø25 here" in o                    # is for a Ø20 shaft: superseded, said)
    b = paths["Output blind cap"]["script"]
    assert "BORE" not in b and _num(b, "HOLE_PCD") == 63 and "Spigot:" in b  # the brief's spigot: noted, no spigot
    c = paths["Housing cover"]["script"]
    assert (_num(c, "HOLES_1_D"), _num(c, "DOWEL_D"), _num(c, "HOLLOW_LENGTH"), _num(c, "HOLLOW_WIDTH")) == (9, 8, 176, 62)
    # the shafts and the pinion keep their reasons (sizes the plan states that the ICD doesn't explain)
    assert direct.plan(doc, _t(doc, "Pinion"))["path"] == "agent"


def test_reducer_parts_pass_the_gate_and_conform(tmp_path: Path) -> None:
    doc = _plan_doc("c_reducer", REDUCER_BRIEF)
    sts = {}
    for name in ("Housing base", "Input open cap", "Housing cover"):
        st, _res, src = _gate(tmp_path, doc, name)
        sts[name] = st
        assert set(st["editable_params"]) == set(templates.script_params(src))  # every parameter is editable
        assert all(k in st["param_meta"] for k in st["editable_params"])
        assert st["material"] in ("Aluminium 6061-T6", "Steel 1018 (low carbon)")
    # the open cap by hand: disc less 4 holes, the bore, relief (33.5 x 1) and seal (40 x 7) over the bore, rim chamfer
    st = sts["Input open cap"]
    a = math.pi / 4
    v = (a * 70 ** 2 * 18 - 4 * a * 6.6 ** 2 * 18 - a * 27 ** 2 * 18 - a * (33.5 ** 2 - 27 ** 2) * 1
         - a * (40 ** 2 - 27 ** 2) * 7 - 0.5 * 2 * math.pi * (35 - 1 / 3))
    assert st["fingerprint"]["volume"] == pytest.approx(v, rel=1e-6)
    assert st["fingerprint"]["bbox"] == pytest.approx([70, 70, 18], abs=1e-6)


# ---------------------------------------------------------------------------- plates, brackets, hubs
def test_plate_corner_holes_and_superseded_hole_statement() -> None:
    """(d) base plate: "two Ø6.6 holes 40 mm apart for the bracket bolts" is the plan's statement of the joint the
    ICD fixes (4 x Ø6.6 now); "four Ø9 corner holes" are added at 1.5 d = 13.5 from both edges: (±46.5, ±26.5)."""
    brief = ("An aluminium angle bracket (foot 60 x 40 x 8 mm, upright 50 mm high and 8 mm thick) bolted to a 120 x 80 "
             "x 10 mm aluminium base plate with two M6 x 30 hex bolts, washers and nuts.")
    doc = _plan_doc("d_bracket", brief)
    p = direct.plan(doc, _t(doc, "Base plate"))
    assert p["path"] == "direct", p.get("reasons")
    s = p["script"]
    assert (_num(s, "CORNER_HOLE_D"), _num(s, "CORNER_EDGE")) == (9, 13.5)
    assert p["material"] == "Aluminium 6061-T6"
    # the bracket: the brief's 8 mm upright leaves no room for the M6 washers (Ø12) of the ICD's pattern: the agent
    r = direct.plan(doc, _t(doc, "Angle bracket"))
    assert r["path"] == "agent" and "no room for the M6 washers" in r["reasons"][0]


def test_bracket_and_clevis_on_the_graph_path(tmp_path: Path) -> None:
    doc = _graph_doc(GC / "d_bracket.intent.json")
    p = direct.plan(doc, _t(doc, "Angle bracket"))
    assert p["path"] == "direct", p.get("reasons")
    assert (_num(p["script"], "FOOT_T"), _num(p["script"], "UPRIGHT_T")) == (8, 8)  # the brief's, from its sentence
    st, _res, _src = _gate(tmp_path, doc, "Angle bracket")
    it = doc["skeleton"]["items"][_id(doc, "Angle bracket")]
    L, W, H = it["size"]
    holes = [x for x in icd.item_features(doc["skeleton"], doc["icd"]["interfaces"], _id(doc, "Angle bracket"))
             if x["type"] == "hole"]
    v = L * W * H - L * (W - 8) * (H - 8) - sum(math.pi / 4 * float(x["d"]) ** 2 * 8 for x in holes)
    v += sum(0.5 * _num(p["script"], "GUSSET_LEG") ** 2 * 8 for _ in range(p["script"].count("fw.gusset(")))
    assert st["fingerprint"]["volume"] == pytest.approx(v, rel=1e-6)
    # the clevis: the layout's slot between the lugs is a pocket; the pin bore through both lugs
    hd = _graph_doc(GC / "g_hinge_arm.intent.json")
    c = direct.plan(hd, _t(hd, "Clevis base"))
    assert c["path"] == "direct" and c["kind"] == "plate" and '"Slot"' in c["script"], c.get("reasons")
    _gate(tmp_path, hd, "Clevis base")


def test_pulleys_coupling_and_pillow_blocks(tmp_path: Path) -> None:
    doc = _graph_doc(G2 / "pulley_pair.json")
    p = direct.plan(doc, _t(doc, "Drive pulley"))
    assert p["path"] == "direct" and p["kind"] == "pulley", p.get("reasons")
    s = p["script"]
    assert (_num(s, "OD"), _num(s, "WIDTH"), _num(s, "BORE"), _num(s, "KEY_B"), _num(s, "KEY_T2")) == (60, 20, 20, 6, 2.8)
    hub = max(1.8 * 20, 20 + 2 * (2.8 + 4))  # 36
    assert _num(s, "HUB_D") == hub and _num(s, "RIM_T") == max(3.0, round(0.08 * 60, 1))
    st, _res, _src = _gate(tmp_path, doc, "Drive pulley")
    R, ri, web = 30.0, 30.0 - 4.8, 6.0
    v = math.pi * ((R ** 2 - ri ** 2) * 20 + (ri ** 2 - (hub / 2) ** 2) * web + ((hub / 2) ** 2 - 10 ** 2) * 20)
    v -= (6 * (10 + 2.8) - fw_std._keyway_segment(10, 6)) * 20
    assert st["fingerprint"]["volume"] == pytest.approx(v, rel=1e-6)
    for name in ("Drive pillow block", "Base plate"):
        assert direct.plan(doc, _t(doc, name))["path"] == "direct"
    # the motor coupling (finding G1, fixed in office-polish2): the layout gives each bore its own half, Ø20 from one
    # end face to the middle of the gap and Ø14 from the other end to the middle, so the stepped coupling is built
    # direct and passes conformance. Coupling Ø50 x 62 (2 x 30 engagement + 2 gap): by hand
    # V = π (25² x 62 - 10² x 31 - 7² x 31) = π x 34131
    md = _graph_doc(G2 / "motor_drive.json")
    cid = _id(md, "Coupling")
    spans = sorted((f["data"]["d"], f["data"]["bore_z"]) for f in md["icd"]["interfaces"]
                   if f["kind"] == "shaft_bore" and f["a"]["item"] == cid)
    assert [d for d, _z in spans] == [14.0, 20.0] and spans[0][1][1] == spans[1][1][0]  # they meet in the middle
    c = direct.plan(md, _t(md, "Coupling"))
    assert c["path"] == "direct" and "bores Ø20 / Ø14" in c["summary"], c.get("reasons")
    st, _res, _src = _gate(tmp_path, md, "Coupling")
    assert st["fingerprint"]["volume"] == pytest.approx(math.pi * (25 ** 2 * 62 - 10 ** 2 * 31 - 7 ** 2 * 31), rel=1e-6)
    # an older ICD that still states both bores through: said, not built (the generator's guard stays)
    md = _graph_doc(G2 / "motor_drive.json")
    for f in md["icd"]["interfaces"]:
        f["data"].pop("bore_z", None)
    c = direct.plan(md, _t(md, "Coupling"))
    assert c["path"] == "agent" and "bores of two sizes" in c["reasons"][0]
    for f in md["icd"]["interfaces"]:
        if f["kind"] == "shaft_bore" and cid in (f["a"]["item"], f["b"]["item"]):
            f["data"]["d"] = 20.0
    for f in md["icd"]["interfaces"]:
        if f["kind"] == "key" and cid in (f["a"]["item"], f["b"]["item"]):
            f["data"].update(d=20.0, b=6.0, t2=2.8, h=6.0, t1=3.5)
    c = direct.plan(md, _t(md, "Coupling"))
    assert c["path"] == "direct" and c["summary"].startswith("rigid sleeve coupling"), c.get("reasons")
    _gate(tmp_path, md, "Coupling")


def test_timing_pulley_pitch_diameter_and_what_needs_the_designer() -> None:
    doc = _graph_doc(G2 / "pulley_pair.json")
    item = _id(doc, "Drive pulley")
    doc["skeleton"]["items"][item]["size"] = [44.0, 44.0, 20.0]
    for i in doc["items"]:
        if i["id"] == item:
            i["description"] = "HTD 5M timing pulley, 24 teeth, 20 mm H7 bore."
    p = direct.plan(doc, _t(doc, "Drive pulley"))
    assert p["path"] == "direct", p.get("reasons")
    assert _num(p["script"], "PITCH_D") == pytest.approx(24 * 5 / math.pi, abs=1e-4)  # z p / π = 38.197
    for desc, why in (("V-belt pulley SPZ, 20 mm bore.", "V-belt"), ("Timing pulley GT2, 20 mm bore.", "teeth"),
                      ("Pulley with an M5 set screw.", "set screw")):
        for i in doc["items"]:
            if i["id"] == item:
                i["description"] = desc
        r = direct.plan(doc, _t(doc, "Drive pulley"))
        assert r["path"] == "agent" and any(why in x for x in r["reasons"]), r


def test_graph_reducer_is_all_direct() -> None:
    doc = _graph_doc(GC / "c_reducer.intent.json")
    designed = [i["name"] for i in doc["items"] if i["id"] in doc["skeleton"]["items"]
                and doc["skeleton"]["items"][i["id"]]["role"] != "standard"]
    paths = {n: direct.plan(doc, _t(doc, n))["path"] for n in designed}
    assert set(paths.values()) == {"direct"}, paths
    assert len(paths) == 10


# ---------------------------------------------------------------------------- templates (WORKLIST 48)
TUBE_SCRIPT = '''"""Roller tube, written by the designer."""
from build123d import *
from aicad import fw

NAME = "Roller tube"
MATERIAL = "Steel 1045 (medium carbon)"
OD = 50.0  # mm
LENGTH = 200.0  # mm
BORE = 20.0  # mm
WALL = 4.0  # mm
CHAMFER = 1.0  # mm

PARAMS = dict(OD=OD, LENGTH=LENGTH, BORE=BORE, WALL=WALL, CHAMFER=CHAMFER)
PARAM_META = {"OD": {"min": 10, "max": 200}}
result = Cylinder(OD / 2, LENGTH) - Cylinder(BORE / 2, LENGTH + 2)
'''


def test_template_bindings_similarity_and_direct_reuse(tmp_path: Path) -> None:
    doc = _graph_doc(GC / "e_roller.intent.json")
    t = {**_t(doc, "Roller tube"), "column": "approved", "direct": {"path": "agent", "reasons": ["the brief asks for x"]}}
    rec = templates.harvest(tmp_path, doc, t, {"ok": True, "source": TUBE_SCRIPT}, "Ann")
    assert rec["family"] == "hub" and rec["params"] == 5 and rec["mapped"] == 3 and rec["finish"] == 1 \
        and rec["design"] == 1  # OD, LENGTH, BORE map; CHAMFER is a finish; WALL is a design value
    stored = templates.load_all(tmp_path)[0]
    assert stored["bindings"]["OD"]["to"] == ["D"] and stored["bindings"]["LENGTH"]["to"] == ["H"]
    assert "hole_d1" in stored["bindings"]["BORE"]["to"]
    # a bigger tube of the same family: similarity 0.5 x 1 (same features) + 0.5 x mean(60/50... ) by hand
    it = doc["skeleton"]["items"][_id(doc, "Roller tube")]
    it["size"] = [60.0, 60.0, 250.0]
    q = templates.quantities(doc, _id(doc, "Roller tube"))
    assert templates.similarity(stored, templates.signature(doc, _id(doc, "Roller tube")), q) == \
        pytest.approx(0.5 + 0.5 * (50 / 60 + 200 / 250) / 2, abs=1e-4)
    # WALL is a design value: the template seeds the agent (the generator builds a hub too, but the template is the
    # same kind of part with the same features, so it is preferred as the starting point)
    dp = templates.plan(tmp_path, doc, t, {"path": "agent", "reasons": ["a hub of this kind needs the designer"]})
    assert dp["path"] == "agent" and dp["seed"]["template"]["id"] == rec["id"] and dp["template"]["loose"] == ["WALL"]
    assert _num(dp["seed"]["script"], "OD") == 60 and _num(dp["seed"]["script"], "LENGTH") == 250
    # every parameter mapped (no design value): built directly from the template, labelled so
    stored["bindings"]["WALL"] = {"finish": True, "value": 4.0}
    (tmp_path / "templates" / f"{rec['id']}.json").write_text(json.dumps(stored), encoding="utf-8")
    dp = templates.plan(tmp_path, doc, t, {"path": "agent", "reasons": ["the brief asks for x"]})
    assert dp["path"] == "direct" and dp["label"] == templates.LABEL
    assert 'NAME = "Roller tube"' in dp["script"] and _num(dp["script"], "BORE") == 20
    assert "workspace template" in direct.note(dp)
    # a brief extra its source part never answered blocks the direct use
    assert templates.plan(tmp_path, doc, t, {"path": "agent", "reasons": ["the brief asks for knurling"]})["path"] == "agent"
    # other families never match; delete
    other = _graph_doc(G2 / "pulley_pair.json")
    assert templates.plan(tmp_path, other, _t(other, "Base plate"), {"path": "agent", "reasons": []}) is None
    assert templates.delete(tmp_path, rec["id"]) and templates.load_all(tmp_path) == []
    assert not templates.delete(tmp_path, "../../etc")


def test_only_approved_parametric_ai_parts_can_be_kept(tmp_path: Path) -> None:
    doc = _graph_doc(GC / "e_roller.intent.json")
    base = {**_t(doc, "Roller tube"), "column": "approved", "direct": {"path": "agent"}}
    ok = {"ok": True, "source": TUBE_SCRIPT}
    for t, st, why in (({**base, "column": "in_design"}, ok, "once it is approved"),
                       ({**base, "direct": {"path": "direct"}}, ok, "interface spec already"),
                       (base, {"ok": False, "source": TUBE_SCRIPT}, "doesn't pass"),
                       (base, {"ok": True, "source": TUBE_SCRIPT.replace("PARAM_META", "META")}, "isn't parametric")):
        with pytest.raises(templates.TemplateError, match=why):
            templates.harvest(tmp_path, doc, t, st, "Ann")


def test_templates_kept_in_the_office_and_reused_by_the_next_program(office: Any) -> None:  # noqa: F811
    """A part the designer made with AI (simulated agents) is kept as a template through the API; the next program
    with the same part starts from it (a seeded design turn, said on the ticket); another workspace never sees it."""
    from sqlalchemy import select
    from test_office_orchestrator import _program, _wait
    from test_platform import signup

    from aicad.platform.db import session_factory
    from aicad.platform.models import Project
    from aicad.platform.routers.projects import workspace_for

    c = office
    plan = json.loads((GC / "g_hinge_arm.plan.json").read_text(encoding="utf-8"))
    brief = "A hinged arm on a clevis base."
    v = _program(c, "tpl@x.com", plan, brief=brief)
    pid = v["id"]
    assert c.get("/api/office/templates").json()["items"] == []
    c.post(f"/api/office/programs/{pid}/run")
    v = _wait(c, pid, lambda v: v["orchestrator"]["state"] in ("complete", "blocked", "stopped"), timeout=600)
    t = next(x for x in v["tickets"] if x["title"] == "Clevis base")
    assert t["direct"]["path"] == "agent" and t["column"] in ("approved", "integrated", "done"), t["direct"]
    # the simulated designer's script has no PARAM_META: not offered as parametric
    r = c.post(f"/api/office/programs/{pid}/tickets/{t['id']}/template")
    assert r.status_code == 422 and "parametric" in r.json()["detail"], r.text
    # as the real designer would leave it: a parametric script (the interface model) that passed its checks
    from aicad.office import store
    from aicad.platform.config import get_settings

    org = c.get("/api/auth/me").json()["org"]["id"]
    doc = store.load(store.org_root(get_settings().data_dir, org), pid)
    script = direct.plan(doc, {"kind": "part", "item_id": t["item_id"], "title": "Clevis base", "qty": 1})["seed"]["script"]
    db = session_factory()()
    try:
        ws = workspace_for(db.scalar(select(Project).where(Project.id == t["project_id"])))
    finally:
        db.close()
    (ws / "model.py").write_text(script, encoding="utf-8")
    st = json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
    (ws / "out" / "status.json").write_text(json.dumps({**st, "ok": True}), encoding="utf-8")
    r = c.post(f"/api/office/programs/{pid}/tickets/{t['id']}/template")
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["family"] == "plate" and rec["source"]["title"] == "Clevis base" and rec["params"] >= 4
    assert [x["id"] for x in c.get("/api/office/templates").json()["items"]] == [rec["id"]]
    t = next(x for x in c.get(f"/api/office/programs/{pid}").json()["tickets"] if x["title"] == "Clevis base")
    assert t["template_kept"]["id"] == rec["id"]
    # the next program with the same part: its design turn starts from the template
    r = c.post("/api/office/programs", json={"name": "Second rig", "brief": brief, "planner": "standard",
                                             "deliverables": False})
    pid2 = r.json()["id"]
    assert c.post(f"/api/office/programs/{pid2}/gates/brief/approve", json={"plan": plan}).status_code == 200
    assert c.post(f"/api/office/programs/{pid2}/gates/icd/approve").status_code == 200
    c.post(f"/api/office/programs/{pid2}/run")
    v2 = _wait(c, pid2, lambda v: v["orchestrator"]["state"] in ("complete", "blocked", "stopped"), timeout=600)
    t2 = next(x for x in v2["tickets"] if x["title"] == "Clevis base")
    d2 = t2["direct"]
    assert d2["path"] == "agent" and d2["template"]["id"] == rec["id"] and d2["seed_kind"].startswith("template:"), d2
    assert any(x.startswith("starting from the workspace template Clevis base") for x in d2["reasons"])
    assert c.get("/api/office/templates").json()["items"][0]["uses"] == 0  # a seed is not a direct use
    # tenant scoping: another workspace sees none and can't delete it; the owner can
    c.post("/api/auth/logout")
    signup(c, "other@x.com")
    assert c.get("/api/office/templates").json()["items"] == []
    assert c.delete(f"/api/office/templates/{rec['id']}").status_code == 404


from test_office_orchestrator import office  # noqa: F401  (fixture)
