"""The founder's benchmark "Build a single stage planetary Gearbox", attempt A1 (2026-11-21), and its orchestration
fixes (``docs/reports/planetary-orchestration.md``).

A1 planned the gears right (sun z30, three planets z30, ring z90 internal, m2, a = 60, i = 4) and failed in the
office: the built input shaft and all three planet pins were sent back and blocked "after 2 rounds" for clashing with
the placeholder of the ring gear (not built yet: a solid Ø180 disc where the real internal gear is open to its teeth),
and the planet bearing 6204 (D 47) left a 4 mm rim in a planet whose root is Ø55.

Hand values: root Ø of a z30 m2 planet d_f = m (z - 2.5) = 55; the rim rule s_R >= 1.2 h_t = 1.2 x 2.25 m = 2.7 m
(ISO 6336-3 Y_B = 1, AGMA 2001-D04 K_B = 1) = 5.4 mm, so D <= 55 - 10.8 = 44.2: on the Ø20 pin the 6004 (20 x 42 x
12), rim (55 - 42) / 2 = 6.5 mm = 3.25 m. Ring: root Ø m (z + 2.5) = 185, rim 6 mm, OD 197 (the layout's own rule).
"""

from __future__ import annotations

import asyncio
import copy
import json
import math
from pathlib import Path
from typing import Any

import pytest

from aicad.eval import golden
from aicad.graph import compile as gc
from aicad.graph import intent, planetary
from aicad.office import (
    icd,
    interfaces,
    orchestrator,
    planner,
    program_assembly,
    service,
    store,
    supervisor,
)

HERE = Path(__file__).resolve().parent
CASES = Path(golden.__file__).resolve().parent / "golden_cases"
A1 = json.loads((HERE / "golden" / "planetary_a1_icd.json").read_text(encoding="utf-8"))
REPLY = json.loads((CASES / "k_planetary.intent.json").read_text(encoding="utf-8"))
BRIEF = "Build a single stage planetary Gearbox"
ENG = {"kind": "user", "id": "u1", "name": "Eng"}


def _graph(reply: dict[str, Any] | None = None, brief: str = BRIEF):
    g, iss, _qs = intent.compile_reply(copy.deepcopy(reply or REPLY["reply"]), "Planetary", brief)
    assert not [i for i in iss if i["severity"] == "error"], iss
    return g


def _icd(g) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    p = gc.to_plan(g, resolved=True)
    return gc.to_icd(g, p)


def _item(sk: dict[str, Any], name: str) -> str:
    return next(i for i, v in sk["items"].items() if v["name"] == name)


# ============================================================================ the rim rule (graph/planetary.py)
def test_a1_planet_bearing_follows_the_rim_rule() -> None:
    g = _graph()
    brg, pin, planet = g.comp("planet_bearing"), g.comp("planet_pin"), g.comp("planet_gear")
    assert planetary.root_d(2, 30) == 55.0
    assert brg.v("designation") == 6004 and (brg.v("d"), brg.v("D"), brg.v("B")) == (20.0, 42.0, 12.0)
    assert pin.v("d") == 20.0 and pin.v("journal_d") == 20.0  # the pin keeps its Ø: 6004 has its bore
    assert planet.v("bore") == 42.0
    assert planetary.rim(2, 30, 42) == 6.5 >= planetary.RIM_MIN_M * 2
    assert planetary.rim(2, 30, 47) == 4.0 < planetary.RIM_MIN_M * 2  # A1's 6204 fails the rule
    said = " ".join(g.notes)
    assert "6004" in said and "6204 (OD 47) left a rim of 4 mm" in said and "ISO 6336-3" in said
    # teeth and the set unchanged: z_r = z_s + 2 z_p, (z_s + z_r) / 3 whole, i = 1 + 90 / 30 = 4
    zs, zp, zr = (int(g.comp(i).v("teeth")) for i in ("sun_gear", "planet_gear", "ring_gear"))
    assert (zs, zp, zr) == (30, 30, 90) and (zs + zr) % 3 == 0 and 1 + zr / zs == 4
    assert planetary.normalise(copy.deepcopy(g)).dump() == g.dump()  # idempotent


def test_planet_bearing_choice_by_hand() -> None:
    # m2 z30: root 55, D <= 55 - 2 x 5.4 = 44.2
    assert planetary.planet_bearing(2, 30, 20.0) == 6004       # D 42, on the Ø20 pin
    assert planetary.planet_bearing(2, 30, 17.0) == 6203       # on a Ø17 pin: the larger of 6003 (D35) / 6203 (D40)
    assert planetary.planet_bearing(2, 30, 25.0) == 6004       # no Ø25 fits: the largest bore that does
    assert planetary.planet_bearing(2, 30, 25.0, pin_fixed=True) is None  # the brief's Ø25 pin: none
    assert planetary.planet_bearing(2, 17, 20.0) is None       # root 29, D <= 18.2: no 60xx / 62xx


def test_no_bearing_fits_so_the_planets_grow_with_the_ring() -> None:
    reply = copy.deepcopy(REPLY["reply"])
    for c in reply["components"]:
        if c["id"] in ("sun_gear", "planet_gear", "ring_gear"):
            c["params"] = {**c.get("params", {}), "module": 1}
    g = _graph(reply)
    zs, zp, zr = (int(g.comp(i).v("teeth")) for i in ("sun_gear", "planet_gear", "ring_gear"))
    # m1, z_p 30: root 27.5, D <= 27.5 - 5.4 = 22.1: no 60xx / 62xx (the least D is 26). 2 (30 + z) / 3 whole
    # steps z by 3: z 33 (root 30.5, D <= 25.1: none), z 36 (root 33.5, D <= 28.1): 6000 (10 x 26) and 6001
    # (12 x 28) fit; the larger bore, 6001, rim (33.5 - 28) / 2 = 2.75 mm = 2.75 m
    assert (zs, zp, zr) == (30, 36, 102)
    assert (zs + zr) % 3 == 0
    brg = g.comp("planet_bearing")
    assert brg.v("designation") == 6001 and g.comp("planet_pin").v("d") == 12.0
    assert planetary.rim(1, zp, brg.v("D")) >= planetary.RIM_MIN_M * 1
    assert any("36 teeth (was 30)" in n and "1 + 102 / 30" in n for n in g.notes)
    assert planetary.normalise(copy.deepcopy(g)).dump() == g.dump()


def test_a_bearing_the_brief_names_is_kept_and_checked() -> None:
    reply = copy.deepcopy(REPLY["reply"])
    g0 = _graph(reply, BRIEF + ", planet bearings 6204")
    for c in g0.components:  # the brief's own bearing: written in the reply as the engineer's
        if c.id == "planet_bearing":
            c.set("designation", 6204, "brief", "the brief", force=True)
    g = planetary.normalise(g0)
    assert g.comp("planet_bearing").v("designation") == 6204
    assert any(n.startswith("Check: Planet bearing 6204") for n in g.notes)


# ============================================================================ faithful placeholders (office/icd.py)
def test_placeholders_carry_the_openings_the_icd_defines() -> None:
    sk, ifs = _icd(_graph())
    ring = icd.placeholder_spec(sk, ifs, _item(sk, "Ring gear"))
    assert ring["size"][0] == 197.0  # the rim's OD, not the pitch Ø
    assert {"c": [0.0, 0.0], "d": 185.0} in ring["holes"]  # open to the root circle m (z + 2.5) = 185
    assert icd.internal_opening(2, 90) == 185.0
    planet = icd.placeholder_spec(sk, ifs, _item(sk, "Planet gear"))
    seats = sorted((s["z0"], s["z1"], s["d"]) for s in planet["seats"])
    # the 6004 seat Ø42 bored from the -Y face (-10) to its shoulder (+6), and behind the shoulder the gear
    # generator's bore 42 - (42 - 20) / 4 = 36.5 (clear of the turning inner ring and of the Ø20 pin)
    assert seats == [(-10.0, 6.0, 42.0)]
    assert {"c": [0.0, 0.0], "d": 36.5} in planet["holes"]
    house = icd.placeholder_spec(sk, ifs, _item(sk, "Housing base"))
    clear = sorted((s["z0"], s["z1"]) for s in house["seats"] if s["d"] == 22.0)
    assert clear == [(-33.5, -29.5), (29.5, 33.5)]  # (housing W 123: the 1 mm running gap) the shafts through the end-wall shoulders to the cavity
    assert house["pockets"]  # the gear cavity
    # two bearings side by side in one bore: no fictitious shoulder between them
    walls = [f for f in icd.item_features(sk, ifs, _item(sk, "Housing base")) if "bearing shoulder" in f["label"]]
    assert sorted(f["z"] for f in walls) == [-33.5, 33.5]


def _solid(spec: dict[str, Any], T: list[float]) -> Any:
    import numpy as np

    from aicad.assembly import geometry, placeholder, xform

    return placeholder.shape(spec).moved(geometry._loc(np.asarray(xform.from12(T))))


def _overlap(a: Any, b: Any) -> float:
    try:
        return float((a & b).volume)
    except Exception:  # noqa: BLE001  (an empty common)
        return 0.0


def test_a1_ring_placeholder_no_longer_claims_the_room_inside() -> None:
    """A1's own ICD: the old ring placeholder (a solid pitch disc) against the input shaft and the planet pins, and
    the faithful one (open to Ø185)."""
    sk, ifs = A1["skeleton"], A1["interfaces"]
    ring = _item(sk, "Ring gear")
    it = sk["items"][ring]
    p = it["module"] * it["teeth"]
    old = icd.body_spec(it["shape"], [p, p, it["size"][2]], icd.item_features(sk, ifs, ring), None, it["name"])
    new = icd.placeholder_spec(sk, ifs, ring)
    r_old = _solid(old, program_assembly.place(sk, ring, 0))
    r_new = _solid(new, program_assembly.place(sk, ring, 0))
    for name, copies in (("Input shaft", 1), ("Planet pin", 3), ("Sun gear", 1), ("Planet carrier", 1)):
        i = _item(sk, name)
        spec = icd.placeholder_spec(sk, ifs, i)
        for k in range(copies):
            s = _solid(spec, program_assembly.place(sk, i, k))
            if name in ("Input shaft", "Planet pin", "Sun gear"):
                assert _overlap(r_old, s) > 1000.0, name  # what A1 measured (6858.5 / 7823.6 mm³ for real parts)
            assert _overlap(r_new, s) < 1e-3, name


def test_no_two_placeholders_of_the_planetary_set_overlap() -> None:
    """Every placeholder of the benchmark's ICD, placed: no pair claims the same material (meshing gears touch on
    their pitch circles, the ring is open to its root circle), so no swap-in can be sent back by an envelope."""
    sk, ifs = _icd(_graph())
    solids = []
    for i, it in sk["items"].items():
        spec = icd.placeholder_spec(sk, ifs, i)
        for k in range(len(it["copies"])):
            solids.append((f"{it['name']}<{k + 1}>", _solid(spec, program_assembly.place(sk, i, k))))
    hits = []
    for n, (a, sa) in enumerate(solids):
        for b, sb in solids[n + 1:]:
            v = _overlap(sa, sb)
            if v > 0.1:  # (meshing pitch cylinders are tangent; positions are rounded to 0.01 mm: 0.01 mm³)
                hits.append((a, b, round(v, 2)))
    assert hits == []


# ============================================================================ swap-in: placeholders are notes
def _adoc() -> dict[str, Any]:
    return {"instances": [{"id": "i1", "part": "p_real", "office": {"item": "shaft", "copy": 0}},
                          {"id": "i2", "part": "h_ring", "office": {"item": "ring", "copy": 0}},
                          {"id": "i3", "part": "p_pin", "office": {"item": "pin", "copy": 0}},
                          {"id": "i4", "part": "h_sun", "office": {"item": "sun", "copy": 0}}]}


def test_a_clash_with_a_placeholder_is_named_by_the_placeholder() -> None:
    ad = _adoc()
    assert program_assembly.placeholder_side(ad, {"a": "i2", "b": "i1"}) == "ring"
    assert program_assembly.placeholder_side(ad, {"a": "i1", "b": "i3"}) is None  # both built: a real clash
    assert program_assembly.placeholder_side(ad, {"a": "i2", "b": "i4"}, {"sun"}) == "ring"
    txt = program_assembly.pending_text({"a_name": "Ring gear<1>", "b_name": "Input shaft<1>", "volume_mm3": 6858.49,
                                         "until_name": "Ring gear"})
    assert "6858.5 mm³ against the placeholder of Ring gear" in txt and "re-checked when Ring gear is built" in txt
    st = {"clashes": [], "pending_clashes": [{}, {}], "check": {"status": "done", "scope": "swap"}}
    cs = program_assembly.clash_status(st)
    assert cs["count"] == 0 and cs["pending"] == 2 and "2 overlaps with placeholders" in cs["text"]


KIT = {"subassemblies": [{"name": "Gears", "parts": [
    {"name": "Input shaft", "family": "turned", "complexity": 1, "qty": 1, "description": "Shaft Ø20 x 90 mm."},
    {"name": "Ring gear", "family": "turned", "complexity": 1, "qty": 1, "description": "Ring Ø197 x 26 mm."}]}]}


def _program(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    root = store.org_root(tmp_path, "org1")
    doc = service.new_program("Bench", "Two parts made on their own", "org1", "u1", 2, 1000, "standard")
    service.set_plan(root, doc, planner.normalise_plan(KIT, "standard"), ENG)
    service.approve_plan(root, doc, None, ENG)
    if interfaces.unconnected(doc):
        interfaces.keep_separate(root, doc, None, True, ENG)
    interfaces.approve(root, doc, ENG)
    doc["orchestrator"] = {"state": "paused", "user_id": "u1"}
    sk = doc["skeleton"]["items"]
    doc["assembly"] = {"status": "ready", "parts": {i: {"key": f"h_{i}", "kind": "placeholder", "icd_version": 1}
                                                    for i in sk}}
    for t in doc["tickets"]:
        if t["kind"] == "part":
            t["project_id"] = f"p-{t['id']}"
    store.save(root, doc)
    return root, doc


def _tk(root: Path, pid: str, title: str) -> dict[str, Any]:
    doc = store.load(root, pid)
    return next(t for t in doc["tickets"] if t["title"] == title)


def _edit(root: Path, pid: str, fn: Any) -> None:
    with store.lock(pid):
        doc = store.load(root, pid)
        fn(doc)
        store.save(root, doc)


class SwapEnv(orchestrator.Env):
    def __init__(self, last: dict[str, Any]) -> None:
        self.last = last

    async def swap_in(self, root: Path, pid: str, tid: str) -> dict[str, Any]:
        return {"last": self.last, "problems": [], "mates": 3}


async def _fit(root: Path, pid: str, env: orchestrator.Env, tid: str) -> str | None:
    return await orchestrator.Runner(root, pid, env)._fit(tid)


CLASH = {"a": "i2", "b": "i1", "a_name": "Ring gear<1>", "b_name": "Input shaft<1>", "volume_mm3": 6858.49}


@pytest.mark.parametrize("last", [
    {"clashes": [], "deferred": [{**CLASH, "until": "ring", "until_name": "Ring gear"}], "checked": True},
    {"clashes": [{**CLASH, "until": "ring", "until_name": "Ring gear"}], "checked": True},  # (an older env)
])
def test_a_built_part_is_never_sent_back_for_a_placeholder(tmp_path: Path, last: dict[str, Any]) -> None:
    root, doc = _program(tmp_path)
    pid = doc["id"]
    tid = _tk(root, pid, "Input shaft")["id"]
    _edit(root, pid, lambda d: orchestrator._set_run(next(t for t in d["tickets"] if t["id"] == tid),
                                                     status="fitting", next="fit", clash_round=0))
    assert asyncio.run(_fit(root, pid, SwapEnv(last), tid)) is None
    t = _tk(root, pid, "Input shaft")
    assert t["run"]["status"] == "done" and t["fitted"] is True and t["column"] != "changes_requested"
    assert int(t["run"].get("clash_round") or 0) == 0 and t["clash_pending"] == ["Ring gear"]
    assert "re-checked when it is built" in t["run"]["line"]
    assert "re-checked when Ring gear is built" in t["comments"][-1]["text"]


def test_a_real_clash_still_goes_back_and_blocks_after_the_rounds(tmp_path: Path) -> None:
    root, doc = _program(tmp_path)
    pid = doc["id"]
    tid = _tk(root, pid, "Input shaft")["id"]
    env = SwapEnv({"clashes": [CLASH], "checked": True})
    for n in range(1, orchestrator.MAX_CLASH_ROUNDS + 2):
        _edit(root, pid, lambda d: orchestrator._set_run(next(t for t in d["tickets"] if t["id"] == tid),
                                                         status="fitting", next="fit"))
        out = asyncio.run(_fit(root, pid, env, tid))
        t = _tk(root, pid, "Input shaft")
        if n <= orchestrator.MAX_CLASH_ROUNDS:
            assert out == "design" and t["run"]["clash_round"] == n
    assert t["run"]["status"] == "blocked" and "still clashes" in t["run"]["blocked"]


def _a1_block(d: dict[str, Any], tid: str, ring_kind: str = "placeholder") -> None:
    """A1's state: the shaft built, swapped in, sent back twice, then blocked; the ring still a placeholder."""
    t = next(x for x in d["tickets"] if x["id"] == tid)
    ring = next(i for i, v in d["skeleton"]["items"].items() if v["name"] == "Ring gear")
    d["assembly"]["parts"][ring]["kind"] = ring_kind
    d["assembly"]["parts"][t["item_id"]]["kind"] = "real"
    t["column"] = "changes_requested"
    desc = "Clash: Ring gear ↔ Input shaft, 6858.5 mm³ of overlap"
    orchestrator._set_run(t, status="blocked", next=None, clash_round=3, feedback=[desc],
                          blocked=f"Input shaft still clashes in the program assembly after 2 rounds: {desc}")


def test_a1s_blocked_shaft_goes_back_to_fitz_unchanged_when_the_office_starts(tmp_path: Path) -> None:
    root, doc = _program(tmp_path)
    pid = doc["id"]
    tid = _tk(root, pid, "Input shaft")["id"]
    _edit(root, pid, lambda d: _a1_block(d, tid))
    doc = store.load(root, pid)
    t = next(x for x in doc["tickets"] if x["id"] == tid)
    assert program_assembly.placeholder_only(doc, t) == ["Ring gear"]
    assert orchestrator.heal_review_blocks(root, doc) == 1
    assert (t["run"]["status"], t["run"]["next"], t["column"]) == ("queued", "fit", "approved")
    assert t["run"]["clash_round"] == 0 and not t["run"].get("blocked")
    # once the ring is built, the same clash is real: nothing is healed
    root2, doc2 = _program(tmp_path / "b")
    tid2 = _tk(root2, doc2["id"], "Input shaft")["id"]
    _edit(root2, doc2["id"], lambda d: _a1_block(d, tid2, ring_kind="real"))
    doc2 = store.load(root2, doc2["id"])
    assert program_assembly.placeholder_only(doc2, next(x for x in doc2["tickets"] if x["id"] == tid2)) is None
    assert orchestrator.heal_review_blocks(root2, doc2) == 0


def test_archie_reads_a_placeholder_clash_as_a_measurement_artefact(tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor, "wallet_left", lambda org_id: 500)
    root, doc = _program(tmp_path)
    pid = doc["id"]
    tid = _tk(root, pid, "Input shaft")["id"]
    _edit(root, pid, lambda d: _a1_block(d, tid))
    doc = store.load(root, pid)
    t = next(x for x in doc["tickets"] if x["id"] == tid)
    trig = [{"kind": "blocked", "ticket": tid, "text": t["run"]["blocked"]}]
    plan = supervisor.rule_plan(doc, trig, {}, 500)
    assert plan["cause"] == "measurement" and "placeholder of Ring gear" in plan["diagnosis"]
    assert "measurement artefact" in plan["diagnosis"]
    assert plan["actions"] == [{"tool": "retry", "ticket": t["key"], "why": plan["actions"][0]["why"]}]
    assert "placeholder of Ring gear" in supervisor.state_view(doc, trig, {}, 500)
    assert "measurement artefact" in supervisor.SUPERVISOR_INSTRUCTIONS
    outcome, _undo = asyncio.run(supervisor.execute(root, pid, plan["actions"][0]))
    assert "back to Fitz" in outcome
    t = _tk(root, pid, "Input shaft")
    assert (t["run"]["next"], t["column"]) == ("fit", "approved")


# ============================================================================ the golden case
def _boxes(sk: dict[str, Any]) -> list[dict[str, Any]]:
    """Final-assembly-like instances from a skeleton: each item's envelope placed at its copies."""
    out = []
    for i, it in sk["items"].items():
        for k in range(len(it["copies"])):
            T = program_assembly.place(sk, i, k)
            sz = it["size"]
            bb = [-sz[0] / 2, -sz[1] / 2, -sz[2] / 2, sz[0] / 2, sz[1] / 2, sz[2] / 2]
            out.append({"name": f"{it['name']}<{k + 1}>", "T": T, "box": golden.world_box(T, bb)})
    return out


def test_the_benchmark_case_loads_and_its_planetary_rows_hold_on_the_hand_layout() -> None:
    case = next(c for c in golden.load_cases(["k_planetary"]))
    assert case["id"] == "planetary" and case["brief"] == BRIEF and case["sim"]["intent_data"]
    g = _graph()
    sk, _ifs = _icd(g)
    insts = _boxes(sk)
    spec = case["expect"]["planetary"][0]
    rows = golden.planetary_rows(1, spec, insts, {"graph": g.dump()})
    bad = [r for r in rows if not r["ok"]]
    assert not bad, bad
    assert {r["id"].split(".")[-1] for r in rows} >= {"coaxial", "assembly", "ratio", "rim", "chain", "spacing",
                                                       "coplanar", "placed", "running"}
    # running gaps by hand: m2 gives max(1, 0.5 x 2) = 1 mm. Ring Y -29.5 .. -3.5 on the -Y wall's inner face, the
    # carrier -2.5 .. 17.5 (1 mm off the ring's end face), sun and planets -26.5 .. -6.5 (3 mm lands), pin ends at
    # -28.5 (1 mm off the wall)
    assert planetary.running_gap(2) == 1.0 and planetary.running_gap(4) == 2.0
    run = next(r for r in rows if r["id"].endswith(".running"))
    assert run["got"] == {"carrier_to_ring": 1.0, "gears_to_ring_faces": 3.0, "pin_end_to_wall": 1.0}, run
    # A1's own layout (approved ICD v1): the turning carrier sat on the fixed ring's end face (ring -29 .. -3,
    # carrier -3 .. 17)
    a1 = next(r for r in golden.planetary_rows(1, spec, _boxes(A1["skeleton"]), {"graph": g.dump()})
              if r["id"].endswith(".running"))
    assert a1["ok"] is False and a1["got"]["carrier_to_ring"] == 0.0
    # the A1 graph as it was (the 6204) fails the rim rule
    data = g.dump()
    for c in data["components"]:
        if c["id"] == "planet_bearing":
            c["params"]["D"]["value"] = 47.0
            c["params"]["designation"]["value"] = 6204
    rim = next(r for r in golden.planetary_rows(1, spec, insts, {"graph": data}) if r["id"].endswith(".rim"))
    assert rim["ok"] is False and rim["got"].startswith("4 mm = 2 m")


# ============================================================================ benchmark A2: rounding in a fit
A2_FIT = [{"id": "IF-19", "kind": "shaft_bore", "a": {"item": "car", "copy": 0}, "b": {"item": "pin", "copy": 2},
           "data": {"d": 20.0, "length": 20.0, "z": [-2.5, 17.5]}}]


def _a2_adoc() -> dict[str, Any]:
    return {"instances": [{"id": "i24", "part": "p_car", "office": {"item": "car", "copy": 0}},
                          {"id": "i19", "part": "p_pin", "office": {"item": "pin", "copy": 2}},
                          {"id": "i18", "part": "p_pin", "office": {"item": "pin", "copy": 1}},
                          {"id": "i9", "part": "p_ring", "office": {"item": "ring", "copy": 0}}]}


def test_a2_pin_in_its_carrier_bore_a_micron_off_is_the_fit_not_a_clash() -> None:
    ad = _a2_adoc()
    # A2: 0.579 mm³ for a 0.0015 mm offset of a Ø20 x 20 press fit (d e L = 20 x 0.0015 x 20 = 0.6)
    assert program_assembly.fit_rounding(ad, A2_FIT, {"a": "i19", "b": "i24", "volume_mm3": 0.579})
    assert program_assembly.fit_rounding(ad, A2_FIT, {"a": "i24", "b": "i19", "volume_mm3": 4.0})  # e = 0.01: the band
    assert not program_assembly.fit_rounding(ad, A2_FIT, {"a": "i19", "b": "i24", "volume_mm3": 4.1})  # beyond it
    # another copy of the pin is not mated by IF-19, and a part with no fit interface is always a clash
    assert not program_assembly.fit_rounding(ad, A2_FIT, {"a": "i18", "b": "i24", "volume_mm3": 0.579})
    assert not program_assembly.fit_rounding(ad, A2_FIT, {"a": "i9", "b": "i24", "volume_mm3": 0.01})
    an = {"interference": {"pairs": [{"a": "i19", "b": "i24", "kind": "interference", "volume_mm3": 0.579},
                                     {"a": "i9", "b": "i24", "kind": "interference", "volume_mm3": 12.0}]}}
    assert [(c["a"], c["b"]) for c in program_assembly._clashes(an, ad, A2_FIT)] == [("i9", "i24")]
    assert len(program_assembly._clashes(an)) == 2  # without the ICD nothing is excused


def test_planet_positions_are_exact_so_pins_sit_on_the_carrier_pattern() -> None:
    _sk, ifs = _icd(_graph())
    pins = [f for f in ifs if f["kind"] == "shaft_bore" and "pressed into the carrier" in f["name"]]
    assert len(pins) == 3
    za = pins[0]["data"]["axis"][1] - 60.0  # the first planet straight above the axis, a = 60
    for f, k in zip(pins, range(3)):
        th = math.pi / 2 + 2 * math.pi * k / 3
        x, z = f["data"]["axis"]
        assert abs(x - 60 * math.cos(th)) < 1e-8 and abs(z - za - 60 * math.sin(th)) < 1e-8


# ============================================================================ benchmark A4: a cap bolted to the lid
def test_a4_a_cap_the_model_bolted_to_the_cover_goes_on_the_housing_and_the_fast_path_holds() -> None:
    from aicad.master import decide

    reply = copy.deepcopy(REPLY["reply"])
    for x in reply["connections"]:
        if x["kind"] == "bolted_joint" and x["guest"] == "output_open_cap":
            x["host"] = "cover"  # A4's reply: the output cap on the cover, every bearing seat in the housing
    g = _graph(reply)
    caps = {x.guest: x.host for x in g.connections if x.kind == "bolted_joint" and g.comp(x.guest).kind == "bearing_cap"}
    assert set(caps.values()) == {g.comp("housing").id}
    assert any("Output open cap is bolted to the" in n for n in g.notes)
    p = gc.to_plan(g, resolved=True)
    d = decide.decide(p, BRIEF, "Planetary")
    assert d["path"] == "fast", d["reasons"]


# ============================================================================ benchmark A5: bolts to the holes
def test_a5_cover_bolts_are_planned_to_the_holes_of_the_lid_grid() -> None:
    from aicad.graph import office as goffice
    from aicad.graph import validate

    g = _graph()
    bolts = next(c for c in g.components if c.kind == "fastener" and "cover" in c.name.lower())
    bolts.qty = 6  # A5's reply: six cover bolts for a grid of four holes
    out = goffice.finish(goffice.OfficePlan(None), g, validate.issues(g))
    parts = {p["name"]: p["qty"] for s in out.plan["subassemblies"] for p in s["parts"]}
    _sk, ifs = _icd(out.graph)
    lid = next(f for f in ifs if f["kind"] == "hole_pattern" and f["data"].get("pattern") == "grid")
    assert parts[bolts.name] == lid["data"]["count"] == 4
    assert any(f"{bolts.name}: 4, one per hole" in n and "(6 were planned)" in n for n in out.graph.notes)
    caps = next(c for c in out.graph.components if c.kind == "fastener" and c is not bolts and "cap" in c.name.lower())
    assert parts[caps.name] == 8  # the caps' circular patterns are not touched
    g2 = _graph(brief=BRIEF + " with 6 cover bolts")  # a count the brief states is kept
    b2 = next(c for c in g2.components if c.kind == "fastener" and "cover" in c.name.lower())
    b2.qty = 6
    assert not goffice.fit_fastener_counts(g2, gc.to_plan(g2, resolved=True), _icd(g2)[1])


# ============================================================================ benchmark A6: no blind caps in a coaxial set
def test_a6_blind_caps_are_left_out_of_a_planetary_set_and_the_screws_follow() -> None:
    from aicad.master import decide

    reply = copy.deepcopy(REPLY["reply"])
    screws = next(x["via"][0] for x in reply["connections"] if x["guest"] == "input_open_cap")
    for c in reply["components"]:
        if c["id"] == screws:
            c["qty"] = 16  # A6: four caps of four screws
    for side in ("input", "output"):  # A6's reply: an open and a blind cap on each shaft
        reply["components"].append({"id": f"{side}_blind_cap", "kind": "bearing_cap",
                                    "name": f"{side.capitalize()} blind cap", "params": {"style": "blind"}})
        reply["connections"].append({"kind": "bolted_joint", "host": "housing", "guest": f"{side}_blind_cap",
                                     "via": [screws]})
    g = _graph(reply)
    assert sorted(c.name for c in g.components if c.kind == "bearing_cap") == ["Input open cap", "Output open cap"]
    assert g.comp(screws).qty == 8
    assert any("Input blind cap, Output blind cap: left out" in n for n in g.notes)
    assert decide.decide(gc.to_plan(g, resolved=True), BRIEF, "Planetary")["path"] == "fast"
