"""Upload validation: size limits and type sniffing from magic bytes (the file name and browser MIME type are not
trusted), plus safe image normalisation for the preview and the vision read."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aicad.image2cad import InputError

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 40_000_000  # decompression-bomb guard (Pillow raises above 2x this anyway)
PREVIEW_PX = 2000  # long side of the preview / vision raster
MAX_PAGES_READ = 1

TYPES = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


def sniff(data: bytes) -> str:
    """'pdf' | 'png' | 'jpg' | 'webp' from the content, else InputError."""
    head = data[:16]
    if data[:1024].lstrip(b"\x00\t\r\n ").startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    raise InputError("Unsupported file. Upload a PDF drawing or a PNG, JPG or WebP image.")


def validate(data: bytes) -> str:
    if not data:
        raise InputError("The file is empty.")
    kind = sniff(data)
    limit = MAX_PDF_BYTES if kind == "pdf" else MAX_IMAGE_BYTES
    if len(data) > limit:
        raise InputError(f"The file is larger than {limit // (1024 * 1024)} MB.")
    return kind


def normalise_image(src: Path, dest: Path) -> dict[str, Any]:
    """Decode an uploaded image safely, apply the camera orientation, flatten transparency onto white and write a
    PNG no larger than PREVIEW_PX on its long side. Returns pixel sizes."""
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(src) as probe:
            probe.verify()
        with Image.open(src) as im:
            if im.width * im.height > MAX_PIXELS:
                raise InputError("The image has too many pixels. Upload an image under 40 megapixels.")
            ow, oh = im.width, im.height
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.getchannel("A"))
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")
            im.thumbnail((PREVIEW_PX, PREVIEW_PX), Image.Resampling.LANCZOS)
            im.save(dest, "PNG", optimize=True)
            return {"w": im.width, "h": im.height, "source_px": [ow, oh]}
    except InputError:
        raise
    except Image.DecompressionBombError:
        raise InputError("The image has too many pixels. Upload an image under 40 megapixels.") from None
    except Exception:  # noqa: BLE001 - any decoder failure is a bad upload, never a crash
        raise InputError("The image could not be read. It may be damaged or in an unsupported format.") from None
