# Platform audit fixes (PLT-01..34, IDEA-01, IDEA-02, IDEA-04)

Branch `polish/platform`. Audit: `docs/reports/audit/platform.md`. Walkthrough on port 8781 (isolated data dir
`$SCRATCH/fw-e2e-8781`), screenshots in `$SCRATCH/fw-e2e-8781/shots/` (`$SCRATCH` =
`C:\Users\awais\AppData\Local\Temp\claude\ae5066db278ece3d\6657173d-006b-4ae9-a4dd-ffbf9518d104\scratchpad`).
Two live agent runs were used (the founder's Claude login), both by the new user "Dana".

## Headline: what the money story is now

- **Root cause found beyond the audit.** The agent reports a cost that is *cumulative for the connected session*
  (confirmed in the Agent SDK's own field description: "cumulative across turns in streaming-input sessions"). The
  platform charged that number on every run, so every follow-up run on a project was charged for all earlier runs
  again. Runs are now charged the difference from the previous report (`AgentSession._run_cost`).
- **Measured costs** (ledger rows + agent cost reports in isolated workspaces):

  | Run | Tokens | Notes |
  |---|---|---|
  | New part, Mounting plate template (audit run) | 260 | agent starting cold, 289 s |
  | New part from a vector PDF drawing | 281 | cold, 1,941-character brief |
  | New part from a drawing image | 275 | cold, 3,075-character brief |
  | New part, Mounting plate template (this walkthrough) | **45** | 46 s, verified at 45 s |
  | Change: pocket 6 mm deep + R2 vertical edge fillets | **26** | same session, 46 s |

  Brief length barely moves the cost; whether the design context is already loaded moves it ~6×. Defaults are
  therefore an honest wide range: **new part 40–400 (typical 250), change 20–280 (typical 60)**, replaced by the
  workspace's own median and 10–90 % range after 3 runs of that kind (short and long briefs kept apart once there is
  enough history). Every run is recorded in a new `agent_runs` table (kind, brief size, budget, estimate shown,
  tokens charged, cost, verified, duration).
- **Trial = 1,000 tokens**: about 3 new parts even at the measured cold cost (3 × 281 = 843), plus changes. All copy
  matches: Pricing header and "What a run costs" box, Landing hero/FAQ/CTA, Onboarding, Signup, tour, Dashboard
  token card, Help guide (all read the numbers from the catalog API, not hard-coded).
- **Run budget + live meter (IDEA-01)**: every run has a budget (workspace default 500, settable 50–5,000 in Billing;
  lowerable per run from the meter's "stops at" menu), never above the balance not reserved by other running runs.
  The meter beside Send shows tokens so far against the budget (`b02-meter-3.png`: "10 / 300 tokens"); at the cap
  the run is interrupted cleanly with "Stopped at the N token budget", and it is **never charged more than its
  budget**, so the balance cannot go negative (PLT-16 fixed at the root).

## Status by finding

| ID | Status | What changed | Evidence |
|---|---|---|---|
| PLT-01 | Fixed | Cumulative-cost bug fixed; measured per-kind estimates learned per workspace; trial 1,000; all copy from the catalog | `test_session_charges_each_run_not_the_cumulative_cost`, `test_estimate_learns_from_the_workspace`; `b03-studio-done.png` (45 tokens), `a02-pricing.png` |
| PLT-02 | Fixed | Hero chat shows "Drafting the design", "Building and checking the part — all checks passed"; parameters "Horizontal leg 60 mm" etc. | `a01-landing.png` |
| PLT-03 | Fixed | "From idea to verified, editable CAD." in H1, footer and meta description; OG/Twitter tags + `public/og.png` | `a01-landing.png`, `web/public/og.png` |
| PLT-04 | Fixed | (a) tour rewritten; (b) Modules subtitle; (c) Pricing add-ons; (d) Landing modules section "One part, every next step"; (e) checklist "Open a module on your part"; (f) God panel "All modules", "Drawing Studio" | `a08-tour-3.png`, `a10-modules.png` |
| PLT-05 | Fixed | One written tagline per add-on (`ADDON_TAGLINES`, keeps "not a quote", "not a slicer"); stored rows still holding the old mid-word cut are upgraded on start | `test_catalog_upgrades_old_defaults_but_keeps_admin_edits`; `a02-pricing.png` |
| PLT-06 | Fixed | `Badge tone="solid"`; no other conflicting Badge/Button overrides found | `a02-pricing.png` |
| PLT-07 | Fixed | A running trial owns every live module; after expiry only Design Studio (parts, edits, exports stay); sidebar locks modules not owned | `test_trial_uses_every_live_module_until_it_ends`; `c18-phone-menu.png` (locks on Pro) |
| PLT-08 | Fixed | 24 h grace for unconfirmed email with a banner + inline resend; onboarding is one optional screen (role, units, workspace name, Skip); signup goes straight to it. Signup → Home in 3.0 s scripted | `test_unverified_grace_then_wall`; `a06-onboarding.png`, `a09-home.png` |
| PLT-09 | Fixed | "Next for <part>" card on Home: drawing, DFM, print prep, render, each deep-linked to the module on that part (lock if not owned), plus STEP; "Choose a plan" dropped from the checklist | `b04-home-next-steps.png` |
| PLT-10 | Fixed | `POST /api/billing/preview`: credit for unused time, account credit, leftover credit kept, seat overage warning, add-ons the new plan includes are cancelled, modules lost listed; checkout charges the prorated amount; Stripe path uses subscription item update (`_stripe_switch`, untested without keys) | `test_plan_switch_prorates_cancels_included_addons_and_warns_on_seats`; `c11-switch-pro-to-team.png` ($199 − $49 = $150) |
| PLT-11 | Fixed | Confirm dialogs for role change, owner transfer, remove, leave (naming the person and what they lose); extra seat add-on $39/seat/mo (Team plan, simulated) with add/remove | `test_extra_seat_addon_on_team_only`; `c15-leave-confirm.png` |
| PLT-12 | Fixed | Row menu: Open in new tab, Rename…, Duplicate (copies model, outputs, revisions; not the conversation), Find similar parts, Archive, Delete; sort by updated/name/size/created | `test_duplicate_project_copies_the_model_not_the_conversation`; `d03-projects-catalogue.png` |
| PLT-13 | Fixed | New project dialog has "Import a STEP file" and "From a drawing, sketch or photo"; the Home start box accepts both by drop or picker | code: `NewProjectDialog.tsx`, `StartBox.tsx` |
| PLT-14 | Fixed | Sidebar: Home, Projects, Modules (one row, expandable, locks), Account; duplicate Design Studio link removed; help moved to the header "?" (tour anchors there); sidebar folds to icons inside a project or module | `a09-home.png`, `a08-tour-5.png`, `b03-studio-done.png` |
| PLT-15 | Fixed | Notifications: agent run ready / checks failing / stopped at budget / stopped (runs ≥ 20 s), revision by someone else on your project (agent, params, hand edit, library), image read finished, final render or turntable finished. Email digest skipped (as instructed) | `test_revision_by_someone_else_notifies_the_creator`, `test_run_budget_caps_the_charge_and_never_overdraws`; `b05-notifications.png` |
| PLT-16 | Fixed | Budget ≤ unreserved balance, charge ≤ budget, in-flight reservations | `test_run_budget_caps_the_charge_and_never_overdraws` |
| PLT-17 | Fixed | Dead verify link → "This link has expired or was already used" + "Send a new link" (signed in, or by email via new `POST /api/auth/resend-verification-public`, never reveals accounts); reset page without/with a dead token → "Send a new link" | `c03-verify-dead-link.png`, `c04-reset-no-token.png` |
| PLT-18 | Fixed | One in-shell `NotFoundPanel` for unknown `/app/*` routes, unknown modules and missing projects | `d07-app-404.png` |
| PLT-19 | Fixed | Per-route titles (`useTitle`, project and module names via the shared query cache); OG/Twitter meta + image | code: `lib/title.ts`, `AppLayout.tsx` |
| PLT-20 | Fixed | Signed in: hero/CTA "Open the app", Pricing CTAs "Switch to Pro" → Billing, mobile menu mirrors desktop | `d01-landing-signed-in.png` |
| PLT-21 | Fixed | Both Enterprise CTAs go to `sales@`; footer "Careers" replaced by "Enterprise sales" | `a02-pricing.png` footer |
| PLT-22 | Fixed | Plan grid sized to the number of plans and centred | `a02-pricing.png` |
| PLT-23 | Fixed | One page width (`PAGE`, max-w-7xl) on Home, Projects, Modules, Billing, Team, Settings, Help, module sales pages; status/role badges capitalised; Provider column replaced by Receipt; "Live" eyebrow removed; "Live" pills on Pricing only shown for Preview | screenshots `a11`, `c13`, `d03` |
| PLT-24 | Fixed | New `thumb.png` per build: single isometric view, transparent background, no caption or triad (render.py, never allowed to fail the review sheet); cards fall back to the old crop for older builds | `d06-dark-projects.png`, `b04-home-next-steps.png` |
| PLT-25 | Fixed | Checklist auto-hides when complete, has Dismiss, invite item only when the plan has seats and the user is not "Just me", no plan item | `test_checklist_dismiss_and_size_search_in_inches` |
| PLT-26 | Fixed | Proper lucide icons; grouped results (Recent projects, Actions, Modules, Templates); a size-shaped query routes to the size search | `d04-palette-size.png`, `d05-size-results.png` |
| PLT-27 | Fixed | Help guides name the real tabs and icons; one guide per live module; shortcuts list = the real bindings; Studio tour: prompt+meter, viewer, checks, command bar, feature tree/history, Make (anchors `data-tour=viewer|feature-tree|make` added) | `d08-help.png` |
| PLT-28 | Fixed | Dialog tracks whether the user typed the name; template switch updates it otherwise; names made unique "(2)"; Home template cards now fill the start box instead of creating a project per click | code |
| PLT-29 | Partly | Envelopes and volumes in the user's units on cards and the catalogue; size search accepts `4.7 x 3.1 in`. The per-match reason line from the similarity engine still reads in mm | `test_checklist_dismiss_and_size_search_in_inches` |
| PLT-30 | Fixed | Funnel over a real cohort (90 days, no founders/admins/demo), each step as a share of the cohort; unit economics tiles (median tokens per first verified part and per change, runs above the shown range, budget stops, failures, AI cost); confirmations for Disable user and hiding a product (native confirm in the founder-only console) | `test_admin_funnel_cohort_and_unit_economics`; `d02-admin-overview.png` |
| PLT-31 | Fixed | Under 768 px the sidebar is a drawer behind a menu button; header and Home single-column; Studio/modules show a polite "built for a larger screen" note | `c17-phone-home.png`, `c18-phone-menu.png` |
| PLT-32 | Fixed | DFM sample uses "Centre pocket", "4× M6 clearance holes" (Ø6.6 now correctly "stock drill, no change"), "Top edge chamfer" | code: `ModuleSamples.tsx` |
| PLT-33 | Fixed | Declined payment has "Try again" (new checkout); printable receipt per paid payment (labelled "Simulated payment… not a tax invoice" when simulated), linked from Payments and the success page | `c09-declined-retry.png`; `test_plan_switch_…` asserts the receipt |
| PLT-34 | Partly | Clear-search button in the field and in the empty state, size-aware empty copy. The "within ±10 %" toggle was not added | `d03`/`d05` |
| IDEA-01 | Built | See headline | as above |
| IDEA-02 | Built | Home start box: describe a part (creates the project and sends the brief in one action; a Toolbox-shaped brief is prefilled instead, so the free component is offered first), or drop/pick STEP (import with recognition) or PDF/photo (Image & Drawing to CAD); templates are suggestion chips; `?template=` prefill from search | `b01-home-template-picked.png` → project opened in 1.3 s, verified geometry at 45 s |
| IDEA-04 | Partly | Projects list view is a catalogue: part, status, material, envelope, volume, builds, updated; search also matches material; "Duplicate" (use as starting point) and "Find similar" per row. No mass, hole-size or filter columns yet | `d03-projects-catalogue.png` |
| IDEA-03, IDEA-05 | Not done | Skipped as instructed | |

## Parked decisions (defaults used)

| # | Decision | Default used |
|---|---|---|
| PD-a | Trial size and copy (PLT-01) | 1,000 tokens / 14 days, "about 3 new parts" (worst measured cold cost 281 × 3 = 843) |
| PD-b | Default estimates | New part 40–400 (typical 250), change 20–280 (typical 60) until a workspace has 3 runs of a kind, then its own median and 10–90 % range |
| PD-c | Run budget | Workspace default 500 tokens, admins set 50–5,000; per-run override from the meter; the charge is capped at the budget (the platform absorbs any overshoot of the last model response) |
| PD-d | Plan allowances vs measured cost | Unchanged: Pro 1,500 tokens/mo is 6–35 new parts depending on warm/cold context. Founder to decide whether to re-price the token unit or the allowances |
| PD-e | Unverified accounts (PLT-08) | 24 h in the app with a banner; design runs and image reads allowed up to **300 tokens** (about one first part); buying, inviting and seat changes need a confirmed email; after 24 h the verification wall returns |
| PD-f | Trial module access (PLT-07) | Every live module during the trial; after it ends, Design Studio only (parts, edits and exports stay open), other modules locked |
| PD-g | Plan switch (PLT-10) | Credit for unused time prorated by time; the new plan starts a fresh period today and adds its full allowance; leftover credit kept as account credit; purchased add-ons the new plan includes are cancelled automatically; seat overage warns but does not block |
| PD-h | Extra seats (PLT-11) | $39/seat/mo, Team plan only, simulated (catalog code `seat_team`, kind `seat`) |
| PD-i | Notifications (PLT-15) | Bell only; run notifications only for runs ≥ 20 s or budget stops; email digest skipped |
| PD-j | God scenario `fresh_signup` | Now lands in the first-day grace (resets `created_at`); new scenario `verify_overdue` shows the verification wall |

## Files touched outside platform areas

- `src/aicad/agent/session.py` (per-run cost from the cumulative report, live meter events, budget interrupt; meter
  events are never persisted), new `src/aicad/agent/pricing.py`, `src/aicad/agent/render.py` (extra `thumb.png`).
- `src/aicad/meshstudio/jobs.py` (job-finished listener hook), `src/aicad/platform/routers/mod_mesh.py`,
  `mod_image2cad.py` (notifications; unverified cap on AI reads).
- `src/aicad/platform/routers/studio.py`: estimate endpoint delegates to `metering`; one `notify_revision` line after a
  hand-edit snapshot. `library.py`: one `notify_revision` line.
- Studio UI (kept minimal; another agent edits the Studio): `ProjectStudio.tsx` (2 `data-tour` attributes, the
  not-found panel), `studio/CommandManager.tsx` (`data-tour="make"`), `studio/Chat.tsx` (estimate line replaced by
  `RunMeter`, `meter` events, per-run budget in the request, clearer result line).

## Gate and walkthrough

- Tests: 13 new backend tests in `tests/test_platform.py` (metering, budgets, trial, grace, notifications, proration,
  seats, duplicate, catalog upgrade, checklist, inch search, admin cohort); 4 existing assertions updated for the
  new rules (grace, trial modules, 20-token minimum, God scenarios).
- Walkthrough (port 8781): public pages at 1440 and 390 px (no horizontal scroll), UI signup → one-screen
  onboarding → Home (3.0 s scripted) → tour (6 steps, Help anchored to "?") → start box first part (opened 1.3 s,
  verified 45 s, 45 tokens) → Home next steps → notifications → email confirmed via the dev mailbox → change run
  (26 tokens) → dead verify/reset links → trial → Pro (declined, Try again, paid) → Pro → Team preview ($150 due) →
  team confirmations → sidebar modules → phone drawer; admin overview, catalogue view, palette size search, dark
  projects, in-app 404, Help. Console: only the expected 400 from the deliberately dead verify link.
