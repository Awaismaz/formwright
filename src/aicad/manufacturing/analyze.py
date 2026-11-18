"""Manufacturing analysis of one verified build: DFM findings (CHK-13), process ranking, relative cost and cost
drivers. `analyse_shape` works on any build123d shape (tests); `analyse_workspace` reads a project's `out/`."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from build123d import Shape
from pydantic import BaseModel, Field

from aicad import deliverables
from aicad import materials as base_materials
from aicad.manufacturing import ADVICE_LEVELS, ANALYSER_VERSION, matlib
from aicad.manufacturing import cost as C
from aicad.manufacturing import features as F
from aicad.manufacturing import process as P
from aicad.manufacturing import rules as R
from aicad.manufacturing import standards as S
from aicad.manufacturing.geometry import PartGeom
from aicad.manufacturing.shop import ShopProfile

DISCLAIMER = ("Advisory design-for-manufacture screening. Measurements are deterministic, but the limits are "
              "published guidance and your shop-profile inputs. This is not manufacturing approval, and the costs are "
              "a relative estimate, not a quote. Review with your manufacturer before release.")
DEFAULT_MATERIAL = "al_6061"


class Inputs(BaseModel):
    quantity: int = Field(default=10, ge=1, le=1_000_000)
    material: str | None = None
    tolerance: Literal["general", "fine", "precision"] = "general"


def resolve_material(code: str | None, status_material: str | None = None) -> tuple[dict[str, Any], str]:
    """(material, how it was chosen)."""
    if code and matlib.get(code):
        return matlib.get(code), "selected"  # type: ignore[return-value]
    guess = base_materials.guess(status_material)
    if guess and matlib.get(guess):
        return matlib.get(guess), f"matched from the model material \"{status_material}\""  # type: ignore[return-value]
    return matlib.get(DEFAULT_MATERIAL), "assumed (no material set)"  # type: ignore[return-value]


def _drivers(g: PartGeom, shop: ShopProfile, inputs: Inputs, lines: dict[str, Any], findings: list[dict[str, Any]],
             primary: str) -> list[dict[str, Any]]:
    q = inputs.quantity
    ln = lines.get(primary)
    if ln is None:
        return []
    unit = C.unit_cost(ln, q)
    bd = C.breakdown(ln, q)
    cur = shop.currency
    out: list[dict[str, Any]] = []

    def add(title: str, rationale: str, faces: list[int] | None = None, saving: float | None = None,
            features: list[str] | None = None, rule: str | None = None) -> None:
        out.append({"title": title, "rationale": rationale, "faces": sorted(set(faces or [])),
                    "features": sorted(set(features or [])), "rule": rule,
                    "saving_per_unit": round(saving, 2) if saving else None,
                    "saving_pct": round(100 * saving / unit, 1) if saving and unit > 0 else None,
                    "advice_level": ADVICE_LEVELS["estimate"]})

    def fnd(rule: str, sev: tuple[str, ...] = ("critical", "warning")) -> list[dict[str, Any]]:
        return [f for f in findings if f["rule"] == rule and f["severity"] in sev]

    name = P.NAMES[primary]
    if bd["setup_tooling"] > 0.5 * unit and q < 10000:
        q2 = q * 10
        u2 = C.unit_cost(ln, q2)
        add(f"Setup, programming and tooling are {100 * bd['setup_tooling'] / unit:.0f} % of the unit cost",
            f"At {q:,} parts the fixed costs dominate ({name}). The estimate falls from {cur} {unit:,.2f} to "
            f"{cur} {u2:,.2f} per part at {q2:,} parts. Batch orders where you can.", saving=unit - u2)
    if bd["machine_time"] > 0.5 * unit:
        detail = ""
        if primary == "cnc_milling":
            detail = (f" Roughing ≈ {ln['rough_min']:.0f} min for {ln['removed_cm3']:.0f} cm³ removed, finishing ≈ "
                      f"{ln['finish_min']:.0f} min over the surface area.")
        add(f"Machine time is {100 * bd['machine_time'] / unit:.0f} % of the unit cost",
            f"{name} cycle time dominates at {q:,} parts.{detail} Thinner or near-net stock, fewer finished faces and "
            "larger internal radii (larger, faster tools) shorten it.")
    if primary == "cnc_milling":
        frac = float(ln.get("removed_frac", 0.0))
        if frac > 0.6:
            add(f"{100 * frac:.0f} % of the stock block is machined away",
                "Most of the cost is chip-making. Near-net stock (plate, extrusion, bar or a casting/forging blank) or "
                "a different process reduces roughing time and material.")
        if ln.get("setups", 0) >= 3:
            per = (shop.setup_minutes / 60 * ln["rate_per_hour"]) / q + C.HANDLING_MIN_PER_SETUP / 60 * ln["rate_per_hour"]
            fs = fnd("DFM-CNC-07")
            add(f"{ln['setups']} setups estimated", "Each extra setup adds fixturing, re-referencing and handling. "
                "Moving the highlighted features onto the main sides would save about one setup.",
                faces=[i for f in fs for i in f["faces"]], saving=per, rule="DFM-CNC-07")
        if "cnc_turning" in lines:
            ut = C.unit_cost(lines["cnc_turning"], q)
            if ut < unit:
                add("Rotational part: turning is estimated cheaper",
                    f"Turning from bar is estimated at {cur} {ut:,.2f} per part against {cur} {unit:,.2f} for milling "
                    f"at {q:,} parts.", saving=unit - ut)
    for rule, title, why in (
            ("DFM-CNC-01", "Small internal corner radii force small, slow tools",
             "Larger radii allow a larger cutter that removes material faster and deflects less."),
            ("DFM-CNC-02", "Sharp internal corners need EDM or a design change",
             "A rotating cutter cannot make them; EDM is slow and adds an operation."),
            ("DFM-HOLE-02", "Non-standard hole sizes need extra tools",
             "Stocked drill sizes avoid interpolation, boring or special reamers."),
            ("DFM-HOLE-01", "Deep holes need peck cycles or special drills",
             "Shallower or larger holes drill in one pass with standard tools."),
            ("DFM-CNC-04", "Deep, narrow cavities need long-reach tools",
             "Shallower or wider cavities let a stiffer tool run at full feed."),
            ("DFM-CNC-05", "Thin walls must be machined slowly",
             "Thicker walls tolerate normal cutting forces.")):
        fs = fnd(rule)
        if fs:
            add(title, why, faces=[i for f in fs for i in f["faces"]],
                features=[x for f in fs for x in f["features"]], rule=rule)
    if inputs.tolerance != "general":
        mult = C.TOL_FINISH[inputs.tolerance]
        saving = None
        if primary == "cnc_milling":
            saving = (mult - 1) / mult * ln.get("finish_min", 0.0) / 60 * ln["rate_per_hour"]
        add(f"'{inputs.tolerance.capitalize()}' tolerance applied to the whole part",
            f"The model assumes finishing takes {mult:g} × longer. Apply tight tolerances only to functional "
            "features (fits, datums) and leave the rest at a general tolerance such as ISO 2768-m.", saving=saving)
    return out


def screens(findings: list[dict[str, Any]], ranking: list[dict[str, Any]], mat: dict[str, Any],
            ctx: R.Ctx) -> dict[str, dict[str, Any]]:
    """Which rule groups are shown by default. A group is moved to "other screens" when the material excludes its
    processes or (moulding / casting) none of them is shortlisted. A group with a critical finding is always shown."""
    procs = set(mat["processes"])
    score = {r["process"]: r["score"] if r["feasible"] else 0 for r in ranking}
    out: dict[str, dict[str, Any]] = {}
    for key in R.PROCESS_LABEL:
        if key == "cnc_milling":
            shown, why = "mill" in procs, f"{mat['name']} is not normally milled"
        elif key == "cnc_turning":
            shown, why = ctx.turn.turnable and "turn" in procs, "not a rotational part"
        elif key == "sheet_metal":
            shown, why = R._sheet_applies(ctx), "not a constant-thickness sheet part"
        else:
            allowed = bool({"mould", "cast"} & procs)
            short = max(score.get("casting", 0), score.get("injection_moulding", 0)) >= 45
            shown = allowed and short
            why = (f"{mat['name']} is neither moulded nor cast" if not allowed else
                   "casting and moulding are not shortlisted at this quantity")
        if any(f["process"] == key and f["severity"] == "critical" for f in findings):
            shown = True
        out[key] = {"shown": bool(shown), "reason": None if shown else why}
    return out


def summary_counts(findings: list[dict[str, Any]], scr: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Severity counts across every shown process (never filtered by the process chip); critical always counted."""
    keep = [f for f in findings if f["severity"] == "critical" or scr.get(f["process"], {}).get("shown", True)
            or any(scr.get(a, {}).get("shown") for a in f.get("also") or [])]
    return {s: sum(1 for f in keep if f["severity"] == s) for s in ("critical", "warning", "info")}


def analyse_shape(shape: Shape, shop: ShopProfile, inputs: Inputs, topo: dict[str, Any] | None = None,
                  status_material: str | None = None, meta: dict[str, Any] | None = None,
                  sheet_model: dict[str, Any] | None = None) -> dict[str, Any]:
    g = PartGeom(shape, topo)
    return analyse_geom(g, shop, inputs, status_material, meta, sheet_model)


def analyse_geom(g: PartGeom, shop: ShopProfile, inputs: Inputs, status_material: str | None = None,
                 meta: dict[str, Any] | None = None, sheet_model: dict[str, Any] | None = None) -> dict[str, Any]:
    """``sheet_model``: the part's sheet-metal model (CAD-026). The part is then sheet metal of that thickness
    whatever the geometric screen says, and the flat size and bend count come from the model."""
    mat, mat_how = resolve_material(inputs.material, status_material)
    acc = F.accessibility(g, shop.max_tool_reach_mm, shop.max_flank_mm)
    th = F.thickness(g)
    hs = F.holes(g)
    ctx = R.Ctx(g=g, shop=shop, metal=bool(mat["metal"]), acc=acc, thick=th, holes=hs,
                corners=F.corners(g, acc, hs), sharp=F.sharp_internal_corners(g, acc), pockets=F.pockets(g, acc),
                turn=F.turning(g), sheet=F.sheet_like(g, th), material=mat)
    if sheet_model and sheet_model.get("flat") and not sheet_model.get("flat_error"):
        geo = ctx.sheet
        ctx.sheet = F.Sheet(True, float(sheet_model["thickness"]), geo.frac if geo and geo.sheet_like else 1.0)
        ctx.sheet_model = sheet_model
    sheet = ctx.sheet
    ctx.mould_acc = F.accessibility(g, 1e9, 1e9)
    ctx.pull = R.choose_pull(g, ctx.mould_acc)
    findings, summary = R.run(ctx)
    lines = C.models(g, shop, mat, acc, hs, ctx.turn, sheet, inputs.tolerance, ctx.sheet_model)
    unit_costs = {k: C.unit_cost(v, inputs.quantity) for k, v in lines.items()}
    draft_faces = sum(len(f["faces"]) for f in findings if f["rule"] == "MLD-01")
    mould_uc = sum(len(f["faces"]) for f in findings if f["rule"] == "MLD-02")
    thick_m = any(f["rule"] == "MLD-03" for f in findings)
    proc = P.rank(g, shop, mat, inputs.quantity, inputs.tolerance, acc, ctx.turn, sheet, findings, unit_costs,
                  draft_faces, mould_uc, thick_m)
    for r in proc["ranking"]:
        if r["unit_cost"] is not None:
            r["unit_cost"] = round(r["unit_cost"], 2)
    costed = [r["process"] for r in proc["ranking"] if r["feasible"] and r["process"] in lines]
    primary = next((p for p in costed if p in ("cnc_milling", "cnc_turning")), costed[0] if costed else "cnc_milling")
    cost = C.summary(lines, inputs.quantity, shop.currency)
    cost["primary"] = primary
    drivers = _drivers(g, shop, inputs, lines, findings, primary)
    walls = sorted(t.t for t in th if t.wall)
    scr = screens(findings, proc["ranking"], mat, ctx)
    counts = summary_counts(findings, scr)
    density = float(mat["density_g_cm3"])
    return {
        "version": 1, "analyser": ANALYSER_VERSION, "tables": S.TABLES_VERSION,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "build": meta or {},
        "inputs": inputs.model_dump(),
        "material": {**mat, "how": mat_how, "library_version": matlib.LIBRARY_VERSION,
                     "price_used": C.price_per_kg(shop, mat)},
        "shop": {"name": shop.name, "fingerprint": shop.fingerprint(), "currency": shop.currency},
        "part": {"bbox": [round(float(x), 4) for x in g.size], "volume_mm3": round(g.volume, 3),
                 "area_mm2": round(g.area, 3), "mass_kg": round(g.volume * density / 1e6, 4),
                 "faces": len(g.faces), "solids": g.n_solids},
        "signals": {
            "setups": acc.setups, "setup_faces": {k: g.fids(v) for k, v in acc.by_setup.items()},
            "undercut_faces": g.fids(acc.undercut),
            "turning": {"turnable": ctx.turn.turnable, "axis": ctx.turn.axis_name,
                        "revolved_pct": round(100 * ctx.turn.revolved_frac, 1),
                        "max_diameter": round(ctx.turn.max_d, 3), "length": round(ctx.turn.length, 3)},
            "sheet": {"sheet_like": sheet.sheet_like, "thickness": sheet.thickness, "pct": round(100 * sheet.frac, 1),
                      **({"model": True, "flat_size": ctx.sheet_model["flat"]["size"],
                          "bend_count": ctx.sheet_model.get("bend_count", 0),
                          "k_factor": ctx.sheet_model.get("k_factor")} if ctx.sheet_model else {})},
            "holes": [{"d": round(h.d, 4), "depth": round(h.depth, 4), "ld": round(h.ld, 3), "through": h.through,
                       "faces": g.fids(h.faces)} for h in hs],
            "pockets": [{"depth": round(p.depth, 3), "width": round(p.width, 3), "direction": p.direction,
                         "faces": g.fids([p.floor, *p.walls])} for p in ctx.pockets],
            "min_wall_mm": round(walls[0], 3) if walls else None, "pull_direction": ctx.pull,
        },
        "findings": findings,
        "summary": counts, "screens": scr,
        "chk13": {"id": "CHK-13", "name": "DFM rules (advisory)", "gate": False, "counts": counts,
                  "rules": summary, "advice_level": ADVICE_LEVELS["check"]},
        "process": proc, "cost": cost, "drivers": drivers, "disclaimer": DISCLAIMER,
    }


# ----------------------------------------------------------------------------- workspace entry point
def cache_key(status: dict[str, Any], shop: ShopProfile, inputs: Inputs, material_code: str | None) -> str:
    basis = {"v": ANALYSER_VERSION, "t": S.TABLES_VERSION, "m": matlib.LIBRARY_VERSION,
             "step": status.get("step_sha256") or status.get("fingerprint"), "build": status.get("build_id"),
             "shop": shop.fingerprint(), "inputs": inputs.model_dump(), "mat": material_code}
    return hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()[:20]


def analyse_workspace(ws: Path, shop: ShopProfile, inputs: Inputs, material_code: str | None = None,
                      use_cache: bool = True) -> dict[str, Any]:
    out = ws / "out"
    status = json.loads((out / "status.json").read_text(encoding="utf-8"))
    if not inputs.material and material_code:
        inputs = inputs.model_copy(update={"material": material_code})
    key = cache_key(status, shop, inputs, inputs.material)
    dest = ws / "manufacturing" / "analysis.json"
    if use_cache and dest.is_file():
        try:
            prev = json.loads(dest.read_text(encoding="utf-8"))
            if prev.get("cache_key") == key:
                return prev
        except ValueError:
            pass
    topo = None
    if (out / "topo.json").is_file():
        topo = json.loads((out / "topo.json").read_text(encoding="utf-8"))
    g = PartGeom.from_step(out / "part.step", topo)
    meta = {**deliverables.build_stamp(ws, status), "fingerprint": status.get("fingerprint"), "part": status.get("part")}
    res = analyse_geom(g, shop, inputs, status.get("material"), meta, status.get("sheet_metal"))
    res["cache_key"] = key
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    tmp.replace(dest)
    return res
