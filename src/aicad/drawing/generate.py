"""Generate a drawing sheet for a project workspace: SVG + PDF + DXF + drawing.json under <workspace>/drawings/.

Associative (DRW-015): every generation reads the latest verified build (``out/part.step`` + ``out/status.json``).
When the build differs from the last drawn one, a revision row is added to ``history.json`` (model revision,
parameter changes, date, user) and shown in the sheet's revision table. Regenerating the same build reuses the
row, so the same model and options always give byte-identical SVG.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from aicad.drawing import VERSION, DrawingInputError
from aicad.drawing.check import chk12
from aicad.drawing.dims import candidates, fmt, tag
from aicad.drawing.layout import SHEETS, compose
from aicad.drawing.render import to_dxf, to_pdf, to_svg

ISO2768 = {"f": "fine", "m": "medium", "c": "coarse", "v": "very coarse"}
VIEW_CHOICES = ("front", "top", "right", "iso")
_cache: dict[tuple[Any, ...], dict[str, Any]] = {}


def normalize_options(o: dict[str, Any] | None) -> dict[str, Any]:
    o = dict(o or {})
    sheet = o.get("sheet") if o.get("sheet") in SHEETS else "A3"
    proj = o.get("projection") if o.get("projection") in ("first", "third") else "first"
    views = [v for v in VIEW_CHOICES if v in (o.get("views") or VIEW_CHOICES)]
    if "front" not in views:
        views.insert(0, "front")
    sec = o.get("section")
    sec = sec if sec in ("x", "y", "z") else None
    tol = o.get("tolerance") or {}
    mode = tol.get("mode") if tol.get("mode") in ("none", "iso2768", "custom") else "none"
    tclass = tol.get("class") if tol.get("class") in ISO2768 else "m"
    text = " ".join(str(tol.get("text") or "").split())[:60]
    if mode == "custom" and not text:
        mode = "none"
    return {"sheet": sheet, "projection": proj, "views": views, "section": sec, "hidden": o.get("hidden", True) is not False,
            "tolerance": {"mode": mode, "class": tclass if mode == "iso2768" else None,
                          "text": text if mode == "custom" else None}}


def tolerance_text(t: dict[str, Any]) -> str:
    if t["mode"] == "iso2768":
        return f"ISO 2768-{t['class']} ({ISO2768[t['class']]})"
    if t["mode"] == "custom":
        return t["text"]
    return "Not specified"


def _analysis(step: Path, views: list[str], section: str | None) -> dict[str, Any]:
    from aicad.drawing import geometry

    st = step.stat()
    key = (str(step.resolve()), st.st_mtime_ns, st.st_size, tuple(views), section, VERSION)
    if key not in _cache:
        if len(_cache) > 24:
            _cache.clear()
        _cache[key] = geometry.analyse(str(step), views, section)
    return _cache[key]


def _history(path: Path, status: dict[str, Any], meta: dict[str, Any]) -> list[dict[str, Any]]:
    hist: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    bid = str(status.get("build_id") or status.get("step_sha256") or "")
    if hist and hist[-1].get("build_id") == bid:
        return hist
    params = {k: v for k, v in (status.get("params") or {}).items() if isinstance(v, (int, float))}
    if not hist:
        change = "Initial issue"
    else:
        prev = hist[-1].get("params") or {}
        diffs = [f"{k} {fmt(prev[k])}→{fmt(v)}" for k, v in sorted(params.items())
                 if k in prev and abs(float(prev[k]) - float(v)) > 1e-9]
        diffs += [f"{k} added" for k in sorted(params) if k not in prev]
        change = ("Regenerated: " + ", ".join(diffs)) if diffs else "Regenerated: model geometry changed"
    hist.append({"rev": meta.get("model_rev") or str(len(hist) + 1), "build_id": bid, "date": meta.get("date", ""),
                 "by": meta.get("drawn_by", ""), "change": change, "params": params,
                 "fingerprint": status.get("fingerprint")})
    path.write_text(json.dumps(hist, indent=1, sort_keys=True), encoding="utf-8")
    return hist


def generate(out_dir: Path, dest: Path, options: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    """Build the sheet for the verified model in ``out_dir`` and write the files to ``dest``.

    ``meta``: title, drawing_no, drawn_by, date (YYYY-MM-DD), model_rev."""
    t0 = time.perf_counter()
    from aicad.drawing.geometry import bbox_extents

    step, status_p = out_dir / "part.step", out_dir / "status.json"
    if not step.is_file() or not status_p.is_file():
        raise DrawingInputError("This project has no verified build yet. Build the model in the Design Studio first.")
    status = json.loads(status_p.read_text(encoding="utf-8"))
    if not status.get("ok"):
        raise DrawingInputError("The latest build did not pass its checks. Fix the model before drawing it.")
    opts = normalize_options(options)
    dest.mkdir(parents=True, exist_ok=True)
    an = _analysis(step, opts["views"], opts["section"])
    t_geo = time.perf_counter() - t0
    cen = an["census"]
    enabled = set(opts["views"])
    dims, callouts, notes_extra = candidates(cen, enabled)
    mapping = tag(dims, callouts, status.get("params") or {}, status.get("param_meta") or {})
    history = _history(dest / "history.json", status, meta)
    row = history[-1]
    tol = tolerance_text(opts["tolerance"])
    sheet_meta = {"title": meta.get("title") or status.get("part") or "Part", "drawing_no": meta.get("drawing_no", ""),
                  "material": status.get("material") or "Not specified", "drawn_by": row.get("by", ""),
                  "date": row.get("date", ""), "rev": str(row.get("rev", "—")), "tolerance": tol,
                  "source": f"Model rev {row.get('rev', '—')} · build {str(row.get('build_id', ''))[-8:]}"}
    notes = ["DIMENSIONS IN MILLIMETRES. DO NOT SCALE.",
             "NOT APPROVED FOR MANUFACTURE: A QUALIFIED ENGINEER MUST REVIEW AND APPROVE THIS DRAWING.",
             "SPEC = EQUALS A DECLARED MODEL PARAMETER. INFERRED = MEASURED FROM THE MODEL. VERIFY BEFORE USE."]
    if opts["tolerance"]["mode"] == "none":
        notes.append("NO TOLERANCES SPECIFIED.")
    else:  # printed exactly as chosen (ISO 2768 class letters are lower case)
        notes.append(f"GENERAL TOLERANCES {tol}, AS SELECTED BY THE USER. NO OTHER TOLERANCES OR GD&T.")
    # Parameters with no unambiguous match (mapping["unmapped"]) are listed in the Drawing Studio panel, never on the
    # sheet: model parameter names are not manufacturing information (and a reader takes them for missing sizes).
    notes += [n.upper() for n in notes_extra]
    sheet = compose(an, dims, callouts, notes, opts, sheet_meta, history)
    expected = {v: bbox_extents(cen["bbox"], v) for v in ("front", "top", "right") if v in enabled}
    check = chk12(sheet, dims, callouts, mapping, cen, expected)
    t_layout = time.perf_counter() - t0 - t_geo
    title = f"{sheet_meta['title']} — drawing {sheet_meta['drawing_no']} rev {sheet_meta['rev']}"
    svg = to_svg(sheet, title)
    (dest / "sheet.svg").write_text(svg, encoding="utf-8", newline="\n")
    to_pdf(sheet, dest / "sheet.pdf", title)
    to_dxf(sheet, dest / "sheet.dxf")
    timings = {"geometry_s": round(t_geo, 3), "layout_s": round(t_layout, 3),
               "total_s": round(time.perf_counter() - t0, 3)}
    rec = {
        "version": VERSION, "build_id": row.get("build_id"), "model_rev": row.get("rev"), "options": opts,
        "sheet": {"size": sheet["size"], "w": sheet["w"], "h": sheet["h"], "scale": sheet["scale_txt"],
                  "iso_scale": sheet["iso_scale"], "projection": sheet["projection"]},
        "title": sheet_meta, "check": check,
        "dimensions": [{"id": d["id"], "text": d["text"], "tag": d["tag"], "param": d["param"], "kind": d["kind"],
                        "view": d["view"], "aux": d["aux"], "value": d["value"]} for d in dims],
        "callouts": [{"id": c["id"], "view": c["view"], "qty": c["qty"], "dia": c["dia"], "thru": c["thru"],
                      "lines": [{"text": ln["text"], "tag": ln["tag"], "param": ln["param"]} for ln in c["lines"]]}
                     for c in callouts],
        "mapping": mapping, "census": {"bbox": cen["bbox"], "holes": len(cen["holes"]),
                                       "unsupported_holes": cen["unsupported_holes"]},
        "history": [{k: h.get(k) for k in ("rev", "date", "by", "change", "build_id")} for h in history],
        "files": {n: (dest / n).stat().st_size for n in ("sheet.svg", "sheet.pdf", "sheet.dxf")},
        "timings": timings,
    }
    (dest / "drawing.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec
