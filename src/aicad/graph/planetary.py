"""Planetary (epicyclic) gear sets in a design graph: recognised and made consistent by code (no model).

Founder's "Planetary Gearbox" (2026-11-20): the intent reply named a sun, three planets, a ring and a carrier, but the
ring had the planets' 30 teeth, the planet bearings were seated in the housing wall, and the connection solver had no
rule for gears that ride on bearings on pins in a carrier, so the program fell back to a master model whose layout hung
the gears on the housing. This module is the rule.

``find(graph)`` returns the set (sun, planet, ring, carrier, pins, planet bearings, input and output shafts) when the
graph reads as one: a ring gear (``internal`` true, or named ring / annulus / internal), a sun gear and a planet gear
that mesh sun / planet and planet / ring, by name (sun, planet) or by the meshes. ``normalise(graph)`` makes the set
consistent, idempotently, and says what it changed in ``graph.notes``:

* the ring is an internal gear (``internal`` true) with z_ring = z_sun + 2 z_planet (coaxial sun and ring), unless
  the brief gives it; then the planet takes z_planet = (z_ring - z_sun) / 2 when that is whole;
* the assembly condition: (z_sun + z_ring) / N planets is whole, else the sun (and the ring with it) takes the nearest
  tooth count that makes it whole, when the teeth are code's own (never the brief's);
* a stated ratio (the brief's "4:1", the sun as input, the carrier as output, the ring fixed: i = 1 + z_ring / z_sun)
  sizes the teeth when the brief gives none;
* the mounting chain: each planet on its bearing on its pin (or on its pin), each pin fixed in the carrier, the carrier
  on the output shaft, the sun on the input shaft, the ring in the housing. A planet bearing seated in the housing, or
  a gear, pin or carrier hung on the housing or its cover, is dropped (that is not how the set carries load);
* centre distances: sun / planet a = m (z_s + z_p) / 2, planet / ring a = m (z_r - z_p) / 2 (internal mesh);
* the rim rule (benchmark A1, 2026-11-21: a 6204, D 47, in a z30 m2 planet whose root is Ø55 left a 4 mm rim): the
  planet bearing is the deep-groove bearing (60xx / 62xx, ``toolbox.BEARING``) that leaves a rim
  (root Ø - bearing D) / 2 of at least ``RIM_MIN_M`` modules under the teeth, on the pin's bore when it can; when
  none fits, the planets grow (and the ring with them: z_ring = z_sun + 2 z_planet, the assembly condition kept)
  until one does. The choice and its reason are said in ``graph.notes``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from aicad.graph.model import Component, Connection, DesignGraph

_SUN = re.compile(r"\bsun\b", re.IGNORECASE)
_PLANET = re.compile(r"\bplanet", re.IGNORECASE)
_RING = re.compile(r"\bring gear|\bannulus|\binternal\b|\bring\b", re.IGNORECASE)
_CARRIER = re.compile(r"carrier|\bspider\b", re.IGNORECASE)
_PIN = re.compile(r"\bpins?\b|\baxle|spindle|\bstud\b", re.IGNORECASE)
_RATIO = re.compile(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)")
HUBS = ("keyed_hub", "hub_fit")
MIN_TEETH = 13          # the least planet / sun teeth without undercut at 20 deg (with a little margin: 17 ideal)
SUN_TEETH = 24          # code's sun when a stated ratio sizes the set
PLANET_CLEAR = 1.0      # mm between the tip circles of neighbouring planets
DEDENDUM = 1.25         # ISO 53 basic rack: dedendum 1.25 m (root Ø of an external gear m (z - 2.5))
# The least rim under the teeth of a gear that runs on a bearing in its bore, in modules. ISO 6336-3 (rim thickness
# factor Y_B = 1) and AGMA 2001-D04 (K_B = 1) put no rim penalty on tooth bending when the rim s_R is at least 1.2
# tooth depths h_t; full-depth teeth have h_t = 2.25 m, so s_R >= 1.2 x 2.25 m = 2.7 m. Within the usual 2.5 to 3 m
# rule of thumb. Verify against the standard for a real design (PD-261).
RIM_MIN_M = 2.7
RIM_SOURCE = "ISO 6336-3 / AGMA 2001-D04: rim at least 1.2 tooth depths, 1.2 x 2.25 m (verify)"
# Axial running gap between a part that turns and one that is fixed (carrier to ring end face, planets and sun to the
# housing wall, a pin's free end to the wall): at least 1 mm, and half a module on larger sets, so the faces never rub
# under axial play, tolerance stack and thermal growth. Formwright's rule (PD-269), not a standard's value.
RUN_GAP_MIN = 1.0
RUN_GAP_M = 0.5
GROW_MAX = 40           # the most teeth the rim rule adds to a planet before it gives up and says so


@dataclass
class Planetary:
    sun: str
    planet: str
    ring: str
    n: int
    carrier: str | None = None
    pin: str | None = None
    bearing: str | None = None
    input: str | None = None
    output: str | None = None
    housing: str | None = None
    meshes: list[str] = field(default_factory=list)   # connection ids: sun / planet, planet / ring

    def members(self) -> set[str]:
        return {x for x in (self.sun, self.planet, self.ring, self.carrier, self.pin, self.bearing) if x}


def _meshes(g: DesignGraph) -> list[Connection]:
    return [x for x in g.connections if x.kind == "gear_mesh"]


def _pair(x: Connection, a: str, b: str) -> bool:
    return {x.host, x.guest} == {a, b}


def is_internal(c: Component | None) -> bool:
    if c is None or c.kind != "spur_gear":
        return False
    return c.v("internal") is True or bool(_RING.search(c.name) and not _SUN.search(c.name)
                                            and not _PLANET.search(c.name))


def find(g: DesignGraph) -> Planetary | None:
    gears = g.of_kind("spur_gear")
    if len(gears) < 3:
        return None
    ms = _meshes(g)
    ring = next((c for c in gears if is_internal(c)), None)
    if ring is None:
        return None
    partners = {c.id: [x.guest if x.host == c.id else x.host for x in ms if c.id in (x.host, x.guest)] for c in gears}
    planet = next((c for c in gears if _PLANET.search(c.name) and c.id != ring.id), None) or next(
        (c for c in gears if c.id != ring.id and ring.id in partners[c.id] and len(partners[c.id]) >= 2), None)
    if planet is None:
        return None
    sun = next((c for c in gears if _SUN.search(c.name) and c.id not in (ring.id, planet.id)), None) or next(
        (g.comp(o) for o in partners[planet.id] if o not in (ring.id, planet.id)), None)
    if sun is None:
        return None
    if not any(_pair(x, sun.id, planet.id) for x in ms) or not any(_pair(x, planet.id, ring.id) for x in ms):
        return None
    ps = Planetary(sun=sun.id, planet=planet.id, ring=ring.id, n=max(1, int(planet.qty)),
                   meshes=[x.id for x in ms if _pair(x, sun.id, planet.id) or _pair(x, planet.id, ring.id)])
    comps = {c.id: c for c in g.components}

    def linked(cid: str) -> list[tuple[Connection, str]]:
        return [(x, x.guest if x.host == cid else x.host) for x in g.connections if cid in (x.host, x.guest)]

    # the carrier: named so, else the part the pins sit in
    car = next((c for c in g.components if _CARRIER.search(c.name) and c.kind not in ("spur_gear", "bearing",
                                                                                        "fastener", "key")), None)
    ps.carrier = car.id if car else None
    # the planet bearing: on a pin journal, or the bearing a planet is mounted on, or named planet bearing
    brg = next((comps[o] for x, o in linked(planet.id) if comps.get(o) is not None and comps[o].kind == "bearing"), None)
    if brg is None:
        brg = next((c for c in g.of_kind("bearing") if _PLANET.search(c.name)), None)
    ps.bearing = brg.id if brg else None
    # the pin: a shaft (or dowel) the planet or its bearing rides on, or one the carrier holds, named pin
    cands = [c for c in g.of_kind("shaft", "dowel") if _PIN.search(c.name) or _PLANET.search(c.name)]
    pin = None
    for c in cands:
        near = {o for _x, o in linked(c.id)}
        if planet.id in near or (brg is not None and brg.id in near) or (car is not None and car.id in near):
            pin = c
            break
    ps.pin = pin.id if pin else (cands[0].id if cands else None)
    for x in g.connections:
        if x.kind in HUBS and x.guest == sun.id and comps.get(x.host) and comps[x.host].kind == "shaft":
            ps.input = x.host
        if car is not None and x.kind in HUBS and x.guest == car.id and comps.get(x.host) and \
                comps[x.host].kind == "shaft":
            ps.output = x.host
    hs = g.of_kind("housing")
    ps.housing = hs[0].id if hs else None
    return ps


def _given(c: Component, k: str) -> bool:
    p = c.params.get(k)
    return p is not None and p.source in ("brief", "answer")


def _brief_ratio(brief: str) -> float | None:
    m = _RATIO.search(brief or "")
    if not m or float(m.group(1)) <= 0 or float(m.group(2)) <= 0:
        return None
    r = max(float(m.group(1)), float(m.group(2))) / min(float(m.group(1)), float(m.group(2)))
    return r if 2.5 <= r <= 12 else None


def ring_teeth(z_sun: int, z_planet: int) -> int:
    return int(z_sun) + 2 * int(z_planet)


def centre_distance(m: float, z_a: int, z_b: int, internal: bool) -> float:
    """External pair a = m (z1 + z2) / 2; a planet in its ring a = m (z_ring - z_planet) / 2."""
    return float(m) * (abs(int(z_a) - int(z_b)) if internal else int(z_a) + int(z_b)) / 2


def running_gap(m: float) -> float:
    """The axial running gap between a turning part and a fixed one: max(1 mm, 0.5 m)."""
    return max(RUN_GAP_MIN, RUN_GAP_M * float(m))


def root_d(m: float, z: int) -> float:
    """Root Ø of an external gear: d_f = m (z - 2 x 1.25) (ISO 53 basic rack)."""
    return float(m) * (int(z) - 2 * DEDENDUM)


def rim(m: float, z: int, D: float) -> float:
    """The rim under the teeth of a gear with a bore of Ø D: (root Ø - D) / 2."""
    return (root_d(m, z) - float(D)) / 2


def planet_bearing(m: float, zp: int, pin_d: float | None = None, pin_fixed: bool = False) -> int | None:
    """The planet bearing the rim rule allows: a 60xx / 62xx (``toolbox.BEARING``) whose outer Ø leaves at least
    ``RIM_MIN_M`` m under the planet's root. The pin's bore first (nothing else changes), then the largest bore (the
    stiffest pin), then the larger bearing (capacity). ``pin_fixed``: the brief fixes the pin Ø, so only that bore.
    None when none fits."""
    from aicad.toolbox import BEARING

    dmax = root_d(m, zp) - 2 * RIM_MIN_M * float(m)
    fit = [k for k, (_d, D, _b) in BEARING.items() if D <= dmax + 1e-9]
    if pin_fixed and pin_d is not None:
        fit = [k for k in fit if abs(BEARING[k][0] - float(pin_d)) < 1e-9]
    if not fit:
        return None
    on_pin = (lambda k: pin_d is not None and abs(BEARING[k][0] - float(pin_d)) < 1e-9)
    return max(fit, key=lambda k: (on_pin(k), BEARING[k][0], BEARING[k][1], BEARING[k][2]))


def _rim_words(m: float, zp: int, des: int, D: float) -> str:
    s = rim(m, zp, D)
    return (f"rim (Ø{root_d(m, zp):g} root - Ø{D:g}) / 2 = {s:g} mm = {s / float(m):.3g} m under the planet teeth, "
            f"at least {RIM_MIN_M:g} m ({RIM_SOURCE})")


def _planets_touch(m: float, zs: int, zp: int, n: int) -> bool:
    a = float(m) * (zs + zp) / 2
    return n > 1 and 2 * a * math.sin(math.pi / n) < float(m) * (zp + 2) + PLANET_CLEAR


def _teeth_for_ratio(r: float, n: int) -> tuple[int, int, int] | None:
    best = None
    for zs in range(SUN_TEETH - 6, SUN_TEETH + 7):
        for zr in range(round((r - 1) * zs) - 3, round((r - 1) * zs) + 4):
            if (zr - zs) % 2 or (zr - zs) // 2 < MIN_TEETH or (zs + zr) % n:
                continue
            err = abs(1 + zr / zs - r)
            key = (round(err, 6), abs(zs - SUN_TEETH))
            if best is None or key < best[0]:
                best = (key, (zs, (zr - zs) // 2, zr))
    return best[1] if best else None


def _rim_rule(g: DesignGraph, ps: Planetary, sun: Component, planet: Component, ring: Component, m: float,
              zs: int, zp: int, notes: list[str]) -> int:
    """The planet bearing that leaves the rim ``RIM_MIN_M`` m under the planet teeth (module docstring). Returns the
    planet's teeth (grown when no bearing fits the planet as it is)."""
    from aicad.toolbox import BEARING

    brg = g.comp(ps.bearing) if ps.bearing else None
    if brg is None:
        return zp
    pin = g.comp(ps.pin) if ps.pin else None
    pin_d = float(pin.v("d")) if pin is not None and pin.v("d") is not None else None
    pin_fixed = pin is not None and _given(pin, "d")
    cur = brg.v("designation")
    cur = int(cur) if isinstance(cur, int | float) and int(cur) in BEARING else None
    if cur is not None and rim(m, zp, BEARING[cur][1]) >= RIM_MIN_M * m - 1e-9 and (
            pin_d is None or abs(BEARING[cur][0] - pin_d) < 1e-9 or not pin_fixed):
        notes.append(f"{brg.name} {cur}: {_rim_words(m, zp, cur, BEARING[cur][1])}.")
        return zp
    if cur is not None and (_given(brg, "designation") or _given(brg, "D")):
        notes.append(f"Check: {brg.name} {cur} (OD {BEARING[cur][1]:g}) leaves a rim of "
                     f"{rim(m, zp, BEARING[cur][1]):g} mm = {rim(m, zp, BEARING[cur][1]) / m:.3g} m under the teeth of "
                     f"{planet.name} (root Ø{root_d(m, zp):g}), less than {RIM_MIN_M:g} m ({RIM_SOURCE}); the brief's "
                     "bearing is kept.")
        return zp
    was = (f"{cur} (OD {BEARING[cur][1]:g}) left a rim of {rim(m, zp, BEARING[cur][1]):g} mm = "
           f"{rim(m, zp, BEARING[cur][1]) / m:.3g} m under the planet's Ø{root_d(m, zp):g} root, less than "
           f"{RIM_MIN_M:g} m" if cur is not None else "no bearing was sized yet")
    des = planet_bearing(m, zp, pin_d, pin_fixed)
    teeth_free = not any(_given(c, "teeth") for c in (sun, planet, ring))
    if des is None and teeth_free:
        for z in range(zp + 1, zp + GROW_MAX + 1):
            if (2 * zs + 2 * z) % ps.n or _planets_touch(m, zs, z, ps.n):
                continue
            des = planet_bearing(m, z, pin_d, pin_fixed)
            if des is not None:
                why = f"the rim rule: no 60xx / 62xx bearing fits a {zp}-tooth planet with {RIM_MIN_M:g} m of rim"
                planet.set("teeth", z, "rule", why, force=True)
                ring.set("teeth", ring_teeth(zs, z), "rule", "z_ring = z_sun + 2 z_planet", force=True)
                notes.append(f"{planet.name}: {z} teeth (was {zp}) and {ring.name} {ring_teeth(zs, z)} (z_ring = z_sun"
                             f" + 2 z_planet), because {was} and no 60xx / 62xx bearing fits a {zp}-tooth planet with "
                             f"{RIM_MIN_M:g} m of rim. (z_sun + z_ring) / {ps.n} = {(2 * zs + 2 * z) // ps.n} stays "
                             f"whole; the ratio is now 1 + {ring_teeth(zs, z)} / {zs} = "
                             f"{1 + ring_teeth(zs, z) / zs:.3g}.")
                zp = z
                break
    if des is None:
        notes.append(f"Check: no 60xx / 62xx bearing leaves {RIM_MIN_M:g} m of rim under the teeth of {planet.name} "
                     f"(root Ø{root_d(m, zp):g}): a needle bearing, a plain bush or larger planets (verify).")
        return zp
    bd, bD, bB = BEARING[des]
    reason = f"the rim rule: {_rim_words(m, zp, des, bD)}"
    brg.set("designation", des, "rule", reason[:300], force=True)
    for k, v in (("d", bd), ("D", bD), ("B", bB)):
        brg.set(k, float(v), "standard", f"ISO 15 {des}", force=True)
    if pin is not None and (pin_d is None or abs(pin_d - bd) > 1e-9):
        pin.set("d", float(bd), "rule", f"the bore of its {des} planet bearing", force=True)
    if pin is not None:
        pin.set("journal_d", float(bd), "standard", f"the bore of the {des}", force=True)
    if cur != des:
        notes.append(f"{brg.name}: {des} (Ø{bd:g} x Ø{bD:g} x {bB:g}) instead, because {was}"
                     + (f"; the pin is Ø{bd:g} to suit" if pin is not None and pin_d is not None and
                        abs(pin_d - bd) > 1e-9 else "") + ".")
    notes.append(f"{brg.name} {des}: {_rim_words(m, zp, des, bD)}.")
    return zp


def normalise(graph: DesignGraph) -> DesignGraph:
    """The graph with its planetary set made consistent (see the module docstring). Unchanged without one."""
    ps = find(graph)
    if ps is None:
        return graph
    g = graph
    notes: list[str] = []
    sun, planet, ring = g.comp(ps.sun), g.comp(ps.planet), g.comp(ps.ring)
    assert sun is not None and planet is not None and ring is not None
    m = sun.v("module") or planet.v("module") or ring.v("module")
    if m is not None:
        for c in (sun, planet, ring):
            if c.v("module") is None or (not _given(c, "module") and abs(float(c.v("module")) - float(m)) > 1e-9):
                c.set("module", float(m), "rule", "the gears of a planetary set share their module", force=True)
    if ring.v("internal") is not True:
        ring.set("internal", True, "rule", "the ring of a planetary set: internal teeth", force=True)
        notes.append(f"{ring.name} is the internal ring gear of the planetary set.")
    r = _brief_ratio(g.brief)
    if r and not any(_given(c, "teeth") for c in (sun, planet, ring)):
        t = _teeth_for_ratio(r, ps.n)
        if t and (sun.v("teeth"), planet.v("teeth"), ring.v("teeth")) != t:
            for c, z in zip((sun, planet, ring), t, strict=True):
                c.set("teeth", int(z), "rule", f"planetary ratio 1 + z_ring / z_sun = {1 + t[2] / t[0]:.3g} for "
                      f"the stated {r:g}:1", force=True)
            notes.append(f"Teeth from the stated ratio {r:g}:1 (sun input, carrier output, ring fixed): sun {t[0]}, "
                         f"planets {t[1]}, ring {t[2]} (i = 1 + {t[2]} / {t[0]} = {1 + t[2] / t[0]:.3g}).")
    zs, zp = sun.v("teeth"), planet.v("teeth")
    if zs is not None and zp is not None:
        zs, zp = int(zs), int(zp)
        zr = ring.v("teeth")
        if _given(ring, "teeth") and not _given(planet, "teeth") and zr is not None and (int(zr) - zs) % 2 == 0 \
                and (int(zr) - zs) // 2 >= MIN_TEETH:
            if zp != (int(zr) - zs) // 2:
                zp = (int(zr) - zs) // 2
                planet.set("teeth", zp, "rule", "z_planet = (z_ring - z_sun) / 2 (coaxial sun and ring)", force=True)
                notes.append(f"{planet.name}: {zp} teeth so it fits between the sun and the ring.")
        elif not _given(ring, "teeth") and zr != ring_teeth(zs, zp):
            ring.set("teeth", ring_teeth(zs, zp), "rule", "z_ring = z_sun + 2 z_planet (coaxial sun and ring)",
                     force=True)
            notes.append(f"{ring.name}: {ring_teeth(zs, zp)} internal teeth (z_ring = z_sun + 2 z_planet = {zs} + 2 x "
                         f"{zp}), so the sun and the ring are coaxial.")
        zr = int(ring.v("teeth"))
        if (zs + zr) % ps.n and not any(_given(c, "teeth") for c in (sun, planet, ring)):
            for dz in (1, -1, 2, -2, 3, -3):
                if zs + dz >= MIN_TEETH and (2 * (zs + dz) + 2 * zp) % ps.n == 0:
                    zs += dz
                    sun.set("teeth", zs, "rule", f"(z_sun + z_ring) / {ps.n} planets must be whole", force=True)
                    ring.set("teeth", ring_teeth(zs, zp), "rule", "z_ring = z_sun + 2 z_planet", force=True)
                    notes.append(f"Sun {zs} and ring {ring_teeth(zs, zp)} teeth, so {ps.n} equally spaced planets "
                                 "can be assembled ((z_sun + z_ring) / N whole).")
                    break
        zr = int(ring.v("teeth"))
        if (zs + zr) % ps.n:
            notes.append(f"Check: (z_sun + z_ring) / {ps.n} = {(zs + zr) / ps.n:g} is not whole, so {ps.n} equally "
                         "spaced planets can't all mesh; the brief's teeth are kept.")
        if m is not None:
            zp = _rim_rule(g, ps, sun, planet, ring, float(m), zs, zp, notes)
        if m is not None and ps.n > 1:
            a = float(m) * (zs + zp) / 2
            if 2 * a * math.sin(math.pi / ps.n) < float(m) * (zp + 2) + PLANET_CLEAR:
                notes.append(f"Check: {ps.n} planets of {zp} teeth on a = {a:g} mm touch each other (tip circles "
                             "overlap): use fewer planets or a larger sun.")
    # the planet's bore is its bearing's outer ring (or the pin)
    brg = g.comp(ps.bearing) if ps.bearing else None
    pin = g.comp(ps.pin) if ps.pin else None
    if brg is not None and brg.v("D") is not None:
        planet.set("bore", float(brg.v("D")), "rule", "the outer ring of its bearing", force=True)
    elif pin is not None and pin.v("d") is not None:
        planet.set("bore", float(pin.v("d")), "rule", "running on its pin", force=True)
    # the mounting chain
    shells = {c.id for c in g.components if c.kind in ("housing", "cover")}
    turning = {ps.sun, ps.planet, ps.pin, ps.carrier, ps.bearing} - {None}

    def wrong_host(x: Connection) -> bool:
        if x.kind == "bearing_seat":  # a planet bearing in the housing wall
            return bool(ps.bearing) and x.guest == ps.bearing and x.host in shells
        if x.kind not in ("mounted_on", "bolted_joint"):
            return False
        return (x.host in shells and x.guest in turning) or (x.guest in shells and x.host in turning)

    drop = [x for x in g.connections if wrong_host(x)]
    for x in drop:
        g.connections.remove(x)
        h, gu = g.comp(x.host), g.comp(x.guest)
        notes.append(f"{gu.name if gu else x.guest} is not carried by {h.name if h else x.host} in a planetary set: "
                     "that joint is left out (it runs on its own axis in the set).")

    def has(kind: str | tuple[str, ...], host: str | None, guest: str | None) -> bool:
        kinds = (kind,) if isinstance(kind, str) else kind
        return any(x.kind in kinds and x.host == host and x.guest == guest for x in g.connections)

    def add(kind: str, host: str, guest: str, words: str) -> None:
        g.connections.append(Connection(id=g.next_connection_id(), kind=kind, host=host, guest=guest))
        notes.append(words)

    if brg is not None and pin is not None and not has("bearing_journal", pin.id, brg.id):
        add("bearing_journal", pin.id, brg.id, f"{brg.name}: one on each {pin.name}.")
    for x in g.connections:
        if x.kind == "bearing_journal" and pin is not None and brg is not None and x.host == pin.id and \
                x.guest == brg.id and x.v("count") != 1:
            from aicad.graph.model import Param

            x.params["count"] = Param(value=1, source="rule", note="one bearing per planet")
    if brg is not None and not has(("mounted_on",), brg.id, planet.id):
        add("mounted_on", brg.id, planet.id, f"{planet.name} runs on its {brg.name}.")
    elif brg is None and pin is not None and not has(HUBS + ("mounted_on",), pin.id, planet.id):
        add("hub_fit", pin.id, planet.id, f"{planet.name} runs on its {pin.name}.")
    car = g.comp(ps.carrier) if ps.carrier else None
    if car is not None and pin is not None and not any(x.host == car.id and x.guest == pin.id for x in g.connections):
        add("mounted_on", car.id, pin.id, f"Each {pin.name} is fixed in the {car.name}.")
    if ps.housing and not any(x.guest == ring.id and x.host == ps.housing for x in g.connections):
        hs = g.comp(ps.housing)
        add("mounted_on", ps.housing, ring.id, f"{ring.name} is fixed in the {hs.name if hs else 'housing'}.")
    # bearing caps sit over the end walls' bearing seats, which are all in the housing in a planetary set (the cover
    # is the lid on top): a cap the model bolted to the cover goes on the housing (benchmark A4, 2026-11-21: the
    # output cap on the cover was reached by no connection, so the fast layout gave way to a master model)
    if ps.housing:
        hs = g.comp(ps.housing)
        covers = {c.id for c in g.components if c.kind == "cover"}
        seats_in_cover = any(x.kind == "bearing_seat" and x.host in covers for x in g.connections)
        for x in g.connections:
            gu = g.comp(x.guest)
            if x.kind == "bolted_joint" and x.host in covers and gu is not None and gu.kind == "bearing_cap" \
                    and not seats_in_cover:
                x.host = ps.housing
                notes.append(f"{gu.name} is bolted to the {hs.name if hs else 'housing'}'s end wall, over its "
                             "bearing seat (the shaft bearings sit in the housing walls; the cover is the lid).")
    # a coaxial set has one end wall per shaft, where it leaves the housing, so each shaft gets one open cap; blind
    # caps (a parallel-shaft gearbox's far side) have no seat to cover (benchmark A6, 2026-11-21: an open and a blind
    # cap per shaft, the blind ones reached by no connection, so the fast layout gave way to a master model)
    caps = [c for c in g.components if c.kind == "bearing_cap"]
    blind = [c for c in caps if str(c.v("style") or "").lower() == "blind" or (
        not c.v("style") and "blind" in c.name.lower())]
    if blind and len(caps) - len(blind) >= 1:
        gone = {c.id for c in blind}
        screws: dict[str, list[int]] = {}  # fastener id -> [cap joints before, cap joints kept]
        for x in g.connections:
            if x.kind == "bolted_joint" and g.comp(x.guest) is not None and g.comp(x.guest).kind == "bearing_cap":
                for v in x.via:
                    s = screws.setdefault(v, [0, 0])
                    s[0] += 1
                    s[1] += x.guest not in gone
        g.connections = [x for x in g.connections if x.guest not in gone and x.host not in gone]
        g.components = [c for c in g.components if c.id not in gone]
        for v, (before, kept) in screws.items():
            f = g.comp(v)
            if f is not None and before and kept and not any(x.kind != "bolted_joint" or (
                    g.comp(x.guest) is not None and g.comp(x.guest).kind != "bearing_cap")
                    for x in g.connections if v in x.via):
                f.qty = max(1, round(f.qty * kept / before))
        notes.append(f"{', '.join(c.name for c in blind)}: left out. In a planetary set each shaft leaves the housing "
                     "through its own end wall, so each has one open cap and there is no far-side seat to close.")
    if pin is not None and pin.kind == "shaft":
        pin.set("role", "intermediate", "rule", "a planet pin")
    # centre distances (the internal mesh by the difference)
    from aicad.graph.model import Param

    for x in g.connections:
        if x.kind != "gear_mesh" or x.id not in ps.meshes:
            continue
        a, b = g.comp(x.host), g.comp(x.guest)
        if a is None or b is None or a.v("teeth") is None or b.v("teeth") is None or a.v("module") is None:
            continue
        internal = ring.id in (a.id, b.id)
        cd = centre_distance(float(a.v("module")), int(a.v("teeth")), int(b.v("teeth")), internal)
        x.params["centre_distance"] = Param(value=cd, source="rule", note="a = m (z_ring - z_planet) / 2 (internal)"
                                            if internal else "a = m (z1 + z2) / 2")
        x.params["ratio"] = Param(value=round(int(b.v("teeth")) / int(a.v("teeth")), 4), source="rule", note="z2 / z1")
    for n in notes:
        if n not in g.notes:
            g.notes.append(n)
    return g
