"""Personal design memory: deterministic learning from what a person does (counting choices, no AI).

What is observed (only while the person's "Learn from my work" setting is on, never while an admin impersonates):

- the materials of the parts they create (from each part's latest verified build);
- the hand features they add: fillet radii, chamfer sizes, Hole Wizard type / size / fit;
- edits they make right after the design agent built (a hand feature or parameter change on top of an agent
  revision, within ``AFTER_AGENT_S``): the strongest signal of what the agent should have done;
- how they name parts;
- "always / never / I prefer" statements in the design chat (kept verbatim as stated rules).

Facts are recomputed from those observations with fixed thresholds (``MIN_*``); each carries its evidence count, a
confidence (the share of choices it covers) and a plain source. A person can edit, pin or delete any fact; a deleted
learned fact stays deleted (a tombstone stops it being re-learned) and an edited one is never overwritten.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from aicad.memory import extract
from aicad.memory.tables import MemoryEvent, MemoryFact, ProjectDecision
from aicad.platform.db import utcnow
from aicad.platform.models import Project, User

MAX_EVENTS = 400  # per person and workspace; older observations are dropped (PD: retention)
AFTER_AGENT_S = 30 * 60  # a hand edit this soon after an agent revision counts as a correction of it
MIN_MATERIAL = 2  # parts
MIN_FEATURE = 3  # hand fillets / chamfers of the same size
MIN_HOLE = 2
MIN_AFTER = 2
MIN_NAMING = 3
SHARE = 0.5  # a learned habit covers at least half of the person's choices of that kind


# ------------------------------------------------------------------ settings
def learning_on(user: User) -> bool:
    return (user.preferences or {}).get("memory_learning", True) is not False


def use_on(user: User) -> bool:
    return (user.preferences or {}).get("memory_use", True) is not False


def forgotten_at(user: User | None, org_id: str) -> datetime | None:
    """When this person last chose "Forget everything" in this workspace."""
    v = (((user.preferences or {}) if user else {}).get("memory_since") or {})
    v = v.get(org_id) if isinstance(v, dict) else None
    try:
        return datetime.fromisoformat(v) if isinstance(v, str) else None
    except ValueError:
        return None


def may_learn(ctx: Any) -> bool:
    """Learn from this request: the person's own action (not an impersonating admin) with learning on."""
    return bool(ctx.user and learning_on(ctx.user) and not getattr(ctx, "impersonating", False))


# ------------------------------------------------------------------ observations
def record(db: Session, user_id: str, org_id: str, part_id: str | None, kind: str, data: dict[str, Any]) -> None:
    db.add(MemoryEvent(user_id=user_id, org_id=org_id, part_id=part_id, kind=kind, data=data))
    db.flush()
    n = db.scalar(select(func.count()).select_from(MemoryEvent).where(MemoryEvent.user_id == user_id,
                                                                       MemoryEvent.org_id == org_id)) or 0
    if n > MAX_EVENTS:
        old = db.scalars(select(MemoryEvent.id).where(MemoryEvent.user_id == user_id, MemoryEvent.org_id == org_id)
                         .order_by(MemoryEvent.created_at).limit(n - MAX_EVENTS)).all()
        db.execute(delete(MemoryEvent).where(MemoryEvent.id.in_(old)))


def _rev_dir(ws: Path, n: int | None) -> Path | None:
    return ws / "revisions" / str(n) if n else None


def _json(f: Path | None) -> dict[str, Any]:
    if f is None:
        return {}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _manual(f: Path | None) -> list[dict[str, Any]]:
    if f is None:
        return []
    try:
        from aicad.agent.runner import _manual_block

        return [x for x in _manual_block(f.read_text(encoding="utf-8"))[1] if isinstance(x, dict)]
    except Exception:  # noqa: BLE001 - a model we can't parse teaches nothing
        return []


def feature_signal(f: dict[str, Any]) -> dict[str, Any] | None:
    op = f.get("op")
    if op == "fillet" and isinstance(f.get("r"), (int, float)):
        return {"op": "fillet", "size": round(float(f["r"]), 3)}
    if op == "chamfer" and isinstance(f.get("d"), (int, float)):
        return {"op": "chamfer", "size": round(float(f["d"]), 3)}
    if op == "hole":
        spec = f.get("spec") if isinstance(f.get("spec"), dict) else None
        if spec:
            return {"op": "hole", "type": spec.get("type"), "size": spec.get("size"), "fit": spec.get("fit")}
        if isinstance(f.get("d"), (int, float)):
            return {"op": "hole", "d": round(float(f["d"]), 3)}
    return None


def changes(ws: Path, rev: int) -> dict[str, Any]:
    """What revision ``rev`` changed relative to the revision it was made from: new/resized hand features and
    parameter changes, plus whether that parent was an agent build made shortly before."""
    d = _rev_dir(ws, rev)
    cause = _json(d / "cause.json") if d else {}
    parent = cause.get("parent")
    pd = _rev_dir(ws, parent if isinstance(parent, int) else None)
    before = {f.get("id"): f for f in _manual(pd / "model.py" if pd else None)}
    new_feats = []
    for f in _manual(d / "model.py" if d else None):
        old = before.get(f.get("id"))
        sig = feature_signal(f)
        if sig and (old is None or feature_signal(old) != sig) and not f.get("suppressed"):
            new_feats.append(sig)
    st, pst = _json(d / "status.json" if d else None), _json(pd / "status.json" if pd else None)
    meta = st.get("param_meta") or {}
    params = []
    for k, v in (st.get("editable_params") or {}).items():
        ov = (pst.get("editable_params") or {}).get(k)
        if isinstance(v, (int, float)) and isinstance(ov, (int, float)) and v != ov:
            params.append({"name": k, "label": (meta.get(k) or {}).get("label") or k, "from": ov, "to": v})
    after_agent = False
    if pd is not None and _json(pd / "cause.json").get("kind") == "agent":
        try:
            after_agent = (time.time() - (pd / "status.json").stat().st_mtime) <= AFTER_AGENT_S
        except OSError:
            after_agent = False
    return {"features": new_feats, "params": params, "after_agent": after_agent}


def observe_revision(db: Session, ctx: Any, part: Project, ws: Path, rev: int | None) -> None:
    """A person made revision ``rev`` by hand (manual feature or parameter edit): record what they chose."""
    if not rev or not may_learn(ctx):
        return
    try:
        ch = changes(ws, rev)
    except Exception:  # noqa: BLE001 - learning never breaks an edit
        return
    uid, oid = ctx.user.id, part.org_id
    for sig in ch["features"]:
        record(db, uid, oid, part.id, "feature", sig)
        if ch["after_agent"]:
            record(db, uid, oid, part.id, "after_agent", {"what": sig["op"], **sig})
    if ch["after_agent"]:
        for p in ch["params"][:3]:
            record(db, uid, oid, part.id, "after_agent", {"what": "param", "label": str(p["label"])[:60],
                                                          "from": p["from"], "to": p["to"]})
    recompute(db, uid, oid)


def observe_prompt(db: Session, ctx: Any, part: Project, text: str, design_project_id: str | None) -> list[dict[str, str]]:
    """Capture explicit standing instructions from a chat message. Returns what was remembered (for the chat)."""
    if not may_learn(ctx):
        return []
    out: list[dict[str, str]] = []
    for s in extract.statements(text, in_project=bool(design_project_id)):
        if s.scope == "project" and design_project_id:
            have = {extract.normalise(t) for t in db.scalars(select(ProjectDecision.text).where(
                ProjectDecision.project_id == design_project_id))}
            if extract.normalise(s.text) in have:
                continue
            db.add(ProjectDecision(project_id=design_project_id, text=s.text, category=s.category, source="chat",
                                   source_part_id=part.id, created_by=ctx.user.id))
            out.append({"scope": "project", "text": s.text})
        elif s.scope == "personal":
            f = db.scalar(select(MemoryFact).where(MemoryFact.user_id == ctx.user.id,
                                                   MemoryFact.org_id == part.org_id, MemoryFact.key == s.key))
            if f is not None:
                continue
            db.add(MemoryFact(user_id=ctx.user.id, org_id=part.org_id, key=s.key, kind="rule", text=s.text,
                              value={"category": s.category}, origin="said", confidence=1.0, evidence=1,
                              source=f"You said this in the chat on “{part.name[:60]}”"))
            out.append({"scope": "personal", "text": s.text})
    db.flush()
    return out


# ------------------------------------------------------------------ derivation
def _g(x: Any) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    return f"{v:.4g}"


def _mode(values: list[Any]) -> tuple[Any, int, int]:
    c = Counter(values)
    v, n = c.most_common(1)[0]
    return v, n, len(values)


HOLE_TYPE = {"clearance": "clearance", "tapped": "tapped", "cbore": "counterbored", "csk": "countersunk"}
_NAMING = re.compile(r"^([A-Z]{2,6}\d{0,3})[-_ ]?(\d{2,4})\b")


def derive(db: Session, user_id: str, org_id: str) -> dict[str, dict[str, Any]]:
    """Facts implied by the person's observations and parts (key -> fields). Pure counting with fixed thresholds."""
    out: dict[str, dict[str, Any]] = {}
    q = select(Project).where(Project.org_id == org_id, Project.created_by == user_id)
    since = forgotten_at(db.get(User, user_id), org_id)
    if since is not None:  # "Forget everything": parts made before it teach nothing
        q = q.where(Project.created_at > since)
    parts = db.scalars(q.order_by(Project.created_at.desc()).limit(200)).all()
    mats = [str((p.last_status or {}).get("material")) for p in parts if (p.last_status or {}).get("material")]
    if mats:
        m, n, total = _mode(mats)
        if n >= MIN_MATERIAL and n / total >= SHARE:
            out["material"] = {"kind": "material", "text": f"Usually specifies {m}", "value": {"material": m},
                               "evidence": n, "confidence": round(n / total, 2),
                               "source": f"Material of {n} of your {total} parts with a material"}
    names = [p.name for p in parts[:12]]
    coded = [mm.group(1) for nm in names if (mm := _NAMING.match(nm))]
    if len(coded) >= MIN_NAMING and len(coded) / max(len(names), 1) >= SHARE:
        ex = next(nm for nm in names if _NAMING.match(nm))
        out["naming"] = {"kind": "naming", "text": f"Names parts with a code and number first, like “{ex[:40]}”",
                         "value": {"example": ex[:40]}, "evidence": len(coded),
                         "confidence": round(len(coded) / len(names), 2),
                         "source": f"{len(coded)} of your last {len(names)} part names"}
    evs = db.scalars(select(MemoryEvent).where(MemoryEvent.user_id == user_id, MemoryEvent.org_id == org_id)
                     .order_by(MemoryEvent.created_at)).all()
    feats = [e.data for e in evs if e.kind == "feature"]
    for op, label, unit in (("fillet", "Typical hand fillet R{v} mm", "fillets"),
                            ("chamfer", "Typical chamfer {v} mm", "chamfers")):
        sizes = [f["size"] for f in feats if f.get("op") == op and f.get("size") is not None]
        if sizes:
            v, n, total = _mode(sizes)
            if n >= MIN_FEATURE and n / total >= SHARE:
                out[f"{op}_size"] = {"kind": op, "text": label.format(v=_g(v)), "value": {"size": v}, "evidence": n,
                                     "confidence": round(n / total, 2),
                                     "source": f"{n} of the {total} {unit} you added by hand"}
    holes = [f for f in feats if f.get("op") == "hole" and f.get("type")]
    if holes:
        fits = [h.get("fit") for h in holes if h.get("type") != "tapped" and h.get("fit")]
        if fits:
            v, n, total = _mode(fits)
            if n >= MIN_HOLE and n / total >= 0.6:
                out["hole_fit"] = {"kind": "hole", "text": f"Clearance holes in the {v} fit (ISO 273)",
                                   "value": {"fit": v}, "evidence": n, "confidence": round(n / total, 2),
                                   "source": f"{n} of the {total} clearance holes you placed with the Hole Wizard"}
        kinds = [(h.get("type"), h.get("size")) for h in holes]
        (t, sz), n, total = _mode(kinds)
        if n >= MIN_HOLE and n / total >= SHARE:
            out["hole_std"] = {"kind": "hole", "text": f"Most-used hole: M{_g(sz)} {HOLE_TYPE.get(t, t)}",
                               "value": {"type": t, "size": sz}, "evidence": n, "confidence": round(n / total, 2),
                               "source": f"{n} of the {total} holes you placed with the Hole Wizard"}
    after = [e.data for e in evs if e.kind == "after_agent"]
    by: dict[str, list[dict[str, Any]]] = {}
    for a in after:
        k = a.get("what") if a.get("what") != "param" else f"param:{str(a.get('label', '')).lower()}"
        by.setdefault(str(k), []).append(a)
    for k, items in by.items():
        if len(items) < MIN_AFTER:
            continue
        if k in ("fillet", "chamfer"):
            v, _, _ = _mode([i.get("size") for i in items])
            what = "fillets" if k == "fillet" else "chamfers"
            size = f"R{_g(v)}" if k == "fillet" else f"{_g(v)} mm"
            text = f"Adds {what} ({size}) by hand after the agent builds: include them in the first build"
        elif k == "hole":
            text = "Adds holes by hand after the agent builds: ask about holes or include them up front"
        else:
            label = items[-1].get("label") or k[6:]
            ups = sum(1 for i in items if isinstance(i.get("to"), (int, float)) and isinstance(i.get("from"), (int, float))
                      and i["to"] > i["from"])
            way = "increases" if ups == len(items) else "decreases" if ups == 0 else "changes"
            text = f"Often {way} “{label}” after the agent builds"
        out[f"after:{k}"[:80]] = {"kind": "after_agent", "text": text[:200], "value": {"what": k},
                                  "evidence": len(items), "confidence": round(min(1.0, len(items) / 4), 2),
                                  "source": f"{len(items)} hand edits right after a design-agent build"}
    return out


def recompute(db: Session, user_id: str, org_id: str) -> None:
    derived = derive(db, user_id, org_id)
    existing = {f.key: f for f in db.scalars(select(MemoryFact).where(MemoryFact.user_id == user_id,
                                                                     MemoryFact.org_id == org_id))}
    now = utcnow()
    for key, d in derived.items():
        f = existing.get(key)
        if f is None:
            db.add(MemoryFact(user_id=user_id, org_id=org_id, key=key, origin="learned", **d))
        elif f.status == "dismissed":
            continue
        elif f.origin == "user":
            f.evidence, f.confidence, f.updated_at = d["evidence"], d["confidence"], now
        elif (f.text, f.evidence, f.confidence, f.source) != (d["text"], d["evidence"], d["confidence"], d["source"]):
            f.text, f.value, f.evidence, f.confidence, f.source = d["text"], d["value"], d["evidence"], d["confidence"], d["source"]
            f.updated_at = now
    for key, f in existing.items():
        if f.origin == "learned" and key not in derived and not f.pinned and f.status == "active":
            db.delete(f)
    db.flush()
