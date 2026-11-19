"""PS-01..04: the fast agent build loop with deferred CHK-07/08, and the verdict that must wait for them."""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from typing import Any

import pytest

from aicad.agent import runner, worker
from aicad.agent.deferred import DeferredChecks, failed_deferred, has_pending
from aicad.agent.replay import message_from_dict
from aicad.agent.session import AgentSession
from aicad.agent.tools import build_handler, summarize

PLATE = '''from build123d import *
from aicad import fw
L = 40  # length
W = 20  # width
T = 5  # thickness
PARAMS = dict(L=L, W=W, T=T)
part = fw.feature("Plate", Box(L, W, T, align=(Align.CENTER, Align.CENTER, Align.MIN)))
result = part
EXPECTED = {"bbox": [L, W, T], "volume": L * W * T, "solids": 1}
'''

# CHK-02..05 pass, but every run gives a different length: only the deferred CHK-08 can catch it
DRIFT = '''from build123d import *
import random
L = 40 + random.random()
result = Box(L, 20, 5)
EXPECTED = {"bbox": [L, 20, 5], "volume": L * 100, "solids": 1}
'''


def _st(out: Path) -> dict[str, Any]:
    return json.loads((out / "status.json").read_text(encoding="utf-8"))


def _chk(st: dict[str, Any], cid: str) -> dict[str, Any]:
    return next(c for c in st["checks"] if c["id"] == cid)


def _ws(tmp: Path, src: str) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "model.py").write_text(src, encoding="utf-8")
    return tmp


# ------------------------------------------------------------------ runner semantics
def test_fast_agent_build_is_not_verified_until_both_deferred_checks_ran(tmp_path: Path) -> None:
    ws = _ws(tmp_path / "ws", PLATE)
    out = ws / "out"
    assert runner.main(ws / "model.py", out, determinism=True, fast=True) == 0
    st = _st(out)
    assert st["ok"] is True and st["verified"] is False and not runner.is_verified(st)
    assert st["pending_checks"] == ["CHK-07", "CHK-08"] and st["exports_pending"] is True
    assert (out / "topo.json").is_file() and (out / "preview.stl").stat().st_size > 84
    assert not (out / "part.step").exists()
    assert _chk(st, "CHK-07")["detail"]["pending"] and not _chk(st, "CHK-07")["gating"]
    bid = st["build_id"]

    assert runner.finalize(out, "exports") == 0
    st = _st(out)
    assert st["build_id"] == bid  # the viewer doesn't reload identical geometry
    assert _chk(st, "CHK-07")["passed"] and _chk(st, "CHK-07")["gating"] and (out / "part.step").is_file()
    assert st["pending_checks"] == ["CHK-08"] and st["exports_pending"] is False and not runner.is_verified(st)

    assert runner.finalize(out, "determinism") == 0
    st = _st(out)
    c8 = _chk(st, "CHK-08")
    assert c8["passed"] and c8["gating"] and c8["detail"] == {"fingerprint_equal": True, "step_bytes_equal": True}
    assert st["pending_checks"] == [] and st["verified"] is True and runner.is_verified(st)
    assert runner.finalize(out) == 2  # nothing left

    # same verdicts and the same STEP bytes as the old all-in-one build
    full = tmp_path / "full"
    assert runner.main(ws / "model.py", full, determinism=True) == 0
    fs = _st(full)
    assert {c["id"]: (c["passed"], c["gating"]) for c in fs["checks"]} == \
        {c["id"]: (c["passed"], c["gating"]) for c in st["checks"]}
    assert (full / "part.step").read_bytes() == (out / "part.step").read_bytes()
    assert fs["verified"] is True and fs["fingerprint"] == st["fingerprint"]


def test_deferred_determinism_failure_fails_the_build(tmp_path: Path) -> None:
    ws = _ws(tmp_path / "ws", DRIFT)
    out = ws / "out"
    assert runner.main(ws / "model.py", out, determinism=True, fast=True) == 0  # core checks pass
    assert _st(out)["ok"] is True
    assert runner.finalize(out) == 0
    st = _st(out)
    assert _chk(st, "CHK-07")["passed"] and not _chk(st, "CHK-08")["passed"]
    assert st["ok"] is False and st["verified"] is False and not runner.is_verified(st)
    assert [c["id"] for c in failed_deferred(st)] == ["CHK-08"]
    assert "BACKGROUND CHECKS ON YOUR PREVIOUS BUILD FAILED" in summarize(_st(out), failed_deferred(st))


def test_deferred_determinism_reruns_the_source_that_was_built(tmp_path: Path) -> None:
    ws = _ws(tmp_path / "ws", PLATE)
    out = ws / "out"
    runner.main(ws / "model.py", out, determinism=True, fast=True)
    (ws / "model.py").write_text(PLATE.replace("L = 40", "L = 55"), encoding="utf-8")  # the agent edits meanwhile
    runner.finalize(out)
    assert _st(out)["verified"] is True  # judged on what was built, not on the half-written next version


def test_superseded_finalize_writes_nothing(tmp_path: Path) -> None:
    ws = _ws(tmp_path / "ws", PLATE)
    out = ws / "out"
    runner.main(ws / "model.py", out, determinism=True, fast=True)
    runner._LAST[str(out)]["build_id"] = 1  # a newer build replaced the status this finalize was for
    before = (out / "status.json").read_bytes()
    assert runner.finalize(out) == runner.SUPERSEDED
    assert (out / "status.json").read_bytes() == before and not (out / "part.step").exists()


def test_interactive_fast_edit_keeps_its_semantics(tmp_path: Path) -> None:
    ws = _ws(tmp_path / "ws", PLATE)
    out = ws / "out"
    runner.main(ws / "model.py", out, determinism=False, fast=True)
    st = _st(out)
    assert st["pending_checks"] == ["CHK-07"] and _chk(st, "CHK-08")["detail"].get("note")
    runner.finalize(out)
    st = _st(out)
    assert st["verified"] is True and not _chk(st, "CHK-08")["gating"]


def test_is_verified_for_old_status_files() -> None:
    assert runner.is_verified({"ok": True, "exports_pending": False})
    assert not runner.is_verified({"ok": True, "exports_pending": True})
    assert not runner.is_verified({"ok": False})
    assert not runner.is_verified({"ok": True, "verified": False, "pending_checks": ["CHK-08"]})
    assert not runner.is_verified(None)


def test_summary_lists_pending_checks(tmp_path: Path) -> None:
    ws = _ws(tmp_path / "ws", PLATE)
    runner.main(ws / "model.py", ws / "out", determinism=True, fast=True)
    text = summarize(_st(ws / "out"))
    assert text.startswith("Overall gating checks: PASS")  # friendly_result keys on this prefix
    assert "[PENDING] CHK-07" in text and "[PENDING] CHK-08" in text and "not reported as verified" in text


# ------------------------------------------------------------------ build tool + background chain (real worker)
def test_build_tool_returns_before_the_exports_and_chain_completes(tmp_path: Path) -> None:
    ws = _ws(tmp_path / "ws", PLATE)
    out = ws / "out"
    bg = DeferredChecks("ps-tool", out)
    handler = build_handler(ws, out, "ps-tool", bg)

    async def go() -> None:
        try:
            res = await handler({"script": "model.py"})
            assert not res["is_error"] and res["content"][0]["text"].startswith("Overall gating checks: PASS")
            assert any(c["type"] == "image" for c in res["content"])  # render of the preview mesh
            assert bg.task is not None and bg.started == 1
            st = await bg.settle()
            assert st is not None and runner.is_verified(st) and (out / "part.step").is_file()
            assert (out / "part.stl").is_file() and (out / "model.glb").is_file()
            # a superseding build cancels the old chain if it hasn't run; failures of the previous one are reported
            (ws / "model.py").write_text(DRIFT, encoding="utf-8")
            await handler({"script": "model.py"})
            st = await bg.settle()
            assert st is not None and not runner.is_verified(st)
            (ws / "model.py").write_text(PLATE, encoding="utf-8")
            res = await handler({"script": "model.py"})
            assert "BACKGROUND CHECKS ON YOUR PREVIOUS BUILD FAILED" in res["content"][0]["text"]
            await bg.settle()
        finally:
            await worker.shutdown_all()

    asyncio.run(go())


def test_settle_rebuilds_in_full_when_the_worker_lost_the_shape(tmp_path: Path) -> None:
    ws = _ws(tmp_path / "ws", PLATE)
    out = ws / "out"
    runner.main(ws / "model.py", out, determinism=True, fast=True)  # in this process, not in the worker
    assert has_pending(_st(out))
    bg = DeferredChecks("ps-lost", out)

    async def go() -> dict[str, Any] | None:
        try:
            return await bg.settle()
        finally:
            await worker.shutdown_all()

    st = asyncio.run(go())
    assert st is not None and runner.is_verified(st) and not has_pending(st)


# ------------------------------------------------------------------ the turn's verdict
class _BuildingClient:
    """Stands in for the agent: each query writes the given design, builds it through the real build tool, then
    reports a result. Records the prompts it received."""

    def __init__(self, session: AgentSession, designs: list[str]) -> None:
        self.s, self.designs, self.prompts = session, list(designs), []
        self.handler = build_handler(session.workspace, session.out_dir, "ps-turn", session.deferred)

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def interrupt(self) -> None:
        return None

    async def query(self, prompt: str) -> None:
        self.prompts.append(prompt)

    async def receive_response(self) -> Any:
        if self.designs:
            (self.s.workspace / "model.py").write_text(self.designs.pop(0), encoding="utf-8")
            yield message_from_dict({"type": "assistant", "model": "fake", "content": [
                {"type": "tool_use", "id": f"b{len(self.prompts)}", "name": "mcp__cad__build_model", "input": {}}]})
            res = await self.handler({"script": "model.py"})
            yield message_from_dict({"type": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"b{len(self.prompts)}", "is_error": res["is_error"],
                 "content": [{"type": "text", "text": res["content"][0]["text"]}]}]})
        yield message_from_dict({"type": "assistant", "model": "fake", "content": [{"type": "text", "text": "Done."}]})
        yield message_from_dict({"type": "result", "subtype": "success", "num_turns": 2, "session_id": "s1",
                                 "total_cost_usd": 0.01 * len(self.prompts), "duration_ms": 1000})


def _turn(tmp: Path, designs: list[str]) -> tuple[list[dict[str, Any]], _BuildingClient, AgentSession]:
    events: list[dict[str, Any]] = []
    s = AgentSession(tmp / "ws", on_event=events.append, worker_key="ps-turn")
    client = _BuildingClient(s, designs)
    s.client_factory = lambda o: client

    async def go() -> None:
        try:
            await s.send("make a plate")
        finally:
            await worker.shutdown_all()

    asyncio.run(go())
    return events, client, s


def test_turn_verdict_waits_for_the_deferred_checks(tmp_path: Path) -> None:
    events, client, s = _turn(tmp_path, [PLATE])
    res = [e for e in events if e["type"] == "result"]
    assert len(res) == 1 and res[0]["build_verified"] is True
    st = _st(s.out_dir)
    assert runner.is_verified(st) and (s.out_dir / "part.step").is_file()  # complete before the result went out
    i_res = events.index(res[0])
    assert any(e["type"] == "tool_result" and e.get("brief") == "Verification complete" for e in events[:i_res])
    assert client.prompts == ["make a plate"]


def test_failed_deferred_check_gets_one_follow_up_and_is_never_verified(tmp_path: Path) -> None:
    events, client, s = _turn(tmp_path, [DRIFT, DRIFT])
    assert len(client.prompts) == 2 and client.prompts[1].startswith("[Background verification]")
    assert "CHK-08" in client.prompts[1]
    res = [e for e in events if e["type"] == "result"]
    assert len(res) == 1 and res[0]["build_verified"] is False  # one result for the whole turn
    assert res[0]["cost_est_usd"] == pytest.approx(0.02)  # both rounds are charged once, from the cumulative report
    assert not runner.is_verified(_st(s.out_dir))


def test_follow_up_that_fixes_the_design_ends_verified(tmp_path: Path) -> None:
    events, client, _s = _turn(tmp_path, [DRIFT, PLATE])
    assert len(client.prompts) == 2
    assert next(e for e in events if e["type"] == "result")["build_verified"] is True


def test_preview_stl_matches_the_viewer_mesh(tmp_path: Path) -> None:
    import struct

    ws = _ws(tmp_path / "ws", PLATE)
    runner.main(ws / "model.py", ws / "out", determinism=True, fast=True)
    topo = json.loads((ws / "out" / "topo.json").read_text(encoding="utf-8"))
    data = (ws / "out" / "preview.stl").read_bytes()
    n = struct.unpack("<I", data[80:84])[0]
    assert n == sum(len(f["idx"]) // 3 for f in topo["faces"]) and len(data) == 84 + 50 * n
    area = 0.0
    for k in range(n):
        v = struct.unpack("<12f", data[84 + 50 * k: 84 + 50 * k + 48])[3:]
        a, b, c = (v[0:3], v[3:6], v[6:9])
        u = [b[i] - a[i] for i in range(3)]
        w = [c[i] - a[i] for i in range(3)]
        cr = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
        area += math.sqrt(sum(x * x for x in cr)) / 2
    assert area == pytest.approx(2 * (40 * 20 + 40 * 5 + 20 * 5), rel=1e-6)  # hand calculation: box surface


# ------------------------------------------------------------------ PS-04 pre-connect
class _CountingClient:
    def __init__(self) -> None:
        self.connects = self.disconnects = 0

    async def connect(self) -> None:
        self.connects += 1
        await asyncio.sleep(0.05)

    async def disconnect(self) -> None:
        self.disconnects += 1

    async def query(self, prompt: str) -> None:
        return None

    async def interrupt(self) -> None:
        return None

    async def receive_response(self) -> Any:
        yield message_from_dict({"type": "result", "subtype": "success", "num_turns": 1, "session_id": "s",
                                 "total_cost_usd": 0.0, "duration_ms": 10})


def test_preconnect_is_reused_by_the_first_message_and_dropped_when_idle(tmp_path: Path) -> None:
    made: list[_CountingClient] = []

    def factory(_o: Any) -> _CountingClient:
        made.append(_CountingClient())
        return made[-1]

    async def go() -> None:
        s = AgentSession(tmp_path / "a")
        s.client_factory = factory
        pre = asyncio.create_task(s.preconnect(idle_s=0.2))
        await asyncio.sleep(0)
        await s.send("hello")  # arrives while the pre-connect is still starting: waits for it, one process only
        await pre
        await asyncio.sleep(0.4)
        assert len(made) == 1 and made[0].connects == 1 and made[0].disconnects == 0 and s.client is made[0]
        idle = AgentSession(tmp_path / "b")
        idle.client_factory = factory
        await idle.preconnect(idle_s=0.1)
        assert idle.client is made[1]
        await asyncio.sleep(0.3)
        assert idle.client is None and made[1].disconnects == 1  # nobody used it

    asyncio.run(go())
