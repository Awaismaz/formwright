"""PD-82: model routing by job size (founder decision 2026-11-19, docs/reports/agent-latency.md).

"For smaller jobs, use Sonnet or even Haiku, while major orchestration is done by Opus." Every model call names a
role (``llm.base.ROLES``); the design agent also names the size of the job (``agent.speed.job_of``):

  complex  new or open-ended geometry, gears, housings, mechanisms, many features, large programs   -> Opus
  simple   one fully dimensioned simple part, or a part in a small Design Office program           -> tier below
  edit     a local change to an existing design in the Studio                                       -> tier below

A cheaper tier is a default only where the agent-latency benchmark measured the same gate pass rate as Opus; every
other route stays on Opus (``DEFAULT_ROUTES`` says which and why). The platform config overrides any route:
``FW_LLM_MODELS="design_agent.simple=opus,reviewer=haiku"`` (role or role.job = tier name, a full ``claude-...``
model id, or ``default`` for the provider's own default). Server-side only; the UI never names a model.
"""

from __future__ import annotations

TIERS: dict[str, str] = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}
JOBS = ("complex", "simple", "edit")

# role[.job] -> tier. Evidence for each cheaper tier is in docs/reports/agent-latency.md.
DEFAULT_ROUTES: dict[str, str] = {
    "design_agent.complex": "opus",   # novel or complex geometry
    "design_agent.simple": "sonnet",  # benchmark: same pass rate as Opus on the simple cases (agent-latency)
    "design_agent.edit": "sonnet",    # benchmark: same pass rate as Opus on the edit case (agent-latency)
    "planner": "opus",                # Archie: program planning and intent
    "intent": "opus",                 # design graph from a brief (graph/intent.py): programs, mechanisms
    "intent.complex": "opus",
    "intent.simple": "sonnet",        # a shaft and what rides on it: docs/reports/design-graph.md (same graph)
    "change_review": "opus",          # Archie: ICD change requests
    "office_chat": "opus",            # Archie in the program chat (orchestration)
    "supervisor": "opus",             # Archie supervising a running program (office/supervisor, WORKLIST 49)
    "reconcile": "opus",
    "vision": "opus",                 # reading drawings and photos to geometry
    "reviewer": "opus",               # Gage's note can send a part back: Haiku not benchmarked yet (parked)
    "librarian": "opus",              # parts-list parsing: Haiku not benchmarked yet (parked)
    "assembly_check": "haiku",        # PD-73: measured on the visual check (assembly/visual.py uses the alias)
    "assembly_agent": "opus",         # Assembly Studio chat (WORKLIST 51, PD-170): job size from assembly/chat.job_of
    "assembly_agent.complex": "opus",  # assemble everything, several kinds of work at once, a part with no sizes
    "assembly_agent.simple": "sonnet",  # bring, mate, check, a sized part, an edit
    "render_refine": "opus",
    "draft_assist": "opus",
}


def parse(text: str) -> dict[str, str]:
    """``"design_agent.edit=sonnet, reviewer=haiku"`` -> {key: model or ""} (validated; "" = provider default)."""
    from aicad.llm.base import ROLES

    out: dict[str, str] = {}
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        key, sep, val = (s.strip() for s in part.partition("="))
        role, _, job = key.partition(".")
        if not sep or role not in ROLES or (job and job not in JOBS):
            raise ValueError(f"FW_LLM_MODELS: unknown route {key!r}")
        v = val.lower()
        if v not in TIERS and v != "default" and not v.startswith("claude-"):
            raise ValueError(f"FW_LLM_MODELS: unknown model {val!r} (opus, sonnet, haiku, default or a claude- id)")
        out[key] = "" if v == "default" else TIERS.get(v, val)
    return out


def _configured() -> dict[str, str]:
    try:
        from aicad.platform.config import get_settings

        return parse(get_settings().llm_models)
    except ValueError:
        import logging

        logging.getLogger("aicad.llm").warning("FW_LLM_MODELS ignored", exc_info=True)
        return {}


def model_for(role: str, job: str | None = None) -> str | None:
    """The model id for a call of ``role`` (and job size), or None for the provider's default."""
    cfg = _configured()
    keys = [f"{role}.{job}", role] if job else [role]
    for k in keys:
        if k in cfg:
            return cfg[k] or None
    for k in keys:
        if k in DEFAULT_ROUTES:  # Opus is every provider's default model: leave the call unchanged
            return None if DEFAULT_ROUTES[k] == "opus" else TIERS[DEFAULT_ROUTES[k]]
    return None


def tier_of(model: str | None) -> str:
    """'opus' / 'sonnet' / 'haiku' / 'default' for a model id or alias (run records, reports)."""
    m = (model or "").lower()
    return next((t for t in TIERS if t in m), "default" if not m else m)


def describe() -> dict[str, str]:
    """Effective routes (super-admin console)."""
    from aicad.llm.base import ROLES

    keys = [f"design_agent.{j}" for j in JOBS] + [r for r in ROLES if r != "design_agent"]
    return {k: model_for(*k.split(".", 1)) or "opus (default)" for k in keys}
