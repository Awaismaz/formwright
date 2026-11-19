"""Change impact preview (ASM-018): what a pending Studio edit would do to the assemblies that use the part.

Given a *trial* build of the part (built from the edited model in a scratch folder, never committed), every
assembly that holds an instance of the project is copied in memory and refreshed onto the trial snapshot exactly as
"Part updated: refresh" would do it (``service.remap_refs`` + ``run_solve``), then compared with the assembly as it
stands. Nothing is saved: the documents on disk, their analysis and the part cache stay untouched (the trial
snapshot lives under its own ``x_`` key and is removed afterwards).

Reported per assembly (all deterministic: exact references, the mate solver, exact B-rep booleans):
- mates that would break (a reference that disappears) and mates whose references move (followed);
- parts that would move after the re-solve (beyond 1 µm / 1e-6 rad);
- fastener stacks that need a refit (the hole is gone, or the proposal / grip changes);
- new interference: exact overlap volumes after the change that did not exist (or were smaller) before, checked on
  the pairs involving the changed part and the parts that move.
"""

from __future__ import annotations

import copy
import hashlib
import math
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from aicad.assembly import service, store, xform

MOVE_MM = 1e-3
MOVE_RAD = 1e-6
VOL_TOL = 1e-3  # mm³: overlap growth below this is numerical noise


def trial_key(project_id: str, step: Path) -> str:
    h = hashlib.sha1(step.read_bytes()).hexdigest()[:12]
    return f"x_{project_id[:60]}_{h}"


def users(root: Path, org_id: str, project_id: str) -> list[dict[str, Any]]:
    """Assembly documents of the organisation holding at least one instance of the project."""
    out = []
    for d in store.list_docs(root):
        if d.get("org_id") != org_id:
            continue
        if any(i["source"]["kind"] == "project" and i["source"].get("project_id") == project_id for i in d["instances"]):
            out.append(d)
    return out


def _moved(a: list[float], b: list[float]) -> tuple[float, float]:
    Ta, Tb = xform.from12(a), xform.from12(b)
    dt = float(np.linalg.norm(Tb[:3, 3] - Ta[:3, 3]))
    R = Ta[:3, :3].T @ Tb[:3, :3]
    ang = math.acos(max(-1.0, min(1.0, (float(np.trace(R)) - 1) / 2)))
    return dt, ang


async def _overlaps(root: Path, org_id: str, doc: dict[str, Any], focus: list[str]) -> dict[tuple[str, str], float]:
    if not focus or len(doc["instances"]) < 2:
        return {}
    res = (await service.check_pairs(root, org_id, doc, only=focus))["interference"]
    return {tuple(sorted((p["a"], p["b"]))): float(p["volume_mm3"]) for p in res["pairs"]
            if p["kind"] == "interference"}


async def prepare_trial(root: Path, org_id: str, project_id: str, name: str, step: Path, material: Any) -> str:
    key = trial_key(project_id, step)
    if not store.part_ready(root, key):
        d = store.part_dir(root, key)
        await service._call(org_id, {"op": "prepare", "dest": str(d), "step": str(step)})
        store.write_json(d / "meta.json", {"key": key, "kind": "project", "project_id": project_id,
                                           "build_id": "trial", "rev": None, "name": service.clean_name(name),
                                           "material": material, "standard": None, "created_at": store.now()})
    return key


def drop_trial(root: Path, key: str) -> None:
    shutil.rmtree(store.part_dir(root, key), ignore_errors=True)


async def assess(root: Path, org_id: str, doc: dict[str, Any], project_id: str, key: str,
                 current_build: Any = None) -> dict[str, Any]:
    """The impact of re-pointing the project's instances in ``doc`` at the trial snapshot ``key`` (doc unchanged).
    ``current_build``: the project's build now; instances on an older build also carry earlier changes."""
    before = copy.deepcopy(doc)
    service.run_solve(root, before)  # compare solved with solved, so only this change shows
    after = copy.deepcopy(doc)
    mine = [i["id"] for i in after["instances"]
            if i["source"]["kind"] == "project" and i["source"].get("project_id") == project_id]
    behind = sum(1 for i in after["instances"] if i["id"] in mine and current_build is not None
                 and str(i["source"].get("build_id")) != str(current_build))
    old_infos: dict[str, dict[str, Any]] = {}
    counts = {"kept": 0, "followed": 0, "lost": 0}
    for i in after["instances"]:
        if i["id"] not in mine:
            continue
        old_infos[i["id"]] = (store.part(root, i["part"]) or {}).get("info") or {}
        c = service.remap_refs(root, after, i["id"], key, i["part"])
        for k in counts:
            counts[k] += c[k]
        i["part"] = key
    service.run_solve(root, after)
    was_broken = {m["id"] for m in before["mates"] if m.get("broken")}
    mates = []
    for m_old, m_new in zip(before["mates"], after["mates"], strict=True):
        if m_new["a"]["inst"] not in mine and m_new["b"]["inst"] not in mine:
            continue
        if m_new.get("broken") and m_new["id"] not in was_broken:
            mates.append({"id": m_new["id"], "type": m_new["type"], "status": "breaks", "a": m_old["a"], "b": m_old["b"]})
        elif not m_new.get("broken") and not all(service._same(m_old[s]["ref"], m_new[s]["ref"]) for s in ("a", "b")):
            mates.append({"id": m_new["id"], "type": m_new["type"], "status": "follows", "a": m_old["a"], "b": m_old["b"]})
    moved = []
    for io, inew in zip(before["instances"], after["instances"], strict=True):
        dt, ang = _moved(io["T"], inew["T"])
        if dt > MOVE_MM or ang > MOVE_RAD:
            moved.append({"id": inew["id"], "mm": round(dt, 4), "deg": round(math.degrees(ang), 4)})
    # fastener stacks fitted to this part: the same re-check a refresh runs (AMI-07), on the copy
    stacks_before = {g["id"]: g.get("check") for g in after["groups"]}
    await service.recheck_stacks(root, org_id, after, old_infos)
    refit = [{"id": g["id"], "name": g.get("name") or "Fastener stack", "why": g["check"]["text"]}
             for g in after["groups"] if g.get("check") and g["check"] != stacks_before.get(g["id"])
             and g.get("hole", {}).get("inst") in mine]
    focus = sorted(set(mine) | {m["id"] for m in moved})
    o_before = await _overlaps(root, org_id, before, focus)
    o_after = await _overlaps(root, org_id, after, focus)
    names = service.display_names(after)
    clashes = [{"a": a, "b": b, "a_name": names[a], "b_name": names[b], "volume_mm3": round(v, 3),
                "was_mm3": round(o_before.get((a, b), 0.0), 3)}
               for (a, b), v in sorted(o_after.items()) if v - o_before.get((a, b), 0.0) > VOL_TOL]
    resolved = [{"a": a, "b": b, "a_name": names[a], "b_name": names[b], "volume_mm3": round(v, 3)}
                for (a, b), v in sorted(o_before.items()) if (a, b) not in o_after]
    return {"id": doc["id"], "name": doc["name"], "instances": len(mine), "behind": behind,
            "program": next((i.get("office", {}).get("program") for i in doc["instances"] if i.get("office")), None),
            "references": counts, "mates": mates, "moved": [{**m, "name": names[m["id"]]} for m in moved],
            "refit": refit, "clashes": clashes, "resolved": resolved,
            "breaks": sum(1 for m in mates if m["status"] == "breaks")}


def headline(items: list[dict[str, Any]]) -> str:
    """'This change affects 2 assemblies: 1 mate breaks, 1 new clash' (plain words, for the panel and the chat)."""
    if not items:
        return "This part isn't used in any assembly."
    n = len(items)
    breaks = sum(a["breaks"] for a in items)
    clashes = sum(len(a["clashes"]) for a in items)
    refit = sum(len(a["refit"]) for a in items)
    moved = sum(len(a["moved"]) for a in items)
    bits = []
    if breaks:
        bits.append(f"{breaks} mate{'s' if breaks > 1 else ''} break{'' if breaks > 1 else 's'}")
    if clashes:
        bits.append(f"{clashes} new clash{'es' if clashes > 1 else ''}")
    if refit:
        bits.append(f"{refit} fastener stack{'s' if refit > 1 else ''} to refit")
    if moved:
        bits.append(f"{moved} part{'s' if moved > 1 else ''} move{'' if moved > 1 else 's'}")
    where = f"{n} assembl{'ies' if n > 1 else 'y'}"
    return f"This change affects {where}: " + ", ".join(bits) if bits else f"No problems found in {where}."
