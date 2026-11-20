"""Hole Wizard standards: metric clearance, tapped, counterbored and countersunk holes for ISO fasteners.

Every number is a table value with its source, never a guess. Sizes match the Toolbox fastener tables
(`toolbox.METRIC`), so a hole made here fits the bolt the Toolbox makes. Values marked "verify" are common
practice rather than a single normative table: the app labels them so.
"""

from __future__ import annotations

from typing import Any

from aicad import toolbox

# ISO 273:1979 clearance holes for bolts and screws: d -> (fine H12, medium H13, coarse H14) hole Ø, mm
CLEARANCE = {3: (3.2, 3.4, 3.6), 4: (4.3, 4.5, 4.8), 5: (5.3, 5.5, 5.8), 6: (6.4, 6.6, 7.0), 8: (8.4, 9.0, 10.0),
             10: (10.5, 11.0, 12.0), 12: (13.0, 13.5, 14.5), 16: (17.0, 17.5, 18.5), 20: (21.0, 22.0, 24.0),
             24: (25.0, 26.0, 28.0)}
FITS = ("fine", "medium", "coarse")
# ISO 261 coarse pitch P, and the usual tap drill (about d - P; cf. ISO 2306), mm
PITCH = {3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75, 16: 2.0, 20: 2.5, 24: 3.0}
TAP_DRILL = {3: 2.5, 4: 3.3, 5: 4.2, 6: 5.0, 8: 6.8, 10: 8.5, 12: 10.2, 16: 14.0, 20: 17.5, 24: 21.0}
# DIN 974-1 counterbore Ø for ISO 4762 socket head cap screws (no washer), mm
CBORE_D = {3: 6.5, 4: 8.0, 5: 10.0, 6: 11.0, 8: 15.0, 10: 18.0, 12: 20.0, 16: 26.0, 20: 33.0, 24: 40.0}
CBORE_ALLOWANCE = 0.4  # depth = ISO 4762 head height k + this, so the head sits just below the face (verify)
# ISO 10642 countersunk socket screw: theoretical head Ø dk (90° countersink), mm
CSK_D = {3: 6.72, 4: 8.96, 5: 11.2, 6: 13.44, 8: 17.92, 10: 22.4, 12: 26.88, 16: 33.6, 20: 40.32}

SOURCES = {
    "clearance": "ISO 273 clearance holes (fine H12 / medium H13 / coarse H14)",
    "tapped": "ISO 261 coarse pitch; tap drill ≈ d − P (common practice, cf. ISO 2306); verify for your tap",
    "cbore": "Counterbore Ø per DIN 974-1 for ISO 4762 cap screws; depth = head height k (ISO 4762) + 0.4 mm; verify",
    "csk": "90° countersink to the ISO 10642 head Ø (theoretical); verify for your screw",
    "washer": "ISO 7089 plain washer outside Ø",
    "edge": "Edge distance guidance: at least 1.5 × d is a common design rule; EN 1993-1-8 Table 3.3 gives "
            "1.2 × hole Ø as the minimum for steel. Guidance only, not a strength check.",
}


class HoleError(ValueError):
    pass


def _size(v: Any) -> int:
    try:
        d = int(float(v))
    except (TypeError, ValueError):
        raise HoleError("Choose a thread size (M3 to M24)") from None
    if float(v) != d or d not in CLEARANCE:
        raise HoleError(f"M{v} isn't in the hole tables; choose M3 to M24")
    return d


def resolve(spec: Any) -> dict[str, Any]:
    """Hole feature fields for a Hole Wizard spec {"type", "size", "fit"}: drill Ø `d`, plus `cbore` / `csk`."""
    if not isinstance(spec, dict) or spec.get("type") not in ("clearance", "tapped", "cbore", "csk"):
        raise HoleError("Hole type must be clearance, tapped, counterbore or countersink")
    t, d = spec["type"], _size(spec.get("size"))
    fit = spec.get("fit", "medium")
    if fit not in FITS:
        raise HoleError("Clearance fit must be fine, medium or coarse")
    out: dict[str, Any] = {"spec": {"type": t, "size": d, "fit": fit}}
    clear = CLEARANCE[d][FITS.index(fit)]
    if t == "clearance":
        out["d"] = clear
    elif t == "tapped":
        out["d"] = TAP_DRILL[d]
        out["spec"]["pitch"] = PITCH[d]
    elif t == "cbore":
        out["d"] = clear
        out["cbore"] = {"d": CBORE_D[d], "depth": round(toolbox.SHCS[d][1] + CBORE_ALLOWANCE, 3)}
    else:
        if d not in CSK_D:
            raise HoleError(f"No ISO 10642 countersunk screw in M{d}; choose M3 to M20")
        out["d"] = clear
        out["csk"] = {"d": CSK_D[d], "angle": 90.0}
    out["spec"]["label"] = label(out)
    return out


def label(f: dict[str, Any]) -> str:
    s = f["spec"]
    m = f"M{s['size']:g}"
    if s["type"] == "tapped":
        return f"{m}×{s['pitch']:g} tapped (Ø{f['d']:g} drill)"
    base = f"{m} clearance Ø{f['d']:g} ({s['fit']})"
    if s["type"] == "cbore":
        return f"{base}, counterbore Ø{f['cbore']['d']:g} × {f['cbore']['depth']:g}"
    if s["type"] == "csk":
        return f"{base}, countersink Ø{f['csk']['d']:g} × 90°"
    return base


def tables() -> dict[str, Any]:
    """Everything the Hole Wizard shows, for the app (one source of truth)."""
    sizes = sorted(CLEARANCE)
    return {
        "sizes": sizes, "fits": list(FITS),
        "clearance": {d: dict(zip(FITS, CLEARANCE[d], strict=True)) for d in sizes},
        "tap_drill": TAP_DRILL, "pitch": PITCH, "cbore_d": CBORE_D,
        "cbore_depth": {d: round(toolbox.SHCS[d][1] + CBORE_ALLOWANCE, 3) for d in sizes},
        "csk_d": CSK_D, "washer_od": {d: toolbox.WASHER[d][1] for d in sizes},
        "sources": SOURCES,
    }
