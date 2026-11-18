---
name: studio-e2e
description: Run the Formwright app on an isolated throwaway data dir and drive it in headless Chrome (puppeteer-core) to confirm a change works in the real UI, with screenshots and console/page errors. Use when asked to run, start or launch the app, take screenshots, do a browser walkthrough, or confirm a Design Studio / platform change end to end, beyond the tests.
---

# Run the app and walk it in a browser

Rule: **never test against the founder's `data/`**. Use a scratch data dir with its own God-mode superadmin.
The founder's own login (`data/ADMIN_CREDENTIALS.txt`) is only for reproducing something in their real projects, and
then read-only.

## 1. Build and start (scratch data dir)
Prerequisites (uv, `.venv`, `web/node_modules`) are covered by `dev-setup`. From the repo root in Git Bash:
```bash
unset VIRTUAL_ENV
(cd web && npx vite build)                       # app serves the SPA from web/dist
PORT=8766                                         # your own port (agents are each given one)
E2E="$SCRATCH/fw-e2e-$PORT"                       # ONE FOLDER PER PORT: sessions and agents share the scratch dir
rm -rf "$E2E"; mkdir -p "$E2E"                    # only ever delete your own folder
export FW_DATA_DIR="$(cygpath -w "$E2E")\\data"   # Windows path; native Python misreads /c/Users/...
export FW_SUPERADMIN_EMAILS="e2e@formwright.test" FW_ADMIN_PASSWORD="E2e-walkthrough-2026"
uv run aicad app --no-browser --port $PORT       # run_in_background; wait until GET /api/health answers 200
```
On first start, `ensure_founder()` creates that superadmin (verified, God mode on), so no signup or mailbox step is
needed. Never use port 8765: that is the founder's own app on their real data.
Stop only your own server: find it by command line (`--port $PORT`) and stop that process tree, never by image name.

## 2. Walk it
```bash
cd "$E2E" && npm init -y >/dev/null && npm i puppeteer-core     # record the installed version in SESSION_LOG
cp "<repo>/.claude/skills/studio-e2e/walkthrough.mjs" .
FW_URL=http://127.0.0.1:8766 FW_EMAIL=e2e@formwright.test FW_PASSWORD=E2e-walkthrough-2026 OUT="$E2E/shots" node walkthrough.mjs
```
The template logs in through the API, completes onboarding, dismisses tours, seeds the demo projects (God mode),
opens the first demo in the Studio and screenshots it. Extend `steps()` for the change under test, then **Read the
PNGs**: a run with no errors does not prove the screen is right.

Chrome: `C:/Program Files/Google/Chrome/Application/chrome.exe` (Edge also works: `C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`).

Faster path for new flows: `lib.mjs` (in this folder) exports `start()`, which returns `{ page, api, clickAt, clickText,
shot, sleep, finish }` already logged in. `example-revolve.mjs` shows a full Studio flow, including calibrating sketch
mm↔px from the sketcher's cursor readout and waiting for builds. Copy both next to your script.

## Gotchas
- **Never wait for `networkidle0` on a project page.** The Studio keeps an agent event stream open, so it never goes
  idle. Use `waitUntil: "domcontentloaded"` plus `waitForSelector("[data-tour=command-manager]")`, and wait for
  concrete UI (sketcher closed: `waitForSelector("svg.touch-none", { hidden: true })`; panel gone: "Add feature"
  hidden).
- Text selectors can hit the wrong element: the tree lists "Front/Top/Right Plane" and the viewer has "Front/Top"
  view buttons. Prefer stable attributes (`button[data-plane=Top]`, `aria-label`).
- Fetching `files/status.json` before the first build returns 404, which shows up as a console error.
- Every non-GET API call needs header `X-FW-CSRF: 1`, or the response is 403 "Missing CSRF header" (`api()` in the
  template adds it).
- Radix menus and tabs ignore synthetic `el.click()`. Use real pointer events: `clickAt(selector)` moves the mouse to
  the element's centre and clicks.
- Tours (driver.js) overlay the UI. The template sets `localStorage fw_tour_app/fw_tour_studio = "1"` and calls
  `/api/tour/complete`.
- Studio panel state persists in `localStorage` (`fw_studio_left`, `fw_studio_chat`).
- The viewer renders WebGL. Headless Chrome needs `--use-angle=swiftshader` or `--enable-unsafe-swiftshader`
  (set in the template), otherwise the canvas stays blank.
- The Studio chat sends with **Ctrl+Enter** (Enter is a newline). Agent turns without tokens: start the server with
  `FW_AGENT_REPLAY=<cassette.json>` (turns matched by regex on the prompt; a build turn carries `files` + `rebuild`).
  Example cassette and flow: `docs/reports/studio-intel/README.md`.
- Live design-agent runs spend the founder's Claude subscription (PD-09). Do them only when the change is agent-side,
  and say in the session log that one was run.

## 3. Report
In `docs/SESSION_LOG.md` "Evidence", record: the flow walked, the observed numbers (bbox, volume, check results),
zero or listed console errors, the screenshots reviewed, and the fixes made from them. Stop the server afterwards and
delete the scratch dir when done.
