---
name: add-studio-feature
description: End-to-end recipe for adding or changing a manual CAD feature in the Formwright Design Studio (revolve, sweep, loft, draft, rib, pattern-any-feature, reference planes, sketch tools, or edits to fillet/chamfer/hole/shell/mirror/extrude/sketch). Use whenever work touches DS-010/DS-017/DS-024, `fw._op`, `validate_feature`, the FeatureManager PropertyManager or the CommandManager ribbon.
---

# Add a manual Studio feature

A manual feature is a JSON dict stored as a Python literal in the project's model script and replayed on every
build. It must work with no AI and no tokens, and the design agent must be able to keep it intact. Touch every
layer below in one change. A feature that is only partly wired is worse than one that is missing.

## 1. Geometry: `src/aicad/fw.py`
- Add a branch to `_op(part, f, diag)`. It takes the current solid and the validated dict and returns the new solid.
- Select topology **by location, never by index**: `edges_near(part, points)` and `faces_near(part, point, normal=...)`.
  Store picked points/normals in the dict, not ids.
- Edge picks: send the edge's true middle (`edgeMid`) plus `edge_refs` (`edgeRef`: line direction / circle axis) and
  resolve with `_resolve_edges`; face picks with `_resolve_face`. Ops listed in `REF_OPS` (studio.py) get `ref_bbox`
  stamped server-side, so picks follow the body when a dimension changes (`fw._remaps`). Add new picking ops there.
- When a selection resolves to nothing, raise a plain `ValueError("... was not found (the geometry changed)")`.
  `apply_manual` no longer aborts the build: the feature is skipped and listed in `status.manual_errors` (a rebuild
  error the tree offers to repair). `_apply_manual(strict=...)` refuses the change when the feature just added or
  edited fails (`strict={id}`), or when suppress/delete breaks another feature (`strict="new"`).
- Kernel exceptions must reach the user as plain words: raise `ValueError` with an engineering sentence (see
  `_too_large`), and map anything else through `aicad.platform.plain.build_error`.
- Use `diag` (the bbox diagonal) for "through all" depths. Do not hard-code sizes.
- Sketch-based ops: reuse `_plane(spec)` and `sketch_region(profiles)`. Loops are normalised CCW, so the extrude
  direction is always out of the face (see `test_sketch_boss_always_extrudes_out_of_the_face`).
- Do not read files, globals, time or randomness. The op must be a pure function of `(part, f)`, because the runner's base
  cache (`_BASE_CACHE`) replays manual ops on a cached base and CHK-08 compares rebuilds byte for byte.

## 2. Validation: `src/aicad/platform/routers/studio.py`
- Add the op to `OPS` and a branch in `validate_feature()`. Every number goes through `_num(v, name, lo, hi)` and every
  point through `_pt`, with explicit list-length caps. Copy only whitelisted keys into `out`.
- The output is written back into the model script and parsed with `ast.literal_eval`, so it may contain only numbers,
  strings, bools, None, lists and dicts.
- Error messages are user-facing (422 detail). Use plain engineering wording.

## 3. Frontend
- `web/src/lib/types.ts`: extend the `ManualFeature["op"]` union and its optional fields.
- `web/src/pages/app/studio/FeatureManager.tsx` (PropertyManager): `TITLE`, `selectKindsFor(op)` (edge vs face
  picking), default name and size, the fields, and the payload builder in the submit handler. `FeatureOp` excludes
  `sketch`, which has its own editor (`SketchEditor.tsx`, solver in `web/src/sketch/model.ts`).
- `web/src/pages/app/studio/CommandManager.tsx`: add a ribbon button on the right tab (Features / Sketch / Evaluate /
  View / Library) with a lucide icon and a one-line `tip`. Use SOLIDWORKS names: "Revolved Boss/Base", "Revolved Cut",
  "Swept Boss/Base", "Draft", "Rib", "Linear Pattern", "Reference Plane".
- `web/src/pages/app/ProjectStudio.tsx`: `openPm` routes the command. Tree actions go through `manualCall(fn, okMsg,
  optimistic)`. Keep the tree optimistic, with rollback (DS-016).

## 4. Design agent
- If the agent should author or understand the new op, update `src/aicad/agent/prompt.py` (manual-features section).
- If a new `fw.<name>` helper can appear in agent text, add it to `_SCRUB` in `src/aicad/agent/session.py`. Users must
  never see helper, file or tool names (DS-014).

## 5. Tests: `tests/test_studio.py`
Model the test on `test_manual_feature_lifecycle`:
```python
def test_<op>_feature(app_client):
    c = app_client
    signup(c, "<op>@x.com")
    pid, ws = _project_with_model(c, (DEMO / "l_bracket.py").read_text(encoding="utf-8"))
    v0 = c.get(f"/api/projects/{pid}/files/status.json").json()["fingerprint"]["volume"]
    r = c.post(f"/api/projects/{pid}/manual", json={"feature": {...}})
    assert r.status_code == 200, r.text
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["ok"] and st["fingerprint"]["volume"] == pytest.approx(v0 + <analytic delta>, rel=1e-6)
```
- Assert an **analytic** volume or bbox delta (a hand formula), plus: suppress restores `v0`; bad input gives 422;
  an impossible selection gives a clean error and leaves the model unchanged.
- Demo parts live in `src/aicad/demo/` (l_bracket, mounting_plate, pipe_flange, stepped_shaft).

## 6. Verify and record
- `uv run pytest -q tests/test_studio.py`, then the full gate (see `formwright-ship`).
- Exercise it in the browser at least once (`studio-e2e`): pick, preview, OK, edit from the tree, suppress, delete.
- Update the DS-* row in `docs/PUNCH_LIST.md`, naming the test as evidence.
