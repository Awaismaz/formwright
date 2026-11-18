"""Program operations and the live event bus.

Every change to a program goes through a function here and emits one event. The manual board (Phase 2) calls these
with a ``user`` actor; the orchestrator (Phase 3) will call the same functions with an ``agent`` actor, so the board,
the roll-up and the activity feed need no changes when agents start working tickets.

Callers hold ``store.lock(program_id)`` around load -> change -> save.
"""

from __future__ import annotations

import asyncio
import re
import threading
from pathlib import Path
from typing import Any

from aicad.office import OfficeInputError, estimates, planner, roster, store

COLUMNS: list[tuple[str, str]] = [
    ("backlog", "Backlog"), ("ready", "Ready"), ("in_design", "In design"), ("in_review", "In review"),
    ("changes_requested", "Changes requested"), ("approved", "Approved"), ("integrated", "Integrated"),
]
COLUMN_CODES = [c for c, _ in COLUMNS]
COLUMN_LABEL = dict(COLUMNS)
DONE_COLUMNS = {"approved", "integrated"}
STATUSES = ("planning", "plan_review", "active", "complete")
MAX_COMMENT = 2000
DEFAULT_BUDGET_TOKENS = 3000


# --------------------------------------------------------------------------- event bus (thread-safe)
class Bus:
    """In-process pub/sub per program for the board's SSE stream. ``publish`` may be called from any thread."""

    def __init__(self) -> None:
        self._subs: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]]] = {}
        self._lock = threading.Lock()

    def subscribe(self, key: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        with self._lock:
            self._subs.setdefault(key, set()).add((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, key: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            subs = self._subs.get(key, set())
            for s in [s for s in subs if s[1] is q]:
                subs.discard(s)

    def publish(self, key: str, ev: dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subs.get(key, set()))
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, ev)
            except RuntimeError:  # loop closed: the subscriber is gone
                pass


bus = Bus()


def user_actor(name: str, uid: str | None = None) -> dict[str, Any]:
    return {"kind": "user", "id": uid, "name": name}


def agent_actor(code: str) -> dict[str, Any]:
    a = roster.agent(code)
    return {"kind": "agent", "code": a["code"], "name": a["name"]}


STUDIO_ACTOR = {"kind": "studio", "name": "Design Studio"}


def emit(root: Path, doc: dict[str, Any], type_: str, text: str, actor: dict[str, Any],
         ticket_id: str | None = None, **data: Any) -> dict[str, Any]:
    """Record one event (log + live bus). ``text`` is plain engineering language: it is shown as-is."""
    doc["event_seq"] = int(doc.get("event_seq", 0)) + 1
    ev = {"seq": doc["event_seq"], "t": store.now(), "type": type_, "program_id": doc["id"], "ticket_id": ticket_id,
          "actor": actor, "text": text, "data": data}
    store.append_event(root, doc["id"], ev)
    bus.publish(doc["id"], ev)
    bus.publish(f"org:{doc['org_id']}", ev)
    return ev


# --------------------------------------------------------------------------- program lifecycle
def key_prefix(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name)
    p = "".join(w[0] for w in words[:4]).upper() if len(words) > 1 else (words[0][:3].upper() if words else "PRG")
    return p if len(p) >= 2 else (p + "X")[:2]


def new_program(name: str, brief: str, org_id: str, user_id: str, concurrency: int, budget_tokens: int,
                planner_kind: str) -> dict[str, Any]:
    return {"schema": store.SCHEMA, "id": store.new_id(), "org_id": org_id, "name": name, "brief": brief,
            "key": key_prefix(name), "created_by": user_id, "created_at": store.now(), "updated_at": store.now(),
            "rev": 0, "event_seq": 0, "ticket_seq": 0,
            "status": "planning" if planner_kind == "archie" else "plan_review",
            "planner": planner_kind, "planning": None, "plan": None, "plan_history": [],
            "gates": [
                {"code": "brief", "name": "Brief approval", "mandatory": True, "status": "pending"},
                {"code": "icd", "name": "Architecture and interfaces", "mandatory": True, "status": "later",
                 "note": "Interfaces (ICD) arrive in a later release."},
                {"code": "release", "name": "Release", "mandatory": True, "status": "locked"},
            ],
            "items": [], "tickets": [],
            "concurrency": max(1, min(estimates.MAX_CONCURRENCY, int(concurrency))),
            "budget": {"tokens": max(0, int(budget_tokens)), "planning_tokens": 0}}


def set_plan(root: Path, doc: dict[str, Any], plan: dict[str, Any], actor: dict[str, Any], *,
             narrative: str = "", note: str | None = None) -> None:
    if doc.get("plan"):
        doc.setdefault("plan_history", []).append(doc["plan"])
        doc["plan_history"] = doc["plan_history"][-5:]
    plan = {**plan, "narrative": narrative, "note": note}
    doc["plan"], doc["status"], doc["planning"] = plan, "plan_review", None
    n_parts = sum(len(s["parts"]) for s in plan["subassemblies"])
    who = "Archie" if plan["source"] == "archie" else "The standard planner"
    emit(root, doc, "plan.ready", f"{who} split {doc['name']} into {len(plan['subassemblies'])} sub-assemblies and "
         f"{n_parts} parts. Review the plan before tickets are created.", actor, source=plan["source"])


def gate(doc: dict[str, Any], code: str) -> dict[str, Any]:
    return next(g for g in doc["gates"] if g["code"] == code)


def plan_estimate(plan: dict[str, Any], concurrency: int) -> dict[str, Any]:
    """Estimates for a plan that has no tickets yet (plan review shows what approval will create)."""
    items, tickets = _build(plan, "Program", "P")
    total = sum(t["estimate_min"] for t in tickets)
    return {"tickets": len(tickets), "estimate_min": round(total, 1),
            "eta": estimates.eta(items, tickets, "root", concurrency)}


def _ticket_brief(program: str, brief: str, sub: str, part: dict[str, Any]) -> str:
    qty = f" ({part['qty']} off)" if part["qty"] > 1 else ""
    fam = roster.FAMILIES[part["family"]][0].lower()
    if part["family"] == "standard":
        return (f"{part['name']}{qty} for the {sub} of {program}: a standard part. {part['description']} "
                "Use the Toolbox component that fits, with sizes taken from the program brief.\n\n"
                f"Program brief: {brief[:1500]}")
    return (f"Design the {part['name']}{qty} for the {sub} of {program}, as a {fam} part. {part['description']}\n\n"
            f"Program brief: {brief[:1500]}")


def _build(plan: dict[str, Any], name: str, prefix: str, brief: str = "") \
        -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = [{"id": "root", "parent_id": None, "kind": "program", "name": name}]
    tickets: list[dict[str, Any]] = []
    seq = [0]

    def ticket(item_id: str, kind: str, title: str, family: str, complexity: int, qty: int, brief_: str,
               column: str, depends: list[str]) -> dict[str, Any]:
        seq[0] += 1
        t = {"id": f"t{seq[0]}", "key": f"{prefix}-{seq[0]}", "item_id": item_id, "kind": kind, "title": title,
             "brief": brief_, "family": family, "specialist": roster.specialist_for(family),
             "complexity": complexity, "estimate_min": estimates.estimate_minutes(family, complexity), "qty": qty,
             "column": column, "milestones": [], "progress": 0, "project_id": None, "assembly_id": None,
             "depends_on": depends, "comments": [], "checks": None, "tokens": 0, "run": None,
             "created_at": store.now(), "updated_at": store.now()}
        tickets.append(t)
        return t

    sub_integrations = []
    for s in plan["subassemblies"]:
        sid = f"i_{s['id']}"
        items.append({"id": sid, "parent_id": "root", "kind": "subassembly", "name": s["name"],
                      "description": s.get("description", "")})
        deps = []
        for p in s["parts"]:
            pid = f"i_{s['id']}_{p['id']}"
            items.append({"id": pid, "parent_id": sid, "kind": "part", "name": p["name"], "family": p["family"],
                          "qty": p["qty"], "description": p.get("description", ""), "toolbox": p.get("toolbox")})
            kind = "standard" if p["family"] == "standard" else "part"
            deps.append(ticket(pid, kind, p["name"], p["family"], p["complexity"], p["qty"],
                               _ticket_brief(name, brief, s["name"], p), "ready", [])["id"])
        cx = estimates.integration_complexity(len(s["parts"]))
        sub_integrations.append(ticket(sid, "integration", f"Assemble {s['name']}", "integration", cx, 1,
                                       f"Assemble the {s['name']} of {name} from its parts and check for clashes.",
                                       "backlog", deps)["id"])
    ticket("root", "integration", f"Final assembly of {name}", "integration",
           estimates.integration_complexity(len(plan["subassemblies"])), 1,
           f"Bring the sub-assemblies of {name} together and check the whole product for clashes.", "backlog",
           sub_integrations)
    return items, tickets


def approve_plan(root: Path, doc: dict[str, Any], plan: dict[str, Any] | None, actor: dict[str, Any]) -> None:
    """Brief approval gate: the (possibly edited) plan becomes the item tree and the tickets."""
    if doc["status"] != "plan_review" or not doc.get("plan"):
        raise OfficeInputError("There is no plan waiting for approval.")
    if plan is not None:
        source = doc["plan"]["source"]
        p2 = planner.normalise_plan(plan, source)
        if p2 is None:
            raise OfficeInputError("The plan needs at least one sub-assembly with one part.")
        p2["edited"] = _plan_shape(p2) != _plan_shape(doc["plan"])
        doc["plan"] = {**doc["plan"], **p2}
    items, tickets = _build(doc["plan"], doc["name"], doc["key"], doc["brief"])
    doc["items"], doc["tickets"], doc["ticket_seq"] = items, tickets, len(tickets)
    doc["status"] = "active"
    g = gate(doc, "brief")
    g.update(status="approved", by=actor.get("name"), at=store.now())
    edited = " (edited)" if doc["plan"].get("edited") else ""
    emit(root, doc, "gate.approved", f"{actor.get('name', 'Someone')} approved the brief and plan{edited}. "
         f"{len(tickets)} tickets opened.", actor, gate="brief")


def _plan_shape(plan: dict[str, Any]) -> Any:
    return [(s["name"], [(p["name"], p["family"], p["complexity"], p["qty"]) for p in s["parts"]])
            for s in plan["subassemblies"]]


# --------------------------------------------------------------------------- tickets
def ticket(doc: dict[str, Any], tid: str) -> dict[str, Any]:
    t = next((t for t in doc["tickets"] if t["id"] == tid), None)
    if t is None:
        raise OfficeInputError("Ticket not found")
    return t


def _refresh(t: dict[str, Any]) -> None:
    t["progress"] = estimates.progress_of(t["milestones"])
    t["updated_at"] = store.now()


def _label(t: dict[str, Any]) -> str:
    return f"{t['key']} {t['title']}"


def move(root: Path, doc: dict[str, Any], tid: str, column: str, actor: dict[str, Any]) -> dict[str, Any]:
    if doc["status"] not in ("active", "complete"):
        raise OfficeInputError("Approve the brief first: tickets open when the plan is approved.")
    if column not in COLUMN_CODES:
        raise OfficeInputError("Unknown column")
    t = ticket(doc, tid)
    before = t["column"]
    if before == column:
        return t
    t["column"] = column
    ms = set(t["milestones"])
    if column in DONE_COLUMNS:
        ms.add("approved")
    else:
        ms.discard("approved")
    if column == "changes_requested":
        ms.discard("self_review")
    t["milestones"] = [m for m, _l, _w in estimates.MILESTONES if m in ms]
    _refresh(t)
    emit(root, doc, "ticket.moved", f"{actor.get('name', 'Someone')} moved {_label(t)}: {COLUMN_LABEL[before]} → "
         f"{COLUMN_LABEL[column]}.", actor, tid, **{"from": before, "to": column})
    _check_complete(root, doc, actor)
    return t


def _check_complete(root: Path, doc: dict[str, Any], actor: dict[str, Any]) -> None:
    done = all(t["column"] == "integrated" for t in doc["tickets"])
    if done and doc["status"] != "complete":
        doc["status"] = "complete"
        emit(root, doc, "program.milestone", f"Every ticket of {doc['name']} is integrated. First article "
             "assembled.", actor)
    elif not done and doc["status"] == "complete":
        doc["status"] = "active"


def set_milestone(root: Path, doc: dict[str, Any], tid: str, code: str, reached: bool,
                  actor: dict[str, Any]) -> dict[str, Any]:
    if code not in estimates.MILESTONE_WEIGHT:
        raise OfficeInputError("Unknown milestone")
    t = ticket(doc, tid)
    ms = set(t["milestones"])
    if (code in ms) == reached:
        return t
    ms.add(code) if reached else ms.discard(code)
    t["milestones"] = [m for m, _l, _w in estimates.MILESTONES if m in ms]
    _refresh(t)
    label = next(lbl for c, lbl, _w in estimates.MILESTONES if c == code)
    emit(root, doc, "ticket.milestone", f"{_label(t)}: {label} {'reached' if reached else 'cleared'} "
         f"({t['progress']} %).", actor, tid, milestone=code, reached=reached, progress=t["progress"])
    return t


def update(root: Path, doc: dict[str, Any], tid: str, actor: dict[str, Any], *, title: str | None = None,
           specialist: str | None = None, complexity: int | None = None) -> dict[str, Any]:
    t = ticket(doc, tid)
    changes = []
    if title is not None and title.strip() and title.strip() != t["title"]:
        t["title"] = title.strip()[:120]
        changes.append("renamed")
    if specialist is not None and specialist != t["specialist"]:
        if specialist not in roster.AGENT_CODES or specialist == "archie":
            raise OfficeInputError("Unknown specialist")
        t["specialist"] = specialist
        changes.append(f"reassigned to {roster.agent(specialist)['name']}")
    if complexity is not None:
        cx = estimates.clamp_complexity(complexity)
        if cx != t["complexity"]:
            t["complexity"], t["estimate_min"] = cx, estimates.estimate_minutes(t["family"], cx)
            changes.append(f"complexity {cx} ({t['estimate_min']:g} min estimate)")
    if changes:
        _refresh(t)
        emit(root, doc, "ticket.updated", f"{actor.get('name', 'Someone')} updated {_label(t)}: "
             f"{', '.join(changes)}.", actor, tid)
    return t


def comment(root: Path, doc: dict[str, Any], tid: str, text: str, actor: dict[str, Any]) -> dict[str, Any]:
    t = ticket(doc, tid)
    body = text.strip()[:MAX_COMMENT]
    if not body:
        raise OfficeInputError("Write a comment first")
    c = {"id": store.new_id(), "by": actor, "text": body, "t": store.now()}
    t["comments"].append(c)
    t["updated_at"] = store.now()
    emit(root, doc, "ticket.comment", f"{actor.get('name', 'Someone')} commented on {_label(t)}.", actor, tid,
         comment_id=c["id"])
    return c


def link(root: Path, doc: dict[str, Any], tid: str, actor: dict[str, Any], *, project_id: str | None = None,
         assembly_id: str | None = None) -> dict[str, Any]:
    t = ticket(doc, tid)
    if project_id:
        t["project_id"] = project_id
    if assembly_id:
        t["assembly_id"] = assembly_id
    what = "Design Studio part" if project_id else "assembly"
    emit(root, doc, "ticket.started", f"{actor.get('name', 'Someone')} opened {_label(t)} as a {what}.", actor, tid,
         project_id=project_id, assembly_id=assembly_id)
    if t["column"] in ("backlog", "ready"):
        move(root, doc, tid, "in_design", actor)
    return t


def sync_studio(root: Path, doc: dict[str, Any], info: dict[str, dict[str, Any]]) -> bool:
    """Derive the build milestones of linked tickets from their Studio projects (first build; latest build passes
    the gating checks). ``info``: project id -> {"builds", "ok", "tokens"}. Returns True when anything changed."""
    changed = False
    for t in doc["tickets"]:
        p = info.get(t.get("project_id") or "")
        if p is None:
            continue
        ms = set(t["milestones"])
        before = (set(ms), t.get("checks"), t.get("tokens"))
        if p.get("builds"):
            ms.add("first_build")
        if p.get("ok") is True:
            ms.add("gates_pass")
        elif p.get("ok") is False and "approved" not in ms:
            ms.discard("gates_pass")
        t["checks"] = None if not p.get("builds") else {"ok": bool(p.get("ok"))}
        t["tokens"] = int(p.get("tokens") or 0)
        t["milestones"] = [m for m, _l, _w in estimates.MILESTONES if m in ms]
        if (ms, t["checks"], t["tokens"]) != before:
            changed = True
            old_ms = before[0]
            t["progress"] = estimates.progress_of(t["milestones"])
            if "gates_pass" in ms and "gates_pass" not in old_ms:
                emit(root, doc, "ticket.milestone", f"{_label(t)}: the latest build passes the gating checks "
                     f"({t['progress']} %).", STUDIO_ACTOR, t["id"], milestone="gates_pass", reached=True,
                     progress=t["progress"])
            elif "first_build" in ms and "first_build" not in old_ms:
                emit(root, doc, "ticket.milestone", f"{_label(t)}: first build in the Design Studio "
                     f"({t['progress']} %).", STUDIO_ACTOR, t["id"], milestone="first_build", reached=True,
                     progress=t["progress"])
            elif "gates_pass" in old_ms and "gates_pass" not in ms:
                emit(root, doc, "ticket.milestone", f"{_label(t)}: the latest build fails a gating check "
                     f"({t['progress']} %).", STUDIO_ACTOR, t["id"], milestone="gates_pass", reached=False,
                     progress=t["progress"])
    return changed


# --------------------------------------------------------------------------- views
AGENT_STATE = {"in_design": "working", "in_review": "review", "changes_requested": "blocked",
               "approved": "done", "integrated": "done"}


def view(doc: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in doc.items() if k not in ("plan_history",)}
    items, tickets = doc["items"], doc["tickets"]
    out["columns"] = [{"code": c, "label": lbl} for c, lbl in COLUMNS]
    if items:
        ru = estimates.rollup(items, tickets)
        out["items"] = [{**it, "rollup": ru[it["id"]],
                         "eta": estimates.eta(items, tickets, it["id"], doc["concurrency"])
                         if it["kind"] != "part" else None} for it in items]
        out["rollup"] = ru["root"]
        out["eta"] = estimates.eta(items, tickets, "root", doc["concurrency"])
    else:
        out["rollup"] = None
        out["eta"] = None
    out["tickets"] = [{**t, "agent_state": AGENT_STATE.get(t["column"], "idle")} for t in tickets]
    out["counts"] = {c: sum(1 for t in tickets if t["column"] == c) for c in COLUMN_CODES}
    spent = int(doc["budget"].get("planning_tokens", 0)) + sum(int(t.get("tokens") or 0) for t in tickets)
    out["budget"] = {**doc["budget"], "spent": spent}
    if doc.get("plan") and doc["status"] == "plan_review":
        out["plan_estimate"] = plan_estimate(doc["plan"], doc["concurrency"])
    out["constants"] = estimates.constants()
    out["families"] = [{"code": f, "label": lbl, "specialist": s} for f, (lbl, s) in roster.FAMILIES.items()]
    return out


def summary(doc: dict[str, Any]) -> dict[str, Any]:
    v = view(doc)
    return {k: v.get(k) for k in ("id", "name", "key", "status", "planner", "created_at", "updated_at", "rollup",
                                  "eta", "counts", "budget", "gates", "concurrency")} | {
        "tickets": len(doc["tickets"]), "brief": doc["brief"][:300]}


def roster_view(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each agent's state across the organisation's programs, from the tickets assigned to it."""
    rank = {"working": 4, "review": 3, "blocked": 2, "idle": 0}
    out = []
    for a in roster.AGENTS:
        state, line, assigned, delivered, prog = "idle", a["idle_line"], 0, 0, None
        if a["code"] == "archie":
            planning = [d for d in docs if d["status"] == "planning"]
            waiting = [d for d in docs if d["status"] == "plan_review"]
            if planning:
                state, line, prog = "working", f"Archie is planning {planning[0]['name']}", planning[0]["id"]
            elif waiting:
                state, line, prog = "review", f"Archie's plan for {waiting[0]['name']} is waiting for you", \
                    waiting[0]["id"]
            delivered = sum(1 for d in docs if d["status"] in ("active", "complete"))
        else:
            best = None
            for d in docs:
                for t in d["tickets"]:
                    if t["specialist"] != a["code"]:
                        continue
                    if t["column"] in DONE_COLUMNS:
                        delivered += 1
                        continue
                    assigned += 1
                    s = AGENT_STATE.get(t["column"], "idle")
                    if best is None or rank[s] > rank[best[0]]:
                        best = (s, t, d)
            if best and best[0] != "idle":
                s, t, d = best
                state, prog = s, d["id"]
                line = {"working": f"{t['title']} is in design", "review": f"{t['title']} is waiting for review",
                        "blocked": f"{t['title']}: changes requested"}[s]
            elif assigned:
                line = f"{assigned} ticket{'s' if assigned != 1 else ''} queued"
        out.append({**a, "state": state, "line": line, "assigned": assigned, "delivered": delivered,
                    "program_id": prog})
    return out


def inbox(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for d in docs:
        if d["status"] == "plan_review":
            out.append({"kind": "brief", "program_id": d["id"], "program": d["name"], "at": d["updated_at"],
                        "title": f"Approve the brief and plan for {d['name']}",
                        "source": (d.get("plan") or {}).get("source")})
        for t in d["tickets"]:
            if t["column"] == "in_review":
                out.append({"kind": "ticket", "program_id": d["id"], "program": d["name"], "at": t["updated_at"],
                            "ticket_id": t["id"], "key": t["key"], "title": t["title"],
                            "specialist": t["specialist"], "checks": t.get("checks")})
    out.sort(key=lambda x: x["at"], reverse=True)
    return out
