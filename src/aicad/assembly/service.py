"""Assembly operations on documents (web-process side: pure Python + numpy; kernel work goes to the worker).

An instance is a placed copy of a cached part snapshot (``store.part_dir``): a project's verified build (pinned to
its build id, so the assembly notices when the part changes) or a Toolbox component (pinned to the generator
VERSION). Mates reference exact part-local geometry (``refs.json``) and are solved by ``solver``.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from aicad import materials, toolbox
from aicad.assembly import AssemblyInputError, fasteners, solver, store, xform
from aicad.assembly import worker as aworker

THREADED = {"hex_bolt", "shcs", "hex_nut"}
MAX_INSTANCES = 200
MAX_MATES = 600


class WorkerError(RuntimeError):
    pass


async def _call(org_id: str, req: dict[str, Any], timeout: float = 180) -> Any:
    res = await aworker.call(org_id, req, timeout)
    if not res.get("ok"):
        raise WorkerError(res.get("error") or "assembly worker failed")
    return res["result"]


# ----------------------------------------------------------------------------- parts
def clean_name(name: str) -> str:
    return name.removeprefix("Demo · ").strip() or "Part"


async def ensure_project_part(root: Path, org_id: str, project_id: str, project_name: str, ws: Path,
                              status: dict[str, Any], rev: str | None) -> str:
    step = ws / "out" / "part.step"
    if not status.get("ok") or not step.is_file():
        raise AssemblyInputError(f"{clean_name(project_name)} has no verified build yet. Build it in the Design "
                                 "Studio first.")
    key = store.project_key(project_id, status.get("build_id"))
    if not store.part_ready(root, key):
        d = store.part_dir(root, key)
        await _call(org_id, {"op": "prepare", "dest": str(d), "step": str(step)})
        store.write_json(d / "meta.json", {
            "key": key, "kind": "project", "project_id": project_id, "build_id": str(status.get("build_id")),
            "rev": rev, "name": clean_name(project_name), "material": status.get("material"), "standard": None,
            "created_at": store.now()})
    return key


async def ensure_toolbox_part(root: Path, org_id: str, code: str, params: dict[str, Any]) -> str:
    c = toolbox.spec(code)
    p = toolbox.normalize(code, params)
    key = store.toolbox_key(code, p, toolbox.VERSION)
    if not store.part_ready(root, key):
        d = store.part_dir(root, key)
        await _call(org_id, {"op": "prepare", "dest": str(d), "toolbox": {"code": code, "params": p}})
        store.write_json(d / "meta.json", {
            "key": key, "kind": "toolbox", "code": code, "params": p, "version": toolbox.VERSION, "name": c.title(p),
            "material": c.material, "standard": c.standard, "category": c.category, "created_at": store.now()})
    return key


async def ensure_placeholder_part(root: Path, org_id: str, key: str, spec: dict[str, Any], name: str,
                                  origin: dict[str, Any]) -> str:
    """A placeholder body (CD-011) in the part cache: the envelope with its interface features. ``origin`` says
    where it comes from (program, item, ICD version); the key must start with ``h_``."""
    if not key.startswith("h_"):
        raise AssemblyInputError("bad placeholder key")
    if not store.part_ready(root, key):
        d = store.part_dir(root, key)
        await _call(org_id, {"op": "placeholder", "dest": str(d), "spec": spec})
        store.write_json(d / "meta.json", {"key": key, "kind": "placeholder", "name": name, "material": None,
                                           "standard": None, **origin, "created_at": store.now()})
    return key


def _parts(root: Path, doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for i in doc["instances"]:
        if i["part"] not in out:
            p = store.part(root, i["part"])
            if p is None:
                raise AssemblyInputError("A part snapshot of this assembly is missing. Remove and re-insert it.")
            out[i["part"]] = p
    return out


def _inst(doc: dict[str, Any], iid: str) -> dict[str, Any]:
    for i in doc["instances"]:
        if i["id"] == iid:
            return i
    raise AssemblyInputError("Instance not found")


def world_box(doc: dict[str, Any], parts: dict[str, dict[str, Any]],
              only: Callable[[dict[str, Any]], bool] | None = None) -> tuple[np.ndarray, np.ndarray] | None:
    pts = []
    for i in doc["instances"]:
        if only and not only(i):
            continue
        T = xform.from12(i["T"])
        x0, y0, z0, x1, y1, z1 = parts[i["part"]]["info"]["bbox"]
        pts += [xform.pt(T, (x, y, z)) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    if not pts:
        return None
    a = np.array(pts)
    return a.min(axis=0), a.max(axis=0)


def length_scale(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> float:
    b = world_box(doc, parts)
    return 50.0 if b is None else max(10.0, float(np.linalg.norm(b[1] - b[0])) / 2)


# ----------------------------------------------------------------------------- instances
def add_instance(root: Path, doc: dict[str, Any], key: str, T: list[float] | None = None,
                 group: str | None = None, name: str | None = None) -> dict[str, Any]:
    if len(doc["instances"]) >= MAX_INSTANCES:
        raise AssemblyInputError(f"An assembly can hold up to {MAX_INSTANCES} instances.")
    p = store.part(root, key)
    if p is None:
        raise AssemblyInputError("Part not found")
    first = not doc["instances"]
    if T is None:
        if first:
            T = xform.to12(xform.ident())
        else:
            parts = _parts(root, doc)
            lo, hi = world_box(doc, parts)  # type: ignore[misc]
            bx = p["info"]["bbox"]
            gap = max(10.0, 0.15 * float(np.linalg.norm(hi - lo)))
            t = (hi[0] + gap - bx[0], (lo[1] + hi[1]) / 2 - (bx[1] + bx[4]) / 2, lo[2] - bx[2])
            T = xform.to12(xform.translate(t))
    inst = {"id": store.next_id(doc, "i"), "name": name or p["name"], "part": key,
            "source": _source(p), "T": T, "fixed": first, "visible": True, "group": group}
    doc["instances"].append(inst)
    return inst


def _source(p: dict[str, Any]) -> dict[str, Any]:
    if p["kind"] == "project":
        return {"kind": "project", "project_id": p["project_id"], "build_id": p["build_id"], "rev": p.get("rev")}
    if p["kind"] == "placeholder":
        return {"kind": "placeholder", "program_id": p.get("program_id"), "item_id": p.get("item_id"),
                "icd_version": p.get("icd_version")}
    return {"kind": "toolbox", "code": p["code"], "params": p["params"], "version": p["version"]}


def remove_instance(doc: dict[str, Any], iid: str) -> None:
    _inst(doc, iid)
    doc["instances"] = [i for i in doc["instances"] if i["id"] != iid]
    doc["mates"] = [m for m in doc["mates"] if iid not in (m["a"]["inst"], m["b"]["inst"])]
    used = {i.get("group") for i in doc["instances"]}
    doc["groups"] = [g for g in doc["groups"] if g["id"] in used]
    subs = {i.get("sub") for i in doc["instances"]}
    doc["subassemblies"] = [g for g in doc.get("subassemblies") or [] if g["id"] in subs]
    if doc["instances"] and not any(i["fixed"] for i in doc["instances"]):
        doc["instances"][0]["fixed"] = True


def remove_group(doc: dict[str, Any], gid: str) -> None:
    ids = [i["id"] for i in doc["instances"] if i.get("group") == gid]
    if not ids:
        raise AssemblyInputError("Group not found")
    for iid in ids:
        remove_instance(doc, iid)


def move_instance(root: Path, doc: dict[str, Any], iid: str, move: dict[str, Any]) -> None:
    inst = _inst(doc, iid)
    if inst["fixed"]:
        raise AssemblyInputError("This part is fixed. Float it first to move it.")
    parts = _parts(root, doc)
    T = xform.from12(inst["T"])
    if move.get("T") is not None:
        M = xform.from12(move["T"])
        if not xform.is_rigid(M):
            raise AssemblyInputError("A placement must be a rigid transform (rotation + translation).")
        T = M
    if move.get("translate") is not None:
        T = xform.translate(move["translate"]) @ T
    if move.get("rotate") is not None:
        r = move["rotate"]
        ax = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}[r["axis"]]
        c = xform.pt(T, parts[inst["part"]]["info"]["center"])
        T = xform.about(xform.rot(ax, math.radians(float(r["deg"]))), c) @ T
    inst["T"] = xform.to12(xform.orthonormalize(T))


# ----------------------------------------------------------------------------- mates
def resolve_ref(root: Path, doc: dict[str, Any], sel: dict[str, Any]) -> dict[str, Any]:
    inst = _inst(doc, str(sel.get("inst")))
    kind = sel.get("kind")
    if kind not in ("face", "edge"):
        raise AssemblyInputError("Pick a face or an edge.")
    r = store.refs(root, inst["part"])["faces" if kind == "face" else "edges"].get(str(int(sel.get("id", -1))))
    if r is None:
        raise AssemblyInputError("That selection can't be used in a mate. Pick a flat face, a cylindrical face, "
                                 "or a circular or straight edge.")
    return {"inst": inst["id"], "kind": kind, "id": int(sel["id"]), "ref": r}


def make_mate(root: Path, doc: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    if len(doc["mates"]) >= MAX_MATES:
        raise AssemblyInputError(f"An assembly can hold up to {MAX_MATES} mates.")
    a = resolve_ref(root, doc, body["a"])
    b = resolve_ref(root, doc, body["b"])
    if a["inst"] == b["inst"]:
        raise AssemblyInputError("Pick references on two different parts.")
    t = body.get("type") or "auto"
    ka, kb = a["ref"]["kind"], b["ref"]["kind"]
    if t == "auto":
        if ka == kb == "plane":
            t = "coincident"
        elif ka == kb == "axis":
            t = "concentric"
        else:
            raise AssemblyInputError("Pick two flat faces (coincident) or two cylinders / circular edges "
                                     "(concentric).")
    if t not in solver.MATE_TYPES:
        raise AssemblyInputError("Unknown mate type")
    need = solver.NEEDS[t]
    if ka != need or kb != need:
        raise AssemblyInputError(f"{solver.LABEL[t]} needs two " +
                                 ("flat faces." if need == "plane" else "cylindrical faces, circular or straight edges."))
    value = float(body.get("value") or 0.0)
    if not math.isfinite(value) or abs(value) > 10000:
        raise AssemblyInputError("Value out of range")
    if t == "angle" and not 0 <= value <= 180:
        raise AssemblyInputError("Angle must be between 0° and 180°.")
    if t == "distance" and value < 0:
        raise AssemblyInputError("Distance must be zero or positive (use Flip to change sides).")
    m = {"id": store.next_id(doc, "m"), "type": t, "a": a, "b": b, "value": value, "flip": bool(body.get("flip")),
         "suppressed": False, "broken": False, "group": body.get("group")}
    doc["mates"].append(m)
    return m


def edit_mate(root: Path, doc: dict[str, Any], m: dict[str, Any], body: dict[str, Any]) -> bool:
    """Change a mate in place (type, value, flip, suppress, re-pick either reference; AMI-06). Returns True when the
    mate's geometry changed, so the caller pre-aligns it like a new mate."""
    t = body.get("type") or m["type"]
    if t not in solver.MATE_TYPES:
        raise AssemblyInputError("Unknown mate type")
    a = resolve_ref(root, doc, body["a"]) if body.get("a") else m["a"]
    b = resolve_ref(root, doc, body["b"]) if body.get("b") else m["b"]
    if a["inst"] == b["inst"]:
        raise AssemblyInputError("Pick references on two different parts.")
    need = solver.NEEDS[t]
    if a["ref"]["kind"] != need or b["ref"]["kind"] != need:
        raise AssemblyInputError(f"{solver.LABEL[t]} needs two " +
                                 ("flat faces." if need == "plane" else "cylindrical faces, circular or straight edges."))
    value = float(body["value"]) if body.get("value") is not None else float(m.get("value") or 0.0)
    if not math.isfinite(value):
        raise AssemblyInputError("Value out of range")
    if t == "angle" and not 0 <= value <= 180:
        raise AssemblyInputError("Angle must be between 0° and 180°.")
    if t == "distance" and not 0 <= value <= 10000:
        raise AssemblyInputError("Distance must be between 0 and 10000 mm.")
    if t not in ("angle", "distance"):
        value = 0.0
    flip = bool(body["flip"]) if body.get("flip") is not None else bool(m.get("flip"))
    geometric = (t != m["type"] or value != float(m.get("value") or 0.0) or bool(body.get("a")) or bool(body.get("b"))
                 or flip != bool(m.get("flip")))
    m["type"], m["a"], m["b"], m["value"], m["flip"] = t, a, b, value, flip
    if body.get("suppressed") is not None:
        m["suppressed"] = bool(body["suppressed"])
    m["broken"] = bool(m["a"].get("lost") or m["b"].get("lost"))
    return geometric


def _spec(m: dict[str, Any]) -> solver.MateSpec:
    return solver.MateSpec(m["id"], m["type"], m["a"]["inst"], solver.Ref.of(m["a"]["ref"]), m["b"]["inst"],
                           solver.Ref.of(m["b"]["ref"]), float(m.get("value") or 0.0), bool(m.get("flip")))


def run_solve(root: Path, doc: dict[str, Any], prealign: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    parts = _parts(root, doc)
    insts = {i["id"]: solver.Inst(i["id"], xform.from12(i["T"]), bool(i["fixed"]),
                                  tuple(parts[i["part"]]["info"]["center"]))  # type: ignore[arg-type]
             for i in doc["instances"]}
    active = [m for m in doc["mates"] if not m.get("suppressed") and not m.get("broken")]
    res = solver.solve(insts, [_spec(m) for m in active], length_scale(doc, parts), prealign)
    for i in doc["instances"]:
        if not i["fixed"]:
            i["T"] = xform.to12(res.poses[i["id"]])
    rep = res.as_dict()
    rep["suppressed"] = sum(1 for m in doc["mates"] if m.get("suppressed"))
    rep["broken"] = sum(1 for m in doc["mates"] if m.get("broken"))
    rep["no_fixed"] = bool(doc["instances"]) and not any(i["fixed"] for i in doc["instances"])
    doc["solve"] = rep
    return rep


# ----------------------------------------------------------------------------- refresh (part updated)
def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a["kind"] != b["kind"]:
        return False
    va, vb = np.array(a["v"]), np.array(b["v"])
    pa, pb = np.array(a["p"]), np.array(b["p"])
    if a["kind"] == "plane":
        return float(va @ vb) > 1 - 1e-9 and abs(float((pb - pa) @ va)) < 1e-6
    if abs(abs(float(va @ vb)) - 1) > 1e-9:
        return False
    if (a.get("r") is None) != (b.get("r") is None) or (a.get("r") is not None and abs(a["r"] - b["r"]) > 1e-6):
        return False
    w = pb - pa
    return float(np.linalg.norm(w - va * float(w @ va))) < 1e-6


def _compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Same kind of reference with the same orientation (planes keep their outward normal; axes may flip)."""
    if a["kind"] != b["kind"]:
        return False
    va, vb = xform.unit(a["v"]), xform.unit(b["v"])
    if a["kind"] == "plane":
        return float(va @ vb) > 1 - 1e-6
    return abs(abs(float(va @ vb)) - 1) < 1e-6 and (a.get("r") is None) == (b.get("r") is None)


def _line_offset(a: dict[str, Any], q: Any) -> float:
    v = xform.unit(a["v"])
    w = np.asarray(q, dtype=float) - np.asarray(a["p"], dtype=float)
    return float(np.linalg.norm(w - v * float(w @ v)))


def _canon(v: Any) -> np.ndarray:
    u = xform.unit(v)
    for c in u:
        if abs(c) > 1e-9:
            return u if c > 0 else -u
    return u


def match_ref(old: dict[str, Any], old_id: int, old_pool: dict[str, dict[str, Any]], new_pool: dict[str, dict[str, Any]],
              old_role: set[int], new_role: set[int], scale: float, face: bool) -> tuple[int | None, bool]:
    """Find the reference in a rebuilt part that plays the same role as ``old`` (AMI-05).

    Returns (new id or None, identical geometry?). Order of evidence: the same id with identical geometry; identical
    geometry under another id; then the *same role and topology*: same kind and orientation, same feature role (a
    recognised hole stays a hole), and either the same axis line (a hole whose Ø changed) or the same rank among its
    peers (the top face stays the top face when the plate gets thicker; the upper rim stays the upper rim)."""
    hit = new_pool.get(str(old_id))
    if hit is not None and _same(old, hit):
        return old_id, True
    for k, v in sorted(new_pool.items(), key=lambda kv: int(kv[0])):
        if _same(old, v):
            return int(k), True
    role = old_id in old_role

    def group(pool: dict[str, dict[str, Any]], roles: set[int]) -> list[tuple[int, dict[str, Any]]]:
        return sorted(((int(k), r) for k, r in pool.items() if _compatible(old, r) and (int(k) in roles) == role),
                      key=lambda kr: kr[0])

    peers = [kr for kr in group(old_pool, old_role) if kr[0] != old_id] + [(old_id, old)]
    cands = group(new_pool, new_role)
    if not cands:
        return None, False
    v = _canon(old["v"])

    def ranked(items: list[tuple[int, dict[str, Any]]], key: Any) -> list[int]:
        return [k for k, _r in sorted(items, key=lambda kr: key(kr[1]))]

    if old["kind"] == "plane":
        def pkey(r: dict[str, Any]) -> tuple[float, ...]:
            p = np.asarray(r["p"], dtype=float)
            return (round(float(p @ v), 6), *(round(float(x), 3) for x in p))

        if len(peers) == len(cands):
            return ranked(cands, pkey)[ranked(peers, pkey).index(old_id)], False
        o = float(np.asarray(old["p"]) @ v)
        best = min(cands, key=lambda kr: abs(float(np.asarray(kr[1]["p"]) @ v) - o)
                   + 0.01 * float(np.linalg.norm(np.asarray(kr[1]["p"]) - np.asarray(old["p"]))))
        return best[0], False

    # axes: cylindrical faces (ordered by radius on one line) and circular / straight edges (ordered along the line)
    p0 = np.asarray(old["p"], dtype=float)

    def akey(r: dict[str, Any]) -> tuple[float, float]:
        t = round(float((np.asarray(r["p"], dtype=float) - p0) @ v), 6)
        rr = round(float(r.get("r") or 0.0), 6)
        return (rr, t) if face else (t, rr)

    tol = max(0.5, 0.02 * scale)
    near = [kr for kr in cands if _line_offset(old, kr[1]["p"]) <= tol]
    if near:
        off = min(_line_offset(old, kr[1]["p"]) for kr in near)
        near = [kr for kr in near if _line_offset(old, kr[1]["p"]) <= off + 1e-6]
        on_line = [kr for kr in peers if _line_offset(old, kr[1]["p"]) <= 1e-6]
        if len(on_line) == len(near) > 1:
            return ranked(near, akey)[ranked(on_line, akey).index(old_id)], False
        ko = akey(old)
        best = min(near, key=lambda kr: abs(akey(kr[1])[0] - ko[0]) + abs(akey(kr[1])[1] - ko[1]))
        return best[0], False
    if len(peers) == len(cands):
        def gkey(r: dict[str, Any]) -> tuple[float, ...]:
            pp = np.asarray(r["p"], dtype=float)
            foot = pp - v * float(pp @ v)
            return (*(round(float(x), 3) for x in foot), round(float(r.get("r") or 0.0), 6))

        return ranked(cands, gkey)[ranked(peers, gkey).index(old_id)], False
    return None, False


def _hole_faces(info: dict[str, Any] | None) -> set[int]:
    return {int(f) for h in (info or {}).get("holes", []) for f in h.get("faces", [])}


def remap_refs(root: Path, doc: dict[str, Any], iid: str, new_key: str, old_key: str | None = None) -> dict[str, int]:
    """Point the mates of instance iid at the same references in a new part snapshot, matched by role and topology
    rather than identical geometry. Returns counts {kept (identical), followed (geometry changed), lost}."""
    new = store.refs(root, new_key)
    new_part = store.part(root, new_key) or {}
    old_part = store.part(root, old_key) if old_key else None
    try:
        old = store.refs(root, old_key) if old_key and old_part else {"faces": {}, "edges": {}}
    except (AssemblyInputError, OSError, ValueError):
        old = {"faces": {}, "edges": {}}
    roles = {"faces": (_hole_faces(old_part["info"] if old_part else None), _hole_faces(new_part.get("info"))),
             "edges": (set(), set())}
    bb = (new_part.get("info") or {}).get("bbox") or [0, 0, 0, 100, 100, 100]
    scale = float(np.linalg.norm(np.array(bb[3:]) - np.array(bb[:3]))) or 100.0
    out = {"kept": 0, "followed": 0, "lost": 0}
    for m in doc["mates"]:
        touched = False
        for side in ("a", "b"):
            s = m[side]
            if s["inst"] != iid:
                continue
            touched = True
            pool = "faces" if s["kind"] == "face" else "edges"
            o_role, n_role = roles[pool]
            new_id, same = match_ref(s["ref"], int(s["id"]), old.get(pool) or {}, new[pool], o_role, n_role, scale,
                                     face=pool == "faces")
            if new_id is None:
                s["lost"] = True
                out["lost"] += 1
                continue
            s["id"] = new_id
            s["ref"] = new[pool][str(new_id)]
            s.pop("lost", None)
            out["kept" if same else "followed"] += 1
        if touched:
            m["broken"] = bool(m["a"].get("lost") or m["b"].get("lost"))
    return out


def remap_hole(old_info: dict[str, Any] | None, new_info: dict[str, Any], k: int) -> int | None:
    """Index of the same hole in a rebuilt part: parallel axis, nearest axis line (its Ø may have changed)."""
    holes = new_info.get("holes", [])
    if old_info is None or not 0 <= k < len(old_info.get("holes", [])):
        return k if 0 <= k < len(holes) else None
    h = old_info["holes"][k]
    ref = {"kind": "axis", "p": (h.get("exact") or {}).get("p") or h["center"], "v": h["axis"]}
    best, best_d = None, math.inf
    for j, n in enumerate(holes):
        if abs(abs(float(xform.unit(n["axis"]) @ xform.unit(h["axis"]))) - 1) > 1e-6:
            continue
        d = _line_offset(ref, (n.get("exact") or {}).get("p") or n["center"])
        d += 0.01 * float(np.linalg.norm(np.asarray(n["center"]) - np.asarray(h["center"])))
        if d < best_d:
            best, best_d = j, d
    bb = new_info.get("bbox") or [0, 0, 0, 100, 100, 100]
    tol = max(0.5, 0.02 * float(np.linalg.norm(np.array(bb[3:]) - np.array(bb[:3]))))
    return best if best is not None and best_d <= tol else None


# ----------------------------------------------------------------------------- explode (ASM-007)
def explode(root: Path, doc: dict[str, Any]) -> dict[str, list[float]]:
    """Offsets at full explode. Each part moves away from the part it sits on: along the mated face normal
    (contact mates first), else along a concentric axis, else radially; offsets accumulate down the mate tree so a
    fastener stack spreads in order (washer, then bolt head)."""
    if not doc["instances"]:
        return {}
    parts = _parts(root, doc)
    lo, hi = world_box(doc, parts)  # type: ignore[misc]
    diag = float(np.linalg.norm(hi - lo)) or 1.0
    s0 = 0.08 * diag
    centre = (lo + hi) / 2
    poses = {i["id"]: xform.from12(i["T"]) for i in doc["instances"]}
    ctr = {i["id"]: xform.pt(poses[i["id"]], parts[i["part"]]["info"]["center"]) for i in doc["instances"]}
    active = [m for m in doc["mates"] if not m.get("suppressed") and not m.get("broken")]
    off: dict[str, np.ndarray] = {i["id"]: np.zeros(3) for i in doc["instances"] if i["fixed"]}
    if not off:
        off[doc["instances"][0]["id"]] = np.zeros(3)

    def extent(iid: str, d: np.ndarray) -> float:
        inst = next(i for i in doc["instances"] if i["id"] == iid)
        x0, y0, z0, x1, y1, z1 = parts[inst["part"]]["info"]["bbox"]
        T = poses[iid]
        vals = [float(xform.pt(T, (x, y, z)) @ d) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
        return max(vals) - min(vals)

    while True:
        progressed = False
        for plane_pass in (True, False):
            for inst in doc["instances"]:
                iid = inst["id"]
                if iid in off:
                    continue
                for m in active:
                    if iid not in (m["a"]["inst"], m["b"]["inst"]):
                        continue
                    other = m["b"]["inst"] if m["a"]["inst"] == iid else m["a"]["inst"]
                    if other not in off:
                        continue
                    if (m["type"] in solver.PLANE_MATES) != plane_pass:
                        continue
                    so = m["a"] if other == m["a"]["inst"] else m["b"]
                    v = xform.unit(xform.vec(poses[other], so["ref"]["v"]))
                    if m["type"] in solver.PLANE_MATES:
                        d = v  # the parent's outward face normal points at the part sitting on it
                    else:
                        side = float((ctr[iid] - ctr[other]) @ v)
                        d = v if side >= 0 else -v
                    off[iid] = off[other] + d * (s0 + 0.6 * extent(iid, d))
                    progressed = True
                    break
            if progressed:
                break
        if not progressed:
            break
    for inst in doc["instances"]:
        if inst["id"] not in off:
            r = ctr[inst["id"]] - centre
            n = float(np.linalg.norm(r))
            d = r / n if n > 1e-9 else np.array([0.0, 0.0, 1.0])
            off[inst["id"]] = d * (s0 + 0.6 * extent(inst["id"], d))
    return {k: [round(float(x), 6) for x in v] for k, v in off.items()}


# ----------------------------------------------------------------------------- BOM (ASM-008 / DRW-014)
def _density(material: str | None) -> float | None:
    m = materials.get(materials.guess(material))
    return float(m["density_g_cm3"]) if m else None  # type: ignore[arg-type]


def bom(root: Path, doc: dict[str, Any], project_names: dict[str, str] | None = None) -> dict[str, Any]:
    parts = _parts(root, doc)
    groups: dict[str, list[dict[str, Any]]] = {}
    for i in doc["instances"]:
        groups.setdefault(i["part"], []).append(i)

    def sort_key(key: str) -> tuple[Any, ...]:
        p = parts[key]
        if p["kind"] in ("project", "placeholder"):
            return (0, doc["instances"].index(groups[key][0]))
        order = list(toolbox.COMPONENTS)
        return (1, order.index(p["code"]) if p["code"] in order else 99, p["params"].get("D", 0), p["params"].get("L", 0))

    rows = []
    total = 0.0
    unknown = 0
    for n, key in enumerate(sorted(groups, key=sort_key), start=1):
        p = parts[key]
        qty = len(groups[key])
        rho = _density(p.get("material"))
        each = p["info"]["volume"] * rho / 1000.0 if rho else None
        if each is None:
            unknown += qty
        else:
            total += each * qty
        name = p["name"]
        if p["kind"] == "project" and project_names and p["project_id"] in project_names:
            name = clean_name(project_names[p["project_id"]])
        rows.append({
            "item": n, "qty": qty, "part": name, "kind": p["kind"],
            "description": (f"Project part, revision {p['rev']}" if p["kind"] == "project" and p.get("rev")
                            else "Project part" if p["kind"] == "project"
                            else "Placeholder (envelope with its interfaces; the part is still in design)"
                            if p["kind"] == "placeholder" else toolbox.spec(p["code"]).name),
            "standard": p.get("standard") if p["kind"] == "toolbox" else None,
            "designation": p["name"] if p["kind"] == "toolbox" else None,
            "material": p.get("material"), "density_g_cm3": rho,
            "mass_each_g": None if each is None else round(each, 2),
            "mass_total_g": None if each is None else round(each * qty, 2),
            "instances": [i["id"] for i in groups[key]], "part_key": key})
    return {"rows": rows, "total_qty": sum(r["qty"] for r in rows), "total_mass_g": round(total, 2),
            "mass_unknown_qty": unknown,
            "note": "Masses use nominal densities for the stated materials (verify with your supplier). Toolbox "
                    "fasteners are modelled with cosmetic threads. Placeholders have no mass."}


def bom_csv(b: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["Item", "Qty", "Part", "Description", "Standard", "Material", "Mass each (g)", "Mass total (g)"])
    for r in b["rows"]:
        w.writerow([r["item"], r["qty"], r["part"], r["description"], r["standard"] or "", r["material"] or "",
                    "" if r["mass_each_g"] is None else f"{r['mass_each_g']:.2f}",
                    "" if r["mass_total_g"] is None else f"{r['mass_total_g']:.2f}"])
    w.writerow(["", b["total_qty"], "Total", "", "", "", "", f"{b['total_mass_g']:.2f}"])
    return buf.getvalue()


# ----------------------------------------------------------------------------- worker payloads
def geometry_signature(doc: dict[str, Any]) -> str:
    sig = [(i["id"], i["part"], [round(x, 9) for x in i["T"]]) for i in doc["instances"]]
    return hashlib.sha1(json.dumps(sig).encode()).hexdigest()[:16]


def worker_instances(root: Path, doc: dict[str, Any], skip_groups: bool = False) -> list[dict[str, Any]]:
    parts = _parts(root, doc)
    out = []
    for i in doc["instances"]:
        if skip_groups and i.get("group"):
            continue
        p = parts[i["part"]]
        row = {"id": i["id"], "name": display_names(doc)[i["id"]], "step": str(store.part_dir(root, i["part"]) / "part.step"),
               "T": i["T"], "bbox": p["info"]["bbox"], "material": p.get("material"), "holes": p["info"].get("holes", [])}
        if p["kind"] == "toolbox" and p["code"] in THREADED:
            row["thread"] = {"d_nom": p["params"]["D"], "p": [0, 0, 0], "d": [0, 0, 1]}
        env = part_envelope(p)
        if env:
            row["envelope"] = env
        out.append(row)
    return out


def part_envelope(p: dict[str, Any]) -> dict[str, Any] | None:
    """A simple solid that contains every solid of a multi-solid Toolbox part, for clash screening: a ball bearing
    (rings + balls) lies inside the ring from its bore to its OD over its width (``toolbox._bearing``)."""
    if p.get("kind") != "toolbox" or p.get("code") != "bearing":
        return None
    row = toolbox.BEARING.get(round(float((p.get("params") or {}).get("SERIES") or 0)))
    if not row:
        return None
    d, D, B = (float(x) for x in row)
    return {"kind": "annulus", "r0": d / 2, "r1": D / 2, "z0": 0.0, "z1": B}


def display_names(doc: dict[str, Any]) -> dict[str, str]:
    """SOLIDWORKS-style instance names: ``Mounting plate<1>``, ``Mounting plate<2>``."""
    count: dict[str, int] = {}
    out = {}
    for i in doc["instances"]:
        count[i["name"]] = count.get(i["name"], 0) + 1
        out[i["id"]] = f"{i['name']}<{count[i['name']]}>"
    return out


async def analyse(root: Path, org_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    insts = worker_instances(root, doc)
    pairs = sorted({(m["a"]["inst"], m["b"]["inst"], "mate") for m in doc["mates"]})
    parts = _parts(root, doc)
    near = max(2.0, 0.05 * length_scale(doc, parts) * 2)
    res = await _call(org_id, {"op": "analyse", "instances": insts, "pairs": [list(p) for p in pairs],
                               "near_mm": near}, timeout=300)
    names = display_names(doc)
    inter = res["interference"]
    by_pair = {tuple(sorted((p["a"], p["b"]))): p for p in inter["pairs"]}
    for p in inter["pairs"]:
        p["a_name"], p["b_name"] = names[p["a"]], names[p["b"]]
    rows = []
    for r in res["clearance"]["rows"]:
        ip = by_pair.get(tuple(sorted((r["a"], r["b"]))))
        if ip is not None:
            status = "interference" if ip["kind"] == "interference" else "thread"
        elif r["distance_mm"] < 1e-6:
            status = "contact"
        else:
            status = "clear"
        rows.append({**r, "a_name": names[r["a"]], "b_name": names[r["b"]], "status": status,
                     "mates": [m["id"] for m in doc["mates"] if {m["a"]["inst"], m["b"]["inst"]} == {r["a"], r["b"]}]})
    rows.sort(key=lambda r: ({"interference": 0, "thread": 2, "contact": 3, "clear": 1}[r["status"]], r["distance_mm"]))
    hard = [p for p in inter["pairs"] if p["kind"] == "interference"]
    out = {"signature": geometry_signature(doc), "at": store.now(),
           "interference": {"pairs": inter["pairs"], "checked_pairs": inter["checked_pairs"],
                            "count": len(hard), "total_mm3": round(sum(p["volume_mm3"] for p in hard), 6)},
           "clearance": {"rows": rows, "near_mm": round(near, 3),
                         "min_clear_mm": min((r["distance_mm"] for r in rows if r["status"] == "clear"), default=None)},
           "note": "Exact B-rep booleans (interference volume) and exact minimum distances on the nominal geometry. "
                   "Threads are cosmetic: an overlap that stays inside a fastener's nominal thread diameter is "
                   "reported as thread engagement, not a clash. Tolerances and deflection are not considered."}
    store.write_json(store.doc_dir(root, doc["id"]) / "analysis.json", out)
    return out


async def export_step(root: Path, org_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    if not doc["instances"]:
        raise AssemblyInputError("The assembly is empty.")
    parts = _parts(root, doc)
    names = display_names(doc)
    glabel = {g["id"]: g["name"] for g in doc["groups"]}
    slabel = {g["id"]: g["name"] for g in doc.get("subassemblies") or []}
    nodes = [{"id": i["id"], "part_label": parts[i["part"]]["name"], "instance": names[i["id"]],
              "step": str(store.part_dir(root, i["part"]) / "part.step"), "T": i["T"], "group": i.get("group"),
              "group_label": glabel.get(i.get("group") or "", None),
              "sub": i.get("sub") if i.get("sub") in slabel else None, "sub_label": slabel.get(i.get("sub") or "")}
             for i in doc["instances"]]
    dest = store.doc_dir(root, doc["id"]) / "assembly.step"
    res = await _call(org_id, {"op": "export", "dest": str(dest), "name": doc["name"], "nodes": nodes}, timeout=300)
    res["signature"] = geometry_signature(doc)
    res["at"] = store.now()
    store.write_json(store.doc_dir(root, doc["id"]) / "export.json", res)
    return res


# ----------------------------------------------------------------------------- fastener auto-fit
def fastener_targets(root: Path, doc: dict[str, Any], iid: str, hole: int, pattern: bool) -> list[dict[str, Any]]:
    inst = _inst(doc, iid)
    if inst.get("group"):
        raise AssemblyInputError("Pick a hole in a part, not in a fastener.")
    info = store.part(root, inst["part"])["info"]  # type: ignore[index]
    holes = info.get("holes", [])
    if not 0 <= hole < len(holes):
        raise AssemblyInputError("Hole not found")
    idx = [hole]
    if pattern:
        for p in info.get("patterns", []):
            if hole in p["holes"]:
                idx = sorted(p["holes"])
                break
    return [{"inst": iid, "hole": k} for k in idx]


def _space_warnings(pr: dict[str, Any], prop: dict[str, Any]) -> None:
    if not prop.get("ok"):
        return
    d = prop["size"]
    items = {i["role"]: i for i in prop["items"]}
    screw = items["screw"]
    head_h = (toolbox.HEX_HEAD[d][1] if screw["code"] == "hex_bolt" else toolbox.SHCS[d][1])
    wh = toolbox.WASHER[d][2] if "washer_head" in items else 0.0
    sp = pr["head"].get("space")
    if sp is not None and sp < head_h + wh - 1e-6:
        prop["warnings"].append(f"Head side: only {sp:g} mm free for the head and washer ({head_h + wh:g} mm needed).")
        prop["no_room"] = True
    if prop["kind"] == "through":
        wn = toolbox.WASHER[d][2] if "washer_nut" in items else 0.0
        need = wn + prop["length"]["protrusion"] + 0.0
        sp = pr["nut"].get("space")
        if sp is not None and sp < need - 1e-6:
            prop["warnings"].append(f"Nut side: only {sp:g} mm free for the washer, nut and bolt end ({need:g} mm needed).")
            prop["no_room"] = True


async def propose(root: Path, org_id: str, doc: dict[str, Any], targets: list[dict[str, Any]], style: str,
                  washers: str, flip: bool) -> dict[str, Any]:
    insts = worker_instances(root, doc, skip_groups=True)
    probes = await _call(org_id, {"op": "probe", "instances": insts,
                                  "targets": [{**t, "flip": flip} for t in targets]}, timeout=240)
    holes = []
    for t, pr in zip(targets, probes, strict=True):
        prop = fasteners.propose(pr, style=style, washers=washers)
        _space_warnings(pr, prop)
        holes.append({"inst": t["inst"], "hole": t["hole"], "probe": pr, "proposal": prop})
    ok = [h for h in holes if h["proposal"]["ok"]]
    lengths: dict[str, int] = {}
    for h in ok:
        s = h["proposal"]["summary"]
        lengths[s] = lengths.get(s, 0) + 1
    return {"holes": holes, "ok": len(ok), "failed": len(holes) - len(ok),
            "stacks": [{"summary": k, "count": v} for k, v in lengths.items()],
            "style": style, "washers": washers, "flip": flip}


def coaxial_hole_pairs(root: Path, doc: dict[str, Any], a: str, b: str) -> list[dict[str, Any]]:
    """Every recognised hole of part a that lines up with a recognised hole of part b (same axis line within
    0.01 mm, in the current placement). The stack is fitted from the smaller hole, so the screw passes both
    (AMI-I2: "Fasten these two parts")."""
    ia, ib = _inst(doc, a), _inst(doc, b)
    if a == b or ia.get("group") or ib.get("group"):
        raise AssemblyInputError("Pick two different parts (not fasteners).")
    parts = _parts(root, doc)

    def world(inst: dict[str, Any]) -> list[tuple[int, dict[str, Any], np.ndarray, np.ndarray]]:
        T = xform.from12(inst["T"])
        return [(k, h, xform.pt(T, (h.get("exact") or {}).get("p") or h["center"]), xform.unit(xform.vec(T, h["axis"])))
                for k, h in enumerate(parts[inst["part"]]["info"].get("holes", []))]

    out = []
    used_b: set[int] = set()
    for ka, ha, pa, ua in world(ia):
        for kb, hb, pb, ub in world(ib):
            if kb in used_b or abs(abs(float(ua @ ub)) - 1) > 1e-6:
                continue
            w = pb - pa
            if float(np.linalg.norm(w - ua * float(w @ ua))) > 0.01:
                continue
            used_b.add(kb)
            small = (a, ka, ha) if ha["d"] <= hb["d"] + 1e-9 else (b, kb, hb)
            big = (b, kb, hb) if small[0] == a else (a, ka, ha)
            sa, sb = fasteners.size_for_clearance(ha["d"]), fasteners.size_for_clearance(hb["d"])
            out.append({"a_hole": ka, "b_hole": kb, "a_d": ha["d"], "b_d": hb["d"],
                        "target": {"inst": small[0], "hole": small[1]},
                        "mismatch": None if (sa and sb and sa["d"] == sb["d"]) or abs(ha["d"] - hb["d"]) < 1e-9 else
                        {"inst": small[0], "hole": small[1], "d": small[2]["d"], "to_d": big[2]["d"],
                         "size": (fasteners.size_for_clearance(big[2]["d"]) or {}).get("d")},
                        "point": [round(float(x), 4) for x in pa]})
            break
    return out


def _tb_ref(root: Path, key: str, kind: str, *, r: float | None = None, z: float | None = None,
            nz: float | None = None) -> dict[str, Any] | None:
    for fid, f in sorted(store.refs(root, key)["faces"].items(), key=lambda kv: int(kv[0])):
        if f["kind"] != kind:
            continue
        if kind == "axis" and r is not None and f.get("r") is not None and abs(f["r"] - r) < 1e-6 \
                and abs(abs(f["v"][2]) - 1) < 1e-9 and abs(f["p"][0]) < 1e-9 and abs(f["p"][1]) < 1e-9:
            return {"kind": "face", "id": int(fid), "ref": f}
        if kind == "plane" and z is not None and abs(f["p"][2] - z) < 1e-9 and nz is not None \
                and abs(f["v"][2] - nz) < 1e-9:
            return {"kind": "face", "id": int(fid), "ref": f}
    return None


async def accept(root: Path, org_id: str, doc: dict[str, Any], targets: list[dict[str, Any]], style: str,
                 washers: str, flip: bool) -> dict[str, Any]:
    plan = await propose(root, org_id, doc, targets, style, washers, flip)
    pattern_id = store.next_id(doc, "fp") if len(targets) > 1 else None
    made = 0
    before = {i["id"] for i in doc["instances"]}
    for h in plan["holes"]:
        prop = h["proposal"]
        if not prop["ok"]:
            continue
        keys = {}
        for it in prop["items"]:
            keys[it["role"]] = await ensure_toolbox_part(root, org_id, it["code"], it["params"])
        made += 1
        gid = store.next_id(doc, "g")
        n_groups = sum(1 for g in doc["groups"] if g.get("kind") == "fastener") + 1
        doc["groups"].append({"id": gid, "kind": "fastener", "name": f"Fastener stack {n_groups} ({prop['summary']})",
                              "pattern": pattern_id, "hole": {"inst": h["inst"], "hole": h["hole"]},
                              "spec": {**{k: prop[k] for k in ("summary", "designation", "size", "kind", "grip", "rule",
                                                               "clearance", "length", "warnings", "sources")},
                                       "style": style, "washers": washers, "flip": flip}})
        _insert_stack(root, doc, h, keys, gid)
    if not made:
        raise AssemblyInputError(next((h["proposal"].get("error") for h in plan["holes"] if h["proposal"].get("error")),
                                      "No fastener could be fitted."))
    run_solve(root, doc)
    new_ids = [i["id"] for i in doc["instances"] if i["id"] not in before]
    clashes = await stack_clashes(root, org_id, doc, new_ids)
    return {"inserted": made, "plan": plan, "clashes": clashes}


async def stack_clashes(root: Path, org_id: str, doc: dict[str, Any], ids: list[str]) -> list[dict[str, Any]]:
    """Exact interference of just-inserted fastener parts against everything else (thread engagement excluded), so
    a stack that lands inside a part is reported at once instead of looking verified (AMI-01)."""
    if not ids:
        return []
    res = await _call(org_id, {"op": "interference", "instances": worker_instances(root, doc), "only": ids}, timeout=240)
    names = display_names(doc)
    return [{"a": p["a"], "b": p["b"], "a_name": names[p["a"]], "b_name": names[p["b"]],
             "volume_mm3": p["volume_mm3"]} for p in res["pairs"] if p["kind"] == "interference"]


async def recheck_stacks(root: Path, org_id: str, doc: dict[str, Any], old_infos: dict[str, dict[str, Any]]) -> int:
    """After parts were refreshed, re-run the fastener proposal for every inserted stack (AMI-07). A stack whose
    size, length or fit changed is flagged ``check`` with the new proposal, and the user updates it in one click.
    ``old_infos`` maps refreshed instance ids to their previous part info (to follow the picked hole)."""
    flagged = 0
    for g in doc["groups"]:
        if g.get("kind") != "fastener" or not g.get("hole"):
            continue
        h = g["hole"]
        g.pop("check", None)
        try:
            inst = _inst(doc, h["inst"])
        except AssemblyInputError:
            g["check"] = {"text": "The part this stack was fitted to is gone. Delete the stack.", "summary": None}
            flagged += 1
            continue
        info = (store.part(root, inst["part"]) or {}).get("info") or {}
        if h["inst"] in old_infos:
            k = remap_hole(old_infos[h["inst"]], info, int(h["hole"]))
            if k is None:
                g["check"] = {"text": "The hole this stack was fitted to is gone from the updated part.",
                              "summary": None}
                flagged += 1
                continue
            h["hole"] = k
        spec = g.get("spec") or {}
        plan = await propose(root, org_id, doc, [{"inst": h["inst"], "hole": int(h["hole"])}],
                             spec.get("style", "hex_bolt"), spec.get("washers", "both"), bool(spec.get("flip")))
        hp = plan["holes"][0]
        prop = hp["proposal"]
        old_grip = float(spec.get("grip") or 0.0)
        if not prop.get("ok"):
            g["check"] = {"text": "No longer fits: " + (prop.get("error") or "the hole changed."), "summary": None}
            flagged += 1
            continue
        grip_changed = abs(float(prop.get("grip") or 0.0) - old_grip) > 1e-6
        if prop["summary"] == spec.get("summary") and not grip_changed:
            continue
        why = []
        if prop.get("designation") != spec.get("designation"):
            hd = hp["probe"].get("hole_d")
            why.append(f"hole now Ø{hd:g} ({prop['designation']} clearance)" if hd else "the hole changed")
        if grip_changed:
            why.append(f"grip now {float(prop['grip']):g} mm (was {old_grip:g} mm)")
        g["check"] = {"text": "Check size: " + "; ".join(why or ["the joint changed"]) + ".",
                      "summary": prop["summary"]}
        flagged += 1
    return flagged


def _insert_stack(root: Path, doc: dict[str, Any], h: dict[str, Any], keys: dict[str, str], gid: str) -> None:
    """Place one proposed stack along its hole axis and mate it: every element concentric with the hole, and a
    contact chain seat -> washer -> head (and seat -> washer -> nut). Placements satisfy the mates exactly."""
    prop, pr = h["proposal"], h["probe"]
    d = prop["size"]
    head_pt, out = np.array(pr["head"]["point"]), xform.unit(pr["head"]["out"])
    nut_pt, out_n = np.array(pr["nut"]["point"]), xform.unit(pr["nut"]["out"])
    R_head, R_nut = xform.frame_z(out), xform.frame_z(out_n)
    hole_face = (pr["hole"]["faces"] or [None])[0]
    hole_sel = {"inst": h["inst"], "kind": "face", "id": hole_face} if hole_face is not None else None
    wh = toolbox.WASHER[d][2]
    placed: dict[str, str] = {}

    def put(role: str, R: np.ndarray, origin: np.ndarray) -> None:
        inst = add_instance(root, doc, keys[role], T=xform.to12(xform.make(R, origin)), group=gid)
        placed[role] = inst["id"]

    z = head_pt
    if "washer_head" in keys:
        put("washer_head", R_head, z)
        z = z + out * wh
    put("screw", R_head, z)
    if "nut" in keys:
        zn = nut_pt
        if "washer_nut" in keys:
            put("washer_nut", R_nut, zn)
            zn = zn + out_n * wh
        put("nut", R_nut, zn)

    def mate(t: str, a: dict[str, Any] | None, b_inst: str, b: dict[str, Any] | None) -> None:
        if a is None or b is None or a.get("id") is None:
            return
        make_mate(root, doc, {"type": t, "a": a, "b": {"inst": b_inst, "kind": b["kind"], "id": b["id"]},
                              "group": gid})

    bore = {"washer_head": toolbox.WASHER[d][0] / 2, "washer_nut": toolbox.WASHER[d][0] / 2, "nut": d / 2,
            "screw": d / 2}
    for role, iid in placed.items():
        mate("concentric", hole_sel, iid, _tb_ref(root, keys[role], "axis", r=bore[role]))
    chains = ((({"inst": pr["head"]["inst"], "kind": "face", "id": pr["head"]["face"]}), ("washer_head", "screw")),
              (({"inst": pr["nut"]["inst"], "kind": "face", "id": pr["nut"].get("face")}), ("washer_nut", "nut")))
    for seat, roles in chains:
        prev: dict[str, Any] | None = seat
        for role in roles:
            if role not in placed:
                continue
            mate("coincident", prev, placed[role], _tb_ref(root, keys[role], "plane", z=0.0, nz=-1.0))
            if role.startswith("washer"):
                top = _tb_ref(root, keys[role], "plane", z=wh, nz=1.0)
                prev = {"inst": placed[role], "kind": "face", "id": top["id"]} if top else None


# ----------------------------------------------------------------------------- sub-assemblies (nested assemblies)
# An assembly can contain other assemblies. The parent keeps a *copy* of the sub-assembly's instances, mates and
# fastener stacks, tagged with the sub-assembly group (inst["sub"], mate["sub"]) and the source instance id
# (inst["src"]); doc["subassemblies"] lists the groups with their source document, the source revision copied
# and a rigid transform T (sub-assembly frame -> parent frame). Refresh re-copies from the source and keeps the
# parent's instance ids, so mates between sub-assemblies survive. One level is kept: a sub-assembly that itself
# contains sub-assemblies is copied flat (its parts and stacks stay, its own grouping does not). The STEP export
# writes each group as a sub-assembly node (its parts and fastener stacks inside it).


def subassembly(doc: dict[str, Any], gid: str) -> dict[str, Any]:
    g = next((x for x in doc.get("subassemblies") or [] if x["id"] == gid), None)
    if g is None:
        raise AssemblyInputError("Sub-assembly not found")
    return g


def insert_subassembly(root: Path, doc: dict[str, Any], src: dict[str, Any], T: list[float] | None = None,
                       name: str | None = None) -> dict[str, Any]:
    if src["id"] == doc["id"]:
        raise AssemblyInputError("An assembly can't contain itself.")
    if not src["instances"]:
        raise AssemblyInputError(f"{src['name']} is empty: add parts to it first.")
    if len(doc["instances"]) + len(src["instances"]) > MAX_INSTANCES:
        raise AssemblyInputError(f"An assembly can hold up to {MAX_INSTANCES} instances.")
    if T is None and doc["instances"]:  # beside what is there, like a part
        parts = _parts(root, doc)
        lo, hi = world_box(doc, parts)  # type: ignore[misc]
        sparts = _parts(root, src)
        slo, shi = world_box(src, sparts)  # type: ignore[misc]
        gap = max(10.0, 0.15 * float(np.linalg.norm(hi - lo)))
        T = xform.to12(xform.translate((hi[0] + gap - slo[0], (lo[1] + hi[1]) / 2 - (slo[1] + shi[1]) / 2,
                                        lo[2] - slo[2])))
    gid = store.next_id(doc, "s")
    g = {"id": gid, "kind": "subassembly", "name": (name or src["name"])[:120], "assembly_id": src["id"],
         "rev": None, "T": T or xform.to12(xform.ident())}
    doc.setdefault("subassemblies", []).append(g)
    sync_subassembly(root, doc, gid, src)
    if not any(i["fixed"] for i in doc["instances"]):
        first = next(i for i in doc["instances"] if i.get("sub") == gid)
        first["fixed"] = True
    return g


def sync_subassembly(root: Path, doc: dict[str, Any], gid: str, src: dict[str, Any]) -> dict[str, int]:
    """Copy (or re-copy) the source assembly into group ``gid``: the same parent ids for the same source
    instances, new ones added, vanished ones removed; internal mates and stacks re-copied. Returns counts."""
    g = subassembly(doc, gid)
    G = xform.from12(g["T"])
    mine = {i["src"]: i for i in doc["instances"] if i.get("sub") == gid and i.get("src")}
    src_ids = {i["id"] for i in src["instances"]}
    gone = [i["id"] for i in doc["instances"] if i.get("sub") == gid and i.get("src") not in src_ids]
    for iid in gone:
        doc["instances"] = [i for i in doc["instances"] if i["id"] != iid]
        doc["mates"] = [m for m in doc["mates"] if iid not in (m["a"]["inst"], m["b"]["inst"])]
    gmap: dict[str, str] = {}
    old_groups = {x.get("src"): x for x in doc["groups"] if x.get("sub") == gid}
    keep: list[str] = []
    for sg in src.get("groups") or []:
        pg = old_groups.get(sg["id"])
        if pg is None:
            pg = {**sg, "id": store.next_id(doc, "g"), "sub": gid, "src": sg["id"]}
            doc["groups"].append(pg)
        else:
            pg.update({k: v for k, v in sg.items() if k != "id"})
            pg["sub"], pg["src"] = gid, sg["id"]
        gmap[sg["id"]] = pg["id"]
        keep.append(pg["id"])
    added = updated = 0
    imap: dict[str, str] = {}
    for si in src["instances"]:
        T = xform.to12(G @ xform.from12(si["T"]))
        pi = mine.get(si["id"])
        if pi is None:
            pi = {"id": store.next_id(doc, "i"), "fixed": False, "visible": True}
            doc["instances"].append(pi)
            added += 1
        elif pi["part"] != si["part"] or pi["T"] != T:
            updated += 1
        pi.update(name=si["name"], part=si["part"], source=si["source"], T=T, group=gmap.get(si.get("group") or ""),
                  sub=gid, src=si["id"])
        if si.get("office"):
            pi["office"] = si["office"]
        imap[si["id"]] = pi["id"]
    doc["groups"] = [x for x in doc["groups"] if x.get("sub") != gid or x["id"] in keep]
    for x in doc["groups"]:  # a stack's hole reference follows the copy
        if x.get("sub") == gid and x.get("hole") and x["hole"].get("inst") in imap:
            x["hole"] = {**x["hole"], "inst": imap[x["hole"]["inst"]]}
    doc["mates"] = [m for m in doc["mates"] if m.get("sub") != gid]
    for sm in src["mates"]:
        if sm["a"]["inst"] not in imap or sm["b"]["inst"] not in imap:
            continue
        doc["mates"].append({**sm, "id": store.next_id(doc, "m"), "sub": gid, "src": sm["id"],
                             "a": {**sm["a"], "inst": imap[sm["a"]["inst"]]},
                             "b": {**sm["b"], "inst": imap[sm["b"]["inst"]]},
                             "group": gmap.get(sm.get("group") or "")})
    g["rev"] = src.get("rev")
    return {"added": added, "updated": updated, "removed": len(gone)}


def remove_subassembly(doc: dict[str, Any], gid: str) -> None:
    subassembly(doc, gid)
    ids = {i["id"] for i in doc["instances"] if i.get("sub") == gid}
    doc["instances"] = [i for i in doc["instances"] if i["id"] not in ids]
    doc["mates"] = [m for m in doc["mates"] if m["a"]["inst"] not in ids and m["b"]["inst"] not in ids]
    doc["groups"] = [g for g in doc["groups"] if g.get("sub") != gid]
    doc["subassemblies"] = [g for g in doc.get("subassemblies") or [] if g["id"] != gid]
    if doc["instances"] and not any(i["fixed"] for i in doc["instances"]):
        doc["instances"][0]["fixed"] = True


# ----------------------------------------------------------------------------- motion (ASM-011)
def _axis_world(root: Path, doc: dict[str, Any], body: dict[str, Any]) -> tuple[list[float], list[float]]:
    """The axis of a new joint in the assembly frame: a concentric mate's axis, a picked cylindrical face /
    circular edge, or an explicit point + direction."""
    ref = None
    if body.get("from_mate"):
        m = next((x for x in doc["mates"] if x["id"] == body["from_mate"]), None)
        if m is None or m["type"] != "concentric":
            raise AssemblyInputError("Pick a concentric mate: its axis becomes the joint axis.")
        ref = m["a"]
    elif body.get("ref"):
        ref = resolve_ref(root, doc, body["ref"])
    if ref is not None:
        r = ref["ref"]
        if r.get("kind") != "axis":
            raise AssemblyInputError("Pick a cylindrical face or a circular edge for the axis.")
        T = xform.from12(_inst(doc, ref["inst"])["T"])
        return [float(x) for x in xform.pt(T, r["p"])], [float(x) for x in xform.unit(xform.vec(T, r["v"]))]
    return list(body.get("p") or [0, 0, 0]), list(body.get("dir") or [0, 0, 1])


def _gear_teeth(root: Path, doc: dict[str, Any], j: dict[str, Any]) -> int | None:
    parts = _parts(root, doc)
    for iid in j.get("insts") or []:
        part = parts[_inst(doc, iid)["part"]]
        if part.get("kind") == "toolbox" and part.get("code") == "spur_gear" and (part.get("params") or {}).get("Z"):
            return int(part["params"]["Z"])
        comp = (part.get("info") or {}).get("component") or {}
        if comp.get("kind") == "spur_gear" and (comp.get("params") or {}).get("teeth"):
            return int(comp["params"]["teeth"])
    return None


def add_joint(root: Path, doc: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    from aicad.assembly import motion

    joints = doc.setdefault("joints", [])
    if len(joints) >= motion.MAX_JOINTS:
        raise AssemblyInputError(f"An assembly can hold up to {motion.MAX_JOINTS} joints.")
    body = dict(body)
    if body.get("type") in ("revolute", "slider"):
        p, d = _axis_world(root, doc, body)
        body["p"], body["dir"] = p, d
    elif body.get("type") == "gear" and not body.get("teeth") and not body.get("ratio"):
        by = {x["id"]: x for x in joints}
        if body.get("a") not in by or body.get("b") not in by:
            raise AssemblyInputError("A gear pair couples two different revolute joints.")
        za = _gear_teeth(root, doc, by.get(body.get("a"), {}))
        zb = _gear_teeth(root, doc, by.get(body.get("b"), {}))
        if not za or not zb:
            raise AssemblyInputError("No gear teeth found on the parts of one of the joints: enter the tooth counts.")
        body["teeth"] = [za, zb]
    j = motion.clean_joint(body, {i["id"] for i in doc["instances"]}, joints)
    j["id"] = store.next_id(doc, "j")
    joints.append(j)
    return j


def delete_joint(doc: dict[str, Any], jid: str) -> None:
    joints = doc.get("joints") or []
    if not any(j["id"] == jid for j in joints):
        raise AssemblyInputError("Joint not found")
    doc["joints"] = [j for j in joints if j["id"] != jid and not (j["type"] == "gear" and jid in (j["a"], j["b"]))]


async def motion_check(root: Path, org_id: str, doc: dict[str, Any], joints: list[dict[str, Any]] | None = None,
                       driver: str | None = None, start: float | None = None, end: float | None = None,
                       steps: int | None = None, save: bool = True) -> dict[str, Any]:
    """Sweep the driving joint through its range and check collisions at every step (worker, exact booleans
    behind box screening). ``joints`` default: the document's own."""
    from aicad.assembly import motion

    joints = joints if joints is not None else (doc.get("joints") or [])
    live = {i["id"] for i in doc["instances"]}
    joints = [j if j["type"] == "gear" else {**j, "insts": [x for x in j["insts"] if x in live]} for j in joints]
    pl = motion.plan({i["id"]: i["T"] for i in doc["instances"]}, joints, driver, start, end,
                     steps or motion.DEFAULT_STEPS)
    insts = worker_instances(root, doc)
    body = {k: v for k, v in motion.bodies(joints).items() if k in live}
    res = await _call(org_id, {"op": "motion", "instances": insts, "body": body,
                               "steps": [{"i": s["i"], "T": s["T"]} for s in pl["steps"]]}, timeout=1200)
    out = motion.summarize(pl, res, display_names(doc))
    out.update(signature=geometry_signature(doc), at=store.now(), joints=joints)
    if save:
        store.write_json(store.doc_dir(root, doc["id"]) / "motion.json", out)
    return out
