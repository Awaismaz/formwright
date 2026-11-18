"""Collaboration API: teams, project access and sharing, share links, presence, activity, comments, branches,
merge requests and tags. Permission decisions live in `aicad.platform.collab.permissions`."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from aicad.platform import metering
from aicad.platform.collab import branches, merge, permissions, reconcile
from aicad.platform.collab.permissions import GENERAL_LEVELS, GRANT_LEVELS, RANK, TEAM_ROLES
from aicad.platform.collab.tables import (
    Branch,
    Comment,
    GuestInvite,
    MergeRequest,
    ProjectAccess,
    ProjectGrant,
    Review,
    ShareLink,
    Tag,
    Team,
    TeamMember,
)
from aicad.platform.config import get_settings
from aicad.platform.db import utcnow
from aicad.platform.deps import Ctx, confirmed_ctx, verified_ctx
from aicad.platform.models import (
    AgentRun,
    AuditLog,
    Invite,
    Membership,
    Organization,
    Project,
    User,
)
from aicad.platform.security import hash_token, new_token, normalize_email, valid_email
from aicad.platform.services import audit, debit, notify, send_email

router = APIRouter(prefix="/api", tags=["collab"])
COLORS = ("#2563eb", "#0891b2", "#059669", "#65a30d", "#d97706", "#dc2626", "#db2777", "#7c3aed", "#475569")


def _projects_mod() -> Any:
    from aicad.platform.routers import projects

    return projects


def _user_brief(u: User | None) -> dict[str, Any] | None:
    return {"id": u.id, "name": u.name, "email": u.email} if u else None


def _names(ctx: Ctx, ids: set[str | None]) -> dict[str, str]:
    ids = {i for i in ids if i}
    return {u.id: u.name for u in ctx.db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def _ws_admin(ctx: Ctx) -> bool:
    return ctx.role in ("owner", "admin")


# =============================================================================== teams (PLT-020)
class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=2000)
    color: str = "#2563eb"


class TeamPatch(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    color: str | None = None


class TeamMemberIn(BaseModel):
    user_id: str
    role: str = "editor"


class TeamRoleIn(BaseModel):
    role: str


def _team(ctx: Ctx, tid: str) -> Team:
    t = ctx.db.get(Team, tid)
    if t is None or t.org_id != ctx.require_org().id:
        raise HTTPException(404, "Team not found")
    return t


def _can_manage_team(ctx: Ctx, t: Team) -> bool:
    return _ws_admin(ctx) or permissions.team_role(ctx.db, t.id, ctx.user.id) == "admin"


def _color(c: str | None) -> str:
    return c if c and re.fullmatch(r"#[0-9a-fA-F]{6}", c) else COLORS[0]


def _team_dict(ctx: Ctx, t: Team, members: list[TeamMember], users: dict[str, User], projects: int) -> dict[str, Any]:
    mine = next((m.role for m in members if m.user_id == ctx.user.id), None)
    return {"id": t.id, "name": t.name, "description": t.description, "color": t.color,
            "created_at": t.created_at.isoformat(), "my_role": mine, "can_manage": _ws_admin(ctx) or mine == "admin",
            "projects": projects,
            "members": [{"user_id": m.user_id, "name": users[m.user_id].name, "email": users[m.user_id].email,
                         "role": m.role} for m in members if m.user_id in users]}


@router.get("/teams")
def list_teams(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    org = ctx.require_org()
    teams = ctx.db.scalars(select(Team).where(Team.org_id == org.id).order_by(Team.name)).all()
    tids = [t.id for t in teams]
    tms = ctx.db.scalars(select(TeamMember).where(TeamMember.team_id.in_(tids))).all() if tids else []
    mems = ctx.db.scalars(select(Membership).where(Membership.org_id == org.id)).all()
    users = {u.id: u for u in ctx.db.scalars(select(User).where(User.id.in_({m.user_id for m in mems})))}
    counts: dict[str, int] = {}
    for a in ctx.db.scalars(select(ProjectAccess).where(ProjectAccess.team_id.in_(tids))) if tids else []:
        counts[a.team_id or ""] = counts.get(a.team_id or "", 0) + 1
    return {"items": [_team_dict(ctx, t, [m for m in tms if m.team_id == t.id], users, counts.get(t.id, 0))
                      for t in teams],
            "members": [{"user_id": m.user_id, "name": users[m.user_id].name, "email": users[m.user_id].email,
                         "role": m.role} for m in mems if m.user_id in users],
            "roles": list(TEAM_ROLES), "colors": list(COLORS), "can_create": ctx.role != "viewer"}


@router.post("/teams")
def create_team(body: TeamIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    org = ctx.require_org()
    if ctx.role == "viewer":
        raise HTTPException(403, "Viewers can't create teams")
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Team name is required")
    if ctx.db.scalar(select(Team).where(Team.org_id == org.id, Team.name == name)):
        raise HTTPException(409, "A team with that name already exists")
    t = Team(org_id=org.id, name=name, description=body.description.strip(), color=_color(body.color),
             created_by=ctx.user.id)
    ctx.db.add(t)
    ctx.db.flush()
    ctx.db.add(TeamMember(team_id=t.id, user_id=ctx.user.id, role="admin"))
    audit(ctx.db, "team.created", ctx.user, org.id, target=t.id, name=name)
    ctx.db.commit()
    return {"id": t.id, "name": t.name, "color": t.color}


@router.patch("/teams/{tid}")
def patch_team(tid: str, body: TeamPatch, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    t = _team(ctx, tid)
    if not _can_manage_team(ctx, t):
        raise HTTPException(403, "Only team admins can change this team")
    if body.name is not None and body.name.strip():
        t.name = body.name.strip()
    if body.description is not None:
        t.description = body.description.strip()
    if body.color is not None:
        t.color = _color(body.color)
    audit(ctx.db, "team.updated", ctx.user, t.org_id, target=t.id)
    ctx.db.commit()
    return {"ok": True}


@router.delete("/teams/{tid}")
def delete_team(tid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    t = _team(ctx, tid)
    if not _can_manage_team(ctx, t):
        raise HTTPException(403, "Only team admins can delete this team")
    for a in ctx.db.scalars(select(ProjectAccess).where(ProjectAccess.team_id == t.id)):
        a.team_id = None  # its projects stay, open to the workspace at their general access
    for g in ctx.db.scalars(select(ProjectGrant).where(ProjectGrant.subject_type == "team",
                                                       ProjectGrant.subject_id == t.id)):
        ctx.db.delete(g)
    ctx.db.delete(t)
    audit(ctx.db, "team.deleted", ctx.user, t.org_id, target=t.id, name=t.name)
    ctx.db.commit()
    return {"ok": True}


@router.post("/teams/{tid}/members")
def add_team_member(tid: str, body: TeamMemberIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    t = _team(ctx, tid)
    if not _can_manage_team(ctx, t):
        raise HTTPException(403, "Only team admins can add members")
    if body.role not in TEAM_ROLES:
        raise HTTPException(422, "Role must be admin, editor or viewer")
    if ctx.db.scalar(select(Membership).where(Membership.org_id == t.org_id, Membership.user_id == body.user_id)) is None:
        raise HTTPException(422, "Only workspace members can join a team")
    tm = ctx.db.scalar(select(TeamMember).where(TeamMember.team_id == t.id, TeamMember.user_id == body.user_id))
    if tm:
        tm.role = body.role
    else:
        ctx.db.add(TeamMember(team_id=t.id, user_id=body.user_id, role=body.role))
        if body.user_id != ctx.user.id:
            notify(ctx.db, body.user_id, f"You were added to the {t.name} team", f"Role: team {body.role}.",
                   "/app/team?tab=teams")
    audit(ctx.db, "team.member_added", ctx.user, t.org_id, target=t.id, user=body.user_id, role=body.role)
    ctx.db.commit()
    return {"ok": True}


def _last_admin(ctx: Ctx, t: Team, user_id: str) -> bool:
    admins = ctx.db.scalars(select(TeamMember).where(TeamMember.team_id == t.id, TeamMember.role == "admin")).all()
    return len(admins) == 1 and admins[0].user_id == user_id and not _ws_admin(ctx)


@router.patch("/teams/{tid}/members/{user_id}")
def set_team_role(tid: str, user_id: str, body: TeamRoleIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    t = _team(ctx, tid)
    if not _can_manage_team(ctx, t):
        raise HTTPException(403, "Only team admins can change roles")
    if body.role not in TEAM_ROLES:
        raise HTTPException(422, "Role must be admin, editor or viewer")
    tm = ctx.db.scalar(select(TeamMember).where(TeamMember.team_id == t.id, TeamMember.user_id == user_id))
    if tm is None:
        raise HTTPException(404)
    if tm.role == "admin" and body.role != "admin" and _last_admin(ctx, t, user_id):
        raise HTTPException(409, "A team needs at least one admin")
    tm.role = body.role
    audit(ctx.db, "team.role_changed", ctx.user, t.org_id, target=t.id, user=user_id, role=body.role)
    ctx.db.commit()
    return {"ok": True}


@router.delete("/teams/{tid}/members/{user_id}")
def remove_team_member(tid: str, user_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    t = _team(ctx, tid)
    if user_id != ctx.user.id and not _can_manage_team(ctx, t):
        raise HTTPException(403, "Only team admins can remove members")
    tm = ctx.db.scalar(select(TeamMember).where(TeamMember.team_id == t.id, TeamMember.user_id == user_id))
    if tm is None:
        raise HTTPException(404)
    if tm.role == "admin" and _last_admin(ctx, t, user_id):
        raise HTTPException(409, "Make someone else a team admin first")
    ctx.db.delete(tm)
    audit(ctx.db, "team.member_removed", ctx.user, t.org_id, target=t.id, user=user_id)
    ctx.db.commit()
    return {"ok": True}


# =============================================================================== project access & sharing (PLT-021/022)
class AccessPatch(BaseModel):
    team_id: str | None = None
    personal: bool | None = None  # True: owned by its creator, not a team
    general: str | None = None
    protected_main: bool | None = None
    required_approvals: int | None = Field(default=None, ge=1, le=5)


class GrantIn(BaseModel):
    subject_type: str  # user|team
    subject_id: str
    level: str = "read"


class LevelIn(BaseModel):
    level: str


class GuestIn(BaseModel):
    email: str
    level: str = "read"


class LinkIn(BaseModel):
    label: str = Field(default="", max_length=80)
    expires_days: int | None = Field(default=None, ge=1, le=365)


def _access_row(ctx: Ctx, p: Project) -> ProjectAccess:
    a = ctx.db.get(ProjectAccess, p.id)
    if a is None:
        a = ProjectAccess(project_id=p.id, general="edit")
        ctx.db.add(a)
        ctx.db.flush()
    return a


def _sign(link_id: str) -> str:
    from aicad.airender.keystore import _secret

    sig = hmac.new(_secret(), f"fw-share:{link_id}".encode(), hashlib.sha256).digest()
    return f"{link_id}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')[:32]}"


def _link_dict(link: ShareLink) -> dict[str, Any]:
    tok = _sign(link.id)
    return {"id": link.id, "label": link.label, "url": f"{get_settings().app_url}/share/{tok}", "token": tok,
            "created_at": link.created_at.isoformat(), "uses": link.uses,
            "expires_at": link.expires_at.isoformat() if link.expires_at else None,
            "last_used_at": link.last_used_at.isoformat() if link.last_used_at else None,
            "expired": bool(link.expires_at and link.expires_at < utcnow())}


@router.get("/projects/{project_id}/access")
def get_access(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "read")
    acc: permissions.Access = ctx.project_access  # type: ignore[attr-defined]
    out: dict[str, Any] = {"me": acc.as_dict(), "project": {"id": p.id, "name": p.name,
                                                             "created_by": p.created_by}}
    grants = ctx.db.scalars(select(ProjectGrant).where(ProjectGrant.project_id == p.id)).all()
    users = {u.id: u for u in ctx.db.scalars(select(User).where(User.id.in_(
        {g.subject_id for g in grants if g.subject_type == "user"} | {p.created_by or ""})))}
    teams = {t.id: t for t in ctx.db.scalars(select(Team).where(Team.org_id == p.org_id))}
    out["owner"] = _user_brief(users.get(p.created_by or ""))
    out["grants"] = [{"id": g.id, "subject_type": g.subject_type, "subject_id": g.subject_id, "level": g.level,
                      "guest": g.guest,
                      "name": (users[g.subject_id].name if g.subject_type == "user" and g.subject_id in users
                               else teams[g.subject_id].name if g.subject_id in teams else "Removed"),
                      "email": users[g.subject_id].email if g.subject_type == "user" and g.subject_id in users else None,
                      "color": teams[g.subject_id].color if g.subject_id in teams else None}
                     for g in grants]
    if acc.guest:  # guests see who else has access, not their email addresses
        out["owner"] = out["owner"] and {**out["owner"], "email": ""}
        for g in out["grants"]:
            g["email"] = None if g["subject_id"] != ctx.user.id else g["email"]
    if acc.member_role:
        mems = ctx.db.scalars(select(Membership).where(Membership.org_id == p.org_id)).all()
        mu = {u.id: u for u in ctx.db.scalars(select(User).where(User.id.in_({m.user_id for m in mems})))}
        out["members"] = [{"user_id": m.user_id, "name": mu[m.user_id].name, "email": mu[m.user_id].email,
                           "role": m.role} for m in mems if m.user_id in mu]
        out["teams"] = [{"id": t.id, "name": t.name, "color": t.color} for t in teams.values()]
    if acc.level == "admin":
        out["links"] = [_link_dict(link) for link in ctx.db.scalars(
            select(ShareLink).where(ShareLink.project_id == p.id, ShareLink.revoked.is_(False))
            .order_by(ShareLink.created_at.desc()))]
        out["pending_guests"] = [{"id": i.id, "email": i.email, "level": gi.level,
                                  "expires_at": i.expires_at.isoformat()}
                                 for gi, i in ctx.db.execute(select(GuestInvite, Invite).join(
                                     Invite, Invite.id == GuestInvite.invite_id).where(
                                     GuestInvite.project_id == p.id, Invite.accepted_at.is_(None),
                                     Invite.revoked.is_(False))).all()]
    return out


@router.patch("/projects/{project_id}/access")
def patch_access(project_id: str, body: AccessPatch, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "read")
    if not ctx.project_access.at_least("admin"):  # type: ignore[attr-defined]
        raise HTTPException(403, "Only the project's admins can change who has access")
    a = _access_row(ctx, p)
    changes: dict[str, Any] = {}
    if body.personal:
        if a.team_id:
            changes["team"] = None
        a.team_id = None
    elif body.team_id is not None:
        t = ctx.db.get(Team, body.team_id)
        if t is None or t.org_id != p.org_id:
            raise HTTPException(422, "Unknown team")
        if a.team_id != t.id and a.general == "edit" and body.general is None:
            a.general = "read"  # a team project is read-only to the rest of the workspace unless widened
            changes["general"] = "read"
        a.team_id = t.id
        changes["team"] = t.name
    if body.general is not None:
        if body.general not in GENERAL_LEVELS:
            raise HTTPException(422, "General access must be none, read, comment or edit")
        a.general = body.general
        changes["general"] = body.general
    if body.protected_main is not None:
        a.protected_main = body.protected_main
        changes["protected_main"] = body.protected_main
    if body.required_approvals is not None:
        a.required_approvals = body.required_approvals
        changes["required_approvals"] = body.required_approvals
    a.updated_at = utcnow()
    audit(ctx.db, "access.changed", ctx.user, p.org_id, target=p.id, **changes)
    ctx.db.commit()
    return {"ok": True, **changes}


@router.post("/projects/{project_id}/grants")
def add_grant(project_id: str, body: GrantIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "admin")
    if body.level not in GRANT_LEVELS:
        raise HTTPException(422, "Level must be read, comment or edit")
    if body.subject_type == "user":
        if ctx.db.scalar(select(Membership).where(Membership.org_id == p.org_id,
                                                  Membership.user_id == body.subject_id)) is None:
            raise HTTPException(422, "Invite people outside the workspace as guests by email")
    elif body.subject_type == "team":
        t = ctx.db.get(Team, body.subject_id)
        if t is None or t.org_id != p.org_id:
            raise HTTPException(422, "Unknown team")
    else:
        raise HTTPException(422, "Share with a person or a team")
    g = ctx.db.scalar(select(ProjectGrant).where(ProjectGrant.project_id == p.id,
                                                 ProjectGrant.subject_type == body.subject_type,
                                                 ProjectGrant.subject_id == body.subject_id))
    if g:
        g.level = body.level
    else:
        g = ProjectGrant(project_id=p.id, subject_type=body.subject_type, subject_id=body.subject_id,
                         level=body.level, created_by=ctx.user.id)
        ctx.db.add(g)
    if body.subject_type == "user" and body.subject_id != ctx.user.id:
        notify(ctx.db, body.subject_id, f"{ctx.user.name} shared {p.name} with you",
               f"You can {permissions.LEVEL_LABEL[body.level]} it.", f"/app/projects/{p.id}")
    audit(ctx.db, "access.granted", ctx.user, p.org_id, target=p.id, subject_type=body.subject_type,
          subject=body.subject_id, level=body.level)
    ctx.db.commit()
    return {"ok": True, "id": g.id}


def _grant(ctx: Ctx, project_id: str, gid: str) -> tuple[Project, ProjectGrant]:
    p = _projects_mod()._project(ctx, project_id, "admin")
    g = ctx.db.get(ProjectGrant, gid)
    if g is None or g.project_id != p.id:
        raise HTTPException(404)
    return p, g


@router.patch("/projects/{project_id}/grants/{gid}")
def change_grant(project_id: str, gid: str, body: LevelIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p, g = _grant(ctx, project_id, gid)
    if body.level not in GRANT_LEVELS:
        raise HTTPException(422, "Level must be read, comment or edit")
    g.level = body.level
    audit(ctx.db, "access.granted", ctx.user, p.org_id, target=p.id, subject_type=g.subject_type,
          subject=g.subject_id, level=body.level)
    ctx.db.commit()
    return {"ok": True}


@router.delete("/projects/{project_id}/grants/{gid}")
def remove_grant(project_id: str, gid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p, g = _grant(ctx, project_id, gid)
    ctx.db.delete(g)
    audit(ctx.db, "access.revoked", ctx.user, p.org_id, target=p.id, subject_type=g.subject_type,
          subject=g.subject_id)
    ctx.db.commit()
    return {"ok": True}


@router.post("/projects/{project_id}/guests")
def invite_guest(project_id: str, body: GuestIn, ctx: Ctx = Depends(confirmed_ctx)) -> dict[str, Any]:
    """Share with someone by email. A workspace member gets a grant; anyone else is invited as a guest with access
    to this project only (no workspace seat; PD-50)."""
    p = _projects_mod()._project(ctx, project_id, "admin")
    if body.level not in GRANT_LEVELS:
        raise HTTPException(422, "Level must be read, comment or edit")
    email = normalize_email(body.email)
    if not valid_email(email):
        raise HTTPException(422, "Invalid email")
    org = ctx.db.get(Organization, p.org_id)
    user = ctx.db.scalar(select(User).where(User.email == email))
    if user is not None:
        member = ctx.db.scalar(select(Membership).where(Membership.org_id == p.org_id, Membership.user_id == user.id))
        g = ctx.db.scalar(select(ProjectGrant).where(ProjectGrant.project_id == p.id,
                                                     ProjectGrant.subject_type == "user",
                                                     ProjectGrant.subject_id == user.id))
        if g:
            g.level = body.level
        else:
            ctx.db.add(ProjectGrant(project_id=p.id, subject_type="user", subject_id=user.id, level=body.level,
                                    guest=member is None, created_by=ctx.user.id))
        notify(ctx.db, user.id, f"{ctx.user.name} shared {p.name} with you",
               f"You can {permissions.LEVEL_LABEL[body.level]} it.", f"/app/projects/{p.id}")
        send_email(ctx.db, email, f"{ctx.user.name} shared {p.name} with you on Formwright",
                   f"{ctx.user.name} gave you {body.level} access to the part {p.name}.",
                   f"{get_settings().app_url}/app/projects/{p.id}")
        audit(ctx.db, "access.granted", ctx.user, p.org_id, target=p.id, subject_type="user", subject=user.id,
              level=body.level, guest=member is None)
        ctx.db.commit()
        return {"ok": True, "invited": False, "guest": member is None}
    token = new_token()
    inv = Invite(org_id=p.org_id, email=email, role="guest", token_hash=hash_token(token), invited_by=ctx.user.id,
                 expires_at=utcnow() + timedelta(days=14))
    ctx.db.add(inv)
    ctx.db.flush()
    ctx.db.add(GuestInvite(invite_id=inv.id, project_id=p.id, level=body.level))
    send_email(ctx.db, email, f"{ctx.user.name} shared {p.name} with you on Formwright",
               f"{ctx.user.name} ({org.name if org else 'Formwright'}) invited you to {body.level} the part "
               f"{p.name}. Guests see only this project.", f"{get_settings().app_url}/invite?token={token}")
    audit(ctx.db, "access.guest_invited", ctx.user, p.org_id, target=p.id, email=email, level=body.level)
    ctx.db.commit()
    return {"ok": True, "invited": True, "guest": True}


@router.delete("/projects/{project_id}/guests/{invite_id}")
def revoke_guest_invite(project_id: str, invite_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "admin")
    gi = ctx.db.get(GuestInvite, invite_id)
    inv = ctx.db.get(Invite, invite_id)
    if gi is None or inv is None or gi.project_id != p.id:
        raise HTTPException(404)
    inv.revoked = True
    audit(ctx.db, "access.guest_invite_revoked", ctx.user, p.org_id, target=p.id, email=inv.email)
    ctx.db.commit()
    return {"ok": True}


def accept_guest_invite(db: Any, inv: Invite, user: User) -> str | None:
    """Called by the invite-accept flow for role "guest": grant the project, no workspace membership."""
    gi = db.get(GuestInvite, inv.id)
    if gi is None:
        return None
    member = db.scalar(select(Membership).where(Membership.org_id == inv.org_id, Membership.user_id == user.id))
    g = db.scalar(select(ProjectGrant).where(ProjectGrant.project_id == gi.project_id,
                                             ProjectGrant.subject_type == "user", ProjectGrant.subject_id == user.id))
    if g is None:
        db.add(ProjectGrant(project_id=gi.project_id, subject_type="user", subject_id=user.id, level=gi.level,
                            guest=member is None, created_by=inv.invited_by))
    elif RANK[gi.level] > RANK[g.level]:
        g.level = gi.level
    audit(db, "access.guest_joined", user, inv.org_id, target=gi.project_id, level=gi.level)
    return gi.project_id


@router.post("/projects/{project_id}/share-links")
def create_link(project_id: str, body: LinkIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "admin")
    link = ShareLink(project_id=p.id, label=body.label.strip(), created_by=ctx.user.id,
                     expires_at=utcnow() + timedelta(days=body.expires_days) if body.expires_days else None)
    ctx.db.add(link)
    ctx.db.flush()
    audit(ctx.db, "access.link_created", ctx.user, p.org_id, target=p.id, link=link.id,
          expires_days=body.expires_days)
    ctx.db.commit()
    return _link_dict(link)


@router.delete("/projects/{project_id}/share-links/{lid}")
def revoke_link(project_id: str, lid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "admin")
    link = ctx.db.get(ShareLink, lid)
    if link is None or link.project_id != p.id:
        raise HTTPException(404)
    link.revoked = True
    audit(ctx.db, "access.link_revoked", ctx.user, p.org_id, target=p.id, link=link.id)
    ctx.db.commit()
    return {"ok": True}


@router.get("/shared-with-me")
def shared_with_me(ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Projects shared with me by grant (to me or a team I'm in), including guest access in other workspaces."""
    my_teams = set(ctx.db.scalars(select(TeamMember.team_id).where(TeamMember.user_id == ctx.user.id)))
    grants = ctx.db.scalars(select(ProjectGrant).where(
        ((ProjectGrant.subject_type == "user") & (ProjectGrant.subject_id == ctx.user.id))
        | ((ProjectGrant.subject_type == "team") & (ProjectGrant.subject_id.in_(my_teams or {""}))))).all()
    ps = [p for p in ctx.db.scalars(select(Project).where(Project.id.in_({g.project_id for g in grants})))
          if not p.archived]
    acc = permissions.access_map(ctx.db, ctx.user, ps)
    orgs = {o.id: o.name for o in ctx.db.scalars(select(Organization).where(
        Organization.id.in_({p.org_id for p in ps})))}
    names = _names(ctx, {p.created_by for p in ps})
    pm = _projects_mod()
    items = [{**pm.project_dict(p, names.get(p.created_by or "")), "access": acc[p.id].as_dict(),
              "workspace": orgs.get(p.org_id)} for p in ps if acc[p.id].at_least("read")]
    items.sort(key=lambda x: x["updated_at"], reverse=True)
    return {"items": items}


# =============================================================================== public read-only share links
def _link_from(token: str) -> tuple[Any, ShareLink, Project]:
    from aicad.platform.db import session_factory

    lid = token.split(".", 1)[0]
    if not re.fullmatch(r"[a-f0-9]{32}", lid) or not hmac.compare_digest(_sign(lid), token):
        raise HTTPException(404, "This link is invalid")
    db = session_factory()()
    link = db.get(ShareLink, lid)
    p = db.get(Project, link.project_id) if link else None
    if link is None or link.revoked or p is None:
        db.close()
        raise HTTPException(404, "This link was turned off by its owner")
    if link.expires_at and link.expires_at < utcnow():
        db.close()
        raise HTTPException(410, "This link has expired")
    return db, link, p


SHARE_FILES = {"model.glb": "model/gltf-binary", "topo.json": "application/json", "status.json": "application/json",
               "views.png": "image/png", "thumb.png": "image/png"}


@router.get("/share/{token}")
def share_view(token: str) -> dict[str, Any]:
    db, link, p = _link_from(token)
    try:
        pm = _projects_mod()
        ws = pm.main_workspace(p)  # links always show main
        st = pm._read_status(ws)
        root = ws / "revisions"
        revs = []
        if root.is_dir():
            for d in sorted((d for d in root.iterdir() if d.name.isdigit()), key=lambda d: -int(d.name))[:30]:
                cause = pm._cause(ws, int(d.name))
                revs.append({"n": int(d.name), "why": cause.get("cause"), "kind": cause.get("kind"),
                             "by": cause.get("by")})
        link.uses += 1
        link.last_used_at = utcnow()
        org = db.get(Organization, p.org_id)
        db.commit()
        edit = st.get("editable_params") or {}
        meta = st.get("param_meta") or {}
        return {"project": {"id": p.id, "name": p.name, "description": p.description, "builds": p.builds,
                            "updated_at": p.updated_at.isoformat()},
                "workspace": org.name if org else None, "read_only": True,
                "status": {k: st.get(k) for k in ("ok", "part", "material", "fingerprint", "checks", "mass",
                                                  "build_id", "features")},
                "params": [{"name": k, "value": v, **(meta.get(k) or {})} for k, v in edit.items()],
                "revisions": revs, "has_drawing": (ws / "drawings" / "sheet.svg").is_file(),
                "files": [n for n in SHARE_FILES if (ws / "out" / n).is_file()],
                "expires_at": link.expires_at.isoformat() if link.expires_at else None}
    finally:
        db.close()


@router.get("/share/{token}/files/{name}")
def share_file(token: str, name: str) -> FileResponse:
    db, _link, p = _link_from(token)
    try:
        ws = _projects_mod().main_workspace(p)
    finally:
        db.close()
    if name == "drawing.svg":
        f, mime = ws / "drawings" / "sheet.svg", "image/svg+xml"
    elif name in SHARE_FILES:
        f, mime = ws / "out" / name, SHARE_FILES[name]
    else:
        raise HTTPException(404)
    if not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, media_type=mime, headers={"Cache-Control": "no-store"})


@router.api_route("/share/{token}/{rest:path}", methods=["POST", "PUT", "PATCH", "DELETE"])
def share_write(token: str, rest: str) -> None:
    raise HTTPException(403, "Share links are read-only")


# =============================================================================== presence, locks, activity (PLT-010)
def _branch_names(ctx: Ctx, p: Project) -> dict[str, str]:
    return {"main": "main", **{b.id: b.name for b in ctx.db.scalars(select(Branch).where(Branch.project_id == p.id))}}


def _presence_snapshot(project_id: str, names: dict[str, str]) -> dict[str, Any]:
    from aicad.platform.routers.projects import _sessions

    lks = branches.locks(_sessions, project_id)  # type: ignore[arg-type]
    for lk in lks:
        lk["branch_name"] = names.get(lk["branch"], lk["branch"])
    users = branches.presence_list(project_id)
    for u in users:
        u["branch_names"] = [names.get(b, b) for b in u["branches"]]
        u["editing"] = next((lk for lk in lks if lk.get("user_id") == u["user_id"]), None)
    return {"type": "presence", "users": users, "locks": lks}


@router.get("/projects/{project_id}/collab")
def collab_state(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """One call for the Studio's collaboration bar: my access and branch, presence, locks, open merge requests."""
    p = _projects_mod()._project(ctx, project_id, "read")
    names = _branch_names(ctx, p)
    bid = branches.active_branch(p.id)
    if bid != "main" and bid not in names:
        bid = "main"
    open_mrs = ctx.db.scalars(select(MergeRequest).where(MergeRequest.project_id == p.id,
                                                         MergeRequest.status == "open")).all()
    return {"access": ctx.project_access.as_dict(), "branch": {"id": bid, "name": names.get(bid, "main")},  # type: ignore[attr-defined]
            **_presence_snapshot(p.id, names),
            "open_merge_requests": [{"id": m.id, "number": m.number, "title": m.title, "branch_id": m.branch_id}
                                    for m in open_mrs],
            "comments": len(ctx.db.scalars(select(Comment.id).where(Comment.project_id == p.id,
                                                                   Comment.resolved.is_(False))).all())}


@router.post("/projects/{project_id}/presence")
def presence_ping(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Heartbeat presence (for clients that can't hold an event stream open). Expires after 45 s."""
    p = _projects_mod()._project(ctx, project_id, "read")
    bid = branches.active_branch(p.id)
    branches.presence_join(p.id, ctx.user, bid, conn_id=f"hb-{ctx.user.id}")
    snap = _presence_snapshot(p.id, _branch_names(ctx, p))
    branches.broadcast(p.id, snap)
    return snap


@router.get("/projects/{project_id}/presence/stream")
async def presence_stream(project_id: str, once: bool = False, ctx: Ctx = Depends(verified_ctx)) -> StreamingResponse:
    """Server-sent events: who is here now (and on which branch), and who is editing. Joining is implicit."""
    p = _projects_mod()._project(ctx, project_id, "read")
    names = _branch_names(ctx, p)
    pid, user, bid = p.id, ctx.user, branches.active_branch(p.id)
    ctx.db.close()
    cid = branches.presence_join(pid, user, bid)
    branches.broadcast(pid, _presence_snapshot(pid, names))
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    branches.watchers(pid).add(q)

    async def gen():  # type: ignore[no-untyped-def]
        try:
            yield f"data: {json.dumps(_presence_snapshot(pid, names), default=str)}\n\n"
            if once:
                return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), 10)
                except TimeoutError:
                    branches.presence_touch(pid, cid)
                    ev = _presence_snapshot(pid, names)  # refresh locks (agent runs start and stop)
                yield f"data: {json.dumps(ev, default=str)}\n\n"
        finally:
            branches.watchers(pid).discard(q)
            branches.presence_leave(pid, cid)
            branches.broadcast(pid, _presence_snapshot(pid, names))

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


ACTIVITY = {
    "project.created": "created the project", "project.params_edited": "changed parameters",
    "project.revision_restored": "restored a revision", "project.undo_redo": "undid / redid a change",
    "project.duplicated": "duplicated the project", "project.manual_added": "added a feature",
    "project.manual_edited": "edited a feature", "project.manual_deleted": "deleted a feature",
    "project.manual_reordered": "reordered features", "project.manual_rollback": "moved the rollback bar",
    "access.changed": "changed access settings", "access.granted": "shared the project",
    "access.revoked": "removed someone's access", "access.guest_invited": "invited a guest",
    "access.guest_joined": "joined as a guest", "access.link_created": "created a read-only link",
    "access.link_revoked": "turned off a read-only link", "branch.created": "created a branch",
    "branch.deleted": "deleted a branch", "mr.opened": "opened a merge request", "mr.merged": "merged",
    "mr.closed": "closed a merge request", "mr.approved": "approved a merge request",
    "mr.changes_requested": "requested changes", "mr.reconciled": "asked the design agent to reconcile",
    "comment.added": "commented", "tag.created": "tagged a release",
}


def _activity_text(action: str, meta: dict[str, Any]) -> str:
    base = ACTIVITY.get(action)
    if base is None:
        if action.startswith("project.manual_"):
            base = "edited the feature tree"
        elif action.startswith("project."):
            base = action.split(".", 1)[1].replace("_", " ")
        else:
            base = action.replace(".", " ").replace("_", " ")
    if action == "project.params_edited" and isinstance(meta.get("changes"), dict):
        base += ": " + ", ".join(f"{k} {v.get('from')} → {v.get('to')}" for k, v in list(meta["changes"].items())[:4])
    if action == "project.revision_restored" and meta.get("revision"):
        base = f"restored revision {meta['revision']}"
    if action in ("mr.opened", "mr.merged", "mr.closed", "mr.approved", "mr.changes_requested") and meta.get("title"):
        base += f" !{meta.get('number', '')} “{meta['title']}”"
    if action == "branch.created" and meta.get("name"):
        base += f" “{meta['name']}”"
    if action == "tag.created" and meta.get("name"):
        base += f" {meta['name']}"
    return base


@router.get("/projects/{project_id}/activity")
def activity(project_id: str, limit: int = 40, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "read")
    limit = max(1, min(limit, 200))
    rows = ctx.db.scalars(select(AuditLog).where(AuditLog.target == p.id).order_by(AuditLog.created_at.desc())
                          .limit(limit)).all()
    runs = ctx.db.scalars(select(AgentRun).where(AgentRun.project_id == p.id).order_by(AgentRun.created_at.desc())
                          .limit(limit)).all()
    names = _names(ctx, {r.actor_id for r in rows} | {r.user_id for r in runs})
    bn = _branch_names(ctx, p)
    items = [{"id": r.id, "at": r.created_at.isoformat(), "who": names.get(r.actor_id or "", "Someone"),
              "user_id": r.actor_id, "kind": r.action, "text": _activity_text(r.action, r.meta or {}),
              "branch": bn.get((r.meta or {}).get("branch") or "main", "main")} for r in rows]
    for run in runs:
        state = {"ok": "built and verified" if run.verified else "finished", "failed": "stopped with an error",
                 "running": "is running", "stopped": "was stopped", "stopped_budget": "stopped at its budget"}
        items.append({"id": run.id, "at": run.created_at.isoformat(), "who": names.get(run.user_id or "", "Someone"),
                      "user_id": run.user_id, "kind": "agent.run",
                      "text": f"ran the design agent ({state.get(run.status, run.status)}"
                              + (f", {run.tokens} tokens)" if run.tokens else ")"), "branch": None})
    items.sort(key=lambda x: x["at"], reverse=True)
    return {"items": items[:limit]}


# =============================================================================== comments (PLT-010)
class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    revision: int | None = None
    mr_id: str | None = None
    parent_id: str | None = None


class CommentPatch(BaseModel):
    resolved: bool | None = None
    body: str | None = Field(default=None, max_length=5000)


def mentioned(body: str, people: list[User]) -> list[User]:
    """People named with @ (full name or first name, case-insensitive)."""
    low = body.lower()
    out = []
    for u in people:
        full, first = u.name.lower().strip(), u.name.lower().split()[0] if u.name.strip() else ""
        for cand in {full, first}:
            if cand and re.search(r"(?<![\w@])@" + re.escape(cand) + r"(?![\w])", low):
                out.append(u)
                break
    return out


def _comment_dict(c: Comment, names: dict[str, str], me: str) -> dict[str, Any]:
    return {"id": c.id, "body": c.body, "author": {"id": c.author_id, "name": names.get(c.author_id or "", "Someone")},
            "branch": c.branch, "revision": c.revision, "mr_id": c.mr_id, "parent_id": c.parent_id,
            "resolved": c.resolved, "created_at": c.created_at.isoformat(), "mine": c.author_id == me,
            "mentions": c.mentions or []}


@router.get("/projects/{project_id}/comments")
def list_comments(project_id: str, revision: int | None = None, mr_id: str | None = None,
                  ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "read")
    q = select(Comment).where(Comment.project_id == p.id)
    if revision is not None:
        q = q.where(Comment.revision == revision)
    q = q.where(Comment.mr_id == mr_id) if mr_id else q.where(Comment.mr_id.is_(None))
    rows = ctx.db.scalars(q.order_by(Comment.created_at)).all()
    names = _names(ctx, {c.author_id for c in rows})
    people = [{"id": u.id, "name": u.name} for u in permissions.readers(ctx.db, p)]
    return {"items": [_comment_dict(c, names, ctx.user.id) for c in rows], "people": people,
            "can_comment": ctx.project_access.at_least("comment")}  # type: ignore[attr-defined]


def _add_comment(ctx: Ctx, p: Project, body: CommentIn, link: str | None = None) -> Comment:
    if body.parent_id:
        parent = ctx.db.get(Comment, body.parent_id)
        if parent is None or parent.project_id != p.id:
            raise HTTPException(404, "Comment not found")
    readers = permissions.readers(ctx.db, p)
    who = [u for u in mentioned(body.body, readers) if u.id != ctx.user.id]
    c = Comment(project_id=p.id, author_id=ctx.user.id, branch=branches.active_branch(p.id), revision=body.revision,
                mr_id=body.mr_id, parent_id=body.parent_id, body=body.body.strip(), mentions=[u.id for u in who])
    ctx.db.add(c)
    ctx.db.flush()
    for u in who:
        notify(ctx.db, u.id, f"{ctx.user.name} mentioned you on {p.name}", body.body.strip()[:200],
               link or f"/app/projects/{p.id}?panel=activity")
    audit(ctx.db, "comment.added", ctx.user, p.org_id, target=p.id, comment=c.id, revision=body.revision,
          mr=body.mr_id)
    return c


@router.post("/projects/{project_id}/comments")
def add_comment(project_id: str, body: CommentIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "comment")
    if body.mr_id:
        mr = ctx.db.get(MergeRequest, body.mr_id)
        if mr is None or mr.project_id != p.id:
            raise HTTPException(404, "Merge request not found")
    c = _add_comment(ctx, p, body, f"/app/projects/{p.id}/merge/{body.mr_id}" if body.mr_id else None)
    ctx.db.commit()
    return _comment_dict(c, {ctx.user.id: ctx.user.name}, ctx.user.id)


@router.patch("/projects/{project_id}/comments/{cid}")
def patch_comment(project_id: str, cid: str, body: CommentPatch, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "comment")
    c = ctx.db.get(Comment, cid)
    if c is None or c.project_id != p.id:
        raise HTTPException(404)
    if body.body is not None:
        if c.author_id != ctx.user.id:
            raise HTTPException(403, "Only the author can edit a comment")
        c.body = body.body.strip() or c.body
    if body.resolved is not None:
        c.resolved = body.resolved
    ctx.db.commit()
    return {"ok": True}


@router.delete("/projects/{project_id}/comments/{cid}")
def delete_comment(project_id: str, cid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "comment")
    c = ctx.db.get(Comment, cid)
    if c is None or c.project_id != p.id:
        raise HTTPException(404)
    if c.author_id != ctx.user.id and not ctx.project_access.at_least("admin"):  # type: ignore[attr-defined]
        raise HTTPException(403, "Only the author or a project admin can delete a comment")
    ctx.db.delete(c)
    ctx.db.commit()
    return {"ok": True}


# =============================================================================== branches (CAD-062)
class BranchIn(BaseModel):
    name: str
    from_branch: str = "main"
    from_rev: int | None = None
    switch: bool = True


def _set_branch_cookie(resp: Response, project_id: str, branch_id: str) -> None:
    name = branches.cookie_name(project_id)
    if branch_id == "main":
        resp.delete_cookie(name, path="/")
    else:
        resp.set_cookie(name, branch_id, httponly=True, samesite="lax", secure=get_settings().cookie_secure,
                        path="/", max_age=90 * 86400)


def _branch_ws(p: Project, bid: str) -> Path:
    main = _projects_mod().main_workspace(p)
    return main if bid == "main" else branches.branch_dir(main, bid)


def _head(ws: Path) -> dict[str, Any]:
    pm = _projects_mod()
    st = pm._read_status(ws)
    return {"revision": pm.current_revision(ws), "latest": pm.latest_revision(ws), "ok": st.get("ok"),
            "build_id": st.get("build_id")}


def _branch_dict(ctx: Ctx, p: Project, b: Branch | None, names: dict[str, str], mrs: dict[str, MergeRequest]) -> dict[str, Any]:
    from aicad.platform.routers.projects import _sessions

    bid = b.id if b else "main"
    ws = _branch_ws(p, bid)
    lock = branches.lock_for(_sessions, p.id, bid)  # type: ignore[arg-type]
    mr = mrs.get(bid)
    return {"id": bid, "name": b.name if b else "main", "status": b.status if b else "open",
            "source": names.get(b.source, b.source) if b else None, "base_rev": b.base_rev if b else None,
            "created_by": names.get((b.created_by or "") if b else "", None),
            "created_at": b.created_at.isoformat() if b else p.created_at.isoformat(),
            "head": _head(ws) if ws.is_dir() else None, "lock": lock,
            "merge_request": {"id": mr.id, "number": mr.number, "status": mr.status} if mr else None}


@router.get("/projects/{project_id}/branches")
def list_branches(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "read")
    rows = ctx.db.scalars(select(Branch).where(Branch.project_id == p.id).order_by(Branch.created_at.desc())).all()
    names = {**_names(ctx, {b.created_by for b in rows}), "main": "main", **{b.id: b.name for b in rows}}
    mrs: dict[str, MergeRequest] = {}
    for m in ctx.db.scalars(select(MergeRequest).where(MergeRequest.project_id == p.id)
                            .order_by(MergeRequest.created_at)):
        mrs[m.branch_id] = m
    cur = branches.active_branch(p.id)
    if cur != "main" and not any(b.id == cur for b in rows):
        cur = "main"
    return {"current": cur, "items": [_branch_dict(ctx, p, None, names, mrs)]
            + [_branch_dict(ctx, p, b, names, mrs) for b in rows if b.status != "closed"],
            "access": ctx.project_access.as_dict()}  # type: ignore[attr-defined]


@router.post("/projects/{project_id}/branches")
async def create_branch(project_id: str, body: BranchIn, response: Response,
                        ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """"Work on a copy": a new branch from a revision of main (or of another branch). Needs edit access, but works
    while main is protected or someone else is editing it: that is what branches are for."""
    pm = _projects_mod()
    p = pm._project(ctx, project_id, "read")
    acc: permissions.Access = ctx.project_access  # type: ignore[attr-defined]
    if not acc.at_least("edit"):
        raise permissions._deny(acc, "edit")
    name = " ".join(body.name.split())
    if not branches.NAME_RE.match(name) or name.lower() == "main":
        raise HTTPException(422, "Branch names use letters, numbers, spaces and . _ - / (up to 47 characters)")
    if ctx.db.scalar(select(Branch).where(Branch.project_id == p.id, Branch.name == name)):
        raise HTTPException(409, "A branch with that name already exists")
    src_id = body.from_branch or "main"
    if src_id != "main":
        sb = ctx.db.get(Branch, src_id)
        if sb is None or sb.project_id != p.id:
            raise HTTPException(404, "Source branch not found")
    src_ws = _branch_ws(p, src_id)
    rev = body.from_rev
    if rev is not None and not (src_ws / "revisions" / str(rev)).is_dir():
        raise HTTPException(404, "Revision not found")
    if rev is None:
        rev = pm.current_revision(src_ws)
    with branches.use_branch(p.id, src_id):
        await pm.wait_finalized(p.id)  # never copy outputs while background exports are writing them
    b = Branch(project_id=p.id, name=name, source=src_id, base_rev=rev, created_by=ctx.user.id)
    ctx.db.add(b)
    ctx.db.flush()
    dst = branches.branch_dir(pm.main_workspace(p), b.id)
    needs_build = branches.fork_workspace(src_ws, dst, rev)
    with branches.use_branch(p.id, b.id):
        if needs_build:
            await pm._rebuild(p, dst, determinism=False, fast=True)  # a failing revision stays as it was
            pm.schedule_finalize(p, dst)
        src_name = "main" if src_id == "main" else ctx.db.get(Branch, src_id).name  # type: ignore[union-attr]
        pm._snapshot(p, dst, cause=f"Branch “{name}” started from {src_name}" + (f" revision {rev}" if rev else ""),
                     kind="branch", by=ctx.user.name)
    audit(ctx.db, "branch.created", ctx.user, p.org_id, target=p.id, branch=b.id, name=name, source=src_id, rev=rev)
    ctx.db.commit()
    if body.switch:
        _set_branch_cookie(response, p.id, b.id)
    return {"id": b.id, "name": b.name, "base_rev": rev, "switched": body.switch}


@router.post("/projects/{project_id}/branches/{bid}/checkout")
def checkout(project_id: str, bid: str, response: Response, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "read")
    if bid != "main":
        b = ctx.db.get(Branch, bid)
        if b is None or b.project_id != p.id or b.status == "closed":
            raise HTTPException(404, "Branch not found")
        if not _branch_ws(p, bid).is_dir():
            raise HTTPException(410, "This branch's files are gone")
    _set_branch_cookie(response, p.id, bid)
    return {"ok": True, "branch": bid}


@router.delete("/projects/{project_id}/branches/{bid}")
def delete_branch(project_id: str, bid: str, response: Response, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    from aicad.platform.routers.projects import _sessions

    p = _projects_mod()._project(ctx, project_id, "read")
    b = ctx.db.get(Branch, bid)
    if b is None or b.project_id != p.id:
        raise HTTPException(404, "Branch not found")
    acc: permissions.Access = ctx.project_access  # type: ignore[attr-defined]
    if b.created_by != ctx.user.id and not acc.at_least("admin"):
        raise HTTPException(403, "Only the branch's creator or a project admin can delete it")
    if branches.lock_for(_sessions, p.id, b.id):  # type: ignore[arg-type]
        raise HTTPException(409, "The design agent is working on this branch")
    b.status = "closed"
    for m in ctx.db.scalars(select(MergeRequest).where(MergeRequest.branch_id == b.id,
                                                       MergeRequest.status == "open")):
        m.status = "closed"
    _sessions.pop(f"{p.id}@{b.id}", None)
    shutil.rmtree(_branch_ws(p, b.id), ignore_errors=True)
    audit(ctx.db, "branch.deleted", ctx.user, p.org_id, target=p.id, branch=b.id, name=b.name)
    ctx.db.commit()
    if branches.active_branch(p.id) == b.id:
        _set_branch_cookie(response, p.id, "main")
    return {"ok": True}


# =============================================================================== merge requests (PLT-017/023/024)
class MRIn(BaseModel):
    branch_id: str
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=8000)


class ReviewIn(BaseModel):
    state: str  # approve|request_changes|comment
    body: str = Field(default="", max_length=5000)


class MergeIn(BaseModel):
    resolutions: dict[str, Any] = {}


def _mr(ctx: Ctx, p: Project, mid: str) -> tuple[MergeRequest, Branch]:
    mr = ctx.db.get(MergeRequest, mid)
    if mr is None or mr.project_id != p.id:
        raise HTTPException(404, "Merge request not found")
    b = ctx.db.get(Branch, mr.branch_id)
    if b is None:
        raise HTTPException(404, "Branch not found")
    return mr, b


def _src(ws: Path) -> str:
    f = ws / "model.py"
    return f.read_text(encoding="utf-8") if f.is_file() else ""


def _causes_since(ws: Path, after: int | None) -> list[dict[str, Any]]:
    pm = _projects_mod()
    root = ws / "revisions"
    out = []
    if root.is_dir():
        for d in sorted((d for d in root.iterdir() if d.name.isdigit()), key=lambda d: int(d.name)):
            n = int(d.name)
            if after is None or n > after:
                c = pm._cause(ws, n)
                if c.get("kind") != "branch":
                    out.append({"n": n, "why": c.get("cause"), "by": c.get("by"), "kind": c.get("kind")})
    return out


def _approvals(ctx: Ctx, mr: MergeRequest) -> tuple[list[dict[str, Any]], int, bool]:
    reviews = ctx.db.scalars(select(Review).where(Review.mr_id == mr.id).order_by(Review.created_at)).all()
    latest: dict[str, Review] = {}
    for r in reviews:
        if r.state in ("approved", "changes_requested"):
            latest[r.user_id] = r
    names = _names(ctx, {r.user_id for r in reviews})
    approved = sum(1 for u, r in latest.items() if r.state == "approved" and u != mr.created_by)
    blocked = any(r.state == "changes_requested" for r in latest.values())
    return ([{"id": r.id, "user": {"id": r.user_id, "name": names.get(r.user_id, "Someone")}, "state": r.state,
              "body": r.body, "created_at": r.created_at.isoformat()} for r in reviews], approved, blocked)


def _plain_conflicts(conflicts: list[dict[str, Any]], meta: dict[str, Any], show_code: bool,
                     main_causes: list[dict[str, Any]], branch_causes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in conflicts:
        d = {"id": c["id"], "kind": c["kind"], "key": c["key"]}
        if c["kind"] == "param":
            m = meta.get(c["key"]) or {}
            d.update(label=m.get("label") or c["key"], unit=m.get("unit"), base=c["base"], ours=c["ours"],
                     theirs=c["theirs"])
        elif c["kind"] == "feature":
            def brief(f: Any) -> Any:
                return None if f is None else {"name": f.get("name"), "op": f.get("op"),
                                               "suppressed": bool(f.get("suppressed"))}
            d.update(label=c.get("name"), base=brief(c["base"]), ours=brief(c["ours"]), theirs=brief(c["theirs"]))
        else:  # design steps written by the agent: plain language, the script stays internal
            d.update(label=f"Design steps (change {c['key']})",
                     ours_changes=[x["why"] for x in main_causes if x.get("why")][-4:],
                     theirs_changes=[x["why"] for x in branch_causes if x.get("why")][-4:])
            if show_code:
                d.update(code={"base": c["base"], "ours": c["ours"], "theirs": c["theirs"]})
        out.append(d)
    return out


def _resolutions(mr: MergeRequest, conflicts: list[dict[str, Any]], chosen: dict[str, Any]) -> dict[str, Any]:
    """Map the person's choices (ours/theirs/agent) to merge resolutions; "agent" uses the stored proposal."""
    props = (mr.reconcile or {}).get("resolutions") or {}
    by_id = {c["id"]: c for c in conflicts}
    out: dict[str, Any] = {}
    for cid, choice in chosen.items():
        if cid not in by_id:
            continue
        if choice in ("ours", "theirs"):
            out[cid] = choice
        elif choice == "agent":
            r = reconcile.to_resolution(by_id[cid], props.get(cid))
            if r is None:
                raise HTTPException(409, "There is no design-agent proposal for that conflict. Ask the design agent "
                                         "to reconcile first, or pick a side.")
            out[cid] = r
    return out


def _mr_state(ctx: Ctx, p: Project, mr: MergeRequest, b: Branch) -> dict[str, Any]:
    pm = _projects_mod()
    main_ws, bws = pm.main_workspace(p), _branch_ws(p, b.id)
    base, ours, theirs = branches.merge_base_source(bws), _src(main_ws), _src(bws)
    ff = merge.same_model(base, ours)
    dry = merge.merge_model(base, ours, theirs) if not ff else {"all_conflicts": [], "conflicts": []}
    bst, mst = pm._read_status(bws), pm._read_status(main_ws)
    meta = {**(mst.get("param_meta") or {}), **(bst.get("param_meta") or {})}
    main_causes = _causes_since(main_ws, b.base_rev if b.source == "main" else None) if not ff else []
    branch_causes = _causes_since(bws, None)
    acc: permissions.Access = ctx.project_access  # type: ignore[attr-defined]
    reviews, approved, blocked = _approvals(ctx, mr)
    checks = [{"id": c.get("id"), "name": c.get("name") or c.get("title") or c.get("id"),
               "passed": c.get("passed"), "gating": c.get("gating")} for c in bst.get("checks") or []]
    blockers = []
    if mr.status != "open":
        blockers.append(f"This merge request is {mr.status}.")
    if not acc.at_least("edit"):
        blockers.append("You need edit access to merge.")
    if acc.protected_main and approved < acc.required_approvals:
        blockers.append(f"Main is protected: needs {acc.required_approvals} approval"
                        f"{'s' if acc.required_approvals > 1 else ''} from someone other than the author "
                        f"({approved} so far).")
    if blocked:
        blockers.append("A reviewer requested changes.")
    if bst and not bst.get("ok"):
        blockers.append("The branch's latest build does not pass its checks.")
    names = _names(ctx, {mr.created_by, mr.merged_by})
    return {"id": mr.id, "number": mr.number, "title": mr.title, "description": mr.description,
            "status": mr.status, "created_at": mr.created_at.isoformat(),
            "author": {"id": mr.created_by, "name": names.get(mr.created_by or "", "Someone")},
            "merged_by": names.get(mr.merged_by or "") if mr.merged_by else None,
            "merged_at": mr.merged_at.isoformat() if mr.merged_at else None, "merge_rev": mr.merge_rev,
            "branch": {"id": b.id, "name": b.name, "status": b.status, "base_rev": b.base_rev,
                       "head": _head(bws) if bws.is_dir() else None},
            "main": {"head": _head(main_ws)},
            "fast_forward": ff,
            "params": {"branch": merge.diff_params(merge.read_params(base), merge.read_params(theirs)),
                       "main": merge.diff_params(merge.read_params(base), merge.read_params(ours)),
                       "meta": {k: {"label": v.get("label"), "unit": v.get("unit")} for k, v in meta.items()}},
            "features": {"branch": merge.diff_features(merge.read_manual(base), merge.read_manual(theirs)),
                         "main": merge.diff_features(merge.read_manual(base), merge.read_manual(ours))},
            "changes": {"branch": branch_causes, "main": main_causes},
            "conflicts": _plain_conflicts(dry["all_conflicts"], meta, ctx.actor.is_superadmin, main_causes,
                                          branch_causes),
            "checks": {"ok": bst.get("ok"), "items": checks},
            "reviews": reviews, "approvals": approved, "required_approvals": acc.required_approvals,
            "protected_main": acc.protected_main, "changes_requested": blocked,
            "reconcile": {"note": (mr.reconcile or {}).get("note"), "tokens": (mr.reconcile or {}).get("tokens"),
                          "ids": sorted(((mr.reconcile or {}).get("resolutions") or {}).keys())},
            "can_merge": not blockers, "blockers": blockers,
            "can_review": acc.at_least("comment") and mr.status == "open",
            "can_approve": acc.at_least("edit") and mr.created_by != ctx.user.id and mr.status == "open"
            and not any(r["user"]["id"] == ctx.user.id and r["state"] == "approved" for r in reviews[-1:])}


@router.get("/projects/{project_id}/merge-requests")
def list_mrs(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "read")
    rows = ctx.db.scalars(select(MergeRequest).where(MergeRequest.project_id == p.id)
                          .order_by(MergeRequest.created_at.desc())).all()
    names = _names(ctx, {m.created_by for m in rows})
    bn = _branch_names(ctx, p)
    return {"items": [{"id": m.id, "number": m.number, "title": m.title, "status": m.status,
                       "branch": {"id": m.branch_id, "name": bn.get(m.branch_id, "?")},
                       "author": names.get(m.created_by or "", "Someone"), "created_at": m.created_at.isoformat(),
                       "merged_at": m.merged_at.isoformat() if m.merged_at else None} for m in rows]}


@router.post("/projects/{project_id}/merge-requests")
def open_mr(project_id: str, body: MRIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "read")
    acc: permissions.Access = ctx.project_access  # type: ignore[attr-defined]
    if not acc.at_least("edit"):
        raise permissions._deny(acc, "edit")
    b = ctx.db.get(Branch, body.branch_id)
    if b is None or b.project_id != p.id or b.status != "open":
        raise HTTPException(404, "Branch not found")
    if ctx.db.scalar(select(MergeRequest).where(MergeRequest.branch_id == b.id, MergeRequest.status == "open")):
        raise HTTPException(409, "This branch already has an open merge request")
    n = len(ctx.db.scalars(select(MergeRequest.id).where(MergeRequest.project_id == p.id)).all()) + 1
    mr = MergeRequest(project_id=p.id, branch_id=b.id, number=n, title=body.title.strip(),
                      description=body.description.strip(), created_by=ctx.user.id)
    ctx.db.add(mr)
    ctx.db.flush()
    for u in permissions.readers(ctx.db, p):
        if u.id != ctx.user.id and permissions.project_access(ctx.db, u, p).at_least("admin"):
            notify(ctx.db, u.id, f"{ctx.user.name} asks to merge “{b.name}” into {p.name}", mr.title,
                   f"/app/projects/{p.id}/merge/{mr.id}")
    audit(ctx.db, "mr.opened", ctx.user, p.org_id, target=p.id, mr=mr.id, number=n, title=mr.title, branch=b.id)
    ctx.db.commit()
    return {"id": mr.id, "number": n}


@router.get("/projects/{project_id}/merge-requests/{mid}")
def get_mr(project_id: str, mid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "read")
    mr, b = _mr(ctx, p, mid)
    return _mr_state(ctx, p, mr, b)


@router.post("/projects/{project_id}/merge-requests/{mid}/reviews")
def review(project_id: str, mid: str, body: ReviewIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "comment")
    mr, _b = _mr(ctx, p, mid)
    if mr.status != "open":
        raise HTTPException(409, f"This merge request is {mr.status}")
    acc: permissions.Access = ctx.project_access  # type: ignore[attr-defined]
    state = {"approve": "approved", "request_changes": "changes_requested", "comment": "commented"}.get(body.state)
    if state is None:
        raise HTTPException(422, "Review must approve, request changes or comment")
    if state == "approved":
        if mr.created_by == ctx.user.id:
            raise HTTPException(403, "You can't approve your own merge request")
        if not acc.at_least("edit"):
            raise HTTPException(403, "Approving needs edit access")
    ctx.db.add(Review(mr_id=mr.id, user_id=ctx.user.id, state=state, body=body.body.strip()))
    if body.body.strip():
        _add_comment(ctx, p, CommentIn(body=body.body, mr_id=mr.id), f"/app/projects/{p.id}/merge/{mr.id}")
    if mr.created_by and mr.created_by != ctx.user.id:
        verb = {"approved": "approved", "changes_requested": "requested changes on", "commented": "commented on"}[state]
        notify(ctx.db, mr.created_by, f"{ctx.user.name} {verb} !{mr.number} {mr.title}", body.body[:200],
               f"/app/projects/{p.id}/merge/{mr.id}")
    if state != "commented":
        audit(ctx.db, "mr.approved" if state == "approved" else "mr.changes_requested", ctx.user, p.org_id,
              target=p.id, mr=mr.id, number=mr.number, title=mr.title)
    ctx.db.commit()
    return {"ok": True, "state": state}


@router.post("/projects/{project_id}/merge-requests/{mid}/close")
def close_mr(project_id: str, mid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "read")
    mr, _b = _mr(ctx, p, mid)
    acc: permissions.Access = ctx.project_access  # type: ignore[attr-defined]
    if mr.created_by != ctx.user.id and not acc.at_least("admin"):
        raise HTTPException(403, "Only the author or a project admin can close it")
    if mr.status != "open":
        raise HTTPException(409, f"Already {mr.status}")
    mr.status = "closed"
    audit(ctx.db, "mr.closed", ctx.user, p.org_id, target=p.id, mr=mr.id, number=mr.number, title=mr.title)
    ctx.db.commit()
    return {"ok": True}


@router.post("/projects/{project_id}/merge-requests/{mid}/compare")
async def compare_mr(project_id: str, mid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """3D compare: main's current part vs the branch's (added / removed material), like the revision compare."""
    from aicad.agent import worker

    pm = _projects_mod()
    p = pm._project(ctx, project_id, "read")
    mr, b = _mr(ctx, p, mid)
    main_ws, bws = pm.main_workspace(p), _branch_ws(p, b.id)
    for bid in ("main", b.id):
        with branches.use_branch(p.id, bid):
            await pm.wait_finalized(p.id)
    a, c = main_ws / "out" / "part.step", bws / "out" / "part.step"
    if not a.is_file() or not c.is_file():
        raise HTTPException(404, "Both main and the branch need a built part to compare")
    out = bws / ".fw" / "compare" / f"mr{mr.number}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    r = await worker.diff(p.org_id, a, c, out)
    if not r.get("ok"):
        raise HTTPException(422, "The 3D compare could not be computed for these two parts. Try again after both "
                                 "have finished building.")
    url = f"/api/projects/{p.id}/merge-requests/{mr.id}/compare-files"
    return {"added_mm3": r.get("added_mm3"), "removed_mm3": r.get("removed_mm3"),
            "added_url": f"{url}/added.json" if (out / "added.json").is_file() else None,
            "removed_url": f"{url}/removed.json" if (out / "removed.json").is_file() else None,
            "main_topo": f"{url}/main_topo.json", "branch_topo": f"{url}/branch_topo.json"}


@router.get("/projects/{project_id}/merge-requests/{mid}/compare-files/{name}")
def mr_compare_file(project_id: str, mid: str, name: str, ctx: Ctx = Depends(verified_ctx)) -> FileResponse:
    pm = _projects_mod()
    p = pm._project(ctx, project_id, "read")
    mr, b = _mr(ctx, p, mid)
    bws = _branch_ws(p, b.id)
    files = {"added.json": bws / ".fw" / "compare" / f"mr{mr.number}" / "added.json",
             "removed.json": bws / ".fw" / "compare" / f"mr{mr.number}" / "removed.json",
             "main_topo.json": pm.main_workspace(p) / "out" / "topo.json",
             "branch_topo.json": bws / "out" / "topo.json"}
    f = files.get(name)
    if f is None or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, media_type="application/json", headers={"Cache-Control": "no-store"})


@router.post("/projects/{project_id}/merge-requests/{mid}/reconcile")
async def reconcile_mr(project_id: str, mid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Optional: ask the design agent to propose resolutions for the conflicts (metered in tokens). Proposals are
    shown next to "take main" / "take branch"; nothing is applied until the person merges."""
    pm = _projects_mod()
    p = pm._project(ctx, project_id, "read")
    acc: permissions.Access = ctx.project_access  # type: ignore[attr-defined]
    if not acc.as_dict()["can_agent"]:
        raise permissions._deny(acc, "agent")
    mr, b = _mr(ctx, p, mid)
    if mr.status != "open":
        raise HTTPException(409, f"This merge request is {mr.status}")
    allowed, reason, cta = pm.can_run_agent(ctx)
    if not allowed:
        raise HTTPException(402, {"message": reason, "cta": cta})
    main_ws, bws = pm.main_workspace(p), _branch_ws(p, b.id)
    base, ours, theirs = branches.merge_base_source(bws), _src(main_ws), _src(bws)
    dry = merge.merge_model(base, ours, theirs)
    if not dry["all_conflicts"]:
        raise HTTPException(409, "Nothing to reconcile: there are no conflicts")
    org = ctx.require_org()
    budget, _why = metering.run_budget(ctx.db, org, ctx.user, None, ctx.god_on("bypass_tokens"))
    ctx_info = {"part": p.name, "main_changes": [x["why"] for x in _causes_since(main_ws, b.base_rev)][-6:],
                "branch_changes": [x["why"] for x in _causes_since(bws, None)][-6:], "merge_request": mr.title}
    proposal, cost = await reconcile.propose(bws / ".fw" / "reconcile", dry["all_conflicts"], ctx_info,
                                             budget * metering.USD_PER_TOKEN if budget else None)
    tokens = metering.tokens_for_usd(cost) if cost else 0
    if budget is not None:
        tokens = min(tokens, budget)
    charged = 0 if ctx.god_on("bypass_tokens") else tokens
    if charged:
        debit(ctx.db, org, charged, "usage", f"Merge reconcile · {p.name}", ctx.user, ref=p.id)
    ids = {c["id"] for c in dry["all_conflicts"]}
    mr.reconcile = {"resolutions": {k: v for k, v in (proposal.get("resolutions") or {}).items() if k in ids},
                    "note": proposal.get("note"), "tokens": charged}
    audit(ctx.db, "mr.reconciled", ctx.user, p.org_id, target=p.id, mr=mr.id, tokens=charged)
    ctx.db.commit()
    return {"ok": True, "note": mr.reconcile["note"], "tokens": charged, "ids": sorted(mr.reconcile["resolutions"])}


@router.post("/projects/{project_id}/merge-requests/{mid}/merge")
async def do_merge(project_id: str, mid: str, body: MergeIn, response: Response,
                   ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    """Merge the branch into main: fast-forward when main hasn't moved since the branch started, otherwise a 3-way
    merge (parameters and features structurally, the design source as text). The merged part must rebuild and pass
    its gating checks, else nothing changes and the reason is returned."""
    from aicad.platform.plain import build_error

    pm = _projects_mod()
    p = pm._project(ctx, project_id, "read")
    mr, b = _mr(ctx, p, mid)
    state = _mr_state(ctx, p, mr, b)
    if not state["can_merge"]:
        raise HTTPException(409, {"message": " ".join(state["blockers"]), "code": "merge_blocked"})
    for bid in ("main", b.id):
        lk = branches.lock_for(pm._sessions, p.id, bid)
        if lk:
            raise HTTPException(409, {"message": f"{lk['name']} is editing {'main' if bid == 'main' else 'the branch'} "
                                                 "(design agent running). Merge when the run has finished.",
                                      "code": "edit_locked", "lock": lk})
    main_ws, bws = pm.main_workspace(p), _branch_ws(p, b.id)
    base, ours, theirs = branches.merge_base_source(bws), _src(main_ws), _src(bws)
    ff = merge.same_model(base, ours)
    if ff:
        merged = theirs
    else:
        dry = merge.merge_model(base, ours, theirs)
        res = merge.merge_model(base, ours, theirs, _resolutions(mr, dry["all_conflicts"], body.resolutions))
        if res["source"] is None:
            meta = pm._read_status(bws).get("param_meta") or {}
            raise HTTPException(409, {"message": f"{len(res['conflicts'])} conflict(s) need a decision before merging.",
                                      "code": "conflicts",
                                      "conflicts": _plain_conflicts(res["conflicts"], meta, ctx.actor.is_superadmin,
                                                                    [], [])})
        merged = res["source"]
    with branches.use_branch(p.id, "main"):
        await pm.wait_finalized(p.id)
        model = main_ws / "model.py"
        had_model = model.is_file()
        backup = main_ws / ".out_backup"
        shutil.rmtree(backup, ignore_errors=True)
        if (main_ws / "out").is_dir():
            shutil.copytree(main_ws / "out", backup)
        main_ws.mkdir(parents=True, exist_ok=True)
        copied = branches.carry_inputs(bws, main_ws)
        settings_before = (main_ws / ".fw" / "project.json").read_bytes() if (main_ws / ".fw" / "project.json").is_file() else None
        if ff and (bws / ".fw" / "project.json").is_file():
            (main_ws / ".fw").mkdir(parents=True, exist_ok=True)
            shutil.copy2(bws / ".fw" / "project.json", main_ws / ".fw" / "project.json")
        model.write_text(merged, encoding="utf-8")

        def rollback() -> None:
            if had_model:
                model.write_text(ours, encoding="utf-8")
            else:
                model.unlink(missing_ok=True)
            for rel in copied:
                (main_ws / rel).unlink(missing_ok=True)
            if settings_before is not None:
                (main_ws / ".fw" / "project.json").write_bytes(settings_before)
            if backup.is_dir():
                shutil.rmtree(main_ws / "out", ignore_errors=True)
                backup.rename(main_ws / "out")

        try:
            st = await pm._rebuild(p, main_ws, determinism=False, fast=True)
        except HTTPException:
            rollback()
            raise
        gating = [c for c in st.get("checks") or [] if c.get("gating") and not c.get("passed")]
        if not st.get("ok") or not st.get("fingerprint"):
            rollback()
            raise HTTPException(422, {"message": "Merge refused: the merged part "
                                                 f"{'fails its checks' if gating else 'does not build'}: "
                                                 f"{build_error(st.get('error'), gating or st.get('checks'))}. "
                                                 "Main was not changed.", "code": "checks_failed"})
        shutil.rmtree(backup, ignore_errors=True)
        rev = pm._snapshot(p, main_ws, cause=f"Merged “{b.name}”: {mr.title}", kind="merge", by=ctx.user.name)
        pm.schedule_finalize(p, main_ws, rev)
        p.last_status = pm._status_summary(st)
        p.builds += 1
        p.updated_at = utcnow()
    mr.status, mr.merged_by, mr.merged_at, mr.merge_rev = "merged", ctx.user.id, utcnow(), rev
    b.status, b.merged_at = "merged", utcnow()
    if mr.created_by and mr.created_by != ctx.user.id:
        notify(ctx.db, mr.created_by, f"{ctx.user.name} merged !{mr.number} {mr.title}",
               f"Main is now at revision {rev}.", f"/app/projects/{p.id}")
    audit(ctx.db, "mr.merged", ctx.user, p.org_id, target=p.id, mr=mr.id, number=mr.number, title=mr.title,
          branch="main", source_branch=b.id, revision=rev, fast_forward=ff)
    ctx.db.commit()
    if branches.active_branch(p.id) == b.id:
        _set_branch_cookie(response, p.id, "main")
    return {"ok": True, "revision": rev, "fast_forward": ff, "status_ok": st.get("ok")}


# =============================================================================== tags (releases)
class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    note: str = Field(default="", max_length=2000)
    revision: int | None = None


@router.get("/projects/{project_id}/tags")
def list_tags(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "read")
    rows = ctx.db.scalars(select(Tag).where(Tag.project_id == p.id).order_by(Tag.created_at.desc())).all()
    names = _names(ctx, {t.created_by for t in rows})
    return {"items": [{"id": t.id, "name": t.name, "revision": t.revision, "note": t.note,
                       "by": names.get(t.created_by or ""), "created_at": t.created_at.isoformat()} for t in rows]}


@router.post("/projects/{project_id}/tags")
def create_tag(project_id: str, body: TagIn, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    pm = _projects_mod()
    p = pm._project(ctx, project_id, "read")
    acc: permissions.Access = ctx.project_access  # type: ignore[attr-defined]
    if not acc.at_least("edit"):
        raise permissions._deny(acc, "edit")
    main_ws = pm.main_workspace(p)
    rev = body.revision or pm.current_revision(main_ws)
    if rev is None or not (main_ws / "revisions" / str(rev)).is_dir():
        raise HTTPException(404, "Tags mark a revision of main: build the part first")
    name = body.name.strip()
    if ctx.db.scalar(select(Tag).where(Tag.project_id == p.id, Tag.name == name)):
        raise HTTPException(409, "That tag already exists")
    t = Tag(project_id=p.id, name=name, revision=rev, note=body.note.strip(), created_by=ctx.user.id)
    ctx.db.add(t)
    audit(ctx.db, "tag.created", ctx.user, p.org_id, target=p.id, name=name, revision=rev)
    ctx.db.commit()
    return {"id": t.id, "name": name, "revision": rev}


@router.delete("/projects/{project_id}/tags/{tid}")
def delete_tag(project_id: str, tid: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    p = _projects_mod()._project(ctx, project_id, "admin")
    t = ctx.db.get(Tag, tid)
    if t is None or t.project_id != p.id:
        raise HTTPException(404)
    ctx.db.delete(t)
    audit(ctx.db, "tag.deleted", ctx.user, p.org_id, target=p.id, name=t.name)
    ctx.db.commit()
    return {"ok": True}
