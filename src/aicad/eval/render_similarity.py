"""EVAL-006 render similarity (advisory, never gating).

How alike two renders of the same part and view look, as a number in [0, 1] (1 = identical). It is logged next to the
deterministic results in the benchmark, repeatability and run-record reports so a reviewer can spot a run whose part
*looks* different, but it never decides a pass: acceptance stays the deterministic checks (CHK-02..09).

Method (numpy + Pillow only, both already in the environment):
1. Both images are flattened onto their background, converted to grey and resampled to the same working size
   (longest side ``SIZE`` px, the reference's aspect ratio). Zoom, offset and shape differences survive the resample.
2. **Silhouette**: a pixel is foreground when it differs from the background (the median of the image border) by
   more than ``FG_THRESHOLD`` (or, for an image with transparency, when its alpha is above one half).
3. **Edges**: the Sobel gradient magnitude of the grey image above ``EDGE_THRESHOLD``, dilated by ``EDGE_TOL_PX``
   pixels on both sides so a one-pixel rasterisation shift is not a difference.
4. ``silhouette_ssim``: mean SSIM (Wang et al. 2004, 7 x 7 uniform window, C1 = 0.01^2, C2 = 0.03^2) of the two
   silhouette masks; ``edge_iou``: intersection over union of the dilated edge maps; ``silhouette_iou``: plain IoU
   of the masks (hand-checkable). ``score`` = mean of ``silhouette_ssim`` and ``edge_iou``.

Two empty images are identical (1.0); one empty and one not score 0. A Formwright review sheet (``views.png``: a
2 x 2 grid of ISO / FRONT / TOP / RIGHT) is compared quadrant by quadrant with each quadrant's label strip masked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

SIZE = 256              # working resolution (longest side, px)
FG_THRESHOLD = 0.06     # grey-level difference from the background that counts as part
EDGE_THRESHOLD = 0.25   # Sobel magnitude (grey 0..1, kernel sum 4) that counts as an edge
EDGE_TOL_PX = 1         # edge maps are dilated by this many pixels before the IoU
WINDOW = 7
C1, C2 = 0.01 ** 2, 0.03 ** 2
METHOD = "mean(silhouette SSIM, edge-map IoU ±1 px) at 256 px; advisory, never gating"
SHEET_GRID = (2, 2)     # views.png: rows x columns
LABEL_STRIP = (0.0, 0.92, 0.6, 1.0)  # per quadrant (x0, y0, x1, y1) as fractions: the view label, bottom left


# ------------------------------------------------------------------ image preparation
def _load(img: Any) -> tuple[np.ndarray, np.ndarray | None]:
    """(grey float32 H x W in 0..1, alpha mask or None). Accepts a path, a PIL image or an array."""
    from PIL import Image

    if isinstance(img, (str, Path)):
        with Image.open(img) as im:
            im.load()
            pil = im.copy()
    elif isinstance(img, np.ndarray):
        a = img.astype(np.float64)
        if a.max(initial=0) > 1.0:
            a = a / 255.0
        if a.ndim == 3 and a.shape[2] == 4:
            alpha = a[..., 3]
            grey = a[..., :3].mean(axis=2) * alpha + (1 - alpha)
            return grey.astype(np.float32), (alpha > 0.5) if alpha.min() < 0.99 else None
        grey = a.mean(axis=2) if a.ndim == 3 else a
        return grey.astype(np.float32), None
    else:
        pil = img
    if pil.mode in ("RGBA", "LA") or (pil.mode == "P" and "transparency" in pil.info):
        rgba = np.asarray(pil.convert("RGBA"), dtype=np.float64) / 255.0
        alpha = rgba[..., 3]
        grey = rgba[..., :3].mean(axis=2) * alpha + (1 - alpha)
        return grey.astype(np.float32), (alpha > 0.5) if alpha.min() < 0.99 else None
    return (np.asarray(pil.convert("L"), dtype=np.float32) / 255.0), None


def _resample(a: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    from PIL import Image

    if a.shape == shape:
        return a
    im = Image.fromarray(np.ascontiguousarray(a, dtype=np.float32))
    return np.asarray(im.resize((shape[1], shape[0]), Image.Resampling.BILINEAR), dtype=np.float32)


def _work_shape(h: int, w: int) -> tuple[int, int]:
    s = SIZE / max(h, w, 1)
    return max(8, round(h * s)), max(8, round(w * s))


def silhouette(grey: np.ndarray, alpha: np.ndarray | None = None) -> np.ndarray:
    """Foreground mask: alpha when the image has transparency, else 'differs from the border median'."""
    if alpha is not None:
        return alpha.astype(bool)
    border = np.concatenate([grey[0], grey[-1], grey[:, 0], grey[:, -1]])
    bg = float(np.median(border))
    return np.abs(grey - bg) > FG_THRESHOLD


def _sobel(g: np.ndarray) -> np.ndarray:
    p = np.pad(g.astype(np.float64), 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    return np.hypot(gx, gy)


def dilate(mask: np.ndarray, r: int) -> np.ndarray:
    """Binary dilation by a (2r+1) square, numpy only."""
    if r <= 0:
        return mask.copy()
    p = np.pad(mask, r, mode="constant")
    out = np.zeros_like(mask)
    h, w = mask.shape
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            out |= p[dy:dy + h, dx:dx + w]
    return out


def edges(grey: np.ndarray) -> np.ndarray:
    return _sobel(grey) > EDGE_THRESHOLD


# ------------------------------------------------------------------ measures
def _box_mean(a: np.ndarray, k: int) -> np.ndarray:
    """Mean over every k x k window (valid positions only), via an integral image."""
    c = np.pad(a, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return s / (k * k)


def ssim(a: np.ndarray, b: np.ndarray, k: int = WINDOW) -> float:
    """Mean SSIM of two equal-shape images in 0..1 (uniform k x k window)."""
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    if a.shape != b.shape:
        raise ValueError("ssim needs images of the same size")
    if min(a.shape) < k:
        k = max(1, min(a.shape))
    ma, mb = _box_mean(a, k), _box_mean(b, k)
    va = _box_mean(a * a, k) - ma * ma
    vb = _box_mean(b * b, k) - mb * mb
    cov = _box_mean(a * b, k) - ma * mb
    m = ((2 * ma * mb + C1) * (2 * cov + C2)) / ((ma * ma + mb * mb + C1) * (va + vb + C2))
    return float(np.clip(m.mean(), -1.0, 1.0))


def iou(a: np.ndarray, b: np.ndarray) -> float:
    union = int(np.count_nonzero(a | b))
    if union == 0:
        return 1.0
    return int(np.count_nonzero(a & b)) / union


def _prepare(img: Any, shape: tuple[int, int] | None, mask_out: np.ndarray | None = None
             ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    grey, alpha = _load(img)
    work = shape or _work_shape(*grey.shape)
    g = _resample(grey, work)
    al = None if alpha is None else _resample(alpha.astype(np.float32), work) > 0.5
    sil = silhouette(g, al)
    e = edges(g)
    if mask_out is not None:
        sil = sil & ~mask_out
        e = e & ~mask_out
    return g, sil, e


def compare(reference: Any, new: Any, *, ignore: list[tuple[float, float, float, float]] | None = None
            ) -> dict[str, Any]:
    """Similarity of ``new`` to ``reference`` (paths, PIL images or arrays). ``ignore``: boxes (x0, y0, x1, y1 as
    fractions of the image) left out of both, e.g. a caption."""
    g_ref, _ = _load(reference)
    work = _work_shape(*g_ref.shape)
    mask = None
    if ignore:
        mask = np.zeros(work, dtype=bool)
        h, w = work
        for x0, y0, x1, y1 in ignore:
            mask[round(y0 * h):round(y1 * h), round(x0 * w):round(x1 * w)] = True
    _, sa, ea = _prepare(reference, work, mask)
    _, sb, eb = _prepare(new, work, mask)
    return _measures(sa, ea, sb, eb)


def _measures(sa: np.ndarray, ea: np.ndarray, sb: np.ndarray, eb: np.ndarray) -> dict[str, Any]:
    empty_a, empty_b = not sa.any(), not sb.any()
    if empty_a and empty_b:
        sil_ssim, sil_iou = 1.0, 1.0
    elif empty_a or empty_b:
        sil_ssim, sil_iou = 0.0, 0.0
    else:
        sil_ssim = max(0.0, ssim(sa.astype(np.float64), sb.astype(np.float64)))
        sil_iou = iou(sa, sb)
    e_iou = iou(dilate(ea, EDGE_TOL_PX), dilate(eb, EDGE_TOL_PX))
    score = (sil_ssim + e_iou) / 2
    return {"score": round(score, 4), "silhouette_ssim": round(sil_ssim, 4), "edge_iou": round(e_iou, 4),
            "silhouette_iou": round(sil_iou, 4), "size_px": [int(sa.shape[1]), int(sa.shape[0])],
            "advisory": True, "gating": False, "method": METHOD}


def compare_sheets(reference: Any, new: Any, grid: tuple[int, int] = SHEET_GRID) -> dict[str, Any]:
    """Two review sheets (views.png) quadrant by quadrant; the label strip of each quadrant is masked.
    ``score`` is the mean over the views, ``views`` the per-view results (row-major: ISO, FRONT, TOP, RIGHT)."""
    from PIL import Image

    def tiles(img: Any) -> list[Any]:
        if isinstance(img, (str, Path)):
            with Image.open(img) as im:
                im.load()
                pil = im.copy()
        elif isinstance(img, np.ndarray):
            pil = Image.fromarray(img)
        else:
            pil = img
        w, h = pil.size
        rows, cols = grid
        return [pil.crop((c * w // cols, r * h // rows, (c + 1) * w // cols, (r + 1) * h // rows))
                for r in range(rows) for c in range(cols)]

    ta, tb = tiles(reference), tiles(new)
    views = [compare(a, b, ignore=[LABEL_STRIP]) for a, b in zip(ta, tb, strict=True)]
    keys = ("score", "silhouette_ssim", "edge_iou", "silhouette_iou")
    out: dict[str, Any] = {k: round(float(np.mean([v[k] for v in views])), 4) for k in keys}
    out.update(views=[{k: v[k] for k in keys} for v in views], worst_view=int(np.argmin([v["score"] for v in views])),
               advisory=True, gating=False, method=METHOD + "; per view of the 2 x 2 sheet, labels masked")
    return out


def compare_files(reference: Path, new: Path) -> dict[str, Any] | None:
    """Advisory comparison of two render files, or None when either is missing or unreadable (never raises).
    A ``views.png`` sheet is compared view by view."""
    try:
        if not (Path(reference).is_file() and Path(new).is_file()):
            return None
        if Path(new).name == "views.png" or Path(reference).name == "views.png":
            return compare_sheets(reference, new)
        return compare(reference, new)
    except Exception:  # noqa: BLE001 - an advisory metric must never break a report
        return None


def summary(values: list[float]) -> dict[str, Any]:
    """Mean / min / n of a list of scores, labelled advisory."""
    if not values:
        return {"n": 0, "advisory": True}
    return {"n": len(values), "mean": round(float(np.mean(values)), 4), "min": round(float(min(values)), 4),
            "advisory": True, "note": "render similarity is advisory: it never changes a pass or fail"}
