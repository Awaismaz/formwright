"""Change notice: what changed between two revisions of a part, and why, in shop language (deterministic).

Inputs are the revision snapshots (`revisions/<n>/status.json`, `model.py`, `cause.json`). Nothing is inferred
that isn't in the data: parameter values, recorded features, manual features, the exact volume/mass/size of the
verified models, material, and the gating checks. The "why" is the request or action that produced the revision,
recorded at snapshot time.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aicad import materials

MANUAL_START = "# --- Formwright manual features"


def _json(p: Path) -> dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _manual(src: str) -> list[dict[str, Any]]:
    if MANUAL_START not in src:
        return []
    for node in ast.parse(src[src.index(MANUAL_START):]).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "MANUAL_FEATURES":
            try:
                return list(ast.literal_eval(node.value))
            except ValueError:
                return []
    return []


def load_revision(d: Path) -> dict[str, Any]:
    st = _json(d / "status.json")
    try:
        src = (d / "model.py").read_text(encoding="utf-8")
    except OSError:
        src = ""
    return {"n": int(d.name), "status": st, "manual": _manual(src), "cause": _json(d / "cause.json"),
            "views": (d / "views.png").is_file(),
            "created_at": datetime.fromtimestamp(d.stat().st_mtime, UTC).replace(tzinfo=None).isoformat(timespec="minutes")}


def _num(v: Any) -> str:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return str(v)
    return f"{v:g}" if isinstance(v, int) or abs(v) >= 1e-3 else f"{v:.3g}"


def _mass_g(st: dict[str, Any]) -> float | None:
    m = materials.get(materials.guess(st.get("material")))
    vol = (st.get("fingerprint") or {}).get("volume")
    if not m or vol is None:
        return None
    return float(vol) * float(m["density_g_cm3"]) / 1000.0


def _feature_states(st: dict[str, Any]) -> dict[str, bool]:
    """Recorded feature name -> suppressed? (blank/edit bookkeeping entries excluded)."""
    return {f["name"]: bool(f.get("suppressed")) for f in st.get("features") or []
            if f.get("kind") not in ("edit",) and f.get("name")}


def diff(prev: dict[str, Any], cur: dict[str, Any]) -> dict[str, Any]:
    """Structured changes plus readable lines, prev → cur."""
    ps, cs = prev["status"], cur["status"]
    lines: list[str] = []
    # parameters
    pp, cp = ps.get("params") or {}, cs.get("params") or {}
    params = [{"name": k, "from": pp.get(k), "to": cp.get(k)} for k in sorted(set(pp) | set(cp)) if pp.get(k) != cp.get(k)]
    for x in params:
        if x["from"] is None:
            lines.append(f"New parameter {x['name']} = {_num(x['to'])}")
        elif x["to"] is None:
            lines.append(f"Parameter {x['name']} removed (was {_num(x['from'])})")
        else:
            lines.append(f"{x['name']}: {_num(x['from'])} → {_num(x['to'])}")
    # recorded design features
    fp, fc = _feature_states(ps), _feature_states(cs)
    added = [n for n in fc if n not in fp]
    removed = [n for n in fp if n not in fc]
    suppressed = [n for n in fc if n in fp and fc[n] and not fp[n]]
    restored = [n for n in fc if n in fp and fp[n] and not fc[n]]
    manual_prev = {m.get("id"): m for m in prev["manual"]}
    manual_cur = {m.get("id"): m for m in cur["manual"]}
    edited = [m.get("name", m.get("op")) for i, m in manual_cur.items() if i in manual_prev
              and {k: v for k, v in m.items() if k != "editor"} != {k: v for k, v in manual_prev[i].items() if k != "editor"}
              and m.get("suppressed") == manual_prev[i].get("suppressed")]
    for label, names in (("Added", added), ("Removed", removed), ("Suppressed", suppressed), ("Restored", restored),
                         ("Edited", edited)):
        if names:
            lines.append(f"{label}: " + ", ".join(names))
    # geometry
    gp, gc = ps.get("fingerprint") or {}, cs.get("fingerprint") or {}
    geo: dict[str, Any] = {}
    if gp.get("volume") is not None and gc.get("volume") is not None:
        dv = float(gc["volume"]) - float(gp["volume"])
        geo["volume"] = {"from": gp["volume"], "to": gc["volume"], "delta": dv,
                         "pct": 100 * dv / float(gp["volume"]) if gp["volume"] else None}
        if abs(dv) > 1e-6:
            lines.append(f"Volume {dv:+,.1f} mm³ ({geo['volume']['pct']:+.2f} %)")
    mp, mc = _mass_g(ps), _mass_g(cs)
    if mp is not None and mc is not None:
        geo["mass_g"] = {"from": mp, "to": mc, "delta": mc - mp}
        if abs(mc - mp) > 1e-3:
            lines.append(f"Mass {mc - mp:+,.1f} g (now {mc:,.1f} g)")
    if gp.get("bbox") and gc.get("bbox"):
        geo["bbox"] = {"from": gp["bbox"], "to": gc["bbox"]}
        if any(abs(a - b) > 1e-6 for a, b in zip(gp["bbox"], gc["bbox"], strict=False)):
            lines.append("Envelope " + " × ".join(_num(round(v, 3)) for v in gp["bbox"]) + " → "
                         + " × ".join(_num(round(v, 3)) for v in gc["bbox"]) + " mm")
    material = None
    if ps.get("material") != cs.get("material"):
        material = {"from": ps.get("material"), "to": cs.get("material")}
        lines.append(f"Material: {ps.get('material') or '—'} → {cs.get('material') or '—'}")
    gating = lambda st: sorted(c["id"] for c in st.get("checks") or [] if c.get("gating") and not c.get("passed"))
    checks = {"from_ok": bool(ps.get("ok")), "to_ok": bool(cs.get("ok")), "failing": gating(cs)}
    if not lines:
        lines.append("No change to parameters, features or geometry (rebuild only)")
    return {"params": params, "features": {"added": added, "removed": removed, "suppressed": suppressed,
                                           "restored": restored, "edited": edited},
            "geometry": geo, "material": material, "checks": checks, "lines": lines}


def notice(rev_root: Path, n: int, base: int | None = None) -> dict[str, Any]:
    """Change notice for revision n against `base` (default: the previous revision)."""
    cur_dir = rev_root / str(n)
    if not cur_dir.is_dir():
        raise FileNotFoundError(n)
    nums = sorted(int(d.name) for d in rev_root.iterdir() if d.is_dir() and d.name.isdigit())
    if base is None:
        older = [x for x in nums if x < n]
        base = older[-1] if older else None
    cur = load_revision(cur_dir)
    out: dict[str, Any] = {"revision": n, "base": base, "part": cur["status"].get("part"),
                           "material": cur["status"].get("material"), "created_at": cur["created_at"],
                           "why": cur["cause"].get("cause"), "kind": cur["cause"].get("kind"), "by": cur["cause"].get("by"),
                           "views": cur["views"], "ok": bool(cur["status"].get("ok")),
                           "fingerprint": cur["status"].get("fingerprint")}
    if base is None:
        out.update(first=True, changes={"lines": ["First revision of this part"]})
        return out
    prev = load_revision(rev_root / str(base))
    out.update(first=False, base_views=prev["views"], base_created_at=prev["created_at"], changes=diff(prev, cur))
    return out
