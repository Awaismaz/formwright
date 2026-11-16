"""Triangle meshes: tessellation of the exact B-rep, safe STL/OBJ/3MF parsing, STL/3MF writing.

Units are millimetres throughout. Parsers are written for untrusted input: size and triangle caps, type sniffing,
no XML DTDs/entities, zip-bomb limits on 3MF, and no file paths taken from the upload.
"""

from __future__ import annotations

import io
import re
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import numpy as np

MAX_UPLOAD_BYTES = 40 * 1024 * 1024
MAX_TRIANGLES = 600_000
MAX_3MF_UNCOMPRESSED = 256 * 1024 * 1024

UNITS_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "micron": 0.001, "ft": 304.8}
_3MF_UNITS = {"micron": "micron", "millimeter": "mm", "centimeter": "cm", "inch": "in", "foot": "ft", "meter": "m"}
NS_3MF = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"


class MeshError(ValueError):
    """Input that cannot be turned into a mesh (message is user-facing, plain language)."""


@dataclass
class Mesh:
    v: np.ndarray                      # (n, 3) float64, mm
    f: np.ndarray                      # (m, 3) int64
    region: np.ndarray | None = None   # (m,) int32: exact B-rep face id per triangle, or None for plain meshes
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_tri(self) -> int:
        return len(self.f)

    def copy(self) -> Mesh:
        return Mesh(self.v.copy(), self.f.copy(), None if self.region is None else self.region.copy(),
                    dict(self.meta))

    def transformed(self, rot: np.ndarray, shift: np.ndarray | None = None) -> Mesh:
        v = self.v @ np.asarray(rot, float).T
        if shift is not None:
            v = v + np.asarray(shift, float)
        return Mesh(v, self.f.copy(), None if self.region is None else self.region.copy(), dict(self.meta))


# ------------------------------------------------------------------ basic geometry
def tri_vectors(v: np.ndarray, f: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Unit normals (m,3), areas (m,), centroids (m,3). Degenerate triangles get a zero normal."""
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    cr = np.cross(b - a, c - a)
    dbl = np.linalg.norm(cr, axis=1)
    n = np.zeros_like(cr)
    ok = dbl > 0
    n[ok] = cr[ok] / dbl[ok, None]
    return n, dbl / 2.0, (a + b + c) / 3.0


def signed_volume(v: np.ndarray, f: np.ndarray) -> float:
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def surface_area(v: np.ndarray, f: np.ndarray) -> float:
    return float(tri_vectors(v, f)[1].sum())


def merge_vertices(v: np.ndarray, f: np.ndarray, tol: float = 1e-6) -> tuple[np.ndarray, np.ndarray]:
    """Weld vertices closer than `tol` (deterministic: each cluster maps to its lowest original index)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree

    n = len(v)
    if n == 0:
        return v, f
    pairs = cKDTree(v).query_pairs(tol, output_type="ndarray")
    if len(pairs):
        g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
        _, lab = connected_components(g, directed=False)
        rep = np.full(lab.max() + 1, n, dtype=np.int64)
        np.minimum.at(rep, lab, np.arange(n))
        mapping = rep[lab]
    else:
        mapping = np.arange(n)
    f2 = mapping[f]
    used = np.unique(f2)
    new_index = np.full(n, -1, dtype=np.int64)
    new_index[used] = np.arange(len(used))
    return v[used].copy(), new_index[f2]


# ------------------------------------------------------------------ exact B-rep tessellation
def tessellate_shape(shape: Any, tolerance: float, angular_deg: float = 15.0) -> Mesh:
    """Mesh the exact B-rep with an absolute chordal tolerance (mm) and record the measured deviation.

    Triangles keep the B-rep face id (same order as topo.json: per solid, `solid.faces()`), so results can be
    reported per face/feature.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepTools import BRepTools
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location

    tolerance = float(tolerance)
    BRepTools.Clean_s(shape.wrapped)
    BRepMesh_IncrementalMesh(shape.wrapped, tolerance, False, float(np.radians(angular_deg)), False)
    kids = [c for c in (getattr(shape, "children", None) or ()) if c.solids()]
    bodies = kids if kids else (list(shape.solids()) or [shape])
    verts: list[np.ndarray] = []
    tris: list[np.ndarray] = []
    regs: list[np.ndarray] = []
    faces: list[Any] = []
    base = 0
    for sol in bodies:
        for face in sol.faces():
            fid = len(faces)
            faces.append(face)
            loc = TopLoc_Location()
            poly = BRep_Tool.Triangulation_s(face.wrapped, loc)
            if poly is None:
                continue
            trsf = loc.Transformation()
            nn = poly.NbNodes()
            pts = np.empty((nn, 3))
            for i in range(1, nn + 1):
                p = poly.Node(i).Transformed(trsf)
                pts[i - 1] = (p.X(), p.Y(), p.Z())
            nt = poly.NbTriangles()
            tri = np.empty((nt, 3), dtype=np.int64)
            for i in range(1, nt + 1):
                t = poly.Triangle(i)
                tri[i - 1] = t.Get()
            tri -= 1
            if face.wrapped.Orientation() == TopAbs_REVERSED:
                tri = tri[:, [0, 2, 1]]
            verts.append(pts)
            tris.append(tri + base)
            regs.append(np.full(nt, fid, dtype=np.int32))
            base += nn
    if not tris:
        raise MeshError("The model produced no triangles")
    v = np.concatenate(verts)
    f = np.concatenate(tris)
    region = np.concatenate(regs)
    v, f = merge_vertices(v, f, tol=min(max(tolerance * 0.01, 1e-6), 1e-3))
    mesh = Mesh(v, f, region, {"source": "brep", "tolerance": tolerance, "angular_deg": angular_deg,
                               "n_faces": len(faces)})
    mesh.meta["deviation"] = measure_deviation(mesh, faces)
    exact_v = float(sum(abs(s.volume) for s in bodies))
    mv = signed_volume(mesh.v, mesh.f)
    mesh.meta["exact_volume"] = exact_v
    mesh.meta["volume_rel_dev"] = abs(mv - exact_v) / exact_v if exact_v > 0 else None
    mesh.meta["_faces"] = faces  # kept in memory only (not serialised): exact faces for hole/pin info
    return mesh


def measure_deviation(mesh: Mesh, faces: list[Any], max_samples: int = 6000) -> dict[str, Any]:
    """Max distance from mesh sample points (edge midpoints and centroids) to the exact surface of their face.

    Plane faces are exact by construction (deviation 0) and skipped. Samples are taken with a deterministic stride.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.gp import gp_Pnt

    assert mesh.region is not None
    curved = [i for i, fc in enumerate(faces) if BRepAdaptor_Surface(fc.wrapped).GetType() != GeomAbs_Plane]
    if not curved:
        return {"max_mm": 0.0, "samples": 0, "method": "all faces planar (exact)"}
    sel = np.flatnonzero(np.isin(mesh.region, curved))
    v, f = mesh.v, mesh.f
    per = 4
    stride = max(1, int(np.ceil(len(sel) * per / max_samples)))
    sel = sel[::stride]
    a, b, c = v[f[sel, 0]], v[f[sel, 1]], v[f[sel, 2]]
    samples = np.stack([(a + b) / 2, (b + c) / 2, (c + a) / 2, (a + b + c) / 3], axis=1)  # (k,4,3)
    surfs: dict[int, Any] = {}
    worst = 0.0
    for k, t in enumerate(sel):
        fid = int(mesh.region[t])
        s = surfs.get(fid)
        if s is None:
            s = surfs[fid] = BRep_Tool.Surface_s(faces[fid].wrapped)
        for p in samples[k]:
            proj = GeomAPI_ProjectPointOnSurf(gp_Pnt(*map(float, p)), s)
            if proj.NbPoints() > 0:
                worst = max(worst, proj.LowerDistance())
    return {"max_mm": float(worst), "samples": int(len(sel) * per),
            "method": "edge midpoints and centroids projected onto the exact surface"}


def load_step(path: Path) -> Any:
    from build123d import import_step

    return import_step(str(path))


# ------------------------------------------------------------------ parsing uploads
def sniff(data: bytes, filename: str = "") -> str:
    """Return 'stl-binary' | 'stl-ascii' | 'obj' | '3mf' from the content (the extension is only a tie-breaker)."""
    if data[:4] == b"PK\x03\x04":
        return "3mf"
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if 84 + 50 * n == len(data):
            return "stl-binary"
    head = data[:4096]
    if b"\x00" in head:
        raise MeshError("Unrecognised binary file. Upload an STL, OBJ or 3MF mesh.")
    text = head.decode("latin-1").lower()
    if text.lstrip().startswith("solid") and ("facet" in text or len(data) < 4096):
        return "stl-ascii"
    if re.search(r"(?m)^\s*v\s+[-+0-9.]", text):
        return "obj"
    raise MeshError("Unrecognised file. Upload an STL (binary or ASCII), OBJ or 3MF mesh.")


def _check_tris(n: int) -> None:
    if n == 0:
        raise MeshError("The file contains no triangles")
    if n > MAX_TRIANGLES:
        raise MeshError(f"The mesh has {n:,} triangles; the limit is {MAX_TRIANGLES:,}. Decimate it first.")


def _finish(tris: np.ndarray, scale: float) -> tuple[np.ndarray, np.ndarray]:
    if not np.all(np.isfinite(tris)):
        raise MeshError("The mesh contains invalid (non-finite) coordinates")
    pts = tris.reshape(-1, 3).astype(np.float64) * scale
    f = np.arange(len(pts), dtype=np.int64).reshape(-1, 3)
    return merge_vertices(pts, f, tol=1e-5)


def parse_stl_binary(data: bytes) -> np.ndarray:
    n = struct.unpack_from("<I", data, 80)[0]
    _check_tris(n)
    rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=n,
                        offset=84)
    return rec["v"].astype(np.float64)


def parse_stl_ascii(data: bytes) -> np.ndarray:
    text = data.decode("latin-1")
    nums = re.findall(r"(?im)^\s*vertex\s+(\S+)\s+(\S+)\s+(\S+)", text)
    if len(nums) % 3:
        raise MeshError("The ASCII STL is truncated (vertex count is not a multiple of 3)")
    _check_tris(len(nums) // 3)
    try:
        arr = np.array(nums, dtype=np.float64)
    except ValueError as e:
        raise MeshError("The ASCII STL has unreadable coordinates") from e
    return arr.reshape(-1, 3, 3)


def parse_obj(data: bytes) -> np.ndarray:
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for line in data.decode("latin-1").splitlines():
        s = line.strip()
        if s.startswith("v "):
            p = s.split()
            if len(p) < 4:
                raise MeshError("The OBJ file has a malformed vertex line")
            try:
                verts.append((float(p[1]), float(p[2]), float(p[3])))
            except ValueError as e:
                raise MeshError("The OBJ file has unreadable coordinates") from e
        elif s.startswith("f "):
            idx = []
            for tok in s.split()[1:]:
                try:
                    i = int(tok.split("/")[0])
                except ValueError as e:
                    raise MeshError("The OBJ file has a malformed face line") from e
                idx.append(i - 1 if i > 0 else len(verts) + i)
            for k in range(1, len(idx) - 1):  # fan-triangulate polygons
                faces.append((idx[0], idx[k], idx[k + 1]))
            if len(faces) > MAX_TRIANGLES:
                _check_tris(len(faces))
    _check_tris(len(faces))
    v = np.array(verts, dtype=np.float64)
    f = np.array(faces, dtype=np.int64)
    if f.min() < 0 or f.max() >= len(v):
        raise MeshError("The OBJ file references vertices that do not exist")
    return v[f]


def _mat_3mf(s: str | None) -> np.ndarray:
    m = np.eye(4)
    if s:
        vals = [float(x) for x in s.split()]
        if len(vals) != 12:
            raise MeshError("The 3MF file has a malformed transform")
        m[:3, :3] = np.array(vals[:9]).reshape(3, 3).T  # 3MF: row vectors, m00 m01 m02 m10 ... m30 m31 m32
        m[:3, 3] = vals[9:]
    return m


def parse_3mf(data: bytes) -> tuple[np.ndarray, float]:
    """Mesh objects (with components and build-item transforms) of the root 3D model part. Returns (tris, scale)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise MeshError("The 3MF file is not a valid package") from e
    total = sum(i.file_size for i in zf.infolist())
    if total > MAX_3MF_UNCOMPRESSED:
        raise MeshError("The 3MF package expands to more than 256 MB")
    names = {i.filename.lstrip("/"): i for i in zf.infolist()}
    model = next((n for n in names if n.lower() == "3d/3dmodel.model"), None)
    if model is None:
        model = next((n for n in names if n.lower().endswith(".model")), None)
    if model is None:
        raise MeshError("The 3MF package has no 3D model part")
    raw = zf.read(names[model])
    if b"<!DOCTYPE" in raw[:4096].upper() or b"<!ENTITY" in raw.upper():
        raise MeshError("The 3MF model uses XML declarations that are not allowed")
    try:
        root = ET.fromstring(raw)  # DOCTYPE/ENTITY declarations were rejected above
    except ET.ParseError as e:
        raise MeshError("The 3MF model XML is malformed") from e
    ns = root.tag[1:].split("}")[0] if root.tag.startswith("{") else ""
    q = (lambda t: f"{{{ns}}}{t}") if ns else (lambda t: t)
    scale = UNITS_TO_MM[_3MF_UNITS.get(root.get("unit", "millimeter"), "mm")]
    objects: dict[str, Any] = {}
    res = root.find(q("resources"))
    if res is None:
        raise MeshError("The 3MF model has no resources")
    for ob in res.findall(q("object")):
        objects[ob.get("id", "")] = ob
    count = [0]

    def emit(ob: Any, m: np.ndarray, depth: int) -> list[np.ndarray]:
        if depth > 8:
            raise MeshError("The 3MF components are nested too deeply")
        out: list[np.ndarray] = []
        me = ob.find(q("mesh"))
        if me is not None:
            vs = me.find(q("vertices"))
            ts = me.find(q("triangles"))
            if vs is None or ts is None:
                return out
            v = np.array([[float(x.get("x", 0)), float(x.get("y", 0)), float(x.get("z", 0))]
                          for x in vs.findall(q("vertex"))], dtype=np.float64)
            t = np.array([[int(x.get("v1", -1)), int(x.get("v2", -1)), int(x.get("v3", -1))]
                          for x in ts.findall(q("triangle"))], dtype=np.int64)
            if len(t) == 0:
                return out
            if t.min() < 0 or t.max() >= len(v):
                raise MeshError("The 3MF mesh references vertices that do not exist")
            count[0] += len(t)
            _check_tris(count[0])
            vh = np.c_[v, np.ones(len(v))] @ m.T
            out.append(vh[:, :3][t])
        comps = ob.find(q("components"))
        if comps is not None:
            for comp in comps.findall(q("component")):
                child = objects.get(comp.get("objectid", ""))
                if child is None:
                    raise MeshError("The 3MF file references an object that is not in the model part")
                out += emit(child, m @ _mat_3mf(comp.get("transform")), depth + 1)
        return out

    parts: list[np.ndarray] = []
    build = root.find(q("build"))
    items = build.findall(q("item")) if build is not None else []
    if items:
        for it in items:
            ob = objects.get(it.get("objectid", ""))
            if ob is not None:
                parts += emit(ob, _mat_3mf(it.get("transform")), 0)
    else:
        for ob in objects.values():
            parts += emit(ob, np.eye(4), 0)
    if not parts:
        raise MeshError("The 3MF file contains no mesh triangles")
    return np.concatenate(parts), scale


def parse_mesh(data: bytes, filename: str = "", units: str = "mm") -> Mesh:
    if len(data) > MAX_UPLOAD_BYTES:
        raise MeshError(f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    kind = sniff(data, filename)
    scale = UNITS_TO_MM.get(units)
    if scale is None:
        raise MeshError("Unknown units")
    file_units = units
    if kind == "stl-binary":
        tris = parse_stl_binary(data)
    elif kind == "stl-ascii":
        tris = parse_stl_ascii(data)
    elif kind == "obj":
        tris = parse_obj(data)
    else:
        tris, scale = parse_3mf(data)  # 3MF carries its own unit
        file_units = next(k for k, s in UNITS_TO_MM.items() if s == scale)
    v, f = _finish(tris, scale)
    return Mesh(v, f, None, {"source": "upload", "format": kind, "units": file_units, "scale_to_mm": scale})


# ------------------------------------------------------------------ writing
def write_stl(mesh: Mesh, path: Path, header: str = "Formwright 3D Print Prep, units mm") -> None:
    n, _, _ = tri_vectors(mesh.v, mesh.f)
    rec = np.zeros(mesh.n_tri, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    rec["n"] = n
    rec["v"] = mesh.v[mesh.f]
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as fh:
        fh.write(header.encode("ascii", "replace")[:80].ljust(80, b" "))
        fh.write(struct.pack("<I", mesh.n_tri))
        fh.write(rec.tobytes())
    tmp.replace(path)


_CT = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
       'content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships'
       '+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
       '</Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/'
         '2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/'
         '3dmanufacturing/2013/01/3dmodel"/></Relationships>')


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def write_3mf(mesh: Mesh, path: Path, title: str = "Part") -> None:
    """3MF core package, unit="millimeter", one object, one build item. Deterministic bytes (fixed zip dates)."""
    vs = "".join(f'<vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>' for x, y, z in mesh.v.tolist())
    ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in mesh.f.tolist())
    model = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" xmlns="{NS_3MF}">'
             f'<metadata name="Title">{_xml_escape(title)}</metadata>'
             '<metadata name="Application">Formwright 3D Print Prep</metadata>'
             f'<resources><object id="1" type="model" name="{_xml_escape(title)}"><mesh><vertices>{vs}</vertices>'
             f'<triangles>{ts}</triangles></mesh></object></resources><build><item objectid="1"/></build></model>')
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in (("[Content_Types].xml", _CT), ("_rels/.rels", _RELS), ("3D/3dmodel.model", model)):
            zi = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, body)
    tmp.replace(path)


def save_npz(mesh: Mesh, path: Path) -> None:
    tmp = path.with_name(path.stem + ".tmp.npz")
    np.savez_compressed(tmp, v=mesh.v, f=mesh.f, region=mesh.region if mesh.region is not None else np.zeros(0))
    tmp.replace(path)


def load_npz(path: Path) -> Mesh:
    d = np.load(path, allow_pickle=False)
    r = d["region"]
    return Mesh(d["v"], d["f"].astype(np.int64), r.astype(np.int32) if len(r) else None, {})
