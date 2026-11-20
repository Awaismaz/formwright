"""Design Office estimating: every constant in one documented place, plus progress, roll-up and ETA maths.

Plan §2.5. All functions are pure, so the board, the tree and the tests use the same arithmetic.

Estimate per ticket: a range from the part's build path (office-polish2, PD-190)
    A part is built one of four ways, and the estimate follows the way it will be built:
      toolbox   Hex takes a standard part from the Toolbox: 1 to 6 s.
      direct    the interfaces fix the part and a generator builds it with no AI: 3 to 9 s per part
                (office-direct report: Pinion 8.4 s, Gear 9.1 s, Output shaft 3.5 s; Gage 0.9 to 2.5 s).
      template  a workspace part template bound to the ICD, then built and checked: 6 to 21 s.
      agent     the AI designer: complexity x MINUTES_PER_UNIT[family], shown as 0.6x to 1.5x of that. The rates are
                calibrated on measured turns: 60 to 100 s per design turn on Sonnet or Opus (agent-cost: 61 s a cold
                turn; live gear run: 70 to 125 s), plus Gage's notes (11 to 19 s); a complexity-2 part is one or two
                turns, about 1.4 to 3.6 min.
    Before the interfaces exist the path is predicted from the part (``predict_path``); at ICD approval each
    designed part gets the path the direct builder actually decides (``interfaces.approve``). The ticket keeps
    ``estimate_lo`` / ``estimate_hi`` and ``estimate_min`` (their midpoint, used by roll-up and progress).
    complexity is 1 (trivial) .. 5 (very complex), set by Archie from the brief and editable in plan review. CD-015
    recalibrates the AI designer's rates from completed tickets (direct builds are never samples).

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
    Per-agent threads (CD-027, PD-66): an agent with k threads works at most k of its tickets at once. With
    W_a = that agent's remaining effort, its lane takes at least L = max_a W_a / min(k_a, N); when every agent
    with work has a thread count, N is also capped at the sum of their threads.
    low  = ETA_LOW_FACTOR  x max(CP, W / N, L)    (perfect packing: no schedule beats this bound), on the low ends
    high = ETA_HIGH_FACTOR x (CP + max(W / N, L)) (greedy-schedule bound), on the high ends
    The factors widen the range for estimate error until calibration (CD-015) narrows it.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

# --------------------------------------------------------------------------- constants (the only place)
MINUTES_PER_UNIT: dict[str, float] = {  # the AI designer's minutes per complexity unit (measured, see above)
    "machined": 1.2,     # prismatic part: sketch, pockets, holes, checks
    "turned": 1.1,       # revolved profile, grooves, keyways
    "gear": 1.2,         # tooth form, hub, bore, key
    "sheet": 1.4,        # flanges and bends
    "plastic": 1.5,      # shells, bosses, ribs, draft
    "standard": 0.05,    # Toolbox lookup: deterministic, seconds
    "integration": 0.25, # Fitz places from the ICD and looks (deterministic, plus the visual check): 15 s a unit
    "drawings": 0.1,     # Ortho: deterministic sheets (per complexity unit = about two parts)
    "dfm": 0.1,          # Smithy: deterministic DFM screening (per complexity unit = about two parts)
}
# minutes per part on the paths with no AI turn (low, high)
PATH_MINUTES: dict[str, tuple[float, float]] = {
    "toolbox": (0.02, 0.1),    # 1 to 6 s
    "direct": (0.05, 0.15),    # 3 to 9 s (office-direct report)
    "template": (0.1, 0.35),   # 6 to 21 s: bind, build, check
}
PATHS = ("toolbox", "direct", "template", "agent")
AGENT_SPREAD = (0.6, 1.5)  # the AI designer's range around complexity x rate (one turn or a few)
PATH_LABEL = {"toolbox": "Toolbox", "direct": "Built from the interfaces", "template": "Workspace template",
              "agent": "AI designer"}
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


_DIRECT_TURNED = re.compile(r"\b(shaft|spindle|axle|spacer|collar|hub|pulley|sheave|sprocket|coupling|bush(?:ing)?|"
                            r"sleeve|ring|roller|drum|wheel|disc|disk|flange|cap)s?\b", re.IGNORECASE)
_DIRECT_BLOCK = re.compile(r"\b(plate|bracket|housing|cover|lid|cap|base|block|mount|frame|pillow|support|clevis|"
                           r"angle|panel)s?\b", re.IGNORECASE)
_NOT_SPUR = re.compile(r"\b(worm|bevel|helical|herringbone|rack|planet\w*|internal|ring gear)\b", re.IGNORECASE)


def predict_path(family: str, name: str = "", description: str = "", direct_on: bool = True) -> str:
    """The build path a part will most likely take, before its interfaces exist (plan review): standard parts come
    from the Toolbox; the families the generators build from the interfaces (shafts, turned hubs and caps, spur gears,
    plates, brackets, housings and covers) are built directly; the rest go to the AI designer. At ICD approval the
    direct builder's own decision replaces the prediction."""
    if family == "standard":
        return "toolbox"
    if not direct_on or family in ("sheet", "plastic", "integration", "drawings", "dfm"):
        return "agent"
    text = f"{name} {description}"
    if family == "gear":
        return "agent" if _NOT_SPUR.search(text) else "direct"
    if family == "turned" and _DIRECT_TURNED.search(name):
        return "direct"
    if family == "machined" and _DIRECT_BLOCK.search(name):
        return "direct"
    return "agent"


def estimate_range(family: str, complexity: int, path: str | None = None,
                   rates: dict[str, float] | None = None) -> tuple[float, float]:
    """(low, high) minutes for one ticket on its build path (``PATH_MINUTES``; the AI designer and the assembly,
    drawing and DFM steps: complexity x rate, ``AGENT_SPREAD`` around it)."""
    if path in PATH_MINUTES:
        lo, hi = PATH_MINUTES[str(path)]
        return lo, hi
    mid = estimate_minutes(family, complexity, rates)
    return round(AGENT_SPREAD[0] * mid, 3), round(AGENT_SPREAD[1] * mid, 3)


def apply_estimate(t: dict[str, Any], path: str | None, rates: dict[str, float] | None = None) -> dict[str, Any]:
    """Set a ticket's estimate from its build path: ``estimate_lo``, ``estimate_hi``, ``estimate_min`` (midpoint) and
    ``estimate_path``. Returns the ticket."""
    lo, hi = estimate_range(t["family"], int(t.get("complexity") or 1), path, rates)
    t["estimate_lo"], t["estimate_hi"] = lo, hi
    t["estimate_min"] = round((lo + hi) / 2, 3)
    if path:
        t["estimate_path"] = path
    else:
        t.pop("estimate_path", None)
    return t


def integration_complexity(children: int) -> int:
    """One complexity unit per three items to place and mate at this level (1..5)."""
    return clamp_complexity(max(1, math.ceil(children / 3)))


def progress_of(milestones: Iterable[str]) -> int:
    return max((MILESTONE_WEIGHT.get(m, 0) for m in milestones), default=0)


def remaining_min(ticket: dict[str, Any], end: str = "min") -> float:
    """The ticket's remaining effort; ``end`` "lo" / "hi" reads the low / high end of its range (tickets from before
    ranges have only ``estimate_min``)."""
    est = ticket.get(f"estimate_{end}") if end != "min" else None
    return float(ticket["estimate_min"] if est is None else est) * (100 - int(ticket["progress"])) / 100.0


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


def critical_path(items: list[dict[str, Any]], tickets: list[dict[str, Any]], item_id: str, end: str = "min") -> float:
    """Longest chain of remaining work ending at this item: its own tickets after the slowest child."""
    kids = _children(items)
    by_item = _by_item(tickets)

    def cp(i: str) -> float:
        own = sum(remaining_min(t, end) for t in by_item.get(i, []))
        return own + max((cp(c) for c in kids.get(i, [])), default=0.0)

    return round(cp(item_id), 2)


def clean_threads(raw: Any) -> dict[str, int]:
    """{agent code: threads 1..MAX_CONCURRENCY}; anything else is dropped (codes are checked by the caller)."""
    out: dict[str, int] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = max(1, min(MAX_CONCURRENCY, int(v)))
    return out


def lanes(tickets: Iterable[dict[str, Any]], threads: dict[str, int] | None, n: int, end: str = "min"
          ) -> tuple[int, float]:
    """(effective concurrency, slowest agent lane in minutes) for the remaining work of ``tickets``. An agent's
    lane is its tickets' remaining effort over its threads; agents without a thread count share the pool."""
    per: dict[str, float] = {}
    for t in tickets:
        w = remaining_min(t, end)
        if w > 0:
            per[t.get("specialist") or ""] = per.get(t.get("specialist") or "", 0.0) + w
    if not threads:
        return n, 0.0
    bound, cap, pooled = 0.0, 0, False
    for code, w in per.items():
        k = threads.get(code)
        if k:
            bound = max(bound, w / min(k, n))
            cap += min(k, n)
        else:
            pooled = True
    return (n if pooled or not per else max(1, min(n, cap))), bound


def eta(items: list[dict[str, Any]], tickets: list[dict[str, Any]], item_id: str,
        concurrency: int = DEFAULT_CONCURRENCY, threads: dict[str, int] | None = None) -> dict[str, float]:
    n = max(1, min(MAX_CONCURRENCY, int(concurrency or DEFAULT_CONCURRENCY)))
    ids = set(subtree(items, item_id))
    mine = [t for t in tickets if t["item_id"] in ids]
    w = sum(remaining_min(t) for t in mine)
    cp = critical_path(items, tickets, item_id)
    wl, wh = sum(remaining_min(t, "lo") for t in mine), sum(remaining_min(t, "hi") for t in mine)
    cpl, cph = critical_path(items, tickets, item_id, "lo"), critical_path(items, tickets, item_id, "hi")
    nl, lane_l = lanes(mine, threads, n, "lo")
    nh, lane_h = lanes(mine, threads, n, "hi")
    return {"remaining_min": round(w, 2), "critical_path_min": cp, "concurrency": n,
            "remaining_lo_min": round(wl, 2), "remaining_hi_min": round(wh, 2),
            "low_min": round(ETA_LOW_FACTOR * max(cpl, wl / nl, lane_l), 1),
            "high_min": round(ETA_HIGH_FACTOR * (cph + max(wh / nh, lane_h)), 1)}


def constants(rates: dict[str, float] | None = None) -> dict[str, Any]:
    """What the client needs to preview estimates while the user edits a plan (same numbers as the server)."""
    return {"minutes_per_unit": {**MINUTES_PER_UNIT, **(rates or {})}, "complexity": [COMPLEXITY_MIN, COMPLEXITY_MAX],
            "path_minutes": {k: list(v) for k, v in PATH_MINUTES.items()}, "agent_spread": list(AGENT_SPREAD),
            "path_labels": PATH_LABEL,
            "milestones": [{"code": c, "label": lbl, "weight": w} for c, lbl, w in MILESTONES],
            "default_concurrency": DEFAULT_CONCURRENCY, "eta_factors": [ETA_LOW_FACTOR, ETA_HIGH_FACTOR]}
