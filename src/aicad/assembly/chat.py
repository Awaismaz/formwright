"""The assembly agent's conversation (WORKLIST 51): one persistent chat per assembly, stored server side.

Founder, 2026-11-20: "In assembly, I want the Chat to flow, instead of new prompt every time. The chat maintains the
context. The Agent intelligently decides based on history and understanding of project what is needed."

This module is the data side, pure and deterministic:

- the store: ``<assembly>/chat/chat.json`` holds the messages (the user's words; the agent's reply with the steps it
  ran and what each one found), the running turn (``busy``: what it is doing now) and background jobs (a part the
  design agent is making). It survives reloads; "New conversation" archives it.
- the live summary the model reads every turn: instances (with ids, where they are, what they are mated to and
  whether the solver satisfies those mates), loose parts, the last clash and motion checks, the parts the workspace
  can bring, the Toolbox families, and the project context (design memory, DS-040);
- the reply contract: one JSON object (``REPLY_SCHEMA``) with what to say, typed actions and at most two clickable
  questions. The model never writes code and never sizes geometry the code can size; every action is validated in
  ``agent`` before it runs, and an unknown one is dropped;
- the job size for model routing (``job_of``, PD-82): simple turns on Sonnet, multi-step or unclear ones on Opus;
- an offline reader for the common requests when no AI is available (no tokens).

Everything shown to the engineer is scrubbed of internals (``agent.session.scrub`` plus the action names here).
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from aicad.assembly import service, store

MAX_MESSAGES = 300
HISTORY_MESSAGES = 14       # what the model reads of the conversation each turn (older turns are summarised)
MAX_TEXT = 4000
TURN_MAX_TOKENS = 40        # hard cap (platform tokens) for one agent turn's model call
ACTIONS = ("find", "bring", "make", "mate", "assemble", "check", "move", "remove", "replace", "resize", "explain")
HOWS = ("auto", "keyed_hub", "hub_fit", "shoulder_stop", "bearing_journal", "gear_mesh", "ring_retained", "key_in_seat",
        "bolted_joint", "mounted_on", "coaxial")

_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def lock(aid: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(aid, threading.Lock())


# ----------------------------------------------------------------------------- store
def _dir(root: Path, aid: str) -> Path:
    return store.doc_dir(root, aid) / "chat"


def load(root: Path, aid: str) -> dict[str, Any]:
    d = store.read_json(_dir(root, aid) / "chat.json")
    if not isinstance(d, dict):
        d = {}
    d.setdefault("messages", [])
    d.setdefault("jobs", [])
    d.setdefault("busy", None)
    d.setdefault("seq", 0)
    return d


def save(root: Path, aid: str, chat: dict[str, Any]) -> None:
    chat["messages"] = chat["messages"][-MAX_MESSAGES:]
    p = _dir(root, aid)
    p.mkdir(parents=True, exist_ok=True)
    store.write_json(p / "chat.json", chat)


def update(root: Path, aid: str, fn: Any) -> dict[str, Any]:
    """Read, change and write the chat under its lock (turns, jobs and the API all go through here)."""
    with lock(aid):
        chat = load(root, aid)
        fn(chat)
        save(root, aid, chat)
        return chat


def next_id(chat: dict[str, Any]) -> str:
    chat["seq"] = int(chat.get("seq", 0)) + 1
    return f"c{chat['seq']}"


def reset(root: Path, aid: str) -> None:
    """New conversation: the old one is kept next to it (``chat.<n>.json``), never shown again."""
    with lock(aid):
        p = _dir(root, aid)
        f = p / "chat.json"
        if f.is_file():
            n = len(list(p.glob("chat.*.json"))) + 1
            f.replace(p / f"chat.{n}.json")


def user_message(chat: dict[str, Any], text: str, by: str | None) -> dict[str, Any]:
    m = {"id": next_id(chat), "role": "user", "text": text[:MAX_TEXT], "at": store.now(), "by": by}
    chat["messages"].append(m)
    return m


# ----------------------------------------------------------------------------- the live summary
def _g(x: float) -> str:
    return f"{round(float(x), 3):g}"


def _role(part: dict[str, Any], name: str) -> str:
    """What an instance is, for the summary and the agent: shaft / gear / hub / bearing / key / ring / fastener /
    nut / washer / dowel / plate / bracket / housing / other."""
    if part.get("kind") == "toolbox":
        return {"shaft": "shaft", "spur_gear": "gear", "bearing": "bearing", "parallel_key": "key",
                "retaining_ring": "ring", "hex_bolt": "fastener", "shcs": "fastener", "hex_nut": "nut",
                "washer": "washer", "dowel": "dowel", "standoff": "spacer", "flange": "flange",
                "l_bracket": "bracket"}.get(str(part.get("code")), "other")
    comp = ((part.get("info") or {}).get("component") or {}).get("kind")
    if comp == "spur_gear":
        return "gear"
    from aicad.graph import registry

    k = registry.kind_from_name(name)
    return {"spur_gear": "gear", "retaining_ring": "ring", "fastener": "fastener", "pulley": "hub"}.get(k, k)


def role_of(root: Path, doc: dict[str, Any], iid: str) -> str:
    inst = service._inst(doc, iid)
    return _role(store.part(root, inst["part"]) or {}, inst["name"])


def mate_state(doc: dict[str, Any]) -> dict[str, Any]:
    """Mates as the solver left them: counts by status, and each instance's mate partners and their status."""
    solve = (doc.get("solve") or {}).get("mates", {})
    counts = {"total": 0, "ok": 0, "unsatisfied": 0, "conflict": 0, "broken": 0, "suppressed": 0}
    per: dict[str, list[tuple[str, str]]] = {}
    for m in doc["mates"]:
        st = solve.get(m["id"], {})
        status = ("broken" if m.get("broken") else "suppressed" if m.get("suppressed") else "conflict"
                  if st.get("conflict") else "unsatisfied" if st and not st.get("ok") else "ok")
        counts["total"] += 1
        counts[status] += 1
        a, b = m["a"]["inst"], m["b"]["inst"]
        per.setdefault(a, []).append((b, status))
        per.setdefault(b, []).append((a, status))
    return {"counts": counts, "per": per}


def loose(doc: dict[str, Any]) -> list[str]:
    """Instances that nothing places: no mate and not fixed (fastener stacks place themselves)."""
    ms = mate_state(doc)["per"]
    return [i["id"] for i in doc["instances"] if not i.get("fixed") and not i.get("group") and i["id"] not in ms]


def state_line(root: Path, doc: dict[str, Any]) -> dict[str, Any]:
    """The honest status after a turn: mates (as the solver says), unplaced parts, the last clash check if current."""
    ms = mate_state(doc)
    c = ms["counts"]
    an = store.read_json(store.doc_dir(root, doc["id"]) / "analysis.json") or {}
    current = bool(an) and an.get("signature") == service.geometry_signature(doc)
    clashes = (an.get("interference") or {}).get("count") if current else None
    names = service.human_names(doc)
    lo = loose(doc)
    return {"parts": len([i for i in doc["instances"] if not i.get("group")]), "mates": c["total"], "ok": c["ok"],
            "bad": c["unsatisfied"] + c["conflict"] + c["broken"], "unplaced": len(lo),
            "unplaced_names": [names[i] for i in lo][:8], "clashes": clashes}


def state_text(st: dict[str, Any]) -> str:
    bits = [f"{st['parts']} part{'s' if st['parts'] != 1 else ''}"]
    if st["mates"]:
        bits.append(f"{st['mates']} mate{'s' if st['mates'] != 1 else ''}, "
                    + ("all satisfied by the solver" if not st["bad"] else f"{st['bad']} not satisfied"))
    else:
        bits.append("no mates yet")
    bits.append("nothing unplaced" if not st["unplaced"] else
                f"{st['unplaced']} unplaced ({', '.join(st['unplaced_names'])})")
    if st["clashes"] is not None:
        bits.append(f"{st['clashes']} clash{'es' if st['clashes'] != 1 else ''} (exact check)")
    else:
        bits.append("clash check not run since the last change")
    return "; ".join(bits)


def _pt(T: list[float], c: Any) -> str:
    from aicad.assembly import xform

    p = xform.pt(xform.from12(T), c)
    return f"({_g(p[0])}, {_g(p[1])}, {_g(p[2])})"


def _part_line(root: Path, part: dict[str, Any], role: str) -> str:
    """What a part is, in the words that matter for assembling it."""
    prm = part.get("params") or {}
    if part.get("kind") == "toolbox":
        bits = [f"Toolbox {part.get('code')} " + " ".join(f"{k}={_g(v)}" for k, v in prm.items())]
    else:
        bits = ["your part"]
    if role == "shaft":
        try:
            from aicad.assembly import trains

            sg = trains.shaft_geom(root, part["key"])
        except Exception:  # noqa: BLE001  (the summary never fails on one part's geometry)
            sg = None
        if sg:
            seats = sorted(sg["seats"], key=lambda s: s["lo"])
            bits.append("seats " + ", ".join(
                f"Ø{_g(s['d'])}×{_g(s['length'])}" + ("+shoulder" if any((e or {}).get("shoulder") for e in s["ends"].values())
                                                      else "") for s in seats))
            for k in sg.get("keyseats") or []:
                bits.append(f"keyseat {_g(k['b'])}×{_g(k['t1'])} L{_g(k['length'])} on the Ø{_g(k['d'])} seat")
            for g in sg.get("grooves") or []:
                bits.append(f"circlip groove Ø{_g(g['d2'])} (DIN 471 Ø{_g(g['d1'])})")
    comp = (part.get("info") or {}).get("component") or {}
    if comp.get("kind") == "spur_gear" and part.get("kind") != "toolbox":
        cp = comp.get("params") or {}
        bits.append(f"gear m{cp.get('module')} z{cp.get('teeth')}")
    return "; ".join(bits)


def summary(root: Path, doc: dict[str, Any], candidates: list[dict[str, Any]] | None = None,
            context: str = "", jobs: list[dict[str, Any]] | None = None) -> str:
    """The compact live state the model reads each turn (ids are how it refers to parts in its actions)."""
    names = service.human_names(doc)
    parts = service._parts(root, doc) if doc["instances"] else {}
    ms = mate_state(doc)
    lines = [f'ASSEMBLY "{service.clean_name(doc["name"])}"']
    if not doc["instances"]:
        lines.append("Empty: no parts yet.")
    for i in doc["instances"]:
        if i.get("group"):
            continue
        p = parts[i["part"]]
        role = _role(p, i["name"])
        partners = ms["per"].get(i["id"], [])
        where = "fixed base" if i.get("fixed") else ("UNPLACED (no mates)" if not partners else "placed by mates")
        mates = ""
        if partners:
            by: dict[str, list[str]] = {}
            for o, s in partners:
                by.setdefault(o, []).append(s)
            mates = "; mated to " + ", ".join(
                f"{o} ({len(v)} {'ok' if all(x == 'ok' for x in v) else 'NOT all satisfied'})" for o, v in by.items())
        lines.append(f"- {i['id']} \"{names[i['id']]}\" [{role}] {where}, centre at "
                     f"{_pt(i['T'], p['info']['center'])}{mates}. {_part_line(root, p, role)}")
    stacks = [g for g in doc.get("groups") or [] if g.get("kind") == "fastener"]
    if stacks:
        lines.append(f"Fastener stacks: {len(stacks)}")
    c = ms["counts"]
    lines.append(f"Mates: {c['total']} ({c['ok']} satisfied, {c['unsatisfied'] + c['conflict']} not satisfied, "
                 f"{c['broken']} broken)")
    if doc.get("joints"):
        lines.append("Motion joints: " + ", ".join(f"{j.get('name')} ({j['type']})" for j in doc["joints"]))
    st = state_line(root, doc)
    lines.append("Clash check: " + ("not run since the last change" if st["clashes"] is None else
                                    f"{st['clashes']} clashes, current"))
    mo = store.read_json(store.doc_dir(root, doc["id"]) / "motion.json") or {}
    if mo and mo.get("signature") == service.geometry_signature(doc):
        lines.append(f"Motion check: {len(mo.get('colliding_steps') or [])} colliding steps of {len(mo.get('steps') or [])}")
    for j in jobs or []:
        if j.get("status") == "running":
            lines.append(f"Being designed now in the Design Studio: \"{j['name']}\" (it comes in when it is verified)")
    if candidates:
        lines.append("Workspace parts you can bring (verified builds):")
        for cd in candidates[:15]:
            lines.append(f"- {cd['id']} \"{service.clean_name(cd['name'])}\"" +
                         (f": {cd['description'][:80]}" if cd.get("description") else ""))
    if context:
        lines.append("Project context:\n" + context[:1500])
    return "\n".join(lines)


def history(chat: dict[str, Any], n: int = HISTORY_MESSAGES) -> str:
    """The conversation so far, compact: the user's words, what the agent said and what each step did (with ids)."""
    msgs = chat["messages"][-n:]
    out = []
    if len(chat["messages"]) > n:
        out.append(f"({len(chat['messages']) - n} earlier messages not shown)")
    for m in msgs:
        if m["role"] == "user":
            out.append(f"Engineer: {m['text']}")
            continue
        t = m.get("text") or ""
        steps = "; ".join(f"{s.get('label')}: {' / '.join(s.get('lines') or [])}"
                          + (f" [parts {', '.join(s['parts'])}]" if s.get("parts") else "")
                          for s in m.get("steps") or [])
        q = "; ".join(f"asked: {x['question']} ({' | '.join(x['options'])})" for x in m.get("questions") or [])
        out.append("You: " + " ".join(x for x in (t, f"[done: {steps}]" if steps else "", q) if x)[:1500])
    return "\n".join(out)


# ----------------------------------------------------------------------------- the reply contract
REPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["say", "actions"],
    "properties": {
        "say": {"type": "string", "maxLength": 1500},
        "actions": {"type": "array", "maxItems": 12,
                    "items": {"type": "object", "required": ["do"],
                              "properties": {"do": {"type": "string", "enum": list(ACTIONS)}}}},
        "questions": {"type": "array", "maxItems": 2,
                      "items": {"type": "object", "required": ["question", "options"],
                                "properties": {"id": {"type": "string"}, "question": {"type": "string"},
                                               "options": {"type": "array", "minItems": 2, "maxItems": 5,
                                                           "items": {"type": "string"}},
                                               "default": {"type": ["string", "null"]}}}},
    },
}


def _toolbox_reference() -> str:
    from aicad import toolbox

    out = []
    for c in toolbox.COMPONENTS.values():
        ps = ", ".join(f"{p.name} ({p.label}{', ' + p.unit if p.unit else ''})" for p in c.params)
        out.append(f"- {c.code}: {c.name} {c.standard}: {ps}")
    return "\n".join(out)


INSTRUCTIONS = """You are the assembly agent of Assembly Studio, a CAD assembly workspace for mechanical engineers. \
You talk with the engineer in one flowing conversation and decide, from what they say, the conversation so far and \
the live state of the assembly, what to do next. You act only through the typed actions below; you never write code \
and you never model geometry yourself. The software sizes, places and checks everything deterministically: you choose \
what happens, it measures what happened.

Answer with exactly one JSON object: {"say": "...", "actions": [...], "questions": [...]}.
- "say": one to three short sentences to the engineer, in plain engineering words, BEFORE the actions run: what you \
are going to do, or the answer to their question. Never claim a result (mated, satisfied, no clashes, done): the \
software reports results after the actions run. Never mention actions, JSON, ids, files, code, tools or models.
- "actions": run in order. Refer to parts by instance id (i3), by a label you gave an earlier action of this turn \
("$shaft"), or by a short name ("the gear"). Resolve "that shaft", "the gear I just made", "the left one" from the \
conversation and the state (positions are in the state).
- "questions": only when the request is genuinely ambiguous and guessing could put a part in the wrong place; at most \
2, each with 2 to 5 short clickable options. When you ask, do not also act on the ambiguous part.

Actions:
- {"do": "find", "query": "6204 bearing"}: search the assembly, the workspace parts and the Toolbox; shows matches.
- {"do": "bring", "code": "<toolbox code>", "params": {...}, "qty": 1, "for": "<part>", "as": "$label"}: insert a \
Toolbox component. Give only the parameters the engineer stated (module, teeth, designation...); with "for" the \
software sizes the rest from that part (a bearing for a shaft gets the journal bore; a gear the keyed seat's bore, \
keyway and face width; a key the keyseat's size; a circlip the groove's size). \
Or {"do": "bring", "part": "<workspace part id>", "qty": 1, "as": "$label"} for one of the workspace parts. \
Brought parts come in unplaced: follow with "mate" or "assemble" when they should be put somewhere.
- {"do": "make", "kind": "shaft", "spec": {"journal_d": 20, "keyseat": true, "groove": false, "seat_d": null, \
"collar_d": null, "hub_width": null, "journal_l": null, "seat_l": null}, "name": "...", "as": "$label"}: a stepped \
shaft (journals | hub seat against a collar | journal); give what was stated, leave the rest null. \
{"do": "make", "kind": "gear", "spec": {"module": 2, "teeth": 40, "face_width": null, "bore": null, "keyway": true}, \
"for": "<shaft>"}: a spur gear (bore, keyway and face width from the shaft when "for" is given). \
{"do": "make", "kind": "spacer", "spec": {"bore": null, "length": null, "od": null}, "between": ["<part>", "<part>"]}: \
a spacer, sized from the gap between two parts on one shaft. \
{"do": "make", "kind": "other", "name": "...", "brief": "<a full design brief with every size you know and the \
mating features>", "for": "<part>"}: anything else, designed by the design agent in the Design Studio (it takes \
minutes and costs more; the part comes in when it is verified). Prefer the direct kinds when they fit.
- {"do": "mate", "part": "<part>", "to": "<part>", "how": "<kind>"}: put one part on another the intended way. \
how: keyed_hub (gear / pulley / hub on a keyed shaft seat, with its key), hub_fit, shoulder_stop, bearing_journal, \
gear_mesh (two gears, each on its shaft), ring_retained (circlip in its groove), key_in_seat, bolted_joint, \
mounted_on, coaxial, auto.
- {"do": "assemble", "parts": ["<part>", ...]} or {"do": "assemble", "parts": "all"}: assemble those parts (or \
everything) where they belong: shaft lines with their gears, keys, circlips and bearings, gear meshes, bolted joints.
- {"do": "check", "what": ["interference", "clearance", "motion", "visual"]}: run the checks; results are reported.
- {"do": "move", "part": "<part>", "by": [dx, dy, dz]}, {"do": "remove", "part": "<part>"}, \
{"do": "replace", "part": "<part>", "code": "<toolbox code>", "params": {...}}, \
{"do": "resize", "part": "<part>", "param": "<name or plain word: face width, length, bore, teeth>", "by": 2} or \
"to": 22: a resize changes the part's own parameters (Toolbox parameters or the design's PARAMS) and keeps its mates.
- {"do": "explain"}: describe the assembly state in plain words (the software writes the facts).

Rules: units are mm. A shaft line is assembled by its shoulders, keyseats and grooves; bearings go two per shaft. Never \
claim a mate is satisfied, a part fits, or anything is fit for manufacture or validated. Unplaced parts are unplaced. \
Keep "say" short. If the engineer only asks a question, answer it in "say" with no actions (or "explain").

Toolbox components (code: name standard: parameters):
"""


def system_prompt() -> str:
    return INSTRUCTIONS + _toolbox_reference()


def prompt(summary_text: str, history_text: str, text: str) -> str:
    return (f"[Assembly state]\n{summary_text}\n\n[Conversation so far]\n{history_text or '(none)'}\n\n"
            f"[The engineer now says]\n{text}")


# ----------------------------------------------------------------------------- routing (PD-82)
_ALL = re.compile(r"\b(all|everything|whole|entire|every part|all of (?:it|them))\b", re.IGNORECASE)
_VERBS = {"make": r"\b(make|design|create|model)\b", "bring": r"\b(bring|add|insert|get|fetch)\b",
          "assemble": r"\b(assemble|mate|put|mount|fit|place|seat|attach)\b", "check": r"\b(check|clash|interfer)",
          "edit": r"\b(move|remove|delete|replace|swap|resize|wider|narrower|longer|shorter|bigger|smaller)\b"}


def job_of(text: str) -> str:
    """``complex`` (Opus): assemble everything, several kinds of work in one message, or a new part with no
    numbers to go on; else ``simple`` (Sonnet: bring, mate, check, a sized part, an edit)."""
    t = text or ""
    kinds = [k for k, rx in _VERBS.items() if re.search(rx, t, re.IGNORECASE)]
    if re.search(_VERBS["assemble"], t, re.IGNORECASE) and _ALL.search(t):
        return "complex"
    if len(kinds) >= 3:
        return "complex"
    if "make" in kinds and not re.search(r"\d", t):
        return "complex"
    return "simple"


# ----------------------------------------------------------------------------- reply parsing and scrubbing
_INTERNAL = re.compile(r"\b(" + "|".join(ACTIONS[:-1]) + r")_\w+\b|\bjson\b|\b[ip]_[0-9a-f]{6,}\w*\b|"
                       r"\bclaude[-\w.]*|\b(?:opus|sonnet|haiku)\b|\b\w+\.py\b|```|\$\w+|\(\bi\d{1,4}\)|\bi\d{1,4}\b",
                       re.IGNORECASE)
_CLAIM = re.compile(r"\b(validated|certified|ready for (?:manufactur\w*|production)|safe to (?:run|use|manufacture))\b",
                    re.IGNORECASE)


def scrub(text: str) -> str:
    """No internals and no validity claims in what the engineer reads."""
    from aicad.agent.session import scrub as base

    t = base(str(text or ""))
    t = _INTERNAL.sub("", t)
    t = _CLAIM.sub("checked", t)
    t = t.replace(" \u2014 ", ", ").replace("\u2014", ", ").replace(" \u2013 ", ", ")
    return re.sub(r"[ \t]{2,}", " ", t).replace(" ,", ",").strip()


def clean_questions(qs: Any) -> list[dict[str, Any]]:
    out = []
    for k, q in enumerate(qs or []):
        if not isinstance(q, dict):
            continue
        opts = [scrub(str(o))[:80] for o in q.get("options") or [] if str(o).strip()][:5]
        if len(opts) < 2 or not str(q.get("question") or "").strip():
            continue
        d = q.get("default")
        out.append({"id": str(q.get("id") or f"q{k + 1}")[:20], "question": scrub(str(q["question"]))[:200],
                    "options": opts, "default": d if d in opts else None, "multi": False, "other": True})
    return out[:2]


def parse_reply(data: Any) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """(say, actions, questions) from the model's validated JSON; unknown actions dropped."""
    if not isinstance(data, dict):
        return "", [], []
    acts = [a for a in data.get("actions") or [] if isinstance(a, dict) and a.get("do") in ACTIONS][:12]
    return scrub(str(data.get("say") or ""))[:1500], acts, clean_questions(data.get("questions"))


# ----------------------------------------------------------------------------- the offline reader (no AI)
def offline(text: str) -> tuple[str, list[dict[str, Any]]]:
    """The common requests read without a model: assemble everything, check, explain, bring a Toolbox part by its
    description (Hex reads it), remove. Anything else asks the engineer to rephrase or to use the quick tools."""
    from aicad.assembly import librarian

    t = (text or "").strip()
    low = t.lower()
    m = re.match(r"^which shaft does (.+?) go on\?\s+(.+)$", t, re.IGNORECASE | re.DOTALL)
    if m:   # the answer to the assemble-everything question (a clicked chip)
        return "Thanks, assembling it that way.", [{"do": "assemble", "parts": "all",
                                                    "on": {m.group(1).strip(): m.group(2).strip()}}]
    if re.search(r"\b(assemble|put|mate)\b", low) and _ALL.search(low):
        return "I'll assemble everything where it belongs.", [{"do": "assemble", "parts": "all"}]
    if re.search(r"\b(check|clash|interfer|clearance)\w*", low):
        what = ["interference", "clearance"] + (["motion"] if "motion" in low else [])
        return "I'll run the checks.", [{"do": "check", "what": what}]
    if re.search(r"\b(explain|status|what(?:'s| is) (?:in|there|the state)|summar)", low):
        return "", [{"do": "explain"}]
    m = re.match(r"^\s*(?:please\s+)?(?:bring|add|insert|get)\s+(.+)$", t, re.IGNORECASE)
    if m:
        body = m.group(1)
        assemble = bool(re.search(r"\b(and|then)\s+(?:put|mount|fit|seat|assemble)\b|\bput (?:it|them) on\b", body,
                                  re.IGNORECASE))
        body = re.split(r"\b(?:and|then)\s+(?:put|mount|fit|seat|assemble)\b", body, flags=re.IGNORECASE)[0]
        acts: list[dict[str, Any]] = []
        for k, cl in enumerate(librarian.parse(body)):
            tb = librarian.read_toolbox(cl.core)
            if not tb:
                continue
            target = cl.target.split(" ", 1)[-1] if cl.target else None
            acts.append({"do": "bring", "code": tb["code"], "params": tb.get("params") or {}, "qty": cl.qty,
                         **({"for": target} if target else {}), "as": f"$b{k}"})
        if acts and assemble:
            acts.append({"do": "assemble", "parts": "all"})
        if acts:
            return "I'll bring them in" + (" and put them on." if assemble else "."), acts
    m = re.match(r"^\s*(?:please\s+)?(?:remove|delete)\s+(.+)$", t, re.IGNORECASE)
    if m:
        return "", [{"do": "remove", "part": m.group(1)}]
    return ("I can't read that without the AI assistant. Try \"bring a 6204 bearing for the shaft\", "
            "\"assemble everything\" or \"check for clashes\", or use Quick add to add parts."), []


def public(chat: dict[str, Any]) -> dict[str, Any]:
    """What the page shows (never the model's raw reply)."""
    return {"messages": chat["messages"], "busy": chat.get("busy"),
            "jobs": [{k: j.get(k) for k in ("id", "name", "status", "step", "project_id", "started_at", "text")}
                     for j in chat.get("jobs") or []][-6:]}


def dumps(x: Any) -> str:
    return json.dumps(x, sort_keys=True, default=str)
