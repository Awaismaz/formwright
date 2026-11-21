"""The program assembly (CD-011, CD-013): Fitz assembles the program from placeholders at ICD approval, mates every
interface by its ICD name, swaps each real part in when Gage approves it, and integrates each level.

Documents (normal Assembly Studio documents, so the engineer can open and edit them):
  * one assembly per sub-assembly: its items' instances at their skeleton positions (program frame), mated by the
    interfaces whose both sides are inside it, its base fixed;
  * the final assembly: every sub-assembly inserted as a nested sub-assembly (``assembly.service.insert_subassembly``,
    a copy kept in sync), plus the interfaces between sub-assemblies, the program base fixed.
Instances carry ``office = {program, item, copy}``; mates carry ``icd`` (the interface id) and ``icd_role``.

Mates by interface name (deterministic): bolted joint = coincident mounting faces + concentric on the two holes
farthest apart; shaft in a bore = concentric (+ flush end faces for a shaft through a block); seating face =
coincident; gear mesh = no mate (the skeleton spaces the shafts at the centre distance; Gage measures the teeth).
Features are found on each part's exact references (``refs.json``) and recognised holes (``info.json``) at the
positions the ICD gives in the part frame, so the same code mates a placeholder and the real part.

Swap-in keeps the instance (same id), resets it to the skeleton placement, re-attaches its interface mates by name
and re-runs the exact interference check; clashes involving the part are returned for Gage's "changes requested".
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aicad.assembly import locks
from aicad.office import frames, icd

_locks: dict[str, asyncio.Lock] = {}
ProjectPart = Callable[[str], Awaitable[str]]


def lock(pid: str) -> asyncio.Lock:
    """One assembly operation per program at a time (swap-ins from parallel Gage approvals queue here)."""
    return _locks.setdefault(pid, asyncio.Lock())


def placeholder_key(pid: str, item: str, spec: dict[str, Any]) -> str:
    h = hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:10]
    return f"h_{pid}_{item}_{h}"[:120]



# CD-038: every instance in a program assembly is placed from the approved layout (``place``); its mates record how
# the parts connect. Solving them numerically took 387 s per call on a 311-instance, 600-mate program (F1) and ran
# after every swap and integration, so the office records the layout placement instead of solving.


async def _placed(aroot: Path, doc: dict[str, Any]) -> None:
    """Record the layout placement and check every mate against it (one pass, no solve)."""
    from aicad.assembly import service as aservice

    await asyncio.to_thread(aservice.check_placement, aroot, doc)  # PD-71 interim: off in the office until fasteners are placed straight from the ICD


def subs_of(prog: dict[str, Any]) -> list[dict[str, Any]]:
    """Sub-assembly items (plan order) that hold at least one designed part."""
    sk = prog["skeleton"]
    return [i for i in prog["items"] if i["kind"] == "subassembly"
            and any(v["sub"] == i["id"] for v in sk["items"].values())]


def place(sk: dict[str, Any], item: str, copy: int, f: dict[str, Any] | None = None) -> list[float]:
    """Where an item copy sits: its part frame at the skeleton position, turned by its quarter-turn about Z, and
    (a real part modelled in another frame) through the frame Gage found."""
    it = sk["items"][item]
    return frames.placed(it["copies"][copy], float(it.get("rot") or 0) + float(it.get("phase") or 0), f,
                         it.get("ax") or "z")


# ----------------------------------------------------------------------------- finding interface features on a part
def find_feature(refs: dict[str, Any], info: dict[str, Any], feat: dict[str, Any]) -> int | None:
    """The face id (topology numbering) carrying one ICD feature, or None. A feature along X or Y (``ax``) is looked
    for in its canonical frame (face ids don't change with the frame)."""
    from aicad.office import conformance

    info, refs = conformance.in_canon(feat.get("ax"), info, refs)
    tol = max(float(feat.get("tol") or icd.POS_TOL), 0.05)
    faces = refs.get("faces") or {}
    if feat["type"] == "face":
        best = None
        for fid, r in faces.items():
            if r.get("kind") != "plane" or float(r["v"][2]) * feat["n"] < 1 - 1e-6:
                continue
            dz = abs(float(r["p"][2]) - feat["z"])
            if dz <= tol and (best is None or dz < best[0]):
                best = (dz, int(fid))
        return best[1] if best else None
    if feat["type"] == "hole":
        best = None
        for h in info.get("holes") or []:
            if abs(abs(float(h["axis"][2])) - 1) > 1e-3 or not h.get("faces"):
                continue
            off = math.hypot(float(h["center"][0]) - feat["c"][0], float(h["center"][1]) - feat["c"][1])
            if off <= tol and abs(float(h["d"]) - feat["d"]) <= 0.5 and (best is None or off < best[0]):
                best = (off, int(h["faces"][0]))
        return best[1] if best else None
    if feat["type"] == "seat":  # any cylinder along Z on the axis with that Ø (a bore over a Z range)
        best = None
        for fid, r in faces.items():
            if r.get("kind") != "axis" or r.get("r") is None or abs(abs(float(r["v"][2])) - 1) > 1e-3:
                continue
            off = math.hypot(float(r["p"][0]) - feat["c"][0], float(r["p"][1]) - feat["c"][1])
            if off <= tol and abs(2 * float(r["r"]) - feat["d"]) <= 0.5 and (best is None or off < best[0]):
                best = (off, int(fid))
        return best[1] if best else None
    if feat["type"] == "boss":
        holes = {int(f) for h in info.get("holes") or [] for f in h.get("faces") or []}
        best = None
        for fid, r in faces.items():
            if r.get("kind") != "axis" or r.get("r") is None or int(fid) in holes or abs(abs(float(r["v"][2])) - 1) > 1e-3:
                continue
            off = math.hypot(float(r["p"][0]) - feat["c"][0], float(r["p"][1]) - feat["c"][1])
            if off <= tol and abs(2 * float(r["r"]) - feat["d"]) <= 0.5 and (best is None or off < best[0]):
                best = (off, int(fid))
        return best[1] if best else None
    return None


def _part_data(aroot: Path, key: str, f: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Exact references and recognised features of a part, in its ICD part frame (through ``f`` when the part was
    modelled in another frame)."""
    from aicad.assembly import store as astore

    refs, info = astore.refs(aroot, key), (astore.part(aroot, key) or {}).get("info") or {}
    if f:
        return frames.refs_in(refs, f["R"], f["t"]), frames.info_in(info, f["R"], f["t"])
    return refs, info


def icd_mates(aroot: Path, adoc: dict[str, Any], skel: dict[str, Any], f: dict[str, Any], ia: dict[str, Any],
              ib: dict[str, Any]) -> tuple[int, list[str]]:
    """Mate two instances by one interface. Returns (mates made, problems)."""
    from aicad.assembly import AssemblyInputError
    from aicad.assembly import service as aservice

    fa, fb = icd.side_features(skel, f, "a"), icd.side_features(skel, f, "b")
    ra, na = _part_data(aroot, ia["part"], (ia.get("office") or {}).get("frame"))
    rb, nb = _part_data(aroot, ib["part"], (ib.get("office") or {}).get("frame"))
    pairs: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []  # (mate type, role, feat a, feat b)
    if f["kind"] == "hole_pattern":
        pairs.append(("coincident", "face", fa[0], fb[0]))
        ha, hb = fa[1:], fb[1:]
        if len(ha) >= 2:
            k0, k1 = max(((x, y) for x in range(len(ha)) for y in range(x + 1, len(ha))),
                         key=lambda xy: math.hypot(ha[xy[0]]["c"][0] - ha[xy[1]]["c"][0],
                                                   ha[xy[0]]["c"][1] - ha[xy[1]]["c"][1]))
            pairs += [("concentric", f"hole{k0 + 1}", ha[k0], hb[k0]), ("concentric", f"hole{k1 + 1}", ha[k1], hb[k1])]
        elif ha:
            pairs.append(("concentric", "hole1", ha[0], hb[0]))
    elif f["kind"] == "shaft_bore":
        pairs.append(("concentric", "axis", fa[0], fb[0]))
        ea = next((x for x in fa[1:] if "flush" in x["label"]), None)
        eb = next((x for x in fb[1:] if "flush" in x["label"]), None)
        if ea and eb:
            pairs.append(("flush", "end", ea, eb))
        sa = next((x for x in fa[1:] if "shoulder" in x["label"]), None)
        sb = next((x for x in fb[1:] if "shoulder" in x["label"]), None)
        if sa and sb:  # a hub against the shoulder of a stepped shaft
            pairs.append(("coincident", "shoulder", sa, sb))
    elif f["kind"] == "bearing_seat":
        seat = next(x for x in fa if x["type"] == "seat")
        journal = next(x for x in fb if x["type"] == "boss")
        pairs.append(("concentric", "axis", seat, journal))
        ea = next((x for x in fa if x["type"] == "face" and x["n"] < 0 and "flush" in x["label"]), None)
        eb = next((x for x in fb if x["type"] == "face"), None)
        if ea and eb:
            pairs.append(("flush", "end", ea, eb))
    elif f["kind"] == "bearing_journal":  # the shaft's journal in the bearing's bore (+ its shoulder on the ring)
        journal = next(x for x in fa if x["type"] == "boss")
        bore = next(x for x in fb if x["type"] == "seat")
        pairs.append(("concentric", "axis", journal, bore))
        sa = next((x for x in fa if x["type"] == "face"), None)
        sb = next((x for x in fb if x["type"] == "face"), None)
        if sa and sb:
            pairs.append(("coincident", "shoulder", sa, sb))
    elif f["kind"] == "face":
        pairs.append(("coincident", "face", fa[0], fb[0]))
    made, problems = 0, []
    for typ, role, xa, xb in pairs:
        ida, idb = find_feature(ra, na, xa), find_feature(rb, nb, xb)
        if ida is None or idb is None:
            who = ia["name"] if ida is None else ib["name"]
            problems.append(f"{f['id']} {f['name']}: {(xa if ida is None else xb)['label']} not found on {who}")
            continue
        try:
            m = aservice.make_mate(aroot, adoc, {"type": typ, "a": {"inst": ia["id"], "kind": "face", "id": ida},
                                                 "b": {"inst": ib["id"], "kind": "face", "id": idb}})
        except AssemblyInputError as e:
            problems.append(f"{f['id']}: {e}")
            continue
        m["icd"], m["icd_role"], m["icd_name"] = f["id"], role, f["name"]
        made += 1
    return made, problems


def _inst_of(adoc: dict[str, Any], item: str, copy: int) -> dict[str, Any] | None:
    return next((i for i in adoc["instances"] if (i.get("office") or {}).get("item") == item
                 and (i.get("office") or {}).get("copy") == copy), None)


def relink(aroot: Path, adoc: dict[str, Any], skel: dict[str, Any], ifaces: list[dict[str, Any]],
           items: set[str] | None, *, top_only: bool = False) -> tuple[int, list[str]]:
    """(Re)create the ICD mates of ``items`` (None = all) whose both sides are in this document. ``top_only``: only
    mates that are not copies from a sub-assembly (the final assembly's own interfaces)."""
    def touches(m: dict[str, Any]) -> bool:
        if not m.get("icd") or (top_only and m.get("sub")):
            return False
        f = next((x for x in ifaces if x["id"] == m["icd"]), None)
        return f is None or items is None or f["a"]["item"] in items or f["b"]["item"] in items

    adoc["mates"] = [m for m in adoc["mates"] if not touches(m)]
    have = {m["icd"] for m in adoc["mates"] if m.get("icd")}
    made, problems = 0, []
    for f in ifaces:
        if f["kind"] == "gear_mesh" or f["id"] in have:
            continue
        if items is not None and f["a"]["item"] not in items and f["b"]["item"] not in items:
            continue
        ia, ib = _inst_of(adoc, f["a"]["item"], f["a"]["copy"]), _inst_of(adoc, f["b"]["item"], f["b"]["copy"])
        if ia is None or ib is None:
            continue
        if top_only and ia.get("sub") and ia.get("sub") == ib.get("sub"):
            continue  # inside one sub-assembly: its own document carries that mate
        n, p = icd_mates(aroot, adoc, skel, f, ia, ib)
        made += n
        problems += p
    return made, problems


# ----------------------------------------------------------------------------- building the program assembly
async def _placeholder(aroot: Path, org_id: str, prog: dict[str, Any], item: str) -> str:
    from aicad.assembly import service as aservice

    spec = icd.placeholder_spec(prog["skeleton"], prog["icd"]["interfaces"], item)
    key = placeholder_key(prog["id"], item, spec)
    name = f"{prog['skeleton']['items'][item]['name']} (placeholder)"
    return await aservice.ensure_placeholder_part(aroot, org_id, key, spec, name, {
        "program_id": prog["id"], "item_id": item, "icd_version": prog["icd"]["version"]})


def _sub_base(prog: dict[str, Any], sub: str) -> str | None:
    sk = prog["skeleton"]
    mine = [i for i, v in sk["items"].items() if v["sub"] == sub]
    return next((i for i in mine if sk["items"][i]["parent"] not in mine), mine[0] if mine else None)


async def build(aroot: Path, org_id: str, user_id: str, prog: dict[str, Any],
                keys: dict[str, str] | None = None, frames: dict[str, dict[str, Any]] | None = None,
                keep_subs: set[str] | None = None) -> dict[str, Any]:
    """Create (or rebuild) every program assembly document. ``keys``: item -> part key for items that already have a
    real part (the rest get placeholders). ``frames``: item -> the frame Gage found for a real part modelled in
    another frame (placed through it, as a swap-in does). ``keep_subs``: sub-assemblies a program revision didn't
    touch: their documents (with the fasteners Fitz fitted) stay as they are. Returns the program's ``assembly``
    record."""
    from aicad.assembly import service as aservice
    from aicad.assembly import store as astore
    from aicad.assembly import xform

    sk, ifaces = prog["skeleton"], prog["icd"]["interfaces"]
    state = prog.get("assembly") or {}
    parts: dict[str, dict[str, Any]] = {}
    for item in sk["items"]:
        real = (keys or {}).get(item)
        key = real or await _placeholder(aroot, org_id, prog, item)
        parts[item] = {"key": key, "kind": "real" if real else "placeholder", "icd_version": prog["icd"]["version"]}
    problems: list[str] = []
    sub_docs: dict[str, dict[str, Any]] = {}
    for sub in subs_of(prog):
        aid = (state.get("subs") or {}).get(sub["id"])
        kept = astore.load(aroot, aid) if aid and sub["id"] in (keep_subs or set()) else None
        if kept is not None:  # untouched by a revision: as integrated
            sub_docs[sub["id"]] = kept
            continue
        fresh = astore.new_doc(f"{prog['name']} · {sub['name']}"[:120], org_id, user_id, None)
        async with locks.hold(aid or fresh["id"], locks.OFFICE):  # the same lock as Assembly Studio's hand edits
            adoc = (astore.load(aroot, aid) if aid else None) or fresh
            adoc.update(instances=[], mates=[], groups=[], subassemblies=[], solve=None,
                        office={"program": prog["id"], "level": sub["id"]})
            base = _sub_base(prog, sub["id"])
            for item, v in sk["items"].items():
                if v["sub"] != sub["id"]:
                    continue
                f = (frames or {}).get(item) if parts[item]["kind"] == "real" else None
                for c, _at in enumerate(v["copies"]):
                    inst = aservice.add_instance(aroot, adoc, parts[item]["key"], T=place(sk, item, c, f), name=v["name"])
                    inst["fixed"] = item == base and c == 0
                    inst["office"] = {"program": prog["id"], "item": item, "copy": c, **({"frame": f} if f else {})}
            if not any(i["fixed"] for i in adoc["instances"]) and adoc["instances"]:
                adoc["instances"][0]["fixed"] = True
            _n, p = await asyncio.to_thread(lambda adoc=adoc: relink(aroot, adoc, sk, ifaces, None))
            problems += p
            await _placed(aroot, adoc)
            astore.save(aroot, adoc)
        sub_docs[sub["id"]] = adoc
    fid = state.get("final")
    fresh = astore.new_doc(f"{prog['name']} · Final assembly"[:120], org_id, user_id, None)
    async with locks.hold(fid or fresh["id"], locks.OFFICE):
        final = (astore.load(aroot, fid) if fid else None) or fresh
        final.update(instances=[], mates=[], groups=[], subassemblies=[], solve=None,
                     office={"program": prog["id"], "level": "root"})
        for sub in subs_of(prog):
            aservice.insert_subassembly(aroot, final, sub_docs[sub["id"]], T=xform.to12(xform.ident()),
                                        name=sub["name"])
        for i in final["instances"]:
            o = i.get("office") or {}
            i["fixed"] = o.get("item") == sk["base"] and o.get("copy") == 0
        _n, p = await asyncio.to_thread(lambda: relink(aroot, final, sk, ifaces, None, top_only=True))
        problems += p
        await _placed(aroot, final)
        an = await aservice.analyse(aroot, org_id, final)
        astore.save(aroot, final)
    clashes = _clashes(an, final, ifaces)
    n_mates = len(final["mates"])
    n_ph = sum(1 for v in parts.values() if v["kind"] == "placeholder")
    summary = (f"Fitz assembled {prog['name']} from {n_ph} placeholder{'s' if n_ph != 1 else ''}"
               + (f" and {len(parts) - n_ph} real part{'s' if len(parts) - n_ph != 1 else ''}" if n_ph < len(parts) else "")
               + f": {n_mates} mates by interface name.")
    return {"status": "ready", "final": final["id"], "subs": {k: v["id"] for k, v in sub_docs.items()},
            "parts": parts, "at": astore.now(), "summary": summary, "clashes": clashes, "mates": n_mates,
            "check": {"status": "done", "scope": "placeholders", "count": len(clashes), "at": astore.now()},
            "problems": problems[:20], "solve": (final.get("solve") or {}).get("status"),
            "icd_version": prog["icd"]["version"]}


def _clashes(an: dict[str, Any], adoc: dict[str, Any] | None = None,
             ifaces: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    return [{"a": c["a"], "b": c["b"], "a_name": c.get("a_name"), "b_name": c.get("b_name"),
             "volume_mm3": round(float(c["volume_mm3"]), 3)} for c in an["interference"]["pairs"]
            if c["kind"] == "interference" and not (adoc is not None and ifaces and fit_rounding(adoc, ifaces, c))]


async def swap(aroot: Path, org_id: str, prog: dict[str, Any], updates: dict[str, str],
               analyse: bool = True, frames: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Put new part snapshots in for items (real part on approval, or a regenerated placeholder): same instances,
    skeleton placement, interface mates re-attached by name, interference re-run. ``updates``: item -> key.
    ``frames``: item -> the frame Gage found (``conformance.best_frame``) for a real part modelled in another frame:
    the instance is placed through it and its features are found through it."""
    from aicad.assembly import service as aservice
    from aicad.assembly import store as astore

    sk, ifaces = prog["skeleton"], prog["icd"]["interfaces"]
    state = dict(prog["assembly"])
    problems: list[str] = []
    items = set(updates)
    touched_subs = {sk["items"][i]["sub"] for i in items if i in sk["items"]}
    sub_docs: dict[str, dict[str, Any]] = {}
    fr = frames or {}
    for sub, aid in (state.get("subs") or {}).items():
        async with locks.hold(aid, locks.OFFICE):  # the same lock as Assembly Studio's hand edits
            adoc = astore.load(aroot, aid)
            if adoc is None:
                continue
            sub_docs[sub] = adoc
            if sub not in touched_subs:
                continue
            for inst in adoc["instances"]:
                o = inst.get("office") or {}
                if o.get("item") in items:
                    key = updates[o["item"]]
                    p = astore.part(aroot, key)
                    if p is None:
                        continue
                    inst["part"], inst["source"] = key, aservice._source(p)
                    f = fr.get(o["item"]) if not key.startswith("h_") else None
                    inst["T"] = place(sk, o["item"], o["copy"], f)
                    inst["office"] = {**o, "frame": f} if f else {k: v for k, v in o.items() if k != "frame"}
                    # stacks fitted through the old part no longer fit
                    for g in [g for g in adoc["groups"] if (g.get("hole") or {}).get("inst") == inst["id"]]:
                        aservice.remove_group(adoc, g["id"])
            _n, p = await asyncio.to_thread(lambda adoc=adoc: relink(aroot, adoc, sk, ifaces, items))
            problems += p
            await _placed(aroot, adoc)
            astore.save(aroot, adoc)
    clashes: list[dict[str, Any]] = state.get("clashes") or []
    # overlaps with a part that is still a placeholder (an envelope, not the part): noted, re-checked when that part
    # is built, never a reason to send the built part back (benchmark A1, 2026-11-21)
    pending: list[dict[str, Any]] = list(state.get("pending_clashes") or [])
    deferred: list[dict[str, Any]] = []
    names = {i: sk["items"][i]["name"] for i in sk["items"]}
    checked = False  # the swapped parts' clash check ran (only then may anyone say "0 clashes")
    async with locks.hold(state["final"], locks.OFFICE):
        final = astore.load(aroot, state["final"])
        if final is not None:
            for g in final.get("subassemblies") or []:
                src = sub_docs.get(next((s for s, a in state["subs"].items() if a == g["assembly_id"]), ""))
                if src is not None:
                    await asyncio.to_thread(aservice.sync_subassembly, aroot, final, g["id"], src)
            for inst in final["instances"]:
                o = inst.get("office") or {}
                inst["fixed"] = o.get("item") == sk["base"] and o.get("copy") == 0
            _n, p = await asyncio.to_thread(lambda: relink(aroot, final, sk, ifaces, items, top_only=True))
            problems += p
            await _placed(aroot, final)
            if analyse:
                # only the swapped parts against everything else (CD-035): the whole-program check grows with every
                # real part and runs at the final assembly; here it timed out once ten parts went in together
                checked = True
                ids = [i["id"] for i in final["instances"] if (i.get("office") or {}).get("item") in items]
                keep = [c for c in clashes if _item_of(final, c["a"]) not in items and _item_of(final, c["b"]) not in items]
                try:
                    fresh = await aservice.stack_clashes(aroot, org_id, final, ids)
                    fresh = [c for c in fresh if not _envelope_mesh(final, ifaces, c)
                             and not fit_rounding(final, ifaces, c)]
                    real: list[dict[str, Any]] = []
                    for c in fresh:
                        c = {**c, "volume_mm3": round(float(c["volume_mm3"]), 3)}
                        w = placeholder_side(final, c, items)
                        if w is None:
                            real.append(c)
                        else:
                            deferred.append({**c, "until": w, "until_name": names.get(w, w)})
                    clashes = keep + real
                    pending = [c for c in pending if _item_of(final, c["a"]) not in items
                               and _item_of(final, c["b"]) not in items] + deferred
                except aservice.WorkerError:
                    checked = False
                    problems.append("Fitz's clash check on these parts didn't finish in time; the final assembly's "
                                    "check covers them.")
            astore.save(aroot, final)
    parts = dict(state.get("parts") or {})
    for i, key in updates.items():
        parts[i] = {"key": key, "kind": "placeholder" if key.startswith("h_") else "real",
                    "icd_version": prog["icd"]["version"]}
    state["summary"] = summarize(parts, final)
    state.update(parts=parts, clashes=clashes, at=astore.now(), problems=problems[:20],
                 solve=((final or {}).get("solve") or {}).get("status"), mates=len((final or {}).get("mates") or []))
    if pending or state.get("pending_clashes"):
        state["pending_clashes"] = pending
    mine = [c for c in clashes if _item_of(final, c["a"]) in items or _item_of(final, c["b"]) in items]
    by_item = {i: [c for c in mine if i in (_item_of(final, c["a"]), _item_of(final, c["b"]))] for i in items}
    d_by = {i: [c for c in deferred if i in (_item_of(final, c["a"]), _item_of(final, c["b"]))] for i in items}
    state["last"] = {"items": sorted(items), "clashes": mine, "by_item": by_item, "problems": problems,
                     "text": ", ".join(names.get(i, i) for i in sorted(items)), "checked": checked,
                     "deferred": deferred, "deferred_by_item": d_by}
    if checked:
        state["check"] = {**(state.get("check") or {}), "status": "done", "scope": "swap", "count": len(clashes),
                          "at": astore.now()}
    return state


async def prewarm_swap(aroot: Path, org_id: str, prog: dict[str, Any], updates: dict[str, str],
                       frames: dict[str, dict[str, Any]] | None = None) -> int:
    """Fill the pair cache for a swap before the program lock is taken (ASM-023): the final assembly as saved, the
    swapped parts at their skeleton placement, mates solved, the swapped parts' pairs checked. Writes no document;
    the swap under the lock then finds its pairs in the cache (a part the solve puts elsewhere is simply a miss).
    Returns the pairs computed."""
    from aicad.assembly import service as aservice
    from aicad.assembly import store as astore

    state = prog.get("assembly") or {}
    final = astore.load(aroot, state["final"]) if state.get("final") else None
    if final is None:
        return 0
    sk, fr = prog["skeleton"], frames or {}
    ids = []
    for inst in final["instances"]:
        o = inst.get("office") or {}
        key = updates.get(o.get("item") or "")
        if key is None or o.get("copy") is None or astore.part(aroot, key) is None:
            continue
        inst["part"] = key
        inst["T"] = place(sk, o["item"], o["copy"], fr.get(o["item"]) if not key.startswith("h_") else None)
        ids.append(inst["id"])
    if not ids:
        return 0
    res = await aservice.check_pairs(aroot, org_id, final, only=ids)
    return int(res["stats"]["computed"])


def clash_status(state: dict[str, Any]) -> dict[str, Any]:
    """The program assembly's clash count, from ONE place (``state["clashes"]`` with ``state["check"]``): every
    page, comment and chat line takes it from here (live run 2026-11-19 showed "0 clashes" next to "2 clashes").
    ``count`` is None while no finished check covers the assembly."""
    chk = state.get("check") or {}
    n = len(state.get("clashes") or [])
    word = f"{n} clash{'es' if n != 1 else ''}"
    npend = len(state.get("pending_clashes") or [])
    tail = (f"; {npend} overlap{'s' if npend != 1 else ''} with placeholders, re-checked when those parts are built"
            if npend else "")
    if chk.get("status") == "running":
        return {"count": None, "status": "running", "text": "the whole-program clash check is running (advisory)"}
    if chk.get("status") == "failed":
        return {"count": None, "status": "failed", "text": "the whole-program clash check didn't finish (check "
                "clashes in Assembly Studio)"}
    if chk.get("status") == "done" and chk.get("scope") in (None, "program"):
        return {"count": n, "status": "done", "text": f"{word} in the whole-program check (advisory)"}
    if chk.get("status") == "done":
        return {"count": n, "status": "partial", "text": f"{word} at the last check ("
                + ("placeholders" if chk.get("scope") == "placeholders" else "the parts swapped in so far") + ")" + tail,
                "pending": npend}
    return {"count": None, "status": "none", "text": "no clash check yet"}


def summarize(parts: dict[str, dict[str, Any]], final: dict[str, Any] | None,
              clashes: list[dict[str, Any]] | None = None) -> str:
    """One line for the program page: real parts / placeholders, mates, fastener stacks. The clash count is not in
    it (``clash_status`` is the one source); ``clashes`` is accepted for older callers and ignored."""
    n_ph = sum(1 for v in parts.values() if v["kind"] == "placeholder")
    n_real = len(parts) - n_ph
    mates = len((final or {}).get("mates") or [])
    stacks = sum(1 for g in (final or {}).get("groups") or [] if g.get("kind") == "fastener")
    s = (f"{n_real} real part{'s' if n_real != 1 else ''} and {n_ph} placeholder{'s' if n_ph != 1 else ''}: "
         f"{mates} mates (interfaces mated by name)")
    if stacks:
        s += f", {stacks} fastener stack{'s' if stacks != 1 else ''}"
    _ = clashes
    return s + "."


def _envelope_mesh(adoc: dict[str, Any], ifaces: list[dict[str, Any]], c: dict[str, Any]) -> bool:
    """A real gear against the *placeholder* of the gear it meshes with: the placeholder is the tip-circle envelope,
    so the real teeth always overlap it. That is not a clash (it says nothing about the real mesh, which the
    whole-program check measures once both are real); reporting it sent a correct pinion back to its designer when
    it happened to be swapped in before its gear."""
    by = {i["id"]: i for i in adoc["instances"]}
    a, b = by.get(c["a"]), by.get(c["b"])
    if a is None or b is None:
        return False
    ia, ib = (a.get("office") or {}).get("item"), (b.get("office") or {}).get("item")
    if not any(f["kind"] == "gear_mesh" and {f["a"]["item"], f["b"]["item"]} == {ia, ib} for f in ifaces):
        return False
    return str(a.get("part", "")).startswith("h_") != str(b.get("part", "")).startswith("h_")


FIT_BAND = 0.01  # mm: the axis offset below which an overlap in a mated fit is that fit, not a clash
_FIT_KINDS = ("shaft_bore", "bearing_seat")


def fit_rounding(adoc: dict[str, Any], ifaces: list[dict[str, Any]], c: dict[str, Any]) -> bool:
    """An overlap between two parts the ICD mates in a cylindrical fit (a pin pressed into its bore, a shaft in its
    bearing seat) that is only the fit itself, a few microns off: equivalent axis offset V / (d L) at most
    ``FIT_BAND``, a tenth of the position tolerance. Rounding in one part's pattern and the other's placement made
    exactly this (benchmark A2, 2026-11-21: Planet pin #3 in the carrier, 0.58 mm³ for a 0.0015 mm offset). It is
    not a clash and must never send a correct part back."""
    by = {i["id"]: i for i in adoc["instances"]}
    a, b = by.get(c["a"]), by.get(c["b"])
    if a is None or b is None:
        return False
    oa, ob = a.get("office") or {}, b.get("office") or {}
    pair = {(oa.get("item"), int(oa.get("copy") or 0)), (ob.get("item"), int(ob.get("copy") or 0))}
    vol = float(c.get("volume_mm3") or 0)
    for f in ifaces:
        if f.get("kind") not in _FIT_KINDS:
            continue
        if {(f["a"]["item"], int(f["a"].get("copy") or 0)), (f["b"]["item"], int(f["b"].get("copy") or 0))} != pair:
            continue
        d = f["data"]
        z = d.get("z") or [0, 0]
        length = float(d.get("length") or abs(float(z[1]) - float(z[0])) or 0)
        dia = float(d.get("d") or 0)
        if dia > 0 and length > 0 and vol <= FIT_BAND * dia * length:
            return True
    return False


def placeholder_side(adoc: dict[str, Any], c: dict[str, Any], swapped: set[str] | None = None) -> str | None:
    """The item of the placeholder in a clash that involves one (a part against a placeholder, or two
    placeholders), else None. A placeholder is an envelope built from the ICD, not the part: its overlap with a built
    part is a measurement artefact until the part is built, and is re-checked then (benchmark A1, 2026-11-21: the
    built input shaft was sent back twice for a clash with the solid placeholder of an internal ring gear). When both
    sides are placeholders, the one not just swapped is named."""
    by = {i["id"]: i for i in adoc["instances"]}
    sides = [by.get(c["a"]), by.get(c["b"])]
    ph = [(i.get("office") or {}).get("item") for i in sides if i is not None and str(i.get("part", "")).startswith("h_")]
    ph = [x for x in ph if x]
    if not ph:
        return None
    return next((x for x in ph if x not in (swapped or set())), ph[0])


def pending_text(c: dict[str, Any]) -> str:
    """The note for an overlap with a placeholder: what it is and when it is checked for real."""
    who = c.get("until_name") or "the other part"
    return (f"{c['a_name']} ↔ {c['b_name']}: {float(c['volume_mm3']):.1f} mm³ against the placeholder of {who}, which "
            f"is not built yet; re-checked when {who} is built")


_CLASH_LINE = re.compile(r"Clash: (.+?) ↔ (.+?), [\d.]+ mm³")


def placeholder_only(doc: dict[str, Any], t: dict[str, Any]) -> list[str] | None:
    """A part ticket stopped for clashes that are all with parts still placeholders in the program assembly: the
    names of those parts, else None. Read from the ticket's clash lines ("Clash: A ↔ B, v mm³"), so it also
    recognises programs blocked before swap-in kept such overlaps as notes (benchmark A1, 2026-11-21)."""
    r = t.get("run") or {}
    lines = [str(x) for x in (r.get("feedback") or [])] + [str(r.get("blocked") or "")]
    sk = (doc.get("skeleton") or {}).get("items") or {}
    parts = (doc.get("assembly") or {}).get("parts") or {}
    by_name = {v["name"]: i for i, v in sk.items()}
    own = t.get("item_id")
    found: list[str] = []
    seen = False
    for ln in lines:
        for m in _CLASH_LINE.finditer(ln):
            seen = True
            a, b = (by_name.get(re.sub(r"<\d+>$", "", x.strip())) for x in m.groups())
            other = b if a == own else a if b == own else None
            if other is None or (parts.get(other) or {}).get("kind") != "placeholder":
                return None
            found.append(sk[other]["name"])
    return sorted(set(found)) if seen else None


def _item_of(adoc: dict[str, Any] | None, iid: str) -> str | None:
    if adoc is None:
        return None
    return next(((i.get("office") or {}).get("item") for i in adoc["instances"] if i["id"] == iid), None)


async def regenerate(aroot: Path, org_id: str, prog: dict[str, Any], items: set[str]) -> dict[str, Any]:
    """After an accepted change request: fresh placeholders for the affected items (their real parts go back to
    placeholders until they pass Gage again), mates re-attached."""
    updates = {i: await _placeholder(aroot, org_id, prog, i) for i in sorted(items) if i in prog["skeleton"]["items"]}
    return await swap(aroot, org_id, prog, updates)


# ----------------------------------------------------------------------------- integrating one level
def _hole_index(info: dict[str, Any], c: list[float], lax: str | None = None, z: float | None = None) -> int | None:
    """The recognised hole on the axis at ``c`` (canonical frame of part axis ``lax``). Holes are read per stretch
    along their line (recognize VERSION 4): with ``z`` (the joint plane), of several holes on that line (a housing's
    tapped holes in both end walls) the one nearest the joint."""
    if lax and lax != "z":
        from aicad.office import conformance

        info = conformance.in_canon(lax, info, {})[0]
    best: tuple[float, int] | None = None
    for k, h in enumerate(info.get("holes") or []):
        if abs(abs(float(h["axis"][2])) - 1) < 1e-3 and math.hypot(float(h["center"][0]) - c[0],
                                                                    float(h["center"][1]) - c[1]) <= 0.1:
            if z is None:
                return k
            zc, half = float(h["center"][2]), float(h.get("depth") or 0.0) / 2
            gap = max(0.0, abs(z - zc) - half)
            if best is None or gap < best[0]:
                best = (gap, k)
    return best[1] if best else None


def _hole_span(aroot: Path, inst: dict[str, Any], k: int, c: Any, u: Any) -> tuple[dict[str, Any], float, float]:
    """A recognised hole of a placed part (its info.json, part frame) as an interval along the joint axis (world)."""
    from aicad.assembly import store as astore
    from aicad.assembly import xform

    h = ((astore.part(aroot, inst["part"]) or {}).get("info") or {})["holes"][k]
    T = xform.from12(inst["T"])
    if h.get("open") is not None and h.get("dir") is not None:
        e0 = [float(x) for x in h["open"]]
        e1 = [e0[i] + float(h["dir"][i]) * float(h["depth"]) for i in range(3)]
    else:
        e0 = [float(h["center"][i]) - float(h["axis"][i]) * float(h["depth"]) / 2 for i in range(3)]
        e1 = [float(h["center"][i]) + float(h["axis"][i]) * float(h["depth"]) / 2 for i in range(3)]
    t0, t1 = sorted(float((xform.pt(T, e) - c) @ u) for e in (e0, e1))
    return h, t0, t1


def _seat_face(aroot: Path, inst: dict[str, Any], point: Any, out: Any) -> int | None:
    """The planar face of a placed part through ``point`` whose outward normal is ``out`` (world): where a washer,
    head or nut sits (exact references, refs.json)."""
    from aicad.assembly import store as astore
    from aicad.assembly import xform

    Ti = xform.inv(xform.from12(inst["T"]))
    q, n = xform.pt(Ti, point), xform.unit(xform.vec(Ti, out))
    best = None
    for fid, r in (astore.refs(aroot, inst["part"]).get("faces") or {}).items():
        if r.get("kind") != "plane" or float(n @ r["v"]) < 1 - 1e-6:
            continue
        off = abs(float((q - r["p"]) @ r["v"]))
        if off <= 0.05 and (best is None or off < best[0]):
            best = (off, int(fid))
    return best[1] if best else None


def program_material(prog: dict[str, Any] | None) -> str | None:
    """The program's housing material, when the plan's design graph knows it: the housing component's material, else
    the answer to a material question (e.g. "Cast iron"). Used for a tapped part whose own material is unknown."""
    data = (((prog or {}).get("plan") or {}).get("graph") or {}).get("data") or {}
    for c in data.get("components") or []:
        if c.get("kind") == "housing" and str(c.get("material") or "").strip():
            return str(c["material"])
    answers = data.get("answers") or {}
    for k in sorted(answers):
        if k.startswith("material") and str(answers[k] or "").strip():
            return str(answers[k])
    return None


def icd_stack(aroot: Path, adoc: dict[str, Any], sk: dict[str, Any], f: dict[str, Any], xy: list[float],
              fitted: set[tuple[str, int]], material: str | None = None) -> dict[str, Any] | None:
    """One bolted-joint hole as the stack Fitz fits there, straight from the ICD (PD-71): the hole the ICD put in each
    part (looked up in the part's recognised holes, no kernel work), the clamped thickness from those holes along
    the joint axis, head on the mounted part, nut under the host or a screw into the host's tapped hole. Returns
    {inst, hole, probe} in the shape ``assembly.service.insert_planned`` takes, or None (the hole isn't there, or it
    already has a stack)."""
    import numpy as np

    from aicad.assembly import service as aservice
    from aicad.assembly import store as astore
    from aicad.assembly import xform

    d = f["data"]
    ia, ib = _inst_of(adoc, f["a"]["item"], f["a"]["copy"]), _inst_of(adoc, f["b"]["item"], f["b"]["copy"])
    if ia is None or ib is None:
        return None
    gb = icd._axial(sk, f["b"], d, xy, d["plane_z"], d["plane_z"])   # z0 = z1: the joint plane in the part's frame
    kb = _hole_index(_part_data(aroot, ib["part"], (ib.get("office") or {}).get("frame"))[1], gb["c"], gb.get("ax"),
                     gb["z0"])
    if kb is None or (ib["id"], kb) in fitted:
        return None
    ga = icd._axial(sk, f["a"], d, xy, d["plane_z"], d["plane_z"])
    ka = _hole_index(_part_data(aroot, ia["part"], (ia.get("office") or {}).get("frame"))[1], ga["c"], ga.get("ax"),
                     ga["z0"])
    hb = ((astore.part(aroot, ib["part"]) or {}).get("info") or {})["holes"][kb]
    Tb = xform.from12(ib["T"])
    c = xform.pt(Tb, (hb.get("exact") or {}).get("p") or hb["center"])
    u = xform.unit(xform.vec(Tb, hb["axis"]))
    normal = np.asarray(d.get("normal") or [0, 0, 1], dtype=float)
    if float(u @ normal) < 0:
        u = -u  # u: from the host (a) to the mounted part (b), the head side
    _h, b0, b1 = _hole_span(aroot, ib, kb, c, u)
    tp = d.get("tapped")
    if ka is None:
        if not tp:
            return None  # a through joint needs the host's hole for the nut side
        a0, a1, ha = b0 - float(tp["depth"]), b0, {"d": tp["d"], "through": False}
    else:
        ha, a0, a1 = _hole_span(aroot, ia, ka, c, u)
    names = aservice.display_names(adoc)
    head_pt, nut_pt = c + u * b1, c + u * a0
    probe: dict[str, Any] = {
        "kind": "tapped" if tp else "through", "hole_d": float(hb["d"]), "warnings": [], "tapped": None,
        "axis": {"p": [float(x) for x in c], "u": [float(x) for x in u]},
        "hole": {"faces": hb.get("faces") or []}, "planned": f["id"],
        "head": {"point": [float(x) for x in head_pt], "out": [float(x) for x in u], "inst": ib["id"],
                 "face": _seat_face(aroot, ib, head_pt, u), "space": None},
        "nut": {"point": [float(x) for x in nut_pt], "out": [float(x) for x in -u], "inst": ia["id"],
                "face": None if tp else _seat_face(aroot, ia, nut_pt, -u), "space": None}}
    if tp:
        probe["grip"] = round(b1 - b0, 4)
        probe["members"] = [{"inst": ib["id"], "name": names[ib["id"]], "t": round(b1 - b0, 4)}]
        probe["tapped"] = {"inst": ia["id"], "name": names[ia["id"]], "d": float(ha["d"]),
                           "depth": round(a1 - a0, 4), "blind": not ha.get("through"),
                           "material": _tapped_material((astore.part(aroot, ia["part"]) or {}).get("material"),
                                                        material)}
    else:
        probe["grip"] = round(b1 - a0, 4)
        probe["members"] = [{"inst": ib["id"], "name": names[ib["id"]], "t": round(b1 - b0, 4)},
                            {"inst": ia["id"], "name": names[ia["id"]], "t": round(a1 - a0, 4)}]
    return {"inst": ib["id"], "hole": kb, "probe": probe}


def _integration_order(t: dict[str, Any]) -> int:
    """Fasteners first, then nuts and washers (counted against the stacks), then the rest (stable in plan order)."""
    r = t.get("reuse") or {}
    if r.get("kind") == "fastener" or r.get("code") in ("hex_bolt", "shcs"):
        return 0
    return 1 if r.get("code") in ("hex_nut", "washer") else 2


def _stack_hardware(aroot: Path, adoc: dict[str, Any]) -> dict[tuple[str, float], int]:
    """Washers and nuts in this assembly's fastener stacks: {(code, D): count}."""
    from aicad.assembly import store as astore

    stacks = {g["id"] for g in adoc.get("groups") or [] if g.get("kind") == "fastener"}
    out: dict[tuple[str, float], int] = {}
    for i in adoc["instances"]:
        if i.get("group") not in stacks:
            continue
        p = astore.part(aroot, i["part"]) or {}
        code = p.get("code")
        if code in ("hex_nut", "washer") and (p.get("params") or {}).get("D") is not None:
            k = (str(code), float(p["params"]["D"]))
            out[k] = out.get(k, 0) + 1
    return out


def _tapped_material(own: str | None, program: str | None) -> str | None:
    """The tapped part's own material; the program's housing material only when the part's is unknown (PD-285)."""
    from aicad.assembly import fasteners

    if program and fasteners.engagement_factor(own)[1] == fasteners.UNKNOWN_MATERIAL:
        return program
    return own


def plan_stacks(aroot: Path, adoc: dict[str, Any], sk: dict[str, Any], joints: list[dict[str, Any]],
                fitted: set[tuple[str, int]], material: str | None = None) -> list[dict[str, Any]]:
    """Every hole of these bolted joints that has no stack yet, as ``icd_stack`` plans it (``fitted`` is updated).
    ``material``: the program's housing material (``program_material``), for tapped parts of unknown material."""
    out = []
    for f in joints:
        for xy in f["data"]["positions"]:
            h = icd_stack(aroot, adoc, sk, f, xy, fitted, material)
            if h is not None:
                out.append(h)
                fitted.add((h["inst"], h["hole"]))
    return out


async def integrate(aroot: Path, org_id: str, prog: dict[str, Any], level: str,
                    standard: list[dict[str, Any]]) -> dict[str, Any]:
    """Fit the level's fasteners into its bolted joints (ISO auto-fit through both parts), put its other standard
    parts in the parts bin beside the program, refresh the final assembly's sub-assemblies, re-check interference.
    ``level``: a sub-assembly item id or "root". ``standard``: the level's standard tickets (with their reuse)."""
    from aicad.assembly import AssemblyInputError, xform
    from aicad.assembly import service as aservice
    from aicad.assembly import store as astore

    sk, ifaces = prog["skeleton"], prog["icd"]["interfaces"]
    state = prog["assembly"]
    log: list[dict[str, str]] = []
    stats = {"stacks": 0, "asked": 0, "binned": 0, "unplaced": 0, "in_stacks": 0}
    unchecked = False  # the whole-program clash check didn't finish: never report "0 clashes" then
    seated: dict[str, int] = {}

    def say(text: str, tone: str = "ok") -> None:
        log.append({"agent": "Fitz", "text": text, "tone": tone})

    if level != "root":
        aid = state["subs"].get(level)
        if not aid or astore.load(aroot, aid) is None:
            return {"blocked": "The sub-assembly's assembly document is missing. Rebuild the program assembly."}
        async with locks.hold(aid, locks.OFFICE):  # the same lock as Assembly Studio's hand edits
            adoc = astore.load(aroot, aid)
            joints = [f for f in ifaces if f["kind"] == "hole_pattern" and sk["items"][f["a"]["item"]]["sub"] == level
                      and sk["items"][f["b"]["item"]]["sub"] == level]
            fitted = {(g["hole"]["inst"], int(g["hole"]["hole"])) for g in adoc["groups"] if g.get("hole")}
            env = sk["envelope"]
            bin_y = env["max"][1] + 40.0
            bin_x = env["min"][0]
            sub_items = [x["id"] for x in prog["items"] if x["kind"] == "subassembly"]
            bin_x += 120.0 * (sub_items.index(level) if level in sub_items else 0)
            # fasteners first, then the plan's nuts and washers (they are the stacks' own when the sizes match),
            # then everything else
            stack_hw: dict[tuple[str, float], int] | None = None
            for t in sorted(standard, key=_integration_order):
                r = t.get("reuse") or {}
                if r.get("source") != "toolbox":
                    if t["kind"] in ("standard", "part") and not t.get("_kit") and t["item_id"] not in sk["items"]:
                        # a bought-out part Hex didn't stock (a plug, a seal): modelled by a designer, but the ICD has
                        # no place for it, so it is reported, never left lying beside the program
                        stats["unplaced"] += int(t.get("qty") or 1)
                        say(f"{t['title']} has no interface in the ICD, so Fitz didn't place it ({int(t.get('qty') or 1)}"
                            " in the BOM as planned): fit it by hand in Assembly Studio", "warn")
                    continue
                kind, code = r.get("kind"), r.get("code")
                is_fastener = kind == "fastener" or code in ("hex_bolt", "shcs")
                if t.get("_kit") and not is_fastener:
                    continue  # kit parts that aren't fasteners (inserts, pins) are not this level's to place
                # integrating again (a change reopened the level): the pieces Fitz seated or binned last time go,
                # so they are placed once, where the ICD says now (fastener stacks are skipped by ``fitted``)
                for old in [i for i in adoc["instances"] if (i.get("office") or {}).get("item") == t["item_id"]
                            and ((i.get("office") or {}).get("bin") or (i.get("office") or {}).get("seated"))]:
                    aservice.remove_instance(adoc, old["id"])
                seat = icd.seated(ifaces, t["item_id"])
                if seat:  # bearings in their seats, dowel pins in their holes (coaxial with the ICD features)
                    try:
                        key = await aservice.ensure_toolbox_part(aroot, org_id, seat["code"], seat["params"])
                    except Exception as e:  # noqa: BLE001 - a size the generator refuses
                        say(f"{t['title']}: {e}", "warn")
                        continue
                    for n, at in enumerate(seat["at"]):
                        T = frames.to12(seat["R"], at) if seat.get("R") else xform.to12(xform.translate(tuple(at)))
                        inst = aservice.add_instance(aroot, adoc, key, T=T,
                                                     name=t["title"])
                        inst["office"] = {"program": prog["id"], "item": t["item_id"], "copy": n, "seated": seat["interface"]}
                    what = {"bearing": "bearing", "dowel": "dowel pin", "parallel_key": "key",
                            "retaining_ring": "retaining ring"}.get(seat["code"], "part")
                    seated[what] = seated.get(what, 0) + len(seat["at"])
                    if any(f["kind"] == "bearing_journal" and f["b"]["item"] == t["item_id"] for f in ifaces):
                        # bearings on shaft journals (no housing): mated to their shafts by interface name
                        _nm, pm = await asyncio.to_thread(
                            lambda adoc=adoc, it=t["item_id"]: relink(aroot, adoc, sk, ifaces, {it}))
                        if pm:
                            say(f"{t['title']}: {pm[0]}", "warn")
                    extra = int(t.get("qty") or 1) - len(seat["at"])
                    say(f"Fitz seated {len(seat['at'])} × {seat['title']} in the {seat['what']} of {seat['interface']}"
                        + (f" ({extra} more than the ICD places: left out)" if extra > 0 else ""),
                        "ok" if extra <= 0 else "warn")
                    continue
                if kind == "fastener" or code in ("hex_bolt", "shcs"):
                    # a joint whose ICD names another fastener item is that item's: never stacked with this one
                    # (golden suite F6: the cover bolts took the caps' joints, 16 hex bolts for the cap screws)
                    mine = [f for f in joints if f["data"].get("fastener_item") in (None, t["item_id"])] or \
                        [f for f in joints if not any(t2.get("item_id") == f["data"].get("fastener_item")
                                                      for t2 in prog.get("tickets") or [])]
                    planned = await asyncio.to_thread(plan_stacks, aroot, adoc, sk, mine, fitted,
                                                      program_material(prog))
                    want = int(t.get("qty") or 1)
                    if t.get("_kit"):
                        if not planned:
                            continue  # no joint for the kit here: other levels take them
                        want = len(planned)
                    stats["asked"] += want
                    planned = planned[:want]
                    if not planned and any(f["kind"] == "hole_pattern" and f["data"].get("fastener_item") == t["item_id"]
                                           and sk["items"][f["a"]["item"]]["sub"] != sk["items"][f["b"]["item"]]["sub"]
                                           for f in ifaces):
                        say(f"{t['title']}: their joints are between sub-assemblies, so Fitz fits them in the final "
                            "assembly")
                        continue
                    if not planned:
                        stats["unplaced"] += want
                        say(f"{t['title']}: no bolted joint of the ICD inside this sub-assembly takes it, so Fitz "
                            f"didn't place it ({want} in the BOM as planned)", "warn")
                        continue
                    else:
                        # PD-71: straight from the ICD (positions, thickness, size): no probe, no clash check
                        try:
                            res = await aservice.insert_planned(aroot, org_id, adoc, planned,
                                                                "shcs" if code == "shcs" else "hex_bolt")
                        except AssemblyInputError as e:  # e.g. the assembly is full
                            say(f"Fitz couldn't fit {t['title']}: {e}", "warn")
                            continue
                        stats["stacks"] += res["inserted"]
                        errs = sorted({h["proposal"]["error"] for h in res["plan"]["holes"]
                                       if not h["proposal"]["ok"] and h["proposal"].get("error")})
                        stack_hw = None  # the stacks changed: count their washers and nuts again
                        if res["inserted"]:
                            summ = sorted({h["proposal"]["summary"] for h in res["plan"]["holes"] if h["proposal"]["ok"]})
                            extra = int(t.get("qty") or 1) - res["inserted"] if not t.get("_kit") else 0
                            stats["unplaced"] += max(0, extra)
                            say(f"Fitz fitted {res['inserted']} of {want} {t['title'].lower()} from the ICD: "
                                + "; ".join(summ)
                                + (f" ({extra} more than the ICD's joints take: not placed, in the BOM as planned)"
                                   if extra > 0 else "")
                                + (f". Not fitted: {errs[0]}" if errs else ""),
                                "ok" if extra <= 0 and not errs else "warn")
                            continue
                        stats["unplaced"] += want
                        say(f"Fitz couldn't fit {t['title']}: {errs[0] if errs else 'no standard stack fits'} "
                            f"({want} not placed, in the BOM as planned)", "warn")
                        continue
                if code in ("hex_nut", "washer") and not t.get("_kit") and (r.get("params") or {}).get("D"):
                    # the plan's nuts / washers for its bolts: the ICD's stacks carry their own (ISO 4032 / 7089), so
                    # the plan's are those when the size matches; the rest are more than the joints use
                    if stack_hw is None:
                        stack_hw = _stack_hardware(aroot, adoc)
                    D = float(r["params"]["D"])
                    want = int(t.get("qty") or 1)
                    used = min(want, stack_hw.get((code, D), 0))
                    stack_hw[(code, D)] = stack_hw.get((code, D), 0) - used
                    stats["in_stacks"] += used
                    stats["unplaced"] += want - used
                    what = "nuts" if code == "hex_nut" else "washers"
                    if used == want:
                        say(f"{t['title']}: all {want} are in the bolt stacks Fitz fitted from the ICD")
                    elif used:
                        say(f"{t['title']}: {used} of {want} are in the bolt stacks Fitz fitted from the ICD; the other "
                            f"{want - used} are more than the joints use (not placed, in the BOM as planned)", "warn")
                    else:
                        say(f"{t['title']}: no bolt stack of the ICD here uses M{D:g} {what}"
                            + (" (its joints are tapped into the part)" if code == "hex_nut" else "")
                            + f", so Fitz didn't place them ({want} in the BOM as planned)", "warn")
                    continue
                # everything else (and fasteners that found no joint): the parts bin, beside the program, no clash
                try:
                    key = await aservice.ensure_toolbox_part(aroot, org_id, code, r.get("params") or {})
                except Exception as e:  # noqa: BLE001 - a Toolbox value Hex read but the generator refuses
                    say(f"{t['title']}: {e}", "warn")
                    continue
                part = astore.part(aroot, key) or {}
                bb = (part.get("info") or {}).get("bbox") or [0, 0, 0, 10, 10, 10]
                for _n in range(min(int(t.get("qty") or 1), 4)):
                    inst = aservice.add_instance(aroot, adoc, key, T=xform.to12(xform.translate(
                        (bin_x - bb[0], bin_y - bb[1], -bb[2]))), name=t["title"])
                    inst["office"] = {"program": prog["id"], "item": t["item_id"], "copy": _n, "bin": True}
                    bin_x += (bb[3] - bb[0]) + 10.0
                    stats["binned"] += 1
                say(f"{t['title']} is in the parts bin beside the program: the ICD has no interface for it yet, mate it "
                    "by hand", "muted")
            await _placed(aroot, adoc)
            astore.save(aroot, adoc)
            # PD-71: no interference work in a sub-assembly step: every part was checked by Gage and when Fitz swapped
            # it in, and the stacks come from the ICD; the whole-program check runs after the final assembly (advisory)
            clashes = []
            aid_out = adoc["id"]
    else:
        clashes = []
        aid_out = state["final"]
    # the final assembly follows every sub-assembly
    async with locks.hold(state["final"], locks.OFFICE):
        final = astore.load(aroot, state["final"])
        if final is not None:
            for g in final.get("subassemblies") or []:
                sub = next((s for s, a in state["subs"].items() if a == g["assembly_id"]), None)
                src = astore.load(aroot, state["subs"][sub]) if sub else None
                if src is not None:
                    await asyncio.to_thread(aservice.sync_subassembly, aroot, final, g["id"], src)
            for inst in final["instances"]:
                o = inst.get("office") or {}
                inst["fixed"] = o.get("item") == sk["base"] and o.get("copy") == 0 and not o.get("bin")
            await asyncio.to_thread(lambda: relink(aroot, final, sk, ifaces, None, top_only=True))
            if level == "root":
                # bolted joints between sub-assemblies: Fitz's auto-fit (ISO 4017 + washers + ISO 4032)
                joints = [f for f in ifaces if f["kind"] == "hole_pattern"
                          and sk["items"][f["a"]["item"]]["sub"] != sk["items"][f["b"]["item"]]["sub"]]
                fitted = {(g["hole"]["inst"], int(g["hole"]["hole"])) for g in final["groups"] if g.get("hole")}
                # each joint takes the style of the fastener its ICD names (cap screws stay socket head, golden F6)
                by_style: dict[str, list[dict[str, Any]]] = {}
                for f in joints:
                    tk = next((x for x in prog.get("tickets") or []
                               if x.get("item_id") and x.get("item_id") == f["data"].get("fastener_item")), None)
                    code = ((tk or {}).get("reuse") or {}).get("code")
                    by_style.setdefault("shcs" if code == "shcs" else "hex_bolt", []).append(f)
                for style, js in by_style.items():
                    planned = await asyncio.to_thread(plan_stacks, aroot, final, sk, js, fitted, program_material(prog))
                    if not planned:
                        continue
                    try:  # PD-71: from the ICD, like every level
                        res = await aservice.insert_planned(aroot, org_id, final, planned, style)
                    except AssemblyInputError as e:  # e.g. the assembly is full
                        res = {"inserted": 0, "plan": {"holes": [{"proposal": {"ok": False, "error": str(e)}}]}}
                    stats["stacks"] += res["inserted"]
                    if res["inserted"]:
                        say(f"Fitz fitted {res['inserted']} {'cap screw' if style == 'shcs' else 'bolt'} stacks at the "
                            "joints between sub-assemblies (from the ICD)")
                    else:
                        say("Fitz couldn't fit the joints between sub-assemblies: " + next(
                            (h["proposal"]["error"] for h in res["plan"]["holes"] if h["proposal"].get("error")),
                            "no standard stack fits"), "warn")
            await _placed(aroot, final)
            # PD-71: the whole-program clash check is advisory and runs after this, outside the program lock
            # (``advisory_check``): it never holds up or fails the integration
            astore.save(aroot, final)
    bits = []
    if stats["asked"]:
        bits.append(f"fitted {stats['stacks']} fastener stack{'s' if stats['stacks'] != 1 else ''}")
    elif stats["stacks"]:
        bits.append(f"fitted {stats['stacks']} fastener stacks between sub-assemblies")
    for what, n in seated.items():
        bits.append(f"seated {n} {what}{'s' if n != 1 else ''} per the ICD")
    if stats["binned"]:
        bits.append(f"{stats['binned']} part{'s' if stats['binned'] != 1 else ''} in the parts bin")
    if stats["unplaced"]:
        bits.append(f"{stats['unplaced']} planned part{'s' if stats['unplaced'] != 1 else ''} not placed (more than "
                    "the ICD uses, or no interface: see the notes)")
    name = "the program" if level == "root" else next((x["name"] for x in prog["items"] if x["id"] == level), level)
    # PD-71: integration measures no clashes, so it never states a count ("0 clashes" was said under "2 clashes"
    # in the live run 2026-11-19); the final assembly's whole-program check reports them (``clash_status``)
    tail = (". Fitz's whole-program clash check runs now (advisory)" if level == "root" and not unchecked else
            ", clash check didn't finish (check clashes in Assembly Studio)" if unchecked else "")
    summary = f"Fitz integrated {name}" + (": " + ", ".join(bits) if bits else "") + tail + "."
    say(summary, "ok")
    return {"summary": summary, "clashes": clashes, "log": log, "assembly_id": aid_out, "inserted": stats["stacks"],
            "program_summary": summarize(state.get("parts") or {}, final)}


# ----------------------------------------------------------------------------- advisory whole-program check (PD-71)
async def advisory_check(aroot: Path, org_id: str, prog: dict[str, Any]) -> dict[str, Any]:
    """The whole-program clash check after the final assembly: exact interference of every pair (the pair cache
    makes most of them hits), saved as the final assembly's analysis so the Assembly tab shows the clash volumes.
    Advisory: called outside the program lock, it never blocks or fails anything. Returns {clashes, text, ...}."""
    import time

    from aicad.assembly import store as astore

    t0 = time.perf_counter()
    fid = (prog.get("assembly") or {}).get("final")
    final = astore.load(aroot, fid) if fid else None
    if final is None:
        return {"status": "skipped", "clashes": [], "text": "No final assembly to check."}
    from aicad.assembly import service as aservice

    an = await aservice.analyse(aroot, org_id, final, clearance=False)
    clashes = _clashes(an, final, (prog.get("icd") or {}).get("interfaces") or [])
    n = len(clashes)
    if n:
        top = "; ".join(f"{c['a_name']} ↔ {c['b_name']} {c['volume_mm3']:.1f} mm³" for c in clashes[:5])
        text = (f"Fitz's whole-program clash check (advisory): {n} clash{'es' if n != 1 else ''} in the final "
                f"assembly: {top}. They are shown on the Assembly tab; nothing was held up.")
    else:
        text = (f"Fitz's whole-program clash check (advisory): no clashes across "
                f"{an['interference']['checked_pairs']} candidate pairs in the final assembly.")
    return {"status": "done", "scope": "program", "clashes": clashes, "text": text, "at": astore.now(),
            "checked_pairs": an["interference"]["checked_pairs"], "seconds": round(time.perf_counter() - t0, 1),
            "computed": an["pairs"]["computed"], "cached": an["pairs"]["cached"]}


# ----------------------------------------------------------------------------- the live view (CD-013)
def view(aroot: Path, prog: dict[str, Any]) -> dict[str, Any] | None:
    """What the program's live assembly view needs: the final assembly's instances with their item and state,
    part topology links, exploded offsets and the clash volumes of the last check."""
    from aicad.assembly import service as aservice
    from aicad.assembly import store as astore

    state = prog.get("assembly") or {}
    if not state.get("final"):
        return None
    adoc = astore.load(aroot, state["final"])
    if adoc is None:
        return None
    parts = aservice._parts(aroot, adoc)
    names = aservice.display_names(adoc)
    sk = prog["skeleton"]
    insts = []
    for i in adoc["instances"]:
        o = i.get("office") or {}
        p = parts[i["part"]]
        insts.append({"id": i["id"], "name": names[i["id"]], "part": i["part"], "T": i["T"], "item": o.get("item"),
                      "copy": o.get("copy"), "kind": p["kind"] if p["kind"] != "project" else "real",
                      "fastener": bool(i.get("group")), "bin": bool(o.get("bin")), "sub": i.get("sub")})
    pview = {k: {"key": k, "topo_url": f"/api/m/assembly/parts/{k}/topo", "bbox": p["info"]["bbox"],
                 "kind": p["kind"]} for k, p in parts.items()}
    analysis = astore.read_json(astore.doc_dir(aroot, adoc["id"]) / "analysis.json") or {}
    stale = analysis.get("signature") != aservice.geometry_signature(adoc)
    clashes = [{"a": c["a"], "b": c["b"], "a_name": c.get("a_name"), "b_name": c.get("b_name"),
                "volume_mm3": c["volume_mm3"], "mesh": c.get("mesh")}
               for c in (analysis.get("interference") or {}).get("pairs") or [] if c.get("kind") == "interference"
               and not fit_rounding(adoc, (prog.get("icd") or {}).get("interfaces") or [], c)]
    return {"assembly_id": adoc["id"], "rev": adoc["rev"], "instances": insts, "parts": pview,
            "explode": aservice.explode(aroot, adoc), "clashes": [] if stale else clashes,
            "solve": (adoc.get("solve") or {}).get("status"), "envelope": sk["envelope"],
            "subs": [{"id": g["id"], "name": g["name"], "assembly_id": g["assembly_id"]}
                     for g in adoc.get("subassemblies") or []]}
