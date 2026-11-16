"""Mate solver and degrees-of-freedom analysis over rigid instance placements.

Each mate contributes residual equations on the world geometry of two references (a plane: point + outward normal;
an axis: point + direction). Free instances get six variables each (rotation about their own reference point and a
translation, rotations scaled by the assembly length L so every column is in millimetres). A damped Gauss-Newton
(Levenberg-Marquardt) iteration drives the residuals to zero from the current placements, so parts move as little
as possible. Everything is deterministic: fixed iteration order, no randomness.

Honesty about the state:
- conflicting mates (residual left after the solve) are isolated by re-adding mates one at a time in creation
  order; a mate that cannot be satisfied together with the earlier ones is reported as a conflict and its
  equations are not applied (the assembly keeps the placement the consistent mates give);
- remaining freedom comes from the rank of the constraint Jacobian at the solution (SVD): DOF = 6 n - rank, and per
  instance the rank of its block of the null space. A single remaining rotation about a concentric axis is labelled
  as a free spin (normal for fasteners and shafts).

Equation counts per mate (independent constraints when the mate stands alone): coincident / flush / distance 3
(normals aligned: 2, plane offset: 1), concentric 4 (axes parallel: 2, on line: 2), angle 1 (2 at 0° / 180°).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from aicad.assembly import xform

PLANE_MATES = ("coincident", "flush", "distance", "angle")
AXIS_MATES = ("concentric",)
MATE_TYPES = PLANE_MATES + AXIS_MATES
NEEDS = {"coincident": "plane", "flush": "plane", "distance": "plane", "angle": "plane", "concentric": "axis"}
LABEL = {"coincident": "Coincident", "flush": "Flush", "distance": "Distance", "angle": "Angle",
         "concentric": "Concentric"}
TOL_MM = 1e-6       # a mate is satisfied when its positional residual is below this (mm)
TOL_RAD = 1e-7      # ... and its angular residual below this (rad)
H = 1e-6            # finite-difference step (scaled variables, mm)


@dataclass(frozen=True)
class Ref:
    kind: str                 # "plane" | "axis"
    p: tuple[float, float, float]
    v: tuple[float, float, float]   # plane: outward normal; axis: direction
    r: float | None = None    # axis radius when it comes from a cylinder / circle

    @staticmethod
    def of(d: dict[str, Any]) -> Ref:
        v = xform.unit(d["v"])
        return Ref(str(d["kind"]), tuple(float(x) for x in d["p"]), tuple(float(x) for x in v),  # type: ignore[arg-type]
                   None if d.get("r") is None else float(d["r"]))


@dataclass
class MateSpec:
    id: str
    type: str
    a: str
    ra: Ref
    b: str
    rb: Ref
    value: float = 0.0        # distance (mm) or angle (deg)
    flip: bool = False        # plane mates: aligned instead of anti-aligned; concentric: reverse the axis

    def eqs(self) -> int:
        if self.type == "concentric":
            return 4
        if self.type == "angle":
            return 2 if self._parallel() else 1
        return 3

    def _parallel(self) -> bool:
        th = self.angle_rad()
        return th < 1e-9 or th > math.pi - 1e-9

    def angle_rad(self) -> float:
        th = math.radians(self.value)
        return math.pi - th if self.flip else th

    def aligned(self) -> bool:
        return (self.type == "flush") != bool(self.flip)


@dataclass
class Inst:
    id: str
    T: np.ndarray
    fixed: bool = False
    ref_point: tuple[float, float, float] = (0.0, 0.0, 0.0)   # local point the instance rotates about (bbox centre)


@dataclass
class MateState:
    id: str
    ok: bool
    residual_mm: float
    residual_deg: float
    conflict: bool = False


@dataclass
class InstState:
    id: str
    dof: int
    rot: int
    trans: int
    spin: bool = False        # the only freedom is a spin about a concentric axis
    fixed: bool = False
    over: bool = False        # involved in a conflicting mate


@dataclass
class Result:
    poses: dict[str, np.ndarray]
    mates: dict[str, MateState]
    insts: dict[str, InstState]
    dof: int
    redundant: int
    conflicts: list[str] = field(default_factory=list)
    iterations: int = 0
    status: str = "fully_defined"   # fully_defined | under_defined | over_defined

    def as_dict(self) -> dict[str, Any]:
        spins = sum(1 for s in self.insts.values() if s.spin)
        return {
            "status": self.status, "dof": self.dof, "redundant": self.redundant, "conflicts": self.conflicts,
            "free_spins": spins, "iterations": self.iterations,
            "mates": {k: {"ok": v.ok, "residual_mm": v.residual_mm, "residual_deg": v.residual_deg,
                          "conflict": v.conflict} for k, v in self.mates.items()},
            "instances": {k: {"dof": v.dof, "rot": v.rot, "trans": v.trans, "spin": v.spin, "fixed": v.fixed,
                              "over": v.over} for k, v in self.insts.items()},
        }


# ----------------------------------------------------------------------------- geometry
def world(T: np.ndarray, ref: Ref) -> tuple[np.ndarray, np.ndarray]:
    return xform.pt(T, ref.p), xform.vec(T, ref.v)


def residual(m: MateSpec, Ta: np.ndarray, Tb: np.ndarray, L: float) -> np.ndarray:
    pa, va = world(Ta, m.ra)
    pb, vb = world(Tb, m.rb)
    if m.type == "concentric":
        par = L * np.cross(va, vb)
        d = pb - pa
        off = d - va * float(d @ va)
        return np.concatenate([par, off])
    if m.type == "angle":
        th = m.angle_rad()
        if th < 1e-9:
            return L * (va - vb)
        if th > math.pi - 1e-9:
            return L * (va + vb)
        return np.array([L * (float(va @ vb) - math.cos(th))])
    gap = m.value if m.type == "distance" else 0.0
    rn = L * (va - vb) if m.aligned() else L * (va + vb)
    return np.concatenate([rn, [float((pb - pa) @ va) - gap]])


def mate_error(m: MateSpec, Ta: np.ndarray, Tb: np.ndarray) -> tuple[float, float]:
    """(positional error mm, angular error deg) of a mate at the given placements."""
    pa, va = world(Ta, m.ra)
    pb, vb = world(Tb, m.rb)
    if m.type == "concentric":
        ang = math.asin(min(1.0, float(np.linalg.norm(np.cross(va, vb)))))
        d = pb - pa
        return float(np.linalg.norm(d - va * float(d @ va))), math.degrees(ang)
    c = float(np.clip(va @ vb, -1.0, 1.0))
    if m.type == "angle":
        return 0.0, abs(math.degrees(math.acos(c)) - math.degrees(m.angle_rad()))
    target = 1.0 if m.aligned() else -1.0
    ang = math.degrees(math.acos(float(np.clip(c * target, -1.0, 1.0))))
    gap = m.value if m.type == "distance" else 0.0
    return abs(float((pb - pa) @ va) - gap), ang


def _delta(x: np.ndarray, c: np.ndarray, L: float) -> np.ndarray:
    R = xform.exp_so3(x[:3] / L)
    return xform.make(R, c - R @ c + x[3:])


# ----------------------------------------------------------------------------- core
class _Problem:
    def __init__(self, insts: dict[str, Inst], mates: list[MateSpec], L: float) -> None:
        self.insts = insts
        self.mates = mates
        self.L = L
        involved = sorted({m.a for m in mates} | {m.b for m in mates}, key=list(insts).index)
        self.free = [i for i in involved if not insts[i].fixed]
        self.col = {iid: 6 * k for k, iid in enumerate(self.free)}
        self.rows = []
        r0 = 0
        for m in mates:
            n = len(residual(m, insts[m.a].T, insts[m.b].T, L))
            self.rows.append((r0, n))
            r0 += n
        self.m = r0
        self.n = 6 * len(self.free)

    def centre(self, iid: str, poses: dict[str, np.ndarray]) -> np.ndarray:
        return xform.pt(poses[iid], self.insts[iid].ref_point)

    def r(self, poses: dict[str, np.ndarray]) -> np.ndarray:
        if not self.mates:
            return np.zeros(0)
        return np.concatenate([residual(m, poses[m.a], poses[m.b], self.L) for m in self.mates])

    def jac(self, poses: dict[str, np.ndarray]) -> np.ndarray:
        J = np.zeros((self.m, self.n))
        for (r0, n), m in zip(self.rows, self.mates, strict=True):
            for side in ("a", "b"):
                iid = getattr(m, side)
                if iid not in self.col or (side == "b" and m.a == m.b):
                    continue
                c = self.centre(iid, poses)
                c0 = self.col[iid]
                for j in range(6):
                    e = np.zeros(6)
                    e[j] = H
                    vals = []
                    for s in (1.0, -1.0):
                        p = dict(poses)
                        p[iid] = _delta(s * e, c, self.L) @ poses[iid]
                        vals.append(residual(m, p[m.a], p[m.b], self.L))
                    J[r0:r0 + n, c0 + j] += (vals[0] - vals[1]) / (2 * H)
        return J

    def step(self, poses: dict[str, np.ndarray], dx: np.ndarray) -> dict[str, np.ndarray]:
        out = dict(poses)
        for iid, c0 in self.col.items():
            out[iid] = xform.orthonormalize(_delta(dx[c0:c0 + 6], self.centre(iid, poses), self.L) @ poses[iid])
        return out


def _lm(prob: _Problem, poses: dict[str, np.ndarray], iters: int = 80) -> tuple[dict[str, np.ndarray], int]:
    if not prob.n or not prob.m:
        return poses, 0
    lam = 1e-6
    r = prob.r(poses)
    cost = float(r @ r)
    it = 0
    for it in range(1, iters + 1):
        if float(np.max(np.abs(r))) < 1e-10:
            break
        J = prob.jac(poses)
        g = J.T @ r
        A = J.T @ J
        improved = False
        dx = np.zeros(prob.n)
        for _ in range(12):
            try:
                dx = np.linalg.solve(A + lam * np.diag(np.maximum(np.diag(A), 1e-9)) + lam * np.eye(prob.n), -g)
            except np.linalg.LinAlgError:
                lam *= 10
                continue
            cand = prob.step(poses, dx)
            rc = prob.r(cand)
            cc = float(rc @ rc)
            if cc < cost:
                poses, r, cost = cand, rc, cc
                lam = max(lam / 4, 1e-12)
                improved = True
                break
            lam *= 8
        if not improved or float(np.linalg.norm(dx)) < 1e-14:
            break
    return poses, it


def _satisfied(m: MateSpec, poses: dict[str, np.ndarray]) -> tuple[bool, float, float]:
    e_mm, e_deg = mate_error(m, poses[m.a], poses[m.b])
    return e_mm < TOL_MM and math.radians(e_deg) < TOL_RAD, e_mm, e_deg


def prealign(m: MateSpec, poses: dict[str, np.ndarray], mover: str) -> np.ndarray:
    """Move one instance so this mate alone is satisfied, with the smallest motion (used when a mate is first
    added, so the iterative solve starts on the right side: e.g. faces facing each other, not back to back)."""
    other = m.a if mover == m.b else m.b
    rm = m.rb if mover == m.b else m.ra
    ro = m.ra if mover == m.b else m.rb
    T = poses[mover]
    po, vo = world(poses[other], ro)
    pm, vm = world(T, rm)
    if m.type == "concentric":
        target = vo if float(vm @ vo) >= 0 else -vo
        if m.flip:
            target = -target
        T = xform.about(xform.min_rot(vm, target), pm) @ T
        pm, vm = world(T, rm)
        d = pm - po
        T = xform.translate(-(d - vo * float(d @ vo))) @ T
        return T
    if m.type == "angle":
        th = m.angle_rad()
        axis = np.cross(vo, vm)
        if float(np.linalg.norm(axis)) < 1e-9:
            axis = xform.perp(vo)
        cur = math.acos(float(np.clip(vo @ vm, -1, 1)))
        if mover == m.b:
            return xform.about(xform.rot(axis, th - cur), pm) @ T
        return xform.about(xform.rot(axis, cur - th), pm) @ T
    target = vo if m.aligned() else -vo
    T = xform.about(xform.min_rot(vm, target), pm) @ T
    pm, _vm = world(T, rm)
    gap = m.value if m.type == "distance" else 0.0
    # plane offset is measured along a's normal: (pb - pa)·na = gap
    if mover == m.b:
        err = float((pm - po) @ vo) - gap
        return xform.translate(-err * vo) @ T
    na = vm
    err = float((po - pm) @ na) - gap
    return xform.translate(err * na) @ T


def _analyse(prob: _Problem, poses: dict[str, np.ndarray], all_ids: Iterable[str]) -> tuple[dict[str, InstState], int, int]:
    insts = prob.insts
    states: dict[str, InstState] = {}
    rank = 0
    null = np.zeros((prob.n, 0))
    if prob.n:
        if prob.m:
            J = prob.jac(poses)
            s = np.linalg.svd(J, compute_uv=False)
            tol = 1e-6 * max(1.0, float(s[0]) if s.size else 1.0)
            rank = int(np.sum(s > tol))
            _u, _s, Vt = np.linalg.svd(J)
            null = Vt[rank:].T
        else:
            null = np.eye(prob.n)
    eqs = sum(m.eqs() for m in prob.mates)
    redundant = max(0, eqs - rank)
    for iid in all_ids:
        inst = insts[iid]
        if inst.fixed:
            states[iid] = InstState(iid, 0, 0, 0, fixed=True)
            continue
        if iid not in prob.col:
            states[iid] = InstState(iid, 6, 3, 3)
            continue
        c0 = prob.col[iid]
        B = null[c0:c0 + 6, :]

        def rk(M: np.ndarray) -> int:
            if M.size == 0:
                return 0
            sv = np.linalg.svd(M, compute_uv=False)
            return int(np.sum(sv > 1e-6))

        dof, rot, trans = rk(B), rk(B[:3]), rk(B[3:])
        spin = False
        if dof == 1:
            U, _sv, _vt = np.linalg.svd(B)
            v = U[:, 0]
            w = v[:3] / prob.L
            if float(np.linalg.norm(w)) > 1e-9:
                c = prob.centre(iid, poses)
                for m in prob.mates:
                    if m.type != "concentric" or iid not in (m.a, m.b):
                        continue
                    p, d = world(poses[iid], m.ra if m.a == iid else m.rb)
                    wn = w / np.linalg.norm(w)
                    vel = np.cross(w, p - c) + v[3:]
                    if abs(abs(float(wn @ d)) - 1) < 1e-6 and float(np.linalg.norm(vel)) < 1e-6 * max(1.0, float(np.linalg.norm(v))):
                        spin = True
                        break
        states[iid] = InstState(iid, dof, rot, trans, spin=spin)
    return states, rank, redundant


def solve(insts: dict[str, Inst], mates: list[MateSpec], L: float = 100.0,
          prealign_ids: Iterable[str] = ()) -> Result:
    """Solve all mates from the current placements. ``prealign_ids``: mates just added (pre-aligned first when
    their moving instance has no other mates)."""
    L = max(float(L), 1.0)
    poses = {k: v.T.copy() for k, v in insts.items()}
    for mid in prealign_ids:
        m = next((x for x in mates if x.id == mid), None)
        if m is None:
            continue
        mover = _mover(m, insts, mates, poses)
        if mover is not None:
            poses[mover] = prealign(m, poses, mover)
    for m in mates:
        if m.a == m.b:
            raise ValueError("a mate needs two different instances")
    prob = _Problem(insts, mates, L)
    poses, its = _lm(prob, poses)
    conflicts: list[str] = []
    if not all(_satisfied(m, poses)[0] for m in mates):
        # isolate conflicts: add mates one at a time in creation order
        poses = {k: v.T.copy() for k, v in insts.items()}
        keep: list[MateSpec] = []
        for m in mates:
            trial = keep + [m]
            p1, k1 = _lm(_Problem(insts, trial, L), poses)
            its += k1
            if not all(_satisfied(x, p1)[0] for x in trial):
                mover = _mover(m, insts, keep, poses)
                if mover is not None:
                    p2 = dict(poses)
                    p2[mover] = prealign(m, p2, mover)
                    p1, k1 = _lm(_Problem(insts, trial, L), p2)
                    its += k1
            if all(_satisfied(x, p1)[0] for x in trial):
                keep, poses = trial, p1
            else:
                conflicts.append(m.id)
        prob = _Problem(insts, keep, L)
    states, _rank, redundant = _analyse(prob, poses, list(insts))
    mstates: dict[str, MateState] = {}
    for m in mates:
        ok, e_mm, e_deg = _satisfied(m, poses)
        mstates[m.id] = MateState(m.id, ok and m.id not in conflicts, round(e_mm, 9), round(e_deg, 9),
                                  conflict=m.id in conflicts)
        if m.id in conflicts:
            for iid in (m.a, m.b):
                states[iid].over = True
    free_dof = sum(s.dof for s in states.values())
    status = "over_defined" if conflicts else ("fully_defined" if free_dof == 0 else "under_defined")
    return Result(poses=poses, mates=mstates, insts=states, dof=free_dof, redundant=redundant, conflicts=conflicts,
                  iterations=its, status=status)


def _mover(m: MateSpec, insts: dict[str, Inst], mates: list[MateSpec], poses: dict[str, np.ndarray]) -> str | None:
    """Instance to pre-align for a new mate: the second pick unless it is fixed; never one already held by other
    mates (that would break them; the iterative solve handles those)."""
    del poses
    for cand in (m.b, m.a):
        if insts[cand].fixed:
            continue
        others = [x for x in mates if x.id != m.id and cand in (x.a, x.b)]
        if not others:
            return cand
    return None
