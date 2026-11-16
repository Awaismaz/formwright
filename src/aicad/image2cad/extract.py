"""Parse one uploaded file in a child process (``python -m aicad.image2cad.extract <upload dir>``).

Untrusted PDFs and images are never parsed in the web process: the parent runs this with a time limit and kills
it on overrun. Writes ``preview.png`` and ``extract.json``::

  {"ok": true, "kind": "pdf"|"png"|..., "pages": n, "preview": {"w", "h"}, "read": {...vector read...} | null,
   "needs_vision": bool}
  {"ok": false, "error": "user-facing message", "user": true}
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from aicad.image2cad import InputError
from aicad.image2cad.sniff import PREVIEW_PX, normalise_image

TIMEOUT_S = 90
MIN_TEXT_CHARS = 8  # fewer characters than this on a PDF page means a scan (no usable text layer)


def render_pdf(src: Path, dest: Path) -> dict[str, Any]:
    """Rasterise page 1 with PDFium (pypdfium2) so its long side is PREVIEW_PX pixels."""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(str(src))
    except pdfium.PdfiumError as e:
        msg = str(e).lower()
        if "password" in msg:
            raise InputError("This PDF is password-protected. Upload an unprotected copy.") from None
        raise InputError("The PDF could not be read. It may be damaged.") from None
    try:
        n = len(pdf)
        if n == 0:
            raise InputError("The PDF has no pages.")
        page = pdf[0]
        w, h = page.get_size()
        if page.get_rotation() in (90, 270):
            w, h = h, w
        scale = PREVIEW_PX / max(w, h, 1.0)
        img = page.render(scale=scale, may_draw_forms=True).to_pil().convert("RGB")
        img.save(dest, "PNG", optimize=True)
        return {"pages": n, "w": img.width, "h": img.height}
    finally:
        pdf.close()


def run(d: Path) -> dict[str, Any]:
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    kind = meta["type"]
    src = d / meta["file"]
    if kind == "pdf":
        from aicad.image2cad.vector import read_pdf

        info = render_pdf(src, d / "preview.png")
        read = read_pdf(src)
        scan = read["chars"] < MIN_TEXT_CHARS
        return {"ok": True, "kind": kind, "pages": info["pages"], "preview": {"w": info["w"], "h": info["h"]},
                "read": None if scan else read, "needs_vision": scan}
    info = normalise_image(src, d / "preview.png")
    return {"ok": True, "kind": kind, "pages": 1, "preview": {"w": info["w"], "h": info["h"]},
            "source_px": info["source_px"], "read": None, "needs_vision": True}


def main() -> None:
    d = Path(sys.argv[1])
    try:
        out = run(d)
    except InputError as e:
        out = {"ok": False, "error": str(e), "user": True}
    except Exception:  # noqa: BLE001 - a hostile or broken file must yield a message, not a traceback
        out = {"ok": False, "error": "The file could not be read. It may be damaged or use features we can't parse.",
               "user": True}
    (d / "extract.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


async def extract(d: Path, timeout: float = TIMEOUT_S) -> dict[str, Any]:
    """Run the child process for upload folder ``d`` and return its result."""
    f = d / "extract.json"
    f.unlink(missing_ok=True)
    proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "aicad.image2cad.extract", str(d),
                                                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return {"ok": False, "error": "Reading this file took too long. Try a simpler or smaller file.", "user": True}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        import logging

        logging.getLogger("aicad.image2cad").error("extract failed: %s", (err or b"")[-2000:].decode(errors="replace"))
        return {"ok": False, "error": "The file could not be read.", "user": True}


if __name__ == "__main__":
    main()
