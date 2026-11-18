"""Archie, the Chief Designer: a program brief -> a structured decomposition (sub-assemblies, parts with a family
and a complexity, standard parts for the Toolbox).

Two planners, one output schema:
- ``archie``: one planning turn of the design agent (no tools, no files). It must answer with a fenced
  ```fw-plan JSON block, which is parsed and validated here; anything malformed is rejected, never shown raw.
- ``standard``: a deterministic breakdown from product templates and keywords. No AI, instant, free, and the
  fallback whenever the agent's answer can't be used. The UI labels which planner produced a plan.

The user reviews and edits the plan at the brief approval gate before any ticket exists.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from aicad.office import roster
from aicad.office.estimates import clamp_complexity

MAX_SUBASSEMBLIES = 12
MAX_PARTS_PER_SUB = 30
MAX_PARTS = 120
MAX_QTY = 500

ARCHIE_INSTRUCTIONS = """You are Archie, the Chief Designer of a mechanical design office. You receive a program \
brief for a product or machine. You do not model CAD. You plan: break the product into sub-assemblies and parts so \
specialists can design the parts in parallel.

Rules:
- 2 to 8 sub-assemblies, each a physical group that is assembled as a unit. Every part belongs to one.
- Each part has a family: "machined" (prismatic, milled), "turned" (lathe, round), "gear" (gears, pulleys, \
sprockets), "sheet" (sheet metal), "plastic" (moulded or printed), or "standard" (bought-out: bolts, nuts, \
washers, bearings, dowels, standoffs, keys, motors). Standard parts are picked from the catalogue, not designed.
- complexity 1..5 for designed parts: 1 a plain plate or spacer, 2 a few features, 3 a typical part with pockets, \
holes and fillets, 4 many features or tight tolerances, 5 a complex casting-like or multi-setup part. Use 1 for \
standard parts.
- qty is how many identical parts the product needs.
- description: one or two sentences with the key sizes, material and interfaces you can infer. Say when a size is \
assumed.
- Keep names short and specific ("Output shaft", "Motor plate"). Plain engineering language.
- Optional, for the layout and the interfaces (ICD) that follow approval: "envelope": [L, W, H] in mm (a turned \
part or gear: [D, D, length]); "mounts_on": the name of the part it is fixed to; for gears "module" and "teeth". \
Leave them out when you can't infer them: the office assumes and marks the assumption.

Answer with a short paragraph, then exactly one fenced block:
```fw-plan
{"summary": "one sentence", "assumptions": ["..."],
 "subassemblies": [{"name": "...", "description": "...",
   "parts": [{"name": "...", "family": "machined", "complexity": 3, "qty": 1, "description": "..."}]}]}
```"""

_BLOCK = re.compile(r"```fw-plan\s*\n(.*?)\n?```", re.DOTALL)

_TOOLBOX_HINTS = [  # (regex on the part name/description, Toolbox component code)
    (r"\bbearing|\b6[02]0\d\b", "bearing"), (r"\bsocket head|cap screw|\bshcs\b", "shcs"),
    (r"\bbolt|\bscrew", "hex_bolt"), (r"\bnut\b|\bnuts\b", "hex_nut"), (r"\bwasher", "washer"),
    (r"\bdowel|\blocating pin", "dowel"), (r"\bstandoff|\bspacer", "standoff"),
]


def _s(v: Any, n: int) -> str:
    from aicad.agent.session import scrub

    t = " ".join(str(v or "").split())
    t = scrub(t)
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def toolbox_code(text: str) -> str | None:
    t = text.lower()
    for rx, code in _TOOLBOX_HINTS:
        if re.search(rx, t):
            return code
    return None


# --------------------------------------------------------------------------- validation (shared by both planners)
def normalise_plan(raw: Any, source: str) -> dict[str, Any] | None:
    """A validated plan or None. Ids are reassigned (s1.., p1..) so edits and tickets refer to stable keys."""
    if not isinstance(raw, dict):
        return None
    subs_in = raw.get("subassemblies")
    if not isinstance(subs_in, list) or not subs_in:
        return None
    subs: list[dict[str, Any]] = []
    n_parts = 0
    for s in subs_in[:MAX_SUBASSEMBLIES]:
        if not isinstance(s, dict) or not str(s.get("name") or "").strip():
            continue
        parts = []
        for p in (s.get("parts") or [])[:MAX_PARTS_PER_SUB]:
            if not isinstance(p, dict) or not str(p.get("name") or "").strip() or n_parts >= MAX_PARTS:
                continue
            fam = roster.normalise_family(p.get("family"))
            name, desc = _s(p["name"], 80), _s(p.get("description"), 400)
            try:
                qty = max(1, min(MAX_QTY, int(p.get("qty") or 1)))
            except (TypeError, ValueError):
                qty = 1
            tb = p.get("toolbox") if p.get("toolbox") in {c for _, c in _TOOLBOX_HINTS} else None
            n_parts += 1
            part = {"id": f"p{n_parts}", "name": name, "family": fam,
                    "complexity": 1 if fam == "standard" else clamp_complexity(p.get("complexity")),
                    "qty": qty, "description": desc,
                    "toolbox": (tb or toolbox_code(f"{name} {desc}")) if fam == "standard" else None}
            part.update(_layout_hints(p, fam))
            parts.append(part)
        if parts:
            subs.append({"id": f"s{len(subs) + 1}", "name": _s(s["name"], 80),
                         "description": _s(s.get("description"), 300), "parts": parts})
    if not subs:
        return None
    assumptions = [_s(a, 240) for a in (raw.get("assumptions") or []) if str(a or "").strip()][:10] \
        if isinstance(raw.get("assumptions"), list) else []
    return {"source": source, "summary": _s(raw.get("summary"), 400), "assumptions": assumptions,
            "subassemblies": subs}


def _layout_hints(p: dict[str, Any], fam: str) -> dict[str, Any]:
    """Archie's optional layout hints, validated (anything odd is dropped: the layout engine assumes instead)."""
    out: dict[str, Any] = {}
    if fam == "standard":
        return out
    env = p.get("envelope")
    if isinstance(env, list) and len(env) == 3:
        try:
            e = [float(x) for x in env]
            if all(0.5 <= x <= 5000 for x in e):
                out["envelope"] = e
        except (TypeError, ValueError):
            pass
    if isinstance(p.get("mounts_on"), str) and p["mounts_on"].strip():
        out["mounts_on"] = _s(p["mounts_on"], 80)
    if fam == "gear":
        try:
            if p.get("module") is not None and 0.3 <= float(p["module"]) <= 20:
                out["module"] = float(p["module"])
            if p.get("teeth") is not None and 8 <= int(p["teeth"]) <= 300:
                out["teeth"] = int(p["teeth"])
        except (TypeError, ValueError):
            pass
    return out


def parse_plan(text: str) -> dict[str, Any] | None:
    """The last valid ```fw-plan block in Archie's answer, validated; None when there is no usable block."""
    for m in reversed(list(_BLOCK.finditer(text or ""))):
        try:
            raw = json.loads(m.group(1))
        except ValueError:
            continue
        plan = normalise_plan(raw, "archie")
        if plan is not None:
            return plan
    return None


def narrative(text: str) -> str:
    """Archie's prose without the block (shown in plan review)."""
    return _s(_BLOCK.sub("", text or ""), 1200)


# --------------------------------------------------------------------------- the agent (mocked in tests)
async def run_agent(folder: Path, name: str, brief: str, notes: str = "",
                    budget_usd: float | None = None) -> tuple[str, float | None]:
    """One planning turn, no tools. Returns (assistant text, estimated cost in USD). Via the LLM provider (AGT-001)."""
    from aicad import llm

    prompt = f"Program: {name}\n\nBrief:\n{brief}"
    if notes.strip():
        prompt += f"\n\nThe engineering manager reviewed your previous plan and asks for these changes:\n{notes}"
    res = await llm.complete(llm.CallRequest(role="planner", system=ARCHIE_INSTRUCTIONS, prompt=prompt, max_turns=2,
                                             budget_usd=budget_usd, cwd=folder))
    return res.text, res.metering.cost_usd


# --------------------------------------------------------------------------- Archie on a change request (CD-012)
CR_MAX_TOKENS = 60
CR_INSTRUCTIONS = """You are Archie, the Chief Designer. A part designer asks to change an interface of the \
program (the ICD). A deterministic check has already confirmed the change fits inside the frozen envelopes and both \
parts can take it. Judge only whether the change is justified by the program brief and the reason given, and whether \
it risks the product (strength, fit, assembly). Answer with one short sentence, then exactly one fenced block:
```fw-cr-decision
{"decision": "accept" | "reject", "reason": "one short sentence"}
```"""
_CR_BLOCK = re.compile(r"```fw-cr-decision\s*\n(.*?)\n?```", re.DOTALL)


def cr_prompt(doc: dict[str, Any], c: dict[str, Any], why: str) -> str:
    vals = ", ".join(f"{k}: {c['before'].get(k)} -> {v}" for k, v in c["values"].items())
    return (f"Program: {doc['name']}\n\nBrief:\n{doc['brief'][:2000]}\n\nChange request {c['id']} on "
            f"{c['interface']} {c['interface_name']}: {vals}.\nReason given: {c['reason']}\n"
            f"Deterministic check: {why}")


def parse_cr_decision(text: str) -> dict[str, Any] | None:
    found = None
    for m in _CR_BLOCK.finditer(text or ""):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("decision") in ("accept", "reject"):
            found = {"decision": d["decision"], "reason": _s(d.get("reason"), 300)}
    if found is not None:
        found["note"] = _s(_CR_BLOCK.sub("", text or ""), 300)
    return found


async def run_cr_review(folder: Path, prompt: str, budget_usd: float | None = None) -> tuple[str, float | None]:
    """One text-only turn (same shape as the planning turn). Tests and simulated mode replace it."""
    from aicad import llm

    res = await llm.complete(llm.CallRequest(role="change_review", system=CR_INSTRUCTIONS, prompt=prompt,
                                             budget_usd=budget_usd, cwd=folder))
    return res.text, res.metering.cost_usd


# --------------------------------------------------------------------------- the deterministic planner
P = tuple  # (name, family, complexity, qty, description)

_TEMPLATES: list[tuple[tuple[str, ...], str, list[tuple[str, str, list[P]]]]] = [
    (("gearbox", "gear box", "reducer", "speed reducer", "transmission"), "gear reducer", [
        ("Housing", "The casing that carries the bearings, seals and mounting feet.", [
            ("Housing base", "machined", 4, 1, "Lower casing with bearing bores, mounting feet and an oil drain."),
            ("Housing cover", "machined", 3, 1, "Upper casing matching the base split line, with a breather boss."),
            ("Bearing cap", "turned", 2, 4, "Bolted cap that locates the outer bearing ring."),
            ("Cover bolt", "standard", 1, 8, "Hex bolts clamping the cover to the base.")]),
        ("Input stage", "The fast shaft with its pinion and bearings.", [
            ("Input shaft", "turned", 3, 1, "Stepped shaft with bearing seats and a keyed coupling end."),
            ("Pinion", "gear", 3, 1, "Spur pinion on the input shaft."),
            ("Input bearing", "standard", 1, 2, "Deep-groove ball bearings supporting the input shaft.")]),
        ("Output stage", "The slow shaft with its gear and bearings.", [
            ("Output shaft", "turned", 3, 1, "Stepped shaft with bearing seats, gear seat and a keyed output end."),
            ("Output gear", "gear", 3, 1, "Spur gear meshing with the pinion, keyed to the output shaft."),
            ("Output bearing", "standard", 1, 2, "Deep-groove ball bearings supporting the output shaft.")]),
    ]),
    (("conveyor", "belt conveyor", "roller conveyor"), "conveyor", [
        ("Frame", "Side rails, cross members and legs.", [
            ("Side rail", "sheet", 3, 2, "Formed side channel carrying the roller axles."),
            ("Cross member", "machined", 2, 3, "Tie bar between the side rails."),
            ("Leg", "machined", 2, 4, "Support leg with an adjustable foot pad."),
            ("Frame bolt", "standard", 1, 24, "Hex bolts joining rails, cross members and legs.")]),
        ("Drive end", "The driven pulley, motor mount and bearings.", [
            ("Drive pulley", "turned", 3, 1, "Crowned drum pulley with a keyed shaft bore."),
            ("Drive shaft", "turned", 3, 1, "Shaft carrying the drive pulley, keyed at the motor end."),
            ("Motor plate", "machined", 3, 1, "Plate locating the gear motor on the frame."),
            ("Shaft bearing", "standard", 1, 2, "Bearings supporting the drive shaft.")]),
        ("Idler end", "The tail pulley and belt tensioner.", [
            ("Idler pulley", "turned", 2, 1, "Plain drum pulley on a fixed axle."),
            ("Tensioner block", "machined", 2, 2, "Slotted block with a take-up screw for belt tension.")]),
        ("Carry rollers", "Rollers supporting the belt between the ends.", [
            ("Carry roller", "turned", 2, 6, "Tube roller with pressed-in bearing ends."),
            ("Roller bearing", "standard", 1, 12, "Bearings at both ends of each roller.")]),
    ]),
    (("gripper", "robot arm", "end effector", "end-effector", "manipulator"), "gripper", [
        ("Base and wrist mount", "Interface to the robot flange and the actuator housing.", [
            ("Mounting flange", "turned", 2, 1, "Adapter to the robot's tool flange bolt pattern."),
            ("Actuator housing", "machined", 4, 1, "Body carrying the actuator and the jaw guides."),
            ("Mounting screw", "standard", 1, 4, "Socket head cap screws to the robot flange.")]),
        ("Jaw mechanism", "The jaws, guides and linkage that open and close.", [
            ("Jaw", "machined", 3, 2, "Jaw with replaceable finger seats."),
            ("Guide rail", "machined", 2, 2, "Linear guide for the jaws."),
            ("Link", "machined", 2, 2, "Linkage from the actuator to the jaws."),
            ("Pivot pin", "standard", 1, 4, "Dowel pins at the link pivots.")]),
        ("Fingers", "Part-specific contact fingers.", [
            ("Finger", "plastic", 2, 2, "Contoured finger pad matching the gripped part.")]),
    ]),
    (("enclosure", "housing", "electronics box"), "enclosure", [
        ("Body", "The main shell and its internal mounting features.", [
            ("Enclosure base", "plastic", 4, 1, "Shell with bosses, ribs and a gasket groove."),
            ("Mounting plate", "machined", 2, 1, "Internal plate carrying the electronics.")]),
        ("Lid", "The cover, seal and closing hardware.", [
            ("Enclosure lid", "plastic", 3, 1, "Cover matching the base, with a seal lip."),
            ("Lid screw", "standard", 1, 4, "Screws closing the lid into the base bosses."),
            ("Standoff", "standard", 1, 4, "Standoffs under the mounting plate.")]),
    ]),
    (("fixture", "jig", "clamp", "workholding"), "fixture", [
        ("Base", "The fixture plate and its locating features.", [
            ("Fixture plate", "machined", 3, 1, "Base plate with tapped grid and machine-table slots."),
            ("Locator", "turned", 2, 2, "Locating pins and rest buttons setting the part datum."),
            ("Locating dowel", "standard", 1, 2, "Dowel pins locating the fixture on the table.")]),
        ("Clamping", "Clamps that hold the part against the locators.", [
            ("Clamp arm", "machined", 3, 2, "Swing clamp arm with a contact pad."),
            ("Clamp bracket", "machined", 2, 2, "Bracket carrying the clamp pivot."),
            ("Clamp screw", "standard", 1, 4, "Screws for the clamp brackets.")]),
    ]),
    (("linear stage", "actuator", "slide", "axis", "lead screw", "ball screw"), "linear axis", [
        ("Base", "The base plate, rails and end blocks.", [
            ("Base plate", "machined", 3, 1, "Plate carrying the rails and end blocks."),
            ("End block", "machined", 3, 2, "Bearing blocks supporting the screw ends."),
            ("End bearing", "standard", 1, 2, "Bearings in the end blocks.")]),
        ("Carriage", "The moving table and its nut housing.", [
            ("Carriage plate", "machined", 3, 1, "Moving table with a tapped mounting pattern."),
            ("Nut housing", "machined", 3, 1, "Housing for the screw nut, bolted under the carriage.")]),
        ("Drive", "The screw, coupling and motor mount.", [
            ("Lead screw", "turned", 3, 1, "Screw with machined bearing journals."),
            ("Motor mount", "machined", 3, 1, "Bracket locating the motor on the base plate."),
            ("Mount screw", "standard", 1, 8, "Screws for the motor mount and end blocks.")]),
    ]),
]

_GENERIC: list[tuple[str, str, list[P]]] = [
    ("Frame", "The structure that carries everything else.", [
        ("Base plate", "machined", 3, 1, "Main plate with the mounting pattern."),
        ("Support bracket", "machined", 2, 2, "Bracket tying the base to the moving parts."),
        ("Frame bolt", "standard", 1, 8, "Bolts joining the frame members.")]),
    ("Mechanism", "The parts that move or transmit load.", [
        ("Main shaft", "turned", 3, 1, "Stepped shaft with bearing seats."),
        ("Bearing housing", "machined", 3, 1, "Housing carrying the shaft bearings."),
        ("Shaft bearing", "standard", 1, 2, "Bearings supporting the main shaft.")]),
    ("Covers", "Guards and covers.", [
        ("Cover", "sheet", 2, 1, "Formed guard over the mechanism.")]),
]


def standard_plan(name: str, brief: str) -> dict[str, Any]:
    """Deterministic decomposition: the best-matching product template, adjusted by keywords in the brief."""
    t = f"{name} {brief}".lower()
    best, kind, subs = 0, "", _GENERIC
    for keys, label, tpl in _TEMPLATES:
        score = sum(len(k) for k in keys if re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", t))
        if score > best:
            best, kind, subs = score, label, tpl
    bump = 1 if re.search(r"precision|tight toleranc|\bh7\b|\bh6\b|ground|lapped", t) else 0
    plastic = bool(re.search(r"\bplastic|moulded|molded|\babs\b|nylon|3d[- ]?print", t))
    sheet = bool(re.search(r"sheet metal|sheet-metal|\bbent\b|folded", t))
    raw_subs = []
    for sname, sdesc, parts in subs:
        rp = []
        for pname, fam, cx, qty, desc in parts:
            if fam == "sheet" and plastic and not sheet:
                fam = "plastic"
            if fam == "plastic" and sheet and not plastic:
                fam = "sheet"
            rp.append({"name": pname, "family": fam, "complexity": cx + (bump if fam != "standard" else 0),
                       "qty": qty, "description": desc})
        raw_subs.append({"name": sname, "description": sdesc, "parts": rp})
    if re.search(r"\bmotor\b|nema|servo|stepper", t) and not any("motor" in p["name"].lower()
                                                                 for s in raw_subs for p in s["parts"]):
        raw_subs[0]["parts"].append({"name": "Motor mount", "family": "machined", "complexity": 3, "qty": 1,
                                     "description": "Bracket locating the motor and its pilot."})
    summary = (f"Standard breakdown for a {kind}: {len(raw_subs)} sub-assemblies." if kind else
               f"General breakdown into {len(raw_subs)} sub-assemblies: no product template matched the brief, so "
               "review it closely.")
    assumptions = [("Sizes, materials and interfaces come from the brief; anything not stated is for the part "
                   "designer to confirm."), "Standard parts are taken from the Toolbox."]
    if bump:
        assumptions.append("The brief asks for precision, so designed parts are one complexity step higher.")
    plan = normalise_plan({"summary": summary, "assumptions": assumptions, "subassemblies": raw_subs}, "standard")
    assert plan is not None
    return plan
