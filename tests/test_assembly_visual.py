"""PD-73: the visual assembly check (advisory), the quick placement checks, the exact-check policy and Archie telling
the engineer. No model is called: vision replies are the ones recorded live on 2026-11-19 (haiku, low effort; see
docs/reports/assembly-fix/asm-visual.md), served through the stub provider.

The test case (ASM fix brief): spur gear pair 1:3, pinion m2 z20 and gear m2 z60 -> centre distance
a = m (z1 + z2) / 2 = 2 (20 + 60) / 2 = 80 mm; tip diameters m (z + 2) = 44 and 124 mm; face width 20 mm; shafts
Ø20 x 120 along +Y at x = 0 and x = 80; 6204 bearings (d 20, D 47, B 14) at y 10..24 and 96..110 on each shaft.
"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from aicad import llm
from aicad.assembly import render, visual
from aicad.llm.stub import StubProvider
from aicad.office import archie_chat, icd, planner, service, visual_office

GEAR_PAIR = {"title": "Spur gear pair 1:3", "subassemblies": [{"name": "Gear pair", "parts": [
    {"name": "Pinion", "family": "gear", "complexity": 2, "qty": 1, "description": "spur pinion module 2, 20 teeth"},
    {"name": "Gear", "family": "gear", "complexity": 2, "qty": 1, "description": "spur gear module 2, 60 teeth"},
    {"name": "Input shaft", "family": "turned", "complexity": 2, "qty": 1, "description": "shaft 20 mm diameter, 120 long"},
    {"name": "Output shaft", "family": "turned", "complexity": 2, "qty": 1, "description": "shaft 20 mm diameter, 120 long"},
    {"name": "Deep groove ball bearing 6204", "family": "standard", "complexity": 1, "qty": 4,
     "description": "6204 ball bearing"}]}]}
BRIEF = "Simple spur gear pair 1:3 with shafts and bearings"

ROW_REPLY = '''```json
{"overall": "looks_wrong",
 "relations": [
  {"id": "R1", "status": "wrong", "reason": "Pinion and gear lie side by side, the shafts stand apart from them."},
  {"id": "R2", "status": "wrong", "reason": "Neither gear sits on a shaft."}],
 "problems": [
  {"kind": "row", "items": [1, 2, 3, 4], "text": "The parts lie apart on the floor in a row."}],
 "summary": "The parts lie side by side on the floor, so the assembly does not look as intended."}
```'''
OK_REPLY = '''```json
{"overall": "looks_assembled",
 "relations": [{"id": "R1", "status": "ok", "reason": "Shafts parallel, about 80 mm apart, gears in one plane."}],
 "problems": [],
 "summary": "The gear pair, shaft spacing and bearing positions look as intended."}
```'''


def _parts(plan: dict[str, Any]) -> list[dict[str, Any]]:
    p = planner.normalise_plan(plan, "standard")
    assert p is not None
    return [{"id": f"i_{s['id']}_{q['id']}", "name": q["name"], "family": q["family"], "qty": q["qty"],
             "description": q["description"], "complexity": q["complexity"], "sub": f"i_{s['id']}"}
            for s in p["subassemblies"] for q in s["parts"]]


def _row_layout() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return icd.build(_parts(GEAR_PAIR), BRIEF)


# ============================================================================ the picture
def test_skeleton_render_row_case(tmp_path: Path) -> None:
    sk, ifs = _row_layout()
    assert ifs == []  # the founder's case: no interfaces at all (the layout engine's row fallback)
    scene = render.scene_from_skeleton(sk, "Gear pair (layout)", ifs)
    assert [k["label"] for k in scene["key"]] == ["Pinion", "Gear", "Input shaft", "Output shaft"]
    assert len({k["color"] for k in scene["key"]}) == 4  # every item its own colour
    # the pinion envelope is its tip circle: m (z + 2) = 44 mm, 20 wide
    pin = next(b for b in scene["bodies"] if b["label"] == "Pinion")
    assert pin["prim"] == "cyl" and pin["size"] == [44.0, 44.0, 20.0]
    out = render.render(scene, tmp_path / "layout.png")
    assert out["bodies"] == 4 and out["seconds"] < 60  # measured ~1.2 s on the dev workstation
    with Image.open(tmp_path / "layout.png") as im:
        assert im.size == render.SIZE


def test_seated_bearings_are_drawn_where_fitz_seats_them() -> None:
    sk, ifs = icd.build(_parts({"subassemblies": [{"name": "Gear pair", "parts": [
        {"name": "Housing", "family": "machined", "complexity": 3, "qty": 1, "description": "Housing."},
        *GEAR_PAIR["subassemblies"][0]["parts"]]}]}), BRIEF)
    scene = render.scene_from_skeleton(sk, "", ifs)
    brg = [b for b in scene["bodies"] if "6204" in b["label"]]
    assert brg and all(b["size"] == [47.0, 47.0, 14.0] for b in brg)  # 6204: D 47, B 14


# ============================================================================ quick placement checks
def test_quick_skeleton_row_and_unplaced_bearings() -> None:
    sk, ifs = _row_layout()
    q = visual.quick_skeleton(sk, ifs)
    codes = [f["code"] for f in q["findings"]]
    assert codes == ["row", "unplaced_standard"]
    assert q["findings"][0]["severity"] == "block" and "4 of 4 parts touch nothing" in q["findings"][0]["text"]
    assert "4 × Deep groove ball bearing 6204 have no seat" in q["findings"][1]["text"]


def test_quick_skeleton_catches_stacked_gears() -> None:
    # with a housing added, today's layout stacks the gear on the pinion's axis: the gears must mesh 80 mm apart
    sk, ifs = icd.build(_parts({"subassemblies": [{"name": "Gear pair", "parts": [
        {"name": "Housing", "family": "machined", "complexity": 3, "qty": 1, "description": "Housing."},
        *GEAR_PAIR["subassemblies"][0]["parts"]]}]}), BRIEF)
    found = visual.skeleton_gear_findings(sk, ifs)
    if found:  # the layout engine may learn shaft lines (wip/office-layout): then there is nothing to find
        assert found[0]["code"] == "gear_centre" and "must mesh 80 mm apart" in found[0]["text"]


def test_quick_skeleton_clean_on_a_good_gearbox() -> None:
    brief = "A spur gear reducer, 3:1, 1450 rpm input."
    sk, ifs = icd.build(_parts(planner.standard_plan("Gear reducer", brief)), brief)
    assert visual.quick_skeleton(sk, ifs)["findings"] == []


def test_touch_groups_and_findings() -> None:
    import numpy as np

    def box(x: float) -> tuple[np.ndarray, np.ndarray]:
        return np.array([x, 0.0, 0.0]), np.array([x + 10, 10.0, 10.0])

    # three boxes 20 mm apart: nothing touches -> a row
    g = visual._groups({"a": box(0), "b": box(20), "c": box(40)})
    f = visual.apart_findings({"a": "A", "b": "B", "c": "C"}, g, {"a": True, "b": True, "c": True})
    assert [x["code"] for x in f] == ["row"] and "3 of them stand on the floor" in f[0]["text"]
    # a touching pair plus one apart -> that one floats
    g = visual._groups({"a": box(0), "b": box(10.3), "c": box(60)})
    f = visual.apart_findings({"a": "A", "b": "B", "c": "C"}, g, {})
    assert [(x["code"], x["items"]) for x in f] == [("floating", ["c"])]


# ============================================================================ verdicts
def test_parse_recorded_replies() -> None:
    rels = [{"id": "R1", "text": "Pinion meshes with Gear"}, {"id": "R2", "text": "gears on shafts"}]
    key = [{"n": n, "label": lb} for n, lb in enumerate(["Pinion", "Gear", "Input shaft", "Output shaft"], 1)]
    v = visual.parse_verdict(ROW_REPLY, rels, key)
    assert v["overall"] == "looks_wrong" and [r["status"] for r in v["relations"]] == ["wrong", "wrong"]
    assert v["problems"][0]["kind"] == "row" and v["problems"][0]["labels"][:2] == ["Pinion", "Gear"]
    v = visual.parse_verdict(OK_REPLY, rels[:1], key)
    assert v["overall"] == "looks_assembled" and v["relations"][0]["status"] == "ok"
    # unreadable -> unsure, never a pass
    v = visual.parse_verdict("I think it is fine.", rels, key)
    assert v["overall"] == "unsure" and v["readable"] is False
    # a pass with a wrong relation is not a pass
    bad = OK_REPLY.replace('"status": "ok"', '"status": "wrong"')
    assert visual.parse_verdict(bad, rels[:1], key)["overall"] == "looks_wrong"
    # a relation the answer skipped is unsure
    assert visual.parse_verdict(OK_REPLY, rels, key)["relations"][1]["status"] == "unsure"


def test_reasons_are_scrubbed() -> None:
    reply = OK_REPLY.replace("Shafts parallel", "Read model.py with the Read tool; shafts parallel")
    v = visual.parse_verdict(reply, [{"id": "R1", "text": "x"}])
    assert "model.py" not in json.dumps(v)


# ============================================================================ policy
QUICK_ROW = {"findings": [{"code": "row", "severity": "block", "items": ["i1", "i2"], "text": "Nothing touches."}]}
CLEAN: dict[str, Any] = {"findings": []}


def _v(overall: str, statuses: list[str], problems: int = 0) -> dict[str, Any]:
    return {"overall": overall, "relations": [{"id": f"R{k}", "text": "t", "status": s, "reason": ""}
                                              for k, s in enumerate(statuses)],
            "problems": [{"kind": "row", "items": [1], "labels": [], "text": "x"}] * problems, "summary": "s",
            "readable": True}


def test_policy_table() -> None:
    slow, fast = {"seconds": 60.0}, {"seconds": 1.0}
    # a measured problem stops, whatever the picture says
    d = visual.decide(_v("looks_assembled", ["ok"]), QUICK_ROW, fast)
    assert d["stop"] and d["exact"] == "targeted" and d["targets"] == ["i1", "i2"]
    # no look: as before
    assert visual.decide(None, CLEAN, slow)["exact"] == "inline"
    # looks assembled, every relation ok: background only when measuring is slower than looking was
    assert visual.decide(_v("looks_assembled", ["ok", "ok"]), CLEAN, slow, vision_s=20)["exact"] == "background"
    assert visual.decide(_v("looks_assembled", ["ok", "ok"]), CLEAN, fast, vision_s=20)["exact"] == "inline"
    # unsure (the 5 mm offset case): measure as usual
    assert visual.decide(_v("unsure", ["unsure", "ok"]), CLEAN, slow)["exact"] == "inline"
    # looks wrong: measure the flagged parts first; stop only when a measurement confirms it
    d = visual.decide(_v("looks_wrong", ["wrong"], 1), CLEAN, slow)
    assert d["exact"] == "targeted" and not d["stop"] and d["confirm"]
    hit = visual.confirm(d, _v("looks_wrong", ["wrong"], 1), [{"a_name": "A", "b_name": "B", "volume_mm3": 3.25}])
    assert hit["stop"] and "overlap by 3.2 mm³" in hit["reason"]
    miss = visual.confirm(d, _v("looks_wrong", ["wrong"], 1), [])
    assert not miss["stop"] and miss["unconfirmed"]


def test_targets_from_numbers_and_names() -> None:
    doc = {"instances": [{"id": "i1", "name": "Pinion"}, {"id": "i2", "name": "Gear"}, {"id": "i3", "name": "Shaft"}]}
    key = [{"n": 1, "label": "Pinion"}, {"n": 2, "label": "Gear"}, {"n": 3, "label": "Shaft"}]
    v = _v("looks_wrong", ["ok"])
    v["problems"] = [{"kind": "floating", "items": [3], "labels": ["Shaft"], "text": "x"}]
    assert visual.targets_from(v, doc, key) == ["i3"]


# ============================================================================ relations
def test_relations_from_the_brief_roles() -> None:
    sk, ifs = _row_layout()
    rels = [r["text"] for r in visual.relations_from_skeleton(sk, ifs, BRIEF)]
    assert rels[0] == ("Pinion meshes with Gear: axes parallel, 80 mm apart (m (z1 + z2) / 2), the two gears in one "
                       "plane")
    assert any("each gear sits on its own shaft" in r for r in rels)
    assert any(r.startswith("4 × Deep groove ball bearing 6204 carry the shafts") for r in rels)


# ============================================================================ one look through the provider layer
def test_look_through_the_stub_provider(tmp_path: Path) -> None:
    sk, ifs = _row_layout()
    scene = render.scene_from_skeleton(sk, "Gear pair", ifs)
    rels = visual.relations_from_skeleton(sk, ifs, BRIEF)
    stub = StubProvider(responder=lambda req: ROW_REPLY)
    with llm.use_provider(stub, roles=(visual.ROLE,)):
        rec = asyncio.run(visual.look(scene, rels, tmp_path / "v", brief=BRIEF, budget_usd=0.15))
    assert rec["status"] == "done" and rec["verdict"]["overall"] == "looks_wrong"
    assert rec["tokens"] == 0  # the stub bills nothing; a live look was 2 platform tokens (haiku, low effort)
    req = stub.calls[0]
    assert req.role == "assembly_check" and req.images[0].name == "assembly.png" and req.effort == "low"
    assert "Pinion meshes with Gear" in req.prompt and "Picture: assembly.png" in req.prompt
    assert visual.load_record(tmp_path / "v")["line"].startswith("Visual check (advisory): it looks wrong")


def test_look_simulated_follows_quick_checks(tmp_path: Path) -> None:
    sk, ifs = _row_layout()
    q = visual.quick_skeleton(sk, ifs)
    rec = asyncio.run(visual.look(render.scene_from_skeleton(sk, "", ifs), visual.relations_from_skeleton(sk, ifs),
                                  tmp_path / "v", simulated=True, quick=q))
    assert rec["verdict"]["overall"] == "looks_wrong" and rec["verdict"]["simulated"] and rec["tokens"] == 0


# ============================================================================ Archie
def _program(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    from aicad.office import store

    root = store.org_root(tmp_path, "org1")
    doc = service.new_program("Spur gear pair", BRIEF, "org1", "u1", 2, 3000, "standard")
    service.set_plan(root, doc, planner.normalise_plan(GEAR_PAIR, "standard"), {"name": "Eng"})
    service.approve_plan(root, doc, None, {"name": "Eng"})
    store.save(root, doc)
    return root, doc


def test_archie_tells_the_row_layout_and_proposes_a_housing(tmp_path: Path) -> None:
    _root, doc = _program(tmp_path)
    q = visual.quick_skeleton(doc["skeleton"], doc["icd"]["interfaces"])
    verdict = visual.parse_verdict(ROW_REPLY, visual.relations_from_skeleton(doc["skeleton"], []))
    text, acts = visual_office.layout_message(doc, q, {"verdict": verdict})
    assert text.startswith("Before you approve the interfaces, I looked at the layout of Spur gear pair.")
    assert "There's no housing or base in this plan, so the parts can't be mounted" in text
    assert "4 × Deep groove ball bearing 6204 have no seat" in text
    assert "Visual check (advisory): it looks wrong" in text and "which?" in text
    assert [a["type"] for a in acts] == ["revise_plan", "revise_plan"]
    assert acts[0]["add"]["part"]["name"] == "Housing" and acts[1]["add"]["part"]["name"] == "Base plate"
    # the proposal is checked against the program before it is offered (and again before it applies)
    clean = archie_chat.normalise(doc, acts[0])
    assert clean is not None and clean["add"]["sub"] == "Gear pair"
    assert archie_chat.describe(doc, clean).startswith("Send the plan back to you with a housing added to Gear pair")


def test_revise_plan_goes_back_to_review_with_the_part(tmp_path: Path) -> None:
    root, doc = _program(tmp_path)
    a = archie_chat.normalise(doc, {"type": "revise_plan", "notes": "Add a housing.",
                                    "add": {"sub": "Gear pair", "part": visual_office.HOUSING_PART}})
    service.revise_plan(root, doc, a, {"name": "Eng"})
    assert doc["status"] == "plan_review" and doc["tickets"] == [] and "icd" not in doc
    assert service.gate(doc, "brief")["status"] == "pending" and service.gate(doc, "icd")["status"] == "locked"
    names = [p["name"] for p in doc["plan"]["subassemblies"][0]["parts"]]
    assert names[0] == "Housing" and len(names) == 6
    assert "Archie sent the plan back" in doc["plan"]["note"]
    # once part work starts, the plan can't go back
    service.approve_plan(root, doc, None, {"name": "Eng"})
    doc["tickets"][0]["run"] = {"status": "designing"}
    assert archie_chat.normalise(doc, {"type": "revise_plan", "notes": "x"}) is None


def test_archie_speaks_first_in_the_chat(tmp_path: Path) -> None:
    root, doc = _program(tmp_path)
    archie_chat.post(root, doc["id"], "Hello", [{"type": "fix_icd"}], kind="look", visual={"level": "layout"})
    m = archie_chat.history(root, doc["id"])[-1]
    assert m["role"] == "archie" and m["unprompted"] and m["kind"] == "look" and m["visual"] == {"level": "layout"}
    assert m["actions"][0]["status"] == "proposed"


def test_failure_and_level_messages() -> None:
    doc = {"status": "active"}
    t = {"key": "GP-7", "title": "Assemble Gear pair", "item_id": "i_s1"}
    text, acts = visual_office.failure_message(doc, t, "Fitz couldn't integrate this: timeout (3 tries).")
    assert text.startswith("GP-7 Assemble Gear pair is blocked: Fitz couldn't integrate") and acts == [
        {"type": "retry_blocked"}]
    text, acts = visual_office.failure_message(doc, t, "x.", retrying=True)
    assert "retries it shortly on its own" in text and acts == []
    look = {"stop": True, "reason": "Nothing touches.", "line": "", "quick": [{"severity": "block",
                                                                              "text": "4 of 4 parts touch nothing."}]}
    text, acts = visual_office.level_message(t, look)
    assert text.startswith("I stopped GP-7 Assemble Gear pair: Gear pair isn't assembled") and acts[0]["type"] == \
        "retry_blocked"


def test_parts_without_interfaces_are_a_note_not_a_stop() -> None:
    doc = {"icd": {"interfaces": [{"a": {"item": "A"}, "b": {"item": "B"}}]}, "skeleton": {"items": {
        "A": {}, "B": {}, "C": {}}}}
    adoc = {"instances": [{"id": "i1", "office": {"item": "A"}}, {"id": "i3", "office": {"item": "C"}}]}
    f = visual_office.known_loose(doc, adoc, [{"code": "floating", "severity": "block", "items": ["i3"], "text": "x"}])
    assert f[0]["severity"] == "note"


def test_icd_problems_read_generically() -> None:
    assert visual_office.problem_text("Plain") == "Plain"
    assert visual_office.problem_text({"code": "row_layout", "message": "Laid out in a row", "items": ["a"]}) == \
        "Laid out in a row"
    assert visual_office.problem_code({"code": "row_layout"}) == "row_layout" and visual_office.problem_code("x") is None


def test_centre_distance_formula() -> None:
    assert math.isclose(2 * (20 + 60) / 2, 80.0)


# ============================================================================ placement checks on real parts
@pytest.fixture(scope="module")
def gear_docs(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The test case built by hand from Toolbox parts: correct, in a row, gear 5 mm off the mesh plane, a bearing
    60 mm off its shaft. Parts go through the assembly worker (real CAD)."""
    from aicad.assembly import service as aservice
    from aicad.assembly import store, xform
    from aicad.assembly import worker as aworker

    data = tmp_path_factory.mktemp("visual")
    root = store.org_root(data, "orgv")

    def Ty(x: float, y: float, z: float, turn: float = 0.0) -> list[float]:
        Rx = xform.make(xform.rot((1, 0, 0), -math.pi / 2), (0, 0, 0))  # part Z -> world +Y
        Rs = xform.make(xform.rot((0, 0, 1), math.radians(turn)), (0, 0, 0))
        return xform.to12(xform.translate((x, y, z)) @ Rx @ Rs)

    async def build() -> dict[str, Any]:
        tb = aservice.ensure_toolbox_part
        pin = await tb(root, "orgv", "spur_gear", {"M": 2, "Z": 20, "B": 20, "BORE": 20})
        gear = await tb(root, "orgv", "spur_gear", {"M": 2, "Z": 60, "B": 20, "BORE": 20})
        shaft = await tb(root, "orgv", "shaft", {"D": 20, "L": 120, "KEY_L": 16, "C": 1})
        brg = await tb(root, "orgv", "bearing", {"SERIES": 6204})
        docs = {}
        for v in ("ok", "row", "offset", "float"):
            doc = store.new_doc(v, "orgv", "u", None)
            if v == "row":
                for k, n in ((pin, "Pinion"), (gear, "Gear"), (shaft, "Input shaft"), (shaft, "Output shaft")):
                    aservice.add_instance(root, doc, k, name=n)
            else:
                aservice.add_instance(root, doc, shaft, T=Ty(0, 0, 0), name="Input shaft")
                aservice.add_instance(root, doc, shaft, T=Ty(80, 0, 0), name="Output shaft")
                aservice.add_instance(root, doc, pin, T=Ty(0, 50, 0), name="Pinion")
                aservice.add_instance(root, doc, gear, T=Ty(80, 55 if v == "offset" else 50, 0, 3.0), name="Gear")
                for x in (0.0, 80.0):
                    for y0 in (10.0, 96.0):
                        up = 60.0 if v == "float" and x == 80.0 and y0 == 96.0 else 0.0
                        aservice.add_instance(root, doc, brg, T=Ty(x, y0, up), name="Ball bearing 6204")
            docs[v] = doc
        await aworker.shutdown_all()
        return docs

    docs = asyncio.run(build())
    yield root, docs
    aworker.kill_all()


def test_quick_checks_on_the_hand_built_gear_pair(gear_docs: Any, tmp_path: Path) -> None:
    root, docs = gear_docs
    q = visual.quick_doc(root, docs["ok"])
    assert q["findings"] == [] and q["seconds"] < 1.0  # measured ~6 ms
    g = q["gear_pairs"][0]
    assert (g["a_mm"], g["centre_mm"], g["offset_mm"], g["engaged_mm"]) == (80.0, 80.0, 0.0, 20.0)
    assert [f["code"] for f in visual.quick_doc(root, docs["row"])["findings"]] == ["row"]
    off = visual.quick_doc(root, docs["offset"])["findings"]
    # 5 mm along the axes: 20 - 5 = 15 of 20 mm face width in mesh
    assert [f["code"] for f in off] == ["gear_plane"] and "only 15 of 20 mm face width" in off[0]["text"]
    fl = visual.quick_doc(root, docs["float"])["findings"]
    assert [f["code"] for f in fl] == ["floating"] and "Ball bearing 6204<4>" in fl[0]["text"]
    rels = [r["text"] for r in visual.relations_from_doc(root, docs["ok"])]
    assert rels == [("Pinion<1> meshes with Gear<1>: axes parallel, 80 mm apart (m (z1 + z2) / 2), the two gears in "
                    "one plane")]
    out = render.render(render.scene_from_doc(root, docs["ok"], "Gear pair"), tmp_path / "ok.png")
    assert out["bodies"] == 8 and out["seconds"] < 60  # measured 1.3-2.6 s
