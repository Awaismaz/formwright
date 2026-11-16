"""Manufacturing Advisor: advisory DFM rules (CHK-13), turning, sheet-metal and moulding checks, process ranking and
a relative cost model, computed on the exact B-rep of a project's verified build (`out/part.step`, face ids from
`topo.json`).

Everything here is advisory. Measurements are deterministic and unit-tested; the limits they are compared with are
published design guidance or shop-profile inputs, never manufacturing approval. Advice levels follow
docs/VALIDATION.md §4 (`aicad.deliverables`): findings are a *Recommended check*, costs a *Preliminary estimate*;
nothing here is ever a "Verified calculation" (that level is reserved for a signed calculation set).
"""

from __future__ import annotations

from aicad import deliverables as _d

ANALYSER_VERSION = "mfg-1.1.0"

ADVICE_LEVELS = {
    "check": _d.LEVEL_LABELS[_d.RECOMMENDED],
    "estimate": _d.LEVEL_LABELS[_d.PRELIMINARY],
    "measured": _d.LEVEL_LABELS[_d.MEASURED],
}
