"""Shop profile (MFG-015): the machines, tooling limits, rates and cost assumptions DFM advice is checked against.

Stored per organisation as JSON (`<workspaces>/<org>/manufacturing/shop_profile.json`). Until a workspace saves its
own, the defaults below apply; every default is an assumption and is labelled as such in the UI and report.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

MachineKind = Literal["mill3", "mill5", "lathe", "printer_fdm", "printer_sla", "printer_sls"]
CLASSES = ("aluminium", "steel", "stainless", "cast_iron", "titanium", "copper", "plastic")
# Assumed roughing removal rates on a mid-size 3-axis VMC (cm^3/min). They vary 3-5x with machine, tooling and
# strategy: replace them with your shop's numbers.
DEFAULT_MRR = {"aluminium": 40.0, "plastic": 40.0, "copper": 25.0, "cast_iron": 15.0, "steel": 12.0,
               "stainless": 7.0, "titanium": 4.0}


class Machine(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: MachineKind
    travel_mm: list[float] | None = None  # mills: X, Y, Z travel; printers: build volume
    max_diameter_mm: float | None = Field(default=None, gt=0, le=5000)  # lathes: max turning diameter
    max_length_mm: float | None = Field(default=None, gt=0, le=20000)  # lathes: max turning length
    rate_per_hour: float = Field(ge=0, le=10000)

    @field_validator("travel_mm")
    @classmethod
    def _travel(cls, v: list[float] | None) -> list[float] | None:
        if v is not None and (len(v) != 3 or any(not (0 < x <= 20000) for x in v)):
            raise ValueError("travel must be three positive values in mm")
        return v


def _default_machines() -> list[Machine]:
    return [
        Machine(name="3-axis vertical machining centre", kind="mill3", travel_mm=[760, 410, 510], rate_per_hour=75),
        Machine(name="2-axis CNC lathe", kind="lathe", max_diameter_mm=250, max_length_mm=500, rate_per_hour=65),
        Machine(name="FDM printer", kind="printer_fdm", travel_mm=[250, 210, 210], rate_per_hour=6),
        Machine(name="SLA printer", kind="printer_sla", travel_mm=[145, 145, 175], rate_per_hour=10),
        Machine(name="SLS printer", kind="printer_sls", travel_mm=[300, 300, 300], rate_per_hour=25),
    ]


class ShopProfile(BaseModel):
    name: str = Field(default="Default shop (assumed values)", max_length=120)
    currency: str = Field(default="USD", min_length=1, max_length=8)
    machines: list[Machine] = Field(default_factory=_default_machines, max_length=40)
    # tooling and DFM limits
    smallest_tool_d_mm: float = Field(default=3.0, gt=0, le=100)
    max_tool_reach_mm: float = Field(default=50.0, gt=0, le=1000)  # tool end below the top of the part
    max_flank_mm: float = Field(default=25.0, gt=0, le=1000)  # wall height cut with the tool flank (flute length)
    max_drill_ld: float = Field(default=4.0, gt=0, le=100)
    deep_drill_ld: float = Field(default=10.0, gt=0, le=200)
    min_wall_metal_mm: float = Field(default=0.8, gt=0, le=50)
    min_wall_plastic_mm: float = Field(default=1.5, gt=0, le=50)
    min_draft_deg: float = Field(default=1.0, ge=0, le=15)
    # time and cost assumptions
    setup_minutes: float = Field(default=30.0, ge=0, le=10000)
    programming_minutes: float = Field(default=60.0, ge=0, le=100000)
    mrr_cm3_min: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_MRR))
    turning_mrr_factor: float = Field(default=2.0, gt=0, le=20)
    finish_cm2_min: float = Field(default=20.0, gt=0, le=10000)
    minutes_per_hole: float = Field(default=0.5, ge=0, le=100)
    material_price_per_kg: dict[str, float] = Field(default_factory=dict)
    mould_tooling_cost: float = Field(default=10000.0, ge=0, le=1e8)
    mould_cycle_s: float = Field(default=45.0, gt=0, le=3600)
    moulding_rate_per_hour: float = Field(default=60.0, ge=0, le=10000)
    casting_tooling_cost: float = Field(default=3000.0, ge=0, le=1e8)
    casting_minutes_per_part: float = Field(default=12.0, ge=0, le=10000)
    am_material_per_kg: dict[str, float] = Field(default_factory=lambda: {"fdm": 25.0, "sla": 80.0, "sls": 60.0})
    am_rate_cm3_h: dict[str, float] = Field(default_factory=lambda: {"fdm": 12.0, "sla": 15.0, "sls": 25.0})
    sheet_cut_mm_min: float = Field(default=3000.0, gt=0, le=1e6)
    sheet_minutes_per_bend: float = Field(default=1.0, ge=0, le=1000)

    @field_validator("mrr_cm3_min")
    @classmethod
    def _mrr(cls, v: dict[str, float]) -> dict[str, float]:
        out = {k: float(x) for k, x in v.items() if k in CLASSES}
        if any(not (0 < x <= 100000) for x in out.values()):
            raise ValueError("removal rates must be positive")
        return out

    @field_validator("material_price_per_kg", "am_material_per_kg", "am_rate_cm3_h")
    @classmethod
    def _positive(cls, v: dict[str, float]) -> dict[str, float]:
        if len(v) > 200 or any(not (0 <= float(x) <= 1e6) for x in v.values()):
            raise ValueError("values must be between 0 and 1,000,000")
        return {str(k)[:40]: float(x) for k, x in v.items()}

    def mrr(self, cls: str) -> float:
        return self.mrr_cm3_min.get(cls) or DEFAULT_MRR.get(cls, 10.0)

    def mills(self) -> list[Machine]:
        return [m for m in self.machines if m.kind in ("mill3", "mill5")]

    def lathes(self) -> list[Machine]:
        return [m for m in self.machines if m.kind == "lathe"]

    def printers(self, kind: str) -> list[Machine]:
        return [m for m in self.machines if m.kind == f"printer_{kind}"]

    def mill_rate(self) -> float:
        ms = self.mills()
        return min(m.rate_per_hour for m in ms) if ms else 75.0

    def lathe_rate(self) -> float:
        ms = self.lathes()
        return min(m.rate_per_hour for m in ms) if ms else 65.0

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True).encode()).hexdigest()[:16]


def profile_path(org_dir: Path) -> Path:
    return org_dir / "manufacturing" / "shop_profile.json"


def load(org_dir: Path) -> tuple[ShopProfile, bool]:
    """(profile, is_default)."""
    p = profile_path(org_dir)
    try:
        return ShopProfile.model_validate(json.loads(p.read_text(encoding="utf-8"))), False
    except (OSError, ValueError):
        return ShopProfile(), True


def save(org_dir: Path, prof: ShopProfile) -> None:
    p = profile_path(org_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(prof.model_dump(), indent=2), encoding="utf-8")
    tmp.replace(p)


def defaults_note() -> dict[str, Any]:
    return {"text": "Default values are assumptions typical of a small job shop, for relative comparison only. "
                    "Replace them with your own machines, tools and rates."}
