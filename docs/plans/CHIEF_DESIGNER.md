# Plan: Formwright Design Office — Chief Designer, specialist agents, live program board

Status: **proposed** (2026-11-18). Owner: founder. Punch list: `CD-*` rows, plus ASM-010 / ASM-019.

## 1. The idea in one paragraph

The user runs Formwright like a mechanical product design company. They hand a **program** (a product or machine)
to the **Chief Designer**. The Chief writes the design brief, breaks the product into sub-assemblies and parts,
fixes the **interfaces** between them first, and opens a **ticket** per part or sub-assembly. Named **specialist
agents** pick up tickets in priority order and build in parallel. Standard parts come from the Toolbox, and existing
parts come from the company library. The assembly starts **before every part is finished**: placeholder bodies sit
at their interfaces and are swapped for the real parts as each one passes its checks. The user watches the work
move across a Jira-style board, with time estimates per ticket that roll up to sub-assembly and program. They
approve at a few gates, as an engineering manager would.

## 2. What makes this work (the refinements)

### 2.1 Interfaces first, a skeleton model, and placeholder bodies
Parallel part design only works if the parts fit the first time. Real design offices manage this with a layout or
skeleton model and an interface control document (ICD). The Chief therefore produces, before any part ticket opens:
- **Skeleton:** overall envelope, datums, main axes, the program coordinate system.
- **ICD:** every interface between two items, with named, numeric data. Examples: "bracket-to-base: 4 × M6
  clearance on 80 × 40 pattern, mating face Z = 10, datum A", "shaft Ø25 h6 at bearing seat".
- **Placeholder bodies:** an envelope solid for each part, with its interface features (holes, bores, faces)
  carrying the ICD names.

Part agents build against the ICD. The Assembly agent mates the **placeholders by ICD names**, so the assembly
exists from minute one. When a real part passes its checks it **replaces** its placeholder, and the mates reattach
by name because the ICD gives stable names. This is how the assembly runs in parallel with part building. It also
largely sidesteps topological naming (CAD-007) at assembly level.

### 2.2 Interface changes go through an engineering change request
A part agent that needs to change an interface may not do so silently. It raises a **change request** ticket. The
Chief accepts or rejects it, updates the ICD and puts the affected tickets back into work. Every change is
recorded. This keeps parallel agents consistent and gives the user the audit trail a real company has.

### 2.3 Reuse before design
Before a part ticket is designed, the **Librarian** searches in this order:
1. the Toolbox, which is deterministic and costs no tokens;
2. the company's own parts, using the existing similarity search;
3. only then a new design.

Reused items go straight to Done. The same Librarian powers the founder's request that the **Assembly
environment picks Toolbox components or your own parts automatically** (ASM-019).

### 2.4 Priority = critical path
Tickets form a dependency graph. An interface-defining part, such as a base frame, unblocks others. Priority is
the critical path: the longest chain of estimated work first, ties broken by how many tickets a part unblocks.
Standard and reused parts resolve instantly. A concurrency cap (default 3 agents) keeps cost and rate limits under
control.

### 2.5 Honest estimates and progress
- **Estimate per ticket:** a complexity score (feature count from the brief, part family, tolerance class) times a
  calibrated time per unit. It starts from measured agent runs and **recalibrates after every completed ticket**,
  so estimates improve with use.
- **Progress per ticket** comes from real agent milestones, not a timer. The weights are: brief read 5 % · first
  build 35 % · gating checks pass 70 % · self-review 85 % · Checker approved 100 %.
- **Roll-up:** sub-assembly and program progress are effort-weighted (sum of done effort over sum of estimated
  effort). The integration work at each assembly level counts as its own effort.
- **ETA:** the remaining critical path divided by available concurrency. It is shown as a range, never a promise.

### 2.6 Independent checking
No agent approves its own work. The **Checker** reviews every part ticket before Done:
- gating checks;
- ICD conformance (the interface features measured against the ICD numbers);
- drawing round-trip;
- DFM flags.

The Checker is an independent reviewer with its own instructions. It can send work back with findings.

### 2.7 The user is the engineering manager
- **Gates:** brief approval (closes CAD-028) → architecture + ICD approval → optional per-part design review →
  release.
- **Tickets:** the user can comment on, reprioritise, reassign or reopen any ticket. A comment reaches the working
  agent as a message.
- **Open any ticket:** this lands in that part's normal Design Studio project, with the agent's full chat history.
  Nothing is hidden or locked away. The user can also take over by hand.

## 3. The company (agent roster)

Names read like people but carry a mechanical pun, so each specialty is obvious and the office feels alive
(founder direction 2026-11-18: "Mill" and "Chuck" kept; component names rejected). Each is a configured agent role:
instructions, allowed tools, default model/effort, a tool-glyph avatar and a colour.

| Name | Role | Wordplay | Example status line |
|---|---|---|---|
| **Archie** | Chief Designer | Archimedes, the original engineer | "Archie is splitting the gearbox into 3 sub-assemblies" |
| **Mill** | Machined (prismatic) parts | the milling machine | "Mill is pocketing the motor plate" |
| **Chuck** | Turned parts | the lathe chuck | "Chuck is turning the Ø25 output shaft" |
| **Axel** | Gears, pulleys, drives | axle | "Axel is hobbing 40 teeth, m3" |
| **Benny** | Sheet metal (after CAD-026) | bend | "Benny is bending the cover, 4 flanges" |
| **Molly** | Plastic / moulded parts | mould | "Molly is adding 1.5° draft to the housing" |
| **Hex** | Librarian: Toolbox + company parts | hex bolts, the standard-parts shelf | "Hex found a 6204 bearing in the Toolbox (0 tokens)" |
| **Fitz** | Assembly | makes things fit | "Fitz mated 14/18 parts, 0 clashes" |
| **Gage** | Checker (independent) | gauge | "Gage sent Bracket back: bore Ø25.4 ≠ ICD Ø25 H7" |
| **Ortho** | Drawings | orthographic projection | "Ortho is dimensioning sheet 2 of 5" |
| **Smithy** | Manufacturing review | the blacksmith's shop | "Smithy flagged a 0.5 mm wall as too thin to mill" |

### 3.1 Avatars and working animations (founder requirement 2026-11-18)

Every agent has an illustrated avatar: a round badge in the agent's colour carrying its tool, with a small face
or character. Avatars are animated by **state**, so you can see who is working at a glance on the board, the
roster, ticket cards and the Studio chat. Everything is SVG and CSS (no video), and has a static fallback when the
system asks for reduced motion.

| Agent | Avatar | "Working" animation |
|---|---|---|
| Archie | compass + blueprint | compass swings an arc across a blueprint |
| Mill | end mill over a block | the cutter spins and chips fly off |
| Chuck | three-jaw chuck | the chuck spins and a curl of swarf peels away |
| Axel | gear pair | the gears mesh at the correct ratio |
| Benny | sheet with a bend line | the sheet folds to 90° and springs back |
| Molly | mould halves | the halves close, a fill shimmer, then eject |
| Hex | hex nut on a bolt | the nut spins down the thread; a drawer of parts slides out while searching |
| Fitz | two parts with a dowel | the parts slide together and click |
| Gage | caliper | the jaws close on a part and the readout ticks |
| Ortho | pen and drawing sheet | the pen draws a view and a dimension line |
| Smithy | anvil and hammer | the hammer strikes and sparks fly |

States, shared by all agents:
- **idle:** gentle breathing.
- **working:** the role-specific animation above, plus a progress ring around the badge.
- **waiting for review:** a pulsing outline.
- **blocked / changes requested:** an amber shake once, then still.
- **done:** a check pops on the badge.
- **hand-off:** the avatar slides from one agent's lane to the next on the board.

Engagement: live present-tense status lines on cards (plain engineering language, never internals); visible
hand-offs ("Chuck → Gage for inspection", "Gage → Fitz: approved for assembly"); a "fitted" moment when a
placeholder turns solid; program milestones with a short celebration and summary ("All interfaces frozen",
"First article assembled", "Released"); a shop-floor roster with each agent's state and track record (parts
delivered, first-pass approval rate, average time vs estimate). Parallel instances show as Mill #1, Mill #2.

## 4. Screens (design-office UX)

1. **Office home:** programs in flight, team roster with status (idle / working on ticket X / waiting for
   review), today's approvals for you, token spend vs budget.
2. **Program board (Jira-style).**
   - Columns: Backlog → Ready → In design → In review → Changes requested → Approved → Integrated.
   - Swimlanes: one per sub-assembly.
   - Ticket card: part name, agent avatar, estimate bar (filled = progress, outline = estimate), checks badge,
     tokens spent, blocking/blocked links.
   - Cards move live as agents work.
3. **Program tree with roll-up:** program → sub-assemblies → parts, each with a progress bar, ETA range and
   status. Clicking a node opens the ticket or the assembly.
4. **Timeline:** Gantt-lite of the critical path and agent lanes, so you see why something is waiting.
5. **Assembly view:** the live program assembly. Placeholders are shown in translucent orange and turn solid as
   real parts arrive. Interference results update live.
6. **Interfaces (ICD) page:** each interface, its numbers, the parts on both sides, change-request history.
7. **Reviews inbox:** gates and change requests waiting for you, each with an Approve / Request changes action.

## 5. Architecture on what exists

- **Program data:** a program has a brief, skeleton, ICD, a tree of sub-assemblies and items, tickets, events
  and a budget. It is stored per org, like assemblies are.
  - Each part ticket owns a normal Design Studio project.
  - Each sub-assembly owns an Assembly Studio document.
  - Nothing is a parallel universe: every artefact is the same project, assembly, drawing and release you already
  have.
- **Orchestrator:** a server-side scheduler (asyncio) that keeps up to N part agents running. Each one is an
  existing `AgentSession` on its project, given the ticket brief + ICD excerpt + specialist instructions.
  - Milestones are derived from agent events (build results, checks).
  - Events stream to the board over server-sent events (SSE), like the Studio chat.
- **Archie** is an agent session with planning tools (in-process tools, like `build_model` today): `write_brief`,
  `define_interface`, `create_item`, `create_ticket`, `set_priority`, `decide_change_request`. Archie plans; it
  does not write CAD.
- **Hex** is mostly deterministic: Toolbox `match` + `similarity` search, with the agent consulted only when
  ambiguous.
- **Fitz** uses the assembly service: place placeholder → mate by ICD name → swap in the real part on Done →
  interference.
- **Gage:** the deterministic checks plus ICD conformance measurement (new, deterministic), plus an AI review
  note.

## 6. Delivery plan (phases, each shippable)

| Phase | Delivers | Punch list |
|---|---|---|
| **1. Smart assembly** | Assembly from a description: Hex picks Toolbox / company parts automatically, Fitz places and mates them, fastener auto-fit; "Add components by description" in Assembly Studio | ASM-010, ASM-019 |
| **2. Program + board** | Program model, Archie brief → tree → tickets (brief gate), Jira board with live cards, estimates, roll-up progress, roster | CD-001…CD-005 |
| **3. Parallel build** | Orchestrator with concurrency cap, specialist part agents on tickets, critical-path priority, Gage review loop, comments to agents | CD-006…CD-009 |
| **4. Interfaces + parallel assembly** | Skeleton + ICD, placeholder bodies, mates by ICD names, swap-in, change requests | CD-010…CD-013 |
| **5. Deliverables + learning** | Program drawings/BOM/DFM/release pack (Ortho, Smithy), estimate calibration, budgets, timeline | CD-014…CD-016 |

## 7. Risks and decisions

- **Parallel agents on one Claude Code subscription** may hit rate limits. The default is 3 concurrent agents,
  configurable. This sharpens PD-09: an API key is needed before this runs for anyone but you.
- **Cost:** a program can spend many tokens. Each program gets a budget with stops at 80 % and 100 %, and the board
  shows spend per ticket.
- **Divergence between agents:** mitigated by the ICD, Gage's ICD conformance check and change requests.
- **Estimates:** honest ranges, recalibrated from real runs, and labelled as estimates.

Parked for the founder (with the default used until decided):
- PD-35 agent names and avatars (default: the mechanical roster above, founder direction 2026-11-18);
- PD-36 default concurrency and program token budget (default: 3 agents, budget set at program creation);
- PD-37 which gates are mandatory (default: brief and ICD mandatory, per-part review optional, release
  mandatory).
