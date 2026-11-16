# Customer Journey — Formwright

Written for the founder, the product team and anyone demoing the product. Status labels: **Live** (implemented in the app), **Preview** (UI shown, function not built), **Planned**.

## 1. Personas (hypotheses — validate in pilots, COM-001)

| Persona | Context | Job to be done | What wins them |
|---|---|---|---|
| **Dana, consultancy principal** (2–20 engineers) | Bills by the hour; many small custom parts per client | Turn client briefs into first models and drawings faster, without losing rigour | Verified output, STEP into SOLIDWORKS, team seats, predictable cost |
| **Marco, machine/prototype shop owner** | Receives sketches, photos, legacy prints | Re-model customer parts quickly, quote faster, flag DFM issues | Image/drawing → CAD (Preview), DFM advisor (Preview), cheap per-part cost |
| **Priya, independent PE** | Solo, wears every hat | Go from idea to a manufacturable, documented part alone | Low entry price, drawings, honest engineering checklists |

## 2. Journey map

| # | Stage | Screen / touchpoint | Goal of the step | Status | Success event (analytics) |
|---|---|---|---|---|---|
| 1 | Discover | Landing page `/` — hero, real product illustration, how-it-works, module roadmap with Live/Preview badges, security, FAQ | Understand value in 10 s; trust the honesty | Live | — |
| 2 | Evaluate | Pricing `/pricing` — plans, comparison table, add-ons, token packs | See a path that fits budget | Live | — |
| 3 | Sign up | `/signup` (plan intent remembered from pricing) — name, email, password strength, terms | Account in < 30 s, no card | Live | `signup` |
| 4 | Verify | `/verify-email` — resend, dev mailbox when no SMTP | Prove email; prevents abuse | Live | `email_verified` |
| 5 | Onboard | `/onboarding` 5-step wizard: role, team size, CAD tools, goals + units, workspace name | Personalise; create workspace; start 14-day trial with 300 tokens | Live | `onboarding_completed` |
| 6 | Orient | Dashboard + **guided product tour** (7 steps) + getting-started checklist (8 items) + goal-based module suggestions + plan-intent banner | Know where everything is; next action obvious | Live | `tour_completed` |
| 7 | First value ("aha") | Template quick-start → Design Studio with starter prompt prefilled → **studio tour** (4 steps) → agent run → live model + checks | First verified part in minutes | Live (AI run uses the founder's dev login) | `project_created`, `prompt_sent`, `first_build` |
| 8 | Iterate | Conversational revisions; **Params tab: edit a dimension and rebuild with no AI and no tokens**; **Revisions: restore any build**; STEP/STL download | Feel in control; trust repeatability | Live | `download` |
| 9 | Explore | Modules page + preview pages with labelled SAMPLE output, early-access waitlist, add-on unlock | Understand roadmap; signal demand | Live (modules themselves Preview) | `module_viewed`, `feedback_waitlist` |
| 10 | Convert | Paywall moments (below) → Billing → checkout (Stripe or simulated) → success page → updated sidebar/modules/tokens | Pay without friction | Live | `paywall_shown`, `checkout_started`, `purchase` |
| 11 | Expand | Team invites with roles and seat limits; add-on modules; token top-ups | Bring colleagues; grow spend | Live | `teammate_invited`, `invite_accepted` |
| 12 | Retain | Notifications (low tokens, payments, joins), usage chart, ledger, feedback/ratings, help center | Stay informed; feel heard | Live | `feedback_*` |

## 3. Paywall and upgrade moments (designed, not accidental)

| Trigger | Where it appears | Message pattern | CTA |
|---|---|---|---|
| Trial tokens < 50 | Top banner, sidebar trial card, token pill turns amber, notification | "Only N trial tokens left." | Choose a plan |
| Balance below run preflight (10) | Studio composer replaced by a lock card; 402 toast | "You need at least 10 tokens to run the agent." | Upgrade or top up |
| Trial expired | Banner + studio lock | "Your free trial has ended." | Choose a plan |
| Seat limit | Invite dialog + 402 toast | "All seats are in use…" | Upgrade to Team |
| Locked module | Sidebar lock icon → module page | Availability card: add-on price + plans that include it | Unlock add-on / Compare plans |
| Payment failed | Red banner | "Your last payment failed." | Fix billing |

Principles: never block reading or exporting work already made; parameter edits and revision restores are always free; costs are shown before and after every run.

## 4. Guided tours

- **Product tour** (auto-starts on first dashboard visit after onboarding; restart from Help, the account menu, the checklist or `?tour=1`): welcome → Projects → templates → Modules → Tokens → checklist → Help.
- **Studio tour** (auto on first project open; `?` in the studio toolbar): prompt → live viewer → checks → revisions & files.
- Implemented with driver.js, themed to the design system. Missing anchors are skipped automatically.

## 5. God mode (founder/demo only)

Floating **God mode** button for super-admins; the whole API is disabled in production (`FW_ENV=production`).

- **Bypasses:** paywalls (all modules unlocked, trial expiry ignored), token limits (agent runs free), email verification, onboarding.
- **Jump to any journey step:** landing, pricing, signup, verify, onboarding, dashboard + tour, new project, module roadmap, Drawing Studio preview, billing, team, admin.
- **Account scenarios:** fresh signup · needs onboarding · first tour · trial active · trial low tokens · trial expired · Pro · Team · past due · all modules · no modules.
- **Demo data:** seed 4 demo projects (real builds of original parts, all checks pass) + 3 demo teammates; reset removes them.
- **Impersonation:** Admin → Users → "View as" with a persistent banner and one-click stop; logged in the audit trail.

### Suggested 7-minute investor demo

1. Landing → pricing (1 min). 2. Sign up as a new user, verify via dev mailbox, onboarding (1.5 min). 3. Product tour, then L-bracket template → send prompt → watch agent build and verify (2 min; or open a seeded demo project if offline). 4. Params: change a dimension, rebuild instantly, restore a revision (1 min). 5. Drawing Studio preview + early access (30 s). 6. God mode → "trial low tokens" → show paywall → simulated checkout → success (1 min). 7. Admin overview: funnel, MRR (simulated), audit log (30 s).

**Honesty rule for demos:** Preview modules are labelled *Preview* and their outputs *SAMPLE*. Simulated payments are labelled. Do not present either as working production capability.

## 6. Funnel instrumentation

`signup → email_verified → onboarding_completed → project_created → first_build → checkout_started → purchase`, plus `tour_*`, `template_used`, `prompt_sent`, `agent_run`, `paywall_shown`, `upgrade_clicked`, `module_viewed`, `download`, `teammate_invited`, `feedback_*`. Visible in Admin → Overview (funnel, signups, plan mix, MRR, tokens used).
