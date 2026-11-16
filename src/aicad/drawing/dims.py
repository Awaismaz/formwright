"""Candidate dimensions and hole callouts from the exact census, tagged ``spec`` or ``inferred``.

Rules (deterministic, documented in docs/reports/drawings.md):
- Every value is measured from the model geometry. A dimension is tagged ``spec`` when its value equals a declared
  model parameter (``PARAMS``) of a compatible kind (diameter, length, position ...) and that match is
  unambiguous: no other compatible parameter has the same value, and the parameter does not match two
  dimensions of the same family (e.g. two segments of one chain). Otherwise it is ``inferred``.
- Each measurement is dimensioned once (ISO 129-1): overall extents, turned diameters, hole callouts with
  quantity / diameter / THRU or depth, hole locations from the nearest edge, step chains between planar levels.
- One segment of a chain is shown as an auxiliary (reference) dimension in parentheses so that a chain plus the
  overall size is not over-dimensioned.
- Tolerances and GD&T are never generated here.
"""

from __future__ import annotations

import itertools
import math
import re
from typing import Any

from aicad.drawing.geometry import AXIS_INDEX

#: Where each model axis appears in the principal views (U is paper-right, V is paper-up).
COORD = {"front": {"x": "u", "z": "v"}, "top": {"x": "u", "y": "v"}, "right": {"y": "u", "z": "v"}}
EXTENT_VIEWS = {"x": ["front", "top"], "y": ["top", "right"], "z": ["front", "right"]}
CHAIN_VIEWS = {"x": ["top", "front"], "y": ["top", "right"], "z": ["front", "right"]}
CIRCLE_VIEW = {"x": "right", "y": "front", "z": "top"}  # the view that looks along a hole axis
DIA_VIEWS = {"z": [("front", "x"), ("right", "y")], "x": [("front", "z"), ("top", "y")],
             "y": [("top", "x"), ("right", "z")]}
COMPATIBLE = {"extent": {"linear", "any"}, "step": {"linear", "any"}, "depth": {"linear", "any"},
              "diameter": {"dia", "any"}, "hole": {"dia", "any"}, "pcd": {"pcd", "any"},
              "position": {"position", "any"}}
TOL = 1e-6


def fmt(v: float) -> str:
    """Drawing number format: millimetres, at most 2 decimals, no trailing zeros."""
    s = f"{round(v + 0.0, 2):.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def param_kind(name: str, meta: dict[str, Any] | None = None) -> str:
    """Classify a declared parameter from its name and label (used only to stop coincidental matches)."""
    label = str((meta or {}).get("label", ""))
    s = f"{name} {label}".lower()
    toks = {t for t in re.split(r"[^a-z0-9ø]+", s) if t}
    if "pcd" in toks or ("pitch" in toks and ({"circle", "dia", "diameter"} & toks or "ø" in s)):
        return "pcd"
    if {"angle", "deg", "degrees"} & toks:
        return "angle"
    if {"n", "count", "num", "qty", "number"} & toks or name.lower().startswith("n_"):
        return "count"
    if {"r", "rad", "radius", "fillet", "round", "chamfer", "ch"} & toks:
        return "other"
    if {"d", "dia", "diameter", "bore", "od", "id"} & toks or "ø" in s or any(re.fullmatch(r"d\d+", t) for t in toks):
        return "dia"
    if {"edge", "offset", "inset", "spacing", "pitch", "pos", "position", "from", "dist", "distance", "margin",
            "centre", "center"} & toks:
        return "position"
    if {"l", "w", "t", "h", "len", "length", "width", "thick", "thickness", "height", "depth", "leg", "size", "step",
            "long", "wide", "tall"} & toks or any(re.fullmatch(r"[lwth]\d+", t) for t in toks):
        return "linear"
    return "any"


def _side_span(points: list[float]) -> list[float]:
    return [min(points), max(points)]


def _dim(id_: str, kind: str, view: str, orient: str, a: float, b: float, *, prefix: str = "",
         ext_a: list[float] | None = None, ext_b: list[float] | None = None, family: str = "",
         order: int = 0) -> dict[str, Any]:
    a, b = (a, b) if a <= b else (b, a)
    return {"id": id_, "kind": kind, "view": view, "orient": orient, "a": a, "b": b, "value": round(b - a, 6),
            "prefix": prefix, "ext_a": ext_a, "ext_b": ext_b, "family": family or id_, "aux": False,
            "tag": "inferred", "param": None, "order": order}


def _first(views: list[str], enabled: set[str]) -> str | None:
    return next((v for v in views if v in enabled), None)


def _revolve(cen: dict[str, Any]) -> tuple[str, list[float], float] | None:
    """Axis, centre and envelope diameter when the outer envelope is a turned (coaxial cylinder) body."""
    bb = cen["bbox"]
    for ax in ("z", "x", "y"):
        i = AXIS_INDEX[ax]
        others = [j for j in range(3) if j != i]
        centre = [round((bb[j] + bb[j + 3]) / 2, 6) for j in others]
        ext = [bb[j + 3] - bb[j] for j in others]
        cyl = [c for c in cen["outer"] if c["axis"] == ax and all(abs(c["centre"][k] - centre[k]) < TOL for k in (0, 1))]
        if cyl:
            d = max(c["dia"] for c in cyl)
            if all(abs(d - e) < TOL for e in ext):
                return ax, centre, d
    return None


def candidates(cen: dict[str, Any], enabled: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """All dimensions and callouts the sheet will show (before tagging and placement)."""
    bb = cen["bbox"]
    lo = {a: bb[i] for a, i in AXIS_INDEX.items()}
    hi = {a: bb[i + 3] for a, i in AXIS_INDEX.items()}
    dims: list[dict[str, Any]] = []
    callouts: list[dict[str, Any]] = []
    notes: list[str] = []
    rev = _revolve(cen)

    # turned envelope: diameters replace the two extents across the axis
    covered: set[str] = set()
    if rev:
        ax, centre, _env = rev
        others = [a for a in ("x", "y", "z") if a != ax]
        for view, along in DIA_VIEWS[ax]:
            if view in enabled:
                k = others.index(along)
                c0 = centre[k]
                seen: set[float] = set()
                for c in sorted(cen["outer"], key=lambda c: (-c["dia"], c["t0"])):
                    if c["axis"] != ax or any(abs(c["centre"][j] - centre[j]) > TOL for j in (0, 1)):
                        continue
                    if c["dia"] in seen:
                        continue
                    seen.add(c["dia"])
                    r = c["dia"] / 2
                    o = COORD[view][along]
                    dims.append(_dim(f"dia-{ax}-{len(seen)}", "diameter", view, "h" if o == "u" else "v",
                                     c0 - r, c0 + r, prefix="Ø", family=f"dia-{ax}-{len(seen)}", order=1))
                covered = set(others)
                break

    # overall extents
    for ax in ("x", "y", "z"):
        if ax in covered:
            continue
        view = _first(EXTENT_VIEWS[ax], enabled)
        if view is None:
            notes.append(f"Overall {ax.upper()} size is not shown: no enabled view shows it.")
            continue
        o = COORD[view][ax]
        dims.append(_dim(f"ext-{ax}", "extent", view, "h" if o == "u" else "v", lo[ax], hi[ax], order=9))

    # step chains between planar levels along each axis
    for ax in ("x", "y", "z"):
        if rev and ax != rev[0] and not cen["levels"][ax]:
            continue
        vals = sorted({v for v in cen["levels"][ax] if lo[ax] - TOL <= v <= hi[ax] + TOL} | {lo[ax], hi[ax]})
        dedup: list[float] = []
        for v in vals:
            if not dedup or v - dedup[-1] > TOL:
                dedup.append(v)
        if not 3 <= len(dedup) <= 7 or min(b - a for a, b in itertools.pairwise(dedup)) < 0.2:
            continue
        view = _first(CHAIN_VIEWS[ax], enabled)
        if view is None:
            continue
        o = COORD[view][ax]
        for n, (a, b) in enumerate(itertools.pairwise(dedup)):
            dims.append(_dim(f"step-{ax}-{n}", "step", view, "h" if o == "u" else "v", a, b,
                             family=f"step-{ax}", order=3))

    # holes: callout in the view that looks along the axis, locations from the nearest edge
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for h in cen["holes"]:
        groups.setdefault((h["axis"], h["dia"], h["thru"], 0.0 if h["thru"] else h["depth"]), []).append(h)
    for gi, ((ax, dia, thru, depth), hs) in enumerate(sorted(groups.items(), key=lambda kv: (kv[0][0], -kv[0][1], kv[0][2], kv[0][3]))):
        view = CIRCLE_VIEW[ax]
        if view not in enabled:
            notes.append(f"{len(hs)}× Ø{fmt(dia)} hole(s) along {ax.upper()} not called out: the {view} view is off.")
            continue
        others = [a for a in ("x", "y", "z") if a != ax]
        cmap = COORD[view]
        pts = []
        for h in hs:
            p = {others[0]: h["centre"][0], others[1]: h["centre"][1]}
            pts.append((p[next(a for a in others if cmap[a] == "u")], p[next(a for a in others if cmap[a] == "v")]))
        pts.sort()
        callout = {"id": f"hole-{gi}", "view": view, "axis": ax, "holes": [[u, v, dia / 2] for u, v in pts],
                   "qty": len(hs), "dia": dia, "thru": thru, "depth": depth, "lines": [], "pcd": None}
        qty = f"{len(hs)}X " if len(hs) > 1 else ""
        callout["lines"].append({"text": f"{qty}Ø{fmt(dia)} " + ("THRU" if thru else f"DEEP {fmt(depth)}"),
                                 "kind": "hole", "value": dia, "depth": None if thru else depth,
                                 "tag": "inferred", "param": None})
        # circular pattern?
        pcd = None
        grid = len({round(p[0], 6) for p in pts}) <= 2 and len({round(p[1], 6) for p in pts}) <= 2
        if len(pts) >= 3 and not grid:  # a rectangular grid of holes is located by edge distances instead
            cu = sum(p[0] for p in pts) / len(pts)
            cv = sum(p[1] for p in pts) / len(pts)
            rads = [math.hypot(p[0] - cu, p[1] - cv) for p in pts]
            if min(rads) > TOL and max(rads) - min(rads) < 1e-6:
                angs = sorted(math.atan2(p[1] - cv, p[0] - cu) for p in pts)
                gaps = [b - a for a, b in itertools.pairwise(angs)] + [angs[0] + 2 * math.pi - angs[-1]]
                eq = max(gaps) - min(gaps) < 1e-6
                pcd = (round(cu, 6), round(cv, 6), round(rads[0], 6))
                callout["pcd"] = list(pcd)
                callout["lines"].append({"text": ("EQ SP ON " if eq else "ON ") + f"PCD Ø{fmt(2 * rads[0])}",
                                         "kind": "pcd", "value": round(2 * rads[0], 6), "tag": "inferred",
                                         "param": None})
        callouts.append(callout)
        # hole locations: chain from the nearest edge, unless the holes sit on the part's centre line
        for axis_name in others:
            o = cmap[axis_name]
            idx = 0 if o == "u" else 1
            if pcd is not None:
                coords = sorted({round(pcd[idx], 6)})
                ext = {coords[0]: [pcd[1 - idx], pcd[1 - idx]]}
            else:
                coords = sorted({round(p[idx], 6) for p in pts})
                ext = {c: _side_span([p[1 - idx] for p in pts if abs(p[idx] - c) < TOL]) for c in coords}
            mid = (lo[axis_name] + hi[axis_name]) / 2
            if len(coords) > 4 or all(abs(c - mid) < TOL for c in coords):
                continue
            if len(coords) == 2 and abs((coords[0] + coords[1]) / 2 - mid) < TOL and pcd is None:
                pass  # symmetric pair: still dimensioned from the edge (edge distance + spacing)
            d_lo, d_hi = coords[0] - lo[axis_name], hi[axis_name] - coords[-1]
            chain = [lo[axis_name], *coords] if d_lo <= d_hi + TOL else [*coords, hi[axis_name]]
            for n, (a, b) in enumerate(itertools.pairwise(chain)):
                ea = ext.get(a)
                eb = ext.get(b)
                dims.append(_dim(f"pos-{gi}-{axis_name}-{n}", "position", view, "h" if o == "u" else "v", a, b,
                                 ext_a=ea, ext_b=eb, family=f"pos-{gi}-{axis_name}", order=2))
    if cen.get("unsupported_holes"):
        notes.append(f"{cen['unsupported_holes']} hole(s) not on a principal axis or fully internal: not called out.")
    return _dedupe(dims), callouts, notes


def _dedupe(dims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ISO 129-1: a measurement is dimensioned once (keep the first, most meaningful one)."""
    out, seen = [], set()
    for d in dims:
        k = (d["view"], d["orient"], round(d["a"], 6), round(d["b"], 6))
        if k in seen:
            continue
        seen.add(k)
        out.append(d)
    return out


def _numeric_params(params: dict[str, Any]) -> dict[str, float]:
    out = {}
    for k, v in (params or {}).items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
            continue
        out[str(k)] = float(v)
    return out


def tag(dims: list[dict[str, Any]], callouts: list[dict[str, Any]], params: dict[str, Any],
        meta: dict[str, Any]) -> dict[str, Any]:
    """Choose auxiliary chain segments, then tag every value spec / inferred. Returns the parameter mapping."""
    nump = _numeric_params(params)
    kinds = {p: param_kind(p, (meta or {}).get(p)) for p in nump}

    def matches(kind: str, value: float) -> list[str]:
        ok = COMPATIBLE.get(kind, set())
        return sorted(p for p, v in nump.items() if kinds[p] in ok and abs(v - value) <= TOL * max(1.0, v))

    # items = (record, kind, value, family)
    items: list[tuple[dict[str, Any], str, float, str]] = [(d, d["kind"], d["value"], d["family"]) for d in dims]
    for c in callouts:
        for ln in c["lines"]:
            items.append((ln, ln["kind"], ln["value"], f"{ln['kind']}-callout-{c['id']}"))

    # auxiliary segment per chain (pass 1 ignores aux)
    fam_of: dict[str, list[dict[str, Any]]] = {}
    for d in dims:
        if d["kind"] == "step":
            fam_of.setdefault(d["family"], []).append(d)

    def unique(d: dict[str, Any], pool: list[dict[str, Any]]) -> bool:
        m = matches(d["kind"], d["value"])
        if len(m) != 1:
            return False
        same = [x for x in pool if x is not d and abs(x["value"] - d["value"]) < TOL]
        return not same

    for fam, segs in sorted(fam_of.items()):
        none = [s for s in segs if not matches(s["kind"], s["value"])]
        amb = [s for s in segs if s not in none and not unique(s, segs)]
        if none:
            none[0]["aux"] = True
        elif amb:
            amb[0]["aux"] = True
        else:
            ax = fam.split("-")[1]
            overall = next((d for d in dims if d["id"] == f"ext-{ax}"), None)
            if overall is not None and not matches("extent", overall["value"]):
                overall["aux"] = True
            else:
                segs[-1]["aux"] = True

    # pass 2: tag (aux dimensions are references: never spec)
    by_param_family: dict[tuple[str, str], int] = {}
    cand: dict[int, str] = {}
    for rec, kind, value, fam in items:
        if rec.get("aux"):
            continue
        m = matches(kind, value)
        if rec.get("depth") is not None and len(matches("depth", rec["depth"])) != 1:
            continue  # a blind-hole callout is spec only if its depth maps as well
        if len(m) == 1:
            cand[id(rec)] = m[0]
            by_param_family[(m[0], fam)] = by_param_family.get((m[0], fam), 0) + 1
    mapped: dict[str, int] = {}
    for rec, _kind, _value, fam in items:
        p = cand.get(id(rec))
        if p is not None and by_param_family[(p, fam)] == 1:
            rec["tag"], rec["param"] = "spec", p
            mapped[p] = mapped.get(p, 0) + 1
    for rec, *_ in items:
        val = rec["value"]
        txt = (rec.get("prefix") or "") + fmt(val) if "lines" not in rec and "text" not in rec else None
        if txt is not None:
            rec["text"] = f"({txt})" if rec.get("aux") else txt
    unmapped = sorted(p for p in nump if p not in mapped)
    return {"mapped": {p: mapped[p] for p in sorted(mapped)}, "unmapped": unmapped, "kinds": kinds}
