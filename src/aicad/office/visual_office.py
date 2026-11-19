"""Archie tells the engineer, on the go (founder, 2026-11-19): "even if it fails, the design office can tell this on
the go to intelligently steer the design ... they must tell me."

Three moments, each a message from Archie in the program chat (``archie_chat.post``), with any fix as a proposed
action the engineer applies (PD-65: Archie never changes the program by himself):

  (a) **The interfaces gate** (``layout_look``): the skeleton is drawn with its envelopes and seated bearings, the
      quick placement checks run (a row of parts touching nothing, gears that must mesh but don't, bearings with no
      seat), the visual check looks at the picture against the brief's relations, and the ICD's own problems are read
      (generically: plain strings, or ``{code, message, items}`` records). Archie says what is wrong in plain words
      and proposes the fix (send the plan back with a housing added, or fix the interfaces).
  (b) **After each sub-assembly and the final assembly** (``level_look``): the level's assembly is drawn and checked
      the same way; a measured problem stops the integration step with the reason, a visual concern that no
      measurement confirms is reported and the step goes on (``visual.decide`` / ``visual.confirm``).
  (c) **A failed or retried step** (``on_failure``): what failed and what he proposes, from the program itself (no AI).

Visual checks are advisory and metered (``visual.CHECK_MAX_TOKENS`` at most per look); simulated programs look for
free from the quick checks.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from aicad.office import archie_chat, service, store

log = logging.getLogger(__name__)

HOUSING_PART = {"name": "Housing", "family": "machined", "complexity": 3, "qty": 1,
                "description": "Housing that carries every shaft on its bearings (seats in the side walls) and holds the "
                               "gears in a closed cavity."}
BASE_PART = {"name": "Base plate", "family": "machined", "complexity": 2, "qty": 1,
             "description": "Base plate with bearing supports that carry every shaft; the gears sit above it."}


# ----------------------------------------------------------------------------- reading ICD problems generically
def problem_text(p: Any) -> str:
    """A problem as plain words: a string as it is, a record by its message (``wip/office-layout`` adds codes)."""
    if isinstance(p, dict):
        return str(p.get("message") or p.get("text") or p.get("code") or "").strip()
    return str(p or "").strip()


def problem_code(p: Any) -> str | None:
    return str(p["code"]) if isinstance(p, dict) and p.get("code") else None


def _mountless(sk: dict[str, Any]) -> bool:
    """No block in the layout to mount the other parts on (a gear pair with only shafts and bearings)."""
    items = (sk.get("items") or {}).values()
    return bool(items) and not any(it.get("role") == "block" for it in items)


# ----------------------------------------------------------------------------- (a) the interfaces gate
def layout_message(doc: dict[str, Any], quick: dict[str, Any], rec: dict[str, Any] | None
                   ) -> tuple[str, list[dict[str, Any]]]:
    """Archie's words and proposed actions after looking at the layout (pure: tests call it directly)."""
    from aicad.assembly import visual

    sk, ic = doc["skeleton"], doc["icd"]
    probs = [problem_text(p) for p in ic.get("problems") or [] if problem_text(p)]
    codes = {problem_code(p) for p in ic.get("problems") or []} - {None}
    found = quick.get("findings") or []
    block = [f for f in found if f["severity"] == "block"]
    verdict = (rec or {}).get("verdict")
    vline = visual.summary_line(verdict) if verdict else ""
    name = doc["name"]
    kept = [sk["items"][i]["name"] for i in sk.get("separate") or [] if i in (sk.get("items") or {})]
    if not probs and not found and (verdict is None or verdict["overall"] == "looks_assembled"):
        tail = f" {vline}" if vline else ""
        if kept and len(kept) == len(sk.get("items") or {}):  # a kit: nothing is meant to be assembled
            listed = ", ".join(kept[:-1]) + " and " + kept[-1] if len(kept) > 1 else kept[0]
            return ((f"I looked at the layout of {name} before you approve the interfaces: {listed} "
                     f"{'are' if len(kept) > 1 else 'is'} kept separate as you decided, so there is nothing to "
                     "assemble and no interface to check. Approve the interfaces when you're happy."), [])
        sep = (f" {', '.join(kept)} {'are' if len(kept) > 1 else 'is'} kept separate as you decided (placed beside "
               "the assembly)." if kept else "")
        return ((f"I looked at the layout of {name} before you approve the interfaces: the parts are placed where they "
                f"connect and the placement checks pass.{sep}{tail} Approve the interfaces when you're happy."), [])
    lines: list[str] = []
    row = any(f["code"] == "row" for f in found) or bool(codes & {"row_layout", "no_mount", "no_host"})
    mountless = _mountless(sk)
    if row and mountless:
        lines.append(f"There's no housing or base in this plan, so the parts can't be mounted: the layout puts them "
                     f"side by side on the floor, touching nothing ({len(sk['items'])} parts, "
                     f"{len(ic.get('interfaces') or [])} interfaces).")
    loose = [f for f in found if f["code"] == "no_interface"]
    names = [str(f["text"]).split(":")[0] for f in loose]
    for f in found:
        if (f["code"] == "row" and row and mountless) or f["code"] == "no_interface":
            continue
        lines.append(f["text"])
    if loose:  # one sentence for every part the layout can't connect (icd.issues "no_interface")
        who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        lines.insert(1 if row and mountless else 0, f"{who}: no interface connects "
                     f"{'it' if len(names) == 1 else 'them'} to the rest of the program, so "
                     f"{'it' if len(names) == 1 else 'they'} would be placed beside it.")
    said = {f["text"] for f in found}
    for p in probs[:4]:
        if p not in lines and p not in said:
            lines.append(p)
    if verdict is not None and verdict["overall"] != "looks_assembled" and vline:
        lines.append(vline)
    acts: list[dict[str, Any]] = []
    first_sub = next((s["name"] for s in (doc.get("plan") or {}).get("subassemblies") or []), None)
    ask = ""
    if mountless and (row or block) and first_sub:
        acts = [{"type": "revise_plan", "notes": "Add a housing that carries both shafts on their bearings.",
                 "add": {"sub": first_sub, "part": HOUSING_PART}},
                {"type": "revise_plan", "notes": "Add a base plate with bearing supports for the shafts.",
                 "add": {"sub": first_sub, "part": BASE_PART}}]
        ask = ("I can send the plan back to you with a housing that carries the shafts on their bearings, or with a "
               "base plate that supports them: which? Either way you review the plan again, I lay it out again and "
               "look again before any part is designed.")
    elif probs:
        acts = [{"type": "fix_icd"}]
        ask = "I can make the smallest safe changes to the interfaces so every part can be made, then look again."
    elif block:
        acts = [{"type": "revise_plan", "notes": "Re-plan: " + "; ".join(f["text"] for f in block[:2])}]
        ask = ("The layout engine placed these parts this way from the plan; I can send the plan back to you with "
               "this note so the parts are planned to connect, then lay it out and look again.")
    else:
        ask = "Nothing measured is wrong, so this is your call: approve the interfaces, or tell me what to change."
    loose_ids = [i for f in loose for i in f.get("items") or []]
    if loose_ids:  # a kit, or parts made on their own: the engineer may say so (recorded at the gate, PD-85)
        one = len(loose_ids) == 1
        acts.append({"type": "keep_separate", "items": loose_ids})
        ask += (f" If {'it is' if one else 'they are'} meant to be {'a separate part' if one else 'separate parts'} "
                f"(a kit, or parts made on their own), keep {'it' if one else 'them'} separate: your decision is "
                "recorded in the interfaces history and no longer blocks approval.")
    # the heading follows what was found: measured or seen wrong, unsure, or only notes (live run 2026-11-19: an
    # unsure picture with every relation ok was headed "It doesn't look right")
    overall = (verdict or {}).get("overall")
    if probs or block or overall == "looks_wrong":
        head = "It doesn't look right:"
    elif overall == "unsure":
        head = "I can't tell from the picture whether it is assembled as intended:"
    else:
        head = "It looks assembled, with notes:"
    text = (f"Before you approve the interfaces, I looked at the layout of {name}. {head}\n"
            + "\n".join(f"- {x}" for x in lines[:6]) + ("\n\n" + ask.strip() if ask.strip() else ""))
    return text, acts


async def layout_look(root: Path, pid: str, *, org_id: str, user_id: str, god: bool, mode: str) -> dict | None:
    """(a) Look at the drafted layout and tell the engineer in the program chat. ``mode``: "ai" (a metered visual
    check), "simulated" (development: free, from the quick checks) or "none" (no AI for this account: the measured
    checks still speak). Never raises."""
    from aicad.assembly import render, visual

    try:
        doc = store.load(root, pid)
        if doc is None or not doc.get("skeleton") or (doc.get("icd") or {}).get("status") != "draft":
            return None
        sk, ifs = doc["skeleton"], doc["icd"]["interfaces"]
        q = await asyncio.to_thread(visual.quick_skeleton, sk, ifs)
        rels = visual.relations_from_skeleton(sk, ifs, doc["brief"])
        scene = render.scene_from_skeleton(sk, f"{doc['name']} (layout)", ifs)
        folder = store.program_dir(root, pid) / "visual" / "layout"
        rec = None
        simulated = mode == "simulated"
        budget = _budget(org_id, god) if mode == "ai" else None
        if visual.enabled() and mode != "none" and (simulated or budget is not False):
            notes = [f["text"] for f in q["findings"] if f["severity"] == "note"]
            rec = await visual.look(scene, rels, folder, brief=doc["brief"], notes=notes,
                                    budget_usd=None if budget is False else budget, simulated=simulated, quick=q)
            rec.update(quick=q["findings"], level="layout", name="Layout")
            visual.store_record(folder, rec)
            _charge(root, pid, org_id, user_id, int(rec.get("tokens") or 0), god, "Archie's look at the layout")
        text, acts = layout_message(doc, q, rec)
        with store.lock(pid):
            d = store.load(root, pid)
            if d is not None and d.get("icd"):
                d["icd"]["look"] = {"at": store.now(), "verdict": (rec or {}).get("verdict"),
                                    "quick": q["findings"], "image": bool(rec and rec.get("status") == "done"),
                                    "line": (rec or {}).get("line") or ""}
                store.save(root, d)
        archie_chat.post(root, pid, text, acts, kind="look",
                         visual={"level": "layout", "image": f"/api/office/programs/{pid}/visual/layout.png"
                                 if rec and rec.get("status") == "done" else None,
                                 "verdict": (rec or {}).get("verdict"), "quick": q["findings"],
                                 "tokens": int((rec or {}).get("tokens") or 0)})
        return rec
    except Exception:
        log.warning("layout look failed", exc_info=True)
        return None


# ----------------------------------------------------------------------------- (b) after an integration step
async def level_look(root: Path, pid: str, tid: str, aroot: Path, aid: str, *, org_id: str, user_id: str,
                     god: bool, mode: str) -> dict[str, Any]:
    """Look at one level's assembly after Fitz integrated it (``mode`` as in ``layout_look``). Returns {stop, reason,
    line, verdict, ...}. Never raises."""
    from aicad.assembly import render, visual
    from aicad.assembly import store as astore

    out: dict[str, Any] = {"stop": False, "reason": "", "line": "", "verdict": None}
    try:
        doc = store.load(root, pid)
        adoc = astore.load(aroot, aid)
        if doc is None or adoc is None or not adoc["instances"]:
            return out
        t = service.ticket(doc, tid)
        q = await asyncio.to_thread(visual.quick_doc, aroot, adoc)
        q["findings"] = known_loose(doc, adoc, q["findings"])
        rels = visual.relations_from_skeleton(_level_skeleton(doc, t), _level_ifaces(doc, t), doc["brief"])
        rec = None
        simulated = mode == "simulated"
        budget = _budget(org_id, god) if mode == "ai" else None
        folder = astore.doc_dir(aroot, aid) / "visual"
        if visual.enabled() and mode != "none" and (simulated or budget is not False):
            scene = await asyncio.to_thread(render.scene_from_doc, aroot, adoc, t["title"])
            rec = await visual.look(scene, rels, folder, brief=doc["brief"], simulated=simulated, quick=q,
                                    budget_usd=None if budget is False else budget)
            from aicad.assembly import service as aservice

            rec.update(quick=q["findings"], level=t["item_id"], name=t["title"],
                       signature=aservice.geometry_signature(adoc))
            visual.store_record(folder, rec)
            _charge(root, pid, org_id, user_id, int(rec.get("tokens") or 0), god, f"visual check of {t['title']}")
        verdict = (rec or {}).get("verdict")
        d = visual.decide(verdict, q, None)
        binned = {i["id"] for i in adoc["instances"] if (i.get("office") or {}).get("bin")}
        measured = False
        if d["exact"] == "targeted" and not d["stop"] and verdict:
            # parts in the parts bin are not placed at all: measuring them can't confirm or clear anything
            targets = [i for i in visual.targets_from(verdict, adoc, (rec or {}).get("key") or []) if i not in binned]
            try:
                clashes = await visual.targeted(aroot, org_id, adoc, targets) if targets else []
                measured = bool(targets)
            except Exception:  # noqa: BLE001 - a worker hiccup: the concern stays unconfirmed
                clashes = []
            d = visual.confirm(d, verdict, clashes)
        out.update(stop=bool(d["stop"]), reason=d.get("reason") or "", verdict=verdict,
                   line=(rec or {}).get("line") or "", unconfirmed=bool(d.get("unconfirmed")), measured=measured,
                   unplaced=unplaced_names(adoc, binned),
                   image=f"/api/m/assembly/assemblies/{aid}/visual.png" if rec and rec.get("status") == "done"
                   else None, quick=q["findings"], tokens=int((rec or {}).get("tokens") or 0))
        return out
    except Exception:
        log.warning("level look failed", exc_info=True)
        return out


def known_loose(doc: dict[str, Any], adoc: dict[str, Any], findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parts the approved layout gives no interface were placed beside the program on purpose (the engineer was told
    at the interfaces gate): a part of those apart from the rest is a note, not a stop. A whole level that touches
    nothing (a row) still stops: nothing there is assembled."""
    ifs = (doc.get("icd") or {}).get("interfaces") or []
    linked = {f[s]["item"] for f in ifs for s in ("a", "b")}
    sk = doc.get("skeleton") or {}
    items = sk.get("items") or {}
    loose_items = {i for i in items if i not in linked} if ifs else set()
    separate = set(sk.get("separate") or [])  # the engineer kept these separate at the gate
    loose_items |= separate
    loose = {i["id"] for i in adoc["instances"] if (i.get("office") or {}).get("item") in loose_items}
    kept = {i["id"] for i in adoc["instances"] if (i.get("office") or {}).get("item") in separate}
    out = []
    for f in findings:
        its = set(f.get("items") or [])
        if f["code"] in ("floating", "row") and its and len(its - kept) <= 1 and kept & its:
            continue  # only parts the engineer kept separate (and at most one other) touch nothing: as decided
        if f["code"] == "floating" and its and its <= loose:
            f = {**f, "severity": "note", "text": f["text"] + " The approved layout gives it no interface."}
        out.append(f)
    return out


def unplaced_names(adoc: dict[str, Any], binned: set[str]) -> list[str]:
    """The parts of a level Fitz left in the parts bin (the interfaces give them no seat), as people name them:
    "Pinion key", "2 × Gear circlip"."""
    count: dict[str, int] = {}
    for i in adoc["instances"]:
        if i["id"] in binned:
            count[i["name"]] = count.get(i["name"], 0) + 1
    return [n if k == 1 else f"{k} × {n}" for n, k in count.items()]


def _unplaced_line(names: list[str]) -> str:
    """Said plainly, never as reassurance (live run 2026-11-19: "found nothing to confirm it" about a key that no
    seat would ever take)."""
    if not names:
        return ""
    one = len(names) == 1 and " × " not in names[0]
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    it = "it" if one else "them"
    return (f"{listed} {'is' if one else 'are'} not placed: the interfaces have no seat for {it}, so Fitz left {it} "
            f"in the parts bin beside the assembly, not fitted. Fit {it} by hand in Assembly Studio, or change the "
            f"plan or the interfaces so they say where {'it goes' if one else 'they go'}.")


def level_message(t: dict[str, Any], look: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Archie's words after looking at an integrated level (pure)."""
    what = t["title"].removeprefix("Assemble ")
    loose = _unplaced_line(list(look.get("unplaced") or []))
    if look.get("stop"):
        found = [f["text"] for f in look.get("quick") or [] if f["severity"] == "block"]
        bullets = "\n".join(f"- {x}" for x in (found or [look["reason"]])[:4])
        line = look.get("line") or ""  # the reason already carries the visual line when a measurement confirmed it
        extra = f"\n{line}" if line and line not in bullets else ""
        if found:  # a placement measurement: the interfaces placed it so
            tip = ("The interfaces place every part, so this comes from the layout or the plan. I can rebuild the "
                   "program assembly from the approved interfaces and retry the step; if it stops again, the layout "
                   "needs a change (tell me what, or raise a change request on the Interfaces tab).")
        else:  # the picture, confirmed by a measured clash between the flagged parts
            tip = ("A measured clash between the flagged parts confirms what the picture shows. Look at the clash in "
                   "the assembly view: if a part is wrong, reopen it with a note; if the interface is wrong, raise a "
                   "change request on the Interfaces tab. I can retry the step once that is done.")
        return ((f"I stopped {t['key']} {t['title']}: {what} isn't assembled as the interfaces say.\n{bullets}{extra}"
                 + (f"\n- {loose}" if loose else "") + f"\n\n{tip}"), [{"type": "retry_blocked"}])
    if look.get("unconfirmed"):
        bits = [f"{what} is integrated. {look['line']}"]
        if loose:
            bits.append(loose)
        if look.get("measured"):
            bits.append("I checked the flagged parts that are placed for clashes and found none. A clash check can't "
                        "show a part that is loose or in the wrong place, so this is not a confirmation either way: "
                        "the office carries on, and the picture in the assembly view is worth a look.")
        elif not loose:
            bits.append("Nothing measured confirms it, so the office carries on; the picture in the assembly view is "
                        "worth a look.")
        else:
            bits.append("The office carries on with the parts that are placed.")
        return " ".join(bits), []
    if look.get("line") or loose:
        return " ".join(x for x in (f"{what} is integrated.", look.get("line") or "", loose) if x), []
    return "", []


def _level_skeleton(doc: dict[str, Any], t: dict[str, Any]) -> dict[str, Any]:
    sk = doc.get("skeleton") or {}
    if t["item_id"] == "root":
        return sk
    return {**sk, "items": {i: v for i, v in (sk.get("items") or {}).items() if v.get("sub") == t["item_id"]},
            "standard": [s for s in sk.get("standard") or [] if s.get("sub") == t["item_id"]]}


def _level_ifaces(doc: dict[str, Any], t: dict[str, Any]) -> list[dict[str, Any]]:
    ifs = (doc.get("icd") or {}).get("interfaces") or []
    if t["item_id"] == "root":
        return ifs
    items = (doc.get("skeleton") or {}).get("items") or {}
    mine = {i for i, v in items.items() if v.get("sub") == t["item_id"]}
    return [f for f in ifs if f["a"]["item"] in mine and f["b"]["item"] in mine]


# ----------------------------------------------------------------------------- (c) a failed or retried step
def failure_message(doc: dict[str, Any], t: dict[str, Any], why: str, retrying: bool = False
                    ) -> tuple[str, list[dict[str, Any]]]:
    """Archie on a blocked or retried step, from the program itself (pure, no AI)."""
    who = t["title"]
    if retrying:
        return ((f"{t['key']} {who} hit a problem: {why} The office retries it shortly on its own; if it keeps "
                "failing it will wait for you and I'll tell you what to do."), [])
    low = why.lower()
    if "run budget" in low:
        tip = ("I can put it back to work: the designer carries on from where it stopped, with a new run budget "
               "(more tokens). Or take it over in the Studio and finish it by hand.")
    elif "review" in low or "gage" in low or "rounds" in low:
        tip = ("Gage kept sending it back. I can put the blocked parts back to work under the current review rules "
               "(a part that passes every measurable check is approved with the open points recorded).")
    elif "clash" in low:
        tip = ("It still clashes in the program assembly. I can retry it; if the clash is in the layout, change the "
               "interface on the Interfaces tab (a change request) and I'll re-check it.")
    elif "assembly" in low or "placeholder" in low or "fitz" in low:
        tip = "I can retry the step; if the program assembly is out of date, rebuild it from the Assembly tab first."
    else:
        tip = "I can put it back to work and run the office; or take it over in the Studio."
    acts = [{"type": "retry_blocked"}] if doc["status"] in ("active", "complete") else []
    return f"{t['key']} {who} is blocked: {why}\n\n{tip}", acts


def on_failure(root: Path, doc: dict[str, Any], t: dict[str, Any], why: str, retrying: bool = False) -> None:
    """Called by the orchestrator (inside its program edit) when a step blocks or will be retried."""
    try:
        text, acts = failure_message(doc, t, why, retrying)
        archie_chat.post(root, doc["id"], text, acts, kind="office")
    except Exception:
        log.warning("Archie couldn't post the failure note", exc_info=True)


# ----------------------------------------------------------------------------- metering
def _budget(org_id: str, god: bool) -> float | None | bool:
    """USD cap for one look, None (unlimited God-mode tokens, still capped by the role), or False (no tokens left)."""
    from aicad.assembly import visual
    from aicad.platform import metering
    from aicad.platform.db import session_factory
    from aicad.platform.models import Organization

    cap = visual.CHECK_MAX_TOKENS * metering.USD_PER_TOKEN
    if god:
        return cap
    db = session_factory()()
    try:
        org = db.get(Organization, org_id)
        left = (org.token_balance if org else 0) - metering.reserved(org_id)
    finally:
        db.close()
    return cap if left >= visual.CHECK_MAX_TOKENS else False


def _charge(root: Path, pid: str, org_id: str, user_id: str, tokens: int, god: bool, what: str) -> None:
    from aicad.platform.db import session_factory
    from aicad.platform.models import Organization, User
    from aicad.platform.services import debit, track

    db = session_factory()()
    try:
        org, user = db.get(Organization, org_id), db.get(User, user_id)
        if tokens and org is not None and not god:
            debit(db, org, tokens, "usage", f"Design Office · {what}", user, ref=pid)
        track(db, "office_visual_check", user, org_id, tokens=0 if god else tokens)
        db.commit()
    finally:
        db.close()
    if tokens and not god:
        with store.lock(pid):
            d = store.load(root, pid)
            if d is not None:
                d["budget"]["planning_tokens"] = int(d["budget"].get("planning_tokens", 0)) + tokens
                store.save(root, d)
