"""A planetary gearbox through the design graph and the connection layout (founder's "Planetary Gearbox", 2026-11-20).

The founder's program was stuck at the interfaces gate: the intent reply gave the ring the planets' 30 teeth and seated
the planet bearings in the housing, the connection solver had no rule for planets on bearings on pins in a carrier
("Planet gear meshes or belts but sits on no shaft"), so the plan went to a master model whose measured layout hung
the gears on the housing (every part a "block"), and a revision with Archie's mount and size changes said "the
revised layout is the same as the one the program has" (the master path kept the measured positions). Pure: no model
call, no CAD kernel.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any

import pytest

from aicad.assembly import visual
from aicad.graph import compile as gc
from aicad.graph import intent, planetary
from aicad.master import decide
from aicad.office import icd, revision, service, store

BRIEF = "Build a planetary Gearbox"
ENG = {"kind": "user", "id": "u1", "name": "Eng"}

# the intent reply as the model gave it for the founder's brief (the structure of the live program's graph), with
# its two mistakes: the ring with 30 teeth, and the planet bearings seated in the housing wall
REPLY: dict[str, Any] = {
    "summary": "Single-stage planetary gearbox: a keyed sun on the input shaft drives three planets on ball bearings.",
    "components": [
        {"id": "housing", "kind": "housing", "name": "Gearbox base", "params": {"style": "split"}},
        {"id": "cover", "kind": "cover", "name": "Gearbox cover"},
        {"id": "input_shaft", "kind": "shaft", "name": "Input shaft", "params": {"role": "input"}},
        {"id": "output_shaft", "kind": "shaft", "name": "Output shaft", "params": {"role": "output"}},
        {"id": "sun_gear", "kind": "spur_gear", "name": "Sun gear", "params": {"module": 2, "teeth": 30}},
        {"id": "planet_gear", "kind": "spur_gear", "name": "Planet gear", "qty": 3, "params": {"module": 2, "teeth": 30}},
        {"id": "ring_gear", "kind": "spur_gear", "name": "Ring gear (internal)", "params": {"module": 2, "teeth": 30}},
        {"id": "carrier", "kind": "hub", "name": "Planet carrier"},
        {"id": "planet_pin", "kind": "shaft", "name": "Planet pin", "qty": 3, "params": {"stepped": False}},
        {"id": "planet_bearing", "kind": "bearing", "name": "Planet bearing", "qty": 3},
        {"id": "sun_key", "kind": "key", "name": "Sun gear key"},
        {"id": "carrier_key", "kind": "key", "name": "Carrier key"},
        {"id": "input_bearing", "kind": "bearing", "name": "Input shaft bearing", "qty": 2},
        {"id": "output_bearing", "kind": "bearing", "name": "Output shaft bearing", "qty": 2},
        {"id": "input_cap", "kind": "bearing_cap", "name": "Input open cap", "params": {"style": "open"}},
        {"id": "output_cap", "kind": "bearing_cap", "name": "Output open cap", "params": {"style": "open"}},
        {"id": "cap_screw", "kind": "fastener", "name": "Cap screw", "qty": 8},
        {"id": "cover_bolt", "kind": "fastener", "name": "Cover bolt", "qty": 6}],
    "connections": [
        {"kind": "keyed_hub", "host": "input_shaft", "guest": "sun_gear", "via": ["sun_key"]},
        {"kind": "gear_mesh", "host": "sun_gear", "guest": "planet_gear"},
        {"kind": "gear_mesh", "host": "planet_gear", "guest": "ring_gear"},
        {"kind": "mounted_on", "host": "housing", "guest": "ring_gear"},
        {"kind": "bearing_journal", "host": "planet_pin", "guest": "planet_bearing", "params": {"count": 1}},
        {"kind": "mounted_on", "host": "planet_bearing", "guest": "planet_gear"},
        {"kind": "mounted_on", "host": "carrier", "guest": "planet_pin"},
        {"kind": "keyed_hub", "host": "output_shaft", "guest": "carrier", "via": ["carrier_key"]},
        {"kind": "bearing_journal", "host": "input_shaft", "guest": "input_bearing", "params": {"count": 2}},
        {"kind": "bearing_journal", "host": "output_shaft", "guest": "output_bearing", "params": {"count": 2}},
        {"kind": "bearing_seat", "host": "housing", "guest": "input_bearing"},
        {"kind": "bearing_seat", "host": "housing", "guest": "output_bearing"},
        {"kind": "bolted_joint", "host": "housing", "guest": "cover", "via": ["cover_bolt"]},
        {"kind": "bolted_joint", "host": "housing", "guest": "input_cap", "via": ["cap_screw"]},
        {"kind": "bolted_joint", "host": "housing", "guest": "output_cap", "via": ["cap_screw"]},
        {"kind": "bearing_seat", "host": "housing", "guest": "planet_bearing", "params": {"count": 1}}],
}


def _graph(reply: dict[str, Any] = REPLY, brief: str = BRIEF):
    g, iss, _qs = intent.compile_reply(copy.deepcopy(reply), "Planetary Gearbox", brief)
    assert not [i for i in iss if i["severity"] == "error"], iss
    return g


def _plan(g) -> dict[str, Any]:
    p = gc.to_plan(g, resolved=True)
    skel, _ifs = gc.to_icd(g, p)
    p["graph"]["data"] = gc.read_layout(g, skel).dump()
    return p


def test_the_graph_is_made_consistent_ring_teeth_and_mounting_chain() -> None:
    g = _graph()
    ring, planet, sun = g.comp("ring_gear"), g.comp("planet_gear"), g.comp("sun_gear")
    assert ring.v("internal") is True
    assert ring.v("teeth") == 90  # z_ring = z_sun + 2 z_planet
    assert (int(sun.v("teeth")) + int(ring.v("teeth"))) % 3 == 0  # three planets can be assembled
    assert planet.v("bore") == 47.0  # the outer ring of its 6204
    # the planet bearings sit in the planets, never in the housing wall
    assert not [x for x in g.connections if x.kind == "bearing_seat" and x.guest == "planet_bearing"]
    meshes = {(x.host, x.guest): x.v("centre_distance") for x in g.connections if x.kind == "gear_mesh"}
    assert meshes[("sun_gear", "planet_gear")] == 60.0
    assert meshes[("planet_gear", "ring_gear")] == 60.0  # internal: m (z_r - z_p) / 2
    ps = planetary.find(g)
    assert ps is not None and (ps.input, ps.output, ps.carrier, ps.pin) == ("input_shaft", "output_shaft", "carrier",
                                                                            "planet_pin")
    assert planetary.normalise(copy.deepcopy(g)).dump() == g.dump()  # idempotent


def test_a_stated_ratio_sizes_the_teeth() -> None:
    reply = copy.deepcopy(REPLY)
    for c in reply["components"]:
        if c["kind"] == "spur_gear":
            c["params"] = {"module": 2}
    g = _graph(reply, "Build a planetary gearbox, ratio 5:1, three planets")
    zs, zp, zr = (int(g.comp(i).v("teeth")) for i in ("sun_gear", "planet_gear", "ring_gear"))
    assert zr == zs + 2 * zp and (zs + zr) % 3 == 0
    assert abs(1 + zr / zs - 5) < 0.1


def test_planetary_gearbox_lays_out_on_the_first_attempt_with_round_roles_and_the_kinematic_chain() -> None:
    g = _graph()
    plan = _plan(g)
    tr = decide.trial(plan, BRIEF, "Planetary Gearbox")  # what the master rule reads: nothing sends it there now
    assert tr["solver"] == "graph" and not (tr["unsupported"] or tr["conflicts"] or tr["unreachable"]
                                            or tr["problems"]), tr
    skel, ifs = gc.to_icd(g, plan)
    items = {v["name"]: v for v in skel["items"].values()}
    name = {i: v["name"] for i, v in skel["items"].items()}
    roles = {n: v["role"] for n, v in items.items()}
    assert roles["Sun gear"] == roles["Planet gear"] == roles["Ring gear (internal)"] == "gear"
    assert roles["Input shaft"] == roles["Output shaft"] == roles["Planet pin"] == "shaft"
    assert roles["Planet carrier"] == "hub" and roles["Gearbox base"] == "block"
    parent = {n: name.get(v["parent"]) for n, v in items.items()}
    assert parent["Sun gear"] == "Input shaft"
    assert parent["Planet gear"] == "Planet pin"
    assert parent["Planet pin"] == "Planet carrier"
    assert parent["Planet carrier"] == "Output shaft"
    assert parent["Ring gear (internal)"] == "Gearbox base"
    assert parent["Input shaft"] == parent["Output shaft"] == parent["Gearbox cover"] == "Gearbox base"
    assert items["Ring gear (internal)"]["internal"] is True
    # three planets on the radius a = 60 about the coaxial input / output axis
    axis = items["Input shaft"]["copies"][0]
    assert items["Output shaft"]["copies"][0][0] == axis[0] and items["Output shaft"]["copies"][0][2] == axis[2]
    pl = items["Planet gear"]["copies"]
    assert len(pl) == 3
    for c in pl:
        assert abs(math.hypot(c[0] - axis[0], c[2] - axis[2]) - 60.0) < 0.02
    # the housing holds the ring with walls to spare
    ring_od = items["Ring gear (internal)"]["size"][0]
    hb = items["Gearbox base"]["size"]
    assert hb[0] > ring_od + 2 * icd.CAV and hb[2] > ring_od + 2 * icd.CAV
    # no interface problem, the design check agrees, no placement block
    assert icd.problems(skel, ifs) == []
    assert gc.check(g, skel, ifs) == []
    assert not [f for f in visual.quick_skeleton(skel, ifs)["findings"] if f.get("severity") == "block"]
    kinds = [f["kind"] for f in ifs]
    assert kinds.count("gear_mesh") == 6  # sun / planet and planet / ring for each of three planets
    internal = [f for f in ifs if f["kind"] == "gear_mesh" and f["data"].get("internal")]
    assert len(internal) == 3 and all(f["data"]["centre_distance"] == 60.0 for f in internal)
    # every bearing has its place: 2 + 2 in the end walls, one in each planet
    for nm, n in (("Input shaft bearing", 2), ("Output shaft bearing", 2), ("Planet bearing", 3)):
        st = next(s for s in skel["standard"] if s["name"] == nm)
        assert len(icd.seated(ifs, st["item"])["at"]) == n
    assert not [w for w in icd.warnings(skel, ifs) if "bearing" in w.lower()]


def test_negative_hole_spacing_is_said_in_plain_words() -> None:
    skel = {"items": {"b": {"name": "Plate", "role": "block", "shape": "box", "size": [300.0, 300.0, 20.0],
                            "copies": [[0.0, 0.0, -10.0]], "sub": "s"}}}
    ifs = [{"id": "IF-01", "kind": "face", "a": {"item": "b", "copy": 0, "name": "Plate"},
            "b": {"item": "x", "copy": 0, "name": "X", "standard": True},
            "data": {"plane_z": 0.0, "normal": [0, 0, 1], "flatness": 0.05, "position_tol": 0.1,
                     "passages": [{"at": [0.0, 0.0], "d_a": 210.0, "d_b": 210.0},
                                  {"at": [35.0, 0.0], "d_a": 5.0, "d_b": 5.0}]}}]
    txt = [p for p in icd.problems(skel, ifs) if "run into each other" in p]
    assert txt and "inside" in txt[0] and "-" not in txt[0].split("run into")[1].split(")")[0]
    assert not [p for p in icd.problems(skel, ifs) if "mm apart" in p and "-" in p]


def test_outgrowing_the_planned_envelope_warns_and_does_not_block() -> None:
    it = {"name": "Gearbox base", "role": "block", "shape": "box", "size": [257.0, 122.0, 219.0],
          "planned": [100.0, 100.0, 100.0], "copies": [[0.0, 0.0, 0.0]], "sub": "s"}
    skel = {"items": {"b": it}}
    assert not [p for p in icd.problems(skel, []) if "planned" in p]
    assert [w for w in icd.warnings(skel, []) if "planned" in w]


# ============================================================================ the revision at the interfaces gate
def _master_program(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """The founder's state: the plan on the master path, the draft ICD measured from it (the gears hung on the
    housing as blocks). The master measurement itself is not needed: the revision leaves it."""
    root = store.org_root(tmp_path, "org1")
    g = _graph()
    plan = _plan(g)
    doc = service.new_program("Planetary Gearbox", BRIEF, "org1", "u1", 3, 3000, "standard")
    service.set_plan(root, doc, plan, ENG)
    service.approve_plan(root, doc, None, ENG)
    assert doc["icd"]["status"] == "draft"
    sk = doc["skeleton"]
    base = sk["base"]
    for i, it in sk["items"].items():  # what the master model gave: every part a block, the gears on the housing
        it["role"], it["shape"] = "block", "box"
        if i != base:
            it["parent"] = base
    doc["plan"]["layout_path"] = {"path": "master", "reasons": [{"code": "unsupported", "text": "old solver"}],
                                  "words": "Laid out from a master model (new structure)"}
    doc["plan"]["master"] = {"ok": True, "measure": {"version": 1, "bodies": [], "contacts": []}}
    for _s, p in revision.plan_parts(doc["plan"]):  # the measured boxes the master wrote into the plan
        if p["name"] == "Planet carrier":
            p["envelope"] = [30.0, 160.0, 160.0]
    store.save(root, doc)
    return root, doc


@pytest.mark.parametrize("ops", [
    [{"op": "relayout"}],
    [{"op": "mount", "part": "Sun gear", "on": "Input shaft"}, {"op": "mount", "part": "Planet gear", "on": "Planet pin"},
     {"op": "mount", "part": "Planet pin", "on": "Planet carrier"},
     {"op": "mount", "part": "Ring gear (internal)", "on": "Gearbox base"},
     {"op": "size", "part": "Gearbox base", "envelope": [260, 300, 260]}],
])
def test_a_revision_at_the_draft_gate_leaves_the_master_layout_and_builds_the_chain(tmp_path: Path,
                                                                                      ops: list[dict[str, Any]]) -> None:
    _root, doc = _master_program(tmp_path)
    c = revision.candidate(doc, ops)
    assert c["ok"], c["why"]
    assert c["impact"]["changed"]
    assert c["plan"]["layout_path"]["path"] == "fast" and c["plan"]["layout_path"]["from_master"]
    sk = c["skeleton"]
    name = {i: v["name"] for i, v in sk["items"].items()}
    parent = {v["name"]: name.get(v["parent"]) for v in sk["items"].values()}
    assert parent["Planet gear"] == "Planet pin" and parent["Sun gear"] == "Input shaft"
    assert {v["name"]: v["role"] for v in sk["items"].values()}["Planet carrier"] == "hub"
    assert c["problems"] == []
    # the graph meshes are untouched by the mount changes (only what carries a part changes host)
    data = c["plan"]["graph"]["data"]
    meshes = {(x["host"], x["guest"]) for x in data["connections"] if x["kind"] == "gear_mesh"}
    assert meshes == {("sun_gear", "planet_gear"), ("planet_gear", "ring_gear")}
    if any(o["op"] == "size" for o in ops):  # the size asked for is kept (at least)
        hb = next(v for v in sk["items"].values() if v["name"] == "Gearbox base")["size"]
        assert hb == [260.0, 300.0, 260.0]
