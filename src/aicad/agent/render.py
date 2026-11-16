"""Offscreen VTK render of part.stl into one 2x2 PNG (iso, front, top, right).

Fixed cameras, parallel projection, CAD coordinates (Z up, front = looking along +Y).
Run as a subprocess (`python -m aicad.agent.render <stl> <png> [title]`) so a VTK/OpenGL
failure cannot take down the server.
"""

from __future__ import annotations

import sys
from pathlib import Path

VIEWS = [  # name, camera direction from centre, view-up
    ("ISO", (1.0, -1.0, 0.8), (0.0, 0.0, 1.0)),
    ("FRONT (-Y)", (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    ("TOP (+Z)", (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    ("RIGHT (+X)", (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
]
VIEWPORTS = [(0.0, 0.5, 0.5, 1.0), (0.5, 0.5, 1.0, 1.0), (0.0, 0.0, 0.5, 0.5), (0.5, 0.0, 1.0, 0.5)]


def render(stl: Path, png: Path, title: str = "", size: tuple[int, int] = (1400, 1050)) -> None:
    import vtk

    reader = vtk.vtkSTLReader()
    reader.SetFileName(str(stl))
    reader.Update()
    poly = reader.GetOutput()
    if poly.GetNumberOfPoints() == 0:
        raise RuntimeError("empty mesh")
    b = poly.GetBounds()
    centre = ((b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2)
    diag = max(((b[1] - b[0]) ** 2 + (b[3] - b[2]) ** 2 + (b[5] - b[4]) ** 2) ** 0.5, 1e-6)

    normals = vtk.vtkPolyDataNormals()
    normals.SetInputConnection(reader.GetOutputPort())
    normals.SetFeatureAngle(30)
    normals.SplittingOn()
    edges = vtk.vtkFeatureEdges()
    edges.SetInputConnection(reader.GetOutputPort())
    edges.BoundaryEdgesOn()
    edges.FeatureEdgesOn()
    edges.SetFeatureAngle(30)
    edges.ManifoldEdgesOff()
    edges.NonManifoldEdgesOn()
    edges.ColoringOff()

    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.SetSize(*size)
    win.SetMultiSamples(8)
    for (name, d, up), vp in zip(VIEWS, VIEWPORTS, strict=True):
        ren = vtk.vtkRenderer()
        ren.SetViewport(*vp)
        ren.SetBackground(0.93, 0.94, 0.96)
        m = vtk.vtkPolyDataMapper()
        m.SetInputConnection(normals.GetOutputPort())
        a = vtk.vtkActor()
        a.SetMapper(m)
        a.GetProperty().SetColor(0.72, 0.75, 0.80)
        a.GetProperty().SetSpecular(0.25)
        em = vtk.vtkPolyDataMapper()
        em.SetInputConnection(edges.GetOutputPort())
        em.SetResolveCoincidentTopologyToPolygonOffset()
        ea = vtk.vtkActor()
        ea.SetMapper(em)
        ea.GetProperty().SetColor(0.08, 0.09, 0.12)
        ea.GetProperty().SetLineWidth(1.5)
        ren.AddActor(a)
        ren.AddActor(ea)
        axes = vtk.vtkAxesActor()
        axes.SetTotalLength(diag * 0.12, diag * 0.12, diag * 0.12)
        axes.SetPosition(b[0], b[2], b[4])
        axes.AxisLabelsOff()
        ren.AddActor(axes)
        cam = ren.GetActiveCamera()
        cam.ParallelProjectionOn()
        cam.SetFocalPoint(*centre)
        n = sum(x * x for x in d) ** 0.5
        cam.SetPosition(*(c + diag * 2 * x / n for c, x in zip(centre, d, strict=True)))
        cam.SetViewUp(*up)
        ren.ResetCamera()
        cam.SetParallelScale(cam.GetParallelScale() * 0.92)
        t = vtk.vtkTextActor()
        t.SetInput(name if not title or name != "ISO" else f"ISO  -  {title}")
        t.GetTextProperty().SetFontSize(18)
        t.GetTextProperty().SetColor(0.1, 0.1, 0.15)
        t.SetPosition(10, 10)
        ren.AddViewProp(t)
        win.AddRenderer(ren)
    win.Render()
    w2i = vtk.vtkWindowToImageFilter()
    w2i.SetInput(win)
    w2i.Update()
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(png))
    writer.SetInputConnection(w2i.GetOutputPort())
    writer.Write()
    if png.name == "views.png":
        try:  # the project-card picture: one clean view, never allowed to break the review sheet above
            _thumb(vtk, normals, edges, centre, diag, png.with_name("thumb.png"))
        except Exception as e:  # noqa: BLE001
            print(f"thumbnail skipped: {e}", file=sys.stderr)


def _thumb(vtk, normals, edges, centre, diag, out: Path, size: tuple[int, int] = (960, 720)) -> None:  # type: ignore[no-untyped-def]
    """Isometric view on a transparent background, without labels or the axis triad (for project cards)."""
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.SetSize(*size)
    win.SetAlphaBitPlanes(1)
    win.SetMultiSamples(0)
    ren = vtk.vtkRenderer()
    ren.SetBackground(1.0, 1.0, 1.0)
    ren.SetBackgroundAlpha(0.0)
    ren.SetUseFXAA(True)
    m = vtk.vtkPolyDataMapper()
    m.SetInputConnection(normals.GetOutputPort())
    a = vtk.vtkActor()
    a.SetMapper(m)
    a.GetProperty().SetColor(0.72, 0.75, 0.80)
    a.GetProperty().SetSpecular(0.25)
    em = vtk.vtkPolyDataMapper()
    em.SetInputConnection(edges.GetOutputPort())
    em.SetResolveCoincidentTopologyToPolygonOffset()
    ea = vtk.vtkActor()
    ea.SetMapper(em)
    ea.GetProperty().SetColor(0.08, 0.09, 0.12)
    ea.GetProperty().SetLineWidth(2.0)
    ren.AddActor(a)
    ren.AddActor(ea)
    _, d, up = VIEWS[0]
    cam = ren.GetActiveCamera()
    cam.ParallelProjectionOn()
    cam.SetFocalPoint(*centre)
    n = sum(x * x for x in d) ** 0.5
    cam.SetPosition(*(c + diag * 2 * x / n for c, x in zip(centre, d, strict=True)))
    cam.SetViewUp(*up)
    ren.ResetCamera()
    cam.SetParallelScale(cam.GetParallelScale() * 0.86)
    win.AddRenderer(ren)
    win.Render()
    w2i = vtk.vtkWindowToImageFilter()
    w2i.SetInput(win)
    w2i.SetInputBufferTypeToRGBA()
    w2i.ReadFrontBufferOff()
    w2i.Update()
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(out))
    writer.SetInputConnection(w2i.GetOutputPort())
    writer.Write()


if __name__ == "__main__":
    render(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "")
