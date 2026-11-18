"""Generate a drawing sheet for a project workspace: SVG + PDF + DXF + drawing.json under <workspace>/drawings/.

Associative (DRW-015): every generation reads the latest verified build (``out/part.step`` + ``out/status.json``).
``history.json`` keeps one row per drawn build (model revision, parameter changes, date, user) for the History tab.
Regenerating the same build reuses its row, so the same model, options and edits give byte-identical SVG.

Revisions (MAKE-08): the sheet's REV field and revision table show *issued* revisions only (A, B, … from the
release gate, ``meta["releases"]``). A sheet of a build that has not been issued says REV "DRAFT"; once a release
exists, a note states that the changes since that revision are not issued.

Copies (MAKE-09): the review copy (on screen, ``sheet.svg`` and ``sheet_review.pdf``) shows the spec / inferred
tags with colours and a legend; the issue copy (``sheet.pdf``, ``sheet_issue.svg``, ``sheet.dxf``, the export
default) is monochrome with no legend. Both come from one layout, so they share scale and positions.

User edits (MAKE-06, ``edits``): hidden dimensions or callouts, per-dimension tolerance or fit text (printed after
the value and marked user-entered in the record), title-block fields and free notes. Edits are keyed by stable
dimension ids and re-applied on every regeneration; CHK-12 runs on the edited sheet.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from aicad import deliverables
from aicad.drawing import VERSION, DrawingInputError
from aicad.drawing.check import chk12
from aicad.drawing.dims import candidates, fmt, tag
from aicad.drawing.layout import SHEETS, compose
from aicad.drawing.render import issue_sheet, to_dxf, to_pdf, to_svg

ISO2768 = {"f": "fine", "m": "medium", "c": "coarse", "v": "very coarse"}
VIEW_CHOICES = ("front", "top", "right", "iso")
SECTION_CHOICES = ("auto", "x", "y", "z", "axial", "cross")
TITLE_FIELDS = ("title", "drawing_no", "company", "checked_by")
_cache: dict[tuple[Any, ...], dict[str, Any]] = {}


def normalize_options(o: dict[str, Any] | None) -> dict[str, Any]:
    """``views`` None = chosen from the part type; ``section`` "auto" = chosen from the part type, None = off."""
    o = dict(o or {})
    sheet = o.get("sheet") if o.get("sheet") in SHEETS else "A3"
    proj = o.get("projection") if o.get("projection") in ("first", "third") else "first"
    views: list[str] | None
    if o.get("views") is None:
        views = None
    else:
        views = [v for v in VIEW_CHOICES if v in o["views"]]
        if "front" not in views:
            views.insert(0, "front")
    sec = o.get("section", "auto")
    sec = sec if sec in SECTION_CHOICES else None
    tol = o.get("tolerance") or {}
    mode = tol.get("mode") if tol.get("mode") in ("none", "iso2768", "custom") else "none"
    tclass = tol.get("class") if tol.get("class") in ISO2768 else "m"
    text = " ".join(str(tol.get("text") or "").split())[:60]
    if mode == "custom" and not text:
        mode = "none"
    return {"sheet": sheet, "projection": proj, "views": views, "section": sec, "hidden": o.get("hidden", True) is not False,
            "tolerance": {"mode": mode, "class": tclass if mode == "iso2768" else None,
                          "text": text if mode == "custom" else None}}


_TOL_RE = re.compile(r"^[A-Za-z0-9 ±+\-.,/()°]{1,24}$")


def normalize_edits(e: dict[str, Any] | None) -> dict[str, Any]:
    """User edits, sanitised: dims {id: {hidden, tol}}, title {title, drawing_no, company, checked_by}, notes."""
    e = dict(e or {})
    dims: dict[str, dict[str, Any]] = {}
    for k, v in sorted((e.get("dims") or {}).items())[:400]:
        if not isinstance(v, dict) or not re.fullmatch(r"[a-z]+(-[a-z0-9]+){1,4}", str(k)):
            continue
        rec: dict[str, Any] = {}
        if v.get("hidden"):
            rec["hidden"] = True
        tol = " ".join(str(v.get("tol") or "").split())
        if tol:
            if not _TOL_RE.fullmatch(tol):
                raise DrawingInputError(f"Tolerance “{tol[:24]}” uses characters a drawing can't print. Use digits, "
                                        "letters, ±, +, -, . and spaces (e.g. ±0.1, H7, +0.1/-0).")
            rec["tol"] = tol
        if rec:
            dims[str(k)] = rec
    title = {f: " ".join(str((e.get("title") or {}).get(f) or "").split())[:60] for f in TITLE_FIELDS}
    title = {k: v for k, v in title.items() if v}
    notes = [" ".join(str(n).split())[:160] for n in (e.get("notes") or [])][:12]
    return {"dims": dims, "title": title, "notes": [n for n in notes if n]}


def spec_params(status: dict[str, Any], spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    """The model's parameters plus interface numbers from the Design Office ICD (``spec``: params / meta / fits).
    An ICD value is offered only when no model parameter already carries that value (two names for one size would
    make the dimension ambiguous, and then neither could tag it spec)."""
    from aicad.drawing.dims import _numeric_params, param_kind

    params = dict(status.get("params") or {})
    pmeta = dict(status.get("param_meta") or {})
    fits: dict[str, str] = {}
    own = _numeric_params(params)
    for k, v in (spec.get("params") or {}).items():
        if not str(k).startswith("ICD_") or k in params or not isinstance(v, int | float):
            continue
        kind = param_kind(k, (spec.get("meta") or {}).get(k))
        same = [p for p, x in own.items() if abs(float(v) - x) <= 1e-6 * max(1.0, x)]
        if same:
            # the model already declares this size: a parameter of the same kind carries the fit
            match = [p for p in same if param_kind(p, pmeta.get(p)) == kind]
            if len(match) == 1 and (spec.get("fits") or {}).get(k):
                fits.setdefault(match[0], spec["fits"][k])
            continue
        params[k] = float(v)
        pmeta[k] = (spec.get("meta") or {}).get(k) or {"label": k}
        if (spec.get("fits") or {}).get(k):
            fits[k] = spec["fits"][k]
    return params, pmeta, fits


def tolerance_text(t: dict[str, Any]) -> str:
    if t["mode"] == "iso2768":
        return f"ISO 2768-{t['class']} ({ISO2768[t['class']]})"
    if t["mode"] == "custom":
        return t["text"]
    return "Not specified"


def _analysis(step: Path, opts: dict[str, Any]) -> dict[str, Any]:
    from aicad.drawing import geometry

    st = step.stat()
    key = (str(step.resolve()), st.st_mtime_ns, st.st_size, tuple(opts["views"] or ()), opts["views"] is None,
           opts["section"], VERSION)
    if key not in _cache:
        if len(_cache) > 24:
            _cache.clear()
        _cache[key] = geometry.analyse(str(step), {"views": opts["views"], "section": opts["section"]})
    return _cache[key]


def _history(path: Path, status: dict[str, Any], meta: dict[str, Any], write: bool = True) -> list[dict[str, Any]]:
    hist: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    bid = str(status.get("build_id") or status.get("step_sha256") or "")
    if hist and hist[-1].get("build_id") == bid:
        return hist
    params = {k: v for k, v in (status.get("params") or {}).items() if isinstance(v, (int, float))}
    if not hist:
        change = "First drawing"
    else:
        prev = hist[-1].get("params") or {}
        diffs = [f"{k} {fmt(prev[k])}→{fmt(v)}" for k, v in sorted(params.items())
                 if k in prev and abs(float(prev[k]) - float(v)) > 1e-9]
        diffs += [f"{k} added" for k in sorted(params) if k not in prev]
        change = ("Regenerated: " + ", ".join(diffs)) if diffs else "Regenerated: model geometry changed"
    hist.append({"rev": meta.get("model_rev") or str(len(hist) + 1), "build_id": bid, "date": meta.get("date", ""),
                 "by": meta.get("drawn_by", ""), "change": change, "params": params,
                 "fingerprint": status.get("fingerprint")})
    if write:
        path.write_text(json.dumps(hist, indent=1, sort_keys=True), encoding="utf-8")
    return hist


def sheet_revision(releases: list[dict[str, Any]], stamp: dict[str, Any], issue: dict[str, Any] | None
                   ) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
    """REV field, revision-table rows (issued revisions only) and the latest release (MAKE-08)."""
    rels = [r for r in releases if r.get("rev")]
    if issue is not None:
        rels = [r for r in rels if r.get("rev") != issue.get("rev")] + [issue]
    rows = [{"rev": r["rev"], "date": r.get("date", ""), "change": r.get("note") or "Issued", "by": r.get("by", "")}
            for r in rels]
    latest = rels[-1] if rels else None
    if issue is not None:
        return str(issue["rev"]), rows, latest
    if latest and deliverables.same_build(latest.get("build"), stamp):
        return str(latest["rev"]), rows, latest
    return "DRAFT", rows, latest


def generate(out_dir: Path, dest: Path, options: dict[str, Any], meta: dict[str, Any],
             edits: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the sheet for the verified model in ``out_dir`` and write the files to ``dest``.

    ``meta``: title, drawing_no, drawn_by, date (YYYY-MM-DD, the user's local date), model_rev, releases (issued
    revisions, oldest first) and ``issue`` (a release being issued now: write only the issue copy, dated by it, and
    leave the working history alone)."""
    t0 = time.perf_counter()
    from aicad.drawing.geometry import bbox_extents

    step, status_p = out_dir / "part.step", out_dir / "status.json"
    if not step.is_file() or not status_p.is_file():
        raise DrawingInputError("This project has no verified build yet. Build the model in the Design Studio first.")
    status = json.loads(status_p.read_text(encoding="utf-8"))
    if not status.get("ok"):
        raise DrawingInputError("The latest build did not pass its checks. Fix the model before drawing it.")
    opts = normalize_options(options)
    ed = normalize_edits(edits)
    issue = meta.get("issue")
    dest.mkdir(parents=True, exist_ok=True)
    an = _analysis(step, opts)
    t_geo = time.perf_counter() - t0
    cen = an["census"]
    pl = an["plan"]
    enabled = set(an["views"])
    sec = an.get("section")
    cross = sec is not None and not pl.get("front_section")
    if cross:
        enabled.add("section")
    dims, callouts, notes_extra = candidates(cen, enabled, {"axis": sec["axis"], "at": sec["plane"]} if cross else None)
    params, pmeta, fits = spec_params(status, meta.get("spec") or {})
    mapping = tag(dims, callouts, params, pmeta)
    # interface fits (Design Office ICD) printed after the value they belong to, unless the user wrote a tolerance
    for d in dims:
        if d.get("tag") == "spec" and d.get("param") in fits and not ed["dims"].get(d["id"], {}).get("tol"):
            d["text"] = f"{d['text']} {fits[d['param']]}"
            d["icd_fit"] = fits[d["param"]]
    for c in callouts:
        ln = c["lines"][0]
        if ln.get("tag") == "spec" and ln.get("param") in fits and not ed["dims"].get(c["id"], {}).get("tol"):
            ln["text"] += f" {fits[ln['param']]}"
            c["icd_fit"] = fits[ln["param"]]
    # user edits: tolerance / fit text after the value, hidden dimensions and callouts
    hidden = sorted(k for k, v in ed["dims"].items() if v.get("hidden"))
    for d in dims:
        tol = ed["dims"].get(d["id"], {}).get("tol")
        if tol:
            d["text"] = f"{d['text']} {tol}"
            d["tol"] = tol
    for c in callouts:
        tol = ed["dims"].get(c["id"], {}).get("tol")
        if tol:
            c["lines"][0]["text"] += f" {tol}"
            c["tol"] = tol
    shown_dims = [d for d in dims if d["id"] not in hidden]
    shown_callouts = [c for c in callouts if c["id"] not in hidden]

    stamp = deliverables.build_stamp(out_dir.parent, status)
    history = _history(dest / "history.json", status, meta, write=issue is None)
    row = history[-1]
    rev, rev_rows, latest = sheet_revision(meta.get("releases") or [], stamp, issue)
    tol = opts["tolerance"]
    tol_txt = tolerance_text(tol)
    title = ed["title"]
    sheet_meta = {"title": title.get("title") or meta.get("title") or status.get("part") or "Part",
                  "drawing_no": title.get("drawing_no") or meta.get("drawing_no", ""),
                  "company": title.get("company", ""), "checked_by": title.get("checked_by", ""),
                  "material": status.get("material") or "Not specified",
                  "drawn_by": row.get("by", "") if issue is None else (issue.get("by") or row.get("by", "")),
                  "date": row.get("date", "") if issue is None else issue.get("date", ""), "rev": rev,
                  "tolerance": tol_txt,
                  "source": f"Model rev {row.get('rev', '—')} · build {str(row.get('build_id', ''))[-8:]}"}
    notes = ["DIMENSIONS IN MILLIMETRES. DO NOT SCALE.",
             "NOT APPROVED FOR MANUFACTURE: A QUALIFIED ENGINEER MUST REVIEW AND APPROVE THIS DRAWING."]
    if tol["mode"] == "none":
        notes.append("NO GENERAL TOLERANCES SPECIFIED.")
    else:  # printed exactly as chosen (ISO 2768 class letters are lower case)
        notes.append(f"GENERAL TOLERANCES {tol_txt}, AS SELECTED BY THE USER.")
    if any(d.get("tol") for d in shown_dims) or any(c.get("tol") for c in shown_callouts):
        notes.append("TOLERANCES AND FITS SHOWN AT INDIVIDUAL DIMENSIONS ARE ENTERED BY THE USER.")
    if rev == "DRAFT" and latest is not None:
        notes.append(f"DRAFT: CHANGES SINCE REV {latest['rev']} ARE NOT ISSUED.")
    # Parameters with no unambiguous match (mapping["unmapped"]) are listed in the Drawing Studio panel, never on the
    # sheet: model parameter names are not manufacturing information (and a reader takes them for missing sizes).
    notes += [n.upper() for n in notes_extra]
    notes += [str(n) for n in (meta.get("spec") or {}).get("notes") or []][:6]
    notes += ed["notes"]
    sheet = compose(an, shown_dims, shown_callouts, notes, opts, sheet_meta, rev_rows)
    expected = {v: bbox_extents(cen["bbox"], v) for v in ("front", "top", "right") if v in an["views"]}
    check = chk12(sheet, dims, callouts, mapping, cen, expected, hidden=hidden)
    t_layout = time.perf_counter() - t0 - t_geo
    doc_title = f"{sheet_meta['title']} — drawing {sheet_meta['drawing_no']} rev {rev}"
    issue_copy = issue_sheet(sheet)
    if issue is None:
        (dest / "sheet.svg").write_text(to_svg(sheet, doc_title), encoding="utf-8", newline="\n")
        (dest / "sheet_issue.svg").write_text(to_svg(issue_copy, doc_title), encoding="utf-8", newline="\n")
        to_pdf(sheet, dest / "sheet_review.pdf", doc_title)
    else:
        (dest / "sheet.svg").write_text(to_svg(issue_copy, doc_title), encoding="utf-8", newline="\n")
    to_pdf(issue_copy, dest / "sheet.pdf", doc_title)
    to_dxf(issue_copy, dest / "sheet.dxf")
    timings = {"geometry_s": round(t_geo, 3), "layout_s": round(t_layout, 3),
               "total_s": round(time.perf_counter() - t0, 3)}
    files = [n for n in ("sheet.svg", "sheet_issue.svg", "sheet.pdf", "sheet_review.pdf", "sheet.dxf")
             if (dest / n).is_file()]
    part = an["part"]
    rec = {
        "version": VERSION, "build_id": row.get("build_id"), "build": stamp, "model_rev": row.get("rev"),
        "sheet_rev": rev, "issued": issue is not None, "options": opts, "edits": ed,
        "sheet": {"size": sheet["size"], "w": sheet["w"], "h": sheet["h"], "scale": sheet["scale_txt"],
                  "iso_scale": sheet["iso_scale"], "projection": sheet["projection"],
                  "iso_dropped": sheet.get("iso_dropped", False)},
        "plan": {"turned": bool(part.get("turned")), "hollow": bool(part.get("hollow")),
                 "views": [v for v in pl["views"] if v in an["views"]],
                 "section": pl.get("kind") or pl["section"], "front_section": bool(pl.get("front_section")),
                 "note": pl.get("note")},
        "title": sheet_meta, "check": check, "revisions": rev_rows,
        "dimensions": [{"id": d["id"], "text": d["text"], "tag": d["tag"], "param": d["param"], "kind": d["kind"],
                        "view": d["view"], "aux": d["aux"], "value": d["value"], "tol": d.get("tol"),
                        "hidden": d["id"] in hidden} for d in dims],
        "callouts": [{"id": c["id"], "type": c.get("type", "hole"), "view": c["view"], "qty": c["qty"], "dia": c["dia"],
                      "thru": c["thru"], "tol": c.get("tol"), "hidden": c["id"] in hidden,
                      "lines": [{"text": ln["text"], "tag": ln["tag"], "param": ln["param"],
                                 "params": ln.get("params") or []} for ln in c["lines"]]}
                     for c in callouts],
        "mapping": mapping,
        "param_labels": {k: str((pmeta.get(k) or {}).get("label") or k)
                         for k in sorted({*mapping["mapped"], *mapping["unmapped"]})},
        "icd": {"mapped": sorted(k for k in mapping["mapped"] if k.startswith("ICD_")),
                "offered": sorted(k for k in params if k.startswith("ICD_"))},
        "census": {"bbox": cen["bbox"], "holes": len(cen["holes"]),
                                       "unsupported_holes": cen["unsupported_holes"]},
        "history": [{k: h.get(k) for k in ("rev", "date", "by", "change", "build_id")} for h in history],
        "files": {n: (dest / n).stat().st_size for n in files},
        "timings": timings,
    }
    (dest / "drawing.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec
