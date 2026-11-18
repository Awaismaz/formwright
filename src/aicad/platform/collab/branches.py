"""Branches of a project, the per-request branch context, soft edit locks and presence.

Storage: `main` is the project's own workspace (``<workspaces>/<org>/<project>``: its model, outputs and the
linear revision history every project already has, so nothing moves). A branch is a sibling workspace
``<workspaces>/<org>/<project>.branches/<branch id>`` made copy-on-write from a revision of its source: the inputs
(model, imported STEP files, settings) and that revision's outputs are copied once, and from then on the branch has
its own model head, build outputs and revision chain. ``.fw/merge_base/model.py`` keeps the script it started from
(the common ancestor for a 3-way merge).

Which branch a request works on is per person and per project: a ``fw_br_<project>`` cookie (set by "switch
branch"), read by `RequestContextMiddleware` into a context variable. `workspace_for(project)` (projects router)
resolves through `resolve_workspace`, so every existing endpoint (agent, params, manual features, restore, files,
modules) works on the active branch without knowing branches exist.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

from aicad.platform.db import utcnow

COOKIE_PREFIX = "fw_br_"
BRANCH_ID_RE = re.compile(r"^[a-f0-9]{12}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]{0,46}$")

_cookies: ContextVar[dict[str, str] | None] = ContextVar("fw_branch_cookies", default=None)
_override: ContextVar[dict[str, str] | None] = ContextVar("fw_branch_override", default=None)
_method: ContextVar[str | None] = ContextVar("fw_request_method", default=None)


# ----------------------------------------------------------------------------- request context
class RequestContextMiddleware:
    """Pure ASGI middleware: records the request method (default permission level) and the branch cookies in
    context variables for the life of the request (and of tasks it starts)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            _method.set(scope.get("method"))
            raw = next((v.decode("latin-1") for k, v in scope.get("headers") or [] if k == b"cookie"), "")
            found: dict[str, str] = {}
            if COOKIE_PREFIX in raw:
                c: SimpleCookie = SimpleCookie()
                try:
                    c.load(raw)
                except Exception:  # noqa: BLE001  (a malformed cookie header only loses branch choice)
                    c = SimpleCookie()
                for k, morsel in c.items():
                    if k.startswith(COOKIE_PREFIX) and BRANCH_ID_RE.match(morsel.value):
                        found[k[len(COOKIE_PREFIX):]] = morsel.value
            _cookies.set(found)
            _override.set(None)
        await self.app(scope, receive, send)


def request_method() -> str | None:
    return _method.get()


def active_branch(project_id: str) -> str:
    """The branch this request works on for `project_id` ("main" unless switched)."""
    ov = _override.get() or {}
    if project_id in ov:
        return ov[project_id]
    return (_cookies.get() or {}).get(project_id, "main")


@contextmanager
def use_branch(project_id: str, branch_id: str) -> Iterator[None]:
    """Work on a given branch inside this block (merges write main; branch setup writes the new branch)."""
    tok = _override.set({**(_override.get() or {}), project_id: branch_id})
    try:
        yield
    finally:
        _override.reset(tok)


def cookie_name(project_id: str) -> str:
    return COOKIE_PREFIX + project_id


# ----------------------------------------------------------------------------- storage
def branches_root(main_ws: Path) -> Path:
    return main_ws.parent / f"{main_ws.name}.branches"


def branch_dir(main_ws: Path, branch_id: str) -> Path:
    if not BRANCH_ID_RE.match(branch_id):
        raise ValueError("bad branch id")
    return branches_root(main_ws) / branch_id


def resolve_workspace(main_ws: Path, project_id: str) -> Path:
    bid = active_branch(project_id)
    if bid == "main":
        return main_ws
    d = branch_dir(main_ws, bid)
    return d if d.is_dir() else main_ws  # a merged or deleted branch falls back to main


COPY_IGNORE = shutil.ignore_patterns("revisions", ".out_backup", "compare", "chat.jsonl", "current_rev",
                                     "recognition_ai.json", "merge_base", "agent.json")


def fork_workspace(src_ws: Path, dst_ws: Path, rev: int | None) -> bool:
    """Copy-on-write fork: inputs + outputs of `src_ws`, with the model of revision `rev` when given. Returns True
    when the model differs from the copied outputs (the caller must rebuild)."""
    if dst_ws.exists():
        shutil.rmtree(dst_ws)
    dst_ws.parent.mkdir(parents=True, exist_ok=True)
    if src_ws.is_dir():
        shutil.copytree(src_ws, dst_ws, ignore=COPY_IGNORE)
    else:
        dst_ws.mkdir(parents=True)
    needs_build = False
    if rev is not None:
        rsrc = src_ws / "revisions" / str(rev) / "model.py"
        if rsrc.is_file():
            cur = dst_ws / "model.py"
            if not cur.is_file() or cur.read_text(encoding="utf-8") != rsrc.read_text(encoding="utf-8"):
                shutil.copy2(rsrc, cur)
                needs_build = True
    base = dst_ws / ".fw" / "merge_base"
    base.mkdir(parents=True, exist_ok=True)
    if (dst_ws / "model.py").is_file():
        shutil.copy2(dst_ws / "model.py", base / "model.py")
    return needs_build


def merge_base_source(branch_ws: Path) -> str:
    f = branch_ws / ".fw" / "merge_base" / "model.py"
    return f.read_text(encoding="utf-8") if f.is_file() else ""


def carry_inputs(src_ws: Path, dst_ws: Path) -> list[str]:
    """Copy-on-write the branch's input files (imported STEP etc.) that main does not have yet."""
    skip = {"model.py", "out", "revisions", ".fw", ".out_backup", "refs"}
    copied = []
    if not src_ws.is_dir():
        return copied
    for item in src_ws.iterdir():
        if item.name in skip:
            continue
        target = dst_ws / item.name
        if item.is_dir():
            for f in item.rglob("*"):
                t = target / f.relative_to(item)
                if f.is_file() and not t.exists():
                    t.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, t)
                    copied.append(str(t.relative_to(dst_ws)))
        elif item.is_file() and not target.exists():
            shutil.copy2(item, target)
            copied.append(item.name)
    return copied


def remove_all(main_ws: Path) -> None:
    shutil.rmtree(branches_root(main_ws), ignore_errors=True)


# ----------------------------------------------------------------------------- per-branch session keys
class BranchKeyed(dict):  # type: ignore[type-arg]
    """A dict keyed by project id whose entries are per active branch: ``d[pid]`` means "this project on the
    branch the current request works on". Lets the projects router keep one agent session (and one background
    export task) per branch without changing its call sites."""

    @staticmethod
    def key(project_id: Any) -> Any:
        if not isinstance(project_id, str) or "@" in project_id:
            return project_id
        b = active_branch(project_id)
        return project_id if b == "main" else f"{project_id}@{b}"

    def __getitem__(self, k: Any) -> Any:
        return super().__getitem__(self.key(k))

    def __setitem__(self, k: Any, v: Any) -> None:
        super().__setitem__(self.key(k), v)

    def __delitem__(self, k: Any) -> None:
        super().__delitem__(self.key(k))

    def __contains__(self, k: object) -> bool:
        return super().__contains__(self.key(k))

    def get(self, k: Any, default: Any = None) -> Any:
        return super().get(self.key(k), default)

    def pop(self, k: Any, *default: Any) -> Any:
        return super().pop(self.key(k), *default)

    def setdefault(self, k: Any, default: Any = None) -> Any:
        return super().setdefault(self.key(k), default)

    def raw(self, k: str) -> Any:
        return super().get(k)

    def all_for(self, project_id: str) -> list[tuple[str, Any]]:
        """(branch id, value) for every branch of the project that has an entry."""
        out = []
        for k, v in self.items():
            if k == project_id:
                out.append(("main", v))
            elif isinstance(k, str) and k.startswith(project_id + "@"):
                out.append((k.split("@", 1)[1], v))
        return out


# ----------------------------------------------------------------------------- soft edit locks
def lock_for(sessions: BranchKeyed, project_id: str, branch_id: str) -> dict[str, Any] | None:
    """Who is editing this branch right now (a design-agent run in progress), or None."""
    key = project_id if branch_id == "main" else f"{project_id}@{branch_id}"
    s = sessions.raw(key)
    if s is None or not getattr(s, "busy", False):
        return None
    return {"user_id": getattr(s, "driver", None), "name": getattr(s, "driver_name", None) or "Someone",
            "what": "design agent running", "branch": branch_id}


def locks(sessions: BranchKeyed, project_id: str) -> list[dict[str, Any]]:
    out = []
    for bid, _s in sessions.all_for(project_id):
        lk = lock_for(sessions, project_id, bid)
        if lk:
            out.append(lk)
    return out


# ----------------------------------------------------------------------------- presence (in memory, per process)
_presence: dict[str, dict[str, dict[str, Any]]] = {}
_watchers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
PRESENCE_TTL_S = 45


def presence_join(project_id: str, user: Any, branch: str, conn_id: str | None = None) -> str:
    cid = conn_id or uuid.uuid4().hex[:12]
    _presence.setdefault(project_id, {})[cid] = {"user_id": user.id, "name": user.name, "branch": branch,
                                                 "since": utcnow(), "seen": utcnow()}
    return cid


def presence_touch(project_id: str, conn_id: str) -> None:
    row = _presence.get(project_id, {}).get(conn_id)
    if row:
        row["seen"] = utcnow()


def presence_leave(project_id: str, conn_id: str) -> None:
    _presence.get(project_id, {}).pop(conn_id, None)


def presence_list(project_id: str) -> list[dict[str, Any]]:
    now = utcnow()
    rows = _presence.get(project_id, {})
    for cid in [c for c, r in rows.items() if (now - r["seen"]).total_seconds() > PRESENCE_TTL_S]:
        rows.pop(cid, None)
    by_user: dict[str, dict[str, Any]] = {}
    for r in sorted(rows.values(), key=lambda r: r["since"]):
        u = by_user.setdefault(r["user_id"], {"user_id": r["user_id"], "name": r["name"], "branches": [],
                                              "since": r["since"].isoformat()})
        if r["branch"] not in u["branches"]:
            u["branches"].append(r["branch"])
    return list(by_user.values())


def watchers(project_id: str) -> set[asyncio.Queue[dict[str, Any]]]:
    return _watchers.setdefault(project_id, set())


def broadcast(project_id: str, event: dict[str, Any]) -> None:
    for q in list(_watchers.get(project_id, ())):
        q.put_nowait(event)
