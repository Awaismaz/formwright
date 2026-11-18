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
the value and marked user-entered in the record), title-block fields and free notes, detail views (DRW-011: a circle
on a view, redrawn at a larger standard scale) and GD&T (DRW-013: datum symbols and feature control frames, only as
entered). Edits are keyed by stable dimension ids / view coordinates and re-applied on every regeneration; CHK-12
runs on the edited sheet.

Also drawn from the model, never invented: cosmetic threads (CAD-027, ``status["threads"]``) as ISO 6410-1 marks and
callouts; datums and frames a Design Office interface spec states (CD-021, ``meta["spec"]["gdt"]``), labelled as
such. An imported STEP (DRW-016, ``status["imported"]``) has no design parameters: every value is tagged inferred and
the sheet says so.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from aicad import deliverables
from aicad.drawing import VERSION, DrawingInputError
from aicad.drawing import detail as detail_mod
from aicad.drawing import gdt as gdt_mod
from aicad.drawing.check import chk12
from aicad.drawing.dims import candidates, fmt, tag, thread_lines
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
    out: dict[str, Any] = {"dims": dims, "title": title, "notes": [n for n in notes if n]}
    details = detail_mod.normalize(e.get("details"))
    g = gdt_mod.normalize(e.get("gdt"))
    if details:  # only when used, so edits without them keep their old shape
        out["details"] = details
    if g["datums"] or g["frames"]:
        out["gdt"] = g
    return out


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


def _main_line(c: dict[str, Any]) -> dict[str, Any]:
    """The callout line that carries the feature's own size (the drill Ø under a thread designation)."""
    return next((ln for ln in c["lines"] if ln.get("kind") in ("hole", "radius", "chamfer")), c["lines"][0])


def tolerance_text(t: dict[str, Any]) -> str:
    if t["mode"] == "iso2768":
        return f"ISO 2768-{t['class']} ({ISO2768[t['class']]})"
    if t["mode"] == "custom":
        return t["text"]
    return "Not specified"


def _analysis(step: Path, opts: dict[str, Any], threads: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    from aicad.drawing import geometry

    st = step.stat()
    key = (str(step.resolve()), st.st_mtime_ns, st.st_size, tuple(opts["views"] or ()), opts["views"] is None,
           opts["section"], VERSION, json.dumps(threads or [], sort_keys=True))
    if key not in _cache:
        if len(_cache) > 24:
            _cache.clear()
        _cache[key] = geometry.analyse(str(step), {"views": opts["views"], "section": opts["section"],
                                                   "threads": threads or []})
    return _cache[key]


def _recognition(ws: Path) -> dict[str, Any] | None:
    """The feature recognition of an imported STEP (the file the model script names in ``RECOGNITION``)."""
    try:
        src = (ws / "model.py").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^RECOGNITION = '([^'\n]+)'", src, re.MULTILINE)
    if not m or ".." in m.group(1):
        return None
    f = ws / m.group(1)
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except (OSError, ValueError):
        return None


def _details(an: dict[str, Any], reqs: list[dict[str, Any]], hidden: bool, datums: set[str] | None = None
             ) -> tuple[list[dict[str, Any]], list[str]]:
    """Detail views with their letters (after the section's A, never a datum's letter) and clipped geometry;
    requests on a view that is not drawn are reported, not drawn."""
    taken = ({"A"} if an.get("section") else set()) | set(datums or ())
    letters = detail_mod.letters(len(reqs), taken)
    out, skipped = [], []
    for d, letter in zip(reqs, letters, strict=False):
        parent = an["section"] if d["view"] == "section" and an.get("section") else an["views"].get(d["view"])
        if parent is None or (d["view"] == "front" and parent.get("is_section")):
            skipped.append(f"Detail {letter}: the {d['view']} view is not on the sheet.")
            continue
        out.append({**d, "letter": letter, "parent": d["view"], "geom": detail_mod.geometry(parent, d, hidden)})
    return out, skipped


def _gdt_items(an: dict[str, Any], dims: list[dict[str, Any]], callouts: list[dict[str, Any]],
               user: dict[str, Any], spec: dict[str, Any], hidden: list[str]
               ) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Datum symbols and feature control frames to draw, from the interface spec (first) and the user's edits, with
    their record. Nothing is added that was not given; references to a datum that is not on the sheet are refused."""
    by_id = {d["id"]: d for d in dims} | {c["id"]: c for c in callouts}
    items: list[dict[str, Any]] = []
    rec_d: list[dict[str, Any]] = []
    rec_f: list[dict[str, Any]] = []
    notes: list[str] = []
    unresolved: list[dict[str, Any]] = []
    letters: dict[str, str] = {}
    sg = (spec or {}).get("gdt") or {}
    icd_refs: set[str] = set()
    drawn_at: dict[str, str] = {}
    alias: dict[str, str] = {}
    for d in sg.get("datums") or []:
        hit = gdt_mod.resolve_model_target(d["target"], an, dims, callouts)
        if hit is None:
            unresolved.append({"type": "datum", "letter": d["letter"], "label": d.get("label"), "ref": d.get("ref")})
            continue
        tgt, view = hit
        tkey = json.dumps(tgt, sort_keys=True)
        if tkey in drawn_at:  # two ICD features on one drawn feature (coaxial seats): one datum, the letter aliased
            alias[d["letter"]] = drawn_at[tkey]
            continue
        drawn_at[tkey] = d["letter"]
        letters[d["letter"]] = "icd"
        icd_refs.add(str(d.get("ref") or ""))
        items.append({"type": "datum", "rec": {"letter": d["letter"]}, "target": tgt, "view": view,
                      "ref": f"datum-{d['letter']}"})
        rec_d.append({"letter": d["letter"], "source": "icd", "ref": d.get("ref"), "label": d.get("label"),
                      "target": tgt, "view": view})
    seen_frames: set[str] = set()
    for n, f in enumerate(sg.get("frames") or []):
        f = {**f, "datums": list(dict.fromkeys(alias.get(x, x) for x in f.get("datums") or []))}
        if any(x not in letters for x in f.get("datums") or []):
            unresolved.append({"type": "frame", "char": f["char"], "label": f.get("label"), "ref": f.get("ref")})
            continue
        hit = gdt_mod.resolve_model_target(f["target"], an, dims, callouts)
        if hit is None:
            unresolved.append({"type": "frame", "char": f["char"], "label": f.get("label"), "ref": f.get("ref")})
            continue
        tgt, view = hit
        fr = {"id": f"icd-{n + 1}", "char": f["char"], "tol": float(f["tol"]), "dia": bool(f.get("dia")),
              "mod": f.get("mod"), "datums": list(f.get("datums") or [])}
        key = json.dumps([tgt, fr["char"], fr["tol"], fr["dia"], fr["datums"]], sort_keys=True)
        if key in seen_frames:  # the holes of one pattern share one callout: one frame for the group
            continue
        seen_frames.add(key)
        icd_refs.add(str(f.get("ref") or ""))
        items.append({"type": "frame", "rec": fr, "target": tgt, "view": view, "ref": fr["id"]})
        rec_f.append({**fr, "source": "icd", "ref": f.get("ref"), "label": f.get("label"), "target": tgt, "view": view,
                      "text": gdt_mod.describe(fr)})
    conflicts = []
    for d in user.get("datums") or []:
        if d["letter"] in letters:
            conflicts.append(d["letter"])
            continue
        letters[d["letter"]] = "user"
    for d in user.get("datums") or []:
        if d["letter"] in conflicts:
            continue
        tgt = d["target"]
        view = by_id[tgt["id"]]["view"] if tgt["kind"] in ("dim", "callout") and tgt["id"] in by_id else tgt.get("view")
        if tgt["kind"] in ("dim", "callout") and (tgt["id"] not in by_id or tgt["id"] in hidden):
            unresolved.append({"type": "datum", "letter": d["letter"], "label": "dimension not on the sheet"})
            continue
        items.append({"type": "datum", "rec": {"letter": d["letter"]}, "target": tgt, "view": view,
                      "ref": f"datum-{d['letter']}"})
        rec_d.append({"letter": d["letter"], "source": "user", "target": tgt, "view": view})
    for f in user.get("frames") or []:
        missing = [x for x in f["datums"] if x not in letters]
        if missing:
            raise DrawingInputError(f"The {gdt_mod.CHARS[f['char']][0].lower()} frame refers to datum "
                                    f"{', '.join(missing)}, which is not on the drawing. Add the datum first.")
        tgt = f["target"]
        if tgt["kind"] in ("dim", "callout") and (tgt["id"] not in by_id or tgt["id"] in hidden):
            unresolved.append({"type": "frame", "char": f["char"], "label": "dimension not on the sheet"})
            continue
        view = by_id[tgt["id"]]["view"] if tgt["kind"] in ("dim", "callout") else tgt["view"]
        items.append({"type": "frame", "rec": f, "target": tgt, "view": view, "ref": f["id"]})
        rec_f.append({**f, "source": "user", "view": view, "text": gdt_mod.describe(f)})
    if conflicts:
        notes.append(f"Datum {', '.join(conflicts)} is already defined by the interface spec; your datum with that "
                     "letter is not drawn.")
    rec = {"datums": rec_d, "frames": rec_f, "unresolved": unresolved, "aliases": alias,
           "icd_version": sg.get("version"), "icd_interfaces": sorted(r for r in icd_refs if r)}
    return items, rec, notes


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
    an = _analysis(step, opts, status.get("threads") or [])
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
    imported = bool(status.get("imported"))
    if imported:  # DRW-016: an imported STEP's "parameters" were measured from it: nothing on the sheet is spec
        for d in dims:
            d["tag"], d["param"] = "inferred", None
        for c in callouts:
            c.pop("count_param", None)
            for ln in c["lines"]:
                if ln.get("source") != "thread":
                    ln["tag"], ln["param"] = "inferred", None
                    ln.pop("params", None)
        mapping = {"mapped": {}, "unmapped": sorted(k for k, v in params.items()
                                                    if isinstance(v, int | float) and not isinstance(v, bool)),
                   "kinds": mapping.get("kinds", {})}
        fits = {}
    # external cosmetic threads on a turned diameter: the designation replaces the Ø (ISO 6410-1)
    for d in dims:
        if d.get("thread"):
            d["text"] = d["thread"]["designation"]
            d["tag"] = "spec"
    # interface fits (Design Office ICD) printed after the value they belong to, unless the user wrote a tolerance
    for d in dims:
        if d.get("tag") == "spec" and d.get("param") in fits and not ed["dims"].get(d["id"], {}).get("tol"):
            d["text"] = f"{d['text']} {fits[d['param']]}"
            d["icd_fit"] = fits[d["param"]]
    for c in callouts:
        ln = _main_line(c)
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
            _main_line(c)["text"] += f" {tol}"
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
    recog = _recognition(out_dir.parent) if imported else None
    if imported:
        notes.append("DIMENSIONS INFERRED FROM IMPORTED GEOMETRY — VERIFY BEFORE USE.")
        comp = (recog or {}).get("component") or {}
        if comp.get("name"):
            notes.append(f"RECOGNISED AS: {str(comp['name']).upper()} (INFERRED).")
        unrec = sum(int(v) for v in ((recog or {}).get("unrecognised") or {}).values())
        if unrec:
            notes.append(f"{unrec} FACE(S) NOT RECOGNISED: SHOWN IN THE VIEWS, NOT DIMENSIONED.")
    if cen_threads := [h for h in cen["holes"] + cen["outer"] if h.get("thread")]:
        notes.append("THREADS ARE COSMETIC (ISO 6410-1); TAP DRILL SIZES ARE COMMON PRACTICE — VERIFY FOR YOUR TAP."
                     if any(h["thread"].get("internal") for h in cen_threads) else
                     "THREADS ARE COSMETIC (ISO 6410-1).")
    for d in dims:
        th = d.get("thread")
        if th and th.get("depth") is not None and d["id"] not in hidden:
            notes.append(f"THREAD {th['designation']}: {fmt(th['depth'])} LONG FROM THE END SHOWN BY THE THREAD LIMIT.")
    used = {d["letter"] for d in (ed.get("gdt") or {}).get("datums") or []} |         {d["letter"] for d in ((meta.get("spec") or {}).get("gdt") or {}).get("datums") or []}
    details, skipped_details = _details(an, ed.get("details") or [], opts.get("hidden", True), used)
    gdt_items, gdt_rec, gdt_notes = _gdt_items(an, shown_dims, shown_callouts, ed.get("gdt") or {},
                                               meta.get("spec") or {}, hidden)
    gdt_rec["notes"] = gdt_notes  # for the panel (a datum letter the interface spec already uses)
    if gdt_rec["icd_interfaces"]:
        notes.append(f"DATUMS AND GEOMETRIC TOLERANCES FROM THE INTERFACE SPEC (ICD v{gdt_rec['icd_version'] or '—'}: "
                     f"{', '.join(gdt_rec['icd_interfaces'])}). VERIFY.")
    if any(f["source"] == "user" for f in gdt_rec["frames"]):
        notes.append("GEOMETRIC TOLERANCES SHOWN WITHOUT AN ICD REFERENCE ARE ENTERED BY THE USER.")
    notes += [str(n) for n in (meta.get("spec") or {}).get("notes") or []][:6]
    notes += ed["notes"]
    an_sheet = {**an, "details": details, "gdt_items": gdt_items,
                "thread_lines": thread_lines(cen, enabled, shown_callouts)}
    sheet = compose(an_sheet, shown_dims, shown_callouts, notes, opts, sheet_meta, rev_rows)
    expected = {v: bbox_extents(cen["bbox"], v) for v in ("front", "top", "right") if v in an["views"]}
    check = chk12(sheet, dims, callouts, mapping, cen, expected, hidden=hidden,
                  gdt={"items": gdt_items, "record": gdt_rec})
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
                  "iso_dropped": sheet.get("iso_dropped", False),
                  # where each view sits on the sheet, so the app can turn a click into view coordinates
                  "views": {k: {"rect": [round(x, 4) for x in v["rect"]], "scale": v["scale"],
                                "origin": [round(x, 6) for x in v["origin"]]}
                            for k, v in sheet["views"].items() if k in ("front", "top", "right", "section")}},
        "details": {"drawn": sheet.get("details") or [], "skipped": skipped_details},
        "gdt": {**gdt_rec, "missing": sheet.get("gdt_missing") or []},
        "threads": [{"designation": h["thread"]["designation"], "internal": bool(h["thread"].get("internal")),
                     "depth": h["thread"].get("depth"), "feature": h["thread"].get("name"), "dia": h["dia"]}
                    for h in cen["holes"] + cen["outer"] if h.get("thread")],
        "threads_unmatched": (an.get("threads") or {}).get("unmatched", 0),
        "imported": {"inferred_only": True, "component": ((recog or {}).get("component") or {}).get("name"),
                     "unrecognised_faces": sum(int(v) for v in ((recog or {}).get("unrecognised") or {}).values())}
        if imported else None,
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
