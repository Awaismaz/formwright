"""Geometry-derived manufacturing features: tool accessibility and setups, wall thickness, holes, pockets,
internal corners, turning axis and sheet-likeness. Pure functions of a `PartGeom` (deterministic)."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np

from aicad.manufacturing.geometry import DIRS, FaceG, PartGeom, principal

COVER = 0.8  # a face counts as reachable when >= 80 % of its sampled area is reachable
WALL = 0.01  # |n·d| below this: the face is a wall for direction d (cut with the tool flank)


# ----------------------------------------------------------------------------- accessibility & setups
@dataclass
class Access:
    reach_mm: float
    flank_mm: float
    frac: dict[int, dict[str, float]]  # face -> direction -> reachable area fraction
    sample_dirs: dict[int, list[set[str]]]  # face -> per-sample set of reaching directions
    setups: list[str]  # minimal set of principal directions covering every coverable face
    undercut: list[int]  # faces not reachable from any of the six principal directions
    by_setup: dict[str, list[int]] = field(default_factory=dict)  # first setup reaching each face

    def reachable_from(self, i: int, d: str) -> bool:
        return self.frac.get(i, {}).get(d, 0.0) >= COVER


def accessibility(g: PartGeom, reach_mm: float = 50.0, flank_mm: float = 25.0) -> Access:
    """Which faces a 3-axis tool reaches from each principal direction.

    A sample is reachable from direction d when its outward normal faces d (n·d > 0, cut with the tool end) and lies
    within `reach_mm` of the part's top in that direction, or it is on a wall (n ⟂ d, cut with the tool flank) within
    `flank_mm` of the top; and the ray from the sample towards +d leaves the part without hitting it.
    """
    frac: dict[int, dict[str, float]] = {}
    sdirs: dict[int, list[set[str]]] = {}
    for f in g.faces:
        sdirs[f.i] = [set() for _ in f.samples]
        frac[f.i] = {}
        for name, d in DIRS:
            top = float(max(np.dot(g.bmin, d), np.dot(g.bmax, d)))
            ok_area = 0.0
            for k, s in enumerate(f.samples):
                nd = float(np.dot(s.n, d))
                if nd < -WALL:
                    continue
                limit = flank_mm if abs(nd) <= WALL else reach_mm
                if top - float(np.dot(s.p, d)) > limit + 1e-6:
                    continue
                if g.blocked(s.p + 1e-3 * s.n, d):
                    continue
                sdirs[f.i][k].add(name)
                ok_area += s.w
            frac[f.i][name] = ok_area / f.area if f.area > 0 else 0.0

    def cover(f: FaceG, dirs: tuple[str, ...]) -> float:
        if not f.samples or f.area <= 0:
            return 1.0
        return sum(s.w for k, s in enumerate(f.samples) if sdirs[f.i][k] & set(dirs)) / f.area

    names = tuple(n for n, _ in DIRS)
    coverable = [f for f in g.faces if cover(f, names) >= COVER]
    undercut = [f.i for f in g.faces if cover(f, names) < COVER]
    setups: list[str] = list(names)
    for k in range(1, 7):
        hit = next((c for c in itertools.combinations(names, k) if all(cover(f, c) >= COVER for f in coverable)),
                   None)
        if hit is not None:
            setups = list(hit)
            break
    by_setup: dict[str, list[int]] = {d: [] for d in setups}
    for f in coverable:
        for k in range(1, len(setups) + 1):
            if cover(f, tuple(setups[:k])) >= COVER:
                by_setup[setups[k - 1]].append(f.i)
                break
    return Access(reach_mm, flank_mm, frac, sdirs, setups, undercut, by_setup)


# ----------------------------------------------------------------------------- wall thickness
@dataclass
class Thick:
    face: int
    t: float  # distance through material along -n (mm)
    hit: int | None
    cos: float  # cosine between the start normal and the far face normal (-1: parallel opposite walls)
    w: float

    @property
    def opposed(self) -> bool:  # parallel, opposite walls (sheet test)
        return self.cos < -0.95

    @property
    def wall(self) -> bool:  # roughly opposite walls (within ~37 deg): a measurable wall thickness
        return self.cos < -0.8


def thickness(g: PartGeom) -> list[Thick]:
    """Ray from every face sample into the material along -n; distance to the first face hit."""
    out: list[Thick] = []
    for f in g.faces:
        for s in f.samples:
            r = g.ray(s.p, -s.n, 1e-5)
            if r is None:
                continue
            t, j = r
            cos = 1.0
            if j is not None:
                na = g.normal_at(g.faces[j], s.p - t * s.n)
                if na is not None:
                    cos = float(np.dot(na[1], s.n))
            out.append(Thick(f.i, float(t), j, cos, s.w))
    return out


# ----------------------------------------------------------------------------- holes
@dataclass
class Hole:
    faces: list[int]
    d: float
    axis: np.ndarray
    origin: np.ndarray  # point on the axis at the start of the hole (lowest axial coordinate)
    depth: float
    blind_ends: list[str]  # "+" / "-" ends closed by material
    bottom: str | None  # plane | cone | other (blind holes)

    @property
    def through(self) -> bool:
        return not self.blind_ends

    @property
    def ld(self) -> float:
        return self.depth / self.d if self.d > 0 else 0.0


def _canon(a: np.ndarray) -> np.ndarray:
    for c in a:
        if abs(c) > 1e-9:
            return a if c > 0 else -a
    return a


def holes(g: PartGeom) -> list[Hole]:
    groups: dict[tuple[float, ...], list[FaceG]] = {}
    for f in g.faces:
        if f.kind != "cylinder" or not f.concave or f.axis is None or f.axis_point is None or f.radius is None:
            continue
        a = _canon(f.axis)
        p0 = f.axis_point - np.dot(f.axis_point, a) * a
        key = (round(f.radius, 4), *np.round(a, 4), *np.round(p0, 3))
        groups.setdefault(key, []).append(f)
    out: list[Hole] = []
    for fs in groups.values():
        if sum(f.sweep or 0.0 for f in fs) < 2 * math.pi - 1e-3:
            continue  # partial cylinders are corners/slot ends, not holes
        f0 = fs[0]
        a = _canon(f0.axis)  # type: ignore[arg-type]
        p0 = f0.axis_point - np.dot(f0.axis_point, a) * a  # type: ignore[operator]
        lo = min(f.extent_along(a)[0] for f in fs)
        hi = max(f.extent_along(a)[1] for f in fs)
        d = 2 * float(f0.radius)  # type: ignore[arg-type]
        depth = hi - lo
        mid = p0 + 0.5 * (lo + hi) * a
        ends: list[str] = []
        bottom = None
        for sign, name in ((1.0, "+"), (-1.0, "-")):
            r = g.ray(mid, sign * a, 1e-6, 0.5 * depth + 0.6 * d)
            if r is not None:
                ends.append(name)
                if r[1] is not None:
                    k = g.faces[r[1]].kind
                    bottom = k if k in ("plane", "cone") else "other"
        out.append(Hole(sorted(f.i for f in fs), d, a, p0 + lo * a, depth, ends, bottom))
    out.sort(key=lambda h: (h.d, h.faces))
    return out


# ----------------------------------------------------------------------------- internal corners (partial concave cylinders)
@dataclass
class Corner:
    face: int
    r: float
    axis_dir: str | None  # principal direction the corner axis is reachable along (vertical corner)
    depth: float  # corner length along its axis
    kind: str  # vertical | blend


def corners(g: PartGeom, acc: Access, hole_list: list[Hole]) -> list[Corner]:
    hole_faces = {i for h in hole_list for i in h.faces}
    out: list[Corner] = []
    for f in g.faces:
        if f.kind != "cylinder" or not f.concave or f.i in hole_faces or f.axis is None or f.radius is None:
            continue
        lo, hi = f.extent_along(f.axis)
        # A pocket corner: reachable along its own axis and standing on a floor perpendicular to that axis.
        floor = any(g.faces[k].kind == "plane" and g.faces[k].normal is not None
                    and abs(float(np.dot(g.faces[k].normal, f.axis))) > 1 - 1e-6
                    for k in g.neighbours(f.i, "concave"))
        vdir = None
        for sign in (1.0, -1.0):
            name = principal(sign * f.axis, 1e-4)
            if floor and name and acc.reachable_from(f.i, name):
                vdir = name
                break
        out.append(Corner(f.i, float(f.radius), vdir, hi - lo, "vertical" if vdir else "blend"))
    return out


@dataclass
class SharpCorner:
    edge: int
    faces: tuple[int, int]
    length: float


def sharp_internal_corners(g: PartGeom, acc: Access) -> list[SharpCorner]:
    """Concave straight edges between two planes where neither plane can be cut by a tool's end face along its own
    (principal) normal: a rotating cutter leaves its radius there."""
    out: list[SharpCorner] = []
    for e in g.edges:
        if e.convexity != "concave" or e.kind != "line" or len(e.faces) != 2:
            continue
        a, b = (g.faces[k] for k in e.faces)
        if a.kind != "plane" or b.kind != "plane" or a.normal is None or b.normal is None:
            continue
        if abs(float(np.dot(a.normal, b.normal))) > 0.999:
            continue
        ok = False
        for f in (a, b):
            name = principal(f.normal, 1e-4)  # type: ignore[arg-type]
            if name and acc.reachable_from(f.i, name):
                ok = True
        if not ok:
            out.append(SharpCorner(e.i, (a.i, b.i), e.length))
    return out


# ----------------------------------------------------------------------------- pockets
def _wpercentile(vals: list[tuple[float, float]], q: float) -> float:
    """Area-weighted percentile of (value, weight) pairs (infinite values sort last)."""
    if not vals:
        return math.inf
    vals = sorted(vals)
    total = sum(w for _, w in vals)
    acc = 0.0
    for v, w in vals:
        acc += w
        if acc >= q * total - 1e-12:
            return v
    return vals[-1][0]


@dataclass
class Pocket:
    floor: int
    walls: list[int]
    direction: str
    depth: float
    width: float  # opening across the pocket at mid depth (25th percentile of floor samples, mm)


def pockets(g: PartGeom, acc: Access) -> list[Pocket]:
    out: list[Pocket] = []
    for f in g.faces:
        if f.kind != "plane" or f.normal is None:
            continue
        dname = principal(f.normal, 1e-4)
        if not dname or not acc.reachable_from(f.i, dname):
            continue
        walls = g.neighbours(f.i, "concave")
        if not walls:
            continue
        d = f.normal
        level = float(np.dot(f.center, d))
        depth = max(g.faces[w].extent_along(d)[1] for w in walls) - level
        if depth < 1e-3:
            continue
        u = next(v for _, v in DIRS if abs(float(np.dot(v, d))) < 0.5)
        v = np.cross(d, u)
        spans: list[tuple[float, float]] = []
        for s in f.samples:
            p = s.p + 0.5 * depth * d
            if g.inside(p):
                continue
            sw = math.inf
            for w in (u, v):
                r1, r2 = g.ray(p, w), g.ray(p, -w)
                if r1 is not None and r2 is not None:
                    sw = min(sw, r1[0] + r2[0])
            spans.append((sw, s.w))
        width = _wpercentile(spans, 0.25)
        if math.isfinite(width):
            out.append(Pocket(f.i, sorted(walls), dname, depth, width))
    return out


# ----------------------------------------------------------------------------- turning
@dataclass
class Turning:
    turnable: bool
    axis: np.ndarray | None = None
    axis_point: np.ndarray | None = None
    axis_name: str | None = None
    revolved_frac: float = 0.0
    length: float = 0.0
    max_d: float = 0.0
    revolved: list[int] = field(default_factory=list)
    secondary: list[int] = field(default_factory=list)  # faces needing milling / drilling after turning


def _on_axis(p: np.ndarray, a: np.ndarray, q: np.ndarray, tol: float) -> bool:
    r = p - q
    return float(np.linalg.norm(r - np.dot(r, a) * a)) < tol


def turning(g: PartGeom) -> Turning:
    cands: list[tuple[np.ndarray, np.ndarray]] = []
    for f in g.faces:
        if f.kind in ("cylinder", "cone", "torus") and f.axis is not None and f.axis_point is not None:
            a = _canon(f.axis)
            if not any(abs(float(np.dot(a, c[0]))) > 1 - 1e-6 and _on_axis(f.axis_point, a, c[1], 1e-3)
                       for c in cands):
                cands.append((a, f.axis_point))
    tol = max(1e-3, 1e-5 * g.diag)
    best = Turning(False)
    for a, q in cands:
        rev: list[int] = []
        for f in g.faces:
            if f.kind in ("cylinder", "cone", "torus") and f.axis is not None and f.axis_point is not None:
                if abs(float(np.dot(f.axis, a))) > 1 - 1e-6 and _on_axis(f.axis_point, a, q, tol):
                    rev.append(f.i)
            elif f.kind == "sphere" and f.axis_point is not None and _on_axis(f.axis_point, a, q, tol) or f.kind == "plane" and f.normal is not None and abs(float(np.dot(f.normal, a))) > 1 - 1e-6 \
                    and _on_axis(f.center, a, q, tol):
                rev.append(f.i)
        frac = sum(g.faces[i].area for i in rev) / g.area if g.area else 0.0
        if frac > best.revolved_frac:
            pts = np.vstack([f.verts for f in g.faces if len(f.verts)])
            rel = pts - q
            ax = rel @ a
            rad = np.linalg.norm(rel - np.outer(ax, a), axis=1)
            maxr = float(rad.max())
            for i in rev:
                f = g.faces[i]
                if f.kind == "cylinder" and not f.concave and f.radius:
                    maxr = max(maxr, float(f.radius))
            best = Turning(False, a, q, principal(a, 1e-6) or principal(-a, 1e-6), frac, float(ax.max() - ax.min()),
                           2 * maxr, sorted(rev), sorted(f.i for f in g.faces if f.i not in rev))
    # Turnable: most of the surface is revolved about one axis and the outermost surface is a coaxial cylinder.
    if best.axis is not None and best.revolved_frac >= 0.6:
        outer = [g.faces[i] for i in best.revolved if g.faces[i].kind == "cylinder" and not g.faces[i].concave]
        if outer and abs(2 * max(float(f.radius or 0) for f in outer) - best.max_d) < 1e-3 * max(1.0, best.max_d):
            best.turnable = True
    return best


# ----------------------------------------------------------------------------- sheet-likeness
@dataclass
class Sheet:
    sheet_like: bool
    thickness: float | None
    frac: float
    model: bool = False  # the part carries a sheet-metal model (CAD-026): flat pattern and bends are known


def sheet_like(g: PartGeom, th: list[Thick], max_t: float = 6.0) -> Sheet:
    """Constant-thickness shell test: most of the surface sees the same through-thickness to an opposed face."""
    if not th:
        return Sheet(False, None, 0.0)
    hist: dict[float, float] = {}
    for s in th:
        if s.opposed:
            k = round(s.t, 2)
            hist[k] = hist.get(k, 0.0) + s.w
    if not hist:
        return Sheet(False, None, 0.0)
    t0 = max(sorted(hist), key=lambda k: hist[k])
    # Edge strips (faces about one thickness wide: sheet edges, hole walls) don't count towards the test.
    strips = {f.i for f in g.faces if f.area <= 1.1 * t0 * sum(g.edges[e].length for e in f.edges)}
    body = [s for s in th if s.face not in strips]
    total = sum(s.w for s in body)
    near = sum(s.w for s in body if s.opposed and abs(s.t - t0) <= 0.05 * t0 + 0.02)
    frac = near / total if total else 0.0
    kinds_ok = all(f.kind in ("plane", "cylinder") for f in g.faces)
    return Sheet(frac >= 0.8 and t0 <= max_t and kinds_ok, float(t0), frac)
