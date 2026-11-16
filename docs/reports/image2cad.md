# Image & Drawing to CAD (`image2cad`): module report

Branch `module/image2cad`. Status: **Live** (catalog `image2cad.status = "live"`).

Promise built into the product: **never guess scale, and show exactly what was read and what is missing before any
modelling.** Scale stays *Undefined* until the user confirms one real dimension; every value read is pinned on the
source; every gap is a blocking question; the design agent receives only the confirmed values.

## What was built

**Flow:** Upload → Read (deterministic first) → Review ("What we read / What we need") → Create model (project +
reference attached + one structured prompt to the design agent) → Studio.

### Backend `src/aicad/image2cad/`
| File | What it does |
|---|---|
| `tokens.py` | Deterministic dimension-callout parser: linear, Ø, R, SR, □, M threads (pitch, class, LH), ± / limit deviations, ISO fits (H7, H7/g6), counts (4X, 4 HOLES, (4X), 4 PLCS), THRU, DEEP / ↧ depth, TYP, EQ SP, PCD, REF, `(10)` reference dims, angles, chamfers (1 x 45°, C1), scale ratios, inch marks. Whole text must match, so sentences and notes never become dimensions. `label()` gives the canonical callout. |
| `sniff.py` | Upload validation: magic-byte sniffing (PDF / PNG / JPEG / WebP only; SVG, GIF, ZIP, EXE refused), size caps (PDF 20 MB, image 12 MB), Pillow decode with 40 MP cap, `verify()`, EXIF orientation, alpha flattened, 2000 px preview. |
| `vector.py` | Vector PDF read with **pdfminer.six (MIT)**: characters regrouped into runs by direction + baseline (rotated dimension texts read correctly, adjacent callouts stay apart); title block found from its field labels (TITLE, SCALE, UNITS, DRAWN, REV ...) and never read as dimensions; units/scale/projection from the title block or notes; views = clusters of the dominant outline line weight; view labels (SECTION A-A, ISOMETRIC VIEW, DETAIL B, FRONT VIEW ...) name regions; unlabelled orthographic views get their place in the layout and the "hub" view is the front suggestion; each dimension is tied to its nearest view with text direction (horizontal / vertical). **Cross-check:** each view's drawn size × stated scale is compared with its largest horizontal / vertical dimension (evidence only, plus a blocking question when a dimension is larger than its drawn view). |
| `extract.py` | Every untrusted file is parsed in a **child process with a 90 s limit**; PDF page 1 rasterised with **pypdfium2 / PDFium (Apache-2.0 / BSD-3)**; a PDF with no text layer is treated as a scan and goes to vision. |
| `vision.py` | Raster drawings, scans, sketches, photos: one read-only design-agent turn (Claude Agent SDK `query`, tools = `Read` only, existing path guard confined to the upload folder, `setting_sources=[]`) must return a fenced `fw-read` JSON block: dimensions with confidence, location, alternatives, unclear kind, what each measures; views; unreadable areas; missing sizes. Every text is re-parsed by `tokens.parse`. `run_agent` is the only model call; tests replace it. |
| `review.py` | The review: effective dims (edits, exclusions, kind answers, user-added), blocking **needs** (reference dimension always; front view when unlabelled; low-confidence vision reads < 0.75; Ø-or-R kind doubts; scale conflicts; unparsed numeric texts; unreadable areas; missing sizes with "I know it / Estimate (flagged) / Not needed"), readiness, scale state with evidence, assumptions, and the agent **hand-off prompt** (exactly the included values, grouped by view, with provenance: read from text / read by vision / corrected by me / added by me). |
| `store.py` | Per-org upload folders `<data>/image2cad/<org>/<id>/` (meta, source, preview, read.json, review.json). |

### API `src/aicad/platform/routers/mod_image2cad.py` (`/api/m/image2cad`)
`GET/POST /uploads`, `GET /uploads/{id}`, `POST /uploads/{id}/review`, `POST /uploads/{id}/reread`,
`POST /uploads/{id}/create`, `GET /uploads/{id}/preview.png`, `GET /uploads/{id}/source`, `DELETE /uploads/{id}`.
Org-scoped (other orgs get 404), 402 when the add-on isn't unlocked, viewers read-only (403 on changes), reading runs in
the background (status `reading → review | failed`), vision reads are metered like agent runs (token preflight,
`debit` of `tokens_for_cost`, God-mode bypass honoured). **Create** reuses the Studio's own paths: `create_project`
(or the `project` target), then `agent_chat` with the preview as a chat attachment (so it lands in `refs/` exactly like a
Chat attachment), the original file and `spec.json` (confirmed spec + prompt) under `<workspace>/image2cad/`.

### Frontend `web/src/pages/app/modules/image2cad/`
- `index.tsx`: uploads list (status: reading / N to answer / ready / model requested → Open in Studio), drop zone
  with limits, 5-step strip, `?project=<id>` prefill banner.
- `Review.tsx`: the signature screen. Left: `SourcePane.tsx` (preview with zoom / pan / fit, dashed view regions with
  names, numbered pins at the top-right of each text so the value stays visible; blue read, amber needs you, black-with
  -orange-ring reference, grey left out; hover syncs pins and rows). Right: **Scale card** (Undefined, striped, until a
  reference is confirmed; stated scale, units and geometry evidence), **What we need** (question cards with choice chips,
  suggested defaults never auto-applied, inline inputs for callouts / text / value + mm|in; "Estimate all missing sizes
  (flagged)" bulk action), **What we read** (grouped by view: pin no., callout, what it measures, TEXT or confidence %
  badge, correct / leave out; add a dimension you know), assumptions, notes, and the create bar (new or existing
  project; disabled with "N open items" until everything is answered).
- `types.ts`.

### Catalog
`image2cad` → `"live"`, summary and bullets rewritten to what ships (test asserts no validation claims).

## Punch-list rows
| ID | Status | Evidence |
|---|---|---|
| CAD-020 Vector-PDF drawing → spec | **Done** | `vector.py`; `test_vector_pdf_values_and_positions` (7 callouts at known positions incl. rotated text, values and positions within 1 mm), `test_vector_pdf_views_title_block_and_scale_check`, `test_round_trip_formwright_drawing` (Drawing Studio sheet of FX-DRW-1 reads back 100/60/20/80/40/4X Ø8 THRU/Ø6 DEEP 10/(10), 1:1, mm, SECTION A-A + ISOMETRIC views; legend/notes/title never read as dims). Walkthrough: demo Mounting Plate sheet → 16 dims, 4 views, scale 1:1 and mm from the title block, 3 geometry matches. |
| CAD-021 Raster drawing → spec (OCR/vision), ambiguity list on every run | **Done (vision, no paid OCR)** | `vision.py`; scanned PDFs (no text layer) routed to vision (`test_damaged_and_scanned_pdfs`); every run lists unreadable areas, unparsed texts, low-confidence reads and missing sizes as blocking questions (`test_vision_block_parsing_and_questions`, API test with mocked agent and metering). Live: one real vision read (below). |
| CAD-022 Image/photo/sketch → model with explicit missing-dimension questions; never invents scale; asks ≥1 reference dim | **Done** | Reference dimension is required on every upload (`need id=reference`, scale `undefined` until confirmed, units not preselected when not stated); the hand-off forbids measuring from the image; estimates only when the user chooses "Estimate (flagged)". Tests + live sketch walkthrough. |
| DS-005 note | — | The Chat attachment path now has a live run with an image (the create hand-off attaches the drawing raster). |

## Tests (`tests/test_image2cad.py`, 65 tests, ~15 s, no model calls)
- 40 parser hand cases (the brief's Ø12 H7, R5, 4X Ø6.6 THRU, M8x1.25, 25±0.1, 45°, 1:2 scale and more) + 13
  not-a-dimension cases + canonical label round trip.
- Vector PDF generated in the test with reportlab (FX-I2C-1, A4 at 1:2): values, positions, direction, view
  association, title block, scale cross-check (drawn 50 mm × 2 = 100), front-view question; the same sheet without a
  title block has no scale and stays undefined.
- Formwright Drawing Studio round trip (FX-DRW-1).
- Upload validation: sniffing, refusals (GIF, SVG, ZIP, EXE, empty), size caps, truncated PNG, downscale; damaged PDF;
  scanned PDF → vision.
- Vision parsing + question generation + answers → ready + prompt; hand-off prompt contains **exactly** the included
  values (excluded R5 absent, corrected value shown with its original, added value marked, 7 lines).
- API: 401, 402 (locked), 415/400 validation, upload → background read → review, 409 when not ready, 422 on an
  unparsable edit, create (agent `send` mocked: one prompt, project, `refs/ref_*.png`, `image2cad/spec.json`, source
  copy), viewer 403s, cross-org 404s; image upload → mocked vision → metered tokens (−5 for $0.05).
- Catalog live + no validation claims.

Full suite: see the final commit message / master's run (`uv run pytest -q`). Ruff, `tsc --noEmit`, `vite build` clean.

## Walkthrough (port 8777, scratch data dir, puppeteer-core 25.17.0, 0 console/page errors)
Live agent runs used: **2** (budget 2).
1. Seeded demo projects (God mode), Drawing Studio sheet of *Demo · Mounting Plate* (120 × 80 × 10, A3 1:1) →
   uploaded the PDF. Read in < 2 s: 16 dimensions (120, 10, 4, (6), 25, 60, 30, 80, 10, (25), 10, 100, (40), 40, 40,
   4X Ø6.6 THRU), views View 1 / View 2 (hub) / View 3 / ISOMETRIC VIEW, scale 1:1 and mm from the title block, geometry
   evidence "View 2: drawn width 120 mm at 1:1 = 120", "drawn height 10 = 10", "View 3: drawn height 80 = 80". Two
   questions: reference (suggested 120, matched) and front view (suggested View 2). Answered in the UI → ready.
2. **Live run 1** (Create model → new project → Studio): the agent built a verified model in 4 turns / 69.5 s:
   **bbox 120.00 × 80.00 × 10.00 mm = drawing overall size**, params PLATE 120×80×10, pocket 40×30×4 at 40/25,
   4 × Ø6.6 at 10 mm edges on 100 × 60 pitch, and it listed its assumptions (pocket corner R5 and 1 × 45° top chamfer,
   visible but undimensioned) and asked to confirm them.
3. **Live run 2** (vision): a photo-like hand sketch of an L-bracket (JPEG, rotated, uneven light, blurred note, no
   units, one view) uploaded through the file input. Read in 27 s: 60 (90 %), 120 (95 %), Ø8 (85 %), each with what it
   measures; "2 holes" flagged as not a callout; the blurred note flagged unreadable; missing sizes listed (leg
   thicknesses, width, hole positions, second hole size, radii, material...). Scale **Undefined**; Confirm reference
   disabled until a unit is chosen; after choosing 120 mm and "Estimate all missing sizes (flagged)", scale shows
   Confirmed and 2 questions remain. No model created (budget).
Screens reviewed and fixed from: pins covering texts (moved to the text corner), view label carried "SCALE 1:2", invalid
date in the list, answered pins, reference vs needs colours too close, units/tolerances duplicated as missing items,
long missing-size chips, reference wording.

## Known limits
- Vector: page 1 only (multi-page PDFs say "Page 1 of N read"); projection is read only from text ("FIRST ANGLE"), not
  from the ISO projection symbol; views are found from the dominant outline line weight, so PDFs drawn with one line
  weight, or exported as outlined text (no text layer), fall back to fewer views / vision; dimension-to-view association
  is nearest-region (no dimension-line tracing); GD&T frames, surface finish symbols, basic dims in boxes and
  dual-unit callouts are not parsed (shown as "What is …?" when they hold a number).
- Vision: quality depends on the model; positions are approximate (centre only); one image per read; a vision read is
  metered at the SDK cost estimate (248 tokens in the walkthrough, see PD below).
- The Studio's chat shows the hand-off prompt as the user's message (plain engineering text; it includes the existing
  attachment note line from the Chat path).
- Not done: DXF/DWG input, multi-sheet association, re-read of a single region, a "compare model to drawing" check after
  the build (the master could wire Drawing Studio round-trip as CHK later).

## Files outside the module
`src/aicad/platform/catalog.py` (image2cad entry only), `pyproject.toml` / `uv.lock` (`pdfminer.six` MIT,
`pypdfium2` Apache-2.0 / BSD-3 incl. PDFium BSD-3). No shared UI, Studio, agent or App files edited.

## Requests to the master
- Studio **Make** tab: map `image2cad` (opens `/app/modules/image2cad?project=<id>`; the review screen preselects that
  project as the target).
- `web/src/components/ModuleSamples.tsx` → `image2cad` sample shows "Overall length ≈ 120 mm, confidence low", which
  contradicts the shipped behaviour (we never estimate scale from an image). Suggest replacing it with a "What we read /
  What we need" illustration labelled SAMPLE.
- Drawing Studio could add "Re-read this sheet" as an honesty demo (round trip).

## Parked decisions (defaults used)
| # | Decision | Default used |
|---|---|---|
| PD-I2C-1 | Vision read cost: it runs the full design-agent preset (≈ the cost of a design run, 248 tokens in the walkthrough). Use a lean system prompt and/or a cheaper vision model? | Same configuration as the design agent (live-verified); metered like an agent run. Suggest a lean prompt + smaller model after an eval. |
| PD-I2C-2 | Low-confidence threshold for vision reads that must be confirmed | 0.75 |
| PD-I2C-3 | Upload limits | PDF 20 MB, image 12 MB, 40 MP, page 1 only, 90 s parse limit |
| PD-I2C-4 | Missing sizes: allow "Estimate (flagged)" | Allowed, only by explicit user choice per item or the bulk action; the agent must state each as assumed |
| PD-I2C-5 | Undimensioned small features in the hand-off (radii, chamfers) | Agent may give a sensible size and must list it as assumed; it must ask first if the size changes overall size or fit |
| PD-I2C-6 | Vision runs on the founder's Claude Code login in development | As PD-09: API key before any other user |
| PD-I2C-7 | Upload retention | Kept until the user deletes them; no automatic expiry |
