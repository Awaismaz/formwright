# Studio follow-ups: sheet-metal corners, cuts through bends, jog; fw-edit depth / pattern / multi; impact on tree actions

Branch `wip/studio-followups`, 2026-11-19. Defaults: PD-62 (sheet-metal defaults stay PD-60, agent edits PD-57).

## What was built
1. **Sheet metal (CAD-026 follow-ups)** in `src/aicad/sheetmetal.py`
   - Automatic corner relief where a new flange's edge ends on an existing flange's bend start line (adjacent edges,
     square corner, same panel). The earlier flange is cut back to the new bend start + w (w = relief ratio × T); a
     w × w square (rectangular relief) or radius-w circle (obround) is cut where the two bend start lines meet.
   - Closed corners (default, gap 0.2 mm; two 90° flanges bending the same way): the earlier wall runs on to `gap` short
     of the later wall's inside face, the later wall reaches the earlier wall's outer face. Open corners: walls stop at
     their bends. Base flange settings: `corner: {type, gap}` (Studio sketch editor: "Closed corners / Open corners", Gap).
   - Cuts through a bend appear in the flat: the bend's material is traced on the neutral surface (radius R + K·T) and
     unbent (x = φ·(R + K·T)); bends shortened by a corner keep their exact strip.
   - **Jog** (`sm_jog`, `fw.jog`, Sheet Metal ribbon "Jog"): pick a straight sheet edge, give the jog-line distance, offset
     (bottom face to bottom face) and angle ≤ 90°; the end between the edge and the line is raised (Flip lowers it) through
     two opposite bends; holes already in that end ride along. Middle length m from
     offset = (T + 2R)(1 − cos θ) + m·sin θ; the flat grows by 2·BA + m. Miter flange: not built (edge flanges with closed
     corners give the box case; PD-62).
2. **fw-edit coverage (DS-035)** in `src/aicad/agent/edits.py`: `op: extrude` (depth / end of an existing hand-made extrude
   or cut), `op: pattern` (count, spacing along the same direction, circular total angle; feature patterns and hole
   patterns), and several edits in one block (`{"summary", "edits": [...]}` or a JSON list, ≤ 8, every step checked
   before any opens). The Studio opens one PropertyManager per step in order (sketched extrudes open the sketch editor);
   the next step opens after OK and the rebuild; Cancel drops the rest. The chat card lists the steps and previews the
   impact of the whole sequence.
3. **Impact preview for tree actions and Ctrl+K (ASM-018)**: `POST /api/m/assembly/impact/{project}` now takes
   `suppress`, `delete`, `reorder`, `design_suppress`, `design_delete` and `sequence` (`studio.trial_source`). Tree
   suppress / unsuppress / delete / move up-down (hand-made features and the agent's own steps) and the typed commands
   (Ctrl+K: fillet / chamfer / shell / suppress) check first when the part is in an assembly and open the same
   "Apply anyway / Back" panel when something breaks.

## Tests (hand formulas)
- `tests/test_sheet_metal.py` (+11): corner area = base − s·W − s·(D − s) − w² + (W − s − w)·BA + (D − s)·BA + walls
  (closed: L·(W − T − g) and L·(D − s + R + T); open: L·(W − s − w), L·(D − s)) for closed/open × rect/obround/none; the
  gap g probed in the folded solid; a tray with two corners; a 10 × (3 + BA + 6) window through a bend; a radial Ø2.4 hole
  through a bend = ∫ 2√(ρ² − rn² sin²(s/rn)) ds within 0.5 % (sampled outline); jog 90°/60°/flipped (flat W + 2·BA + m,
  shift (2R + T)·sin θ + m·cos θ, z range); jog errors; Studio API corner + jog.
- `tests/test_studio_intel.py` (+5): extrude/pattern/multi parsing and errors; a replayed one-turn two-step edit applied
  through the manual endpoints (volume 24000 − 4·6·6·5 − 2·π·2²·10); `trial_source` for every tree action;
  fixture assembly: suppress / delete the pin hole = 1 mate breaks + 117π mm³ clash, reorder before the boss = 27π,
  a sequence (boss 3 → 2 mm, delete hole) = 108π + break, suppress the boss = nothing.
- vitest `studio/agentEdit.test.ts` (+4): depth / pattern prefill (spacing scaled along the step), multi steps and
  sequence impact, tree action → impact request mapping.

## Browser walkthrough
Throwaway data dir, port 8851, puppeteer-core 25.18.1, God mode, `FW_AGENT_REPLAY=cassette.json` (made by
`make_cassette.py`; zero model calls). Script: `walkthrough.mjs` (`ONLY=A|B|C` runs a part).

| Shot | What it shows |
|---|---|
| `01-jog-propertymanager.png` | Sheet Metal ribbon → Jog, left edge picked in the viewer (Line 60 mm), distance 20, offset 10, angle 90: "4 mm between them: the flat grows by 2 × BA + 4 = 13.048 mm" |
| `02-closed-corner-jog-window-folded.png` | Jog + back and right flanges meeting at a closed corner (gap 0.5) + a 10 × 10 window cut through the back bend; bbox 106 × 60 × 20 |
| `03-flat-pattern-relief-window-jog.png` | Flat pattern 129.6 × 76.5 mm: corner relief notch, the window across the bend line, bend table (Jog1 (1) UP, Jog1 (2) DOWN, two flanges UP, BA 4.524); no "not shown" note |
| `04-base-flange-corner-settings.png` | Editing the base flange: Rectangular relief ×T 0.5, Closed corners, Gap 0.5 mm |
| `05-agent-multi-edit-step1-extrude-pm.png` | "make the pockets 5 deep and four of them, 12 apart" → one replayed turn, card "Several changes" with 2 steps; step 1 opens Edit Extruded Cut with Cut depth 5 |
| `06-step2-pattern-pm-prefilled.png` | After OK (Pocket updated) step 2 opens by itself: Edit Linear Pattern, 4 instances, spacing 12 (preview markers) |
| `07-multi-edit-applied.png` | Both applied: volume 23,028.67 mm³ = 24000 − 720 − 80π |
| `08-tree-suppress-impact-gate.png` | Tree eye on "Pin hole" → "Suppress “Pin hole”?" panel: Concentric Base plate Ø6.6 hole ↔ Pin Ø6 breaks, new clash 367.6 mm³ (= 117π); Back |
| `09-ctrl-k-suppress-command.png` | Ctrl+K "suppress Pin hole" |
| `10-ctrl-k-impact-gate.png` | The same gate from the typed command |
| `11-applied-after-gate.png` | Apply anyway → "Pin hole suppressed", header "In 1 assembly · update" |

Jog numbers: flat 113.047787 × 60 (expected 100 + 2·BA + 4 = 113.047787), bbox 106 × 60 × 12.

Console / page errors: 0 (parts A+B and C run separately to the end). Fixed from the walkthrough: the multi-step queue
(next panel opens after the rebuilt geometry and the new build's feature list have loaded).
