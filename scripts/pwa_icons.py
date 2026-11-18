"""Render the PWA / home-screen icons from the Formwright logo mark (web/public/favicon.svg).

The mark is five flat polygons in a 32x32 box, so it is drawn here directly with Pillow (4x supersampled), with no
SVG rasteriser dependency. Re-run after a logo change and commit the PNGs:

    uv run python scripts/pwa_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "web" / "public" / "icons"
GRAPHITE = "#23272E"  # BRAND --chrome, also the manifest theme/background colour

# favicon.svg, path by path (absolute coordinates in the 32x32 viewBox)
MARK: list[tuple[str, list[tuple[float, float]]]] = [
    ("#1F5FBF", [(16, 2.5), (27.7, 9.25), (27.7, 22.75), (16, 29.5), (4.3, 22.75), (4.3, 9.25)]),
    ("#5C93E6", [(16, 2.5), (27.7, 9.25), (16, 16), (4.3, 9.25)]),
    ("#174A96", [(16, 16), (27.7, 9.25), (27.7, 22.75), (16, 29.5)]),
    ("#FFFFFF", [(8.2, 11.1), (16, 6.6), (19.2, 8.45), (11.4, 12.95), (11.4, 16.35), (17.0, 13.15), (20.2, 15.0),
                 (11.4, 20.05), (11.4, 24.65), (8.2, 21.8)]),
    ("#C8742E", [(22.6, 15.3), (27.7, 12.35), (27.7, 16.95), (22.6, 19.9)]),
]
# the mark's own extent inside the viewBox (x 4.3..27.7, y 2.5..29.5)
MARK_BOX = (4.3, 2.5, 27.7, 29.5)
SS = 4  # supersampling


def render(size: int, mark_frac: float, background: str | None, rounded: float = 0.0) -> Image.Image:
    """`mark_frac`: the mark's height as a fraction of the icon; `rounded`: corner radius fraction (0 = square)."""
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if background:
        if rounded:
            d.rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * rounded), fill=background)
        else:
            d.rectangle((0, 0, big, big), fill=background)
    x0, y0, x1, y1 = MARK_BOX
    scale = big * mark_frac / (y1 - y0)
    ox = (big - (x1 - x0) * scale) / 2 - x0 * scale
    oy = (big - (y1 - y0) * scale) / 2 - y0 * scale
    for colour, pts in MARK:
        d.polygon([(ox + x * scale, oy + y * scale) for x, y in pts], fill=colour)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for s in (192, 512):
        # purpose "any": the mark on a rounded graphite tile (reads well on light and dark launchers)
        render(s, 0.70, GRAPHITE, rounded=0.22).save(OUT / f"icon-{s}.png", optimize=True)
        # purpose "maskable": full-bleed background, mark inside the 80 % safe circle
        render(s, 0.52, GRAPHITE).save(OUT / f"icon-maskable-{s}.png", optimize=True)
    # iOS rounds the corners itself and fills transparency with black, so: square, opaque
    render(180, 0.64, GRAPHITE).convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)
    print(f"icons written to {OUT}")


if __name__ == "__main__":
    main()
