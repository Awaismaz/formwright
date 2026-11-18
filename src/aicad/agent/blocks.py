"""Structured blocks the design agent embeds in its replies, parsed and validated server-side.

- ```fw-brief``` (CAD-028): the agent's interpreted requirements, assumptions and open questions for a new design,
  shown as an editable approval card before anything is built.
- ```fw-review``` (AGT-006): a short self-critique after a build, observed vs uncertain findings, each tied to a
  check id or to the render. The deterministic checks always win: a finding that claims a failed gating check as
  fine is marked "overridden", and the card's gate line comes from the build's own status, never from the agent.

Malformed blocks are removed from the visible text and never shown raw (same rule as ``fw-questions``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

_B_BLOCK = re.compile(r"```fw-brief\s*\n(.*?)\n?```", re.DOTALL)
_V_BLOCK = re.compile(r"```fw-review\s*\n(.*?)\n?```", re.DOTALL)
_CHECK_ID = re.compile(r"^CHK-\d{2}$")
_ALL_PASS = re.compile(r"\b(all|every)\b[^.]*\bchecks?\b[^.]*\bpass", re.IGNORECASE)

MAX_ITEMS = 12
MAX_CHARS = 300


def _same(s: str) -> str:
    return s


def _strs(raw: Any, clean: Callable[[str], str], limit: int = MAX_ITEMS) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [clean(str(x).strip())[:MAX_CHARS] for x in raw if isinstance(x, (str, int, float)) and str(x).strip()][:limit]


def parse_brief(raw: Any, clean: Callable[[str], str] = _same) -> dict[str, Any] | None:
    """Validate a brief. Requirements are mandatory; questions may be strings or {question, default}."""
    if not isinstance(raw, dict):
        return None
    reqs = _strs(raw.get("requirements"), clean)
    if not reqs:
        return None
    qs: list[dict[str, Any]] = []
    for q in raw.get("questions") or []:
        if isinstance(q, str) and q.strip():
            qs.append({"question": clean(q.strip())[:MAX_CHARS], "default": None})
        elif isinstance(q, dict) and isinstance(q.get("question"), str) and q["question"].strip():
            d = q.get("default")
            qs.append({"question": clean(q["question"].strip())[:MAX_CHARS],
                       "default": clean(str(d))[:120] if isinstance(d, (str, int, float)) and str(d).strip() else None})
        if len(qs) >= 6:
            break
    title = raw.get("title")
    return {"title": clean(str(title).strip())[:120] if isinstance(title, str) and title.strip() else None,
            "requirements": reqs, "assumptions": _strs(raw.get("assumptions"), clean), "questions": qs}


def extract_brief(text: str, clean: Callable[[str], str] = _same) -> tuple[str, dict[str, Any] | None]:
    """Pull a ```fw-brief JSON block out of a reply. Returns (text without the block, validated brief or None)."""
    found: dict[str, Any] | None = None
    for m in _B_BLOCK.finditer(text):
        try:
            b = parse_brief(json.loads(m.group(1)), clean)
        except ValueError:
            continue
        if b is not None:
            found = b
    return _B_BLOCK.sub("", text).strip(), found


def _findings(raw: Any, clean: Callable[[str], str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for f in raw if isinstance(raw, list) else []:
        if not isinstance(f, dict) or not isinstance(f.get("text"), str) or not f["text"].strip():
            continue
        basis = str(f.get("basis", "")).strip()
        basis = basis.upper() if _CHECK_ID.match(basis.upper()) else basis.lower()
        if basis != "render" and not _CHECK_ID.match(basis):
            continue  # every finding must be tied to a check or the render
        out.append({"text": clean(f["text"].strip())[:MAX_CHARS], "basis": basis})
        if len(out) >= MAX_ITEMS:
            break
    return out


def gate_summary(status: dict[str, Any] | None) -> dict[str, Any]:
    """The gate verdict as the deterministic checks report it (the only source of truth)."""
    if not status:
        return {"ok": None, "failed": [], "build_id": None}
    failed = [c.get("id") for c in status.get("checks") or [] if c.get("gating") and not c.get("passed")]
    ok = bool(status.get("ok")) and not status.get("error")
    return {"ok": ok, "failed": [f for f in failed if f], "build_id": status.get("build_id")}


def parse_review(raw: Any, status: dict[str, Any] | None, clean: Callable[[str], str] = _same) -> dict[str, Any] | None:
    """Validate a self-review and reconcile it with the build's real gate results. A finding can never turn a failed
    gate into a pass: observed findings on a failed check (or claiming all checks pass when they don't) are marked
    "overridden"."""
    if not isinstance(raw, dict):
        return None
    gates = gate_summary(status)
    failed = set(gates["failed"])
    items: list[dict[str, str]] = []
    for f in _findings(raw.get("observed"), clean):
        bad = f["basis"] in failed or (gates["ok"] is False and bool(_ALL_PASS.search(f["text"])))
        items.append({**f, "kind": "overridden" if bad else "observed"})
    items += [{**f, "kind": "uncertain"} for f in _findings(raw.get("uncertain"), clean)]
    if not items:
        return None
    return {"items": items, "gates": gates}


def extract_review(text: str, status: dict[str, Any] | None,
                   clean: Callable[[str], str] = _same) -> tuple[str, dict[str, Any] | None]:
    found: dict[str, Any] | None = None
    for m in _V_BLOCK.finditer(text):
        try:
            r = parse_review(json.loads(m.group(1)), status, clean)
        except ValueError:
            continue
        if r is not None:
            found = r
    return _V_BLOCK.sub("", text).strip(), found


def brief_to_prompt(brief: dict[str, Any], answers: dict[str, str] | None = None) -> str:
    """The confirmed brief as the build instruction (used by the eval harness and tests; the UI composes the same)."""
    answers = answers or {}
    lines = ["Approved design brief. Build it now.", "", "Requirements:"]
    lines += [f"- {r}" for r in brief.get("requirements", [])]
    if brief.get("assumptions"):
        lines += ["", "Assumptions (confirmed):"] + [f"- {a}" for a in brief["assumptions"]]
    if brief.get("questions"):
        lines += ["", "Answers to open questions:"]
        for q in brief["questions"]:
            a = answers.get(q["question"]) or q.get("default") or "your call; state the assumption"
            lines.append(f"- {q['question']} {a}")
    return "\n".join(lines)
