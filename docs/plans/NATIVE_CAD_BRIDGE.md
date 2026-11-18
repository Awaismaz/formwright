
# Plan: Native CAD Bridge (SOLIDWORKS first, then Onshape, Inventor, Creo)

Status: **backlog** (founder request 2026-11-18). Pilot: **SOLIDWORKS**. Punch list: `NCB-*`, plus the existing
CAD-070/071/072 and LEG-006.

## 1. Goal

A Formwright model arrives in the engineer's own CAD system as a **real parametric part** — sketches, features,
dimensions and named global variables in the tree, not a dumb STEP body. Everything Formwright does today stays the
same: the agent, the deterministic checks, the revisions and the verification. The native CAD system becomes one
more output, and it is verified the same way.

### Until then: the STEP pathway (CAD-070, live)
"Export for SOLIDWORKS" (Studio Files panel, Projects menu, `GET /api/projects/{id}/export/solidworks`) gives a zip:
a STEP (AP214 default or AP242, mm, one product named after the part, material colour) that is read back and compared
with the verified build before it is offered, the parameters as CSV, and a README. The UI and the README say plainly
that SOLIDWORKS imports it as a **dumb solid with no feature history** and that native trees are this plan's job.
Whether SOLIDWORKS 2025 opens it is the founder's periodic manual check (EVAL-005); Formwright never claims it.

## 2. Key design decisions

### 2.1 A neutral feature recipe (Feature IR) is the single source
Today, two kinds of model live side by side:
- agent models are free build123d code;
- manual features are already structured operations (`fw` ops).

A native bridge needs a structured recipe. So the bridge adds a **Feature IR** that `fw` records while a model
builds. It contains, in order:
- reference planes and sketches (entities + constraints + dimensions);
- extrude, cut, revolve, sweep, loft;
- Hole Wizard holes (standard, size, type);
- fillets and chamfers (with the edges they act on);
- patterns, mirror, shell, draft, rib;
- named parameters with their formulas.

Each IR operation records how to find the faces and edges it uses again by location, not by a fragile topology
index.
- Manual features and Toolbox generators already map onto this cleanly.
- The design agent is taught to model through `fw` feature calls whenever the user wants native export, so its
  models record IR too. Free-form code still works, but it exports as a native body only, labelled honestly.
- Imported STEP stays the exact "Imported blank" plus the recognised features. In SOLIDWORKS the blank can also be
  handed to **FeatureWorks**, SOLIDWORKS's own recognition tool, as a fallback.

### 2.2 Translators per CAD system, same IR
| Target | API | Where it runs | Notes |
|---|---|---|---|
| **SOLIDWORKS** (pilot) | SOLIDWORKS API (COM) | Local connector on the user's PC, using the user's licence | Sketches, FeatureManager, Hole Wizard, Equations / Global Variables, custom properties |
| Onshape | REST API + FeatureScript | Cloud to cloud, **no local install** | OAuth to the user's Onshape account; features built in a Part Studio |
| Inventor | Inventor API (COM) | Local connector | Same shape as the SOLIDWORKS translator; parameters become User Parameters |
| Creo | Creo Toolkit / J-Link | Local connector | Licence for the toolkit may be needed (LEG-006) |

### 2.3 Formwright Connector (the local agent)
- **What it is:** a small, signed Windows app installed by the user. It pairs with their Formwright account, one
  time, with a code shown in the app.
- **Connection:** it connects **outbound** only, over a websocket. No open ports, and nothing works without the
  online account (founder requirement).
- **What it runs:** only signed translator jobs, which apply a Feature IR, export, and read back. It never runs
  arbitrary code. Each job needs consent: "Open in SOLIDWORKS" in the app → the job appears in the connector →
  it runs.
- **Discovery:** it detects installed CAD versions (e.g. SOLIDWORKS 2025) and reports capabilities.

### 2.4 Same verification methodology
After the native rebuild, the connector exports STEP from the CAD system and sends it back. Formwright then runs
the **same checks** used for STEP:
- CHK-09 symmetric-difference volume against the Formwright model;
- bounding box, volume and solid count;
- parameter values read back from the CAD system's equations.

The result appears on the project as a "SOLIDWORKS native: verified (Δvol 0.000 %)" badge, or as a precise list
of mismatches. Nothing is claimed equivalent without this round trip.

### 2.5 Later: both directions
Read a native feature tree back into the Feature IR. The user could then edit in SOLIDWORKS, sync to Formwright,
and keep using the agent, checks, drawings and Design Office. This comes after the one-way pilot is solid.

## 3. SOLIDWORKS pilot (phases)

| Phase | Delivers |
|---|---|
| 0. Spike | Python/COM on the founder's machine (SOLIDWORKS 2025 is installed): create a part, sketch, extrude, Hole Wizard, fillet, global variable, export STEP; report on feasibility, speed and API limits (closes CAD-071) |
| 1. Feature IR | `fw` records the IR for manual features, Toolbox parts and IR-mode agent models; IR schema + versioning; analytic tests |
| 2. Translator | IR → SOLIDWORKS for the core set (planes, sketches with constraints and dimensions, extrude/cut, revolve, Hole Wizard, fillet/chamfer, patterns, mirror, shell); parameters become Global Variables; feature names match the Formwright tree |
| 3. Connector | Signed Windows app, account pairing, job queue, consent, CAD detection, logs |
| 4. Verified round trip | Export STEP from SOLIDWORKS → CHK-09 + read-back of parameters → "native verified" badge |
| 5. Assemblies + drawings | Assemblies with mates; drawings (later) |

## 4. Risks and decisions
- **Licensing (LEG-006):** API and EULA terms for automating the user's own CAD licence. This needs review before
  any external pilot. The founder's own use for the spike is fine to try.
- **Feature coverage:** anything outside the IR becomes an imported body inside the native part. It is always
  labelled, never hidden.
- **Version drift:** translators are tested against specific CAD versions; the connector reports the version.
- Parked: PD-38 the order of targets after SOLIDWORKS (default: Onshape next, because it needs no install, then
  Inventor, then Creo).
