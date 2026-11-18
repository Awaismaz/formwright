"""```fw-edit``` (DS-035): a small edit the design agent hands to the PropertyManager instead of writing code.

When a request maps to ONE existing manual feature or to declared parameters ("fillet the top edges 2 mm", "add a
3 mm chamfer", "make the holes 8 mm", "plate thickness 12"), the agent replies with a short sentence and one block::

    ```fw-edit
    {"summary": "Fillet the top edges R2", "op": "fillet", "r": 2, "edges": "top"}
    ```

The app opens the real PropertyManager pre-filled, highlights the targets, and the user presses OK: the change runs
through the normal manual-feature path (validated by ``studio.validate_feature``), never through agent-written code.

Accepted forms (everything is validated here; anything unusable is dropped with a plain note, never shown raw):

- ``op`` fillet / chamfer: ``r`` / ``d`` and ``edges``: a side keyword (``top``, ``bottom``, ``front``, ``back``,
  ``left``, ``right``: the outer edges of the outermost flat face on that side, hole rims excluded) or a list of points on the edges (for
  edges the user selected: the "passes through" points of the [Selected ...] lines).
- ``op`` shell: ``t`` and ``faces``: a side keyword or a list of points on the faces (``{"point": [..]}`` or [x, y, z]).
- ``op`` hole: a Hole Wizard preset (``type`` clearance / tapped / cbore / csk / simple, ``size`` (M), ``d``, ``mode``
  corners, ``dx``, ``dy``) and ``faces`` (one face).
- ``feature``: the id or name of an existing hand-made feature to edit instead (fillet r, chamfer d, shell t,
  hole d or size); targets are optional then (the feature keeps its picks).
- ``op`` params: ``params`` = {NAME: value} over the design's editable parameters (limits enforced).

Targets are resolved deterministically on the current build's exact topology (``out/topo.json``), so the UI can
highlight exactly what OK will change.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

_E_BLOCK = re.compile(r"```fw-edit\s*\n(.*?)\n?```", re.DOTALL)
SIDES: dict[str, tuple[int, int]] = {"top": (2, 1), "bottom": (2, -1), "right": (0, 1), "left": (0, -1),
                                     "back": (1, 1), "front": (1, -1)}
FEATURE_OPS = ("fillet", "chamfer", "shell", "hole")
SIZE_KEY = {"fillet": "r", "chamfer": "d", "shell": "t"}
HOLE_TYPES = ("clearance", "tapped", "cbore", "csk", "simple")
MAX_TARGETS = 200


class EditError(ValueError):
    """The block can't become a PropertyManager edit; the message is plain language."""


# ----------------------------------------------------------------------------- geometry helpers (topo.json)
def _pts(flat: list[float]) -> list[tuple[float, float, float]]:
    return [(flat[i], flat[i + 1], flat[i + 2]) for i in range(0, len(flat) - 2, 3)]


def edge_mid(e: dict[str, Any]) -> list[float]:
    """The true middle of an edge's polyline (same rule as the viewer's ``edgeMid``)."""
    p = _pts(e.get("pts") or [])
    if not p:
        return [0.0, 0.0, 0.0]
    if len(p) < 2:
        return list(p[0])
    seg = [math.dist(p[i], p[i - 1]) for i in range(1, len(p))]
    half = sum(seg) / 2
    for i in range(1, len(p)):
        seg_len = seg[i - 1]
        if half <= seg_len or i == len(p) - 1:
            k = min(1.0, half / seg_len) if seg_len > 0 else 0.0
            a, b = p[i - 1], p[i]
            return [round(a[j] + (b[j] - a[j]) * k, 6) for j in range(3)]
        half -= seg_len
    return list(p[-1])


def edge_ref(e: dict[str, Any]) -> dict[str, Any]:
    """Kind and direction of an edge (same rule as the viewer's ``edgeRef``)."""
    if e.get("type") == "line":
        p = _pts(e.get("pts") or [])
        if len(p) >= 2:
            d = [p[-1][j] - p[0][j] for j in range(3)]
            n = math.hypot(*d)
            if n > 0:
                return {"kind": "line", "dir": [round(c / n, 9) for c in d]}
        return {"kind": "line"}
    if e.get("type") == "circle" and e.get("axis"):
        return {"kind": "circle", "dir": list(e["axis"])}
    return {"kind": "other"}


def _seg_dist(q: tuple[float, ...], a: tuple[float, ...], b: tuple[float, ...]) -> float:
    ab = [b[j] - a[j] for j in range(3)]
    L2 = sum(c * c for c in ab)
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, sum((q[j] - a[j]) * ab[j] for j in range(3)) / L2))
    return math.dist(q, [a[j] + ab[j] * t for j in range(3)])


def _edge_dist(q: tuple[float, ...], e: dict[str, Any]) -> float:
    p = _pts(e.get("pts") or [])
    if len(p) < 2:
        return math.dist(q, p[0]) if p else math.inf
    return min(_seg_dist(q, p[i - 1], p[i]) for i in range(1, len(p)))


def _tri_dist(q: tuple[float, ...], f: dict[str, Any]) -> float:
    """Distance from a point to a face's triangulation (vertices and planar projection inside the triangles)."""
    pos = _pts(f.get("pos") or [])
    idx = f.get("idx") or []
    best = min((math.dist(q, v) for v in pos), default=math.inf)
    for i in range(0, len(idx) - 2, 3):
        a, b, c = pos[idx[i]], pos[idx[i + 1]], pos[idx[i + 2]]
        u = [b[j] - a[j] for j in range(3)]
        v = [c[j] - a[j] for j in range(3)]
        n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
        nn = math.hypot(*n)
        if nn == 0:
            continue
        n = [x / nn for x in n]
        h = sum((q[j] - a[j]) * n[j] for j in range(3))
        p = [q[j] - h * n[j] for j in range(3)]
        # barycentric inside test
        w = [p[j] - a[j] for j in range(3)]
        d00, d01, d11 = sum(x * x for x in u), sum(u[j] * v[j] for j in range(3)), sum(x * x for x in v)
        d20, d21 = sum(w[j] * u[j] for j in range(3)), sum(w[j] * v[j] for j in range(3))
        den = d00 * d11 - d01 * d01
        if den == 0:
            continue
        s = (d11 * d20 - d01 * d21) / den
        t = (d00 * d21 - d01 * d20) / den
        if s >= -1e-9 and t >= -1e-9 and s + t <= 1 + 1e-9:
            best = min(best, abs(h))
    return best


def _tol(topo: dict[str, Any]) -> float:
    b = topo.get("bbox") or [0, 0, 0, 100, 100, 100]
    return max(0.05, 2e-3 * math.dist(b[:3], b[3:]))


def side_face(topo: dict[str, Any], side: str) -> list[int]:
    """The outermost flat face(s) facing ``side``: planar faces whose normal is the side's axis direction, at the
    extreme position along it (several coplanar faces count together)."""
    ax, sgn = SIDES[side]
    cands = [f for f in topo.get("faces", []) if f.get("type") == "plane" and f.get("normal")
             and f["normal"][ax] * sgn > 1 - 1e-6]
    if not cands:
        return []
    far = max(f["center"][ax] * sgn for f in cands)
    return [f["id"] for f in cands if abs(f["center"][ax] * sgn - far) <= 1e-6]


def outer_loop(topo: dict[str, Any], fid: int) -> list[int]:
    """The edges of a planar face's outer boundary: its edges grouped into loops by shared vertices, keeping the loop
    that spans the face (hole rims and pocket openings are inner loops)."""
    edges = list(dict.fromkeys(topo["faces"][fid].get("edges", [])))
    parent = {e: e for e in edges}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_vert: dict[int, int] = {}
    for e in edges:
        for v in topo["edges"][e].get("verts") or []:
            if v in by_vert:
                parent[find(e)] = find(by_vert[v])
            else:
                by_vert[v] = e
    loops: dict[int, list[int]] = {}
    for e in edges:
        loops.setdefault(find(e), []).append(e)
    if len(loops) <= 1:
        return edges

    def span(loop: list[int]) -> float:
        pts = [p for e in loop for p in _pts(topo["edges"][e].get("pts") or [])]
        return math.dist([min(p[j] for p in pts) for j in range(3)], [max(p[j] for p in pts) for j in range(3)]) if pts else 0.0

    return max(loops.values(), key=span)


def side_edges(topo: dict[str, Any], side: str) -> list[int]:
    """The outer edges of the outermost flat face(s) on a side ("the top edges"): hole rims are not included."""
    out: list[int] = []
    for fid in side_face(topo, side):
        for e in outer_loop(topo, fid):
            if e not in out:
                out.append(e)
    return out


def _as_point(v: Any) -> tuple[float, float, float] | None:
    if isinstance(v, dict):
        v = v.get("point")
    if isinstance(v, (list, tuple)) and len(v) == 3 and all(isinstance(c, (int, float)) and math.isfinite(c) for c in v):
        return (float(v[0]), float(v[1]), float(v[2]))
    return None


def resolve_edges(topo: dict[str, Any], spec: Any) -> list[int]:
    if isinstance(spec, str):
        side = spec.strip().lower()
        if side not in SIDES:
            raise EditError(f"I can't tell which edges “{spec[:40]}” means: pick them in the viewer.")
        ids = side_edges(topo, side)
        if not ids:
            raise EditError(f"There is no flat {side} face whose edges could be used: pick the edges in the viewer.")
        return ids
    if not isinstance(spec, list) or not spec:
        raise EditError("Which edges? Pick them in the viewer.")
    tol, edges, out = _tol(topo), topo.get("edges", []), []
    for raw in spec[:MAX_TARGETS]:
        q = _as_point(raw)
        if q is None or not edges:
            raise EditError("An edge position wasn't readable: pick the edges in the viewer.")
        e = min(edges, key=lambda e: _edge_dist(q, e))
        if _edge_dist(q, e) > tol:
            raise EditError("An edge wasn't found where expected (the model changed): pick it in the viewer.")
        if e["id"] not in out:
            out.append(e["id"])
    return out


def resolve_faces(topo: dict[str, Any], spec: Any, limit: int = 50) -> list[int]:
    if isinstance(spec, str):
        side = spec.strip().lower()
        if side not in SIDES:
            raise EditError(f"I can't tell which face “{spec[:40]}” means: pick it in the viewer.")
        ids = side_face(topo, side)
        if not ids:
            raise EditError(f"There is no flat {side} face: pick the face in the viewer.")
        return ids[:limit]
    if isinstance(spec, dict):
        spec = [spec]
    if not isinstance(spec, list) or not spec:
        raise EditError("Which face? Pick it in the viewer.")
    tol, faces, out = _tol(topo), topo.get("faces", []), []
    for raw in spec[:limit]:
        q = _as_point(raw)
        if q is None or not faces:
            raise EditError("A face position wasn't readable: pick the face in the viewer.")
        f = min(faces, key=lambda f: _tri_dist(q, f))
        if _tri_dist(q, f) > tol:
            raise EditError("A face wasn't found where expected (the model changed): pick it in the viewer.")
        if f["id"] not in out:
            out.append(f["id"])
    return out


def _num(v: Any, what: str, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise EditError(f"{what}: a number is needed.") from None
    if not math.isfinite(x) or not lo <= x <= hi:
        raise EditError(f"{what} must be between {lo:g} and {hi:g}.")
    return x


def _find_feature(manual: list[dict[str, Any]], ref: Any) -> dict[str, Any]:
    key = str(ref).strip()
    hit = next((f for f in manual if f.get("id") == key), None) or \
        next((f for f in manual if str(f.get("name", "")).strip().lower() == key.lower()), None)
    if hit is None:
        raise EditError(f"There is no hand-made feature called “{key[:60]}”.")
    return hit


# ----------------------------------------------------------------------------- the block
def parse_edit(raw: Any, ws: Path, clean: Callable[[str], str] = lambda s: s,
               validate: Callable[[dict[str, Any]], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Turn a raw fw-edit object into a PropertyManager edit for the UI. Raises EditError with a plain reason."""
    if not isinstance(raw, dict):
        raise EditError("The proposed edit wasn't readable.")
    status = _read(ws / "out" / "status.json") or {}
    topo = _read(ws / "out" / "topo.json")
    op = str(raw.get("op") or ("params" if raw.get("params") else "")).strip().lower()
    summary = raw.get("summary")
    summary = clean(str(summary).strip())[:160] if isinstance(summary, (str, int, float)) and str(summary).strip() else None
    out: dict[str, Any] = {"op": op, "summary": summary, "build_id": status.get("build_id"), "targets": None,
                           "feature": None, "feature_id": None, "params": None, "values": {}}
    if op == "params":
        p = raw.get("params")
        if not isinstance(p, dict) or not p:
            raise EditError("Which parameter should change?")
        editable = status.get("editable_params") or {}
        meta = status.get("param_meta") or {}
        rows: dict[str, Any] = {}
        for name, val in list(p.items())[:12]:
            name = str(name)
            if name not in editable:
                raise EditError(f"{name} isn't an editable design parameter.")
            m = meta.get(name) or {}
            label = m.get("label") or name
            x = _num(val, label, float(m.get("min", -1e6)), float(m.get("max", 1e6)))
            if isinstance(editable[name], int) and not isinstance(editable[name], bool) and not x.is_integer():
                raise EditError(f"{label} must be a whole number.")
            rows[name] = {"from": editable[name], "to": x, "label": label, "unit": m.get("unit") or ""}
        out["params"] = rows
        out["summary"] = summary or "Change " + ", ".join(f"{r['label']} to {r['to']:g}{(' ' + r['unit']) if r['unit'] else ''}"
                                                          for r in rows.values())
        return out
    if op not in FEATURE_OPS:
        raise EditError("Only fillets, chamfers, shells, holes and parameter changes open in the PropertyManager.")
    manual = _manual(ws)
    base: dict[str, Any] = {}
    if raw.get("feature") not in (None, ""):
        base = dict(_find_feature(manual, raw["feature"]))
        if base.get("op") != op:
            raise EditError(f"“{base.get('name')}” is a {base.get('op')}, not a {op}.")
        out["feature_id"] = base["id"]
    feat: dict[str, Any] = {**base, "op": op}
    feat.setdefault("name", {"fillet": "Fillet", "chamfer": "Chamfer", "shell": "Shell", "hole": "Hole"}[op])
    if op in SIZE_KEY:
        k = SIZE_KEY[op]
        v = raw.get(k, raw.get("size", raw.get("value")))
        if v is None and base:
            v = base.get(k)
        what = {"r": "Radius", "d": "Distance", "t": "Wall thickness"}[k]
        feat[k] = _num(v, what, 0.001, 1e4)
        out["values"] = {"size": feat[k]}
    target_spec = raw.get("edges") if op in ("fillet", "chamfer") else raw.get("faces", raw.get("face"))
    if target_spec is not None or not base:
        if topo is None:
            raise EditError("The model has no build yet to pick from.")
        if op in ("fillet", "chamfer"):
            ids = resolve_edges(topo, target_spec)
            edges = [topo["edges"][i] for i in ids]
            feat["edges"] = [edge_mid(e) for e in edges]
            feat["edge_refs"] = [edge_ref(e) for e in edges]
            out["targets"] = {"kind": "edge", "picks": [{"id": i, "point": edge_mid(topo["edges"][i])} for i in ids]}
        else:
            ids = resolve_faces(topo, target_spec, 1 if op == "hole" else 50)
            fs = [topo["faces"][i] for i in ids]
            if any(f.get("type") != "plane" or not f.get("normal") for f in fs):
                raise EditError("Pick flat faces for this feature.")
            out["targets"] = {"kind": "face", "picks": [{"id": f["id"], "point": [round(c, 6) for c in f["center"]]}
                                                        for f in fs]}
            if op == "shell":
                feat["faces"] = [{"point": [round(c, 6) for c in f["center"]], "normal": list(f["normal"])} for f in fs]
            else:
                f0 = fs[0]
                feat["point"], feat["normal"] = [round(c, 6) for c in f0["center"]], list(f0["normal"])
    if op == "hole":
        preset: dict[str, Any] = {}
        t = str(raw.get("type") or (base.get("spec") or {}).get("type") or ("simple" if raw.get("d") else "clearance"))
        if t not in HOLE_TYPES:
            raise EditError("Hole type must be clearance, tapped, counterbore, countersink or simple.")
        preset["type"] = t
        if t == "simple":
            preset["d"] = _num(raw.get("d", base.get("d")), "Hole diameter", 0.01, 1e4)
            feat["d"] = preset["d"]
            feat.pop("spec", None)
        else:
            preset["size"] = _num(raw.get("size", (base.get("spec") or {}).get("size", 6)), "Metric size", 1, 64)
            feat["spec"] = {**(base.get("spec") or {}), "type": t, "size": preset["size"]}
            feat.setdefault("d", 1.0)  # resolved from the standard table by validate_feature
        if not base:
            preset["mode"] = "corners"
            preset["dx"] = _num(raw.get("dx", 10), "Edge distance X", 0.01, 1e5)
            preset["dy"] = _num(raw.get("dy", raw.get("dx", 10)), "Edge distance Y", 0.01, 1e5)
            feat["place"] = {"mode": "corners", "face": {"point": feat.get("point")}, "dx": preset["dx"], "dy": preset["dy"]}
        out["values"] = {"hole": preset}
    if validate is not None:
        try:
            feat = validate(feat)
        except EditError:
            raise
        except Exception as e:  # noqa: BLE001 - the validator's 422 detail is already plain language
            raise EditError(str(getattr(e, "detail", e))[:300]) from None
    out["feature"] = feat
    if not out["summary"]:
        n = len((out["targets"] or {}).get("picks") or [])
        what = {"fillet": f"Fillet R{feat.get('r', 0):g}", "chamfer": f"Chamfer {feat.get('d', 0):g} mm",
                "shell": f"Shell {feat.get('t', 0):g} mm", "hole": "Hole"}[op]
        out["summary"] = f"{'Edit' if base else 'Add'} {what}" + (f" on {n} {'edges' if op in ('fillet', 'chamfer') else 'face(s)'}" if n else "")
    return out


def _read(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _manual(ws: Path) -> list[dict[str, Any]]:
    from aicad.agent.runner import _manual_block

    try:
        return _manual_block((ws / "model.py").read_text(encoding="utf-8"))[1]
    except (OSError, ValueError, SyntaxError):
        return []


def _default_validate(f: dict[str, Any]) -> dict[str, Any]:
    from aicad.platform.routers.studio import validate_feature

    return validate_feature(f)


def extract_edit(text: str, ws: Path, clean: Callable[[str], str] = lambda s: s,
                 validate: Callable[[dict[str, Any]], dict[str, Any]] | None = _default_validate
                 ) -> tuple[str, dict[str, Any] | None, str | None]:
    """Pull a ```fw-edit block out of a reply. Returns (text without the block, the edit or None, a plain note when
    the block couldn't be used)."""
    found: dict[str, Any] | None = None
    note: str | None = None
    for m in _E_BLOCK.finditer(text):
        try:
            found = parse_edit(json.loads(m.group(1)), ws, clean, validate)
            note = None
        except ValueError as e:  # EditError, or malformed JSON (json.JSONDecodeError is a ValueError)
            note = str(e) if isinstance(e, EditError) else "The proposed edit wasn't readable."
    return _E_BLOCK.sub("", text).strip(), found, note


def design_state(ws: Path, limit: int = 1200) -> str | None:
    """A compact line about the current design, appended to short change requests so the agent can answer a small
    edit with a fw-edit block in one turn (no file reading)."""
    st = _read(ws / "out" / "status.json") or {}
    if not st.get("fingerprint"):
        return None
    meta = st.get("param_meta") or {}
    params = ", ".join(f"{k}={v:g}" + (f" ({meta[k]['label']})" if (meta.get(k) or {}).get("label") else "")
                       for k, v in (st.get("editable_params") or {}).items() if isinstance(v, (int, float)))
    feats = []
    for f in _manual(ws)[:20]:
        size = next((f"{k}={f[k]:g}" for k in ("r", "d", "t") if isinstance(f.get(k), (int, float))), "")
        feats.append(f"{f.get('id')} “{f.get('name')}” {f.get('op')} {size}".strip())
    bb = st.get("bbox_minmax")
    parts = []
    if bb:
        parts.append("size " + " × ".join(f"{bb[i + 3] - bb[i]:g}" for i in range(3)) + " mm")
    if params:
        parts.append("parameters " + params)
    if feats:
        parts.append("hand-made features " + "; ".join(feats))
    if not parts:
        return None
    return ("[Design state for quick edits: " + "; ".join(parts))[:limit] + "]"
