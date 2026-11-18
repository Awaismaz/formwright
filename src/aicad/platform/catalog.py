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
        "name": "Mesh Studio", "status": "live", "icon": "shapes",
        "summary": "Product renders of your verified parts: finishes mapped from the material, studio lighting, "
                   "turntables and visualisation meshes. For presentation, not engineering geometry.",
        "bullets": ["Photoreal renders in anodised, steel, brass, plastic and rubber finishes",
                    "Studio, dark and technical-white lighting; hero, iso, front and top views",
                    "Turntable GIF / MP4 and transparent PNGs",
                    "Editable .blend plus GLB / OBJ / STL visualisation meshes"],
    },
    "airender": {
        "name": "AI Render Studio", "status": "live", "icon": "sparkles", "beta": True, "byo_key": True,
        "tags": ["Beta", "Uses your OpenAI key"],
        "summary": "Marketing visuals of your verified parts made with OpenAI image generation on your own OpenAI "
                   "key. A render of the real model is always the reference, but the images are AI-generated and "
                   "illustrative, not dimensionally exact.",
        "bullets": ["Scenes from studio packshot to workshop bench, installed or in-hand",
                    "Finish pre-filled from the part's material; lighting, camera, background and style",
                    "Review and edit the prompt before anything is sent",
                    "Variants, variations and PNG downloads, each captioned as AI-generated"],
    },
}

TOKEN_COSTS = {
    "design_run_min": 1,       # minimum per agent run
    "design_run_preflight": 20,  # balance required to start a run (or an image read)
    "usd_per_token": 0.01,     # metering: tokens = ceil(estimated compute USD / usd_per_token)
}

# One written line per add-on (never a slice of the module summary). Honesty notes stay in the line.
ADDON_TAGLINES = {
    "drawings": "Drawing sheets from your verified part: views, a section, dimensions and a title block, marked "
                "not approved for manufacture.",
    "image2cad": "Rebuild a part from a PDF drawing, scan, sketch or photo. Every value read is shown for review "
                 "before modelling.",
    "assembly": "Assemble your parts with honest mate status, exact interference checks, a BOM and fastener "
                "auto-fit.",
    "manufacturing": "Advisory DFM checks on your exact model, a process shortlist and a relative cost estimate "
                     "(not a quote).",
    "engineering": "Hand-calculation checks (beams, bolts, shafts, fits) with the working shown. Estimates, never "
                   "validation.",
    "print": "Watertightness, wall thickness, overhang and orientation checks before you slice. Not a slicer.",
    "mesh": "Product renders and turntables of your parts, for presentation, not engineering geometry.",
}

DEFAULT_PRODUCTS: list[dict[str, Any]] = [
    # plans
    {"code": "trial", "kind": "plan", "name": "Free trial", "tagline": "Every module, on your own parts",
     "price_cents": 0, "interval": None, "tokens": 1000, "seats": 1,
     "modules": [c for c, m in MODULES.items() if m["status"] == "live"],
     "features": ["1,000 trial tokens: about 3 new parts", "Every module on your own parts", "STEP / STL export",
                  "14 days, no card"],
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
    # extra seats (Team plan)
    {"code": "seat_team", "kind": "seat", "name": "Extra seat", "tagline": "One more teammate on the Team plan",
     "price_cents": 3900, "interval": "month", "seats": 1, "features": ["Shares the pooled Team tokens"], "sort": 30},
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
        p.setdefault("tagline", ADDON_TAGLINES[p["modules"][0]])
        p.setdefault("features", m["bullets"])

# Shipped defaults that changed. A stored row is upgraded only while it still holds the old default, so edits made
# in the admin catalog are never overwritten.
_OLD_DEFAULTS: dict[str, dict[str, Any]] = {
    "trial": {"tokens": 300, "modules": ["design"], "tagline": "Try the full design loop",
              "features": ["300 trial tokens", "Design Studio", "STEP / STL export", "14 days"]},
}


def _truncated_summary(tagline: str, module: str) -> bool:
    """Old add-on taglines were the module summary cut at 190 characters, often mid-word."""
    summary = MODULES.get(module, {}).get("summary", "")
    return bool(tagline) and len(tagline) <= 190 and summary.startswith(tagline) and tagline != summary


def seed_catalog(db: Session) -> None:
    for p in DEFAULT_PRODUCTS:
        row = db.get(Product, p["code"])
        if row is None:
            db.add(Product(**p))
            continue
        for field, old in _OLD_DEFAULTS.get(p["code"], {}).items():
            if getattr(row, field) == old:
                setattr(row, field, p[field])
        if p["kind"] == "addon" and _truncated_summary(row.tagline, p["modules"][0]):
            row.tagline = p["tagline"]
    db.commit()


def product_dict(p: Product) -> dict[str, Any]:
    return {k: getattr(p, k) for k in ("code", "kind", "name", "tagline", "description", "price_cents", "interval",
                                       "tokens", "seats", "modules", "features", "highlight", "contact_sales",
                                       "purchasable", "active", "sort")}
