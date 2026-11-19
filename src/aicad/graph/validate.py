"""Validation and repair of a design graph (pure, deterministic).

``issues(graph)`` lists what is wrong, each with a stable ``code``, a ``severity`` (``error`` blocks compiling,
``warning`` is shown) and a plain-words ``text``:

  duplicate_id, unknown_kind, unknown_connection, dangling, self_connection, wrong_side, wrong_via, unknown_param,
  out_of_range, missing_param, conflict, excluded, not_named, over_used, bore_too_large, outside_table, unconnected

``repair(graph)`` fixes what code can fix without guessing: drops components the brief excludes (or, for an
exclusive brief, doesn't name) with their connections, drops dangling connections and unknown parameters, reads an
unknown component kind from its name. It never invents a size and never removes the last designed part.
"""

from __future__ import annotations

from typing import Any

from aicad.graph import registry, standards
from aicad.graph.model import Component, DesignGraph

CODES = ("duplicate_id", "unknown_kind", "unknown_connection", "dangling", "self_connection", "wrong_side",
         "wrong_via", "unknown_param", "out_of_range", "missing_param", "conflict", "excluded", "not_named",
         "over_used", "bore_too_large", "outside_table", "unconnected")

# values code derives and keeps on components (not in the registry's input parameters)
_DERIVED = {"key": {"b", "h", "t1", "t2"}, "bearing": {"d", "D", "B"}, "retaining_ring": {"d2", "m", "s"}}


def _issue(code: str, text: str, *, severity: str = "error", items: list[str] | None = None) -> dict[str, Any]:
    return {"code": code, "severity": severity, "text": text, "items": items or []}


def _scope_kind(c: Component) -> str | None:
    ct = registry.component(c.kind)
    return ct.scope if ct else None


def _out_of_scope(g: DesignGraph, c: Component) -> str | None:
    """'excluded' / 'not_named' when the brief rules this component out, else None. Implied parts of a kind the brief
    names (a key for "locked with a key") are in scope; fasteners of a housing the brief names are too."""
    k = _scope_kind(c)
    if k is None:
        return None
    if k in g.constraints.excluded:
        return "excluded"
    if g.constraints.exclusive and g.constraints.named and k not in g.constraints.named and not _said(c.name, g.brief):
        return "not_named"
    return None


def _said(name: str, brief: str) -> bool:
    """The brief names this part in its own words ("two guide rods" for a "Guide rod"), though not in a scope word."""
    import re

    n = re.sub(r"\s+", " ", (name or "").strip().lower())
    return bool(n) and re.search(r"(?<![a-z])" + re.escape(n) + r"(?:e?s)?(?![a-z])", (brief or "").lower()) is not None


def issues(g: DesignGraph) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in g.components:
        if c.id in seen:
            out.append(_issue("duplicate_id", f"Two components are called {c.id}.", items=[c.id]))
        seen.add(c.id)
        ct = registry.component(c.kind)
        if ct is None:
            out.append(_issue("unknown_kind", f"{c.name}: unknown kind of part '{c.kind}'.", items=[c.id]))
            continue
        for name, p in c.params.items():
            spec = ct.params.get(name)
            if spec is None:
                if name not in _DERIVED.get(c.kind, set()):
                    out.append(_issue("unknown_param", f"{c.name}: '{name}' is not a parameter of a {ct.label.lower()}.",
                                      severity="warning", items=[c.id]))
                continue
            v = p.value
            if spec.choices and v not in spec.choices:
                out.append(_issue("out_of_range", f"{c.name}: {name} {v} is not one of "
                                  f"{', '.join(str(x) for x in spec.choices)}.", items=[c.id]))
            elif isinstance(v, int | float) and not isinstance(v, bool):
                if (spec.lo is not None and v < spec.lo) or (spec.hi is not None and v > spec.hi):
                    out.append(_issue("out_of_range", f"{c.name}: {name} {v:g} is outside {spec.lo:g} .. {spec.hi:g}.",
                                      items=[c.id]))
                if spec.integer and float(v) != int(v):
                    out.append(_issue("out_of_range", f"{c.name}: {name} must be a whole number.", items=[c.id]))
        for name in ct.required:
            if c.v(name) is None:
                out.append(_issue("missing_param", f"{c.name}: needs its {ct.params[name].label or name}.",
                                  items=[c.id]))
        why = _out_of_scope(g, c)
        if why == "excluded":
            out.append(_issue("excluded", f"{c.name}: the brief excludes a {_scope_kind(c)}.", items=[c.id]))
        elif why == "not_named":
            out.append(_issue("not_named", f"{c.name}: the brief limits the design to what it names.", items=[c.id]))

    ids = {c.id for c in g.components}
    used: dict[str, int] = {}
    for x in g.connections:
        kt = registry.connection(x.kind)
        if kt is None:
            out.append(_issue("unknown_connection", f"Unknown kind of connection '{x.kind}'.", items=[x.id]))
            continue
        missing = [i for i in (x.host, x.guest, *x.via) if i not in ids]
        if missing:
            out.append(_issue("dangling", f"{kt.label.capitalize()} {x.id} names "
                              f"{', '.join(missing)}, which is not in the design.", items=[x.id]))
            continue
        if x.host == x.guest:
            out.append(_issue("self_connection", f"{kt.label.capitalize()} {x.id} connects a part to itself.",
                              items=[x.id]))
        h, gst = g.comp(x.host), g.comp(x.guest)
        assert h is not None and gst is not None
        if h.kind not in kt.hosts or gst.kind not in kt.guests:
            out.append(_issue("wrong_side", f"A {kt.label} needs a {'/'.join(kt.hosts[:4])} as host and a "
                              f"{'/'.join(kt.guests[:4])} on it (got {h.name} and {gst.name}).", items=[x.id]))
        for v in x.via:
            vc = g.comp(v)
            if vc is not None and kt.via and vc.kind not in kt.via:
                out.append(_issue("wrong_via", f"{vc.name} can't make a {kt.label}.", items=[x.id, v]))
        n = int(x.v("count", 1) or 1)
        used[x.guest] = used.get(x.guest, 0) + (n if x.kind in ("bearing_journal", "bearing_seat") else 0)
        out += _conflicts(g, x, h, gst)
    for cid, n in used.items():
        c = g.comp(cid)
        if c is not None and c.kind == "bearing" and n > c.qty and not _has_seat_and_journal(g, cid):
            out.append(_issue("over_used", f"{c.name}: {n} journals but only {c.qty} bearings.", items=[cid]))
    linked = {i for x in g.connections for i in (x.host, x.guest, *x.via)}
    if len(g.components) > 1:
        for c in g.components:
            if c.id not in linked and c.kind not in ("fastener", "nut", "washer", "dowel", "seal", "other"):
                out.append(_issue("unconnected", f"{c.name} is not connected to anything.", severity="warning",
                                  items=[c.id]))
    return out


def _has_seat_and_journal(g: DesignGraph, cid: str) -> bool:
    kinds = {x.kind for x in g.connections if x.guest == cid}
    return {"bearing_journal", "bearing_seat"} <= kinds


def _conflicts(g: DesignGraph, x: Any, h: Component, gst: Component) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if x.kind in ("keyed_hub", "hub_fit") and h.kind == "shaft":
        d, bore = h.v("d"), gst.v("bore")
        if d is not None and bore is not None and abs(float(d) - float(bore)) > 1e-6:
            out.append(_issue("conflict", f"{gst.name} is bored Ø{float(bore):g} but its seat on {h.name} is "
                              f"Ø{float(d):g}.", items=[x.id]))
        if gst.kind == "spur_gear" and bore is not None and gst.v("module") and gst.v("teeth"):
            t2 = 0.0
            if x.kind == "keyed_hub":
                try:
                    t2 = standards.key_for_shaft(float(bore))["t2"]
                except ValueError:
                    t2 = 0.0
            if not standards.bore_fits_gear(float(gst.v("module")), int(gst.v("teeth")), float(bore), t2):
                g_ = standards.gear_geometry(float(gst.v("module")), int(gst.v("teeth")))
                out.append(_issue("bore_too_large", f"{gst.name} (m{float(gst.v('module')):g} x {int(gst.v('teeth'))}) "
                                  f"can't take a Ø{float(bore):g} bore{' with its keyway' if t2 else ''}: the rim "
                                  f"needs the bore below Ø{g_['max_bore']:g}.", items=[x.id]))
        if x.kind == "keyed_hub" and d is not None:
            try:
                standards.key_for_shaft(float(d))
            except ValueError:
                out.append(_issue("outside_table", f"Ø{float(d):g} is outside the DIN 6885 key table (over 8 up to "
                                  "65 mm).", items=[x.id]))
    elif x.kind == "gear_mesh":
        ma, mb = h.v("module"), gst.v("module")
        if ma is not None and mb is not None and abs(float(ma) - float(mb)) > 1e-9:
            out.append(_issue("conflict", f"{h.name} (m{float(ma):g}) and {gst.name} (m{float(mb):g}) can't mesh: "
                              "meshing gears share their module.", items=[x.id]))
    elif x.kind == "bearing_journal":
        des, jd = gst.v("designation"), h.v("journal_d") or h.v("d")
        if des is not None and jd is not None:
            from aicad.toolbox import BEARING

            if int(des) in BEARING and abs(BEARING[int(des)][0] - float(jd)) > 1e-6 and \
                    gst.params.get("designation") and gst.params["designation"].source in ("brief", "answer") and \
                    h.params.get("d") and h.params["d"].source in ("brief", "answer") and h.v("journal_d") is None:
                out.append(_issue("conflict", f"{gst.name} has a Ø{BEARING[int(des)][0]:g} bore but {h.name} is "
                                  f"Ø{float(jd):g}.", items=[x.id]))
    elif x.kind == "shoulder_stop":
        d, sd = h.v("d"), h.v("shoulder_d")
        if d is not None and sd is not None and float(sd) <= float(d):
            out.append(_issue("conflict", f"{h.name}: the shoulder Ø{float(sd):g} must be larger than the seat "
                              f"Ø{float(d):g}.", items=[x.id]))
    return out


def errors(g: DesignGraph) -> list[dict[str, Any]]:
    return [i for i in issues(g) if i["severity"] == "error"]


def repair(graph: DesignGraph) -> DesignGraph:
    """What code can fix without guessing (see the module doc). Notes say what changed, in plain words."""
    g = graph.model_copy(deep=True)
    for c in g.components:
        if registry.component(c.kind) is None:
            k = registry.kind_from_name(c.name)
            g.notes.append(f"Read {c.name} as a {registry.COMPONENTS[k].label.lower()}.")
            c.kind = k
        ct = registry.COMPONENTS[c.kind]
        for name in list(c.params):
            if name not in ct.params and name not in _DERIVED.get(c.kind, set()):
                del c.params[name]
    dropped = [c for c in g.components if _out_of_scope(g, c) is not None]
    designed_left = [c for c in g.components if c not in dropped and registry.COMPONENTS[c.kind].family != "standard"]
    if dropped and designed_left:
        gone = {c.id for c in dropped}
        g.components = [c for c in g.components if c.id not in gone]
        g.connections = [x for x in g.connections if x.host not in gone and x.guest not in gone]
        for x in g.connections:
            x.via = [v for v in x.via if v not in gone]
        names = [c.name for c in dropped]
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        g.notes.append(f"The brief rules these out, so they are not in the design: {listed}.")
    ids = {c.id for c in g.components}
    keep = []
    for x in g.connections:
        if x.host in ids and x.guest in ids and x.host != x.guest:
            x.via = [v for v in x.via if v in ids]
            keep.append(x)
    g.connections = keep
    return g
