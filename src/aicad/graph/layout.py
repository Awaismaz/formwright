"""Layout solved from the design graph's connection semantics (architecture v2, step 2; WORKLIST 44).

``build(graph, parts, brief, overrides)`` returns ``(skeleton, interfaces)`` in exactly the format ``office.icd.build``
produces (the same items, copies, axes, datums, interface kinds and data keys), so the office, Fitz, the direct
builder, conformance, drawings and the visual check run unchanged. The difference is where positions come from: the
template engine in ``icd.build`` recognises a few mechanisms (block rows, the gearbox, the shaft line, the shaft
sub-assembly) from the plan's words; this module places every part by the connection that carries it, so a new
combination of known connections needs no new template.

Placement rule per connection kind (the registry's ``placement`` words, ``graph/registry.py``):

  keyed_hub / hub_fit   the hub coaxial on its shaft's seat; along the axis: the hub that meshes with (or belts to) an
                        already placed shaft is the shaft's anchor (its mid-plane on the partner's), the others stack
                        +Y after it (GEAR_SPACE between two gears, none after a spacer); the key centred in the hub
  shoulder_stop         the hub's +Y face on the shoulder: the shaft is stepped there (a collar of the shoulder Ø
                        runs on to the bearing on that side, so the bearing bears on it too, or COLLAR long)
  bearing_journal       two bearings per shaft, one either side of what turns near them, BEARING_CLEAR clear (a
                        spacer or a collar in between: against it); in a housing the bearings sit in the walls (flush
                        with the outer face); the shaft runs SHAFT_END beyond the outer bearing faces
  bearing_seat          housing: the shaft axis through both walls, the seats at the outer faces (the shafts' axes
                        are the housing bores, so a loop "two shafts mesh and sit in one housing" is consistent by
                        construction); pillow block: the block centred on its bearing, the seat open outboard
  gear_mesh             parallel axes at a = m (z1 + z2) / 2 along +X, mid-planes coplanar, teeth phased v = 1/2 - u
  belt_drive            parallel axes at the stated C (else C = D1 + D2, a rule), pulley mid-planes coplanar
  coupling              coaxial, end to end with COUPLING_GAP; the coupling across the joint, BEARING_CLEAR clear of
                        the bearing (or pillow block) next to it
  bolted_joint          faces coincident, holes aligned: a cover on top of its housing, caps over the seats (coaxial),
                        blocks on their host's top face (pillow blocks under their bearings, a bracket under its motor)
  ring_retained         the DIN 471 ring in its groove at the guest's free face (opposite the shoulder)
  spacer (hub_fit)      between the faces of its neighbours: the next part bears on it

The solve is a walk from a fixed base (the housing, the base plate, else the input shaft). Shafts are the nodes of an
axis graph whose edges are the meshes, belts and couplings; a breadth-first walk places each shaft at its edge's
distance (the first neighbour along +X, a second along -X) and carries the mesh planes along. Edges that close a
loop are checked, never assumed: two shafts meshing and belted at different distances, or coupled and meshed, are a
``layout_conflict`` that names the parts and the connections. Heights that two paths fix (pillow blocks and a motor
bracket on one plate: the coupled axes must agree) are solved together: the lowest height every path allows, a
stated height wins, two stated heights that disagree are a conflict. A part no connection reaches is a conflict too
(it is still drawn beside the program, and said, never left silently on the floor).

What this solver does not lay out yet raises ``Unsupported`` and the caller uses the template layout (said in the
notes): gears or pulleys that sit on no shaft, a housing next to free shafts or on a plate, blocks with no shafts,
a shaft meshing with more than two unplaced neighbours (a 2-D train).
Canonical frames as in ``office/frames.py``: shafts along +Y (the gearbox convention), program +Z up.
"""

from __future__ import annotations

import math
import os
import re
from collections import deque
from typing import Any

from aicad.graph import registry
from aicad.graph.model import Connection, DesignGraph
from aicad.office import frames, icd
from aicad.office.icd import (
    BEARING_CLEAR,
    BEARINGS,
    CAP_RELIEF,
    CAV,
    CAV_Y,
    CLEARANCE,
    EXIT_SIDE,
    FITS,
    FLATNESS,
    FLOOR,
    GAP,
    GEAR_SPACE,
    HOUSING_FITS,
    KIND_LABEL,
    LIGAMENT,
    LIGAMENT_D,
    MARGIN,
    POS_TOL,
    PRESSURE_ANGLE,
    RINGS,
    SEAT_END,
    SHAFT_END,
    SHAFT_FIT_BEARING,
    SHOULDER,
    TAP_DRILL,
    WASHER_OD,
    _r2,
)

ENV = "FW_GRAPH_LAYOUT"   # "0": graph plans use the template layout (icd.build) too
COLLAR = BEARING_CLEAR    # mm: a shoulder collar with no bearing against it (the same room a gear keeps to a bearing)
COUPLING_GAP = 2.0        # mm between the two shaft ends inside a coupling
COUPLING_ENGAGE = 1.5     # x the larger shaft Ø: how far each shaft reaches into the coupling (at most the stub)
PB_WALL = 0.25            # x the bearing OD: wall of a pillow block around its seat (at least PB_WALL_MIN)
PB_WALL_MIN = 8.0
BRACKET_MIN = 10.0        # mm: the least bracket under a motor
BEARING_SPAN = 4.0        # x the shaft Ø (at least 2 x the bearing OD): bearings of a shaft that carries nothing
MOTOR = {"shaft_d": 14.0, "shaft_length": 30.0, "L": 180.0, "W": 120.0, "H": 120.0}  # assumed envelope (IEC 71-ish)
CORNER = 30.0             # mm from a base's edges to a connector at its corner (a table's leg brackets)
PIVOT_CLEAR = 2.0         # mm between a pivoting member's upper end and the base it hangs under
_TOPPY = re.compile(r"\btop\b|table|desk|deck|shelf|seat|worktop|\blid\b", re.IGNORECASE)
ROLE = {"shaft": "shaft", "spur_gear": "gear", "pulley": "hub", "hub": "hub", "spacer": "hub", "bearing_cap": "hub",
        "coupling": "hub"}
HUBS = ("keyed_hub", "hub_fit")
TOL = 1e-6


class Unsupported(Exception):
    """A graph this solver does not lay out yet: the caller lays it out with the template (``icd.build``)."""


def enabled() -> bool:
    return os.environ.get(ENV, "").strip() != "0"


def graph_of(plan: dict[str, Any] | None) -> DesignGraph | None:
    gd = (((plan or {}).get("graph") or {}).get("data"))
    if not gd:
        return None
    try:
        return DesignGraph.load(gd)
    except Exception:  # noqa: BLE001  (an unreadable graph: the template layout)
        return None


def build_for_doc(doc: dict[str, Any], overrides: dict[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """The office's layout of a program planned from a design graph, or None (no graph, the switch is off, or the
    solver can't lay it out: the caller uses ``icd.build`` and says why in the notes)."""
    g = graph_of(doc.get("plan"))
    if g is None or not enabled():
        return None
    try:
        return build(g, icd.parts_from(doc), str(doc.get("brief") or ""), overrides, resolved=True)
    except Unsupported as e:
        doc.setdefault("_layout_fallback", str(e))
        return None


def build(graph: DesignGraph, parts: list[dict[str, Any]], brief: str = "", overrides: dict[str, Any] | None = None,
          *, resolved: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from aicad.graph.resolve import resolve

    g = graph if resolved else resolve(graph)
    return _Layout(g, parts, brief or g.brief, overrides).run()


# ============================================================================ the solver
class _Layout:
    def __init__(self, g: DesignGraph, parts: list[dict[str, Any]], brief: str, overrides: dict[str, Any] | None):
        self.g, self.parts, self.brief = g, parts, brief
        ov = overrides or {}
        self.ov = ov
        self.iov: dict[str, dict[str, Any]] = ov.get("items") or {}
        self.fov: dict[str, dict[str, Any]] = ov.get("interfaces") or {}
        self.by_pid = {p["id"]: p for p in parts}
        by_name = {p["name"]: p for p in parts}
        self.comp = {c.id: c for c in g.components}
        self.item: dict[str, str] = {}
        self.bought: set[str] = set()  # bought-out components (an "other" part the plan buys out counts)
        for c in g.components:
            p = by_name.get(c.name)
            if p is None:
                raise Unsupported(f"{c.name} is in the design graph but not in the plan")
            std = registry.COMPONENTS[c.kind].family == "standard" or (c.kind == "other" and p["family"] == "standard")
            if std:
                self.bought.add(c.id)
            if std != (p["family"] == "standard"):
                raise Unsupported(f"{c.name} is a {'bought-out' if std else 'designed'} part in the graph, not in the plan")
            self.item[c.id] = p["id"]
        names = {c.name for c in g.components}
        extra = [p["name"] for p in parts if p["name"] not in names and p["family"] != "standard"]
        if extra:
            raise Unsupported(f"the plan has parts the design graph doesn't ({', '.join(extra[:3])})")
        self.cid_of = {v: k for k, v in self.item.items()}
        self.designed = [c.id for c in g.components if c.id not in self.bought]
        self.spec: dict[str, dict[str, Any]] = {}
        self.at: dict[str, list[list[float] | None]] = {}
        self.notes: list[str] = []
        self.conflicts: list[dict[str, Any]] = []
        self.ifs: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ small helpers
    def name(self, cid: str) -> str:
        return self.comp[cid].name

    def role(self, cid: str | None) -> str:
        if cid is None:
            return ""
        return "standard" if cid in self.bought else ROLE.get(self.comp[cid].kind, "block")

    def height(self, cid: str) -> float:
        s = self.spec[cid]
        return float(s["b"]) if s["role"] == "gear" else float(s.get("H") or 0.0)

    def tip(self, cid: str) -> float:
        s = self.spec[cid]
        if s["role"] == "gear":
            return float(s["module"]) * (int(s["teeth"]) + 2)
        return float(s.get("OD") or s.get("d") or 0.0)

    def od(self, cid: str) -> float:
        s = self.spec[cid]
        return {"gear": s.get("pitch", 0.0), "hub": s.get("OD", 0.0), "shaft": s.get("d", 0.0)}.get(s["role"], 0.0)

    def conflict(self, text: str, parts: list[str], conns: list[str]) -> None:
        names = [self.name(c) for c in dict.fromkeys(parts)]
        self.conflicts.append({"text": "Layout conflict: " + text, "parts": names, "connections": list(dict.fromkeys(conns)),
                               "items": [self.item[c] for c in dict.fromkeys(parts) if c in self.item and
                                         self.role(c) != "standard"]})

    def o(self, cid: str) -> dict[str, Any]:
        return self.iov.get(self.item[cid]) or {}

    def p(self, cid: str) -> dict[str, Any]:
        return self.by_pid[self.item[cid]]

    def ncopies(self, cid: str) -> int:
        return min(int(self.comp[cid].qty), icd.MAX_COPIES)

    # ------------------------------------------------------------------ the run
    def run(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        self._sizes()
        self._topology()
        self._context()
        self._axes()
        if self.kind == "gearbox":
            self._gearbox()
        elif self.kind == "plate":
            self._plate()
        elif self.kind == "guide":
            self._guide()
        elif self.kind == "pin":
            self._pin()
        elif self.kind == "blocks":
            self._blocks()
        elif self.kind == "mount":
            self._mount()
        else:
            self._line()
        self._loose()
        self._emit()
        return self._skeleton(), self.ifs

    # ------------------------------------------------------------------ 1. sizes from the graph (and ICD edits)
    def _sizes(self) -> None:
        ratio = icd._ratio(self.brief)
        gear_n = 0
        for cid in self.designed:
            c, p = self.comp[cid], self.p(cid)
            r = self.role(cid)
            o = self.o(cid)
            s = icd._initial(p, r, self.brief, ratio, gear_n, o)
            gear_n += r == "gear"

            def put(key: str, val: Any, s: dict[str, Any] = s, o: dict[str, Any] = o) -> None:
                if val is not None and key not in o:
                    s[key] = float(val) if key != "teeth" else int(val)

            if r == "shaft":
                put("d", c.v("d"))
                put("length", c.v("length"))
                s["seat"] = float(s["d"])
                if c.v("stepped") is True and c.v("shoulder_d") is not None:
                    body = float(o.get("shoulder_d") or c.v("shoulder_d"))
                    s["body"] = body if body > s["seat"] + TOL else None
                s.setdefault("length", 0.0)
                s["length"] = float(s.get("length") or 0.0)
            elif r == "gear":
                put("module", c.v("module"))
                put("teeth", c.v("teeth"))
                if "b" not in o:
                    s["b"] = float(c.v("face_width") or 10.0 * float(s["module"]))
                s["pitch"] = float(s["module"]) * int(s["teeth"])
            elif r == "hub":
                k = c.kind
                if k in ("pulley", "hub"):
                    put("OD", c.v("od"))
                    put("H", c.v("width"))
                elif k == "spacer" or k == "coupling":
                    put("OD", c.v("od"))
                    put("H", c.v("length"))
                s["od_given"] = bool(c.v("od") is not None or "OD" in o)
            else:
                k = c.kind
                keys = ("L", "W", "T") if k == "plate" else ("L", "W", "H")
                for src, dst in zip(keys, ("L", "W", "H"), strict=True):
                    put(dst, c.v(src))
                s["given"] = {dst for src, dst in zip(keys, ("L", "W", "H"), strict=True)
                              if c.v(src) is not None or dst in o}
                if k == "motor":
                    for key, v in MOTOR.items():
                        src = c.v(key)
                        val = float(src) if src is not None else v
                        # the motor's envelope: X its width W, Y its body length L (along its shaft), Z its height
                        if key == "L" and "W" not in o:
                            s["W"] = val
                        elif key == "W" and "L" not in o:
                            s["L"] = val
                        elif key == "H" and "H" not in o:
                            s["H"] = val
                        elif key in ("shaft_d", "shaft_length"):
                            s[key] = val
                    s["given"] = {"L", "W", "H"}
                    if c.v("L") is None or c.v("H") is None:
                        self.notes.append(f"{c.name}: bought out; its envelope ({s['L']:g} x {s['W']:g} x {s['H']:g}, "
                                          f"shaft Ø{s['shaft_d']:g} x {s['shaft_length']:g}) is assumed: replace it with "
                                          "the maker's dimensions.")
            pl = icd._planned(p, s, o)
            if pl:
                s["planned"] = pl
            s["rot"] = 0
            self.spec[cid] = s

    # ------------------------------------------------------------------ 2. what carries what
    def _topology(self) -> None:
        g = self.g
        self.riders: dict[str, list[str]] = {}
        self.rider_of: dict[str, str] = {}
        self.hub_conn: dict[str, Connection] = {}
        self.stops: dict[str, set[str]] = {}
        self.brg: dict[str, list[tuple[str, int, Connection]]] = {}
        self.seat_host: dict[str, tuple[str, Connection]] = {}
        self.edges: list[dict[str, Any]] = []
        self.rings: list[Connection] = []
        self.joints: list[Connection] = []
        self.shafts = [c for c in self.designed if self.comp[c].kind == "shaft"]
        for s in self.shafts:
            self.riders[s], self.stops[s], self.brg[s] = [], set(), []
        piece: dict[str, int] = {}
        for x in g.connections:
            h, gu = self.comp.get(x.host), self.comp.get(x.guest)
            if h is None or gu is None:
                continue
            if x.kind in HUBS:
                if h.kind != "shaft":
                    raise Unsupported(f"{gu.name} is fitted on {h.name}, which is not a shaft")
                if gu.kind == "coupling" or self.role(gu.id) not in ("gear", "hub"):
                    continue
                if gu.id in self.rider_of and self.rider_of[gu.id] != h.id:
                    other = self.rider_of[gu.id]
                    self.conflict(f"{gu.name} is fitted on two shafts ({self.name(other)} and {h.name}): a hub sits on "
                                  "one shaft.", [gu.id, other, h.id], [self.hub_conn[gu.id].id, x.id])
                    continue
                self.rider_of[gu.id] = h.id
                self.hub_conn[gu.id] = x
                if gu.id not in self.riders[h.id]:
                    self.riders[h.id].append(gu.id)
            elif x.kind == "shoulder_stop":
                if h.kind == "shaft" and gu.kind != "bearing":
                    self.stops[h.id].add(gu.id)
            elif x.kind == "bearing_journal":
                if h.kind != "shaft" or gu.kind != "bearing":
                    continue
                n = int(x.v("count") or 2)
                for _ in range(min(n, 2)):
                    k = piece.get(gu.id, 0)
                    if k >= int(gu.qty):
                        self.conflict(f"{h.name} needs {n} of {gu.name} but the design has {gu.qty} in all.",
                                      [h.id, gu.id], [x.id])
                        break
                    piece[gu.id] = k + 1
                    self.brg[h.id].append((gu.id, k, x))
            elif x.kind == "bearing_seat":
                if gu.id in self.seat_host and self.seat_host[gu.id][0] != h.id:
                    o = self.seat_host[gu.id]
                    if self.comp[o[0]].kind == "housing" or h.kind == "housing":
                        self.conflict(f"{gu.name} is seated in both {self.name(o[0])} and {h.name}.",
                                      [gu.id, o[0], h.id], [o[1].id, x.id])
                    continue
                self.seat_host[gu.id] = (h.id, x)
            elif x.kind in ("gear_mesh", "belt_drive"):
                self.edges.append({"kind": x.kind, "ra": h.id, "rb": gu.id, "conn": x})
            elif x.kind == "coupling":
                self.edges.append({"kind": "coupling", "ra": h.id, "rb": gu.id, "conn": x,
                                   "via": next((v for v in x.via if self.comp.get(v) is not None
                                                and self.comp[v].kind == "coupling"), None)})
            elif x.kind == "ring_retained":
                self.rings.append(x)
            elif x.kind in ("bolted_joint", "mounted_on"):
                self.joints.append(x)
        for s in self.shafts:  # a shoulder stop on a part the shaft doesn't carry
            for r in sorted(self.stops[s]):
                if r not in self.riders[s]:
                    x = next(c for c in g.connections if c.kind == "shoulder_stop" and c.host == s and c.guest == r)
                    self.conflict(f"{self.name(r)} is stopped by a shoulder of {self.name(s)} but is not fitted on it.",
                                  [r, s], [x.id])
                    self.stops[s].discard(r)
        for e in self.edges:  # the shafts at the two ends of every axis edge
            if e["kind"] == "coupling":
                a = e["ra"] if self.comp[e["ra"]].kind == "shaft" else None
                e["a"], e["b"] = a, e["rb"]
                e["motor"] = e["ra"] if a is None else None
                continue
            for w in ("a", "b"):
                r = e["r" + w]
                if r not in self.rider_of:
                    raise Unsupported(f"{self.name(r)} meshes or belts but sits on no shaft")
                e[w] = self.rider_of[r]
            if e["a"] == e["b"]:
                self.conflict(f"{self.name(e['ra'])} and {self.name(e['rb'])} are on the same shaft "
                              f"({self.name(e['a'])}) and can't {'mesh' if e['kind'] == 'gear_mesh' else 'be belted'}.",
                              [e["ra"], e["rb"], e["a"]], [e["conn"].id])
                e["dead"] = True
                continue
            if e["kind"] == "gear_mesh":
                sa, sb = self.spec[e["ra"]], self.spec[e["rb"]]
                if abs(float(sa["module"]) - float(sb["module"])) > 1e-9:
                    self.conflict(f"{self.name(e['ra'])} (m{sa['module']:g}) and {self.name(e['rb'])} "
                                  f"(m{sb['module']:g}) can't mesh.", [e["ra"], e["rb"]], [e["conn"].id])
                    e["dead"] = True
                    continue
                e["dist"] = float(sa["module"]) * (int(sa["teeth"]) + int(sb["teeth"])) / 2
            else:
                d1, d2 = self.od(e["ra"]), self.od(e["rb"])
                given = e["conn"].v("centre_distance")
                e["dist"] = float(given) if given else d1 + d2
                e["rule"] = not given
                if e["dist"] < (d1 + d2) / 2 + 1.0:
                    self.conflict(f"the belt drive {self.name(e['ra'])} / {self.name(e['rb'])} at C = {e['dist']:g} mm "
                                  f"puts the pulleys (Ø{d1:g}, Ø{d2:g}) into each other.", [e["ra"], e["rb"]],
                                  [e["conn"].id])
        self.edges = [e for e in self.edges if not e.get("dead")]
        # bore / OD of hubs on their shafts (as the template: a hub's OD leaves a rim)
        for sh in self.shafts:
            d = self.spec[sh]["seat"]
            for r in self.riders[sh]:
                s = self.spec[r]
                s["bore"] = d
                if s["role"] == "hub" and not s.get("od_given"):
                    s["OD"] = max(float(s["OD"]), d + 2 * max(8.0, 0.5 * d))
        for e in self.edges:
            if e["kind"] == "coupling" and e.get("via"):
                cs = self.spec[e["via"]]
                da = self.spec[e["a"]]["seat"] if e["a"] else float(self.spec[e["motor"]]["shaft_d"])
                db = self.spec[e["b"]]["seat"]
                dm = max(da, db)
                eng = COUPLING_ENGAGE * dm
                if e.get("motor"):
                    eng = min(eng, float(self.spec[e["motor"]]["shaft_length"]))
                if not cs.get("od_given"):
                    cs["OD"] = _r2(2.5 * dm)
                if "H" not in self.o(e["via"]) and self.comp[e["via"]].v("length") is None:
                    cs["H"] = _r2(2 * eng + COUPLING_GAP)
                cs["bore"] = db
                e["eng"] = (float(cs["H"]) - COUPLING_GAP) / 2
                e["da"], e["db"] = da, db

    # ------------------------------------------------------------------ 3. which mechanism carries the shafts
    def _context(self) -> None:
        self.rod_x = [x for x in self.g.connections if x.kind == "rod_support" and x.guest in self.spec
                      and x.host in self.spec]
        self.slide_x = [x for x in self.g.connections if x.kind == "slide" and x.host in self.spec and x.guest in self.spec]
        self.pin_x = [x for x in self.g.connections if x.kind == "pin_joint" and x.host in self.spec
                      and x.guest in self.spec]
        rods = {x.guest for x in self.rod_x}
        if self.shafts and rods >= set(self.shafts) and not any(self.brg[s] for s in self.shafts):
            self.kind, self.sub_line, self.ctx = "guide", False, {s: "guide" for s in self.shafts}
            return
        if not self.shafts and self.pin_x:
            guests = {x.guest for x in self.joints} | {x.guest for x in self.pin_x}
            roots = [b for b in self.designed if b not in guests]
            mounted = all(x.host in roots for x in self.pin_x) and len(self.pin_x) == 1
            self.kind, self.sub_line, self.ctx = ("pin" if mounted else "mount"), False, {}
            return
        if not self.shafts and self._mount_shape():
            self.kind, self.sub_line, self.ctx = "mount", False, {}
            return
        if not self.shafts and self.designed and all(self.role(c) == "block" for c in self.designed) and self.joints:
            self.kind, self.sub_line, self.ctx = "blocks", False, {}
            return
        ctx: dict[str, str] = {}
        host_of: dict[str, set[str]] = {}
        for sh in self.shafts:
            hosts = {self.seat_host[b][0] for b, _k, _x in self.brg[sh] if b in self.seat_host}
            host_of[sh] = hosts
            kinds = {self.comp[h].kind for h in hosts}
            if not self.brg[sh]:
                ctx[sh] = "sub"
            elif "housing" in kinds:
                ctx[sh] = "housing"
            elif kinds and (kinds <= {"pillow_block", "bracket"} or all(self._joint_to(h) is None for h in hosts)):
                ctx[sh] = "pillow"  # pillow blocks on a base, or supports standing on their own (side plates)
            elif kinds:
                raise Unsupported(f"{self.name(sh)} runs in bearings seated in a {min(kinds)}")
            else:
                ctx[sh] = "line"
        self.ctx = ctx
        blocks = [c for c in self.designed if self.role(c) == "block"]
        vals = set(ctx.values())
        if not self.shafts:
            raise Unsupported("no shafts: blocks and what is bolted to them use the standard layout")
        if "housing" in vals:
            hs = {h for sh in self.shafts for h in host_of[sh] if self.comp[h].kind == "housing"}
            if len(hs) != 1 or vals != {"housing"}:
                raise Unsupported("shafts outside the housing, or in two housings")
            self.housing = hs.pop()
            if str((self.o(self.housing)).get("layout") or "") == "row":
                raise Unsupported(f"the {self.name(self.housing)} keeps the row layout (an edit at the ICD gate)")
            other = [b for b in blocks if b != self.housing and self.comp[b].kind != "cover"]
            if other:
                raise Unsupported(f"{self.name(other[0])} beside a housing")
            if any(e["kind"] == "coupling" for e in self.edges):
                raise Unsupported("a coupling on a shaft in a housing")
            self.kind = "gearbox"
        elif "pillow" in vals:
            if vals - {"pillow"}:
                raise Unsupported("shafts in pillow blocks next to free shafts")
            self.kind = "plate"
        else:
            if blocks:
                raise Unsupported(f"{self.name(blocks[0])} next to a free shaft line")
            self.kind = "line"
        self.sub_line = self.kind == "line" and not any(self.brg[s] for s in self.shafts) and \
            not any(self.comp[c].kind == "bearing" for c in self.comp)

    # ------------------------------------------------------------------ 4. the axis graph: where each shaft runs
    def _rank(self, sh: str) -> tuple[int, int]:
        c = self.comp[sh]
        r = str(c.v("role") or "")
        cls = {"input": "input", "output": "output", "intermediate": "mid"}.get(r) or icd._line_class(c.name)
        return ({"input": 0, "mid": 1, None: 1, "output": 2}.get(cls, 1), self.shafts.index(sh))

    def _axes(self) -> None:
        order0 = sorted(self.shafts, key=self._rank)
        self.pos: dict[str, list[float]] = {}     # shaft -> [x, z] (z relative to the axis plane)
        self.anchor: dict[str, str | None] = {}
        self.via: dict[str, dict[str, Any]] = {}  # shaft -> the edge that placed it
        self.order: list[str] = []
        used_dir: dict[str, set[int]] = {}
        self.tree: set[int] = set()
        x_next = 0.0
        for start in order0:
            if start in self.pos:
                continue
            if self.order:  # a shaft no gear, belt or coupling reaches: beside the others, along +X
                x_next = max(self.pos[s][0] + self._reach(s) for s in self.order) + GAP + self._reach(start)
            self.pos[start] = [x_next, 0.0]
            first = next((e for e in self.edges if start in (e.get("a"), e.get("b")) and e["kind"] != "coupling"), None)
            self.anchor[start] = (first["ra"] if first["a"] == start else first["rb"]) if first else \
                (self.riders[start][0] if self.riders[start] else None)
            self.order.append(start)
            q = deque([start])
            while q:
                a = q.popleft()
                for n, e in enumerate(self.edges):
                    if a not in (e.get("a"), e.get("b")):
                        continue
                    b = e["b"] if e.get("a") == a else e.get("a")
                    if b is None or b in self.pos:
                        continue
                    self.tree.add(n)
                    if e["kind"] == "coupling":
                        self.pos[b] = list(self.pos[a])
                        self.anchor[b] = None
                    else:
                        free = [d for d in (1, -1) if d not in used_dir.setdefault(a, set())]
                        if not free:
                            raise Unsupported(f"{self.name(a)} drives more than two shafts (a train in two directions)")
                        used_dir[a].add(free[0])
                        used_dir.setdefault(b, set()).add(-free[0])
                        self.pos[b] = [self.pos[a][0] + free[0] * e["dist"], self.pos[a][1]]
                        self.anchor[b] = e["rb"] if e["b"] == b else e["ra"]
                    self.via[b] = e
                    self.order.append(b)
                    q.append(b)
        # every edge that closes a loop must agree with the positions the walk gave
        for n, e in enumerate(self.edges):
            if n in self.tree or e.get("a") is None:
                continue
            pa, pb = self.pos[e["a"]], self.pos[e["b"]]
            dist = math.dist(pa, pb)
            want = 0.0 if e["kind"] == "coupling" else e["dist"]
            if abs(dist - want) > 1e-6:
                path = self._path(e["a"], e["b"])
                what = {"gear_mesh": f"the mesh {self.name(e['ra'])} / {self.name(e['rb'])} needs a = {want:g} mm",
                        "belt_drive": f"the belt {self.name(e['ra'])} / {self.name(e['rb'])} is set at C = {want:g} mm",
                        "coupling": f"the coupling makes {self.name(e['a'])} and {self.name(e['b'])} coaxial"}[e["kind"]]
                self.conflict(f"{what}, but {' and '.join(self._edge_words(p) for p in path)} put the "
                              f"{self.name(e['a'])} and {self.name(e['b'])} axes {dist:g} mm apart. The loop is "
                              "over-constrained: change a size, or remove one of these connections.",
                              [e["a"], e["b"], e["ra"], e["rb"]] + [c for p in path for c in (p["ra"], p["rb"])],
                              [e["conn"].id] + [p["conn"].id for p in path])
                e["loop_bad"] = True

    def _reach(self, sh: str) -> float:
        bd = max((BEARINGS[self._des(b)][1] for b, _k, _x in self.brg[sh]), default=0.0)
        return max([self.spec[sh]["d"] / 2, bd / 2] + [self.tip(r) / 2 for r in self.riders[sh]])

    def _des(self, b: str) -> int:
        c = self.comp[b]
        des = c.v("designation")
        o = next((self.iov.get(self.item[sh]) or {} for sh in self.shafts
                  if any(x[0] == b for x in self.brg[sh])), {})
        if isinstance(o.get("designation"), int | float):
            des = int(o["designation"])
        if des is None or int(des) not in BEARINGS:
            raise Unsupported(f"{c.name} has no bearing size")
        return int(des)

    def _path(self, a: str, b: str) -> list[dict[str, Any]]:
        """The tree edges from shaft a to shaft b (the other side of a loop)."""
        adj: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for n, e in enumerate(self.edges):
            if n in self.tree and e.get("a"):
                adj.setdefault(e["a"], []).append((e["b"], e))
                adj.setdefault(e["b"], []).append((e["a"], e))
        prev: dict[str, tuple[str, dict[str, Any]] | None] = {a: None}
        q = deque([a])
        while q:
            u = q.popleft()
            for v, e in adj.get(u, []):
                if v not in prev:
                    prev[v] = (u, e)
                    q.append(v)
        out: list[dict[str, Any]] = []
        cur = b
        while prev.get(cur):
            u, e = prev[cur]  # type: ignore[misc]
            out.append(e)
            cur = u
        return out[::-1]

    def _edge_words(self, e: dict[str, Any]) -> str:
        if e["kind"] == "gear_mesh":
            return f"the mesh {self.name(e['ra'])} / {self.name(e['rb'])} (a = {e['dist']:g})"
        if e["kind"] == "belt_drive":
            return f"the belt {self.name(e['ra'])} / {self.name(e['rb'])} (C = {e['dist']:g})"
        return f"the coupling of {self.name(e['a'] or e['ra'])} and {self.name(e['b'])}"

    # ------------------------------------------------------------------ the stack along each shaft (local Y)
    def _stack(self, sh: str) -> dict[str, float]:
        """Centre Y of each rider about the shaft's anchor (0): the anchor first, the riders that meet the next
        shafts after it, then the rest, +Y; GEAR_SPACE between two gears, a collar after a hub on a shoulder."""
        nxt = []
        for e in self.edges:  # the riders that place the shafts this one reaches (the walk's next shafts)
            if e["kind"] == "coupling":
                continue
            if e["a"] == sh and self.via.get(e["b"]) is e:
                nxt.append(e["ra"])
            elif e["b"] == sh and self.via.get(e["a"]) is e:
                nxt.append(e["rb"])
        seq = list(dict.fromkeys([r for r in (self.anchor.get(sh), *nxt) if r] + self.riders[sh]))
        y: dict[str, float] = {}
        hi: float | None = None
        prev: str | None = None
        for r in seq:
            h = self.height(r)
            if hi is None:
                y[r] = 0.0
            else:
                gap = GEAR_SPACE if self.role(r) == "gear" and self.role(prev) == "gear" else 0.0
                if prev in self.stops[sh]:
                    gap = COLLAR + gap
                y[r] = hi + gap + h / 2
            hi = y[r] + h / 2 if hi is None else max(hi, y[r] + h / 2)
            prev = r
        return y

    def _offsets(self) -> None:
        """Global Y of every shaft's anchor: mesh and belt mid-planes coplanar; a coupled shaft end to end."""
        for sh in self.shafts:  # a stepped shaft with no stated stop: the hub at its +Y end bears on the step
            if self.spec[sh].get("body") and self.riders[sh] and not self.stops[sh]:
                y = self._stack(sh)
                self.stops[sh].add(max(self.riders[sh], key=lambda r: y[r] + self.height(r) / 2))
        self.local = {sh: self._stack(sh) for sh in self.shafts}
        self.yoff: dict[str, float] = {}
        for sh in self.order:
            e = self.via.get(sh)
            if e is None:
                self.yoff[sh] = 0.0
                continue
            a = e["a"] if e["b"] == sh else e["b"]
            if e["kind"] == "coupling":
                continue  # after the bearings (it needs the shaft ends)
            ra, rb = (e["ra"], e["rb"]) if e["a"] == a else (e["rb"], e["ra"])
            self.yoff[sh] = self.yoff[a] + self.local[a][ra] - self.local[sh][rb]
        for sh in self.shafts:
            self.yoff.setdefault(sh, 0.0)

    def gy(self, sh: str, r: str) -> float:
        return self.yoff[sh] + self.local[sh][r]

    def _spans(self, sh: str) -> list[tuple[float, float, str]]:
        return [(self.gy(sh, r) - self.height(r) / 2, self.gy(sh, r) + self.height(r) / 2, r) for r in self.riders[sh]]

    def _check_planes(self) -> None:
        """Loops along the axis: a mesh or belt whose two mid-planes the walk put apart."""
        for n, e in enumerate(self.edges):
            if n in self.tree or e["kind"] == "coupling" or e.get("loop_bad"):
                continue
            pa, pb = self.gy(e["a"], e["ra"]), self.gy(e["b"], e["rb"])
            if abs(pa - pb) > 1e-6:
                path = self._path(e["a"], e["b"])
                self.conflict(f"{self.name(e['ra'])} and {self.name(e['rb'])} must share a mid-plane, but "
                              f"{' and '.join(self._edge_words(p) for p in path) or 'their shafts'} put them "
                              f"{abs(pa - pb):g} mm apart along the axis.",
                              [e["ra"], e["rb"]] + [c for p in path for c in (p["ra"], p["rb"])],
                              [e["conn"].id] + [p["conn"].id for p in path])

    # ------------------------------------------------------------------ bearings and ends on free shafts
    def _near(self, sh: str) -> list[tuple[float, float]]:
        x = self.pos[sh][0]
        bd = max((BEARINGS[self._des(b)][1] for b, _k, _xx in self.brg[sh]), default=0.0)
        out = []
        for o in self.shafts:
            if o == sh or self.pos[o][1] != self.pos[sh][1]:
                continue
            for lo, hi, r in self._spans(o):
                if abs(self.pos[o][0] - x) < self.tip(r) / 2 + max(bd, self.spec[sh]["d"]) / 2 + 1.0:
                    out.append((lo, hi))
        return out

    def _free_bearings(self, sh: str, pillow: bool) -> None:
        """Two bearings either side of what turns near them; the shaft ends beyond them (or a coupling)."""
        s = self.spec[sh]
        spans = self._spans(sh)
        allsp = [(a, b) for a, b, _r in spans] + self._near(sh)
        clear = BEARING_CLEAR + (SHOULDER if pillow else 0.0)
        if allsp:
            lo, hi = min(a for a, _b in allsp), max(b for _a, b in allsp)
        else:
            span = max(BEARING_SPAN * s["seat"], 2 * max((BEARINGS[self._des(b)][1] for b, _k, _x in self.brg[sh]),
                                                          default=0.0))
            lo, hi = self.yoff[sh] - span / 2, self.yoff[sh] + span / 2
            clear = 0.0
        first = min(spans, key=lambda t: t[0])[2] if spans else None
        last = max(spans, key=lambda t: t[1])[2] if spans else None
        c_lo = (SHOULDER if pillow else 0.0) if first and self.comp[first].kind == "spacer" else clear
        c_hi = (SHOULDER if pillow else 0.0) if last and self.comp[last].kind == "spacer" else clear
        collar = last in self.stops[sh] and s.get("body") and abs(max(b for _a, b, _r in spans) - hi) < TOL
        s["collar"] = None
        if last in self.stops[sh] and s.get("body"):
            y_sh = self.gy(sh, last) + self.height(last) / 2
            s["collar"] = [_r2(y_sh), _r2(y_sh + (c_hi if collar and len(self.brg[sh]) > 1 else COLLAR))]
        pieces = self.brg[sh]
        brg: list[tuple[int, float, float, tuple[str, int]]] = []
        if pieces:
            B0 = BEARINGS[self._des(pieces[0][0])][2]
            brg.append((-1, lo - c_lo - B0, lo - c_lo, (pieces[0][0], pieces[0][1])))
        if len(pieces) > 1:
            B1 = BEARINGS[self._des(pieces[1][0])][2]
            brg.append((1, hi + c_hi, hi + c_hi + B1, (pieces[1][0], pieces[1][1])))
        s["brg"] = brg
        s["against_collar"] = bool(collar and len(pieces) > 1)
        self._ends(sh)

    def _ends(self, sh: str) -> None:
        s = self.spec[sh]
        brg = s.get("brg") or []
        own = [(a, b) for a, b, _r in self._spans(sh)]
        end = max(SHAFT_END, 0.5 * s["seat"])
        outer_lo = min([b0 for _sd, b0, _b1, _p in brg] + [a for a, _b in own] + [self.yoff[sh]])
        outer_hi = max([b1 for _sd, _b0, b1, _p in brg] + [b for _a, b in own] + [self.yoff[sh]])
        if s.get("collar"):
            outer_hi = max(outer_hi, s["collar"][1])
        y0, y1 = outer_lo - end, outer_hi + end
        for e in self.edges:
            if e["kind"] != "coupling" or e.get("loop_bad"):
                continue
            if e["b"] == sh:  # the coupling at the -Y end
                y0 = outer_lo - BEARING_CLEAR - e["eng"]
            elif e["a"] == sh:
                y1 = outer_hi + BEARING_CLEAR + e["eng"]
        if "length" not in self.o(sh):
            s["length"] = _r2(max(y1 - y0, float(s.get("length") or 0.0)))
            s["y0"] = _r2((y0 + y1) / 2 - s["length"] / 2)
        else:
            s["y0"] = _r2((y0 + y1) / 2 - float(s["length"]) / 2)
        if any(e["kind"] == "coupling" and e["b"] == sh for e in self.edges):
            s["y0"] = _r2(y0)  # the coupled end stays where the coupling needs it
        s["y1"] = _r2(s["y0"] + float(s["length"]))

    def _couple(self) -> None:
        """Coupled shafts end to end (in walk order): the coupled shaft and every shaft the walk reached through it
        move along +Y together, so their mesh planes stay shared."""
        for sh in self.order:
            e = self.via.get(sh)
            if e is None or e["kind"] != "coupling" or e.get("a") is None:
                continue
            delta = self.spec[e["a"]]["y1"] + COUPLING_GAP - self.spec[sh]["y0"]
            for d in self._below(sh):
                self._move(d, delta)

    def _below(self, sh: str) -> list[str]:
        out = [sh]
        for o in self.order:
            e = self.via.get(o)
            if e is not None and o not in out and ({e.get("a"), e.get("b")} - {o}) & set(out):
                out.append(o)
        return out

    def _move(self, sh: str, delta: float) -> None:
        s = self.spec[sh]
        self.yoff[sh] += delta
        for k in ("y0", "y1"):
            if s.get(k) is not None:
                s[k] = _r2(s[k] + delta)
        s["brg"] = [(sd, b0 + delta, b1 + delta, p) for sd, b0, b1, p in s.get("brg") or []]
        if s.get("collar"):
            s["collar"] = [_r2(s["collar"][0] + delta), _r2(s["collar"][1] + delta)]

    def _place_couplings(self, z_of: dict[str, float]) -> None:
        """The coupling across the joint: its centre half the gap before the driven shaft's end."""
        for e in self.edges:
            if e["kind"] == "coupling" and e.get("via") and not e.get("loop_bad"):
                sh = e["b"]
                self.spec[e["via"]]["ax"] = "y"
                self.at[e["via"]] = [[_r2(self.pos[sh][0]), _r2(self.spec[sh]["y0"] - COUPLING_GAP / 2),
                                      _r2(z_of[sh])]]

    # ------------------------------------------------------------------ 5a. a free shaft line / sub-assembly
    def _line(self) -> None:
        self._offsets()
        self._check_planes()
        for sh in self.order:
            if self.brg[sh] or not self.spec[sh].get("body"):
                self._free_bearings(sh, pillow=False)
            else:
                self._stepped_sub(sh)
        self._couple()
        for sh in self.shafts:  # the axes lie in the plane Z = 0 (datum A)
            self.spec[sh]["ax"] = "y"
            for r in self.riders[sh]:
                self.spec[r]["ax"] = "y"
        if len(self.shafts) == 1 and self.spec[self.shafts[0]].get("shoulder_z") is not None and self.sub_line:
            sh = self.shafts[0]
            dy = -float(self.spec[sh]["shoulder_z"])
            self._shift_y(sh, dy)
        self._place_line()

    def _shift_y(self, sh: str, dy: float) -> None:
        s = self.spec[sh]
        self.yoff[sh] += dy
        for k in ("y0", "y1", "shoulder_z"):
            if s.get(k) is not None:
                s[k] = _r2(float(s[k]) + dy)
        if s.get("seat_z"):
            s["seat_z"] = [_r2(s["seat_z"][0] + dy), _r2(s["seat_z"][1] + dy)]

    def _stepped_sub(self, sh: str) -> None:
        """A stepped shaft with no bearings (a sub-assembly, the template's rule): the hubs on the seat from SEAT_END
        beyond the free hub face to the shoulder; the larger step (the body) runs on from the shoulder."""
        s = self.spec[sh]
        own = [(a, b) for a, b, _r in self._spans(sh)]
        if not own:
            return self._free_bearings(sh, pillow=False)
        olo, ohi = min(a for a, _b in own), max(b for _a, b in own)
        stopped = [r for r in self.riders[sh] if r in self.stops[sh]]
        if not stopped:  # stepped (written) with nothing on the shoulder: the shoulder at the +Y hub face
            stopped = [max(self.riders[sh], key=lambda r: self.gy(sh, r))]
            self.stops[sh].add(stopped[0])
        y0 = olo - SEAT_END
        need = ohi - y0 + 1.0
        body_l = max(ohi - olo + SHAFT_END, 2.0 * s["seat"])
        given = float(s.get("length") or 0.0)
        L = max(given, need) if given > 0 and "length" not in self.o(sh) else (
            float(s["length"]) if "length" in self.o(sh) else (ohi - y0) + body_l)
        s["length"], s["y0"], s["y1"] = _r2(L), _r2(y0), _r2(y0 + L)
        s["brg"], s["collar"] = [], None
        s["shoulder_z"] = _r2(ohi)
        s["seat_z"] = [_r2(y0), _r2(ohi)]
        s["sub_stepped"] = True

    def _place_line(self) -> None:
        for sh in self.shafts:
            s = self.spec[sh]
            x, z = self.pos[sh]
            self.at[sh] = [[_r2(x), _r2((s["y0"] + s["y1"]) / 2), _r2(z)]]
            for r in self.riders[sh]:
                self.at[r] = [[_r2(x), _r2(self.gy(sh, r)), _r2(z)]]
            self._seat_spans(sh)
        self._place_couplings({sh: self.pos[sh][1] for sh in self.shafts})

    def _seat_spans(self, sh: str) -> None:
        """A stepped shaft: the seat Ø runs from the end (or the journal before it) to the shoulder."""
        s = self.spec[sh]
        if not s.get("body") or s.get("sub_stepped"):
            return
        stopped = [r for r in self.riders[sh] if r in self.stops[sh]]
        if not stopped:
            return
        r = stopped[0]
        sz = self.gy(sh, r) + self.height(r) / 2
        s["shoulder_z"] = _r2(sz)
        lo = s["y0"]
        brg = s.get("brg") or []
        lo_b = [b for b in brg if b[0] < 0]
        if lo_b and (BEARINGS[self._des(lo_b[0][3][0])][0] < s["seat"] - TOL or abs(lo_b[0][1] - lo) < TOL):
            lo = lo_b[0][2]  # a smaller journal, or a bearing flush with the end: the seat starts at its inner face
        s["seat_z"] = [_r2(lo), _r2(sz)]

    # ------------------------------------------------------------------ 5b. shafts in pillow blocks on a plate
    def _plate(self) -> None:
        self._offsets()
        self._check_planes()
        for sh in self.order:
            self._free_bearings(sh, pillow=True)
        self._couple()
        for sh in self.shafts:
            self.spec[sh]["ax"] = "y"
            for r in self.riders[sh]:
                self.spec[r]["ax"] = "y"
        # the base: the block every other block is bolted to, in the end
        parent: dict[str, tuple[str, Connection]] = {}
        for x in self.joints:
            if self.role(x.host) == "block" and self.role(x.guest) == "block" and x.guest not in parent:
                parent[x.guest] = (x.host, x)
        blocks = [c for c in self.designed if self.role(c) == "block"]
        roots = [b for b in blocks if b not in parent]
        pbs = sorted({self.seat_host[b][0] for sh in self.shafts for b, _k, _x in self.brg[sh]}, key=self.designed.index)
        self.parent = parent
        motors = [e for e in self.edges if e["kind"] == "coupling" and e.get("motor")]
        self.motor_edges = motors
        # supports standing on their own (side plates, no frame in the design): the shaft is the base, the supports
        # are centred on their bearings, the axis is datum A (Z = 0)
        self.frameless = bool(roots) and all(r in pbs for r in roots)
        if self.frameless:
            if motors:
                raise Unsupported("a motor beside supports that stand on nothing")
            self.base = min(self.shafts, key=self._rank)
            for pb in pbs:  # a plate carrying a bearing stands across the shaft: its thickness along the axis
                s = self.spec[pb]
                if self.comp[pb].kind == "plate":
                    s["L"], s["W"], s["H"] = s["L"], s["H"], s["W"]
                    s["given"] = {{"W": "H", "H": "W"}.get(k, k) for k in s["given"]}
                    if s.get("planned"):
                        s["planned"] = [s["planned"][0], s["planned"][2], s["planned"][1]]
            self.h = 0.0
            self._place_supports(pbs)
            for sh in self.shafts:
                s = self.spec[sh]
                x = self.pos[sh][0]
                self.at[sh] = [[_r2(x), _r2((s["y0"] + s["y1"]) / 2), 0.0]]
                for r in self.riders[sh]:
                    self.at[r] = [[_r2(x), _r2(self.gy(sh, r)), 0.0]]
                self._seat_spans(sh)
            self._place_couplings({sh: 0.0 for sh in self.shafts})
            self.cy = 0.0
            return
        plates = [b for b in roots if self.comp[b].kind == "plate"] or roots
        if len(plates) != 1:
            raise Unsupported("the shafts' supports stand on more than one base")
        self.base = plates[0]
        for pb in pbs:
            if parent.get(pb, (None,))[0] != self.base:
                raise Unsupported(f"{self.name(pb)} is not bolted to the base plate")
        # heights: every path from the plate to an axis must agree (the axes of coupled / belted shafts coincide)
        need: list[tuple[float, str]] = []   # (the least axis height a path allows, why)
        fixed: list[tuple[float, str, list[str]]] = []
        for sh in self.shafts:
            r = max([self.spec[sh]["seat"] / 2] + [self.tip(x) / 2 for x in self.riders[sh]]
                    + [self.spec[e["via"]]["OD"] / 2 for e in self.edges if e["kind"] == "coupling" and e.get("via")
                       and sh in (e["a"], e["b"])])
            need.append((r + CAV, f"what turns on {self.name(sh)} clears the plate"))
        for pb in pbs:
            D = max(BEARINGS[self._des(b)][1] for b in self._pb_bearings(pb))
            wall = max(PB_WALL_MIN, PB_WALL * D)
            need.append((D / 2 + wall, f"{self.name(pb)} carries its seat"))
            c = self.comp[pb]  # heights the design states fix the axis (a size frozen at approval is a size)
            if c.v("centre_height") is not None:
                fixed.append((float(c.v("centre_height")), f"{self.name(pb)} centre height", [pb]))
            elif c.v("H") is not None:
                fixed.append((float(c.v("H")) - D / 2 - wall, f"{self.name(pb)} height", [pb]))
        for e in motors:
            m = e["motor"]
            ms = self.spec[m]
            br = self._bracket(m)
            need.append((ms["H"] / 2 + (BRACKET_MIN if br else 0.0), f"{self.name(m)} stands on its bracket"))
            if br and self.comp[br].v("H") is not None:
                fixed.append((float(self.comp[br].v("H")) + ms["H"] / 2, f"{self.name(br)} height", [br, m]))
            elif not br:
                fixed.append((ms["H"] / 2, f"{self.name(m)} on the plate", [m]))
        hmin = max(v for v, _w in need)
        h = hmin
        if fixed:
            h = fixed[0][0]
            for v, why, who in fixed[1:]:
                if abs(v - h) > 1e-6:
                    self.conflict(f"{fixed[0][1]} puts the shaft axis {h:g} mm above the plate, {why} puts it "
                                  f"{v:g} mm: the axes must coincide. State one of them, not both.",
                                  fixed[0][2] + who + [sh for sh in self.shafts],
                                  [e["conn"].id for e in motors] + [x.id for x in self.joints])
            if h < hmin - 1e-6:
                v, why = max(need)
                self.conflict(f"{fixed[0][1]} puts the shaft axis {h:g} mm above the plate, but {why} needs at "
                              f"least {v:g} mm.", fixed[0][2] + list(self.shafts), [x.id for x in self.joints])
                h = hmin
        self.h = _r2(h)
        self._place_supports(pbs)
        self._plate_rest(motors, parent)

    def _place_supports(self, pbs: list[str]) -> None:
        """Pillow blocks (or side plates): centred on their bearing, the seat open outboard, the shoulder wall
        inboard; on the plate (bolt feet either side) or, standing on their own, centred on the axis."""
        self.pb_of: dict[tuple[str, int], tuple[str, int]] = {}  # (pillow block, copy) -> (bearing, piece)
        self.pb_seat: dict[tuple[str, int], dict[str, Any]] = {}
        used: dict[str, int] = {}
        for sh in self.shafts:
            x = self.pos[sh][0]
            for sd, b0, b1, (b, k) in self.spec[sh]["brg"]:
                pb = self.seat_host[b][0]
                n = used.get(pb, 0)
                used[pb] = n + 1
                if n >= self.ncopies(pb):
                    self.conflict(f"{self.name(pb)}: {n + 1} bearings to carry but {self.comp[pb].qty} planned.",
                                  [pb, b, sh], [self.seat_host[b][1].id])
                    continue
                _bd, D, B = BEARINGS[self._des(b)]
                s = self.spec[pb]
                wall = max(PB_WALL_MIN, PB_WALL * D)
                m = self._fastener(self._joint_to(pb), 2 * D)
                inset = max(2 * CLEARANCE[m], 6.0)
                Ws = B + SHOULDER
                Hs = _up((self.h + D / 2 + wall) if not self.frameless else D + 2 * wall, 0.5)
                Ls = _up(D + 2 * wall + (4 * inset if not self.frameless else 0.0), 0.5)
                for key, v in (("L", Ls), ("W", Ws), ("H", Hs)):
                    if key not in s["given"]:
                        s[key] = _r2(max(v, float(s[key]) if n else v))
                # every copy of one support is the same part: the seat opens toward -Y on each (the +Y bearing goes in
                # from the inboard side, against a shoulder outboard), so one design serves both
                y_lo, y_hi = b0, (b0 + float(s["W"])) if "W" in s["given"] else b1 + SHOULDER
                self.at.setdefault(pb, [None] * self.ncopies(pb))
                self.at[pb][n] = [_r2(x), _r2((y_lo + y_hi) / 2), 0.0 if self.frameless else _r2(float(s["H"]) / 2)]
                self.pb_of[(pb, n)] = (b, k)
                self.pb_seat[(pb, n)] = {"shaft": sh, "side": sd, "z": [_r2(y_lo), _r2(y_hi)], "seat": [_r2(b0), _r2(b1)],
                                         "des": self._des(b)}
                s["ax_hint"] = "y"

    def _plate_rest(self, motors: list[dict[str, Any]], parent: dict[str, tuple[str, Connection]]) -> None:
        # the motor and its bracket: coaxial with the shaft it drives, its +Y face behind the coupling
        for e in motors:
            m, sh = e["motor"], e["b"]
            ms = self.spec[m]
            face = self.spec[sh]["y0"] - COUPLING_GAP - float(ms["shaft_length"])
            x = self.pos[sh][0]
            self.at[m] = [[_r2(x), _r2(face - ms["W"] / 2), _r2(self.h)]]
            e["motor_end"] = _r2(self.spec[sh]["y0"] - COUPLING_GAP)
            br = self._bracket(m)
            if br:
                bs = self.spec[br]
                if "H" not in bs["given"]:
                    bs["H"] = _r2(self.h - ms["H"] / 2)
                # the motor's footprint, and a flange either side across the shaft for the bracket's own bolts (two
                # insets of its bolt each side), so they don't meet the motor's bolts
                bs["joint_span"] = min(float(ms["L"]), float(ms["W"]))
                mb = self._fastener(self._joint_to(br), bs["joint_span"])
                flange = 2 * max(2 * CLEARANCE[mb], 6.0)
                for key, v in (("L", float(ms["L"]) + 2 * flange), ("W", ms["W"])):
                    if key not in bs["given"]:
                        bs[key] = _up(v, 0.5)
                self.at[br] = [[_r2(x), _r2(face - ms["W"] / 2), _r2(float(bs["H"]) / 2)]]
        for sh in self.shafts:
            s = self.spec[sh]
            x = self.pos[sh][0]
            self.at[sh] = [[_r2(x), _r2((s["y0"] + s["y1"]) / 2), self.h]]
            for r in self.riders[sh]:
                self.at[r] = [[_r2(x), _r2(self.gy(sh, r)), self.h]]
            self._seat_spans(sh)
        self._place_couplings({sh: self.h for sh in self.shafts})
        # the plate: under everything, centred on what it carries; grown to it unless its size is stated
        lo = [math.inf, math.inf]
        hi = [-math.inf, -math.inf]
        for cid, cps in self.at.items():
            if cid == self.base:
                continue
            s = self.spec[cid]
            for c in cps:
                if c is None:
                    continue
                if s["role"] == "block":
                    ex, ey = float(s["L"]) / 2, float(s["W"]) / 2
                elif s["role"] == "shaft":
                    ex, ey = float(s["d"]) / 2, float(s["length"]) / 2
                else:
                    ex, ey = self.tip(cid) / 2, self.height(cid) / 2
                lo = [min(lo[0], c[0] - ex), min(lo[1], c[1] - ey)]
                hi = [max(hi[0], c[0] + ex), max(hi[1], c[1] + ey)]
        cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        bs = self.spec[self.base]
        need_L, need_W = hi[0] - lo[0] + 2 * MARGIN, hi[1] - lo[1] + 2 * MARGIN
        for key, v in (("L", need_L), ("W", need_W)):
            if key in bs["given"] and float(bs[key]) < v - 1e-6:
                self.conflict(f"{self.name(self.base)} is stated {float(bs[key]):g} mm {'long' if key == 'L' else 'wide'}"
                              f", but what it carries needs {_r2(v):g} mm (with {MARGIN:g} mm margins).",
                              [self.base], [x.id for x in self.joints if x.host == self.base])
            elif key not in bs["given"]:
                bs[key] = _up(v, 1.0)
        for cid, cps in self.at.items():
            self.at[cid] = [None if c is None else [_r2(c[0] - cx), _r2(c[1] - cy), c[2]] for c in cps]
        for sh in self.shafts:
            self.pos[sh][0] -= cx
            self._shift_y(sh, -cy)
            s = self.spec[sh]
            s["brg"] = [(sd, b0 - cy, b1 - cy, p) for sd, b0, b1, p in s.get("brg") or []]
            if s.get("collar"):
                s["collar"] = [_r2(s["collar"][0] - cy), _r2(s["collar"][1] - cy)]
        for v in self.pb_seat.values():
            v["z"] = [_r2(v["z"][0] - cy), _r2(v["z"][1] - cy)]
            v["seat"] = [_r2(v["seat"][0] - cy), _r2(v["seat"][1] - cy)]
        for e in motors:
            if e.get("motor_end") is not None:
                e["motor_end"] = _r2(e["motor_end"] - cy)
        self.at[self.base] = [[0.0, 0.0, -float(bs["H"]) / 2]]
        self.cy = cy

    def _bracket(self, m: str) -> str | None:
        """The block a motor stands on, when it isn't the base plate itself."""
        br = self.parent.get(m, (None,))[0]
        return br if br is not None and br != self.base else None

    def _pb_bearings(self, pb: str) -> list[str]:
        return [b for b, (h, _x) in self.seat_host.items() if h == pb]

    def _joint_to(self, guest: str, host: str | None = None) -> Connection | None:
        return next((x for x in self.joints if x.guest == guest and (host is None or x.host == host)), None)

    def _fastener(self, x: Connection | None, span: float) -> int:
        """M size of a bolted joint: the via fastener's stated size, else the layout rule for the span."""
        for v in (x.via if x else []):
            c = self.comp.get(v)
            if c is not None and c.kind == "fastener" and c.v("size") and int(c.v("size")) in CLEARANCE:
                return int(c.v("size"))
        return icd.fastener_for(span)

    def _fastener_item(self, x: Connection | None) -> str | None:
        for v in (x.via if x else []):
            c = self.comp.get(v)
            if c is not None and c.kind == "fastener":
                return self.item[v]
        return None

    # ------------------------------------------------------------------ 5c. the gearbox: shafts in a housing
    def _gearbox(self) -> None:
        self._offsets()
        self._check_planes()
        h = self.housing
        s, o = self.spec[h], self.o(h)
        hs = sorted(self.shafts, key=lambda sh: self.pos[sh][0])
        for sh in hs:
            if self.pos[sh][1] != 0.0:
                raise Unsupported("housing shafts off one plane")
        xs = [self.pos[sh][0] - self.pos[hs[0]][0] for sh in hs]
        for n in range(1, len(hs)):  # shafts that don't mesh: apart by their reach (the template's rule)
            if not any({e["a"], e["b"]} == {hs[n - 1], hs[n]} for e in self.edges):
                pass
        rel, rr = [], []
        for sh in hs:
            sp = self._spans(sh)
            rel.append((min([a for a, _b, _r in sp] + [0.0]), max([b for _a, b, _r in sp] + [0.0])))
            rr.append(max([self.spec[sh]["seat"] / 2] + [self.tip(r) / 2 for r in self.riders[sh]]))
        D = [BEARINGS[self._des(self.brg[sh][0][0])][1] for sh in hs]
        hm: dict[str, Any] = {"shafts": hs, "rel": rel, "r": rr, "xs": xs, "D": D}
        # caps: which cap goes over which seat (open where the shaft leaves the housing, EXIT_SIDE; by name class)
        seats_at = [(n, side) for n, sh in enumerate(hs) for side in ((-1, 1) if len(self.brg[sh]) >= 2 else (-1,))]
        cap_joints = [x for x in self.joints if x.host == h and self.comp[x.guest].kind == "bearing_cap"]
        cap_sts = [(self.item[x.guest], c) for x in cap_joints for c in range(self.ncopies(x.guest))]
        by_id = {p["id"]: p for p in self.parts}
        assign = icd._assign_caps(cap_sts, seats_at, [self.name(sh) for sh in hs], D, by_id) if cap_sts else []
        caps: list[tuple[tuple[str, int], int, int]] = []
        cap_m, cap_item = 0, None
        if assign:
            by_cap: dict[str, list[int]] = {}
            for j, st in assign:
                by_cap.setdefault(st[0], []).append(j)
            at_seat = {seats_at[j]: st[0] for j, st in assign}
            x0 = cap_joints[0]
            Dall = max(D[seats_at[j][0]] for j, _st in assign)
            want = self._fastener(x0, 0.6 * Dall)
            for m in sorted((x for x in CLEARANCE if x <= max(want, 3)), reverse=True):
                lig = max(LIGAMENT, LIGAMENT_D * m)
                size: dict[str, tuple[float, float, float]] = {}
                for ci, js in by_cap.items():
                    Dc = max(D[seats_at[j][0]] for j in js)
                    pcd = math.ceil(2 * (Dc + TAP_DRILL[m] + 2 * lig) - 1e-9) / 2
                    co = self.iov.get(ci) or {}
                    size[ci] = (Dc, pcd, float(co["OD"]) if "OD" in co else _r2(pcd + WASHER_OD[m]))
                fits = all(OD >= pcd + CLEARANCE[m] + 2.0 for _Dc, pcd, OD in size.values())
                for n in range(1, len(hs)):
                    for sd in (-1, 1):
                        a, b = at_seat.get((n - 1, sd)), at_seat.get((n, sd))
                        if a and b and size[a][2] / 2 + size[b][2] / 2 + 1.0 > xs[n] - xs[n - 1] + 1e-9:
                            fits = False
                if not fits:
                    continue
                cap_m, cap_item = m, self._fastener_item(x0)
                for ci, (Dc, pcd, OD) in size.items():
                    cid = self.cid_of[ci]
                    cs, co = self.spec[cid], self.iov.get(ci) or {}
                    cs.update(OD=OD, od_given=True, pcd=_r2(pcd), cap_d=Dc)
                    if "H" not in co and cs["source"] == "assumed":
                        cs["H"] = float(round(max(8.0, 0.25 * Dc)))
                    through = [self._exit_d(hs[seats_at[j][0]]) for j in by_cap[ci] if seats_at[j][1] == EXIT_SIDE]
                    style = self.comp[cid].v("style") or icd._cap_kind(self.p(cid))
                    if through and style != "blind":
                        cs["bore"] = _r2(max(through) + 2.0)
                        cs["cap"] = "open"
                    else:
                        cs.pop("bore", None)
                        cs["cap"] = "blind"
                    cs["relief"] = _r2(max((BEARINGS[self._des(self.brg[hs[seats_at[j][0]]][0][0])][0]
                                            + D[seats_at[j][0]]) / 2 for j in by_cap[ci]))
                caps = sorted(((st, seats_at[j][0], seats_at[j][1]) for j, st in assign),
                              key=lambda x: seats_at.index((x[1], x[2])))
                break
            missing = [seats_at[j] for j in range(len(seats_at)) if seats_at[j] not in at_seat]
            if missing:
                self.notes.append(f"{len(missing)} bearing seat{'s' if len(missing) != 1 else ''} without a cap in the "
                                  "design (" + ", ".join(f"{'+' if sd > 0 else '-'}Y seat of the {self.name(hs[n])}"
                                                         for n, sd in missing) + ").")
        if cap_sts and not caps:
            for x in cap_joints:
                self.conflict(f"{self.name(x.guest)} is bolted over a bearing seat of {self.name(h)}, but no cap fits "
                              "over the seats at these shaft centres.", [x.guest, h], [x.id])
        elif caps:
            lig = max(LIGAMENT, LIGAMENT_D * cap_m)
            self.notes.append("Bearing caps: " + "; ".join(
                f"{self.name(self.cid_of[st[0]])} ({self.spec[self.cid_of[st[0]]]['cap']}) over the "
                f"{'+' if sd > 0 else '-'}Y seat of the {self.name(hs[n])}" for st, n, sd in caps)
                + f". Cap screws M{cap_m} in tapped holes (tap drill Ø{TAP_DRILL[cap_m]:g}) in the walls, on a PCD "
                f"of seat Ø + tap drill + 2 × {lig:g} mm: at least {lig:g} mm of wall between the seat and each "
                "tapped hole.")
        hm.update(caps=caps, cap_m=cap_m, cap_item=cap_item)
        lid_x = next((x for x in self.joints if x.host == h and self.comp[x.guest].kind == "cover"), None)
        hm["lid"] = lid_x.guest if lid_x is not None else None
        hm["lid_x"] = lid_x
        self.hm = hm
        # the casing around the gear row (the template's sizing rule, icd.build size_housing)
        B = max(BEARINGS[self._des(self.brg[sh][0][0])][2] for sh in hs)
        caps_od = max([self.spec[self.cid_of[st[0]]]["OD"] for st, _n, _s in caps] or [0.0])
        t = max(B + SHOULDER, icd.tap_depth(cap_m) + 3.0 if caps else 0.0, 12.0)
        half_in = max(max(-lo, hi) for lo, hi in rel) + CAV_Y
        rmax, Dmax = max(rr), max(D)
        lo_x = min(x - r for x, r in zip(xs, rr, strict=True)) - CAV
        hi_x = max(x + r for x, r in zip(xs, rr, strict=True)) + CAV
        mid = (lo_x + hi_x) / 2
        above = max(CAV + rmax, caps_od / 2 + 2.0, Dmax / 2 + 3.0)
        below = max(FLOOR + CAV + rmax, caps_od / 2 + 2.0, Dmax / 2 + 3.0)
        for _ in range(2):
            W = 2 * (half_in + t)
            if hm["lid"]:
                lm = self._fastener(lid_x, min(W, 2 * (max(hi_x - mid, mid - lo_x) + t)))
                lm = lm if lm in CLEARANCE else 6
                t = max(t, 2.5 * CLEARANCE[lm] + 1.5, icd.tap_depth(lm) - 6.0)
        reach = max(max(abs(x - mid) + caps_od / 2 + 2.0, abs(x - mid) + Dmax / 2 + 3.0) for x in xs)
        need = {"L": 2 * max(hi_x - mid + t, mid - lo_x + t, reach), "W": 2 * (half_in + t), "H": above + below}
        for k, v in need.items():
            if k in o:
                continue
            s[k] = _r2(v) if s["source"] == "assumed" else _r2(max(float(s[k]), v))
        hm.update(t=_r2(t), mid=mid, above=_r2(above + (s["H"] - need["H"]) / 2), half_in=_r2(s["W"] / 2 - t))
        hm["end_t"] = _r2(s["L"] / 2 - max(hi_x - mid, mid - lo_x))
        if hm["lid"]:
            ls, lo_ = self.spec[hm["lid"]], self.o(hm["lid"])
            if "L" not in lo_:
                ls["L"], ls["W"] = s["L"], s["W"]
        # positions: the housing's top face is datum A; shafts from the -Y outer face (flush) through the +Y wall
        cz = -float(s["H"]) / 2
        self.at[h] = [[0.0, 0.0, _r2(cz)]]
        top = 0.0
        za = top - hm["above"]
        y0, y1 = -float(s["W"]) / 2, float(s["W"]) / 2
        hm.update(za=za, y0=y0, y1=y1)
        cap_h = max([self.spec[self.cid_of[st[0]]]["H"] for st, _n, side in caps if side > 0] or [0.0])
        for n, sh in enumerate(hs):
            ks = self.spec[sh]
            x = xs[n] - mid
            self.pos[sh] = [x, za]
            if "length" not in self.o(sh):
                ks["length"] = _r2(max(float(ks.get("length") or 0.0), s["W"] + cap_h + max(15.0, ks["seat"])))
            ks["y0"], ks["y1"] = _r2(y0), _r2(y0 + float(ks["length"]))
            ks["ax"] = "y"
            pieces = self.brg[sh]
            des = [self._des(b) for b, _k, _x in pieces]
            brg = [(-1, y0, y0 + BEARINGS[des[0]][2], (pieces[0][0], pieces[0][1]))]
            if len(pieces) > 1:
                brg.append((1, y1 - BEARINGS[des[1]][2], y1, (pieces[1][0], pieces[1][1])))
            ks["brg"] = brg
            self.at[sh] = [[_r2(x), _r2(y0 + float(ks["length"]) / 2), _r2(za)]]
            for r in self.riders[sh]:
                self.spec[r]["ax"] = "y"
                self.at[r] = [[_r2(x), _r2(self.gy(sh, r)), _r2(za)]]
            ks["collar"] = None
            stopped = [r for r in self.riders[sh] if r in self.stops[sh]]
            if stopped and ks.get("body"):
                yy = self.gy(sh, stopped[0]) + self.height(stopped[0]) / 2
                ks["collar"] = [_r2(yy), _r2(yy + COLLAR)]
                if yy + COLLAR > hm["half_in"] - 1.0 + 1e-9:
                    self.conflict(f"the shoulder of {self.name(sh)} behind {self.name(stopped[0])} reaches into the "
                                  f"{self.name(h)} wall.", [sh, stopped[0], h],
                                  [x.id for x in self.g.connections if x.kind == "shoulder_stop" and x.host == sh])
            self._seat_spans(sh)
        for (ci, cc), n, side in caps:
            cid = self.cid_of[ci]
            hc = float(self.spec[cid]["H"])
            yy = (y0 - hc / 2) if side < 0 else (y1 + hc / 2)
            self.spec[cid]["ax"] = "y"
            self.at.setdefault(cid, [None] * self.ncopies(cid))
            self.at[cid][cc] = [_r2(xs[n] - mid), _r2(yy), _r2(za)]
        if hm["lid"]:
            ls = self.spec[hm["lid"]]
            self.at[hm["lid"]] = [[0.0, 0.0, _r2(top + float(ls["H"]) / 2)]]
        self.base = h

    def _exit_d(self, sh: str) -> float:
        """The shaft Ø where it leaves the housing (the +Y journal, which runs to the end on a stepped shaft)."""
        s = self.spec[sh]
        if s.get("body"):
            return float(BEARINGS[self._des(self.brg[sh][-1][0])][0]) if self.brg[sh] else s["seat"]
        return float(s["seat"])

    # ------------------------------------------------------------------ 5d. guide rods in end blocks, a carriage on them
    def foot(self, cid: str) -> tuple[float, float]:
        """A block's footprint in the program frame (X, Y): its L x W, or W x L when turned a quarter."""
        s = self.spec[cid]
        return (float(s["W"]), float(s["L"])) if s.get("rot") in (90, 270) else (float(s["L"]), float(s["W"]))

    def _turn_along_y(self, cid: str) -> None:
        """A block whose shorter side runs along the rods (an end block, a carriage): a quarter turn, so that side
        lies along +Y (the rods' axis). An edit or a frozen turn at the ICD gate wins."""
        s, o = self.spec[cid], self.o(cid)
        if "rot" in o:
            s["rot"] = int(o["rot"]) % 360
        elif float(s["L"]) < float(s["W"]) - TOL:
            s["rot"] = 90

    def _guide(self) -> None:
        """Parallel rods along +Y, held at both ends in end blocks on the base, a carriage sliding on them: the rods
        at the stated spacing (else the end block's width / 2), symmetric about X = 0, at the stated height above the
        base (else half the end block's height); each rod's ends flush with its blocks' outer faces; the carriage
        centred between the blocks unless the design places it."""
        rods = sorted(self.shafts, key=self._rank)
        hosts: list[str] = list(dict.fromkeys(x.host for x in self.rod_x))
        carriages = list(dict.fromkeys(x.guest for x in self.slide_x))
        parent: dict[str, tuple[str, Connection]] = {}
        for x in self.joints:
            if self.role(x.host) == "block" and self.role(x.guest) == "block" and x.guest not in parent:
                parent[x.guest] = (x.host, x)
        self.parent = parent
        roots = [b for b in self.designed if self.role(b) == "block" and b not in parent and b not in carriages]
        if len(roots) != 1 or any(parent.get(h, (None,))[0] != roots[0] for h in hosts):
            raise Unsupported("the rods' end blocks are not on one base")
        self.base = roots[0]
        for c in hosts + carriages:
            self._turn_along_y(c)
        spacing = next((float(x.v("spacing")) for x in self.rod_x if x.v("spacing")), None)
        height = next((float(x.v("height")) for x in self.rod_x if x.v("height")), None)
        b0 = hosts[0]
        bx, by = self.foot(b0)
        if spacing is None:
            spacing = _r2(bx / 2)
        if height is None:
            height = _r2(float(self.spec[b0]["H"]) / 2)
        t = by  # the block's thickness along the rods
        copies = [(r, k) for r in rods for k in range(self.ncopies(r))]  # (a "Guide rod" x 2 is two rods)
        n = len(copies)
        self.h = height
        for r in rods:
            s = self.spec[r]
            L = float(s.get("length") or 0.0)
            if not L:
                cl = max((self.foot(c)[1] for c in carriages), default=0.0)
                L = _r2(3 * cl + 2 * t) if cl else _r2(6 * t)
                s["length"] = L
            s["ax"], s["y0"], s["y1"], s["brg"] = "y", _r2(-L / 2), _r2(L / 2), []
            self.at[r] = [None] * self.ncopies(r)
        for j, (r, k) in enumerate(copies):
            x = _r2((j - (n - 1) / 2) * spacing)
            self.at[r][k] = [x, 0.0, height]
            if k == 0:
                self.pos[r] = [x, height]
        self.rod_copies = copies
        L = float(self.spec[rods[0]]["length"])
        self.rod_ends = (-L / 2, L / 2)
        for h in hosts:  # copy 0 at the -Y ends, copy 1 at the +Y ends (one block holds every rod at its end)
            hx, hy = self.foot(h)
            hs = self.spec[h]
            self.at[h] = [[0.0, _r2(-L / 2 + hy / 2), _r2(float(hs["H"]) / 2)],
                          [0.0, _r2(L / 2 - hy / 2), _r2(float(hs["H"]) / 2)]][:self.ncopies(h)]
            if height + float(self.spec[rods[0]]["d"]) / 2 > float(hs["H"]) - 1.0 + TOL or \
                    abs(spacing) * (n - 1) / 2 + float(self.spec[rods[0]]["d"]) / 2 > hx / 2 - 1.0 + TOL:
                self.conflict(f"the rods (Ø{self.spec[rods[0]]['d']:g}, {spacing:g} apart, {height:g} above the base) "
                              f"don't fit in {self.name(h)} ({hx:g} x {float(hs['H']):g}).", [h] + rods,
                              [x.id for x in self.rod_x if x.host == h])
        for c in carriages:
            cs = self.spec[c]
            self.at[c] = [[0.0, 0.0, _r2(height)]]
            _cx, cy_ = self.foot(c)
            if cy_ > L - 2 * t + TOL:
                self.conflict(f"{self.name(c)} ({cy_:g} along the rods) doesn't fit between the end blocks "
                              f"({L - 2 * t:g} mm apart).", [c] + hosts, [x.id for x in self.slide_x if x.guest == c])
            if height - float(cs["H"]) / 2 < -TOL:
                self.conflict(f"{self.name(c)} reaches below the base.", [c, self.base],
                              [x.id for x in self.slide_x if x.guest == c])
        # the base: under everything; turned when its long side must run along the rods; grown unless stated
        bs = self.spec[self.base]
        ext_x = max([self.foot(h)[0] for h in hosts] + [self.foot(c)[0] for c in carriages]
                    + [abs(spacing) * (n - 1) + float(self.spec[rods[0]]["d"])])
        ext_y = L
        bL, bW = float(bs["L"]), float(bs["W"])
        if "rot" in self.o(self.base):
            bs["rot"] = int(self.o(self.base)["rot"]) % 360
        elif not (bL >= ext_x and bW >= ext_y) and (bW >= ext_x and bL >= ext_y or (bL > bW and ext_y > ext_x)):
            bs["rot"] = 90  # its long side along the rods
        fx, fy = self.foot(self.base)
        for key, have, need in (("x", fx, ext_x), ("y", fy, ext_y)):
            if have < need - 1e-6:
                k = ("L" if (key == "x") == (bs.get("rot") not in (90, 270)) else "W")
                if k in bs["given"]:
                    self.conflict(f"{self.name(self.base)} ({fx:g} x {fy:g}) is smaller than what it carries "
                                  f"({_r2(ext_x):g} x {_r2(ext_y):g}).", [self.base] + hosts, [x.id for x in self.joints])
                else:
                    bs[k] = _up(need + 2 * MARGIN, 1.0)
        self.at[self.base] = [[0.0, 0.0, -float(bs["H"]) / 2]]

    # ------------------------------------------------------------------ 5f. blocks bolted on blocks
    def _blocks(self) -> None:
        """No shafts: every block on its host's top face (bolted_joint / mounted_on), side by side along +X with
        GAP between them, the row centred on the host; the root (the largest part nothing carries) is the base."""
        parent: dict[str, tuple[str, Connection]] = {}
        for x in self.joints:
            if x.guest not in parent and x.guest != x.host:
                parent[x.guest] = (x.host, x)
        roots = [b for b in self.designed if b not in parent]
        if len(roots) != 1:
            raise Unsupported("blocks on more than one base")
        self.base, self.parent = roots[0], parent
        bs = self.spec[self.base]
        self.at[self.base] = [[0.0, 0.0, _r2(-float(bs["H"]) / 2)]]
        self.block_order: list[tuple[str, int]] = []

        def place(h: str) -> None:
            kids = [(k, c) for k in self.designed if parent.get(k, (None,))[0] == h for c in range(self.ncopies(k))]
            if not kids:
                return
            hp = self.at[h][0]
            assert hp is not None
            top = hp[2] + float(self.spec[h]["H"]) / 2
            widths = [self.foot(k)[0] for k, _c in kids]
            x = -(sum(widths) + GAP * (len(kids) - 1)) / 2
            for (k, c), w in zip(kids, widths, strict=True):
                self.at.setdefault(k, [None] * self.ncopies(k))
                self.at[k][c] = [_r2(hp[0] + x + w / 2), _r2(hp[1]), _r2(top + float(self.spec[k]["H"]) / 2)]
                x += w + GAP
                self.block_order.append((k, c))
            for k in dict.fromkeys(k for k, _c in kids):
                place(k)

        place(self.base)

    # ------------------------------------------------------------------ 5g. parts mounted on a base, members pivoting
    def _mount_shape(self) -> bool:
        """A base, connectors bolted to it and members joined to the connectors (a pin joint, or a bolted joint as an
        intent step wrote a folding table's legs before pin joints existed): every designed part is one of them."""
        guests = {x.guest for x in self.joints} | {x.guest for x in self.pin_x}
        roots = [b for b in self.designed if b not in guests]
        if len(roots) != 1 or self.role(roots[0]) != "block":
            return False
        conns = {x.guest for x in self.joints if x.host == roots[0] and self.role(x.guest) == "block"}
        membs = {x.guest for x in list(self.joints) + list(self.pin_x) if x.host in conns and x.guest not in conns
                 and self.role(x.guest) == "block"}
        return bool(conns and membs) and set(self.designed) == {roots[0]} | conns | membs

    def _role_sizes(self, base: str, conns: list[str], membs: list[str]) -> None:
        """Sizes nobody stated (not in the graph, not in the plan; a size frozen at approval was only an assumption
        then) take the role sizes ``graph/roles.py`` states: a table top 1200 x 700 x 18, legs 700 long and 40 x 20,
        brackets 60 x 30 x 60, other bases 600 x 400 x 15, other members 300 x 30 x 15 (said in the notes)."""
        from aicad.graph import roles

        words = " ".join([self.brief] + [self.name(c) for c in self.designed])
        table = bool(re.search(r"\btable\b", words, re.IGNORECASE))
        said = []
        for cid, dims in ([(base, roles.BASE_TABLE if table else roles.BASE_OTHER)]
                          + [(c, roles.CONNECTOR) for c in conns]
                          + [(m, roles.LEG if re.search(r"\blegs?\b", self.name(m), re.IGNORECASE) else roles.MEMBER)
                             for m in membs]):
            c, s = self.comp[cid], self.spec[cid]
            keys = ("L", "W", "T") if c.kind == "plate" else ("L", "W", "H")
            if any(c.v(k) is not None for k in keys) or icd._planned(self.p(cid), s, {}) or self.p(cid).get("envelope"):
                continue
            s["L"], s["W"], s["H"] = (float(x) for x in dims)
            s["given"] = set()
            s.pop("planned", None)
            said.append(f"{self.name(cid)} {' x '.join(f'{x:g}' for x in dims)}")
        if said:
            self.notes.append("Sizes the design leaves open, assumed by role: " + "; ".join(said) + ".")

    def _mount(self) -> None:
        """A base (a table top, a frame, a plate: by its role, never just the largest box) with connectors bolted to
        it (under it when it is a top) and members pivoting on the connectors. Connector copies sit at the base's
        corners (4), its ends (2) or its centre (1), CORNER mm in from its edges; member copy i pivots on connector
        copy i (a pivot bolt along Y through both: the member flush against the connector's inboard face, its pivot
        bore half its width from its upper end, hanging straight down). Every copy gets its own interfaces."""
        guests = {x.guest for x in self.joints} | {x.guest for x in self.pin_x}
        roots = [b for b in self.designed if b not in guests]
        if len(roots) != 1:
            raise Unsupported("parts mounted on more than one base")
        self.base = roots[0]
        conn_ids = {x.guest for x in self.joints if x.host == self.base and self.role(x.guest) == "block"}
        # members bolted to a connector pivot on it when the design folds (a folding table's legs)
        pins = list(self.pin_x) + [x for x in self.joints if x.host in conn_ids and x.guest not in conn_ids
                                   and self.role(x.guest) == "block"]
        self._role_sizes(self.base, [c for c in self.designed if c in conn_ids],
                         [m for m in self.designed if any(x.guest == m for x in pins)])
        self.under = bool(_TOPPY.search(self.name(self.base)))
        parent: dict[str, tuple[str, Connection]] = {}
        for x in self.joints:
            if x.host == self.base and self.role(x.guest) == "block":
                parent.setdefault(x.guest, (x.host, x))
        self.parent = parent
        self.connectors = [k for k in self.designed if k in parent]
        bs = self.spec[self.base]
        T = float(bs["H"])
        self.at[self.base] = [[0.0, 0.0, _r2(-T / 2)]]
        bx, by = self.foot(self.base)
        self.block_order: list[tuple[str, int]] = []
        for k in self.connectors:
            ks = self.spec[k]
            kx, ky = self.foot(k)
            n = self.ncopies(k)
            ex, ey = bx / 2 - CORNER - kx / 2, by / 2 - CORNER - ky / 2
            spots = {4: [(-ex, -ey), (ex, -ey), (-ex, ey), (ex, ey)], 2: [(-ex, 0.0), (ex, 0.0)], 1: [(0.0, 0.0)]}.get(
                n, [(-ex + 2 * ex * j / max(1, n - 1), 0.0) for j in range(n)])
            z = -T - float(ks["H"]) / 2 if self.under else float(ks["H"]) / 2
            self.at[k] = [[_r2(px), _r2(py), _r2(z)] for px, py in spots]
            self.block_order += [(k, c) for c in range(n)]
            if ex < 0 or ey < 0:
                self.conflict(f"{n} x {self.name(k)} don't fit on the {self.name(self.base)} ({bx:g} x {by:g}).",
                              [k, self.base], [parent[k][1].id])
        self.pivots: list[dict[str, Any]] = []
        for x in pins:
            h, m = x.host, x.guest
            if h not in self.at:
                raise Unsupported(f"{self.name(m)} pivots on {self.name(h)}, which isn't mounted on the base")
            if self.ncopies(m) != self.ncopies(h):
                self.conflict(f"{self.comp[m].qty} x {self.name(m)} pivot on {self.comp[h].qty} x {self.name(h)}: "
                              "each copy needs its own host copy.", [m, h], [x.id])
            hs, ms = self.spec[h], self.spec[m]
            _hx, hy = self.foot(h)
            mx_, my = self.foot(m)
            e = mx_ / 2  # the pivot bore half the member's width from its upper end
            self.at[m] = [None] * self.ncopies(m)
            bolt = next((self.comp[v] for v in x.via if self.comp.get(v) is not None and self.comp[v].kind == "fastener"),
                        None)
            mm = int(bolt.v("size")) if bolt is not None and bolt.v("size") and int(bolt.v("size")) in CLEARANCE else 8
            if self.under:
                # the pivot just under the top: the member's upper end PIVOT_CLEAR below the top's underside, its bore
                # e under that; the bracket is at least deep enough to hold the bore with 1 mm of wall (it grows to
                # it when sized smaller: the pivot rule sizes the bracket, not the other way round)
                need = e + PIVOT_CLEAR + CLEARANCE[mm] / 2 + 1.0
                if float(hs["H"]) < need - 1e-9:
                    self.notes.append(f"{self.name(h)}: {float(hs['H']):g} deep grown to {_r2(need):g} so the pivot "
                                      f"holds {self.name(m)}'s upper end {PIVOT_CLEAR:g} mm clear of the "
                                      f"{self.name(self.base)}.")
                    hs["H"] = _r2(need)
                    if hs.get("planned"):  # a stated rule re-plans the depth (not a part outgrowing its plan)
                        hs["planned"] = [hs["planned"][0], hs["planned"][1], max(hs["planned"][2], _r2(need))]
                    self.at[h] = [None if q is None else [q[0], q[1], _r2(-T - need / 2)] for q in self.at[h]]
            for c in range(min(self.ncopies(m), self.ncopies(h))):
                hp = self.at[h][c]
                assert hp is not None
                side = -1.0 if hp[1] > 0 else 1.0  # the host's inboard face
                zp = _r2(-T - PIVOT_CLEAR - e) if self.under else hp[2]
                ym = hp[1] + side * (hy / 2 + my / 2)
                self.at[m][c] = [_r2(hp[0]), _r2(ym), _r2(zp + e - float(ms["H"]) / 2)]
                self.pivots.append({"x": x, "host": h, "member": m, "c": c, "axis": [_r2(hp[0]), _r2(zp)],
                                    "plane": _r2(hp[1] + side * hy / 2), "normal": [0, int(side), 0]})

    def _pivot_joint(self, pv: dict[str, Any]) -> None:
        """A pivot bolt through the host and the member along Y: a one-hole bolted joint (head on the member, washers
        and the lock nut on the host side), so Fitz stacks the planned bolt, washers and nut there."""
        x, h, m, c = pv["x"], pv["host"], pv["member"], pv["c"]
        o = self.nxt()
        bolt = next((self.comp[v] for v in x.via if self.comp.get(v) is not None and self.comp[v].kind == "fastener"),
                    None)
        mm = int(o.get("fastener") or (bolt.v("size") if bolt is not None and bolt.v("size") else 8))
        mm = mm if mm in CLEARANCE else 8
        d = float(o.get("d") or CLEARANCE[mm])
        self.add("hole_pattern", (self.item[h], c), (self.item[m], c), {
            "fastener": f"M{mm}", "fastener_size": mm, "fastener_item": self.item[bolt.id] if bolt is not None else None,
            "count": 1, "d": d, "pattern": "linear", "inset": None, "ax": "y", "plane_z": pv["plane"],
            "normal": pv["normal"], "positions": [pv["axis"]], "through": True, "pivot": True,
            "flatness": float(o.get("flatness") or FLATNESS), "position_tol": float(o.get("position_tol") or POS_TOL)},
            ["A", "B", "C"], f"pivot bolt M{mm} (the {self.name(m).lower()} folds about it)")

    # ------------------------------------------------------------------ 5e. a pin joint (a hinge)
    def _pin(self) -> None:
        """An arm pivoting on a pin between the lugs of its host: the host is the base (its top face datum A); the
        pin axis along Y at the stated pivot height above the host's underside (else 80 % of its height), the guest
        centred between the lugs, lying along +X, its pivot bore half its width from its end; the slot between the
        lugs is the host's open cavity (the gap stated, else the guest's width + 2 mm)."""
        x = self.pin_x[0]
        host, guest = x.host, x.guest
        roots = [b for b in self.designed if self.role(b) == "block" and not any(j.guest == b for j in self.joints)
                 and b != guest]
        if roots != [host]:
            raise Unsupported("a pin joint whose host is not the base")
        self.base = host
        self.parent = {guest: (host, x)}
        hs, gs = self.spec[host], self.spec[guest]
        if "rot" in self.o(guest):
            gs["rot"] = int(self.o(guest)["rot"]) % 360
        elif float(gs["L"]) < float(gs["W"]) - TOL:
            gs["rot"] = 90  # its long side along +X
        glen, gw = self.foot(guest)
        gh = float(gs["H"])
        H = float(hs["H"])
        ph = float(x.v("pivot_height") or _r2(0.8 * H))
        gap = float(x.v("gap") or gw + 2.0)
        pin = next((v for v in x.via if self.comp.get(v) is not None and self.comp[v].kind == "dowel"), None)
        pd = float(self.comp[pin].v("d") or 8.0) if pin else 8.0
        pl = float(self.comp[pin].v("length") or self.foot(host)[1]) if pin else self.foot(host)[1]
        self.at[host] = [[0.0, 0.0, _r2(-H / 2)]]
        zp = _r2(-H + ph)
        e = gw / 2  # the pivot bore half the arm's width from its end
        self.at[guest] = [[_r2(glen / 2 - e), 0.0, zp]]
        floor = _r2(ph - gh / 2 - 2.0)  # 2 mm under the arm at the pivot
        hs["cavity"] = {"min": [_r2(-float(hs["L"]) / 2), _r2(-gap / 2), _r2(-H / 2 + floor)],
                        "max": [_r2(float(hs["L"]) / 2), _r2(gap / 2), _r2(H / 2)], "wall": _r2((self.foot(host)[1] - gap) / 2),
                        "floor": floor, "open_through": True,
                        "note": "Slot between the lugs: the arm swings here; the pin bore crosses it."}
        if gap < gw + TOL:
            self.conflict(f"{self.name(guest)} ({gw:g} wide) doesn't fit between the lugs of {self.name(host)} "
                          f"({gap:g} apart).", [guest, host], [x.id])
        if ph + pd / 2 > H - 1.0 + TOL:
            self.conflict(f"the pivot ({ph:g} above the underside) leaves no lug above the Ø{pd:g} pin bore in "
                          f"{self.name(host)} ({H:g} high).", [host], [x.id])
        if pl > self.foot(host)[1] + TOL:
            self.notes.append(f"The pin ({pl:g} long) stands {(pl - self.foot(host)[1]) / 2:g} mm out of each lug.")
        self.pin = {"x": x, "pin": pin, "d": pd, "length": pl, "axis": [0.0, zp]}

    # ------------------------------------------------------------------ anything no connection reached
    def _loose(self) -> None:
        if self.kind == "line":
            self.base = min(self.shafts, key=self._rank)
        env_x = max([c[0] + self.tip(i) / 2 for i in self.at for c in self.at[i] if c is not None
                     and self.role(i) != "block"] + [c[0] + float(self.spec[i]["L"]) / 2 for i in self.at
                                                      for c in self.at[i] if c is not None and self.role(i) == "block"]
                    + [0.0])
        loose_x = env_x + 3 * GAP
        for cid in self.designed:
            self.at.setdefault(cid, [None] * self.ncopies(cid))
            if len(self.at[cid]) < self.ncopies(cid):
                self.at[cid] += [None] * (self.ncopies(cid) - len(self.at[cid]))
            for c in range(len(self.at[cid])):
                if self.at[cid][c] is not None:
                    continue
                s = self.spec[cid]
                w = float(s["L"]) if s["role"] == "block" else self.tip(cid)
                hgt = float(s["H"]) if s["role"] == "block" else (s.get("length") or self.height(cid) or 20.0)
                if s["role"] == "shaft" and not s.get("length"):
                    s["length"] = max(40.0, float(hgt))
                    hgt = s["length"]
                self.at[cid][c] = [_r2(loose_x + w / 2), 0.0, _r2(float(hgt) / 2)]
                loose_x += w + GAP
                if c == 0:
                    via = [x.id for x in self.g.connections if cid in (x.host, x.guest)]
                    self.conflict(f"{self.name(cid)} is not placed by any connection to the base "
                                  f"({self.name(self.base)}): it is drawn beside the program and would not be "
                                  "assembled. Connect it, or remove it from the design.", [cid], via)

    # ------------------------------------------------------------------ 6. the interfaces
    def add(self, kind: str, a: tuple[str, int], b: tuple[str, int], data: dict[str, Any], datums: list[str],
            label: str | None = None) -> dict[str, Any]:
        iid = f"IF-{len(self.ifs) + 1:02d}"
        o = self.fov.get(iid) or {}

        def nm(i: str, c: int) -> str:
            cid = self.cid_of.get(i)
            n = (self.ncopies(cid) if cid and self.role(cid) != "standard" else
                 int(self.comp[cid].qty) if cid else int(self.by_pid[i]["qty"]))
            return self.by_pid[i]["name"] + (f" #{c + 1}" if n > 1 else "")

        na, nb = nm(*a), nm(*b)
        f = {"id": iid, "kind": kind, "name": f"{nb} ↔ {na}: {label or KIND_LABEL[kind]}",
             "a": {"item": a[0], "copy": a[1], "name": na}, "b": {"item": b[0], "copy": b[1], "name": nb},
             "datums": datums, "data": data, "edited": sorted(o)}
        for w, i in (("a", a[0]), ("b", b[0])):
            cid = self.cid_of.get(i)
            if cid is None or self.role(cid) == "standard":
                f[w]["standard"] = True
        self.ifs.append(f)
        return f

    def nxt(self) -> dict[str, Any]:
        return self.fov.get(f"IF-{len(self.ifs) + 1:02d}") or {}

    def _emit(self) -> None:
        if self.kind == "gearbox":
            hm = self.hm
            if hm["lid"]:
                self._grid_joint(self.housing, 0, hm["lid"], 0, hm["lid_x"], tapped=True)
            for sh in hm["shafts"]:
                self._housing_seat(sh)
                self._riders(sh)
            for st, n, side in hm["caps"]:
                self._cap_joint(st, n, side)
        elif self.kind == "guide":
            for x in self.joints:  # the end blocks on the base
                if self.role(x.host) == "block" and self.role(x.guest) == "block" and x.guest in self.at:
                    for c in range(len(self.at[x.guest])):
                        if self.at[x.guest][c] is not None:
                            self._grid_joint(x.host, 0, x.guest, c, x, tapped=False)
            for r, k in self.rod_copies:
                for x in self.rod_x:
                    if x.guest == r:
                        for c in range(len(self.at.get(x.host) or [])):
                            self._rod_bore(x.host, c, r, k, "end")
                for x in self.slide_x:
                    if x.host == r:
                        self._rod_bore(x.guest, 0, r, k, "slide")
        elif self.kind == "pin":
            self._pin_joint()
        elif self.kind == "mount":
            for k, c in self.block_order:
                x = self.parent[k][1]
                self._grid_joint(self.parent[k][0], 0, k, c, x, tapped=self.under, under=self.under)
            for pv in self.pivots:
                self._pivot_joint(pv)
        elif self.kind == "blocks":
            for k, c in self.block_order:
                x = self.parent[k][1]
                self._grid_joint(self.parent[k][0], 0, k, c, x, tapped=False)
        elif self.kind == "plate":
            for x in self.joints:  # blocks on blocks: pillow blocks and the bracket on the plate, the motor on it
                if self.role(x.host) == "block" and self.role(x.guest) == "block":
                    for c in range(self.ncopies(x.guest)):
                        if self.at[x.guest][c] is not None and self.at[x.host][0] is not None:
                            self._grid_joint(x.host, 0, x.guest, c, x, tapped=False)
            for sh in self.order:
                for (pb, n), (b, _k) in sorted(self.pb_of.items(), key=lambda kv: (kv[0][0], kv[0][1])):
                    if self.pb_seat[(pb, n)]["shaft"] == sh:
                        self._pillow_seat(pb, n, b)
                self._riders(sh)
            for e in self.edges:
                if e["kind"] == "coupling" and e.get("via") and not e.get("loop_bad"):
                    self._coupling(e)
        else:
            for sh in self.order:
                self._journals(sh)
                self._riders(sh)
            for e in self.edges:
                if e["kind"] == "coupling" and e.get("via") and not e.get("loop_bad"):
                    self._coupling(e)
        for e in self.edges:
            if e["kind"] == "gear_mesh" and not e.get("loop_bad"):
                self._mesh(e)
        for e in self.edges:
            if e["kind"] == "belt_drive" and not e.get("loop_bad"):
                self._belt(e)
        self._rings()
        self._phase()

    def _rod_bore(self, block: str, c: int, rod: str, k: int, what: str) -> None:
        """A rod in a block's bore: held at its end (flush with the -Y block's outer face), or a carriage sliding."""
        pos = self.at[block][c]
        assert pos is not None
        y0 = pos[1] - self.foot(block)[1] / 2
        y1 = pos[1] + self.foot(block)[1] / 2
        d = float(self.spec[rod]["seat"])
        o = self.nxt()
        fit = str(o.get("fit") or ("H7/h6" if what == "end" else "H7/g6"))
        flush = _r2(y0) if what == "end" and abs(y0 - self.rod_ends[0]) < 1e-6 else None
        rp = self.at[rod][k]
        assert rp is not None
        self.add("shaft_bore", (self.item[block], c), (self.item[rod], k), {
            "d": d, "fit": fit if fit in FITS else "H7/h6", "length": _r2(y1 - y0), "ax": "y", "axis": [rp[0], rp[2]],
            "z": [_r2(y0), _r2(y1)], "flush_z": flush, "position_tol": POS_TOL}, ["A", "B", "C"],
            ("rod end held in its block" + (", flush with the outer face" if flush is not None else "")) if what == "end"
            else "carriage sliding on the rod")

    def _pin_joint(self) -> None:
        """The pin through both lugs and the arm's pivot bore (ISO 8734 dowel pin, along Y)."""
        p = self.pin
        x = p["x"]
        o = self.nxt()
        self.add("dowel", (self.item[x.host], 0), (self.item[x.guest], 0), {
            "d": p["d"], "fit": str(o.get("fit") or "H7/h6"), "count": 1, "positions": [p["axis"]], "plane_z": 0.0,
            "ax": "y", "length": p["length"], "pin_item": self.item[p["pin"]] if p["pin"] else None,
            "joint": None, "standard": "ISO 8734", "position_tol": POS_TOL}, ["A", "B", "C"],
            f"hinge pin Ø{p['d']:g} x {p['length']:g} (ISO 8734)")

    def _axis2(self, sh: str) -> list[float]:
        c = self.at[sh][0]
        assert c is not None
        return [_r2(c[0]), _r2(c[2])]

    def _riders(self, sh: str) -> None:
        s = self.spec[sh]
        a2 = self._axis2(sh)
        for r in sorted(self.riders[sh], key=lambda r: self.gy(sh, r)):
            for c in range(self.ncopies(r)):
                if c:
                    continue  # (copies of a rider on one shaft: the first is laid out)
                h = self.height(r)
                bottom = self.gy(sh, r) - h / 2
                o = self.nxt()
                x = self.hub_conn[r]
                fit = str(o.get("fit") or x.v("fit") or "H7/k6")
                step: dict[str, Any] = {}
                if s.get("seat_z") and s.get("body"):
                    step = {"seat_z": s["seat_z"], "shoulder_d": s["body"],
                            "shoulder_source": "edited" if "shoulder_d" in self.o(sh) else "plan"}
                    if r in self.stops[sh] and abs(bottom + h - float(s["shoulder_z"])) < 1e-6:
                        step.update(shoulder_z=s["shoulder_z"], side=1)
                    elif not (s["seat_z"][0] - 1e-6 <= bottom and bottom + h <= s["seat_z"][1] + 1e-6):
                        step = {}
                self.add("shaft_bore", (self.item[r], c), (self.item[sh], 0), {
                    "d": s["seat"], "fit": fit if fit in FITS else "H7/k6", "length": _r2(h), "ax": "y",
                    "axis": a2, "z": [_r2(bottom), _r2(bottom + h)], "flush_z": None, **step,
                    "position_tol": POS_TOL}, ["A", "B", "C"],
                    "bore on its seat, against the shoulder" if step.get("shoulder_z") is not None else "bore on shaft")
                key = icd.key_for(s["seat"])
                if x.kind == "keyed_hub" and key and h >= key[0] + 3:
                    o2 = self.nxt()
                    kb, kh, t1, t2 = key
                    kc = next((self.comp[v] for v in x.via if self.comp.get(v) is not None and self.comp[v].kind == "key"),
                              None)
                    kl = float(o2.get("length") or math.floor(max(kb + 2, h - 2)))
                    kl = min(kl, float(math.floor(h)))
                    z0 = bottom + (h - kl) / 2
                    self.add("key", (self.item[r], c), (self.item[sh], 0), {
                        "d": s["seat"], "b": kb, "h": kh, "t1": t1, "t2": t2, "length": kl, "ax": "y",
                        "axis": a2, "dir": [1, 0], "z": [_r2(z0), _r2(z0 + kl)],
                        "hub_z": [_r2(bottom), _r2(bottom + h)], "key_item": self.item[kc.id] if kc else None,
                        "standard": "DIN 6885-1 A", "position_tol": POS_TOL}, ["A", "B", "C"],
                        f"parallel key {kb:g} x {kh:g} x {kl:g}")
                elif x.kind == "keyed_hub" and key:
                    self.notes.append(f"{self.name(r)}: {h:g} mm is too narrow for a DIN 6885 key "
                                      f"{key[0]:g} wide; the keyway is left out.")
                # a spacer bears on its neighbour's face
                if self.comp[r].kind == "spacer":
                    prev = [q for q in self.riders[sh] if q != r and abs(self.gy(sh, q) + self.height(q) / 2 - bottom)
                            < 1e-6]
                    if prev:
                        o2 = self.nxt()
                        self.add("face", (self.item[prev[0]], 0), (self.item[r], 0), {
                            "plane_z": _r2(bottom), "normal": [0, 1, 0], "ax": "y",
                            "flatness": float(o2.get("flatness") or FLATNESS),
                            "position_tol": float(o2.get("position_tol") or POS_TOL)}, ["A"])

    def _journals(self, sh: str) -> None:
        """Bearings on the shaft's journals (no housing): the shaft line's interface."""
        s = self.spec[sh]
        a2 = self._axis2(sh)
        y_lo, y_hi = s["y0"], s["y1"]
        for side, b0, b1, (bitem, k) in s.get("brg") or []:
            des = self._des(bitem)
            bd, bD, bB = BEARINGS[des]
            inboard = self._inboard_d(sh, side)
            plain = inboard <= bd + 1e-9
            against = side > 0 and s.get("against_collar")
            if plain and not against:
                jz, shz = (b0, b1), None
            else:
                jz = (y_lo, b1) if side < 0 else (b0, y_hi)
                shz = b1 if side < 0 else b0
            self.add("bearing_journal", (self.item[sh], 0), (self.item[bitem], k), {
                "designation": str(des), "bearing": f"Deep-groove ball bearing {des}", "d": bd, "D": bD, "B": bB,
                "shaft_fit": SHAFT_FIT_BEARING, "ax": "y", "axis": a2, "z": [_r2(b0), _r2(b1)],
                "journal_z": [_r2(jz[0]), _r2(jz[1])], "shoulder_z": None if shz is None else _r2(shz),
                "side": side, "bearing_item": self.item[bitem], "shaft_d": s["seat"], "count": 1,
                "r_s_min": icd._BEARING_RS[int(des)], "standard": "ISO 15 (Toolbox table)", "position_tol": POS_TOL},
                ["A", "B", "C"], f"bearing {des} on its journal ({'-' if side < 0 else '+'}Y end)")

    def _inboard_d(self, sh: str, side: int) -> float:
        """The shaft Ø next to a bearing on its inboard side (the seat, or the collar of a shoulder)."""
        s = self.spec[sh]
        if side > 0 and s.get("against_collar") and s.get("body"):
            return float(s["body"])
        return float(s["seat"])

    def _housing_seat(self, sh: str) -> None:
        hm, s = self.hm, self.spec[sh]
        h = self.housing
        pos = self.at[sh][0]
        assert pos is not None
        bitem, _k = s["brg"][0][3]
        des = self._des(bitem)
        bd, bD, bB = BEARINGS[des]
        o = self.nxt()
        hf = str(o.get("housing_fit") or "H7")
        y0, y1 = hm["y0"], hm["y1"]
        seats = [{"face": "+Y wall", "open": 1, "z": [_r2(y1 - bB), _r2(y1)]}] if len(s["brg"]) >= 2 else []
        seats.append({"face": "-Y wall", "open": -1, "z": [_r2(y0), _r2(y0 + bB)]})
        extra: dict[str, Any] = {}
        if s.get("body"):  # a stepped shaft: its journals, not the whole span, are the bearing Ø (the +Y journal
            # runs from the collar's end out through the wall and the open cap)
            hi0 = s["collar"][1] if s.get("collar") else y1 - bB
            extra["journals"] = [[_r2(y0), _r2(y0 + bB)]] + ([[_r2(hi0), _r2(s["y1"])]] if len(s["brg"]) >= 2 else [])
        n_s = len(seats)
        self.add("bearing_seat", (self.item[h], 0), (self.item[sh], 0), {
            "designation": str(des), "bearing": f"Deep-groove ball bearing {des}", "d": bd, "D": bD, "B": bB,
            "housing_fit": hf if hf in HOUSING_FITS else "H7", "shaft_fit": SHAFT_FIT_BEARING, "ax": "y",
            "axis": [_r2(pos[0]), _r2(pos[2])], "z": [_r2(y0), _r2(y1)], "seats": seats,
            "clearance_d": _r2(bd + 2), "flush_z": _r2(y0), "bearing_item": self.item[bitem], "shaft_d": s["seat"],
            "count": n_s, "r_s_min": icd._BEARING_RS[int(des)], "standard": "ISO 15 (Toolbox table)",
            "position_tol": POS_TOL, **extra},
            ["A", "B", "C"], f"shaft in {n_s} bearing{'s' if n_s != 1 else ''} {des} (side walls)")

    def _pillow_seat(self, pb: str, n: int, bitem: str) -> None:
        ps = self.pb_seat[(pb, n)]
        sh, sd = ps["shaft"], ps["side"]
        s = self.spec[sh]
        des = ps["des"]
        bd, bD, bB = BEARINGS[des]
        o = self.nxt()
        hf = str(o.get("housing_fit") or "H7")
        inboard = self._inboard_d(sh, sd)
        k = next(k for b, k in [self.pb_of[(pb, n)]] if b == bitem)
        s_lo, s_hi = ps["seat"]
        jz = [s_lo, s_hi]
        if inboard > bd + 1e-9:  # the shaft is larger inboard: the journal runs out to the end (a shoulder at it)
            jz = [s["y0"], s_hi] if sd < 0 else [s_lo, s["y1"]]
        self.add("bearing_seat", (self.item[pb], n), (self.item[sh], 0), {
            "designation": str(des), "bearing": f"Deep-groove ball bearing {des}", "d": bd, "D": bD, "B": bB,
            "housing_fit": hf if hf in HOUSING_FITS else "H7", "shaft_fit": SHAFT_FIT_BEARING, "ax": "y",
            "axis": self._axis2(sh), "z": ps["z"],
            "seats": [{"face": "-Y face", "open": -1, "z": [_r2(s_lo), _r2(s_hi)]}],
            "clearance_d": _r2(max(bd + 2, inboard + 2)), "flush_z": None, "bearing_item": self.item[bitem],
            "piece": k, "shaft_d": s["seat"], "count": 1, "r_s_min": icd._BEARING_RS[int(des)],
            "journals": [[_r2(jz[0]), _r2(jz[1])]], "standard": "ISO 15 (Toolbox table)", "position_tol": POS_TOL},
            ["A", "B", "C"], f"shaft in bearing {des} ({self.name(pb)})")

    def _coupling(self, e: dict[str, Any]) -> None:
        cid = e["via"]
        sh = e["b"]
        a2 = self._axis2(sh)
        lo = self.spec[sh]["y0"]
        eng = e["eng"]
        self.add("shaft_bore", (self.item[cid], 0), (self.item[sh], 0), {
            "d": e["db"], "fit": "H7/k6", "length": _r2(eng), "ax": "y", "axis": a2, "z": [_r2(lo), _r2(lo + eng)],
            "flush_z": None, "position_tol": POS_TOL}, ["A", "B", "C"], "coupling bore on the shaft end")
        if e.get("motor"):
            m = e["motor"]
            end = lo - COUPLING_GAP
            self.add("shaft_bore", (self.item[cid], 0), (self.item[m], 0), {
                "d": e["da"], "fit": "H7/k6", "length": _r2(eng), "ax": "y", "axis": a2,
                "z": [_r2(end - eng), _r2(end)], "flush_z": None, "position_tol": POS_TOL}, ["A", "B", "C"],
                "coupling bore on the motor shaft")
        elif e.get("a"):
            a = e["a"]
            end = self.spec[a]["y1"]
            self.add("shaft_bore", (self.item[cid], 0), (self.item[a], 0), {
                "d": e["da"], "fit": "H7/k6", "length": _r2(eng), "ax": "y", "axis": a2,
                "z": [_r2(end - eng), _r2(end)], "flush_z": None, "position_tol": POS_TOL}, ["A", "B", "C"],
                "coupling bore on the shaft end")

    def _mesh(self, e: dict[str, Any]) -> None:
        ga, gb = e["ra"], e["rb"]
        sa, sb = self.spec[ga], self.spec[gb]
        pa, pb = self.at[ga][0], self.at[gb][0]
        assert pa is not None and pb is not None
        self.add("gear_mesh", (self.item[ga], 0), (self.item[gb], 0), {
            "module": sa["module"], "teeth_a": int(sa["teeth"]), "teeth_b": int(sb["teeth"]),
            "centre_distance": _r2(float(sa["module"]) * (int(sa["teeth"]) + int(sb["teeth"])) / 2),
            "face_width": _r2(min(sa["b"], sb["b"])), "pressure_angle": PRESSURE_ANGLE,
            "ratio": round(int(sb["teeth"]) / int(sa["teeth"]), 4),
            "axis_a": [_r2(pa[0]), _r2(pa[2])], "axis_b": [_r2(pb[0]), _r2(pb[2])],
            "ax": "y", "plane_a": _r2(pa[1]), "plane_b": _r2(pb[1])}, ["A", "B"])

    def _belt(self, e: dict[str, Any]) -> None:
        pa_, pb_ = e["ra"], e["rb"]
        pa, pb = self.at[pa_][0], self.at[pb_][0]
        assert pa is not None and pb is not None
        d1, d2, C = self.od(pa_), self.od(pb_), e["dist"]
        L = 2 * C + math.pi * (d1 + d2) / 2 + (d2 - d1) ** 2 / (4 * C)
        wrap = 180.0 - 2 * math.degrees(math.asin(min(1.0, abs(d2 - d1) / (2 * C))))
        self.add("belt_drive", (self.item[pa_], 0), (self.item[pb_], 0), {
            "centre_distance": _r2(C), "d_a": _r2(d1), "d_b": _r2(d2), "ratio": round(d2 / d1, 4) if d1 else None,
            "belt_length": _r2(L), "wrap_small": _r2(wrap), "rule": "C = D1 + D2 (assumed)" if e.get("rule") else "stated",
            "axis_a": [_r2(pa[0]), _r2(pa[2])], "axis_b": [_r2(pb[0]), _r2(pb[2])], "ax": "y",
            "plane_a": _r2(pa[1]), "plane_b": _r2(pb[1]), "position_tol": POS_TOL}, ["A", "B"],
            f"belt drive C {C:g}, pitch length {L:.0f}")

    def _grid_joint(self, host: str, hc: int, child: str, cc: int, x: Connection | None, *, tapped: bool,
                    under: bool = False) -> None:
        """A block bolted on its host's top face (the template's rule for a bolted block: a grid of 4, or 2 along
        the longer side when the washers of two rows don't fit side by side)."""
        ks = self.spec[child]
        pos = self.at[child][cc]
        assert pos is not None
        o = self.nxt()
        Lp, Wp = self.foot(child)
        bottom = pos[2] + (1 if under else -1) * float(ks["H"]) / 2  # the joint face (the child's top when under)
        if self.comp[child].kind == "pillow_block":
            span = 2 * max(BEARINGS[self._des(b)][1] for b in self._pb_bearings(child))
        else:
            span = float(ks.get("joint_span") or min(Lp, Wp))
        m = int(o.get("fastener") or self._fastener(x, span))
        m = m if m in CLEARANCE else icd.fastener_for(span)
        d = float(o.get("d") or CLEARANCE[m])
        inset_pref = max(2 * d, 6.0)
        wod = WASHER_OD.get(max(m, icd.bolt_for_hole(d)), 2 * d)
        bolts = next((self.comp[v] for v in (x.via if x else []) if self.comp.get(v) is not None
                      and self.comp[v].kind == "fastener"), None)
        per = int(bolts.qty) // max(1, self.ncopies(child)) if bolts is not None else 0

        def pattern(o_count: Any, o_inset: Any) -> tuple[int, float, list[list[float]]]:
            inset = float(o_inset or inset_pref)
            count = int(o_count or (4 if min(Lp, Wp) - 2 * inset >= wod and max(Lp, Wp) - 2 * inset >= wod else 2))
            if not o_count and bolts is not None and int(bolts.qty) in (2, 3):  # no more holes than planned bolts
                count = 2
            if not o_count and not o_inset and count == 2 and per >= 4:
                in4 = _r2(min(inset_pref, (min(Lp, Wp) - wod) / 2))  # four planned per joint: the holes move in
                if in4 >= d / 2 + 1.0:
                    count, inset = 4, in4
            pts = _grid(pos, Lp, Wp, count, inset)
            if count == 2 and not o_inset:
                inset = _r2(max(min(inset_pref, (max(Lp, Wp) - wod) / 2), d / 2 + 1.0))
                pts = _grid(pos, Lp, Wp, count, inset)
            return count, inset, pts

        _count, inset, pts = pattern(o.get("count"), o.get("inset"))
        gap = min((math.dist(a, b) for k, a in enumerate(pts) for b in pts[k + 1:]), default=math.inf)
        if (o.get("count") or o.get("inset")) and (gap < wod - 1e-6 or inset < d / 2 + 1.0 - 1e-6):
            # a pattern frozen for another layout of this joint (a revision moved or resized the part): the rule again
            _count, inset, pts = pattern(None, None)
        tap = {"d": TAP_DRILL[m], "depth": icd.tap_depth(m), "thread": f"M{m}"} if tapped else None
        self.add("hole_pattern", (self.item[host], hc), (self.item[child], cc), {
            "fastener": f"M{m}", "fastener_size": m, "fastener_item": self._fastener_item(x),
            "count": len(pts), "d": d, "pattern": "grid" if len(pts) > 2 else "linear", "inset": inset,
            "plane_z": _r2(bottom), "normal": [0, 0, -1 if under else 1], "positions": pts, "through": tap is None,
            **({"tapped": tap} if tap else {}),
            "flatness": float(o.get("flatness") or FLATNESS), "position_tol": float(o.get("position_tol") or POS_TOL)},
            ["A", "B", "C"])

    def _cap_joint(self, st: tuple[str, int], n: int, side: int) -> None:
        hm = self.hm
        ci, cc = st
        cid = self.cid_of[ci]
        ks = self.spec[cid]
        pos = self.at[cid][cc]
        assert pos is not None
        o = self.nxt()
        m = int(o.get("fastener") or hm["cap_m"])
        m = m if m in CLEARANCE else hm["cap_m"]
        d = float(o.get("d") or CLEARANCE[m])
        count = int(o.get("count") or 4)
        pcd = _r2(ks["pcd"])
        plane = hm["y0"] if side < 0 else hm["y1"]
        a2 = [_r2(pos[0]), _r2(pos[2])]
        des = self._des(self.brg[hm["shafts"][n]][0][0])
        x = self._joint_to(cid, self.housing)
        self.add("hole_pattern", (self.item[self.housing], 0), (ci, cc), {
            "fastener": f"M{m}", "fastener_size": m, "fastener_item": hm.get("cap_item") or self._fastener_item(x),
            "count": count, "d": d, "pattern": "circular", "pcd": pcd, "centre": a2, "ax": "y",
            "plane_z": _r2(plane), "normal": [0, side, 0], "positions": _circle(a2, pcd, count), "through": False,
            "tapped": {"d": TAP_DRILL[m], "depth": icd.tap_depth(m), "thread": f"M{m}"},
            "cap": ks.get("cap") or "open", "seat_D": BEARINGS[des][1], "bearing": str(des),
            "relief": {"d": ks["relief"], "depth": CAP_RELIEF} if ks.get("relief") else None,
            "flatness": float(o.get("flatness") or FLATNESS), "position_tol": float(o.get("position_tol") or POS_TOL)},
            ["A", "B", "C"], f"{ks.get('cap') or 'open'} bearing cap over the {'+' if side > 0 else '-'}Y seat")

    def _rings(self) -> None:
        """DIN 471 rings in their grooves at the free face of the part they hold (the face away from a shoulder)."""
        took: dict[str, int] = {}
        for x in self.rings:
            sh = x.host
            if sh not in self.spec or self.comp[sh].kind != "shaft":
                continue
            rc = next((v for v in x.via if self.comp.get(v) is not None and self.comp[v].kind == "retaining_ring"), None)
            if rc is None:
                continue
            s = self.spec[sh]
            gu = x.guest
            faces: list[tuple[float, int, str, tuple[str, int], float]] = []  # (face, side, against, who, shaft Ø)
            if gu in self.riders.get(sh, []):
                h = self.height(gu)
                lo, hi = self.gy(sh, gu) - h / 2, self.gy(sh, gu) + h / 2
                if gu in self.stops[sh]:
                    faces = [(lo, -1, "hub", (self.item[gu], 0), s["seat"])]
                else:
                    faces = [(lo, -1, "hub", (self.item[gu], 0), s["seat"]), (hi, 1, "hub", (self.item[gu], 0), s["seat"])]
            elif self.comp[gu].kind == "bearing":
                for sd, b0, b1, (b, k) in s.get("brg") or []:
                    if b == gu:
                        bd = BEARINGS[self._des(b)][0]
                        faces.append((b0 if sd < 0 else b1, sd, "bearing", (self.item[b], k), min(s["seat"], bd)))
            for face, side, against, who, d1 in faces:
                n = took.get(rc, 0)
                if n >= int(self.comp[rc].qty):
                    break
                row = RINGS.get(round(d1)) if abs(d1 - round(d1)) < 1e-9 else None
                if row is None:
                    self.conflict(f"{self.name(rc)}: Ø{d1:g} is not a DIN 471 shaft size.", [rc, sh], [x.id])
                    break
                s_, b_, d2, m_, n_ = row
                g0, g1 = (face, face + m_) if side > 0 else (face - m_, face)
                if g0 < s["y0"] + n_ - 1e-9 or g1 > s["y1"] - n_ + 1e-9:
                    self.conflict(f"{self.name(rc)}: no room for its groove between {self.name(gu)} and the end of "
                                  f"{self.name(sh)}.", [rc, sh, gu], [x.id])
                    continue
                took[rc] = n + 1
                r0, r1 = (face, face + s_) if side > 0 else (face - s_, face)
                self.add("retaining_ring", (self.item[sh], 0), (self.item[rc], n), {
                    "d": d1, "s": s_, "b": b_, "d2": d2, "m": m_, "n": n_, "t": _r2((d1 - d2) / 2), "ax": "y",
                    "axis": self._axis2(sh), "z": [_r2(r0), _r2(r1)], "groove_z": [_r2(g0), _r2(g1)],
                    "face_z": _r2(face), "side": side, "against": against, "against_item": who[0],
                    "against_copy": who[1], "ring_item": self.item[rc], "ring": f"Retaining ring DIN 471 {d1:g}×{s_:g}",
                    "count": 1, "standard": "DIN 471", "position_tol": POS_TOL}, ["A", "B"],
                    f"retaining ring DIN 471 {d1:g} at the {'+' if side > 0 else '-'}Y face of the "
                    f"{self.name(gu) if against == 'hub' else 'bearing'}")

    def _phase(self) -> None:
        """Tooth phasing (the template's rule): gear b turns so a tooth space faces gear a's tooth, v = 1/2 - u."""
        self.phase: dict[str, float] = {}
        for f in self.ifs:
            if f["kind"] != "gear_mesh":
                continue
            ga, gb = f["a"]["item"], f["b"]["item"]
            d = f["data"]
            v = frames.apply(frames.transpose(icd.CANON[icd.ax_of(d)]),
                             icd.point3(icd.ax_of(d), [d["axis_b"][0] - d["axis_a"][0], d["axis_b"][1] - d["axis_a"][1]],
                                        0.0))
            th = math.degrees(math.atan2(v[1], v[0]))
            pa, pb = 360.0 / d["teeth_a"], 360.0 / d["teeth_b"]
            u = ((th - self.phase.get(ga, 0.0)) % pa) / pa
            w = (0.5 - u) % 1.0
            if gb not in self.phase:
                self.phase[gb] = round(((th + 180.0) - w * pb) % pb, 6)
            d["phase_b"] = self.phase[gb]

    # ------------------------------------------------------------------ 7. the skeleton document
    def _skeleton(self) -> dict[str, Any]:
        items: dict[str, Any] = {}
        lo = [math.inf] * 3
        hi = [-math.inf] * 3
        for cid in self.designed:
            s = self.spec[cid]
            i = self.item[cid]
            p = self.by_pid[i]
            if s["role"] == "shaft":
                s["d"] = float(s.get("body") or s["seat"])
                if s["role"] == "shaft" and not s.get("length"):
                    s["length"] = 40.0
            size = icd._size_of(s)
            Rw = frames.item_rotation(s.get("ax") or "z", float(s.get("rot") or 0) if s["role"] == "block" else 0.0)
            wsize = [sum(abs(Rw[r][j]) * size[j] for j in range(3)) for r in range(3)]
            cps = [c for c in self.at[cid] if c is not None]
            for c in cps:
                for k in range(3):
                    lo[k] = min(lo[k], c[k] - wsize[k] / 2)
                    hi[k] = max(hi[k], c[k] + wsize[k] / 2)
            bearing = None
            if s["role"] == "shaft" and self.brg.get(cid):
                b0 = self.brg[cid][0][0]
                bearing = {"designation": self._des(b0), "item": self.item[b0],
                           "journal": BEARINGS[self._des(b0)][0], "seats": len(self.brg[cid])}
            items[i] = {"name": p["name"], "role": s["role"], "shape": "box" if s["role"] == "block" else "cylinder",
                        "size": [_r2(x) for x in size], "sub": p["sub"], "parent": self._parent_item(cid),
                        "copies": [[_r2(x) for x in c] for c in cps], "qty": p["qty"], "source": s["source"],
                        **({"rot": s["rot"]} if s.get("rot") and s["role"] == "block" else {}),
                        **({"planned": s["planned"]} if s.get("planned") else {}),
                        **({"ax": s["ax"]} if s.get("ax") and s["ax"] != "z" else {}),
                        **({"cavity": self._cavity()} if self.kind == "gearbox" and cid == self.housing else
                           {"cavity": s["cavity"]} if s.get("cavity") else {}),
                        **({"phase": self.phase[i]} if self.phase.get(i) else {}),
                        **({"d": s["d"]} if s["role"] == "shaft" else {}),
                        **({"bearing": bearing} if bearing else {}),
                        **({"bore": s["bore"]} if s.get("bore") else {}),
                        **({"module": s["module"], "teeth": int(s["teeth"]), "face_width": s["b"]}
                           if s["role"] == "gear" else {})}
        axes = [{"id": f"AX{n + 1}", "name": f"{items[i]['name']} axis", "item": i, "origin": [items[i]["copies"][0][0],
                 0.0, items[i]["copies"][0][2]], "dir": [0.0, 1.0, 0.0]}
                for n, i in enumerate(i for i in items if items[i]["role"] == "shaft")]
        base = items[self.item[self.base]]
        if self.kind == "line" or getattr(self, "frameless", False):
            csys, datums = self._line_datums(base)
        else:
            csys = (f"Origin at the centre of the top face of the {base['name']} (datums A, B, C); +Z up, away from "
                    "the base; +X along the row of parts; +Y completes a right-handed frame."
                    + (" Gearbox shafts run along +Y." if self.kind == "gearbox" else " The shafts run along +Y."))
            datums = [{"id": "A", "kind": "plane", "name": f"{base['name']} top face", "origin": [0, 0, 0],
                       "normal": [0, 0, 1]},
                      {"id": "B", "kind": "plane", "name": "Mid-plane XZ", "origin": [0, 0, 0], "normal": [0, 1, 0]},
                      {"id": "C", "kind": "plane", "name": "Mid-plane YZ", "origin": [0, 0, 0], "normal": [1, 0, 0]}]
        self._summary_notes()
        parts_std = [{"item": p["id"], "name": p["name"], "qty": p["qty"], "sub": p["sub"]}
                     for p in self.parts if p["family"] == "standard"]
        skel = {"units": "mm", "base": self.item[self.base],
                "layout": {"gearbox": "gearbox", "plate": "block", "line": "shaft_line", "guide": "block",
                           "pin": "block", "blocks": "block", "mount": "block"}[self.kind],
                "csys": csys, "datums": datums, "axes": axes,
                "envelope": {"min": [_r2(x) for x in lo], "max": [_r2(x) for x in hi],
                             "size": [_r2(hi[k] - lo[k]) for k in range(3)]},
                "items": items, "notes": self.notes, "standard": parts_std, "solver": "graph"}
        if self.conflicts:
            skel["conflicts"] = self.conflicts
        sep = sorted(i for i in (self.ov.get("separate") or {}) if i in items)
        if sep:
            skel["separate"] = sep
        if self.sub_line:
            skel["shaft_subassembly"] = True
        return skel

    def _parent_item(self, cid: str) -> str | None:
        if cid in self.rider_of:
            return self.item[self.rider_of[cid]]
        if self.kind == "gearbox":
            return None if cid == self.housing else self.item[self.housing]
        if self.kind in ("plate", "guide", "pin", "blocks", "mount"):
            if cid == self.base:
                return None
            if cid in getattr(self, "parent", {}):
                return self.item[self.parent[cid][0]]
            return self.item[self.base]
        return None

    def _cavity(self) -> dict[str, Any]:
        hm, s = self.hm, self.spec[self.housing]
        L, W, H = float(s["L"]), float(s["W"]), float(s["H"])
        return {"min": [_r2(-L / 2 + hm["end_t"]), _r2(-W / 2 + hm["t"]), _r2(-H / 2 + FLOOR)],
                "max": [_r2(L / 2 - hm["end_t"]), _r2(W / 2 - hm["t"]), _r2(H / 2)],
                "wall": hm["t"], "end_wall": hm["end_t"], "floor": FLOOR,
                "note": "Gear cavity: keep it clear (the gears run there); open at the top under the lid."}

    def _line_datums(self, base: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        meshy = any(e["kind"] == "gear_mesh" for e in self.edges)
        b0 = self.base
        shoulder = len(self.shafts) == 1 and self.spec[b0].get("sub_stepped")
        first = next((self.name(r) for r in sorted(self.riders[b0], key=lambda r: self.gy(b0, r))), None)
        if shoulder:
            bname = f"Shoulder face of the {base['name']} (the {first or 'hub'} locates on it)"
        elif meshy:
            bname = "Mesh plane (first gear pair)"
        elif self.sub_line and first:
            bname = f"Mid-plane of the {first}"
        else:
            bname = "Mid-plane XZ"
        csys = (f"Origin on the {base['name']} axis" + (" in the mesh plane of the first gear pair" if meshy else
                                                         " at its shoulder face" if shoulder else "")
                + " (datums A, B, C); the shafts run along +Y, parallel, in the plane Z = 0 (datum A, the plane of "
                "the shaft axes); +X from the input shaft towards the next one; +Z up.")
        if self.sub_line and len(self.shafts) == 1:
            csys = (f"Origin on the {base['name']} axis" + (" at its shoulder face" if shoulder else
                                                             f" in the mid-plane of the {first}" if first else "")
                    + f" (datums A, B, C); the {base['name']} is the base (fixed), its axis along +Y in the plane "
                    "Z = 0 (datum A); +Z up.")
        datums = [{"id": "A", "kind": "plane", "name": "Horizontal plane through the shaft axis"
                   if self.sub_line and len(self.shafts) == 1 else "Plane of the shaft axes", "origin": [0, 0, 0],
                   "normal": [0, 0, 1]},
                  {"id": "B", "kind": "plane", "name": bname, "origin": [0, 0, 0], "normal": [0, 1, 0]},
                  {"id": "C", "kind": "plane", "name": f"{base['name']} axis plane (YZ)", "origin": [0, 0, 0],
                   "normal": [1, 0, 0]}]
        return csys, datums

    def _summary_notes(self) -> None:
        """What the solve did, in plain words (the skeleton's notes, shown at the ICD gate)."""
        loops = [e for n, e in enumerate(self.edges) if n not in self.tree and not e.get("loop_bad") and e.get("a")]
        words = []
        for e in self.edges:
            if e["kind"] == "gear_mesh":
                words.append(f"{self.name(e['ra'])} / {self.name(e['rb'])} mesh at a = {e['dist']:g} mm")
            elif e["kind"] == "belt_drive":
                words.append(f"{self.name(e['ra'])} / {self.name(e['rb'])} belted at C = {e['dist']:g} mm"
                             + (" (C = D1 + D2, assumed)" if e.get("rule") else ""))
            elif e["kind"] == "coupling":
                words.append(f"{self.name(e['motor'] or e['a'])} coupled to {self.name(e['b'])}")
        head = "Laid out from the design's connections: " + ("; ".join(words) + ". " if words else "")
        if self.kind == "gearbox":
            names = self.name(self.housing)
            head += (f"Gearbox: the shafts run along +Y in the side walls of the {names}, each in a bearing seat per "
                     "wall, so the bores are at the centre distances (the loop through the housing is consistent by "
                     "construction); the gears mesh in the cavity on the plane Y = 0"
                     + ("; the caps are bolted over the seats (coaxial)" if self.hm["caps"] else "") + ".")
            st = [f"{self.name(sh)} steps to Ø{self.spec[sh]['body']:g} behind the {self.name(r)} (a {COLLAR:g} mm "
                  "collar in the cavity)" for sh in self.shafts for r in self.riders[sh]
                  if r in self.stops[sh] and self.spec[sh].get("body")]
            if st:
                head += " Shoulders inside the housing: " + "; ".join(st) + "."
        elif self.kind == "guide":
            xs = [self.at[r][k][0] for r, k in self.rod_copies]  # type: ignore[index]
            r0 = self.rod_copies[0][0]
            head += (f"Guide rods: {len(xs)} x Ø{self.spec[r0]['seat']:g} along +Y, "
                     f"{_r2((max(xs) - min(xs)) / max(1, len(xs) - 1)):g} mm apart, {self.h:g} mm above the top face "
                     f"of the {self.name(self.base)}, each end flush in its end block; the carriage slides on them, "
                     "centred between the blocks.")
        elif self.kind == "pin":
            p = self.pin
            head += (f"Pin joint: {self.name(p['x'].guest)} pivots on a Ø{p['d']:g} x {p['length']:g} pin along +Y "
                     f"between the lugs of the {self.name(self.base)}, {self.spec[self.base]['H'] + p['axis'][1]:g} mm "
                     "above its underside; the arm lies along +X in the slot.")
        elif self.kind == "mount":
            head += (f"The {self.name(self.base)} is the base (its top face datum A); "
                     + "; ".join(f"{self.ncopies(k)} x {self.name(k)} bolted {'under' if self.under else 'on'} it"
                                 + (" at its corners" if self.ncopies(k) == 4 else "") for k in self.connectors)
                     + "".join(f"; each {self.name(pv['member'])} pivots on its own {self.name(pv['host'])} (copy by "
                               "copy) on a pivot bolt along Y" for pv in self.pivots[:1])
                     + ". Copies pair with their host's copies: every copy has its own interfaces.")
        elif self.kind == "blocks":
            head += (f"Blocks bolted on their host's top face: the {self.name(self.base)} is the base (its top face "
                     "datum A), each part centred on it (side by side along +X when several), its bolts no more than "
                     "the design plans.")
        elif self.kind == "plate" and getattr(self, "frameless", False):
            head += ("No frame in the design: the shaft is the base (its axis datum A), each bearing in its support, "
                     "the supports standing across the shaft, centred on their bearings.")
        elif self.kind == "plate":
            head += (f"The shafts run along +Y {self.h:g} mm above the top face of the {self.name(self.base)}, each in "
                     "its pillow blocks (the seat open outboard, the shoulder wall inboard)"
                     + (", the motor coaxial on its bracket" if self.motor_edges else "")
                     + "; every path from the plate to an axis gives the same height.")
        elif self.sub_line:
            sh = self.shafts[0]
            riders = ", ".join(self.name(r) for s in self.shafts for r in self.riders[s]) or "nothing yet"
            s = self.spec[sh]
            stepped = (f" {self.name(sh)} is stepped: a Ø{s['seat']:g} seat and a Ø{s['body']:g} step; the hub bears on "
                       "the shoulder" + (" (datum B, Y = 0)." if len(self.shafts) == 1 else ".")) if s.get("body") else ""
            head += (f"Shaft sub-assembly: no housing or bearings in the design, so "
                     f"{'the shafts are' if len(self.shafts) > 1 else self.name(sh) + ' is'} the base, along +Y, "
                     f"carrying {riders}.{stepped} What carries the shaft (bearings, a housing) is outside this "
                     "program: it is delivered as a sub-assembly.")
        else:
            nb = sum(len(self.spec[s].get("brg") or []) for s in self.shafts)
            head += ("Shaft line: no housing or base plate in the design, so the shafts run along +Y on their own "
                     f"bearings ({nb} on the shaft journals), parallel at their centre distances; the first pair "
                     "meets on the plane Y = 0. The bearings still need something to stand on (pedestals or a frame): "
                     "not in this design.")
        if loops:
            head += " Closed loops checked: " + "; ".join(self._edge_words(e) for e in loops) + " agree."
        self.notes.insert(0, head)


def _up(x: float, step: float) -> float:
    """Rounded up to the next ``step`` mm (sizes the layout makes up: pillow blocks, brackets, the base plate)."""
    return _r2(math.ceil(float(x) / step - 1e-9) * step)


def _grid(cxy: list[float], L: float, W: float, count: int, inset: float) -> list[list[float]]:
    ex, ey = L / 2 - inset, W / 2 - inset
    if count == 2 and W > L:
        return [[_r2(cxy[0]), _r2(cxy[1] - ey)], [_r2(cxy[0]), _r2(cxy[1] + ey)]]
    if count == 2:
        return [[_r2(cxy[0] - ex), _r2(cxy[1])], [_r2(cxy[0] + ex), _r2(cxy[1])]]
    if count >= 6:
        return [[_r2(cxy[0] + sx), _r2(cxy[1] + sy)] for sy in (-ey, ey) for sx in (-ex, 0.0, ex)]
    return [[_r2(cxy[0] + sx), _r2(cxy[1] + sy)] for sy in (-ey, ey) for sx in (-ex, ex)]


def _circle(cxy: list[float], pcd: float, count: int) -> list[list[float]]:
    return [[_r2(cxy[0] + pcd / 2 * math.cos(2 * math.pi * k / count + math.pi / count)),
             _r2(cxy[1] + pcd / 2 * math.sin(2 * math.pi * k / count + math.pi / count))] for k in range(count)]
