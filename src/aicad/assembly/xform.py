"""Rigid transforms (4x4 homogeneous, millimetres). An instance placement maps part-local coordinates to assembly
coordinates: ``world = T @ local``. Stored in documents as 12 numbers, the rows of ``[R | t]``."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

Mat = np.ndarray


def ident() -> Mat:
    return np.eye(4)


def from12(v: Sequence[float] | None) -> Mat:
    m = np.eye(4)
    if v is None:
        return m
    a = np.asarray(v, dtype=float)
    if a.shape != (12,) or not np.all(np.isfinite(a)):
        raise ValueError("a placement needs 12 finite numbers")
    m[:3, :] = a.reshape(3, 4)
    return m


def to12(m: Mat) -> list[float]:
    """Rounded so JSON documents are stable (1e-12 is far below any modelling tolerance)."""
    return [0.0 if abs(x) < 1e-13 else round(float(x), 12) for x in m[:3, :].reshape(-1)]


def make(R: Mat, t: Sequence[float]) -> Mat:
    m = np.eye(4)
    m[:3, :3] = R
    m[:3, 3] = np.asarray(t, dtype=float)
    return m


def unit(v: Sequence[float]) -> np.ndarray:
    a = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(a))
    if n < 1e-12:
        raise ValueError("zero-length direction")
    return a / n


def rot(axis: Sequence[float], angle: float) -> Mat:
    """3x3 rotation by ``angle`` radians about ``axis`` (Rodrigues)."""
    k = unit(axis)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(angle) * K + (1 - math.cos(angle)) * (K @ K)


def exp_so3(w: Sequence[float]) -> Mat:
    w = np.asarray(w, dtype=float)
    th = float(np.linalg.norm(w))
    if th < 1e-15:
        return np.eye(3)
    return rot(w / th, th)


def perp(v: Sequence[float]) -> np.ndarray:
    """A deterministic unit vector perpendicular to v."""
    u = unit(v)
    ref = np.array([1.0, 0.0, 0.0]) if abs(u[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    p = ref - u * float(ref @ u)
    return p / float(np.linalg.norm(p))


def min_rot(a: Sequence[float], b: Sequence[float]) -> Mat:
    """Smallest rotation taking direction a onto direction b (180° about a deterministic perpendicular when
    they are opposite)."""
    ua, ub = unit(a), unit(b)
    c = float(np.clip(ua @ ub, -1.0, 1.0))
    if c > 1 - 1e-15:
        return np.eye(3)
    if c < -1 + 1e-12:
        return rot(perp(ua), math.pi)
    return rot(np.cross(ua, ub), math.acos(c))


def frame_z(z: Sequence[float]) -> Mat:
    """Rotation whose local +Z maps to ``z`` (x axis chosen deterministically)."""
    uz = unit(z)
    ux = perp(uz)
    uy = np.cross(uz, ux)
    return np.column_stack([ux, uy, uz])


def about(R: Mat, pivot: Sequence[float]) -> Mat:
    """4x4 rotation R about a pivot point."""
    p = np.asarray(pivot, dtype=float)
    return make(R, p - R @ p)


def translate(t: Sequence[float]) -> Mat:
    return make(np.eye(3), t)


def pt(m: Mat, p: Sequence[float]) -> np.ndarray:
    return m[:3, :3] @ np.asarray(p, dtype=float) + m[:3, 3]


def vec(m: Mat, v: Sequence[float]) -> np.ndarray:
    return m[:3, :3] @ np.asarray(v, dtype=float)


def inv(m: Mat) -> Mat:
    R = m[:3, :3]
    return make(R.T, -R.T @ m[:3, 3])


def is_rigid(m: Mat, tol: float = 1e-6) -> bool:
    R = m[:3, :3]
    return bool(np.allclose(R.T @ R, np.eye(3), atol=tol) and abs(np.linalg.det(R) - 1) < tol)


def orthonormalize(m: Mat) -> Mat:
    """Remove numerical drift from a rotation (SVD projection onto SO(3))."""
    U, _s, Vt = np.linalg.svd(m[:3, :3])
    R = U @ Vt
    if np.linalg.det(R) < 0:
        U[:, -1] *= -1
        R = U @ Vt
    return make(R, m[:3, 3])
