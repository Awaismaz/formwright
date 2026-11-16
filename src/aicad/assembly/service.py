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
    return {"kind": "toolbox", "code": p["code"], "params": p["params"], "version": p["version"]}


def remove_instance(doc: dict[str, Any], iid: str) -> None:
    _inst(doc, iid)
    doc["instances"] = [i for i in doc["instances"] if i["id"] != iid]
    doc["mates"] = [m for m in doc["mates"] if iid not in (m["a"]["inst"], m["b"]["inst"])]
    used = {i.get("group") for i in doc["instances"]}
    doc["groups"] = [g for g in doc["groups"] if g["id"] in used]
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


def remap_refs(root: Path, doc: dict[str, Any], iid: str, new_key: str) -> tuple[int, int]:
    """Point the mates of instance iid at the same geometry in a new part snapshot. Returns (kept, broken)."""
    new = store.refs(root, new_key)
    kept = broken = 0
    for m in doc["mates"]:
        for side in ("a", "b"):
            s = m[side]
            if s["inst"] != iid:
                continue
            pool = new["faces" if s["kind"] == "face" else "edges"]
            hit = pool.get(str(s["id"]))
            if hit is None or not _same(s["ref"], hit):
                hit_id = next((k for k, v in sorted(pool.items(), key=lambda kv: int(kv[0])) if _same(s["ref"], v)), None)
                if hit_id is None:
                    m["broken"] = True
                    broken += 1
                    continue
                s["id"] = int(hit_id)
                hit = pool[hit_id]
            s["ref"] = hit
            m["broken"] = False
            kept += 1
    return kept, broken


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
        if p["kind"] == "project":
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
                            else "Project part" if p["kind"] == "project" else toolbox.spec(p["code"]).name),
            "standard": p.get("standard") if p["kind"] == "toolbox" else None,
            "designation": p["name"] if p["kind"] == "toolbox" else None,
            "material": p.get("material"), "density_g_cm3": rho,
            "mass_each_g": None if each is None else round(each, 2),
            "mass_total_g": None if each is None else round(each * qty, 2),
            "instances": [i["id"] for i in groups[key]], "part_key": key})
    return {"rows": rows, "total_qty": sum(r["qty"] for r in rows), "total_mass_g": round(total, 2),
            "mass_unknown_qty": unknown,
            "note": "Masses use nominal densities for the stated materials (verify with your supplier). Toolbox "
                    "fasteners are modelled with cosmetic threads."}


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
        out.append(row)
    return out


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
    nodes = [{"id": i["id"], "part_label": parts[i["part"]]["name"], "instance": names[i["id"]],
              "step": str(store.part_dir(root, i["part"]) / "part.step"), "T": i["T"], "group": i.get("group"),
              "group_label": glabel.get(i.get("group") or "", None)} for i in doc["instances"]]
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
    if prop["kind"] == "through":
        wn = toolbox.WASHER[d][2] if "washer_nut" in items else 0.0
        need = wn + prop["length"]["protrusion"] + 0.0
        sp = pr["nut"].get("space")
        if sp is not None and sp < need - 1e-6:
            prop["warnings"].append(f"Nut side: only {sp:g} mm free for the washer, nut and bolt end ({need:g} mm needed).")


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
                              "spec": {k: prop[k] for k in ("summary", "designation", "size", "kind", "grip", "rule",
                                                             "clearance", "length", "warnings", "sources")}})
        _insert_stack(root, doc, h, keys, gid)
    if not made:
        raise AssemblyInputError(next((h["proposal"].get("error") for h in plan["holes"] if h["proposal"].get("error")),
                                      "No fastener could be fitted."))
    run_solve(root, doc)
    return {"inserted": made, "plan": plan}


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
