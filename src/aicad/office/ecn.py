"""Engineering change notices after a program release (CD-024).

A released program changes only through an ECN: the engineer names the parts to change (and/or one interface
change, which Archie's change-request rule checks first), with a reason. The ECN then

  * reopens exactly the affected part tickets (with the reason as the designer's instruction) and the integrations
    holding them; untouched parts keep their build, so their release keeps its letter;
  * scopes the deliverables: Ortho redraws and Smithy re-screens only the affected parts (the others' sheets and
    DFM lines are kept from the previous release);
  * locks the release gate until the changed parts are integrated and the deliverables done; the next program
    release (Rev B, C, ...) issues the touched parts at their next letter (Rev A -> B) and reuses the letters of
    the untouched ones, and its pack carries a diff summary against the previous release.

States: ``open`` (raised) -> ``in_work`` (tickets reopened) -> ``ready`` (release gate pending) -> ``released``.
Released packs are immutable: a release directory that already holds a pack is never written again.

Pure Python except ``open_ecn`` (which mutates the program document the caller holds under its lock).
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from aicad.office import OfficeInputError, icd, interfaces, service, store

MAX_REASON = 600


def ecns(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return doc.setdefault("ecns", [])


def current(doc: dict[str, Any]) -> dict[str, Any] | None:
    """The ECN in work (at most one at a time), or None."""
    return next((e for e in doc.get("ecns") or [] if e["status"] in ("open", "in_work", "ready")), None)


def _history(e: dict[str, Any], status: str, text: str, by: str | None = None) -> None:
    e["status"] = status
    e.setdefault("history", []).append({"status": status, "at": store.now(), "by": by, "text": text})


def evaluate_interface(doc: dict[str, Any], iid: str, values: dict[str, Any]) -> dict[str, Any]:
    """Archie's change-request rule for an interface change on a released program: the same rule as during design,
    except that integrated parts don't block it (the ECN reopens them). Returns {ok, reason, items, values}."""
    f = icd.iface(doc["icd"], iid)
    if f is None:
        raise OfficeInputError(f"There is no interface {iid} in the ICD.")
    vals = icd.clean_values(f, values)
    probe = {**doc, "tickets": [{**t, "column": "ready"} for t in doc["tickets"]]}
    ev = interfaces.evaluate(probe, {"interface": iid, "values": vals})
    if not ev["ok"]:
        return {"ok": False, "reason": ev["reason"], "items": [], "values": vals}
    items = sorted(set(ev["diff"]["features_changed"]) | {f["a"]["item"], f["b"]["item"]})
    return {"ok": True, "reason": ev["reason"], "items": items, "values": vals,
            "changes": [icd.describe_change(x) for x in ev["diff"]["changes"][:8]]}


def open_ecn(root: Path, doc: dict[str, Any], reason: str, items: list[str], actor: dict[str, Any],
             interface: str | None = None, values: dict[str, Any] | None = None) -> dict[str, Any]:
    """Raise an ECN on a released program and put the affected tickets back into work. Returns the ECN (with
    ``cr_id`` when an interface change was raised as a change request: the caller lets Archie decide it)."""
    from aicad.office import orchestrator

    if not doc.get("releases"):
        raise OfficeInputError("Change notices are for released programs: release the program first.")
    if current(doc):
        raise OfficeInputError(f"{current(doc)['id']} is still in work: release it before raising another.")  # type: ignore[index]
    if any(orchestrator.run_of(t).get("status") in orchestrator.ACTIVE for t in doc["tickets"]):
        raise OfficeInputError("An agent is still working on the program.")
    why = " ".join(str(reason or "").split())[:MAX_REASON]
    if not why:
        raise OfficeInputError("Give the reason for the change.")
    makes = {t["item_id"]: t for t in doc["tickets"] if t["kind"] == "part" and t.get("project_id")}
    chosen: list[str] = []
    for i in items or []:
        if i not in makes:
            raise OfficeInputError("Change notices change parts the program makes (bought parts change through "
                                   "their interface).")
        if i not in chosen:
            chosen.append(i)
    icd_ev = None
    if interface:
        if not interfaces.has_icd(doc):
            raise OfficeInputError("This program has no interfaces to change.")
        icd_ev = evaluate_interface(doc, interface, values or {})
        if not icd_ev["ok"]:
            raise OfficeInputError(f"Archie can't accept that interface change: {icd_ev['reason']}")
        for i in icd_ev["items"]:
            if i in makes and i not in chosen:
                chosen.append(i)
    if not chosen:
        raise OfficeInputError("Name the parts to change (or an interface change that touches them).")
    prev = doc["releases"][-1]
    e = {"id": f"ECN-{len(ecns(doc)) + 1:03d}", "reason": why, "by": actor, "created_at": store.now(),
         "items": chosen, "tickets": [makes[i]["id"] for i in chosen],
         "titles": [makes[i]["title"] for i in chosen], "from_rev": prev["rev"], "to_rev": None,
         "interface": interface, "values": icd_ev["values"] if icd_ev else None,
         "icd_changes": icd_ev["changes"] if icd_ev else [], "cr_id": None, "status": "open", "history": []}
    ecns(doc).append(e)
    who = actor.get("name", "Someone")
    _history(e, "open", f"{who} raised {e['id']}: {why}", who)
    service.emit(root, doc, "ecn.raised", f"{who} raised {e['id']} on {doc['name']} rev {prev['rev']}: "
                 f"{', '.join(e['titles'])}. {why}", actor, ecn=e["id"])
    # reopen the affected parts with the reason as the designer's instruction
    subs: set[str | None] = set()
    for i in chosen:
        t = makes[i]
        subs.add(next((x["parent_id"] for x in doc["items"] if x["id"] == i), None))
        orchestrator.control(root, doc, t["id"], "reopen", actor)
        c = service.comment(root, doc, t["id"], f"{e['id']}: {why}", actor)
        c["delivery"] = "queued"
        orchestrator._set_run(t, feedback=[f"Engineering change notice {e['id']}: {why}"]
                              + [f"Interface change: {x}" for x in e["icd_changes"]],
                              line=f"{e['id']}: back to the designer")
        t["fitted"] = False
        t["ecn"] = e["id"]
    for t in doc["tickets"]:
        if t["kind"] == "integration" and (t["item_id"] in subs or t["item_id"] == "root") \
                and t["column"] == "integrated":
            orchestrator.control(root, doc, t["id"], "reopen", actor)
        if t["kind"] == "deliverable" and (t["column"] in service.DONE_COLUMNS
                                           or orchestrator.run_of(t).get("status") == "blocked"):
            orchestrator.control(root, doc, t["id"], "reopen", actor)
    doc["ecn_scope"] = list(e["tickets"])
    g = service.gate(doc, "release")
    g.update(status="locked", note=f"{e['id']} in work: the release opens when the changed parts are integrated and "
                                    "their drawings and manufacturing review are redone.")
    o = orchestrator.orch(doc)
    if o.get("state") == "complete":
        o["state"] = "idle"
    if interface and values:
        c = interfaces.raise_cr(root, doc, interface, values, f"{e['id']}: {why}", actor)
        e["cr_id"] = c["id"]
    _history(e, "in_work", f"{len(chosen)} part{'s' if len(chosen) != 1 else ''} reopened: {', '.join(e['titles'])}",
             who)
    service.emit(root, doc, "ecn.in_work", f"{e['id']}: {', '.join(e['titles'])} reopened; untouched parts keep rev "
                 f"{prev['rev']}.", actor, ecn=e["id"])
    return e


def mark_ready(root: Path, doc: dict[str, Any]) -> None:
    """The release gate opened again: the ECN in work is ready to release."""
    e = current(doc)
    if e and e["status"] == "in_work":
        _history(e, "ready", "The changed parts are integrated and the deliverables redone: ready to release.")
        service.emit(root, doc, "ecn.ready", f"{e['id']} is ready: release the program to issue it.",
                     service.agent_actor("archie"), ecn=e["id"])


def mark_released(doc: dict[str, Any], rev: str, by: str) -> dict[str, Any] | None:
    e = current(doc)
    if e is None:
        return None
    e["to_rev"] = rev
    _history(e, "released", f"Released as program rev {rev}.", by)
    doc.pop("ecn_scope", None)
    return e


def scope(doc: dict[str, Any]) -> set[str] | None:
    """The ticket ids the deliverables are redone for (an ECN in work), or None (all parts)."""
    s = doc.get("ecn_scope")
    return set(s) if s else None


# ----------------------------------------------------------------------------- the diff between two releases
def _bom_rows(csv_text: str | None) -> list[dict[str, Any]]:
    if not csv_text:
        return []
    rows = []
    for r in csv.DictReader(io.StringIO(csv_text)):
        if not (r.get("Item") or "").strip():
            continue  # the totals line
        try:
            qty = int(float(r.get("Qty") or 0))
        except ValueError:
            qty = 0
        rows.append({"part": r.get("Part") or "", "qty": qty, "make_buy": r.get("Make/Buy") or "",
                     "designation": r.get("Designation") or ""})
    return rows


def bom_diff(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    """Lines added, removed and quantity changes, keyed by part (and designation for bought parts)."""
    def key(r: dict[str, Any]) -> tuple[str, str]:
        return (str(r["part"]), str(r.get("designation") or ""))

    def agg(rows: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
        out: dict[tuple[str, str], int] = {}
        for r in rows:
            out[key(r)] = out.get(key(r), 0) + int(r["qty"])
        return out
    a, b = agg(before), agg(after)
    added = [{"part": k[0], "designation": k[1] or None, "qty": b[k]} for k in b if k not in a]
    removed = [{"part": k[0], "designation": k[1] or None, "qty": a[k]} for k in a if k not in b]
    qty = [{"part": k[0], "designation": k[1] or None, "before": a[k], "after": b[k]} for k in b
           if k in a and a[k] != b[k]]
    return {"added": added, "removed": removed, "qty_changed": qty, "unchanged": sum(1 for k in b if k in a and a[k] == b[k])}


def icd_diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    """Interface changes between two releases (``{"version", "skeleton", "interfaces"}`` each)."""
    if not before or not after:
        return {"before": (before or {}).get("version"), "after": (after or {}).get("version"), "changes": []}
    changes: list[str] = []
    try:
        d = icd.diff(before["skeleton"], before["interfaces"], after["skeleton"], after["interfaces"])
        changes = [icd.describe_change(x) for x in d["changes"]]
    except Exception:  # noqa: BLE001 - an older pack's ICD format: compare interfaces field by field instead
        ob = {f["id"]: f for f in before.get("interfaces") or []}
        for f in after.get("interfaces") or []:
            o = ob.get(f["id"])
            if o and o.get("data") != f.get("data"):
                changes.append(f"{f['id']} changed")
    return {"before": before.get("version"), "after": after.get("version"), "changes": changes}


def release_diff(prev: dict[str, Any], parts: list[dict[str, Any]], prev_bom_csv: str | None,
                 bom_after: dict[str, Any], prev_icd: dict[str, Any] | None, icd_after: dict[str, Any] | None,
                 ecn: dict[str, Any] | None) -> dict[str, Any]:
    """What a release changes against the previous one: parts (revision before -> after), BOM lines, ICD."""
    before = {p["ticket"]: p for p in prev.get("parts") or []}
    rows = []
    for p in parts:
        b = before.get(p["ticket"])
        rows.append({"ticket": p["ticket"], "key": p["key"], "title": p["title"], "before": b and b["rev"],
                     "after": p["rev"], "changed": b is None or b["rev"] != p["rev"]})
    after_bom = [{"part": r["part"], "qty": r["qty"], "make_buy": r["make_buy"], "designation": r.get("designation") or ""}
                 for r in bom_after["rows"]]
    bd = bom_diff(_bom_rows(prev_bom_csv), after_bom)
    idf = icd_diff(prev_icd, icd_after)
    changed = [r for r in rows if r["changed"]]
    return {"from": prev["rev"], "ecn": ecn and {"id": ecn["id"], "reason": ecn["reason"]},
            "parts": rows, "changed": len(changed), "unchanged": len(rows) - len(changed), "bom": bd, "icd": idf,
            "summary": f"{len(changed)} part{'s' if len(changed) != 1 else ''} revised, {len(rows) - len(changed)} "
                       f"unchanged; BOM {len(bd['added'])} added / {len(bd['removed'])} removed / "
                       f"{len(bd['qty_changed'])} quantity change{'s' if len(bd['qty_changed']) != 1 else ''}; "
                       f"{len(idf['changes'])} interface change{'s' if len(idf['changes']) != 1 else ''}."}


def changes_txt(doc: dict[str, Any], rev: str, d: dict[str, Any]) -> str:
    """CHANGES.txt in a release pack: the diff summary in plain words."""
    lines = [f"CHANGES IN {doc['name']} REV {rev} AGAINST REV {d['from']}", ""]
    if d.get("ecn"):
        lines += [f"Change notice: {d['ecn']['id']}: {d['ecn']['reason']}", ""]
    lines.append(d["summary"])
    lines += ["", "Parts:"]
    for p in d["parts"]:
        lines.append(f"  {p['key']}  {p['title']}  rev {p['before'] or '-'} -> {p['after']}"
                     + ("  (revised)" if p["changed"] else "  (unchanged)"))
    b = d["bom"]
    lines += ["", "Bill of materials:"]
    lines += [f"  + {x['part']}{' ' + x['designation'] if x['designation'] else ''}  qty {x['qty']}" for x in b["added"]]
    lines += [f"  - {x['part']}{' ' + x['designation'] if x['designation'] else ''}  qty {x['qty']}" for x in b["removed"]]
    lines += [f"  ~ {x['part']}  qty {x['before']} -> {x['after']}" for x in b["qty_changed"]]
    if not (b["added"] or b["removed"] or b["qty_changed"]):
        lines.append("  no line changes")
    i = d["icd"]
    lines += ["", f"Interfaces (ICD v{i['before'] or '-'} -> v{i['after'] or '-'}):"]
    lines += [f"  {x}" for x in i["changes"]] or ["  no interface changes"]
    return "\n".join(lines) + "\n"
