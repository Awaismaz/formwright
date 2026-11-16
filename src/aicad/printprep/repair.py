"""Mesh repair for print: weld, drop degenerate/duplicate triangles, make winding consistent and outward, fill holes.

Deterministic and conservative: it never moves existing vertices (except welding coincident ones) and reports
every change with before/after counts.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np

from aicad.printprep.analysis import boundary_loops, components, edge_maps, face_adjacency, topology
from aicad.printprep.mesh import Mesh, merge_vertices, signed_volume, tri_vectors

MAX_HOLE_EDGES = 5000


def _n(k: int, word: str) -> str:
    return f"{k:,} {word}" + ("" if k == 1 else "s")


def _counts(m: Mesh) -> dict[str, Any]:
    t = topology(m)
    return {k: t[k] for k in ("vertices", "triangles", "boundary_edges", "nonmanifold_edges", "inconsistent_edges",
                              "degenerate_faces", "holes", "shells")} | {"volume_mm3": t["volume_mm3"]}


def _fix_winding(f: np.ndarray, n_vert: int) -> tuple[np.ndarray, int]:
    """Flip triangles so neighbours across every manifold edge traverse it in opposite directions (BFS per shell,
    seeded from the lowest triangle index)."""
    adj = face_adjacency(f, n_vert)
    m = len(f)
    if not len(adj):
        return f, 0
    nb: list[list[int]] = [[] for _ in range(m)]
    for a, b in adj.tolist():
        nb[a].append(b)
        nb[b].append(a)

    def dir_edges(t: np.ndarray) -> set[tuple[int, int]]:
        return {(int(t[0]), int(t[1])), (int(t[1]), int(t[2])), (int(t[2]), int(t[0]))}

    f = f.copy()
    seen = np.zeros(m, dtype=bool)
    flips = 0
    for seed in range(m):
        if seen[seed]:
            continue
        seen[seed] = True
        q = deque([seed])
        while q:
            a = q.popleft()
            ea = dir_edges(f[a])
            for b in nb[a]:
                if seen[b]:
                    continue
                if ea & dir_edges(f[b]):  # same direction on the shared edge -> flip b
                    f[b] = f[b][[0, 2, 1]]
                    flips += 1
                seen[b] = True
                q.append(b)
    return f, flips


def _ear_clip(poly: np.ndarray) -> list[tuple[int, int, int]] | None:
    """Triangulate a simple CCW 2D polygon; None if it is not simple enough to clip."""
    idx = list(range(len(poly)))

    def area2(a: int, b: int, c: int) -> float:
        p, q, r = poly[a], poly[b], poly[c]
        return float((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]))

    def inside(p: np.ndarray, a: int, b: int, c: int) -> bool:
        def s(u: np.ndarray, v: np.ndarray, w: np.ndarray) -> float:
            return float((v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0]))
        A, B, C = poly[a], poly[b], poly[c]
        return s(A, B, p) > 1e-12 and s(B, C, p) > 1e-12 and s(C, A, p) > 1e-12

    out: list[tuple[int, int, int]] = []
    guard = 0
    while len(idx) > 3 and guard < 10 * len(poly) ** 2:
        guard += 1
        clipped = False
        for k in range(len(idx)):
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            if area2(a, b, c) <= 1e-14:
                continue
            if any(inside(poly[j], a, b, c) for j in idx if j not in (a, b, c)):
                continue
            out.append((a, b, c))
            idx.pop(k)
            clipped = True
            break
        if not clipped:
            return None
    if len(idx) == 3:
        out.append((idx[0], idx[1], idx[2]))
    return out


def _fill(v: np.ndarray, loop: list[int]) -> tuple[list[tuple[int, int, int]], np.ndarray | None]:
    """Triangles closing a boundary loop (vertex ids). Ear clipping in the loop's best-fit plane, else a centroid
    fan (returns the extra centroid vertex)."""
    pts = v[loop]
    if len(loop) == 3:
        return [(loop[0], loop[1], loop[2])], None
    nrm = np.zeros(3)
    for i in range(len(pts)):  # Newell normal: orientation of the loop as traversed
        p, q = pts[i], pts[(i + 1) % len(pts)]
        nrm += np.array([(p[1] - q[1]) * (p[2] + q[2]), (p[2] - q[2]) * (p[0] + q[0]),
                         (p[0] - q[0]) * (p[1] + q[1])])
    ln = np.linalg.norm(nrm)
    if ln > 1e-12:
        nrm /= ln
        u = np.cross(nrm, [1.0, 0, 0] if abs(nrm[0]) < 0.9 else [0, 1.0, 0])
        u /= np.linalg.norm(u)
        w = np.cross(nrm, u)
        c = pts.mean(axis=0)
        planar = np.abs((pts - c) @ nrm).max() <= 1e-3 * max(1.0, float(np.ptp(pts, axis=0).max()))
        if planar:
            tri = _ear_clip(np.c_[(pts - c) @ u, (pts - c) @ w])
            if tri is not None:
                return [(loop[a], loop[b], loop[c_]) for a, b, c_ in tri], None
    cen = pts.mean(axis=0)
    k = len(v)
    return [(k, loop[i], loop[(i + 1) % len(loop)]) for i in range(len(loop))], cen


def repair(mesh: Mesh) -> tuple[Mesh, dict[str, Any]]:
    before = _counts(mesh)
    actions: list[str] = []
    v, f = mesh.v.copy(), mesh.f.copy()
    # 1. weld coincident vertices
    nv0 = len(v)
    v, f = merge_vertices(v, f, tol=1e-5)
    if len(v) < nv0:
        actions.append(f"Welded {_n(nv0 - len(v), 'duplicate vertex').replace('vertexs', 'vertices')}")
    # 2. degenerate triangles (repeated index or zero area)
    _, areas, _ = tri_vectors(v, f)
    bad = (f[:, 0] == f[:, 1]) | (f[:, 1] == f[:, 2]) | (f[:, 2] == f[:, 0]) | (areas <= 1e-12)
    if bad.any():
        f = f[~bad]
        actions.append(f"Removed {_n(int(bad.sum()), 'degenerate triangle')}")
    # 3. duplicate triangles (same three vertices, either winding)
    key = np.sort(f, axis=1)
    _, first = np.unique(key, axis=0, return_index=True)
    if len(first) < len(f):
        actions.append(f"Removed {_n(len(f) - len(first), 'duplicate triangle')}")
        f = f[np.sort(first)]
    # 4. consistent winding
    f, flips = _fix_winding(f, len(v))
    if flips:
        actions.append(f"Flipped {_n(flips, 'triangle')} to make the winding consistent")
    # 5. fill holes
    loops = boundary_loops(f, len(v), edge_maps(f, len(v)))
    new_tris: list[tuple[int, int, int]] = []
    extra: list[np.ndarray] = []
    filled = skipped = 0
    for lp in loops:
        if len(lp) > MAX_HOLE_EDGES:
            skipped += 1
            continue
        tri, cen = _fill(v, lp)
        if cen is not None:
            k = len(v) + len(extra)
            tri = [(k, b, c) for _, b, c in tri]
            extra.append(cen[None, :])
        new_tris += tri
        filled += 1
    if extra:
        v = np.vstack([v, *extra])
    if new_tris:
        f = np.vstack([f, np.array(new_tris, dtype=np.int64)])
        actions.append(f"Filled {_n(filled, 'hole')} with {_n(len(new_tris), 'triangle')}")
    if skipped:
        actions.append(f"Left {_n(skipped, 'very large opening')} unfilled (over {MAX_HOLE_EDGES:,} edges)")
    # 6. outward normals per closed shell
    lab = components(f, len(v))
    flipped_shells = 0
    for k in np.unique(lab).tolist():
        sel = lab == k
        if signed_volume(v, f[sel]) < 0:
            f[sel] = f[sel][:, [0, 2, 1]]
            flipped_shells += 1
    if flipped_shells:
        actions.append(f"Reversed {_n(flipped_shells, 'inward-facing shell')}")
    out = Mesh(v, f, None, {**{k: x for k, x in mesh.meta.items() if not k.startswith("_")}, "repaired": True})
    after = _counts(out)
    if not actions:
        actions.append("No repairs needed")
    return out, {"before": before, "after": after, "actions": actions}
