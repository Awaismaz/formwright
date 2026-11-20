"""Assembly Studio as a one-window operation (ASM-OW, founder 2026-11-20): every part of a request in one turn, the
design agent's questions answered in the assembly chat, built parts brought in honestly labelled, splined pairs
placed and fit-checked in the assembly, and the engineer's "mark as verified" override.

Hand values (ISO 14 medium series, from the table, never measured from the shapes):
- Ø25 major: 6 × 21 × 25 × 5. One tooth's section = S(12.5, 2.5) − S(10.5, 2.5), S(ρ, h) = h√(ρ² − h²) + ρ² asin(h/ρ).
- the splined shaft for journal Ø20: journals 20 × 16, seat Ø25 × 30 (16..46) splined over its length, collar Ø30 × 8.
- the gear m2 z40 on it: face width min(10 m, 30) = 20, against the collar: z 26..46, a groove on every tooth.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from pathlib import Path
from typing import Any

import pytest
from test_assembly import app_client  # noqa: F401  (fixture)
from test_assembly_ai import _project, _setup

from aicad import fw_std, llm
from aicad.agent.runner import is_verified, verification
from aicad.assembly import agent, makers, xform
from aicad.llm.stub import StubProvider


def _strip(r: float, h: float) -> float:
    return h * math.sqrt(r * r - h * h) + r * r * math.asin(h / r)


TOOTH = _strip(12.5, 2.5) - _strip(10.5, 2.5)


# ----------------------------------------------------------------------------- pure
def test_iso14_and_spline_volumes_by_hand() -> None:
    from build123d import Align, Cylinder

    assert fw_std.iso14(25) == {"n": 6, "d": 21.0, "D": 25.0, "b": 5.0}
    assert fw_std.iso14(26)["D"] == 25 and fw_std.iso14(26, "light")["D"] == 26
    assert fw_std.spline_tooth_area(21, 25, 5) == pytest.approx(TOOTH, rel=1e-12)
    bar = Cylinder(12.5, 30, align=(Align.CENTER, Align.CENTER, Align.MIN))
    shaft, v = fw_std.spline_shaft(bar, 25, 21, 6, 5, 0, 30)
    assert v == pytest.approx((math.pi / 4 * (25 ** 2 - 21 ** 2) - 6 * TOOTH) * 30, rel=1e-12)
    assert shaft.volume == pytest.approx(bar.volume - v, rel=1e-6) and shaft.is_valid
    hub = Cylinder(30, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))
    bored, vb = fw_std.spline_bore(hub, 25, 21, 6, 5, 0, 20)
    assert vb == pytest.approx((math.pi / 4 * 21 ** 2 + 6 * TOOTH) * 20, rel=1e-12)
    assert bored.volume == pytest.approx(hub.volume - vb, rel=1e-6)
    assert (shaft & bored).volume == pytest.approx(0, abs=1e-6)          # nominal: they meet, never overlap
    feats = [{"name": "Spline", "params": {"spline": "external", "spline_n": 6, "spline_d": 21, "spline_D": 25,
                                           "spline_b": 5, "z0": 0, "z1": 30}}, {"name": "Other", "params": {}}]
    assert fw_std.spline_interfaces(feats) == [{"kind": "external", "n": 6, "d": 21.0, "D": 25.0, "b": 5.0, "z0": 0.0,
                                                "z1": 30.0, "feature": "Spline"}]


def test_splined_shaft_and_gear_layouts() -> None:
    lay = makers.design_shaft({"journal_d": 20, "spline": True})
    assert lay["spline"] == {"n": 6, "d": 21.0, "D": 25.0, "b": 5.0, "z0": 16, "z1": 46, "series": "ISO 14 medium"}
    assert lay["keyseat"] is None and [(s["d"], s["l"]) for s in lay["segments"]] == [(20, 16), (25, 30), (30, 8), (20, 16)]
    by_hand = sum(math.pi * (d / 2) ** 2 * L for d, L in [(20, 16), (25, 30), (30, 8), (20, 16)]) \
        - 2 * (0.5 * 2 * math.pi * (10 - 1 / 3)) - (math.pi / 4 * (25 ** 2 - 21 ** 2) - 6 * TOOTH) * 30
    assert makers.shaft_volume(lay) == pytest.approx(by_hand, rel=1e-12)
    assert "fw.spline_shaft" in makers.shaft_script(lay) and "D_SEAT=" not in makers.shaft_script(lay)
    g = makers.design_gear({"module": 2, "teeth": 40, "spline": fw_std.iso14(25)})
    assert g["spline"]["n"] == 6 and g["keyway"] is None and "fw.spline_bore" in makers.gear_script(g)
    with pytest.raises(makers.MakeError):
        makers.design_shaft({"journal_d": 20, "spline": True, "groove": True})


def test_verification_states_and_rebuild_revokes() -> None:
    chk = [{"id": "CHK-05", "name": "volume vs analytic", "passed": False, "gating": True}]
    st = {"ok": False, "build_id": 11, "checks": chk}
    assert verification(st)["state"] == "unverified" and not is_verified(st)
    st["accepted"] = {"by": "Ada", "build_id": 11, "open": [{"id": "CHK-05", "name": "volume"}]}
    assert is_verified(st) and verification(st)["state"] == "accepted"
    assert verification({**st, "build_id": 12})["state"] == "unverified"      # a new build: the mark is gone
    assert verification({"ok": True, "build_id": 3, "verified": True, "checks": []})["state"] == "verified"


def test_turn_runs_every_action_and_defers_on_parts_in_design() -> None:
    assert agent._labels_in({"do": "mate", "part": "$gear", "to": "$shaft"}) == {"$gear", "$shaft"}
    assert agent._labels_in({"do": "assemble", "parts": ["$a", "i3"]}) == {"$a"}
    qs = agent.relay_questions([{"question": "Hub length?", "options": ["20 mm", "30 mm"], "default": "20 mm"}],
                               "Spline gear")
    assert qs[0]["question"] == "Spline gear: Hub length?" and qs[0]["default"] == "20 mm"
    assert agent.unverified_note({"open": [{"id": "CHK-05", "name": "volume"}]}) == "Unverified: CHK-05 volume did not pass"


# ----------------------------------------------------------------------------- through the app
def _stub(replies: dict[str, Any]) -> StubProvider:
    def responder(req: llm.CallRequest) -> str | None:
        if req.role != "assembly_agent":
            return None
        said = req.prompt.rsplit("[The engineer now says]\n", 1)[-1].strip()
        assert said in replies, said
        return "```json\n" + json.dumps(replies[said]) + "\n```"
    return StubProvider(responder)


def _say(c: Any, aid: str, text: str, job: str | None = None) -> dict[str, Any]:
    r = c.post(f"/api/m/assembly/assemblies/{aid}/chat", json={"text": text, "wait": True, **({"job": job} if job else {})})
    assert r.status_code == 200, r.text
    return r.json()


def _wait(c: Any, aid: str, until: Any, what: str) -> dict[str, Any]:
    for _ in range(240):
        v = c.get(f"/api/m/assembly/assemblies/{aid}/chat").json()
        if until(v):
            return v
        time.sleep(0.5)
    raise AssertionError(f"timed out waiting for {what}: {json.dumps(v['jobs'])} {json.dumps(v['messages'][-3:])[:4000]}")


def test_splined_shaft_and_gear_in_one_request_direct(app_client: Any) -> None:  # noqa: F811
    c = app_client
    _setup(c, "ow1@x.com")
    aid = c.post("/api/m/assembly/assemblies", json={"name": "Spline line"}).json()["assembly"]["id"]
    said = "make a stepped splined shaft Ø20 and a spur gear m2 z40 on it"
    replies = {said: {"say": "I'll make both and put the gear on the spline.", "actions": [
        {"do": "make", "kind": "shaft", "spec": {"journal_d": 20, "spline": True}, "as": "$shaft"},
        {"do": "make", "kind": "gear", "spec": {"module": 2, "teeth": 40}, "for": "$shaft", "as": "$gear"}]},
        "check for clashes": {"say": "", "actions": [{"do": "check", "what": ["interference"]}]}}
    with llm.use_provider(_stub(replies), roles=("assembly_agent",)):
        m = _say(c, aid, said)["messages"][-1]
        assert [s["status"] for s in m["steps"]] == ["ok", "ok"], m["steps"]
        lines = " ".join(m["steps"][1]["lines"])
        assert "hub spline 6 × 21 × 25 × 5" in lines and "sizes match" in lines, lines
        v = c.get(f"/api/m/assembly/assemblies/{aid}").json()
        assert len(v["instances"]) == 2 and all(mt["status"] == "ok" for mt in v["mates"]) and len(v["mates"]) >= 2
        gear = next(i for i in v["instances"] if i["id"] == "i2")
        T = xform.from12(gear["T"])
        o, z = xform.pt(T, (0, 0, 0)), xform.vec(T, (0, 0, 1))
        assert abs(o[0]) + abs(o[1]) < 1e-6 and sorted([o[2], o[2] + 20 * z[2]]) == pytest.approx([26, 46], abs=1e-6)
        m = _say(c, aid, "check for clashes")["messages"][-1]
        text = " ".join(m["steps"][0]["lines"])
        assert "no clashes" in text and "Spline fit" in text and "sizes match" in text, text


def test_design_jobs_in_parallel_questions_relayed_and_unverified_part_brought_in(
        app_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Both parts go to the design agent in one turn; the gear's design agent asks a question, answered in the
    assembly chat; the gear is built with its volume check failing (as the founder's was) and still comes in,
    labelled, and is mated to the shaft by its spline, fit-checked here."""
    from aicad.platform.routers import mod_assembly as asm
    from aicad.platform.routers import mod_assembly_chat as mac
    from aicad.platform.routers.library import install_model
    from aicad.platform.routers.projects import workspace_for

    seen: dict[str, Any] = {"briefs": {}, "answers": [], "asked": set()}
    sp = fw_std.iso14(25)

    async def design_part(self: Any, name: str, brief: str) -> str:
        seen["briefs"][name] = brief
        with self.ctx() as cx:
            p = self._new_project(cx, name, brief[:400])
            pid = str(p.id)
        if "shaft" in name.lower():
            await _install(self, pid, makers.make("shaft", {"journal_d": 20, "spline": True, "name": name})[1])
        else:
            seen["gear"] = pid
        return pid

    async def _install(self: Any, pid: str, src: str, fail_volume: bool = False) -> None:
        with self.ctx() as cx:
            p = asm._project(cx, pid)
            await install_model(p, cx, src, strict=True, note="test design agent")
            cx.db.commit()
            if fail_volume:   # the founder's gear: built, but its own volume check failed
                f = workspace_for(p) / "out" / "status.json"
                st = json.loads(f.read_text(encoding="utf-8"))
                for ck in st["checks"]:
                    if ck["id"] == "CHK-05":
                        ck["passed"] = False
                st["ok"] = st["verified"] = False
                f.write_text(json.dumps(st), encoding="utf-8")

    async def watch_design(self: Any, pid: str, on_step: Any, on_questions: Any = None) -> bool:
        on_step("Building")
        await asyncio.sleep(0.05)
        if pid == seen.get("gear") and pid not in seen["asked"]:
            seen["asked"].add(pid)
            on_questions([{"id": "hub", "question": "Hub length?", "options": ["20 mm", "30 mm"]}])
            return False
        from aicad.platform.routers.projects import wait_finalized

        await wait_finalized(pid)            # as the real follower does before it reads the build
        return bool(self.build_state(pid)["verified"])

    async def answer_design(self: Any, pid: str, text: str) -> None:
        seen["answers"].append(text)
        _lay, src = makers.make("gear", {"module": 2, "teeth": 40, "spline": sp, "name": "Spline gear"})
        await _install(self, pid, src, fail_volume=True)

    monkeypatch.setattr(mac.PlatformEnv, "design_part", design_part)
    monkeypatch.setattr(mac.PlatformEnv, "watch_design", watch_design)
    monkeypatch.setattr(mac.PlatformEnv, "answer_design", answer_design)
    c = app_client
    _setup(c, "ow2@x.com")
    aid = c.post("/api/m/assembly/assemblies", json={"name": "Designed line"}).json()["assembly"]["id"]
    said = "make a splined drive shaft and a spline gear on it"
    replies = {said: {"say": "Both go to the design agent now.", "actions": [
        {"do": "make", "kind": "other", "name": "Splined drive shaft", "as": "$shaft",
         "brief": "A stepped shaft, Ø20 journals, an ISO 14 splined seat Ø25 against a collar."},
        {"do": "make", "kind": "other", "name": "Spline gear", "for": "$shaft", "as": "$gear",
         "brief": "A spur gear m2 z40 with an ISO 14 spline hub for the shaft."}]}}
    with llm.use_provider(_stub(replies), roles=("assembly_agent",)):
        m = _say(c, aid, said)["messages"][-1]
    # one turn, both parts started (in parallel), the mate waits for both
    assert [s["label"] for s in m["steps"]][:2] == ["Designing Splined drive shaft", "Designing Spline gear"], m["steps"]
    assert any(s["label"].startswith("Then: mating") for s in m["steps"]), m["steps"]
    gb = seen["briefs"]["Spline gear"]
    assert "[Assembly Studio build]" in gb and "ISO 14 splined seat" in gb and "checked in the assembly" in gb
    assert "do not ask questions" in gb
    v = _wait(c, aid, lambda v: any(j["status"] == "question" for j in v["jobs"]) and
              any(j["status"] == "done" for j in v["jobs"]), "the question and the shaft")
    q = next(x for x in v["messages"] if x.get("questions") and x.get("job"))
    assert q["questions"][0]["question"] == "Spline gear: Hub length?" and "Design Studio" not in q["text"]
    gear_job = q["job"]
    # the chip answer goes to the design agent of that part, from the assembly chat
    _say(c, aid, f"{q['questions'][0]['question']} 20 mm", job=gear_job)
    assert seen["answers"] == ["Spline gear: Hub length? 20 mm"]
    v = _wait(c, aid, lambda v: all(j["status"] in ("done", "failed") for j in v["jobs"]) and
              "with a check open" in json.dumps(v["messages"][-1]), "the gear")
    last = v["messages"][-1]
    blob = json.dumps(last)
    assert "Unverified: CHK-05" in blob and "sizes match" in blob, blob
    brought = next(s for s in last["steps"] if s["label"].startswith("Brought"))
    assert brought["unverified"] and brought["open"][0]["id"] == "CHK-05"
    view = c.get(f"/api/m/assembly/assemblies/{aid}").json()
    assert len(view["instances"]) == 2 and all(mt["status"] == "ok" for mt in view["mates"]) and view["mates"]
    gp = next(p for p in view["parts"].values() if p["name"] == "Spline gear")
    assert gp["verification"] == "Unverified: CHK-05" and not gp["accepted"]
    row = next(r for r in view["bom"]["rows"] if r["part"] == "Spline gear")
    assert row["verification"] == "Unverified: CHK-05" and "Unverified: CHK-05" in row["description"]


def test_unverified_insert_and_verify_override(app_client: Any) -> None:  # noqa: F811
    from test_platform import PW, _link_token

    from aicad.platform.db import session_factory
    from aicad.platform.models import Project

    c = app_client
    _setup(c, "ow3@x.com")

    def failing_plate(out: Path) -> None:
        from build123d import Align, Box, export_step

        out.mkdir(parents=True, exist_ok=True)
        export_step(Box(60, 40, 8, align=(Align.CENTER, Align.CENTER, Align.MIN)), str(out / "part.step"))
        (out / "status.json").write_text(json.dumps({
            "ok": False, "verified": False, "part": "Plate", "material": "Steel S235", "build_id": "9001",
            "checks": [{"id": "CHK-05", "name": "volume vs analytic", "passed": False, "gating": True},
                       {"id": "CHK-02", "name": "valid B-rep", "passed": True, "gating": True}]}), encoding="utf-8")

    pid = _project(c, "Cover Plate", failing_plate)
    src = next(p for p in c.get("/api/m/assembly/sources").json()["projects"] if p["id"] == pid)
    assert src["geometry"] and not src["verified"] and src["verification"] == "unverified"
    assert src["open_checks"] == [{"id": "CHK-05", "name": "volume vs analytic"}]
    aid = c.post("/api/m/assembly/assemblies", json={"name": "Cover"}).json()["assembly"]["id"]
    r = c.post(f"/api/m/assembly/assemblies/{aid}/instances", json={"project_id": pid})
    assert r.status_code == 200, r.text
    v = r.json()
    part = next(iter(v["parts"].values()))
    assert part["verification"] == "Unverified: CHK-05" and v["bom"]["rows"][0]["verification"] == "Unverified: CHK-05"
    # a project with no geometry at all is still refused
    empty = c.post("/api/projects", json={"name": "Empty"}).json()["id"]
    assert c.post(f"/api/m/assembly/assemblies/{aid}/instances", json={"project_id": empty}).status_code in (409, 422)

    # the engineer's override: recorded on this build, labelled with the name and the open check
    r = c.post(f"/api/projects/{pid}/verify-override", json={"reason": "fit checked in the assembly"})
    assert r.status_code == 200, r.text
    assert r.json()["verification"]["state"] == "accepted"
    src = next(p for p in c.get("/api/m/assembly/sources").json()["projects"] if p["id"] == pid)
    assert src["verification"] == "accepted" and src["accepted_by"] and not src["verified"]
    v = c.get(f"/api/m/assembly/assemblies/{aid}").json()
    part = next(iter(v["parts"].values()))
    assert part["accepted"] and part["verification"].startswith("Verified by ") and "open: CHK-05" in part["verification"]
    assert "Verified by" in v["bom"]["rows"][0]["description"]
    lst = c.get(f"/api/projects/{pid}").json()
    assert (lst.get("last_status") or {}).get("accepted_by")
    # a rebuild (a new build id) revokes it
    db = session_factory()()
    from aicad.platform.routers.projects import workspace_for

    ws = workspace_for(db.get(Project, pid))
    db.close()
    f = ws / "out" / "status.json"
    st = json.loads(f.read_text(encoding="utf-8"))
    assert st["accepted"]["open"][0]["id"] == "CHK-05"
    st.pop("accepted")
    st["build_id"] = "9002"
    f.write_text(json.dumps(st), encoding="utf-8")
    src = next(p for p in c.get("/api/m/assembly/sources").json()["projects"] if p["id"] == pid)
    assert src["verification"] == "unverified"
    st["accepted"] = {"by": "Ada", "build_id": "9001", "open": []}       # a stale mark from the old build: ignored
    f.write_text(json.dumps(st), encoding="utf-8")
    src = next(p for p in c.get("/api/m/assembly/sources").json()["projects"] if p["id"] == pid)
    assert src["verification"] == "unverified"
    # withdraw is harmless; viewers can't override
    assert c.delete(f"/api/projects/{pid}/verify-override").status_code == 200
    pay = c.post("/api/billing/checkout", json={"product_code": "team"}).json()["payment_id"]
    c.post(f"/api/billing/payments/{pay}/simulate", json={"outcome": "success"})
    assert c.post("/api/team/invites", json={"email": "view3@x.com", "role": "viewer"}).status_code == 200
    from fastapi.testclient import TestClient

    tok = _link_token("view3@x.com", "invited you")
    guest = TestClient(c.app)
    guest.headers.update({"X-FW-CSRF": "1"})
    guest.post("/api/auth/signup", json={"name": "Vic", "email": "view3@x.com", "password": PW})
    guest.post("/api/team/invites/accept", json={"token": tok})
    assert guest.post(f"/api/projects/{pid}/verify-override", json={}).status_code in (403, 404)
