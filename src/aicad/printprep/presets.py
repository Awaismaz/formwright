"""Process presets: documented, editable defaults. Every value is an ASSUMPTION to adjust for the real printer.

Design-rule values (walls, holes, pins, clearances, bridges, overhang angle) follow the widely reproduced
"key design rules per 3D printing process" table published by 3D Hubs (now Protolabs Network), e.g.
https://www.hubs.com/knowledge-base/how-design-parts-3d-printing/ . They are generic guidance, not guarantees:
verify with your printer, material and service provider. Build volumes are generic desktop-class sizes; time-model
constants are rough averages chosen by us and are labelled estimates in the UI.
"""

from __future__ import annotations

from typing import Any

from aicad import materials

SOURCE = ("Design-rule defaults: 3D Hubs / Protolabs Network design-rules table (generic guidance). Build volume "
          "and time constants: generic assumptions. Verify every value for your printer and material.")

PROCESSES: dict[str, dict[str, Any]] = {
    "fdm": {
        "name": "FDM, 0.4 mm nozzle",
        "nozzle_mm": 0.4, "layer_mm": 0.2, "line_width_mm": 0.45,
        "min_wall_mm": 0.8, "warn_wall_mm": 1.2,
        "min_hole_mm": 2.0, "min_pin_mm": 3.0, "min_gap_mm": 0.5, "min_feature_mm": 2.0,
        "overhang_deg": 45.0, "max_bridge_mm": 10.0, "supports": True,
        "printer_mm": [220.0, 220.0, 250.0],
        "infill": 0.20, "shell_mm": 0.9, "support_density": 0.15,
        "flow_mm3_s": 6.0, "layer_overhead_s": 1.5,
        "materials": ["pla", "petg", "abs", "pa12"], "default_material": "pla",
        "anisotropic": True,
    },
    "sla": {
        "name": "SLA (resin)",
        "nozzle_mm": None, "layer_mm": 0.05, "line_width_mm": None,
        "min_wall_mm": 0.5, "warn_wall_mm": 1.0,
        "min_hole_mm": 0.5, "min_pin_mm": 0.5, "min_gap_mm": 0.5, "min_feature_mm": 0.2,
        "overhang_deg": 45.0, "max_bridge_mm": None, "supports": True,
        "printer_mm": [145.0, 145.0, 175.0],
        "infill": 1.0, "shell_mm": None, "support_density": None,
        "flow_mm3_s": None, "layer_overhead_s": 9.0,
        "materials": ["resin_standard"], "default_material": "resin_standard",
        "anisotropic": False,
    },
    "sls": {
        "name": "SLS (powder bed)",
        "nozzle_mm": None, "layer_mm": 0.1, "line_width_mm": None,
        "min_wall_mm": 0.7, "warn_wall_mm": 1.0,
        "min_hole_mm": 1.5, "min_pin_mm": 0.8, "min_gap_mm": 0.3, "min_feature_mm": 0.8,
        "overhang_deg": 45.0, "max_bridge_mm": None, "supports": False,
        "printer_mm": [165.0, 165.0, 300.0],
        "infill": 1.0, "shell_mm": None, "support_density": None,
        "flow_mm3_s": None, "layer_overhead_s": 12.0,
        "materials": ["pa12"], "default_material": "pa12",
        "anisotropic": False,
    },
}

NOTES = {
    "fdm": "Supports are needed under overhangs beyond the angle; short horizontal spans can bridge. Parts are "
           "weakest across layers (along print Z).",
    "sla": "Resin parts are normally printed on supports; the overhang map shows where support tips will land. "
           "Hollow parts need drain holes (not checked here).",
    "sls": "Powder supports the part, so no support structures are needed; orientation mainly drives build height "
           "and time. Enclosed cavities trap powder (not checked here).",
}

# Print-only material not in the shared library. Typical datasheet range for standard photopolymer resins is about
# 1.1-1.2 g/cm3 (cured); flagged to verify.
EXTRA_MATERIALS = [{"code": "resin_standard", "name": "Standard photopolymer resin (cured)", "group": "Resins",
                    "density_g_cm3": 1.15, "verify": True}]

EDITABLE = ("layer_mm", "min_wall_mm", "warn_wall_mm", "min_hole_mm", "min_pin_mm", "min_gap_mm", "overhang_deg",
            "max_bridge_mm", "infill", "flow_mm3_s", "layer_overhead_s", "nozzle_mm")


def material(code: str | None) -> dict[str, Any] | None:
    m = materials.get(code) or next((x for x in EXTRA_MATERIALS if x["code"] == code), None)
    return dict(m) if m else None


def process_settings(process: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    if process not in PROCESSES:
        raise ValueError("Unknown process")
    s = {**PROCESSES[process], "code": process}
    edited: list[str] = []
    for k, val in (overrides or {}).items():
        if k in EDITABLE and val is not None and s.get(k) is not None:
            s[k] = float(val)
            if float(val) != PROCESSES[process][k]:
                edited.append(k)
    s["edited"] = edited
    return s


def catalog() -> dict[str, Any]:
    mats = {}
    for p in PROCESSES.values():
        for c in p["materials"]:
            m = material(c)
            if m:
                mats[c] = {**m, "source": materials.SOURCE_NOTE}
    return {"processes": {k: {**v, "note": NOTES[k]} for k, v in PROCESSES.items()}, "materials": mats,
            "editable": list(EDITABLE), "source": SOURCE}
