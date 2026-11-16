"""Image & Drawing to CAD (module ``image2cad``): read a drawing, sketch or photo into a reviewed spec, then hand
the confirmed spec to the design agent.

Promise: never guess scale, and show exactly what was read and what is missing before any modelling.

Pipeline:
  tokens.py   deterministic dimension-text parser (linear, Ø, R, M threads, ±/fit tolerances, 4X counts, angles,
              chamfers, scale ratios, reference dimensions)
  sniff.py    upload validation: size limits, magic-byte type sniffing, image normalisation (Pillow, pixel cap)
  vector.py   vector PDF: text runs with positions (pdfminer.six, MIT), outline clustering into views, title block
              (scale, units, projection), dimension to view association, drawn-size vs dimension cross-check
  render.py   PDF page raster for the preview (pypdfium2 / PDFium, Apache-2.0 / BSD-3)
  extract.py  subprocess entry point: every untrusted file is parsed in a child process with a time limit
  vision.py   raster drawings, sketches and photos: the design agent's vision reads the image and returns a
              fenced JSON block; its texts go through the same token parser (mocked in tests)
  review.py   "What we read / What we need": open questions, answers, readiness and the agent hand-off prompt
  store.py    per-organisation upload folders under <data>/image2cad/<org>/<id>/
"""

VERSION = "1.0.0"


class InputError(ValueError):
    """A problem with the uploaded file that the user can act on (message shown as is)."""
