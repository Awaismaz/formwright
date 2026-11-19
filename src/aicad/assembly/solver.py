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
(normals aligned: 2, plane offset: 1), concentric 4 (axes parallel: 2, on line: 2), angle 1 (2 at 0° / 180°),
gear 3 (axes parallel: 2, distance between the axes = the centre distance: 1). A gear mesh mate holds two gear axes
(or the shafts carrying them) at the centre distance m(z1 + z2)/2; the turning ratio itself lives in the motion
joints (``motion.py``), since a mate fixes placement only.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from aicad.assembly import xform

PLANE_MATES = ("coincident", "flush", "distance", "angle")
AXIS_MATES = ("concentric", "gear")
MATE_TYPES = PLANE_MATES + AXIS_MATES
NEEDS = {"coincident": "plane", "flush": "plane", "distance": "plane", "angle": "plane", "concentric": "axis",
         "gear": "axis"}
LABEL = {"coincident": "Coincident", "flush": "Flush", "distance": "Distance", "angle": "Angle",
         "concentric": "Concentric", "gear": "Gear mesh"}
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
    value: float = 0.0        # distance (mm), angle (deg) or gear centre distance (mm)
    flip: bool = False        # plane mates: aligned instead of anti-aligned; concentric: reverse the axis

    def eqs(self) -> int:
        if self.type == "concentric":
            return 4
        if self.type == "gear":
            return 3
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


def _axis_offset(pa: np.ndarray, va: np.ndarray, pb: np.ndarray) -> np.ndarray:
    """The perpendicular from axis a to the point pb (its length is the distance between parallel axes)."""
    d = pb - pa
    return d - va * float(d @ va)


def _unit_offset(off: np.ndarray, va: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(off))
    return off / n if n > 1e-12 else xform.perp(va)


def residual(m: MateSpec, Ta: np.ndarray, Tb: np.ndarray, L: float) -> np.ndarray:
    pa, va = world(Ta, m.ra)
    pb, vb = world(Tb, m.rb)
    if m.type == "concentric":
        par = L * np.cross(va, vb)
        return np.concatenate([par, _axis_offset(pa, va, pb)])
    if m.type == "gear":
        par = L * np.cross(va, vb)
        return np.concatenate([par, [float(np.linalg.norm(_axis_offset(pa, va, pb))) - m.value]])
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
    if m.type in ("concentric", "gear"):
        ang = math.asin(min(1.0, float(np.linalg.norm(np.cross(va, vb)))))
        dist = float(np.linalg.norm(_axis_offset(pa, va, pb)))
        return (dist if m.type == "concentric" else abs(dist - m.value)), math.degrees(ang)
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


def _skew(v: np.ndarray) -> np.ndarray:
    return np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])


def _mate_blocks(m: MateSpec, poses: dict[str, np.ndarray], insts: dict[str, Inst], L: float) -> dict[str, np.ndarray]:
    """d residual / d x for each side of a mate (rows x 6), x = (L w, t) as in ``_delta``."""
    pa, va = world(poses[m.a], m.ra)
    pb, vb = world(poses[m.b], m.rb)
    I3 = np.eye(3)

    def motion(iid: str, p: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        c = xform.pt(poses[iid], insts[iid].ref_point)
        # dp = w x (p - c) + t,  dv = w x v ; returned as (dp/dx, dv/dx), 3 x 6 each, x = (L w, t)
        dp = np.hstack([-_skew(p - c) / L, I3])
        dv = np.hstack([-_skew(v) / L, np.zeros((3, 3))])
        return dp, dv

    dpa, dva = motion(m.a, pa, va)
    dpb, dvb = motion(m.b, pb, vb)
    if m.type == "concentric":
        d = pb - pa
        P = I3 - np.outer(va, va)
        Q = float(d @ va) * I3 + np.outer(va, d)
        ja = np.vstack([L * (-_skew(vb)) @ dva, -P @ dpa - Q @ dva])
        jb = np.vstack([L * _skew(va) @ dvb, P @ dpb])
    elif m.type == "gear":   # d|off| = u·d(off), u the unit offset; d(off) as in concentric
        d = pb - pa
        P = I3 - np.outer(va, va)
        Q = float(d @ va) * I3 + np.outer(va, d)
        u = _unit_offset(P @ d, va)
        ja = np.vstack([L * (-_skew(vb)) @ dva, (u @ (-P @ dpa - Q @ dva))[None, :]])
        jb = np.vstack([L * _skew(va) @ dvb, (u @ (P @ dpb))[None, :]])
    elif m.type == "angle":
        th = m.angle_rad()
        if th < 1e-9:
            ja, jb = L * dva, -L * dvb
        elif th > math.pi - 1e-9:
            ja, jb = L * dva, L * dvb
        else:
            ja, jb = L * (vb @ dva)[None, :], L * (va @ dvb)[None, :]
    else:
        sgn = -1.0 if m.aligned() else 1.0
        d = pb - pa
        ja = np.vstack([L * dva, (-va @ dpa + d @ dva)[None, :]])
        jb = np.vstack([sgn * L * dvb, (va @ dpb)[None, :]])
    return {m.a: ja, m.b: jb}


def _components(mates: list[MateSpec], insts: dict[str, Inst]) -> list[tuple[list[str], list[MateSpec]]]:
    """Independent sub-problems: free instances joined by mates (a fixed instance joins nothing: it can't move).
    Each with its mates; a mate between a free and a fixed instance belongs to the free one's component."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for m in mates:
        fa, fb = not insts[m.a].fixed, not insts[m.b].fixed
        if fa:
            find(m.a)
        if fb:
            find(m.b)
        if fa and fb:
            ra, rb = find(m.a), find(m.b)
            if ra != rb:
                parent[ra] = rb
    groups: dict[str, tuple[list[str], list[MateSpec]]] = {}
    order = {k: n for n, k in enumerate(insts)}
    for iid in sorted(parent, key=order.__getitem__):
        groups.setdefault(find(iid), ([], []))[0].append(iid)
    for m in mates:
        k = m.a if not insts[m.a].fixed else m.b if not insts[m.b].fixed else None
        if k is not None:
            groups[find(k)][1].append(m)
    return list(groups.values())


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
        """Analytic Jacobian (dense): the same derivatives as ``jac_numeric`` (central differences), exact."""
        return self.jac_sparse(poses).toarray()

    def jac_sparse(self, poses: dict[str, np.ndarray]) -> Any:
        """Analytic Jacobian of every mate residual w.r.t. the free instances' small motions (ASM-023): a sparse
        matrix (each mate touches at most two instances), built in one pass. With x = (L w, t) per instance, a world
        point moves by w x (p - c) + t and a world direction by w x v (``_delta`` at x = 0)."""
        from scipy import sparse

        rows: list[np.ndarray] = []
        cols: list[np.ndarray] = []
        vals: list[np.ndarray] = []
        for (r0, n), m in zip(self.rows, self.mates, strict=True):
            for iid, blk in _mate_blocks(m, poses, self.insts, self.L).items():
                if iid not in self.col:
                    continue
                c0 = self.col[iid]
                rr, cc = np.meshgrid(np.arange(r0, r0 + n), np.arange(c0, c0 + 6), indexing="ij")
                rows.append(rr.ravel())
                cols.append(cc.ravel())
                vals.append(blk.ravel())
        if not rows:
            return sparse.csr_matrix((self.m, self.n))
        return sparse.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                                 shape=(self.m, self.n))

    def jac_numeric(self, poses: dict[str, np.ndarray]) -> np.ndarray:
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
    from scipy import sparse
    from scipy.sparse.linalg import spsolve

    lam = 1e-6
    r = prob.r(poses)
    cost = float(r @ r)
    it = 0
    eye = sparse.identity(prob.n, format="csc")
    for it in range(1, iters + 1):
        if float(np.max(np.abs(r))) < 1e-10:
            break
        J = prob.jac_sparse(poses)  # analytic and sparse: a 300-part assembly no longer takes minutes (ASM-023)
        g = J.T @ r
        A = (J.T @ J).tocsc()
        dA = sparse.diags(np.maximum(A.diagonal(), 1e-9), format="csc")
        improved = False
        dx = np.zeros(prob.n)
        for _ in range(12):
            try:
                dx = np.asarray(spsolve(A + lam * dA + lam * eye, -g)).ravel()
            except (np.linalg.LinAlgError, RuntimeError):
                lam *= 10
                continue
            if not np.all(np.isfinite(dx)):
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
    if m.type in ("concentric", "gear"):
        target = vo if float(vm @ vo) >= 0 else -vo
        if m.flip:
            target = -target
        T = xform.about(xform.min_rot(vm, target), pm) @ T
        pm, vm = world(T, rm)
        off = _axis_offset(po, vo, pm)
        if m.type == "concentric":
            return xform.translate(-off) @ T
        # gear: along the current offset (the smallest move) to the centre distance
        return xform.translate(_unit_offset(off, vo) * (m.value - float(np.linalg.norm(off)))) @ T
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


BLOCKS_FROM_COLS = 600  # free columns (100 instances) above which leaf blocks are analysed on their own


def _null_blocks(prob: _Problem, J: np.ndarray, blocks: dict[str, str]) -> tuple[int, np.ndarray] | None:
    """Rank and null space of J when some instances form leaf blocks (a fastener stack: its mates join only its own
    members and the parts it clamps). Exact, the same space as the SVD of the whole J: with P the other columns and
    J = [[J1, 0], [A_k, B_k]] row-blocked per leaf block k, x is in the null space iff J1 xP = 0,
    (I - B_k B_k^+) A_k xP = 0 for every k, and xS_k = -B_k^+ A_k xP + null(B_k) z_k. The big SVD (the whole
    assembly, cubic in its size) becomes one over the parts plus one small SVD per block. None: not applicable."""
    by: dict[str, list[str]] = {}
    for iid in prob.free:
        if iid in blocks:
            by.setdefault(blocks[iid], []).append(iid)
    if not by:
        return None
    rows_of: dict[str, list[int]] = {}
    rows_p: list[int] = []
    for (r0, n), m in zip(prob.rows, prob.mates, strict=True):
        ks = {blocks[x] for x in (m.a, m.b) if x in blocks and x in prob.col}
        if len(ks) > 1:
            return None  # a mate between two blocks: not leaves
        idx = list(range(r0, r0 + n))
        if ks:
            rows_of.setdefault(ks.pop(), []).extend(idx)
        else:
            rows_p.extend(idx)
    cols = lambda ids: [prob.col[i] + j for i in ids for j in range(6)]
    pcols = cols([i for i in prob.free if i not in blocks])
    # the whole-J rule is 1e-6 x its largest singular value; sqrt(|J|_1 |J|_inf) bounds that from above, cheaply
    aj = np.abs(J)
    smax = float(np.sqrt(aj.sum(axis=0).max() * aj.sum(axis=1).max())) if J.size else 1.0
    tol = 1e-6 * max(1.0, smax)
    cons = [J[np.ix_(rows_p, pcols)]] if rows_p and pcols else []
    parts: dict[str, tuple[list[int], np.ndarray, np.ndarray]] = {}
    for k, ids in by.items():
        sc, rk_ = cols(ids), rows_of.get(k, [])
        if not rk_:
            parts[k] = (sc, np.zeros((len(sc), len(pcols))), np.eye(len(sc)))
            continue
        B = J[np.ix_(rk_, sc)]
        A = J[np.ix_(rk_, pcols)] if pcols else np.zeros((len(rk_), 0))
        U, sv, Vt = np.linalg.svd(B)
        r = int(np.sum(sv > tol))
        if pcols:
            cons.append(U[:, r:].T @ A)
        Bp = Vt[:r].T @ np.diag(1.0 / sv[:r]) @ U[:, :r].T
        parts[k] = (sc, -(Bp @ A), Vt[r:].T)
    if pcols:
        M = np.vstack(cons) if cons else np.zeros((0, len(pcols)))
        if M.shape[0]:
            _u, sm, Vm = np.linalg.svd(M)
            rp = int(np.sum(sm > tol))
            Np = Vm[rp:].T
        else:
            Np = np.eye(len(pcols))
    else:
        Np = np.zeros((0, 0))
    dim = Np.shape[1] + sum(v[2].shape[1] for v in parts.values())
    null = np.zeros((prob.n, dim))
    if pcols:
        null[pcols, :Np.shape[1]] = Np
    off = Np.shape[1]
    for sc, G, Ns in parts.values():
        if Np.shape[1]:
            null[sc, :Np.shape[1]] = G @ Np
        null[sc, off:off + Ns.shape[1]] = Ns
        off += Ns.shape[1]
    return prob.n - dim, null


def _null_components(prob: _Problem, J: np.ndarray) -> tuple[int, np.ndarray]:
    """Rank and null space of J, one SVD per independent group of instances (J is block diagonal over them after
    reordering): the same space as one SVD of the whole J, without its cubic cost on a large assembly. The rank
    tolerance is the whole-J rule, 1e-6 x its largest singular value (the largest over the blocks)."""
    comps = _components(prob.mates, prob.insts)
    pieces = []
    smax = 0.0
    for ids, mates in comps:
        cols = [prob.col[i] + j for i in ids if i in prob.col for j in range(6)]
        mids = {m.id for m in mates}
        rws = [r for (r0, n), m in zip(prob.rows, prob.mates, strict=True) if m.id in mids for r in range(r0, r0 + n)]
        if not cols:
            continue
        sub = J[np.ix_(rws, cols)] if rws else np.zeros((0, len(cols)))
        if sub.shape[0]:
            _u, sv, Vt = np.linalg.svd(sub)
            smax = max(smax, float(sv[0]) if sv.size else 0.0)
        else:
            sv, Vt = np.zeros(0), np.eye(len(cols))
        pieces.append((cols, sv, Vt))
    tol = 1e-6 * max(1.0, smax)
    rank = 0
    blocks = []
    for cols, sv, Vt in pieces:
        r = int(np.sum(sv > tol))
        rank += r
        blocks.append((cols, Vt[r:].T))
    null = np.zeros((prob.n, sum(b.shape[1] for _c, b in blocks)))
    off = 0
    for cols, b in blocks:
        null[cols, off:off + b.shape[1]] = b
        off += b.shape[1]
    return rank, null


def _analyse(prob: _Problem, poses: dict[str, np.ndarray], all_ids: Iterable[str],
             blocks: dict[str, str] | None = None) -> tuple[dict[str, InstState], int, int]:
    insts = prob.insts
    states: dict[str, InstState] = {}
    rank = 0
    null = np.zeros((prob.n, 0))
    if prob.n:
        if prob.m:
            J = prob.jac(poses)
            got = _null_blocks(prob, J, blocks) if blocks and prob.n > BLOCKS_FROM_COLS else None
            if got is not None:
                rank, null = got
            else:
                rank, null = _null_components(prob, J)
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
        B = B[:, np.any(B != 0.0, axis=0)]  # only the null vectors that move this instance (same ranks, far smaller)

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
          prealign_ids: Iterable[str] = (), blocks: dict[str, str] | None = None) -> Result:
    """Solve all mates from the current placements. ``prealign_ids``: mates just added (pre-aligned first when
    their moving instance has no other mates). ``blocks``: instance -> leaf block (fastener stack) id, so a large
    assembly's degrees of freedom are analysed block by block (same result, ``_null_blocks``)."""
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
    start = dict(poses)
    prob = _Problem(insts, mates, L)
    # only the groups of instances with an unsatisfied mate move (each group is independent of the others); after a
    # hand edit that is the edited part's group, not the whole assembly (ASM-023)
    start_ok = {m.id for m in mates if _satisfied(m, poses)[0]}
    moving = [ms for _ids, ms in _components(mates, insts) if any(m.id not in start_ok for m in ms)]
    its = 0
    if moving:
        sub = [m for ms in moving for m in ms]
        poses, its = _lm(_Problem(insts, sub, L), poses)
    conflicts: list[str] = []
    if not all(_satisfied(m, poses)[0] for m in mates):
        # isolate conflicts: the mates satisfied at the start are consistent (one placement satisfies them all);
        # add the others one at a time in creation order, in their own groups only
        poses = dict(start)
        keep: list[MateSpec] = [m for m in mates if m.id in start_ok]
        for m in [m for m in mates if m.id not in start_ok]:
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
        order = {m.id: k for k, m in enumerate(mates)}
        prob = _Problem(insts, sorted(keep, key=lambda m: order[m.id]), L)
    states, _rank, redundant = _analyse(prob, poses, list(insts), blocks)
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
