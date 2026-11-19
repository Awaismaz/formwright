"""Turn planning for a faster design agent (docs/reports/agent-latency.md).

A cold design turn is two model calls (write + build, then the reply) and its wall time is dominated by output
generation: thinking, the script and the reply. This module decides, per turn and without a model call:

- **What the agent already knows** (``folder_note``): the project folder's state in one line, so a new design never
  spends a call listing an empty folder, and the current design's text when the agent has not seen this version of
  it, so a change can be edited and built in one call (``build_model`` with ``edits``) instead of Read, then Edit.
- **How hard to think** (``choose_effort``): ``low`` when the request fully dimensions a simple part or asks for a
  local change to an existing one; the harness default (``medium``) otherwise. ``FW_AGENT_EFFORT`` still forces one
  level; ``FW_AGENT_ADAPTIVE_EFFORT=0`` turns the adaptive choice off.
- **Which model** (``route_model``, PD-82, opt-in): a faster model for edits and simple, fully dimensioned parts when
  ``FW_AGENT_FAST_MODEL`` names one. Off by default.

Everything here is plain text heuristics on the user's words; nothing is shown in the chat.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

ADAPTIVE_ENV, FAST_MODEL_ENV = "FW_AGENT_ADAPTIVE_EFFORT", "FW_AGENT_FAST_MODEL"
INLINE_MAX_LINES = 260  # a design longer than this is read by the agent itself (keeps the prompt small)
INLINE_MAX_CHARS = 16_000
DESIGN = "model.py"

# context blocks the app appends to a prompt (never the user's own words)
_BLOCKS = re.compile(r"\n\n\[(?:Selected|Reference image|Recognition data|Design state|Project context|Designer "
                     r"preferences|Project folder|Current design|Benchmark run)[\s\S]*$")
_NUM_UNIT = re.compile(r"(?:Ø|M|R)?\d+(?:[.,]\d+)?\s*(?:mm|°|deg|x|×|\b)", re.IGNORECASE)
# words that say the user wants judgement, options or a mechanism designed: think at the default level
_OPEN = re.compile(r"\b(?:suggest|recommend|which|what|how|why|should|could|best|optimi[sz]e|roughly|about|approx\w*|"
                   r"around|something|some kind|ideas?|options?|alternatives?|mechanism|assembly|gearbox|linkage|"
                   r"enclosure for|fit (?:a|an|the)|calculate|load|stress|deflection|strength|lighter|stiffer|"
                   r"cheaper|redesign|figure out|not sure|whatever)\b|\?", re.IGNORECASE)
_EDIT = re.compile(r"^\s*(?:make|change|set|move|add|remove|delete|increase|decrease|reduce|enlarge|resize|"
                   r"replace|turn|switch|fillet|chamfer|round|drill|tap|thread|shorten|lengthen|thicken|widen|"
                   r"mirror|pattern|offset|rename)\b", re.IGNORECASE)


def user_words(prompt: str) -> str:
    """The user's request without the context blocks the app appends."""
    return _BLOCKS.split(prompt, maxsplit=1)[0].strip()


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def design_text(workspace: Path) -> str | None:
    try:
        return (workspace / DESIGN).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _status(workspace: Path) -> dict[str, Any] | None:
    try:
        st = json.loads((workspace / "out" / "status.json").read_text(encoding="utf-8"))
        return st if isinstance(st, dict) else None
    except (OSError, ValueError):
        return None


def folder_note(workspace: Path, seen_sha: str | None, mode: str = "build") -> tuple[str, str | None]:
    """The one-line project folder state (plus the current design when the agent hasn't seen this version of it).
    Returns (note, sha of the design or None)."""
    src = design_text(workspace)
    refs = sorted(p.name for p in (workspace / "refs").glob("*") if p.is_file()) if (workspace / "refs").is_dir() \
        else []
    ref_note = f" Reference files in refs/: {', '.join(refs[:8])}." if refs else ""
    if src is None or not src.strip():
        if mode != "build":
            return f"[Project folder: no design yet.{ref_note}]", None
        return ("[Project folder: no design yet (model.py doesn't exist). Write the new design and build it in the same "
                f"response; no need to look through the folder.{ref_note}]"), None
    h = sha(src)
    st = _status(workspace) or {}
    built = ("last build: checks pass" if st.get("ok") else "last build: checks failed" if st.get("checks") else
             "last build: error" if st.get("error") else "not built yet")
    lines = len(src.splitlines())
    head = f"[Project folder: model.py exists ({lines} lines, {built}).{ref_note}"
    if h == seen_sha:
        return head + " It is unchanged since your last turn.]", h
    if lines > INLINE_MAX_LINES or len(src) > INLINE_MAX_CHARS or mode != "build":
        return head + " Read it before changing it.]", h
    return (head + " Its current text is below, so you don't need to read it: to change it, call build_model with "
            "`edits` (exact old/new excerpts of this text) to edit and build in one step.]\n"
            f"[Current design: model.py]\n```python\n{src.rstrip()}\n```"), h


# ------------------------------------------------------------------ effort and model
def adaptive_on() -> bool:
    return (os.environ.get(ADAPTIVE_ENV) or "1").strip().lower() not in ("0", "false", "off", "no")


def classify(prompt: str, has_design: bool) -> dict[str, Any]:
    """How demanding the request is, from the user's words only: ``edit`` (a local change to an existing design),
    ``dimensioned`` (a new simple part with its sizes given), or ``open`` (judgement, options, a mechanism, missing
    sizes, attachments). ``reason`` says why (run record)."""
    words = user_words(prompt)
    if "[Reference image" in prompt or "[Recognition data" in prompt:
        return {"kind": "open", "reason": "reference image"}
    if prompt.lstrip().startswith(("[Discussion mode", "[Brief confirmation")):
        return {"kind": "open", "reason": "discussion or brief"}
    if "[Background verification]" in prompt:
        return {"kind": "open", "reason": "fixing a failed check"}
    office = "```fw-icd" in prompt
    text = words if not office else re.split(r"```fw-icd", words)[0]
    nums = len(_NUM_UNIT.findall(text))
    open_m = _OPEN.search(re.sub(r"\(assumed\)", "", text)) if not office else None
    if open_m:
        return {"kind": "open", "reason": f"open request ('{open_m.group(0).strip()}')"}
    if has_design and len(words) <= 400 and _EDIT.search(words):
        return {"kind": "edit", "reason": "local change to the existing design"}
    if office:
        return {"kind": "dimensioned", "reason": "Design Office ticket with approved interfaces"}
    if not has_design and nums >= 4 and len(words) <= 1500:
        return {"kind": "dimensioned", "reason": f"new part with {nums} stated sizes"}
    return {"kind": "open", "reason": "not fully dimensioned" if not has_design else "larger change"}


def choose_effort(prompt: str, has_design: bool, forced: str | None = None) -> tuple[str | None, str]:
    """(effort or None for the harness default, why)."""
    if forced:
        return forced, "FW_AGENT_EFFORT"
    if not adaptive_on():
        return None, "adaptive effort off"
    c = classify(prompt, has_design)
    return ("low" if c["kind"] in ("edit", "dimensioned") else None), c["reason"]


def route_model(prompt: str, has_design: bool, default: str | None) -> tuple[str | None, str]:
    """PD-82 (opt-in): the fast model for edits and simple dimensioned parts when FW_AGENT_FAST_MODEL is set."""
    fast = (os.environ.get(FAST_MODEL_ENV) or "").strip()
    if not fast:
        return default, "routing off"
    c = classify(prompt, has_design)
    if c["kind"] in ("edit", "dimensioned") and "```fw-icd" not in prompt:
        return fast, f"fast model: {c['reason']}"
    return default, f"default model: {c['reason']}"
