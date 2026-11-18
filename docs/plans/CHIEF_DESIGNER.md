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

Names are short, specialty-flavoured and easy to say. Each is a configured agent role: system instructions, allowed
tools, default model and effort.

| Name | Role | Does | Mostly uses |
|---|---|---|---|
| **Atlas** | Chief Designer | Brief, decomposition, skeleton + ICD, tickets, priorities, change requests, integration sign-off | Planning tools (no CAD writing) |
| **Mira** | Machined-parts designer | Prismatic milled parts: plates, brackets, housings, blocks | Design Studio agent |
| **Theo** | Turned-parts designer | Shafts, bushings, pins, spacers, hubs (lathe work) | Design Studio agent + Toolbox |
| **Gale** | Power-transmission designer | Gears, pulleys, keys, couplings, bearing seats | Toolbox generators + Studio |
| **Sheila** | Sheet-metal designer | Bent parts, covers, brackets (after sheet-metal features, CAD-026) | Studio |
| **Polly** | Plastics designer | Moulded/printed enclosures, bosses, ribs, draft | Studio |
| **Libby** | Librarian | Toolbox and company-part search, reuse, standard-part selection | Toolbox + similarity search, no tokens for matches |
| **Ada** | Assembly engineer | Placeholders, mates by ICD name, fasteners, interference and clearance, explode, BOM | Assembly Studio |
| **Vera** | Checker | Independent verification, ICD conformance, send-back with findings | Checks, measurement |
| **Drew** | Draftsman | Part and assembly drawings, BOM tables | Drawing Studio |
| **Forge** | Manufacturing reviewer | DFM, process and cost notes | Manufacturing Advisor |

Specialists can run more than one instance at once (Mira #1, Mira #2) within the concurrency cap. Agent avatars
show who is on which ticket.

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
- **Atlas** is an agent session with planning tools (in-process tools, like `build_model` today): `write_brief`,
  `define_interface`, `create_item`, `create_ticket`, `set_priority`, `decide_change_request`. Atlas plans; it
  does not write CAD.
- **Libby** is mostly deterministic: Toolbox `match` + `similarity` search, with the agent consulted only when
  ambiguous.
- **Ada** uses the assembly service: place placeholder → mate by ICD name → swap in the real part on Done →
  interference.
- **Vera:** the deterministic checks plus ICD conformance measurement (new, deterministic), plus an AI review
  note.

## 6. Delivery plan (phases, each shippable)

| Phase | Delivers | Punch list |
|---|---|---|
| **1. Smart assembly** | Assembly from a description: Libby picks Toolbox / company parts automatically, Ada places and mates them, fastener auto-fit; "Add components by description" in Assembly Studio | ASM-010, ASM-019 |
| **2. Program + board** | Program model, Atlas brief → tree → tickets (brief gate), Jira board with live cards, estimates, roll-up progress, roster | CD-001…CD-005 |
| **3. Parallel build** | Orchestrator with concurrency cap, specialist part agents on tickets, critical-path priority, Vera review loop, comments to agents | CD-006…CD-009 |
| **4. Interfaces + parallel assembly** | Skeleton + ICD, placeholder bodies, mates by ICD names, swap-in, change requests | CD-010…CD-013 |
| **5. Deliverables + learning** | Program drawings/BOM/DFM/release pack (Drew, Forge), estimate calibration, budgets, timeline | CD-014…CD-016 |

## 7. Risks and decisions

- **Parallel agents on one Claude Code subscription** may hit rate limits. The default is 3 concurrent agents,
  configurable. This sharpens PD-09: an API key is needed before this runs for anyone but you.
- **Cost:** a program can spend many tokens. Each program gets a budget with stops at 80 % and 100 %, and the board
  shows spend per ticket.
- **Divergence between agents:** mitigated by the ICD, Vera's ICD conformance check and change requests.
- **Estimates:** honest ranges, recalibrated from real runs, and labelled as estimates.

Parked for the founder (with the default used until decided):
- PD-35 agent names and avatars (default: the roster above);
- PD-36 default concurrency and program token budget (default: 3 agents, budget set at program creation);
- PD-37 which gates are mandatory (default: brief and ICD mandatory, per-part review optional, release
  mandatory).
