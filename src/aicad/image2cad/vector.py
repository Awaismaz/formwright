"""Vector PDF drawing -> read spec (deterministic, no AI).

1. Characters with their exact positions come from pdfminer.six (MIT). They are regrouped into text runs by
   baseline and direction (so rotated dimension texts read correctly and neighbouring callouts stay apart).
2. Runs that fully parse as dimension callouts (``tokens.parse``) become dimensions; sentences and notes do not.
3. The title block is found from its field labels (TITLE, SCALE, UNITS ...); its runs are never dimensions and
   give the drawing scale, units and projection when stated.
4. Views: outline strokes (the dominant thick line weight) are clustered into regions. Labels such as
   "SECTION A-A" or "ISOMETRIC VIEW" name a region; each dimension is associated with its nearest region.
5. Cross-check: each view's drawn size times the stated scale is compared with its largest horizontal and vertical
   dimension. A match is evidence for the scale and units; it never replaces a confirmed reference dimension.

Positions are returned normalised to the displayed page: x, y in 0..1 from the top-left corner (page /Rotate
applied), so the review screen pins them on the raster preview directly.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from aicad.image2cad import InputError
from aicad.image2cad.tokens import parse

PT_MM = 25.4 / 72.0
MAX_CHARS = 60_000

_TB_LABELS = re.compile(
    r"^(TITLE|DRAWN(?: BY)?|CHECKED(?: BY)?|APPROVED(?: BY)?|SCALE|MATERIAL|DRAWING NO\.?|DWG\.? NO\.?|SHEET|REV\.?|"
    r"REVISION|DATE|UNITS|PROJECTION|GENERAL TOLERANCES|TOLERANCES?|DESCRIPTION|BY|FINISH|WEIGHT|MASS|PART NO\.?|"
    r"SIZE|QTY|DESIGNED(?: BY)?|COMPANY|PART NAME|ITEM)$")
_VIEW_LABEL = re.compile(
    r"^(?:(?:FRONT|TOP|BOTTOM|LEFT|RIGHT|REAR|BACK|SIDE|END|PLAN|ISOMETRIC|ISO|AUXILIARY)(?:\s+(?:SIDE\s+)?"
    r"(?:VIEW|ELEVATION))?|(?:SECTION|DETAIL|VIEW)\s+[A-Z](?:\s*-\s*[A-Z])?|ELEVATION)(?:\s+SCALE\s+\S+)?$")
_UNITS_NOTE = [(re.compile(r"\b(MILLIMET(?:RE|ER)S?|IN MM)\b"), "mm"), (re.compile(r"\bINCH(?:ES)?\b|\bIN INCHES\b"), "in")]
_PROJ_NOTE = [(re.compile(r"\bFIRST[- ]ANGLE\b"), "first"), (re.compile(r"\bTHIRD[- ]ANGLE\b"), "third")]


# ----------------------------------------------------------------------------- pdf objects
def _walk(o: Any) -> Any:
    from pdfminer.layout import LTChar, LTCurve

    if isinstance(o, (LTChar, LTCurve)):
        yield o
    elif hasattr(o, "__iter__"):
        for c in o:
            yield from _walk(c)


def _load(path: Path) -> tuple[Any, list[Any], list[Any]]:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTChar
    from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
    from pdfminer.pdfparser import PDFSyntaxError

    try:
        page = next(iter(extract_pages(str(path), maxpages=1, laparams=LAParams())), None)
    except (PDFPasswordIncorrect, PDFEncryptionError):
        raise InputError("This PDF is password-protected. Upload an unprotected copy.") from None
    except PDFSyntaxError:
        raise InputError("The PDF could not be read. It may be damaged.") from None
    if page is None:
        raise InputError("The PDF has no pages.")
    chars, curves = [], []
    for o in _walk(page):
        (chars if isinstance(o, LTChar) else curves).append(o)
        if len(chars) > MAX_CHARS:
            raise InputError("The PDF page holds too much text to be a drawing.")
    return page, chars, curves


# ----------------------------------------------------------------------------- text runs
def _runs(chars: list[Any]) -> list[dict[str, Any]]:
    """Group characters into runs: same direction, same baseline, small gaps."""
    items = []
    for c in chars:
        a, b = c.matrix[0], c.matrix[1]
        deg = math.degrees(math.atan2(b, a)) % 360
        q = round(deg / 90) * 90 % 360
        ang = q if abs(((deg - q + 180) % 360) - 180) < 3 else round(deg) % 360
        r = math.radians(ang)
        ux, uy = math.cos(r), math.sin(r)
        x0, y0, x1, y1 = c.bbox
        fs = (y1 - y0) if abs(ux) >= abs(uy) else (x1 - x0)
        fs = max(fs, 0.5)
        e, f = c.matrix[4], c.matrix[5]
        items.append({"ch": c.get_text(), "ang": ang, "s": e * ux + f * uy, "t": -e * uy + f * ux, "adv": c.adv,
                      "fs": fs, "bbox": c.bbox, "font": c.fontname or ""})
    runs: list[dict[str, Any]] = []
    by_ang: dict[int, list[dict[str, Any]]] = {}
    for it in items:
        by_ang.setdefault(it["ang"], []).append(it)
    for ang, its in by_ang.items():
        its.sort(key=lambda i: (i["t"], i["s"]))
        lines: list[list[dict[str, Any]]] = []
        for it in sorted(its, key=lambda i: i["t"]):
            for ln in lines:
                if abs(ln[0]["t"] - it["t"]) < 0.3 * max(it["fs"], ln[0]["fs"]) and \
                        max(it["fs"], ln[0]["fs"]) / min(it["fs"], ln[0]["fs"]) < 1.6:
                    ln.append(it)
                    break
            else:
                lines.append([it])
        for ln in lines:
            ln.sort(key=lambda i: i["s"])
            cur: list[dict[str, Any]] = []
            for it in ln:
                if cur:
                    prev = cur[-1]
                    gap = it["s"] - (prev["s"] + prev["adv"])
                    fs = max(prev["fs"], it["fs"])
                    if gap > 0.75 * fs or gap < -0.5 * fs:
                        runs.append(_run(cur, ang))
                        cur = []
                    elif gap > 0.18 * fs and prev["ch"] != " " and it["ch"] != " ":
                        it = {**it, "space": True}
                cur.append(it)
            if cur:
                runs.append(_run(cur, ang))
    return [r for r in runs if r["text"]]


def _run(its: list[dict[str, Any]], ang: int) -> dict[str, Any]:
    text = "".join((" " if i.get("space") else "") + i["ch"] for i in its)
    xs0, ys0, xs1, ys1 = zip(*(i["bbox"] for i in its), strict=True)
    fonts = {i["font"] for i in its if i["ch"].strip()}
    style = "italic" if any("Oblique" in f or "Italic" in f for f in fonts) else \
        "bold" if any("Bold" in f for f in fonts) else "regular"
    return {"text": " ".join(text.split()), "bbox": [min(xs0), min(ys0), max(xs1), max(ys1)], "ang": ang,
            "fs": sorted(i["fs"] for i in its)[len(its) // 2], "style": style}


# ----------------------------------------------------------------------------- geometry helpers
def _centre(b: list[float]) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _inside(p: tuple[float, float], b: list[float]) -> bool:
    return b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]


def _box_dist(p: tuple[float, float], b: list[float]) -> float:
    dx = max(b[0] - p[0], 0.0, p[0] - b[2])
    dy = max(b[1] - p[1], 0.0, p[1] - b[3])
    return math.hypot(dx, dy)


def _gap(a: list[float], b: list[float]) -> float:
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def _union(a: list[float], b: list[float]) -> list[float]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _length(o: Any) -> float:
    pts = getattr(o, "pts", None) or []
    if len(pts) >= 2:
        return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    return 2 * (o.width + o.height)


# ----------------------------------------------------------------------------- title block
def _title_block(runs: list[dict[str, Any]]) -> tuple[list[float] | None, list[dict[str, Any]]]:
    labels = [r for r in runs if _TB_LABELS.match(r["text"].upper()) and r["ang"] == 0]
    if len(labels) < 3:
        return None, []
    # the title block is the densest group of labels: keep labels near the label median
    cx = sorted(_centre(r["bbox"])[0] for r in labels)[len(labels) // 2]
    cy = sorted(_centre(r["bbox"])[1] for r in labels)[len(labels) // 2]
    span = max(max(r["bbox"][2] for r in labels) - min(r["bbox"][0] for r in labels), 1.0)
    near = [r for r in labels if math.dist(_centre(r["bbox"]), (cx, cy)) < span]
    if len(near) < 3:
        near = labels
    box = near[0]["bbox"]
    for r in near[1:]:
        box = _union(box, r["bbox"])
    fs = sorted(r["fs"] for r in near)[len(near) // 2]
    box = [box[0] - 1.5 * fs, box[1] - 3.0 * fs, box[2] + 8.0 * fs, box[3] + 1.5 * fs]
    return box, near


def _field(label: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Value of a title-block field: the nearest run below the label (same column) or to its right."""
    lx0, ly0, lx1, ly1 = label["bbox"]
    fs = label["fs"]
    best, bd = None, 1e9
    for r in runs:
        if r is label or r["ang"] != 0 or _TB_LABELS.match(r["text"].upper()):
            continue
        x0, y0, _x1, y1 = r["bbox"]
        below = y1 <= ly0 + 0.5 * fs and ly0 - y1 < 3.5 * fs and abs(x0 - lx0) < 4 * fs
        right = x0 >= lx1 - 0.5 * fs and x0 - lx1 < 6 * fs and abs((y0 + y1) / 2 - (ly0 + ly1) / 2) < 0.8 * fs
        if below or right:
            d = (ly0 - y1) + abs(x0 - lx0) * 0.2 if below else (x0 - lx1) + 1.0
            if d < bd:
                best, bd = r, d
    return best


# ----------------------------------------------------------------------------- views
def _views(curves: list[Any], page_box: list[float], tb: list[float] | None) -> list[dict[str, Any]]:
    W, H = page_box[2] - page_box[0], page_box[3] - page_box[1]
    diag = math.hypot(W, H)
    edge = 0.03
    cands = []
    for o in curves:
        if not getattr(o, "stroke", True):
            continue
        b = list(o.bbox)
        if (b[2] - b[0]) > 0.6 * W or (b[3] - b[1]) > 0.6 * H:
            continue  # frame and border lines
        c = _centre(b)
        if tb and _inside(c, tb):
            continue
        fx0, fy0 = (b[0] - page_box[0]) / W, (b[1] - page_box[1]) / H
        fx1, fy1 = (b[2] - page_box[0]) / W, (b[3] - page_box[1]) / H
        if fx1 < edge or fy1 < edge or fx0 > 1 - edge or fy0 > 1 - edge:
            continue  # zone marks in the margin
        lw = round(float(getattr(o, "linewidth", 0) or 0), 2)
        cands.append((b, lw, _length(o)))
    if not cands:
        return []
    by_w: dict[float, float] = {}
    for _, lw, ln in cands:
        by_w[lw] = by_w.get(lw, 0.0) + ln
    top = max(by_w.values())
    outline_w = max(w for w, ln in by_w.items() if ln >= 0.2 * top)
    segs = [b for b, lw, _ in cands if 0.9 * outline_w <= lw <= 1.15 * outline_w + 1e-6]
    # union-find on bounding boxes
    parent = list(range(len(segs)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    tol = 0.008 * diag
    order = sorted(range(len(segs)), key=lambda i: segs[i][0])
    for k, i in enumerate(order):
        for j in order[k + 1:]:
            if segs[j][0] > segs[i][2] + tol:
                break
            if _gap(segs[i], segs[j]) <= tol:
                parent[find(i)] = find(j)
    groups: dict[int, list[float]] = {}
    counts: dict[int, int] = {}
    for i, b in enumerate(segs):
        r = find(i)
        groups[r] = _union(groups[r], b) if r in groups else list(b)
        counts[r] = counts.get(r, 0) + 1
    boxes = [b for r, b in groups.items() if math.hypot(b[2] - b[0], b[3] - b[1]) >= 0.02 * diag]
    # merge boxes nested in another (e.g. a hole outline drawn apart from its boundary)
    boxes.sort(key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))
    kept: list[list[float]] = []
    for b in boxes:
        if not any(k[0] <= b[0] and k[1] <= b[1] and k[2] >= b[2] and k[3] >= b[3] for k in kept):
            kept.append(b)
    # reading order: top to bottom, then left to right
    kept.sort(key=lambda b: (-round(b[3] / (0.05 * H)), b[0]))
    return [{"id": f"v{i + 1}", "pbox": b} for i, b in enumerate(kept)]


def _name_views(views: list[dict[str, Any]], runs: list[dict[str, Any]], diag: float) -> list[dict[str, Any]]:
    labels = [r for r in runs if _VIEW_LABEL.match(r["text"].upper())]
    for lab in labels:
        c = _centre(lab["bbox"])
        best = min(views, key=lambda v: _box_dist(c, v["pbox"]), default=None)
        if best is not None and _box_dist(c, best["pbox"]) < 0.08 * diag and \
                (not best.get("label") or _box_dist(c, best["pbox"]) < best["_ld"]):
            best["label"], best["_ld"], best["_lrun"] = lab["text"], _box_dist(c, best["pbox"]), lab
    for v in views:
        lab = (v.get("label") or "").upper()
        v["kind"] = ("iso" if lab.startswith("ISO") else "section" if lab.startswith("SECTION") else
                     "detail" if lab.startswith("DETAIL") else "ortho")
        v.pop("_ld", None)
    # arrangement: an orthographic view with neighbours both above/below and beside it is the likely front
    ortho = [v for v in views if v["kind"] == "ortho"]
    for v in ortho:
        b = v["pbox"]
        v["_vert"] = [w for w in ortho if w is not v and min(b[2], w["pbox"][2]) - max(b[0], w["pbox"][0]) > 0.3 * (b[2] - b[0])]
        v["_horz"] = [w for w in ortho if w is not v and min(b[3], w["pbox"][3]) - max(b[1], w["pbox"][1]) > 0.3 * (b[3] - b[1])]
    hub = None
    if len(ortho) >= 2:
        scored = sorted(ortho, key=lambda v: (-(bool(v["_vert"]) + bool(v["_horz"])), -len(v["_vert"]) - len(v["_horz"]),
                                              -(v["pbox"][2] - v["pbox"][0]) * (v["pbox"][3] - v["pbox"][1])))
        hub = scored[0]
    for i, v in enumerate(views):
        v["name"] = re.sub(r"\s+SCALE\s+\S+$", "", v.get("label") or "") or f"View {i + 1}"
        if hub is not None and v["kind"] == "ortho" and not v.get("label"):
            if v is hub:
                v["place"] = "centre of the layout"
            else:
                hb, b = hub["pbox"], v["pbox"]
                hc, c = _centre(hb), _centre(b)
                if v in hub["_vert"]:
                    v["place"] = "above the centre view" if c[1] > hc[1] else "below the centre view"
                elif v in hub["_horz"]:
                    v["place"] = "left of the centre view" if c[0] < hc[0] else "right of the centre view"
    for v in views:
        v.pop("_vert", None)
        v.pop("_horz", None)
    if hub is not None:
        hub["suggest_front"] = True
    return views


# ----------------------------------------------------------------------------- main
def read_pdf(path: Path) -> dict[str, Any]:
    page, chars, curves = _load(path)
    pb = list(page.bbox)
    W, H = pb[2] - pb[0], pb[3] - pb[1]
    rot = int(getattr(page, "rotate", 0) or 0) % 360
    diag = math.hypot(W, H)

    def norm(x: float, y: float) -> tuple[float, float]:
        nx, ny = (x - pb[0]) / W, 1 - (y - pb[1]) / H
        if rot == 90:
            return 1 - ny, nx
        if rot == 180:
            return 1 - nx, 1 - ny
        if rot == 270:
            return ny, 1 - nx
        return nx, ny

    def nbox(b: list[float]) -> list[float]:
        (ax, ay), (bx, by) = norm(b[0], b[1]), norm(b[2], b[3])
        return [round(min(ax, bx), 5), round(min(ay, by), 5), round(max(ax, bx), 5), round(max(ay, by), 5)]

    runs = _runs(chars)
    tb, tb_labels = _title_block(runs)
    views = _name_views(_views(curves, pb, tb), runs, diag)
    label_runs = {id(v["_lrun"]) for v in views if v.get("_lrun")}

    # title block fields
    title: dict[str, str] = {}
    tb_runs = [r for r in runs if tb and _inside(_centre(r["bbox"]), tb)]
    for lab in tb_labels:
        val = _field(lab, tb_runs)
        if val is not None:
            title.setdefault(lab["text"].upper().rstrip(".").replace("DRAWN BY", "DRAWN").strip(), val["text"])
    scale = units = projection = None
    if title.get("SCALE"):
        d = parse(title["SCALE"])
        if d and d["kind"] == "scale":
            scale = {"ratio": d["ratio"], "text": title["SCALE"], "evidence": "Title block, SCALE field"}
    if title.get("UNITS"):
        u = title["UNITS"].lower().strip(". ")
        if u in ("mm", "millimetres", "millimeters", "millimetre", "millimeter"):
            units = {"value": "mm", "evidence": "Title block, UNITS field"}
        elif u in ("in", "inch", "inches", '"'):
            units = {"value": "in", "evidence": "Title block, UNITS field"}

    dims: list[dict[str, Any]] = []
    unparsed: list[dict[str, Any]] = []
    for r in runs:
        c = _centre(r["bbox"])
        up = r["text"].upper()
        if tb and _inside(c, tb):
            continue
        if id(r) in label_runs:
            m = re.search(r"SCALE\s+(\S+)", up)
            if m:
                for v in views:
                    if v.get("_lrun") is r:
                        d = parse(m.group(1))
                        if d and d["kind"] == "scale":
                            v["scale"] = d["ratio"]
            continue
        if units is None:
            for rx, u in _UNITS_NOTE:
                if rx.search(up):
                    units = {"value": u, "evidence": f'Drawing note: "{r["text"][:80]}"'}
        if projection is None:
            for rx, p in _PROJ_NOTE:
                if rx.search(up):
                    projection = {"value": p, "evidence": f'Drawing note: "{r["text"][:80]}"'}
        d = parse(r["text"])
        if d is None:
            if len(r["text"]) <= 14 and re.search(r"\d", r["text"]) and not re.fullmatch(r"\d+\.", r["text"]):
                nx, ny = norm(*c)
                unparsed.append({"text": r["text"], "x": round(nx, 5), "y": round(ny, 5)})
            continue
        if d["kind"] == "scale":
            if scale is None:
                scale = {"ratio": d["ratio"], "text": d["text"], "evidence": "Scale text on the sheet"}
            continue
        nx, ny = norm(*c)
        # nearest view
        ranked = sorted(views, key=lambda v: _box_dist(c, v["pbox"]))
        view = ranked[0] if ranked and _box_dist(c, ranked[0]["pbox"]) < 0.12 * diag else None
        alt = None
        if view is not None and len(ranked) > 1:
            d0, d1 = _box_dist(c, ranked[0]["pbox"]), _box_dist(c, ranked[1]["pbox"])
            if d1 - d0 < 3.0 / PT_MM and d0 > 0:
                alt = ranked[1]["id"]
        ang = (r["ang"] + rot) % 360
        direction = "horizontal" if ang in (0, 180) else "vertical" if ang in (90, 270) else "aligned"
        dims.append({**d, "x": round(nx, 5), "y": round(ny, 5), "box": nbox(r["bbox"]), "rot": r["ang"],
                     "dir": direction if d["kind"] == "linear" else None, "view": view["id"] if view else None,
                     "view_alt": alt, "confidence": 1.0, "source": "text", "style": r["style"]})
    dims.sort(key=lambda d: (d["view"] or "zz", d["y"], d["x"]))
    for i, d in enumerate(dims):
        d["id"] = f"d{i + 1}"

    # drawn size and scale cross-check
    checks = []
    for v in views:
        b = v["pbox"]
        w_mm, h_mm = (b[2] - b[0]) * PT_MM, (b[3] - b[1]) * PT_MM
        if rot in (90, 270):
            w_mm, h_mm = h_mm, w_mm
        v["drawn_mm"] = [round(w_mm, 2), round(h_mm, 2)]
        if v["kind"] == "iso":
            continue
        ratio = v.get("scale") or (scale or {}).get("ratio")
        for axis, drawn, want in (("width", w_mm, "horizontal"), ("height", h_mm, "vertical")):
            cand = [d for d in dims if d["view"] == v["id"] and d["kind"] == "linear" and d["dir"] == want]
            if not cand:
                continue
            big = max(cand, key=lambda d: d["value"])
            res: dict[str, Any] = {"view": v["id"], "axis": axis, "drawn_mm": round(drawn, 2), "dim": big["id"],
                                   "value": big["value"]}
            if ratio:
                k = ratio[1] / ratio[0]
                real_mm = drawn * k
                for u, real in (("mm", real_mm), ("in", real_mm / 25.4)):
                    if units and units["value"] != u:
                        continue
                    if abs(real - big["value"]) <= max(0.01 * big["value"], 0.5 if u == "mm" else 0.02):
                        res["match"], res["units"] = True, u
                        break
                else:
                    res["match"] = False
                    # a dimension larger than the drawn view cannot be right at this scale; smaller ones are just
                    # not the overall size
                    u = (units or {}).get("value", "mm")
                    res["conflict"] = big["value"] > (real_mm if u == "mm" else real_mm / 25.4) * 1.02
                res["at_scale"] = round(real_mm, 2)
            else:
                res["implied_scale"] = round(big["value"] / drawn, 4) if drawn else None
            checks.append(res)
    for v in views:
        v["box"] = nbox(v.pop("pbox"))
        lr = v.pop("_lrun", None)
        if lr is not None:
            lx, ly = norm(*_centre(lr["bbox"]))
            v["label_xy"] = [round(lx, 5), round(ly, 5)]
    if units is None:
        hits = {c.get("units") for c in checks if c.get("match")}
        if len(hits) == 1:
            u = hits.pop()
            units = {"value": u, "evidence": "Drawn sizes at the stated scale match the dimensions in "
                                              + ("millimetres" if u == "mm" else "inches"), "inferred": True}
    paper = [W * PT_MM, H * PT_MM] if rot in (0, 180) else [H * PT_MM, W * PT_MM]
    return {"method": "vector", "paper_mm": [round(paper[0], 1), round(paper[1], 1)], "rotate": rot,
            "text_runs": len(runs), "chars": len(chars), "dims": dims, "views": views, "title": title,
            "title_block": nbox(tb) if tb else None, "scale": scale, "units": units, "projection": projection,
            "unparsed": unparsed[:40], "checks": checks}
