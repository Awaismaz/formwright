"""Compilers from the design graph to what runs today (so the current office runs unchanged on a graph).

* ``to_plan(graph)``: the Design Office plan (``planner.normalise_plan`` format). Each part's description is written
  from the graph's numbers in the phrases the layout reader (``office/icd.py``) and the direct builder
  (``office/direct.py``) are tested on, with the layout hints (envelope, module, teeth, mounts_on). ICD overrides for
  values the description can't carry (a gear face width other than 10 m) go in ``plan["graph"]["icd_overrides"]``,
  keyed by part name, and are applied when the ICD is drafted.
* ``to_icd(graph)``: (skeleton, interfaces) solved from the connections (``graph/layout.py``), exactly as the
  office does at plan approval (the template ``icd.build`` is the fallback).
* ``check(graph, skeleton, interfaces)``: the cross-check. Every connection must come out as the interface it means,
  with the numbers the graph sized (centre distance, key size, bearing, seat and shoulder Ø), nothing the brief
  excludes may appear, and every component must be placed or listed. Mismatches are returned in plain words.
* ``to_direct(graph)``: the direct builder's decision per designed component (``direct.plan`` on the compiled ICD):
  which parts build with no AI, and the model script for each.
* ``to_fitz_items(graph)``: the items Fitz's shaft lines / gear trains (``assembly/trains.py``) assemble, where the
  graph is a housing-less train of Toolbox parts; other components are listed as not applicable.
* ``read_layout(graph, skeleton)``: the solved positions read back into the graph (``graph.layout``).
"""

from __future__ import annotations

import math
import re
from typing import Any

from aicad.graph import registry, standards
from aicad.graph.model import Component, DesignGraph
from aicad.graph.resolve import resolve

PLAN_SOURCE = "archie"   # the office shows graph plans as Archie's (AI at the edge, code in the middle)


def _f(x: Any) -> str:
    return f"{float(x):g}"


# ----------------------------------------------------------------------------- groups (sub-assemblies)
def _riders(g: DesignGraph, shaft: str) -> list[str]:
    out: list[str] = []
    for x in g.connections:
        if x.host == shaft and x.kind in ("keyed_hub", "hub_fit", "bearing_journal", "shoulder_stop", "ring_retained"):
            for i in (x.guest, *x.via):
                if i not in out:
                    out.append(i)
    return out


def groups(g: DesignGraph) -> list[tuple[str, list[Component]]]:
    """Sub-assemblies in plan order. The graph's own groups when every component has one; else: with a housing, a
    "Housing" group (housing, cover, caps, their fasteners) and one group per shaft with what rides on it; without, one
    group (a shaft and what it carries is one unit to assemble, PD-93)."""
    if g.components and all(c.group for c in g.components):
        order: list[str] = []
        for c in g.components:
            if c.group not in order:
                order.append(c.group)
        return [(n, [c for c in g.components if c.group == n]) for n in order]
    shafts = g.of_kind("shaft")
    if g.of_kind("housing") and shafts:
        taken: set[str] = set()
        out: list[tuple[str, list[Component]]] = []
        for sh in shafts:
            ids = [sh.id] + [i for i in _riders(g, sh.id) if i not in taken]
            taken |= set(ids)
            out.append((f"{sh.name} group", [c for c in g.components if c.id in ids]))
        rest = [c for c in g.components if c.id not in taken]
        return [("Housing", rest)] + out if rest else out
    name = g.name if g.name and len(g.name) <= 40 else "Assembly"
    return [(name, list(g.components))]


# ----------------------------------------------------------------------------- one plan part per component
def _hub_on(g: DesignGraph, cid: str) -> Component | None:
    for x in g.connections:
        if x.guest == cid and x.kind in ("keyed_hub", "hub_fit"):
            return g.comp(x.host)
    return None


def _keyed(g: DesignGraph, cid: str) -> bool:
    return any(x.guest == cid and x.kind == "keyed_hub" for x in g.connections)


def _joint_role(g: DesignGraph, cid: str) -> str | None:
    """'caps' when a fastener holds bearing caps, 'cover' when it holds a cover, else None."""
    for x in g.connections:
        if x.kind == "bolted_joint" and cid in x.via:
            gk = (g.comp(x.guest) or Component(id="", kind="", name="")).kind
            return "caps" if gk == "bearing_cap" else "cover" if gk == "cover" else None
    return None


def _material(c: Component) -> str:
    return f"{c.material} " if c.material else "Steel "


def part(g: DesignGraph, c: Component) -> dict[str, Any]:
    ct = registry.COMPONENTS[c.kind]
    p: dict[str, Any] = {"name": c.name, "family": ct.family, "complexity": ct.complexity, "qty": c.qty}
    k = c.kind
    if k == "shaft":
        d, L = float(c.v("d")), c.v("length")
        riders = [g.comp(x.guest) for x in g.connections if x.host == c.id and x.kind in ("keyed_hub", "hub_fit")]
        what = "gear" if any(r is not None and r.kind == "spur_gear" for r in riders) else "hub"
        keyed = any(x.host == c.id and x.kind == "keyed_hub" for x in g.connections)
        if c.v("stepped") is True and not g.of_kind("housing"):
            D = float(c.v("shoulder_d"))
            p["description"] = (f"{_material(c)}stepped shaft with {_f(d)} mm k6 {what} seat and {_f(D)} mm larger "
                                f"step forming the {what} shoulder" + (f", overall length {_f(L)} mm" if L else "")
                                + ("; DIN 6885 keyseat in the seat." if keyed else "."))
            if L:
                p["envelope"] = [D, D, float(L)]
        else:
            p["description"] = (f"{_material(c)}shaft Ø{_f(d)}" + (f" x {_f(L)}" if L else "")
                                + (", with a DIN 6885 keyseat for its " + what + "." if keyed else "."))
            if L:
                p["envelope"] = [d, d, float(L)]
    elif k == "spur_gear":
        m, z, b = float(c.v("module")), int(c.v("teeth")), float(c.v("face_width"))
        bore = c.v("bore")
        p.update(module=m, teeth=z)
        tip = m * (z + 2)
        p["envelope"] = [tip, tip, b]
        p["description"] = (f"{_material(c)}spur gear, module {_f(m)}, {z} teeth, {_f(b)} mm face width"
                            + (f", {_f(bore)} mm H7 bore" if bore else "")
                            + (" with a keyway per DIN 6885." if _keyed(g, c.id) else "."))
        host = _hub_on(g, c.id)
        if host is not None:
            p["mounts_on"] = host.name
    elif k in ("pulley", "hub", "spacer"):
        od, w, bore = c.v("od"), c.v("width") or c.v("length"), c.v("bore")
        p["description"] = (f"{ct.label} {('Ø' + _f(od)) if od else ''}{(' x ' + _f(w)) if od and w else ''}"
                            + (f", {_f(bore)} mm H7 bore" if bore else "") + ".").replace("  ", " ")
        if od and w:
            p["envelope"] = [float(od), float(od), float(w)]
        host = _hub_on(g, c.id)
        if host is not None:
            p["mounts_on"] = host.name
    elif k == "key":
        b, h, L = c.v("b"), c.v("h"), c.v("length")
        x = next((x for x in g.connections if c.id in x.via), None)
        hub, sh = (g.comp(x.guest), g.comp(x.host)) if x else (None, None)
        size = f" {_f(b)} x {_f(h)}" + (f" x {_f(L)}" if L else "") + " mm" if b and h else ""
        p["description"] = (f"Parallel key DIN 6885 form A{size}, locks the {hub.name if hub else 'hub'} to the "
                            f"{sh.name if sh else 'shaft'}.")
    elif k == "bearing":
        des = c.v("designation")
        p["description"] = (f"{des} deep-groove ball bearing" + (f", {_f(c.v('d'))} x {_f(c.v('D'))} x {_f(c.v('B'))}"
                                                                 if c.v("D") else "") + "." if des else
                            "Deep-groove ball bearing sized to its journal.")
        p["toolbox"] = "bearing"
    elif k == "retaining_ring":
        p["description"] = f"DIN 471 retaining ring for a Ø{_f(c.v('shaft_d'))} shaft." if c.v("shaft_d") else \
            "DIN 471 retaining ring sized to the shaft."
    elif k == "housing":
        p["description"] = ("Lower half of the split housing: mounting feet, the bearing bores for every shaft and the "
                            "flange the cover bolts to." if c.v("style", "split") == "split" else
                            "Housing block carrying the bearing bores.")
        if c.v("L") and c.v("W") and c.v("H"):
            p["envelope"] = [float(c.v("L")), float(c.v("W")), float(c.v("H"))]
    elif k == "cover":
        p["description"] = "Upper half of the split housing (the cover), bolted to the base."
        hs = next((h for h in g.of_kind("housing")), None)
        if hs is not None:
            p["mounts_on"] = hs.name
    elif k == "bearing_cap":
        style = c.v("style") or ("open" if re.search(r"\bopen\b", c.name, re.IGNORECASE) else "blind")
        p["description"] = (f"{'Open' if style == 'open' else 'Blind'} flanged bearing cap"
                            + (": the shaft passes through it." if style == "open" else ": it closes the bore."))
        hs = next((h for h in g.of_kind("housing")), None)
        if hs is not None:
            p["mounts_on"] = hs.name
    elif k == "fastener":
        size, L = c.v("size"), c.v("length")
        st = "Socket head cap screw" if c.v("style") == "shcs" else "Hex bolt"
        dims = (f" M{int(size)}" + (f"x{_f(L)}" if L else "")) if size else ""
        role = _joint_role(g, c.id)
        p["description"] = (f"{st}{dims} that fixes the bearing caps." if role == "caps" else
                            f"{st}{dims} joining the cover to the base." if role == "cover" else f"{st}{dims}.")
        p["toolbox"] = "shcs" if c.v("style") == "shcs" else "hex_bolt"
    elif k in ("nut", "washer"):
        p["description"] = f"{ct.label}" + (f" M{int(c.v('size'))}" if c.v("size") else "") + "."
        p["toolbox"] = "hex_nut" if k == "nut" else "washer"
    elif k == "dowel":
        p["description"] = "Dowel pin" + (f" {_f(c.v('d'))} x {_f(c.v('length'))}" if c.v("d") and c.v("length")
                                          else "") + "."
        p["toolbox"] = "dowel"
    elif k == "pillow_block":
        p["description"] = ("Pillow block: carries one bearing of its shaft, bolted to the base plate; sized by the "
                             "layout from its bearing and the shaft height.")
    elif k == "motor":
        dims = [c.v(n) for n in ("L", "W", "H")]
        p["description"] = ("Bought-out electric motor (envelope only, replace with the maker's dimensions)"
                            + (f": body {' x '.join(_f(x) for x in dims)} mm" if all(dims) else "")
                            + (f", shaft Ø{_f(c.v('shaft_d'))}" if c.v("shaft_d") else "") + ".")
    elif k == "coupling":
        p["description"] = ("Shaft coupling joining two shaft ends" + (f", Ø{_f(c.v('od'))}" if c.v("od") else "")
                            + (f" x {_f(c.v('length'))}" if c.v("length") else "") + ".")
    elif k in ("plate", "bracket"):
        dims = [c.v(n) for n in ("L", "W", "T" if k == "plate" else "H")]
        p["description"] = f"{ct.label} " + (" x ".join(_f(x) for x in dims) + " mm." if all(dims) else "(size assumed).")
        if all(dims):
            p["envelope"] = [float(x) for x in dims]
    else:
        dims = [c.v(n) for n in ("L", "W", "H")]
        p["description"] = c.name + (f", {' x '.join(_f(x) for x in dims)} mm." if all(dims) else ".")
        if all(dims):
            p["envelope"] = [float(x) for x in dims]
    if c.material and "description" in p and ct.family != "standard" and c.material not in p["description"]:
        p["description"] = p["description"].rstrip(".") + f", {c.material}."
    return p


_SIZE_WORDS = {"d": "Ø", "shoulder_d": "step Ø", "journal_d": "journal Ø", "length": "length ", "module": "module ",
               "teeth": "", "face_width": "face width ", "od": "Ø", "width": "width ", "L": "L ", "W": "W ", "H": "H ",
               "T": "T ", "size": "M"}


def assumptions(g: DesignGraph) -> list[str]:
    """The sizes code assumed (no size in the brief), one line per part, then the model's own assumptions. Labels
    (input / output, open / blind, a fastener's style) are not sizes and are not listed."""
    out: list[str] = []
    for c in g.components:
        bits = []
        for n, p in c.params.items():
            if p.source != "assumed" or n not in _SIZE_WORDS or isinstance(p.value, bool) or                     not isinstance(p.value, int | float):
                continue
            bits.append(f"{_f(p.value)} teeth" if n == "teeth" else f"{_SIZE_WORDS[n]}{_f(p.value)}")
        if bits:
            out.append(f"{c.name}: {', '.join(bits)} assumed (the brief gives none).")
    return (out + list(g.assumptions))[:10]


def to_plan(graph: DesignGraph, *, resolved: bool = False) -> dict[str, Any]:
    from aicad.office import planner, scope

    g = graph if resolved else resolve(graph)
    subs = []
    for name, comps in groups(g):
        subs.append({"name": name, "description": _group_text(g, comps),
                     "parts": [part(g, c) for c in comps]})
    raw = {"summary": g.summary or _summary(g), "assumptions": assumptions(g), "subassemblies": subs}
    if len(subs) > 1 and scope.small(raw) and scope.rides_on_shafts(raw):  # PD-93: one unit to assemble
        raw = scope.one_unit(raw)
    plan = planner.normalise_plan(raw, PLAN_SOURCE)
    if plan is None:
        raise ValueError("the design graph has no parts")
    ids = {c.id: c.name for c in g.components}
    plan["graph"] = {"icd_overrides": icd_overrides_by_name(g), "components": ids}
    return plan


def _group_text(g: DesignGraph, comps: list[Component]) -> str:
    if any(c.kind == "housing" for c in comps):
        return "The housing that carries the bearings, with its cover and bearing caps."
    sh = [c for c in comps if c.kind == "shaft"]
    if len(sh) == 1:
        return f"The {sh[0].name.lower()} with what it carries, assembled as one unit."
    return "Every part, assembled as one unit."


def _summary(g: DesignGraph) -> str:
    designed = [c.name for c in g.components if registry.COMPONENTS[c.kind].family != "standard"]
    return f"{len(g.components)} parts from the design graph: " + ", ".join(designed[:6]) + "."


def icd_overrides_by_name(g: DesignGraph) -> dict[str, dict[str, float]]:
    """Values the plan's text can't carry: a gear face width other than the layout's 10 m."""
    out: dict[str, dict[str, float]] = {}
    for c in g.of_kind("spur_gear"):
        b, m = c.v("face_width"), c.v("module")
        if b is not None and m is not None and abs(float(b) - standards.FACE_PER_MODULE * float(m)) > 1e-9:
            out[c.name] = {"b": float(b)}
    return out


def overrides_for(plan: dict[str, Any], parts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The ICD overrides of a graph plan, keyed by the program's item ids (by part name)."""
    by_name = ((plan or {}).get("graph") or {}).get("icd_overrides") or {}
    items = {p["id"]: dict(by_name[p["name"]]) for p in parts if p["name"] in by_name}
    return {"items": items, "interfaces": {}} if items else None


def plan_parts(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """The plan as the layout's part list (``icd.parts_from`` without a program document)."""
    out = []
    for s in plan["subassemblies"]:
        for q in s["parts"]:
            out.append({"id": f"i_{s['id']}_{q['id']}", "name": q["name"], "family": q["family"], "qty": q["qty"],
                        "description": q["description"], "complexity": q["complexity"], "sub": f"i_{s['id']}",
                        **{k: q[k] for k in ("envelope", "mounts_on", "module", "teeth", "rotate") if k in q}})
    return out


def to_icd(graph: DesignGraph, plan: dict[str, Any] | None = None, *, template: bool = False
           ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(skeleton, interfaces) as the office lays out this graph's program at plan approval: solved from the
    connections (``graph/layout.py``, architecture v2 step 2), or the template layout (``icd.build``) when
    ``template`` is set, the switch ``FW_GRAPH_LAYOUT=0`` is on, or the solver can't lay this graph out yet."""
    from aicad.graph import layout
    from aicad.office import icd

    plan = plan or to_plan(graph)
    parts = plan_parts(plan)
    ov = overrides_for(plan, parts)
    if not template and layout.enabled():
        try:
            return layout.build(graph, parts, graph.brief, ov)
        except layout.Unsupported as e:
            skel, ifs = icd.build(parts, graph.brief, ov)
            skel["notes"].append(f"Laid out with the standard layout: {e}.")
            return skel, ifs
    return icd.build(parts, graph.brief, ov)


# ----------------------------------------------------------------------------- the cross-check
def check(graph: DesignGraph, skel: dict[str, Any], ifs: list[dict[str, Any]]) -> list[str]:
    """Plain-words mismatches between the graph and the ICD compiled from it (empty when they agree)."""
    g = graph
    names = {it["name"]: iid for iid, it in (skel.get("items") or {}).items()}
    std = {s["name"]: s["item"] for s in skel.get("standard") or []}
    out: list[str] = []
    for c in g.components:
        if registry.COMPONENTS[c.kind].family != "standard" and c.name not in names:
            out.append(f"{c.name} is not in the layout.")
    for k in g.constraints.excluded:
        from aicad.office import scope

        for n in list(names) + list(std):
            if scope.kind_of(n) == k:
                out.append(f"{n} is in the layout but the brief excludes a {k}.")

    def ifs_of(kind: str) -> list[dict[str, Any]]:
        return [f for f in ifs if f["kind"] == kind]

    for x in g.connections:
        h, gu = g.comp(x.host), g.comp(x.guest)
        if h is None or gu is None:
            continue
        if x.kind == "gear_mesh":
            f = next((f for f in ifs_of("gear_mesh") if {f["a"].get("name"), f["b"].get("name")} == {h.name, gu.name}),
                     None)
            if f is None:
                out.append(f"No gear mesh between {h.name} and {gu.name} in the interfaces.")
                continue
            d = f["data"]
            a = float(x.v("centre_distance") or 0)
            if abs(float(d["centre_distance"]) - a) > 1e-6 or abs(float(d["module"]) - float(h.v("module"))) > 1e-9:
                out.append(f"{h.name} / {gu.name}: the interfaces say m{d['module']:g} at {d['centre_distance']:g} mm, "
                           f"the graph m{float(h.v('module')):g} at {a:g} mm.")
            ia, ib = names.get(h.name), names.get(gu.name)
            if ia and ib:
                pa, pb = skel["items"][ia]["copies"][0], skel["items"][ib]["copies"][0]
                dist = math.dist([pa[0], pa[2]], [pb[0], pb[2]]) if skel["items"][ia].get("ax") == "y" else \
                    math.dist(pa[:2], pb[:2])
                if abs(dist - a) > 1e-6:
                    out.append(f"{h.name} and {gu.name} are laid out {dist:g} mm apart, the mesh needs {a:g}.")
        elif x.kind in ("keyed_hub", "hub_fit"):
            f = next((f for f in ifs_of("shaft_bore") if {f["a"].get("name"), f["b"].get("name")} == {h.name, gu.name}),
                     None)
            if f is None:
                out.append(f"No shaft / bore fit between {gu.name} and {h.name} in the interfaces.")
                continue
            if abs(float(f["data"]["d"]) - float(h.v("d"))) > 1e-6:
                out.append(f"{gu.name} on {h.name}: the interfaces fit it on Ø{f['data']['d']:g}, the graph Ø"
                           f"{float(h.v('d')):g}.")
            if h.v("stepped") is True and f["data"].get("shoulder_d") is not None and \
                    abs(float(f["data"]["shoulder_d"]) - float(h.v("shoulder_d"))) > 1e-6:
                out.append(f"{h.name}: the interfaces step to Ø{f['data']['shoulder_d']:g}, the graph to Ø"
                           f"{float(h.v('shoulder_d')):g}.")
            if x.kind == "keyed_hub":
                k = next((f for f in ifs_of("key") if {f["a"].get("name"), f["b"].get("name")} == {h.name, gu.name}),
                         None)
                if k is None:
                    out.append(f"No keyed joint between {gu.name} and {h.name} in the interfaces.")
                    continue
                kd = k["data"]
                row = standards.key_for_shaft(float(h.v("d")))
                if (kd["b"], kd["h"], kd["t1"], kd["t2"]) != (row["b"], row["h"], row["t1"], row["t2"]):
                    out.append(f"Key on {h.name}: the interfaces say {kd['b']:g} x {kd['h']:g}, DIN 6885 says "
                               f"{row['b']:g} x {row['h']:g}.")
                key = next((g.comp(v) for v in x.via if (g.comp(v) or Component(id="", kind="", name="")).kind == "key"),
                           None)
                if key is not None and kd.get("key_item") != std.get(key.name):
                    out.append(f"{key.name} is not the piece in the keyseat of {h.name}.")
                if key is not None and key.v("length") is not None and abs(float(kd["length"]) - float(key.v("length"))) > 1e-6:
                    out.append(f"{key.name}: {kd['length']:g} long in the interfaces, {float(key.v('length')):g} in the graph.")
        elif x.kind == "bearing_journal":
            des = gu.v("designation")
            got = [f for f in ifs if f["kind"] in ("bearing_journal", "bearing_seat")
                   and h.name in (f["a"].get("name"), f["b"].get("name"))]
            if not got:
                out.append(f"No bearing on {h.name} in the interfaces.")
            elif des is not None and any(str(f["data"].get("designation")) != str(int(des)) for f in got):
                out.append(f"{h.name}: the interfaces carry it on "
                           f"{', '.join(sorted({str(f['data'].get('designation')) for f in got}))}, the graph on {int(des)}.")
    return out


def limits(graph: DesignGraph, skel: dict[str, Any], ifs: list[dict[str, Any]]) -> list[str]:
    """Connections the graph states that the layout does not realise (said, never hidden): a shoulder stop the
    interfaces don't carry (the template layout seats hubs inside a housing on a plain shaft), and the solver's
    layout conflicts. The connection solver (``graph/layout.py``) lays shoulders out, so this is empty on it."""
    out: list[str] = [c["text"] for c in skel.get("conflicts") or []]
    for x in graph.connections:
        h, gu = graph.comp(x.host), graph.comp(x.guest)
        if x.kind != "shoulder_stop" or h is None or gu is None:
            continue
        f = next((f for f in ifs if f["kind"] == "shaft_bore" and {f["a"].get("name"), f["b"].get("name")} ==
                  {h.name, gu.name}), None)
        if f is None or f["data"].get("shoulder_d") is None:
            out.append(f"{gu.name} against a shoulder of {h.name}: inside a housing the layout seats it on a plain "
                       "shaft between the bearings for now.")
    return out


# ----------------------------------------------------------------------------- direct builds (no AI)
def to_direct(graph: DesignGraph, plan: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Per designed component: the direct builder's decision on the compiled, approved-as-is ICD."""
    from aicad.office import direct

    plan = plan or to_plan(graph)
    skel, ifs = to_icd(graph, plan)
    parts = plan_parts(plan)
    doc = {"skeleton": skel, "icd": {"version": 1, "status": "approved", "interfaces": ifs}, "brief": graph.brief,
           "items": [{"id": p["id"], "name": p["name"], "description": p["description"]} for p in parts]}
    out: dict[str, dict[str, Any]] = {}
    by_name = {p["name"]: p for p in parts}
    for c in graph.components:
        if registry.COMPONENTS[c.kind].family == "standard" or c.name not in by_name:
            continue
        p = by_name[c.name]
        out[c.id] = direct.plan(doc, {"kind": "part", "item_id": p["id"], "title": c.name, "qty": c.qty})
    return out


# ----------------------------------------------------------------------------- Fitz trains (Assembly Studio)
def to_fitz_items(graph: DesignGraph) -> tuple[list[dict[str, Any]], list[str]]:
    """(items for ``trains.select`` / the smart-insert run, components not applicable with the reason). A train is
    plain Toolbox shafts, spur gears and bearings with no housing; a stepped shaft, keys and rings are the office's."""
    from aicad import toolbox

    g = resolve(graph)
    items: list[dict[str, Any]] = []
    skipped: list[str] = []
    if g.of_kind("housing"):
        return [], ["the design has a housing: the Design Office lays it out (trains are housing-less)"]
    gears = _mesh_order(g)
    shafts = []
    for gr in gears:
        sh = _hub_on(g, gr.id)
        if sh is not None and sh not in shafts:
            shafts.append(sh)
    shafts += [s for s in g.of_kind("shaft") if s not in shafts]
    for gr in gears:
        keyed = _keyed(g, gr.id)
        bore = float(gr.v("bore") or 20.0)
        kb, kt2 = (0.0, 0.0)
        if keyed:
            row = standards.key_for_shaft(bore)
            kb, kt2 = row["b"], row["t2"]
        params = {"M": float(gr.v("module")), "Z": int(gr.v("teeth")), "B": float(gr.v("face_width")), "BORE": bore,
                  "KEY_B": kb, "KEY_T2": kt2, "KEY_ANG": 0.0}
        items.append(_item(gr, "spur_gear", toolbox.normalize("spur_gear", params), len(items)))
    for sh in shafts:
        if sh.v("stepped") is True:
            skipped.append(f"{sh.name}: a stepped shaft is designed, not a Toolbox shaft")
            continue
        L = float(sh.v("length") or 120.0)
        params = {"D": float(sh.v("d")), "L": L, "KEY_L": 40.0 if L >= 60 else max(10.0, L / 3), "C": 1.0}
        items.append(_item(sh, "shaft", toolbox.normalize("shaft", params), len(items)))
    for br in g.of_kind("bearing"):
        if br.v("designation") is None:
            skipped.append(f"{br.name}: no journal to size it from")
            continue
        items.append(_item(br, "bearing", {"SERIES": int(br.v("designation"))}, len(items), action="seat"))
    for c in g.components:
        if c.kind not in ("spur_gear", "shaft", "bearing"):
            skipped.append(f"{c.name}: placed by the Design Office (keys, rings and other parts are not train parts)")
    return items, skipped


def _mesh_order(g: DesignGraph) -> list[Component]:
    out: list[Component] = []
    for x in g.connections:
        if x.kind == "gear_mesh":
            for i in (x.host, x.guest):
                c = g.comp(i)
                if c is not None and c not in out:
                    out.append(c)
    return out + [c for c in g.of_kind("spur_gear") if c not in out]


def _item(c: Component, code: str, params: dict[str, Any], n: int, action: str = "train") -> dict[str, Any]:
    from aicad import toolbox

    comp = toolbox.spec(code)
    return {"id": f"g{n + 1}", "text": c.name, "qty": c.qty, "qty_explicit": True, "source": "toolbox", "code": code,
            "params": params, "title": comp.title(params), "standard": comp.standard, "name": comp.name,
            "confidence": "high", "read": sorted(params), "kind": code if code != "spur_gear" else "gear",
            "enabled": True, "target": None, "target_name": None, "action": action, "codes": [], "train": True,
            "order": n + 1, "graph": c.id}


# ----------------------------------------------------------------------------- layout read back
def read_layout(graph: DesignGraph, skel: dict[str, Any]) -> DesignGraph:
    """The solved positions (envelope centre of each copy, axis) and sizes, by component id."""
    g = graph.model_copy(deep=True)
    by_name = {it["name"]: it for it in (skel.get("items") or {}).values()}
    lay: dict[str, Any] = {"layout": skel.get("layout"), "parts": {}}
    for c in g.components:
        it = by_name.get(c.name)
        if it is None:
            continue
        lay["parts"][c.id] = {"at": it.get("copies"), "size": it.get("size"), "axis": it.get("ax") or "z"}
        if c.kind == "shaft" and c.v("length") is None and it.get("size"):
            c.set("length", float(it["size"][2]), "layout", "laid out from what it carries")
    g.layout = lay
    return g
