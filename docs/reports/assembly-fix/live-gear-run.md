# Live run 2026-11-19: the founder's 1:3 spur gear pair through the Design Office (branch `wip/live-gear`)

Real in-app agents (dev Claude Code login), isolated app on :8797, UI driven with puppeteer, every gate clicked as an
engineer would. Brief, verbatim: *"Simple spur gear pair, ratio 1:3, with only shafts and bearings. Pinion module 2,
20 teeth; gear 60 teeth. Shafts Ø20 at the bearings; four 6204 bearings, two per shaft. No housing."*

## Verdict
**The mechanism itself now assembles correctly.** Two parallel shafts 80 mm apart, pinion and gear coplanar and
meshing (0 mm³ gear clash in the final), two 6204s on each shaft, one either side of its gear, nothing floating.
The "parts lying on the floor" symptom is gone for the parts that matter.

**But an engineer would not accept it:** four junk parts stand on the floor beside it (two spur gears m2 z24 posing as
"keys", two Ø22×120 shafts posing as "circlips"), they are in the BOM as bought parts, the keys are not fitted, and the
run stopped once on a false alarm until I fixed it. Tokens: **689 platform tokens (≈ $6.9)**, far over the 400 stop:
528 of them went in the first 85 s after Run, before anything could be checked.

Screenshots (read and judged): `live-gear/1-layout-gate.png` (layout at the ICD gate: correct),
`2-pinion-sub.png` (sub-assembly: correct + gear/shaft junk), `3-archie-blocked.png` (the false stop),
`4-final-4views.png`, `5-final-iso.png`, `6-final-top.png`, `7-final-front.png` (final: mesh correct, 2 advisory
clash rings at the gear-shaft bearings), `8-final-page.png` (Assembly tab).

## Timeline (UTC, wall clock)
| Phase | Start → end | Time | Tokens | Notes |
|---|---|---|---|---|
| Create + Archie plans | 15:19:39 → 15:20:22 | 43 s | 67 | 2 subs, 10 parts; added keys + circlips (explained) |
| Plan review (me) → approve | → 15:21:51 | 1.5 min | 0 | ICD drafted instantly: `shaft_line`, AX2 at X = 80, 9 interfaces, 0 problems |
| Archie's layout look | → 15:22:20 | 29 s | 1 | haiku 25.5 s, 4 706 output tokens for a JSON verdict |
| ICD approve → Run | 15:23:59 / 15:24:22 | 23 s | 0 | |
| 3 design turns in parallel | 15:24:22 → 15:25:45 | 70–80 s each | 302 + 207 + 19 | $3.01 Gear, $2.96 Pinion shaft, $0.19 Gear shaft |
| Gage reviews (opus) | 15:25:36 → 15:26:04 | 11–19 s each | ~20 total | |
| Hex: bearings, "keys", "circlips" | 15:25:49 | 0 s work, **waited 87 s** for a slot | 0 | |
| Gear clashes pinion 149.5 mm³ → Axel rework | 15:25:51 → 15:28:26 | **2.6 min** | 63 | fixed by 0.15 mm backlash |
| Pinion shaft sub integrated | 15:26:13 → 15:26:30 | 17 s | 1 | visual 10.6 s |
| Gear shaft sub **stopped** (false) | 15:28:28 → 15:28:49 | — | 2 | blocked 6.9 min while I diagnosed + fixed + restarted |
| Gear sub (retry, fixed code) → final → drawings/DFM | 15:35:42 → 15:36:36 | 54 s | ~6 | final: "looks wrong" (loose keys), not confirmed, carries on |

Total 17 min wall clock; machine time without my pauses and the false stop ≈ 6.5 min. **Where the time goes: the
LLM.** Build worker per build 0.2–7 s (`timings_s`: the final gear 6.6 s build + 6.6 s determinism; shafts 0.15–0.4 s);
all builds together < 45 s. LLM: design turns 70–125 s, Gage 11–19 s per part, visual checks 10–25 s per level,
planning 43 s. The gear rework (2.6 min) and the false stop were the two big avoidable delays.

## What the agents told the user
- Archie's plan narrative was honest: it said the brief asked for only shafts and bearings and why it added keys and
  circlips. Good.
- Layout look (unprompted, before ICD approval): correct relations, but headed **"It doesn't look right:"** when the
  verdict was *unsure* and every relation ok; the only "problem" was the picture's origin triad (a blue arrow it
  called "an unlisted blue spike").
- Pinion sub: "Key (3) lies on the floor… I measured the parts in question and found nothing to confirm it, so the
  office carries on". True that the key isn't fitted, but the reassurance is misleading: the "key" is a spur gear and
  nothing will ever fit it; measurement cannot confirm a loose part.
- Gear sub stop: the same visual paragraph **twice**, internal instance names ("Gear shaft<1>", "Item 3") in the text,
  and the advice "this usually comes from the layout" (wrong here). After Apply, the action reads "Retry the **0**
  blocked parts".
- Final: "Fitz integrated the program, 0 clashes" directly under "2 clashes in the final assembly"; the Assembly card
  says "0 clashes" beside a red "2 clashes" chip. Program shows Complete / Integrated while every level says Looks wrong.
- Gage caught the ICD/brief mismatch (bore Ø26 vs brief Ø22, key 8×7 vs 6×6) as notes. Good.

## Defects, by severity
1. **Hex reads standard parts by any noun in their name** (S1, fixed). "Pinion key" → Spur gear m2 z24, "Gear
   circlip" → Shaft Ø22×120: the gear/shaft branches of `librarian.read_toolbox` (`assembly/librarian.py:254-270`) fire
   on "pinion"/"gear"/"shaft" in the title; the Toolbox has no key or circlip. Result: 4 junk parts in the assembly and
   BOM. Fix: `office/platform_env.py` `NOT_STOCKED` — a standard ticket named key/circlip/retaining ring/seal/… skips the
   Toolbox reading (it then goes to a designer as a bought-out part, CD-031).
2. **Keys and circlips are never placed** (S1, not fixed). The ICD has `key` interfaces with `key_item`, but
   `icd.seated` (`office/icd.py:2042`) only seats bearings and dowels, so keys/circlips go to the parts bin, and the
   Toolbox has no DIN 6885 key / DIN 471 ring. Needs a key + circlip component and seating (fits the
   `wip/office-direct` deterministic-parts work).
3. **Visual stop confirmed by an unrelated clash** (S1, fixed). `visual.targets_from` matches labels by substring
   ("Gear" is in "Gear shaft"), and `visual.targeted` counted any clash of a flagged part, so a loose-key complaint was
   "confirmed" by a 2.2 mm³ shaft↔bearing contact and the sub-assembly stopped, although whole-program clashes are
   advisory (PD-71). Fix: `assembly/visual.py` `targeted` — with ≥ 2 flagged parts only a clash between flagged parts
   confirms.
4. **Shaft-line relation applied to one shaft's sub-assembly** (S2, fixed). "The shafts are parallel…" was asked of
   a level with one shaft; the picture "lacked the second shaft" → looks wrong. Fix: `assembly/visual.py:160`, one
   shaft gets "<shaft> runs in two bearings…".
5. **Token burn** (S1, not fixed). One cold design turn costs ≈ $3 (Gear $3.01 / 4 turns, Pinion shaft $2.96 /
   3 turns) — 300 tokens of a 1 000-token trial per part; three in parallel spent 528 tokens in 85 s. Default program
   budget 3 000 exceeds the trial wallet. The third concurrent run got a 138-token budget (reservations) and ended
   `stopped_budget` at 19 tokens yet was approved (`agent/session.py` `_budget_hit`; investigate).
6. **Toolbox bearing has sharp bore corners** (S2, not fixed). A correctly filleted shoulder (r 0.4 < 6204 r_s 1.0)
   overlaps the envelope by 2.2 mm³ per bearing (`toolbox.py:164` `_bearing`); every real shaft will show these.
   Fix needs a chamfer per ISO 15 r_s (verify values), closed-form volume, `VERSION` bump.
7. **First gear clashed the pinion by 149.5 mm³** (S2, unexplained). Bench check: Toolbox z20 vs `fw_std.spur_gear`
   z60 at 80 mm with the ICD's 3° phase = 0.00 mm³ (412 mm³ unphased), so placement maths is right; Axel's rev 1 had
   the tooth on +X. Needs a deterministic repro from the rev-1 STEP. Cost 2.6 min + 63 tokens.
8. **Pinion silently replaced by a Toolbox gear** (S2). Its description matched `toolbox.match`, the gear's didn't
   (`toolbox.py:462` penalises "with a"). The pinion loses its ICD keyway (IF-04) and 42CrMo4 (BOM: "Steel C45, buy"),
   never seen by Gage; the gear went through a 4-min LLM design. Inconsistent and wrong either way.
9. **Standard parts wait for an LLM slot** (S3). Hex lookups (0 s, 0 tokens) took one of the 3 slots and waited 87 s
   (`office/orchestrator.py:689`).
10. **ICD contradicts the plan** (S3). Plan: Ø22 gear seat, 6×6 key; ICD `shaft_bore` d = 26 (the shaft's envelope),
    key 8×7.
11. **Archie's words** (S3): "It doesn't look right" header on an unsure verdict (`office/visual_office.py:119`);
    duplicated visual paragraph (fixed, `visual_office.py:242`); instance names "<1>" and "Item 3" in chat and ticket
    comments (`assembly/visual.py:700`, `platform_env.py:706`); "0 clashes" next to "2 clashes"; "Retry the 0 blocked
    parts" after Apply (`archie_chat.py:508` relabels); "comes from the layout" advice when it doesn't.
12. **Picture quirks** (S3): the origin triad is drawn and read as a part by the checker; the Visual-check image on
    the Interfaces tab renders tiny inside a wide empty frame.
13. **Smithy applies MLD-01 (draft, moulding) to a CNC-turned shaft** (S3, `manufacturing/rules.py:806`).
14. Axel set `EXPECTED.bbox[2] = 1000 + a0·1000 + n` to read values through a failing check (a wasted build); the
    revision cause says "Gage sent back" for Fitz's clash.

## Fixes made (branch `wip/live-gear`)
- `office/platform_env.py`: `NOT_STOCKED`; Hex no longer turns a key/circlip/ring/seal into its host's family.
  Test `test_hex_does_not_read_a_key_or_circlip_as_its_host`.
- `assembly/visual.py`: one-shaft relation; `targeted` confirms only clashes between flagged parts. Tests
  `test_relations_of_one_shaft_sub_assembly_ask_for_no_parallel_pair`,
  `test_targeted_check_confirms_only_clashes_between_flagged_parts`.
- `office/visual_office.py`: the visual line is said once in a stop message (test in
  `test_failure_and_level_messages`).
- Verified live: with the visual fixes the blocked Gear-shaft sub integrated on retry and the program completed.

## Parked
- PD (proposed): a design turn's cost must be capped well below a trial wallet; default program budget ≤ wallet.
  Default used: none changed.
