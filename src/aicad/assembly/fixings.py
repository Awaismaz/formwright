"""Keys and retaining rings, recognised on the parts and placed by construction (assembly agent, WORKLIST 51).

The design graph's ``keyed_hub`` and ``ring_retained`` connections (``graph/registry.py``) need two things the shaft
line builder (``trains``) did not have: where a shaft's keyseat and circlip groove are, and where a hub's keyway
points. Everything here reads the exact references (``refs.json``) and the face meshes (``topo.json``) of the cached
part snapshots, in the part's own frame, so it works the same for Toolbox parts and the user's own parts:

- **keyseat** on a shaft: a flat face parallel to the axis, inside a seat cylinder, its outward normal pointing away
  from the axis (the floor), with its two side walls and, for an end-milled (form A) seat, the two half-round ends;
  depth t1 = seat radius minus the floor's distance from the axis, length from the floor face's extent;
- **hub keyway** in a gear / hub bore: a flat face parallel to the axis outside the bore, its normal pointing at the
  axis; t2 = its distance from the axis minus the bore radius;
- **groove** for a DIN 471 ring: a short seat (at most 4 mm) closed by shoulders on both ends whose diameter is the
  ring table's groove diameter d2 for the neighbouring seat diameter d1.

Placement (pure numpy, mates satisfied by construction, the solver confirms them):

- a parallel key lies on the keyseat floor, centred on the keyseat, its length along the shaft axis: coincident
  floor, coincident side wall, and for a round-ended seat concentric ends (a square-ended seat leaves the key free to
  slide along its seat, and that is said);
- a retaining ring sits in its groove against the wall away from the part it holds: concentric with the groove,
  coincident with that wall.

Fits and tolerances are not modelled: a key is at nominal width in a nominal keyseat. Standards values come from the
Toolbox tables (``toolbox.KEY_ROWS``, ``toolbox.DIN471``), which are marked "verify" there.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from aicad import toolbox
from aicad.assembly import service, store, xform

GROOVE_MAX = 4.0   # mm: a seat this short closed by two shoulders is a groove


# ----------------------------------------------------------------------------- small geometry helpers (pure)
def signed_angle(a: Any, b: Any, n: Any) -> float:
    """Angle (rad) from a to b about the axis n (all 3-vectors; a and b perpendicular to n)."""
    a, b, n = (np.asarray(x, dtype=float) for x in (a, b, n))
    return float(math.atan2(float(np.cross(a, b) @ n), float(a @ b)))


def _faces_pos(root: Path, key: str) -> dict[int, np.ndarray]:
    topo = store.read_json(store.part_dir(root, key) / "topo.json") or {}
    out: dict[int, np.ndarray] = {}
    for f in topo.get("faces", []):
        if isinstance(f, dict) and "id" in f and f.get("pos"):
            out[int(f["id"])] = np.asarray(f["pos"], dtype=float).reshape(-1, 3)
    return out


def _radial(c: np.ndarray, p: np.ndarray, v: np.ndarray) -> tuple[float, np.ndarray, float]:
    """(t along v, unit radial direction, radial distance) of point c from the line (p, v)."""
    q = c - p
    t = float(q @ v)
    w = q - v * t
    d = float(np.linalg.norm(w))
    return t, (w / d if d > 1e-9 else np.zeros(3)), d


# ----------------------------------------------------------------------------- recognition
def keyseats(root: Path, key: str, p: Any, v: Any, seats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keyseats of a shaft part (local frame): [{floor, walls, ends, k, t_c, length, b, t1, d, f, rounded}] where k is
    the unit direction from the axis to the keyseat, t_c its centre along v, f the floor's distance from the axis."""
    p, v = np.asarray(p, dtype=float), xform.unit(v)
    refs = store.refs(root, key)["faces"]
    pos = _faces_pos(root, key)
    out: list[dict[str, Any]] = []
    for fid, f in sorted(refs.items(), key=lambda kv: int(kv[0])):
        if f["kind"] != "plane":
            continue
        n = xform.unit(f["v"])
        if abs(float(n @ v)) > 1e-6:
            continue
        c = np.asarray(f["p"], dtype=float)
        t, k, dist = _radial(c, p, v)
        if dist < 1e-3 or float(n @ k) < 1 - 1e-6:
            continue  # a face through the axis, or one looking at it (a hub keyway, a flat's far side)
        seat = next((s for s in seats if s["lo"] - 1e-6 <= t <= s["hi"] + 1e-6 and dist < s["r"] - 0.2), None)
        if seat is None:
            continue
        t1 = seat["r"] - dist
        if not 0.4 <= t1 <= 0.6 * seat["r"]:
            continue
        P = pos.get(int(fid))
        if P is not None and len(P):
            tt = (P - p) @ v
            lo, hi = float(tt.min()), float(tt.max())
        else:
            lo = hi = t
        e = np.cross(v, k)
        walls: dict[str, int] = {}
        ends, b = [], None
        for gid, g in sorted(refs.items(), key=lambda kv: int(kv[0])):
            if g["kind"] == "plane":
                m = xform.unit(g["v"])
                if abs(float(m @ v)) > 1e-6 or abs(float(m @ k)) > 1e-6:
                    continue
                cg = np.asarray(g["p"], dtype=float)
                tg = float((cg - p) @ v)
                lat = float((cg - p) @ e)
                rad = float((cg - p) @ k)
                # a side wall looks into the slot: its normal points back across it
                if lo - 1e-6 <= tg <= hi + 1e-6 and dist - 1e-6 <= rad <= seat["r"] + 1e-6 and float(m @ e) * lat < 0:
                    sgn = "neg" if lat < 0 else "pos"
                    if sgn not in walls:
                        walls[sgn] = int(gid)
                        b = 2 * abs(lat) if b is None else min(b, 2 * abs(lat))
            elif g["kind"] == "axis" and g.get("r") is not None and abs(abs(float(xform.unit(g["v"]) @ k)) - 1) < 1e-6:
                cg = np.asarray(g["p"], dtype=float)
                tg = float((cg - p) @ v)
                if lo - 1e-6 <= tg <= hi + 1e-6 and abs(float((cg - p) @ e)) < 1e-3:
                    ends.append({"face": int(gid), "t": tg, "r": float(g["r"])})
        if b is None:
            continue
        rounded = bool(ends) and all(abs(x["r"] - b / 2) < 1e-3 for x in ends)
        if rounded:
            lo, hi = min(x["t"] for x in ends) - b / 2, max(x["t"] for x in ends) + b / 2
        out.append({"floor": int(fid), "ends": sorted(ends, key=lambda x: x["t"]) if rounded else [],
                    "k": [float(x) for x in k], "t_c": (lo + hi) / 2, "length": hi - lo, "lo": lo, "hi": hi,
                    "b": round(b, 4), "t1": round(t1, 4), "d": seat["d"], "f": dist, "rounded": rounded,
                    "walls": walls, "seat": seat["faces"][0]})
    return out


def hub_keyway(root: Path, key: str, p: Any, v: Any, bore: float) -> dict[str, Any] | None:
    """The keyway of a hub's bore (local frame): {floor, k, b, t2} or None."""
    p, v = np.asarray(p, dtype=float), xform.unit(v)
    refs = store.refs(root, key)["faces"]
    best = None
    for fid, f in sorted(refs.items(), key=lambda kv: int(kv[0])):
        if f["kind"] != "plane":
            continue
        n = xform.unit(f["v"])
        if abs(float(n @ v)) > 1e-6:
            continue
        _t, k, dist = _radial(np.asarray(f["p"], dtype=float), p, v)
        if dist <= bore / 2 + 0.2 or dist > bore / 2 + 0.6 * bore or float(n @ k) > -1 + 1e-6:
            continue
        if best is None or dist < best[1]:
            best = (int(fid), dist, k)
    if best is None:
        return None
    fid, dist, k = best
    e = np.cross(v, k)
    b = None
    for g in refs.values():
        if g["kind"] != "plane":
            continue
        m = xform.unit(g["v"])
        if abs(float(m @ v)) > 1e-6 or abs(float(m @ k)) > 1e-6:
            continue
        cg = np.asarray(g["p"], dtype=float)
        rad = float((cg - p) @ k)
        lat = float((cg - p) @ e)
        if bore / 2 - 1.0 <= rad <= dist + 1e-6 and float(m @ e) * lat < 0:
            b = 2 * abs(lat) if b is None else min(b, 2 * abs(lat))
    return {"floor": fid, "k": [float(x) for x in k], "b": round(b, 4) if b else None, "t2": round(dist - bore / 2, 4)}


def ring_for_groove(d_groove: float, d_shaft: float | None = None) -> int | None:
    """The DIN 471 shaft size d1 whose groove diameter d2 is this groove (the neighbouring seat Ø when known)."""
    hits = [d1 for d1, row in toolbox.DIN471.items() if abs(row[2] - d_groove) < 0.06]
    if d_shaft is not None:
        exact = [d1 for d1 in hits if abs(d1 - d_shaft) < 1e-3]
        if exact:
            return exact[0]
    return min(hits) if hits else None


def grooves(seats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Circlip grooves among a shaft's coaxial seats: [{seat, d2, d1, lo, hi, faces: {lo, hi}}]."""
    out = []
    for s in seats:
        e = s.get("ends") or {}
        lo, hi = e.get("lo"), e.get("hi")
        if not (lo and hi and lo.get("shoulder") and hi.get("shoulder")) or s["length"] > GROOVE_MAX:
            continue
        near = [x["d"] for x in seats if x is not s and x["d"] > s["d"] and
                (abs(x["hi"] - s["lo"]) < 1e-3 or abs(x["lo"] - s["hi"]) < 1e-3)]
        d1 = ring_for_groove(s["d"], max(near) if near else None)
        if d1 is None:
            continue
        out.append({"seat": s, "d2": s["d"], "d1": d1, "lo": s["lo"], "hi": s["hi"],
                    "faces": {"lo": lo["face"], "hi": hi["face"]}, "cyl": s["faces"][0]})
    return out


# ----------------------------------------------------------------------------- part frames of the Toolbox fixings
def key_geom(root: Path, key: str) -> dict[str, Any] | None:
    """A Toolbox parallel key: b, h, L and its bottom, side and end faces (local: length X, width Y, bottom Z = 0)."""
    part = store.part(root, key) or {}
    if part.get("kind") != "toolbox" or part.get("code") != "parallel_key":
        return None
    prm = part["params"]
    b, h, _t1, _t2 = toolbox.key_row(float(prm["D"]))
    L = float(prm["L"])
    refs = store.refs(root, key)["faces"]
    bottom = side = None
    ends: dict[str, int] = {}
    for fid, f in sorted(refs.items(), key=lambda kv: int(kv[0])):
        c, n = np.asarray(f["p"], dtype=float), np.asarray(f["v"], dtype=float)
        if f["kind"] == "plane":
            if abs(n[2] + 1) < 1e-9 and abs(c[2]) < 1e-6:
                bottom = int(fid)
            elif abs(n[1] - 1) < 1e-9 and abs(c[1] - b / 2) < 1e-6:
                side = int(fid)
        elif f["kind"] == "axis" and f.get("r") is not None and abs(float(f["r"]) - b / 2) < 1e-6:
            ends["hi" if c[0] > 0 else "lo"] = int(fid)
    if bottom is None:
        return None
    return {"b": b, "h": h, "L": L, "D": float(prm["D"]), "bottom": bottom, "side": side, "ends": ends}


def ring_geom(root: Path, key: str) -> dict[str, Any] | None:
    """A Toolbox retaining ring: bore d2, thickness s, its bore and two faces (local: axis Z, faces Z 0 and s)."""
    part = store.part(root, key) or {}
    if part.get("kind") != "toolbox" or part.get("code") != "retaining_ring":
        return None
    s, _b, d2, _m, _n = toolbox.ring_row(float(part["params"]["D"]))
    bore = service._tb_ref(root, key, "axis", r=d2 / 2)
    lo = service._tb_ref(root, key, "plane", z=0.0, nz=-1.0)
    hi = service._tb_ref(root, key, "plane", z=s, nz=1.0)
    if bore is None or lo is None or hi is None:
        return None
    return {"d1": float(part["params"]["D"]), "d2": d2, "s": s, "bore": bore["id"], "lo": lo["id"], "hi": hi["id"]}


# ----------------------------------------------------------------------------- placement
def _mate(root: Path, doc: dict[str, Any], t: str, a: tuple[str, int], b: tuple[str, int], value: float = 0.0,
          flip: bool = False) -> dict[str, Any]:
    return service.make_mate(root, doc, {"type": t, "a": {"inst": a[0], "kind": "face", "id": a[1]},
                                         "b": {"inst": b[0], "kind": "face", "id": b[1]}, "value": value, "flip": flip})


def key_pose(Ts: np.ndarray, sg_p: Any, sg_v: Any, ks: dict[str, Any], kg: dict[str, Any]) -> np.ndarray:
    """World pose of a key on a keyseat of a shaft placed at Ts: length along the axis, bottom on the floor,
    centred on the keyseat (key local X = shaft axis, Z = keyseat direction)."""
    R = Ts[:3, :3]
    V = xform.unit(R @ np.asarray(sg_v, dtype=float))
    K = xform.unit(R @ np.asarray(ks["k"], dtype=float))
    P = xform.pt(Ts, np.asarray(sg_p, dtype=float) + np.asarray(sg_v, dtype=float) * ks["t_c"])
    Rk = np.column_stack([V, np.cross(K, V), K])
    del kg
    return xform.make(Rk, P + K * ks["f"])


def place_key(root: Path, doc: dict[str, Any], sid: str, sg: dict[str, Any], ks: dict[str, Any], key: str,
              T: np.ndarray | None = None) -> tuple[str | None, str, str | None]:
    """Insert one Toolbox key into a keyseat of shaft ``sid`` (or mate an existing instance placed at T). Returns
    (instance, sentence, outcome code or None)."""
    kg = key_geom(root, key)
    names = service.display_names
    if kg is None:
        return None, "the key's faces were not recognised", "no_keyseat"
    if abs(kg["b"] - ks["b"]) > 0.05:
        return None, (f"the key is {kg['b']:g} mm wide and the keyseat {ks['b']:g} mm"), "key_mismatch"
    if kg["L"] > ks["length"] + 1e-3:
        return None, (f"the key ({kg['L']:g} mm) is longer than the {ks['length']:.4g} mm keyseat"), "key_mismatch"
    Ts = xform.from12(service._inst(doc, sid)["T"])
    Tk = key_pose(Ts, sg["p"], sg["v"], ks, kg)
    inst = service.add_instance(root, doc, key, T=xform.to12(Tk))
    iid = str(inst["id"])
    _mate(root, doc, "coincident", (sid, ks["floor"]), (iid, kg["bottom"]))
    # the key's +Y face looks along -(axis x k): it bears on the keyseat wall on that side (``walls["neg"]``)
    if ks.get("walls", {}).get("neg") is not None and kg.get("side") is not None:
        _mate(root, doc, "coincident", (sid, ks["walls"]["neg"]), (iid, kg["side"]))
    slides = True
    if ks.get("rounded") and abs(kg["L"] - ks["length"]) < 1e-3 and ks["ends"] and kg["ends"].get("hi") is not None:
        hi_end = max(ks["ends"], key=lambda x: x["t"])
        _mate(root, doc, "concentric", (sid, hi_end["face"]), (iid, kg["ends"]["hi"]))
        slides = False
    text = (f"Fitz put {names(doc)[iid]} in the {ks['b']:g}×{ks['t1']:g} keyseat of {names(doc)[sid]}: on the floor, "
            "centred on the keyseat" + (", free to slide along it (its ends are square)" if slides else ""))
    return iid, text, None


def ring_pose(Ts: np.ndarray, sg_p: Any, sg_v: Any, gr: dict[str, Any], rg: dict[str, Any], away: str
              ) -> np.ndarray:
    """World pose of a ring in groove ``gr``, its Z = 0 face on the wall at the ``away`` end ("lo" / "hi"), its +Z
    pointing back into the groove."""
    R = Ts[:3, :3]
    v = np.asarray(sg_v, dtype=float)
    V = xform.unit(R @ v)
    z = V if away == "lo" else -V
    t = gr["lo"] if away == "lo" else gr["hi"]
    P = xform.pt(Ts, np.asarray(sg_p, dtype=float) + v * t)
    del rg
    return xform.make(xform.frame_z(z), P)


def place_ring(root: Path, doc: dict[str, Any], sid: str, sg: dict[str, Any], gr: dict[str, Any], key: str,
               away: str) -> tuple[str | None, str, str | None]:
    """Insert one Toolbox retaining ring into groove ``gr`` of shaft ``sid``, against the wall at ``away``."""
    rg = ring_geom(root, key)
    names = service.display_names
    if rg is None:
        return None, "the ring's faces were not recognised", "no_groove"
    if abs(rg["d2"] - gr["d2"]) > 0.06:
        return None, f"the ring's groove Ø{rg['d2']:g} doesn't match the Ø{gr['d2']:g} groove", "ring_mismatch"
    Ts = xform.from12(service._inst(doc, sid)["T"])
    inst = service.add_instance(root, doc, key, T=xform.to12(ring_pose(Ts, sg["p"], sg["v"], gr, rg, away)))
    iid = str(inst["id"])
    _mate(root, doc, "concentric", (sid, gr["cyl"]), (iid, rg["bore"]))
    _mate(root, doc, "coincident", (sid, gr["faces"][away]), (iid, rg["lo"]))
    return iid, (f"Fitz snapped {names(doc)[iid]} into the Ø{gr['d2']:g} groove of {names(doc)[sid]}, against the "
                 "groove wall away from the part it holds"), None
