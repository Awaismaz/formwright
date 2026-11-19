---
name: toolbox-component
description: Add or change a Formwright Toolbox standard component (bolts, nuts, washers, bearings, gears, shafts, flanges, brackets and new families such as pulleys, circlips, keys or profiles) in src/aicad/toolbox.py. Use for any change to a generator, its standard table, parameters, keywords/matching, VERSION, or the "Use Toolbox component" offer.
---

# Toolbox component

Toolbox parts are **deterministic and versioned**: the same inputs give byte-identical STEP, now and in a year.
Each generator returns `(shape, EXPECTED)`, with EXPECTED computed analytically, so the normal CHK-04/05 checks apply.

## Steps (`src/aicad/toolbox.py`)
1. **Table.** Standard dimensions go in a module-level dict named after the standard (see `HEX_HEAD`, `SHCS`,
   `BEARING`, `KEYS`). Add a comment naming the standard and its edition. Values typed from public references are
   unverified until PD-13 is resolved, so say so in `Component.note` or the docs. Never invent values.
2. **Generator** `_<code>(**params) -> (shape, expected)`. Build from primitives (`_cyl`, `_hex_prism`, ...).
   `expected = {"bbox": [...], "volume": <closed form>, "solids": n}`, using closed-form volumes and shoelace areas
   for polygons (`_shoelace`), **never** `shape.volume`. Set `.label` on the result.
3. **Register** a `Component(code, name, category, standard, keywords, params, material, build, title, note, icon)`
   in `COMPONENTS`. Parameters are `P(name, label, default, unit, min, max, options, help, integer)`; use `options`
   for standard sizes (`_m()` gives metric M3–M24). `keywords` drive `match(prompt)`, the chat popup offering
   "Use Toolbox component" vs "Continue with custom design" (DS-021). Include standard numbers and common synonyms,
   and avoid keywords that hijack generic requests.
4. State simplifications honestly in `note` (cosmetic threads, envelope bearing, and so on).
5. **VERSION.** Bump the module `VERSION` on *any* change to the geometry of an existing component.
   `model_source()` writes `TOOLBOX = {'code', 'version'}` into each project, so old models stay reproducible. Adding a
   new component without changing existing geometry needs no bump.
6. Update the agent's code list in `src/aicad/agent/prompt.py` ("Toolbox" section) with the new code and its
   parameter names.

## Parts that go into an ICD seat (keys, rings, bearings)
- Model them **as fitted** so they seat with 0 mm³ interference (DIN 471 ring: bore at the groove Ø d2, not the
  free d3), give mounting corners their ISO 582 r_s min (bearings), and add a `seated()` branch in
  `office/icd.py` with the part's own frame documented (see `icd.key_frame`). Prove it with a kernel test
  that places every part by the ICD and intersects solid by solid (`tests/test_toolbox_keys.py`).
- A Toolbox generator used for a *designed* part (a gear sized to the ICD) must carry every ICD feature
  (`platform_env.toolbox_gear_for`), else the part stays designed.

## Tests (`tests/test_library.py`)
- `test_every_toolbox_component_is_deterministic_and_matches_expected` iterates `COMPONENTS` automatically. It must
  pass for the new code: checks green, two builds give identical STEP bytes.
- Add matching cases to `test_toolbox_validation_and_matching`: a positive prompt with sizes pre-filled, a negative
  prompt that must not match, and out-of-range/non-option values that raise `ToolboxError`.
- If a recognised import could be this component (as with gears), consider "Replace with Toolbox part" with CHK-09
  as the exactness gate. This is in the SESSION_LOG (h) "Next" list.

## Record
Update DS-020 in `docs/PUNCH_LIST.md`. If the standard's licensing or verification is uncertain, extend PD-13 rather
than stopping.
