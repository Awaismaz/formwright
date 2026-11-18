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
        if len(fa) > 1 and len(fb) > 1:
            pairs.append(("flush", "end", fa[1], fb[1]))
    elif f["kind"] == "bearing_seat":
        seat = next(x for x in fa if x["type"] == "seat")
        journal = next(x for x in fb if x["type"] == "boss")
        pairs.append(("concentric", "axis", seat, journal))
        ea = next((x for x in fa if x["type"] == "face" and x["n"] < 0 and "flush" in x["label"]), None)
        eb = next((x for x in fb if x["type"] == "face"), None)
        if ea and eb:
            pairs.append(("flush", "end", ea, eb))
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
                keys: dict[str, str] | None = None) -> dict[str, Any]:
    """Create (or rebuild) every program assembly document. ``keys``: item -> part key for items that already have a
    real part (the rest get placeholders). Returns the program's ``assembly`` record."""
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
        fresh = astore.new_doc(f"{prog['name']} · {sub['name']}"[:120], org_id, user_id, None)
        async with locks.hold(aid or fresh["id"], locks.OFFICE):  # the same lock as Assembly Studio's hand edits
            adoc = (astore.load(aroot, aid) if aid else None) or fresh
            adoc.update(instances=[], mates=[], groups=[], subassemblies=[], solve=None,
                        office={"program": prog["id"], "level": sub["id"]})
            base = _sub_base(prog, sub["id"])
            for item, v in sk["items"].items():
                if v["sub"] != sub["id"]:
                    continue
                for c, _at in enumerate(v["copies"]):
                    inst = aservice.add_instance(aroot, adoc, parts[item]["key"], T=place(sk, item, c), name=v["name"])
                    inst["fixed"] = item == base and c == 0
                    inst["office"] = {"program": prog["id"], "item": item, "copy": c}
            if not any(i["fixed"] for i in adoc["instances"]) and adoc["instances"]:
                adoc["instances"][0]["fixed"] = True
            _n, p = relink(aroot, adoc, sk, ifaces, None)
            problems += p
            aservice.run_solve(aroot, adoc)
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
        _n, p = relink(aroot, final, sk, ifaces, None, top_only=True)
        problems += p
        aservice.run_solve(aroot, final)
        an = await aservice.analyse(aroot, org_id, final)
        astore.save(aroot, final)
    clashes = _clashes(an)
    n_mates = len(final["mates"])
    n_ph = sum(1 for v in parts.values() if v["kind"] == "placeholder")
    summary = (f"Fitz assembled {prog['name']} from {n_ph} placeholder{'s' if n_ph != 1 else ''}"
               + (f" and {len(parts) - n_ph} real part{'s' if len(parts) - n_ph != 1 else ''}" if n_ph < len(parts) else "")
               + f": {n_mates} mates by interface name, {len(clashes)} clash{'es' if len(clashes) != 1 else ''}.")
    return {"status": "ready", "final": final["id"], "subs": {k: v["id"] for k, v in sub_docs.items()},
            "parts": parts, "at": astore.now(), "summary": summary, "clashes": clashes, "mates": n_mates,
            "problems": problems[:20], "solve": (final.get("solve") or {}).get("status"),
            "icd_version": prog["icd"]["version"]}


def _clashes(an: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"a": c["a"], "b": c["b"], "a_name": c.get("a_name"), "b_name": c.get("b_name"),
             "volume_mm3": round(float(c["volume_mm3"]), 3)} for c in an["interference"]["pairs"]
            if c["kind"] == "interference"]


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
            _n, p = relink(aroot, adoc, sk, ifaces, items)
            problems += p
            aservice.run_solve(aroot, adoc)
            astore.save(aroot, adoc)
    clashes: list[dict[str, Any]] = state.get("clashes") or []
    async with locks.hold(state["final"], locks.OFFICE):
        final = astore.load(aroot, state["final"])
        if final is not None:
            for g in final.get("subassemblies") or []:
                src = sub_docs.get(next((s for s, a in state["subs"].items() if a == g["assembly_id"]), ""))
                if src is not None:
                    aservice.sync_subassembly(aroot, final, g["id"], src)
            for inst in final["instances"]:
                o = inst.get("office") or {}
                inst["fixed"] = o.get("item") == sk["base"] and o.get("copy") == 0
            _n, p = relink(aroot, final, sk, ifaces, items, top_only=True)
            problems += p
            aservice.run_solve(aroot, final)
            if analyse:
                clashes = _clashes(await aservice.analyse(aroot, org_id, final))
            astore.save(aroot, final)
    parts = dict(state.get("parts") or {})
    for i, key in updates.items():
        parts[i] = {"key": key, "kind": "placeholder" if key.startswith("h_") else "real",
                    "icd_version": prog["icd"]["version"]}
    state["summary"] = summarize(parts, final, clashes)
    state.update(parts=parts, clashes=clashes, at=astore.now(), problems=problems[:20],
                 solve=((final or {}).get("solve") or {}).get("status"), mates=len((final or {}).get("mates") or []))
    names = {i: sk["items"][i]["name"] for i in sk["items"]}
    mine = [c for c in clashes if _item_of(final, c["a"]) in items or _item_of(final, c["b"]) in items]
    state["last"] = {"items": sorted(items), "clashes": mine, "problems": problems,
                     "text": ", ".join(names.get(i, i) for i in sorted(items))}
    return state


def summarize(parts: dict[str, dict[str, Any]], final: dict[str, Any] | None, clashes: list[dict[str, Any]]) -> str:
    """One line for the program page: real parts / placeholders, mates, fastener stacks, clashes."""
    n_ph = sum(1 for v in parts.values() if v["kind"] == "placeholder")
    n_real = len(parts) - n_ph
    mates = len((final or {}).get("mates") or [])
    stacks = sum(1 for g in (final or {}).get("groups") or [] if g.get("kind") == "fastener")
    s = (f"{n_real} real part{'s' if n_real != 1 else ''} and {n_ph} placeholder{'s' if n_ph != 1 else ''}: "
         f"{mates} mates (interfaces mated by name)")
    if stacks:
        s += f", {stacks} fastener stack{'s' if stacks != 1 else ''}"
    return s + f", {len(clashes)} clash{'es' if len(clashes) != 1 else ''}."


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
def _hole_index(info: dict[str, Any], c: list[float], lax: str | None = None) -> int | None:
    """The recognised hole on the axis at ``c`` (canonical frame of part axis ``lax``)."""
    if lax and lax != "z":
        from aicad.office import conformance

        info = conformance.in_canon(lax, info, {})[0]
    for k, h in enumerate(info.get("holes") or []):
        if abs(abs(float(h["axis"][2])) - 1) < 1e-3 and math.hypot(float(h["center"][0]) - c[0],
                                                                    float(h["center"][1]) - c[1]) <= 0.1:
            return k
    return None


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
    stats = {"stacks": 0, "asked": 0, "binned": 0}
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
            for t in standard:
                r = t.get("reuse") or {}
                if r.get("source") != "toolbox":
                    continue
                kind, code = r.get("kind"), r.get("code")
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
                    what = "bearing" if seat["code"] == "bearing" else "dowel pin"
                    seated[what] = seated.get(what, 0) + len(seat["at"])
                    extra = int(t.get("qty") or 1) - len(seat["at"])
                    say(f"Fitz seated {len(seat['at'])} × {seat['title']} in the {seat['what']} of {seat['interface']}"
                        + (f" ({extra} more than the ICD places: left out)" if extra > 0 else ""),
                        "ok" if extra <= 0 else "warn")
                    continue
                if kind == "fastener" or code in ("hex_bolt", "shcs"):
                    mine = [f for f in joints if f["data"].get("fastener_item") in (None, t["item_id"])] or joints
                    targets = []
                    for f in mine:
                        ib = _inst_of(adoc, f["b"]["item"], f["b"]["copy"])
                        if ib is None:
                            continue
                        info = _part_data(aroot, ib["part"], (ib.get("office") or {}).get("frame"))[1]
                        for xy in f["data"]["positions"]:
                            g = icd._axial(sk, f["b"], f["data"], xy, f["data"]["plane_z"])
                            k = _hole_index(info, g["c"], g.get("ax"))
                            if k is not None and (ib["id"], k) not in fitted:
                                targets.append({"inst": ib["id"], "hole": k})
                                fitted.add((ib["id"], k))
                    want = int(t.get("qty") or 1)
                    stats["asked"] += want
                    targets = targets[:want]
                    if not targets:
                        say(f"{t['title']}: no bolted joint inside this sub-assembly; put in the parts bin", "warn")
                    else:
                        try:
                            res = await aservice.accept(aroot, org_id, adoc, targets, "shcs" if code == "shcs" else "hex_bolt",
                                                        "both", False)
                            stats["stacks"] += res["inserted"]
                            summ = sorted({h["proposal"]["summary"] for h in res["plan"]["holes"] if h["proposal"]["ok"]})
                            say(f"Fitz fitted {res['inserted']} of {want} {t['title'].lower()}: " + "; ".join(summ)
                                + (f" ({want - res['inserted']} more than the joints take)" if want > res["inserted"] else ""),
                                "ok" if res["inserted"] >= want else "warn")
                            continue
                        except AssemblyInputError as e:
                            say(f"Fitz couldn't fit {t['title']}: {e}", "warn")
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
            aservice.run_solve(aroot, adoc)
            an = await aservice.analyse(aroot, org_id, adoc)
            astore.save(aroot, adoc)
            clashes = _clashes(an)
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
                    aservice.sync_subassembly(aroot, final, g["id"], src)
            for inst in final["instances"]:
                o = inst.get("office") or {}
                inst["fixed"] = o.get("item") == sk["base"] and o.get("copy") == 0 and not o.get("bin")
            relink(aroot, final, sk, ifaces, None, top_only=True)
            if level == "root":
                # bolted joints between sub-assemblies: Fitz's auto-fit (ISO 4017 + washers + ISO 4032)
                joints = [f for f in ifaces if f["kind"] == "hole_pattern"
                          and sk["items"][f["a"]["item"]]["sub"] != sk["items"][f["b"]["item"]]["sub"]]
                fitted = {(g["hole"]["inst"], int(g["hole"]["hole"])) for g in final["groups"] if g.get("hole")}
                targets = []
                for f in joints:
                    ib = _inst_of(final, f["b"]["item"], f["b"]["copy"])
                    if ib is None:
                        continue
                    info = _part_data(aroot, ib["part"], (ib.get("office") or {}).get("frame"))[1]
                    for xy in f["data"]["positions"]:
                        g = icd._axial(sk, f["b"], f["data"], xy, f["data"]["plane_z"])
                        k = _hole_index(info, g["c"], g.get("ax"))
                        if k is not None and (ib["id"], k) not in fitted:
                            targets.append({"inst": ib["id"], "hole": k})
                if targets:
                    try:
                        res = await aservice.accept(aroot, org_id, final, targets, "hex_bolt", "both", False)
                        stats["stacks"] += res["inserted"]
                        say(f"Fitz fitted {res['inserted']} bolt stacks at the joints between sub-assemblies (ISO auto-fit)")
                    except AssemblyInputError as e:
                        say(f"Fitz couldn't fit the joints between sub-assemblies: {e}", "warn")
            aservice.run_solve(aroot, final)
            an = await aservice.analyse(aroot, org_id, final)
            astore.save(aroot, final)
            if level == "root":
                clashes = _clashes(an)
    bits = []
    if stats["asked"]:
        bits.append(f"fitted {stats['stacks']} fastener stack{'s' if stats['stacks'] != 1 else ''}")
    elif stats["stacks"]:
        bits.append(f"fitted {stats['stacks']} fastener stacks between sub-assemblies")
    for what, n in seated.items():
        bits.append(f"seated {n} {what}{'s' if n != 1 else ''} per the ICD")
    if stats["binned"]:
        bits.append(f"{stats['binned']} part{'s' if stats['binned'] != 1 else ''} in the parts bin")
    name = "the program" if level == "root" else next((x["name"] for x in prog["items"] if x["id"] == level), level)
    summary = f"Fitz integrated {name}" + (": " + ", ".join(bits) if bits else "") + \
        f", {len(clashes)} clash{'es' if len(clashes) != 1 else ''}"
    say(summary, "warn" if clashes else "ok")
    return {"summary": summary, "clashes": clashes, "log": log, "assembly_id": aid_out, "inserted": stats["stacks"],
            "program_summary": summarize(state.get("parts") or {}, final, clashes if level == "root" else
                                         state.get("clashes") or [])}


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
               for c in (analysis.get("interference") or {}).get("pairs") or [] if c.get("kind") == "interference"]
    return {"assembly_id": adoc["id"], "rev": adoc["rev"], "instances": insts, "parts": pview,
            "explode": aservice.explode(aroot, adoc), "clashes": [] if stale else clashes,
            "solve": (adoc.get("solve") or {}).get("status"), "envelope": sk["envelope"],
            "subs": [{"id": g["id"], "name": g["name"], "assembly_id": g["assembly_id"]}
                     for g in adoc.get("subassemblies") or []]}
