"""WORKLIST 46 golden mechanism suite: the case format, the expectation engine (hand-made snapshots, no CAD), the
history store, the God-mode admin endpoint, and the CI hook: the simulated suite for the two fast cases.

The full suite is a separate command (``uv run aicad golden``, a few minutes, one case at a time).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aicad.eval import golden


# a 4 x 4 row-major transform: identity rotation, translation (x, y, z)
def _T(x: float = 0, y: float = 0, z: float = 0) -> list[float]:
    return [1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1]


def _inst(name: str, T: list[float], bbox: list[float]) -> dict[str, Any]:
    return {"name": name, "T": T, "kind": "real", "bin": False, "fastener": False, "box": golden.world_box(T, bbox)}


def test_every_case_loads_with_its_plan() -> None:
    cases = golden.load_cases()
    ids = [c["id"] for c in cases]
    assert {"keyed-gear", "gear-pair", "reducer", "bracket", "roller", "linear-stage", "hinge-arm", "r-test5",
            "r-shaft-gear"} <= set(ids)
    for c in cases:
        sim = c["sim"]
        assert "plan_data" in sim or sim.get("planner", "standard") == "standard", c["id"]
        if "plan_data" in sim:  # the replayed plan is one the planner accepts, with the part lines the case expects
            from aicad.office import planner

            plan = planner.normalise_plan(sim["plan_data"], "archie")
            assert plan is not None, c["id"]
            lines = [p for s in plan["subassemblies"] for p in s["parts"]]
            assert len(lines) == c["expect"]["parts"], c["id"]
            assert sum(int(p["qty"]) for p in lines) == c["expect"]["pieces"], c["id"]
        assert c["limits"].get("tokens") and c["limits"].get("wall_simulated_s"), c["id"]
    assert [c["id"] for c in golden.load_cases(["a", "R1"])] == ["keyed-gear", "r-test5"]
    with pytest.raises(golden.CaseError):
        golden.load_cases(["nope"])


def test_kinds_in_the_cases_are_the_head_nouns() -> None:
    """The kinds each case expects are read by hand from its plan's part names; the office reads them the same way."""
    from aicad.office import scope

    for c in golden.load_cases():
        if "plan_data" not in c["sim"] or "kinds" not in c["expect"]:
            continue
        got: dict[str, int] = {}  # pieces of each kind
        for s in c["sim"]["plan_data"]["subassemblies"]:
            for p in s["parts"]:
                k = scope.kind_of(p["name"])
                if k:
                    got[k] = got.get(k, 0) + int(p["qty"])
        assert got == c["expect"]["kinds"], (c["id"], got)


def test_world_boxes_gaps_and_loose_parts() -> None:
    # a 10 x 10 x 10 box turned 90 deg about Z (x -> y) and moved to (100, 0, 0): x 95..105 from y -5..5
    T = [0, -1, 0, 100, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    assert golden.world_box(T, [0, -5, -5, 20, 5, 5]) == [95, 0, -5, 105, 20, 5]
    a, b = [0, 0, 0, 10, 10, 10], [13, 0, 0, 20, 10, 10]
    assert golden.gap(a, b) == 3 and golden.gap(a, [5, 5, 5, 6, 6, 6]) == 0
    assert golden.gap(a, [13, 14, 0, 20, 20, 10]) == pytest.approx(5)  # (3, 4, 0): 5
    insts = [_inst("Plate", _T(), [0, 0, 0, 10, 10, 10]), _inst("Block", _T(10, 0, 0), [0, 0, 0, 5, 5, 5]),
             _inst("Stray", _T(0, 40, 0), [0, 0, 0, 1, 1, 1])]
    assert golden.loose_names(insts) == ["Stray"]
    assert golden.loose_names(insts[:1]) == []  # a lone part is never loose


def _snap(insts: list[dict[str, Any]], **metrics: Any) -> dict[str, Any]:
    m = {"wall_s": 12.0, "tokens": 0, "light": True, "parts": 3, "pieces": 3, "subs": 1, "tickets": 5,
         "instances": len(insts), "clashes": 0, "binned": 0, "loose": 0, "placeholders": 0, "blocked": 0,
         "icd_problems": 0, "conformance": {"ok": 6, "total": 6}, "direct": 2, "supervisor": 0, **metrics}
    return {"status": "complete", "metrics": m, "kinds": {"shaft": 1, "gear": 1, "key": 1}, "instances": insts,
            "tickets": [{"title": "Parallel key", "reuse_code": "parallel_key"}, {"title": "Spur gear", "reuse_code": ""}],
            "stacks": [{"style": "shcs", "size": 6}, {"style": "shcs", "size": 6}, {"style": "hex_bolt", "size": 8}]}


# the founder's keyed gear as the office lays it out (docs/reports/office-small.md): shaft Y -22..58 (Ø20 seat,
# Ø26 step), gear m2 x 30 Y -20..0 (tip Ø64), key 6 x 6 x 18 at (6.5, -10, 0) in X 6.5..12.5, Y -19..-1
KEYED = [_inst("Stepped shaft", _T(), [-13, -22, -13, 13, 58, 13]),
         _inst("Spur gear", _T(0, -10, 0), [-32, -10, -32, 32, 10, 32]),
         _inst("Parallel key", _T(6.5, -10, 0), [0, -9, -3, 6, 9, 3])]


def test_the_keyed_gear_case_passes_on_its_hand_layout() -> None:
    case = golden.load_cases(["keyed-gear"])[0]
    rows = golden.evaluate(case, _snap(KEYED), "simulated")
    bad = [r for r in rows if r["ok"] is False]
    assert not bad, bad
    by = {r["id"]: r for r in rows}
    assert by["at.1"]["got"] == [[6.5, -10.0, 0.0]] and by["span.1"]["got"] == [-20.0, 0.0]
    assert by["within.1"]["got"] == [[-19.0, -1.0]] and by["touch.1"]["got"] == 0.0
    assert by["tokens"]["ok"] is None  # simulated: metering, not spend
    assert golden.passed(rows)
    # live: the sizes Archie chooses may differ, so the numbers that depend on them don't apply; the relations do
    ids = {r["id"] for r in golden.evaluate(case, _snap(KEYED, tokens=12), "live")}
    assert "at.1" not in ids and "span.1" not in ids and {"within.1", "touch.1", "tokens"} <= ids


def test_each_failure_is_reported_with_what_was_measured() -> None:
    case = golden.load_cases(["keyed-gear"])[0]
    moved = [KEYED[0], KEYED[1], _inst("Parallel key", _T(6.5, 30, 0), [0, -9, -3, 6, 9, 3])]  # key out of the hub
    snap = _snap(moved, clashes=2, binned=1, light=False, wall_s=500.0)
    snap["kinds"] = {"shaft": 1, "gear": 1, "key": 1, "housing": 1}
    snap["status"] = "planning"
    bad = {r["id"]: r for r in golden.evaluate(case, snap, "simulated") if r["ok"] is False}
    # the listed kinds still match (one each); the extra housing is what no_extras reports
    assert set(bad) == {"complete", "light", "clashes", "binned", "no_extras", "at.1", "within.1", "wall"}
    assert bad["no_extras"]["got"] == {"housing": 1} and bad["at.1"]["got"] == [[6.5, 30.0, 0.0]]
    assert bad["within.1"]["got"] == [[21.0, 39.0]] and bad["clashes"]["got"] == 2
    # a clash check that did not finish never passes as 0
    rows = golden.evaluate(case, _snap(KEYED, clashes=None), "simulated")
    assert next(r for r in rows if r["id"] == "clashes")["ok"] is False
    # a live run over its token cap fails
    rows = golden.evaluate(case, _snap(KEYED, tokens=31), "live")
    assert next(r for r in rows if r["id"] == "tokens")["ok"] is False


def test_distance_pick_stacks_reuse_count_and_auto_axis() -> None:
    # the gear pair: pinion tip Ø44 at X 0, gear tip Ø124 at X 80, shafts along +Y, faces Y -10..10
    insts = [_inst("Pinion", _T(), [-22, -10, -22, 22, 10, 22]), _inst("Gear", _T(80, 0, 0), [-62, -10, -62, 62, 10, 62]),
             _inst("Input shaft", _T(), [-10, -60, -10, 10, 60, 10]), _inst("Output shaft", _T(80, 0, 0), [-10, -60, -10, 10, 60, 10])]
    case = {"id": "t", "title": "t", "brief": "t", "limits": {}, "expect": {
        "distance": [{"a": {"kind": "gear", "pick": "smallest"}, "b": {"kind": "gear", "pick": "largest"},
                      "value": 80.0, "plane": "xz"},
                     {"a": {"kind": "shaft"}, "value": 80.0, "plane": "xz"}],  # the two shafts, across their axis
        "same_span": [{"a": {"kind": "gear", "pick": "smallest"}, "b": {"kind": "gear", "pick": "largest"}, "axis": "y"}],
        "within": [{"inner": {"name": "Pinion"}, "outer": {"kind": "shaft"}, "axis": "y", "hull": True}],
        # "auto" is the longest axis of the whole assembly's box: here X (the gears' tips, -62 .. 142), not the shafts
        "along": [{"kind": "shaft", "axis": "auto"}, {"kind": "shaft", "axis": "y"}],
        "stacks": [{"style": "shcs", "size": 6, "n": 2}, {"style": "hex_bolt", "size": 8, "n": 4}],
        "reuse": [{"title": "Parallel key", "code": "parallel_key"}, {"title": "Spur gear", "code": ""}],
        "count": [{"name": "(?i)shaft", "n": 2}]}}
    rows = {r["id"]: r for r in golden.evaluate(case, _snap(insts), "simulated")}
    assert rows["distance.1"]["ok"] and rows["distance.1"]["got"] == 80.0
    assert rows["distance.2"]["ok"] and rows["same_span.1"]["ok"] and rows["within.1"]["ok"]
    assert rows["stacks.1"]["ok"] and not rows["stacks.2"]["ok"] and rows["stacks.2"]["got"] == 1
    assert rows["reuse.1"]["ok"] and rows["reuse.2"]["ok"] and rows["count.1"]["ok"]
    assert not rows["along.1"]["ok"] and rows["along.1"]["got"] == ["Y", "Y"] and rows["along.2"]["ok"]


def test_history_is_append_only_jsonl_and_public_rows_carry_no_model_names(tmp_path: Path) -> None:
    rec = {"schema": golden.SCHEMA, "run_id": "r1", "at": "2026-11-20T10:00:00Z", "mode": "simulated", "case": "a",
           "title": "A", "passed": True, "status": "complete", "metrics": {"wall_s": 1}, "expectations": [],
           "sha": "abc", "routing": {"planner": "opus"}, "routing_id": golden.routing_id({"planner": "opus"}),
           "detail": {"x": 1}}
    golden.append(rec, tmp_path)
    golden.append({**rec, "run_id": "r2"}, tmp_path)
    (tmp_path / "runs.jsonl").open("a", encoding="utf-8").write("not json\n")
    rs = golden.read(tmp_path)
    assert [r["run_id"] for r in rs] == ["r1", "r2"]
    pub = golden.public(rs[0])
    assert "routing" not in pub and "detail" not in pub and len(pub["routing_id"]) == 6
    assert "opus" not in json.dumps(pub)


def test_admin_dashboard_endpoint_is_god_mode_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    from test_platform import ADMIN, PW, signup

    from aicad.platform import config
    from aicad.platform.routers import auth as auth_router

    hist = tmp_path / "hist"
    golden.append({"schema": golden.SCHEMA, "run_id": "r1", "at": "2026-11-20T10:00:00Z", "mode": "simulated",
                   "case": "keyed-gear", "title": "t", "passed": True, "status": "complete", "metrics": {},
                   "expectations": [], "sha": "abc", "routing": {"planner": "opus"}, "routing_id": "abcdef"}, hist)
    monkeypatch.setenv("FW_GOLDEN_DIR", str(hist))
    monkeypatch.setenv("FW_ADMIN_PASSWORD", PW)
    for env in ("development", "production"):
        auth_router._attempts.clear()
        config.override_settings(config.Settings(
            env=env, data_dir=tmp_path / env, database_url=f"sqlite:///{(tmp_path / f'{env}.sqlite').as_posix()}",
            app_url="http://testserver", superadmin_emails=(ADMIN,), stripe_secret_key="", trial_tokens=300))
        from aicad.platform.app import create_app

        with TestClient(create_app()) as c:
            c.headers.update({"X-FW-CSRF": "1"})
            if env == "development":
                signup(c, "someone@x.com")
                assert c.get("/api/admin/golden").status_code == 403
                c.post("/api/auth/logout")
            assert c.post("/api/auth/login", json={"email": ADMIN, "password": PW}).status_code == 200
            r = c.get("/api/admin/golden")
            if env == "production":
                assert r.status_code == 404
                continue
            assert r.status_code == 200, r.text
            body = r.json()
            assert "keyed-gear" in [x["id"] for x in body["cases"]]
            assert [x["run_id"] for x in body["runs"]] == ["r1"] and "routing" not in body["runs"][0]


# ---------------------------------------------------------------------------- CI hook: the two fast cases, simulated
def test_simulated_suite_fast_cases(tmp_path: Path) -> None:
    """The cases marked ``fast`` (the founder's keyed gear and his Test 5 regression) through the Design Office with
    simulated agents: every expectation holds. One case at a time, workers reaped after each."""
    from aicad.eval import golden_run

    cases = [c for c in golden.load_cases() if c.get("fast")]
    assert [c["id"] for c in cases] == ["keyed-gear", "r-test5"]
    recs = golden_run.run_suite(cases, "simulated", work=tmp_path, history=tmp_path / "hist", log=lambda *a: None)
    for r in recs:
        bad = [e for e in r.get("expectations") or [] if e["ok"] is False]
        assert r["passed"], (r["case"], r.get("error"), r.get("stopped"), bad)
        assert r["metrics"]["tokens"] == 0 and r["mode"] == "simulated" and r["sha"]
    assert len(golden.read(tmp_path / "hist")) == 2
