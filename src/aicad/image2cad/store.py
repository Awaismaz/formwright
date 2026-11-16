"""Upload folders: ``<data>/image2cad/<org id>/<upload id>/`` holding the source file, ``meta.json``,
``preview.png``, ``read.json`` (what was read) and ``review.json`` (the user's edits and answers)."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aicad.image2cad.sniff import validate

UPLOAD_ID = re.compile(r"[0-9a-f]{32}")
EXT = {"pdf": "pdf", "png": "png", "jpg": "jpg", "webp": "webp"}


def root(data_dir: Path, org_id: str) -> Path:
    r = data_dir / "image2cad" / org_id
    r.mkdir(parents=True, exist_ok=True)
    return r


def upload_dir(data_dir: Path, org_id: str, uid: str) -> Path | None:
    if not UPLOAD_ID.fullmatch(uid):
        return None
    d = root(data_dir, org_id) / uid
    return d if (d / "meta.json").is_file() else None


def read_json(d: Path, name: str) -> Any:
    try:
        return json.loads((d / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(d: Path, name: str, data: Any) -> None:
    tmp = d / (name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / name)


def update_meta(d: Path, **kw: Any) -> dict[str, Any]:
    meta = read_json(d, "meta.json") or {}
    meta.update(kw)
    write_json(d, "meta.json", meta)
    return meta


def safe_name(filename: str) -> str:
    return re.sub(r"[^A-Za-z0-9 ._()-]", "_", Path(filename or "drawing").name)[:120].strip() or "drawing"


def create(data_dir: Path, org_id: str, user_id: str, filename: str, data: bytes) -> tuple[Path, dict[str, Any]]:
    kind = validate(data)  # raises InputError before anything is stored
    uid = uuid.uuid4().hex
    d = root(data_dir, org_id) / uid
    d.mkdir()
    fname = f"source.{EXT[kind]}"
    (d / fname).write_bytes(data)
    meta = {"id": uid, "name": safe_name(filename), "type": kind, "file": fname, "bytes": len(data),
            "created_at": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"), "created_by": user_id,
            "status": "reading", "error": None, "project_id": None, "method": None}
    write_json(d, "meta.json", meta)
    return d, meta


def list_uploads(data_dir: Path, org_id: str) -> list[tuple[Path, dict[str, Any]]]:
    out = []
    for d in root(data_dir, org_id).iterdir():
        if d.is_dir() and UPLOAD_ID.fullmatch(d.name):
            m = read_json(d, "meta.json")
            if m:
                out.append((d, m))
    out.sort(key=lambda t: t[1].get("created_at", ""), reverse=True)
    return out
