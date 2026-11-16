"""Mesh Studio: product renders and visualisation meshes of a project's verified part, made by Blender.

Blender (GPL) is only ever run as a separate program from the command line with a generated Python scene script
(`runner.py`). Nothing here imports or links Blender: `bpy` exists only inside that external process.

Everything this module produces is a *visualisation*: a triangle mesh tessellated from the exact B-rep, lit and
shaded for presentation. It is not the engineering model and must never be used to measure, inspect or manufacture.
"""

from __future__ import annotations

DISCLOSURE = ("Visualisation only. Renders and meshes are made from a tessellated copy of the verified model, with "
              "edges softened for display. They are not the exact model: use the STEP for engineering, inspection "
              "and manufacturing.")

VERSION = "1"  # scene-script version: bump on any change that alters a render, so cached renders are rebuilt
