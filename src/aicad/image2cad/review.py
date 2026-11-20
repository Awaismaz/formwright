"""The review: "What we read / What we need".

``state(read, review)`` merges what was read with the user's edits and answers and returns:
  dims        effective dimensions (edited, excluded, kind changed) in display order
  needs       every open question, each blocking until answered. A reference dimension is always required:
              scale stays undefined until the user confirms one real size.
  ready       True only when nothing is open
  scale       what we know about scale and units, with the evidence for each
  assumptions what the design agent must state because the drawing does not give it

``handoff_prompt`` turns a ready state into the one structured message the design agent receives.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from aicad.image2cad import InputError
from aicad.image2cad.tokens import fmt, label, parse
from aicad.image2cad.vision import LOW_CONFIDENCE

KIND_NAMES = {"linear": "length", "diameter": "diameter", "radius": "radius", "spherical_radius": "spherical radius",
              "spherical_diameter": "spherical diameter", "square": "square", "thread": "thread", "angle": "angle",
              "chamfer": "chamfer"}
SIZE_KINDS = ("linear", "diameter", "radius", "square", "spherical_radius", "spherical_diameter")
UNITS = ("mm", "in")
_HANDLED = re.compile(r"(?i)^\s*(units?|(general )?tolerances?|scale)\s*$")
# Vision lists everything a drawing doesn't give. Only sizes that change the model are questions; documentation
# (tolerances, approval, finish, treatment, material, title-block fields) becomes a note, never a blocking question.
_DOC = re.compile(r"(?i)(toleranc|approv|sign[- ]?off|release status|status for|finish|roughness|\bra\b|"
                  r"coating|plating|anodi[sz]|paint|heat[- ]?treat|harden|revision|\brev\b|drawn by|"
                  r"checked by|\btitle\b|drawing (no|number)|part (no|number)|material|weight|\bmass\b|"
                  r"deburr|break (all )?(sharp )?edges|inspection|quantity|\bqty\b|\bnotes?\b|\bdate\b)")


def is_documentation(item: dict[str, Any]) -> bool:
    """True when a missing item does not change the model's geometry (it is documentation, not a size)."""
    return bool(_DOC.search(f"{item.get('what') or ''}"))


_NO_FIELDS = ("DRAWING NO", "DWG NO", "DWG. NO", "PART NO", "DRAWING NUMBER")
_CODE_IN_PARENS = re.compile(r"\s*[(\[]\s*(?:dwg\.?\s*|drawing\s*(?:no\.?|number)\s*:?\s*)?([A-Z0-9][A-Z0-9._/-]*\d[A-Z0-9._/-]*)\s*[)\]]\s*$",
                             re.IGNORECASE)


def drawing_number(read: dict[str, Any]) -> str | None:
    """The drawing number from the title block (vector) or as read by vision; None when not written."""
    title = read.get("title") or {}
    for k, v in title.items():
        if any(k.upper().rstrip(".:").startswith(f.rstrip(".")) for f in _NO_FIELDS) and str(v).strip():
            return " ".join(str(v).split())[:40]
    no = read.get("drawing_no")
    if no:
        return " ".join(str(no).split())[:40]
    m = _CODE_IN_PARENS.search(read.get("part") or "")
    return m.group(1) if m else None


def suggested_name(read: dict[str, Any], filename: str | None) -> str | None:
    """Project name: the title read from the title block, else the read part name without its drawing number,
    else the file name without its extension (None when there is nothing)."""
    title = read.get("title") or {}
    t = next((v for k, v in title.items() if k.upper().rstrip(".:") in ("TITLE", "PART NAME", "DESCRIPTION")
              and str(v).strip()), None) or read.get("title_text")
    if not t and read.get("part") and len(str(read["part"]).split()) <= 6:  # a short name, not a description
        t = _CODE_IN_PARENS.sub("", read["part"])
    if not t and filename:
        t = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", filename)
    t = " ".join(str(t or "").split()).strip(" .,;:-")
    return t[:80] or None


def empty_review() -> dict[str, Any]:
    return {"dims": {}, "added": [], "answers": {}, "reference": None, "notes": ""}


def clean_review(raw: dict[str, Any], read: dict[str, Any]) -> dict[str, Any]:
    """Validate a review posted by the client. Unknown ids are dropped; edited texts must parse."""
    out = empty_review()
    ids = {d["id"] for d in read.get("dims", [])}
    for k, v in (raw.get("dims") or {}).items():
        if k not in ids or not isinstance(v, dict):
            continue
        o: dict[str, Any] = {}
        if isinstance(v.get("text"), str) and v["text"].strip():
            d = parse(v["text"])
            if d is None or d["kind"] == "scale":
                raise InputError(f"“{v['text'][:40]}” isn't a dimension we can read. Use forms like 100, Ø12 H7, "
                                 "R5, 4X Ø6.6 THRU, M8x1.25, 25±0.1 or 45°.")
            o["text"] = d["text"]
        if v.get("excluded") is True:
            o["excluded"] = True
        if v.get("confirmed") is True:
            o["confirmed"] = True
        if isinstance(v.get("describes"), str):
            o["describes"] = " ".join(v["describes"].split())[:100]
        if o:
            out["dims"][k] = o
    for a in (raw.get("added") or [])[:40]:
        if not isinstance(a, dict) or not str(a.get("text") or "").strip():
            continue
        d = parse(str(a["text"]))
        if d is None or d["kind"] == "scale":
            raise InputError(f"“{str(a['text'])[:40]}” isn't a dimension we can read. Use forms like 100, Ø12 H7, "
                             "R5, 4X Ø6.6 THRU, M8x1.25, 25±0.1 or 45°.")
        out["added"].append({"id": f"u{len(out['added']) + 1}", "text": d["text"],
                             "describes": " ".join(str(a.get("describes") or "").split())[:100] or None,
                             "view": str(a.get("view") or "")[:8] or None})
    for k, v in (raw.get("answers") or {}).items():
        if isinstance(v, dict) and len(str(k)) <= 40:
            ans: dict[str, Any] = {}
            if isinstance(v.get("choice"), str):
                ans["choice"] = v["choice"][:120]
            if isinstance(v.get("text"), str):
                ans["text"] = " ".join(v["text"].split())[:300]
            if isinstance(v.get("value"), (int, float)) and v["value"] > 0:
                ans["value"] = float(v["value"])
            if v.get("unit") in UNITS:
                ans["unit"] = v["unit"]
            if ans:
                out["answers"][str(k)] = ans
    ref = raw.get("reference")
    if isinstance(ref, dict):
        r: dict[str, Any] = {}
        if ref.get("dim") in ids or any(a["id"] == ref.get("dim") for a in out["added"]):
            r["dim"] = ref["dim"]
        if isinstance(ref.get("value"), (int, float)) and ref["value"] > 0:
            r["value"] = float(ref["value"])
        if ref.get("unit") in UNITS:
            r["unit"] = ref["unit"]
        r["describes"] = " ".join(str(ref.get("describes") or "").split())[:100] or None
        out["reference"] = r
    out["notes"] = " ".join(str(raw.get("notes") or "").split())[:1000]
    return out


def _view_name(read: dict[str, Any], vid: str | None) -> str | None:
    v = next((v for v in read.get("views", []) if v["id"] == vid), None)
    return v["name"] if v else None


def effective_dims(read: dict[str, Any], review: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    answers = review.get("answers", {})
    for d0 in read.get("dims", []):
        d = copy.deepcopy(d0)
        ov = review.get("dims", {}).get(d["id"], {})
        d["read_text"] = d0["text"]
        d["edited"] = False
        a = answers.get(f"confirm_{d['id']}", {})
        alt = a.get("choice")
        if alt and alt not in ("keep", "exclude"):
            p = parse(alt)
            if p and p["kind"] != "scale":
                d.update({k: v for k, v in p.items()})
                d["edited"] = True
        if ov.get("text") and ov["text"] != d0["text"]:
            p = parse(ov["text"])
            if p:
                d.update(p)
                d["edited"] = True
        k = answers.get(f"kind_{d['id']}", {}).get("choice")
        if k in KIND_NAMES and k != d["kind"]:
            d["kind"] = k
            d["edited"] = True
        if ov.get("describes"):
            d["describes"] = ov["describes"]
        d["excluded"] = bool(ov.get("excluded")) or alt == "exclude" or \
            answers.get(f"conflict_{d['id']}", {}).get("choice") == "exclude"
        d["confirmed"] = bool(ov.get("confirmed")) or alt is not None or d["edited"]
        d["label"] = label(d)
        out.append(d)
    for a in review.get("added", []):
        p = parse(a["text"]) or {}
        out.append({**p, "id": a["id"], "x": None, "y": None, "box": None, "view": a.get("view"), "dir": None,
                    "confidence": 1.0, "source": "user", "describes": a.get("describes"), "read_text": None,
                    "edited": False, "excluded": False, "confirmed": True, "label": label(p)})
    # unparsed readings the user turned into a callout
    for i, u in enumerate(read.get("unparsed", [])):
        ans = answers.get(f"unparsed_{i}", {})
        if ans.get("choice") == "callout" and ans.get("text"):
            p = parse(ans["text"])
            if p and p["kind"] != "scale":
                out.append({**p, "id": f"p{i}", "x": u.get("x"), "y": u.get("y"), "box": None, "view": None,
                            "dir": None, "confidence": 1.0, "source": "user", "describes": u.get("describes"),
                            "read_text": u["text"], "edited": True, "excluded": False, "confirmed": True,
                            "label": label(p)})
    return out


def _ref_options(dims: list[dict[str, Any]], read: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    sizes = [d for d in dims if not d["excluded"] and d.get("kind") in SIZE_KINDS and not d.get("reference")]
    matched = {c["dim"] for c in read.get("checks", []) if c.get("match")}
    sizes.sort(key=lambda d: (d["id"] not in matched, -(d.get("value") or 0)))
    opts = []
    for d in sizes[:8]:
        where = _view_name(read, d.get("view"))
        what = d.get("describes") or (f"{d['dir']} {KIND_NAMES[d['kind']]}" if d.get("dir") else KIND_NAMES[d["kind"]])
        opts.append({"value": d["id"], "label": d["label"], "hint": ", ".join(x for x in (what, where) if x),
                     "matched": d["id"] in matched})
    return opts, (opts[0]["value"] if opts else None)


def state(read: dict[str, Any], review: dict[str, Any] | None) -> dict[str, Any]:
    review = review or empty_review()
    answers = review.get("answers", {})
    dims = effective_dims(read, review)
    by_id = {d["id"]: d for d in dims}
    needs: list[dict[str, Any]] = []
    units = read.get("units") or None

    def need(**kw: Any) -> None:
        a = answers.get(kw["id"])
        kw.setdefault("answer", a)
        kw.setdefault("answered", bool(a))
        kw.setdefault("blocking", True)
        needs.append(kw)

    # 1. reference dimension: always required
    ref = review.get("reference") or {}
    opts, sugg = _ref_options(dims, read)
    ref_ok = bool(ref.get("value") and ref.get("unit") and (ref.get("dim") in by_id or ref.get("describes")))
    if ref.get("dim") in by_id and by_id[ref["dim"]]["excluded"]:
        ref_ok = False
    need(id="reference", kind="reference", question="Confirm one real dimension",
         detail=("Scale stays undefined until you confirm a size you know is right. Pick a dimension we read and "
                 "check its value and units, or enter one you know (for a sketch or photo: any real size, e.g. the "
                 "overall length)."),
         options=opts, default=sugg, default_unit=(units or {}).get("value"), answer=ref or None, answered=ref_ok)

    # 2. which view is the front
    views = read.get("views", [])
    ortho = [v for v in views if v.get("kind") == "ortho"]
    if len(ortho) >= 2 and not any("FRONT" in (v.get("label") or "").upper() for v in views):
        sug = next((v["id"] for v in ortho if v.get("suggest_front") or v.get("looks_like") == "front"), ortho[0]["id"])
        need(id="front_view", kind="choice", question="Which view is the front?",
             detail="The views aren't labelled. The suggestion is the view the others are arranged around.",
             options=[{"value": v["id"], "label": v["name"],
                       "hint": ", ".join(x for x in (v.get("place"), _size_hint(v)) if x)} for v in ortho],
             default=sug, x=_cx(next(v for v in ortho if v["id"] == sug)),
             y=_cy(next(v for v in ortho if v["id"] == sug)))

    # 3. per-dimension doubts (vision): low confidence, unclear kind
    for d in dims:
        if d["source"] != "vision" or d["excluded"] and not answers.get(f"confirm_{d['id']}"):
            continue
        if d["confidence"] < LOW_CONFIDENCE and not review.get("dims", {}).get(d["id"], {}).get("confirmed"):
            opts2 = [{"value": "keep", "label": label({**d, **(parse(d["read_text"]) or {})})}]
            opts2 += [{"value": a, "label": a} for a in d.get("alternatives", []) if parse(a)]
            opts2.append({"value": "exclude", "label": "Leave it out"})
            need(id=f"confirm_{d['id']}", kind="confirm", dim=d["id"], x=d.get("x"), y=d.get("y"),
                 question=f"Is “{d['read_text']}” read correctly?",
                 detail=f"Read with {round(d['confidence'] * 100)}% confidence." +
                        (f" It seems to give the {d['describes']}." if d.get("describes") else ""),
                 options=opts2, default=None, input="callout")
        kinds = [k for k in d.get("kind_unclear", []) if k in KIND_NAMES]
        if len(kinds) >= 2:
            need(id=f"kind_{d['id']}", kind="choice", dim=d["id"], x=d.get("x"), y=d.get("y"),
                 question=f"Is {fmt(d.get('value'))} a {' or a '.join(KIND_NAMES[k] for k in kinds[:3])}?",
                 detail="The symbol in front of the number can't be read with certainty.",
                 options=[{"value": k, "label": KIND_NAMES[k].capitalize()} for k in kinds[:3]], default=None)

    # 4. scale conflicts (vector): a dimension bigger than its view drawn at the stated scale
    for c in read.get("checks", []):
        if c.get("conflict") and c["dim"] in by_id:
            d = by_id[c["dim"]]
            need(id=f"conflict_{d['id']}", kind="choice", dim=d["id"], x=d.get("x"), y=d.get("y"),
                 question=f"{d['label']} is larger than its view drawn at {_ratio(read)}",
                 detail=f"The view measures {fmt(c['at_scale'])} mm at the stated scale. The drawing may not be to "
                        "scale, or the dimension may belong to another view.",
                 options=[{"value": "keep", "label": "Keep the dimension (drawing not to scale)"},
                          {"value": "exclude", "label": "Leave it out"}], default=None)

    # 5. numbers we could not interpret
    for i, u in enumerate(read.get("unparsed", [])):
        a = answers.get(f"unparsed_{i}", {})
        need(id=f"unparsed_{i}", kind="unparsed", x=u.get("x"), y=u.get("y"),
             question=f"What is “{u['text']}”?",
             detail="It holds a number but isn't a dimension callout we recognise." +
                    (f" It may be the {u['describes']}." if u.get("describes") else ""),
             options=[{"value": "callout", "label": "It's a dimension…"},
                      {"value": "note", "label": "Pass it on as a note"},
                      {"value": "ignore", "label": "Ignore it"}], default=None, input="callout",
             answered=a.get("choice") in ("ignore", "note") or (a.get("choice") == "callout" and bool(parse(a.get("text") or ""))))

    # 6. unreadable areas (vision)
    for i, u in enumerate(read.get("unreadable", [])):
        a = answers.get(f"unreadable_{i}", {})
        need(id=f"unreadable_{i}", kind="unreadable", x=u.get("x"), y=u.get("y"),
             question="Unreadable: " + u["note"],
             detail="Tell us what it says, or confirm it doesn't matter for the model.",
             options=[{"value": "ignore", "label": "Doesn't matter"}, {"value": "text", "label": "It says…"}],
             default=None, input="text",
             answered=a.get("choice") == "ignore" or (a.get("choice") == "text" and bool(a.get("text"))))

    # 7. missing sizes
    # units are set with the reference and tolerances are stated as an assumption: not separate questions
    listed = [m for m in read.get("missing", []) if not _HANDLED.match(m.get("what") or "")]
    documentation = [m for m in listed if is_documentation(m)]
    missing = [m for m in listed if not is_documentation(m)]
    if read.get("method") == "vector" and len([v for v in views if v.get("kind") in ("ortho", "section")]) == 1:
        missing.append({"what": "Depth (the third dimension)", "why": "Only one view is drawn"})
    if not [d for d in dims if not d["excluded"]]:
        missing.append({"what": "Overall sizes", "why": "No dimensions were read"})
    for i, m in enumerate(missing):
        a = answers.get(f"missing_{i}", {})
        need(id=f"missing_{i}", kind="missing", question=f"Missing: {m['what']}", detail=m.get("why"),
             options=[{"value": "value", "label": "I know it…"},
                      {"value": "estimate", "label": "Estimate (flagged)"},
                      {"value": "not_needed", "label": "Not needed"}],
             default=None, input="value", default_unit=(units or {}).get("value"),
             answered=a.get("choice") in ("estimate", "not_needed") or
                      (a.get("choice") == "value" and bool(a.get("value")) and bool(a.get("unit"))))

    open_n = sum(1 for n in needs if n["blocking"] and not n["answered"])
    return {"dims": dims, "needs": needs, "open": open_n, "ready": open_n == 0,
            "scale": scale_state(read, review, by_id), "assumptions": assumptions(read, review, dims, missing),
            "documentation": documentation, "name": suggested_name(read, None),
            "drawing_no": drawing_number(read)}


def dim_what(d: dict[str, Any], read: dict[str, Any]) -> str:
    """Plain description of a dimension: what it measures and where, e.g. 'horizontal length, View 2'."""
    what = d.get("describes") or (f"{d['dir']} {KIND_NAMES.get(d['kind'], d['kind'])}" if d.get("dir")
                                  else KIND_NAMES.get(d.get("kind") or "", "size"))
    where = _view_name(read, d.get("view"))
    return f"{what}, {where}" if where else what


def _ratio(read: dict[str, Any]) -> str:
    s = read.get("scale")
    return s["text"] if s else "the stated scale"


def _size_hint(v: dict[str, Any]) -> str | None:
    dm = v.get("drawn_mm")
    return f"drawn {fmt(dm[0])} × {fmt(dm[1])} mm" if dm else None


def _cx(v: dict[str, Any]) -> float | None:
    b = v.get("box")
    return (b[0] + b[2]) / 2 if b else None


def _cy(v: dict[str, Any]) -> float | None:
    b = v.get("box")
    return (b[1] + b[3]) / 2 if b else None


def scale_state(read: dict[str, Any], review: dict[str, Any], by_id: dict[str, Any]) -> dict[str, Any]:
    ref = review.get("reference") or {}
    units = read.get("units")
    out: dict[str, Any] = {"stated": read.get("scale"), "units": units, "reference": None, "status": "undefined",
                           "evidence": [], "summary": "Undefined until you confirm a reference dimension."}
    for c in read.get("checks", []):
        if c.get("match"):
            vn = _view_name(read, c["view"])
            out["evidence"].append(f"{vn}: drawn {c['axis']} {fmt(c['drawn_mm'])} mm at {_ratio(read)} = "
                                   f"{by_id[c['dim']]['label'] if c['dim'] in by_id else fmt(c['value'])}")
    if not (ref.get("value") and ref.get("unit")):
        return out
    d = by_id.get(ref.get("dim") or "")
    what = ref.get("describes") or (dim_what(d, read) if d else "reference size")
    out["reference"] = {"dim": ref.get("dim"), "value": ref["value"], "unit": ref["unit"], "describes": what,
                        "label": d["label"] if d else None}
    out["status"] = "confirmed"
    if d and abs((d.get("value") or 0) - ref["value"]) > 1e-9:
        out["status"] = "corrected"
    ref_txt = f"{fmt(ref['value'])} {ref['unit']}"
    if read.get("method") == "vector":
        st = read.get("scale")
        out["summary"] = (f"Sizes come from the drawing's dimensions in {ref['unit']}. Reference confirmed: {ref_txt} "
                          f"({what})."
                          + (f" Stated scale {st['text']}." if st else " No scale is stated on the drawing; the model "
                             "uses the written dimensions only."))
    else:
        out["summary"] = (f"Set by your reference: {ref_txt} ({what}). Sizes that aren't written are never measured "
                          "from the image unless you choose to estimate them.")
    if units and units.get("value") and units["value"] != ref["unit"]:
        out["warning"] = (f"The drawing indicates {units['value']} ({units['evidence']}) but your reference is in "
                          f"{ref['unit']}.")
    return out


def assumptions(read: dict[str, Any], review: dict[str, Any], dims: list[dict[str, Any]],
                missing: list[dict[str, Any]]) -> list[str]:
    out = []
    live = [d for d in dims if not d["excluded"]]
    if live and not any(d.get("tol") or d.get("fit") for d in live) and \
            not any("TOLERANCE" in k for k in (read.get("title") or {})):
        out.append("No tolerances were read: the model is built at nominal sizes.")
    gt = next((v for k, v in (read.get("title") or {}).items() if "TOLERANCE" in k), None)
    if gt and re.fullmatch(r"(?i)\s*(not specified|none|n/?a|[-\u2014\u2013]+)\s*", gt):
        out.append("No tolerances are specified on the drawing: the model is built at nominal sizes.")
    elif gt:
        out.append(f"General tolerances on the drawing: {gt}. The model is built at nominal sizes.")
    answers = review.get("answers", {})
    for i, m in enumerate(missing):
        if answers.get(f"missing_{i}", {}).get("choice") == "estimate":
            out.append(f"{m['what']} is not given: estimate it and state the value as assumed.")
    if any(d.get("view") is None for d in live) and len(read.get("views", [])) > 1:
        out.append("Some dimensions could not be tied to a view: place them where they make sense in the reference "
                   "and say how you interpreted them.")
    if read.get("method") == "vision":
        out.append("Values were read from an image by vision and reviewed by the user; the image is not to scale.")
    return out


# ----------------------------------------------------------------------------- hand-off
def handoff_prompt(meta: dict[str, Any], read: dict[str, Any], st: dict[str, Any], review: dict[str, Any]) -> str:
    """The one structured message the design agent gets. Contains exactly the confirmed, included values."""
    if not st["ready"]:
        raise InputError("Answer the open questions before creating the model.")
    sc = st["scale"]
    ref = sc["reference"]
    unit = ref["unit"]
    src = {"vector": "a vector PDF drawing (dimensions read from the drawing text)",
           "vision": f"a {read.get('drawing_kind', 'drawing')} image (values read by vision, then checked by me)"}
    lines = [(f"Model this part from {src.get(read.get('method'), 'a drawing')} that I reviewed: “{meta['name']}”. "
              "The drawing is attached as a reference image."), ""]
    name, no = st.get("name") or suggested_name(read, None), st.get("drawing_no")
    if name:
        lines.append(f"Part name: {name}" + (f" (drawing number {no}: keep it out of the part name)" if no else ""))
    if read.get("part") and read["part"] != name:
        lines.append(f"What it is: {read['part']}")
    if name or read.get("part"):
        lines.append("")
    lines.append(f"Units: {unit}. Reference dimension (confirmed by me): {fmt(ref['value'])} {unit}, {ref['describes']}.")
    if read.get("scale"):
        lines.append(f"Drawing scale: {read['scale']['text']} ({read['scale']['evidence'].lower()}).")
    else:
        lines.append("Drawing scale: not stated. Do not derive sizes from the image.")
    answers = review.get("answers", {})
    fv = answers.get("front_view", {}).get("choice")
    views = {v["id"]: v for v in read.get("views", [])}
    if fv in views:
        lines.append(f"Front view: {views[fv]['name']}" + (f" ({views[fv]['place']})" if views[fv].get("place") else "") + ".")
    if len(views) > 1:
        kinds = {"iso": "isometric", "section": "section", "detail": "detail"}
        lines.append("Views on the sheet: " + "; ".join(
            v["name"] + (f" ({kinds[v['kind']]})" if v["kind"] in kinds else f" ({v['place']})" if v.get("place") else "")
            for v in views.values()) + ".")
    if read.get("projection"):
        lines.append(f"Projection: {read['projection']['value']} angle.")
    lines += ["", "Confirmed dimensions (use exactly these values):"]
    live = [d for d in st["dims"] if not d["excluded"]]
    order = list(views) + [None]
    n = 0
    for vid in order:
        group = [d for d in live if d.get("view") == vid or (vid is None and d.get("view") not in views)]
        if not group:
            continue
        vname = views[vid]["name"] if vid in views else "View not identified"
        if vid in views and views[vid].get("place"):
            vname += f", {views[vid]['place']}"
        if vid in views and vid == fv:
            vname += ", FRONT"
        lines.append(f"- {vname}:")
        for d in group:
            n += 1
            bits = []
            if d.get("dir") and d["kind"] == "linear":
                bits.append(d["dir"])
            if d.get("describes"):
                bits.append(d["describes"])
            if d.get("reference"):
                bits.append("reference dimension, not for manufacture")
            if d["source"] == "vision":
                bits.append("read by vision, confirmed by me" if d["confirmed"] else "read by vision")
            if d["edited"]:
                bits.append(f"corrected by me from “{d['read_text']}”" if d.get("read_text") else "corrected by me")
            if d["source"] == "user":
                bits.append("added by me")
            lines.append(f"  {n}. {d['label']}" + (f" ({'; '.join(bits)})" if bits else ""))
    if n == 0:
        lines.append("- none beyond the reference dimension")
    extra = []
    for nd in st["needs"]:
        a = nd.get("answer") or {}
        if nd["kind"] == "missing" and a.get("choice") == "value":
            extra.append(f"{nd['question'].removeprefix('Missing: ')} = {fmt(a['value'])} {a['unit']}")
        elif nd["kind"] == "missing" and a.get("choice") == "not_needed":
            extra.append(f"{nd['question'].removeprefix('Missing: ')}: not needed")
        elif nd["kind"] == "unparsed" and a.get("choice") == "note":
            extra.append(f"Note written on the drawing: {nd['question'].removeprefix('What is ').rstrip('?')}")
        elif nd["kind"] == "unreadable" and a.get("choice") == "text":
            extra.append(f"{nd['question'].removeprefix('Unreadable: ')}: it says “{a['text']}”")
        elif nd["kind"] == "choice" and nd["id"].startswith("conflict_") and a.get("choice") == "keep":
            extra.append(f"{nd['question']}: keep the dimension, the drawing is not to scale")
    if extra:
        lines += ["", "My answers:"] + [f"- {e}" for e in extra]
    if st["assumptions"]:
        lines += ["", "Not given in the drawing (state these as assumptions in your summary):"]
        lines += [f"- {a}" for a in st["assumptions"]]
    if review.get("notes"):
        lines += ["", f"My notes: {review['notes']}"]
    lines += ["", ("Rules: build from the confirmed values only. Do not measure any size from the reference image; "
              "use it for the shape and where features sit. Small features you can see but that have no size above "
              "(radii, chamfers): give them a sensible size and list each one as assumed. If a missing size would "
              "change the overall size or how the part fits, ask me with choices first. Make the listed sizes "
              "editable parameters, and finish with a short list of what you assumed.")]
    return "\n".join(lines)


def handoff_summary(meta: dict[str, Any], st: dict[str, Any], review: dict[str, Any]) -> str:
    """What the Studio chat shows as the user's message for a hand-off: a short summary in the user's words.
    The full structured request (values, provenance, modelling rules) goes to the design agent only."""
    ref = st["scale"]["reference"] or {}
    live = [d for d in st["dims"] if not d["excluded"]]
    answers = review.get("answers", {})
    missing = [n for n in st["needs"] if n["kind"] == "missing"]
    not_needed = sum(1 for n in missing if (answers.get(n["id"]) or {}).get("choice") == "not_needed")
    estimated = sum(1 for n in missing if (answers.get(n["id"]) or {}).get("choice") == "estimate")
    bits = [f"{len(live)} confirmed value{'s' if len(live) != 1 else ''}"]
    if ref.get("value"):
        bits.append(f"reference {fmt(ref['value'])} {ref['unit']}" + (f" ({ref['describes']})" if ref.get("describes") else ""))
    if estimated:
        bits.append(f"{estimated} size{'s' if estimated != 1 else ''} to estimate (flagged)")
    if not_needed:
        bits.append(f"{not_needed} item{'s' if not_needed != 1 else ''} not needed")
    out = f"Model from {meta.get('name') or 'my drawing'}: " + ", ".join(bits) + "."
    if live:
        vals = [d["label"] for d in live[:24]]
        out += "\nValues: " + ", ".join(vals) + (f" and {len(live) - 24} more" if len(live) > 24 else "") + "."
    return out
