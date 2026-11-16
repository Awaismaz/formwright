"""One staleness rule and one advice vocabulary for every downstream output of a part.

Outputs: the drawing sheet (Drawing Studio), the DFM analysis/report (Manufacturing Advisor), calculation sets
(Engineering Advisor) and print exports (3D Print Prep). Each output stores the **build stamp** it was made from
(``build_stamp``). The rule, applied identically in every module and in the Studio's Make tab:

* ``current``  the output was made from the current verified build;
* ``stale``    the model has changed since: show "Model changed since …" and a one-click update. Never replace an
               output silently and never let a stale output keep a higher advice level than it has earned;
* ``missing``  not produced yet.

On top of that, the **release** (shop handoff pack, ``aicad.handoff.issue``) freezes one build as revision A, B, …
Every module then compares the current build with the issued one ("Draft: changes since Rev A").

Advice levels follow docs/VALIDATION.md §4, plus ``measured`` for deterministic geometry measurements (a mesh is
watertight, a wall is 1.2 mm thick). ``verified_calculation`` is reserved for a calculation set signed by a named
engineer; a self-signed set is labelled "self-checked", a set signed by someone who did not author it "independent".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------------------------- advice levels
MEASURED = "measured"
RECOMMENDED = "recommended_check"
PRELIMINARY = "preliminary_estimate"
VERIFIED = "verified_calculation"
VALIDATED = "validated_simulation"
LEVEL_LABELS = {
    MEASURED: "Measured from the model",
    RECOMMENDED: "Recommended check",
    PRELIMINARY: "Preliminary estimate",
    VERIFIED: "Verified calculation",
    VALIDATED: "Validated simulation",
}


def verified_label(self_check: bool) -> str:
    """Badge text for a signed set: who checked it is part of the level, not small print."""
    return "Verified calculation · self-checked" if self_check else "Verified calculation · independent check"


# --------------------------------------------------------------------------------------------- build stamps
def read_status(ws: Path) -> dict[str, Any]:
    try:
        return json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def model_rev(ws: Path, build_id: Any) -> str | None:
    """Revision number (revisions/<n>) holding this build, else the latest revision."""
    root = ws / "revisions"
    if not root.is_dir():
        return None
    nums = sorted((int(d.name) for d in root.iterdir() if d.is_dir() and d.name.isdigit()), reverse=True)
    for n in nums:
        try:
            st = json.loads((root / str(n) / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        if build_id is not None and str(st.get("build_id")) == str(build_id):
            return str(n)
    return str(nums[0]) if nums else None


def build_stamp(ws: Path, status: dict[str, Any] | None = None) -> dict[str, Any]:
    """What an output records about the model it was made from."""
    st = read_status(ws) if status is None else status
    bid = st.get("build_id")
    return {"build_id": None if bid is None else str(bid), "step_sha256": st.get("step_sha256"),
            "material": st.get("material"), "model_rev": model_rev(ws, bid) if bid is not None else None}


def same_build(stamp: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    """Same build id, or the identical STEP file and material (a rebuild of unchanged geometry)."""
    if not stamp or not current.get("build_id"):
        return False
    if stamp.get("build_id") is not None and str(stamp["build_id"]) == str(current["build_id"]):
        return True
    return bool(stamp.get("step_sha256")) and stamp.get("step_sha256") == current.get("step_sha256") \
        and stamp.get("material") == current.get("material")


def freshness(stamp: dict[str, Any] | None, ws: Path, current: dict[str, Any] | None = None) -> dict[str, Any]:
    """``{"state": current|stale|missing, "made_from_rev", "current_rev"}`` for one output."""
    cur = current or build_stamp(ws)
    if not stamp:
        return {"state": "missing", "made_from_rev": None, "current_rev": cur.get("model_rev")}
    return {"state": "current" if same_build(stamp, cur) else "stale", "made_from_rev": stamp.get("model_rev"),
            "current_rev": cur.get("model_rev")}
