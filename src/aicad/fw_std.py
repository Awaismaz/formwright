"""High-level standard features for model scripts (PS-03): one call instead of 50-150 hand-written lines.

The design agent's time is dominated by writing the script, so a 125-line involute gear costs about a minute of model
output before anything is built. These helpers build the common heavy features with clean B-rep (true involute
flanks as splines, revolved shafts, Hole Wizard holes) and return their EXPECTED values from hand formulas that do
not use the CAD kernel, so CHK-04/05 still catch modelling mistakes. Re-exported by ``aicad.fw``:

    part, exp = fw.spur_gear(module=2, teeth=60, face_width=20, bore=20, hub_d=40, hub_l=30, keyway=True)
    part, exp = fw.stepped_shaft([(20, 30), (25, 60), (20, 30)], chamfer=1, fillet=1)
    part, v = fw.shaft_keyway(part, d=25, z_center=60, length=40)
    part, h = fw.bolt_circle(part, n=6, pcd=80, spec="M8 clearance", depth=10)
    part, h = fw.hole(part, (0, 0, 10), "M6 tapped", depth=12)

Every helper records its features with ``fw.feature`` (feature tree, suppression) and returns plain numbers in
millimetres. Standards values come from the tables in ``holes.py`` / ``toolbox.py`` or the DIN 6885-1 table below.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

# DIN 6885-1 (1968) parallel keys, form A: shaft Ø over..up to -> (b width, h height, t1 shaft depth, t2 hub depth), mm.
# Same ranges and b/t1 as toolbox.KEYS; t2 is the hub keyway depth above the bore (verify against the standard).
DIN6885 = [((6, 8), (2, 2, 1.2, 1.0)), ((8, 10), (3, 3, 1.8, 1.4)), ((10, 12), (4, 4, 2.5, 1.8)),
           ((12, 17), (5, 5, 3.0, 2.3)), ((17, 22), (6, 6, 3.5, 2.8)), ((22, 30), (8, 7, 4.0, 3.3)),
           ((30, 38), (10, 8, 5.0, 3.3)), ((38, 44), (12, 8, 5.0, 3.3)), ((44, 50), (14, 9, 5.5, 3.8)),
           ((50, 58), (16, 10, 6.0, 4.3)), ((58, 65), (18, 11, 7.0, 4.4)), ((65, 75), (20, 12, 7.5, 4.9))]
DIN6885_SOURCE = "DIN 6885-1 parallel keys, form A (verify against the standard before release)"


def din6885(d: float) -> dict[str, float]:
    """Key and keyway sizes for shaft/bore diameter d: {"b", "h", "t1" (shaft depth), "t2" (hub depth)}."""
    for (lo, hi), (b, h, t1, t2) in DIN6885:
        if lo < d <= hi:
            return {"b": b, "h": h, "t1": t1, "t2": t2}
    raise ValueError(f"Ø{d:g} mm is outside the DIN 6885-1 table (over 6 up to 75 mm)")


# ------------------------------------------------------------------ hand formulas (no CAD kernel)
def _simpson(f: Any, a: float, b: float, n: int = 400) -> float:
    if b <= a:
        return 0.0
    n += n % 2
    h = (b - a) / n
    s = f(a) + f(b) + sum((4 if i % 2 else 2) * f(a + i * h) for i in range(1, n))
    return s * h / 3


def _inv(x: float) -> float:
    return math.tan(x) - x


class _Involute:
    """Standard (x = 0) spur gear tooth geometry, ISO 53 basic rack: addendum m, dedendum 1.25 m."""

    def __init__(self, m: float, z: int, alpha_deg: float, backlash: float = 0.0) -> None:
        self.m, self.z, self.a = m, z, math.radians(alpha_deg)
        # backlash: circumferential tooth thinning at the pitch circle (mm), half taken off each flank, so two
        # meshing gears at the standard centre distance m(z1+z2)/2 clear instead of touching flank to flank
        self.thin = backlash / 2 / (m * z / 2)
        self.rp = m * z / 2
        self.rb = self.rp * math.cos(self.a)
        self.ra = self.rp + m
        self.rf = self.rp - 1.25 * m
        self.r0 = max(self.rb, self.rf)  # where the involute starts (radial flank below the base circle)

    def psi(self, r: float) -> float:
        """Half the tooth's angular thickness at radius r (involute part)."""
        r = max(r, self.rb)
        return math.pi / (2 * self.z) + _inv(self.a) - _inv(math.acos(min(1.0, self.rb / r))) - self.thin

    def area(self) -> float:
        """Profile area: root disc + z teeth, a tooth being 2 psi(r) r dr above r0 and radial flanks below."""
        tooth = _simpson(lambda r: 2 * self.psi(r) * r, self.r0, self.ra) + self.psi(self.r0) * (self.r0 ** 2 - self.rf ** 2)
        return math.pi * self.rf ** 2 + self.z * tooth

    def samples(self, flank: int = 60) -> list[tuple[float, float]]:
        """Dense points of the exact profile (for the expected bounding box)."""
        pts: list[tuple[float, float]] = []
        pitch = 2 * math.pi / self.z
        for k in range(self.z):
            c = k * pitch
            for i in range(flank + 1):
                r = self.r0 + (self.ra - self.r0) * i / flank
                for s in (-1, 1):
                    t = c + s * self.psi(r)
                    pts.append((r * math.cos(t), r * math.sin(t)))
            pa = self.psi(self.ra)
            for j in range(flank + 1):
                t = c - pa + 2 * pa * j / flank
                pts.append((self.ra * math.cos(t), self.ra * math.sin(t)))
        return pts


def _xy_extent(pts: list[tuple[float, float]], twist_rad: float = 0.0, steps: int = 90) -> tuple[float, float]:
    """X and Y size of the profile, swept through a rotation of twist_rad (helical gears)."""
    angs = [twist_rad * i / steps for i in range(steps + 1)] if twist_rad else [0.0]
    xs_min = ys_min = math.inf
    xs_max = ys_max = -math.inf
    for a in angs:
        ca, sa = math.cos(a), math.sin(a)
        for x, y in pts:
            u, v = x * ca - y * sa, x * sa + y * ca
            xs_min, xs_max = min(xs_min, u), max(xs_max, u)
            ys_min, ys_max = min(ys_min, v), max(ys_max, v)
    return xs_max - xs_min, ys_max - ys_min


def _keyway_segment(radius: float, b: float) -> float:
    """Area of the bore disc inside the strip |x| <= b/2, y >= 0 (half of the chord region)."""
    hw = b / 2
    return hw * math.sqrt(radius ** 2 - hw ** 2) + radius ** 2 * math.asin(hw / radius)


# ------------------------------------------------------------------ gears
def spur_gear(module: float, teeth: float, face_width: float, *, pressure_angle: float = 20.0, bore: float = 0.0,
              hub_d: float = 0.0, hub_l: float = 0.0, keyway: bool | tuple[float, float] = False,
              helix_angle: float = 0.0, name: str = "Gear teeth", z0: float = 0.0,
              keyway_angle: float = 90.0, backlash: float = 0.0) -> tuple[Any, dict[str, Any]]:
    """Spur (or helical) gear from Z = z0 up, axis Z, true involute flanks (no root fillet), standard addendum m and
    dedendum 1.25 m, profile shift 0, a tooth centred on +X. Optional hub (Ø hub_d, length hub_l on the +Z face),
    through bore, and a hub keyway (keyway=True: DIN 6885-1 for the bore; or (b, t2)) on the side keyway_angle
    degrees from +X about Z (default 90: +Y). helix_angle (deg, at the pitch circle) twists the teeth over the face
    width. Returns (part, expected) with expected = {"bbox", "volume", "solids", "gear"}."""
    from build123d import Align, Box, Cylinder, Edge, Face, Pos, Rot, Solid, Vector, Wire, extrude

    from aicad import fw

    z = round(float(teeth))
    if z != teeth or not 8 <= z <= 400:
        raise ValueError("teeth must be a whole number from 8 to 400")
    if module <= 0 or face_width <= 0:
        raise ValueError("module and face width must be positive")
    g = _Involute(float(module), z, float(pressure_angle), float(backlash))
    if bore and bore / 2 >= g.rf - 0.5 * module:
        raise ValueError(f"bore Ø{bore:g} leaves no rim: keep it below Ø{2 * (g.rf - 0.5 * module):.1f}")
    if hub_d and (hub_l <= 0 or hub_d <= bore):
        raise ValueError("a hub needs hub_l > 0 and hub_d larger than the bore")

    edges: list[Any] = []
    pitch = 2 * math.pi / z
    nflank = 9

    def pol(r: float, t: float) -> Any:
        return Vector(r * math.cos(t), r * math.sin(t), 0)

    ps0, pa = g.psi(g.r0), g.psi(g.ra)
    for k in range(z):
        c = k * pitch
        if g.rf < g.r0:
            edges.append(Edge.make_line(pol(g.rf, c - ps0), pol(g.r0, c - ps0)))
        rs = [g.r0 + (g.ra - g.r0) * (i / nflank) ** 1.5 for i in range(nflank + 1)]  # denser near the base
        edges.append(Edge.make_spline([pol(r, c - g.psi(r)) for r in rs]))
        edges.append(Edge.make_three_point_arc(pol(g.ra, c - pa), pol(g.ra, c), pol(g.ra, c + pa)))
        edges.append(Edge.make_spline([pol(r, c + g.psi(r)) for r in reversed(rs)]))
        if g.rf < g.r0:
            edges.append(Edge.make_line(pol(g.r0, c + ps0), pol(g.rf, c + ps0)))
        a0, a1 = c + ps0, c + pitch - ps0
        edges.append(Edge.make_three_point_arc(pol(g.rf, a0), pol(g.rf, (a0 + a1) / 2), pol(g.rf, a1)))
    face = Face(Wire(edges))
    twist = 0.0
    if helix_angle:
        twist = math.degrees(face_width * math.tan(math.radians(helix_angle)) / g.rp)
        body = Solid.extrude_linear_with_rotation(face, Vector(0, 0, 0), Vector(0, 0, face_width), twist)
    else:
        body = extrude(face, face_width)
    if z0:
        body = Pos(0, 0, z0) * body
    label = f"{name} (m{module:g}, z{z}, α{pressure_angle:g}°{f', β{helix_angle:g}°' if helix_angle else ''})"
    part = fw.feature(label, body, module=module, teeth=z, face_width=face_width)
    area = g.area()
    vol = area * face_width
    top = face_width  # height above z0
    if hub_d:
        part = fw.feature("Hub", part + Pos(0, 0, z0 + face_width) * Cylinder(hub_d / 2, hub_l,
                                                                         align=(Align.CENTER, Align.CENTER, Align.MIN)),
                          d=hub_d, length=hub_l)
        vol += math.pi * hub_d ** 2 / 4 * hub_l
        top += hub_l
    if bore:
        part = fw.feature(f"Bore Ø{bore:g}", part - Pos(0, 0, z0 - 0.5) * Cylinder(
            bore / 2, top + 1, align=(Align.CENTER, Align.CENTER, Align.MIN)), d=bore)
        vol -= math.pi * bore ** 2 / 4 * top
    if keyway:
        if not bore:
            raise ValueError("a keyway needs a bore")
        if keyway is True:
            k = din6885(bore)
            kb, kt2, src = k["b"], k["t2"], "DIN 6885"
        else:
            kb, kt2, src = float(keyway[0]), float(keyway[1]), "custom"
        depth = bore / 2 + kt2  # keyway floor measured from the bore axis
        tool = Pos(0, 0, z0 - 0.5) * Box(kb, depth, top + 1, align=(Align.CENTER, Align.MIN, Align.MIN))  # on +Y
        if keyway_angle != 90.0:
            tool = Rot(0, 0, keyway_angle - 90.0) * tool
        part = fw.feature(f"Keyway {kb:g}×{kt2:g} ({src})", part - tool, b=kb, t2=kt2)
        vol -= (kb * depth - _keyway_segment(bore / 2, kb)) * top
    sx, sy = _xy_extent(g.samples(), math.radians(twist))
    gear = {"pitch_d": 2 * g.rp, "tip_d": 2 * g.ra, "root_d": 2 * g.rf, "base_d": 2 * g.rb,
            "profile_area": area, "twist_deg": twist}
    return part, {"bbox": [sx, sy, top], "volume": vol, "solids": 1, "gear": gear}


# ------------------------------------------------------------------ shafts
def stepped_shaft(segments: list[tuple[float, float]], *, chamfer: float = 0.0, fillet: float = 0.0,
                  name: str = "Shaft", z0: float = 0.0) -> tuple[Any, dict[str, Any]]:
    """A revolved shaft along +Z from Z = z0: segments = [(diameter, length), ...] bottom to top. chamfer: 45° on
    both end faces' outer edges; fillet: radius in every concave shoulder corner. Returns (part, expected)."""
    from build123d import Axis, Plane, Polyline, make_face, revolve

    from aicad import fw

    if not segments or any(d <= 0 or L <= 0 for d, L in segments):
        raise ValueError("segments are (diameter, length) pairs, both positive")
    r = [d / 2 for d, _ in segments]
    c = float(chamfer)
    if c and (c >= min(r[0], r[-1]) or c >= min(segments[0][1], segments[-1][1])):
        raise ValueError("chamfer is larger than an end segment")
    pts: list[tuple[float, float]] = [(0.0, 0.0), (r[0] - c, 0.0), (r[0], c)] if c else [(0.0, 0.0), (r[0], 0.0)]
    z = 0.0
    for i, (_d, L) in enumerate(segments):
        z += L
        if i + 1 < len(segments):
            pts += [(r[i], z), (r[i + 1], z)]
    pts += [(r[-1], z - c), (r[-1] - c, z)] if c else [(r[-1], z)]
    pts.append((0.0, z))
    clean = [(x, y + z0) for i, (x, y) in enumerate(pts) if i == 0 or (x, y) != pts[i - 1]]
    prof = make_face(Plane.XZ * Polyline(*clean, close=True))
    part = revolve(prof, Axis.Z, 360)
    vol = sum(math.pi * (d / 2) ** 2 * L for d, L in segments)
    if c:  # each 45° end chamfer removes a triangle (c x c) revolved about its centroid at radius r - c/3
        for rr in (r[0], r[-1]):
            vol -= c * c / 2 * 2 * math.pi * (rr - c / 3)
    part = fw.feature(name + (f" (chamfers {c:g})" if c else ""), part, segments=len(segments))
    if fillet:
        pts_f, z = [], 0.0
        for i in range(len(segments) - 1):
            z += segments[i][1]
            small = min(r[i], r[i + 1])
            if abs(r[i] - r[i + 1]) <= fillet:
                raise ValueError("shoulder fillet must be smaller than the step height")
            pts_f.append((small, 0.0, z + z0))
            # Pappus: spandrel area (1 - pi/4) f^2 at a centroid 0.2234 f from each leg, outside the small radius
            vol += (1 - math.pi / 4) * fillet ** 2 * 2 * math.pi * (small + (10 - 3 * math.pi) / (12 - 3 * math.pi) * fillet)
        if pts_f:
            from build123d import fillet as _fillet

            part = fw.feature(f"Shoulder fillets R{fillet:g}", _fillet(fw.edges_near(part, pts_f), fillet), r=fillet)
    dmax = max(d for d, _ in segments)
    return part, {"bbox": [dmax, dmax, sum(L for _, L in segments)], "volume": vol, "solids": 1}


def shaft_keyway(part: Any, d: float, z_center: float, length: float, *, b: float | None = None,
                 t1: float | None = None, rounded: bool = True, name: str | None = None,
                 angle: float = 90.0) -> tuple[Any, float]:
    """Keyseat on a Ø d shaft whose axis is Z, on the side `angle` degrees from +X about Z (default 90: +Y): DIN
    6885-1 width and depth unless b/t1 are given, `length` overall along Z centred on z_center, rounded (end-milled,
    form A) or square ends. Returns (part, removed volume from the hand formula)."""
    from build123d import Align, Box, Plane, Pos, Rot, SlotOverall, extrude

    from aicad import fw

    k = din6885(d)
    b, t1 = float(b or k["b"]), float(t1 or k["t1"])
    R = d / 2
    if length <= b:
        raise ValueError("keyway length must exceed its width")
    floor = R - t1
    if rounded:
        sk = Plane(origin=(0, floor, z_center), x_dir=(0, 0, 1), z_dir=(0, 1, 0)) * SlotOverall(length, b)
        tool = extrude(sk, t1 + 1)
    else:
        tool = Pos(0, floor, z_center) * Box(b, t1 + 1, length, align=(Align.CENTER, Align.MIN, Align.CENTER))
    if angle != 90.0:
        tool = Rot(0, 0, angle - 90.0) * tool
    label = name or f"Keyway {b:g}×{t1:g} (DIN 6885)"
    part = fw.feature(label, part - tool, b=b, t1=t1, length=length)

    def depth(x: float) -> float:  # material removed at offset x across the key: cylinder surface down to the floor
        return max(0.0, math.sqrt(max(R * R - x * x, 0.0)) - floor)

    hw = b / 2
    straight = (length - b if rounded else length) * _simpson(depth, -hw, hw)
    # the two half-disc ends make one disc of radius hw: x = hw sin(t) keeps the integrand smooth at the rim
    ends = _simpson(lambda t: 2 * hw * hw * math.cos(t) ** 2 * depth(hw * math.sin(t)), -math.pi / 2, math.pi / 2) \
        if rounded else 0.0
    return part, straight + ends


# ------------------------------------------------------------------ holes
def hole_spec(spec: Any, fit: str = "medium") -> dict[str, Any]:
    """'M8', 'M8 clearance', 'M6 tapped', 'M10 cbore', 'M8 csk' (Hole Wizard tables), a plain diameter, or a custom
    hole as a dict: {"d": 6.6, "cbore": (11, 6.5)} (counterbore Ø × depth) or {"d": 6.6, "csk": (13, 90)}
    (countersink Ø × included angle)."""
    from aicad import holes

    if isinstance(spec, (int, float)):
        return {"d": float(spec), "spec": {"label": f"Ø{spec:g}"}}
    if isinstance(spec, dict):
        d = float(spec["d"])
        if d <= 0:
            raise ValueError("hole Ø must be positive")
        out: dict[str, Any] = {"d": d, "spec": {"label": f"Ø{d:g}"}}
        if spec.get("cbore"):
            cd, ch = (float(x) for x in spec["cbore"])
            if cd <= d or ch <= 0:
                raise ValueError("counterbore needs a Ø larger than the hole and a positive depth")
            out["cbore"] = {"d": cd, "depth": ch}
            out["spec"]["label"] = f"Ø{d:g}, counterbore Ø{cd:g} × {ch:g}"
        elif spec.get("csk"):
            cd, ang = (float(x) for x in spec["csk"])
            if cd <= d or not 0 < ang < 180:
                raise ValueError("countersink needs a Ø larger than the hole and an angle between 0 and 180°")
            out["csk"] = {"d": cd, "angle": ang}
            out["spec"]["label"] = f"Ø{d:g}, countersink Ø{cd:g} × {ang:g}°"
        return out
    words = str(spec).replace("×", "x").split()
    size = words[0].upper().lstrip("M").split("X")[0]
    kind = (words[1] if len(words) > 1 else "clearance").lower()
    kind = {"counterbore": "cbore", "countersink": "csk", "tap": "tapped", "thread": "tapped"}.get(kind, kind)
    return holes.resolve({"type": kind, "size": size, "fit": fit})


def _hole_volume(f: dict[str, Any], depth: float) -> float:
    d = float(f["d"])
    v = math.pi * d * d / 4 * depth
    if f.get("cbore"):
        D, h = float(f["cbore"]["d"]), float(f["cbore"]["depth"])
        v += math.pi * (D * D - d * d) / 4 * h
    elif f.get("csk"):
        dk, ang = float(f["csk"]["d"]), math.radians(float(f["csk"].get("angle", 90)))
        h = (dk - d) / 2 / math.tan(ang / 2)
        v += math.pi * h / 12 * (dk * dk + dk * d + d * d) - math.pi * d * d / 4 * h
    return v


def hole(part: Any, point: Any, spec: Any, depth: float, *, normal: Any = (0, 0, 1), fit: str = "medium",
         thread_depth: float | None = None, name: str | None = None) -> tuple[Any, dict[str, Any]]:
    """One Hole Wizard hole whose top centre is `point` on a face with outward `normal`, drilled `depth` into the
    part. Tapped holes also get the cosmetic thread. Returns (part, {"d", "label", "volume"}); the volume is the hand
    formula for a hole fully in material."""
    return holes_at(part, [point], spec, depth, normal=normal, fit=fit, thread_depth=thread_depth, name=name)


def holes_at(part: Any, points: list[Any], spec: Any, depth: float, *, normal: Any = (0, 0, 1),
             fit: str = "medium", thread_depth: float | None = None, name: str | None = None) -> tuple[Any, dict[str, Any]]:
    """The same hole at several points (one feature). See hole()."""
    from build123d import Vector

    from aicad import fw

    f = hole_spec(spec, fit)
    n = Vector(*normal).normalized()
    tools = [fw._hole_tool(Vector(*p), n, f, depth) for p in points]
    tool = tools[0]
    for t in tools[1:]:
        tool = tool + t
    lab = f.get("spec", {}).get("label") or f"Ø{f['d']:g}"
    part = fw.feature(name or (f"{len(points)}× {lab}" if len(points) > 1 else lab), part - tool, d=f["d"])
    if f.get("spec", {}).get("type") == "tapped":
        size = f["spec"]["size"]
        for p in points:
            q = Vector(*p) - n * 0.5  # a point on the drilled cylinder just below the entry
            part = fw.thread(part, (q.X + f["d"] / 2 * _perp(n).X, q.Y + f["d"] / 2 * _perp(n).Y,
                                    q.Z + f["d"] / 2 * _perp(n).Z), f"M{size:g}x{f['spec']['pitch']:g}",
                             depth=thread_depth or depth)
    return part, {"d": f["d"], "label": lab, "count": len(points), "volume": len(points) * _hole_volume(f, depth)}


def _perp(n: Any) -> Any:
    from build123d import Vector

    a = Vector(1, 0, 0) if abs(n.X) < 0.9 else Vector(0, 1, 0)
    return n.cross(a).normalized()


def bolt_circle(part: Any, n: int, pcd: float, spec: Any, depth: float, *, z: float | None = None,
                center: tuple[float, float] = (0.0, 0.0), start_deg: float = 0.0, normal: Any = (0, 0, 1),
                fit: str = "medium", name: str | None = None) -> tuple[Any, dict[str, Any]]:
    """n equally spaced Hole Wizard holes on a pitch circle Ø pcd in a face normal to Z (top face at height z,
    default the part's top). Returns (part, {"d", "label", "count", "volume", "points"})."""
    if n < 1 or pcd <= 0:
        raise ValueError("need n >= 1 holes on a positive pitch circle")
    if z is None:
        bb = part.bounding_box()
        z = bb.max.Z if normal[2] >= 0 else bb.min.Z
    pts = [(center[0] + pcd / 2 * math.cos(math.radians(start_deg) + 2 * math.pi * i / n),
            center[1] + pcd / 2 * math.sin(math.radians(start_deg) + 2 * math.pi * i / n), z) for i in range(n)]
    lab = hole_spec(spec, fit).get("spec", {}).get("label") or f"Ø{spec}"
    part, info = holes_at(part, pts, spec, depth, normal=normal, fit=fit,
                          name=name or f"{n}× {lab} on PCD {pcd:g}")
    return part, {**info, "points": [list(p) for p in pts]}


# ------------------------------------------------------------------ plates, gussets, cross holes, limits (agent-latency)
def plate(length: float, width: float, thickness: float, *, corner_r: float = 0.0, name: str = "Plate",
          z0: float = 0.0) -> tuple[Any, dict[str, Any]]:
    """A rectangular plate length (X) × width (Y) × thickness (Z), centred on X/Y, from Z = z0 up, with optional
    vertical corner radii. Returns (part, expected) with the hand volume (L W - (4 - pi) r²) T."""
    from build123d import Align, Box, Pos, RectangleRounded, extrude

    from aicad import fw

    if min(length, width, thickness) <= 0:
        raise ValueError("plate sizes must be positive")
    r = float(corner_r)
    if r < 0 or 2 * r >= min(length, width):
        raise ValueError("corner radius must be below half the smaller side")
    body = extrude(RectangleRounded(length, width, r), thickness) if r else \
        Box(length, width, thickness, align=(Align.CENTER, Align.CENTER, Align.MIN))
    if z0:
        body = Pos(0, 0, z0) * body
    part = fw.feature(name + (f" (R{r:g} corners)" if r else ""), body, length=length, width=width, t=thickness)
    return part, {"bbox": [length, width, thickness], "volume": (length * width - (4 - math.pi) * r * r) * thickness,
                  "solids": 1}


def gusset(part: Any, corner: Any, leg_a: Any, leg_b: Any, thickness: float, *, align: str = "center",
           name: str = "Gusset") -> tuple[Any, float]:
    """A flat triangular gusset (rib) in an inside corner. ``corner`` is the inside corner point; ``leg_a`` and
    ``leg_b`` are vectors from it along the two faces, their lengths being the gusset's legs, e.g.
    ``fw.gusset(part, (x, 52, 8), (0, -40, 0), (0, 0, 40), 8)``. The plate is ``thickness`` thick across the legs'
    plane: ``align`` "center" (default) centres it on the corner point, "min" / "max" puts it on the negative /
    positive side of leg_a × leg_b. Returns (part, added volume |leg_a × leg_b| · thickness / 2, exact when the
    gusset lies outside the part)."""
    from build123d import Plane, Polygon, Vector, extrude

    from aicad import fw

    c, a, b = Vector(*corner), Vector(*leg_a), Vector(*leg_b)
    n = a.cross(b)
    if n.length < 1e-9 or thickness <= 0:
        raise ValueError("gusset legs must not be parallel and thickness must be positive")
    n = n.normalized()
    off = {"center": -thickness / 2, "min": -thickness, "max": 0.0}.get(align)
    if off is None:
        raise ValueError("align is center, min or max")
    pl = Plane(origin=c + n * off, x_dir=a.normalized(), z_dir=n)
    ua = a.normalized()
    bx = b.dot(ua)
    by = (b - ua * bx).length
    tri = Polygon((0, 0), (a.length, 0), (bx, by), align=None)
    body = extrude(pl * tri, thickness, dir=(n.X, n.Y, n.Z))
    part = fw.feature(name, part + body, legs=(round(a.length, 6), round(b.length, 6)), t=thickness)
    return part, 0.5 * a.cross(b).length * thickness


def cross_hole_volume(shaft_d: float, d: float) -> float:
    """Material a Ø d through hole removes from a round bar Ø shaft_d when the axes cross at right angles: the
    integral of the hole's section chord times the bar's chord, ∫ 2 sqrt(r² - y²) · 2 sqrt(R² - y²) dy over |y| < r."""
    R, r = shaft_d / 2, d / 2
    if r >= R:
        raise ValueError("a cross hole must be smaller than the bar")
    # y = r sin(t), dy = r cos(t) dt keeps the integrand smooth at the rim
    return _simpson(lambda t: 4 * (r * math.cos(t)) ** 2 * math.sqrt(R * R - (r * math.sin(t)) ** 2),
                    -math.pi / 2, math.pi / 2, 800)


def cross_hole(part: Any, d: float, shaft_d: float, z: float, *, angle: float = 0.0,
               center: tuple[float, float] = (0.0, 0.0), name: str | None = None) -> tuple[Any, float]:
    """A Ø d hole straight through a round bar Ø shaft_d whose axis is Z (through ``center``), at height z, along the
    direction ``angle`` degrees from +X about Z (0 = along X). Returns (part, removed volume by the hand integral)."""
    from build123d import Cylinder, Pos, Rot

    from aicad import fw

    vol = cross_hole_volume(shaft_d, d)
    tool = Pos(center[0], center[1], z) * Rot(0, 0, angle) * Rot(0, 90, 0) * Cylinder(d / 2, shaft_d + 2)
    return fw.feature(name or f"Cross hole Ø{d:g}", part - tool, d=d), vol


def meta(group: str | None = None, unit: str = "mm", **limits: Any) -> dict[str, dict[str, Any]]:
    """PARAM_META in one line per parameter: ``NAME=(min, max)``, ``(min, max, "label")`` or ``(min, max, "label",
    step)``. Step defaults to 1 for ranges of 50 or more, 0.5 from 10, else 0.1; unit mm. Merge groups with |:
    ``PARAM_META = fw.meta("Plate", W=(50, 300, "Width")) | fw.meta("Holes", HOLE_D=(3, 20, "Hole Ø"))``."""
    out: dict[str, dict[str, Any]] = {}
    for k, v in limits.items():
        lo, hi = float(v[0]), float(v[1])
        if hi <= lo:
            raise ValueError(f"{k}: max must exceed min")
        step = float(v[3]) if len(v) > 3 else 1.0 if hi - lo >= 50 else 0.5 if hi - lo >= 10 else 0.1
        m: dict[str, Any] = {"min": v[0], "max": v[1], "step": step, "unit": unit}
        if len(v) > 2 and v[2]:
            m["label"] = str(v[2])
        if group:
            m["group"] = group
        out[k] = m
    return out


# ------------------------------------------------------------------ machined blocks and discs (WORKLIST 45 generators)
_AX = {"x": 0, "y": 1, "z": 2}
_ACROSS = {"z": (0, 1), "y": (0, 2), "x": (1, 2)}  # the part axes a cut's "c" is written in, per cut axis
_EPS = 1e-6


def _body_box(body: Any) -> tuple[list[float], list[float]]:
    kind = body[0]
    if kind == "box":
        L, W, H = (float(x) for x in body[1:4])
        return [-L / 2, -W / 2, -H / 2], [L / 2, W / 2, H / 2]
    if kind == "disc":
        D, H = float(body[1]), float(body[2])
        return [-D / 2, -D / 2, -H / 2], [D / 2, D / 2, H / 2]
    raise ValueError("body is ('box', L, W, H) or ('disc', D, H)")


def _clip(lo: list[float], hi: list[float], blo: list[float], bhi: list[float]) -> tuple[list[float], list[float]]:
    return [max(a, b) for a, b in zip(lo, blo, strict=True)], [min(a, b) for a, b in zip(hi, bhi, strict=True)]


def _span(c: dict[str, Any], blo: list[float], bhi: list[float]) -> tuple[float, float]:
    a = _AX[c["ax"]]
    if c.get("span") is None:
        return blo[a], bhi[a]
    s0, s1 = sorted(float(x) for x in c["span"])
    return max(s0, blo[a]), min(s1, bhi[a])


def _cyl_box(c: dict[str, Any], s: tuple[float, float]) -> tuple[list[float], list[float]]:
    r = float(c["d"]) / 2
    a, (i, j) = _AX[c["ax"]], _ACROSS[c["ax"]]
    lo, hi = [0.0] * 3, [0.0] * 3
    lo[a], hi[a] = s
    lo[i], hi[i] = float(c["c"][0]) - r, float(c["c"][0]) + r
    lo[j], hi[j] = float(c["c"][1]) - r, float(c["c"][1]) + r
    return lo, hi


def _boxes_meet(a: tuple[list[float], list[float]], b: tuple[list[float], list[float]]) -> bool:
    return all(min(a[1][k], b[1][k]) - max(a[0][k], b[0][k]) > _EPS for k in range(3))


def _disk_in_rect(u: float, v: float, r: float, rect: tuple[float, float, float, float]) -> str:
    """'in', 'out' or 'straddle': a disk against an axis-aligned rectangle (u0, u1, v0, v1)."""
    u0, u1, v0, v1 = rect
    if u - r >= u0 - _EPS and u + r <= u1 + _EPS and v - r >= v0 - _EPS and v + r <= v1 + _EPS:
        return "in"
    if u + r <= u0 + _EPS or u - r >= u1 - _EPS or v + r <= v0 + _EPS or v - r >= v1 - _EPS:
        return "out"
    return "straddle"


def _pad_meets_cut(p: dict[str, Any], kp: dict[str, Any], c: dict[str, Any], s: tuple[float, float]) -> bool:
    """A pad across another axis than the cut's: does its box meet the cut's box?"""
    ki, kj = _ACROSS[kp["ax"]]
    klo, khi = list(p["lo"]), list(p["hi"])
    klo[ki], khi[ki] = kp["u"] - kp["r"], kp["u"] + kp["r"]
    klo[kj], khi[kj] = kp["v"] - kp["r"], kp["v"] + kp["r"]
    return _boxes_meet((klo, khi), _cyl_box(c, s))


def _pockets(body: Any, pockets: Any, blo: list[float], bhi: list[float], problems: list[str],
             removed: list[tuple[str, float]]) -> tuple[list[dict[str, Any]], float]:
    pk: list[dict[str, Any]] = []
    total = 0.0
    for p in pockets:
        nm = p.get("name", "pocket")
        if body[0] != "box":
            problems.append("a disc takes no box pockets (use coaxial cuts)")
            continue
        lo, hi = _clip([float(x) for x in p["min"]], [float(x) for x in p["max"]], blo, bhi)
        if any(hi[k] - lo[k] <= _EPS for k in range(3)):
            problems.append(f"{nm} lies outside the body")
            continue
        v = (hi[0] - lo[0]) * (hi[1] - lo[1]) * (hi[2] - lo[2])
        keeps = []
        for kp in p.get("keep") or []:
            a, (i, j) = _AX[kp["ax"]], _ACROSS[kp["ax"]]
            u, w, r = float(kp["c"][0]), float(kp["c"][1]), float(kp["d"]) / 2
            if _disk_in_rect(u, w, r, (lo[i], hi[i], lo[j], hi[j])) != "in":
                problems.append(f"{nm}: a pad Ø{2 * r:g} doesn't fit inside it")
                continue
            v -= math.pi * r * r * (hi[a] - lo[a])
            keeps.append({"ax": kp["ax"], "u": u, "v": w, "r": r})
        pk.append({"name": nm, "lo": lo, "hi": hi, "keeps": keeps})
        total += v
        removed.append((nm, v))
    for n, a in enumerate(pk):
        for b in pk[n + 1:]:
            if _boxes_meet((a["lo"], a["hi"]), (b["lo"], b["hi"])):
                problems.append(f"{a['name']} and {b['name']} overlap")
    return pk, total


def _void(c: dict[str, Any], u: float, w: float, r: float, s: tuple[float, float], pk: list[dict[str, Any]],
          problems: list[str]) -> list[tuple[float, float]]:
    """Where along its axis a cut runs through a pocket (no material there)."""
    a, (i, j) = _AX[c["ax"]], _ACROSS[c["ax"]]
    nm = c.get("name", "cut")
    out: list[tuple[float, float]] = []
    for p in pk:
        o0, o1 = max(s[0], p["lo"][a]), min(s[1], p["hi"][a])
        if o1 - o0 <= _EPS:
            continue
        where = _disk_in_rect(u, w, r, (p["lo"][i], p["hi"][i], p["lo"][j], p["hi"][j]))
        if where == "straddle":
            problems.append(f"{nm} half enters {p['name']}")
            continue
        if where == "out":
            continue
        in_pad = False
        for kp in p["keeps"]:
            if kp["ax"] == c["ax"]:
                dist = math.hypot(u - kp["u"], w - kp["v"])
                if dist + r <= kp["r"] + _EPS:
                    in_pad = True
                elif dist < r + kp["r"] - _EPS:
                    problems.append(f"{nm} half enters a pad of {p['name']}")
            elif _pad_meets_cut(p, kp, c, s):
                problems.append(f"{nm} crosses a pad of {p['name']}")
        if not in_pad:
            out.append((o0, o1))
    return out


def machined_volume(body: Any, pockets: Any = (), cuts: Any = (), chamfers: Any = ()) -> dict[str, Any]:
    """The hand volume of a machined part (pure Python, no CAD kernel): a box ("box", L, W, H) or a disc
    ("disc", D, H, axis Z), centred on the origin, less axis-aligned box pockets (each optionally keeping round pads
    ``keep`` standing in it) and axis-aligned cylindrical cuts (holes, bores, seats, recesses), less 45° rim chamfers
    on a disc. Removed volume: each pocket's box inside the body less its pads; each cut π/4 d² times the length of
    material it passes (its span inside the body, outside every pocket it lies in); coaxial cuts are united by length
    (the larger Ø wins where they overlap); a rim chamfer c removes (c² / 2) · 2π (R - c / 3) (Pappus).

    The formula holds while the features stay apart. Anything it can't sum exactly is listed in ``problems`` (and
    ``machined`` refuses to build it): cuts that overlap other cuts across their axes, a cut that half enters a pocket
    or a pad, a hole breaking out of the side, pockets that overlap."""
    blo, bhi = _body_box(body)
    problems: list[str] = []
    removed: list[tuple[str, float]] = []
    if body[0] == "box":
        vol = (bhi[0] - blo[0]) * (bhi[1] - blo[1]) * (bhi[2] - blo[2])
    else:
        vol = math.pi * (float(body[1]) / 2) ** 2 * float(body[2])
    pk, pv = _pockets(body, pockets, blo, bhi, problems, removed)
    vol -= pv
    cs: list[dict[str, Any]] = []
    for c in cuts:
        i, j = _ACROSS[c["ax"]]
        u, w, r = float(c["c"][0]), float(c["c"][1]), float(c["d"]) / 2
        nm = c.get("name", "cut")
        s = _span(c, blo, bhi)
        if r <= 0 or s[1] - s[0] <= _EPS:
            problems.append(f"{nm}: no size or outside the body")
            continue
        if body[0] == "disc":
            if c["ax"] != "z":
                problems.append(f"{nm}: a disc takes cuts along its axis only")
                continue
            if math.hypot(u, w) + r > float(body[1]) / 2 + _EPS:
                problems.append(f"{nm} breaks out of the rim")
        elif _disk_in_rect(u, w, r, (blo[i], bhi[i], blo[j], bhi[j])) != "in":
            problems.append(f"{nm} breaks out of the side")
        cs.append({**c, "s": s, "u": u, "w": w, "r": r, "void": _void(c, u, w, r, s, pk, problems),
                   "key": (c["ax"], round(u, 6), round(w, 6))})
    for n, a_ in enumerate(cs):
        for b_ in cs[n + 1:]:
            if a_["key"] == b_["key"]:
                continue
            if a_["ax"] == b_["ax"]:
                over = min(a_["s"][1], b_["s"][1]) - max(a_["s"][0], b_["s"][0]) > _EPS
                if over and math.hypot(a_["u"] - b_["u"], a_["w"] - b_["w"]) < a_["r"] + b_["r"] - _EPS:
                    problems.append(f"{a_.get('name', 'cut')} and {b_.get('name', 'cut')} overlap")
            elif _boxes_meet(_cyl_box(a_, a_["s"]), _cyl_box(b_, b_["s"])):
                problems.append(f"{a_.get('name', 'cut')} and {b_.get('name', 'cut')} cross")
    groups: dict[tuple[str, float, float], list[dict[str, Any]]] = {}
    for c in cs:
        groups.setdefault(c["key"], []).append(c)
    for members in groups.values():
        cuts_at = sorted({x for m in members for x in (*m["s"], *(y for v in m["void"] for y in v))})
        for z0, z1 in itertools.pairwise(cuts_at):
            if z1 - z0 <= _EPS:
                continue
            mid = (z0 + z1) / 2
            here = [m for m in members if m["s"][0] - _EPS <= mid <= m["s"][1] + _EPS]
            if not here:
                continue
            big = max(here, key=lambda m: m["r"])
            if any(v0 - _EPS <= mid <= v1 + _EPS for v0, v1 in big["void"]):
                continue
            v = math.pi * big["r"] ** 2 * (z1 - z0)
            vol -= v
            removed.append((big.get("name", "cut"), v))
    for ch in chamfers:
        if body[0] != "disc":
            problems.append("rim chamfers are for discs")
            continue
        R, c = float(body[1]) / 2, float(ch["c"])
        if c <= 0 or c >= R:
            problems.append("a rim chamfer needs 0 < c < R")
            continue
        for m in cs:
            if math.hypot(m["u"], m["w"]) + m["r"] > R - c - _EPS:
                problems.append(f"{m.get('name', 'cut')} runs into the rim chamfer")
        v = c * c / 2 * 2 * math.pi * (R - c / 3)
        vol -= v
        removed.append(("rim chamfer", v))
    seen: set[str] = set()
    problems = [p for p in problems if not (p in seen or seen.add(p))]  # type: ignore[func-returns-value]
    return {"volume": vol, "bbox": [bhi[k] - blo[k] for k in range(3)], "solids": 1, "removed": removed,
            "problems": problems}


def _cyl_tool(c: dict[str, Any], s: tuple[float, float]) -> Any:
    from build123d import Cylinder, Pos, Rot

    a, (i, j) = _AX[c["ax"]], _ACROSS[c["ax"]]
    p = [0.0, 0.0, 0.0]
    p[a] = (s[0] + s[1]) / 2
    p[i], p[j] = float(c["c"][0]), float(c["c"][1])
    rot = {"z": Rot(0, 0, 0), "y": Rot(90, 0, 0), "x": Rot(0, 90, 0)}[c["ax"]]
    return Pos(*p) * rot * Cylinder(float(c["d"]) / 2, s[1] - s[0])


def machined(body: Any, *, pockets: Any = (), cuts: Any = (), chamfers: Any = (),
             name: str = "Body") -> tuple[Any, dict[str, Any]]:
    """Build the part ``machined_volume`` describes (same arguments) and return (part, expected): a box or disc
    centred on the origin, then each pocket, each group of cuts with the same ``name`` (one feature), cosmetic
    threads for cuts with ``thread`` ("M6x1"), and rim chamfers. Cuts: ``{"name", "ax": "x" | "y" | "z", "c": (u, v),
    "d": Ø, "span": (a, b) or None (through), "thread": None}``; ``c`` is the position across the axis in part
    coordinates (X, Y for a Z cut; X, Z for a Y cut; Y, Z for an X cut). Pockets: ``{"name", "min": (x, y, z),
    "max": (x, y, z), "keep": [{"ax", "c", "d"}]}``. Chamfers (disc): ``{"z": ±H / 2, "c": size}``. Raises
    ValueError with the reasons when the hand volume can't be exact."""
    from build123d import Box, Cylinder, Pos
    from build123d import chamfer as _chamfer

    from aicad import fw

    info = machined_volume(body, pockets, cuts, chamfers)
    if info["problems"]:
        raise ValueError("; ".join(info["problems"]))
    blo, bhi = _body_box(body)
    part = Box(*(float(x) for x in body[1:4])) if body[0] == "box" else Cylinder(float(body[1]) / 2, float(body[2]))
    part = fw.feature(name, part, size=" x ".join(f"{float(x):g}" for x in body[1:]))
    pk_boxes = []
    for p in pockets:
        lo, hi = _clip([float(x) for x in p["min"]], [float(x) for x in p["max"]], blo, bhi)
        pk_boxes.append((lo, hi))
        glo = [lo[k] - 1.0 if lo[k] <= blo[k] + _EPS else lo[k] for k in range(3)]
        ghi = [hi[k] + 1.0 if hi[k] >= bhi[k] - _EPS else hi[k] for k in range(3)]
        tool = Pos(*((glo[k] + ghi[k]) / 2 for k in range(3))) * Box(*(ghi[k] - glo[k] for k in range(3)))
        for kp in p.get("keep") or []:
            a = _AX[kp["ax"]]
            tool = tool - _cyl_tool(kp, (glo[a] - 1.0, ghi[a] + 1.0))
        part = fw.feature(p.get("name", "Pocket"), part - tool,
                          depth=round(min(hi[k] - lo[k] for k in range(3)), 6))
    order: list[str] = []
    by: dict[str, list[dict[str, Any]]] = {}
    for c in cuts:
        nm = c.get("name", "Cut")
        if nm not in by:
            order.append(nm)
        by.setdefault(nm, []).append(c)
    for nm in order:
        tool = None
        for c in by[nm]:
            a, (i, j) = _AX[c["ax"]], _ACROSS[c["ax"]]
            s0, s1 = _span(c, blo, bhi)
            g0, g1 = s0, s1
            if s0 <= blo[a] + _EPS:
                g0 -= 1.0
            if s1 >= bhi[a] - _EPS:
                g1 += 1.0
            for lo, hi in pk_boxes:  # an end on a pocket face, inside its opening: run into the pocket
                inside = _disk_in_rect(float(c["c"][0]), float(c["c"][1]), float(c["d"]) / 2,
                                       (lo[i], hi[i], lo[j], hi[j])) == "in"
                if inside and abs(s0 - hi[a]) < _EPS:
                    g0 -= 1.0
                if inside and abs(s1 - lo[a]) < _EPS:
                    g1 += 1.0
            t = _cyl_tool(c, (g0, g1))
            tool = t if tool is None else tool + t
        part = fw.feature(nm, part - tool, d=float(by[nm][0]["d"]), count=len(by[nm]))
        for c in by[nm]:
            if not c.get("thread"):
                continue
            a, (i, j) = _AX[c["ax"]], _ACROSS[c["ax"]]
            s0, s1 = _span(c, blo, bhi)
            entry = c.get("entry")
            if entry is None:
                entry = 1 if s1 >= bhi[a] - _EPS else -1
            q = [0.0, 0.0, 0.0]
            q[a] = (s1 - 0.5) if entry > 0 else (s0 + 0.5)
            q[i], q[j] = float(c["c"][0]) + float(c["d"]) / 2, float(c["c"][1])
            part = fw.thread(part, tuple(q), str(c["thread"]), depth=s1 - s0)
    if chamfers:
        R = float(body[1]) / 2
        edges = fw.edges_near(part, [(R, 0.0, float(ch["z"])) for ch in chamfers])
        part = fw.feature("Rim chamfer", _chamfer(edges, float(chamfers[0]["c"])), length=float(chamfers[0]["c"]))
    return part, {"bbox": info["bbox"], "volume": info["volume"], "solids": 1}


def hub_keyway(part: Any, bore: float, b: float, t2: float, z0: float, z1: float, *, angle: float = 90.0,
               name: str | None = None) -> tuple[Any, float]:
    """A hub keyway b wide, t2 deep above a Ø bore (DIN 6885 t2), from Z z0 to z1, on the side ``angle`` degrees
    from +X about Z (90: +Y). The bore must already be cut. Returns (part, removed volume): the strip b x (bore / 2 +
    t2) less the part of the bore disc inside it, times the length."""
    from build123d import Align, Box, Pos, Rot

    from aicad import fw

    if b <= 0 or t2 <= 0 or z1 <= z0 or b >= bore:
        raise ValueError("a hub keyway needs 0 < b < bore, t2 > 0 and z1 > z0")
    depth = bore / 2 + t2
    tool = Pos(0, 0, z0 - 0.5) * Box(b, depth, z1 - z0 + 1, align=(Align.CENTER, Align.MIN, Align.MIN))
    if angle != 90.0:
        tool = Rot(0, 0, angle - 90.0) * tool
    part = fw.feature(name or f"Keyway {b:g}×{t2:g}", part - tool, b=b, t2=t2)
    return part, (b * depth - _keyway_segment(bore / 2, b)) * (z1 - z0)


def revolved_volume(profile: list[tuple[float, float]]) -> float:
    """Volume of a closed (r, z) polygon revolved 360° about Z (Pappus: 2π times the first moment of its area about
    the axis, from the vertex formula (1/6) Σ (r_i + r_i+1)(r_i z_i+1 - r_i+1 z_i))."""
    m = 0.0
    n = len(profile)
    for k in range(n):
        r0, z0 = profile[k]
        r1, z1 = profile[(k + 1) % n]
        m += (r0 + r1) * (r0 * z1 - r1 * z0)
    return abs(2 * math.pi * m / 6)


def revolved(profile: list[tuple[float, float]], *, name: str = "Revolved body") -> tuple[Any, dict[str, Any]]:
    """A turned part: the closed (r, z) polygon ``profile`` (r >= 0) revolved about Z. Returns (part, expected) with
    the Pappus volume and the bounding box from the profile."""
    from build123d import Axis, Plane, Polyline, make_face, revolve

    from aicad import fw

    if len(profile) < 3 or any(r < 0 for r, _z in profile):
        raise ValueError("a profile is three or more (r, z) points with r >= 0")
    pts = [(float(r), float(z)) for r, z in profile]
    face = make_face(Plane.XZ * Polyline(*pts, close=True))
    part = fw.feature(name, revolve(face, Axis.Z, 360), points=len(pts))
    R = max(r for r, _z in pts)
    return part, {"bbox": [2 * R, 2 * R, max(z for _r, z in pts) - min(z for _r, z in pts)],
                  "volume": revolved_volume(pts), "solids": 1}
