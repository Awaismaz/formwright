"""The program skeleton and the Interface Control Document (CD-010, plan §2.1).

Before any part ticket is released, Archie lays the program out and names every interface between two items, with
numbers. Everything here is pure and deterministic: ``build(parts, brief, overrides)`` returns the same skeleton and
the same ICD for the same input, so an edit at the ICD gate or an accepted change request is "set an override and
build again", and interface ids stay stable.

Skeleton (the program coordinate system and the conceptual layout)
  * Program frame = datum reference frame A|B|C: A is the top face of the program base (plane Z = 0, +Z up),
    B the mid-plane Y = 0, C the mid-plane X = 0. Millimetres.
  * Every designed part gets a role and an envelope: ``block`` (prismatic box L x W x H), ``shaft`` (cylinder along
    Z), ``hub`` (a turned ring / collar / pulley along Z) or ``gear`` (pitch cylinder m.z x face width along Z).
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

# ----------------------------------------------------------------------------- constants (documented, PD-xx)
CLEARANCE = {3: 3.4, 4: 4.5, 5: 5.5, 6: 6.6, 8: 9.0, 10: 11.0, 12: 13.5, 16: 17.5}  # ISO 273 medium series
WASHER_OD = {3: 7.0, 4: 9.0, 5: 10.0, 6: 12.0, 8: 16.0, 10: 20.0, 12: 24.0, 16: 30.0}  # ISO 7089
GAP = 12.0          # mm between stations on a block's top face
MARGIN = 10.0       # mm from a block's edge to its first station
MAX_COPIES = 8      # copies of one part laid out in the skeleton (the rest are noted)
POS_TOL = 0.1       # mm: default position tolerance of interface features
FLATNESS = 0.05     # mm: default flatness of a mounting face
PRESSURE_ANGLE = 20.0
KIND_LABEL = {"hole_pattern": "bolted joint", "shaft_bore": "shaft / bore fit", "face": "seating face",
              "gear_mesh": "gear mesh"}
EDITABLE = {"hole_pattern": ("fastener", "d", "count", "inset", "flatness", "position_tol"),
            "shaft_bore": ("d", "fit"), "face": ("flatness", "position_tol"),
            "gear_mesh": ("module", "teeth_a", "teeth_b")}

_SHAFTY = re.compile(r"shaft|axle|spindle|lead screw|ball screw|journal|arbor|\broller\b|\bpin\b", re.IGNORECASE)
_HUBBY = re.compile(r"cap|collar|spacer|bush|hub|pulley|ring|flange|locator|sleeve|wheel|drum|washer|disc|disk", re.IGNORECASE)
_NUM = r"(\d+(?:\.\d+)?)"


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


def parts_from(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The designed and standard parts of an approved program, in plan order, with what the layout needs."""
    plan = doc.get("plan") or {}
    hints: dict[str, dict[str, Any]] = {}
    for s in plan.get("subassemblies") or []:
        for p in s.get("parts") or []:
            hints[f"i_{s['id']}_{p['id']}"] = {k: p.get(k) for k in ("envelope", "mounts_on", "module", "teeth")
                                               if p.get(k) is not None}
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
        if env:
            d, length = float(min(env[0], env[1])), float(env[2])
            src = "plan"
        elif dia:
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
    # fastener size hints from standard parts of the same sub-assembly
    fast_hint: dict[str, int] = {}
    fast_item: dict[str, str] = {}
    for p in parts:
        if p["family"] == "standard" and re.search(r"bolt|screw", f"{p['name']} {p['description']}", re.IGNORECASE):
            fast_item.setdefault(p["sub"], p["id"])
            h = _fastener_hint(f"{p['name']} {p['description']}")
            if h:
                fast_hint.setdefault(p["sub"], h)

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
        sub_base[sb] = max(blocks, key=lambda i: (area(i), -mine.index(i))) if blocks else (shafts or mine)[0]
    bases = [sub_base[s] for s in subs if s in sub_base]
    block_bases = [b for b in bases if spec[b]["role"] == "block"]
    prog_base = max(block_bases, key=lambda i: (area(i), -bases.index(i))) if block_bases else (bases[0] if bases else None)
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
            shaft = next((q["id"] for q in designed if q["sub"] == p["sub"] and spec[q["id"]]["role"] == "shaft"), None)
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
    if prog_base is None:
        return _empty(parts, spec), []
    if spec[prog_base]["role"] != "block":  # nothing to mount on: a row of parts, no interfaces
        notes.append("No prismatic part to mount the others on: the parts are laid out in a row without interfaces.")
        parent = {p["id"]: None for p in designed}
    kids: dict[str, list[str]] = {i: [] for i in spec}
    for p in designed:
        if parent.get(p["id"]):
            kids[parent[p["id"]]].append(p["id"])  # type: ignore[index]

    def ncopies(i: str) -> int:
        q = int(by_id[i]["qty"])
        if q > MAX_COPIES:
            notes.append(f"{by_id[i]['name']}: {q} off, {MAX_COPIES} laid out in the skeleton.")
        return min(q, MAX_COPIES)

    # stacks on shafts: hubs / gears (every copy) in plan order
    stack: dict[str, list[tuple[str, int]]] = {}
    for i, s in spec.items():
        if s["role"] == "shaft":
            stack[i] = [(k, c) for k in kids[i] if spec[k]["role"] in ("hub", "gear") for c in range(ncopies(k))]
    # hubs and gears on a shaft get its bore; a hub's OD must leave a rim
    for sh, st in stack.items():
        d = spec[sh]["d"]
        for k, _c in st:
            s = spec[k]
            s["bore"] = d
            if s["role"] == "hub" and not s.get("od_given"):
                s["OD"] = max(s["OD"], d + 2 * max(8.0, 0.5 * d))
    for i, s in spec.items():
        if s["role"] == "gear":
            s["pitch"] = s["module"] * s["teeth"]

    def od(i: str) -> float:
        s = spec[i]
        return {"hub": s.get("OD", 0.0), "gear": s.get("pitch", 0.0), "shaft": s.get("d", 0.0)}.get(s["role"], 0.0)

    def height(i: str) -> float:
        s = spec[i]
        return {"hub": s.get("H", 0.0), "gear": s.get("b", 0.0)}.get(s["role"], 0.0)

    # stations on each block: [(item, copy)] for child blocks, shafts and hubs/gears bolted to the block
    stations: dict[str, list[tuple[str, int]]] = {}
    for i, s in spec.items():
        if s["role"] == "block":
            stations[i] = [(k, c) for k in kids[i] for c in range(ncopies(k))]

    def first_gear(sh: str) -> str | None:
        return next((k for k, _c in stack.get(sh, []) if spec[k]["role"] == "gear"), None)

    def foot(st: tuple[str, int]) -> tuple[float, float]:
        k = st[0]
        s = spec[k]
        if s["role"] == "block":
            return s["L"], s["W"]
        if s["role"] == "shaft":
            w = max([s["d"]] + [od(x) for x, _c in stack.get(k, [])])
            return w, w
        return od(k), od(k)

    def meshes(a: tuple[str, int], b: tuple[str, int]) -> tuple[str, str] | None:
        if spec[a[0]]["role"] != "shaft" or spec[b[0]]["role"] != "shaft" or a[0] == b[0]:
            return None
        ga, gb = first_gear(a[0]), first_gear(b[0])
        if not ga or not gb or abs(spec[ga]["module"] - spec[gb]["module"]) > 1e-9:
            return None
        if abs(foot(a)[0] - od(ga)) > 1e-9 or abs(foot(b)[0] - od(gb)) > 1e-9:
            return None  # something on a shaft is wider than its gear: no clean mesh in this layout
        return ga, gb

    # sizes bottom-up (blocks grow to carry their row)
    def size_block(i: str) -> None:
        for k, _c in stations[i]:
            if spec[k]["role"] == "block":
                size_block(k)
        row = stations[i]
        if not row:
            return
        length = 2 * MARGIN
        for n, st in enumerate(row):
            w = foot(st)[0]
            if n == 0:
                length += w
                continue
            prev = row[n - 1]
            mesh = meshes(prev, st)
            length += (od(mesh[0]) / 2 + od(mesh[1]) / 2 - foot(prev)[0] / 2 - w / 2 + w) if mesh else GAP + w
        width = max(foot(st)[1] for st in row) + 2 * MARGIN
        s = spec[i]
        frozen = "L" in (iov.get(i) or {})
        if not frozen:
            s["L"] = max(s["L"], length)
            s["W"] = max(s["W"], width)
        s["row_len"] = length

    if spec[prog_base]["role"] == "block":
        size_block(prog_base)
    for i, s in spec.items():  # blocks not reachable from the base (no parent): size their rows too
        if s["role"] == "block" and parent.get(i) is None and i != prog_base:
            size_block(i)

    # positions top-down
    at: dict[str, list[list[float] | None]] = {i: [None] * ncopies_quiet(by_id[i]) for i in spec}
    under: dict[tuple[str, int], tuple[str, int]] = {}   # what a hub / gear copy rests on

    def place_block(i: str, c: int, centre: list[float]) -> None:
        at[i][c] = centre
        s = spec[i]
        if c != 0:
            return
        top, bottom = centre[2] + s["H"] / 2, centre[2] - s["H"] / 2
        row = stations[i]
        if not row:
            return
        x = centre[0] - s["row_len"] / 2 + MARGIN
        prev_x = None
        for n, st in enumerate(row):
            w = foot(st)[0]
            mesh = meshes(row[n - 1], st) if n else None
            if mesh and prev_x is not None:
                cx_ = prev_x + od(mesh[0]) / 2 + od(mesh[1]) / 2
            else:
                cx_ = x + w / 2 if n == 0 else x + GAP + w / 2
            x = cx_ + w / 2
            prev_x = cx_
            k, kc = st
            ks = spec[k]
            if ks["role"] == "block":
                place_block(k, kc, [cx_, centre[1], top + ks["H"] / 2])
            elif ks["role"] == "shaft":
                place_shaft(k, kc, cx_, centre[1], top, bottom, (i, 0))
            else:
                at[k][kc] = [cx_, centre[1], top + height(k) / 2]
                under[(k, kc)] = (i, 0)

    def place_shaft(i: str, c: int, x: float, y: float, top: float, bottom: float, host: tuple[str, int]) -> None:
        s = spec[i]
        st = stack.get(i, []) if c == 0 else []
        h_stack = sum(height(k) for k, _c in st)
        need = (top - bottom) + h_stack + 15.0
        if "length" not in (iov.get(i) or {}):
            s["length"] = max(s.get("length") or 0.0, need, 40.0)
        at[i][c] = [x, y, bottom + s["length"] / 2]
        z = top
        below = host
        for k, kc in st:
            at[k][kc] = [x, y, z + height(k) / 2]
            under[(k, kc)] = below
            below = (k, kc)
            z += height(k)

    if spec[prog_base]["role"] == "block":
        place_block(prog_base, 0, [0.0, 0.0, -spec[prog_base]["H"] / 2])
    env_x = spec[prog_base]["L"] / 2 if spec[prog_base]["role"] == "block" else -3 * GAP
    # anything not placed (no path to the base): a row beside the program base, no interfaces
    loose_x = env_x + 3 * GAP
    for p in designed:
        i = p["id"]
        for c in range(len(at[i])):
            if at[i][c] is None:
                w = foot((i, c))[0] if spec[i]["role"] != "block" else spec[i]["L"]
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
        na = by_id[a[0]]["name"] + (f" #{a[1] + 1}" if len(at[a[0]]) > 1 else "")
        nb = by_id[b[0]]["name"] + (f" #{b[1] + 1}" if len(at[b[0]]) > 1 else "")
        f = {"id": iid, "kind": kind, "name": f"{nb} ↔ {na}: {label or KIND_LABEL[kind]}",
             "a": {"item": a[0], "copy": a[1], "name": na}, "b": {"item": b[0], "copy": b[1], "name": nb},
             "datums": datums, "data": data, "edited": sorted(o)}
        ifs.append(f)
        return f

    def bolt_size(sub: str, span: float, o: dict[str, Any]) -> int:
        m = int(o.get("fastener") or fast_hint.get(sub) or fastener_for(span))
        return m if m in CLEARANCE else fastener_for(span)

    def grid(cxy: list[float], L: float, W: float, d: float, count: int, inset: float) -> list[list[float]]:
        ex, ey = L / 2 - inset, W / 2 - inset
        if count == 2:
            return [[_r2(cxy[0] - ex), _r2(cxy[1])], [_r2(cxy[0] + ex), _r2(cxy[1])]]
        if count >= 6:
            return [[_r2(cxy[0] + sx), _r2(cxy[1] + sy)] for sy in (-ey, ey) for sx in (-ex, 0.0, ex)]
        return [[_r2(cxy[0] + sx), _r2(cxy[1] + sy)] for sy in (-ey, ey) for sx in (-ex, ex)]

    def circle(cxy: list[float], pcd: float, count: int) -> list[list[float]]:
        return [[_r2(cxy[0] + pcd / 2 * math.cos(2 * math.pi * k / count + math.pi / count)),
                 _r2(cxy[1] + pcd / 2 * math.sin(2 * math.pi * k / count + math.pi / count))] for k in range(count)]

    order: list[tuple[str, int]] = []

    def walk(i: str) -> None:
        for k, c in stations.get(i, []):
            order.append((k, c))
            if spec[k]["role"] == "block" and c == 0:
                walk(k)
            if spec[k]["role"] == "shaft" and c == 0:
                order.extend(stack.get(k, []))

    walk(prog_base)
    for k, c in order:
        ks = spec[k]
        p = by_id[k]
        host = parent.get(k)
        if host is None:
            continue
        hs = spec[host]
        pos = at[k][c]
        assert pos is not None
        n_if = len(ifs) + 1
        o = fov.get(f"IF-{n_if:02d}") or {}
        if ks["role"] == "block":
            top = pos[2] - ks["H"] / 2
            span = min(ks["L"], ks["W"])
            m = bolt_size(p["sub"], span, o)
            d = float(o.get("d") or CLEARANCE[m])
            inset = float(o.get("inset") or max(2 * d, 6.0))
            wod = WASHER_OD.get(max(m, bolt_for_hole(d)), 2 * d)
            # two rows only when the washers of neighbouring bolts fit side by side (the ICD's own rule)
            count = int(o.get("count") or (4 if min(ks["L"], ks["W"]) - 2 * inset >= wod
                                           and max(ks["L"], ks["W"]) - 2 * inset >= wod else 2))
            pts = grid(pos, ks["L"], ks["W"], d, count, inset)
            add("hole_pattern", (host, 0), (k, c), {
                "fastener": f"M{m}", "fastener_size": m, "fastener_item": fast_item.get(p["sub"]),
                "count": len(pts), "d": d, "pattern": "grid" if len(pts) > 2 else "linear", "inset": inset,
                "plane_z": _r2(top), "normal": [0, 0, 1], "positions": pts, "through": True,
                "flatness": float(o.get("flatness") or FLATNESS), "position_tol": float(o.get("position_tol") or POS_TOL)},
                ["A", "B", "C"])
        elif ks["role"] == "shaft":
            top, bottom = at[host][0][2] + hs["H"] / 2, at[host][0][2] - hs["H"] / 2  # type: ignore[index]
            fit = str(o.get("fit") or "H7/h6")
            add("shaft_bore", (host, 0), (k, c), {
                "d": ks["d"], "fit": fit if fit in FITS else "H7/h6", "length": _r2(top - bottom),
                "axis": [_r2(pos[0]), _r2(pos[1])], "z": [_r2(bottom), _r2(top)], "flush_z": _r2(bottom),
                "position_tol": POS_TOL}, ["A", "B", "C"], "shaft through bore")
        else:  # hub / gear
            bottom = pos[2] - height(k) / 2
            if hs["role"] == "shaft":
                fit = str(o.get("fit") or "H7/k6")
                add("shaft_bore", (k, c), (host, 0), {
                    "d": hs["d"], "fit": fit if fit in FITS else "H7/k6", "length": _r2(height(k)),
                    "axis": [_r2(pos[0]), _r2(pos[1])], "z": [_r2(bottom), _r2(bottom + height(k))], "flush_z": None,
                    "position_tol": POS_TOL}, ["A", "B", "C"], "bore on shaft")
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
                pcd = _r2(max(0.65 * D, (ks.get("bore") or 0) + 3 * d, wod / math.sin(math.pi / count) + 0.01))
                add("hole_pattern", (host, 0), (k, c), {
                    "fastener": f"M{m}", "fastener_size": m, "fastener_item": fast_item.get(p["sub"]),
                    "count": count, "d": d, "pattern": "circular", "pcd": pcd, "centre": [_r2(pos[0]), _r2(pos[1])],
                    "plane_z": _r2(bottom), "normal": [0, 0, 1], "positions": circle(pos, pcd, count), "through": True,
                    "flatness": float(o.get("flatness") or FLATNESS), "position_tol": float(o.get("position_tol") or POS_TOL)},
                    ["A", "B", "C"])
    # gear meshes last (their existence depends on numbers; earlier ids stay stable)
    for i, row in stations.items():
        for n in range(1, len(row)):
            mesh = meshes(row[n - 1], row[n])
            if not mesh:
                continue
            ga, gb = mesh
            sa, sb = spec[ga], spec[gb]
            pa, pb = at[ga][0], at[gb][0]
            add("gear_mesh", (ga, 0), (gb, 0), {
                "module": sa["module"], "teeth_a": int(sa["teeth"]), "teeth_b": int(sb["teeth"]),
                "centre_distance": _r2(sa["module"] * (sa["teeth"] + sb["teeth"]) / 2),
                "face_width": _r2(min(sa["b"], sb["b"])), "pressure_angle": PRESSURE_ANGLE,
                "ratio": round(sb["teeth"] / sa["teeth"], 4), "axis_a": [_r2(pa[0]), _r2(pa[1])],  # type: ignore[index]
                "axis_b": [_r2(pb[0]), _r2(pb[1])]}, ["A", "B"])  # type: ignore[index]

    # ---- skeleton document
    items_out: dict[str, Any] = {}
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for p in designed:
        i = p["id"]
        s = spec[i]
        size = _size_of(s)
        for c in at[i]:
            for k in range(3):
                lo[k] = min(lo[k], c[k] - size[k] / 2)  # type: ignore[index]
                hi[k] = max(hi[k], c[k] + size[k] / 2)  # type: ignore[index]
        items_out[i] = {"name": p["name"], "role": s["role"], "shape": "box" if s["role"] == "block" else "cylinder",
                        "size": [_r2(x) for x in size], "sub": p["sub"], "parent": parent.get(i),
                        "copies": [[_r2(x) for x in c] for c in at[i]],  # type: ignore[union-attr]
                        "qty": p["qty"], "source": s["source"],
                        **({"d": s["d"]} if s["role"] == "shaft" else {}),
                        **({"bore": s["bore"]} if s.get("bore") else {}),
                        **({"module": s["module"], "teeth": int(s["teeth"]), "face_width": s["b"]}
                           if s["role"] == "gear" else {})}
    axes = [{"id": f"AX{n + 1}", "name": f"{items_out[i]['name']} axis", "item": i,
             "origin": [items_out[i]["copies"][0][0], items_out[i]["copies"][0][1], 0.0], "dir": [0, 0, 1]}
            for n, i in enumerate(i for i in items_out if items_out[i]["role"] == "shaft")]
    base = items_out[prog_base]
    skel = {"units": "mm", "base": prog_base,
            "csys": f"Origin at the centre of the top face of the {base['name']} (datums A, B, C); +Z up, away from "
                    "the base; +X along the row of parts; +Y completes a right-handed frame.",
            "datums": [{"id": "A", "kind": "plane", "name": f"{base['name']} top face", "origin": [0, 0, 0], "normal": [0, 0, 1]},
                       {"id": "B", "kind": "plane", "name": "Mid-plane XZ", "origin": [0, 0, 0], "normal": [0, 1, 0]},
                       {"id": "C", "kind": "plane", "name": "Mid-plane YZ", "origin": [0, 0, 0], "normal": [1, 0, 0]}],
            "axes": axes,
            "envelope": {"min": [_r2(x) for x in lo], "max": [_r2(x) for x in hi],
                         "size": [_r2(hi[k] - lo[k]) for k in range(3)]},
            "items": items_out, "notes": notes,
            "standard": [{"item": p["id"], "name": p["name"], "qty": p["qty"], "sub": p["sub"]}
                         for p in parts if p["family"] == "standard"]}
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
    return [s["pitch"], s["pitch"], s["b"]]


def _empty(parts: list[dict[str, Any]], spec: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"units": "mm", "base": None, "csys": "No designed parts: nothing to lay out.", "datums": [], "axes": [],
            "envelope": {"min": [0, 0, 0], "max": [0, 0, 0], "size": [0, 0, 0]}, "items": {}, "notes": [],
            "standard": [{"item": p["id"], "name": p["name"], "qty": p["qty"], "sub": p["sub"]}
                         for p in parts if p["family"] == "standard"]}


# ----------------------------------------------------------------------------- local features per item
def _local(skel: dict[str, Any], side: dict[str, Any], xy: list[float]) -> list[float]:
    c = skel["items"][side["item"]]["copies"][side["copy"]]
    return [_r2(xy[0] - c[0]), _r2(xy[1] - c[1])]


def _lz(skel: dict[str, Any], side: dict[str, Any], z: float) -> float:
    return _r2(z - skel["items"][side["item"]]["copies"][side["copy"]][2])


def side_features(skel: dict[str, Any], f: dict[str, Any], which: str) -> list[dict[str, Any]]:
    """What one side of an interface must carry, in its part frame."""
    side = f[which]
    d = f["data"]
    out: list[dict[str, Any]] = []
    if f["kind"] == "hole_pattern":
        n = 1 if which == "a" else -1
        out.append({"type": "face", "z": _lz(skel, side, d["plane_z"]), "n": n, "tol": d["position_tol"],
                    "label": "mounting face" + (" (top)" if n > 0 else " (bottom)")})
        for k, xy in enumerate(d["positions"]):
            out.append({"type": "hole", "c": _local(skel, side, xy), "d": d["d"], "tol": d["position_tol"],
                        "label": f"hole {k + 1}"})
    elif f["kind"] == "shaft_bore":
        bore_side = "a"
        if which == bore_side:
            out.append({"type": "hole", "c": _local(skel, side, d["axis"]), "d": d["d"], "fit": d["fit"].split("/")[0],
                        "tol": d["position_tol"], "label": f"bore Ø{d['d']:g} {d['fit'].split('/')[0]}"})
        else:
            out.append({"type": "boss", "c": _local(skel, side, d["axis"]), "d": d["d"], "fit": d["fit"].split("/")[1],
                        "tol": d["position_tol"], "label": f"shaft Ø{d['d']:g} {d['fit'].split('/')[1]}"})
        if d.get("flush_z") is not None:
            out.append({"type": "face", "z": _lz(skel, side, d["flush_z"]), "n": -1, "tol": d["position_tol"],
                        "label": "end face flush with the bottom"})
    elif f["kind"] == "face":
        n = 1 if which == "a" else -1
        out.append({"type": "face", "z": _lz(skel, side, d["plane_z"]), "n": n, "tol": d["position_tol"],
                    "label": "seating face" + (" (top)" if n > 0 else " (bottom)")})
    elif f["kind"] == "gear_mesh":
        z = d["teeth_a"] if which == "a" else d["teeth_b"]
        out.append({"type": "gear", "module": d["module"], "teeth": z, "c": [0.0, 0.0], "tol": d.get("position_tol", POS_TOL),
                    "label": f"m{d['module']:g} × {z} teeth"})
    for o in out:
        o["if"] = f["id"]
    return out


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


def _same_feature(x: dict[str, Any], y: dict[str, Any]) -> bool:
    if x["type"] != y["type"]:
        return False
    if x["type"] == "face":
        return x["n"] == y["n"] and abs(x["z"] - y["z"]) < 1e-6
    if x["type"] == "gear":
        return True
    return abs(x["c"][0] - y["c"][0]) < 1e-6 and abs(x["c"][1] - y["c"][1]) < 1e-6 and abs(x["d"] - y["d"]) < 1e-6


def placeholder_spec(skel: dict[str, Any], ifs: list[dict[str, Any]], item: str) -> dict[str, Any]:
    """The envelope solid with its interface features (through holes / bores along Z), in the part frame."""
    it = skel["items"][item]
    holes = [{"c": f["c"], "d": f["d"]} for f in item_features(skel, ifs, item) if f["type"] == "hole"]
    if it.get("bore") and not any(abs(h["c"][0]) < 1e-6 and abs(h["c"][1]) < 1e-6 for h in holes):
        holes.append({"c": [0.0, 0.0], "d": it["bore"]})
    return {"shape": it["shape"], "size": it["size"], "holes": holes, "name": it["name"]}


# ----------------------------------------------------------------------------- validation
def problems(skel: dict[str, Any], ifs: list[dict[str, Any]]) -> list[str]:
    """Geometry that can't be made: holes outside or too close to the edge of their part, overlapping holes, a bore
    that leaves no rim, a gear bore through the teeth."""
    out: list[str] = []
    for i, it in skel["items"].items():
        L, W, _H = it["size"]
        holes = [f for f in item_features(skel, ifs, i) if f["type"] == "hole"]
        if it.get("bore"):
            holes.append({"c": [0.0, 0.0], "d": it["bore"], "label": "bore"})
        for h in holes:
            r = h["d"] / 2
            x, y = h["c"]
            if h["d"] <= 0:
                out.append(f"{it['name']}: {h.get('label', 'hole')} needs a positive diameter.")
                continue
            if it["shape"] == "box":
                if abs(x) + r > L / 2 - 1.0 or abs(y) + r > W / 2 - 1.0:
                    out.append(f"{it['name']}: {h.get('label', 'hole')} Ø{h['d']:g} at ({x:g}, {y:g}) leaves less "
                               "than 1 mm of wall to the edge of its envelope.")
            else:
                rim = L / 2 - (math.hypot(x, y) + r)
                if it["role"] == "gear":
                    rim = it["module"] * it["teeth"] / 2 - 1.25 * it["module"] - (math.hypot(x, y) + r)
                if rim < 1.0 and it["role"] != "shaft":
                    out.append(f"{it['name']}: {h.get('label', 'hole')} Ø{h['d']:g} leaves {max(rim, 0):.1f} mm of "
                               "material (at least 1 mm needed).")
        for n, a in enumerate(holes):
            for b in holes[n + 1:]:
                gap = math.hypot(a["c"][0] - b["c"][0], a["c"][1] - b["c"][1]) - (a["d"] + b["d"]) / 2
                if gap < 1.0 and not (abs(a["c"][0] - b["c"][0]) < 1e-6 and abs(a["c"][1] - b["c"][1]) < 1e-6
                                      and abs(a["d"] - b["d"]) < 1e-6):
                    out.append(f"{it['name']}: holes at ({a['c'][0]:g}, {a['c'][1]:g}) and ({b['c'][0]:g}, "
                               f"{b['c'][1]:g}) are {gap:.1f} mm apart (at least 1 mm needed).")
    for f in ifs:
        if f["kind"] == "hole_pattern":  # the washers (ISO 7089) of neighbouring bolts must not overlap
            d = f["data"]
            m = max(int(d.get("fastener_size") or 3), bolt_for_hole(d["d"]))
            od = WASHER_OD.get(m, 2 * d["d"])
            pts = d["positions"]
            gap = min((math.hypot(a[0] - b[0], a[1] - b[1]) for k, a in enumerate(pts) for b in pts[k + 1:]),
                      default=math.inf)
            if gap < od - 1e-6:
                out.append(f"{f['id']}: Ø{d['d']:g} holes take M{m} bolts, whose washers (Ø{od:g}) overlap at "
                           f"{gap:.1f} mm between hole centres.")
        if f["kind"] == "shaft_bore":
            h, s = fit_zones(f["data"]["d"], f["data"]["fit"])
            if h is None or s is None:
                out.append(f"{f['id']}: fit {f['data']['fit']} is not in the ISO 286 table used here.")
    return out


# ----------------------------------------------------------------------------- the ICD document
def new_icd(parts: list[dict[str, Any]], brief: str, actor: str, overrides: dict[str, Any] | None = None
            ) -> tuple[dict[str, Any], dict[str, Any]]:
    skel, ifs = build(parts, brief, overrides)
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
        out[k] = x
    if not out:
        raise OfficeInputError("Nothing to change.")
    return out


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
            o.update(L=L, W=W, H=H)
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


def excerpt(skel: dict[str, Any], icd: dict[str, Any], item: str) -> str:
    """The ICD for one part, in plain words plus a machine-readable ``fw-icd`` block (part frame)."""
    it = skel["items"].get(item)
    if not it:
        return ""
    L, W, H = it["size"]
    shape = (f"box {L:g} × {W:g} × {H:g} mm (X × Y × Z)" if it["shape"] == "box"
             else f"cylinder Ø{L:g} × {H:g} mm along Z")
    head = (f"Interfaces (ICD v{icd['version']}, approved). Model this part in its part frame: origin at the centre "
            f"of its envelope, +Z up, axes parallel to the program axes. Envelope: {shape}; the part must stay "
            "inside it.")
    lines = [head]
    mine = [f for f in icd["interfaces"] if item in (f["a"]["item"], f["b"]["item"])]
    seen: set[str] = set()
    for f in mine:
        which = "a" if f["a"]["item"] == item else "b"
        feats = side_features(skel, f, which)
        key = json.dumps([(x["type"], x.get("c"), x.get("z"), x.get("d")) for x in feats])
        if key in seen:
            continue
        seen.add(key)
        d = f["data"]
        bits = []
        for x in feats:
            if x["type"] == "face":
                bits.append(f"{x['label']} at Z {x['z']:g} (normal {'+' if x['n'] > 0 else '−'}Z, flatness "
                            f"{d.get('flatness', FLATNESS):g})")
            elif x["type"] == "hole":
                pass
            elif x["type"] == "boss":
                bits.append(f"{x['label']} on the axis at (X, Y) {_fmt_xy(x['c'])}")
            elif x["type"] == "gear":
                bits.append(f"{x['label']}, pressure angle {d['pressure_angle']:g}°, face width {d['face_width']:g}, "
                            f"centre distance {d['centre_distance']:g} to its mate")
        holes = [x for x in feats if x["type"] == "hole"]
        if holes:
            if f["kind"] == "shaft_bore":
                bits.append(f"{holes[0]['label']} through, axis at (X, Y) {_fmt_xy(holes[0]['c'])}")
            else:
                bits.append(f"{len(holes)} × Ø{holes[0]['d']:g} through ({d['fastener']} clearance) at (X, Y) "
                            + ", ".join(_fmt_xy(h["c"]) for h in holes))
        lines.append(f"- {f['id']} {f['name']}: " + "; ".join(bits) + f" (position tolerance ±{d.get('position_tol', POS_TOL):g}).")
    if len(lines) == 1:
        lines.append("- No interfaces: this part only has to fit its envelope.")
    lines.append("Do not change an interface on your own. If one can't work, keep designing to the ICD and raise a "
                 "change request with exactly one block:\n```fw-change-request\n{\"interface\": \"IF-01\", \"values\": "
                 "{\"d\": 9}, \"reason\": \"one sentence\"}\n```")
    data = {"item": item, "version": icd["version"], "shape": it["shape"], "size": it["size"],
            "features": [{k: v for k, v in x.items() if k not in ("also",)} for x in item_features(skel, icd["interfaces"], item)]}
    if it.get("bore"):
        data["bore"] = it["bore"]
    if it["role"] == "gear":
        data["gear"] = {"module": it["module"], "teeth": it["teeth"], "face_width": it["face_width"]}
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
