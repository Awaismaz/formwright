"""Gage, the independent checker (CD-008). No agent approves its own work.

The review has two parts:
1. **Deterministic** (the acceptance): the latest build passes every gating check (CHK-02..09, including CHK-09
   against a reference when the part has one), and every size the ticket's own brief states (Ø25, 120 x 80, 10 mm)
   is found in the model: in its envelope, its parameters or its dimension lines. Findings are plain sentences.
2. **AI review note** (advisory, metered): one text-only turn of a separate model call with its own instructions
   (``run_review``, tests replace it). Its verdict can send the part back with findings, but it can never approve a
   part that failed the deterministic checks, and when it is unavailable the deterministic verdict stands.

Review rules (CD-030, PD-68): the approved ICD (this part's envelope and interfaces) governs over the brief's sizes;
approximate sizes ("about", "~") get a tolerance; only blocking problems send a part back, the rest are notes; a
re-review checks the earlier findings and raises new problems only when they block. The AI note is advisory: after
``MAX_SENDBACKS`` rounds of AI-only findings, a part whose measurable checks and interfaces pass is approved with the
open findings recorded (the orchestrator does this); only measurable failures make a part wait for the engineer.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

MAX_SENDBACKS = 2      # rounds Gage may send a part back before it waits for the engineer
REVIEW_MAX_TOKENS = 60  # hard cap for one AI review note
DIM_TOL = 0.05         # mm
# findings from the gating build checks (CHK-02..09): never relaxed by Archie (office/supervisor)
GATING_PREFIXES = ("Gating check", "The latest build does not pass", "There is no build")

REVIEW_INSTRUCTIONS = """You are Gage, the independent checker in a mechanical design office. You did not design \
this part. You receive the ticket brief, the approved interfaces (ICD) for this part when there are any, the part's \
measured envelope, parameters and check results, and its dimension lines.

What governs, in order: 1) the approved ICD: this part's envelope, interface positions, holes and fits (the engineer \
approved them; the designer must follow them and can't change them); 2) sizes the engineer's program brief states \
exactly; 3) sizes it gives as approximate ("about", "~", "roughly"): accept within 30 %. The rest of the ticket \
(planned sizes, the part split, what it mounts on) is the office's own plan, not a requirement: a part that differs \
from it is never sent back for that, at most a note. Never send a part back for following the ICD, even where the ICD \
differs from the brief: approve it and mention the difference as a note.

Send the part back ("changes") only for problems that block: it won't fit or assemble as the ICD says; it can't be \
made as modelled (geometry outside the part, stray bodies, holes breaking out of an edge, walls under 1 mm); a \
function the brief requires is missing; a governing size is clearly wrong. Everything else (style, naming, minor \
proportions, missing nice-to-have detail, a check that doesn't apply) is a note, not a finding. If earlier findings \
are listed, check whether they are fixed; raise a new finding only if it blocks.

Do not restate passing items. Never claim a part is manufacturable. Answer with one short sentence, then exactly \
one fenced block:
```fw-gage
{"verdict": "approve" | "changes", "findings": ["one short sentence per blocking problem"], "notes": ["non-blocking"]}
```"""

_BLOCK = re.compile(r"```fw-gage\s*\n(.*?)\n?```", re.DOTALL)
_NUM = r"(\d+(?:\.\d+)?)"


# ----------------------------------------------------------------------------- deterministic
def ticket_text(ticket: dict[str, Any]) -> str:
    """The ticket's own part of the brief (the program brief after it describes the whole product)."""
    return ticket.get("brief", "").split("Program brief:")[0]


def brief_dimensions(text: str) -> list[tuple[str, float]]:
    """Sizes the brief states: (as written, value in mm). Thread sizes (M6) and ratios are not sizes."""
    out: list[tuple[str, float]] = []
    seen: set[float] = set()

    def add(label: str, v: str) -> None:
        f = float(v)
        if f > 0 and f not in seen:
            seen.add(f)
            out.append((label, f))

    for m in re.finditer(r"[ØⲐ⌀]\s*" + _NUM, text):
        add(f"Ø{m.group(1)}", m.group(1))
    for m in re.finditer(_NUM + r"\s*[x×]\s*" + _NUM + r"(?:\s*[x×]\s*" + _NUM + r")?\s*(?:mm)?", text):
        for g in m.groups():
            if g:
                add(f"{g} mm", g)
    for m in re.finditer(r"(?<![M\d.])" + _NUM + r"\s*mm\b", text):
        add(f"{m.group(1)} mm", m.group(1))
    return out


_RADIUS = re.compile(r"(^R(AD)?_|_R(AD)?$|RADIUS)", re.IGNORECASE)


def model_numbers(state: dict[str, Any]) -> list[tuple[str, float]]:
    """(name, value) of the model's sizes: envelope, parameters and dimension lines."""
    nums: list[tuple[str, float]] = []
    nums += [("bbox", float(v)) for v in (state.get("bbox") or []) if isinstance(v, int | float)]
    nums += [(str(k), float(v)) for k, v in (state.get("params") or {}).items() if isinstance(v, int | float)
             and not isinstance(v, bool)]
    for m in re.finditer(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*" + _NUM, state.get("source") or "", re.MULTILINE):
        nums.append((m.group(1), float(m.group(2))))
    return nums


def _has(nums: list[tuple[str, float]], label: str, v: float) -> bool:
    """A size is present when the model carries it, or (for a diameter) a radius named as one."""
    return any(abs(n - v) <= DIM_TOL or (label.startswith("Ø") and _RADIUS.search(k) and abs(2 * n - v) <= DIM_TOL)
               for k, n in nums)


def deterministic(ticket: dict[str, Any], state: dict[str, Any], sizes: bool = True) -> list[str]:
    """Gating checks, then (``sizes``: programs without an ICD) the sizes the brief states. With an ICD, the
    orchestrator adds the interface conformance measurement instead (``aicad.office.conformance``)."""
    findings: list[str] = []
    if not state.get("builds"):
        return ["There is no build of this part yet."]
    if state.get("ok") is not True:
        failed = [c for c in state.get("checks") or [] if c.get("gating", True) and not c.get("passed")]
        if failed:
            findings += [f"Gating check {c.get('id')} ({c.get('name')}) fails on the latest build." for c in failed]
        else:
            findings.append("The latest build does not pass its gating checks.")
    if not sizes:
        return findings
    nums = model_numbers(state)
    for label, v in brief_dimensions(ticket_text(ticket)):
        if not _has(nums, label, v):
            env = " × ".join(f"{x:g}" for x in (state.get("bbox") or []))
            findings.append(f"The brief gives {label}, but the model has no matching size"
                            + (f" (envelope {env} mm)." if env else "."))
    return findings


# ----------------------------------------------------------------------------- AI review note
def review_prompt(ticket: dict[str, Any], state: dict[str, Any], icd: str | None = None,
                  previous: list[str] | None = None) -> str:
    dims = "\n".join(ln for ln in (state.get("source") or "").splitlines()
                     if re.match(r"^\s*[A-Z][A-Z0-9_]*\s*=", ln))[:3000]
    checks = ", ".join(f"{c.get('id')} {'pass' if c.get('passed') else 'fail'}" for c in state.get("checks") or [])
    out = f"Ticket {ticket['key']} {ticket['title']}\n\nBrief:\n{ticket_text(ticket)[:2000]}\n\n"
    if icd:
        out += ("Approved interfaces for this part (they govern; the part already measured inside its envelope and "
                f"to these interfaces):\n{icd[:2500]}\n\n")
    if previous:
        out += "Earlier findings (check whether they are fixed):\n" + "\n".join(f"- {p}" for p in previous[:8]) + "\n\n"
    return (out + f"Envelope (mm): {state.get('bbox')}\nParameters: {json.dumps(state.get('params') or {})[:1500]}\n"
            f"Checks: {checks}\nDimension lines:\n{dims}")


def parse_review(text: str) -> dict[str, Any] | None:
    found = None
    for m in _BLOCK.finditer(text or ""):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("verdict") in ("approve", "changes"):
            fs = [" ".join(str(f).split())[:300] for f in d.get("findings") or [] if str(f).strip()][:5]
            ns = [" ".join(str(f).split())[:300] for f in d.get("notes") or [] if str(f).strip()][:5]
            found = {"verdict": d["verdict"] if fs or d["verdict"] == "approve" else "approve", "findings": fs,
                     "notes": ns}
    if found is not None:
        from aicad.agent.session import scrub

        found["findings"] = [scrub(f) for f in found["findings"]]
        found["notes"] = [scrub(f) for f in found["notes"]]
        found["note"] = scrub(_BLOCK.sub("", text).strip())[:400]
    return found


async def run_review(folder: Path, prompt: str, budget_usd: float | None = None) -> tuple[str, float | None]:
    """One review turn, no tools (same shape as Archie's planning turn). Tests and fake mode replace it."""
    from aicad import llm

    res = await llm.complete(llm.CallRequest(role="reviewer", system=REVIEW_INSTRUCTIONS, prompt=prompt,
                                             budget_usd=budget_usd, cwd=folder))
    return res.text, res.metering.cost_usd
