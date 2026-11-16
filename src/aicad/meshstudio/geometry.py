"""Visualisation mesh of a project's verified part: tessellated from the exact STEP by our OCCT, checked with the
3D Print Prep mesh checks (`aicad.printprep`), and written as plain arrays for the Blender scene script.

The mesh stays watertight (vertices welded across B-rep faces); shading is kept crisp by per-corner ("split")
normals that are smooth inside each exact face and break at face boundaries, so a cylinder looks round and a
chamfer edge stays sharp.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from aicad.printprep.analysis import self_intersections, topology
from aicad.printprep.bvh import BVH
from aicad.printprep.mesh import Mesh, load_step, tessellate_shape, tri_vectors

MAX_TRIANGLES = 1_500_000
ANGULAR_DEG = 5.0


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def choose_tolerance(diag_mm: float) -> float:
    """Chordal tolerance (mm): fine enough that silhouettes are smooth in a full-frame render."""
    return float(min(0.05, max(0.005, round(diag_mm / 8000, 4))))


def split_normals(mesh: Mesh) -> np.ndarray:
    """Per-corner unit normals (m, 3, 3): area-weighted average over triangles of the same exact face."""
    n, areas, _ = tri_vectors(mesh.v, mesh.f)
    region = mesh.region if mesh.region is not None else np.zeros(len(mesh.f), dtype=np.int32)
    key = mesh.f.astype(np.int64) * (int(region.max()) + 1) + region[:, None]  # (vertex, face) pair per corner
    uniq, inv = np.unique(key.ravel(), return_inverse=True)
    acc = np.zeros((len(uniq), 3))
    np.add.at(acc, inv, np.repeat(n * areas[:, None], 3, axis=0))
    norm = np.linalg.norm(acc, axis=1, keepdims=True)
    acc = np.divide(acc, norm, out=np.zeros_like(acc), where=norm > 0)
    corner = acc[inv].reshape(-1, 3, 3)
    flat = np.repeat(n[:, None, :], 3, axis=1)  # fall back to the flat normal where an average vanished
    bad = np.linalg.norm(corner, axis=2) < 0.5
    corner[bad] = flat[bad]
    return corner


def mesh_checks(mesh: Mesh) -> list[dict[str, Any]]:
    """MSH-008: topology checks of the visualisation mesh, measured by the 3D Print Prep functions."""
    topo = topology(mesh)
    sx = self_intersections(mesh, BVH(mesh.v, mesh.f))
    dev = mesh.meta.get("deviation") or {}
    tol = float(mesh.meta.get("tolerance", 0))

    def chk(cid: str, name: str, ok: bool | None, value: Any, detail: str, warn: bool = False) -> dict[str, Any]:
        status = "info" if ok is None else ("pass" if ok else ("warn" if warn else "fail"))
        return {"id": cid, "name": name, "status": status, "value": value, "detail": detail}

    out = [
        chk("MS-01", "Watertight", topo["boundary_edges"] == 0, topo["boundary_edges"],
            "Closed surface, no open edges." if topo["boundary_edges"] == 0 else
            f"{topo['boundary_edges']:,} open edges ({topo['holes']} holes)."),
        chk("MS-02", "Manifold edges", topo["nonmanifold_edges"] == 0, topo["nonmanifold_edges"],
            "Every edge borders at most two triangles." if topo["nonmanifold_edges"] == 0 else
            f"{topo['nonmanifold_edges']:,} edges are shared by more than two triangles."),
        chk("MS-03", "Consistent outward normals", topo["inconsistent_edges"] == 0 and topo["volume_mm3"] > 0,
            topo["inconsistent_edges"], "Winding is consistent and encloses positive volume."
            if topo["inconsistent_edges"] == 0 and topo["volume_mm3"] > 0 else "Some triangles face inwards."),
        chk("MS-04", "Degenerate triangles", topo["degenerate_faces"] == 0, topo["degenerate_faces"],
            "No zero-area triangles." if topo["degenerate_faces"] == 0 else
            f"{topo['degenerate_faces']:,} zero-area triangles (harmless for rendering).", warn=True),
        chk("MS-05", "Self-intersection", (sx["pairs"] == 0) if sx["run"] else None,
            sx.get("pairs"), ("No intersecting triangle pairs." if sx.get("pairs") == 0 else
                              f"{sx.get('pairs'):,} intersecting triangle pairs.") if sx["run"] else
            f"Not run ({sx['reason']}).", warn=True),
        chk("MS-06", "Shells", topo["shells"] == 1 or None, topo["shells"],
            "One connected shell." if topo["shells"] == 1 else f"{topo['shells']} separate shells (bodies)."),
    ]
    if dev:
        out.append(chk("MS-07", "Deviation from the exact model", dev["max_mm"] <= tol * 1.05 + 1e-6,
                       round(dev["max_mm"], 5), f"Max sampled distance to the exact surface {dev['max_mm']:.4f} mm "
                       f"(tolerance {tol:g} mm, {dev['samples']:,} samples); volume differs by "
                       f"{100 * (mesh.meta.get('volume_rel_dev') or 0):.3f}%.", warn=True))
    out.append(chk("MS-08", "UV map", None, None, "None. Finishes are procedural (object space), so the mesh needs "
                   "no UV unwrap; exported meshes carry flat colours, not textures."))
    return out


def build_geometry(step: Path, out_dir: Path) -> dict[str, Any]:
    """Tessellate `step` once per file content into `out_dir/<sha>.npz` (+ .json). Returns the metadata."""
    sha = file_sha(step)[:20]
    meta_p, npz_p = out_dir / f"{sha}.json", out_dir / f"{sha}.npz"
    if meta_p.is_file() and npz_p.is_file():
        return json.loads(meta_p.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    shape = load_step(step)
    bb = shape.bounding_box()
    diag = float(np.linalg.norm([bb.size.X, bb.size.Y, bb.size.Z]))
    tol = choose_tolerance(diag)
    mesh = tessellate_shape(shape, tol, ANGULAR_DEG)
    while mesh.n_tri > MAX_TRIANGLES and tol < 1.0:
        tol *= 2
        mesh = tessellate_shape(shape, tol, ANGULAR_DEG * 1.5)
    normals = split_normals(mesh)
    checks = mesh_checks(mesh)
    tmp = out_dir / f"{sha}.tmp.npz"
    np.savez(tmp, v=(mesh.v * 0.001).astype(np.float32), f=mesh.f.astype(np.int32),
             n=normals.reshape(-1, 3).astype(np.float32))
    tmp.replace(npz_p)
    lo, hi = mesh.v.min(axis=0), mesh.v.max(axis=0)
    meta = {"sha": sha, "file": npz_p.name, "triangles": int(mesh.n_tri), "vertices": len(mesh.v),
            "tolerance_mm": tol, "angular_deg": ANGULAR_DEG, "bbox_mm": [round(float(x), 4) for x in hi - lo],
            "min_mm": [round(float(x), 4) for x in lo], "max_mm": [round(float(x), 4) for x in hi],
            "volume_mm3": round(float(mesh.meta.get("exact_volume") or 0), 3), "checks": checks}
    meta_p.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta


def hull_points(npz: Path, rot: np.ndarray, shift: np.ndarray) -> np.ndarray:
    """Convex-hull vertices (metres) of the posed mesh, for framing."""
    from scipy.spatial import ConvexHull

    v = np.load(npz)["v"].astype(np.float64) @ rot.T + shift
    try:
        return v[ConvexHull(v).vertices]
    except Exception:  # noqa: BLE001  (flat or degenerate point sets: fall back to all points)
        return v
