"""Live comparison on the three golden cases: the new path (intent -> design graph -> plan / ICD) against the old path
(Archie's free-text plan -> scope post-check -> ICD), one live model call per case and path, scored by the same
deterministic checks. Writes docs/reports/design-graph/live/<case>.json and tests/golden/design_graph/<case>.live.json
(the live intent reply, replayed by tests/test_design_graph.py with the stub provider).

Run from the worktree: ``uv run python docs/reports/design-graph/live_intent.py [case ...] [--old] [--new]``.
Uses the development login (PD-09); costs about 30 platform tokens for all six calls.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT / "tests" / "golden" / "design_graph"
OUT = Path(__file__).resolve().parent / "live"

EXPECT: dict[str, dict[str, Any]] = {
    # what a correct plan has, by scope kind (office/scope.kind_of on the part names); "absent" must not appear
    "keyed_gear": {"kinds": {"shaft": 1, "gear": 1, "key": 1}, "absent": {"housing", "bearing", "support", "plate"},
                   "mesh": None},
    "gear_pair": {"kinds": {"shaft": 2, "gear": 2, "bearing": 4}, "absent": {"housing", "support", "plate", "cap"},
                  "mesh": 80.0},
    "reducer": {"kinds": {"shaft": 2, "gear": 2, "bearing": 4, "housing": 1}, "absent": set(), "mesh": 80.0},
}


def score(case: str, plan: dict[str, Any] | None, brief: str) -> dict[str, Any]:
    """The same deterministic checks for both paths: parts by kind, exclusions, ICD problems, the mesh, direct builds."""
    from aicad.graph.compile import plan_parts
    from aicad.office import direct, icd, scope

    if plan is None:
        return {"plan": False}
    want = EXPECT[case]
    parts = plan_parts(plan)
    kinds: dict[str, int] = {}
    for p in parts:
        k = ("gear" if p["family"] == "gear" else
             "housing" if "housing" in p["name"].lower() and "cover" not in p["name"].lower() else
             scope.kind_of(p["name"]) or "?")
        kinds[k] = kinds.get(k, 0) + int(p["qty"])
    missing = {k: n for k, n in want["kinds"].items() if kinds.get(k, 0) < n}
    unwanted = sorted(k for k in kinds if k in want["absent"])
    sk, ifs = icd.build(parts, brief)
    mesh = [f["data"]["centre_distance"] for f in ifs if f["kind"] == "gear_mesh"]
    doc = {"skeleton": sk, "icd": {"version": 1, "status": "approved", "interfaces": ifs}, "brief": brief,
           "items": [{"id": p["id"], "name": p["name"], "description": p["description"]} for p in parts]}
    designed = [p for p in parts if p["family"] != "standard"]
    paths = {p["name"]: direct.plan(doc, {"kind": "part", "item_id": p["id"], "title": p["name"]})["path"]
             for p in designed}
    ok = not missing and not unwanted and not icd.problems(sk, ifs) and (
        want["mesh"] is None or mesh == [want["mesh"]])
    return {"plan": True, "parts": [f"{p['qty']} x {p['name']}" for p in parts], "kinds": kinds,
            "missing": missing, "unwanted": unwanted, "layout": sk["layout"], "problems": icd.problems(sk, ifs),
            "mesh": mesh, "direct": paths, "n_direct": sum(1 for v in paths.values() if v == "direct"),
            "n_designed": len(designed), "correct": ok}


async def new_path(case: str, d: dict[str, Any]) -> dict[str, Any]:
    from aicad.graph import office as goffice

    t0 = time.perf_counter()
    out = await goffice.plan(None, d["name"], d["brief"])
    wall = round(time.perf_counter() - t0, 2)
    res: dict[str, Any] = {"wall_s": wall, "error": out.error, "cost_usd": out.cost_usd, "meta": out.meta,
                           "questions": out.questions, "notes": out.graph.notes if out.graph else [],
                           "raw_reply": out.reply}
    if out.graph is not None:
        res["graph"] = out.graph.dump()
    res["score"] = score(case, out.plan, d["brief"])
    res["check"] = (out.plan or {}).get("graph", {}).get("check")
    return res


def rescore_new(case: str, d: dict[str, Any], rec: dict[str, Any]) -> dict[str, Any]:
    """The recorded live reply through the current deterministic middle (no model call): code fixes made after the
    live run are measured on the same reply."""
    from aicad.graph import intent
    from aicad.graph import office as goffice

    new = dict(rec["new"])
    g, iss, _qs = intent.compile_reply(new["raw_reply"], d["name"], d["brief"])
    out = goffice.finish(goffice.OfficePlan(None), g, iss)
    new.update(score=score(case, out.plan, d["brief"]), check=(out.plan or {}).get("graph", {}).get("check"),
               limits=(out.plan or {}).get("graph", {}).get("limits"), questions=out.questions, graph=g.dump(),
               notes=g.notes, error=out.error, rescored=True)
    return new


async def old_path(case: str, d: dict[str, Any]) -> dict[str, Any]:
    from aicad.llm import metering as llm_metering
    from aicad.office import planner

    t0 = time.perf_counter()
    with llm_metering.capture() as calls:
        text, usd = await planner.run_agent(OUT, d["name"], d["brief"])
    wall = round(time.perf_counter() - t0, 2)
    plan = planner.parse_plan(text)
    note = None
    if plan is not None:
        plan, note = planner.finish(plan, d["name"], d["brief"])
    return {"wall_s": wall, "cost_usd": usd, "tokens": calls[0].usage.as_dict() if calls else {},
            "model": calls[0].model if calls else None, "note": note, "text": text,
            "score": score(case, plan, d["brief"])}


async def main(cases: list[str], do_new: bool, do_old: bool, rescore: bool = False) -> None:
    from aicad.platform import metering

    OUT.mkdir(parents=True, exist_ok=True)
    for case in cases:
        d = json.loads((GOLDEN / f"{case}.json").read_text(encoding="utf-8"))
        path = OUT / f"{case}.json"
        rec = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"case": case, "brief": d["brief"]}
        if do_new:
            rec["new"] = await new_path(case, d)
            rec["new"]["platform_tokens"] = metering.tokens_for_usd(rec["new"]["cost_usd"])
            g = rec["new"].get("graph")
            if g is not None:
                reply = _reply_of(rec["new"])
                (GOLDEN / f"{case}.live.json").write_text(json.dumps(
                    {"case": case, "name": d["name"], "brief": d["brief"],
                     "recorded": f"live intent reply, {time.strftime('%Y-%m-%d')}, tier {rec['new']['meta'].get('tier')}",
                     "reply": reply}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if rescore:
            if "new" in rec:
                rec["new"] = rescore_new(case, d, rec)
            if "old" in rec:
                from aicad.office import planner

                plan = planner.parse_plan(rec["old"]["text"])
                if plan is not None:
                    plan, _n = planner.finish(plan, d["name"], d["brief"])
                rec["old"]["score"] = score(case, plan, d["brief"])
        if do_old:
            rec["old"] = await old_path(case, d)
            rec["old"]["platform_tokens"] = metering.tokens_for_usd(rec["old"]["cost_usd"])
        path.write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        for k in ("new", "old"):
            if k in rec:
                s = rec[k]["score"]
                print(f"{case:11s} {k}: {rec[k]['wall_s']:6.1f} s, {rec[k].get('platform_tokens')} tokens, correct "
                      f"{s.get('correct')}, direct {s.get('n_direct')}/{s.get('n_designed')}, missing "
                      f"{s.get('missing')}, unwanted {s.get('unwanted')}, problems {len(s.get('problems') or [])}")


def _reply_of(new: dict[str, Any]) -> dict[str, Any]:
    return new.get("raw_reply") or {}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if "--rescore" in flags:
        asyncio.run(main(args or list(EXPECT), False, False, True))
    else:
        asyncio.run(main(args or list(EXPECT), "--old" not in flags or "--new" in flags,
                         "--new" not in flags or "--old" in flags))
