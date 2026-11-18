# AI Render Studio (module `airender`, MSH-013): report

Branch `wip/ai-render`. AI Render Studio makes **marketing visuals** of a verified part with OpenAI image generation,
on the workspace's **own OpenAI API key** (bring your own key). It is **Live, marked Beta and "Uses your OpenAI key"**.
Every image is captioned *"AI-generated visual — not dimensionally exact; use Mesh Studio renders or drawings for
exact geometry"* (UI, gallery, lightbox and the PNG's `Description` text chunk).

## Flow

1. **Setup (once per workspace).** An owner/admin pastes an OpenAI key (Settings → API & integrations → OpenAI, or the
   module's own setup screen). The server checks it with a free `models.list` call, encrypts it and keeps only a masked
   hint (`sk-…AbCd`). Someone with the engineer role then agrees, once for the workspace, that the reference image and
   the prompt are sent to OpenAI (consent is stored with who and when, and can be withdrawn).
2. **Pick a verified part** (same picker cards as the other modules; `?project=<id>` opens one directly). Entry points:
   the Studio's **Make → AI render**, Mesh Studio's header **AI render**, Modules page and sidebar.
3. **Refine.** The geometry reference is chosen automatically: the newest Mesh Studio render (final, then preview);
   when the part has none, a quick Mesh Studio preview of the exact model is queued automatically; the build's
   thumbnail (`out/thumb.png`, then `out/views.png`) is the fallback. Settings: scene (studio packshot, workshop
   bench, industrial installation, outdoor, exploded catalogue, in-hand scale), material & finish (pre-filled from
   MATERIAL via Mesh Studio's mapping, e.g. "Machined steel (Carbon steel)"), lighting, camera (default **Match
   reference**; other viewpoints show a warning that the AI must imagine unseen sides), background, style, size,
   quality, variants (1–4), plus a free-text direction.
4. **Review.** The prompt and the "Avoid" list are shown, fully editable. A badge says whether it was polished by AI
   or is the standard template, and a lock line shows whether the geometry clause is still in the text.
5. **Generate** runs in a background job: progress with elapsed time and a typical duration, then the **gallery**
   (thumbnails, lightbox with the exact reference and prompt that were sent, PNG download, **Variation** of an image,
   **Again**, **Use prompt**, delete). OpenAI's reported image tokens are shown per request.

## Backend (`src/aicad/airender/`)

| File | What it does |
|---|---|
| `keystore.py` | Fernet (AES-128-CBC + HMAC) with a key derived (SHA-256) from `FW_SECRET_KEY`; in development a random secret is generated once in `<data_dir>/secret.key`. **Production refuses to store keys without `FW_SECRET_KEY`.** `mask()`, `scrub()` (removes `sk-…` from any message) |
| `integration.py` | Key + consent in `OrgPrefs.data["ai_render"]` (no schema change). `public_state()` never contains the key or the ciphertext |
| `options.py` | The settings catalogue (label + prompt fragment per choice), validation, finish from material. Default model `gpt-image-2` (`FW_AI_RENDER_MODEL` overrides) |
| `refine.py` | **Prompt refinement layer.** `part_facts()` (name, material, bbox size, named features from `status.json`); `compose()` = deterministic template; `polish()` = one Claude turn through the Agent SDK with **no tools, max_turns=1**, parsed from a fenced block, falling back to the template on any failure or timeout (60 s); `guarded()` re-inserts the geometry clause and appends the "Avoid:" section before anything is sent, whatever the user edited |
| `provider.py` | Official `openai` SDK: `images.edit(model, image=[reference(, earlier output for a variation)], prompt, size, quality, background, n, output_format=png, safety_identifier)`; `input_fidelity="high"` only for models that accept it (gpt-image-1.5; gpt-image-2 rejects/ignores it). Error mapping: 401 bad key, 403 organisation not verified for GPT Image, 429 quota vs rate limit, 400 safety/moderation, 404 model, timeout, network, 5xx. `FakeOpenAI` behind `FW_AI_RENDER_FAKE=1` (development only, never in production) draws a toned copy of the reference stamped SIMULATED |
| `service.py` | Reference candidates, background jobs (thread pool of 2, max 3 in progress per workspace), `<ws>/airender/<job>/` with `job.json`, `ref.png` (the exact image sent), `out_<n>.png` (+ caption text chunk), `thumb_<n>.jpg`; ids are generated hex, file names on a fixed pattern; restart-interrupted jobs show as failed; newest 60 kept. **The key is passed to the worker in memory and never written to disk** |
| `routers/mod_airender.py` | `/api/m/airender`: `GET /integration`, `POST|DELETE /integration/key` (admin), `POST /integration/consent`, `GET /options`, `GET /projects/{id}`, `GET /projects/{id}/references/{rid}`, `POST /projects/{id}/references/studio` (+ status), `POST /projects/{id}/refine`, `POST /projects/{id}/generate` (428 without consent, 409 without key), jobs list/get/delete/files. Org-scoped (404 across workspaces), engineer role to generate |

Access: BYO-key modules (`byo_key` in the catalog) are included wherever the Design Studio is (running trial and every
plan), because OpenAI bills the customer (PD-40). The AI polish costs Formwright compute, so it is metered like other
agent use (measured cost → tokens, minimum 1; free in God mode and with the dev fake); the template is free.

## Shared files touched (minimal)

`platform/catalog.py` (the `airender` entry), `platform/services.py` (BYO modules follow the Design Studio in paid
plans, 2 lines), `tests/test_platform.py` (module count = `len(MODULES)`), `web/src/lib/types.ts` (`beta`, `tags`),
`components/icons.tsx` (`sparkles`), `pages/app/Modules.tsx` (Beta badge + tag), `layouts/AppLayout.tsx` (Beta tag in
the sidebar), `pages/app/ProjectStudio.tsx` (Make → AI render), `pages/app/Settings.tsx` (OpenAI card under API &
integrations), `modules/mesh/index.tsx` (AI render button). New dependencies: `openai`, `cryptography` (already a
transitive dependency).

## Tests (no live OpenAI or Claude calls)

`tests/test_airender.py`, 11 tests: key encryption round-trip, masking, a changed secret can't decrypt, production
refuses a generated secret; template refiner deterministic with the clause in every scene × style; text allowed when
asked; `guarded()` restores a deleted clause; agent path parses mocked output, junk and failures fall back; error
mapping 401/403/404/429 quota/429 rate/400 safety/5xx/timeout/network with the key scrubbed; edit parameters
(`input_fidelity` only for 1.5); the **real SDK** builds the multipart request through an httpx mock transport; API
flow: 401 signed out, consent 428, no key 409, bad key 400, key stored only as ciphertext (not in responses, DB
plain text, audit log, job.json or logs), generate → done with 2 images + usage, PNG caption, download, variation sends
two images, quota/bad key/safety jobs fail with plain messages, other workspace 404, delete key; polish metered.
Vitest `prompt.test.ts` (4): negatives editing, clause detection, stale-prompt key, labels.

## Walkthrough (port 8797, throwaway data dir, `FW_AI_RENDER_FAKE=1`)

Headless Chrome (puppeteer-core 25.18.1) on the God-mode demo seed: Modules page (card with Live + Beta, "Uses your
OpenAI key"; sidebar Beta tag) → no-key setup screen → rejected key (simulated 401, message shown) → valid key saved
(masked `sk-…WXYZ`; the key text never appears in the page) → consent → picker → Pipe Flange: an automatic Mesh Studio
preview became the reference → workshop / golden hour / user direction → Refine (polished, editable, geometry lock
shown) → Generate 2 → gallery + lightbox + caption → camera warning → Settings OpenAI card → Mesh Studio "AI render"
entry. **0 console or page errors** (apart from the deliberate 400 of the rejected key). Screenshots reviewed; fixed from
them: awkward template sentence, workshop scene with a white-seamless background (scene now switches the background),
lower-case gallery labels, reference pill wrapping, variants click off-screen in the script.

## How the founder enables it

1. Create an OpenAI API key at platform.openai.com → API keys (a project key is fine). GPT Image models may require
   **organisation verification** (platform.openai.com → Settings → Organization → General); without it the studio
   shows "This OpenAI key isn't allowed to use the image model…".
2. Optional: set `FW_SECRET_KEY` (any long random string) in the server environment; without it, development
   generates `data/secret.key`. Keep the same secret, or stored keys must be re-entered.
3. Optional: `FW_AI_RENDER_MODEL` to try another model (e.g. a gpt-image-2.5 variant).
4. In the app: AI Render Studio (sidebar) or Settings → API & integrations → OpenAI → paste the key → **Check and save
   key** → tick the consent → **Allow AI renders**. Do **not** set `FW_AI_RENDER_FAKE` on the real server.

## Limitations

- Never called the real OpenAI API (all tests and the walkthrough are mocked/faked); first real use should check the
  model id, transparent background on gpt-image-2 (preview feature) and timings (ETA figures are estimates).
- No USD cost: OpenAI returns token usage, which is shown; prices are not hard-coded.
- AI images can still change geometry despite the clause; that is why every image is captioned and the camera
  warning exists. No automatic geometry comparison against the reference yet.
- Jobs run in-process (thread pool), like Mesh Studio's queue; a restart marks running jobs as interrupted.
