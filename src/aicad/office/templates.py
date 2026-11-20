"""Workspace templates harvested from AI-designed parts (WORKLIST 48).

When the design agent writes a part that passes the build gate and Gage and whose script is parametric (``PARAMS``
with ``PARAM_META``), the engineer can keep it as a template of the workspace: its family, its parameters, which
interface features it serves, and the part it came from. The next ticket that needs the same family with compatible
features starts from the closest template, or is built from it directly (no AI) when every parameter maps onto the
new part's interface quantities.

Everything here is deterministic and pure apart from the small file store (``<org root>/templates/<id>.json``,
tenant scoped by the organisation root). Similarity is plain arithmetic: the family must match; then half the score is
the overlap of the feature sets (multiset Jaccard of feature type and axis), half the size ratio (the mean of
min / max over the envelope sizes).

Parameter mapping (``bind``): each numeric parameter of the template is matched by value against the source part's
named interface quantities (envelope sizes, hole / seat / bore / boss Ø, seat depths, keyway sizes, PCDs, gear
module and teeth). A parameter equal to one or more quantities is *bound* to them; a finish parameter (chamfer,
fillet, radius, edge break) keeps its value; anything else is a *design* value. A template is used directly only when
the feature sets are the same, every parameter is bound or a finish, and the bound quantities agree on the new part;
the build gate and the ICD conformance review still check the result (a direct build that fails falls back to the
design agent, as the interface generators do).
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from aicad.office import icd

VERSION = 1
LABEL = "Built from a workspace template (no AI)"
DIRECT_MIN = 0.999   # the same feature set and sizes within the size ratio below: used directly
SEED_MIN = 0.5       # below this a template is not offered as a starting point
_FINISH = re.compile(r"CHAMFER|FILLET|RADIUS|BREAK|(^|_)R($|_)", re.IGNORECASE)
_ID = re.compile(r"^[a-f0-9]{12}$")
TOL = 1e-6


class TemplateError(Exception):
    """Why a part can't be kept as a template (plain words)."""


# ============================================================================ what a part is, in numbers
def family(doc: dict[str, Any], item: str) -> str:
    from aicad.office import generators, scope

    sk = doc["skeleton"]
    it = sk["items"][item]
    name = str(it.get("name") or "")
    desc = next((str(i.get("description") or "") for i in doc.get("items") or [] if i["id"] == item), "")
    try:
        k = generators.kind_of(doc, item, name, desc)
    except (KeyError, TypeError, ValueError):
        k = None
    if k:
        return k
    return f"{it.get('role')}:{scope.kind_of(name) or it.get('role')}"


def signature(doc: dict[str, Any], item: str) -> dict[str, int]:
    """The interface features a part carries: counts of (type, axis)."""
    out: dict[str, int] = {}
    for x in icd.item_features(doc["skeleton"], doc["icd"]["interfaces"], item):
        k = f"{x['type']}:{x.get('ax') or 'z'}" + (f":{x['on']}" if x.get("on") else "")
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def quantities(doc: dict[str, Any], item: str) -> dict[str, float]:
    """Named interface quantities of a part: envelope, feature Ø (distinct, sorted), seat depths, keyways, PCDs."""
    sk = doc["skeleton"]
    it = sk["items"][item]
    size = [float(v) for v in it["size"]]
    q: dict[str, float] = {}
    if it.get("shape") == "box":
        q.update(L=size[0], W=size[1], H=size[2])
    else:
        q.update(D=size[0], H=size[2])
    if it.get("bore"):
        q["bore"] = float(it["bore"])
    feats = icd.item_features(sk, doc["icd"]["interfaces"], item)
    by: dict[str, set[float]] = {}
    for x in feats:
        if x.get("d") is not None:
            by.setdefault(f"{x['type']}_d", set()).add(round(float(x["d"]), 4))
        if x["type"] == "seat" and x.get("z0") is not None:
            by.setdefault("seat_depth", set()).add(round(abs(float(x["z1"]) - float(x["z0"])), 4))
        if x["type"] == "hole" and x.get("z0") is not None:
            by.setdefault("hole_depth", set()).add(round(abs(float(x["z1"]) - float(x["z0"])), 4))
        if x["type"] == "keyway":
            by.setdefault("key_b", set()).add(float(x["b"]))
            by.setdefault("key_depth", set()).add(float(x["depth"]))
        if x["type"] == "gear":
            q["module"], q["teeth"] = float(x["module"]), float(x["teeth"])
    for f in doc["icd"]["interfaces"]:
        if item in (f["a"]["item"], f["b"]["item"]) and (f.get("data") or {}).get("pcd"):
            by.setdefault("pcd", set()).add(float(f["data"]["pcd"]))
    for k, vs in sorted(by.items()):
        for n, v in enumerate(sorted(vs), start=1):
            q[f"{k}{n}"] = v
    return q


def script_params(source: str) -> dict[str, float]:
    """Top-level ``NAME = number`` assignments of a model script (the editable parameters)."""
    out: dict[str, float] = {}
    for m in re.finditer(r"^([A-Z][A-Z0-9_]*)\s*=\s*(-?\d+(?:\.\d+)?)\s*(?:#.*)?$", source, re.MULTILINE):
        out[m.group(1)] = float(m.group(2))
    return out


def bind(params: dict[str, float], q: dict[str, float]) -> dict[str, dict[str, Any]]:
    """Each parameter: {"to": [quantity names]} (bound), {"finish": True} or {"design": True}."""
    out: dict[str, dict[str, Any]] = {}
    for name, v in params.items():
        hits = sorted(k for k, x in q.items() if abs(x - v) < TOL)
        if hits:
            out[name] = {"to": hits, "value": v}
        elif _FINISH.search(name):
            out[name] = {"finish": True, "value": v}
        else:
            out[name] = {"design": True, "value": v}
    return out


# ============================================================================ eligibility and harvesting
def eligible(t: dict[str, Any], state: dict[str, Any]) -> str | None:
    """None when this ticket's part can be kept as a template, else why not."""
    if t.get("kind") != "part":
        return "only designed parts can be kept as templates"
    if (t.get("direct") or {}).get("path") == "direct" and not (t.get("direct") or {}).get("superseded"):
        return "this part was built from the interface spec already (no AI to keep)"
    if t.get("column") not in ("approved", "integrated", "done"):
        return "keep a part as a template once it is approved"
    src = str(state.get("source") or "")
    if not state.get("ok"):
        return "the part's latest build doesn't pass its checks"
    if not re.search(r"^PARAMS\s*=", src, re.MULTILINE) or not re.search(r"^PARAM_META\s*=", src, re.MULTILINE):
        return "the part's script has no PARAMS and PARAM_META, so it isn't parametric"
    if not script_params(src):
        return "the part's script has no numeric parameters"
    return None


def _dir(root: Path) -> Path:
    return root / "templates"


def harvest(root: Path, doc: dict[str, Any], t: dict[str, Any], state: dict[str, Any], by: str) -> dict[str, Any]:
    why = eligible(t, state)
    if why:
        raise TemplateError(why)
    item = t["item_id"]
    if not interfaces_ok(doc, item):
        raise TemplateError("the program has no approved interfaces for this part")
    src = str(state["source"])
    params = script_params(src)
    q = quantities(doc, item)
    tid = uuid.uuid4().hex[:12]
    rec = {"schema": "fw-template", "version": VERSION, "id": tid, "name": t["title"], "family": family(doc, item),
           "signature": signature(doc, item), "quantities": q, "params": params, "bindings": bind(params, q),
           "script": src, "material": _material_of(src),
           "answers": [x for x in (t.get("direct") or {}).get("reasons") or [] if str(x).startswith("the brief")],
           "source": {"program": doc["id"], "program_name": doc.get("name"), "ticket": t["id"], "title": t["title"],
                      "project_id": t.get("project_id"), "icd_version": (doc.get("icd") or {}).get("version")},
           "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "created_by": by, "uses": 0}
    d = _dir(root)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{tid}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    return public(rec)


def interfaces_ok(doc: dict[str, Any], item: str) -> bool:
    return bool((doc.get("icd") or {}).get("interfaces") is not None and item in ((doc.get("skeleton") or {})
                                                                                   .get("items") or {}))


def _material_of(src: str) -> str | None:
    m = re.search(r'^MATERIAL\s*=\s*"([^"]*)"', src, re.MULTILINE)
    return m.group(1) if m else None


def load_all(root: Path) -> list[dict[str, Any]]:
    d = _dir(root)
    out = []
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if r.get("schema") == "fw-template":
            out.append(r)
    return sorted(out, key=lambda r: (r.get("created_at") or "", r["id"]))


def public(r: dict[str, Any]) -> dict[str, Any]:
    """What the library shows: no script, plain counts."""
    b = r.get("bindings") or {}
    return {"id": r["id"], "name": r["name"], "family": r["family"], "features": r.get("signature") or {},
            "params": len(r.get("params") or {}), "mapped": sum(1 for v in b.values() if v.get("to")),
            "finish": sum(1 for v in b.values() if v.get("finish")),
            "design": sum(1 for v in b.values() if v.get("design")),
            "source": r.get("source") or {}, "created_at": r.get("created_at"), "created_by": r.get("created_by"),
            "uses": int(r.get("uses") or 0), "material": r.get("material")}


def get(root: Path, tid: str) -> dict[str, Any] | None:
    """One template of this workspace (``root`` is the organisation's office root: tenant scoped), or None."""
    if not _ID.fullmatch(tid or ""):
        return None
    try:
        r = json.loads((_dir(root) / f"{tid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return r if isinstance(r, dict) and r.get("schema") == "fw-template" else None


def param_meta(src: str) -> dict[str, dict[str, Any]]:
    """The script's ``PARAM_META`` literal (labels, units, limits), read without running anything."""
    import ast

    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PARAM_META" for t in node.targets):
            try:
                v = ast.literal_eval(node.value)
            except (ValueError, SyntaxError, TypeError):
                return {}
            return {str(k): x for k, x in v.items() if isinstance(x, dict)} if isinstance(v, dict) else {}
    return {}


def studio_view(r: dict[str, Any]) -> dict[str, Any]:
    """A template as the Design Studio's Toolbox shows it: the library card plus its editable parameters (value,
    label, unit, limits) so the engineer can start a part from it."""
    meta = param_meta(str(r.get("script") or ""))
    rows = []
    for name, value in (r.get("params") or {}).items():
        m = meta.get(name) or {}
        words = [w if len(w) <= 3 else w.capitalize() for w in name.split("_")]  # OD, BORE_D -> "OD", "Bore D"
        rows.append({"name": name, "value": float(value), "label": str(m.get("label") or " ".join(words)),
                     "unit": str(m.get("unit") or ""), "group": str(m.get("group") or ""),
                     "min": m.get("min"), "max": m.get("max")})
    return {**public(r), "param_list": rows}


def studio_source(r: dict[str, Any], values: dict[str, Any] | None = None, name: str | None = None) -> str:
    """The template's model script with the engineer's values (only its own parameters, finite numbers inside the
    script's own limits), ready to build as a Design Studio part."""
    import math

    params = r.get("params") or {}
    meta = param_meta(str(r.get("script") or ""))
    clean: dict[str, float] = {}
    for k, v in (values or {}).items():
        if k not in params:
            raise TemplateError(f"{k} is not a parameter of this template")
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise TemplateError(f"{k} must be a number") from None
        if not math.isfinite(x):
            raise TemplateError(f"{k} must be a number")
        m = meta.get(k) or {}
        lo, hi = m.get("min"), m.get("max")
        if isinstance(lo, (int, float)) and x < float(lo) - TOL or isinstance(hi, (int, float)) and x > float(hi) + TOL:
            raise TemplateError(f"{m.get('label') or k} must be between {lo:g} and {hi:g}")
        clean[k] = x
    return substitute(str(r.get("script") or ""), clean, name)


def delete(root: Path, tid: str) -> bool:
    if not _ID.fullmatch(tid or ""):
        return False
    p = _dir(root) / f"{tid}.json"
    if not p.is_file():
        return False
    p.unlink()
    return True


def note_use(root: Path, tid: str) -> None:
    p = _dir(root) / f"{tid}.json"
    try:
        r = json.loads(p.read_text(encoding="utf-8"))
        r["uses"] = int(r.get("uses") or 0) + 1
        p.write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")
    except (OSError, ValueError):
        return


# ============================================================================ reuse
def similarity(r: dict[str, Any], sig: dict[str, int], q: dict[str, float]) -> float:
    a, b = r.get("signature") or {}, sig
    keys = set(a) | set(b)
    num = sum(min(a.get(k, 0), b.get(k, 0)) for k in keys)
    den = sum(max(a.get(k, 0), b.get(k, 0)) for k in keys)
    feat = num / den if den else 1.0
    env = [k for k in ("L", "W", "H", "D") if k in q and k in (r.get("quantities") or {})]
    ratios = [min(q[k], r["quantities"][k]) / max(q[k], r["quantities"][k]) for k in env
              if q[k] > 0 and r["quantities"][k] > 0]
    size = sum(ratios) / len(ratios) if ratios else 0.0
    return round(0.5 * feat + 0.5 * size, 4)


def mapped_values(r: dict[str, Any], q: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    """(new values for the bound parameters, parameters that don't map)."""
    vals: dict[str, float] = {}
    loose: list[str] = []
    for name, b in (r.get("bindings") or {}).items():
        if b.get("to"):
            got = {round(q[k], 6) for k in b["to"] if k in q}
            if len(got) == 1 and all(k in q for k in b["to"]):
                vals[name] = got.pop()
            else:
                loose.append(name)
        elif b.get("design"):
            loose.append(name)
    return vals, loose


def substitute(src: str, values: dict[str, float], name: str | None = None) -> str:
    def fmt(v: float) -> str:
        v = round(float(v), 4) + 0.0
        return f"{v:.1f}" if v.is_integer() else repr(v)

    for k, v in values.items():
        src = re.sub(rf"^({re.escape(k)}\s*=\s*)-?\d+(?:\.\d+)?", lambda m, v=v: m.group(1) + fmt(v), src, count=1,
                     flags=re.MULTILINE)
    if name:
        src = re.sub(r'^NAME\s*=\s*"[^"]*"', 'NAME = "' + name.replace('"', "'") + '"', src, count=1, flags=re.MULTILINE)
    return src


def plan(root: Path, doc: dict[str, Any], t: dict[str, Any], dp: dict[str, Any]) -> dict[str, Any] | None:
    """A template for this ticket, as a decision like ``direct.plan`` gives: path "direct" (source "template") when
    every parameter maps, else the agent seeded with the closest template; None when no template fits."""
    from aicad.office import direct

    item = t["item_id"]
    if t.get("kind") != "part" or not interfaces_ok(doc, item) or (doc.get("icd") or {}).get("status") != "approved":
        return None
    recs = load_all(root)
    if not recs:
        return None
    fam = family(doc, item)
    sig = signature(doc, item)
    q = quantities(doc, item)
    best = None
    for r in recs:
        if r.get("family") != fam:
            continue
        s = similarity(r, sig, q)
        if best is None or s > best[0]:
            best = (s, r)
    if best is None or best[0] < SEED_MIN:
        return None
    score, r = best
    vals, loose = mapped_values(r, q)
    script = substitute(r["script"], vals, t["title"])
    info = {"id": r["id"], "name": r["name"], "score": score, "source": r.get("source") or {}, "mapped": len(vals),
            "loose": loose}
    same = (r.get("signature") or {}) == sig
    reasons = [x for x in dp.get("reasons") or [] if not x.startswith("starting from")]
    if same and not loose and not reasons_beyond(reasons, r.get("answers") or []):
        return {"path": "direct", "kind": f"template:{fam}", "script": script, "sha": direct.sha(script),
                "summary": f"from the workspace template {r['name']} ({len(vals)} parameters mapped to the interfaces)",
                "material": r.get("material") or "", "icd_version": doc["icd"]["version"], "version": VERSION,
                "features": sum(sig.values()), "label": LABEL, "template": info}
    if dp.get("seed") and not same:  # the interface model fits better than a template of other features
        return {**dp, "template_hint": info}
    seed = {"kind": f"template:{fam}", "script": script, "sha": direct.sha(script),
            "summary": f"the workspace template {r['name']} (similarity {score:.2f})", "material": r.get("material") or "",
            "icd_version": doc["icd"]["version"], "version": VERSION, "features": sum(sig.values()),
            "template": info}
    why = [f"starting from the workspace template {r['name']} (similarity {score:.2f}"
           + (f"; {', '.join(loose[:4])} to fit" if loose else "") + ")"]
    return {"path": "agent", "reasons": reasons + why, "seed": seed, "template": info}


def reasons_beyond(reasons: list[str], answered: list[str]) -> bool:
    """What the brief asks now that the template's own part didn't have to answer. A template is a finished design
    of the same family: "needs the designer" reasons don't block it, and neither do the brief's extras its source
    part was designed for; anything new does."""
    return any(r.startswith("the brief") and r not in answered for r in reasons)
