"""Clarifying questions (at most 3, in the fw-questions MCQ format) and how an answer changes the graph.

Code asks first, deterministically, about the ambiguities that change which parts exist or how they connect:

* ``housing``: shafts on bearings, and the brief neither names a housing nor rules one out;
* ``bearings``: the brief names bearings but no designation or series;
* ``material``: the brief hints at a material choice ("plastic", "light", "corrosion", "food" ...) without naming one.

The model's own questions (from the intent reply) fill the remaining places. Answers to code's questions are applied
by code (``apply_answers``: no second model call); an answer to one of the model's questions goes back to the model
with the brief. Sizes are never asked: standards size them.

``complete_housing`` is the deterministic completion of a housing the graph names: a cover, a bearing seat for every
shaft bearing, a bearing cap over each (open where the shaft leaves, blind on the other side), the cap screws and the
cover bolts, each part added only when the graph lacks one of its kind.
"""

from __future__ import annotations

import re

from aicad.graph.model import Component, Connection, DesignGraph, Param, Question

MAX = 3
HOUSING_NO = "No housing: the shafts with their bearings"
HOUSING_YES = "A split housing with bearing caps"
BEARINGS_62 = "Deep-groove ball bearings, 62xx (normal series)"
BEARINGS_60 = "Deep-groove ball bearings, 60xx (light series)"
MATERIALS = ("Steel C45", "Stainless 304", "Aluminium 6061-T6", "Acetal POM")
_MAT_HINT = re.compile(r"\b(?:plastic|metal|light(?:weight)?|corrosion|corrosive|food|outdoors?|marine|quiet|wash ?down)\b",
                       re.IGNORECASE)
_MAT_KINDS = [("spur_gear", re.compile(r"\bgears?\b|\bpinions?\b", re.IGNORECASE)), ("shaft", re.compile(r"\bshafts?\b", re.IGNORECASE)),
              ("housing", re.compile(r"\bhousing|casing", re.IGNORECASE))]
_HOUSING_WORDS = re.compile(r"\b(?:reducer|gear ?box|housing|casing|enclosed)\b", re.IGNORECASE)


def _named_material(brief: str) -> bool:
    from aicad.office.direct import _MATERIALS

    return any(rx.search(brief or "") for rx, _n in _MATERIALS)


def ask(g: DesignGraph, answers: dict[str, str] | None = None) -> list[Question]:
    answers = answers or {}
    out: list[Question] = []
    brief = g.brief or ""
    cons = g.constraints
    if (g.of_kind("shaft") and g.of_kind("bearing") and not g.of_kind("housing", "pillow_block") and "housing" not in cons.named
            and "housing" not in cons.excluded and not _HOUSING_WORDS.search(brief) and "housing" not in answers
            and not cons.exclusive):
        out.append(Question(id="housing", question="Should the shafts run in a housing?",
                            options=[HOUSING_NO, HOUSING_YES], default=HOUSING_NO,
                            why="A housing adds a base, a cover, a cap over each bearing and their screws."))
    if (g.of_kind("bearing") and "bearing" in cons.named and not re.search(r"\b6[02]\d\d\b|\b6[02]xx\b", brief, re.IGNORECASE)
            and "bearings" not in answers):
        out.append(Question(id="bearings", question="Which bearings?", options=[BEARINGS_62, BEARINGS_60],
                            default=BEARINGS_62, why="Each is sized to its journal from ISO 15."))
    if _MAT_HINT.search(brief) and not _named_material(brief) and not any(k.startswith("material") for k in answers):
        out.append(Question(id="material", question="Which material for the designed parts?", options=list(MATERIALS),
                            default=MATERIALS[0], why="It sets the material of every designed part."))
    for q in g.questions:  # the model's own questions, where they don't repeat one of ours
        if len(out) >= MAX:
            break
        if re.search(r"\bmaterial", q.question, re.IGNORECASE) and not any(x.id.startswith("material") for x in out):
            # a material question is answered by code: its id names what it applies to (gears, shafts, all)
            kind = next((k for k, rx in _MAT_KINDS if rx.search(q.question)), "")
            qid = f"material_{kind}" if kind else "material"
            if qid not in answers:
                out.append(Question(id=qid, question=q.question, options=q.options, default=q.default,
                                    why="It sets the material of " + (f"every {kind.replace('_', ' ')}" if kind
                                                                      else "every designed part") + "."))
            continue
        topic = q.id.lower()
        if q.id in answers or any(t in topic or topic in t for t in (x.id for x in out)) or \
                (re.search(r"housing", q.question, re.IGNORECASE) and "housing" in [x.id for x in out] + list(answers)) or \
                re.search(r"\b(?:size|diameter|length|module|teeth|width)\b", q.question, re.IGNORECASE):
            continue
        out.append(q)
    return out[:MAX]


def apply_answers(graph: DesignGraph, answers: dict[str, str]) -> DesignGraph:
    """Code's questions are answered by code. Answers to the model's questions only travel back to the model."""
    g = graph.model_copy(deep=True)
    g.answers.update(answers or {})
    a = answers or {}
    if "housing" in a:
        if a["housing"].lower().startswith("no"):
            if "housing" not in g.constraints.excluded:
                g.constraints.excluded.append("housing")
        else:
            g = complete_housing(g, add=True)
    if "bearings" in a:
        series = "60" if "60" in a["bearings"] else "62"
        for b in g.of_kind("bearing"):
            b.params["series"] = Param(value=series, source="answer")
            if b.params.get("designation") and b.params["designation"].source not in ("brief",):
                del b.params["designation"]
    for qid, ans in a.items():
        if not qid.startswith("material"):
            continue
        from aicad.graph import registry

        kind = qid.partition("_")[2]
        for c in g.components:
            ct = registry.COMPONENTS.get(c.kind)
            if ct and ct.family != "standard" and (not kind or c.kind == kind or (kind == "housing" and
                                                                                   c.kind == "cover")):
                c.material = ans[:60]
    if g.of_kind("housing"):
        g = complete_housing(g)
    return g


def _prefix(shaft: Component, n: int) -> str:
    m = re.match(r"\s*(.*?)\s*shaft\b", shaft.name, re.IGNORECASE)
    return (m.group(1) if m and m.group(1) else f"Shaft {n}").strip().capitalize()


def complete_housing(graph: DesignGraph, add: bool = False) -> DesignGraph:
    """Complete a housing the graph names (or add one when ``add``): see the module doc. Idempotent."""
    g = graph.model_copy(deep=True)
    shafts = g.of_kind("shaft")
    if not shafts:
        return g
    notes: list[str] = []
    housing = next(iter(g.of_kind("housing")), None)
    if housing is None:
        if not add:
            return g
        housing = Component(id=g.new_id("housing_base"), kind="housing", name="Housing base", group="Housing",
                            params={"style": Param(value="split", source="answer")}, implied=True)
        g.components.append(housing)
        notes.append("housing base")
    group = housing.group
    cover = next(iter(g.of_kind("cover")), None)
    if cover is None:
        cover = Component(id=g.new_id("housing_cover"), kind="cover", name="Housing cover", group=group, implied=True)
        g.components.append(cover)
        notes.append("cover")
    # one bearing line per shaft: the housing's walls take each shaft's own pair (the layout assigns bearings by
    # sub-assembly), so a bearing component shared by several shafts is split, one per shaft, renamed by shaft
    for br in list(g.of_kind("bearing")):
        js = [x for x in g.connections if x.kind == "bearing_journal" and x.guest == br.id]
        if len(js) < 2:
            continue
        base = br.name
        for k, x in enumerate(js):
            sh = g.comp(x.host)
            n = int(x.v("count", 2) or 2)
            label = f"{_prefix(sh, k + 1)} {base[:1].lower() + base[1:]}" if sh is not None else base
            if k == 0:
                br.name, br.qty, br.group = label, n, sh.group if sh is not None else br.group
                continue
            nb = br.model_copy(deep=True)
            nb.id, nb.name, nb.qty = g.new_id(label), label, n
            nb.group = sh.group if sh is not None else br.group
            g.components.append(nb)
            x.guest = nb.id
        notes.append("one bearing pair per shaft")
    # every shaft runs on two bearings, each in a seat of the housing
    for n, sh in enumerate(shafts, start=1):
        journals = [x for x in g.connections if x.kind == "bearing_journal" and x.host == sh.id]
        if not journals:
            br = Component(id=g.new_id(f"{sh.id}_bearing"), kind="bearing", name=f"{_prefix(sh, n)} bearing", qty=2,
                           group=sh.group, implied=True)
            g.components.append(br)
            g.connections.append(Connection(id=g.next_connection_id(), kind="bearing_journal", host=sh.id,
                                            guest=br.id, params={"count": Param(value=2, source="rule")}))
            notes.append(f"{br.name.lower()} x 2")
        for x in [x for x in g.connections if x.kind == "bearing_journal" and x.host == sh.id]:
            if not any(y.kind == "bearing_seat" and y.guest == x.guest for y in g.connections):
                g.connections.append(Connection(id=g.next_connection_id(), kind="bearing_seat", host=housing.id,
                                                guest=x.guest, params={"count": Param(value=x.v("count", 2), source="rule")}))
    caps = g.of_kind("bearing_cap")
    if not caps:
        for n, sh in enumerate(shafts, start=1):
            for style in ("open", "blind"):
                c = Component(id=g.new_id(f"{_prefix(sh, n)} {style} cap"), kind="bearing_cap",
                              name=f"{_prefix(sh, n)} {style} cap", group=group, implied=True,
                              params={"style": Param(value=style, source="rule")})
                g.components.append(c)
                caps.append(c)
        notes.append(f"{len(caps)} bearing caps")
    screws = next((c for c in g.of_kind("fastener") if any(x.kind == "bolted_joint" and c.id in x.via and
                                                           (g.comp(x.guest) or c).kind == "bearing_cap"
                                                           for x in g.connections)), None)
    if screws is None and not any(re.search(r"cap screw", c.name, re.IGNORECASE) for c in g.of_kind("fastener")):
        screws = Component(id=g.new_id("cap_screw"), kind="fastener", name="Cap screw M6x16", qty=4 * len(caps),
                           group=group, implied=True, params={"style": Param(value="shcs", source="rule"),
                                                              "size": Param(value=6, source="rule"),
                                                              "length": Param(value=16, source="rule")})
        g.components.append(screws)
        notes.append(f"{screws.qty} cap screws M6")
    elif screws is None:
        screws = next(c for c in g.of_kind("fastener") if re.search(r"cap screw", c.name, re.IGNORECASE))
    for c in caps:
        if not any(x.kind == "bolted_joint" and x.guest == c.id for x in g.connections):
            g.connections.append(Connection(id=g.next_connection_id(), kind="bolted_joint", host=housing.id,
                                            guest=c.id, via=[screws.id]))
    if not any(x.kind == "bolted_joint" and x.guest == cover.id for x in g.connections):
        bolts = next((c for c in g.of_kind("fastener") if c is not screws), None)
        if bolts is None:
            bolts = Component(id=g.new_id("cover_bolt"), kind="fastener", name="Cover bolt M8x30", qty=4, group=group,
                              implied=True, params={"style": Param(value="hex_bolt", source="rule"),
                                                    "size": Param(value=8, source="rule"),
                                                    "length": Param(value=30, source="rule")})
            g.components.append(bolts)
            notes.append("4 cover bolts M8")
        g.connections.append(Connection(id=g.next_connection_id(), kind="bolted_joint", host=housing.id,
                                        guest=cover.id, via=[bolts.id]))
    if notes:
        g.notes.append("Completed the housing: " + ", ".join(notes) + ".")
    return g
