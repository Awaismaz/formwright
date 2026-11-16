"""Honest token estimates for Image & Drawing to CAD, from measured runs.

Two actions cost tokens: the **read** (AI vision on an image or scanned PDF; vector PDFs are read from their text
for free) and the **build** (the design agent modelling from the confirmed values). Each finished run records what
it really cost (``tokens_for_cost`` of the SDK's cost estimate, also under God mode so the numbers stay true) in
``<data>/image2cad/costs.json``. The estimate shown before a run is the median of the recent runs, and the upper
figure is their 90th percentile; a run may start only when the balance covers that upper figure.

Until there are ``MIN_RUNS`` measured runs, the measured audit run of 2026-11-17 seeds the sample (stepped-shaft
drawing: read 63 tokens, build 275 tokens, "Done · 4 turns · 111.9 s"). It is the only measurement before this file
existed, so it is used rather than a guess.
"""

from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path
from statistics import median
from typing import Any

KINDS = ("read", "build")
SEED = {"read": 63, "build": 275}  # measured 2026-11-17 (docs/reports/audit/asm-mesh-img.md, AMI-03)
MIN_RUNS = 3  # fewer measured runs than this: the seed run joins the sample
WINDOW = 20  # recent runs used for the estimate
KEEP = 60  # runs kept per kind
_lock = threading.Lock()


def _path(data_dir: Path) -> Path:
    return data_dir / "image2cad" / "costs.json"


def _load(data_dir: Path) -> dict[str, list[dict[str, Any]]]:
    try:
        raw = json.loads(_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    return {k: [r for r in raw.get(k, []) if isinstance(r, dict) and isinstance(r.get("tokens"), int)] for k in KINDS}


def record(data_dir: Path, kind: str, tokens: int, ref: str | None = None) -> None:
    """Remember what one finished run really cost."""
    if kind not in KINDS or tokens <= 0:
        return
    with _lock:
        runs = _load(data_dir)
        runs[kind] = (runs[kind] + [{"tokens": int(tokens), "at": round(time.time()), "ref": ref}])[-KEEP:]
        p = _path(data_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(runs), encoding="utf-8")
        tmp.replace(p)


def percentile(values: list[int], q: float) -> int:
    """Nearest-rank percentile (q in 0..1), rounded up to whole tokens."""
    s = sorted(values)
    return int(s[max(0, math.ceil(q * len(s)) - 1)])


def summarise(samples: list[int], seed: int) -> dict[str, Any]:
    measured = len(samples)
    pool = samples[-WINDOW:] + ([seed] if measured < MIN_RUNS else [])
    typical = math.ceil(median(pool))
    return {"tokens": typical, "high": max(typical, percentile(pool, 0.9)), "runs": measured,
            "basis": "measured" if measured >= MIN_RUNS else "seed"}


def estimate(data_dir: Path) -> dict[str, dict[str, Any]]:
    """{"read": {...}, "build": {...}}: tokens (typical), high (covers 9 in 10 recent runs), runs, basis."""
    runs = _load(data_dir)
    return {k: summarise([r["tokens"] for r in runs[k]], SEED[k]) for k in KINDS}


def first_result_tokens(chat_jsonl: Path, start_line: int) -> tuple[str, float | None]:
    """Look at the Studio chat log after the hand-off: ("done", cost USD) when the first run finished,
    ("failed", None) when it stopped with an error and no result, else ("pending", None)."""
    try:
        lines = chat_jsonl.read_text(encoding="utf-8").splitlines()[start_line:]
    except OSError:
        return "pending", None
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "result":
            return "done", ev.get("cost_est_usd")
        if ev.get("type") == "error":
            return "failed", None
    return "pending", None
