"""Design projects and design memory tables. All new (additive): ``Base.metadata.create_all`` creates them on an
existing database; no existing table or column changes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from aicad.platform.db import Base, utcnow


def _id() -> str:
    return uuid.uuid4().hex


class DesignProject(Base):
    """A user-facing Project: related parts, their purpose, notes and shared decisions. Workspace-scoped."""

    __tablename__ = "design_projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str] = mapped_column(Text, default="")  # what the parts are for (one or two sentences)
    notes: Mapped[str] = mapped_column(Text, default="")  # running notes, edited by people
    program_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)  # Design Office program
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class DesignProjectPart(Base):
    """A part's place in a project. The part id is the primary key: a part belongs to at most one project."""

    __tablename__ = "design_project_parts"
    part_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("design_projects.id", ondelete="CASCADE"), index=True)
    added_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProjectDecision(Base):
    """A decision every part of the project follows ("all fasteners M6 ISO 4762", "material 6061-T6")."""

    __tablename__ = "design_project_decisions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("design_projects.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(String(240))
    category: Mapped[str] = mapped_column(String(20), default="other")  # fastener|material|units|tolerance|standard|other
    source: Mapped[str] = mapped_column(String(10), default="manual")  # manual|chat|memory|program
    source_part_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active|dismissed
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MemoryFact(Base):
    """One learned or stated preference of one person in one workspace. Never read across workspaces."""

    __tablename__ = "memory_facts"
    __table_args__ = (UniqueConstraint("user_id", "org_id", "key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(80))  # what it is about (dedupe), e.g. "material", "fillet_r", "rule:ab12"
    kind: Mapped[str] = mapped_column(String(20))  # material|fillet|chamfer|hole|after_agent|naming|rule
    text: Mapped[str] = mapped_column(String(240))
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(200), default="")  # plain words: where it was learned
    evidence: Mapped[int] = mapped_column(Integer, default=1)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    origin: Mapped[str] = mapped_column(String(10), default="learned")  # learned|said|user (edited by the person)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active|dismissed (a deleted learned fact)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MemoryEvent(Base):
    """A raw observation the learned facts are counted from (bounded per person and workspace)."""

    __tablename__ = "memory_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    part_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # material|feature|after_agent|undo
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
