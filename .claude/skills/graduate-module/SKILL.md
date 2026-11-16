---
name: graduate-module
description: Turn a Formwright Preview module into a real Live one, honestly: Drawing Studio (DRW-*, the next planned module), Assembly Studio (ASM-*), 3D Print Prep (PRN-*), Manufacturing Advisor (MFG-*), Engineering Advisor (ENG-*), Image & Drawing to CAD, Mesh Studio. Use when planning or building any module beyond the Design Studio, or when changing Live/Preview/SAMPLE labelling.
---

# Graduating a module from Preview to Live

ADR-016: Preview modules are honest placeholders. Their pages show illustrative output labelled **SAMPLE**, and
nothing is presented as generated from user data. A module becomes **Live** only when it produces real output from
the user's model and that output is gated by deterministic checks.

## Where the state lives
- `src/aicad/platform/catalog.py` → `MODULES[code]["status"]` (`"live"` | `"preview"`), plus summary and bullets.
  Codes: `design`, `drawings`, `image2cad`, `assembly`, `manufacturing`, `engineering`, `print`, `mesh`.
  Add-ons (`addon_<code>`) gate access through entitlements. Prices are hypotheses (PD-02).
- UI: `StatusBadge` (`web/src/components/ui.tsx`), `Modules.tsx` / module page, `ModuleSamples.tsx` (SAMPLE output),
  sidebar dot (`AppLayout.tsx`), command palette, landing page and pricing copy.

## Bar for flipping to Live
1. **Real pipeline from the user's model**, reachable from the Studio (prefer a Studio tab or CommandManager entry over
   a separate app). Keep SOLIDWORKS-like conventions.
2. **Deterministic acceptance checks** registered alongside CHK-02..09 with unit tests: pass fixtures and seeded
   failure fixtures. Use the IDs in `docs/VALIDATION.md` (Drawing: CHK-12; DFM: CHK-13 advisory).
3. **Honesty**: every output carries its advice level (VALIDATION §4; ENG-007), with spec vs inferred tags on
   dimensions and a "NOT APPROVED" banner on drawings. Never claim manufacturing or engineering validity, and never
   invent tolerances, GD&T, loads or material values.
4. Remove SAMPLE content only from the surfaces that now show real output. Leave the rest labelled.
5. Update the module summary and bullets to what is actually shipped (no roadmap bullets on a Live card), the
   punch-list rows with evidence, and an ADR in `docs/DECISIONS.md` recording the graduation.
6. Run a browser walkthrough (`studio-e2e`) on a demo part.

## Drawing Studio (next): starting points
Punch list DRW-001..006 is the M1 slice:
- HLR orthographic + iso views to SVG, with extents matching the bbox (CHK-12)
- dimensions from model PARAMS and features (tagged spec/inferred)
- hole callouts from the feature census
- title block
- PDF export (license-cleared library, LEG-002)
- no-overlap layout check

build123d ships hidden-line projection (`Shape.project_to_viewport`) and `ExportSVG`/`ExportDXF`. Confirm the
signatures in the installed 0.13 source before designing around them (see `build123d-kernel`). The feature tree
(`fw.feature` provenance) and `topo.json` already give named features and exact hole radii, so dimension from those
rather than re-recognising. Associative regeneration (DRW-015) follows from rebuilding on each model build.
