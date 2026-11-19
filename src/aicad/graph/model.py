"""The design graph schema (architecture v2, step 1; docs/architecture/design-graph.md).

One typed, versioned document describes a mechanical design: its **components** (a shaft, a spur gear, a key, a
bearing, a housing ...), the **connections** between them (a keyed hub on a shaft, a bearing on a journal, a gear
mesh, a bolted joint, a seat against a shoulder ...), and the **parameters** that size them. Everything downstream
(the Design Office plan and ICD, the direct builder, Fitz's trains) is compiled from it by code.

Values carry their provenance (``Param.source``): ``brief`` (written in the brief), ``answer`` (the engineer chose
it), ``standard`` (a standards table sized it: DIN 6885, ISO 15, DIN 471, ISO 286 ...), ``rule`` (a stated design
rule: centre distance, face width 10 m, shoulder step), ``assumed`` (a default, said so) and ``layout`` (read back from
the solved layout). Nothing in this module calls a model or the CAD kernel.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA = "fw-design-graph"
VERSION = 1

Source = Literal["brief", "answer", "standard", "rule", "assumed", "layout", "plan"]
Value = float | int | str | bool


class Param(BaseModel):
    """One parameter value and where it came from."""

    model_config = ConfigDict(extra="forbid")
    value: Value
    source: Source = "brief"
    note: str = ""  # e.g. "DIN 6885-1 for Ø20"


class Component(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str
    name: str
    qty: int = Field(1, ge=1, le=500)
    group: str = ""            # the sub-assembly it is assembled in ("" = the design's single group)
    material: str = ""
    params: dict[str, Param] = Field(default_factory=dict)
    implied: bool = False      # added by code because a connection needs it (a key for a keyed hub)

    def v(self, name: str, default: Any = None) -> Any:
        p = self.params.get(name)
        return default if p is None else p.value

    def set(self, name: str, value: Value, source: Source, note: str = "", *, force: bool = False) -> None:
        """Set a value unless one with a stronger source is already there (brief / answer win over code)."""
        cur = self.params.get(name)
        if cur is not None and not force and cur.source in ("brief", "answer", "plan"):
            return
        self.params[name] = Param(value=value, source=source, note=note)


class Connection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str
    host: str                  # the side that carries (the shaft for a hub, the housing for a bearing seat)
    guest: str                 # the side that is carried / located
    via: list[str] = Field(default_factory=list)  # the parts that make the joint (a key, fasteners, a ring)
    params: dict[str, Param] = Field(default_factory=dict)

    def v(self, name: str, default: Any = None) -> Any:
        p = self.params.get(name)
        return default if p is None else p.value


class Question(BaseModel):
    """A clarifying question in the fw-questions MCQ format (``agent/session.extract_questions``)."""

    model_config = ConfigDict(extra="forbid")
    id: str
    question: str
    options: list[str]
    default: str | None = None
    multi: bool = False
    why: str = ""              # what changes with the answer (shown under the question)


class Constraints(BaseModel):
    """What the brief rules in and out (``office/scope.py``): hard constraints, never overridden by the AI."""

    model_config = ConfigDict(extra="forbid")
    named: list[str] = Field(default_factory=list)      # kinds of part the brief names (scope kinds)
    excluded: list[str] = Field(default_factory=list)   # kinds it excludes ("no housing", "without bearings")
    exclusive: bool = False                              # "just", "only", "no extra items"


class DesignGraph(BaseModel):
    schema_: str = Field(SCHEMA, alias="schema")
    version: int = VERSION
    name: str = ""
    brief: str = ""
    summary: str = ""
    units: Literal["mm"] = "mm"
    components: list[Component] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)
    assumptions: list[str] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    answers: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)       # what code changed (exclusions, implied parts), plain words
    source: str = "intent"                               # intent | plan | manual
    layout: dict[str, Any] = Field(default_factory=dict)  # solved positions, read back from the skeleton

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # ----------------------------------------------------------------- lookups
    def comp(self, cid: str) -> Component | None:
        return next((c for c in self.components if c.id == cid), None)

    def of_kind(self, *kinds: str) -> list[Component]:
        return [c for c in self.components if c.kind in kinds]

    def links(self, cid: str, kind: str | None = None) -> list[Connection]:
        return [c for c in self.connections if (c.host == cid or c.guest == cid or cid in c.via)
                and (kind is None or c.kind == kind)]

    def new_id(self, base: str) -> str:
        ids = {c.id for c in self.components}
        stem = slug(base) or "part"
        if stem not in ids:
            return stem
        n = 2
        while f"{stem}_{n}" in ids:
            n += 1
        return f"{stem}_{n}"

    def next_connection_id(self) -> str:
        n = len(self.connections) + 1
        ids = {c.id for c in self.connections}
        while f"c{n}" in ids:
            n += 1
        return f"c{n}"

    # ----------------------------------------------------------------- (de)serialisation
    def dump(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")

    @classmethod
    def load(cls, data: dict[str, Any]) -> DesignGraph:
        if data.get("schema", SCHEMA) != SCHEMA:
            raise ValueError("not a design graph")
        if int(data.get("version", VERSION)) > VERSION:
            raise ValueError(f"design graph version {data.get('version')} is newer than this code ({VERSION})")
        return cls.model_validate(data)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:40]
