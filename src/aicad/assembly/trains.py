"""Fitz's shaft lines and gear trains (smart assembly, ASM-010 / ASM-019).

A housing-less mechanism (gears, shafts, bearings, pulleys) has no block to mount things on: the parts locate each
other. Fitz builds it the way an engineer lays it out on paper, every placement computed so its mates hold by
construction (the solver only confirms them):

- **lines**: each shaft is a line. Its drive elements (gears, pulleys, couplings: "hubs") sit on the longest seat,
  centred on the keyway (a Toolbox shaft's keyway is at mid-length) else on the seat's middle, side by side with a
  2 mm gap. Two bearings per shaft, one either side of the hubs, each on a journal of its bore: against a shoulder
  facing the hubs, else flush with the free shaft end, else 5 mm from the hub. A bearing closer than 1 mm to a hub,
  or off its journal, is reported, never forced.
- **meshes**: gears pair in the order they are listed, each with the last gear placed, when the modules agree. The
  second gear's axis is parallel to the first at the centre distance a = m (z1 + z2) / 2, its faces on the same
  mid-plane, its teeth phased so a tooth space faces the partner's tooth at the line of centres; its shaft is then
  placed from the gear. Gear i goes on shaft i.
- **frame** (a free choice, PD): the first shaft is the base, fixed at the origin with its axis along +Y and its
  first hub's mid-plane on Y = 0 (the Design Office's gearbox convention: shafts along Y, gears meshing on the plane
  Y = 0); the mesh row runs along +X, so the shafts lie side by side in the horizontal plane. An existing shaft in
  the assembly is used where it is instead; its row runs along the perpendicular closest to +X.
- **mates**: hub or bearing on a shaft: concentric on the seat + an axial mate (coincident with a shoulder, flush
  with a shaft end, else a distance from the shaft's end face); gear pair: a gear mesh mate (axes parallel at the
  centre distance) + flush (or distance) mid-planes; next shaft on its gear like any hub. Motion: one revolute
  joint per line (the shaft and its hubs turn; bearings stay with the ground) and a gear joint per mesh at
  -z1/z2, so the motion range check turns the train at its ratio.

Whatever cannot be placed is named with a machine-readable code (``CODES`` in ``fitz``) and placed beside the
assembly. Tooth phasing is exact for Toolbox gears (a tooth centred on their +X); a gear recognised from a user's
part has no known tooth phase and is reported as unchecked. Fits and tolerances are not modelled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from aicad import toolbox
from aicad.assembly import librarian, service, store, xform

HUB_GAP = 2.0       # mm between two hubs on one shaft
BEARING_GAP = 5.0   # mm from a hub to a bearing that no shoulder or shaft end locates
MIN_CLEAR = 1.0     # mm: a bearing closer than this to a hub is not placed
GEAR_WORDS = {"gear", "pinion", "wheel", "spur", "gearwheel"}
SHAFT_WORDS = {"shaft", "axle", "spindle", "arbor", "arbour"}
HUB_WORDS = {"pulley", "sprocket", "coupling", "hub", "sheave", "flywheel", "collar", "cam", "impeller", "fan",
             "roller", "drum", "rotor"}
BASE_R = np.column_stack([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])  # local Z -> world +Y, X -> +X


# ----------------------------------------------------------------------------- roles (plan and run)
def item_role(it: dict[str, Any]) -> str | None:
    """gear | shaft | bearing | hub from a plan item (Toolbox code, else the part's name)."""
    if it.get("source") == "toolbox":
        return {"spur_gear": "gear", "shaft": "shaft", "bearing": "bearing"}.get(str(it.get("code")))
    if it.get("source") == "project":
        toks = set(librarian._tok(str(it.get("title") or "")))
        if toks & GEAR_WORDS:
            return "gear"
        if toks & SHAFT_WORDS:
            return "shaft"
        if toks & HUB_WORDS:
            return "hub"
    return None


def _free_shafts(root: Path, doc: dict[str, Any]) -> list[str]:
    """Shafts already in the assembly that carry nothing yet (no mate on any of their faces)."""
    used = {s["inst"] for m in doc["mates"] for s in (m["a"], m["b"])}
    out = []
    for i in doc["instances"]:
        if i.get("group") or i["id"] in used:
            continue
        p = store.part(root, i["part"]) or {}
        if p.get("kind") == "toolbox" and p.get("code") == "shaft" or \
                p.get("kind") == "project" and set(librarian._tok(i["name"].split("<")[0])) & SHAFT_WORDS:
            out.append(i["id"])
    return out


@dataclass
class Unit:
    item: str | None          # plan item id (None: a shaft already in the assembly)
    role: str
    title: str
    k: int = 0                # copy number within its item
    key: str | None = None
    inst: str | None = None   # an existing instance
    params: dict[str, Any] | None = None   # Toolbox parameters (gears are re-bored to their shaft)
    code: str | None = None


@dataclass
class Train:
    units: list[Unit] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)

    def of(self, role: str) -> list[Unit]:
        return [u for u in self.units if u.role == role]


def select(root: Path, doc: dict[str, Any], items: list[dict[str, Any]]) -> Train | None:
    """The items Fitz assembles as shaft lines / a gear train, or None (the ordinary seat / mount path applies).

    A train needs a new shaft with something to put on it, two gears or more, or a gear / hub plus a shaft (new or
    already in the assembly, carrying nothing). Bearings join a train; on their own they keep the seat path."""
    tr = Train()
    for it in items:
        if not it.get("enabled", True) or it.get("source") == "new" or it.get("action") == "design" or it.get("inst"):
            continue
        role = item_role(it)
        if role is None:
            continue
        qty = max(1, min(librarian.MAX_QTY, int(it.get("qty") or 1)))
        tr.items.append(it)
        for k in range(qty):
            tr.units.append(Unit(it["id"], role, str(it.get("title") or role), k,
                                 params=dict(it["params"]) if it.get("params") else None, code=it.get("code")))
    new_shafts = len(tr.of("shaft"))
    drives = len(tr.of("gear")) + len(tr.of("hub"))
    existing = _free_shafts(root, doc) if drives else []
    if not (new_shafts and (drives or tr.of("bearing")) or len(tr.of("gear")) >= 2 or drives and existing):
        return None
    tr.units = [Unit(None, "shaft", service.display_names(doc)[i], inst=i) for i in existing] + tr.units
    return tr


# ----------------------------------------------------------------------------- part geometry (local frames)
def _planes_on_axis(refs: dict[str, Any], p: np.ndarray, v: np.ndarray) -> list[tuple[float, int, float]]:
    """(t along v, face id, normal·v) of the flat faces perpendicular to an axis and centred on it."""
    out = []
    for fid, f in sorted(refs["faces"].items(), key=lambda kv: int(kv[0])):
        if f["kind"] != "plane":
            continue
        c = float(xform.unit(f["v"]) @ v)
        if abs(abs(c) - 1) > 1e-9:
            continue
        q = np.asarray(f["p"], dtype=float) - p
        t = float(q @ v)
        if float(np.linalg.norm(q - v * t)) > 1e-3:
            continue
        out.append((t, int(fid), c))
    return out


def shaft_geom(root: Path, key: str) -> dict[str, Any] | None:
    """Axis, coaxial seats (t along the axis), end faces and keyway centre of a shaft part."""
    from aicad.assembly import fitz

    ss = fitz.seats(root, key)
    if not ss:
        return None
    main = ss[0]
    p, v = np.asarray(main["p"], dtype=float), np.asarray(main["v"], dtype=float)

    def coaxial(s: dict[str, Any]) -> bool:
        w = np.asarray(s["p"], dtype=float) - p
        return abs(abs(float(np.asarray(s["v"]) @ v)) - 1) < 1e-9 and float(np.linalg.norm(w - v * float(w @ v))) < 1e-3

    seats = [s for s in ss if coaxial(s)]   # canonical directions and feet: one t parameter for all of them
    planes = _planes_on_axis(store.refs(root, key), p, v)
    lo_end = min(((t, f) for t, f, c in planes if c < 0), default=None)
    hi_end = max(((t, f) for t, f, c in planes if c > 0), default=None)
    part = store.part(root, key) or {}
    key_c = None
    if part.get("kind") == "toolbox" and part.get("code") == "shaft":
        key_c = float(part["params"]["L"]) / 2 - float(p @ v)  # keyway centred at mid-length (z = L / 2)
    t_lo = min([s["lo"] for s in seats] + ([lo_end[0]] if lo_end else []))
    t_hi = max([s["hi"] for s in seats] + ([hi_end[0]] if hi_end else []))
    return {"p": p, "v": v, "seats": seats, "lo_end": lo_end, "hi_end": hi_end, "key_c": key_c, "t_lo": t_lo,
            "t_hi": t_hi, "d": max(s["d"] for s in seats)}


def elem_geom(root: Path, key: str) -> dict[str, Any] | None:
    """A gear / hub / bearing in its own frame: axis (p, v), bore face and diameter, low / high faces (t along v),
    width, x reference (a Toolbox gear's tooth is centred on +X), and gear data when it is one."""
    part = store.part(root, key)
    if part is None:
        return None
    refs = store.refs(root, key)
    if part.get("kind") == "toolbox" and part.get("code") in ("spur_gear", "bearing"):
        prm = part["params"]
        if part["code"] == "spur_gear":
            w, bore = float(prm["B"]), float(prm["BORE"])
            gear = {"module": float(prm["M"]), "teeth": int(prm["Z"]), "phase_known": True}
        else:
            bore, _D, w = (float(x) for x in toolbox.BEARING[int(prm["SERIES"])])
            gear = None
        b = service._tb_ref(root, key, "axis", r=bore / 2)
        lo = service._tb_ref(root, key, "plane", z=0.0, nz=-1.0)
        hi = service._tb_ref(root, key, "plane", z=w, nz=1.0)
        if b is None or lo is None or hi is None:
            return None
        return {"p": np.zeros(3), "v": np.array([0.0, 0.0, 1.0]), "x": np.array([1.0, 0.0, 0.0]), "bore": bore,
                "bore_face": b["id"], "lo": 0.0, "hi": w, "lo_face": lo["id"], "hi_face": hi["id"], "w": w, "gear": gear}
    info = part.get("info") or {}
    comp = info.get("component") or {}
    bb = info.get("bbox") or [0, 0, 0, 0, 0, 0]
    ctr = np.array([(bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2])
    holes = [h for h in info.get("holes", []) if h.get("full", True) and h.get("faces")]
    if comp.get("kind") == "spur_gear" and comp.get("axis"):
        v = xform.unit(comp["axis"])
        p = np.asarray(comp.get("origin") or ctr, dtype=float)
    else:
        v, p = None, ctr
    best = None
    # the bore: a hole on the part's axis (through its centre); a through hole before a blind recess, then the
    # narrowest (a pulley's rim recess or a counterbore is wider than the bore the shaft passes)
    for h in holes:
        a = xform.unit(h["axis"])
        if v is not None and abs(abs(float(a @ v)) - 1) > 1e-6:
            continue
        c = np.asarray(h["center"], dtype=float)
        off = float(np.linalg.norm((p - c) - a * float((p - c) @ a)))
        rank = (not h.get("through"), float(h["d"]))
        if off < max(0.5, 0.01 * float(np.linalg.norm(np.subtract(bb[3:], bb[:3])))) and \
                (best is None or rank < (not best.get("through"), float(best["d"]))):
            best = h
    if best is None:
        return None
    v = service._canon(best["axis"]) if v is None else service._canon(v)
    ex = (best.get("exact") or {})
    p = np.asarray(ex.get("p") or best["center"], dtype=float)
    planes = _planes_on_axis(refs, p, v)
    los = [(t, f) for t, f, c in planes if c < 0]
    his = [(t, f) for t, f, c in planes if c > 0]
    if not los or not his:
        return None
    lo, lo_f = min(los)
    hi, hi_f = max(his)
    gear = None
    cp = comp.get("params") or {}
    if comp.get("kind") == "spur_gear" and cp.get("teeth") and cp.get("module"):
        gear = {"module": float(cp["module"]), "teeth": int(cp["teeth"]), "phase_known": False}
    return {"p": p, "v": v, "x": xform.perp(v), "bore": float(best["d"]), "bore_face": int(best["faces"][0]),
            "lo": lo, "hi": hi, "lo_face": lo_f, "hi_face": hi_f, "w": hi - lo, "gear": gear}


# ----------------------------------------------------------------------------- pure layout helpers
def gear_bore_ok(module: float, teeth: int, d: float) -> bool:
    """The Toolbox gear generator's rule: the bore stays inside the root circle minus a rim of one module."""
    rf = module * teeth / 2 - 1.25 * module
    return 0 < d / 2 < rf - module


def centre_distance(m: float, z1: int, z2: int) -> float:
    return m * (z1 + z2) / 2


def phase(theta: float, phase_a: float, za: int, zb: int) -> float:
    """Tooth phase (deg, about the common axis direction) of gear b meshing gear a, b in direction ``theta`` (deg)
    from a, a turned by ``phase_a``; both gears have a tooth centred on their +X at phase 0.

    At the line of centres a's tooth sits u pitches behind the line (u in [0, 1)); rolling contact keeps
    u + v constant, and a tooth of b fills a's tooth space when v = 1/2 - u, so b's tooth sits v of its pitches
    behind the line seen from b (direction theta + 180°)."""
    pa, pb = 360.0 / za, 360.0 / zb
    u = ((theta - phase_a) % pa) / pa
    v = (0.5 - u) % 1.0
    return round(((theta + 180.0) - v * pb) % pb, 9)


def _frame(axis: np.ndarray, x: np.ndarray) -> np.ndarray:
    z = xform.unit(axis)
    xx = xform.unit(x - z * float(x @ z))
    return np.column_stack([xx, np.cross(z, xx), z])


def place_on_axis(P: np.ndarray, V: np.ndarray, X: np.ndarray, g: dict[str, Any], t0: float) -> np.ndarray:
    """World 4x4 of an element whose axis lies on the line (P, V) with its own axis direction along V, its low face
    at P + V t0, and its x reference along X (perpendicular to V)."""
    R = _frame(V, X) @ _frame(g["v"], g["x"]).T
    low = np.asarray(g["p"], dtype=float) + np.asarray(g["v"], dtype=float) * g["lo"]
    return xform.make(R, P + V * t0 - R @ low)


def stack(sg: dict[str, Any], hubs: list[dict[str, Any]], n_bearings: int, bearing: dict[str, Any] | None
          ) -> dict[str, Any]:
    """Axial layout of one shaft (t along its axis): hub intervals and bearing positions, with problems.

    ``hubs``: [{w, bore}] in order (bores already matched to a seat); ``bearing``: {w, bore} of the bearings.
    Returns {hubs: [{t0, seat}], bearings: [{t0, seat, how, face}], problems: [(code, text)], centre}."""
    probs: list[tuple[str, str]] = []
    out_h: list[dict[str, Any]] = []
    if hubs:
        seat = next((s for s in sg["seats"] if abs(s["d"] - hubs[0]["bore"]) < 1e-3), None)
        W = sum(h["w"] for h in hubs) + HUB_GAP * (len(hubs) - 1)
        if seat is None:
            return {"hubs": [], "bearings": [], "problems": [("bore_mismatch", f"no Ø{hubs[0]['bore']:g} seat")],
                    "centre": None}
        kc = sg.get("key_c")
        c = kc if kc is not None and seat["lo"] + W / 2 - 1e-6 <= kc <= seat["hi"] - W / 2 + 1e-6 else \
            (seat["lo"] + seat["hi"]) / 2
        if W > seat["length"] + 1e-6:
            probs.append(("hub_overhangs_seat", (f"the hubs ({W:g} mm) are longer than the Ø{seat['d']:g} seat "
                                                f"({seat['length']:.4g} mm)")))
        t = c - W / 2
        for h in hubs:
            s_h = next((s for s in sg["seats"] if abs(s["d"] - h["bore"]) < 1e-3 and s["lo"] - 1e-6 <= t + h["w"] / 2
                        <= s["hi"] + 1e-6), seat)
            out_h.append({"t0": t, "seat": s_h})
            t += h["w"] + HUB_GAP
        h0, h1 = c - W / 2, c + W / 2
    else:
        c = (sg["t_lo"] + sg["t_hi"]) / 2
        h0 = h1 = c
    out_b: list[dict[str, Any]] = []
    if bearing and n_bearings:
        bw, bd = bearing["w"], bearing["bore"]
        journals = [s for s in sg["seats"] if abs(s["d"] - bd) < 1e-3]
        for side in ("lo", "hi")[:n_bearings]:
            got = _bearing_side(sg, journals, side, h0, h1, bw)
            if isinstance(got, tuple):
                probs.append(got)
            else:
                out_b.append(got)
    return {"hubs": out_h, "bearings": out_b, "problems": probs, "centre": c}


def _bearing_side(sg: dict[str, Any], journals: list[dict[str, Any]], side: str, h0: float, h1: float, bw: float
                  ) -> dict[str, Any] | tuple[str, str]:
    lo_side = side == "lo"
    cand = [s for s in journals if (s["lo"] < h0 - 1e-6 if lo_side else s["hi"] > h1 + 1e-6)]
    if not cand:
        return ("no_journal_for_bearing", (f"no journal of the bearing bore on the {'first' if lo_side else 'second'} "
                                          "side of the hubs"))
    J = max(cand, key=lambda s: s["hi"]) if lo_side else min(cand, key=lambda s: s["lo"])
    inner, outer = ("hi", "lo") if lo_side else ("lo", "hi")
    tries: list[tuple[float, str, int | None]] = []
    e_in, e_out = J["ends"].get(inner), J["ends"].get(outer)
    if e_in and e_in["shoulder"] and (e_in["t"] <= h0 + 1e-6 if lo_side else e_in["t"] >= h1 - 1e-6):
        tries.append((e_in["t"] - bw if lo_side else e_in["t"], "shoulder", e_in["face"]))
    if e_out and not e_out["shoulder"]:
        tries.append((e_out["t"] if lo_side else e_out["t"] - bw, "end", e_out["face"]))
    tries.append((h0 - BEARING_GAP - bw if lo_side else h1 + BEARING_GAP, "gap", None))
    ch_lo = float((J["ends"].get("lo") or {}).get("chamfer") or 0.0)
    ch_hi = float((J["ends"].get("hi") or {}).get("chamfer") or 0.0)
    for t0, how, face in tries:
        on = J["lo"] - ch_lo - 1e-6 <= t0 and t0 + bw <= J["hi"] + ch_hi + 1e-6
        clear = (h0 - (t0 + bw) if lo_side else t0 - h1) >= MIN_CLEAR - 1e-9 or h0 == h1
        if on and clear:
            return {"t0": t0, "seat": J, "how": how, "face": face, "side": side}
    return ("no_room_for_bearing", (f"the Ø{J['d']:g} journal leaves no room for a {bw:g} mm bearing "
                                   f"{MIN_CLEAR:g} mm clear of the hubs"))


# ----------------------------------------------------------------------------- run: classify, assign, bore
def _key_of(doc: dict[str, Any], u: Unit) -> str | None:
    return str(service._inst(doc, u.inst)["part"]) if u.inst else u.key


def prepare(root: Path, doc: dict[str, Any], tr: Train) -> dict[str, Any]:
    """With every key known except Toolbox gears' (their bore follows the shaft): classify user parts by geometry,
    assign gears / hubs / bearings to shafts, choose each Toolbox gear's bore. Returns the layout skeleton
    {lines: [{shaft, sg, hubs, bearings}], loose: [gears without a shaft], problems: [(unit, code, text)],
    spare: [bearings], geo: {id(unit): geometry}}."""
    probs: list[tuple[Unit, str, str]] = []
    geo: dict[int, dict[str, Any] | None] = {}
    for u in tr.units:
        if u.role == "gear" and u.code == "spur_gear":
            continue
        key = _key_of(doc, u)
        if u.role == "shaft":
            geo[id(u)] = shaft_geom(root, key) if key else None
            if geo[id(u)] is None:
                probs.append((u, "no_shaft_geometry", f"{u.title}: no round seat recognised on it"))
            continue
        g = elem_geom(root, key) if key else None
        geo[id(u)] = g
        if g is None:
            probs.append((u, "no_bore", f"{u.title}: no bore recognised on its axis"))
        elif u.role == "gear" and not g.get("gear"):
            u.role = "hub"
            probs.append((u, "gear_not_recognised", (f"{u.title}: no teeth recognised, so it goes on its shaft as a "
                                                    "plain hub and is not meshed")))
        elif u.role == "hub" and g.get("gear"):
            u.role = "gear"
    ok = {id(u) for u in tr.units if geo.get(id(u), True) is not None}
    shafts = [u for u in tr.of("shaft") if id(u) in ok]
    gears = [u for u in tr.of("gear") if id(u) in ok]
    hubs = [u for u in tr.of("hub") if id(u) in ok]
    bearings = [u for u in tr.of("bearing") if id(u) in ok]
    lines: list[dict[str, Any]] = [{"shaft": s, "sg": geo[id(s)], "hubs": [], "bearings": []} for s in shafts]
    loose: list[Unit] = []
    for k, g in enumerate(gears):
        (lines[k]["hubs"] if k < len(lines) else loose).append(g)
    if lines:
        for g in loose:
            probs.append((g, "gear_without_shaft", ("more gears than shafts, so it is meshed without a shaft (add a "
                                                   "shaft for it)")))
    for h in hubs:
        tgt = next((ln for ln in lines if not ln["hubs"]), lines[0] if lines else None)
        if tgt is None:
            probs.append((h, "no_shaft_for_hub", f"{h.title}: no shaft to put it on"))
        else:
            tgt["hubs"].append(h)
    # Toolbox gears: bore to the longest seat of their shaft that the gear can take
    for ln in lines:
        for g in [x for x in ln["hubs"] if x.role == "gear" and x.code == "spur_gear"]:
            prm = g.params or {}
            m, z = float(prm.get("M", 2)), int(prm.get("Z", 24))
            seat = next((s for s in ln["sg"]["seats"] if gear_bore_ok(m, z, s["d"])), None)
            if seat is None:
                ln["hubs"].remove(g)
                loose.append(g)
                probs.append((g, "gear_bore_too_large", (f"{ln['shaft'].title} is too thick for its bore (over "
                                                        f"Ø{2 * (m * z / 2 - 2.25 * m):.1f} leaves no rim), so it is "
                                                        "meshed without a shaft")))
                continue
            g.params = toolbox.normalize("spur_gear", {**prm, "BORE": seat["d"]})
    it = iter(bearings)
    for ln in lines:
        ln["bearings"] = [b for b in (next(it, None), next(it, None)) if b is not None]
    return {"lines": lines, "loose": loose, "problems": probs, "spare": list(it), "geo": geo}


# ----------------------------------------------------------------------------- run: place and mate
def _mate(root: Path, doc: dict[str, Any], t: str, a: tuple[str, int], b: tuple[str, int], value: float = 0.0,
          flip: bool = False) -> dict[str, Any]:
    return service.make_mate(root, doc, {"type": t, "a": {"inst": a[0], "kind": "face", "id": a[1]},
                                         "b": {"inst": b[0], "kind": "face", "id": b[1]}, "value": value, "flip": flip})


def build(root: Path, doc: dict[str, Any], tr: Train, lay: dict[str, Any]) -> dict[str, Any]:
    """Insert, place and mate the train (every key known). Returns {made: {item: [inst]}, log: [{text, tone,
    code?}], outcomes: [{code, severity, item, inst, name, text}], mated, loose, base, joints}."""
    from aicad.assembly import motion

    res: dict[str, Any] = {"made": {}, "log": [], "outcomes": [], "mated": 0, "loose": 0, "base": 0, "joints": 0}
    geo = lay["geo"]
    for u in tr.units:
        if u.role == "gear" and u.code == "spur_gear" and u.key:
            geo[id(u)] = elem_geom(root, u.key)

    def nm(iid: str) -> str:
        return service.display_names(doc)[iid]

    def say(text: str, tone: str = "ok", code: str | None = None) -> None:
        res["log"].append({"text": text, "tone": tone, **({"code": code} if code else {})})

    def outcome(code: str, u: Unit | None, iid: str | None, text: str, severity: str = "warn") -> None:
        res["outcomes"].append({"code": code, "severity": severity, "item": u.item if u else None, "inst": iid,
                                "name": nm(iid) if iid else (u.title if u else None), "text": text})
        say(text, "warn" if severity == "warn" else "muted", code)

    def add(u: Unit, T: np.ndarray | None) -> str:
        if u.inst:
            return u.inst
        inst = service.add_instance(root, doc, str(u.key), T=xform.to12(T) if T is not None else None)
        if u.item:
            res["made"].setdefault(u.item, []).append(inst["id"])
        return str(inst["id"])

    def beside(u: Unit, code: str, why: str) -> None:
        iid = add(u, None)
        res["loose"] += 1
        outcome(code, u, iid, f"{nm(iid)} placed beside the assembly: {why}")

    for u, code, text in lay["problems"]:
        if code in ("gear_without_shaft", "gear_not_recognised", "gear_bore_too_large"):
            continue  # reported where the part is placed
        beside(u, code, text.split(": ", 1)[-1])

    placed_gears: list[tuple[Unit, str, float]] = []   # (unit, instance, tooth phase in degrees)
    gear_joint: dict[str, str] = {}                     # gear instance -> the joint it turns with
    lines = lay["lines"]
    notes = {id(u): (code, text) for u, code, text in lay["problems"]}

    def add_joint(body: dict[str, Any]) -> str | None:
        joints = doc.setdefault("joints", [])
        if len(joints) >= motion.MAX_JOINTS:
            return None
        j = motion.clean_joint(body, {i["id"] for i in doc["instances"]}, joints)
        j["id"] = store.next_id(doc, "j")
        joints.append(j)
        res["joints"] += 1
        return str(j["id"])

    # the frame: the first shaft (else the first gear) is the base
    first = lines[0]["shaft"] if lines else (lay["loose"][0] if lay["loose"] else None)
    if first is None:
        for b in lay["spare"]:
            beside(b, "bearing_spare", "no shaft to carry it")
        return res
    empty = not doc["instances"]
    origin = np.zeros(3)
    if first.inst:
        Ts0: np.ndarray | None = xform.from12(service._inst(doc, first.inst)["T"])
        A = xform.unit(Ts0[:3, :3] @ lines[0]["sg"]["v"])  # type: ignore[index]
    else:
        Ts0 = None
        A = np.array([0.0, 1.0, 0.0])
        if not empty:   # nothing in the assembly carries the train: build it beside
            parts = service._parts(root, doc)
            lo, hi = service.world_box(doc, parts)  # type: ignore[misc]
            origin = np.array([hi[0] + 120.0, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2])
    X = np.array([1.0, 0.0, 0.0])
    e1 = X - A * float(X @ A)
    if float(np.linalg.norm(e1)) < 1e-6:
        e1 = np.array([0.0, 0.0, 1.0]) - A * float(A[2])
    e1 = xform.unit(e1)

    def phase_known(u: Unit) -> bool:
        return bool(((geo.get(id(u)) or {}).get("gear") or {}).get("phase_known"))

    def mesh(g: dict[str, Any]) -> tuple[np.ndarray, float, tuple[Unit, str, float]] | None:
        """World pose and tooth phase of a gear in mesh with the last gear placed (None: modules differ)."""
        if not placed_gears:
            return None
        pu, pid, pph = placed_gears[-1]
        pg = geo[id(pu)]
        if abs(pg["gear"]["module"] - g["gear"]["module"]) > 1e-9:
            return None
        Tp = xform.from12(service._inst(doc, pid)["T"])
        mid_p = xform.pt(Tp, pg["p"] + pg["v"] * (pg["lo"] + pg["hi"]) / 2)
        a = centre_distance(g["gear"]["module"], pg["gear"]["teeth"], g["gear"]["teeth"])
        ph = phase(0.0, pph, pg["gear"]["teeth"], g["gear"]["teeth"])
        Xg = xform.rot(A, math.radians(ph)) @ e1
        return place_on_axis(mid_p + e1 * a, A, Xg, g, -g["w"] / 2), ph, placed_gears[-1]

    def mesh_mates(u: Unit, iid: str, g: dict[str, Any], partner: tuple[Unit, str, float]) -> None:
        pu, pid, _ = partner
        pg = geo[id(pu)]
        a = centre_distance(g["gear"]["module"], pg["gear"]["teeth"], g["gear"]["teeth"])
        _mate(root, doc, "gear", (pid, pg["bore_face"]), (iid, g["bore_face"]), value=a)
        if abs(pg["w"] - g["w"]) < 1e-9:
            _mate(root, doc, "flush", (pid, pg["hi_face"]), (iid, g["hi_face"]))
        else:   # mid-planes together: the narrower gear's face sits half the width difference inside the wider's
            (na, ga), (nb, gb) = sorted([((pid, pg["hi_face"]), pg), ((iid, g["hi_face"]), g)], key=lambda x: x[1]["w"])
            _mate(root, doc, "distance", na, nb, value=(gb["w"] - ga["w"]) / 2, flip=True)
        res["mated"] += 1
        both = phase_known(pu) and phase_known(u)
        say(f"Fitz meshed {nm(iid)} with {nm(pid)}: axes parallel at {a:g} mm = m(z1+z2)/2 = "
            f"{g['gear']['module']:g}×({pg['gear']['teeth']}+{g['gear']['teeth']})/2, faces on one mid-plane"
            + (", teeth phased" if both else ""))
        if not both:
            outcome("tooth_phase_unchecked", u, iid, f"{nm(iid)}: its tooth phase is not known (a gear from your "
                                                     "parts), so it may need turning half a tooth to mesh; the "
                                                     "interference check shows it", "info")

    def axial(sid: str, sg: dict[str, Any], eid: str, g: dict[str, Any], t0: float, how: str | None = None,
              face: int | None = None, side: str | None = None) -> None:
        if how == "shoulder" and face is not None:
            _mate(root, doc, "coincident", (sid, face), (eid, g["hi_face"] if side == "lo" else g["lo_face"]))
        elif how == "end" and face is not None:
            _mate(root, doc, "flush", (sid, face), (eid, g["lo_face"] if side == "lo" else g["hi_face"]))
        elif sg["lo_end"] is not None:
            val = t0 - sg["lo_end"][0]
            if abs(val) < 1e-9:
                _mate(root, doc, "flush", (sid, sg["lo_end"][1]), (eid, g["lo_face"]))
            else:
                _mate(root, doc, "distance", (eid, g["lo_face"]), (sid, sg["lo_end"][1]), value=val, flip=True)
        elif sg["hi_end"] is not None:
            val = sg["hi_end"][0] - (t0 + g["w"])
            _mate(root, doc, "distance", (eid, g["hi_face"]), (sid, sg["hi_end"][1]), value=max(0.0, val), flip=True)

    def on_shaft(sid: str, sg: dict[str, Any], eid: str, g: dict[str, Any], seat: dict[str, Any], t0: float,
                 **kw: Any) -> None:
        _mate(root, doc, "concentric", (sid, seat["faces"][0]), (eid, g["bore_face"]))
        axial(sid, sg, eid, g, t0, **kw)
        res["mated"] += 1

    def from_end(sg: dict[str, Any], t0: float) -> str:
        return f"{t0 - sg['lo_end'][0]:.4g} mm from its end" if sg["lo_end"] else "centred"

    def drop_line(ln: dict[str, Any], hubs: list[Unit], code: str, why: str) -> None:
        for h in hubs:
            beside(h, code, why)
        beside(ln["shaft"], code, why)
        for b in ln["bearings"]:
            beside(b, code, why)

    for n, ln in enumerate(lines):
        su, sg = ln["shaft"], ln["sg"]
        hubs = list(ln["hubs"])
        hg = [geo[id(h)] for h in hubs]
        bgeo = geo[id(ln["bearings"][0])] if ln["bearings"] else None
        st = stack(sg, [{"w": g["w"], "bore": g["bore"]} for g in hg], len(ln["bearings"]),
                   {"w": bgeo["w"], "bore": bgeo["bore"]} if bgeo else None)
        sname = "the input shaft" if n == 0 else f"shaft {n + 1}"
        hub_ids: list[str] = []
        if hubs and not st["hubs"]:   # no seat for the hubs' bore
            for h in hubs:
                beside(h, "bore_mismatch", f"its Ø{geo[id(h)]['bore']:g} bore fits no seat of {su.title}")
            hubs, hg = [], []
            st = stack(sg, [], len(ln["bearings"]), {"w": bgeo["w"], "bore": bgeo["bore"]} if bgeo else None)
        if n == 0:
            if Ts0 is not None:
                Ts = Ts0
            else:
                R = _frame(A, e1) @ _frame(sg["v"], xform.perp(sg["v"])).T
                Ts = xform.make(R, origin - R @ (sg["p"] + sg["v"] * st["centre"]))
            sid = add(su, Ts)
            if empty:
                res["base"] += 1
                say(f"Fitz fixed {nm(sid)} at the origin as the base, axis along +Y")
            elif not su.inst:
                outcome("train_not_attached", su, sid, f"Nothing in the assembly carries {nm(sid)}: the shaft line is "
                                                       "assembled beside it; mate the shaft or its bearings by hand")
            P, V = xform.pt(Ts, sg["p"]), xform.unit(Ts[:3, :3] @ sg["v"])
            for k, (h, g) in enumerate(zip(hubs, hg, strict=True)):
                t0 = st["hubs"][k]["t0"]
                eid = add(h, place_on_axis(P, V, e1, g, t0))
                hub_ids.append(eid)
                on_shaft(sid, sg, eid, g, st["hubs"][k]["seat"], t0)
                say(f"Fitz put {nm(eid)} on {nm(sid)}: concentric, "
                    f"{'on the keyway, ' if sg.get('key_c') is not None else ''}{from_end(sg, t0)}")
                if h.role == "gear":
                    placed_gears.append((h, eid, 0.0))
        else:
            if not hubs:
                drop_line(ln, [], "no_part_to_mount_shaft", f"no gear or hub goes on {sname}, so nothing locates it")
                continue
            if hubs[0].role != "gear":
                drop_line(ln, hubs, "no_part_to_mount_shaft", f"only a meshing gear locates {sname} (no housing), and "
                                                              "it has none")
                continue
            got = mesh(hg[0])
            if got is None:
                pm = geo[id(placed_gears[-1][0])]["gear"]["module"] if placed_gears else None
                if pm is None:
                    drop_line(ln, hubs, "no_gear_to_mesh", f"no gear to mesh with, so nothing locates {sname}")
                else:
                    drop_line(ln, hubs, "module_mismatch", f"module {hg[0]['gear']['module']:g} doesn't mesh with "
                                                           f"module {pm:g}, so nothing locates {sname}")
                continue
            Tg, ph, partner = got
            gid = add(hubs[0], Tg)
            mesh_mates(hubs[0], gid, hg[0], partner)
            placed_gears.append((hubs[0], gid, ph))
            t0 = st["hubs"][0]["t0"]
            G_loc = place_on_axis(sg["p"], sg["v"], xform.perp(sg["v"]), hg[0], t0)
            Ts = xform.orthonormalize(Tg @ xform.inv(G_loc))
            sid = add(su, Ts)
            hub_ids.append(gid)
            on_shaft(sid, sg, gid, hg[0], st["hubs"][0]["seat"], t0)
            say(f"Fitz put {nm(sid)} through {nm(gid)}: parallel to the input shaft, the gear {from_end(sg, t0)}")
            P, V = xform.pt(Ts, sg["p"]), xform.unit(Ts[:3, :3] @ sg["v"])
            for k in range(1, len(hubs)):
                t0 = st["hubs"][k]["t0"]
                eid = add(hubs[k], place_on_axis(P, V, e1, hg[k], t0))
                hub_ids.append(eid)
                on_shaft(sid, sg, eid, hg[k], st["hubs"][k]["seat"], t0)
                say(f"Fitz put {nm(eid)} on {nm(sid)} beside its gear: concentric, {from_end(sg, t0)}")
        for b, pos in zip(ln["bearings"], st["bearings"], strict=False):
            bg = geo[id(b)]
            eid = add(b, place_on_axis(P, V, e1, bg, pos["t0"]))
            on_shaft(sid, sg, eid, bg, pos["seat"], pos["t0"], how=pos["how"], face=pos["face"], side=pos["side"])
            where = {"shoulder": "against the shoulder", "end": "flush with the shaft end",
                     "gap": f"{BEARING_GAP:g} mm from the hub"}[pos["how"]]
            say(f"Fitz seated {nm(eid)} on the Ø{pos['seat']['d']:g} journal of {nm(sid)}, {where}")
        bprobs = [p for p in st["problems"] if p[0] in ("no_journal_for_bearing", "no_room_for_bearing")]
        for k, b in enumerate(ln["bearings"][len(st["bearings"]):]):
            code, text = bprobs[min(k, len(bprobs) - 1)] if bprobs else ("no_journal_for_bearing", "no journal for it")
            beside(b, code, f"{text} on {nm(sid)}")
        for code, text in st["problems"]:
            if code == "hub_overhangs_seat":
                outcome(code, None, sid, f"On {nm(sid)}: {text}", "info")
        if len(ln["bearings"]) < 2:
            nb = len(ln["bearings"])
            outcome("bearings_short", None, sid, f"{nm(sid)} has {nb or 'no'} bearing{'s' if nb != 1 else ''}: a shaft "
                                                 "needs two to be carried (add more bearings)", "info")
        # motion: the shaft and its hubs turn about its axis; bearings stay with the ground
        mine = [sid] + hub_ids
        jid = add_joint({"type": "revolute", "name": "Input shaft" if n == 0 else f"Shaft {n + 1}",
                         "p": [float(x) for x in P], "dir": [float(x) for x in V], "insts": mine})
        for i in mine:
            if jid:
                gear_joint[i] = jid
    # gears without a shaft: meshed on their own
    for u in lay["loose"]:
        g = geo.get(id(u))
        if g is None or not g.get("gear"):
            beside(u, "no_bore", "no bore recognised on it")
            continue
        if not placed_gears:
            R = _frame(A, e1) @ _frame(g["v"], g["x"]).T
            T = xform.make(R, origin - A * (g["w"] / 2) - R @ (g["p"] + g["v"] * g["lo"]))
            gid = add(u, T)
            placed_gears.append((u, gid, 0.0))
            if empty:
                res["base"] += 1
                say(f"Fitz fixed {nm(gid)} at the origin as the base, axis along +Y")
        else:
            got = mesh(g)
            if got is None:
                beside(u, "module_mismatch", "its module doesn't mesh with the gear before it")
                continue
            T, ph, partner = got
            gid = add(u, T)
            mesh_mates(u, gid, g, partner)
            placed_gears.append((u, gid, ph))
        if id(u) in notes:
            outcome(notes[id(u)][0], u, gid, f"{nm(gid)}: {notes[id(u)][1]}", "info")
        Tg = xform.from12(service._inst(doc, gid)["T"])
        jid = add_joint({"type": "revolute", "name": nm(gid), "p": [float(x) for x in xform.pt(Tg, g["p"])],
                         "dir": [float(x) for x in A], "insts": [gid]})
        if jid:
            gear_joint[gid] = jid
    for ln in lines:
        for h in ln["hubs"]:
            if notes.get(id(h), ("",))[0] == "gear_not_recognised":
                ids = res["made"].get(h.item or "", [])
                outcome("gear_not_recognised", h, ids[-1] if ids else None, f"{h.title}: {notes[id(h)][1]}", "info")
    # gear joints: each mesh turns at -z1/z2
    for k in range(1, len(placed_gears)):
        (ua, ia, _pa), (ub, ib, _pb) = placed_gears[k - 1], placed_gears[k]
        ja, jb = gear_joint.get(ia), gear_joint.get(ib)
        if ja and jb and ja != jb:
            za, zb = geo[id(ua)]["gear"]["teeth"], geo[id(ub)]["gear"]["teeth"]
            add_joint({"type": "gear", "a": ja, "b": jb, "teeth": [za, zb], "name": f"{nm(ia)} → {nm(ib)} ({za}:{zb})"})
    for b in lay["spare"]:
        beside(b, "bearing_spare", "every shaft already has two bearings")
    if Ts0 is None and len(placed_gears) >= 2 and len(lines) >= 2:
        outcome("shafts_not_held", None, None, "No housing holds the shafts: the gear mesh mates keep the centre "
                                               "distances, but each shaft can still swing around the one before it "
                                               "(Fitz set them side by side along +X)", "info")
    return res
