"""The program timeline (CD-015, Gantt-lite): planned against actual, by ticket and by agent lane.

Pure and deterministic; the orchestrator records what happened on each ticket (``segments``: work per stage with the
agent instance that did it, waits for capacity and blocked spells with their times), and this module turns it into
what the Timeline tab draws. Times are minutes from the program's first Run.

Planned schedule (what the estimates promised): list scheduling at the program's concurrency N. At time 0 every
ticket whose dependencies are planned done may start; free slots take ready tickets by critical-path priority (the
longest chain of estimates through the tickets waiting for it, then the most dependents, then ticket order); a ticket
runs for its estimate. This is the greedy schedule the orchestrator itself follows, run on estimates.

Critical path: the chain of tickets with the longest total estimate from a ticket with no dependencies to the end
(an integration waits for all of its children). Ties go to the ticket order.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

WORK = "work"
STAGE_LABEL = {"hex": "Toolbox search", "design": "Design", "review": "Gage review", "fit": "Swap-in",
               "integrate": "Integration", "drawings": "Drawings", "dfm": "Manufacturing review",
               "capacity": "Waiting for capacity", "blocked": "Needs the engineer"}


def epoch(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None


def _seq(t: dict[str, Any]) -> int:
    try:
        return int(str(t["id"]).lstrip("t"))
    except ValueError:
        return 0


def chains(tickets: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, int]]:
    """Static critical-path priority on full estimates: chain = own estimate + the longest chain of the tickets
    waiting for it; dependents = how many tickets wait for it (directly or through others)."""
    by = {t["id"]: t for t in tickets}
    kids: dict[str, list[str]] = {t["id"]: [] for t in tickets}
    for t in tickets:
        for d in t.get("depends_on") or []:
            if d in kids:
                kids[d].append(t["id"])
    chain: dict[str, float] = {}
    reach: dict[str, set[str]] = {}

    def walk(tid: str, stack: frozenset[str] = frozenset()) -> None:
        if tid in chain or tid in stack:
            return
        for k in kids[tid]:
            walk(k, stack | {tid})
        chain[tid] = round(float(by[tid]["estimate_min"]) + max((chain.get(k, 0.0) for k in kids[tid]), default=0.0), 4)
        r: set[str] = set()
        for k in kids[tid]:
            r |= {k} | reach.get(k, set())
        reach[tid] = r

    for tid in by:
        walk(tid)
    return chain, {k: len(v) for k, v in reach.items()}


def critical_path(tickets: list[dict[str, Any]]) -> list[str]:
    """Ticket ids on the longest estimate chain, in order."""
    if not tickets:
        return []
    chain, _deps = chains(tickets)
    by = {t["id"]: t for t in tickets}
    kids: dict[str, list[str]] = {t["id"]: [] for t in tickets}
    for t in tickets:
        for d in t.get("depends_on") or []:
            if d in kids:
                kids[d].append(t["id"])
    roots = [t for t in tickets if not [d for d in t.get("depends_on") or [] if d in by]]
    cur = max(roots or tickets, key=lambda t: (chain[t["id"]], -_seq(t)))["id"]
    path = [cur]
    while kids[cur]:
        cur = max(kids[cur], key=lambda k: (chain[k], -_seq(by[k])))
        path.append(cur)
    return path


def planned(tickets: list[dict[str, Any]], concurrency: int,
            threads: dict[str, int] | None = None) -> dict[str, dict[str, Any]]:
    """Planned start / end (minutes) and slot of every ticket: greedy list scheduling on estimates. With per-agent
    ``threads`` an agent runs at most that many of its tickets at once (CD-027)."""
    n = max(1, int(concurrency or 1))
    threads = threads or {}
    busy: dict[str, int] = {}
    chain, deps = chains(tickets)
    by = {t["id"]: t for t in tickets}
    done: dict[str, float] = {}
    out: dict[str, dict[str, Any]] = {}
    running: list[tuple[float, str, int]] = []
    free = list(range(n))
    now = 0.0
    left = set(by)
    guard = 0
    while left and guard < 10 * len(by) + 10:
        guard += 1
        ready = [by[i] for i in left if i not in out and all(
            d in done and done[d] <= now + 1e-9 for d in by[i].get("depends_on") or [] if d in by)]
        ready.sort(key=lambda t: (-chain[t["id"]], -deps[t["id"]], _seq(t)))
        for t in ready:
            if not free:
                break
            code = t.get("specialist") or ""
            if threads.get(code) and busy.get(code, 0) >= threads[code]:
                continue
            busy[code] = busy.get(code, 0) + 1
            slot = free.pop(0)
            end = now + float(t["estimate_min"])
            out[t["id"]] = {"start": round(now, 4), "end": round(end, 4), "slot": slot}
            running.append((end, t["id"], slot))
        if not running:
            break  # a dependency cycle or a dependency outside the program: leave the rest unplanned
        running.sort()
        end, tid, slot = running.pop(0)
        now = end
        done[tid] = end
        busy[by[tid].get("specialist") or ""] -= 1
        left.discard(tid)
        free.append(slot)
        free.sort()
        while running and abs(running[0][0] - now) < 1e-9:  # everything finishing at the same moment
            e2, t2, s2 = running.pop(0)
            done[t2] = e2
            busy[by[t2].get("specialist") or ""] -= 1
            left.discard(t2)
            free.append(s2)
            free.sort()
    return out


def _segments(t: dict[str, Any], origin: float, now: float) -> list[dict[str, Any]]:
    """The ticket's recorded segments in minutes from the origin, open waits running to now (or to when the ticket
    was finished)."""
    out = []
    for s in t.get("segments") or []:
        a = float(s["start"])
        b = float(s["end"]) if s.get("end") is not None else now
        out.append({"stage": s["stage"], "kind": s.get("kind") or WORK, "agent": s.get("agent"),
                    "label": s.get("label"), "start": round((a - origin) / 60.0, 4),
                    "end": round((b - origin) / 60.0, 4), "open": s.get("end") is None,
                    "what": STAGE_LABEL.get(s["stage"], s["stage"])})
    w = t.get("wait_since")
    if w:
        out.append({"stage": w["kind"], "kind": w["kind"], "agent": None, "label": None,
                    "start": round((float(w["t"]) - origin) / 60.0, 4), "end": round((now - origin) / 60.0, 4),
                    "open": True, "what": STAGE_LABEL.get(w["kind"], w["kind"])})
    return out


def actual_minutes(t: dict[str, Any]) -> float:
    """The agent time a ticket took: the sum of its work segments (waits excluded)."""
    return round(sum((float(s["end"]) - float(s["start"])) / 60.0 for s in t.get("segments") or []
                     if (s.get("kind") or WORK) == WORK and s.get("end") is not None), 4)


def stage_minutes(t: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for s in t.get("segments") or []:
        if (s.get("kind") or WORK) != WORK or s.get("end") is None:
            continue
        out[s["stage"]] = round(out.get(s["stage"], 0.0) + (float(s["end"]) - float(s["start"])) / 60.0, 4)
    return out


def rounds(t: dict[str, Any]) -> dict[str, int]:
    """How many design turns, Gage rounds and Fitz swap-in rounds a ticket needed."""
    out: dict[str, int] = {}
    for s in t.get("segments") or []:
        if (s.get("kind") or WORK) == WORK:
            out[s["stage"]] = out.get(s["stage"], 0) + 1
    return out


def origin_of(doc: dict[str, Any], events: list[dict[str, Any]] | None = None) -> float | None:
    starts = [float(s["start"]) for t in doc["tickets"] for s in t.get("segments") or []]
    starts += [float(t["wait_since"]["t"]) for t in doc["tickets"] if t.get("wait_since")]
    run = next((epoch(e["t"]) for e in events or [] if e.get("type") == "program.run"), None)
    if run is not None:
        starts.append(run)
    first = (doc.get("orchestrator") or {}).get("first_run_at")
    if first:
        starts.append(float(first))
    return min(starts) if starts else None


def build(doc: dict[str, Any], events: list[dict[str, Any]] | None = None, now: float | None = None) -> dict[str, Any]:
    """Everything the Timeline tab draws."""
    import time

    now = time.time() if now is None else now
    tickets = doc["tickets"]
    origin = origin_of(doc, events)
    th = doc.get("threads")
    plan = planned(tickets, doc.get("concurrency") or 1, th if isinstance(th, dict) else None)
    crit = critical_path(tickets)
    rows = []
    lanes: dict[str, list[dict[str, Any]]] = {}
    lane_agent: dict[str, str] = {}
    for t in sorted(tickets, key=lambda x: (plan.get(x["id"], {}).get("start", 1e9), _seq(x))):
        segs = _segments(t, origin, now) if origin is not None else []
        act = actual_minutes(t)
        rows.append({"id": t["id"], "key": t["key"], "title": t["title"], "kind": t["kind"],
                     "specialist": t["specialist"], "column": t["column"], "estimate_min": t["estimate_min"],
                     "planned": plan.get(t["id"]), "segments": segs, "actual_min": act,
                     "error_pct": (round(100.0 * (act - float(t["estimate_min"])) / float(t["estimate_min"]), 1)
                                   if act and t["estimate_min"] and t["column"] in ("approved", "integrated") else None),
                     "critical": t["id"] in crit, "rounds": rounds(t)})
        for s in segs:
            if s["kind"] != WORK or not s["label"]:
                continue
            lanes.setdefault(s["label"], []).append({**s, "ticket": t["id"], "key": t["key"], "title": t["title"],
                                                     "critical": t["id"] in crit})
            lane_agent[s["label"]] = s["agent"]
    order = ["archie", "hex", "mill", "chuck", "axel", "benny", "molly", "gage", "fitz", "ortho", "smithy"]
    lane_list = [{"label": k, "agent": lane_agent[k], "bars": sorted(v, key=lambda b: b["start"])}
                 for k, v in sorted(lanes.items(), key=lambda kv: (order.index(lane_agent[kv[0]])
                                                                  if lane_agent[kv[0]] in order else 99, kv[0]))]
    markers = []
    for e in events or []:
        if e.get("type") in ("cr.raised", "cr.accepted", "cr.rejected") and origin is not None:
            at = epoch(e.get("t"))
            if at is not None:
                markers.append({"t": round((at - origin) / 60.0, 4), "type": e["type"], "text": e.get("text"),
                                "cr": (e.get("data") or {}).get("cr") or (e.get("data") or {}).get("id"),
                                "ticket": e.get("ticket_id")})
    planned_end = max((p["end"] for p in plan.values()), default=0.0)
    actual_end = max((s["end"] for r in rows for s in r["segments"]), default=0.0)
    elapsed = round((now - origin) / 60.0, 4) if origin is not None else 0.0
    done = [r for r in rows if r["column"] in ("approved", "integrated") and r["actual_min"]]
    return {"origin": origin, "now": elapsed, "concurrency": doc.get("concurrency"), "rows": rows, "lanes": lane_list,
            "critical": crit, "markers": markers,
            "planned_end": round(planned_end, 4), "actual_end": round(actual_end, 4),
            "span": round(max(planned_end, actual_end, elapsed if (doc.get("orchestrator") or {}).get("state")
                              == "running" else actual_end, 0.1), 4),
            "totals": {"estimate_min": round(sum(float(r["estimate_min"]) for r in done), 3),
                       "actual_min": round(sum(r["actual_min"] for r in done), 3), "done": len(done)}}
