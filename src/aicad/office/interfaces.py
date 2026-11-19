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
    from aicad.graph.compile import overrides_for

    skel, ic = icd.new_icd(parts, doc["brief"], "Archie", overrides_for(doc.get("plan") or {}, parts))
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
    if ic["problems"]:  # Archie fixes his own layout first, and says what he changed (CD-028)
        ov, steps, probs = autofix(doc, ic["overrides"])
        if steps:
            sk2, ifs2 = _rebuild(doc, ov)
            doc["skeleton"], ic["interfaces"], ic["overrides"], ic["problems"] = sk2, ifs2, ov, probs
            skel = sk2
            ic["history"].append({"version": 1, "at": store.now(), "by": "Archie", "kind": "fixed",
                                  "text": "Archie adjusted his layout so every part can be made: "
                                          + "; ".join(_fmt_step(s) for s in steps[:8]), "changes": []})
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
    before = ic.get("problems") or []
    if len(probs) > len(before):  # a draft may still have problems; an edit must not add one
        new = [p for p in probs if p not in before] or probs
        raise OfficeInputError("That change can't be built: " + new[0])
    d = icd.diff(doc["skeleton"], ic["interfaces"], sk2, ifs2)
    doc["skeleton"], ic["interfaces"], ic["overrides"], ic["problems"] = sk2, ifs2, ov, probs
    lines = [icd.describe_change(c) for c in d["changes"]][:12]
    ic["history"].append({"version": ic["version"], "at": store.now(), "by": actor.get("name"), "kind": "edited",
                          "interface": iid, "text": f"{actor.get('name', 'Someone')} edited {iid} before approval.",
                          "changes": d["changes"][:40]})
    service.emit(root, doc, "icd.edited", f"{actor.get('name', 'Someone')} edited {iid} {f['name']}: "
                 + ("; ".join(lines[:3]) or "no change") + ".", actor, interface=iid)
    return icd.iface(ic, iid) or f


RESIZABLE = {"block": ("L", "W", "H"), "hub": ("OD", "H"), "shaft": ("length",)}


def resize(root: Path, doc: dict[str, Any], item: str, values: dict[str, Any], actor: dict[str, Any]) -> None:
    """Change a part's envelope while the ICD is a draft (asked in the Archie chat). Must not add a problem."""
    if not has_icd(doc):
        raise OfficeInputError("This program has no interfaces document.")
    ic = doc["icd"]
    if ic["status"] != "draft":
        raise OfficeInputError("The envelopes are frozen: the ICD is approved.")
    it = doc["skeleton"]["items"].get(item)
    if it is None:
        raise OfficeInputError("Part not found in the layout.")
    vals = {}
    for k, v in (values or {}).items():
        if k not in RESIZABLE.get(it["role"], ()) or isinstance(v, bool) or not isinstance(v, (int, float)):
            raise OfficeInputError(f"{k} can't be changed on {it['name']}.")
        if not 0.5 <= float(v) <= 5000:
            raise OfficeInputError(f"{k} must be between 0.5 and 5000 mm.")
        vals[k] = float(v)
    ov = copy.deepcopy(ic["overrides"])
    io = ov.setdefault("items", {}).setdefault(item, {})
    io.update(vals)
    if io.get("grown"):  # the engineer chose these sizes: they replace the plan's (no longer Archie's growth)
        io["grown"] = [k for k in io["grown"] if k not in vals]
    sk2, ifs2 = _rebuild(doc, ov)
    probs = icd.problems(sk2, ifs2)
    before = ic.get("problems") or []
    if len(probs) > len(before):
        raise OfficeInputError("That size can't be built: " + ([p for p in probs if p not in before] or probs)[0])
    doc["skeleton"], ic["interfaces"], ic["overrides"], ic["problems"] = sk2, ifs2, ov, probs
    text = f"{actor.get('name', 'Someone')} resized {it['name']}: " + ", ".join(f"{k} {v:g} mm" for k, v in vals.items())
    ic["history"].append({"version": ic["version"], "at": store.now(), "by": actor.get("name"), "kind": "edited",
                          "text": text, "changes": []})
    service.emit(root, doc, "icd.edited", text + ".", actor)


# ----------------------------------------------------------------------------- separate parts (an engineer decision)
def unconnected(doc: dict[str, Any]) -> list[str]:
    """Items the draft layout flags as ``no_interface`` and the engineer has not yet kept separate."""
    if not has_icd(doc):
        return []
    return [i for x in icd.issues(doc["skeleton"], doc["icd"]["interfaces"])
            if x["code"] == "no_interface" and x["severity"] == "error" for i in x["items"]]


def keep_separate(root: Path, doc: dict[str, Any], items: list[str] | None, keep: bool, actor: dict[str, Any]
                  ) -> list[str]:
    """The engineer's recorded decision at the ICD gate: these parts are meant to have no interface (a kit, shafts
    to be made on their own). ``items`` None = every part flagged ``no_interface`` now. ``keep`` False undoes it.
    The gate still blocks every other problem; the decision is in the ICD history and the activity. Returns the
    items changed."""
    if not has_icd(doc):
        raise OfficeInputError("This program has no interfaces document.")
    ic = doc["icd"]
    if ic["status"] != "draft":
        raise OfficeInputError("The ICD is approved: the parts are already placed as it says.")
    ov = copy.deepcopy(ic["overrides"])
    sep: dict[str, Any] = dict(ov.get("separate") or {})
    sk_items = doc["skeleton"]["items"]
    if keep:
        flagged = unconnected(doc)
        want = flagged if items is None else [i for i in items if i in sk_items]
        bad = [sk_items[i]["name"] for i in want if i not in flagged and i not in sep]
        if bad:
            raise OfficeInputError(f"{bad[0]} is connected to the program by an interface: only a part with no "
                                   "interface can be kept separate.")
        changed = [i for i in want if i not in sep]
        for i in changed:
            sep[i] = {"by": actor.get("name"), "at": store.now()}
    else:
        changed = list(sep) if items is None else [i for i in items if i in sep]
        for i in changed:
            sep.pop(i, None)
    if not changed:
        raise OfficeInputError("Nothing to change: " + ("no part is flagged as unconnected." if keep else
                                                         "no part is kept separate."))
    ov["separate"] = sep
    sk2, ifs2 = _rebuild(doc, ov)
    doc["skeleton"], ic["interfaces"], ic["overrides"], ic["problems"] = sk2, ifs2, ov, icd.problems(sk2, ifs2)
    names = [sk_items[i]["name"] for i in changed if i in sk_items]
    who = actor.get("name", "Someone")
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    one = len(names) == 1
    text = (f"{who} kept {listed} as {'a separate part' if one else 'separate parts'}: no interface is intended, so "
            f"{'it is' if one else 'they are'} placed beside the assembly and no longer block the interfaces."
            if keep else
            f"{who} asked for {listed} to be connected again: {'it blocks' if one else 'they block'} the interfaces "
            f"until an interface connects {'it' if one else 'them'} or {'it is' if one else 'they are'} kept separate.")
    ic["history"].append({"version": ic["version"], "at": store.now(), "by": who,
                          "kind": "separate" if keep else "connect", "items": changed, "text": text, "changes": []})
    service.emit(root, doc, "icd.separate" if keep else "icd.connect", text, actor, items=changed)
    return changed


# ----------------------------------------------------------------------------- Archie fixes the draft (CD-028)
FIX_MAX_STEPS = 24


def _candidates(f: dict[str, Any]) -> list[dict[str, Any]]:
    """Small, conservative changes to one interface, in order of preference (least disruptive first)."""
    d = f["data"]
    out: list[dict[str, Any]] = []
    if f["kind"] == "hole_pattern":
        inset = float(d.get("inset") or 0)
        if inset:
            out += [{"inset": round(inset * k, 1)} for k in (0.75, 1.25, 0.6, 1.5, 0.5, 2.0)]
        m = int(d.get("fastener_size") or str(d.get("fastener") or "M0").upper().lstrip("M") or 0)
        smaller = sorted((x for x in icd.CLEARANCE if x < m), reverse=True)
        out += [{"fastener": f"M{x}"} for x in smaller]
        out += [{"count": c} for c in range(int(d.get("count") or 1) - 1, 0, -1)]
        if smaller:
            out += [{"fastener": f"M{smaller[-1]}", "count": c} for c in range(int(d.get("count") or 1) - 1, 0, -1)]
    elif f["kind"] in ("shaft_bore", "dowel"):
        dd = float(d.get("d") or 0)  # a shaft is sized for its load: never shrink it by more than 40 %
        out += [{"d": round(dd * k, 1)} for k in (0.8, 0.6) if dd * k >= 2.0]
    elif f["kind"] == "key":
        ln = float(d.get("length") or 0)
        out += [{"length": round(ln * k, 1)} for k in (0.75, 0.5) if ln * k >= 2]
    return out


def _implicated(sk: dict[str, Any], ifs: list[dict[str, Any]], probs: list[str]) -> list[dict[str, Any]]:
    """Interfaces a problem names (IF-xx) or that touch an item a problem names ("Push rod: ...")."""
    names = {it["name"]: i for i, it in sk["items"].items()}
    items = {names[p.split(":", 1)[0]] for p in probs if p.split(":", 1)[0] in names}
    ids = {p.split(":", 1)[0] for p in probs}
    return [f for f in ifs if f["id"] in ids or f["a"]["item"] in items or f["b"]["item"] in items]


def autofix(doc: dict[str, Any], overrides: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Greedy, deterministic: apply the least disruptive single-interface change that removes the most problems,
    until none are left or nothing helps. Returns (overrides, steps, problems left)."""
    ov = copy.deepcopy(overrides or {"items": {}, "interfaces": {}})
    sk, ifs = _rebuild(doc, ov)
    probs = icd.problems(sk, ifs)
    steps: list[dict[str, Any]] = []
    while probs and len(steps) < FIX_MAX_STEPS:
        best: tuple[int, int, dict[str, Any], dict[str, Any], dict[str, Any]] | None = None
        seen: set[tuple[str, str, str]] = set()
        for f in _implicated(sk, ifs, probs):
            # the same joint on every copy of a part changes together: one design serves all the copies
            group = (f["kind"], f["a"]["item"], f["b"]["item"])
            if group in seen:
                continue
            seen.add(group)
            sibs = [g for g in ifs if (g["kind"], g["a"]["item"], g["b"]["item"]) == group]
            for rank, cand in enumerate(_candidates(f)):
                try:
                    vals = icd.clean_values(f, cand)
                    ov2 = ov
                    for g in sibs:
                        ov2 = icd.apply_values(ov2, g, vals)
                    sk2, ifs2 = _rebuild(doc, ov2)
                except (OfficeInputError, ValueError, KeyError):
                    continue
                n = len(icd.problems(sk2, ifs2))
                if n < len(probs) and (best is None or (n, rank) < (best[0], best[1])):
                    best = (n, rank, f, vals, ov2)
        if best is None:  # no interface change helps: grow the envelope of a part a problem names
            names = {it["name"]: i for i, it in sk["items"].items()}
            byid = {f["id"]: f for f in ifs}
            tries: list[tuple[str, dict[str, Any] | None]] = [
                (names[p.split(":", 1)[0]], None) for p in probs if p.split(":", 1)[0] in names]
            for p in probs:  # "IF-14: ..." grows either side, together with a change to that interface
                f0 = byid.get(p.split(":", 1)[0])
                if f0 is not None:
                    tries += [(f0["a"]["item"], f0), (f0["b"]["item"], f0)]
            for item, f0 in dict.fromkeys((i, f0["id"] if f0 else None) for i, f0 in tries):
                f0 = byid.get(f0) if f0 else None
                extra = [{}] + (_candidates(f0) if f0 else [])
                found = False
                for rank, ch in enumerate(_grow(sk["items"][item])):
                    if found:  # the least growth that helps this part is the one to take
                        break
                    for r2, cand in enumerate(extra):
                        ov2 = copy.deepcopy(ov)
                        io = ov2.setdefault("items", {}).setdefault(item, {})
                        io.update(ch)
                        io["grown"] = sorted(set(io.get("grown") or []) | set(ch))  # still measured against the plan
                        try:
                            if cand:
                                ov2 = icd.apply_values(ov2, f0, icd.clean_values(f0, cand))
                            sk2, ifs2 = _rebuild(doc, ov2)
                        except (OfficeInputError, ValueError, KeyError):
                            continue
                        n = len(icd.problems(sk2, ifs2))
                        found = found or n < len(probs)
                        if n < len(probs) and (best is None or (n, rank * 20 + r2) < (best[0], best[1])):
                            best = (n, rank * 20 + r2, {"id": item, "name": sk["items"][item]["name"], "item": True,
                                                        "iface": f0, "cand": cand}, ch, ov2)
        if best is None:
            break
        _, _, f, vals, ov = best
        if f.get("item"):
            it = sk["items"][f["id"]]
            before = dict(zip(("L", "W", "H"), it["size"], strict=False)) | {"OD": it["size"][0]}
            steps.append({"item": f["id"], "name": f"{f['name']} envelope", "values": vals,
                          "before": {k: before.get(k) for k in vals}})
            if f.get("cand"):
                g = f["iface"]
                steps.append({"interface": g["id"], "name": g["name"], "values": f["cand"],
                              "before": {k: g["data"].get(k) for k in f["cand"]}})
        else:
            before = {k: f["data"].get(k) for k in vals}
            nsib = sum(1 for g in ifs if (g["kind"], g["a"]["item"], g["b"]["item"]) ==
                       (f["kind"], f["a"]["item"], f["b"]["item"]))
            more = f" (and the same joint on {nsib - 1} other cop{'y' if nsib == 2 else 'ies'})" if nsib > 1 else ""
            steps.append({"interface": f["id"], "name": f["name"] + more,
                          "values": vals, "before": before})
        sk, ifs = _rebuild(doc, ov)
        probs = icd.problems(sk, ifs)
    return ov, steps, probs


def _grow(it: dict[str, Any]) -> list[dict[str, Any]]:
    """Envelope changes for a part too small for its holes: the thinnest sizes first, a little before a lot. Never
    past ``icd.PLAN_SLACK`` times the planned envelope (CD-029): beyond that the plan, not the layout, must change."""
    L, W, H = (float(x) for x in it["size"])
    out: list[dict[str, Any]] = []
    if it["role"] == "block":
        dims = sorted((("L", L), ("W", W), ("H", H)), key=lambda kv: kv[1])
        for add in (2.0, 4.0, 8.0):
            for k, v in dims[:2]:
                out.append({k: round(v + add, 1)})
        out.append({dims[0][0]: round(dims[0][1] + 4.0, 1), dims[1][0]: round(dims[1][1] + 8.0, 1)})
    elif it["role"] == "hub":
        if it.get("bore") and float(it["bore"]) + 2.0 > L:  # just enough rim around its bore
            out.append({"OD": round(float(it["bore"]) + 2.0, 1)})
        out += [{"OD": round(L + add, 1)} for add in (2.0, 4.0, 8.0, 16.0)]
    pl = it.get("planned")
    if not pl:
        return out
    keys = icd.SIZE_KEYS.get(it["role"], ())
    cap = {k: icd.PLAN_SLACK * float(pl[n]) for n, k in enumerate(keys)}
    return [ch for ch in out if all(v <= cap.get(k, float("inf")) + 1e-6 for k, v in ch.items())]


def _fmt_step(s: dict[str, Any]) -> str:
    def v(x: Any) -> str:
        return f"{x:g}" if isinstance(x, float) else str(x)
    return f"{s.get('interface', '')} {s['name']}: ".lstrip() + ", ".join(
        f"{k} {v(s['before'].get(k))} → {v(x)}" for k, x in s["values"].items())


def fix(root: Path, doc: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
    """Archie adjusts the draft ICD so it can be built (no AI). Every change is listed in the ICD history and the
    activity; the engineer still reviews and approves the result."""
    if not has_icd(doc):
        raise OfficeInputError("This program has no interfaces document.")
    ic = doc["icd"]
    if ic["status"] != "draft":
        raise OfficeInputError("The ICD is approved: interfaces change through a change request now.")
    if not ic.get("problems"):
        return {"steps": [], "problems": []}
    ov, steps, probs = autofix(doc, ic["overrides"])
    if steps:
        sk2, ifs2 = _rebuild(doc, ov)
        d = icd.diff(doc["skeleton"], ic["interfaces"], sk2, ifs2)
        doc["skeleton"], ic["interfaces"], ic["overrides"], ic["problems"] = sk2, ifs2, ov, probs
        lines = [_fmt_step(s) for s in steps]
        ic["history"].append({"version": ic["version"], "at": store.now(), "by": "Archie", "kind": "fixed",
                              "text": f"Archie adjusted {len(steps)} interface value{'s' if len(steps) != 1 else ''} "
                                      f"so the parts can be made: " + "; ".join(lines[:8]),
                              "changes": d["changes"][:40]})
        service.emit(root, doc, "icd.fixed", f"Archie adjusted {len(steps)} interface value"
                     f"{'s' if len(steps) != 1 else ''} so every part can be made"
                     + (f"; {len(probs)} problem{'s' if len(probs) != 1 else ''} still need you." if probs else
                        ". Review and approve the interfaces.") + " " + "; ".join(lines[:3]),
                     service.agent_actor("archie"), steps=steps)
    _ = actor
    return {"steps": steps, "problems": probs}


def approve(root: Path, doc: dict[str, Any], actor: dict[str, Any], *, with_plan: bool = False) -> None:
    """The ICD gate. ``with_plan``: approved in the same click as the plan (the light path, PD-93), which is only
    allowed when the interfaces have no problem; the history and the activity say so."""
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
    how = " together with the plan (one step: no interface problems)" if with_plan else ""
    ic["history"].append({"version": ic["version"], "at": store.now(), "by": actor.get("name"), "kind": "approved",
                          "text": f"{actor.get('name', 'Someone')} approved ICD v{ic['version']}{how}: envelopes "
                                  "frozen, part tickets released.", "changes": [],
                          **({"with_plan": True} if with_plan else {})})
    g.update(status="approved", by=actor.get("name"), at=store.now(), **({"with_plan": True} if with_plan else {}))
    doc["assembly"] = {**(doc.get("assembly") or {}), "status": "building"}
    service.emit(root, doc, "gate.approved", f"{actor.get('name', 'Someone')} approved the architecture and "
                 f"interfaces{how} (ICD v{ic['version']}, {len(ic['interfaces'])} interfaces). Part tickets are "
                 "released; Fitz is assembling the placeholders.", actor, gate="icd")


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
    if probs:  # a change may not add a problem (one the approved layout already had, e.g. an older check, stays)
        had = set(icd.problems(doc["skeleton"], ic["interfaces"]))
        probs = [p for p in probs if p not in had]
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
        if f["kind"] == "bearing_seat":
            d = f["data"]
            extra["limits"] = {"hole": icd.zone(d["D"], d["housing_fit"]), "shaft": icd.zone(d["d"], d["shaft_fit"])}
        out.append({**f, "label": icd.KIND_LABEL[f["kind"]], "sides": sides, "crs": crs,
                    "editable": list(icd.EDITABLE[f["kind"]]), **extra})
    probs = ic.get("problems") or []
    return {"version": ic["version"], "status": ic["status"], "interfaces": out, "history": ic["history"][-60:],
            "problems": probs, "warnings": icd.warnings(sk, ic["interfaces"]),
            # the problems with their codes and the items / interfaces they name (computed only when there are any)
            "issues": [x for x in icd.issues(sk, ic["interfaces"]) if x["severity"] == "error"] if probs else [],
            # parts the engineer kept separate at the gate (an acknowledged warning, recorded in the history)
            "separate": [{"item": i, "name": sk["items"][i]["name"],
                          **((ic["overrides"].get("separate") or {}).get(i) or {})}
                         for i in sk.get("separate") or [] if i in sk["items"]],
            "skeleton": {k: v for k, v in sk.items()},
            "fits": list(icd.FITS), "fasteners": [f"M{m}" for m in icd.CLEARANCE],
            "bearings": [str(k) for k in sorted(icd.BEARINGS)], "housing_fits": list(icd.HOUSING_FITS),
            "look": ic.get("look")}  # PD-73: Archie's look at the layout (quick checks + visual check, advisory)
