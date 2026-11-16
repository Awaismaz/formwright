# Mesh Studio (module `mesh`): report

Branch `module/mesh`. Mesh Studio is now **Live** as a **product render studio for verified parts**. It takes a
project's latest verified build, tessellates the exact STEP with our OCCT, drops the part into a studio scene in
headless **Blender 5.3 (Cycles)**, and returns photoreal stills, turntables, an editable `.blend`, and GLB / OBJ /
STL visualisation meshes. Everything it produces is labelled as **visualisation, not the exact model**.

## What was built

| Area | What it does |
|---|---|
| Visualisation mesh (MSH-008, MSH-009) | `meshstudio/geometry.py` re-imports `out/part.step` and tessellates it with `aicad.printprep.mesh.tessellate_shape` (chordal tolerance = part diagonal / 8000, clamped 0.005–0.05 mm; 5° angular). The mesh stays welded and watertight. Shading uses per-corner "split" normals: area-weighted and smooth inside each exact B-rep face, breaking at face boundaries, so cylinders read round and edges stay crisp. Checks MS-01..08 (watertight, manifold, outward winding, degenerate triangles, self-intersection, shells, measured deviation from the exact surface, UV) are **measured by the 3D Print Prep functions** (`printprep.analysis.topology`, `self_intersections`, the deviation from `tessellate_shape`), not duplicated. Cached once per STEP content (sha256) in `<ws>/mesh/geom/`. |
| Finishes (MSH-004) | 14 physically based recipes (Principled BSDF): anodised aluminium in 9 colours, bead-blasted aluminium, brushed aluminium, machined steel (turned anisotropy around the part axis), brushed stainless, black oxide (oiled clear-coat sheen), brass, copper, bead-blasted titanium, ABS (textured) and PLA (satin) in 9 colours, rubber in 3 colours, and a neutral studio clay. Details: low-amplitude roughness variation, fine bump grain where it is larger than a pixel, and a Cycles Bevel shader node that rounds edges in **shading only** (the geometry is unchanged; can be switched off). |
| Material auto-mapping | `presets.map_material(text)` reads the project's material text: finish words first (black oxide, bead blast, anodise, brushed), then alloy families (stainless grades, titanium, brass/bronze, copper, aluminium grades, steel grades, cast iron, plastics, elastomers), then colour words. Unknown or unspecified materials start in studio clay. Every entry in our material library maps to a real finish (tested). The UI says what it suggested and why ("Material Carbon steel suggests Machined steel") and offers a one-click reset to the suggestion. |
| Lighting | Three rigs of area lights plus a three-stop gradient world: **Studio softbox** (key, fill, top and two vertical kick strips, light-grey sweep), **Dark dramatic** (narrow key and two rim strips on charcoal) and **Technical white** (bright, even, pure white). Lights are placed relative to the camera azimuth and scaled to the part (position and size ∝ diagonal, power ∝ diagonal²), so a 10 mm pin and a 1 m frame expose the same. The floor is a Cycles shadow catcher: renders come out with alpha and a real contact shadow, and Pillow composites a soft radial studio background unless **Transparent background** is on. View transform: Khronos PBR Neutral (made for accurate product colour). |
| Camera and framing | Presets **Hero 3/4** (85 mm), **Isometric** (true iso, orthographic), **Front**, **Top** (orthographic), **Low hero** (70 mm); aspect 4:3, 16:9, 1:1, 3:4. `framing.py` computes the camera in Python (deterministic, unit-tested): it bisects the distance for the tightest fit of the convex hull at 80% of the frame and centres the part with lens shift (perspective) or a lateral offset (ortho). Turntables are framed over the whole turn. **Auto pose** lays long slender parts (height > 1.6 × footprint) on their side, as a photographer would. |
| Preview → final (MSH-001) | A fast preview (720 px, 24 samples on GPU, adaptive sampling + OpenImageDenoise) re-renders automatically as settings change, one in flight at a time with the newest settings winning. **Render final** (1920 px, 256 samples, editable `.blend`) and **Turntable** (72 frames at 960 px → GIF via Pillow and H.264 MP4 via Blender's own encoder) run in the background queue with a progress bar fed by Cycles' sample count and per-frame markers. |
| Queue and cache | `jobs.py`: worker pool (default 1 Blender at a time, `FW_MESH_WORKERS`), previews jump ahead of exports, finals and turntables; max 6 pending per workspace and 30 overall (429 "queue full"); queued jobs can be cancelled. Results are cached by **(verified STEP content hash, preset hash, script version, CPU/GPU)**: asking again returns the finished job instantly ("Already rendered with these settings"). Previews are pruned to the newest 12. Jobs interrupted by a restart show as failed with a clear message. |
| Runner limits (MSH-001) | `runner.py` starts `blender -b --factory-startup --disable-autoexec --offline-mode -noaudio --python-exit-code 3 --python <job>/scene.py -- <job> <mesh.npz>` with a stripped environment (proxies pointed at a dead local port, no user site-packages), `cwd` = the job folder, and a wall-clock timeout that kills the process (preview 420 s, final 1200 s, turntable 3600 s, export 300 s). Output guard: the job folder must lie inside `<ws>/mesh/`; the scene script refuses any output path outside its job folder; after the run every new file is re-checked to resolve inside the job folder. |
| Scene scripts | `blender_scene.py` is a static template; `scene.build_script(spec)` inlines the job's spec (preset values, computed camera/light matrices, relative file names) as JSON. Same build + same presets → **byte-identical script** (tested), with no machine paths in it. The job folder keeps `spec.json`, `scene.py` and the Blender log for reproducibility. |
| Outputs (MSH-007) | Final: `render.png` (labelled in PNG text chunks: "Visualisation only…", finish, mesh tolerance), `thumb.jpg`, `scene.blend` (self-contained: mesh, materials, lights, camera; the turntable `.blend` keeps its animation). Turntable: `turntable.gif`, `turntable.mp4`, the PNG frames. Exports: `part.glb` (glTF 2.0, metres, Y up, flat PBR colour of the finish), `part_obj.zip` (OBJ + MTL, mm, Z up, disclosure comment), `part.stl` (binary, mm, Z up, header "Formwright Mesh Studio visualisation mesh, mm. Not the exact model."). |
| GPU vs CPU (MSH-012) | `runner.detect()` probes Blender once per binary: Cycles on the best GPU backend (OptiX > CUDA > HIP > Metal > oneAPI), else Cycles on the CPU with fewer samples and a capped thread count (half the cores, max 8, for a shared machine). `FW_MESH_DEVICE=CPU` forces CPU. EEVEE is not used: it needs a GPU context and has no shadow catcher, and Cycles CPU is the honest fallback. Here: **OptiX on an NVIDIA GeForce RTX 3070**. Measured times are below. |
| API | `routers/mod_mesh.py` (`/api/m/mesh`): `GET /presets`, `GET /projects/{id}` (project, suggested finish, mesh stats + checks, gallery), `GET /projects/{id}/jobs`, `POST /projects/{id}/renders`, `POST /projects/{id}/exports`, `GET|DELETE /projects/{id}/jobs/{job}`, `GET /projects/{id}/jobs/{job}/files/{name}` (`?dl=1` to download; names on an allow-list). Org-scoped (404 across workspaces), 402 when locked (`addon_mesh` / plan / God-mode bypass), 409 without a verified build, 503 when Blender is missing, 429 when the queue is full. Viewers can browse and download; rendering and exporting need the engineer role. |
| Frontend | `web/src/pages/app/modules/mesh/` (`index.tsx`, `LookPanel.tsx`, `Gallery.tsx`, `types.ts`). Project picker (verified projects, ISO thumbnails, material). Workspace: left **Look** panel (finish grid with metal/plastic swatches and colour chips, lighting tiles, camera / frame / pose segments, transparent and soften-edges toggles), centre **stage** with the live preview, progress, the visualisation label and the device line ("Cycles GPU (RTX 3070) · 24 samples · 7.9 s"), and **Render final · 1920 × 1440** / **Turntable** actions; right tabs **Gallery** (thumbnails, progress for queued/running jobs, downloads PNG / .blend / GIF / MP4, delete or cancel, lightbox), **Exports** (GLB / OBJ / STL per finish) and **Mesh** (checks with the disclosure). `?project=<id>` opens a project directly. |
| Catalog | `mesh` is `"live"` with an honest summary ("For presentation, not engineering geometry") and bullets that describe only what ships. |

## Files

- New: `src/aicad/meshstudio/{__init__,presets,framing,geometry,scene,runner,jobs,post,service,blender_scene,blender_encode}.py`,
  `src/aicad/platform/routers/mod_mesh.py`, `tests/test_mesh.py`, `web/src/pages/app/modules/mesh/*`, this report.
- Shared file touched (as allowed): `src/aicad/platform/catalog.py` (the `mesh` entry only).
- No new Python or npm dependencies (Pillow, numpy and scipy were already in the lock file).

## Licences (LEG-004: Blender is GPL)

| Component | Licence | How it is used |
|---|---|---|
| Blender 5.3 | GPL-2.0-or-later (binary distributions effectively GPL-3.0) | **Separate program**, installed independently on the server (not bundled, not shipped, not modified). Formwright starts the `blender` executable as a child process with command-line arguments and exchanges only files (a numpy array in, PNG / .blend / GLB / OBJ / STL out). No Formwright module imports `bpy`, links Blender libraries or loads Blender into our process. |
| `blender_scene.py`, `blender_encode.py` | (ours) | The two scripts that run *inside* Blender and import `bpy`. Kept in two isolated files that contain no proprietary logic (the presets and framing are computed outside Blender and passed as data). Blender's own guidance treats `bpy` scripts/add-ons as subject to the GPL when they are distributed; we run them only on our own servers and do not distribute them, and GPL obligations attach to distribution (Blender is not AGPL). See PD-MSH-1. |
| Blender output (renders, `.blend` files) | Not covered by the GPL | Blender's licence FAQ: the output of the program (images, .blend data) belongs to the user. |
| FFmpeg (inside Blender) | LGPL/GPL, part of the Blender binary | Used only through Blender's own video output; we never call or ship it. |
| Pillow | HPND (permissive) | Background composite, PNG text labels, thumbnails, GIF. Already a dependency. |

Reasoning in short: the FSF's GPL FAQ treats programs that communicate through command-line arguments, pipes and
files as separate works ("mere aggregation"), so the GPL does not extend to Formwright's code. The open question for
counsel is only the status of the two `bpy` scripts, and what changes if we ever ship Blender to customers (on-prem
or desktop builds would then have to pass on Blender's source and licence).

## Tests

`tests/test_mesh.py`: **76 tests, all pass in about 53 s** (real Blender on this machine).

- Material mapping: 36 material strings → (finish, colour), plus every library material maps to a real finish.
- sRGB → linear against the IEC 61966-2-1 transfer function (#808080 → 0.21586; knee segment).
- Framing by hand: front ortho of a 100 × 50 × 20 mm box gives `ortho_scale` = 0.100 / 0.78 and the part spans
  11–89% of the width, centred; every camera preset × 4 aspects fits, centres and is tight on one axis; turntable
  framing holds at 36 angles.
- Lights: power ∝ diagonal² (×4 when the part doubles), distance = rig distance × diagonal, aimed at the target.
- Auto pose; visualisation mesh of the demo flange is watertight/manifold/outward, deviation within tolerance,
  volume equals the hand calculation (OD150×16 + RF100×2 − bore 60.3×18 − 6 × Ø14×16), flat faces get exact normals.
- Scene script determinism (byte-identical; changes with presets; no machine paths; CPU vs GPU sample counts).
- Runner: path guard refuses escapes; the command line is headless/offline/factory-clean; **timeout kills Blender**
  (4 s limit on a 120 s sleep); **a spec writing `../escape.png` is refused** and nothing is written outside.
- End to end (tiny 96 × 72, 4 samples): the transparent PNG's opaque pixels cover the hand-projected bbox of the part
  within 0.05 of the frame; second request is served from cache; opaque RGB with a background; final + `.blend`;
  6-frame turntable GIF + MP4; GLB / OBJ / STL exports where the STL reloads (printprep parser) to 40 × 20 × 10 mm and
  8000 mm³.
- Queue caps per workspace, previews jump the queue, cancel.
- API: 401 / 402 / 409 / 422 / 404 across workspaces, render → poll → PNG download, file allow-list and traversal.
- Catalog is live with honest copy.

## Walkthrough (port 8778, scratch data dir, God-mode demo seed)

WALKTHROUGH

## Known limits

- Rendering needs Blender installed on the server (5.x; path auto-detected or `FW_BLENDER`). Without it the module
  says so (503 / "Rendering isn't available on this server"). Production hosting needs a GPU box or accepts slow
  CPU renders (see MSH-012 numbers).
- One render at a time by default; a busy queue shows its position. No token charge for renders yet (PD-MSH-2).
- The first GPU render after installing or upgrading Blender compiles OptiX kernels (about 3 minutes here); the
  preview timeout (420 s) covers it.
- Finishes are look-development recipes, not measured BRDFs of real alloys or coatings. Colours are presentation
  colours, not RAL/Pantone matches.
- One material per part (no per-face finishes, no decals, logos or engraving); no depth-of-field or custom HDRI.
- Assemblies are rendered as one body (whatever the verified STEP contains).
- GLB carries the finish as a flat PBR colour; procedural detail (grain, anisotropy) exists only in renders and
  the `.blend`.
- Not built from the old MSH backlog: text/image → scene (MSH-002/003), render-critique loop (MSH-005/006),
  generative benchmark (MSH-010/011). These are not claimed on the Live card.

## Punch-list rows

| ID | Status | Evidence |
|---|---|---|
| MSH-001 | Done | `runner.py` (separate offline process, timeout kill, output guard), tests `test_runner_enforces_its_timeout`, `test_scene_script_refuses_outputs_outside_its_job_folder`, `test_guard_inside_refuses_escapes`, `test_command_line_is_headless_offline_and_factory_clean`. OS-level sandboxing (no network namespace on Windows) not done: see limits / PD-MSH-3. |
| MSH-004 | Done (for product renders) | 14 finishes, 3 lighting rigs, 5 cameras, 4 aspects, pose, transparent, edge softening; framing tests; walkthrough images. Modifiers beyond shading bevel not exposed. |
| MSH-007 | Done | PNG, `.blend`, GIF, MP4, GLB, OBJ (+MTL), STL; `test_final_turntable_and_exports_produce_their_files`. FBX not offered (Blender's FBX exporter works, but GLB covers the use; can be added). |
| MSH-008 | Done | MS-01..08 via `aicad.printprep` functions; `test_visualisation_mesh_is_watertight_and_close_to_the_exact_model`. |
| MSH-009 | Done | Disclosure in UI (stage footer, lightbox, Mesh tab), PNG text chunks, STL header, OBJ comment, GLB extras, export README; catalog summary. |
| MSH-012 | Done (local measurement) | Device detection + measured GPU/CPU times below; cloud cost comparison not done (no cloud account). |

## Parked decisions

PARKED
