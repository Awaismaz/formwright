"""Bounding-volume hierarchy over triangles with vectorised (wavefront) ray and overlap queries.

Pure numpy, deterministic. Rays are processed level by level as (ray, node) pairs, so there is no per-ray Python
loop. Used for wall thickness / gap rays, support-height rays and self-intersection candidate pairs.
"""

from __future__ import annotations

import numpy as np

LEAF = 8


class BVH:
    def __init__(self, v: np.ndarray, f: np.ndarray) -> None:
        self.v0 = v[f[:, 0]]
        self.e1 = v[f[:, 1]] - self.v0
        self.e2 = v[f[:, 2]] - self.v0
        cr = np.cross(self.e1, self.e2)
        nrm = np.linalg.norm(cr, axis=1)
        self.n = np.divide(cr, nrm[:, None], out=np.zeros_like(cr), where=nrm[:, None] > 0)
        tri = v[f]
        self.tmin = tri.min(axis=1)
        self.tmax = tri.max(axis=1)
        self.f = f
        cen = (self.tmin + self.tmax) / 2
        m = len(f)
        order = np.arange(m)
        lo: list[np.ndarray] = []
        hi: list[np.ndarray] = []
        left: list[int] = []
        right: list[int] = []
        start: list[int] = []
        count: list[int] = []
        stack = [(0, m, -1, 0)]  # (begin, end, parent, side)
        while stack:
            b, e, parent, side = stack.pop()
            idx = order[b:e]
            node = len(lo)
            lo.append(self.tmin[idx].min(axis=0))
            hi.append(self.tmax[idx].max(axis=0))
            left.append(-1)
            right.append(-1)
            start.append(b)
            count.append(0)
            if parent >= 0:
                (left if side == 0 else right)[parent] = node
            if e - b <= LEAF:
                count[node] = e - b
                continue
            c = cen[idx]
            axis = int(np.argmax(c.max(axis=0) - c.min(axis=0)))
            mid = (e - b) // 2
            part = np.argpartition(c[:, axis], mid, kind="introselect")
            order[b:e] = idx[part]
            stack.append((b + mid, e, node, 1))
            stack.append((b, b + mid, node, 0))
        self.order = order
        self.lo = np.array(lo)
        self.hi = np.array(hi)
        self.left = np.array(left)
        self.right = np.array(right)
        self.start = np.array(start)
        self.count = np.array(count)

    # ------------------------------------------------------------ rays
    def closest_hit(self, o: np.ndarray, d: np.ndarray, t_max: np.ndarray | float, *, t_min: float = 1e-9,
                    facing: int = 0, skip: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Closest hit distance (inf when none) and triangle id (-1) per ray.

        facing: +1 accept only triangles whose normal points along the ray (exiting a solid), -1 only against the
        ray (entering), 0 any. skip: per-ray triangle id to ignore (the triangle the ray starts on).
        """
        r = len(o)
        best = np.broadcast_to(np.asarray(t_max, float), (r,)).copy()
        best_tri = np.full(r, -1, dtype=np.int64)
        if r == 0:
            return np.full(0, np.inf), best_tri
        with np.errstate(divide="ignore", invalid="ignore"):
            inv = 1.0 / d
        pr = np.arange(r)
        pn = np.zeros(r, dtype=np.int64)
        while len(pr):
            oo, ii = o[pr], inv[pr]
            with np.errstate(invalid="ignore"):
                t1 = (self.lo[pn] - oo) * ii
                t2 = (self.hi[pn] - oo) * ii
            t1 = np.nan_to_num(t1, nan=-np.inf)
            t2 = np.nan_to_num(t2, nan=np.inf)
            tn = np.maximum(np.minimum(t1, t2).max(axis=1), 0.0)
            tf = np.maximum(t1, t2).min(axis=1)
            keep = (tn <= tf) & (tn <= best[pr])
            pr, pn = pr[keep], pn[keep]
            leaf = self.count[pn] > 0
            lr, ln = pr[leaf], pn[leaf]
            if len(lr):
                cnt = self.count[ln]
                rr = np.repeat(lr, cnt)
                offs = np.repeat(self.start[ln] - np.cumsum(cnt) + cnt, cnt) + np.arange(cnt.sum())
                tt = self.order[offs]
                if skip is not None:
                    ok = tt != skip[rr]
                    rr, tt = rr[ok], tt[ok]
                t = self._ray_tri(o[rr], d[rr], tt, t_min, facing)
                hit = t < best[rr]
                if hit.any():
                    rr, tt, t = rr[hit], tt[hit], t[hit]
                    srt = np.lexsort((tt, t, rr))  # per ray: smallest t, then lowest tri id (deterministic)
                    rr, tt, t = rr[srt], tt[srt], t[srt]
                    first = np.r_[True, rr[1:] != rr[:-1]]
                    rr, tt, t = rr[first], tt[first], t[first]
                    better = t < best[rr]
                    best[rr[better]] = t[better]
                    best_tri[rr[better]] = tt[better]
            inner = ~leaf
            ir, inn = pr[inner], pn[inner]
            pr = np.concatenate([ir, ir])
            pn = np.concatenate([self.left[inn], self.right[inn]])
        dist = np.where(best_tri >= 0, best, np.inf)
        return dist, best_tri

    def _ray_tri(self, o: np.ndarray, d: np.ndarray, t: np.ndarray, t_min: float, facing: int) -> np.ndarray:
        e1, e2 = self.e1[t], self.e2[t]
        p = np.cross(d, e2)
        det = np.einsum("ij,ij->i", e1, p)
        ok = np.abs(det) > 1e-14
        inv = np.divide(1.0, det, out=np.zeros_like(det), where=ok)
        s = o - self.v0[t]
        u = np.einsum("ij,ij->i", s, p) * inv
        q = np.cross(s, e1)
        w = np.einsum("ij,ij->i", d, q) * inv
        dist = np.einsum("ij,ij->i", e2, q) * inv
        eps = 1e-9
        ok &= (u >= -eps) & (w >= -eps) & (u + w <= 1 + eps) & (dist > t_min)
        if facing:
            ok &= np.einsum("ij,ij->i", self.n[t], d) * facing > 0
        return np.where(ok, dist, np.inf)

    # ------------------------------------------------------------ overlaps
    def overlapping_pairs(self, max_pairs: int = 20_000_000) -> np.ndarray | None:
        """Pairs (i<j) of triangles whose bounding boxes overlap. None if the candidate count exceeds max_pairs."""
        m = len(self.f)
        pad = 1e-9 * max(1.0, float(np.abs(self.hi).max(initial=1.0)))
        lo_t, hi_t = self.tmin - pad, self.tmax + pad
        pt = np.arange(m)
        pn = np.zeros(m, dtype=np.int64)
        out: list[np.ndarray] = []
        total = 0
        while len(pt):
            ov = np.all((lo_t[pt] <= self.hi[pn]) & (hi_t[pt] >= self.lo[pn]), axis=1)
            pt, pn = pt[ov], pn[ov]
            leaf = self.count[pn] > 0
            lt, ln = pt[leaf], pn[leaf]
            if len(lt):
                cnt = self.count[ln]
                tt = np.repeat(lt, cnt)
                offs = np.repeat(self.start[ln] - np.cumsum(cnt) + cnt, cnt) + np.arange(cnt.sum())
                oo = self.order[offs]
                k = oo > tt
                tt, oo = tt[k], oo[k]
                ov2 = np.all((lo_t[tt] <= hi_t[oo]) & (hi_t[tt] >= lo_t[oo]), axis=1)
                if ov2.any():
                    out.append(np.stack([tt[ov2], oo[ov2]], axis=1))
                    total += int(ov2.sum())
                    if total > max_pairs:
                        return None
            inner = ~leaf
            it, inn = pt[inner], pn[inner]
            pt = np.concatenate([it, it])
            pn = np.concatenate([self.left[inn], self.right[inn]])
            if len(pt) > max_pairs:
                return None
        return np.concatenate(out) if out else np.zeros((0, 2), dtype=np.int64)


def segments_hit_triangles(p: np.ndarray, q: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray,
                           eps: float = 1e-9) -> np.ndarray:
    """Whether segment p→q crosses the interior of triangle abc (strictly; touching and coplanar cases excluded)."""
    d = q - p
    e1, e2 = b - a, c - a
    h = np.cross(d, e2)
    det = np.einsum("ij,ij->i", e1, h)
    scale = np.linalg.norm(d, axis=1) * np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1)
    ok = np.abs(det) > 1e-10 * np.maximum(scale, 1e-300)
    inv = np.divide(1.0, det, out=np.zeros_like(det), where=ok)
    s = p - a
    u = np.einsum("ij,ij->i", s, h) * inv
    qq = np.cross(s, e1)
    v = np.einsum("ij,ij->i", d, qq) * inv
    t = np.einsum("ij,ij->i", e2, qq) * inv
    return ok & (u > eps) & (v > eps) & (u + v < 1 - eps) & (t > eps) & (t < 1 - eps)
