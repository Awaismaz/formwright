"""CHK-12 drawing consistency (docs/VALIDATION.md): a gating, deterministic check of a generated sheet.

Sub-checks:
  tags        every dimension and callout value is tagged ``spec`` or ``inferred``
  spec_once   every parameter that maps to geometry appears on the sheet, and no measurement is dimensioned twice
  extents     each principal view's projected extents equal the model bounding box projection (0.01 mm)
  overlap     no two texts overlap (bbox test), no text crosses a view's geometry or leaves the frame
  holes       hole callouts on the sheet match the exact hole census (count per diameter)
"""

from __future__ import annotations

from typing import Any

from aicad.drawing.layout import boxes_overlap

EXTENT_TOL = 0.01
TEXT_KINDS_IN_VIEWS = {"dim", "callout"}


def chk12(sheet: dict[str, Any], dims: list[dict[str, Any]], callouts: list[dict[str, Any]],
          mapping: dict[str, Any], census: dict[str, Any], expected_extents: dict[str, list[float]]) -> dict[str, Any]:
    problems: list[str] = []
    detail: dict[str, Any] = {}

    # tags
    untagged = [d["id"] for d in dims if d.get("tag") not in ("spec", "inferred")]
    untagged += [c["id"] for c in callouts for ln in c["lines"] if ln.get("tag") not in ("spec", "inferred")]
    texts = [p for p in sheet["prims"] if p["t"] == "text"]
    dim_texts = [t for t in texts if t.get("kind") in TEXT_KINDS_IN_VIEWS]
    untagged += [t["txt"] for t in dim_texts if t.get("tag") not in ("spec", "inferred")]
    detail["tags"] = {"dimensions": len(dims), "callout_lines": sum(len(c["lines"]) for c in callouts),
                      "untagged": untagged}
    if untagged:
        problems.append(f"{len(untagged)} untagged dimension(s)")

    # spec once: mapped parameters present on the sheet; each measurement once
    on_sheet = {}
    for t in dim_texts:
        if t.get("tag") == "spec" and t.get("param"):
            on_sheet[t["param"]] = on_sheet.get(t["param"], 0) + 1
    missing = sorted(p for p in mapping.get("mapped", {}) if p not in on_sheet)
    seen: dict[tuple[Any, ...], int] = {}
    for d in dims:
        k = (d["view"], d["orient"], round(d["a"], 6), round(d["b"], 6))
        seen[k] = seen.get(k, 0) + 1
    dup = sorted(str(k) for k, n in seen.items() if n > 1)
    placed_refs = {t.get("ref") for t in dim_texts}
    not_placed = sorted(d["id"] for d in dims if d["id"] not in placed_refs)
    detail["spec_once"] = {"spec_on_sheet": dict(sorted(on_sheet.items())), "missing": missing, "duplicates": dup,
                           "not_placed": not_placed, "unmapped_params": mapping.get("unmapped", [])}
    if missing:
        problems.append("spec parameter(s) not shown: " + ", ".join(missing))
    if dup:
        problems.append(f"{len(dup)} duplicated dimension(s)")
    if not_placed:
        problems.append(f"{len(not_placed)} dimension(s) not placed")

    # view extents vs model bbox
    ext_detail = {}
    for v, exp in sorted(expected_extents.items()):
        got = sheet["views"].get(v, {}).get("extents")
        if got is None:
            continue
        err = max(abs(a - b) for a, b in zip(got, exp))
        ext_detail[v] = {"got": got, "expected": exp, "max_err_mm": round(err, 9), "passed": err <= EXTENT_TOL}
        if err > EXTENT_TOL:
            problems.append(f"{v} view extents differ from the model by {err:.3f} mm")
    detail["extents"] = ext_detail

    # overlaps
    overlaps = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a, b = texts[i], texts[j]
            if boxes_overlap(a["box"], b["box"], -0.05):
                overlaps.append([a["txt"], b["txt"]])
    crossing = []
    for t in dim_texts:
        for v, info in sheet["views"].items():
            r = info["rect"]
            if boxes_overlap(t["box"], r, -0.05):
                crossing.append([t["txt"], v])
    fr = sheet["frame"]
    outside = [t["txt"] for t in texts if t["box"][0] < fr[0] or t["box"][1] < fr[1] or t["box"][2] > fr[2]
               or t["box"][3] > fr[3]]
    detail["overlap"] = {"texts": len(texts), "text_overlaps": overlaps, "text_over_geometry": crossing,
                         "outside_frame": outside}
    if overlaps:
        problems.append(f"{len(overlaps)} overlapping text pair(s)")
    if crossing:
        problems.append(f"{len(crossing)} dimension text(s) over view geometry")
    if outside:
        problems.append(f"{len(outside)} text(s) outside the frame")

    # holes vs census
    census_count: dict[float, int] = {}
    for h in census.get("holes", []):
        census_count[h["dia"]] = census_count.get(h["dia"], 0) + 1
    called: dict[float, int] = {}
    for c in callouts:
        if any(t.get("ref") == c["id"] and t.get("kind") == "callout" for t in texts):
            called[c["dia"]] = called.get(c["dia"], 0) + c["qty"]
    mism = {str(d): {"census": census_count.get(d, 0), "called_out": called.get(d, 0)}
            for d in sorted(set(census_count) | set(called)) if census_count.get(d, 0) != called.get(d, 0)}
    detail["holes"] = {"census": {str(k): v for k, v in sorted(census_count.items())},
                       "called_out": {str(k): v for k, v in sorted(called.items())}, "mismatch": mism}
    if mism:
        problems.append("hole callouts differ from the census")

    return {"id": "CHK-12", "name": "drawing consistency", "passed": not problems, "gating": True,
            "problems": problems, "detail": detail}
