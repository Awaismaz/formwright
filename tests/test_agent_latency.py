"""agent-latency: fewer round trips (folder note, write-and-build), adaptive effort and model routing per turn, and the
short-script helpers (plate, gusset, cross hole, custom counterbore, compact limits). No model calls: fakes only.

Expected values are hand formulas: a plate (L W - (4 - pi) r²) T, a gusset 1/2 a b t, a cross hole the integral of
the hole's chord times the bar's chord (checked against an independent midpoint sum), a counterbored hole
pi/4 (d² h + (D² - d²) c)."""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ResultMessage

from aicad import fw
from aicad.agent import speed, tools
from aicad.agent.session import AgentSession, scrub
from aicad.llm import routing

OFFICE = (Path(__file__).parents[1] / "src/aicad/eval/latency_office_shaft.txt").read_text(encoding="utf-8")


# ------------------------------------------------------------------ helpers with hand formulas
def test_plate_gusset_cross_hole_and_custom_counterbore() -> None:
    from build123d import Align, Box, Pos

    fw.reset()
    part, e = fw.plate(90, 90, 10, corner_r=5)
    assert e["volume"] == pytest.approx((90 * 90 - (4 - math.pi) * 25) * 10)
    assert part.volume == pytest.approx(e["volume"], rel=1e-9)
    part, h = fw.holes_at(part, [(35, 35, 10), (-35, -35, 10)], {"d": 6.6, "cbore": (11, 6.5)}, 10)
    cb = math.pi / 4 * (6.6 ** 2 * 10 + (11 ** 2 - 6.6 ** 2) * 6.5)
    assert h["volume"] == pytest.approx(2 * cb) and part.volume == pytest.approx(e["volume"] - 2 * cb, rel=1e-9)
    # an 8 mm L-bracket: the gusset flush with the side face X = -40, legs 40 along the base and up the upright
    base = Box(80, 60, 8, align=(Align.CENTER, Align.MIN, Align.MIN)) + Pos(0, 52, 0) * Box(
        80, 8, 70, align=(Align.CENTER, Align.MIN, Align.MIN))
    g, v = fw.gusset(base, (-36, 52, 8), (0, -40, 0), (0, 0, 40), 8)
    assert v == pytest.approx(0.5 * 40 * 40 * 8) and g.volume - base.volume == pytest.approx(v, rel=1e-9)
    bb = g.bounding_box()
    assert (bb.min.X, bb.max.X) == pytest.approx((-40, 40))  # flush, nothing sticks out of the side face
    with pytest.raises(ValueError):
        fw.gusset(base, (0, 0, 0), (1, 0, 0), (2, 0, 0), 8)
    # cross hole Ø6 through a Ø16 bar: independent midpoint sum of 2 sqrt(r² - y²) 2 sqrt(R² - y²)
    n, r, R = 20000, 3.0, 8.0
    ref = sum(4 * math.sqrt(r * r - y * y) * math.sqrt(R * R - y * y) * (2 * r / n)
              for y in (-r + (i + 0.5) * 2 * r / n for i in range(n)))
    assert fw.cross_hole_volume(16, 6) == pytest.approx(ref, rel=1e-5)
    shaft, _ = fw.stepped_shaft([(30, 12), (16, 50)])
    cut, vol = fw.cross_hole(shaft, 6, 16, 22)
    assert shaft.volume - cut.volume == pytest.approx(vol, rel=1e-4) and cut.is_valid
    with pytest.raises(ValueError):
        fw.cross_hole_volume(10, 10)


def test_compact_limits_and_scrub() -> None:
    m = fw.meta("Plate", W=(50, 300, "Width"), T=(3, 20), C=(0, 2, "Chamfer", 0.05)) | fw.meta(HOLE_D=(3, 9))
    assert m["W"] == {"min": 50, "max": 300, "step": 1.0, "unit": "mm", "label": "Width", "group": "Plate"}
    assert m["T"]["step"] == 0.5 and m["C"]["step"] == 0.05 and m["HOLE_D"]["step"] == 0.1
    assert "group" not in m["HOLE_D"]
    with pytest.raises(ValueError):
        fw.meta(X=(5, 5))
    out = scrub("I used fw.gusset, fw.plate, fw.cross_hole and fw.meta")
    assert "fw." not in out and "the design tools" in out


# ------------------------------------------------------------------ write-and-build in one tool call
def test_build_tool_source_and_edits(tmp_path: Path) -> None:
    f = tmp_path / "model.py"
    assert tools.apply_source(f, {}) is None and not f.exists()  # plain build: nothing written
    assert "doesn't exist" in tools.apply_source(f, {"edits": [{"old": "a", "new": "b"}]})
    assert tools.apply_source(f, {"source": "A = 1\nB = 1\n"}) is None and f.read_text() == "A = 1\nB = 1\n"
    err = tools.apply_source(f, {"edits": [{"old": "= 1", "new": "= 2"}]})
    assert "occurs 2 times" in err and f.read_text() == "A = 1\nB = 1\n"  # all or nothing
    err = tools.apply_source(f, {"edits": [{"old": "A = 1", "new": "A = 3"}, {"old": "C", "new": "D"}]})
    assert "edit 2" in err and f.read_text() == "A = 1\nB = 1\n"
    assert tools.apply_source(f, {"edits": [{"old": "A = 1", "new": "A = 3"}, {"old": "B = 1", "new": "B = 4"}]}) is None
    assert f.read_text() == "A = 3\nB = 4\n"
    assert "not both" in tools.apply_source(f, {"source": "x", "edits": [{"old": "A", "new": "B"}]})
    assert {"script", "source", "edits"} <= set(tools.BUILD_SCHEMA["properties"])


# ------------------------------------------------------------------ what the agent is told, how hard it thinks
def test_folder_note_new_inlined_unchanged(tmp_path: Path) -> None:
    note, h = speed.folder_note(tmp_path, None)
    assert h is None and "no design yet" in note and "same response" in note
    (tmp_path / "model.py").write_text("A = 1\nresult = None\n", encoding="utf-8")
    note, h = speed.folder_note(tmp_path, None)
    assert "2 lines" in note and "```python\nA = 1\nresult = None\n```" in note and "edits" in note
    note2, _ = speed.folder_note(tmp_path, h)
    assert "unchanged since your last turn" in note2 and "```" not in note2
    note3, _ = speed.folder_note(tmp_path, None, mode="discuss")
    assert "```" not in note3
    (tmp_path / "model.py").write_text("x = 1\n" * (speed.INLINE_MAX_LINES + 1), encoding="utf-8")
    assert "Read it before changing it" in speed.folder_note(tmp_path, None)[0]


def test_request_classification_and_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(speed.ADAPTIVE_ENV, raising=False)
    assert speed.classify("Make the holes M8", True)["kind"] == "edit"
    assert speed.classify("Make the holes M8", False)["kind"] == "open"  # nothing to edit and no sizes
    assert speed.classify("Plate 120 × 80 × 8 mm with four Ø6.6 holes 10 mm in", False)["kind"] == "dimensioned"
    assert speed.classify("A bracket for a 2 kg motor: which material would you suggest?", False)["kind"] == "open"
    assert speed.classify("Plate 120 x 80 x 8 mm, 4 holes Ø6.6\n\n[Reference image(s) attached by the user: a]",
                          False)["kind"] == "open"
    assert speed.classify(OFFICE, False)["kind"] == "dimensioned"  # approved interfaces fix the part
    assert speed.choose_effort("Make the holes M8", True) == ("low", "local change to the existing design")
    assert speed.choose_effort("Design a gearbox", False)[0] is None
    assert speed.choose_effort("Design a gearbox", False, forced="high") == ("high", "FW_AGENT_EFFORT")
    monkeypatch.setenv(speed.ADAPTIVE_ENV, "0")
    assert speed.choose_effort("Make the holes M8", True) == (None, "adaptive effort off")


class _Ctl:
    def __init__(self, sink: list[Any]) -> None:
        self.sink = sink

    async def _send_control_request(self, req: dict[str, Any]) -> dict[str, Any]:
        self.sink.append(req)
        return {}


class _Fake:
    """An agent client with the real client's control surface (effort, model) and a canned result."""

    def __init__(self, options: Any) -> None:
        self.options, self.prompts, self.ctl, self.models = options, [], [], []
        self._query = _Ctl(self.ctl)

    async def connect(self, prompt: Any = None) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def set_model(self, model: str | None = None) -> None:
        self.models.append(model)

    async def query(self, prompt: str, session_id: str = "default") -> None:
        self.prompts.append(prompt)

    async def receive_response(self) -> Any:
        yield ResultMessage(subtype="success", duration_ms=10, duration_api_ms=9, is_error=False, num_turns=1,
                            session_id="s1", total_cost_usd=0.0)


def test_session_turn_settings_and_folder_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (speed.ADAPTIVE_ENV, "FW_AGENT_EFFORT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(routing, "_configured", dict)
    events: list[dict[str, Any]] = []
    s = AgentSession(tmp_path / "ws", on_event=events.append)
    s.client_factory = _Fake

    async def go() -> None:
        await s.send("Plate 120 × 80 × 8 mm with four Ø6.6 holes 10 mm in from both edges")
        c = s.client
        assert c.ctl == [{"subtype": "apply_flag_settings", "settings": {"effortLevel": "low"}}]
        assert "[Project folder: no design yet" in c.prompts[0]
        assert s.turn_settings["effort"] == "low" and s.turn_settings["folder"] == "new"
        assert s.last_run_record["turn"]["effort"] == "low"
        # the chat shows the user's words only
        user = [e for e in events if e["type"] == "user"]
        assert "Project folder" not in user[0]["text"]
        # an open request goes back to the harness default (None resets the flag)
        (s.workspace / "model.py").write_text("A = 1\n", encoding="utf-8")
        await s.send("Could you suggest a lighter design?")
        assert c.ctl[-1] == {"subtype": "apply_flag_settings", "settings": {"effortLevel": None}}
        assert "```python\nA = 1\n```" in c.prompts[1]  # changed since the agent last saw it: inlined
        await s.send("Make the holes M8")
        assert "unchanged since your last turn" in c.prompts[2] and s.turn_settings["effort"] == "low"
        # PD-82: simple part and edit on the lighter tier, the open request back on the default (Opus)
        assert c.models == ["claude-sonnet-5-5", None, "claude-sonnet-5-5"]
        assert s.last_run_record["turn"]["job"] == "edit"

    asyncio.run(go())
    st = json.loads((s.workspace / ".fw" / "agent.json").read_text(encoding="utf-8"))
    assert st["design_seen"] == speed.sha("A = 1\n")


def test_job_size_and_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routing, "_configured", dict)
    assert speed.job_of("Make the holes M8", True)["job"] == "edit"
    assert speed.job_of("Plate 120 × 80 × 8 mm with four Ø6.6 holes 10 mm in", False)["job"] == "simple"
    assert speed.job_of("Spur gear m2, 60 teeth, face 20 mm, bore 20 mm", False)["job"] == "complex"  # family
    assert speed.job_of("Gearbox housing for a 1:3 pair, 6 mm walls", False)["job"] == "complex"
    many = ("Block 100 x 60 x 40 mm with 4 holes, 2 slots, a pocket, chamfers, fillets, a thread, a keyway, a "
            "groove, a rib, a counterbore and a boss")
    assert speed.job_of(many, False)["job"] == "complex"  # 11 kinds of feature
    assert speed.job_of(OFFICE, False, {"program_parts": 4})["job"] == "simple"  # the pinion shaft, small program
    assert speed.job_of(OFFICE, False, {"program_parts": 12})["job"] == "complex"
    assert routing.model_for("design_agent", "complex") is None  # Opus = every provider's default
    assert routing.model_for("design_agent", "edit") == "claude-sonnet-5-5"
    assert routing.model_for("assembly_check") == "claude-haiku-5-5" and routing.model_for("planner") is None
    # an explicitly requested model always wins
    assert speed.route_model("Make the holes M8", True, "claude-opus-5-5")[0] == "claude-opus-5-5"
    # platform config overrides any route
    monkeypatch.setattr(routing, "_configured", lambda: routing.parse("design_agent.edit=opus, reviewer=haiku, "
                                                                       "librarian=default"))
    assert routing.model_for("design_agent", "edit") == "claude-opus-5-5"
    assert routing.model_for("reviewer") == "claude-haiku-5-5" and routing.model_for("librarian") is None
    assert routing.model_for("design_agent", "simple") == "claude-sonnet-5-5"  # unchanged default
    for bad in ("nosuchrole=opus", "design_agent.tiny=opus", "planner=gpt", "planner"):
        with pytest.raises(ValueError):
            routing.parse(bad)


def test_single_calls_get_their_routed_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from aicad import llm

    seen: list[Any] = []

    class _P(llm.LLMProvider):
        name, capabilities = "probe", frozenset({llm.CAP_COMPLETE})

        async def _complete(self, req: llm.CallRequest) -> llm.CallResult:
            seen.append(req.model)
            return llm.CallResult("ok", llm.Metering(self.name, req.role, req.model))

    monkeypatch.setattr(routing, "_configured", dict)
    with llm.use_provider(_P()):
        asyncio.run(llm.complete(llm.CallRequest(role="assembly_check", system="s", prompt="p")))
        asyncio.run(llm.complete(llm.CallRequest(role="planner", system="s", prompt="p")))
        asyncio.run(llm.complete(llm.CallRequest(role="reviewer", system="s", prompt="p", model="claude-x")))
    assert seen == ["claude-haiku-5-5", None, "claude-x"]
