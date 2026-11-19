"""ASM-023 pair cache: interference / clearance results per (snapshot a, snapshot b, relative placement) on disk.

Fixture: a small gearbox of Toolbox parts (kernel in-process; the worker protocol is run through ``worker._handle``
with JSON round trips, as the real pipe does): an 18 / 36 tooth m2 spur pair at the exact centre distance 54 mm
(near pair, no overlap), a shaft through the pinion's Ø8 bore (overlap), two flanges overlapping, a mate between
the gears. Checks: cached == uncached exactly, the old whole-assembly worker op agrees, only changed pairs are
recomputed (counted pair evaluations, never wall time), a moved instance or a new snapshot is a miss, a timed-out
chunk keeps the finished chunks.
"""

from __future__ import annotations

import asyncio
import copy
import json
import math
from pathlib import Path
from typing import Any

import pytest

from aicad.assembly import pairs, xform

ORG = "orgpairs"


@pytest.fixture()
def inproc(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    from aicad.assembly import service
    from aicad.assembly import worker as aworker

    calls: list[dict[str, Any]] = []

    async def call(org_id: str, req: dict[str, Any], timeout: float = 180) -> Any:
        calls.append({"op": req["op"], "n": len(req.get("jobs") or []), "timeout": timeout})
        return json.loads(json.dumps(aworker._handle(json.loads(json.dumps(req)))))

    monkeypatch.setattr(service, "_call", call)
    pairs.reset_stats()
    return calls


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture()
def gearbox(tmp_path: Path, inproc: list[dict[str, Any]]) -> tuple[Path, dict[str, Any]]:
    from aicad.assembly import service, store

    root = tmp_path / "assemblies" / ORG
    za, zb, m = 18, 36, 2.0
    cd = m * (za + zb) / 2
    kp = _run(service.ensure_toolbox_part(root, ORG, "spur_gear", {"M": m, "Z": za, "B": 10, "BORE": 8}))
    kw = _run(service.ensure_toolbox_part(root, ORG, "spur_gear", {"M": m, "Z": zb, "B": 10, "BORE": 10}))
    kf = _run(service.ensure_toolbox_part(root, ORG, "flange", {"OD": 60, "T": 8, "BORE": 20, "N": 4, "HOLE": 6.6,
                                                                "PCD": 44}))
    ks = _run(service.ensure_toolbox_part(root, ORG, "dowel", {"D": 10, "L": 30}))
    doc = store.new_doc("Gearbox", ORG, "u1", None)
    pb = 360.0 / zb
    phase = (180.0 - 0.5 * pb) % pb
    pin = service.add_instance(root, doc, kp, T=xform.to12(xform.ident()), name="Pinion")
    whl = service.add_instance(root, doc, kw, T=xform.to12(xform.make(xform.rot([0, 0, 1], math.radians(phase)),
                                                                      [cd, 0, 0])), name="Wheel")
    service.add_instance(root, doc, ks, T=xform.to12(xform.translate((0, 0, -10))), name="Pin")
    service.add_instance(root, doc, kf, T=xform.to12(xform.translate((0, 120, 0))), name="Flange")
    service.add_instance(root, doc, kf, T=xform.to12(xform.translate((10, 125, 3))), name="Flange")
    doc["mates"].append({"id": "m1", "type": "coincident", "a": {"inst": pin["id"]}, "b": {"inst": whl["id"]}})
    store.save(root, doc)
    return root, doc


def _strip(res: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in res.items() if k != "stats"}


def test_cached_equals_uncached_and_the_old_check(gearbox: tuple[Path, dict[str, Any]]) -> None:
    from aicad.assembly import geometry, service

    root, doc = gearbox
    near = 12.0
    cold = _run(service.check_pairs(root, ORG, doc, near_mm=near, use_cache=False))
    first = _run(service.check_pairs(root, ORG, doc, near_mm=near))
    warm = _run(service.check_pairs(root, ORG, doc, near_mm=near))
    assert first["stats"]["computed"] > 0 and warm["stats"]["computed"] == 0
    assert warm["stats"]["cached"] == first["stats"]["computed"]
    assert _strip(cold) == _strip(first) == _strip(warm)          # identical numbers, not just close
    inter = {(p["a"], p["b"]): p for p in warm["interference"]["pairs"]}
    names = {i["id"]: i["name"] for i in doc["instances"]}
    got = {(names[a], names[b]) for a, b in inter}
    assert got == {("Pinion", "Pin"), ("Flange", "Flange")}
    # the whole-assembly check the worker ran before ASM-023: same pairs, same volumes and distances
    insts = service.worker_instances(root, doc)
    old_i = geometry.interference(insts)
    hits = {(p["a"], p["b"]): p["center"] for p in old_i["pairs"]}
    mates = [(m["a"]["inst"], m["b"]["inst"], "mate") for m in doc["mates"]]
    old_c = geometry.clearance(insts, mates, near, overlaps=hits)
    assert {(p["a"], p["b"]) for p in old_i["pairs"]} == set(inter)
    for p in old_i["pairs"]:
        assert inter[(p["a"], p["b"])]["volume_mm3"] == pytest.approx(p["volume_mm3"], rel=1e-7)
        assert inter[(p["a"], p["b"])]["kind"] == p["kind"]
    rows = {(r["a"], r["b"]): r for r in warm["clearance"]["rows"]}
    assert set(rows) == {(r["a"], r["b"]) for r in old_c["rows"]}
    for r in old_c["rows"]:
        assert rows[(r["a"], r["b"])]["distance_mm"] == pytest.approx(r["distance_mm"], abs=1e-6)
        assert rows[(r["a"], r["b"])]["why"] == r["why"]
    # the pin in the Ø8 bore: overlap π (5² − 4²) × 10 (the gear face width) — exact, by hand
    pp = next(v for (a, b), v in inter.items() if {names[a], names[b]} == {"Pinion", "Pin"})
    assert pp["volume_mm3"] == pytest.approx(math.pi * (25 - 16) * 10, rel=1e-6)


def test_only_changed_pairs_are_recomputed(gearbox: tuple[Path, dict[str, Any]], inproc: list[dict[str, Any]]) -> None:
    from aicad.assembly import service

    root, doc = gearbox
    a1 = _run(service.analyse(root, ORG, doc))
    assert a1["pairs"]["computed"] > 0
    a2 = _run(service.analyse(root, ORG, doc))
    assert a2["pairs"]["computed"] == 0
    assert {k: v for k, v in a1.items() if k not in ("at", "pairs")} == {k: v for k, v in a2.items()
                                                                         if k not in ("at", "pairs")}
    # move the pin out of the bore: only pairs involving the pin are evaluated again
    moved = copy.deepcopy(doc)
    pin = next(i for i in moved["instances"] if i["name"] == "Pin")
    pin["T"] = xform.to12(xform.translate((0, 0, -40)))
    a3 = _run(service.analyse(root, ORG, moved))
    involving = [r for r in a3["clearance"]["rows"] if pin["id"] in (r["a"], r["b"])]
    assert 0 < a3["pairs"]["computed"] <= len(involving) + 1
    assert not any(pin["id"] in (p["a"], p["b"]) for p in a3["interference"]["pairs"] if p["kind"] == "interference")
    # the focused check after a swap / a stack insert reuses what the whole check stored
    n = pairs.STATS["computed"]
    _run(service.stack_clashes(root, ORG, doc, [doc["instances"][0]["id"]]))
    assert pairs.STATS["computed"] == n
    # the whole assembly moved rigidly: every relative placement is the same, every pair is a hit (a quarter turn,
    # so world boxes, and with them the candidate pairs, stay the same)
    shifted = copy.deepcopy(doc)
    M = xform.make(xform.rot([0, 0, 1], math.radians(90)), [100, -20, 7])
    for i in shifted["instances"]:
        i["T"] = xform.to12(M @ xform.from12(i["T"]))
    a4 = _run(service.analyse(root, ORG, shifted))
    assert a4["pairs"]["computed"] == 0
    assert a4["interference"]["count"] == a2["interference"]["count"]
    for p, q in zip(a2["interference"]["pairs"], a4["interference"]["pairs"], strict=True):
        assert p["volume_mm3"] == q["volume_mm3"]
        assert xform.pt(M, p["center"]) == pytest.approx(q["center"], abs=2e-4)


def test_new_snapshot_and_moved_instance_are_misses(gearbox: tuple[Path, dict[str, Any]]) -> None:
    from aicad.assembly import service

    root, doc = gearbox
    _run(service.check_pairs(root, ORG, doc))
    kw2 = _run(service.ensure_toolbox_part(root, ORG, "spur_gear", {"M": 2, "Z": 36, "B": 12, "BORE": 10}))
    d2 = copy.deepcopy(doc)
    whl = next(i for i in d2["instances"] if i["name"] == "Wheel")
    whl["part"] = kw2
    r = _run(service.check_pairs(root, ORG, d2))
    insts = service.worker_instances(root, d2)
    boxes = {i["id"]: pairs.world_box(i) for i in insts}
    mine = sum(1 for i in insts if i["id"] != whl["id"] and not (
        any(boxes[i["id"]][0] > boxes[whl["id"]][1] + 1e-6) or any(boxes[whl["id"]][0] > boxes[i["id"]][1] + 1e-6)))
    assert mine >= 1 and r["stats"]["computed"] == mine               # every pair with the new wheel, nothing else
    # by key: a canonical key has the snapshot identity and the relative placement
    Ta, Tb = xform.ident(), xform.translate((1, 2, 3))
    s, _rel, k = pairs.canon("x|1|2", Ta, "y|1|2", Tb)
    s2, _rel2, k2 = pairs.canon("y|1|2", Tb, "x|1|2", Ta)
    assert k == k2 and s != s2                                       # (a, b) and (b, a) share an entry
    assert pairs.canon("x|1|2", Ta, "y|1|2", xform.translate((1, 2, 3.00001)))[2] != k   # moved 10 µm: a miss
    assert pairs.canon("x|1|2", Ta, "y|1|2", xform.translate((1, 2, 3 + 1e-8)))[2] == k  # below the rounding
    assert pairs.canon("x|1|3", Ta, "y|1|2", Tb)[2] != k                                  # re-prepared snapshot


def test_a_failed_chunk_keeps_the_finished_ones(gearbox: tuple[Path, dict[str, Any]], inproc: list[dict[str, Any]],
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    from aicad.assembly import service
    from aicad.assembly import worker as aworker

    root, doc = gearbox
    monkeypatch.setattr(pairs, "CHUNK", 2)
    sent = {"n": 0}

    async def flaky(org_id: str, req: dict[str, Any], timeout: float = 180) -> Any:
        if req["op"] == "pairs":
            sent["n"] += 1
            assert timeout == pairs.BASE_TIMEOUT_S + pairs.PER_PAIR_S * len(req["jobs"])  # scales with the chunk
            if sent["n"] == 2:
                raise service.WorkerError("timed out after 100 s")
        return json.loads(json.dumps(aworker._handle(json.loads(json.dumps(req)))))

    monkeypatch.setattr(service, "_call", flaky)
    with pytest.raises(service.WorkerError):
        _run(service.check_pairs(root, ORG, doc, near_mm=12.0))
    r = _run(service.check_pairs(root, ORG, doc, near_mm=12.0))
    total = r["stats"]["computed"] + r["stats"]["cached"]
    assert r["stats"]["cached"] == 2 and r["stats"]["computed"] == total - 2   # the first chunk was kept


def test_prune_keeps_the_cache_bounded(tmp_path: Path) -> None:
    import os
    import time

    for k in range(30):
        pairs.put(tmp_path, "clr", f"k{k}", {"d": float(k), "p1": [0, 0, 0], "p2": [0, 0, 0]})
        p = pairs._path(tmp_path, "clr", f"k{k}")
        t = time.time() - 1000 + k
        os.utime(p, (t, t))
    assert pairs.get(tmp_path, "clr", "k3") is not None                # read: now the most recently used
    removed = pairs.prune(tmp_path, max_entries=20)
    assert removed == 30 - int(20 * pairs.PRUNE_TO)
    assert pairs.get(tmp_path, "clr", "k3") is not None and pairs.get(tmp_path, "clr", "k0") is None


def test_block_dof_analysis_equals_the_whole_jacobian(monkeypatch: pytest.MonkeyPatch) -> None:
    """PD-71: a large assembly's degrees of freedom are analysed per fastener stack (leaf block) plus the parts; the
    result must be the whole-J SVD's. Fixture: a fixed base, a block on it (coincident + concentric: spin left), and
    stacks of two pins on the block's axis (concentric + seated: each spins) plus one pin also tied by an angle
    mate to the base (fully defined)."""
    import numpy as np

    from aicad.assembly import solver

    top = solver.Ref("plane", (0.0, 0.0, 10.0), (0.0, 0.0, 1.0))
    axis = solver.Ref("axis", (30.0, 20.0, 0.0), (0.0, 0.0, 1.0), 4.0)
    side = solver.Ref("plane", (50.0, 0.0, 5.0), (1.0, 0.0, 0.0))
    bottom = solver.Ref("plane", (0.0, 0.0, 0.0), (0.0, 0.0, -1.0))
    up = solver.Ref("plane", (0.0, 0.0, 20.0), (0.0, 0.0, 1.0))
    bax = solver.Ref("axis", (0.0, 0.0, 10.0), (0.0, 0.0, 1.0), 4.0)
    bside = solver.Ref("plane", (10.0, 0.0, 10.0), (1.0, 0.0, 0.0))
    insts = {"base": solver.Inst("base", xform.ident(), fixed=True, ref_point=(0, 0, 5)),
             "blk": solver.Inst("blk", xform.translate((30, 20, 10)), ref_point=(0, 0, 10))}
    mates = [solver.MateSpec("m1", "coincident", "base", top, "blk", bottom),
             solver.MateSpec("m2", "concentric", "base", axis, "blk", bax)]
    blocks = {}
    for k in range(4):
        a, b = f"p{k}a", f"p{k}b"
        insts[a] = solver.Inst(a, xform.translate((30, 20, 30 + 20 * k)), ref_point=(0, 0, 10))
        insts[b] = solver.Inst(b, xform.translate((30, 20, 50 + 20 * k)), ref_point=(0, 0, 10))
        blocks |= {a: f"g{k}", b: f"g{k}"}
        mates += [solver.MateSpec(f"c{k}a", "concentric", "blk", bax, a, bax),
                  solver.MateSpec(f"c{k}b", "concentric", a, bax, b, bax),
                  solver.MateSpec(f"s{k}b", "coincident", a, up, b, bottom)]
        if k == 0:
            mates.append(solver.MateSpec("ang", "angle", "base", side, b, bside, 0.0))
    whole = solver.solve(insts, mates, L=60)
    monkeypatch.setattr(solver, "BLOCKS_FROM_COLS", 0)
    split = solver.solve(insts, mates, L=60, blocks=blocks)
    assert whole.insts == split.insts
    assert (whole.dof, whole.redundant, whole.status) == (split.dof, split.redundant, split.status)
    assert whole.dof > 0 and any(s.spin for s in whole.insts.values())
    for k, T in whole.poses.items():
        assert np.allclose(T, split.poses[k], atol=1e-12)
