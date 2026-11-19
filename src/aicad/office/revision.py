"""Program revision: a new ICD version at any stage of a program (WORKLIST 49 follow-up, PD-100, PD-150..159).

Founder, 2026-11-20 (TEST Project stuck at Assemble Legs): *"Even if assembly needs changing of dependent parts, it must
revise even after those parts are done. It should do whatever needs to be done to solve problem."*

Before this, nothing could change an approved and partly built program beyond the numbers of one interface: a change
request refuses anything that moves other parts or touches integrated ones, and Archie told the engineer to start a new
program. A **revision** changes the plan (parts added or removed, quantities, which part carries which, the base part,
sizes, a part's description) or only lays the program out again with today's layout, and derives the layout and the
ICD again through the normal path (``interfaces._rebuild``: the plan layout today, the design graph's connection
layout once it is merged). Then a deterministic impact analysis compares the old ICD and skeleton with the new ones,
per item and per copy:

* **unchanged**: same geometry and interface features in the part frame, same placement: the build is kept;
* **moved**: same geometry and features, a new placement (or more / fewer copies): the build is kept and re-placed;
* **redesign**: the envelope or an interface feature in the part frame changed (or the engineer changed the part's
  description): the ticket is reopened even when approved or integrated, with a precise instruction (what to remove
  and what to add) and the new ICD excerpt; a part built from the interface spec is built again from it (no AI);
* **added**: a new ticket; **removed**: the ticket is retired (kept under ``retired_tickets`` with its history).

Sub-assembly and final integrations that hold a changed part are reset and run again; untouched sub-assemblies stay
done. Every revision gets an ICD history entry, an entry in ``doc["revisions"]``, a change record on each reopened
part (``ticket["revisions"]``), an event (the audit trail) and, through the callers, an Archie log entry and an audit
row. ``undo`` restores the previous ICD and ticket states while none of the reopened parts has been rebuilt.

Everything here is deterministic and pure except ``apply`` / ``undo`` (they change the document the caller holds under
``store.lock``) and ``rebuild_assembly`` (the program assembly documents).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from aicad.office import OfficeInputError, estimates, icd, planner, roster, service, store

OPS = ("relayout", "mount", "base", "size", "qty", "add", "remove", "describe")
CLASSES = ("unchanged", "moved", "redesign", "added", "removed")
CLASS_LABEL = {"unchanged": "kept as built", "moved": "kept, re-placed", "redesign": "redesigned",
               "added": "added", "removed": "removed"}
GEOMETRY_KEYS = ("role", "shape", "size", "bore", "module", "teeth", "cavity")
PLACEMENT_KEYS = ("copies", "rot", "phase", "ax")
# estimates shown with the impact list (PD-153): a redesign by the design agent is "a change" (~26 tokens measured,
# docs/CONTEXT.md token economics), a new part a warm new part (~45); a part built from the interface spec costs none
REDESIGN_TOKENS = 26
NEW_PART_TOKENS = 45
MAX_OPS = 24
_SUFFIX = re.compile(r"\s*(?:#\d+|\(\d+\s*off\)|<\d+>)\s*$")


# ============================================================================ the requested changes
def _key(name: Any) -> str:
    return _SUFFIX.sub("", " ".join(str(name or "").split())).lower()


def plan_parts(plan: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [(s, p) for s in (plan or {}).get("subassemblies") or [] for p in s.get("parts") or []]


def _find(plan: dict[str, Any], name: Any) -> tuple[dict[str, Any], dict[str, Any]] | None:
    k = _key(name)
    hits = [(s, p) for s, p in plan_parts(plan) if _key(p["name"]) == k]
    return hits[0] if len(hits) == 1 else None


def _envelope(v: Any) -> list[float] | None:
    if isinstance(v, dict):
        v = [v.get("L"), v.get("W"), v.get("H")]
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        return None
    try:
        e = [round(float(x), 2) for x in v]
    except (TypeError, ValueError):
        return None
    return e if all(0.5 <= x <= 5000 for x in e) else None


def clean_ops(doc: dict[str, Any], raw: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """The requested changes, checked against the plan: (ops, reasons for the ones dropped). Parts are named as in
    the plan (``Folding leg``, also ``Folding leg #2``: one design serves every copy)."""
    plan = doc.get("plan") or {}
    ops: list[dict[str, Any]] = []
    bad: list[str] = []
    for o in (raw if isinstance(raw, list) else [raw])[:MAX_OPS]:
        if not isinstance(o, dict):
            continue
        op = str(o.get("op") or o.get("kind") or "").lower().strip()
        if op not in OPS:
            bad.append(f"unknown change {op or '?'}")
            continue
        if op == "relayout":
            ops.append({"op": op})
            continue
        if op == "add":
            part = o.get("part") if isinstance(o.get("part"), dict) else {}
            p1 = planner.normalise_plan({"subassemblies": [{"name": "x", "parts": [part]}]}, "archie")
            if p1 is None:
                bad.append("a part to add needs a name")
                continue
            new = {k: v for k, v in p1["subassemblies"][0]["parts"][0].items() if k != "id"}
            if _find(plan, new["name"]) is not None:
                bad.append(f"{new['name']} is already in the plan")
                continue
            sub = " ".join(str(o.get("sub") or "").split())[:80]
            subs = [s["name"] for s in plan.get("subassemblies") or []]
            ops.append({"op": op, "sub": sub or (subs[0] if subs else "Parts"), "part": new})
            continue
        hit = _find(plan, o.get("part"))
        if hit is None:
            bad.append(f"no part {o.get('part')!s} in the plan")
            continue
        s, p = hit
        out: dict[str, Any] = {"op": op, "part": p["name"]}
        if op == "mount":
            on = o.get("on") or o.get("host") or o.get("mounts_on")
            h = _find(plan, on) if on else None
            if h is None or h[1]["name"] == p["name"]:
                bad.append(f"{p['name']}: say which planned part it mounts on")
                continue
            if p["family"] == "standard" or h[1]["family"] == "standard":
                bad.append(f"{p['name']}: bought-out parts are placed at the joints, not mounted")
                continue
            out["on"] = h[1]["name"]
        elif op == "size":
            env = _envelope(o.get("envelope") or o.get("size"))
            if env is None or p["family"] == "standard":
                bad.append(f"{p['name']}: a size is L, W, H in mm (0.5 to 5000) on a part the program makes")
                continue
            out["envelope"] = env
        elif op == "qty":
            q = o.get("qty")
            if not isinstance(q, int) or isinstance(q, bool) or not 1 <= q <= planner.MAX_QTY:
                bad.append(f"{p['name']}: a quantity is a whole number")
                continue
            if q == int(p.get("qty") or 1):
                bad.append(f"{p['name']}: already {q}")
                continue
            out["qty"] = q
        elif op == "describe":
            txt = " ".join(str(o.get("description") or "").split())[:400]
            if not txt or txt == p.get("description"):
                bad.append(f"{p['name']}: no new description")
                continue
            out["description"] = txt
        elif op == "base" and p["family"] == "standard":
            bad.append(f"{p['name']}: a bought-out part can't be the base")
            continue
        elif op == "remove" and len(plan_parts(plan)) <= 1:
            bad.append("the plan would be empty")
            continue
        _ = s
        ops.append(out)
    return ops, bad


def _next_id(prefix: str, used: list[str]) -> str:
    n = max([int(x[len(prefix):]) for x in used if x.startswith(prefix) and x[len(prefix):].isdigit()] or [0])
    return f"{prefix}{n + 1}"


def revised_plan(doc: dict[str, Any], ops: list[dict[str, Any]]) -> dict[str, Any]:
    """The plan with the changes applied. Item ids stay stable: kept parts keep their sub-assembly and part ids (so
    their tickets, builds and assemblies stay theirs); added parts and sub-assemblies get new ids."""
    plan = copy.deepcopy(doc["plan"])
    pids = [p["id"] for _s, p in plan_parts(plan)]
    sids = [s["id"] for s in plan["subassemblies"]]
    for o in ops:
        op = o["op"]
        if op == "relayout":
            continue
        if op == "add":
            sub = next((s for s in plan["subassemblies"] if _key(s["name"]) == _key(o["sub"])), None)
            if sub is None:
                sid = _next_id("s", sids)
                sids.append(sid)
                sub = {"id": sid, "name": o["sub"], "description": "", "parts": []}
                plan["subassemblies"].append(sub)
            pid = _next_id("p", pids)
            pids.append(pid)
            sub["parts"].append({"id": pid, **copy.deepcopy(o["part"])})
            continue
        hit = _find(plan, o["part"])
        if hit is None:
            continue
        s, p = hit
        if op == "remove":
            s["parts"] = [x for x in s["parts"] if x is not p]
            for _s2, q in plan_parts(plan):  # nothing mounts on a part that is gone
                if _key(q.get("mounts_on")) == _key(p["name"]):
                    q.pop("mounts_on", None)
        elif op == "mount":
            p["mounts_on"] = o["on"]
        elif op == "base":
            p.pop("mounts_on", None)
        elif op == "size":
            p["envelope"] = list(o["envelope"])
        elif op == "qty":
            p["qty"] = int(o["qty"])
        elif op == "describe":
            p["description"] = o["description"]
    plan["subassemblies"] = [s for s in plan["subassemblies"] if s["parts"]]
    if not plan["subassemblies"]:
        raise OfficeInputError("The revised plan would be empty.")
    _sync_graph(plan, ops)
    plan["edited"] = True
    return plan


def _sync_graph(plan: dict[str, Any], ops: list[dict[str, Any]]) -> None:
    """A design-graph plan keeps its graph in step (quantities, removed parts, who carries whom), so the connection
    layout reads the same change once it lays programs out from the graph. Sizes and new parts stay in the plan."""
    g = plan.get("graph") or {}
    data = g.get("data") or {}
    comps = g.get("components") or {}
    if not data or not comps:
        return
    by_name = {_key(v): k for k, v in comps.items()}
    for o in ops:
        cid = by_name.get(_key(o.get("part")))
        if cid is None:
            continue
        if o["op"] == "qty":
            for c in data.get("components") or []:
                if c.get("id") == cid:
                    c["qty"] = int(o["qty"])
        elif o["op"] == "remove":
            data["components"] = [c for c in data.get("components") or [] if c.get("id") != cid]
            data["connections"] = [c for c in data.get("connections") or []
                                   if cid not in (c.get("host"), c.get("guest")) and cid not in (c.get("via") or [])]
            comps.pop(cid, None)
        elif o["op"] == "mount":
            host = by_name.get(_key(o["on"]))
            if host is None:
                continue
            mine = [c for c in data.get("connections") or [] if c.get("guest") == cid]
            if mine:
                for c in mine[:1]:
                    c["host"] = host
            else:
                data.setdefault("connections", []).append({"id": f"c{len(data.get('connections') or []) + 1}",
                                                           "kind": "mounted_on", "host": host, "guest": cid,
                                                           "via": [], "params": {}})


def items_for(plan: dict[str, Any], name: str) -> list[dict[str, Any]]:
    """The program's item tree for a plan (as ``service._build`` makes it), with the plan's own ids."""
    items: list[dict[str, Any]] = [{"id": "root", "parent_id": None, "kind": "program", "name": name}]
    for s in plan["subassemblies"]:
        sid = f"i_{s['id']}"
        items.append({"id": sid, "parent_id": "root", "kind": "subassembly", "name": s["name"],
                      "description": s.get("description", "")})
        for p in s["parts"]:
            items.append({"id": f"i_{s['id']}_{p['id']}", "parent_id": sid, "kind": "part", "name": p["name"],
                          "family": p["family"], "qty": p["qty"], "description": p.get("description", ""),
                          "toolbox": p.get("toolbox")})
    return items


# ============================================================================ deriving the layout again
def _carry_items(doc: dict[str, Any], plan: dict[str, Any], ops: list[dict[str, Any]], keep: set[str]
                 ) -> dict[str, Any]:
    """The item overrides that still apply: frozen sizes and edits of kept parts. A part whose size the revision
    changes, and the base part (laid out to carry its parts), take their size from the plan again."""
    old = ((doc.get("icd") or {}).get("overrides") or {}).get("items") or {}
    resized = {_key(o["part"]) for o in ops if o["op"] in ("size", "base")}
    names = {f"i_{s['id']}_{p['id']}": p["name"] for s, p in plan_parts(plan)}
    out: dict[str, Any] = {}
    for i, v in old.items():
        if i not in keep or i not in names:
            continue
        v = dict(v)
        if _key(names[i]) in resized:
            for k in ("L", "W", "H", "length", "OD", "grown"):
                v.pop(k, None)
        if v:
            out[i] = v
    return out


def _joint(f: dict[str, Any]) -> tuple[Any, ...]:
    return (f["kind"], f["a"]["item"], f["a"].get("copy", 0), f["b"]["item"], f["b"].get("copy", 0))


def derive(doc: dict[str, Any], plan: dict[str, Any], ops: list[dict[str, Any]] | None = None
           ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """(document with the revised plan and items, skeleton, interfaces, overrides) through the normal layout path.
    Interface overrides (accepted change requests, edits, the values frozen at approval) follow their joint (kind and
    the two part copies), not the interface number, since numbers shift when parts come and go."""
    from aicad.graph.compile import overrides_for
    from aicad.office import interfaces

    ops = ops or []
    items = items_for(plan, doc["name"])
    cx = {f"i_{s['id']}_{p['id']}": int(p.get("complexity") or 2) for s, p in plan_parts(plan)}
    d2 = {**doc, "plan": plan, "items": items,
          "tickets": [{"item_id": i, "complexity": c, "kind": "part"} for i, c in cx.items()]}
    keep = {it["id"] for it in items if it["kind"] == "part"}
    old_ov = (doc.get("icd") or {}).get("overrides") or {}
    ov: dict[str, Any] = {"items": {}, "interfaces": {}}
    g0 = overrides_for(plan, icd.parts_from(d2)) or {}
    for i, v in (g0.get("items") or {}).items():
        ov["items"][i] = dict(v)
    for i, v in _carry_items(doc, plan, ops, keep).items():
        ov["items"].setdefault(i, {}).update(v)
    sep = {i: v for i, v in (old_ov.get("separate") or {}).items() if i in keep}
    if sep:
        ov["separate"] = sep
    sk, ifs = interfaces._rebuild(d2, ov)
    old_ifs = {f["id"]: f for f in (doc.get("icd") or {}).get("interfaces") or []}
    by_joint = {_joint(f): f["id"] for f in ifs}
    carried = {}
    for iid, v in (old_ov.get("interfaces") or {}).items():
        f = old_ifs.get(iid)
        nid = by_joint.get(_joint(f)) if f is not None else None
        if nid and f["kind"] == next(x["kind"] for x in ifs if x["id"] == nid):
            carried[nid] = dict(v)
    if carried:
        ov["interfaces"] = carried
        sk, ifs = interfaces._rebuild(d2, ov)
    return d2, sk, ifs, ov


def _with_base(doc: dict[str, Any], plan: dict[str, Any], ops: list[dict[str, Any]], sk: dict[str, Any]
               ) -> dict[str, Any] | None:
    """The base the revision asks for, when the layout chose another: the layout takes the largest block as the base,
    so the base part is given a footprint that covers every other block (and carries its parts in a row)."""
    want = next((o["part"] for o in ops if o["op"] == "base"), None)
    if want is None:
        return None
    hit = _find(plan, want)
    if hit is None:
        return None
    s, p = hit
    item = f"i_{s['id']}_{p['id']}"
    if sk.get("base") == item or item not in sk["items"]:
        return None
    its = sk["items"]
    me = its[item]
    blocks = [v for i, v in its.items() if v.get("role") == "block" and i != item]
    kids = [v for v in its.values() if v.get("parent") == item and v.get("role") == "block"]
    row = sum(float(v["size"][0]) * len(v["copies"]) for v in kids) + icd.GAP * max(0, sum(len(v["copies"]) for v in kids) - 1)
    L = max([float(me["size"][0]), row + 2 * icd.MARGIN] + [float(v["size"][0]) + 1 for v in blocks])
    W = max([float(me["size"][1])] + [float(v["size"][1]) + 2 * icd.MARGIN for v in kids]
            + [float(v["size"][1]) + 1 for v in blocks])
    p2 = copy.deepcopy(plan)
    _s2, q = _find(p2, want)  # type: ignore[misc]
    q["envelope"] = [round(L, 1), round(W, 1), float(me["size"][2])]
    return p2


# ============================================================================ per-copy connectivity
def loose_copies(sk: dict[str, Any], ifs: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """Copies of designed parts that no interface names (each copy is placed by its own joints). Parts the engineer
    kept separate don't count. A program with one designed part has nothing to connect."""
    items = sk.get("items") or {}
    if len(items) < 2:
        return []
    named = {(f[w]["item"], int(f[w].get("copy") or 0)) for f in ifs for w in ("a", "b")}
    sep = set(sk.get("separate") or [])
    return [(i, c) for i, v in items.items() if i not in sep for c in range(len(v.get("copies") or []))
            if (i, c) not in named]


def placement_blocks(sk: dict[str, Any], ifs: list[dict[str, Any]]) -> list[str]:
    """What would leave parts floating in this layout: copies no interface names, and the touch check on the layout
    (``assembly.visual.quick_skeleton``: parts in a row, parts apart). Plain sentences."""
    out = []
    loose = loose_copies(sk, ifs)
    items = sk.get("items") or {}
    for i in dict.fromkeys(i for i, _c in loose):
        cs = [c for j, c in loose if j == i]
        n = len(items[i]["copies"])
        which = f"{items[i]['name']}" if n == 1 else (
            f"{items[i]['name']} #" + ", #".join(str(c + 1) for c in cs))
        out.append(f"{which}: no interface places {'it' if len(cs) == 1 else 'them'}")
    try:
        from aicad.assembly import visual

        q = visual.quick_skeleton(sk, ifs)
        out += [f["text"] for f in q["findings"] if f.get("severity") == "block" and f.get("code") in
                ("row", "floating", "no_interface")]
    except Exception:  # the touch check is a second opinion; the interface check above stands
        import logging

        logging.getLogger("aicad.office.revision").debug("touch check skipped", exc_info=True)
    return list(dict.fromkeys(out))


# ============================================================================ impact analysis
def _canon(x: Any) -> Any:
    if isinstance(x, float):
        return round(x, 3) + 0.0
    if isinstance(x, list | tuple):
        return [_canon(v) for v in x]
    if isinstance(x, dict):
        return {k: _canon(v) for k, v in sorted(x.items()) if k not in ("if", "also", "label")}
    return x


def feature_sig(sk: dict[str, Any], ifs: list[dict[str, Any]], item: str) -> list[str]:
    """An item's interface features in its own part frame, without interface numbers (they shift in a revision)."""
    return sorted(json.dumps(_canon(f), sort_keys=True) for f in icd.item_features(sk, ifs, item))


def _feature_words(sk: dict[str, Any], ifs: list[dict[str, Any]], item: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in icd.item_features(sk, ifs, item):
        k = json.dumps(_canon(f), sort_keys=True)
        lbl = str(f.get("label") or f.get("type") or "feature")
        lbl = re.sub(r"^(hole|tapped hole|dowel hole) \d+", r"\1", lbl)
        c = f.get("c")
        at = f" at ({float(c[0]):g}, {float(c[1]):g})" if isinstance(c, list) and len(c) >= 2 and f.get("type") != "gear" else ""
        if f.get("type") == "face" and f.get("z") is not None:
            at = f" at {'Z' if not f.get('ax') else 'height'} {float(f['z']):g}"
        dia = f" Ø{float(f['d']):g}" if f.get("d") is not None and "Ø" not in lbl else ""
        out[k] = f"{lbl}{dia}{at}"
    return out


def _geom(it: dict[str, Any]) -> dict[str, Any]:
    return _canon({k: it.get(k) for k in GEOMETRY_KEYS})


def _place(it: dict[str, Any]) -> dict[str, Any]:
    return _canon({k: it.get(k) for k in PLACEMENT_KEYS})


def _dims(it: dict[str, Any]) -> str:
    return " × ".join(f"{float(x):g}" for x in it.get("size") or [])


def impact(doc: dict[str, Any], d2: dict[str, Any], sk2: dict[str, Any], ifs2: list[dict[str, Any]],
           ops: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Deterministic classification of every part (and the levels holding them) between the program as it is and the
    revised layout. Hand-checkable: the reasons name what changed."""
    ops = ops or []
    sk1 = doc.get("skeleton") or {"items": {}}
    ifs1 = (doc.get("icd") or {}).get("interfaces") or []
    by_item = {t["item_id"]: t for t in doc.get("tickets") or [] if t["kind"] in ("part", "standard")}
    old_items = {it["id"]: it for it in doc.get("items") or [] if it["kind"] == "part"}
    new_items = {it["id"]: it for it in d2["items"] if it["kind"] == "part"}
    described = {_key(o["part"]) for o in ops if o["op"] == "describe"}
    rows: list[dict[str, Any]] = []
    for i in list(dict.fromkeys(list(old_items) + list(new_items))):
        a, b = old_items.get(i), new_items.get(i)
        it = b or a
        t = by_item.get(i)
        row: dict[str, Any] = {"item": i, "name": it["name"], "family": it.get("family"),
                               "standard": it.get("family") == "standard", "ticket": (t or {}).get("key"),
                               "ticket_id": (t or {}).get("id"), "column": (t or {}).get("column"),
                               "qty_before": int(a["qty"]) if a else 0, "qty_after": int(b["qty"]) if b else 0,
                               "sub_before": a["parent_id"] if a else None, "sub_after": b["parent_id"] if b else None}
        why: list[str] = []
        if a is None:
            cls = "added"
            why.append("new in the plan")
        elif b is None:
            cls = "removed"
            why.append("taken out of the plan")
        elif row["standard"]:
            cls = "unchanged"
            if row["qty_before"] != row["qty_after"]:
                cls = "moved"
                why.append(f"{row['qty_before']} → {row['qty_after']} off")
        else:
            s1, s2 = sk1["items"].get(i), sk2["items"].get(i)
            if s1 is None or s2 is None:
                cls = "redesign" if s2 is not None else "removed"
                why.append("now laid out" if s2 is not None else "no longer in the layout")
            else:
                f1, f2 = feature_sig(sk1, ifs1, i), feature_sig(sk2, ifs2, i)
                g1, g2 = _geom(s1), _geom(s2)
                if g1 != g2 or f1 != f2 or _key(it["name"]) in described:
                    cls = "redesign"
                    if g1.get("size") != g2.get("size"):
                        why.append(f"envelope {_dims(s1)} → {_dims(s2)} mm")
                    for k in ("role", "bore", "module", "teeth"):
                        if g1.get(k) != g2.get(k):
                            why.append(f"{k} {s1.get(k)} → {s2.get(k)}")
                    if f1 != f2:
                        w1, w2 = _feature_words(sk1, ifs1, i), _feature_words(sk2, ifs2, i)
                        gone = [w1[k] for k in f1 if k not in f2 and k in w1]
                        new = [w2[k] for k in f2 if k not in f1 and k in w2]
                        row["remove"], row["add"] = gone, new
                        why.append(f"interface features: {len(gone)} removed, {len(new)} added")
                    if _key(it["name"]) in described:
                        why.append("description changed")
                elif _place(s1) != _place(s2):
                    cls = "moved"
                    n1, n2 = len(s1["copies"]), len(s2["copies"])
                    why.append(f"{n1} → {n2} copies placed" if n1 != n2 else "new placement in the layout")
                else:
                    cls = "unchanged"
            if row["qty_before"] != row["qty_after"] and cls == "unchanged":
                cls = "moved"
                why.append(f"{row['qty_before']} → {row['qty_after']} off")
        row["class"], row["why"] = cls, "; ".join(why) or "same geometry, features and place"
        row["started"] = bool(t and (t["column"] not in ("backlog", "ready") or (t.get("run") or {}).get("status")))
        row["done"] = bool(t and t["column"] in service.DONE_COLUMNS)
        row["direct"] = bool(t and (t.get("direct") or {}).get("path") == "direct"
                             and not (t.get("direct") or {}).get("superseded"))
        rows.append(row)
    changed = {r["item"] for r in rows if r["class"] != "unchanged"}
    subs_old = {it["id"]: it for it in doc.get("items") or [] if it["kind"] == "subassembly"}
    subs_new = {it["id"]: it for it in d2["items"] if it["kind"] == "subassembly"}
    touched = {r["sub_before"] for r in rows if r["item"] in changed} | {r["sub_after"] for r in rows if r["item"] in changed}
    levels = []
    integ = {t["item_id"]: t for t in doc.get("tickets") or [] if t["kind"] == "integration"}
    for sid in list(dict.fromkeys(list(subs_old) + list(subs_new))):
        it = subs_new.get(sid) or subs_old[sid]
        t = integ.get(sid)
        st = "added" if sid not in subs_old else "removed" if sid not in subs_new else \
            "rerun" if sid in touched else "kept"
        levels.append({"item": sid, "name": it["name"], "status": st, "ticket": (t or {}).get("key"),
                       "column": (t or {}).get("column")})
    final = integ.get("root")
    levels.append({"item": "root", "name": "Final assembly", "status": "rerun" if changed else "kept",
                   "ticket": (final or {}).get("key"), "column": (final or {}).get("column")})
    counts = {c: sum(1 for r in rows if r["class"] == c) for c in CLASSES}
    est = _estimate(doc, rows, levels)
    major_why = []
    if counts["added"] or counts["removed"]:
        major_why.append("it adds or removes parts")
    if any(r["class"] == "redesign" for r in rows if r["started"]):
        major_why.append("it reopens parts already worked on")
    elif counts["redesign"]:
        major_why.append("it changes the interfaces of parts")
    return {"parts": rows, "levels": levels, "counts": counts, "estimate": est,
            "replace_only": not (counts["added"] or counts["removed"] or counts["redesign"]),
            "major_why": major_why, "changed": bool(changed)}


def _estimate(doc: dict[str, Any], rows: list[dict[str, Any]], levels: list[dict[str, Any]]) -> dict[str, Any]:
    """Tokens and minutes the revision costs (an estimate, PD-153): redesigns and new parts by family and complexity
    (the program's calibrated rates), integrations run again, a part built from the interface spec at no tokens."""
    rates = service.rates_of(doc)
    by_item = {t["item_id"]: t for t in doc.get("tickets") or []}
    plan_cx = {f"i_{s['id']}_{p['id']}": p for s, p in plan_parts(doc.get("plan") or {})}
    tokens = 0
    work = 0.0
    for r in rows:
        if r["class"] not in ("redesign", "added") or r["standard"]:
            continue
        t = by_item.get(r["item"])
        fam = (t or {}).get("family") or r.get("family") or "machined"
        cx = int((t or {}).get("complexity") or (plan_cx.get(r["item"]) or {}).get("complexity") or 2)
        if r["direct"]:
            work += 0.2
            continue
        tokens += REDESIGN_TOKENS if r["class"] == "redesign" else NEW_PART_TOKENS
        work += estimates.estimate_minutes(fam, cx, rates) * (0.6 if r["class"] == "redesign" else 1.0)
    lv = sum(estimates.estimate_minutes("integration", 1, rates) for x in levels if x["status"] in ("rerun", "added"))
    conc = max(1, int(doc.get("concurrency") or 1))
    return {"tokens": tokens, "minutes": round(work / conc + lv, 1)}


def summary_line(imp: dict[str, Any]) -> str:
    c = imp["counts"]
    bits = [f"{c['unchanged']} kept", f"{c['moved']} re-placed", f"{c['redesign']} redesigned"]
    if c["added"]:
        bits.append(f"{c['added']} added")
    if c["removed"]:
        bits.append(f"{c['removed']} removed")
    rerun = sum(1 for x in imp["levels"] if x["status"] in ("rerun", "added"))
    e = imp["estimate"]
    return (", ".join(bits) + f"; {rerun} assembl{'y' if rerun == 1 else 'ies'} run again; about {e['tokens']} tokens "
            f"and {e['minutes']:g} min")


def impact_lines(imp: dict[str, Any]) -> list[str]:
    """The impact list as the engineer reads it (chat question, Archie log)."""
    out = []
    for cls in ("redesign", "added", "removed", "moved", "unchanged"):
        rows = [r for r in imp["parts"] if r["class"] == cls]
        if not rows:
            continue
        names = "; ".join(f"{r['name']}" + (f" ({r['why']})" if cls in ("redesign", "moved") else "") for r in rows)
        out.append(f"{CLASS_LABEL[cls].capitalize()}: {names}")
    rr = [x["name"] for x in imp["levels"] if x["status"] in ("rerun", "added")]
    kept = [x["name"] for x in imp["levels"] if x["status"] == "kept"]
    if rr:
        out.append("Assemblies run again: " + ", ".join(rr))
    if kept:
        out.append("Assemblies kept: " + ", ".join(kept))
    e = imp["estimate"]
    out.append(f"Estimate: about {e['tokens']} tokens and {e['minutes']:g} min of office time")
    return out


# ============================================================================ a candidate revision
def candidate(doc: dict[str, Any], raw_ops: Any) -> dict[str, Any]:
    """Everything a revision would do, computed and not applied: {ops, dropped, plan, items, skeleton, interfaces,
    overrides, problems, placement (before / after), impact, ok, why}."""
    if not doc.get("plan") or not doc.get("items"):
        raise OfficeInputError("The program has no approved plan to revise yet.")
    if not doc.get("icd") or not doc.get("skeleton"):
        raise OfficeInputError("This program has no interfaces document to revise.")
    ops, dropped = clean_ops(doc, raw_ops)
    if not ops:
        raise OfficeInputError("No change to make" + (f": {dropped[0]}." if dropped else "."))
    plan = revised_plan(doc, ops)
    d2, sk2, ifs2, ov = derive(doc, plan, ops)
    p_base = _with_base(doc, plan, ops, sk2)
    if p_base is not None:
        plan = p_base
        d2, sk2, ifs2, ov = derive(doc, plan, ops)
    before = placement_blocks(doc["skeleton"], doc["icd"]["interfaces"])
    after = placement_blocks(sk2, ifs2)
    probs0 = set(icd.problems(doc["skeleton"], doc["icd"]["interfaces"]))
    probs = icd.problems(sk2, ifs2)
    new_probs = [p for p in probs if p not in probs0]
    imp = impact(doc, d2, sk2, ifs2, ops)
    base_ok = True
    want = next((o["part"] for o in ops if o["op"] == "base"), None)
    if want is not None:
        hit = _find(plan, want)
        base_ok = hit is not None and sk2.get("base") == f"i_{hit[0]['id']}_{hit[1]['id']}"
    why = ""
    if not imp["changed"] and not any(o["op"] in ("qty",) for o in ops):
        why = "The revised layout is the same as the one the program has."
    elif new_probs:
        why = f"The revised layout can't be built: {new_probs[0]}"
    elif after and len(after) >= len(before) and before:
        why = f"The revised layout still leaves parts apart: {after[0]}"
    elif not base_ok:
        why = f"The layout can't take {want} as its base."
    return {"ops": ops, "dropped": dropped, "plan": plan, "items": d2["items"], "skeleton": sk2, "interfaces": ifs2,
            "overrides": ov, "problems": probs, "new_problems": new_probs,
            "placement": {"before": before, "after": after}, "impact": imp, "ok": not why, "why": why,
            "base": sk2.get("base"), "layout": sk2.get("layout")}


def describe_ops(ops: list[dict[str, Any]]) -> list[str]:
    out = []
    for o in ops:
        op = o["op"]
        if op == "relayout":
            out.append("lay the program out again with today's layout")
        elif op == "mount":
            out.append(f"{o['part']} mounts on {o['on']}")
        elif op == "base":
            out.append(f"{o['part']} is the base")
        elif op == "size":
            out.append(f"{o['part']} envelope " + " × ".join(f"{x:g}" for x in o["envelope"]) + " mm")
        elif op == "qty":
            out.append(f"{o['qty']} × {o['part']}")
        elif op == "add":
            out.append(f"add {o['part']['qty']} × {o['part']['name']} to {o['sub']}")
        elif op == "remove":
            out.append(f"remove {o['part']}")
        elif op == "describe":
            out.append(f"{o['part']}: {o['description']}")
    return out


def title(cand: dict[str, Any], doc: dict[str, Any]) -> str:
    v = int((doc.get("icd") or {}).get("version") or 1)
    return (f"Revise the program to ICD v{v + 1} (" + "; ".join(describe_ops(cand["ops"])[:4])
            + ("…" if len(cand["ops"]) > 4 else "") + f"): {summary_line(cand['impact'])}")


def view(cand: dict[str, Any]) -> dict[str, Any]:
    """What the UI shows of a candidate (no layout internals)."""
    imp = cand["impact"]
    return {"ok": cand["ok"], "why": cand["why"], "changes": describe_ops(cand["ops"]), "dropped": cand["dropped"],
            "summary": summary_line(imp), "lines": impact_lines(imp), "counts": imp["counts"],
            "estimate": imp["estimate"], "replace_only": imp["replace_only"], "major_why": imp["major_why"],
            "parts": [{k: r.get(k) for k in ("name", "class", "why", "ticket", "column", "qty_before", "qty_after",
                                             "remove", "add")} for r in imp["parts"]],
            "levels": imp["levels"], "placement": cand["placement"], "problems": cand["new_problems"]}


# ============================================================================ what Archie proposes (no AI)
def _graph_edges(doc: dict[str, Any]) -> list[tuple[str, str]] | None:
    """(host part name, guest part name) between parts the program makes, from the design graph's connections."""
    g = (doc.get("plan") or {}).get("graph") or {}
    comps = g.get("components") or {}
    data = g.get("data") or {}
    if not comps or not data.get("connections"):
        return None
    made = {_key(p["name"]) for _s, p in plan_parts(doc["plan"]) if p["family"] != "standard"}
    out = []
    for c in data["connections"]:
        h, gst = comps.get(c.get("host")), comps.get(c.get("guest"))
        if h and gst and _key(h) in made and _key(gst) in made and _key(h) != _key(gst):
            out.append((h, gst))
    return out or None


def rehost_ops(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The structural repair of a layout that leaves copies floating: one base part with one piece (the part the
    others hang on in the design graph, else the largest one-off block), every other part mounted on the part it
    connects to, the hosts of paired copies sized as they are now (so copy n carries copy n), and a part larger
    than its host stood on its end. Deterministic; Archie asks before anything changes."""
    sk = doc["skeleton"]
    items = sk["items"]
    names = {v["name"]: i for i, v in items.items()}
    edges = _graph_edges(doc)
    if edges is None:  # the interfaces the program has, as an undirected tree
        edges = []
        for f in doc["icd"]["interfaces"]:
            a, b = items.get(f["a"]["item"]), items.get(f["b"]["item"])
            if a and b and a is not b and (a["name"], b["name"]) not in edges and (b["name"], a["name"]) not in edges:
                edges.append((a["name"], b["name"]))
    guests = {g for _h, g in edges}
    nodes = [n for n in names if any(n in e for e in edges)]
    if not nodes:
        return []

    def area(n: str) -> float:
        s = items[names[n]]["size"]
        return float(s[0]) * float(s[1]) if items[names[n]].get("role") == "block" else 0.0

    def qty(n: str) -> int:
        return len(items[names[n]]["copies"])

    roots = [n for n in nodes if n not in guests and qty(n) == 1] or [n for n in nodes if qty(n) == 1]
    if not roots:
        return []
    base = max(roots, key=lambda n: (area(n), -nodes.index(n)))
    parent: dict[str, str] = {}
    seen, todo = {base}, [base]
    while todo:
        h = todo.pop(0)
        nxt = [g for hh, g in edges if hh == h] + [hh for hh, g in edges if g == h]
        for g in nxt:
            if g not in seen and g in names:
                seen.add(g)
                parent[g] = h
                todo.append(g)
    ops: list[dict[str, Any]] = [{"op": "base", "part": base}]
    sized: set[str] = set()
    for g, h in parent.items():
        ops.append({"op": "mount", "part": g, "on": h})
        gs, hs = items[names[g]], items[names[h]]
        if qty(h) > 1 and qty(g) % qty(h) == 0 and h not in sized and hs.get("role") == "block":
            ops.append({"op": "size", "part": h, "envelope": [float(x) for x in hs["size"]]})
            sized.add(h)
        if gs.get("role") == "block" and hs.get("role") == "block":
            L, W, H = (float(x) for x in gs["size"])
            fl, fw = float(hs["size"][0]), float(hs["size"][1])
            if (L > fl or W > fw) and H < max(L, W):  # wider than what carries it: it stands on its end
                d = sorted((L, W, H))
                ops.append({"op": "size", "part": g, "envelope": [d[1], d[0], d[2]]})
                sized.add(g)
    return ops


def propose(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Archie's revision for a layout that leaves parts floating (no AI): first the program laid out again with
    today's layout, then the structural repair; the first candidate that leaves nothing apart. None when the
    program has nothing floating or no candidate clears it."""
    if not doc.get("skeleton") or not doc.get("icd") or not doc.get("items"):
        return None
    if not placement_blocks(doc["skeleton"], doc["icd"]["interfaces"]):
        return None
    for ops in ([{"op": "relayout"}], rehost_ops(doc)):
        if not ops:
            continue
        try:
            c = candidate(doc, ops)
        except OfficeInputError:
            continue
        if c["ok"] and not c["placement"]["after"]:
            return c
    return None


# ============================================================================ applying it
def _snapshot(doc: dict[str, Any]) -> dict[str, Any]:
    keep = ("plan", "items", "tickets", "icd", "skeleton", "status", "gates", "ticket_seq", "retired_tickets", "light")
    snap = {k: copy.deepcopy(doc.get(k)) for k in keep}
    snap["assembly_status"] = (doc.get("assembly") or {}).get("status")
    return snap


def _new_ticket(doc: dict[str, Any], item: dict[str, Any], part: dict[str, Any], sub_name: str, column: str,
                kind: str, title: str, brief: str, depends: list[str]) -> dict[str, Any]:
    doc["ticket_seq"] = int(doc.get("ticket_seq") or len(doc["tickets"])) + 1
    seq = doc["ticket_seq"]
    fam = part.get("family") or "integration"
    cx = int(part.get("complexity") or 1)
    t = {"id": f"t{seq}", "key": f"{doc['key']}-{seq}", "item_id": item["id"], "kind": kind, "title": title,
         "brief": brief, "family": fam, "specialist": roster.specialist_for(fam), "complexity": cx,
         "estimate_min": estimates.estimate_minutes(fam, cx, service.rates_of(doc)), "qty": int(part.get("qty") or 1),
         "column": column, "milestones": [], "progress": 0, "project_id": None, "assembly_id": None,
         "depends_on": depends, "comments": [], "checks": None, "tokens": 0, "run": None,
         "created_at": store.now(), "updated_at": store.now()}
    doc["tickets"].append(t)
    _ = sub_name
    return t


def _instruction(rev_id: str, ver: int, r: dict[str, Any]) -> str:
    lines = [f"Program revision {rev_id} (ICD v{ver}) changes this part: {r['why']}."]
    if r.get("remove"):
        lines.append("Remove these interface features (they no longer meet a mating part):")
        lines += [f"- {x}" for x in r["remove"][:16]]
    if r.get("add"):
        lines.append("Add these interface features, exactly where stated, in the part frame:")
        lines += [f"- {x}" for x in r["add"][:16]]
    lines.append(f"Build the part to the interface excerpt of ICD v{ver} below; keep everything else as it is.")
    return "\n".join(lines)


def busy_tickets(doc: dict[str, Any], imp: dict[str, Any]) -> list[str]:
    """Tickets the revision must change that an agent is working on right now (it waits until they finish)."""
    from aicad.office import orchestrator

    want = {r["ticket_id"] for r in imp["parts"] if r["class"] in ("redesign", "removed") and r.get("ticket_id")}
    want |= {t["id"] for t in doc["tickets"] if t["kind"] in ("integration", "deliverable")}
    return [t["key"] for t in doc["tickets"] if t["id"] in want
            and orchestrator.run_of(t).get("status") in orchestrator.ACTIVE]


def apply(root: Path, doc: dict[str, Any], cand: dict[str, Any], actor: dict[str, Any], *, why: str,
          source: str = "engineer") -> dict[str, Any]:
    """Apply a candidate revision to the program the caller holds under its lock. Returns the revision record."""
    from aicad.office import orchestrator

    imp = cand["impact"]
    busy = busy_tickets(doc, imp)
    if busy:
        raise OfficeInputError(f"{busy[0]} is in the middle of a step: the revision waits until it finishes. Ask "
                               "again in a minute.")
    if doc.get("releases"):
        raise OfficeInputError("The program is released: a change now is a change notice (Deliverables tab), "
                               "which reopens the parts it names and issues the next revision letter.")
    snap = _snapshot(doc)
    ic = doc["icd"]
    v0 = int(ic.get("version") or 1)
    revs = doc.setdefault("revisions", [])
    rid = f"REV-{len(revs) + 1}"
    who = actor.get("name", "Someone")
    archie = service.agent_actor("archie")
    old_sk, old_ifs = doc["skeleton"], ic["interfaces"]
    d = icd.diff(old_sk, old_ifs, cand["skeleton"], cand["interfaces"])
    # the plan, the items, the ICD and the skeleton
    if doc.get("plan"):
        doc.setdefault("plan_history", []).append(doc["plan"])
        doc["plan_history"] = doc["plan_history"][-5:]
    doc["plan"] = cand["plan"]
    doc["items"] = cand["items"]
    approved = ic.get("status") == "approved"
    ic["version"] = v0 + 1
    ic["interfaces"] = cand["interfaces"]
    ic["overrides"] = icd.freeze(cand["skeleton"], cand["interfaces"], cand["overrides"]) if approved \
        else cand["overrides"]
    ic["problems"] = list(cand["problems"]) if not approved else []
    doc["skeleton"] = cand["skeleton"]
    text = (f"{who} revised the program ({rid}): " + "; ".join(describe_ops(cand["ops"])) + f". ICD v{v0} → v{v0 + 1}: "
            + summary_line(imp) + ".")
    ic["history"].append({"version": v0 + 1, "at": store.now(), "by": who, "kind": "revised", "revision": rid,
                          "reason": why, "text": text, "changes": d["changes"][:40]})
    # tickets
    by_item = {t["item_id"]: t for t in doc["tickets"]}
    retired = doc.setdefault("retired_tickets", [])
    reopened: list[dict[str, Any]] = []
    added: list[str] = []
    for r in imp["parts"]:
        t = by_item.get(r["item"])
        if r["class"] == "removed" and t is not None:
            doc["tickets"] = [x for x in doc["tickets"] if x["id"] != t["id"]]
            for x in doc["tickets"]:
                x["depends_on"] = [k for k in x.get("depends_on") or [] if k != t["id"]]
            retired.append({**t, "retired": {"revision": rid, "at": store.now(), "by": who, "why": why}})
            service.emit(root, doc, "ticket.retired", f"{service._label(t)} is retired by {rid}: {t['title']} is no "
                         "longer in the plan (its history is kept).", actor, t["id"], revision=rid)
    items = {it["id"]: it for it in doc["items"]}
    plan_part = {f"i_{s['id']}_{p['id']}": (s, p) for s, p in plan_parts(doc["plan"])}
    for r in imp["parts"]:
        t = by_item.get(r["item"])
        if r["class"] == "added":
            s, p = plan_part[r["item"]]
            kind = "standard" if p["family"] == "standard" else "part"
            nt = _new_ticket(doc, items[r["item"]], p, s["name"], "ready", kind, p["name"],
                             service._ticket_brief(doc["name"], doc["brief"], s["name"], p), [])
            nt["revisions"] = [{"revision": rid, "icd_version": v0 + 1, "class": "added", "at": store.now(),
                                "text": f"Added by {rid}: {why}"}]
            added.append(nt["id"])
            service.emit(root, doc, "ticket.opened", f"{rid} opened {service._label(nt)}.", actor, nt["id"],
                         revision=rid)
            continue
        if t is None or r["class"] == "removed":
            continue
        if r["qty_after"] and r["qty_after"] != int(t.get("qty") or 1):
            s, p = plan_part[r["item"]]
            t["qty"] = r["qty_after"]
            t["brief"] = service._ticket_brief(doc["name"], doc["brief"], s["name"], p)
        if r["class"] == "redesign":
            busy = orchestrator.run_of(t).get("status") in orchestrator.ACTIVE
            msg = _instruction(rid, v0 + 1, r)
            rec = {"revision": rid, "icd_version": v0 + 1, "class": "redesign", "at": store.now(),
                   "column_before": t["column"], "text": msg}
            t.setdefault("revisions", []).append(rec)
            if not busy:
                orchestrator.control(root, doc, t["id"], "reopen", archie)
            c = service.comment(root, doc, t["id"], msg, archie)
            c["delivery"] = "stored"
            t["icd_delta"] = [f"ICD v{v0 + 1} ({rid}): {x}" for x in msg.splitlines()[1:] if x.startswith("- ")] \
                or [f"ICD v{v0 + 1} ({rid}): {r['why']}"]
            t["fitted"] = False
            r0 = orchestrator.run_of(t)
            reopened.append({"ticket": t["id"], "key": t["key"], "turns": int(r0.get("turns") or 0),
                             "direct_at": (t.get("direct") or {}).get("at")})
        elif r["class"] == "moved" and t["kind"] in ("part", "standard"):
            t.setdefault("revisions", []).append({"revision": rid, "icd_version": v0 + 1, "class": "moved",
                                                  "at": store.now(), "text": f"Re-placed by {rid}: {r['why']}"})
    # sub-assemblies: new integrations, retired ones, reset the touched ones
    integ = {t["item_id"]: t for t in doc["tickets"] if t["kind"] == "integration"}
    final = integ.get("root")
    for lv in imp["levels"]:
        sid = lv["item"]
        if sid == "root":
            continue
        kids = [t["id"] for t in doc["tickets"] if t["kind"] in ("part", "standard")
                and items.get(t["item_id"], {}).get("parent_id") == sid]
        if lv["status"] == "added":
            sub = items[sid]
            cx = estimates.integration_complexity(len(kids))
            nt = _new_ticket(doc, sub, {"family": "integration", "complexity": cx}, sub["name"], "backlog",
                             "integration", f"Assemble {sub['name']}", f"Assemble the {sub['name']} of {doc['name']} "
                             "from its parts and check for clashes.", kids)
            nt["specialist"] = "fitz"
            if final is not None:
                final["depends_on"] = list(final.get("depends_on") or []) + [nt["id"]]
            added.append(nt["id"])
        elif lv["status"] == "removed" and sid in integ:
            t = integ[sid]
            doc["tickets"] = [x for x in doc["tickets"] if x["id"] != t["id"]]
            for x in doc["tickets"]:
                x["depends_on"] = [k for k in x.get("depends_on") or [] if k != t["id"]]
            retired.append({**t, "retired": {"revision": rid, "at": store.now(), "by": who, "why": why}})
        elif sid in integ:
            t = integ[sid]
            t["depends_on"] = list(dict.fromkeys(list(t.get("depends_on") or []) + kids))
    reset: list[str] = []
    for lv in imp["levels"]:
        t = integ.get(lv["item"]) if lv["item"] != "root" else final
        if t is None or lv["status"] != "rerun" or t not in doc["tickets"]:
            continue
        r0 = orchestrator.run_of(t)
        if t["column"] in ("backlog", "ready") and not r0.get("status") and not t.get("paused"):
            continue
        orchestrator.close_wait(t)
        orchestrator.control(root, doc, t["id"], "reopen", archie)
        orchestrator._set_run(t, blocked=None, line=f"{rid}: Fitz assembles it again when its parts are ready")
        t.pop("look", None)
        reset.append(t["key"])
        for x in doc["tickets"]:  # kept parts wait for this level again: approved, not integrated
            if x["id"] in (t.get("depends_on") or []) and x["column"] == "integrated" and x["kind"] != "integration":
                x["column"] = "approved"
    for t in doc["tickets"]:
        if t["kind"] == "deliverable" and (t["column"] != "ready" or orchestrator.run_of(t).get("status")):
            orchestrator.control(root, doc, t["id"], "reopen", archie)
            reset.append(t["key"])
    g = service.gate(doc, "release")
    if g.get("status") == "pending":
        g.update(status="locked", note=f"{rid} changed the program: the release waits for the revised parts.")
    if doc.get("status") == "complete":
        doc["status"] = "active"
    o = doc.get("orchestrator") or {}
    if o.get("state") in ("complete",):
        o["state"] = "running"
    if (doc.get("assembly") or {}).get("final"):
        doc["assembly"] = {**doc["assembly"], "status": "building", "revision": rid,
                           "summary": f"Fitz is laying the program assembly out again for {rid}."}
    rev = {"id": rid, "at": store.now(), "by": actor, "source": source, "why": why, "ops": cand["ops"],
           "changes": describe_ops(cand["ops"]), "icd_from": v0, "icd_to": v0 + 1, "summary": summary_line(imp),
           "lines": impact_lines(imp), "impact": view(cand), "reopened": reopened, "added": added, "reset": reset,
           "retired": [r["ticket"] for r in imp["parts"] if r["class"] == "removed" and r.get("ticket")],
           "kept_subs": [lv["item"] for lv in imp["levels"] if lv["status"] == "kept" and lv["item"] != "root"],
           "status": "applied", "snapshot": snap}
    revs.append(rev)
    service.emit(root, doc, "program.revised", text, actor, revision=rid, icd_version=v0 + 1,
                 counts=imp["counts"])
    service._check_complete(root, doc, actor)
    return rev


def latest(doc: dict[str, Any]) -> dict[str, Any] | None:
    return next((r for r in reversed(doc.get("revisions") or []) if r.get("status") == "applied"), None)


def undoable(doc: dict[str, Any], rid: str) -> str | None:
    """None when the revision can be undone now, else why not: only the latest one, and only while none of the
    parts it reopened has been worked on again and none of the parts it added has started."""
    from aicad.office import orchestrator

    rev = next((r for r in doc.get("revisions") or [] if r["id"] == rid), None)
    if rev is None:
        return "no such revision"
    if rev.get("status") != "applied":
        return "it was undone already"
    if latest(doc) is not rev:
        return "a later revision came after it: undo that one first"
    by = {t["id"]: t for t in doc["tickets"]}
    for x in rev.get("reopened") or []:
        t = by.get(x["ticket"])
        if t is None:
            continue
        r = orchestrator.run_of(t)
        if r.get("status") in orchestrator.ACTIVE:
            return f"{t['key']} is being worked on"
        if int(r.get("turns") or 0) != int(x.get("turns") or 0) or (t.get("direct") or {}).get("at") != x.get("direct_at") \
                or t["column"] in ("in_review", "approved", "integrated"):
            return f"{t['key']} has been rebuilt for the revision"
    for tid in rev.get("added") or []:
        t = by.get(tid)
        if t is not None and (t.get("project_id") or orchestrator.run_of(t).get("status") in orchestrator.ACTIVE
                              or t["column"] not in ("backlog", "ready")):
            return f"{t['key']} has started"
    return None


def undo(root: Path, doc: dict[str, Any], rid: str, actor: dict[str, Any]) -> dict[str, Any]:
    """Restore the ICD, the plan and the ticket states from before the revision (the caller holds the lock)."""
    why = undoable(doc, rid)
    if why:
        raise OfficeInputError(f"It can't be undone: {why}.")
    rev = next(r for r in doc["revisions"] if r["id"] == rid)
    snap = rev["snapshot"]
    hist = list(doc["icd"].get("history") or [])
    for k in ("plan", "items", "tickets", "icd", "skeleton", "status", "gates", "ticket_seq", "light"):
        doc[k] = copy.deepcopy(snap.get(k))
    doc["retired_tickets"] = copy.deepcopy(snap.get("retired_tickets")) or []
    who = actor.get("name", "Someone")
    doc["icd"]["history"] = hist + [{"version": doc["icd"]["version"], "at": store.now(), "by": who, "kind": "undone",
                                     "revision": rid, "text": f"{who} undid {rid}: back to ICD v{rev['icd_from']}.",
                                     "changes": []}]
    if (doc.get("assembly") or {}).get("final"):
        doc["assembly"] = {**doc["assembly"], "status": "building", "revision": None,
                           "summary": f"Fitz is laying the program assembly out again after undoing {rid}."}
    rev["status"] = "undone"
    rev["undone"] = {"by": who, "at": store.now()}
    service.emit(root, doc, "program.revision_undone", f"{who} undid {rid}: the plan, ICD v{rev['icd_from']} and the "
                 "tickets are as they were before it.", actor, revision=rid)
    return rev


def public(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The program's revisions for the UI (no snapshots)."""
    out = []
    for r in reversed(doc.get("revisions") or []):
        why = undoable(doc, r["id"]) if r.get("status") == "applied" else None
        out.append({k: v for k, v in r.items() if k not in ("snapshot", "ops")}
                   | {"undoable": why is None and r.get("status") == "applied", "undo_why": why})
    return out


# ============================================================================ the program assembly after a revision
async def rebuild_assembly(root: Path, pid: str, env: Any = None) -> None:
    """Lay the program assembly out again from the revised skeleton: kept parts go in as built at their new places,
    reopened and new parts as placeholders, sub-assemblies the revision didn't touch stay as they are."""
    from aicad.office import orchestrator, platform_env

    doc = store.load(root, pid)
    if doc is None or not (doc.get("assembly") or {}).get("final"):
        return
    o = doc.get("orchestrator") or {}
    rev = latest(doc)
    keep = set((rev or {}).get("kept_subs") or []) if (doc.get("assembly") or {}).get("revision") else set()
    if isinstance(env, platform_env.PlatformEnv):
        user, gp = env.user_id, env.god_paywall
    else:
        user, gp = o.get("user_id") or doc.get("created_by"), bool(o.get("god_paywall"))
    await platform_env.build_program_assembly(root, pid, doc["org_id"], user, gp, keep_subs=keep)
    orchestrator.poke(pid)


_TASKS: set[Any] = set()


def spawn_rebuild(root: Path, pid: str, env: Any = None) -> Any:
    """Run ``rebuild_assembly`` in the background (the engineer's click returns at once; integrations wait for it:
    ``orchestrator.claimable``). Returns the task, or None outside an event loop."""
    import asyncio
    import logging

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None

    async def run() -> None:
        try:
            await rebuild_assembly(root, pid, env)
        except Exception:  # said on the program, never a crash of the click that started it
            logging.getLogger("aicad.office.revision").exception("program assembly rebuild after a revision failed")
            with store.lock(pid):
                d = store.load(root, pid)
                if d is not None and (d.get("assembly") or {}).get("status") == "building":
                    d["assembly"] = {**d["assembly"], "status": "failed", "revision": None,
                                     "summary": "Fitz couldn't lay the program assembly out again: rebuild it from "
                                                "the Assembly tab."}
                    store.save(root, d)
    task = loop.create_task(run())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return task


def context_lines(doc: dict[str, Any]) -> list[str]:
    """What Archie needs to propose a revision (supervisor and chat prompts): the layout per part with its copies,
    what carries it, its size and the plan's hints, and what the per-copy check finds floating."""
    sk = doc.get("skeleton") or {}
    items = sk.get("items") or {}
    if not items:
        return []
    out = [(f"Layout (ICD v{(doc.get('icd') or {}).get('version')}): {sk.get('layout')}, base part "
            f"{items.get(sk.get('base') or '', {}).get('name', 'none')}. Parts (name, copies, envelope mm, carried "
            "by):")]
    hints = {f"i_{s['id']}_{p['id']}": p for s, p in plan_parts(doc.get("plan") or {})}
    for i, v in list(items.items())[:30]:
        h = hints.get(i) or {}
        par = items.get(v.get("parent") or "", {}).get("name") or "nothing (base)"
        extra = "".join(f", plan {k} {h[k]}" for k in ("mounts_on", "envelope") if h.get(k))
        out.append(f"- {v['name']}: {len(v.get('copies') or [])} × {_dims(v)}, on {par}{extra}")
    std = sk.get("standard") or []
    if std:
        out.append("Bought-out parts: " + ", ".join(f"{s.get('qty', 1)} × {s['name']}" for s in std[:20]))
    pb = placement_blocks(sk, (doc.get("icd") or {}).get("interfaces") or [])
    if pb:
        out.append("Per-copy placement check: " + "; ".join(pb[:6]))
    revs = [r for r in doc.get("revisions") or [] if r.get("status") == "applied"]
    if revs:
        out.append("Earlier revisions: " + "; ".join(f"{r['id']} ({'; '.join(r['changes'][:3])})" for r in revs[-3:]))
    return out
