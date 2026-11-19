"""Joints of a program assembly from its ICD (ASM-011 for the Design Office).

Every shaft that runs in bearing seats (``bearing_seat``), in bearings on its own journals (``bearing_journal``, a
shaft line with no housing) or through a bore in a block (``shaft_bore`` whose bore side is a block) turns about its
axis: one revolute joint per shaft copy, carrying the shaft and every item mounted
on it (hubs and gears with a ``shaft_bore`` or ``key`` interface to that shaft copy). Every ``gear_mesh`` couples the
two shafts carrying its gears with ratio −z_a / z_b (external spur mesh). Bearings, housings, caps and fasteners
stay put. Axes come from ``icd.joint_axis`` (program frame), mapped into the assembly through the shaft instance's
own placement, so it does not matter whether a shaft is vertical or lies in side walls.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from aicad.office import icd


def _world_of(sk: dict[str, Any], inst: dict[str, Any]) -> np.ndarray:
    """Assembly frame from program frame for this instance: its placement over the skeleton placement."""
    from aicad.assembly import xform
    from aicad.office import program_assembly

    o = inst.get("office") or {}
    try:
        P = xform.from12(program_assembly.place(sk, o["item"], int(o.get("copy") or 0), o.get("frame")))
        W = xform.from12(inst["T"])
        M = W @ xform.inv(P)
        return M if xform.is_rigid(M, 1e-4) else np.eye(4)
    except Exception:  # noqa: BLE001 - a placement we can't relate: assume the program frame
        return np.eye(4)


def program_joints(prog: dict[str, Any], adoc: dict[str, Any]) -> dict[str, Any]:
    """{"joints": [...], "driver": joint id | None, "notes": [...]} for the final assembly document ``adoc``."""
    from aicad.assembly import xform

    sk = prog.get("skeleton") or {}
    items = sk.get("items") or {}
    ifaces = (prog.get("icd") or {}).get("interfaces") or []
    inst_of: dict[tuple[str, int], str] = {}
    by_id = {i["id"]: i for i in adoc.get("instances") or []}
    for i in adoc.get("instances") or []:
        o = i.get("office") or {}
        if o.get("item") and not o.get("bin") and not o.get("seated") and not i.get("group"):
            inst_of.setdefault((o["item"], int(o.get("copy") or 0)), i["id"])
    notes: list[str] = []
    shafts: dict[tuple[str, int], dict[str, Any]] = {}
    for f in ifaces:
        a, b = f["a"], f["b"]
        if f["kind"] == "bearing_seat" or (f["kind"] == "shaft_bore" and (items.get(a["item"]) or {}).get("role") == "block"
                                            and (items.get(b["item"]) or {}).get("role") == "shaft"):
            key = (b["item"], int(b.get("copy") or 0))
        elif f["kind"] == "bearing_journal":  # the shaft is side a; the bearing (side b) stays put
            key = (a["item"], int(a.get("copy") or 0))
        else:
            continue
        ax = icd.joint_axis(f)
        if ax and key not in shafts:
            side = a if f["kind"] == "bearing_journal" else b
            shafts[key] = {"axis": ax, "via": f["id"], "name": side.get("name") or items.get(key[0], {}).get("name")}
    riders: dict[tuple[str, int], list[tuple[str, int]]] = {k: [] for k in shafts}
    for f in ifaces:
        if f["kind"] not in ("shaft_bore", "key"):
            continue
        key = (f["b"]["item"], int(f["b"].get("copy") or 0))
        if key in riders and (items.get(f["a"]["item"]) or {}).get("role") != "block":
            r = (f["a"]["item"], int(f["a"].get("copy") or 0))
            if r not in riders[key]:
                riders[key].append(r)
    joints: list[dict[str, Any]] = []
    carrier: dict[tuple[str, int], str] = {}
    for key, s in shafts.items():
        iid = inst_of.get(key)
        if iid is None:
            notes.append(f"{s['name']}: not in the assembly, so it can't turn.")
            continue
        M = _world_of(sk, by_id[iid])
        p = [round(float(x), 6) for x in xform.pt(M, s["axis"]["p"])]
        d = [round(float(x), 9) for x in xform.unit(xform.vec(M, s["axis"]["dir"]))]
        insts = [iid] + [inst_of[r] for r in riders[key] if r in inst_of]
        jid = f"j{len(joints) + 1}"
        joints.append({"id": jid, "type": "revolute", "name": f"{s['name']} rotation", "p": p, "dir": d,
                       "insts": insts, "limits": None, "icd": s["via"]})
        carrier[key] = jid
        for r in riders[key]:
            carrier[r] = jid
    driver = None
    for f in ifaces:
        if f["kind"] != "gear_mesh":
            continue
        ja, jb = carrier.get((f["a"]["item"], 0)), carrier.get((f["b"]["item"], 0))
        if not ja or not jb or ja == jb:
            notes.append(f"{f['id']} {f['name']}: a gear is not on a turning shaft, so the mesh is not swept.")
            continue
        za, zb = int(f["data"]["teeth_a"]), int(f["data"]["teeth_b"])
        joints.append({"id": f"j{len(joints) + 1}", "type": "gear", "name": f"{f['name']}", "a": ja, "b": jb,
                       "ratio": round(-za / zb, 9), "teeth": [za, zb], "icd": f["id"]})
        driver = driver or ja
    if driver is None:
        driver = next((j["id"] for j in joints if j["type"] == "revolute"), None)
    return {"joints": joints, "driver": driver, "notes": notes}
