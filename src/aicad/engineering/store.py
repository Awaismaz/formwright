"""Per-project engineering records under ``<workspace>/engineering/``: load cases (ENG-001), calculation sets with
engineer sign-off (ENG-008), tolerance stack-ups (ENG-011) and the failure-mode checklist status (ENG-002).

Sign-off: a named user signs a calculation set; the record stores who, when, their role, and the SHA-256 of the
set's canonical content (calculator ids and versions, inputs, outputs, checks, linked load cases, notes, data-library
versions). Status is recomputed from the hash on every read, so *any* later edit (an input, a load case, a note)
leaves the signature invalid. Unsigned or invalidated sets are flagged "Unsigned: not for release".

Model binding (MAKE-02): each calculation and each sign-off records the build stamp of the model it was made on
(``aicad.deliverables.build_stamp``). The stamp is *not* part of the content hash: when the part changes after
sign-off the signature is still intact, but the set reads "Model changed since sign-off: re-check" and drops back to
a Preliminary estimate until it is checked and signed again.

Example inputs (MAKE-19): a calculator's illustrative default loads are recorded per item; sign-off is refused while
any of them is neither replaced nor explicitly confirmed by the user.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aicad import deliverables, materials
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
                   "checks": it["result"]["checks"]} | ({"confirmed": it["confirmed"]} if it.get("confirmed") else {})
                  for it in cs.get("items", [])],
        "load_cases": lc, "notes": cs.get("notes", ""), "conclusion": cs.get("conclusion", ""),
        "libraries": {"standards": std.VERSION, "materials": materials.MECHANICAL_VERSION,
                      "engine": core.ENGINE_VERSION},
    }


def set_hash(cs: dict[str, Any], load_cases: list[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical(set_content(cs, load_cases)).encode("utf-8")).hexdigest()


def unconfirmed(it: dict[str, Any]) -> list[dict[str, str]]:
    """Example (textbook default) load inputs of an item that the user has neither replaced nor confirmed."""
    ok = set(it.get("confirmed") or [])
    return [e for e in (it.get("result") or {}).get("examples") or [] if e["key"] not in ok]


def signoff_status(cs: dict[str, Any], load_cases: list[dict[str, Any]],
                   current: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sign-off state. ``current`` is the project's current build stamp: an intact signature given on another build
    is ``model_changed`` (not for release, Preliminary estimate)."""
    h = set_hash(cs, load_cases)
    so = cs.get("signoff")
    if so and so.get("hash") == h:
        state = "signed"
        if current is not None and so.get("build") and not deliverables.same_build(so["build"], current):
            state = "model_changed"
    elif so:
        state = "invalidated"
    else:
        state = "unsigned"
    self_check = bool(so and so.get("self_check"))
    labels = {"signed": deliverables.verified_label(self_check),
              "model_changed": "Model changed since sign-off: re-check",
              "invalidated": "Signature invalid: edited after sign-off",
              "unsigned": "Unsigned: not for release"}
    return {"state": state, "hash": h, "signoff": so, "label": labels[state], "for_release": state == "signed",
            "self_check": self_check,
            "signed_on_rev": ((so or {}).get("build") or {}).get("model_rev"),
            "current_rev": (current or {}).get("model_rev")}


def decorate(cs: dict[str, Any], load_cases: list[dict[str, Any]],
             current: dict[str, Any] | None = None) -> dict[str, Any]:
    """Set with computed sign-off status and per-item advice level (VALIDATION §4)."""
    st = signoff_status(cs, load_cases, current)
    level = deliverables.VERIFIED if st["state"] == "signed" else deliverables.PRELIMINARY
    items = []
    for it in cs.get("items", []):
        stale = bool(current is not None and it.get("build") and not deliverables.same_build(it["build"], current))
        items.append({**it, "result": {**it["result"], "level": level}, "unconfirmed": unconfirmed(it),
                      "model_changed": stale})
    return {**cs, "items": items, "status": st, "level": level,
            "level_label": st["label"] if st["state"] == "signed" else deliverables.LEVEL_LABELS[level]}


def statement_facts(cs: dict[str, Any], load_cases: list[dict[str, Any]], current: dict[str, Any] | None) -> str:
    """The factual sign-off statement: what was reviewed, against which load cases, on which model revision."""
    names = [c["name"] for c in load_cases if c["id"] in (cs.get("load_case_ids") or [])]
    n = len(cs.get("items", []))
    lc = (f"against load case{'s' if len(names) > 1 else ''} {', '.join(names)}" if names
          else "with no load cases linked (the loads are stated in each calculation)")
    rev = (current or {}).get("model_rev")
    return (f"I have reviewed the inputs, assumptions, working and results of {n} calculation{'s' if n != 1 else ''} "
            f"{lc}" + (f", on model revision {rev}." if rev else "."))


def deliverable_summary(ws: Path) -> dict[str, Any]:
    """One line for the Studio's Make tab and the release gate: how the calculation sets stand on the current build.

    ``state``: ``missing`` (no sets), ``stale`` (a set was signed on another build), else ``current``.
    ``signed_sets``: ids of sets signed on the current build (what a release may include)."""
    empty = {"state": "missing", "sets": 0, "signed": 0, "model_changed": 0, "unsigned": 0,
             "label": "No calculation sets", "signed_sets": []}
    if not (ws / "engineering" / FILES["sets"]).is_file():
        return empty
    sets: list[dict[str, Any]] = load(ws, "sets")  # type: ignore[assignment]
    if not sets:
        return empty
    lcs: list[dict[str, Any]] = load(ws, "loadcases")  # type: ignore[assignment]
    cur = deliverables.build_stamp(ws)
    states = [signoff_status(c, lcs, cur)["state"] for c in sets]
    signed, changed = states.count("signed"), states.count("model_changed")
    n = len(sets)
    plural = "s" if n > 1 else ""
    if changed:
        label = f"{changed} signed set{'s' if changed > 1 else ''} · model changed"
    elif signed:
        label = f"{n} set{plural} · {signed} signed"
    else:
        label = f"{n} set{plural} · unsigned"
    return {"state": "stale" if changed else "current", "sets": n, "signed": signed, "model_changed": changed,
            "unsigned": n - signed - changed, "label": label,
            "signed_sets": [c["id"] for c, s_ in zip(sets, states, strict=True) if s_ == "signed"]}


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


def sign(cs: dict[str, Any], load_cases: list[dict[str, Any]], user: dict[str, Any], statement: str,
         build: dict[str, Any] | None = None, loads_in_calcs: bool = False) -> dict[str, Any]:
    h = set_hash(cs, load_cases)
    authors = {it.get("added_by", {}).get("id") for it in cs.get("items", [])} | {cs.get("created_by", {}).get("id")}
    so = {"user_id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"], "at": now(),
          "hash": h, "statement": statement, "self_check": user["id"] in authors, "items": len(cs.get("items", [])),
          "build": build, "loads_in_calcs": loads_in_calcs}
    prev = cs.get("signoff")
    if prev and prev.get("hash") == h and prev.get("build") != build:
        cs.setdefault("history", []).append({"at": so["at"], "by": {"id": user["id"], "name": user["name"]},
                                             "event": "resigned_on_new_model",
                                             "detail": f"Earlier sign-off by {prev['name']} was on model revision "
                                                       f"{(prev.get('build') or {}).get('model_rev') or '-'}"})
    cs["signoff"] = so
    rev = (build or {}).get("model_rev")
    cs.setdefault("history", []).append({"at": so["at"], "by": {"id": user["id"], "name": user["name"]},
                                         "event": "signed",
                                         "detail": f"Signed (hash {h[:12]})" + (f" on model revision {rev}" if rev else "")})
    return so
