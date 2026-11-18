"""Collaboration tables. All new (additive): `Base.metadata.create_all` creates them on an existing database, and no
existing table or column changes, so live workspaces keep working unchanged (a project without rows here behaves
exactly as before: workspace-wide access by role, a single `main` line of revisions)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aicad.platform.db import Base, utcnow


def _id() -> str:
    return uuid.uuid4().hex


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(9), default="#2563eb")
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10), default="editor")  # admin|editor|viewer
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProjectAccess(Base):
    """Ownership and general access of one project. No row = personal to nobody, open to the workspace by role
    (the behaviour of every project made before this table existed)."""

    __tablename__ = "project_access"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    team_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    general: Mapped[str] = mapped_column(String(10), default="edit")  # level for everyone in the workspace
    protected_main: Mapped[bool] = mapped_column(Boolean, default=False)
    required_approvals: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProjectGrant(Base):
    """Explicit access to one project for a person (workspace member or guest) or a team."""

    __tablename__ = "project_grants"
    __table_args__ = (UniqueConstraint("project_id", "subject_type", "subject_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    subject_type: Mapped[str] = mapped_column(String(10))  # user|team
    subject_id: Mapped[str] = mapped_column(String(32), index=True)
    level: Mapped[str] = mapped_column(String(10), default="read")  # read|comment|edit
    guest: Mapped[bool] = mapped_column(Boolean, default=False)  # a person outside the workspace
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GuestInvite(Base):
    """Links a workspace invite (role "guest") to the one project it opens."""

    __tablename__ = "guest_invites"
    invite_id: Mapped[str] = mapped_column(ForeignKey("invites.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(10), default="read")


class ShareLink(Base):
    """A read-only link (signed token, revocable, optional expiry) that opens the part without signing in."""

    __tablename__ = "share_links"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(80), default="")
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    uses: Mapped[int] = mapped_column(Integer, default=0)


class Comment(Base):
    __tablename__ = "project_comments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    branch: Mapped[str] = mapped_column(String(32), default="main")
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mr_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    parent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list[str]] = mapped_column(JSON, default=list)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Branch(Base):
    """A named line of work on a project. `main` is implicit (the project's own workspace and revisions)."""

    __tablename__ = "project_branches"
    __table_args__ = (UniqueConstraint("project_id", "name"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex[:12])
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(48))
    source: Mapped[str] = mapped_column(String(32), default="main")  # branch it was made from
    base_rev: Mapped[int | None] = mapped_column(Integer, nullable=True)  # revision of `source` it started at
    status: Mapped[str] = mapped_column(String(10), default="open")  # open|merged|closed
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MergeRequest(Base):
    __tablename__ = "merge_requests"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[str] = mapped_column(String(32), index=True)
    number: Mapped[int] = mapped_column(Integer, default=1)  # per project, shown as !n
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="open")  # open|merged|closed
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    merged_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    merge_rev: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reconcile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # agent-proposed resolutions


class Review(Base):
    __tablename__ = "mr_reviews"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    mr_id: Mapped[str] = mapped_column(ForeignKey("merge_requests.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(20))  # approved|changes_requested|commented
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Tag(Base):
    """A named release point on main (e.g. "v1.0" or "Rev A")."""

    __tablename__ = "project_tags"
    __table_args__ = (UniqueConstraint("project_id", "name"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    revision: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
