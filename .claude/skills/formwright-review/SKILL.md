---
name: formwright-review
description: Formwright-specific review checklist for a diff before commit (honesty labels, agent-internals leakage, manufacturing claims, determinism/versioning, tenant scoping, path safety, analytic tests, founder data). Use before every commit that touches src/ or web/, after a feature is built, or when asked to review Formwright changes. Complements the generic /code-review.
---

# Formwright review checklist

Run `git diff` (plus `git diff --cached`) and check each item. Fix violations; don't just list them.

## Product rules (CLAUDE.md)
- [ ] **Honesty labels**: only Design Studio is Live; other modules are labelled **Preview**; sample data says
      **SAMPLE**; simulated payments are shown as simulated. No new copy claims a capability that doesn't exist.
- [ ] **No agent internals in the UI**: no file names (`model.py`, `refs/`), tool names, Python, build123d, model ids,
      or tracebacks in user-visible strings, toasts, chat or errors. New identifiers are covered by `_SCRUB`.
- [ ] **No manufacturing or engineering validity claims** ("validated", "safe", "ready for production"). Checks prove
      geometric consistency only. Material values cite a source or are flagged to verify.
- [ ] Plain engineering language and SOLIDWORKS naming in UI text.

## Geometry
- [ ] Acceptance uses deterministic checks, not renders. New EXPECTED values and test assertions are **analytic
      formulas**, not measured from the shape.
- [ ] Determinism: no time, random or set-order dependence. Toolbox `VERSION` is bumped if existing geometry changed.
- [ ] Topology is selected by location (`edges_near`/`faces_near`), never by index.
- [ ] Imported geometry stays exact (no silent approximation of the blank).

## Platform and security
- [ ] Every DB query on tenant data is scoped by `org_id`, and role checks use the existing `Ctx` dependencies.
      Cross-org access returns 404.
- [ ] File access goes through allow-listed names and workspace resolution, with no user-controlled paths. Uploads are
      type-sniffed and size-capped.
- [ ] Mutating endpoints rely on the CSRF middleware (no new exemptions without a reason). God-mode routes stay behind
      `god_ctx` and 404 in production.
- [ ] The tool allow-list, guard and tripwire are not widened. If they are, a PD row and a RISKS entry exist.
- [ ] No secrets, `data/` contents or founder credentials in code, tests, logs or commits.

## Tests and docs
- [ ] New behaviour has a test: pass path, failure path, and a bounds/422 case.
- [ ] `docs/PUNCH_LIST.md` rows touched are updated with evidence; new founder decisions are parked as PD-xx.
