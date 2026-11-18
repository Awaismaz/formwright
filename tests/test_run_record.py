"""AGT-009: complete run record per design-agent turn, driven by the replay provider (zero model calls).

The cassette below carries hand-written usage numbers, so every expected token count and cost is a hand sum."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_ai_quality import PLATE, _wait_idle
from test_platform import admin, app_client, signup  # noqa: F401  (fixture re-export)

from aicad.agent import runrecord
from aicad.agent.pricing import usage_cost_usd
from aicad.agent.replay import ReplayClient
from aicad.agent.session import AgentSession

MODEL_ID = "claude-opus-5-5"
U1 = {"input_tokens": 1200, "output_tokens": 300, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 5000}
U2 = {"input_tokens": 400, "output_tokens": 150, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 0}
RESULT_USAGE = {"input_tokens": 1600, "output_tokens": 450, "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 5000}
PROMPT = ("Plate 80 x 50 x 6 mm please. Contact me at jane.doe@example.com or +44 20 7946 0958, "
          "spec at https://intranet.example.com/spec.pdf, key sk-ant-abcdefghijklmnop.")


def _cassette() -> dict[str, Any]:
    return {"turns": [{"rebuild": True, "files": {"model.py": PLATE}, "messages": [
        {"type": "system", "subtype": "init", "data": {"apiKeySource": "none"}},
        {"type": "assistant", "model": MODEL_ID, "message_id": "r1", "usage": U1, "content": [
            {"type": "text", "text": "Modelling the plate."},
            {"type": "tool_use", "id": "w1", "name": "Write", "input": {"file_path": "model.py"}}]},
        {"type": "user", "content": [{"type": "tool_result", "tool_use_id": "w1", "content": "ok"}]},
        {"type": "assistant", "model": MODEL_ID, "message_id": "r1", "usage": U1, "content": [  # same response again
            {"type": "tool_use", "id": "b1", "name": "mcp__cad__build_model", "input": {}}]},
        {"type": "user", "content": [{"type": "tool_result", "tool_use_id": "b1", "content": "(replayed)"}]},
        {"type": "assistant", "model": MODEL_ID, "message_id": "r2", "usage": U2, "content": [
            {"type": "text", "text": "Built."}]},
        {"type": "result", "subtype": "success", "num_turns": 3, "duration_ms": 4200, "duration_api_ms": 3100,
         "session_id": "sess-1", "total_cost_usd": 0.0421, "usage": RESULT_USAGE}]}]}


def _run(ws: Path, prompt: str = PROMPT) -> tuple[AgentSession, list[dict[str, Any]]]:
    from aicad.agent import worker

    events: list[dict[str, Any]] = []
    s = AgentSession(ws, on_event=events.append, worker_key="runrec")
    cassette = _cassette()
    s.client_factory = lambda o: ReplayClient(o, cassette, worker_key="runrec")

    async def go() -> None:
        try:
            await s.send(prompt)
        finally:
            await worker.shutdown_all()

    asyncio.run(go())
    return s, events


# ------------------------------------------------------------------ prompt policy
def test_prompt_policy_hash_redacted_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    sha = hashlib.sha256(PROMPT.encode()).hexdigest()
    h = runrecord.prompt_entry(PROMPT, "hash")
    assert h == {"sha256": sha, "chars": len(PROMPT), "policy": "hash"}
    r = runrecord.prompt_entry(PROMPT, "redacted")
    ex = r["excerpt"]
    assert r["sha256"] == sha and "text" not in r
    for secret in ("jane.doe@example.com", "7946", "intranet.example.com", "sk-ant-abcdefghijklmnop"):
        assert secret not in ex, secret
    assert "80 x 50 x 6 mm" in ex  # engineering numbers stay
    attach = runrecord.redact("bracket\n\n[Reference image: refs/a.png]\nlots of private context")
    assert attach == "bracket [attachment context removed]"
    raw = runrecord.prompt_entry(PROMPT, "raw")
    assert raw["text"] == PROMPT

    monkeypatch.delenv(runrecord.POLICY_ENV, raising=False)
    assert runrecord.policy() == "redacted"  # default
    monkeypatch.setenv(runrecord.POLICY_ENV, "nonsense")
    assert runrecord.policy() == "redacted"
    monkeypatch.setenv(runrecord.POLICY_ENV, "raw")
    from aicad.platform import config

    s = config.get_settings()
    config.override_settings(config.Settings(**{**s.__dict__, "env": "production", "stripe_secret_key": "sk_test_x"}))
    try:
        assert runrecord.policy() == "redacted"  # raw prompts are never kept in production
    finally:
        config.override_settings(s)


# ------------------------------------------------------------------ the record of a replayed build turn
def test_replayed_turn_writes_complete_run_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(runrecord.POLICY_ENV, raising=False)
    s, events = _run(tmp_path / "ws")
    runs = runrecord.list_runs(s.workspace)
    assert len(runs) == 1
    rec = runrecord.load(s.workspace, runs[0]["run_id"])
    assert rec is not None and rec == s.last_run_record
    assert rec["schema"] == runrecord.SCHEMA and rec["mode"] == "build"
    # prompt: hashed + redacted by default, never raw
    assert rec["prompt"]["sha256"] == hashlib.sha256(PROMPT.encode()).hexdigest()
    assert rec["prompt"]["policy"] == "redacted" and "text" not in rec["prompt"]
    assert "jane.doe@example.com" not in json.dumps(rec)
    # model and versions
    assert rec["model"] == {"requested": None, "used": [MODEL_ID]}
    v = rec["versions"]
    assert v["agent_sdk"] and v["build123d"] and v["ocp"] and v["toolbox"] is not None and v["app"] and v["python"]
    assert rec["agent"] == {"apiKeySource": "none"}
    # tokens: the agent's own turn total; per-response sum counts response r1 once (it arrived twice)
    assert {k: rec["tokens"][k] for k in RESULT_USAGE} == RESULT_USAGE and rec["tokens"]["source"] == "result"
    assert rec["tokens"]["responses"] == 2
    assert rec["tokens"]["per_response_sum"] == {k: U1[k] + U2[k] for k in U1}
    assert rec["cost_usd"]["run"] == pytest.approx(0.0421)
    assert rec["cost_usd"]["estimate_from_usage"] == pytest.approx(
        usage_cost_usd(MODEL_ID, U1) + usage_cost_usd(MODEL_ID, U2), abs=1e-6)
    # tools and builds
    assert rec["tools"] == {"calls": 2, "by_name": {"Write": 1, "cad:build_model": 1}, "errors": 0, "builds": 1}
    assert [b["result"] for b in rec["builds"]] == ["pass"]  # the fresh check report of the real rebuild
    # timings per phase
    t = rec["timings_s"]
    assert t["total"] >= t["builds"] > 0 and t["connect"] is not None and t["first_response"] is not None
    assert t["model_api"] == pytest.approx(3.1) and t["agent_reported"] == pytest.approx(4.2)
    # checks outcome of the final build
    assert rec["checks"]["ok"] is True and rec["checks"]["gating_failed"] == [] and rec["checks"]["new_build"]
    assert sorted(rec["checks"]["fingerprint"]["bbox"]) == [6, 50, 80]
    assert rec["outcome"]["status"] == "ok" and rec["outcome"]["verified"] is True
    assert rec["outcome"]["agent_turns"] == 3
    # never in the user-facing stream: no model id, no record, no token internals
    stream = json.dumps(events)
    assert MODEL_ID not in stream and "run.json" not in stream and "cache_read" not in stream
    assert not any(e.get("type") == "run_record" for e in events)


def test_raw_prompt_kept_only_when_policy_allows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(runrecord.POLICY_ENV, "hash")
    s, _ = _run(tmp_path / "ws", prompt="plate please")
    rec = s.last_run_record or {}
    assert set(rec["prompt"]) == {"sha256", "chars", "policy"}


def test_failed_turn_still_recorded(tmp_path: Path) -> None:
    class Broken:
        def __init__(self, *_: Any) -> None: ...
        async def connect(self) -> None: ...
        async def query(self, prompt: str) -> None:
            raise RuntimeError("agent process died")

    events: list[dict[str, Any]] = []
    s = AgentSession(tmp_path / "ws", on_event=events.append)
    s.client_factory = Broken
    asyncio.run(s.send("anything"))
    rec = s.last_run_record or {}
    assert rec["outcome"]["status"] == "failed" and rec["checks"] is None
    assert runrecord.list_runs(s.workspace)[0]["status"] == "failed"
    assert any(e["type"] == "error" for e in events)


def test_load_rejects_unsafe_run_ids_and_prunes(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    assert runrecord.load(ws, "../../etc/passwd") is None and runrecord.load(ws, "") is None
    for i in range(5):
        r = runrecord.RunRecorder(ws, prompt=f"p{i}", mode="build", requested_model=None, run_id=f"r{i}")
        r.finish()
        r.write()
    runrecord.prune(ws, keep=3)
    assert len(runrecord.list_runs(ws)) == 3


# ------------------------------------------------------------------ admin-only access through the app
def test_run_records_are_admin_only(app_client: TestClient, tmp_path: Path,  # noqa: F811
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "cassette.json"
    f.write_text(json.dumps(_cassette()))
    monkeypatch.setenv("FW_AGENT_REPLAY", str(f))
    c = app_client
    signup(c, "runrec@x.com")
    pid = c.post("/api/projects", json={"name": "Plate"}).json()["id"]
    assert c.post(f"/api/projects/{pid}/agent/chat", json={"prompt": "plate 80 x 50 x 6", "skip_brief": True}
                  ).status_code == 200
    hist = _wait_idle(pid)
    assert MODEL_ID not in json.dumps(hist)
    assert c.get(f"/api/admin/projects/{pid}/runs").status_code == 403  # the customer cannot read it
    assert c.get(f"/api/projects/{pid}/files/run.json").status_code in (400, 404)

    from aicad.platform.routers.projects import _sessions

    for _ in range(100):  # the record is written as the turn closes
        if _sessions[pid].last_run_record:
            break
        import time

        time.sleep(0.1)
    c.post("/api/auth/logout")
    admin(c)
    items = c.get(f"/api/admin/projects/{pid}/runs").json()["items"]
    assert len(items) == 1 and items[0]["models"] == [MODEL_ID] and items[0]["status"] == "ok"
    rid = items[0]["run_id"]
    from aicad.platform.db import session_factory
    from aicad.platform.models import AgentRun

    db = session_factory()()
    try:
        assert db.get(AgentRun, rid) is not None  # the record shares the metering row's id
    finally:
        db.close()
    full = c.get(f"/api/admin/projects/{pid}/runs/{rid}").json()
    assert full["tokens"]["output_tokens"] == RESULT_USAGE["output_tokens"]
    assert c.get(f"/api/admin/projects/{pid}/runs/nope").status_code == 404
