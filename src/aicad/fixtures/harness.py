"""ASM-012 golden assembly fixtures: the shared harness that rebuilds a fixture and runs its deterministic checks.

A fixture module (``fx04_bolted_bracket`` ...) declares, from its parameters and hand formulas only:
- parts: a build function (parametric build123d / Toolbox generator), the hand bounding box, and the hand mass
  decomposition (signed volumes with their centroids, local frame) whose sum is the hand volume;
- instances: the hand placement of each (``T``) and a perturbed start placement (``start``) the mate solver must
  recover from; which instances keep a free spin (``free_axis``) or are judged relative to another (``rel_to``);
- mates (solver references in each part's local frame), the hand DOF count, intended contacts and clearances
  (hand minimum distances), the expected BOM, joints and motion cases with the hand collision prediction.

``run`` builds every part, checks it (CHK-02/03 valid closed solid, CHK-04 bbox, CHK-05 volume vs the hand sum),
exports STEP, solves the mates from the start placements, compares the solved placements with the hand ones, runs
the exact interference check, measures the listed minimum distances, compares kernel mass and centre of mass with
the hand values (at the hand placements), builds the BOM and sweeps the motion cases. Every check is
deterministic; nothing here renders, and passing says nothing about manufacturability.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from aicad import materials
from aicad.assembly import xform

POSE_TOL_MM = 1e-4
POSE_TOL_DIR = 1e-6
DIST_TOL_MM = 1e-4
MASS_REL_TOL = 1e-4
COM_TOL_MM = 1e-3
INTERFERENCE_VOL_TOL = 1e-6   # mm³; same as the Assembly Studio check


@dataclass(frozen=True)
class Feat:
    """A signed volume (mm³, negative = removed) and its centroid in the part frame (mm)."""
    vol: float
    c: tuple[float, float, float]


@dataclass
class PartDef:
    key: str
    name: str
    material: str                      # materials.py code (density source)
    build: Callable[[], Any]           # -> build123d shape (labelled)
    bbox: tuple[float, float, float]   # hand bounding-box size
    feats: list[Feat]                  # hand mass decomposition
    solids: int = 1
    kind: str = "fixture"              # fixture | toolbox
    standard: str | None = None
    designation: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)   # interference metadata (thread / envelope)

    @property
    def volume(self) -> float:
        return sum(f.vol for f in self.feats)


@dataclass
class InstDef:
    id: str
    part: str
    T: np.ndarray                      # hand placement (part frame -> assembly frame)
    start: np.ndarray                  # where the solver starts
    fixed: bool = False
    free_axis: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None  # local spin axis
    rel_to: str | None = None          # judged relative to this instance (a keyed group that spins as one)


@dataclass
class Fixture:
    id: str
    title: str
    params: dict[str, Any]
    parts: dict[str, PartDef]
    insts: list[InstDef]
    mates: list[dict[str, Any]]
    dof: int                                       # hand count of remaining freedoms
    contacts: list[tuple[str, str, float, str]]    # (a, b, hand minimum distance mm, why)
    bom: list[tuple[str, int]]                     # (part name, qty) in item order
    allowed_thread: list[tuple[str, str]] = field(default_factory=list)  # bolt-in-nut pairs (cosmetic threads)
    joints: list[dict[str, Any]] = field(default_factory=list)
    motion: list[dict[str, Any]] = field(default_factory=list)  # {name, driver, start, end, steps, collide: [values]}
    extra: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None


def perturb(T: np.ndarray, k: int) -> np.ndarray:
    """A deterministic start placement near ``T``: a few mm and a few degrees away (instance number ``k``)."""
    t = np.array([3.0 + k % 3, -2.0 - (k % 2), 4.0 + (k % 4)])
    axis = [1.0, 0.6 + 0.1 * (k % 3), 0.3]
    R = xform.rot(axis, math.radians(4.0 + k % 3))
    c = T[:3, 3]
    M = xform.translate(t) @ xform.about(R, c)
    return M @ T


# ------------------------------------------------------------------ helpers
def _check(cid: str, name: str, passed: bool, **detail: Any) -> dict[str, Any]:
    return {"id": cid, "name": name, "passed": bool(passed), "gating": True, "detail": detail}


def _rho_g_mm3(code: str) -> float:
    m = materials.get(code)
    if m is None:
        raise ValueError(f"unknown material code {code}")
    return float(m["density_g_cm3"]) / 1000.0  # type: ignore[arg-type]


def hand_mass(fx: Fixture) -> tuple[float, np.ndarray]:
    """(mass g, centre of mass mm) from the hand decompositions at the hand placements."""
    parts = fx.parts
    m = 0.0
    mc = np.zeros(3)
    for i in fx.insts:
        p = parts[i.part]
        rho = _rho_g_mm3(p.material)
        for f in p.feats:
            m += f.vol * rho
            mc += f.vol * rho * xform.pt(i.T, f.c)
    return m, mc / m


def _world(shape: Any, T: np.ndarray) -> Any:
    from aicad.assembly.geometry import _loc

    return shape.moved(_loc(T))


def _kernel_mass(shapes: dict[str, Any], fx: Fixture) -> tuple[float, np.ndarray]:
    from build123d import CenterOf

    m = 0.0
    mc = np.zeros(3)
    for i in fx.insts:
        rho = _rho_g_mm3(fx.parts[i.part].material)
        w = _world(shapes[i.part], i.T)
        for s in w.solids():
            v = s.volume
            c = s.center(CenterOf.MASS)
            m += v * rho
            mc += v * rho * np.array([c.X, c.Y, c.Z])
    return m, mc / m


def _ref(d: dict[str, Any]) -> Any:
    from aicad.assembly.solver import Ref

    return Ref.of(d)


def bom_rows(fx: Fixture) -> list[dict[str, Any]]:
    """BOM in instance order of first use: item, qty, part, kind, standard / designation, material, hand mass."""
    order: list[str] = []
    qty: dict[str, int] = {}
    for i in fx.insts:
        if i.part not in qty:
            order.append(i.part)
        qty[i.part] = qty.get(i.part, 0) + 1
    rows = []
    for n, key in enumerate(order, start=1):
        p = fx.parts[key]
        m = materials.get(p.material) or {}
        each = p.volume * _rho_g_mm3(p.material)
        rows.append({"item": n, "qty": qty[key], "part": p.name, "kind": p.kind, "standard": p.standard,
                     "designation": p.designation, "material": m.get("name"), "mass_each_g": round(each, 3),
                     "mass_total_g": round(each * qty[key], 3)})
    return rows


# ------------------------------------------------------------------ the run
def build_parts(fx: Fixture) -> dict[str, Any]:
    from aicad import fw

    shapes = {}
    for key, p in fx.parts.items():
        fw.reset()
        shapes[key] = p.build()
    fw.reset()
    return shapes


def run(fx: Fixture, workdir: Path, *, motion: bool = True) -> dict[str, Any]:
    """Rebuild the fixture in ``workdir`` and run every check. Returns the report (``passed`` = all checks)."""
    from build123d import export_step

    from aicad import checks
    from aicad.assembly import geometry, solver
    from aicad.assembly import motion as mo

    workdir.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    shapes = build_parts(fx)

    # 1. parts: valid closed solids, hand bbox and hand volume
    steps: dict[str, Path] = {}
    for key, p in fx.parts.items():
        s = shapes[key]
        for r in checks.check_solid(s, p.solids):
            out.append(_check(f"{key}/{r.id}", f"{p.name}: {r.name}", r.passed, **r.detail))
        r = checks.check_bbox(s, p.bbox)
        out.append(_check(f"{key}/{r.id}", f"{p.name}: {r.name}", r.passed, **r.detail))
        rel = abs(s.volume - p.volume) / p.volume
        out.append(_check(f"{key}/CHK-05", f"{p.name}: volume vs hand sum", rel <= 1e-6, got_mm3=s.volume,
                          hand_mm3=p.volume, rel_err=rel, tol=1e-6))
        f = workdir / f"{key}.step"
        export_step(s, str(f))
        steps[key] = f

    # 2. mates solved from the perturbed start placements
    insts = {}
    for i in fx.insts:
        bb = shapes[i.part].bounding_box()
        c = bb.center()
        insts[i.id] = solver.Inst(i.id, i.start.copy(), fixed=i.fixed, ref_point=(c.X, c.Y, c.Z))
    mates = [solver.MateSpec(m["id"], m["type"], m["a"], _ref(m["ra"]), m["b"], _ref(m["rb"]),
                             float(m.get("value", 0.0)), bool(m.get("flip", False))) for m in fx.mates]
    size = max(max(p.bbox) for p in fx.parts.values())
    res = solver.solve(insts, mates, L=size)
    bad = [k for k, v in res.mates.items() if not v.ok]
    out.append(_check("ASM/mates", "every mate solved (no conflicts)", not bad and not res.conflicts,
                      unsatisfied=bad, conflicts=res.conflicts, status=res.status, iterations=res.iterations))
    # freedoms of the mechanism = null space of the mate Jacobian: 6 per free instance minus its rank (the solver's
    # own ``dof`` sums freedoms per instance, so a keyed group that spins as one counts once per member there)
    rank = sum(m.eqs() for m in mates) - res.redundant
    nullity = 6 * sum(1 for i in fx.insts if not i.fixed) - rank
    out.append(_check("ASM/dof", "remaining freedoms = hand count", nullity == fx.dof, freedoms=nullity, hand=fx.dof,
                      per_instance_sum=res.dof, free_spins=res.as_dict()["free_spins"]))
    pose_err: dict[str, float] = {}
    for i in fx.insts:
        S = res.poses[i.id]
        if i.rel_to is not None:
            got = xform.inv(res.poses[i.rel_to]) @ S
            want = xform.inv(next(x.T for x in fx.insts if x.id == i.rel_to)) @ i.T
            err = float(np.max(np.abs(got - want)))
        elif i.free_axis is not None:
            p, d = i.free_axis
            D = xform.inv(i.T) @ S  # must be a turn about the local spin axis
            err = max(float(np.linalg.norm(xform.pt(D, p) - np.asarray(p))),
                      float(np.linalg.norm(xform.vec(D, d) - np.asarray(d))))
        else:
            err = float(np.max(np.abs(S - i.T)))
        pose_err[i.id] = err
    worst = max(pose_err.values())
    out.append(_check("ASM/poses", "solved placements = hand placements (free spins excepted)",
                      worst <= POSE_TOL_MM, worst=worst, per_instance={k: round(v, 9) for k, v in pose_err.items()},
                      tol=POSE_TOL_MM))

    # 3. interference at the solved placements
    def rows_at(poses: dict[str, np.ndarray]) -> list[dict[str, Any]]:
        rows = []
        for i in fx.insts:
            bb = shapes[i.part].bounding_box()
            row = {"id": i.id, "step": str(steps[i.part]), "T": xform.to12(poses[i.id]),
                   "bbox": [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z]}
            row.update(fx.parts[i.part].meta)
            rows.append(row)
        return rows

    solved_rows = rows_at(res.poses)
    itf = geometry.interference(solved_rows, vol_tol=INTERFERENCE_VOL_TOL)
    clashes = [(r["a"], r["b"], r["volume_mm3"]) for r in itf["pairs"] if r["kind"] == "interference"]
    allowed = {tuple(sorted(x)) for x in fx.allowed_thread}
    threads = [tuple(sorted((r["a"], r["b"]))) for r in itf["pairs"] if r["kind"] == "thread"]
    out.append(_check("ASM/interference", "no interference (contacts only)", not clashes, clashes=clashes,
                      checked_pairs=itf["checked_pairs"]))
    out.append(_check("ASM/threads", "thread engagement only where intended", all(t in allowed for t in threads),
                      thread_pairs=threads, allowed=sorted(allowed)))

    # 4. intended contacts and clearances (hand minimum distances)
    by_id = {i.id: i for i in fx.insts}
    dists = []
    for a, b, want, why in fx.contacts:
        sa = _world(shapes[by_id[a].part], res.poses[a])
        sb = _world(shapes[by_id[b].part], res.poses[b])
        got, _, _ = geometry.min_distance(sa, sb)
        dists.append({"a": a, "b": b, "got_mm": round(got, 9), "hand_mm": want, "why": why,
                      "ok": abs(got - want) <= DIST_TOL_MM})
    out.append(_check("ASM/contacts", "contacts and clearances = hand minimum distances",
                      all(d["ok"] for d in dists), pairs=dists, tol=DIST_TOL_MM))

    # 5. mass properties (hand placements: free spins change nothing that is checked here)
    hm, hc = hand_mass(fx)
    km, kc = _kernel_mass(shapes, fx)
    out.append(_check("ASM/mass", "assembly mass = hand value", abs(km - hm) / hm <= MASS_REL_TOL,
                      kernel_g=round(km, 6), hand_g=round(hm, 6), rel_err=abs(km - hm) / hm, tol=MASS_REL_TOL))
    cerr = float(np.linalg.norm(kc - hc))
    out.append(_check("ASM/com", "centre of mass = hand value", cerr <= COM_TOL_MM,
                      kernel_mm=[round(float(x), 6) for x in kc], hand_mm=[round(float(x), 6) for x in hc],
                      err_mm=cerr, tol=COM_TOL_MM))

    # 6. BOM
    bom = bom_rows(fx)
    got_bom = [(r["part"], r["qty"]) for r in bom]
    out.append(_check("ASM/bom", "BOM rows and quantities = expected", got_bom == list(fx.bom), got=got_bom,
                      expected=list(fx.bom)))

    # 7. motion range (design placements: the joint's zero is the hand pose)
    motion_out = []
    if motion and fx.joints:
        design_rows = rows_at({i.id: i.T for i in fx.insts})
        T0 = {r["id"]: r["T"] for r in design_rows}
        for case in fx.motion:
            pl = mo.plan(T0, fx.joints, case.get("driver"), case["start"], case["end"], case["steps"])
            sw = mo.sweep(design_rows, mo.bodies(fx.joints), [{"i": s["i"], "T": s["T"]} for s in pl["steps"]],
                          worst_mesh=False)
            hit = [s["value"] for s, r in zip(pl["steps"], sw["steps"], strict=True) if r["collisions"]]
            want = [float(v) for v in case["collide"]]
            ok = len(hit) == len(want) and all(abs(a - b) < 1e-6 for a, b in zip(hit, want, strict=False))
            motion_out.append({"name": case["name"], "colliding_values": hit, "hand": want, "ok": ok,
                               "pairs": sorted({(c["a"], c["b"]) for r in sw["steps"] for c in r["collisions"]})})
            out.append(_check(f"ASM/motion/{case['name']}", f"motion sweep '{case['name']}': collisions where the "
                              "hand calculation predicts them", ok, colliding=hit, hand=want,
                              steps=len(pl["steps"])))

    ctx = {"fx": fx, "shapes": shapes, "poses": res.poses, "solve": res, "workdir": workdir}
    if fx.extra is not None:
        out.extend(fx.extra(ctx))
    return {"fixture": fx.id, "title": fx.title, "passed": all(c["passed"] for c in out), "checks": out,
            "solve": res.as_dict(), "interference": {"pairs": [{k: v for k, v in r.items() if k != "mesh"}
                                                               for r in itf["pairs"]],
                                                     "checked_pairs": itf["checked_pairs"]},
            "bom": bom, "mass": {"hand_g": round(hm, 4), "kernel_g": round(km, 4),
                                 "com_hand_mm": [round(float(x), 4) for x in hc]},
            "motion": motion_out}


# ------------------------------------------------------------------ the assembly definition file
def definition(fx: Fixture) -> dict[str, Any]:
    """The assembly definition as data (written to specs/fixtures/<fixture>/assembly.json)."""
    def r(v: float) -> float:
        return 0.0 if abs(v) < 1e-12 else round(float(v), 6)

    hm, hc = hand_mass(fx)
    return {
        "schema": "formwright.fixture-assembly/1", "fixture": fx.id, "title": fx.title, "units": "mm, g, degrees",
        "params": fx.params,
        "parts": [{"key": p.key, "name": p.name, "kind": p.kind, "standard": p.standard, "designation": p.designation,
                   "material": p.material, "params": p.params, "hand": {"bbox": [r(x) for x in p.bbox],
                                                                          "volume_mm3": r(p.volume),
                                                                          "solids": p.solids}}
                  for p in fx.parts.values()],
        "instances": [{"id": i.id, "part": i.part, "fixed": i.fixed, "T": [r(x) for x in xform.to12(i.T)],
                       "free_spin_axis": None if i.free_axis is None else [list(i.free_axis[0]), list(i.free_axis[1])],
                       "relative_to": i.rel_to} for i in fx.insts],
        "mates": fx.mates, "joints": fx.joints, "motion": fx.motion,
        "expected": {"dof": fx.dof, "interference": "none (contacts only)",
                     "thread_engagement": [list(x) for x in fx.allowed_thread],
                     "contacts": [{"a": a, "b": b, "min_distance_mm": d, "why": w} for a, b, d, w in fx.contacts],
                     "bom": [{"part": n, "qty": q} for n, q in fx.bom],
                     "mass_g": r(hm), "com_mm": [r(x) for x in hc]},
    }


def definition_json(fx: Fixture) -> str:
    return json.dumps(definition(fx), indent=1, ensure_ascii=False) + "\n"
