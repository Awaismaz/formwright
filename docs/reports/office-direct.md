# Design Office: parts built from the interface spec (no AI)

Branch `wip/office-direct`. Goal (founder): make part modelling in the Design Office substantially faster, without the
LLM wherever the structure allows it.

## What changed

**The direct path.** When a ticket's part is fully fixed by the approved ICD and skeleton, the Design Office writes the
Studio model script itself and builds it through exactly the gate an agent's build goes through. No model call, no
tokens, seconds instead of minutes.

- `src/aicad/office/direct.py` (new, pure, no kernel): `plan(doc, ticket)` decides per ticket and writes the script.
  - **Shafts**: the diameter profile from the interfaces (bearing journals, gear / hub seats, shoulders where a journal
    is turned down below the shaft Ø), DIN 6885 keyseats on the side the key interface states, 45° end chamfers, R0.5
    shoulder fillets where there are shoulders. Every face the ICD states (end face flush with a plate, bearing
    shoulders) is checked to be an end or a shoulder of that profile.
  - **Spacers / sleeves / collars / bushes** (a hub-role item named so): a bored ring to the envelope, 0.5 mm edge breaks.
  - **Spur gears** that the Toolbox doesn't supply: module, teeth, face width, pressure angle, bore, and the hub keyway
    (DIN 6885 t2) at the exact angle in the gear's frame (a gear turned half a pitch for its mesh has its keyway at
    -3°). True involute flanks through `fw.spur_gear`.
  - Everything else (blocks, plates, housings, pulleys, caps) goes to the design agent as before.
- **The script** is a normal Studio script: a docstring that lists every interface the part carries with its span,
  `NAME`, `MATERIAL`, one driving dimension per line, `PARAMS`, `PARAM_META` limits, `fw.stepped_shaft` /
  `fw.shaft_keyway` / `fw.spur_gear` with EXPECTED from their hand formulas. Segment lengths are dimensioned from the
  -Z end, the body takes up the rest of `LENGTH`, so an engineer can tune it in the Studio without tokens (parameter
  edit, viewport dimensions DS-038 map `LENGTH`, both diameters, journal lengths and the keyseat). No agent internals
  appear in it or in the chat.
- **The decision** (`plan`): direct only when the program's ICD is approved, the part is one of the kinds above, every
  ICD feature on it maps onto a generated feature, and the brief asks for nothing more. "Nothing more" is checked on the
  part's own description, plus program-brief sentences about that kind of part, for features the interfaces don't size
  (thread, groove / circlip, undercut, flat, cross hole, spline, knurl, set screw, hex, taper, slot, centre holes,
  helical teeth, hub on a gear, web / recess, seals, flange, special gear forms, a key the ICD doesn't size, a shoulder
  it doesn't place) and for sizes the interfaces don't explain (the part's own planned envelope statement, which the
  approved ICD supersedes, is not an extra). Anything not determined: the agent, with the reasons recorded. An
  incomplete or malformed ICD entry falls back the same way.
- **Seed.** When the interfaces fix the part and only such extras are missing, the direct model is built first and the
  agent is told to start from it and add only the extras (`direct.seed_prompt`).
- `orchestrator.py`: `_direct_plan` / `_direct` before the agent in the design stage. Direct runs on a ticket's first
  design turn, and again on an ICD change only while the model is still byte-for-byte the one it wrote (sha in
  `ticket.direct`): an engineer's or an agent's edit is never overwritten. Findings from Gage or the engineer's
  comments always go to the agent. A direct build that fails the gate falls back to the agent in the same stage.
  Gage still measures ICD conformance and the gating checks; the AI review note is skipped for an unchanged direct
  build (there is nothing in the brief beyond what is measured). Direct tickets don't teach the designer's rate
  (calibration), since seconds of building would skew the estimates.
- `platform_env.py`: `PlatformEnv.design_direct` writes `model.py` and builds through `tools.build_handler` (the design
  agent's build tool: CHK-02..05, topology and render now; exports, CHK-07, CHK-08 in the background on the same warm
  worker), awaits the deferred checks, snapshots the revision (kind `interface`), maps the viewport dimensions, and keeps
  the Studio chat busy meanwhile. `hex_lookup`: a designed gear whose ICD gives it a keyway is no longer taken from the
  Toolbox (the Toolbox gear has no keyway), so it is built direct instead.
- `fw_std.py`: backward-compatible options: `stepped_shaft(z0=)`, `spur_gear(z0=, keyway_angle=)`,
  `shaft_keyway(angle=)`. Defaults unchanged (Z from 0, keyways on +Y).
- Ticket UI (`TicketDrawer.tsx`, `Board.tsx`, `types.ts`): a "no AI" badge on the card; in the drawer "Built from the
  interface spec (no AI) in N s: shaft Ø20 × 120, … every size from ICD v1; 0 tokens", or "Designed with AI: <why>"
  (and whether it started from the interface model), or "Started from the interface spec; the designer has changed it
  since".
- Switch: `FW_OFFICE_DIRECT=0` (environment) or `direct_build: false` on a program turns the path off.
