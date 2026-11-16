# Opportunities: what mechanical people would love and pay for

Founder direction (2026-11-16): not a SOLIDWORKS clone. Build distinctive, polished experiences inside the existing
major sections. Quality over quantity; finish every detail; don't clutter.

## What the research says (2026-11-16)
- **Hunting for existing parts.** Engineers reportedly spend ~12 h/week looking for models they (or colleagues)
  already made, then remodel because finding is slower than redoing.
  ([Leo AI](https://getleo.ai/blog/why-do-mechanical-engineers-hate-designing-products), vendor source)
- **Design changes get lost on the way to the shop.** About 43 % of design-review feedback is never documented or
  acted on. Teams record *what* changed but not *why*. Machinists keep working from the old print after a
  revision is approved. ([Colab](https://www.colabsoftware.com/post/biggest-mistake-late-stage-design-changes),
  [Onshape](https://www.onshape.com/en/blog/pain-free-design-reviews-engineering-change-orders-ecos),
  [ENGINEERING.com](https://www.engineering.com/engineering-change-orders-and-the-problem-of-two-systems/))
- **AI CAD isn't production-grade.** Testers found text-to-CAD tools overwrite the previous model (no side-by-side
  variants), lose dimensional accuracy on gears and manifolds, export unreliably, and lack parametric control and
  assemblies. ([Wevolver test of 7 tools](https://www.wevolver.com/article/we-tested-7-text-to-cad-tools-are-they-actually-useful-for-engineers))
- **Drawing errors are predictable.** They include missing or over-constrained dimensions, a single title-block
  tolerance applied to everything, thread runout, square internal corners and title-block gaps. Teams want
  automatic dimensioning and automatic checks so humans judge only the nuanced parts.
  ([Colab](https://www.colabsoftware.com/post/ai-for-manufacturing-drawing-checks-a-guide-for-engineering-teams),
  [Modus](https://www.modusadvanced.com/resources/blog/common-cnc-machining-drawing-errors-that-kill-your-lead-time-and-how-to-avoid-them),
  [Five Flute checklist](https://www.fiveflute.com/assets/Five-Flute-Part-Drawing-Checklist-2022-12-03.pdf))
- **Classic CAD gripes**: ease of use, price vs. value, interoperability, and suppression that cascades to children.
  ([Onshape](https://onshape.com/en/blog/4-top-reasons-engineers-hate-their-cad-system),
  [ENGINEERING.com](https://www.engineering.com/?p=22553),
  [Eng-Tips wish list](https://eng-tips.com/threads/whats-your-most-desired-enhancement.179140/page-2))

## What we build (ranked by delight × fit × effort)
| # | Section | Opportunity | Why it is distinctive | Status |
|---|---|---|---|---|
| O-1 | Platform | **Find similar parts**: a shape-signature search across every project (size, volume, holes, features), plus "search by size" (e.g. `plate 120x80`) | Reuse instead of remodel; no mainstream CAD answers "have we made this before?" without PDM | In progress |
| O-2 | Design Studio | **Change notice**: every revision explains *what* changed (parameters, features, volume/mass and size deltas, added/removed material) and *why* (the user's request or the agent's summary). One-page notice for the shop | Kills the "machinist works from old print" failure; ECO tools need a separate PLM | Planned |
| O-3 | Design Studio | **Design variants**: fork the current design into named variants and compare mass, cost, volume and size side by side, with a 3D overlay; promote the winner | AI CAD tools overwrite; engineers need trade studies | Planned |
| O-4 | Platform | **Shop handoff pack**: one click gives STEP + drawing PDF + DFM summary + change notice + manifest with hashes | One coherent, verifiable release package without PLM | After wave-1 merge |
| O-5 | Drawing | **Drawing check**: a checklist run against each sheet (title-block completeness, untoleranced dims, thread callouts, missing views) | Automates the predictable reviewer comments | Drawing agent (CHK-12) + follow-up |
| O-6 | Design Studio | **Deterministic edits everywhere**: suppress/delete/reorder agent steps without AI; parameters with live limits | Founder principle: AI where it helps, never as a toll | Done (suppress/delete, 49c0f02) |

Principles: every output carries its evidence (numbers, checks). Nothing is shown that we can't verify. Nothing
is added to the UI that doesn't earn its pixels.
