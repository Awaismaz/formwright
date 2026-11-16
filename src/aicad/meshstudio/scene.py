"""Scene spec + script generation. Same options and geometry -> byte-identical script (deterministic, testable).

The spec holds only preset values, computed camera/light matrices and file names relative to the job folder; the
geometry path and job folder are passed on Blender's command line, so the script carries no machine paths.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from aicad.meshstudio import VERSION, framing, presets

TEMPLATE = Path(__file__).with_name("blender_scene.py")
MARK = "SPEC = {}  # @@SPEC@@"
# Highlight protection (AMI-12): Khronos PBR Neutral starts compressing towards white at 0.76 (0.8 minus its 0.04
# Fresnel offset). A part pixel whose *minimum* linear channel reaches that shoulder comes out near white with no
# colour or detail. At most 2 % of the part may sit there; otherwise exposure is lowered just enough (at most 4 EV).
AUTO_EXPOSURE = {"shoulder": 0.76, "max_fraction": 0.02, "min_ev": -4.0}


@dataclass(frozen=True)
class Options:
    finish: str = "clay"
    colour: str | None = None
    lighting: str = "studio"
    camera: str = "hero"
    quality: str = "preview"          # preview | final | turntable | turntable_draft
    aspect: str = "4:3"
    transparent: bool = False
    pose: str = "auto"                # auto | as_modelled
    soften_edges: bool = True

    def validate(self) -> Options:
        if self.finish not in presets.FINISHES:
            raise ValueError(f"Unknown finish: {self.finish}")
        table = presets.FINISHES[self.finish].get("colours")
        if self.colour is not None and (not table or self.colour not in table):
            raise ValueError(f"Colour {self.colour} isn't offered for {presets.FINISHES[self.finish]['label']}")
        for val, table_, what in ((self.lighting, presets.LIGHTING, "lighting"), (self.camera, presets.CAMERAS, "camera"),
                                  (self.quality, presets.QUALITY, "quality"), (self.aspect, presets.ASPECTS, "aspect"),
                                  (self.pose, presets.POSES, "pose")):
            if val not in table_:
                raise ValueError(f"Unknown {what}: {val}")
        return self

    def key(self) -> dict[str, Any]:
        d = asdict(self)
        if d["colour"] is None:
            d["colour"] = presets.FINISHES[self.finish].get("default_colour")
        return d


def pose_matrix(bbox_mm: list[float], pose: str) -> np.ndarray:
    """Rotation for the render pose. 'auto' lays a tall slender part (height > 1.6 x footprint) on its side with
    its long axis along X, as a product photographer would; otherwise the part stays as modelled (Z up)."""
    x, y, z = bbox_mm
    if pose == "auto" and z > 1.6 * max(x, y):
        return np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]])  # +90 deg about Y: Z -> X
    return np.eye(3)


def _hex_lin(h: str) -> list[float]:
    return presets.srgb_to_linear(h)


def device_block(device: dict[str, Any], quality: str) -> dict[str, Any]:
    q = presets.QUALITY[quality]
    gpu = device.get("device") == "GPU" and device.get("backend")
    threads = max(1, min(8, (int(__import__("os").cpu_count() or 4) // 2)))
    return {"device": "GPU" if gpu else "CPU", "backend": device.get("backend") if gpu else None,
            "samples": q["samples_gpu"] if gpu else q["samples_cpu"], "threads": threads,
            "noise_threshold": 0.02 if quality == "preview" else 0.01, "bounces": q["bounces"]}


def build_spec(geom: dict[str, Any], hull_mm: np.ndarray, opts: Options, device: dict[str, Any], name: str,
               outputs: dict[str, Any]) -> dict[str, Any]:
    """The full scene description. `hull_mm`: convex-hull vertices of the part in model coordinates (mm)."""
    opts.validate()
    rot = pose_matrix(geom["bbox_mm"], opts.pose)
    pts = (np.asarray(hull_mm, float) @ rot.T) * 0.001
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    shift = np.array([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])  # centred, resting on the floor z = 0
    pts = pts + shift
    diag = float(np.linalg.norm(hi - lo)) or 1e-3
    q = presets.QUALITY[opts.quality]
    aw, ah = presets.ASPECTS[opts.aspect]
    long_side = q["res"][0]
    res = [long_side, round(long_side * ah / aw)] if aw >= ah else [round(long_side * aw / ah), long_side]
    res = [int(r) - int(r) % 2 for r in res]
    cam = presets.CAMERAS[opts.camera]
    turn = presets.is_turntable(opts.quality)
    frame_pts = framing.turntable_points(pts, np.zeros(2)) if turn else pts
    camera = framing.frame_camera(frame_pts, cam, (aw, ah))
    light = presets.LIGHTING[opts.lighting]
    centre = (pts.min(axis=0) + pts.max(axis=0)) / 2
    lights = framing.place_lights(light["lights"], centre, diag, cam["az"])
    m = np.eye(4)
    m[:3, :3] = rot
    m[:3, 3] = shift
    mat = presets.resolve_finish(opts.finish, opts.colour)
    mat["label"] = presets.FINISHES[opts.finish]["label"]
    rend = device_block(device, opts.quality)
    rend.update(res=res, view="Khronos PBR Neutral", look="None", exposure=light["exposure"],
                auto_exposure=AUTO_EXPOSURE)
    spec = {
        "version": VERSION, "mode": "turntable" if turn else "render",
        "object": {"name": name[:60] or "Part", "matrix": [[round(float(x), 7) for x in row] for row in m]},
        "pivot": [0.0, 0.0, 0.0],
        "material": mat,
        "bevel_m": round(min(0.0008, max(0.00008, diag * 0.0022)), 6) if opts.soften_edges else 0.0,
        "scale": {"rough_noise": round(1.0 / (diag * 0.25), 4)},
        "lighting": {"world": {k: _hex_lin(light["world"][k]) for k in ("top", "horizon", "bottom")}
                     | {"strength": light["world"]["strength"]}, "lights": lights},
        "floor": {"z": 0.0, "size": round(diag * 40, 5), "albedo": [light.get("floor", 0.3)] * 3},
        "camera": camera, "render": rend,
        "turntable": {"frames": q["frames"], "fps": q["fps"]} if turn else None,
        "outputs": outputs,
        "post": {"background": None if opts.transparent else light["background"], "shadow": light["shadow"],
                 "aspect": [aw, ah]},
    }
    return spec


def export_spec(name: str, finish: str, colour: str | None, outputs: dict[str, Any]) -> dict[str, Any]:
    mat = presets.resolve_finish(finish, colour)
    mat["label"] = presets.FINISHES[finish]["label"]
    return {"version": VERSION, "mode": "export", "object": {"name": name[:60] or "Part", "matrix": None},
            "material": mat, "bevel_m": 0.0, "scale": {"rough_noise": 1.0}, "outputs": outputs}


def build_script(spec: dict[str, Any]) -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    if MARK not in text:
        raise RuntimeError("scene template marker missing")
    return text.replace(MARK, "SPEC = json.loads(r'''" + json.dumps(spec, sort_keys=True) + "''')", 1)


def spec_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def fov_note(camera: dict[str, Any]) -> str:
    if camera["type"] == "ORTHO":
        return "orthographic"
    return f"{camera['lens']:.0f} mm lens ({math.degrees(2 * math.atan(18 / camera['lens'])):.0f} deg)"
