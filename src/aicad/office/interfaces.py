"""Program ICD operations (CD-010, CD-012): the skeleton and ICD on the program, the "Architecture and interfaces"
gate, edits before release, and engineering change requests.

Gate: when the brief and plan are approved, Archie lays out the skeleton and drafts the ICD; the gate is pending and
no ticket is claimed until the engineer approves it (edits allowed: the editable numbers per interface kind, see
``icd.EDITABLE``). At approval the envelopes are frozen and Fitz builds the program assembly from placeholders.

Change requests: after approval an interface changes only through a CR (raised by a part agent with a
``fw-change-request`` block, or by the engineer). Archie decides:
  * deterministic rule (always): rebuild the ICD with the proposed values; accept only if the geometry is valid
    (``icd.problems``), every envelope stays as frozen, no item other than the interface's two sides moves, and
    neither side is already integrated. Anything else is rejected with the reason;
  * AI note (Archie-planned programs only, mockable): may still reject a change the rule accepts, never the reverse.
On accept the ICD version goes up (history with every field changed), the tickets whose features changed are
reopened with the delta (a busy agent gets it on its next turn), integrations already done are reopened, and the
placeholders of the affected items are regenerated. On reject the requester gets the reason. Every step is an
event (the audit trail) and the CR stays on the board and in the ICD history.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from aicad.office import OfficeInputError, icd, service, store

MAX_CR_PER_TICKET = 3


def has_icd(doc: dict[str, Any]) -> bool:
    return bool(doc.get("icd")) and bool(doc.get("skeleton"))


def gate_open(doc: dict[str, Any]) -> bool:
    """True when part work may start: no ICD on this program (older programs) or the ICD gate is approved."""
    if not has_icd(doc):
        return True
    return service.gate(doc, "icd")["status"] == "approved"


def create(root: Path, doc: dict[str, Any], actor: dict[str, Any]) -> None:
    """Archie's skeleton + draft ICD for the approved plan (called at brief approval)."""
    parts = icd.parts_from(doc)
    skel, ic = icd.new_icd(parts, doc["brief"], "Archie")
    ic["history"][0]["at"] = store.now()
    doc.setdefault("change_requests", [])
    doc["icd"] = ic
    doc["skeleton"] = skel
    g = service.gate(doc, "icd")
    g.pop("note", None)
    archie = service.agent_actor("archie")
    if not skel["items"]:
        g.update(status="approved", by="Archie", at=store.now(), note="No designed parts: nothing to interface.")
        ic["status"] = "approved"
        return
    g.update(status="pending")
    n_items = len(skel["items"])
    service.emit(root, doc, "icd.drafted", f"Archie laid out {doc['name']}: {n_items} designed parts in the skeleton "
                 f"and {len(ic['interfaces'])} named interfaces. Review the interfaces (ICD) before part work starts.",
                 archie, interfaces=len(ic["interfaces"]))


def _rebuild(doc: dict[str, Any], overrides: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return icd.build(icd.parts_from(doc), doc["brief"], overrides)


def edit(root: Path, doc: dict[str, Any], iid: str, values: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
    """Change numbers of one interface while the ICD is a draft (at the gate)."""
    if not has_icd(doc):
        raise OfficeInputError("This program has no interfaces document.")
    ic = doc["icd"]
    if ic["status"] != "draft":
        raise OfficeInputError("The ICD is approved: interfaces change through a change request now.")
    f = icd.iface(ic, iid)
    if f is None:
        raise OfficeInputError("Interface not found")
    vals = icd.clean_values(f, values)
    ov = icd.apply_values(ic["overrides"], f, vals)
    sk2, ifs2 = _rebuild(doc, ov)
    probs = icd.problems(sk2, ifs2)
    if probs:
        raise OfficeInputError("That change can't be built: " + probs[0])
    d = icd.diff(doc["skeleton"], ic["interfaces"], sk2, ifs2)
    doc["skeleton"], ic["interfaces"], ic["overrides"], ic["problems"] = sk2, ifs2, ov, probs
    lines = [icd.describe_change(c) for c in d["changes"]][:12]
    ic["history"].append({"version": ic["version"], "at": store.now(), "by": actor.get("name"), "kind": "edited",
                          "interface": iid, "text": f"{actor.get('name', 'Someone')} edited {iid} before approval.",
                          "changes": d["changes"][:40]})
    service.emit(root, doc, "icd.edited", f"{actor.get('name', 'Someone')} edited {iid} {f['name']}: "
                 + ("; ".join(lines[:3]) or "no change") + ".", actor, interface=iid)
    return icd.iface(ic, iid) or f


def approve(root: Path, doc: dict[str, Any], actor: dict[str, Any]) -> None:
    if not has_icd(doc):
        raise OfficeInputError("This program has no interfaces document.")
    g = service.gate(doc, "icd")
    if g["status"] == "approved":
        return
    if doc["status"] not in ("active", "complete"):
        raise OfficeInputError("Approve the brief first.")
    ic = doc["icd"]
    if ic.get("problems"):
        raise OfficeInputError("Fix the interface problems first: " + ic["problems"][0])
    ic["overrides"] = icd.freeze(doc["skeleton"], ic["interfaces"], ic["overrides"])
    ic["status"] = "approved"
    ic["approved_at"] = store.now()
    ic["history"].append({"version": ic["version"], "at": store.now(), "by": actor.get("name"), "kind": "approved",
                          "text": f"{actor.get('name', 'Someone')} approved ICD v{ic['version']}: envelopes frozen, "
                                  "part tickets released.", "changes": []})
    g.update(status="approved", by=actor.get("name"), at=store.now())
    doc["assembly"] = {**(doc.get("assembly") or {}), "status": "building"}
    service.emit(root, doc, "gate.approved", f"{actor.get('name', 'Someone')} approved the architecture and "
                 f"interfaces (ICD v{ic['version']}, {len(ic['interfaces'])} interfaces). Part tickets are released; "
                 "Fitz is assembling the placeholders.", actor, gate="icd")


# ----------------------------------------------------------------------------- change requests
def cr(doc: dict[str, Any], cid: str) -> dict[str, Any]:
    c = next((x for x in doc.get("change_requests") or [] if x["id"] == cid), None)
    if c is None:
        raise OfficeInputError("Change request not found")
    return c


def raise_cr(root: Path, doc: dict[str, Any], iid: str, values: dict[str, Any], reason: str, actor: dict[str, Any],
             ticket_id: str | None = None) -> dict[str, Any]:
    if not has_icd(doc) or doc["icd"]["status"] != "approved":
        raise OfficeInputError("Change requests start once the ICD is approved; until then edit the interface.")
    f = icd.iface(doc["icd"], iid)
    if f is None:
        raise OfficeInputError(f"There is no interface {iid} in the ICD.")
    vals = icd.clean_values(f, values)
    reason = " ".join(str(reason or "").split())[:400]
    if not reason:
        raise OfficeInputError("Give a reason for the change.")
    if ticket_id:
        n = sum(1 for x in doc.get("change_requests") or [] if x.get("ticket_id") == ticket_id)
        if n >= MAX_CR_PER_TICKET:
            raise OfficeInputError(f"This ticket has raised {n} change requests already; the engineer decides now.")
    crs = doc.setdefault("change_requests", [])
    c = {"id": f"CR-{len(crs) + 1}", "interface": iid, "interface_name": f["name"], "values": vals,
         "before": {k: _current(f, k) for k in vals}, "reason": reason, "by": actor, "ticket_id": ticket_id,
         "status": "open", "created_at": store.now(), "icd_version": doc["icd"]["version"], "decision": None}
    crs.append(c)
    t_label = ""
    if ticket_id:
        t = service.ticket(doc, ticket_id)
        t_label = f" on {service._label(t)}"
    service.emit(root, doc, "cr.raised", f"{actor.get('name', 'Someone')} raised {c['id']}{t_label}: change {iid} "
                 f"({', '.join(f'{k} {_fmt(c['before'][k])} → {_fmt(v)}' for k, v in vals.items())}). {reason}",
                 actor, ticket_id, cr=c["id"], interface=iid)
    return c


def _current(f: dict[str, Any], k: str) -> Any:
    d = f["data"]
    if k == "fastener":
        return d.get("fastener_size")
    return d.get(k)


def _fmt(v: Any) -> str:
    return f"{v:g}" if isinstance(v, float) else str(v)


def evaluate(doc: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    """Archie's deterministic rule. Returns {ok, reason, skeleton, interfaces, overrides, diff}."""
    ic = doc["icd"]
    f = icd.iface(ic, c["interface"])
    if f is None:
        return {"ok": False, "reason": f"{c['interface']} is no longer in the ICD."}
    ov = icd.apply_values(ic["overrides"], f, c["values"])
    sk2, ifs2 = _rebuild(doc, ov)
    probs = icd.problems(sk2, ifs2)
    if probs:
        return {"ok": False, "reason": f"It can't be built inside the frozen envelopes: {probs[0]}"}
    d = icd.diff(doc["skeleton"], ic["interfaces"], sk2, ifs2)
    if not d["changes"]:
        return {"ok": False, "reason": "The proposed values are what the ICD already says."}
    names = {i: v["name"] for i, v in doc["skeleton"]["items"].items()}
    if d["envelope_changed"]:
        i = d["envelope_changed"][0]
        a, b = doc["skeleton"]["items"].get(i, {}).get("size"), sk2["items"].get(i, {}).get("size")
        return {"ok": False, "reason": f"It changes the envelope of {names.get(i, i)} ({_dims(a)} → {_dims(b)} mm); "
                                       "envelopes are frozen at ICD approval."}
    sides = {f["a"]["item"], f["b"]["item"]}
    shaft_items = {x for x in d["features_changed"]}
    moved = [i for i in d["moved"] if i not in sides]
    if moved:
        return {"ok": False, "reason": f"It moves {names.get(moved[0], moved[0])}: the change spreads beyond "
                                       f"{f['a']['name']} and {f['b']['name']}."}
    if f["kind"] == "gear_mesh" and len([x for x in ifs2 if x["kind"] == "gear_mesh"]) < \
            len([x for x in ic["interfaces"] if x["kind"] == "gear_mesh"]):
        return {"ok": False, "reason": "The gears would no longer mesh at the skeleton's centre distance."}
    if any(x["kind"] == "gear_mesh" for x in ic["interfaces"]) and f["kind"] == "gear_mesh" and d["moved"]:
        return {"ok": False, "reason": "A new centre distance moves the shafts: change the layout instead."}
    by_item = {t["item_id"]: t for t in doc["tickets"]}
    for i in sorted(shaft_items | sides):
        t = by_item.get(i)
        if t is not None and t["column"] == "integrated":
            return {"ok": False, "reason": f"{names.get(i, i)} is already integrated; reopen it first."}
    return {"ok": True, "reason": "Within the frozen envelopes and both sides can take it: "
                                  + "; ".join(icd.describe_change(x) for x in d["changes"][:4]) + ".",
            "skeleton": sk2, "interfaces": ifs2, "overrides": ov, "diff": d}


def _dims(s: Any) -> str:
    return " × ".join(f"{x:g}" for x in s) if isinstance(s, list) else "?"


def decide(root: Path, doc: dict[str, Any], cid: str, actor: dict[str, Any], ai: dict[str, Any] | None = None,
           force: str | None = None) -> dict[str, Any]:
    """Apply Archie's decision. ``ai``: the optional AI note {decision, reason, tokens}. Returns
    {"cr", "accepted", "items" (whose placeholders to regenerate)}."""
    c = cr(doc, cid)
    if c["status"] != "open":
        raise OfficeInputError(f"{cid} is already {c['status']}.")
    ev = evaluate(doc, c)
    ok, reason = ev["ok"], ev["reason"]
    note = None
    if ok and ai and ai.get("decision") == "reject":
        ok, reason, note = False, f"Archie's review: {ai.get('reason') or 'not justified by the brief.'}", ai.get("note")
    elif ai and ai.get("note"):
        note = ai["note"]
    if force == "reject" and ok:
        ok, reason = False, "Rejected by the engineering manager."
    archie = service.agent_actor("archie")
    c["decision"] = {"by": "Archie", "at": store.now(), "reason": reason, "ai_note": note,
                     "tokens": int((ai or {}).get("tokens") or 0)}
    doc["budget"]["planning_tokens"] = int(doc["budget"].get("planning_tokens", 0)) + int((ai or {}).get("tokens") or 0)
    requester = service.ticket(doc, c["ticket_id"]) if c.get("ticket_id") else None
    if not ok:
        c["status"] = "rejected"
        service.emit(root, doc, "cr.rejected", f"Archie rejected {cid} ({c['interface']}): {reason}", archie,
                     c.get("ticket_id"), cr=cid)
        if requester is not None:
            requester.setdefault("cr_notes", []).append(
                f"Change request {cid} on {c['interface']} was rejected: {reason} Keep {c['interface']} exactly as "
                "the ICD states and finish the part.")
        return {"cr": c, "accepted": False, "items": set()}
    ic = doc["icd"]
    d = ev["diff"]
    old = {"version": ic["version"], "interfaces": copy.deepcopy(ic["interfaces"])}
    ic["version"] += 1
    doc["skeleton"], ic["interfaces"], ic["overrides"] = ev["skeleton"], ev["interfaces"], ev["overrides"]
    ic["problems"] = []
    c["status"] = "accepted"
    c["version_after"] = ic["version"]
    c["delta"] = d["changes"][:40]
    affected = sorted(set(d["features_changed"]) | {icd.iface(ic, c["interface"])["a"]["item"],  # type: ignore[index]
                                                    icd.iface(ic, c["interface"])["b"]["item"]})  # type: ignore[index]
    c["affected"] = affected
    ic["history"].append({"version": ic["version"], "at": store.now(), "by": "Archie", "kind": "cr_accepted",
                          "cr": cid, "interface": c["interface"], "reason": c["reason"],
                          "text": f"Archie accepted {cid}: ICD v{old['version']} → v{ic['version']}.",
                          "changes": d["changes"][:40]})
    lines = [icd.describe_change(x) for x in d["changes"][:8]]
    service.emit(root, doc, "cr.accepted", f"Archie accepted {cid}: ICD v{ic['version']} ({'; '.join(lines[:3])}). "
                 f"Reopening {len(affected)} part{'s' if len(affected) != 1 else ''}; placeholders regenerated.", archie,
                 c.get("ticket_id"), cr=cid, version=ic["version"])
    _reopen(root, doc, affected, cid, lines, c.get("ticket_id"))
    return {"cr": c, "accepted": True, "items": set(affected)}


def _reopen(root: Path, doc: dict[str, Any], items: list[str], cid: str, lines: list[str], requester: str | None) -> None:
    """Put the affected tickets back into work with the delta (a busy agent gets it on its next turn)."""
    from aicad.office import orchestrator

    archie = service.agent_actor("archie")
    ver = doc["icd"]["version"]
    msg = f"ICD v{ver} ({cid}) changed this part's interfaces:\n" + "\n".join(f"- {x}" for x in lines)
    subs = set()
    for t in doc["tickets"]:
        if t["kind"] == "integration" or t["item_id"] not in items:
            continue
        subs.add(next((i["parent_id"] for i in doc["items"] if i["id"] == t["item_id"]), None))
        service.comment(root, doc, t["id"], msg, archie)
        t["comments"][-1]["delivery"] = "stored"
        t["icd_delta"] = [f"ICD v{ver} ({cid}): {x}" for x in lines]
        t["fitted"] = False  # back to a placeholder until it passes Gage again
        r = orchestrator.run_of(t)
        busy = r.get("status") in orchestrator.ACTIVE
        if busy or t["id"] == requester:
            continue  # the agent picks the delta up after its current step
        if t["column"] in ("in_review", "approved", "integrated", "changes_requested") or r.get("status") in (
                "done", "blocked"):
            orchestrator.control(root, doc, t["id"], "reopen", archie)
            t["icd_delta"] = [f"ICD v{ver} ({cid}): {x}" for x in lines]
    for t in doc["tickets"]:  # assemblies already done that hold an affected part
        if t["kind"] != "integration":
            continue
        if (t["item_id"] in subs or t["item_id"] == "root") and t["column"] == "integrated" \
                and orchestrator.run_of(t).get("status") not in orchestrator.ACTIVE:
            orchestrator.control(root, doc, t["id"], "reopen", archie)


# ----------------------------------------------------------------------------- views
def view(doc: dict[str, Any]) -> dict[str, Any] | None:
    """The ICD page: interfaces with their two sides and the latest conformance result of each side, the skeleton,
    history and change requests."""
    if not has_icd(doc):
        return None
    sk, ic = doc["skeleton"], doc["icd"]
    by_item = {t["item_id"]: t for t in doc["tickets"]}
    out = []
    for f in ic["interfaces"]:
        sides = {}
        for w in ("a", "b"):
            t = by_item.get(f[w]["item"])
            chk = (t or {}).get("icd_check") or {}
            res = next((r for r in chk.get("interfaces") or [] if r["interface"] == f["id"]), None)
            sides[w] = {**f[w], "ticket_id": (t or {}).get("id"), "key": (t or {}).get("key"),
                        "column": (t or {}).get("column"), "features": icd.side_features(sk, f, w),
                        "check": None if res is None else {"ok": res["ok"], "rows": res["rows"],
                                                           "version": chk.get("version")}}
        crs = [x["id"] for x in doc.get("change_requests") or [] if x["interface"] == f["id"]]
        extra = {}
        if f["kind"] == "shaft_bore":
            h, s = icd.fit_zones(f["data"]["d"], f["data"]["fit"])
            extra["limits"] = {"hole": h, "shaft": s}
        out.append({**f, "label": icd.KIND_LABEL[f["kind"]], "sides": sides, "crs": crs,
                    "editable": list(icd.EDITABLE[f["kind"]]), **extra})
    return {"version": ic["version"], "status": ic["status"], "interfaces": out, "history": ic["history"][-60:],
            "problems": ic.get("problems") or [], "skeleton": {k: v for k, v in sk.items()},
            "fits": list(icd.FITS), "fasteners": [f"M{m}" for m in icd.CLEARANCE]}
