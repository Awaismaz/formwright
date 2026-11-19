"""Pair cache (ASM-023): exact interference and clearance results per pair of part snapshots, on disk per org.

Every pair check depends only on the two part snapshots and where one sits relative to the other, so a result is
stored once under (snapshot a, snapshot b, inv(T_a) T_b rounded to 1e-6, op, tolerance) and reused wherever the
same two parts meet the same way again: a re-check after an unrelated swap, the same parts inside a sub-assembly and
its copy in the final assembly, a retry after a timeout. The worker is asked only for pairs not in the cache, in
chunks whose timeout scales with their size; each chunk's results are stored as soon as it returns, so a timeout
loses at most one chunk of work and a retry carries on from there.

Results are computed in the frame of the pair's first part (``geometry.pair_jobs``) whether they come from the cache
or not, so the cached and uncached paths give the same numbers. The pair is put in a canonical order (the smaller of
the two keys), so (a, b) and (b, a) share an entry.

Layout: ``<org assemblies>/_pairs/<2 hex>/<sha1>.json``. Bounded: past MAX_ENTRIES or MAX_BYTES the least recently
used entries are removed (PD-70). Snapshots are identified by part key + STEP size + mtime, so a re-prepared
snapshot is a miss.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import numpy as np

from aicad.assembly import store, xform

VERSION = 1            # bump when pair_jobs / overlap / min_distance_near change their results
ROUND = 6              # relative transform rounding (mm and rotation-matrix entries)
MAX_ENTRIES = 40_000
MAX_BYTES = 400 * 1024 * 1024
PRUNE_TO = 0.8         # prune down to this share of the caps
CHUNK = 24             # pairs per worker call
BASE_TIMEOUT_S = 60.0
PER_PAIR_S = 20.0      # generous: a 3D-printed shell against a shell measured ~1-6 s
STATS = {"computed": 0, "cached": 0, "calls": 0}  # pair evaluations asked of the worker / served from disk

_writes = 0


def cache_dir(root: Path) -> Path:
    return root / "_pairs"


def part_sig(root: Path, key: str) -> str:
    """A snapshot's identity: key + STEP size + mtime (a re-prepared snapshot is a new identity)."""
    st = (store.part_dir(root, key) / "part.step").stat()
    return f"{key}|{st.st_size}|{st.st_mtime_ns}"


def _r(m: np.ndarray) -> list[float]:
    return [round(float(x), ROUND) + 0.0 for x in m[:3, :].reshape(-1)]


def canon(sig_a: str, Ta: np.ndarray, sig_b: str, Tb: np.ndarray) -> tuple[bool, np.ndarray, str]:
    """(swapped, exact relative transform first -> second, key) for a pair in canonical order."""
    rab, rba = xform.inv(Ta) @ Tb, xform.inv(Tb) @ Ta
    ka, kb = [sig_a, sig_b, _r(rab)], [sig_b, sig_a, _r(rba)]
    swapped = json.dumps(kb) < json.dumps(ka)
    return swapped, (rba if swapped else rab), json.dumps(kb if swapped else ka)


def _path(root: Path, op: str, key: str) -> Path:
    h = hashlib.sha1(f"v{VERSION}|{op}|{key}".encode()).hexdigest()
    return cache_dir(root) / h[:2] / f"{h}.json"


def get(root: Path, op: str, key: str) -> dict[str, Any] | None:
    p = _path(root, op, key)
    v = store.read_json(p)
    if isinstance(v, dict) and v.get("key") == key and v.get("op") == op:
        try:
            os.utime(p)  # least recently used goes first when pruning
        except OSError:
            pass
        return v["result"]
    return None


def put(root: Path, op: str, key: str, result: dict[str, Any]) -> None:
    global _writes
    p = _path(root, op, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"op": op, "key": key, "result": result}, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, p)
    _writes += 1
    if _writes % 500 == 0:
        prune(root)


def prune(root: Path, max_entries: int = MAX_ENTRIES, max_bytes: int = MAX_BYTES) -> int:
    """Remove the least recently used entries once over either cap. Returns how many were removed."""
    files = []
    d = cache_dir(root)
    if not d.is_dir():
        return 0
    for sub in d.iterdir():
        if sub.is_dir():
            for f in sub.glob("*.json"):
                try:
                    st = f.stat()
                except OSError:
                    continue
                files.append((st.st_mtime_ns, st.st_size, f))
    total = sum(s for _, s, _ in files)
    if len(files) <= max_entries and total <= max_bytes:
        return 0
    files.sort(key=lambda x: x[0])
    keep_n, keep_b = int(max_entries * PRUNE_TO), int(max_bytes * PRUNE_TO)
    n, removed = len(files), 0
    for _m, size, f in files:
        if n <= keep_n and total <= keep_b:
            break
        try:
            f.unlink()
        except OSError:
            continue
        n, total, removed = n - 1, total - size, removed + 1
    return removed


# ----------------------------------------------------------------------------- mapping results to the world
def _world_int(r: dict[str, Any], P: np.ndarray) -> dict[str, Any]:
    c = xform.pt(P, r["center"])
    x0, y0, z0, x1, y1, z1 = r["bbox"]
    pts = np.array([xform.pt(P, (x, y, z)) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)])
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    mesh = None
    if r.get("mesh"):
        pos = np.asarray(r["mesh"]["pos"], dtype=float).reshape(-1, 3) @ P[:3, :3].T + P[:3, 3]
        mesh = {"pos": [round(float(v), 4) for v in pos.reshape(-1)], "idx": r["mesh"]["idx"]}
    return {"volume_mm3": r["volume_mm3"], "kind": r["kind"], "center": [round(float(v), 4) for v in c],
            "bbox": [round(float(v), 4) for v in (*lo, *hi)], "mesh": mesh}


def _world_clr(r: dict[str, Any], P: np.ndarray, swapped: bool) -> tuple[float, list[float], list[float]]:
    p1 = [float(v) for v in xform.pt(P, r["p1"])]
    p2 = [float(v) for v in xform.pt(P, r["p2"])]
    return float(r["d"]), (p2 if swapped else p1), (p1 if swapped else p2)


# ----------------------------------------------------------------------------- the check
Call = Callable[[dict[str, Any], float], Awaitable[Any]]


def _job_side(inst: dict[str, Any]) -> dict[str, Any]:
    return {k: inst[k] for k in ("step", "bbox", "thread", "envelope") if inst.get(k) is not None}


async def run(root: Path, call: Call, insts: list[dict[str, Any]], want_int: list[tuple[int, int]],
              want_clr: list[tuple[int, int]], vol_tol: float = 1e-6, use_cache: bool = True,
              progress: Callable[[int, int], None] | None = None
              ) -> tuple[dict[tuple[int, int], dict[str, Any]], dict[tuple[int, int], tuple[float, list[float], list[float]] | None],
                         dict[str, int]]:
    """Interference for ``want_int`` and clearance for ``want_clr`` (pairs of indices into ``insts``, which carry
    ``key``). Returns (interference rows by pair for the overlapping ones, clearance by pair (None = overlapping, the
    caller uses the overlap point), stats). ``call(req, timeout)`` sends one request to the assembly worker."""
    sigs = {k: part_sig(root, insts[k]["key"]) for k in {x for p in [*want_int, *want_clr] for x in p}}
    Ts = {k: xform.from12(insts[k]["T"]) for k in sigs}
    info: dict[tuple[int, int], tuple[bool, np.ndarray, str]] = {}
    for p in {*want_int, *want_clr}:
        info[p] = canon(sigs[p[0]], Ts[p[0]], sigs[p[1]], Ts[p[1]])
    tol_tag = f"{vol_tol:g}"
    int_res: dict[tuple[int, int], dict[str, Any]] = {}
    clr_res: dict[tuple[int, int], dict[str, Any]] = {}
    ops: dict[tuple[int, int], list[str]] = {}
    stats = {"computed": 0, "cached": 0}
    clr_set = set(want_clr)
    for p in sorted({*want_int, *want_clr}):
        key = info[p][2]
        need: list[str] = []
        if p in want_int or p in clr_set and _boxes_meet(insts[p[0]], insts[p[1]]):
            r = get(root, f"int|{tol_tag}", key) if use_cache else None
            if r is None:
                need.append("int")
            else:
                int_res[p] = r
        if p in clr_set:
            ir = int_res.get(p)
            if ir is None or ir.get("kind") is None:  # no overlap known yet, or none: the distance is needed
                r = get(root, "clr", key) if use_cache else None
                if r is None:
                    need.append("clr")  # with "int" too: the worker skips it when the parts overlap
                else:
                    clr_res[p] = r
        if need:
            ops[p] = need
        else:
            stats["cached"] += 1
    todo = sorted(ops)
    done = 0
    for k in range(0, len(todo), CHUNK):
        chunk = todo[k:k + CHUNK]
        jobs = []
        for p in chunk:
            swapped = info[p][0]
            a, b = (p[1], p[0]) if swapped else p
            jobs.append({"a": _job_side(insts[a]), "b": _job_side(insts[b]), "rel": xform.to12(info[p][1]),
                         "ops": ops[p]})
        STATS["calls"] += 1
        res = await call({"op": "pairs", "jobs": jobs, "vol_tol": vol_tol},
                         BASE_TIMEOUT_S + PER_PAIR_S * len(jobs))
        for p, r in zip(chunk, res, strict=True):
            key = info[p][2]
            if r.get("int") is not None:
                int_res[p] = r["int"]
                if use_cache:
                    put(root, f"int|{tol_tag}", key, r["int"])
            if r.get("clr") is not None:
                clr_res[p] = r["clr"]
                if use_cache:
                    put(root, "clr", key, r["clr"])
        stats["computed"] += len(chunk)
        STATS["computed"] += len(chunk)
        done += len(chunk)
        if progress:
            progress(done, len(todo))
    STATS["cached"] += stats["cached"]
    # back to the world frame of the pair's own order
    inter: dict[tuple[int, int], dict[str, Any]] = {}
    for p, r in int_res.items():
        if r.get("kind") is None:
            continue
        swapped, _rel, _key = info[p]
        P = Ts[p[1]] if swapped else Ts[p[0]]
        inter[p] = _world_int(r, P)
    clear: dict[tuple[int, int], tuple[float, list[float], list[float]] | None] = {}
    for p in want_clr:
        ir = int_res.get(p)
        if ir is not None and ir.get("kind") is not None:
            clear[p] = None
            continue
        swapped, _rel, _key = info[p]
        P = Ts[p[1]] if swapped else Ts[p[0]]
        clear[p] = _world_clr(clr_res[p], P, swapped)
    return inter, clear, stats


def _boxes_meet(ia: dict[str, Any], ib: dict[str, Any]) -> bool:
    """Instance world boxes overlap (within 1e-6): only then can the parts overlap (``geometry._apart``)."""
    a, b = world_box(ia), world_box(ib)
    return not (np.any(a[0] > b[1] + 1e-6) or np.any(b[0] > a[1] + 1e-6))


def world_box(inst: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    T = xform.from12(inst["T"])
    x0, y0, z0, x1, y1, z1 = inst["bbox"]
    pts = np.array([xform.pt(T, (x, y, z)) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)])
    return pts.min(axis=0), pts.max(axis=0)


def reset_stats() -> None:
    STATS.update(computed=0, cached=0, calls=0)
