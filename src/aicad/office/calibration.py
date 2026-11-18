"""Estimate calibration (CD-015): the minutes-per-complexity constants learn from finished tickets.

Every ticket the office finishes records its actual agent time (the sum of its work segments: design turns, Gage
rounds, Fitz's fitting and clash rounds, Hex's search, Ortho's and Smithy's deliverables). Its family's rate then
moves towards what was observed, with a bounded, explainable update:

    observed = actual_min / complexity                        (minutes per complexity unit on this ticket)
    clamped  = min(max(observed, rate x STEP_DOWN), rate x STEP_UP)   one ticket moves a rate at most x2 / /2
    rate'    = rate + ALPHA x (clamped - rate)                exponential moving average, ALPHA = 0.3
    rate'    = min(max(rate', RATE_MIN), RATE_MAX)            absolute bounds

Each update is kept with its numbers (before, observed, clamped, after) so the board can say why an estimate
changed. Accuracy = (actual - estimate) / estimate per ticket, against the estimate the ticket was given when the
plan was approved; the trend is a rolling mean absolute percentage error.

Persisted per organisation (``<data>/office/<org>/calibration.json``) in two profiles: ``live`` (real agents) and
``simulated`` (development mode), so simulated runs never touch the live constants. New plans take the current
rates of their profile (a snapshot on the program, so plan review and approval agree).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from aicad.assembly.store import read_json, write_json
from aicad.office import estimates, roster, store

ALPHA = 0.3
STEP_DOWN, STEP_UP = 0.5, 2.0
RATE_MIN, RATE_MAX = 0.05, 60.0
TREND_WINDOW = 5
HISTORY_MAX = 300
_lock = threading.Lock()


def defaults() -> dict[str, float]:
    return dict(estimates.MINUTES_PER_UNIT)


def update(rate: float, actual_min: float, complexity: int) -> dict[str, float]:
    """One bounded EMA step. Pure: the numbers the board shows for an update."""
    cx = max(1, int(complexity or 1))
    observed = max(0.0, float(actual_min)) / cx
    clamped = min(max(observed, rate * STEP_DOWN), rate * STEP_UP)
    after = min(max(rate + ALPHA * (clamped - rate), RATE_MIN), RATE_MAX)
    return {"before": round(rate, 4), "observed": round(observed, 4), "clamped": round(clamped, 4),
            "after": round(after, 4)}


def error_pct(estimate_min: float, actual_min: float) -> float | None:
    if not estimate_min:
        return None
    return round(100.0 * (float(actual_min) - float(estimate_min)) / float(estimate_min), 1)


def trend(accuracy: list[dict[str, Any]], window: int = TREND_WINDOW) -> list[dict[str, Any]]:
    """Rolling mean absolute percentage error over the last ``window`` tickets, one point per finished ticket."""
    out = []
    errs = [abs(float(a["error_pct"])) for a in accuracy if a.get("error_pct") is not None]
    for i in range(len(errs)):
        w = errs[max(0, i - window + 1): i + 1]
        out.append({"n": i + 1, "mape": round(sum(w) / len(w), 1)})
    return out


# ----------------------------------------------------------------------------- storage (per organisation)
def path(root: Path) -> Path:
    return root / "calibration.json"


def load(root: Path) -> dict[str, Any]:
    d = read_json(path(root))
    if not isinstance(d, dict) or not isinstance(d.get("profiles"), dict):
        d = {"version": 1, "profiles": {}}
    return d


def _profile(d: dict[str, Any], name: str) -> dict[str, Any]:
    p = d["profiles"].setdefault(name, {})
    p.setdefault("rates", {})
    p.setdefault("n", {})
    p.setdefault("history", [])
    p.setdefault("accuracy", [])
    return p


def rates(root: Path, profile: str) -> dict[str, float]:
    """The current minutes per complexity unit for every family (defaults where nothing was learned yet)."""
    p = (load(root)["profiles"].get(profile) or {}).get("rates") or {}
    return {**defaults(), **{k: float(v) for k, v in p.items() if k in estimates.MINUTES_PER_UNIT}}


def record(root: Path, profile: str, *, family: str, complexity: int, estimate_min: float, actual_min: float,
           ticket: dict[str, Any], program: dict[str, Any], stages: dict[str, float] | None = None) -> dict[str, Any]:
    """A finished ticket: update its family's rate and keep the update and the accuracy point."""
    with _lock:
        d = load(root)
        p = _profile(d, profile)
        cur = float(p["rates"].get(family) or defaults().get(family) or estimates.MINUTES_PER_UNIT["machined"])
        u = update(cur, actual_min, complexity)
        p["rates"][family] = u["after"]
        p["n"][family] = int(p["n"].get(family) or 0) + 1
        err = error_pct(estimate_min, actual_min)
        entry = {"at": store.now(), "family": family, "specialist": roster.specialist_for(family),
                 "ticket": ticket.get("key"), "title": ticket.get("title"), "program": program.get("name"),
                 "program_id": program.get("id"), "complexity": int(complexity or 1),
                 "estimate_min": round(float(estimate_min), 2), "actual_min": round(float(actual_min), 3),
                 "error_pct": err, "stages": stages or {}, **u}
        p["history"] = (p["history"] + [entry])[-HISTORY_MAX:]
        p["accuracy"] = (p["accuracy"] + [{k: entry[k] for k in ("at", "family", "ticket", "program", "estimate_min",
                                                                  "actual_min", "error_pct")}])[-HISTORY_MAX:]
        write_json(path(root), d)
        return entry


def view(root: Path, profile: str) -> dict[str, Any]:
    """What the calibration panel shows: per specialist the rate (default and learned), how many tickets taught
    it, the latest updates with their numbers, and the accuracy trend."""
    d = load(root)
    p = d["profiles"].get(profile) or {}
    cur = rates(root, profile)
    fams = []
    for fam, base in defaults().items():
        fams.append({"family": fam, "label": roster.family_label(fam),
                     "specialist": roster.specialist_for(fam), "default": base, "rate": round(cur[fam], 4),
                     "n": int((p.get("n") or {}).get(fam) or 0)})
    acc = p.get("accuracy") or []
    return {"profile": profile, "families": fams, "history": list(reversed((p.get("history") or [])[-30:])),
            "accuracy": acc[-60:], "trend": trend(acc)[-60:],
            "rule": {"alpha": ALPHA, "step": [STEP_DOWN, STEP_UP], "bounds": [RATE_MIN, RATE_MAX],
                     "window": TREND_WINDOW}}
