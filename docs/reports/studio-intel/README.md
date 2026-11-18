# Studio intelligence: DS-035 (agent fills the PropertyManager) and ASM-018 (change impact preview)

Branch `wip/studio-intel`, 2026-11-18. Defaults: PD-56.

## Browser walkthrough (replayed agent, zero model calls)
Throwaway data dir, port 8821, puppeteer-core 25.18.1, God mode (paywall/token bypass), `FW_AGENT_REPLAY=cassette.json`
(this folder; `walkthrough.mjs` is the script). Fixture: base plate 120 × 80 × 10 with 4 Ø6.6 holes (HOLES parameter),
40 × 30 × 20 block coincident on its top face, Ø6 × 30 pin concentric with the (50, 30) hole; one datasheet shot saved.

| Shot | What it shows |
|---|---|
| `01-studio-where-used-datasheet-chip.png` | Studio header: "In 1 assembly" and "1 render stale · Re-render" |
| `02-agent-param-edit-pm-and-chat-impact.png` | "remove the mounting holes" → agent replies with one short turn; the **Modify dimensions** PropertyManager opens pre-filled (HOLES 4 → 0); the chat card shows "This change affects 1 assembly: 1 mate breaks, 1 new clash" |
| `03-impact-panel-before-apply.png` | OK → impact panel: Concentric Base plate Ø6.6 hole ↔ Pin Ø6 cylinder breaks; new clash Base plate ↔ Pin 282.7 mm³ (= 90π); Apply anyway / Back (Back taken, nothing applied) |
| `04-agent-chamfer-pm-prefilled-highlighted.png` | "chamfer the top edges 1 mm" → real Chamfer PM, Distance 1, the 4 outer top edges (80/120/120/80 mm) selected and highlighted; card: "No problems found in 1 assembly" |
| `05-chamfer-applied-after-impact-check.png` | OK → impact check clean → applied through the manual-feature path (revision 2, "Chamfer added · 0.6 s"); volume 94,631.5 → 94,432.9 mm³ = −(L + W)d² + 4d³/3 = −198.67 mm³; "In 1 assembly · update" |
| `07-mesh-datasheet-pack.png` | Mesh Studio Datasheet tab: the shot "Not rendered yet", "Re-render stale (1)" |

Console / page errors: 0. Not clicked: the re-render button (it would queue a real Blender render).
