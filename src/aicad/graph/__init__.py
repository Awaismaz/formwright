"""The design graph (architecture v2, step 1; docs/architecture/design-graph.md).

AI at the edges, determinism in the middle: the intent compiler (``intent``) turns a brief into a typed graph of
components, connections and parameters through a strict schema; code validates and repairs it (``validate``), sizes it
from standards (``resolve``, ``standards``) and compiles it to what runs today (``compile``: the Design Office plan and
ICD, the direct builder, Fitz's trains). ``adapt`` reads an approved plan and ICD back into a graph. ``office`` is the
Design Office hook behind ``FW_DESIGN_GRAPH=1``.
"""

from __future__ import annotations

from aicad.graph.model import (
    SCHEMA,
    VERSION,
    Component,
    Connection,
    Constraints,
    DesignGraph,
    Param,
    Question,
)

__all__ = ["SCHEMA", "VERSION", "Component", "Connection", "Constraints", "DesignGraph", "Param", "Question"]
