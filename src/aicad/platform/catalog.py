"""Product modules and the default sellable catalog.

`status` is the honest capability state shown in the UI:
  live    - implemented and usable
  preview - UI/roadmap only; any output shown is labelled SAMPLE
Prices are pricing *hypotheses* (DECISIONS AS-01); editable from the admin console.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from aicad.platform.models import Product

MODULES: dict[str, dict[str, Any]] = {
    "design": {
        "name": "Design Studio", "status": "live", "icon": "box",
        "summary": "Describe a part in plain language. The AI design agent writes parametric CAD, builds it, "
                   "verifies geometry and shows it live.",
        "bullets": ["Natural language → parametric build123d model", "Deterministic geometry checks",
                    "Live 3D viewer, STEP / STL export", "Conversational revisions"],
    },
    "drawings": {
        "name": "Drawing Studio", "status": "live", "icon": "ruler",
        "summary": "Turn a verified model into a drawing sheet: exact hidden-line views, a hatched section, "
                   "dimensions tagged spec or inferred, hole callouts and a title block. Every sheet is "
                   "consistency-checked and marked not approved for manufacture.",
        "bullets": ["Front / top / right + isometric, first or third angle", "Section A-A with hatching",
                    "Spec vs inferred dimensions, hole callouts", "SVG / PDF / DXF, regenerates on model change"],
    },
    "image2cad": {
        "name": "Image & Drawing to CAD", "status": "live", "icon": "scan",
        "summary": "Upload a PDF drawing, a scan, a sketch or a photo. Every value read is pinned on the image for "
                   "review, missing sizes become questions, and scale stays undefined until you confirm a real "
                   "dimension. The design agent then models from the confirmed values only.",
        "bullets": ["Vector PDFs read exactly from the drawing text: Ø, R, threads, tolerances, counts, scale",
                    "Scans, sketches and photos read by AI vision, each value with a confidence",
                    "\"What we read / What we need\" review: nothing proceeds silently",
                    "One-click hand-off to the Design Studio with the reference attached"],
    },
    "assembly": {
        "name": "Assembly Studio", "status": "live", "icon": "boxes",
        "summary": "Assemble your verified parts and Toolbox components with mates that report under- and "
                   "over-defined states honestly. Exact interference volumes and clearances, an exploded view, a "
                   "BOM, and Fastener auto-fit: pick a hole and get the ISO bolt, washers and nut sized from the "
                   "clearance and the measured grip.",
        "bullets": ["Coincident, flush, concentric, distance and angle mates with DOF analysis",
                    "Fastener auto-fit: standard bolt length from the measured grip, rule cited",
                    "Exact interference volumes and minimum clearances",
                    "Exploded view, BOM (CSV) and assembly STEP with hierarchy"],
    },
    "manufacturing": {
        "name": "Manufacturing Advisor", "status": "live", "icon": "factory",
        "summary": "Advisory design-for-manufacture checks on your exact model: CNC milling, drilling and turning "
                   "rules, draft and undercut screening, a ranked process shortlist and a relative cost estimate "
                   "(not a quote), checked against your shop profile.",
        "bullets": ["CNC and turning DFM checks on the exact B-rep", "Process ranking with stated assumptions",
                    "Relative cost and cost-driver suggestions", "Printable report (HTML / PDF)"],
    },
    "engineering": {
        "name": "Engineering Advisor", "status": "live", "icon": "gauge",
        "summary": "Hand-calculation checks for your parts: beams, bolted joints, pins, bearings, shafts, fits, "
                   "springs and tolerance stack-ups, with the working and sources shown, inputs pre-filled from "
                   "the model, and named engineer sign-off. Results are estimates, never validation.",
        "bullets": ["10 unit-safe calculators, tested against published textbook examples",
                    "Pre-fill from the model: mass, holes, sections, material",
                    "Load cases, failure-mode checklist and stress-raiser hints",
                    "Advice level on every result; signed sets invalidate on edit"],
    },
    "print": {
        "name": "3D Print Prep", "status": "live", "icon": "printer",
        "summary": "Check a verified model or an uploaded STL / OBJ / 3MF before you slice: watertightness, wall "
                   "thickness, overhangs and bridges, build-volume fit and ranked print orientations. Geometric "
                   "checks and rough estimates, not a slicer.",
        "bullets": ["Watertight, manifold and self-intersection checks", "Wall-thickness heatmap and overhang map",
                    "Ranked orientations with support, height and strength notes",
                    "Mesh repair, oriented STL / 3MF export (mm)"],
    },
    "mesh": {
        "name": "Mesh Studio", "status": "preview", "icon": "shapes",
        "summary": "Procedural and AI-generated meshes for visualisation and concept art, clearly separated "
                   "from precision CAD.",
        "bullets": ["Text / image → scene", "Materials & lighting", "GLB / OBJ / FBX export",
                    "Render–critique loop"],
    },
}

TOKEN_COSTS = {
    "design_run_min": 1,       # minimum per agent run
    "design_run_preflight": 10,  # balance required to start a run
    "usd_per_token": 0.01,     # metering: tokens = ceil(estimated compute USD / usd_per_token)
}

DEFAULT_PRODUCTS: list[dict[str, Any]] = [
    # plans
    {"code": "trial", "kind": "plan", "name": "Free trial", "tagline": "Try the full design loop",
     "price_cents": 0, "interval": None, "tokens": 300, "seats": 1, "modules": ["design"],
     "features": ["300 trial tokens", "Design Studio", "STEP / STL export", "14 days"],
     "purchasable": False, "sort": 0},
    {"code": "pro", "kind": "plan", "name": "Pro", "tagline": "For independent engineers",
     "price_cents": 4900, "interval": "month", "tokens": 1500, "seats": 1,
     "modules": ["design", "drawings", "print"],
     "features": ["1,500 tokens / month", "Design Studio", "Drawing Studio", "3D Print Prep",
                  "Unlimited projects", "Email support"], "highlight": True, "sort": 1},
    {"code": "team", "kind": "plan", "name": "Team", "tagline": "For consultancies and shops",
     "price_cents": 19900, "interval": "month", "tokens": 7500, "seats": 5,
     "modules": ["design", "drawings", "print", "assembly", "manufacturing"],
     "features": ["7,500 pooled tokens / month", "5 seats included", "Assembly Studio",
                  "Manufacturing Advisor", "Roles & permissions", "Priority support"], "sort": 2},
    {"code": "enterprise", "kind": "plan", "name": "Enterprise", "tagline": "Security, scale and control",
     "price_cents": 0, "interval": "month", "tokens": 0, "seats": 0,
     "modules": list(MODULES), "features": ["Every module", "SSO & audit exports", "Private deployment option",
                                            "Data residency & no-AI-training guarantees", "Dedicated engineer"],
     "contact_sales": True, "purchasable": False, "sort": 3},
    # add-ons (monthly module unlocks)
    {"code": "addon_drawings", "kind": "addon", "name": "Drawing Studio", "price_cents": 1900, "interval": "month",
     "modules": ["drawings"], "sort": 10},
    {"code": "addon_image2cad", "kind": "addon", "name": "Image & Drawing to CAD", "price_cents": 1900,
     "interval": "month", "modules": ["image2cad"], "sort": 11},
    {"code": "addon_assembly", "kind": "addon", "name": "Assembly Studio", "price_cents": 2900, "interval": "month",
     "modules": ["assembly"], "sort": 12},
    {"code": "addon_manufacturing", "kind": "addon", "name": "Manufacturing Advisor", "price_cents": 2900,
     "interval": "month", "modules": ["manufacturing"], "sort": 13},
    {"code": "addon_engineering", "kind": "addon", "name": "Engineering Advisor", "price_cents": 2900,
     "interval": "month", "modules": ["engineering"], "sort": 14},
    {"code": "addon_print", "kind": "addon", "name": "3D Print Prep", "price_cents": 900, "interval": "month",
     "modules": ["print"], "sort": 15},
    {"code": "addon_mesh", "kind": "addon", "name": "Mesh Studio", "price_cents": 1900, "interval": "month",
     "modules": ["mesh"], "sort": 16},
    # token packs (one-off)
    {"code": "tokens_500", "kind": "topup", "name": "500 tokens", "price_cents": 1000, "tokens": 500, "sort": 20},
    {"code": "tokens_2000", "kind": "topup", "name": "2,000 tokens", "tagline": "Save 12%", "price_cents": 3500,
     "tokens": 2000, "highlight": True, "sort": 21},
    {"code": "tokens_10000", "kind": "topup", "name": "10,000 tokens", "tagline": "Save 25%", "price_cents": 15000,
     "tokens": 10000, "sort": 22},
]

for p in DEFAULT_PRODUCTS:
    if p["kind"] == "addon":
        m = MODULES[p["modules"][0]]
        p.setdefault("tagline", m["summary"][:190])
        p.setdefault("features", m["bullets"])


def seed_catalog(db: Session) -> None:
    for p in DEFAULT_PRODUCTS:
        if db.get(Product, p["code"]) is None:
            db.add(Product(**p))
    db.commit()


def product_dict(p: Product) -> dict[str, Any]:
    return {k: getattr(p, k) for k in ("code", "kind", "name", "tagline", "description", "price_cents", "interval",
                                       "tokens", "seats", "modules", "features", "highlight", "contact_sales",
                                       "purchasable", "active", "sort")}
