"""A design graph read from the roles of a plan's parts, by code (no model): the fallback layout for plans without a
graph when the template layout leaves parts unconnected (the founder's "TEST Project", 2026-11-20: a foldable table
whose legs floated).

Roles, read from the part names (plain words, stated so they can be checked):

  base        a top, table, desk, deck, frame, chassis or base plate (exactly one, qty 1): what the others mount on,
              never simply the largest box
  connector   a bracket, hinge, mount, clamp, lug or clevis: bolted to the base (under it when the base is a top)
  member      a leg, arm, link, strut or lever: pivots on a connector when the brief or a part name says the thing
              folds, pivots, hinges or swings (a pivot bolt with its washers and nut), else bolted to it; copy i on
              connector copy i
  fasteners   bolts / screws by their words: "pivot" ones make the pivot joints (with the washers and nuts), the
              others hold the connectors; sizes from an M-number in the name or description, else stated defaults

Sizes the plan leaves open are assumed (said in the graph's notes): a table top 1200 x 700 x 18 (a four-seat folding
table), legs 700 long and 40 x 20, brackets 60 x 30 x 60; other bases 600 x 400 x 15, members 300 x 30 x 15. A plan
whose parts don't read this way returns None (the template layout stays).
"""

from __future__ import annotations

import re
from typing import Any

from aicad.graph.model import Component, Connection, DesignGraph, Param

_BASE = re.compile(r"\btop\b|\btable\b|\bdesk\b|\bdeck\b|\bframe\b|chassis|\bbase\b", re.IGNORECASE)
_CONN = re.compile(r"bracket|hinge|\bmount\b|clamp|\blug\b|clevis", re.IGNORECASE)
_MEMB = re.compile(r"\blegs?\b|\barms?\b|\blinks?\b|strut|lever", re.IGNORECASE)
_PIVOT = re.compile(r"fold|pivot|hinge|swing|tilt", re.IGNORECASE)
_M = re.compile(r"\bM(\d{1,2})\b")
BASE_TABLE = (1200.0, 700.0, 18.0)   # a four-seat folding table's top
BASE_OTHER = (600.0, 400.0, 15.0)
CONNECTOR = (60.0, 30.0, 60.0)      # a leg bracket
LEG = (40.0, 20.0, 700.0)           # a table leg: about 730 to the floor with the top and the bracket
MEMBER = (300.0, 30.0, 15.0)


def _p(v: Any, note: str = "assumed by the role layout") -> Param:
    return Param(value=v, source="assumed", note=note)


def _env(p: dict[str, Any]) -> list[float] | None:
    e = p.get("envelope")
    return [float(x) for x in e] if isinstance(e, list) and len(e) == 3 and min(float(x) for x in e) > 0 else None


def from_roles(parts: list[dict[str, Any]], brief: str = "") -> DesignGraph | None:
    designed = [p for p in parts if p.get("family") != "standard"]
    std = [p for p in parts if p.get("family") == "standard"]
    bases = [p for p in designed if _BASE.search(p["name"]) and int(p.get("qty") or 1) == 1
             and not _CONN.search(p["name"]) and not _MEMB.search(p["name"])]
    if len(bases) != 1:
        return None
    base = bases[0]
    conns = [p for p in designed if p is not base and _CONN.search(p["name"])]
    membs = [p for p in designed if p is not base and p not in conns and _MEMB.search(p["name"])]
    if not conns or len(designed) != 1 + len(conns) + len(membs):
        return None
    words = " ".join([brief] + [p["name"] for p in parts])
    pivoting = bool(_PIVOT.search(words))
    table = bool(re.search(r"\btable\b", words, re.IGNORECASE))
    g = DesignGraph(name="", brief=brief, source="plan")
    notes: list[str] = []

    def comp(p: dict[str, Any], kind: str, dims: tuple[float, float, float], keys: tuple[str, str, str]) -> Component:
        e = _env(p)
        c = Component(id=g.new_id(p["name"]), kind=kind, name=p["name"], qty=int(p.get("qty") or 1))
        vals = e or list(dims)
        for k, v in zip(keys, vals, strict=True):
            c.params[k] = Param(value=float(v), source="plan") if e else _p(float(v))
        if not e:
            notes.append(f"{p['name']}: {' x '.join(f'{v:g}' for v in vals)} assumed")
        g.components.append(c)
        return c

    b = comp(base, "plate", BASE_TABLE if table else BASE_OTHER, ("L", "W", "T"))
    cs = [comp(p, "bracket", CONNECTOR, ("L", "W", "H")) for p in conns]
    ms = [comp(p, "other", LEG if re.search(r"\blegs?\b", p["name"], re.IGNORECASE) else MEMBER, ("L", "W", "H"))
          for p in membs]
    pivot_f: list[str] = []
    other_f: list[str] = []
    for p in std:
        t = f"{p['name']} {p.get('description') or ''}"
        kind = "washer" if re.search(r"washer", t, re.IGNORECASE) else "nut" if re.search(r"\bnut\b", t, re.IGNORECASE) \
            else "fastener" if re.search(r"bolt|screw", t, re.IGNORECASE) else None
        if kind is None:
            return None  # a bought-out part this reading can't place: the template stays
        m = _M.search(t)
        piv = bool(re.search(r"pivot", t, re.IGNORECASE)) or (kind != "fastener" and pivoting)
        size = int(m.group(1)) if m else (8 if piv else 5 if re.search(r"wood", t, re.IGNORECASE) else 6)
        c = Component(id=g.new_id(p["name"]), kind=kind, name=p["name"], qty=int(p.get("qty") or 1),
                      params={"size": Param(value=size, source="plan" if m else "assumed")})
        if kind == "fastener":
            c.params["style"] = Param(value="shcs" if re.search(r"socket|cap screw|wood screw", t, re.IGNORECASE)
                                      else "hex_bolt", source="plan")
        g.components.append(c)
        (pivot_f if piv else other_f).append(c.id)
    joint_f = [i for i in other_f if (g.comp(i) or Component(id="", kind="", name="")).kind == "fastener"]
    for c in cs:
        g.connections.append(Connection(id=g.next_connection_id(), kind="bolted_joint", host=b.id, guest=c.id,
                                        via=joint_f[:1]))
    for k, m in enumerate(ms):
        host = cs[min(k, len(cs) - 1)]
        kind = "pin_joint" if pivoting else "bolted_joint"
        g.connections.append(Connection(id=g.next_connection_id(), kind=kind, host=host.id, guest=m.id,
                                        via=pivot_f if pivoting else joint_f[:1]))
    if notes:
        g.assumptions.append("Sizes the plan leaves open, assumed by the role layout: " + "; ".join(notes) + ".")
    return g
