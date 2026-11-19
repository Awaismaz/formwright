"""AGT-001: the typed contract every language-model provider implements (ADR-009, revised by ADR-013).

Two kinds of model work exist in Formwright:

* **Agent sessions** (the Design Studio agent): a tool-using loop with file tools, our ``build_model`` tool, hooks
  and resumable sessions. ``LLMProvider.agent_client(options)`` returns an object with the ``ClaudeSDKClient``
  surface (``connect / query / receive_response / interrupt / disconnect``) that yields the Claude Agent SDK's
  message dataclasses. Those dataclasses are the session's message vocabulary: any provider that supports sessions
  produces them (the replay and stub providers construct them directly), so ``AgentSession`` never changes.
* **Single calls** (planner, reviewers, vision reads, prompt polish, drafting assist, librarian, merge reconcile):
  ``await provider.complete(CallRequest(...))`` returns text, optionally schema-validated JSON (``schema=``), with
  images attached (``images=``), and a ``Metering`` record (tokens, cost, model id, latency).

Every call is metered through ``aicad.llm.metering`` (structured log line + in-process listeners). Which provider
serves which role is configuration (``FW_LLM_PROVIDERS``), never something the UI shows.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar

# Roles: one per place the product calls a model. Config may route each role to a different provider.
ROLES: tuple[str, ...] = (
    "design_agent",   # Design Studio agent session (agent/session.py)
    "planner",        # Design Office: Archie's program plan (office/planner.run_agent)
    "change_review",  # Design Office: Archie on an ICD change request (office/planner.run_cr_review)
    "reviewer",       # Design Office: Gage's part review (office/gage.run_review)
    "vision",         # Image to CAD: reading drawings / sketches / photos (image2cad/vision.run_agent)
    "render_refine",  # AI Render Studio: prompt polish (airender/refine.run_refiner_agent)
    "draft_assist",   # 2D drafting assist (drawing/draft_assist.run_agent)
    "librarian",      # Assembly librarian: parts list reading (assembly/librarian.ask_ai)
    "reconcile",      # Branch merge: conflict reconciliation (platform/collab/reconcile.propose)
    "office_chat",    # Design Office: talking to Archie during a program (office/archie_chat, CD-026)
    "assembly_check", # visual assembly check: one look at the 4-view picture (assembly/visual.ask, PD-73)
    "supervisor",     # Design Office: Archie supervising a running program (office/supervisor.run_supervisor), Opus
)

# Capability names a provider declares (contract tests are gated on them).
CAP_COMPLETE = "complete"
CAP_STRUCTURED = "structured"
CAP_VISION = "vision"
CAP_AGENT = "agent_session"

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp"}


class ProviderError(RuntimeError):
    """The provider could not serve the call (unavailable, misconfigured, refused in this environment)."""


class CapabilityError(ProviderError):
    """The provider does not support what the request needs (e.g. agent sessions, vision)."""


class StructuredOutputError(ProviderError):
    """The model's answer did not contain JSON that validates against the requested schema."""

    def __init__(self, message: str, text: str = "") -> None:
        super().__init__(message)
        self.text = text


@dataclass
class CallRequest:
    """One single-shot model call. ``system`` is the role's instructions, ``prompt`` the user turn."""

    role: str
    system: str
    prompt: str
    images: tuple[Path, ...] = ()
    schema: dict[str, Any] | None = None  # JSON Schema: the answer must validate (see ``CallResult.data``)
    max_turns: int = 1  # agent-harness providers: turns allowed (vision reads need >1 to open the image)
    budget_usd: float | None = None  # hard cap where the provider supports one
    cwd: Path | None = None  # scratch folder for harness providers (images must be inside it)
    max_tokens: int = 16000  # API providers: output cap (thinking counts toward it)
    model: str | None = None  # None = the provider's default for the role
    standalone_system: bool = False  # harness providers: ``system`` replaces the harness's own instructions
    effort: str | None = None  # "low" | "medium" | "high": reasoning effort where the provider supports it

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"unknown model role {self.role!r}")
        self.images = tuple(Path(p) for p in self.images)
        for p in self.images:
            if p.suffix.lower() not in IMAGE_TYPES:
                raise ValueError(f"unsupported image type: {p.suffix}")


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @classmethod
    def from_any(cls, u: Any) -> Usage:
        """From a dict (SDK / JSON) or an object with token attributes (API SDK response usage)."""
        if u is None:
            return cls()

        def g(k: str) -> int:
            v = u.get(k) if isinstance(u, dict) else getattr(u, k, None)
            return int(v) if isinstance(v, int | float) and not isinstance(v, bool) else 0

        return cls(g("input_tokens"), g("output_tokens"), g("cache_creation_input_tokens"),
                   g("cache_read_input_tokens"))

    @property
    def total(self) -> int:
        return (self.input_tokens + self.output_tokens + self.cache_creation_input_tokens
                + self.cache_read_input_tokens)

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class Metering:
    """What one call cost. ``cost_source``: ``reported`` (the provider's own figure), ``estimated`` (list prices
    applied to the token counts, ``agent/pricing.py``) or ``none`` (a provider that bills nothing)."""

    provider: str
    role: str
    model: str | None
    usage: Usage = field(default_factory=Usage)
    cost_usd: float | None = None
    cost_source: str = "none"
    latency_s: float = 0.0
    ok: bool = True

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["usage"] = self.usage.as_dict()
        return d


@dataclass
class CallResult:
    text: str
    metering: Metering
    data: Any = None  # parsed and validated JSON when the request carried a schema


class LLMProvider(ABC):
    """A model provider. Subclasses implement ``_complete`` and, when they support sessions, ``agent_client``."""

    name: ClassVar[str] = "abstract"
    capabilities: ClassVar[frozenset[str]] = frozenset()
    dev_only: ClassVar[bool] = False  # refused when FW_ENV=production

    def supports(self, cap: str) -> bool:
        return cap in self.capabilities

    async def complete(self, req: CallRequest) -> CallResult:
        """One call: text (+ validated JSON when ``req.schema``), metered. Never raises on metering problems."""
        import time

        from aicad.llm import metering

        if not self.supports(CAP_COMPLETE):
            raise CapabilityError(f"{self.name} does not support single calls")
        if req.images and not self.supports(CAP_VISION):
            raise CapabilityError(f"{self.name} does not accept images")
        if req.schema is not None and not self.supports(CAP_STRUCTURED):
            raise CapabilityError(f"{self.name} does not support structured output")
        t0 = time.perf_counter()
        try:
            res = await self._complete(req)
        except Exception:
            metering.emit(Metering(self.name, req.role, req.model, latency_s=time.perf_counter() - t0, ok=False))
            raise
        res.metering.latency_s = round(time.perf_counter() - t0, 4)
        if req.schema is not None and res.data is None:
            try:
                res.data = parse_json_answer(res.text, req.schema)
            except StructuredOutputError:
                res.metering.ok = False
                metering.emit(res.metering)
                raise
        metering.emit(res.metering)
        return res

    @abstractmethod
    async def _complete(self, req: CallRequest) -> CallResult:
        """Provider-specific call. May fill ``data`` itself (native structured output); else it is parsed."""

    def agent_client(self, options: Any) -> Any:
        """A ``ClaudeSDKClient``-shaped client for the Design Studio session (``options``: ``ClaudeAgentOptions``)."""
        raise CapabilityError(f"{self.name} does not support agent sessions")


# ------------------------------------------------------------------ structured output helpers
def schema_instruction(schema: dict[str, Any]) -> str:
    """Appended to the system text by providers without native structured output."""
    return ("\n\nAnswer with exactly one fenced ```json block containing a single JSON value that validates "
            "against this JSON Schema, and nothing after it:\n" + json.dumps(schema, sort_keys=True))


_FENCE = re.compile(r"```[\w-]*\s*\n(.*?)\n?```", re.DOTALL)


def parse_json_answer(text: str, schema: dict[str, Any]) -> Any:
    """The last fenced (or bare) JSON value in ``text``, validated against ``schema``."""
    import jsonschema

    candidates = [m for m in _FENCE.findall(text or "")][::-1] + [(text or "").strip()]
    errors: list[str] = []
    for raw in candidates:
        try:
            value = json.loads(raw)
        except ValueError:
            s, e = raw.find("{"), raw.rfind("}")
            if s < 0 or e <= s:
                continue
            try:
                value = json.loads(raw[s:e + 1])
            except ValueError:
                continue
        try:
            jsonschema.validate(value, schema)
        except jsonschema.ValidationError as ex:
            errors.append(ex.message)
            continue
        return value
    raise StructuredOutputError("the answer did not contain JSON matching the schema"
                                + (f" ({errors[0]})" if errors else ""), text)


def image_hint(req: CallRequest) -> str:
    """For harness providers that read images with a file tool: name any image the prompt does not mention."""
    missing = [p.name for p in req.images if p.name not in req.prompt]
    if not missing:
        return ""
    names = ", ".join(f"`{n}`" for n in missing)
    return f"Open the image file(s) {names} in the current folder with the Read tool and study them.\n\n"
