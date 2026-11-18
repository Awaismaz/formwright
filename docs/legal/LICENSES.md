# Third-party licences and SBOM (LEG-002)

Generated from the lockfiles on 2026-11-18 by `scripts/sbom.py` (offline: `uv.lock` + installed package metadata,
`web/package-lock.json`). This is an engineering audit, **not legal advice**. Counsel review of the copyleft items is
LEG-003 (OCCT in SaaS and in any distributed desktop/plugin) and LEG-004 (Blender / FreeCAD / SolveSpace patterns).

| File | What |
|---|---|
| `sbom-python.cdx.json` | CycloneDX 1.5 SBOM of the server: 110 runtime + 10 dev Python packages, with bundled native libraries as sub-components |
| `sbom-web.cdx.json` | CycloneDX 1.5 SBOM of the web app: 61 runtime + 216 dev npm packages |
| `licenses.json` | the classified audit: counts per licence class and the flagged packages |
| `license-allowlist.json` | every flagged package, with how Formwright uses it (the gate reads this) |

Regenerate after any dependency change: `uv run python scripts/sbom.py`. `tests/test_sbom.py` fails when the
committed SBOM no longer matches the lockfiles, and when a dependency with a copyleft, proprietary or unknown licence
is not on the allow-list (or its class gets worse than the allow-list entry allows, e.g. a package relicensing to AGPL).

## Summary

| Set | Packages | Licences |
|---|---|---|
| Python runtime | 110 | MIT 47 · BSD-3-Clause 33 · Apache-2.0 14 · BSD-2-Clause 3 · PSF-2.0 3 · ISC 2 · dual Apache/BSD 3 · MIT-0, MIT-CMU, MIT OR Apache-2.0, numpy's BSD/0BSD/MIT/Zlib/CC0 set · **MPL-2.0 1 (certifi)** |
| Python dev | 10 | MIT 7 · BSD-3-Clause 2 · **MPL-2.0 1 (pathspec)** |
| npm runtime (shipped in the web bundle) | 61 | MIT 58 · ISC 1 · 0BSD 1 · **OFL-1.1 1 (Inter font)** |
| npm dev (build and test only) | 216 | MIT 196 · ISC 12 · Apache-2.0 5 · BSD-3-Clause 2 · CC-BY-4.0 1 (caniuse-lite data) |

**No GPL, AGPL or SSPL package** is a dependency of the server or the web app. No package has an unknown licence.

## Flagged items and how each is used

| Package | Licence | Class | Use, and why it is acceptable today |
|---|---|---|---|
| `cadquery-ocp-novtk` 8.0.1.1.0 (OCP, the CAD kernel) | bindings Apache-2.0; **bundles OCCT 8.0 under LGPL-2.1-only WITH OCCT-exception-1.0** | weak copyleft | The Python bindings load the unmodified OCCT shared libraries (`TK*.dll` / `.so`) shipped in the wheel: dynamic linking, no modification. Formwright runs it server-side (SaaS), so nothing is distributed to customers today. If a desktop app or CAD plugin ever ships these libraries: keep the LGPL notice, ship or offer the OCCT source, and keep the libraries replaceable (no static linking, no anti-relinking measures). The OCCT exception relaxes the LGPL's header/template clauses. Counsel: LEG-003. |
| ↳ FreeImage (inside the OCP wheel) | FreeImage Public Licence OR GPL-2.0 OR GPL-3.0 | weak copyleft | Shared library used by OCCT's image I/O; we rely on the FIPL option (MPL-1.1-based, file-level). Not used directly by Formwright. |
| ↳ LibRaw (inside the OCP wheel) | LGPL-2.1 OR CDDL-1.0 | weak copyleft | Shared library (raw.dll), unmodified, dynamically linked; not used directly. |
| ↳ FreeType (inside the OCP wheel) | FTL OR GPL-2.0 | permissive option | Used under the FreeType Licence option (attribution). |
| `certifi` | MPL-2.0 | weak copyleft (file level) | CA bundle used unmodified by the HTTP clients. MPL obligations arise only when certifi's own files are modified and distributed. |
| `claude-agent-sdk` 0.2.182 | SDK MIT; **bundles the Claude Code CLI executable (Anthropic commercial terms)** | proprietary component | Design-agent runtime. The CLI runs as a separate subprocess, not linked into Formwright and not redistributed. Development uses the founder's Claude Code login; production must use an API key (PD-09 / AGT-015). |
| `pathspec` (dev only) | MPL-2.0 | weak copyleft | A mypy dependency for development; never deployed. |
| `@fontsource-variable/inter` | OFL-1.1 | weak copyleft (fonts) | The Inter UI font, served unmodified in the web bundle. OFL permits bundling and embedding; only a modified font must stay OFL and drop the reserved name. |
| `caniuse-lite` (dev only) | CC-BY-4.0 | permissive (attribution) | Browser-support data read by the build tooling; not shipped. |

## Outside the SBOM (not package dependencies)

| Tool | Licence | How it is used |
|---|---|---|
| Blender 4.x/5.x (Mesh Studio renders) | GPL-2.0-or-later / GPL-3.0 | Optional, installed separately on the machine; Formwright starts it as a **separate process** with a generated scene script and reads the files it writes. No Blender code is linked or shipped. The generated scene scripts are ours (Blender's GPL does not reach output files or scripts that only call it as a program). Counsel: LEG-004. |
| OpenAI Images API (AI Render Studio) | service terms | Remote API on the customer's own key (BYO); no code dependency beyond the MIT `openai` client. |
| Anthropic API / Claude Code login | service terms | Remote service behind the agent SDK (see above). |

## Method and limits

- Python licences come from the installed wheels' metadata, in this order: PEP 639 `License-Expression`, a short
  `License` field, then trove classifiers. A bare "BSD License" classifier is recorded as BSD-3-Clause (both BSD
  variants are permissive; the exact variant does not change the outcome). Packages whose metadata is empty or prose
  are set in `OVERRIDES` (in the script) with the source of the value.
- Native libraries inside wheels (`BUNDLED` in the script) are listed from the installed wheels' `.libs` folders, as
  CycloneDX sub-components; their licences are engineering readings of upstream licences and need counsel's
  confirmation (LEG-003).
- Environment markers are evaluated for Linux x86-64/arm64 servers and Windows workstations; dependencies only
  installed elsewhere (e.g. emscripten) are left out. Packages not installed on the auditing machine (Linux-only ones
  when auditing on Windows) take their licence from `OVERRIDES`.
- npm licences come from the lockfile (npm records them), then `OVERRIDES` for the vitest family whose entries lack
  one (checked against the installed `package.json` files on 2026-11-18), then `node_modules` if present.
- No network access, no new dependency: the script uses only the standard library and `packaging` (already
  installed as a transitive dependency).
