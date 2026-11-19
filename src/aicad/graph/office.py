"""The Design Office hook (``FW_DESIGN_GRAPH=1``): plan a program by intent -> design graph -> plan / ICD.

With the flag on, Archie's planning turn is the intent compiler (``graph.intent``) instead of the free-text planner
(``office/planner.run_agent``). The graph is compiled to an ordinary plan (``graph.compile.to_plan``), so everything
after plan review (tickets, ICD, direct builds, Fitz, Gage) runs unchanged. The plan carries ``plan["graph"]``:

  data        the graph (the source of truth for this program's plan)
  view        the compact readable list shown at plan review (components, connections; no internals)
  questions   open clarifying questions (at most 3); the plan can't be approved until they are answered
  check       the cross-check of the graph against the ICD it compiles to (empty = they agree)
  icd_overrides, components   what the ICD needs from the graph (``compile.overrides_for``)
  meta        job size, seconds (for the report; never shown as model names)

The old planner stays the default until the golden cases pass on both (PD-110).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aicad.graph import compile as gc
from aicad.graph import intent, questions, registry, resolve, validate
from aicad.graph.model import DesignGraph

ENV = "FW_DESIGN_GRAPH"


def enabled() -> bool:
    return os.environ.get(ENV, "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class OfficePlan:
    plan: dict[str, Any] | None
    narrative: str = ""
    cost_usd: float | None = None
    graph: DesignGraph | None = None
    questions: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    reply: dict[str, Any] | None = None   # the model's raw reply (reports and replay only; never shown)


def _fmt(v: Any) -> str:
    return f"{float(v):g}" if isinstance(v, int | float) and not isinstance(v, bool) else str(v)


def _q(q: Any) -> dict[str, Any]:
    return {"id": q.id, "question": q.question, "options": list(q.options), "default": q.default, "multi": q.multi,
            "other": True, "why": q.why}


async def plan(folder: Path | None, name: str, brief: str, notes: str = "", budget_usd: float | None = None,
               answers: dict[str, str] | None = None) -> OfficePlan:
    """Intent -> graph -> plan. Never raises: a failure comes back as ``error`` and the office falls back."""
    t0 = time.perf_counter()
    try:
        res = await intent.run(name, brief, notes=notes, answers=answers, budget_usd=budget_usd, cwd=folder)
    except Exception as e:  # noqa: BLE001  (provider failure: the office falls back to the standard breakdown)
        return OfficePlan(None, error=f"the intent step failed ({type(e).__name__})")
    from aicad.llm.routing import tier_of

    out = OfficePlan(None, cost_usd=res.cost_usd, reply=res.data,
                     meta={"job": res.job, "seconds": res.seconds, "tokens": res.tokens, "tier": tier_of(res.model)})
    if res.graph is None:
        out.error = res.error or "no design graph"
        return out
    return finish(out, res.graph, res.issues, time.perf_counter() - t0)


def finish(out: OfficePlan, g: DesignGraph, iss: list[dict[str, Any]], seconds: float | None = None) -> OfficePlan:
    errs = [i for i in iss if i["severity"] == "error"]
    out.graph = g
    if errs:
        out.error = "; ".join(i["text"] for i in errs[:3])
        return out
    p = gc.to_plan(g, resolved=True)
    skel, ifs = gc.to_icd(g, p)
    g2 = gc.read_layout(g, skel)
    chk = gc.check(g2, skel, ifs)
    lim = gc.limits(g2, skel, ifs)
    qs = [_q(q) for q in g.questions]
    p["graph"].update(data=g2.dump(), view=view(g2), questions=qs, check=chk, limits=lim,
                      meta={**{k: v for k, v in out.meta.items() if k in ("job", "seconds")},
                            **({"seconds_total": round(seconds, 2)} if seconds is not None else {})})
    out.plan, out.questions = p, qs
    out.narrative = narrative(g2, qs, chk)
    out.meta["check"] = chk
    return out


def narrative(g: DesignGraph, qs: list[dict[str, Any]], chk: list[str]) -> str:
    n_c, n_x = len(g.components), len(g.connections)
    t = (f"I read the brief as {n_c} part{'s' if n_c != 1 else ''} and {n_x} connection{'s' if n_x != 1 else ''}; "
         "sizes the brief doesn't give come from standards and are listed with their source.")
    if g.notes:
        t += " " + " ".join(g.notes)
    if qs:
        t += f" {len(qs)} question{'s' if len(qs) != 1 else ''} before you approve: the answer changes the design."
    if chk:
        t += " The layout does not match the design in places: " + "; ".join(chk[:3])
    return t


def attach(plan_: dict[str, Any], out: OfficePlan) -> dict[str, Any]:
    """Put the graph back on the plan after ``planner.finish`` (which keeps only the plan's own fields)."""
    if out.plan and out.plan.get("graph"):
        plan_["graph"] = out.plan["graph"]
    return plan_


def open_questions(plan_: dict[str, Any] | None) -> list[dict[str, Any]]:
    return list((((plan_ or {}).get("graph") or {}).get("questions")) or [])


def answer(doc: dict[str, Any], answers: dict[str, str]) -> tuple[OfficePlan | None, str | None]:
    """Apply answers to the program's graph. Code's questions (housing, bearings, material) are applied by code here
    (returns the new plan); any other answer needs the model again (returns None and the notes to plan with)."""
    gd = ((doc.get("plan") or {}).get("graph") or {}).get("data")
    if not gd:
        return None, None
    qs = {q["id"]: q for q in open_questions(doc.get("plan"))}
    ans = {k: str(v)[:200] for k, v in (answers or {}).items() if k in qs and str(v).strip()}
    if not ans:
        return None, None
    g = DesignGraph.load(gd)
    if not all(k in ("housing", "bearings") or k.startswith("material") for k in ans):
        notes = "Answers to your questions: " + "; ".join(f"{qs[k]['question']} {v}" for k, v in ans.items())
        return None, notes
    g.questions = [q for q in g.questions if q.id not in ans]
    g = questions.apply_answers(g, ans)
    g = validate.repair(g)
    g = resolve.resolve(g)
    g.questions = questions.ask(g, g.answers)
    out = OfficePlan(None, meta=dict(((doc.get("plan") or {}).get("graph") or {}).get("meta") or {}))
    return finish(out, g, validate.issues(g)), None


# ----------------------------------------------------------------------------- the plan review view
_HIDE = {"role", "stepped", "pressure_angle", "series"}
_LABEL = {"d": "Ø", "shoulder_d": "step Ø", "journal_d": "journal Ø", "length": "length", "module": "m",
          "teeth": "teeth", "face_width": "face", "bore": "bore Ø", "b": "b", "h": "h", "t1": "t1", "t2": "t2",
          "designation": "", "D": "D", "B": "B", "shaft_d": "for Ø", "d2": "groove Ø", "m": "groove", "s": "s",
          "style": "", "size": "M", "od": "Ø", "width": "width", "L": "L", "W": "W", "H": "H", "T": "T"}
SOURCE_WORD = {"brief": "from the brief", "answer": "your answer", "standard": "standard", "rule": "design rule",
               "assumed": "assumed", "layout": "laid out", "plan": "from the plan"}


_STYLE = {"hex_bolt": "hex bolt", "shcs": "socket head cap screw", "split": "split", "open": "open", "blind": "blind",
          "block": "block"}


def _param_text(k: str, v: Any) -> str:
    if k == "style":
        return _STYLE.get(str(v), str(v))
    lab = _LABEL.get(k, k)
    if k == "module":
        return f"m{_fmt(v)}"
    if lab == "M":
        return f"M{_fmt(v)}"
    if lab == "":
        return _fmt(v)
    if lab.endswith("Ø"):
        return f"{lab}{_fmt(v)}"
    return f"{lab} {_fmt(v)}"


def view(g: DesignGraph) -> dict[str, Any]:
    """Components and connections in plain engineering words (no ids, no internals)."""
    comps = []
    for c in g.components:
        ct = registry.COMPONENTS.get(c.kind)
        bits = []
        for k, p in c.params.items():
            if k in _HIDE or (c.kind == "key" and k in ("t1", "t2", "shaft_d")):
                continue
            bits.append({"text": _param_text(k, p.value), "source": SOURCE_WORD.get(p.source, p.source),
                         "note": p.note})
        std = ct.standard if ct and ct.family == "standard" else ""
        if c.kind == "fastener" and c.v("style") in ("hex_bolt", "shcs"):
            std = "ISO 4017" if c.v("style") == "hex_bolt" else "ISO 4762"
        comps.append({"name": c.name, "kind": ct.label if ct else c.kind, "qty": c.qty, "group": c.group,
                      "standard": std, "params": bits, "added": c.implied, "material": c.material})
    names = {c.id: c.name for c in g.components}
    conns = []
    for x in g.connections:
        kt = registry.CONNECTIONS.get(x.kind)
        h, gu = names.get(x.host, x.host), names.get(x.guest, x.guest)
        via = [names.get(v, v) for v in x.via]
        text = {"keyed_hub": f"{gu} keyed on {h}", "hub_fit": f"{gu} fitted on {h}",
                "shoulder_stop": f"{gu} against the shoulder of {h}", "bearing_journal": f"{gu} on {h}",
                "bearing_seat": f"{gu} in {h}", "gear_mesh": f"{h} meshes with {gu}",
                "bolted_joint": f"{gu} bolted to {h}", "ring_retained": f"{gu} held on {h}",
                "mounted_on": f"{gu} on {h}", "belt_drive": f"{h} belted to {gu}",
                "coupling": f"{h} coupled to {gu}"}.get(x.kind, f"{gu} with {h}")
        if via:
            text += f" ({', '.join(via)})"
        extra = []
        if x.kind == "gear_mesh" and x.v("centre_distance") is not None:
            extra.append(f"a = {_fmt(x.v('centre_distance'))} mm, ratio {_fmt(x.v('ratio'))}")
        if x.kind == "belt_drive" and x.v("centre_distance") is not None:
            extra.append(f"C = {_fmt(x.v('centre_distance'))} mm")
        if x.kind in ("keyed_hub", "hub_fit") and x.v("fit"):
            extra.append(f"fit {x.v('fit')}")
        if x.kind in ("bearing_journal", "bearing_seat") and x.v("count"):
            extra.append(f"{_fmt(x.v('count'))} per shaft")
        conns.append({"text": text, "kind": kt.label if kt else x.kind, "detail": ", ".join(extra),
                      "placement": kt.placement if kt else ""})
    return {"components": comps, "connections": conns, "notes": list(g.notes),
            "constraints": {"excluded": list(g.constraints.excluded), "exclusive": g.constraints.exclusive}}


# ----------------------------------------------------------------------------- the ICD hook
def icd_overrides(doc: dict[str, Any], parts: list[dict[str, Any]]) -> dict[str, Any] | None:
    return gc.overrides_for(doc.get("plan") or {}, parts)
