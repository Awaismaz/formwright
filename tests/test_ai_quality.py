"""AI quality: brief approval gate (CAD-028), replay provider (AGT-002), self-review (AGT-006), benchmark (EVAL-003).

No model calls: every agent turn here is a recorded/replayed cassette.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_platform import app_client, signup  # noqa: F401  (fixture re-export)

from aicad.agent.blocks import (
    brief_to_prompt,
    extract_brief,
    extract_review,
    parse_brief,
    parse_review,
)
from aicad.agent.replay import (
    ReplayClient,
    message_from_dict,
    message_to_dict,
    write_files,
)
from aicad.agent.session import AgentSession, make_guard, scrub

PLATE = """from build123d import *
from math import pi
NAME = "Plate"
MATERIAL = "6061-T6"
LENGTH = 80  # overall length
WIDTH = 50  # overall width
THICK = 6  # thickness
PARAMS = dict(LENGTH=LENGTH, WIDTH=WIDTH, THICK=THICK)
result = Box(LENGTH, WIDTH, THICK, align=(Align.CENTER, Align.CENTER, Align.MIN))
EXPECTED = {"bbox": [LENGTH, WIDTH, THICK], "volume": LENGTH*WIDTH*THICK, "solids": 1}
"""

BRIEF = {"title": "Plate 80 × 50 × 6", "requirements": ["80 × 50 × 6 mm plate"],
         "assumptions": ["Aluminium 6061-T6"], "questions": [{"question": "Edge break?", "default": "0.5 mm chamfer"}]}
REVIEW = {"observed": [{"text": "Size 80 × 50 × 6 mm as requested", "basis": "CHK-04"}],
          "uncertain": [{"text": "Edge finish not visible at this scale", "basis": "render"}]}


def _fence(tag: str, obj: Any) -> str:
    return f"```{tag}\n{json.dumps(obj)}\n```"


def _turn(text: str, match: str | None = None, build: bool = False, files: dict[str, str] | None = None) -> dict[str, Any]:
    msgs: list[dict[str, Any]] = [{"type": "system", "subtype": "init", "data": {}}]
    if build:
        msgs += [{"type": "assistant", "model": "replay", "content": [
                    {"type": "tool_use", "id": "w1", "name": "Write", "input": {"file_path": "model.py"}}]},
                 {"type": "user", "content": [{"type": "tool_result", "tool_use_id": "w1", "content": "ok"}]},
                 {"type": "assistant", "model": "replay", "content": [
                     {"type": "tool_use", "id": "b1", "name": "mcp__cad__build_model", "input": {}}]},
                 {"type": "user", "content": [{"type": "tool_result", "tool_use_id": "b1", "content": "(replayed)"}]}]
    msgs += [{"type": "assistant", "model": "replay", "content": [{"type": "text", "text": text}]},
             {"type": "result", "subtype": "success", "num_turns": 2, "duration_ms": 1200, "session_id": "rp-1",
              "total_cost_usd": 0.0}]
    t: dict[str, Any] = {"messages": msgs, "rebuild": build, "files": files or {}}
    if match:
        t["match"] = match
    return t


# ------------------------------------------------------------------ block parsing
def test_brief_block_valid_and_invalid() -> None:
    text, b = extract_brief("Here is my reading.\n" + _fence("fw-brief", BRIEF), scrub)
    assert text == "Here is my reading." and b is not None
    assert b["requirements"] == ["80 × 50 × 6 mm plate"] and b["questions"][0]["default"] == "0.5 mm chamfer"
    # strings are accepted as questions; agent internals are scrubbed
    b2 = parse_brief({"requirements": ["edit model.py"], "questions": ["Material?"]}, scrub)
    assert b2 and b2["requirements"] == ["edit the design"] and b2["questions"] == [{"question": "Material?", "default": None}]
    # invalid: no requirements, not an object, malformed JSON -> no card, block never shown raw
    assert parse_brief({"assumptions": ["x"]}) is None and parse_brief(["x"]) is None
    text, b = extract_brief("Intro\n```fw-brief\n{not json}\n```")
    assert b is None and text == "Intro"
    assert "Approved design brief" in brief_to_prompt(BRIEF) and "0.5 mm chamfer" in brief_to_prompt(BRIEF)


def test_review_block_valid_invalid_and_never_overrides_gates() -> None:
    ok = {"ok": True, "checks": [{"id": "CHK-04", "gating": True, "passed": True}], "build_id": "b1"}
    text, r = extract_review("Built.\n" + _fence("fw-review", REVIEW), ok)
    assert text == "Built." and r is not None and r["gates"] == {"ok": True, "failed": [], "build_id": "b1"}
    assert [i["kind"] for i in r["items"]] == ["observed", "uncertain"]
    # a finding must cite a check or the render
    assert parse_review({"observed": [{"text": "looks right", "basis": "gut feeling"}]}, ok) is None
    assert parse_review("nope", ok) is None
    _, r = extract_review("```fw-review\n{broken\n```", ok)
    assert r is None
    # a failed gate can never be marked passed by the critique
    bad = {"ok": False, "checks": [{"id": "CHK-05", "gating": True, "passed": False},
                                   {"id": "CHK-04", "gating": True, "passed": True}]}
    r = parse_review({"observed": [{"text": "Volume matches", "basis": "CHK-05"},
                                   {"text": "All gating checks pass", "basis": "render"},
                                   {"text": "Size is right", "basis": "chk-04"}]}, bad)
    assert r is not None and r["gates"]["ok"] is False and r["gates"]["failed"] == ["CHK-05"]
    assert [i["kind"] for i in r["items"]] == ["overridden", "overridden", "observed"]


def test_guard_denies_building_while_the_brief_awaits_approval(tmp_path: Path) -> None:
    mode = {"v": "brief"}
    guard = make_guard(tmp_path, lambda: mode["v"])

    def decide(name: str, ti: dict[str, Any]) -> str | None:
        out = asyncio.run(guard({"tool_name": name, "tool_input": ti}, None, None))
        return out.get("hookSpecificOutput", {}).get("permissionDecision")

    inside = str(tmp_path / "model.py")
    assert decide("mcp__cad__build_model", {}) == "deny"
    assert decide("Write", {"file_path": inside}) == "deny"
    assert decide("Edit", {"file_path": inside}) == "deny"
    assert decide("Read", {"file_path": inside}) is None
    mode["v"] = "build"
    assert decide("mcp__cad__build_model", {}) is None


# ------------------------------------------------------------------ replay provider
def test_message_roundtrip_and_cassette_paths_stay_in_workspace(tmp_path: Path) -> None:
    for d in _turn("hi " + _fence("fw-review", REVIEW), build=True)["messages"]:
        assert message_to_dict(message_from_dict(d))["type"] == d["type"]
    with pytest.raises(ValueError):
        write_files(tmp_path, {"../escape.py": "x"})


def _session(ws: Path, cassette: dict[str, Any]) -> tuple[AgentSession, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    s = AgentSession(ws, on_event=events.append)
    s.client_factory = lambda o: ReplayClient(o, cassette)
    return s, events


def test_replayed_questions_turn_changes_nothing(tmp_path: Path) -> None:
    qs = [{"id": "mat", "question": "Which material?", "options": ["6061-T6", "S355"]}]
    s, events = _session(tmp_path / "ws", {"turns": [_turn("Two choices first.\n" + _fence("fw-questions", qs))]})
    asyncio.run(s.send("a bracket"))
    kinds = [e["type"] for e in events]
    assert kinds[:2] == ["user", "busy"] and "questions" in kinds and kinds[-1] == "busy"
    assert next(e for e in events if e["type"] == "questions")["questions"][0]["options"] == ["6061-T6", "S355"]
    assert next(e for e in events if e["type"] == "result")["subtype"] == "success"
    assert not (s.workspace / "model.py").exists() and not (s.workspace / "out").exists()


def test_replayed_build_turn_rebuilds_and_reviews(tmp_path: Path) -> None:
    from aicad.agent import worker

    turn = _turn("Plate built.\n" + _fence("fw-review", REVIEW), build=True, files={"model.py": PLATE})
    s, events = _session(tmp_path / "ws", {"turns": [turn]})

    async def go() -> None:
        try:
            await s.send("plate 80 x 50 x 6")
        finally:
            await worker.shutdown_all()

    asyncio.run(go())
    built = next(e for e in events if e["type"] == "tool_result" and e["build"])
    assert built["brief"] == "All checks passed"  # the fresh check report from the real build, not the recording
    st = json.loads((s.out_dir / "status.json").read_text())
    assert st["ok"] and sorted(st["fingerprint"]["bbox"]) == [6, 50, 80]
    rv = next(e for e in events if e["type"] == "review")
    assert rv["gates"]["ok"] is True and rv["items"][0]["kind"] == "observed"
    assert "fw-review" not in json.dumps([e for e in events if e["type"] == "text"])


# ------------------------------------------------------------------ brief gate through the app (replayed agent)
def _wait_idle(pid: str, timeout: float = 120) -> list[dict[str, Any]]:
    from aicad.platform.routers.projects import _sessions

    t0 = time.time()
    while time.time() - t0 < timeout:
        s = _sessions.get(pid)
        if s is not None and not s.busy and any(e["type"] == "result" for e in s.history):
            return list(s.history)
        time.sleep(0.2)
    raise AssertionError("agent turn did not finish")


def test_brief_gate_then_approve_and_build(app_client: TestClient, tmp_path: Path,  # noqa: F811
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    cassette = {"turns": [
        _turn("Here is how I read it.\n" + _fence("fw-brief", BRIEF), match=r"^\[Brief confirmation"),
        _turn("Plate built.\n" + _fence("fw-review", REVIEW), match=r"Approved design brief", build=True,
              files={"model.py": PLATE})]}
    f = tmp_path / "cassette.json"
    f.write_text(json.dumps(cassette))
    monkeypatch.setenv("FW_AGENT_REPLAY", str(f))
    c = app_client
    signup(c, "brief@x.com")
    pid = c.post("/api/projects", json={"name": "Plate"}).json()["id"]
    assert c.post(f"/api/projects/{pid}/agent/chat", json={"prompt": "plate 80 x 50 x 6"}).status_code == 200
    hist = _wait_idle(pid)
    assert next(e for e in hist if e["type"] == "user")["mode"] == "brief"
    brief = next(e for e in hist if e["type"] == "brief")["brief"]
    assert brief["requirements"] == BRIEF["requirements"]
    assert c.get(f"/api/projects/{pid}").json()["builds"] == 0  # nothing built before approval

    from aicad.platform.routers.projects import _sessions

    _sessions[pid].history.clear()
    r = c.post(f"/api/projects/{pid}/agent/chat", json={"prompt": brief_to_prompt(brief), "brief_approved": True})
    assert r.status_code == 200
    hist = _wait_idle(pid)
    assert next(e for e in hist if e["type"] == "user")["mode"] == "build"
    assert any(e["type"] == "tool_result" and e["build"] for e in hist)
    rv = next(e for e in hist if e["type"] == "review")
    assert rv["gates"]["ok"] is True
    assert c.get(f"/api/projects/{pid}").json()["builds"] == 1
    assert _sessions[pid].brief_approved is True


def test_brief_gate_setting_and_per_message_skip(app_client: TestClient, tmp_path: Path,  # noqa: F811
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    from aicad.platform.routers.projects import _sessions

    f = tmp_path / "cassette.json"
    f.write_text(json.dumps({"turns": [_turn("Sure."), _turn("Sure."), _turn("Sure.")]}))
    monkeypatch.setenv("FW_AGENT_REPLAY", str(f))
    c = app_client
    signup(c, "skip@x.com")
    pid = c.post("/api/projects", json={"name": "Skip"}).json()["id"]
    c.post(f"/api/projects/{pid}/agent/chat", json={"prompt": "a part", "skip_brief": True})
    assert next(e for e in _wait_idle(pid) if e["type"] == "user")["mode"] == "build"
    _sessions[pid].history.clear()
    c.post(f"/api/projects/{pid}/agent/chat", json={"prompt": "talk", "mode": "discuss"})
    assert next(e for e in _wait_idle(pid) if e["type"] == "user")["mode"] == "discuss"
    _sessions[pid].history.clear()
    c.patch("/api/auth/profile", json={"preferences": {"confirm_brief": False}})
    assert c.get("/api/auth/me").json()["user"]["preferences"]["confirm_brief"] is False
    c.post(f"/api/projects/{pid}/agent/chat", json={"prompt": "a part"})
    assert next(e for e in _wait_idle(pid) if e["type"] == "user")["mode"] == "build"


# ------------------------------------------------------------------ benchmark
def test_benchmark_cases_and_dry_run_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    from aicad.eval import benchmark
    from aicad.eval.prompts import CASES

    assert len(CASES) == 20 and {c["family"] for c in CASES} == {"plate", "bracket", "shaft", "flange", "enclosure"}
    assert "250" in benchmark.estimate(1)  # the live run prints its token estimate first
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert benchmark.main(["--live", "--only", "P01"]) == 2  # a live run never starts unconfirmed
    out = tmp_path / "report"
    assert benchmark.main(["--dry", "--only", "P02,B02,F03", "--out", str(out)]) == 0
    rep = json.loads((out / "report.json").read_text())
    assert rep["summary"]["ran"] == 3 and rep["summary"]["pass_rate"] == 1.0 and rep["summary"]["cost_usd"] == 0
    assert all(r["builds"] == 1 and r["census_ok"] and r["self_review"] for r in rep["rows"])
    assert "| P02 | plate | yes |" in (out / "report.md").read_text(encoding="utf-8")
    # scoring catches a wrong part even when its own checks pass
    st = {"ok": True, "checks": [], "fingerprint": {"bbox": [100, 80, 8], "volume": 64000, "solids": 1}}
    bad = benchmark.score(CASES[0]["expect"], st, {"faces": []})
    assert not bad["passed"] and not bad["bbox_ok"] and not bad["volume_ok"] and not bad["census_ok"]
