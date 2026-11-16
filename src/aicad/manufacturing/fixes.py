"""Fix-it loop (IDEA-02, MAKE-14): turn a DFM finding into an action.

* ``param``: a deterministic parameter edit. Offered only when the finding's measured value equals exactly one
  editable design parameter of a compatible kind (a radius finding maps to a radius parameter, a hole diameter to a
  diameter parameter) and the target lies inside the parameter's declared limits. Applying it rebuilds the model
  without AI; the advisor then re-runs and reports the before/after delta.
* ``studio``: otherwise, a plain-language request for the Design Studio chat (prefilled, never auto-sent).
* ``note``: advice that belongs on the drawing (break sharp edges).

Nothing here changes a model by itself; the user applies every action.
"""

from __future__ import annotations

import math
import re
from typing import Any

from aicad.manufacturing.standards import fmt

REL_TOL = 1e-6


def param_kinds(name: str, meta: dict[str, Any] | None = None) -> set[str]:
    """Kinds a design parameter can stand for, from its name and label (radius, diameter, thickness)."""
    up = name.upper()
    lab = f"{(meta or {}).get('label') or ''} {name}".lower()
    kinds: set[str] = set()
    if "radius" in lab or "fillet" in lab or re.search(r"(^R\d*$|^R_|_R$|_R\d|RAD|FILLET|^[A-Z]R$)", up):
        kinds.add("radius")
    if "diameter" in lab or "ø" in lab or "bore" in lab or re.search(r"(^D\d*$|^D_|_D$|_D\d|DIA|BORE)", up):
        kinds.add("diameter")
    if "thick" in lab or "wall" in lab or re.search(r"(^T\d*$|^T_|_T$|THK|THICK|WALL)", up):
        kinds.add("thickness")
    return kinds


def param_fix(finding: dict[str, Any], editable: dict[str, Any],
              param_meta: dict[str, dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """The single parameter this finding's measured value comes from, and the value that resolves it, or None."""
    tgt = finding.get("target") or {}
    v = finding.get("value")
    if not tgt or v is None or not editable:
        return None
    meta = param_meta or {}
    hits = []
    for name, cur in editable.items():
        if isinstance(cur, bool) or not isinstance(cur, (int, float)) or re.search(r"(^N_|^N$|COUNT|NUM|QTY)", name.upper()):
            continue  # counts and flags are never sizes
        if abs(float(cur) - float(v)) > REL_TOL * max(1.0, abs(float(v))):
            continue
        if tgt["kind"] in param_kinds(name, meta.get(name)):
            hits.append(name)
    if len(hits) != 1:
        return None  # nothing, or ambiguous: never guess which parameter the user meant
    name = hits[0]
    to = float(tgt["to"])
    m = meta.get(name) or {}
    if ("min" in m and to < float(m["min"])) or ("max" in m and to > float(m["max"])) or not math.isfinite(to):
        return None
    if abs(to - float(editable[name])) < 1e-9:
        return None
    if isinstance(editable[name], int) and not to.is_integer():
        return None  # whole-number parameter: the parameter editor would refuse a fractional value
    label = m.get("label")
    unit = m.get("unit") or "mm"
    return {"kind": "param", "param": name, "param_label": label, "from": float(editable[name]), "to": to,
            "unit": unit, "why": tgt.get("why"),
            "label": f"Set {label or name} {fmt(float(editable[name]))} → {fmt(to)} {unit}"}


def studio_prompt(f: dict[str, Any], part: str | None = None) -> str:
    """A request for the design agent, in plain engineering language (no ids, no internals)."""
    where = ", ".join(f.get("features") or []) or f.get("where") or "the highlighted area"
    return (f"Manufacturability check on {part or 'this part'}: {f['title']}. Where: {where}. "
            f"Measured {f['measured']}; recommended {f['limit']}. Suggested fix: {f['fix']} "
            "Please change the design to resolve this, keep every other dimension unchanged, then rebuild and check.")


def attach(a: dict[str, Any], editable: dict[str, Any] | None, param_meta: dict[str, Any] | None,
           fresh: bool = True) -> dict[str, Any]:
    """A copy of the analysis with an ``action`` on each finding that has one. Parameter fixes need a fresh
    analysis (the parameter values must belong to the analysed build)."""
    part = (a.get("build") or {}).get("part") or (a.get("project") or {}).get("name")
    out = []
    for f in a.get("findings", []):
        act = None
        if f.get("note"):
            act = {"kind": "note", "text": f["note"], "label": "Add to drawing"}
        elif f["severity"] in ("critical", "warning"):
            act = (param_fix(f, editable or {}, param_meta) if fresh else None) or {
                "kind": "studio", "label": "Fix in Studio", "prompt": studio_prompt(f, part)}
        out.append({**f, "action": act})
    return {**a, "findings": out}


def primary_unit_cost(a: dict[str, Any]) -> float | None:
    c = a.get("cost") or {}
    p = (c.get("processes") or {}).get(c.get("primary") or "")
    return float(p["unit_cost"]) if p else None


def delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Before/after of a fix: severity counts across all processes and the primary process unit cost."""
    b = before.get("summary") or before.get("chk13", {}).get("counts") or {}
    c = after.get("summary") or after.get("chk13", {}).get("counts") or {}
    out: dict[str, Any] = {s: {"before": int(b.get(s, 0)), "after": int(c.get(s, 0))} for s in ("critical", "warning", "info")}
    ub, ua = primary_unit_cost(before), primary_unit_cost(after)
    same = (before.get("cost") or {}).get("primary") == (after.get("cost") or {}).get("primary")
    out["cost"] = {"before": ub, "after": ua, "pct": round(100 * (ua - ub) / ub, 1) if ub and ua is not None and same
                   else None, "process": (after.get("cost") or {}).get("primary")}
    parts = [f"{s} {out[s]['before']} → {out[s]['after']}" for s in ("critical", "warning")
             if out[s]["before"] != out[s]["after"]]
    if out["cost"]["pct"] is not None and abs(out["cost"]["pct"]) >= 0.1:
        parts.append(f"unit cost {out['cost']['pct']:+.1f} %")
    out["text"] = "; ".join(parts) if parts else "no change in findings or cost"
    return out
