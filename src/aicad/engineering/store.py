"""Per-project engineering records under ``<workspace>/engineering/``: load cases (ENG-001), calculation sets with
engineer sign-off (ENG-008), tolerance stack-ups (ENG-011) and the failure-mode checklist status (ENG-002).

Sign-off: a named user signs a calculation set; the record stores who, when, their role, and the SHA-256 of the
set's canonical content (calculator ids and versions, inputs, outputs, checks, linked load cases, notes, data-library
versions). Status is recomputed from the hash on every read, so *any* later edit (an input, a load case, a note)
leaves the signature invalid. Unsigned or invalidated sets are flagged "Unsigned: not for release".
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aicad import materials
from aicad.engineering import core
from aicad.engineering import standards as std

FILES = {"sets": "calc_sets.json", "loadcases": "load_cases.json", "stackups": "stackups.json",
         "checklist": "checklist.json"}


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


def _path(ws: Path, kind: str) -> Path:
    d = ws / "engineering"
    d.mkdir(parents=True, exist_ok=True)
    return d / FILES[kind]


def load(ws: Path, kind: str) -> list[dict[str, Any]] | dict[str, Any]:
    p = _path(ws, kind)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {} if kind == "checklist" else []
    return data


def save(ws: Path, kind: str, data: Any) -> None:
    p = _path(ws, kind)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


# ----------------------------------------------------------------------------- hashing / sign-off
def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def set_content(cs: dict[str, Any], load_cases: list[dict[str, Any]]) -> dict[str, Any]:
    """The content a signature covers."""
    lc = {c["id"]: {k: v for k, v in c.items() if k not in ("updated_at", "updated_by")}
          for c in load_cases if c["id"] in (cs.get("load_case_ids") or [])}
    return {
        "items": [{k: it.get(k) for k in ("id", "calc_id", "calc_version", "engine", "title", "raw_inputs")} |
                  {"inputs": it["result"]["inputs"], "outputs": it["result"]["outputs"],
                   "checks": it["result"]["checks"]} for it in cs.get("items", [])],
        "load_cases": lc, "notes": cs.get("notes", ""), "conclusion": cs.get("conclusion", ""),
        "libraries": {"standards": std.VERSION, "materials": materials.MECHANICAL_VERSION,
                      "engine": core.ENGINE_VERSION},
    }


def set_hash(cs: dict[str, Any], load_cases: list[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical(set_content(cs, load_cases)).encode("utf-8")).hexdigest()


def signoff_status(cs: dict[str, Any], load_cases: list[dict[str, Any]]) -> dict[str, Any]:
    h = set_hash(cs, load_cases)
    so = cs.get("signoff")
    if so and so.get("hash") == h:
        state = "signed"
    elif so:
        state = "invalidated"
    else:
        state = "unsigned"
    return {"state": state, "hash": h, "signoff": so,
            "label": {"signed": "Signed", "invalidated": "Signature invalid: edited after sign-off",
                      "unsigned": "Unsigned: not for release"}[state],
            "for_release": state == "signed"}


def decorate(cs: dict[str, Any], load_cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Set with computed sign-off status and per-item advice level (VALIDATION §4)."""
    st = signoff_status(cs, load_cases)
    level = "verified_calculation" if st["state"] == "signed" else "preliminary_estimate"
    items = [{**it, "result": {**it["result"], "level": level}} for it in cs.get("items", [])]
    return {**cs, "items": items, "status": st, "level": level}


def record_change(cs: dict[str, Any], before_hash: str, load_cases: list[dict[str, Any]], who: dict[str, Any],
                  what: str) -> None:
    """Append to the set's history; note when the change invalidated a valid signature."""
    after = set_hash(cs, load_cases)
    hist = cs.setdefault("history", [])
    so = cs.get("signoff")
    if so and so.get("hash") == before_hash and after != before_hash:
        hist.append({"at": now(), "by": who, "event": "signature_invalidated",
                     "detail": f"{what} after sign-off by {so['name']}"})
    hist.append({"at": now(), "by": who, "event": "edited", "detail": what})
    del hist[:-200]
    cs["updated_at"] = now()
    cs["updated_by"] = who


def sign(cs: dict[str, Any], load_cases: list[dict[str, Any]], user: dict[str, Any], statement: str) -> dict[str, Any]:
    h = set_hash(cs, load_cases)
    authors = {it.get("added_by", {}).get("id") for it in cs.get("items", [])} | {cs.get("created_by", {}).get("id")}
    so = {"user_id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"], "at": now(),
          "hash": h, "statement": statement, "self_check": user["id"] in authors, "items": len(cs.get("items", []))}
    cs["signoff"] = so
    cs.setdefault("history", []).append({"at": so["at"], "by": {"id": user["id"], "name": user["name"]},
                                         "event": "signed", "detail": f"Signed (hash {h[:12]})"})
    return so
