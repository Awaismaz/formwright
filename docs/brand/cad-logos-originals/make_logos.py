"""Turn the founder's logo files into square symbol tiles for the landing page CAD grid."""
import re
import sys
from pathlib import Path

from PIL import Image

SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)


def svg_crop(src: str, dst: str, vb: str) -> None:
    s = (SRC / src).read_text(encoding="utf-8")
    root = re.search(r"<svg\b[^>]*>", s, re.S).group(0)
    new = re.sub(r'\s(width|height)="[^"]*"', "", root)
    new = re.sub(r'viewBox="[^"]*"', f'viewBox="{vb}"', new)
    (OUT / dst).write_text(s.replace(root, new, 1), encoding="utf-8")


def png_symbol(src: str, dst: str, region: tuple[int, int, int, int], white: int = 238) -> None:
    """Crop the symbol inside ``region`` (x0, y0, x1, y1) to its ink, square it, white -> transparent, 256 px."""
    im = Image.open(SRC / src).convert("RGBA").crop(region)
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            if r >= white and g >= white and b >= white:
                px[x, y] = (255, 255, 255, 0)
    bbox = im.getbbox()
    im = im.crop(bbox)
    side = max(im.size) + 8
    sq = Image.new("RGBA", (side, side), (255, 255, 255, 0))
    sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
    sq.resize((256, 256), Image.LANCZOS).save(OUT / dst, optimize=True)
    print(dst, "bbox", bbox, "->", sq.size)


# Inventor: the "I" box is the left ~340 of 1256 units; Creo: the cube is the left ~42 of 141 units
svg_crop("Autodesk_Inventor_Logo.svg", "inventor.svg", "0 0 340 310.77")
svg_crop("PTC_Creo_logo.svg", "creo.svg", "0 0 43 47.5")
# raster symbols: the region above / beside each wordmark
png_symbol("catia.png", "catia.png", (0, 0, 497, 280))          # 3DS mark above "CATIA"
png_symbol("siemens-nx.png", "nx.png", (0, 0, 215, 391))        # red / grey mark left of the wordmark
png_symbol("solid-edge.jpeg", "solid-edge.png", (0, 0, 280, 205))  # mark above "SOLID EDGE"
Image.open(SRC / "fusion.png").convert("RGBA").resize((256, 256), Image.LANCZOS).save(OUT / "fusion.png", optimize=True)
print("ok")
