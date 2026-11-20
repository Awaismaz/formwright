"""Fitz, the assembly engineer: plan where Hex's components go, then insert, place and mate them.

Pure Python + numpy in the web process (kernel work goes through ``service`` to the assembly worker, as everywhere
in Assembly Studio). Placement is computed so every mate is satisfied by construction; the solver then confirms it.

Interfaces Fitz understands (all deterministic):
- **mount** a part on another by matching hole patterns: the face where the holes open on each part, a rigid
  in-plane fit of the hole centres (smallest turn wins), then coincident + two concentric mates;
- **fasten**: fastener auto-fit (ASM-013/015) on the target part's holes; a hole lined up with a smaller hole in
  another part is fitted from the smaller one, so the bolt passes both;
- **seat** a bearing or gear on a shaft seat of the same diameter (a convex cylinder of the part): concentric with
  the seat, against its shoulder (coincident) or flush with the free end of the shaft;
- **dowel** pins into holes of the same diameter: concentric, half the pin length in the hole (distance mate);
- **train**: shafts, gears, pulleys and bearings with no block to mount on form shaft lines and a gear train
  (``trains``): the first shaft is the base, gears mesh at the centre distance with their teeth phased, the next
  shaft goes through its gear, two bearings per shaft either side of the hubs;
- otherwise **place** the part beside the assembly and say so.

Every part Fitz could not place, and every other shortfall, is reported as an outcome with a machine-readable code
(``CODES``) besides the plain sentence, so a reviewer (or another agent) can act on it. After inserting, Fitz runs
the exact interference check and reports clashes. Nothing here claims a fit is manufacturable: fits, tolerances and
press forces are not modelled.
"""

from __future__ import annotations

import math
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import numpy as np

from aicad import toolbox
from aicad.assembly import AssemblyInputError, fasteners, librarian, service, store, trains, xform

TOL = 0.02            # mm: hole centres must coincide this closely for a pattern match
ORDER = {"base": 0, "train": 1, "mount": 2, "seat": 3, "dowel": 4, "fasten": 5, "place": 6, "design": 7}

# Outcome codes (machine-readable, stable): what Fitz could not do, or did with a caveat. "warn" outcomes leave a part
# beside the assembly or a joint unfitted; "info" ones are notes (the part is placed).
CODES = {
    "no_interface": "warn: no interface named or found; the part is placed beside the assembly",
    "no_mount_pattern": "warn: no hole pattern of the part lines up with the target's; placed beside",
    "no_shaft_seat": "warn: no free shaft seat of the bearing / gear bore; placed beside",
    "no_free_hole": "warn: no free hole of the dowel diameter; placed beside",
    "no_clearance_holes": "warn: no free clearance holes for the fasteners; nothing inserted",
    "fastener_failed": "warn: the fastener auto-fit refused the joint",
    "hole_skipped": "warn: one hole of a fastener pattern was skipped",
    "part_unavailable": "warn: the part could not be prepared (missing build, bad parameters)",
    "needs_design": "info: not found in the Toolbox or your parts; left for the Design Studio",
    "already_fixed": "info: the target is fixed; parts are mounted onto it instead",
    "clash": "warn: the exact interference check found an overlap between two parts",
    # shaft lines and gear trains (trains.py)
    "no_part_to_mount_shaft": "warn: a shaft with no meshing gear on it has nothing to locate it (no housing); placed beside",
    "module_mismatch": "warn: a gear's module differs from the gear it should mesh with; it and its shaft are beside",
    "no_gear_to_mesh": "warn: a second shaft's gear has no gear to mesh with; placed beside",
    "gear_without_shaft": "info: more gears than shafts; the gear is meshed without a shaft",
    "gear_bore_too_large": "info: the shaft is too thick for the gear's bore; the gear is meshed without a shaft",
    "gear_not_recognised": "info: a part named like a gear has no recognised teeth; it goes on its shaft unmeshed",
    "tooth_phase_unchecked": "info: a gear from your parts has no known tooth phase; check the mesh for a clash",
    "bore_mismatch": "warn: a hub's bore fits no seat of its shaft; placed beside",
    "no_bore": "warn: no bore recognised on the part's axis; placed beside",
    "no_shaft_geometry": "warn: no round seat recognised on a part named like a shaft; placed beside",
    "no_shaft_for_hub": "warn: a pulley / hub has no shaft to go on; placed beside",
    "no_journal_for_bearing": "warn: no journal of the bearing bore on that side of the hubs; placed beside",
    "no_room_for_bearing": "warn: the journal leaves no room for the bearing clear of the hubs; placed beside",
    "bearing_spare": "warn: more bearings than two per shaft; placed beside",
    "bearings_short": "info: a shaft has fewer than two bearings",
    "hub_overhangs_seat": "info: the hubs on a shaft are wider than its seat",
    "train_not_attached": "warn: nothing in the assembly carries the shaft line; it is assembled beside the rest",
    "shafts_not_held": "info: no housing: gear mesh mates keep the centre distances, the shafts can still swing",
    # keys and retaining rings (fixings.py)
    "no_keyseat": "warn: no free keyseat on the line's shafts for the key; placed beside (or not inserted)",
    "key_mismatch": "warn: the key's width or length doesn't fit the keyseat; placed beside",
    "no_groove": "warn: no free retaining-ring groove on the line's shafts; placed beside (or not inserted)",
    "ring_mismatch": "warn: the ring's groove diameter doesn't match the shaft's groove; placed beside",
}


# ----------------------------------------------------------------------------- geometry helpers (pure)
def _canon(v: Any) -> np.ndarray:
    return service._canon(v)


def _name_tokens(name: str) -> set[str]:
    return set(librarian._tok(name.split("<")[0]))


def _occupied_faces(doc: dict[str, Any], iid: str) -> set[int]:
    """Faces of an instance already used by a mate (a hole with a bolt, a seat with a bearing)."""
    out: set[int] = set()
    for m in doc["mates"]:
        for s in (m["a"], m["b"]):
            if s["inst"] == iid and s["kind"] == "face":
                out.add(int(s["id"]))
    return out


def seats(root: Path, key: str) -> list[dict[str, Any]]:
    """Convex full cylinders of a part (shaft seats, pins, bosses) in part-local coordinates, with their axial extent
    and what closes each end: a shoulder (a flat face looking along the seat) or a free end face.

    Hole faces are excluded (every concave full cylinder is a recognised hole). Extents come from the face mesh in
    topo.json; mates use the exact references from refs.json."""
    p = store.part(root, key)
    if p is None:
        return []
    refs = store.refs(root, key)
    topo = store.read_json(store.part_dir(root, key) / "topo.json") or {}
    tfaces = {int(f["id"]): f for f in topo.get("faces", []) if isinstance(f, dict) and "id" in f}
    hole_faces = service._hole_faces(p["info"])
    groups: dict[tuple[float, ...], dict[str, Any]] = {}
    for fid, f in refs["faces"].items():
        if f["kind"] != "axis" or f.get("r") is None or int(fid) in hole_faces:
            continue
        v = _canon(f["v"])
        o = np.asarray(f["p"], dtype=float)
        foot = o - v * float(o @ v)
        k = (*(round(float(x), 4) for x in foot), *(round(float(x), 6) for x in v), round(float(f["r"]), 4))
        g = groups.setdefault(k, {"faces": [], "r": float(f["r"]), "p": foot, "v": v})
        g["faces"].append(int(fid))
    # split each line into separate stretches (two Ø20 journals on one axis are two seats)
    clusters: list[dict[str, Any]] = []
    for g in groups.values():
        spans = []
        for fid in g["faces"]:
            pos = (tfaces.get(fid) or {}).get("pos") or []
            if pos:
                P = np.asarray(pos, dtype=float).reshape(-1, 3)
                t = (P - g["p"]) @ g["v"]
                spans.append((float(t.min()), float(t.max()), fid, P))
        spans.sort(key=lambda x: x[0])
        cur: dict[str, Any] | None = None
        for lo_, hi_, fid, P in spans:
            if cur is not None and lo_ <= cur["hi"] + 1e-3:
                cur["hi"] = max(cur["hi"], hi_)
                cur["faces"].append(fid)
                cur["pts"].append(P)
            else:
                cur = {"r": g["r"], "p": g["p"], "v": g["v"], "hi": hi_, "faces": [fid], "pts": [P]}
                clusters.append(cur)
    out = []
    for g in clusters:
        P = np.vstack(g["pts"])
        v, foot = g["v"], g["p"]
        t = (P - foot) @ v
        radial = (P - foot) - np.outer(t, v)
        e1 = xform.perp(v)
        e2 = np.cross(v, e1)
        ang = np.sort(np.mod(np.arctan2(radial @ e2, radial @ e1), 2 * math.pi))
        gaps = np.diff(np.concatenate([ang, [ang[0] + 2 * math.pi]])) if len(ang) else np.array([2 * math.pi])
        if float(gaps.max()) > math.radians(100):
            continue  # a partial cylinder (fillet, rounded edge), not a seat
        lo, hi = float(t.min()), float(t.max())
        ends: dict[str, dict[str, Any] | None] = {"lo": None, "hi": None}
        near: dict[str, tuple[float, dict[str, Any]] | None] = {"lo": None, "hi": None}
        for fid, f in sorted(refs["faces"].items(), key=lambda kv: int(kv[0])):
            if f["kind"] != "plane":
                continue
            n = xform.unit(f["v"])
            c = float(n @ v)
            if abs(abs(c) - 1) > 1e-9:
                continue
            q = np.asarray(f["p"], dtype=float)
            tq = float((q - foot) @ v)
            off = float(np.linalg.norm((q - foot) - v * tq))
            if off > 1e-3:
                continue
            for end, tt, into in (("lo", lo, 1.0), ("hi", hi, -1.0)):
                if abs(tq - tt) < 1e-3 and ends[end] is None:
                    ends[end] = {"face": int(fid), "shoulder": c * into > 0, "t": tq}
                # a chamfered end or a filleted shoulder: the closing face lies just beyond the cylinder, at most
                # half the radius away (Toolbox shafts have 45° end chamfers)
                gap = (tt - tq) * into
                if 1e-3 <= gap <= 0.5 * g["r"] + 1e-9 and (near[end] is None or gap < near[end][0]):  # type: ignore[index]
                    near[end] = (gap, {"face": int(fid), "shoulder": c * into > 0, "t": tq, "chamfer": gap})
        for end in ("lo", "hi"):
            if ends[end] is None and near[end] is not None:
                ends[end] = near[end][1]  # type: ignore[index]
        out.append({"faces": sorted(g["faces"]), "r": g["r"], "d": round(2 * g["r"], 4), "p": [float(x) for x in foot],
                    "v": [float(x) for x in v], "lo": lo, "hi": hi, "length": hi - lo, "ends": ends})
    out.sort(key=lambda s: (-s["length"], s["d"]))
    return out


def _world_seat(inst: dict[str, Any], s: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    T = xform.from12(inst["T"])
    return xform.pt(T, s["p"]), xform.unit(xform.vec(T, s["v"]))


def bearing_for(d: float) -> int | None:
    """The 62xx (else 60xx) deep-groove bearing whose bore equals a seat diameter."""
    for series in (62, 60):
        for k, (bd, _D, _B) in sorted(toolbox.BEARING.items()):
            if k // 100 == series and abs(bd - d) < 1e-3:
                return k
    return None


# ----------------------------------------------------------------------------- planning (with the assembly)
def _match_instance(doc: dict[str, Any], hint: str | None) -> tuple[str | None, str | None]:
    if not hint:
        return None, None
    words = [w for w in librarian._tok(hint) if w not in librarian.GENERIC]
    if not words:
        return None, None
    names = service.display_names(doc)
    best, best_s = None, 0.0
    for i in doc["instances"]:
        if i.get("group"):
            continue
        toks = _name_tokens(i["name"])
        s = sum(1 for w in words if w in toks) / len(words)
        if s > best_s + 1e-9:
            best, best_s = i["id"], s
    return (best, names[best]) if best and best_s >= 0.5 else (None, None)


def _seat_instances(root: Path, doc: dict[str, Any], d: float | None) -> list[tuple[str, dict[str, Any]]]:
    out = []
    parts = service._parts(root, doc)
    for i in doc["instances"]:
        if i.get("group") or parts[i["part"]]["kind"] == "toolbox" and parts[i["part"]]["code"] != "shaft":
            continue
        for s in seats(root, i["part"]):
            if d is None or abs(s["d"] - d) < 1e-3:
                out.append((i["id"], s))
    return out


def plan(root: Path, doc: dict[str, Any], text: str, candidates: list[dict[str, Any]],
         ai: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Hex resolves each clause; Fitz attaches a target, an action, the mates it intends and the insertion order.
    Returns {items, order, unresolved, tokens: 0}. ``ai``: validated AI readings per clause index (opt-in)."""
    clauses = librarian.parse(text)
    names = service.display_names(doc)
    items: list[dict[str, Any]] = []
    extra: list[dict[str, Any]] = []
    in_doc = {i["source"].get("project_id"): i["id"] for i in doc["instances"]
              if not i.get("group") and i["source"]["kind"] == "project"}
    for k, cl in enumerate(clauses):
        r = librarian.resolve(cl, candidates)
        if ai and k in ai and r["source"] == "new":
            a = dict(ai[k])
            qty = a.pop("qty", None)
            r = {**r, **a, "qty": qty or r["qty"], "ai": True}
        r["id"] = f"h{k + 1}"
        r["enabled"] = r["source"] != "new"
        items.append(r)
    # targets
    for it in items:
        hint = it.get("target_hint")
        tid, tname = _match_instance(doc, hint)
        target: dict[str, Any] | None = {"inst": tid} if tid else None
        if target is None and hint:
            words = [w for w in librarian._tok(hint) if w not in librarian.GENERIC]
            for other in items + extra:
                if other is it or other["source"] != "project" or not words:
                    continue
                if sum(1 for w in words if w in librarian._tok(other["title"])) / len(words) >= 0.5:
                    target, tname = {"item": other["id"]}, other["title"]
                    break
            if target is None and words:
                hits = librarian.find_parts(hint, candidates, limit=1)
                if hits and hits[0]["score"] >= 0.6:
                    h = hits[0]
                    if h["id"] in in_doc:
                        target, tname = {"inst": in_doc[h["id"]]}, names[in_doc[h["id"]]]
                    else:
                        base = {"id": f"h{len(items) + len(extra) + 1}", "text": hint, "qty": 1, "qty_explicit": False,
                                "target_hint": None, "mount": False, "alternatives": [], "enabled": True,
                                **librarian._project(h), "auto": True}
                        base["found"] += f" (named in “{it['text']}”)"
                        extra.append(base)
                        target, tname = {"item": base["id"]}, base["title"]
        it["target"] = target
        it["target_name"] = tname
    items = extra + items
    for it in items:
        if it["source"] == "project" and it["project_id"] in in_doc and it["qty"] == 1:
            it["inst"] = in_doc[it["project_id"]]
            it["found"] += " (already in this assembly)"
    # actions and intended mates
    for it in items:
        _intend(root, doc, it, items, names)
    train_plan(root, doc, items)
    order = sorted(items, key=lambda x: (ORDER[x["action"]], items.index(x)))
    for n, it in enumerate(order, start=1):
        it["order"] = n
    return {"items": order, "unresolved": [it["id"] for it in order if it["source"] == "new"], "tokens": 0,
            "ai_used": bool(ai)}


def _intend(root: Path, doc: dict[str, Any], it: dict[str, Any], items: list[dict[str, Any]],
            names: dict[str, str]) -> None:
    kind, tgt = it.get("kind"), it.get("target")
    tname = it.get("target_name")
    if it["source"] == "new":
        it["action"], it["plan"] = "design", "Design it in the Design Studio, then insert it here"
        return
    if kind == "fastener":
        f = it.get("fasten") or {}
        it["action"] = "fasten"
        where = f"the holes of {tname}" if tname else "lined-up holes (else the base part's holes)"
        size = f"M{f['size']}" if f.get("size") else "the size of each hole"
        it["plan"] = (f"Fastener auto-fit through {where}: {size}, length from the measured grip, "
                      f"{'washers both sides' if f.get('washers') == 'both' else 'no washers' if f.get('washers') == 'none' else 'head washer'}; "
                      "each stack concentric with its hole and seated on the faces")
        if f.get("size") and not f.get("length"):
            c = toolbox.spec(it["code"])
            it["title"] = f"{c.name} {c.standard} M{f['size']} (length to suit)"
            if not it.get("ai"):
                it["found"] = f"Hex found {c.name.lower()}s {c.standard} M{f['size']} in the Toolbox (length to suit the grip)"
        return
    if kind in ("bearing", "gear"):
        it["action"] = "seat"
        d = None
        if it.get("params"):
            d = float(toolbox.BEARING[int(it["params"]["SERIES"])][0]) if kind == "bearing" else float(it["params"]["BORE"])
        found = _seat_instances(root, doc, None)
        if tgt and "inst" in tgt:
            found = [(i, s) for i, s in found if i == tgt["inst"]]
        # a seat closed by a shoulder is where a bearing or gear goes; then the longer seat
        found.sort(key=lambda f: not any((e or {}).get("shoulder") for e in f[1]["ends"].values()))
        if kind == "bearing" and not it.get("params"):
            pick = next(((i, s) for i, s in found if bearing_for(s["d"])), None)
            if pick:
                series = bearing_for(pick[1]["d"])
                it["params"] = toolbox.normalize("bearing", {"SERIES": series})
                it["title"] = toolbox.spec("bearing").title(it["params"])
                it["found"] = f"Hex picked a {series} bearing in the Toolbox (bore Ø{pick[1]['d']:g} = the shaft seat)"
                it["read"] = ["SERIES"]
                it["confidence"] = "high"
                d = pick[1]["d"]
            else:
                it["params"] = toolbox.normalize("bearing", {"SERIES": 6204})
                it["title"] = toolbox.spec("bearing").title(it["params"])
                it["found"] = "Hex found no shaft seat to size the bearing from: 6204 assumed, change it below"
                it["confidence"] = "low"
        if kind == "gear" and found and "BORE" not in (it.get("read") or []):
            s0 = found[0][1]
            try:
                p = toolbox.normalize("spur_gear", {**it["params"], "BORE": s0["d"]})
                it["params"], d = p, s0["d"]
                it["found"] += f" (bore Ø{s0['d']:g} to suit the shaft)"
            except toolbox.ToolboxError:
                pass
        match = [(i, s) for i, s in found if d is not None and abs(s["d"] - d) < 1e-3]
        if match:
            i, s = match[0]
            if not tgt:
                it["target"], it["target_name"] = {"inst": i}, names[i]
            stop = "against the shoulder" if any((e or {}).get("shoulder") for e in s["ends"].values()) else \
                "flush with the shaft end"
            it["plan"] = f"Concentric with the Ø{s['d']:g} seat of {names[i]}, {stop}"
        elif tgt and "item" in tgt:
            it["plan"] = f"On a matching seat of {tname} once it is inserted, else beside the assembly"
        else:
            it["plan"] = (f"No Ø{d:g} shaft seat found" if d else "No shaft seat found") + ": placed beside the assembly"
        return
    if kind == "dowel":
        it["action"] = "dowel"
        D = float(it["params"]["D"]) if it.get("params") else None
        n = len(dowel_targets(root, doc, D, (tgt or {}).get("inst"), set())) if D and doc["instances"] else 0
        if D and n:
            it["plan"] = (f"Into {min(n, it['qty'])} of {n} free Ø{D:g} holes of {tname or 'the assembly parts'}: "
                          "concentric, half the pin length in the hole")
        elif D and tgt and "item" in tgt:
            it["plan"] = f"Into free Ø{D:g} holes of {tname} once it is inserted, else beside the assembly"
        else:
            it["plan"] = f"No free Ø{D:g} hole found: placed beside the assembly, mate it by hand"
        return
    if it.get("target") and (it.get("mount") or kind in ("part", "shaft")):
        it["action"] = "mount"
        it["plan"] = f"Mount on {tname}: line up the hole patterns, seat face to face (coincident + 2 concentric)"
        return
    base = it["source"] == "project" and not doc["instances"] and not any(
        x is not it and x.get("action") == "base" for x in items)
    it["action"] = "base" if base or it.get("auto") else "place"
    if it.get("inst"):
        it["plan"] = "Already in the assembly"
    elif it["action"] == "base":
        it["plan"] = "Fixed at the origin" if not doc["instances"] else "Inserted; parts are mounted on it"
    else:
        it["plan"] = "Placed beside the assembly (no interface named): mate it by hand"


def train_plan(root: Path, doc: dict[str, Any], items: list[dict[str, Any]]) -> bool:
    """Plan-stage view of a shaft line / gear train (``trains``): actions, plan sentences and expected outcome codes
    for the items that form one; Toolbox gears get the shaft's bore and size-less bearings the shaft's journal size.
    Placement itself happens at run time from the real geometry. Returns whether a train was found."""
    tr = trains.select(root, doc, [it for it in items if it.get("action") != "design"])
    if tr is None:
        return False
    names = service.display_names(doc)
    shafts = tr.of("shaft")
    D = None   # the journal diameter: the first Toolbox shaft's, else a shaft already in the assembly
    for u in shafts:
        if u.inst:
            ss = seats(root, service._inst(doc, u.inst)["part"])
            D = ss[0]["d"] if ss else None
        elif u.code == "shaft" and u.params:
            D = float(u.params["D"])
        if D:
            break
    by_id = {it["id"]: it for it in tr.items}
    notes: dict[str, list[str]] = {i: [] for i in by_id}
    codes: dict[str, list[str]] = {i: [] for i in by_id}
    gears, hubs, bearings = tr.of("gear"), tr.of("hub"), tr.of("bearing")
    for it in tr.items:
        role = trains.item_role(it)
        it["action"] = "seat" if role in ("bearing", "hub") else "train"
        it["target"], it["target_name"] = None, None
        if role == "bearing" and D and (not it.get("params") or it.get("confidence") == "low"):
            series = bearing_for(D)
            if series:
                it["params"] = toolbox.normalize("bearing", {"SERIES": series})
                it["title"] = toolbox.spec("bearing").title(it["params"])
                it["found"] = f"Hex picked a {series} bearing in the Toolbox (bore Ø{D:g} = the shaft journals)"
                it["confidence"] = "high"
    for k, u in enumerate(shafts):
        if not u.item:
            continue
        if k == 0:
            notes[u.item].append("Input shaft: the base, fixed at the origin with its axis along +Y" if not doc["instances"]
                                 else "Input shaft: beside the assembly (nothing in it carries the shaft)")
        elif k < len(gears):
            notes[u.item].append(f"shaft {k + 1} parallel to the input shaft, through its gear in mesh")
        else:
            notes[u.item].append(f"shaft {k + 1}: no gear goes on it, so nothing locates it: placed beside")
            codes[u.item].append("no_part_to_mount_shaft")
    prev = None
    for k, u in enumerate(gears):
        if not u.item:
            continue
        it = by_id[u.item]
        prm = u.params or {}
        if u.code == "spur_gear" and k < len(shafts) and D and gear_bore_ok_plan(prm, D):
            it["params"] = toolbox.normalize("spur_gear", {**it["params"], "BORE": D})
            it["title"] = toolbox.spec("spur_gear").title(it["params"])
        where = ("on the input shaft" if k == 0 else f"on shaft {k + 1}") if k < len(shafts) else "without a shaft"
        if prev is None:
            notes[u.item].append(f"{where}{', on the keyway' if shafts and k < len(shafts) else ''}"
                                 + (f", bore Ø{D:g} to suit" if D and k < len(shafts) and u.code == "spur_gear" else ""))
        elif u.code == "spur_gear" and prev.code == "spur_gear" and prev.params and u.params:
            m0, m1 = float(prev.params["M"]), float(prm["M"])
            if abs(m0 - m1) > 1e-9:
                notes[u.item].append(f"module {m1:g} doesn't mesh with module {m0:g} of {prev.title}: placed beside")
                codes[u.item].append("module_mismatch")
            else:
                a = m1 * (int(prev.params["Z"]) + int(prm["Z"])) / 2
                notes[u.item].append(f"in mesh with {prev.title} at {a:g} mm = m(z1+z2)/2, coplanar, teeth phased, "
                                     f"{where}")
        else:
            notes[u.item].append(f"in mesh with {prev.title} (centre distance from the recognised teeth), {where}")
        if k >= len(shafts) and shafts:
            codes[u.item].append("gear_without_shaft")
        prev = u
    for u in hubs:
        if u.item:
            notes[u.item].append("on a shaft without a gear (else the input shaft), centred on its seat"
                                 if shafts else "no shaft to put it on: placed beside")
            if not shafts:
                codes[u.item].append("no_shaft_for_hub")
    for u in tr.of("key"):
        if u.item:
            notes[u.item].append("in the keyseat under its hub: on the keyseat floor, centred, length along the shaft"
                                 if shafts else "no shaft to put it in: placed beside")
    for u in tr.of("ring"):
        if u.item:
            notes[u.item].append("in the shaft's circlip groove, against the groove wall away from the part it holds"
                                 if shafts else "no shaft to put it on: placed beside")
    if bearings and bearings[0].item:
        item = bearings[0].item
        n_sh = len(shafts)
        jd = f"Ø{D:g} " if D else ""
        notes[item].append(f"two per shaft on the {jd}journals, one either side of the "
                           f"{'gear' if gears else 'hubs' if hubs else 'shaft middle'}: against a shoulder, else flush "
                           "with the shaft end")
        if len(bearings) > 2 * n_sh:
            notes[item].append(f"{len(bearings) - 2 * n_sh} more than two per shaft: placed beside")
            codes[item].append("bearing_spare")
        elif len(bearings) < 2 * n_sh:
            notes[item].append(f"{2 * n_sh - len(bearings)} short of two per shaft")
            codes[item].append("bearings_short")
    for i, it in by_id.items():
        if notes[i]:
            s = "; ".join(dict.fromkeys(notes[i]))
            it["plan"] = s[:1].upper() + s[1:]
        it["codes"] = sorted(set(codes[i]))
        it["train"] = True
    del names
    return True


def gear_bore_ok_plan(prm: dict[str, Any], d: float) -> bool:
    try:
        return trains.gear_bore_ok(float(prm["M"]), int(prm["Z"]), d)
    except (KeyError, TypeError, ValueError):
        return False


# ----------------------------------------------------------------------------- execution
ProjectPart = Callable[[str], Awaitable[str]]


def _part_info(root: Path, doc: dict[str, Any], iid: str) -> dict[str, Any]:
    return (store.part(root, service._inst(doc, iid)["part"]) or {}).get("info") or {}


def _plane_face(root: Path, key: str, n_loc: np.ndarray, offset: float) -> int | None:
    for fid, f in sorted(store.refs(root, key)["faces"].items(), key=lambda kv: int(kv[0])):
        if f["kind"] == "plane" and float(xform.unit(f["v"]) @ n_loc) > 1 - 1e-9 \
                and abs(float(np.asarray(f["p"]) @ n_loc) - offset) < 1e-4:
            return int(fid)
    return None


def _end_holes(info: dict[str, Any], n: np.ndarray) -> tuple[float, list[tuple[int, dict[str, Any]]]]:
    """Offset along n of the face where these holes open (outermost end) and the holes that end there."""
    ends = [(k, h, float(np.asarray(h["center"]) @ n) + h["depth"] / 2) for k, h in enumerate(info.get("holes", []))
            if abs(abs(float(xform.unit(h["axis"]) @ n)) - 1) < 1e-6]
    if not ends:
        return 0.0, []
    s = max(e[2] for e in ends)
    return s, [(k, h) for k, h, e in ends if abs(e - s) < 1e-3]


def _axes(info: dict[str, Any]) -> list[np.ndarray]:
    out: list[np.ndarray] = []
    for h in info.get("holes", []):
        u = _canon(h["axis"])
        if not any(abs(float(u @ x)) > 1 - 1e-6 for x in out):
            out.append(u)
    return out


def _compatible(da: float, db: float) -> bool:
    if abs(da - db) < 1e-6:
        return True
    sa, sb = fasteners.size_for_clearance(da), fasteners.size_for_clearance(db)
    return bool(sa and sb and sa["d"] == sb["d"])


def mount_pose(root: Path, doc: dict[str, Any], a_id: str, b_id: str) -> dict[str, Any] | None:
    """Rigid placement of part b on part a with b's hole pattern on a's holes, face to face. Returns
    {T, a_face, b_face, pairs: [(a_hole, b_hole)], matched} or None when no pattern lines up."""
    A, B = service._inst(doc, a_id), service._inst(doc, b_id)
    ia, ib = _part_info(root, doc, a_id), _part_info(root, doc, b_id)
    TA = xform.from12(A["T"])
    RA = TA[:3, :3]
    bx = ib.get("bbox") or [0, 0, 0, 0, 0, 0]
    corners = [np.array([x, y, z]) for x in (bx[0], bx[3]) for y in (bx[1], bx[4]) for z in (bx[2], bx[5])]
    best = None
    for ua in _axes(ia):
        for na_loc in sorted((ua, -ua), key=lambda n: -float((RA @ n)[2])):   # prefer the face looking up
            sa, a_holes = _end_holes(ia, na_loc)
            if len(a_holes) < 2:
                continue
            a_face = _plane_face(root, A["part"], na_loc, sa)
            if a_face is None:
                continue
            nA = RA @ na_loc
            a_pts = [(k, h, xform.pt(TA, h["center"])) for k, h in a_holes]
            for wb in _axes(ib):
                for m in (-wb, wb):
                    sb, b_holes = _end_holes(ib, m)
                    if len(b_holes) < 2 or abs(sb - max(float(c @ m) for c in corners)) > 1e-3:
                        continue
                    b_face = _plane_face(root, B["part"], m, sb)
                    if b_face is None:
                        continue
                    sol = _fit(nA, a_pts, m, b_holes)
                    if sol is None:
                        continue
                    R, j0, i0, theta = sol
                    c0 = np.asarray(b_holes[j0][1]["center"], dtype=float)
                    t = a_pts[i0][2] - R @ c0
                    t = t + nA * ((float(a_pts[i0][2] @ nA) + 0.0) - float((R @ c0 + t) @ nA))
                    # put b's face on a's face: b face points have (R x)·nA = -sb
                    s_world = float(TA[:3, 3] @ nA) + sa
                    t = t + nA * (s_world + sb - float(t @ nA))
                    T = xform.make(R, t)
                    pairs = []
                    for kb, hb in b_holes:
                        pb = xform.pt(T, hb["center"])
                        for ka, ha, pa in a_pts:
                            w = pb - pa
                            if float(np.linalg.norm(w - nA * float(w @ nA))) < TOL and _compatible(ha["d"], hb["d"]):
                                pairs.append((ka, kb))
                                break
                    score = (len(pairs), -abs(theta))
                    if best is None or score > best[0]:
                        best = (score, {"T": T, "a_face": a_face, "b_face": b_face, "pairs": pairs,
                                        "matched": len(pairs), "b_holes": len(b_holes)})
            if best is not None:
                break
        if best is not None:
            break
    return best[1] if best else None


def _fit(nA: np.ndarray, a_pts: list[tuple[int, dict[str, Any], np.ndarray]], m: np.ndarray,
         b_holes: list[tuple[int, dict[str, Any]]]) -> tuple[np.ndarray, int, int, float] | None:
    """Rotation taking b's hole face normal m onto −nA and b's hole centres onto a's (in plane), smallest turn."""
    R0 = xform.min_rot(m, -nA)
    e1 = xform.perp(nA)
    e2 = np.cross(nA, e1)

    def p2(v: np.ndarray) -> np.ndarray:
        return np.array([float(v @ e1), float(v @ e2)])

    qa = [p2(p) for _k, _h, p in a_pts]
    qb = [p2(R0 @ np.asarray(h["center"], dtype=float)) for _k, h in b_holes]
    # the two b holes farthest apart anchor the fit
    j0, j1 = max(((i, j) for i in range(len(qb)) for j in range(i + 1, len(qb))),
                 key=lambda ij: float(np.linalg.norm(qb[ij[1]] - qb[ij[0]])))
    db = qb[j1] - qb[j0]
    best: tuple[float, np.ndarray, int] | None = None
    for i0 in range(len(qa)):
        for i1 in range(len(qa)):
            if i0 == i1:
                continue
            da = qa[i1] - qa[i0]
            if abs(float(np.linalg.norm(da)) - float(np.linalg.norm(db))) > TOL:
                continue
            th = math.atan2(da[1], da[0]) - math.atan2(db[1], db[0])
            th = (th + math.pi) % (2 * math.pi) - math.pi
            if abs(th + math.pi) < 1e-9:
                th = math.pi
            c, s = math.cos(th), math.sin(th)
            R2 = np.array([[c, -s], [s, c]])
            off = qa[i0] - R2 @ qb[j0]
            ok = all(min(float(np.linalg.norm(R2 @ q + off - a)) for a in qa) < TOL for q in qb)
            if ok and (best is None or abs(th) < abs(best[0]) - 1e-9):
                best = (th, R2, i0)
    if best is None:
        return None
    th, _R2, i0 = best
    R = xform.rot(nA, th) @ R0
    return R, j0, i0, th


async def _toolbox_key(root: Path, org_id: str, it: dict[str, Any]) -> str:
    return await service.ensure_toolbox_part(root, org_id, it["code"], it["params"])


def _mate(root: Path, doc: dict[str, Any], t: str, a: tuple[str, int], b: tuple[str, int], value: float = 0.0,
          flip: bool = False) -> dict[str, Any]:
    return service.make_mate(root, doc, {"type": t, "a": {"inst": a[0], "kind": "face", "id": a[1]},
                                         "b": {"inst": b[0], "kind": "face", "id": b[1]}, "value": value, "flip": flip})


def mount(root: Path, doc: dict[str, Any], a_id: str, b_id: str) -> tuple[bool, str]:
    names = service.display_names(doc)
    pose = mount_pose(root, doc, a_id, b_id)
    if pose is None or pose["matched"] < 2:
        return False, (f"Fitz couldn't line up holes of {names[b_id]} with {names[a_id]}: placed beside it, "
                       "mate it by hand")
    inst = service._inst(doc, b_id)
    inst["T"] = xform.to12(pose["T"])
    ia, ib = _part_info(root, doc, a_id), _part_info(root, doc, b_id)
    _mate(root, doc, "coincident", (a_id, pose["a_face"]), (b_id, pose["b_face"]))
    for ka, kb in pose["pairs"][:2]:
        fa, fb = ia["holes"][ka]["faces"], ib["holes"][kb]["faces"]
        if fa and fb:
            _mate(root, doc, "concentric", (a_id, fa[0]), (b_id, fb[0]))
    service.run_solve(root, doc)
    return True, (f"Fitz mounted {names[b_id]} on {names[a_id]}: {pose['matched']} of {pose['b_holes']} holes "
                  "lined up, face to face")


def seat(root: Path, doc: dict[str, Any], shaft_id: str, s: dict[str, Any], key: str, kind: str,
         width: float, bore_r: float, used_ends: set[tuple[str, str]], shoulders_only: bool = False
         ) -> tuple[str | None, str]:
    """Insert one bearing / gear on a shaft seat: against a free shoulder, else (unless ``shoulders_only``) flush
    with a free end. Returns (instance id, status text)."""
    names = service.display_names(doc)
    shaft = service._inst(doc, shaft_id)
    p0, v = _world_seat(shaft, s)
    R_sh = xform.from12(shaft["T"])[:3, :3]
    cands = []
    occ = _occupied_faces(doc, shaft_id)   # an end face already holding a part (an earlier run)
    for end in ("lo", "hi"):
        e = s["ends"][end]
        if e and e["face"] in occ:
            used_ends.add((shaft_id, f"{s['faces'][0]}{end}"))
    for end in ("hi", "lo"):
        e = s["ends"][end]
        if e and e["shoulder"] and (shaft_id, f"{s['faces'][0]}{end}") not in used_ends:
            cands.append((0, end, e))
    for end in ("lo", "hi"):
        e = s["ends"][end]
        if e and not e["shoulder"] and not shoulders_only and (shaft_id, f"{s['faces'][0]}{end}") not in used_ends:
            cands.append((1, end, e))
    if not cands:
        return None, f"Fitz found no free end on the Ø{s['d']:g} seat of {names[shaft_id]}"
    _r, end, e = min(cands, key=lambda c: c[0])
    used_ends.add((shaft_id, f"{s['faces'][0]}{end}"))
    n_loc = xform.unit(store.refs(root, shaft["part"])["faces"][str(e["face"])]["v"])
    n = xform.unit(R_sh @ n_loc)
    end_pt = p0 + v * e["t"]
    if e["shoulder"]:   # coincident: the part's +Z face (z = width) against the shoulder; its +Z points at -n
        R = xform.frame_z(-n)
        origin = end_pt + n * width
        face_part = service._tb_ref(root, key, "plane", z=width, nz=1.0)
        mtype = "coincident"
        how = "against the shoulder"
    else:               # flush: the part's +Z face flush with the free end face (outward normal n)
        R = xform.frame_z(n)
        origin = end_pt - n * width
        face_part = service._tb_ref(root, key, "plane", z=width, nz=1.0)
        mtype = "flush"
        how = "flush with the shaft end"
    inst = service.add_instance(root, doc, key, T=xform.to12(xform.make(R, origin)))
    bore = service._tb_ref(root, key, "axis", r=bore_r)
    if bore is not None:
        _mate(root, doc, "concentric", (shaft_id, s["faces"][0]), (inst["id"], bore["id"]))
    if face_part is not None:
        _mate(root, doc, mtype, (shaft_id, e["face"]), (inst["id"], face_part["id"]))
    names = service.display_names(doc)
    warn = f" (the seat is {s['length']:.4g} mm long, shorter than the {width:g} mm width)" if s["length"] < width - 1e-6 else ""
    return inst["id"], f"Fitz seated {names[inst['id']]} on {names[shaft_id]}, {how}{warn}"


def dowel_targets(root: Path, doc: dict[str, Any], D: float, only: str | None, taken: set[tuple[str, int]]
                  ) -> list[tuple[str, int]]:
    out = []
    for i in doc["instances"]:
        if i.get("group") or (only and i["id"] != only):
            continue
        p = store.part(root, i["part"]) or {}
        if p.get("kind") == "toolbox" and only is None:
            continue
        occ = _occupied_faces(doc, i["id"])
        for k, h in enumerate((p.get("info") or {}).get("holes", [])):
            if abs(h["d"] - D) <= 0.05 and not (set(h.get("faces") or []) & occ) and (i["id"], k) not in taken:
                out.append((i["id"], k))
    return out


def dowel(root: Path, doc: dict[str, Any], iid: str, k: int, key: str, D: float, L: float) -> str | None:
    """Insert one dowel pin into hole k of instance iid; returns the new instance id (None when the hole's entry
    face can't be found)."""
    inst = service._inst(doc, iid)
    T = xform.from12(inst["T"])
    h = _part_info(root, doc, iid)["holes"][k]
    ax = xform.unit(h["axis"])
    c = np.asarray(h["center"], dtype=float)
    if h.get("through"):
        ends = [(c + ax * h["depth"] / 2, ax), (c - ax * h["depth"] / 2, -ax)]
        ends.sort(key=lambda e: -float(xform.vec(T, e[1])[2]))
    else:
        o = np.asarray(h.get("open") or (c + ax * h["depth"] / 2), dtype=float)
        ends = [(o, -xform.unit(h.get("dir") or (-ax).tolist()))]
    entry, n_loc = ends[0]
    face = _plane_face(root, inst["part"], n_loc, float(entry @ n_loc))
    if face is None or not h.get("faces"):
        return None
    e = min(L / 2, float(h["depth"]))
    n = xform.unit(xform.vec(T, n_loc))
    origin = xform.pt(T, entry) - n * e
    new = service.add_instance(root, doc, key, T=xform.to12(xform.make(xform.frame_z(n), origin)))
    cyl = service._tb_ref(root, key, "axis", r=D / 2)
    top = service._tb_ref(root, key, "plane", z=L, nz=1.0)
    if cyl is not None:
        _mate(root, doc, "concentric", (iid, h["faces"][0]), (new["id"], cyl["id"]))
    if top is not None:
        _mate(root, doc, "distance", (iid, face), (new["id"], top["id"]), value=L - e, flip=True)
    return new["id"]


def fasten_targets(root: Path, doc: dict[str, Any], size: int | None, only: str | None, qty: int | None
                   ) -> list[dict[str, Any]]:
    """Holes to fit: the target part's free holes (of the asked size), each switched to the smaller of a lined-up
    pair so the bolt passes both; without a target, lined-up pairs between parts first, then the base part."""
    parts = [i for i in doc["instances"] if not i.get("group")]
    fitted = {(g["hole"]["inst"], int(g["hole"]["hole"])) for g in doc["groups"] if g.get("hole")}
    tb = {i["id"] for i in doc["instances"] if i["source"]["kind"] == "toolbox"}
    plugged = {(s["inst"], int(s["id"])) for m in doc["mates"] for s, o in ((m["a"], m["b"]), (m["b"], m["a"]))
               if o["inst"] in tb and s["inst"] not in tb and s["kind"] == "face"}   # a dowel or bolt is in it

    def free(iid: str, k: int) -> bool:
        h = _part_info(root, doc, iid).get("holes", [])[k]
        return not any((iid, int(f)) in plugged for f in h.get("faces") or [])

    def ok_size(d: float) -> bool:
        s = fasteners.size_for_clearance(d)
        return s is not None and (size is None or s["d"] == size)

    paired: dict[tuple[str, int], tuple[dict[str, Any], float]] = {}
    for x in range(len(parts)):
        for y in range(x + 1, len(parts)):
            a_id, b_id = parts[x]["id"], parts[y]["id"]
            try:
                found = service.coaxial_hole_pairs(root, doc, a_id, b_id)
            except AssemblyInputError:
                continue
            for p in found:   # both holes of a lined-up pair are fitted from the smaller one
                v = (p["target"], min(float(p["a_d"]), float(p["b_d"])))
                paired.setdefault((a_id, int(p["a_hole"])), v)
                paired.setdefault((b_id, int(p["b_hole"])), v)
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    def add(t: dict[str, Any], d: float) -> None:
        key = (t["inst"], int(t["hole"]))
        if key in seen or key in fitted or not ok_size(d) or not free(*key):
            return
        seen.add(key)
        out.append({"inst": t["inst"], "hole": int(t["hole"])})

    if only:
        info = _part_info(root, doc, only)
        for k, h in enumerate(info.get("holes", [])):
            t, d = paired.get((only, k), ({"inst": only, "hole": k}, h["d"]))
            if free(only, k):
                add(t, d)
    else:
        for t, d in sorted({(v[0]["inst"], v[0]["hole"]): v for v in paired.values()}.values(),
                           key=lambda v: (v[0]["inst"], v[0]["hole"])):
            add(t, d)
        if not out:
            base = next((i for i in parts if i["fixed"]), parts[0] if parts else None)
            if base is not None:
                for k, h in enumerate(_part_info(root, doc, base["id"]).get("holes", [])):
                    add({"inst": base["id"], "hole": k}, h["d"])
    return out[:qty] if qty else out


async def execute(root: Path, org_id: str, doc: dict[str, Any], items: list[dict[str, Any]],
                  project_part: ProjectPart, check: bool = True, shafts: list[str] | None = None) -> dict[str, Any]:
    """Insert, place and mate the approved items in order, then run the exact interference check (``check=False``:
    the caller schedules it, e.g. the visual-check policy in ``aicad.assembly.visual``).

    Returns {log, summary, clashes, outcomes: [{code, severity, item, inst, name, text}], timings, stats...}."""
    t_start = time.perf_counter()
    log: list[dict[str, str]] = []
    outcomes: list[dict[str, Any]] = []
    made: dict[str, list[str]] = {}
    used_ends: set[tuple[str, str]] = set()
    taken: set[tuple[str, int]] = set()
    stats = {"inserted": 0, "mated": 0, "placed_loose": 0, "fastener_stacks": 0, "fastener_asked": 0, "base": 0,
             "joints": 0}

    def say(who: str, text: str, tone: str = "ok", code: str | None = None, it: dict[str, Any] | None = None,
            inst: str | None = None) -> None:
        log.append({"agent": who, "text": text, "tone": tone, **({"code": code} if code else {})})
        if code:
            outcomes.append({"code": code, "severity": "warn" if tone == "warn" else "info",
                             "item": it["id"] if it else None, "inst": inst,
                             "name": service.display_names(doc).get(inst) if inst else (it or {}).get("title"),
                             "text": text})

    def target_inst(it: dict[str, Any]) -> str | None:
        t = it.get("target") or {}
        if t.get("inst"):
            service._inst(doc, t["inst"])
            return str(t["inst"])
        if t.get("item") and made.get(t["item"]):
            return made[t["item"]][0]
        return None

    async def key_for(it: dict[str, Any]) -> str:
        if it.get("part_key") and store.part_ready(root, str(it["part_key"])):
            return str(it["part_key"])   # a part already in the assembly, placed again (assembly agent)
        return await _toolbox_key(root, org_id, it) if it["source"] == "toolbox" else await project_part(it["project_id"])

    # shaft lines and gear trains first: they are built by construction around their own base
    t_train = time.perf_counter()
    in_train: set[str] = set()
    tr = trains.select(root, doc, [it for it in items if it.get("enabled", True)], only_shafts=shafts)
    if tr is not None:
        by_id = {it["id"]: it for it in tr.items}
        keys: dict[str, str] = {}
        bad: set[str] = set()
        for u in tr.units:
            unsized = u.role in ("key", "ring") and not u.params   # sized from the keyseat / groove below
            if u.inst or u.item is None or u.role == "gear" and u.code == "spur_gear" or unsized:
                continue
            if u.item not in keys and u.item not in bad:
                try:
                    keys[u.item] = await key_for(by_id[u.item])
                except (AssemblyInputError, toolbox.ToolboxError) as e:
                    bad.add(u.item)
                    say("Hex", f"{by_id[u.item]['title']}: {e}", "warn", "part_unavailable", by_id[u.item])
            u.key = keys.get(u.item)
        tr.units = [u for u in tr.units if u.item not in bad]
        lay = trains.prepare(root, doc, tr)
        trains.size_fixings(lay)   # "a key", "a circlip": the size of the keyseat / groove they go in
        for u in tr.units:
            if u.role in ("key", "ring") and not u.key and u.params and u.code:
                try:
                    u.key = await service.ensure_toolbox_part(root, org_id, u.code, u.params)
                except (AssemblyInputError, toolbox.ToolboxError) as e:
                    say("Hex", f"{u.title}: {e}", "warn", "part_unavailable", by_id.get(u.item or ""))
        for u in tr.units:
            if u.role == "gear" and u.code == "spur_gear" and u.params:
                u.key = await service.ensure_toolbox_part(root, org_id, "spur_gear", u.params)
        out = trains.build(root, doc, tr, lay)
        for ln in out["log"]:
            log.append({"agent": "Fitz", **ln})
        outcomes.extend(out["outcomes"])
        for k, v in out["made"].items():
            made.setdefault(k, []).extend(v)
        stats["inserted"] += sum(len(v) for v in out["made"].values())
        stats["mated"] += out["mated"]
        stats["placed_loose"] += out["loose"]
        stats["base"] += out["base"]
        stats["joints"] += out["joints"]
        in_train = set(by_id)
        service.run_solve(root, doc)
    t_train = time.perf_counter() - t_train

    for it in sorted(items, key=lambda x: x.get("order", 0)):
        if not it.get("enabled", True) or it["id"] in in_train:
            continue
        act = it["action"]
        names = service.display_names(doc)
        if act == "design":
            say("Hex", f"“{it['title']}” is left for the Design Studio", "muted", "needs_design", it)
            continue
        qty = max(1, min(librarian.MAX_QTY, int(it.get("qty") or 1)))
        if act == "fasten":
            f = it.get("fasten") or {}
            only = target_inst(it)
            targets = fasten_targets(root, doc, f.get("size"), only, qty if it.get("qty_explicit") else None)
            stats["fastener_asked"] += qty if it.get("qty_explicit") else len(targets)
            if not targets:
                say("Fitz", f"Fitz found no free {f"M{f['size']} " if f.get('size') else ''}clearance holes"
                            f"{' in ' + names[only] if only else ''} for {it['title']}", "warn", "no_clearance_holes", it)
                continue
            try:
                res = await service.accept(root, org_id, doc, targets, f.get("style") or it["code"],
                                           f.get("washers") or "both", False)
            except AssemblyInputError as e:
                say("Fitz", f"Fitz couldn't fit {it['title']}: {e}", "warn", "fastener_failed", it)
                continue
            n = res["inserted"]
            stats["fastener_stacks"] += n
            stats["mated"] += n
            summ = sorted({h["proposal"]["summary"] for h in res["plan"]["holes"] if h["proposal"]["ok"]})
            say("Fitz", f"Fitz mated {n}/{len(targets)} {'stack' if len(targets) == 1 else 'stacks'}: " + "; ".join(summ))
            want = f.get("length")
            got = {h["proposal"]["length"]["L"] for h in res["plan"]["holes"] if h["proposal"]["ok"]}
            if want and got and got != {want}:
                lmin = max(h["proposal"]["length"]["L_min"] for h in res["plan"]["holes"] if h["proposal"]["ok"])
                say("Fitz", f"You asked for length {want:g}; the measured grip needs L ≥ {lmin:g} mm, so "
                            f"{', '.join(f'{x:g}' for x in sorted(got))} mm was used", "warn")
            for h in res["plan"]["holes"]:
                if not h["proposal"]["ok"]:
                    say("Fitz", f"Hole skipped: {h['proposal'].get('error')}", "warn", "hole_skipped", it)
            continue
        try:
            key = await key_for(it)
        except (AssemblyInputError, toolbox.ToolboxError) as e:
            say("Hex", f"{it['title']}: {e}", "warn", "part_unavailable", it)
            continue
        if act == "seat":
            p = toolbox.normalize(it["code"], it["params"])
            if it["code"] == "bearing":
                d, _D, width = toolbox.BEARING[int(p["SERIES"])]
                bore_r = d / 2
            else:
                width, bore_r, d = float(p["B"]), float(p["BORE"]) / 2, float(p["BORE"])
            only = target_inst(it)
            cand = [(i, s) for i, s in _seat_instances(root, doc, float(d)) if not only or i == only]
            placed = 0
            for _ in range(qty):
                new = None
                for shoulders_only in (True, False):   # every free shoulder first, then free shaft ends
                    for i, s in cand:
                        new, text = seat(root, doc, i, s, key, it["code"], width, bore_r, used_ends, shoulders_only)
                        if new:
                            say("Fitz", text)
                            break
                    if new:
                        break
                if new is None:
                    inst = service.add_instance(root, doc, key)
                    stats["placed_loose"] += 1
                    say("Fitz", f"Fitz found no free Ø{d:g} shaft seat: {service.display_names(doc)[inst['id']]} "
                                "placed beside the assembly", "warn", "no_shaft_seat", it, inst["id"])
                else:
                    placed += 1
                made.setdefault(it["id"], []).append(new or inst["id"])
                stats["inserted"] += 1
            stats["mated"] += placed
            service.run_solve(root, doc)
            continue
        if act == "dowel":
            p = toolbox.normalize("dowel", it["params"])
            only = target_inst(it)
            holes = dowel_targets(root, doc, float(p["D"]), only, taken)
            n_ok = 0
            for _ in range(qty):
                new = None
                while holes and new is None:
                    iid, k = holes.pop(0)
                    taken.add((iid, k))
                    new = dowel(root, doc, iid, k, key, float(p["D"]), float(p["L"]))
                if new is None:
                    inst = service.add_instance(root, doc, key)
                    new = inst["id"]
                    stats["placed_loose"] += 1
                    outcomes.append({"code": "no_free_hole", "severity": "warn", "item": it["id"], "inst": new,
                                     "name": service.display_names(doc)[new],
                                     "text": f"No free Ø{p['D']:g} hole: placed beside the assembly"})
                else:
                    n_ok += 1
                made.setdefault(it["id"], []).append(new)
                stats["inserted"] += 1
            stats["mated"] += n_ok
            service.run_solve(root, doc)
            loose = qty - n_ok
            say("Fitz", f"Fitz mated {n_ok}/{qty} dowel pins Ø{p['D']:g}×{p['L']:g} into matching holes"
                        + (f"; {loose} placed beside the assembly (no free Ø{p['D']:g} hole)" if loose else ""),
                "warn" if loose else "ok")
            continue
        # base / mount / place
        for _ in range(qty if not it.get("inst") else 1):
            if it.get("inst"):
                iid = str(it["inst"])
                service._inst(doc, iid)
            else:
                iid = service.add_instance(root, doc, key)["id"]
                stats["inserted"] += 1
            made.setdefault(it["id"], []).append(iid)
            names = service.display_names(doc)
            tgt = target_inst(it)
            if act == "mount" and tgt and tgt != iid:
                if service._inst(doc, iid)["fixed"]:
                    say("Fitz", f"{names[iid]} is fixed; Fitz mounts parts onto it instead", "muted", "already_fixed",
                        it, iid)
                    continue
                ok, text = mount(root, doc, tgt, iid)
                stats["mated" if ok else "placed_loose"] += 1
                say("Fitz", text, "ok" if ok else "warn", None if ok else "no_mount_pattern", it, iid)
            elif it.get("inst"):
                say("Fitz", f"{names[iid]} is already in the assembly", "muted")
            elif service._inst(doc, iid)["fixed"]:
                stats["base"] += 1
                say("Fitz", f"Fitz fixed {names[iid]} at the origin")
            else:
                stats["placed_loose"] += 1
                say("Fitz", f"Fitz placed {names[iid]} beside the assembly: no interface was named, mate it by hand",
                    "warn", "no_interface", it, iid)
        service.run_solve(root, doc)
    t0 = time.perf_counter()
    service.run_solve(root, doc)
    t_solve = time.perf_counter() - t0
    clashes: list[dict[str, Any]] = []
    checked = False
    t0 = time.perf_counter()
    if doc["instances"] and check:
        an = await service.analyse(root, org_id, doc)
        checked = True
        clashes = [p for p in an["interference"]["pairs"] if p["kind"] == "interference"]
        for c in clashes:
            outcomes.append({"code": "clash", "severity": "warn", "item": None, "inst": c["a"], "name": c.get("a_name"),
                             "other": c["b"], "text": f"{c.get('a_name')} and {c.get('b_name')} overlap by "
                                                      f"{c['volume_mm3']:.3g} mm³"})
    t_check = time.perf_counter() - t0
    bits = []
    if stats["base"]:
        bits.append(f"fixed {stats['base']} base part{'s' if stats['base'] != 1 else ''}")
    if stats["fastener_asked"]:
        bits.append(f"mated {stats['fastener_stacks']}/{stats['fastener_asked']} bolts")
    other = stats["mated"] - stats["fastener_stacks"]
    if other:
        bits.append(f"placed and mated {other} part{'s' if other != 1 else ''}")
    if stats["placed_loose"]:
        bits.append(f"{stats['placed_loose']} left to mate by hand")
    summary = "Fitz " + (", ".join(bits) if bits else "made no changes") + \
        (f", {len(clashes)} clash{'es' if len(clashes) != 1 else ''}" if checked else "")
    say("Fitz", summary, "warn" if clashes or stats["placed_loose"] else "ok")
    timings = {"total_s": round(time.perf_counter() - t_start, 3), "train_s": round(t_train, 3),
               "solve_s": round(t_solve, 3), "interference_s": round(t_check, 3)}
    return {"log": log, "summary": summary, "outcomes": outcomes, "timings": timings,
            "made": made,
            "clashes": [{"a": c["a"], "b": c["b"], "a_name": c.get("a_name"), "b_name": c.get("b_name"),
                         "volume_mm3": c["volume_mm3"]} for c in clashes], **stats}
