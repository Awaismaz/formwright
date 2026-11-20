"""Archie supervises a running program (WORKLIST 49, founder 2026-11-20).

"Archie must have super powers over the whole Design program, just like you solve problems from here when I tell
you": he watches every ticket and gate, diagnoses what is stuck or failing, and acts through typed, audited tools.

* **Watch** (event driven, plus a heartbeat): a ticket becomes blocked, fails the same way twice (the same block after
  Archie acted), Gage's rounds stop moving the measurement (the no-progress guard), the interfaces gate stays blocked,
  a working ticket shows no progress for ``STUCK_MIN`` minutes, the budget is near its limit, or a visual check says
  "looks wrong". The orchestrator records triggers on the program (``notify``) and kicks a pass (``tick``); a
  heartbeat (``HEARTBEAT_S``) also scans programs that have no runner. Passes are debounced (``DEBOUNCE_S``) and never
  two at once on one program (``_locks``).
* **Diagnose before acting**: Archie (the ``supervisor`` model role, Opus) gets a compact view of the program (run
  records, Gage's findings and how they changed, ICD issues, change requests, visual verdicts, budget) and answers
  with a cause (part, measurement, spec, rule, plan, interfaces, budget, capacity) and typed actions in a fenced
  ``fw-supervisor`` block. Without AI (simulated agents, no tokens, the hourly cap reached) a deterministic reading
  of the known patterns gives the same structure (``rule_plan``). He never runs code.
* **Act** through typed tools that reuse the office's own service functions (``check`` validates against the program
  as it is now, ``execute`` applies). **Minor** actions he does himself and says so in the program chat; **major**
  ones are asked first with clickable choices. The split is deterministic code (``classify``, PD-98), never the
  model's judgement.
* **Rule overrides**: a relaxed check is one named rule, scoped to one ticket, interface or the program, with a
  fair-judgement reason and an expiry (a number of rounds, or until the next rebuild). The gate code honours it
  (``split`` / ``consume`` in Gage's review, ``cap_extra`` for round caps, ``relaxed_clash`` in Fitz's swap-in) and
  records it as "relaxed by Archie: <reason>", never as passed; it stays visible on the ticket, in the BOM and in the
  release README.
* **Log with undo**: every action is in ``doc["supervisor"]["log"]`` (when, what, why, evidence, outcome) and shown
  on the program's Archie tab; ``undo`` reverses what can be reversed (rule overrides, plan edits not yet built,
  budget changes, reassignments, keep-separate decisions at a draft gate).

Hard limits: no fake pass, no manufacturing claim, never past the user's wallet, never another workspace (every tool
resolves names inside this program, and the program's folder must belong to its organisation), at most
``MAX_CALLS_PER_HOUR`` model calls per program per hour (PD-99).
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from aicad.office import OfficeInputError, archie_chat, roster, service, store

log = logging.getLogger("aicad.office.supervisor")

ENV = "FW_OFFICE_SUPERVISOR"            # "0" turns the supervisor off (tests do, unless a test opts in)
LIVE_ENV = "FW_OFFICE_SUPERVISOR_LIVE"  # development: Archie's supervisor calls stay live while agents are simulated
MODEL = "claude-opus-5-5"               # the orchestration tier (PD-82); FW_LLM_MODELS may route the role elsewhere
MAX_CALLS_PER_HOUR = 6                  # model calls per program per hour (PD-99)
CALL_MAX_TOKENS = 30                    # hard cap (platform tokens) for one supervisor call
CALL_MIN_TOKENS = 5                     # less than this left in the wallet: the rule-based reading answers
HEARTBEAT_S = 120.0                     # a pass that only looks (no model call unless it finds something new)
DEBOUNCE_S = 2.0                        # triggers that arrive together make one pass
STUCK_MIN = 20.0                        # a working ticket with no update for this long is stuck
GATE_STALE_MIN = 30.0                   # the interfaces gate blocked with problems for this long
BUDGET_NEAR = 0.9                       # share of the program budget that counts as "near its limit"
MAX_ACTIONS = 4                         # actions per pass
LOG_MAX = 300
PENDING_MAX = 40

CAUSES = ("part", "measurement", "spec", "rule", "plan", "interfaces", "budget", "capacity", "none")
CAUSE_LABEL = {"part": "the part", "measurement": "the measurement", "spec": "the specification",
               "rule": "a procedural rule", "plan": "the plan", "interfaces": "the interfaces",
               "budget": "the budget", "capacity": "capacity", "none": "nothing"}

# The rules Archie may relax. ``measures``: the rule measures geometry (relaxing it is a major change, PD-98).
# ``extra``: for a cap, the extra rounds a relaxation gives by default. Gating build checks (CHK-02..09: a valid,
# closed solid that exports) are never relaxed.
RULES: dict[str, dict[str, Any]] = {
    "review_rounds": {"label": "the review-round cap", "what": "Gage sends a part back at most 2 times",
                      "measures": False, "extra": 2, "next": "review"},
    "no_progress": {"label": "the no-progress guard", "what": "a redesign that doesn't move the measurement stops "
                    "the part", "measures": False, "extra": 1, "next": "review"},
    "design_attempts": {"label": "the design retry cap", "what": "design runs without a passing build are retried "
                        "2 times", "measures": False, "extra": 2, "next": "design"},
    "clash_rounds": {"label": "the clash send-back cap", "what": "Fitz sends a clashing part back at most 2 times",
                     "measures": False, "extra": 2, "next": "fit"},
    "conformance": {"label": "the ICD conformance check", "what": "an interface feature measured on the part",
                    "measures": True, "next": "review"},
    "envelope": {"label": "the ICD envelope check", "what": "the part stays inside its frozen envelope",
                 "measures": True, "next": "review"},
    "brief_size": {"label": "the brief size check", "what": "a size the ticket's brief states is in the model",
                   "measures": True, "next": "review"},
    "clash": {"label": "the swap-in clash check", "what": "no clash when the part goes into the program assembly",
              "measures": True, "next": "fit"},
}


def feature_text(key: Any) -> str:
    """A feature key as people read it: "IF-01:hole 1" -> "hole 1 of IF-01"."""
    k = str(key or "")
    if k == "envelope":
        return "the envelope"
    if k == "frame":
        return "the part frame"
    if ":" in k:
        iface, feat = k.split(":", 1)
        return f"{feat} of {iface}"
    return k
NEVER_RELAXED = ("The gating build checks (a valid, closed solid that exports) are never relaxed: a part that fails "
                 "them is not a part.")

MINOR_TOOLS = frozenset({"retry", "pause", "reassign", "send_back", "approve_with_notes"})
TOOLS = ("retry", "pause", "reassign", "send_back", "approve_with_notes", "relax_rule", "keep_separate",
         "remove_part", "add_part", "set_qty", "resize_part", "edit_part", "change_interface", "budget",
         "revise_program")
PLAN_TOOLS = frozenset({"remove_part", "add_part", "set_qty"})
_PLACEMENT = re.compile(r"touches nothing|touch nothing|floating|not assembled|in a row|no interface places|"
                        r"apart from|lie apart|on the floor", re.IGNORECASE)
_STANDALONE = re.compile(r"\b(kit|separate(?:ly)?|on (?:their|its) own|stand-?alone|loose|spares?|individual(?:ly)?|"
                         r"not assembled|no assembly)\b", re.IGNORECASE)

SUPERVISOR_INSTRUCTIONS = """You are Archie, the Chief Designer, supervising a mechanical design program while it \
runs. Designers (Mill, Chuck, Axel, Benny, Molly) model the parts, Gage checks them (measurements decide), Fitz \
assembles. Something needs attention: see Triggers. Diagnose first, then act.

Diagnose like a senior engineer, from the evidence given: blocked reasons, Gage's findings and how they changed over \
the rounds, the interfaces (ICD) and their issues, change requests, visual verdicts, the budget. Decide what is at fault:
- part: the designer's model is wrong; another round with a precise instruction can fix it;
- measurement: the part looks right but the check reads it wrong (the same measured value after a redesign is the tell);
- spec: the interface or the brief asks for something this part can't have;
- rule: a procedural limit (a round cap, a retry cap) stops work that is otherwise fine;
- plan: a part is missing, not asked for, or wrongly sized;
- interfaces: a number shared between parts is wrong;
- budget or capacity.
Act only through the tools below, the smallest action that unblocks honest work. Relaxing a check records it as \
relaxed, never as passed. Relax a check that measures geometry (conformance, envelope, brief_size, clash) only when \
the evidence shows the measurement or the spec is at fault, scoped to one feature of one part, with an expiry. A \
clash with a part that is still a placeholder (an envelope made from the interfaces, not the part) is a measurement \
artefact: retry the built part (Fitz swaps it in again unchanged), never send it back to be redesigned. Never \
claim a part is fit for manufacture. Put every change you recommend in "actions", major ones too (an interface change, a part added or removed, a bigger budget, a relaxed geometry check): the office asks the engineer for those with clickable choices before anything happens. A change you only describe in words can't be approved with one click.

Answer with one or two plain sentences, then exactly one fenced block:
```fw-supervisor
{"cause": "part|measurement|spec|rule|plan|interfaces|budget|capacity|none",
 "diagnosis": "what is wrong and why, at most three sentences",
 "evidence": ["short facts from the state below"],
 "say": "what you tell the engineer, plain engineering words",
 "actions": [{"tool": "...", "why": "the fair-judgement reason", ...}]}
```
Tools (ticket keys, interface ids and feature keys exactly as listed):
- {"tool": "retry", "ticket": "KEY"}: put a blocked ticket back to work as it is.
- {"tool": "pause", "ticket": "KEY"}
- {"tool": "reassign", "ticket": "KEY", "to": "mill|chuck|axel|benny|molly"}: Mill machined, Chuck turned, Axel gears, Benny sheet metal, Molly plastic; reassign only to the designer whose family fits the part.
- {"tool": "send_back", "ticket": "KEY", "instruction": "a precise instruction for the designer"}
- {"tool": "approve_with_notes", "ticket": "KEY"}: only when every measurable check passes and only advisory \
review notes remain.
- {"tool": "relax_rule", "rule": "CODE", "ticket": "KEY" (or "interface": "IF-n", or "scope": "program" for a \
procedural rule), "feature": "feature key (optional, conformance)", "expiry": "rebuild" or a number of rounds 1-5}
- {"tool": "keep_separate", "parts": ["part name"]}: parts with no interface that are meant to be on their own.
- {"tool": "remove_part", "part": "part name"} / {"tool": "add_part", "sub": "sub-assembly", "part": {"name": "...", \
"family": "machined|turned|sheet|plastic|gear", "qty": 1, "description": "..."}}: before part work starts.
- {"tool": "set_qty", "part": "part name", "qty": integer}: before part work starts (e.g. two bearings per shaft).
- {"tool": "resize_part", "part": "part name", "size": {"L": 120}}: before the interfaces are approved.
- {"tool": "edit_part", "ticket": "KEY", "description": "the requirement to add to the part's brief"}
- {"tool": "change_interface", "interface": "IF-n", "values": {"field": number}}
- {"tool": "budget", "tokens": integer, "concurrency": integer}: never above what the wallet allows.
- {"tool": "revise_program", "changes": [change, ...]}: revise the program at any stage, also after parts are \
approved or integrated: the layout and the interfaces are derived again (ICD v+1), parts whose interface features \
change are reopened with a precise instruction, kept parts are re-placed, the assemblies that hold a change run \
again. Use it when a measured placement problem (a part or a copy floating, parts in a row, a copy with no \
interface) comes from the layout or the plan, or to add, remove or re-size parts after work started. Changes: \
{"op": "base", "part": "name"} (the part everything else is carried by), {"op": "mount", "part": "name", "on": \
"name"} (every copy of the part sits on its own copy of the host when the counts match), {"op": "size", "part": \
"name", "envelope": [L, W, H]} (mm; a part that stands upright has its long side as H), {"op": "qty", "part": "name", \
"qty": n}, {"op": "add", "sub": "sub-assembly", "part": {"name", "family", "qty", "description", "envelope", \
"mounts_on"}}, {"op": "remove", "part": "name"}, {"op": "describe", "part": "name", "description": "..."}, \
{"op": "relayout"} (only lay it out again). The office computes what it keeps, re-places, redesigns, adds and \
removes, and asks the engineer with that list.
Only the engineer's original brief (Brief in the state) is a requirement. The plan, part split, planned sizes, \
hosts, layout and draft interfaces are your own working assumptions: change them freely when a check fails, as long \
as the whole product still meets the brief; "safe" means "within the brief", not "close to the current plan". When \
the brief itself can't work mechanically, say so in "say" (the engineer amends it in the chat). Prefer revising \
this program to starting a new one. Use an empty list when nothing should be done, \
and say why. At most three actions. Never mention files, code, models, prompts or how you work inside."""

_BLOCK = re.compile(r"```fw-supervisor\s*\n(.*?)\n?```", re.DOTALL)


# ============================================================================ state on the program
def enabled() -> bool:
    return os.environ.get(ENV, "1").strip().lower() not in ("0", "false", "no", "off")


def sup(doc: dict[str, Any]) -> dict[str, Any]:
    s = doc.setdefault("supervisor", {})
    for k, v in (("log", []), ("overrides", []), ("calls", []), ("pending", []), ("handled", {}), ("seq", 0),
                 ("oseq", 0)):
        s.setdefault(k, v)
    return s


def _sig(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def _same_org(root: Path, doc: dict[str, Any]) -> bool:
    """Archie can't act on another workspace: the program must live in its own organisation's folder."""
    return Path(root).name == str(doc.get("org_id") or "")


_flags: dict[str, float] = {}


def notify(doc: dict[str, Any], kind: str, t: dict[str, Any] | None = None, text: str = "") -> None:
    """Record a trigger on the program (called inside the orchestrator's program edits; no I/O of its own)."""
    if not enabled():
        return
    s = sup(doc)
    s["pending"] = (s["pending"] + [{"kind": kind, "ticket": t["id"] if t else None, "text": str(text or "")[:600],
                                     "at": round(time.time(), 3)}])[-PENDING_MAX:]
    _flags[doc["id"]] = time.time()


# ============================================================================ rule overrides (honoured by the gates)
def _ticket_scope(o: dict[str, Any], doc: dict[str, Any], t: dict[str, Any]) -> bool:
    sc = o.get("scope") or {}
    kind = sc.get("kind")
    if kind == "program":
        return True
    if kind == "ticket":
        return sc.get("ticket") == t["id"]
    if kind == "interface":
        ic = doc.get("icd") or {}
        f = next((x for x in ic.get("interfaces") or [] if x["id"] == sc.get("interface")), None)
        return f is not None and t.get("item_id") in (f["a"]["item"], f["b"]["item"])
    return False


def active(doc: dict[str, Any], t: dict[str, Any], rule: str) -> list[dict[str, Any]]:
    """Active overrides of ``rule`` that cover ticket ``t``."""
    out = []
    for o in (doc.get("supervisor") or {}).get("overrides") or []:
        if o.get("status") == "active" and o.get("rule") == rule and _ticket_scope(o, doc, t):
            out.append(o)
    return out


def _expired_by_rebuild(o: dict[str, Any], t: dict[str, Any], builds: Any) -> bool:
    if (o.get("expiry") or {}).get("kind") != "rebuild" or not isinstance(builds, int):
        return False
    seen = (o.get("builds") or {}).get(t["id"])
    return seen is not None and builds != seen


def _feature_match(o: dict[str, Any], item: dict[str, Any]) -> bool:
    if o["rule"] != item.get("rule"):
        return False
    want = o.get("feature")
    if not want:
        return True
    key = str(item.get("key") or "")
    return key == want or (":" in want and key.lower() == want.lower())


def split(doc: dict[str, Any], t: dict[str, Any], items: list[dict[str, Any]], builds: Any = None
          ) -> tuple[list[str], list[dict[str, Any]]]:
    """Gage's measurable findings ``items`` ({rule, key, text}) split into (still blocking texts, relaxed items).
    Read-only: ``consume`` records the use once the review decides."""
    keep: list[str] = []
    relaxed: list[dict[str, Any]] = []
    for it in items:
        rule = it.get("rule")
        if rule not in RULES or not RULES[rule]["measures"]:
            keep.append(it["text"])
            continue
        o = next((x for x in active(doc, t, rule) if _feature_match(x, it) and not _expired_by_rebuild(x, t, builds)),
                 None)
        if o is None:
            keep.append(it["text"])
        else:
            relaxed.append({**it, "override": o["id"], "reason": o["reason"], "label": RULES[rule]["label"]})
    return keep, relaxed


def consume(root: Path, doc: dict[str, Any], t: dict[str, Any], relaxed: list[dict[str, Any]], builds: Any = None
            ) -> list[dict[str, Any]]:
    """Record that the gate used these relaxations on ``t`` (the ticket shows them, the expiry counts down). Called on
    every review: a part-scoped relaxation "until the next rebuild" ends here once the part was rebuilt."""
    if isinstance(builds, int):
        for o in (doc.get("supervisor") or {}).get("overrides") or []:
            if o.get("status") == "active" and (o.get("scope") or {}).get("kind") == "ticket"                     and _ticket_scope(o, doc, t) and _expired_by_rebuild(o, t, builds):
                o["status"] = "expired"
                o["ended"] = {"at": store.now(), "why": "the part was rebuilt"}
    out = []
    used: set[str] = set()
    for r in relaxed:
        o = next((x for x in sup(doc)["overrides"] if x["id"] == r["override"] and x.get("status") == "active"), None)
        if o is None:
            continue
        if isinstance(builds, int):
            o.setdefault("builds", {}).setdefault(t["id"], builds)
        if o["id"] not in used:
            used.add(o["id"])
            o.setdefault("uses", []).append({"ticket": t["id"], "at": store.now()})
            ex = o.get("expiry") or {}
            if ex.get("kind") == "rounds":
                ex["left"] = int(ex.get("left", ex.get("n", 1))) - 1
                if ex["left"] <= 0:
                    o["status"] = "expired"
                    o["ended"] = {"at": store.now(), "why": "its rounds are used up"}
        entry = {"rule": r["rule"], "label": r["label"], "feature": r.get("key"),
                 "feature_text": feature_text(r.get("key")) if r.get("key") else None, "text": r["text"],
                 "reason": r["reason"], "override": r["override"], "at": store.now(), "by": "Archie",
                 "approved_by": o.get("approved_by")}
        t["relaxed"] = [x for x in t.get("relaxed") or [] if not (x["override"] == entry["override"]
                                                                   and x.get("feature") == entry["feature"])]
        t["relaxed"].append(entry)
        out.append(entry)
    return out


def cap_extra(doc: dict[str, Any], t: dict[str, Any], rule: str) -> int:
    """Extra rounds an active relaxation of a procedural cap gives this ticket (0 when none)."""
    return max((int(o.get("extra") or RULES[rule].get("extra") or 1) for o in active(doc, t, rule)), default=0)


def use_rule(doc: dict[str, Any], t: dict[str, Any], rule: str) -> dict[str, Any] | None:
    """A one-shot procedural relaxation (the no-progress guard): the override if active (its rounds count down)."""
    o = next(iter(active(doc, t, rule)), None)
    if o is None:
        return None
    ex = o.get("expiry") or {}
    o.setdefault("uses", []).append({"ticket": t["id"], "at": store.now()})
    if ex.get("kind") == "rounds":
        ex["left"] = int(ex.get("left", ex.get("n", 1))) - 1
        if ex["left"] <= 0:
            o["status"] = "expired"
            o["ended"] = {"at": store.now(), "why": "its rounds are used up"}
    return o


def relaxed_clash(doc: dict[str, Any], t: dict[str, Any]) -> dict[str, Any] | None:
    """An active relaxation of the swap-in clash check for this ticket (Fitz records it, never as 0 clashes)."""
    return next(iter(active(doc, t, "clash")), None)


def relaxed_summary(doc: dict[str, Any]) -> list[str]:
    """Every check relaxed on a part of this program, one line each (final summary, BOM, release README)."""
    out = []
    for t in doc.get("tickets") or []:
        for r in t.get("relaxed") or []:
            what = r["label"] + (f" for {feature_text(r['feature'])}" if r.get("feature") else "")
            tail = " (the relaxation was undone after integration; not measured again)" if r.get("undone") else ""
            out.append(f"{t['key']} {t['title']}: {what} relaxed by Archie, not passed{tail}: {r['reason']}")
    return out


# ============================================================================ watching
def detect(doc: dict[str, Any], now: float | None = None) -> list[dict[str, Any]]:
    """What needs Archie now, read from the program alone (deterministic, no AI). Each trigger has a signature so a
    situation is handled once, not on every heartbeat."""
    from aicad.office import interfaces, orchestrator, scope

    now = time.time() if now is None else now
    out: list[dict[str, Any]] = []
    st = doc.get("status")
    if st == "active":
        for t in doc["tickets"]:
            r = t.get("run") or {}
            if r.get("status") == "blocked" and not t.get("taken_over"):
                why = str(r.get("blocked") or r.get("line") or "")
                out.append({"kind": "blocked", "ticket": t["id"], "text": why, "sig": _sig("blocked", t["id"], why)})
            elif r.get("status") in orchestrator.ACTIVE and t.get("updated_at"):
                age = (now - _ts(t["updated_at"])) / 60.0
                if age >= STUCK_MIN:
                    out.append({"kind": "stuck", "ticket": t["id"], "text": f"no progress for {age:.0f} min",
                                "sig": _sig("stuck", t["id"], t["updated_at"])})
        b = orchestrator.budget_state(doc)
        left_work = any(t["column"] not in service.DONE_COLUMNS for t in doc["tickets"] if t["kind"] != "deliverable")
        if b["tokens"] and not b["bypass"] and b["pct"] >= 100 * BUDGET_NEAR and left_work:
            out.append({"kind": "budget", "ticket": None, "text": f"{b['spent']} of {b['tokens']} tokens used",
                        "sig": _sig("budget", b["tokens"])})
        ic = doc.get("icd") or {}
        if ic.get("status") == "draft" and ic.get("problems") and service.gate(doc, "icd")["status"] == "pending":
            since = max([_ts(h.get("at")) for h in ic.get("history") or []] + [_ts(doc.get("updated_at"))])
            if (now - since) / 60.0 >= GATE_STALE_MIN:
                out.append({"kind": "gate", "ticket": None, "text": ic["problems"][0],
                            "sig": _sig("gate", ic.get("version"), len(ic["problems"]),
                                        len(interfaces.unconnected(doc)))})
    if st in ("plan_review", "active") and doc.get("plan") and (st == "plan_review" or archie_chat.can_revise(doc)):
        _named, excluded = scope.mentions(doc.get("brief") or "")
        for sub in doc["plan"].get("subassemblies") or []:
            for p in sub.get("parts") or []:
                k = scope.kind_of(p["name"])
                if k and k in excluded:
                    out.append({"kind": "scope", "ticket": None, "part": p["name"], "text":
                                f"{p['name']} is planned, but the brief excludes a {k}", "sig": _sig("scope", p["name"])})
    return out


def _ts(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    if not v:
        return 0.0
    from datetime import datetime

    try:
        return datetime.fromisoformat(str(v)).timestamp()
    except ValueError:
        return 0.0


def take_triggers(root: Path, pid: str, now: float | None = None, force: bool = False) -> list[dict[str, Any]]:
    """The pending triggers plus what ``detect`` sees, minus what was handled already; marks them handled. A block
    with the same reason after Archie acted becomes a ``repeat`` (fails the same way twice: he escalates)."""
    with store.lock(pid):
        doc = store.load(root, pid)
        if doc is None:
            return []
        s = sup(doc)
        pend, s["pending"] = s["pending"], []
        seen = s["handled"]
        out: list[dict[str, Any]] = []
        for p in pend:
            t = next((x for x in doc["tickets"] if x["id"] == p.get("ticket")), None)
            if p["kind"] == "blocked" and t is not None:
                why = str((t.get("run") or {}).get("blocked") or p.get("text") or "")
                sig = _sig("blocked", t["id"], why)
                n = int(seen.get(sig, {}).get("n", 0)) if isinstance(seen.get(sig), dict) else 0
                if n >= 2 and not force:
                    continue
                out.append({"kind": "repeat" if n >= 1 else "blocked", "ticket": t["id"], "text": why, "sig": sig})
            else:
                sig = _sig(p["kind"], p.get("ticket"), p.get("text"), p.get("at") if p.get("asked") else "")
                if sig in seen and not force:
                    continue
                out.append({**p, "sig": sig})
        for d in detect(doc, now):
            if (d["sig"] in seen and not force) or any(x["sig"] == d["sig"] for x in out):
                continue
            out.append(d)
        for x in out:
            prev = seen.get(x["sig"])
            seen[x["sig"]] = {"n": (int(prev.get("n", 0)) if isinstance(prev, dict) else 0) + 1, "at": store.now()}
        if len(seen) > 500:
            for k in sorted(seen, key=lambda k: str(seen[k].get("at") if isinstance(seen[k], dict) else ""))[:100]:
                seen.pop(k, None)
        if pend or out:  # a heartbeat that finds nothing writes nothing (the program's "last changed" stays true)
            store.save(root, doc)
        return out


# ============================================================================ the compact view Archie reads
def _feature_keys(t: dict[str, Any]) -> list[str]:
    r = t.get("run") or {}
    keys = [str(x.get("key")) for x in r.get("last_items") or [] if x.get("key")]
    ic = t.get("icd_check") or {}
    for f in ic.get("interfaces") or []:
        for row in f.get("rows") or []:
            if not row.get("ok"):
                k = f"{f['interface']}:{row['feature']}"
                if k not in keys:
                    keys.append(k)
    if ic and not (ic.get("envelope") or {}).get("ok", True) and "envelope" not in keys:
        keys.append("envelope")
    return keys


def state_view(doc: dict[str, Any], triggers: list[dict[str, Any]], facts: dict[str, dict[str, Any]],
               wallet: int | None) -> str:
    from aicad.office import orchestrator

    o = doc.get("orchestrator") or {}
    ic = doc.get("icd") or {}
    b = orchestrator.budget_state(doc)
    lines = [f"Program: {doc['name']} ({doc['key']}), stage {doc['status']}, office {o.get('state', 'idle')}"
             + (f", ICD v{ic.get('version')} {ic.get('status')}" if ic else ""),
             f"Brief: {' '.join(str(doc.get('brief') or '').split())[:900]}",
             f"Budget: {b['spent']} of {b['tokens']} tokens ({b['pct']:g} %)" + (", God-mode bypass" if b["bypass"] else "")
             + (f"; wallet left {wallet}" if wallet is not None else "; wallet unlimited")]
    by = {t["id"]: t for t in doc.get("tickets") or []}
    lines.append("Triggers:")
    for x in triggers:
        t = by.get(x.get("ticket") or "")
        lines.append(f"- {x['kind']}" + (f" {t['key']} {t['title']}" if t else "")
                     + (f" ({x.get('part')})" if x.get("part") else "") + f": {str(x.get('text') or '')[:400]}")
    focus = {x.get("ticket") for x in triggers if x.get("ticket")}
    if doc.get("tickets"):
        lines.append("Tickets (key, title, kind, family, designer, column, status):")
        for t in doc["tickets"][:60]:
            r = t.get("run") or {}
            f = facts.get(t["id"]) or {}
            row = (f"- {t['key']} {t['title']} [{t['kind']}, {t.get('family')}, "
                   f"{roster.agent(t['specialist'])['name']}] {t['column']}, {r.get('status') or 'not started'}")
            if t["id"] in focus or r.get("status") == "blocked":
                row += (f"; review rounds {int(r.get('review_round') or 0)}, design turns {int(r.get('turns') or 0)}, "
                        f"attempts {int(r.get('attempt') or 0)}")
                if f:
                    row += f"; latest build: {'passes its gating checks' if f.get('ok') else 'fails' if f.get('builds') else 'none'} ({f.get('builds', 0)} builds)"
                if r.get("blocked"):
                    row += f"\n    blocked: {str(r['blocked'])[:400]}"
                ph = _placeholder_clash(doc, t) if t["kind"] == "part" and r.get("clash_round") else None
                if ph:
                    row += ("\n    every clash is with the placeholder of " + ", ".join(ph) + " (not built yet: an "
                            "envelope, not the part)")
                if r.get("last_findings"):
                    row += "\n    Gage's measurable findings (latest): " + " | ".join(str(x)[:220] for x in r["last_findings"][:4])
                keys = _feature_keys(t)
                if keys:
                    row += "\n    feature keys: " + ", ".join(keys[:8])
                if r.get("ai_findings"):
                    row += "\n    advisory review points: " + " | ".join(str(x)[:200] for x in r["ai_findings"][:4])
                gc = [c["text"] for c in t.get("comments") or [] if (c.get("by") or {}).get("code") == "gage"][-3:]
                if gc:
                    row += "\n    Gage's last reviews: " + " || ".join(" ".join(c.split())[:260] for c in gc)
                if t.get("relaxed"):
                    row += "\n    relaxed: " + "; ".join(f"{x['label']} {x.get('feature') or ''}" for x in t["relaxed"])
                if t.get("look"):
                    row += f"\n    visual: {(t['look'] or {}).get('line') or ''}"[:300]
            lines.append(row)
    if ic.get("problems"):
        lines.append("Interface problems blocking the gate:\n" + "\n".join(f"- {p}" for p in ic["problems"][:10]))
    if ic.get("interfaces"):
        lines.append("Interfaces (id, name, changeable fields):")
        for i in ic["interfaces"][:30]:
            vals = ", ".join(f"{k}={v}" for k, v in archie_chat._editable(i).items())
            lines.append(f"- {i['id']} {i.get('name', '')}: {vals}")
    crs = [c for c in doc.get("change_requests") or []][-5:]
    if crs:
        lines.append("Change requests: " + "; ".join(f"{c['id']} {c['interface']} {c['status']}" for c in crs))
    s = doc.get("supervisor") or {}
    ov = [o for o in s.get("overrides") or [] if o.get("status") == "active"]
    if ov:
        lines.append("Rules relaxed now: " + "; ".join(f"{o['rule']} on {_scope_text(doc, o)}" for o in ov))
    past = (s.get("log") or [])[-6:]
    if past:
        lines.append("Your earlier actions: " + "; ".join(f"{e['title']} ({e['status']})" for e in past))
    if doc.get("plan") and doc["status"] in ("plan_review",) or archie_chat.can_revise(doc):
        lines.append("Plan: " + "; ".join(f"{x['name']}: " + ", ".join(p["name"] for p in x.get("parts", []))
                                          for x in (doc.get("plan") or {}).get("subassemblies") or []))
    else:
        from aicad.office import revision

        lines += revision.context_lines(doc)
    lines.append("Rules you may relax: " + "; ".join(
        f"{k} ({v['what']}; {'measures geometry' if v['measures'] else 'procedural'})" for k, v in RULES.items()))
    return "\n".join(lines)


# ============================================================================ the model call and its reply
def _model() -> str:
    try:
        from aicad.llm import routing  # type: ignore[attr-defined]  # PD-82 routing, when present

        return routing.model_for("supervisor") or MODEL
    except Exception:  # noqa: BLE001 - routing not on this branch, or a bad route: Opus
        return MODEL


async def run_supervisor(folder: Path, prompt: str, budget_usd: float | None = None) -> tuple[str, float | None]:
    """One text-only supervisor turn through the provider layer (role ``supervisor``, Opus). Tests replace the
    provider (stub with recorded replies)."""
    from aicad import llm

    folder.mkdir(parents=True, exist_ok=True)
    res = await llm.complete(llm.CallRequest(role="supervisor", system=SUPERVISOR_INSTRUCTIONS, prompt=prompt,
                                             budget_usd=budget_usd, cwd=folder, standalone_system=True,
                                             model=_model(), max_tokens=4000))
    return res.text, res.metering.cost_usd


def parse_reply(text: str) -> dict[str, Any] | None:
    found = None
    for m in _BLOCK.finditer(text or ""):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(d, dict):
            found = d
    if found is None:
        return None
    from aicad.agent.session import scrub

    def clean(x: Any, n: int = 600) -> str:
        return service.plain_names(scrub(" ".join(str(x or "").split())))[:n]

    cause = str(found.get("cause") or "none").lower()
    acts = [a for a in found.get("actions") or [] if isinstance(a, dict) and a.get("tool") in TOOLS][:MAX_ACTIONS]
    for a in acts:
        a["why"] = clean(a.get("why"), 400)
        for k in ("instruction", "description"):
            if k in a:
                a[k] = clean(a[k], 800)
    return {"cause": cause if cause in CAUSES else "none", "diagnosis": clean(found.get("diagnosis")),
            "evidence": [clean(e, 300) for e in found.get("evidence") or [] if str(e).strip()][:6],
            "say": clean(found.get("say") or _BLOCK.sub("", text), 900), "actions": acts}


# ============================================================================ the rule-based reading (no AI)
def rule_plan(doc: dict[str, Any], triggers: list[dict[str, Any]], facts: dict[str, dict[str, Any]],
              wallet: int | None) -> dict[str, Any]:
    """The known patterns, read deterministically (simulated agents, no AI, the hourly cap). Same shape as the
    model's reply."""
    from aicad.office import orchestrator

    by = {t["id"]: t for t in doc.get("tickets") or []}
    acts: list[dict[str, Any]] = []
    says: list[str] = []
    ev: list[str] = []
    cause = "none"
    diag: list[str] = []
    for x in triggers:
        t = by.get(x.get("ticket") or "")
        r = (t or {}).get("run") or {}
        why = str(x.get("text") or "")
        low = why.lower()
        n_said = len(diag) + len(says)
        if x["kind"] in ("blocked", "repeat") and t is not None and t["kind"] == "integration" \
                and _PLACEMENT.search(low):
            from aicad.office import revision

            if any(a["tool"] == "revise_program" for a in acts):
                continue  # the same layout stops this level too: the one revision covers it
            cand = revision.propose(doc)
            if cand is not None:
                cause = "plan"
                loose = cand["placement"]["before"]
                diag.append(f"{t['key']} {t['title']} stopped on a measured placement problem ({why[:200]}). The "
                            "parts are fine; the layout is not: " + "; ".join(loose[:3]) + ". Numbers on one interface "
                            "can't fix that, but a revision of the program can: " + "; ".join(
                                revision.describe_ops(cand["ops"])) + ".")
                ev.append(f"{t['key']}: " + (loose[0] if loose else why[:200]))
                acts.append({"tool": "revise_program", "changes": cand["ops"],
                             "why": "Every copy gets its own joints, so nothing is left floating; what is already "
                                    "built is kept where its interfaces don't change."})
                continue
            cause = "plan"
            diag.append(f"{t['key']} {t['title']} stopped on a measured placement problem ({why[:200]}): it comes "
                        "from the layout or the plan, not from the parts.")
            says.append("I found no revision of the layout that leaves nothing floating by itself. Tell me what "
                        "should carry what (for example \"the top is the base and each leg sits on its own "
                        "bracket\") and I'll revise the program with that, keeping what is built where I can. Only "
                        "if you'd rather begin again from the brief is a new program the way out.")
            continue
        if x["kind"] in ("blocked", "repeat") and t is not None:
            f = facts.get(t["id"]) or {}
            keys = _feature_keys(t)
            if "came back exactly the same" in low or (x["kind"] == "repeat" and keys and r.get("last_findings")):
                cause = "measurement"
                first = (r.get("last_findings") or [why])[0]
                diag.append(f"{t['key']} {t['title']}: the designer rebuilt it and the measurement didn't move "
                            f"({str(first)[:220]}). That points at the measurement or the interface spec, not the part.")
                ev.append(f"{t['key']}: same measured value after a redesign")
                feat = next((k for k in keys if k not in ("frame",)), None)
                rule = "envelope" if feat == "envelope" else "conformance"
                acts.append({"tool": "relax_rule", "rule": rule, "ticket": t["key"], "feature": feat,
                             "expiry": "rebuild", "why": "A redesign didn't move the measurement, so another round "
                             "can't help; the part looks as specified. Relaxed for this feature of this part until its "
                             "next rebuild, and shown as relaxed, not passed."})
            elif ("sent" in low and "back" in low and "times" in low) or "review" in low and "rounds" in low:
                hard = list(r.get("last_findings") or [])
                ic_ok = (t.get("icd_check") or {}).get("ok", True)
                if not hard and ic_ok and f.get("ok"):
                    cause = "rule"
                    diag.append(f"{t['key']} {t['title']} stopped on the review-round cap, but every measurable check "
                                "passes; only advisory review points are left.")
                    ev.append(f"{t['key']}: build passes its gating checks; no measurable finding open")
                    acts.append({"tool": "approve_with_notes", "ticket": t["key"],
                                 "why": "Only advisory points remain after the round cap; the points are recorded for "
                                        "the engineer."})
                elif hard:
                    cause = "part"
                    diag.append(f"{t['key']} {t['title']} still fails a measurable check: {str(hard[0])[:220]}")
                    acts.append({"tool": "send_back", "ticket": t["key"], "instruction":
                                 "Fix exactly this, nothing else: " + " ".join(str(h) for h in hard[:3])[:700],
                                 "why": "A measurable check still fails and each round moved the part: one more round "
                                        "with the exact finding."})
            elif "without a build that passes" in low or "stopped" in low and "times" in low:
                cause = "part"
                diag.append(f"{t['key']} {t['title']}: the designer's runs ended without a build that passes.")
                if x["kind"] == "blocked":
                    acts.append({"tool": "retry", "ticket": t["key"], "why": "One more run often clears a failed build; "
                                 "if it fails the same way again I'll come back to you."})
            elif "run budget" in low:
                cause = "budget"
                diag.append(f"{t['key']} {t['title']} stopped at its run budget before finishing.")
                says.append(f"{t['key']} {t['title']} stopped at its run budget. A retry carries on and uses more "
                            "tokens: retry it if the budget allows.")
            elif "clash" in low and t["kind"] == "part" and _placeholder_clash(doc, t):
                # (benchmark A1) every overlap is with a part that is still a placeholder: an envelope built from
                # the interfaces, not the part. A measurement artefact: the part goes back to Fitz unchanged
                waits = _placeholder_clash(doc, t) or []
                cause = "measurement"
                diag.append(f"{t['key']} {t['title']} was stopped for clashing with the placeholder of "
                            f"{', '.join(waits)}, which is not built yet. A placeholder is the envelope the "
                            "interfaces describe, not the part, so that overlap says nothing about the real parts: "
                            "a measurement artefact, not a fault in this part.")
                ev.append(f"{t['key']}: every clash is with a placeholder ({', '.join(waits)})")
                if x["kind"] == "blocked":
                    acts.append({"tool": "retry", "ticket": t["key"], "why": "Fitz swaps it in again unchanged; the "
                                 f"overlap with {', '.join(waits)} is checked for real when that part is built."})
            elif "clash" in low:
                cause = "interfaces"
                diag.append(f"{t['key']} {t['title']} still clashes in the program assembly: {why[:220]}")
                if x["kind"] == "blocked":
                    acts.append({"tool": "send_back", "ticket": t["key"], "instruction":
                                 f"Clear this clash with the neighbouring part, keeping every interface as the ICD "
                                 f"states: {why[:400]}", "why": "One round with the exact clash."})
            elif x["kind"] == "blocked" and not t.get("paused"):
                cause = cause if cause != "none" else "capacity"
                diag.append(f"{t['key']} {t['title']} is blocked: {why[:220]}")
                acts.append({"tool": "retry", "ticket": t["key"], "why": "A step that stopped once is retried once."})
            if x["kind"] == "repeat" and not any(a.get("ticket") == t["key"] and a["tool"] == "relax_rule" for a in acts):
                acts = [a for a in acts if a.get("ticket") != t["key"] or a["tool"] not in ("retry", "send_back")]
                says.append(f"{t['key']} {t['title']} failed the same way again after I acted, so I won't repeat it: "
                            "it needs your decision (comment, take it over, or approve it yourself).")
            if len(diag) + len(says) == n_said:  # nothing above applies (a paused part): say what it is, plainly
                diag.append(f"{t['key']} {t['title']} is blocked: {why[:300]}")
        elif x["kind"] == "stuck" and t is not None:
            cause = "capacity"
            diag.append(f"{t['key']} {t['title']} shows no progress for a long time ({why}).")
            acts.append({"tool": "retry", "ticket": t["key"], "why": "The step looks hung: interrupt it and let the "
                         "office pick it up again."})
        elif x["kind"] == "budget":
            cause = "budget"
            b = orchestrator.budget_state(doc)
            done = [t for t in doc["tickets"] if t["column"] in service.DONE_COLUMNS and t["kind"] == "part"]
            left = [t for t in doc["tickets"] if t["column"] not in service.DONE_COLUMNS and t["kind"] == "part"]
            per = max(10, round(sum(int(t.get("tokens") or 0) + int(t.get("review_tokens") or 0) for t in done)
                                / max(1, len(done))))
            want = b["spent"] + max(per * max(1, len(left)), round(0.2 * b["tokens"]))
            cap = None if wallet is None else b["spent"] + max(0, wallet)
            tokens = min(want, cap) if cap is not None else want
            diag.append(f"The program has used {b['spent']} of {b['tokens']} tokens with {len(left)} part"
                        f"{'s' if len(left) != 1 else ''} still open (about {per} tokens each so far).")
            if tokens > b["tokens"]:
                acts.append({"tool": "budget", "tokens": int(tokens), "why": f"About {per} tokens per part so far and "
                             f"{len(left)} open: enough to finish, within the wallet."})
            else:
                says.append("The wallet can't cover more budget: top up, or let the office stop at the budget.")
        elif x["kind"] == "scope":
            cause = "plan"
            diag.append(f"{x['text']}.")
            acts.append({"tool": "remove_part", "part": x["part"], "why": "The brief rules this kind of part out."})
        elif x["kind"] == "gate":
            g = gate_plan(doc, asked=bool(x.get("asked")))
            cause = g["cause"]
            diag.append(g["diagnosis"])
            acts += g["actions"]
            says += g["says"]
        elif x["kind"] == "looks_wrong" and t is not None:
            diag.append(f"The visual check on {t['title']} says it looks wrong ({why[:160]}); measurements decide, "
                        "and none confirmed it.")
    if not diag and not says:
        return {"cause": "none", "diagnosis": "", "evidence": [], "say": "", "actions": []}
    seen: set[str] = set()
    uniq = []
    for a in acts:
        k = json.dumps({k: v for k, v in a.items() if k != "why"}, sort_keys=True)
        if k not in seen:
            seen.add(k)
            uniq.append(a)
    return {"cause": cause, "diagnosis": " ".join(diag)[:900], "evidence": ev[:6], "say": " ".join(says)[:900],
            "actions": uniq[:MAX_ACTIONS]}


# ============================================================================ typed tools: check, classify, describe
def _placeholder_clash(doc: dict[str, Any], t: dict[str, Any]) -> list[str] | None:
    from aicad.office import program_assembly

    return program_assembly.placeholder_only(doc, t)


def _ticket(doc: dict[str, Any], ref: Any) -> dict[str, Any] | None:
    return archie_chat.find_ticket(doc, str(ref or ""))


def _plan_parts(doc: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(s["name"], p) for s in (doc.get("plan") or {}).get("subassemblies") or [] for p in s.get("parts") or []]


def _plan_editable(doc: dict[str, Any]) -> bool:
    """Parts may be added or removed while the plan waits for review, or at the interfaces gate before any part work
    (afterwards: an engineering change, PD-100)."""
    return doc.get("status") == "plan_review" or archie_chat.can_revise(doc)


def _no_hard_findings(t: dict[str, Any], facts: dict[str, dict[str, Any]]) -> str | None:
    """None when only advisory points remain on the ticket; else why not (Archie never fakes a pass)."""
    r = t.get("run") or {}
    f = facts.get(t["id"]) or {}
    if not f.get("builds"):
        return "there is no build of it to approve"
    if f.get("ok") is not True:
        return "its latest build fails a gating check"
    if r.get("last_findings"):
        return "a measurable check still fails: " + str(r["last_findings"][0])[:200]
    ic = t.get("icd_check") or {}
    if ic and not ic.get("ok"):
        relaxed = {(x.get("feature") or "") for x in t.get("relaxed") or []}
        bad = [k for k in _feature_keys(t) if k not in relaxed]
        if bad:
            return f"its interfaces don't conform ({bad[0]})"
    return None


def check(doc: dict[str, Any], a: dict[str, Any], facts: dict[str, dict[str, Any]] | None = None,
          wallet: int | None = None) -> tuple[dict[str, Any] | None, str]:
    """One proposed action against the program as it is now: (normalised action, "") or (None, why not)."""
    from aicad.office import interfaces, orchestrator

    facts = facts or {}
    tool = a.get("tool")
    why = " ".join(str(a.get("why") or "").split())[:400]
    if tool not in TOOLS:
        return None, "unknown action"
    base: dict[str, Any] = {"tool": tool, "why": why}
    st = doc.get("status")
    if tool in ("retry", "pause", "reassign", "send_back", "approve_with_notes", "edit_part"):
        t = _ticket(doc, a.get("ticket"))
        if t is None:
            return None, "no such ticket on this program"
        if st not in ("active", "complete"):
            return None, "the program isn't running yet"
        r = t.get("run") or {}
        base["ticket"] = t["key"]
        busy = r.get("status") in orchestrator.ACTIVE
        if t.get("taken_over"):
            return None, f"{t['key']} is taken over by an engineer"
        if tool == "retry":
            if not busy and r.get("status") not in ("blocked", "retry", "waiting_capacity"):
                return None, f"{t['key']} isn't blocked"
            base["interrupt"] = busy
            return base, ""
        if tool == "pause":
            return (base, "") if not t.get("paused") else (None, f"{t['key']} is already paused")
        if tool == "reassign":
            to = str(a.get("to") or "").lower()
            if t["kind"] not in ("part", "standard") or to not in roster.DESIGNERS or to == t["specialist"] or busy:
                return None, "it can't be reassigned to that designer now"
            base["to"] = to
            return base, ""
        if tool == "send_back":
            txt = " ".join(str(a.get("instruction") or "").split())[:1200]
            if not txt or t["kind"] not in ("part", "standard") or t["column"] == "integrated":
                return None, "nothing to send back"
            base["instruction"] = txt
            return base, ""
        if tool == "edit_part":
            txt = " ".join(str(a.get("description") or "").split())[:1200]
            if not txt or t["kind"] not in ("part", "standard") or t["column"] in service.DONE_COLUMNS:
                return None, "that part can't be edited now"
            base["description"] = txt
            return base, ""
        if tool == "approve_with_notes":
            if r.get("status") != "blocked" or t["kind"] != "part":
                return None, f"{t['key']} isn't waiting on the review rules"
            bad = _no_hard_findings(t, facts)
            if bad:
                return None, f"{t['key']} can't be approved: {bad}"
            base["notes"] = list(r.get("ai_findings") or t.get("review_notes") or [])[:8]
            return base, ""
    if tool == "relax_rule":
        rule = str(a.get("rule") or "")
        if rule not in RULES:
            return None, NEVER_RELAXED if rule.lower().startswith(("chk", "gating", "gate")) else "unknown rule"
        base["rule"] = rule
        if a.get("ticket"):
            t = _ticket(doc, a["ticket"])
            if t is None:
                return None, "no such ticket on this program"
            base["scope"] = {"kind": "ticket", "ticket": t["id"], "key": t["key"]}
        elif a.get("interface"):
            f = next((x for x in (doc.get("icd") or {}).get("interfaces") or [] if x["id"] == a["interface"]), None)
            if f is None:
                return None, "no such interface"
            if not RULES[rule]["measures"]:
                return None, "a procedural rule is relaxed per ticket or for the program"
            base["scope"] = {"kind": "interface", "interface": f["id"]}
        elif a.get("scope") == "program":
            if RULES[rule]["measures"]:
                return None, "a check that measures geometry is only relaxed for one part or one interface"
            base["scope"] = {"kind": "program"}
        else:
            return None, "say which ticket, interface or the program"
        feat = a.get("feature")
        if feat and rule in ("conformance", "envelope"):
            if base["scope"]["kind"] == "ticket":
                t = next(x for x in doc["tickets"] if x["id"] == base["scope"]["ticket"])
                keys = _feature_keys(t)
                hit = next((k for k in keys if k == feat or k.lower() == str(feat).lower()), None)
                if hit is None:
                    return None, f"{feat} isn't a failing feature of {t['key']}"
                feat = hit
            base["feature"] = str(feat)[:200]
        if base["scope"]["kind"] == "ticket":
            b0 = (facts.get(base["scope"]["ticket"]) or {}).get("builds")
            if isinstance(b0, int):
                base["builds_at"] = b0  # "until the next rebuild" counts from the build Archie looked at
        ex = a.get("expiry")
        if isinstance(ex, int) and not isinstance(ex, bool) and 1 <= ex <= 5:
            base["expiry"] = {"kind": "rounds", "n": ex, "left": ex}
        elif ex in (None, "rebuild") and RULES[rule]["measures"]:
            base["expiry"] = {"kind": "rebuild"}
        else:
            n = int(RULES[rule].get("extra") or 1)
            base["expiry"] = {"kind": "rounds", "n": n, "left": n}
        if not why:
            return None, "a relaxation needs a stated reason"
        dup = any(o.get("status") == "active" and o["rule"] == rule and o.get("scope", {}).get("kind") ==
                  base["scope"]["kind"] and o["scope"].get("ticket") == base["scope"].get("ticket")
                  and o["scope"].get("interface") == base["scope"].get("interface")
                  and o.get("feature") == base.get("feature")
                  for o in (doc.get("supervisor") or {}).get("overrides") or [])
        if dup:
            return None, "that rule is already relaxed there"
        return base, ""
    if tool == "keep_separate":
        n = archie_chat.normalise(doc, {"type": "keep_separate", "parts": a.get("parts") or []})
        if n is None:
            return None, "no unconnected part to keep separate"
        return {**base, "items": n["items"], "parts": n["parts"]}, ""
    if tool in PLAN_TOOLS and not _plan_editable(doc):
        # part work has started: the same change is a revision of the program (ICD v+1), never a new program
        op = {"remove_part": {"op": "remove", "part": a.get("part")}, "set_qty": {"op": "qty", "part": a.get("part"),
                                                                                "qty": a.get("qty")},
              "add_part": {"op": "add", "sub": a.get("sub"), "part": a.get("part")}}[tool]
        return check(doc, {"tool": "revise_program", "why": why, "changes": [op]}, facts, wallet)
    if tool == "revise_program":
        from aicad.office import revision

        try:
            cand = revision.candidate(doc, a.get("changes") or a.get("ops") or [])
        except OfficeInputError as e:
            return None, str(e).rstrip(".")
        if not cand["ok"]:
            return None, cand["why"].rstrip(".")
        busy = revision.busy_tickets(doc, cand["impact"])
        if busy:
            return None, f"{busy[0]} is in the middle of a step"
        return {**base, "changes": cand["ops"], "impact": revision.view(cand), "icd_version":
                int((doc.get("icd") or {}).get("version") or 1), "title": revision.title(cand, doc),
                **({"engineer_asked": True} if a.get("engineer_asked") else {})}, ""
    if tool in PLAN_TOOLS:
        if tool in ("remove_part", "set_qty"):
            name = str(a.get("part") or "").strip().lower()
            hits = [(s, p) for s, p in _plan_parts(doc) if p["name"].lower() == name]
            if len(hits) != 1:
                return None, "no such part in the plan"
            if tool == "set_qty":
                q = a.get("qty")
                if not isinstance(q, int) or isinstance(q, bool) or not 1 <= q <= 64 or q == int(hits[0][1].get("qty") or 1):
                    return None, "that quantity changes nothing"
                return {**base, "part": hits[0][1]["name"], "sub": hits[0][0], "qty": q,
                        "before": int(hits[0][1].get("qty") or 1)}, ""
            if len(_plan_parts(doc)) <= 1:
                return None, "the plan would be empty"
            return {**base, "part": hits[0][1]["name"], "sub": hits[0][0]}, ""
        add = a.get("part") if isinstance(a.get("part"), dict) else {}
        subs = [s["name"] for s in (doc.get("plan") or {}).get("subassemblies") or []]
        sub = str(a.get("sub") or (subs[0] if len(subs) == 1 else ""))
        nm = " ".join(str(add.get("name") or "").split())[:80]
        if sub not in subs or not nm:
            return None, "say which sub-assembly and the part's name"
        return {**base, "sub": sub, "part": {"name": nm, "family": roster.normalise_family(add.get("family")),
                                             "complexity": max(1, min(5, int(add.get("complexity") or 2))),
                                             "qty": max(1, min(8, int(add.get("qty") or 1))),
                                             "description": " ".join(str(add.get("description") or "").split())[:400]}}, ""
    if tool == "resize_part":
        n = archie_chat.normalise(doc, {"type": "resize_part", "part": a.get("part"), "size": a.get("size")})
        if n is None:
            return None, "a part is resized only before the interfaces are approved"
        return {**base, "part": n["part"], "item": n["item"], "size": n["size"]}, ""
    if tool == "change_interface":
        n = archie_chat.normalise(doc, {"type": "interface_change", "interface": a.get("interface"),
                                        "values": a.get("values"), "reason": why or "Archie's diagnosis"})
        if n is None:
            return None, "that interface number can't change"
        ic = doc.get("icd") or {}
        return {**base, "interface": n["interface"], "values": n["values"], "icd_status": ic.get("status")}, ""
    if tool == "budget":
        b = orchestrator.budget_state(doc)
        out = dict(base)
        if isinstance(a.get("tokens"), int) and not isinstance(a.get("tokens"), bool) and 0 < a["tokens"] <= 1_000_000:
            cap = None if (b["bypass"] or wallet is None) else b["spent"] + max(0, int(wallet))
            if cap is not None and a["tokens"] > max(cap, b["tokens"]):
                return None, f"the wallet allows at most {cap} tokens for this program"
            if a["tokens"] != b["tokens"]:
                out["tokens"] = int(a["tokens"])
                out["before"] = b["tokens"]
        if isinstance(a.get("concurrency"), int) and 1 <= a["concurrency"] <= 12 \
                and a["concurrency"] != doc.get("concurrency"):
            out["concurrency"] = int(a["concurrency"])
            out["concurrency_before"] = doc.get("concurrency")
        return (out, "") if len(out) > 2 else (None, "nothing to change")
    _ = interfaces
    return None, "unknown action"


def classify(doc: dict[str, Any], a: dict[str, Any]) -> tuple[str, str]:
    """Minor (Archie does it and tells) or major (Archie asks first), with the reason. Deterministic (PD-98)."""
    tool = a["tool"]
    if tool in MINOR_TOOLS:
        return "minor", {"retry": "a retry changes nothing in the design",
                         "pause": "a pause is undone by Resume",
                         "reassign": "another designer, same part and interfaces",
                         "send_back": "a better instruction to the designer, same part",
                         "approve_with_notes": "every measurable check passes; only advisory notes remain"}[tool]
    if tool == "keep_separate":
        if _STANDALONE.search(doc.get("brief") or ""):
            return "minor", "the brief says these parts stand on their own"
        return "major", "only you can say a part is meant to have no interface"
    if tool == "relax_rule":
        if RULES[a["rule"]]["measures"]:
            return "major", "it relaxes a check that measures geometry"
        return "minor", "a procedural rule that measures nothing"
    if tool == "budget":
        if a.get("tokens") is not None and a["tokens"] > int(a.get("before") or 0):
            return "major", "it raises the budget"
        return "major", "program settings are yours to change"
    if tool == "revise_program":
        imp = a.get("impact") or {}
        if imp.get("replace_only") and a.get("engineer_asked"):
            return "minor", "it only re-places parts, and you approved the plan change"
        # founder 2026-11-20: the plan is Archie's own; a revision that redoes no modelled work and drops no part the
        # brief names stays within the brief, so he makes it and tells (it is undoable from the Archie log)
        brief = (doc.get("brief") or "").lower()
        rework = any(r.get("started") and r.get("class") in ("redesign", "removed") for r in imp.get("parts") or [])
        named = [r for r in imp.get("parts") or [] if r.get("class") == "removed"
                 and str(r.get("name") or "").lower() in brief]
        if imp and not rework and not named:
            return "minor", "it changes only my own plan (layout, sizes, hosts) within your brief; nothing modelled is redone"
        mw = list(imp.get("major_why") or []) or ["it changes the plan and the interfaces"]
        return "major", " and ".join(mw)
    if tool in ("remove_part", "add_part"):
        return "major", "it adds or removes a part"
    if tool == "set_qty":
        return "major", "it changes how many of a part the plan has"
    if tool == "change_interface":
        if a.get("icd_status") == "approved":
            return "major", "it changes an approved interface"
        return "major", "it changes the interfaces"
    return "major", "it changes the plan"


def _scope_text(doc: dict[str, Any], o: dict[str, Any]) -> str:
    sc = o.get("scope") or {}
    if sc.get("kind") == "ticket":
        t = next((x for x in doc.get("tickets") or [] if x["id"] == sc.get("ticket")), None)
        return f"{t['key']} {t['title']}" if t else str(sc.get("key") or "a part")
    if sc.get("kind") == "interface":
        return f"interface {sc.get('interface')}"
    return "the whole program"


def _expiry_text(ex: dict[str, Any] | None, rule: str) -> str:
    ex = ex or {}
    if ex.get("kind") == "rebuild":
        return "until the part's next rebuild"
    n = int(ex.get("n") or 1)
    if not RULES[rule]["measures"]:
        return f"for {n} more round{'s' if n != 1 else ''}"
    return f"for {n} review{'s' if n != 1 else ''}"


def describe(doc: dict[str, Any], a: dict[str, Any]) -> str:
    t = _ticket(doc, a.get("ticket")) if a.get("ticket") else None
    lbl = f"{t['key']} {t['title']}" if t else str(a.get("ticket") or "")
    tool = a["tool"]
    if tool == "retry":
        return f"Restart {lbl} (it looked hung)" if a.get("interrupt") else f"Retry {lbl}"
    if tool == "pause":
        return f"Pause {lbl}"
    if tool == "reassign":
        return f"Reassign {lbl} to {roster.agent(a['to'])['name']}"
    if tool == "send_back":
        return f"Send {lbl} back to its designer: {a['instruction']}"
    if tool == "approve_with_notes":
        return f"Approve {lbl} with Gage's advisory notes recorded"
    if tool == "relax_rule":
        what = RULES[a["rule"]]["label"] + (f" for {feature_text(a['feature'])}" if a.get("feature") else "")
        return f"Relax {what} on {_scope_text(doc, a)}, {_expiry_text(a.get('expiry'), a['rule'])}"
    if tool == "keep_separate":
        names = a.get("parts") or []
        return "Keep " + (names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]) + \
            (" as a separate part" if len(names) == 1 else " as separate parts")
    if tool == "revise_program":
        return str(a.get("title") or "Revise the program")
    if tool == "remove_part":
        return f"Remove {a['part']} from the plan"
    if tool == "add_part":
        return f"Add {a['part']['name']} to {a['sub']}"
    if tool == "set_qty":
        return f"Plan {a['qty']} × {a['part']} instead of {a.get('before', '?')}"
    if tool == "resize_part":
        return f"Resize {a['part']}: " + ", ".join(f"{k} {v:g} mm" for k, v in a["size"].items())
    if tool == "edit_part":
        return f"Add to the brief of {lbl}: {a['description']}"
    if tool == "change_interface":
        vals = ", ".join(f"{k} → {v:g}" if isinstance(v, (int, float)) else f"{k} → {v}" for k, v in a["values"].items())
        return (f"Change request on interface {a['interface']}: {vals}" if a.get("icd_status") == "approved"
                else f"Edit interface {a['interface']}: {vals}")
    if tool == "budget":
        bits = []
        if "tokens" in a:
            bits.append(f"token budget {a.get('before', 0):,} → {a['tokens']:,}")
        if "concurrency" in a:
            bits.append(f"{a['concurrency']} agents at a time")
        return "Set " + " and ".join(bits)
    return tool


# ============================================================================ wallet, metering, the actor
def wallet_left(org_id: str) -> int | None:
    """Tokens the workspace can still spend (balance minus reservations), or None when unknown (no database)."""
    try:
        from aicad.platform import metering
        from aicad.platform.db import session_factory
        from aicad.platform.models import Organization

        db = session_factory()()
        try:
            org = db.get(Organization, org_id)
            return None if org is None else max(0, int(org.token_balance) - metering.reserved(org_id))
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        return None


def charge(root: Path, pid: str, org_id: str, user_id: str | None, tokens: int, god: bool) -> None:
    try:
        from aicad.platform.db import session_factory
        from aicad.platform.models import Organization, User
        from aicad.platform.services import debit, track

        db = session_factory()()
        try:
            org = db.get(Organization, org_id)
            user = db.get(User, user_id) if user_id else None
            if tokens and org is not None and not god:
                debit(db, org, tokens, "usage", "Design Office · Archie supervising", user, ref=pid)
            track(db, "office_supervisor", user, org_id, tokens=0 if god else tokens)
            db.commit()
        finally:
            db.close()
    except Exception:
        log.warning("supervisor metering failed", exc_info=True)
    if tokens and not god:
        with store.lock(pid):
            d = store.load(root, pid)
            if d is not None:
                d["budget"]["planning_tokens"] = int(d["budget"].get("planning_tokens", 0)) + tokens
                store.save(root, d)


def mode(doc: dict[str, Any]) -> str:
    """``ai`` (Archie's model call), ``simulated`` (development: simulated agents, rule-based reading) or ``rules``."""
    from aicad.office import fake_agents

    if fake_agents.enabled() and os.environ.get(LIVE_ENV, "") not in ("1", "true", "yes"):
        return "simulated"
    if os.environ.get("FW_OFFICE_SUPERVISOR_AI", "1") in ("0", "false", "no"):
        return "rules"
    return "ai"


def calls_last_hour(doc: dict[str, Any], now: float | None = None) -> int:
    now = time.time() if now is None else now
    return sum(1 for c in (doc.get("supervisor") or {}).get("calls") or [] if now - float(c) < 3600)


ARCHIE = {"kind": "agent", "code": "archie", "name": "Archie"}


def _actor(approved_by: dict[str, Any] | None = None) -> dict[str, Any]:
    a = service.agent_actor("archie")
    if approved_by:
        a = {**a, "name": f"Archie (approved by {approved_by.get('name', 'the engineer')})"}
    return a


# ============================================================================ applying actions
def _edit(root: Path, pid: str, fn: Any) -> Any:
    with store.lock(pid):
        doc = store.load(root, pid)
        if doc is None:
            raise OfficeInputError("Program not found")
        out = fn(doc)
        store.save(root, doc)
        return out


def _next_seq(s: dict[str, Any], k: str = "seq") -> int:
    s[k] = int(s.get(k) or 0) + 1
    return s[k]


async def execute(root: Path, pid: str, a: dict[str, Any], env: Any = None,
                  approved_by: dict[str, Any] | None = None) -> tuple[str, dict[str, Any] | None]:
    """Apply one checked action through the office's own service functions. Returns (outcome, undo info)."""
    from aicad.office import interfaces, orchestrator

    actor = _actor(approved_by)
    tool = a["tool"]
    if tool in ("retry", "pause", "reassign", "send_back", "approve_with_notes", "edit_part"):
        def fn(d: dict[str, Any]) -> tuple[str, dict[str, Any] | None, bool]:
            t = archie_chat.find_ticket(d, a["ticket"])
            if t is None:
                raise OfficeInputError("That ticket is no longer on the program.")
            busy = (t.get("run") or {}).get("status") in orchestrator.ACTIVE
            if tool == "retry":
                if busy:
                    return f"Interrupted {t['key']}: the office picks it up again.", None, True
                if orchestrator.refit_placeholder_clash(root, d, t, actor):  # (benchmark A1) unchanged, to Fitz
                    return f"{t['key']} goes back to Fitz to be swapped in again, unchanged.", None, False
                orchestrator.control(root, d, t["id"], "retry", actor)
                orchestrator.close_wait(t)
                return f"{t['key']} is back in the queue.", None, False
            if tool == "pause":
                interrupt = orchestrator.control(root, d, t["id"], "pause", actor)
                return f"{t['key']} is paused.", {"kind": "resume", "ticket": t["id"]}, interrupt
            if tool == "reassign":
                before = t["specialist"]
                service.update(root, d, t["id"], actor, specialist=a["to"])
                if (t.get("run") or {}).get("status") == "blocked":
                    orchestrator.control(root, d, t["id"], "retry", actor)
                return (f"{t['key']} now goes to {roster.agent(a['to'])['name']}.",
                        {"kind": "reassign", "ticket": t["id"], "to": before}, False)
            if tool == "send_back":
                orchestrator.archie_instruction(root, d, t["id"], a["instruction"], actor)
                return f"{t['key']} went back to {roster.agent(t['specialist'])['name']} with the instruction.", None, False
            if tool == "edit_part":
                before = t["brief"]
                t["brief"] = f"Plan change (Archie): {a['description']}\n\n{t['brief']}"[:8000]
                turns = int((t.get("run") or {}).get("turns") or 0)
                service.emit(root, d, "ticket.updated", f"{actor['name']} added to the brief of {service._label(t)}: "
                             f"{a['description']}", actor, t["id"])
                if (t.get("run") or {}).get("status") == "blocked":
                    orchestrator.archie_instruction(root, d, t["id"], a["description"], actor)
                return (f"{t['key']}'s brief now carries the change.",
                        {"kind": "brief", "ticket": t["id"], "brief": before, "turns": turns}, False)
            # approve_with_notes
            orchestrator.approve_with_notes(root, d, t["id"], list(a.get("notes") or []), actor)
            return f"{t['key']} is approved with its advisory notes recorded.", None, False
        outcome, undo, interrupt = _edit(root, pid, fn)
        if interrupt:
            t = archie_chat.find_ticket(store.load(root, pid) or {"tickets": []}, a["ticket"])
            if t is not None:
                await orchestrator.interrupt(pid, t["id"])
        _wake(root, pid)
        return outcome, undo
    if tool == "relax_rule":
        def fn2(d: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            s = sup(d)
            o = {"id": f"RO-{_next_seq(s, 'oseq')}", "rule": a["rule"], "label": RULES[a["rule"]]["label"],
                 "scope": a["scope"], "feature": a.get("feature"), "reason": a["why"],
                 "expiry": copy.deepcopy(a["expiry"]), "status": "active", "at": store.now(), "by": "Archie",
                 "approved_by": (approved_by or {}).get("name"),
                 "extra": RULES[a["rule"]].get("extra") if not RULES[a["rule"]]["measures"] else None}
            if o["expiry"]["kind"] == "rounds" and not RULES[a["rule"]]["measures"]:
                o["extra"] = o["expiry"]["n"]
            if isinstance(a.get("builds_at"), int):
                o["builds"] = {a["scope"]["ticket"]: a["builds_at"]}
            s["overrides"].append(o)
            service.emit(root, d, "supervisor.relaxed", f"{actor['name']} relaxed {o['label']}"
                         + (f" for {feature_text(o['feature'])}" if o.get("feature") else "") + f" on {_scope_text(d, o)}, "
                         f"{_expiry_text(o['expiry'], o['rule'])}: {o['reason']}", actor, a["scope"].get("ticket"),
                         override=o["id"], rule=o["rule"])
            back = []
            for t in d["tickets"]:
                r = t.get("run") or {}
                if r.get("status") == "blocked" and _ticket_scope(o, d, t) and not t.get("taken_over"):
                    nxt = r.get("next") or RULES[a["rule"]]["next"]
                    orchestrator.control(root, d, t["id"], "retry", actor)
                    orchestrator.close_wait(t)
                    orchestrator._set_run(t, next=nxt, line=f"Back to work: {o['label']} relaxed by Archie")
                    back.append(t["key"])
            head = (f"Relaxed (not passed) {_expiry_text(o['expiry'], o['rule'])}." if RULES[a["rule"]]["measures"]
                    else f"The {o['label'].removeprefix('the ')} is relaxed {_expiry_text(o['expiry'], o['rule'])}.")
            return head + (f" {', '.join(back)} went back to work." if back else ""), {"kind": "override", "id": o["id"]}
        outcome, undo = _edit(root, pid, fn2)
        _wake(root, pid)
        return outcome, undo
    if tool == "keep_separate":
        _edit(root, pid, lambda d: interfaces.keep_separate(root, d, a["items"], True, actor))
        return "Recorded at the interfaces gate.", {"kind": "separate", "items": a["items"]}
    if tool == "revise_program":
        from aicad.office import revision

        rev = _edit(root, pid, lambda d: revise_now(root, d, a["changes"], actor, a.get("why") or "Archie's diagnosis",
                                                    expect=a.get("icd_version")))
        revision.spawn_rebuild(root, pid, env)
        _wake(root, pid)
        return (f"{rev['id']}: ICD v{rev['icd_from']} → v{rev['icd_to']}. {rev['summary']}. "
                + (f"Reopened {', '.join(x['key'] for x in rev['reopened'])}. " if rev["reopened"] else "")
                + (f"Assemblies run again: {', '.join(rev['reset'])}. " if rev["reset"] else "")
                + "The office carries on to completion."), {"kind": "revision", "id": rev["id"]}
    if tool in PLAN_TOOLS:
        def fn3(d: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            old = copy.deepcopy(d["plan"])
            stage = d["status"]
            note = (f"Archie removed {a['part']}: {a['why']}" if tool == "remove_part" else
                    f"Archie planned {a['qty']} × {a['part']} instead of {a.get('before')}: {a['why']}"
                    if tool == "set_qty" else f"Archie added {a['part']['name']} to {a['sub']}: {a['why']}")
            subs = [{**x, "parts": [dict(p) for p in x["parts"]]} for x in d["plan"]["subassemblies"]]
            for x in subs:
                if tool == "remove_part":
                    x["parts"] = [p for p in x["parts"] if p["name"] != a["part"]]
                elif tool == "set_qty":
                    for p in x["parts"]:
                        if p["name"] == a["part"]:
                            p["qty"] = a["qty"]
                elif x["name"] == a["sub"]:
                    x["parts"].append(dict(a["part"]))
            subs = [x for x in subs if x["parts"]]
            from aicad.office import planner, scope

            p2 = planner.normalise_plan({**d["plan"], "subassemblies": subs}, d["plan"]["source"])
            if p2 is None:
                raise OfficeInputError("The plan would be empty.")
            if stage == "plan_review":
                d["plan"] = {**d["plan"], **p2, "edited": True,
                             "note": ((d["plan"].get("note") or "") + " " + note).strip()}
                d["light"] = scope.light_info(d["plan"], d.get("brief") or "")
                service.emit(root, d, "plan.revised", note, actor)
                return "The plan in review changed; approve it as usual.", {"kind": "plan", "stage": stage, "plan": old}
            # at the interfaces gate, nothing started: the plan changes and the program is laid out again (the ICD
            # is derived again from the new plan and the gate checks it again)
            service.revise_plan(root, d, {"notes": note, "plan": {"subassemblies": subs}}, actor)
            service.approve_plan(root, d, None, approved_by and service.user_actor(approved_by.get("name", "Engineer"),
                                                                                  approved_by.get("id")) or actor)
            n = len((d.get("icd") or {}).get("problems") or [])
            return ("The plan changed and the program was laid out again: "
                    + ("the interfaces have no problem left and wait for your approval." if not n else
                       f"{n} interface problem{'s' if n != 1 else ''} still open."),
                    {"kind": "plan", "stage": "icd", "plan": old})
        outcome, undo = _edit(root, pid, fn3)
        return outcome, undo
    if tool == "resize_part":
        def fn4(d: dict[str, Any]) -> dict[str, Any]:
            it = d["skeleton"]["items"][a["item"]]
            before = {k: v for k, v in (d["icd"]["overrides"].get("items", {}).get(a["item"]) or {}).items()
                      if k in a["size"]}
            interfaces.resize(root, d, a["item"], a["size"], actor)
            return {"kind": "resize", "item": a["item"], "before": before, "size_before": list(it.get("size") or [])}
        undo = _edit(root, pid, fn4)
        return "Resized in the draft interfaces.", undo
    if tool == "change_interface":
        if a.get("icd_status") == "draft":
            def fn5(d: dict[str, Any]) -> dict[str, Any]:
                f = next(x for x in d["icd"]["interfaces"] if x["id"] == a["interface"])
                before = {k: archie_chat._editable(f).get(k) for k in a["values"]}
                interfaces.edit(root, d, a["interface"], a["values"], actor)
                return {"kind": "interface", "interface": a["interface"], "values": before}
            undo = _edit(root, pid, fn5)
            return "The draft interface changed.", undo
        cid = _edit(root, pid, lambda d: interfaces.raise_cr(root, d, a["interface"], a["values"], a["why"] or
                                                           "Archie's diagnosis", actor)["id"])
        from aicad.office import platform_env

        res = await platform_env.decide_cr(root, pid, cid, env if isinstance(env, platform_env.PlatformEnv) else None)
        st = (res or {}).get("status") or ((res or {}).get("cr") or {}).get("status")
        return f"{cid} raised: {st or 'decided'} by the interface rules.", None
    if tool == "budget":
        def fn6(d: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            undo: dict[str, Any] = {"kind": "budget"}
            if "tokens" in a:
                undo["tokens"] = d["budget"]["tokens"]
                d["budget"]["tokens"] = a["tokens"]
                o = d.get("orchestrator") or {}
                if o.get("warned") and orchestrator.budget_state(d)["level"] == "ok":
                    o["warned"] = False
                if o.get("state") == "stopped" and o.get("reason") == "budget" \
                        and orchestrator.budget_state(d)["level"] != "stop":
                    o.update(state="running", reason=None)
            if "concurrency" in a:
                undo["concurrency"] = d["concurrency"]
                d["concurrency"] = a["concurrency"]
            service.emit(root, d, "program.updated", f"{actor['name']} set the program's {describe(d, a)[4:]}.", actor)
            return "Budget set.", undo
        outcome, undo = _edit(root, pid, fn6)
        _wake(root, pid)
        return outcome, undo
    raise OfficeInputError("Unknown action")


def revise_now(root: Path, d: dict[str, Any], changes: list[dict[str, Any]], actor: dict[str, Any], why: str,
               expect: int | None = None, source: str = "archie") -> dict[str, Any]:
    """Derive the revision again against the program as it is now and apply it, then set the office running so the
    program goes on to completion (the caller holds the program lock)."""
    from aicad.office import orchestrator, revision

    if expect is not None and int((d.get("icd") or {}).get("version") or 1) != int(expect):
        raise OfficeInputError("The interfaces changed since this was proposed: ask Archie again.")
    cand = revision.candidate(d, changes)
    if not cand["ok"]:
        raise OfficeInputError(cand["why"])
    rev = revision.apply(root, d, cand, actor, why=why, source=source)
    o = d.get("orchestrator") or {}
    if o.get("user_id") and o.get("state") != "running":
        try:
            orchestrator.start(root, d, actor, user_id=o["user_id"], god_tokens=bool(o.get("god_tokens")),
                               god_paywall=bool(o.get("god_paywall")))
        except OfficeInputError as e:  # the budget: said, and the revision stands
            service.emit(root, d, "program.note", f"{rev['id']} is applied; the office didn't start: {e}", actor)
    return rev


def log_revision(d: dict[str, Any], rev: dict[str, Any], actor: dict[str, Any], source: str) -> dict[str, Any]:
    """The Archie log entry of a revision the engineer made (chat Apply, the revision endpoint): same record as
    Archie's own, with undo."""
    imp = rev.get("impact") or {}
    return _entry(d, tool="revise_program", action={"tool": "revise_program", "impact": imp, "changes": rev["ops"]},
                  title=f"Revise the program to ICD v{rev['icd_to']} (" + "; ".join(rev["changes"][:4]) + f"): "
                        f"{rev['summary']}", why=rev.get("why") or "",
                  **{"class": "major", "class_why": "you asked for it"}, cause="plan", diagnosis="",
                  evidence=list(imp.get("lines") or [])[:6], mode="engineer", tokens=0, usd=None,
                  trigger=[source], ticket=None, status="applied",
                  outcome=f"{rev['id']}: ICD v{rev['icd_from']} → v{rev['icd_to']}. {rev['summary']}.",
                  undo={"kind": "revision", "id": rev["id"]},
                  decided={"by": actor.get("name"), "at": store.now(), "choice": "approve"})


def _wake(root: Path, pid: str) -> None:
    from aicad.office import orchestrator

    try:
        doc = store.load(root, pid)
        if doc and (doc.get("orchestrator") or {}).get("state") == "running":
            try:
                asyncio.get_running_loop()
                orchestrator.ensure(root, pid)
            except RuntimeError:
                orchestrator.poke(pid)
    except Exception:
        log.warning("could not wake the office", exc_info=True)


# ============================================================================ one supervisor pass
_locks: dict[str, asyncio.Lock] = {}
_running: dict[str, asyncio.Task[Any]] = {}
_again: set[str] = set()
_last_beat: dict[str, float] = {}


def _lock(pid: str) -> asyncio.Lock:
    lk = _locks.get(pid)
    if lk is None:
        lk = _locks[pid] = asyncio.Lock()
    return lk


async def _facts(doc: dict[str, Any], env: Any, triggers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    want = {x.get("ticket") for x in triggers if x.get("ticket")}
    want |= {t["id"] for t in doc.get("tickets") or [] if (t.get("run") or {}).get("status") == "blocked"}
    for t in doc.get("tickets") or []:
        if t["id"] in want and t.get("project_id") and env is not None:
            try:
                st = await env.part_state(t["project_id"])
                out[t["id"]] = {"builds": int(st.get("builds") or 0), "ok": st.get("ok") is True}
            except Exception:
                log.warning("part state for the supervisor failed", exc_info=True)
    return out


FIX_ROUNDS = 2  # a proposal the office can't apply goes back to Archie with the reason this many times (PD-226)


async def diagnose(root: Path, doc: dict[str, Any], triggers: list[dict[str, Any]],
                   facts: dict[str, dict[str, Any]], wallet: int | None,
                   feedback: tuple[str, list[str]] | None = None) -> tuple[dict[str, Any], str, int]:
    """(plan, how: "ai" | "simulated" | "rules", tokens). The model when it may be called, else the rules.
    ``feedback``: (his previous reply, why each of its actions could not apply): he corrects it (agentic loop)."""
    how = mode(doc)
    god = bool((doc.get("orchestrator") or {}).get("god_tokens"))
    if how == "ai" and calls_last_hour(doc) >= MAX_CALLS_PER_HOUR:
        how = "rules"
    if how == "ai" and not god and wallet is not None and wallet < CALL_MIN_TOKENS:
        how = "rules"
    if how != "ai":
        return rule_plan(doc, triggers, facts, wallet), how, 0
    from aicad.platform import metering

    def note_call(d: dict[str, Any]) -> None:
        s = sup(d)
        s["calls"] = [c for c in s["calls"] if time.time() - float(c) < 3600] + [round(time.time(), 3)]
    _edit(root, doc["id"], note_call)
    cap = CALL_MAX_TOKENS if god or wallet is None else min(CALL_MAX_TOKENS, wallet)
    hint = rule_plan(doc, triggers, facts, wallet)
    prompt = state_view(doc, triggers, facts, None if god else wallet)
    if hint.get("diagnosis"):
        prompt += ("\n\nThe office's rule-based first reading (it may be wrong): " + hint["diagnosis"]
                   + (" Suggested: " + "; ".join(describe(doc, n) for a in hint["actions"]
                                                  if (n := check(doc, a, facts, wallet)[0]) is not None)
                      if hint["actions"] else ""))
    if feedback is not None:
        prompt += ("\n\nYour previous answer:\n" + feedback[0] + "\n\nThe office checked it before acting and these "
                   "actions could not apply:\n" + "\n".join(f"- {x}" for x in feedback[1]) +
                   "\nCorrect them using the evidence above (other hosts, sizes or a different action) and answer "
                   "again in full. If nothing can clear it, say exactly what the engineer must decide.")
    text, usd = "", None
    try:
        text, usd = await run_supervisor(store.program_dir(root, doc["id"]) / "archie" / "supervisor", prompt,
                                         None if god else cap * metering.USD_PER_TOKEN)
    except Exception:
        log.exception("Archie's supervisor turn failed")
    tokens = min(cap, metering.tokens_for_usd(usd)) if usd else 0
    if tokens or usd is not None:
        o = doc.get("orchestrator") or {}
        charge(root, doc["id"], doc["org_id"], o.get("user_id") or doc.get("created_by"), tokens, god)
    plan = parse_reply(text)
    if plan is None:
        return {**hint, "usd": usd}, "rules", tokens
    return {**plan, "usd": usd, "raw": text}, "ai", tokens  # metered tokens (charged unless God mode bypasses tokens)


def _entry(doc: dict[str, Any], **kw: Any) -> dict[str, Any]:
    s = sup(doc)
    e = {"id": f"SA-{_next_seq(s)}", "at": store.now(), **kw}
    s["log"] = (s["log"] + [e])[-LOG_MAX:]
    return e


async def run_pass(root: Path, pid: str, env: Any = None, *, force: bool = False, now: float | None = None
                   ) -> dict[str, Any]:
    """Watch, diagnose, act, tell. Never two passes on one program at once."""
    if not enabled() and not force:
        return {"ran": False, "why": "off"}
    async with _lock(pid):
        doc = store.load(root, pid)
        if doc is None or not _same_org(root, doc):
            return {"ran": False, "why": "no program"}
        triggers = take_triggers(root, pid, now, force=force)
        if not triggers:
            return {"ran": False, "why": "nothing new"}
        doc = store.load(root, pid) or doc
        if env is None:
            from aicad.office import orchestrator

            try:
                env = orchestrator.make_env(root, doc)
            except Exception:  # noqa: BLE001
                env = None
        facts = await _facts(doc, env, triggers)
        wallet = None if (doc.get("orchestrator") or {}).get("god_tokens") else wallet_left(doc["org_id"])
        plan, how, tokens = await diagnose(root, doc, triggers, facts, wallet)
        for _round in range(FIX_ROUNDS):  # agentic: what the office can't apply goes back to Archie with the reason
            if how != "ai":
                break
            bad = [f"{a.get('tool')}: {why}" for a in plan.get("actions") or []
                   if (why := check(doc, a, facts, wallet)[1]) and check(doc, a, facts, wallet)[0] is None]
            if not bad or calls_last_hour(store.load(root, pid) or doc) >= MAX_CALLS_PER_HOUR:
                break
            plan2, how2, t2 = await diagnose(root, doc, triggers, facts, wallet,
                                             feedback=(str(plan.get("raw") or ""), bad))
            tokens += t2
            if how2 != "ai":
                break
            plan = {**plan2, "usd": (plan.get("usd") or 0) + (plan2.get("usd") or 0)}
        doc = store.load(root, pid) or doc
        done: list[dict[str, Any]] = []
        asked: list[dict[str, Any]] = []
        skipped: list[str] = []
        checked = []
        for a in plan.get("actions") or []:
            norm, why_not = check(doc, a, facts, wallet)
            if norm is None:
                skipped.append(f"{a.get('tool')}: {why_not}")
                continue
            checked.append((a, norm, *classify(doc, norm)))
        if how == "ai" and not any(n["tool"] == "revise_program" for _a, n, _c, _w in checked) and (
                any(x.startswith("revise_program:") for x in skipped)
                or any(x["kind"] in ("blocked", "repeat") and _PLACEMENT.search(str(x.get("text") or ""))
                       for x in triggers)):
            # the model's revision could not be built (or he only described it): the office's own one, when it
            # clears the problem, so the engineer always gets a one-click question, never only words
            for a in rule_plan(doc, triggers, facts, wallet)["actions"]:
                if a["tool"] == "revise_program":
                    norm, why_not = check(doc, a, facts, wallet)
                    if norm is not None:
                        checked.append((a, norm, *classify(doc, norm)))
                        break
        ptok = store.new_id()[:6]
        # alternatives (one problem, several ways to clear it): the engineer picks one, so a group with any major
        # option is asked as a whole
        major_groups = {a["alt"] for a, _n, c, _w in checked if a.get("alt") and c == "major"}
        for a, norm, cls, cls_why in checked:
            if a.get("alt") in major_groups and cls == "minor":
                cls, cls_why = "major", "it is one of several ways to clear the problem: your choice"
            title = describe(doc, norm)
            base = {"tool": norm["tool"], "action": norm, "title": title, "why": norm.get("why") or "",
                    "class": cls, "class_why": cls_why, "cause": plan.get("cause"), "diagnosis": plan.get("diagnosis"),
                    "evidence": plan.get("evidence") or [], "mode": how, "tokens": tokens,
                    "usd": plan.get("usd"),
                    "trigger": [x["kind"] for x in triggers],
                    "ticket": norm.get("ticket") or (norm.get("scope") or {}).get("key")}
            tokens = 0  # one call's tokens are shown once
            plan["usd"] = None
            if cls == "minor":
                try:
                    outcome, undo = await execute(root, pid, norm, env)
                    e = _edit(root, pid, lambda d, b=base, o=outcome, u=undo: _entry(d, **b, status="applied",
                                                                                     outcome=o, undo=u))
                except (OfficeInputError, KeyError) as ex:
                    e = _edit(root, pid, lambda d, b=base, ex=ex: _entry(d, **b, status="failed",
                                                                         outcome=f"Not done: {ex}"))
                done.append(e)
            else:
                if a.get("alt"):
                    base["group"] = f"{ptok}:{a['alt']}"
                e = _edit(root, pid, lambda d, b=base: _entry(d, **b, status="asking",
                                                              outcome="Waiting for your decision"))
                asked.append(e)
            doc = store.load(root, pid) or doc
        if not (done or asked or plan.get("say") or plan.get("diagnosis")):
            return {"ran": True, "mode": how, "actions": 0}
        msg = _tell(root, pid, plan, done, asked, skipped, how)
        return {"ran": True, "mode": how, "done": [e["id"] for e in done], "asked": [e["id"] for e in asked],
                "skipped": skipped, "message": msg["id"] if msg else None, "cause": plan.get("cause")}


def _tell(root: Path, pid: str, plan: dict[str, Any], done: list[dict[str, Any]], asked: list[dict[str, Any]],
          skipped: list[str], how: str) -> dict[str, Any] | None:
    parts = []
    if plan.get("diagnosis"):
        parts.append(plan["diagnosis"])
    if plan.get("say") and plan["say"] not in parts:
        parts.append(plan["say"])
    for e in done:
        if e["status"] == "applied":
            parts.append(f"Done: {e['title']}. {e['outcome']} ({e['why'] or e['class_why']}; a minor step, so I did "
                         "it myself. It is in the Archie log.)")
        else:
            parts.append(f"I tried to {e['title'][0].lower() + e['title'][1:]}, but: {e['outcome']}")
    for x in skipped:
        if x.startswith("revise_program:") and not asked:
            parts.append("I couldn't turn that revision into one the layout can build: " + x.split(":", 1)[1].strip()
                         + ". Tell me what should change and I'll work it out again.")
    if asked:
        grouped = len({e.get("group") for e in asked if e.get("group")}) == 1 and all(e.get("group") for e in asked)             and len(asked) > 1
        parts.append(("These are the ways to clear it; pick one in the question below: " if grouped else
                      "This needs your decision first: ")
                     + "; ".join(f"{e['title']} ({e['class_why']})" for e in asked) + ".")
    if not parts:
        return None
    questions: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = {}
    for e in asked:
        if e.get("group"):
            groups.setdefault(e["group"], []).append(e)
            if len(groups[e["group"]]) > 1:
                continue
        imp = (e.get("action") or {}).get("impact")
        questions.append({"action": e["id"], "question": f"{e['title']}?", "why": e["why"],
                          **({"impact": imp} if imp else {}),
                          "options": [{"id": "approve", "label": "Yes, revise the program" if imp else "Yes, do it"},
                                      {"id": "decline", "label": "No, leave it"}]})
    for es in groups.values():  # alternatives: one question, one choice each (choosing one declines the others)
        if len(es) < 2:
            continue
        q = next(x for x in questions if x["action"] == es[0]["id"])
        q.update(question="Which change should I make?", actions=[e["id"] for e in es],
                 why="; ".join(f"{e['title']}: {e['why'].rstrip('.')}" for e in es if e["why"])[:600] + ".",
                 options=[{"id": "approve", "action": e["id"], "label": e["title"]} for e in es]
                 + [{"id": "decline", "label": "None of these"}])
    msg = archie_chat.post(root, pid, "\n\n".join(parts), [], kind="supervisor", questions=questions,
                           supervisor={"mode": how, "entries": [e["id"] for e in done + asked]})

    def link(d: dict[str, Any]) -> None:
        for e in sup(d)["log"]:
            if e["id"] in {x["id"] for x in done + asked}:
                e["message"] = msg["id"]
        if done or asked:
            service.emit(root, d, "supervisor.pass", "Archie: " + " ".join(parts)[:300], service.agent_actor("archie"),
                         None, done=len(done), asked=len(asked))
    _edit(root, pid, link)
    return msg


# ============================================================================ "Fix with Archie" at the interfaces gate
def gate_plan(doc: dict[str, Any], asked: bool = False) -> dict[str, Any]:
    """What numbers can't fix at the interfaces gate, read deterministically: each blocking problem with why it is
    still open and the plan change that clears it (alternatives grouped: the engineer picks one)."""
    from aicad.office import icd, interfaces, scope

    ic = doc.get("icd") or {}
    sk = doc.get("skeleton") or {}
    items = sk.get("items") or {}
    issues = [x for x in icd.issues(sk, ic.get("interfaces") or []) if x.get("severity", "error") == "error"] \
        if sk else []
    acts: list[dict[str, Any]] = []
    open_: list[str] = []
    named, excluded = scope.mentions(str(doc.get("brief") or ""))
    housing_ok = not ({"housing", "plate", "support"} & excluded) and not (
        scope.exclusive(str(doc.get("brief") or "")) and not ({"housing", "plate", "support"} & named))
    subs = [s["name"] for s in (doc.get("plan") or {}).get("subassemblies") or []]
    from aicad.office.visual_office import BASE_PART, HOUSING_PART

    loose = interfaces.unconnected(doc)
    if loose:
        names = [items[i]["name"] for i in loose if i in items]
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        open_.append(f"{listed}: no interface connects {'it' if len(names) == 1 else 'them'}, and no number change "
                     "can make one; it is a decision about the plan")
        acts.append({"tool": "keep_separate", "parts": names, "alt": "loose",
                     "why": "Kept apart on purpose (a kit, or parts made on their own); recorded at the gate."})
        if _plan_editable(doc) and len(names) == 1 and len(_plan_parts(doc)) > 1:
            acts.append({"tool": "remove_part", "part": names[0], "alt": "loose",
                         "why": "Not needed in this program: the plan goes on without it."})
    codes = {x["code"] for x in issues}
    if "shaft_support" in codes and _plan_editable(doc):
        shafts = sum(1 for it in items.values() if it.get("role") == "shaft")
        bearing = next((p for _s, p in _plan_parts(doc) if re.search(r"bearing", p["name"], re.IGNORECASE)), None)
        why_open = ("a shaft runs in fewer than two bearings and nothing else carries it; that is a part count, not a "
                    "number on an interface")
        open_.append(why_open)
        if bearing is not None:
            acts.append({"tool": "set_qty", "part": bearing["name"], "qty": max(2, 2 * max(1, shafts)), "alt": "support",
                         "why": "Two bearings per shaft, one either side of what it carries."})
        if housing_ok and subs:
            acts.append({"tool": "add_part", "sub": subs[0], "part": dict(HOUSING_PART), "alt": "support",
                         "why": "A housing carries the shaft on its bearings."})
        if bearing is not None and not housing_ok:
            acts.append({"tool": "remove_part", "part": bearing["name"], "alt": "support",
                         "why": "No bearings: the shaft with what it carries is delivered as a sub-assembly."})
    if codes & {"row_layout", "no_mount", "no_host"} and _plan_editable(doc):
        open_.append("the parts have nothing to mount on, so the layout puts them side by side; that needs a part, "
                     "not a number")
        if housing_ok and subs:
            acts.append({"tool": "add_part", "sub": subs[0], "part": dict(HOUSING_PART), "alt": "mount",
                         "why": "A housing carries the shafts on their bearings."})
            acts.append({"tool": "add_part", "sub": subs[0], "part": dict(BASE_PART), "alt": "mount",
                         "why": "A base plate with bearing supports."})
    for x in issues:
        if x["code"] in ("no_interface", "shaft_support", "row_layout", "no_mount", "no_host"):
            continue
        open_.append(f"{x['text']} (no safe number change clears it: change the plan, or edit the interface it names)")
    if not issues and ic.get("problems"):
        open_ += [str(p) for p in ic["problems"][:4]]
    diag = ("Numbers alone can't clear the interfaces: " + "; ".join(open_[:5]) + "." if open_ else
            "The interfaces have no problem left.")
    says = []
    if open_ and not acts:
        says.append("I have no safe change to propose for these: tell me in the chat what the parts should do, or "
                    "edit the interface the problem names.")
    return {"cause": "plan" if acts else "interfaces", "diagnosis": diag, "actions": acts[:MAX_ACTIONS],
            "says": says, "open": open_}


async def fix_gate(root: Path, pid: str, actor: dict[str, Any], env: Any = None) -> dict[str, Any]:
    """The interfaces gate's "Fix with Archie": (1) the free number fix (``interfaces.fix``, no AI); (2) when problems
    remain and the supervisor is on, Archie diagnoses them and acts (minor: applied; major: asked in the chat with
    clickable choices); (3) a plain account of what was fixed, what he did or proposes and what is still open."""
    from aicad.office import interfaces

    steps = _edit(root, pid, lambda d: interfaces.fix(root, d, actor))
    out: dict[str, Any] = {"steps": steps["steps"], "problems": steps["problems"]}
    if not steps["problems"]:
        return out
    if not enabled():
        out["archie"] = {"ran": False, "open": gate_plan(store.load(root, pid) or {})["open"]}
        return out

    def trig(d: dict[str, Any]) -> None:
        s = sup(d)
        s["pending"] = (s["pending"] + [{"kind": "gate", "ticket": None, "asked": True, "at": round(time.time(), 3),
                                         "text": f"the engineer asked Archie to fix: {d['icd']['problems'][0]}"}])
    _edit(root, pid, trig)
    res = await run_pass(root, pid, env, force=True)
    doc = store.load(root, pid) or {}
    log_ = {e["id"]: e for e in (doc.get("supervisor") or {}).get("log") or []}
    out["problems"] = list((doc.get("icd") or {}).get("problems") or [])
    out["archie"] = {"ran": bool(res.get("ran")), "mode": res.get("mode"),
                     "done": [log_[i]["title"] for i in res.get("done") or [] if log_.get(i, {}).get("status") == "applied"],
                     "asked": [log_[i]["title"] for i in res.get("asked") or [] if i in log_],
                     "open": gate_plan(doc)["open"] if out["problems"] else []}
    return out


# ============================================================================ the engineer's answer, undo
async def decide(root: Path, pid: str, aid: str, choice: str, actor: dict[str, Any], env: Any = None
                 ) -> dict[str, Any]:
    """The engineer answers Archie's question on a major action: approve (re-checked against the program now, then
    applied) or decline."""
    if choice not in ("approve", "decline"):
        raise OfficeInputError("Approve or decline.")
    async with _lock(pid):
        doc = store.load(root, pid)
        if doc is None or not _same_org(root, doc):
            raise OfficeInputError("Program not found")
        e = next((x for x in sup(doc)["log"] if x["id"] == aid), None)
        if e is None:
            raise OfficeInputError("That action is not in Archie's log.")
        if e["status"] != "asking":
            raise OfficeInputError("That question was already answered.")
        status, outcome, undo = "declined", f"Declined by {actor.get('name', 'the engineer')}", None
        if choice == "approve":
            facts = await _facts(doc, env, [{"ticket": (archie_chat.find_ticket(doc, e.get("ticket") or "") or {}).get("id")}])
            wallet = None if (doc.get("orchestrator") or {}).get("god_tokens") else wallet_left(doc["org_id"])
            norm, why_not = check(doc, {k: v for k, v in e["action"].items()
                                        if k not in ("before", "concurrency_before", "icd_status", "builds_at", "scope",
                                                     "expiry", "items")} | _reask(e["action"]), facts, wallet)
            if norm is None:
                status, outcome = "lapsed", f"No longer applies: {why_not}"
            else:
                try:
                    outcome, undo = await execute(root, pid, norm, env, approved_by=actor)
                    status = "applied"
                except (OfficeInputError, KeyError) as ex:
                    status, outcome = "failed", f"Not done: {ex}"

        def fn(d: dict[str, Any]) -> dict[str, Any]:
            x = next(y for y in sup(d)["log"] if y["id"] == aid)
            x.update(status=status, outcome=outcome, undo=undo, decided={"by": actor.get("name"), "at": store.now(),
                                                                         "choice": choice})
            service.emit(root, d, f"supervisor.{status}", f"{actor.get('name', 'Someone')} "
                         f"{'approved' if choice == 'approve' else 'declined'} Archie's proposal: {x['title']}. "
                         f"{outcome}", actor, None, action=aid)
            if x.get("group"):  # alternatives: the others are settled by this answer
                for y in sup(d)["log"]:
                    if y.get("group") == x["group"] and y["id"] != aid and y["status"] == "asking":
                        y.update(status="declined", outcome="You chose another option" if choice == "approve"
                                 else f"Declined by {actor.get('name', 'the engineer')}",
                                 decided={"by": actor.get("name"), "at": store.now(), "choice": "decline"})
            return x
        x = _edit(root, pid, fn)
    _answer_question(root, pid, aid, choice, actor)
    return x


def _reask(a: dict[str, Any]) -> dict[str, Any]:
    """A stored (normalised) action in the shape ``check`` takes, so a yes re-checks it against the program now."""
    out: dict[str, Any] = {}
    sc = a.get("scope") or {}
    if sc.get("kind") == "ticket":
        out["ticket"] = sc.get("key") or sc.get("ticket")
    elif sc.get("kind") == "interface":
        out["interface"] = sc.get("interface")
    elif sc.get("kind") == "program":
        out["scope"] = "program"
    ex = a.get("expiry") or {}
    if ex:
        out["expiry"] = "rebuild" if ex.get("kind") == "rebuild" else int(ex.get("n") or 1)
    return out


def _answer_question(root: Path, pid: str, aid: str, choice: str, actor: dict[str, Any]) -> None:
    with archie_chat.chat_lock(pid):
        hist = archie_chat.history(root, pid)
        for m in hist:
            for q in m.get("questions") or []:
                if q.get("action") == aid or aid in (q.get("actions") or []):
                    q.update(answered=choice, chosen=aid if choice == "approve" else None, by=actor, at=store.now())
        archie_chat.save_history(root, pid, hist)


def undoable(doc: dict[str, Any], e: dict[str, Any]) -> str | None:
    """None when the action can be undone now, else why not."""
    if e.get("status") != "applied":
        return "only an applied action can be undone"
    u = e.get("undo") or {}
    k = u.get("kind")
    if not k:
        return "this step can't be reversed (a retry, an instruction or an approval stays done)"
    if k == "override":
        o = next((x for x in (doc.get("supervisor") or {}).get("overrides") or [] if x["id"] == u["id"]), None)
        return None if o is not None and o.get("status") in ("active", "expired") else "already ended"
    if k == "budget":
        return None
    if k in ("reassign", "resume", "brief"):
        t = next((x for x in doc["tickets"] if x["id"] == u["ticket"]), None)
        if t is None:
            return "the ticket is gone"
        if k == "brief" and int((t.get("run") or {}).get("turns") or 0) != int(u.get("turns") or 0):
            return "the designer has already worked on the changed brief"
        if k == "reassign" and (t.get("run") or {}).get("status") in ("designing", "reviewing"):
            return "the new designer is working on it"
        return None
    if k == "plan":
        if u.get("stage") == "plan_review":
            return None if doc.get("status") == "plan_review" else "the plan was approved since"
        return None if archie_chat.can_revise(doc) else "part work has started on the new plan"
    if k in ("separate", "resize", "interface"):
        return None if (doc.get("icd") or {}).get("status") == "draft" else "the interfaces were approved since"
    if k == "revision":
        from aicad.office import revision

        return revision.undoable(doc, u["id"])
    return "this step can't be reversed"


def undo(root: Path, pid: str, aid: str, actor: dict[str, Any]) -> dict[str, Any]:
    """Reverse an applied action where it can be reversed (rule overrides, plan edits not yet built, budget,
    reassignment, keep-separate and draft-interface edits)."""
    from aicad.office import interfaces, orchestrator

    def fn(d: dict[str, Any]) -> dict[str, Any]:
        if not _same_org(root, d):
            raise OfficeInputError("Program not found")
        e = next((x for x in sup(d)["log"] if x["id"] == aid), None)
        if e is None:
            raise OfficeInputError("That action is not in Archie's log.")
        why = undoable(d, e)
        if why:
            raise OfficeInputError(f"It can't be undone: {why}.")
        u = e["undo"]
        k = u["kind"]
        who = actor.get("name", "Someone")
        res = ""
        if k == "override":
            o = next(x for x in sup(d)["overrides"] if x["id"] == u["id"])
            o["status"] = "undone"
            o["ended"] = {"at": store.now(), "why": f"undone by {who}"}
            back = []
            kept = []
            for t in d["tickets"]:
                hit = [r for r in t.get("relaxed") or [] if r.get("override") == o["id"] and not r.get("undone")]
                if not hit:
                    continue
                if t["column"] == "integrated":  # already in the assembly: stays listed as relaxed, never re-checked
                    for r in hit:
                        r["undone"] = True
                    kept.append(t["key"])
                    continue
                t["relaxed"] = [r for r in t["relaxed"] if r.get("override") != o["id"]]
                busy = (t.get("run") or {}).get("status") in orchestrator.ACTIVE
                if not busy and not t.get("taken_over"):
                    orchestrator.close_wait(t)
                    if t["column"] != "in_review":
                        service.move(root, d, t["id"], "in_review", actor)
                    orchestrator._set_run(t, status="queued", next=RULES[o["rule"]]["next"], attempt=0, blocked=None,
                                          line=f"{who} undid Archie's relaxation: back to Gage")
                    back.append(t["key"])
            res = (f"The rule applies again{': ' + ', '.join(back) + ' went back to Gage' if back else ''}."
                   + (f" {', '.join(kept)} {'is' if len(kept) == 1 else 'are'} already integrated: reopen "
                      f"{'it' if len(kept) == 1 else 'them'} so Gage measures again; until then the check stays "
                      "listed as relaxed, not passed." if kept else ""))
        elif k == "budget":
            if "tokens" in u:
                d["budget"]["tokens"] = u["tokens"]
            if "concurrency" in u:
                d["concurrency"] = u["concurrency"]
            res = "The previous budget is back."
        elif k == "reassign":
            service.update(root, d, u["ticket"], actor, specialist=u["to"])
            res = "Back with its first designer."
        elif k == "resume":
            orchestrator.control(root, d, u["ticket"], "resume", actor)
            res = "Resumed."
        elif k == "brief":
            t = service.ticket(d, u["ticket"])
            t["brief"] = u["brief"]
            res = "The brief is as it was."
        elif k == "plan":
            if u["stage"] == "plan_review":
                d["plan"] = u["plan"]
            else:
                service.revise_plan(root, d, {"notes": f"{who} undid Archie's plan change", "plan": u["plan"]}, actor)
                service.approve_plan(root, d, None, actor)
            res = "The plan is as it was."
        elif k == "separate":
            interfaces.keep_separate(root, d, u["items"], False, actor)
            res = "The parts block the interfaces again until they are connected or kept separate."
        elif k == "resize":
            item = d["skeleton"]["items"].get(u["item"])
            if item is None:
                raise OfficeInputError("The part is no longer in the layout.")
            if u.get("before"):
                interfaces.resize(root, d, u["item"], u["before"], actor)
            else:  # back to the plan's own size: drop the override
                ic = d["icd"]
                ov = copy.deepcopy(ic["overrides"])
                (ov.get("items") or {}).pop(u["item"], None)
                sk2, ifs2 = interfaces._rebuild(d, ov)
                from aicad.office import icd

                d["skeleton"], ic["interfaces"], ic["overrides"], ic["problems"] = sk2, ifs2, ov, icd.problems(sk2, ifs2)
            res = "The part has its earlier size."
        elif k == "interface":
            interfaces.edit(root, d, u["interface"], u["values"], actor)
            res = "The interface has its earlier numbers."
        elif k == "revision":
            from aicad.office import revision

            rv = revision.undo(root, d, u["id"], actor)
            res = f"The program is back at ICD v{rv['icd_from']}, with the plan and the tickets as they were."
        e.update(status="undone", undone={"by": who, "at": store.now(), "outcome": res})
        service.emit(root, d, "supervisor.undone", f"{who} undid Archie's action: {e['title']}. {res}", actor, None,
                     action=aid)
        return e
    e = _edit(root, pid, fn)
    if (e.get("undo") or {}).get("kind") == "revision":
        from aicad.office import revision

        revision.spawn_rebuild(root, pid)
    _wake(root, pid)
    return e


# ============================================================================ the view (program page, Archie tab)
def view(doc: dict[str, Any]) -> dict[str, Any]:
    s = doc.get("supervisor") or {}
    log_ = []
    for e in reversed(s.get("log") or []):
        why = undoable(doc, e) if e.get("status") == "applied" else "n/a"
        log_.append({k: v for k, v in e.items() if k not in ("action", "undo")} | {
            "undoable": why is None, "undo_why": None if why in (None, "n/a") else why,
            "impact": (e.get("action") or {}).get("impact")})
    ovs = []
    for o in reversed(s.get("overrides") or []):
        ovs.append({**{k: v for k, v in o.items() if k not in ("builds",)}, "scope_text": _scope_text(doc, o),
                    "feature_text": feature_text(o.get("feature")) if o.get("feature") else None,
                    "expiry_text": _expiry_text(o.get("expiry"), o["rule"]) if o.get("rule") in RULES else "",
                    "measures": bool(RULES.get(o.get("rule"), {}).get("measures")),
                    "action": next((e["id"] for e in s.get("log") or [] if (e.get("undo") or {}).get("id") == o["id"]),
                                   None)})
    return {"enabled": enabled(), "log": log_, "overrides": ovs, "calls_hour": calls_last_hour(doc),
            "max_calls_hour": MAX_CALLS_PER_HOUR, "asking": sum(1 for e in s.get("log") or [] if e["status"] == "asking"),
            "relaxed": relaxed_summary(doc)}


# ============================================================================ the runner hook and the heartbeat
def tick(root: Path, pid: str, env: Any = None, now: float | None = None) -> None:
    """Called by the program's runner on every tick: a pass when something was recorded, else a heartbeat."""
    if not enabled():
        return
    now = time.time() if now is None else now
    if _flags.pop(pid, None) is not None:
        kick(root, pid, env)
        return
    last = _last_beat.setdefault(pid, now)
    if now - last >= HEARTBEAT_S:
        _last_beat[pid] = now
        kick(root, pid, env)


def kick(root: Path, pid: str, env: Any = None) -> asyncio.Task[Any] | None:
    """Start a debounced pass (or ask the running one to go again afterwards)."""
    if not enabled():
        return None
    t = _running.get(pid)
    if t is not None and not t.done():
        _again.add(pid)
        return t
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    task = loop.create_task(_loop(root, pid, env))
    _running[pid] = task

    def done(tk: asyncio.Task[Any]) -> None:
        if _running.get(pid) is tk:
            _running.pop(pid, None)
    task.add_done_callback(done)
    return task


async def _loop(root: Path, pid: str, env: Any) -> None:
    while True:
        await asyncio.sleep(DEBOUNCE_S)
        _again.discard(pid)
        try:
            await run_pass(root, pid, env)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("supervisor pass failed")
        if pid not in _again:
            return


def heartbeat_all(data_dir: Path) -> int:
    """Kick a look at every program that waits without a runner (the interfaces gate, a stopped office)."""
    from aicad.office import orchestrator

    base = Path(data_dir) / "office"
    n = 0
    if not enabled() or not base.is_dir():
        return 0
    for org in base.iterdir():
        if not org.is_dir():
            continue
        for doc in store.list_docs(org.resolve()):
            if doc.get("status") not in ("active", "plan_review") or orchestrator.runner(doc["id"]) is not None:
                continue
            if time.time() - _ts(doc.get("updated_at")) > 7 * 86400:
                continue
            if kick(org.resolve(), doc["id"]) is not None:
                n += 1
    return n


async def heartbeat_loop(data_dir: Path) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_S)
        try:
            heartbeat_all(data_dir)
        except Exception:
            log.exception("supervisor heartbeat failed")
