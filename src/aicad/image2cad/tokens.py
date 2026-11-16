"""Dimension-text parser for engineering drawings (deterministic, no AI).

``parse(text)`` returns a structured dimension for a text that *is* a dimension callout, or ``None`` for anything
else (sentences, notes, part numbers, dates). The whole text must match: a number inside a sentence is not a
dimension. Conventions follow ISO 129-1 / ASME Y14.5 callout practice:

  100            linear                      (10)          reference dimension (parentheses)
  25±0.1         linear, symmetric tol.      25 +0.1/-0.05 linear, limit deviations
  Ø12 H7         diameter with ISO fit        R5 / SR10     radius / spherical radius
  4X Ø6.6 THRU   count, diameter, through     Ø6 DEEP 10    blind depth (also "↧10", "DP 10")
  M8x1.25-6H     metric thread, pitch, class  45°           angle
  1 x 45°        chamfer                      1:2           scale ratio (also "SCALE 1:2")
  □20            square                       10 TYP        typical (applies to like features)
"""

from __future__ import annotations

import re
from typing import Any

NUM = r"(?:\d+(?:[.,]\d+)?|[.,]\d+)"
_N = re.compile(NUM)

_SYMBOLS = str.maketrans({"⌀": "Ø", "∅": "Ø", "ø": "Ø", "Φ": "Ø", "φ": "Ø", "×": "x", "−": "-", "–": "-",
                          "º": "°", "˚": "°", " ": " "})
def _tol_re(k: str = "") -> str:
    return (rf"(?:±\s*(?P<pm{k}>{NUM})"
            rf"|\+\s*(?P<up{k}>{NUM})\s*/?\s*-\s*(?P<lo{k}>{NUM})"
            rf"|\+\s*(?P<upz{k}>{NUM})\s*/\s*0"
            rf"|0\s*/\s*-\s*(?P<loz{k}>{NUM}))")


TOL, TOL2 = _tol_re(), _tol_re("2")
FIT = r"(?P<fit>(?:[A-HJ-NP-Za-hj-np-z]|[JjZz][Ss]?|[Cc][Dd]|[Ee][Ff]|[Ff][Gg])\d{1,2}(?:\s*/\s*[A-Za-z]{1,2}\d{1,2})?)"
UNIT = r"(?P<unit>mm|in|\"|inch|inches)"

_RE_SCALE = re.compile(rf"(?:SCALE\s*:?\s*)?(?P<a>{NUM})\s*:\s*(?P<b>{NUM})", re.IGNORECASE)
_RE_CHAMFER = re.compile(rf"(?P<v>{NUM})\s*(?:mm)?\s*x\s*(?P<ang>{NUM})\s*°", re.IGNORECASE)
_RE_CHAMFER_C = re.compile(rf"C\s*(?P<v>{NUM})")
_RE_THREAD = re.compile(rf"M\s*(?P<d>{NUM})(?:\s*x\s*(?P<p>{NUM}))?(?:\s*-\s*(?P<cls>\d[A-Ha-h](?:\d[A-Ha-h])?))?"
                        rf"(?:\s*-?\s*(?P<lh>LH))?", re.IGNORECASE)
_RE_ANGLE = re.compile(rf"(?P<v>{NUM})\s*(?:°|DEG\b|DEGREES?\b)\s*(?:{TOL}\s*°?)?", re.IGNORECASE)
_RE_PREFIXED = re.compile(rf"(?P<sym>SØ|SR|Ø|R|□)\s*(?P<v>{NUM})\s*(?:{UNIT})?\s*(?:{TOL})?\s*(?:{FIT})?\s*(?:{TOL2})?",
                          re.IGNORECASE)
_RE_LINEAR = re.compile(rf"(?P<v>{NUM})\s*(?:{UNIT})?\s*(?:{TOL})?\s*(?:{FIT})?\s*(?:{TOL2})?")

_LEAD_COUNT = [re.compile(r"^(?P<n>\d{1,3})\s*x\s+(?=\S)", re.IGNORECASE),          # "4X Ø6", "4 x R5"
               re.compile(r"^(?P<n>\d{1,3})\s*x(?=[ØRMS□])", re.IGNORECASE),          # "4XØ6"
               re.compile(r"^(?P<n>\d{1,3})\s+(?:HOLES?|PLCS|PLACES)\s+", re.IGNORECASE)]
_TRAIL_COUNT = re.compile(r"\s*[(\[]?\s*(?P<n>\d{1,3})\s*(?:X|PLCS|PLACES|HOLES?)\s*[)\]]?$", re.IGNORECASE)
_SUFFIXES: list[tuple[str, re.Pattern[str]]] = [
    ("through", re.compile(r"\s*\b(?:THRU(?:\s+ALL)?|THROUGH)\s*$", re.IGNORECASE)),
    ("depth", re.compile(rf"\s*(?:\b(?:DEEP|DP|DEPTH)\s*(?P<d>{NUM})|↧\s*(?P<d2>{NUM})|x\s*(?P<d3>{NUM})\s*(?:DEEP|DP))\s*$",
                         re.IGNORECASE)),
    ("depth", re.compile(rf"\s*(?:x\s*)?(?P<d>{NUM})\s*(?:DEEP|DP)\s*$", re.IGNORECASE)),
    ("typ", re.compile(r"\s*\bTYP(?:ICAL|\.)?\s*$", re.IGNORECASE)),
    ("eqsp", re.compile(r"\s*\bEQ\.?\s*SP(?:ACED|\.)?\s*$", re.IGNORECASE)),
    ("pcd", re.compile(r"\s*\b(?:PCD|BCD|P\.C\.D\.?|B\.C\.)\s*$", re.IGNORECASE)),
    ("max", re.compile(r"\s*\bMAX\.?\s*$", re.IGNORECASE)),
    ("min", re.compile(r"\s*\bMIN\.?\s*$", re.IGNORECASE)),
    ("ref", re.compile(r"\s*\bREF\.?\s*$", re.IGNORECASE)),
    ("cbore", re.compile(r"\s*(?:\bC'?BORE\b|⌴)\s*$", re.IGNORECASE)),
    ("csk", re.compile(r"\s*(?:\bC'?SINK\b|\bCSK\b|⌵)\s*$", re.IGNORECASE)),
]
_PREFIX_KIND = {"Ø": "diameter", "R": "radius", "SR": "spherical_radius", "SØ": "spherical_diameter", "□": "square"}
KINDS = ("linear", "diameter", "radius", "spherical_radius", "spherical_diameter", "square", "thread", "angle",
         "chamfer", "scale")


def num(s: str | None) -> float | None:
    if s is None or s == "":
        return None
    return float(s.replace(",", "."))


def normalize(text: str) -> str:
    t = text.translate(_SYMBOLS)
    t = re.sub(r"\+\s*/\s*-", "±", t)  # +/- 0.1 -> ±0.1
    return " ".join(t.split())


def _tol(m: re.Match[str]) -> dict[str, float] | None:
    g = m.groupdict()
    for k in ("", "2"):
        if g.get(f"pm{k}"):
            v = num(g[f"pm{k}"]) or 0.0
            return {"plus": v, "minus": v}
        if g.get(f"up{k}") is not None and g.get(f"lo{k}") is not None:
            return {"plus": num(g[f"up{k}"]) or 0.0, "minus": num(g[f"lo{k}"]) or 0.0}
        if g.get(f"upz{k}"):
            return {"plus": num(g[f"upz{k}"]) or 0.0, "minus": 0.0}
        if g.get(f"loz{k}"):
            return {"plus": 0.0, "minus": num(g[f"loz{k}"]) or 0.0}
    return None


def _unit(u: str | None) -> str | None:
    if not u:
        return None
    return "mm" if u.lower() == "mm" else "in"


def parse(text: str) -> dict[str, Any] | None:
    """Structured dimension for a callout text, or None when the text is not a dimension."""
    raw = normalize(text)
    if not raw or len(raw) > 60:
        return None
    t = raw
    out: dict[str, Any] = {"text": raw, "kind": None, "value": None, "count": None, "tol": None, "fit": None,
                           "unit": None, "reference": False, "through": False, "depth": None, "modifiers": []}
    # reference dimension: the whole callout in parentheses
    if t.startswith("(") and t.endswith(")") and t.count("(") == 1:
        out["reference"] = True
        t = t[1:-1].strip()
    m = _RE_SCALE.fullmatch(t)
    if m:
        a, b = num(m["a"]), num(m["b"])
        if a and b:
            return {**out, "kind": "scale", "value": a / b, "ratio": [a, b], "reference": False}
    m = _RE_CHAMFER.fullmatch(t)
    if m:
        return {**out, "kind": "chamfer", "value": num(m["v"]), "angle": num(m["ang"])}
    for rx in _LEAD_COUNT:
        m = rx.match(t)
        if m:
            out["count"] = int(m["n"])
            t = t[m.end():].strip()
            break
    if out["count"] is None:
        m = _TRAIL_COUNT.search(t)
        if m and m.start() > 0:
            out["count"] = int(m["n"])
            t = t[:m.start()].strip()
    # trailing modifiers, any order
    changed = True
    while changed and t:
        changed = False
        for name, rx in _SUFFIXES:
            m = rx.search(t)
            if m and m.start() > 0:
                if name == "through":
                    out["through"] = True
                elif name == "depth":
                    out["depth"] = num(m.groupdict().get("d") or m.groupdict().get("d2") or m.groupdict().get("d3"))
                elif name == "ref":
                    out["reference"] = True
                else:
                    out["modifiers"].append(name)
                t = t[:m.start()].strip()
                changed = True
                break
    if out["count"] is None:  # "Ø6 4X THRU" (count after the size)
        m = _TRAIL_COUNT.search(t)
        if m and m.start() > 0:
            out["count"] = int(m["n"])
            t = t[:m.start()].strip()
    m = _RE_CHAMFER_C.fullmatch(t)
    if m:
        return {**out, "kind": "chamfer", "value": num(m["v"]), "angle": 45.0}
    m = _RE_CHAMFER.fullmatch(t)
    if m:
        return {**out, "kind": "chamfer", "value": num(m["v"]), "angle": num(m["ang"])}
    m = _RE_THREAD.fullmatch(t)
    if m:
        return {**out, "kind": "thread", "value": num(m["d"]), "pitch": num(m["p"]), "thread_class": m["cls"],
                "left_hand": bool(m["lh"])}
    m = _RE_ANGLE.fullmatch(t)
    if m:
        return {**out, "kind": "angle", "value": num(m["v"]), "tol": _tol(m), "unit": "deg"}
    m = _RE_PREFIXED.fullmatch(t)
    if m:
        sym = m["sym"].upper()
        return {**out, "kind": _PREFIX_KIND[sym], "value": num(m["v"]), "tol": _tol(m), "fit": _fit(m["fit"]),
                "unit": _unit(m["unit"])}
    m = _RE_LINEAR.fullmatch(t)
    if m:
        return {**out, "kind": "linear", "value": num(m["v"]), "tol": _tol(m), "fit": _fit(m["fit"]),
                "unit": _unit(m["unit"])}
    return None


def _fit(f: str | None) -> str | None:
    return re.sub(r"\s+", "", f) if f else None


def label(d: dict[str, Any]) -> str:
    """Canonical callout text for a parsed (or user-edited) dimension, e.g. ``4X Ø6.6 THRU``."""
    v = d.get("value")
    vs = fmt(v) if isinstance(v, (int, float)) else "?"
    k = d.get("kind") or "linear"
    core = {"diameter": f"Ø{vs}", "radius": f"R{vs}", "spherical_radius": f"SR{vs}",
            "spherical_diameter": f"SØ{vs}", "square": f"□{vs}", "angle": f"{vs}°",
            "scale": f"1:{fmt(1 / v) if v else '?'}" if isinstance(v, (int, float)) and v and v < 1 else f"{vs}:1"}.get(k, vs)
    if k == "thread":
        core = f"M{vs}" + (f"x{fmt(d['pitch'])}" if d.get("pitch") else "") + (f"-{d['thread_class']}" if d.get("thread_class") else "")
    if k == "chamfer":
        core = f"{vs} x {fmt(d.get('angle') or 45)}°"
    if d.get("unit") == "in" and k != "angle":
        core += '"'
    if d.get("fit"):
        core += f" {d['fit']}"
    tol = d.get("tol")
    if tol:
        up, lo = fmt(tol["plus"]), fmt(tol["minus"])
        core += (f" ±{up}" if tol["plus"] == tol["minus"] else
                 f" +{up}/0" if not tol["minus"] else f" 0/-{lo}" if not tol["plus"] else f" +{up}/-{lo}")
    if d.get("count"):
        core = f"{d['count']}X {core}"
    if d.get("through"):
        core += " THRU"
    if d.get("depth"):
        core += f" DEEP {fmt(d['depth'])}"
    for m in d.get("modifiers") or []:
        core += " " + {"typ": "TYP", "eqsp": "EQ SP", "pcd": "PCD", "max": "MAX", "min": "MIN", "cbore": "CBORE",
                       "csk": "CSK"}.get(m, m.upper())
    if d.get("reference"):
        core = f"({core})"
    return core


def fmt(v: float | None) -> str:
    if v is None:
        return "?"
    return f"{v:.4f}".rstrip("0").rstrip(".")


def looks_numeric(text: str) -> bool:
    """True when a text holds a number but is not a parseable callout (shown as 'unparsed' for review)."""
    return bool(_N.search(normalize(text)))
