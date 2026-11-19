"""Small programs in the Design Office (founder, 2026-11-19): "Build a Spur Gear mounted on stepped Shaft and locked
with a key". The Design Studio did it in a minute; the Design Office added a shaft support housing although the brief
said "No extra items. Just a spur gear, a shaft and a key", blocked on a shaft-support rule meant for gearboxes, ran
9 tickets for 3 parts and assembled the key into the parts bin.

Standing test case. Every expected number is a hand calculation, never a measurement of what was built:

* Spur gear m2, 30 teeth (assumed): pitch Ø m z = 60, tip Ø m (z + 2) = 64, face width 10 m = 20.
* Shaft seat Ø20 (assumed), larger step Ø20 + 2 max(2.5, 0.1 * 20 + 1) = Ø26 (``icd.shoulder_for``), 80 long (assumed).
* DIN 6885-1, shaft over 17 up to 22: key 6 x 6, t1 3.5 (shaft), t2 2.8 (hub); key length floor(max(b + 2, B - 2))
  = floor(max(8, 18)) = 18, centred on the hub.
* Layout: the shoulder face is datum B (Y = 0); the gear (20 wide) on its -Y side, Y -20..0, centre Y -10; the seat
  runs SEAT_END = 2 mm past the free hub face: Y -22..0; the shaft is 80 long: Y -22..58, centre Y 18.
* Key: span Y -20 + (20 - 18) / 2 = -19 .. -1 (centred on the hub, inside it); its underside on the keyseat floor
  d / 2 - t1 = 10 - 3.5 = 6.5 from the axis, on +X: base point (6.5, -10, 0).
No live AI (simulated agents).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from test_office_orchestrator import _topup, _wait, office  # noqa: F401  (fixture)
from test_office_shaft_line import _parts
from test_toolbox_keys import _overlap

from aicad.office import direct, icd, planner, scope

FOUNDER = "Build a Spur Gear mounted on stepped Shaft and locked with a key"
FOUNDER_RUN = ("Build a Spur Gear, mounted on shaft and locked with a key. No extra items. Just a spur gear, a shaft "
               "and a key")
# Archie's plan in the founder's failing run (2026-11-19), after the shaft-support rule made him add a housing
ARCHIE_RUN = {"source": "archie", "summary": "A single keyed spur gear on a plain steel shaft.", "assumptions": [],
              "subassemblies": [
                  {"name": "Keyed shaft", "description": "Shaft with its key.", "parts": [
                      {"name": "Shaft support housing", "family": "machined", "complexity": 2, "qty": 1,
                       "description": "Simple machined block with two aligned 20 mm bores carrying the shaft ends."},
                      {"name": "Shaft", "family": "turned", "complexity": 2, "qty": 1, "envelope": [20, 20, 80],
                       "description": "C45 steel shaft, 20 mm h6 diameter by 80 mm long (assumed), chamfered ends, "
                                      "with an 18 mm long, 6 mm wide, 3.5 mm deep closed keyseat."},
                      {"name": "Parallel key", "family": "standard", "complexity": 1, "qty": 1,
                       "description": "DIN 6885 form A parallel key 6 x 6 x 18, C45."}]},
                  {"name": "Spur gear", "description": "The gear.", "parts": [
                      {"name": "Spur gear", "family": "gear", "complexity": 3, "qty": 1, "envelope": [64, 64, 20],
                       "mounts_on": "Shaft", "module": 2, "teeth": 30,
                       "description": "42CrMo4 involute spur gear, module 2, 30 teeth, face width 20 mm (assumed), "
                                      "with a 20 H7 bore and a 6 mm JS9 hub keyway 2.8 mm deep."}]}]}


def _std_parts() -> list[dict[str, Any]]:
    plan, note = planner.finish(planner.standard_plan("Keyed gear", FOUNDER), "Keyed gear", FOUNDER)
    assert note is None
    return _parts(plan)


def _ids(sk: dict[str, Any]) -> dict[str, str]:
    return {it["name"]: i for i, it in sk["items"].items()}


# ---------------------------------------------------------------------------- A. the brief is respected
def test_the_brief_is_read() -> None:
    named, excluded = scope.mentions(FOUNDER_RUN)
    assert named == {"gear", "shaft", "key"} and excluded == set() and scope.exclusive(FOUNDER_RUN)
    assert scope.mentions(FOUNDER)[0] == {"gear", "shaft", "key"} and not scope.exclusive(FOUNDER)
    named, excluded = scope.mentions("A gear on a shaft without a housing, bearings or a base plate")
    assert named == {"gear", "shaft"} and {"housing", "bearing", "plate"} <= excluded
    assert scope.mentions("no housing, just a gear and a shaft") == ({"gear", "shaft"}, {"housing"})
    # the head noun names the part: "Shaft support housing" is a housing, "Pinion key" a key, "Gear shaft" a shaft
    assert [scope.kind_of(n) for n in ("Shaft support housing", "Parallel key", "Pinion key", "Gear shaft",
                                       "Spur gear", "Gear circlip", "Base plate", "Bearing cap")] == \
        ["housing", "key", "key", "shaft", "gear", "ring", "plate", "cap"]


def test_the_planner_leaves_out_what_the_brief_excludes() -> None:
    plan = planner.normalise_plan(ARCHIE_RUN, "archie")
    assert plan is not None
    out, note = planner.finish(plan, "Test 5", FOUNDER_RUN)
    assert note == ("You asked for just a spur gear, a shaft and a key, so I left out the shaft support housing I'd "
                    "normally add. Add it back here if you want it.")
    # three parts, no extras, one sub-assembly (a small program assembles as one unit)
    assert [(s["name"], [p["name"] for p in s["parts"]]) for s in out["subassemblies"]] == \
        [("Keyed shaft", ["Shaft", "Parallel key", "Spur gear"])]
    assert out["scope"]["dropped"] == ["Shaft support housing"]
    # an explicit exclusion works without "just": a planner's housing goes, the rest stays
    out, note = planner.finish(plan, "x", "A spur gear keyed on a shaft, no housing.")
    assert [p["name"] for s in out["subassemblies"] for p in s["parts"]] == ["Shaft", "Parallel key", "Spur gear"]
    assert note is not None and note.startswith("You asked for no housing, so I left out the shaft support housing")
    # nothing excluded, nothing limited: the plan stays as it is (only merged into one unit)
    out, note = planner.finish(plan, "x", "A spur gear keyed on a shaft in a housing.")
    assert note is None and sum(len(s["parts"]) for s in out["subassemblies"]) == 4


def test_the_standard_planner_plans_the_founders_sentence() -> None:
    plan = planner.standard_plan("Keyed gear", FOUNDER)
    assert [(p["name"], p["family"], p["qty"]) for s in plan["subassemblies"] for p in s["parts"]] == [
        ("Stepped shaft", "turned", 1), ("Spur gear", "gear", 1), ("Parallel key", "standard", 1)]
    assert len(plan["subassemblies"]) == 1
    lt = scope.light_info(plan, FOUNDER)
    assert lt is not None and (lt["parts"], lt["pieces"], lt["deliverables_asked"]) == (3, 3, False)
    assert scope.light_info(plan, FOUNDER + ", with drawings")["deliverables_asked"] is True
    # the rule (PD-88): at most 6 part lines and 8 pieces
    big = {"subassemblies": [{"parts": [{"qty": 1}] * 7}]}
    assert not scope.small(big) and not scope.small({"subassemblies": [{"parts": [{"qty": 9}]}]})


def test_archie_is_told_to_plan_only_what_is_asked() -> None:
    t = planner.ARCHIE_INSTRUCTIONS
    assert "1 to 8 sub-assemblies" in t and "2 to 8" not in t
    assert "Never add a part only to make the layout complete" in t
    assert "a sub-assembly that goes into the customer's own machine" in t


# ---------------------------------------------------------------------------- B. the shaft sub-assembly
def test_shaft_subassembly_layout_hand_checked() -> None:
    parts = _std_parts()
    sk, ifs = icd.build(parts, FOUNDER)
    by = _ids(sk)
    sh, gear = by["Stepped shaft"], by["Spur gear"]
    key = next(p["id"] for p in parts if p["name"] == "Parallel key")
    it = sk["items"]
    assert sk["layout"] == "shaft_line" and sk["shaft_subassembly"] and sk["base"] == sh
    assert len(it) == 2 and [s["name"] for s in sk["standard"]] == ["Parallel key"]  # 3 parts, no extras
    # the shaft is the fixed base on the origin axis, along +Y; Ø26 x 80, centre Y 18 (Y -22 .. 58)
    assert it[sh]["parent"] is None and it[sh]["ax"] == "y"
    assert it[sh]["size"] == [26, 26, 80] and it[sh]["copies"] == [[0, 18, 0]]
    # the gear on the seat against the shoulder: tip Ø64 x 20, centre Y -10 (Y -20 .. 0), bored Ø20
    assert it[gear]["parent"] == sh and it[gear]["size"] == [64, 64, 20] and it[gear]["copies"] == [[0, -10, 0]]
    assert it[gear]["bore"] == 20
    kinds = [(f["id"], f["kind"]) for f in ifs]
    assert kinds == [("IF-01", "shaft_bore"), ("IF-02", "key")]
    b = ifs[0]["data"]
    assert (b["d"], b["fit"], b["z"], b["seat_z"], b["shoulder_z"], b["shoulder_d"], b["side"]) == \
        (20, "H7/k6", [-20, 0], [-22, 0], 0, 26, 1)
    k = ifs[1]["data"]
    assert (k["d"], k["b"], k["h"], k["t1"], k["t2"], k["length"], k["z"], k["hub_z"], k["key_item"]) == \
        (20, 6, 6, 3.5, 2.8, 18, [-19, -1], [-20, 0], key)
    # the key centred in its keyseat ((-19 + -1) / 2 = -10, the hub's centre) and inside the hub length
    assert (k["z"][0] + k["z"][1]) / 2 == -10 and k["hub_z"][0] <= k["z"][0] and k["z"][1] <= k["hub_z"][1]
    seat = icd.seated(ifs, key)
    assert seat is not None and seat["code"] == "parallel_key" and seat["params"] == {"D": 20.0, "L": 18.0}
    assert seat["at"] == [[6.5, -10, 0]]
    # the gates pass with no housing: no problem, one note (delivered as a sub-assembly)
    assert icd.problems(sk, ifs) == []
    iss = icd.issues(sk, ifs)
    assert [(x["code"], x["severity"]) for x in iss] == [("shaft_support", "warning")]
    assert "delivered as a sub-assembly" in iss[0]["text"]
    assert [d["name"] for d in sk["datums"]][1] == "Shoulder face of the Stepped shaft (the Spur gear locates on it)"
    # the shaft's features in its own frame (Z along program +Y, centred): seat Z -40 .. -18, shoulder face at -18
    # looking at the gear (-Z), keyseat -37 .. -19; the gear's face at +10 (+Z) bears on it
    sf = {x["label"]: x for x in icd.item_features(sk, ifs, sh)}
    assert (sf["seat Ø20 k6 (stepped shaft)"]["z0"], sf["seat Ø20 k6 (stepped shaft)"]["z1"]) == (-40, -18)
    assert (sf["shoulder Ø26 (the hub locates on it)"]["z"], sf["shoulder Ø26 (the hub locates on it)"]["n"]) == (-18, -1)
    gf = {x["label"]: x for x in icd.item_features(sk, ifs, gear)}
    assert (gf["hub face against the shoulder"]["z"], gf["hub face against the shoulder"]["n"]) == (10, 1)


def test_archies_plan_from_the_failing_run_now_assembles() -> None:
    """The founder's own run: the key was planned in another sub-assembly than the gear, so it went to the parts
    bin; the shaft had no bearings, so the gate blocked until a housing was added."""
    plan = planner.normalise_plan(ARCHIE_RUN, "archie")
    assert plan is not None
    out, _note = planner.finish(plan, "Test 5", FOUNDER_RUN)
    parts = _parts(out)
    sk, ifs = icd.build(parts, FOUNDER_RUN)
    key = next(p["id"] for p in parts if p["name"] == "Parallel key")
    assert sk["layout"] == "shaft_line" and icd.problems(sk, ifs) == []
    assert icd.seated(ifs, key)["at"] == [[6.5, 0, 0]]  # a plain shaft: the gear centred on it, the key under it
    # and the planned key is seated even when Archie keeps it in another sub-assembly than the gear
    sk2, ifs2 = icd.build(_parts(plan)[1:], FOUNDER_RUN)
    k2 = next(p["id"] for p in _parts(plan) if p["name"] == "Parallel key")
    assert next(f for f in ifs2 if f["kind"] == "key")["data"]["key_item"] == k2 and icd.problems(sk2, ifs2) == []


def test_shaft_support_still_blocks_where_bearings_are_planned() -> None:
    one = {"source": "standard", "summary": "", "assumptions": [], "subassemblies": [{"name": "A", "description": "",
           "parts": [{"name": "Shaft", "family": "turned", "complexity": 2, "qty": 1, "description": "Ø20 x 100"},
                     {"name": "Spur gear", "family": "gear", "complexity": 2, "qty": 1, "description": "m2 30 teeth"},
                     {"name": "Ball bearing 6204", "family": "standard", "complexity": 1, "qty": 1,
                      "description": "6204"}]}]}
    sk, ifs = icd.build(_parts(one), "")
    assert [x["code"] for x in icd.issues(sk, ifs) if x["severity"] == "error"] == ["shaft_support"]


def test_parts_are_built_without_ai(tmp_path: Path) -> None:
    """The stepped shaft (seat, shoulder, keyseat) and the gear (bore, hub keyway) are built from the interfaces by
    the direct path; the key is the Toolbox DIN 6885 key."""
    parts = _std_parts()
    sk, ifs = icd.build(parts, FOUNDER)
    doc = {"skeleton": sk, "icd": {"version": 1, "status": "approved", "interfaces": ifs}, "brief": FOUNDER,
           "items": [{"id": p["id"], "name": p["name"], "description": p["description"]} for p in parts]}
    by = _ids(sk)
    p_sh = direct.plan(doc, {"kind": "part", "item_id": by["Stepped shaft"], "title": "Stepped shaft"})
    p_g = direct.plan(doc, {"kind": "part", "item_id": by["Spur gear"], "title": "Spur gear"})
    assert p_sh["path"] == "direct" and p_sh["summary"] == "shaft Ø20 / Ø26 × 80, 1 seat, 1 keyseat"
    assert p_g["path"] == "direct" and p_g["summary"] == "spur gear m2 × 30 teeth, face 20, bore Ø20 with a keyway"


def _build(tmp: Path, script: str, name: str) -> tuple[Any, dict[str, Any]]:
    from build123d import import_step

    from aicad.agent import runner

    ws = tmp / name
    (ws / "out").mkdir(parents=True)
    (ws / "model.py").write_text(script, encoding="utf-8")
    runner.main(ws / "model.py", ws / "out", determinism=False, fast=False)
    st = json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
    return import_step(str(ws / "out" / "part.step")), st


def test_the_assembly_fits_hand_checked(tmp_path: Path) -> None:
    """Kernel check: the direct shaft, the direct gear and the Toolbox key placed where Fitz puts them: no
    interference (< 1e-6 mm³ per pair), the gear's face on the shoulder, the key on its keyseat floor, the gear and
    the shaft pass ICD conformance."""
    import numpy as np
    from build123d import Location

    from aicad import toolbox
    from aicad.agent import runner
    from aicad.assembly import geometry
    from aicad.assembly.geometry import _trsf
    from aicad.office import conformance, frames, program_assembly

    parts = _std_parts()
    sk, ifs = icd.build(parts, FOUNDER)
    doc = {"skeleton": sk, "icd": {"version": 1, "status": "approved", "interfaces": ifs}, "brief": FOUNDER,
           "items": [{"id": p["id"], "name": p["name"], "description": p["description"]} for p in parts]}
    by = _ids(sk)
    key = next(p["id"] for p in parts if p["name"] == "Parallel key")

    def at(shape: Any, T12: list[float]) -> Any:
        T = np.array(T12 + [0, 0, 0, 1], dtype=float).reshape(4, 4)
        return shape.moved(Location(_trsf(T)))

    placed: dict[str, Any] = {}
    for name in ("Stepped shaft", "Spur gear"):
        p = direct.plan(doc, {"kind": "part", "item_id": by[name], "title": name})
        shape, st = _build(tmp_path, p["script"], name.replace(" ", "_"))
        assert runner.is_verified(st), [c for c in st["checks"] if not c["passed"]]
        info = geometry.prepare(tmp_path / f"{name}_snap", step=str(tmp_path / name.replace(" ", "_") / "out" /
                                                                   "part.step"))
        refs = json.loads((tmp_path / f"{name}_snap" / "refs.json").read_text())
        res = conformance.measure(sk, doc["icd"], by[name], info, refs)
        assert res["ok"], [r for x in res["interfaces"] for r in x["rows"] if not r["ok"]]
        placed[name] = at(shape, program_assembly.place(sk, by[name], 0))
    seat = icd.seated(ifs, key)
    kshape, _e = toolbox.build(seat["code"], **seat["params"])
    placed["key"] = at(kshape, frames.to12(seat["R"], seat["at"][0]))
    # hand: the shaft Y -22 .. 58 (80), Ø26; the gear Y -20 .. 0, tip Ø64; the key Y -19 .. -1, X 6.5 .. 12.5
    bb = placed["Stepped shaft"].bounding_box()
    assert (bb.min.Y, bb.max.Y, bb.max.X) == pytest.approx((-22, 58, 13), abs=1e-3)
    bb = placed["Spur gear"].bounding_box()
    assert (bb.min.Y, bb.max.Y) == pytest.approx((-20, 0), abs=1e-3) and bb.max.Z <= 32 + 1e-3
    bb = placed["key"].bounding_box()
    assert (bb.min.Y, bb.max.Y, bb.min.X, bb.max.X) == pytest.approx((-19, -1, 6.5, 12.5), abs=1e-3)
    names = sorted(placed)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            v = _overlap(placed[a], placed[b])
            assert v < 1e-6, (a, b, v)
    # nothing floats: the gear touches the shaft (bore on the seat, face on the shoulder), the key its keyseat floor
    assert placed["Spur gear"].distance_to(placed["Stepped shaft"]) < 1e-6
    assert placed["key"].distance_to(placed["Stepped shaft"]) < 1e-6
    # the key sits in the hub keyway with 0.3 mm over its top (t1 + t2 - h = 3.5 + 2.8 - 6)
    assert placed["key"].distance_to(placed["Spur gear"]) < 1e-6  # its sides bear on the keyway walls (b = 6 both)


# ---------------------------------------------------------------------------- C + D. one step, assembled
def test_founders_request_end_to_end(office: Any) -> None:  # noqa: F811
    """The founder's sentence, simulated agents, standard planner (no AI): one click approves the plan and the
    interfaces and runs; 5 tickets (3 parts + the sub-assembly + the final assembly), no drawings or manufacturing
    review until asked; the gear on its seat at the shoulder, the key in its keyseat, nothing in the parts bin."""
    from test_office_icd import _asm
    from test_platform import signup

    from aicad.assembly import store as astore

    c = office
    signup(c, "small@x.com")
    _topup("small@x.com")
    r = c.post("/api/office/programs", json={"name": "Keyed gear", "brief": FOUNDER, "planner": "standard"})
    assert r.status_code == 200, r.text
    v = r.json()
    pid = v["id"]
    assert v["status"] == "plan_review" and v["light"]["parts"] == 3 and v["deliverables_mode"] == "auto"
    t0 = time.time()
    r = c.post(f"/api/office/programs/{pid}/gates/express", json={})
    assert r.status_code == 200, r.text
    v = r.json()
    ex = v["express"]
    assert ex["approved"] and ex["run"] and ex["parts"] == ["Stepped shaft", "Spur gear", "Parallel key"]
    assert ex["interfaces"] == 2 and len(ex["warnings"]) == 1 and "sub-assembly" in ex["warnings"][0]
    assert [g["status"] for g in v["gates"]] == ["approved", "approved", "locked"]
    assert v["deliverables_auto"] is False and "only when you ask" in v["deliverables_why"]
    v = _wait(c, pid, lambda v: v["orchestrator"]["state"] in ("complete", "blocked", "stopped"), timeout=600)
    took = time.time() - t0
    assert v["status"] == "complete", [(t["title"], t["column"], (t.get("run") or {}).get("status")) for t in v["tickets"]]
    titles = sorted(t["title"] for t in v["tickets"])
    assert titles == sorted(["Stepped shaft", "Spur gear", "Parallel key", "Assemble Keyed gear",
                             "Final assembly of Keyed gear"]), titles
    by = {t["title"]: t for t in v["tickets"]}
    assert by["Parallel key"]["reuse"]["code"] == "parallel_key"
    for name in ("Stepped shaft", "Spur gear"):
        assert (by[name].get("direct") or {}).get("path") == "direct", (name, by[name].get("direct"))
    st = v["assembly"]
    assert st["clashes"] == [], st.get("summary")
    final = astore.load(_asm(c)[0], st["final"])
    pos: dict[str, tuple[float, float, float]] = {}
    for i in final["instances"]:
        o = i.get("office") or {}
        assert not o.get("bin"), i.get("name")
        pos[i["name"]] = (round(i["T"][3], 3), round(i["T"][7], 3), round(i["T"][11], 3))
    assert pos["Parallel key"] == (6.5, -10, 0)
    assert len(final["instances"]) == 3
    print(f"\nfounder's request, simulated: brief -> assembled in {took:.1f} s")
