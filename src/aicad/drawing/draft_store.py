"""2D drawing documents (DRW-017): plain JSON files per organisation, atomic writes, one snapshot per saved revision.

Layout under ``<data_dir>/drafts/<org_id>/<draft_id>/``:
  draft.json        {id, org_id, name, created_by, created_at, updated_at, rev, revs: [...], doc: {...}}
  revs/<n>.json     the document as saved in revision n (never changed afterwards)
  exports/<n>/      sheet.svg / sheet.pdf / sheet.dxf rendered on demand from revision n
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aicad.drawing import DrawingInputError

_ID = re.compile(r"^[a-f0-9]{12}$")
_locks: dict[str, threading.Lock] = {}
_glock = threading.Lock()
MAX_REVS_LISTED = 200


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def org_root(data_dir: Path, org_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", org_id):
        raise DrawingInputError("bad organisation id")
    return (data_dir / "drafts" / org_id).resolve()


def lock(did: str) -> threading.Lock:
    with _glock:
        return _locks.setdefault(did, threading.Lock())


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def draft_dir(root: Path, did: str) -> Path:
    if not _ID.fullmatch(did or ""):
        raise DrawingInputError("Drawing not found")
    return root / did


def load(root: Path, did: str) -> dict[str, Any] | None:
    d = read_json(draft_dir(root, did) / "draft.json")
    return d if isinstance(d, dict) else None


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def create(root: Path, org_id: str, user: str, name: str, doc: dict[str, Any], did: str | None = None) -> dict[str, Any]:
    rec = {"id": did or new_id(), "org_id": org_id, "name": name, "created_by": user, "created_at": now(),
           "updated_at": now(), "rev": 0, "revs": [], "doc": doc}
    return save(root, rec, doc, user, "Created")


def save(root: Path, rec: dict[str, Any], doc: dict[str, Any], user: str, note: str = "") -> dict[str, Any]:
    """Store ``doc`` as the next revision (a snapshot that is never changed afterwards)."""
    rev = int(rec.get("rev", 0)) + 1
    d = draft_dir(root, rec["id"])
    write_json(d / "revs" / f"{rev}.json", doc)
    g = doc["geom"]
    rec["revs"] = [*rec.get("revs", []), {"rev": rev, "date": now(), "by": user, "note": note[:120],
                                          "entities": len(g["entities"]), "dims": len(doc["dims"]),
                                          "annos": len(doc["annos"])}][-MAX_REVS_LISTED:]
    rec.update(rev=rev, doc=doc, updated_at=now())
    write_json(d / "draft.json", rec)
    return rec


def load_rev(root: Path, did: str, rev: int) -> dict[str, Any] | None:
    d = read_json(draft_dir(root, did) / "revs" / f"{int(rev)}.json")
    return d if isinstance(d, dict) else None


def list_drafts(root: Path) -> list[dict[str, Any]]:
    out = []
    if not root.is_dir():
        return out
    for d in root.iterdir():
        if d.is_dir() and _ID.fullmatch(d.name):
            rec = read_json(d / "draft.json")
            if isinstance(rec, dict):
                out.append(rec)
    out.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return out


def delete(root: Path, did: str) -> None:
    shutil.rmtree(draft_dir(root, did), ignore_errors=True)


def export_dir(root: Path, did: str, rev: int) -> Path:
    return draft_dir(root, did) / "exports" / str(int(rev))
