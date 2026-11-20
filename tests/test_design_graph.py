"""The design graph (architecture v2, step 1): schema, registries, standards sizing, validation and repair, the
compilers to the Design Office plan / ICD / direct builds / Fitz trains, the reverse adapter, the intent compiler
(stub provider with recorded replies) and the office flag, on the three golden cases.

Every expected number is a hand calculation (never a measurement of what was built):

* DIN 6885-1, shaft over 17 up to 22: key 6 x 6, t1 3.5, t2 2.8; over 22 up to 30: 8 x 7, t1 4.0, t2 3.3.
  Key length for a hub B = 20 wide: floor(max(b + 2, B - 2)) = floor(max(8, 18)) = 18.
* ISO 15: 6204 = 20 x 47 x 14, 6206 = 30 x 62 x 16 (the largest 62xx bore not above the journal).
* DIN 471 for d1 = 20: d2 19.0, m 1.3, n 1.5, groove depth (20 - 19) / 2 = 0.5 (table typed from a reprint, verify).
* Spur gear m2: pitch Ø m z, tip Ø m (z + 2), root Ø m (z - 2.5); z30 -> 60 / 64 / 55; face width 10 m = 20.
* Centre distance a = m (z1 + z2) / 2 = 2 (20 + 60) / 2 = 80; 3:1 from the ratio: z1 = 20, z2 = round(3 x 20) = 60.
* Output shaft at 3:1 from an Ø20 input: 20 x 3^(1/3) = 28.84 -> the next 62xx bore, Ø30 (6206).
* Shoulder behind an Ø20 seat: 20 + 2 max(2.5, 0.1 x 20 + 1) = 26.

Golden case 1 (founder, 2026-11-19): "Build a Spur Gear mounted on stepped Shaft and locked with a key": shaft Ø20 seat
/ Ø26 step x 80 (assumed), gear m2 x 30 (assumed) on the seat against the shoulder: the shoulder face is datum B
(Y = 0), the gear Y -20 .. 0 (centre -10), the seat runs 2 mm past the free face (Y -22), the shaft Y -22 .. 58
(centre 18); the key 18 long centred on the hub (Y -19 .. -1), its underside on the keyseat floor 10 - 3.5 = 6.5
from the axis: (6.5, -10, 0).
Golden case 2: the 1:3 pair m2 20 / 60 on two Ø20 shafts, four 6204, no housing: axes 80 apart on Z = 0, gears
centred on Y = 0 (face 20: Y -10 .. 10), bearings BEARING_CLEAR 5 from the gear faces: Y 15 .. 29 and -29 .. -15,
shafts SHAFT_END 10 beyond: Y -39 .. 39, length 78.
Golden case 3: "Build a Single stage 3:1 reducer with Spur Gears": a split housing, m2 20 / 60 at a = 80, input Ø20
on 6204, output Ø30 on 6206, keys 6 x 6 x 18 and 8 x 7 x 18, four caps (open on +Y, blind on -Y), every interface
consistent with the graph.
No live AI (stub provider with recorded replies, simulated office agents).
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from pathlib import Path
from typing import Any

import pytest
from test_office_orchestrator import _topup, _wait, office  # noqa: F401  (fixture)

from aicad import llm
from aicad.graph import adapt, intent, questions, registry, resolve, standards, validate
from aicad.graph import compile as gc
from aicad.graph import office as goffice
from aicad.graph.model import Component, Connection, DesignGraph, Param
from aicad.llm.stub import StubProvider
from aicad.office import icd

GOLDEN = Path(__file__).parent / "golden" / "design_graph"


def _case(name: str) -> dict[str, Any]:
    return json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))


def _graph(name: str) -> DesignGraph:
    d = _case(name)
    g, iss, qs = intent.compile_reply(d["reply"], d["name"], d["brief"])
    assert [i for i in iss if i["severity"] == "error"] == [] and qs == []
    return g


def _by(g: DesignGraph) -> dict[str, Component]:
    return {c.id: c for c in g.components}


def _items(sk: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {it["name"]: it for it in sk["items"].values()}


# ----------------------------------------------------------------------------- schema and registries
def test_schema_round_trip_and_version() -> None:
    g = _graph("keyed_gear")
    d = g.dump()
    assert d["schema"] == "fw-design-graph" and d["version"] == 1
    assert DesignGraph.load(json.loads(json.dumps(d))).dump() == d
    with pytest.raises(ValueError):
        DesignGraph.load({**d, "version": 99})
    with pytest.raises(ValueError):
        DesignGraph.load({**d, "schema": "something-else"})


def test_registries_are_consistent() -> None:
    for kt in registry.CONNECTIONS.values():
        assert set(kt.hosts) <= set(registry.COMPONENTS) and set(kt.guests) <= set(registry.COMPONENTS)
        assert set(kt.via) <= set(registry.COMPONENTS)
        assert set(kt.icd) <= set(icd.KIND_LABEL), kt.kind
        assert kt.placement, kt.kind
    # semantics: the host carries, the features each side gets
    kh = registry.CONNECTIONS["keyed_hub"]
    assert kh.hosts == ("shaft",) and "spur_gear" in kh.guests and kh.via == ("key",) and kh.via_required
    assert any("keyseat" in f for f in kh.host_features) and any("keyway" in f for f in kh.guest_features)
    assert registry.CONNECTIONS["bearing_seat"].hosts == ("housing", "pillow_block", "bracket", "plate")  # step 2
    assert any("groove" in f for f in registry.CONNECTIONS["ring_retained"].host_features)
    assert any("hole" in f for f in registry.CONNECTIONS["bolted_joint"].guest_features)
    assert "m (z1 + z2) / 2" in registry.CONNECTIONS["gear_mesh"].placement
    ref = registry.prompt_reference()
    assert all(k in ref for k in registry.COMPONENTS) and all(k in ref for k in registry.CONNECTIONS)
    assert registry.kind_from_name("Shaft support housing") == "housing"
    assert registry.kind_from_name("Pinion key") == "key" and registry.kind_from_name("Gear shaft") == "shaft"


# ----------------------------------------------------------------------------- standards (hand values)
def test_sizing_from_standards() -> None:
    assert standards.key_for_shaft(20) == {"b": 6, "h": 6, "t1": 3.5, "t2": 2.8}
    assert standards.key_for_shaft(30) == {"b": 8, "h": 7, "t1": 4.0, "t2": 3.3}
    with pytest.raises(ValueError):
        standards.key_for_shaft(70)
    assert standards.key_length(6, 20) == 18 and standards.key_length(6, 6) == 6  # capped at the hub width
    assert standards.bearing_for_journal(20) == 6204 and standards.bearing_dims(6204) == {"d": 20, "D": 47, "B": 14}
    assert standards.bearing_for_journal(30) == 6206 and standards.bearing_dims(6206) == {"d": 30, "D": 62, "B": 16}
    assert standards.bearing_for_journal(20, "60") == 6004
    assert standards.bearing_for_journal(20, designation=6204) == 6204
    assert standards.circlip_groove(20) == {"s": 1.2, "b": 2.6, "d2": 19.0, "m": 1.3, "n": 1.5, "t": 0.5}
    assert standards.centre_distance(2, 20, 60) == 80
    assert standards.teeth_for_ratio(3) == (20, 60)
    gg = standards.gear_geometry(2, 30)
    assert (gg["pitch_d"], gg["tip_d"], gg["root_d"], gg["face_width"]) == (60, 64, 55, 20)
    assert gg["max_bore"] == 2 * (30 - 2.5 - 2)  # root radius minus a rim of one module, doubled = 51
    assert standards.output_shaft(20, 3) == 30 and 20 * 3 ** (1 / 3) == pytest.approx(28.845, abs=1e-3)
    assert standards.shoulder_for(20) == 26
    assert standards.bore_fits_gear(2, 20, 20, 2.8) and not standards.bore_fits_gear(2, 12, 20)


# ----------------------------------------------------------------------------- validation and repair
def _g(*comps: Component, conns: tuple[Connection, ...] = (), brief: str = "") -> DesignGraph:
    return DesignGraph(brief=brief, components=list(comps), connections=list(conns),
                       constraints=intent.constraints_of(brief))


def _c(cid: str, kind: str, **params: Any) -> Component:
    return Component(id=cid, kind=kind, name=cid.replace("_", " ").capitalize(),
                     params={k: Param(value=v, source="brief") for k, v in params.items()})


def test_validation_codes() -> None:
    sh, gr = _c("shaft", "shaft", d=20), _c("gear", "spur_gear", module=2, teeth=30, bore=25)
    g = _g(sh, gr, _c("wheel", "spur_gear", module=3, teeth=40), _c("mystery", "flux_capacitor"),
           conns=(Connection(id="c1", kind="keyed_hub", host="shaft", guest="gear"),
                  Connection(id="c2", kind="gear_mesh", host="gear", guest="wheel"),
                  Connection(id="c3", kind="hub_fit", host="gear", guest="shaft"),
                  Connection(id="c4", kind="bolted_joint", host="shaft", guest="ghost"),
                  Connection(id="c5", kind="teleport", host="shaft", guest="gear")))
    codes = {i["code"] for i in validate.issues(g)}
    assert {"conflict", "unknown_kind", "wrong_side", "dangling", "unknown_connection"} <= codes
    texts = " | ".join(i["text"] for i in validate.issues(g))
    assert "bored Ø25 but its seat on Shaft is Ø20" in texts and "meshing gears share their module" in texts
    # a gear too small for its bore; a key outside the table; a shoulder smaller than its seat
    small = _g(_c("shaft", "shaft", d=20, shoulder_d=18), _c("gear", "spur_gear", module=1, teeth=20, bore=20),
               conns=(Connection(id="c1", kind="hub_fit", host="shaft", guest="gear"),
                      Connection(id="c2", kind="shoulder_stop", host="shaft", guest="gear")))
    assert {"bore_too_large", "conflict"} <= {i["code"] for i in validate.issues(small)}
    big = _g(_c("shaft", "shaft", d=70), _c("gear", "spur_gear", module=4, teeth=60, bore=70),
             conns=(Connection(id="c1", kind="keyed_hub", host="shaft", guest="gear"),))
    assert "outside_table" in {i["code"] for i in validate.issues(big)}
    # out of range, required, unconnected (a warning), unknown parameter (a warning)
    odd = _g(_c("gear", "spur_gear", module=50, colour="red"), _c("plate", "plate"))
    got = {(i["code"], i["severity"]) for i in validate.issues(odd)}
    assert {("out_of_range", "error"), ("missing_param", "error"), ("unconnected", "warning"),
            ("unknown_param", "warning")} <= got


def test_exclusions_are_hard_constraints() -> None:
    """The founder's failing run: "No extra items. Just a spur gear, a shaft and a key", and a reply that adds a
    support housing and bearings anyway: code drops them whatever the model wrote, and says so."""
    brief = ("Build a Spur Gear, mounted on shaft and locked with a key. No extra items. Just a spur gear, a shaft "
             "and a key")
    reply = {"components": [
        {"id": "housing", "kind": "housing", "name": "Shaft support housing"},
        {"id": "shaft", "kind": "shaft", "name": "Shaft"}, {"id": "gear", "kind": "spur_gear", "name": "Spur gear"},
        {"id": "key", "kind": "key", "name": "Key"}, {"id": "brg", "kind": "bearing", "name": "Bearing", "qty": 2}],
        "connections": [{"kind": "keyed_hub", "host": "shaft", "guest": "gear", "via": ["key"]},
                        {"kind": "bearing_journal", "host": "shaft", "guest": "brg"},
                        {"kind": "bearing_seat", "host": "housing", "guest": "brg"}]}
    g, iss, qs = intent.compile_reply(reply, "Test 5", brief)
    assert sorted(c.kind for c in g.components) == ["key", "shaft", "spur_gear"]
    assert [x.kind for x in g.connections] == ["keyed_hub"] and not iss and not qs
    assert g.constraints.exclusive and g.constraints.named == ["gear", "key", "shaft"]
    assert "Shaft support housing and Bearing" in g.notes[0]
    # "no housing" excludes a housing; keys excluded turn a keyed hub into a plain fit (said so)
    g2 = resolve.resolve(validate.repair(_g(
        _c("shaft", "shaft", d=20), _c("gear", "spur_gear", module=2, teeth=30),
        conns=(Connection(id="c1", kind="keyed_hub", host="shaft", guest="gear"),), brief="A gear on a shaft, no key.")))
    assert [x.kind for x in g2.connections] == ["hub_fit"] and not g2.of_kind("key") and "plain fit" in g2.notes[0]


def test_resolve_adds_implied_parts_and_sizes() -> None:
    g = resolve.resolve(_g(_c("shaft", "shaft"), _c("gear", "spur_gear"),
                           conns=(Connection(id="c1", kind="keyed_hub", host="shaft", guest="gear"),
                                  Connection(id="c2", kind="ring_retained", host="shaft", guest="gear"))))
    by = _by(g)
    assert by["parallel_key"].implied and by["retaining_ring"].implied
    assert (by["shaft"].v("d"), by["shaft"].params["d"].source) == (20, "assumed")
    assert by["gear"].v("bore") == 20 and by["gear"].params["bore"].source == "rule"
    assert (by["parallel_key"].v("b"), by["parallel_key"].v("length")) == (6, 18)
    assert (by["retaining_ring"].v("d2"), by["retaining_ring"].v("m")) == (19.0, 1.3)
    assert by["parallel_key"].params["b"].note == "DIN 6885-1 for Ø20"


# ----------------------------------------------------------------------------- golden case 1: the keyed gear
def test_golden_keyed_gear_graph_plan_icd_direct() -> None:
    g = _graph("keyed_gear")
    by = _by(g)
    sh, gr, key = by["shaft"], by["gear"], by["key"]
    assert (sh.v("d"), sh.v("shoulder_d"), sh.v("length"), sh.v("stepped")) == (20, 26, 80, True)
    assert (gr.v("module"), gr.v("teeth"), gr.v("face_width"), gr.v("bore")) == (2, 30, 20, 20)
    assert (key.v("b"), key.v("h"), key.v("t1"), key.v("t2"), key.v("length")) == (6, 6, 3.5, 2.8, 18)
    plan = gc.to_plan(g, resolved=True)
    assert [s["name"] for s in plan["subassemblies"]] == ["Keyed gear"]
    assert [p["name"] for p in plan["subassemblies"][0]["parts"]] == ["Stepped shaft", "Spur gear", "Parallel key"]
    sk, ifs = gc.to_icd(g, plan)
    it = _items(sk)
    assert sk["layout"] == "shaft_line" and sk["shaft_subassembly"] and icd.problems(sk, ifs) == []
    assert it["Stepped shaft"]["size"] == [26, 26, 80] and it["Stepped shaft"]["copies"] == [[0, 18, 0]]
    assert it["Spur gear"]["size"] == [64, 64, 20] and it["Spur gear"]["copies"] == [[0, -10, 0]]
    b, k = ifs[0]["data"], ifs[1]["data"]
    assert (b["d"], b["seat_z"], b["shoulder_z"], b["shoulder_d"]) == (20, [-22, 0], 0, 26)
    assert (k["b"], k["h"], k["length"], k["z"]) == (6, 6, 18, [-19, -1])
    key_item = next(s["item"] for s in sk["standard"] if s["name"] == "Parallel key")
    assert icd.seated(ifs, key_item)["at"] == [[6.5, -10, 0]]
    assert gc.check(g, sk, ifs) == []
    d = gc.to_direct(g, plan)
    assert (d["shaft"]["path"], d["shaft"]["summary"]) == ("direct", "shaft Ø20 / Ø26 × 80, 1 seat, 1 keyseat")
    assert (d["gear"]["path"], d["gear"]["summary"]) == ("direct", "spur gear m2 × 30 teeth, face 20, bore Ø20 with a keyway")
    items, skipped = gc.to_fitz_items(g)
    assert [i["code"] for i in items] == ["spur_gear"] and items[0]["params"]["KEY_B"] == 6
    assert any("stepped shaft" in s for s in skipped)


# ----------------------------------------------------------------------------- golden case 2: the 1:3 pair
def test_golden_gear_pair_graph_plan_icd_direct_fitz(tmp_path: Path) -> None:
    from aicad.assembly import trains

    g = _graph("gear_pair")
    by = _by(g)
    mesh = next(x for x in g.connections if x.kind == "gear_mesh")
    assert (mesh.v("centre_distance"), mesh.v("ratio")) == (80, 3)
    assert by["bearing"].v("designation") == 6204 and by["bearing"].params["designation"].source == "brief"
    assert by["input_shaft"].params["d"].source == "brief" and "housing" in g.constraints.excluded
    plan = gc.to_plan(g, resolved=True)
    sk, ifs = gc.to_icd(g, plan)
    it = _items(sk)
    assert sk["layout"] == "shaft_line" and icd.problems(sk, ifs) == [] and icd.warnings(sk, ifs) == []
    assert it["Pinion"]["copies"] == [[0, 0, 0]] and it["Gear"]["copies"] == [[80, 0, 0]]
    assert it["Input shaft"]["size"] == [20, 20, 78] and it["Output shaft"]["copies"] == [[80, 0, 0]]
    js = sorted(tuple(f["data"]["z"]) for f in ifs if f["kind"] == "bearing_journal")
    assert js == [(-29, -15), (-29, -15), (15, 29), (15, 29)]
    assert all(f["data"]["designation"] == "6204" for f in ifs if f["kind"] == "bearing_journal")
    assert gc.check(g, sk, ifs) == []
    d = gc.to_direct(g, plan)
    assert {k: v["path"] for k, v in d.items()} == {"input_shaft": "direct", "output_shaft": "direct",
                                                    "pinion": "direct", "gear": "direct"}
    assert d["input_shaft"]["summary"] == "shaft Ø20 × 78, 2 bearing journals, 1 seat"
    # Fitz's train: the two gears in mesh order, the two shafts, the bearings, as the smart-insert plan reads them
    items, skipped = gc.to_fitz_items(g)
    assert skipped == []
    assert [(i["code"], i["qty"]) for i in items] == [("spur_gear", 1), ("spur_gear", 1), ("shaft", 1), ("shaft", 1),
                                                      ("bearing", 4)]
    assert [i["params"]["Z"] for i in items[:2]] == [20, 60] and items[4]["params"] == {"SERIES": 6204}
    tr = trains.select(tmp_path, {"instances": [], "mates": [], "groups": []}, items)
    assert tr is not None and [len(tr.of(r)) for r in ("gear", "shaft", "bearing")] == [2, 2, 4]
    assert trains.centre_distance(2, 20, 60) == mesh.v("centre_distance")


# ----------------------------------------------------------------------------- golden case 3: the reducer
def test_golden_reducer_graph_plan_icd_direct() -> None:
    g = _graph("reducer")
    by = _by(g)
    assert (by["pinion"].v("teeth"), by["output_gear"].v("teeth"), by["pinion"].v("module")) == (20, 60, 2)
    assert (by["input_shaft"].v("d"), by["output_shaft"].v("d")) == (20, 30)
    assert (by["input_bearing"].v("designation"), by["output_bearing"].v("designation")) == (6204, 6206)
    assert (by["gear_key"].v("b"), by["gear_key"].v("h"), by["gear_key"].v("length")) == (8, 7, 18)
    plan = gc.to_plan(g, resolved=True)
    assert [s["name"] for s in plan["subassemblies"]] == ["Housing", "Input shaft group", "Output shaft group"]
    sk, ifs = gc.to_icd(g, plan)
    it = _items(sk)
    assert sk["layout"] == "gearbox" and icd.problems(sk, ifs) == []
    xi, xo = it["Input shaft"]["copies"][0][0], it["Output shaft"]["copies"][0][0]
    assert xo - xi == 80
    seats = {f["b"]["name"]: f["data"]["designation"] for f in ifs if f["kind"] == "bearing_seat"}
    assert seats == {"Input shaft": "6204", "Output shaft": "6206"}
    keys = {f["b"]["name"]: (f["data"]["b"], f["data"]["h"], f["data"]["length"]) for f in ifs if f["kind"] == "key"}
    assert keys == {"Input shaft": (6, 6, 18), "Output shaft": (8, 7, 18)}
    caps = sorted((f["b"]["name"], f["data"]["cap"], f["data"]["normal"][1]) for f in ifs
                  if f["kind"] == "hole_pattern" and f["data"].get("cap"))
    assert caps == [("Input blind cap", "blind", -1), ("Input open cap", "open", 1), ("Output blind cap", "blind", -1),
                    ("Output open cap", "open", 1)]
    assert gc.check(g, sk, ifs) == []
    d = gc.to_direct(g, plan)
    # every designed part, the housing, cover and caps included (WORKLIST 45 generators, tests/test_generators.py)
    assert {k for k, v in d.items() if v["path"] == "direct"} == set(d) and len(d) == 10
    assert gc.to_fitz_items(g)[0] == []  # a housing: the office lays it out, not a train


# ----------------------------------------------------------------------------- the reverse adapter
@pytest.mark.parametrize("case", ["keyed_gear", "gear_pair", "reducer"])
def test_reverse_adapter_round_trip(case: str) -> None:
    g = _graph(case)
    plan = gc.to_plan(g, resolved=True)
    sk, ifs = gc.to_icd(g, plan)
    back = adapt.from_office(plan, sk, ifs, g.brief, g.name)
    assert back.source == "plan" and validate.errors(back) == []
    assert sorted(c.name for c in back.components) == sorted(c.name for c in g.components)
    want = sorted((x.kind, g.comp(x.host).name, g.comp(x.guest).name) for x in g.connections  # type: ignore[union-attr]
                  if True)
    got = sorted((x.kind, back.comp(x.host).name, back.comp(x.guest).name) for x in back.connections)  # type: ignore[union-attr]
    assert got == want
    for c in g.components:
        b = next(x for x in back.components if x.name == c.name)
        assert b.kind == c.kind, c.name
        for p in ("module", "teeth", "d", "designation", "b", "h", "shoulder_d"):
            if c.v(p) is not None and p in b.params:
                assert float(b.v(p)) == float(c.v(p)), (c.name, p)
    # and the graph read back compiles to the same layout
    _sk2, ifs2 = gc.to_icd(back, gc.to_plan(back, resolved=True)) if case != "reducer" else (sk, ifs)
    assert [f["kind"] for f in ifs2] == [f["kind"] for f in ifs]


def test_reverse_adapter_reads_old_programs() -> None:
    """Plans made before the graph: the 1:3 pair as written by the standard planner and the live reducer plan."""
    from test_office_gearbox_caps import BRIEF, REDUCER
    from test_office_gearbox_caps import _parts as reducer_parts
    from test_office_shaft_line import PAIR, _parts

    from aicad.office import planner

    sk, ifs = icd.build(_parts(PAIR), "Simple spur gear pair 1:3 with shafts and bearings")
    g = adapt.from_office(planner.normalise_plan(PAIR, "standard"), sk, ifs)  # type: ignore[arg-type]
    mesh = next(x for x in g.connections if x.kind == "gear_mesh")
    assert (mesh.v("centre_distance"), mesh.v("ratio")) == (80, 3)
    assert sorted(x.kind for x in g.connections).count("bearing_journal") == 2
    assert g.layout["parts"][next(c.id for c in g.components if c.name == "Gear")]["at"] == [[80, 0, 0]]
    parts, _ids = reducer_parts()
    sk, ifs = icd.build(parts, BRIEF)
    g = adapt.from_office(planner.normalise_plan(REDUCER, "archie"), sk, ifs, BRIEF)  # type: ignore[arg-type]
    kinds = [x.kind for x in g.connections]
    assert kinds.count("bolted_joint") == 5 and kinds.count("bearing_seat") == 2 and kinds.count("hub_fit") == 0
    assert kinds.count("keyed_hub") == 2 and kinds.count("gear_mesh") == 1
    assert {c.v("designation") for c in g.of_kind("bearing")} == {6204, 6205}


# ----------------------------------------------------------------------------- the intent compiler (stub provider)
def _stub(*cases: str) -> StubProvider:
    replies = [_case(c)["reply"] for c in cases]

    def responder(req: llm.CallRequest) -> str | None:
        if req.role != "intent":
            return None
        return "```json\n" + json.dumps(replies.pop(0)) + "\n```"

    return StubProvider(responder)


@pytest.mark.parametrize("case,job,tier", [("keyed_gear", "simple", "sonnet"), ("gear_pair", "simple", "sonnet"),
                                           ("reducer", "complex", None)])
def test_intent_run_routes_by_job_and_validates(case: str, job: str, tier: str | None) -> None:
    from aicad.llm import routing

    d = _case(case)
    stub = _stub(case)
    with llm.use_provider(stub, roles=("intent",)):
        res = asyncio.run(intent.run(d["name"], d["brief"]))
    assert res.ok and res.job == job and res.error is None
    req = stub.calls[0]
    assert req.role == "intent" and req.schema == intent.INTENT_SCHEMA and req.standalone_system
    assert req.model == (routing.TIERS[tier] if tier else None)  # None: the provider default, Opus
    assert "keyed_hub" in req.system and "Never invent sizes" in req.system
    assert res.graph is not None and res.graph.dump() == _graph(case).dump()


def test_intent_rejects_a_bad_answer() -> None:
    bad = StubProvider(lambda req: '```json\n{"components": [{"id": "X!", "kind": "shaft"}]}\n```')
    with llm.use_provider(bad, roles=("intent",)), pytest.raises(llm.StructuredOutputError):
        asyncio.run(intent.run("x", "A shaft"))
    with llm.use_provider(bad, roles=("intent",)):
        out = asyncio.run(goffice.plan(None, "x", "A shaft"))
    assert out.plan is None and out.error  # the office falls back to its planner


def test_job_size() -> None:
    assert intent.job_of("Build a Spur Gear mounted on stepped Shaft and locked with a key") == "simple"
    assert intent.job_of(_case("gear_pair")["brief"]) == "simple"  # "No housing" names no housing
    assert intent.job_of("Build a Single stage 3:1 reducer with Spur Gears") == "complex"
    assert intent.job_of("A conveyor with a drive pulley and a motor plate") == "complex"


# ----------------------------------------------------------------------------- questions instead of guessing
def test_questions_when_it_matters_and_answers_by_code() -> None:
    brief = "A spur gear pair 1:3 on two shafts with bearings"
    reply = {"components": [
        {"id": "s1", "kind": "shaft", "name": "Input shaft"}, {"id": "s2", "kind": "shaft", "name": "Output shaft"},
        {"id": "p", "kind": "spur_gear", "name": "Pinion"}, {"id": "w", "kind": "spur_gear", "name": "Wheel"},
        {"id": "b", "kind": "bearing", "name": "Bearing", "qty": 4}],
        "connections": [{"kind": "hub_fit", "host": "s1", "guest": "p"}, {"kind": "hub_fit", "host": "s2", "guest": "w"},
                        {"kind": "gear_mesh", "host": "p", "guest": "w", "params": {"ratio": 3}},
                        {"kind": "bearing_journal", "host": "s1", "guest": "b", "params": {"count": 2}},
                        {"kind": "bearing_journal", "host": "s2", "guest": "b", "params": {"count": 2}}],
        "questions": [{"id": "shaft_size", "question": "What shaft diameter?", "options": ["20", "25"]},
                      {"id": "lube", "question": "Grease or oil?", "options": ["Grease", "Oil bath"]}]}
    _g0, _iss, qs = intent.compile_reply(reply, "Pair", brief)
    assert [q.id for q in qs] == ["housing", "bearings", "lube"]  # sizes are never asked; at most three
    assert qs[0].options == [questions.HOUSING_NO, questions.HOUSING_YES] and qs[0].default == questions.HOUSING_NO
    # answering "a housing" completes it by code: base, cover, a seat per bearing, four caps, screws and bolts
    g2, _iss2, qs2 = intent.compile_reply(reply, "Pair", brief, answers={"housing": questions.HOUSING_YES,
                                                                        "bearings": questions.BEARINGS_60})
    assert [q.id for q in qs2] == ["lube"] and not validate.errors(g2)
    kinds = sorted(c.kind for c in g2.components)
    assert kinds.count("bearing_cap") == 4 and "housing" in kinds and "cover" in kinds
    # the shared bearing line is split, one pair per shaft, each pair in a seat of the housing
    assert sorted((c.name, c.qty) for c in g2.of_kind("bearing")) == [("Input bearing", 2), ("Output bearing", 2)]
    assert sum(1 for x in g2.connections if x.kind == "bearing_seat") == 2
    # 60xx as answered: Ø20 input (assumed) -> 6004; output 20 x 3^(1/3) = 28.8 -> Ø30 -> 6006
    assert sorted(c.v("designation") for c in g2.of_kind("bearing")) == [6004, 6006]
    sk, ifs = gc.to_icd(g2)
    assert sk["layout"] == "gearbox" and len([f for f in ifs if f["data"].get("cap")]) == 4
    # "no housing": ruled out, and never asked again
    g3, _i, qs3 = intent.compile_reply(reply, "Pair", brief, answers={"housing": questions.HOUSING_NO})
    assert "housing" in g3.constraints.excluded and "housing" not in [q.id for q in qs3]
    # a material question only when the brief hints at a choice without naming one
    assert "material" in [q.id for q in intent.compile_reply(reply, "Pair", brief + " for a food line")[2]]
    assert "material" not in [q.id for q in intent.compile_reply(reply, "Pair", brief + " in stainless 316")[2]]


# ----------------------------------------------------------------------------- the office, behind the flag
def _start(c: Any, email: str, case: str) -> str:
    from test_platform import signup

    d = _case(case)
    signup(c, email)
    _topup(email)
    r = c.post("/api/office/programs", json={"name": d["name"], "brief": d["brief"], "planner": "archie",
                                             "deliverables": False})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_flag_off_keeps_the_old_planner(office: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.delenv(goffice.ENV, raising=False)
    assert goffice.enabled()  # the default for everyone since 2026-11-20 (PD-110)
    monkeypatch.setenv(goffice.ENV, "0")  # the off switch keeps the old planner
    assert not goffice.enabled()
    stub = _stub("keyed_gear")
    with llm.use_provider(stub, roles=("intent",)):
        pid = _start(office, "old@x.com", "keyed_gear")
        v = _wait(office, pid, lambda v: v["status"] == "plan_review")
    assert stub.calls == [] and "graph" not in v["plan"]  # the old path ran (no live AI in tests: the fallback)


def test_office_keyed_gear_end_to_end(office: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Golden case 1 through the office with FW_DESIGN_GRAPH=1: the plan comes from the graph (3 parts, one unit), the
    review shows the graph, one click approves plan and interfaces, both parts build with no AI, and the key sits in
    its keyseat at (6.5, -10, 0)."""
    from test_office_icd import _asm

    from aicad.assembly import store as astore

    monkeypatch.setenv(goffice.ENV, "1")
    c = office
    with llm.use_provider(_stub("keyed_gear"), roles=("intent",)):
        pid = _start(c, "graph1@x.com", "keyed_gear")
        v = _wait(c, pid, lambda v: v["status"] == "plan_review")
    pg = v["plan"]["graph"]
    assert v["plan"]["source"] == "archie" and pg["questions"] == [] and pg["check"] == []
    assert [x["name"] for x in pg["view"]["components"]] == ["Stepped shaft", "Spur gear", "Parallel key"]
    assert [x["text"] for x in pg["view"]["connections"]] == ["Spur gear keyed on Stepped shaft (Parallel key)",
                                                             "Spur gear against the shoulder of Stepped shaft"]
    shaft_params = {p["text"]: p["source"] for p in pg["view"]["components"][0]["params"]}
    assert shaft_params == {"Ø20": "assumed", "step Ø26": "design rule", "length 80": "assumed"}
    key_params = [p["text"] for p in pg["view"]["components"][2]["params"]]
    assert key_params == ["b 6", "h 6", "length 18"]
    view_text = json.dumps(pg["view"])
    assert "claude" not in view_text.lower() and "_id" not in view_text and "intent" not in view_text
    t0 = time.time()
    r = c.post(f"/api/office/programs/{pid}/gates/express", json={})
    assert r.status_code == 200, r.text
    assert r.json()["express"]["run"]
    v = _wait(c, pid, lambda v: v["orchestrator"]["state"] in ("complete", "blocked", "stopped"), timeout=600)
    assert v["status"] == "complete", [(t["title"], t["column"], (t.get("run") or {}).get("status")) for t in v["tickets"]]
    by = {t["title"]: t for t in v["tickets"]}
    assert sorted(by) == sorted(["Stepped shaft", "Spur gear", "Parallel key", "Assemble Keyed gear",
                                 "Final assembly of Keyed gear"])
    assert all((by[n].get("direct") or {}).get("path") == "direct" for n in ("Stepped shaft", "Spur gear"))
    final = astore.load(_asm(c)[0], v["assembly"]["final"])
    pos = {i["name"]: (round(i["T"][3], 3), round(i["T"][7], 3), round(i["T"][11], 3)) for i in final["instances"]}
    assert pos["Parallel key"] == (6.5, -10, 0) and v["assembly"]["clashes"] == []
    assert not any((i.get("office") or {}).get("bin") for i in final["instances"])
    print(f"\ngraph keyed gear, simulated: approve -> assembled in {time.time() - t0:.1f} s")


def test_office_gear_pair_end_to_end(office: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Golden case 2: no housing, four 6204 seated on the journals at Y -29 .. -15 and 15 .. 29 on both axes (the
    instance origin is the bearing's face: hand values from the layout rule), gears 80 apart, no clash."""
    from test_office_icd import _asm

    from aicad.assembly import store as astore

    monkeypatch.setenv(goffice.ENV, "1")
    c = office
    with llm.use_provider(_stub("gear_pair"), roles=("intent",)):
        pid = _start(c, "graph2@x.com", "gear_pair")
        v = _wait(c, pid, lambda v: v["status"] == "plan_review")
    assert v["plan"]["graph"]["check"] == [] and v["light"] is not None
    r = c.post(f"/api/office/programs/{pid}/gates/express", json={})
    assert r.status_code == 200 and r.json()["express"]["run"], r.text
    v = _wait(c, pid, lambda v: v["orchestrator"]["state"] in ("complete", "blocked", "stopped"), timeout=1500)
    assert v["status"] == "complete", [(t["title"], t["column"], (t.get("run") or {}).get("status")) for t in v["tickets"]]
    st = v["assembly"]
    assert st["clashes"] == [] and not any(p["kind"] == "placeholder" for p in st["parts"].values())
    final = astore.load(_asm(c)[0], st["final"])
    bearings = [i for i in final["instances"] if (i.get("office") or {}).get("seated")]
    at = sorted((round(b["T"][3], 3), round(b["T"][7], 3), round(b["T"][11], 3)) for b in bearings)
    assert at == [(0, -29, 0), (0, 15, 0), (80, -29, 0), (80, 15, 0)]
    gears = {i["name"]: round(i["T"][3], 3) for i in final["instances"] if i["name"] in ("Pinion", "Gear")}
    assert abs(gears["Gear"] - gears["Pinion"]) == 80


def test_office_reducer_end_to_end(office: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Golden case 3: the reducer in its housing. The plan is not small (two gates); four caps on four seats, the
    shafts 80 apart, both keys in their keyseats, nothing in the parts bin, no clash."""
    from test_office_icd import _asm

    from aicad.assembly import store as astore

    monkeypatch.setenv(goffice.ENV, "1")
    c = office
    with llm.use_provider(_stub("reducer"), roles=("intent",)):
        pid = _start(c, "graph3@x.com", "reducer")
        v = _wait(c, pid, lambda v: v["status"] == "plan_review")
    assert v["plan"]["graph"]["check"] == [] and v["light"] is None
    assert c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={}).status_code == 200
    v = c.get(f"/api/office/programs/{pid}").json()
    assert v["icd"]["problems"] == [], v["icd"]["problems"]
    assert c.post(f"/api/office/programs/{pid}/gates/icd/approve").status_code == 200
    c.post(f"/api/office/programs/{pid}/run")
    v = _wait(c, pid, lambda v: v["orchestrator"]["state"] in ("complete", "blocked", "stopped"), timeout=2400)
    assert v["status"] == "complete", [(t["title"], t["column"], (t.get("run") or {}).get("status")) for t in v["tickets"]]
    final = astore.load(_asm(c)[0], v["assembly"]["final"])
    assert not [i["name"] for i in final["instances"] if (i.get("office") or {}).get("bin")]
    names = [i["name"] for i in final["instances"]]
    assert sum(1 for n in names if n.endswith(" cap")) == 4 and "Pinion key" in names and "Gear key" in names
    shafts = {i["name"]: i["T"][3] for i in final["instances"] if i["name"] in ("Input shaft", "Output shaft")}
    assert math.isclose(abs(shafts["Output shaft"] - shafts["Input shaft"]), 80, abs_tol=1e-6)
    from aicad.office import program_assembly

    v = _wait(c, pid, lambda v: program_assembly.clash_status(v["assembly"])["status"] in ("done", "failed"),
              timeout=900)
    cs = program_assembly.clash_status(v["assembly"])
    assert (cs["status"], cs["count"]) == ("done", 0), (cs, v["assembly"].get("clashes"))


def test_questions_block_approval_until_answered(office: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """An ambiguous brief: the plan review shows Archie's questions; approval is refused until they are answered;
    answering "a split housing" is applied by code (no second model call) and the plan gains the housing."""
    monkeypatch.setenv(goffice.ENV, "1")
    reply = {"components": [
        {"id": "s1", "kind": "shaft", "name": "Input shaft"}, {"id": "s2", "kind": "shaft", "name": "Output shaft"},
        {"id": "p", "kind": "spur_gear", "name": "Pinion", "params": {"module": 2, "teeth": 20}},
        {"id": "w", "kind": "spur_gear", "name": "Gear", "params": {"module": 2, "teeth": 40}},
        {"id": "b", "kind": "bearing", "name": "Bearing 6204", "qty": 4, "params": {"designation": 6204}}],
        "connections": [{"kind": "keyed_hub", "host": "s1", "guest": "p"}, {"kind": "keyed_hub", "host": "s2", "guest": "w"},
                        {"kind": "gear_mesh", "host": "p", "guest": "w"},
                        {"kind": "bearing_journal", "host": "s1", "guest": "b", "params": {"count": 2}},
                        {"kind": "bearing_journal", "host": "s2", "guest": "b", "params": {"count": 2}}]}
    stub = StubProvider(lambda req: "```json\n" + json.dumps(reply) + "\n```" if req.role == "intent" else None)
    from test_platform import signup

    c = office
    signup(c, "ask@x.com")
    _topup("ask@x.com")
    with llm.use_provider(stub, roles=("intent",)):
        pid = c.post("/api/office/programs", json={"name": "Pair", "brief": "A 1:2 spur pair m2 20/40 on two shafts "
                                                   "with 6204 bearings", "planner": "archie"}).json()["id"]
        v = _wait(c, pid, lambda v: v["status"] == "plan_review")
        qs = v["plan"]["graph"]["questions"]
        assert [q["id"] for q in qs] == ["housing"]
        r = c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={})
        assert r.status_code == 409 and "questions" in r.json()["detail"]
        r = c.post(f"/api/office/programs/{pid}/plan/answers", json={"answers": {"housing": questions.HOUSING_YES}})
        assert r.status_code == 200, r.text
    v = r.json()
    assert len(stub.calls) == 1 and v["plan"]["graph"]["questions"] == []
    names = [p["name"] for s in v["plan"]["subassemblies"] for p in s["parts"]]
    assert {"Housing base", "Housing cover", "Input open cap", "Output blind cap"} <= set(names)
    assert c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={}).status_code == 200


# ----------------------------------------------------------------------------- the live replies, replayed
@pytest.mark.parametrize("case,direct,question", [("keyed_gear", 2, None), ("gear_pair", 4, None),
                                                  ("reducer", 10, "material_spur_gear")])
def test_live_intent_replies_replayed(case: str, direct: int, question: str | None) -> None:
    """The one live intent reply per golden case (docs/reports/design-graph.md), replayed with the stub provider:
    the same deterministic middle gives a graph whose compiled ICD has no problem and agrees with it. The live
    reducer asked about the gear material: answered by code, no second model call."""
    d = json.loads((GOLDEN / f"{case}.live.json").read_text(encoding="utf-8"))
    stub = StubProvider(lambda req: "```json\n" + json.dumps(d["reply"]) + "\n```" if req.role == "intent" else None)
    with llm.use_provider(stub, roles=("intent",)):
        out = asyncio.run(goffice.plan(None, d["name"], d["brief"]))
    assert out.error is None and out.plan is not None
    pg = out.plan["graph"]
    assert pg["check"] == [] and [q["id"] for q in pg["questions"]] == ([question] if question else [])
    g = out.graph
    assert g is not None
    sk, ifs = gc.to_icd(g, out.plan)
    assert icd.problems(sk, ifs) == []
    assert sum(1 for v in gc.to_direct(g, out.plan).values() if v["path"] == "direct") == direct
    if case == "reducer":
        # shoulders inside a housing: laid out from the connections (step 2); the template still can't (said as limits)
        from aicad.graph import layout

        assert sk["layout"] == "gearbox" and len(pg["limits"]) == (0 if layout.enabled() else 2)
        doc = {"plan": out.plan}
        new, notes = goffice.answer(doc, {question: "Carbon steel (C45)"})
        assert notes is None and new is not None and new.plan is not None and new.plan["graph"]["questions"] == []
        mats = {c["name"]: c["material"] for c in new.plan["graph"]["data"]["components"] if c["kind"] == "spur_gear"}
        assert mats == {"Pinion": "Carbon steel (C45)", "Output gear": "Carbon steel (C45)"}
        assert len(stub.calls) == 1


# ----------------------------------------------------------------------------- benchmark A3: answers that keep the design
_PLANETARY = json.loads((Path(__file__).resolve().parents[1] / "src" / "aicad" / "eval" / "golden_cases"
                         / "k_planetary.intent.json").read_text(encoding="utf-8"))["reply"]
_PLANET_Q = {"id": "planet_count", "question": "How many planet gears?", "options": ["3", "4", "2"], "default": "3"}


def _planetary_program(c: Any, email: str, second: Any) -> tuple[str, StubProvider]:
    """A planetary program whose first intent reply asks the planet count (A3); ``second`` answers any later call."""
    from test_platform import signup

    first = {**_PLANETARY, "questions": [_PLANET_Q]}
    n = {"i": 0}

    def responder(req: Any) -> str | None:
        if req.role != "intent":
            return None
        n["i"] += 1
        return "```json\n" + json.dumps(first if n["i"] == 1 else second) + "\n```"

    stub = StubProvider(responder)
    signup(c, email)
    _topup(email)
    with llm.use_provider(stub, roles=("intent",)):
        pid = c.post("/api/office/programs", json={"name": "Planetary", "brief": "Build a single stage planetary "
                                                   "Gearbox", "planner": "archie"}).json()["id"]
        v = _wait(c, pid, lambda v: v["status"] == "plan_review")
    assert [q["id"] for q in v["plan"]["graph"]["questions"]] == ["planet_count"]
    return pid, stub


def _parts(v: dict[str, Any]) -> dict[str, int]:
    return {p["name"]: int(p.get("qty") or 1) for s in v["plan"]["subassemblies"] for p in s["parts"]}


def test_a3_the_default_answer_keeps_the_graph_with_no_second_call(office: Any,  # noqa: F811
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(goffice.ENV, "1")
    c = office
    pid, stub = _planetary_program(c, "a3d@x.com", None)
    with llm.use_provider(stub, roles=("intent",)):
        r = c.post(f"/api/office/programs/{pid}/plan/answers", json={"answers": {"planet_count": "3"}})
    assert r.status_code == 200, r.text
    v = r.json()
    assert len(stub.calls) == 1 and v["status"] == "plan_review" and v["plan"]["graph"]["questions"] == []
    parts = _parts(v)
    assert parts["Planet gear"] == 3 and parts["Ring gear"] == 1 and parts["Planet pin"] == 3


def test_a3_a_failed_replan_keeps_the_plan_it_started_from(office: Any,  # noqa: F811
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(goffice.ENV, "1")
    c = office
    pid, stub = _planetary_program(c, "a3f@x.com", {"components": "not a graph"})
    with llm.use_provider(stub, roles=("intent",)):
        r = c.post(f"/api/office/programs/{pid}/plan/answers", json={"answers": {"planet_count": "4"}})
        assert r.status_code == 200, r.text
        v = _wait(c, pid, lambda v: v["status"] == "plan_review")
    assert len(stub.calls) == 2
    parts = _parts(v)
    assert parts["Planet gear"] == 3 and parts["Ring gear"] == 1  # the planetary plan, not a generic breakdown
    assert "plan before them is kept" in (v["plan"].get("note") or "")


def test_a3_a_long_summary_no_longer_loses_the_plan(office: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setenv(goffice.ENV, "1")
    c = office
    four = json.loads(json.dumps(_PLANETARY))
    four["summary"] = "Single-stage planetary gearbox with 4 planets. " * 9  # ~430 characters, the limit is 300
    for comp in four["components"]:
        if comp.get("qty") == 3:
            comp["qty"] = 4
    pid, stub = _planetary_program(c, "a3l@x.com", four)
    with llm.use_provider(stub, roles=("intent",)):
        r = c.post(f"/api/office/programs/{pid}/plan/answers", json={"answers": {"planet_count": "4"}})
        assert r.status_code == 200, r.text
        v = _wait(c, pid, lambda v: v["status"] == "plan_review")
    assert len(stub.calls) == 2 and "plan before them is kept" not in (v["plan"].get("note") or "")
    assert _parts(v)["Planet gear"] == 4
