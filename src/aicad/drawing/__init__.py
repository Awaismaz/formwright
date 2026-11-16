"""Drawing Studio: manufacturing drawing sheets generated from a project's verified model.

Pipeline (all deterministic, no AI):
  geometry.py  exact OCCT work: hidden-line projections, section cut, hole / cylinder / level census
  dims.py      candidate dimensions and hole callouts, tagged ``spec`` (declared parameter) or ``inferred``
  layout.py    sheet: frame, scale, view placement, dimension placement, title block, legend, revision table
  check.py     CHK-12 drawing consistency (tags, spec-once, view extents vs bbox, text overlap, hole callouts)
  render.py    SVG (native), PDF (reportlab, BSD) and DXF (build123d ExportDXF / ezdxf, MIT) from one sheet
  generate.py  orchestration, revision history (associative regeneration) and outputs under <workspace>/drawings/
  worker.py    warm subprocess so the web process never loads the kernel

Only geometry.py and render.to_dxf import the CAD kernel; the rest is plain Python and unit-testable quickly.
"""

VERSION = "1.1.0"  # 1.1: turned parts axis-horizontal, radius/chamfer callouts, MAKE-01 placement, edits, releases


class DrawingInputError(ValueError):
    """A problem with the model or options that the user can act on (message is shown as is)."""
