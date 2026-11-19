"""Talk to Archie at any stage of a program (CD-026).

The engineer can ask the Chief Designer for a status report or ask for a change while the office works. Two rules:

* A status report is built from the program state itself (no AI, no tokens, always available and always true).
* Archie never changes the program on his own. A request for a change comes back as one or more *proposed
  actions*; each one runs only when the engineer presses Apply, through the same code path as the matching
  button on the board (comment to a ticket, reopen, pause, priority, interface change request, budget, re-plan,
  engineering change notice). Anything outside that list (adding or removing parts after the plan is approved)
  is answered honestly with what to do instead (PD-65).

With AI available (Archie-planned program, AI allowed for the account, tokens left) one short text-only turn reads
the message against a compact view of the program and proposes actions in a fenced ``fw-office-actions`` block.
Otherwise a deterministic reader handles the common requests (status, pause, resume, an instruction for a named
ticket, re-plan notes during plan review) and says plainly what it can't do.

The conversation is kept per program in ``<program>/archie/chat.json`` (last ``MAX_MESSAGES``).
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from aicad.office import roster, service, store

MAX_MESSAGES = 200
MAX_TEXT = 2000
CHAT_MAX_TOKENS = 150  # hard cap (platform tokens) for one AI chat turn; the "Status report" chip costs none
HISTORY_TURNS = 8

ACTION_TYPES = ("instruct", "reopen", "pause_ticket", "resume_ticket", "priority", "pause_program",
                "resume_program", "interface_change", "budget", "replan", "ecn", "fix_icd", "resize_part", "retry_blocked",
                "revise_plan", "keep_separate")

CHAT_INSTRUCTIONS = """You are Archie, the Chief Designer of a mechanical design office. The engineering manager \
talks to you while a program is planned or in work. You see the program state below. Answer in plain engineering \
language. When asked why something happens, diagnose it from the evidence below (review findings, blocked \
reasons, interfaces, recent events): name the tickets, the cause and the fix, then propose the actions that fix it. \
Keep it under eight sentences. Never mention files, tools, code, models or how you work inside.

If the manager asks for a change, do not claim it is done. Propose the concrete actions that would make it, in \
exactly one fenced block (omit the block when no action is needed):
```fw-office-actions
[{"type": "...", ...}]
```
Allowed actions (use ticket keys exactly as listed, interface ids exactly as listed):
- {"type": "instruct", "ticket": "KEY", "text": "instruction for the designer"}: a new requirement for a part \
that is still being worked on.
- {"type": "reopen", "ticket": "KEY", "text": "what must change"}: a finished part must be redone.
- {"type": "pause_ticket", "ticket": "KEY"} / {"type": "resume_ticket", "ticket": "KEY"}
- {"type": "priority", "ticket": "KEY", "priority": "high" | "normal" | "low"}
- {"type": "pause_program"} / {"type": "resume_program"}
- {"type": "interface_change", "interface": "ID", "values": {"field": number}, "reason": "why"}: a number \
shared between parts changes (only fields listed for that interface). Before the interfaces are approved this edits
the draft; after, it raises a change request.
- {"type": "resize_part", "part": "part name as listed", "size": {"W": 6}}: only before the interfaces are \
approved: a part's envelope in mm (block: L, W, H; round part: OD, H; shaft: length).
- {"type": "budget", "tokens": integer, "concurrency": integer, "threads": {"molly": 3}}: any field may be left \
out. "concurrency" is how many agents work at once in total; "threads" is parallel sub-agents of one designer \
(mill, chuck, axel, benny, molly).
- {"type": "replan", "notes": "what to change"}: only while the plan waits for approval.
- {"type": "retry_blocked"}: put every blocked part back to work under the current review rules (a part that \
passes every measurable check is approved with Gage's open points recorded) and run the office.
- {"type": "fix_icd"}: while the interfaces wait for approval and have problems: adjust them so every part can be made (smallest safe changes, listed for review).
- {"type": "keep_separate", "parts": ["part name as listed", ...]}: only while the interfaces wait for approval: parts with no interface are meant to be separate (a kit, parts made on their own); the manager's decision is recorded and they no longer block approval. Only propose it when the manager says the parts are meant to be apart.
- {"type": "revise_plan", "notes": "what to change", "add": {"sub": "sub-assembly name", "part": {"name": "...", \
"family": "machined", "qty": 1, "description": "..."}}}: only while the interfaces wait for approval and no part \
work has started: send the plan back to the manager for review with this change ("add" is optional: one part to add, \
e.g. a housing or base plate the other parts mount on).
- {"type": "ecn", "reason": "why", "tickets": ["KEY", ...]}: only after the program is released.
Parts can't be added to or removed from an approved plan: say so and suggest a new program or an ECN instead."""

_BLOCK = re.compile(r"```fw-office-actions\s*\n(.*?)\n?```", re.DOTALL)
_STATUS = re.compile(r"\b(status|progress|report|update|how(?:'s| is| are)? (?:it|things|we) going|where are we|"
                     r"eta|when will|how long|what(?:'s| is) (?:left|blocked|happening)|summary|blocked|stuck)\b", re.IGNORECASE)
_PAUSE = re.compile(r"^\s*(?:please\s+)?(?:pause|stop|hold|halt)\b(?:\s+(?:the\s+)?(?:program|office|work|"
                    r"everything|all))?\s*[.!]?\s*$", re.IGNORECASE)
_RESUME = re.compile(r"^\s*(?:please\s+)?(?:resume|continue|carry on|go on|run|start|restart|unpause)\b"
                     r"(?:\s+(?:the\s+)?(?:program|office|work|everything|all))?\s*[.!]?\s*$", re.IGNORECASE)


# --------------------------------------------------------------------------- the conversation file
_chat_locks: dict[str, threading.Lock] = {}
_glock = threading.Lock()


def chat_lock(pid: str) -> threading.Lock:
    """The conversation's own lock (never the program's: the orchestrator posts while it holds that one)."""
    with _glock:
        return _chat_locks.setdefault(pid, threading.Lock())


def _file(root: Path, pid: str) -> Path:
    return store.program_dir(root, pid) / "archie" / "chat.json"


def history(root: Path, pid: str) -> list[dict[str, Any]]:
    d = store.read_json(_file(root, pid))
    return d if isinstance(d, list) else []


def save_history(root: Path, pid: str, msgs: list[dict[str, Any]]) -> None:
    f = _file(root, pid)
    f.parent.mkdir(parents=True, exist_ok=True)
    store.write_json(f, msgs[-MAX_MESSAGES:])


def post(root: Path, pid: str, text: str, actions: list[dict[str, Any]], *, kind: str = "office",
         **extra: Any) -> dict[str, Any]:
    """Archie speaks first (founder, 2026-11-19: the office tells the engineer on the go): a message in the program
    chat with proposed actions, as if he had answered. ``extra``: e.g. ``visual`` (picture link + verdict)."""
    msg = {**archie_message(text, actions, kind=kind), **extra, "unprompted": True}
    with chat_lock(pid):
        hist = history(root, pid)
        hist.append(msg)
        save_history(root, pid, hist)
    return msg


def user_message(text: str, actor: dict[str, Any]) -> dict[str, Any]:
    return {"id": store.new_id(), "role": "user", "by": actor, "text": text.strip()[:MAX_TEXT], "t": store.now()}


def archie_message(text: str, actions: list[dict[str, Any]], *, kind: str, tokens: int = 0) -> dict[str, Any]:
    """``kind``: "status" (built from the program), "ai" (Archie's AI turn) or "office" (deterministic reader)."""
    return {"id": store.new_id(), "role": "archie", "text": service.plain_names(text).strip()[:MAX_TEXT],
            "t": store.now(), "kind": kind,
            "tokens": tokens, "actions": [{**a, "id": f"a{i + 1}", "status": "proposed"} for i, a in enumerate(actions)]}


# --------------------------------------------------------------------------- status report (deterministic)
def _mins(m: float | None) -> str:
    if not m:
        return "0 min"
    m = float(m)
    return f"{m:.0f} min" if m < 90 else f"{m / 60:.1f} h"


def needs_you(doc: dict[str, Any]) -> list[str]:
    """What waits for the engineer right now, in plain words."""
    out: list[str] = []
    if doc["status"] == "plan_review":
        out.append("the plan waits for your approval")
    g = {x["code"]: x for x in doc.get("gates", [])}
    if (doc.get("icd") or {}).get("status") == "draft" and (g.get("icd") or {}).get("status") == "pending":
        from aicad.office import interfaces as _ifs

        n = len(doc["icd"].get("problems") or [])
        loose = len(_ifs.unconnected(doc)) if n else 0
        if loose:  # a part with no interface: connect it, or keep it separate (the engineer's call, PD-85)
            out.append(f"{loose} part{'s have' if loose != 1 else ' has'} no interface: connect "
                       f"{'them' if loose != 1 else 'it'} on the Interfaces tab, or keep "
                       f"{'them' if loose != 1 else 'it'} as separate parts if that is intended")
        n -= loose
        if n or not loose:
            out.append(f"{n} interface problem{'s' if n != 1 else ''} block the interfaces (ICD): I can fix them "
                       "(Fix with Archie on the Interfaces tab), then you approve and press Run" if n else
                       "the interfaces (ICD) wait for your approval on the Interfaces tab; then press Run")
    for t in doc["tickets"]:
        st = (t.get("run") or {}).get("status")
        if st == "awaiting_review":
            out.append(f"{t['key']} {t['title']} waits for your review")
        elif st == "blocked":
            line = (t.get("run") or {}).get("line") or "it needs you"
            out.append(f"{t['key']} {t['title']} is blocked: {line}")
    if (g.get("release") or {}).get("status") == "pending":
        out.append("the release pack waits for your sign-off on the Deliverables tab")
    if (doc.get("orchestrator") or {}).get("state") == "stopped":
        out.append("the office stopped at the token budget: raise it and press Resume")
    asking = [e for e in (doc.get("supervisor") or {}).get("log") or [] if e.get("status") == "asking"]
    if asking:  # Archie's major proposals wait for a yes or no (office/supervisor)
        out.append(f"{len(asking)} proposal{'s' if len(asking) != 1 else ''} of mine wait{'' if len(asking) != 1 else 's'} "
                   f"for your decision: {asking[0]['title']}")
    return out


def status_report(root: Path, doc: dict[str, Any]) -> str:
    """A short, true status of the program from its own state."""
    name = doc["name"]
    if doc["status"] == "planning":
        return f"I'm still planning {name}. You'll review and edit the plan before any ticket opens."
    if doc["status"] == "plan_review":
        plan = doc.get("plan") or {}
        n = sum(len(s.get("parts", [])) for s in plan.get("subassemblies", []))
        return (f"The plan for {name} is ready: {len(plan.get('subassemblies', []))} sub-assemblies, {n} parts. "
                "It waits for your approval; tell me what to change and I'll propose a re-plan.")
    v = service.view(doc)
    tickets = doc["tickets"]
    done = sum(1 for t in tickets if t["column"] in service.DONE_COLUMNS)
    c = v["counts"]
    o = v["orchestrator"]
    state = {"running": "working", "paused": "paused", "stopped": "stopped at the budget", "complete": "finished",
             "idle": "not started (press Run)"}.get(o["state"], o["state"])
    parts = [(f"{name} is {round((v.get('rollup') or {}).get('progress', 0))} % done: {done} of {len(tickets)} "
             f"tickets finished, {c.get('in_design', 0)} in design, {c.get('in_review', 0)} in review.")]
    if doc.get("released"):
        parts[0] = f"{name} is released at rev {doc['released'].get('rev')}. " + parts[0]
    line = f"The office is {state}"
    if o["state"] == "running":
        line += f" with {o['working']} agent{'s' if o['working'] != 1 else ''} on tickets"
        if o["waiting"]:
            line += f", {o['waiting']} waiting for capacity"
    eta = v.get("eta") or {}
    if eta.get("remaining_min"):
        line += f"; about {_mins(eta.get('low_min'))} to {_mins(eta.get('high_min'))} of work left"
    parts.append(line + ".")
    b = v["budget"]
    if b.get("tokens"):
        parts.append(f"Tokens: {b['spent']:,} of {b['tokens']:,} ({round(b.get('pct') or 0)} %).")
    working = [f"{t['key']} {t['title']} ({(t.get('run') or {}).get('agent_label') or roster.agent(t['specialist'])['name']})"
               for t in tickets if (t.get("run") or {}).get("status") in ("searching", "designing", "reviewing",
                                                                           "integrating", "fitting", "drafting",
                                                                           "screening")]
    if working:
        parts.append("On the bench now: " + "; ".join(working[:5]) + ("…" if len(working) > 5 else "") + ".")
    from aicad.office import supervisor

    relaxed = supervisor.relaxed_summary(doc)
    if relaxed:
        parts.append(f"Relaxed by me, not passed ({len(relaxed)}): " + "; ".join(relaxed[:3])
                     + ("…" if len(relaxed) > 3 else "") + ".")
    need = needs_you(doc)
    if need:
        parts.append("Needs you: " + "; ".join(need[:5]) + ("…" if len(need) > 5 else "") + ".")
    elif doc["status"] != "complete":
        parts.append("Nothing waits for you right now.")
    return " ".join(parts)


def blocked(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Tickets waiting for the engineer after the office gave up on them (review rounds, failed builds)."""
    return [t for t in doc["tickets"] if (t.get("run") or {}).get("status") == "blocked" and not t.get("taken_over")]


# --------------------------------------------------------------------------- reading the message
def find_ticket(doc: dict[str, Any], ref: str) -> dict[str, Any] | None:
    ref = (ref or "").strip()
    if not ref:
        return None
    for t in doc["tickets"]:
        if t["key"].lower() == ref.lower() or t["id"] == ref:
            return t
    low = ref.lower()
    hits = [t for t in doc["tickets"] if t["title"].lower() == low]
    return hits[0] if len(hits) == 1 else None


def mentioned(doc: dict[str, Any], text: str) -> list[dict[str, Any]]:
    """Tickets a message names, by key (GR-3) or by full title (the output shaft)."""
    low = text.lower()
    out = []
    for t in doc["tickets"]:
        if re.search(rf"\b{re.escape(t['key'].lower())}\b", low) or (
                t["kind"] in ("part", "standard") and re.search(rf"\b{re.escape(t['title'].lower())}\b", low)):
            out.append(t)
    return out


def is_status(text: str) -> bool:
    """Only a bare status request is answered from the template (free, no AI): "Status report", "status?",
    "progress". Anything with a question in it (why, what's wrong, how to fix) goes to Archie's AI turn."""
    words = re.findall(r"[a-z']+", text.lower())
    return 0 < len(words) <= 3 and bool(_STATUS.search(text)) and not re.search(
        r"\b(why|how|what|issue|problem|fix|solve|wrong|stuck|blocked)\b", text, re.IGNORECASE)


def asks_status(text: str) -> bool:
    """Broad reading for the office reader (no AI): any short question about progress, ETA or what is happening."""
    return bool(_STATUS.search(text)) and len(text) < 200 and not re.search(
        r"\b(change|make|add|increase|decrease|reduce|use|switch|set|instead|should|must)\b", text, re.IGNORECASE)


def offline_reply(doc: dict[str, Any], text: str, root: Path) -> tuple[str, list[dict[str, Any]], str]:
    """Deterministic answer: (text, proposed actions, kind)."""
    stuck = blocked(doc)
    if doc["status"] in ("active", "complete") and stuck and re.search(
            r"\b(stuck|blocked|review|sent back|retry|rejected|gage|strict|resolve|unblock)\w*", text, re.IGNORECASE):
        n = len(stuck)
        names = ", ".join(f"{t['key']} {t['title']}" for t in stuck[:6]) + ("…" if n > 6 else "")
        msg = (f"{n} part{'s are' if n != 1 else ' is'} blocked: {names}. Under the current review rules the approved "
               "interfaces govern, and when only advisory points remain, a part that passes every measurable check "
               "is approved with those points recorded for you. I'll put the blocked parts back to work and run the "
               "office; a part that really fails a check comes back to you with the reason.")
        return msg, [{"type": "retry_blocked"}], "office"
    if asks_status(text):
        return status_report(root, doc), [], "status"
    st = doc["status"]
    running = (doc.get("orchestrator") or {}).get("state") == "running"
    if _PAUSE.match(text):
        if st != "active" or not running:
            return "The office isn't running, so there is nothing to pause.", [], "office"
        return "I'll pause the office: agents finish the step they are on and nothing new starts.", \
            [{"type": "pause_program"}], "office"
    if _RESUME.match(text):
        if st != "active" or running:
            return ("The office is already working." if running else
                    "There's nothing to run yet: approve the plan first."), [], "office"
        return "I'll set the office working the tickets again.", [{"type": "resume_program"}], "office"
    icd = doc.get("icd") or {}
    from aicad.office import interfaces as _ifs

    if icd.get("status") == "draft" and icd.get("problems") and len(_ifs.unconnected(doc)) < len(icd["problems"]) and re.search(
            r"\b(fix|stuck|proceed|next|problem|interfer|blocked|can'?t|cannot|approve|dead)\w*", text, re.IGNORECASE):
        n = len(icd["problems"])
        return ((f"The interfaces have {n} problem{'s' if n != 1 else ''}: parts that can't be made as I laid them "
                "out. I'll make the smallest safe changes (bolt spacing, a thicker part) and list each one; then you "
                "review and approve the interfaces and press Run."), [{"type": "fix_icd"}], "office")
    if st == "plan_review":
        return ("I'll re-plan from the brief with your notes. Your unsaved edits to the plan are replaced.",
                [{"type": "replan", "notes": text[:MAX_TEXT]}], "office")
    if st == "planning":
        return "I'm still planning. Once the plan is up, tell me what to change and I'll re-plan with it.", [], "office"
    named = [t for t in mentioned(doc, text) if t["kind"] in ("part", "standard")]
    if named:
        acts = []
        for t in named[:4]:
            done = t["column"] in service.DONE_COLUMNS
            acts.append({"type": "reopen" if done else "instruct", "ticket": t["key"], "text": text[:MAX_TEXT]})
        names = ", ".join(f"{t['key']} {t['title']}" for t in named[:4])
        return ((f"I'll pass this to the designer of {names}. A finished part is reopened with it; a part in work "
                "gets it with its next step."), acts, "office")
    return ("I can give you a status report, pause or resume the office, or send an instruction to a part if you "
            "name it (its key, like " + (doc["tickets"][0]["key"] if doc["tickets"] else "AB-1") + ", or its title). "
            "Shared numbers between parts change on the Interfaces tab. Parts can't be added to an approved plan."), \
        [], "office"


# --------------------------------------------------------------------------- the AI turn
def _editable(i: dict[str, Any]) -> dict[str, Any]:
    """The numeric fields of an interface that a change request may change (as on the Interfaces tab)."""
    from aicad.office import icd

    data = i.get("data") or {}
    return {k: data[k] for k in icd.EDITABLE.get(i.get("kind"), ()) if isinstance(data.get(k), (int, float, str))
            and not isinstance(data.get(k), bool)}


def chat_prompt(root: Path, doc: dict[str, Any], hist: list[dict[str, Any]], text: str) -> str:
    lines = [f"Program: {doc['name']} ({doc['key']}), stage: {doc['status']}"
             + (f", released rev {doc['released'].get('rev')}" if doc.get("released") else ""),
             f"Brief:\n{doc['brief'][:1500]}"]
    if doc.get("plan") and doc["status"] in ("plan_review", "planning"):
        p = doc["plan"]
        lines.append("Plan: " + "; ".join(f"{s['name']}: " + ", ".join(x["name"] for x in s.get("parts", []))
                                          for s in p.get("subassemblies", [])))
    if doc["tickets"]:
        lines.append("Tickets (key, title, kind, column, agent status):")
        for t in doc["tickets"][:80]:
            r = t.get("run") or {}
            lines.append(f"- {t['key']} {t['title']} [{t['kind']}] {t['column']}"
                         + (f", {r.get('status')}" if r.get("status") else "") + (", paused" if t.get("paused") else "")
                         + (f": {r['line']}" if r.get("line") else ""))
    icd = doc.get("icd") or {}
    if icd.get("status") == "draft" and doc.get("skeleton"):
        lines.append("Part envelopes (mm, before approval): " + "; ".join(
            f"{it['name']} {it['role']} {'x'.join(f'{v:g}' for v in it['size'])}"
            for it in list(doc["skeleton"]["items"].values())[:60]))
        if icd.get("problems"):
            lines.append("Problems blocking approval:\n" + "\n".join(f"- {p}" for p in icd["problems"][:20]))
    if icd.get("interfaces"):
        lines.append(f"Interfaces (ICD v{icd.get('version')}, {icd.get('status')}; changeable fields):")
        for i in icd["interfaces"][:40]:
            vals = ", ".join(f"{k}={v}" for k, v in _editable(i).items())
            lines.append(f"- {i['id']} {i.get('name', '')}: {vals}")
    lines.append("Status: " + status_report(root, doc))
    trouble = [t for t in doc["tickets"] if (t.get("run") or {}).get("status") == "blocked"
               or int((t.get("run") or {}).get("review_round") or 0) > 0]
    if trouble:
        lines.append("Review history of parts sent back or blocked (Gage's latest findings):")
        for t in trouble[:25]:
            r = t.get("run") or {}
            last = next((c["text"] for c in reversed(t.get("comments") or [])
                         if (c.get("by") or {}).get("code") == "gage"), "")
            lines.append(f"- {t['key']} {t['title']}: {r.get('status')}, {int(r.get('review_round') or 0)} send-backs"
                         + (f"; blocked: {str(r['blocked'])[:200]}" if r.get("blocked") else "")
                         + (f"; Gage: {' '.join(last.split())[:300]}" if last else ""))
    evs = [e for e in store.events(root, doc["id"], limit=400)
           if e["type"] not in ("agent.status", "ticket.milestone", "ticket.moved", "ticket.claimed")][-15:]
    if evs:
        lines.append("Recent events:\n" + "\n".join(f"- {e['text'][:200]}" for e in evs))
    convo = [f"{'Manager' if m['role'] == 'user' else 'Archie'}: {m['text'][:600]}"
             for m in hist[-HISTORY_TURNS:]]
    if convo:
        lines.append("Conversation so far:\n" + "\n".join(convo))
    lines.append(f"Manager: {text}")
    return "\n\n".join(lines)


def parse_actions(doc: dict[str, Any], text: str) -> tuple[str, list[dict[str, Any]]]:
    """Archie's prose (block removed) and the valid actions in his block; anything invalid is dropped."""
    acts: list[dict[str, Any]] = []
    for m in _BLOCK.finditer(text or ""):
        try:
            raw = json.loads(m.group(1))
        except ValueError:
            continue
        for a in raw if isinstance(raw, list) else [raw]:
            ok = normalise(doc, a)
            if ok is not None and ok not in acts:
                acts.append(ok)
    prose = " ".join(_BLOCK.sub("", text or "").split())[:MAX_TEXT]
    return prose, acts[:6]


def normalise(doc: dict[str, Any], a: Any) -> dict[str, Any] | None:
    """One proposed action, checked against the program; None when it can't apply."""
    if not isinstance(a, dict) or a.get("type") not in ACTION_TYPES:
        return None
    typ = a["type"]
    st = doc["status"]
    txt = " ".join(str(a.get("text") or a.get("notes") or a.get("reason") or "").split())[:MAX_TEXT]
    if typ in ("instruct", "reopen", "pause_ticket", "resume_ticket", "priority"):
        if st not in ("active", "complete"):
            return None
        t = find_ticket(doc, str(a.get("ticket") or ""))
        if t is None:
            return None
        out: dict[str, Any] = {"type": typ, "ticket": t["key"]}
        if typ in ("instruct", "reopen"):
            if not txt or t["kind"] not in ("part", "standard"):
                return None
            out["text"] = txt
        if typ == "priority":
            if a.get("priority") not in ("high", "normal", "low"):
                return None
            out["priority"] = a["priority"]
        return out
    if typ in ("pause_program", "resume_program"):
        return {"type": typ} if st == "active" else None
    if typ == "retry_blocked":
        return {"type": typ} if st in ("active", "complete") and blocked(doc) else None
    if typ == "fix_icd":
        icd = doc.get("icd") or {}
        return {"type": typ} if icd.get("status") == "draft" and icd.get("problems") else None
    if typ == "keep_separate":
        from aicad.office import interfaces

        if (doc.get("icd") or {}).get("status") != "draft" or not doc.get("skeleton"):
            return None
        flagged = interfaces.unconnected(doc)
        items = doc["skeleton"]["items"]
        names = {str(n).strip().lower() for n in a.get("parts") or [] if isinstance(n, str)}
        want = [i for i in flagged if i in (a.get("items") or []) or items[i]["name"].lower() in names]
        return {"type": typ, "items": want, "parts": [items[i]["name"] for i in want]} if want else None
    if typ == "revise_plan":
        return revise_ok(doc, a, txt)
    if typ == "resize_part":
        from aicad.office import interfaces

        if (doc.get("icd") or {}).get("status") != "draft" or not doc.get("skeleton"):
            return None
        name = str(a.get("part") or "").strip().lower()
        hit = [(i, it) for i, it in doc["skeleton"]["items"].items() if it["name"].lower() == name or i == a.get("item")]
        if len(hit) != 1 or not isinstance(a.get("size"), dict):
            return None
        i, it = hit[0]
        size = {k: float(v) for k, v in a["size"].items() if k in interfaces.RESIZABLE.get(it["role"], ())
                and isinstance(v, (int, float)) and not isinstance(v, bool) and 0.5 <= v <= 5000}
        return {"type": typ, "part": it["name"], "item": i, "size": size} if size else None
    if typ == "interface_change":
        icd = doc.get("icd") or {}
        i = next((x for x in icd.get("interfaces", []) if x["id"] == a.get("interface")), None)
        vals = a.get("values")
        if icd.get("status") not in ("draft", "approved") or i is None or not isinstance(vals, dict) or not txt:
            return None
        ed = _editable(i)
        clean: dict[str, Any] = {}
        for k, v in vals.items():
            if k not in ed or isinstance(v, bool):
                continue
            if isinstance(ed[k], str) and isinstance(v, str) and v.strip():
                clean[k] = v.strip()[:40]
            elif not isinstance(ed[k], str) and isinstance(v, (int, float)):
                clean[k] = v
        return {"type": typ, "interface": i["id"], "values": clean, "reason": txt} if clean else None
    if typ == "budget":
        out = {"type": typ}
        if isinstance(a.get("tokens"), int) and 0 <= a["tokens"] <= 1_000_000:
            out["tokens"] = a["tokens"]
        if isinstance(a.get("concurrency"), int) and 1 <= a["concurrency"] <= 12:
            out["concurrency"] = a["concurrency"]
        from aicad.office import estimates

        th = {k: v for k, v in estimates.clean_threads(a.get("threads")).items() if k in roster.AGENT_CODES
              and k != "archie"}
        if th:
            out["threads"] = th
        return out if len(out) > 1 else None
    if typ == "replan":
        return {"type": typ, "notes": txt} if st == "plan_review" and txt else None
    if typ == "ecn":
        if not doc.get("released") or not txt:
            return None
        keys = [t["key"] for k in (a.get("tickets") or []) if (t := find_ticket(doc, str(k))) is not None
                and t["kind"] in ("part", "standard")]
        return {"type": typ, "reason": txt, "tickets": keys} if keys else None
    return None


def describe(doc: dict[str, Any], a: dict[str, Any]) -> str:
    """The action in one line, for the Apply card."""
    t = find_ticket(doc, a.get("ticket", "")) if a.get("ticket") else None
    lbl = f"{t['key']} {t['title']}" if t else a.get("ticket", "")
    typ = a["type"]
    if typ == "instruct":
        return f"Send to the designer of {lbl}: {a['text']}"
    if typ == "reopen":
        return f"Reopen {lbl} with: {a['text']}"
    if typ == "pause_ticket":
        return f"Pause {lbl}"
    if typ == "resume_ticket":
        return f"Resume {lbl}"
    if typ == "priority":
        return f"Set {lbl} to {a['priority']} priority"
    if typ == "pause_program":
        return "Pause the office"
    if typ == "resume_program":
        return "Run the office"
    if typ == "interface_change":
        vals = ", ".join(f"{k} → {v:g}" if isinstance(v, (int, float)) else f"{k} → {v}" for k, v in a["values"].items())
        if (doc.get("icd") or {}).get("status") == "draft":
            return f"Edit interface {a['interface']}: {vals} ({a['reason']})"
        return f"Change request on interface {a['interface']}: {vals} ({a['reason']})"
    if typ == "budget":
        bits = []
        if "tokens" in a:
            bits.append(f"token budget {a['tokens']:,}")
        if "concurrency" in a:
            bits.append(f"{a['concurrency']} agents at a time")
        for k, v in (a.get("threads") or {}).items():
            bits.append(f"{roster.agent(k)['name']} {v} thread{'s' if v != 1 else ''}")
        return "Set " + " and ".join(bits)
    if typ == "replan":
        return f"Re-plan with: {a['notes']}"
    if typ == "retry_blocked":
        if a.get("status") == "applied" and a.get("count") is not None:  # what was done, not what is blocked now
            n = int(a["count"])
            return (f"Retried {n} blocked part{'s' if n != 1 else ''} under the current review rules and ran the "
                    "office")
        n = len(blocked(doc))
        if not n:
            return "Retry the blocked parts (none is blocked now: nothing to retry)"
        return (f"Retry the {n} blocked part{'s' if n != 1 else ''} under the current review rules and run the "
                "office")
    if typ == "resize_part":
        return f"Resize {a['part']}: " + ", ".join(f"{k} {v:g} mm" for k, v in a["size"].items())
    if typ == "fix_icd":
        return "Fix the interface problems (smallest safe changes, listed in the ICD history for your review)"
    if typ == "keep_separate":
        sk_items = (doc.get("skeleton") or {}).get("items") or {}
        names = list(a.get("parts") or [sk_items[i]["name"] for i in a.get("items") or [] if i in sk_items])
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else "them"
        return (f"Keep {listed} as {'a separate part' if len(names) == 1 else 'separate parts'} (no interface "
                "intended; recorded in the interfaces history)")
    if typ == "revise_plan":
        add = a.get("add") or {}
        if add:
            return (f"Send the plan back to you with a {add['part']['name'].lower()} added to {add['sub']} "
                    f"({a['notes']})")
        return f"Send the plan back to you for review: {a['notes']}"
    if typ == "ecn":
        return f"Raise an engineering change on {', '.join(a['tickets'])}: {a['reason']}"
    return typ


def with_labels(doc: dict[str, Any], msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each action with its one-line label; a proposal the program has moved past is marked ``stale`` (the chat
    shows "No longer needed" instead of Apply: live run 2026-11-19 offered "Retry the 0 blocked parts")."""
    def one(a: dict[str, Any]) -> dict[str, Any]:
        out = {**a, "label": describe(doc, a)}
        if a.get("status") == "proposed":
            try:
                live = normalise(doc, {k: v for k, v in a.items() if k not in ("id", "status", "label")})
            except Exception:  # noqa: BLE001 - an old proposal the reader no longer knows: not offered
                live = None
            if live is None:
                out["stale"] = True
        return out
    return [{**m, "actions": [one(a) for a in m.get("actions", [])]} for m in msgs]


def emit_said(root: Path, doc: dict[str, Any], actor: dict[str, Any], text: str) -> None:
    service.emit(root, doc, "archie.chat", f"{actor.get('name', 'Someone')} talked to Archie: {text[:140]}", actor)


async def run_chat(folder: Path, prompt: str, budget_usd: float | None = None) -> tuple[str, float | None]:
    """One text-only turn through the LLM provider. Tests and simulated mode replace it."""
    from aicad import llm

    res = await llm.complete(llm.CallRequest(role="office_chat", system=CHAT_INSTRUCTIONS, prompt=prompt,
                                             budget_usd=budget_usd, cwd=folder))
    return res.text, res.metering.cost_usd


# --------------------------------------------------------------------------- revising the plan at the interfaces gate
def can_revise(doc: dict[str, Any]) -> bool:
    """The plan may go back for review while the interfaces wait for approval and no ticket has started."""
    from aicad.office import service as _svc

    return (doc["status"] == "active" and (doc.get("icd") or {}).get("status") == "draft"
            and _svc.gate(doc, "icd")["status"] == "pending"
            and not any((t.get("run") or {}).get("status") or t["column"] not in ("backlog", "ready")
                        for t in doc["tickets"]))


def revise_ok(doc: dict[str, Any], a: dict[str, Any], txt: str) -> dict[str, Any] | None:
    from aicad.office import roster as _roster

    if not can_revise(doc) or not txt:
        return None
    out: dict[str, Any] = {"type": "revise_plan", "notes": txt}
    add = a.get("add")
    if isinstance(add, dict) and isinstance(add.get("part"), dict):
        subs = [s["name"] for s in (doc.get("plan") or {}).get("subassemblies") or []]
        sub = str(add.get("sub") or "")
        part = add["part"]
        nm = " ".join(str(part.get("name") or "").split())[:80]
        if sub not in subs or not nm:
            return None
        out["add"] = {"sub": sub, "part": {"name": nm, "family": _roster.normalise_family(part.get("family")),
                                           "complexity": 2 if part.get("complexity") is None else
                                           max(1, min(5, int(part.get("complexity") or 2))),
                                           "qty": max(1, min(8, int(part.get("qty") or 1))),
                                           "description": " ".join(str(part.get("description") or "").split())[:400]}}
    return out
