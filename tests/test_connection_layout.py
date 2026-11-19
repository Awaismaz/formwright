"""Layout solved from the design graph's connections (architecture v2, step 2; ``graph/layout.py``).

Five golden mechanisms, every expected number a hand calculation from the placement rules (never a measurement):

1. Keyed gear on a stepped shaft (no bearings): the shoulder face is datum B (Y = 0); gear m2 x 30, face 20: Y -20 .. 0
   (centre -10); the seat runs SEAT_END 2 past the free face (Y -22); shaft 80 long (assumed): Y -22 .. 58, centre 18;
   key 6 x 6 x 18 (DIN 6885-1, Ø20), Y -19 .. -1, underside 10 - 3.5 = 6.5 off the axis.
2. 1:3 pair m2 20 / 60, Ø20 shafts, four 6204 (20 x 47 x 14), no housing: a = 2 (20 + 60) / 2 = 80; gears Y -10 .. 10;
   bearings BEARING_CLEAR 5 from the gear faces: Y 15 .. 29 and -29 .. -15; shafts SHAFT_END 10 beyond: length 78.
3. 3:1 reducer, split housing, four caps, shoulders inside (the live reply): the housing as the template sizes it,
   216 x 84 x 146 (walls 20, seats at the outer faces Y -42 / +42); input Ø20 seat, step 20 + 2 max(2.5, 0.1 x 20 + 1)
   = Ø26; output Ø30 (6206, 30 x 62 x 16), step 30 + 2 max(2.5, 4) = Ø38; each gear's +Y face (Y 10) on its shoulder,
   a 5 mm collar (Y 10 .. 15) in the cavity, the seat from the -Y bearing's inner face (-42 + 14 = -28, -42 + 16 = -26)
   to the shoulder, the +Y journal from the collar's end to the shaft end (input 84 + 16 + 20 = 120 long: Y -42 .. 78).
4. Belt drive (new): pulleys Ø60 / Ø120 x 20 on Ø20 shafts, two pillow blocks per shaft, 6204, on a base plate.
   C = D1 + D2 = 180 (stated rule); belt pitch length 2 C + pi (D1 + D2) / 2 + (D2 - D1)^2 / 4C = 360 + 282.74 + 5 =
   647.74. Bearings BEARING_CLEAR + SHOULDER = 9 from the pulley faces: Y 19 .. 33 and -33 .. -19; blocks 14 + 4 = 18
   wide, centred Y +-24; shafts Y -43 .. 43 (86). Axis height = max(120 / 2 + CAV 6, 47 / 2 + 11.75) = 66 (the big
   pulley clears the plate). Pillow block: wall max(8, 0.25 x 47) = 11.75, bolts M6 (fastener_for(2 x 47 = 94)),
   inset 2 x 6.6 = 13.2; L = 47 + 23.5 + 4 x 13.2 = 123.3 -> 123.5, H = 66 + 23.5 + 11.75 = 101.25 -> 101.5 (0.5 mm up),
   centre Z 50.75; its two M6 holes 61.75 - 13.2 = 48.55 either side. Axes at X 0 and 180, centred on the plate:
   X -90 / +90. Plate: (180 + 123.5) + 2 x 10 = 323.5 -> 324 long, 86 + 20 = 106 wide.
5. Motor drive (new): a motor (assumed envelope 120 x 180 x 120, shaft Ø14 x 30) on a bracket on a base plate,
   coupled to a Ø20 shaft in two pillow blocks (6204). The shaft carries nothing: its bearings are max(4 x 20,
   2 x 47) = 94 apart (Y -61 .. -47 and 47 .. 61). Coupling: engagement min(1.5 x 20, 30) = 30 a side, gap 2: 62 long,
   Ø50 (2.5 x 20); the coupled end 5 + 30 beyond the -Y block face: Y -96, the other end 61 + 10 = 71 (167 long). Height:
   the motor needs 120 / 2 + 10 (the least bracket) = 70 > 35.25 (pillow block) > 25 + 6 (coupling): the shaft axis is
   70 above the plate, the bracket 70 - 60 = 10 tall and 120 + 2 x 2 x 13.2 = 172.8 -> 173 wide (its own M6 bolts
   outside the motor's), the pillow blocks 70 + 23.5 + 11.75 = 105.25 -> 105.5 tall. The motor face 2 + 30 behind the
   shaft end. Everything centred on the plate (shift Y + 118.5): shaft centre Y 106, motor -99.5, coupling 21.5;
   plate: the bracket is the widest part, 173 + 2 x 10 = 193 long; Y -308 .. 71 is 379, + 20 = 399 wide.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aicad.graph import compile as gc
from aicad.graph import intent, layout
from aicad.graph.model import DesignGraph
from aicad.office import icd

G1 = Path(__file__).parent / "golden" / "design_graph"
G2 = Path(__file__).parent / "golden" / "connection_layout"


def _reply(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _graph(path: Path, mutate: Any = None) -> DesignGraph:
    d = _reply(path)
    if mutate:
        mutate(d["reply"])
    g, iss, qs = intent.compile_reply(d["reply"], d["name"], d["brief"])
    assert [i for i in iss if i["severity"] == "error"] == [] and qs == [], ([i["text"] for i in iss], qs)
    return g


def _solve(g: DesignGraph) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    plan = gc.to_plan(g, resolved=True)
    sk, ifs = gc.to_icd(g, plan)
    assert sk.get("solver") == "graph", sk["notes"]
    return plan, sk, ifs


def _it(sk: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {it["name"]: it for it in sk["items"].values()}


def _ifs(ifs: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [f for f in ifs if f["kind"] == kind]


# ----------------------------------------------------------------------------- 1. the keyed gear on a stepped shaft
def test_keyed_gear_on_a_stepped_shaft() -> None:
    g = _graph(G1 / "keyed_gear.json")
    plan, sk, ifs = _solve(g)
    it = _it(sk)
    assert sk["layout"] == "shaft_line" and sk["shaft_subassembly"] and icd.problems(sk, ifs) == []
    assert it["Stepped shaft"]["size"] == [26, 26, 80] and it["Stepped shaft"]["copies"] == [[0, 18, 0]]
    assert it["Spur gear"]["copies"] == [[0, -10, 0]]
    b, k = ifs[0]["data"], ifs[1]["data"]
    assert (b["d"], b["seat_z"], b["shoulder_z"], b["shoulder_d"], b["side"]) == (20, [-22, 0], 0, 26, 1)
    assert (k["b"], k["h"], k["length"], k["z"]) == (6, 6, 18, [-19, -1])
    key_item = next(s["item"] for s in sk["standard"] if s["name"] == "Parallel key")
    assert icd.seated(ifs, key_item)["at"] == [[6.5, -10, 0]]
    assert gc.check(g, sk, ifs) == [] and gc.limits(g, sk, ifs) == []
    assert gc.to_direct(g, plan)["shaft"]["summary"] == "shaft Ø20 / Ø26 × 80, 1 seat, 1 keyseat"


# ----------------------------------------------------------------------------- 2. the 1:3 pair, four 6204, no housing
def test_gear_pair_on_four_bearings() -> None:
    g = _graph(G1 / "gear_pair.json")
    plan, sk, ifs = _solve(g)
    it = _it(sk)
    assert sk["layout"] == "shaft_line" and icd.problems(sk, ifs) == [] and icd.warnings(sk, ifs) == []
    assert it["Pinion"]["copies"] == [[0, 0, 0]] and it["Gear"]["copies"] == [[80, 0, 0]]
    assert it["Input shaft"]["size"] == [20, 20, 78] and it["Output shaft"]["copies"] == [[80, 0, 0]]
    js = sorted(tuple(f["data"]["z"]) for f in _ifs(ifs, "bearing_journal"))
    assert js == [(-29, -15), (-29, -15), (15, 29), (15, 29)]
    m = _ifs(ifs, "gear_mesh")[0]["data"]
    assert (m["centre_distance"], m["axis_a"], m["axis_b"], m["plane_a"], m["plane_b"]) == (80, [0, 0], [80, 0], 0, 0)
    assert gc.check(g, sk, ifs) == []
    assert {k: v["path"] for k, v in gc.to_direct(g, plan).items()} == {
        "input_shaft": "direct", "output_shaft": "direct", "pinion": "direct", "gear": "direct"}


# ----------------------------------------------------------------------------- 3. the reducer: shoulders in a housing
def test_reducer_shoulders_inside_the_housing() -> None:
    d = _reply(G1 / "reducer.live.json")  # (the live reply asks a material question: compiled as it is)
    g, iss, _qs = intent.compile_reply(d["reply"], d["name"], d["brief"])
    assert [i for i in iss if i["severity"] == "error"] == []
    plan, sk, ifs = _solve(g)
    it = _it(sk)
    assert sk["layout"] == "gearbox" and icd.problems(sk, ifs) == []
    assert it["Housing base"]["size"] == [216, 84, 146] and it["Housing base"]["cavity"]["wall"] == 20
    xi, xo = it["Input shaft"]["copies"][0][0], it["Output shaft"]["copies"][0][0]
    assert (xi, xo) == (-60, 20) and it["Input shaft"]["copies"][0][2] == it["Output shaft"]["copies"][0][2] == -68
    assert it["Input shaft"]["size"] == [26, 26, 120] and it["Output shaft"]["size"] == [38, 38, 130]
    bores = {f["b"]["name"]: f["data"] for f in _ifs(ifs, "shaft_bore")}
    pin, out = bores["Input shaft"], bores["Output shaft"]
    assert (pin["d"], pin["shoulder_d"], pin["shoulder_z"], pin["seat_z"], pin["z"]) == (20, 26, 10, [-28, 10], [-10, 10])
    assert (out["d"], out["shoulder_d"], out["shoulder_z"], out["seat_z"]) == (30, 38, 10, [-26, 10])
    seats = {f["b"]["name"]: f["data"] for f in _ifs(ifs, "bearing_seat")}
    assert seats["Input shaft"]["journals"] == [[-42, -28], [15, 78]]
    assert seats["Output shaft"]["journals"] == [[-42, -26], [15, 88]]
    assert {n: s["designation"] for n, s in seats.items()} == {"Input shaft": "6204", "Output shaft": "6206"}
    caps = sorted((f["b"]["name"], f["data"]["cap"], f["data"]["normal"][1]) for f in _ifs(ifs, "hole_pattern")
                  if f["data"].get("cap"))
    assert caps == [("Input blind cap", "blind", -1), ("Input open cap", "open", 1), ("Output blind cap", "blind", -1),
                    ("Output open cap", "open", 1)]
    assert it["Input open cap"]["bore"] == 22  # the shaft leaves on its Ø20 journal, not the Ø26 step
    mesh = _ifs(ifs, "gear_mesh")[0]["data"]
    assert mesh["centre_distance"] == 80 and mesh["axis_b"][0] - mesh["axis_a"][0] == 80
    assert gc.check(g, sk, ifs) == [] and gc.limits(g, sk, ifs) == []  # "not laid out yet" is gone
    assert "Shoulders inside the housing" in sk["notes"][0] and "consistent by construction" in sk["notes"][0]
    d_ = gc.to_direct(g, plan)
    assert d_["input_shaft"]["summary"] == "shaft Ø20 / Ø26 / Ø20 × 120, 2 bearing journals, 1 seat, 1 keyseat"
    assert d_["output_shaft"]["summary"] == "shaft Ø30 / Ø38 / Ø30 × 130, 2 bearing journals, 1 seat, 1 keyseat"


@pytest.mark.parametrize("case", ["keyed_gear", "gear_pair", "reducer"])
def test_parity_with_the_template_on_the_golden_cases(case: str) -> None:
    """The recorded golden graphs (no shoulder in a housing): the solver gives exactly the template's layout, item by
    item and number by number."""
    g = _graph(G1 / f"{case}.json")
    plan = gc.to_plan(g, resolved=True)
    t_sk, t_if = gc.to_icd(g, plan, template=True)
    s_sk, s_if = gc.to_icd(g, plan)
    for i, a in t_sk["items"].items():
        b = s_sk["items"][i]
        assert {k: a.get(k) for k in ("size", "copies", "ax", "d", "bore", "phase", "bearing", "cavity")} == \
            {k: b.get(k) for k in ("size", "copies", "ax", "d", "bore", "phase", "bearing", "cavity")}, a["name"]
    assert [(f["id"], f["kind"], f["a"], f["b"]) for f in t_if] == [(f["id"], f["kind"], f["a"], f["b"]) for f in s_if]
    for a, b in zip(t_if, s_if, strict=True):
        assert a["data"] == b["data"], a["id"]


# ----------------------------------------------------------------------------- 4. the belt drive on pillow blocks
def test_belt_drive_on_pillow_blocks() -> None:
    g = _graph(G2 / "pulley_pair.json")
    plan, sk, ifs = _solve(g)
    it = _it(sk)
    assert sk["layout"] == "block" and icd.problems(sk, ifs) == [] and icd.warnings(sk, ifs) == []
    assert it["Drive shaft"]["copies"] == [[-90, 0, 66]] and it["Driven shaft"]["copies"] == [[90, 0, 66]]
    assert it["Drive shaft"]["size"] == [20, 20, 86] and it["Driven pulley"]["copies"] == [[90, 0, 66]]
    belt = _ifs(ifs, "belt_drive")[0]["data"]
    assert (belt["centre_distance"], belt["belt_length"], belt["plane_a"], belt["plane_b"]) == (180, 647.74, 0, 0)
    pb = it["Drive pillow block"]
    assert pb["size"] == [123.5, 18, 101.5] and pb["copies"] == [[-90, -24, 50.75], [-90, 24, 50.75]]
    assert it["Base plate"]["size"] == [324, 106, 16] and it["Base plate"]["copies"] == [[0, 0, -8]]
    seats = sorted((f["a"]["name"], tuple(f["data"]["seats"][0]["z"])) for f in _ifs(ifs, "bearing_seat"))
    assert seats == [("Drive pillow block #1", (-33, -19)), ("Drive pillow block #2", (19, 33)),
                     ("Driven pillow block #1", (-33, -19)), ("Driven pillow block #2", (19, 33))]
    holes = next(f for f in _ifs(ifs, "hole_pattern") if f["b"]["name"] == "Drive pillow block #1")["data"]
    assert (holes["fastener"], holes["positions"], holes["plane_z"]) == ("M6", [[-138.55, -24], [-41.45, -24]], 0)
    keys = _ifs(ifs, "key")
    assert len(keys) == 2 and all(k["data"]["key_item"] for k in keys)  # the implied keys sit in their keyseats
    brg = next(s["item"] for s in sk["standard"] if s["name"] == "Drive shaft bearing")
    assert icd.seated(ifs, brg)["at"] == [[-90, -33, 66], [-90, 19, 66]]
    assert gc.check(g, sk, ifs) == []
    assert {k for k, v in gc.to_direct(g, plan).items() if v["path"] == "direct"} == {"drive_shaft", "driven_shaft"}


# ----------------------------------------------------------------------------- 5. a motor coupled to a shaft unit
def test_motor_on_a_bracket_coupled_to_a_shaft_in_pillow_blocks() -> None:
    g = _graph(G2 / "motor_drive.json")
    _plan, sk, ifs = _solve(g)
    it = _it(sk)
    assert sk["layout"] == "block" and icd.problems(sk, ifs) == []
    assert it["Drive shaft"]["copies"] == [[0, 106, 70]] and it["Drive shaft"]["size"] == [20, 20, 167]
    assert it["Motor"]["copies"] == [[0, -99.5, 70]] and it["Motor"]["size"] == [120, 180, 120]
    assert it["Motor bracket"]["size"] == [173, 180, 10] and it["Motor bracket"]["copies"] == [[0, -99.5, 5]]
    assert it["Coupling"]["size"] == [50, 50, 62] and it["Coupling"]["copies"] == [[0, 21.5, 70]]
    assert it["Pillow block"]["size"] == [123.5, 18, 105.5]
    assert it["Base plate"]["size"] == [193, 399, 16]
    bores = {f["b"]["name"]: f["data"] for f in _ifs(ifs, "shaft_bore") if f["a"]["name"] == "Coupling"}
    assert (bores["Drive shaft"]["d"], bores["Drive shaft"]["z"]) == (20, [22.5, 52.5])
    assert (bores["Motor"]["d"], bores["Motor"]["z"]) == (14, [-9.5, 20.5])  # the motor shaft, 2 mm gap to the shaft
    seats = sorted(tuple(f["data"]["seats"][0]["z"]) for f in _ifs(ifs, "bearing_seat"))
    assert seats == [(57.5, 71.5), (165.5, 179.5)]
    plate_bracket = next(f for f in _ifs(ifs, "hole_pattern") if f["b"]["name"] == "Motor bracket")["data"]
    motor_bolts = next(f for f in _ifs(ifs, "hole_pattern") if f["b"]["name"] == "Motor")["data"]
    assert max(abs(p[0]) for p in plate_bracket["positions"]) == 73.3  # the bracket's bolts outside the motor's 60
    assert max(abs(p[0]) for p in motor_bolts["positions"]) == 46.8 and motor_bolts["plane_z"] == 10
    assert any("assumed" in n for n in sk["notes"]) and "70 mm above" in sk["notes"][0]


# ----------------------------------------------------------------------------- conflicts: precise, never silent
def _pair(extra_c: list[dict[str, Any]], extra_x: list[dict[str, Any]]) -> DesignGraph:
    reply = {"components": [
        {"id": "s1", "kind": "shaft", "name": "Input shaft", "params": {"d": 20, "role": "input"}},
        {"id": "s2", "kind": "shaft", "name": "Output shaft", "params": {"d": 20, "role": "output"}},
        {"id": "g1", "kind": "spur_gear", "name": "Pinion", "params": {"module": 2, "teeth": 20}},
        {"id": "g2", "kind": "spur_gear", "name": "Gear", "params": {"module": 2, "teeth": 60}},
        {"id": "b", "kind": "bearing", "name": "Bearing 6204", "qty": 4, "params": {"designation": 6204}}] + extra_c,
        "connections": [{"kind": "hub_fit", "host": "s1", "guest": "g1"}, {"kind": "hub_fit", "host": "s2", "guest": "g2"},
                        {"kind": "gear_mesh", "host": "g1", "guest": "g2"},
                        {"kind": "bearing_journal", "host": "s1", "guest": "b", "params": {"count": 2}},
                        {"kind": "bearing_journal", "host": "s2", "guest": "b", "params": {"count": 2}}] + extra_x}
    g, _iss, _qs = intent.compile_reply(reply, "Pair", "A spur pair, no housing.")
    return g


PULLEYS = [{"id": "p1", "kind": "pulley", "name": "Small pulley", "params": {"od": 40, "width": 15}},
           {"id": "p2", "kind": "pulley", "name": "Large pulley", "params": {"od": 60, "width": 15}}]
BELTED = [{"kind": "hub_fit", "host": "s1", "guest": "p1"}, {"kind": "hub_fit", "host": "s2", "guest": "p2"}]


def _conflicts(g: DesignGraph) -> list[dict[str, Any]]:
    _plan, sk, ifs = _solve(g)
    return [i for i in icd.issues(sk, ifs) if i["code"] == "layout_conflict"]


def test_a_closed_loop_that_disagrees_is_a_conflict_naming_the_parts() -> None:
    """Two shafts that mesh (a = 80) and are belted at a stated C = 200: over-constrained."""
    g = _pair(PULLEYS, BELTED + [{"kind": "belt_drive", "host": "p1", "guest": "p2", "params": {"centre_distance": 200}}])
    cs = _conflicts(g)
    assert len(cs) == 1 and cs[0]["severity"] == "error"
    c = cs[0]
    assert "C = 200" in c["text"] and "a = 80" in c["text"] and "over-constrained" in c["text"]
    assert {"Small pulley", "Large pulley", "Pinion", "Gear", "Input shaft", "Output shaft"} <= set(c["parts"])
    belt = next(x.id for x in g.connections if x.kind == "belt_drive")
    mesh = next(x.id for x in g.connections if x.kind == "gear_mesh")
    assert c["connections"] == [belt, mesh] and c["items"]


def test_a_closed_loop_that_agrees_is_solved_and_said() -> None:
    g = _pair(PULLEYS, BELTED + [{"kind": "belt_drive", "host": "p1", "guest": "p2", "params": {"centre_distance": 80}}])
    _plan, sk, ifs = _solve(g)
    assert icd.problems(sk, ifs) == [] and "Closed loops checked" in sk["notes"][0]
    belt = _ifs(ifs, "belt_drive")[0]["data"]
    assert belt["axis_b"][0] - belt["axis_a"][0] == 80 and belt["plane_a"] == belt["plane_b"] == 17.5  # 10 + 15 / 2


def test_a_hub_on_two_shafts_and_an_unconnected_part_are_conflicts() -> None:
    g = _pair([], [{"kind": "hub_fit", "host": "s1", "guest": "g2"}])
    (c,) = _conflicts(g)
    assert c["text"].startswith("Layout conflict: Gear is fitted on two shafts") and set(c["parts"]) == {
        "Gear", "Output shaft", "Input shaft"}
    g = _pair([{"id": "sp", "kind": "spacer", "name": "Spacer", "params": {"od": 30, "length": 5}}], [])
    _plan, sk, ifs = _solve(g)
    codes = {i["code"] for i in icd.issues(sk, ifs) if i["severity"] == "error"}
    assert codes == {"layout_conflict", "no_interface"}  # drawn beside the program and said, never silently


def test_two_stated_heights_that_disagree_are_a_conflict() -> None:
    def mutate(r: dict[str, Any]) -> None:
        for c in r["components"]:
            if c["id"] == "bracket":
                c["params"] = {"H": 20}      # motor axis at 20 + 120 / 2 = 80
            if c["id"] == "pb":
                c["params"] = {"centre_height": 70}

    (c,) = _conflicts(_graph(G2 / "motor_drive.json", mutate))
    assert "70 mm" in c["text"] and "80 mm" in c["text"] and {"Pillow block", "Motor bracket", "Motor"} <= set(c["parts"])

    def one(r: dict[str, Any]) -> None:  # one stated height: the other path adapts to it
        for c in r["components"]:
            if c["id"] == "bracket":
                c["params"] = {"H": 30}

    _plan, sk, ifs = _solve(_graph(G2 / "motor_drive.json", one))
    assert icd.problems(sk, ifs) == [] and _it(sk)["Drive shaft"]["copies"][0][2] == 90  # 30 + 60
    assert _it(sk)["Pillow block"]["size"][2] == 125.5  # 90 + 23.5 + 11.75 = 125.25 -> 125.5


# ----------------------------------------------------------------------------- fallback, stability, the office hook
def test_graphs_the_solver_does_not_lay_out_yet_use_the_template_and_say_so() -> None:
    reply = {"components": [{"id": "p", "kind": "plate", "name": "Base plate", "params": {"L": 200, "W": 100, "T": 10}},
                            {"id": "b", "kind": "bracket", "name": "Bracket", "params": {"L": 60, "W": 40, "H": 30}},
                            {"id": "f", "kind": "fastener", "name": "Bolt", "qty": 4, "params": {"size": 6}}],
             "connections": [{"kind": "bolted_joint", "host": "p", "guest": "b", "via": ["f"]}]}
    g, _iss, _qs = intent.compile_reply(reply, "Bracket", "A bracket bolted to a plate")
    sk, ifs = gc.to_icd(g)
    assert "solver" not in sk and sk["layout"] == "block" and icd.problems(sk, ifs) == []
    assert any(n.startswith("Laid out with the standard layout") for n in sk["notes"])
    with pytest.raises(layout.Unsupported):
        layout.build(g, gc.plan_parts(gc.to_plan(g, resolved=True)), g.brief)


@pytest.mark.parametrize("path", [G1 / "keyed_gear.json", G1 / "gear_pair.json", G1 / "reducer.live.json",
                                  G2 / "pulley_pair.json", G2 / "motor_drive.json"])
def test_freeze_and_rebuild_gives_the_same_layout(path: Path) -> None:
    """At ICD approval the envelopes are frozen (``icd.freeze``); every rebuild (an edit, a change request) must
    then lay the program out exactly as before."""
    d = _reply(path)
    g, _iss, _qs = intent.compile_reply(d["reply"], d["name"], d["brief"])
    plan = gc.to_plan(g, resolved=True)
    parts = gc.plan_parts(plan)
    sk, ifs = gc.to_icd(g, plan)
    ov = icd.freeze(sk, ifs, gc.overrides_for(plan, parts) or {})
    sk2, ifs2 = layout.build(g, parts, g.brief, ov, resolved=True)
    for i, it in sk["items"].items():
        assert (it["size"], it["copies"]) == (sk2["items"][i]["size"], sk2["items"][i]["copies"]), it["name"]
    assert [f["data"] for f in ifs] == [f["data"] for f in ifs2]


def test_the_office_lays_graph_programs_out_from_their_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    from aicad.graph import office as goffice
    from aicad.office import interfaces

    d = _reply(G2 / "pulley_pair.json")
    out = goffice.finish(goffice.OfficePlan(None), *intent.compile_reply(d["reply"], d["name"], d["brief"])[:2])
    assert out.plan is not None and out.plan["graph"]["check"] == [] and out.plan["graph"]["limits"] == []
    items = [{"id": p["id"], "kind": "part", "name": p["name"], "family": p["family"], "qty": p["qty"],
              "description": p["description"], "parent_id": p["sub"]} for p in gc.plan_parts(out.plan)]
    doc = {"plan": out.plan, "brief": d["brief"], "items": items, "tickets": []}
    sk, _ifs2 = interfaces._rebuild(doc, {"items": {}, "interfaces": {}})
    assert sk.get("solver") == "graph" and _it(sk)["Driven shaft"]["copies"] == [[90, 0, 66]]
    assert "_layout_fallback" not in doc
    monkeypatch.setenv(layout.ENV, "0")  # the switch: graph plans back on the template
    sk, _ifs = interfaces._rebuild(doc, {"items": {}, "interfaces": {}})
    assert "solver" not in sk
    monkeypatch.delenv(layout.ENV)
    doc2 = {**doc, "plan": {k: v for k, v in out.plan.items() if k != "graph"}}  # a plan without a graph: template
    assert interfaces._graph_layout(doc2, None) is None


def test_pillow_blocks_carry_the_bearings_so_no_housing_question() -> None:
    d = _reply(G2 / "pulley_pair.json")
    _g, _iss, qs = intent.compile_reply(d["reply"], d["name"], d["brief"])
    assert [q.id for q in qs] == []


def test_spacer_between_two_faces_and_circlips_in_their_grooves() -> None:
    """A spacer 8 long after the pinion (Y 10 .. 18): the +Y bearing bears on it (Y 18 .. 32, no BEARING_CLEAR) and the
    spacer seats on the pinion's face; two DIN 471 rings for Ø20 (s 1.2, m 1.3) hold the gear at both faces: rings
    Y -11.2 .. -10 and 10 .. 11.2, grooves -11.3 .. -10 and 10 .. 11.3."""
    g = _pair([{"id": "sp", "kind": "spacer", "name": "Spacer", "params": {"od": 28, "length": 8}},
               {"id": "rr", "kind": "retaining_ring", "name": "Circlip", "qty": 2}],
              [{"kind": "hub_fit", "host": "s1", "guest": "sp"},
               {"kind": "ring_retained", "host": "s2", "guest": "g2", "via": ["rr"]}])
    _plan, sk, ifs = _solve(g)
    assert icd.problems(sk, ifs) == []
    assert _it(sk)["Spacer"]["copies"] == [[0, 14, 0]]
    js = {(f["a"]["name"], f["data"]["side"]): f["data"]["z"] for f in _ifs(ifs, "bearing_journal")}
    assert js[("Input shaft", 1)] == [18, 32] and js[("Output shaft", 1)] == [15, 29]
    face = _ifs(ifs, "face")[0]
    assert (face["a"]["name"], face["b"]["name"], face["data"]["plane_z"]) == ("Pinion", "Spacer", 10)
    rings = sorted((f["data"]["z"], f["data"]["groove_z"]) for f in _ifs(ifs, "retaining_ring"))
    assert rings == [([-11.2, -10], [-11.3, -10]), ([10, 11.2], [10, 11.3])]
    ring = next(s["item"] for s in sk["standard"] if s["name"] == "Circlip")
    assert len(icd.seated(ifs, ring)["at"]) == 2
