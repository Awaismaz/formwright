"""The assembly agent (WORKLIST 51): one flowing conversation per assembly, typed actions, deterministic results.

No model is called: the role ``assembly_agent`` is served by the stub provider with recorded replies
(``tests/golden/assembly_agent/replies.json``, keyed by what the engineer says). Everything after the reply is the
real path: direct part builds through the check gate, Toolbox parts, shaft lines placed by construction, the solver,
the exact interference check.

Hand values (from the inputs, never measured from the built shapes):
- "stepped shaft Ø20 with a keyseat": journals Ø20 × (6204 width 14 + 2) = 16, seat Ø25 (a 2.5 mm shoulder), collar
  Ø30 × 8, hub width 20, seat 20 + 10 = 30. Along Z: journal 0..16, seat 16..46, collar 46..54, journal 54..70.
  Keyseat DIN 6885 for Ø25 (over 22 up to 30): b 8, t1 4; length = the longest standard length up to 20 - 4 = 16;
  centred in the hub: z 36 (28..44). Floor at 12.5 - 4 = 8.5 from the axis, on +Y.
- the gear "for" that shaft: bore Ø25 (the keyed seat), hub keyway DIN 6885 8 × 3.3, face width 16 + 4 = 20; against
  the collar shoulder: z 26..46. The key 8 × 7 × 16 on the floor: its origin (0, 8.5, 36), length along Z.
- two 6204 (20 × 47 × 14) on the journals against the shoulders: z 2..16 (the seat's step at 16) and 54..68 (the
  collar's step at 54).
- "2 mm wider": face width 22, still against the collar: z 24..46.
- with a circlip groove: DIN 471 for Ø25: s 1.2, d2 23.9, m 1.3, at the hub's free face: z 24.7..26; the ring
  against the groove wall away from the gear: z 24.7..25.9 (0.1 mm short of the gear face at 26).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from test_assembly import app_client  # noqa: F401  (fixture)
from test_assembly_ai import _setup

from aicad import llm
from aicad.assembly import chat, makers, trains, xform
from aicad.llm import routing
from aicad.llm.stub import StubProvider

REPLIES = json.loads((Path(__file__).parent / "golden" / "assembly_agent" / "replies.json").read_text(encoding="utf-8"))


def _stub() -> StubProvider:
    def responder(req: llm.CallRequest) -> str | None:
        if req.role != "assembly_agent":
            return None
        said = req.prompt.rsplit("[The engineer now says]\n", 1)[-1].strip()
        reply = REPLIES.get(said)
        assert reply is not None, f"no recorded reply for {said!r}"
        return "```json\n" + json.dumps(reply) + "\n```"
    return StubProvider(responder)


def _say(c: Any, aid: str, text: str) -> dict[str, Any]:
    r = c.post(f"/api/m/assembly/assemblies/{aid}/chat", json={"text": text, "wait": True})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["busy"] is None
    return v["messages"][-1]


def _view(c: Any, aid: str) -> dict[str, Any]:
    return c.get(f"/api/m/assembly/assemblies/{aid}").json()


def _inst(v: dict[str, Any], iid: str) -> dict[str, Any]:
    return next(i for i in v["instances"] if i["id"] == iid)


def _origin(v: dict[str, Any], iid: str) -> np.ndarray:
    return xform.pt(xform.from12(_inst(v, iid)["T"]), (0, 0, 0))


def _z(v: dict[str, Any], iid: str) -> np.ndarray:
    return xform.vec(xform.from12(_inst(v, iid)["T"]), (0, 0, 1))


def _x(v: dict[str, Any], iid: str) -> np.ndarray:
    return xform.vec(xform.from12(_inst(v, iid)["T"]), (1, 0, 0))


def _ids(v: dict[str, Any], prefix: str) -> list[str]:
    return [i["id"] for i in v["instances"] if i["name"].startswith(prefix)]


def _no_internals(msg: dict[str, Any]) -> None:
    text = json.dumps({k: msg.get(k) for k in ("text", "steps", "questions", "state_text")})
    for bad in ("make_part", "t_bring", "assembly_agent", "json", ".py", "claude", "sonnet", "opus", "$shaft",
                "\u2014"):
        assert bad not in text, bad


# ----------------------------------------------------------------------------- pure
def test_routing_and_job_size() -> None:
    assert "assembly_agent" in llm.ROLES
    assert chat.job_of("bring two 6204 bearings for that shaft and put them on") == "simple"
    assert chat.job_of("make the gear 2 mm wider") == "simple"
    assert chat.job_of("check for clashes") == "simple"
    assert chat.job_of("assemble everything") == "complex"
    assert chat.job_of("make a stepped shaft Ø20 with a keyseat, then bring a spur gear m2 z40 and a key, then "
                       "assemble them") == "complex"
    assert chat.job_of("make a bracket for the motor") == "complex"      # a new part with nothing to size it by
    assert routing.model_for("assembly_agent", "simple") == routing.TIERS["sonnet"]
    assert routing.model_for("assembly_agent", "complex") is None        # Opus, the provider default


def test_reply_contract_drops_unknown_and_scrubs() -> None:
    say, acts, qs = chat.parse_reply({
        "say": "I'll call make_part on model.py with claude-opus-5-5 \u2014 it is validated.",
        "actions": [{"do": "bring", "code": "bearing"}, {"do": "rm -rf"}, {"no": 1}],
        "questions": [{"question": "Which shaft?", "options": ["A", "B"]}, {"question": "x", "options": ["only"]},
                      {"question": "Two?", "options": ["1", "2"]}, {"question": "Three?", "options": ["1", "2"]}]})
    assert [a["do"] for a in acts] == ["bring"]
    assert "make_part" not in say and "model.py" not in say and "claude" not in say and "validated" not in say
    assert "\u2014" not in say
    assert chat.scrub("I put $gear (i3) on i1 and $shaft.") == "I put on and ."
    assert [q["question"] for q in qs] == ["Which shaft?", "Two?"]                          # at most 2, valid ones
    assert chat.parse_reply("not a dict") == ("", [], [])


def test_offline_reader() -> None:
    assert chat.offline("assemble everything")[1] == [{"do": "assemble", "parts": "all"}]
    assert chat.offline("check for clashes")[1][0]["do"] == "check"
    _say_text, acts = chat.offline("bring two 6204 bearings for the shaft and put them on")
    assert acts[0]["do"] == "bring" and acts[0]["code"] == "bearing" and acts[0]["qty"] == 2
    assert acts[0]["for"] == "shaft" and acts[-1] == {"do": "assemble", "parts": "all"}
    assert chat.offline("compose a sonnet")[1] == []
    # a clicked chip of the "which shaft" question reads without AI too
    assert chat.offline("Which shaft does Spur gear m2 z30 go on? Shaft #2")[1] == [
        {"do": "assemble", "parts": "all", "on": {"Spur gear m2 z30": "Shaft #2"}}]


def test_shaft_layout_by_hand() -> None:
    lay = makers.design_shaft({"journal_d": 20, "keyseat": True, "groove": True})
    assert [(s["d"], s["l"]) for s in lay["segments"]] == [(20, 16), (25, 30), (30, 8), (20, 16)]
    assert lay["hub"] == (26, 46) and lay["length"] == 70
    assert lay["keyseat"] == {"b": 8, "t1": 4, "length": 16, "center": 36, "d": 25}
    assert lay["groove"] == {"d1": 25, "d2": 23.9, "m": 1.3, "s": 1.2, "z0": pytest.approx(24.7), "z1": 26}
    assumed = makers.assumed(lay)
    assert any(a.startswith("seat Ø25 mm (a 2.5 mm shoulder") for a in assumed), assumed
    assert any(a.startswith("journal length 16 mm (bearing 6204 width 14") for a in assumed), assumed
    # hand volume: 4 cylinders - 2 chamfers - keyseat - groove (each by its own formula)
    cyl = math.pi * (100 * 16 * 2 + 156.25 * 30 + 225 * 8)
    chamfers = 2 * (0.5 * 2 * math.pi * (10 - 1 / 3))
    groove = math.pi / 4 * (25 ** 2 - 23.9 ** 2) * 1.3
    v = makers.shaft_volume(lay)
    assert cyl - chamfers - groove - v == pytest.approx(_keyseat_volume(12.5, 8, 4, 16), rel=1e-6)
    with pytest.raises(makers.MakeError):
        makers.design_shaft({"seat_d": 25})                     # no journal: ask, don't guess
    with pytest.raises(makers.MakeError):
        makers.design_gear({"module": 2, "teeth": 20, "bore": 40})   # no rim left


def _keyseat_volume(R: float, b: float, t1: float, L: float, n: int = 20000) -> float:
    """Independent midpoint sum of the rounded keyseat: slot area × depth to the cylinder at each point."""
    floor = R - t1
    tot = 0.0
    hw = b / 2
    for i in range(n):
        x = -hw + (i + 0.5) * b / n
        depth = math.sqrt(R * R - x * x) - floor
        half_len = (L - b) / 2 + math.sqrt(max(hw * hw - x * x, 0.0))
        tot += depth * 2 * half_len * b / n
    return tot


def test_sizes_follow_the_shaft() -> None:
    seat = {"d": 25.0, "length": 30.0, "lo": 16.0, "hi": 46.0}
    host = {"seats": [{"d": 20.0, "length": 16.0}, seat, {"d": 30.0, "length": 8.0}],
            "keyseats": [{"d": 25.0, "b": 8.0, "t1": 4.0, "length": 16.0}],
            "grooves": [{"d1": 25, "d2": 23.9}]}
    p, notes = makers.size_for_host("spur_gear", {"M": 2, "Z": 40}, host)
    assert (p["BORE"], p["KEY_B"], p["KEY_T2"], p["B"]) == (25, 8, 3.3, 20) and len(notes) == 3
    assert makers.size_for_host("bearing", {}, host)[0]["SERIES"] == 6204
    assert makers.size_for_host("parallel_key", {}, host)[0] == {"D": 25, "L": 16}
    assert makers.size_for_host("retaining_ring", {}, host)[0] == {"D": 25}
    assert makers.size_for_host("bearing", {"SERIES": 6004}, host)[0]["SERIES"] == 6004   # stated wins
    assert trains.gear_bore_ok(2, 40, 25)


# ----------------------------------------------------------------------------- conversations (kernel)
def test_conversation_make_bring_assemble_then_bearings_then_wider(app_client: Any) -> None:  # noqa: F811
    c = app_client
    _setup(c, "chat1@x.com")
    aid = c.post("/api/m/assembly/assemblies", json={"name": "Gear shaft"}).json()["assembly"]["id"]
    with llm.use_provider(_stub(), roles=("assembly_agent",)):
        # (1) make + bring + assemble in one message
        m = _say(c, aid, "make a stepped shaft Ø20 with a keyseat, then bring a spur gear m2 z40 and a key, then "
                         "assemble them")
        assert [s["status"] for s in m["steps"]] == ["ok", "ok", "ok", "ok"], m["steps"]
        _no_internals(m)
        v = _view(c, aid)
        shaft, gear, key = "i1", "i2", "i3"
        assert _inst(v, shaft)["fixed"] and _inst(v, shaft)["source"]["kind"] == "project"
        assert _inst(v, gear)["name"] == "Spur gear m2 z40, keyed 8×3.3"
        assert _inst(v, key)["name"] == "Parallel key DIN 6885 A 8×7×16"
        gp = next(p for p in v["parts"].values() if p["code"] == "spur_gear")["params"]
        assert (gp["BORE"], gp["B"], gp["KEY_B"], gp["KEY_T2"]) == (25, 20, 8, 3.3)
        # the gear against the collar: its axis on the shaft's, z 26..46 (either way round)
        o, z = _origin(v, gear), _z(v, gear)
        assert abs(o[0]) < 1e-6 and abs(o[1]) < 1e-6 and abs(abs(z[2]) - 1) < 1e-9
        assert sorted([o[2], o[2] + 20 * z[2]]) == pytest.approx([26, 46], abs=1e-6)
        # the key on the keyseat floor, centred, length along the axis
        assert _origin(v, key) == pytest.approx([0, 8.5, 36], abs=1e-6)
        assert abs(_x(v, key)[2]) == pytest.approx(1, abs=1e-9) and _z(v, key) == pytest.approx([0, 1, 0], abs=1e-9)
        assert all(mt["status"] == "ok" for mt in v["mates"]) and len(v["mates"]) >= 5
        assert m["state"]["unplaced"] == 0 and m["state"]["bad"] == 0
        # the made shaft is a real verified part with the hand volume
        sp = next(p for p in v["parts"].values() if p["kind"] == "project")
        lay = makers.design_shaft({"journal_d": 20, "keyseat": True})
        assert sp["volume"] == pytest.approx(makers.shaft_volume(lay), rel=1e-4)

        # (2) "that shaft" from the conversation; both bearings against the shoulders, the gear and key stay
        m = _say(c, aid, "bring two 6204 bearings for that shaft and put them on")
        assert [s["status"] for s in m["steps"]] == ["ok", "ok"], m["steps"]
        v = _view(c, aid)
        b1, b2 = _ids(v, "Ball bearing 6204")
        spans = sorted(sorted([_origin(v, b)[2], _origin(v, b)[2] + 14 * _z(v, b)[2]]) for b in (b1, b2))
        assert spans == [pytest.approx([2, 16], abs=1e-6), pytest.approx([54, 68], abs=1e-6)]
        assert _origin(v, key) == pytest.approx([0, 8.5, 36], abs=1e-6)
        assert m["state"]["unplaced"] == 0 and all(mt["status"] == "ok" for mt in v["mates"])

        # (4) "the gear" from the conversation: its own face width parameter, mates kept, still on the collar
        m = _say(c, aid, "make the gear 2 mm wider")
        assert m["steps"][0]["status"] == "ok", m["steps"]
        assert "20 → 22" in m["steps"][0]["lines"][0]
        v = _view(c, aid)
        assert _inst(v, gear)["name"] == "Spur gear m2 z40, keyed 8×3.3"
        o, z = _origin(v, gear), _z(v, gear)
        assert sorted([o[2], o[2] + 22 * z[2]]) == pytest.approx([24, 46], abs=1e-6)
        assert all(mt["status"] == "ok" for mt in v["mates"])
        assert "no clashes" in m["steps"][1]["lines"][0], m["steps"][1]

        # a spacer sized from the gap between two parts on the shaft, put in it
        m = _say(c, aid, "make a spacer between the first bearing and the gear")
        assert m["steps"][0]["status"] == "ok", m["steps"]
        assert "no clashes" in m["steps"][1]["lines"][0], m["steps"][1]
        v = _view(c, aid)
        sp = _ids(v, "Spacer")[0]
        part = next(p for p in v["parts"].values() if p["name"].startswith("Spacer"))
        assert part["bbox"][5] - part["bbox"][2] == pytest.approx(8, abs=1e-6)    # the gap 16..24
        o, z = _origin(v, sp), _z(v, sp)
        assert abs(o[0]) + abs(o[1]) < 1e-6 and sorted([o[2], o[2] + 8 * z[2]]) == pytest.approx([16, 24], abs=1e-6)
        assert all(mt["status"] == "ok" for mt in v["mates"]) and m["state"]["unplaced"] == 0
    # the conversation survives: read back from the server
    msgs = c.get(f"/api/m/assembly/assemblies/{aid}/chat").json()["messages"]
    assert [x["role"] for x in msgs] == ["user", "agent"] * 4
    assert msgs[0]["text"].startswith("make a stepped shaft")


def test_assemble_everything_six_loose_parts(app_client: Any) -> None:  # noqa: F811
    c = app_client
    _setup(c, "chat3@x.com")
    aid = c.post("/api/m/assembly/assemblies", json={"name": "Loose parts"}).json()["assembly"]["id"]
    with llm.use_provider(_stub(), roles=("assembly_agent",)):
        m = _say(c, aid, "make a stepped shaft Ø20 with a keyseat and a circlip groove, and bring a gear m2 z40, a key, "
                         "two 6204 bearings and a circlip for it")
        assert all(s["status"] == "ok" for s in m["steps"]), m["steps"]
        v = _view(c, aid)
        assert len(v["instances"]) == 6 and m["state"]["unplaced"] == 5 and not v["mates"]
        m = _say(c, aid, "assemble everything")
        assert m["steps"][0]["status"] == "ok", m["steps"]
        assert "no clashes" in m["steps"][1]["lines"][0], m["steps"][1]
        _no_internals(m)
    v = _view(c, aid)
    gear = _ids(v, "Spur gear")[0]
    key = _ids(v, "Parallel key")[0]
    ring = _ids(v, "Retaining ring")[0]
    o, z = _origin(v, gear), _z(v, gear)
    assert sorted([o[2], o[2] + 20 * z[2]]) == pytest.approx([26, 46], abs=1e-6)
    assert _origin(v, key) == pytest.approx([0, 8.5, 36], abs=1e-6)
    o, z = _origin(v, ring), _z(v, ring)
    assert sorted([o[2], o[2] + 1.2 * z[2]]) == pytest.approx([24.7, 25.9], abs=1e-6) and abs(o[0]) + abs(o[1]) < 1e-6
    spans = sorted(sorted([_origin(v, b)[2], _origin(v, b)[2] + 14 * _z(v, b)[2]]) for b in _ids(v, "Ball bearing"))
    assert spans == [pytest.approx([2, 16], abs=1e-6), pytest.approx([54, 68], abs=1e-6)]
    assert all(mt["status"] == "ok" for mt in v["mates"])
    assert v["analysis"]["interference"]["count"] == 0
    assert m["state"] == {**m["state"], "unplaced": 0, "bad": 0, "clashes": 0}
    joint = next(j for j in v["joints"] if j["type"] == "revolute")
    assert {gear, key, ring} <= set(joint["insts"])      # the key and ring turn with the shaft, bearings don't


def test_ambiguous_request_answered_by_a_chip(app_client: Any) -> None:  # noqa: F811
    c = app_client
    _setup(c, "chat5@x.com")
    aid = c.post("/api/m/assembly/assemblies", json={"name": "Two shafts"}).json()["assembly"]["id"]
    with llm.use_provider(_stub(), roles=("assembly_agent",)):
        _say(c, aid, "bring two Ø20 shafts and a spur gear m2 z30")
        before = _view(c, aid)
        # the code asks instead of guessing: one gear, two shafts
        m = _say(c, aid, "assemble everything")
        assert m["questions"] and m["questions"][0]["question"].startswith("Which shaft does Spur gear")
        assert len(m["questions"][0]["options"]) == 2 and not m["steps"]
        assert _view(c, aid)["instances"] == before["instances"]
        # the chip: the gear goes on the first shaft; the second one carries nothing, stays unplaced, and is moved
        # out of the gear's way (it sat where the gear now is)
        m = _say(c, aid, f"{m['questions'][0]['question']} {m['questions'][0]['options'][0]}")
        assert m["steps"][0]["status"] == "ok", m["steps"]
        assert any("nothing goes on it" in ln for ln in m["steps"][0]["lines"])
        v = _view(c, aid)
        assert {mt["a"]["inst"] for mt in v["mates"]} | {mt["b"]["inst"] for mt in v["mates"]} == {"i1", "i3"}
        assert m["state"]["unplaced"] == 1 and m["state"]["unplaced_names"] == ["Shaft Ø20×120 with keyway #2"]
        g_box = next(p for p in v["parts"].values() if p["code"] == "spur_gear")["bbox"]
        tip_r = (g_box[3] - g_box[0]) / 2
        assert abs(_origin(v, "i2")[0]) > tip_r + 10                   # beside the gear, not through it
        # the model asks too; the engineer clicks a chip
        m = _say(c, aid, "put the gear on a shaft")
        q = m["questions"][0]
        m = _say(c, aid, f"{q['question']} {q['options'][1]}")
        assert m["steps"][0]["status"] == "ok", m["steps"]
    v = _view(c, aid)
    s2 = xform.from12(_inst(v, "i2")["T"])
    o = _origin(v, "i3")
    # on the second shaft's axis, centred on its keyway at mid-length: z 52.5..67.5 along it
    rel = xform.pt(xform.inv(s2), o)
    assert abs(rel[0]) < 1e-6 and abs(rel[1]) < 1e-6
    assert sorted([rel[2], rel[2] + 15 * float(xform.vec(xform.inv(s2), _z(v, "i3"))[2])]) == \
        pytest.approx([52.5, 67.5], abs=1e-6)
    assert {mt["a"]["inst"] for mt in v["mates"]} | {mt["b"]["inst"] for mt in v["mates"]} == {"i2", "i3"}


def test_chat_api_rules(app_client: Any) -> None:  # noqa: F811
    c = app_client
    _setup(c, "chat6@x.com")
    aid = c.post("/api/m/assembly/assemblies", json={"name": "Rules"}).json()["assembly"]["id"]
    v = c.get(f"/api/m/assembly/assemblies/{aid}/chat").json()
    assert v["messages"] == [] and v["busy"] is None and v["can_edit"]
    assert c.post(f"/api/m/assembly/assemblies/{aid}/chat", json={"text": ""}).status_code == 422
    with llm.use_provider(StubProvider(lambda req: "no json here"), roles=("assembly_agent",)):
        m = _say(c, aid, "what is in it")                      # an unusable reply: the offline reader answers
    assert m["offline"] and m["steps"][0]["lines"][0].startswith("The assembly is empty")
    assert c.post(f"/api/m/assembly/assemblies/{aid}/chat/reset").json()["messages"] == []


def test_a_part_with_no_direct_builder_goes_to_the_design_agent(app_client: Any) -> None:  # noqa: F811
    """Unclear geometry: a Design Studio design-agent turn on a new part, followed in the chat; the offline stand-in
    design agent changes nothing, so the part is not verified and is honestly left out of the assembly."""
    import time

    c = app_client
    _setup(c, "chat7@x.com")
    aid = c.post("/api/m/assembly/assemblies", json={"name": "Bracket"}).json()["assembly"]["id"]
    with llm.use_provider(_stub(), roles=("assembly_agent",)), llm.use_provider(StubProvider(), roles=("design_agent",)):
        _say(c, aid, "bring two Ø20 shafts and a spur gear m2 z30")
        m = _say(c, aid, "make a motor bracket that holds this shaft line")
        assert m["steps"][0]["status"] == "info" and "design agent" in m["steps"][0]["lines"][0]
        pid = m["steps"][0]["project_id"]
        for _ in range(120):
            v = c.get(f"/api/m/assembly/assemblies/{aid}/chat").json()
            if all(j["status"] != "running" for j in v["jobs"]):
                break
            time.sleep(0.5)
    job = v["jobs"][-1]
    assert job["status"] == "failed" and job["project_id"] == pid
    assert "not verified" in v["messages"][-1]["text"] and "Design Studio" in v["messages"][-1]["text"]
    assert c.get(f"/api/projects/{pid}").status_code == 200        # the part exists in the workspace to finish
    assert len(_view(c, aid)["instances"]) == 3                      # and nothing unverified came into the assembly
