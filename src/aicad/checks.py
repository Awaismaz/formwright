"""Deterministic geometry checks (VALIDATION.md CHK-*). Renders never gate acceptance; these do."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from build123d import Edge, Shape
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

BBOX_TOL_MM = 0.01
VOLUME_REL_TOL = 1e-3  # 0.1 %
ROUNDTRIP_REL_TOL = 1e-6


@dataclass
class CheckResult:
    id: str
    name: str
    passed: bool
    gating: bool = True
    detail: dict[str, Any] = field(default_factory=dict)


def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-12)


def bbox_size(shape: Shape) -> tuple[float, float, float]:
    bb = shape.bounding_box()
    return (bb.size.X, bb.size.Y, bb.size.Z)


def free_edge_count(shape: Shape) -> int:
    """Edges not shared by exactly two faces (closed manifold solid => 0)."""
    # Count every oriented edge occurrence per face (seam edges occur twice in one face).
    uses: Counter[Edge] = Counter()
    for f in shape.faces():
        exp = TopExp_Explorer(f.wrapped, TopAbs_EDGE)
        while exp.More():
            e = TopoDS.Edge(exp.Current())
            if not BRep_Tool.Degenerated_s(e):  # sphere/cone poles are degenerate, not free edges
                uses[Edge(e)] += 1
            exp.Next()
    return sum(1 for n in uses.values() if n != 2)


def cylinder_radii(shape: Shape, ndigits: int = 4) -> Counter[float]:
    radii: Counter[float] = Counter()
    for f in shape.faces():
        s = BRepAdaptor_Surface(f.wrapped)
        if s.GetType() == GeomAbs_Cylinder:
            radii[round(s.Cylinder().Radius(), ndigits)] += 1
    return radii


def _count(shape: Shape, kind: Any, skip_degenerated: bool = False) -> int:
    """len(shape.faces()) etc. without building a Python wrapper per sub-shape (same identity: TopoDS hash)."""
    seen: set[int] = set()
    exp = TopExp_Explorer(shape.wrapped, kind)
    while exp.More():
        cur = exp.Current()
        if not (skip_degenerated and BRep_Tool.Degenerated_s(TopoDS.Edge(cur))):
            seen.add(hash(cur))
        exp.Next()
    return len(seen)


def fingerprint(shape: Shape, volume: float | None = None) -> dict[str, Any]:
    sx, sy, sz = bbox_size(shape)
    return {
        "volume": round(shape.volume if volume is None else volume, 6),
        "bbox": [round(sx, 6), round(sy, 6), round(sz, 6)],
        "faces": _count(shape, TopAbs_FACE),
        "edges": _count(shape, TopAbs_EDGE, skip_degenerated=True),  # build123d's edges() leaves out degenerate ones
        "vertices": _count(shape, TopAbs_VERTEX),
        "solids": _count(shape, TopAbs_SOLID),
    }


def check_solid(shape: Shape, expected_solids: int = 1) -> list[CheckResult]:
    n = len(shape.solids())
    fe = free_edge_count(shape)
    return [
        CheckResult("CHK-02", "valid B-rep, solid count", shape.is_valid and n == expected_solids,
                    detail={"is_valid": shape.is_valid, "solids": n, "expected": expected_solids}),
        CheckResult("CHK-03", "closed manifold (no free edges)", fe == 0,
                    detail={"free_or_nonmanifold_edges": fe}),
    ]


def check_bbox(shape: Shape, expected: tuple[float, float, float]) -> CheckResult:
    got = bbox_size(shape)
    err = max(abs(g - e) for g, e in zip(got, expected, strict=True))
    return CheckResult("CHK-04", "bounding box", err <= BBOX_TOL_MM,
                       detail={"got_mm": got, "expected_mm": expected, "max_err_mm": err,
                               "tol_mm": BBOX_TOL_MM})


def check_volume(shape: Shape, expected: float, got: float | None = None) -> CheckResult:
    vol = shape.volume if got is None else got
    rel = _rel(vol, expected)
    return CheckResult("CHK-05", "volume vs analytic", rel <= VOLUME_REL_TOL,
                       detail={"got_mm3": vol, "expected_mm3": expected,
                               "rel_err": rel, "tol": VOLUME_REL_TOL})


def check_cylinders(shape: Shape, expected: dict[float, int]) -> CheckResult:
    got = cylinder_radii(shape)
    ok = all(got.get(round(r, 4), 0) == n for r, n in expected.items())
    return CheckResult("CHK-06", "feature census (cylindrical faces by radius)", ok,
                       detail={"got": {str(k): v for k, v in sorted(got.items())},
                               "expected": {str(k): v for k, v in expected.items()}})


def check_roundtrip(original: Shape, reimported: Shape, original_fp: dict[str, Any] | None = None) -> CheckResult:
    """CHK-07. ``original_fp``: the original's fingerprint when the build already computed it (saves a pass)."""
    rv, ov = reimported.volume, original.volume
    fo, fr = original_fp or fingerprint(original, volume=ov), fingerprint(reimported, volume=rv)
    vrel = _rel(rv, ov)
    berr = max(abs(a - b) for a, b in zip(fo["bbox"], fr["bbox"], strict=True))
    ok = vrel <= ROUNDTRIP_REL_TOL and berr <= 1e-6 and fo["solids"] == fr["solids"] \
        and fo["faces"] == fr["faces"]
    return CheckResult("CHK-07", "STEP export -> reimport", ok,
                       detail={"original": fo, "reimported": fr, "volume_rel_err": vrel,
                               "bbox_max_err_mm": berr})


def as_dicts(results: list[CheckResult]) -> list[dict[str, Any]]:
    return [asdict(r) for r in results]
