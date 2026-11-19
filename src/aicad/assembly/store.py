"""Assembly documents and the per-organisation part cache (plain JSON files, atomic writes).

Layout under ``<data_dir>/assemblies/<org_id>/``:
  _parts/<key>/      part snapshots shared by the org's assemblies: part.step, topo.json, refs.json, info.json,
                     meta.json. Keys are immutable: ``p_<project>_<build>`` for a project build,
                     ``t_<code>_<hash>_v<toolbox VERSION>`` for a Toolbox component.
  <assembly_id>/     assembly.json (the document), analysis.json (last interference / clearance run),
                     assembly.step (last export)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aicad.assembly import AssemblyInputError

_ID = re.compile(r"^[a-f0-9]{12}$")
_KEY = re.compile(r"^[a-z]_[A-Za-z0-9_\-]{1,120}$")
_locks: dict[str, threading.Lock] = {}
_glock = threading.Lock()
SCHEMA = 1


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def org_root(data_dir: Path, org_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", org_id):
        raise AssemblyInputError("bad organisation id")
    return (data_dir / "assemblies" / org_id).resolve()


def lock(aid: str) -> threading.Lock:
    with _glock:
        return _locks.setdefault(aid, threading.Lock())


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


# ----------------------------------------------------------------------------- documents
def doc_dir(root: Path, aid: str) -> Path:
    if not _ID.fullmatch(aid or ""):
        raise AssemblyInputError("Assembly not found")
    return root / aid


def new_doc(name: str, org_id: str, user_id: str, project_id: str | None) -> dict[str, Any]:
    return {"schema": SCHEMA, "id": uuid.uuid4().hex[:12], "name": name, "org_id": org_id, "project_id": project_id,
            "created_by": user_id, "created_at": now(), "updated_at": now(), "rev": 0, "seq": 0,
            "instances": [], "mates": [], "groups": [], "solve": None}


def load(root: Path, aid: str) -> dict[str, Any] | None:
    d = read_json(doc_dir(root, aid) / "assembly.json")
    return d if isinstance(d, dict) else None


def save(root: Path, doc: dict[str, Any]) -> dict[str, Any]:
    doc["rev"] = int(doc.get("rev", 0)) + 1
    doc["updated_at"] = now()
    write_json(doc_dir(root, doc["id"]) / "assembly.json", doc)
    return doc


def list_docs(root: Path) -> list[dict[str, Any]]:
    out = []
    if not root.is_dir():
        return out
    for d in root.iterdir():
        if d.is_dir() and _ID.fullmatch(d.name):
            doc = read_json(d / "assembly.json")
            if isinstance(doc, dict):
                out.append(doc)
    out.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return out


def delete(root: Path, aid: str) -> None:
    import shutil

    shutil.rmtree(doc_dir(root, aid), ignore_errors=True)


def next_id(doc: dict[str, Any], prefix: str) -> str:
    doc["seq"] = int(doc.get("seq", 0)) + 1
    return f"{prefix}{doc['seq']}"


# ----------------------------------------------------------------------------- part cache
def part_dir(root: Path, key: str) -> Path:
    if not _KEY.fullmatch(key or ""):
        raise AssemblyInputError("Part not found")
    return root / "_parts" / key


def project_key(project_id: str, build_id: Any) -> str:
    b = re.sub(r"[^A-Za-z0-9]", "", str(build_id))[:40] or "0"
    return f"p_{project_id}_{b}"


def toolbox_key(code: str, params: dict[str, Any], version: int) -> str:
    h = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:10]
    return f"t_{code}_{h}_v{version}"


def part_ready(root: Path, key: str) -> bool:
    d = part_dir(root, key)
    if not all((d / f).is_file() for f in ("part.step", "topo.json", "refs.json", "info.json", "meta.json")):
        return False
    # a snapshot recognised by an older recogniser is made again (its holes may be wrong: recognize.VERSION)
    from aicad.recognize import VERSION

    info = read_json(d / "info.json")
    return isinstance(info, dict) and info.get("recognize_version") == VERSION


def part(root: Path, key: str) -> dict[str, Any] | None:
    """meta + info for a cached part (no topology)."""
    d = part_dir(root, key)
    meta, info = read_json(d / "meta.json"), read_json(d / "info.json")
    if not isinstance(meta, dict) or not isinstance(info, dict):
        return None
    return {**meta, "info": info}


def refs(root: Path, key: str) -> dict[str, Any]:
    r = read_json(part_dir(root, key) / "refs.json")
    return r if isinstance(r, dict) else {"faces": {}, "edges": {}}
