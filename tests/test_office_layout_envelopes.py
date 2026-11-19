"""CD-029: the layout respects the envelopes Archie planned. A host the plan sized keeps its size when its children
don't fit side by side (each child needs only its joint's pad), a part grows only for its own features (hole wall,
washer spacing, a rim round a hosted bore), and anything laid out beyond PLAN_SLACK x its plan is an ICD problem
that Archie's self-fix may not paper over. Pure layout tests (no app, no AI)."""

from __future__ import annotations

import json
from typing import Any

from aicad.office import icd, interfaces, planner

# An original toy rover display model: a chassis carrying a body far longer than a row of its children allows, four
# wheel arms, thin sensor fins with M3 screws, a small camera bracket with two M3 screws, axles in the arms and a
# 3 mm tie rod Archie hung on an axle (a rod, not a hub: it must not be given the axle's bore).
ROVER = {"summary": "Rover display model", "assumptions": [], "subassemblies": [
    {"name": "Body", "description": "", "parts": [
        {"name": "Chassis plate", "family": "plastic", "complexity": 3, "qty": 1, "description": "Printed plate.",
         "envelope": [300.0, 120.0, 12.0]},
        {"name": "Body shell", "family": "plastic", "complexity": 4, "qty": 1, "description": "Shell.",
         "envelope": [260.0, 110.0, 60.0], "mounts_on": "Chassis plate"},
        {"name": "Battery box", "family": "plastic", "complexity": 2, "qty": 1, "description": "Box.",
         "envelope": [120.0, 80.0, 40.0], "mounts_on": "Chassis plate"},
        {"name": "Sensor fin", "family": "plastic", "complexity": 1, "qty": 2, "description": "Thin fin.",
         "envelope": [50.0, 4.0, 30.0], "mounts_on": "Body shell"},
        {"name": "Camera bracket", "family": "machined", "complexity": 1, "qty": 1,
         "description": "Small bracket, two M3 screws.", "envelope": [18.0, 10.0, 12.0], "mounts_on": "Body shell"},
        {"name": "Mast", "family": "plastic", "complexity": 1, "qty": 1, "description": "Mast.",
         "envelope": [30.0, 30.0, 80.0], "mounts_on": "Body shell"},
        {"name": "M3 cap screw", "family": "standard", "complexity": 1, "qty": 20, "description": "ISO 4762 M3x10."}]},
    {"name": "Running gear", "description": "", "parts": [
        {"name": "Wheel arm", "family": "plastic", "complexity": 2, "qty": 4, "description": "Arm.",
         "envelope": [60.0, 30.0, 6.0], "mounts_on": "Chassis plate"},
        {"name": "Axle", "family": "turned", "complexity": 1, "qty": 4, "description": "Steel axle.",
         "envelope": [10.0, 10.0, 30.0], "mounts_on": "Wheel arm"},
        {"name": "Hub cap", "family": "turned", "complexity": 1, "qty": 4, "description": "Cap.",
         "envelope": [16.0, 16.0, 5.0], "mounts_on": "Axle"},
        {"name": "Tie rod", "family": "turned", "complexity": 1, "qty": 2, "description": "3 mm rod.",
         "envelope": [3.0, 3.0, 50.0], "mounts_on": "Axle"}]}]}


TIE_ROD = "i_s2_p11"


def _parts(plan: dict[str, Any]) -> list[dict[str, Any]]:
    p = planner.normalise_plan(plan, "archie")
    assert p is not None
    return [{"id": f"i_{s['id']}_{q['id']}", "name": q["name"], "family": q["family"], "qty": q["qty"],
             "description": q["description"], "complexity": q["complexity"], "sub": f"i_{s['id']}",
             **{k: q[k] for k in ("envelope", "mounts_on") if q.get(k) is not None}}
            for s in p["subassemblies"] for q in s["parts"]]


def _by_name(sk: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {it["name"]: it for it in sk["items"].values()}


def test_a_crowded_plan_keeps_its_planned_envelopes() -> None:
    parts = _parts(ROVER)
    sk, ifs = icd.build(parts, "A rover display model.")
    # the only problem: the tie rods Archie hung on an axle have no interface in this layout, so they would lie
    # beside the rover; the gate says so (and blocks) instead of passing them silently
    assert [(x["code"], x["items"]) for x in icd.issues(sk, ifs)] == [("no_interface", [TIE_ROD])]
    assert icd.problems(sk, ifs)[0].startswith("Tie rod: no interface connects it")
    it = _by_name(sk)
    for p in parts:
        if p["family"] == "standard":
            continue
        x = sk["items"][p["id"]]
        assert x["planned"], p["name"]
        assert all(s <= icd.PLAN_SLACK * q + 1e-6 for s, q in zip(x["size"], x["planned"], strict=True)), \
            (p["name"], x["size"], x["planned"])
    # the hosts keep the plan's size: the children don't line up their whole footprints on them
    assert it["Chassis plate"]["size"] == [300, 120, 12]
    assert it["Body shell"]["size"] == [260, 110, 60]
    assert it["Wheel arm"]["size"] == [60, 30, 6]
    # own features only: the 4 mm fin holds an M3 hole with 1 mm of wall each side (3.4 + 2 = 5.4)
    assert it["Sensor fin"]["size"] == [50, 5.4, 30]
    # the 18 mm bracket holds two M3 bolts whose washers (Ø7, ISO 7089) just clear: centres 7 apart, 1 mm wall
    cam = next(f for f in ifs if f["b"]["name"] == "Camera bracket" and f["kind"] == "hole_pattern")["data"]
    (x0, y0), (x1, y1) = cam["positions"]
    assert cam["fastener"] == "M3" and abs(abs(x1 - x0) + abs(y1 - y0) - 7.0) < 1e-6
    assert it["Camera bracket"]["size"] == [18, 10, 12]
    # four axles over four arms: one each, at the planned 30 mm (not one arm carrying all four)
    axle = it["Axle"]
    assert axle["size"] == [10, 10, 30]
    arms = {(f["a"]["item"], f["a"]["copy"]) for f in ifs if f["b"]["name"].startswith("Axle")
            and f["a"]["name"].startswith("Wheel arm") and f["kind"] == "shaft_bore"}
    assert len(arms) == 4
    # the tie rod is a rod (a shaft by its planned shape): nothing bores it out to the axle's Ø10
    assert it["Tie rod"]["role"] == "shaft" and it["Tie rod"]["size"] == [3, 3, 50]
    assert not any(f["a"]["name"].startswith("Tie rod") and f["kind"] == "shaft_bore" for f in ifs)
    # deterministic
    assert json.dumps(icd.build(parts, "A rover display model."), sort_keys=True) == json.dumps((sk, ifs),
                                                                                                sort_keys=True)


def test_an_envelope_beyond_the_plan_is_an_icd_problem_and_self_fix_respects_it() -> None:
    plan = json.loads(json.dumps(ROVER))
    # a 12 x 6 tab told to take the sub-assembly's M6 screws: two M6 bolts need 12 + 6.6 + 2 = 20.6 mm (1.7 x)
    body = plan["subassemblies"][0]["parts"]
    body.append({"name": "Tab", "family": "plastic", "complexity": 1, "qty": 1, "description": "Tab.",
                 "envelope": [12.0, 6.0, 8.0], "mounts_on": "Body shell"})
    next(p for p in body if p["family"] == "standard").update(name="M6 cap screw", description="ISO 4762 M6x16.")
    parts = _parts(plan)
    sk, ifs = icd.build(parts, "")
    probs = icd.problems(sk, ifs)
    tab = [p for p in probs if p.startswith("Tab:")]
    assert tab and "laid out at 20.6 × 8.6 × 8 mm" in tab[0] and "planned 12 × 6 × 8 mm" in tab[0]
    # Archie's self-fix may grow a part only up to 1.5 x its plan
    it = _by_name(sk)["Tab"]
    for ch in interfaces._grow(it):
        assert all(v <= 1.5 * dict(zip(("L", "W", "H"), it["planned"], strict=True))[k] + 1e-6
                   for k, v in ch.items())
    assert interfaces._grow({"role": "block", "size": [12, 6, 8], "planned": [12, 6, 8]})  # small growth allowed
    assert interfaces._grow({"role": "block", "size": [18, 9, 12], "planned": [12, 6, 8]}) == []
    # a smaller bolt (an interface change the engineer sees) brings it back inside the plan
    doc = {"brief": "", "plan": planner.normalise_plan(plan, "archie"), "items": [], "tickets": []}
    for s in doc["plan"]["subassemblies"]:
        for q in s["parts"]:
            doc["items"].append({"id": f"i_{s['id']}_{q['id']}", "kind": "part", "name": q["name"],
                                 "family": q["family"], "qty": q["qty"], "description": q["description"],
                                 "parent_id": f"i_{s['id']}"})
    ov, steps, left = interfaces.autofix(doc, {"items": {}, "interfaces": {}})
    assert [p.split(":")[0] for p in left] == ["Tie rod"] and steps  # (no interface: Archie can't fix that alone)
    sk2, _ifs2 = icd.build(icd.parts_from(doc), "", ov)
    t2 = _by_name(sk2)["Tab"]
    assert all(s <= 1.5 * q + 1e-6 for s, q in zip(t2["size"], t2["planned"], strict=True))


def test_a_resize_by_the_engineer_replaces_the_plan() -> None:
    parts = _parts(ROVER)
    shell = next(p["id"] for p in parts if p["name"] == "Body shell")
    sk, ifs = icd.build(parts, "", {"items": {shell: {"L": 420.0}}, "interfaces": {}})
    assert sk["items"][shell]["size"][0] == 420 and sk["items"][shell]["planned"][0] == 420
    assert not [p for p in icd.problems(sk, ifs) if p.startswith("Body shell:")]
    # the same size reached by Archie's growth (``grown``) is still measured against the plan
    sk2, ifs2 = icd.build(parts, "", {"items": {shell: {"L": 420.0, "grown": ["L"]}}, "interfaces": {}})
    assert any(p.startswith("Body shell: laid out at 420 × 110 × 60 mm") for p in icd.problems(sk2, ifs2))


def test_unplanned_layouts_are_unchanged() -> None:
    """Without envelopes in the plan nothing is planned: rows grow their hosts as before (gearbox unchanged)."""
    plan = planner.standard_plan("Gear reducer", "A spur gear reducer, 3:1, 1450 rpm input.")
    parts = [{"id": f"i_{s['id']}_{p['id']}", "name": p["name"], "family": p["family"], "qty": p["qty"],
              "description": p["description"], "complexity": p["complexity"], "sub": f"i_{s['id']}"}
             for s in plan["subassemblies"] for p in s["parts"]]
    sk, ifs = icd.build(parts, "A spur gear reducer, 3:1, 1450 rpm input.")
    assert icd.problems(sk, ifs) == [] and not any(it.get("planned") for it in sk["items"].values())
    housing = next(it for it in sk["items"].values() if it["name"] == "Housing base")
    assert housing["size"] == [198, 82, 134]
