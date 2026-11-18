"""Specialist part agents (CD-007): what each one is told, and how its work reads on the board.

A specialist is the normal Design Studio agent working in the ticket's own Studio project, given the ticket brief
plus a short practice note for its trade. Nothing here talks to a model: ``prompt`` builds the message, ``line``
turns run progress into a present-tense status line in machinist language (plain words, never internals).
"""

from __future__ import annotations

from typing import Any

DESIGNERS = ("mill", "chuck", "axel", "benny", "molly")

PRACTICE: dict[str, str] = {
    "mill": ("You are Mill, the machined-parts specialist. Design prismatic parts the way a CNC shop makes them: "
             "a stock envelope, pockets and through holes from one or two setups, standard drill and tap sizes, "
             "inside corner radii a cutter can reach, and edge breaks noted rather than modelled when small."),
    "chuck": ("You are Chuck, the turned-parts specialist. Design lathe parts as a revolved profile on one axis: "
              "shoulders, grooves, chamfers and undercuts on the profile; keyways and cross holes as second "
              "operations. Keep diameters on standard sizes and bearing seats exactly as the brief gives them."),
    "axel": ("You are Axel, the gears and drives specialist. Use the Toolbox gear and pulley generators for tooth "
             "forms (module, tooth count, face width, bore) instead of drawing teeth by hand; add hubs, keyways "
             "and set-screw holes around them."),
    "benny": ("You are Benny, the sheet-metal specialist. Sheet-metal tools are not yet supported in this app, so "
              "design the part as a machined solid of the blank thickness with the bends as solid radii, and say "
              "clearly in your answer that the flat pattern and bend allowances are not modelled."),
    "molly": ("You are Molly, the plastic-parts specialist. Design moulded parts with a uniform nominal wall, "
              "draft on faces parallel to the pull direction (1 to 2 degrees), ribs at about 60 % of the wall, "
              "bosses cored out, and generous radii; say which faces carry draft."),
}

CLOSING = ("This is a Design Office ticket: the brief below is already approved, so build it now without asking for "
           "approval. Keep every size the brief gives exactly, put the driving dimensions in PARAMS, and finish "
           "with your self-review. An independent checker will measure the part against the brief afterwards.")

# Present-tense status lines per trade: (reading, first build, rebuild, fixing, checks pass, self-review)
_LINES: dict[str, tuple[str, str, str, str, str, str]] = {
    "mill": ("Mill is reading the brief for {p}", "Mill is roughing out {p}", "Mill is pocketing {p}",
             "Mill is re-cutting {p}: a check failed", "{p} passes the gating checks: Mill is deburring",
             "Mill is measuring {p} against the brief"),
    "chuck": ("Chuck is reading the brief for {p}", "Chuck is turning {p}", "Chuck is facing and grooving {p}",
              "Chuck is re-turning {p}: a check failed", "{p} passes the gating checks: Chuck is chamfering",
              "Chuck is miking {p} against the brief"),
    "axel": ("Axel is reading the brief for {p}", "Axel is hobbing {p}", "Axel is cutting the hub of {p}",
             "Axel is re-hobbing {p}: a check failed", "{p} passes the gating checks: Axel is checking the mesh",
             "Axel is checking {p} against the brief"),
    "benny": ("Benny is reading the brief for {p}", "Benny is cutting the blank for {p}", "Benny is bending {p}",
              "Benny is re-bending {p}: a check failed", "{p} passes the gating checks: Benny is flattening burrs",
              "Benny is checking {p} against the brief"),
    "molly": ("Molly is reading the brief for {p}", "Molly is filling the cavity for {p}",
              "Molly is adding draft and ribs to {p}", "Molly is re-moulding {p}: a check failed",
              "{p} passes the gating checks: Molly is trimming the gates", "Molly is checking {p} against the brief"),
}
STAGES = ("reading", "first_build", "rebuild", "fixing", "checks_pass", "self_review")


def name(code: str) -> str:
    from aicad.office import roster

    return roster.agent(code)["name"]


def line(code: str, stage: str, part: str, agent_label: str | None = None) -> str:
    lines = _LINES.get(code, _LINES["mill"])
    text = lines[STAGES.index(stage)].format(p=part)
    if agent_label and agent_label != name(code):
        text = text.replace(name(code), agent_label, 1)
    return text


def prompt(code: str, ticket: dict[str, Any], *, feedback: list[str] | None = None,
           comments: list[dict[str, Any]] | None = None, full: bool = True, resume: bool = False) -> str:
    """The message to the part agent. ``full``: its practice note and the brief (first turn, or a fresh session);
    later turns carry only the checker's findings or the engineer's comments."""
    parts: list[str] = []
    if feedback:
        parts.append("The independent checker (Gage) sent this part back. Fix every finding, rebuild, and finish "
                     "with your self-review:\n" + "\n".join(f"- {f}" for f in feedback))
    if comments:
        parts.append("Comments from the engineering manager on this ticket. Act on them, rebuild if the model "
                     "changes, and finish with your self-review:\n"
                     + "\n".join(f"- {c['by'].get('name', 'Engineer')}: {c['text']}" for c in comments))
    if not full:
        return "\n\n".join(parts) or "Continue the ticket and finish with your self-review."
    head = [PRACTICE.get(code, PRACTICE["mill"]), CLOSING]
    if resume:
        head.append("The previous session was interrupted. Continue from the current model if there is one.")
    return "\n\n".join(head + [f"Ticket {ticket['key']}: {ticket['brief']}"] + parts)


def shown(ticket: dict[str, Any], agent_label: str, *, feedback: bool = False, comments: bool = False) -> str:
    """What the Studio chat shows as the request (the practice note is not shown)."""
    if feedback:
        return f"Design Office: Gage sent {ticket['key']} {ticket['title']} back to {agent_label} with findings."
    if comments:
        return f"Design Office: new comments on {ticket['key']} {ticket['title']} for {agent_label}."
    return f"Design Office ticket {ticket['key']} for {agent_label}: {ticket['brief'].split(chr(10))[0]}"
