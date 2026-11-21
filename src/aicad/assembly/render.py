"""Multi-view picture of an assembly (ASM visual check): iso + front + top + right in one PNG, every item in its own
colour with a numbered key, parallel projection, Z up, and the floor drawn as a grid so "parts lying on the floor in
a row" is obvious at a glance.

Two scene sources, same renderer:
  * ``scene_from_doc``: an Assembly Studio document (or a Design Office program assembly, which is one): every visible
    instance's exact face mesh (``topo.json`` of its part snapshot) placed by its 12-number placement;
  * ``scene_from_skeleton``: a Design Office skeleton before anything is built (the ICD gate): every item copy as its
    envelope (a box, or a cylinder along its axis) at its layout position. This needs no CAD kernel at all.

Rendering runs in a subprocess (``python -m aicad.assembly.render <scene.json> <out.png>``) so a VTK/OpenGL failure
can never take the server down, exactly like the part review sheet (``aicad.agent.render``). The picture is an
advisory signal (CLAUDE.md: geometry acceptance is deterministic checks, never renders).
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# distinct, saturated colours that stay apart on a light background (and in a small picture)
PALETTE: tuple[tuple[float, float, float], ...] = (
    (0.90, 0.33, 0.13), (0.13, 0.47, 0.85), (0.20, 0.66, 0.29), (0.85, 0.65, 0.10), (0.58, 0.31, 0.78),
    (0.05, 0.68, 0.72), (0.86, 0.22, 0.52), (0.50, 0.38, 0.22), (0.47, 0.71, 0.12), (0.24, 0.29, 0.60),
    (0.95, 0.50, 0.55), (0.42, 0.45, 0.48),
)
FASTENER = (0.55, 0.57, 0.60)
MAX_KEY = 24        # items listed in the key (the rest are summarised)
MAX_BODIES = 1200   # instances drawn (an F1-sized program has ~650)
SIZE = (1280, 960)
TIMEOUT_S = 60.0

VIEWS = [  # name, camera direction from the centre, view-up (CAD convention: front looks along +Y)
    ("ISO", (1.0, -1.0, 0.8), (0.0, 0.0, 1.0)),
    ("FRONT", (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    ("TOP", (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    ("RIGHT", (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
]
VIEWPORTS = [(0.0, 0.5, 0.5, 1.0), (0.5, 0.5, 1.0, 1.0), (0.0, 0.0, 0.5, 0.5), (0.5, 0.0, 1.0, 0.5)]


class RenderError(RuntimeError):
    """The picture could not be made (plain message, safe to show)."""


# ----------------------------------------------------------------------------- scenes (pure, server side)
def _clean_label(name: str) -> str:
    return " ".join(str(name).split("<")[0].replace("Demo · ", "").split())[:48] or "Part"


def _key_items(bodies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Number and colour each item (copies share both), in first-seen order; fasteners share one grey entry."""
    items: dict[str, dict[str, Any]] = {}
    for b in bodies:
        g = b["group"]
        if g not in items:
            n = len(items) + 1
            items[g] = {"n": n, "label": b["label"], "count": 0, "fastener": bool(b.get("fastener")),
                        "color": FASTENER if b.get("fastener") else PALETTE[(n - 1) % len(PALETTE)]}
        items[g]["count"] += 1
        b["n"] = items[g]["n"]
        b["color"] = items[g]["color"]
    return list(items.values())


def scene_from_doc(root: Path, doc: dict[str, Any], title: str = "") -> dict[str, Any]:
    """Every visible instance of an assembly document, with the face mesh of its part snapshot."""
    from aicad.assembly import store

    bodies: list[dict[str, Any]] = []
    fasteners = 0
    for i in doc["instances"]:
        if not i.get("visible", True):
            continue
        if len(bodies) >= MAX_BODIES:
            break
        topo = store.part_dir(root, i["part"]) / "topo.json"
        if not topo.is_file():
            continue
        o = i.get("office") or {}
        fast = bool(i.get("group"))
        fasteners += fast
        group = "fasteners" if fast else (f"item:{o['item']}" if o.get("item") else f"name:{_clean_label(i['name'])}")
        bodies.append({"id": i["id"], "group": group, "label": "Fasteners" if fast else _clean_label(i["name"]),
                       "mesh": str(topo), "T": [float(x) for x in i["T"]], "fastener": fast,
                       "bin": bool(o.get("bin"))})
    key = _key_items(bodies)
    return {"title": title or doc.get("name") or "Assembly", "bodies": bodies, "key": key, "kind": "assembly"}


def scene_from_skeleton(skel: dict[str, Any], title: str = "", ifaces: list[dict[str, Any]] | None = None
                        ) -> dict[str, Any]:
    """Every copy of every skeleton item as its envelope (no CAD): boxes for blocks, cylinders along the item's axis
    for shafts, hubs and gears, at the layout position and turn the program assembly would use. With the ICD's
    interfaces, bearings and dowel pins the ICD seats are drawn where Fitz would seat them."""
    from aicad.office import frames, icd

    bodies: list[dict[str, Any]] = []
    for iid, it in (skel.get("items") or {}).items():
        size = [float(v) for v in it.get("size") or [10, 10, 10]]
        prim = "box" if it.get("shape") == "box" else "cyl"
        for c, at in enumerate(it.get("copies") or []):
            T = frames.placed(at, float(it.get("rot") or 0) + float(it.get("phase") or 0), None, it.get("ax") or "z")
            bodies.append({"id": f"{iid}#{c}", "group": f"item:{iid}", "label": _clean_label(it.get("name") or iid),
                           "prim": prim, "size": size, "T": [float(x) for x in T]})
    for st in skel.get("standard") or []:
        seat = icd.seated(ifaces or [], st["item"])
        if not seat:
            continue
        prim = "cyl"
        if seat["code"] == "bearing":
            from aicad.toolbox import BEARING

            _d, D, B = BEARING[int(seat["params"]["SERIES"])]
            size = [float(D), float(D), float(B)]
        elif seat["code"] == "parallel_key":  # a box: length along its X, width Y, height Z from its base
            from aicad.toolbox import key_row

            kb, kh, _t1, _t2 = key_row(float(seat["params"]["D"]))
            size, prim = [float(seat["params"]["L"]), kb, kh], "box"
        elif seat["code"] == "retaining_ring":
            from aicad.toolbox import ring_row

            s_, b_, d2, _m, _n = ring_row(float(seat["params"]["D"]))
            size = [d2 + 2 * b_, d2 + 2 * b_, s_]
        elif seat["code"] == "shaft_seal":
            from aicad.toolbox import seal_row

            sD, sb = seal_row(float(seat["params"]["D"]))
            size = [sD, sD, sb]
        else:
            size = [float(seat["params"]["D"])] * 2 + [float(seat["params"]["L"])]
        R = seat.get("R") or frames.IDENT
        for c, at in enumerate(seat["at"]):  # the part's base point; the body is centred: half its length along Z
            R = (seat.get("Rs") or [])[c] if c < len(seat.get("Rs") or []) else (seat.get("R") or frames.IDENT)
            mid = [float(at[k]) + R[k][2] * size[2] / 2 for k in range(3)]
            bodies.append({"id": f"{st['item']}#{c}", "group": f"item:{st['item']}", "prim": prim, "size": size,
                           "label": _clean_label(st.get("name") or seat["title"]), "T": frames.to12(R, mid)})
    key = _key_items(bodies)
    return {"title": title or "Layout", "bodies": bodies, "key": key, "kind": "skeleton"}


def bounds(scene: dict[str, Any]) -> tuple[list[float], list[float]] | None:
    """World box of a scene (envelopes of primitives; meshes use their placement origin plus a part box when the
    caller added one as ``bbox``). Used for quick placement checks without opening any mesh."""
    pts: list[list[float]] = []
    for b in scene["bodies"]:
        if b.get("prim"):
            L, W, H = b["size"]
            loc = [(x, y, z) for x in (-L / 2, L / 2) for y in (-W / 2, W / 2) for z in (-H / 2, H / 2)]
        elif b.get("bbox"):
            x0, y0, z0, x1, y1, z1 = b["bbox"]
            loc = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
        else:
            continue
        T = b["T"]
        for p in loc:
            pts.append([T[4 * r] * p[0] + T[4 * r + 1] * p[1] + T[4 * r + 2] * p[2] + T[4 * r + 3] for r in range(3)])
    if not pts:
        return None
    return [min(p[k] for p in pts) for k in range(3)], [max(p[k] for p in pts) for k in range(3)]


def render(scene: dict[str, Any], png: Path, timeout: float = TIMEOUT_S) -> dict[str, Any]:
    """Draw ``scene`` into ``png`` in a subprocess. Returns {seconds, bytes, bodies}. Raises ``RenderError``."""
    if not scene["bodies"]:
        raise RenderError("There is nothing to draw: the assembly has no visible parts.")
    png.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="fw-asmrender-") as tmp:
        spec = Path(tmp) / "scene.json"
        spec.write_text(json.dumps(scene), encoding="utf-8")
        out = Path(tmp) / "out.png"
        try:
            r = subprocess.run([sys.executable, "-m", "aicad.assembly.render", str(spec), str(out)],
                               check=False, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise RenderError("The assembly picture took too long to draw.") from e
        if r.returncode != 0 or not out.is_file():
            tail = (r.stderr or "").strip().splitlines()[-1:] or ["no output"]
            raise RenderError(f"The assembly picture could not be drawn ({tail[0][:200]}).")
        png.write_bytes(out.read_bytes())
    return {"seconds": round(time.perf_counter() - t0, 3), "bytes": png.stat().st_size, "bodies": len(scene["bodies"])}


async def render_async(scene: dict[str, Any], png: Path, timeout: float = TIMEOUT_S) -> dict[str, Any]:
    import asyncio

    return await asyncio.to_thread(render, scene, png, timeout)


# ----------------------------------------------------------------------------- the VTK side (subprocess only)
def _nice_step(span: float) -> float:
    raw = max(span, 1.0) / 12
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * mag:
            return float(m * mag)
    return float(10 * mag)


def _mesh_poly(vtk: Any, path: str, cache: dict[str, Any]) -> tuple[Any, Any]:
    """(faces polydata, edges polydata) of a part's topo.json, cached per file."""
    if path in cache:
        return cache[path]
    import numpy as np
    from vtkmodules.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray

    topo = json.loads(Path(path).read_text(encoding="utf-8"))
    pos_parts, idx_parts, off = [], [], 0
    for f in topo.get("faces") or []:
        p = np.asarray(f.get("pos") or [], dtype=float).reshape(-1, 3)
        ix = np.asarray(f.get("idx") or [], dtype=np.int64).reshape(-1, 3)
        if len(p) == 0 or len(ix) == 0:
            continue
        pos_parts.append(p)
        idx_parts.append(ix + off)
        off += len(p)
    poly = vtk.vtkPolyData()
    if pos_parts:
        P = np.concatenate(pos_parts)
        I = np.concatenate(idx_parts)
        pts = vtk.vtkPoints()
        pts.SetData(numpy_to_vtk(P, deep=True))
        cells = np.hstack([np.full((len(I), 1), 3, dtype=np.int64), I]).ravel()
        ca = vtk.vtkCellArray()
        ca.SetCells(len(I), numpy_to_vtkIdTypeArray(cells, deep=True))
        poly.SetPoints(pts)
        poly.SetPolys(ca)
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(poly)
    normals.SetFeatureAngle(35)
    normals.SplittingOn()
    normals.Update()
    # outline: real corners only (faces carry their own vertices, so merge them first; a polyline-sampled involute
    # flank is smooth at 35 degrees and would otherwise blacken a gear with hundreds of edges)
    clean = vtk.vtkCleanPolyData()
    clean.SetInputData(poly)
    clean.Update()
    edges = vtk.vtkFeatureEdges()
    edges.SetInputConnection(clean.GetOutputPort())
    edges.BoundaryEdgesOff()
    edges.FeatureEdgesOn()
    edges.SetFeatureAngle(35)
    edges.ManifoldEdgesOff()
    edges.NonManifoldEdgesOff()
    edges.ColoringOff()
    edges.Update()
    cache[path] = (normals.GetOutput(), edges.GetOutput())
    return cache[path]


def _prim_poly(vtk: Any, prim: str, size: list[float], cache: dict[str, Any]) -> tuple[Any, Any]:
    k = f"{prim}:{size}"
    if k in cache:
        return cache[k]
    L, W, H = size
    if prim == "box":
        src = vtk.vtkCubeSource()
        src.SetXLength(L)
        src.SetYLength(W)
        src.SetZLength(H)
        src.Update()
        poly = src.GetOutput()
    else:
        src = vtk.vtkCylinderSource()  # along its Y: turn it onto Z
        src.SetRadius(max(L, W) / 2)
        src.SetHeight(H)
        src.SetResolution(48)
        src.CappingOn()
        tf = vtk.vtkTransform()
        tf.RotateX(90)
        f = vtk.vtkTransformPolyDataFilter()
        f.SetInputConnection(src.GetOutputPort())
        f.SetTransform(tf)
        f.Update()
        poly = f.GetOutput()
    edges = vtk.vtkFeatureEdges()
    edges.SetInputData(poly)
    edges.BoundaryEdgesOn()
    edges.FeatureEdgesOn()
    edges.SetFeatureAngle(30)
    edges.ManifoldEdgesOff()
    edges.ColoringOff()
    edges.Update()
    cache[k] = (poly, edges.GetOutput())
    return cache[k]


def _matrix(vtk: Any, T: list[float]) -> Any:
    m = vtk.vtkMatrix4x4()
    for r in range(3):
        for c in range(4):
            m.SetElement(r, c, float(T[4 * r + c]))
    return m


def _vtk() -> Any:
    """Only the VTK modules the picture needs (``import vtk`` loads every module: 1.0 s against 0.4 s)."""
    from types import SimpleNamespace

    import vtkmodules.vtkInteractionStyle
    import vtkmodules.vtkRenderingFreeType
    import vtkmodules.vtkRenderingOpenGL2  # noqa: F401
    from vtkmodules import (
        vtkCommonCore,
        vtkCommonDataModel,
        vtkCommonMath,
        vtkCommonTransforms,
        vtkFiltersCore,
        vtkFiltersGeneral,
        vtkFiltersSources,
        vtkIOImage,
        vtkRenderingAnnotation,
        vtkRenderingCore,
    )

    ns = SimpleNamespace()
    for mod in (vtkCommonCore, vtkCommonDataModel, vtkCommonMath, vtkCommonTransforms, vtkFiltersCore,
                vtkFiltersGeneral, vtkFiltersSources, vtkIOImage, vtkRenderingAnnotation, vtkRenderingCore):
        for k in dir(mod):
            if k.startswith("vtk"):
                setattr(ns, k, getattr(mod, k))
    return ns


def draw(scene: dict[str, Any], png: Path, size: tuple[int, int] = SIZE) -> None:
    vtk = _vtk()

    cache: dict[str, Any] = {}
    actors: list[tuple[Any, Any, dict[str, Any]]] = []  # (mapper faces, mapper edges, body)
    world = vtk.vtkBoundingBox()
    for b in scene["bodies"]:
        if b.get("prim"):
            faces, edges = _prim_poly(vtk, b["prim"], b["size"], cache)
        else:
            faces, edges = _mesh_poly(vtk, b["mesh"], cache)
        if faces.GetNumberOfPoints() == 0:
            continue
        m = _matrix(vtk, b["T"])
        bb = faces.GetBounds()
        for x in (bb[0], bb[1]):
            for y in (bb[2], bb[3]):
                for z in (bb[4], bb[5]):
                    p = m.MultiplyPoint((x, y, z, 1.0))
                    world.AddPoint(p[0], p[1], p[2])
        actors.append((faces, edges, b))
    if not actors:
        raise RuntimeError("no geometry to draw")
    lo = [world.GetMinPoint()[k] for k in range(3)]
    hi = [world.GetMaxPoint()[k] for k in range(3)]
    span = max(hi[k] - lo[k] for k in range(3))
    diag = max(math.dist(lo, hi), 1e-6)
    centre = [(lo[k] + hi[k]) / 2 for k in range(3)]

    # the floor: a grid on the lowest point of the assembly, 15 % wider than its footprint
    step = _nice_step(max(hi[0] - lo[0], hi[1] - lo[1], span * 0.5))
    pad = max(step, 0.15 * max(hi[0] - lo[0], hi[1] - lo[1]))
    gx0 = math.floor((lo[0] - pad) / step) * step
    gx1 = math.ceil((hi[0] + pad) / step) * step
    gy0 = math.floor((lo[1] - pad) / step) * step
    gy1 = math.ceil((hi[1] + pad) / step) * step
    gz = lo[2] - 0.002 * diag
    grid_pts = vtk.vtkPoints()
    grid_lines = vtk.vtkCellArray()

    def seg(a: tuple[float, float, float], b: tuple[float, float, float]) -> None:
        i0 = grid_pts.InsertNextPoint(*a)
        i1 = grid_pts.InsertNextPoint(*b)
        ln = vtk.vtkLine()
        ln.GetPointIds().SetId(0, i0)
        ln.GetPointIds().SetId(1, i1)
        grid_lines.InsertNextCell(ln)

    x = gx0
    while x <= gx1 + 1e-9:
        seg((x, gy0, gz), (x, gy1, gz))
        x += step
    y = gy0
    while y <= gy1 + 1e-9:
        seg((gx0, y, gz), (gx1, y, gz))
        y += step
    grid = vtk.vtkPolyData()
    grid.SetPoints(grid_pts)
    grid.SetLines(grid_lines)
    floor = vtk.vtkPlaneSource()
    floor.SetOrigin(gx0, gy0, gz - 0.001 * diag)
    floor.SetPoint1(gx1, gy0, gz - 0.001 * diag)
    floor.SetPoint2(gx0, gy1, gz - 0.001 * diag)

    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.SetSize(*size)
    win.SetMultiSamples(0)  # depth peeling needs it off
    win.SetAlphaBitPlanes(1)
    # containers (a housing, a cover over parts): drawn see-through so the parts inside them show
    boxes = []
    for faces, _e, b in actors:
        bb = faces.GetBounds()
        m = _matrix(vtk, b["T"])
        ps = [m.MultiplyPoint((x, y, z, 1.0)) for x in bb[:2] for y in bb[2:4] for z in bb[4:]]
        boxes.append(([min(p[k] for p in ps) for k in range(3)], [max(p[k] for p in ps) for k in range(3)]))
    see_through: set[int] = set()
    for i, (lo_i, hi_i) in enumerate(boxes):
        vol_i = math.prod(hi_i[k] - lo_i[k] for k in range(3))
        for j, (lo_j, hi_j) in enumerate(boxes):
            if i == j or math.prod(hi_j[k] - lo_j[k] for k in range(3)) >= vol_i:
                continue
            if all(lo_i[k] - 0.5 <= lo_j[k] and hi_j[k] <= hi_i[k] + 0.5 for k in range(3)):  # wholly inside
                see_through.add(i)
                break
    # labels on the first copy of each item only (keeps a big program readable)
    labelled: set[int] = set()
    label_at: list[tuple[int, list[float], tuple[float, float, float]]] = []
    for faces, _e, b in actors:
        if b["n"] in labelled or b.get("fastener") or len(labelled) >= MAX_KEY:
            continue
        labelled.add(b["n"])
        bb = faces.GetBounds()
        m = _matrix(vtk, b["T"])
        c = m.MultiplyPoint(((bb[0] + bb[1]) / 2, (bb[2] + bb[3]) / 2, (bb[4] + bb[5]) / 2, 1.0))
        label_at.append((b["n"], [c[0], c[1], c[2]], b["color"]))
    for vi, ((name, d, up), vp) in enumerate(zip(VIEWS, VIEWPORTS, strict=True)):
        ren = vtk.vtkRenderer()
        ren.SetViewport(*vp)
        ren.SetBackground(0.96, 0.97, 0.98)
        ren.SetUseDepthPeeling(1)
        ren.SetMaximumNumberOfPeels(4)
        for ai, (faces, edges, b) in enumerate(actors):
            m = _matrix(vtk, b["T"])
            fm = vtk.vtkPolyDataMapper()
            fm.SetInputData(faces)
            a = vtk.vtkActor()
            a.SetMapper(fm)
            a.SetUserMatrix(m)
            a.GetProperty().SetColor(*b["color"])
            a.GetProperty().SetSpecular(0.2)
            a.GetProperty().SetDiffuse(0.85)
            a.GetProperty().SetAmbient(0.18)
            if ai in see_through:
                a.GetProperty().SetOpacity(0.28)
            ren.AddActor(a)
            if edges.GetNumberOfPoints():
                em = vtk.vtkPolyDataMapper()
                em.SetInputData(edges)
                em.SetResolveCoincidentTopologyToPolygonOffset()
                ea = vtk.vtkActor()
                ea.SetMapper(em)
                ea.SetUserMatrix(m)
                ea.GetProperty().SetColor(0.16, 0.18, 0.22)
                ea.GetProperty().SetLineWidth(1.0)
                ren.AddActor(ea)
        if name != "TOP":  # seen from above, the floor would hide nothing but look like a part
            fm = vtk.vtkPolyDataMapper()
            fm.SetInputConnection(floor.GetOutputPort())
            fa = vtk.vtkActor()
            fa.SetMapper(fm)
            fa.GetProperty().SetColor(0.86, 0.88, 0.91)
            fa.GetProperty().SetOpacity(0.55)
            fa.GetProperty().LightingOff()
            ren.AddActor(fa)
        gm = vtk.vtkPolyDataMapper()
        gm.SetInputData(grid)
        ga = vtk.vtkActor()
        ga.SetMapper(gm)
        ga.GetProperty().SetColor(0.62, 0.65, 0.70)
        ga.GetProperty().SetLineWidth(1.0)
        ga.GetProperty().LightingOff()
        ren.AddActor(ga)
        axes = vtk.vtkAxesActor()
        L = step * 1.5
        axes.SetTotalLength(L, L, L)
        axes.SetPosition(gx0, gy0, gz)
        axes.AxisLabelsOff()
        ren.AddActor(axes)
        cam = ren.GetActiveCamera()
        cam.ParallelProjectionOn()
        cam.SetFocalPoint(*centre)
        nrm = math.sqrt(sum(v * v for v in d))
        cam.SetPosition(*(centre[k] + diag * 3 * d[k] / nrm for k in range(3)))
        cam.SetViewUp(*up)
        ren.ResetCamera()
        cam.SetParallelScale(cam.GetParallelScale() * (0.80 if vi else 0.92))
        win.AddRenderer(ren)
        # item numbers: 2D tags at each item's projected centre (always readable, never hidden inside a solid)
        w_px, h_px = size[0] * (vp[2] - vp[0]), size[1] * (vp[3] - vp[1])
        for n, c, col in label_at:
            co = vtk.vtkCoordinate()
            co.SetCoordinateSystemToWorld()
            co.SetValue(*c)
            x, y = co.GetComputedDoubleViewportValue(ren)
            if not (0 <= x <= w_px and 0 <= y <= h_px):
                continue
            t = vtk.vtkTextActor()
            t.SetInput(f" {n} ")
            tp = t.GetTextProperty()
            tp.SetFontSize(15)
            tp.BoldOn()
            tp.SetColor(1, 1, 1)
            tp.SetBackgroundColor(*col)
            tp.SetBackgroundOpacity(1.0)
            tp.SetFrame(True)
            tp.SetFrameColor(0.1, 0.1, 0.12)
            tp.SetJustificationToCentered()
            tp.SetVerticalJustificationToCentered()
            t.SetPosition(x, y)
            ren.AddViewProp(t)
        lbl = vtk.vtkTextActor()
        lbl.SetInput({"ISO": "ISO", "FRONT": "FRONT (looking +Y)", "TOP": "TOP (looking -Z)",
                      "RIGHT": "RIGHT (looking -X)"}[name])
        lbl.GetTextProperty().SetFontSize(16)
        lbl.GetTextProperty().BoldOn()
        lbl.GetTextProperty().SetColor(0.12, 0.13, 0.17)
        lbl.SetPosition(10, 8)
        ren.AddViewProp(lbl)
        if vi == 0:
            key = scene["key"]
            lines = [f"{k['n']}  {k['label']}" + (f"  x{k['count']}" if k["count"] > 1 else "") for k in key[:MAX_KEY]]
            if len(key) > MAX_KEY:
                lines.append(f"... and {len(key) - MAX_KEY} more items")
            y0 = int(size[1] * 0.5) - 44
            for j, (ln, k) in enumerate(zip(lines, key[:MAX_KEY] + [None] * 2, strict=False)):
                ta = vtk.vtkTextActor()
                ta.SetInput(ln)
                tp = ta.GetTextProperty()
                tp.SetFontSize(14)
                tp.BoldOn()
                tp.SetColor(*(k["color"] if k else (0.3, 0.3, 0.35)))
                ta.SetPosition(10, y0 - 18 * j)
                ren.AddViewProp(ta)
            head = vtk.vtkTextActor()
            head.SetInput(f"{scene.get('title') or 'Assembly'}   (Z up, floor grid {step:g} mm)")
            head.GetTextProperty().SetFontSize(15)
            head.GetTextProperty().SetColor(0.12, 0.13, 0.17)
            head.SetPosition(10, int(size[1] * 0.5) - 24)
            ren.AddViewProp(head)
    win.Render()
    w2i = vtk.vtkWindowToImageFilter()
    w2i.SetInput(win)
    w2i.Update()
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(png))
    writer.SetInputConnection(w2i.GetOutputPort())
    writer.Write()


if __name__ == "__main__":
    draw(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")), Path(sys.argv[2]))
