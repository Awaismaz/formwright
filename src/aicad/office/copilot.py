"""Archie as the whole-app copilot (founder, 2026-11-20: "its role is not only design office, it should be my
complete software copilot").

Archie is reachable from every page. Besides the program actions in ``archie_chat`` he has *app actions*:

* ``navigate`` / ``point``: take the engineer to a page (optionally a program tab) and highlight a button on it.
  They run at once on the engineer's screen (nothing changes in their data), so they need no Apply.
* ``studio_request``: open a part in Design Studio with a request typed into its design chat (the engineer sends
  it, so the design agent's run and its cost stay theirs to start).
* ``new_program`` / ``restart_program``: start a program from a new prompt; a restart pauses the old program
  (kept, never deleted) and opens the new one.
* ``heal_program``: the office repairs a program in place: work left running by a stopped server is queued
  again, old review blocks are healed, blocked parts retried and the office run.
* ``rebuild_assembly`` / ``run_program`` / ``new_part`` / ``stop_studio_agent``.

Everything that changes data is a proposal applied by the engineer, through the same route as its button.
The conversation outside a program is kept per user in ``<org>/_copilot/<user>.json``; on a program page the
program's own conversation is used (so Archie's supervision messages stay with the program).
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote

from aicad.office import store

APP_ACTION_TYPES = ("navigate", "point", "studio_request", "new_program", "restart_program", "heal_program",
                    "rebuild_assembly", "run_program", "new_part", "stop_studio_agent")
# run on the engineer's screen when the reply arrives (no data changes): shown as "Show me" instead of Apply
CLIENT_ACTIONS = frozenset({"navigate", "point", "studio_request"})
PROGRAM_TABS = ("board", "interfaces", "assembly", "deliverables", "timeline", "tree", "archie", "activity", "brief")
MAX_BRIEF = 20000
MAX_TARGETS = 80

# the app's pages: (pattern, title, what it is for); patterns use {project}, {program}, {module}
PAGES: tuple[tuple[str, str, str], ...] = (
    ("/app", "Home", "start a part from a brief or a STEP/PDF/photo, the getting-started checklist, recent work"),
    ("/app/projects", "Projects", "every part project; ?new=1 opens New project, ?q=text searches (also by size)"),
    ("/app/projects/{project}", "Design Studio", ("one part: design chat with the design agent, 3D model, model by "
     "hand (sketch, extrude, fillet...), checks, parameters, revisions, files and exports")),
    ("/app/office", "Design Office", "every multi-part program, its status and what waits for the engineer"),
    ("/app/office/new", "New program", "start a program (an assembly of many parts) from a brief"),
    ("/app/office/programs/{program}", "Program", ("one program; ?tab= board | interfaces | assembly | deliverables | "
     "timeline | tree | archie | activity | brief")),
    ("/app/modules", "Modules", "drawings, manufacturability, engineering checks, print prep, assemblies, renders"),
    ("/app/modules/{module}", "Module", "one module's own page"),
    ("/app/billing", "Billing and tokens", "plan, token balance, top-ups (#tokens)"),
    ("/app/team", "Team", "invite teammates, roles"),
    ("/app/settings", "Settings", "profile, password, preferences"),
    ("/app/help", "Help", "guides for every module, keyboard shortcuts, contact"),
)

COPILOT_INSTRUCTIONS = """You are Archie, Chief Designer at Formwright and the engineer's copilot for the whole \
app: parts in Design Studio, programs in Design Office, the modules, billing, team and settings. You see the page \
the engineer is on, the controls on it, their programs and their part projects. Answer in plain engineering \
language, under eight sentences. When asked where something is or how to do something, show them: navigate to \
the page and point at the control. When something is wrong (stuck, blocked, failing, slow), diagnose it from what \
you see and propose the fix with your actions. Never mention files, tools, code, models or how you work inside.

""" + "{BRIEF_RULE}" + """

Navigation and pointing run at once. Everything else is proposed: never claim a change is done; the engineer \
applies it. Put actions in exactly one fenced block (omit it when none is needed):
```fw-office-actions
[{"type": "...", ...}]
```
""" + "{APP_ACTIONS}"

APP_ACTIONS_DOC = """App actions (use ids exactly as listed; a program or project may also be given by its exact name):
- {"type": "navigate", "to": "/app/...", "highlight": "control label (optional)"}: open a page of the app (only \
pages listed under Pages, with real ids). For a program tab: "/app/office/programs/ID?tab=interfaces".
- {"type": "point", "target": "control id or label as listed under Controls", "note": "what to press it for"}: \
highlight a control on the current page.
- {"type": "studio_request", "project": "ID", "text": "the request for the design agent"}: open that part in \
Design Studio with the request typed into its design chat, ready for the engineer to send.
- {"type": "new_part", "name": "...", "brief": "..."}: a new part project, opened in Design Studio with the brief \
ready to send.
- {"type": "new_program", "name": "...", "brief": "full brief"}: a new Design Office program planned from this brief.
- {"type": "restart_program", "program": "ID", "brief": "the new full brief", "name": "optional"}: the program is \
wrong at its root (a different product or a brief that changes most parts): start again from the new prompt. The \
old program is paused and kept. Prefer a revision when most of the work still fits.
- {"type": "heal_program", "program": "ID"}: the office repairs a stuck program: work left half-done is queued \
again, review blocks are healed, blocked parts retried and the office run.
- {"type": "rebuild_assembly", "program": "ID"}: lay out and build the program assembly again.
- {"type": "run_program", "program": "ID"}: run the office on a program.
- {"type": "stop_studio_agent", "project": "ID"}: stop a design agent run that is stuck on a part."""

_lock = threading.Lock()
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# --------------------------------------------------------------------------- the per-user conversation
def _file(root: Path, user_id: str) -> Path:
    return root / "_copilot" / f"{user_id}.json"


def history(root: Path, user_id: str) -> list[dict[str, Any]]:
    if not _ID.match(user_id):
        return []
    d = store.read_json(_file(root, user_id))
    return d if isinstance(d, list) else []


def save_history(root: Path, user_id: str, msgs: list[dict[str, Any]]) -> None:
    from aicad.office.archie_chat import MAX_MESSAGES

    if not _ID.match(user_id):
        return
    f = _file(root, user_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        store.write_json(f, msgs[-MAX_MESSAGES:])


# --------------------------------------------------------------------------- what Archie can see
def clean_page(page: Any) -> dict[str, Any]:
    """The page the engineer is on, as the app sent it: path, title and the visible controls (ids and labels)."""
    if not isinstance(page, dict):
        return {}
    path = str(page.get("path") or "")[:300]
    if not path.startswith("/app"):
        path = ""
    targets = []
    for t in (page.get("targets") or [])[:MAX_TARGETS * 2]:
        if not isinstance(t, dict):
            continue
        tid = " ".join(str(t.get("id") or "").split())[:80]
        lbl = " ".join(str(t.get("label") or "").split())[:80]
        if tid and lbl and all(x["id"] != tid for x in targets):
            targets.append({"id": tid, "label": lbl})
        if len(targets) >= MAX_TARGETS:
            break
    return {"path": path, "title": " ".join(str(page.get("title") or "").split())[:120], "targets": targets}


def context_lines(page: dict[str, Any], known: dict[str, Any]) -> list[str]:
    lines = ["Pages:\n" + "\n".join(f"- {p} ({t}): {w}" for p, t, w in PAGES)]
    if known.get("modules"):
        lines.append("Modules: " + ", ".join(f"{c} ({n})" for c, n in known["modules"].items()))
    if page.get("path"):
        lines.append(f"The engineer is on: {page['path']}" + (f" ({page['title']})" if page.get("title") else ""))
    if page.get("targets"):
        lines.append("Controls on this page (id: label):\n" + "\n".join(f"- {t['id']}: {t['label']}"
                                                                      for t in page["targets"]))
    if known.get("programs"):
        lines.append("Programs (id, name, state):\n" + "\n".join(
            f"- {pid} {p['name']}: {p['state']}" for pid, p in list(known["programs"].items())[:30]))
    if known.get("projects"):
        lines.append("Part projects (id, name):\n" + "\n".join(
            f"- {pid} {p['name']}" for pid, p in list(known["projects"].items())[:40]))
    return lines


def prompt(page: dict[str, Any], known: dict[str, Any], hist: list[dict[str, Any]], text: str) -> str:
    from aicad.office.archie_chat import HISTORY_TURNS

    lines = context_lines(page, known)
    convo = [f"{'Engineer' if m['role'] == 'user' else 'Archie'}: {m['text'][:600]}" for m in hist[-HISTORY_TURNS:]]
    if convo:
        lines.append("Conversation so far:\n" + "\n".join(convo))
    lines.append(f"Engineer: {text}")
    return "\n\n".join(lines)


def system(program: bool) -> str:
    """The copilot's instructions; on a program page the program instructions come first and these are added."""
    if not program:
        from aicad.office.archie_chat import BRIEF_RULE

        return COPILOT_INSTRUCTIONS.replace("{APP_ACTIONS}", APP_ACTIONS_DOC).replace("{BRIEF_RULE}", BRIEF_RULE)
    return ("\n\nYou are also the engineer's copilot for the whole app. You see the page they are on and its "
            "controls. When asked where something is, navigate and point. When the program is wrong at its root, "
            "propose restart_program; when it is stuck, heal_program.\n" + APP_ACTIONS_DOC)


# --------------------------------------------------------------------------- checking a proposed app action
def _ref(kind: dict[str, Any] | None, ref: Any) -> str | None:
    """A program or project id from Archie's reference (an id, or an exact name); None when unknown. Without the
    list (re-checking a stored proposal) an id-shaped reference is kept: the route itself checks it exists."""
    r = " ".join(str(ref or "").split())
    if not r:
        return None
    if kind is None:
        return r if _ID.match(r) else None
    if r in kind:
        return r
    hit = [i for i, v in kind.items() if v["name"].lower() == r.lower()]
    return hit[0] if len(hit) == 1 else None


def _path_ok(to: str, known: dict[str, Any] | None) -> str | None:
    base, _, query = to.partition("?")
    base = base.rstrip("/") or "/app"
    for pat, _t, _w in PAGES:
        rx = "^" + re.escape(pat).replace(r"\{project\}", "(?P<project>[A-Za-z0-9_-]+)").replace(
            r"\{program\}", "(?P<program>[A-Za-z0-9_-]+)").replace(r"\{module\}", "(?P<module>[a-z0-9_-]+)") + "$"
        m = re.match(rx, base)
        if not m:
            continue
        g = m.groupdict()
        if known is not None:
            if "project" in g and g["project"] not in known.get("projects", {}):
                return None
            if "program" in g and g["program"] not in known.get("programs", {}):
                return None
            if "module" in g and known.get("modules") and g["module"] not in known["modules"]:
                return None
        if query:
            if "program" in g:
                tab = dict(x.split("=", 1) for x in query.split("&") if "=" in x).get("tab", "")
                query = f"tab={tab}" if tab in PROGRAM_TABS else ""
            elif base == "/app/projects":
                query = "&".join(x for x in query.split("&") if x == "new=1" or x.startswith("q="))[:200]
            else:
                query = ""
        return base + (f"?{query}" if query else "")
    return None


def _text(v: Any, n: int = 2000) -> str:
    return " ".join(str(v or "").split())[:n]


def normalise(a: Any, known: dict[str, Any] | None = None, page: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """One proposed app action, checked; None when it can't apply. ``known`` (programs, projects, modules of the
    engineer) makes references strict; ``page`` holds the controls a ``point`` may use."""
    if not isinstance(a, dict) or a.get("type") not in APP_ACTION_TYPES:
        return None
    typ = a["type"]
    progs = None if known is None else known.get("programs", {})
    projs = None if known is None else known.get("projects", {})
    if typ == "navigate":
        to = _path_ok(str(a.get("to") or "").strip(), known)
        if to is None:
            return None
        out: dict[str, Any] = {"type": typ, "to": to}
        if _text(a.get("highlight"), 80):
            out["highlight"] = _text(a.get("highlight"), 80)
        return out
    if typ == "point":
        tgt = _text(a.get("target"), 80)
        if not tgt:
            return None
        if page is not None and page.get("targets"):
            hit = next((t for t in page["targets"] if t["id"] == tgt or t["label"].lower() == tgt.lower()), None)
            if hit is None:
                return None
            return {"type": typ, "target": hit["id"], "label": hit["label"], "note": _text(a.get("note"), 300)}
        return {"type": typ, "target": tgt, "label": _text(a.get("label"), 80) or tgt, "note": _text(a.get("note"), 300)}
    if typ in ("studio_request", "stop_studio_agent"):
        pid = _ref(projs, a.get("project"))
        if pid is None:
            return None
        out = {"type": typ, "project": pid}
        if typ == "studio_request":
            if not _text(a.get("text")):
                return None
            out["text"] = _text(a.get("text"))
        return out
    if typ in ("new_program", "new_part"):
        brief = " ".join(str(a.get("brief") or "").split())[:MAX_BRIEF]
        if len(brief) < 20:
            return None
        name = _text(a.get("name"), 120) or " ".join(brief.split()[:6])[:60]
        return {"type": typ, "name": name, "brief": brief}
    pid = _ref(progs, a.get("program"))
    if pid is None:
        return None
    if typ == "restart_program":
        brief = " ".join(str(a.get("brief") or "").split())[:MAX_BRIEF]
        if len(brief) < 20:
            return None
        return {"type": typ, "program": pid, "brief": brief, "name": _text(a.get("name"), 120)}
    return {"type": typ, "program": pid}


def why_not(a: Any, known: dict[str, Any] | None = None, page: dict[str, Any] | None = None) -> str:
    """Why an app action was rejected, for the agentic loop."""
    if not isinstance(a, dict):
        return "an action must be an object with a type"
    typ = a.get("type")
    if typ == "navigate":
        return (f"'{a.get('to')}' is not an app page (use a pattern under Pages with an id that is listed; tabs: "
                f"{', '.join(PROGRAM_TABS)})")
    if typ == "point":
        return f"there is no control '{a.get('target')}' on this page (use an id or label exactly as listed)"
    if typ in ("studio_request", "stop_studio_agent"):
        if _ref(None if known is None else known.get("projects", {}), a.get("project")) is None:
            return f"there is no part project '{a.get('project')}' (use an id or exact name as listed)"
        return "the request text is missing"
    if typ in ("new_program", "new_part"):
        return "the brief must say what to make in at least a sentence"
    if _ref(None if known is None else known.get("programs", {}), a.get("program")) is None:
        return f"there is no program '{a.get('program')}' (use an id or exact name as listed)"
    return "the new brief must say what to make in at least a sentence"


def describe(a: dict[str, Any], known: dict[str, Any] | None = None) -> str:
    def nm(kind: str, i: str) -> str:
        return ((known or {}).get(kind, {}).get(i) or {}).get("name") or a.get(f"{kind[:-1]}_name") or "it"

    typ = a["type"]
    if typ == "navigate":
        return f"Open {a['to']}" + (f" and show {a['highlight']}" if a.get("highlight") else "")
    if typ == "point":
        return f"Show {a.get('label') or a['target']}" + (f": {a['note']}" if a.get("note") else "")
    if typ == "studio_request":
        return f"Open {nm('projects', a['project'])} in Design Studio with the request: {a['text']}"
    if typ == "stop_studio_agent":
        return f"Stop the design agent run on {nm('projects', a['project'])}"
    if typ == "new_part":
        return f"New part {a['name']}, opened in Design Studio with the brief ready to send"
    if typ == "new_program":
        return f"Start a new program {a['name']} from: {a['brief'][:200]}"
    if typ == "restart_program":
        return (f"Start {nm('programs', a['program'])} again from the new brief (the old program is paused and "
                f"kept): {a['brief'][:200]}")
    if typ == "heal_program":
        return (f"Repair {nm('programs', a['program'])}: queue half-done work again, heal review blocks, retry "
                "blocked parts and run the office")
    if typ == "rebuild_assembly":
        return f"Rebuild the program assembly of {nm('programs', a['program'])}"
    if typ == "run_program":
        return f"Run the office on {nm('programs', a['program'])}"
    return typ


def with_names(a: dict[str, Any], known: dict[str, Any]) -> dict[str, Any]:
    """Keep the names next to the ids, so the label stays readable after the list changes."""
    out = dict(a)
    if a.get("program") in known.get("programs", {}):
        out["program_name"] = known["programs"][a["program"]]["name"]
    if a.get("project") in known.get("projects", {}):
        out["project_name"] = known["projects"][a["project"]]["name"]
    return out


def studio_path(project: str, text: str) -> str:
    return f"/app/projects/{project}?ask={quote(text[:1500])}"


# --------------------------------------------------------------------------- without AI
_NAV = (
    (r"\b(new program|start a program)\b", "/app/office/new"),
    (r"\b(new part|new project)\b", "/app/projects?new=1"),
    (r"\b(billing|tokens?|top.?up|pay|plan|subscription|invoice)\b", "/app/billing"),
    (r"\b(team|invite|teammate|member)s?\b", "/app/team"),
    (r"\b(settings?|password|profile|preferences?)\b", "/app/settings"),
    (r"\b(help|guide|shortcuts?|support)\b", "/app/help"),
    (r"\b(office|programs?)\b", "/app/office"),
    (r"\b(modules?|drawings?|render|manufactur\w*|print)\b", "/app/modules"),
    (r"\b(projects?|parts?)\b", "/app/projects"),
)


def offline_reply(text: str, known: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """The common requests without AI: open a named program or part, or a page by its subject."""
    low = text.lower()
    for kind, base in (("programs", "/app/office/programs/"), ("projects", "/app/projects/")):
        hits = [(i, v) for i, v in known.get(kind, {}).items() if v["name"].lower() in low and len(v["name"]) >= 3]
        if hits:
            i, v = max(hits, key=lambda h: len(h[1]["name"]))
            return f"Opening {v['name']}.", [{"type": "navigate", "to": base + i}]
    for rx, to in _NAV:
        if re.search(rx, low):
            title = next(t for p, t, _w in PAGES if p == to.split("?")[0])
            return f"That is on {title}. Taking you there.", [{"type": "navigate", "to": to}]
    return ("AI replies are off here, so I can only take you to a page or a named program or part. Try \"open "
            "billing\", \"open the office\" or the name of a program."), []
