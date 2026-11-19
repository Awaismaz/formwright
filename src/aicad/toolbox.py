"""Formwright Toolbox: deterministic, versioned generators for frequently used mechanical components.

Every component is produced by pure code from a small set of numeric parameters (standard tables where a
standard exists), so the same inputs always give byte-identical STEP. Each generator also returns its
EXPECTED values computed analytically (closed-form volumes, shoelace areas), never by measuring the result,
so the normal CHK-04/05 verification applies.

Use from a model script:   from aicad import toolbox
                           result, EXPECTED = toolbox.build("hex_bolt", D=8, L=30)

Simplifications are stated per component (threads are cosmetic: shanks/bores at nominal diameter).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

VERSION = 3  # v3 (2026-11-20): spur gear flanks are true involute splines (were polylines: faceted teeth). v2: bearing ISO 582 chamfers
SQ3 = math.sqrt(3.0)

# ------------------------------------------------------------------------------------------------ tables
# ISO 4017/4014 hex head: d -> (s across flats, k head height)
HEX_HEAD = {3: (5.5, 2.0), 4: (7.0, 2.8), 5: (8.0, 3.5), 6: (10.0, 4.0), 8: (13.0, 5.3), 10: (16.0, 6.4),
            12: (18.0, 7.5), 16: (24.0, 10.0), 20: (30.0, 12.5), 24: (36.0, 15.0)}
# ISO 4762 socket head cap screw: d -> (dk head dia, k head height, s socket across flats, t socket depth)
SHCS = {3: (5.5, 3.0, 2.5, 1.3), 4: (7.0, 4.0, 3.0, 2.0), 5: (8.5, 5.0, 4.0, 2.5), 6: (10.0, 6.0, 5.0, 3.0),
        8: (13.0, 8.0, 6.0, 4.0), 10: (16.0, 10.0, 8.0, 5.0), 12: (18.0, 12.0, 10.0, 6.0), 16: (24.0, 16.0, 14.0, 8.0),
        20: (30.0, 20.0, 17.0, 10.0), 24: (36.0, 24.0, 19.0, 12.0)}
# ISO 4032 hex nut height m
NUT_M = {3: 2.4, 4: 3.2, 5: 4.7, 6: 5.2, 8: 6.8, 10: 8.4, 12: 10.8, 16: 14.8, 20: 18.0, 24: 21.5}
# ISO 7089 plain washer: d -> (d1 inner, d2 outer, h)
WASHER = {3: (3.2, 7.0, 0.5), 4: (4.3, 9.0, 0.8), 5: (5.3, 10.0, 1.0), 6: (6.4, 12.0, 1.6), 8: (8.4, 16.0, 1.6),
          10: (10.5, 20.0, 2.0), 12: (13.0, 24.0, 2.5), 16: (17.0, 30.0, 3.0), 20: (21.0, 37.0, 3.0), 24: (25.0, 44.0, 4.0)}
# Deep-groove ball bearings 60xx / 62xx: designation -> (d, D, B)
BEARING = {6000: (10, 26, 8), 6001: (12, 28, 8), 6002: (15, 32, 9), 6003: (17, 35, 10), 6004: (20, 42, 12),
           6005: (25, 47, 12), 6006: (30, 55, 13), 6200: (10, 30, 9), 6201: (12, 32, 10), 6202: (15, 35, 11),
           6203: (17, 40, 12), 6204: (20, 47, 14), 6205: (25, 52, 15), 6206: (30, 62, 16), 6207: (35, 72, 17),
           6208: (40, 80, 18)}
# ISO 15 boundary dimensions with the ISO 582 chamfer dimension r_s min (bore and outside corners of both rings), as
# printed in rolling-bearing catalogues (e.g. SKF 60xx / 62xx tables): designation -> r_s min. Unverified (PD-13).
BEARING_RS = {6000: 0.3, 6001: 0.3, 6002: 0.3, 6003: 0.3, 6004: 0.6, 6005: 0.6, 6006: 1.0, 6200: 0.6, 6201: 0.6,
              6202: 0.6, 6203: 0.6, 6204: 1.0, 6205: 1.0, 6206: 1.0, 6207: 1.1, 6208: 1.1}
# DIN 6885-1 parallel keys: shaft range (over, up to) -> (b width, t1 shaft groove depth)
KEYS = [((8, 10), (3, 1.8)), ((10, 12), (4, 2.5)), ((12, 17), (5, 3.0)), ((17, 22), (6, 3.5)), ((22, 30), (8, 4.0)),
        ((30, 38), (10, 5.0)), ((38, 44), (12, 5.0)), ((44, 50), (14, 5.5)), ((50, 58), (16, 6.0)), ((58, 65), (18, 7.0))]
# DIN 6885-1:1968 parallel keys, the full row: shaft Ø (over, up to) -> (b, h, t1 shaft depth, t2 hub depth). Same
# values as ``office.icd.KEYS`` (one standard, two consumers; a test keeps them equal). d = 20 -> 6 x 6, t1 3.5, t2 2.8.
KEY_ROWS = [((8, 10), (3, 3, 1.8, 1.4)), ((10, 12), (4, 4, 2.5, 1.8)), ((12, 17), (5, 5, 3.0, 2.3)),
            ((17, 22), (6, 6, 3.5, 2.8)), ((22, 30), (8, 7, 4.0, 3.3)), ((30, 38), (10, 8, 5.0, 3.3)),
            ((38, 44), (12, 8, 5.0, 3.3)), ((44, 50), (14, 9, 5.5, 3.8)), ((50, 58), (16, 10, 6.0, 4.3)),
            ((58, 65), (18, 11, 7.0, 4.4))]
# DIN 6885-1 preferred key lengths l (mm)
KEY_LENGTHS = (6, 8, 10, 12, 14, 16, 18, 20, 22, 25, 28, 32, 36, 40, 45, 50, 56, 63, 70, 80, 90, 100, 110, 125, 140,
               160, 180, 200)
# DIN 471:2011-04 external retaining rings for shafts, normal type: shaft d1 -> (s ring thickness, b radial width
# approx. (the narrow section opposite the lugs), d2 groove Ø, m groove width (H13), n min edge distance of the groove
# from the shaft end). Typed from a distributor's reprint of the DIN 471 table (Aspen Fasteners, "Metric DIN 471
# External Retaining Rings for Shafts"); unverified against the standard itself (PD-13). d1 = 20 -> s 1.2, d2 19.0,
# m 1.3, n 1.5 (groove depth t = (d1 - d2) / 2 = 0.5).
DIN471 = {8: (0.8, 1.5, 7.6, 0.9, 0.6), 9: (1.0, 1.7, 8.6, 1.1, 0.6), 10: (1.0, 1.8, 9.6, 1.1, 0.6),
          11: (1.0, 1.8, 10.5, 1.1, 0.8), 12: (1.0, 1.8, 11.5, 1.1, 0.8), 13: (1.0, 2.0, 12.4, 1.1, 0.9),
          14: (1.0, 2.1, 13.4, 1.1, 0.9), 15: (1.0, 2.2, 14.3, 1.1, 1.1), 16: (1.0, 2.2, 15.2, 1.1, 1.2),
          17: (1.0, 2.3, 16.2, 1.1, 1.2), 18: (1.2, 2.4, 17.0, 1.3, 1.5), 19: (1.2, 2.5, 18.0, 1.3, 1.5),
          20: (1.2, 2.6, 19.0, 1.3, 1.5), 21: (1.2, 2.7, 20.0, 1.3, 1.5), 22: (1.2, 2.8, 21.0, 1.3, 1.5),
          24: (1.2, 3.0, 22.9, 1.3, 1.7), 25: (1.2, 3.0, 23.9, 1.3, 1.7), 26: (1.2, 3.1, 24.9, 1.3, 1.7),
          28: (1.5, 3.2, 26.6, 1.6, 2.1), 30: (1.5, 3.5, 28.6, 1.6, 2.1), 32: (1.5, 3.6, 30.3, 1.6, 2.6),
          34: (1.5, 3.8, 32.3, 1.6, 2.6), 35: (1.5, 3.9, 33.0, 1.6, 3.0), 36: (1.8, 4.0, 34.0, 1.85, 3.0),
          38: (1.8, 4.2, 36.0, 1.85, 3.0), 40: (1.8, 4.4, 37.5, 1.85, 3.8), 42: (1.8, 4.5, 39.5, 1.85, 3.8),
          45: (1.8, 4.7, 42.5, 1.85, 3.8), 48: (2.0, 5.0, 45.5, 1.85, 3.8), 50: (2.0, 5.1, 47.0, 2.15, 4.5),
          52: (2.0, 5.2, 49.0, 2.15, 4.5), 55: (2.0, 5.4, 52.0, 2.15, 4.5), 56: (2.0, 5.5, 53.0, 2.15, 4.5),
          58: (2.0, 5.6, 55.0, 2.15, 4.5), 60: (2.0, 5.8, 57.0, 2.15, 4.5), 62: (2.0, 6.0, 59.0, 2.15, 4.5),
          63: (2.0, 6.2, 60.0, 2.15, 4.5), 65: (2.5, 6.3, 62.0, 2.65, 4.5)}
METRIC = sorted(HEX_HEAD)


class ToolboxError(ValueError):
    pass


@dataclass
class P:
    name: str
    label: str
    default: float
    unit: str = "mm"
    min: float | None = None
    max: float | None = None
    options: list[float] | None = None
    help: str = ""
    integer: bool = False


@dataclass
class Component:
    code: str
    name: str
    category: str
    standard: str
    keywords: list[str]
    params: list[P]
    material: str
    build: Callable[..., tuple[Any, dict[str, Any]]]
    title: Callable[[dict[str, float]], str]
    note: str = ""
    icon: str = "wrench"
    extra: dict[str, Any] = field(default_factory=dict)


def _std(table: dict[int, Any], d: float, what: str) -> Any:
    key = round(d)
    if abs(d - key) > 1e-9 or key not in table:
        raise ToolboxError(f"{what}: M{d:g} is not a supported standard size ({', '.join(f'M{k}' for k in sorted(table))})")
    return table[key]


def _hex_prism(s: float, h: float) -> Any:
    from build123d import RegularPolygon, extrude

    return extrude(RegularPolygon(s / SQ3, 6, align=None), h)


def _cyl(r: float, h: float, z0: float = 0.0) -> Any:
    from build123d import Align, Cylinder, Pos

    return Pos(0, 0, z0) * Cylinder(r, h, align=(Align.CENTER, Align.CENTER, Align.MIN))


def _chamfer_ring(r: float, c: float) -> float:
    """Volume removed by a 45° chamfer c on the circular edge of a radius-r cylinder (Pappus)."""
    return 2 * math.pi * (c * c / 2) * (r - c / 3)


def _chamfer_bore(r: float, c: float) -> float:
    """Volume removed by a 45° chamfer c on the circular edge of a radius-r bore (material outside r; Pappus)."""
    return 2 * math.pi * (c * c / 2) * (r + c / 3)


def _chamfer_circles(part: Any, r: float, c: float) -> Any:
    """45° chamfer c on every circular edge of radius r (a ring's bore or outside corners)."""
    from build123d import chamfer

    if c <= 0:
        return part
    edges = part.edges().filter_by(lambda e: e.geom_type.name == "CIRCLE" and abs(e.radius - r) < 1e-6)
    return chamfer(edges, c)


# ------------------------------------------------------------------------------------------------ generators
def _hex_bolt(D: float, L: float) -> tuple[Any, dict[str, Any]]:
    from aicad import fw

    s, k = _std(HEX_HEAD, D, "Hex bolt")
    if L < 2 * D / 2 or L > 20 * D:
        raise ToolboxError("length out of range for this diameter")
    head = fw.feature("Hex head", _hex_prism(s, k))
    part = fw.feature("Shank (thread cosmetic)", head + _cyl(D / 2, L, -L))
    vol = SQ3 / 2 * s * s * k + math.pi * D * D / 4 * L
    return part, {"bbox": [2 * s / SQ3, s, L + k], "volume": vol, "solids": 1}


def _shcs(D: float, L: float) -> tuple[Any, dict[str, Any]]:
    from build123d import Pos

    from aicad import fw

    dk, k, s, t = _std(SHCS, D, "Socket head cap screw")
    head = fw.feature("Cylindrical head", _cyl(dk / 2, k))
    head = fw.feature("Hex socket", head - Pos(0, 0, k - t) * _hex_prism(s, t + 0.01))
    part = fw.feature("Shank (thread cosmetic)", head + _cyl(D / 2, L, -L))
    vol = math.pi * dk * dk / 4 * k - SQ3 / 2 * s * s * t + math.pi * D * D / 4 * L
    return part, {"bbox": [dk, dk, L + k], "volume": vol, "solids": 1}


def _hex_nut(D: float) -> tuple[Any, dict[str, Any]]:
    from aicad import fw

    s, _k = _std(HEX_HEAD, D, "Hex nut")
    m = NUT_M[int(D)]
    body = fw.feature("Hex body", _hex_prism(s, m))
    part = fw.feature("Bore (thread cosmetic)", body - _cyl(D / 2, m + 0.02, -0.01))
    return part, {"bbox": [2 * s / SQ3, s, m], "volume": SQ3 / 2 * s * s * m - math.pi * D * D / 4 * m, "solids": 1}


def _washer(D: float) -> tuple[Any, dict[str, Any]]:
    from aicad import fw

    d1, d2, h = _std(WASHER, D, "Washer")
    part = fw.feature("Washer", _cyl(d2 / 2, h) - _cyl(d1 / 2, h + 0.02, -0.01))
    return part, {"bbox": [d2, d2, h], "volume": math.pi / 4 * (d2 * d2 - d1 * d1) * h, "solids": 1}


def _bearing(SERIES: float) -> tuple[Any, dict[str, Any]]:
    from build123d import Compound, Pos, Sphere

    from aicad import fw

    key = round(SERIES)
    if key not in BEARING:
        raise ToolboxError(f"Bearing {SERIES:g} not in table ({', '.join(str(k) for k in sorted(BEARING))})")
    d, Dd, B = BEARING[key]
    c = BEARING_RS[key]  # ISO 582 r_s min, as a 45° chamfer: inside the r_s min arc, so a shaft or housing
    #                      fillet r <= r_s min never touches the ring (live gear run 2026-11-19: 2.2 mm³ per shoulder)
    w = (Dd - d) / 2 * 0.3  # ring wall
    gap = (Dd - d) / 2 - 2 * w
    db = gap * 0.9
    dm = (Dd + d) / 2
    n = max(6, int(math.pi * dm / (1.6 * db)))
    inner = _cyl(d / 2 + w, B) - _cyl(d / 2, B + 0.02, -0.01)
    outer = _cyl(Dd / 2, B) - _cyl(Dd / 2 - w, B + 0.02, -0.01)
    inner = _chamfer_circles(inner, d / 2, c)   # the bore corners (against the shaft shoulder)
    outer = _chamfer_circles(outer, Dd / 2, c)  # the outside corners (against the housing shoulder)
    inner.label, outer.label = "Inner ring", "Outer ring"
    balls = []
    for i in range(n):
        a = 2 * math.pi * i / n
        b = Pos(dm / 2 * math.cos(a), dm / 2 * math.sin(a), B / 2) * Sphere(db / 2)
        b.label = f"Ball {i + 1}"
        balls.append(b)
    fw.feature("Rings", inner)
    part = Compound(children=[inner, outer, *balls])
    vol = math.pi / 4 * B * (((d + 2 * w) ** 2 - d * d) + (Dd * Dd - (Dd - 2 * w) ** 2)) + n * math.pi / 6 * db ** 3
    vol -= 2 * _chamfer_bore(d / 2, c) + 2 * _chamfer_ring(Dd / 2, c)
    return part, {"bbox": [Dd, Dd, B], "volume": vol, "solids": 2 + n}


def key_row(D: float) -> tuple[float, float, float, float]:
    """DIN 6885-1 (b, h, t1, t2) for a shaft Ø D (over lo, up to hi)."""
    for (lo, hi), v in KEY_ROWS:
        if lo < D <= hi:
            return (float(v[0]), float(v[1]), float(v[2]), float(v[3]))
    raise ToolboxError("shaft diameter outside the DIN 6885 key table (over 8 up to 65 mm)")


def _spur_gear(M: float, Z: float, B: float, BORE: float, KEY_B: float = 0.0, KEY_T2: float = 0.0,
               KEY_ANG: float = 0.0) -> tuple[Any, dict[str, Any]]:
    from aicad import fw

    z = round(Z)
    if z < 12 or z > 200 or abs(Z - z) > 1e-9:
        raise ToolboxError("teeth must be a whole number between 12 and 200")
    if M <= 0 or B <= 0:
        raise ToolboxError("module and face width must be positive")
    rf = M * z / 2 - 1.25 * M
    if BORE <= 0 or BORE / 2 >= rf - M:
        raise ToolboxError(f"bore must be positive and below Ø{2 * (rf - M):.1f} (root diameter minus a rim)")
    R = BORE / 2
    if KEY_B > 0 and not (KEY_B < BORE and KEY_T2 > 0 and R + KEY_T2 < rf - M / 2):
        raise ToolboxError("hub keyway: width must be below the bore and the keyway top inside the rim "
                           f"(bore radius + t2 below {rf - M / 2:.1f})")
    # v3: true involute flanks as smooth splines (fw_std.spur_gear, the generator the direct path uses). v2 sampled
    # each flank as a polyline, so every flank was several flat faces (founder: "split into multiple planes").
    # Same conventions: a tooth centred on +X, axis Z, faces Z = 0..B, keyway centred KEY_ANG degrees from +X.
    from aicad import fw_std

    # a small working backlash (0.04 m of tooth thinning at the pitch circle): exact involutes at m(z1+z2)/2 would
    # touch flank to flank and read as a clash; the old polyline flanks only cleared because their chords cut inside
    part, exp = fw_std.spur_gear(M, z, B, bore=BORE, name="Involute teeth", backlash=0.04 * M,
                                 keyway=(KEY_B, KEY_T2) if KEY_B > 0 else False, keyway_angle=KEY_ANG)
    if KEY_B > 0:
        fw.feature(f"Hub keyway {KEY_B:g}×{KEY_T2:g} (DIN 6885)", part)
    return part, {"bbox": exp["bbox"], "volume": exp["volume"], "solids": 1}


def _key_for(D: float) -> tuple[float, float]:
    for (lo, hi), v in KEYS:
        if lo < D <= hi:
            return v
    raise ToolboxError("shaft diameter outside the DIN 6885 key table (8–65 mm)")


def _shaft(D: float, L: float, KEY_L: float, C: float) -> tuple[Any, dict[str, Any]]:
    from build123d import Align, Box, Pos, chamfer

    from aicad import fw

    b, t1 = _key_for(D)
    R = D / 2
    if not (0 <= C < R / 2) or KEY_L <= b or KEY_L > L - 4 * C - 2:
        raise ToolboxError("keyway length must exceed the key width and fit between the chamfers")
    part = fw.feature("Shaft", _cyl(R, L))
    if C > 0:
        part = fw.feature("End chamfers", chamfer(part.edges().filter_by(lambda e: e.geom_type.name == "CIRCLE"), C))
    slot = Pos(0, R - t1, L / 2) * Box(b, t1 + R, KEY_L, align=(Align.CENTER, Align.MIN, Align.CENTER))
    part = fw.feature(f"Keyway {b:g}×{t1:g} (DIN 6885)", part - slot)
    y = b / 2

    def F(v: float) -> float:
        return v / 2 * math.sqrt(R * R - v * v) + R * R / 2 * math.asin(v / R)

    seg = F(y) - F(-y) - b * (R - t1)
    vol = math.pi * R * R * L - 2 * _chamfer_ring(R, C) - seg * KEY_L
    return part, {"bbox": [D, D, L], "volume": vol, "solids": 1}


def _parallel_key(D: float, L: float) -> tuple[Any, dict[str, Any]]:
    """DIN 6885-1 form A (round-ended) parallel key for a shaft Ø D: b × h from the table, length L. Frame: length
    along X and width along Y, both centred; the underside (in the shaft keyseat) on Z 0, the top at Z h."""
    from build123d import SlotOverall, extrude

    from aicad import fw

    b, h, _t1, _t2 = key_row(D)
    if L <= b:
        raise ToolboxError(f"key length must exceed the key width {b:g} mm")
    part = fw.feature(f"Parallel key {b:g}×{h:g} form A", extrude(SlotOverall(L, b), h))
    part.label = f"Parallel key DIN 6885 A {b:g}×{h:g}×{L:g}"
    return part, {"bbox": [L, b, h], "volume": h * (b * (L - b) + math.pi * b * b / 4), "solids": 1}


def ring_row(D: float) -> tuple[float, float, float, float, float]:
    """DIN 471 (s, b, d2, m, n) for a shaft d1 = D."""
    key = round(D)
    if abs(D - key) > 1e-9 or key not in DIN471:
        raise ToolboxError(f"Retaining ring: Ø{D:g} is not a DIN 471 size ({', '.join(str(k) for k in sorted(DIN471))})")
    return DIN471[key]


def _retaining_ring(D: float) -> tuple[Any, dict[str, Any]]:
    """DIN 471 external retaining ring for a shaft d1 = D, as fitted in its groove: an annulus from the groove Ø d2
    out by the ring's radial width b, thickness s. Frame: axis Z, one face on Z 0 (like a bearing)."""
    from aicad import fw

    s, b, d2, _m, _n = ring_row(D)
    part = fw.feature("Retaining ring (as fitted)", _cyl(d2 / 2 + b, s) - _cyl(d2 / 2, s + 0.02, -0.01))
    part.label = f"Retaining ring DIN 471 {D:g}×{s:g}"
    return part, {"bbox": [d2 + 2 * b, d2 + 2 * b, s], "volume": math.pi / 4 * ((d2 + 2 * b) ** 2 - d2 * d2) * s,
                  "solids": 1}


def _dowel(D: float, L: float) -> tuple[Any, dict[str, Any]]:
    from build123d import chamfer

    from aicad import fw

    c = round(min(0.2 * D, 1.0), 3)
    part = fw.feature("Pin", _cyl(D / 2, L))
    part = fw.feature("End chamfers", chamfer(part.edges(), c))
    return part, {"bbox": [D, D, L], "volume": math.pi * D * D / 4 * L - 2 * _chamfer_ring(D / 2, c), "solids": 1}


def _flange(OD: float, T: float, BORE: float, N: float, HOLE: float, PCD: float) -> tuple[Any, dict[str, Any]]:
    from build123d import Pos

    from aicad import fw

    n = round(N)
    if not (BORE < PCD - HOLE and PCD + HOLE < OD and n >= 2):
        raise ToolboxError("need bore < PCD − hole and PCD + hole < outside diameter")
    part = fw.feature("Flange disc", _cyl(OD / 2, T) - _cyl(BORE / 2, T + 0.02, -0.01))
    for i in range(n):
        a = 2 * math.pi * i / n
        part -= Pos(PCD / 2 * math.cos(a), PCD / 2 * math.sin(a), 0) * _cyl(HOLE / 2, T + 0.02, -0.01)
    part = fw.feature(f"{n} bolt holes", part)
    vol = math.pi / 4 * (OD * OD - BORE * BORE - n * HOLE * HOLE) * T
    return part, {"bbox": [OD, OD, T], "volume": vol, "solids": 1}


def _l_bracket(A: float, B: float, W: float, T: float, HOLE: float) -> tuple[Any, dict[str, Any]]:
    from build123d import Align, Box, Pos, Rot

    from aicad import fw

    if T * 3 > min(A, B) or HOLE >= W / 2 or HOLE >= (min(A, B) - T) / 2:
        raise ToolboxError("legs must be > 3× thickness and the holes must fit the legs")
    base = Box(A, W, T, align=(Align.MIN, Align.MIN, Align.MIN))
    up = Box(T, W, B, align=(Align.MIN, Align.MIN, Align.MIN))
    part = fw.feature("L body", base + up)
    xs = [T + (A - T) * f for f in (0.35, 0.75)]
    for x in xs:
        part -= Pos(x, W / 2, -0.01) * _cyl(HOLE / 2, T + 0.02)
    zs = [T + (B - T) * f for f in (0.35, 0.75)]
    for z in zs:
        part -= Pos(-0.01, W / 2, z) * Rot(0, 90, 0) * _cyl(HOLE / 2, T + 0.02)
    part = fw.feature("Mounting holes", part)
    vol = (A * T + (B - T) * T) * W - 4 * math.pi * HOLE * HOLE / 4 * T
    return part, {"bbox": [A, W, B], "volume": vol, "solids": 1}


def _standoff(D: float, AF: float, L: float) -> tuple[Any, dict[str, Any]]:
    from aicad import fw

    _std(HEX_HEAD, D, "Standoff thread")
    if AF <= D + 1:
        raise ToolboxError("across-flats must exceed the thread diameter by at least 1 mm")
    part = fw.feature("Hex body", _hex_prism(AF, L))
    part = fw.feature("Through bore (thread cosmetic)", part - _cyl(D / 2, L + 0.02, -0.01))
    return part, {"bbox": [2 * AF / SQ3, AF, L], "volume": (SQ3 / 2 * AF * AF - math.pi * D * D / 4) * L, "solids": 1}


def _m(label: str = "Thread size", default: float = 8) -> P:
    return P("D", label, default, options=[float(k) for k in METRIC], help="Metric coarse thread (ISO 261)")


COMPONENTS: dict[str, Component] = {c.code: c for c in [
    Component("hex_bolt", "Hex head bolt", "Fasteners", "ISO 4017", ["bolt", "hex bolt", "hex head", "screw", "4017", "4014"],
              [_m(), P("L", "Length under head", 30, min=4, max=300)], "Steel 8.8", _hex_bolt,
              lambda p: f"Hex bolt ISO 4017 M{p['D']:g}×{p['L']:g}", "Thread modelled cosmetically (shank at nominal Ø).", "bolt"),
    Component("shcs", "Socket head cap screw", "Fasteners", "ISO 4762", ["socket head", "cap screw", "allen", "shcs", "4762", "screw"],
              [_m(), P("L", "Length under head", 20, min=4, max=300)], "Steel 12.9", _shcs,
              lambda p: f"Socket head cap screw ISO 4762 M{p['D']:g}×{p['L']:g}", "Thread modelled cosmetically.", "bolt"),
    Component("hex_nut", "Hex nut", "Fasteners", "ISO 4032", ["nut", "hex nut", "4032"],
              [_m()], "Steel 8", _hex_nut, lambda p: f"Hex nut ISO 4032 M{p['D']:g}", "Bore at nominal Ø (thread cosmetic).", "nut"),
    Component("washer", "Plain washer", "Fasteners", "ISO 7089", ["washer", "7089", "flat washer"],
              [_m()], "Steel", _washer, lambda p: f"Washer ISO 7089 M{p['D']:g}", "", "circle"),
    Component("standoff", "Hex standoff (spacer)", "Fasteners", "—", ["standoff", "spacer", "hex spacer", "pillar"],
              [_m("Thread size", 3), P("AF", "Across flats", 5.5, min=3, max=40), P("L", "Length", 10, min=2, max=200)],
              "Brass", _standoff, lambda p: f"Hex standoff M{p['D']:g} AF{p['AF']:g}×{p['L']:g}", "Through bore at nominal Ø.", "hexagon"),
    Component("dowel", "Dowel pin", "Pins & keys", "ISO 8734 (envelope)", ["dowel", "pin", "8734", "locating pin"],
              [P("D", "Diameter", 6, min=1, max=50), P("L", "Length", 20, min=3, max=200)], "Steel (hardened)", _dowel,
              lambda p: f"Dowel pin Ø{p['D']:g}×{p['L']:g}", "45° end chamfers.", "minus"),
    Component("bearing", "Deep-groove ball bearing", "Bearings", "ISO 15 (envelope)", ["bearing", "ball bearing", "6204", "6205", "60", "62"],
              [P("SERIES", "Designation", 6204, unit="", options=[float(k) for k in sorted(BEARING)], help="60xx / 62xx series", integer=True)],
              "Bearing steel", _bearing, lambda p: f"Ball bearing {int(p['SERIES'])}",
              "Simplified: plain rings + balls at catalogue d × D × B (no grooves, cage or seals); bore and outside "
              "corners chamfered 45° by r_s min (ISO 582).", "circle-dot"),
    Component("spur_gear", "Spur gear", "Power transmission", "ISO 53 profile, α = 20°", ["gear", "spur gear", "pinion", "teeth", "module"],
              [P("M", "Module", 2, min=0.3, max=20), P("Z", "Teeth", 24, unit="", min=12, max=200, integer=True),
               P("B", "Face width", 15, min=1, max=300), P("BORE", "Bore", 10, min=1, max=500),
               P("KEY_B", "Hub keyway width", 0, min=0, max=100, help="DIN 6885 b; 0 = no keyway"),
               P("KEY_T2", "Hub keyway depth t2", 0, min=0, max=50, help="From the bore surface (DIN 6885 t2)"),
               P("KEY_ANG", "Hub keyway angle", 0, unit="°", min=-360, max=360, help="Keyway centre line from +X")],
              "Steel C45", _spur_gear,
              lambda p: f"Spur gear m{p['M']:g} z{int(p['Z'])}" + (
                  f", keyed {p['KEY_B']:g}×{p['KEY_T2']:g}" if p.get("KEY_B") else ""),
              "True involute flanks (smooth splines), no profile shift. Optional DIN 6885 hub keyway.", "cog"),
    Component("parallel_key", "Parallel key", "Pins & keys", "DIN 6885-1 form A",
              ["parallel key", "feather key", "6885", "key", "keys"],
              [P("D", "Shaft diameter", 20, min=8, max=65, help="b × h from DIN 6885-1 for the shaft Ø"),
               P("L", "Key length", 18, min=4, max=400, help="DIN 6885 lengths: " + ", ".join(f"{x:g}" for x in KEY_LENGTHS[:16]) + " …")],
              "Steel C45+C (bright key steel)", _parallel_key,
              lambda p: "Parallel key DIN 6885 A {:g}×{:g}×{:g}".format(*key_row(p["D"])[:2], p["L"]),
              "Round-ended (form A); edge chamfers not modelled. Table typed from public references (verify).", "minus"),
    Component("retaining_ring", "Retaining ring for shafts", "Pins & keys", "DIN 471",
              ["circlip", "circlips", "retaining ring", "retaining rings", "snap ring", "seeger", "471"],
              [P("D", "Shaft diameter d1", 20, options=[float(k) for k in sorted(DIN471)], help="DIN 471 normal type")],
              "Spring steel", _retaining_ring, lambda p: f"Retaining ring DIN 471 {p['D']:g}×{ring_row(p['D'])[0]:g}",
              "Modelled as fitted: a plain annulus from the groove Ø d2 out by the radial width b (no lugs, holes "
              "or gap). Table typed from a distributor's DIN 471 reprint (verify).", "circle"),
    Component("shaft", "Shaft with keyway", "Power transmission", "DIN 6885-1 keyway", ["shaft", "keyway", "key way", "axle"],
              [P("D", "Diameter", 25, min=9, max=65), P("L", "Length", 120, min=20, max=2000), P("KEY_L", "Keyway length", 40, min=5, max=1000),
               P("C", "End chamfer", 1, min=0, max=5)], "Steel C45", _shaft,
              lambda p: f"Shaft Ø{p['D']:g}×{p['L']:g} with keyway", "Key width/depth from DIN 6885 for the diameter.", "minus"),
    Component("flange", "Bolted flange", "Structural", "—", ["flange", "pipe flange", "bolt circle", "pcd"],
              [P("OD", "Outside Ø", 150, min=20, max=2000), P("T", "Thickness", 16, min=2, max=200), P("BORE", "Bore", 60, min=1, max=1900),
               P("N", "Bolt holes", 6, unit="", min=2, max=64, integer=True), P("HOLE", "Bolt hole Ø", 14, min=1, max=100),
               P("PCD", "Pitch circle Ø", 120, min=10, max=2000)], "Steel S235", _flange,
              lambda p: f"Flange Ø{p['OD']:g}×{p['T']:g}, {int(p['N'])}×Ø{p['HOLE']:g} on PCD {p['PCD']:g}", "", "circle-dot"),
    Component("l_bracket", "L-bracket", "Structural", "—", ["bracket", "l-bracket", "angle bracket", "l bracket"],
              [P("A", "Base leg", 80, min=10, max=1000), P("B", "Upright leg", 60, min=10, max=1000), P("W", "Width", 40, min=5, max=1000),
               P("T", "Thickness", 6, min=1, max=50), P("HOLE", "Hole Ø", 8.4, min=1, max=50)], "Steel S235", _l_bracket,
              lambda p: f"L-bracket {p['A']:g}×{p['B']:g}×{p['W']:g}, t{p['T']:g}", "Two holes per leg.", "corner-down-right"),
]}


def spec(code: str) -> Component:
    c = COMPONENTS.get(code)
    if c is None:
        raise ToolboxError(f"unknown toolbox component '{code}'")
    return c


def normalize(code: str, values: dict[str, Any]) -> dict[str, float]:
    c = spec(code)
    out: dict[str, float] = {}
    for p in c.params:
        v = values.get(p.name, p.default)
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ToolboxError(f"{p.label}: not a number") from None
        if p.options and f not in p.options:
            raise ToolboxError(f"{p.label}: choose one of {', '.join(f'{o:g}' for o in p.options)}")
        if p.min is not None and f < p.min or p.max is not None and f > p.max:
            raise ToolboxError(f"{p.label}: must be between {p.min:g} and {p.max:g}")
        out[p.name] = int(f) if p.integer or (p.options and f.is_integer()) else f
    return out


def build(code: str, **values: Any) -> tuple[Any, dict[str, Any]]:
    """Build a component (deterministic). Returns (shape, EXPECTED)."""
    c = spec(code)
    p = normalize(code, values)
    return c.build(**p)


def catalog() -> list[dict[str, Any]]:
    return [{"code": c.code, "name": c.name, "category": c.category, "standard": c.standard, "material": c.material,
             "note": c.note, "icon": c.icon, "keywords": c.keywords, "version": VERSION,
             "params": [{"name": p.name, "label": p.label, "default": p.default, "unit": p.unit, "min": p.min, "max": p.max,
                         "options": p.options, "help": p.help, "integer": p.integer} for p in c.params]}
            for c in COMPONENTS.values()]


def model_source(code: str, values: dict[str, Any]) -> str:
    """A complete, editable model.py for a toolbox component (PARAMS drive the generator)."""
    c = spec(code)
    p = normalize(code, values)
    title = c.title(p)
    lines = [f'"""{title} — Formwright Toolbox ({c.standard}), generator v{VERSION}.',
             "",
             "Deterministic: the same parameters always give the same geometry. Edit the parameters in the app",
             "(or ask the design agent to modify / extend this part).",
             f"{c.note}".rstrip(),
             '"""',
             "from aicad import toolbox", "",
             f"NAME = {title!r}", f"MATERIAL = {c.material!r}",
             f"TOOLBOX = {{'code': {code!r}, 'version': {VERSION}}}", ""]
    for q in c.params:
        lines.append(f"{q.name} = {p[q.name]!r}  # {q.label}{' (' + q.unit + ')' if q.unit else ''}")
    lines += ["", "PARAMS = dict(" + ", ".join(f"{q.name}={q.name}" for q in c.params) + ")"]
    meta = []
    for q in c.params:
        m: dict[str, Any] = {"label": q.label, "group": c.name}
        if q.unit:
            m["unit"] = q.unit
        if q.options:
            m["min"], m["max"] = min(q.options), max(q.options)
        else:
            if q.min is not None:
                m["min"] = q.min
            if q.max is not None:
                m["max"] = q.max
        if q.integer:
            m["step"] = 1
        if q.help:
            m["help"] = q.help
        meta.append(f"{q.name!r}: {m!r}")
    lines.append("PARAM_META = {" + ", ".join(meta) + "}")
    lines += ["", f"result, EXPECTED = toolbox.build({code!r}, " + ", ".join(f"{q.name}={q.name}" for q in c.params) + ")", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------ prompt matching
_NUM = r"(\d+(?:\.\d+)?)"


def match(prompt: str) -> list[dict[str, Any]]:
    """Suggest toolbox components for a free-text request, with parameters pre-filled where they can be read.
    Conservative: only fires on clear component nouns; custom features (pockets, special shapes) lower the score."""
    t = prompt.lower()
    out: list[dict[str, Any]] = []
    # "with a keyway" / "with a bore" name features a standard gear or shaft carries (the hub keyway is a parameter):
    # they are not custom work (live gear run 2026-11-19: "Gear with a keyway" was designed, the pinion swapped in)
    tc = re.sub(r"\bwith an?\s+(?:(?:din\s*6885\s+|hub\s+|keyed\s+|plain\s+|ø?\d+(?:\.\d+)?\s*(?:mm\s+)?)*)"
                r"(?:key\s?way|keyseat|key|bore)s?\b", " ", t)
    custom = sum(w in tc for w in ("pocket", "slot", "custom", "rib", "boss", "with a", "cutout", "enclosure", "housing",
                                  "assembly", "mount for", "adapter", "modify", "change", "make it", "the part",
                                  # edits and plain prismatic parts are not standard components (STU-15)
                                  "chamfer", "fillet", "block", "plate", "through hole", "holes", "add a", "add an"))
    # "Pinion key", "Gear circlip": the part is the key / ring, the gear or shaft word only says where it goes
    small = re.search(r"\b(?:keys?|circlips?|retaining rings?|snap rings?)\b", t)
    host = re.search(r"\b(?:pinion|gears?|shafts?|hub|wheel|pulley)\b", t)
    for c in COMPONENTS.values():
        score = 0
        for k in c.keywords:
            if re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", t):
                score += 2 if " " in k or len(k) > 4 else 1
        if score == 0:
            continue
        if small and c.code not in ("parallel_key", "retaining_ring"):
            score -= 2
        if c.code == "parallel_key" and host and re.search(r"\bkeys?\b", t):
            score += 1
        vals: dict[str, float] = {}
        m = re.search(r"\bm\s?(\d{1,2})(?:\s*[x×]\s*" + _NUM + r")?", t)
        names = {p.name for p in c.params}
        if m and "D" in names and int(m.group(1)) in METRIC:
            vals["D"] = float(m.group(1))
            if m.group(2) and "L" in names:
                vals["L"] = float(m.group(2))
        if "SERIES" in names:
            b = re.search(r"\b(6[02]0\d)\b", t)
            if b and int(b.group(1)) in BEARING:
                vals["SERIES"] = float(b.group(1))
                score += 2
        if c.code == "spur_gear":
            # "m2 z60" / "m2 20T" (the usual gear shorthand) first; the spelled-out forms override them
            for pat, key in ((r"\bm\s?" + _NUM + r"(?![\d.]|\s*[x×])", "M"), (r"\bz\s?(\d{2,3})\b", "Z"),
                             (r"\b(\d{2,3})\s?t\b", "Z"),
                             (r"module\s*(?:of\s*)?" + _NUM, "M"), (r"\bm\s?=\s?" + _NUM, "M"), (_NUM + r"\s*teeth", "Z"),
                             (r"(?:z|teeth)\s*=\s*" + _NUM, "Z"), (r"face\s*width\s*(?:of\s*)?" + _NUM, "B"), (r"bore\s*(?:of\s*)?ø?\s*" + _NUM, "BORE")):
                g = re.search(pat, t)
                if g:
                    vals[key] = float(g.group(1))
        if c.code in ("shaft", "dowel", "parallel_key", "retaining_ring"):
            g = re.search(r"(?:ø|dia(?:meter)?\s*)\s*" + _NUM, t)
            if g:
                vals["D"] = float(g.group(1))
        if c.code == "parallel_key":  # "6x6x18" (b × h × l): the table row of that b gives the shaft range
            g = re.search(r"\b(\d{1,2})\s*[x×]\s*(\d{1,2})\s*[x×]\s*" + _NUM, t)
            row = next(((lo, hi) for (lo, hi), v in KEY_ROWS if g and v[0] == int(g.group(1)) and v[1] == int(g.group(2))), None)
            if g and row:
                vals["D"], vals["L"] = float(row[1]), float(g.group(3))
        if c.code in ("hex_bolt", "shcs", "standoff", "dowel", "shaft", "parallel_key"):
            g = re.search(r"(?:length|long)\s*(?:of\s*)?" + _NUM + r"|" + _NUM + r"\s*mm\s*long", t)
            if g:
                vals["L"] = float(g.group(1) or g.group(2))
        score -= 2 * custom
        if score >= 2:
            try:
                p = normalize(c.code, vals)
            except ToolboxError:
                p = normalize(c.code, {})
                vals = {}
            out.append({"code": c.code, "name": c.name, "standard": c.standard, "score": score, "params": p,
                        "title": c.title(p), "prefilled": sorted(vals)})
    return sorted(out, key=lambda r: -r["score"])[:3]
