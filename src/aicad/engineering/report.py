"""Calculation package (MAKE-20): one calculation set as a PDF a checker or customer can file.

Cover (project, model revision and build, sign-off state, signer and role, date, statement, content hash, advice
level, self-checked or independent, a model-changed warning), then per calculation: inputs with their provenance
(from the model, from a load case, entered, or an example value not confirmed), the working with equations and
sources, checks against the required factor and its source, warnings and assumptions; then the linked load cases,
notes and conclusion, and the limits of what the document is.

Never a certification: the document states the advice level and that hand-calculation methods are not a validated
simulation. Deterministic for a given set and model (reportlab ``invariant``).
"""

from __future__ import annotations

import html
import io
from pathlib import Path
from typing import Any

from aicad import deliverables
from aicad.engineering import REGISTRY, core, store, units

DISCLAIMER = ("Hand-calculation methods from the cited references, run by deterministic, unit-tested code. A signature "
              "records that the named engineer reviewed the inputs, assumptions, working and results; it does not "
              "certify the design, and nothing in this document is a validated simulation, a test result or an "
              "approval for manufacture. Verify material data against the supplier certificate.")


def _e(s: Any) -> str:
    return html.escape(str(s if s is not None else "—"))


def _font() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    try:
        pdfmetrics.getFont("FwSans")
        return "FwSans", "FwSans-Bold"
    except KeyError:
        pass
    try:
        import matplotlib
        from reportlab.lib.fonts import addMapping

        base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        pdfmetrics.registerFont(TTFont("FwSans", str(base / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("FwSans-Bold", str(base / "DejaVuSans-Bold.ttf")))
        addMapping("FwSans", 0, 0, "FwSans")
        addMapping("FwSans", 1, 0, "FwSans-Bold")
        return "FwSans", "FwSans-Bold"
    except Exception:  # noqa: BLE001 - core font fallback (Greek letters may not render)
        return "Helvetica", "Helvetica-Bold"


def _value(p: core.Param | None, v: Any) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        cols = {c.key: c for c in (p.columns or [])} if p else {}
        rows = []
        for r in v:
            rows.append(", ".join(f"{cols[k].label if k in cols else k} {_value(None, x)}"
                                  f"{' ' + units.KINDS[cols[k].kind].label if k in cols and cols[k].kind in units.KINDS else ''}"
                                  for k, x in r.items()))
        return "; ".join(rows)
    if isinstance(v, float):
        s = core.g(v)
    else:
        s = str(v)
    if p and p.kind == "enum":
        s = next((o["label"] for o in p.options or [] if o["value"] == v), s)
    if p and p.kind in units.KINDS and units.KINDS[p.kind].label not in ("", "–"):
        s += f" {units.KINDS[p.kind].label}"
    return s


def _provenance(it: dict[str, Any], key: str, lcs_by_load: dict[str, str]) -> str:
    unconf = {e["key"] for e in store.unconfirmed(it)}
    if key in unconf:
        return "EXAMPLE VALUE, NOT CONFIRMED"
    if key in (it.get("confirmed") or []):
        return "Example value kept and confirmed by the user"
    src = (it.get("source") or {}).get(key)
    if src:
        return str(src)
    return "Entered"


def build_pdf(ws: Path, set_id: str, project_name: str) -> bytes:
    """The calculation package of set ``set_id`` in the project workspace ``ws`` as PDF bytes."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    sets: list[dict[str, Any]] = store.load(ws, "sets")  # type: ignore[assignment]
    lcs: list[dict[str, Any]] = store.load(ws, "loadcases")  # type: ignore[assignment]
    raw = next((s for s in sets if s["id"] == set_id), None)
    if raw is None:
        raise KeyError(set_id)
    cur = deliverables.build_stamp(ws)
    cs = store.decorate(raw, lcs, cur)
    st, so = cs["status"], cs.get("signoff") or {}
    status = deliverables.read_status(ws)

    font, bold = _font()
    body = ParagraphStyle("b", fontName=font, fontSize=8.6, leading=11)
    sm = ParagraphStyle("s", parent=body, fontSize=7.4, leading=9.4, textColor=colors.HexColor("#566270"))
    mono = ParagraphStyle("m", parent=body, fontSize=7.6, leading=9.6)
    h1 = ParagraphStyle("h1", parent=body, fontName=bold, fontSize=15, leading=19)
    h2 = ParagraphStyle("h2", parent=body, fontName=bold, fontSize=11, leading=14, spaceBefore=9, spaceAfter=4,
                        textColor=colors.HexColor("#1f5fa8"))
    h3 = ParagraphStyle("h3", parent=body, fontName=bold, fontSize=9.4, leading=12, spaceBefore=6, spaceAfter=2)
    tone = {"signed": ("#e8f5ee", "#1b5e3b"), "model_changed": ("#fff4e5", "#7a4b00"),
            "invalidated": ("#fdecea", "#8e1c1c"), "unsigned": ("#fff4e5", "#7a4b00")}[st["state"]]
    if st["state"] == "signed" and st["self_check"]:
        tone = ("#fff4e5", "#7a4b00")
    ban = ParagraphStyle("ban", parent=body, fontName=bold, backColor=colors.HexColor(tone[0]),
                         textColor=colors.HexColor(tone[1]), borderPadding=5)
    P = lambda t, s=body: Paragraph(_e(t), s)
    grid = TableStyle([("FONT", (0, 0), (-1, -1), font, 7.6), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6dbe1")),
                       ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f4f7")), ("VALIGN", (0, 0), (-1, -1), "TOP")])
    kv = TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6dbe1")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                     ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f6f7f9"))])

    level = cs["level_label"]
    story: list[Any] = [P(f"{st['label'].upper()} · Advice level: {level}", ban), Spacer(1, 6),
                        P(f"Calculation package: {cs['name']}", h1), P(project_name, sm), Spacer(1, 6)]
    signed_rev = st.get("signed_on_rev")
    cover = [[P("Project"), P(project_name)],
             [P("Part"), P(status.get("part") or "—")],
             [P("Material (model)"), P(status.get("material") or "—")],
             [P("Model"), P(f"revision {cur.get('model_rev') or '—'} · build {str(cur.get('build_id') or '—')[-8:]}")],
             [P("Advice level"), P(level)],
             [P("Sign-off"), P(st["label"])]]
    if so:
        who = "self-checked (the signer also authored calculations in this set)" if so.get("self_check") \
            else "independent check (the signer did not author these calculations)"
        cover += [[P("Signed by"), P(f"{so.get('name')} ({so.get('role')}) · {so.get('at')}")],
                  [P("Check type"), P(who)],
                  [P("Signed on model"), P(f"revision {signed_rev or '—'}")],
                  [P("Statement"), P(f"“{so.get('statement')}”")]]
        if so.get("facts"):
            cover.append([P("Recorded facts"), P(so["facts"])])
    cover.append([P("Content hash"), Paragraph(_e(st["hash"]), mono)])
    t = Table(cover, colWidths=[34 * mm, 148 * mm])
    t.setStyle(kv)
    story.append(t)
    if st["state"] == "model_changed":
        story += [Spacer(1, 5), P(f"The model has changed since sign-off (signed on revision {signed_rev or '—'}, "
                                  f"current revision {cur.get('model_rev') or '—'}). Re-check the calculations "
                                  "against the current model and sign again before relying on them.", ban)]
    elif st["state"] == "invalidated":
        story += [Spacer(1, 5), P("The set was edited after it was signed: the signature does not cover this content.",
                                  ban)]
    elif st["state"] == "unsigned":
        story += [Spacer(1, 5), P("Unsigned: these results are preliminary estimates, not for release.", ban)]

    lc_names = {c["id"]: c["name"] for c in lcs}
    for i, it in enumerate(cs["items"], 1):
        r = it["result"]
        calc = REGISTRY.get(it["calc_id"])
        params = {p.key: p for p in calc.all_inputs()} if calc else {}
        block: list[Any] = [P(f"{i}. {it['title']}", h2),
                            P(f"{r.get('calc_name')} · calculator v{r.get('calc_version')} · {r.get('engine')}", sm)]
        if it.get("model_changed"):
            block.append(P("Pre-filled from an earlier model revision.", ban))
        rows = [[P("Input"), P("Value"), P("Provenance")]]
        for k, v in r["inputs"].items():
            if v is None or k in ("sf_required", "sf_source"):
                continue
            prm = params.get(k)
            rows.append([P(prm.label if prm else k), P(_value(prm, v)), P(_provenance(it, k, lc_names), sm)])
        tb = Table(rows, colWidths=[50 * mm, 52 * mm, 80 * mm], repeatRows=1)
        tb.setStyle(grid)
        block.append(tb)
        if r.get("safety_factor"):
            block.append(P(f"Required safety factor {core.g(r['safety_factor']['required'])} · source: "
                           f"{r['safety_factor']['source']}", body))
        story += block
        story.append(P("Working", h3))
        rows = [[P("#"), P("Step"), P("Equation and substitution"), P("Result"), P("Source")]]
        for j, s in enumerate(r["steps"], 1):
            eq = _e(s["equation"]) + (f"<br/><font color='#566270'>= {_e(s['substitution'])}</font>"
                                     if s.get("substitution") else "")
            rows.append([P(str(j), sm), P(s["label"]), Paragraph(eq, mono),
                         P(f"{core.g(s['value']) if isinstance(s['value'], float) else _e(s['value'])} {s.get('unit') or ''}"),
                         P(s.get("ref") or "", sm)])
        tb = Table(rows, colWidths=[7 * mm, 38 * mm, 77 * mm, 26 * mm, 34 * mm], repeatRows=1)
        tb.setStyle(grid)
        story.append(tb)
        if r["checks"]:
            story.append(P("Checks", h3))
            rows = [[P("Check"), P("Achieved"), P("Required"), P("Result"), P("Basis / source")]]
            for c in r["checks"]:
                res = "—" if c["passed"] is None else ("meets" if c["passed"] else "BELOW REQUIREMENT")
                rows.append([P(c["label"]), P(core.g(c["achieved"]) if isinstance(c["achieved"], float)
                                              else _e(c["achieved"])),
                             P(core.g(c["required"]) if c.get("required") is not None else "—"), P(res),
                             P(c["basis"] + (f" · {c['source']}" if c.get("source") else ""), sm)])
            tb = Table(rows, colWidths=[46 * mm, 22 * mm, 20 * mm, 30 * mm, 64 * mm], repeatRows=1)
            tb.setStyle(grid)
            story.append(tb)
        notes = [("Warning", w) for w in r.get("warnings") or []] + [("Assumption", a) for a in r.get("assumptions") or []] \
            + [("Note", n) for n in r.get("notes") or []] + [("Reference", x) for x in r.get("references") or []]
        story += [P(f"{k}: {v}", sm) for k, v in notes]

    story.append(P("Load cases", h2))
    linked = [c for c in lcs if c["id"] in (raw.get("load_case_ids") or [])]
    if not linked:
        story.append(P("No load cases linked." + (" The signer confirmed that the loads are stated in each "
                                                  "calculation." if so.get("loads_in_calcs") else "")))
    for c in linked:
        loads = "; ".join(f"{ld['name']} {core.g(float(ld['value']))} {ld['unit']} ({ld['basis']}"
                          f"{', ' + ld['source'] if ld.get('source') else ''})" for ld in c.get("loads") or [])
        sup = "; ".join(f"{s_['type']} {s_.get('location') or ''}".strip() for s_ in c.get("supports") or [])
        story.append(KeepTogether([P(f"{c['name']} ({c['kind']})", h3), P(f"Loads: {loads or '—'}"),
                                   P(f"Supports: {sup or '—'}"),
                                   *([P(c["description"], sm)] if c.get("description") else []),
                                   *([P(f"Source: {c['source']}", sm)] if c.get("source") else [])]))
    if raw.get("notes") or raw.get("conclusion"):
        story.append(P("Notes and conclusion", h2))
        if raw.get("notes"):
            story.append(P(raw["notes"]))
        if raw.get("conclusion"):
            story.append(P("Conclusion: " + raw["conclusion"]))
    story += [P("Limits of this document", h2), P(DISCLAIMER),
              P("Advice levels (docs: VALIDATION §4): Recommended check → Preliminary estimate → Verified calculation "
                "(signed by a named engineer) → Validated simulation (not produced by Formwright).", sm)]

    buf = io.BytesIO()

    def _footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(font, 7)
        canvas.setFillColor(colors.HexColor("#566270"))
        canvas.drawString(14 * mm, 8 * mm, f"Formwright Engineering Advisor · {project_name} · {cs['name']} · "
                                           f"{level} · hash {st['hash'][:12]}")
        canvas.drawRightString(196 * mm, 8 * mm, f"page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm,
                            bottomMargin=14 * mm, title=f"Calculation package · {cs['name']}", author="Formwright",
                            invariant=1)
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
