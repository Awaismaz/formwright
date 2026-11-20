"""Office polish 2 (office-polish2 report, PD-190..): stale visual looks, the brief's fastener size, path-based
estimates, workspace templates in the Studio, and integrations queued behind the placeholder build. The stepped
coupling (generators finding G1) is in ``test_generators.py`` (it builds CAD)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from aicad.assembly import store as astore
from aicad.assembly import visual
from aicad.office import estimates, icd, orchestrator, planner, service, store, visual_office

PLATE_BRIEF = "Mounting plate 120 x 80 x 10 mm and a cover plate 120 x 80 x 6 mm, joined by 4 M6 bolts. Nothing else."
GC = Path(__file__).resolve().parents[1] / "src" / "aicad" / "eval" / "golden_cases"


def _parts(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": f"i_{s['id']}_{q['id']}", "name": q["name"], "family": q["family"], "qty": q["qty"],
             "description": q["description"], "complexity": q["complexity"], "sub": f"i_{s['id']}"}
            for s in plan["subassemblies"] for q in s["parts"]]


# ----------------------------------------------------------------------------- 2. the brief's fastener size wins
def test_brief_fastener_size_reads_one_explicit_size_only() -> None:
    assert icd.brief_fastener(PLATE_BRIEF) == 6
    assert icd.brief_fastener("Fix it with M8x30 hex bolts.") == 8
    assert icd.brief_fastener("1:3 spur gear pair, m2, 20/60 teeth") is None  # a module, not a screw
    assert icd.brief_fastener("A gear of M2 module on a shaft") is None
    assert icd.brief_fastener("M6 cap screws for the caps and M8 bolts for the cover") is None  # two sizes: per joint
    assert icd.brief_fastener("A plate with four holes") is None


def test_standard_planner_and_icd_use_the_briefs_m6_not_the_span_rule() -> None:
    """Archie's live run (archie-supervisor report): "the brief calls for M6 bolts, but IF-01 specifies M5". The layout's
    size-from-span rule picked M5 for the cover's footprint; the brief says M6, so the interface is M6 with the ISO 273
    medium clearance Ø6.6, and the plan's bolt line says M6, 4 off ("joined by 4 M6 bolts")."""
    plan, _note = planner.finish(planner.standard_plan("Plate and cover", PLATE_BRIEF), "Plate and cover", PLATE_BRIEF)
    bolts = [q for s in plan["subassemblies"] for q in s["parts"] if q["family"] == "standard"]
    assert len(bolts) == 1 and "M6" in bolts[0]["description"] and bolts[0]["qty"] == 4
    _sk, ifs = icd.build(_parts(plan), PLATE_BRIEF)
    joint = next(f for f in ifs if f["kind"] == "hole_pattern")
    assert joint["data"]["fastener"] == "M6" and joint["data"]["d"] == 6.6
    # without the size in the brief the span rule still decides (unchanged behaviour)
    brief = PLATE_BRIEF.replace("4 M6 bolts", "4 bolts")
    plan2, _ = planner.finish(planner.standard_plan("Plate and cover", brief), "Plate and cover", brief)
    _sk, ifs2 = icd.build(_parts(plan2), brief)
    assert next(f for f in ifs2 if f["kind"] == "hole_pattern")["data"]["fastener"] == "M5"


def test_brief_size_never_overrides_the_bearing_cap_screws() -> None:
    plan = {"subassemblies": [{"parts": [
        {"name": "Cap screw", "family": "standard", "description": "Cap screw M5x12 that fixes the four bearing caps."},
        {"name": "Cover bolt", "family": "standard", "description": "Hex bolt M10 joining the cover."}]}]}
    out = planner.brief_fasteners(plan, "A gearbox with M8 cover bolts.")
    caps, cover = out["subassemblies"][0]["parts"]
    assert "M5x12" in caps["description"] and "M8" in cover["description"] and "M10" not in cover["description"]


# ----------------------------------------------------------------------------- 1. stale looks after a revision
def _look(folder: Path, verdict: str, rels: list[str], **extra: Any) -> None:
    visual.store_record(folder, {"status": "done", "at": extra.pop("at", "2026-11-20T10:00:00Z"),
                                 "relations_in": [{"id": f"R{k + 1}", "text": t} for k, t in enumerate(rels)],
                                 "verdict": {"overall": verdict, "relations": [], "problems": [], "summary": ""},
                                 "line": f"Visual check (advisory): it {verdict}.", **extra})


def _test_doc() -> dict[str, Any]:
    """The founder's TEST Project after REV-1 (shape only): the Top level holds the table top alone."""
    items = {"i_s1_p1": {"name": "Table top", "role": "block", "shape": "box", "sub": "i_s1", "size": [800, 600, 20]},
             "i_s2_p2": {"name": "Leg hinge bracket", "role": "block", "shape": "box", "sub": "i_s2"},
             "i_s2_p3": {"name": "Folding leg", "role": "block", "shape": "box", "sub": "i_s2"}}
    return {"id": "aaaaaaaaaaa1", "name": "TEST Project", "brief": "A foldable table.",
            "skeleton": {"items": items, "standard": []},
            "icd": {"version": 2, "status": "approved", "interfaces": []},
            "revisions": [{"id": "REV-1", "status": "applied", "at": "2026-11-20T11:00:00Z", "icd_to": 2}],
            "tickets": [{"id": "t2", "kind": "integration", "item_id": "i_s1", "title": "Assemble Top",
                         "assembly_id": "a00000000001", "look": {"line": "x"}},
                        {"id": "t5", "kind": "integration", "item_id": "i_s2", "title": "Assemble Legs",
                         "assembly_id": "a00000000002", "look": {"line": "y"}}]}


def test_looks_after_a_revision_are_superseded_not_shown_as_current(tmp_path: Path) -> None:
    root, aroot = tmp_path / "office", tmp_path / "asm"
    doc = _test_doc()
    # the gate's look of ICD v1 (from before the version stamp: compared by time with REV-1)
    _look(store.program_dir(root, "aaaaaaaaaaa1") / "visual" / "layout", "looks_wrong", ["Folding leg #1 is bolted to x"])
    # Top: judged against "the other parts mount on Table top" for a level holding the table top alone
    _look(astore.doc_dir(aroot, "a00000000001") / "visual", "looks_wrong", ["the other parts mount on Table top"])
    # Legs: a look whose relations are today's
    legs_rels = [r["text"] for r in visual.relations_from_skeleton(
        visual_office._level_skeleton(doc, doc["tickets"][1]), [], doc["brief"])]
    _look(astore.doc_dir(aroot, "a00000000002") / "visual", "looks_assembled", legs_rels)
    out = {x["name"]: x for x in visual_office.looks(root, aroot, "aaaaaaaaaaa1", doc)}
    assert out["Layout (interfaces gate)"]["superseded"].startswith("Superseded by REV-1 (ICD v2)")
    assert "no longer has" in out["Assemble Top"]["superseded"]
    assert out["Assemble Legs"]["superseded"] is None
    # a level that runs again (revision reset, retry, reopen: its look is dropped) is superseded until Fitz looks
    doc["tickets"][1].pop("look")
    doc["tickets"][1]["run"] = {"status": "integrating"}
    assert "is being assembled again" in {x["name"]: x for x in visual_office.looks(root, aroot, "aaaaaaaaaaa1", doc)}[
        "Assemble Legs"]["superseded"]
    # the revised layout's own look (stamped with the ICD version) is current again
    _look(store.program_dir(root, "aaaaaaaaaaa1") / "visual" / "layout", "looks_assembled", [], icd_version=2, revision="REV-1")
    lay = visual_office.looks(root, aroot, "aaaaaaaaaaa1", doc)[0]
    assert lay["name"] == "Layout (REV-1)" and lay["superseded"] is None


def test_a_level_of_one_part_has_no_relation_to_judge() -> None:
    one = {"items": {"a": {"name": "Table top", "role": "block", "sub": "s"}}, "standard": []}
    assert visual.relations_from_skeleton(one, [], "A table.") == []
    two = {"items": {"a": {"name": "Table top", "role": "block", "sub": "s"},
                     "b": {"name": "Bracket", "role": "block", "sub": "s"}}, "standard": []}
    assert [r["text"] for r in visual.relations_from_skeleton(two, [], "")] == ["the other parts mount on Table top"]


def test_revised_layout_message_names_the_revision_and_offers_nothing() -> None:
    doc = _test_doc()
    text, acts = visual_office.revised_message(doc, {"findings": []}, None, "REV-1")
    assert acts == [] and "(REV-1, ICD v2)" in text and "superseded" in text
    text, _ = visual_office.revised_message(doc, {"findings": [{"severity": "block", "text": "Leg #2 floats"}]},
                                            None, "ICD v1")
    assert "(ICD v2)" in text and "- Leg #2 floats" in text


# ----------------------------------------------------------------------------- 5. estimates on the build path
def test_estimate_ranges_follow_the_build_path() -> None:
    assert estimates.predict_path("standard", "Frame bolt") == "toolbox"
    assert estimates.predict_path("machined", "Base plate") == "direct"
    assert estimates.predict_path("gear", "Pinion") == "direct"
    assert estimates.predict_path("gear", "Worm wheel") == "agent"
    assert estimates.predict_path("sheet", "Guard") == "agent"
    assert estimates.predict_path("machined", "Base plate", direct_on=False) == "agent"
    # seconds where no AI turn runs (office-direct report: 3 to 9 s a part); minutes for the AI designer
    assert estimates.estimate_range("machined", 3, "direct") == (0.05, 0.15)
    assert estimates.estimate_range("standard", 1, "toolbox") == (0.02, 0.1)
    assert estimates.estimate_range("machined", 3, "agent") == (pytest.approx(0.6 * 3.6), pytest.approx(1.5 * 3.6))
    t = estimates.apply_estimate({"family": "turned", "complexity": 2}, "agent")
    assert (t["estimate_lo"], t["estimate_hi"], t["estimate_min"]) == (1.32, 3.3, 2.31) and t["estimate_path"] == "agent"


def test_plan_review_estimate_is_seconds_for_a_program_built_without_ai() -> None:
    """The founder's complaint: plan review said "29 min" for a program that now finishes in seconds. The plate and
    cover are fixed by the drafted layout (direct), the bolts come from the Toolbox: the whole program estimates at
    under two minutes, as a range."""
    plan, _ = planner.finish(planner.standard_plan("Plate and cover", PLATE_BRIEF), "Plate and cover", PLATE_BRIEF)
    pe = service.plan_estimate(plan, 3, None, None, PLATE_BRIEF, direct_on=True)
    assert sorted(pe["paths"].values()) == ["direct", "direct", "toolbox"]
    assert pe["estimate_lo"] < pe["estimate_hi"] < 2 and pe["eta"]["high_min"] < 2
    off = service.plan_estimate(plan, 3, None, None, PLATE_BRIEF, direct_on=False)
    assert sorted(off["paths"].values()) == ["agent", "agent", "toolbox"] and off["estimate_hi"] > 3


def test_icd_approval_sets_each_part_on_the_path_the_office_decides() -> None:
    """Golden c (reducer, template layout): the direct builder builds the housing, cover, caps and the output gear and
    sends the shafts and the pinion to the AI designer; the re-estimate at ICD approval follows exactly that."""
    from aicad.office import direct, interfaces

    brief = "Build a Single stage 3:1 reducer with Spur Gears"
    plan = planner.normalise_plan(json.loads((GC / "c_reducer.plan.json").read_text(encoding="utf-8")), "standard")
    assert plan is not None
    items, tickets = service._build(plan, "Reducer", "RE", brief, direct_on=True)
    doc: dict[str, Any] = {"id": "x", "name": "Reducer", "brief": brief, "plan": plan, "items": items,
                           "tickets": tickets}
    sk, ifs = interfaces._rebuild(doc, {})
    doc.update(skeleton=sk, icd={"version": 1, "status": "approved", "interfaces": ifs, "overrides": {}})
    for t in tickets:
        t["estimate_path"] = "agent"  # as if predicted wrongly
    service.reestimate(None, doc)
    for t in tickets:
        if t["kind"] == "part":
            want = "direct" if direct.plan(doc, t)["path"] == "direct" else "agent"
            assert t["estimate_path"] == want, t["title"]
        elif t["kind"] == "standard":
            assert t["estimate_path"] == "toolbox"
    assert {t["title"] for t in tickets if t.get("estimate_path") == "direct"} >= {"Housing base", "Output gear"}


# ----------------------------------------------------------------------------- 7. Run while the placeholders build
def test_integrations_queue_behind_a_placeholder_build_in_flight() -> None:
    doc = {"id": "pq1", "icd": {"status": "approved", "interfaces": [], "version": 1}, "skeleton": {"items": {}},
           "gates": [{"code": "icd", "status": "approved"}], "assembly": {"status": "building"},
           "tickets": []}
    integ = {"id": "t9", "kind": "integration", "item_id": "root", "column": "backlog", "depends_on": [], "run": None}
    doc["tickets"].append(integ)
    # nothing is building it in this server (tests that never build, a restart): the step is claimable, and the
    # integration itself builds the assembly first (PlatformEnv._assembly_ready)
    assert orchestrator.claimable(doc, integ, 0) is not None
    orchestrator.mark_assembly_build("pq1", True)
    try:
        assert orchestrator.assembly_building("pq1") and orchestrator.claimable(doc, integ, 0) is None
        part = {**integ, "id": "t1", "kind": "part", "column": "ready"}
        assert orchestrator.claimable(doc, part, 0) is not None  # part work never waits for the assembly
        orchestrator.mark_assembly_build("pq1", True)  # a second build (a rebuild while the first runs): counted
        orchestrator.mark_assembly_build("pq1", False)
        assert orchestrator.claimable(doc, integ, 0) is None
    finally:
        orchestrator.mark_assembly_build("pq1", False)
    assert not orchestrator.assembly_building("pq1") and orchestrator.claimable(doc, integ, 0) is not None


def test_integration_waits_for_the_build_then_builds_it_when_none_runs(tmp_path: Path,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    from aicad.office import platform_env

    root = tmp_path / "office"
    doc = {"id": "bbbbbbbbbbb2", "org_id": "o1", "name": "P", "assembly": {"status": "building"}}
    store.save(root, doc)
    calls: list[str] = []

    async def fake_build(r: Path, pid: str, org: str, user: str, gp: bool = False, keep_subs: Any = None) -> None:
        calls.append(pid)
        with store.lock(pid):
            d = store.load(r, pid)
            assert d is not None
            d["assembly"] = {"status": "ready"}
            store.save(r, d)

    monkeypatch.setattr(platform_env, "build_program_assembly", fake_build)
    env = platform_env.PlatformEnv.__new__(platform_env.PlatformEnv)
    env.org_id, env.user_id, env.god_paywall = "o1", "u1", False

    async def run() -> dict[str, Any]:
        orchestrator.mark_assembly_build("bbbbbbbbbbb2", True)

        async def finish() -> None:  # the build in flight ends a moment later
            await asyncio.sleep(0.3)
            with store.lock("bbbbbbbbbbb2"):
                d = store.load(root, "bbbbbbbbbbb2")
                assert d is not None
                d["assembly"] = {"status": "ready"}
                store.save(root, d)
            orchestrator.mark_assembly_build("bbbbbbbbbbb2", False)
        asyncio.get_running_loop().create_task(finish())
        return await env._assembly_ready(root, "bbbbbbbbbbb2", doc)

    out = asyncio.run(run())
    assert out["assembly"]["status"] == "ready" and calls == []  # waited for the one in flight, built nothing
    store.save(root, {**doc, "assembly": {"status": "failed"}})
    out = asyncio.run(env._assembly_ready(root, "bbbbbbbbbbb2", doc))
    assert out["assembly"]["status"] == "ready" and calls == ["bbbbbbbbbbb2"]  # none in flight: built once, here


# ----------------------------------------------------------------------------- 6. templates in the Studio
def test_studio_starts_a_part_from_a_workspace_template_tenant_scoped(office: Any) -> None:  # noqa: F811
    from test_generators import GC as GEN_GC
    from test_generators import TUBE_SCRIPT, _graph_doc, _t
    from test_platform import signup

    from aicad.office import templates
    from aicad.platform.config import get_settings

    c = office
    signup(c, "studio-tpl@x.com")
    org = c.get("/api/auth/me").json()["org"]["id"]
    root = store.org_root(get_settings().data_dir, org)
    gdoc = _graph_doc(GEN_GC / "e_roller.intent.json")
    t = {**_t(gdoc, "Roller tube"), "column": "approved", "direct": {"path": "agent"}}
    rec = templates.harvest(root, gdoc, t, {"ok": True, "source": TUBE_SCRIPT}, "Ann")
    items = c.get("/api/part-templates").json()["items"]
    assert [x["id"] for x in items] == [rec["id"]]
    rows = {p["name"]: p for p in items[0]["param_list"]}
    assert set(rows) >= {"OD", "LENGTH", "BORE"} and rows["OD"]["value"] == 50
    pid = c.post("/api/projects", json={"name": "From a template"}).json()["id"]
    r = c.post(f"/api/projects/{pid}/part-template", json={"template_id": rec["id"], "values": {"OD": 60, "LENGTH": 120}})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Roller tube" and r.json()["ok"]
    from sqlalchemy import select

    from aicad.platform.db import session_factory
    from aicad.platform.models import Project
    from aicad.platform.routers.projects import workspace_for

    db = session_factory()()
    try:
        model = (workspace_for(db.scalar(select(Project).where(Project.id == pid))) / "model.py").read_text(
            encoding="utf-8")
    finally:
        db.close()
    assert "OD = 60.0" in model and "LENGTH = 120.0" in model and 'NAME = "Roller tube"' in model
    assert c.get("/api/part-templates").json()["items"][0]["uses"] == 1
    # bad values are refused with the reason, and nothing changes
    r = c.post(f"/api/projects/{pid}/part-template", json={"template_id": rec["id"], "values": {"NOPE": 1}})
    assert r.status_code == 422 and "not a parameter" in r.json()["detail"]
    # another workspace sees none and can't use it by id
    c.post("/api/auth/logout")
    signup(c, "studio-tpl-other@x.com")
    assert c.get("/api/part-templates").json()["items"] == []
    pid2 = c.post("/api/projects", json={"name": "Theirs"}).json()["id"]
    assert c.post(f"/api/projects/{pid2}/part-template", json={"template_id": rec["id"]}).status_code == 404


from test_office_orchestrator import office  # noqa: F401  (fixture)
