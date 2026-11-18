"""Relative cost model (MFG-017). **Relative estimate, not a quote.**

Unit cost(q) = material + machine time × rate + (setups, programming and tooling) / q, per process. Inputs come
from the measured part (volume, area, envelope, holes, setups) and the shop profile, whose defaults are labelled
assumptions. The model is for comparing options and spotting cost drivers, never for pricing.
"""

from __future__ import annotations

import math
from typing import Any

from aicad.manufacturing import ADVICE_LEVELS
from aicad.manufacturing import features as F
from aicad.manufacturing.geometry import PartGeom
from aicad.manufacturing.shop import ShopProfile

LABEL = "Relative estimate, not a quote"
QUANTITIES = [1, 10, 100, 1000, 10000]
TOL_FINISH = {"general": 1.0, "fine": 1.3, "precision": 1.8}  # finishing-time multiplier (assumption)
STOCK_ALLOWANCE_MM = 3.0  # per side, block stock (assumption)
HANDLING_MIN_PER_SETUP = 2.0  # load / unload per part per setup (assumption)


def _line(name: str, material: float, run_min: float, rate: float, fixed: float, notes: list[str],
          extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"material": material, "run_minutes": run_min, "rate_per_hour": rate, "fixed": fixed, "notes": notes,
            **(extra or {}), "process": name}


def unit_cost(line: dict[str, Any], q: int) -> float:
    q = max(1, int(q))
    return line["material"] + line["run_minutes"] / 60.0 * line["rate_per_hour"] + line["fixed"] / q


def breakdown(line: dict[str, Any], q: int) -> dict[str, float]:
    q = max(1, int(q))
    return {"material": line["material"], "machine_time": line["run_minutes"] / 60.0 * line["rate_per_hour"],
            "setup_tooling": line["fixed"] / q}


def price_per_kg(shop: ShopProfile, mat: dict[str, Any]) -> float:
    return float(shop.material_price_per_kg.get(mat["code"], mat["price_per_kg"]))


def models(g: PartGeom, shop: ShopProfile, mat: dict[str, Any], acc: F.Access, holes: list[F.Hole],
           turn: F.Turning, sheet: F.Sheet, tolerance: str,
           sheet_model: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    rho = float(mat["density_g_cm3"]) / 1000.0  # g/mm^3 -> kg via /1000 below
    price = price_per_kg(shop, mat)
    v_cm3 = g.volume / 1000.0
    area_cm2 = g.area / 100.0
    tolf = TOL_FINISH.get(tolerance, 1.0)
    procs = set(mat["processes"])
    out: dict[str, dict[str, Any]] = {}

    # CNC milling from a block
    stock = [float(s) + 2 * STOCK_ALLOWANCE_MM for s in g.size]
    v_stock = math.prod(stock)
    m_stock = v_stock * rho / 1000.0
    removed_cm3 = max(0.0, v_stock - g.volume) / 1000.0
    mrr = shop.mrr(mat["machining_class"])
    rough = removed_cm3 / mrr
    finish = area_cm2 / shop.finish_cm2_min * tolf
    holes_min = len(holes) * shop.minutes_per_hole
    n_set = len(acc.setups)
    run = rough + finish + holes_min + n_set * HANDLING_MIN_PER_SETUP
    fixed = (n_set * shop.setup_minutes + shop.programming_minutes) / 60.0 * shop.mill_rate()
    out["cnc_milling"] = _line("cnc_milling", m_stock * price, run, shop.mill_rate(), fixed, [
        f"Block stock {' × '.join(f'{s:.0f}' for s in stock)} mm ({STOCK_ALLOWANCE_MM:g} mm per side, assumed)",
        f"Removed {removed_cm3:.1f} cm³ at {mrr:g} cm³/min ({mat['machining_class']}, shop profile)",
        f"Finishing {area_cm2:.0f} cm² at {shop.finish_cm2_min:g} cm²/min × {tolf:g} (tolerance)",
        (f"{len(holes)} holes × {shop.minutes_per_hole:g} min; {n_set} setups × {shop.setup_minutes:g} min + "
        f"{shop.programming_minutes:g} min programming per batch")],
        {"stock_mass_kg": m_stock, "removed_cm3": removed_cm3, "rough_min": rough, "finish_min": finish,
         "holes_min": holes_min, "setups": n_set, "removed_frac": removed_cm3 * 1000.0 / v_stock if v_stock else 0})

    if turn.turnable:
        bar_d = math.ceil(turn.max_d + 3.0)
        bar_l = turn.length + 5.0
        v_bar = math.pi / 4 * bar_d ** 2 * bar_l
        m_bar = v_bar * rho / 1000.0
        rem = max(0.0, v_bar - g.volume) / 1000.0
        tmrr = mrr * shop.turning_mrr_factor
        sec = bool(turn.secondary)
        sec_holes = [h for h in holes if any(i in turn.secondary for i in h.faces)]
        ops = 2 + (1 if sec else 0)
        run_t = rem / tmrr + finish + (5.0 if sec else 0.0) + len(sec_holes) * shop.minutes_per_hole \
            + ops * HANDLING_MIN_PER_SETUP
        fixed_t = (ops * shop.setup_minutes + shop.programming_minutes) / 60.0 * shop.lathe_rate()
        out["cnc_turning"] = _line("cnc_turning", m_bar * price, run_t, shop.lathe_rate(), fixed_t, [
            f"Bar stock Ø{bar_d} × {bar_l:.0f} mm (assumed +3 mm on Ø, +5 mm length)",
            f"Removed {rem:.1f} cm³ at {tmrr:g} cm³/min (milling rate × {shop.turning_mrr_factor:g}, assumed)",
            f"{ops} operations (both ends{', plus a secondary milling setup' if sec else ''})"],
            {"stock_mass_kg": m_bar, "removed_cm3": rem, "setups": ops})

    if sheet_model and sheet.thickness and "sheet" in procs:  # CAD-026: flat size and bends from the model
        t = sheet.thickness
        fx, fy = (float(v) for v in sheet_model["flat"]["size"])
        cut_len = float(sheet_model["flat"]["perimeter_mm"])
        bends = int(sheet_model.get("bend_count") or 0)
        m_sheet = fx * fy * t * 1.1 * rho / 1000.0
        run_s = cut_len / shop.sheet_cut_mm_min + bends * shop.sheet_minutes_per_bend + 1.0
        fixed_s = (shop.setup_minutes + shop.programming_minutes / 2) / 60.0 * shop.mill_rate()
        out["sheet_metal"] = _line("sheet_metal", m_sheet * price, run_s, shop.mill_rate(), fixed_s, [
            f"{t:g} mm sheet, blank = flat pattern {fx:.1f} × {fy:.1f} mm × 1.1 nesting allowance (assumed)",
            f"Cut length {cut_len:.0f} mm (flat outline) at {shop.sheet_cut_mm_min:g} mm/min; {bends} bend(s) from the model",
            "Laser / punch and press-brake rates use the milling rate (assumed)"],
            {"flat_mm": [fx, fy], "bends": bends})
    elif sheet.sheet_like and sheet.thickness and "sheet" in procs:
        t = sheet.thickness
        strips = [f for f in g.faces if f.area <= 1.1 * t * sum(g.edges[e].length for e in f.edges)]
        cut_len = sum(f.area for f in strips) / t
        bend_axes = {(round(float(f.axis[0]), 3), round(float(f.axis[1]), 3), round(float(f.axis[2]), 3))
                     for f in g.faces if f.kind == "cylinder" and (f.sweep or 0) < 2 * math.pi - 1e-3
                     and f.axis is not None}
        bends = len(bend_axes)
        m_sheet = g.volume * 1.2 * rho / 1000.0
        run_s = cut_len / shop.sheet_cut_mm_min + bends * shop.sheet_minutes_per_bend + 1.0
        fixed_s = (shop.setup_minutes + shop.programming_minutes / 2) / 60.0 * shop.mill_rate()
        out["sheet_metal"] = _line("sheet_metal", m_sheet * price, run_s, shop.mill_rate(), fixed_s, [
            f"{t:g} mm sheet, blank = part area × 1.2 nesting allowance (assumed)",
            f"Cut length ≈ {cut_len:.0f} mm at {shop.sheet_cut_mm_min:g} mm/min; {bends} bend(s)",
            "Laser / punch and press-brake rates use the milling rate (assumed)"])

    if not mat["metal"]:
        for kind in ("fdm", "sla", "sls"):
            if kind not in procs and not (kind == "sla" and "fdm" in procs):
                continue
            pr = shop.printers(kind)
            rate = pr[0].rate_per_hour if pr else 10.0
            m_am = v_cm3 * 1.15 * float(mat["density_g_cm3"]) / 1000.0
            hrs = v_cm3 / shop.am_rate_cm3_h.get(kind, 12.0)
            out[kind] = _line(kind, m_am * shop.am_material_per_kg.get(kind, 40.0), hrs * 60 + 10.0, rate,
                              15.0 / 60.0 * rate, [
                                  (f"{v_cm3:.1f} cm³ + 15 % supports at {shop.am_material_per_kg.get(kind, 40.0):g} "
                                  "per kg (assumed)"),
                                  (f"Build {shop.am_rate_cm3_h.get(kind, 12.0):g} cm³/h, 10 min post-processing "
                                  "(assumed)")])

    if "cast" in procs:
        mill = out["cnc_milling"]
        run_c = shop.casting_minutes_per_part + 0.3 * (mill["finish_min"] + mill["holes_min"])
        out["casting"] = _line("casting", g.volume * 1.4 * rho / 1000.0 * price, run_c, shop.mill_rate(),
                               shop.casting_tooling_cost, [
                                   (f"Pattern / tooling {shop.casting_tooling_cost:,.0f} (assumed), 40 % gating yield "
                                   "loss (assumed)"),
                                   "Plus 30 % of the milling finish time for machined datums and holes (assumed)"])

    if "mould" in procs:
        out["injection_moulding"] = _line(
            "injection_moulding", g.volume * 1.05 * rho / 1000.0 * price, shop.mould_cycle_s / 60.0,
            shop.moulding_rate_per_hour, shop.mould_tooling_cost, [
                f"Mould {shop.mould_tooling_cost:,.0f} (assumed single-cavity tool)",
                f"Cycle {shop.mould_cycle_s:g} s at {shop.moulding_rate_per_hour:g} per hour (assumed)"])
    return out


def summary(lines: dict[str, dict[str, Any]], quantity: int, currency: str) -> dict[str, Any]:
    qs = sorted(set(QUANTITIES + [max(1, int(quantity))]))
    out: dict[str, Any] = {"label": LABEL, "advice_level": ADVICE_LEVELS["estimate"], "currency": currency,
                           "quantity": quantity, "quantities": qs, "processes": {}}
    for name, ln in lines.items():
        out["processes"][name] = {
            "unit_cost": round(unit_cost(ln, quantity), 2),
            "batch_cost": round(unit_cost(ln, quantity) * quantity, 2),
            "breakdown": {k: round(v, 2) for k, v in breakdown(ln, quantity).items()},
            "curve": [{"q": q, "unit": round(unit_cost(ln, q), 2)} for q in qs],
            "run_minutes": round(ln["run_minutes"], 2), "fixed": round(ln["fixed"], 2),
            "material": round(ln["material"], 2), "notes": ln["notes"],
            **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in ln.items()
               if k in ("setups", "removed_cm3", "stock_mass_kg", "removed_frac", "rough_min", "finish_min")},
        }
    return out
