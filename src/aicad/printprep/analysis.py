"""Print-readiness analysis of a triangle mesh: topology, wall thickness, gaps, holes/pins, overhangs, bridges,
build-volume fit, orientation ranking and rough estimates.

All numbers are deterministic geometry measurements. Limits come from editable process presets (assumptions).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from aicad.printprep import DISCLOSURE, VERSION
from aicad.printprep.bvh import BVH, segments_hit_triangles
from aicad.printprep.mesh import Mesh, signed_volume, tri_vectors

LEVEL_GEOM = "Verified calculation"     # deterministic, unit-tested geometry measurement
LEVEL_EST = "Preliminary estimate"      # rough model with stated assumptions
LEVEL_ADVICE = "Recommended check"      # guidance to confirm in the slicer

MAX_RAYS = 80_000
MAX_SELFX_TRIS = 250_000


# ------------------------------------------------------------------ topology
def edge_maps(f: np.ndarray, n_vert: int) -> dict[str, np.ndarray]:
    d = f[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)
    und = np.sort(d, axis=1)
    key = und[:, 0] * np.int64(n_vert) + und[:, 1]
    uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    dkey = d[:, 0] * np.int64(n_vert) + d[:, 1]
    _, dcnt = np.unique(dkey, return_counts=True)
    face_of = np.repeat(np.arange(len(f)), 3)
    return {"edge_key": uk, "inv": inv, "count": cnt, "dir_dups": int((dcnt > 1).sum()), "face_of": face_of,
            "half": d}


def face_adjacency(f: np.ndarray, n_vert: int, em: dict[str, np.ndarray] | None = None) -> np.ndarray:
    """(k,2) pairs of faces sharing a manifold edge."""
    em = em or edge_maps(f, n_vert)
    inv, cnt, face_of = em["inv"], em["count"], em["face_of"]
    sel = cnt[inv] == 2
    order = np.argsort(inv[sel], kind="stable")
    fo = face_of[sel][order]
    return fo.reshape(-1, 2)


def components(f: np.ndarray, n_vert: int) -> np.ndarray:
    """Shell label per triangle (connected through shared vertices)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    if len(f) == 0:
        return np.zeros(0, dtype=np.int64)
    r = np.concatenate([f[:, 0], f[:, 1]])
    c = np.concatenate([f[:, 1], f[:, 2]])
    g = coo_matrix((np.ones(len(r)), (r, c)), shape=(n_vert, n_vert))
    _, lab = connected_components(g, directed=False)
    return lab[f[:, 0]]


def boundary_loops(f: np.ndarray, n_vert: int, em: dict[str, np.ndarray] | None = None) -> list[list[int]]:
    """Closed loops of boundary edges, ordered so a filling triangle fan has winding consistent with the mesh."""
    em = em or edge_maps(f, n_vert)
    half, inv, cnt = em["half"], em["inv"], em["count"]
    b = half[cnt[inv] == 1]
    nxt: dict[int, list[int]] = {}
    for u, w in b.tolist():  # boundary half-edge u->w; the hole runs w->u
        nxt.setdefault(w, []).append(u)
    loops: list[list[int]] = []
    used: set[tuple[int, int]] = set()
    for w0 in sorted(nxt):
        for u0 in sorted(nxt[w0]):
            if (w0, u0) in used:
                continue
            loop = [w0]
            cur, nx = w0, u0
            ok = True
            while True:
                used.add((cur, nx))
                if nx == w0:
                    break
                loop.append(nx)
                cand = [x for x in nxt.get(nx, []) if (nx, x) not in used]
                if not cand or len(loop) > 100_000:
                    ok = False
                    break
                cur, nx = nx, min(cand)
            if ok and len(loop) >= 3:
                loops.append(loop)
    return loops


def topology(mesh: Mesh) -> dict[str, Any]:
    v, f = mesh.v, mesh.f
    em = edge_maps(f, len(v))
    cnt = em["count"]
    _n, areas, _ = tri_vectors(v, f)
    lab = components(f, len(v))
    shells = int(lab.max() + 1) if len(lab) else 0
    vol = signed_volume(v, f)
    loops = boundary_loops(f, len(v), em) if (cnt == 1).any() else []
    return {"vertices": len(v), "triangles": len(f), "edges": len(cnt),
            "boundary_edges": int((cnt == 1).sum()), "nonmanifold_edges": int((cnt > 2).sum()),
            "inconsistent_edges": int(em["dir_dups"]), "degenerate_faces": int((areas <= 1e-12).sum()),
            "holes": len(loops), "shells": shells, "volume_mm3": vol, "area_mm2": float(areas.sum()),
            "euler": int(len(v) - len(cnt) + len(f))}


def self_intersections(mesh: Mesh, bvh: BVH) -> dict[str, Any]:
    if mesh.n_tri > MAX_SELFX_TRIS:
        return {"run": False, "reason": f"skipped above {MAX_SELFX_TRIS:,} triangles"}
    pairs = bvh.overlapping_pairs()
    if pairs is None:
        return {"run": False, "reason": "too many overlapping candidates"}
    f, v = mesh.f, mesh.v
    if len(pairs):
        fa, fb = f[pairs[:, 0]], f[pairs[:, 1]]
        share = (fa[:, :, None] == fb[:, None, :]).any(axis=(1, 2))
        pairs = pairs[~share]
    hit = np.zeros(len(pairs), dtype=bool)
    for s in range(0, len(pairs), 400_000):
        pp = pairs[s:s + 400_000]
        ta, tb = v[f[pp[:, 0]]], v[f[pp[:, 1]]]
        h = np.zeros(len(pp), dtype=bool)
        for x, y in ((tb, ta), (ta, tb)):
            for p, q in ((0, 1), (1, 2), (2, 0)):
                h |= segments_hit_triangles(y[:, p], y[:, q], x[:, 0], x[:, 1], x[:, 2])
        hit[s:s + 400_000] = h
    bad = pairs[hit]
    tris = np.unique(bad.reshape(-1)) if len(bad) else np.zeros(0, dtype=np.int64)
    return {"run": True, "pairs": len(bad), "triangles": tris[:5000].tolist(),
            "method": "segment-triangle tests on bounding-box candidate pairs (coplanar overlaps not detected)"}


# ------------------------------------------------------------------ ray-based measurements
def _samples(mesh: Mesh, n: np.ndarray, areas: np.ndarray, cen: np.ndarray) -> tuple[np.ndarray, ...]:
    """Ray origins: every triangle centroid, plus three interior points on large triangles (deterministic)."""
    ok = areas > 1e-12
    tri = np.flatnonzero(ok)
    if len(tri) > MAX_RAYS:
        tri = tri[np.linspace(0, len(tri) - 1, MAX_RAYS).astype(np.int64)]
    pts = [cen[tri]]
    ids = [tri]
    budget = MAX_RAYS - len(tri)
    if budget > 0 and len(tri):
        big = tri[areas[tri] > 4 * np.median(areas[tri])]
        big = big[np.argsort(-areas[big], kind="stable")][: budget // 3]
        if len(big):
            a, b, c = (mesh.v[mesh.f[big, k]] for k in range(3))
            for wa, wb, wc in ((0.6, 0.2, 0.2), (0.2, 0.6, 0.2), (0.2, 0.2, 0.6)):
                pts.append(wa * a + wb * b + wc * c)
                ids.append(big)
    return np.concatenate(pts), np.concatenate(ids)


def thickness_map(mesh: Mesh, bvh: BVH, cap: float, outward: bool = False) -> np.ndarray:
    """Per-triangle distance to the opposite surface along the inward normal (wall thickness), or along the
    outward normal to the next surface (gap). Values above `cap` are reported as inf (not thin)."""
    n, areas, cen = tri_vectors(mesh.v, mesh.f)
    pts, ids = _samples(mesh, n, areas, cen)
    d = n[ids] if outward else -n[ids]
    dist, _ = bvh.closest_hit(pts, d, cap, t_min=1e-7, facing=-1 if outward else 1, skip=ids)
    out = np.full(mesh.n_tri, np.inf)
    np.minimum.at(out, ids, dist)
    sampled = np.zeros(mesh.n_tri, dtype=bool)
    sampled[ids] = True
    if not sampled.all() and sampled.any():  # very large meshes: nearest sampled triangle for the colour map
        from scipy.spatial import cKDTree

        miss = np.flatnonzero(~sampled)
        src = np.flatnonzero(sampled)
        _, j = cKDTree(cen[src]).query(cen[miss])
        out[miss] = out[src[j]]
    return out


def thin_regions(mesh: Mesh, vals: np.ndarray, limit: float, areas: np.ndarray, cen: np.ndarray,
                 names: list[str | None] | None) -> list[dict[str, Any]]:
    """Groups of triangles below `limit`: per exact face for models, connected patches for plain meshes."""
    thin = np.flatnonzero(vals < limit)
    if not len(thin):
        return []
    groups: dict[int, list[int]] = {}
    if mesh.region is not None:
        for t in thin.tolist():
            groups.setdefault(int(mesh.region[t]), []).append(t)
    else:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components

        adj = face_adjacency(mesh.f, len(mesh.v))
        mask = np.zeros(mesh.n_tri, dtype=bool)
        mask[thin] = True
        adj = adj[mask[adj[:, 0]] & mask[adj[:, 1]]] if len(adj) else adj
        g = coo_matrix((np.ones(len(adj)), (adj[:, 0], adj[:, 1])), shape=(mesh.n_tri, mesh.n_tri))
        _, lab = connected_components(g, directed=False)
        for t in thin.tolist():
            groups.setdefault(int(lab[t]), []).append(t)
    out = []
    for key, ts in groups.items():
        ts_a = np.array(ts)
        a = float(areas[ts_a].sum())
        w = areas[ts_a] / a if a > 0 else np.full(len(ts_a), 1 / len(ts_a))
        rec: dict[str, Any] = {"min_mm": float(vals[ts_a].min()), "area_mm2": a,
                               "at": [float(x) for x in (cen[ts_a] * w[:, None]).sum(axis=0)],
                               "triangles": len(ts_a)}
        if mesh.region is not None:
            rec["face"] = key
            if names and key < len(names) and names[key]:
                rec["feature"] = names[key]
        out.append(rec)
    out.sort(key=lambda r: (r["min_mm"], -r["area_mm2"]))
    return out[:25]


def cylinders(mesh: Mesh) -> list[dict[str, Any]]:
    """Holes and pins of the exact model (cylindrical faces spanning >= 180 deg / >= 300 deg)."""
    faces = mesh.meta.get("_faces")
    if not faces or mesh.region is None:
        return []
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_Cylinder

    n, _areas, cen = tri_vectors(mesh.v, mesh.f)
    out = []
    for fid, fc in enumerate(faces):
        ad = BRepAdaptor_Surface(fc.wrapped)
        if ad.GetType() != GeomAbs_Cylinder:
            continue
        cyl = ad.Cylinder()
        r = cyl.Radius()
        ax = cyl.Axis()
        p0 = np.array([ax.Location().X(), ax.Location().Y(), ax.Location().Z()])
        a = np.array([ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()])
        umin, umax, vmin, vmax = BRepTools.UVBounds_s(fc.wrapped)
        span = math.degrees(umax - umin)
        ts = np.flatnonzero(mesh.region == fid)
        if not len(ts):
            continue
        rad = cen[ts] - p0 - np.outer((cen[ts] - p0) @ a, a)
        s = float(np.einsum("ij,ij->i", rad, n[ts]).sum())
        kind = "hole" if s < 0 else "pin"
        if (kind == "hole" and span < 179.0) or (kind == "pin" and span < 299.0):
            continue
        out.append({"face": fid, "kind": kind, "diameter_mm": 2 * r, "length_mm": float(vmax - vmin),
                    "span_deg": min(span, 360.0), "axis": a.tolist(),
                    "at": [float(x) for x in cen[ts].mean(axis=0)]})
    return out


# ------------------------------------------------------------------ orientation
def rotation_to_down(d: np.ndarray) -> np.ndarray:
    """Rotation taking unit vector d to (0, 0, -1)."""
    d = d / np.linalg.norm(d)
    t = np.array([0.0, 0.0, -1.0])
    c = float(d @ t)
    if c > 1 - 1e-12:
        return np.eye(3)
    if c < -1 + 1e-12:
        return np.diag([1.0, -1.0, -1.0])  # 180 deg about X
    ax = np.cross(d, t)
    s = np.linalg.norm(ax)
    ax /= s
    k = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    ang = math.atan2(s, c)
    return np.eye(3) + math.sin(ang) * k + (1 - math.cos(ang)) * (k @ k)


def _rz(theta: float) -> np.ndarray:
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def _min_rect(xy: np.ndarray) -> tuple[float, float, float]:
    """(angle, w, h) of the minimum-area bounding rectangle of 2D points (rotating calipers on the hull)."""
    from scipy.spatial import ConvexHull, QhullError

    try:
        hull = xy[ConvexHull(xy).vertices]
    except (QhullError, ValueError):
        span = xy.max(axis=0) - xy.min(axis=0)
        return 0.0, float(span[0]), float(span[1])
    e = np.roll(hull, -1, axis=0) - hull
    angs = np.unique(np.round(np.mod(np.arctan2(e[:, 1], e[:, 0]), math.pi / 2), 9))
    best = (math.inf, 0.0, 0.0, 0.0)
    for a in angs.tolist():
        r = hull @ _rz(-a)[:2, :2].T
        span = r.max(axis=0) - r.min(axis=0)
        area = float(span[0] * span[1])
        if area < best[0] - 1e-9:
            best = (area, a, float(span[0]), float(span[1]))
    return best[1], best[2], best[3]


def euler_xyz(r: np.ndarray) -> list[float]:
    """Angles (deg) for 'rotate about X, then Y, then Z (fixed axes)': R = Rz @ Ry @ Rx."""
    b = math.degrees(math.asin(max(-1.0, min(1.0, -r[2, 0]))))
    if abs(r[2, 0]) < 1 - 1e-9:
        a = math.degrees(math.atan2(r[2, 1], r[2, 2]))
        c = math.degrees(math.atan2(r[1, 0], r[0, 0]))
    else:
        a = math.degrees(math.atan2(-r[1, 2], r[1, 1]))
        c = 0.0
    return [round(x, 2) + 0.0 for x in (a, b, c)]


def _axis_name(d: np.ndarray) -> str | None:
    for i, nm in enumerate("XYZ"):
        if abs(abs(d[i]) - 1) < 1e-9:
            return ("+" if d[i] > 0 else "−") + nm
    return None


def candidate_downs(mesh: Mesh, n: np.ndarray, areas: np.ndarray, cen: np.ndarray,
                    names: list[str | None] | None) -> list[dict[str, Any]]:
    total = float(areas.sum())
    cands: list[dict[str, Any]] = [{"down": np.array([0.0, 0.0, -1.0]), "kind": "as_modelled",
                                    "label": "As modelled"}]
    for i in range(3):
        for sgn in (-1.0, 1.0):
            d = np.zeros(3)
            d[i] = sgn
            cands.append({"down": d, "kind": "axis", "label": f"Model {_axis_name(d)} down"})
    # flat faces resting on the bed: normal groups lying on a supporting plane of the part
    key = np.round(n * 2000).astype(np.int64)
    ok = areas > 1e-12
    _uk, inv = np.unique(key[ok], axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    garea = np.bincount(inv, weights=areas[ok])
    order = np.argsort(-garea, kind="stable")
    for g in order[:40].tolist():
        if garea[g] < 0.01 * total:
            break
        tris = np.flatnonzero(ok)[inv == g]
        d = (n[tris] * areas[tris, None]).sum(axis=0)
        d /= np.linalg.norm(d)
        top = float((mesh.v @ d).max())
        on = tris[(cen[tris] @ d) >= top - 1e-3]
        if areas[on].sum() < 0.01 * total:
            continue
        label = f"Flat face down ({areas[on].sum():,.0f} mm²)"
        if mesh.region is not None and names:
            regs = np.unique(mesh.region[on])
            nm = next((names[r] for r in regs.tolist() if r < len(names) and names[r]), None)
            if nm:
                label = f"{nm} face down ({areas[on].sum():,.0f} mm²)"
        cands.append({"down": d, "kind": "flat_face", "label": label})
    # principal axes of the surface: exact area-weighted second moments of the triangles
    tri = mesh.v[mesh.f]
    c0 = (cen * areas[:, None]).sum(axis=0) / max(total, 1e-12)
    rel = tri - c0
    ssum = rel.sum(axis=1)
    cov = (np.einsum("k,kij,kil->jl", areas, rel, rel) + np.einsum("k,kj,kl->jl", areas, ssum, ssum)) / 12.0
    _, vecs = np.linalg.eigh(cov)
    for k in range(3):
        for sgn, tag in ((-1.0, "−"), (1.0, "+")):
            d = vecs[:, k] * sgn
            d = np.where(np.abs(d) < 1e-9, 0.0, d)
            cands.append({"down": d / np.linalg.norm(d), "kind": "principal",
                          "label": f"Principal axis {3 - k} ({tag}) down"})
    out: list[dict[str, Any]] = []
    for cnd in cands:
        if all(float(cnd["down"] @ o["down"]) < math.cos(math.radians(2.0)) for o in out):
            out.append(cnd)
    return out


def orientation_metrics(mesh: Mesh, bvh: BVH, rot: np.ndarray, s: dict[str, Any], n: np.ndarray,
                        areas: np.ndarray, cen: np.ndarray, volume: float, area: float,
                        adj: np.ndarray, hull_pts: np.ndarray) -> dict[str, Any]:
    vr = mesh.v @ rot.T
    nr = n @ rot.T
    zmin = float(vr[:, 2].min())
    zmax = float(vr[:, 2].max())
    height = zmax - zmin
    bed_eps = float(s.get("bed_eps_mm", 0.02))
    tri_zmax = vr[mesh.f, 2].max(axis=1)
    contact = (nr[:, 2] < -0.999) & (tri_zmax <= zmin + bed_eps)
    thr = -math.sin(math.radians(float(s["overhang_deg"])))
    over = (nr[:, 2] < thr) & ~contact & (areas > 1e-12)
    ot = np.flatnonzero(over)
    proj = areas[ot] * np.abs(nr[ot, 2])
    support_area = float(proj.sum())
    # support height: drop a ray from each overhang triangle to the bed or to the part below
    sv = 0.0
    on_part = 0.0
    if len(ot):
        smp = ot if len(ot) <= MAX_RAYS else ot[np.linspace(0, len(ot) - 1, MAX_RAYS).astype(np.int64)]
        w = (len(ot) / len(smp))
        down = rot.T @ np.array([0.0, 0.0, -1.0])
        h_bed = (cen[smp] @ rot.T)[:, 2] - zmin
        dist, _ = bvh.closest_hit(cen[smp], np.broadcast_to(down, (len(smp), 3)).copy(), h_bed + 1e-6,
                                  t_min=1e-6, facing=-1, skip=smp)
        lands = np.isfinite(dist)
        h = np.where(lands, dist, h_bed)
        pa = areas[smp] * np.abs(nr[smp, 2])
        sv = float((pa * h).sum() * w)
        on_part = float(pa[lands].sum() * w)
    # bridges: horizontal undersides (not on the bed) and their shortest span
    horiz = (nr[:, 2] < -math.cos(math.radians(2.0))) & ~contact & (areas > 1e-12)
    bridges = _bridges(mesh, vr, horiz, adj, areas, s)
    # footprint and build-volume fit
    xy = (hull_pts @ rot.T)[:, :2]
    span = xy.max(axis=0) - xy.min(axis=0)
    px, py, pz = (float(x) for x in s["printer_mm"])
    fits = height <= pz + 1e-9 and ((span[0] <= px and span[1] <= py) or (span[0] <= py and span[1] <= px))
    layers = math.ceil(height / float(s["layer_mm"]) - 1e-9) if height > 0 else 0
    est = estimate(s, volume, area, layers, sv)
    return {"height_mm": height, "footprint_mm": [float(span[0]), float(span[1])], "fits": bool(fits),
            "contact_area_mm2": float(areas[contact].sum()), "overhang_area_mm2": float(areas[ot].sum()),
            "support_area_mm2": support_area, "support_volume_mm3": sv, "support_on_part_mm2": on_part,
            "bridges": bridges, "layers": layers, "estimate": est, "zmin": zmin}


def _bridges(mesh: Mesh, vr: np.ndarray, horiz: np.ndarray, adj: np.ndarray, areas: np.ndarray,
             s: dict[str, Any]) -> dict[str, Any]:
    idx = np.flatnonzero(horiz)
    if not len(idx):
        return {"count": 0, "max_span_mm": 0.0, "regions": []}
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    a = adj[horiz[adj[:, 0]] & horiz[adj[:, 1]]] if len(adj) else adj
    g = coo_matrix((np.ones(len(a)), (a[:, 0], a[:, 1])), shape=(mesh.n_tri, mesh.n_tri))
    _, lab = connected_components(g, directed=False)
    regions = []
    for lb in np.unique(lab[idx]).tolist():
        ts = idx[lab[idx] == lb]
        pts = vr[mesh.f[ts]].reshape(-1, 3)[:, :2]
        _, w, h = _min_rect(np.unique(np.round(pts, 6), axis=0))
        regions.append({"span_mm": float(min(w, h)), "length_mm": float(max(w, h)),
                        "area_mm2": float(areas[ts].sum()), "z_mm": float(vr[mesh.f[ts], 2].mean())})
    regions.sort(key=lambda r: (-r["area_mm2"], r["span_mm"]))
    lim = s.get("max_bridge_mm")
    for r in regions:
        r["bridgeable"] = bool(lim) and r["span_mm"] <= float(lim)
    return {"count": len(regions), "max_span_mm": max(r["span_mm"] for r in regions), "regions": regions[:20]}


def estimate(s: dict[str, Any], volume: float, area: float, layers: int, support_volume: float) -> dict[str, Any]:
    """Rough print time and material model (labelled estimate; slicers differ, often by 30 % or more)."""
    if s["code"] == "fdm":
        shell = min(volume, area * float(s["shell_mm"]))
        deposited = shell + max(volume - shell, 0.0) * float(s["infill"])
        sup = support_volume * float(s["support_density"]) if s.get("supports") else 0.0
        t = (deposited + sup) / float(s["flow_mm3_s"]) + layers * float(s["layer_overhead_s"])
        return {"time_s": t, "part_material_mm3": deposited, "support_material_mm3": sup,
                "model": f"(shell {s['shell_mm']} mm + {s['infill'] * 100:.0f}% infill + "
                         f"{s['support_density'] * 100:.0f}% dense supports) / {s['flow_mm3_s']} mm³/s + "
                         f"{s['layer_overhead_s']} s per layer"}
    t = layers * float(s["layer_overhead_s"])
    note = ("layers × time per layer (resin cure + peel); supports excluded" if s["code"] == "sla" else
            "layers × time per layer for a build of this height; a shared batch spreads it across parts")
    return {"time_s": t, "part_material_mm3": volume, "support_material_mm3": 0.0, "model": note}


def strength_note(rot: np.ndarray, s: dict[str, Any], load: np.ndarray | None) -> tuple[str, float]:
    """(note, penalty). Print Z (layer stacking) is the weak axis for FDM."""
    zm = rot.T @ np.array([0.0, 0.0, 1.0])  # model direction that becomes print Z
    name = _axis_name(np.round(zm, 9)) or "an oblique axis"
    if not s.get("anisotropic"):
        return (("Near-isotropic process: orientation has little effect on strength (verify with the material "
                "datasheet)."), 0.0)
    if load is None:
        return ((f"Layers stack along model {name.lstrip('+−')}: loads along that axis pull layers apart "
                "(weakest direction for FDM). Set a load direction to rank for strength."), 0.0)
    c = abs(float(load @ zm))
    if c > 0.7:
        return (("The load direction runs across layers (weakest for FDM). Prefer an orientation where the load "
                "lies in the layer plane."), 0.6)
    if c < 0.3:
        return "The load direction lies in the layer plane (strongest for FDM).", 0.0
    return "The load direction is oblique to the layers (intermediate strength for FDM).", 0.25


def rank_orientations(mesh: Mesh, bvh: BVH, s: dict[str, Any], names: list[str | None] | None,
                      load: np.ndarray | None, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    n, areas, cen = ctx["n"], ctx["areas"], ctx["cen"]
    cands = candidate_downs(mesh, n, areas, cen, names)
    rows = []
    for c in cands:
        r0 = np.eye(3) if c["kind"] == "as_modelled" else rotation_to_down(c["down"])
        rot = r0
        if c["kind"] != "as_modelled":
            xy = (ctx["hull"] @ r0.T)[:, :2]
            span0 = xy.max(axis=0) - xy.min(axis=0)
            ang, w, h = _min_rect(xy)
            if w * h < 0.99 * span0[0] * span0[1]:
                rot = _rz(-ang) @ r0
                span0 = np.array([w, h])
            if span0[1] > span0[0] + 1e-9:
                rot = _rz(math.pi / 2) @ rot
            rot = np.where(np.abs(rot) < 1e-12, 0.0, rot)
        m = orientation_metrics(mesh, bvh, rot, s, n, areas, cen, ctx["volume"], ctx["area"], ctx["adj"],
                                ctx["hull"])
        note, pen = strength_note(rot, s, load)
        rows.append({"kind": c["kind"], "label": c["label"], "down": [float(x) for x in c["down"]],
                     "rotation": rot.round(12).tolist(), "euler_xyz_deg": euler_xyz(rot), **m,
                     "strength_note": note, "_pen": pen})
    max_h = max((r["height_mm"] for r in rows), default=1.0) or 1.0
    max_c = max((r["contact_area_mm2"] for r in rows), default=0.0)
    total = ctx["area"] or 1.0
    w_sup = 1.0 if s.get("supports") else 0.0
    w_h = 0.35 if s.get("supports") else 1.0
    w_c = 0.2 if s["code"] == "fdm" else 0.0
    for r in rows:
        sup = r["support_area_mm2"] / total
        cont = 1.0 - (min(1.0, r["contact_area_mm2"] / max_c) if max_c > 0 else 0.0)
        cost = w_sup * 4 * sup + w_h * r["height_mm"] / max_h + w_c * cont + r.pop("_pen") + (0 if r["fits"] else 5)
        r["score"] = round(float(cost), 6)
        r["cost_terms"] = {"support": round(w_sup * 4 * sup, 4), "height": round(w_h * r["height_mm"] / max_h, 4),
                           "contact": round(w_c * cont, 4)}
        r["rationale"] = _rationale(r, s, total)
    rows.sort(key=lambda r: (r["score"], r["kind"] != "as_modelled", r["label"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
        r["id"] = f"o{i + 1}"
    return rows


def _rationale(r: dict[str, Any], s: dict[str, Any], total: float) -> list[str]:
    out = []
    if not s.get("supports"):
        out.append("No support structures (powder-supported process)")
    elif r["support_area_mm2"] < 0.5:
        out.append("No supports needed at this overhang angle")
    else:
        pct = 100 * r["support_area_mm2"] / total
        txt = f"Supports under about {r['support_area_mm2']:,.0f} mm² ({pct:.0f}% of the surface)"
        if r["support_on_part_mm2"] > 0.5:
            txt += f", {r['support_on_part_mm2']:,.0f} mm² of it resting on the part"
        out.append(txt)
    out.append(f"{r['height_mm']:,.1f} mm tall ({r['layers']:,} layers at {s['layer_mm']:g} mm)")
    if s["code"] == "fdm":
        if r["contact_area_mm2"] >= 1.0:
            out.append(f"{r['contact_area_mm2']:,.0f} mm² flat on the bed")
        else:
            out.append("No flat face on the bed: needs supports or a brim to hold it")
    if not r["fits"]:
        fx, fy = r["footprint_mm"]
        out.append(f"Does not fit the {' × '.join(f'{x:g}' for x in s['printer_mm'])} mm build volume "
                   f"(needs {fx:,.1f} × {fy:,.1f} × {r['height_mm']:,.1f} mm)")
    return out


# ------------------------------------------------------------------ report
def _status(ok: bool, warn: bool = False) -> str:
    return "pass" if ok else ("warn" if warn else "fail")


def analyse(mesh: Mesh, bvh: BVH, s: dict[str, Any], material: dict[str, Any] | None,
            load_dir: str | None = None, names: list[str | None] | None = None,
            cache: dict[str, Any] | None = None) -> dict[str, Any]:
    """Full report. `cache` (optional dict) memoises orientation-independent ray maps between calls."""
    cache = cache if cache is not None else {}
    n, areas, cen = tri_vectors(mesh.v, mesh.f)
    topo = cache.get("topo") or topology(mesh)
    cache["topo"] = topo
    volume = abs(topo["volume_mm3"])
    area = topo["area_mm2"]
    bb = mesh.v.max(axis=0) - mesh.v.min(axis=0)
    diag = float(np.linalg.norm(bb)) or 1.0
    checks: list[dict[str, Any]] = []

    def add(cid: str, name: str, status: str, value: Any, limit: Any = None, unit: str = "", detail: str = "",
            level: str = LEVEL_GEOM, assumption: bool = False, **extra: Any) -> None:
        checks.append({"id": cid, "name": name, "status": status, "value": value, "limit": limit, "unit": unit,
                       "detail": detail, "level": level, "limit_is_assumption": assumption, **extra})

    wt = topo["boundary_edges"] == 0
    add("PP-01", "Watertight (closed surface)", _status(wt), topo["boundary_edges"], 0, "open edges",
        "No open edges: every edge is shared by two triangles." if wt else
        f"{topo['boundary_edges']:,} open edges forming {topo['holes']} hole(s). Slicers may fill or skip them.")
    mf = topo["nonmanifold_edges"] == 0
    add("PP-02", "Manifold edges", _status(mf), topo["nonmanifold_edges"], 0, "edges",
        "Every edge borders at most two triangles." if mf else
        f"{topo['nonmanifold_edges']:,} edges are shared by more than two triangles.")
    wind = topo["inconsistent_edges"] == 0 and (topo["volume_mm3"] > 0 or not wt)
    add("PP-03", "Consistent winding, normals outward", _status(wind), topo["inconsistent_edges"], 0, "edges",
        "Triangle winding is consistent and encloses positive volume." if wind else
        ("Signed volume is negative: normals point inward." if topo["inconsistent_edges"] == 0 else
         f"{topo['inconsistent_edges']:,} edges have neighbouring triangles with opposite winding."))
    deg = topo["degenerate_faces"]
    add("PP-04", "Degenerate triangles", _status(deg == 0, warn=True), deg, 0, "triangles",
        "No zero-area triangles." if deg == 0 else f"{deg:,} zero-area triangles (harmless to most slicers).")
    sx = cache.get("selfx") or self_intersections(mesh, bvh)
    cache["selfx"] = sx
    if sx["run"]:
        add("PP-05", "Self-intersection", _status(sx["pairs"] == 0, warn=True), sx["pairs"], 0, "triangle pairs",
            "No intersecting triangle pairs found." if sx["pairs"] == 0 else
            f"{sx['pairs']:,} intersecting triangle pairs. Slicers usually merge them, but check the preview.",
            method=sx["method"], triangles=sx["triangles"])
    else:
        add("PP-05", "Self-intersection", "info", None, None, "", f"Not run ({sx['reason']}).")
    add("PP-06", "Separate shells", "pass" if topo["shells"] == 1 else "info", topo["shells"], None, "shells",
        "One connected shell." if topo["shells"] == 1 else f"{topo['shells']} separate shells (bodies or loose "
        "pieces); each prints as its own object.")
    dev = mesh.meta.get("deviation")
    if dev is not None:
        tol = float(mesh.meta["tolerance"])
        ok = dev["max_mm"] <= tol * 1.05 + 1e-6
        add("PP-07", "Tessellation deviation from the exact model", _status(ok, warn=True), dev["max_mm"], tol,
            "mm", f"Max sampled distance from the mesh to the exact surface ({dev['samples']:,} samples); "
            f"volume differs by {100 * (mesh.meta.get('volume_rel_dev') or 0):.3f}%.")

    # wall thickness
    min_wall, warn_wall = float(s["min_wall_mm"]), float(s["warn_wall_mm"])
    cap = max(5 * warn_wall, 10.0)
    tkey = ("thick", round(cap, 6))
    th = cache.get(tkey)
    if th is None:
        th = cache[tkey] = thickness_map(mesh, bvh, cap)
    fin = np.isfinite(th)
    tmin = float(th[fin].min()) if fin.any() else None
    below_min = float(areas[th < min_wall].sum())
    below_warn = float(areas[th < warn_wall].sum())
    noise = max(0.25, 1e-4 * area)
    st = "pass" if below_warn <= noise else ("warn" if below_min <= noise else "fail")
    regions = thin_regions(mesh, th, warn_wall, areas, cen, names)
    add("PP-08", "Minimum wall thickness", st, tmin, min_wall, "mm",
        (f"Thinnest wall {tmin:.2f} mm (measured along the inward normal). " if tmin is not None else
         f"No wall thinner than {cap:g} mm. ") +
        (f"{below_min:,.1f} mm² below {min_wall:g} mm. " if below_min > noise else "") +
        (f"{below_warn:,.1f} mm² below {warn_wall:g} mm." if below_warn > noise else
         f"All walls are at least {warn_wall:g} mm."), assumption=True, regions=regions)
    # narrow gaps
    min_gap = float(s["min_gap_mm"])
    gkey = ("gap", round(3 * min_gap, 6))
    gp = cache.get(gkey)
    if gp is None:
        gp = cache[gkey] = thickness_map(mesh, bvh, 3 * min_gap, outward=True)
    gap_area = float(areas[gp < min_gap].sum())
    gfin = np.isfinite(gp)
    add("PP-09", "Narrow gaps and slots", "pass" if gap_area <= noise else "warn",
        float(gp[gfin].min()) if gfin.any() else None, min_gap, "mm",
        f"No gaps narrower than {min_gap:g} mm." if gap_area <= noise else
        f"{gap_area:,.1f} mm² of surface faces another surface closer than {min_gap:g} mm: these may fuse.",
        assumption=True, regions=thin_regions(mesh, gp, min_gap, areas, cen, names))
    # holes and pins (exact model only)
    cyl = cache.get("cyl")
    if cyl is None:
        cyl = cache["cyl"] = cylinders(mesh)
    if mesh.region is not None and mesh.meta.get("_faces"):
        small_h = [c for c in cyl if c["kind"] == "hole" and c["diameter_mm"] < float(s["min_hole_mm"]) - 1e-9]
        small_p = [c for c in cyl if c["kind"] == "pin" and c["diameter_mm"] < float(s["min_pin_mm"]) - 1e-9]
        nh = sum(1 for c in cyl if c["kind"] == "hole")
        add("PP-10", "Small holes", "pass" if not small_h else "warn",
            min((c["diameter_mm"] for c in small_h), default=None), s["min_hole_mm"], "mm Ø",
            f"{nh} hole(s), none below Ø{s['min_hole_mm']:g} mm." if not small_h else
            f"{len(small_h)} hole(s) below Ø{s['min_hole_mm']:g} mm may close up or print undersize; plan to "
            "drill or ream them.", assumption=True, items=small_h)
        add("PP-11", "Thin pins and bosses", "pass" if not small_p else "warn",
            min((c["diameter_mm"] for c in small_p), default=None), s["min_pin_mm"], "mm Ø",
            "No pins below the minimum diameter." if not small_p else
            f"{len(small_p)} pin(s) below Ø{s['min_pin_mm']:g} mm may break or print poorly.", assumption=True,
            items=small_p)
    else:
        add("PP-10", "Small holes and pins", "info", None, s["min_hole_mm"], "mm Ø",
            "Needs exact geometry: not available for an uploaded mesh. Thin walls and narrow gaps are still checked.")
    # tiny shells (small features)
    lab = components(mesh.f, len(mesh.v))
    tiny = []
    for k in range(int(lab.max()) + 1 if len(lab) else 0):
        vv = mesh.v[np.unique(mesh.f[lab == k])]
        ext = float((vv.max(axis=0) - vv.min(axis=0)).max())
        if ext < float(s["min_feature_mm"]):
            tiny.append({"shell": k, "size_mm": ext})
    add("PP-12", "Small features", "pass" if not tiny else "warn", len(tiny), s["min_feature_mm"], "mm",
        f"No loose pieces smaller than {s['min_feature_mm']:g} mm." if not tiny else
        f"{len(tiny)} piece(s) smaller than {s['min_feature_mm']:g} mm may not print.", assumption=True, items=tiny)

    # orientations
    from scipy.spatial import ConvexHull, QhullError

    try:
        hull = mesh.v[ConvexHull(mesh.v).vertices]
    except (QhullError, ValueError):
        hull = mesh.v
    adj = face_adjacency(mesh.f, len(mesh.v))
    load = None
    if load_dir in ("X", "Y", "Z"):
        load = np.eye(3)[["X", "Y", "Z"].index(load_dir)]
    ctx = {"n": n, "areas": areas, "cen": cen, "volume": volume, "area": area, "adj": adj, "hull": hull}
    orients = rank_orientations(mesh, bvh, s, names, load, ctx)
    for o in orients:
        o["checks"] = orientation_checks(o, s)
    dens = float(material["density_g_cm3"]) if material else None
    est = {"volume_mm3": volume, "area_mm2": area, "bbox_mm": [float(x) for x in bb],
           "mass_solid_g": volume * dens / 1000 if dens else None, "density_g_cm3": dens,
           "level": LEVEL_EST}
    for o in orients:
        e = o["estimate"]
        e["part_mass_g"] = e["part_material_mm3"] * dens / 1000 if dens else None
        e["support_mass_g"] = e["support_material_mm3"] * dens / 1000 if dens else None
        e["level"] = LEVEL_EST
    pct_thick = {}
    if fin.any():
        pct_thick = {"p5": float(np.percentile(th[fin], 5)), "median": float(np.median(th[fin]))}
    return {
        "version": VERSION, "disclosure": DISCLOSURE, "units": "mm",
        "process": {k: s[k] for k in s if not k.startswith("_")},
        "material": material, "topology": topo, "checks": checks, "orientations": orients,
        "estimates": est,
        "thickness": {"min_mm": tmin, "cap_mm": cap, "min_wall_mm": min_wall, "warn_wall_mm": warn_wall,
                      "below_min_mm2": below_min, "below_warn_mm2": below_warn, **pct_thick},
        "overhang": {"angle_deg": float(s["overhang_deg"]), "bed_eps_mm": float(s.get("bed_eps_mm", 0.02)),
                     "rule": "A downward-facing triangle needs support when its normal is more than the overhang "
                             "angle away from vertical (n_z < -sin(angle)); triangles on the bed are excluded."},
        "cylinders": cyl, "diag_mm": diag,
        "summary": summary(checks, orients[0] if orients else None),
    }


def orientation_checks(o: dict[str, Any], s: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    px, py, pz = s["printer_mm"]
    out.append({"id": "PP-13", "name": "Fits the build volume", "status": "pass" if o["fits"] else "fail",
                "value": [*o["footprint_mm"], o["height_mm"]], "limit": [px, py, pz], "unit": "mm",
                "detail": (f"{o['footprint_mm'][0]:,.1f} × {o['footprint_mm'][1]:,.1f} × {o['height_mm']:,.1f} mm "
                           f"in a {px:g} × {py:g} × {pz:g} mm volume."), "level": LEVEL_GEOM,
                "limit_is_assumption": True})
    if s.get("supports"):
        sa = o["support_area_mm2"]
        out.append({"id": "PP-14", "name": f"Overhangs beyond {s['overhang_deg']:g}°",
                    "status": "pass" if sa < 0.5 else "warn", "value": sa, "limit": s["overhang_deg"],
                    "unit": "mm² to support",
                    "detail": ("No overhangs need support." if sa < 0.5 else
                               f"{o['overhang_area_mm2']:,.0f} mm² of overhanging surface; about {sa:,.0f} mm² of "
                               f"support footprint and {o['support_volume_mm3'] / 1000:,.1f} cm³ of support "
                               "envelope (estimate)."),
                    "level": LEVEL_ADVICE, "limit_is_assumption": True})
    else:
        out.append({"id": "PP-14", "name": "Overhangs", "status": "info", "value": o["overhang_area_mm2"],
                    "limit": None, "unit": "mm²", "detail": "Powder-supported: overhangs need no support structures.",
                    "level": LEVEL_ADVICE, "limit_is_assumption": False})
    b = o["bridges"]
    lim = s.get("max_bridge_mm")
    if b["count"] and lim:
        long_ = [r for r in b["regions"] if not r["bridgeable"]]
        out.append({"id": "PP-15", "name": "Bridges", "status": "pass" if not long_ else "warn",
                    "value": b["max_span_mm"], "limit": lim, "unit": "mm span",
                    "detail": (f"{b['count']} horizontal underside(s); the widest unsupported span is "
                               f"{b['max_span_mm']:,.1f} mm. " +
                               ("All can bridge if anchored at both ends." if not long_ else
                                f"{len(long_)} span(s) exceed {lim:g} mm and need support.")),
                    "level": LEVEL_ADVICE, "limit_is_assumption": True})
    elif s["code"] == "fdm":
        out.append({"id": "PP-15", "name": "Bridges", "status": "pass", "value": 0, "limit": lim, "unit": "mm span",
                    "detail": "No horizontal undersides above the bed.", "level": LEVEL_ADVICE,
                    "limit_is_assumption": True})
    if s["code"] == "fdm":
        c = o["contact_area_mm2"]
        out.append({"id": "PP-16", "name": "Bed contact", "status": "pass" if c >= 25 else "warn", "value": c,
                    "limit": 25, "unit": "mm²",
                    "detail": (f"{c:,.0f} mm² flat on the bed." if c >= 25 else
                               f"Only {c:,.1f} mm² flat on the bed: add a brim or supports for adhesion."),
                    "level": LEVEL_ADVICE, "limit_is_assumption": True})
    return out


def summary(checks: list[dict[str, Any]], best: dict[str, Any] | None) -> dict[str, Any]:
    allc = checks + (best["checks"] if best else [])
    worst = "fail" if any(c["status"] == "fail" for c in allc) else (
        "warn" if any(c["status"] == "warn" for c in allc) else "pass")
    return {"status": worst, "fails": sum(c["status"] == "fail" for c in allc),
            "warnings": sum(c["status"] == "warn" for c in allc)}
