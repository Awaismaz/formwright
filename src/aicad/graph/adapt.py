"""The reverse adapter: an existing approved plan and its ICD / skeleton -> a design graph, so programs made before the
graph (Archie's text plans, the standard planner, engineer edits) can be read, shown and compared the same way.

Every value comes from the approved interfaces and the solved skeleton (``source="plan"``): the layout already sized
them, so nothing is re-derived. Mapping of the ICD interface kinds (``office.icd.KIND_LABEL``):

  shaft_bore + key (same pair)        -> keyed_hub (the key item as via)      shaft_bore alone -> hub_fit
  shaft_bore with a shoulder          -> + shoulder_stop                      gear_mesh        -> gear_mesh
  bearing_journal                     -> bearing_journal (count per shaft)    bearing_seat     -> bearing_seat
  hole_pattern                        -> bolted_joint (fastener item as via)  face             -> mounted_on
  retaining_ring                      -> ring_retained
"""

from __future__ import annotations

from typing import Any

from aicad.graph import intent, registry
from aicad.graph.model import Component, Connection, DesignGraph, Param


def _kind(p: dict[str, Any], role: str | None) -> str:
    fam = p.get("family")
    k = registry.kind_from_name(p["name"])
    if fam == "gear":
        return "spur_gear" if k in ("spur_gear", "other") else k
    if role == "shaft":
        return "shaft"
    if fam == "standard":
        return k if registry.COMPONENTS.get(k) and registry.COMPONENTS[k].family == "standard" else (
            "bearing" if "bearing" in p["name"].lower() else "other")
    if k in registry.COMPONENTS and registry.COMPONENTS[k].family != "standard":
        return k
    return "plate" if role == "block" and "plate" in p["name"].lower() else ("housing" if role == "block" and k == "housing"
                                                                             else "other")


def from_office(plan: dict[str, Any], skel: dict[str, Any] | None, ifs: list[dict[str, Any]] | None,
                brief: str = "", name: str = "") -> DesignGraph:
    """A graph from an approved plan (``doc["plan"]``) and, when present, the ICD (``doc["skeleton"]``,
    ``doc["icd"]["interfaces"]``). Without an ICD the graph has the components and no connections."""
    rows = [(f"i_{s['id']}_{p['id']}", p, str(s.get("name") or "")) for s in plan.get("subassemblies") or []
            for p in s.get("parts") or []]
    g = DesignGraph(name=name, brief=brief, summary=str(plan.get("summary") or ""), source="plan",
                    constraints=intent.constraints_of(brief), assumptions=list(plan.get("assumptions") or []))
    return _from_rows(g, rows, skel, ifs)


def from_parts(parts: list[dict[str, Any]], skel: dict[str, Any] | None, ifs: list[dict[str, Any]] | None,
               brief: str = "", name: str = "") -> DesignGraph:
    """The same from the layout's own part list (``icd.parts_from`` / ``compile.plan_parts``: item ids, no plan
    document): what the parity check of the connection layout re-solves (``docs/reports/connection-layout.md``)."""
    g = DesignGraph(name=name, brief=brief, source="plan", constraints=intent.constraints_of(brief))
    return _from_rows(g, [(p["id"], p, str(p.get("sub") or "")) for p in parts], skel, ifs)


def _from_rows(g: DesignGraph, rows: list[tuple[str, dict[str, Any], str]], skel: dict[str, Any] | None,
               ifs: list[dict[str, Any]] | None) -> DesignGraph:
    skel = skel or {}
    items = skel.get("items") or {}
    by_item: dict[str, str] = {}
    for iid, p, group in rows:
        it = items.get(iid) or {}
        kind = _kind(p, it.get("role"))
        c = Component(id=g.new_id(p["name"]), kind=kind, name=p["name"], qty=int(p.get("qty") or 1), group=group)
        _params_from(c, p, it)
        g.components.append(c)
        by_item[iid] = c.id
    pairs: dict[frozenset[str], dict[str, Any]] = {}
    journals: dict[tuple[str, str], int] = {}
    for f in ifs or []:
        a, b = by_item.get(str((f.get("a") or {}).get("item"))), by_item.get(str((f.get("b") or {}).get("item")))
        d = f.get("data") or {}
        k = f.get("kind")
        if k in ("shaft_bore", "key") and a and b:
            e = pairs.setdefault(frozenset((a, b)), {"a": a, "b": b})
            e[k] = d
        elif k == "gear_mesh" and a and b:
            g.connections.append(Connection(id=g.next_connection_id(), kind="gear_mesh", host=a, guest=b, params={
                "centre_distance": Param(value=float(d.get("centre_distance") or 0), source="plan"),
                "ratio": Param(value=float(d.get("ratio") or 0), source="plan")}))
        elif k == "bearing_journal" and a:
            br = by_item.get(str(d.get("bearing_item")))
            if br:
                journals[(a, br)] = journals.get((a, br), 0) + int(d.get("count") or 1)
                _bearing(g, br, d)
        elif k == "bearing_seat" and a and b:
            br = by_item.get(str(d.get("bearing_item")))
            n = int(d.get("count") or 2)
            if br:
                journals[(b, br)] = journals.get((b, br), 0) + n
                _bearing(g, br, d)
                g.connections.append(Connection(id=g.next_connection_id(), kind="bearing_seat", host=a, guest=br,
                                                params={"count": Param(value=n, source="plan")}))
        elif k == "hole_pattern" and a and b:
            via = [x for x in [by_item.get(str(d.get("fastener_item")))] if x]
            g.connections.append(Connection(id=g.next_connection_id(), kind="bolted_joint", host=a, guest=b, via=via))
        elif k == "face" and a and b:
            g.connections.append(Connection(id=g.next_connection_id(), kind="mounted_on", host=a, guest=b))
        elif k == "retaining_ring" and a and b:
            via = [x for x in [by_item.get(str(d.get("ring_item")))] if x]
            g.connections.append(Connection(id=g.next_connection_id(), kind="ring_retained", host=b, guest=a, via=via))
    for e in pairs.values():
        sb = e.get("shaft_bore") or {}
        shaft, hub = _shaft_side(g, e["a"], e["b"])
        kx: Connection | None = None
        if e.get("key"):
            via = [x for x in [by_item.get(str(e["key"].get("key_item")))] if x]
            kx = Connection(id=g.next_connection_id(), kind="keyed_hub", host=shaft, guest=hub, via=via)
            g.connections.append(kx)
        else:
            g.connections.append(Connection(id=g.next_connection_id(), kind="hub_fit", host=shaft, guest=hub, params={
                "fit": Param(value=str(sb.get("fit") or "H7/k6"), source="plan")}))
        sh = g.comp(shaft)
        if sb.get("d") is not None and sh is not None:
            sh.set("d", float(sb["d"]), "plan", force=True)
            hc = g.comp(hub)
            if hc is not None:
                hc.set("bore", float(sb["d"]), "plan", force=True)
        if sb.get("shoulder_d") is not None and sh is not None:
            sh.set("stepped", True, "plan", force=True)
            sh.set("shoulder_d", float(sb["shoulder_d"]), "plan", force=True)
            g.connections.append(Connection(id=g.next_connection_id(), kind="shoulder_stop", host=shaft, guest=hub))
        if kx is not None:
            for v in kx.via:
                kc = g.comp(v)
                if kc is not None:
                    for n in ("b", "h", "t1", "t2", "length"):
                        if e["key"].get(n) is not None:
                            kc.set(n, float(e["key"][n]), "plan", force=True)
                    kc.set("shaft_d", float(e["key"]["d"]), "plan", force=True)
    for (sh, br), n in journals.items():
        if not any(x.kind == "bearing_journal" and x.host == sh and x.guest == br for x in g.connections):
            g.connections.append(Connection(id=g.next_connection_id(), kind="bearing_journal", host=sh, guest=br,
                                            params={"count": Param(value=n, source="plan")}))
    from aicad.graph.compile import read_layout

    return read_layout(g, skel) if skel else g


def _shaft_side(g: DesignGraph, a: str, b: str) -> tuple[str, str]:
    ca, cb = g.comp(a), g.comp(b)
    if ca is not None and ca.kind == "shaft":
        return a, b
    if cb is not None and cb.kind == "shaft":
        return b, a
    return b, a


def _bearing(g: DesignGraph, br: str, d: dict[str, Any]) -> None:
    c = g.comp(br)
    if c is None or d.get("designation") is None:
        return
    c.kind = "bearing"
    c.set("designation", int(d["designation"]), "plan", force=True)
    for n in ("d", "D", "B"):
        if d.get(n) is not None:
            c.set(n, float(d[n]), "plan", force=True)


def _params_from(c: Component, p: dict[str, Any], it: dict[str, Any]) -> None:
    size = it.get("size") or p.get("envelope")
    if c.kind == "spur_gear":
        for src, dst in (("module", "module"), ("teeth", "teeth")):
            v = it.get(src) if it.get(src) is not None else p.get(src)
            if v is not None:
                c.set(dst, float(v) if dst == "module" else int(v), "plan", force=True)
        fw = it.get("face_width") or (size[2] if size else None)
        if fw is not None:
            c.set("face_width", float(fw), "plan", force=True)
        if it.get("bore") is not None:
            c.set("bore", float(it["bore"]), "plan", force=True)
    elif c.kind == "shaft" and size:
        c.set("d", float(it.get("d") or size[0]), "plan", force=True)
        c.set("length", float(size[2]), "plan", force=True)
    elif c.kind in ("housing", "cover", "plate", "bracket") and size:
        keys = ("L", "W", "T") if c.kind == "plate" else ("L", "W", "H")
        for k, v in zip(keys, size, strict=False):
            c.params[k] = Param(value=float(v), source="plan")
    elif c.kind in ("pulley", "hub", "spacer") and size:
        c.set("od", float(size[0]), "plan", force=True)
        c.set("length" if c.kind == "spacer" else "width", float(size[2]), "plan", force=True)
    elif c.kind == "bearing_cap":
        from aicad.office import icd

        style = icd._cap_kind(p)  # by its name, else its description; a cap that says neither goes either way
        if style:
            c.set("style", style, "plan", force=True)
