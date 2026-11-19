"""Design parameters on the model: which faces each parameter drives, found by sensitivity (no AI, no tokens).

For every editable design parameter the model is rebuilt with that one value nudged (about 1 %, or one more
instance for a whole number) and its B-rep compared with the current one, face by face. A parameter is shown on the
model as a CAD dimension when the change is explained by exactly one measurable quantity that *equals the value*:

- ``linear``: the distance between two parallel planes (or a plane and a cylinder axis or tangent, or two parallel
  axes) equals the value and grew by the nudge;
- ``diameter`` / ``radius``: cylinders (spheres, fillet tori) whose diameter or radius equals the value and moved with
  it;
- ``count``: a whole number whose nudge adds instances of a pattern (cylinders of one size);
- ``angle``: a plane that turned by the nudge, at the value's angle to a fixed plane;
- ``none``: still editable in the panel; ``driven`` lists the faces it moves (highlighted on hover).

The mapping depends on the script's structure, not on the values (``structure_key``): after a value edit the
previous mapping is checked against the new geometry (``validate``) and reused when it still holds. Face ids are
positions in ``topo.json`` (same body and face order, ``topo.body_list``). Runs inside the warm build worker one
parameter per request (``base`` then ``step``), so an interactive build never waits for more than one nudge.

The script may override inference per parameter in ``PARAM_META``: ``"dim": {"kind": "none"}`` hides it, and
``"dim": {"kind": "linear", "a": [x, y, z], "b": [x, y, z]}`` / ``{"kind": "label", "at": [x, y, z]}`` place it
explicitly (points evaluated by the script, so they follow the values).
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from pathlib import Path
from typing import Any

FORMAT = "formwright-dims/1"
MAX_PARAMS = 24
NUDGE = 0.01  # relative perturbation of a real-valued parameter

Row = dict[str, Any]


# ----------------------------------------------------------------------------- face table
def _dot(a: Any, b: Any) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a: Any, b: Any) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Any, b: Any) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a: Any) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a: Any) -> tuple[float, float, float]:
    n = _norm(a) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def _canon(d: Any) -> tuple[float, float, float]:
    """Direction with an unsigned sense (first clear component positive): parallel lines compare equal."""
    for c in d:
        if abs(c) > 1e-9:
            return (d[0], d[1], d[2]) if c > 0 else (-d[0], -d[1], -d[2])
    return (d[0], d[1], d[2])


def _xyz(p: Any) -> tuple[float, float, float]:
    return (p.X(), p.Y(), p.Z())


def face_row(f: Any) -> Row:
    """The exact surface of a face, cheaply (no mass properties): planes as outward normal + offset, cylinders as
    axis + radius, and so on."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import (
        GeomAbs_Cone,
        GeomAbs_Cylinder,
        GeomAbs_Plane,
        GeomAbs_Sphere,
        GeomAbs_Torus,
    )
    from OCP.TopAbs import TopAbs_REVERSED

    s = BRepAdaptor_Surface(f.wrapped)
    t = s.GetType()
    if t == GeomAbs_Plane:
        pl = s.Plane()
        n = _xyz(pl.Axis().Direction())
        if f.wrapped.Orientation() == TopAbs_REVERSED:
            n = (-n[0], -n[1], -n[2])
        return {"t": "plane", "n": n, "d": _dot(n, _xyz(pl.Location()))}
    if t == GeomAbs_Cylinder:
        c = s.Cylinder()
        return {"t": "cylinder", "a": _canon(_xyz(c.Axis().Direction())), "p": _xyz(c.Axis().Location()),
                "r": c.Radius()}
    if t == GeomAbs_Cone:
        c = s.Cone()
        return {"t": "cone", "a": _canon(_xyz(c.Axis().Direction())), "p": _xyz(c.Apex()),
                "ang": math.degrees(c.SemiAngle())}
    if t == GeomAbs_Sphere:
        sp = s.Sphere()
        return {"t": "sphere", "p": _xyz(sp.Location()), "r": sp.Radius()}
    if t == GeomAbs_Torus:
        tr = s.Torus()
        return {"t": "torus", "a": _canon(_xyz(tr.Axis().Direction())), "p": _xyz(tr.Axis().Location()),
                "r": tr.MinorRadius(), "R": tr.MajorRadius()}
    return {"t": "freeform"}


def faces_of(shape: Any) -> list[Any]:
    from aicad.topo import body_list

    return [f for _, b in body_list(shape) for f in b.faces()]


def topo_sig(rows: list[Row]) -> str:
    return hashlib.sha256("".join(r["t"][0] for r in rows).encode()).hexdigest()[:16]


# ----------------------------------------------------------------------------- script text
_ASSIGN = r"^(?P<name>{name})(?P<sp>\s*=\s*)(?P<val>-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)(?P<rest>\s*(?:#.*)?)$"


def set_literal(src: str, name: str, value: float, is_int: bool) -> str:
    lit = str(round(value)) if is_int else repr(float(value))
    new, n = re.subn(_ASSIGN.format(name=re.escape(name)), lambda m: f"{m['name']}{m['sp']}{lit}{m['rest']}", src,
                     count=1, flags=re.MULTILINE)
    if not n:
        raise ValueError(f"{name} is not a plain literal")
    return new


def structure_key(src: str, names: Any, helpers: str = "") -> str:
    """The script with every editable parameter's value blanked: unchanged by parameter edits."""
    for n in sorted(names):
        src = re.sub(_ASSIGN.format(name=re.escape(n)), lambda m: f"{m['name']} = ?", src, count=1, flags=re.MULTILINE)
    return hashlib.sha256((src + "\0" + helpers).encode()).hexdigest()[:24]


def delta_for(value: float, meta: dict[str, Any], is_int: bool) -> list[float]:
    """Nudges to try, in order (the second is the other direction, for a value at its limit or a failed build)."""
    lo, hi = meta.get("min"), meta.get("max")
    if is_int:
        steps = [1.0, -1.0]
    else:
        d = abs(value) * NUDGE if value else float(meta.get("step") or 0.5) * 0.5
        d = max(d, 1e-3)
        steps = [d, -d]
    return [d for d in steps if (lo is None or value + d >= lo) and (hi is None or value + d <= hi)]


# ----------------------------------------------------------------------------- classification
def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def _vtol(v: float) -> float:
    return 1e-4 * max(1.0, abs(v)) + 1e-6


def _dtol(d: float) -> float:
    return 2e-3 * abs(d) + 1e-7


def _plane_x(r: Row, u: Any) -> float:
    """Position of a plane along unit direction u (u parallel to its normal)."""
    return r["d"] * _dot(r["n"], u)


def _perp(v: Any, a: Any) -> tuple[float, float, float]:
    k = _dot(v, a)
    return (v[0] - k * a[0], v[1] - k * a[1], v[2] - k * a[2])


def moved(b: Row, p: Row) -> bool:
    if b["t"] != p["t"]:
        return True
    if b["t"] == "plane":
        return abs(b["d"] - p["d"]) > 1e-7 or _dot(b["n"], p["n"]) < 1 - 1e-9
    if b["t"] in ("cylinder", "torus", "cone"):
        if abs(_dot(b["a"], p["a"])) < 1 - 1e-9 or _norm(_perp(_sub(p["p"], b["p"]), b["a"])) > 1e-7:
            return True
        if b["t"] == "torus" and abs(b["R"] - p["R"]) > 1e-7:
            return True
        if b["t"] == "cone":
            return abs(b["ang"] - p["ang"]) > 1e-7 or _norm(_sub(p["p"], b["p"])) > 1e-7
        return abs(b["r"] - p["r"]) > 1e-7
    if b["t"] == "sphere":
        return abs(b["r"] - p["r"]) > 1e-7 or _norm(_sub(p["p"], b["p"])) > 1e-7
    return False


def _gap(b: Row, p: Row) -> float:
    """How far a face moved/turned/resized (same surface type): the cost of pairing b with p."""
    if b["t"] == "plane":
        return abs(b["d"] - p["d"]) + 1e3 * (1 - _dot(b["n"], p["n"]))
    if b["t"] in ("cylinder", "torus", "cone"):
        g = _norm(_perp(_sub(p["p"], b["p"]), b["a"])) + 1e3 * (1 - abs(_dot(b["a"], p["a"])))
        return g + abs(b.get("r", 0) - p.get("r", 0)) + abs(b.get("R", 0) - p.get("R", 0)) + abs(b.get("ang", 0) - p.get("ang", 0))
    if b["t"] == "sphere":
        return _norm(_sub(p["p"], b["p"])) + abs(b["r"] - p["r"])
    return 0.0


def _bucket(r: Row) -> tuple[Any, ...]:
    d = r.get("n") or r.get("a")
    return (r["t"], *(round(c, 4) for c in d)) if d else (r["t"],)


def match(B: list[Row], P: list[Row]) -> list[Row] | None:
    """P reordered so P[i] is the nudged version of B[i]. OCCT may number faces differently after a nudge (seen on
    the pipe flange: a bolt hole and the raised face swapped places), so faces are paired by least movement within
    the same surface type and direction, identity first on ties. None when the face census differs."""
    if len(B) != len(P):
        return None
    out: list[Row | None] = [None] * len(B)
    for pass_key in (_bucket, lambda r: (r["t"],)):  # same direction first, then turned faces of the same type
        free_b: dict[Any, list[int]] = {}
        free_p: dict[Any, list[int]] = {}
        used = {id(x) for x in out if x is not None}
        for i, r in enumerate(B):
            if out[i] is None:
                free_b.setdefault(pass_key(r), []).append(i)
        for j, r in enumerate(P):
            if id(r) not in used:
                free_p.setdefault(pass_key(r), []).append(j)
        for k, bi in free_b.items():
            pj = free_p.get(k, [])
            if len(bi) == len(pj) and all(_gap(B[i], P[i]) == 0 for i in bi) and bi == pj:
                for i in bi:
                    out[i] = P[i]
                continue
            pairs = sorted((_gap(B[i], P[j]), abs(i - j), i, j) for i in bi for j in pj)
            taken: set[int] = set()
            for _, _, i, j in pairs:
                if out[i] is None and j not in taken:
                    out[i] = P[j]
                    taken.add(j)
    return None if any(x is None for x in out) else out  # type: ignore[return-value]


def _axis_groups(rows: list[Row], idx: list[int]) -> int:
    """Distinct axes among cylinder rows (a cylinder split into two faces counts once)."""
    seen: list[tuple[Any, Any]] = []
    for i in idx:
        r = rows[i]
        if not any(abs(_dot(r["a"], a)) > 1 - 1e-9 and _norm(_perp(_sub(r["p"], p), a)) < 1e-6 for a, p in seen):
            seen.append((r["a"], r["p"]))
    return len(seen)


def _linear_candidates(B: list[Row], P: list[Row], drv: set[int], v: float, d: float) -> list[tuple[Any, ...]]:
    """(rank, a_ref, b_ref, u, s) for every pair whose distance equals the value and grew by the nudge."""
    out: list[tuple[Any, ...]] = []
    planes = [i for i, r in enumerate(B) if r["t"] == "plane"]
    axes = [i for i, r in enumerate(B) if r["t"] == "cylinder"]
    vt, dt = _vtol(v), _dtol(d)

    def take(rank: int, a: dict[str, Any], b: dict[str, Any], u: Any, s0: float, s1: float) -> None:
        if s0 < 0:  # orient from a to b
            u, s0, s1 = (-u[0], -u[1], -u[2]), -s0, -s1
        if _close(s0, v, vt) and _close(s1 - s0, d, dt):
            out.append((rank, a, b, u, s0))

    for i in planes:
        u = _canon(B[i]["n"])
        for j in planes:
            if j <= i or (i not in drv and j not in drv) or abs(_dot(B[j]["n"], u)) < 1 - 1e-9:
                continue
            take(0, {"face": i, "ref": "plane"}, {"face": j, "ref": "plane"}, u,
                 _plane_x(B[j], u) - _plane_x(B[i], u), _plane_x(P[j], u) - _plane_x(P[i], u))
        for j in axes:
            if (i not in drv and j not in drv) or abs(_dot(B[j]["a"], u)) > 1e-9:
                continue
            x0, x1 = _plane_x(B[i], u), _plane_x(P[i], u)
            take(2, {"face": i, "ref": "plane"}, {"face": j, "ref": "axis"}, u, _dot(B[j]["p"], u) - x0,
                 _dot(P[j]["p"], u) - x1)
            for side in (1, -1):
                take(4, {"face": i, "ref": "plane"}, {"face": j, "ref": "tangent", "side": side}, u,
                     _dot(B[j]["p"], u) + side * B[j]["r"] - x0, _dot(P[j]["p"], u) + side * P[j]["r"] - x1)
    for ii, i in enumerate(axes):
        for j in axes[ii + 1:]:
            if (i not in drv and j not in drv) or abs(_dot(B[i]["a"], B[j]["a"])) < 1 - 1e-9:
                continue
            w0 = _perp(_sub(B[j]["p"], B[i]["p"]), B[i]["a"])
            if _norm(w0) < 1e-6:
                continue  # coaxial
            u = _unit(w0)
            w1 = _perp(_sub(P[j]["p"], P[i]["p"]), P[i]["a"])
            take(3, {"face": i, "ref": "axis"}, {"face": j, "ref": "axis"}, u, _norm(w0), _dot(w1, u))
            # overall length of a slot / over two bosses: outer tangent to outer tangent
            take(5, {"face": i, "ref": "tangent", "side": -1}, {"face": j, "ref": "tangent", "side": 1}, u,
                 _norm(w0) + B[i]["r"] + B[j]["r"], _dot(w1, u) + P[i]["r"] + P[j]["r"])
    return out


def classify(B: list[Row], P: list[Row], name: str, v: float, d: float, is_int: bool,
             area: Any = None) -> Row | None:
    """The dimension a parameter drives, from the face tables before (B) and after (P) the nudge d. None when the
    nudge changed the topology of a parameter that is not a count (the caller tries the other direction)."""
    rec: Row = {"param": name}
    M = match(B, P)
    if M is None:
        if not is_int:
            return None
        return _count(B, P, name, v, d) or {**rec, "kind": "none", "reason": "topology"}
    P = M
    drv = {i for i, (b, p) in enumerate(zip(B, P, strict=True)) if moved(b, p)}
    rec["driven"] = sorted(drv)[:400]
    if not drv:
        return static_round(B, name, v) or {**rec, "kind": "none", "reason": "no change"}
    area = area or (lambda i: 0.0)
    cands = _linear_candidates(B, P, drv, v, d) if v > 0 else []
    best = None
    if cands:
        best = min(cands, key=lambda c: (c[0], -(area(c[1]["face"]) + area(c[2]["face"])), c[1]["face"], c[2]["face"]))
    if best is not None and best[0] == 0:
        return _linear(rec, best, B)
    # diameter / radius: round faces whose size equals the value and moved with it
    for kind, k in (("diameter", 2.0), ("radius", 1.0)):
        hit = [i for i in sorted(drv) if B[i]["t"] in ("cylinder", "sphere", "torus")
               and _close(k * B[i]["r"], v, _vtol(v)) and _close(k * (P[i]["r"] - B[i]["r"]), d, _dtol(d))]
        if hit:
            cyl = [i for i in hit if B[i]["t"] == "cylinder"]
            n = _axis_groups(B, cyl) + len(hit) - len(cyl)
            return {**rec, "kind": kind, "faces": hit, "count": n}
    if best is not None:
        return _linear(rec, best, B)
    ang = _angle(B, P, drv, v, d)
    if ang:
        return {**rec, **ang}
    return {**rec, "kind": "none", "reason": "no single dimension"}


def static_round(B: list[Row], name: str, v: float) -> Row | None:
    """A size picked from a standard list (M8, a bearing series) can't be nudged: the build refuses the in-between
    value or snaps back. Then the round faces equal to it are its dimension, by value alone (shown only while equal)."""
    hit = [i for i, r in enumerate(B) if r["t"] == "cylinder" and _close(2 * r["r"], v, _vtol(v))]
    return {"param": name, "kind": "diameter", "faces": hit, "count": _axis_groups(B, hit), "static": True}         if hit and v > 0 else None


def _linear(rec: Row, c: tuple[Any, ...], B: list[Row]) -> Row:
    _, a, b, u, s = c
    out = {**rec, "kind": "linear", "a": a, "b": b, "u": [round(x, 9) for x in u], "s": s}
    if a["ref"] == b["ref"] == "axis":  # two holes opposite each other about a round body's axis: a pitch circle
        ra, rb = B[a["face"]], B[b["face"]]
        mid = tuple((x + y) / 2 for x, y in zip(ra["p"], rb["p"], strict=True))
        if any(r["t"] == "cylinder" and abs(_dot(r["a"], ra["a"])) > 1 - 1e-9
               and _norm(_perp(_sub(mid, r["p"]), r["a"])) < 1e-6 for r in B):
            out["circle"] = True
    return out


def _angle(B: list[Row], P: list[Row], drv: set[int], v: float, d: float) -> Row | None:
    turned = [i for i in sorted(drv) if B[i]["t"] == "plane"
              and _close(math.degrees(math.acos(max(-1.0, min(1.0, _dot(B[i]["n"], P[i]["n"]))))), abs(d), 1e-3 + 2e-3 * abs(d))]
    for i in turned:
        for j, r in enumerate(B):
            if r["t"] != "plane" or j in drv:
                continue
            phi = math.degrees(math.acos(max(-1.0, min(1.0, _dot(B[i]["n"], r["n"])))))
            if _close(phi, v, 1e-3) or _close(180 - phi, v, 1e-3):
                return {"kind": "angle", "faces": [j, i]}
    return {"kind": "angle", "faces": [turned[0]]} if turned else None


def _count(B: list[Row], P: list[Row], name: str, v: float, d: float) -> Row | None:
    """A whole-number parameter whose nudge adds instances: cylinders of one size whose number of distinct axes is
    value x m before and (value + nudge) x m after."""
    def groups(rows: list[Row]) -> dict[float, list[int]]:
        g: dict[float, list[int]] = {}
        for i, r in enumerate(rows):
            if r["t"] == "cylinder":
                g.setdefault(round(r["r"], 6), []).append(i)
        return g

    gb, gp = groups(B), groups(P)
    for r, idx in sorted(gb.items()):
        n0, n1 = _axis_groups(B, idx), _axis_groups(P, gp.get(r, []))
        if v <= 0 or n0 % int(v):
            continue
        m = n0 // int(v)
        if m >= 1 and n1 == int(v + d) * m:
            return {"param": name, "kind": "count", "faces": idx, "count": n0, "per": m}
    return None


def validate(dims: list[Row], rows: list[Row], values: dict[str, Any]) -> bool:
    """Does a mapping made for the same script structure still hold on the current geometry and values?"""
    n = len(rows)
    for dm in dims:
        k, v = dm.get("kind"), values.get(dm.get("param", ""))
        if k in ("none", "label", None) or dm.get("explicit"):
            continue
        if v is None:
            return False
        faces = [dm["a"]["face"], dm["b"]["face"]] if k == "linear" else dm.get("faces") or []
        if any(not isinstance(i, int) or i >= n for i in faces):
            return False
        if k == "linear":
            s = measure_linear(rows, dm["a"], dm["b"], dm["u"])
            if s is None or not _close(s, float(v), _vtol(float(v))):
                return False
        elif k in ("diameter", "radius"):
            kk = 2.0 if k == "diameter" else 1.0
            if any(rows[i].get("r") is None or not _close(kk * rows[i]["r"], float(v), _vtol(float(v))) for i in faces):
                return False
        elif k == "count" and _axis_groups(rows, [i for i in faces if rows[i]["t"] == "cylinder"])                 != int(v) * int(dm.get("per", 1)):
            return False
    return True


def _ref_x(r: Row, ref: dict[str, Any], u: Any) -> float | None:
    if ref["ref"] == "plane":
        return _plane_x(r, u) if r["t"] == "plane" else None
    if r["t"] != "cylinder":
        return None
    x = _dot(r["p"], u)
    return x + ref.get("side", 1) * r["r"] if ref["ref"] == "tangent" else x


def measure_linear(rows: list[Row], a: dict[str, Any], b: dict[str, Any], u: Any) -> float | None:
    ra, rb = rows[a["face"]], rows[b["face"]]
    if a["ref"] == "axis" and b["ref"] == "axis":
        if ra["t"] != "cylinder" or rb["t"] != "cylinder":
            return None
        return _norm(_perp(_sub(rb["p"], ra["p"]), ra["a"]))
    xa, xb = _ref_x(ra, a, u), _ref_x(rb, b, u)
    return None if xa is None or xb is None else xb - xa


# ----------------------------------------------------------------------------- worker side
_STATE: dict[str, dict[str, Any]] = {}


def _explicit(name: str, spec: Any) -> Row | None:
    if not isinstance(spec, dict):
        return None
    kind = spec.get("kind")

    def pt(x: Any) -> list[float] | None:
        try:
            p = [float(c) for c in x]
            return p if len(p) == 3 and all(math.isfinite(c) for c in p) else None
        except (TypeError, ValueError):
            return None

    if kind == "none":
        return {"param": name, "kind": "hidden", "explicit": True}
    if kind == "linear" and pt(spec.get("a")) and pt(spec.get("b")):
        return {"param": name, "kind": "linear", "explicit": True, "pa": pt(spec["a"]), "pb": pt(spec["b"])}
    if pt(spec.get("at")):
        return {"param": name, "kind": "label", "explicit": True, "at": pt(spec["at"]),
                "as": kind if kind in ("diameter", "radius", "count", "angle") else "label"}
    return None


def base(script: Path, prev: dict[str, Any] | None = None) -> dict[str, Any]:
    """Current geometry's face table + the plan of nudges. ``valid`` when ``prev`` (an earlier dims document for the
    same structure) still holds: nothing else to compute."""
    from aicad.agent import runner

    t0 = time.perf_counter()
    source = script.read_text(encoding="utf-8")
    runner.tripwire(source)
    helpers = "".join(f.read_text(encoding="utf-8") for f in sorted(script.parent.glob("*.py"))
                      if f.resolve() != script.resolve())
    ns = runner._exec(script, use_cache=True)
    shape = ns["result"]
    declared = ns.get("PARAMS") if isinstance(ns.get("PARAMS"), dict) else {}
    params = {str(k): v for k, v in declared.items() if isinstance(v, (int, float, str, bool))}
    editable = runner.editable_params(source, params)
    raw_meta = ns.get("PARAM_META") if isinstance(ns.get("PARAM_META"), dict) else {}
    meta = runner.param_meta(raw_meta, params)
    faces = faces_of(shape)
    rows = [face_row(f) for f in faces]
    key, sig = structure_key(source, editable, helpers), topo_sig(rows)
    _STATE.clear()  # one part at a time per worker: the newest base wins
    _STATE[str(script)] = {"key": key, "sig": sig, "rows": rows, "faces": faces, "source": source,
                           "editable": editable, "meta": meta, "areas": {}}
    explicit = {k: e for k in editable if (e := _explicit(k, (raw_meta.get(k) or {}).get("dim")
                                                        if isinstance(raw_meta.get(k), dict) else None))}
    res: dict[str, Any] = {"key": key, "sig": sig, "faces": len(rows), "explicit": list(explicit.values()),
                           "base_s": round(time.perf_counter() - t0, 3)}
    if prev and prev.get("key") == key and prev.get("sig") == sig and validate(prev.get("dims") or [], rows, editable):
        return {**res, "valid": True}
    plan = []
    for k, v in editable.items():
        if k in explicit:
            continue
        is_int = isinstance(v, int) and not isinstance(v, bool)
        plan.append({"param": k, "value": v, "is_int": is_int, "deltas": delta_for(float(v), meta.get(k) or {}, is_int)})
    res["skipped"] = [p["param"] for p in plan[MAX_PARAMS:]]
    return {**res, "valid": False, "plan": plan[:MAX_PARAMS]}


def step(script: Path, key: str, param: str, value: float, is_int: bool, deltas: list[float]) -> Row:
    """One parameter: rebuild with each nudge until one classifies (no exports, no caching)."""
    from aicad.agent import runner

    t0 = time.perf_counter()
    st = _STATE.get(str(script))
    if st is None or st["key"] != key:  # the worker was recycled, or another part ran in between
        base(script)
        st = _STATE.get(str(script))
        if st is None or st["key"] != key:
            return {"param": param, "kind": "none", "reason": "stale"}
    rows: list[Row] = st["rows"]
    areas: dict[int, float] = st["areas"]

    def area(i: int) -> float:
        if i not in areas:
            areas[i] = float(st["faces"][i].area)
        return areas[i]

    rec: Row | None = None
    for d in deltas:
        try:
            src = set_literal(st["source"], param, value + d, is_int)
            ns = runner._exec(script, use_cache=False, source=src, store=False)
            prow = [face_row(f) for f in faces_of(ns["result"])]
        except Exception:  # noqa: BLE001, S112 - a nudge that doesn't build: try the other direction
            continue
        rec = classify(rows, prow, param, float(value), d, is_int, area)
        if rec is not None:
            break
    rec = rec or static_round(rows, param, float(value)) or {"param": param, "kind": "none", "reason": "rebuild"}
    rec["t_s"] = round(time.perf_counter() - t0, 3)
    return rec


def document(base_res: dict[str, Any], records: list[Row], build_id: Any, t0: float) -> dict[str, Any]:
    dims = [*base_res.get("explicit", []), *records]
    return {"format": FORMAT, "key": base_res["key"], "sig": base_res["sig"], "build_id": build_id, "dims": dims,
            "skipped": base_res.get("skipped", []),
            "timings": {"base_s": base_res.get("base_s"), "params": len(records),
                        "total_s": round(time.perf_counter() - t0, 3),
                        "per_param_s": {r["param"]: r.get("t_s") for r in records}}}


def map_script(script: Path, prev: dict[str, Any] | None = None, build_id: Any = None) -> dict[str, Any]:
    """The whole pass in this process (tests, CLI). The app runs the same steps one by one on the warm worker."""
    t0 = time.perf_counter()
    b = base(script, prev)
    if b.get("valid"):
        return {**(prev or {}), "build_id": build_id, "key": b["key"], "sig": b["sig"]}
    recs = [step(script, b["key"], p["param"], p["value"], p["is_int"], p["deltas"]) for p in b["plan"]]
    return document(b, recs, build_id, t0)
