# Formwright

**The AI design engineer for mechanical teams: from idea to verified, manufacturable CAD.**

This repository contains:
- the full **Formwright web application**: marketing site, signup and onboarding, guided tours, workspaces and teams, billing with tokens and add-ons, admin console and God mode;
- the live **Design Studio**: an AI agent (Claude Agent SDK) that writes parametric build123d CAD, builds it, runs deterministic geometry checks and shows the part live.

Modules that aren't built yet appear in the app as labelled **Preview** placeholders (`docs/DECISIONS.md` ADR-016).

## Run it (Windows, development)

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 20+, and Claude Code installed and logged in (the design agent uses that login in development).

```sh
uv python install 3.12
uv sync
cd web && npm install && npm run build && cd ..
uv run aicad app            # opens http://127.0.0.1:8765
```

On first start a **founder super-admin** account is created. The credentials are written to `data/ADMIN_CREDENTIALS.txt` (gitignored). Sign in with them, complete onboarding, and use the orange **God mode** button (bottom right) to:
- bypass paywalls, token limits, verification and onboarding;
- jump to any step of the customer journey, or put your workspace into a scenario (trial low on tokens, expired, Pro, Team, past due…);
- seed demo projects (real, verified builds) and demo teammates;
- view the app as any user (Admin → Users → View as).

Investor demo script: `docs/CUSTOMER_JOURNEY.md` §5.

### Frontend development with hot reload

```sh
uv run aicad app --no-browser     # API on :8765
cd web && npm run dev             # UI on :5173, proxies /api to :8765
```

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `FW_ENV` | `development` | `production` disables God mode and simulated payments, and requires `--api-key` |
| `FW_DATA_DIR` | `./data` | SQLite database, workspaces, admin credentials |
| `FW_DATABASE_URL` | SQLite in data dir | Any SQLAlchemy URL (Postgres planned) |
| `FW_APP_URL` | `http://127.0.0.1:8765` | Used in email links and Stripe redirects |
| `FW_SUPERADMIN_EMAILS` | `founder@formwright.dev` | Comma-separated; these accounts get the admin console and God mode |
| `FW_ADMIN_PASSWORD` | random | Password for the auto-created founder account |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | unset | Enables real Stripe Checkout (test or live). Unset means a labelled simulated checkout |
| `FW_SMTP_HOST`, `FW_SMTP_PORT`, `FW_SMTP_USER`, `FW_SMTP_PASSWORD`, `FW_SMTP_FROM` | unset | Sends real email. Unset means emails go to the local outbox (Admin → Email outbox, and a dev mailbox on the verify page) |
| `ANTHROPIC_API_KEY` | ignored in dev | Used only with `aicad app --api-key`; required before anyone but the founder uses the agent |

## Tests

```sh
uv run pytest -q          # backend + geometry + agent plumbing (no AI calls)
cd web && npx tsc --noEmit -p .
```

## Other commands

```sh
uv run aicad build specs/fx01_plate.json     # spec-file build + checks (no AI)
uv run aicad live  specs/fx01_plate.json     # live viewer, rebuild on save
uv run aicad studio --project NAME           # original single-user agent studio
```

## Important limits (read before showing anyone)

- **Agent auth:** the design agent uses the founder's Claude Code login. That is for the founder's own development only. Before any other person uses it, switch to an API key (`--api-key`) or an Anthropic-approved method (`docs/RISKS.md` R-LIC-05).
- **Not a sandbox:** agent-written model scripts run as Python on this machine, with a timeout and an import tripwire. A container sandbox is required before external users (SEC-004).
- **Payments:** simulated unless Stripe keys are set. Simulated revenue in the admin console is labelled.
- **Engineering:** checks prove geometric consistency with stated expectations only. Nothing is validated for strength or manufacture.

Planning docs: `docs/` (punch list, roadmap, architecture, decisions and parked decisions, risks, validation, customer journey, brand, session log).
