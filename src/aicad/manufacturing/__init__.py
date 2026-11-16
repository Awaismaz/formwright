"""Manufacturing Advisor: advisory DFM rules (CHK-13), turning and moulding checks, process ranking and a relative
cost model, computed on the exact B-rep of a project's verified build (`out/part.step`, face ids from `topo.json`).

Everything here is advisory. Measurements are deterministic and unit-tested; the limits they are compared with are
published design guidance or shop-profile inputs, never manufacturing approval.
"""

from __future__ import annotations

ANALYSER_VERSION = "mfg-1.0.0"

ADVICE_LEVELS = {
    "check": "Recommended check",
    "estimate": "Preliminary estimate",
    "verified": "Verified calculation",
}
