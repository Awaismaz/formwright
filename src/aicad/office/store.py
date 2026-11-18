"""Program documents, per organisation (plain JSON files, atomic writes), like assemblies.

Layout under ``<data_dir>/office/<org_id>/<program_id>/``:
  program.json   the program document (brief, gates, plan, item tree, tickets, budget)
  events.jsonl   the append-only event log (what the board's live feed and the activity tab show)
  archie/        Archie's planning folder (the agent's working directory; nothing else is in it)
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aicad.assembly.store import read_json, write_json
from aicad.office import OfficeInputError

SCHEMA = 1
_ID = re.compile(r"^[a-f0-9]{12}$")
_locks: dict[str, threading.Lock] = {}
_glock = threading.Lock()


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def org_root(data_dir: Path, org_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", org_id or ""):
        raise OfficeInputError("bad organisation id")
    return (data_dir / "office" / org_id).resolve()


def program_dir(root: Path, pid: str) -> Path:
    if not _ID.fullmatch(pid or ""):
        raise OfficeInputError("Program not found")
    return root / pid


def lock(pid: str) -> threading.Lock:
    with _glock:
        return _locks.setdefault(pid, threading.Lock())


def load(root: Path, pid: str) -> dict[str, Any] | None:
    """The program, or None when it doesn't exist. On Windows a read can collide with the atomic replace of a
    concurrent save (the orchestrator saves often), so a failed read of an existing file is retried."""
    f = program_dir(root, pid) / "program.json"
    for i in range(20):
        d = read_json(f)
        if isinstance(d, dict):
            return d
        if not f.exists():
            return None
        time.sleep(0.01 * (i + 1))
    return None


def save(root: Path, doc: dict[str, Any]) -> dict[str, Any]:
    doc["rev"] = int(doc.get("rev", 0)) + 1
    doc["updated_at"] = now()
    f = program_dir(root, doc["id"]) / "program.json"
    for i in range(20):
        try:
            write_json(f, doc)
            break
        except PermissionError:  # a reader holds the file open for a moment (Windows)
            if i == 19:
                raise
            time.sleep(0.01 * (i + 1))
    return doc


def list_docs(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    for d in root.iterdir():
        if d.is_dir() and _ID.fullmatch(d.name):
            doc = read_json(d / "program.json")
            if isinstance(doc, dict):
                out.append(doc)
    out.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return out


def delete(root: Path, pid: str) -> None:
    import shutil

    shutil.rmtree(program_dir(root, pid), ignore_errors=True)


# --------------------------------------------------------------------------- events
def append_event(root: Path, pid: str, ev: dict[str, Any]) -> None:
    f = program_dir(root, pid) / "events.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(ev, ensure_ascii=False) + "\n")


def events(root: Path, pid: str, limit: int = 200, after: int = 0) -> list[dict[str, Any]]:
    f = program_dir(root, pid) / "events.jsonl"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and int(ev.get("seq", 0)) > after:
            out.append(ev)
    return out[-limit:]
