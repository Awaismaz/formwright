"""Design Office (plan docs/plans/CHIEF_DESIGNER.md): programs, the Chief Designer (Archie), tickets on a Jira-style
board, estimates with effort-weighted roll-up, and the agent roster.

Pure-Python, no kernel imports:
  ``roster``     the named agents (Archie, Mill, Chuck, ...), part families and who owns which family
  ``estimates``  every estimating constant in one place, milestone progress, roll-up, critical path and ETA ranges
  ``planner``    Archie: brief -> decomposition (AI with a strict fenced block, plus a deterministic fallback)
  ``store``      per-organisation program documents and their event log (JSON files, atomic writes)
  ``service``    program operations (plan, approve, move, milestones, comments, links) and the live event bus

Phase 3 (the orchestrator) plugs in through ``service``: it moves tickets, sets milestones and emits events with an
``agent`` actor, exactly as the manual board does today.
"""


class OfficeInputError(ValueError):
    """A problem the user can fix (shown as-is)."""
