"""When the Design Office lays a program out from a master model (WORKLIST 50): a deterministic rule.

Founder (2026-11-20): "hybrid master model, used only when needed", and the golden suite decides the default. The
fast path (the design graph, the connection solver or the standard layout, spec builds) stays the default; the master
path is taken when one of these holds, checked in this order and all recorded:

  product     the brief is a free-form product (an enclosure, shells, a handheld device, an appliance) and the plan
              has no shafts, gears or bearings: its shapes and joints come from the shape, not a connection pattern
  adapter     a designed part is a custom adapter (an adapter or interface plate): its holes come from two parts
  unsupported the design graph has connections the solver can't lay out yet (``layout.Unsupported``)
  conflict    the solver reports a ``layout_conflict`` (connections that can't all hold)
  unreachable a part no connection reaches (it would lie beside the program), or a bought-out joint part (a pin,
              a pivot, an axle) no interface places (the gate's ``part_unplaced`` warning; an oil plug is not one)
  gate        the fast layout fails a placement check at the interfaces gate (``icd.problems``), run here as a trial on
              the very plan the gate will see (same code, same input: the same result)

``FW_MASTER_MODEL``: ``auto`` (default, the rule), ``0`` / ``off`` (always the fast path), ``force`` (always the master
path, for the golden comparison). The decision is a plain dict on ``plan["layout_path"]``; the plan review shows its
``words`` ("Laid out from a master model (new structure)").
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

ENV = "FW_MASTER_MODEL"
MAX_BODIES = 40   # designed bodies one master turn models; larger programs keep the fast path (PD-184)
PRODUCT = re.compile(
    r"enclosure|\bshells?\b|controller|game ?pad|joystick|hand-?held|remote control|\bconsole\b|appliance|gadget|"
    r"\btoy\b|ergonomic|consumer product|wearable|\bphone\b|\btablet\b|\bcase for\b|housing for (?:the )?"
    r"(?:electronics|pcb|board|battery)|\bmou?lded\b", re.IGNORECASE)
MECHANISM = re.compile(r"shaft|axle|spindle|\bgear|pinion|bearing|\b6[02]0\d\b|pulley|sprocket", re.IGNORECASE)
JOINT = re.compile(r"pin|dowel|pivot|hinge|axle|rod|shaft", re.IGNORECASE)  # bought-out parts that ARE a joint
ADAPTER = re.compile(r"\badapt[eo]r\b|interface plate|transition (?:plate|piece)", re.IGNORECASE)
WORDS = {
    "product": "free-form product",
    "adapter": "custom adapter part",
    "unsupported": "new structure",
    "conflict": "the fast layout has a conflict",
    "unreachable": "a part no connection reaches",
    "gate": "the fast layout fails a placement check",
    "forced": "forced for comparison",
}


def mode() -> str:
    v = os.environ.get(ENV, "").strip().lower()
    if v in ("0", "off", "false", "no", "fast"):
        return "off"
    if v in ("force", "always", "master"):
        return "force"
    return "auto"


def _parts(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for s in plan.get("subassemblies") or [] for p in s.get("parts") or []]


def pseudo_doc(plan: dict[str, Any], brief: str, name: str = "Program") -> dict[str, Any]:
    """The program as the interfaces gate will see it after plan approval (items from the plan, no tickets run)."""
    from aicad.office import service

    items, tickets = service._build(plan, name or "Program", "P", brief)
    return {"plan": plan, "items": items, "tickets": tickets, "brief": brief, "name": name}


def trial(plan: dict[str, Any], brief: str, name: str = "") -> dict[str, Any]:
    """The fast path's layout of this plan, run as a trial: {"solver", "unsupported", "conflicts", "unreachable",
    "problems", "seconds"}. Deterministic and quick (no CAD)."""
    from aicad.graph import layout
    from aicad.graph.compile import overrides_for
    from aicad.office import icd, interfaces

    t0 = time.perf_counter()
    doc = pseudo_doc(plan, brief, name)
    parts = icd.parts_from(doc)
    ov = overrides_for(plan, parts)
    out: dict[str, Any] = {"solver": None, "unsupported": None, "conflicts": [], "unreachable": [], "problems": []}
    g = layout.graph_of(plan)
    skel = ifs = None
    if g is not None and layout.enabled():
        try:
            skel, ifs = layout.build(g, parts, brief, ov, resolved=True)
        except layout.Unsupported as e:
            out["unsupported"] = str(e)
        except Exception as e:  # noqa: BLE001 - a solver crash on this graph: the same as a structure it can't place
            out["unsupported"] = f"the solver failed ({type(e).__name__})"
    if skel is None and out["unsupported"] is None:
        skel, ifs = interfaces._rebuild(doc, ov or {})
    if skel is not None and ifs is not None:
        out["solver"] = skel.get("solver") or skel.get("layout")
        for c in skel.get("conflicts") or []:
            (out["unreachable"] if "not placed by any connection" in c.get("text", "") else out["conflicts"]).append(
                c["text"])
        out["problems"] = [p for p in icd.problems(skel, ifs) if not p.startswith("Layout conflict")]
        # a bought-out joint part no interface places (the hinge pin that vanished, golden F3) is unreachable too;
        # an accessory nothing places (an oil plug, a seal) is not a layout problem (it stays in the BOM, said)
        names = {i["id"]: i["name"] for i in doc["items"]}
        out["unreachable"] += [x["text"] for x in icd.issues(skel, ifs) if x["code"] == "part_unplaced"
                               and any(JOINT.search(names.get(i, "")) for i in x.get("items") or [])]
    out["seconds"] = round(time.perf_counter() - t0, 3)
    return out


def decide(plan: dict[str, Any], brief: str, name: str = "") -> dict[str, Any]:
    """The layout path for a plan: {"path": "fast" | "master", "reasons": [{"code", "text"}], "words", "mode",
    "trial"}. Deterministic: the same plan and brief give the same decision."""
    md = mode()
    reasons: list[dict[str, str]] = []
    designed = [p for p in _parts(plan) if p.get("family") != "standard"]
    text = " ".join([brief or "", name or ""] + [str(p.get("name") or "") for p in designed])
    if md == "off":
        return {"path": "fast", "reasons": [], "mode": md, "trial": None,
                "words": "Laid out on the fast path (the master model is switched off)"}
    mech = any(MECHANISM.search(str(p.get("name") or "")) for p in _parts(plan))
    hit = PRODUCT.search(text)
    if hit and not mech:
        reasons.append({"code": "product", "text": f"The brief is a free-form product (\"{hit.group(0)}\"): its "
                        "shapes and joints come from the shape itself, not from a known connection pattern."})
    for p in designed:
        if ADAPTER.search(str(p.get("name") or "")):
            reasons.append({"code": "adapter", "text": f"{p['name']} is a custom adapter: its holes and faces come "
                            "from both parts it joins, so they are measured from one model."})
            break
    tr = trial(plan, brief, name)
    if tr["unsupported"]:
        reasons.append({"code": "unsupported", "text": "The connection solver can't lay this structure out yet: "
                        + tr["unsupported"] + "."})
    if tr["conflicts"]:
        reasons.append({"code": "conflict", "text": tr["conflicts"][0]})
    if tr["unreachable"]:
        reasons.append({"code": "unreachable", "text": tr["unreachable"][0]})
    if tr["problems"]:
        reasons.append({"code": "gate", "text": "The fast layout fails a placement check at the interfaces gate: "
                        + tr["problems"][0]})
    if md == "force" and not reasons:
        reasons.append({"code": "forced", "text": "The master path is forced on this server (golden comparison)."})
    path = "master" if reasons else "fast"
    from aicad.office.icd import MAX_COPIES

    bodies = sum(min(int(p.get("qty") or 1), MAX_COPIES) for p in designed)
    if path == "master" and bodies > MAX_BODIES:  # one skeleton per sub-assembly is not built yet (PD-184)
        return {"path": "fast", "reasons": reasons, "mode": md, "trial": tr, "too_large": bodies,
                "words": f"Laid out on the fast path ({bodies} bodies is more than one master model takes)"}
    if path == "master":
        words = f"Laid out from a master model ({WORDS[reasons[0]['code']]})"
    elif tr["solver"] == "graph":
        words = "Laid out by the connection solver (fast path)"
    elif tr["solver"] == "roles":
        words = "Laid out from the parts' roles (fast path)"
    else:
        words = "Laid out with the standard layout (fast path)"
    return {"path": path, "reasons": reasons, "words": words, "mode": md, "trial": tr}
