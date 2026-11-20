"""The program skeleton and the Interface Control Document (CD-010, plan §2.1).

Before any part ticket is released, Archie lays the program out and names every interface between two items, with
numbers. Everything here is pure and deterministic: ``build(parts, brief, overrides)`` returns the same skeleton and
the same ICD for the same input, so an edit at the ICD gate or an accepted change request is "set an override and
build again", and interface ids stay stable.

Skeleton (the program coordinate system and the conceptual layout)
  * Program frame = datum reference frame A|B|C: A is the top face of the program base (plane Z = 0, +Z up),
    B the mid-plane Y = 0, C the mid-plane X = 0. Millimetres.
  * Every designed part gets a role and an envelope: ``block`` (prismatic box L x W x H), ``shaft`` (cylinder along
    Z), ``hub`` (a turned ring / collar / pulley along Z) or ``gear`` (envelope: tip circle m.(z + 2) x face width along Z; meshing at the pitch circles).
  * The part frame of an item: origin at the centre of its envelope, axes parallel to the program axes. A copy
    (qty > 1) is placed by a pure translation ``at`` (the envelope centre in the program frame).
  * Layout: the program base sits under datum A. Blocks carry a row of stations on their top face (along +X):
    child blocks, shafts (through a bore, bottom flush with the block), and hubs / gears (on a shaft if the
    sub-assembly has one, else bolted to the block). Hubs and gears on a shaft stack on the block's top face.
    Neighbouring shafts whose gears mesh are spaced at the exact centre distance.
  Sizes come from the plan (Archie's envelope, or sizes written in the part description); anything else is an
  assumption marked ``assumed``.

ICD (named interfaces with numbers, in the program frame)
  ``hole_pattern``  bolted joint: mounting face (plane, flatness, position tolerance) + n x Ø clearance holes
                    (ISO 273 medium for the fastener) at stated positions; grid or bolt circle (PCD)
  ``shaft_bore``    shaft in a bore: Ø, ISO 286 fit (H7/h6, H7/k6), engagement length, axis position, and for a
                    shaft through a block the flush end face
  ``face``          a part seated on another: plane, flatness, position tolerance
  ``gear_mesh``     module, teeth on both gears, centre distance, face width, pressure angle 20°
Each interface names its two items (``a`` carries the face pointing +Z / the bore; ``b`` sits on it / in it) and
its datum references.

Local features (what each side must carry, in its part frame) drive the placeholder bodies, the specialist's ICD
excerpt, Fitz's mates by interface name and Gage's conformance measurement.
"""

from __future__ import annotations

import copy
import json
import math
import re
from typing import Any

from aicad.office import frames
from aicad.toolbox import BEARING as _BEARING
from aicad.toolbox import BEARING_RS as _BEARING_RS
from aicad.toolbox import DIN471 as _DIN471

# ----------------------------------------------------------------------------- constants (documented, PD-xx)
CLEARANCE = {3: 3.4, 4: 4.5, 5: 5.5, 6: 6.6, 8: 9.0, 10: 11.0, 12: 13.5, 16: 17.5}  # ISO 273 medium series
WASHER_OD = {3: 7.0, 4: 9.0, 5: 10.0, 6: 12.0, 8: 16.0, 10: 20.0, 12: 24.0, 16: 30.0}  # ISO 7089
GAP = 12.0          # mm between stations on a block's top face
MARGIN = 10.0       # mm from a block's edge to its first station
MAX_COPIES = 8      # copies of one part laid out in the skeleton (the rest are noted)
PLAN_SLACK = 1.5    # past this multiple of the planned envelope the gate WARNS (outgrown): the plan was an estimate
GROW_CAP = 4.0      # autofix grows an envelope up to this multiple of the planned one (a sanity cap, not the brief)
PAD_GAP = 2.0       # mm between joint pads when a host's planned size can't take its children side by side
SLENDER = 4.0       # a turned part at least this many diameters long (planned envelope) is a rod: a shaft role
POS_TOL = 0.1       # mm: default position tolerance of interface features
FLATNESS = 0.05     # mm: default flatness of a mounting face
PRESSURE_ANGLE = 20.0
# gearbox housings (Phase 6): shafts along +Y in two side walls, caps over the seats, the cover as a lid
CAV = 6.0           # mm between gear tips / hubs and the housing floor, end walls and lid
CAV_Y = 12.0        # mm between a shaft's stack and the inner face of a side wall (room for the cap screw ends)
FLOOR = 10.0        # mm floor under the cavity
SHOULDER = 4.0      # mm of wall left behind a bearing seat (the shoulder the outer ring sits against)
TAP_DRILL = {3: 2.5, 4: 3.3, 5: 4.2, 6: 5.0, 8: 6.8, 10: 8.5, 12: 10.2, 16: 14.0}  # ISO 2306 tap drills (verify)
# bearing caps (PD: cap ligament): the cap screws' tapped holes leave at least max(LIGAMENT, LIGAMENT_D x d) of wall
# between the bearing seat and each tap drill, so PCD = D + tap drill + 2 x ligament, rounded up to 0.5 mm. The live
# gear reducer (2026-11-19) had M8 on PCD 58 over a Ø47 seat: 2.1 mm of wall.
LIGAMENT = 3.0       # mm
LIGAMENT_D = 0.5     # x the nominal screw size
CAP_RELIEF = 1.0     # mm deep recess in a cap's mounting face over the bearing's inner ring (it turns; the cap doesn't)
EXIT_SIDE = 1        # gearbox shafts leave the housing through the +Y wall (open caps there, blind caps on -Y)
# shaft lines (no housing or base plate: the mechanism is carried by its own shafts and bearings)
BEARING_CLEAR = 5.0  # mm between a gear / hub face and the face of a bearing on its shaft (room for a spacer)
GEAR_SPACE = 5.0     # mm between two gears on one shaft (a compound train)
SHAFT_END = 10.0     # mm of shaft beyond each outer bearing face (at least half the shaft Ø)
SEAT_END = 2.0       # mm of seat beyond the free face of the hub on a stepped shaft with no bearings (a sub-assembly)
KIND_LABEL = {"hole_pattern": "bolted joint", "shaft_bore": "shaft / bore fit", "face": "seating face",
              "gear_mesh": "gear mesh", "bearing_seat": "bearing seat", "key": "keyed joint", "dowel": "dowel pins",
              "bearing_journal": "bearing on journal", "retaining_ring": "retaining ring", "belt_drive": "belt drive"}
EDITABLE = {"hole_pattern": ("fastener", "d", "count", "inset", "flatness", "position_tol"),
            "shaft_bore": ("d", "fit"), "face": ("flatness", "position_tol"),
            "gear_mesh": ("module", "teeth_a", "teeth_b"), "bearing_seat": ("designation", "housing_fit"),
            "key": ("length",), "dowel": ("d",), "bearing_journal": ("designation",), "retaining_ring": (),
            "belt_drive": ()}
ROTATIONS = (0, 90, 180, 270)  # quarter turns of a part frame about +Z (Archie's ``rotate`` hint or an ICD edit)

# Deep-groove ball bearings (the Toolbox table, ISO 15): designation -> (bore d, OD D, width B). 62xx first: the
# office prefers the heavier series for shafts it sizes itself.

BEARINGS: dict[int, tuple[float, float, float]] = {k: (float(v[0]), float(v[1]), float(v[2])) for k, v in _BEARING.items()}
# DIN 471 external retaining rings (the Toolbox table): shaft d1 -> (s, b radial width, d2 groove Ø, m groove width,
# n min groove edge distance)
RINGS: dict[int, tuple[float, float, float, float, float]] = {k: tuple(float(x) for x in v) for k, v in _DIN471.items()}  # type: ignore[misc]
HOUSING_FITS = ("H7", "J7", "K7")
SHAFT_FIT_BEARING = "k6"  # rotating inner ring, normal load (ISO 286 values; verify against the bearing maker)
# DIN 6885-1 form A parallel keys: shaft Ø (over, up to) -> (b, h, t1 shaft depth, t2 hub depth)
KEYS = [((8, 10), (3, 3, 1.8, 1.4)), ((10, 12), (4, 4, 2.5, 1.8)), ((12, 17), (5, 5, 3.0, 2.3)),
        ((17, 22), (6, 6, 3.5, 2.8)), ((22, 30), (8, 7, 4.0, 3.3)), ((30, 38), (10, 8, 5.0, 3.3)),
        ((38, 44), (12, 8, 5.0, 3.3)), ((44, 50), (14, 9, 5.5, 3.8)), ((50, 58), (16, 10, 6.0, 4.3)),
        ((58, 65), (18, 11, 7.0, 4.4))]
KEY_TOL = 0.05     # mm on the keyway width (P9 / JS9 are tighter: a drawing callout)
DEPTH_TOL = 0.1    # mm on keyway depths and seat depths
DOWEL_LENGTHS = (6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 45, 50, 60)  # ISO 8734 preferred lengths

_SHAFTY = re.compile(r"shaft|axle|spindle|lead screw|ball screw|journal|arbor|\broller\b|\bpin\b", re.IGNORECASE)
_HUBBY = re.compile(r"cap|collar|spacer|bush|hub|pulley|ring|flange|locator|sleeve|wheel|drum|washer|disc|disk", re.IGNORECASE)
_BEARINGY = re.compile(r"\bbearing|\b6[02]0\d\b", re.IGNORECASE)
_KEYY = re.compile(r"\bkey(?:ed|way)?\b|feather key|parallel key", re.IGNORECASE)
_RINGY = re.compile(r"circlips?|retaining rings?|snap rings?|seeger|\bDIN\s*471\b", re.IGNORECASE)
_DOWELY = re.compile(r"\bdowel|\blocating pin", re.IGNORECASE)
_CAPPY = re.compile(r"\bcap\b|end cover|bearing cover", re.IGNORECASE)
# open caps let the shaft through (a seal bore); blind caps close the bore. Read from the name first.
_OPENY = re.compile(r"\bopen\b|\bthrough\b|\bthru\b|\bseal(?:ed|ing)?\b|\blip\b|\bpass(?:es)?\b", re.IGNORECASE)
_BLINDY = re.compile(r"\bblind\b|\bclosed\b|\bsolid\b|\bblank\b", re.IGNORECASE)
# the screws that hold the bearing caps: "Cap screw M6x16 that fixes the four bearing caps" (not "cap screw" alone)
_CAP_FIXY = re.compile(r"\b(?:bearing |end )?caps\b|\b(?:bearing|end) cap\b|\bbearing covers?\b|\bend covers?\b",
                       re.IGNORECASE)
_LIDDY = re.compile(r"cover|\blid\b", re.IGNORECASE)
_PLATEY = re.compile(r"\bplate\b", re.IGNORECASE)
_HOUSINGY = re.compile(r"housing|casing|\bcase\b|gearbox|gear box", re.IGNORECASE)
# where a shaft / gear / bearing sits in a shaft line, by its name (intermediate first: "intermediate pinion")
_LINE_CLASS = (("mid", re.compile(r"intermediate|\bidler|counter|\blay\s*shaft|\bmiddle", re.IGNORECASE)),
               ("input", re.compile(r"\binput|\bdrive\b|\bdriving|\bmotor|\bpinion|high.speed", re.IGNORECASE)),
               ("output", re.compile(r"\boutput|\bdriven|\bwheel\b|low.speed", re.IGNORECASE)))
_NUM = r"(\d+(?:\.\d+)?)"


# ----------------------------------------------------------------------------- axes of interfaces (Phase 6)
# An interface whose features are cylinders / planes along a program axis other than Z carries ``data["ax"]`` ("x"
# or "y"; absent = "z"). Its 2-D numbers are then in the plane across that axis, in program coordinates ordered
# ``PLANE[ax]`` ("axis": [X, Z] for a shaft along Y), and its 1-D numbers ("z" ranges, "plane_z", "flush_z") are
# coordinates along the axis.
PLANE = {"z": (0, 1), "y": (0, 2), "x": (1, 2)}
AXIS_INDEX = {"x": 0, "y": 1, "z": 2}
CANON = frames.CANON  # canonical feature frame -> part frame (the canonical Z is the feature's axis)


def ax_of(data: dict[str, Any]) -> str:
    a = str((data or {}).get("ax") or "z")
    return a if a in PLANE else "z"


def point3(ax: str, a2: Any, t: float) -> list[float]:
    """A program-frame point from an interface's 2-D axis coordinates and a coordinate along its axis."""
    p = [0.0, 0.0, 0.0]
    i, j = PLANE[ax]
    p[i], p[j] = float(a2[0]), float(a2[1])
    p[AXIS_INDEX[ax]] = float(t)
    return p


def unit(ax: str) -> list[float]:
    v = [0.0, 0.0, 0.0]
    v[AXIS_INDEX[ax]] = 1.0
    return v


def joint_axis(f: dict[str, Any], which: str = "a") -> dict[str, Any] | None:
    """The rotation axis an interface defines, in the program frame: {"p": [x, y, z], "dir": [dx, dy, dz]}.
    bearing_seat / bearing_journal / shaft_bore / key: the shaft axis; gear_mesh: the axis of gear ``which``."""
    d = f.get("data") or {}
    ax = ax_of(d)
    if f.get("kind") in ("bearing_seat", "shaft_bore", "key", "bearing_journal") and d.get("axis") is not None:
        z = d.get("z") or [0.0, 0.0]
        return {"p": point3(ax, d["axis"], float(z[0])), "dir": unit(ax)}
    if f.get("kind") == "gear_mesh":
        a2 = d.get("axis_a" if which == "a" else "axis_b")
        if a2 is None:
            return None
        return {"p": point3(ax, a2, float(d.get("plane_" + which) or 0.0)), "dir": unit(ax)}
    return None


def key_for(d: float) -> tuple[float, float, float, float] | None:
    """DIN 6885-1 key (b, h, t1, t2) for a shaft Ø, or None outside the table (8..65 mm)."""
    for (lo, hi), v in KEYS:
        if lo < d <= hi:
            return (float(v[0]), float(v[1]), float(v[2]), float(v[3]))
    return None


def bearing_for(d: float, designation: int | None = None) -> int | None:
    """The bearing for a shaft Ø: the written designation if its bore fits, else the 62xx (then 60xx) bearing with
    the largest bore not above the shaft Ø."""
    if designation in BEARINGS and BEARINGS[designation][0] <= d + 1e-9:  # type: ignore[index]
        return designation
    for series in (62, 60):
        fit = [k for k, v in BEARINGS.items() if k // 100 == series and v[0] <= d + 1e-9]
        if fit:
            return max(fit, key=lambda k: (BEARINGS[k][0], -k))
    return None


def tap_depth(m: int) -> float:
    """Depth of a blind tapped hole for an M``m`` screw: 2.5 d of thread room + 3 mm (engagement 2 d in aluminium,
    thread run-out, chips)."""
    return float(2.5 * m + 3.0)


def dowel_length(total: float) -> float:
    return float(next((x for x in DOWEL_LENGTHS if x >= total), DOWEL_LENGTHS[-1]))


# ----------------------------------------------------------------------------- ISO 286 fits (verify)
_RANGES = [3, 6, 10, 18, 30, 50, 80, 120, 180, 250, 315, 400, 500]
_IT = {6: [6, 8, 9, 11, 13, 16, 19, 22, 25, 29, 32, 36, 40], 7: [10, 12, 15, 18, 21, 25, 30, 35, 40, 46, 52, 57, 63],
       8: [14, 18, 22, 27, 33, 39, 46, 54, 63, 72, 81, 89, 97]}
_DEV = {"f": [-6, -10, -13, -16, -20, -25, -30, -36, -43, -50, -56, -62, -68],     # es (shafts)
        "g": [-2, -4, -5, -6, -7, -9, -10, -12, -14, -15, -17, -18, -20],          # es
        "h": [0] * 13,                                                               # es
        "k": [0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4, 5],                                # ei (IT4..IT7)
        "p": [6, 12, 15, 18, 22, 26, 32, 37, 43, 50, 56, 62, 68]}                    # ei
FITS = ("H7/h6", "H7/g6", "H7/k6", "H7/p6", "H8/f7", "H7/f7")


def zone(d: float, code: str) -> tuple[float, float] | None:
    """Limits (lo, hi) in mm for one tolerance class (``H7``, ``h6``, ``k6`` ...), ISO 286-2 values (verify)."""
    m = re.fullmatch(r"([A-Za-z])(\d)", code.strip())
    if not m or d <= 0 or d > 500:
        return None
    letter, grade = m.group(1), int(m.group(2))
    if grade not in _IT:
        return None
    k = next(i for i, top in enumerate(_RANGES) if d <= top)
    it = _IT[grade][k] / 1000.0
    if letter == "H":
        return d, d + it
    lo_letter = letter.lower()
    if letter.isupper() or lo_letter not in _DEV:
        return None
    dev = _DEV[lo_letter][k] / 1000.0
    if lo_letter in ("k", "p"):
        return d + dev, d + dev + it
    return d + dev - it, d + dev


def fit_zones(d: float, fit: str) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    hole, _, shaft = (fit or "").partition("/")
    return zone(d, hole), zone(d, shaft)


def bolt_for_hole(d: float) -> int:
    """The bolt a clearance hole takes (the largest size whose ISO 273 medium hole fits in it)."""
    return max((m for m, c in CLEARANCE.items() if c <= d + 1e-9), default=3)


def fastener_for(span: float) -> int:
    """Fastener size for a bolted joint from the smaller footprint dimension of the part being bolted down."""
    for limit, m in ((30, 3), (50, 4), (80, 5), (150, 6), (260, 8)):
        if span < limit:
            return m
    return 10


# ----------------------------------------------------------------------------- reading the plan
def _sizes(text: str) -> tuple[float | None, list[float]]:
    """(a written Ø, the other sizes in order) from a part description."""
    t = text or ""
    dia = re.search(r"[ØⲐ⌀]\s*" + _NUM, t)
    rest = re.sub(r"[ØⲐ⌀]\s*" + _NUM, " ", t)
    rest = re.sub(r"\bM\d+(?:\s*[x×]\s*\d+)?", " ", rest)  # thread sizes are not sizes
    nums = []
    for m in re.finditer(_NUM + r"\s*[x×]\s*" + _NUM + r"(?:\s*[x×]\s*" + _NUM + r")?", rest):
        nums += [float(g) for g in m.groups() if g]
    if not nums:
        nums = [float(m.group(1)) for m in re.finditer(_NUM + r"\s*mm\b", rest)]
    return (float(dia.group(1)) if dia else None), [n for n in nums if n > 0]


_STEPPED = re.compile(r"\bstepped\b|\bshoulders?\b|\bsteps?\b", re.IGNORECASE)


def _diameters(text: str) -> list[float]:
    """Every diameter written in a description (Ø20, "20 mm diameter", "diameter 26"), in order."""
    t = text or ""
    out = [float(m.group(1)) for m in re.finditer(r"[ØⲐ⌀]\s*" + _NUM, t)]
    out += [float(m.group(1)) for m in re.finditer(_WORDED_D, t)]
    out += [float(m.group(1)) for m in re.finditer(r"\b(?:diameter|dia\.?)\s*(?:of\s*)?" + _NUM, t, re.IGNORECASE)]
    out += [float(m.group(1)) for m in re.finditer(_STEP_D, t)]
    return [d for d in out if d > 0]


def _bore_hint(text: str) -> float | None:
    """The bore a hub or gear description states ("20 mm H7 bore", "bore Ø20", "a 20 H7 bore")."""
    m = _BORE_D.search(text or "") or re.search(r"\bbore\s*(?:of\s*)?[ØⲐ⌀]?\s*" + _NUM, text or "", re.IGNORECASE)
    return float(m.group(1)) if m else None


# "20 mm diameter", "20 mm h6 diameter", "20h6 dia": the number is not part of a word ("h6" is a tolerance class)
_WORDED_D = re.compile(r"(?<![\w.])" + _NUM + r"\s*(?:mm\s*)?(?:[a-zA-Z]{1,2}\d{1,2}\s*)?(?:diameter|dia\b)",
                       re.IGNORECASE)
# a shaft's steps in words: "20 mm k6 gear seat", "25 mm larger step", "Ø26 body" (not "6 mm keyseat")
_STEP_D = re.compile(r"(?<![\w.])" + _NUM + r"\s*(?:mm\s*)?(?:[a-zA-Z]{1,2}\d{1,2}\s+)?(?:[a-z]+\s+){0,2}"
                     r"(?:seat|journal|step|body|shoulder|collar)\b", re.IGNORECASE)
_BORE_D = re.compile(r"(?<![\w.])" + _NUM + r"\s*(?:mm\s*)?(?:[a-zA-Z]{1,2}\d{1,2}\s*)?bore\b", re.IGNORECASE)


def shoulder_for(d: float) -> float:
    """The larger step of a stepped shaft behind a hub seat of Ø d when the plan gives none (assumed, said so):
    a shoulder of max(2.5, 0.1 d + 1) mm per side, rounded to a whole mm (Ø20 -> Ø26, Ø25 -> Ø32, Ø40 -> Ø50)."""
    return float(round(d + 2 * max(2.5, 0.1 * d + 1.0)))


def _worded(text: str) -> tuple[float | None, float | None]:
    """(Ø, length) written in words: "20 mm diameter" / "diameter 20", "120 long" / "length 120"."""
    t = text or ""
    dm = _WORDED_D.search(t) or re.search(r"\b(?:diameter|dia\.?)\s*(?:of\s*)?" + _NUM, t, re.IGNORECASE)
    lm = re.search(_NUM + r"\s*(?:mm\s*)?long\b", t, re.IGNORECASE) or \
        re.search(r"\blength\s*(?:of\s*)?" + _NUM, t, re.IGNORECASE)
    return (float(dm.group(1)) if dm else None), (float(lm.group(1)) if lm else None)


def _module_teeth(text: str) -> tuple[float | None, int | None]:
    t = text or ""
    m = (re.search(r"\bmodule\s*" + _NUM, t, re.IGNORECASE) or re.search(r"\bm\s*=\s*" + _NUM, t)
         or re.search(r"\bm(\d+(?:\.\d+)?)\b", t))
    z = re.search(r"(\d+)\s*(?:teeth|tooth)", t, re.IGNORECASE)
    mod = float(m.group(1)) if m else None
    return (mod if mod and 0.3 <= mod <= 20 else None), (int(z.group(1)) if z and 8 <= int(z.group(1)) <= 300 else None)


def _ratio(brief: str) -> float | None:
    m = re.search(_NUM + r"\s*:\s*1\b", brief or "")
    if m and 1 < float(m.group(1)) <= 10:
        return float(m.group(1))
    m = re.search(r"\bratio\s*(?:of\s*)?" + _NUM, brief or "", re.IGNORECASE)
    return float(m.group(1)) if m and 1 < float(m.group(1)) <= 10 else None


def _fastener_hint(text: str) -> int | None:
    m = re.search(r"\bM(\d{1,2})\b", text or "")
    return int(m.group(1)) if m and int(m.group(1)) in CLEARANCE else None


# a metric thread size as the engineer writes it ("4 M6 bolts", "M6x20", "M6 x 20"); upper case only, so a gear
# module ("m2, 20/60 teeth") never reads as a screw, and not when "module" stands next to it ("M2 module")
_BRIEF_M = re.compile(r"(?<!module )(?<![A-Za-z0-9])M(\d{1,2})(?![0-9.])(?!\s*module)")


def brief_fastener(brief: str) -> int | None:
    """The one fastener size the brief states explicitly ("joined by 4 M6 bolts"), else None. It wins over the
    plan's own hints and the layout's size-from-span rule, so the interface says what the engineer asked for
    (Archie's live run 2026-11-20: the brief said M6, the ICD said M5). A brief that names several sizes leaves
    the choice per joint to the plan's fasteners (``fast_hint``)."""
    sizes = {int(m.group(1)) for m in _BRIEF_M.finditer(brief or "")}
    sizes &= set(CLEARANCE)
    return next(iter(sizes)) if len(sizes) == 1 else None


def parts_from(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The designed and standard parts of an approved program, in plan order, with what the layout needs."""
    plan = doc.get("plan") or {}
    hints: dict[str, dict[str, Any]] = {}
    for s in plan.get("subassemblies") or []:
        for p in s.get("parts") or []:
            hints[f"i_{s['id']}_{p['id']}"] = {k: p.get(k) for k in ("envelope", "mounts_on", "module", "teeth",
                                                                     "rotate") if p.get(k) is not None}
    cx = {t["item_id"]: t.get("complexity", 2) for t in doc.get("tickets") or []}
    out = []
    for it in doc.get("items") or []:
        if it["kind"] != "part":
            continue
        out.append({"id": it["id"], "name": it["name"], "family": it.get("family") or "machined",
                    "qty": int(it.get("qty") or 1), "description": it.get("description") or "",
                    "complexity": int(cx.get(it["id"], 2)), "sub": it["parent_id"], **hints.get(it["id"], {})})
    return out


# ----------------------------------------------------------------------------- roles and sizes
def _role(p: dict[str, Any], sub_has_shaft: bool) -> str:
    fam = p["family"]
    if fam == "standard":
        return "standard"
    if fam == "gear":
        return "gear"
    if fam == "turned":
        if _SHAFTY.search(p["name"]):
            return "shaft"
        env = p.get("envelope") if isinstance(p.get("envelope"), list) and len(p["envelope"]) == 3 else None
        if env and not _HUBBY.search(p["name"]) and float(env[2]) >= SLENDER * max(float(env[0]), float(env[1])):
            return "shaft"  # a rod / pin / strut by its planned shape: it is carried, it doesn't carry a shaft
        if _HUBBY.search(p["name"]) or sub_has_shaft:
            return "hub"
        return "shaft"
    return "block"


def _r2(x: float) -> float:
    return round(float(x) + 0.0, 2) + 0.0


def _initial(p: dict[str, Any], role: str, brief: str, ratio: float | None, gear_n: int,
             ov: dict[str, Any]) -> dict[str, Any]:
    """Role-based starting size: the override, Archie's envelope, sizes in the description, else an assumption."""
    cx = max(1, min(5, int(p.get("complexity") or 2)))
    dia, nums = _sizes(p["description"])
    env = p.get("envelope") if isinstance(p.get("envelope"), list) and len(p["envelope"]) == 3 else None
    src = "assumed"
    s: dict[str, Any] = {"role": role}
    if role == "block":
        L, W, H = 60.0 + 20 * cx, 0.0, 8.0 + 4 * cx
        W = round(0.7 * L)
        if p["family"] == "sheet":
            H = 3.0
        if env:
            L, W, H = (float(x) for x in env)
            src = "plan"
        elif len(nums) >= 3:
            L, W, H = nums[0], nums[1], nums[2]
            src = "brief"
        elif len(nums) == 2:
            L, W = nums[0], nums[1]
            src = "brief"
        s.update(L=L, W=W, H=H)
    elif role == "shaft":
        d, length = 16.0 + 4 * cx, 0.0
        dia = dia or _worded(p["description"])[0]
        if env:
            d, length = float(min(env[0], env[1])), float(env[2])
            src = "plan"
        elif dia:
            nums = nums + ([_worded(p["description"])[1]] if _worded(p["description"])[1] else [])
            d = dia
            length = max(nums) if nums else 0.0
            src = "brief"
        s.update(d=d, length=length)
    elif role == "hub":
        OD, H = 40.0 + 10 * cx, 10.0 + 4 * cx
        if env:
            OD, H = float(max(env[0], env[1])), float(env[2])
            src = "plan"
        elif dia:
            OD = dia
            H = max(nums) if nums else H
            src = "brief"
        s.update(OD=OD, H=H, od_given=src != "assumed")
    elif role == "gear":
        mod, z = _module_teeth(f"{p['description']} {p['name']}")
        if p.get("module"):
            mod = float(p["module"])
        if p.get("teeth"):
            z = int(p["teeth"])
        z0 = 18 if gear_n == 0 or "pinion" in p["name"].lower() else round(18 * (ratio or 2.0))
        if mod or z:
            src = "brief" if not (p.get("module") or p.get("teeth")) else "plan"
        mod = mod or 2.0
        z = z or z0
        s.update(module=mod, teeth=z, b=10.0 * mod)
    for k, v in (ov or {}).items():
        if k in s and isinstance(v, int | float) and v > 0:
            s[k] = float(v) if k != "teeth" else int(v)
            src = "edited"
    if role == "hub" and "OD" in (ov or {}):
        s["od_given"] = True
    s["source"] = src
    return s


SIZE_KEYS = {"block": ("L", "W", "H"), "shaft": ("d", "d", "length"), "hub": ("OD", "OD", "H")}


def _planned(p: dict[str, Any], s: dict[str, Any], io: dict[str, Any]) -> list[float] | None:
    """The envelope the plan gives a part, in the order of its skeleton ``size`` (box L, W, H; shaft Ø, Ø, length;
    round part OD, OD, H), with the sizes an engineer set (a resize, an approved freeze) in place of the plan's.
    Sizes Archie grew to make a part buildable (``grown``) don't count: they are measured against the plan."""
    keys = SIZE_KEYS.get(s["role"])
    env = p.get("envelope") if isinstance(p.get("envelope"), list) and len(p["envelope"]) == 3 else None
    if not keys or not env:
        return None
    try:
        e = [float(x) for x in env]
    except (TypeError, ValueError):
        return None
    if min(e) <= 0:
        return None
    if s["role"] == "block":
        out = e
    elif s["role"] == "shaft":
        out = [min(e[0], e[1])] * 2 + [e[2]]
    else:
        out = [max(e[0], e[1])] * 2 + [e[2]]
    grown = set(io.get("grown") or [])
    for n, k in enumerate(keys):
        v = io.get(k)
        if k not in grown and isinstance(v, int | float) and not isinstance(v, bool) and v > 0:
            out[n] = float(v)
    return [_r2(x) for x in out]


# ----------------------------------------------------------------------------- shaft lines: who sits where
_BASEY = re.compile(r"\btop\b|\btable\b|\bdesk\b|\bdeck\b|\bframe\b|chassis|\bbase\b|\bhousing\b", re.IGNORECASE)


def _base_rank(p: dict[str, Any]) -> tuple[int, int]:
    """What the others mount on, before the largest box (the founder's "TEST Project": a leg x 4 was the base and
    legs #2 .. #4 floated): a single part first (a part made in copies can't carry the rest from one of them), then a
    top, base, frame or housing by name."""
    return (int(int(p.get("qty") or 1) == 1), int(bool(_BASEY.search(p.get("name") or ""))))


def _line_class(name: str) -> str | None:
    return next((c for c, rx in _LINE_CLASS if rx.search(name or "")), None)


def _cap_kind(p: dict[str, Any]) -> str | None:
    """"open" (the shaft passes through it), "blind" (it closes the bore) or None, by the cap's name, else its
    description."""
    for t in (p.get("name") or "", p.get("description") or ""):
        o, b = bool(_OPENY.search(t)), bool(_BLINDY.search(t))
        if o != b:
            return "open" if o else "blind"
    return None


def _assign_caps(cap_sts: list[tuple[str, int]], seats_at: list[tuple[int, int]], shaft_names: list[str],
                 D: list[float], by_id: dict[str, dict[str, Any]]) -> list[tuple[int, tuple[str, int]]]:
    """Which cap piece goes over which bearing seat: [(seat index, (cap item, copy))]. A seat on the side its shaft
    leaves the housing (EXIT_SIDE) takes an open cap, the other a blind cap; a cap named for the input / output takes
    that shaft's seats only; caps that say neither go anywhere. Best match first (kind 4, shaft 2, the seat Ø written
    in the cap's description 1), then seat order and plan order, so a plan of identical caps fills the seats in seat
    order. A cap that fits no seat is left out (it gets no interface: the ICD gate shows it)."""
    cand: list[tuple[int, int, int]] = []
    for j, (n, side) in enumerate(seats_at):
        want = "open" if side == EXIT_SIDE else "blind"
        sc = _line_class(shaft_names[n])
        for k, st in enumerate(cap_sts):
            p = by_id[st[0]]
            kind, cc = _cap_kind(p), _line_class(p["name"])
            if (kind and kind != want) or (cc and sc and cc != sc):
                continue
            said = re.search(rf"(?<![\d.]){D[n]:g}(?![\d.])", f"{p['name']} {p.get('description') or ''}")
            cand.append((-(4 * (kind == want) + 2 * (cc is not None and cc == sc) + (1 if said else 0)), j, k))
    used_s: set[int] = set()
    used_c: set[int] = set()
    out: list[tuple[int, tuple[str, int]]] = []
    for _s, j, k in sorted(cand):
        if j in used_s or k in used_c:
            continue
        used_s.add(j)
        used_c.add(k)
        out.append((j, cap_sts[k]))
    return sorted(out)


def _line_order(shafts: list[dict[str, Any]]) -> list[str]:
    """The shafts of a shaft line, input first, output last (by name), else in plan order."""
    rank = {"input": 0, "mid": 1, None: 1, "output": 2}
    return [p["id"] for p in sorted(shafts, key=lambda p: (rank[_line_class(p["name"])], shafts.index(p)))]


def _line_parents(designed: list[dict[str, Any]], spec: dict[str, dict[str, Any]], order: list[str],
                  names: dict[str, str]) -> dict[str, str | None]:
    """Which shaft each gear / hub of a shaft line sits on: Archie's ``mounts_on``, else by name (the pinion on the
    input shaft, the wheel on the output shaft, the intermediate gears on the intermediate shaft), else in plan
    order: one gear per shaft (a simple or idler train), or 1, 2, ..., 2, 1 gears for a compound train (2 (n - 1)
    gears on n shafts). Hubs go on a shaft of their own sub-assembly. Shafts have no parent."""
    by_id = {p["id"]: p for p in designed}
    parent: dict[str, str | None] = {p["id"]: None for p in designed}
    gears = {sh: 0 for sh in order}
    left: list[dict[str, Any]] = []
    for p in designed:
        if spec[p["id"]]["role"] not in ("hub", "gear"):
            continue
        want = names.get(str(p.get("mounts_on") or "").lower())
        cls = _line_class(p["name"])
        same = [sh for sh in order if _line_class(by_id[sh]["name"]) == cls] if cls else []
        if want not in gears and same:
            mine = [sh for sh in same if by_id[sh]["sub"] == p["sub"]] or same
            want = min(mine, key=lambda sh: (gears[sh], order.index(sh)))
        if want in gears:
            parent[p["id"]] = want
            gears[want] += spec[p["id"]]["role"] == "gear"  # type: ignore[index]
            continue
        left.append(p)
    lg = [p for p in left if spec[p["id"]]["role"] == "gear"]
    n = len(order)
    if n >= 3 and lg and len(lg) == 2 * (n - 1) and not any(gears.values()):
        for k, p in enumerate(lg):  # compound: g0 on s0, g1 g2 on s1, ..., the last on the last shaft
            parent[p["id"]] = order[(k + 1) // 2]
            gears[order[(k + 1) // 2]] += 1
        lg = []
    for p in lg:
        pool = [sh for sh in order if by_id[sh]["sub"] == p["sub"] and not gears[sh]] or \
            [sh for sh in order if not gears[sh]] or order
        sh = min(pool, key=lambda s: (gears[s], order.index(s)))
        parent[p["id"]] = sh
        gears[sh] += 1
    for p in left:
        if spec[p["id"]]["role"] == "hub":
            parent[p["id"]] = next((sh for sh in order if by_id[sh]["sub"] == p["sub"]), order[0])
    return parent


# ----------------------------------------------------------------------------- the layout engine
def build(parts: list[dict[str, Any]], brief: str = "", overrides: dict[str, Any] | None = None
          ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(skeleton, interfaces) for the program's parts. Deterministic; overrides = {"items": {id: {...}},
    "interfaces": {IF-id: {...}}} (ICD edits, accepted change requests and envelopes frozen at approval)."""
    ov = overrides or {}
    iov: dict[str, dict[str, Any]] = ov.get("items") or {}
    fov: dict[str, dict[str, Any]] = ov.get("interfaces") or {}
    ratio = _ratio(brief)
    by_id = {p["id"]: p for p in parts}
    subs: list[str] = []
    for p in parts:
        if p["sub"] not in subs:
            subs.append(p["sub"])
    designed = [p for p in parts if p["family"] != "standard"]
    shaft_subs = {p["sub"] for p in designed if p["family"] == "turned" and _SHAFTY.search(p["name"])}
    spec: dict[str, dict[str, Any]] = {}
    gear_n = 0
    for p in designed:
        role = _role(p, p["sub"] in shaft_subs)
        spec[p["id"]] = _initial(p, role, brief, ratio, gear_n, iov.get(p["id"], {}))
        gear_n += role == "gear"
        pl = _planned(p, spec[p["id"]], iov.get(p["id"]) or {})
        if pl:
            spec[p["id"]]["planned"] = pl
    # fastener size hints from standard parts of the same sub-assembly
    fast_hint: dict[str, int] = {}
    fast_item: dict[str, str] = {}
    bearing_item: dict[str, dict[str, Any]] = {}   # sub -> the bearing standard part (and its written designation)
    key_item: dict[str, str] = {}                   # sub -> a parallel-key standard part
    key_pool: list[dict[str, Any]] = []             # every key standard part: pieces left, its one size (d, l)
    ring_pool: list[dict[str, Any]] = []            # every DIN 471 retaining ring: pieces left, its one shaft Ø
    dowel_item: dict[str, dict[str, Any]] = {}      # sub -> the dowel standard part
    bearing_all: list[dict[str, Any]] = []          # every bearing standard part (shaft lines share them out)
    # sub -> the screws the plan names for its bearing caps ({"id", "m"}): they hold the caps, not the cover
    cap_fast: dict[str, dict[str, Any]] = {}
    for p in parts:
        text = f"{p['name']} {p['description']}"
        if p["family"] == "standard" and re.search(r"bolt|screw", p["name"], re.IGNORECASE) \
                and _CAP_FIXY.search(text) and p["sub"] not in cap_fast:
            mm = re.search(r"\bM(\d{1,2})(?=\s*[x×]|\b)", text)
            cap_fast[p["sub"]] = {"id": p["id"], "qty": int(p["qty"]),
                                  "m": int(mm.group(1)) if mm and int(mm.group(1)) in CLEARANCE else None}
    for p in parts:
        text = f"{p['name']} {p['description']}"
        if p["family"] == "standard" and any(c["id"] == p["id"] for c in cap_fast.values()):
            continue  # the cap screws: only the caps take them (fast_item falls back to them below)
        if p["family"] == "standard" and re.search(r"bolt|screw", text, re.IGNORECASE):
            fast_item.setdefault(p["sub"], p["id"])
            h = _fastener_hint(text)
            if h:
                fast_hint.setdefault(p["sub"], h)
        if p["family"] != "standard":
            continue
        # by name first: "Gear circlip" or "Pinion key" whose description mentions the 6204 next to it is no bearing
        ringy = _RINGY.search(p["name"]) or (_RINGY.search(text) and not _BEARINGY.search(p["name"])
                                             and not _KEYY.search(p["name"]))
        keyy = not ringy and (_KEYY.search(p["name"]) or (_KEYY.search(text) and not _BEARINGY.search(text)
                                                          and not _DOWELY.search(text)))
        if ringy:
            # its role, as the plan states it: what it locates ("locating each bearing inner race" / "holding the gear
            # against the shoulder"): rings go to spots of that role, never just by order and Ø (golden suite F4)
            # A leading "Gear" / "Pinion" in the name says whose line the ring belongs to ("Gear circlip" in the Gear
            # shaft assembly), not what it holds: only the description, or a later word of the name, gives the hub
            # role (live gear pair: four "Gear circlip" rings read as hub rings left the gear shaft's bearings without
            # rings and crossed to the pinion's gear faces)
            hubby = r"gear|hub|pulley|wheel|sprocket|spacer"
            rest = " ".join(str(p["name"]).split()[1:])
            role = "bearing" if _BEARINGY.search(text) and not re.search(hubby, p["name"], re.IGNORECASE) else \
                "hub" if re.search(hubby, f"{rest} {p['description']}", re.IGNORECASE) else None
            ring_pool.append({"id": p["id"], "left": int(p["qty"]), "sub": p["sub"], "name": p["name"], "d": None,
                              "role": role})
        elif keyy:
            key_item.setdefault(p["sub"], p["id"])
            key_pool.append({"id": p["id"], "left": int(p["qty"]), "sub": p["sub"], "size": None})
        elif _BEARINGY.search(text):
            m = re.search(r"\b(6[02]0\d)\b", text)
            bearing_item.setdefault(p["sub"], {"id": p["id"], "qty": int(p["qty"]),
                                               "designation": int(m.group(1)) if m else None})
            bearing_all.append({"id": p["id"], "qty": int(p["qty"]), "designation": int(m.group(1)) if m else None})
        elif _DOWELY.search(text):
            dowel_item.setdefault(p["sub"], {"id": p["id"], "qty": int(p["qty"])})
    for sb, c in cap_fast.items():  # a sub-assembly whose only screws are the cap screws: they are its fasteners
        if sb not in fast_item:
            fast_item[sb] = c["id"]
            if c["m"]:
                fast_hint.setdefault(sb, c["m"])
    bm = brief_fastener(brief)
    if bm:  # an explicit size in the brief wins over the plan's hints and the span rule (the cap screws the plan
        for p in parts:  # names for the bearing caps keep their own size: ``cap_fast`` is read first there)
            fast_hint[p["sub"]] = bm

    def take_key(sub: str, size: tuple[float, float]) -> str | None:
        """The key item of ``sub`` one more keyed joint gets (one Toolbox size per item, at most its quantity), else
        None: the keyway is still cut, there is just no planned key piece for it. A key planned in another
        sub-assembly (Archie's "keyed shaft" group, the gear in its own) is taken when its own has none: the key goes
        where the keyway is, not into the parts bin (founder's run 2026-11-19)."""
        for own in (True, False):
            for e in key_pool:
                if (e["sub"] == sub or not own) and e["left"] > 0 and e["size"] in (None, size):
                    e["left"] -= 1
                    e["size"] = size
                    return str(e["id"])
        return None
    # quarter turns of part frames about +Z (Archie's ``rotate`` hint, or an edit at the ICD gate)
    for p in designed:
        r = (iov.get(p["id"]) or {}).get("rot", p.get("rotate"))
        try:
            rr = round(float(r or 0)) % 360
        except (TypeError, ValueError):
            rr = 0
        spec[p["id"]]["rot"] = rr if rr in ROTATIONS and spec[p["id"]]["role"] == "block" else 0
    # a shaft line: nothing prismatic to mount on, but shafts. They run horizontally (along +Y, the Phase 6 gearbox
    # convention) on their own bearings, parallel, at the centre distances of their gears.
    line = not any(spec[p["id"]]["role"] == "block" for p in designed) and \
        any(spec[p["id"]]["role"] == "shaft" for p in designed)
    line_sh = _line_order([p for p in designed if spec[p["id"]]["role"] == "shaft"]) if line else []
    line_brg: dict[str, list[tuple[str, int]]] = {}  # shaft -> its bearing pieces [(bearing item, designation)]
    if line:  # share the bearings out: two per shaft, its own sub-assembly's and same-named ("input bearing") first
        pool = [dict(b, left=b["qty"]) for b in bearing_all]
        for sh in line_sh:
            p, s = by_id[sh], spec[sh]
            cls = _line_class(p["name"])
            got: list[tuple[str, int]] = []
            for b in sorted(pool, key=lambda b: (by_id[b["id"]]["sub"] != p["sub"],
                                                 _line_class(by_id[b["id"]]["name"]) != cls, pool.index(b))):
                ov_d = (iov.get(sh) or {}).get("designation")
                des = bearing_for(s["d"], int(ov_d) if isinstance(ov_d, int | float) else b["designation"])
                while des is not None and b["left"] > 0 and len(got) < 2:
                    got.append((b["id"], des))
                    b["left"] -= 1
            if got:
                bd = BEARINGS[got[0][1]][0]
                if s["source"] == "assumed" and "d" not in (iov.get(sh) or {}):
                    s["d"] = bd  # an assumed shaft takes the bearing bore: one plain journal
                s["bearing"] = {"designation": got[0][1], "item": got[0][0], "journal": bd, "seats": len(got)}
                line_brg[sh] = got
    # a shaft sub-assembly (founder, 2026-11-19: "a spur gear mounted on a stepped shaft, locked with a key"): a shaft
    # line with no bearing anywhere in the plan is the shaft with what it carries, a normal deliverable. A stepped one
    # has a seat for its hubs and a larger step behind them: the shoulder the hub locates against.
    sub_line = line and not bearing_all
    stepped: dict[str, dict[str, float]] = {}  # shaft -> {"seat": Ø, "body": Ø, "source": ...}
    if sub_line:
        shaft_talk = " ".join(x for x in re.split(r"(?<=[.;!?])\s+|\n+", brief or "") if _SHAFTY.search(x))
        for sh in line_sh:
            p, s = by_id[sh], spec[sh]
            text = f"{p['name']} {p['description']}"
            if not (_STEPPED.search(text) or _STEPPED.search(shaft_talk)):
                continue
            ds = sorted(set(_diameters(p["description"])))
            riders = [q for q in designed if spec[q["id"]]["role"] in ("gear", "hub") and (
                len(line_sh) == 1 or str(q.get("mounts_on") or "").lower() == p["name"].lower())]
            bores = sorted({b for b in (_bore_hint(q["description"]) for q in riders) if b})
            if len(ds) >= 2 and ds[-1] > ds[0]:
                seat, body, src = ds[0], ds[-1], "plan"
            elif bores and bores[0] < float(s["d"]) - 1e-9:  # the hub's bore is the seat, the planned Ø the step
                seat, body, src = bores[0], float(s["d"]), "plan"
            else:
                seat = float(s["d"])
                body, src = shoulder_for(seat), "assumed"
            ob = (iov.get(sh) or {}).get("shoulder_d")
            if isinstance(ob, int | float) and not isinstance(ob, bool) and ob > seat:
                body, src = float(ob), "edited"
            s["d"] = seat
            if not float(s.get("length") or 0.0) and _worded(p["description"])[1]:  # "overall length 120 mm"
                s["length"] = float(_worded(p["description"])[1] or 0.0)
            stepped[sh] = {"seat": seat, "body": body, "source": src}
    # shafts in a sub-assembly with bearings run in bearing seats (62xx / 60xx from the Toolbox table)
    for p in designed:
        s = spec[p["id"]]
        b = bearing_item.get(p["sub"])
        if line or s["role"] != "shaft" or not b:
            continue
        ov_d = (iov.get(p["id"]) or {}).get("designation")
        want = int(ov_d) if isinstance(ov_d, int | float) else b["designation"]
        des = bearing_for(s["d"], want)
        if des is None:
            continue
        bd, _bD, _bB = BEARINGS[des]
        if s["source"] == "assumed" and "d" not in (iov.get(p["id"]) or {}):
            s["d"] = bd  # an assumed shaft takes the bearing bore: one plain journal
        s["bearing"] = {"designation": des, "item": b["id"], "journal": bd}
    shafts_per_sub = {sb: sum(1 for q in designed if q["sub"] == sb and spec[q["id"]].get("bearing")) for sb in subs}
    for p in designed:
        s = spec[p["id"]]
        if s.get("bearing") and not line:
            b = bearing_item[p["sub"]]
            s["bearing"]["seats"] = 2 if b["qty"] >= 2 * max(1, shafts_per_sub[p["sub"]]) else 1

    # ---- tree: parent of every designed item
    def area(i: str) -> float:
        s = spec[i]
        return s["L"] * s["W"] if s["role"] == "block" else 0.0

    sub_base: dict[str, str] = {}
    for sb in subs:
        mine = [p["id"] for p in designed if p["sub"] == sb]
        if not mine:
            continue
        blocks = [i for i in mine if spec[i]["role"] == "block"]
        shafts = [i for i in mine if spec[i]["role"] == "shaft"]
        sub_base[sb] = max(blocks, key=lambda i: (_base_rank(by_id[i]), area(i), -mine.index(i))) if blocks else             (shafts or mine)[0]
    bases = [sub_base[s] for s in subs if s in sub_base]
    block_bases = [b for b in bases if spec[b]["role"] == "block"]
    prog_base = max(block_bases, key=lambda i: (_base_rank(by_id[i]), area(i), -bases.index(i))) if block_bases else         (bases[0] if bases else None)
    names = {p["name"].lower(): p["id"] for p in designed}
    parent: dict[str, str | None] = {}
    notes: list[str] = []
    for p in designed:
        i = p["id"]
        r = spec[i]["role"]
        sb = sub_base.get(p["sub"])
        if i == prog_base:
            parent[i] = None
            continue
        want = names.get(str(p.get("mounts_on") or "").lower())
        if want and want != i and spec[want]["role"] in ("block", "shaft") and not (r == "block" and spec[want]["role"] == "shaft"):
            parent[i] = want
            continue
        own_block = sb if sb and spec[sb]["role"] == "block" and sb != i else prog_base
        if r in ("block", "shaft"):
            parent[i] = own_block if i != sb else prog_base
        else:  # hub / gear: on a shaft of its sub-assembly, else bolted to a block
            mine = [q["id"] for q in designed if q["sub"] == p["sub"] and spec[q["id"]]["role"] == "shaft"]
            shaft = mine[0] if mine else None
            if r == "gear" and len(mine) > 1:  # several shafts: the pinion on the input shaft, the wheel on the
                # output shaft... (as in a shaft line), so neighbouring shafts mesh instead of one carrying every gear
                sub_parts = [q for q in designed if q["sub"] == p["sub"]]
                shaft = _line_parents(sub_parts, spec, _line_order([by_id[x] for x in mine]), names).get(i) or shaft
            parent[i] = shaft or own_block
        if parent[i] is None or parent[i] == i:
            parent[i] = None
    # break cycles (a mounts_on hint pointing back down the tree)
    for i in list(parent):
        seen = {i}
        j = parent[i]
        while j is not None:
            if j in seen:
                parent[i] = prog_base if i != prog_base else None
                break
            seen.add(j)
            j = parent.get(j)
    # a rod / pin / axle hung on another shaft (Archie's ``mounts_on``) has nothing to fit on a shaft: it stands in a
    # bore of the block that carries that shaft (the nearest block up the tree), beside it, instead of lying loose
    rehung: list[str] = []
    for p in designed:
        i = p["id"]
        if spec[i]["role"] != "shaft" or not parent.get(i) or spec[parent[i]]["role"] != "shaft":  # type: ignore[index]
            continue
        j, seen = parent[i], {i}
        while j is not None and spec[j]["role"] != "block" and j not in seen:
            seen.add(j)
            j = parent.get(j)
        host = j if j is not None and spec[j]["role"] == "block" else (
            prog_base if prog_base and spec[prog_base]["role"] == "block" else None)
        if host:
            rehung.append(f"{p['name']} (planned on {by_id[parent[i]]['name']})")  # type: ignore[index]
            parent[i] = host
    if rehung:
        notes.append("A rod or pin can't be carried by another shaft: " + ", ".join(rehung) + " stand"
                     + ("s" if len(rehung) == 1 else "") + " in a bore of the block carrying that shaft instead.")
    if prog_base is None:
        return _empty(parts, spec), []
    layout = "block"
    if line:  # the program base (fixed) is the input shaft; gears and hubs ride on their shafts
        prog_base = line_sh[0]
        parent = _line_parents(designed, spec, line_sh, names)
        layout = "shaft_line"
    elif spec[prog_base]["role"] != "block":  # nothing to mount on: a row of parts, no interfaces
        notes.append("No prismatic part to mount the others on: the parts are laid out in a row without interfaces.")
        parent = {p["id"]: None for p in designed}
        layout = "row"
    kids: dict[str, list[str]] = {i: [] for i in spec}
    for p in designed:
        if parent.get(p["id"]):
            kids[parent[p["id"]]].append(p["id"])  # type: ignore[index]
    # a block carrying bearing seats is deep enough for them (top seat, bottom seat and 4 mm between)
    for i, s in spec.items():
        host = parent.get(i)
        if line:
            break  # shaft lines carry their bearings on the shaft journals (line_brg)
        if s.get("bearing") and (not host or spec[host]["role"] != "block" or by_id[host]["family"] == "sheet"):
            s.pop("bearing")  # bearings sit in a machined (or moulded) housing, not in a sheet or a loose part
            continue
        if s.get("bearing") and host and spec[host]["role"] == "block":
            _d, _D, B = BEARINGS[s["bearing"]["designation"]]
            need = s["bearing"]["seats"] * B + 4.0
            if "H" not in (iov.get(host) or {}):
                spec[host]["H"] = max(spec[host]["H"], need)
            elif spec[host]["H"] < need:
                s["bearing"]["seats"] = 1 if spec[host]["H"] >= B + 4.0 else 0
    for s in spec.values():
        if s.get("bearing") and not s["bearing"]["seats"]:
            s.pop("bearing")

    def ncopies(i: str) -> int:
        q = int(by_id[i]["qty"])
        if q > MAX_COPIES:
            notes.append(f"{by_id[i]['name']}: {q} off, {MAX_COPIES} laid out in the skeleton.")
        return min(q, MAX_COPIES)

    # which copy of its host each copy of a part sits on. On a host the plan sized: copy c on host copy c mod (host
    # copies), so four stub axles on two uprights are two per upright, not four on the first.
    hostc: dict[tuple[str, int], int] = {}
    # stacks on shafts: hubs / gears (every copy) in plan order, per shaft copy
    stk: dict[tuple[str, int], list[tuple[str, int]]] = {}
    for i, s in spec.items():
        if s["role"] == "shaft":
            ns = ncopies_quiet(by_id[i]) if s.get("planned") else 1  # spread over copies when the plan sized it
            for sc in range(ncopies_quiet(by_id[i])):
                stk[(i, sc)] = []
            for k in kids[i]:
                if spec[k]["role"] not in ("hub", "gear"):
                    continue
                for c in range(ncopies(k)):
                    stk[(i, c % ns)].append((k, c))
                    hostc[(k, c)] = c % ns
    stack: dict[str, list[tuple[str, int]]] = {i: stk[(i, 0)] for i, s in spec.items() if s["role"] == "shaft"}
    # hubs and gears on a shaft get its bore; a hub's OD must leave a rim (1 mm at least when the plan sized it)
    for (sh, _sc), st in stk.items():
        d = spec[sh]["d"]
        for k, _c in st:
            s = spec[k]
            s["bore"] = d
            if s["role"] == "hub" and not s.get("od_given"):
                s["OD"] = max(s["OD"], d + 2 * max(8.0, 0.5 * d))
            elif s["role"] == "hub" and "OD" not in (iov.get(k) or {}):
                s["OD"] = max(s["OD"], _r2(d + 2.0))
    for i, s in spec.items():
        if s["role"] == "gear":
            s["pitch"] = s["module"] * s["teeth"]

    def od(i: str) -> float:
        s = spec[i]
        return {"hub": s.get("OD", 0.0), "gear": s.get("pitch", 0.0), "shaft": s.get("d", 0.0)}.get(s["role"], 0.0)

    def height(i: str) -> float:
        s = spec[i]
        return {"hub": s.get("H", 0.0), "gear": s.get("b", 0.0)}.get(s["role"], 0.0)

    # stations on each block copy: [(item, copy)] for child blocks, shafts and hubs/gears bolted to the block. A
    # host that may become a gearbox housing (shafts in bearings) keeps every child on its first copy.
    rows_of: dict[tuple[str, int], list[tuple[str, int]]] = {}
    for i, s in spec.items():
        if s["role"] == "block":
            nh = ncopies_quiet(by_id[i])
            if not s.get("planned") or any(spec[k]["role"] == "shaft" and spec[k].get("bearing") for k in kids[i]):
                nh_d = 1  # unplanned hosts and possible gearbox housings keep every child on their first copy
            else:
                nh_d = nh
            for hc in range(nh):
                rows_of[(i, hc)] = []
            for k in kids[i]:
                for c in range(ncopies(k)):
                    rows_of[(i, c % nh_d)].append((k, c))
                    hostc[(k, c)] = c % nh_d
    stations: dict[str, list[tuple[str, int]]] = {i: rows_of[(i, 0)] for i, s in spec.items() if s["role"] == "block"}

    def copy_rows(i: str) -> list[list[tuple[str, int]]]:
        return [rows_of[(i, hc)] for hc in range(ncopies_quiet(by_id[i])) if (i, hc) in rows_of]

    def stack_w(sh: str) -> float:
        """The widest thing on a shaft above its host (the shaft, its hubs and gears), over its copies."""
        return max([spec[sh]["d"]] + [od(x) for (k, _sc), st in stk.items() if k == sh for x, _c in st])

    def first_gear(sh: str) -> str | None:
        return next((k for k, _c in stack.get(sh, []) if spec[k]["role"] == "gear"), None)

    def foot(st: tuple[str, int]) -> tuple[float, float]:
        """(along the row, across it) in the program frame."""
        k = st[0]
        s = spec[k]
        if s["role"] == "block":
            return (s["W"], s["L"]) if s.get("rot") in (90, 270) else (s["L"], s["W"])
        if s["role"] == "shaft":
            w = max(stack_w(k), BEARINGS[s["bearing"]["designation"]][1] + 2.0 if s.get("bearing") else 0.0)
            return w, w
        return od(k), od(k)

    def meshes(a: tuple[str, int], b: tuple[str, int]) -> tuple[str, str] | None:
        if spec[a[0]]["role"] != "shaft" or spec[b[0]]["role"] != "shaft" or a[0] == b[0]:
            return None
        ga, gb = first_gear(a[0]), first_gear(b[0])
        if not ga or not gb or abs(spec[ga]["module"] - spec[gb]["module"]) > 1e-9:
            return None
        if abs(stack_w(a[0]) - od(ga)) > 1e-9 or abs(stack_w(b[0]) - od(gb)) > 1e-9:
            return None  # something on a shaft is wider than its gear: no clean mesh in this layout
        return ga, gb

    def gap(a: float, b: float) -> float:
        """Space between neighbouring stations: 12 mm, or a tenth of the larger part (room for spanners)."""
        return max(GAP, 0.1 * max(a, b))

    def tip(i: str) -> float:
        """The diameter an item sweeps about its shaft: a gear's tip circle, a hub's OD, a shaft's Ø."""
        s = spec[i]
        return s["module"] * (s["teeth"] + 2) if s["role"] == "gear" else od(i)

    # ---- gearbox-like hosts (Phase 6): a block carrying two or more shafts in bearings whose gears mesh holds them
    # horizontally (part Z along program +Y) in its two side walls: a casing with a cavity open at the top, a bearing
    # seat in each wall, caps bolted over the seats on the outer wall faces (coaxial), the cover as a lid on top.
    housing: dict[str, dict[str, Any]] = {}
    for h in list(stations):
        row = stations[h]
        if by_id[h]["family"] == "sheet" or str((iov.get(h) or {}).get("layout") or "") == "row":
            continue
        if _PLATEY.search(by_id[h]["name"]) and not _HOUSINGY.search(by_id[h]["name"]):
            continue  # a plate Archie planned stays a plate: vertical shafts in bearing seats, the gears on top
        shafts_h = [st for st in row if spec[st[0]]["role"] == "shaft" and spec[st[0]].get("bearing")]
        if len(shafts_h) < 2 or not any(meshes(shafts_h[n - 1], shafts_h[n]) for n in range(1, len(shafts_h))):
            continue
        hm: dict[str, Any] = {"shafts": shafts_h, "rel": [], "r": [], "xs": [0.0]}
        for k, c in shafts_h:  # each stack along its shaft, about the mid-plane of its first gear (the mesh plane)
            st = stk.get((k, c), [])
            pre, tot, found = 0.0, 0.0, False
            for x, _xc in st:
                if not found and spec[x]["role"] == "gear":
                    pre, found = pre + height(x) / 2, True
                elif not found:
                    pre += height(x)
                tot += height(x)
            if not found:
                pre = tot / 2
            hm["rel"].append((-pre, tot - pre))
            hm["r"].append(max([spec[k]["d"] / 2] + [tip(x) / 2 for x, _xc in st]))
        D = [BEARINGS[spec[k]["bearing"]["designation"]][1] for k, _c in shafts_h]
        for n in range(1, len(shafts_h)):
            mesh = meshes(shafts_h[n - 1], shafts_h[n])
            dx = (od(mesh[0]) / 2 + od(mesh[1]) / 2) if mesh else max(hm["r"][n - 1] + hm["r"][n] + GAP,
                                                                      D[n - 1] / 2 + D[n] / 2 + 2 * GAP)
            hm["xs"].append(hm["xs"][-1] + dx)
        # caps over the seats, in seat order (shaft by shaft, -Y wall then +Y wall): every seat gets a cap the plan
        # has. An open cap (the shaft passes through it) goes over a seat on the side the shaft leaves the housing
        # (EXIT_SIDE), a blind cap over the other; "input" / "output" in a cap's name puts it on that shaft
        seats_at = [(n, side) for n, (k, _c) in enumerate(shafts_h)
                    for side in ((-1, 1) if spec[k]["bearing"]["seats"] >= 2 else (-1,))]
        cap_sts = [st for st in row if spec[st[0]]["role"] == "hub" and _CAPPY.search(by_id[st[0]]["name"])]
        caps: list[tuple[tuple[str, int], int, int]] = []
        cap_m = 0
        cap_item: str | None = None
        assign = _assign_caps(cap_sts, seats_at, [by_id[k]["name"] for k, _c in shafts_h], D, by_id) if cap_sts else []
        if assign:
            by_cap: dict[str, list[int]] = {}
            for j, st in assign:
                by_cap.setdefault(st[0], []).append(j)
            at_seat = {seats_at[j]: st[0] for j, st in assign}
            csub = by_id[cap_sts[0][0]]["sub"]
            cf = cap_fast.get(csub) or next(iter(cap_fast.values()), None)
            Dall = max(D[seats_at[j][0]] for j, _st in assign)
            want = int((cf or {}).get("m") or fast_hint.get(csub) or fastener_for(0.6 * Dall))
            for m in sorted((x for x in CLEARANCE if x <= max(want, 3)), reverse=True):
                lig = max(LIGAMENT, LIGAMENT_D * m)
                size: dict[str, tuple[float, float, float]] = {}  # cap item -> (seat Ø, PCD, OD)
                for ci, js in by_cap.items():
                    Dc = max(D[seats_at[j][0]] for j in js)
                    pcd = math.ceil(2 * (Dc + TAP_DRILL[m] + 2 * lig) - 1e-9) / 2
                    co = iov.get(ci) or {}
                    size[ci] = (Dc, pcd, float(co["OD"]) if "OD" in co else _r2(pcd + WASHER_OD[m]))
                fits = all(OD >= pcd + CLEARANCE[m] + 2.0 for _Dc, pcd, OD in size.values())
                for n in range(1, len(shafts_h)):  # neighbouring caps on one wall keep 1 mm apart
                    for sd in (-1, 1):
                        a, b = at_seat.get((n - 1, sd)), at_seat.get((n, sd))
                        if a and b and size[a][2] / 2 + size[b][2] / 2 + 1.0 > hm["xs"][n] - hm["xs"][n - 1] + 1e-9:
                            fits = False
                if not fits:
                    continue
                cap_m, cap_item = m, (cf or {}).get("id")
                for ci, (Dc, pcd, OD) in size.items():
                    cs, co = spec[ci], iov.get(ci) or {}
                    cs.update(OD=OD, od_given=True, pcd=_r2(pcd), cap_d=Dc)
                    if "H" not in co and cs["source"] == "assumed":
                        cs["H"] = float(round(max(8.0, 0.25 * Dc)))
                    through = [spec[shafts_h[seats_at[j][0]][0]]["d"] for j in by_cap[ci] if seats_at[j][1] == EXIT_SIDE]
                    if through and _cap_kind(by_id[ci]) != "blind":
                        cs["bore"] = _r2(max(through) + 2.0)  # the shaft passes through (the seal sits there)
                        cs["cap"] = "open"
                    else:
                        cs.pop("bore", None)  # a blind cap closes the bore
                        cs["cap"] = "blind"
                    # the recess over the turning inner ring and shaft end: the bearing's mean diameter (between
                    # the inner ring's OD and the outer ring's bore), so the cap bears on the outer ring only
                    cs["relief"] = _r2(max((BEARINGS[spec[shafts_h[seats_at[j][0]][0]]["bearing"]["designation"]][0]
                                            + D[seats_at[j][0]]) / 2 for j in by_cap[ci]))
                caps = sorted(((st, seats_at[j][0], seats_at[j][1]) for j, st in assign),
                              key=lambda x: seats_at.index((x[1], x[2])))
                if cf and cf.get("m") and m != cf["m"]:
                    notes.append(f"{by_id[cf['id']]['name']}: M{cf['m']} caps don't fit side by side at these shaft "
                                 f"centres; the caps take M{m} instead.")
                break
        if cap_sts and not caps:
            notes.append(f"{by_id[cap_sts[0][0]]['name']}: no cap fits over the bearing seats at these shaft "
                         "centres; laid out on the housing instead.")
        elif caps:
            lig = max(LIGAMENT, LIGAMENT_D * cap_m)
            notes.append("Bearing caps: " + "; ".join(
                f"{by_id[st[0]]['name']}{f' #{st[1] + 1}' if ncopies_quiet(by_id[st[0]]) > 1 else ''} "
                f"({spec[st[0]]['cap']}) over the {'+' if sd > 0 else '-'}Y seat of the "
                f"{by_id[shafts_h[n][0]]['name']}" for st, n, sd in caps)
                + f". Cap screws M{cap_m} in tapped holes (tap drill Ø{TAP_DRILL[cap_m]:g}) in the walls, on a PCD "
                f"of seat Ø + tap drill + 2 × {lig:g} mm: at least {lig:g} mm of wall between the seat and each "
                "tapped hole.")
            missing = [seats_at[j] for j in range(len(seats_at)) if seats_at[j] not in at_seat]
            if missing:
                notes.append(f"{len(missing)} bearing seat{'s' if len(missing) != 1 else ''} without a cap in the "
                             "plan (" + ", ".join(f"{'+' if sd > 0 else '-'}Y seat of the {by_id[shafts_h[n][0]]['name']}"
                                                  for n, sd in missing) + ").")
        hm.update(caps=caps, cap_m=cap_m, cap_item=cap_item, D=D)
        capped = {st for st, _n, _s in caps}
        rest = [st for st in row if st not in shafts_h and st not in capped]
        lid = next((k for k, kc in rest if kc == 0 and spec[k]["role"] == "block" and ncopies_quiet(by_id[k]) == 1
                    and _LIDDY.search(by_id[k]["name"])), None)
        hm["lid"] = lid
        # the casing is open at the top: only the lid sits there; anything else (caps that don't fit, plates) goes
        # beside the program for the engineer to place (no interface in this layout)
        rows_of[(h, 0)] = stations[h] = []
        spec[h]["rot"] = 0
        for k, c in shafts_h:
            spec[k]["ax"] = "y"
            for x, _xc in stk.get((k, c), []):
                spec[x]["ax"] = "y"
        for (ci_, _cc), _n, _s in caps:
            spec[ci_]["ax"] = "y"
        housing[h] = hm

    def size_housing(h: str) -> None:
        """Casing around the gear row: side walls carry the seats (and the cap screws), the cavity clears the stacks
        by CAV radially and CAV_Y axially, the floor is FLOOR thick, the lid's screws land in the rim."""
        hm, s, o = housing[h], spec[h], iov.get(h) or {}
        B = max(BEARINGS[spec[k]["bearing"]["designation"]][2] for k, _c in hm["shafts"])
        caps_od = max([spec[st[0]]["OD"] for st, _n, _s in hm["caps"]] or [0.0])
        t = max(B + SHOULDER, tap_depth(hm["cap_m"]) + 3.0 if hm["caps"] else 0.0, 12.0)
        half_in = max(max(-lo, hi) for lo, hi in hm["rel"]) + CAV_Y
        rmax, Dmax = max(hm["r"]), max(hm["D"])
        xs = hm["xs"]
        lo_x = min(x - r for x, r in zip(xs, hm["r"], strict=True)) - CAV
        hi_x = max(x + r for x, r in zip(xs, hm["r"], strict=True)) + CAV
        mid = (lo_x + hi_x) / 2
        above = max(CAV + rmax, caps_od / 2 + 2.0, Dmax / 2 + 3.0)
        below = max(FLOOR + CAV + rmax, caps_od / 2 + 2.0, Dmax / 2 + 3.0)
        for _ in range(2):  # the lid's screws (ISO 273 hole at 2 d from the edge) must land in the rim walls
            W = 2 * (half_in + t)
            lm = 0
            if hm["lid"]:
                lid_sub = by_id[hm["lid"]]["sub"]
                lm = int(fast_hint.get(lid_sub) or fastener_for(min(W, 2 * (max(hi_x - mid, mid - lo_x) + t))))
                lm = lm if lm in CLEARANCE else 6
                t = max(t, 2.5 * CLEARANCE[lm] + 1.5, tap_depth(lm) - 6.0)
        reach = max(max(abs(x - mid) + caps_od / 2 + 2.0, abs(x - mid) + Dmax / 2 + 3.0) for x in xs)
        need_L = 2 * max(hi_x - mid + t, mid - lo_x + t, reach)
        need_W = 2 * (half_in + t)
        need_H = above + below
        for k, need in (("L", need_L), ("W", need_W), ("H", need_H)):
            if k in o:
                continue  # frozen (ICD approved): the layout works inside it, problems() says if it can't
            s[k] = _r2(need) if s["source"] == "assumed" else _r2(max(float(s[k]), need))
            if k == "L" and s.get("row_len"):
                s[k] = max(s[k], _r2(s["row_len"]))
        hm.update(t=_r2(t), mid=mid, above=_r2(above + (s["H"] - need_H) / 2), half_in=_r2(s["W"] / 2 - t))
        hm["end_t"] = _r2(s["L"] / 2 - max(hi_x - mid, mid - lo_x))  # the end walls take what is left
        lid = hm["lid"]
        if lid:
            ls, lo_ = spec[lid], iov.get(lid) or {}
            ls["rot"] = 0
            if "L" not in lo_:
                ls["L"], ls["W"] = s["L"], s["W"]

    def joint_m(k: str) -> int:
        """The bolt size of a part bolted to its host before any ICD edit (the same rule as the interfaces below)."""
        if spec[k]["role"] == "block":
            span = min(foot((k, 0)))
            m = int(fast_hint.get(by_id[k]["sub"]) or fastener_for(span))
            return m if m in CLEARANCE else fastener_for(span)
        m = int(fast_hint.get(by_id[k]["sub"]) or fastener_for(od(k) * 0.6))
        return m if m in CLEARANCE else 5

    def pad(st: tuple[str, int], level: int, room: float) -> tuple[float, float]:
        """(along, across) the joint needs on its host, not the child's whole footprint: level 1 a comfortable bolt
        pad, level 2 the least that holds the joint (two bolts with their washers side by side, 1 mm of wall)."""
        k = st[0]
        s = spec[k]
        ca, cw = foot(st)
        if s["role"] == "block":
            m = joint_m(k)
            d, wod = CLEARANCE[m], WASHER_OD[m]
            least = wod + d + 2.0
            along = max(min(ca, 2 * max(2 * d, 6.0) + wod if level == 1 else least), least)
            return _r2(along), _r2(max(min(cw, room), d + 2.0))
        if s["role"] == "shaft":
            if level == 1:
                return ca, cw
            w = (BEARINGS[s["bearing"]["designation"]][1] if s.get("bearing") else s["d"]) + 2.0
            return _r2(w), _r2(w)
        D = od(k)
        if level == 1:
            return D, D
        m = joint_m(k)
        d, wod = CLEARANCE[m], WASHER_OD[m]
        pcd = max((s.get("bore") or 0) + 3 * d, wod / math.sin(math.pi / 4) + 0.01)
        w = _r2(min(D, pcd + d + 2.0))
        return w, w

    def row_length(row: list[tuple[str, int]]) -> float:
        length = 2 * MARGIN
        for n, st in enumerate(row):
            w = foot(st)[0]
            if n == 0:
                length += w
                continue
            prev = row[n - 1]
            mesh = meshes(prev, st)
            length += (od(mesh[0]) / 2 + od(mesh[1]) / 2 - foot(prev)[0] / 2 - w / 2 + w) if mesh else \
                gap(foot(prev)[0], w) + w
        return length

    # sizes bottom-up. A block the plan didn't size grows to carry its row of children side by side. A block the
    # plan sized keeps its size when it can't take them in a row: each child then needs only its joint's pad (the
    # bolts and their washers), the children may overhang it and each other, and the block grows only as far as the
    # pads need (CD-029; problems() flags anything beyond PLAN_SLACK x the plan).
    slot_of: dict[tuple[str, int], tuple[str, int]] = {}  # station -> its slot on the host (shared by host copies)

    def key_row(i: str) -> list[tuple[str, int]]:
        """One station per slot on block i, in row order. The n-th copy of a part on any copy of i takes the same
        slot, so every copy of the host carries the same holes (one design serves them all)."""
        reps: dict[tuple[str, int], tuple[str, int]] = {}
        for row in copy_rows(i):
            seen: dict[str, int] = {}
            for k, c in row:
                j = seen.get(k, 0)
                seen[k] = j + 1
                slot_of[(k, c)] = (k, j)
                reps.setdefault((k, j), (k, c))
        return list(reps.values())

    def size_block(i: str) -> None:
        row = key_row(i)
        for k, _c in row:
            if spec[k]["role"] == "block":
                size_block(k)
        if i in housing and housing[i]["lid"]:
            size_block(housing[i]["lid"])
        if not row:
            if i in housing:
                size_housing(i)
            return
        s = spec[i]
        along, across = ("W", "L") if s.get("rot") in (90, 270) else ("L", "W")
        frozen = "L" in (iov.get(i) or {})
        length = row_length(row)
        width = max(foot(st)[1] for st in row) + 2 * MARGIN
        meshy = any(meshes(row[n - 1], row[n]) for n in range(1, len(row)))
        room_a, room_c = float(s[along]), float(s[across])
        if s.get("planned") and not meshy and i not in housing and \
                (length > room_a + 1e-6 or width > room_c + 1e-6):
            pads: dict[tuple[str, int], tuple[float, float]] = {}
            need_a = need_c = 0.0
            for level in (1, 2):
                pads = {slot_of[st]: pad(st, level, room_c) for st in row}
                need_a = sum(v[0] for v in pads.values()) + PAD_GAP * (len(row) - 1)
                need_c = max(v[1] for v in pads.values())
                if need_a <= room_a + 1e-6:  # (the width a bolt needs grows the host at any level)
                    break
            if not frozen:
                s[along] = _r2(max(room_a, need_a))
                s[across] = _r2(max(room_c, need_c))
            A = float(s[along])
            w = [pads[slot_of[st]][0] for st in row]
            n = len(w)
            if n * (max(w) + PAD_GAP) <= A + 1e-6:  # spread evenly along the host
                offs = [_r2(-A / 2 + A * (j + 0.5) / n) for j in range(n)]
            else:
                x = -(sum(w) + PAD_GAP * (n - 1)) / 2
                offs = []
                for wj in w:
                    offs.append(_r2(x + wj / 2))
                    x += wj + PAD_GAP
            s["xoff"] = {slot_of[st]: off for st, off in zip(row, offs, strict=True)}
            s["pads"] = pads
            return
        if not frozen:
            s[along] = max(s[along], length)
            s[across] = max(s[across], width)
        s["row_len"] = length
        xoff: dict[tuple[str, int], float] = {}
        x, prev_x = -length / 2 + MARGIN, None
        for n, st in enumerate(row):
            w0 = foot(st)[0]
            mesh = meshes(row[n - 1], st) if n else None
            if mesh and prev_x is not None:
                cx_ = prev_x + od(mesh[0]) / 2 + od(mesh[1]) / 2
            else:
                cx_ = x + w0 / 2 if n == 0 else x + gap(foot(row[n - 1])[0], w0) + w0 / 2
            x = cx_ + w0 / 2
            prev_x = cx_
            xoff[slot_of[st]] = cx_
        s["xoff"] = xoff
        if i in housing:
            size_housing(i)

    if spec[prog_base]["role"] == "block":
        size_block(prog_base)
    for i, s in spec.items():  # blocks not reachable from the base (no parent): size their rows too
        if s["role"] == "block" and parent.get(i) is None and i != prog_base:
            size_block(i)

    # positions top-down
    at: dict[str, list[list[float] | None]] = {i: [None] * ncopies_quiet(by_id[i]) for i in spec}
    under: dict[tuple[str, int], tuple[str, int]] = {}   # what a hub / gear copy rests on
    eng: dict[tuple[str, int], float] = {}               # how far a shaft copy reaches into its host block

    def place_block(i: str, c: int, centre: list[float]) -> None:
        at[i][c] = centre
        s = spec[i]
        top, bottom = centre[2] + s["H"] / 2, centre[2] - s["H"] / 2
        if c == 0 and i in housing:
            place_housing(i, centre)
        for k, kc in rows_of.get((i, c)) or []:
            cx_ = centre[0] + s["xoff"][slot_of[(k, kc)]]
            ks = spec[k]
            if ks["role"] == "block":
                place_block(k, kc, [cx_, centre[1], top + ks["H"] / 2])
            elif ks["role"] == "shaft":
                place_shaft(k, kc, cx_, centre[1], top, bottom, (i, c))
            else:
                at[k][kc] = [cx_, centre[1], top + height(k) / 2]
                under[(k, kc)] = (i, c)

    def place_housing(h: str, centre: list[float]) -> None:
        """Shafts along +Y from the -Y outer wall face (flush) out through the +Y wall and its cap; each stack with
        its first gear on the mesh plane Y = centre; caps on the outer wall faces, coaxial; the lid on top."""
        hm, s = housing[h], spec[h]
        cx, cy, cz = centre
        top = cz + s["H"] / 2
        za = top - hm["above"]
        y0 = cy - s["W"] / 2
        hm["za"], hm["y0"], hm["y1"] = za, y0, cy + s["W"] / 2
        cap_h = max([spec[st[0]]["H"] for st, _n, side in hm["caps"] if side > 0] or [0.0])
        for n, (k, c) in enumerate(hm["shafts"]):
            ks = spec[k]
            x = cx + hm["xs"][n] - hm["mid"]
            if "length" not in (iov.get(k) or {}):
                ks["length"] = _r2(max(ks.get("length") or 0.0, s["W"] + cap_h + max(15.0, ks["d"])))
            at[k][c] = [_r2(x), _r2(y0 + ks["length"] / 2), _r2(za)]
            y = cy + hm["rel"][n][0]
            below: tuple[str, int] | None = None
            for x_, xc in stk.get((k, c), []):
                at[x_][xc] = [_r2(x), _r2(y + height(x_) / 2), _r2(za)]
                if below is not None:
                    under[(x_, xc)] = below
                below = (x_, xc)
                y += height(x_)
        for (ci, cc), n, side in hm["caps"]:
            hc = spec[ci]["H"]
            yy = (y0 - hc / 2) if side < 0 else (hm["y1"] + hc / 2)
            at[ci][cc] = [_r2(cx + hm["xs"][n] - hm["mid"]), _r2(yy), _r2(za)]
        if hm["lid"]:
            place_block(hm["lid"], 0, [cx, cy, top + spec[hm["lid"]]["H"] / 2])

    def place_shaft(i: str, c: int, x: float, y: float, top: float, bottom: float, host: tuple[str, int]) -> None:
        """A shaft copy standing in its host block with its stack above. Unplanned: through the block, 15 mm above
        the stack (at least 40 long). Planned: its planned length, into the block as far as it reaches."""
        s = spec[i]
        st = stk.get((i, c), [])
        h_stack = sum(height(k) for k, _c in st)
        t = top - bottom
        planned = bool(s.get("planned")) and not s.get("bearing")
        if "length" not in (iov.get(i) or {}):
            h_max = max(sum(height(k) for k, _c in stk.get((i, cc), [])) for cc in range(len(at[i])))
            if planned:
                s["length"] = _r2(max(s["planned"][2], h_max + min(t, max(s["d"], 5.0))))
            else:
                s["length"] = max(s.get("length") or 0.0, t + h_max + 15.0, 40.0)
        e = max(0.0, min(t, s["length"] - h_stack)) if planned else t
        eng[(i, c)] = e
        at[i][c] = [x, y, top - e + s["length"] / 2]
        z = top
        below = host
        for k, kc in st:
            at[k][kc] = [x, y, z + height(k) / 2]
            under[(k, kc)] = below
            below = (k, kc)
            z += height(k)

    line_info: dict[str, Any] = {"xs": [], "brg": {}, "mesh": [], "seat": {}}

    def layout_line() -> float:
        """A shaft line: shafts along +Y at Z = 0 (datum A is the plane of the shaft axes), the input shaft on X = 0
        (datum C), each next shaft along +X at the centre distance of the gears it meshes with; every mesh coplanar,
        the first on Y = 0 (datum B), further gears of a compound shaft stacked along +Y; on each shaft two bearings,
        one either side of everything that turns near them (its own riders and the gears of other shafts that reach
        over its bearings), BEARING_CLEAR from them; the shaft SHAFT_END beyond its outer bearing faces (or longer
        when the plan says so). Returns the largest X the line reaches."""
        S = line_sh
        on = {sh: list(stk.get((sh, 0), [])) for sh in S}
        gears_on = {sh: [st for st in on[sh] if spec[st[0]]["role"] == "gear"] for sh in S}
        mesh: list[tuple[tuple[str, int], tuple[str, int]] | None] = []
        for j in range(len(S) - 1):  # a gear of shaft j not already meshing shaft j - 1, the first of shaft j + 1
            prev = mesh[-1][1] if mesh and mesh[-1] else None
            cand = [g for g in gears_on[S[j]] if g != prev] or gears_on[S[j]]
            mesh.append(next(((ga, gb) for ga in cand for gb in gears_on[S[j + 1]]
                              if abs(spec[ga[0]]["module"] - spec[gb[0]]["module"]) < 1e-9), None))

        def bD(sh: str) -> float:
            return max((BEARINGS[des][1] for _b, des in line_brg.get(sh, [])), default=0.0)

        def reach(sh: str) -> float:
            return max([spec[sh]["d"] / 2, bD(sh) / 2] + [tip(k) / 2 for k, _c in on[sh]])

        xs = [0.0]
        for j in range(1, len(S)):
            m = mesh[j - 1]
            xs.append(xs[-1] + (od(m[0][0]) / 2 + od(m[1][0]) / 2 if m else reach(S[j - 1]) + reach(S[j]) + GAP))
        y: dict[tuple[str, int], float] = {}
        for j, sh in enumerate(S):
            first = mesh[j - 1][1] if j and mesh[j - 1] else None
            nxt = mesh[j][0] if j < len(S) - 1 and mesh[j] else None
            seq = list(dict.fromkeys([st for st in (first, nxt) if st] + on[sh]))
            hi: float | None = None
            for n, st in enumerate(seq):
                h = height(st[0])
                if st == first:
                    y[st] = y[mesh[j - 1][0]]  # type: ignore[index]
                elif hi is None:
                    y[st] = 0.0
                else:
                    both = spec[st[0]]["role"] == "gear" and spec[seq[n - 1][0]]["role"] == "gear"
                    y[st] = hi + (GEAR_SPACE if both else 0.0) + h / 2
                hi = y[st] + h / 2 if hi is None else max(hi, y[st] + h / 2)
        for j, sh in enumerate(S):
            s = spec[sh]
            own = [(y[st] - height(st[0]) / 2, y[st] + height(st[0]) / 2) for st in on[sh]]
            near = [(y[st] - height(st[0]) / 2, y[st] + height(st[0]) / 2) for k, o in enumerate(S) if k != j
                    for st in on[o] if abs(xs[k] - xs[j]) < tip(st[0]) / 2 + max(bD(sh), s["d"]) / 2 + 1.0]
            spans = own + near
            lo = min((a for a, _b in spans), default=0.0)
            hi_ = max((b for _a, b in spans), default=0.0)
            pieces = line_brg.get(sh, [])
            brg: list[tuple[int, float, float, tuple[str, int]]] = []
            if pieces:
                B0 = BEARINGS[pieces[0][1]][2]
                brg.append((-1, lo - BEARING_CLEAR - B0, lo - BEARING_CLEAR, pieces[0]))
            if len(pieces) > 1:
                brg.append((1, hi_ + BEARING_CLEAR, hi_ + BEARING_CLEAR + BEARINGS[pieces[1][1]][2], pieces[1]))
            end = max(SHAFT_END, 0.5 * s["d"])
            y0 = min([b0 for _s, b0, _b1, _p in brg] + [a for a, _b in own] + [0.0]) - end
            y1 = max([b1 for _s, _b0, b1, _p in brg] + [b for _a, b in own] + [0.0]) + end
            dy = 0.0
            if sh in stepped and own and not brg:
                # a stepped shaft in a sub-assembly: the hubs sit on the seat (Ø seat) from SEAT_END beyond the
                # free hub face to the shoulder; the larger step (the body) runs on from the shoulder. One shaft on
                # its own: the shoulder face is datum B (Y = 0), the hubs on its -Y side.
                olo, ohi = min(a for a, _b in own), max(b for _a, b in own)
                y0 = olo - SEAT_END
                need = ohi - y0 + 1.0
                body_l = max(ohi - olo + SHAFT_END, 2.0 * stepped[sh]["seat"])
                L = max(float(s.get("length") or 0.0), need) if float(s.get("length") or 0.0) > 0 \
                    else (ohi - y0) + body_l
                y1 = y0 + L
                if len(S) == 1:
                    dy = -ohi
                s["length"] = _r2(L)
                line_info["seat"][sh] = {"z": [_r2(y0 + dy), _r2(ohi + dy)], "shoulder_z": _r2(ohi + dy),
                                         "seat": stepped[sh]["seat"], "body": stepped[sh]["body"], "side": 1,
                                         "source": stepped[sh]["source"]}
            elif "length" not in (iov.get(sh) or {}):
                s["length"] = _r2(max(y1 - y0, float(s.get("length") or 0.0)))
            at[sh][0] = [_r2(xs[j]), _r2((y0 + y1) / 2 + dy), 0.0]
            s["ax"] = "y"
            for st in on[sh]:
                at[st[0]][st[1]] = [_r2(xs[j]), _r2(y[st] + dy), 0.0]
                spec[st[0]]["ax"] = "y"
            line_info["brg"][sh] = [(sd, _r2(b0), _r2(b1), p) for sd, b0, b1, p in brg]
        line_info.update(xs=xs, mesh=mesh)
        return xs[-1] + reach(S[-1]) if S else 0.0

    if spec[prog_base]["role"] == "block":
        place_block(prog_base, 0, [0.0, 0.0, -spec[prog_base]["H"] / 2])
    env_x = spec[prog_base]["L"] / 2 if spec[prog_base]["role"] == "block" else -3 * GAP
    if line:
        env_x = layout_line()
    # anything not placed (no path to the base): a row beside the program base, no interfaces
    loose_x = env_x + 3 * GAP
    for p in designed:
        i = p["id"]
        for c in range(len(at[i])):
            if at[i][c] is None:
                w = foot((i, c))[0]
                h = spec[i]["H"] if spec[i]["role"] == "block" else (spec[i].get("length") or height(i) or 20.0)
                if spec[i]["role"] == "shaft" and not spec[i].get("length"):
                    spec[i]["length"] = max(40.0, h)
                    h = spec[i]["length"]
                at[i][c] = [loose_x + w / 2, 0.0, h / 2]
                loose_x += w + GAP
                if c == 0:
                    notes.append(f"{p['name']} has no interface in this layout: placed beside the program, mate it "
                                 "by hand.")

    # ---- interfaces
    ifs: list[dict[str, Any]] = []

    def add(kind: str, a: tuple[str, int], b: tuple[str, int], data: dict[str, Any], datums: list[str],
            label: str | None = None) -> dict[str, Any]:
        iid = f"IF-{len(ifs) + 1:02d}"
        o = fov.get(iid) or {}
        def copies(i: str) -> int:  # a standard part (a bearing on a journal) is not in the skeleton: its qty
            return len(at[i]) if i in at else int(by_id[i]["qty"])

        na = by_id[a[0]]["name"] + (f" #{a[1] + 1}" if copies(a[0]) > 1 else "")
        nb = by_id[b[0]]["name"] + (f" #{b[1] + 1}" if copies(b[0]) > 1 else "")
        f = {"id": iid, "kind": kind, "name": f"{nb} ↔ {na}: {label or KIND_LABEL[kind]}",
             "a": {"item": a[0], "copy": a[1], "name": na}, "b": {"item": b[0], "copy": b[1], "name": nb},
             "datums": datums, "data": data, "edited": sorted(o)}
        for w, i in (("a", a[0]), ("b", b[0])):
            if i not in at:
                f[w]["standard"] = True
        ifs.append(f)
        return f

    def bolt_size(sub: str, span: float, o: dict[str, Any]) -> int:
        m = int(o.get("fastener") or fast_hint.get(sub) or fastener_for(span))
        return m if m in CLEARANCE else fastener_for(span)

    def grid(cxy: list[float], L: float, W: float, d: float, count: int, inset: float) -> list[list[float]]:
        ex, ey = L / 2 - inset, W / 2 - inset
        if count == 2 and W > L:  # two bolts along the longer side of the joint
            return [[_r2(cxy[0]), _r2(cxy[1] - ey)], [_r2(cxy[0]), _r2(cxy[1] + ey)]]
        if count == 2:
            return [[_r2(cxy[0] - ex), _r2(cxy[1])], [_r2(cxy[0] + ex), _r2(cxy[1])]]
        if count >= 6:
            return [[_r2(cxy[0] + sx), _r2(cxy[1] + sy)] for sy in (-ey, ey) for sx in (-ex, 0.0, ex)]
        return [[_r2(cxy[0] + sx), _r2(cxy[1] + sy)] for sy in (-ey, ey) for sx in (-ex, ex)]

    def circle(cxy: list[float], pcd: float, count: int) -> list[list[float]]:
        return [[_r2(cxy[0] + pcd / 2 * math.cos(2 * math.pi * k / count + math.pi / count)),
                 _r2(cxy[1] + pcd / 2 * math.sin(2 * math.pi * k / count + math.pi / count))] for k in range(count)]

    order: list[tuple[str, int]] = []

    def walk(i: str, hc: int = 0) -> None:
        hm = housing.get(i) if hc == 0 else None
        if hm and hm["lid"]:
            order.append((hm["lid"], 0))
            walk(hm["lid"])
        for k, c in rows_of.get((i, hc), []):
            order.append((k, c))
            if spec[k]["role"] == "block":
                walk(k, c)
            if spec[k]["role"] == "shaft":
                order.extend(stk.get((k, c), []))
        if hm:
            for k, c in hm["shafts"]:
                order.append((k, c))
                order.extend(stk.get((k, c), []))
            order.extend(st for st, _n, _s in hm["caps"])

    walk(prog_base)
    dowels_left = {sb: d["qty"] // 2 for sb, d in dowel_item.items()}  # two pins per joint

    def dowel_points(cxy: list[float], Lp: float, Wp: float, pts: list[list[float]], d: float, dd: float,
                     inset: float) -> list[list[float]] | None:
        """Two dowel positions on the joint, clear of the bolt holes and inside the part (or None)."""
        ex, ey = Lp / 2 - inset, Wp / 2 - inset
        cands = [[(cxy[0] - ex, cxy[1]), (cxy[0] + ex, cxy[1])],
                 [(cxy[0] - ex / 2, cxy[1]), (cxy[0] + ex / 2, cxy[1])],
                 [(cxy[0], cxy[1] - ey), (cxy[0], cxy[1] + ey)],
                 [(cxy[0] - ex / 2, cxy[1] - ey), (cxy[0] + ex / 2, cxy[1] + ey)]]
        for cand in cands:
            if math.hypot(cand[0][0] - cand[1][0], cand[0][1] - cand[1][1]) < 2 * dd:
                continue
            clear = all(math.hypot(q[0] - h[0], q[1] - h[1]) >= (d + dd) / 2 + 1.0 for q in cand for h in pts)
            inside = all(abs(q[0] - cxy[0]) + dd / 2 <= Lp / 2 - 1.0 and abs(q[1] - cxy[1]) + dd / 2 <= Wp / 2 - 1.0
                         for q in cand)
            if clear and inside:
                return [[_r2(q[0]), _r2(q[1])] for q in cand]
        return None

    # holes already in each part (Z axis, part frame up to the copy's turn): new bolt patterns keep 1 mm clear of
    # them. Shaft bores and bearing seats in blocks are known from the placement, so they go in first.
    holes_reg: dict[str, list[tuple[float, float, float]]] = {}

    def reg(item: str, cp: int, pts: list[list[float]], d: float) -> None:
        c0 = at[item][cp]
        assert c0 is not None
        holes_reg.setdefault(item, []).extend((x - c0[0], y - c0[1], d) for x, y in pts)

    def clash(item: str, cp: int, pts: list[list[float]], d: float) -> bool:
        c0 = at[item][cp]
        assert c0 is not None
        for x, y in pts:
            lx, ly = x - c0[0], y - c0[1]
            for rx, ry, rd in holes_reg.get(item, []):
                if _near(lx, rx) and _near(ly, ry):
                    continue  # concentric: one bolt through both
                if math.hypot(lx - rx, ly - ry) - (d + rd) / 2 < 1.0:
                    return True
        return False

    for k, c in order:
        host = parent.get(k)
        if host is None or spec[k]["role"] != "shaft" or host in housing or spec[host]["role"] != "block":
            continue
        pos0 = at[k][c]
        assert pos0 is not None
        br = spec[k].get("bearing")
        reg(host, hostc.get((k, c), 0), [[pos0[0], pos0[1]]],
            BEARINGS[br["designation"]][1] if br else spec[k]["d"])

    def pattern2(cxy: list[float], Lp: float, Wp: float, inset: float, along_x: bool, off: float
                 ) -> list[list[float]]:
        """Two holes on a line along X (or Y), ``inset`` from the ends of the joint, ``off`` across it."""
        if along_x:
            ex = Lp / 2 - inset
            return [[_r2(cxy[0] - ex), _r2(cxy[1] + off)], [_r2(cxy[0] + ex), _r2(cxy[1] + off)]]
        ey = Wp / 2 - inset
        return [[_r2(cxy[0] + off), _r2(cxy[1] - ey)], [_r2(cxy[0] + off), _r2(cxy[1] + ey)]]

    def grow_foot(k: str, along: float, across: float) -> None:
        """A block grows (program X / Y) to hold its own joint; sizes the engineer set or froze stay."""
        s, o = spec[k], iov.get(k) or {}
        kx, ky = ("W", "L") if s.get("rot") in (90, 270) else ("L", "W")
        for key, need in ((kx, along), (ky, across)):
            if key not in o and float(s[key]) < need - 1e-9:
                s[key] = _r2(need)

    for k, c in order:
        ks = spec[k]
        p = by_id[k]
        host = parent.get(k)
        if host is None:
            continue
        hs = spec[host]
        hc = hostc.get((k, c), 0)  # the copy of the host this copy sits on
        pos = at[k][c]
        assert pos is not None
        n_if = len(ifs) + 1
        o = fov.get(f"IF-{n_if:02d}") or {}
        if ks["role"] == "block":
            top = pos[2] - ks["H"] / 2
            Lc, Wc = foot((k, c))
            # the joint's pad on a crowded planned host, else the child's whole footprint
            Lp, Wp = (hs.get("pads") or {}).get(slot_of.get((k, c), ("", -1))) or (Lc, Wc)
            m = bolt_size(p["sub"], min(Lc, Wc), o)
            d = float(o.get("d") or CLEARANCE[m])
            inset_pref = max(2 * d, 6.0)
            inset = float(o.get("inset") or inset_pref)
            wod = WASHER_OD.get(max(m, bolt_for_hole(d)), 2 * d)
            # the part holds its own joint: two bolts with their washers side by side along its longer side, 1 mm of
            # wall around every hole. It grows that far for them (its own features), never to fit anything else.
            lng, shr = wod + d + 2.0, d + 2.0
            need_x, need_y = (lng, shr) if Lp >= Wp else (shr, lng)
            grow_foot(k, need_x, need_y)
            Lp, Wp = _r2(max(Lp, need_x)), _r2(max(Wp, need_y))
            # two rows only when the washers of neighbouring bolts fit side by side (the ICD's own rule)
            count = int(o.get("count") or (4 if min(Lp, Wp) - 2 * inset >= wod
                                           and max(Lp, Wp) - 2 * inset >= wod else 2))
            pts = grid(pos, Lp, Wp, d, count, inset)
            if count == 2 and not o.get("inset"):  # a short joint: the bolts move in until the washers just clear
                inset = _r2(max(min(inset_pref, (max(Lp, Wp) - wod) / 2), d / 2 + 1.0))
                pts = grid(pos, Lp, Wp, d, count, inset)
            if clash(host, hc, pts, d) or clash(k, c, pts, d):
                # clear of the holes already in either part: two bolts, moved along and across the joint (the
                # search is deterministic, so frozen count and inset find the same holes again)
                cands: list[tuple[float, list[list[float]]]] = []
                for along_x in ((Lp >= Wp, Lp < Wp) if not o.get("count") or count == 2 else ()):
                    ln, wd = (Lp, Wp) if along_x else (Wp, Lp)
                    if ln - wod < d + 2.0 - 1e-9:
                        continue
                    hi = min(inset_pref, (ln - wod) / 2)
                    lo = d / 2 + 1.0
                    ins = [float(o["inset"])] if o.get("inset") else \
                        list(dict.fromkeys(_r2(hi - (hi - lo) * t / 4) for t in range(5)))
                    om = max(0.0, wd / 2 - d / 2 - 1.0)
                    for off in dict.fromkeys((0.0, _r2(om / 2), _r2(-om / 2), _r2(om), _r2(-om))):
                        cands += [(x, pattern2(pos, Lp, Wp, x, along_x, off)) for x in ins]
                for x, q in cands:
                    if not clash(host, hc, q, d) and not clash(k, c, q, d):
                        count, inset, pts = 2, x, q
                        break
            tapped = {"d": TAP_DRILL[m], "depth": tap_depth(m), "thread": f"M{m}"} if host in housing else None
            joint = add("hole_pattern", (host, hc), (k, c), {
                "fastener": f"M{m}", "fastener_size": m, "fastener_item": fast_item.get(p["sub"]),
                "count": len(pts), "d": d, "pattern": "grid" if len(pts) > 2 else "linear", "inset": inset,
                "plane_z": _r2(top), "normal": [0, 0, 1], "positions": pts, "through": tapped is None,
                **({"tapped": tapped} if tapped else {}),
                "flatness": float(o.get("flatness") or FLATNESS), "position_tol": float(o.get("position_tol") or POS_TOL)},
                ["A", "B", "C"])
            reg(host, hc, pts, d)
            reg(k, c, pts, d)
            hsub = by_id[host]["sub"]
            dsub = p["sub"] if dowels_left.get(p["sub"]) else hsub if dowels_left.get(hsub) else None
            if dsub:
                o2 = fov.get(f"IF-{len(ifs) + 1:02d}") or {}
                dd = float(o2.get("d") or max(3, min(m, 16)))
                dp = dowel_points(pos, Lp, Wp, pts, d, dd, inset)
                if dp and (clash(host, hc, dp, dd) or clash(k, c, dp, dd)):
                    dp = None
                if dp:
                    dowels_left[dsub] -= 1
                    reg(host, hc, dp, dd)
                    reg(k, c, dp, dd)
                    add("dowel", (host, hc), (k, c), {
                        "d": dd, "fit": "H7/m6", "count": 2, "positions": dp, "plane_z": _r2(top),
                        "length": dowel_length(min(3 * dd, ks["H"] + hs["H"] - 2)), "pin_item": dowel_item[dsub]["id"],
                        "joint": joint["id"], "standard": "ISO 8734", "position_tol": POS_TOL}, ["A", "B", "C"],
                        "dowel pins (ISO 8734)")
                else:
                    notes.append(f"{p['name']}: no room for two dowel pins clear of the bolts; located by the bolts.")
        elif ks["role"] == "shaft" and host in housing:
            hm = housing[host]
            br = ks["bearing"]
            des = br["designation"]
            bd, bD, bB = BEARINGS[des]
            hf = str(o.get("housing_fit") or "H7")
            y0, y1 = hm["y0"], hm["y1"]
            seats = [{"face": "+Y wall", "open": 1, "z": [_r2(y1 - bB), _r2(y1)]}] if br["seats"] >= 2 else []
            seats.append({"face": "-Y wall", "open": -1, "z": [_r2(y0), _r2(y0 + bB)]})
            n_s = len(seats)
            add("bearing_seat", (host, hc), (k, c), {
                "designation": str(des), "bearing": f"Deep-groove ball bearing {des}", "d": bd, "D": bD, "B": bB,
                "housing_fit": hf if hf in HOUSING_FITS else "H7", "shaft_fit": SHAFT_FIT_BEARING, "ax": "y",
                "axis": [_r2(pos[0]), _r2(pos[2])], "z": [_r2(y0), _r2(y1)], "seats": seats,
                "clearance_d": _r2(bd + 2), "flush_z": _r2(y0), "bearing_item": br["item"], "shaft_d": ks["d"],
                "count": n_s, "r_s_min": _BEARING_RS[int(des)], "standard": "ISO 15 (Toolbox table)", "position_tol": POS_TOL},
                ["A", "B", "C"], f"shaft in {n_s} bearing{'s' if n_s != 1 else ''} {des} (side walls)")
        elif ks["role"] == "shaft":
            top, bottom = at[host][hc][2] + hs["H"] / 2, at[host][hc][2] - hs["H"] / 2  # type: ignore[index]
            br = ks.get("bearing")
            if br and hs["role"] == "block":
                des = br["designation"]
                bd, bD, bB = BEARINGS[des]
                hf = str(o.get("housing_fit") or "H7")
                seats = [{"face": "top", "z": [_r2(top - bB), _r2(top)]}]
                if br["seats"] >= 2:
                    seats.append({"face": "bottom", "z": [_r2(bottom), _r2(bottom + bB)]})
                n_s = len(seats)
                add("bearing_seat", (host, hc), (k, c), {
                    "designation": str(des), "bearing": f"Deep-groove ball bearing {des}", "d": bd, "D": bD, "B": bB,
                    "housing_fit": hf if hf in HOUSING_FITS else "H7", "shaft_fit": SHAFT_FIT_BEARING,
                    "axis": [_r2(pos[0]), _r2(pos[1])], "z": [_r2(bottom), _r2(top)], "seats": seats,
                    "clearance_d": _r2(bd + 2), "flush_z": _r2(bottom), "bearing_item": br["item"], "shaft_d": ks["d"],
                    "count": n_s, "r_s_min": _BEARING_RS[int(des)], "standard": "ISO 15 (Toolbox table)", "position_tol": POS_TOL},
                    ["A", "B", "C"], f"shaft in {n_s} bearing{'s' if n_s != 1 else ''} {des}")
            else:
                fit = str(o.get("fit") or "H7/h6")
                e = eng.get((k, c), top - bottom)
                through = e >= top - bottom - 1e-9  # a planned short shaft reaches only part way in
                add("shaft_bore", (host, hc), (k, c), {
                    "d": ks["d"], "fit": fit if fit in FITS else "H7/h6", "length": _r2(e),
                    "axis": [_r2(pos[0]), _r2(pos[1])], "z": [_r2(top - e), _r2(top)],
                    "flush_z": _r2(bottom) if through else None,
                    "position_tol": POS_TOL}, ["A", "B", "C"], "shaft through bore" if through else "shaft in bore")
        elif hs["role"] == "shaft" and hs.get("ax") == "y":  # hub / gear on a shaft along +Y (gearbox housing)
            bottom = pos[1] - height(k) / 2
            fit = str(o.get("fit") or "H7/k6")
            a2 = [_r2(pos[0]), _r2(pos[2])]
            add("shaft_bore", (k, c), (host, hc), {
                "d": hs["d"], "fit": fit if fit in FITS else "H7/k6", "length": _r2(height(k)), "ax": "y",
                "axis": a2, "z": [_r2(bottom), _r2(bottom + height(k))], "flush_z": None,
                "position_tol": POS_TOL}, ["A", "B", "C"], "bore on shaft")
            key = key_for(hs["d"])
            keyed = _KEYY.search(f"{p['name']} {p['description']}") or key_item.get(p["sub"])
            if key and keyed and height(k) >= key[0] + 3:
                o2 = fov.get(f"IF-{len(ifs) + 1:02d}") or {}
                kb, kh, t1, t2 = key
                kl = float(o2.get("length") or math.floor(max(kb + 2, height(k) - 2)))
                kl = min(kl, float(math.floor(height(k))))
                z0 = bottom + (height(k) - kl) / 2
                add("key", (k, c), (host, hc), {
                    "d": hs["d"], "b": kb, "h": kh, "t1": t1, "t2": t2, "length": kl, "ax": "y",
                    "axis": a2, "dir": [1, 0], "z": [_r2(z0), _r2(z0 + kl)],
                    "hub_z": [_r2(bottom), _r2(bottom + height(k))], "key_item": take_key(p["sub"], (float(hs["d"]), kl)),
                    "standard": "DIN 6885-1 A", "position_tol": POS_TOL}, ["A", "B", "C"],
                    f"parallel key {kb:g} x {kh:g} x {kl:g}")
            below = under.get((k, c))
            if below is not None:
                o2 = fov.get(f"IF-{len(ifs) + 1:02d}") or {}
                add("face", below, (k, c), {"plane_z": _r2(bottom), "normal": [0, 1, 0], "ax": "y",
                                            "flatness": float(o2.get("flatness") or FLATNESS),
                                            "position_tol": float(o2.get("position_tol") or POS_TOL)}, ["A"])
        elif host in housing and any(st == (k, c) for st, _n, _s in housing[host]["caps"]):  # a cap over a seat
            hm = housing[host]
            _st, _n, side = next(x for x in hm["caps"] if x[0] == (k, c))
            m = int(o.get("fastener") or hm["cap_m"])
            m = m if m in CLEARANCE else hm["cap_m"]
            d = float(o.get("d") or CLEARANCE[m])
            count = int(o.get("count") or 4)
            pcd = _r2(ks["pcd"])
            plane = hm["y0"] if side < 0 else hm["y1"]
            a2 = [_r2(pos[0]), _r2(pos[2])]
            sh_k = hm["shafts"][_n][0]
            des = spec[sh_k]["bearing"]["designation"]
            add("hole_pattern", (host, 0), (k, c), {
                "fastener": f"M{m}", "fastener_size": m, "fastener_item": hm.get("cap_item") or fast_item.get(p["sub"]),
                "count": count, "d": d, "pattern": "circular", "pcd": pcd, "centre": a2, "ax": "y",
                "plane_z": _r2(plane), "normal": [0, side, 0], "positions": circle(a2, pcd, count), "through": False,
                "tapped": {"d": TAP_DRILL[m], "depth": tap_depth(m), "thread": f"M{m}"},
                "cap": ks.get("cap") or "open", "seat_D": BEARINGS[des][1], "bearing": str(des),
                "relief": {"d": ks["relief"], "depth": CAP_RELIEF} if ks.get("relief") else None,
                "flatness": float(o.get("flatness") or FLATNESS), "position_tol": float(o.get("position_tol") or POS_TOL)},
                ["A", "B", "C"], f"{ks.get('cap') or 'open'} bearing cap over the {'+' if side > 0 else '-'}Y seat")
        else:  # hub / gear
            bottom = pos[2] - height(k) / 2
            if hs["role"] == "shaft":
                fit = str(o.get("fit") or "H7/k6")
                add("shaft_bore", (k, c), (host, hc), {
                    "d": hs["d"], "fit": fit if fit in FITS else "H7/k6", "length": _r2(height(k)),
                    "axis": [_r2(pos[0]), _r2(pos[1])], "z": [_r2(bottom), _r2(bottom + height(k))], "flush_z": None,
                    "position_tol": POS_TOL}, ["A", "B", "C"], "bore on shaft")
                key = key_for(hs["d"])
                keyed = _KEYY.search(f"{p['name']} {p['description']}") or key_item.get(p["sub"])
                if key and keyed and height(k) >= key[0] + 3:
                    o2 = fov.get(f"IF-{len(ifs) + 1:02d}") or {}
                    kb, kh, t1, t2 = key
                    kl = float(o2.get("length") or math.floor(max(kb + 2, height(k) - 2)))
                    kl = min(kl, float(math.floor(height(k))))
                    z0 = bottom + (height(k) - kl) / 2
                    add("key", (k, c), (host, hc), {
                        "d": hs["d"], "b": kb, "h": kh, "t1": t1, "t2": t2, "length": kl,
                        "axis": [_r2(pos[0]), _r2(pos[1])], "dir": [1, 0], "z": [_r2(z0), _r2(z0 + kl)],
                        "hub_z": [_r2(bottom), _r2(bottom + height(k))], "key_item": take_key(p["sub"], (float(hs["d"]), kl)),
                        "standard": "DIN 6885-1 A", "position_tol": POS_TOL}, ["A", "B", "C"],
                        f"parallel key {kb:g} x {kh:g} x {kl:g}")
                below = under.get((k, c))
                if below is not None:
                    o2 = fov.get(f"IF-{len(ifs) + 1:02d}") or {}
                    add("face", below, (k, c), {"plane_z": _r2(bottom), "normal": [0, 0, 1],
                                                "flatness": float(o2.get("flatness") or FLATNESS),
                                                "position_tol": float(o2.get("position_tol") or POS_TOL)}, ["A"])
            else:  # bolted to a block on a bolt circle
                D = od(k)
                m = int(o.get("fastener") or fast_hint.get(p["sub"]) or fastener_for(D * 0.6))
                m = m if m in CLEARANCE else 5
                d = float(o.get("d") or CLEARANCE[m])
                count = int(o.get("count") or 4)
                wod = WASHER_OD.get(max(m, bolt_for_hole(d)), 2 * d)
                pd = (hs.get("pads") or {}).get(slot_of.get((k, c), ("", -1)))
                pcd = _r2(max(min(0.65 * D, pd[0] - d - 2.0) if pd else 0.65 * D, (ks.get("bore") or 0) + 3 * d,
                              wod / math.sin(math.pi / count) + 0.01))
                add("hole_pattern", (host, hc), (k, c), {
                    "fastener": f"M{m}", "fastener_size": m, "fastener_item": fast_item.get(p["sub"]),
                    "count": count, "d": d, "pattern": "circular", "pcd": pcd, "centre": [_r2(pos[0]), _r2(pos[1])],
                    "plane_z": _r2(bottom), "normal": [0, 0, 1], "positions": circle(pos, pcd, count), "through": True,
                    "flatness": float(o.get("flatness") or FLATNESS), "position_tol": float(o.get("position_tol") or POS_TOL)},
                    ["A", "B", "C"])
    # gear meshes last (their existence depends on numbers; earlier ids stay stable)
    rows = list(stations.items()) + [(h, hm["shafts"]) for h, hm in housing.items()]
    for i, row in rows:
        for n in range(1, len(row)):
            mesh = meshes(row[n - 1], row[n])
            if not mesh:
                continue
            ga, gb = mesh
            sa, sb = spec[ga], spec[gb]
            pa, pb = at[ga][0], at[gb][0]
            gax = "y" if i in housing else "z"
            pl = PLANE[gax]
            add("gear_mesh", (ga, 0), (gb, 0), {
                "module": sa["module"], "teeth_a": int(sa["teeth"]), "teeth_b": int(sb["teeth"]),
                "centre_distance": _r2(sa["module"] * (sa["teeth"] + sb["teeth"]) / 2),
                "face_width": _r2(min(sa["b"], sb["b"])), "pressure_angle": PRESSURE_ANGLE,
                "ratio": round(sb["teeth"] / sa["teeth"], 4),
                "axis_a": [_r2(pa[pl[0]]), _r2(pa[pl[1]])], "axis_b": [_r2(pb[pl[0]]), _r2(pb[pl[1]])],  # type: ignore[index]
                **({"ax": gax, "plane_a": _r2(pa[1]), "plane_b": _r2(pb[1])} if gax != "z" else {})},  # type: ignore[index]
                ["A", "B"])

    if line:  # shaft lines: per shaft its bearings on the journals, then its gears / hubs; the meshes last
        piece: dict[str, int] = {}
        brg_copy: dict[tuple[str, int], int] = {}  # (shaft, side) -> the bearing piece on that journal
        for sh in line_sh:
            ks = spec[sh]
            pos = at[sh][0]
            assert pos is not None
            a2 = [_r2(pos[0]), _r2(pos[2])]
            y_lo, y_hi = pos[1] - ks["length"] / 2, pos[1] + ks["length"] / 2
            for side, b0, b1, (bitem, des) in line_info["brg"].get(sh, []):
                n = piece.get(bitem, 0)
                piece[bitem] = n + 1
                brg_copy[(sh, side)] = n
                bd, bDD, bB = BEARINGS[des]
                plain = ks["d"] <= bd + 1e-9  # the shaft is the bearing bore: a plain journal, else a shoulder
                jz = (b0, b1) if plain else ((y_lo, b1) if side < 0 else (b0, y_hi))
                add("bearing_journal", (sh, 0), (bitem, n), {
                    "designation": str(des), "bearing": f"Deep-groove ball bearing {des}", "d": bd, "D": bDD, "B": bB,
                    "shaft_fit": SHAFT_FIT_BEARING, "ax": "y", "axis": a2, "z": [_r2(b0), _r2(b1)],
                    "journal_z": [_r2(jz[0]), _r2(jz[1])], "shoulder_z": None if plain else _r2(b1 if side < 0 else b0),
                    "side": side, "bearing_item": bitem, "shaft_d": ks["d"], "count": 1,
                    "r_s_min": _BEARING_RS[int(des)], "standard": "ISO 15 (Toolbox table)", "position_tol": POS_TOL},
                    ["A", "B", "C"], f"bearing {des} on its journal ({'-' if side < 0 else '+'}Y end)")
            for k, c in stk.get((sh, 0), []):
                pos_k = at[k][c]
                assert pos_k is not None
                bottom = pos_k[1] - height(k) / 2
                o = fov.get(f"IF-{len(ifs) + 1:02d}") or {}
                fit = str(o.get("fit") or "H7/k6")
                ak = [_r2(pos_k[0]), _r2(pos_k[2])]
                seat = line_info["seat"].get(sh)
                step: dict[str, Any] = {}
                if seat:  # a stepped shaft: the seat Ø runs from near the free end to the shoulder
                    step = {"seat_z": seat["z"], "shoulder_d": seat["body"], "shoulder_source": seat["source"]}
                    if abs(bottom + height(k) - seat["shoulder_z"]) < 1e-6:  # this hub bears on the shoulder
                        step.update(shoulder_z=seat["shoulder_z"], side=seat["side"])
                add("shaft_bore", (k, c), (sh, 0), {
                    "d": ks["d"], "fit": fit if fit in FITS else "H7/k6", "length": _r2(height(k)), "ax": "y",
                    "axis": ak, "z": [_r2(bottom), _r2(bottom + height(k))], "flush_z": None, **step,
                    "position_tol": POS_TOL}, ["A", "B", "C"],
                    "bore on its seat, against the shoulder" if step.get("shoulder_z") is not None else "bore on shaft")
                key = key_for(ks["d"])
                p = by_id[k]
                keyed = _KEYY.search(f"{p['name']} {p['description']}") or key_item.get(p["sub"]) or \
                    (sub_line and any(e["left"] > 0 for e in key_pool))
                if key and keyed and height(k) >= key[0] + 3:
                    o2 = fov.get(f"IF-{len(ifs) + 1:02d}") or {}
                    kb, kh, t1, t2 = key
                    kl = float(o2.get("length") or math.floor(max(kb + 2, height(k) - 2)))
                    kl = min(kl, float(math.floor(height(k))))
                    z0 = bottom + (height(k) - kl) / 2
                    add("key", (k, c), (sh, 0), {
                        "d": ks["d"], "b": kb, "h": kh, "t1": t1, "t2": t2, "length": kl, "ax": "y",
                        "axis": ak, "dir": [1, 0], "z": [_r2(z0), _r2(z0 + kl)],
                        "hub_z": [_r2(bottom), _r2(bottom + height(k))], "key_item": take_key(p["sub"], (float(ks["d"]), kl)),
                        "standard": "DIN 6885-1 A", "position_tol": POS_TOL}, ["A", "B", "C"],
                        f"parallel key {kb:g} x {kh:g} x {kl:g}")
        for m in line_info["mesh"]:
            if not m:
                continue
            (ga, ca), (gb, cb) = m
            sa, sb = spec[ga], spec[gb]
            pa, pb = at[ga][ca], at[gb][cb]
            assert pa is not None and pb is not None
            add("gear_mesh", (ga, ca), (gb, cb), {
                "module": sa["module"], "teeth_a": int(sa["teeth"]), "teeth_b": int(sb["teeth"]),
                "centre_distance": _r2(sa["module"] * (sa["teeth"] + sb["teeth"]) / 2),
                "face_width": _r2(min(sa["b"], sb["b"])), "pressure_angle": PRESSURE_ANGLE,
                "ratio": round(sb["teeth"] / sa["teeth"], 4),
                "axis_a": [_r2(pa[0]), _r2(pa[2])], "axis_b": [_r2(pb[0]), _r2(pb[2])],
                "ax": "y", "plane_a": _r2(pa[1]), "plane_b": _r2(pb[1])}, ["A", "B"])
        # DIN 471 retaining rings last (earlier ids stay stable): on each shaft, both faces of every gear / hub first
        # (a plain shaft has no shoulder to locate them), then the outboard face of each bearing
        spots: list[tuple[int, int, dict[str, Any]]] = []  # (shaft order, spot order, place)
        for j, sh in enumerate(line_sh):
            ks = spec[sh]
            pos = at[sh][0]
            assert pos is not None
            y_lo, y_hi = pos[1] - ks["length"] / 2, pos[1] + ks["length"] / 2
            mine: list[tuple[float, float, int, str, tuple[str, int]]] = []  # (shaft Ø, face, side, against, part)
            for k, c in stk.get((sh, 0), []):
                pos_k = at[k][c]
                assert pos_k is not None
                mine += [(float(ks["d"]), pos_k[1] - height(k) / 2, -1, "hub", (k, c)),
                         (float(ks["d"]), pos_k[1] + height(k) / 2, 1, "hub", (k, c))]
            for side, b0, b1, (bitem, des) in line_info["brg"].get(sh, []):
                mine.append((min(float(ks["d"]), BEARINGS[des][0]), b0 if side < 0 else b1, side, "bearing",
                             (bitem, brg_copy[(sh, side)])))
            seat = line_info["seat"].get(sh)
            for n_s, (d1, face, side, against, who) in enumerate(mine):
                if seat and against == "hub" and side > 0 and abs(face - seat["shoulder_z"]) < 1e-6:
                    continue  # the shoulder locates this face: no ring there
                row = RINGS.get(round(d1)) if abs(d1 - round(d1)) < 1e-9 else None
                if row is None:
                    continue  # not a DIN 471 shaft size
                m_, n_ = row[3], row[4]
                g0, g1 = (face, face + m_) if side > 0 else (face - m_, face)
                if g0 < y_lo + n_ - 1e-9 or g1 > y_hi - n_ + 1e-9:
                    continue  # no room for the groove before the shaft end
                spots.append((j, n_s, {"sh": sh, "d": d1, "face": face, "side": side, "against": against,
                                       "who": who, "row": row, "g": (g0, g1)}))
        # the rings of a shaft's own sub-assembly first (every shaft), then what is left, same-named first
        took: list[tuple[int, int, dict[str, Any], dict[str, Any]]] = []
        for own in (True, False):
            for j, n_s, sp in spots:
                if any(x[0] == j and x[1] == n_s for x in took):
                    continue
                sub, cls = by_id[sp["sh"]]["sub"], _line_class(by_id[sp["sh"]]["name"])
                cands = sorted((e for e in ring_pool if e["left"] > 0 and e["d"] in (None, sp["d"])
                                and (e["sub"] == sub or not own) and e.get("role") in (None, sp["against"])),
                               key=lambda e: (_line_class(e["name"]) != cls, ring_pool.index(e)))
                if cands:
                    e = cands[0]
                    e["left"] -= 1
                    e["d"] = sp["d"]
                    took.append((j, n_s, sp, e))
        rpiece: dict[str, int] = {}
        for _j, _n, sp, e in sorted(took, key=lambda x: (x[0], x[1])):
            sh, d1, face, side = sp["sh"], sp["d"], sp["face"], sp["side"]
            s_, b_, d2, m_, n_ = sp["row"]
            pos = at[sh][0]
            assert pos is not None
            r0, r1 = (face, face + s_) if side > 0 else (face - s_, face)
            n = rpiece.get(e["id"], 0)
            rpiece[e["id"]] = n + 1
            who, wc = sp["who"]
            add("retaining_ring", (sh, 0), (e["id"], n), {
                "d": d1, "s": s_, "b": b_, "d2": d2, "m": m_, "n": n_, "t": _r2((d1 - d2) / 2), "ax": "y",
                "axis": [_r2(pos[0]), _r2(pos[2])], "z": [_r2(r0), _r2(r1)],
                "groove_z": [_r2(sp["g"][0]), _r2(sp["g"][1])], "face_z": _r2(face), "side": side,
                "against": sp["against"], "against_item": who, "against_copy": wc, "ring_item": e["id"],
                "ring": f"Retaining ring DIN 471 {d1:g}×{s_:g}", "count": 1, "standard": "DIN 471",
                "position_tol": POS_TOL}, ["A", "B"],
                f"retaining ring DIN 471 {d1:g} at the {'+' if side > 0 else '-'}Y face of the "
                f"{by_id[who]['name'] if sp['against'] == 'hub' else 'bearing'}")
        nb = sum(len(v) for v in line_info["brg"].values())
        for sh, seat in line_info["seat"].items():
            spec[sh]["d"] = seat["body"]  # the shaft's envelope is its larger step; its riders keep the seat Ø
        if sub_line:
            riders = [by_id[k]["name"] for sh in line_sh for k, _c in stk.get((sh, 0), [])]
            what = ", ".join(dict.fromkeys(riders)) or "nothing yet"
            stepped_txt = "".join(
                f" {by_id[sh]['name']} is stepped: a Ø{seat['seat']:g} seat and a Ø{seat['body']:g} step"
                f"{' (assumed)' if seat['source'] == 'assumed' else ''}; the hub bears on the shoulder"
                + (" (datum B, Y = 0)." if len(line_sh) == 1 else ".") for sh, seat in line_info["seat"].items())
            notes.append(f"Shaft sub-assembly: no housing or bearings in the plan, so "
                         f"{'the shafts are' if len(line_sh) > 1 else by_id[line_sh[0]]['name'] + ' is'} the base, "
                         f"along +Y, carrying {what}.{stepped_txt} What carries the shaft (bearings, a housing) is "
                         "outside this program: it is delivered as a sub-assembly.")
        else:
            notes.append("Shaft line: no housing or base plate in the plan, so the shafts run along +Y on their own "
                         f"bearings ({nb} on the shaft journals), parallel at the centre distances of their gears; "
                         "the first gear pair meshes on the plane Y = 0. The bearings still need something to stand "
                         "on (pedestals or a frame): not in this plan.")

    # tooth phasing: the second gear of a mesh turns about its axis so a tooth space faces the first gear's tooth
    # (Toolbox gears have a tooth centred on +X); without it two real gears at the exact centre distance collide
    phase: dict[str, float] = {}
    for f in ifs:
        if f["kind"] != "gear_mesh":
            continue
        ga, gb = f["a"]["item"], f["b"]["item"]
        d = f["data"]
        # the direction from gear a to gear b in the gears' (unphased) part frames
        v = frames.apply(frames.transpose(CANON[ax_of(d)]), point3(ax_of(d), [d["axis_b"][0] - d["axis_a"][0],
                                                                         d["axis_b"][1] - d["axis_a"][1]], 0.0))
        th = math.degrees(math.atan2(v[1], v[0]))
        pa, pb = 360.0 / d["teeth_a"], 360.0 / d["teeth_b"]
        u = ((th - phase.get(ga, 0.0)) % pa) / pa       # 0 = a tooth faces gear b, 0.5 = a space does
        v = (0.5 - u) % 1.0                              # gear b shows the opposite at the contact (the gears turn
        #                                                  opposite ways, so an offset +s on a is -s on b)
        if gb not in phase:
            phase[gb] = round(((th + 180.0) - v * pb) % pb, 6)
        d["phase_b"] = phase[gb]

    def _cavity(h: str) -> dict[str, Any]:
        """The housing's cavity in its part frame: open at the top (the lid closes it), the floor below."""
        hm, s = housing[h], spec[h]
        L, W, H = s["L"], s["W"], s["H"]
        return {"min": [_r2(-L / 2 + hm["end_t"]), _r2(-W / 2 + hm["t"]), _r2(-H / 2 + FLOOR)],
                "max": [_r2(L / 2 - hm["end_t"]), _r2(W / 2 - hm["t"]), _r2(H / 2)],
                "wall": hm["t"], "end_wall": hm["end_t"], "floor": FLOOR,
                "note": "Gear cavity: keep it clear (the gears run there); open at the top under the lid."}

    if housing:
        names_h = ", ".join(by_id[h]["name"] for h in housing)
        notes.append(f"Gearbox layout: the shafts run along +Y in the side walls of the {names_h}, each in a bearing "
                     "seat per wall; the gears mesh in the cavity on the plane Y = 0"
                     + ("; the caps are bolted over the seats (coaxial)" if any(hm["caps"] for hm in housing.values())
                        else "") + ".")

    # ---- skeleton document
    items_out: dict[str, Any] = {}
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for p in designed:
        i = p["id"]
        s = spec[i]
        size = _size_of(s)
        Rw = frames.item_rotation(s.get("ax") or "z", float(s.get("rot") or 0) if s["role"] == "block" else 0.0)
        wsize = [sum(abs(Rw[r][j]) * size[j] for j in range(3)) for r in range(3)]
        for c in at[i]:
            for k in range(3):
                lo[k] = min(lo[k], c[k] - wsize[k] / 2)  # type: ignore[index]
                hi[k] = max(hi[k], c[k] + wsize[k] / 2)  # type: ignore[index]
        items_out[i] = {"name": p["name"], "role": s["role"], "shape": "box" if s["role"] == "block" else "cylinder",
                        "size": [_r2(x) for x in size], "sub": p["sub"], "parent": parent.get(i),
                        "copies": [[_r2(x) for x in c] for c in at[i]],  # type: ignore[union-attr]
                        "qty": p["qty"], "source": s["source"], **({"rot": s["rot"]} if s.get("rot") else {}),
                        **({"planned": s["planned"]} if s.get("planned") else {}),
                        **({"ax": s["ax"]} if s.get("ax") and s["ax"] != "z" else {}),
                        **({"cavity": _cavity(i)} if i in housing else {}),
                        **({"phase": phase[i]} if phase.get(i) else {}),
                        **({"d": s["d"]} if s["role"] == "shaft" else {}),
                        **({"bearing": s["bearing"]} if s.get("bearing") else {}),
                        **({"bore": s["bore"]} if s.get("bore") else {}),
                        **({"module": s["module"], "teeth": int(s["teeth"]), "face_width": s["b"]}
                           if s["role"] == "gear" else {})}
    def axis_of(i: str) -> dict[str, Any]:
        ax = items_out[i].get("ax") or "z"
        c = items_out[i]["copies"][0]
        o = [c[0], c[1], 0.0] if ax == "z" else [c[0], 0.0, c[2]] if ax == "y" else [0.0, c[1], c[2]]
        return {"origin": o, "dir": unit(ax)}

    axes = [{"id": f"AX{n + 1}", "name": f"{items_out[i]['name']} axis", "item": i, **axis_of(i)}
            for n, i in enumerate(i for i in items_out if items_out[i]["role"] == "shaft")]
    base = items_out[prog_base]
    if line:  # datums of a shaft line: the plane of the shaft axes, the (first) mesh plane, the input shaft's axis
        meshy = any(line_info["mesh"])
        shoulder = len(line_sh) == 1 and line_sh[0] in line_info["seat"]
        first = next((by_id[k]["name"] for k, _c in stk.get((line_sh[0], 0), [])), None) if line_sh else None
        if shoulder:
            bname = f"Shoulder face of the {base['name']} (the {first or 'hub'} locates on it)"
        elif meshy:
            bname = "Mesh plane (first gear pair)"
        elif sub_line and first:
            bname = f"Mid-plane of the {first}"
        else:
            bname = "Mid-plane XZ"
        csys = (f"Origin on the {base['name']} axis" + (" in the mesh plane of the first gear pair" if meshy else
                                                         " at its shoulder face" if shoulder else "")
                + " (datums A, B, C); the shafts run along +Y, parallel, in the plane Z = 0 (datum A, the plane of "
                "the shaft axes); +X from the input shaft towards the next one; +Z up.")
        if sub_line and len(line_sh) == 1:
            csys = (f"Origin on the {base['name']} axis" + (" at its shoulder face" if shoulder else
                                                             f" in the mid-plane of the {first}" if first else "")
                    + f" (datums A, B, C); the {base['name']} is the base (fixed), its axis along +Y in the plane "
                    "Z = 0 (datum A); +Z up.")
        datums = [{"id": "A", "kind": "plane", "name": "Horizontal plane through the shaft axis"
                   if sub_line and len(line_sh) == 1 else "Plane of the shaft axes", "origin": [0, 0, 0],
                   "normal": [0, 0, 1]},
                  {"id": "B", "kind": "plane", "name": bname, "origin": [0, 0, 0], "normal": [0, 1, 0]},
                  {"id": "C", "kind": "plane", "name": f"{base['name']} axis plane (YZ)", "origin": [0, 0, 0],
                   "normal": [1, 0, 0]}]
    else:
        csys = (f"Origin at the centre of the top face of the {base['name']} (datums A, B, C); +Z up, away from "
                "the base; +X along the row of parts; +Y completes a right-handed frame."
                + (" Gearbox shafts run along +Y." if housing else ""))
        datums = [{"id": "A", "kind": "plane", "name": f"{base['name']} top face", "origin": [0, 0, 0], "normal": [0, 0, 1]},
                  {"id": "B", "kind": "plane", "name": "Mid-plane XZ", "origin": [0, 0, 0], "normal": [0, 1, 0]},
                  {"id": "C", "kind": "plane", "name": "Mid-plane YZ", "origin": [0, 0, 0], "normal": [1, 0, 0]}]
    skel = {"units": "mm", "base": prog_base, "layout": "gearbox" if housing else layout, "csys": csys,
            "datums": datums,
            "axes": axes,
            "envelope": {"min": [_r2(x) for x in lo], "max": [_r2(x) for x in hi],
                         "size": [_r2(hi[k] - lo[k]) for k in range(3)]},
            "items": items_out, "notes": notes,
            "standard": [{"item": p["id"], "name": p["name"], "qty": p["qty"], "sub": p["sub"]}
                         for p in parts if p["family"] == "standard"]}
    # parts the engineer decided to keep separate at the ICD gate (a kit, two shafts to be made): no interface is
    # their intended state, an acknowledged warning instead of a blocking ``no_interface`` (``keep_separate``)
    sep = sorted(i for i in (ov.get("separate") or {}) if i in items_out)
    if sep:
        skel["separate"] = sep
    if sub_line:  # a shaft with what it carries, no bearings or housing in the plan: delivered as a sub-assembly
        skel["shaft_subassembly"] = True
    return skel, ifs


def ncopies_quiet(p: dict[str, Any]) -> int:
    return min(int(p.get("qty") or 1), MAX_COPIES)


def _size_of(s: dict[str, Any]) -> list[float]:
    r = s["role"]
    if r == "block":
        return [s["L"], s["W"], s["H"]]
    if r == "shaft":
        return [s["d"], s["d"], s.get("length") or 40.0]
    if r == "hub":
        return [s["OD"], s["OD"], s["H"]]
    tip = s["module"] * (s["teeth"] + 2)  # the envelope holds the teeth: tip circle m (z + 2)
    return [tip, tip, s["b"]]


def _empty(parts: list[dict[str, Any]], spec: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"units": "mm", "base": None, "csys": "No designed parts: nothing to lay out.", "datums": [], "axes": [],
            "envelope": {"min": [0, 0, 0], "max": [0, 0, 0], "size": [0, 0, 0]}, "items": {}, "notes": [],
            "standard": [{"item": p["id"], "name": p["name"], "qty": p["qty"], "sub": p["sub"]}
                         for p in parts if p["family"] == "standard"]}


# ----------------------------------------------------------------------------- local features per item
def _rot(skel: dict[str, Any], side: dict[str, Any]) -> float:
    """How far a part frame is turned about its own Z: a block's quarter turns, a gear's tooth phase."""
    it = skel["items"][side["item"]]
    return float(it.get("rot") or 0) + float(it.get("phase") or 0)


def item_R(it: dict[str, Any]) -> list[list[float]]:
    """Part frame -> program frame of a skeleton item (its axis, then its turn about its own Z)."""
    return frames.item_rotation(it.get("ax") or "z", float(it.get("rot") or 0) + float(it.get("phase") or 0))


def _part_pt(skel: dict[str, Any], side: dict[str, Any], p: list[float]) -> list[float]:
    it = skel["items"][side["item"]]
    c = it["copies"][side["copy"]]
    return frames.apply(frames.transpose(item_R(it)), [float(p[k]) - float(c[k]) for k in range(3)])


def _part_vec(skel: dict[str, Any], side: dict[str, Any], v: list[float]) -> list[float]:
    return frames.apply(frames.transpose(item_R(skel["items"][side["item"]])), v)


def _lax(v: list[float]) -> str:
    return "xyz"[max(range(3), key=lambda k: abs(v[k]))]


def to_canon(lax: str, p: list[float]) -> list[float]:
    """Part frame -> canonical frame of a feature along part axis ``lax``."""
    return frames.apply(frames.transpose(CANON[lax]), p)


def from_canon(lax: str, p: list[float]) -> list[float]:
    """Canonical frame of a feature along part axis ``lax`` -> part frame."""
    return frames.apply(CANON[lax], p)


def _axial(skel: dict[str, Any], side: dict[str, Any], d: dict[str, Any], a2: Any, t0: float,
           t1: float | None = None) -> dict[str, Any]:
    """An interface's axis line (2-D ``a2`` across its axis, from ``t0`` to ``t1`` along it) as a feature of one side:
    ``c`` (and ``z0``, ``z1``) in the canonical frame of the part axis it lies along (``ax`` when not Z)."""
    ax = ax_of(d)
    lax = _lax(_part_vec(skel, side, unit(ax)))
    q0 = to_canon(lax, _part_pt(skel, side, point3(ax, a2, t0)))
    out: dict[str, Any] = {"c": [_r2(q0[0]), _r2(q0[1])]}
    if t1 is not None:
        q1 = to_canon(lax, _part_pt(skel, side, point3(ax, a2, t1)))
        z0, z1 = sorted((q0[2], q1[2]))
        out.update(z0=_r2(z0), z1=_r2(z1))
    if lax != "z":
        out["ax"] = lax
    return out


def _plane(skel: dict[str, Any], side: dict[str, Any], d: dict[str, Any], t: float, sign: int) -> dict[str, Any]:
    """A plane across the interface's axis at ``t``, normal ``sign`` along it, as a face of one side: ``z`` and ``n``
    in the canonical frame of the part axis it faces along."""
    ax = ax_of(d)
    nl = _part_vec(skel, side, [sign * x for x in unit(ax)])
    lax = _lax(nl)
    c = skel["items"][side["item"]]["copies"][side["copy"]]
    i, j = PLANE[ax]
    q = to_canon(lax, _part_pt(skel, side, point3(ax, [c[i], c[j]], t)))
    out: dict[str, Any] = {"z": _r2(q[2]), "n": 1 if to_canon(lax, nl)[2] > 0 else -1}
    if lax != "z":
        out["ax"] = lax
    return out


def _dir2(skel: dict[str, Any], side: dict[str, Any], d: dict[str, Any], v2: Any, lax: str) -> list[float]:
    """A direction across the interface's axis (2-D) in the canonical frame of the side's feature axis."""
    q = to_canon(lax, _part_vec(skel, side, point3(ax_of(d), v2, 0.0)))
    return [_r2(q[0]), _r2(q[1])]


def _local(skel: dict[str, Any], side: dict[str, Any], xy: list[float], d: dict[str, Any] | None = None) -> list[float]:
    """A point of an interface's pattern (2-D across its axis) in the canonical frame of one side (Phase 4/5: the
    program-frame (X, Y) in the part frame)."""
    dd = d or {}
    t = float(dd.get("plane_z") or 0.0) if dd else skel["items"][side["item"]]["copies"][side["copy"]][2]
    return _axial(skel, side, dd, xy, t)["c"]


def _side_word(fc: dict[str, Any]) -> str:
    if fc.get("ax"):
        return f" ({'+' if fc['n'] > 0 else '-'}{fc['ax'].upper()} side)"
    return " (top)" if fc["n"] > 0 else " (bottom)"


def _sgn(d: dict[str, Any]) -> int:
    """The sign, along the interface's axis, of the normal of side a's face (+1: a's face looks along +axis)."""
    n = d.get("normal") or unit(ax_of(d))
    return 1 if float(n[AXIS_INDEX[ax_of(d)]]) >= 0 else -1


def side_features(skel: dict[str, Any], f: dict[str, Any], which: str) -> list[dict[str, Any]]:
    """What one side of an interface must carry, in its part frame. Features along a part axis other than Z carry
    ``ax`` and are written in that axis' canonical frame (``CANON``): ``c`` across the axis, ``z`` along it."""
    side = f[which]
    d = f["data"]
    tol = d.get("position_tol", POS_TOL)
    out: list[dict[str, Any]] = []
    horiz = ax_of(d) != "z"
    if f["kind"] == "hole_pattern":
        sa = _sgn(d)
        fc = _plane(skel, side, d, d["plane_z"], sa if which == "a" else -sa)
        out.append({"type": "face", **fc, "tol": tol, "label": "mounting face" + _side_word(fc)})
        tp = d.get("tapped") if which == "a" else None
        for k, xy in enumerate(d["positions"]):
            if tp:  # blind, tapped from the mounting face into side a
                g = _axial(skel, side, d, xy, d["plane_z"], d["plane_z"] - sa * float(tp["depth"]))
                out.append({"type": "hole", **g, "d": tp["d"], "blind": True, "thread": tp["thread"], "tol": tol,
                            "label": f"tapped hole {k + 1} {tp['thread']} × {tp['depth']:g} deep"})
            else:
                out.append({"type": "hole", **_axial(skel, side, d, xy, d["plane_z"]), "d": d["d"], "tol": tol,
                            "label": f"hole {k + 1}"})
        for n, w in enumerate(d.get("passages") or []):  # an opening across the joint (master model, WORKLIST 50)
            dw = float(w["d_a" if which == "a" else "d_b"])
            out.append({"type": "hole", **_axial(skel, side, d, w["at"], d["plane_z"]), "d": dw, "tol": tol,
                        "label": f"clearance opening {n + 1} Ø{dw:g} through (across the joint)"})
        cb = d.get("counterbore") if which == "b" else None
        if cb:  # the screw heads sink into the head side (measured from a master model): a seat at its far face
            far = d["plane_z"] + sa * float(cb["length"])
            for k, xy in enumerate(d["positions"]):
                g = _axial(skel, side, d, xy, far - sa * float(cb["depth"]), far)
                out.append({"type": "seat", **g, "d": float(cb["d"]), "tol": tol,
                            "label": f"counterbore {k + 1} Ø{float(cb['d']):g} × {float(cb['depth']):g} deep"})
        rl = d.get("relief") if which == "b" else None
        if rl:  # a bearing cap: the recess in its mounting face over the turning inner ring (and the shaft end)
            g = _axial(skel, side, d, d["centre"], d["plane_z"], d["plane_z"] + sa * float(rl["depth"]))
            out.append({"type": "seat", **g, "d": float(rl["d"]), "tol": tol,
                        "label": f"relief Ø{float(rl['d']):g} × {float(rl['depth']):g} deep in the mounting face (the "
                                 "cap bears on the bearing's outer ring only, clear of the turning inner ring and shaft)"})
    elif f["kind"] == "shaft_bore":
        g = _axial(skel, side, d, d["axis"], d["z"][0])
        if which == "a" and d.get("bore_z"):  # one bore of a stepped (two-bore) coupling: through its own half
            bz = d["bore_z"]
            out.append({"type": "hole", **_axial(skel, side, d, d["axis"], bz[0], bz[1]), "d": d["d"],
                        "fit": d["fit"].split("/")[0], "tol": tol, "span": True,
                        "label": f"bore Ø{d['d']:g} {d['fit'].split('/')[0]} through its half"})
        elif which == "a":
            out.append({"type": "hole", **g, "d": d["d"], "fit": d["fit"].split("/")[0],
                        "tol": tol, "label": f"bore Ø{d['d']:g} {d['fit'].split('/')[0]}"})
        elif d.get("seat_z"):  # a stepped shaft: the seat Ø over its span, up to the shoulder
            out.append({"type": "boss", **_axial(skel, side, d, d["axis"], d["seat_z"][0], d["seat_z"][1]),
                        "d": d["d"], "fit": d["fit"].split("/")[1], "tol": tol,
                        "label": f"seat Ø{d['d']:g} {d['fit'].split('/')[1]} (stepped shaft)"})
        else:
            out.append({"type": "boss", **g, "d": d["d"], "fit": d["fit"].split("/")[1],
                        "tol": tol, "label": f"shaft Ø{d['d']:g} {d['fit'].split('/')[1]}"})
        if d.get("flush_z") is not None:
            out.append({"type": "face", **_plane(skel, side, d, d["flush_z"], -1), "tol": tol,
                        "label": "end face flush with the bottom"})
        if d.get("shoulder_z") is not None:  # the hub face bears on the shaft's shoulder (faces opposed)
            sd = int(d.get("side") or 1)
            out.append({"type": "face", **_plane(skel, side, d, d["shoulder_z"], sd if which == "a" else -sd),
                        "tol": tol, "label": ("hub face against the shoulder" if which == "a" else
                                              f"shoulder Ø{float(d.get('shoulder_d') or 0):g} (the hub locates on it)")})
    elif f["kind"] == "bearing_seat":
        if which == "a":  # the housing: a seat per bearing (Ø D, housing fit, depth B) and the shaft clearance
            for st in d["seats"]:
                g = _axial(skel, side, d, d["axis"], st["z"][0], st["z"][1])
                out.append({"type": "seat", **g, "d": d["D"], "fit": d["housing_fit"], "tol": tol,
                            "label": f"bearing seat Ø{d['D']:g} {d['housing_fit']} ({st['face']})"})
                op = int(st.get("open") or (1 if st["face"] == "top" else -1))
                fz = st["z"][0] if op > 0 else st["z"][1]
                if any(o is not st and any(abs(float(e) - float(fz)) < 1e-6 for e in o["z"]) for o in d["seats"]):
                    continue  # two bearings side by side in one bore: the seat runs on, no shoulder between them
                fc = _plane(skel, side, d, fz, op)
                out.append({"type": "face", **fc, "tol": tol,
                            "label": f"bearing shoulder ({st['face']}), seat depth {d['B']:g}"})
            opens = [(int(st.get("open") or (1 if st["face"] == "top" else -1)), st["z"]) for st in d["seats"]]
            lo = max([z[1] for o, z in opens if o < 0] or [d["z"][0]])
            hi = min([z[0] for o, z in opens if o > 0] or [d["z"][1]])
            if hi - lo > 0.5:
                out.append({"type": "seat", **_axial(skel, side, d, d["axis"], lo, hi), "d": d["clearance_d"], "tol": tol,
                            "label": f"shaft clearance Ø{d['clearance_d']:g}"})
            for ps_ in d.get("passes") or []:  # the bore beyond the seats (planetary layout): a shaft through the
                # wall's shoulder, a planet's bearing entry and pin clearance (benchmark A1: they were left solid)
                out.append({"type": "seat", **_axial(skel, side, d, d["axis"], ps_["z"][0], ps_["z"][1]),
                            "d": float(ps_["d"]), "tol": tol, "label": f"{ps_['what']} Ø{float(ps_['d']):g}"})
            if d.get("flush_z") is not None:  # (a pillow block's seat has no flush shaft end)
                out.append({"type": "face", **_plane(skel, side, d, d["flush_z"], -1), "tol": tol,
                            "label": ("outer face (-Y wall), shaft end flush with it" if horiz
                                      else "bottom face, shaft end flush with it")})
        else:  # the shaft: the bearing journal through the housing, end flush with its bottom
            # a stepped shaft (graph layout) names its journal spans: the shaft between them may be larger
            for z0, z1 in d.get("journals") or [d["z"]]:
                out.append({"type": "boss", **_axial(skel, side, d, d["axis"], z0, z1), "d": d["d"],
                            "fit": d["shaft_fit"], "tol": tol, "label": f"bearing journal Ø{d['d']:g} {d['shaft_fit']}"})
            if d.get("flush_z") is not None:
                out.append({"type": "face", **_plane(skel, side, d, d["flush_z"], -1), "tol": tol,
                            "label": "end face flush with the " + ("-Y wall" if horiz else "bottom")})
    elif f["kind"] == "bearing_journal":
        sd = int(d.get("side") or -1)
        if which == "a":  # the shaft: the journal (bearing bore Ø, k6), and the shoulder when the shaft is larger
            g = _axial(skel, side, d, d["axis"], d["journal_z"][0], d["journal_z"][1])
            end = _plane(skel, side, d, d["z"][0], sd)
            words = f"{'+' if end['n'] > 0 else '-'}{(end.get('ax') or 'z').upper()} end"
            out.append({"type": "boss", **g, "d": d["d"], "fit": d["shaft_fit"], "tol": tol,
                        "label": f"bearing journal Ø{d['d']:g} {d['shaft_fit']} ({d['designation']}, {words})"})
            if d.get("shoulder_z") is not None:
                out.append({"type": "face", **_plane(skel, side, d, d["shoulder_z"], sd), "tol": tol,
                            "label": f"bearing shoulder ({words})"})
        else:  # the bearing (a Toolbox part, not in the skeleton): its own frame, base face on Z 0, bore along +Z
            out.append({"type": "seat", "c": [0.0, 0.0], "z0": 0.0, "z1": float(d["B"]), "d": d["d"], "tol": tol,
                        "label": f"bearing bore Ø{d['d']:g} ({d['designation']})"})
            if d.get("shoulder_z") is not None:
                out.append({"type": "face", "z": float(d["B"]) if sd < 0 else 0.0, "n": 1 if sd < 0 else -1,
                            "tol": tol, "label": "inner ring face against the shoulder"})
    elif f["kind"] == "key":
        on = "hub" if which == "a" else "shaft"
        z = d["hub_z"] if on == "hub" else d["z"]
        depth = d["t2"] if on == "hub" else d["t1"]
        g = _axial(skel, side, d, d["axis"], z[0], z[1])
        out.append({"type": "keyway", "on": on, **g, "d": d["d"], "b": d["b"], "depth": depth,
                    "dir": _dir2(skel, side, d, d["dir"], g.get("ax") or "z"), "tol": tol,
                    "label": f"keyway {d['b']:g} × {depth:g} ({on}, {d['standard']})"})
    elif f["kind"] == "retaining_ring":
        if which == "a":  # the shaft: the DIN 471 groove (groove Ø d2, width m H13 over groove_z)
            g = _axial(skel, side, d, d["axis"], d["groove_z"][0], d["groove_z"][1])
            out.append({"type": "groove", **g, "d": d["d2"], "shaft_d": d["d"], "m": d["m"], "tol": tol,
                        "label": f"retaining ring groove Ø{d['d2']:g} × {d['m']:g} H13 ({d['standard']} {d['d']:g})"})
        else:  # the ring (a Toolbox part, not in the skeleton): its own frame, a face on Z 0, axis along +Z
            out.append({"type": "seat", "c": [0.0, 0.0], "z0": 0.0, "z1": float(d["s"]), "d": d["d2"], "tol": tol,
                        "label": f"ring bore Ø{d['d2']:g} as fitted ({d['ring']})"})
    elif f["kind"] == "dowel":
        for k, xy in enumerate(d["positions"]):
            out.append({"type": "hole", **_axial(skel, side, d, xy, d["plane_z"]), "d": d["d"],
                        "fit": d["fit"].split("/")[0], "tol": tol,
                        "label": f"dowel hole {k + 1} Ø{d['d']:g} {d['fit'].split('/')[0]}"})
    elif f["kind"] == "face":
        sa = _sgn(d)
        fc = _plane(skel, side, d, d["plane_z"], sa if which == "a" else -sa)
        out.append({"type": "face", **fc, "tol": tol, "label": "seating face" + _side_word(fc)})
        for n, w in enumerate(d.get("passages") or []):  # an opening across the joint (master model, WORKLIST 50)
            dw = float(w["d_a" if which == "a" else "d_b"])
            out.append({"type": "hole", **_axial(skel, side, d, w["at"], d["plane_z"]), "d": dw, "tol": tol,
                        "label": f"clearance opening {n + 1} Ø{dw:g} through (across the joint)"})
    elif f["kind"] == "gear_mesh":
        z = d["teeth_a"] if which == "a" else d["teeth_b"]
        g = {"type": "gear", "module": d["module"], "teeth": z, "c": [0.0, 0.0], "tol": tol,
             "label": f"m{d['module']:g} × {z} teeth"}
        if d.get("internal") and _internal_member(skel, f, which):
            g.update(internal=True, label=f"m{d['module']:g} × {z} internal teeth")  # the ring of a planet / ring mesh
        out.append(g)
    for o in out:
        o["if"] = f["id"]
    return out


def _internal_member(skel: dict[str, Any], f: dict[str, Any], which: str) -> bool:
    """Of an internal gear mesh, is side ``which`` the internal (ring) gear? The item says so (``internal``), else
    the member with more teeth (a ring always has more teeth than the pinion inside it)."""
    items = skel.get("items") or {}
    flags = {w: bool((items.get(f[w]["item"]) or {}).get("internal")) for w in ("a", "b")}
    if any(flags.values()):
        return flags[which]
    d = f["data"]
    za, zb = int(d["teeth_a"]), int(d["teeth_b"])
    return (za > zb) if which == "a" else (zb > za)


def item_features(skel: dict[str, Any], ifs: list[dict[str, Any]], item: str) -> list[dict[str, Any]]:
    """Every feature an item carries (deduplicated across copies), with the interfaces that need it."""
    feats: list[dict[str, Any]] = []
    for f in ifs:
        for which in ("a", "b"):
            if f[which]["item"] != item:
                continue
            for x in side_features(skel, f, which):
                same = next((y for y in feats if _same_feature(x, y)), None)
                if same:
                    same.setdefault("also", []).append(x["if"])
                else:
                    feats.append(x)
    return feats


def _near(a: Any, b: Any) -> bool:
    return abs(float(a) - float(b)) < 1e-6


def _same_feature(x: dict[str, Any], y: dict[str, Any]) -> bool:
    if x["type"] != y["type"] or x.get("ax") != y.get("ax"):
        return False
    if x["type"] == "face":
        return x["n"] == y["n"] and _near(x["z"], y["z"])
    if x["type"] == "gear":
        return True
    same_c = _near(x["c"][0], y["c"][0]) and _near(x["c"][1], y["c"][1])
    if x["type"] == "keyway":
        return same_c and x["on"] == y["on"] and _near(x["z0"], y["z0"])
    if x["type"] == "seat":
        return same_c and _near(x["d"], y["d"]) and _near(x["z0"], y["z0"])
    if x.get("z0") is not None or y.get("z0") is not None:  # blind holes at different depths are different holes
        return same_c and _near(x["d"], y["d"]) and x.get("z0") is not None and y.get("z0") is not None \
            and _near(x["z0"], y["z0"])
    return same_c and _near(x["d"], y["d"])


def body_spec(shape: str, size: list[float], features: list[dict[str, Any]], bore: float | None = None,
              name: str = "", cavity: dict[str, Any] | None = None) -> dict[str, Any]:
    """The solid that carries a set of ICD features in its part frame (placeholders, and the simulated agents'
    parts): the envelope with through (or blind, over a range) holes, bearing seats (counterbores / bores over a
    range), journals (a shaft turned down over a range), keyways and a housing's cavity. Features along X or Y carry
    ``ax`` (canonical frame, see ``CANON``)."""
    def keep(f: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        return {**{k: f[k] for k in keys if f.get(k) is not None}, **({"ax": f["ax"]} if f.get("ax") else {})}

    holes = [keep(f, ("c", "d", "z0", "z1")) for f in features if f["type"] == "hole"]
    if bore and not any(_near(h["c"][0], 0) and _near(h["c"][1], 0) and not h.get("ax") for h in holes):
        holes.append({"c": [0.0, 0.0], "d": bore})
    seats = [keep(f, ("c", "d", "z0", "z1")) for f in features if f["type"] == "seat"]
    journals = [keep(f, ("c", "d", "z0", "z1")) for f in features
                if f["type"] == "boss" and f.get("z0") is not None and shape == "cylinder" and f["d"] < size[0] - 1e-6]
    keyways = [keep(f, ("on", "c", "d", "b", "depth", "dir", "z0", "z1")) for f in features if f["type"] == "keyway"]
    grooves = [keep(f, ("c", "d", "z0", "z1")) for f in features if f["type"] == "groove"]
    out = {"shape": shape, "size": size, "holes": holes, "seats": seats, "journals": journals, "keyways": keyways,
           "name": name}
    if grooves:  # only when there are some: placeholders of programs without retaining rings keep their cache keys
        out["grooves"] = grooves
    if cavity:
        out["pockets"] = [{"min": cavity["min"], "max": cavity["max"]}]
    return out


def internal_opening(module: float, teeth: int) -> float:
    """The opening of an internal gear's placeholder: the root circle of its teeth, d_f = m (z + 2 x 1.25) (ISO 53
    basic rack, dedendum 1.25 m). Inside it there is only tooth space and the room the planets turn in."""
    return round(float(module) * (int(teeth) + 2.5), 3)


def placeholder_spec(skel: dict[str, Any], ifs: list[dict[str, Any]], item: str) -> dict[str, Any]:
    """The envelope solid with its interface features, in the part frame. A placeholder never claims material where
    the ICD says there is none (benchmark A1, 2026-11-21: a solid Ø197 disc for an internal ring sent a correct input
    shaft and three pins back for "clashes" with empty space):

    * an external gear is its pitch cylinder (meshing placeholders touch, never clash), with its bore, or its bearing
      seat and the passes beside it (a planet: the bearing entry and the pin clearance);
    * an internal gear is its rim: the envelope OD, open to the root circle of its teeth (``internal_opening``);
    * through bores and shaft bores of hubs, gears and carriers, bearing seats and a housing's cavity, as the ICD
      features say (``item_features`` / ``body_spec``)."""
    it = skel["items"][item]
    size = it["size"]
    feats = item_features(skel, ifs, item)
    bore = it.get("bore")
    if it["role"] == "gear" and it.get("internal"):
        opening = internal_opening(it["module"], it["teeth"])
        if opening < float(size[0]) - 1.0:
            bore = max(float(bore or 0.0), opening)
    elif it["role"] == "gear":
        p = it["module"] * it["teeth"]
        size = [p, p, size[2]]
        # a gear on its bearing (a planet): the seat is bored from its open face to the shoulder, and the bore behind
        # the shoulder clears the turning inner ring (the gear generator's rule, D - (D - d) / 4 down to 0.5 mm);
        # without these the pin "clashed" with the planet's placeholder. Placeholder only: the ICD keeps its seat.
        byid = {f["id"]: f for f in ifs}
        for x in [f for f in feats if f["type"] == "seat" and f.get("fit")]:
            d = (byid.get(x["if"]) or {}).get("data") or {}
            if (byid.get(x["if"]) or {}).get("kind") != "bearing_seat" or not d.get("d"):
                continue
            D, bd, H = float(d["D"]), float(d["d"]), float(size[2])
            bore = max(float(bore or 0.0), math.floor(2 * (D - (D - bd) / 4)) / 2)
            opens = [int(s.get("open") or -1) for s in d.get("seats") or []] or [-1]
            z0, z1 = float(x["z0"]), float(x["z1"])
            x["z0"], x["z1"] = (-H / 2, z1) if opens[0] < 0 else (z0, H / 2)
    return body_spec(it["shape"], size, feats, bore, it["name"], it.get("cavity"))


def key_frame(d: dict[str, Any]) -> tuple[list[list[float]], list[float]]:
    """Placement (R, base point; program frame) of the Toolbox parallel key of a ``key`` interface. The key's frame
    (``toolbox._parallel_key``): length along X and width along Y, centred, underside on Z 0. In the program its X
    runs along the shaft axis, its Z out along the keyway direction ``dir`` and its underside lies on the keyseat
    floor, ``d / 2 - t1`` from the axis, centred on the key's span ``z``."""
    ax = ax_of(d)
    u = unit(ax)
    w = point3(ax, d["dir"], 0.0)
    w[AXIS_INDEX[ax]] = 0.0
    nw = math.sqrt(sum(x * x for x in w)) or 1.0
    w = [x / nw for x in w]
    v = [w[1] * u[2] - w[2] * u[1], w[2] * u[0] - w[0] * u[2], w[0] * u[1] - w[1] * u[0]]  # Y = Z × X
    R = [[float(u[i]), float(v[i]), float(w[i])] for i in range(3)]
    mid = point3(ax, d["axis"], (float(d["z"][0]) + float(d["z"][1])) / 2)
    r = float(d["d"]) / 2 - float(d["t1"])
    return R, [_r2(mid[i] + w[i] * r) for i in range(3)]


def seated(ifs: list[dict[str, Any]], item: str) -> dict[str, Any] | None:
    """Where the ICD puts a standard part (a bearing in its seats, dowel pins in their holes, a parallel key in its
    keyseat under the hub, a DIN 471 ring in its shaft groove): the Toolbox component, its sizes and one placement
    per piece (the part's base point, program frame; ``R`` turns the part's own frame when it isn't the program's)."""
    keys = [f for f in ifs if f["kind"] == "key" and f["data"].get("key_item") == item]
    if keys:
        d0 = keys[0]["data"]
        R0, _p = key_frame(d0)
        out_k: dict[str, Any] = {
            "code": "parallel_key", "params": {"D": float(d0["d"]), "L": float(d0["length"])}, "at": [], "R": R0,
            "interface": keys[0]["id"], "interfaces": [], "standard": "DIN 6885-1 A", "what": "shaft keyseats",
            "title": f"Parallel key DIN 6885 A {d0['b']:g}×{d0['h']:g}×{d0['length']:g}"}
        for f in keys:  # one Toolbox part per standard item: another size or direction is not this item's place
            R, p = key_frame(f["data"])
            if R != R0 or abs(float(f["data"]["d"]) - float(d0["d"])) > 1e-9 \
                    or abs(float(f["data"]["length"]) - float(d0["length"])) > 1e-9:
                continue
            out_k["at"].append(p)
            out_k["interfaces"].append(f["id"])
        return out_k
    rings = [f for f in ifs if f["kind"] == "retaining_ring" and f["data"].get("ring_item") == item]
    if rings:
        d0 = rings[0]["data"]
        out_r: dict[str, Any] = {
            "code": "retaining_ring", "params": {"D": float(d0["d"])}, "at": [], "interface": rings[0]["id"],
            "interfaces": [], "standard": "DIN 471", "what": "shaft grooves", "title": d0["ring"]}
        if ax_of(d0) != "z":
            out_r["R"] = CANON[ax_of(d0)]
        for f in rings:  # the ring's face on Z 0 of its frame: the lower end of its span along the axis
            d = f["data"]
            if abs(float(d["d"]) - float(d0["d"])) > 1e-9 or ax_of(d) != ax_of(d0):
                continue
            out_r["at"].append([_r2(x) for x in point3(ax_of(d), d["axis"], float(d["z"][0]))])
            out_r["interfaces"].append(f["id"])
        return out_r
    out: dict[str, Any] | None = None
    for f in ifs:  # bearings: every seat / journal of this item, in ICD order (copy n is the n-th place)
        d = f["data"]
        if f["kind"] not in ("bearing_seat", "bearing_journal") or d.get("bearing_item") != item:
            continue
        ax = ax_of(d)
        spans = d["seats"] if f["kind"] == "bearing_seat" else [{"z": d["z"]}]
        at = [[_r2(x) for x in point3(ax, d["axis"], st["z"][0])] for st in spans]
        if out is None:
            out = {"code": "bearing", "params": {"SERIES": int(d["designation"])}, "at": [], "interface": f["id"],
                   "interfaces": [], "title": f"Ball bearing {d['designation']}", "standard": "ISO 15",
                   "what": "bearing seats" if f["kind"] == "bearing_seat" else "shaft journals"}
            if ax != "z":  # the bearing's own Z (its width, from its base face) along the shaft axis
                out["R"] = CANON[ax]
        if int(d["designation"]) != out["params"]["SERIES"] or CANON[ax] != out.get("R", CANON["z"]):
            continue  # one Toolbox part per standard item: a different size or axis is not this item's place
        out["at"] += at
        out["interfaces"].append(f["id"])
    if out is not None:
        return out
    for f in ifs:
        d = f["data"]
        if f["kind"] == "dowel" and d.get("pin_item") == item:
            ax = ax_of(d)  # (a hinge pin lies along Y: graph layout's pin joint)
            at = [[_r2(v) for v in point3(ax, xy, d["plane_z"] - d["length"] / 2)] for xy in d["positions"]]
            out_d = {"code": "dowel", "params": {"D": d["d"], "L": d["length"]}, "at": at, "interface": f["id"],
                     "title": f"Dowel pin ISO 8734 Ø{d['d']:g}×{d['length']:g}", "standard": "ISO 8734",
                     "what": "dowel holes" if ax == "z" else "pin bores"}
            if ax != "z":
                out_d["R"] = CANON[ax]
            return out_d
    return None


# ----------------------------------------------------------------------------- validation
def _dims_text(shape: str, size: list[float]) -> str:
    if shape == "cylinder":
        return f"Ø{size[0]:g} × {size[2]:g}"
    return " × ".join(f"{x:g}" for x in size)


def outgrown(it: dict[str, Any]) -> str | None:
    """The plain-language problem when a part is laid out more than PLAN_SLACK times its planned envelope in any
    direction (CD-029), else None. The designer must build to the laid-out envelope, so it can't pass silently."""
    pl = it.get("planned")
    if not pl:
        return None
    size = it["size"]
    worst = max(range(3), key=lambda k: size[k] / pl[k] if pl[k] else 0.0)
    if not pl[worst] or size[worst] <= PLAN_SLACK * pl[worst] + 1e-6:
        return None
    return (f"{it['name']}: laid out at {_dims_text(it['shape'], size)} mm, {size[worst] / pl[worst]:.1f} times the "
            f"{_dims_text(it['shape'], pl)} mm first planned for it, because what it carries or the bolts it needs "
            "take that room. The planned size was a starting estimate, so this is shown for review and does not "
            "block the gate; resize it on purpose if the space is limited.")


def _hole_words(h: dict[str, Any]) -> str:
    """A hole as the engineer reads it: its label without the running number, and its diameter."""
    lbl = re.sub(r"^(hole|tapped hole|dowel hole|clearance opening) \d+", r"\1", str(h.get("label") or "hole"))
    return lbl if "Ø" in lbl else f"{lbl} Ø{float(h['d']):g}"


def issues(skel: dict[str, Any], ifs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every problem of a layout, machine-readable: {"code", "severity", "text", "items": [item ids], "interfaces":
    [IF ids]}. ``code`` is stable (callers branch on it); ``severity`` "error" blocks the ICD gate (``problems``
    returns their texts), "warning" is shown at the gate and does not block (``warnings``):

      layout (the program doesn't assemble):
        ``row_layout``       nothing to mount the parts on, no shafts either: they are laid out in a row, unconnected
        ``no_interface``     a designed part with no interface (it would lie beside the program)
        ``bearing_unplaced`` (warning) bearings in the plan that no seat or journal takes: they go to the parts bin
        ``shaft_support``    a shaft of a shaft line that runs in fewer than two bearings (a warning when the plan
                             has no bearings at all: the shaft is delivered as a sub-assembly)
        ``line_clash``       two things on different shafts of a shaft line overlap (gears are taken at the pitch circle)
        ``journal_off_shaft`` a bearing beyond the end of its shaft
        ``layout_conflict``  the design graph's connections can't all hold (an over-constrained or inconsistent loop,
                             a part no connection reaches): it names the parts and connections
      geometry (a part can't be made):
        ``hole_diameter``, ``hole_edge``, ``rim``, ``cavity_breach``, ``hole_overlap``, ``keyway_rim``,
        ``washer_overlap``, ``fit_unknown``, ``bearing_depth``, ``bearing_wall``, ``bearing_bore``
        ``outgrown`` (warning) a part laid out well past its planned envelope (the plan was an estimate)
        ``ligament`` (warning) a bearing cap's tapped holes leave less than max(3 mm, 0.5 d) of wall to the seat
    """
    out: list[dict[str, Any]] = []
    warn: list[dict[str, Any]] = []

    def add(code: str, text: str, items: list[str] | None = None, ifaces: list[str] | None = None) -> None:
        out.append({"code": code, "text": text, "items": list(items or []), "interfaces": list(ifaces or [])})

    for i, it in skel["items"].items():
        big = outgrown(it)
        if big:  # a warning (founder rule 2026-11-20): the planned envelope is Archie's guess, not the brief's limit
            warn.append({"code": "outgrown", "items": [i], "interfaces": [], "text": big})
        L, _W, _H = it["size"]
        feats = item_features(skel, ifs, i)
        holes = [f for f in feats if f["type"] in ("hole", "seat")]
        if it.get("bore"):
            holes.append({"c": [0.0, 0.0], "d": it["bore"], "label": "bore"})
        cav = it.get("cavity")
        for h in holes:
            r = h["d"] / 2
            x, y = h["c"]
            hif = [h["if"]] if h.get("if") else []
            if h["d"] <= 0:
                add("hole_diameter", f"{it['name']}: {h.get('label', 'hole')} needs a positive diameter.", [i], hif)
                continue
            if it["shape"] == "box":
                half = [abs(v) / 2 for v in to_canon(h.get("ax") or "z", it["size"])]
                if abs(x) + r > half[0] - 1.0 or abs(y) + r > half[1] - 1.0:
                    add("hole_edge", f"{it['name']}: {h.get('label', 'hole')} Ø{h['d']:g} at ({x:g}, {y:g}) leaves "
                        "less than 1 mm of wall to the edge of its envelope.", [i], hif)
            else:
                rim = L / 2 - (math.hypot(x, y) + r)
                if it["role"] == "gear":
                    rim = it["module"] * it["teeth"] / 2 - 1.25 * it["module"] - (math.hypot(x, y) + r)
                if rim < 1.0 and it["role"] != "shaft":
                    add("rim", f"{it['name']}: {h.get('label', 'hole')} Ø{h['d']:g} leaves {max(rim, 0):.1f} mm of "
                        "material (at least 1 mm needed).", [i], hif)
            if cav and h["type"] == "hole" and not cav.get("open_through"):  # a hole must not break into a cavity
                lax = h.get("ax") or "z"
                lo_c = to_canon(lax, cav["min"])
                hi_c = to_canon(lax, cav["max"])
                bx = sorted((lo_c[0], hi_c[0]))
                by = sorted((lo_c[1], hi_c[1]))
                bz = sorted((lo_c[2], hi_c[2]))
                across = bx[0] - r - 1.0 < x < bx[1] + r + 1.0 and by[0] - r - 1.0 < y < by[1] + r + 1.0
                along = h.get("z0") is None or (h["z0"] < bz[1] + 1.0 and h["z1"] > bz[0] - 1.0)
                if across and along:
                    add("cavity_breach", f"{it['name']}: {h.get('label', 'hole')} Ø{h['d']:g} breaks into the gear "
                        "cavity.", [i], hif)
        for n, a in enumerate(holes):
            for b in holes[n + 1:]:
                if a.get("ax") != b.get("ax"):
                    continue
                if a.get("z0") is not None and b.get("z0") is not None and (a["z1"] <= b["z0"] or b["z1"] <= a["z0"]):
                    continue  # one behind the other along the axis (seats / tapped holes in opposite walls)
                if _near(a["c"][0], b["c"][0]) and _near(a["c"][1], b["c"][1]):
                    continue  # concentric: a seat over a clearance bore, a bore that is also a hole
                gap = math.hypot(a["c"][0] - b["c"][0], a["c"][1] - b["c"][1]) - (a["d"] + b["d"]) / 2
                if gap < 1.0:
                    wa, wb = _hole_words(a), _hole_words(b)
                    if gap < 0:  # the holes run into each other: say how, never a negative distance
                        dist = math.hypot(a["c"][0] - b["c"][0], a["c"][1] - b["c"][1])
                        inside = dist + min(a["d"], b["d"]) / 2 <= max(a["d"], b["d"]) / 2 + 1e-6
                        big, small = (a, b) if a["d"] >= b["d"] else (b, a)
                        how = (f"the {_hole_words(small)} lies inside the {_hole_words(big)}" if inside else
                               f"they overlap by {-gap:.1f} mm")
                        text = (f"{it['name']}: the {wa} at ({a['c'][0]:g}, {a['c'][1]:g}) and the {wb} at "
                                f"({b['c'][0]:g}, {b['c'][1]:g}) run into each other ({how}); they need at least "
                                "1 mm of material between them.")
                    else:
                        text = (f"{it['name']}: the {wa} at ({a['c'][0]:g}, {a['c'][1]:g}) and the {wb} at "
                                f"({b['c'][0]:g}, {b['c'][1]:g}) leave {gap:.1f} mm of material between them (at "
                                "least 1 mm needed).")
                    add("hole_overlap", text, [i], [x["if"] for x in (a, b) if x.get("if")])
        for k in (f for f in feats if f["type"] == "keyway" and f["on"] == "hub"):
            outer = (it["module"] * it["teeth"] / 2 - 1.25 * it["module"]) if it["role"] == "gear" else L / 2
            rim = outer - (k["d"] / 2 + k["depth"])
            if rim < 1.0:
                add("keyway_rim", f"{it['name']}: the keyway ({k['b']:g} wide, {k['depth']:g} deep) leaves "
                    f"{max(rim, 0):.1f} mm of material (at least 1 mm needed).", [i], [k["if"]])
    for f in ifs:
        if f["kind"] == "hole_pattern":  # the washers (ISO 7089) of neighbouring bolts must not overlap
            d = f["data"]
            m = max(int(d.get("fastener_size") or 3), bolt_for_hole(d["d"]))
            od = WASHER_OD.get(m, 2 * d["d"])
            pts = d["positions"]
            gap = min((math.hypot(a[0] - b[0], a[1] - b[1]) for k, a in enumerate(pts) for b in pts[k + 1:]),
                      default=math.inf)
            if gap < od - 1e-6:
                add("washer_overlap", f"{f['id']}: Ø{d['d']:g} holes take M{m} bolts, whose washers (Ø{od:g}) "
                    f"overlap at {gap:.1f} mm between hole centres.", [f["a"]["item"], f["b"]["item"]], [f["id"]])
            if d.get("seat_D") and d.get("pcd") and d.get("tapped"):  # a bearing cap's tapped holes beside the seat
                lig = float(d["pcd"]) / 2 - float(d["seat_D"]) / 2 - float(d["tapped"]["d"]) / 2
                need = max(LIGAMENT, LIGAMENT_D * int(d.get("fastener_size") or 0))
                if lig < need - 1e-6:
                    warn.append({"code": "ligament", "items": [f["a"]["item"], f["b"]["item"]], "interfaces": [f["id"]],
                                 "text": f"{f['id']}: the {d['fastener']} tapped holes on PCD {d['pcd']:g} leave {lig:.1f} mm "
                                         f"of wall to the Ø{d['seat_D']:g} bearing seat (at least {need:g} mm wanted). "
                                         "Use smaller cap screws or a larger PCD."})
        if f["kind"] == "shaft_bore":
            h, s = fit_zones(f["data"]["d"], f["data"]["fit"])
            if h is None or s is None:
                add("fit_unknown", f"{f['id']}: fit {f['data']['fit']} is not in the ISO 286 table used here.",
                    [f["a"]["item"], f["b"]["item"]], [f["id"]])
        if f["kind"] == "bearing_seat":
            d = f["data"]
            if zone(d["D"], d["housing_fit"]) is None or zone(d["d"], d["shaft_fit"]) is None:
                add("fit_unknown", f"{f['id']}: fit {d['housing_fit']} / {d['shaft_fit']} is not in the ISO 286 "
                    "table used here.", [f["a"]["item"], f["b"]["item"]], [f["id"]])
            host = skel["items"][f["a"]["item"]]
            deep = host["size"][AXIS_INDEX[ax_of(d)]]
            if d["count"] * d["B"] > deep + 1e-6:
                add("bearing_depth", f"{f['id']}: {d['count']} bearings {d['designation']} ({d['B']:g} wide) don't "
                    f"fit in the {deep:g} mm deep {host['name']}.", [f["a"]["item"]], [f["id"]])
            wall = (host.get("cavity") or {}).get("wall")
            if wall is not None and d["B"] + 1.0 > wall + 1e-6:
                add("bearing_wall", f"{f['id']}: the {d['B']:g} mm wide bearing {d['designation']} needs a wall of at "
                    f"least {d['B'] + 1:g} mm; the {host['name']} walls are {wall:g} mm.", [f["a"]["item"]], [f["id"]])
        if f["kind"] == "bearing_journal":
            d = f["data"]
            sh = skel["items"].get(f["a"]["item"])
            if zone(d["d"], d["shaft_fit"]) is None:
                add("fit_unknown", f"{f['id']}: fit {d['shaft_fit']} is not in the ISO 286 table used here.",
                    [f["a"]["item"]], [f["id"]])
            if sh and float(d["d"]) > float(sh.get("d") or sh["size"][0]) + 1e-9:
                add("bearing_bore", f"{f['id']}: bearing {d['designation']} has a {d['d']:g} mm bore, larger than "
                    f"the Ø{sh.get('d') or sh['size'][0]:g} {sh['name']}.", [f["a"]["item"]], [f["id"]])
            if sh:
                c = sh["copies"][f["a"]["copy"]]
                k = AXIS_INDEX[ax_of(d)]
                lo, hi = c[k] - sh["size"][2] / 2, c[k] + sh["size"][2] / 2
                if d["z"][0] < lo - 1e-6 or d["z"][1] > hi + 1e-6:
                    add("journal_off_shaft", f"{sh['name']}: bearing {d['designation']} ({f['id']}) sits beyond the "
                        f"end of the shaft ({sh['size'][2]:g} mm long): lengthen the shaft or move the bearing.",
                        [f["a"]["item"]], [f["id"]])
    for x in out:
        x["severity"] = "error"
    return (out + [{"severity": "error", **x} for x in _layout_issues(skel, ifs)] + _bearing_issues(skel, ifs)
            + [{**x, "severity": "warning"} for x in warn])


def _layout_issues(skel: dict[str, Any], ifs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Layouts that don't assemble (the founder's "parts on the floor"): never silent at the ICD gate."""
    out: list[dict[str, Any]] = []
    items = skel.get("items") or {}
    if skel.get("layout") == "row" and len(set(items) - set(skel.get("separate") or [])) > 1:
        out.append({"code": "row_layout", "items": sorted(items), "interfaces": [],
                    "text": "Layout: there is nothing to mount the parts on (no base plate, housing or frame) and no "
                            "shaft to carry them, so they are laid out in a row with no interfaces and would not be "
                            "assembled. Add a base plate or housing to the plan, or the shafts the parts sit on."})
    for c in skel.get("conflicts") or []:  # the graph layout's solve (graph/layout.py): never silent, never guessed
        out.append({"code": "layout_conflict", "items": list(c.get("items") or []), "interfaces": [],
                    "parts": list(c.get("parts") or []), "connections": list(c.get("connections") or []),
                    "text": c["text"]})
    for w in skel.get("findings") or []:  # a measured layout's findings (master model, WORKLIST 50): shown at the gate
        out.append({"code": str(w.get("code") or "master"), "severity": str(w.get("severity") or "warning"),
                    "items": list(w.get("items") or []), "interfaces": list(w.get("interfaces") or []),
                    "text": str(w.get("text") or "")})
    linked = {f[w]["item"] for f in ifs for w in ("a", "b")}
    separate = set(skel.get("separate") or [])
    if len(items) > 1:
        for i, it in items.items():
            if i in linked:
                continue
            if i in separate:  # the engineer's recorded decision at the gate: shown, never blocking
                out.append({"code": "no_interface", "severity": "warning", "acknowledged": True, "items": [i],
                            "interfaces": [],
                            "text": f"{it['name']}: kept as a separate part (your decision at the interfaces gate). "
                                    "No interface connects it, so Fitz places it beside the assembly."})
                continue
            out.append({"code": "no_interface", "items": [i], "interfaces": [],
                        "text": f"{it['name']}: no interface connects it to the rest of the program, so it would "
                                "be placed beside the assembly, unconnected. Say what it mounts on (or resize the "
                                "part it should fit), remove it from the plan, or keep it as a separate part."})
        # every copy, not just the item: leg #2 of four with no interface floats beside the program (founder's
        # "TEST Project", 2026-11-20: the gate passed per item, Assemble Legs then found leg #2 floating)
        linked_c = {(f[w]["item"], int(f[w].get("copy") or 0)) for f in ifs for w in ("a", "b")}
        for i, it in items.items():
            if i not in linked or i in separate or len(it.get("copies") or []) < 2:
                continue
            for c in range(len(it["copies"])):
                if (i, c) not in linked_c:
                    out.append({"code": "no_interface", "items": [i], "interfaces": [], "copy": c,
                                "text": f"{it['name']} #{c + 1}: no interface connects this copy (the others are "
                                        "connected), so it would be placed beside the assembly, unconnected. Each "
                                        "copy needs its own joint: say what each one mounts on, or plan fewer."})
    if skel.get("layout") != "shaft_line":
        return out
    # a shaft line: two bearings per shaft, and nothing on one shaft overlapping another shaft's parts
    shafts = [i for i, it in items.items() if it["role"] == "shaft"]
    nb = {i: 0 for i in shafts}
    for f in ifs:
        if f["kind"] == "bearing_journal" and f["a"]["item"] in nb:
            nb[f["a"]["item"]] += 1
    # no bearing anywhere in the plan (and, in a shaft line, no housing): the shaft with what it carries is the
    # deliverable, a sub-assembly. Said at the gate, never blocking (founder 2026-11-19). Bearings that are planned
    # but don't carry a shaft still block.
    no_bearings = not any(_BEARINGY.search(str(st.get("name") or "")) for st in skel.get("standard") or [])
    for i in shafts:
        if nb[i] < 2 and i not in separate:
            if nb[i] == 0 and no_bearings:
                out.append({"code": "shaft_support", "severity": "warning", "items": [i], "interfaces": [],
                            "text": f"{items[i]['name']}: no bearings or housing in the plan, so it is delivered as a "
                                    "sub-assembly (the shaft with what it carries); what carries it is outside this "
                                    "program."})
                continue
            out.append({"code": "shaft_support", "items": [i], "interfaces": [],
                        "text": f"{items[i]['name']}: runs in {nb[i]} bearing{'s' if nb[i] != 1 else ''}; a shaft "
                                "with no housing needs two (one either side of what it carries). Plan two more "
                                "bearings per shaft, or a housing."})
    out += _line_clashes(skel, ifs)
    return out


def _bearing_issues(skel: dict[str, Any], ifs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bearings of the plan that no bearing seat or journal takes (warnings: Fitz puts them in the parts bin)."""
    out: list[dict[str, Any]] = []
    for st in skel.get("standard") or []:
        if not _BEARINGY.search(st.get("name") or "") or re.search(r"screw|bolt|\bnut|washer", st.get("name") or "",
                                                                    re.IGNORECASE):
            continue  # ("Bearing cap screws" are screws)
        placed = len((seated(ifs, st["item"]) or {}).get("at") or [])
        want = int(st.get("qty") or 0)
        if placed < want:
            out.append({"code": "bearing_unplaced", "severity": "warning", "items": [st["item"]], "interfaces": [],
                        "text": f"{st['name']}: {want - placed} of {want} have no bearing seat or journal in this "
                                "layout, so Fitz will leave them in the parts bin. A bearing needs a shaft and a "
                                "housing (or the shaft's own journals, with no housing) in the same program: add them "
                                "to the plan, or plan fewer bearings."})
    # every other bought-out part (a pin, a key, a ring, an oil plug) that no interface places: said at the gate,
    # never vanishing silently (golden suite F3). Fasteners, nuts and washers are placed by the bolted joints' stacks.
    named = {str(v) for f in ifs for k, v in (f.get("data") or {}).items()
             if k in ("fastener_item", "key_item", "ring_item", "pin_item", "bearing_item", "cap_item") and v}
    for st in skel.get("standard") or []:
        nm = st.get("name") or ""
        if _BEARINGY.search(nm) or re.search(r"screw|bolt|\bnut|washer|\bstud", nm, re.IGNORECASE) \
                or st["item"] in named or seated(ifs, st["item"]):
            continue
        out.append({"code": "part_unplaced", "severity": "warning", "items": [st["item"]], "interfaces": [],
                    "text": f"{nm}: no interface in this layout places it, so Fitz can't fit it in the assembly (it "
                            "stays in the bill of materials and the parts bin). Say what it fits into, or remove it "
                            "from the plan."})
    return out


def _line_clashes(skel: dict[str, Any], ifs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cylinders of a shaft line (shafts, gears at their pitch circle, hubs, bearings at their OD) on different shaft
    axes whose radial and axial extents overlap by more than 0.05 mm."""
    items = skel.get("items") or {}
    cyl: list[tuple[str, str, float, float, float, float, str]] = []  # (axis key, name, x, z, r, y0..y1), item
    rider_of: dict[str, str] = {}
    for f in ifs:
        if f["kind"] == "shaft_bore" and (items.get(f["b"]["item"]) or {}).get("role") == "shaft":
            rider_of[f["a"]["item"]] = f["b"]["item"]
    for i, it in items.items():
        if it.get("ax") != "y" or it["role"] not in ("shaft", "gear", "hub"):
            continue
        r = it["module"] * it["teeth"] / 2 if it["role"] == "gear" else it["size"][0] / 2
        for c in it["copies"]:
            cyl.append((f"{_r2(c[0])},{_r2(c[2])}", it["name"], c[0], c[2], r, c[1] - it["size"][2] / 2,
                        c[1] + it["size"][2] / 2, i))  # type: ignore[arg-type]
    for f in ifs:
        if f["kind"] == "bearing_journal":
            d = f["data"]
            cyl.append((f"{_r2(d['axis'][0])},{_r2(d['axis'][1])}", f["b"]["name"], d["axis"][0], d["axis"][1],
                        d["D"] / 2, d["z"][0], d["z"][1], f["b"]["item"]))  # type: ignore[arg-type]
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for n, a in enumerate(cyl):
        for b in cyl[n + 1:]:
            if a[0] == b[0]:
                continue  # the same shaft axis: riders and bearings stack along it
            gap = math.hypot(a[2] - b[2], a[3] - b[3]) - a[4] - b[4]
            if gap > -0.05 or min(a[6], b[6]) - max(a[5], b[5]) <= 0.05:  # type: ignore[operator]
                continue
            key = (min(a[1], b[1]), max(a[1], b[1]))
            if key in seen:
                continue
            seen.add(key)
            out.append({"code": "line_clash", "items": sorted({a[7], b[7]}), "interfaces": [],  # type: ignore[index]
                        "text": f"Layout: {a[1]} and {b[1]} overlap by {-gap:.1f} mm across their shafts. Use smaller "
                                "bearings or gears, or a larger centre distance."})
    return out


def warnings(skel: dict[str, Any], ifs: list[dict[str, Any]]) -> list[str]:
    """Plain-language layout warnings (shown at the ICD gate, not blocking): bearings no seat or journal takes, and
    parts the engineer kept separate."""
    return [x["text"] for x in issues(skel, ifs) if x["severity"] == "warning"]


def problems(skel: dict[str, Any], ifs: list[dict[str, Any]]) -> list[str]:
    """Plain-language problems of a layout (``issues`` has the codes and the items / interfaces they name): geometry
    that can't be made (holes outside or too close to the edge of their part, overlapping holes, a bore that leaves
    no rim, a gear bore or keyway through the teeth, a part laid out far beyond its planned envelope) and layouts that
    don't assemble (parts in a row, a part with no interface, bearings with no seat, a shaft line that clashes)."""
    return [x["text"] for x in issues(skel, ifs) if x["severity"] == "error"]


# ----------------------------------------------------------------------------- the ICD document
def new_icd(parts: list[dict[str, Any]], brief: str, actor: str, overrides: dict[str, Any] | None = None,
            built: tuple[dict[str, Any], list[dict[str, Any]]] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """The draft ICD document. ``built``: a layout already solved (the design graph's, ``graph/layout.py``)."""
    skel, ifs = built if built is not None else build(parts, brief, overrides)
    icd = {"version": 1, "status": "draft", "interfaces": ifs, "overrides": overrides or {"items": {}, "interfaces": {}},
           "history": [{"version": 1, "at": None, "by": actor, "kind": "created",
                        "text": f"Archie laid out the program and named {len(ifs)} interfaces.", "changes": []}],
           "problems": problems(skel, ifs)}
    return skel, icd


def iface(icd: dict[str, Any], iid: str) -> dict[str, Any] | None:
    return next((f for f in icd["interfaces"] if f["id"] == iid), None)


def clean_values(f: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Validate an edit / change request on one interface: only its editable numbers, in sane ranges."""
    from aicad.office import OfficeInputError

    allowed = EDITABLE[f["kind"]]
    out: dict[str, Any] = {}
    for k, v in (values or {}).items():
        if k not in allowed:
            raise OfficeInputError(f"{k} can't be changed on a {KIND_LABEL[f['kind']]}.")
        if k == "fit":
            if str(v) not in FITS:
                raise OfficeInputError(f"Fit must be one of {', '.join(FITS)}.")
            out[k] = str(v)
            continue
        if k == "fastener":
            m = int(str(v).upper().lstrip("M") or 0) if str(v).upper().lstrip("M").isdigit() else 0
            if m not in CLEARANCE:
                raise OfficeInputError(f"Fastener must be one of {', '.join(f'M{x}' for x in CLEARANCE)}.")
            out[k] = m
            continue
        if k == "housing_fit":
            if str(v) not in HOUSING_FITS:
                raise OfficeInputError(f"Housing fit must be one of {', '.join(HOUSING_FITS)}.")
            out[k] = str(v)
            continue
        if k == "designation":
            des = int(float(v)) if str(v).replace(".", "", 1).isdigit() else 0
            if des not in BEARINGS:
                raise OfficeInputError("Bearing must be one of " + ", ".join(str(x) for x in sorted(BEARINGS)) + ".")
            if BEARINGS[des][0] > float(f["data"]["d"]) + 1e-9 and BEARINGS[des][0] > _shaft_d(f):
                raise OfficeInputError(f"Bearing {des} has a {BEARINGS[des][0]:g} mm bore: larger than the shaft.")
            out[k] = des
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise OfficeInputError(f"{k} must be a number.") from None
        if not math.isfinite(x) or x <= 0 or x > 5000:
            raise OfficeInputError(f"{k} must be a positive size.")
        if k in ("count", "teeth_a", "teeth_b"):
            if abs(x - round(x)) > 1e-9:
                raise OfficeInputError(f"{k} must be a whole number.")
            x = round(x)
            if k == "count" and x not in (2, 3, 4, 6, 8):
                raise OfficeInputError("A bolt pattern has 2, 3, 4, 6 or 8 holes.")
            if k != "count" and not 8 <= x <= 300:
                raise OfficeInputError("Teeth must be between 8 and 300.")
        if f["kind"] == "dowel" and k == "d" and not 3 <= x <= 16:
            raise OfficeInputError("Dowel pins here are 3 to 16 mm.")
        out[k] = x
    if not out:
        raise OfficeInputError("Nothing to change.")
    return out


def _shaft_d(f: dict[str, Any]) -> float:
    """The shaft Ø behind a bearing seat (its journal is the bearing bore; the shaft may be larger)."""
    return float(f["data"].get("shaft_d") or f["data"]["d"])


def apply_values(overrides: dict[str, Any], f: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """New overrides with ``values`` on interface ``f`` (shaft Ø and gear numbers live on their items)."""
    ov = copy.deepcopy(overrides or {})
    ov.setdefault("items", {})
    ov.setdefault("interfaces", {})
    mine = dict(ov["interfaces"].get(f["id"]) or {})
    for k, v in values.items():
        if f["kind"] == "shaft_bore" and k == "d":
            shaft = f["b"]["item"]
            ov["items"].setdefault(shaft, {})["d"] = v
        elif f["kind"] in ("bearing_seat", "bearing_journal") and k == "designation":  # on the shaft item
            ov["items"].setdefault(f["b" if f["kind"] == "bearing_seat" else "a"]["item"], {})["designation"] = v
        elif f["kind"] == "gear_mesh" and k in ("module", "teeth_a", "teeth_b"):
            if k == "module":
                ov["items"].setdefault(f["a"]["item"], {})["module"] = v
                ov["items"].setdefault(f["b"]["item"], {})["module"] = v
            else:
                ov["items"].setdefault(f["a" if k == "teeth_a" else "b"]["item"], {})["teeth"] = v
        else:
            mine[k] = v
            if k == "fastener" and "d" not in values:
                mine.pop("d", None)
    if mine:
        ov["interfaces"][f["id"]] = mine
    return ov


def freeze(skel: dict[str, Any], ifs: list[dict[str, Any]], overrides: dict[str, Any]) -> dict[str, Any]:
    """At ICD approval the envelopes are frozen (later changes must fit inside them), and so are the bolt patterns'
    edge distance and hole count, so a change to a hole Ø keeps the holes where they are."""
    ov = copy.deepcopy(overrides or {})
    ov.setdefault("items", {})
    ov.setdefault("interfaces", {})
    for f in ifs:
        if f["kind"] == "hole_pattern":
            o = ov["interfaces"].setdefault(f["id"], {})
            o.setdefault("count", f["data"]["count"])
            o.setdefault("fastener", f["data"]["fastener_size"])
            if f["data"].get("inset") is not None:
                o.setdefault("inset", f["data"]["inset"])
    for i, it in skel["items"].items():
        o = ov["items"].setdefault(i, {})
        r = it["role"]
        L, W, H = it["size"]
        if r == "block":
            o.update(L=L, W=W, H=H, rot=int(it.get("rot") or 0))
        elif r == "shaft":
            o.update(length=H)
        elif r == "hub":
            o.update(OD=L, H=H)
    return ov


def diff(old_s: dict[str, Any], old_i: list[dict[str, Any]], new_s: dict[str, Any], new_i: list[dict[str, Any]]
         ) -> dict[str, Any]:
    """What changed between two ICD builds: interfaces (field by field), item envelopes and positions, and which
    items' local features changed (the tickets to reopen)."""
    changes: list[dict[str, Any]] = []
    ob = {f["id"]: f for f in old_i}
    nb = {f["id"]: f for f in new_i}
    for iid in sorted(set(ob) | set(nb)):
        a, b = ob.get(iid), nb.get(iid)
        if a is None or b is None:
            changes.append({"interface": iid, "field": "interface", "before": a and a["name"], "after": b and b["name"]})
            continue
        for k in sorted(set(a["data"]) | set(b["data"])):
            if a["data"].get(k) != b["data"].get(k):
                changes.append({"interface": iid, "name": b["name"], "field": k, "before": a["data"].get(k),
                                "after": b["data"].get(k)})
    env, moved, feats = [], [], []
    for i in sorted(set(old_s["items"]) | set(new_s["items"])):
        a, b = old_s["items"].get(i), new_s["items"].get(i)
        if a is None or b is None:
            env.append(i)
            continue
        if a["size"] != b["size"]:
            env.append(i)
        if a["copies"] != b["copies"]:
            moved.append(i)
        if json.dumps(item_features(old_s, old_i, i), sort_keys=True) != json.dumps(item_features(new_s, new_i, i),
                                                                                      sort_keys=True):
            feats.append(i)
    return {"changes": changes, "envelope_changed": env, "moved": moved, "features_changed": feats}


def describe_change(c: dict[str, Any]) -> str:
    def fmt(v: Any) -> str:
        if isinstance(v, float):
            return f"{v:g}"
        if isinstance(v, list) and len(v) > 4:
            return f"{len(v)} positions"
        return json.dumps(v, ensure_ascii=False) if isinstance(v, list | dict) else str(v)

    return f"{c['interface']} {c['field']}: {fmt(c['before'])} → {fmt(c['after'])}"


# ----------------------------------------------------------------------------- the excerpt for a part agent
def _fmt_xy(c: list[float]) -> str:
    return f"({c[0]:g}, {c[1]:g})"


_ACROSS = {"z": ("X", "Y", 0, 1), "y": ("X", "Z", 0, 2), "x": ("Y", "Z", 1, 2)}


def _at(x: dict[str, Any]) -> str:
    """Where a feature's axis is, in part-frame words: "the axis at (X, Y) (a, b)" or, along Y, "the axis along Y
    at (X, Z) (a, b)"."""
    lax = x.get("ax") or "z"
    u, v, i, j = _ACROSS[lax]
    q = from_canon(lax, [x["c"][0], x["c"][1], 0.0])
    where = f"({u}, {v}) ({_r2(q[i]):g}, {_r2(q[j]):g})"
    return f"the axis at {where}" if lax == "z" else f"the axis along {lax.upper()} at {where}"


def _span(x: dict[str, Any]) -> str:
    return f"from {(x.get('ax') or 'z').upper()} {x['z0']:g} to {x['z1']:g}"


def excerpt(skel: dict[str, Any], icd: dict[str, Any], item: str) -> str:
    """The ICD for one part, in plain words plus a machine-readable ``fw-icd`` block (part frame)."""
    it = skel["items"].get(item)
    if not it:
        return ""
    L, W, H = it["size"]
    shape = (f"box {L:g} × {W:g} × {H:g} mm (X × Y × Z)" if it["shape"] == "box"
             else f"cylinder Ø{L:g} × {H:g} mm along Z")
    turn = (f"turned {int(it['rot'])}° about +Z from the program axes" if it.get("rot")
            else f"turned {it['phase']:g}° about +Z from the program axes (tooth phasing for its mesh: a tooth "
                 f"{'space ' if it.get('internal') else ''}is centred on +X of the part frame)" if it.get("phase")
            else "axes parallel to the program axes")
    if it.get("ax"):
        turn = (f"its +Z laid along program +{it['ax'].upper()} (a horizontal shaft line; model it along Z as "
                "usual)" + ("" if turn.startswith("axes") else f", then {turn}"))
    head = (f"Interfaces (ICD v{icd['version']}, approved). Model this part in its part frame: origin at the centre "
            f"of its envelope, +Z up, {turn}. Envelope: {shape}; the part must stay inside it.")
    lines = [head]
    mine = [f for f in icd["interfaces"] if item in (f["a"]["item"], f["b"]["item"])]
    seen: set[str] = set()
    for f in mine:
        which = "a" if f["a"]["item"] == item else "b"
        feats = side_features(skel, f, which)
        key = json.dumps([(x["type"], x.get("c"), x.get("z"), x.get("d"), x.get("z0"), x.get("z1")) for x in feats])
        if key in seen:
            continue
        seen.add(key)
        d = f["data"]
        bits = []
        for x in feats:
            if x["type"] == "face":
                A = (x.get("ax") or "z").upper()
                bits.append(f"{x['label']} at {A} {x['z']:g} (normal {'+' if x['n'] > 0 else '−'}{A}, flatness "
                            f"{d.get('flatness', FLATNESS):g})")
            elif x["type"] == "hole":
                pass
            elif x["type"] == "boss":
                span = f" {_span(x)}" if x.get("z0") is not None else ""
                if not span and f["kind"] == "shaft_bore" and d.get("z"):  # where the hub / gear sits on the shaft
                    g = _axial(skel, f[which], d, d["axis"], d["z"][0], d["z"][1])
                    span = f", where {f['a']['name']} sits {_span(g)}"
                bits.append(f"{x['label']} on {_at(x)}{span}")
            elif x["type"] == "seat":
                bits.append(f"{x['label']} on {_at(x)}, {_span(x)}")
            elif x["type"] == "keyway":
                lax = x.get("ax") or "z"
                u, v, i, j = _ACROSS[lax]
                dv = from_canon(lax, [x["dir"][0], x["dir"][1], 0.0])
                bits.append(f"{x['label']}: {x['b']:g} wide, {x['depth']:g} deep from the "
                            f"{'bore' if x['on'] == 'hub' else 'shaft surface'}, on the ({u}, {v}) "
                            f"({_r2(dv[i]):g}, {_r2(dv[j]):g}) side of {_at(x)}, {_span(x)}")
            elif x["type"] == "groove":
                bits.append(f"{x['label']}: groove bottom Ø{x['d']:g} (depth {d['t']:g} on the Ø{d['d']:g} shaft), "
                            f"{d['m']:g} wide, on {_at(x)}, {_span(x)}, at least {d['n']:g} from the shaft end; the "
                            f"{d['ring']} bears on the {d['against']} face there")
            elif x["type"] == "gear":
                bits.append(f"{x['label']}, pressure angle {d['pressure_angle']:g}°, face width {d['face_width']:g}, "
                            f"centre distance {d['centre_distance']:g} to its mate")
        holes = [x for x in feats if x["type"] == "hole"]

        def where(h: dict[str, Any]) -> str:
            lax = h.get("ax") or "z"
            _u, _v, i, j = _ACROSS[lax]
            q = from_canon(lax, [h["c"][0], h["c"][1], 0.0])
            return f"({_r2(q[i]):g}, {_r2(q[j]):g})"

        if holes and holes[0].get("thread"):
            h0 = holes[0]
            lax = h0.get("ax") or "z"
            u, v, _i, _j = _ACROSS[lax]
            bits.append(f"{len(holes)} × {h0['thread']} tapped holes (tap drill Ø{h0['d']:g}, blind, "
                        f"{abs(h0['z1'] - h0['z0']):g} deep from the mounting face, along {lax.upper()}) at ({u}, {v}) "
                        + ", ".join(where(h) for h in holes))
        elif holes:
            if f["kind"] == "shaft_bore" and holes[0].get("span"):
                bits.append(f"{holes[0]['label']}, {_at(holes[0])}, {_span(holes[0])} (a stepped bore: it runs from "
                            "the coupling's end face to the middle, where the other shaft's bore meets it)")
            elif f["kind"] == "shaft_bore":
                bits.append(f"{holes[0]['label']} through, {_at(holes[0])}")
            elif f["kind"] == "dowel":
                bits.append(f"{len(holes)} × Ø{holes[0]['d']:g} {holes[0].get('fit') or ''} dowel holes through for "
                            f"{d['standard']} pins Ø{d['d']:g} × {d['length']:g}, at (X, Y) "
                            + ", ".join(_fmt_xy(h["c"]) for h in holes))
            else:
                lax = holes[0].get("ax") or "z"
                u, v, _i, _j = _ACROSS[lax]
                bits.append(f"{len(holes)} × Ø{holes[0]['d']:g} through ({d['fastener']} clearance"
                            + (f", along {lax.upper()}" if lax != "z" else "") + f") at ({u}, {v}) "
                            + ", ".join(where(h) for h in holes))
        if f["kind"] in ("bearing_seat", "bearing_journal"):
            bits.insert(0, f"{d['count']} × {d['bearing']} (bore {d['d']:g}, OD {d['D']:g}, width {d['B']:g})")
        if f["kind"] == "hole_pattern" and d.get("cap") and which == "b":
            bits.insert(0, (f"an open cap: the shaft passes through its Ø{it['bore']:g} bore (seal there)"
                            if d["cap"] == "open" and it.get("bore") else "a blind cap: closed, no bore")
                        + f", over the Ø{d['seat_D']:g} seat of bearing {d['bearing']}; flat mounting face (the "
                        "bearing's outer ring is flush with the wall face, so no spigot)")
        lines.append(f"- {f['id']} {f['name']}: " + "; ".join(bits) + f" (position tolerance ±{d.get('position_tol', POS_TOL):g}).")
    cav = it.get("cavity")
    if cav and cav.get("kind") == "pocket":  # the open pocket of a master body (an L bracket's inside corner)
        lines.append(f"- Open pocket (keep clear, {cav.get('note') or 'a mating part sits there'}): X {cav['min'][0]:g} "
                     f"to {cav['max'][0]:g}, Y {cav['min'][1]:g} to {cav['max'][1]:g}, Z {cav['min'][2]:g} to "
                     f"{cav['max'][2]:g} (open on {', '.join(cav.get('open') or []) or 'no side'}).")
    elif cav and cav.get("open_through"):  # a slot (a clevis between its lugs: graph layout's pin joint)
        lines.append(f"- Slot (keep clear, {cav.get('note') or 'a part moves there'}): X {cav['min'][0]:g} to "
                     f"{cav['max'][0]:g} (open at both ends), Y {cav['min'][1]:g} to {cav['max'][1]:g}, Z "
                     f"{cav['min'][2]:g} up to the top face; lugs {cav['wall']:g} thick, floor {cav['floor']:g} mm.")
    elif cav:
        lines.append(f"- Gear cavity (keep clear, the gears run there): X {cav['min'][0]:g} to {cav['max'][0]:g}, "
                     f"Y {cav['min'][1]:g} to {cav['max'][1]:g}, Z {cav['min'][2]:g} up to the top face (open, the "
                     f"lid closes it); side walls {cav['wall']:g}, end walls {cav['end_wall']:g}, floor "
                     f"{cav['floor']:g} mm.")
    if len(lines) == 1:
        lines.append("- No interfaces: this part only has to fit its envelope.")
    lines.append("Do not change an interface on your own. If one can't work, keep designing to the ICD and raise a "
                 "change request with exactly one block:\n```fw-change-request\n{\"interface\": \"IF-01\", \"values\": "
                 "{\"d\": 9}, \"reason\": \"one sentence\"}\n```")
    data = {"item": item, "version": icd["version"], "shape": it["shape"], "size": it["size"],
            "features": [{k: v for k, v in x.items() if k not in ("also",)} for x in item_features(skel, icd["interfaces"], item)]}
    if it.get("bore"):
        data["bore"] = it["bore"]
    if cav:
        data["cavity"] = {"min": cav["min"], "max": cav["max"]}
    if any(x.get("ax") for x in data["features"]):
        data["frames"] = ("features with \"ax\" run along that part axis and are written turned so that axis is "
                          "their Z: ax y -> part (X, Y, Z) = (c0, z, -c1); ax x -> (z, c1, -c0)")
    if it["role"] == "gear":
        data["gear"] = {"module": it["module"], "teeth": it["teeth"], "face_width": it["face_width"]}
        if it.get("internal"):  # a ring gear: internal teeth (tip inside, root outside), a tooth space on +X
            m, z = float(it["module"]), int(it["teeth"])
            data["gear"].update(internal=True, tip_d=round(m * (z - 2), 4), root_d=round(m * (z + 2.5), 4))
    lines.append("```fw-icd\n" + json.dumps(data, separators=(",", ":")) + "\n```")
    return "\n".join(lines)


_CR = re.compile(r"```fw-change-request\s*\n(.*?)\n?```", re.DOTALL)


def parse_change_request(text: str) -> dict[str, Any] | None:
    """The last valid change-request block in a part agent's answer."""
    for m in reversed(list(_CR.finditer(text or ""))):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(d, dict) and isinstance(d.get("interface"), str) and isinstance(d.get("values"), dict):
            from aicad.agent.session import scrub

            return {"interface": d["interface"].strip()[:20], "values": d["values"],
                    "reason": scrub(" ".join(str(d.get("reason") or "").split()))[:400]}
    return None
