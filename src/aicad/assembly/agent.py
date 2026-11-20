"""The assembly agent: one turn of the conversation, and the typed tools it acts through (WORKLIST 51).

A turn: the engineer's words + the conversation so far + the live assembly state go to one model call (role
``assembly_agent``, routed by ``chat.job_of``: Sonnet for simple turns, Opus for multi-step ones), which answers with
what to say, typed actions and at most two clickable questions (``chat.REPLY_SCHEMA``). The actions run here, in
order, each one deterministic:

  find      search the assembly, the workspace parts and the Toolbox (Hex)
  bring     insert a Toolbox component (sized from the part it is for) or a workspace part, unplaced
  make      a direct part (shaft, spur gear, spacer: ``makers``, no AI geometry, built through the normal check gate)
            or a Design Studio design-agent turn for anything else (a background job; inserted when verified)
  mate      one part on another the intended way: a shaft line is placed again by construction (``trains`` +
            ``fixings``: hubs against shoulders, keys in keyseats, circlips in grooves, bearings on journals, gear
            meshes at m(z1+z2)/2); plates by their hole patterns (``fitz.mount``); else coaxial
  assemble  the same over the given parts or everything, with questions instead of guesses when it is ambiguous
  check     exact interference and clearance, the motion range check, the visual check (advisory)
  move / remove / replace / resize   edits; a resize changes the part's own parameters and keeps its mates
  explain   the state in plain words, written by code

What the engineer reads after a turn is written by code from what happened (steps, the solver's mate status, unplaced
parts, the clash check), never the model's own claims. Instance ids stay the same when a part is placed again, so
the conversation's references ("that shaft", "the gear I just made") keep pointing at the same parts.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from aicad import toolbox
from aicad.assembly import (
    AssemblyInputError,
    chat,
    fitz,
    librarian,
    locks,
    makers,
    service,
    splines,
    store,
    trains,
    xform,
)

log = logging.getLogger(__name__)
MAX_QTY = 16
LINE_ROLES = ("gear", "hub", "bearing", "key", "ring")   # what a shaft line places by construction


class Ambiguous(Exception):
    """A reference or a request that could mean more than one thing: ask, don't guess."""

    def __init__(self, question: str, options: list[str]) -> None:
        super().__init__(question)
        self.question = {"id": "q1", "question": question, "options": options[:5], "default": None, "multi": False,
                         "other": True}


class ToolError(Exception):
    """An action that can't run as asked (a plain sentence for the engineer)."""


class Pending(Exception):
    """An action refers to a part that is still being designed in this turn (``$label`` of a design job): it runs
    when that part comes into the assembly."""

    def __init__(self, label: str) -> None:
        super().__init__(label)
        self.label = label


# ----------------------------------------------------------------------------- what the agent needs from the platform
class Env(ABC):
    """The platform side of a turn (the router implements it; tests use the real one through the API)."""

    org_id: str
    user_name: str | None = None

    @abstractmethod
    async def project_part(self, project_id: str) -> str:
        """The assembly part key of a workspace part's latest verified build."""

    @abstractmethod
    def candidates(self) -> list[dict[str, Any]]:
        """Workspace parts that can be brought in: [{id, name, description, sig}]."""

    @abstractmethod
    async def make_part(self, name: str, source: str, note: str) -> str:
        """Create a new workspace part from a model script, build it through the check gate; its project id."""

    @abstractmethod
    async def set_params(self, project_id: str, values: dict[str, float]) -> dict[str, Any]:
        """Edit a workspace part's parameters (rebuilt and checked); {changed, revision}."""

    @abstractmethod
    async def design_part(self, name: str, brief: str) -> str:
        """Start a Design Studio design-agent turn on a new part; its project id."""

    @abstractmethod
    async def watch_design(self, project_id: str, on_step: Callable[[str], None],
                           on_questions: Callable[[list[dict[str, Any]]], None] | None = None) -> bool:
        """Wait for that design turn to finish; whether the part is verified. Questions the design agent asks are
        handed to ``on_questions`` (relayed into the assembly chat)."""

    async def answer_design(self, project_id: str, text: str) -> None:
        """Send the engineer's answer to that design session (it continues the design)."""
        raise ToolError("The design agent can't be reached from here.")

    def build_state(self, project_id: str) -> dict[str, Any]:
        """The part's latest build: {geometry: a built STEP exists, verified, accepted: {by, open} or None, open:
        [{id, name}] the gating checks that failed}."""
        return {"geometry": False, "verified": False, "accepted": None, "open": []}

    async def look(self, root: Path, doc: dict[str, Any]) -> dict[str, Any] | None:
        """The visual check (advisory); None when it isn't available."""
        return None

    def context(self, doc: dict[str, Any]) -> str:
        """Project context and design memory for the model (DS-040)."""
        return ""

    @abstractmethod
    async def model(self, system: str, prompt: str, job: str, schema: dict[str, Any]
                    ) -> tuple[Any, int, str | None]:
        """One model call: (validated JSON or None, platform tokens charged, error)."""


@dataclass
class Turn:
    root: Path
    aid: str
    env: Env
    labels: dict[str, list[str]] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)
    on_step: Callable[[str], None] = lambda s: None
    jobs: list[dict[str, Any]] = field(default_factory=list)
    pending: dict[str, dict[str, Any]] = field(default_factory=dict)   # $label -> the design job making that part
    deferred: list[dict[str, Any]] = field(default_factory=list)       # actions waiting for a design job's part
    tid: str = ""                                                      # this turn's id (labels outlive the turn)


# ----------------------------------------------------------------------------- references
_ROLE_WORDS = {"shaft": ("shaft", "axle", "spindle"), "gear": ("gear", "pinion", "wheel"), "bearing": ("bearing",),
               "key": ("key",), "ring": ("circlip", "ring", "seeger"), "hub": ("pulley", "hub", "sprocket"),
               "spacer": ("spacer", "sleeve", "collar"), "fastener": ("bolt", "screw"), "plate": ("plate",),
               "bracket": ("bracket",)}


def _num_id(iid: str) -> int:
    m = re.search(r"\d+", iid)
    return int(m.group()) if m else 0


def _centre(root: Path, doc: dict[str, Any], iid: str) -> np.ndarray:
    inst = service._inst(doc, iid)
    p = store.part(root, inst["part"]) or {}
    return xform.pt(xform.from12(inst["T"]), (p.get("info") or {}).get("center") or (0, 0, 0))


def resolve(t: Turn, doc: dict[str, Any], ref: Any, want: int | None = 1) -> list[str]:
    """Instance ids for a reference: an id, a ``$label`` of this turn, a list, or a short name ("the gear", "the
    left bearing", "the gear I just made"). Several equally good matches when one is wanted: Ambiguous."""
    if ref is None or ref == "":
        return []
    if isinstance(ref, list):
        out: list[str] = []
        for r in ref:
            out += [x for x in resolve(t, doc, r, None) if x not in out]
        return out
    s = str(ref).strip()
    ids = {i["id"] for i in doc["instances"] if not i.get("group")}
    if s in ids:
        return [s]
    if s.startswith("$"):
        if s in t.pending and not t.labels.get(s):
            raise Pending(s)
        got = [x for x in t.labels.get(s, []) if x in ids]
        if not got:
            raise ToolError(f"I lost track of {s.lstrip('$')}: it is not in the assembly.")
        return got
    low = s.lower()
    names = service.human_names(doc)
    words = [w for w in librarian._tok(low) if w not in librarian.GENERIC and w not in
             ("left", "right", "upper", "lower", "top", "bottom", "first", "second", "other", "just", "last", "new",
              "latest", "made", "brought", "one")]
    role = next((r for r, ws in _ROLE_WORDS.items() if any(re.search(rf"\b{w}s?\b", low) for w in ws)), None)
    scored = []
    for iid in ids:
        nm = names[iid].lower()
        toks = set(librarian._tok(nm))
        score = sum(1 for w in words if w in toks) / max(1, len(words))
        if role is not None and chat.role_of(t.root, doc, iid) == role:
            score = max(score, 0.6) + 0.3
        if score > 0.45:
            scored.append((score, iid))
    if not scored:
        raise ToolError(f"There is no {s} in the assembly.")
    top = max(x[0] for x in scored)
    best = sorted([iid for sc, iid in scored if sc >= top - 1e-9], key=_num_id)
    if len(best) == 1 or want is None and not re.search(r"\b(left|right|first|second|last|just|new|latest)\b", low):
        return best if want is None else best[:1]
    if re.search(r"\b(just|last|latest|new|recent)\b", low):
        return best[-1:]
    if re.search(r"\b(left|right|upper|lower|top|bottom)\b", low):
        ax = 2 if re.search(r"\b(upper|lower|top|bottom)\b", low) else 0
        pick = max if re.search(r"\b(right|upper|top)\b", low) else min
        return [pick(best, key=lambda i: float(_centre(t.root, doc, i)[ax]))]
    if re.search(r"\bfirst\b", low):
        return best[:1]
    if re.search(r"\bsecond\b", low) and len(best) > 1:
        return best[1:2]
    raise Ambiguous(f"Which {s.removeprefix('the ').strip()} do you mean?", [names[i] for i in best])


def one(t: Turn, doc: dict[str, Any], ref: Any, what: str) -> str:
    got = resolve(t, doc, ref, 1)
    if not got:
        raise ToolError(f"Say which part to {what}.")
    return got[0]


# ----------------------------------------------------------------------------- the doc, under its lock
class DocEdit:
    """``async with DocEdit(turn) as doc:`` load the assembly, change it, solve and save (the lock is shared with
    the Assembly Studio routes and the Design Office)."""

    def __init__(self, t: Turn, solve: bool = True) -> None:
        self.t, self.solve, self.doc = t, solve, None

    async def __aenter__(self) -> dict[str, Any]:
        self.lk = locks.lock(self.t.aid)
        await self.lk.acquire()
        doc = store.load(self.t.root, self.t.aid)
        if doc is None:
            self.lk.release()
            raise ToolError("The assembly was deleted.")
        self.doc = doc
        return doc

    async def __aexit__(self, et: object, ev: object, tb: object) -> None:
        try:
            if et is None and self.doc is not None:
                if self.solve and self.doc["instances"]:
                    service.run_solve(self.t.root, self.doc)
                store.save(self.t.root, self.doc)
        finally:
            self.lk.release()


def _step(label: str, lines: list[str], status: str = "ok", parts: list[str] | None = None, **kw: Any) -> dict[str, Any]:
    return {"label": label, "status": status, "lines": [chat.scrub(x) for x in lines if x], "parts": parts or [], **kw}


def _g(x: float) -> str:
    return f"{round(float(x), 3):g}"


def shaft_geo(root: Path, doc: dict[str, Any], iid: str) -> dict[str, Any] | None:
    try:
        return trains.shaft_geom(root, service._inst(doc, iid)["part"])
    except Exception:
        log.warning("shaft geometry failed", exc_info=True)
        return None


# ----------------------------------------------------------------------------- find
async def t_find(t: Turn, a: dict[str, Any]) -> dict[str, Any]:
    q = str(a.get("query") or a.get("text") or "").strip()
    if not q:
        raise ToolError("Say what to look for.")
    doc = store.load(t.root, t.aid) or {"instances": []}
    names = service.human_names(doc) if doc.get("instances") else {}
    toks = set(librarian._tok(q)) - librarian.GENERIC
    lines, matches = [], []
    inside = [i["id"] for i in doc["instances"] if not i.get("group") and toks & set(librarian._tok(i["name"]))]
    if inside:
        lines.append("In the assembly: " + ", ".join(names[i] for i in inside[:6]))
        matches += [{"kind": "instance", "id": i, "name": names[i]} for i in inside[:6]]
    hits = librarian.find_parts(q, t.env.candidates(), limit=4)
    if hits:
        lines.append("Your parts: " + ", ".join(f"{h['name']}" for h in hits))
        matches += [{"kind": "part", "id": h["id"], "name": h["name"], "score": h["score"]} for h in hits]
    tb = librarian.read_toolbox(q)
    if tb:
        lines.append(f"Toolbox: {tb['title'] if tb.get('params') else tb['name']} ({tb['standard']})")
        matches.append({"kind": "toolbox", "code": tb["code"], "params": tb.get("params"), "name": tb["title"]})
    else:
        for m in toolbox.match(q)[:2]:
            lines.append(f"Toolbox: {m['name']} ({m['standard']})")
            matches.append({"kind": "toolbox", "code": m["code"], "params": m.get("params"), "name": m["name"]})
    if not lines:
        lines.append(f"Nothing called {q} in the assembly, your parts or the Toolbox. I can make it.")
    return _step(f"Looked for {q}", lines, "ok" if matches else "info", parts=inside, matches=matches)


# ----------------------------------------------------------------------------- bring
async def t_bring(t: Turn, a: dict[str, Any]) -> dict[str, Any]:
    qty = max(1, min(MAX_QTY, int(a.get("qty") or 1)))
    doc = store.load(t.root, t.aid)
    if doc is None:
        raise ToolError("The assembly was deleted.")
    host = one(t, doc, a["for"], "size it from") if a.get("for") else None
    hgeo = shaft_geo(t.root, doc, host) if host and chat.role_of(t.root, doc, host) == "shaft" else None
    notes: list[str] = []
    if a.get("part"):
        cands = t.env.candidates()
        ref = str(a["part"])
        hit = next((c for c in cands if c["id"] == ref), None)
        if hit is None:
            fp = librarian.find_parts(ref, cands, limit=2)
            if not fp or fp[0]["score"] < 0.5:
                raise ToolError(f"I couldn't find {ref} among your built parts.")
            if len(fp) > 1 and fp[1]["score"] >= fp[0]["score"] - 1e-9:
                raise Ambiguous(f"Which {ref} do you mean?", [h["name"] for h in fp])
            hit = next(c for c in cands if c["id"] == fp[0]["id"])
        key = await t.env.project_part(hit["id"])
        title, src = service.clean_name(hit["name"]), "your parts"
        bs = t.env.build_state(hit["id"])
        if bs.get("geometry") and not bs.get("verified"):
            notes.append(unverified_note(bs))
    else:
        code = a.get("code")
        params = dict(a.get("params") or {})
        if not code and a.get("text"):
            tb = librarian.read_toolbox(str(a["text"]))
            if not tb:
                raise ToolError(f"I couldn't read {a['text']} as a Toolbox component.")
            code, params = tb["code"], dict(tb.get("params") or {})
        if code not in toolbox.COMPONENTS:
            raise ToolError("That isn't a Toolbox component.")
        try:
            params, notes = makers.size_for_host(str(code), params, hgeo)
        except toolbox.ToolboxError as e:
            raise ToolError(str(e)) from None
        if code == "spur_gear" and host and hgeo and not trains.gear_bore_ok(float(params["M"]), int(params["Z"]),
                                                                            float(params["BORE"])):
            raise ToolError(f"An m{_g(params['M'])} z{int(params['Z'])} gear is too small for a Ø{_g(params['BORE'])} "
                            "bore: pick more teeth or a larger module.")
        key = await service.ensure_toolbox_part(t.root, t.env.org_id, str(code), params)
        title, src = toolbox.spec(str(code)).title(params), "the Toolbox"
    async with DocEdit(t) as doc:
        ids = [service.add_instance(t.root, doc, key)["id"] for _ in range(qty)]
        names = service.human_names(doc)
    if a.get("as"):
        t.labels[str(a["as"])] = ids
    lines = [f"From {src}" + (", sized for " + names.get(host, "the shaft") + ": " + "; ".join(notes)
                              if notes and host else "")]
    if notes and not host:
        lines += notes
    lines.append("The base part, fixed at the origin." if len(doc["instances"]) == len(ids) else
                 "Unplaced until it is mated." if qty == 1 else "Unplaced until they are mated.")
    return _step(f"Brought {qty} × {title}" if qty > 1 else f"Brought {title}", lines, "ok", parts=ids)


# ----------------------------------------------------------------------------- make
async def t_make(t: Turn, a: dict[str, Any]) -> dict[str, Any]:
    kind = str(a.get("kind") or "other")
    spec = {k: v for k, v in dict(a.get("spec") or {}).items() if v is not None}
    doc = store.load(t.root, t.aid)
    if doc is None:
        raise ToolError("The assembly was deleted.")
    host_job = t.pending.get(str(a.get("for"))) if str(a.get("for") or "").startswith("$") and \
        not t.labels.get(str(a.get("for"))) else None
    if host_job is not None and kind in ("shaft", "gear", "spacer"):
        raise Pending(str(a["for"]))      # sized from the host's real geometry once it is in the assembly
    host = one(t, doc, a["for"], "make it for") if a.get("for") and host_job is None else None
    notes: list[str] = []
    ext = splines.of(t.root, service._inst(doc, host)["part"], "external") if host else []
    if kind == "gear" and host and ext:   # interface first: the hub spline is the shaft's spline
        e = max(ext, key=lambda x: x["z1"] - x["z0"])
        spec["spline"] = {k: e[k] for k in ("n", "d", "D", "b")}
        spec["bore_src"] = "the shaft's spline minor Ø"
        notes.append(f"hub spline {splines.spec_text(e)} = the shaft's spline (ISO 14)")
        if not spec.get("face_width"):
            m_ = float(spec.get("module") or 2)
            spec["face_width"] = min(10 * m_, e["z1"] - e["z0"])
            spec["face_width_src"] = "10 × module, at most the splined length"
    elif kind == "gear" and host and chat.role_of(t.root, doc, host) == "shaft":
        hg = shaft_geo(t.root, doc, host)
        if hg:
            prm, notes = makers.size_for_host("spur_gear", {"M": spec.get("module", 2), "Z": spec.get("teeth", 24),
                                                            **({"BORE": spec["bore"]} if spec.get("bore") else {}),
                                                            **({"B": spec["face_width"]} if spec.get("face_width") else {})},
                                              hg)
            spec.setdefault("bore", prm["BORE"])
            spec["bore_src"] = "the shaft's seat"
            if not spec.get("face_width"):
                spec["face_width"], spec["face_width_src"] = prm["B"], "covers the shaft's key"
            spec.setdefault("keyway", bool(prm.get("KEY_B")))
    if kind == "spacer" and a.get("between"):
        spec.update(_spacer_between(t, doc, a["between"]))
    if kind in ("shaft", "gear", "spacer"):
        try:
            lay, source = makers.make(kind, {**spec, "name": a.get("name") or spec.get("name")})
        except makers.MakeError as e:
            raise ToolError(str(e)) from None
        name = lay["name"]
        t.on_step(f"Building {name}")
        pid = await t.env.make_part(name, source, f"Made **{name}** in Assembly Studio (no AI geometry)")
        key = await t.env.project_part(pid)
        placed = None
        async with DocEdit(t) as doc:
            iid = service.add_instance(t.root, doc, key)["id"]
            if spec.get("_place"):
                placed = _place_spacer(t, doc, iid, spec["_place"])
        if a.get("as"):
            t.labels[str(a["as"])] = [iid]
        if host and lay.get("spline") and kind == "gear":
            t.on_step(f"Putting {name} on its shaft")
            async with DocEdit(t) as doc:
                ins = splines.of(t.root, service._inst(doc, iid)["part"], "internal")
                e = splines.of(t.root, service._inst(doc, host)["part"], "external")
                if ins and e:
                    placed = "; ".join(splines.place(t.root, doc, iid, host, ins[0], e[0]))
                    service.run_solve(t.root, doc)
                    _ok, fl = splines.check(t.root, doc, iid, host, ins[0], e[0])
                    notes.append(fl[0])
        lines = [(f"Made {name} as a new part in your workspace: built from its dimensions (no AI geometry) and "
                 "passed the part checks")]
        asm = makers.assumed(lay)
        if asm:
            lines.append("Assumed: " + "; ".join(asm))
        if notes:
            lines.append("From the shaft: " + "; ".join(notes))
        lines.append(placed or ("The base part, fixed at the origin." if len(doc["instances"]) == 1 else
                                "Unplaced until it is mated."))
        return _step(f"Made {name}", lines, "ok", parts=[iid], project_id=pid)
    brief = str(a.get("brief") or "").strip()
    name = str(a.get("name") or "New part").strip()[:80]
    if len(brief) < 12:
        raise ToolError("Describe the part with its sizes so the design agent can make it.")
    brief += "\n\n" + assembly_brief(t, doc, host, host_job)
    pid = await t.env.design_part(name, brief)
    label = str(a.get("as") or f"$job{len(t.jobs) + 1}")
    job = {"id": f"j{time.time_ns() // 1000 % 10_000_000_000}", "kind": "design", "name": name, "project_id": pid,
           "status": "running", "step": "Starting the design agent", "started_at": store.now(), "for": host,
           "as": label, "turn": t.tid, "brief": brief[:1500]}
    t.jobs.append(job)
    t.pending[label] = job
    if host_job is not None:     # both parts are being designed now: mate them when both are in
        t.deferred.append({"action": {"do": "mate", "part": label, "to": str(a["for"]), "how": "auto"},
                           "needs": [label, str(a["for"])]})
    return _step(f"Designing {name}", [(f"The design agent is designing {name} now, in parallel; I relay its progress "
                                        "and any question here, and bring it in and mate it when it is built.")],
                 "info", project_id=pid, job=job["id"])


def assembly_brief(t: Turn, doc: dict[str, Any], host: str | None, host_job: dict[str, Any] | None) -> str:
    """What the design agent is told about an assembly-initiated part: decide from the context, interface first,
    and leave the fit with the mating part to the assembly."""
    names = service.human_names(doc)
    out = [f"[Assembly Studio build] This part goes into the assembly \"{service.clean_name(doc['name'])}\"."]
    if host:
        out.append(f"It mates with {names[host]}.")
        ext = splines.of(t.root, service._inst(doc, host)["part"], "external")
        if ext:
            e = ext[0]
            out.append(f"That shaft's spline: {splines.spec_text(e)} (n × minor Ø × major Ø × width, ISO 14), "
                       f"{e['z1'] - e['z0']:g} mm long: make the hub with fw.spline_bore using exactly these sizes.")
        else:
            sg = shaft_geo(t.root, doc, host) if chat.role_of(t.root, doc, host) == "shaft" else None
            if sg:
                out.append("That shaft's seats: " + ", ".join(f"Ø{_g(x['d'])} × {_g(x['length'])}"
                                                            for x in sorted(sg["seats"], key=lambda x: x["lo"])))
    if host_job is not None:
        out.append(f"It mates with {host_job['name']}, which is being designed at the same time from this brief:\n"
                   f"\"\"\"{host_job.get('brief', '')[:900]}\"\"\"\nUse the same interface sizes (for a spline: "
                   "the same fw.iso14 row, fw.spline_shaft on the shaft and fw.spline_bore in the hub).")
    out.append("The engineer is working in Assembly Studio, not in the Design Studio: do not ask questions unless the "
               "part can't be made at all. Decide reasonable values from this context and standard practice, build, "
               "and state each assumption in your summary. The fit with the mating part is checked in the assembly "
               "where both parts are: it is never an open item of this part's own checks or self-review.")
    return "\n".join(out)


def _spacer_between(t: Turn, doc: dict[str, Any], refs: Any) -> dict[str, Any]:
    """Bore and length of a spacer between two parts on one shaft: the gap between their facing faces along the
    shaft axis, the bore of the seat there."""
    ids = resolve(t, doc, refs, None)
    if len(ids) != 2:
        raise ToolError("Name the two parts the spacer sits between.")
    shaft = next((s for s in _shafts_of(t.root, doc, ids[0]) if s in _shafts_of(t.root, doc, ids[1])), None)
    if shaft is None:
        raise ToolError("Those two parts are not on one shaft yet: put them on it first.")
    sg = shaft_geo(t.root, doc, shaft)
    if sg is None:
        raise ToolError("I couldn't read that shaft's seats.")
    Ts = xform.from12(service._inst(doc, shaft)["T"])
    P, V = xform.pt(Ts, sg["p"]), xform.unit(Ts[:3, :3] @ sg["v"])
    spans = []
    for iid in ids:
        g = trains.elem_geom(t.root, service._inst(doc, iid)["part"])
        if g is None:
            raise ToolError(f"I couldn't read the faces of {service.human_names(doc)[iid]}.")
        T = xform.from12(service._inst(doc, iid)["T"])
        ends = sorted((float((xform.pt(T, g["p"] + g["v"] * g[x]) - P) @ V), g[f"{x}_face"]) for x in ("lo", "hi"))
        spans.append(([ends[0][0], ends[1][0]], iid, ends[1][1]))
    spans.sort(key=lambda x: x[0][0])
    (s0, a_id, a_face), (s1, _b, _bf) = spans
    spans = [s0, s1]
    gap = spans[1][0] - spans[0][1]
    if gap <= 0.2:
        raise ToolError(f"There is no gap between them ({_g(gap)} mm).")
    mid = (spans[0][1] + spans[1][0]) / 2
    seat = next((s for s in sg["seats"] if s["lo"] - 1e-6 <= mid <= s["hi"] + 1e-6), None)
    if seat is None:
        raise ToolError("There is no seat between them to put a spacer on.")
    return {"bore": seat["d"], "bore_src": "the shaft's seat", "length": round(gap, 3), "length_src": "the gap",
            "_place": {"shaft": shaft, "seat": seat["faces"][0], "t0": spans[0][1], "a": a_id, "a_face": a_face}}


def _place_spacer(t: Turn, doc: dict[str, Any], iid: str, pl: dict[str, Any]) -> str:
    """Put a spacer made for a gap into it: on the shaft's axis, its low face against the first part's face."""
    sg = shaft_geo(t.root, doc, pl["shaft"])
    g = trains.elem_geom(t.root, service._inst(doc, iid)["part"])
    if sg is None or g is None:
        return "I couldn't read the spacer's bore: it is unplaced, mate it by hand."
    Ts = xform.from12(service._inst(doc, pl["shaft"])["T"])
    P, V = xform.pt(Ts, sg["p"]), xform.unit(Ts[:3, :3] @ sg["v"])
    service._inst(doc, iid)["T"] = xform.to12(trains.place_on_axis(P, V, xform.perp(V), g, pl["t0"]))
    for typ, a, b in (("concentric", (pl["shaft"], pl["seat"]), (iid, g["bore_face"])),
                      ("coincident", (pl["a"], pl["a_face"]), (iid, g["lo_face"]))):
        service.make_mate(t.root, doc, {"type": typ, "a": {"inst": a[0], "kind": "face", "id": a[1]},
                                        "b": {"inst": b[0], "kind": "face", "id": b[1]}})
    names = service.human_names(doc)
    return f"Fitz put {names[iid]} on {names[pl['shaft']]} in the gap, against {names[pl['a']]}"


# ----------------------------------------------------------------------------- shaft lines
def _mated(doc: dict[str, Any], iid: str) -> set[str]:
    return {s["inst"] for m in doc["mates"] for s in (m["a"], m["b"]) if iid in (m["a"]["inst"], m["b"]["inst"])} - {iid}


def _shafts_of(root: Path, doc: dict[str, Any], iid: str) -> list[str]:
    return [o for o in _mated(doc, iid) if chat.role_of(root, doc, o) == "shaft"]


def line_of(root: Path, doc: dict[str, Any], shaft: str) -> list[str]:
    """What a shaft carries: the gears, hubs, bearings, keys, rings and spacers mated to it."""
    return sorted((o for o in _mated(doc, shaft) if chat.role_of(root, doc, o) in LINE_ROLES), key=_num_id)


def _meshing(root: Path, doc: dict[str, Any], gear: str) -> list[str]:
    return [o for m in doc["mates"] if m["type"] == "gear" and gear in (m["a"]["inst"], m["b"]["inst"])
            for o in (m["a"]["inst"], m["b"]["inst"]) if o != gear]


def closure(root: Path, doc: dict[str, Any], shafts: list[str]) -> list[str]:
    """The shafts whose lines mesh with these (placing one line again re-meshes the others)."""
    out = list(shafts)
    k = 0
    while k < len(out):
        for g in line_of(root, doc, out[k]):
            for o in _meshing(root, doc, g):
                for s in _shafts_of(root, doc, o):
                    if s not in out:
                        out.append(s)
        k += 1
    return out


def _item(root: Path, doc: dict[str, Any], iid: str, n: int, shafts: list[str]) -> dict[str, Any]:
    inst = service._inst(doc, iid)
    p = store.part(root, inst["part"]) or {}
    role = chat.role_of(root, doc, iid)
    it: dict[str, Any] = {"id": f"r{n}", "qty": 1, "qty_explicit": True, "enabled": True, "order": n,
                          "title": inst["name"], "part_key": inst["part"],
                          "action": "seat" if role == "bearing" else "train"}
    if p.get("kind") == "toolbox":
        it.update(source="toolbox", code=p["code"], params=dict(p["params"]))
    else:
        it.update(source="project", project_id=inst["source"].get("project_id"))
    if role == "bearing" and shafts:
        it["target"] = {"inst": shafts[0]}
    return it


def _rekey(doc: dict[str, Any], new: str, old: str, name: str, index: int) -> None:
    """Give a re-inserted instance its old id, name and place in the tree (references in the conversation hold)."""
    for i in doc["instances"]:
        if i["id"] == new:
            i["id"], i["name"] = old, name
    for m in doc["mates"]:
        for s in (m["a"], m["b"]):
            if s["inst"] == new:
                s["inst"] = old
    for j in doc.get("joints") or []:
        if j.get("insts"):
            j["insts"] = [old if x == new else x for x in j["insts"]]
    inst = next(i for i in doc["instances"] if i["id"] == old)
    doc["instances"].remove(inst)
    doc["instances"].insert(min(index, len(doc["instances"])), inst)


async def place_line(t: Turn, doc: dict[str, Any], shafts: list[str], members: list[str]) -> dict[str, Any]:
    """Place a set of shaft-line parts again, by construction, on these shafts (in order; the first one stays
    where it is and carries the line). Returns Fitz's result."""
    shafts = [s for s in shafts if s not in members]
    old = {}
    for iid in members:
        inst = service._inst(doc, iid)
        old[iid] = {"name": inst["name"], "index": doc["instances"].index(inst), "fixed": inst.get("fixed")}
    if shafts and any(o["fixed"] for o in old.values()):
        service._inst(doc, shafts[0])["fixed"] = True   # a part that goes on the shaft hands the base to it
    gone = set(members) | set(shafts)
    keep = [j for j in doc.get("joints") or [] if j["type"] == "gear" or not set(j.get("insts") or []) & gone]
    live = {j["id"] for j in keep if j["type"] != "gear"}
    doc["joints"] = [j for j in keep if j["type"] != "gear" or (j.get("a") in live and j.get("b") in live)]
    # mates from the line to parts outside it (a spacer, a fastener) are put back when the part comes back as it was
    member_set, shaft_set = set(members), set(shafts)
    any_shaft = shaft_set | {i["id"] for i in doc["instances"] if chat.role_of(t.root, doc, i["id"]) == "shaft"}
    outside = [m for m in doc["mates"] if (m["a"]["inst"] in member_set) != (m["b"]["inst"] in member_set)
               and not {m["a"]["inst"], m["b"]["inst"]} & any_shaft]   # never the shaft a part is moved off
    parts_before = {iid: service._inst(doc, iid)["part"] for iid in members}
    items = [_item(t.root, doc, iid, n, shafts) for n, iid in enumerate(members, start=1)]
    by_item = {f"r{n}": iid for n, iid in enumerate(members, start=1)}
    for iid in members:
        service.remove_instance(doc, iid)

    async def project_part(pid: str) -> str:
        return await t.env.project_part(pid)

    res = await fitz.execute(t.root, t.env.org_id, doc, items, project_part, check=False, shafts=shafts)
    for item, ids in (res.get("made") or {}).items():
        if item in by_item and ids:
            o = by_item[item]
            _rekey(doc, ids[0], o, old[o]["name"], old[o]["index"])
    now = {i["id"]: i["part"] for i in doc["instances"]}
    for m in outside:
        a_, b_ = m["a"]["inst"], m["b"]["inst"]
        if a_ in now and b_ in now and all(now[x] == parts_before.get(x, now[x]) for x in (a_, b_)):
            doc["mates"].append(m)
    service.run_solve(t.root, doc)
    return res


def _fitz_lines(res: dict[str, Any], doc: dict[str, Any]) -> tuple[list[str], str]:
    """Fitz's log, with the generated instance names translated to the conversation's names."""
    disp, human = service.display_names(doc), service.human_names(doc)
    swap = {disp[i]: human[i] for i in disp}
    lines = []
    for ln in res.get("log") or []:
        txt = ln["text"]
        if txt == res.get("summary"):
            continue
        for a, b in swap.items():
            txt = txt.replace(a, b)
        lines.append(txt)
    warn = any(o.get("severity") == "warn" for o in res.get("outcomes") or [])
    return lines, "warn" if warn else "ok"


def _gear_teeth(root: Path, doc: dict[str, Any], iid: str) -> int:
    p = store.part(root, service._inst(doc, iid)["part"]) or {}
    if p.get("kind") == "toolbox" and p.get("code") == "spur_gear":
        return int(p["params"]["Z"])
    cp = (((p.get("info") or {}).get("component") or {}).get("params") or {})
    return int(cp.get("teeth") or 999)


def order_members(root: Path, doc: dict[str, Any], shafts: list[str], members: list[str],
                  assign: dict[str, str] | None = None) -> list[str]:
    """Members in the order the line builder assigns them: gear k goes on shaft k (a gear already on a shaft, or
    named for one, keeps it; free gears smallest first, so the pinion goes on the first shaft), then hubs,
    bearings, keys, rings."""
    assign = dict(assign or {})
    roles = {m: chat.role_of(root, doc, m) for m in members}
    gears = [m for m in members if roles[m] == "gear"]
    for g in gears:
        if g not in assign:
            on = [s for s in _shafts_of(root, doc, g) if s in shafts]
            if on:
                assign[g] = on[0]
    slots: list[str | None] = [None] * len(shafts)
    for g in gears:
        s = assign.get(g)
        if s in shafts and slots[shafts.index(s)] is None:
            slots[shafts.index(s)] = g
    free = sorted((g for g in gears if g not in slots), key=lambda g: (_gear_teeth(root, doc, g), _num_id(g)))
    for k in range(len(slots)):
        if slots[k] is None and free:
            slots[k] = free.pop(0)
    out = [g for g in slots if g] + free
    for r in ("hub", "spacer", "bearing", "key", "ring"):
        out += [m for m in members if roles[m] == r]
    return out


async def t_mate(t: Turn, a: dict[str, Any]) -> dict[str, Any]:
    how = str(a.get("how") or "auto")
    async with DocEdit(t, solve=False) as doc:
        ps = resolve(t, doc, a.get("part"), None if str(a.get("part") or "").startswith("$") else 1)
        if not ps:
            raise ToolError("Say which part to mate.")
        p = ps[0]
        q = one(t, doc, a.get("to"), "mate it to")
        if q in ps:
            raise ToolError("A part can't be mated to itself.")
        names = service.human_names(doc)
        rp, rq = chat.role_of(t.root, doc, p), chat.role_of(t.root, doc, q)
        label = f"Mated {names[p]} to {names[q]}"
        sp = splines.pair(t.root, doc, p, q)
        if sp is not None:          # a splined hub on a splined shaft: by the interface, then the fit check
            hub, shaft, ins, ext = sp
            lines = splines.place(t.root, doc, hub, shaft, ins, ext)
            service.run_solve(t.root, doc)
            ok, fl = splines.check(t.root, doc, hub, shaft, ins, ext)
            lines += fl
            if not ok:
                lines.append("I can have the hub's spline remade to match the shaft: say \"fix the spline\".")
            return _step(label, lines, "ok" if ok else "warn", parts=[p, q])
        if how in ("bolted_joint", "mounted_on") or rp in ("plate", "bracket", "housing", "other", "flange") and \
                rq in ("plate", "bracket", "housing", "other", "flange"):
            ok, text = fitz.mount(t.root, doc, q, p)
            lines = [text]
            if ok and how == "bolted_joint":
                targets = fitz.fasten_targets(t.root, doc, None, p, None)
                if targets:
                    r = await service.accept(t.root, t.env.org_id, doc, targets, "hex_bolt", "both", False)
                    lines.append(f"Fitz fitted {r['inserted']} bolt stack{'s' if r['inserted'] != 1 else ''} through "
                                 "the lined-up holes")
            service.run_solve(t.root, doc)
            return _step(label, lines, "ok" if ok else "warn", parts=[p, q])
        if rp == "gear" and rq == "gear" or how == "gear_mesh":
            sp, sq = _shafts_of(t.root, doc, p), _shafts_of(t.root, doc, q)
            shafts = closure(t.root, doc, sq[:1] + [s for s in sp[:1] if s not in sq[:1]])
            members = sorted({m for s in shafts for m in line_of(t.root, doc, s)} | {p, q}, key=_num_id)
            assign = {q: sq[0]} if sq else {}
            if sp:
                assign[p] = sp[0]
            res = await place_line(t, doc, shafts, order_members(t.root, doc, shafts, members, assign))
            lines, status = _fitz_lines(res, doc)
            return _step(f"Meshed {names[p]} with {names[q]}", lines, status, parts=[p, q])
        if "shaft" in (rp, rq) and ({rp, rq} - {"shaft"}) <= set(LINE_ROLES):
            shaft, mems = (q, ps) if rq == "shaft" else (p, [q])
            shafts = closure(t.root, doc, [shaft])
            members = sorted({m for s in shafts for m in line_of(t.root, doc, s)} | set(mems), key=_num_id)
            res = await place_line(t, doc, shafts, order_members(t.root, doc, shafts, members, {m: shaft for m in mems}))
            lines, status = _fitz_lines(res, doc)
            if len(mems) > 1:
                label = f"Mated {len(mems)} parts to {names[shaft]}"
            return _step(label, lines, status, parts=[*mems, shaft])
        # anything else: concentric on the two largest round faces
        fa, fb = _main_axis(t.root, doc, p), _main_axis(t.root, doc, q)
        if fa is None or fb is None:
            raise ToolError(f"I can't tell how {names[p]} goes on {names[q]}: mate it by hand in the Mate tab.")
        m = service.make_mate(t.root, doc, {"type": "concentric", "a": {"inst": q, "kind": "face", "id": fb},
                                            "b": {"inst": p, "kind": "face", "id": fa}})
        service.run_solve(t.root, doc, [m["id"]])
        return _step(label, [(f"Made {names[p]} concentric with {names[q]} on their main round faces; slide or turn "
                             "it along the axis as needed")], "ok", parts=[p, q])


def _main_axis(root: Path, doc: dict[str, Any], iid: str) -> int | None:
    refs = store.refs(root, service._inst(doc, iid)["part"])["faces"]
    best = max(((float(f.get("r") or 0), int(k)) for k, f in refs.items() if f["kind"] == "axis" and f.get("r")),
               default=None)
    return best[1] if best else None


# ----------------------------------------------------------------------------- assemble
async def t_assemble(t: Turn, a: dict[str, Any]) -> dict[str, Any]:
    scope_all = a.get("parts") in (None, "all", "everything", ["all"]) or not a.get("parts")
    async with DocEdit(t, solve=False) as doc:
        names = service.human_names(doc)
        ids = [i["id"] for i in doc["instances"] if not i.get("group")] if scope_all else resolve(t, doc, a["parts"], None)
        if not ids:
            raise ToolError("There is nothing to assemble yet.")
        roles = {i: chat.role_of(t.root, doc, i) for i in ids}
        shafts = [i for i in ids if roles[i] == "shaft"]
        for i in ids:   # the shafts the named parts sit on belong to the job too
            for s in _shafts_of(t.root, doc, i):
                if s not in shafts:
                    shafts.append(s)
        members = [i for i in ids if roles[i] in LINE_ROLES]
        if shafts:
            shafts = closure(t.root, doc, sorted(shafts, key=lambda s: (not service._inst(doc, s).get("fixed"), _num_id(s))))
            members = sorted(set(members) | {m for s in shafts for m in line_of(t.root, doc, s)}, key=_num_id)
        gears = [m for m in members if chat.role_of(t.root, doc, m) == "gear"]
        hubs = [m for m in members if chat.role_of(t.root, doc, m) == "hub"]
        free_gears = [g for g in gears if not _shafts_of(t.root, doc, g)]
        assign = _assign_from_answers(t, doc, a, shafts, gears + hubs)
        if len(shafts) >= 2 and len(gears) < len(shafts) and any(g not in assign for g in free_gears + hubs):
            g = next(g for g in free_gears + hubs if g not in assign)
            raise Ambiguous(f"Which shaft does {names[g]} go on?", [names[s] for s in shafts])
        lines: list[str] = []
        status = "ok"
        # only the shafts something goes on: those carrying parts already, the ones named in an answer, and enough
        # more (in order) for the gears; the rest stay out of the line, and are said to be unplaced
        used = [s for s in shafts if line_of(t.root, doc, s) or s in assign.values()]
        for s in shafts:
            if len(used) >= max(1, len(gears)) or s in used:
                continue
            used.append(s)
        used = [s for s in shafts if s in used]
        idle = [s for s in shafts if s not in used]
        if members or len(gears) >= 2:
            res = await place_line(t, doc, used, order_members(t.root, doc, used, members, assign))
            lines, status = _fitz_lines(res, doc)
        for s in idle:
            lines.append(f"{names[s]}: nothing goes on it, so it stays where it is" +
                         (" (the fixed base)" if service._inst(doc, s).get("fixed") else ", unplaced"))
        others = [i for i in ids if roles[i] in ("plate", "bracket", "housing", "flange", "other", "cover")
                  and not _mated(doc, i) and not service._inst(doc, i).get("fixed")]
        base = next((i["id"] for i in doc["instances"] if i.get("fixed") and roles.get(i["id"]) not in LINE_ROLES), None)
        for o in others:
            if base and base != o:
                ok, text = fitz.mount(t.root, doc, base, o)
                lines.append(text)
                status = status if ok else "warn"
        service.run_solve(t.root, doc)
        lines += clear_loose(t.root, doc)
        if not lines:
            lines.append("Nothing here is a shaft line or a part with a hole pattern to mount, so nothing moved.")
            status = "info"
        return _step("Assembled everything" if scope_all else f"Assembled {len(ids)} parts", lines, status,
                     parts=sorted(set(ids) | set(members) | set(shafts), key=_num_id))


def clear_loose(root: Path, doc: dict[str, Any]) -> list[str]:
    """Unplaced parts that now sit inside the assembled parts move beside them (they would read as clashes)."""
    parts = service._parts(root, doc)
    lo_ids = set(chat.loose(doc))
    placed = service.world_box(doc, parts, only=lambda i: i["id"] not in lo_ids and not i.get("group"))
    if placed is None:
        return []
    lo, hi = placed
    out = []
    names = service.human_names(doc)
    for iid in sorted(lo_ids, key=_num_id):
        box = service.world_box(doc, parts, only=lambda i, iid=iid: i["id"] == iid)
        if box is None:
            continue
        b0, b1 = box
        if np.all(b0 < hi) and np.all(b1 > lo):
            dx = float(hi[0] - b0[0]) + max(10.0, 0.1 * float(np.linalg.norm(hi - lo)))
            service.move_instance(root, doc, iid, {"translate": [dx, 0.0, 0.0]})
            hi = np.maximum(hi, b1 + np.array([dx, 0.0, 0.0]))
            out.append(f"Moved {names[iid]} aside: it is unplaced and sat inside the assembled parts")
    return out


def _assign_from_answers(t: Turn, doc: dict[str, Any], a: dict[str, Any], shafts: list[str], movers: list[str]
                         ) -> dict[str, str]:
    """{"on": {"<part>": "<shaft>"}}: what the engineer chose for a question, as a gear/hub to shaft map."""
    out: dict[str, str] = {}
    for k, v in dict(a.get("on") or {}).items():
        try:
            g, s = one(t, doc, k, "place"), one(t, doc, v, "place it on")
        except (ToolError, Ambiguous):
            continue
        if g in movers and s in shafts:
            out[g] = s
    return out


# ----------------------------------------------------------------------------- check
async def t_check(t: Turn, a: dict[str, Any]) -> dict[str, Any]:
    what = [w for w in (a.get("what") or ["interference", "clearance"]) if w in
            ("interference", "clearance", "motion", "visual")] or ["interference", "clearance"]
    doc = store.load(t.root, t.aid)
    if doc is None or not doc["instances"]:
        raise ToolError("There is nothing to check yet.")
    lines: list[str] = []
    status = "ok"
    if "interference" in what or "clearance" in what:
        t.on_step("Checking for clashes")
        async with DocEdit(t, solve=False) as doc:
            an = await service.analyse(t.root, t.env.org_id, doc)
        hard = [p for p in an["interference"]["pairs"] if p["kind"] == "interference"]
        human = service.human_names(doc)
        if hard:
            status = "warn"
            lines.append(f"Interference: {len(hard)} clash{'es' if len(hard) != 1 else ''} (exact check): " + "; ".join(
                f"{human.get(p['a'])} and {human.get(p['b'])} overlap by {p['volume_mm3']:.3g} mm³" for p in hard[:5]))
        else:
            n = an["interference"]["checked_pairs"]
            lines.append(f"Interference: no clashes among {n} pair{'s' if n != 1 else ''} (exact check on nominal "
                         "geometry)")
        if "clearance" in what:
            mc = an["clearance"].get("min_clear_mm")
            contact = sum(1 for r in an["clearance"]["rows"] if r["status"] == "contact")
            lines.append(f"Clearance: {contact} pair{'s' if contact != 1 else ''} in contact (seated faces)"
                         + (f"; the smallest gap between parts that don't touch is {mc:.3g} mm" if mc is not None else ""))
    if "motion" in what:
        if not doc.get("joints"):
            lines.append("Motion: no joints yet (a shaft line gets them when it is assembled)")
        else:
            t.on_step("Turning the mechanism through its range")
            async with DocEdit(t, solve=False) as doc:
                mo = await service.motion_check(t.root, t.env.org_id, doc)
            bad = len(mo.get("colliding_steps") or [])
            status = "warn" if bad else status
            lines.append(f"Motion: {len(mo.get('steps') or [])} steps through the range, "
                         + (f"{bad} with a collision" if bad else "no collisions"))
    if "visual" in what:
        t.on_step("Looking at the assembly")
        rec = await t.env.look(t.root, doc)
        if rec is None:
            lines.append("Visual check: not available on this account")
        else:
            v = rec.get("verdict") or {}
            lines.append("Visual check (advisory, measurements decide): " + {
                "looks_assembled": "it looks assembled", "looks_wrong": "something looks wrong",
                "unsure": "unsure"}.get(str(v.get("verdict")), "no verdict") + (f": {v['summary']}" if v.get("summary") else ""))
    for ok, ln in splines.check_all(t.root, store.load(t.root, t.aid) or doc):
        lines.append(ln)
        status = status if ok else "warn"
    return _step("Checked the assembly", lines, status)


# ----------------------------------------------------------------------------- edits
async def t_move(t: Turn, a: dict[str, Any]) -> dict[str, Any]:
    by = a.get("by")
    if not (isinstance(by, list) and len(by) == 3):
        raise ToolError("Say how far to move it (x, y, z in mm).")
    async with DocEdit(t) as doc:
        p = one(t, doc, a.get("part"), "move")
        try:
            service.move_instance(t.root, doc, p, {"translate": [float(x) for x in by]})
        except AssemblyInputError as e:
            raise ToolError(str(e)) from None
        name = service.human_names(doc)[p]
    note = " Its mates pull it back where they hold it." if _mated(doc, p) else ""
    return _step(f"Moved {name}", [f"Moved {name} by ({', '.join(_g(x) for x in by)}) mm.{note}"], parts=[p])


async def t_remove(t: Turn, a: dict[str, Any]) -> dict[str, Any]:
    async with DocEdit(t) as doc:
        ids = resolve(t, doc, a.get("part"), None)
        if not ids:
            raise ToolError("Say which part to remove.")
        names = service.human_names(doc)
        gone = [names[i] for i in ids]
        for i in ids:
            service.remove_instance(doc, i)
        doc["joints"] = [j for j in doc.get("joints") or [] if j["type"] == "gear" or set(j.get("insts") or []) - set(ids)]
    return _step("Removed " + ", ".join(gone), [(f"Removed {', '.join(gone)} and the mates that held "
                                                f"{'it' if len(gone) == 1 else 'them'}.")])


async def _swap(t: Turn, doc: dict[str, Any], iid: str, key: str) -> dict[str, int]:
    old = service._inst(doc, iid)["part"]
    c = service.remap_refs(t.root, doc, iid, key, old)
    inst = service._inst(doc, iid)
    inst["part"] = key
    inst["source"] = service._source(store.part(t.root, key))  # type: ignore[arg-type]
    return c


async def t_replace(t: Turn, a: dict[str, Any]) -> dict[str, Any]:
    doc = store.load(t.root, t.aid)
    if doc is None:
        raise ToolError("The assembly was deleted.")
    p = one(t, doc, a.get("part"), "replace")
    code = a.get("code")
    if code not in toolbox.COMPONENTS:
        raise ToolError("Say which Toolbox component replaces it.")
    host = next(iter(_shafts_of(t.root, doc, p)), None)
    try:
        params, _notes = makers.size_for_host(str(code), dict(a.get("params") or {}),
                                              shaft_geo(t.root, doc, host) if host else None)
    except toolbox.ToolboxError as e:
        raise ToolError(str(e)) from None
    key = await service.ensure_toolbox_part(t.root, t.env.org_id, str(code), params)
    title = toolbox.spec(str(code)).title(params)
    async with DocEdit(t) as doc:
        old = service.human_names(doc)[p]
        c = await _swap(t, doc, p, key)
        service._inst(doc, p)["name"] = title
    return _step(f"Replaced {old}", [f"Replaced {old} with {title}: {c['kept'] + c['followed']} mate references kept"
                                     + (f", {c['lost']} lost (those mates are broken: fix them in the Mate tab)"
                                        if c["lost"] else "")], "warn" if c["lost"] else "ok", parts=[p])


_PARAM_WORDS = {"face width": ("B", "FACE_WIDTH"), "width": ("B", "FACE_WIDTH", "L", "LENGTH"),
                "wider": ("B", "FACE_WIDTH"), "narrower": ("B", "FACE_WIDTH"), "teeth": ("Z", "TEETH"),
                "module": ("M", "MODULE"), "bore": ("BORE",), "length": ("L", "LENGTH", "L_SEAT"),
                "longer": ("L", "LENGTH", "L_SEAT"), "diameter": ("D", "D_SEAT", "D_JOURNAL", "OD"),
                "designation": ("SERIES",), "size": ("SERIES", "D")}


def _param_name(given: str, avail: list[str]) -> str | None:
    if given in avail:
        return given
    up = given.upper().replace(" ", "_")
    if up in avail:
        return up
    for word, cands in _PARAM_WORDS.items():
        if word in given.lower():
            hit = next((c for c in cands if c in avail), None)
            if hit:
                return hit
    return None


async def t_resize(t: Turn, a: dict[str, Any]) -> dict[str, Any]:
    doc = store.load(t.root, t.aid)
    if doc is None:
        raise ToolError("The assembly was deleted.")
    p = one(t, doc, a.get("part"), "resize")
    inst = service._inst(doc, p)
    part = store.part(t.root, inst["part"]) or {}
    name = service.human_names(doc)[p]
    by, to = a.get("by"), a.get("to")
    if part.get("kind") == "toolbox":
        prm = dict(part["params"])
        pn = _param_name(str(a.get("param") or ""), list(prm))
        if pn is None:
            raise ToolError(f"{name} has no parameter called {a.get('param')}: it has " + ", ".join(
                f"{p_.label.lower()}" for p_ in toolbox.spec(part["code"]).params) + ".")
        new = float(to) if to is not None else float(prm[pn]) + float(by or 0)
        before = float(prm[pn])
        prm[pn] = new
        try:
            prm = toolbox.normalize(part["code"], prm)
        except toolbox.ToolboxError as e:
            raise ToolError(str(e)) from None
        key = await service.ensure_toolbox_part(t.root, t.env.org_id, part["code"], prm)
        title = toolbox.spec(part["code"]).title(prm)
        async with DocEdit(t) as doc:
            c = await _swap(t, doc, p, key)
            if service._inst(doc, p)["name"] == part.get("name"):
                service._inst(doc, p)["name"] = title
        label = next((x.label for x in toolbox.spec(part["code"]).params if x.name == pn), pn)
    else:
        pid = inst["source"].get("project_id")
        avail = list(((part.get("params") or {}) or _project_params(t, pid)).keys())
        pn = _param_name(str(a.get("param") or ""), avail)
        if pn is None:
            raise ToolError(f"{name} has no parameter for {a.get('param')}: ask in the Design Studio.")
        cur = _project_params(t, pid)
        if pn not in cur:
            raise ToolError(f"{pn} is not an editable parameter of {name}.")
        before = float(cur[pn])
        new = float(to) if to is not None else before + float(by or 0)
        t.on_step(f"Rebuilding {name}")
        await t.env.set_params(str(pid), {pn: new})
        key = await t.env.project_part(str(pid))
        async with DocEdit(t) as doc:
            c = {"kept": 0, "followed": 0, "lost": 0}
            for i in doc["instances"]:
                if i["source"].get("project_id") == pid and i["part"] != key:
                    cc = await _swap(t, doc, i["id"], key)
                    for k_ in c:
                        c[k_] += cc[k_]
        label = pn
    lines = [f"{name}: {str(label).lower()} {_g(before)} → {_g(new)} mm, the part's own parameter; its mates are kept "
             f"({c['kept'] + c['followed']} references followed" + (f", {c['lost']} lost" if c["lost"] else "") + ")"]
    return _step(f"Resized {name}", lines, "warn" if c["lost"] else "ok", parts=[p])


def _project_params(t: Turn, pid: Any) -> dict[str, Any]:
    getp = getattr(t.env, "project_params", None)
    return dict(getp(str(pid)) or {}) if getp else {}


async def t_explain(t: Turn, a: dict[str, Any]) -> dict[str, Any]:
    doc = store.load(t.root, t.aid)
    if doc is None or not doc["instances"]:
        return _step("The assembly", ["The assembly is empty: tell me what to make or bring in."], "info")
    names = service.human_names(doc)
    ms = chat.mate_state(doc)
    lines = []
    for i in doc["instances"]:
        if i.get("group"):
            continue
        partners = sorted({o for o, _s in ms["per"].get(i["id"], [])}, key=_num_id)
        bad = any(s != "ok" for _o, s in ms["per"].get(i["id"], []))
        where = ("fixed at the origin (the base)" if i.get("fixed") else
                 "unplaced" if not partners else "on " + ", ".join(names[o] for o in partners[:3])
                 + (" (a mate is not satisfied)" if bad else ""))
        lines.append(f"{names[i['id']]}: {where}")
    st = chat.state_line(t.root, doc)
    lines.append(chat.state_text(st))
    return _step("The assembly now", lines, "info")


TOOLS: dict[str, Callable[[Turn, dict[str, Any]], Awaitable[dict[str, Any]]]] = {
    "find": t_find, "bring": t_bring, "make": t_make, "mate": t_mate, "assemble": t_assemble, "check": t_check,
    "move": t_move, "remove": t_remove, "replace": t_replace, "resize": t_resize, "explain": t_explain}
FAILED = {"find": "Search not done", "bring": "Not brought in", "make": "Not made", "mate": "Not mated",
          "assemble": "Not assembled", "check": "Check not run", "move": "Not moved", "remove": "Not removed",
          "replace": "Not replaced", "resize": "Not resized", "explain": "Not explained"}
LABELS = {"find": "Looking for parts", "bring": "Bringing in a part", "make": "Making a part", "mate": "Mating",
          "assemble": "Assembling", "check": "Checking", "move": "Moving a part", "remove": "Removing a part",
          "replace": "Replacing a part", "resize": "Resizing a part", "explain": "Summing up"}


# ----------------------------------------------------------------------------- one turn
async def run_turn(root: Path, aid: str, env: Env, text: str, ai: bool) -> dict[str, Any]:
    """Run one conversation turn end to end and store the reply. Never raises: a failure is said in the chat."""
    t0 = time.perf_counter()
    turn = Turn(root, aid, env, tid=f"t{time.time_ns() // 1000 % 10_000_000_000}")

    def busy(step: str) -> None:
        chat.update(root, aid, lambda c: c.__setitem__("busy", {**(c.get("busy") or {}), "step": step}))

    turn.on_step = busy
    say, actions, questions, tokens, offline = "", [], [], 0, not ai
    doc = store.load(root, aid)
    try:
        c = chat.load(root, aid)
        if ai and doc is not None:
            busy("Reading the conversation")
            summ = chat.summary(root, doc, env.candidates(), env.context(doc), c.get("jobs"))
            hist = chat.history({"messages": c["messages"][:-1]})
            data, tokens, err = await env.model(chat.system_prompt(), chat.prompt(summ, hist, text), chat.job_of(text),
                                                chat.REPLY_SCHEMA)
            if data is not None:
                say, actions, questions = chat.parse_reply(data)
            else:
                log.warning("assembly agent: no usable reply (%s)", err)
                offline = True
        if offline:
            say, actions = chat.offline(text)
        held: set[str] = set()       # labels of actions that asked a question: what depends on them waits
        for a in actions:
            # after a question, the parts still get made and brought (everything that can proceed does); what
            # places, checks or edits them waits for the answer, as does anything naming the part asked about
            if held & _labels_in(a) or turn.questions and a["do"] not in ("find", "bring", "make"):
                continue
            busy(LABELS.get(a["do"], "Working"))
            try:
                turn.steps.append(await TOOLS[a["do"]](turn, a))
            except Pending as e:
                turn.deferred.append({"action": a, "needs": sorted(_labels_in(a) & (set(turn.pending) | set(turn.labels)))
                                      or [e.label]})
                if a.get("as"):
                    turn.pending.setdefault(str(a["as"]), turn.pending[e.label])
            except Ambiguous as e:
                if len(turn.questions) < 2:
                    turn.questions.append({**e.question, "id": f"q{len(turn.questions) + 1}"})
                if a.get("as"):
                    held.add(str(a["as"]))
            except ToolError as e:
                turn.steps.append(_step(FAILED.get(a["do"], "Not done"), [str(e)], "fail"))
            except (AssemblyInputError, toolbox.ToolboxError, makers.MakeError) as e:
                turn.steps.append(_step("Not done", [str(e)], "fail"))
            except service.WorkerError:
                log.warning("assembly agent step failed", exc_info=True)
                turn.steps.append(_step("Not done", ["The geometry engine failed on this step. Try again."], "fail"))
    except Exception:
        log.exception("assembly agent turn failed")
        turn.steps.append(_step("Stopped", [("Something went wrong on my side; the assembly is as the last step left "
                                            "it. Try again, or use the tools on the right.")], "fail"))
    doc = store.load(root, aid)
    st = chat.state_line(root, doc) if doc is not None and doc["instances"] else None
    for d in turn.deferred:
        job = turn.pending.get(d["needs"][0]) if d["needs"] else None
        names = [turn.pending[x]["name"] for x in d["needs"] if x in turn.pending]
        if names:
            turn.steps.append(_step(f"Then: {LABELS.get(d['action']['do'], 'the next step').lower()}",
                                    [(f"Runs when {' and '.join(dict.fromkeys(names))} "
                                      f"{'is' if len(set(names)) == 1 else 'are'} in the assembly")], "info",
                                    job=(job or {}).get("id")))
    reply = {"role": "agent", "text": say, "steps": turn.steps, "questions": (turn.questions or questions)[:2],
             "state": st, "state_text": chat.state_text(st) if st else "",
             "tokens": tokens, "seconds": round(time.perf_counter() - t0, 1), "offline": offline, "at": store.now()}
    if not say and not turn.steps and not reply["questions"]:
        reply["text"] = "I'm not sure what to do with that. Tell me what to make, bring, assemble or check."

    def finish(c: dict[str, Any]) -> None:
        reply["id"] = chat.next_id(c)
        c["messages"].append(reply)
        c["busy"] = None
        c["jobs"] = (c.get("jobs") or []) + turn.jobs
        if turn.deferred or turn.jobs:
            bound = c.setdefault("labels", {}).setdefault(turn.tid, {})
            bound.update({k: v for k, v in turn.labels.items() if v})
            c.setdefault("deferred", []).extend({**d, "turn": turn.tid} for d in turn.deferred)

    chat.update(root, aid, finish)
    for job in turn.jobs:
        _spawn(watch_job(root, aid, env, job))
    return reply


_bg: set[asyncio.Task[Any]] = set()


def _spawn(coro: Any) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    _bg.add(task)
    task.add_done_callback(_bg.discard)


def _labels_in(a: dict[str, Any]) -> set[str]:
    """The ``$labels`` an action refers to."""
    out: set[str] = set()
    for k in ("part", "for", "to", "parts", "between", "of"):
        v = a.get(k)
        for x in v if isinstance(v, list) else [v]:
            if isinstance(x, str) and x.startswith("$"):
                out.add(x)
    return out


def unverified_note(bs: dict[str, Any]) -> str:
    """Honest words for a built part whose own checks are not all passed (or that the engineer accepted)."""
    open_ = ", ".join(f"{c['id']} {c['name']}" for c in bs.get("open") or []) or "a check"
    acc = bs.get("accepted")
    if acc:
        return f"Verified by {acc.get('by') or 'the engineer'} (open: {open_})"
    return f"Unverified: {open_} did not pass"


def _set_job(root: Path, aid: str, jid: str, **kw: Any) -> None:
    def fn(c: dict[str, Any]) -> None:
        for j in c.get("jobs") or []:
            if j["id"] == jid:
                j.update(kw)
    chat.update(root, aid, fn)


def _post(root: Path, aid: str, text: str, steps: list[dict[str, Any]], jid: str,
          questions: list[dict[str, Any]] | None = None) -> None:
    doc = store.load(root, aid)
    st = chat.state_line(root, doc) if doc is not None and doc["instances"] else None

    def post(c: dict[str, Any]) -> None:
        c["messages"].append({"id": chat.next_id(c), "role": "agent", "text": text, "steps": steps,
                              "questions": questions or [], "state": st, "state_text": chat.state_text(st) if st else "",
                              "tokens": 0, "at": store.now(), "job": jid})
    chat.update(root, aid, post)


def relay_questions(qs: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    """The design agent's questions as the assembly chat's clickable questions, prefixed with the part's name."""
    out = []
    for k, q in enumerate(qs or []):
        if not isinstance(q, dict) or not str(q.get("question") or "").strip():
            continue
        opts = [chat.scrub(str(o))[:80] for o in q.get("options") or [] if str(o).strip()][:6]
        d = q.get("default")
        out.append({"id": f"d{k + 1}", "question": chat.scrub(f"{name}: {q['question']}")[:220], "options": opts,
                    "default": d if d in opts else None, "multi": bool(q.get("multi")), "other": True})
    return out[:5]


async def watch_job(root: Path, aid: str, env: Env, job: dict[str, Any]) -> None:
    """A part the design agent makes: relay its progress and questions into the chat; bring it in when it is built
    (verified, or built with a check open: then honestly labelled), mate it, and run what waited for it."""
    asked: list[dict[str, Any]] = []

    def on_questions(qs: list[dict[str, Any]]) -> None:
        asked.extend(qs)

    text = ""
    steps: list[dict[str, Any]] = []
    try:
        verified = await env.watch_design(job["project_id"], lambda s: _set_job(root, aid, job["id"], step=s),
                                          on_questions)
        bs = env.build_state(job["project_id"])
        if asked and not bs.get("geometry"):
            qs = relay_questions(asked, job["name"])
            _set_job(root, aid, job["id"], status="question", step="Waiting for your answer", questions=qs)
            _post(root, aid, (f"The design agent needs an answer to finish {job['name']}. Pick one (or type your "
                              "own) and it continues from here."), [], job["id"], qs)
            return
        if bs.get("geometry"):
            key = await env.project_part(job["project_id"])
            turn = Turn(root, aid, env)
            async with DocEdit(turn) as doc:
                iid = service.add_instance(root, doc, key)["id"]
                name = service.human_names(doc)[iid]
            lines = [f"{job['name']} is built: brought it into the assembly"]
            status = "ok"
            if not (verified or bs.get("verified")):
                lines.append(unverified_note(bs) + ". It is in the assembly with that label; I can fix it, or you can "
                             "mark it as verified.")
                status = "warn"
            steps.append(_step(f"Brought {name}", lines, status, parts=[iid], project_id=job["project_id"],
                               unverified=not (verified or bs.get("verified")) and not bs.get("accepted"),
                               open=bs.get("open") or []))
            _bind(root, aid, job, iid)
            if job.get("for"):
                try:
                    steps.append(await t_mate(turn, {"part": iid, "to": job["for"], "how": "auto"}))
                except (ToolError, Ambiguous, AssemblyInputError) as e:
                    steps.append(_step("Not mated", [str(e)], "warn"))
            text = f"{job['name']} is ready." if status == "ok" else f"{job['name']} is in, with a check open."
            _set_job(root, aid, job["id"], status="done", step="Brought in" if status == "ok" else "Brought in, unverified",
                     questions=None)
        else:
            text = (f"The design agent stopped before {job['name']} had any geometry. Tell me what to change and I'll "
                    "start it again.")
            _set_job(root, aid, job["id"], status="failed", step="No geometry")
    except Exception:
        log.exception("design job failed")
        text = f"The design of {job['name']} stopped. Say \"try {job['name']} again\" and I'll restart it."
        _set_job(root, aid, job["id"], status="failed", step="Stopped")
    steps += await run_deferred(root, aid, env)
    _post(root, aid, text, steps, job["id"])


def _bind(root: Path, aid: str, job: dict[str, Any], iid: str) -> None:
    if not job.get("as") or not job.get("turn"):
        return

    def fn(c: dict[str, Any]) -> None:
        c.setdefault("labels", {}).setdefault(job["turn"], {})[job["as"]] = [iid]
    chat.update(root, aid, fn)


async def run_deferred(root: Path, aid: str, env: Env) -> list[dict[str, Any]]:
    """Run the actions that waited for parts being designed, once every part they name is in the assembly."""
    steps: list[dict[str, Any]] = []
    for _round in range(8):    # an action that ran can bind a label another one waits for
        ready: list[dict[str, Any]] = []

        def take(c: dict[str, Any], ready: list[dict[str, Any]] = ready) -> None:
            keep = []
            for d in c.get("deferred") or []:
                bound = (c.get("labels") or {}).get(d.get("turn"), {})
                (ready if all(bound.get(x) for x in d.get("needs") or []) else keep).append(d)
            c["deferred"] = keep
        c = chat.update(root, aid, take)
        if not ready:
            break
        steps += await _run_ready(root, aid, env, c, ready)
    return steps


async def _run_ready(root: Path, aid: str, env: Env, c: dict[str, Any], ready: list[dict[str, Any]]
                     ) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for d in ready:
        t = Turn(root, aid, env, tid=str(d.get("turn")))
        t.labels = {k: list(v) for k, v in ((c.get("labels") or {}).get(d.get("turn"), {})).items()}
        a = d["action"]
        try:
            steps.append(await TOOLS[a["do"]](t, a))
        except (ToolError, Ambiguous, Pending) as e:
            steps.append(_step(FAILED.get(a["do"], "Not done"), [str(getattr(e, "question", {}).get("question")
                                                                    if isinstance(e, Ambiguous) else e)], "warn"))
        except (AssemblyInputError, toolbox.ToolboxError, makers.MakeError, service.WorkerError) as e:
            steps.append(_step(FAILED.get(a["do"], "Not done"), [str(e)], "warn"))
        if t.labels:
            def keep_labels(cc: dict[str, Any], tl: dict[str, list[str]] = t.labels, tid: str = t.tid) -> None:
                cc.setdefault("labels", {}).setdefault(tid, {}).update({k: v for k, v in tl.items() if v})
            chat.update(root, aid, keep_labels)
        for j in t.jobs:
            chat.update(root, aid, lambda cc, j=j: cc.setdefault("jobs", []).append(j))
            _spawn(watch_job(root, aid, env, j))
    return steps


async def answer_job(root: Path, aid: str, env: Env, jid: str, text: str) -> dict[str, Any]:
    """The engineer answered a design job's question in the assembly chat: pass it on and follow the design again."""
    c = chat.load(root, aid)
    job = next((j for j in c.get("jobs") or [] if j["id"] == jid), None)
    if job is None or job.get("status") != "question":
        raise ToolError("That design isn't waiting for an answer any more.")
    await env.answer_design(job["project_id"], text)
    _set_job(root, aid, jid, status="running", step="Continuing with your answer", questions=None)
    _post(root, aid, f"Passed your answer to the design agent for {job['name']}; it continues.", [], jid)
    _spawn(watch_job(root, aid, env, {**job, "status": "running"}))
    return job
