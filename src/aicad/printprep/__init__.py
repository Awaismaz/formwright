"""3D Print Prep: mesh checks, wall thickness, overhangs, orientation ranking, repair and STL/3MF export.

Everything here is deterministic numpy/OCCT code (no randomness, no time dependence). Results are geometric
measurements of a triangle mesh; they are NOT a slicer simulation and never a guarantee that a part will print.
"""

from __future__ import annotations

DISCLOSURE = ("Not slicer-verified. These are geometric checks of the mesh and rough estimates from editable "
              "assumptions. Slice the exported file in your printer's slicer and check its preview before printing.")

VERSION = "1"  # bump when an algorithm change alters reported numbers
