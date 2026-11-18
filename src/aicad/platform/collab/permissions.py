"""The one place that decides what a person may do on a project.

Levels: none < read < comment < edit < admin.

Effective access = max(workspace baseline, owning-team role, explicit grants), then capped:

- workspace **owner/admin**: always admin;
- the project's **creator**: admin;
- everyone else in the workspace starts from the project's *general access* (default ``edit``, the behaviour of
  every project made before teams existed; a team project defaults to ``read`` outside the team; a personal
  project to ``none``). A workspace **viewer** starts at most at ``read`` and is capped at ``comment``: viewers
  never edit, whatever a team or grant says;
- the **owning team**: team admin -> admin, editor -> edit, viewer -> read;
- **grants** to the person, or to a team they are in;
- a **guest** (signed in, not in the workspace) has only their own grants, capped at ``edit``, and never runs the
  design agent (tokens belong to the workspace; PD-50).

Routers call `require_project(ctx, project_id, need)`. When `need` is omitted it follows the HTTP method: reads
(GET/HEAD) need ``read``, every other method needs ``edit``; endpoints override that where it differs (compare is a
read, sharing/deleting need ``admin``, the agent needs ``agent`` = edit by a workspace member, a native ``.fwpart``
export needs ``export`` = edit without the edit-lock checks; STEP/STL downloads stay reads). A project you can't
read is reported as not found (no existence leak).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from aicad.platform.collab import branches
from aicad.platform.collab.tables import ProjectAccess, ProjectGrant, Team, TeamMember
from aicad.platform.models import Membership, Organization, Project, User

LEVELS = ("none", "read", "comment", "edit", "admin")
RANK = {lv: i for i, lv in enumerate(LEVELS)}
GRANT_LEVELS = ("read", "comment", "edit")
GENERAL_LEVELS = ("none", "read", "comment", "edit")
TEAM_ROLES = ("admin", "editor", "viewer")
TEAM_ROLE_LEVEL = {"admin": "admin", "editor": "edit", "viewer": "read"}
LEVEL_LABEL = {"read": "view", "comment": "comment on", "edit": "edit", "admin": "manage"}


def hi(*levels: str) -> str:
    return max(levels, key=lambda lv: RANK[lv])


def lo(*levels: str) -> str:
    return min(levels, key=lambda lv: RANK[lv])


@dataclass
class Access:
    level: str = "none"
    source: str = "none"  # admin|creator|workspace|team|grant|guest
    member_role: str | None = None  # workspace role, None for a guest
    team: dict[str, Any] | None = None  # owning team {id, name, color}
    general: str = "edit"
    protected_main: bool = False
    required_approvals: int = 1
    reasons: list[str] = field(default_factory=list)

    @property
    def guest(self) -> bool:
        return self.member_role is None and self.level != "none"

    def at_least(self, need: str) -> bool:
        return RANK[self.level] >= RANK[need]

    def as_dict(self) -> dict[str, Any]:
        lv = self.level
        return {"level": lv, "source": self.source, "guest": self.guest, "team": self.team, "general": self.general,
                "can_read": RANK[lv] >= 1, "can_comment": RANK[lv] >= 2, "can_edit": RANK[lv] >= 3,
                "can_admin": lv == "admin", "can_agent": RANK[lv] >= 3 and not self.guest,
                "protected_main": self.protected_main, "required_approvals": self.required_approvals}


# ----------------------------------------------------------------------------- computation (batched)
class _Index:
    """Everything needed to compute a user's access to a set of projects, in a handful of queries."""

    def __init__(self, db: Session, user: User, projects: Iterable[Project]) -> None:
        ps = list(projects)
        ids = [p.id for p in ps]
        self.roles = {m.org_id: m.role for m in db.scalars(select(Membership).where(Membership.user_id == user.id))}
        self.my_teams: dict[str, str] = {tm.team_id: tm.role for tm in db.scalars(
            select(TeamMember).where(TeamMember.user_id == user.id))}
        self.access = {a.project_id: a for a in db.scalars(select(ProjectAccess).where(
            ProjectAccess.project_id.in_(ids)))} if ids else {}
        team_ids = {a.team_id for a in self.access.values() if a.team_id} | set(self.my_teams)
        self.teams = {t.id: t for t in db.scalars(select(Team).where(Team.id.in_(team_ids)))} if team_ids else {}
        self.grants: dict[str, list[ProjectGrant]] = {}
        if ids:
            q = select(ProjectGrant).where(ProjectGrant.project_id.in_(ids))
            for g in db.scalars(q):
                if (g.subject_type == "user" and g.subject_id == user.id) or (
                        g.subject_type == "team" and g.subject_id in self.my_teams):
                    self.grants.setdefault(g.project_id, []).append(g)
        self.user = user

    def compute(self, p: Project) -> Access:
        a = self.access.get(p.id)
        team = self.teams.get(a.team_id) if a and a.team_id else None
        acc = Access(general=a.general if a else "edit", protected_main=bool(a and a.protected_main),
                     required_approvals=max(1, a.required_approvals) if a else 1,
                     team={"id": team.id, "name": team.name, "color": team.color} if team else None)
        role = self.roles.get(p.org_id)
        acc.member_role = role
        grants = self.grants.get(p.id, [])
        if role is None:  # guest: only grants made to them personally
            mine = [g.level for g in grants if g.subject_type == "user"]
            if mine:
                acc.level, acc.source = lo(hi(*mine), "edit"), "guest"
            return acc
        if role in ("owner", "admin"):
            acc.level, acc.source = "admin", "admin"
            return acc
        cands: list[tuple[str, str]] = [(acc.general if role != "viewer" else lo(acc.general, "read"), "workspace")]
        if p.created_by == self.user.id:
            cands.append(("admin", "creator"))
        if team and team.org_id == p.org_id and team.id in self.my_teams:
            cands.append((TEAM_ROLE_LEVEL.get(self.my_teams[team.id], "read"), "team"))
        for g in grants:
            if g.subject_type == "user" or (self.teams.get(g.subject_id) and
                                            self.teams[g.subject_id].org_id == p.org_id):
                cands.append((g.level, "grant"))
        level, source = max(cands, key=lambda c: RANK[c[0]])
        if role == "viewer":
            level = lo(level, "comment")  # viewers never edit
        acc.level, acc.source = level, source
        return acc


def project_access(db: Session, user: User, p: Project) -> Access:
    return _Index(db, user, [p]).compute(p)


def access_map(db: Session, user: User, projects: Iterable[Project]) -> dict[str, Access]:
    ps = list(projects)
    idx = _Index(db, user, ps)
    return {p.id: idx.compute(p) for p in ps}


def visible(db: Session, user: User, projects: Iterable[Project]) -> list[Project]:
    """The projects (in order) this person can at least read."""
    ps = list(projects)
    m = access_map(db, user, ps)
    return [p for p in ps if m[p.id].at_least("read")]


# ----------------------------------------------------------------------------- enforcement
def default_need() -> str:
    m = branches.request_method()
    return "read" if m in ("GET", "HEAD") else "edit"


def _deny(acc: Access, need: str) -> HTTPException:
    if acc.member_role == "viewer" and need in ("edit", "agent", "admin"):
        return HTTPException(403, "Viewers can look but not change. Ask an admin for engineer access.")
    if need == "agent" and acc.guest:
        return HTTPException(403, "Guests can't run the design agent on a shared project. Edit parameters and "
                                  "features by hand, or ask the owner.")
    want = "edit" if need == "agent" else need
    return HTTPException(403, f"You have {acc.level} access to this project; this needs {want} access. "
                              "Ask the project owner to share it with you.")


def require_project(ctx: Any, project_id: str, need: str | None = None) -> Project:
    """Load a project the current person may use at `need` (default: by HTTP method), or raise 404/403/409.
    Members whose selected workspace differs from the project's are switched to the project's workspace for the
    rest of the request (role, tokens and billing then follow the project)."""
    need = need or default_need()
    p = ctx.db.get(Project, project_id) if isinstance(project_id, str) and len(project_id) <= 64 else None
    if p is None:
        raise HTTPException(404, "Project not found")
    acc = project_access(ctx.db, ctx.user, p)
    if not acc.at_least("read"):
        raise HTTPException(404, "Project not found")
    if acc.member_role and (ctx.org is None or ctx.org.id != p.org_id):
        ctx.org, ctx.role = ctx.db.get(Organization, p.org_id), acc.member_role
    if need == "agent":
        if acc.guest or not acc.at_least("edit"):
            raise _deny(acc, need)
    elif need == "export":  # a full native copy (model, history) of the part: edit access, no lock needed
        if not acc.at_least("edit"):
            raise _deny(acc, "edit")
    elif not acc.at_least(need):
        raise _deny(acc, need)
    if need in ("edit", "agent"):
        _check_main_and_locks(ctx, p, acc)
    ctx.project_access = acc  # for endpoints that want to show it
    return p


def _check_main_and_locks(ctx: Any, p: Project, acc: Access) -> None:
    bid = branches.active_branch(p.id)
    if bid == "main" and acc.protected_main and acc.level != "admin":
        raise HTTPException(409, {"message": "Main is protected: changes reach it through a reviewed merge request. "
                                             "Work on a branch to make this change.", "code": "protected_main"})
    from aicad.platform.routers.projects import _sessions

    lk = branches.lock_for(_sessions, p.id, bid)
    if lk and lk.get("user_id") and lk["user_id"] != ctx.user.id:
        where = "main" if bid == "main" else "this branch"
        raise HTTPException(409, {"message": f"{lk['name']} is editing {where} ({lk['what']}). Continue on your own "
                                             "branch so your changes don't collide.", "code": "edit_locked",
                                  "lock": lk})


def agent_gate(ctx: Any, p: Project) -> tuple[bool, str | None, str | None] | None:
    """Why this person can't start the design agent on this project's active branch (None = no project-level
    reason; plan, tokens and verification are checked by the caller)."""
    acc: Access = ctx.project_access
    if acc.guest:
        return False, "Guests can't run the design agent on a shared project.", None
    if not acc.at_least("edit"):
        return False, "You can view this project but not change it.", None
    if branches.active_branch(p.id) == "main" and acc.protected_main and acc.level != "admin":
        return False, "Main is protected: work on your own branch to use the design agent.", None
    return None


# ----------------------------------------------------------------------------- helpers for routers
def team_role(db: Session, team_id: str, user_id: str) -> str | None:
    tm = db.scalar(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id))
    return tm.role if tm else None


def readers(db: Session, p: Project) -> list[User]:
    """Everyone who can read the project (workspace members with access, and guests with grants)."""
    ids = {m.user_id for m in db.scalars(select(Membership).where(Membership.org_id == p.org_id))}
    ids |= {g.subject_id for g in db.scalars(select(ProjectGrant).where(ProjectGrant.project_id == p.id,
                                                                        ProjectGrant.subject_type == "user"))}
    out = []
    for u in db.scalars(select(User).where(User.id.in_(ids))):
        if project_access(db, u, p).at_least("read"):
            out.append(u)
    return out


def is_guest_only(db: Session, user: User) -> bool:
    """Signed in with project grants but no workspace of their own (a guest)."""
    if db.scalar(select(Membership).where(Membership.user_id == user.id)) is not None:
        return False
    return db.scalar(select(ProjectGrant).where(ProjectGrant.subject_type == "user",
                                                ProjectGrant.subject_id == user.id)) is not None
