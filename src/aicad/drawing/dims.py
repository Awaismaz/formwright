"""Candidate dimensions and hole callouts from the exact census, tagged ``spec`` or ``inferred``.

Rules (deterministic, documented in docs/reports/drawings.md):
- Every value is measured from the model geometry. A dimension is tagged ``spec`` when its value equals a declared
  model parameter (``PARAMS``) of a compatible kind (diameter, length, position ...) and that match is
  unambiguous: no other compatible parameter has the same value, and the parameter does not match two
  dimensions of the same family (e.g. two segments of one chain). Otherwise it is ``inferred``.
- Each measurement is dimensioned once (ISO 129-1): overall extents, turned diameters, hole callouts with
  quantity / diameter / THRU or depth, hole locations from the nearest edge, step chains between planar levels,
  radius callouts for fillets and rounds ("4X R3") and chamfer callouts ("4X 1 × 45°") from the exact faces.
- Turned parts (drawn axis-horizontal): the axial chain runs between diameter steps only; a flat feature such as a
  keyway gets its own chain from the nearest shoulder; widths across the axis that are symmetric about it are
  dimensioned as one width (the centre line carries the symmetry), on the cross-section when there is one.
- A count parameter (N_BOLTS) is shown by the quantity of a callout ("6X") and counts as mapped.
- One segment of a chain is shown as an auxiliary (reference) dimension in parentheses so that a chain plus the
  overall size is not over-dimensioned.
- Cosmetic threads (CAD-027) are called out from the model's thread metadata, never guessed from a diameter: a
  tapped hole group reads "4X M6×1-6H ▽12" over its drill "Ø5 ▽15"; a threaded turned diameter prints its
  designation in place of the Ø; other threaded cylinders get a leader callout.
- Tolerances and GD&T are never generated here.
"""

from __future__ import annotations

import itertools
import math
import re
from typing import Any

from aicad.drawing.geometry import AXIS_INDEX, turned

#: Where each model axis appears in the principal views (U is paper-right, V is paper-up).
COORD = {"front": {"x": "u", "z": "v"}, "top": {"x": "u", "y": "v"}, "right": {"y": "u", "z": "v"}}
EXTENT_VIEWS = {"x": ["front", "top"], "y": ["top", "right"], "z": ["front", "right"]}
CHAIN_VIEWS = {"x": ["top", "front"], "y": ["top", "right"], "z": ["front", "right"]}
CIRCLE_VIEW = {"x": "right", "y": "front", "z": "top"}  # the view that looks along a hole axis
DIA_VIEWS = {"z": [("front", "x"), ("right", "y")], "x": [("front", "z"), ("top", "y")],
             "y": [("top", "x"), ("right", "z")]}
SECTION_LIKE_VIEW = {"x": "right", "y": "front", "z": "top"}
COMPATIBLE = {"extent": {"linear", "any"}, "step": {"linear", "any"}, "depth": {"linear", "any"},
              "diameter": {"dia", "any"}, "hole": {"dia", "any"}, "pcd": {"pcd", "any"},
              "position": {"position", "any"}, "radius": {"radius", "any"}, "chamfer": {"chamfer", "any"}}
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
    if {"chamfer", "ch", "bevel"} & toks:
        return "chamfer"
    if {"r", "rad", "radius", "fillet", "round", "corner"} & toks or any(re.fullmatch(r"r\d+", t) for t in toks):
        return "radius"
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
    return turned(cen)


def _uv(view: str, p: list[float], coord: dict[str, dict[str, str]]) -> tuple[float, float]:
    """A model point in a principal view's (U, V)."""
    cm = coord[view]
    u = next(p[AXIS_INDEX[a]] for a, c in cm.items() if c == "u")
    v = next(p[AXIS_INDEX[a]] for a, c in cm.items() if c == "v")
    return u, v


def candidates(cen: dict[str, Any], enabled: set[str], section: dict[str, Any] | None = None
               ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """All dimensions and callouts the sheet will show (before tagging and placement).

    ``section``: ``{"axis", "at"}`` of a cross-section drawn as its own view ("section"), which then carries the
    dimensions across a turned part's axis."""
    bb = cen["bbox"]
    lo = {a: bb[i] for a, i in AXIS_INDEX.items()}
    hi = {a: bb[i + 3] for a, i in AXIS_INDEX.items()}
    dims: list[dict[str, Any]] = []
    callouts: list[dict[str, Any]] = []
    notes: list[str] = []
    rev = _revolve(cen)
    coord = dict(COORD)
    if section:
        coord["section"] = COORD[SECTION_LIKE_VIEW[section["axis"]]]

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
                    dd = _dim(f"dia-{ax}-{len(seen)}", "diameter", view, "h" if o == "u" else "v",
                              c0 - r, c0 + r, prefix="Ø", family=f"dia-{ax}-{len(seen)}", order=1)
                    th = next((q["thread"] for q in cen["outer"] if q.get("thread") and q["axis"] == ax
                               and abs(q["dia"] - c["dia"]) < TOL
                               and all(abs(q["centre"][j] - centre[j]) < TOL for j in (0, 1))), None)
                    if th:
                        dd["thread"] = th
                    dims.append(dd)
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
        if rev and ax != rev[0]:
            dims += _across_turned(cen, rev, ax, enabled, coord, section)
            continue
        levels = [v for v in cen["levels"][ax] if lo[ax] - TOL <= v <= hi[ax] + TOL]
        feat: list[float] = []
        if rev:  # turned: the chain runs between diameter steps; other levels belong to flat features
            steps = {lo[ax], hi[ax]} | {t for c in cen["outer"] if c["axis"] == ax for t in (c["t0"], c["t1"])}
            feat = sorted(v for v in levels if all(abs(v - q) > TOL for q in steps))
            levels = sorted(steps)
        dedup = _dedup_levels(sorted(set(levels) | {lo[ax], hi[ax]}))
        view = _first(CHAIN_VIEWS[ax], enabled)
        if view is None:
            continue
        o = COORD[view][ax]
        if 3 <= len(dedup) <= 7 and min(b - a for a, b in itertools.pairwise(dedup)) >= 0.2:
            for n, (a, b) in enumerate(itertools.pairwise(dedup)):
                dims.append(_dim(f"step-{ax}-{n}", "step", view, "h" if o == "u" else "v", a, b,
                                 family=f"step-{ax}", order=3))
        if feat:  # a keyway or flat: located from the nearest shoulder, then its length
            below = [q for q in dedup if q <= feat[0] + TOL]
            above = [q for q in dedup if q >= feat[-1] - TOL]
            if below and (not above or feat[0] - below[-1] <= above[0] - feat[-1] + TOL):
                chain = _dedup_levels([below[-1], *feat[:5]])
            else:
                chain = _dedup_levels([*feat[:5], above[0]])
            for n, (a, b) in enumerate(itertools.pairwise(chain)):
                dims.append(_dim(f"feat-{ax}-{n}", "step", view, "h" if o == "u" else "v", a, b,
                                 family=f"feat-{ax}", order=4))

    # holes: callout in the view that looks along the axis, locations from the nearest edge
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for h in cen["holes"]:
        t = h.get("thread")
        tkey = f"{t['designation']}|{t['depth']}" if t else ""
        groups.setdefault((h["axis"], h["dia"], h["thru"], 0.0 if h["thru"] else h["depth"], tkey), []).append(h)
    for gi, ((ax, dia, thru, depth, tkey), hs) in enumerate(sorted(groups.items(), key=lambda kv: (kv[0][0], -kv[0][1], kv[0][2], kv[0][3], kv[0][4]))):
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
        callout = {"id": f"hole-{gi}", "type": "hole", "view": view, "axis": ax,
                   "holes": [[u, v, dia / 2] for u, v in pts],
                   "qty": len(hs), "dia": dia, "thru": thru, "depth": depth, "lines": [], "pcd": None}
        qty = f"{len(hs)}X " if len(hs) > 1 else ""
        if tkey:  # cosmetic thread: the designation (declared in the hole feature) over its drill
            from aicad import threads as _th

            t = hs[0]["thread"]
            callout["thread"] = t
            full = None if t["depth"] is not None or thru else depth
            callout["lines"].append({"text": _th.callout({**t, "thru": thru}, len(hs), full), "kind": "thread",
                                     "value": t["major"], "tag": "spec", "param": None, "source": "thread"})
            callout["lines"].append({"text": f"Ø{fmt(dia)} " + ("THRU" if thru else f"▽{fmt(depth)}"),
                                     "kind": "hole", "value": dia, "depth": None if thru else depth,
                                     "tag": "inferred", "param": None})
        else:
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
    callouts += _radius_callouts(cen, enabled, coord)
    callouts += _chamfer_callouts(cen, enabled, coord)
    callouts += _thread_callouts(cen, enabled, coord, {id(d.get("thread")) for d in dims if d.get("thread")})
    if cen.get("unsupported_holes"):
        notes.append(f"{cen['unsupported_holes']} hole(s) not on a principal axis or fully internal: not called out.")
    return _dedupe(dims), callouts, notes


def _thread_callouts(cen: dict[str, Any], enabled: set[str], coord: dict[str, dict[str, str]], on_dims: set[int]
                     ) -> list[dict[str, Any]]:
    """External cosmetic threads not already printed on a turned diameter: a leader callout on the cylinder seen
    end-on ("M10×1.5-6g")."""
    from aicad import threads as _th

    out = []
    for n, c in enumerate(q for q in cen["outer"] if q.get("thread") and id(q["thread"]) not in on_dims):
        view = CIRCLE_VIEW[c["axis"]]
        if view not in enabled:
            continue
        i = AXIS_INDEX[c["axis"]]
        others = [j for j in range(3) if j != i]
        p3 = [0.0, 0.0, 0.0]
        p3[others[0]], p3[others[1]] = c["centre"][0], c["centre"][1]
        p3[i] = c["thread"]["start"]
        u, v = _uv(view, p3, coord)
        r = c["dia"] / 2
        t = c["thread"]
        out.append({"id": f"thd-{n}", "type": "thread", "view": view, "axis": c["axis"],
                    "holes": [[u, v, r]], "tip": [u + r * 0.7071, v + r * 0.7071], "qty": 1, "dia": c["dia"],
                    "thru": None, "depth": None, "pcd": None, "thread": t,
                    "lines": [{"text": _th.callout(t), "kind": "thread", "value": t["major"], "depth": None,
                               "tag": "spec", "param": None, "source": "thread"}]})
    return out


def thread_lines(cen: dict[str, Any], enabled: set[str], callouts: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """ISO 6410-1 marks for external threads in the principal views: ("view", "side", orient, across, t0, t1, root
    radius, crest radius when the thread stops short) along the cylinder, and ("view", "end", u, v, root radius)
    end-on where no thread callout already draws it."""
    out: list[tuple[Any, ...]] = []
    called = {id(c.get("thread")) for c in callouts if c.get("type") == "thread"}
    for c in cen["outer"]:
        t = c.get("thread")
        if not t:
            continue
        ax = c["axis"]
        i = AXIS_INDEX[ax]
        others = [a for a in ("x", "y", "z") if a != ax]
        start, sign = t["start"], t["sign"]
        full = (c["t1"] - start) if sign > 0 else (start - c["t0"])
        length = full if t.get("depth") is None else min(float(t["depth"]), full)
        end = start + sign * length
        crest = t["major"] / 2 if length < full - 1e-6 else None
        for view in ("front", "top", "right"):
            if view not in enabled or ax not in COORD[view]:
                continue
            o = COORD[view][ax]
            b = next(a for a in COORD[view] if a != ax)
            across = c["centre"][others.index(b)]
            out.append((view, "side", "h" if o == "u" else "v", across, start, end, t["minor"] / 2, crest))
        view = CIRCLE_VIEW[ax]
        if view in enabled and id(t) not in called:
            p3 = [0.0, 0.0, 0.0]
            j = [k for k in range(3) if k != i]
            p3[j[0]], p3[j[1]] = c["centre"][0], c["centre"][1]
            u, v = _uv(view, p3, COORD)
            out.append((view, "end", u, v, t["minor"] / 2))
    return out


def _dedup_levels(vals: list[float]) -> list[float]:
    out: list[float] = []
    for v in vals:
        if not out or v - out[-1] > TOL:
            out.append(v)
    return out


def _across_turned(cen: dict[str, Any], rev: tuple[str, list[float], float], ax: str, enabled: set[str],
                   coord: dict[str, dict[str, str]], section: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flat features across a turned part's axis (keyway floor, keyway width), on the cross-section if drawn."""
    levels = cen["levels"][ax]
    if not levels:
        return []
    axis, centre, env = rev
    k = [a for a in ("x", "y", "z") if a != axis].index(ax)
    c0 = centre[k]
    r = env / 2
    if section and section.get("at") is not None:  # the outside diameter at the cut
        at = section["at"]
        cyl = [c for c in cen["outer"] if c["axis"] == axis and c["t0"] - TOL <= at <= c["t1"] + TOL]
        if cyl:
            r = max(c["dia"] for c in cyl) / 2
    if section and "section" in enabled:
        view = "section"
    else:
        view = next((v for v in ("right", "front", "top") if v in enabled and ax in coord[v]), None)
    if view is None or ax not in coord[view]:
        return []
    o = "h" if coord[view][ax] == "u" else "v"
    offs = [v - c0 for v in levels if abs(v - c0) < r - TOL]
    sym = [q for q in offs if q > TOL and any(abs(q + w) < TOL for w in offs)]
    out = []
    if sym and len(sym) * 2 == len(offs):  # widths symmetric about the axis: one dimension per width
        for n, q in enumerate(sorted(sym)):
            out.append(_dim(f"w-{ax}-{n}", "step", view, o, c0 - q, c0 + q, family=f"w-{ax}-{n}", order=3))
        return out
    vals = _dedup_levels(sorted({c0 - r, c0 + r, *(c0 + q for q in offs)}))
    if 3 <= len(vals) <= 6:
        for n, (a, b) in enumerate(itertools.pairwise(vals)):
            out.append(_dim(f"step-{ax}-{n}", "step", view, o, a, b, family=f"step-{ax}", order=3))
    return out


def _radius_callouts(cen: dict[str, Any], enabled: set[str], coord: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Fillets and rounds on principal axes: "4X R3" with a leader to one arc, in the view looking along the axis."""
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for a in cen.get("arcs", []):
        groups.setdefault((a["axis"], a["r"], a["concave"]), []).append(a)
    out = []
    for gi, ((ax, r, _concave), arcs) in enumerate(sorted(groups.items(), key=lambda kv: (kv[0][0], -kv[0][1], not kv[0][2]))):
        view = CIRCLE_VIEW[ax]
        if view not in enabled:
            continue
        pts = sorted((_uv(view, a["mid"], coord) for a in arcs), key=lambda p: (-p[1], -p[0]))
        qty = len({(round(a["centre"][0], 4), round(a["centre"][1], 4)) for a in arcs})
        text = (f"{qty}X " if qty > 1 else "") + f"R{fmt(r)}"
        out.append({"id": f"rad-{gi}", "type": "radius", "view": view, "axis": ax, "holes": [], "tip": list(pts[0]),
                    "tips": [list(q) for q in pts],
                    "qty": qty, "dia": None, "thru": None, "depth": None, "pcd": None,
                    "lines": [{"text": text, "kind": "radius", "value": r, "depth": None, "tag": "inferred",
                               "param": None}]})
    return out


def _chamfer_callouts(cen: dict[str, Any], enabled: set[str], coord: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Flat edge chamfers: "4X 1 × 45°" with a leader to a chamfer seen edge-on (along its edge)."""
    groups: dict[tuple[float, ...], list[dict[str, Any]]] = {}
    for c in cen.get("chamfers", []):
        groups.setdefault(tuple(sorted(c["legs"])), []).append(c)
    out = []
    for gi, (legs, chs) in enumerate(sorted(groups.items())):
        rep_ = None
        for view in ("front", "right", "top"):
            if view not in enabled:
                continue
            ok = [c for c in chs if CIRCLE_VIEW[c["edge"]] == view]
            if ok:
                rep_ = (view, min((_uv(view, c["mid"], coord) for c in ok), key=lambda p: (-p[1], -p[0])))
                break
        if rep_ is None:
            continue
        view, tip = rep_
        qty = len(chs)
        a, b = legs
        size = f"{fmt(a)} × 45°" if abs(a - b) < 1e-6 else f"{fmt(a)} × {fmt(b)}"
        out.append({"id": f"chf-{gi}", "type": "chamfer", "view": view, "axis": None, "holes": [], "tip": list(tip),
                    "qty": qty, "dia": None, "thru": None, "depth": None, "pcd": None,
                    "lines": [{"text": (f"{qty}X " if qty > 1 else "") + size, "kind": "chamfer", "value": a,
                               "depth": None, "tag": "inferred", "param": None}]})
    return out


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

    # auxiliary segment per chain that adds up to an overall size (pass 1 ignores aux). A feature's location chain
    # (keyway from the shoulder) and a symmetric width are not closed by an overall size: every value is needed.
    fam_of: dict[str, list[dict[str, Any]]] = {}
    for d in dims:
        if d["kind"] == "step" and d["family"].startswith("step-"):
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
    # a count parameter is shown by a callout's quantity ("6X Ø14 THRU" carries N_BOLTS = 6)
    for p, v in sorted(nump.items()):
        if kinds[p] != "count" or p in mapped or not float(v).is_integer():
            continue
        hits = [c for c in callouts if c.get("type", "hole") == "hole" and c["qty"] == int(v) and c["qty"] > 1]
        if len(hits) == 1:
            hits[0]["lines"][0].setdefault("params", []).append(p)
            hits[0]["count_param"] = p
            mapped[p] = mapped.get(p, 0) + 1
    unmapped = sorted(p for p in nump if p not in mapped)
    return {"mapped": {p: mapped[p] for p in sorted(mapped)}, "unmapped": unmapped, "kinds": kinds}
