"""Flat-pattern sheet for sheet-metal parts (CAD-026): the developed blank with its bend lines and a bend table.

Drawn from ``out/flat.json`` (written by the build from the sheet-metal model, never re-derived here): the outline at
a standard scale, every bend's centre line (layer ``center``, labelled "B1 UP 90° R2"), the overall flat size, a bend
table (direction, angle, inside radius, K-factor, bend allowance, bend length) and notes that state the bend
allowance formula and the K-factor used. It shares the title block and renderers of the main sheet, so the SVG, PDF
and DXF (model-space outline at true size) show the same thing.
"""

from __future__ import annotations

import math
from typing import Any

from aicad.drawing.dims import fmt
from aicad.drawing.layout import (
    FRAME,
    SCALES,
    SHEETS,
    Group,
    _info_blocks,
    _wrap,
    scale_label,
    text_width,
)

TABLE_COLS = [("#", 8.0), ("DIR", 13.0), ("ANGLE", 16.0), ("R", 13.0), ("K", 11.0), ("BA", 16.0), ("LENGTH", 18.0)]
ROW_H, HEAD_H, TXT = 4.6, 5.2, 2.3
MAX_ROWS = 24


def _bend_label(b: dict[str, Any]) -> str:
    return f"B{b['n']} {b['direction']} {fmt(b['angle'])}° R{fmt(b['radius'])}"


def _dim(g: Group, a: tuple[float, float], b: tuple[float, float], off: float, txt: str, horizontal: bool) -> None:
    """A linear dimension between paper points a and b, its line ``off`` mm away (below / left for negative)."""
    from aicad.drawing.layout import ARROW, GAP, OVERSHOOT

    if horizontal:
        y = a[1] + off
        for p in (a, b):
            sgn = 1 if off > 0 else -1
            g.line("dim", p[0], p[1] + sgn * GAP, p[0], y + sgn * OVERSHOOT)
        g.line("dim", a[0], y, b[0], y)
        g.arrow((a[0], y), (a[0] + ARROW, y))
        g.arrow((b[0], y), (b[0] - ARROW, y))
        g.text((a[0] + b[0]) / 2, y - 1.0, 3.0, txt, anchor="middle", kind="dim")
    else:
        x = a[0] + off
        for p in (a, b):
            sgn = 1 if off > 0 else -1
            g.line("dim", p[0] + sgn * GAP, p[1], x + sgn * OVERSHOOT, p[1])
        g.line("dim", x, a[1], x, b[1])
        g.arrow((x, a[1]), (x, a[1] + ARROW if b[1] > a[1] else a[1] - ARROW))
        g.arrow((x, b[1]), (x, b[1] - ARROW if b[1] > a[1] else b[1] + ARROW))
        g.text(x - 1.0, (a[1] + b[1]) / 2, 3.0, txt, anchor="middle", rot=90, kind="dim")


def flat_sheet(flat: dict[str, Any], meta: dict[str, Any], revisions: list[dict[str, Any]], size: str = "A3",
               first_angle: bool = True) -> dict[str, Any]:
    """The flat-pattern sheet as layout primitives (same format as ``layout.compose``)."""
    W, H = SHEETS[size]
    bends = list(flat.get("bends") or [])
    x0b, y0b, x1b, y1b = (float(v) for v in flat["flat"]["bbox"])
    fw_, fh = x1b - x0b, y1b - y0b
    t, k = float(flat["thickness"]), float(flat["k_factor"])
    left, top = FRAME["left"] + 6.0, FRAME["top"] + 6.0
    right = W - FRAME["right"] - 6.0
    # title block (+ revision table) bottom right; bend table top right; notes bottom left
    title_meta = {**meta, "title": f"{meta.get('title') or 'Part'} (FLAT PATTERN)"}
    tb, tb_box = _info_blocks(W, H, title_meta, "", first_angle, revisions, size)
    rows = bends[:MAX_ROWS]
    tab_w = sum(w for _, w in TABLE_COLS)
    tab_h = HEAD_H + ROW_H * max(len(rows), 1) + (ROW_H if len(bends) > MAX_ROWS else 0)
    tab_x, tab_y = right - tab_w, top + 6.0
    notes = [(f"FLAT PATTERN OF THE SHEET-METAL PART, {fmt(t)} MM SHEET. DEVELOPED FROM THE MODEL: BEND ALLOWANCE "
             f"BA = ANGLE (RAD) × (R + K × T), K = {fmt(k)}."),
             "BEND LINES ARE BEND CENTRE LINES. UP / DOWN AS SEEN ON THIS VIEW.",
             "VERIFY THE K-FACTOR AND MINIMUM BEND RADIUS WITH YOUR FABRICATOR BEFORE CUTTING.",
             "NOT APPROVED FOR MANUFACTURE: A QUALIFIED ENGINEER MUST REVIEW AND APPROVE THIS DRAWING."]
    notes += [str(n).upper() for n in flat.get("notes") or []]
    note_w = tb_box[0] - left - 8.0
    lines: list[tuple[str, str]] = []
    for i, n in enumerate(notes, 1):
        for j, w in enumerate(_wrap(n, note_w - 6.0, 2.5)):
            lines.append((f"{i}." if j == 0 else "", w))
    notes_h = 6.0 + 3.6 * len(lines)
    notes_y0 = H - FRAME["bottom"] - 3.0 - notes_h
    # view area: left of the bend table, above the notes / title block, with room for two dimensions
    vx0, vy0 = left + 14.0, top + 8.0
    vx1 = tab_x - 12.0
    vy1 = min(notes_y0, tb_box[1]) - 18.0
    if vx1 - vx0 < 60:  # narrow sheet: put the view under the table instead
        vx1, vy0 = right - 4.0, tab_y + tab_h + 10.0
    sc = SCALES[-1]
    for cand in SCALES:
        s = cand[0] / cand[1]
        if fw_ * s <= vx1 - vx0 and fh * s <= vy1 - vy0:
            sc = cand
            break
    s = sc[0] / sc[1]
    tb, _ = _info_blocks(W, H, title_meta, scale_label(sc), first_angle, revisions, size)
    ox = (vx0 + vx1) / 2 - (x0b + fw_ / 2) * s
    oy = (vy0 + vy1) / 2 + (y0b + fh / 2) * s

    def P(x: float, y: float) -> tuple[float, float]:
        return ox + x * s, oy - y * s

    g = Group()
    g.rect("frame", FRAME["left"], FRAME["top"], W - FRAME["left"] - FRAME["right"], H - FRAME["top"] - FRAME["bottom"])
    view: list[dict[str, Any]] = []
    gv = Group()
    for e in flat.get("outline") or []:
        if e["type"] == "line":
            a, b = P(*e["a"]), P(*e["b"])
            gv.line("visible", a[0], a[1], b[0], b[1])
        elif e["type"] == "circle":
            c = P(*e["c"])
            gv.circle("visible", c[0], c[1], e["r"] * s)
        elif e["type"] == "arc":
            c = P(*e["c"])
            gv.arc("visible", c[0], c[1], e["r"] * s, e["a0"], e["a1"])
        else:
            gv.poly("visible", [list(P(*q)) for q in e["pts"]])
    for b in bends:
        (ax, ay), (bx, by) = b["line"]
        a, c = P(ax, ay), P(bx, by)
        gv.line("center", a[0], a[1], c[0], c[1])
    for p in gv.prims:
        view.append({**p, "view": "flat"})
    for b in bends:  # labels on paper, along the bend line, offset to one side
        (ax, ay), (bx, by) = b["line"]
        a, c = P(ax, ay), P(bx, by)
        ang = math.degrees(math.atan2(-(c[1] - a[1]), c[0] - a[0]))
        vertical = abs(abs(ang) - 90) < 45
        mx, my = (a[0] + c[0]) / 2, (a[1] + c[1]) / 2
        if vertical:
            g.text(mx - 1.2, my, 2.5, _bend_label(b), anchor="middle", rot=90, kind="note")
        else:
            g.text(mx, my - 1.2, 2.5, _bend_label(b), anchor="middle", kind="note")
    # overall flat size
    lo, hi = P(x0b, y0b), P(x1b, y1b)  # lo = bottom-left on paper, hi = top-right
    _dim(g, (lo[0], lo[1]), (hi[0], lo[1]), 10.0, fmt(round(fw_, 2)), True)
    _dim(g, (lo[0], hi[1]), (lo[0], lo[1]), -10.0, fmt(round(fh, 2)), False)
    g.text(vx0, vy0 - 2.0, 3.2, f"FLAT PATTERN  SCALE {scale_label(sc)}", font="bold", kind="label")
    # bend table
    g.text(tab_x, tab_y - 1.5, 2.8, "BEND TABLE", font="bold", kind="label")
    g.rect("tbthin", tab_x, tab_y, tab_w, tab_h)
    g.line("tbthin", tab_x, tab_y + HEAD_H, tab_x + tab_w, tab_y + HEAD_H)
    cx = tab_x
    for i, (lab, w) in enumerate(TABLE_COLS):
        if i:
            g.line("tbthin", cx, tab_y, cx, tab_y + tab_h)
        g.text(cx + 1.0, tab_y + 3.7, 2.0, lab, font="bold", color="label", kind="table")
        cx += w
    for r, b in enumerate(rows):
        yy = tab_y + HEAD_H + ROW_H * r + 3.4
        vals = [str(b["n"]), b["direction"], f"{fmt(b['angle'])}°", fmt(b["radius"]), fmt(b["k"]),
                fmt(round(b["ba"], 3)), fmt(round(b["span"], 2))]
        cx = tab_x
        for (_lab, w), v in zip(TABLE_COLS, vals, strict=True):
            while v and text_width(v, TXT) > w - 2.0:
                v = v[:-1]
            g.text(cx + 1.0, yy, TXT, v, kind="table")
            cx += w
    if not rows:
        g.text(tab_x + 1.0, tab_y + HEAD_H + 3.4, TXT, "No bends", kind="table")
    if len(bends) > MAX_ROWS:
        g.text(tab_x + 1.0, tab_y + HEAD_H + ROW_H * len(rows) + 3.4, TXT,
               f"+ {len(bends) - MAX_ROWS} more bends (see the DXF)", kind="table")
    sizes = flat["flat"]
    g.text(tab_x, tab_y + tab_h + 4.5, 2.3, f"FLAT {fmt(round(sizes['size'][0], 2))} × {fmt(round(sizes['size'][1], 2))} MM"
           f"  ·  T {fmt(t)}  ·  {len(bends)} BEND(S)", kind="table")
    # notes
    g.text(left - 2.0, notes_y0 + 3.6, 2.6, "NOTES", font="bold", kind="note")
    for i, (num_, ln) in enumerate(lines):
        yy = notes_y0 + 6.0 + 3.6 * (i + 1) - 0.8
        if num_:
            g.text(left - 2.0, yy, 2.5, num_, kind="note")
        g.text(left + 3.0, yy, 2.5, ln, kind="note")
    prims = view + g.prims + tb.prims
    return {"w": W, "h": H, "size": size, "prims": prims, "scale": sc, "scale_txt": scale_label(sc),
            "copy": "issue", "flat": {"scale": scale_label(sc), "size": [round(fw_, 6), round(fh, 6)],
                                       "bends": len(bends), "table_rows": len(rows),
                                       "view_box": [round(min(lo[0], hi[0]), 3), round(min(lo[1], hi[1]), 3),
                                                    round(max(lo[0], hi[0]), 3), round(max(lo[1], hi[1]), 3)]}}


def write(flat: dict[str, Any], dest: Any, meta: dict[str, Any], revisions: list[dict[str, Any]], size: str,
          first_angle: bool) -> dict[str, Any]:
    """flat_sheet.svg / .pdf / .dxf in ``dest``; returns the record for drawing.json."""
    from aicad.drawing.render import to_dxf, to_pdf, to_svg

    sheet = flat_sheet(flat, meta, revisions, size, first_angle)
    title = f"{meta.get('title') or 'Part'}, flat pattern {meta.get('drawing_no', '')}".strip()
    (dest / "flat_sheet.svg").write_text(to_svg(sheet, title), encoding="utf-8", newline="\n")
    to_pdf(sheet, dest / "flat_sheet.pdf", title)
    to_dxf(sheet, dest / "flat_sheet.dxf")
    return {**sheet["flat"], "files": ["flat_sheet.svg", "flat_sheet.pdf", "flat_sheet.dxf"],
            "thickness": flat["thickness"], "k_factor": flat["k_factor"],
            "table": [{k: b[k] for k in ("n", "name", "direction", "angle", "radius", "k", "ba", "span")}
                      for b in flat.get("bends") or []]}
