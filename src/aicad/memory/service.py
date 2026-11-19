"""Design projects: membership, Design Office program mapping, activity."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aicad.memory.tables import DesignProject, DesignProjectPart, ProjectDecision
from aicad.platform.db import utcnow
from aicad.platform.models import Project


def link(db: Session, part: Project, dp: DesignProject, user_id: str | None) -> None:
    """Put ``part`` in ``dp`` (moving it out of any other project). Same workspace only."""
    if part.org_id != dp.org_id:
        raise ValueError("A part can only join a project in its own workspace")
    row = db.get(DesignProjectPart, part.id)
    if row is None:
        db.add(DesignProjectPart(part_id=part.id, project_id=dp.id, added_by=user_id))
    elif row.project_id != dp.id:
        row.project_id, row.added_by, row.added_at = dp.id, user_id, utcnow()
    dp.updated_at = utcnow()
    db.flush()


def unlink(db: Session, part_id: str) -> None:
    row = db.get(DesignProjectPart, part_id)
    if row is not None:
        db.delete(row)
        db.flush()


def project_map(db: Session, part_ids: list[str]) -> dict[str, dict[str, str]]:
    """part id -> {id, name} of its project, for lists (one query)."""
    if not part_ids:
        return {}
    rows = db.execute(select(DesignProjectPart.part_id, DesignProject.id, DesignProject.name)
                      .join(DesignProject, DesignProject.id == DesignProjectPart.project_id)
                      .where(DesignProjectPart.part_id.in_(part_ids))).all()
    return {r[0]: {"id": r[1], "name": r[2]} for r in rows}


def part_ids(db: Session, project_id: str) -> list[str]:
    return list(db.scalars(select(DesignProjectPart.part_id).where(DesignProjectPart.project_id == project_id)
                           .order_by(DesignProjectPart.added_at)))


def sync_programs(db: Session, org_id: str, data_dir: Path) -> None:
    """Every Design Office program appears as a project holding its parts. Created once per program; a part a
    person already put in another project stays where they put it."""
    try:
        from aicad.office import store

        docs = store.list_docs(store.org_root(data_dir, org_id))
    except Exception:  # noqa: BLE001 - no office data, nothing to map
        return
    if not docs:
        return
    have = {dp.program_id: dp for dp in db.scalars(select(DesignProject).where(
        DesignProject.org_id == org_id, DesignProject.program_id.is_not(None)))}
    changed = False
    for doc in docs:
        pid = str(doc.get("id") or "")
        if not pid:
            continue
        dp = have.get(pid)
        if dp is None:
            dp = DesignProject(org_id=org_id, name=str(doc.get("name") or "Program")[:120],
                               purpose=str(doc.get("brief") or "")[:2000], program_id=pid,
                               created_by=doc.get("created_by") if isinstance(doc.get("created_by"), str) else None)
            db.add(dp)
            db.flush()
            changed = True
        ids = {t.get("project_id") for t in doc.get("tickets") or [] if isinstance(t, dict) and t.get("project_id")}
        if not ids:
            continue
        taken = set(db.scalars(select(DesignProjectPart.part_id).where(DesignProjectPart.part_id.in_(ids))))
        for p in db.scalars(select(Project).where(Project.id.in_(ids - taken), Project.org_id == org_id)):
            db.add(DesignProjectPart(part_id=p.id, project_id=dp.id))
            changed = True
    if changed:
        db.flush()


def activity(db: Session, dp: DesignProject, parts: list[Project], ws_for: Any, limit: int = 20) -> list[dict[str, Any]]:
    """Recent revisions of the project's parts and decisions captured, newest first (plain words)."""
    out: list[dict[str, Any]] = []
    for p in parts:
        root = ws_for(p) / "revisions"
        if not root.is_dir():
            continue
        nums = sorted((int(d.name) for d in root.iterdir() if d.is_dir() and d.name.isdigit()), reverse=True)[:8]
        for n in nums:
            d = root / str(n)
            try:
                cause = json.loads((d / "cause.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cause = {}
            try:
                at = datetime.fromtimestamp((d / "status.json").stat().st_mtime, UTC).replace(tzinfo=None)
            except OSError:
                continue
            out.append({"kind": "revision", "part": {"id": p.id, "name": p.name}, "revision": n,
                        "what": cause.get("cause") or "New revision", "by": cause.get("by"),
                        "source": cause.get("kind"), "at": at.isoformat()})
    for d in db.scalars(select(ProjectDecision).where(ProjectDecision.project_id == dp.id)
                        .order_by(ProjectDecision.created_at.desc()).limit(limit)):
        out.append({"kind": "decision", "what": d.text, "source": d.source, "status": d.status,
                    "at": d.created_at.isoformat()})
    out.sort(key=lambda e: e["at"], reverse=True)
    return out[:limit]
