"""Multi-stage planetary gearboxes (founder 2026-11-21: "Build a 2 stage planetary gearbox" failed every time, so the
single-stage foundation was generalised to N stages; golden case m runs the whole program).

Two replies the model really gave, both kept (the model's own components, connections and sizes):

* ``m_planetary_2stage.intent.json`` (the founder's "Multistage"): a ring per stage, an intermediate shaft with the
  stage 1 carrier and the stage 2 sun keyed on it, housing bearings on that shaft, stage 2's ring with the planets'
  30 teeth and its planet bearing seated in the housing wall.
* ``tests/golden/planetary_stages/shared_ring.json`` (his detailed brief): one ring for both stages, the stage 2 sun
  mounted straight on the stage 1 carrier, stage 1 sun 20 / planets 30 and stage 2 sun 20 / planets 30, lip seals.

Hand values: z_ring = z_sun + 2 z_planet in every stage; (z_sun + z_ring) / N whole; a shared ring is sized by stage 1
and stage 2 fits it (z_ring - z_sun even); the rim rule 2.7 m under a z30 m2 planet (root Ø55): 6004 (D 42), rim
6.5 mm; a = m (z_s + z_p) / 2; overall ratio = product of 1 + z_r / z_s.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from aicad.graph import intent, planetary, validate
from aicad.graph import office as goffice
from aicad.master import decide

HERE = Path(__file__).resolve().parent
CASES = HERE.parent / "src" / "aicad" / "eval" / "golden_cases"
SEPARATE = json.loads((CASES / "m_planetary_2stage.intent.json").read_text(encoding="utf-8"))
SHARED = json.loads((HERE / "golden" / "planetary_stages" / "shared_ring.json").read_text(encoding="utf-8"))


def _graph(d: dict[str, Any]):
    g, iss, _qs = intent.compile_reply(copy.deepcopy(d["reply"]), d["name"], d["brief"])
    assert not [i for i in iss if i["severity"] == "error"], iss
    return g


def _teeth(g, st) -> tuple[int, int, int]:
    return tuple(int(g.comp(c).v("teeth")) for c in (st.sun, st.planet, st.ring))  # type: ignore[return-value]


def test_separate_rings_both_stages_sized_and_chained() -> None:
    g = _graph(SEPARATE)
    sets = planetary.find_all(g)
    assert [s.stage for s in sets] == [1, 2]
    s1, s2 = sets
    assert _teeth(g, s1) == (30, 30, 90) and _teeth(g, s2) == (30, 30, 90)  # stage 2's ring was 30
    assert s1.ring != s2.ring and s1.output == s2.input == "inter_shaft" and s1.input == "input_shaft"
    assert s2.output == "output_shaft"
    for st in sets:
        zs, zp, zr = _teeth(g, st)
        assert zr == zs + 2 * zp and (zs + zr) % st.n == 0
        brg = g.comp(st.bearing)
        assert brg.v("designation") == 6004 and planetary.rim(2, zp, brg.v("D")) >= planetary.RIM_MIN_M * 2
        # the planet bearing sits in the planet, never in the housing wall (stage 2's was)
        assert not any(x.kind == "bearing_seat" and x.guest == st.bearing for x in g.connections)
    # the intermediate shaft floats on the planets: no housing bearings on it
    assert not any(x.kind == "bearing_journal" and x.host == "inter_shaft" for x in g.connections)
    total = 1.0
    for st in sets:
        zs, _zp, zr = _teeth(g, st)
        total *= 1 + zr / zs
    assert total == 16.0


def test_shared_ring_and_a_sun_on_the_carrier() -> None:
    g = _graph(SHARED)
    sets = planetary.find_all(g)
    assert len(sets) == 2 and sets[0].ring == sets[1].ring
    (zs1, zp1, zr1), (zs2, zp2, zr2) = _teeth(g, sets[0]), _teeth(g, sets[1])
    assert zr1 == zr2 == zs1 + 2 * zp1 == zs2 + 2 * zp2  # one ring, both stages fit it
    assert (zs1 + zr1) % 3 == 0 and (zs2 + zr2) % 3 == 0
    # the stage 2 sun was mounted straight on the stage 1 carrier: now an intermediate shaft keyed to both
    inter = sets[0].output
    assert inter is not None and inter == sets[1].input and g.comp(inter).kind == "shaft"
    keyed = {x.guest for x in g.connections if x.kind == "keyed_hub" and x.host == inter}
    assert keyed == {sets[0].carrier, sets[1].sun}
    assert all(x.via for x in g.connections if x.kind == "keyed_hub" and x.host == inter)  # keys added
    assert not any({x.host, x.guest} == {sets[0].carrier, sets[1].sun} for x in g.connections)
    assert any("Intermediate shaft" in n for n in g.notes)


def test_both_two_stage_designs_lay_out_on_the_fast_path() -> None:
    for d in (SEPARATE, SHARED):
        g = _graph(d)
        out = goffice.finish(goffice.OfficePlan(None), g, validate.issues(g))
        assert out.plan is not None and not out.plan["graph"]["check"], out.plan["graph"]["check"]
        dec = decide.decide(out.plan, d["brief"], d["name"])
        assert dec["path"] == "fast", dec["reasons"]
    # the separate-ring layout: stage 2's ring sits against stage 1's, both stages' planets 120° apart on a = 60
    g = _graph(SEPARATE)
    out = goffice.finish(goffice.OfficePlan(None), g, validate.issues(g))
    from aicad.graph import compile as gc

    _sk, ifs = gc.to_icd(out.graph, gc.to_plan(out.graph, resolved=True))
    faces = [f for f in ifs if f["kind"] == "face" and "ring" in f["name"].lower()]
    assert any("ring of the stage before" in f["name"] or "Stage 1 ring gear" in f["name"] and "Stage 2 ring gear"
               in f["name"] for f in faces), [f["name"] for f in faces]
    meshes = [f for f in ifs if f["kind"] == "gear_mesh"]
    assert len(meshes) == 12  # 2 stages x 3 planets x (sun mesh + ring mesh)
    assert {f["data"]["centre_distance"] for f in meshes} == {60.0}


def test_nuts_and_washers_follow_the_bolts_to_the_grid() -> None:
    g = _graph(SHARED)
    out = goffice.finish(goffice.OfficePlan(None), g, validate.issues(g))
    q = {p["name"]: p["qty"] for s in out.plan["subassemblies"] for p in s["parts"]}
    bolts = next(v for k, v in q.items() if k.lower().startswith("cover bolt") and "nut" not in k.lower()
                 and "washer" not in k.lower())
    assert q["Cover bolt nut"] == bolts and q["Cover bolt washer"] == 2 * bolts


def test_a_stated_ratio_is_split_over_the_stages() -> None:
    assert planetary._stage_ratio("about 25:1 (two stages of about 5:1 each)", 2) == 5.0
    assert abs(planetary._stage_ratio("a 2 stage planetary gearbox, 20:1", 2) - 20 ** 0.5) < 1e-9
    assert planetary._stage_ratio("single stage 4:1", 1) == 4.0
    assert planetary._stage_ratio("two stages, 400:1", 2) is None  # 20:1 a stage: out of range, said by the rules
