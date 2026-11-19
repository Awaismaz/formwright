"""The Design Office orchestrator (CD-006, CD-007, CD-008, CD-009, CD-016): one asyncio runner per program that
keeps up to ``program.concurrency`` agents working tickets.

Scheduling (pure, tested by hand calculation):
- A ticket is **claimable** when its dependencies are Approved/Integrated, it is not paused, taken over, blocked or
  already being worked, and (after a failure or a rate limit) its back-off time has passed.
- **Priority** is the critical path: the longest chain of remaining estimated effort that starts at the ticket and
  runs through the tickets waiting for it; ties go to the ticket with the most (transitive) dependents, then to the
  ticket order. The engineer's priority (high / normal / low) sorts first.
- **Concurrency** counts every running stage (Hex, a part agent, Gage, Fitz); it is never exceeded.

Work per ticket (stages, each persisted so a restart resumes where it stopped):
  part / standard:  hex (Toolbox and company parts, 0 tokens) -> design (specialist in the Studio project) ->
                    review (Gage: deterministic checks + AI note; send back up to 2 times, then the engineer)
  integration:      integrate (Fitz: assembly document, insert approved parts, auto-mate, interference)
  deliverables:     drawings (Ortho: a sheet per part with ICD spec dimensions, the assembly drawing with its BOM and
                    balloons) and dfm (Smithy: the Manufacturing Advisor on every part, the program DFM summary);
                    opened when the final assembly is integrated (CD-014)

Every stage is recorded on its ticket (``segments``: stage, agent instance, start, end) together with waits for
capacity and blocked spells; a finished ticket teaches its family's estimate (``calibration``, CD-015) and the
Timeline tab draws planned against actual (``timeline``).

Budget (CD-016): warn at 80 % of the program budget, stop claiming new work at 100 % (God mode's token bypass is
respected); every run's own budget is capped by what is left. Rate limits (the founder's subscription is shared):
exponential back-off and a "waiting for capacity" state on the board.

Everything that changes a program goes through ``aicad.office.service`` under ``store.lock`` and emits an event.
The platform side (database, Studio sessions, assemblies, the review model call) is behind ``Env``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aicad.office import (
    OfficeInputError,
    archie_chat,
    calibration,
    conformance,
    deliverables,
    direct,
    ecn,
    estimates,
    gage,
    interfaces,
    roster,
    service,
    specialists,
    store,
    timeline,
    visual_office,
)

log = logging.getLogger("aicad.office.orchestrator")

ACTIVE = {"searching", "designing", "reviewing", "integrating", "fitting", "drafting", "screening"}
STAGE_OF = {"searching": "hex", "designing": "design", "reviewing": "review", "integrating": "integrate",
            "fitting": "fit", "drafting": "drawings", "screening": "dfm"}
STATUS_OF = {"hex": "searching", "design": "designing", "review": "reviewing", "integrate": "integrating",
             "fit": "fitting", "drawings": "drafting", "dfm": "screening"}
STAGE_AGENT = {"hex": "hex", "integrate": "fitz", "review": "gage", "fit": "fitz"}
# stages that never take an LLM agent slot: Hex's Toolbox / parts lookup is deterministic (no model, no tokens; the
# live run 2026-11-19 had bearings wait 87 s for a slot), Fitz's swap-in is one shared step (CD-032)
FREE_STAGES = frozenset({"hex", "fit"})
MAX_CLASH_ROUNDS = 2       # times Fitz sends a part back for clashes before it waits for the engineer
PRIORITY = {"high": 1, "normal": 0, "low": -1}
MAX_ATTEMPTS = 2           # failed design runs retried before the ticket waits for the engineer
RETRY_BASE_S, RETRY_CAP_S = 20.0, 300.0
CAPACITY_BASE_S, CAPACITY_CAP_S = 30.0, 600.0
TICK_S = 1.0
BUDGET_WARN = 0.8
MIN_RUN_TOKENS = 20        # less budget than this left: no new design run starts (metering's preflight minimum)


class Stop(Exception):
    pass


# ============================================================================ pure scheduling
def run_of(t: dict[str, Any]) -> dict[str, Any]:
    return t.get("run") or {}


def _seq(t: dict[str, Any]) -> int:
    try:
        return int(str(t["id"]).lstrip("t"))
    except ValueError:
        return 0


def dependents(doc: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {t["id"]: [] for t in doc["tickets"]}
    for t in doc["tickets"]:
        for d in t.get("depends_on") or []:
            out.setdefault(d, []).append(t["id"])
    return out


def priority(doc: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Critical-path priority per ticket: ``chain`` = own remaining effort + the longest chain of tickets waiting
    for it; ``dependents`` = how many tickets wait for it, directly or through others."""
    by = {t["id"]: t for t in doc["tickets"]}
    deps = dependents(doc)
    chain: dict[str, float] = {}
    reach: dict[str, set[str]] = {}

    def rem(t: dict[str, Any]) -> float:
        return 0.0 if t["column"] in service.DONE_COLUMNS else estimates.remaining_min(t)

    def walk(tid: str, stack: frozenset[str] = frozenset()) -> None:
        if tid in chain or tid in stack:
            return
        kids = [k for k in deps.get(tid, []) if k in by]
        for k in kids:
            walk(k, stack | {tid})
        chain[tid] = round(rem(by[tid]) + max((chain.get(k, 0.0) for k in kids), default=0.0), 4)
        r: set[str] = set()
        for k in kids:
            r |= {k} | reach.get(k, set())
        reach[tid] = r

    for tid in by:
        walk(tid)
    return {tid: {"chain": chain[tid], "dependents": len(reach[tid])} for tid in by}


def deps_done(doc: dict[str, Any], t: dict[str, Any]) -> bool:
    """Every dependency is Approved / Integrated and none is still being fitted into the program assembly."""
    by = {x["id"]: x for x in doc["tickets"]}
    return all(by[d]["column"] in service.DONE_COLUMNS and run_of(by[d]).get("status") not in ACTIVE
               and run_of(by[d]).get("next") != "fit" for d in t.get("depends_on") or [] if d in by)


def first_stage(t: dict[str, Any]) -> str:
    if t["kind"] == "deliverable":
        return str(t["deliverable"])
    return "integrate" if t["kind"] == "integration" else "hex"


def claimable(doc: dict[str, Any], t: dict[str, Any], now: float) -> str | None:
    """The stage a ticket would start at if claimed now, or None."""
    r = run_of(t)
    if not interfaces.gate_open(doc):
        return None  # part work starts at the "Architecture and interfaces" gate
    if (t["column"] in service.DONE_COLUMNS and r.get("next") != "fit") or t.get("paused") or t.get("taken_over"):
        return None
    st = r.get("status")
    if st in ACTIVE or st in ("blocked", "done", "manual", "awaiting_review"):
        return None
    if st in ("waiting_capacity", "retry") and float(r.get("next_try_at") or 0) > now:
        return None
    if not deps_done(doc, t):
        return None
    if st is None:  # never touched by the orchestrator: only what the plan put in Backlog / Ready
        if t["column"] in ("ready", "backlog"):
            return first_stage(t)
        if t["column"] == "in_review" and t.get("project_id") and t["kind"] == "part":
            return "review"  # the engineer finished it by hand: Gage still checks it
        return None
    return r.get("next") or first_stage(t)


def queue(doc: dict[str, Any], now: float) -> list[tuple[dict[str, Any], str]]:
    pr = priority(doc)
    out = [(t, s) for t in doc["tickets"] if (s := claimable(doc, t, now))]
    out.sort(key=lambda ts: (-PRIORITY.get(ts[0].get("priority") or "normal", 0), -pr[ts[0]["id"]]["chain"],
                             -pr[ts[0]["id"]]["dependents"], _seq(ts[0])))
    return out


def backoff(n: int, base: float, cap: float) -> float:
    return min(cap, base * 2 ** max(0, n - 1))


def spent(doc: dict[str, Any]) -> int:
    return int(doc["budget"].get("planning_tokens", 0)) + sum(
        int(t.get("tokens") or 0) + int(t.get("review_tokens") or 0) for t in doc["tickets"])


def budget_state(doc: dict[str, Any]) -> dict[str, Any]:
    tokens = int(doc["budget"].get("tokens") or 0)
    s = spent(doc)
    pct = round(100.0 * s / tokens, 1) if tokens else 0.0
    bypass = bool((doc.get("orchestrator") or {}).get("god_tokens"))
    level = "ok" if not tokens or pct < 100 * BUDGET_WARN else "warn" if s <= tokens - MIN_RUN_TOKENS else "stop"
    return {"tokens": tokens, "spent": s, "pct": pct, "level": level, "bypass": bypass,
            "remaining": max(0, tokens - s) if tokens else None}


# ============================================================================ program and ticket controls
def orch(doc: dict[str, Any]) -> dict[str, Any]:
    return doc.setdefault("orchestrator", {"state": "idle"})


def start(root: Path, doc: dict[str, Any], actor: dict[str, Any], *, user_id: str, god_tokens: bool,
          god_paywall: bool) -> None:
    if doc["status"] not in ("active", "complete"):
        raise OfficeInputError("Approve the brief first: tickets open when the plan is approved.")
    o = orch(doc)
    if o.get("state") == "running":
        return  # idempotent
    if not interfaces.gate_open(doc):
        raise OfficeInputError("Approve the architecture and interfaces (ICD) first: part tickets are released at "
                               "that gate.")
    b = budget_state({**doc, "orchestrator": {"god_tokens": god_tokens}})
    if b["level"] == "stop" and not god_tokens:
        raise OfficeInputError("The program has used its token budget. Raise the budget to run more work.")
    o.update(state="running", user_id=user_id, by=actor.get("name"), god_tokens=god_tokens,
             god_paywall=god_paywall, started_at=store.now(), reason=None)
    o.setdefault("first_run_at", round(time.time(), 3))  # the timeline's origin
    o.setdefault("warned", False)
    service.emit(root, doc, "program.run", f"{actor.get('name', 'Someone')} pressed Run: the office works the "
                 f"tickets, {doc['concurrency']} at a time.", actor)


def pause(root: Path, doc: dict[str, Any], actor: dict[str, Any]) -> None:
    o = orch(doc)
    if o.get("state") != "running":
        return
    o.update(state="paused", reason=None)
    service.emit(root, doc, "program.paused", f"{actor.get('name', 'Someone')} paused the program. Agents finish "
                 "the step they are on; nothing new starts.", actor)


def open_wait(t: dict[str, Any], kind: str) -> None:
    """Start a waiting spell on the ticket (``capacity``: waiting for the AI service or the token balance;
    ``blocked``: waiting for the engineer). The timeline draws it until the ticket is picked up again."""
    w = t.get("wait_since")
    if w and w.get("kind") == kind:
        return
    close_wait(t)
    t["wait_since"] = {"kind": kind, "t": round(time.time(), 3)}


def close_wait(t: dict[str, Any]) -> None:
    w = t.pop("wait_since", None)
    if w:
        t.setdefault("segments", []).append({"stage": w["kind"], "kind": w["kind"], "agent": None, "label": None,
                                             "start": w["t"], "end": round(time.time(), 3)})


def _set_run(t: dict[str, Any], **kw: Any) -> dict[str, Any]:
    r = dict(run_of(t))
    for k in ("line", "blocked"):  # the card's words: part names as people say them
        if isinstance(kw.get(k), str):
            kw[k] = service.plain_names(kw[k])
    r.update(kw)
    t["run"] = r
    t["updated_at"] = store.now()
    return r


def control(root: Path, doc: dict[str, Any], tid: str, action: str, actor: dict[str, Any]) -> bool:
    """Engineer controls on one ticket. Returns True when a working agent must be interrupted."""
    t = service.ticket(doc, tid)
    r = run_of(t)
    who = actor.get("name", "Someone")
    busy = r.get("status") in ACTIVE
    if action == "pause":
        t["paused"] = True
        service.emit(root, doc, "ticket.paused", f"{who} paused {service._label(t)}.", actor, tid)
        return busy
    if action == "resume":
        t["paused"] = False
        service.emit(root, doc, "ticket.resumed", f"{who} resumed {service._label(t)}.", actor, tid)
        return False
    if action == "take_over":
        if t["kind"] == "deliverable":
            raise OfficeInputError("Ortho and Smithy make the deliverables from the parts: edit a sheet in Drawing "
                                   "Studio, or reopen the ticket to make them again.")
        if t["kind"] == "integration":
            raise OfficeInputError("Open the assembly to work on it by hand; Fitz only runs when you press Run.")
        t["taken_over"] = True
        t["manual_work"] = True  # an engineer's hands on it: its time doesn't calibrate the agents' estimates
        _set_run(t, status="manual", line=f"{who} took over: continuing by hand in the Design Studio")
        service.emit(root, doc, "ticket.taken_over", f"{who} took over {service._label(t)} and continues by hand.",
                     actor, tid)
        return busy
    if action == "hand_back":
        if not t.get("taken_over"):
            raise OfficeInputError("This ticket is not taken over.")
        t["taken_over"] = False
        _set_run(t, status="queued", next="design" if t["kind"] != "integration" else "integrate",
                 line="Handed back: waiting for an agent", attempt=0)
        service.emit(root, doc, "ticket.handed_back", f"{who} handed {service._label(t)} back to "
                     f"{roster.agent(t['specialist'])['name']}.", actor, tid)
        return False
    if action in ("reopen", "retry"):
        if busy:
            raise OfficeInputError("An agent is working on this ticket. Pause it or take over first.")
        t["taken_over"] = t["paused"] = False
        if action == "reopen":
            service.move(root, doc, tid, "ready" if deps_done(doc, t) or t["kind"] != "integration" else "backlog",
                         actor)
            t["milestones"] = [m for m in t["milestones"] if m not in ("self_review", "approved")]
            t["progress"] = estimates.progress_of(t["milestones"])
            t["reuse"] = None if t.get("reuse") and t["kind"] == "part" else t.get("reuse")
        nxt = first_stage(t) if action == "reopen" else (r.get("next") or first_stage(t))
        if action == "reopen" and t["kind"] == "part" and t.get("project_id"):
            nxt = "design"
        _set_run(t, status="queued", next=nxt, attempt=0, review_round=0, feedback=None, next_try_at=None,
                 line="Reopened: waiting for an agent" if action == "reopen" else "Retry: waiting for an agent")
        service.emit(root, doc, f"ticket.{action}", f"{who} {'reopened' if action == 'reopen' else 'retried'} "
                     f"{service._label(t)}.", actor, tid)
        return False
    raise OfficeInputError("Unknown action")


def gated(doc: dict[str, Any], t: dict[str, Any]) -> bool:
    """The program's optional per-part review gate (PD default: off): part tickets wait for the engineer after
    Gage passes them."""
    return bool(doc.get("review_gate")) and t["kind"] == "part"


def review_decision(root: Path, doc: dict[str, Any], tid: str, decision: str, note: str,
                    actor: dict[str, Any]) -> dict[str, Any]:
    """The engineer's decision at the per-part review gate. ``approve``: the part goes on to assembly exactly as a
    Gage approval does (Fitz swaps it in next). ``changes``: the ticket reopens with the note as the designer's
    instruction (its next turn starts from it)."""
    t = service.ticket(doc, tid)
    r = run_of(t)
    if r.get("status") != "awaiting_review":
        raise OfficeInputError("This ticket is not waiting for your review.")
    who = actor.get("name", "Someone")
    body = " ".join((note or "").split())[: service.MAX_COMMENT]
    close_wait(t)
    if decision == "approve":
        service.comment(root, doc, tid, f"Approved by {who} at the review gate." + (f" {body}" if body else ""), actor)
        t["comments"][-1]["delivery"] = "stored"
        service.move(root, doc, tid, "approved", actor)
        t["reviewed"] = {"by": who, "at": store.now(), "decision": "approved", "note": body or None}
        if (doc.get("assembly") or {}).get("status") in ("ready", "building") and                 t["item_id"] in (doc.get("skeleton") or {}).get("items", {}):
            _set_run(t, status="queued", next="fit", agent="fitz", agent_label="Fitz",
                     line=f"Approved by {who}: Fitz swaps {t['title']} in next")
        else:
            _set_run(t, status="done", next=None, line=f"Approved by {who}")
        service.emit(root, doc, "ticket.review_approved", f"{who} approved {service._label(t)} at the review gate.",
                     actor, tid)
        return t
    if decision != "changes":
        raise OfficeInputError("Decide approve or changes.")
    if not body:
        raise OfficeInputError("Say what should change: the note goes to the designer.")
    c = service.comment(root, doc, tid, f"Changes requested at the review gate: {body}", actor)
    c["delivery"] = "queued"
    service.move(root, doc, tid, "changes_requested", actor)
    t["reviewed"] = {"by": who, "at": store.now(), "decision": "changes", "note": body}
    name = roster.agent(t["specialist"])["name"]
    _set_run(t, status="queued", next="design", attempt=0, review_round=0, feedback=[f"Engineer review: {body}"],
             line=f"{who} requested changes: back to {name}")
    service.emit(root, doc, "ticket.review_changes", f"{who} requested changes on {service._label(t)}: {body}",
                 actor, tid, note=body)
    return t


def set_priority(root: Path, doc: dict[str, Any], tid: str, prio: str, actor: dict[str, Any]) -> None:
    if prio not in PRIORITY:
        raise OfficeInputError("Priority is high, normal or low.")
    t = service.ticket(doc, tid)
    if (t.get("priority") or "normal") == prio:
        return
    t["priority"] = prio
    service.emit(root, doc, "ticket.priority", f"{actor.get('name', 'Someone')} set {service._label(t)} to "
                 f"{prio} priority.", actor, tid, priority=prio)


def on_comment(root: Path, doc: dict[str, Any], tid: str, c: dict[str, Any]) -> None:
    """A user comment reaches the working agent: queued while it works, sent with its next turn. A comment on a
    ticket that waits for the engineer puts it back to the agent with the comment as the instruction."""
    t = service.ticket(doc, tid)
    if c["by"].get("kind") != "user":
        return
    r = run_of(t)
    st = r.get("status")
    name = roster.agent(t["specialist"])["name"]
    if t["kind"] == "integration" or t.get("taken_over") or t["column"] in service.DONE_COLUMNS or st is None:
        c["delivery"] = "stored"
        return
    c["delivery"] = "queued"
    t.setdefault("inbox", []).append(c["id"])
    if st == "blocked":
        _set_run(t, status="queued", next="design", attempt=0, review_round=0, line=f"Your comment goes to {name}")
    service.emit(root, doc, "ticket.comment_queued", f"Your comment on {service._label(t)} is queued for {name}"
                 + (" (it reaches the agent after the current step)." if st in ACTIVE else "."),
                 service.agent_actor(t["specialist"]), tid, comment_id=c["id"])


def recover(root: Path, doc: dict[str, Any], skip: set[str] | frozenset[str] = frozenset()) -> int:
    """After a restart: work that was running when the server stopped is queued again at the same stage."""
    n = 0
    for t in doc["tickets"]:
        r = run_of(t)
        if r.get("status") in ACTIVE and t["id"] not in skip:
            _set_run(t, status="queued", next=STAGE_OF[r["status"]], resume=r["status"] == "designing",
                     line="Resuming after a restart")
            n += 1
    if n:
        service.emit(root, doc, "program.resumed", f"The server restarted: {n} ticket{'s' if n != 1 else ''} "
                     "picked up where they stopped.", service.agent_actor("archie"))
    healed = heal_review_blocks(root, doc)
    return n + healed


_ROUND = re.compile(r"\b(insert|bush|bushing|pin|dowel|spacer|standoff|stand-off|nut|washer|rivet|collar|sleeve|"
                    r"bearing|seal|o-ring|circlip|shaft|roller)\b", re.IGNORECASE)


def to_designer(root: Path, doc: dict[str, Any], t: dict[str, Any]) -> str:
    """A standard part Hex couldn't find becomes a part ticket for a designer (turned parts to Chuck, else Mill)."""
    fam = "turned" if _ROUND.search(t["title"]) else "machined"
    t["kind"], t["family"] = "part", fam
    t["specialist"] = roster.specialist_for(fam)
    t["estimate_min"] = estimates.estimate_minutes(fam, max(1, int(t.get("complexity") or 1)), service.rates_of(doc))
    if "Model it as a bought-out part" not in t["brief"]:
        t["brief"] = (f"{t['title']}: no stock part in the Toolbox or the company's parts. Model it as a bought-out "
                      "part to its standard catalogue sizes (state the standard you follow), simple and accurate at "
                      "its interfaces.\n\n" + t["brief"])
    service.emit(root, doc, "ticket.updated", f"{service._label(t)}: not in stock, so "
                 f"{roster.agent(t['specialist'])['name']} models it.", service.agent_actor("hex"), t["id"])
    return str(t["specialist"])


def heal_review_blocks(root: Path, doc: dict[str, Any]) -> int:
    """Parts left waiting by the review rules before CD-030 (AI points could block forever) go back to Gage under
    the current rules: AI-only points end in an approval with the points recorded; a measurable failure comes back
    to the engineer with the failing check named. Runs whenever the office starts on a program."""
    out = []
    for t in doc["tickets"]:
        r = run_of(t)
        why = str(r.get("blocked") or "")
        if r.get("status") == "blocked" and t["kind"] == "deliverable" and why.startswith("Ortho couldn't finish every"):
            close_wait(t)  # CD-039: sheets needing a touch-up no longer stop the drawing set
            _set_run(t, status="queued", next=t.get("deliverable") or "drawings", attempt=0, blocked=None,
                     line="Back to Ortho: sheets that need a touch-up are flagged, not a stop")
            out.append(t)
            continue
        parts = (doc.get("assembly") or {}).get("parts") or {}
        if t["kind"] == "part" and t["column"] in service.DONE_COLUMNS and r.get("status") == "done" \
                and (parts.get(t["item_id"]) or {}).get("kind") == "placeholder" \
                and (doc.get("assembly") or {}).get("status") == "ready" and t.get("project_id"):
            _set_run(t, status="queued", next="fit", agent="fitz", fit_attempt=0,
                     line=f"Fitz swaps {t['title']} in for its placeholder (an earlier swap didn't finish)")
            out.append(t)
            continue
        if r.get("status") == "blocked" and t["kind"] == "integration" and (
                why.startswith(("Fitz is still waiting for the real", "Fitz couldn't swap", "Fitz found")) or why.startswith("Fitz couldn't integrate this") and "timed out" in why):
            close_wait(t)
            _set_run(t, status="queued", next="integrate", attempt=0, blocked=None, line="Back to Fitz")
            out.append(t)
            continue
        if r.get("status") == "blocked" and t["kind"] == "integration" \
                and why.startswith("The sub-assembly's assembly document is missing"):
            close_wait(t)  # a fastener-kit level: it integrates now (CD-034)
            _set_run(t, status="queued", next="integrate", attempt=0, blocked=None,
                     line="Back to Fitz: a kit of bought-out parts is fitted where the joints are")
            out.append(t)
            continue
        if r.get("status") == "blocked" and why.startswith("Hex couldn't find") and t["kind"] == "standard" \
                and not t.get("taken_over"):
            close_wait(t)
            to_designer(root, doc, t)
            _set_run(t, status="queued", next="design", attempt=0, blocked=None,
                     line=f"Not in stock: {roster.agent(t['specialist'])['name']} models it")
            out.append(t)
            continue
        if r.get("status") == "blocked" and r.get("next") == "review" and why.startswith("Gage sent") \
                and "measurable check" not in why and not t.get("taken_over"):
            close_wait(t)
            _set_run(t, status="queued", next="review", attempt=0, blocked=None,
                     line="Back to Gage under the current review rules")
            out.append(t)
    if out:
        service.emit(root, doc, "program.healed", f"Archie put {len(out)} part{'s' if len(out) != 1 else ''} blocked "
                     "by the old review rules back to Gage: advisory points no longer block a part that passes every "
                     "measurable check.", service.agent_actor("archie"), tickets=[t["key"] for t in out])
    return len(out)


# ============================================================================ the platform boundary
class Env:
    """What the orchestrator needs from the platform. ``platform_env.PlatformEnv`` is the real one."""

    simulated = False

    async def studio_info(self, doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {}

    async def hex_lookup(self, doc: dict[str, Any], t: dict[str, Any]) -> dict[str, Any] | None:
        return None

    async def ensure_project(self, root: Path, pid: str, tid: str) -> str:
        raise NotImplementedError

    async def run_budget(self, doc: dict[str, Any], remaining: int | None) -> tuple[int | None, str | None]:
        """(tokens for one run or None when unlimited, a reason when no run is possible: "capacity"/"balance")."""
        return None, None

    async def design(self, project_id: str, prompt: str, shown: str, budget: int | None,
                     on_event: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        """One agent turn. Returns {ok_run, rate_limited, interrupted, tokens, error}."""
        raise NotImplementedError

    async def interrupt(self, project_id: str) -> None:
        return None

    async def warm(self) -> None:
        """Start the program's geometry engine ahead of its first build."""
        return

    async def design_direct(self, project_id: str, script: str, note: str) -> dict[str, Any]:
        """Build a model script written without AI (``direct``) through the Studio's build and check gate, as the
        project's new revision. {ok (verified: CHK-02..08), build_s, checks_s, error}."""
        return {"ok": False, "error": "building from the interface spec is not available here"}

    async def part_state(self, project_id: str) -> dict[str, Any]:
        """{builds, ok, checks, bbox, params, source} of the project's latest build."""
        raise NotImplementedError

    async def review_ai(self, doc: dict[str, Any], t: dict[str, Any], state: dict[str, Any],
                        budget: int | None, previous: list[str] | None = None) -> dict[str, Any] | None:
        return None

    async def integrate(self, root: Path, pid: str, tid: str) -> dict[str, Any]:
        raise NotImplementedError

    async def look_level(self, root: Path, pid: str, tid: str, res: dict[str, Any]) -> dict[str, Any] | None:
        """PD-73: look at the level Fitz just integrated (quick placement checks + the visual check, advisory).
        {stop, reason, line, ...} or None (nothing to look at)."""
        return None

    # ---- Phase 4: interfaces, placeholders and the program assembly
    async def conformance(self, doc: dict[str, Any], t: dict[str, Any]) -> dict[str, Any] | None:
        """ICD conformance of the ticket's latest build (``conformance.measure``), or None when not measurable."""
        return None

    async def swap_in(self, root: Path, pid: str, tid: str) -> dict[str, Any]:
        """Put the approved part into the program assembly in place of its placeholder. {last, problems, mates}."""
        return {"skipped": "No program assembly to fit into."}

    # ---- Phase 5: deliverables
    async def drawing(self, doc: dict[str, Any], t: dict[str, Any], project_id: str) -> dict[str, Any]:
        """Ortho: the part's drawing sheet (Drawing Studio) with ICD spec dimensions. {ok, check_passed, ...}."""
        return {"ok": False, "error": "Drawing Studio is not available here."}

    async def assembly_drawing(self, root: Path, pid: str) -> dict[str, Any]:
        """Ortho: the program's assembly drawing with its BOM table and balloons (DRW-014). {ok, balloons, ...}."""
        return {"ok": False, "error": "Drawing Studio is not available here."}

    async def dfm(self, doc: dict[str, Any], t: dict[str, Any], project_id: str) -> dict[str, Any]:
        """Smithy: the Manufacturing Advisor's analysis of the part. {analysis} or {error}."""
        return {"error": "The Manufacturing Advisor is not available here."}

    async def decide_cr(self, root: Path, pid: str, cid: str) -> dict[str, Any]:
        """Archie decides a change request (rule + optional AI note) and regenerates placeholders on accept."""
        from aicad.office import platform_env

        return await platform_env.decide_cr(root, pid, cid, None)


EnvFactory = Callable[[Path, dict[str, Any]], Env]
_env_factory: EnvFactory | None = None


def set_env_factory(f: EnvFactory | None) -> None:
    """Tests (and nothing else) swap the platform boundary."""
    global _env_factory
    _env_factory = f


def make_env(root: Path, doc: dict[str, Any]) -> Env:
    if _env_factory is not None:
        return _env_factory(root, doc)
    from aicad.office.platform_env import PlatformEnv

    return PlatformEnv(root, doc)


# ============================================================================ the runner
class Runner:
    def __init__(self, root: Path, pid: str, env: Env) -> None:
        self.root, self.pid, self.env = root, pid, env
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.stages: dict[str, str] = {}  # the stage each running task is in now (fit runs outside the slots)
        self.labels: dict[str, tuple[str, int]] = {}
        self.wake = asyncio.Event()
        self.loop = asyncio.get_running_loop()
        self.max_seen = 0  # the most slot-taking stages that ever ran at once (tests assert the cap)
        self.main: asyncio.Task[None] | None = None
        self.warming: asyncio.Task[None] | None = None  # the geometry engine starting for direct builds

    # ------------------------------------------------------------------ helpers
    def edit(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        with store.lock(self.pid):
            doc = store.load(self.root, self.pid)
            if doc is None:
                raise Stop("program deleted")
            r = fn(doc)
            store.save(self.root, doc)
            return r

    def load(self) -> dict[str, Any]:
        doc = store.load(self.root, self.pid)
        if doc is None:
            raise Stop("program deleted")
        return doc

    def label(self, tid: str, code: str) -> str:
        """Mill, Mill #2, ... (parallel instances of one specialist)."""
        cur = self.labels.get(tid)
        if cur and cur[0] == code:
            n = cur[1]
        else:
            used = {n for t, (c, n) in self.labels.items() if c == code and t != tid}
            n = next(i for i in range(1, 99) if i not in used)
            self.labels[tid] = (code, n)
        nm = roster.agent(code)["name"]
        return nm if n == 1 else f"{nm} #{n}"

    def status(self, doc: dict[str, Any], t: dict[str, Any], code: str, line: str, **run: Any) -> None:
        """Set the live status line on the card (and the run state), and tell the board."""
        if run_of(t).get("line") == line and all(run_of(t).get(k) == v for k, v in run.items()):
            return
        _set_run(t, line=line, agent=code, agent_label=self.label(t["id"], code), **run)
        service.emit(self.root, doc, "agent.status", line, service.agent_actor(code), t["id"], agent=code)

    def handoff(self, doc: dict[str, Any], t: dict[str, Any], a: str, b: str, text: str) -> None:
        service.emit(self.root, doc, "ticket.handoff", text, service.agent_actor(a), t["id"], **{"from": a, "to": b})

    # ------------------------------------------------------------------ the loop
    async def run(self) -> None:
        try:
            self.edit(lambda d: recover(self.root, d, set(self.tasks)))
            # parts built from the interfaces need the geometry engine at once: start it now, not on the first build
            self.warming = asyncio.get_running_loop().create_task(self.env.warm())
            self.warming.add_done_callback(lambda t: t.cancelled() or t.exception())
            while True:
                info = await self.env.studio_info(self.load())
                if self.tick(info):
                    break
                try:
                    await asyncio.wait_for(self.wake.wait(), TICK_S)
                except TimeoutError:
                    pass
                self.wake.clear()
        except Stop:
            pass
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("orchestrator loop failed")
        finally:
            if _runners.get(self.pid) is self and not self.tasks:
                _runners.pop(self.pid, None)

    def tick(self, info: dict[str, dict[str, Any]]) -> bool:
        """Claim what the cap and the budget allow. Returns True when the loop should end."""
        now = time.time()
        claims: list[tuple[str, str]] = []

        def fn(doc: dict[str, Any]) -> bool:
            if info:
                service.sync_studio(self.root, doc, info)
            o = orch(doc)
            if o.get("state") != "running":
                return not self.tasks
            core = [t for t in doc["tickets"] if t["kind"] != "deliverable"]
            if core and all(t["column"] == "integrated" for t in core):
                deliv = [t for t in doc["tickets"] if t["kind"] == "deliverable"]
                if not deliv and doc.get("deliverables_auto", True):
                    service.add_deliverables(self.root, doc)
                    deliv = [t for t in doc["tickets"] if t["kind"] == "deliverable"]
                if all(t["column"] in service.DONE_COLUMNS for t in deliv):
                    o.update(state="complete")
                    if deliv:
                        g = service.gate(doc, "release")
                        if g["status"] == "locked":
                            g.update(status="pending", note="Drawings, BOM and the manufacturing review are ready: "
                                                            "release the program.")
                            ecn.mark_ready(self.root, doc)
                    service.emit(self.root, doc, "program.done", f"{doc['name']}: every ticket is integrated"
                                 + (", the drawings, BOM and manufacturing review are done. Ready to release."
                                    if deliv else ". The office has stopped."), service.agent_actor("archie"))
                    return True
            b = budget_state(doc)
            if not b["bypass"] and b["level"] in ("warn", "stop") and not o.get("warned"):
                o["warned"] = True
                service.emit(self.root, doc, "budget.warn", f"{doc['name']} has used {b['pct']:g} % of its "
                             f"{b['tokens']} token budget.", service.agent_actor("archie"), pct=b["pct"])
            if not b["bypass"] and b["level"] == "stop":
                o.update(state="stopped", reason="budget")
                left = f"reached its token budget ({b['spent']} of {b['tokens']})" if b["remaining"] == 0 else \
                    f"has {b['remaining']} of its {b['tokens']} budget tokens left, too few for another run"
                service.emit(self.root, doc, "budget.stop", f"{doc['name']} {left}. No new work starts; raise the "
                             "budget and press Resume to continue.", service.agent_actor("archie"), pct=b["pct"])
                return not self.tasks
            if float(o.get("capacity_until") or 0) > now:
                return False
            fitting = {t for t in self.tasks if self.stages.get(t) == "fit"}
            # swapping a part into the program assembly is one shared step (it batches every part waiting) and Hex's
            # lookups are deterministic: neither takes an agent slot from design, review or integration (CD-032)
            free = max(0, int(doc["concurrency"]) - self.slots_used())
            threads = service.threads_of(doc) or {}
            busy: dict[str, int] = {}  # running work per agent: per-agent threads cap it (CD-027)
            for x in doc["tickets"]:
                if x["id"] in self.tasks:
                    a = run_of(x).get("agent") or x["specialist"]
                    busy[a] = busy.get(a, 0) + 1
            for t, stage in queue(doc, now):
                if t["id"] in self.tasks:
                    continue
                if stage == "fit":
                    if fitting:
                        continue
                    fitting.add(t["id"])
                elif stage not in FREE_STAGES and free <= 0:
                    continue
                code = STAGE_AGENT.get(stage, t["specialist"])
                if stage not in FREE_STAGES and threads.get(code) and busy.get(code, 0) >= threads[code]:
                    continue
                busy[code] = busy.get(code, 0) + 1
                lbl = self.label(t["id"], code)
                close_wait(t)
                _set_run(t, status=STATUS_OF[stage], next=stage, agent=code, agent_label=lbl,
                         started_at=store.now(), line=f"{lbl} picked up {t['title']}")
                service.emit(self.root, doc, "ticket.claimed", f"{lbl} picked up {service._label(t)}.",
                             service.agent_actor(code), t["id"], stage=stage, agent=code)
                claims.append((t["id"], stage))
                self.stages[t["id"]] = stage
                if stage not in FREE_STAGES:
                    free -= 1
            return False

        stop = self.edit(fn)
        for tid, stage in claims:
            self.tasks[tid] = asyncio.create_task(self.work(tid, stage))
        self.max_seen = max(self.max_seen, self.slots_used())
        return bool(stop)

    def slots_used(self) -> int:
        """Running work that holds an agent slot (everything but Hex's lookups and Fitz's swap-in)."""
        return sum(1 for t in self.tasks if self.stages.get(t) not in FREE_STAGES)

    async def work(self, tid: str, stage: str | None) -> None:
        try:
            while stage:
                self.stages[tid] = stage
                t0 = time.time()
                code = STAGE_AGENT.get(stage) or service.ticket(self.load(), tid)["specialist"]
                lbl = self.label(tid, code)
                nxt = await getattr(self, f"_{stage}")(tid)
                self._segment(tid, stage, code, lbl, t0)
                stage = nxt
                if stage and self._halt(tid, stage):
                    break
        except Stop:
            pass
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("ticket work failed")
            try:
                self.edit(lambda d: self._fail(d, tid, "An internal error stopped this ticket. Retry it, or take over."))
            except Stop:
                pass
        finally:
            self.tasks.pop(tid, None)
            self.labels.pop(tid, None)
            self.wake.set()

    def _segment(self, tid: str, stage: str, code: str, lbl: str, t0: float) -> None:
        """Record one stage's work on the ticket; a ticket that has just finished teaches its estimate."""
        t1 = time.time()

        def fn(d: dict[str, Any]) -> None:
            tt = service.ticket(d, tid)
            seg = {"stage": stage, "kind": "work", "agent": code, "label": lbl, "start": round(t0, 3),
                   "end": round(t1, 3)}
            tt["segments"] = (tt.get("segments") or [])[-199:] + [seg]
            self._calibrate(d, tt)
        try:
            self.edit(fn)
        except Stop:
            pass

    def _calibrate(self, d: dict[str, Any], tt: dict[str, Any]) -> None:
        r = run_of(tt)
        if tt["column"] not in service.DONE_COLUMNS or r.get("status") != "done":
            return
        actual = timeline.actual_minutes(tt)
        if tt.get("calibrated"):
            tt["calibrated"]["actual_min_now"] = actual  # reopened and finished again: shown, not learned twice
            return
        if (tt.get("direct") or {}).get("path") == "direct" and not tt["direct"].get("superseded"):
            # built from the interfaces in seconds: not a sample of the designer's rate (it would skew the estimates)
            tt["calibrated"] = {"actual_min": actual, "learned": False, "at": store.now(),
                                "why": "built from the interface spec (no AI)"}
            return
        if tt.get("manual_work") or not actual:
            tt["calibrated"] = {"actual_min": actual, "learned": False, "at": store.now(),
                                "why": "an engineer worked on it by hand" if tt.get("manual_work") else "no agent time"}
            return
        prof = "simulated" if self.env.simulated else "live"
        e = calibration.record(self.root, prof, family=tt["family"], complexity=tt["complexity"],
                               estimate_min=tt["estimate_min"], actual_min=actual, ticket=tt, program=d,
                               stages=timeline.stage_minutes(tt))
        tt["calibrated"] = {"actual_min": actual, "learned": True, "at": e["at"], "error_pct": e["error_pct"],
                            "before": e["before"], "after": e["after"], "observed": e["observed"],
                            "profile": prof}
        name = roster.agent(roster.specialist_for(tt["family"]))["name"]
        service.emit(self.root, d, "estimate.calibrated",
                     f"{service._label(tt)} took {_mins(actual)} against {_mins(float(tt['estimate_min']))} estimated: "
                     f"{name}'s rate for {roster.family_label(tt['family']).lower()} moves {e['before']:g} → "
                     f"{e['after']:g} min per complexity unit.", service.agent_actor("archie"), tt["id"],
                     family=tt["family"], before=e["before"], after=e["after"], error_pct=e["error_pct"])

    def _halt(self, tid: str, nxt: str) -> bool:
        """Between stages: stop for a paused program, a paused ticket or a take-over (resumable at ``nxt``)."""
        def fn(doc: dict[str, Any]) -> bool:
            t = service.ticket(doc, tid)
            o = orch(doc)
            if t.get("taken_over"):
                _set_run(t, status="manual", next=nxt)
                return True
            if t.get("paused") or o.get("state") != "running":
                why = "paused" if t.get("paused") else "the program is paused" if o.get("state") == "paused" \
                    else "the program stopped"
                _set_run(t, status="queued", next=nxt, line=f"Waiting: {why}")
                return True
            return False
        return bool(self.edit(fn))

    def _fail(self, doc: dict[str, Any], tid: str, why: str, tell: bool = True) -> None:
        t = service.ticket(doc, tid)
        _set_run(t, status="blocked", line=why, blocked=why)
        open_wait(t, "blocked")
        if t["column"] != "changes_requested":
            service.move(self.root, doc, tid, "changes_requested", service.agent_actor("archie"))
        service.emit(self.root, doc, "ticket.blocked", f"{service._label(t)} needs you: {why}",
                     service.agent_actor(t["specialist"]), tid)
        if tell:  # founder 2026-11-19: Archie tells the engineer what failed and what he proposes
            visual_office.on_failure(self.root, doc, t, why)

    # ------------------------------------------------------------------ stage: Hex
    async def _hex(self, tid: str) -> str | None:
        doc = self.load()
        t = service.ticket(doc, tid)
        self.edit(lambda d: self.status(d, service.ticket(d, tid), "hex",
                                        f"Hex is searching the Toolbox and your parts for {t['title']}"))
        hit = await self.env.hex_lookup(doc, t)

        def fn(d: dict[str, Any]) -> str | None:
            tt = service.ticket(d, tid)
            hex_ = service.agent_actor("hex")
            if hit:
                tt["reuse"] = hit
                tt["milestones"] = [m for m, _l, _w in estimates.MILESTONES]
                service.move(self.root, d, tid, "approved", hex_)
                tt["milestones"] = [m for m, _l, _w in estimates.MILESTONES]
                tt["progress"] = 100
                _set_run(tt, status="done", line=f"{hit['found']} (0 tokens)", agent="hex")
                service.emit(self.root, d, "ticket.reused", f"{hit['found']} for {service._label(tt)} (0 tokens).",
                             hex_, tid, source=hit["source"])
                parent = next((x for x in d["tickets"] if tid in (x.get("depends_on") or [])), None)
                if parent:
                    self.handoff(d, tt, "hex", "fitz", f"Hex → Fitz: {tt['title']} is in stock, ready for assembly.")
                return None
            if tt["kind"] == "standard":  # not in stock: a designer models it to its catalogue sizes (CD-031)
                spec = to_designer(self.root, d, tt)
                self.handoff(d, tt, "hex", spec, f"Hex → {roster.agent(spec)['name']}: {tt['title']} is not in the "
                             "Toolbox or your parts, model it as a bought-out part to its catalogue sizes.")
            else:
                spec = tt["specialist"]
                self.handoff(d, tt, "hex", spec, f"Hex → {roster.agent(spec)['name']}: no stock part for "
                             f"{tt['title']}, design it.")
            # Hex ran outside the agent slots: the design turn queues for a slot (in critical-path order)
            _set_run(tt, status="queued", next="design",
                     line=f"Waiting for {roster.agent(spec)['name']}: Hex found no stock part")
            return None
        return self.edit(fn)

    # ------------------------------------------------------------------ stage: the part agent
    async def _design(self, tid: str) -> str | None:
        doc = self.load()
        t = service.ticket(doc, tid)
        code = t["specialist"]
        if code not in specialists.DESIGNERS:
            self.edit(lambda d: self._fail(d, tid, f"{roster.agent(code)['name']} doesn't design parts. Reassign "
                                                   "the ticket to a designer (Mill, Chuck, Axel, Benny or Molly)."))
            return None
        # a part the approved interfaces fix completely is built from them, without AI (no tokens, seconds)
        seed: dict[str, Any] | None = None
        dp = await self._direct_plan(doc, t)
        if dp is not None and dp["path"] == "direct":
            nxt = await self._direct(tid, dp)
            if nxt != "agent":
                return nxt
            doc = self.load()
            dp = None
        elif dp is not None:
            seed = dp.get("seed")
        b = budget_state(doc)
        if b["level"] == "stop" and not b["bypass"]:
            self.edit(lambda d: _set_run(service.ticket(d, tid), status="queued", next="design",
                                         line="Waiting: the program budget is used up"))
            return None
        budget, why = await self.env.run_budget(doc, None if b["bypass"] else b["remaining"])
        if why:
            return self._capacity(tid, "design", why)
        project_id = await self.env.ensure_project(self.root, self.pid, tid)
        lbl = self.label(tid, code)
        seeded = False
        if seed is not None:  # the interfaces fix the part but the brief asks for more: start the agent from them
            res0 = await self.env.design_direct(project_id, seed["script"], direct.note(seed, seed=True))
            seeded = bool(res0.get("ok"))

        def prep(d: dict[str, Any]) -> tuple[str, str]:
            tt = service.ticket(d, tid)
            r = run_of(tt)
            if tt["column"] != "in_design":
                service.move(self.root, d, tid, "in_design", service.agent_actor(code))
            prev = tt.get("direct") or {}
            if dp is not None and not prev:
                tt["direct"] = {"path": "agent", "reasons": dp["reasons"], "seeded": seeded, "at": store.now()}
            elif prev.get("path") == "direct" and not prev.get("superseded"):
                tt["direct"] = {**prev, "superseded": True}  # the agent works on it from here (findings, comments)
            pending = [c for c in tt["comments"] if c["id"] in (tt.get("inbox") or [])]
            for c in pending:
                c["delivery"] = "delivered"
            tt["inbox"] = []
            fb = r.get("feedback") or None
            resume = bool(r.get("resume"))
            notes = list(tt.pop("icd_delta", None) or []) + list(tt.pop("cr_notes", None) or [])
            excerpt = None
            if interfaces.has_icd(d) and tt["item_id"] in d["skeleton"]["items"]:
                from aicad.office import icd as icd_mod

                excerpt = icd_mod.excerpt(d["skeleton"], d["icd"], tt["item_id"])
            text = specialists.prompt(code, tt, feedback=fb, comments=pending, full=resume or not r.get("turns"),
                                      resume=resume, icd=excerpt, icd_notes=notes)
            if seeded:
                text += "\n\n" + direct.seed_prompt(dp["reasons"] if dp else [])
            shown = specialists.shown(tt, lbl, feedback=bool(fb), comments=bool(pending) and not fb,
                                      icd=bool(notes) and not fb)
            _set_run(tt, status="designing", next="design", feedback=None, resume=False,
                     turns=int(r.get("turns") or 0) + 1, stage_seen=[])
            if pending:
                service.emit(self.root, d, "ticket.comment_delivered", f"{lbl} got {len(pending)} comment"
                             f"{'s' if len(pending) != 1 else ''} on {service._label(tt)}.", service.agent_actor(code),
                             tid)
            self.status(d, tt, code, specialists.line(code, "reading", tt["title"], lbl))
            return text, shown

        text, shown = self.edit(prep)
        seen: set[str] = set()
        said: list[str] = []

        def on_event(ev: dict[str, Any]) -> None:
            if ev.get("type") == "text":
                said.append(str(ev.get("text") or ""))
            try:
                self.edit(lambda d: self._progress(d, tid, code, lbl, ev, seen))
            except Stop:
                pass

        res = await self.env.design(project_id, text, shown, budget, on_event)
        state = await self.env.part_state(project_id)
        await self._change_request(tid, "\n".join(said))

        def after(d: dict[str, Any]) -> str | None:
            tt = service.ticket(d, tid)
            r = run_of(tt)
            if tt.get("taken_over") or tt.get("paused"):
                return "design"  # _halt records why
            if res.get("rate_limited"):
                return self._capacity_doc(d, tt, "design", "rate")
            if res.get("budget_stopped"):
                # the turn was cut at its run budget: whatever it built last is not the designer's finished part, so
                # it never goes to Gage or counts as approved (live run 2026-11-19: stopped at the budget, approved)
                built = bool(state.get("builds") and state.get("ok") is True)
                cap = res.get("budget")
                _set_run(tt, next="design", resume=True)
                self._fail(d, tid, f"{lbl} stopped at its run budget"
                           + (f" ({cap} tokens)" if cap else "") + " before finishing "
                           + (f"{tt['title']}: the last build passes its checks but the design isn't finished, so it "
                              "is not sent for review. " if built else f"{tt['title']}, with no passing build. ")
                           + "Retry to let it carry on (it uses more tokens), or take it over in the Studio.")
                return None
            if state.get("builds") and state.get("ok") is True:
                for m in ("brief_read", "first_build", "gates_pass", "self_review"):
                    if m not in tt["milestones"]:
                        service.set_milestone(self.root, d, tid, m, True, service.agent_actor(code))
                if tt.get("inbox") or tt.get("icd_delta") or tt.get("cr_notes"):
                    return "design"  # comments / an ICD change arrived during the turn: the agent reads them next
                service.move(self.root, d, tid, "in_review", service.agent_actor(code))
                _set_run(tt, status="reviewing", next="review", attempt=0)
                self.handoff(d, tt, code, "gage", f"{lbl} → Gage: {tt['title']} for inspection.")
                return "review"
            n = int(r.get("attempt") or 0) + 1
            if n > MAX_ATTEMPTS:
                self._fail(d, tid, f"{lbl} stopped {n} times without a build that passes the gating checks. Open "
                                   "it in the Design Studio, comment, or retry.")
                return None
            wait = backoff(n, RETRY_BASE_S, RETRY_CAP_S)
            _set_run(tt, status="retry", next="design", attempt=n, next_try_at=time.time() + wait,
                     line=f"{lbl} stopped without a passing build: trying again in {wait:.0f} s")
            if n == 1:
                visual_office.on_failure(self.root, d, tt, f"{lbl} stopped without a build that passes the gating "
                                         "checks.", retrying=True)
            service.emit(self.root, d, "ticket.retry", f"{service._label(tt)}: no passing build yet; retry {n} of "
                         f"{MAX_ATTEMPTS} in {wait:.0f} s.", service.agent_actor(code), tid, attempt=n)
            return None
        return self.edit(after)

    async def _direct_plan(self, doc: dict[str, Any], t: dict[str, Any]) -> dict[str, Any] | None:
        """How this design turn runs (``direct.plan``), or None when the design agent must take it as it is: the
        checker's findings or the engineer's comments to act on, a take-over, or a model that is no longer the one
        the interfaces produced (an agent or an engineer changed it)."""
        if not direct.enabled(doc) or t["kind"] != "part" or t.get("taken_over"):
            return None
        if run_of(t).get("feedback") or t.get("inbox"):
            return None
        prev = t.get("direct") or {}
        if t.get("project_id"):
            if prev.get("path") != "direct" or prev.get("superseded"):
                return None
            st = await self.env.part_state(t["project_id"])
            if direct.sha(st.get("source") or "") != prev.get("sha"):
                return None  # edited in the Design Studio since: never overwrite the engineer's work
        return direct.plan(doc, t)

    async def _direct(self, tid: str, dp: dict[str, Any]) -> str | None:
        """Build the part from its interfaces: the script ``direct.plan`` wrote, through the same build and check
        gate as an agent's build, then Gage. Returns the next stage, or "agent" when the build didn't pass."""
        t = service.ticket(self.load(), tid)
        code = t["specialist"]
        project_id = await self.env.ensure_project(self.root, self.pid, tid)
        lbl = self.label(tid, code)

        def prep(d: dict[str, Any]) -> None:
            tt = service.ticket(d, tid)
            if tt["column"] != "in_design":
                service.move(self.root, d, tid, "in_design", service.agent_actor(code))
            tt.pop("icd_delta", None)  # the model is generated from the current ICD: nothing to tell anyone
            tt.pop("cr_notes", None)
            if "brief_read" not in tt["milestones"]:
                service.set_milestone(self.root, d, tid, "brief_read", True, service.agent_actor(code))
            _set_run(tt, status="designing", next="design", path="direct", stage_seen=[])
            self.status(d, tt, code, f"{lbl} is building {tt['title']} from the interface spec (no AI)")
        self.edit(prep)
        t0 = time.time()
        res = await self.env.design_direct(project_id, dp["script"], direct.note(dp))
        secs = round(time.time() - t0, 1)

        def after(d: dict[str, Any]) -> str | None:
            tt = service.ticket(d, tid)
            a = service.agent_actor(code)
            if res.get("ok"):
                tt["direct"] = {"path": "direct", "label": direct.LABEL, "kind": dp["kind"], "sha": dp["sha"],
                                "summary": dp["summary"], "material": dp["material"], "features": dp["features"],
                                "icd_version": dp["icd_version"], "version": dp["version"], "seconds": secs,
                                "build_s": res.get("build_s"), "checks_s": res.get("checks_s"), "at": store.now()}
                for m in ("first_build", "gates_pass", "self_review"):
                    if m not in tt["milestones"]:
                        service.set_milestone(self.root, d, tid, m, True, a)
                service.emit(self.root, d, "ticket.direct", f"{lbl} built {service._label(tt)} from the interface "
                             f"spec in {secs:.1f} s (no AI, 0 tokens): {dp['summary']}.", a, tid, seconds=secs)
                if tt.get("taken_over") or tt.get("paused"):
                    return "design"  # _halt records why (a resumed direct build is the same script again)
                if tt.get("inbox") or tt.get("icd_delta") or tt.get("cr_notes"):
                    return "design"  # comments / an ICD change arrived during the build
                service.move(self.root, d, tid, "in_review", a)
                _set_run(tt, status="reviewing", next="review", attempt=0, path="direct")
                self.handoff(d, tt, code, "gage", f"{lbl} → Gage: {tt['title']} built from the interface spec (no "
                             "AI), for inspection.")
                return "review"
            why = res.get("error") or "the build didn't pass its checks"
            tt["direct"] = {"path": "agent", "fallback": True, "at": store.now(), "seeded": False,
                            "reasons": [f"the build from the interface spec didn't pass ({why})"]}
            _set_run(tt, path="agent")
            log.warning("direct build of %s failed: %s", tid, why)
            return "agent"
        return self.edit(after)

    def _progress(self, d: dict[str, Any], tid: str, code: str, lbl: str, ev: dict[str, Any],
                  seen: set[str]) -> None:
        """Milestones and status lines from the agent's real events."""
        tt = service.ticket(d, tid)
        a = service.agent_actor(code)
        typ = ev.get("type")
        if typ in ("text", "tool") and "brief_read" not in tt["milestones"]:
            service.set_milestone(self.root, d, tid, "brief_read", True, a)
        if typ == "tool" and ev.get("name") == "build":
            stage = "rebuild" if "first_build" in tt["milestones"] or "build" in seen else "first_build"
            seen.add("build")
            self.status(d, tt, code, specialists.line(code, stage, tt["title"], lbl))
        elif typ == "tool_result" and ev.get("build"):
            if "first_build" not in tt["milestones"]:
                service.set_milestone(self.root, d, tid, "first_build", True, a)
            if ev.get("is_error") or "FAILED" in str(ev.get("brief") or "").upper():
                self.status(d, tt, code, specialists.line(code, "fixing", tt["title"], lbl))
            else:
                self.status(d, tt, code, specialists.line(code, "checks_pass", tt["title"], lbl))
        elif typ == "review":
            self.status(d, tt, code, specialists.line(code, "self_review", tt["title"], lbl))

    def _capacity(self, tid: str, nxt: str, why: str) -> None:
        self.edit(lambda d: self._capacity_doc(d, service.ticket(d, tid), nxt, why))

    def _capacity_doc(self, d: dict[str, Any], tt: dict[str, Any], nxt: str, why: str) -> None:
        r = run_of(tt)
        o = orch(d)
        if why == "balance":
            open_wait(tt, "capacity")
            o.update(state="stopped", reason="balance")
            _set_run(tt, status="queued", next=nxt, line="Waiting: the workspace is out of tokens")
            service.emit(self.root, d, "budget.stop", "The workspace token balance is too low for another design "
                         "run. Top up, then press Run.", service.agent_actor("archie"))
            return
        open_wait(tt, "capacity")
        n = int(r.get("waits") or 0) + 1
        wait = backoff(n, CAPACITY_BASE_S, CAPACITY_CAP_S)
        until = time.time() + wait
        if why == "rate":
            o["capacity_until"] = max(float(o.get("capacity_until") or 0), until)
        msg = ("Waiting for capacity: the AI service is busy" if why == "rate" else
               "Waiting for capacity: other runs hold the token balance") + f", retrying in {wait:.0f} s"
        _set_run(tt, status="waiting_capacity", next=nxt, waits=n, next_try_at=until, line=msg)
        service.emit(self.root, d, "capacity.wait", f"{service._label(tt)}: {msg[0].lower() + msg[1:]}.",
                     service.agent_actor(tt["specialist"]), tt["id"], seconds=round(wait))
        return

    # ------------------------------------------------------------------ stage: Gage
    async def _review(self, tid: str) -> str | None:
        doc = self.load()
        t = service.ticket(doc, tid)
        self.edit(lambda d: self.status(d, service.ticket(d, tid), "gage",
                                        f"Gage is inspecting {t['title']} against the brief", status="reviewing"))
        if not t.get("project_id"):
            self.edit(lambda d: self._fail(d, tid, "There is no Design Studio part to inspect."))
            return None
        state = await self.env.part_state(t["project_id"])
        use_icd = interfaces.has_icd(doc) and t["item_id"] in doc["skeleton"]["items"]
        findings = gage.deterministic(t, state, sizes=not use_icd)
        icd_res: dict[str, Any] | None = None
        if use_icd and state.get("builds") and state.get("ok") is True:
            icd_res = await self.env.conformance(doc, t)
            if icd_res is not None:
                findings += conformance.findings(icd_res)
        ai: dict[str, Any] | None = None
        hard = bool(findings)  # measurable failures (checks, ICD conformance): only these can block a part
        # a part built from its interfaces, unchanged since and conforming: the AI note has nothing to judge that the
        # measurements don't (the brief asked for nothing beyond the ICD, or it would have gone to the agent)
        built_direct = direct.is_direct(t, state) and icd_res is not None
        if not findings and not built_direct:
            b = budget_state(doc)
            prev = list(run_of(t).get("ai_findings") or [])
            ai = await self.env.review_ai(doc, t, state, None if b["bypass"] else b["remaining"], prev)
            if ai and ai.get("verdict") == "changes":
                findings = list(ai.get("findings") or [])

        def fn(d: dict[str, Any]) -> str | None:
            nonlocal findings
            tt = service.ticket(d, tid)
            g = service.agent_actor("gage")
            tt["review_tokens"] = int(tt.get("review_tokens") or 0) + int((ai or {}).get("tokens") or 0)
            if icd_res is not None:
                tt["icd_check"] = {**icd_res, "at": store.now()}
            r = run_of(tt)
            spec = tt["specialist"]
            sname = roster.agent(spec)["name"]
            parent = next((x for x in d["tickets"] if tid in (x.get("depends_on") or [])), None)
            if tt.get("icd_delta") or (tt.get("inbox") and not findings):
                _set_run(tt, status="designing", next="design")  # the ICD changed (or comments came) meanwhile
                return "design"
            n0 = int(r.get("review_round") or 0) + 1
            settled: list[str] = []
            if findings and not hard and n0 > gage.MAX_SENDBACKS:
                # the AI note is advisory: after the rounds it may take, a part that passes everything measurable
                # is approved and its open findings are recorded for the engineer (CD-030, PD-68)
                settled, findings = findings, []
            if not findings:
                note = "Approved: the latest build passes every gating check and carries the sizes the brief gives."
                if icd_res is not None:
                    n = sum(len(x["rows"]) for x in icd_res["interfaces"])
                    note = (f"Approved: the latest build passes every gating check, and {n} interface feature"
                            f"{'s' if n != 1 else ''} measured on the part match ICD v{icd_res['version']} "
                            f"({len(icd_res['interfaces'])} interface{'s' if len(icd_res['interfaces']) != 1 else ''}"
                            ", inside the envelope).")
                    fr = icd_res.get("frame") or {}
                    if fr and not fr.get("identity"):
                        note += (f" The part is modelled in its own frame ({fr['label']} from the ICD part frame): "
                                 "Gage measured it there and Fitz places it through that frame.")
                if settled:
                    note = (f"Approved by Archie after {n0 - 1} review rounds: every measurable check passes"
                            + (" and the part matches its interfaces" if icd_res is not None else "")
                            + ". Gage's remaining points are advisory and recorded for you here (reopen the ticket "
                            "if one matters):\n" + "\n".join(f"- {f}" for f in settled))
                    tt["review_notes"] = settled
                elif ai and ai.get("note"):
                    note += f" Review note: {ai['note']}"
                elif built_direct:
                    note += (" It was built from the interface spec (no AI), so no AI review note was needed: the "
                             "measurements above are the whole review.")
                elif ai is None:
                    note += " (No AI review note this time: approved on the deterministic checks.)"
                if ai and ai.get("notes") and not settled:
                    note += "\nNotes (not blocking):\n" + "\n".join(f"- {x}" for x in ai["notes"])
                service.comment(self.root, d, tid, note, g)
                tt["comments"][-1]["delivery"] = "stored"
                if gated(d, tt):  # the program's per-part review gate: the engineer approves before assembly
                    _set_run(tt, status="awaiting_review", next=None, agent="gage", feedback=None,
                             line=f"Gage passed {tt['title']}: waiting for your review")
                    open_wait(tt, "blocked")
                    service.emit(self.root, d, "ticket.review_requested", f"{service._label(tt)} passed Gage and waits "
                                 "for your review (approve it, or request changes with a note).", g, tid)
                    return None
                service.move(self.root, d, tid, "approved", g)
                _set_run(tt, status="done", agent="gage", feedback=None, ai_findings=None,
                         line=(f"Approved by Archie with {len(settled)} open review note"
                               f"{'s' if len(settled) != 1 else ''}" if settled else f"Gage approved {tt['title']}"))
                if parent:
                    self.handoff(d, tt, "gage", "fitz", f"Gage → Fitz: {tt['title']} approved for assembly.")
                if (d.get("assembly") or {}).get("status") in ("ready", "building") and \
                        tt["item_id"] in (d.get("skeleton") or {}).get("items", {}):
                    # back to the queue: the review slot frees now and Fitz's one swap step takes it (CD-032)
                    _set_run(tt, status="queued", next="fit", agent="fitz", agent_label="Fitz",
                             line=f"Approved: Fitz swaps {tt['title']} in for its placeholder next")
                    return None
                return None
            n = int(r.get("review_round") or 0) + 1
            service.comment(self.root, d, tid, "Changes requested:\n" + "\n".join(f"- {f}" for f in findings), g)
            tt["comments"][-1]["delivery"] = "stored"
            if n > gage.MAX_SENDBACKS:
                _set_run(tt, review_round=n)
                self._fail(d, tid, f"Gage sent {tt['title']} back {n} times; a measurable check still fails: "
                                   f"{findings[0]} It needs your decision: comment, take over, or approve it yourself.")
                return None
            service.move(self.root, d, tid, "changes_requested", g)
            _set_run(tt, status="designing", next="design", review_round=n, feedback=findings,
                     ai_findings=None if hard else findings,
                     line=f"Gage sent {tt['title']} back: {findings[0]}")
            self.handoff(d, tt, "gage", spec, f"Gage → {sname}: {tt['title']} sent back. {findings[0]}")
            return "design"
        return self.edit(fn)

    # ------------------------------------------------------------------ change requests from a part agent
    async def _change_request(self, tid: str, text: str) -> None:
        from aicad.office import icd as icd_mod

        req = icd_mod.parse_change_request(text)
        if req is None:
            return

        def raise_(d: dict[str, Any]) -> str | None:
            tt = service.ticket(d, tid)
            code = tt["specialist"]
            actor = {**service.agent_actor(code), "name": self.label(tid, code)}
            try:
                c = interfaces.raise_cr(self.root, d, req["interface"], req["values"], req["reason"] or
                                        "The part can't meet the interface as written.", actor, ticket_id=tid)
            except OfficeInputError as e:
                tt.setdefault("cr_notes", []).append(f"Your change request could not be raised: {e} Design to the "
                                                     "ICD as it stands.")
                return None
            self.status(d, tt, code, f"{actor['name']} raised {c['id']} on {req['interface']}: waiting for Archie")
            return str(c["id"])

        cid = self.edit(raise_)
        if cid:
            await self.env.decide_cr(self.root, self.pid, cid)

    # ------------------------------------------------------------------ stage: Fitz swaps the real part in
    async def _fit(self, tid: str) -> str | None:
        self.edit(lambda d: self.status(d, service.ticket(d, tid), "fitz", "Fitz is swapping "
                                        f"{service.ticket(d, tid)['title']} in for its placeholder", status="fitting"))
        res = await self.env.swap_in(self.root, self.pid, tid)

        def fn(d: dict[str, Any]) -> str | None:
            tt = service.ticket(d, tid)
            f = service.agent_actor("fitz")
            if tt.get("icd_delta"):  # a change request changed this part while it was being fitted
                service.move(self.root, d, tid, "in_design", f)
                _set_run(tt, status="designing", next="design", line="The interfaces changed: back to the designer")
                return "design"
            if res.get("error"):  # the part stays a placeholder: try again, never mark it done (CD-035)
                n = int(run_of(tt).get("fit_attempt") or 0) + 1
                if n > MAX_ATTEMPTS + 1:
                    _set_run(tt, fit_attempt=n, next="fit")
                    self._fail(d, tid, f"{res['error']} ({n - 1} tries). Retry it, or rebuild the program assembly.")
                    return None
                _set_run(tt, status="retry", next="fit", fit_attempt=n, agent="fitz",
                         next_try_at=time.time() + backoff(n, RETRY_BASE_S, RETRY_CAP_S),
                         line=f"{res['error']}: Fitz tries again shortly")
                if n == 1:
                    visual_office.on_failure(self.root, d, tt, f"{res['error']}.", retrying=True)
                return None
            if res.get("skipped"):
                _set_run(tt, status="done", next=None, line=res["skipped"], agent="fitz")
                return None
            clashes = (res.get("last") or {}).get("clashes") or []
            if clashes:
                n = int(run_of(tt).get("clash_round") or 0) + 1
                desc = [f"Clash: {c['a_name']} ↔ {c['b_name']}, {float(c['volume_mm3']):.1f} mm³ of overlap"
                        for c in clashes[:6]]
                service.comment(self.root, d, tid, "Fitz found clashes when the part went into the program "
                                "assembly:\n" + "\n".join(f"- {x}" for x in desc), f)
                tt["comments"][-1]["delivery"] = "stored"
                tt["fitted"] = False
                if n > MAX_CLASH_ROUNDS:
                    _set_run(tt, clash_round=n, next=None)
                    self._fail(d, tid, f"{tt['title']} still clashes in the program assembly after {n - 1} rounds: "
                                       + desc[0])
                    return None
                service.move(self.root, d, tid, "changes_requested", f)
                _set_run(tt, status="designing", next="design", clash_round=n, feedback=desc,
                         line=f"Fitz sent {tt['title']} back: {desc[0]}")
                self.handoff(d, tt, "fitz", tt["specialist"], f"Fitz → {roster.agent(tt['specialist'])['name']}: "
                             f"{tt['title']} clashes in the assembly. {desc[0]}")
                return "design"
            tt["fitted"] = True
            checked = bool((res.get("last") or {}).get("checked"))  # "0 clashes" only when it was measured
            cl = "0 clashes" if checked else "its clash check is left to the final assembly"
            _set_run(tt, status="done", next=None, agent="fitz", fit_attempt=0,
                     line=f"Fitz swapped {tt['title']} in: interface mates re-attached, {cl}")
            service.emit(self.root, d, "ticket.fitted", f"Fitz swapped the real {tt['title']} in for its placeholder: "
                         f"every interface mate re-attached by name, {cl}"
                         + (f" ({res['mates']} mates in the program assembly)." if res.get("mates") else "."), f, tid,
                         item=tt["item_id"])
            if res.get("problems"):
                service.comment(self.root, d, tid, "Fitz could not re-attach:\n" + "\n".join(
                    f"- {p}" for p in res["problems"][:6]), f)
                tt["comments"][-1]["delivery"] = "stored"
            return None
        return self.edit(fn)

    # ------------------------------------------------------------------ stage: Fitz
    async def _integrate(self, tid: str) -> str | None:
        doc = self.load()
        t = service.ticket(doc, tid)

        def begin(d: dict[str, Any]) -> None:
            tt = service.ticket(d, tid)
            if tt["column"] != "in_design":
                service.move(self.root, d, tid, "in_design", service.agent_actor("fitz"))
            self.status(d, tt, "fitz", f"Fitz is laying out {t['title'].removeprefix('Assemble ')} on the bench",
                        status="integrating")
        self.edit(begin)
        res = await self.env.integrate(self.root, self.pid, tid)
        look = None
        if not (res.get("blocked") or res.get("error") or res.get("wait_fit")):
            self.edit(lambda d: self.status(d, service.ticket(d, tid), "fitz", f"Fitz is looking at "
                                            f"{t['title'].removeprefix('Assemble ')} before it is signed off"))
            look = await self.env.look_level(self.root, self.pid, tid, res)

        def fn(d: dict[str, Any]) -> None:
            tt = service.ticket(d, tid)
            f = service.agent_actor("fitz")
            if look:
                text, acts = visual_office.level_message(tt, look)
                tt["look"] = {k: look.get(k) for k in ("stop", "line", "image", "unconfirmed", "tokens", "unplaced")}
                if look.get("stop"):
                    self._fail(d, tid, look["reason"], tell=False)
                    if text:
                        archie_chat.post(self.root, self.pid, text, acts, kind="look",
                                         visual={"level": tt["item_id"], "image": look.get("image"),
                                                 "verdict": look.get("verdict"), "quick": look.get("quick"),
                                                 "tokens": look.get("tokens")})
                    return
                if look.get("line"):
                    service.comment(self.root, d, tid, look["line"], service.agent_actor("archie"))
                    tt["comments"][-1]["delivery"] = "stored"
                if text and (look.get("unconfirmed") or look.get("unplaced") or tt["item_id"] == "root"
                             or (look.get("verdict") or {}).get("overall") != "looks_assembled"):
                    archie_chat.post(self.root, self.pid, text, acts, kind="look",
                                     visual={"level": tt["item_id"], "image": look.get("image"),
                                             "verdict": look.get("verdict"), "quick": look.get("quick"),
                                             "tokens": look.get("tokens")})
            if res.get("blocked"):
                self._fail(d, tid, res["blocked"])
                return
            if res.get("error"):
                n = int(run_of(tt).get("attempt") or 0) + 1
                if n > MAX_ATTEMPTS + 1:
                    self._fail(d, tid, f"{res['error']} ({n - 1} tries). Retry it, or rebuild the program assembly.")
                    return
                _set_run(tt, status="retry", next="integrate", attempt=n, agent="fitz",
                         next_try_at=time.time() + backoff(n, RETRY_BASE_S, RETRY_CAP_S),
                         line=f"{res['error']}: Fitz tries again shortly")
                if n == 1:
                    visual_office.on_failure(self.root, d, tt, f"{res['error']}.", retrying=True)
                return
            if res.get("wait_fit"):
                for k in res["wait_fit"]:
                    kt = service.ticket(d, k)
                    if run_of(kt).get("status") not in ACTIVE:
                        _set_run(kt, status="queued", next="fit", agent="fitz", fit_attempt=0,
                                 line=f"Fitz swaps {kt['title']} in for its placeholder next")
                _set_run(tt, status="queued", next="integrate", line=res["why"], agent="fitz")
                return
            if res.get("assembly_id") and tt.get("assembly_id") != res["assembly_id"]:
                tt["assembly_id"] = res["assembly_id"]
            tt["integration"] = {k: res.get(k) for k in ("summary", "clashes", "log", "inserted")}
            lines = [res.get("summary") or "Fitz assembled the parts."]
            lines += [f"- {x['text']}" for x in (res.get("log") or []) if x.get("tone") == "warn"][:8]
            service.comment(self.root, d, tid, "\n".join(lines), f)
            tt["comments"][-1]["delivery"] = "stored"
            clashes = res.get("clashes") or []
            if clashes:
                # advisory (PD-71): every part passed Gage and was placed by its approved interfaces, so a clash is
                # reported on the ticket and the assembly view for the engineer, never a stop
                desc = "; ".join(f"{c.get('a_name') or c['a']} ↔ {c.get('b_name') or c['b']} "
                                 f"{float(c.get('volume_mm3') or 0):.1f} mm³" for c in clashes[:5])
                service.comment(self.root, d, tid, f"Advisory: Fitz found {len(clashes)} clash"
                                f"{'es' if len(clashes) != 1 else ''} to look at in the assembly view: {desc}.", f)
                tt["comments"][-1]["delivery"] = "stored"
                tt["clash_notes"] = [desc]
            changed = [service.ticket(d, k)["title"] for k in res.get("children") or []
                       if service.ticket(d, k)["column"] not in service.DONE_COLUMNS]
            if changed:  # a change request reopened a part while Fitz was integrating: integrate again later
                service.move(self.root, d, tid, "backlog", f)
                _set_run(tt, status="queued", next="integrate", line=f"{changed[0]} changed during integration: "
                         "Fitz integrates again when it is approved")
                return
            for k in res.get("children") or []:
                kt = service.ticket(d, k)
                if kt["column"] == "approved":
                    service.move(self.root, d, k, "integrated", f)
                    if run_of(kt).get("status") == "blocked":  # the engineer approved it by hand: no longer waiting
                        close_wait(kt)
                        _set_run(kt, status="done", blocked=None, line="Approved by the engineer and integrated")
            service.move(self.root, d, tid, "integrated", f)
            if "approved" not in tt["milestones"]:
                tt["milestones"].append("approved")
            tt["progress"] = 100
            _set_run(tt, status="done", line=res.get("summary") or "Integrated", agent="fitz")
            service.emit(self.root, d, "ticket.integrated", f"{service._label(tt)}: {res.get('summary')}", f, tid,
                         assembly_id=tt.get("assembly_id"))
            return
        self.edit(fn)
        return None


    # ------------------------------------------------------------------ stage: Ortho (drawings, CD-014 / DRW-014)
    def _deliverable_begin(self, tid: str, code: str, line: str) -> list[dict[str, Any]]:
        def fn(d: dict[str, Any]) -> list[dict[str, Any]]:
            tt = service.ticket(d, tid)
            if tt["column"] != "in_design":
                service.move(self.root, d, tid, "in_design", service.agent_actor(code))
            self.status(d, tt, code, line, status=STATUS_OF[tt["deliverable"]])
            sc = ecn.scope(d)
            return [{"ticket_id": p["ticket"]["id"], "project_id": p["project_id"], "reused": p["reused"]}
                    for p in deliverables.make_parts(d) if sc is None or p["ticket"]["id"] in sc]
        return self.edit(fn)

    def _deliverable_progress(self, tid: str, code: str, k: int, n: int, line: str) -> None:
        def fn(d: dict[str, Any]) -> None:
            tt = service.ticket(d, tid)
            tt["progress"] = max(int(tt.get("progress") or 0), min(95, int(100 * k / max(1, n))))
            self.status(d, tt, code, line)
        self.edit(fn)

    async def _drawings(self, tid: str) -> str | None:
        parts = self._deliverable_begin(tid, "ortho", "Ortho is laying out the drawing sheets")
        n = len(parts) + 1
        sheets: list[dict[str, Any]] = []
        for k, p in enumerate(parts):
            doc = self.load()
            pt = service.ticket(doc, p["ticket_id"])
            self._deliverable_progress(tid, "ortho", k, n, f"Ortho is dimensioning sheet {k + 1} of {n}: {pt['title']}")
            res = await self.env.drawing(doc, pt, p["project_id"])
            sheets.append({"ticket": pt["id"], "key": pt["key"], "title": pt["title"], "project_id": p["project_id"],
                           **res})
        self._deliverable_progress(tid, "ortho", n - 1, n, f"Ortho is drawing the assembly with its BOM and balloons "
                                                           f"(sheet {n} of {n})")
        asm = await self.env.assembly_drawing(self.root, self.pid)

        def fn(d: dict[str, Any]) -> None:
            tt = service.ticket(d, tid)
            o = service.agent_actor("ortho")
            dv = d.setdefault("deliverables", {})
            sc = ecn.scope(d)
            if sc is not None:  # an ECN: only the changed parts were redrawn, the others' sheets stand
                new = {x["ticket"]: x for x in sheets}
                old = {x["ticket"]: x for x in (dv.get("drawings") or {}).get("sheets") or []}
                order = [p["ticket"]["id"] for p in deliverables.make_parts(d)]
                sheets[:] = [new.get(k) or {**old[k], "kept": True} for k in order if k in new or k in old]
            dv["drawings"] = {"sheets": sheets, "assembly": asm, "at": store.now(),
                              "redrawn": None if sc is None else sorted(sc)}
            bad = [x for x in sheets if not x.get("ok") or not x.get("check_passed")]
            spec = sum(int(x.get("icd_dims") or 0) for x in sheets)
            lines = [f"Ortho drew {len(sheets)} part sheet{'s' if len(sheets) != 1 else ''}"
                     + (f" ({spec} dimension{'s' if spec != 1 else ''} tagged spec from the ICD)" if spec else "")
                     + (" and the assembly drawing with its BOM table and "
                        f"{len(asm.get('balloons') or [])} balloons." if asm.get("ok") else ".")]
            lines += [f"- {x['key']} {x['title']}: {x.get('error') or 'fails its consistency check (CHK-12): ' + '; '.join((x.get('problems') or [])[:2])}"
                      for x in bad]
            if not asm.get("ok"):
                lines.append(f"- Assembly drawing: {asm.get('error') or 'not drawn'}")
            service.comment(self.root, d, tid, "\n".join(lines), o)
            tt["comments"][-1]["delivery"] = "stored"
            drawn = [x for x in sheets if x.get("ok")]
            if not asm.get("ok") or not drawn:
                self._fail(d, tid, "Ortho couldn't finish the drawings: " + (asm.get("error") or "assembly drawing"
                           if not asm.get("ok") else f"{bad[0]['title']}: {bad[0].get('error') or 'not drawn'}")
                           + ". Fix it in Drawing Studio, then retry.")
                return
            if bad:  # CD-039: the set is delivered; sheets needing a touch-up are flagged, never a stop
                tt["sheet_notes"] = [f"{x['key']} {x['title']}" for x in bad]
                lines[0] += (f" {len(bad)} sheet{'s' if len(bad) != 1 else ''} need a touch-up in Drawing Studio: "
                             + ", ".join(tt["sheet_notes"][:4]) + ".")
            service.move(self.root, d, tid, "approved", o)
            _set_run(tt, status="done", line=lines[0], agent="ortho")
            service.emit(self.root, d, "deliverable.done", lines[0], o, tid, deliverable="drawings")
        self.edit(fn)
        return None

    # ------------------------------------------------------------------ stage: Smithy (manufacturing review)
    async def _dfm(self, tid: str) -> str | None:
        parts = self._deliverable_begin(tid, "smithy", "Smithy is banking the forge for the manufacturing review")
        n = len(parts)
        lines: list[dict[str, Any]] = []
        for k, p in enumerate(parts):
            doc = self.load()
            pt = service.ticket(doc, p["ticket_id"])
            self._deliverable_progress(tid, "smithy", k, n, f"Smithy is checking {pt['title']} for manufacture "
                                                            f"({k + 1} of {n})")
            res = await self.env.dfm(doc, pt, p["project_id"])
            lines.append(deliverables.dfm_part(pt, res.get("analysis"), res.get("error")))
        sc = ecn.scope(self.load())
        if sc is not None:  # an ECN: only the changed parts were screened again, the others' lines stand
            doc = self.load()
            new = {x["ticket"]: x for x in lines}
            old = {x["ticket"]: x for x in ((doc.get("deliverables") or {}).get("dfm") or {}).get("parts") or []}
            order = [p["ticket"]["id"] for p in deliverables.make_parts(doc)]
            lines = [new.get(k) or {**old[k], "kept": True} for k in order if k in new or k in old]
        summ = deliverables.dfm_summary(lines)

        def fn(d: dict[str, Any]) -> None:
            tt = service.ticket(d, tid)
            s_ = service.agent_actor("smithy")
            d.setdefault("deliverables", {})["dfm"] = {**summ, "at": store.now()}
            head = (f"Smithy screened {summ['analysed'] if sc is None else len(parts)} of {n} part{'s' if n != 1 else ''}: {summ['critical']} "
                    f"critical and {summ['warning']} warning flag{'s' if summ['warning'] != 1 else ''} (advisory).")
            body = []
            for x in summ["parts"]:
                if not x.get("ok"):
                    body.append(f"- {x['key']} {x['title']}: {x.get('error')}")
                    continue
                top = (x.get("findings") or [{}])[0]
                body.append(f"- {x['key']} {x['title']}: {x.get('process_name')}"
                            + (f", relative cost {x['relative_cost']:g}×" if x.get("relative_cost") else "")
                            + (f"; {top.get('rule')} {top.get('title')}" if top else ""))
            service.comment(self.root, d, tid, "\n".join([head, *body[:12]]), s_)
            tt["comments"][-1]["delivery"] = "stored"
            if not summ["analysed"] and n:
                self._fail(d, tid, "Smithy couldn't analyse any part. Open them in the Manufacturing Advisor.")
                return
            service.move(self.root, d, tid, "approved", s_)
            _set_run(tt, status="done", line=head, agent="smithy")
            service.emit(self.root, d, "deliverable.done", head, s_, tid, deliverable="dfm")
        self.edit(fn)
        return None


def _mins(m: float) -> str:
    return f"{m * 60:.0f} s" if m < 1 else f"{m:.1f} min"


# ============================================================================ registry
_runners: dict[str, Runner] = {}


def runner(pid: str) -> Runner | None:
    """The program's live runner in this process. Callable from the event loop or a worker thread (sync routes)."""
    r = _runners.get(pid)
    if r is None:
        return None
    try:
        cur: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:  # a sync route's worker thread
        cur = None
    stale = r.loop.is_closed() or (cur is not None and cur is not r.loop)
    if stale or (r.main is not None and r.main.done() and not r.tasks):
        _runners.pop(pid, None)
        return None
    return r


def _wake(r: Runner) -> None:
    try:
        r.loop.call_soon_threadsafe(r.wake.set)
    except RuntimeError:  # loop closed
        pass


def ensure(root: Path, pid: str) -> Runner:
    """Start the program's runner if it is not running in this process (idempotent)."""
    r = runner(pid)
    if r is not None:
        r.wake.set()
        if r.main is None or r.main.done():
            r.main = asyncio.create_task(r.run())
        return r
    doc = store.load(root, pid)
    if doc is None:
        raise OfficeInputError("Program not found")
    r = Runner(root, pid, make_env(root, doc))
    _runners[pid] = r
    r.main = asyncio.create_task(r.run())
    return r


def poke(pid: str) -> None:
    r = runner(pid)
    if r is not None:
        _wake(r)


async def interrupt(pid: str, tid: str) -> None:
    r = runner(pid)
    if r is None:
        return
    doc = store.load(r.root, pid)
    t = next((x for x in (doc or {}).get("tickets", []) if x["id"] == tid), None)
    if t and t.get("project_id"):
        await r.env.interrupt(t["project_id"])
    r.wake.set()


def resume_all(data_dir: Path) -> int:
    """At startup: every program that was running when the server stopped starts again."""
    base = data_dir / "office"
    n = 0
    if not base.is_dir():
        return 0
    for org in base.iterdir():
        if not org.is_dir():
            continue
        for doc in store.list_docs(org.resolve()):
            if (doc.get("orchestrator") or {}).get("state") == "running":
                try:
                    ensure(org.resolve(), doc["id"])
                    n += 1
                except Exception:
                    log.exception("could not resume program %s", doc.get("id"))
    return n


async def shutdown() -> None:
    rs = list(_runners.values())
    _runners.clear()
    for r in rs:
        for t in [*r.tasks.values(), *([r.main] if r.main else [])]:
            t.cancel()
    for r in rs:
        for t in [*r.tasks.values(), *([r.main] if r.main else [])]:
            with contextlib.suppress(BaseException):  # cancelled on shutdown
                await t


def forget(pid: str) -> None:
    """Stop a program's runner and its work (the program is being deleted)."""
    r = _runners.pop(pid, None)
    if r is not None:
        for t in [*r.tasks.values(), *([r.main] if r.main else [])]:
            t.cancel()
