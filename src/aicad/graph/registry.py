"""The registries: what kinds of component and connection a design graph may hold, and what each one means.

A **component type** names its parameters (unit, limits, required or defaulted), the Design Office family that makes
it, the Toolbox component when it is bought out, and the scope kind the brief's exclusions talk about.

A **connection type** is the semantics of a joint: which side is the host (the side that carries), which kinds may
sit on each side, which part makes the joint (``via``: a key, fasteners, a ring), which features it implies on each
side (keyseat, bore, journal, groove, hole pattern), the placement rule it implies, the standards that size it, and
the ICD interface kinds it compiles to. Code reads these; the intent prompt is generated from them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aicad.toolbox import BEARING


@dataclass(frozen=True)
class ParamSpec:
    unit: str = "mm"
    lo: float | None = None
    hi: float | None = None
    integer: bool = False
    choices: tuple[Any, ...] = ()
    label: str = ""


@dataclass(frozen=True)
class ComponentType:
    kind: str
    label: str
    family: str                 # Design Office family: turned | gear | machined | sheet | plastic | standard
    scope: str | None           # office/scope.py kind (exclusions are read in these words)
    params: dict[str, ParamSpec] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    toolbox: str | None = None  # Toolbox component code when bought out
    standard: str = ""
    complexity: int = 2
    rotates: bool = False       # sits on a shaft axis (shaft, gear, hub, bearing, ring, spacer)


@dataclass(frozen=True)
class ConnectionType:
    kind: str
    label: str
    hosts: tuple[str, ...]
    guests: tuple[str, ...]
    via: tuple[str, ...] = ()           # kinds of the parts that make the joint
    via_required: bool = False          # code adds one (sized from standards) when the graph has none
    host_features: tuple[str, ...] = ()
    guest_features: tuple[str, ...] = ()
    placement: str = ""
    standards: tuple[str, ...] = ()
    icd: tuple[str, ...] = ()           # the ICD interface kinds it compiles to (``office.icd.KIND_LABEL``)
    params: dict[str, ParamSpec] = field(default_factory=dict)
    axial: bool = False                 # locates the guest along the host's axis (not radially)


MM = ParamSpec()
_D = ParamSpec(lo=3, hi=500, label="diameter")
_L = ParamSpec(lo=1, hi=5000, label="length")

ROTATING_HUBS = ("spur_gear", "pulley", "hub", "spacer")

COMPONENTS: dict[str, ComponentType] = {c.kind: c for c in [
    ComponentType("shaft", "Shaft", "turned", "shaft", {
        "d": ParamSpec(lo=3, hi=300, label="seat Ø (the Ø its hubs sit on)"),
        "shoulder_d": ParamSpec(lo=4, hi=400, label="larger step Ø behind the seat (a stepped shaft)"),
        "journal_d": ParamSpec(lo=3, hi=300, label="bearing journal Ø"),
        "length": _L, "stepped": ParamSpec(unit="", choices=(True, False), label="stepped"),
        "role": ParamSpec(unit="", choices=("input", "output", "intermediate", ""), label="input / output")},
        complexity=2, rotates=True),
    ComponentType("spur_gear", "Spur gear", "gear", "gear", {
        "module": ParamSpec(lo=0.3, hi=20, label="module m"),
        "teeth": ParamSpec(unit="", lo=8, hi=300, integer=True, label="teeth z"),
        "face_width": ParamSpec(lo=1, hi=500, label="face width b"),
        "bore": _D, "pressure_angle": ParamSpec(unit="deg", lo=14.5, hi=25, label="pressure angle"),
        "role": ParamSpec(unit="", choices=("pinion", "wheel", ""), label="pinion / wheel"),
        "internal": ParamSpec(unit="", choices=(True, False), label="internal teeth (a ring gear)")},
        required=("module", "teeth"), complexity=2, rotates=True, standard="ISO 53 profile, 20 deg"),
    ComponentType("key", "Parallel key", "standard", "key", {
        "shaft_d": _D, "b": MM, "h": MM, "t1": MM, "t2": MM, "length": _L},
        toolbox="parallel_key", standard="DIN 6885-1 form A", complexity=1),
    ComponentType("bearing", "Deep-groove ball bearing", "standard", "bearing", {
        "designation": ParamSpec(unit="", integer=True, choices=tuple(sorted(BEARING))),
        "series": ParamSpec(unit="", choices=("62", "60")), "d": MM, "D": MM, "B": MM},
        toolbox="bearing", standard="ISO 15", complexity=1, rotates=True),
    ComponentType("retaining_ring", "Retaining ring", "standard", "ring", {
        "shaft_d": _D, "d2": MM, "m": MM, "s": MM},
        toolbox="retaining_ring", standard="DIN 471", complexity=1, rotates=True),
    ComponentType("spacer", "Spacer", "turned", "spacer", {"bore": _D, "od": _D, "length": _L},
                  complexity=1, rotates=True),
    ComponentType("pulley", "Pulley", "turned", "pulley", {"od": _D, "width": _L, "bore": _D},
                  complexity=2, rotates=True),
    ComponentType("hub", "Hub", "turned", "hub", {"od": _D, "width": _L, "bore": _D}, complexity=2, rotates=True),
    ComponentType("housing", "Housing", "machined", "housing", {
        "style": ParamSpec(unit="", choices=("split", "block")), "L": _L, "W": _L, "H": _L},
        complexity=4),
    ComponentType("cover", "Housing cover", "machined", "cap", {"L": _L, "W": _L, "H": _L}, complexity=3),
    ComponentType("bearing_cap", "Bearing cap", "turned", "cap", {
        "style": ParamSpec(unit="", choices=("open", "blind")), "seat_D": _D}, complexity=2),
    ComponentType("plate", "Plate", "machined", "plate", {"L": _L, "W": _L, "T": _L}, complexity=2),
    ComponentType("bracket", "Bracket", "machined", "support", {"L": _L, "W": _L, "H": _L}, complexity=2),
    ComponentType("pillow_block", "Pillow block", "machined", "support", {
        "L": _L, "W": _L, "H": _L, "centre_height": ParamSpec(lo=5, hi=2000, label="shaft centre height")},
        complexity=2),
    ComponentType("motor", "Motor (bought out: envelope only)", "machined", "motor", {
        "L": _L, "W": _L, "H": _L, "shaft_d": _D, "shaft_length": _L}, complexity=1),
    ComponentType("coupling", "Shaft coupling", "turned", "coupling", {"od": _D, "length": _L, "bore": _D},
                  complexity=2, rotates=True),
    ComponentType("fastener", "Screw or bolt", "standard", "fastener", {
        "style": ParamSpec(unit="", choices=("hex_bolt", "shcs")),
        "size": ParamSpec(unit="M", integer=True, choices=(3, 4, 5, 6, 8, 10, 12, 16)), "length": _L},
        toolbox="hex_bolt", standard="ISO 4017 / ISO 4762", complexity=1),
    ComponentType("nut", "Hex nut", "standard", "fastener", {"size": ParamSpec(unit="M", integer=True)},
                  toolbox="hex_nut", standard="ISO 4032", complexity=1),
    ComponentType("washer", "Washer", "standard", "fastener", {"size": ParamSpec(unit="M", integer=True)},
                  toolbox="washer", standard="ISO 7089", complexity=1),
    ComponentType("dowel", "Dowel pin", "standard", "pin", {"d": _D, "length": _L},
                  toolbox="dowel", standard="ISO 8734", complexity=1),
    ComponentType("seal", "Seal", "standard", "seal", {"d": _D, "D": _D, "B": _L}, complexity=1),
    ComponentType("other", "Part", "machined", None, {"L": _L, "W": _L, "H": _L}, complexity=3),
]}

CONNECTIONS: dict[str, ConnectionType] = {c.kind: c for c in [
    ConnectionType(
        "keyed_hub", "keyed hub on a shaft", ("shaft",), ROTATING_HUBS, via=("key",), via_required=True,
        host_features=("seat Ø d (k6)", "keyseat b x t1 (DIN 6885)"),
        guest_features=("bore Ø d (H7)", "hub keyway b x t2 (DIN 6885)"),
        placement="coaxial; along the axis by its shoulder stop, else centred on the seat; the key centred in the hub",
        standards=("DIN 6885-1", "ISO 286 H7/k6"), icd=("shaft_bore", "key")),
    ConnectionType(
        "hub_fit", "hub fitted on a shaft (no key)", ("shaft",), ROTATING_HUBS,
        host_features=("seat Ø d",), guest_features=("bore Ø d",),
        placement="coaxial; along the axis by its shoulder stop, else centred on the seat",
        standards=("ISO 286",), icd=("shaft_bore",),
        params={"fit": ParamSpec(unit="", choices=("H7/k6", "H7/h6", "H7/p6", "H7/g6"))}),
    ConnectionType(
        "shoulder_stop", "seated against a shoulder", ("shaft",), ROTATING_HUBS + ("bearing",), axial=True,
        host_features=("shoulder: step from the seat Ø to a larger Ø",), guest_features=("face against the shoulder",),
        placement="the guest's face coincident with the shoulder face", icd=("shaft_bore",)),
    ConnectionType(
        "bearing_journal", "bearing on a journal", ("shaft",), ("bearing",),
        host_features=("journal Ø d (k6)",), guest_features=("inner ring bore d",),
        placement="coaxial; two per shaft, one either side of what it carries",
        standards=("ISO 15", "ISO 286 k6"), icd=("bearing_journal", "bearing_seat")),
    ConnectionType(
        "bearing_seat", "bearing in a housing bore", ("housing", "pillow_block", "bracket", "plate"), ("bearing",),
        host_features=("bore Ø D (H7) through the wall", "shoulder behind the outer ring"),
        guest_features=("outer ring D",),
        placement="the shaft axis through the housing walls; the outer ring against the wall shoulder",
        standards=("ISO 15", "ISO 286 H7"), icd=("bearing_seat",)),
    ConnectionType(
        "gear_mesh", "gear mesh", ("spur_gear",), ("spur_gear",),
        placement="parallel axes at a = m (z1 + z2) / 2, mid-planes coplanar, teeth phased",
        standards=("ISO 53",), icd=("gear_mesh",)),
    ConnectionType(
        "belt_drive", "belt drive between two pulleys", ("pulley",), ("pulley",),
        placement="parallel axes at the centre distance C (given, else C = D1 + D2), pulley mid-planes coplanar",
        icd=("belt_drive",), params={"centre_distance": ParamSpec(lo=10, hi=10000, label="centre distance C")}),
    ConnectionType(
        "coupling", "shafts coupled end to end", ("shaft", "motor"), ("shaft",), via=("coupling",),
        via_required=True, host_features=("shaft end Ø d",), guest_features=("shaft end Ø d",),
        placement="coaxial, end to end with a 2 mm gap; the coupling across the joint, clear of the bearings",
        icd=("shaft_bore",)),
    ConnectionType(
        "rod_support", "rod end held in a block", ("bracket", "pillow_block", "other"), ("shaft",),
        host_features=("bore Ø d (H7) along the rod",), guest_features=("rod end Ø d (h6)",),
        placement="the rod coaxial in the block's bore, its end flush with the block's outer face; the blocks at "
                  "both ends of the rod, on the base; parallel rods at the stated spacing",
        standards=("ISO 286 H7/h6",), icd=("shaft_bore",),
        params={"spacing": ParamSpec(lo=5, hi=5000, label="rod spacing (centre to centre)"),
                "height": ParamSpec(lo=1, hi=5000, label="rod axis above the base")}),
    ConnectionType(
        "slide", "slides on a rod", ("shaft",), ("other", "bracket", "plate", "hub"),
        host_features=("rod Ø d (h6)",), guest_features=("sliding bore Ø d (H7/g6)",),
        placement="coaxial on the rod, between the rod's supports (centred on them unless placed)",
        standards=("ISO 286 H7/g6",), icd=("shaft_bore",)),
    ConnectionType(
        "pin_joint", "pivots on a pin or a pivot bolt", ("bracket", "other", "plate", "housing"),
        ("other", "bracket", "plate"), via=("dowel", "fastener", "washer", "nut"), host_features=("pin bore through both lugs",), guest_features=("pivot bore",),
        placement="the pin axis across the host's lugs (along Y) at the pivot height; the guest centred between the "
                  "lugs, its pivot bore on the pin, lying along +X",
        icd=("dowel",), params={"pivot_height": ParamSpec(lo=1, hi=5000, label="pivot above the host's underside"),
                                "gap": ParamSpec(lo=1, hi=5000, label="gap between the lugs")}),
    ConnectionType(
        "bolted_joint", "bolted joint", ("housing", "plate", "bracket", "cover", "pillow_block", "other"),
        ("cover", "bearing_cap", "plate", "bracket", "housing", "pillow_block", "motor", "other"),
        via=("fastener", "nut", "washer", "dowel"),
        host_features=("mounting face", "tapped or clearance holes on a pattern"),
        guest_features=("mounting face", "clearance holes (ISO 273)"),
        placement="faces coincident, holes aligned", standards=("ISO 273", "ISO 4762 / ISO 4017"),
        icd=("hole_pattern",)),
    ConnectionType(
        "ring_retained", "held by a retaining ring", ("shaft",), ROTATING_HUBS + ("bearing",), via=("retaining_ring",),
        via_required=True, axial=True, host_features=("groove d2 x m (DIN 471)",),
        guest_features=("face against the ring",), placement="the ring in its groove against the guest's free face",
        standards=("DIN 471",), icd=("retaining_ring",)),
    ConnectionType(
        "mounted_on", "seated on", tuple(COMPONENTS), tuple(COMPONENTS),
        host_features=("mounting face",), guest_features=("seating face",),
        placement="the guest on the host's mounting face", icd=("face",)),
]}

# words in names / briefs -> component kind (the intent compiler's fallback reading of a free name)
NAME_KINDS: list[tuple[str, str]] = [
    (r"\bpinion|gear\b|gearwheel|\bwheel\b", "spur_gear"), (r"shaft|axle|spindle|arbou?r", "shaft"),
    (r"circlip|retaining ring|snap ring|seeger", "retaining_ring"), (r"\bkey\b|feather key|parallel key", "key"),
    (r"bearing|\b6[02]0\d\b", "bearing"), (r"\bcap\b|end cover|bearing cover", "bearing_cap"),
    (r"cover|\blid\b", "cover"), (r"housing|casing|gear ?box|\bcase\b", "housing"),
    (r"spacer|sleeve|distance ring|collar|bush", "spacer"), (r"pulley|sprocket|sheave", "pulley"),
    (r"\bhub\b", "hub"), (r"plate", "plate"), (r"bracket|support|pedestal", "bracket"),
    (r"\bnut", "nut"), (r"washer", "washer"), (r"dowel|locating pin", "dowel"),
    (r"bolt|screw", "fastener"), (r"seal|o-?ring", "seal"),
]


def component(kind: str) -> ComponentType | None:
    return COMPONENTS.get(kind)


def connection(kind: str) -> ConnectionType | None:
    return CONNECTIONS.get(kind)


def kind_from_name(name: str) -> str:
    import re

    best = (-1, "other")
    for rx, k in NAME_KINDS:
        for m in re.finditer(rx, name or "", re.IGNORECASE):
            if m.end() > best[0]:
                best = (m.end(), k)
    return best[1]


def prompt_reference() -> str:
    """The component and connection vocabulary, generated from the registries (the intent prompt's reference)."""
    lines = ["Component kinds (params in mm unless said; leave a size out when the brief doesn't give it):"]
    for c in COMPONENTS.values():
        ps = ", ".join(f"{k}" + (f" [{'/'.join(str(x) for x in s.choices)}]" if s.choices and len(s.choices) <= 4 else "")
                       for k, s in c.params.items() if k not in ("b", "h", "t1", "t2", "d2", "m", "s", "D", "B")
                       or c.kind in ("seal",))
        lines.append(f"- {c.kind}: {c.label}" + (f" ({ps})" if ps else ""))
    lines.append("Connection kinds (host = the side that carries; via = the parts that make the joint):")
    for k in CONNECTIONS.values():
        via = f"; via {'/'.join(k.via)}" if k.via else ""
        lines.append(f"- {k.kind}: {k.label}; host {'/'.join(k.hosts) if len(k.hosts) < 8 else 'any'}, guest "
                     f"{'/'.join(k.guests) if len(k.guests) < 8 else 'any'}{via}")
    return "\n".join(lines)
