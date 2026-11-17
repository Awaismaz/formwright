"""Drawing round-trip check (AMI-I1): does the model built from a drawing carry the values that were confirmed?

After the design agent has built the model, the Drawing Studio generates its sheet (exact OCCT measurements of the
model, no AI). ``sheet_values`` collects what that sheet dimensions: overall extents, step chains, positions, turned
diameters, hole callouts (quantity, Ø, THRU or depth) and the bounding box. ``compare`` then looks for each
confirmed value of the review among them, kind by kind:

  match     a measured value of the same kind equals it (within ``TOL`` mm, the sheet prints 2 decimals)
  count     the diameter is there, but the sheet calls out a different number of holes
  missing   no measured value of that kind equals it: the model may differ from the drawing, or the sheet may not
            dimension that feature (the check says which value to look at; it never decides)
  skipped   kinds the sheet does not measure automatically (radii, chamfers, angles, threads)

It proves the model carries the confirmed values; it is not an inspection and says nothing about tolerances or
manufacturability.
"""

from __future__ import annotations

from typing import Any

from aicad.image2cad.tokens import fmt, parse

TOL = 0.011  # mm: the sheet rounds to 0.01 mm
LINEAR_KINDS = ("extent", "step", "depth", "position", "pcd")
CHECKED = ("linear", "diameter")
SKIP_WHY = {"radius": "radii", "spherical_radius": "radii", "chamfer": "chamfers", "angle": "angles",
            "thread": "threads", "square": "square sizes", "spherical_diameter": "spherical sizes"}


def sheet_values(rec: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Measured values on a Drawing Studio record, grouped as {"linear": [...], "diameter": [...]}.
    Each item: value (mm), text (as printed), count (holes), where."""
    lin: list[dict[str, Any]] = []
    dia: list[dict[str, Any]] = []
    for d in rec.get("dimensions", []):
        v = d.get("value")
        if not isinstance(v, (int, float)):
            continue
        item = {"value": float(v), "text": d.get("text"), "count": None, "where": d.get("view")}
        if d.get("kind") in ("diameter", "hole"):
            dia.append(item)
        elif d.get("kind") in LINEAR_KINDS:
            lin.append(item)
        if d.get("kind") == "pcd":
            dia.append(item)
    for c in rec.get("callouts", []):
        text = (c.get("lines") or [{}])[0].get("text")
        if isinstance(c.get("dia"), (int, float)):
            dia.append({"value": float(c["dia"]), "text": text, "count": int(c.get("qty") or 1), "where": c.get("view")})
        for ln in c.get("lines") or []:
            p = parse(ln.get("text") or "") or {}
            if isinstance(p.get("depth"), (int, float)):
                lin.append({"value": float(p["depth"]), "text": ln.get("text"), "count": None, "where": c.get("view")})
    bb = (rec.get("census") or {}).get("bbox")
    if isinstance(bb, list) and len(bb) == 6:
        for i, axis in enumerate("XYZ"):
            lin.append({"value": round(bb[i + 3] - bb[i], 6), "text": fmt(bb[i + 3] - bb[i]), "count": None,
                        "where": f"overall {axis}"})
    return {"linear": lin, "diameter": dia}


def compare(dims: list[dict[str, Any]], measured: dict[str, list[dict[str, Any]]], unit: str = "mm") -> dict[str, Any]:
    """Each confirmed dimension against the measured values. ``dims``: {"id", "label", "describes"?}, where the
    label is the canonical callout (re-parsed here, so counts, THRU and depths are known)."""
    k = 25.4 if unit == "in" else 1.0
    rows = []
    for d in dims:
        p = parse(d.get("label") or "") or {}
        kind, value = p.get("kind"), p.get("value")
        row: dict[str, Any] = {"id": d.get("id"), "label": d.get("label"), "describes": d.get("describes"),
                               "status": "skipped", "found": None, "note": None}
        if kind not in CHECKED or not isinstance(value, (int, float)):
            row["note"] = f"Not measured automatically ({SKIP_WHY.get(kind or '', 'this kind')})."
            rows.append(row)
            continue
        want = value * k
        hits = [m for m in measured[kind] if abs(m["value"] - want) <= TOL]
        if kind == "diameter" and isinstance(p.get("depth"), (int, float)):
            deep = p["depth"] * k
            if not any(abs(m["value"] - deep) <= TOL for m in measured["linear"]):
                hits = []
                row["note"] = f"Ø{fmt(want)} found, but no hole {fmt(deep)} mm deep."
        if not hits:
            row["status"] = "missing"
            row["note"] = row["note"] or ("No dimension of this value on the model's drawing. Check this size in the "
                                          "model: it differs, or the drawing does not show that feature.")
        else:
            row["status"], row["found"] = "match", hits[0]["text"]
            want_n = p.get("count")
            if kind == "diameter" and want_n:
                counts = [m["count"] for m in hits if m["count"]]
                if counts and want_n not in counts and sum(counts) != want_n:
                    row["status"] = "count"
                    row["note"] = f"The model has {sum(counts)} × Ø{fmt(want)}, the drawing calls for {want_n}."
        if unit == "in" and row["found"]:
            row["found"] = f"{row['found']} mm"
        rows.append(row)
    checked = [r for r in rows if r["status"] != "skipped"]
    matched = sum(1 for r in checked if r["status"] == "match")
    return {"rows": rows, "matched": matched, "checked": len(checked), "skipped": len(rows) - len(checked),
            "ok": matched == len(checked)}
