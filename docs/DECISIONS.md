# Architecture Decision Records

Status values: **Proposed** (awaiting approval), **Accepted**, **Superseded**, **Rejected**, **Deferred**.
Each ADR: context, decision, alternatives, consequences, revisit trigger.

---

## Assumptions register

| ID | Assumption | Confidence | How to test | Owner |
|---|---|---|---|---|
| AS-01 | US design consultancies/machine shops will pay for reduced concept-to-drawing effort | Low (no evidence yet) | 5–10 pilot interviews (COM-001) | Founder |
| AS-02 | Simple prismatic machined parts are a frequent, time-consuming task for target users | Medium (founder experience) | Interview + time logs | Founder |
| AS-03 | A general LLM + deterministic CAD toolchain is good enough; no custom model needed | Medium | Benchmark EVAL-003 | Eng |
| AS-04 | Customers accept STEP (no native feature history) for M1–M2 | Medium | Pilot feedback | Founder |
| AS-05 | Customers will allow cloud LLM processing of non-sensitive designs | Low–medium | Pilot security questionnaire | Founder |
| AS-06 | OCCT is robust enough for the M1 feature set (extrude, pocket, holes, fillet, chamfer) | High | ARC-010 spike + fuzz tests | Eng |
| AS-07 | Server-side use of LGPL OCCT in SaaS is acceptable with dynamic linking | Medium | Counsel (LEG-003) | Counsel |
| AS-08 | Dev hardware (72-thread Xeon, RTX 8000) is not representative of production cost | High | Record CPU-seconds per job | Eng |

---

## ADR-001 — Precision geometry backend: build123d on OCP/OCCT
**Status:** Accepted 2026-11-16 (founder approval; spike ARC-010 passed) · **Date:** 2026-11-16
**Context:** Need B-rep solids, STEP AP214/AP242 export, projections for drawings, pip-installable, permissive enough for SaaS.
**Decision:** build123d as primary API; CadQuery permitted as secondary (same OCP kernel, already installed in base env).
**Alternatives:** CadQuery only (mature, larger corpus, slightly less explicit API); FreeCAD (feature history + sketcher but heavy, LGPL, harder to sandbox); direct OCP (too verbose for agent output).
**Consequences:** We own feature history, naming, assembly constraints, drawings. build123d small maintainer team → pin versions, wrap behind our compiler.
**Revisit if:** spike ARC-010 shows instability on Windows/Python 3.12, or FreeCAD's solver becomes necessary.

## ADR-002 — Agent output: typed Part Spec DSL, code generation gated
**Status:** Accepted 2026-11-16
**Context:** No container runtime on dev machine; need deterministic regeneration, edits, revisions, eval.
**Decision:** LLM produces JSON conforming to a versioned Part Spec schema (units, parameters, ordered features with IDs, semantic references, assumptions, open questions). Trusted compiler → build123d. Free-form code generation disabled until SEC-004 sandbox exists; then allowed as a fallback with stricter checks.
**Alternatives:** free-form code (max coverage, unsafe, hard to edit); pure DSL forever (coverage ceiling).
**Consequences:** DSL design becomes core IP; coverage grows feature by feature. Schema changes need migrations (approval gate).

## ADR-003 — M1 wedge: text/spec → prismatic machined part → STEP + drawing
**Status:** Accepted 2026-11-16 (founder: "Go ahead")
**Context:** User preference is image/drawing/text → part → STEP → drawing. Image input has high ambiguity and weak objective evaluation.
**Decision:** M1 input = text (and the structured spec itself). Part class = prismatic machined plates/brackets: base block, through/blind holes, hole patterns, rectangular pockets, slots, edge fillets/chamfers. Output = STEP, STL, GLB, renders, checks report, 3-view drawing (SVG/PDF), basic CNC DFM notes.
**Alternatives:** W2 image, W3 vector PDF, W4 STEP→drawing+DFM (ARCHITECTURE §4).
**Revisit:** after pilot interviews (COM-001); M2 picks W3 or W4.

## ADR-004 — Go-to-market surface: standalone web app with STEP interop first
**Status:** Proposed
**Decision:** Browser app; SOLIDWORKS/Creo bridges are backlog spikes, not M1.
**Consequences:** No native feature trees in customer CAD; honest disclosure required (STEP-in-SLDPRT is dumb solid).

## ADR-005 — Python environment: isolated uv venv, Python 3.12
**Status:** Accepted 2026-11-16 (implemented: `.venv`, Python 3.12.13, build123d 0.13.0 pinned, `uv.lock`)
**Context:** Base miniconda (3.13.9) already holds unrelated packages; modifying it risks other projects.
**Decision:** Project-local `.venv` via uv, Python 3.12 (widest wheel support for OCP/VTK; *verify* 3.13 later), lockfile committed.

## ADR-006 — Rendering: VTK/PyVista offscreen with fixed cameras
**Status:** Proposed
**Decision:** Tessellate B-rep (fixed tolerance), render iso + front/top/right at fixed resolution, deterministic lighting. Store camera params with images.
**Alternatives:** Blender render (GPL, heavier), pyrender/trimesh (fine; second option), Three.js headless (complex).

## ADR-007 — Execution isolation in M1
**Status:** Proposed
**Decision:** M1 executes only compiler-generated code in a subprocess with wall-clock timeout and memory guard; no LLM-authored code. Container sandbox (Docker Desktop or WSL2 + rootless containers) required before ADR-002 code fallback. Installing either needs approval.

## ADR-008 — Deployment and persistence
**Status:** Proposed
**Decision:** M1: single process, SQLite job/asset tables, local FS artifact store with content hashing. M2 pilot: single VM, Postgres, S3-compatible store, containerized worker. Scale only on evidence.

## ADR-009 — LLM provider abstraction
**Status:** Proposed
**Decision:** `LLMProvider` interface (structured output + vision). Implementations: Claude (primary), recorded/replay (CI default), stub for others. Log model ID, tokens, cost, latency per call. Default to latest capable Claude model, configurable.
**Note:** Anthropic commercial/API terms for this use need review (LEG-005); Claude Code subscription usage is a dev tool, not the product's runtime.

## ADR-010 — Mesh Studio deferred
**Status:** Deferred to M5
**Decision:** Blender as separate headless process only; never mixed with precision CAD paths. Benchmark against generative 3D models before committing.

## ADR-011 — Drawing generation approach (M1)
**Status:** Proposed
**Decision:** HLR projections (build123d/OCCT) → SVG; dimensions generated from Part Spec features (not inferred from geometry) and labelled by source: *spec* vs *inferred*. Title block with "NOT APPROVED FOR MANUFACTURE — ENGINEER REVIEW REQUIRED" until signed. PDF library chosen after license check (prefer permissive, e.g. reportlab BSD; avoid LGPL-3 cairosvg unless cleared).

## ADR-012 — Live local viewer instead of per-run checks in desktop CAD
**Status:** Accepted 2026-11-16 (founder request)
**Context:** Opening every STEP in SOLIDWORKS/Creo is slow and manual.
**Decision:** `aicad live` runs a stdlib HTTP server on 127.0.0.1 and serves a Three.js page. The page polls `status.json` and reloads `model.glb` whenever a build finishes. The GLB is tessellated from the **re-imported STEP**, not from the in-memory model, so the view reflects what the file contains. The page also shows kernel check results, measurements, a section plane and downloads. It is the seed of the M1b web viewer (UX-004).
**Alternatives:** OCP CAD Viewer for VS Code (`ocp_vscode`, works well with build123d, but it is a developer tool and cannot become the product UI); `occt-import-js` loading STEP in the browser (LGPL-2.1 WASM, same OCCT kernel, so no independence gained).
**Consequences:** Manual SOLIDWORKS/Creo checks drop from every run to periodic interop spot checks (EVAL-005). Our viewer reads STEP with the same OCCT kernel that wrote it, so it cannot catch reader-specific interop bugs. The page loads Three.js from a CDN, so it needs internet access; vendor it locally before any offline or customer use.

## ADR-013 — Agent engine: Claude Agent SDK (Claude Code harness) driving build123d code
**Status:** Accepted 2026-11-16 (founder). **Supersedes** the "DSL-only, no LLM-authored code" part of ADR-002 for the design agent, and **revises** ADR-009.
**Context:** The founder validated the concept with Claude Code's agentic loop (write code → run → render → inspect → fix). A plain chat API call does not reproduce that. The Claude Agent SDK ships the same harness as a library: built-in file tools, the agent loop, context management, subagents, hooks, permissions and sessions.
**Decision:**
- `aicad studio` runs one `ClaudeSDKClient` session per project workspace (`workspace/<project>/`).
- The agent writes build123d `model.py` following a contract (`result`, `EXPECTED` from hand calculation, `PARAMS`).
- It calls our in-process MCP tool `build_model`. That tool runs the script in a subprocess, exports STEP/STL/GLB, runs the deterministic checks, updates the viewer, and returns the check report plus a 4-view render image so the agent can critique its own result.
- Tools are a hard allow-list: Read, Write, Edit, Glob, Grep, TodoWrite, WebFetch (build123d docs host only), plus `build_model`. There is **no Bash**. A PreToolUse hook confines file paths to the workspace. `setting_sources=[]` isolates the agent from the developer's personal `~/.claude` config.
- **Auth (development only):** the local Claude Code subscription login. API credentials are stripped from the environment, so nothing is billed to an API account. **Production and any third-party user must use API-key auth**: Anthropic's Agent SDK docs disallow offering claude.ai login in third-party products unless previously approved (R-LIC-05).
**Typed DSL:** kept as a future option for structured parameter editing and for regeneration without an LLM. It is no longer the agent's output format.
**Consequences:**
- Matches the validated workflow.
- Accepts dependence on the Claude Code harness. The provider abstraction now lives at the tool boundary (`build_model` and the checks are provider-neutral), not at the loop.
- AI-written Python runs on the dev PC without a sandbox. Mitigations are a subprocess, timeout, stripped environment and an import tripwire, which is **not** a security boundary (R-SEC-05). A container sandbox (SEC-004) is required before any customer use.
**Evidence:** e2e run 2026-11-16 (SESSION_LOG c): L-bracket prompt → 3 turns, 38.4 s, all gating checks pass, auth = subscription login.

## ADR-014 — Formwright platform architecture (full product shell)
**Status:** Accepted 2026-11-16 (founder asked for a complete, production-grade, user-facing product before going deeper on CAD features)
**Decision:**
- One deployable: FastAPI (`aicad.platform.app`) serves the JSON API and the built React SPA from one origin.
- Persistence: SQLAlchemy 2. SQLite in dev (`data/formwright.db`), and any SQLAlchemy URL via `FW_DATABASE_URL` (Postgres planned).
- Auth: email + password (argon2). Opaque session tokens are stored hashed, in an HttpOnly SameSite=Lax cookie. Email-verification and reset tokens are hashed with expiries. CSRF uses a required custom header on every mutating API call. Security headers and CSP are set. Login, signup and reset are rate-limited.
- Tenancy: organizations, memberships and roles (owner, admin, engineer, viewer). Every project, ledger row and payment is scoped by org. Workspaces live on disk at `data/workspaces/<org>/<project>/`.
- Monetisation: a catalog of plans (subscriptions), add-ons (module unlocks as in-app purchases) and token packs. A token wallet with an append-only ledger. Agent runs are metered as `tokens = ceil(estimated compute USD / $0.01)`, with a 10-token preflight. Parameter edits and restores are free.
- Payments: Stripe Checkout, Billing Portal and signed webhooks when `STRIPE_SECRET_KEY` is set. Otherwise a clearly labelled **simulated** checkout is used, and it is refused in production.
- God mode: super-admin only, with bypasses, journey scenarios, demo seed and impersonation. The router 404s and the flags are ignored when `FW_ENV=production`.
- Frontend: React 18, TypeScript, Vite 6, Tailwind 3, Radix primitives, TanStack Query, three.js, driver.js and sonner. All pinned; `npm audit` reports 0 vulnerabilities.
**Alternatives:** Next.js with SSR (unneeded for an app behind login; the marketing site can move later); a hosted auth provider such as Clerk or Auth0 (vendor cost and data residency, so revisit for SSO/Enterprise); separate API and web origins (CORS and cookie complexity).
**Consequences:** No migrations yet (`create_all`), so Alembic is needed before the first production deploy (INF-008). In-memory rate limiting is single-process only.

## ADR-015 — Brand: Formwright
**Status:** Accepted 2026-11-16 (founder delegated the choice). Trademark and domain checks are parked (PD-01). See `docs/BRAND.md`.

## ADR-016 — Preview modules are honest placeholders
**Status:** Accepted 2026-11-16
**Decision:** Modules that aren't built (Drawing, Image-to-CAD, Assembly, Manufacturing, Engineering, Print, Mesh) appear in navigation, pricing and the app with a **Preview** badge. Their pages show illustrative output labelled **SAMPLE**, plus early-access sign-up and add-on unlock. Nothing is presented as generated from user data.
**Why:** The investor and customer demos must not misrepresent capability (master prompt §0.4).

---

## Parked decisions (need the founder; work continued with the defaults shown)

| ID | Decision | Default used meanwhile | Needed by |
|---|---|---|---|
| PD-01 | Final brand name: trademark, company and domain clearance for "Formwright" | Name used everywhere; domains are placeholders | Before any public launch |
| PD-02 | Pricing: Pro $49/mo with 1,500 tokens; Team $199/mo with 7,500 tokens and 5 seats; add-ons $9–29/mo; packs $10/$35/$150 | Editable in Admin → Pricing catalog | Before pilots pay |
| PD-03 | Token economics: 1 token = $0.01 of estimated compute; 10-token preflight; trial 300 tokens / 14 days | Implemented as configurable constants | After measuring real runs |
| PD-04 | Billing for **preview** add-ons: charge now, pre-order, or free reservation | Purchase unlocks the entitlement immediately (simulated payments only) | Before Stripe live mode |
| PD-05 | Data/AI policy wording (e.g. "never used to train models"), DPA and retention | Marketing copy avoids training claims; legal pages marked **Draft** | Before pilots |
| PD-06 | Stripe account (test keys, then live) and webhook endpoint | Simulated payments | When ready to take real payments |
| PD-07 | Email provider (SMTP / SES / Postmark) and sender domain | Local outbox + dev mailbox | Before inviting external users |
| PD-08 | Production hosting (single VM vs PaaS), Postgres provider, backups | Local only | Before pilots |
| PD-09 | Agent auth for anyone except the founder: Anthropic API key (or approved method) | Founder's Claude Code login (dev only) | Before the first external user (AGT-015) |
| PD-10 | Container sandbox for agent-written code (Docker Desktop or WSL2) | Subprocess + tripwire (not a sandbox) | Before the first external user (SEC-004) |
| PD-11 | Support and sales contact addresses | Placeholder `@formwright.dev` mailto links | Before launch |
| PD-12 | GitHub repo | **Resolved 2026-11-16:** founder created private repo `github.com/Awaismaz/formwright`; `main` pushed and tracking `origin/main` | Done |
| PD-13 | Toolbox catalogue scope and standards to license/verify (ISO table values typed from public references; verify before production) | 11 components, envelope-accurate, threads cosmetic | Before pilots |
| PD-14 | Feature recognition depth: in-house heuristics vs a commercial FR library | In-house heuristics + agent rebuild with CHK-09 | When customers import complex parts |
| PD-15 | 3D Print process limits (walls, holes, pins, clearances, bridges, overhang) | From 3D Hubs / Protolabs design-rule tables; build volumes, time constants, FDM 1.2 mm wall warning and resin density 1.15 g/cm³ are assumptions, editable and labelled in the UI | Before pilots |
| PD-16 | 3D Print permissions | Viewers analyse/download; engineers upload, repair, export, delete | When roles are reviewed |
| PD-17 | Uploaded-mesh retention/quota | Stored per workspace on disk, no retention or quota limit | Before external users |
| PD-18 | Module check numbering | 3D Print uses PP-01..17 internally; map to CHK-15+ later if a single catalogue is wanted | Optional |
| PD-19 | Manufacturing defaults & permissions | Shop defaults (Ø3 smallest tool, 50 mm reach, rates, MRR) shown as 'Assumed defaults' until saved; rule limits from public design guides; material prices are placeholders; owners/admins/engineers edit the profile | Before pilots |
| PD-20 | Engineering sign-off policy | Authors may self-sign (recorded and shown as self-check); engineer/admin/owner can sign, never while impersonating; no default safety factor (always user-entered with source); add-on stays $29/mo, not in Pro/Team | Before pilots |
| PD-21 | Drawing defaults | First-angle projection; A3, largest ISO 5455 scale that fits; tolerances 'Not specified' unless an ISO 2768 class is chosen; viewers view/download only; no token charge; drawing number FW-<project id 8>; spec tags blue upright, inferred brown italic (details DRW-PD-1..9 in docs/reports/drawings.md) | Before pilots |
| PD-22 | Studio modelling defaults | New body mirrors use the Right plane through the origin (SOLIDWORKS-like); draft pull points into the part from the neutral face (Reverse available); rollback bar covers manual features (agent steps use Suppress); ribbon Sketch defaults to 'Sketch only'; sweep/loft mitred, no twist/guides; rib symmetric | Review in use |
| PD-23 | Image & Drawing to CAD defaults | Vision read uses the full design-agent config and is metered like a run (~250 tokens; try a leaner prompt/model after an eval); low-confidence threshold 0.75; limits PDF 20 MB, image 12 MB, 40 MP, page 1, 90 s parse; 'Estimate (flagged)' only by explicit choice; agent may size undimensioned small features (listed as assumptions) but must ask if overall size or fit depends on them; uploads kept until deleted | Before pilots |
| PD-24 | Assembly defaults | Assemblies are their own documents per org (optional home project); parts pinned to builds, refreshed manually; protrusion ≥ 2·pitch, engagement 1.0/1.5/2.0·d (steel / cast iron & copper / Al, plastic, unknown), flagged VERIFY; default stack ISO 4017 + 2× ISO 7089 + ISO 4032, head up; checks/exports need engineer role; redundant consistent mates allowed | Before pilots |
| PD-25 | Mesh Studio (Blender) | Blender (GPL) runs only as a separate external process exchanging files; the two in-Blender scripts (`import bpy`) are kept isolated and not relicensed pending counsel (LEG-004); renders cost no tokens (add-on + queue caps); production needs a container with no network before untrusted input; default finish studio clay; cloud GPU cost not compared | Before external users / counsel |
| PD-26 | **Plan allowances vs measured run cost (founder call)** | Measured: a new part costs 260-281 tokens when the agent starts cold, about 45 when warm; a change about 26 (per-run cost; the old code also charged the session's running total). Trial raised to 1,000 tokens / 14 days ("about 3 new parts"). Plan allowances left unchanged: Pro 1,500/month is only about 6-35 new parts, so re-price the token unit or the allowances | Before pricing goes public |
| PD-27 | Run estimates and budget | Default estimate new part 40-400, change 20-280, replaced by the workspace's own history after 3 runs of a kind; per-run budget default 500 (50-5,000 in Billing, lowerable per run); charge capped at the budget (platform absorbs the last response's overshoot); Image to CAD preflight needs the upper measured figure (read 251, build 291) | Review with PD-26 |
| PD-28 | Trial access and first run | Running trial can use every Live module; afterwards Design Studio only (parts, edits, exports always open). Unconfirmed email: 24 h in the app, AI capped at 300 tokens, buying/inviting/seats need a confirmed email. Onboarding one optional screen | Before external users |
| PD-29 | Plan switches and seats | Unused time credited pro rata, new period starts today with the full allowance, leftover credit kept; included add-ons cancelled; seat overage warns, not blocks; extra seat $39/seat/month on Team (simulated); Stripe path written but untested without keys | Before real payments |
| PD-30 | Notifications | In-app bell only (no email digest): agent runs of 20 s or more, or stopped at budget; revisions by someone else on your project; long module jobs | Optional |
| PD-31 | Release gate (Issue Rev A) | Any editor can issue; issuing is not approval (drawings keep NOT APPROVED); a current drawing passing its check is required when the workspace has Drawing Studio; letters skip I, O, Q, S, X, Z; older sign-offs count as signed, unstamped print exports count as outdated | Before pilots (approver role) |
| PD-32 | Make module defaults after the audit | DFM score capped at 60 when a process is not analysed or has an open critical; clearance-hole fix targets ISO 273 medium; sheet-metal bend-radius table and Kt values flagged verify; sign-off bound to the model build | Before pilots |
| PD-33 | Assembly / Mesh / Image fixes | Fastener grip probes rings just outside larger coaxial holes (to about washer OD); "Insert anyway (will clash)" allowed; mate references follow a change on the same axis within max(0.5 mm, 2 % of diagonal), else reported broken; one-click hole fix only when exactly one parameter drives the hole; Mesh highlight protection lowers exposure up to 4 EV, at most two Blender processes | Before pilots |
| PD-34 | Studio audit defaults | Source (model script) view is superadmin-only; Ctrl+Z also undoes agent revisions, redo is per browser session; suppress/delete that would break a dependent feature is refused; SOLIDWORKS mouse mapping is the default (no setting yet); hole edge-distance guidance 1.5 d, counterbore depth and tap drill flagged verify; Toolbox creates a new part by default; three demo parts gained feature steps and parameter limits | Optional |
| PD-35 | Design Office agent names/avatars | Archie, Mill, Chuck, Axel, Benny, Molly, Hex, Fitz, Gage, Ortho, Smithy (docs/plans/CHIEF_DESIGNER.md §3) | Before CD-005 |
| PD-36 | Design Office default concurrency and program token budget | 3 parallel agents; budget set at program creation | Before CD-006 |
| PD-37 | Mandatory gates in a program | Brief + ICD + release mandatory; per-part review optional | Before CD-002 |
| PD-38 | Native CAD bridge target order after the SOLIDWORKS pilot | Onshape (no install), then Inventor, then Creo | When NCB-006 is done |
| PD-39 | Design Office Phase 2 defaults | Estimates: complexity 1–5 × minutes per unit (machined 4, turned 3.5, gear 4, sheet 4.5, plastic 5, standard 0.5, integration 3); ETA range = [0.8·max(critical path, work/N), 1.3·(critical path + work/N)]; Archie plan capped at 200 tokens, failures uncharged and fall back to the labelled standard breakdown; program budget default 3,000 tokens (display only until CD-016); Design Office labelled Preview; one Studio project per part ticket, one Assembly doc per integration ticket | Before CD-006 / CD-015 |
| PD-40 | Brief approval gate scope (CAD-028) | Per-user setting, default on; only new parts (no builds) in Build mode; skipped after a brief is approved in the conversation, for module hand-offs (image → CAD) and recognition/rebuild; a brief turn is a normal metered run (kind `brief`) | Before pilots |
| PD-41 | First live EVAL-003 benchmark run | Not run (harness verified with dry replays only). Live run of all 20 prompts ≈ 5,000 tokens typical, up to 8,000; scoring = gates + bbox/volume/cylinder census; record cassettes with `--record` so later re-scoring is free | When the founder approves the spend |
| PD-42 | Landing page CAD-tool section: vendor logos | Founder chose launch-state copy ('Integrates with…'); our own icon tiles until official logo use is licensed (drop-in slot `web/public/landing/logos/<slug>.svg`); trademark notice kept. Legal review of landing claims before public launch | Before public launch |
| PD-43 | AI Render Studio defaults (MSH-013) | Model `gpt-image-2` (stable, custom sizes; `FW_AI_RENDER_MODEL` overrides, e.g. a gpt-image-2.5 variant); 1536×1024, Standard (`medium`) quality, 1 variant (max 4); camera "Match reference"; reference = newest Mesh Studio render, else an automatic Mesh Studio preview, else the build thumbnail; the Claude prompt polish is on by default and charged at its measured cost (min 1 token), template fallback is free; keys are managed by owners/admins, consent is per workspace by any engineer | Before external users |
| PD-44 | AI Render access and a platform OpenAI key | BYO key only: OpenAI bills the customer, so the module is included wherever the Design Studio is (trial and every plan), with no add-on price. No platform key is offered yet; offering one later means metering image tokens into Formwright tokens and a content-policy review | Before pricing goes public |
