"""Motion range check (ASM-011): joints on an assembly and a collision sweep through their range.

Joints (stored on the assembly document as ``doc["joints"]``, program frame / assembly frame, mm and degrees):
  revolute  {"id", "type": "revolute", "name", "p": [x, y, z], "dir": [dx, dy, dz], "insts": [instance ids],
             "limits": [lo, hi] | None}         the instances turn together about the axis through p along dir
  slider    {"id", "type": "slider", "name", "dir", "insts", "limits": [lo, hi] (mm)}   they move along dir
  gear      {"id", "type": "gear", "name", "a": joint id, "b": joint id, "ratio": r, "teeth": [za, zb]}
            couples two revolute joints: angle_b = r * angle_a (an external spur mesh: r = -za / zb)
Everything not carried by a joint is ground (it stays where it is).

Sweep: the driving joint runs from ``start`` to ``end`` in ``steps`` equal steps (both ends included); joints coupled
to it by gear pairs turn by their ratios (chains included). At each step every pair of instances on different
bodies (one at least moving) is checked: instance boxes first (the part's own box turned with it), then solid boxes,
then a bearing's envelope, and the exact OCCT boolean common only on what is left. Pairs that move together are
not re-checked (their relation never changes: that is the ordinary interference check's job). The same relative pose
of a pair is computed once. Overlaps of ``vol_tol`` mm³ or less count as contact.

The planning half (``values``, ``poses``, ``plan``) is pure numpy and runs in the web process; ``sweep`` runs in
the assembly worker (kernel).
"""

from __future__ import annotations

import math
import time
from collections import deque
from typing import Any

import numpy as np

from aicad.assembly import AssemblyInputError, xform

TYPES = ("revolute", "slider", "gear")
DEFAULT_STEPS = 24
MAX_STEPS = 120
MAX_JOINTS = 24
VOL_TOL = 0.5  # mm³: below this an overlap is contact (faceted gear flanks rolling on each other leave slivers)


# ----------------------------------------------------------------------------- validation
def _vec3(v: Any, what: str) -> list[float]:
    try:
        out = [float(x) for x in v]
    except (TypeError, ValueError):
        raise AssemblyInputError(f"{what} needs three numbers.") from None
    if len(out) != 3 or not all(math.isfinite(x) for x in out):
        raise AssemblyInputError(f"{what} needs three numbers.")
    return out


def clean_joint(j: dict[str, Any], inst_ids: set[str], existing: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate one joint (raises AssemblyInputError with a plain sentence)."""
    typ = j.get("type")
    if typ not in TYPES:
        raise AssemblyInputError("A joint is revolute, slider or a gear pair.")
    name = str(j.get("name") or "").strip()[:80]
    out: dict[str, Any] = {"type": typ}
    if typ == "gear":
        by = {x["id"]: x for x in existing}
        a, b = by.get(j.get("a")), by.get(j.get("b"))
        if not a or not b or a["type"] != "revolute" or b["type"] != "revolute" or a["id"] == b["id"]:
            raise AssemblyInputError("A gear pair couples two different revolute joints.")
        teeth = j.get("teeth")
        if teeth:
            za, zb = int(teeth[0]), int(teeth[1])
            if za < 4 or zb < 4:
                raise AssemblyInputError("Gears need at least 4 teeth.")
            ratio = -za / zb
            out["teeth"] = [za, zb]
        else:
            ratio = float(j.get("ratio") or 0)
        if not math.isfinite(ratio) or ratio == 0 or abs(ratio) > 100:
            raise AssemblyInputError("The gear ratio must be a number between -100 and 100, not 0.")
        out.update(a=a["id"], b=b["id"], ratio=round(ratio, 9), name=name or f"{a['name']} → {b['name']}")
        return out
    insts = [str(x) for x in j.get("insts") or []]
    if not insts:
        raise AssemblyInputError("Pick the parts that move with the joint.")
    bad = [x for x in insts if x not in inst_ids]
    if bad:
        raise AssemblyInputError("A part of the joint is not in this assembly.")
    taken = {i for x in existing if x["type"] != "gear" for i in x.get("insts") or []}
    clash = [x for x in insts if x in taken]
    if clash:
        raise AssemblyInputError("A part can move with one joint only; it already moves with another one.")
    d = _vec3(j.get("dir"), "The axis direction")
    if float(np.linalg.norm(d)) < 1e-9:
        raise AssemblyInputError("The axis direction can't be zero.")
    d = [round(float(x), 9) for x in xform.unit(d)]
    out.update(dir=d, insts=sorted(set(insts), key=insts.index), name=name or ("Revolute" if typ == "revolute" else "Slider"))
    if typ == "revolute":
        out["p"] = _vec3(j.get("p"), "The axis point")
    lim = j.get("limits")
    if lim is not None:
        lo, hi = float(lim[0]), float(lim[1])
        if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
            raise AssemblyInputError("Limits need a lower and a higher value.")
        out["limits"] = [lo, hi]
    elif typ == "slider":
        raise AssemblyInputError("A slider needs its travel (from, to) in mm.")
    else:
        out["limits"] = None
    return out


# ----------------------------------------------------------------------------- planning (pure)
def values(joints: list[dict[str, Any]], driver: str, x: float) -> dict[str, float]:
    """Every joint's value when the driver is at ``x``: gear pairs pass the angle on by their ratio (both ways,
    through chains); joints not coupled to the driver stay at 0."""
    out = {driver: float(x)}
    gears = [j for j in joints if j["type"] == "gear"]
    q = deque([driver])
    while q:
        k = q.popleft()
        for g in gears:
            if g["a"] == k and g["b"] not in out:
                out[g["b"]] = out[k] * float(g["ratio"])
                q.append(g["b"])
            elif g["b"] == k and g["a"] not in out:
                out[g["a"]] = out[k] / float(g["ratio"])
                q.append(g["a"])
    for j in joints:
        if j["type"] != "gear":
            out.setdefault(j["id"], 0.0)
    return out


def motion_of(j: dict[str, Any], v: float) -> np.ndarray:
    """4x4 rigid motion of joint ``j`` at value ``v`` (degrees for revolute, mm for slider)."""
    if j["type"] == "revolute":
        return xform.about(xform.rot(j["dir"], math.radians(v)), j["p"])
    return xform.translate(np.asarray(j["dir"], dtype=float) * v)


def poses(instances: dict[str, list[float]], joints: list[dict[str, Any]], vals: dict[str, float]
          ) -> dict[str, list[float]]:
    """{instance id: 12-number placement} for every instance a joint carries."""
    out: dict[str, list[float]] = {}
    for j in joints:
        if j["type"] == "gear":
            continue
        M = motion_of(j, vals.get(j["id"], 0.0))
        for iid in j["insts"]:
            if iid in instances:
                out[iid] = [round(float(x), 9) for x in xform.to12(M @ xform.from12(instances[iid]))]
    return out


def bodies(joints: list[dict[str, Any]]) -> dict[str, str]:
    return {iid: j["id"] for j in joints if j["type"] != "gear" for iid in j["insts"]}


def driver_of(joints: list[dict[str, Any]], driver: str | None) -> dict[str, Any]:
    movers = [j for j in joints if j["type"] != "gear"]
    if not movers:
        raise AssemblyInputError("Add a joint first: a revolute or slider joint with the parts that move.")
    if driver:
        j = next((x for x in movers if x["id"] == driver), None)
        if j is None:
            raise AssemblyInputError("Pick a revolute or slider joint to drive the motion.")
        return j
    return movers[0]


def plan(instances: dict[str, list[float]], joints: list[dict[str, Any]], driver: str | None = None,
         start: float | None = None, end: float | None = None, steps: int = DEFAULT_STEPS) -> dict[str, Any]:
    """The sweep: driver, range and per step the joint values and the placements of the moving instances."""
    dj = driver_of(joints, driver)
    lim = dj.get("limits")
    lo = float(start) if start is not None else (lim[0] if lim else 0.0)
    hi = float(end) if end is not None else (lim[1] if lim else 360.0)
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi == lo:
        raise AssemblyInputError("The range needs two different values.")
    n = max(2, min(int(steps or DEFAULT_STEPS), MAX_STEPS))
    full_turn = dj["type"] == "revolute" and abs(abs(hi - lo) - 360.0) < 1e-9
    count = n if full_turn else n + 1  # a full turn's last step would repeat the first
    xs = [lo + (hi - lo) * k / n for k in range(count)]
    out = []
    for k, x in enumerate(xs):
        vals = values(joints, dj["id"], x)
        out.append({"i": k, "value": round(x, 6), "values": {a: round(b, 6) for a, b in vals.items()},
                    "T": poses(instances, joints, vals)})
    return {"driver": dj["id"], "driver_name": dj.get("name") or "the joint", "unit": "°" if dj["type"] == "revolute" else "mm",
            "start": lo, "end": hi, "steps": out}


# ----------------------------------------------------------------------------- kernel sweep (assembly worker)
def _box(T: np.ndarray, bb: Any) -> tuple[np.ndarray, np.ndarray]:
    x0, y0, z0, x1, y1, z1 = (float(v) for v in bb)
    pts = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)])
    w = pts @ T[:3, :3].T + T[:3, 3]
    return w.min(axis=0), w.max(axis=0)


def sweep(instances: list[dict[str, Any]], body: dict[str, str], steps: list[dict[str, Any]],
          vol_tol: float = VOL_TOL, worst_mesh: bool = True) -> dict[str, Any]:
    """Collisions per step. ``instances``: worker rows {id, step, T, bbox, envelope?, thread?} at the start pose;
    ``body``: instance id -> joint id (absent = ground); ``steps``: [{"i", "T": {id: 12 numbers}}]."""
    from aicad.assembly import geometry as g

    t0 = time.perf_counter()
    n = len(instances)
    ids = [i["id"] for i in instances]
    local = {}
    for k, inst in enumerate(instances):  # local solids and their local boxes, loaded once
        shape = g.load(inst["step"])
        local[k] = [(s, _sbbox(s)) for s in g._solids(shape)]
    moving = {k for k in range(n) if ids[k] in body}
    pairs = [(a, b) for a in range(n) for b in range(a + 1, n)
             if (a in moving or b in moving) and body.get(ids[a]) != body.get(ids[b])]
    memo: dict[tuple[int, int, tuple[float, ...]], tuple[float, list[Any], np.ndarray]] = {}
    stats = {"candidates": 0, "booleans": 0, "memo": 0, "box_skips": 0}
    out_steps = []
    worst: tuple[float, int] | None = None
    keep_commons: dict[int, dict[tuple[int, int], list[Any]]] = {}
    for st in steps:
        Ts = [xform.from12(st["T"].get(ids[k]) or instances[k]["T"]) for k in range(n)]
        boxes = [_box(Ts[k], instances[k]["bbox"]) for k in range(n)]
        hits = []
        commons_here: dict[tuple[int, int], list[Any]] = {}
        for a, b in pairs:
            if g._apart(boxes[a], boxes[b]):
                stats["box_skips"] += 1
                continue
            stats["candidates"] += 1
            rel = xform.inv(Ts[a]) @ Ts[b]
            key = (a, b, tuple(round(float(x), 6) for x in rel[:3, :].ravel()))
            if key in memo:  # the same relative pose: same overlap, its solids moved with a
                stats["memo"] += 1
                vol, commons, Ta_old = memo[key]
                if commons:
                    D = g._loc(Ts[a] @ xform.inv(Ta_old))
                    commons = [c.moved(D) for c in commons]
            else:
                vol, commons = _overlap(g, local, instances, a, b, Ts[a], Ts[b], vol_tol, stats)
                memo[key] = (vol, commons, Ts[a])
            if vol > vol_tol:
                bb = _union_box(commons)
                hits.append({"a": ids[a], "b": ids[b], "volume_mm3": round(vol, 6),
                             "center": [round((bb[0][k] + bb[1][k]) / 2, 3) for k in range(3)] if bb else None})
                commons_here[(a, b)] = commons
        hits.sort(key=lambda h: (-h["volume_mm3"], h["a"], h["b"]))
        total = round(sum(h["volume_mm3"] for h in hits), 6)
        out_steps.append({"i": st["i"], "collisions": hits, "total_mm3": total})
        if hits and (worst is None or total > worst[0]):
            worst = (total, len(out_steps) - 1)
            keep_commons = {len(out_steps) - 1: commons_here}
    if worst is not None and worst_mesh:
        k = worst[1]
        for h in out_steps[k]["collisions"]:
            a, b = ids.index(h["a"]), ids.index(h["b"])
            cs = keep_commons.get(k, {}).get((a, b))
            if cs:
                h["mesh"] = _mesh_of(g, cs)
    return {"steps": out_steps, "worst": None if worst is None else out_steps[worst[1]]["i"],
            "pairs_per_step": len(pairs), "stats": stats, "elapsed_s": round(time.perf_counter() - t0, 3),
            "vol_tol": vol_tol}


def _sbbox(s: Any) -> tuple[np.ndarray, np.ndarray]:
    bb = s.bounding_box()
    return np.array([bb.min.X, bb.min.Y, bb.min.Z]), np.array([bb.max.X, bb.max.Y, bb.max.Z])


def _overlap(g: Any, local: dict[int, list[Any]], instances: list[dict[str, Any]], a: int, b: int, Ta: np.ndarray,
             Tb: np.ndarray, vol_tol: float, stats: dict[str, int]) -> tuple[float, list[Any]]:
    """Exact overlap of instance a at Ta with b at Tb (world), with box and envelope screening."""
    def solids(k: int, T: np.ndarray) -> list[tuple[Any, tuple[np.ndarray, np.ndarray]]]:
        loc = g._loc(T)
        return [(s.moved(loc), _box(T, [*bb[0], *bb[1]])) for s, bb in local[k]]

    sa, sb = solids(a, Ta), solids(b, Tb)
    for k, T, other in ((a, Ta, sb), (b, Tb, sa)):
        if len(local[k]) <= 2:
            continue
        env = g._envelope({**instances[k], "T": xform.to12(T)})
        if env is None:
            continue
        eb = g._sbox(env)
        v = 0.0
        for so, bo in other:
            if g._apart(eb, bo):
                continue
            stats["booleans"] += 1
            c = g._common(env, so)
            if c is not None:
                v += g._volume(c)
        if v <= vol_tol:
            return 0.0, []
    vol, commons = 0.0, []
    for x, bx in sa:
        for y, by in sb:
            if g._apart(bx, by):
                continue
            stats["booleans"] += 1
            c = g._common(x, y)
            if c is None:
                continue
            v = g._volume(c)
            if v > 1e-9:
                vol += v
                commons.append(c)
    return vol, commons


def _union_box(commons: list[Any]) -> tuple[list[float], list[float]] | None:
    if not commons:
        return None
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for c in commons:
        bb = c.bounding_box()
        for k, (mn, mx) in enumerate(((bb.min.X, bb.max.X), (bb.min.Y, bb.max.Y), (bb.min.Z, bb.max.Z))):
            lo[k], hi[k] = min(lo[k], mn), max(hi[k], mx)
    return lo, hi


def _mesh_of(g: Any, commons: list[Any]) -> dict[str, Any]:
    from build123d import Compound

    c = commons[0] if len(commons) == 1 else Compound(children=commons)
    bb = c.bounding_box()
    return g._mesh(c, max(max(bb.size.X, bb.size.Y, bb.size.Z, 1e-3) / 150, 0.01))


# ----------------------------------------------------------------------------- summary (pure)
def summarize(pl: dict[str, Any], res: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    """Join the plan and the sweep: per step the driver value, placements, collisions with names; the worst step."""
    by_i = {s["i"]: s for s in res["steps"]}
    steps = []
    for s in pl["steps"]:
        r = by_i.get(s["i"]) or {"collisions": [], "total_mm3": 0.0}
        cols = [{**c, "a_name": names.get(c["a"], c["a"]), "b_name": names.get(c["b"], c["b"])} for c in r["collisions"]]
        steps.append({"i": s["i"], "value": s["value"], "values": s["values"], "T": s["T"], "collisions": cols,
                      "total_mm3": r["total_mm3"]})
    hit = [s for s in steps if s["collisions"]]
    worst = res.get("worst")
    ws = next((s for s in steps if s["i"] == worst), None)
    u = pl["unit"]
    if not hit:
        text = (f"No collisions through {pl['driver_name']} from {pl['start']:g}{u} to {pl['end']:g}{u} in "
                f"{len(steps)} steps.")
    else:
        pairs = sorted({(c["a_name"], c["b_name"]) for s in hit for c in s["collisions"]})
        text = (f"Collisions in {len(hit)} of {len(steps)} steps; worst at {ws['value']:g}{u} "  # type: ignore[index]
                f"({ws['total_mm3']:.1f} mm³): " + "; ".join(f"{a} ↔ {b}" for a, b in pairs[:4])  # type: ignore[index]
                + (f" and {len(pairs) - 4} more pairs" if len(pairs) > 4 else "") + ".")
    return {"driver": pl["driver"], "driver_name": pl["driver_name"], "unit": u, "start": pl["start"], "end": pl["end"],
            "steps": steps, "worst": worst, "colliding_steps": [s["i"] for s in hit], "summary": text,
            "elapsed_s": res.get("elapsed_s"), "pairs_per_step": res.get("pairs_per_step"), "stats": res.get("stats"),
            "vol_tol": res.get("vol_tol"),
            "note": "Each step checks the exact solids of the parts in that pose for overlap (boxes screen out pairs that can't "
                    "touch). Parts that move together, or stand still together, are not re-checked here: the "
                    "ordinary interference check covers them. Overlaps up to "
                    f"{res.get('vol_tol', VOL_TOL):g} mm³ count as contact. Nominal geometry; no backlash, "
                    "tolerances or deflection."}
