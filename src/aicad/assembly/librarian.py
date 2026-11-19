"""Hex, the Librarian: turn a plain description of what to add to an assembly into concrete components.

Reuse before design (docs/plans/CHIEF_DESIGNER.md §2.3), in this order:
1. the Toolbox (deterministic generators, zero tokens): "4 M6x25 bolts with washers and nuts", "a 6204 bearing",
   "two Ø8 dowel pins", "a Ø20 shaft 150 long", "spur gear m2 24 teeth";
2. the company's own parts (verified projects of the workspace) by name / description words, or by size
   ("the 120x80 plate");
3. otherwise "not found": design it with the Design Studio agent.

Everything here is pure Python and deterministic. The only model call is ``ask_ai`` (the AI fallback for clauses
the parser cannot read); it is opt-in per request, its tokens are reported, and tests replace it. A model answer is
never trusted as-is: every suggested component goes back through ``toolbox.normalize`` and the project list.

``parse`` reads the text into clauses (quantity, component words, a target hint such as "on the shaft"); ``resolve``
picks a source for each clause; ``plan`` (in ``fitz``) adds placement and order.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from aicad import similarity, toolbox

NUM = r"(\d+(?:\.\d+)?)"
WORDS = {"a": 1, "an": 1, "one": 1, "single": 1, "two": 2, "pair of": 2, "a pair of": 2, "both": 2, "three": 3,
         "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
         "sixteen": 16, "twenty": 20}
MAX_QTY = 64
STOP = {"the", "a", "an", "my", "our", "from", "projects", "project", "parts", "part", "company", "library", "existing",
        "own", "workspace", "with", "and", "of", "for", "to", "in", "on", "into", "onto", "some", "that", "this", "we",
        "made", "use", "using", "one", "i", "me", "please", "x", "mm"}
GENERIC = {"hole", "holes", "seat", "seats", "bore", "bores", "top", "side", "face", "end", "both", "each", "all",
           "them", "it", "assembly", "mounting"}
VERB = re.compile(r"^(?:please\s+)?(?:then\s+)?(?:add|insert|put|place|fit|mount|attach|fix|bolt|use|install|"
                  r"i need|we need|need|give me|get|press|drive|slide|assemble|fasten|secure)\s+", re.IGNORECASE)
OWN = re.compile(r"\b(?:from|in)\s+(?:my|our|the)\s+(?:own\s+)?(?:projects?|parts?|library|company|workspace|"
                 r"designs?)\b|\b(?:my|our)\s+(?:own\s+)?|\bexisting\b|\bcompany\b", re.IGNORECASE)
PREP = re.compile(r"\s(for|on|onto|into|in|to|through|at|over|under|between|against)\s+(?!toolbox\b)", re.IGNORECASE)
MOUNT = re.compile(r"^\s*(?:please\s+)?(mount|attach|fix|bolt|place|put|secure|fasten)\b", re.IGNORECASE)
ACCESSORY = {"washer", "washers", "nut", "nuts"}
FASTENER_WORDS = re.compile(r"\b(bolts?|screws?|cap screws?|shcs|allen|set of bolts|fasteners?)\b", re.IGNORECASE)


@dataclass
class Clause:
    text: str                       # the original clause
    core: str                       # component words, without verbs / target / source hints
    qty: int = 1
    qty_explicit: bool = False
    target: str | None = None       # "the plate holes", "the shaft"
    own: bool = False               # "from my projects", "our ..."
    mount: bool = False             # "mount / attach / bolt X on Y"
    extras: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------------- splitting
def _norm(t: str) -> str:
    t = t.replace("×", "x").replace("⌀", "ø").replace("Ø", "ø").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", t).strip()


def _lead_qty(s: str) -> tuple[int | None, str]:
    """A quantity at the start of a chunk: '4', '4x', '4 off', 'four', 'a pair of', 'a', 'an'."""
    s = s.strip()
    m = re.match(r"^(\d{1,3})\s*(?:x\s+|×\s*|off\s+|pcs\.?\s+|pieces?\s+(?:of\s+)?)?(?=\D)", s, re.IGNORECASE)
    if m and not re.match(r"^\d{1,3}\s*x\s*\d", s, re.IGNORECASE):  # "8x20 dowel" is a size, not a count
        return int(m.group(1)), s[m.end():].strip()
    low = s.lower()
    for w in sorted(WORDS, key=len, reverse=True):
        if low.startswith(w + " "):
            return WORDS[w], s[len(w) + 1:].strip()
    return None, s


def _nouns(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", s.lower())}


def _starts_item(chunk: str) -> bool:
    m = PREP.search(" " + chunk)
    if m and m.start() > 0:
        chunk = chunk[:m.start() - 1]
    q, _rest = _lead_qty(chunk)
    if q is not None:
        return True
    low = chunk.lower().strip()
    if re.match(r"^(?:the|my|our|some|then)\b", low) or VERB.match(low):
        return True
    words = _nouns(low)
    return bool(words) and not words <= (ACCESSORY | STOP | {"plain", "flat", "hex", "spring", "lock"})


GEAR_PAIR = re.compile(r"\b(\d{2,3})\s*t?\s*/\s*(\d{2,3})\s*(?:t\b|teeth\b)", re.IGNORECASE)


def _gear_pairs(clause: str) -> list[str]:
    """"spur gear pair 1:3 m2 20T/60T" is two gears: one clause each ("spur gear m2 20T", "spur gear m2 60T")."""
    m = GEAR_PAIR.search(clause)
    if not m or not re.search(r"\b(gears?|pinion|spur)\b", clause, re.IGNORECASE):
        return [clause]
    rest = clause[:m.start()] + "{z}T" + clause[m.end():]
    rest = re.sub(r"\b(?:a\s+)?pair\s+(?:of\s+)?", "", rest, flags=re.IGNORECASE)
    rest = re.sub(r"\b\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?\b", "", rest)       # the ratio is in the teeth
    rest = re.sub(r"\bgears\b", "gear", re.sub(r"^\s*(?:two|2|a|an)\s+", "", rest, flags=re.IGNORECASE))
    rest = re.sub(r"\s+", " ", rest).strip()
    return [rest.replace("{z}", m.group(1)), rest.replace("{z}", m.group(2))]


def split(text: str) -> list[str]:
    """Clauses of a description. Accessories stay with their fastener ("bolts with washers and nuts"); a chunk
    after ',', 'and', 'plus', 'then' or 'with' starts a new item only when it reads like one."""
    t = _norm(text)
    if not t:
        return []
    parts = [p.strip() for p in re.split(r"[\n;]+|\.\s+(?=[A-Za-z])|\.$", t) if p.strip()]
    out: list[str] = []
    for p in parts:
        chunks = re.split(r"\s*,\s*|\s+(?:and|plus|then|also|as well as|&)\s+|\s+with\s+(?=(?:\d|a\s|an\s|two\s|"
                          r"three\s|four\s|five\s|six\s|eight\s|ten\s|twelve\s|m\d|ø|iso\s|hex\s|socket\s|"
                          r"(?:bolts?|screws?|cap screws?|dowels?|pins?|bearings?)\b))", p, flags=re.IGNORECASE)
        cur: list[str] = []
        for c in chunks:
            c = c.strip(" .")
            if not c:
                continue
            if cur and not _starts_item(c):
                cur.append(c)
            else:
                if cur:
                    out.append(" and ".join(cur))
                cur = [c]
        if cur:
            out.append(" and ".join(cur))
    return [x for c in out for x in _gear_pairs(c)][:24]   # a gear pair is two items


def parse_clause(text: str) -> Clause:
    raw = _norm(text)
    s = re.sub(r"^(?:and|then|also|plus|with)\s+", "", raw, flags=re.IGNORECASE)
    mount = bool(MOUNT.match(s))
    s = VERB.sub("", s).strip()
    own = bool(OWN.search(s))
    s = OWN.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    target = None
    m = PREP.search(" " + s)
    if m:
        k = m.start()  # index in " " + s
        target = s[k + len(m.group(0)) - 1:].strip() or None
        s = s[:max(0, k - 1)].strip() if k > 0 else ""
    qty, rest = _lead_qty(s)
    core = rest
    xm = re.search(r"\b(?:x\s?(\d{1,3})|(\d{1,3})\s?(?:off|pcs|pieces))\b$", core, re.IGNORECASE)
    if qty is None and xm:
        qty = int(xm.group(1) or xm.group(2))
        core = core[:xm.start()].strip()
    core = re.sub(r"^(?:the|some|of)\s+", "", core, flags=re.IGNORECASE).strip()
    return Clause(text=raw, core=core, qty=max(1, min(MAX_QTY, qty or 1)), qty_explicit=qty is not None,
                  target=target, own=own, mount=mount)


def parse(text: str) -> list[Clause]:
    return [parse_clause(c) for c in split(text)]


# ----------------------------------------------------------------------------- Toolbox reading
def _size(t: str) -> tuple[float | None, float | None]:
    m = re.search(r"\bm\s?(\d{1,2})(?:\s*x\s*" + NUM + r")?\b", t)
    if m and int(m.group(1)) in toolbox.METRIC:
        return float(m.group(1)), float(m.group(2)) if m.group(2) else None
    return None, None


def _length(t: str) -> float | None:
    g = re.search(r"(?:length|long|l\s*=)\s*(?:of\s*)?" + NUM + r"|" + NUM + r"\s*(?:mm)?\s*long\b", t)
    return float(g.group(1) or g.group(2)) if g else None


def _dia(t: str) -> float | None:
    g = re.search(r"(?:ø|dia(?:meter)?\.?|d\s*=)\s*" + NUM, t) or re.search(NUM + r"\s*(?:mm)?\s*(?:dia(?:meter)?|ø)\b", t)
    return float(g.group(1)) if g else None


def _dxl(t: str) -> tuple[float | None, float | None]:
    g = re.search(r"(?<![m\d.])(?:ø\s*)?" + NUM + r"\s*x\s*" + NUM, t)
    return (float(g.group(1)), float(g.group(2))) if g else (None, None)


DOWEL_L = (4, 5, 6, 8, 10, 12, 14, 16, 18, 20, 24, 26, 28, 30, 32, 35, 40, 45, 50, 55, 60, 70, 80, 90, 100)


def default_dowel_length(d: float) -> float:
    """A common ISO 8734 length about 2.5 × d (verify against your stock list)."""
    want = 2.5 * d
    return float(next((x for x in DOWEL_L if x >= want - 1e-9), DOWEL_L[-1]))


# ----------------------------------------------------------------------------- what kind of part a clause names
# The part a clause names is the last part noun of its leading phrase: "Hex nut M8 for the flange bolts" is a nut,
# "Oil plug M16, with sealing washer" a plug, "Pinion key, DIN 6885" a key, "Bearing 6204, held by a circlip" a
# bearing. Hex reads only that family; a noun the Toolbox doesn't stock (a plug, a breather, a seal), or a different
# kind of a stocked noun (a lock washer is not an ISO 7089 plain washer, a taper roller bearing not a ball bearing),
# is never read as some other part (live gear reducer run 2026-11-19: "Hex nut M8" and "Washer M8" became hex bolts,
# "Oil plug M16" a washer).
LEAD_SPLIT = re.compile(r"[,.;:(]|\b(?:without|with|plus|including|for|on|onto|to|in|of|from|that|which|held|holds?|located|against|by|and|"
                        r"fixes|fixing|joining|joins|clamping|clamps|supporting|supports|used|fitted|between)\b")
HEAD = re.compile(r"\b(keys?|circlips?|seeger|(?:retaining|snap) rings?|471|bearings?|gears?|pinions?|shafts?|axles?|"
                  r"bolts?|screws?|nuts?|washers?|dowels?|pins?|standoffs?|spacers?|"
                  # nouns the Toolbox has no family for: "not stocked" (designed as a bought-out part)
                  r"plugs?|breathers?|vents?|seals?|o-?rings?|gaskets?|springs?|nipples?|rivets?|inserts?|grommets?|"
                  r"clips?|couplings?|collars?|caps?|covers?|bush(?:es|ings?)?|sleeves?|magnets?|dipsticks?|"
                  r"sight ?glass(?:es)?|studs?)\b")
FAMILY = {"key": "key", "keys": "key", "circlip": "ring", "circlips": "ring", "seeger": "ring", "471": "ring",
          "bearing": "bearing", "bearings": "bearing", "gear": "gear", "gears": "gear", "pinion": "gear",
          "pinions": "gear", "shaft": "shaft", "shafts": "shaft", "axle": "shaft", "axles": "shaft",
          "bolt": "fastener", "bolts": "fastener", "screw": "fastener", "screws": "fastener", "nut": "nut",
          "nuts": "nut", "washer": "washer", "washers": "washer", "dowel": "dowel", "dowels": "dowel", "pin": "pin",
          "pins": "pin", "standoff": "standoff", "standoffs": "standoff", "spacer": "standoff", "spacers": "standoff"}
FAMILY_CODES = {"fastener": ("hex_bolt", "shcs"), "nut": ("hex_nut",), "washer": ("washer",), "key": ("parallel_key",),
                "ring": ("retaining_ring",), "bearing": ("bearing",), "gear": ("spur_gear",), "shaft": ("shaft",),
                "dowel": ("dowel",), "pin": ("dowel",), "standoff": ("standoff",)}
# a different kind of a stocked noun (the Toolbox has ISO 4017 / 4762 screws, ISO 4032 nuts, ISO 7089 washers,
# DIN 6885 A keys, DIN 471 rings, deep-groove ball bearings, ISO 8734 dowels and spur gears)
OTHER_KIND = {
    "fastener": re.compile(r"\b(?:set|grub|wood|self[- ]?tapping|tapping|countersunk|csk|button|pan|shoulder|eye|"
                           r"carriage|anchor|banjo|thumb|wing|u|t|tee|expansion)[- ]?(?:head\s+)?(?:bolts?|screws?)\b"),
    "nut": re.compile(r"\b(?:lock|nyloc|wing|acorn|dome|cap|t|tee|cage|slotted|castle|castellated|flange|coupling|"
                      r"square|jam|thin|weld|rivet|knurled|prevailing[- ]torque)[- ]?nuts?\b"),
    "washer": re.compile(r"\b(?:lock|spring|tab|wave|serrated|star|tooth(?:ed)?|fender|sealing|bonded|thrust|"
                         r"belleville|conical|split|crinkle|shim)[- ]?washers?\b"),
    "bearing": re.compile(r"\b(?:needle|roller|taper(?:ed)?|thrust|plain|sleeve|linear|angular[- ]contact|spherical|"
                          r"self[- ]aligning|flanged|pillow[- ]block|housed|cam[- ]follower|slewing)\b"),
    "key": re.compile(r"\b(?:woodruff|gib(?:[- ]head)?|taper)\b"),
    "ring": re.compile(r"\b(?:internal|bore|housing)\s+(?:\w+\s+)?(?:circlips?|rings?)\b|\bdin\s*472\b"),
    "pin": re.compile(r"\b(?:spring|roll|cotter|split|clevis|taper|grooved|slotted|hinge|shear|tension)[- ]?pins?\b"),
    "dowel": re.compile(r"\b(?:spring|roll|taper|grooved|slotted|tension)[- ]?(?:dowels?|pins?)\b"),
    "gear": re.compile(r"\b(?:helical|bevel|worm|rack|internal|ring|planet(?:ary)?|sun|herringbone|spiral|hypoid|"
                       r"crown|face)\s+(?:gears?|pinions?|wheels?)\b|\bworm\b"),
}


def kind_of(text: str) -> tuple[str, str]:
    """(family, head noun) of the part a clause names: family "" when no part noun leads the clause, "unstocked"
    when the Toolbox has no such part (or only a different kind of it)."""
    t = _norm(text).lower()
    lead = LEAD_SPLIT.split(t)[0]
    heads = HEAD.findall(lead)
    if not heads:
        return "", ""
    head = heads[-1]
    fam = FAMILY.get(head) or ("ring" if re.fullmatch(r"(?:retaining|snap) rings?", head) else "unstocked")
    if fam == "key" and re.search(r"\b(?:allen|hex) keys?\b", lead):
        return "unstocked", head  # a hex key is a tool
    rx = OTHER_KIND.get(fam)
    if rx is not None and rx.search(lead):
        return "unstocked", head
    return fam, head


def read_toolbox(core: str, extra: str = "") -> dict[str, Any] | None:
    """Deterministic reading of one clause into a Toolbox component with parameters, or None.

    Returns {code, params, title, standard, confidence, read (param names taken from the text), kind, fasten?}.
    The part noun that leads the clause picks the family (``kind_of``): a nut is read as a nut or not at all."""
    t = _norm(core).lower()
    words = _nouns(t)
    d, L = _size(t)
    found: dict[str, Any] | None = None
    fam, _head = kind_of(t)
    if fam == "unstocked":
        return None
    lead = LEAD_SPLIT.split(t)[0]

    def out(code: str, vals: dict[str, float], read: list[str], conf: str, kind: str = "part",
            **kw: Any) -> dict[str, Any] | None:
        try:
            p = toolbox.normalize(code, vals)
        except toolbox.ToolboxError:
            return None
        c = toolbox.spec(code)
        return {"code": code, "params": p, "title": c.title(p), "standard": c.standard, "name": c.name,
                "confidence": conf, "read": sorted(read), "kind": kind, **kw}

    is_fastener = fam == "fastener" or (not fam and bool(FASTENER_WORDS.search(t))
                                        and not re.search(r"\b(set ?screw|grub)\b", t))
    if is_fastener:
        shcs = r"\b(cap screws?|socket|allen|shcs|4762)\b"
        style = ("hex_bolt" if re.search(r"\bhex\b|\b401[47]\b", lead) and not re.search(shcs, lead) else
                 "shcs" if re.search(shcs, lead) or re.search(shcs, t) else "hex_bolt")
        washers = "none" if re.search(r"\bno washers?\b|\bwithout washers?\b", t) else \
            ("head" if re.search(r"\bwasher under the head\b|\bhead washer\b", t) else "both")
        if d is None:
            return out(style, {}, [], "low", "fastener",
                       fasten={"style": style, "washers": washers, "size": None, "length": None})
        L = L or _length(t)
        vals = {"D": d, **({"L": L} if L else {})}
        r = out(style, vals, list(vals), "high" if L else "medium", "fastener",
                fasten={"style": style, "washers": washers, "size": int(d), "length": L})
        return r
    # keys and retaining rings before anything their host's noun would pick ("Pinion key", "Gear shaft circlip"):
    # the family is the last part noun of the leading phrase (``kind_of``)
    if fam == "key":
        g = re.search(r"\b(\d{1,2})\s*x\s*(\d{1,2})\s*x\s*" + NUM, t)
        row = next((hi for (_lo, hi), v in toolbox.KEY_ROWS
                    if g and (v[0], v[1]) == (int(g.group(1)), int(g.group(2)))), None)
        if g and row:
            return out("parallel_key", {"D": float(row), "L": float(g.group(3))}, ["D", "L"], "high", "key")
        dd, ll = _dia(t), _length(t)
        if dd and 8 < dd <= 65:
            vals = {"D": dd, **({"L": ll} if ll else {})}
            return out("parallel_key", vals, list(vals), "high" if ll else "medium", "key")
        return {"code": "parallel_key", "params": None, "title": "Parallel key DIN 6885 A (size from the shaft)",
                "standard": "DIN 6885-1 A", "name": "Parallel key", "confidence": "medium", "read": [],
                "kind": "key"}
    if fam == "ring":
        dd = _dia(t)
        g = re.search(r"\bfor (?:a |an )?" + NUM + r"\s*(?:mm)?\s*shaft", t)
        dd = dd or (float(g.group(1)) if g else None)
        if dd and abs(dd - round(dd)) < 1e-9 and round(dd) in toolbox.DIN471:
            return out("retaining_ring", {"D": dd}, ["D"], "high", "retaining_ring")
        return {"code": "retaining_ring", "params": None, "title": "Retaining ring DIN 471 (size from the shaft)",
                "standard": "DIN 471", "name": "Retaining ring for shafts", "confidence": "medium", "read": [],
                "kind": "retaining_ring"}
    if fam == "nut" or (not fam and words & {"nut", "nuts"} and d is not None):
        return out("hex_nut", {"D": d}, ["D"], "high") if d is not None else out("hex_nut", {}, [], "low")
    if fam == "washer" or (not fam and words & {"washer", "washers"} and d is not None):
        return out("washer", {"D": d}, ["D"], "high") if d is not None else out("washer", {}, [], "low")
    if fam == "bearing" or (not fam and words & {"bearing", "bearings"}):
        b = re.search(r"\b(6[02]0\d)\b", t)
        if b and int(b.group(1)) in toolbox.BEARING:
            return out("bearing", {"SERIES": float(b.group(1))}, ["SERIES"], "high", "bearing")
        bore = _dia(t)
        return {"code": "bearing", "params": None, "title": "Ball bearing (size from the shaft)", "standard": "ISO 15",
                "name": "Deep-groove ball bearing", "confidence": "medium", "read": [], "kind": "bearing",
                "bore": bore}
    if fam == "dowel" or (fam in ("", "pin") and (words & {"dowel", "dowels"} or re.search(r"\b(locating|dowel) pins?\b", t)
                                                   or (words & {"pin", "pins"} and _dia(t)))):
        dd, ll = _dxl(t)
        mm_ = re.search(NUM + r"\s*mm\s+(?:dowel|pin|locating)", t)
        dd = dd or _dia(t) or (float(mm_.group(1)) if mm_ else None)
        ll = ll or _length(t)
        if not dd:
            return out("dowel", {}, [], "low", "dowel")
        read = ["D"] + (["L"] if ll else [])
        return out("dowel", {"D": dd, "L": ll or default_dowel_length(float(dd))}, read, "high" if ll else "medium", "dowel")
    if fam == "shaft" or (not fam and words & {"shaft", "shafts", "axle"} and not words & {"collar", "coupling"}):
        dd, ll = _dxl(t)
        dd = dd or _dia(t)
        ll = ll or _length(t)
        if dd:
            ll = ll or 120.0
            b = toolbox._key_for(dd)[0] if 8 < dd <= 65 else 3.0
            key_l = min(40.0, max(b + 2, round(0.4 * ll)))
            return out("shaft", {"D": dd, "L": ll, "KEY_L": key_l}, ["D"] + (["L"] if _length(t) or _dxl(t)[1] else []),
                       "high", "shaft")
    if fam == "gear" or (not fam and words & {"gear", "gears", "pinion"}):
        m = toolbox.match(core)
        g = next((x for x in m if x["code"] == "spur_gear"), None) or \
            next((x for x in toolbox.match("spur gear " + core) if x["code"] == "spur_gear"), None)
        if g:
            return out("spur_gear", dict(g["params"]), g["prefilled"], "high" if len(g["prefilled"]) >= 2 else "medium",
                       "gear")
    if (fam == "standoff" or (not fam and words & {"standoff", "standoffs", "spacer", "spacers"})) and d is not None:
        L = L or _length(t)
        return out("standoff", {"D": d, **({"L": L} if L else {})}, ["D"] + (["L"] if L else []), "medium")
    if fam:
        return None  # the named part is this family or nothing: never another kind of part
    m = toolbox.match(core)
    if m and m[0]["score"] >= 2:
        g = m[0]
        found = out(g["code"], dict(g["params"]), g["prefilled"], "medium" if g["prefilled"] else "low")
    return found


# ----------------------------------------------------------------------------- company parts
def _tok(s: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", s.lower()):
        if w in STOP or len(w) < 2 and not w.isdigit():
            continue
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 4 and w.endswith(("ses", "xes", "ches", "shes")):
            w = w[:-2]
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


def _clean_project_name(name: str) -> str:
    return name.removeprefix("Demo · ").strip()


def find_parts(query: str, candidates: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    """Company parts matching a clause, best first. ``candidates``: [{id, name, description, sig}] (sig from
    ``similarity.signature``; verified builds only). Score 0–1 from name words (and description words at half
    weight), or from the envelope when the query is a size ("the 120x80 plate")."""
    q = [w for w in _tok(query) if w not in GENERIC]
    dims = similarity.parse_size_query(query)
    hits = []
    for c in candidates:
        name = _tok(_clean_project_name(c["name"]))
        desc = set(_tok(c.get("description") or ""))
        score = 0.0
        reasons = []
        if q:
            in_name = [w for w in q if w in name]
            in_desc = [w for w in q if w not in name and w in desc]
            score = (len(in_name) + 0.5 * len(in_desc)) / len(q)
            if name:
                score *= 0.75 + 0.25 * len(in_name) / len(name)   # "bracket" fits "Motor Bracket" less than "Bracket"
            if in_name:
                reasons.append("name: " + " ".join(in_name))
            if in_desc:
                reasons.append("description: " + " ".join(in_desc))
        if dims and c.get("sig"):
            sm = similarity.size_match(dims, c["sig"])
            if sm["score"] >= 60:
                score = max(score, 0.5 + 0.5 * sm["score"] / 100)
                reasons += sm["reasons"]
        if score > 0:
            hits.append({"id": c["id"], "name": _clean_project_name(c["name"]), "score": round(score, 3),
                         "reasons": reasons})
    hits.sort(key=lambda h: (-h["score"], h["name"]))
    return hits[:limit]


# ----------------------------------------------------------------------------- resolve
def _conf_rank(c: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(c, 0)


def resolve(cl: Clause, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the source for one clause: Toolbox, your part, or new design. Deterministic, zero tokens."""
    tb = read_toolbox(cl.core)
    parts = find_parts(cl.core, candidates) if cl.core else []
    best = parts[0] if parts else None
    base = {"text": cl.text, "qty": cl.qty, "qty_explicit": cl.qty_explicit, "target_hint": cl.target,
            "mount": cl.mount, "alternatives": parts[1:]}
    designation = tb is not None and tb.get("read")
    if cl.own and best and best["score"] >= 0.5:
        return {**base, **_project(best)}
    if tb is not None and (designation or not best or best["score"] < 0.67):
        if tb["confidence"] == "low" and best and best["score"] >= 0.5:
            return {**base, **_project(best)}
        return {**base, "source": "toolbox", **tb,
                "found": f"Hex found {tb['title'] if tb.get('params') else tb['name']} in the Toolbox"}
    if best and best["score"] >= 0.5:
        return {**base, **_project(best)}
    return {**base, "source": "new", "kind": "part", "confidence": "low", "title": cl.core or cl.text,
            "found": f"Hex couldn't find “{cl.core or cl.text}” in the Toolbox or your parts"}


def _project(hit: dict[str, Any]) -> dict[str, Any]:
    conf = "high" if hit["score"] >= 0.99 else "medium" if hit["score"] >= 0.67 else "low"
    return {"source": "project", "kind": "part", "project_id": hit["id"], "title": hit["name"], "confidence": conf,
            "reasons": hit["reasons"], "found": f"Hex found {hit['name']} in your parts"}


# ----------------------------------------------------------------------------- AI fallback (opt-in, metered)
AI_INSTRUCTIONS = """You help a mechanical engineer add components to a CAD assembly. You never model anything. \
Map each request line to a standard component from the catalogue, or to one of the user's own parts, or to null \
when neither fits. Never invent sizes that are not written or clearly implied. Answer with exactly one fenced \
block tagged fw-items, nothing else after it."""


def ai_prompt(clauses: list[str], parts: list[str]) -> str:
    cat = [{"code": c["code"], "name": c["name"], "params": {p["name"]: p["label"] + (f" (one of {p['options']})"
                                                                                    if p["options"] else "")
                                                             for p in c["params"]}}
           for c in toolbox.catalog()]
    return ("Catalogue (code, parameters in mm):\n" + json.dumps(cat, ensure_ascii=False) +
            "\n\nThe user's own parts:\n" + json.dumps(parts[:200], ensure_ascii=False) +
            "\n\nRequest lines:\n" + "\n".join(f"{i}. {c}" for i, c in enumerate(clauses)) +
            '\n\nReturn:\n```fw-items\n[{"line": 0, "code": "hex_bolt" | null, "params": {"D": 6, "L": 25}, '
            '"part": "exact name of one of the user\'s parts" | null, "qty": 4}]\n```')


async def ask_ai(clauses: list[str], parts: list[str], budget_usd: float | None = None) -> tuple[str, float | None]:
    """One text-only turn of the design agent's model (no tools). Returns (answer, cost in USD). The only model call
    in this module; tests replace it."""
    from aicad import llm

    res = await llm.complete(llm.CallRequest(role="librarian", system=AI_INSTRUCTIONS,
                                             prompt=ai_prompt(clauses, parts), budget_usd=budget_usd))
    return res.text, res.metering.cost_usd


_BLOCK = re.compile(r"```(?:fw-items|json)?\s*\n(.*?)\n?```", re.DOTALL)


def read_ai(text: str, n: int, candidates: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Validated AI suggestions per clause index. Anything that doesn't pass toolbox.normalize or name an existing
    part is dropped."""
    blocks = _BLOCK.findall(text or "")
    raw: Any = None
    for b in reversed(blocks or [text or ""]):
        try:
            raw = json.loads(b)
            break
        except ValueError:
            continue
    if not isinstance(raw, list):
        return {}
    names = {_clean_project_name(c["name"]).lower(): c for c in candidates}
    out: dict[int, dict[str, Any]] = {}
    for r in raw[:50]:
        if not isinstance(r, dict) or not isinstance(r.get("line"), int) or not 0 <= r["line"] < n:
            continue
        qty = r.get("qty")
        qty = int(qty) if isinstance(qty, int | float) and 1 <= qty <= MAX_QTY else None
        if isinstance(r.get("part"), str) and r["part"].strip().lower() in names:
            c = names[r["part"].strip().lower()]
            out[r["line"]] = {**_project({"id": c["id"], "name": _clean_project_name(c["name"]), "score": 0.7,
                                          "reasons": ["read by AI"]}), "qty": qty, "confidence": "medium"}
            continue
        code = r.get("code")
        if not isinstance(code, str) or code not in toolbox.COMPONENTS:
            continue
        params = r.get("params") if isinstance(r.get("params"), dict) else {}
        try:
            p = toolbox.normalize(code, {k: v for k, v in params.items() if isinstance(v, int | float)})
        except toolbox.ToolboxError:
            continue
        c = toolbox.spec(code)
        kind = {"hex_bolt": "fastener", "shcs": "fastener", "bearing": "bearing", "dowel": "dowel",
                "shaft": "shaft", "spur_gear": "gear"}.get(code, "part")
        item = {"source": "toolbox", "code": code, "params": p, "title": c.title(p), "standard": c.standard,
                "name": c.name, "confidence": "medium", "read": sorted(params), "kind": kind, "qty": qty,
                "found": f"Hex read it with AI: {c.title(p)} from the Toolbox"}
        if kind == "fastener":
            item["fasten"] = {"style": code, "washers": "both", "size": int(p["D"]), "length": p.get("L")}
        out[r["line"]] = item
    return out
