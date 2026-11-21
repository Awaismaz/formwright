# Design Office Board, slice 1: parts come alive on their cards

Branch `wip/board-previews` (from main e25ff92). Status: built and verified on an isolated app; not merged.

## What was built

Every part ticket on the Board now carries a small line drawing of its real geometry: the placeholder from the
interfaces while it waits and while the agent works, the approved part once Fitz swaps it in. The drawing is always
the exact geometry of a part snapshot at that moment (OCCT hidden-line projection), never a mock-up: until the server
has drawn it, the card shows a neutral box outline.

### Server: blueprint line-art thumbnails

- `GET /api/office/programs/{pid}/items/{item}/thumb?state=ghost|real[&k=<snapshot key>]` returns a small SVG
  (about 3 to 15 KB). Scoped like every office endpoint: the program is loaded for the caller's organisation (another
  org gets 404), and the part snapshot comes from that org's part cache.
  - `ghost`: the item's placeholder snapshot (the current key, or the one a real part replaced, now kept in
    `assembly.parts[item].ghost`, or the one the current ICD makes if it is still in the cache).
  - `real`: the approved part's snapshot (only when `assembly.parts[item].kind == "real"`).
  - `k`: the key the card expects. With it the answer is `Cache-Control: private, max-age=86400, immutable`; a stale
    key gets 404 (the card asks again with the new key from the next program update).
  - Not drawn yet: **202** at once (`Retry-After: 1`) and the drawing starts in the background; the program API never
    waits. A drawing that failed answers 404 for five minutes (the card keeps its neutral outline).
- Drawn in the organisation's warm **drawing worker** (new op `thumb`, `src/aicad/drawing/thumb.py`); the web process
  never loads the kernel. Cached next to the snapshot as `_parts/<key>/thumb_v<THUMB VERSION>_<view hash>.svg`, written
  atomically. Snapshots are immutable, so each is drawn once per view.
- View: iso, except a disc (gear blank, flange) which is seen 35 degrees off its axis. Both drawings are framed by the
  item's envelope from the skeleton and seen in the ICD part frame (a real part modelled in another frame is turned
  through the frame Gage found), so the placeholder and the real part line up for the cross-fade.
- Visible edges solid, hidden edges dashed and faint, `stroke="currentColor"` so it themes with Paper and Blueprint.
- Feature groups (`<g data-feature=... data-g=... data-d=...>`): `bore` (recognised holes and partial bores, any other
  concave full cylinder), `teeth` (faces between the root and tip circles of a recognised gear), `keyway` (flat faces
  along the axis of a round part, inside its outer diameter), `groove` (a short turned diameter below its
  neighbours), `chamfer` (small cones, small oblique flats), `profile` (turned diameters, tapers), `envelope` (the
  rest). Grouping matches each projected edge back to the 3D edges it was projected from (an edge takes the most
  specific group of its two faces); a silhouette of a curved face takes the group its two ends share. Nothing is ever
  added or moved: an edge that can't be placed stays with the envelope. Timing: plate 0.07 s, stepped shaft 0.11 s,
  24-tooth gear 1.4 s (warm worker); the first drawing of an app run waits about 8 s for the worker to start.

### Board cards

- A 48 px square under the meta row, beside the title; tidy at phone width (see `5-phone.png`).
- Waiting: the placeholder, faint. Working: the placeholder with the stage reveal, from the agent's own status line
  (`workStage` / `stageView` in `model.ts`, the part title removed first so "Turning bracket" never reads as turning):
  - reading the brief: envelope;
  - turning, roughing out, hobbing, cutting the blank: plus the turned profile and teeth;
  - facing and grooving, pocketing, cutting the hub, any re-work: plus bores, grooves, keyways;
  - checks pass (chamfering, deburring): plus chamfers;
  - miking / measuring against the brief, and Gage inspecting: everything, with a short scan line;
  - built from the interface spec (no AI): everything at once.
- Approved and swapped in: the real part. If the card saw the swap happen, a 0.6 s cross-fade from placeholder to real
  plays once (remembered per part in `sessionStorage`); a page that opens on a finished program never replays it.
  While the real drawing is still being drawn, the card keeps the placeholder rather than an empty box.
- Review overlay: while Gage's conformance rows exist, the matching feature groups turn green or red (`reviewMarks`:
  by feature kind, and for round features by diameter, the ICD's or the measured one; a turned part's envelope row
  lands on its largest diameter). A failing feature also gets a red dot, and a sent-back, blocked or being-reworked card
  shows a red reason chip ("Off: envelope", "Off: bore Ø20 H7", or the office's blocked reason).
- `prefers-reduced-motion`: no transitions, no fade, a still scan line. No sound.

### Drawer

`TicketDrawer` shows the larger drawings (150 px): the placeholder and the approved part side by side when both exist,
with Gage's marks.

### Performance

No WebGL on cards. Thumbnails load only when the card is near the viewport (IntersectionObserver), each URL (snapshot
key) is fetched once per session and shared by every card and the drawer, at most three requests at a time, and a
202 is polled with a backoff (0.5 s growing to 4 s, giving up after 2 min). Each drawing renders as at most two paths
per feature group.

## Verification

- `tests/test_office_thumbs.py` (4 tests): grouping on a real plate (three bores by diameter, chamfer, envelope,
  hidden lines, nothing unplaced), deterministic output, the frame turn, the view choice, the kept placeholder key,
  and the endpoint (202 then SVG, cached file next to the snapshot, identical second answer, immutable with `k`,
  stale key 404, real 404 while a placeholder, bad state 422, unknown item 404, a real snapshot swapped in draws the
  real part and leaves the ghost as it was, another organisation 404).
- `tests/test_office_icd.py -k "swap or placeholders or change_request_accepted"`: 3 passed (the program assembly
  changes). `tests/test_no_long_dashes.py` passed. `ruff check src tests` clean.
- Web: `tsc --noEmit` clean; `vitest run` 29 files, 195 tests (new `thumbs.test.ts`: stage mapping, title never read as a
  stage, the reveal order, row kinds, diameters, marks, envelope on a turned part, reason chip, SVG parsing that keeps
  only our groups and plain path data); `vite build` ok.
- studio-e2e: isolated app on port 8791, throwaway data dir, simulated agents (`FW_OFFICE_FAKE_AGENTS=1`,
  `FW_OFFICE_FAKE_DELAY=2`, `FW_OFFICE_DIRECT=0`, the stepped shaft built 0.4 mm oversize on its first turn so Gage
  sends it back), puppeteer-core 25.18.1. Program: "Build a Spur Gear mounted on stepped Shaft and locked with a key"
  (standard planner): stepped shaft (Chuck), spur gear and parallel key (Hex, Toolbox). Stages seen on the cards:
  waiting, reading, rough, finish, features, inspect, fit, done (real). Console: one 404, from the existing ticket 3D
  preview (`/api/projects/<id>/files/topo.json` of a simulated part, not this change); no other errors.

Screenshots (`docs/reports/board-previews/`):

| | |
|---|---|
| `1-before-run.png` | the board after the ICD gate: placeholders, faint |
| `2-mid-run-stage.png` | Chuck turning the shaft (profile lit); the gear from the Toolbox waiting for Fitz |
| `2-mid-run-gage-scan.png` | Gage inspecting the shaft (scan line) after a send-back (red ICD chip) |
| `2-mid-run-sent-back.png` | the shaft sent back: outer diameter red, keyway and journal green, "Off: envelope" chip |
| `3-complete.png` | every part integrated: real parts, the shaft's conforming features green |
| `4-drawer.png` | the shaft's drawer: placeholder and approved part side by side |
| `5-phone.png` | 390 px wide: the Integrated column with its thumbnails |

## Not done, and what slice 2 needs

- **Live assembly viewport above the board** (PD-302): the program assembly (`GET /programs/{pid}/assembly` already
  returns instances, placements and part topology) in one WebGL view over the board, each instance coloured by its
  ticket's state (waiting, working, in review, sent back, approved), with two-way hover linking: hover a card and its
  part lights in the viewport; hover a part and its card scrolls into view and highlights. Needs an instance -> ticket
  map (the `items` map of that endpoint has it), a shared hover store, and the reveal and review colours of this slice
  reused per instance.
- **Replay of a program from its events**: the activity log (`/programs/{pid}/activity`) plus the immutable snapshot
  keys per swap give everything needed to scrub a finished program (cards moving, thumbnails revealing, the assembly
  filling in). Needs the snapshot key recorded on `ticket.fitted` / `assembly.updated` events (today only the current
  key and the replaced placeholder are kept), and a timeline scrubber.
- Eager drawing (when a placeholder or real part is created) was left out on purpose (PD-303).
- Matching rows to features by position (the ICD gives hole centres) would tell holes of one size apart; today every
  hole of that diameter takes the combined result (PD-306).
- Standard parts without a skeleton item (keys, bolts) have no thumbnail (PD-308).

## Parked decisions (defaults used; not yet in `docs/DECISIONS.md`)

| PD | Decision | Default used |
|---|---|---|
| PD-300 | Card previews style | Blueprint line art (exact hidden-line projection), not shaded renders |
| PD-301 | Sound on the board | None |
| PD-302 | Next board slice | The live assembly viewport above the board (two-way hover), then program replay |
| PD-303 | When thumbnails are drawn | Lazily on the first card request, in the org's drawing worker (shared with drawings); no eager drawing at placeholder or swap time, so no CAD process starts for programs nobody is watching |
| PD-304 | Thumbnail view | Iso; a disc 35 degrees off its axis; framed by the item's skeleton envelope, real parts turned through Gage's frame so ghost and real line up |
| PD-305 | Ghost-to-real cross-fade | 0.6 s, only when the card saw the swap live, once per part per browser session |
| PD-306 | Matching Gage's rows to drawn features | By feature kind and diameter (ICD or measured); envelope rows on a turned part mark its largest diameter; a row that matches nothing marks nothing |
| PD-307 | Reason chip | Shown on sent-back and blocked cards, and while a part with a failing ICD measurement is reworked, until Gage measures it again |
| PD-308 | Which tickets get a thumbnail | Items with a placeholder in the program assembly (designed parts and Toolbox parts that are skeleton items, e.g. a gear); keys and bolts outside the skeleton get none |
| PD-309 | Large drawings | Hidden lines are left out when the SVG would pass 90 KB (visible lines never); while a real drawing loads the card keeps the placeholder |
