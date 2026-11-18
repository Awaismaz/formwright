"""Assembly drawing (DRW-014): an isometric view of an assembly, a BOM table and item balloons, on one sheet.

Kernel side (the drawing worker): every instance's part snapshot is placed by its 12-number placement, the whole
assembly is projected with exact hidden-line removal (visible edges only, like the isometric view of a part sheet),
and each BOM row gets a balloon with a leader to one of its instances (the centre of its placed bounding box, as seen
in the view). Balloons sit on a ring around the view in the angular order of their anchors, pushed apart so they
never overlap, and clamped inside the drawing area (clear of the BOM table and the title block).

The sheet uses the same primitives, title block and renderers (SVG / PDF / DXF) as the part sheets, so it carries
the NOT APPROVED FOR MANUFACTURE banner too. Deterministic: same assembly, same BOM, same meta = same SVG.
"""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

from aicad.drawing.layout import FRAME, SCALES, SHEETS, Group, _info_blocks, scale_label, text_width

BALLOON_R = 4.2
ROW_H = 5.2
TABLE_W = 180.0
COLS = [(0.0, 11.0, "ITEM"), (11.0, 11.0, "QTY"), (22.0, 62.0, "PART"), (84.0, 72.0, "DESIGNATION / MATERIAL"),
        (156.0, 24.0, "MAKE/BUY")]


def _fit(txt: str, w: float, size: float) -> str:
    while txt and text_width(txt, size) > w:
        txt = txt[:-2] + "…" if len(txt) > 2 else ""
    return txt


def _bom_table(rows: list[dict[str, Any]], x0: float, y_bottom: float, max_rows: int) -> tuple[Group, list[float]]:
    """The BOM table, its header at the top, growing upwards from ``y_bottom`` (ISO 7573 style, above the title
    block). Rows beyond ``max_rows`` are summarised in a last line."""
    g = Group()
    shown = rows[:max_rows]
    more = len(rows) - len(shown)
    n = len(shown) + (1 if more else 0)
    h = ROW_H * (n + 1)
    y0 = y_bottom - h
    g.rect("tb", x0, y0, TABLE_W, h)
    for cx, _w, label in COLS:
        if cx:
            g.line("tbthin", x0 + cx, y0, x0 + cx, y0 + h)
        g.text(x0 + cx + 1.2, y0 + ROW_H - 1.5, 2.1, label, font="bold", color="label", kind="bom")
    g.line("tb", x0, y0 + ROW_H, x0 + TABLE_W, y0 + ROW_H)
    for i, r in enumerate(shown):
        yy = y0 + ROW_H * (i + 2) - 1.5
        g.line("tbthin", x0, y0 + ROW_H * (i + 1), x0 + TABLE_W, y0 + ROW_H * (i + 1))
        desig = r.get("designation") or r.get("material") or ""
        vals = [str(r["item"]), str(r["qty"]), str(r["part"]), str(desig), str(r.get("make_buy") or "").upper()]
        for (cx, w, _l), v in zip(COLS, vals, strict=True):
            g.text(x0 + cx + 1.2, yy, 2.3, _fit(v, w - 2.4, 2.3), kind="bom")
    if more:
        yy = y0 + ROW_H * (len(shown) + 2) - 1.5
        g.line("tbthin", x0, y0 + ROW_H * (len(shown) + 1), x0 + TABLE_W, y0 + ROW_H * (len(shown) + 1))
        g.text(x0 + 1.2, yy, 2.3, f"… and {more} more lines: see the BOM (CSV) in the release pack", kind="bom")
    return g, [x0, y0, x0 + TABLE_W, y_bottom]


def _assemble(nodes: list[dict[str, Any]]) -> tuple[Any, list[list[float]]]:
    """The placed compound and every node's placed bounding box [xmin, ymin, zmin, xmax, ymax, zmax]."""
    from build123d import Compound

    from aicad.assembly import xform
    from aicad.assembly.geometry import _loc, load

    shapes, boxes = [], []
    for nd in nodes:
        base = load(nd["step"])
        placed = base.moved(_loc(xform.from12(nd["T"])))
        shapes.append(placed)
        b = placed.bounding_box()
        boxes.append([b.min.X, b.min.Y, b.min.Z, b.max.X, b.max.Y, b.max.Z])
    return Compound(children=shapes), boxes


def _ring(anchors: list[tuple[int, float, float]], cx: float, cy: float, rx: float, ry: float,
          area: list[float]) -> dict[int, tuple[float, float]]:
    """Balloon centres on an ellipse around the view, in the angular order of their anchors, at least two balloon
    diameters apart (pushed along the ellipse), clamped to the drawing area."""
    if not anchors:
        return {}
    ang = sorted(((math.atan2(y - cy, x - cx), item) for item, x, y in anchors))
    need = 2.0 * BALLOON_R * 1.35
    per = 2 * math.pi * math.sqrt((rx * rx + ry * ry) / 2)
    step = need / max(per, 1e-6) * 2 * math.pi
    out_ang: list[float] = []
    for a, _item in ang:
        if out_ang and a - out_ang[-1] < step:
            a = out_ang[-1] + step
        out_ang.append(a)
    if len(out_ang) > 1 and out_ang[-1] - out_ang[0] > 2 * math.pi - step:  # wrapped round: spread evenly
        out_ang = [ang[0][0] + k * 2 * math.pi / len(ang) for k in range(len(ang))]
    pos = {}
    for (_a, item), a in zip(ang, out_ang, strict=True):
        x = min(max(cx + rx * math.cos(a), area[0] + BALLOON_R + 1), area[2] - BALLOON_R - 1)
        y = min(max(cy + ry * math.sin(a), area[1] + BALLOON_R + 1), area[3] - BALLOON_R - 1)
        pos[item] = (x, y)
    return pos


def generate(nodes: list[dict[str, Any]], rows: list[dict[str, Any]], dest: Path, meta: dict[str, Any],
             size: str = "A3") -> dict[str, Any]:
    """Write ``assembly.svg / .pdf / .dxf`` and ``assembly.json`` into ``dest``. ``nodes``: [{step, T, inst}];
    ``rows``: the BOM rows (item, qty, part, designation, material, make_buy, instances)."""
    from aicad.drawing.geometry import project, view_axes
    from aicad.drawing.render import to_dxf, to_pdf, to_svg

    t0 = time.perf_counter()
    if not nodes:
        raise ValueError("The assembly is empty.")
    comp, boxes = _assemble(nodes)
    view = project(comp, "iso", hidden=False)
    ext = view["extents"] or [0, 1, 0, 1]
    xv, up, _d = view_axes("iso")
    W, H = SHEETS[size]
    frame = [FRAME["left"], FRAME["top"], W - FRAME["right"], H - FRAME["bottom"]]
    meta = {"title": meta.get("title") or "Assembly", "drawing_no": meta.get("drawing_no") or "",
            "material": "See the BOM", "drawn_by": meta.get("drawn_by") or "", "date": meta.get("date") or "",
            "rev": meta.get("rev") or "DRAFT", "tolerance": "See the part drawings", "units": "mm",
            "source": meta.get("source") or ""}
    rows_cap = 22
    for sc in [*SCALES, (1, 200), (1, 500)]:
        s = sc[0] / sc[1]
        info, tb = _info_blocks(W, H, meta, scale_label(sc), True, [], size)
        table, tbox = _bom_table(rows, frame[2] - TABLE_W, tb[1] - 3.0, rows_cap)
        area = [frame[0] + 4.0, frame[1] + 4.0, tbox[0] - 6.0, frame[3] - 4.0]
        vw, vh = (ext[1] - ext[0]) * s, (ext[3] - ext[2]) * s
        if vw + 4 * (BALLOON_R + 10) <= area[2] - area[0] and vh + 4 * (BALLOON_R + 10) <= area[3] - area[1]:
            break
    ox = (area[0] + area[2]) / 2 - vw / 2
    oy = (area[1] + area[3]) / 2 - vh / 2

    def P(u: float, v: float) -> tuple[float, float]:
        return ox + (u - ext[0]) * s, oy + (ext[3] - v) * s

    g = Group()
    g.rect("frame", frame[0], frame[1], frame[2] - frame[0], frame[3] - frame[1])
    for pr in view["visible"]:
        kind = pr[0]
        if kind == "line":
            a, b = P(pr[1], pr[2]), P(pr[3], pr[4])
            g.line("visible", a[0], a[1], b[0], b[1])
        elif kind == "circle":
            c = P(pr[1], pr[2])
            g.circle("visible", c[0], c[1], pr[3] * s)
        elif kind == "arc":
            c = P(pr[1], pr[2])
            g.arc("visible", c[0], c[1], pr[3] * s, pr[4], pr[5])
        elif kind == "poly":
            g.poly("visible", [list(P(x, y)) for x, y in pr[1]])
    # balloons: one per BOM row that has an instance in the assembly
    idx = {nd["inst"]: k for k, nd in enumerate(nodes)}
    anchors = []
    for r in rows:
        k = next((idx[i] for i in r.get("instances") or [] if i in idx), None)
        if k is None:
            continue
        b = boxes[k]
        c = ((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2)
        u = c[0] * xv[0] + c[1] * xv[1] + c[2] * xv[2]
        v = c[0] * up[0] + c[1] * up[1] + c[2] * up[2]
        x, y = P(u, v)
        anchors.append((int(r["item"]), x, y))
    cx, cy = ox + vw / 2, oy + vh / 2
    rx = min(vw / 2 + 14.0, (area[2] - area[0]) / 2 - BALLOON_R - 2)
    ry = min(vh / 2 + 12.0, (area[3] - area[1]) / 2 - BALLOON_R - 2)
    pos = _ring(anchors, cx, cy, max(rx, 20.0), max(ry, 16.0), area)
    balloons = []
    for item, ax, ay in anchors:
        bx, by = pos[item]
        dx, dy = ax - bx, ay - by
        dist = math.hypot(dx, dy) or 1.0
        sx, sy = bx + dx / dist * BALLOON_R, by + dy / dist * BALLOON_R
        g.line("dim", sx, sy, ax, ay)
        g.fill("dim", [[ax + 0.6 * math.cos(a / 6 * 2 * math.pi), ay + 0.6 * math.sin(a / 6 * 2 * math.pi)]
                       for a in range(6)])
        g.circle("dim", bx, by, BALLOON_R)
        g.text(bx, by + 1.25, 3.5, str(item), anchor="middle", font="bold", kind="balloon")
        balloons.append({"item": item, "at": [round(bx, 3), round(by, 3)], "anchor": [round(ax, 3), round(ay, 3)]})
    g.text(area[0], frame[1] + 8.0, 3.2, "ASSEMBLY · ISOMETRIC VIEW", font="bold", kind="label")
    g.text(area[0], frame[1] + 12.5, 2.3, "BALLOON NUMBERS ARE THE ITEMS OF THE BILL OF MATERIALS. "
           "SIZES AND TOLERANCES: SEE THE PART DRAWINGS.", kind="note")
    prims = g.placed(0, 0) + table.placed(0, 0) + info.placed(0, 0)
    sheet = {"size": size, "w": W, "h": H, "scale": list(sc), "scale_txt": scale_label(sc), "iso_scale": None,
             "projection": "first", "frame": frame, "prims": prims, "views": {}, "copy": "issue"}
    dest.mkdir(parents=True, exist_ok=True)
    title = f"{meta['title']}: assembly drawing {meta['drawing_no']} rev {meta['rev']}"
    (dest / "assembly.svg").write_text(to_svg(sheet, title), encoding="utf-8", newline="\n")
    to_pdf(sheet, dest / "assembly.pdf", title)
    to_dxf(sheet, dest / "assembly.dxf")
    files = {n: (dest / n).stat().st_size for n in ("assembly.svg", "assembly.pdf", "assembly.dxf")}
    rec = {"size": size, "scale": scale_label(sc), "balloons": balloons, "rows": len(rows),
           "rows_on_sheet": min(len(rows), rows_cap), "instances": len(nodes), "files": files,
           "elapsed_s": round(time.perf_counter() - t0, 3)}
    import json

    (dest / "assembly.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec
