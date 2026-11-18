"""Independent read-back helpers for the IO-008 coordinate/unit round-trip matrix.

Every reader here is written from the file format's specification, not from the exporter that produced the file, so
a shared misconception (axis swap, mirror, wrong unit) cannot cancel out between writer and reader. The fixture is an
asymmetric, off-origin analytic part whose expectations are hand formulas (see ``tests/test_io_roundtrip.py``).
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

import numpy as np

# ------------------------------------------------------------------ meshes (triangles: (n, 3, 3) array, mm)


def signed_volume(tris: np.ndarray) -> float:
    """Divergence theorem over outward-wound triangles. A mirrored export flips winding, so the sign goes negative."""
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def bbox_minmax(tris: np.ndarray) -> list[float]:
    v = tris.reshape(-1, 3)
    return [*v.min(axis=0).tolist(), *v.max(axis=0).tolist()]


def top_cap_centre(tris: np.ndarray, tol: float = 1e-6) -> tuple[float, float, float]:
    """Centroid (area-weighted) of the triangles lying in the highest Z plane: the boss's top face in the fixture."""
    zmax = float(tris[:, :, 2].max())
    cap = tris[np.all(np.abs(tris[:, :, 2] - zmax) < tol, axis=1)]
    area = 0.5 * np.linalg.norm(np.cross(cap[:, 1] - cap[:, 0], cap[:, 2] - cap[:, 0]), axis=1)
    cen = cap.mean(axis=1)
    c = (cen * area[:, None]).sum(axis=0) / area.sum()
    return float(c[0]), float(c[1]), zmax


# ------------------------------------------------------------------ binary STL
def read_stl(path: Path) -> np.ndarray:
    data = path.read_bytes()
    n = struct.unpack_from("<I", data, 80)[0]
    rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=n,
                        offset=84)
    return rec["v"].astype(np.float64)


# ------------------------------------------------------------------ glTF 2.0 binary (GLB)
_COMP = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _quat(q: list[float]) -> np.ndarray:
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _node_matrix(n: dict[str, Any]) -> np.ndarray:
    if "matrix" in n:
        return np.array(n["matrix"], dtype=float).reshape(4, 4).T  # glTF matrices are column-major
    m = np.eye(4)
    s = np.diag(n.get("scale", [1, 1, 1]))
    m[:3, :3] = _quat(n.get("rotation", [0, 0, 0, 1])) @ s
    m[:3, 3] = n.get("translation", [0, 0, 0])
    return m


def read_glb(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    """World-space triangles of the default scene, in the file's own units (glTF: metres, +Y up)."""
    data = path.read_bytes()
    magic, ver, _ = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF" and ver == 2, "not a glTF 2.0 binary"
    off, js, binc = 12, None, b""
    while off < len(data):
        ln, kind = struct.unpack_from("<I4s", data, off)
        chunk = data[off + 8: off + 8 + ln]
        if kind == b"JSON":
            js = json.loads(chunk)
        elif kind == b"BIN\x00":
            binc = chunk
        off += 8 + ln
    assert js is not None

    def acc(i: int) -> np.ndarray:
        a = js["accessors"][i]
        bv = js["bufferViews"][a["bufferView"]]
        nc = _NCOMP[a["type"]]
        fmt = _COMP[a["componentType"]]
        size = struct.calcsize(fmt)
        stride = bv.get("byteStride") or size * nc
        start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        out = np.empty((a["count"], nc), dtype=np.float64)
        for k in range(a["count"]):
            out[k] = struct.unpack_from("<" + fmt * nc, binc, start + k * stride)
        return out

    tris: list[np.ndarray] = []

    def walk(ni: int, parent: np.ndarray) -> None:
        node = js["nodes"][ni]
        m = parent @ _node_matrix(node)
        if "mesh" in node:
            for prim in js["meshes"][node["mesh"]]["primitives"]:
                if prim.get("mode", 4) != 4:
                    continue
                pos = acc(prim["attributes"]["POSITION"])
                pos = (np.c_[pos, np.ones(len(pos))] @ m.T)[:, :3]
                idx = acc(prim["indices"]).astype(np.int64).reshape(-1, 3) if "indices" in prim \
                    else np.arange(len(pos)).reshape(-1, 3)
                tris.append(pos[idx])
        for c in node.get("children", []):
            walk(c, m)

    scene = js["scenes"][js.get("scene", 0)]
    for ni in scene["nodes"]:
        walk(ni, np.eye(4))
    return np.concatenate(tris), js


def gltf_to_cad_mm(tris: np.ndarray) -> np.ndarray:
    """glTF (metres, +Y up, +Z toward the viewer) -> Formwright (mm, +Z up): (x, y, z)_gl = (X, Z, -Y) / 1000."""
    x, y, z = tris[..., 0], tris[..., 1], tris[..., 2]
    return np.stack([x, -z, y], axis=-1) * 1000.0


# ------------------------------------------------------------------ STEP
def step_length_unit(path: Path) -> str:
    """The STEP file's declared length unit, e.g. 'MILLI.METRE' (empty prefix = metre)."""
    import re

    txt = path.read_text(encoding="latin-1")
    m = re.search(r"LENGTH_UNIT\(\)\s*NAMED_UNIT\(\*\)\s*SI_UNIT\((\$|\.\w+\.),\s*\.METRE\.\)", txt)
    if not m:
        m = re.search(r"SI_UNIT\((\$|\.\w+\.),\s*\.METRE\.\)", txt)
    if not m:
        return "unknown"
    prefix = m.group(1).strip(".")
    return f"{'' if prefix == '$' else prefix + '.'}METRE"


def shape_top_centre(shape: Any) -> tuple[float, float, float]:
    """Centre of the highest planar face of an exact B-rep shape (the fixture boss's top)."""
    faces = [f for f in shape.faces() if f.geom_type.name == "PLANE"]
    top = max(faces, key=lambda f: f.center().Z)
    c = top.center()
    return c.X, c.Y, c.Z


def close(a: float, b: float, tol: float) -> bool:
    return math.isfinite(a) and abs(a - b) <= tol
