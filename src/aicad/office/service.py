"""Program operations and the live event bus.

Every change to a program goes through a function here and emits one event. The manual board (Phase 2) calls these
with a ``user`` actor; the orchestrator (Phase 3) will call the same functions with an ``agent`` actor, so the board,
the roll-up and the activity feed need no changes when agents start working tickets.

Callers hold ``store.lock(program_id)`` around load -> change -> save.
"""

from __future__ import annotations

import asyncio
import math
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


_INSTANCE = re.compile(r"<(\d+)>")


def plain_names(text: str) -> str:
    """Agents' sentences say part names as people do: ``Gear shaft<1>`` -> ``Gear shaft``, ``Bearing<2>`` ->
    ``Bearing #2`` (the Assembly Studio tree keeps its SOLIDWORKS-style ``<n>``; live run 2026-11-19)."""
    return _INSTANCE.sub(lambda m: "" if m.group(1) == "1" else f" #{m.group(1)}", text or "")


def emit(root: Path, doc: dict[str, Any], type_: str, text: str, actor: dict[str, Any],
         ticket_id: str | None = None, **data: Any) -> dict[str, Any]:
    """Record one event (log + live bus). ``text`` is plain engineering language: it is shown as-is."""
    if actor.get("kind") == "agent":
        text = plain_names(text)
    doc["event_seq"] = int(doc.get("event_seq", 0)) + 1
    ev = {"seq": doc["event_seq"], "t": store.now(), "type": type_, "program_id": doc["id"], "ticket_id": ticket_id,
          "actor": actor, "text": text, "data": data}
    store.append_event(root, doc["id"], ev)
    bus.publish(doc["id"], ev)
    bus.publish(f"org:{doc['org_id']}", ev)
    return ev


# --------------------------------------------------------------------------- program lifecycle
def default_budget(wallet: int, unlimited: bool = False) -> int:
    """A new program's token budget when the engineer sets none: ``DEFAULT_BUDGET_TOKENS``, but never more than the
    workspace has left (a 1,000-token trial wallet got a 3,000 budget: live run 2026-11-19)."""
    return DEFAULT_BUDGET_TOKENS if unlimited else max(0, min(DEFAULT_BUDGET_TOKENS, int(wallet)))


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
                {"code": "icd", "name": "Architecture and interfaces", "mandatory": True, "status": "locked",
                 "note": "Opens when the brief is approved: Archie lays out the skeleton and names the interfaces."},
                {"code": "release", "name": "Release", "mandatory": True, "status": "locked"},
            ],
            "items": [], "tickets": [], "review_gate": False,
            "concurrency": max(1, min(estimates.MAX_CONCURRENCY, int(concurrency))),
            "budget": {"tokens": max(0, int(budget_tokens)), "planning_tokens": 0}}


def profile() -> str:
    """Which calibration profile applies now: simulated agents (development) never touch the live constants."""
    from aicad.office import fake_agents

    return "simulated" if fake_agents.enabled() else "live"


def snapshot_rates(root: Path, doc: dict[str, Any]) -> None:
    """The program takes the organisation's current calibrated rates when it is planned (CD-015)."""
    from aicad.office import calibration

    prof = profile()
    doc["calibration"] = {"profile": prof, "rates": calibration.rates(root, prof), "at": store.now()}


def rates_of(doc: dict[str, Any]) -> dict[str, float] | None:
    return (doc.get("calibration") or {}).get("rates")


def set_plan(root: Path, doc: dict[str, Any], plan: dict[str, Any], actor: dict[str, Any], *,
             narrative: str = "", note: str | None = None) -> None:
    snapshot_rates(root, doc)
    if doc.get("plan"):
        doc.setdefault("plan_history", []).append(doc["plan"])
        doc["plan_history"] = doc["plan_history"][-5:]
    plan = {**plan, "narrative": narrative, "note": note}
    doc["plan"], doc["status"], doc["planning"] = plan, "plan_review", None
    from aicad.office import scope

    doc["light"] = scope.light_info(plan, doc.get("brief") or "")
    n_parts = sum(len(s["parts"]) for s in plan["subassemblies"])
    who = "Archie" if plan["source"] == "archie" else "The standard planner"
    n_subs = len(plan["subassemblies"])
    emit(root, doc, "plan.ready", f"{who} split {doc['name']} into {n_subs} sub-assembl{'y' if n_subs == 1 else 'ies'} "
         f"and {n_parts} part{'' if n_parts == 1 else 's'}. Review the plan before tickets are created.", actor,
         source=plan["source"])


def gate(doc: dict[str, Any], code: str) -> dict[str, Any]:
    return next(g for g in doc["gates"] if g["code"] == code)


def plan_estimate(plan: dict[str, Any], concurrency: int, rates: dict[str, float] | None = None,
                  threads: dict[str, int] | None = None) -> dict[str, Any]:
    """Estimates for a plan that has no tickets yet (plan review shows what approval will create)."""
    items, tickets = _build(plan, "Program", "P", rates=rates)
    total = sum(t["estimate_min"] for t in tickets)
    return {"tickets": len(tickets), "estimate_min": round(total, 1),
            "eta": estimates.eta(items, tickets, "root", concurrency, threads)}


def default_threads() -> dict[str, int]:
    """New programs (PD-66): one thread per designer; Hex, Gage, Fitz, Ortho and Smithy share the office pool."""
    return {c: 1 for c in roster.DESIGNERS}


def set_threads(doc: dict[str, Any], raw: Any) -> dict[str, int]:
    """Per-agent threads (CD-027): parallel sub-agents of one specialist, capped by the program's concurrency."""
    clean = {k: v for k, v in estimates.clean_threads(raw).items() if k in roster.AGENT_CODES and k != "archie"}
    doc["threads"] = clean
    return clean


def threads_of(doc: dict[str, Any]) -> dict[str, int] | None:
    """None for programs from before per-agent threads: every agent shares the pool (the old behaviour)."""
    t = doc.get("threads")
    return t if isinstance(t, dict) else None


def _ticket_brief(program: str, brief: str, sub: str, part: dict[str, Any]) -> str:
    qty = f" ({part['qty']} off)" if part["qty"] > 1 else ""
    fam = roster.FAMILIES[part["family"]][0].lower()
    if part["family"] == "standard":
        return (f"{part['name']}{qty} for the {sub} of {program}: a standard part. {part['description']} "
                "Use the Toolbox component that fits, with sizes taken from the program brief.\n\n"
                f"Program brief: {brief[:1500]}")
    return (f"Design the {part['name']}{qty} for the {sub} of {program}, as a {fam} part. {part['description']}\n\n"
            f"Program brief: {brief[:1500]}")


def _build(plan: dict[str, Any], name: str, prefix: str, brief: str = "",
           rates: dict[str, float] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = [{"id": "root", "parent_id": None, "kind": "program", "name": name}]
    tickets: list[dict[str, Any]] = []
    seq = [0]

    def ticket(item_id: str, kind: str, title: str, family: str, complexity: int, qty: int, brief_: str,
               column: str, depends: list[str]) -> dict[str, Any]:
        seq[0] += 1
        t = {"id": f"t{seq[0]}", "key": f"{prefix}-{seq[0]}", "item_id": item_id, "kind": kind, "title": title,
             "brief": brief_, "family": family, "specialist": roster.specialist_for(family),
             "complexity": complexity, "estimate_min": estimates.estimate_minutes(family, complexity, rates),
             "qty": qty,
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
    items, tickets = _build(doc["plan"], doc["name"], doc["key"], doc["brief"], rates_of(doc))
    doc["items"], doc["tickets"], doc["ticket_seq"] = items, tickets, len(tickets)
    doc["status"] = "active"
    g = gate(doc, "brief")
    g.update(status="approved", by=actor.get("name"), at=store.now())
    edited = " (edited)" if doc["plan"].get("edited") else ""
    emit(root, doc, "gate.approved", f"{actor.get('name', 'Someone')} approved the brief and plan{edited}. "
         f"{len(tickets)} tickets opened.", actor, gate="brief")
    _light_deliverables(root, doc)
    from aicad.office import interfaces

    interfaces.create(root, doc, actor)


def _light_deliverables(root: Path, doc: dict[str, Any]) -> None:
    """The light path (PD-93) at plan approval: a small program makes its drawings and manufacturing review only when
    the brief asks for them or the engineer adds them later (Deliverables tab), unless the engineer chose "always"
    or "never" when creating it. Said in the activity, never a silent removal."""
    from aicad.office import scope

    doc["light"] = scope.light_info(doc.get("plan"), doc.get("brief") or "")
    if doc.get("deliverables_mode", "auto") != "auto":
        return
    lt = doc["light"]
    on = lt is None or bool(lt["deliverables_asked"])
    doc["deliverables_auto"] = on
    doc["deliverables_why"] = None if lt is None else (
        "Small program: the brief asks for drawings, so Ortho and Smithy follow the final assembly." if on else
        "Small program: drawings and the manufacturing review run only when you ask (Deliverables tab).")
    if lt is not None and not on:
        emit(root, doc, "program.light", f"{doc['name']} is a small program ({lt['parts']} parts, {lt['pieces']} "
             "pieces): the office assembles it first; drawings and the manufacturing review wait until you ask for "
             "them in the Deliverables tab.", agent_actor("archie"))


def express_ok(doc: dict[str, Any]) -> bool:
    """The plan and the interfaces may be approved in one step (light path, PD-93)."""
    return doc.get("status") == "plan_review" and bool(doc.get("light"))


def revise_plan(root: Path, doc: dict[str, Any], a: dict[str, Any], actor: dict[str, Any]) -> None:
    """Archie's "send the plan back" (applied by the engineer): while the interfaces wait for approval and nothing
    has started, the program returns to plan review with the note and (optionally) one part added. The tickets,
    skeleton and draft ICD go; approving the plan again lays the program out again (and Archie looks again)."""
    from aicad.office import archie_chat

    if not archie_chat.can_revise(doc):
        raise OfficeInputError("The plan can go back only while the interfaces wait for approval and no part work "
                               "has started.")
    plan = doc["plan"]
    if a.get("plan"):  # a whole earlier plan back (Archie's plan change undone, office/supervisor)
        subs = [{**sub, "parts": [dict(x) for x in sub["parts"]]} for sub in a["plan"]["subassemblies"]]
    else:
        subs = [{**sub, "parts": [dict(x) for x in sub["parts"]]} for sub in plan["subassemblies"]]
    add = a.get("add") or {}
    if add:
        sub = next((x for x in subs if x["name"] == add["sub"]), None)
        if sub is None:
            raise OfficeInputError("That sub-assembly is no longer in the plan.")
        sub["parts"].insert(0, dict(add["part"]))
    if a.get("remove"):  # one part out (a part the brief excludes, approved by the engineer)
        for sub in subs:
            sub["parts"] = [x for x in sub["parts"] if x["name"] != a["remove"]]
        subs = [sub for sub in subs if sub["parts"]]
    p2 = planner.normalise_plan({**plan, "subassemblies": subs}, plan["source"])
    if p2 is None:
        raise OfficeInputError("The revised plan is empty.")
    p2["edited"] = True
    doc["items"], doc["tickets"], doc["ticket_seq"] = [], [], 0
    for k in ("icd", "skeleton", "assembly"):
        doc.pop(k, None)
    g = gate(doc, "brief")
    for k in ("by", "at"):
        g.pop(k, None)
    g["status"] = "pending"
    gate(doc, "icd").update(status="locked", note="Opens when the brief is approved: Archie lays out the skeleton and "
                                                  "names the interfaces.")
    note = f"Archie sent the plan back at the interfaces gate: {a['notes']}"
    set_plan(root, doc, p2, actor, narrative=plan.get("narrative") or "", note=note)
    emit(root, doc, "plan.revised", f"{actor.get('name', 'Someone')} sent the plan back for review: {a['notes']}",
         actor, added=(add.get("part") or {}).get("name"), removed=a.get("remove"))


DELIVERABLE_TICKETS = (
    ("drawings", "Drawings: part sheets and the assembly drawing",
     ("Draw every part the program makes (Drawing Studio sheets, ICD interface numbers tagged as spec dimensions where "
     "they map) and the assembly drawing with its BOM table and balloons.")),
    ("dfm", "Manufacturing review of every part",
     ("Run the Manufacturing Advisor on every part the program makes and summarise the program: process per part, "
     "flags, relative cost.")),
)


def add_deliverables(root: Path, doc: dict[str, Any]) -> list[dict[str, Any]]:
    """After the final assembly is integrated: Ortho's and Smithy's deliverable tickets (CD-014). One complexity
    unit per two parts made; the estimate uses the program's calibrated rates."""
    from aicad.office import deliverables

    final = next((t for t in doc["tickets"] if t["kind"] == "integration" and t["item_id"] == "root"), None)
    n = len(deliverables.make_parts(doc))
    cx = estimates.clamp_complexity(max(1, math.ceil(n / 2)))
    out = []
    for code, title, brief in DELIVERABLE_TICKETS:
        doc["ticket_seq"] = int(doc.get("ticket_seq") or len(doc["tickets"])) + 1
        seq = doc["ticket_seq"]
        t = {"id": f"t{seq}", "key": f"{doc['key']}-{seq}", "item_id": "root", "kind": "deliverable",
             "deliverable": code, "title": title, "brief": brief, "family": code,
             "specialist": roster.specialist_for(code), "complexity": cx,
             "estimate_min": estimates.estimate_minutes(code, cx, rates_of(doc)), "qty": 1, "column": "ready",
             "milestones": [], "progress": 0, "project_id": None, "assembly_id": None,
             "depends_on": [final["id"]] if final else [], "comments": [], "checks": None, "tokens": 0, "run": None,
             "created_at": store.now(), "updated_at": store.now()}
        doc["tickets"].append(t)
        out.append(t)
    emit(root, doc, "deliverables.opened", f"First article assembled: Ortho draws the {n} part"
         f"{'s' if n != 1 else ''} the program makes and the assembly drawing with its BOM; Smithy reviews every part "
         "for manufacture.", agent_actor("archie"))
    return out


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
    """Complete = first article assembled: every part and integration ticket integrated (deliverables follow)."""
    core = [t for t in doc["tickets"] if t["kind"] != "deliverable"]
    done = bool(core) and all(t["column"] == "integrated" for t in core)
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
        if t["kind"] == "deliverable" and specialist != roster.specialist_for(t["family"]):
            raise OfficeInputError("Deliverables stay with their owner: Ortho draws, Smithy reviews for manufacture.")
        if t["kind"] == "integration" and specialist != "fitz":
            raise OfficeInputError("Fitz assembles sub-assemblies; assign part tickets to the designers.")
        if t["kind"] in ("part", "standard") and specialist not in roster.DESIGNERS + ("hex",):
            raise OfficeInputError(f"{roster.agent(specialist)['name']} doesn't design parts. Gage checks them "
                                   "independently, so he can't be the designer (no self-approval).")
        t["specialist"] = specialist
        changes.append(f"reassigned to {roster.agent(specialist)['name']}")
    if complexity is not None:
        cx = estimates.clamp_complexity(complexity)
        if cx != t["complexity"]:
            t["complexity"], t["estimate_min"] = cx, estimates.estimate_minutes(t["family"], cx, rates_of(doc))
            changes.append(f"complexity {cx} ({t['estimate_min']:g} min estimate)")
    if changes:
        _refresh(t)
        emit(root, doc, "ticket.updated", f"{actor.get('name', 'Someone')} updated {_label(t)}: "
             f"{', '.join(changes)}.", actor, tid)
    return t


def comment(root: Path, doc: dict[str, Any], tid: str, text: str, actor: dict[str, Any]) -> dict[str, Any]:
    t = ticket(doc, tid)
    body = (plain_names(text) if actor.get("kind") == "agent" else text).strip()[:MAX_COMMENT]
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
            # both can arrive in one sync (the build passed at once): say them in the order they happened (the
            # first build was silently skipped before, a flaky test on main)
            if "first_build" in ms and "first_build" not in old_ms:
                emit(root, doc, "ticket.milestone", f"{_label(t)}: first build in the Design Studio "
                     f"({t['progress']} %).", STUDIO_ACTOR, t["id"], milestone="first_build", reached=True,
                     progress=t["progress"])
            if "gates_pass" in ms and "gates_pass" not in old_ms:
                emit(root, doc, "ticket.milestone", f"{_label(t)}: the latest build passes the gating checks "
                     f"({t['progress']} %).", STUDIO_ACTOR, t["id"], milestone="gates_pass", reached=True,
                     progress=t["progress"])
            elif "gates_pass" in old_ms and "gates_pass" not in ms:
                emit(root, doc, "ticket.milestone", f"{_label(t)}: the latest build fails a gating check "
                     f"({t['progress']} %).", STUDIO_ACTOR, t["id"], milestone="gates_pass", reached=False,
                     progress=t["progress"])
    return changed


# --------------------------------------------------------------------------- views
AGENT_STATE = {"in_design": "working", "in_review": "review", "changes_requested": "blocked",
               "approved": "done", "integrated": "done"}
RUN_STATE = {"searching": "working", "designing": "working", "reviewing": "working", "integrating": "working",
             "fitting": "working", "drafting": "working", "screening": "working", "blocked": "blocked",
             "done": "done", "awaiting_review": "review"}
WORKING = ("searching", "designing", "reviewing", "integrating", "fitting", "drafting", "screening")


def ticket_view(t: dict[str, Any]) -> dict[str, Any]:
    """The card: who holds the ticket now (Hex searching, Mill designing, Gage inspecting, Fitz assembling), their
    state and the live status line. Tickets the office has not touched keep the Phase 2 column-derived state."""
    r = t.get("run") or {}
    st = r.get("status")
    state = RUN_STATE.get(st or "", AGENT_STATE.get(t["column"], "idle")) if st else AGENT_STATE.get(t["column"], "idle")
    if st in ("queued", "waiting_capacity", "retry", "manual") or t.get("paused"):
        state = "idle"
    if st == "done" and t["column"] not in DONE_COLUMNS:
        state = AGENT_STATE.get(t["column"], "idle")
    agent_code = r.get("agent") if st in WORKING else t["specialist"]
    if st in ("done", "awaiting_review") and r.get("agent") in ("hex", "gage", "fitz"):
        agent_code = r["agent"]
    from aicad.office import timeline

    actual = timeline.actual_minutes(t)
    done = t["column"] in DONE_COLUMNS and st in (None, "done")
    return {**t, "agent": agent_code or t["specialist"], "agent_label": r.get("agent_label") if st in WORKING else None,
            "actual_min": actual, "rounds": timeline.rounds(t),
            "error_pct": round(100.0 * (actual - float(t["estimate_min"])) / float(t["estimate_min"]), 1)
            if done and actual and t["estimate_min"] else None,
            "agent_state": state, "line": r.get("line"), "run_status": "paused" if t.get("paused") else st,
            "review_tokens": int(t.get("review_tokens") or 0), "spent": int(t.get("tokens") or 0) + int(t.get("review_tokens") or 0)}


def view(doc: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in doc.items() if k not in ("plan_history",)}
    items, tickets = doc["items"], doc["tickets"]
    out["columns"] = [{"code": c, "label": lbl} for c, lbl in COLUMNS]
    if items:
        ru = estimates.rollup(items, tickets)
        out["items"] = [{**it, "rollup": ru[it["id"]],
                         "eta": estimates.eta(items, tickets, it["id"], doc["concurrency"], threads_of(doc))
                         if it["kind"] != "part" else None} for it in items]
        out["rollup"] = ru["root"]
        out["eta"] = estimates.eta(items, tickets, "root", doc["concurrency"], threads_of(doc))
    else:
        out["rollup"] = None
        out["eta"] = None
    from aicad.office import orchestrator

    out["tickets"] = [ticket_view(t) for t in tickets]
    out["counts"] = {c: sum(1 for t in tickets if t["column"] == c) for c in COLUMN_CODES}
    from aicad.office import interfaces

    out.pop("skeleton", None)
    out["icd"] = interfaces.view(doc)
    from aicad.office import supervisor

    out["supervisor"] = supervisor.view(doc)  # Archie's log, rule overrides and what is relaxed (WORKLIST 49)
    out["change_requests"] = doc.get("change_requests") or []
    out["assembly"] = doc.get("assembly")
    b = orchestrator.budget_state(doc)
    out["budget"] = {**doc["budget"], "spent": b["spent"], "pct": b["pct"], "level": b["level"]}
    o = doc.get("orchestrator") or {}
    out["orchestrator"] = {"state": o.get("state", "idle"), "reason": o.get("reason"), "by": o.get("by"),
                           "started_at": o.get("started_at"), "capacity_until": o.get("capacity_until"),
                           "bypass": bool(o.get("god_tokens")),
                           "working": sum(1 for t in tickets if (t.get("run") or {}).get("status") in
                                          orchestrator.ACTIVE),
                           "waiting": sum(1 for t in tickets if (t.get("run") or {}).get("status") in
                                          ("waiting_capacity", "retry")),
                           "blocked": sum(1 for t in tickets if (t.get("run") or {}).get("status") == "blocked"),
                           "review": sum(1 for t in tickets if (t.get("run") or {}).get("status") == "awaiting_review")}
    out["review_gate"] = bool(doc.get("review_gate"))
    out["threads"] = threads_of(doc)
    out["ecns"] = doc.get("ecns") or []
    if doc.get("plan") and doc["status"] == "plan_review":
        out["plan_estimate"] = plan_estimate(doc["plan"], doc["concurrency"], rates_of(doc), threads_of(doc))
    out["constants"] = estimates.constants(rates_of(doc))
    out["families"] = [{"code": f, "label": lbl, "specialist": s} for f, (lbl, s) in roster.FAMILIES.items()]
    return out


def summary(doc: dict[str, Any]) -> dict[str, Any]:
    v = view(doc)
    v.pop("icd", None)
    return {k: v.get(k) for k in ("id", "name", "key", "status", "planner", "created_at", "updated_at", "rollup",
                                  "eta", "counts", "budget", "gates", "concurrency", "orchestrator", "released")} | {
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
            live = [(t, d) for d in docs for t in d["tickets"] if (t.get("run") or {}).get("agent") == a["code"]
                    and (t.get("run") or {}).get("status") in WORKING]
            if live:
                t, d = live[0]
                state, prog = "working", d["id"]
                line = t["run"].get("line") or f"{a['name']} is working on {t['title']}"
                if len(live) > 1:
                    line += f" (+{len(live) - 1} more)"
            elif best and best[0] != "idle":
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
        if d.get("icd") and next((g for g in d["gates"] if g["code"] == "icd"), {}).get("status") == "pending":
            out.append({"kind": "icd", "program_id": d["id"], "program": d["name"], "at": d["updated_at"],
                        "title": f"Review the interfaces (ICD v{d['icd']['version']}) for {d['name']}"})
        for t in d["tickets"]:
            if (t.get("run") or {}).get("status") == "blocked":
                out.append({"kind": "blocked", "program_id": d["id"], "program": d["name"], "at": t["updated_at"],
                            "ticket_id": t["id"], "key": t["key"], "title": t["title"],
                            "specialist": t["specialist"], "checks": t.get("checks"),
                            "reason": (t.get("run") or {}).get("blocked")})
                continue
            if (t.get("run") or {}).get("status") == "awaiting_review":
                out.append({"kind": "review", "program_id": d["id"], "program": d["name"], "at": t["updated_at"],
                            "ticket_id": t["id"], "key": t["key"], "title": t["title"],
                            "specialist": t["specialist"], "checks": t.get("checks")})
                continue
            if t["column"] == "in_review" and not (t.get("run") or {}).get("status"):
                out.append({"kind": "ticket", "program_id": d["id"], "program": d["name"], "at": t["updated_at"],
                            "ticket_id": t["id"], "key": t["key"], "title": t["title"],
                            "specialist": t["specialist"], "checks": t.get("checks")})
    out.sort(key=lambda x: x["at"], reverse=True)
    return out
