"""Design Office estimating: every constant in one documented place, plus progress, roll-up and ETA maths.

Plan §2.5. All functions are pure, so the board, the tree and the tests use the same arithmetic.

Estimate per ticket
    estimate_min = complexity x MINUTES_PER_UNIT[family]
    complexity is 1 (trivial) .. 5 (very complex), set by Archie from the brief (feature count, family, tolerance
    class) and editable by the user in plan review. MINUTES_PER_UNIT are starting values from measured design-agent
    runs (a new prismatic part: about 1-4 minutes of agent time warm, longer cold; see platform/metering.py). CD-015
    recalibrates them from completed tickets; until then they are labelled estimates everywhere.

Progress per ticket (milestones, never a timer)
    brief read 5 % . first build 35 % . gating checks pass 70 % . self-review 85 % . approved 100 %
    Progress is the weight of the furthest milestone reached.

Roll-up (effort-weighted)
    progress(node) = sum(estimate_i x progress_i) / sum(estimate_i) over every ticket in the node's subtree,
    including the node's own integration ticket (integration effort counts at each assembly level).

ETA range (remaining agent time, a range, never a promise)
    W  = remaining effort in the subtree, sum(estimate_i x (100 - progress_i) / 100)
    CP = remaining critical path: a sub-assembly's integration waits for all of its children
    N  = concurrency (agents working in parallel, default 3, PD-36)
    low  = ETA_LOW_FACTOR  x max(CP, W / N)    (perfect packing: no schedule beats this bound)
    high = ETA_HIGH_FACTOR x (CP + W / N)      (Graham's bound for any greedy schedule)
    The factors widen the range for estimate error until calibration (CD-015) narrows it.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

# --------------------------------------------------------------------------- constants (the only place)
MINUTES_PER_UNIT: dict[str, float] = {
    "machined": 4.0,     # prismatic part: sketch, pockets, holes, checks
    "turned": 3.5,       # revolved profile, grooves, keyways
    "gear": 4.0,         # tooth form, hub, bore, key
    "sheet": 4.5,        # flanges and bends modelled as solids until sheet-metal tools land (CAD-026)
    "plastic": 5.0,      # shells, bosses, ribs, draft
    "standard": 0.5,     # Toolbox lookup: deterministic, almost free
    "integration": 3.0,  # place, mate and interference-check one assembly level
    "drawings": 0.5,     # Ortho: deterministic sheets (per complexity unit = about two parts)
    "dfm": 0.5,          # Smithy: deterministic DFM screening (per complexity unit = about two parts)
}
COMPLEXITY_MIN, COMPLEXITY_MAX = 1, 5
DEFAULT_CONCURRENCY = 3  # PD-36
MAX_CONCURRENCY = 12
ETA_LOW_FACTOR = 0.8
ETA_HIGH_FACTOR = 1.3

MILESTONES: list[tuple[str, str, int]] = [
    ("brief_read", "Brief read", 5),
    ("first_build", "First build", 35),
    ("gates_pass", "Gating checks pass", 70),
    ("self_review", "Self-review", 85),
    ("approved", "Approved", 100),
]
MILESTONE_WEIGHT = {code: w for code, _label, w in MILESTONES}


# --------------------------------------------------------------------------- per ticket
def clamp_complexity(v: Any) -> int:
    try:
        c = round(float(v))
    except (TypeError, ValueError):
        c = 2
    return max(COMPLEXITY_MIN, min(COMPLEXITY_MAX, c))


def estimate_minutes(family: str, complexity: int, rates: dict[str, float] | None = None) -> float:
    """complexity x minutes per unit (the calibrated ``rates`` when given, else the starting constants)."""
    r = rates or MINUTES_PER_UNIT
    rate = r.get(family, MINUTES_PER_UNIT.get(family, MINUTES_PER_UNIT["machined"]))
    return round(clamp_complexity(complexity) * float(rate), 2)


def integration_complexity(children: int) -> int:
    """One complexity unit per three items to place and mate at this level (1..5)."""
    return clamp_complexity(max(1, math.ceil(children / 3)))


def progress_of(milestones: Iterable[str]) -> int:
    return max((MILESTONE_WEIGHT.get(m, 0) for m in milestones), default=0)


def remaining_min(ticket: dict[str, Any]) -> float:
    return float(ticket["estimate_min"]) * (100 - int(ticket["progress"])) / 100.0


# --------------------------------------------------------------------------- tree helpers
def _children(items: list[dict[str, Any]]) -> dict[str | None, list[str]]:
    out: dict[str | None, list[str]] = {}
    for it in items:
        out.setdefault(it.get("parent_id"), []).append(it["id"])
    return out


def _by_item(tickets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for t in tickets:
        out.setdefault(t["item_id"], []).append(t)
    return out


def subtree(items: list[dict[str, Any]], item_id: str) -> list[str]:
    kids = _children(items)
    out, stack = [], [item_id]
    while stack:
        i = stack.pop()
        out.append(i)
        stack.extend(kids.get(i, []))
    return out


# --------------------------------------------------------------------------- roll-up
def rollup(items: list[dict[str, Any]], tickets: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Effort-weighted progress for every item (its whole subtree, own integration ticket included)."""
    by_item = _by_item(tickets)
    out: dict[str, dict[str, float]] = {}
    for it in items:
        est = done = 0.0
        for i in subtree(items, it["id"]):
            for t in by_item.get(i, []):
                est += float(t["estimate_min"])
                done += float(t["estimate_min"]) * int(t["progress"]) / 100.0
        out[it["id"]] = {"estimate_min": round(est, 2), "done_min": round(done, 2),
                         "remaining_min": round(est - done, 2),
                         "progress": round(100.0 * done / est, 1) if est > 0 else 0.0}
    return out


def critical_path(items: list[dict[str, Any]], tickets: list[dict[str, Any]], item_id: str) -> float:
    """Longest chain of remaining work ending at this item: its own tickets after the slowest child."""
    kids = _children(items)
    by_item = _by_item(tickets)

    def cp(i: str) -> float:
        own = sum(remaining_min(t) for t in by_item.get(i, []))
        return own + max((cp(c) for c in kids.get(i, [])), default=0.0)

    return round(cp(item_id), 2)


def eta(items: list[dict[str, Any]], tickets: list[dict[str, Any]], item_id: str,
        concurrency: int = DEFAULT_CONCURRENCY) -> dict[str, float]:
    n = max(1, min(MAX_CONCURRENCY, int(concurrency or DEFAULT_CONCURRENCY)))
    ids = set(subtree(items, item_id))
    w = sum(remaining_min(t) for t in tickets if t["item_id"] in ids)
    cp = critical_path(items, tickets, item_id)
    return {"remaining_min": round(w, 2), "critical_path_min": cp, "concurrency": n,
            "low_min": round(ETA_LOW_FACTOR * max(cp, w / n), 1),
            "high_min": round(ETA_HIGH_FACTOR * (cp + w / n), 1)}


def constants(rates: dict[str, float] | None = None) -> dict[str, Any]:
    """What the client needs to preview estimates while the user edits a plan (same numbers as the server)."""
    return {"minutes_per_unit": {**MINUTES_PER_UNIT, **(rates or {})}, "complexity": [COMPLEXITY_MIN, COMPLEXITY_MAX],
            "milestones": [{"code": c, "label": lbl, "weight": w} for c, lbl, w in MILESTONES],
            "default_concurrency": DEFAULT_CONCURRENCY, "eta_factors": [ETA_LOW_FACTOR, ETA_HIGH_FACTOR]}
