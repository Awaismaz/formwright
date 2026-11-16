"""FX-01: parametric machined mounting plate (M0 spike, hand-written, no LLM).

Geometry: rectangular block, top-outer-edge chamfer, corner clearance holes (through),
centred rounded-rectangle blind pocket. All units millimetres. Z=0 is the bottom face.

`expected_volume` is an independent analytic calculation used by checks; it must not
call into the CAD kernel.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from build123d import (
    Align,
    Axis,
    Box,
    Cylinder,
    Part,
    Pos,
    Rectangle,
    RectangleRounded,
    chamfer,
    extrude,
)


class SpecError(ValueError):
    """Spec is geometrically invalid; message is user-readable."""


@dataclass(frozen=True)
class PlateSpec:
    length: float = 120.0  # X
    width: float = 80.0  # Y
    thickness: float = 10.0  # Z
    hole_diameter: float = 6.6  # M6 clearance, ISO 273 medium
    hole_edge_offset: float = 10.0  # hole centre to nearest X and Y edge
    pocket_length: float = 40.0
    pocket_width: float = 30.0
    pocket_depth: float = 4.0
    pocket_corner_radius: float = 3.0
    top_chamfer: float = 1.0
    material: str = "Al 6061-T6"
    name: str = "FX-01 mounting plate"

    def validate(self) -> None:
        errs: list[str] = []
        pos = ("length", "width", "thickness", "hole_diameter", "pocket_length",
               "pocket_width", "pocket_depth")
        for f in pos:
            if getattr(self, f) <= 0:
                errs.append(f"{f} must be > 0")
        if self.pocket_depth >= self.thickness:
            errs.append("pocket_depth must be < thickness (blind pocket)")
        if not 0 <= self.pocket_corner_radius < min(self.pocket_length, self.pocket_width) / 2:
            errs.append("pocket_corner_radius must be in [0, min(pocket L,W)/2)")
        if not 0 <= self.top_chamfer < self.thickness - self.pocket_depth:
            errs.append("top_chamfer must be in [0, thickness - pocket_depth)")
        r = self.hole_diameter / 2
        o = self.hole_edge_offset
        if o - r <= self.top_chamfer:
            errs.append("holes intersect edge chamfer or edge (hole_edge_offset too small)")
        hx, hy = self.length / 2 - o, self.width / 2 - o
        if hx <= 0 or hy <= 0:
            errs.append("hole_edge_offset too large for plate size")
        # holes must clear pocket (axis-aligned rectangle vs circle, conservative)
        if hx - r <= self.pocket_length / 2 and hy - r <= self.pocket_width / 2:
            errs.append("holes intersect pocket")
        if self.pocket_length / 2 >= self.length / 2 - self.top_chamfer or (
            self.pocket_width / 2 >= self.width / 2 - self.top_chamfer
        ):
            errs.append("pocket breaks through plate side")
        if errs:
            raise SpecError("; ".join(errs))

    def hole_centres(self) -> list[tuple[float, float]]:
        hx = self.length / 2 - self.hole_edge_offset
        hy = self.width / 2 - self.hole_edge_offset
        return [(sx * hx, sy * hy) for sx in (-1, 1) for sy in (-1, 1)]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_plate(spec: PlateSpec) -> Part:
    spec.validate()
    L, W, T = spec.length, spec.width, spec.thickness
    part = Box(L, W, T, align=(Align.CENTER, Align.CENTER, Align.MIN))
    if spec.top_chamfer > 0:
        top_edges = part.edges().group_by(Axis.Z)[-1]
        part = chamfer(top_edges, spec.top_chamfer)
    for x, y in spec.hole_centres():
        part -= Pos(x, y, T / 2) * Cylinder(spec.hole_diameter / 2, T + 2)
    pocket = extrude(
        RectangleRounded(spec.pocket_length, spec.pocket_width, spec.pocket_corner_radius)
        if spec.pocket_corner_radius > 0
        else Rectangle(spec.pocket_length, spec.pocket_width),
        amount=spec.pocket_depth,
    )
    part -= Pos(0, 0, T - spec.pocket_depth) * pocket
    part.label = spec.name
    return part


def expected_volume(spec: PlateSpec) -> float:
    """Analytic volume, independent of the kernel."""
    L, W, T, c = spec.length, spec.width, spec.thickness, spec.top_chamfer
    v = L * W * T
    # 45° chamfer on top perimeter: integral of removed area 2s(L+W) - 4s^2, s in [0, c]
    v -= (L + W) * c**2 - 4 * c**3 / 3
    v -= 4 * math.pi * (spec.hole_diameter / 2) ** 2 * T
    r = spec.pocket_corner_radius
    pocket_area = spec.pocket_length * spec.pocket_width - (4 - math.pi) * r**2
    v -= pocket_area * spec.pocket_depth
    return v
