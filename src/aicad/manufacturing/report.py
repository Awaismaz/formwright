"""Manufacturability report (MFG-018): printable HTML and PDF, tied to model features and highlighted views.

Views are rendered from the exact face tessellation in `topo.json` (orthographic isometric, z-buffered),
with each finding's faces highlighted, so every finding links finding → face ids / feature → view.
"""

from __future__ import annotations

import base64
import html
import io
import itertools
from pathlib import Path
from typing import Any

import numpy as np

from aicad.manufacturing.rules import PROCESS_LABEL

SEV_COLOR = {"critical": "#c62828", "warning": "#b26a00", "info": "#1f5fa8"}
MAX_VIEWS = 12
SEV_RANK = {"critical": 0, "warning": 1, "info": 2}


# ----------------------------------------------------------------------------- views
def render_view(topo: dict[str, Any], highlight: list[int] | None = None, px: int = 520,
                view: tuple[float, float, float] = (1.0, -1.0, 0.8), focus: bool = False) -> bytes:
    """PNG of the part (orthographic iso, z-buffered, with model edges) with the given topo face ids highlighted.
    ``focus`` zooms onto the highlighted faces (with surrounding context) so a small feature is visible."""
    ss = 2  # supersampling for anti-aliasing
    W, H = px * ss, int(px * 0.75) * ss
    hl = set(highlight or [])
    cam = np.array(view, dtype=float)
    cam /= np.linalg.norm(cam)
    right = np.cross(-cam, [0.0, 0.0, 1.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, -cam)
    faces = [f for f in topo.get("faces", []) if f.get("idx")]
    img = np.full((H, W, 3), 255.0)
    if not faces:
        return _png(img, px, ss)
    allp = np.vstack([np.array(f["pos"], dtype=float).reshape(-1, 3) for f in faces])
    sx, sy = allp @ right, allp @ up
    span = max(float(sx.max() - sx.min()) / (W * 0.88), float(sy.max() - sy.min()) / (H * 0.88), 1e-9)
    cx, cy = float(sx.max() + sx.min()) / 2, float(sy.max() + sy.min()) / 2
    hfaces = [f for f in faces if f["id"] in hl]
    if focus and hfaces:
        hp = np.vstack([np.array(f["pos"], dtype=float).reshape(-1, 3) for f in hfaces])
        hx, hy = hp @ right, hp @ up
        w = max(2.4 * float(np.ptp(hx)), 0.3 * float(np.ptp(sx)))
        h = max(2.4 * float(np.ptp(hy)), 0.3 * float(np.ptp(sy)))
        span = max(min(w / (W * 0.88), span), min(h / (H * 0.88), span), 1e-9)
        cx, cy = float(hx.max() + hx.min()) / 2, float(hy.max() + hy.min()) / 2

    def proj(p: np.ndarray) -> np.ndarray:
        return np.stack([(p @ right - cx) / span + W / 2, H / 2 - (p @ up - cy) / span, p @ cam], axis=-1)

    zbuf = np.full((H, W), -np.inf)
    base, hcol = np.array([200.0, 205.0, 212.0]), np.array([47.0, 163.0, 107.0])
    for f in faces:
        pos = np.array(f["pos"], dtype=float).reshape(-1, 3)
        idx = np.array(f["idx"], dtype=int).reshape(-1, 3)
        tri3 = pos[idx]
        n = np.cross(tri3[:, 1] - tri3[:, 0], tri3[:, 2] - tri3[:, 0])
        nn = np.linalg.norm(n, axis=1)
        col = hcol if f["id"] in hl else base
        for t, nv, ln in zip(proj(tri3), n, nn, strict=True):
            if ln < 1e-12:
                continue
            shade = 0.45 + 0.55 * abs(float(nv @ cam) / ln)
            x0, x1 = max(int(t[:, 0].min()), 0), min(int(t[:, 0].max()) + 1, W - 1)
            y0, y1 = max(int(t[:, 1].min()), 0), min(int(t[:, 1].max()) + 1, H - 1)
            if x1 < x0 or y1 < y0:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            (ax, ay, az), (bx, by, bz), (qx, qy, qz) = t
            den = (by - qy) * (ax - qx) + (qx - bx) * (ay - qy)
            if abs(den) < 1e-12:
                continue
            w1 = ((by - qy) * (gx - qx) + (qx - bx) * (gy - qy)) / den
            w2 = ((qy - ay) * (gx - qx) + (ax - qx) * (gy - qy)) / den
            w3 = 1 - w1 - w2
            inside = (w1 >= -1e-6) & (w2 >= -1e-6) & (w3 >= -1e-6)
            z = w1 * az + w2 * bz + w3 * qz
            zb = zbuf[y0:y1 + 1, x0:x1 + 1]
            m = inside & (z > zb)
            zb[m] = z[m]
            img[y0:y1 + 1, x0:x1 + 1][m] = col * shade
    tol = 0.004 * float(np.linalg.norm(allp.max(axis=0) - allp.min(axis=0))) / span
    for e in topo.get("edges", []):
        pts = proj(np.array(e["pts"], dtype=float).reshape(-1, 3))
        for a, b in itertools.pairwise(pts):
            k = max(2, int(np.hypot(*(b[:2] - a[:2]))) + 1)
            s = np.linspace(0, 1, k)[:, None]
            q = a + (b - a) * s
            xi, yi = q[:, 0].astype(int), q[:, 1].astype(int)
            ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
            xi, yi, zq = xi[ok], yi[ok], q[ok, 2]
            vis = zq >= zbuf[yi, xi] - tol
            for dx in (0, 1):
                img[yi[vis], np.minimum(xi[vis] + dx, W - 1)] = (40, 46, 56)
    return _png(img, px, ss)


def _png(img: np.ndarray, px: int, ss: int) -> bytes:
    from PIL import Image

    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    if ss > 1:
        im = im.resize((px, im.height // ss), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


ISO = np.array([1.0, -1.0, 0.8])


def _facing(topo: dict[str, Any], ids: list[int]) -> tuple[float, float, float]:
    """A view direction that looks at the highlighted faces (their area-weighted outward normal, tilted towards the
    standard isometric so the part stays recognisable)."""
    hl = set(ids)
    n = np.zeros(3)
    for f in topo.get("faces", []):
        if f["id"] not in hl or not f.get("idx"):
            continue
        pos = np.array(f["pos"], dtype=float).reshape(-1, 3)
        tri = pos[np.array(f["idx"], dtype=int).reshape(-1, 3)]
        n += np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]).sum(axis=0)
    iso = ISO / np.linalg.norm(ISO)
    if np.linalg.norm(n) < 1e-9:
        return tuple(iso)  # type: ignore[return-value]
    v = n / np.linalg.norm(n) + 0.45 * iso
    if abs(float(v[2])) > 0.98 * float(np.linalg.norm(v)):  # straight down an axis: keep some tilt
        v = v + np.array([0.3, -0.3, 0.0])
    return tuple(v / np.linalg.norm(v))  # type: ignore[return-value]


def _views(a: dict[str, Any], topo: dict[str, Any] | None) -> tuple[bytes | None, dict[str, bytes]]:
    if not topo:
        return None, {}
    overview = render_view(topo, [], 640)
    nfaces = len(topo.get("faces", []))
    out: dict[str, bytes] = {}
    for f in _shown(a)[0]:
        if len(out) >= MAX_VIEWS:
            break
        if f["faces"] and len(f["faces"]) < max(2, 0.6 * nfaces):
            out[f["id"]] = render_view(topo, f["faces"], 480, view=_facing(topo, f["faces"]), focus=True)
    return overview, out


# ----------------------------------------------------------------------------- helpers
def _e(s: Any) -> str:
    return html.escape("" if s is None else str(s))


def _money(v: float | None, cur: str) -> str:
    return "-" if v is None else f"{cur} {v:,.2f}"


def _summary(a: dict[str, Any]) -> dict[str, int]:
    return a.get("summary") or a["chk13"]["counts"]


def _counts(a: dict[str, Any]) -> str:
    c = _summary(a)
    pl = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
    return f"{c['critical']} critical, {pl(c['warning'], 'warning')}, {pl(c['info'], 'note')}"


def _shown(a: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(findings of the shortlisted processes, findings of the other screens)."""
    scr = a.get("screens") or {}

    def shown(f: dict[str, Any]) -> bool:
        return f["severity"] == "critical" or scr.get(f["process"], {}).get("shown", True) or any(
            scr.get(x, {}).get("shown") for x in f.get("also") or [])

    return [f for f in a["findings"] if shown(f)], [f for f in a["findings"] if not shown(f)]


def _sections(main: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Process sections, the ones holding a critical finding first."""
    worst = {k: min((SEV_RANK[f["severity"]] for f in main if f["process"] == k), default=9) for k in PROCESS_LABEL}
    return sorted(PROCESS_LABEL.items(), key=lambda kv: (worst[kv[0]], list(PROCESS_LABEL).index(kv[0])))


def where(f: dict[str, Any]) -> str:
    """Feature name from the design tree, else a plain geometric description; never face ids."""
    return ", ".join(f.get("features") or []) or f.get("where") or "whole part"


def _model_line(a: dict[str, Any]) -> str:
    b = a.get("build") or {}
    rev = b.get("model_rev")
    bid = str(b.get("build_id") or "")
    return (f"model rev {rev}" if rev else "model") + (f" · build …{bid[-8:]}" if bid else "") + \
        f" · analysed {a['generated_at'].replace('T', ' ').replace('Z', ' UTC')}"


# ----------------------------------------------------------------------------- HTML
CSS = """
body{font:13px/1.45 -apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1d2733;margin:0;background:#fff}
.wrap{max-width:980px;margin:0 auto;padding:28px}
h1{font-size:22px;margin:0}h2{font-size:15px;margin:26px 0 8px;border-bottom:2px solid #1f5fa8;padding-bottom:4px}
.banner{background:#fff4e5;border:1px solid #f0b45c;color:#7a4b00;padding:8px 12px;border-radius:6px;font-weight:600}
.meta{color:#566270;font-size:12px}.lvl{display:inline-block;font-size:11px;padding:1px 7px;border-radius:9px;
background:#e8eef7;color:#1f5fa8;font-weight:600}
table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #d6dbe1;padding:5px 7px;text-align:left;
vertical-align:top}th{background:#f2f4f7}td.id{white-space:nowrap;font-family:monospace;font-size:11px}
.f{border:1px solid #d6dbe1;border-left:4px solid #999;border-radius:6px;padding:10px 12px;margin:10px 0;
display:flex;gap:14px;page-break-inside:avoid}.f img{width:260px;height:auto;border:1px solid #e3e6ea;border-radius:4px}
.sev{font-size:11px;font-weight:700;text-transform:uppercase}.small{font-size:11px;color:#566270}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media print{.wrap{padding:0}h2{page-break-after:avoid}}
"""


def build_html(a: dict[str, Any], project_name: str, topo: dict[str, Any] | None) -> str:
    overview, views = _views(a, topo)
    cur = a["cost"]["currency"]
    b64 = lambda png: "data:image/png;base64," + base64.b64encode(png).decode()
    p = a["part"]
    main, other = _shown(a)
    scr = a.get("screens") or {}
    h: list[str] = [(f"<!doctype html><html><head><meta charset='utf-8'><title>Manufacturability report · "
                    f"{_e(project_name)}</title><style>{CSS}</style></head><body><div class='wrap'>")]
    h.append("<div class='banner'>NOT APPROVED FOR MANUFACTURE · Advisory DFM screening · Costs: "
             "relative estimate, not a quote</div>")
    h.append(f"<h1 style='margin-top:14px'>Manufacturability report: {_e(project_name)}</h1>")
    h.append(f"<div class='meta'>{_e(_model_line(a))} · {_e(a['analyser'])} · {_e(a['tables'])}</div>")
    h.append("<div class='grid' style='margin-top:14px'><div>")
    if overview:
        h.append(f"<img src='{b64(overview)}' style='width:100%;border:1px solid #e3e6ea;border-radius:6px'>")
    h.append("</div><div><table>")
    top = a["process"]["ranking"][0]
    rows = [("Envelope", " × ".join(f"{x:g}" for x in p["bbox"]) + " mm"), ("Volume", f"{p['volume_mm3']:,.0f} mm³"),
            ("Material", f"{a['material']['name']} ({a['material']['how']})"), ("Mass", f"{p['mass_kg']:.3f} kg"),
            ("Quantity", f"{a['inputs']['quantity']:,}"), ("Tolerance class", a["inputs"]["tolerance"]),
            ("Shop profile", a["shop"]["name"]), ("Findings (all processes)", _counts(a)),
            ("Top process", f"{top['name']} · {top['fit']}")]
    h += [f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in rows]
    h.append("</table></div></div>")

    h.append(f"<h2>Findings <span class='lvl'>{_e(a['chk13']['advice_level'])}</span></h2>")

    def finding_html(f: dict[str, Any]) -> str:
        col = SEV_COLOR[f["severity"]]
        img = f"<img src='{b64(views[f['id']])}'>" if f["id"] in views else ""
        return (f"<div class='f' style='border-left-color:{col}'>{img}<div>"
                f"<div class='sev' style='color:{col}'>{_e(f['severity'])}</div>"
                f"<div style='font-weight:600;font-size:13.5px'>{_e(f['title'])}</div>"
                f"<div><b>Where:</b> {_e(where(f))}</div>"
                f"<div><b>Measured:</b> {_e(f['measured'])} &nbsp; <b>Limit:</b> {_e(f['limit'])}</div>"
                f"<div style='margin-top:4px'>{_e(f['rationale'])}</div>"
                f"<div style='margin-top:4px'><b>Suggested fix:</b> {_e(f['fix'])}</div>"
                f"<div class='small' style='margin-top:4px'>Source: {_e(f['source'])} · rule {_e(f['rule'])}</div>"
                "</div></div>")

    for proc, label in _sections(main):
        fs = [f for f in main if f["process"] == proc]
        if fs:
            h.append(f"<h3 style='font-size:13px;margin:14px 0 4px'>{_e(label)}</h3>")
            h += [finding_html(f) for f in fs]
    if other:
        h.append("<h2>Other screens (processes not shortlisted)</h2><p class='small'>"
                 + _e("; ".join(f"{PROCESS_LABEL[k]}: {v['reason']}" for k, v in scr.items() if not v.get("shown")))
                 + "</p><ul class='small'>" + "".join(
                     f"<li>{_e(f['severity'])}: {_e(f['title'])} ({_e(f['measured'])})</li>" for f in other) + "</ul>")
    h.append("<h2>Rules run (advisory, not a gate)</h2><table><tr><th>Rule</th><th>Check</th><th>Process</th>"
             "<th>Result</th></tr>")
    for r in a["chk13"]["rules"]:
        h.append(f"<tr><td class='id'>{_e(r['rule'])}</td><td>{_e(r['name'])}</td>"
                 f"<td>{_e(PROCESS_LABEL[r['process']])}</td><td>{_e(r['status'])}</td></tr>")
    h.append("</table>")

    h.append(f"<h2>Process recommendation <span class='lvl'>{_e(a['process']['advice_level'])}</span></h2>")
    h.append("<table><tr><th>#</th><th>Process</th><th>Score</th><th>Fit</th><th>Confidence</th><th>For</th>"
             "<th>Against</th></tr>")
    for i, r in enumerate(a["process"]["ranking"], 1):
        h.append(f"<tr><td>{i}</td><td>{_e(r['name'])}</td><td>{r['score']}</td><td>{_e(r['fit'])}</td>"
                 f"<td>{_e(r['confidence'])}</td><td>{_e('; '.join(r['pros']))}</td><td>{_e('; '.join(r['cons']))}</td></tr>")
    h.append("</table><ul class='small'>" + "".join(f"<li>{_e(x)}</li>" for x in a["process"]["assumptions"]) + "</ul>")

    c = a["cost"]
    h.append(f"<h2>Relative cost · {_e(c['label'])} <span class='lvl'>{_e(c['advice_level'])}</span></h2>")
    qs = c["quantities"]
    h.append("<table><tr><th>Process</th>" + "".join(f"<th>q = {q:,}</th>" for q in qs) + "</tr>")
    for name, pr in c["processes"].items():
        h.append(f"<tr><td>{_e(name.replace('_', ' '))}</td>" + "".join(
            f"<td>{_money(pt['unit'], cur)}</td>" for pt in pr["curve"]) + "</tr>")
    h.append("</table><p class='small'>Unit cost per part. Material, machine time and setup/tooling at your quantity:</p>")
    h.append("<table><tr><th>Process</th><th>Material</th><th>Machine time</th><th>Setup & tooling</th><th>Assumptions</th></tr>")
    for name, pr in c["processes"].items():
        bd = pr["breakdown"]
        h.append(f"<tr><td>{_e(name.replace('_', ' '))}</td><td>{_money(bd['material'], cur)}</td>"
                 f"<td>{_money(bd['machine_time'], cur)}</td><td>{_money(bd['setup_tooling'], cur)}</td>"
                 f"<td class='small'>{_e('; '.join(pr['notes']))}</td></tr>")
    h.append("</table>")
    if a["drivers"]:
        h.append("<h2>Cost drivers and suggestions</h2><ol>")
        for d in a["drivers"]:
            sv = f" (≈ {_money(d['saving_per_unit'], cur)} per part)" if d.get("saving_per_unit") else ""
            h.append(f"<li><b>{_e(d['title'])}</b>{_e(sv)}. {_e(d['rationale'])}</li>")
        h.append("</ol>")
    m = a["material"]
    h.append("<h2>Material and provenance</h2><table>")
    for k in ("density_g_cm3", "machining_class", "processes", "price_per_kg"):
        v = m[k] if k != "price_per_kg" else f"{m['price_used']:g} per kg"
        h.append(f"<tr><th>{_e(k.replace('_', ' '))}</th><td>{_e(v)}</td><td class='small'>"
                 f"{_e(m['provenance'][k])}</td></tr>")
    h.append(f"</table><p class='small'>{_e(m['library_version'])}</p>")
    h.append(f"<h2>Disclaimer</h2><p>{_e(a['disclaimer'])}</p></div></body></html>")
    return "".join(h)


# ----------------------------------------------------------------------------- PDF
def _font() -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    try:
        pdfmetrics.getFont("FwSans")
        return "FwSans"
    except KeyError:
        pass
    import matplotlib

    base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    try:
        pdfmetrics.registerFont(TTFont("FwSans", str(base / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("FwSans-Bold", str(base / "DejaVuSans-Bold.ttf")))
        from reportlab.lib.fonts import addMapping

        addMapping("FwSans", 0, 0, "FwSans")
        addMapping("FwSans", 1, 0, "FwSans-Bold")
        return "FwSans"
    except Exception:  # noqa: BLE001 - fall back to a core font (some symbols may not render)
        return "Helvetica"


def build_pdf(a: dict[str, Any], project_name: str, topo: dict[str, Any] | None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Image,
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    font = _font()
    bold = "FwSans-Bold" if font == "FwSans" else "Helvetica-Bold"
    st = ParagraphStyle("b", fontName=font, fontSize=8.6, leading=11)
    sm = ParagraphStyle("s", parent=st, fontSize=7.4, leading=9.4, textColor=colors.HexColor("#566270"))
    h1 = ParagraphStyle("h1", parent=st, fontName=bold, fontSize=15, leading=19)
    h2 = ParagraphStyle("h2", parent=st, fontName=bold, fontSize=11, leading=14, spaceBefore=8, spaceAfter=4,
                        textColor=colors.HexColor("#1f5fa8"))
    ban = ParagraphStyle("ban", parent=st, fontName=bold, backColor=colors.HexColor("#fff4e5"),
                         textColor=colors.HexColor("#7a4b00"), borderPadding=5)
    P = lambda t, s=st: Paragraph(_e(t), s)
    grid = TableStyle([("FONT", (0, 0), (-1, -1), font, 7.6), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6dbe1")),
                       ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f4f7")), ("VALIGN", (0, 0), (-1, -1), "TOP")])
    overview, views = _views(a, topo)
    main, other = _shown(a)
    scr = a.get("screens") or {}
    cur = a["cost"]["currency"]
    story: list[Any] = [P("NOT APPROVED FOR MANUFACTURE · Advisory DFM screening · Costs: relative estimate, "
                          "not a quote", ban), Spacer(1, 6),
                        P(f"Manufacturability report: {project_name}", h1),
                        P(f"{_model_line(a)} · {a['analyser']} · {a['tables']}", sm), Spacer(1, 6)]
    p = a["part"]
    top = a["process"]["ranking"][0]
    info = [[P("Envelope"), P(" × ".join(f"{x:g}" for x in p["bbox"]) + " mm")],
            [P("Material"), P(f"{a['material']['name']} ({a['material']['how']})")],
            [P("Mass"), P(f"{p['mass_kg']:.3f} kg")], [P("Quantity"), P(f"{a['inputs']['quantity']:,}")],
            [P("Tolerance class"), P(a["inputs"]["tolerance"])], [P("Shop profile"), P(a["shop"]["name"])],
            [P("Findings (all processes)"), P(_counts(a))], [P("Top process"), P(f"{top['name']} · {top['fit']}")]]
    t_info = Table(info, colWidths=[32 * mm, 60 * mm])
    t_info.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6dbe1"))]))
    if overview:
        story.append(Table([[Image(io.BytesIO(overview), width=84 * mm, height=63 * mm), t_info]],
                           colWidths=[88 * mm, 94 * mm]))
    else:
        story.append(t_info)
    story.append(P(f"Findings ({a['chk13']['advice_level']})", h2))
    for proc, label in _sections(main):
        fs = [f for f in main if f["process"] == proc]
        if not fs:
            continue
        story.append(P(label, ParagraphStyle("h3", parent=st, fontName=bold, spaceBefore=4)))
        for f in fs:
            txt = [Paragraph(f"<font color='{SEV_COLOR[f['severity']]}'><b>{_e(f['severity'].upper())}</b></font>", st),
                   Paragraph(f"<b>{_e(f['title'])}</b>", st), P("Where: " + where(f)),
                   P(f"Measured: {f['measured']}   Limit: {f['limit']}"), P(f["rationale"]),
                   P("Suggested fix: " + f["fix"]), P(f"Source: {f['source']} · rule {f['rule']}", sm)]
            img = Image(io.BytesIO(views[f["id"]]), width=56 * mm, height=42 * mm) if f["id"] in views else ""
            row = Table([[img, txt]], colWidths=[59 * mm, 123 * mm] if img else [2 * mm, 180 * mm])
            row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                     ("LINEBEFORE", (0, 0), (0, 0), 2.5, colors.HexColor(SEV_COLOR[f["severity"]])),
                                     ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6dbe1"))]))
            story += [KeepTogether([row]), Spacer(1, 3)]
    story.append(P("Rules run (advisory, not a gate)", h2))
    rows = [["Rule", P("Check"), P("Process"), P("Result")]] + [
        [r["rule"], P(r["name"]), P(PROCESS_LABEL[r["process"]]), P(r["status"])] for r in a["chk13"]["rules"]]
    t = Table(rows, colWidths=[24 * mm, 86 * mm, 44 * mm, 28 * mm], repeatRows=1)
    t.setStyle(grid)  # rule ids are plain strings: they never wrap mid-id
    story.append(t)
    story.append(P(f"Process recommendation ({a['process']['advice_level']})", h2))
    rows = [[P("Process"), P("Score"), P("Fit"), P("For"), P("Against")]] + [
        [P(r["name"]), P(str(r["score"])), P(f"{r['fit']} ({r['confidence']} confidence)"), P("; ".join(r["pros"]), sm),
         P("; ".join(r["cons"]), sm)] for r in a["process"]["ranking"]]
    t = Table(rows, colWidths=[30 * mm, 12 * mm, 30 * mm, 55 * mm, 55 * mm], repeatRows=1)
    t.setStyle(grid)
    story += [t] + [P("• " + x, sm) for x in a["process"]["assumptions"]]
    c = a["cost"]
    story.append(P(f"Relative cost: {c['label']} ({c['advice_level']})", h2))
    rows = [[P("Process")] + [P(f"q = {q:,}") for q in c["quantities"]]] + [
        [P(n.replace("_", " "))] + [P(_money(pt["unit"], cur)) for pt in pr["curve"]] for n, pr in c["processes"].items()]
    t = Table(rows, repeatRows=1)
    t.setStyle(grid)
    story.append(t)
    for n, pr in c["processes"].items():
        story.append(P(f"{n.replace('_', ' ')}: " + "; ".join(pr["notes"]), sm))
    if a["drivers"]:
        story.append(P("Cost drivers and suggestions", h2))
        for i, d in enumerate(a["drivers"], 1):
            sv = f" (≈ {_money(d['saving_per_unit'], cur)} per part)" if d.get("saving_per_unit") else ""
            story.append(P(f"{i}. {d['title']}{sv}. {d['rationale']}"))
    if other:
        story.append(P("Appendix: other screens (processes not shortlisted)", h2))
        story.append(P("; ".join(f"{PROCESS_LABEL[k]}: {v['reason']}" for k, v in scr.items() if not v.get("shown")), sm))
        story += [P(f"• {f['severity']}: {f['title']} ({f['measured']})", sm) for f in other]
    m = a["material"]
    story.append(P("Material and provenance", h2))
    for k in ("density_g_cm3", "machining_class", "processes", "price_per_kg"):
        v = m[k] if k != "price_per_kg" else f"{m['price_used']:g} per kg"
        story.append(P(f"{k.replace('_', ' ')}: {v} ({m['provenance'][k]})", sm))
    story += [P("Disclaimer", h2), P(a["disclaimer"])]
    buf = io.BytesIO()
    model = _model_line(a).split(" · analysed")[0]

    def _footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(font, 7)
        canvas.setFillColor(colors.HexColor("#566270"))
        canvas.drawString(14 * mm, 8 * mm, f"Formwright Manufacturing Advisor · {project_name} · {model} · "
                                           "advisory: not approved for manufacture, not a quote")
        canvas.drawRightString(196 * mm, 8 * mm, f"page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm,
                            bottomMargin=14 * mm, title=f"Manufacturability report · {project_name}",
                            author="Formwright", invariant=1)
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
