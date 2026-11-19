"""The project brief and the preferences block a design-agent turn carries.

``turn_context`` is the single entry point (keep prompt additions here so other prompt changes merge cleanly). It
returns the internal text block (never shown to the user: its wording is for the agent) and a plain-language view
of the same content for the Studio's "the agent knows" indicator.

Bounds: the project brief is at most ``PROJECT_LIMIT`` characters and the preferences at most ``PREFS_LIMIT``
(about 4 characters per token, so the whole block stays under ~700 tokens). The block is sent once per agent
conversation and again only when its content changes (``should_send``): the agent keeps earlier turns in context.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aicad.memory import facts as F
from aicad.memory import learn
from aicad.memory.tables import DesignProject, DesignProjectPart, MemoryFact, ProjectDecision
from aicad.platform.models import Project, User

PROJECT_LIMIT = 2000
PREFS_LIMIT = 700
MAX_PREFS = 8
MAX_DECISIONS = 8
PART_LINE = 300
CHARS_PER_TOKEN = 4  # rough English/CAD text ratio, for the bound and the estimate shown to admins

_KEYWORDS = {
    "fillet": r"fillet|round|radius|\bR\d",
    "chamfer": r"chamfer|bevel",
    "hole": r"hole|bolt|screw|tap|thread|\bM\d",
    "material": r"material|alumin|steel|stainless|brass|plastic|ABS|nylon|6061|7075",
    "naming": r"name|call it",
}


@dataclass
class TurnContext:
    text: str = ""  # internal block for the agent ("" when there is nothing to add)
    project: dict[str, Any] | None = None  # {id, name, purpose}
    parts: list[dict[str, Any]] = field(default_factory=list)  # siblings: {id, name, line}
    named: list[dict[str, Any]] = field(default_factory=list)  # siblings named only (not built yet, or no room)
    hidden_parts: int = 0  # siblings this person can't read (never described)
    decisions: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    digest: str = ""

    @property
    def tokens_est(self) -> int:
        return (len(self.text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN

    def view(self) -> dict[str, Any]:
        """What the person sees: plain words, no internals."""
        return {"project": self.project, "parts": [{"id": p["id"], "name": p["name"], "summary": p["line"]}
                                                     for p in self.parts + self.named],
                "decisions": self.decisions, "preferences": self.preferences, "in_use": bool(self.text)}


def design_project_of(db: Session, part_id: str) -> DesignProject | None:
    link = db.get(DesignProjectPart, part_id)
    return db.get(DesignProject, link.project_id) if link else None


def active_decisions(db: Session, project_id: str) -> list[ProjectDecision]:
    return list(db.scalars(select(ProjectDecision).where(ProjectDecision.project_id == project_id,
                                                         ProjectDecision.status == "active")
                           .order_by(ProjectDecision.created_at)))


def siblings(db: Session, user: User, part: Project, dp: DesignProject) -> tuple[list[Project], int]:
    """The other parts of the project that this person can read (and how many they can't)."""
    from aicad.platform.collab import permissions

    ids = [r.part_id for r in db.scalars(select(DesignProjectPart).where(DesignProjectPart.project_id == dp.id)
                                         .order_by(DesignProjectPart.added_at, DesignProjectPart.part_id))
           if r.part_id != part.id]
    rows = list(db.scalars(select(Project).where(Project.id.in_(ids), Project.org_id == dp.org_id,
                                                 Project.archived.is_(False)))) if ids else []
    order = {pid: i for i, pid in enumerate(ids)}
    rows.sort(key=lambda p: order[p.id])  # the order parts joined the project (stable block, fewer re-sends)
    seen = permissions.visible(db, user, rows)
    return seen, len(rows) - len(seen)


def _priority(parts: list[Project], prompt: str) -> list[Project]:
    """Parts the request names first, then built parts (they have sizes to share), most recently changed first."""
    low = prompt.lower()

    def score(p: Project) -> tuple[int, int, float]:
        words = [w for w in re.findall(r"[a-z0-9]+", p.name.lower()) if len(w) >= 4]
        hit = any(w in low or (w.endswith("s") and w[:-1] in low) for w in words)
        return (0 if hit else 1, 0 if p.builds else 1, -p.updated_at.timestamp())

    return sorted(parts, key=score)


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    return text if len(text) <= n else text[: n - 1] + "…"


def project_brief(db: Session, user: User, part: Project, prompt: str = "",
                  ws_for: Any = None) -> tuple[str, TurnContext]:
    tc = TurnContext()
    dp = design_project_of(db, part.id)
    if dp is None:
        return "", tc
    if ws_for is None:
        from aicad.platform.routers.projects import workspace_for as ws_for
    tc.project = {"id": dp.id, "name": dp.name, "purpose": dp.purpose}
    sibs, tc.hidden_parts = siblings(db, user, part, dp)
    tc.decisions = [d.text for d in active_decisions(db, dp.id)][:MAX_DECISIONS]
    head = f"[Project context: this part (“{_clip(part.name, 80)}”) belongs to the project “{_clip(dp.name, 80)}”"
    head += f" with {len(sibs)} other part(s)." if sibs else "."
    lines = [head]
    if dp.purpose.strip():
        lines.append("Purpose: " + _clip(dp.purpose, 300))
    if dp.notes.strip():
        lines.append("Notes: " + _clip(dp.notes, 240))
    if tc.decisions:
        lines.append(_clip("Project decisions (follow them unless this request says otherwise): "
                           + "; ".join(tc.decisions), 480))
    tail = ("Mating features (hole patterns, bores, shaft diameters, outlines) of the other parts are in mm, in each "
            "part's own coordinates. Use them to make this part fit; change another part only if the user asks.]")
    budget = PROJECT_LIMIT - sum(len(x) + 1 for x in lines) - len(tail) - len("Other parts:") - 2
    chosen: dict[str, str] = {}
    for p in _priority(sibs, prompt):  # described while there is room; the rest are named
        if not p.builds or budget < 60:
            continue
        line = F.fact_line(F.part_facts(ws_for(p), p.name), min(PART_LINE, budget - 3))
        chosen[p.id] = line
        budget -= len(line) + 3
    if chosen:
        lines.append("Other parts:")
        for p in sibs:  # written in a stable order, so the same content gives the same block
            if p.id in chosen:
                lines.append("- " + chosen[p.id])
                tc.parts.append({"id": p.id, "name": p.name, "line": chosen[p.id]})
    rest = [p for p in sibs if p.id not in chosen]
    tc.named = [{"id": p.id, "name": p.name, "line": p.name + (": not built yet" if not p.builds else ": named only")}
                for p in rest]
    if rest:
        label = "Not built yet: " if all(not p.builds for p in rest) else "Also in the project: "
        names, room = [], budget - len(label) - 2
        for p in rest:
            nm = _clip(p.name, 60)
            if len(nm) + 2 > room:
                names.append(f"{len(rest) - len(names)} more")
                break
            names.append(nm)
            room -= len(nm) + 2
        lines.append(label + ", ".join(names))
    lines.append(tail)
    return "\n".join(lines), tc


def _pref_score(f: MemoryFact, prompt: str) -> float:
    s = f.confidence * min(f.evidence, 10)
    s += 100 if f.pinned else 0
    s += 50 if f.origin == "said" else 40 if f.origin == "user" else 0
    rx = _KEYWORDS.get(f.kind) or _KEYWORDS.get(str((f.value or {}).get("category")))
    if rx and re.search(rx, prompt, re.IGNORECASE):
        s += 30
    return s


def preference_facts(db: Session, user: User, org_id: str, prompt: str = "") -> list[MemoryFact]:
    if not learn.use_on(user):
        return []
    rows = list(db.scalars(select(MemoryFact).where(MemoryFact.user_id == user.id, MemoryFact.org_id == org_id,
                                                    MemoryFact.status == "active")))
    picked = sorted(rows, key=lambda f: (-_pref_score(f, prompt), f.key))[:MAX_PREFS]  # most relevant are kept
    return sorted(picked, key=lambda f: (-_pref_score(f, ""), f.key))  # stable order: same facts, same block


def preferences_block(db: Session, user: User, org_id: str, prompt: str = "") -> tuple[str, list[str]]:
    head = ("[Designer preferences, learned from this person's earlier work in this workspace. Apply them only where "
            "the request and the project decisions say nothing; an explicit instruction always wins. Don't mention "
            "this list:")
    units = (user.preferences or {}).get("units")
    items: list[str] = ["Works in inches (show inch values alongside mm)"] if units == "in" else []
    for f in preference_facts(db, user, org_id, prompt):
        items.append(f.text)
    out, shown = head, []
    for t in items:
        line = "\n- " + t
        if len(out) + len(line) + 1 > PREFS_LIMIT:
            break
        out += line
        shown.append(t)
    return (out + "]", shown) if shown else ("", [])


def turn_context(db: Session, user: User, part: Project, prompt: str = "", ws_for: Any = None) -> TurnContext:
    """Everything a design-agent turn on ``part`` should know beyond the part itself (project + preferences)."""
    brief, tc = project_brief(db, user, part, prompt, ws_for)
    prefs, tc.preferences = preferences_block(db, user, part.org_id, prompt)
    tc.text = "\n\n".join(t for t in (brief, prefs) if t)
    tc.digest = hashlib.sha256(tc.text.encode("utf-8")).hexdigest()[:16] if tc.text else ""
    return tc


# ------------------------------------------------------------------ once per conversation
def _state(state_dir: Path) -> Path:
    return state_dir / "context.json"


def should_send(state_dir: Path, session_id: str | None, digest: str) -> bool:
    """Send the block on a conversation's first turn and whenever it changed since it was last sent."""
    if not digest:
        return False
    if not session_id:
        return True
    try:
        st = json.loads(_state(state_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    return st.get("digest") != digest


def mark_sent(state_dir: Path, digest: str) -> None:
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        _state(state_dir).write_text(json.dumps({"digest": digest}), encoding="utf-8")
    except OSError:
        pass
