"""Sheet metal (CAD-026): base flange, edge flange, hem, flat pattern (solid + DXF).

A sheet-metal part is kept as a small model next to the solid: flat **panels** (a planar region of constant
thickness T, placed by a frame whose local z = 0 is the panel's "bottom" face and z = T its "top") joined by
cylindrical **bends** (inner radius R, angle θ). Every panel also has a rigid placement in the flat pattern, so the
flat is built from the same model as the folded solid:

- bend allowance BA = θ · (R + K · T)  (θ in radians, K = K-factor, the neutral fibre's position as a fraction of T)
- a flange's flat strip is BA wide; the flange's straight part follows it unrolled.

Conventions (parked as a PD row):
- Flange length ``length_ref="outer"`` is measured from the outer virtual sharp (the intersection of the outer
  faces): straight part = L − (R + T)·tan(θ/2). ``"tangent"`` = the straight part itself. A hem is always tangent.
- Position (where the bend sits relative to the picked edge), setback s of the bend start from the edge:
  θ ≤ 90°: material inside s = (R + T)·tan(θ/2), material outside s = R·tan(θ/2), bend outside s = 0;
  θ > 90°: inside s = R + T, outside s = R, bend outside 0.
- The flange bends towards the side of the picked edge's face (top edge → up); ``flip`` reverses it.
- End offsets (``inset``) shorten the flange from the ends of the edge; the bend then gets reliefs (rectangular or
  obround, width = ratio·T, cut past the bend start line by the same width) unless the relief type is "none".

All functions are pure (no files, globals, time or randomness): the runner replays them on every build and CHK-08
compares rebuilds byte for byte. The model objects are immutable; every operation returns a new one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from build123d import (
    Align,
    Axis,
    Circle,
    Location,
    Plane,
    Pos,
    Rectangle,
    Rot,
    Vector,
    extrude,
    revolve,
)

EPS = 1e-3  # mm: trims and reliefs overcut by this much so they never leave a skin
PICK_TOL = 0.05
POSITIONS = ("inside", "outside", "bend_outside")
RELIEFS = ("rect", "obround", "none")
CORNERS = ("closed", "open")
POSITION_LABEL = {"inside": "Material inside", "outside": "Material outside", "bend_outside": "Bend outside"}


@dataclass(frozen=True)
class Panel:
    id: int
    frame: Location  # panel local -> world
    flat: Location  # panel local -> flat (the base panel's local frame)
    region: Any  # planar region in local XY (z = 0)
    name: str


@dataclass(frozen=True)
class Bend:
    id: int
    name: str
    kind: str  # "flange" | "hem"
    parent: int
    child: int
    c_local: Location  # bend frame in the parent's local coords (x out of the edge, y along it, z = parent normal)
    angle: float
    radius: float
    k: float
    up: bool
    span: float
    ba: float
    straight: float
    length: float
    length_ref: str
    position: str
    ext: tuple[float, float] | None = None  # (lo, hi) along the bend when a corner relief shortened it; None = (0, span)


def extent(b: Bend) -> tuple[float, float]:
    return b.ext if b.ext is not None else (0.0, b.span)


@dataclass(frozen=True)
class Sheet:
    t: float
    r: float
    k: float
    relief: str
    relief_ratio: float
    panels: tuple[Panel, ...]
    bends: tuple[Bend, ...]
    used: tuple[tuple[int, tuple[float, float], tuple[float, float]], ...]  # panel id, segment with a bend on it
    base_name: str
    corner: str = "closed"  # where flanges on adjacent edges meet: "closed" (walls meet with a gap) or "open"
    corner_gap: float = 0.2  # mm, closed corners: between one wall's end and the other wall's inside face


def bend_allowance(angle_deg: float, r: float, k: float, t: float) -> float:
    """BA = θ (R + K T), θ in radians: the developed length of the neutral fibre through the bend."""
    return math.radians(angle_deg) * (r + k * t)


def setback(position: str, angle_deg: float, r: float, t: float) -> float:
    """How far the bend start sits back from the picked edge (see the module notes)."""
    if position == "bend_outside":
        return 0.0
    if angle_deg <= 90.0 + 1e-9:
        tan = math.tan(math.radians(angle_deg) / 2)
        return (r + t) * tan if position == "inside" else r * tan
    return r + t if position == "inside" else r


def straight_length(length: float, length_ref: str, angle_deg: float, r: float, t: float) -> float:
    if length_ref == "outer" and angle_deg < 180.0 - 1e-9:
        return length - (r + t) * math.tan(math.radians(angle_deg) / 2)
    return length


def _tp(loc: Location, v: Any) -> Vector:
    return (loc * Location(Vector(*v) if not isinstance(v, Vector) else v)).position


def _rect(x0: float, y0: float, w: float, h: float) -> Any:
    return Pos(x0, y0) * Rectangle(w, h, align=(Align.MIN, Align.MIN))


def _area(region: Any) -> float:
    try:
        return float(sum(f.area for f in region.faces()))
    except Exception:  # noqa: BLE001 - an empty result
        return 0.0


def _slab(region: Any, t: float) -> Any:
    return extrude(region, amount=t)


# ----------------------------------------------------------------------------- start: base flange
def base(region: Any, frame: Location, t: float, r: float | None = None, k: float = 0.44, relief: str = "rect",
         relief_ratio: float = 0.5, name: str = "Base-Flange", corner: str = "closed",
         corner_gap: float = 0.2) -> tuple[Sheet, Any]:
    """A base flange: the planar ``region`` (local XY of ``frame``) thickened by ``t`` along the frame's +z.
    ``corner`` / ``corner_gap``: how later flanges on adjacent edges meet (see ``_treat_corner``)."""
    t = float(t)
    r = t if r is None else float(r)
    if not t > 0:
        raise ValueError("the sheet thickness must be positive")
    if r < 0:
        raise ValueError("the bend radius can't be negative")
    if not 0 <= k <= 1:
        raise ValueError("the K-factor must be between 0 and 1")
    if relief not in RELIEFS:
        raise ValueError("relief type must be rectangular, obround or none")
    if corner not in CORNERS:
        raise ValueError("corner type must be closed or open")
    if corner_gap < 0:
        raise ValueError("the corner gap can't be negative")
    if _area(region) <= 0:
        raise ValueError("the base flange sketch has no closed profile")
    p = Panel(0, frame, Location(), region, name)
    sheet = Sheet(t, r, float(k), relief, float(relief_ratio), (p,), (), (), name, corner, float(corner_gap))
    return sheet, frame * _slab(region, t)


def with_params(sheet: Sheet, **kw: Any) -> Sheet:
    return replace(sheet, **kw)


# ----------------------------------------------------------------------------- picking an edge
def _line_edge(e: Any) -> tuple[Vector, Vector] | None:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Line

    if BRepAdaptor_Curve(e.wrapped).GetType() != GeomAbs_Line:
        return None
    a, b = e.position_at(0), e.position_at(1)
    return Vector(a.X, a.Y, 0), Vector(b.X, b.Y, 0)


def _on_used(sheet: Sheet, pid: int, q: Vector) -> bool:
    for upid, a, b in sheet.used:
        if upid != pid:
            continue
        av, bv = Vector(a[0], a[1], 0), Vector(b[0], b[1], 0)
        d = bv - av
        ln = d.length
        if ln < 1e-12:
            continue
        s = (q - av).dot(d) / (ln * ln)
        if -1e-6 <= s <= 1 + 1e-6 and (av + d * s - q).length <= PICK_TOL:
            return True
    return False


def find_edge(sheet: Sheet, point: Any, direction: Any | None = None) -> dict[str, Any] | None:
    """The panel edge (on its top or bottom face) through a picked point: panel, side, endpoints and outward normal
    in panel coordinates. None when no free straight sheet edge passes through the point."""
    p = Vector(*point) if not isinstance(point, Vector) else point
    best: tuple[float, dict[str, Any]] | None = None
    used_hit = False
    for pan in sheet.panels:
        inv = pan.frame.inverse()
        q = _tp(inv, p)
        if abs(q.Z) <= PICK_TOL:
            side = "bottom"
        elif abs(q.Z - sheet.t) <= PICK_TOL:
            side = "top"
        elif -PICK_TOL < q.Z < sheet.t + PICK_TOL:  # picked before the thickness changed: nearer face wins
            side = "top" if q.Z >= sheet.t / 2 else "bottom"
        else:
            continue
        q2 = Vector(q.X, q.Y, 0)
        dloc = None
        if direction is not None:
            dv = Vector(*direction)
            if dv.length > 1e-12:
                dl = _tp(inv, p + dv.normalized()) - q
                dloc = Vector(dl.X, dl.Y, 0)
                if dloc.length < 0.5:  # the picked edge isn't parallel to this panel (a thickness edge)
                    continue
                dloc = dloc.normalized()
        for e in pan.region.edges():
            ln = _line_edge(e)
            if ln is None:
                continue
            a, b = ln
            dist = e.distance_to(q2)
            if dist > PICK_TOL:
                continue
            d = b - a
            if d.length < 1e-9:
                continue
            if dloc is not None and abs(d.normalized().dot(dloc)) < 0.999:
                continue
            if _on_used(sheet, pan.id, q2):
                used_hit = True
                continue
            m = (a + b) * 0.5
            n1 = Vector(d.Y, -d.X, 0).normalized()
            dl = min(0.01, sheet.t * 0.05)
            out1 = pan.region.distance_to(m + n1 * dl) > 1e-7
            out2 = pan.region.distance_to(m - n1 * dl) > 1e-7
            if out1 == out2:
                continue  # not a boundary edge with material on one side
            o = n1 if out1 else n1 * -1
            u = Vector(-o.Y, o.X, 0)  # z × o: along the edge, so (o, u, z) is right-handed
            if (b - a).dot(u) < 0:
                a, b = b, a
            cand = {"panel": pan.id, "side": side, "a": a, "b": b, "o": o, "u": u, "length": (b - a).length}
            if best is None or dist < best[0]:
                best = (dist, cand)
    if best is None and used_hit:
        raise ValueError("this edge already has a bend on it; pick a free edge of the sheet")
    return best[1] if best else None


# ----------------------------------------------------------------------------- edge flange / hem / jog
def _bend_local(angle: float, r: float, t: float, up: bool, lo: float, hi: float, pad: float = 0.0) -> Any:
    """The bend solid in its bend frame (x out of the edge, y along it, z = the parent's normal), between ``lo`` and
    ``hi`` along the bend; ``pad`` grows the section through the thickness (cutting tools)."""
    sec = Plane(origin=(0, lo, -pad), x_dir=(0, 1, 0), z_dir=(1, 0, 0)) * Rectangle(
        hi - lo, t + 2 * pad, align=(Align.MIN, Align.MIN))
    axis = Axis((0, 0, t + r), (0, -1, 0)) if up else Axis((0, 0, -r), (0, 1, 0))
    return revolve(sec, axis=axis, revolution_arc=angle)


def _fold(angle: float, r: float, t: float, up: bool) -> Location:
    """Bend frame -> child panel frame: the rotation of the bend about its axis."""
    cz, beta = (t + r, -angle) if up else (-r, angle)
    return Pos(0, 0, cz) * Rot(0, beta, 0) * Pos(0, 0, -cz)


def _poly(pts: list[Vector]) -> Any:
    from build123d import Polygon

    return Polygon(*[(p.X, p.Y) for p in pts], align=None)


def _corner_width(sheet: Sheet) -> float:
    """Corner relief width: relief ratio × T (with relief type "none", half the thickness so the bends still part)."""
    if sheet.relief != "none" and sheet.relief_ratio > 0:
        return sheet.relief_ratio * sheet.t
    return 0.5 * sheet.t


def _corners(sheet: Sheet, e: dict[str, Any], ends: tuple[bool, bool]) -> list[dict[str, Any]]:
    """Existing flanges on the same panel whose bend starts where this edge ends (flanges on adjacent edges).

    For each: the bend, which end of the new flange (0 = a, 1 = b), and which end of the old bend (sigma = +1 at
    its high end). Only square corners between plain flanges are treated."""
    out = []
    a, b, o, u = e["a"], e["b"], e["o"], e["u"]
    tol = 1e-5 * max(1.0, e["length"])
    for b1 in sheet.bends:
        if b1.parent != e["panel"] or b1.kind != "flange":
            continue
        if any(x.parent == b1.child for x in sheet.bends):
            continue  # flanges already hang off that wall: leave the corner as it is
        lo, hi = extent(b1)
        q_lo, q_hi = _tp(b1.c_local, (0, lo, 0)), _tp(b1.c_local, (0, hi, 0))
        u1 = _tp(b1.c_local, (0, 1, 0)) - _tp(b1.c_local, (0, 0, 0))
        o1 = _tp(b1.c_local, (1, 0, 0)) - _tp(b1.c_local, (0, 0, 0))
        if abs(u1.dot(u)) > 1e-6:
            continue  # not a square corner
        for end, pt, has in ((0, a, ends[0]), (1, b, ends[1])):
            if not has:
                continue
            for sigma, q in ((-1, q_lo), (1, q_hi)):
                beyond = u * (1 if end == 1 else -1)  # leaving the new edge at this end
                if (Vector(q.X, q.Y, 0) - pt).length <= tol and (u1 * sigma).dot(o) > 0.999 and o1.dot(beyond) > 0.999:
                    out.append({"bend": b1, "end": end, "sigma": sigma, "yc": hi if sigma > 0 else lo, "o1": o1,
                                "o2": o})
    return out


def _treat_corner(sheet: Sheet, part: Any, c: dict[str, Any], parent: Panel, s2: float, r2: float, angle2: float,
                  up2: bool, region: Any) -> tuple[Sheet, Any, Any, Any | None]:
    """Corner relief where the new flange meets an existing one on the adjacent edge.

    The old flange (bend and wall) is cut back to ``s2 + w`` inside the new edge (w = corner relief width), so in the
    flat its strip ends ``w`` short of the new bend; a w × w square (or a radius-w circle for obround reliefs) is cut
    from the panel where the two bend start lines meet. Closed corners (two 90° flanges bending the same way) then
    carry the old wall on to ``gap`` short of the new wall's inside face and return the extension the new wall needs
    to reach the old wall's outer face. Returns the new sheet, part, parent region and that extension length."""
    t, b1 = sheet.t, c["bend"]
    w = _corner_width(sheet)
    sig, yc = c["sigma"], c["yc"]
    lo, hi = extent(b1)
    cut = s2 + w
    keep_lo, keep_hi = (lo, yc - cut) if sig > 0 else (yc + cut, hi)
    if keep_hi - keep_lo <= 1e-6:
        raise ValueError(f"the flange on the adjacent edge is too short for a corner relief here ({hi - lo:.4g} mm)")
    child = sheet.panels[b1.child]
    ls1 = b1.straight
    cut_lo, cut_hi = (yc - cut, yc + EPS) if sig > 0 else (yc - EPS, yc + cut)
    # 3D: cut the old bend and wall over the corner
    bw = parent.frame * b1.c_local
    tool = bw * _bend_local(b1.angle, b1.radius, t, b1.up, cut_lo, cut_hi, pad=1e-4)
    wall_cut = _rect(-EPS, cut_lo, ls1 + 2 * EPS, cut_hi - cut_lo)
    tool = tool + child.frame * Pos(0, 0, -EPS) * extrude(wall_cut, amount=t + 2 * EPS)
    part = part - tool
    child_region = child.region - wall_cut
    # the relief at the meeting point of the two bend start lines (in the parent panel)
    o1, o2 = c["o1"], c["o2"]  # outward normals of the old and the new edge
    cpt = _tp(b1.c_local, (0, yc, 0)) - o2 * s2
    cpt = Vector(cpt.X, cpt.Y, 0)
    if sheet.relief == "obround":
        rel = Pos(cpt.X, cpt.Y) * Circle(w)
    elif sheet.relief == "rect":
        rel = _poly([cpt + o2 * EPS + o1 * EPS, cpt - o2 * w + o1 * EPS, cpt - o2 * w - o1 * w, cpt + o2 * EPS - o1 * w])
    else:
        rel = None
    if rel is not None:
        region = region - rel
        part = part - parent.frame * Pos(0, 0, -EPS) * extrude(rel, amount=t + 2 * EPS)
    new_ext = None
    closed = (sheet.corner == "closed" and abs(b1.angle - 90) < 1e-9 and abs(angle2 - 90) < 1e-9 and b1.up == up2)
    if closed:
        end_off = r2 - s2 - sheet.corner_gap  # the old wall ends here, along the new edge's outward normal
        y_end = yc + sig * end_off
        a0, a1 = (keep_hi, y_end) if sig > 0 else (y_end, keep_lo)
        if a1 - a0 > 1e-6:
            ext = _rect(0, a0, ls1, a1 - a0)
            child_region = child_region + ext
            part = part + child.frame * _slab(ext, t)
        new_ext = b1.radius + t  # from the old bend start line to the old wall's outer face
    panels = list(sheet.panels)
    panels[child.id] = replace(child, region=child_region)
    bends = list(sheet.bends)
    bends[b1.id] = replace(b1, ext=(keep_lo, keep_hi))
    return replace(sheet, panels=tuple(panels), bends=tuple(bends)), part, region, new_ext


def flange(sheet: Sheet, part: Any, point: Any, length: float, angle: float = 90.0, radius: float | None = None,
           flip: bool = False, position: str = "inside", length_ref: str = "outer",
           inset: tuple[float, float] = (0.0, 0.0), name: str = "Edge-Flange", kind: str = "flange",
           direction: Any | None = None, edge: dict[str, Any] | None = None, child_region: Any = None,
           child_solid: Any = None) -> tuple[Sheet, Any]:
    """Add an edge flange on the straight sheet edge through ``point`` (see the module notes).

    ``child_region`` / ``child_solid`` (jogs) replace the flange's rectangular wall by a given region and solid in
    the child panel's frame."""
    t = sheet.t
    r = sheet.r if radius is None else float(radius)
    angle, length = float(angle), float(length)
    if not 0 < angle <= 180:
        raise ValueError("the flange angle must be between 0 and 180 degrees")
    if r < 0:
        raise ValueError("the bend radius can't be negative")
    if position not in POSITIONS:
        raise ValueError("position must be material inside, material outside or bend outside")
    if length <= 0:
        raise ValueError("the flange length must be positive")
    r = max(r, 1e-3)  # a zero inside radius is modelled as a 0.001 mm radius (a true sharp bend has no solid)
    e = edge or find_edge(sheet, point, direction)
    if e is None:
        raise ValueError("the picked edge was not found: pick a long edge on the top or bottom face of the sheet "
                         "(the geometry may have changed)")
    i0, i1 = (float(inset[0]), float(inset[1]))
    if i0 < 0 or i1 < 0:
        raise ValueError("end offsets can't be negative")
    span = e["length"] - i0 - i1
    if span <= 1e-6:
        raise ValueError(f"the end offsets leave no flange: the edge is {e['length']:.4g} mm long")
    s = setback(position, angle, r, t)
    ls = straight_length(length, "tangent" if kind in ("hem", "jog") else length_ref, angle, r, t)
    if ls <= 1e-6:
        raise ValueError(f"the flange is too short for this bend: an outer length must be more than "
                         f"{(r + t) * math.tan(math.radians(angle) / 2):.4g} mm (R + T times tan(angle/2))")
    up = (e["side"] == "top") != bool(flip)
    a, o, u = e["a"], e["o"], e["u"]
    p0 = a + u * i0 - o * s
    c_local = Location(Plane(origin=(p0.X, p0.Y, 0), x_dir=(o.X, o.Y, 0), z_dir=(0, 0, 1)))

    # corners with flanges already on the adjacent edges (relief, then closed-corner extensions)
    region = sheet.panels[e["panel"]].region
    exts = [0.0, 0.0]
    if kind == "flange" and child_region is None:
        for c in _corners(sheet, e, (i0 <= 1e-9, i1 <= 1e-9)):
            sheet, part, region, ext = _treat_corner(sheet, part, c, sheet.panels[e["panel"]], s, r, angle, up, region)
            if ext:
                exts[c["end"]] = ext
    parent = replace(sheet.panels[e["panel"]], region=region)
    cw = parent.frame * c_local

    # material of the parent between the bend start and the edge goes; reliefs at offset ends
    cuts2d: list[Any] = []
    if s > 0:
        cuts2d.append(_rect(0, 0, s + EPS, span))
    w = sheet.relief_ratio * t
    if sheet.relief != "none" and w > 0:
        for y0, has in ((-w, i0 > 1e-9), (span, i1 > 1e-9)):
            if not has:
                continue
            notch = _rect(-w, y0, s + EPS + w, w)
            if sheet.relief == "obround":
                notch = _rect(-w / 2, y0, s + EPS + w / 2, w) + Pos(-w / 2, y0 + w / 2) * Circle(w / 2)
            cuts2d.append(notch)
    for c2 in cuts2d:
        region = region - c_local * c2
        cut3d = cw * Pos(0, 0, -EPS) * extrude(c2, amount=t + 2 * EPS)
        part = part - cut3d
    if _area(region) <= 1e-9:
        raise ValueError("the bend doesn't fit: the sheet behind this edge is narrower than the bend setback")

    # the bend: the parent's end section swept round the bend axis
    bend_c = _bend_local(angle, r, t, up, 0.0, span)
    if child_region is None:
        child_region = _rect(0, 0, ls, span)
        if exts[0]:
            child_region = child_region + _rect(0, -exts[0], ls, exts[0])
        if exts[1]:
            child_region = child_region + _rect(0, span, ls, exts[1])
    ba = bend_allowance(angle, r, sheet.k, t)
    child_frame = cw * _fold(angle, r, t, up)
    wall = child_frame * (child_solid if child_solid is not None else _slab(child_region, t))
    new = (cw * bend_c) + wall
    try:
        hit = (part & new).volume
    except Exception:  # noqa: BLE001 - treat a failed intersection as a clash
        hit = float("inf")
    if hit > 1e-6 * max(new.volume, 1.0):
        raise ValueError("the flange runs into existing material: shorten it, offset its ends, or flip it")
    part = part + new

    child = Panel(len(sheet.panels), child_frame, parent.flat * c_local * Pos(ba, 0, 0), child_region, name)
    panels = list(sheet.panels)
    panels[parent.id] = replace(parent, region=region)
    panels.append(child)
    b = Bend(len(sheet.bends), name, kind, parent.id, child.id, c_local, angle, r, sheet.k, up, span, ba, ls, length,
             "tangent" if kind in ("hem", "jog") else length_ref, position)
    used = (*sheet.used, (parent.id, (p0.X, p0.Y), (p0.X + u.X * span, p0.Y + u.Y * span)), (child.id, (0.0, 0.0), (0.0, span)))
    return replace(sheet, panels=tuple(panels), bends=(*sheet.bends, b), used=used), part


def jog_flat_length(offset: float, angle: float, r: float, t: float) -> float:
    """Straight length of a jog's middle panel for a bottom-to-bottom ``offset`` (two equal bends, radius r):
    offset = (T + 2R)(1 − cos θ) + m·sin θ."""
    th = math.radians(angle)
    return (offset - (t + 2 * r) * (1 - math.cos(th))) / math.sin(th)


def jog(sheet: Sheet, part: Any, point: Any, distance: float, offset: float, angle: float = 90.0,
        radius: float | None = None, flip: bool = False, name: str = "Jog", direction: Any | None = None,
        edge: dict[str, Any] | None = None) -> tuple[Sheet, Any]:
    """A jog: the sheet between the picked straight edge and a line ``distance`` in from it is raised by
    ``offset`` (bottom face to bottom face; ``flip`` lowers it) through two opposite bends of ``angle``.

    The panel is split along the jog line; the far piece (with any holes already in it) rides on the second bend.
    Both bends start on their lines (no setback), so the flat grows by 2·BA + m (m = the middle panel's length)."""
    t = sheet.t
    r = max(sheet.r if radius is None else float(radius), 1e-3)
    distance, offset, angle = float(distance), float(offset), float(angle)
    if not 0 < angle <= 90:
        raise ValueError("the jog angle must be between 0 and 90 degrees")
    if distance <= 0:
        raise ValueError("the jog line must be inside the sheet: give a positive distance from the edge")
    m = jog_flat_length(offset, angle, r, t)
    if m <= 1e-6:
        low = (t + 2 * r) * (1 - math.cos(math.radians(angle)))
        raise ValueError(f"the jog offset must be more than {low:.4g} mm for this angle and radius "
                         "((T + 2R)(1 − cos angle))")
    e = edge or find_edge(sheet, point, direction)
    if e is None:
        raise ValueError("the picked edge was not found: pick a long edge on the top or bottom face of the sheet "
                         "(the geometry may have changed)")
    pan = sheet.panels[e["panel"]]
    o, u = e["o"], e["u"]
    line0 = e["a"] - o * distance
    bb = pan.region.bounding_box()
    big = 10.0 * (bb.diagonal + abs(bb.center().X) + abs(bb.center().Y)) + 1000.0
    hl = Location(Plane(origin=(line0.X, line0.Y, 0), x_dir=(o.X, o.Y, 0), z_dir=(0, 0, 1)))
    half = hl * _rect(0, -big, big, 2 * big)
    moving, staying = pan.region & half, pan.region - half
    if len(moving.faces()) != 1 or len(staying.faces()) != 1 or _area(moving) <= 1e-9 or _area(staying) <= 1e-9:
        raise ValueError("the jog line must cross the sheet once, between two straight edges")
    for upid, sa, sb in sheet.used:
        if upid != pan.id:
            continue
        for q in (sa, sb):
            if (Vector(q[0], q[1], 0) - line0).dot(o) > -1e-6:
                raise ValueError("a bend is already on the side that moves: add the jog before the flanges there")
    # the edge of the staying piece on the jog line
    hits = []
    for ed in staying.edges():
        ln = _line_edge(ed)
        if ln is not None and all(abs((q - line0).dot(o)) <= 1e-6 for q in ln):
            hits.append(ln)
    if len(hits) != 1:
        raise ValueError("the jog line must cross the sheet once, between two straight edges")
    a1, b1 = hits[0]
    if (b1 - a1).dot(u) < 0:
        a1, b1 = b1, a1
    span = (b1 - a1).length
    # the moving piece (with what's already cut in it), then the panel keeps the staying side
    slab_half = pan.frame * Pos(0, 0, -EPS) * extrude(half, amount=t + 2 * EPS)
    piece = part & slab_half
    if getattr(piece, "volume", 0) > _area(moving) * t * (1 + 1e-6) + 1e-9:
        raise ValueError("the jog would move other flanges: add it before the flanges on that end")
    part = part - slab_half
    panels = list(sheet.panels)
    panels[pan.id] = replace(pan, region=staying)
    sheet = replace(sheet, panels=tuple(panels))
    e1 = {"panel": pan.id, "side": e["side"], "a": a1, "b": b1, "o": o, "u": u, "length": span}
    sheet, part = flange(sheet, part, None, m, angle, r, flip, "bend_outside", "tangent", (0.0, 0.0), f"{name} (1)",
                         kind="jog", edge=e1)
    mid = sheet.panels[-1]
    up1 = sheet.bends[-1].up
    c1 = sheet.bends[-1].c_local  # the first bend's frame in the panel: the jog line, x towards the moving side
    to_local = c1.inverse()
    child_region = to_local * moving
    child_solid = (pan.frame * c1).inverse() * piece
    e2 = {"panel": mid.id, "side": "bottom" if up1 else "top", "a": Vector(m, 0, 0), "b": Vector(m, span, 0),
          "o": Vector(1, 0, 0), "u": Vector(0, 1, 0), "length": span}
    reach = float(child_region.bounding_box().max.X)
    return flange(sheet, part, None, reach, angle, r, False, "bend_outside", "tangent", (0.0, 0.0), f"{name} (2)",
                  kind="jog", edge=e2, child_region=child_region, child_solid=child_solid)


# ----------------------------------------------------------------------------- volumes and the flat pattern
def bend_volume(b: Bend, t: float) -> float:
    lo, hi = extent(b)
    return math.radians(b.angle) / 2 * ((b.radius + t) ** 2 - b.radius ** 2) * (hi - lo)


def model_volume(sheet: Sheet) -> float:
    """Folded volume of the model (panels + bends), from its own numbers."""
    return sum(_area(p.region) for p in sheet.panels) * sheet.t + sum(bend_volume(b, sheet.t) for b in sheet.bends)


def _fuse(pieces: list[Any]) -> Any:
    out = pieces[0]
    for p in pieces[1:]:
        out = out + p
    return out.clean() if hasattr(out, "clean") else out


def _wire_points(wire: Any, n: int = 48) -> list[Vector]:
    """Points along a closed wire in order (lines by their ends, curves sampled), chained end to start so edge
    orientation flags don't matter."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Line

    runs = []
    for ed in wire.edges():
        k = 1 if BRepAdaptor_Curve(ed.wrapped).GetType() == GeomAbs_Line else n
        runs.append([ed.position_at(i / k) for i in range(k + 1)])
    if not runs:
        return []
    pts = list(runs.pop(0))
    while runs:
        end = pts[-1]
        best = min(range(len(runs)), key=lambda i: min((runs[i][0] - end).length, (runs[i][-1] - end).length))
        run = runs.pop(best)
        if (run[-1] - end).length < (run[0] - end).length:
            run = run[::-1]
        pts.extend(run[1:])
    return pts[:-1] if len(pts) > 1 and (pts[-1] - pts[0]).length < 1e-7 else pts


def _simplify(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in pts:
        if out and math.dist(out[-1], p) < 1e-7:
            continue
        out.append(p)
    if len(out) > 1 and math.dist(out[0], out[-1]) < 1e-7:
        out.pop()
    changed = True
    while changed and len(out) > 3:
        changed = False
        for i in range(len(out)):
            a, b, c = out[i - 1], out[i], out[(i + 1) % len(out)]
            if abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) < 1e-9 * max(1.0, math.dist(a, c)):
                out.pop(i)
                changed = True
                break
    return out


def _bend_flat(b: Bend, t: float, part: Any, frame: Location) -> tuple[Any, float]:
    """The bend's strip in the flat (bend frame x = 0..BA), with whatever was cut through the bend unbent onto it.

    Material cut through the bend zone is traced on the neutral surface (radius R + K·T): a point at angle φ from
    the bend start and distance y along the axis lands at x = φ·(R + K·T), y. Returns (region, folded volume)."""
    from build123d import Edge, Face, Wire

    lo, hi = extent(b)
    full = bend_volume(b, t)
    rect = _rect(0, lo, b.ba, hi - lo)
    try:
        common = part & (frame * _bend_local(b.angle, b.radius, t, b.up, lo, hi))
        vol = float(common.volume)
    except Exception:  # noqa: BLE001 - keep the clean strip
        return rect, full
    if abs(vol - full) <= 1e-7 * max(full, 1.0):
        return rect, full
    if vol <= 1e-9:
        return None, 0.0
    rn = b.radius + b.k * t
    zn = t * (1 - b.k) if b.up else b.k * t
    axis = Axis((0, 0, t + b.radius), (0, -1, 0)) if b.up else Axis((0, 0, -b.radius), (0, 1, 0))
    neutral = Face.revolve(Edge.make_line((0, lo - EPS, zn), (0, hi + EPS, zn)), b.angle, axis)
    inv = frame.inverse()
    try:
        sec = (frame * neutral) & common
        faces = sec.faces()
    except Exception:  # noqa: BLE001
        return rect, vol
    th = math.radians(b.angle)

    def to_flat(p: Vector) -> tuple[float, float]:
        q = _tp(inv, p)
        phi = math.atan2(q.X, -(q.Z - (t + b.radius))) if b.up else math.atan2(q.X, q.Z + b.radius)
        if phi < -1e-6:
            phi += 2 * math.pi
        phi = min(max(phi, 0.0), th)
        x = phi * rn
        x = 0.0 if abs(x) < 1e-6 else (b.ba if abs(x - b.ba) < 1e-6 else x)
        y = min(max(q.Y, lo), hi)
        return (x, y)

    def face(lp: list[tuple[float, float]]) -> Any:
        if sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(lp, lp[1:] + lp[:1])) < 0:
            lp = lp[::-1]  # counter-clockwise, so the face's normal is +z and the slab grows up
        return Face(Wire.make_polygon([Vector(x, y, 0) for x, y in lp], close=True))

    out = None
    for fc in faces:
        loops = [_simplify([to_flat(p) for p in _wire_points(w)]) for w in [fc.outer_wire(), *fc.inner_wires()]]
        if len(loops[0]) < 3:
            continue
        f2 = face(loops[0])
        for hole in loops[1:]:
            if len(hole) >= 3:
                f2 = f2 - face(hole)
        out = f2 if out is None else out + f2
    return (out if out is not None else rect), vol


def _curve_entity(e: Any) -> dict[str, Any]:
    """One outline edge of the flat (local XY) as a DXF-ready entity."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line

    def r6(x: float) -> float:
        v = round(float(x), 6)
        return 0.0 if v == 0 else v

    c = BRepAdaptor_Curve(e.wrapped)
    typ = c.GetType()
    a, b = e.position_at(0), e.position_at(1)
    if typ == GeomAbs_Line:
        return {"type": "line", "a": [r6(a.X), r6(a.Y)], "b": [r6(b.X), r6(b.Y)]}
    if typ == GeomAbs_Circle:
        circ = c.Circle()
        ctr, rad = circ.Location(), circ.Radius()
        if (a - b).length < 1e-9:
            return {"type": "circle", "c": [r6(ctr.X()), r6(ctr.Y())], "r": r6(rad)}
        m = e.position_at(0.5)
        ang = [math.degrees(math.atan2(q.Y - ctr.Y(), q.X - ctr.X())) % 360 for q in (a, m, b)]
        ccw = (m.X - a.X) * (b.Y - m.Y) - (m.Y - a.Y) * (b.X - m.X) > 0
        a0, a1 = (ang[0], ang[2]) if ccw else (ang[2], ang[0])
        return {"type": "arc", "c": [r6(ctr.X()), r6(ctr.Y())], "r": r6(rad), "a0": r6(a0), "a1": r6(a1)}
    n = 24
    pts = [e.position_at(i / n) for i in range(n + 1)]
    return {"type": "poly", "pts": [[r6(q.X), r6(q.Y)] for q in pts]}


def flatten(sheet: Sheet, part: Any) -> dict[str, Any]:
    """The flat pattern of the folded ``part``: a solid in the base panel's local frame (``local``) and placed over
    the base (``world``), its outline, bend lines and summary numbers. Cuts made in panels after the flanges (holes,
    notches) are carried into the flat; material outside panels and bends is left out and reported."""
    t = sheet.t
    folded = float(part.volume)
    exact = abs(folded - model_volume(sheet)) <= 1e-6 * max(folded, 1.0)
    pieces: list[Any] = []
    captured = 0.0
    for pan in sheet.panels:
        slab = _slab(pan.region, t)
        if exact:
            local = slab
        else:
            try:
                common = part & (pan.frame * slab)
                local = pan.frame.inverse() * common
            except Exception:  # noqa: BLE001 - fall back to the clean panel
                local = slab
        if getattr(local, "volume", 0) > 1e-9:
            captured += local.volume
            pieces.append(pan.flat * local)
    for b in sheet.bends:
        f = sheet.panels[b.parent].flat * b.c_local
        if exact:
            lo, hi = extent(b)
            reg, vol = _rect(0, lo, b.ba, hi - lo), bend_volume(b, t)
        else:
            reg, vol = _bend_flat(b, t, part, sheet.panels[b.parent].frame * b.c_local)
        if reg is not None:
            pieces.append(f * _slab(reg, t))
        captured += vol
    flat_local = _fuse(pieces)
    base_frame = sheet.panels[0].frame
    world = base_frame * flat_local
    bb = flat_local.bounding_box()
    outline: list[dict[str, Any]] = []
    perimeter = 0.0
    for fc in flat_local.faces():
        try:
            n = fc.normal_at(fc.center())
        except Exception:  # noqa: BLE001,S112 - non-planar faces are not on the bottom
            continue
        if n.Z < -0.999 and abs(fc.center().Z) < 1e-6:
            for e in fc.edges():
                outline.append(_curve_entity(e))
                perimeter += e.length
    outline.sort(key=lambda d: (d["type"], str(d)))
    bends = []
    for i, b in enumerate(sheet.bends, 1):
        f = sheet.panels[b.parent].flat * b.c_local

        def seg(x: float, f: Location = f, b: Bend = b) -> list[list[float]]:
            lo, hi = extent(b)
            p, q = _tp(f, (x, lo, 0)), _tp(f, (x, hi, 0))
            return [[round(p.X, 6) + 0.0, round(p.Y, 6) + 0.0], [round(q.X, 6) + 0.0, round(q.Y, 6) + 0.0]]

        outer = b.straight + (b.radius + t) * math.tan(math.radians(b.angle) / 2) if b.angle < 180 - 1e-9 else None
        bends.append({"n": i, "name": b.name, "kind": b.kind, "direction": "UP" if b.up else "DOWN",
                      "angle": round(b.angle, 6), "radius": round(b.radius, 6), "k": round(b.k, 6),
                      "ba": round(b.ba, 6), "span": round(b.span, 6), "straight": round(b.straight, 6),
                      "length": round(b.length, 6), "length_ref": b.length_ref, "position": b.position,
                      "outer_length": round(outer, 6) if outer is not None else None,
                      "line": seg(b.ba / 2), "tangents": [seg(0.0), seg(b.ba)]})
    notes = []
    if abs(captured - folded) > 1e-4 * max(folded, 1.0):
        notes.append("Some material is not part of a sheet-metal panel or bend and is not shown in the flat "
                     "pattern.")
    return {
        "local": flat_local, "world": world,
        "size": [round(bb.size.X, 6), round(bb.size.Y, 6)],
        "bbox": [round(bb.min.X, 6), round(bb.min.Y, 6), round(bb.max.X, 6), round(bb.max.Y, 6)],
        "area": round(flat_local.volume / t, 6), "perimeter": round(perimeter, 6),
        "outline": outline, "bends": bends, "notes": notes, "exact": exact,
    }


def summary(sheet: Sheet, flat: dict[str, Any]) -> dict[str, Any]:
    """status.json ``sheet_metal``: parameters, flat size and bend table (no geometry objects)."""
    return {"thickness": sheet.t, "radius": sheet.r, "k_factor": sheet.k,
            "relief": {"type": sheet.relief, "ratio": sheet.relief_ratio},
            "corner": {"type": sheet.corner, "gap": sheet.corner_gap},
            "flat": {"size": flat["size"], "bbox": flat["bbox"], "area_mm2": flat["area"],
                     "perimeter_mm": flat["perimeter"]},
            "bend_count": len(flat["bends"]), "bends": flat["bends"], "notes": flat["notes"],
            "formula": "BA = angle(rad) x (R + K x T)"}


# ----------------------------------------------------------------------------- DXF
def write_dxf(flat: dict[str, Any], sm: dict[str, Any], path: Any, material: str | None = None) -> None:
    """Flat pattern DXF at true size (mm): OUTLINE, BEND_UP / BEND_DOWN centre lines (dashed) and BEND_NOTES text
    ("UP 90° R2"). Fixed header dates so the same flat gives the same file."""
    import ezdxf
    from ezdxf import units

    doc = ezdxf.new("R2010", setup=True)
    doc.units = units.MM
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    for k in ("$TDCREATE", "$TDUPDATE", "$TDUCREATE", "$TDUUPDATE"):
        try:
            doc.header[k] = 2451545.0
        except Exception:  # noqa: BLE001,S112 - header var not in this version
            continue
    doc.layers.add("OUTLINE", color=7)
    doc.layers.add("BEND_UP", color=3, linetype="DASHED")
    doc.layers.add("BEND_DOWN", color=1, linetype="DASHED")
    doc.layers.add("BEND_NOTES", color=2)
    doc.layers.add("NOTES", color=8)
    msp = doc.modelspace()
    for ent in flat["outline"]:
        if ent["type"] == "line":
            msp.add_line(ent["a"], ent["b"], dxfattribs={"layer": "OUTLINE"})
        elif ent["type"] == "circle":
            msp.add_circle(ent["c"], ent["r"], dxfattribs={"layer": "OUTLINE"})
        elif ent["type"] == "arc":
            msp.add_arc(ent["c"], ent["r"], ent["a0"], ent["a1"], dxfattribs={"layer": "OUTLINE"})
        else:
            msp.add_lwpolyline(ent["pts"], dxfattribs={"layer": "OUTLINE"})
    t = float(sm["thickness"])
    h = max(1.5, min(5.0, t * 1.5))
    for b in flat["bends"]:
        (x0, y0), (x1, y1) = b["line"]
        layer = "BEND_UP" if b["direction"] == "UP" else "BEND_DOWN"
        msp.add_line((x0, y0), (x1, y1), dxfattribs={"layer": layer})
        rot = math.degrees(math.atan2(y1 - y0, x1 - x0))
        if rot > 90.0001 or rot < -89.9999:
            rot -= 180 if rot > 0 else -180
        txt = f"{b['direction']} {b['angle']:g}%%d R{b['radius']:g}"
        msp.add_text(txt, height=h, rotation=rot, dxfattribs={"layer": "BEND_NOTES"}).set_placement(
            ((x0 + x1) / 2, (y0 + y1) / 2), align=ezdxf.enums.TextEntityAlignment.BOTTOM_CENTER)
    bx = flat["bbox"]
    note = (f"FLAT PATTERN  T {t:g}  K {float(sm['k_factor']):g}  {len(flat['bends'])} BEND(S)"
            + (f"  {material.upper()}" if material else ""))
    msp.add_text(note, height=h, dxfattribs={"layer": "NOTES"}).set_placement((bx[0], bx[1] - 3 * h))
    doc.saveas(str(path))
