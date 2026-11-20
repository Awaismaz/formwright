"""The intent compiler: a brief in natural language -> a design graph, through a strict JSON schema.

The model does only what needs language: it names the components the brief asks for, how they connect, the sizes the
brief states, and up to three questions when something that changes the design is ambiguous. Everything else is code:

* the schema (``INTENT_SCHEMA``) is strict; the provider validates the answer against it (``llm.CallRequest.schema``);
* provenance: a size the model gives that is not written in the brief is marked ``assumed`` (it is the model's
  guess, said so), never ``brief``;
* the brief's exclusions are hard constraints read by ``office/scope.py`` (``"just"``, ``"only"``, ``"no X"``):
  ``validate.repair`` drops what they rule out whatever the model wrote;
* sizing (``resolve``), validation (``validate``) and the deterministic questions (``questions``) follow.

Routing (PD-82, ``llm/routing.py``): role ``intent``; a small, simple brief (a shaft and what rides on it, no
housing, a short sentence) runs on the tier below Opus, anything else on Opus.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aicad.graph import questions as qmod
from aicad.graph import registry, resolve, validate
from aicad.graph.model import Component, Connection, Constraints, DesignGraph, Param, Question, slug

MAX_QUESTIONS = 3
VALUE = {"type": ["number", "string", "boolean"]}
INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["components", "connections"],
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string", "maxLength": 300},
        "components": {"type": "array", "minItems": 1, "maxItems": 60, "items": {
            "type": "object", "required": ["id", "kind", "name"], "additionalProperties": False,
            "properties": {
                "id": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,39}$"},
                "kind": {"enum": sorted(registry.COMPONENTS)},
                "name": {"type": "string", "minLength": 1, "maxLength": 80},
                "qty": {"type": "integer", "minimum": 1, "maximum": 500},
                "group": {"type": "string", "maxLength": 60},
                "material": {"type": "string", "maxLength": 60},
                "params": {"type": "object", "additionalProperties": VALUE}}}},
        "connections": {"type": "array", "maxItems": 120, "items": {
            "type": "object", "required": ["kind", "host", "guest"], "additionalProperties": False,
            "properties": {
                "kind": {"enum": sorted(registry.CONNECTIONS)},
                "host": {"type": "string"}, "guest": {"type": "string"},
                "via": {"type": "array", "items": {"type": "string"}, "maxItems": 40},
                "params": {"type": "object", "additionalProperties": VALUE}}}},
        "assumptions": {"type": "array", "items": {"type": "string", "maxLength": 240}, "maxItems": 10},
        "questions": {"type": "array", "maxItems": MAX_QUESTIONS, "items": {
            "type": "object", "required": ["id", "question", "options"], "additionalProperties": False,
            "properties": {
                "id": {"type": "string", "maxLength": 40}, "question": {"type": "string", "maxLength": 200},
                "options": {"type": "array", "minItems": 2, "maxItems": 6, "items": {"type": "string", "maxLength": 120}},
                "default": {"type": "string", "maxLength": 120}}}},
    },
}

SYSTEM = """You turn a mechanical design brief into a design graph: the components the brief asks for, how they \
connect, and the sizes the brief states. Code sizes everything else from standards (DIN 6885 keys, ISO 15 bearings, \
DIN 471 rings, centre distance m (z1 + z2) / 2) and lays it out, so:

- Plan exactly what the brief asks for. "just", "only", "no extra items", "no X", "without X" are hard limits: never \
add a part they rule out. A shaft with what it carries and no bearings or housing is a normal deliverable.
- A gear reducer or gearbox has a housing (a split base and a cover) carrying two bearings per shaft in its walls, a \
bearing cap over each bearing (open where the shaft leaves the housing, blind on the other side), cap screws that fix \
the caps and bolts that join the cover to the base; its gears are keyed on their shafts.
- Give a size only when the brief states it (module, teeth, a diameter, a length, a bearing designation, a ratio as \
the gear_mesh param "ratio"). Never invent sizes: leave them out.
- One component per distinct part; qty for identical pieces (four 6204 bearings = one bearing component, qty 4). \
Name parts plainly ("Input shaft", "Pinion", "Output gear", "Input open cap").
- Connections: host is the side that carries (the shaft for a hub or bearing, the housing for a bearing seat, the \
base for a bolted cover), guest the part it carries; via the parts that make the joint (the key of a keyed hub, the \
screws of a bolted joint). A gear "locked with a key" is keyed_hub; a hub against a step is shoulder_stop (and the \
shaft is stepped); each shaft's bearings are bearing_journal with param "count" (how many on that shaft), and in a \
housing also bearing_seat (host the housing).
- A planetary (epicyclic) gearbox: a sun gear keyed on the input shaft; N planet gears (one component, qty N) each \
running on a bearing on a planet pin (pin kind shaft, qty N: bearing_journal pin -> bearing with count 1, mounted_on \
bearing -> planet gear); the pins fixed in a planet carrier (kind hub, mounted_on carrier -> pin) keyed on the output \
shaft; a ring gear (spur_gear with internal true) mounted_on the housing; gear_mesh sun -> planet and planet -> ring. \
The planet bearings sit in the planet gears, never in the housing; only the input and output shafts run in housing \
bearings. Code sizes the ring (z_ring = z_sun + 2 z_planet) and the housing around it.
- Ask at most 3 questions, only when the answer changes which parts exist or how they connect (housing or not, the \
bearing type, the number of stages) or the material when the use makes it a real choice. Never ask about sizes. \
Each question has 2 to 4 short options, the most likely first, and a default. Build the components and connections \
for each question's default answer.

""" + registry.prompt_reference() + """

Answer with one JSON object only."""

_SIMPLE_MAX_CHARS = 300
_COMPLEX_WORDS = re.compile(r"\b(?:reducer|gear ?box|housing|casing|stages?|conveyor|gripper|fixture|actuator|"
                            r"enclosure|frame|machine|robot|linear|motor)\b", re.IGNORECASE)


def job_of(brief: str) -> str:
    """PD-82 job size of an intent call: ``simple`` for a short brief naming only a shaft and what rides on it (no
    housing, no machine words), else ``complex``."""
    from aicad.office import scope

    named, _excluded = scope.mentions(brief)
    text = brief or ""
    positive = _COMPLEX_WORDS.search(re.sub(r"\b(?:no|without)\s+(?:a\s+|any\s+)?\w+", " ", text, flags=re.IGNORECASE))
    if len(text) <= _SIMPLE_MAX_CHARS and named and named <= scope.NAMED_KINDS and not positive:
        return "simple"
    return "complex"


def constraints_of(brief: str) -> Constraints:
    from aicad.office import scope

    named, excluded = scope.mentions(brief)
    return Constraints(named=sorted(named), excluded=sorted(excluded), exclusive=scope.exclusive(brief))


def _num_in_brief(v: Any, brief: str) -> bool:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return isinstance(v, str) and v.lower() in (brief or "").lower()
    s = f"{float(v):g}"
    return re.search(rf"(?<![\d.]){re.escape(s)}(?![\d])", brief or "") is not None


def from_reply(data: dict[str, Any], name: str, brief: str, *, answers: dict[str, str] | None = None) -> DesignGraph:
    """The model's JSON (already schema-valid) as a graph: ids made unique, provenance checked against the brief, the
    brief's constraints attached. No sizing or repair yet (``compile_reply`` does the full pipeline)."""
    g = DesignGraph(name=name, brief=brief, summary=str(data.get("summary") or "")[:300], source="intent",
                    constraints=constraints_of(brief), answers=dict(answers or {}))
    idmap: dict[str, str] = {}
    for raw in data.get("components") or []:
        cid = g.new_id(str(raw.get("id") or raw.get("name") or "part"))
        idmap[str(raw.get("id"))] = cid
        c = Component(id=cid, kind=str(raw.get("kind")), name=" ".join(str(raw.get("name") or cid).split())[:80],
                      qty=max(1, min(500, int(raw.get("qty") or 1))), group=str(raw.get("group") or "")[:60],
                      material=str(raw.get("material") or "")[:60])
        for k, v in (raw.get("params") or {}).items():
            if v is None or v == "":
                continue
            src = "answer" if any(str(v).lower() in str(a).lower() for a in (answers or {}).values()) else \
                ("brief" if _num_in_brief(v, brief) else "assumed")
            if k == "designation" and isinstance(v, str) and v.isdigit():
                v = int(v)
            c.params[str(k)[:40]] = Param(value=v, source=src, note="" if src != "assumed" else "the model's guess")
        g.components.append(c)
    for raw in data.get("connections") or []:
        x = Connection(id=g.next_connection_id(), kind=str(raw.get("kind")),
                       host=idmap.get(str(raw.get("host")), str(raw.get("host"))),
                       guest=idmap.get(str(raw.get("guest")), str(raw.get("guest"))),
                       via=[idmap.get(str(v), str(v)) for v in raw.get("via") or []])
        for k, v in (raw.get("params") or {}).items():
            if v is not None and v != "":
                x.params[str(k)[:40]] = Param(value=v, source="brief" if _num_in_brief(v, brief) else "assumed")
        g.connections.append(x)
    g.assumptions = [" ".join(str(a).split())[:240] for a in data.get("assumptions") or []][:10]
    for q in (data.get("questions") or [])[:MAX_QUESTIONS]:
        opts = [str(o)[:120] for o in q.get("options") or []][:6]
        if len(opts) >= 2:
            g.questions.append(Question(id=slug(str(q.get("id") or "q"))[:40] or "q", question=str(q["question"])[:200],
                                        options=opts, default=str(q.get("default") or opts[0])[:120]))
    return g


@dataclass
class Result:
    """What the intent compiler hands the office: a validated graph (or None) and the questions to ask."""

    graph: DesignGraph | None
    issues: list[dict[str, Any]] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    text: str = ""
    model: str | None = None
    job: str = "complex"
    cost_usd: float | None = None
    tokens: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0
    error: str | None = None
    data: dict[str, Any] | None = None  # the model's reply as parsed (recorded for replay)

    @property
    def ok(self) -> bool:
        return self.graph is not None and not [i for i in self.issues if i["severity"] == "error"]


def compile_reply(data: dict[str, Any], name: str, brief: str, *, answers: dict[str, str] | None = None
                  ) -> tuple[DesignGraph, list[dict[str, Any]], list[Question]]:
    """The deterministic middle: reply -> graph -> repair -> answers applied -> resolve -> validate -> questions."""
    g = from_reply(data, name, brief, answers=answers)
    g = validate.repair(g)
    g = qmod.apply_answers(g, answers or {})
    g = resolve.resolve(g)
    qs = qmod.ask(g, answers or {})
    g.questions = qs
    return g, validate.issues(g), qs


def prompt_for(name: str, brief: str, notes: str = "", answers: dict[str, str] | None = None) -> str:
    p = f"Design: {name}\n\nBrief:\n{brief}"
    if answers:
        p += "\n\nThe engineer answered:\n" + "\n".join(f"{k}: {v}" for k, v in answers.items())
    if notes.strip():
        p += f"\n\nThe engineer asks for these changes:\n{notes.strip()}"
    return p


async def run(name: str, brief: str, *, notes: str = "", answers: dict[str, str] | None = None,
              budget_usd: float | None = None, cwd: Path | None = None, job: str | None = None) -> Result:
    """One model call (role ``intent``, routed by job size), then the deterministic middle. Never raises on a bad
    answer: the result carries the error and the office falls back to its planner."""
    from aicad import llm
    from aicad.llm import routing

    job = job or job_of(brief)
    model = routing.model_for("intent", job)
    t0 = time.perf_counter()
    req = llm.CallRequest(role="intent", system=SYSTEM, prompt=prompt_for(name, brief, notes, answers),
                          schema=INTENT_SCHEMA, budget_usd=budget_usd, cwd=cwd, model=model, max_tokens=8000,
                          standalone_system=True)
    res = await llm.complete(req)
    out = Result(None, text=res.text, model=res.metering.model, job=job, cost_usd=res.metering.cost_usd,
                 tokens=res.metering.usage.as_dict(), seconds=round(time.perf_counter() - t0, 2))
    data = res.data if isinstance(res.data, dict) else _json(res.text)
    if not isinstance(data, dict):
        out.error = "the answer had no design graph"
        return out
    out.data = data
    try:
        g, iss, qs = compile_reply(data, name, brief, answers=answers)
    except (ValueError, TypeError, KeyError) as e:
        out.error = f"the design graph could not be read ({e})"
        return out
    out.graph, out.issues, out.questions = g, iss, qs
    return out


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        s, e = (text or "").find("{"), (text or "").rfind("}")
        if 0 <= s < e:
            try:
                return json.loads(text[s:e + 1])
            except ValueError:
                return None
    return None
