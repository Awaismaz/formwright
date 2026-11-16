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
        "name": "Drawing Studio", "status": "preview", "icon": "ruler",
        "summary": "Generate manufacturing drawings from your model: orthographic and section views, "
                   "dimensions, hole callouts, title block and BOM.",
        "bullets": ["3-view + isometric layouts", "Spec vs inferred dimension tags", "PDF / DXF export",
                    "Associative updates on model change"],
    },
    "image2cad": {
        "name": "Image & Drawing to CAD", "status": "preview", "icon": "scan",
        "summary": "Turn a photo, sketch or legacy drawing into an editable model. Ambiguities and missing "
                   "dimensions are flagged instead of guessed.",
        "bullets": ["Sketch / photo / PDF input", "Missing-dimension questions", "Confidence per feature",
                    "Editable parametric output"],
    },
    "assembly": {
        "name": "Assembly Studio", "status": "preview", "icon": "boxes",
        "summary": "Multi-part assemblies with mates, interference checks, degrees-of-freedom analysis, "
                   "exploded views and BOM.",
        "bullets": ["Mates & joints", "Interference / clearance checks", "Exploded views", "Assembly STEP + BOM"],
    },
    "manufacturing": {
        "name": "Manufacturing Advisor", "status": "preview", "icon": "factory",
        "summary": "Design-for-manufacture checks per process, process recommendations and cost-driver "
                   "suggestions tied to model features.",
        "bullets": ["CNC, turning, sheet metal, AM, casting rules", "Process recommendation",
                    "Cost & setup reduction ideas", "Manufacturability report"],
    },
    "engineering": {
        "name": "Engineering Advisor", "status": "preview", "icon": "gauge",
        "summary": "Load cases, failure modes and recommended analyses with clear evidence levels. "
                   "Engineer sign-off is always required.",
        "bullets": ["Load case & failure-mode checklist", "Deterministic calculators",
                    "Material library with provenance", "Sign-off workflow"],
    },
    "print": {
        "name": "3D Print Prep", "status": "preview", "icon": "printer",
        "summary": "Watertightness, wall thickness, overhangs and orientation suggestions before you slice.",
        "bullets": ["Manifold & wall checks", "Overhang map", "Orientation ranking", "3MF / STL export"],
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
