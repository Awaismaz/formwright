"""Mesh Studio: material mapping, deterministic scene scripts, framing, the Blender runner's limits, tiny end-to-end
renders/exports of a demo part, and the API (auth, scoping, 402).

Hand calculations: framing of an orthographic front view of a 100 x 50 x 20 mm box, sRGB -> linear conversion
(IEC 61966-2-1 transfer function), light power scaling with part size, the flange volume from its dimensions.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
import pytest
from build123d import Box, export_step
from fastapi.testclient import TestClient
from PIL import Image
from test_platform import admin, app_client, signup  # noqa: F401  (fixture re-export)
from trial_helpers import set_trial_ended

from aicad.meshstudio import (
    DISCLOSURE,
    framing,
    geometry,
    jobs,
    post,
    presets,
    runner,
    scene,
    service,
)

DEMO = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo"
BLENDER = runner.find_blender()
needs_blender = pytest.mark.skipif(BLENDER is None, reason="Blender is not installed on this machine "
                                   "(set FW_BLENDER to its executable to run the render tests)")


def _demo_step(name: str, tmp: Path) -> Path:
    ns: dict = {}
    src = DEMO / f"{name}.py"
    exec(compile(src.read_text(encoding="utf-8"), str(src), "exec"), ns)  # noqa: S102  (our own demo script)
    p = tmp / f"{name}.step"
    export_step(ns["result"], str(p))
    return p


def _tiny(monkeypatch: pytest.MonkeyPatch, frames: int = 6) -> None:
    """Shrink the quality presets so a render takes seconds (the pipeline is otherwise identical)."""
    monkeypatch.setitem(presets.QUALITY, "preview", {"label": "Preview", "res": (96, 72), "samples_gpu": 4,
                                                     "samples_cpu": 2, "bounces": 2})
    monkeypatch.setitem(presets.QUALITY, "final", {"label": "Final", "res": (128, 96), "samples_gpu": 4,
                                                   "samples_cpu": 2, "bounces": 2})
    monkeypatch.setitem(presets.QUALITY, "turntable", {"label": "Turntable", "res": (64, 48), "samples_gpu": 2,
                                                       "samples_cpu": 1, "bounces": 2, "frames": frames, "fps": 12})


def _wait(get, timeout: float = 240.0) -> dict:
    t0 = time.monotonic()
    while True:
        v = get()
        if v["state"] in ("done", "failed"):
            return v
        assert time.monotonic() - t0 < timeout, f"job stuck: {v}"
        time.sleep(0.3)


# ------------------------------------------------------------------ material mapping
@pytest.mark.parametrize("text,finish,colour", [
    ("Aluminium 6061-T6", "anodised", "clear"),
    ("6061-T6 aluminium, black anodised", "anodised", "black"),
    ("Al 7075, hard anodise (type III), grey", "anodised", "grey"),
    ("Aluminum 6082 anodized red", "anodised", "red"),
    ("AL 5052 blue anodised", "anodised", "blue"),
    ("6061 bead blasted", "bead_blasted", None),
    ("Aluminium, bead-blast + clear anodise", "bead_blasted", None),
    ("Brushed aluminium 5083", "brushed_aluminium", None),
    ("Carbon steel", "machined_steel", None),
    ("Steel 1045 (medium carbon)", "machined_steel", None),
    ("EN8 steel", "machined_steel", None),
    ("4140 alloy steel, black oxide", "black_oxide", None),
    ("Steel, blackened", "black_oxide", None),
    ("Stainless 304", "stainless_brushed", None),
    ("316 stainless steel", "stainless_brushed", None),
    ("Stainless 17-4 PH", "stainless_brushed", None),
    ("Brass C360", "brass", None),
    ("Bearing bronze C932", "brass", None),
    ("Copper C110", "copper", None),
    ("Titanium Ti-6Al-4V", "titanium", None),
    ("ABS", "abs", "black"),
    ("ABS, white", "abs", "white"),
    ("PLA (solid)", "pla", "white"),
    ("PLA red", "pla", "red"),
    ("PETG orange", "abs", "orange"),
    ("Nylon PA12 (SLS)", "abs", "white"),
    ("Acetal POM (Delrin), black", "abs", "black"),
    ("Polycarbonate", "abs", "black"),
    ("EPDM rubber", "rubber", "black"),
    ("Silicone, grey", "rubber", "grey"),
    ("TPU 95A", "rubber", "black"),
    ("Grey cast iron", "machined_steel", None),
    ("unspecified", "clay", None),
    ("", "clay", None),
    (None, "clay", None),
    ("Unobtainium", "clay", None),
])
def test_material_text_maps_to_a_finish(text: str | None, finish: str, colour: str | None) -> None:
    m = presets.map_material(text)
    assert (m["finish"], m["colour"]) == (finish, colour), text


def test_every_platform_material_maps_to_a_real_finish() -> None:
    from aicad.materials import MATERIALS

    for mat in MATERIALS:
        m = presets.map_material(str(mat["name"]))
        assert m["finish"] in presets.FINISHES and m["finish"] != "clay", mat["name"]
        presets.resolve_finish(m["finish"], m["colour"])  # resolvable


def test_srgb_to_linear_matches_the_standard_transfer_function() -> None:
    assert presets.srgb_to_linear("#ffffff") == [1.0, 1.0, 1.0]
    assert presets.srgb_to_linear("#000000") == [0.0, 0.0, 0.0]
    # 128/255 = 0.50196 -> ((0.50196 + 0.055) / 1.055) ** 2.4 = 0.21586
    assert presets.srgb_to_linear("#808080")[0] == pytest.approx(0.21586, abs=1e-4)
    # below the linear-segment knee: 10/255 / 12.92 = 0.0030353
    assert presets.srgb_to_linear("#0a0a0a")[0] == pytest.approx(0.0030353, abs=1e-5)  # stored to 5 decimals


def test_resolve_finish_rejects_unknown_and_defaults_colour() -> None:
    a = presets.resolve_finish("anodised", None)
    assert a["colour"] == "clear" and a["metallic"] == 1.0 and len(a["base"]) == 3
    assert presets.resolve_finish("anodised", "nope")["colour"] == "clear"
    with pytest.raises(ValueError):
        presets.resolve_finish("chrome-unicorn", None)
    with pytest.raises(ValueError):
        scene.Options(finish="machined_steel", colour="red").validate()  # steel has no colour table


# ------------------------------------------------------------------ framing and lights (hand calculations)
def _box_points(x: float, y: float, z: float) -> np.ndarray:
    return np.array([[a, b, c] for a in (0, x) for b in (0, y) for c in (0, z)], dtype=float)


def test_front_ortho_framing_of_a_box_matches_hand_calculation() -> None:
    pts = _box_points(0.100, 0.050, 0.020)
    cam = framing.frame_camera(pts, presets.CAMERAS["front"], (4, 3))
    # frame is 1.0 wide x 0.75 high (fractions of the larger side); fill 0.78:
    # scale = max(0.100 / 0.78, 0.020 / (0.78 * 0.75)) = 0.128205 m
    assert cam["type"] == "ORTHO" and cam["ortho_scale"] == pytest.approx(0.100 / 0.78, rel=1e-6)
    uv = framing.project(pts, cam, (4, 3))
    assert uv[:, 0].min() == pytest.approx(0.11, abs=1e-6) and uv[:, 0].max() == pytest.approx(0.89, abs=1e-6)
    assert (uv[:, 1].min() + uv[:, 1].max()) / 2 == pytest.approx(0.5, abs=1e-6)  # centred vertically


@pytest.mark.parametrize("view", list(presets.CAMERAS))
@pytest.mark.parametrize("aspect", [(4, 3), (16, 9), (1, 1), (3, 4)])
def test_every_camera_preset_fits_and_centres_the_part(view: str, aspect: tuple[int, int]) -> None:
    pts = _box_points(0.15, 0.15, 0.018)
    cam = presets.CAMERAS[view]
    c = framing.frame_camera(pts, cam, aspect)
    uv = framing.project(pts, c, aspect)
    lo, hi = uv.min(axis=0), uv.max(axis=0)
    assert lo.min() >= -1e-6 and hi.max() <= 1 + 1e-6
    assert np.allclose((lo + hi) / 2, 0.5, atol=1e-4)
    assert max(hi[0] - lo[0], hi[1] - lo[1]) == pytest.approx(cam["fill"], abs=2e-3)  # tight on one axis


def test_turntable_framing_holds_over_a_full_turn() -> None:
    pts = _box_points(0.2, 0.04, 0.03) - [0.1, 0.02, 0]
    sweep = framing.turntable_points(pts, np.zeros(2))
    c = framing.frame_camera(sweep, presets.CAMERAS["hero"], (4, 3))
    for k in range(36):
        a = 2 * math.pi * k / 36
        r = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
        uv = framing.project(pts @ r.T, c, (4, 3))
        assert uv.min() >= -0.01 and uv.max() <= 1.01


def test_light_power_scales_with_part_size_squared() -> None:
    rig = presets.LIGHTING["studio"]["lights"]
    a = framing.place_lights(rig, np.zeros(3), 0.25, 35.0)
    b = framing.place_lights(rig, np.zeros(3), 0.50, 35.0)
    for la, lb, spec in zip(a, b, rig, strict=True):
        assert la["power"] == pytest.approx(spec["power"], rel=1e-4)
        assert lb["power"] == pytest.approx(4 * spec["power"], rel=1e-4)
        loc = np.asarray(la["matrix"])[:3, 3]
        assert np.linalg.norm(loc) == pytest.approx(spec["dist"] * 0.25, rel=1e-5)
        back = np.asarray(la["matrix"])[:3, 2]  # light emits along -Z: towards the target
        assert np.allclose(back, loc / np.linalg.norm(loc), atol=1e-6)


def test_auto_pose_lays_long_parts_down() -> None:
    assert np.allclose(scene.pose_matrix([20, 20, 150], "auto") @ [0, 0, 1], [1, 0, 0])
    assert np.allclose(scene.pose_matrix([150, 150, 18], "auto"), np.eye(3))
    assert np.allclose(scene.pose_matrix([20, 20, 150], "as_modelled"), np.eye(3))


# ------------------------------------------------------------------ geometry + scene script
@pytest.fixture(scope="module")
def flange(tmp_path_factory: pytest.TempPathFactory) -> dict:
    tmp = tmp_path_factory.mktemp("flange")
    step = _demo_step("pipe_flange", tmp)
    geom = geometry.build_geometry(step, tmp / "geom")
    npz = tmp / "geom" / geom["file"]
    return {"tmp": tmp, "step": step, "geom": geom, "npz": npz,
            "hull": geometry.hull_points(npz, np.eye(3), np.zeros(3)) * 1000}


def test_visualisation_mesh_is_watertight_and_close_to_the_exact_model(flange: dict) -> None:
    g = flange["geom"]
    checks = {c["id"]: c for c in g["checks"]}
    for cid in ("MS-01", "MS-02", "MS-03", "MS-05", "MS-06", "MS-07"):
        assert checks[cid]["status"] == "pass", checks[cid]
    assert checks["MS-08"]["status"] == "info"
    # flange volume by hand: OD150 x 16 + RF100 x 2 - bore 60.3 x 18 - 6 x bolt 14 x 16
    v = (math.pi * 75 ** 2 * 16 + math.pi * 50 ** 2 * 2 - math.pi * (60.3 / 2) ** 2 * 18
         - 6 * math.pi * 7 ** 2 * 16)
    assert g["volume_mm3"] == pytest.approx(v, rel=1e-6)
    assert g["bbox_mm"] == pytest.approx([150, 150, 18], abs=g["tolerance_mm"])  # inscribed polygon: within tol
    d = np.load(flange["npz"])
    n = d["n"].reshape(-1, 3)
    assert np.allclose(np.linalg.norm(n, axis=1), 1, atol=1e-4) and len(n) == 3 * g["triangles"]
    # split normals: on the flat back face (z = 0) every corner normal is exactly -Z
    v_m, f = d["v"], d["f"]
    back = np.all(np.abs(v_m[f][:, :, 2]) < 1e-9, axis=1)
    assert back.any() and np.allclose(d["n"].reshape(-1, 3, 3)[back], [0, 0, -1], atol=1e-5)


def test_scene_script_is_deterministic_and_carries_no_paths(flange: dict) -> None:
    dev = {"available": True, "device": "GPU", "backend": "OPTIX"}
    o = scene.Options(finish="anodised", colour="blue", lighting="dark", camera="iso", quality="final")
    outs = {"image": "raw.png", "blend": "scene.blend"}
    s1 = scene.build_script(scene.build_spec(flange["geom"], flange["hull"], o, dev, "Flange", outs))
    s2 = scene.build_script(scene.build_spec(flange["geom"], flange["hull"].copy(), o, dev, "Flange", outs))
    assert s1 == s2
    o2 = scene.Options(finish="anodised", colour="red", lighting="dark", camera="iso", quality="final")
    s3 = scene.build_script(scene.build_spec(flange["geom"], flange["hull"], o2, dev, "Flange", outs))
    assert s3 != s1
    line = next(ln for ln in s1.splitlines() if ln.startswith("SPEC = json.loads"))
    spec = json.loads(line[len("SPEC = json.loads(r'''"):-len("''')")])
    assert spec["material"]["id"] == "anodised" and spec["material"]["colour"] == "blue"
    assert spec["material"]["base"] == presets.srgb_to_linear(presets.ANODISE_COLOURS["blue"][1])
    assert spec["render"]["samples"] == presets.QUALITY["final"]["samples_gpu"]
    assert spec["camera"]["type"] == "ORTHO" and len(spec["lighting"]["lights"]) == 4
    assert ":\\" not in s1 and str(flange["tmp"]) not in s1  # no machine paths in the script
    cpu = scene.build_spec(flange["geom"], flange["hull"], o, {"available": True, "device": "CPU"}, "F", outs)
    assert cpu["render"]["device"] == "CPU" and cpu["render"]["samples"] == presets.QUALITY["final"]["samples_cpu"]


# ------------------------------------------------------------------ runner limits
def test_guard_inside_refuses_escapes(tmp_path: Path) -> None:
    root = tmp_path / "mesh"
    (root / "job").mkdir(parents=True)
    assert runner.guard_inside(root / "job" / "a.png", root) == (root / "job" / "a.png").resolve()
    for bad in (root / ".." / "x.png", tmp_path / "other" / "a.png", root.parent):
        with pytest.raises(ValueError):
            runner.guard_inside(bad, root)
    script = tmp_path / "s.py"
    script.write_text("pass")
    with pytest.raises(ValueError):  # job folder outside the allowed root: refused before Blender starts
        runner.run(script, tmp_path / "elsewhere", root, [], 5)
    with pytest.raises(ValueError):  # script outside the job folder
        runner.run(script, root / "job", root, [], 5)


def test_command_line_is_headless_offline_and_factory_clean() -> None:
    cmd = runner.command(Path("blender"), Path("s.py"), ["a"])
    for flag in ("-b", "--factory-startup", "--disable-autoexec", "--offline-mode", "--python-exit-code"):
        assert flag in cmd
    assert cmd[-2:] == ["--", "a"]
    env = runner._env()
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:9") and "PYTHONPATH" not in env


@needs_blender
def test_runner_enforces_its_timeout(tmp_path: Path) -> None:
    root = tmp_path / "mesh"
    job = root / "j"
    job.mkdir(parents=True)
    (job / "s.py").write_text("import time\ntime.sleep(120)\n")
    t0 = time.monotonic()
    with pytest.raises(runner.BlenderTimeout):
        runner.run(job / "s.py", job, root, [], 4.0)
    assert time.monotonic() - t0 < 40


@needs_blender
def test_scene_script_refuses_outputs_outside_its_job_folder(flange: dict, tmp_path: Path) -> None:
    root = tmp_path / "mesh"
    job = root / "j"
    job.mkdir(parents=True)
    dev = runner.detect()
    spec = scene.build_spec(flange["geom"], flange["hull"], scene.Options(finish="clay"), dev, "F",
                            {"image": "../escape.png"})
    (job / "scene.py").write_text(scene.build_script(spec), encoding="utf-8")
    with pytest.raises(runner.BlenderError, match="output path refused"):
        runner.run(job / "scene.py", job, root, [str(job), str(flange["npz"])], 120)
    assert not (root / "escape.png").exists()


def test_detect_reports_a_device() -> None:
    d = runner.detect()
    if BLENDER is None:
        assert d["available"] is False
    else:
        assert d["available"] and d["device"] in ("GPU", "CPU") and d["engine"] == "Cycles"


# ------------------------------------------------------------------ end to end (tiny renders)
def _ws(tmp: Path, step: Path, material: str = "Aluminium 6061-T6") -> Path:
    ws = tmp / "ws"
    (ws / "out").mkdir(parents=True)
    (ws / "out" / "part.step").write_bytes(step.read_bytes())
    (ws / "out" / "status.json").write_text(json.dumps({"ok": True, "build_id": 7, "material": material}))
    return ws


@needs_blender
def test_tiny_render_covers_the_parts_projected_bbox(flange: dict, tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    _tiny(monkeypatch)
    ws = _ws(tmp_path, flange["step"])
    o = scene.Options(finish="anodised", colour="clear", lighting="technical", camera="iso", transparent=True)
    v = service.request_render(ws, "Flange", o, "org1", "u1")
    v = _wait(lambda: service.job_view(ws, v["id"], ""))
    assert v["state"] == "done", v
    png = service.file_path(ws, v["id"], "render.png")
    im = Image.open(png)
    assert im.size == (96, 72) and im.mode == "RGBA" and png.stat().st_size > 1000
    assert DISCLOSURE in im.text["Description"]
    mask = np.asarray(im)[..., 3] >= 250  # the part is opaque; the caught shadow is partly transparent
    ys, xs = np.nonzero(mask)
    got = np.array([xs.min() / 96, ys.min() / 72, (xs.max() + 1) / 96, (ys.max() + 1) / 72])
    spec = json.loads((png.parent / "spec.json").read_text())
    pose = np.asarray(spec["object"]["matrix"])
    pts = (flange["hull"] * 0.001) @ pose[:3, :3].T + pose[:3, 3]
    uv = framing.project(pts, spec["camera"], (4, 3))
    want = np.array([uv[:, 0].min(), uv[:, 1].min(), uv[:, 0].max(), uv[:, 1].max()])
    assert np.abs(got - want).max() < 0.05, (got, want)  # within ~4 px of the hand-projected box
    # cached: same build + presets returns the finished job without rendering again
    again = service.request_render(ws, "Flange", o, "org1", "u1")
    assert again["cached"] and again["id"] == v["id"]
    # with a background the PNG is opaque RGB
    o2 = scene.Options(finish="machined_steel", lighting="studio", camera="hero")
    v2 = _wait(lambda: service.job_view(ws, service.request_render(ws, "F", o2, "org1", "u1")["id"], ""))
    assert v2["state"] == "done" and Image.open(service.file_path(ws, v2["id"], "render.png")).mode == "RGB"
    assert v2["device"]["engine"] == "Cycles" and v2["render_seconds"] > 0


@needs_blender
def test_final_turntable_and_exports_produce_their_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _tiny(monkeypatch, frames=6)
    step = tmp_path / "box.step"
    export_step(Box(40, 20, 10), str(step))
    ws = _ws(tmp_path, step, "ABS black")
    fin = service.request_render(ws, "Box", scene.Options(finish="abs", quality="final"), "o", "u")
    fin = _wait(lambda: service.job_view(ws, fin["id"], ""))
    assert fin["state"] == "done" and {"render.png", "thumb.jpg", "scene.blend"} <= set(fin["files"])
    assert service.file_path(ws, fin["id"], "scene.blend").read_bytes()[:4] in (b"BLEN", b"\x28\xb5\x2f\xfd")
    tt = service.request_render(ws, "Box", scene.Options(finish="abs", quality="turntable"), "o", "u")
    tt = _wait(lambda: service.job_view(ws, tt["id"], ""))
    assert tt["state"] == "done", tt
    gif = Image.open(service.file_path(ws, tt["id"], "turntable.gif"))
    assert gif.n_frames == 6
    assert "turntable.mp4" in tt["files"] and tt["files"]["turntable.mp4"]["bytes"] > 500
    ex = service.request_export(ws, "Box", "abs", "red", "o", "u")
    ex = _wait(lambda: service.job_view(ws, ex["id"], ""))
    assert ex["state"] == "done" and {"part.glb", "part_obj.zip", "part.stl"} <= set(ex["files"])
    from aicad.printprep.mesh import parse_mesh, signed_volume

    stl = service.file_path(ws, ex["id"], "part.stl").read_bytes()
    assert stl[:22] == b"Formwright Mesh Studio"
    m = parse_mesh(stl, "part.stl", "mm")
    assert signed_volume(m.v, m.f) == pytest.approx(40 * 20 * 10, rel=1e-4)  # mm, model coordinates
    assert np.allclose(m.v.max(axis=0) - m.v.min(axis=0), [40, 20, 10], atol=1e-3)
    assert service.file_path(ws, ex["id"], "part.glb").read_bytes()[:4] == b"glTF"
    listing = service.list_jobs(ws, "")
    assert {j["id"] for j in listing["renders"]} == {fin["id"], tt["id"]} and listing["exports"][0]["id"] == ex["id"]
    assert service.delete_job(ws, fin["id"]) and service.job_view(ws, fin["id"], "") is None


def test_queue_caps_pending_jobs_per_workspace(tmp_path: Path) -> None:
    q = jobs.RenderQueue(workers=1)
    gate = __import__("threading").Event()

    def slow(d: Path, j: dict) -> None:
        gate.wait(10)

    try:
        for i in range(jobs.MAX_PENDING_PER_ORG):
            d = tmp_path / f"j{i}"
            d.mkdir()
            job = {"id": f"{i:016x}", "kind": "final", "org": "A", "state": "queued"}
            jobs.write_job(d, job)
            q.submit(d, job, slow)
        d = tmp_path / "x"
        d.mkdir()
        with pytest.raises(jobs.QueueFull):
            q.submit(d, {"id": "f" * 16, "kind": "preview", "org": "A"}, slow)
        q.submit(d, {"id": "e" * 16, "kind": "preview", "org": "B", "state": "queued"}, slow)  # other workspace ok
        assert q.position("e" * 16) == 1  # previews jump the queue
        assert q.cancel("e" * 16) and not q.is_live("e" * 16)
    finally:
        gate.set()


# ------------------------------------------------------------------ API
def _grant(c: TestClient) -> None:
    from aicad.platform.db import session_factory
    from aicad.platform.models import Entitlement

    me = c.get("/api/auth/me").json()
    db = session_factory()()
    db.add(Entitlement(org_id=me["org"]["id"], module="mesh", source="grant"))
    db.commit()
    db.close()


def test_api_auth_scoping_paywall_and_flow(app_client: TestClient, tmp_path: Path,  # noqa: F811
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    _tiny(monkeypatch)
    c = app_client
    assert c.get("/api/m/mesh/presets").status_code == 401
    signup(c, "mesh@x.com")
    pid = c.post("/api/projects", json={"name": "Flange"}).json()["id"]
    set_trial_ended("mesh@x.com")  # a running trial may use every live module: test the paywall after it
    r = c.get(f"/api/m/mesh/projects/{pid}")
    assert r.status_code == 402 and "Mesh Studio" in r.json()["detail"]["message"]
    set_trial_ended("mesh@x.com", False)
    _grant(c)
    pre = c.get("/api/m/mesh/presets").json()
    assert {f["id"] for f in pre["finishes"]} >= {"anodised", "machined_steel", "abs", "rubber"}
    assert pre["disclosure"] == DISCLOSURE and "renderer" in pre
    assert c.get(f"/api/m/mesh/projects/{pid}").status_code == 409  # no verified build yet
    from aicad.platform.db import session_factory
    from aicad.platform.models import Project
    from aicad.platform.routers.projects import workspace_for

    db = session_factory()()
    ws = workspace_for(db.get(Project, pid))
    db.close()
    (ws / "out").mkdir(parents=True, exist_ok=True)
    export_step(Box(30, 20, 10), str(ws / "out" / "part.step"))
    (ws / "out" / "status.json").write_text(json.dumps({"ok": True, "build_id": 1, "material": "Brass C360"}))
    info = c.get(f"/api/m/mesh/projects/{pid}").json()
    assert info["suggested"]["finish"] == "brass" and info["mesh"]["bbox_mm"] == pytest.approx([30, 20, 10])
    assert all(ch["status"] in ("pass", "info") for ch in info["mesh"]["checks"])
    assert c.post(f"/api/m/mesh/projects/{pid}/renders", json={"finish": "nope"}).status_code == 422
    assert c.post(f"/api/m/mesh/projects/{pid}/renders", json={"finish": "brass", "camera": "x"}).status_code == 422
    if BLENDER is not None:
        v = c.post(f"/api/m/mesh/projects/{pid}/renders", json={"finish": "brass", "quality": "preview"})
        assert v.status_code == 200, v.text
        jid = v.json()["id"]
        done = _wait(lambda: c.get(f"/api/m/mesh/projects/{pid}/jobs/{jid}").json())
        assert done["state"] == "done", done
        png = c.get(done["files"]["render.png"]["url"])
        assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
        dl = c.get(done["files"]["render.png"]["url"] + "?dl=1")
        assert "attachment" in dl.headers.get("content-disposition", "")
        assert c.get(f"/api/m/mesh/projects/{pid}/jobs/{jid}/files/spec.json").status_code == 404
        assert c.get(f"/api/m/mesh/projects/{pid}/jobs/{jid}/files/..%2F..%2Fout%2Fpart.step").status_code == 404
        assert c.get(f"/api/m/mesh/projects/{pid}/jobs").json()["previews"][0]["id"] == jid
    assert c.get(f"/api/m/mesh/projects/{pid}/jobs/zzz").status_code == 404
    # another workspace sees nothing
    c.post("/api/auth/logout")
    signup(c, "other-mesh@x.com", workspace="Other Co")
    _grant(c)
    assert c.get(f"/api/m/mesh/projects/{pid}").status_code == 404
    assert c.post(f"/api/m/mesh/projects/{pid}/renders", json={"finish": "brass"}).status_code == 404


def test_catalog_marks_mesh_live_with_honest_copy() -> None:
    from aicad.platform.catalog import MODULES

    m = MODULES["mesh"]
    assert m["status"] == "live"
    assert "not engineering geometry" in m["summary"].lower() or "presentation" in m["summary"].lower()
    assert all("Text" not in b and "critique" not in b for b in m["bullets"])  # no roadmap bullets


def test_disclosure_states_visualisation_only() -> None:
    assert "Visualisation only" in DISCLOSURE and "not the exact model" in DISCLOSURE
    assert post.coverage_bbox  # used by the walkthrough
