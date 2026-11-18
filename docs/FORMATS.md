# Formwright native file formats

Formwright's own files carry the **full parametric model** (and each module's work on it) from one workspace to
another, so nothing has to be recognised again, unlike STEP. Every format uses one container, one manifest, one
checksum and signature scheme and one set of untrusted-input rules. The manifest's `kind` says what is inside.

Code: `src/aicad/native/` (`container.py` writer/reader, `gate.py` script checks, `part.py`, `bundles.py`,
`modules.py`); API: `src/aicad/platform/routers/mod_native.py` + `native_modules.py`; client: `web/src/lib/native.ts`,
`web/src/components/NativeImport.tsx`, `NativeExport.tsx`. Tests: `tests/test_native_formats.py`, `web/src/lib/native.test.ts`.

## Extensions

| Extension  | Media type                                         | Manifest `format`         | `kind`            | Holds |
|------------|----------------------------------------------------|---------------------------|-------------------|-------|
| `.fwpart`  | `application/vnd.formwright.part+zip`              | `formwright.part`         | `part`            | one part: model script incl. manual-feature block, helpers, imported STEP blanks + recognised features, reference images, exact STEP, status subset, thumbnail, optional revisions and conversation |
| `.fwasm`   | `application/vnd.formwright.assembly+zip`          | `formwright.assembly`     | `assembly`        | assembly document (instances, transforms, mates, fastener stacks), BOM snapshot, each distinct project part embedded once as `.fwpart`, Toolbox parts as generator code + parameters |
| `.fwdrw`   | `application/vnd.formwright.drawing+zip`           | `formwright.drawing`      | `model` / `draft` | `model`: sheet settings + edits + embedded `.fwpart` (+ issue PDF for people without Formwright). `draft`: a 2D drawing (Drawing Studio drafts) with every saved revision |
| `.fwprog`  | `application/vnd.formwright.program+zip`           | `formwright.program`      | `program`         | Design Office program (brief, plan, items, tickets, gates, budget), an events summary, and the linked parts (`.fwpart`) and assemblies (`.fwasm`) |
| `.fwrender`| `application/vnd.formwright.render+zip`            | `formwright.render`       | `mesh` / `ai`     | `mesh`: Mesh Studio look + finished renders (stills, turntables) of a part. `ai`: AI Render Studio jobs (settings, refined prompt, reference, images). Both embed the part. Never `.blend` scenes, never the API key |
| `.fwmfg`   | `application/vnd.formwright.manufacturing+zip`     | `formwright.manufacturing`| `mfg`             | Manufacturing Advisor analysis/report of a part + the part |
| `.fwcalc`  | `application/vnd.formwright.calculation+zip`       | `formwright.calculation`  | `calc`            | Engineering Advisor load cases, calculation sets, stack-ups, checklist + the part |
| `.fwprint` | `application/vnd.formwright.print+zip`             | `formwright.print`        | `print` / `upload`| `print`: 3D Print Prep setup of a part + the part. `upload`: an uploaded mesh (STL/OBJ/3MF) as the module stores it |
| `.fwread`  | `application/vnd.formwright.read+zip`              | `formwright.read`         | `read`            | Image & Drawing to CAD: the source drawing/photo, what was read, the user's confirmed values and answers |
| `.zip`     | `application/zip`                                  | `formwright.projects`     | `projects`        | "Download all": every built project as `.fwpart` (same container, signed) |

## Container

A zip. Entry 1 is `mimetype` (stored, the media type: lets a renamed file still be recognised), entry 2
`manifest.json`, then every other entry sorted by name. All timestamps 1980-01-01 00:00, Unix mode 0644, images /
nested packages / PDF stored, text deflated. The same content exported twice is byte-identical (a part's
`created_at` is the time of the build that was exported, not of the download).

### Manifest (common fields)

```json
{
  "format": "formwright.part", "format_version": 1, "kind": "part",
  "app_version": "0.0.1", "generator": "Formwright", "created_at": "2026-11-18T10:04:12Z",
  "title": "Mounting plate", "description": "…",
  "kernel": {"build123d": "0.13.0", "cadquery-ocp": "7.9.x"},
  "source": {"org": "<24-hex keyed hash>", "project": "<24-hex keyed hash>"},
  "entries": {"model.py": {"sha256": "…", "size": 1234}, "…": {}},
  "signature": {"alg": "HMAC-SHA256", "org": "<same as source.org>", "value": "<hex>"}
}
```

`.fwpart` adds `part` `{name, material, units: "mm"}`, `geometry` `{fingerprint {volume, bbox, faces, edges, vertices,
solids}, step_sha256, bbox_minmax, mass, checks_ok}` (from the exported build) and `contents` (history, revisions,
current_revision, refs, chat, imported, manual_features, helpers, parameters, features). Other formats add a
section named after themselves (`assembly`, `drawing`, `program`, `module`).

Workspace, project and user ids never appear: `source.*` are keyed hashes (HMAC of a server secret), and JSON written
from module folders has `org_id`/`project_id`/`created_by`/`user_id` set to null (filled with the importer's ids) and
absolute paths reduced to a file name.

### `.fwpart` layout

```
model.py                        model script (incl. "# --- Formwright manual features" managed block)
<helper>.py                     helper modules (top level, identifier names)
imports/<name>.step|.stp|.json  imported STEP blanks + recognised-feature JSON
refs/<name>.png|jpg|jpeg|webp|gif  reference images            (option, default on)
out/part.step                   exact geometry of the exported build
out/status.json                 params, param_meta, editable_params, features, checks, mass, fingerprint, …
thumbnail.png                   one clean view
design/brief.json               {name, description}
revisions/<n>/model.py|status.json|cause.json   revision history (option, default on; "who" is not exported)
chat/chat.jsonl                 user + assistant text only, no tools/costs (option, default OFF)
```

Part-linked module files (`.fwmfg`, `.fwcalc`, `.fwprint` kind `print`, `.fwrender`) are `part.fwpart` +
`doc/<path>` for allow-listed files of the module's workspace folder (`manufacturing/`, `engineering/`, `print/`,
`mesh/`, `airender/`). Caches (`engineering/geometry.json`, Mesh Studio `geom/`), export lists, Blender scenes and
mesh exports are never included.

## Versioning

`format_version` is an integer per format (currently 1). A reader accepts versions ≤ its own; a newer file is
refused ("made by a newer version of Formwright"). Older versions are upgraded in memory by a chain of migrations
registered with `@container.migration(format, from_version)` (one step per version). Checksums are verified against
the file as written, before migrating. Version 0 (pre-release draft, fingerprint at the top level) is migrated as the
example. Rules: adding optional manifest fields or entries does not bump the version; renaming/removing/restructuring
anything a reader relies on does, together with a migration.

## Security model (every file is untrusted input)

Nothing is written or run until all of these pass (`container.read_package`, `gate`, each `parse_*`):

1. **Size**: upload ≤ 200 MB; ≤ 2,000 entries; each entry ≤ 150 MB; manifest ≤ 2 MB.
2. **Zip bombs**: decompression is streamed and counted (a lying header can't bypass it): total ≤ 400 MB across the
   file *and all embedded packages* (one shared budget); entries above 1 MB with a ratio above 120:1 are refused;
   nesting depth ≤ 2 (`.fwprog` → `.fwasm` → `.fwpart`).
3. **Paths**: relative, `/`-separated, no `..`, `.`, empty, hidden (`.x`), drive-letter, backslash, NUL or Windows
   reserved names, ≤ 6 levels; no directories, symlinks or special files; no encryption; stored/deflate only;
   duplicate names refused. Each format has an **allow-list** of entry names; anything else is refused. Files are only
   ever written to destinations computed by the server, and re-checked to stay inside the target folder.
4. **Manifest**: valid JSON object, known `format` matching the extension (or sniffed `mimetype`), supported
   `format_version`; **every entry listed with its sha256 and size, nothing missing, nothing extra**.
5. **Content**: images/PDF/MP4 by magic bytes, STEP by its ISO-10303-21 header, JSON parses, text is UTF-8; module
   content goes through the module's own validation (2D draft normaliser, Image-to-CAD file sniffing, the mesh parser
   for STL/OBJ/3MF, drawing options through the API schema). Uploaded drawings and meshes are re-validated, not trusted.
6. **Scripts**: every `.py` (model, helpers, every revision) passes the runner's import tripwire (R-SEC-05) before
   anything runs. Files **not** signed by this workspace also pass a strict allow-list (`gate.py`): imports only from
   build123d (top level), `aicad.fw`/`aicad.toolbox`, a few pure standard-library modules and the file's own helpers;
   no file/network names (`import_*`/`export_*`, `Mesher`, `open`, …) or attributes (`.write_*`, `.export_*`, `.save`,
   …); no dunder or private attributes, `getattr`/`globals`/`vars`…, `global`, or strings containing `__`. This is
   defence in depth on top of the separate build-worker process; it is **not a sandbox** (PD-10 still applies).
7. **Trust**: the manifest is signed with HMAC-SHA256 under a per-workspace key derived from the server secret
   (`FW_FILE_SECRET`, else a random key in `<data>/secrets/native_files.key`). A file whose signature verifies for the
   current workspace is "from your workspace" (no confirmation; only the tripwire applies to its scripts). Anything else
   (another workspace, unsigned, or signed by this workspace but edited) shows a notice and needs explicit confirmation
   (`confirm=1`) before the first rebuild. Foreign Engineering Advisor sign-offs are not carried over.
8. **Verification**: an imported part is rebuilt in the importing workspace's build worker and its fingerprint is
   compared with the manifest (counts exact; volume to 1e-6 relative; bbox to 1e-4 mm): **Verified identical**,
   **Rebuilt with differences** (list of differences), or — if the script cannot rebuild here — **Exact geometry kept
   (read-only)**: the embedded STEP becomes an imported blank and the original script is kept unexecuted in
   `.fw/native/`. The result is stored in `.fw/native/import.json` and shown in the Studio Files panel.

## API

- `GET /api/native/projects/{id}/export?history=1&refs=1&chat=0` → `.fwpart`
- `GET /api/native/projects/export-all` → `.zip` of `.fwpart`
- `GET /api/native/assemblies/{id}/export` → `.fwasm` (409 if a part changed since it was placed)
- `GET /api/native/drawings/{project_id}/export` → `.fwdrw` (model drawing)
- `GET /api/native/programs/{id}/export` → `.fwprog`
- `GET /api/native/modules/{kind}/{id}/export` → kind `mfg|calc|print|mesh|ai` (project id), `draft` (2D drawing id),
  `read` (Image-to-CAD upload id), `upload` (3D Print Prep mesh upload id)
- `POST /api/native/inspect?filename=` (raw body) → kind, summary, trust, warnings; nothing is written
- `POST /api/native/import?filename=&confirm=1` (raw body) → created ids + verification
- `GET /api/native/projects/{id}/provenance` → how an imported part was verified

Assembly import links each part to an existing project of the workspace with the identical fingerprint, STEP and
material instead of duplicating it (also for programs, archives). Part-linked module files always import a new
project, so they never overwrite another part's outputs.

## PWA file handlers (to add to the web app manifest)

```json
"file_handlers": [{
  "action": "/app/open-file",
  "accept": {
    "application/vnd.formwright.part+zip": [".fwpart"],
    "application/vnd.formwright.assembly+zip": [".fwasm"],
    "application/vnd.formwright.drawing+zip": [".fwdrw"],
    "application/vnd.formwright.program+zip": [".fwprog"],
    "application/vnd.formwright.render+zip": [".fwrender"],
    "application/vnd.formwright.manufacturing+zip": [".fwmfg"],
    "application/vnd.formwright.calculation+zip": [".fwcalc"],
    "application/vnd.formwright.print+zip": [".fwprint"],
    "application/vnd.formwright.read+zip": [".fwread"]
  }
}]
```
The `/app/open-file` route should read `window.launchQueue` and call `openNativeImport(file)` (`web/src/lib/native.ts`).
