"""What the brief asks for, read deterministically: which kinds of part it names, which it excludes, whether it
limits the program to exactly those ("no extra items", "just a gear, a shaft and a key", "only", "without a
housing"), and whether a program is small enough for the light path.

Founder, 2026-11-19: "Build a Spur Gear mounted on stepped Shaft and locked with a key" took the Design Studio a
minute; the Design Office added a shaft support housing although the brief said "No extra items. Just a spur gear, a
shaft and a key", ran 9 tickets for 3 parts and still assembled it wrong. ``respect`` is the post-check on every plan a
planner makes (Archie or the standard breakdown): parts of a kind the brief excludes, or does not name when it is
exclusive, are left out, with a plain-words note for the engineer. The engineer's own edits are never touched.

Pure (no kernel, no model): tested against the founder's sentences.
"""

from __future__ import annotations

import re
from typing import Any

# kinds of part, by the nouns that name them (the head noun of a part name is its rightmost match)
KINDS: list[tuple[str, str]] = [
    ("gear", r"gears?|pinions?|gearwheels?|cogs?"),
    ("shaft", r"shafts?|axles?|spindles?|arbou?rs?"),
    ("key", r"keys?|keyed"),
    ("bearing", r"bearings?|6[02]0\d"),
    ("ring", r"circlips?|retaining rings?|snap rings?|e-?clips?|seeger rings?"),
    ("housing", r"housings?|casings?|cases?|gear ?box(?:es)?|enclosures?"),
    ("plate", r"plates?"),
    ("support", r"supports?|pedestals?|stands?|frames?|brackets?|blocks?|bases?|mounts?|carriers?|chassis"),
    ("spacer", r"spacers?|sleeves?|collars?|bush(?:es|ings?)?|distance rings?"),
    ("fastener", r"bolts?|screws?|nuts?|washers?|studs?|fasteners?"),
    ("pin", r"pins?|dowels?"),
    ("cap", r"caps?|covers?|lids?|end plates?"),
    ("seal", r"seals?|o-?rings?|gaskets?"),
    ("pulley", r"pulleys?|sprockets?|sheaves?"),
    ("hub", r"hubs?"),
    ("coupling", r"couplings?"),
    ("motor", r"motors?"),
]
_KIND_RX = [(k, re.compile(rf"(?<![\w-])(?:{p})(?![\w-])", re.IGNORECASE)) for k, p in KINDS]

_NEG = re.compile(r"\b(?:no|without|not|nor|never|exclud\w*|except|minus|omit\w*|leave out|drop)\b", re.IGNORECASE)
_EXCLUSIVE = re.compile(
    r"\bno (?:extra|other|additional|more|further|separate) (?:items?|parts?|components?|pieces?|things?)\b|"
    r"\bno extras\b|\bnothing (?:else|more|extra)\b|\bthat'?s all\b|\bonly\b|\bjust\b|\bexclusively\b|\bsolely\b",
    re.IGNORECASE)
_LIMIT = re.compile(r"\b(?:just|only)\b[^.;!?\n]*", re.IGNORECASE)
_NOEXTRA = re.compile(r"\bno (?:extra|other|additional|more|further) (?:items?|parts?|components?)|\bnothing else\b|"
                      r"\bno extras\b", re.IGNORECASE)
# words that start a positive clause again after a negation ("no housing, just a gear and a shaft")
_POSITIVE = re.compile(r"\b(?:just|only|with|build|make|design|add|plus|include|including|use)\b", re.IGNORECASE)

# the light path (PD-88): a program this small is planned, laid out and assembled in one step
SMALL_MAX_LINES = 6     # part lines in the plan
SMALL_MAX_PIECES = 8    # pieces in total (quantities summed)
DELIVERABLES_ASKED = re.compile(r"\bdrawings?\b|\bdrawn\b|\bdfm\b|manufactur|\bbom\b|bill of materials|"
                                r"\brelease\b|\bdetail(?:ed)? sheets?\b", re.IGNORECASE)


def kind_of(name: str) -> str | None:
    """The kind of a part by the head noun of its name (the rightmost noun: "Shaft support housing" is a housing,
    "Pinion key" a key, "Gear shaft" a shaft); None when no kind matches."""
    best: tuple[int, str] | None = None
    for k, rx in _KIND_RX:
        for m in rx.finditer(name or ""):
            if best is None or m.end() > best[0] or (m.end() == best[0] and k == "ring"):
                best = (m.end(), k)
    return best[1] if best else None


def _chunks(text: str) -> list[str]:
    return [c for c in re.split(r"[.;:!?\n]+", text or "") if c.strip()]


def mentions(brief: str) -> tuple[set[str], set[str]]:
    """(kinds the brief names, kinds it excludes). A kind is excluded when a negation ("no", "without", "not",
    "except") comes before it in its clause, with no positive word ("just", "with", "build", ...) in between; a
    comma list after a negation stays negated ("without a housing, bearings or a base plate")."""
    named: set[str] = set()
    excluded: set[str] = set()
    for chunk in _chunks(brief):
        neg = False
        for part in re.split(r",", chunk):
            hits: list[tuple[int, str]] = []
            for k, rx in _KIND_RX:
                hits += [(m.start(), k) for m in rx.finditer(part)]
            if not hits:
                if _NEG.search(part):
                    neg = True
                if _POSITIVE.search(part):
                    neg = False
                continue
            # a new comma part keeps the negation only while it is a bare list ("bearings or a base plate")
            if neg and (_POSITIVE.search(part) or not re.search(r"\b(?:or|nor|and)\b|^\s*(?:a|an|any|the)?\s*\w+\s*$",
                                                                   part, re.IGNORECASE)):
                neg = False
            pos = 0
            for at, k in sorted(hits):
                before = part[pos:at]
                if _NEG.search(before):
                    neg = True
                if _POSITIVE.search(before):
                    neg = False
                (excluded if neg else named).add(k)
                pos = at
    return named - excluded, excluded


def exclusive(brief: str) -> bool:
    """The brief limits the program to what it names."""
    return bool(_EXCLUSIVE.search(brief or ""))


def _phrase(brief: str) -> str:
    m = _LIMIT.search(brief or "")
    if m:
        return " ".join(m.group(0).split()).rstrip(" ,").lower()
    m = _NOEXTRA.search(brief or "")
    if m:
        return " ".join(m.group(0).split()).lower()
    for chunk in _chunks(brief):
        m = re.search(r"\b(?:no|without|not|except)\b.*", chunk, re.IGNORECASE)
        if m and any(rx.search(m.group(0)) for _k, rx in _KIND_RX):
            return " ".join(m.group(0).split()).rstrip(" ,").lower()
    return "only what the brief names"


def _listed(names: list[str]) -> str:
    low = [n[:1].lower() + n[1:] if n[1:2].islower() or len(n) < 2 else n for n in names]
    return low[0] if len(low) == 1 else ", ".join(low[:-1]) + " and " + low[-1]


def respect(plan: dict[str, Any], brief: str) -> tuple[dict[str, Any], list[str], str | None]:
    """The plan without the parts the brief excludes (or, when it is exclusive, does not name), the names left out,
    and a note for the engineer in plain words. Parts of an unknown kind stay (we can't tell); a plan is never
    emptied of its designed parts (then the reading is wrong, and the plan stays as it was)."""
    named, excluded = mentions(brief)
    excl = exclusive(brief)
    if not excluded and not (excl and named):
        return plan, [], None
    dropped: list[str] = []
    subs: list[dict[str, Any]] = []
    for s in plan.get("subassemblies") or []:
        keep = []
        for p in s.get("parts") or []:
            k = kind_of(str(p.get("name") or ""))
            if k is not None and (k in excluded or (excl and named and k not in named)):
                dropped.append(str(p["name"]))
                continue
            keep.append(p)
        if keep:
            subs.append({**s, "parts": keep})
    designed = [p for s in subs for p in s["parts"] if p.get("family") != "standard"]
    if not dropped or not designed:
        return plan, [], None
    gone = {d.lower() for d in dropped}
    for s in subs:
        for p in s["parts"]:
            if str(p.get("mounts_on") or "").lower() in gone:
                p.pop("mounts_on", None)
    out = {**plan, "subassemblies": subs}
    note = (f"You asked for {_phrase(brief)}, so I left out the {_listed(dropped)} I'd normally add. Add "
            f"{'it' if len(dropped) == 1 else 'them'} back here if you want {'it' if len(dropped) == 1 else 'them'}.")
    out["scope"] = {"exclusive": excl, "named": sorted(named), "excluded": sorted(excluded), "dropped": dropped}
    return out, dropped, note


# ----------------------------------------------------------------------------- the light path
def pieces(plan: dict[str, Any]) -> tuple[int, int]:
    """(part lines, pieces) of a plan."""
    parts = [p for s in plan.get("subassemblies") or [] for p in s.get("parts") or []]
    return len(parts), sum(max(1, int(p.get("qty") or 1)) for p in parts)


def small(plan: dict[str, Any] | None) -> bool:
    """PD-88: at most SMALL_MAX_LINES part lines and SMALL_MAX_PIECES pieces (keys and rings count)."""
    if not plan:
        return False
    lines, n = pieces(plan)
    return 0 < lines <= SMALL_MAX_LINES and n <= SMALL_MAX_PIECES


RIDERS = frozenset({"shaft", "gear", "pulley", "hub", "spacer", "key", "ring", "bearing"})


def rides_on_shafts(plan: dict[str, Any]) -> bool:
    """Every part is a shaft or something that rides on one (gears, pulleys, hubs, spacers, keys, rings, bearings):
    the plan is physically one unit, whatever groups the planner drew. Nothing of an unknown kind."""
    parts = [p for s in plan.get("subassemblies") or [] for p in s.get("parts") or []]
    kinds = [kind_of(str(p.get("name") or "")) for p in parts]
    return bool(parts) and "shaft" in kinds and all(k in RIDERS for k in kinds)


def one_unit(plan: dict[str, Any], name: str | None = None) -> dict[str, Any]:
    """A small plan as one sub-assembly (its parts assemble as one unit): one integration ticket, not one per group.
    The first sub-assembly's name and description stay."""
    subs = plan.get("subassemblies") or []
    if len(subs) <= 1:
        return plan
    first = subs[0]
    parts = [dict(p) for s in subs for p in s.get("parts") or []]
    return {**plan, "subassemblies": [{**first, "name": name or first["name"], "parts": parts}]}


def deliverables_asked(brief: str) -> bool:
    return bool(DELIVERABLES_ASKED.search(brief or ""))


def light_info(plan: dict[str, Any] | None, brief: str) -> dict[str, Any] | None:
    """What the light path changes for this plan (None when the program is not small)."""
    if not small(plan):
        return None
    lines, n = pieces(plan or {})
    asked = deliverables_asked(brief)
    return {"rule": f"at most {SMALL_MAX_LINES} part lines and {SMALL_MAX_PIECES} pieces",
            "parts": lines, "pieces": n, "deliverables_asked": asked,
            "text": ("Approve the plan and the interfaces in one step: the office builds it straight away when the "
                     "interfaces have no problems (otherwise they wait for you). "
                     + ("Drawings and the manufacturing review follow, as the brief asks." if asked else
                        "Drawings and the manufacturing review run only when you ask for them."))}


NAMED_KINDS = frozenset({"gear", "shaft", "key", "bearing", "ring", "pulley", "hub", "spacer"})


def named_plan(name: str, brief: str) -> dict[str, Any] | None:
    """The standard planner's breakdown for a brief that names its parts and matches no product template ("a spur
    gear on a stepped shaft, locked with a key"): exactly those parts, one sub-assembly, sizes assumed and said so.
    None when the brief names no designed part."""
    named, _excluded = mentions(brief)
    t = brief or ""
    stepped = bool(re.search(r"\bstepped\b|\bshoulder", t, re.IGNORECASE))
    pulley = "pulley" in named
    rows: list[dict[str, Any]] = []
    if "shaft" in named:
        rows.append({"name": "Stepped shaft" if stepped else "Shaft", "family": "turned", "complexity": 2, "qty": 1,
                     "envelope": [20.0, 20.0, 80.0],
                     "description": (("Stepped steel shaft: a Ø20 seat with a shoulder the "
                                      + ("gear" if "gear" in named else "hub") + " locates against" if stepped
                                      else "Steel shaft Ø20") + ", 80 long (sizes assumed).")})
    if "gear" in named:
        g = {"name": "Spur gear", "family": "gear", "complexity": 2, "qty": 1, "module": 2.0, "teeth": 30,
             "description": "Spur gear, module 2, 30 teeth, face width 20 (sizes assumed), bored to suit the shaft"
                            + (", with a keyway for the key." if "key" in named else ".")}
        if "shaft" in named:
            g["mounts_on"] = rows[0]["name"]
        rows.append(g)
    if pulley:
        rows.append({"name": "Pulley", "family": "turned", "complexity": 2, "qty": 1,
                     "description": "Pulley bored to suit the shaft (sizes assumed)."})
    if "hub" in named:
        rows.append({"name": "Hub", "family": "turned", "complexity": 2, "qty": 1,
                     "description": "Hub bored to suit the shaft (sizes assumed)."})
    if "spacer" in named:
        rows.append({"name": "Spacer", "family": "turned", "complexity": 1, "qty": 1,
                     "description": "Spacer ring bored to suit the shaft (sizes assumed)."})
    if not rows:
        return None
    if "key" in named:
        rows.append({"name": "Parallel key", "family": "standard", "complexity": 1, "qty": 1,
                     "description": "Parallel key DIN 6885 form A, sized to the shaft seat."})
    if "bearing" in named:
        rows.append({"name": "Ball bearing", "family": "standard", "complexity": 1, "qty": 2,
                     "description": "Deep-groove ball bearings carrying the shaft, sized to it."})
    if "ring" in named:
        rows.append({"name": "Retaining ring", "family": "standard", "complexity": 1, "qty": 1,
                     "description": "DIN 471 retaining ring sized to the shaft."})
    what = ", ".join(r["name"].lower() for r in rows)
    sizes = ("The brief gives no sizes: module 2, 30 teeth, a Ø20 shaft 80 long are assumed; the key follows DIN "
             "6885 for the shaft." if "gear" in named else "The brief gives no sizes: a Ø20 shaft 80 long is assumed.")
    carried = ("The bearings carry the shaft; no housing unless the brief names one." if "bearing" in named else
               "No bearings or housing unless the brief names them: the shaft is delivered with what it carries, as "
               "a sub-assembly.")
    return {"summary": f"The parts the brief names, nothing else: {what}.",
            "assumptions": [sizes, carried],
            "subassemblies": [{"name": name if len(name) <= 40 else "Shaft assembly",
                               "description": "The shaft with what it carries, assembled as one unit.",
                               "parts": rows}]}
