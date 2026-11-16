"""Image post-processing with Pillow (HPND licence): background composite, labelling metadata, thumbnails and the
turntable GIF. Deterministic: no randomness, fixed encoder settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, PngImagePlugin

from aicad.meshstudio import DISCLOSURE


def _rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float64)


def background(size: tuple[int, int], centre: str, edge: str) -> Image.Image:
    """Soft radial studio gradient, brightest a little above the middle (where a sweep catches the top light)."""
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    r = np.sqrt(((xx - 0.5 * w) / (0.75 * w)) ** 2 + ((yy - 0.42 * h) / (0.75 * h)) ** 2)
    t = np.clip(r, 0, 1) ** 1.6
    img = _rgb(centre)[None, None, :] * (1 - t[..., None]) + _rgb(edge)[None, None, :] * t[..., None]
    # 1-LSB ordered dither so smooth gradients don't band in 8-bit PNG
    bayer = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) / 16.0 - 0.5
    img = img + np.tile(bayer, (h // 4 + 1, w // 4 + 1))[:h, :w, None]
    return Image.fromarray(np.clip(np.rint(img), 0, 255).astype(np.uint8), "RGB").convert("RGBA")


def info(meta: dict[str, Any]) -> PngImagePlugin.PngInfo:
    pi = PngImagePlugin.PngInfo()
    pi.add_text("Software", "Formwright Mesh Studio")
    pi.add_text("Description", DISCLOSURE)
    for k, v in meta.items():
        pi.add_text(k, str(v))
    return pi


def finish_frame(src: Path, dst: Path, bg: dict[str, str] | None, meta: dict[str, Any]) -> tuple[int, int]:
    """Composite the transparent render over the studio background (or keep the alpha), add the labelling text
    chunks, and save. Returns the image size."""
    im = Image.open(src).convert("RGBA")
    if bg is not None:
        im = Image.alpha_composite(background(im.size, bg["centre"], bg["edge"]), im).convert("RGB")
    im.save(dst, "PNG", pnginfo=info(meta), optimize=False, compress_level=6)
    return im.size


def thumbnail(src: Path, dst: Path, width: int = 480) -> None:
    im = Image.open(src)
    im.thumbnail((width, width * 2), Image.Resampling.LANCZOS)
    if im.mode == "RGBA":  # keep transparency visible in the gallery as a light checker-free grey
        base = Image.new("RGBA", im.size, (236, 238, 241, 255))
        im = Image.alpha_composite(base, im)
    im.convert("RGB").save(dst, "JPEG", quality=86)


def gif(frames: list[Path], dst: Path, fps: int, width: int = 640) -> None:
    """Animated GIF (looping). One adaptive palette from the middle frame keeps colours stable across the turn."""
    ims = []
    for p in frames:
        im = Image.open(p).convert("RGB")
        if im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.Resampling.LANCZOS)
        ims.append(im)
    pal = ims[len(ims) // 2].quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    q = [im.quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG) for im in ims]
    q[0].save(dst, save_all=True, append_images=q[1:], duration=round(1000 / fps), loop=0, optimize=False,
              disposal=1, comment=DISCLOSURE.encode())


def coverage_bbox(path: Path, bg_threshold: float = 12.0) -> tuple[float, float, float, float] | None:
    """Normalised (x0, y0, x1, y1) box of pixels that differ from the background (alpha > 0 for transparent PNGs,
    else distance from the corner colour). Used by tests and the walkthrough to confirm framing."""
    im = np.asarray(Image.open(path).convert("RGBA")).astype(np.float64)
    if (im[..., 3] < 255).any():
        mask = im[..., 3] > 128
    else:
        ref = im[2, 2, :3]
        mask = np.linalg.norm(im[..., :3] - ref, axis=2) > bg_threshold
    if not mask.any():
        return None
    ys, xs = np.nonzero(mask)
    h, w = mask.shape
    return xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h
