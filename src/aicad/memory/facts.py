"""Key facts of one part, read from its latest verified build (no AI, no tokens).

``part_facts(ws)`` returns a small dict (name, material, size, revision, key parameters, interfaces) and ``fact_line``
renders it as one bounded line for the agent's project brief. Interfaces (hole patterns, bores, shaft diameters) come
from geometric recognition when it is current for the build (``out/recognition.json``), otherwise from a census of
the cylindrical faces in ``out/topo.json`` (same numbers, no hole/boss distinction), plus Hole Wizard holes written
in the model (their standard size and fit).
"""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path
from typing import Any

AXES = "XYZ"
MAX_PARAMS = 6
MAX_INTERFACES = 5


def _read(f: Path) -> dict[str, Any] | None:
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _g(x: float) -> str:
    return f"{x:.6g}" if abs(x - round(x)) > 1e-6 else str(round(x))


def _axis_letter(axis: Any) -> str:
    try:
        i = max(range(3), key=lambda k: abs(float(axis[k])))
        return AXES[i] if abs(float(axis[i])) > 0.999 else "oblique"
    except (TypeError, ValueError, IndexError):
        return "?"


def current_revision(ws: Path) -> int | None:
    from aicad.platform.routers.projects import current_revision as cur

    try:
        return cur(ws)
    except Exception:  # noqa: BLE001 - facts are best effort
        return None


def recognition_current(ws: Path, st: dict[str, Any]) -> dict[str, Any] | None:
    rec = _read(ws / "out" / "recognition.json")
    if rec and st.get("build_id") is not None and rec.get("build_id") == st.get("build_id"):
        return rec
    return None


# ------------------------------------------------------------------ interfaces
def _centroid(pts: list[list[float]]) -> list[float]:
    return [sum(p[k] for p in pts) / len(pts) for k in range(3)]


def _in_plane(c: list[float], ax: str) -> str:
    """A point written in the two coordinates perpendicular to the axis (the third is depth)."""
    if ax not in AXES:
        return ""
    keep = [k for k in range(3) if AXES[k] != ax]
    return "(" + ", ".join(f"{AXES[k]}{_g(round(c[k], 2))}" for k in keep) + ")"


def interfaces_from_recognition(rec: dict[str, Any]) -> list[str]:
    out: list[str] = []
    stock = rec.get("stock") or {}
    if stock.get("kind") == "turned":
        out.append(f"turned Ø{_g(stock['d'])} × {_g(stock['length'])} along {stock.get('axis', '?')}")
    holes = rec.get("holes") or []
    in_pat: set[int] = set()
    for p in rec.get("patterns") or []:
        idx = [i for i in p.get("holes") or [] if 0 <= i < len(holes)]
        in_pat |= set(idx)
        ax = _axis_letter(p.get("axis"))
        c = _centroid([holes[i]["center"] for i in idx]) if idx else None
        thr = "thru" if idx and all(holes[i].get("through") for i in idx) else (
            f"{_g(holes[idx[0]]['depth'])} deep" if idx and holes[idx[0]].get("depth") else "")
        at = f" centred {_in_plane(c, ax)}" if c else ""
        if p["kind"] == "circular":
            out.append(f"{p['count']}× Ø{_g(p['d'])} {thr} on Ø{_g(p['pcd'])} PCD, axis {ax}{at}".replace("  ", " "))
        elif p["kind"] == "grid":
            out.append(f"{p['count']}× Ø{_g(p['d'])} {thr} on {_g(p['pitch'][0])} × {_g(p['pitch'][1])} grid, "
                       f"axis {ax}{at}".replace("  ", " "))
        elif p["kind"] == "linear":
            out.append(f"{p['count']}× Ø{_g(p['d'])} {thr} in line, pitch {_g(p['pitch'])}, axis {ax}{at}"
                       .replace("  ", " "))
        else:
            out.append(f"{p['count']}× Ø{_g(p['d'])} {thr}, axis {ax}".replace("  ", " "))
    lone = [h for i, h in enumerate(holes) if i not in in_pat]
    for h in sorted(lone, key=lambda h: -float(h.get("d") or 0))[:3]:
        ax = _axis_letter(h.get("axis") or h.get("dir"))
        kind = "thru" if h.get("through") else f"blind {_g(h.get('depth') or 0)}"
        out.append(f"bore Ø{_g(h['d'])} {kind}, axis {ax} at {_in_plane(h.get('center') or [0, 0, 0], ax)}")
    for b in (rec.get("bosses") or [])[:2]:
        ax = _axis_letter(b.get("axis"))
        out.append(f"boss/shaft Ø{_g(b['d'])} × {_g(b.get('depth') or 0)}, axis {ax}")
    return out


def _line_key(pt: list[float], ax: list[float]) -> tuple[float, float, float]:
    d = sum(pt[k] * ax[k] for k in range(3))
    return tuple(round(pt[k] - d * ax[k], 2) for k in range(3))  # type: ignore[return-value]


def _angles(pos: Any, origin: list[float], ax: list[float]) -> list[float]:
    """Angles (degrees) of a face's tessellation points around its axis."""
    if not isinstance(pos, list) or len(pos) < 9:
        return []
    i = max(range(3), key=lambda k: abs(ax[k]))
    u, v = [k for k in range(3) if k != i]
    return [math.degrees(math.atan2(pos[j + v] - origin[v], pos[j + u] - origin[u])) % 360
            for j in range(0, len(pos) - 2, 3)]


def _coverage(angles: list[float]) -> float:
    """How far round the axis the faces reach: 360 for a full hole or shaft, about 90 for a rounded corner."""
    if not angles:
        return 360.0  # no tessellation: assume full
    a = sorted(angles)
    gaps = [b - x for x, b in itertools.pairwise(a)] + [a[0] + 360 - a[-1]]
    return 360.0 - max(gaps)


def interfaces_from_topo(topo: dict[str, Any], bbox: list[float] | None) -> list[str]:
    """Round features from the cylindrical faces: equal diameters on parallel axes, grouped into patterns. Partial
    cylinders (rounded corners, fillets) are left out; full ones are holes, bores or shafts."""
    groups: dict[tuple[float, str], dict[tuple[float, float, float], dict[str, Any]]] = {}
    for f in topo.get("faces") or []:
        if f.get("type") != "cylinder" or not f.get("radius") or not f.get("axis") or not f.get("axis_point"):
            continue
        ax = [abs(float(x)) for x in f["axis"]]
        letter = _axis_letter(ax)
        d = round(2 * float(f["radius"]), 2)
        o = [float(x) for x in f["axis_point"]]
        line = groups.setdefault((d, letter), {}).setdefault(_line_key(o, ax), {"pt": o, "angles": []})
        line["angles"] += _angles(f.get("pos"), o, ax)
    out: list[tuple[float, str]] = []
    for (d, ax), lines in groups.items():
        pts = [ln["pt"] for ln in lines.values() if _coverage(ln["angles"]) >= 300]
        n = len(pts)
        if not n:
            continue
        if bbox and ax in AXES and n == 1:
            i = AXES.index(ax)
            perp = [bbox[k + 3] - bbox[k] for k in range(3) if k != i]
            if all(abs(p - d) < 0.05 for p in perp):
                out.append((d * 10, f"outer Ø{_g(d)} along {ax}"))
                continue
        c = _centroid(pts)
        label = f"Ø{_g(d)}" if n == 1 else f"{n}× Ø{_g(d)}"
        extra = f" at {_in_plane(c, ax)}" if n == 1 else ""
        if n >= 4 and ax in AXES:  # grid first: a 2 × 2 grid is also on a circle
            keep = [k for k in range(3) if AXES[k] != ax]
            us = sorted({round(p[keep[0]], 2) for p in pts})
            vs = sorted({round(p[keep[1]], 2) for p in pts})
            if len(us) * len(vs) == n and len(us) >= 2 and len(vs) >= 2:
                du = {round(b - a, 2) for a, b in itertools.pairwise(us)}
                dv = {round(b - a, 2) for a, b in itertools.pairwise(vs)}
                if len(du) == 1 and len(dv) == 1:
                    extra = f" on {_g(du.pop())} × {_g(dv.pop())} grid centred {_in_plane(c, ax)}"
        if n >= 3 and not extra:
            rads = [math.dist(p, c) for p in pts]
            if max(rads) - min(rads) < 0.05 and min(rads) > 1e-3:
                extra = f" on Ø{_g(round(2 * rads[0], 2))} PCD centred {_in_plane(c, ax)}"
        if n == 2 and not extra:
            extra = f", {_g(round(math.dist(pts[0], pts[1]), 2))} apart"
        out.append((d * n, f"{label} round, axis {ax}{extra}"))
    out.sort(key=lambda t: -t[0])
    return [s for _, s in out]


def wizard_holes(ws: Path) -> list[str]:
    """Hole Wizard holes written in the model (standard size, type and fit), e.g. "4× M6 clearance Ø6.6 (medium)"."""
    try:
        from aicad.agent.runner import _manual_block

        feats = _manual_block((ws / "model.py").read_text(encoding="utf-8"))[1]
    except Exception:  # noqa: BLE001
        return []
    out: dict[str, int] = {}
    for f in feats:
        spec = f.get("spec") if isinstance(f, dict) else None
        if f.get("op") == "hole" and not f.get("suppressed") and isinstance(spec, dict) and spec.get("label"):
            out[spec["label"]] = out.get(spec["label"], 0) + _hole_count(f)
    return [f"{n}× {lab}" if n > 1 else lab for lab, n in out.items()]


def _hole_count(f: dict[str, Any]) -> int:
    pl = f.get("place") if isinstance(f.get("place"), dict) else None
    if pl and pl.get("mode") == "corners":
        return 4
    if pl and isinstance(pl.get("pts"), list):
        return max(1, len(pl["pts"]))
    c = f.get("count")
    return int(c) if isinstance(c, int) and c > 1 else 1



# ------------------------------------------------------------------ facts
_CACHE: dict[tuple[Any, ...], tuple[list[str], str]] = {}


def _mtime(f: Path) -> float:
    try:
        return f.stat().st_mtime
    except OSError:
        return 0.0


def interfaces(ws: Path, st: dict[str, Any]) -> tuple[list[str], str]:
    """Mating features of the current build (cached per build: topo.json can be large)."""
    key = (str(ws), st.get("build_id"), _mtime(ws / "out" / "recognition.json"), _mtime(ws / "model.py"))
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    rec = recognition_current(ws, st)
    if rec:
        ifaces, src = interfaces_from_recognition(rec), "recognition"
    else:
        bb = st.get("bbox_minmax")
        topo = _read(ws / "out" / "topo.json") or {}
        ifaces, src = interfaces_from_topo(topo, bb if isinstance(bb, list) else None), "faces"
    out = ((wizard_holes(ws) + ifaces)[:MAX_INTERFACES], src)
    if len(_CACHE) > 256:
        _CACHE.clear()
    _CACHE[key] = out
    return out


def part_facts(ws: Path, name: str) -> dict[str, Any]:
    """What the agent should know about a sibling part. ``built`` False when there is no verified build yet."""
    st = _read(ws / "out" / "status.json") or {}
    facts: dict[str, Any] = {"name": name, "built": bool(st.get("ok") and st.get("fingerprint"))}
    if not st.get("fingerprint"):
        return facts
    bb = st.get("bbox_minmax")
    if isinstance(bb, list) and len(bb) == 6:
        facts["size"] = [round(bb[i + 3] - bb[i], 3) for i in range(3)]
        facts["bbox"] = bb
    if st.get("material"):
        facts["material"] = str(st["material"])[:60]
    facts["revision"] = current_revision(ws)
    meta = st.get("param_meta") or {}
    params = []
    for k, v in (st.get("editable_params") or st.get("params") or {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            label = (meta.get(k) or {}).get("label")
            params.append(f"{k}={_g(v)}" + (f" ({label})" if label else ""))
    facts["params"] = params[:MAX_PARAMS]
    facts["interfaces"], facts["interfaces_from"] = interfaces(ws, st)
    if st.get("sheet_metal"):
        facts["sheet_metal"] = True
    return facts


def size_text(size: list[float] | None) -> str:
    return " × ".join(_g(round(x, 2)) for x in size) + " mm" if size else ""


def fact_line(f: dict[str, Any], limit: int = 300) -> str:
    """One bounded line: name (rev, material): size; interfaces; parameters."""
    head = f["name"]
    tags = [t for t in (f"rev {f['revision']}" if f.get("revision") else "", f.get("material") or "") if t]
    if tags:
        head += f" ({', '.join(tags)})"
    if not f.get("size"):
        return (head + ": not built yet")[:limit]
    bits = [size_text(f["size"])]
    if f.get("interfaces"):
        bits.append("; ".join(f["interfaces"]))
    if f.get("params"):
        bits.append("params " + ", ".join(f["params"]))
    line = head + ": " + "; ".join(bits)
    return line if len(line) <= limit else line[: limit - 1] + "…"
