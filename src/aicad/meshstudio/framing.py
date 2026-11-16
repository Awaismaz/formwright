"""Camera and light placement, computed here (not in Blender) so framing is deterministic and unit-testable.

Conventions: Z up, metres. The front view looks along +Y (camera on -Y), like SOLIDWORKS' Front. A Blender camera
looks down its local -Z with +Y up, so its world matrix columns are (right, up, -forward, location).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

SENSOR_MM = 36.0


def view_dir(az_deg: float, el_deg: float) -> np.ndarray:
    """Unit vector from the target towards the camera."""
    az, el = math.radians(az_deg), math.radians(el_deg)
    return np.array([math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)])


def basis(az_deg: float, el_deg: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(right, up, back) where back points from the target to the camera."""
    back = view_dir(az_deg, el_deg)
    fwd = -back
    right = np.cross(fwd, [0.0, 0.0, 1.0])
    if np.linalg.norm(right) < 1e-9:  # looking straight down/up: keep screen-right = +X rotated by azimuth
        az = math.radians(az_deg)
        right = np.array([math.cos(az), math.sin(az), 0.0])
    right = right / np.linalg.norm(right)
    up = np.cross(right, fwd)
    return right, up / np.linalg.norm(up), back


def matrix(right: np.ndarray, up: np.ndarray, back: np.ndarray, loc: np.ndarray) -> list[list[float]]:
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = right, up, back, loc
    return [[round(float(x), 7) for x in row] for row in m]


def _frame_sizes(aspect: tuple[int, int]) -> tuple[float, float]:
    """Visible frame (width, height) as fractions of the larger sensor dimension (Blender sensor_fit AUTO)."""
    w, h = aspect
    return (1.0, h / w) if w >= h else (w / h, 1.0)


def turntable_points(points: np.ndarray, centre_xy: np.ndarray, steps: int = 24) -> np.ndarray:
    """The points swept around a vertical axis through `centre_xy` (for framing that holds over a full turn)."""
    out = []
    q = points.copy()
    q[:, :2] -= centre_xy
    for k in range(steps):
        a = 2 * math.pi * k / steps
        c, s = math.cos(a), math.sin(a)
        r = q.copy()
        r[:, 0], r[:, 1] = c * q[:, 0] - s * q[:, 1], s * q[:, 0] + c * q[:, 1]
        r[:, :2] += centre_xy
        out.append(r)
    return np.concatenate(out)


def frame_camera(points: np.ndarray, cam: dict[str, Any], aspect: tuple[int, int]) -> dict[str, Any]:
    """Place the camera so every point is inside `cam["fill"]` of the frame, centred, for a preset view.

    points: (n, 3) metres (hull vertices of the posed part). Returns the camera block of the scene spec.
    """
    pts = np.asarray(points, float)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    target = (lo + hi) / 2
    diag = float(np.linalg.norm(hi - lo)) or 1e-3
    right, up, back = basis(cam["az"], cam["el"])
    fw, fh = _frame_sizes(aspect)
    fill = float(cam["fill"])
    q = pts - target
    x, y, z = q @ right, q @ up, q @ back  # z: towards the camera
    if cam["ortho"]:
        xe, ye = float(x.max() - x.min()), float(y.max() - y.min())
        scale = max(xe / (fill * fw), ye / (fill * fh), 1e-6)
        cx, cy = float(x.max() + x.min()) / 2, float(y.max() + y.min()) / 2
        dist = 4.0 * diag
        loc = target + right * cx + up * cy + back * dist
        return {"type": "ORTHO", "ortho_scale": round(scale, 7), "lens": 50.0, "shift": [0.0, 0.0],
                "matrix": matrix(right, up, back, loc), "clip": [round(dist * 0.01, 6), round(dist * 4, 6)],
                "target": [round(float(t), 7) for t in target], "distance": round(dist, 6)}
    lens = float(cam["lens"])
    t = SENSOR_MM / 2 / lens  # tan(half fov) across the larger sensor dimension

    def extents(d: float) -> tuple[float, float, float, float]:
        depth = d - z
        u, v = x / depth / (2 * t), y / depth / (2 * t)
        return float(u.min()), float(u.max()), float(v.min()), float(v.max())

    near = float(z.max()) + 1e-6
    lo_d, hi_d = near, near + 1000 * diag
    for _ in range(80):  # extents shrink monotonically with distance: bisect for the tightest fit
        mid = (lo_d + hi_d) / 2
        u0, u1, v0, v1 = extents(mid)
        if u1 - u0 <= fill * fw and v1 - v0 <= fill * fh:
            hi_d = mid
        else:
            lo_d = mid
    dist = hi_d
    u0, u1, v0, v1 = extents(dist)
    loc = target + back * dist
    return {"type": "PERSP", "lens": lens, "ortho_scale": 1.0,
            "shift": [round((u0 + u1) / 2, 7), round((v0 + v1) / 2, 7)],
            "matrix": matrix(right, up, back, loc), "clip": [round(dist * 0.02, 6), round(dist * 20, 6)],
            "target": [round(float(t_), 7) for t_ in target], "distance": round(dist, 6)}


def project(points: np.ndarray, camera: dict[str, Any], aspect: tuple[int, int]) -> np.ndarray:
    """Normalised image coordinates (0..1, origin top-left) of world points for a camera block (for tests and
    for measuring where the part lands in a render)."""
    m = np.asarray(camera["matrix"], float)
    right, up, back, loc = m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3]
    q = np.asarray(points, float) - loc
    x, y, z = q @ right, q @ up, -(q @ back)
    fw, fh = _frame_sizes(aspect)
    if camera["type"] == "ORTHO":
        u, v = x / camera["ortho_scale"], y / camera["ortho_scale"]
    else:
        t = SENSOR_MM / 2 / camera["lens"]
        u, v = x / z / (2 * t) - camera["shift"][0], y / z / (2 * t) - camera["shift"][1]
    return np.stack([0.5 + u / fw, 0.5 - v / fh], axis=1)


def place_lights(rig: list[dict[str, Any]], target: np.ndarray, diag: float, cam_az: float) -> list[dict[str, Any]]:
    """Area lights aimed at the target, positioned relative to the camera azimuth and scaled to the part."""
    out = []
    ref = 0.25  # metres: the rig's powers are tuned for a part with a 250 mm diagonal
    for light in rig:
        d = view_dir(cam_az + light["az"], light["el"])
        loc = np.asarray(target, float) + d * light["dist"] * diag
        right, up, back = basis(cam_az + light["az"], light["el"])
        out.append({"name": light["name"], "matrix": matrix(right, up, back, loc),
                    "size": [round(light["w"] * diag, 6), round(light["h"] * diag, 6)],
                    "power": round(light["power"] * (diag / ref) ** 2, 5)})
    return out
