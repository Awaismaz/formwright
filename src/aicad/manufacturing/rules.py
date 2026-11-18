"""Advisory DFM rules (CHK-13): CNC milling and drilling, turning, sheet metal and moulding / casting screening.

Each rule is a deterministic function of measured B-rep features and the shop profile. It returns findings with a
rule id, severity, the measured value against its limit, the rationale with its source, a suggested fix and the
topo face ids to highlight. Limits are published guidance or shop inputs, so every finding is a *Recommended check*,
never an approval.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from aicad.manufacturing import ADVICE_LEVELS
from aicad.manufacturing import features as F
from aicad.manufacturing import standards as S
from aicad.manufacturing.geometry import PartGeom
from aicad.manufacturing.shop import ShopProfile

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
PROCESS_LABEL = {"cnc_milling": "CNC milling & drilling", "cnc_turning": "CNC turning", "sheet_metal": "Sheet metal",
                 "moulding_casting": "Moulding & casting"}


@dataclass
class Finding:
    rule: str
    process: str
    severity: str
    title: str
    measured: str
    limit: str
    rationale: str
    fix: str
    source: str
    faces: list[int] = field(default_factory=list)  # B-rep face indices (converted to topo ids on output)
    value: float | None = None
    # What a deterministic parameter fix would aim for: {"kind": radius|diameter|thickness, "to": mm, "why": text}.
    target: dict[str, Any] | None = None
    note: str | None = None  # drawing-note text when the advice is a note rather than a geometry change
    where: str | None = None  # plain description of the faces ("keyway 6 × 30 mm on the Ø25 section")
    also: list[str] = field(default_factory=list)  # other process views this finding belongs to

    def out(self, g: PartGeom, n: int) -> dict[str, Any]:
        return {"id": f"F-{n:02d}", "rule": self.rule, "process": self.process, "severity": self.severity,
                "title": self.title, "measured": self.measured, "limit": self.limit, "value": self.value,
                "rationale": self.rationale, "fix": self.fix, "source": self.source,
                "faces": g.fids(self.faces), "features": g.features(self.faces), "where": self.where,
                "also": list(self.also), "target": self.target, "note": self.note,
                "advice_level": ADVICE_LEVELS["check"]}


@dataclass
class Ctx:
    g: PartGeom
    shop: ShopProfile
    metal: bool
    acc: F.Access
    thick: list[F.Thick]
    holes: list[F.Hole]
    corners: list[F.Corner]
    sharp: list[F.SharpCorner]
    pockets: list[F.Pocket]
    turn: F.Turning
    mould_acc: F.Access | None = None
    pull: str | None = None
    sheet: F.Sheet | None = None
    material: dict[str, Any] = field(default_factory=dict)
    #: sheet-metal model of the part (CAD-026, ``status["sheet_metal"]``): flat size and the bend table
    sheet_model: dict[str, Any] | None = None


@dataclass
class Rule:
    id: str
    name: str
    process: str
    fn: Callable[[Ctx], list[Finding]]
    applies: Callable[[Ctx], bool] = lambda c: True


f2 = S.fmt


# ----------------------------------------------------------------------------- plain descriptions of face sets
def _verts(c: Ctx, faces: list[int] | set[int]) -> np.ndarray:
    arr = [c.g.faces[i].verts for i in faces if len(c.g.faces[i].verts)]
    if arr:
        return np.vstack(arr)
    return np.array([c.g.faces[i].center for i in faces]) if faces else np.zeros((0, 3))


def slot_on_turned_part(c: Ctx, faces: list[int]) -> tuple[float, float, float] | None:
    """(width, length, section diameter) when ``faces`` are a slot along the axis of a turned part (a keyway)."""
    t = c.turn
    if not (t.turnable and t.axis is not None and t.axis_point is not None and faces):
        return None
    if not set(faces) <= set(t.secondary):
        return None
    pts = _verts(c, faces)
    a = t.axis / float(np.linalg.norm(t.axis))
    rel = pts - t.axis_point
    along = rel @ a
    radial = rel - np.outer(along, a)
    cen = radial.mean(axis=0)
    if float(np.linalg.norm(cen)) < 1e-6:
        return None
    tdir = np.cross(a, cen / float(np.linalg.norm(cen)))
    ln = float(np.ptp(along))
    w = float(np.ptp(rel @ tdir))
    if w <= 1e-6 or ln < w:
        return None
    lo, hi = float((pts @ a).min()), float((pts @ a).max())
    rev = set(t.revolved)
    ds = [2 * float(f.radius) for f in c.g.faces if f.i in rev and f.kind == "cylinder" and f.concave is False
          and f.radius and f.extent_along(a)[0] < hi - 1e-6 and f.extent_along(a)[1] > lo + 1e-6]
    return round(w, 3), round(ln, 3), round(max(ds), 3) if ds else round(t.max_d, 3)


def describe(c: Ctx, faces: list[int]) -> str | None:
    """Where a finding is, in shop words, for reports and prompts (face ids mean nothing outside the app)."""
    if not faces:
        return None
    fs = set(faces)
    if len(fs) > 0.6 * len(c.g.faces) and len(fs) > 6:
        return f"edges and faces across the whole part ({len(fs)} faces)"
    hs = [h for h in c.holes if set(h.faces) & fs]
    if hs and fs <= {i for h in hs for i in h.faces}:
        groups: dict[tuple[float, bool, float], int] = {}
        for h in hs:
            k = (round(h.d, 3), h.through, round(h.depth, 2))
            groups[k] = groups.get(k, 0) + 1
        return "; ".join((f"{n}× " if n > 1 else "") + f"Ø{f2(d)} "
                         + ("through hole" if th else f"blind hole, {f2(dep)} deep") + ("s" if n > 1 and th else "")
                         for (d, th, dep), n in sorted(groups.items()))
    slot = slot_on_turned_part(c, sorted(fs))
    if slot:
        return f"keyway {f2(slot[0])} × {f2(slot[1])} mm on the Ø{f2(slot[2])} section"
    for pk in c.pockets:
        pf = {pk.floor, *pk.walls}
        if fs <= pf:
            pts = _verts(c, pf)
            ax = "XYZ".index(pk.direction[-1])
            ext = [float(np.ptp(pts[:, i])) for i in range(3) if i != ax]
            what = "corners of the pocket" if fs != pf else "pocket"
            return f"{what} {f2(max(ext))} × {f2(min(ext))} mm, {f2(pk.depth)} deep from {pk.direction}"
    cyl = [c.g.faces[i] for i in fs]
    if all(f.kind == "cylinder" and f.radius and f.axis is not None and (f.sweep or 0) < 2 * math.pi - 1e-3
           for f in cyl):
        radii = sorted({round(float(f.radius), 3) for f in cyl})
        a = cyl[0].axis / float(np.linalg.norm(cyl[0].axis))  # type: ignore[union-attr,operator]
        ln = max(f.extent_along(a)[1] - f.extent_along(a)[0] for f in cyl)
        side = "internal" if all(f.concave for f in cyl) else "external" if all(f.concave is False for f in cyl) \
            else "blend"
        return (f"{side} " + " / ".join(f"R{f2(r)}" for r in radii) + f" radius, {f2(ln, 1)} mm long"
                + (f" ({len(cyl)} faces)" if len(cyl) > 1 else ""))
    t = c.turn
    if t.turnable and fs <= set(t.revolved):
        ds = sorted({2 * float(c.g.faces[i].radius) for i in fs
                     if c.g.faces[i].kind == "cylinder" and c.g.faces[i].radius})
        if ds:
            return "turned " + " / ".join(f"Ø{f2(d)}" for d in ds) + " section" + ("s" if len(ds) > 1 else "")
    pts = _verts(c, fs)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    mid = (lo + hi) / 2
    size = " × ".join(f2(float(v), 1) for v in hi - lo)
    return (f"{len(fs)} face{'s' if len(fs) > 1 else ''} in a {size} mm region around "
            f"X {f2(float(mid[0]), 1)}, Y {f2(float(mid[1]), 1)}, Z {f2(float(mid[2]), 1)}")


# ----------------------------------------------------------------------------- CNC milling
def r_corner_radius(c: Ctx) -> list[Finding]:
    tool_r = c.shop.smallest_tool_d_mm / 2
    groups: dict[tuple[str, float, float], list[F.Corner]] = {}
    for k in c.corners:
        if k.kind != "vertical":
            continue
        if k.r < tool_r - 1e-6:
            sev = "critical"
        elif k.r < S.GUIDE["corner_radius_to_depth"] * k.depth - 1e-6:
            sev = "warning"
        else:
            continue
        groups.setdefault((sev, round(k.r, 4), round(k.depth, 3)), []).append(k)
    out = []
    for (sev, r, depth), ks in sorted(groups.items(), key=lambda x: (SEVERITY_ORDER[x[0][0]], x[0][1])):
        n = len(ks)
        if sev == "critical":
            out.append(Finding(
                "DFM-CNC-01", "cnc_milling", sev, f"Internal corner R{f2(r)} is smaller than your smallest tool",
                f"R{f2(r)} ({n} corner{'s' if n > 1 else ''}, {f2(depth)} mm deep)",
                f"≥ R{f2(tool_r)} (smallest tool Ø{f2(c.shop.smallest_tool_d_mm)} in the shop profile)",
                "A rotating cutter leaves at least its own radius in a vertical internal corner. A corner radius "
                "below the smallest available tool radius cannot be milled as modelled.",
                f"Increase the corner radius to at least R{f2(tool_r * 1.1)} (about 10 % above the tool radius), or "
                "add a smaller tool to the shop profile if one is available. Sharp corners need EDM.",
                "Shop profile (smallest tool) and " + S.HUBS, [k.face for k in ks], r,
                target={"kind": "radius", "to": S.nice_up(tool_r * 1.1), "why": f"≥ R{f2(tool_r * 1.1)}"}))
        else:
            need = depth / (2 * r)
            out.append(Finding(
                "DFM-CNC-01", "cnc_milling", sev, f"Corner R{f2(r)} is tight for a {f2(depth)} mm deep cavity",
                f"R{f2(r)} at {f2(depth)} mm depth (tool L/D ≈ {f2(need, 1)})",
                f"≥ R{f2(depth / 3)} (⅓ of the cavity depth)",
                "Deep corners with small radii need long, slender cutters that must run slowly to avoid deflection "
                "and chatter.", f"Increase the corner radius to about R{f2(depth / 3)} or reduce the cavity depth.",
                S.HUBS, [k.face for k in ks], r,
                target={"kind": "radius", "to": S.nice_up(depth / 3), "why": f"≥ R{f2(depth / 3)}"}))
    return out


def r_sharp_internal(c: Ctx) -> list[Finding]:
    if not c.sharp:
        return []
    faces = sorted({i for s in c.sharp for i in s.faces})
    tool_r = c.shop.smallest_tool_d_mm / 2
    n = len(c.sharp)
    slot = slot_on_turned_part(c, faces)
    if slot:
        w, ln, _dia = slot
        return [Finding(
            "DFM-CNC-02", "cnc_milling", "critical", f"Keyway has square ends: {n} sharp internal corners cannot be "
            "milled", f"R0 on {n} concave edges of the {f2(w)} × {f2(ln)} mm keyway", f"≥ R{f2(tool_r)} (smallest "
            "tool radius); an end-mill keyway has R = width / 2",
            "A keyway on a shaft is cut with an end mill (or a disc cutter) along the axis. An end mill leaves "
            "full-radius ends equal to half the keyway width; a square end needs EDM, broaching or a slotting "
            "machine.",
            f"Model the keyway with full-radius ends, R = width / 2 = R{f2(w / 2)} (an end-mill keyway cut with a "
            f"Ø{f2(w)} end mill), keeping the {f2(ln)} mm length. Or let the ends run out with a disc cutter (sled "
            "runner keyway).", S.HUBS + "; common keyway practice (end-mill and sled-runner keyseats)", faces, 0.0)]
    return [Finding(
        "DFM-CNC-02", "cnc_milling", "critical", f"{n} sharp internal corner{'s' if n > 1 else ''} cannot be milled",
        f"R0 on {n} concave edge{'s' if n > 1 else ''}", f"≥ R{f2(tool_r)} (smallest tool radius)",
        "Neither face at these internal edges can be cut by a flat end face from one of the six principal "
        "directions, so a rotating cutter leaves its radius in the corner.",
        f"Model a corner radius of at least R{f2(tool_r * 1.1)} (or the radius of the intended cutter), add a "
        "corner relief, or plan EDM for a truly sharp corner.", S.HUBS, faces, 0.0)]


def r_blend(c: Ctx) -> list[Finding]:
    tool_r = c.shop.smallest_tool_d_mm / 2
    bl = [k for k in c.corners if k.kind == "blend"]
    if not bl:
        return []
    small = [k for k in bl if k.r < tool_r - 1e-6]
    out = []
    if small:
        r = min(k.r for k in small)
        out.append(Finding(
            "DFM-CNC-03", "cnc_milling", "warning", f"Internal radius R{f2(r)} is smaller than your smallest tool",
            f"R{f2(r)} ({len(small)} blend face{'s' if len(small) > 1 else ''})",
            f"≥ R{f2(tool_r)} (smallest ball or corner-radius tool)",
            "Internal blends that are not along a tool axis are cut with a ball-nose or corner-radius tool whose "
            "radius must not exceed the blend radius.",
            "Increase the blend radius, or confirm the shop has a smaller ball-nose cutter.",
            "Shop profile (smallest tool)", [k.face for k in small], r,
            target={"kind": "radius", "to": S.nice_up(tool_r), "why": f"≥ R{f2(tool_r)}"}))
    rest = [k for k in bl if k not in small]
    if rest:
        r = min(k.r for k in rest)
        out.append(Finding(
            "DFM-CNC-03", "cnc_milling", "info", "Internal radii away from a pocket floor",
            f"{len(rest)} face{'s' if len(rest) > 1 else ''}, smallest R{f2(r)}", "Tool radius ≤ internal radius",
            "These internal radii have no pocket floor. They are cut along their axis with the tool flank (the tool "
            "must cover the full length) or with a ball-nose or corner-radius cutter in finishing passes.",
            "Keep the radius if it is functional (stress, fit). Otherwise check with your shop which tool and "
            "direction they will use.", "General machining practice", [k.face for k in rest], r))
    return out


def r_cavity(c: Ctx) -> list[Finding]:
    out = []
    lim = S.GUIDE["cavity_depth_to_width"]
    tool_d = c.shop.smallest_tool_d_mm
    for p in sorted(c.pockets, key=lambda p: p.floor):
        ratio = p.depth / p.width if p.width > 0 else math.inf
        faces = [p.floor, *p.walls]
        if p.width < tool_d - 1e-6:
            out.append(Finding(
                "DFM-CNC-04", "cnc_milling", "critical", f"Cavity opening {f2(p.width)} mm is narrower than your "
                "smallest tool", f"{f2(p.width)} mm wide, {f2(p.depth)} mm deep (from {p.direction})",
                f"≥ Ø{f2(tool_d)} (smallest tool)", "The cutter has to fit into the opening to reach the floor.",
                "Widen the slot or cavity, or confirm a smaller cutter (or wire EDM) is available.",
                "Shop profile (smallest tool)", faces, p.width))
        elif ratio > lim + 1e-9:
            out.append(Finding(
                "DFM-CNC-04", "cnc_milling", "warning", "Deep, narrow cavity",
                f"depth / width = {f2(ratio)} ({f2(p.depth)} mm deep, {f2(p.width)} mm wide, from {p.direction})",
                f"≤ {f2(lim)}", "End mills cut reliably to about 3-4 × their diameter; deeper cavities need long-reach "
                "tools, step-downs and slower feeds.",
                f"Reduce the depth to about {f2(lim * p.width)} mm, widen the cavity, or split the part.", S.HUBS,
                faces, ratio))
    return out


def r_thin_wall(c: Ctx) -> list[Finding]:
    lim = c.shop.min_wall_metal_mm if c.metal else c.shop.min_wall_plastic_mm
    thin = [t for t in c.thick if t.wall and t.t < lim - 1e-6]
    if not thin:
        return []
    tmin = min(t.t for t in thin)
    faces = sorted({t.face for t in thin} | {t.hit for t in thin if t.hit is not None})
    sev = "critical" if tmin < 0.5 * lim else "warning"
    kind = "metal" if c.metal else "plastic"
    return [Finding(
        "DFM-CNC-05", "cnc_milling", sev, f"Thin wall {f2(tmin)} mm",
        f"{f2(tmin)} mm minimum wall (ray-sampled between opposite faces)", f"≥ {f2(lim)} mm for {kind} parts",
        "Thin walls vibrate and deflect under cutting forces, which limits accuracy and can break the wall.",
        f"Thicken the wall to at least {f2(lim)} mm, or support it during machining (leave stock, machine it last).",
        S.HUBS + " (minimum wall thickness)", faces, tmin,
        target={"kind": "thickness", "to": S.nice_up(lim), "why": f"≥ {f2(lim)} mm"})]


def r_undercut(c: Ctx) -> list[Finding]:
    if not c.acc.undercut:
        return []
    n = len(c.acc.undercut)
    has5 = any(m.kind == "mill5" for m in c.shop.machines)
    return [Finding(
        "DFM-CNC-06", "cnc_milling", "warning", f"{n} face{'s' if n > 1 else ''} not reachable from the six setup "
        "directions", f"{n} face{'s' if n > 1 else ''} hidden from ±X, ±Y and ±Z",
        "Every machined face reachable from a principal direction (3-axis)",
        "These faces are shadowed by other material from every principal direction (undercuts). They need "
        "special cutters (T-slot, dovetail, lollipop), " + ("the 5-axis machine in your profile" if has5 else
                                                             "a 4/5-axis machine") + " or a design change.",
        "Open the undercut to a principal direction, split the part, or check that a special cutter can reach it.",
        "Geometric reachability test (rays along ±X, ±Y, ±Z)", list(c.acc.undercut), float(n))]


def r_setups(c: Ctx) -> list[Finding]:
    n = len(c.acc.setups)
    extra = [i for d in c.acc.setups[2:] for i in c.acc.by_setup.get(d, [])]
    sev = "warning" if n >= 3 else "info"
    return [Finding(
        "DFM-CNC-07", "cnc_milling", sev, f"Estimated {n} setup{'s' if n > 1 else ''} on a 3-axis mill",
        f"{n} setup{'s' if n > 1 else ''}: {', '.join(c.acc.setups)}", "Fewer setups cost less (each one needs "
        "fixturing and re-referencing)",
        "Minimum number of principal directions from which every reachable face can be machined (tool reach "
        f"{f2(c.shop.max_tool_reach_mm)} mm, flank {f2(c.shop.max_flank_mm)} mm). Assumes the part is cut from a solid block and every face is machined.",
        "Bring features onto fewer sides of the part where you can; faces needing the extra setups are highlighted."
        if n >= 3 else "No action needed.", "Geometric reachability test; shop profile (tool reach and flank length)",
        extra if n >= 3 else [], float(n))]


def r_envelope(c: Ctx) -> list[Finding]:
    dims = sorted(c.g.size.tolist(), reverse=True)
    mills = c.shop.mills()
    if not mills:
        return [Finding("DFM-CNC-08", "cnc_milling", "info", "No milling machine in the shop profile",
                        "—", "—", "The envelope could not be checked against a milling machine.",
                        "Add your milling machines to the shop profile.", "Shop profile", [], None)]
    fits = [m for m in mills if m.travel_mm and all(a <= b + 1e-6 for a, b in zip(dims, sorted(m.travel_mm,
                                                                                               reverse=True)))]
    if fits:
        return []
    return [Finding(
        "DFM-CNC-08", "cnc_milling", "critical", "Part is larger than every milling machine in your shop",
        "envelope " + " × ".join(f2(d, 1) for d in dims) + " mm",
        "; ".join(f"{m.name}: " + " × ".join(f2(t, 0) for t in sorted(m.travel_mm or [], reverse=True))
                  for m in mills),
        "The part envelope (in any orientation) exceeds the machine travel.",
        "Split the part, choose a larger machine or outsource.", "Shop profile (machine travel)", [], dims[0])]


def r_edges(c: Ctx) -> list[Finding]:
    out = []
    acute = [e for e in c.g.edges if e.convexity == "convex" and e.angle_deg > 120.0]
    if acute:
        faces = sorted({i for e in acute for i in e.faces})
        amin = min(180.0 - e.angle_deg for e in acute)
        out.append(Finding(
            "DFM-EDGE-01", "cnc_milling", "warning", f"{len(acute)} acute external edge{'s' if len(acute) > 1 else ''}",
            f"included angle down to {f2(amin, 1)}°", "≥ 60° included angle (or a flat / chamfer)",
            "Knife edges are fragile, burr heavily and are hard to deburr or handle safely.",
            "Add a small flat or chamfer on the acute edges, or specify an edge break.", "General machining practice",
            faces, amin))
    sharp = [e for e in c.g.edges if e.convexity == "convex" and 30.0 <= e.angle_deg <= 120.0]
    if sharp:
        out.append(Finding(
            "DFM-EDGE-02", "cnc_milling", "info", "Drawing note suggested: break sharp edges",
            f"{len(sharp)} convex edges without a chamfer or fillet", "Edge break specified on the drawing",
            "Machined edges carry burrs. Shops normally break sharp edges by deburring; modelled micro-fillets add "
            "tool changes and time.", "Add a drawing note such as \"break all sharp edges 0.2-0.5 mm\" instead of "
            "modelling small fillets.", "General machining practice (drawing note)",
            sorted({i for e in sharp for i in e.faces}), float(len(sharp)),
            note="BREAK ALL SHARP EDGES 0.2-0.5 MM UNLESS OTHERWISE SPECIFIED."))
    fil = [f for f in c.g.faces if f.kind == "cylinder" and f.concave is False and (f.sweep or 0) < 2 * math.pi - 1e-3
           and any(c.g.edges[e].convexity == "smooth" for e in f.edges)]
    if fil:
        out.append(Finding(
            "DFM-EDGE-03", "cnc_milling", "info", f"{len(fil)} external fillet face{'s' if len(fil) > 1 else ''}",
            f"smallest R{f2(min(float(f.radius or 0) for f in fil))}", "Chamfer or edge break where acceptable",
            "External fillets need a corner-rounding cutter or 3D finishing passes; a chamfer is usually quicker.",
            "Keep the fillets that are functional; replace cosmetic ones with chamfers or an edge-break note.",
            "General machining practice", [f.i for f in fil], None))
    return out


# ----------------------------------------------------------------------------- holes
def _hole_groups(c: Ctx) -> dict[tuple[float, float, tuple[str, ...], str | None], list[F.Hole]]:
    gr: dict[tuple[float, float, tuple[str, ...], str | None], list[F.Hole]] = {}
    for h in c.holes:
        gr.setdefault((round(h.d, 4), round(h.depth, 3), tuple(h.blind_ends), h.bottom), []).append(h)
    return gr


def r_hole_ld(c: Ctx) -> list[Finding]:
    out = []
    for (d, depth, ends, _b), hs in sorted(_hole_groups(c).items()):
        ld = depth / d
        if ld <= c.shop.max_drill_ld + 1e-9:
            continue
        sev = "critical" if ld > c.shop.deep_drill_ld + 1e-9 else "warning"
        n = len(hs)
        out.append(Finding(
            "DFM-HOLE-01", "cnc_milling", sev, f"Deep hole Ø{f2(d)} × {f2(depth)} mm",
            f"L/D = {f2(ld)} ({n} hole{'s' if n > 1 else ''}, {'blind' if ends else 'through'})",
            f"≤ {f2(c.shop.max_drill_ld)} recommended, ≤ {f2(c.shop.deep_drill_ld)} typical maximum",
            "Standard twist drills evacuate chips well to about 4 × D. Deeper holes need peck cycles or long-series "
            "drills; beyond about 10 × D they need gun drilling.",
            f"Reduce the depth (e.g. drill from both sides), counterbore the entry, or increase the diameter to "
            f"about Ø{f2(depth / c.shop.max_drill_ld, 1)}.", S.HUBS + "; shop profile (drill L/D)",
            [i for h in hs for i in h.faces], ld))
    return out


def r_hole_std(c: Ctx) -> list[Finding]:
    out = []
    by_d: dict[float, list[F.Hole]] = {}
    for h in c.holes:
        by_d.setdefault(round(h.d, 4), []).append(h)
    for d, hs in sorted(by_d.items()):
        if d > S.DRILL_MAX:
            continue
        faces = [i for h in hs for i in h.faces]
        n = len(hs)
        through = all(h.through for h in hs)
        holes_txt = f"{n} {'through' if through else 'blind'} hole{'s' if n > 1 else ''}" + (
            " in a pattern" if n > 1 else "")
        clear = S.clearance_matches(d)
        taps = S.tap_drill_matches(d)
        if through:
            # A through hole (most often in a bolt pattern) is read as a clearance hole: ISO 273 decides.
            thread = S.clearance_thread(d)
            if clear:
                names = [f"ISO 273 {s} clearance for {t}" for t, s in clear]
                out.append(Finding(
                    "DFM-HOLE-02", "cnc_milling", "info", f"Ø{f2(d)} is a standard clearance hole",
                    f"Ø{f2(d)} ({holes_txt})", "; ".join(names),
                    "Through holes are read as clearance holes for bolts or screws. This diameter is in the ISO 273 "
                    "table, so it is a stocked drill and fits the fastener with the stated clearance.",
                    "No action needed. " + S.VERIFY, S.ISO_273_SOURCE, faces, d))
            elif thread:
                f_, m_, c_ = S.ISO_273[thread]
                lo, hi = S.clearance_neighbours(d)
                between = (f"between {lo[0]} {lo[1]} Ø{f2(lo[2])} and {hi[0]} {hi[1]} Ø{f2(hi[2])}"
                           if lo and hi else f"in the {thread} range")
                tap = (f" If the hole is meant to be tapped through, Ø{f2(d)} is the tap drill for "
                       f"{', '.join(taps)} coarse; then show the thread on the drawing." if taps else "")
                out.append(Finding(
                    "DFM-HOLE-02", "cnc_milling", "warning", f"Ø{f2(d)} is not a standard clearance hole",
                    f"Ø{f2(d)} ({holes_txt}), {between}",
                    f"ISO 273 for {thread}: fine Ø{f2(f_)} / medium Ø{f2(m_)} / coarse Ø{f2(c_)}",
                    "Through holes in a bolt pattern are clearance holes. A diameter between the ISO 273 series gives "
                    "a clearance nobody specified, and the fastener size is left to guesswork.",
                    f"Use the ISO 273 size for the intended bolt, e.g. Ø{f2(m_)} ({thread} medium) or Ø{f2(c_)} "
                    f"({thread} coarse, for a looser pattern fit).{tap} " + S.VERIFY,
                    f"{S.ISO_273_SOURCE}; {S.TAP_DRILL_SOURCE}", faces, d,
                    target={"kind": "diameter", "to": m_, "why": f"ISO 273 {thread} medium clearance"}))
            elif taps:
                out.append(Finding(
                    "DFM-HOLE-02", "cnc_milling", "info", f"Ø{f2(d)} matches a tap drill",
                    f"Ø{f2(d)} ({holes_txt})", f"tap drill for {', '.join(taps)} coarse",
                    "This through hole is not an ISO 273 clearance size but equals a tap drill, so it reads as a "
                    "hole to be tapped through.", "If it is to be tapped, show the thread on the drawing. " + S.VERIFY,
                    S.TAP_DRILL_SOURCE, faces, d))
            elif not S.is_stock_drill(d):
                out.append(_non_stock(d, holes_txt, faces))
            continue
        if taps or clear:
            names = [f"tap drill for {t} coarse" for t in taps] + [f"ISO 273 {s} clearance for {t}" for t, s in clear]
            out.append(Finding(
                "DFM-HOLE-02", "cnc_milling", "info", f"Ø{f2(d)} matches a standard hole size",
                f"Ø{f2(d)} ({holes_txt})", "; ".join(names),
                "A blind hole of a tap-drill size is normally tapped; standard sizes use stocked drills.",
                ("If it is to be tapped, show the thread and its depth on the drawing. " if taps else "No action "
                 "needed. ") + S.VERIFY, f"{S.TAP_DRILL_SOURCE}; {S.ISO_273_SOURCE}", faces, d))
        elif not S.is_stock_drill(d):
            out.append(_non_stock(d, holes_txt, faces))
    return out


def _non_stock(d: float, holes_txt: str, faces: list[int]) -> Finding:
    near = S.nearest_stock_drill(d)
    return Finding(
        "DFM-HOLE-02", "cnc_milling", "warning", f"Non-standard hole diameter Ø{f2(d, 3)}",
        f"Ø{f2(d, 3)} ({holes_txt})", f"stocked drill size (nearest Ø{f2(near)})",
        "Diameters off the stocked drill series need interpolation, boring or a special drill or reamer, which "
        "adds time and tool cost.",
        f"Use Ø{f2(near)}, or the ISO 273 clearance / tap drill size for the intended fastener. " + S.VERIFY,
        S.DRILL_SERIES_SOURCE, faces, d, target={"kind": "diameter", "to": near, "why": "nearest stocked drill"})


def r_hole_bottom(c: Ctx) -> list[Finding]:
    flat = [h for h in c.holes if h.blind_ends and h.bottom == "plane" and h.d <= S.DRILL_MAX]
    if not flat:
        return []
    return [Finding(
        "DFM-HOLE-03", "cnc_milling", "info", f"{len(flat)} flat-bottom blind hole{'s' if len(flat) > 1 else ''}",
        "flat bottom", "118° drill point (standard)",
        "Twist drills leave a conical (118°) bottom. A flat bottom needs an extra end-mill or flat-bottom-drill pass.",
        "Allow a drill-point bottom unless the flat bottom is functional (e.g. a seating face).",
        "General machining practice", [i for h in flat for i in h.faces], None)]


# ----------------------------------------------------------------------------- turning
def _turn_applies(c: Ctx) -> bool:
    return c.turn.turnable


def r_turn_detect(c: Ctx) -> list[Finding]:
    t = c.turn
    return [Finding(
        "TRN-01", "cnc_turning", "info", "Rotational part: suited to turning",
        f"{f2(100 * t.revolved_frac, 0)} % of the surface is revolved about {t.axis_name or 'one axis'} "
        f"(Ø{f2(t.max_d)} × {f2(t.length)} mm)", "≥ 60 % revolved surface",
        "Most of the surface is coaxial cylinders, cones and end faces, so a lathe can produce it from bar stock.",
        "Consider turning as the primary process; the remaining faces are secondary operations.",
        "Geometric revolution-axis test", list(t.revolved), t.revolved_frac)]


def r_turn_slender(c: Ctx) -> list[Finding]:
    t = c.turn
    ld = t.length / t.max_d if t.max_d > 0 else 0.0
    if ld <= S.TURN["ld_chuck_only"]:
        return []
    sev = "warning" if ld > S.TURN["ld_steady_rest"] else "info"
    return [Finding(
        "TRN-02", "cnc_turning", sev, "Slender part needs support while turning",
        f"L/D = {f2(ld)} ({f2(t.length)} mm / Ø{f2(t.max_d)})",
        f"≤ {f2(S.TURN['ld_chuck_only'])} in a chuck alone; ≤ {f2(S.TURN['ld_steady_rest'])} with a tailstock",
        "Long parts deflect under cutting forces. A tailstock centre (and above about 10 × D a steady rest) keeps "
        "diameters round and straight.",
        "Allow a centre hole on one end, or plan a steady rest." if sev == "warning"
        else "Allow a centre drill on one end (or say if it is not permitted).", S.TURN_SOURCE, [], ld)]


def r_turn_shoulders(c: Ctx) -> list[Finding]:
    t = c.turn
    rev = set(t.revolved)
    edges = [e for e in c.g.edges if e.convexity == "concave" and e.kind == "circle" and len(e.faces) == 2
             and set(e.faces) <= rev]
    if not edges:
        return []
    r0, r1 = S.TURN["insert_nose_radii"]
    return [Finding(
        "TRN-03", "cnc_turning", "info", f"{len(edges)} sharp internal shoulder{'s' if len(edges) > 1 else ''}",
        f"R0 at {len(edges)} shoulder{'s' if len(edges) > 1 else ''}", f"insert nose radius R{f2(r0)}-R{f2(r1)}",
        "Turning inserts have a nose radius, so a modelled sharp internal shoulder will get a small radius.",
        f"State the maximum allowed corner radius (e.g. R{f2(r0)}), or add a relief groove if a mating part must sit "
        "against the shoulder.", S.TURN_SOURCE, sorted({i for e in edges for i in e.faces}), 0.0)]


def r_turn_secondary(c: Ctx) -> list[Finding]:
    t = c.turn
    if not t.secondary:
        return []
    n = len(t.secondary)
    return [Finding(
        "TRN-04", "cnc_turning", "info", f"{n} non-rotational face{'s' if n > 1 else ''} need a secondary operation",
        f"{n} face{'s' if n > 1 else ''} not revolved about the turning axis", "Turned faces only, or live tooling",
        "Keyways, flats and off-axis holes are milled or drilled after turning, either with live tooling on a "
        "mill-turn or in a separate milling setup.",
        "Group these features so one secondary setup covers them all.", "General turning practice",
        list(t.secondary), float(n))]


def r_turn_envelope(c: Ctx) -> list[Finding]:
    t = c.turn
    lathes = c.shop.lathes()
    if not lathes:
        return [Finding("TRN-05", "cnc_turning", "info", "No lathe in the shop profile", "—", "—",
                        "The turning envelope could not be checked.", "Add your lathes to the shop profile.",
                        "Shop profile", [], None)]
    fits = [m for m in lathes if (m.max_diameter_mm or 0) >= t.max_d - 1e-6 and (m.max_length_mm or 0)
            >= t.length - 1e-6]
    if fits:
        return []
    return [Finding(
        "TRN-05", "cnc_turning", "critical", "Part exceeds every lathe in your shop",
        f"Ø{f2(t.max_d)} × {f2(t.length)} mm",
        "; ".join(f"{m.name}: Ø{f2(m.max_diameter_mm or 0)} × {f2(m.max_length_mm or 0)}" for m in lathes),
        "The turning diameter or length exceeds the machine capacity.", "Use a larger lathe or outsource.",
        "Shop profile (lathe capacity)", [], t.max_d)]


def r_turn_bores(c: Ctx) -> list[Finding]:
    t = c.turn
    if t.axis is None or t.axis_point is None:
        return []
    out = []
    for h in c.holes:
        if abs(float(np.dot(h.axis, t.axis))) < 1 - 1e-6:
            continue
        r = h.origin - t.axis_point
        if float(np.linalg.norm(r - np.dot(r, t.axis) * t.axis)) > 1e-3:
            continue
        if h.ld > 4.0:
            out.append(Finding(
                "TRN-06", "cnc_turning", "warning", f"Deep bore Ø{f2(h.d)} × {f2(h.depth)} mm",
                f"bore depth / Ø = {f2(h.ld)}", "≤ 4 for a standard boring bar",
                "Boring bars deflect and chatter with long overhang (steel bars to about 4 × their diameter).",
                "Shorten the bore, increase its diameter, or plan a carbide or damped boring bar.",
                "General turning practice (boring bar overhang)", list(h.faces), h.ld))
    return out


# ----------------------------------------------------------------------------- sheet metal
def _sheet_applies(c: Ctx) -> bool:
    return bool(c.sheet and c.sheet.sheet_like and c.sheet.thickness and "sheet" in c.material.get("processes", []))


def _bends(c: Ctx) -> tuple[list[tuple[Any, float, Any]], list[Any]]:
    """(rounded bends as (inner face, inside radius, matching outer face or None), sharp inside bend edges)."""
    t = float(c.sheet.thickness or 0.0)  # type: ignore[union-attr]
    part = [f for f in c.g.faces if f.kind == "cylinder" and f.radius and f.axis is not None
            and f.axis_point is not None and (f.sweep or 0.0) < 2 * math.pi - 1e-3]
    inner = [f for f in part if f.concave]
    outer = [f for f in part if f.concave is False]
    bends = []
    for f in inner:
        r = float(f.radius)
        match = None
        for o in outer:
            if abs(abs(float(np.dot(o.axis, f.axis))) - 1) > 1e-6:
                continue
            d = o.axis_point - f.axis_point
            if float(np.linalg.norm(d - np.dot(d, f.axis) * f.axis)) > 1e-3 * max(1.0, t):
                continue
            if abs(float(o.radius) - (r + t)) <= 0.05 * t + 0.02:
                match = o
                break
        bends.append((f, r, match))
    sharp = [e for e in c.g.edges if e.convexity == "concave" and e.kind == "line" and e.length >= 2 * t
             and len(e.faces) == 2 and all(c.g.faces[i].kind == "plane" for i in e.faces)]
    return bends, sharp


def r_sheet_scope(c: Ctx) -> list[Finding]:
    sh = c.sheet
    t = float(sh.thickness or 0.0)  # type: ignore[union-attr]
    return [Finding(
        "SHM-00", "sheet_metal", "info", f"Screening only: {f2(t)} mm sheet, bends checked",
        f"constant {f2(t)} mm thickness over {f2(100 * sh.frac, 0)} % of the surface",  # type: ignore[union-attr]
        "—", "Inside bend radius against the material table and the formed outer radius are checked. "
        + ("The flat pattern and bend count come from the sheet-metal model (SHM-03); bend reliefs, hole-to-bend "
           "distances, grain direction and springback are not analysed." if sh.model else  # type: ignore[union-attr]
           "The flat pattern, bend reliefs, hole-to-bend distances, grain direction and springback are not analysed."),
        "Ask your fabricator to review the flat pattern before ordering.", S.BEND_SOURCE, [], t)]


def r_bend_radius(c: Ctx) -> list[Finding]:
    t = float(c.sheet.thickness or 0.0)  # type: ignore[union-attr]
    bends, sharp = _bends(c)
    items = [(r, [f.i]) for f, r, _m in bends] + [(0.0, list(e.faces)) for e in sharp]
    if not items:
        return []
    name = c.material.get("name") or "this material"
    mb = S.min_bend_radius(str(c.material.get("code")), t)
    faces = sorted({i for _r, fs in items for i in fs})
    if mb is None:
        return [Finding(
            "SHM-01", "sheet_metal", "info", f"Minimum bend radius is not tabulated for {name}",
            f"inside R{f2(min(r for r, _ in items))} at t = {f2(t)} mm", "fabricator's minimum inside radius",
            "The minimum inside radius depends on alloy, temper, thickness and grain direction.",
            "Confirm the minimum inside bend radius with your fabricator.", S.BEND_SOURCE, faces, None)]
    rmin, k = mb
    bad = [(r, fs) for r, fs in items if r < rmin - 1e-6]
    if not bad:
        return []
    r = min(r for r, _ in bad)
    n = len(bad)
    return [Finding(
        "SHM-01", "sheet_metal", "critical", f"Inside bend radius R{f2(r)} is below the minimum for {name}",
        f"R{f2(r)} inside ({n} bend{'s' if n > 1 else ''}, t = {f2(t)} mm)",
        f"≥ R{f2(rmin)} ({f2(k, 1)} × t for {name} at {f2(t)} mm; verify)",
        "Bending tighter than the alloy's minimum inside radius stretches the outer fibres past their limit and "
        "cracks the outside of the bend. Hard tempers such as 6061-T6 are the most sensitive.",
        f"Increase the inside bend radius to at least R{f2(rmin)}, bend in a softer temper and heat-treat afterwards, "
        "or machine the part instead of bending it.", S.BEND_SOURCE, sorted({i for _r, fs in bad for i in fs}), r,
        target={"kind": "radius", "to": S.nice_up(rmin), "why": f"≥ R{f2(rmin)} to bend {name}"})]


def r_bend_outer(c: Ctx) -> list[Finding]:
    t = float(c.sheet.thickness or 0.0)  # type: ignore[union-attr]
    bends, _sharp = _bends(c)
    missing = [(f, r) for f, r, m in bends if m is None]
    if not missing:
        return []
    r = min(r for _f, r in missing)
    n = len(missing)
    return [Finding(
        "SHM-02", "sheet_metal", "critical", f"{n} bend{'s' if n > 1 else ''} without an outer radius",
        f"inside R{f2(r)}, outside corner sharp", f"outside radius = inside radius + t = R{f2(r + t)}",
        "A formed bend keeps the sheet thickness constant round the corner, so its outside radius is the inside "
        "radius plus the thickness. A rounded inside with a sharp outside is a machined or welded shape, not a bend.",
        f"Model the bend with an outside radius of R{f2(r + t)} (inside R{f2(r)} + {f2(t)} mm), or plan the part as "
        "machined.", "Sheet-metal geometry (constant thickness through a bend)", [f.i for f, _r in missing], r)]


def _model_applies(c: Ctx) -> bool:
    return bool(c.sheet_model and c.sheet_model.get("flat"))


MIN_FLANGE_T = 4.0  # flange at least 4 × thickness long (common press-brake practice: the die opening)


def r_flat_pattern(c: Ctx) -> list[Finding]:
    sm = c.sheet_model or {}
    fl = sm["flat"]
    t = float(sm["thickness"])
    n = int(sm.get("bend_count") or 0)
    return [Finding(
        "SHM-03", "sheet_metal", "info", f"Flat pattern {f2(fl['size'][0])} × {f2(fl['size'][1])} mm, {n} bend{'s' if n != 1 else ''}",
        f"{f2(t)} mm sheet, K = {f2(float(sm['k_factor']), 3)}, blank area {f2(float(fl['area_mm2']), 0)} mm², "
        f"cut length {f2(float(fl['perimeter_mm']), 0)} mm", "—",
        "The flat pattern is developed from the sheet-metal model with bend allowance BA = angle × (R + K × T). The "
        "real allowance depends on the press brake, tooling and material, so the flat size is as good as the K-factor.",
        "Send the flat-pattern DXF with the K-factor to your fabricator and ask them to confirm it.",
        "Sheet-metal model (bend allowance from the K-factor)", [], float(n))]


def r_flange_length(c: Ctx) -> list[Finding]:
    sm = c.sheet_model or {}
    t = float(sm["thickness"])
    lim = MIN_FLANGE_T * t
    short = []
    for b in sm.get("bends") or []:
        if b.get("kind") == "hem":
            continue
        ln = b.get("outer_length") if b.get("outer_length") is not None else b.get("straight")
        if ln is not None and float(ln) < lim - 1e-9:
            short.append((b, float(ln)))
    if not short:
        return []
    worst = min(ln for _b, ln in short)
    names = ", ".join(f"B{b['n']} {b['name']} ({f2(ln)} mm)" for b, ln in short[:4])
    return [Finding(
        "SHM-04", "sheet_metal", "warning", f"{len(short)} flange{'s' if len(short) > 1 else ''} shorter than "
        f"{f2(MIN_FLANGE_T, 0)} × the thickness", names, f"≥ {f2(lim)} mm ({f2(MIN_FLANGE_T, 0)} × T)",
        "A flange has to rest on both shoulders of the press-brake die while it bends; flanges shorter than about "
        "four thicknesses slip into the die and come out short or twisted.",
        f"Lengthen the flange to at least {f2(lim)} mm, or ask your fabricator about their minimum for this tooling.",
        "Common press-brake practice (die opening about 6–8 × T)", [], worst,
        target={"kind": "length", "to": S.nice_up(lim), "why": f"≥ {f2(lim)} mm flange"})]


def r_radius_vs_thickness(c: Ctx) -> list[Finding]:
    sm = c.sheet_model or {}
    t = float(sm["thickness"])
    tight = [b for b in sm.get("bends") or [] if b.get("kind") != "hem" and float(b["radius"]) < t - 1e-9]
    if not tight:
        return []
    r = min(float(b["radius"]) for b in tight)
    return [Finding(
        "SHM-05", "sheet_metal", "warning", f"Inside bend radius R{f2(r)} is below the sheet thickness",
        f"{len(tight)} bend{'s' if len(tight) > 1 else ''} with R < T ({f2(t)} mm)", f"inside radius ≥ T = R{f2(t)}",
        "An inside radius below the thickness strains the outside of the bend hard: many alloys and tempers crack, "
        "and the bend allowance becomes less predictable.",
        f"Use an inside radius of at least R{f2(t)} unless your fabricator confirms a tighter one for this material.",
        "Rule of thumb for formed sheet (R ≥ T)", [], r,
        target={"kind": "radius", "to": S.nice_up(t), "why": f"≥ R{f2(t)} (the thickness)"})]


# ----------------------------------------------------------------------------- moulding / casting
def _pull_vec(c: Ctx) -> np.ndarray:
    return {"Z": np.array([0.0, 0.0, 1.0]), "X": np.array([1.0, 0.0, 0.0]), "Y": np.array([0.0, 1.0, 0.0])}[c.pull or "Z"]


def r_mould_scope(c: Ctx) -> list[Finding]:
    return [Finding(
        "MLD-00", "moulding_casting", "info", f"Screening only: two-part mould pulled along ±{c.pull}",
        f"pull direction ±{c.pull} (fewest undercut faces)", "—",
        "Only draft, undercuts and wall thickness are checked. Parting line, gates, shrinkage, cooling and flow are "
        "not analysed.", "Ask your moulder or foundry to review before tooling.", S.MOULD_SOURCE, [], None)]


def r_draft(c: Ctx) -> list[Finding]:
    d = _pull_vec(c)
    lim = math.sin(math.radians(c.shop.min_draft_deg))
    faces, worst = [], 90.0
    for f in c.g.faces:
        if not f.samples:
            continue
        m = sum(abs(float(np.dot(s.n, d))) * s.w for s in f.samples) / sum(s.w for s in f.samples)
        if m < lim - 1e-9:
            faces.append(f.i)
            worst = min(worst, math.degrees(math.asin(min(1.0, m))))
    if not faces:
        return []
    return [Finding(
        "MLD-01", "moulding_casting", "warning", f"{len(faces)} face{'s' if len(faces) > 1 else ''} without draft",
        f"draft {f2(worst, 1)}° relative to ±{c.pull}", f"≥ {f2(c.shop.min_draft_deg, 1)}° (1-2° typical)",
        "Walls parallel to the pull direction drag on the mould or pattern, which damages the surface and the tool.",
        f"Add at least {f2(c.shop.min_draft_deg, 1)}° draft to these walls (more on textured faces).",
        S.MOULD_SOURCE, faces, worst)]


def r_mould_undercut(c: Ctx) -> list[Finding]:
    a = c.mould_acc
    if a is None:
        return []
    names = (f"+{c.pull}", f"-{c.pull}")
    pair = set(names)
    faces = [f.i for f in c.g.faces if f.samples and f.area > 0
             and sum(s.w for k, s in enumerate(f.samples) if a.sample_dirs[f.i][k] & pair) / f.area < F.COVER]
    if not faces:
        return []
    return [Finding(
        "MLD-02", "moulding_casting", "warning", f"{len(faces)} undercut face{'s' if len(faces) > 1 else ''} for a "
        "two-part mould", f"{len(faces)} face{'s' if len(faces) > 1 else ''} hidden from +{c.pull} and -{c.pull}",
        "Every face visible from one of the two mould halves",
        "Faces shadowed in both pull directions (side holes, undercuts) need side actions, cores or lifters, which "
        "raise tooling cost.", "Reorient these features along the pull direction, or accept side actions.",
        "Geometric visibility test along the pull direction", faces, float(len(faces)))]


def r_mould_walls(c: Ctx) -> list[Finding]:
    walls = sorted(t.t for t in c.thick if t.wall)
    if not walls or c.metal:  # solid metal parts: ray thickness isn't a casting wall measure, so stay silent
        return []
    p90 = walls[min(len(walls) - 1, int(0.9 * len(walls)))]
    p10 = walls[int(0.1 * len(walls))]
    out = []
    if p90 > S.MOULD["max_wall_plastic"]:
        thick = sorted({t.face for t in c.thick if t.wall and t.t > S.MOULD["max_wall_plastic"]})
        out.append(Finding(
            "MLD-03", "moulding_casting", "warning", f"Thick sections for moulding ({f2(p90, 1)} mm)",
            f"90th-percentile wall {f2(p90, 1)} mm", f"≤ {f2(S.MOULD['max_wall_plastic'])} mm typical for "
            "thermoplastics", "Thick plastic sections shrink unevenly (sink marks, voids) and lengthen cooling time.",
            "Core out thick regions to a uniform wall (often 2-3 mm) with ribs for stiffness.", S.MOULD_SOURCE,
            thick, p90))
    if p10 > 0 and p90 / p10 > S.MOULD["wall_ratio"]:
        out.append(Finding(
            "MLD-04", "moulding_casting", "info", "Non-uniform wall thickness",
            f"walls {f2(p10, 1)}-{f2(p90, 1)} mm (ratio {f2(p90 / p10, 1)})", f"ratio ≤ {f2(S.MOULD['wall_ratio'])}",
            "Large wall-thickness changes cool at different rates, which causes warp and sink in moulded and cast "
            "parts.", "Even out the walls or blend thickness changes gradually.", S.MOULD_SOURCE, [], p90 / p10))
    return out


RULES: list[Rule] = [
    Rule("DFM-CNC-01", "Internal corner radius vs smallest tool and cavity depth", "cnc_milling", r_corner_radius),
    Rule("DFM-CNC-02", "Sharp internal corners", "cnc_milling", r_sharp_internal),
    Rule("DFM-CNC-03", "Internal radii away from pocket floors", "cnc_milling", r_blend),
    Rule("DFM-CNC-04", "Deep or narrow cavities", "cnc_milling", r_cavity),
    Rule("DFM-CNC-05", "Minimum wall thickness", "cnc_milling", r_thin_wall),
    Rule("DFM-CNC-06", "Undercuts (unreachable faces)", "cnc_milling", r_undercut),
    Rule("DFM-CNC-07", "Setup count", "cnc_milling", r_setups),
    Rule("DFM-CNC-08", "Part envelope vs machine travel", "cnc_milling", r_envelope),
    Rule("DFM-EDGE", "External edges (acute, sharp, fillets)", "cnc_milling", r_edges),
    Rule("DFM-HOLE-01", "Hole depth / diameter", "cnc_milling", r_hole_ld),
    Rule("DFM-HOLE-02", "Standard hole diameters", "cnc_milling", r_hole_std),
    Rule("DFM-HOLE-03", "Blind hole bottoms", "cnc_milling", r_hole_bottom),
    Rule("TRN-01", "Rotational part detection", "cnc_turning", r_turn_detect, _turn_applies),
    Rule("TRN-02", "Slenderness (L/D)", "cnc_turning", r_turn_slender, _turn_applies),
    Rule("TRN-03", "Internal shoulder corners", "cnc_turning", r_turn_shoulders, _turn_applies),
    Rule("TRN-04", "Secondary (non-rotational) features", "cnc_turning", r_turn_secondary, _turn_applies),
    Rule("TRN-05", "Lathe capacity", "cnc_turning", r_turn_envelope, _turn_applies),
    Rule("TRN-06", "Bore depth", "cnc_turning", r_turn_bores, _turn_applies),
    Rule("SHM-00", "Sheet-metal screening scope", "sheet_metal", r_sheet_scope, _sheet_applies),
    Rule("SHM-01", "Minimum inside bend radius (material table)", "sheet_metal", r_bend_radius, _sheet_applies),
    Rule("SHM-02", "Formed outer radius on bends", "sheet_metal", r_bend_outer, _sheet_applies),
    Rule("SHM-03", "Flat pattern and bend count (sheet-metal model)", "sheet_metal", r_flat_pattern, _model_applies),
    Rule("SHM-04", "Minimum flange length (4 × T)", "sheet_metal", r_flange_length, _model_applies),
    Rule("SHM-05", "Inside bend radius vs thickness", "sheet_metal", r_radius_vs_thickness, _model_applies),
    Rule("MLD-00", "Moulding / casting screening scope", "moulding_casting", r_mould_scope),
    Rule("MLD-01", "Draft angle", "moulding_casting", r_draft),
    Rule("MLD-02", "Undercuts for a two-part mould", "moulding_casting", r_mould_undercut),
    Rule("MLD-03", "Wall thickness and uniformity (plastics)", "moulding_casting", r_mould_walls,
         lambda c: not c.metal),
]


def choose_pull(g: PartGeom, acc: F.Access) -> str:
    """Pull axis (Z, X or Y) with the least undercut area for a two-part mould; ties keep the earlier axis."""
    best, best_area = "Z", math.inf
    for ax in ("Z", "X", "Y"):
        pair = {f"+{ax}", f"-{ax}"}
        area = 0.0
        for f in g.faces:
            cov = sum(s.w for k, s in enumerate(f.samples) if acc.sample_dirs[f.i][k] & pair)
            if f.area > 0 and cov / f.area < F.COVER:
                area += f.area
        if area < best_area - 1e-9:
            best, best_area = ax, area
    return best


def run(c: Ctx) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(findings, CHK-13 rule summary)."""
    found: list[Finding] = []
    summary: list[dict[str, Any]] = []
    for r in RULES:
        if not r.applies(c):
            summary.append({"rule": r.id, "name": r.name, "process": r.process, "status": "not applicable",
                            "findings": 0})
            continue
        fs = r.fn(c)
        flagged = [f for f in fs if f.severity in ("critical", "warning")]
        summary.append({"rule": r.id, "name": r.name, "process": r.process,
                        "status": "flagged" if flagged else "pass", "findings": len(fs),
                        "worst": min((f.severity for f in fs), key=lambda s: SEVERITY_ORDER[s]) if fs else None})
        found += fs
    sec = set(c.turn.secondary) if c.turn.turnable else set()
    for f in found:
        if f.where is None:
            f.where = describe(c, f.faces)
        if f.process == "cnc_milling" and sec and set(f.faces) & sec:
            f.also = ["cnc_turning"]  # a milled secondary operation of the turned part
    order = {p: i for i, p in enumerate(PROCESS_LABEL)}
    found.sort(key=lambda f: (SEVERITY_ORDER[f.severity], order[f.process], f.rule))
    return [f.out(c.g, i + 1) for i, f in enumerate(found)], summary


