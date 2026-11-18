"""Program deliverables (CD-014): what Ortho and Smithy produce after integration, and the program release pack.

Pure Python (the kernel work happens in the drawing worker, the manufacturing analyser and the assembly worker):
  ``make_parts``    the parts the program makes (designed parts and reused company parts with a Studio project)
  ``icd_spec``      ICD numbers a part's drawing should show as spec dimensions (fits, hole patterns, seats)
  ``bom``           the program BOM: quantity, make / buy, material, mass, Toolbox designations, the ticket
  ``bom_csv``       the BOM as CSV
  ``dfm_part``      Smithy's line for one part: best process, flags, top findings, unit cost
  ``dfm_summary``   the program DFM summary: relative cost index per part, totals, parts that need attention
  ``readme``        the release pack's README

Nothing here is an approval: every output says that checks prove geometric consistency only, DFM is advisory and the
costs are a relative estimate, not a quote.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from aicad.office import icd

PACK_NOTE = ("Checks prove geometric consistency of the models only. Drawings carry NOT APPROVED FOR MANUFACTURE until "
             "a qualified engineer approves them; the manufacturability screening is advisory and its costs are a "
             "relative estimate, not a quote. Interface numbers (ICD) are planning values; ISO 286 limits come from "
             "the standard tables and must be verified.")


# ----------------------------------------------------------------------------- what the program makes
def make_parts(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The part tickets with a Design Studio project (designed here, or a company part Hex reused), plan order."""
    out = []
    for t in doc["tickets"]:
        if t["kind"] == "part" and t.get("project_id"):
            out.append({"ticket": t, "project_id": t["project_id"], "reused": False})
        elif t["kind"] in ("part", "standard") and (t.get("reuse") or {}).get("source") == "project":
            out.append({"ticket": t, "project_id": t["reuse"]["project_id"], "reused": True})
    return out


# ----------------------------------------------------------------------------- ICD numbers on the drawings
def icd_spec(skel: dict[str, Any], doc_icd: dict[str, Any], item: str) -> dict[str, Any]:
    """Spec values a part's drawing can tag (``spec_params`` / ``spec_meta``, merged with the model's own parameters
    by Drawing Studio) and the fits to print next to them (``spec_fits``): bore and journal Ø with their ISO 286
    class, clearance and dowel hole Ø, bearing seat Ø, the PCD of a bolt circle. Names start with ``ICD_`` so a
    model parameter of the same name is never shadowed."""
    params: dict[str, float] = {}
    meta: dict[str, dict[str, str]] = {}
    fits: dict[str, str] = {}
    notes: list[str] = []
    if not skel or item not in (skel.get("items") or {}):
        return {"params": params, "meta": meta, "fits": fits, "notes": notes}

    def put(name: str, value: float, label: str, fit: str | None = None) -> None:
        if name in params or value <= 0:
            return
        params[name] = round(float(value), 4)
        meta[name] = {"label": label}
        if fit:
            fits[name] = fit

    for f in icd.item_features(skel, doc_icd["interfaces"], item):
        iid = f["if"].replace("-", "")
        if f["type"] == "hole":
            label = f"{f['if']} hole Ø" if not f.get("fit") else f"{f['if']} bore Ø"
            put(f"ICD_{iid}_D{'_FIT' if f.get('fit') else ''}", f["d"], label, f.get("fit"))
        elif f["type"] == "boss":
            put(f"ICD_{iid}_SHAFT_D", f["d"], f"{f['if']} shaft Ø", f.get("fit"))
        elif f["type"] == "seat":
            put(f"ICD_{iid}_SEAT_D{round(f['d'])}", f["d"], f"{f['if']} seat Ø", f.get("fit"))
        elif f["type"] == "keyway":
            notes.append(f"{f['if']}: KEYWAY {f['b']:g} × {f['depth']:g} DEEP ({'HUB' if f['on'] == 'hub' else 'SHAFT'}) "
                         "TO DIN 6885-1, TOLERANCES TO BE ADDED BY THE ENGINEER.")
    for f in doc_icd["interfaces"]:
        if f["kind"] == "hole_pattern" and f["data"].get("pcd") and item in (f["a"]["item"], f["b"]["item"]):
            put(f"ICD_{f['id'].replace('-', '')}_PCD", f["data"]["pcd"], f"{f['id']} pitch circle Ø")
    if params:
        notes.append(f"VALUES TAGGED SPEC INCLUDE INTERFACE NUMBERS FROM ICD v{doc_icd['version']} (VERIFY FITS "
                     "AGAINST ISO 286).")
    return {"params": params, "meta": meta, "fits": fits, "notes": notes}


# ----------------------------------------------------------------------------- the program BOM
def bom(tickets: list[dict[str, Any]], asm_rows: list[dict[str, Any]] | None,
        inst_items: dict[str, dict[str, Any]] | None = None, part_projects: dict[str, str] | None = None,
        project_info: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """The program BOM.

    ``asm_rows``: the final assembly's BOM rows (``assembly.service.bom``: one row per part snapshot, with its
    instances, quantity, Toolbox designation and mass), or None before the assembly exists. ``inst_items``:
    instance id -> its office tag (``item``, ``bin``); ``part_projects``: part key -> Studio project id;
    ``project_info``: project id -> {name, material, mass_g, rev}.

    Rules: a row per part in the product. The plan's quantity is authoritative for parts with a ticket (the parts
    bin holds at most four of a kind); parts Fitz added (washers and nuts of the bolted joints) keep the assembly's
    quantity. Make = designed or company parts (and placeholders still in design); buy = Toolbox parts, with their
    designation and standard. Item numbers: made parts first in plan order, then bought parts."""
    inst_items = inst_items or {}
    part_projects = part_projects or {}
    project_info = project_info or {}
    by_item = {t["item_id"]: t for t in tickets if t["kind"] in ("part", "standard")}
    by_project = {t.get("project_id"): t for t in tickets if t.get("project_id")}
    by_project.update({(t.get("reuse") or {}).get("project_id"): t for t in tickets
                       if (t.get("reuse") or {}).get("source") == "project"})
    by_code: dict[str, list[dict[str, Any]]] = {}
    for t in tickets:
        r = t.get("reuse") or {}
        if t["kind"] == "standard" and r.get("source") == "toolbox":
            by_code.setdefault(str(r.get("code")), []).append(t)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in asm_rows or []:
        # every planned item whose instances are in this row (two bearing tickets can share one Toolbox bearing)
        ts: list[dict[str, Any]] = []
        for iid in r.get("instances") or []:
            o = inst_items.get(iid) or {}
            if o.get("item") in by_item and by_item[o["item"]] not in ts:
                ts.append(by_item[o["item"]])
        if not ts and r["kind"] in ("project", "placeholder"):
            t0 = by_project.get(part_projects.get(r.get("part_key") or ""))
            ts = [t0] if t0 else []
        if not ts and r["kind"] == "toolbox":
            code = str(r.get("code") or "")
            cands = [x for x in by_code.get(code, []) if x["id"] not in seen]
            ts = cands[:1]
        ts = [x for x in ts if x["id"] not in seen]
        t = ts[0] if ts else None
        qty = int(r["qty"])
        planned = sum(int(x.get("qty") or 1) for x in ts)
        if ts and (r["kind"] != "toolbox" or any((inst_items.get(i) or {}).get("bin") for i in r.get("instances") or [])):
            qty = max(qty, planned)
        each = r.get("mass_each_g")
        rows.append({
            "qty": qty, "part": r["part"], "make_buy": "buy" if r["kind"] == "toolbox" else "make",
            "kind": r["kind"], "designation": r.get("designation"), "standard": r.get("standard"),
            "material": r.get("material"), "mass_each_g": each,
            "mass_total_g": None if each is None else round(float(each) * qty, 2),
            "description": (("Placeholder: still in design" if r["kind"] == "placeholder" else
                             "Company part, reused" if t is not None and (t.get("reuse") or {}).get("source") == "project"
                             else "Designed in this program") if r["kind"] != "toolbox" else
                            ("From the plan" if t is not None else "Added by Fitz for the bolted joints")),
            "ticket": t["id"] if t is not None else None,
            "key": ", ".join(x["key"] for x in ts) if ts else None,
            "part_key": r.get("part_key"), "instances": r.get("instances") or []})
        seen.update(x["id"] for x in ts)
    for t in tickets:  # plan items not in the assembly (yet)
        if t["kind"] not in ("part", "standard") or t["id"] in seen:
            continue
        r = t.get("reuse") or {}
        pid = t.get("project_id") or (r.get("project_id") if r.get("source") == "project" else None)
        info = project_info.get(pid or "") or {}
        buy = r.get("source") == "toolbox" or (t["kind"] == "standard" and not pid)
        each = info.get("mass_g")
        qty = int(t.get("qty") or 1)
        rows.append({"qty": qty, "part": info.get("name") or (r.get("title") if buy else None) or t["title"],
                     "make_buy": "buy" if buy else "make", "kind": "toolbox" if buy else "project",
                     "designation": r.get("title") if buy else None, "standard": r.get("standard") if buy else None,
                     "material": info.get("material"), "mass_each_g": each,
                     "mass_total_g": None if each is None else round(float(each) * qty, 2),
                     "description": "Not in the program assembly yet" if not buy else "From the plan (not placed)",
                     "ticket": t["id"], "key": t["key"], "part_key": None, "instances": []})
    order = {t["id"]: n for n, t in enumerate(tickets)}
    rows.sort(key=lambda x: (x["make_buy"] != "make", order.get(x["ticket"] or "", 10_000), x["part"]))
    for n, r in enumerate(rows, start=1):
        r["item"] = n
    known = [r for r in rows if r["mass_total_g"] is not None]
    return {"rows": rows, "total_qty": sum(r["qty"] for r in rows),
            "make": sum(1 for r in rows if r["make_buy"] == "make"), "buy": sum(1 for r in rows if r["make_buy"] == "buy"),
            "total_mass_g": round(sum(float(r["mass_total_g"]) for r in known), 2),
            "mass_unknown": sum(1 for r in rows if r["mass_total_g"] is None),
            "note": "Masses use nominal densities for the stated materials (verify with your supplier); Toolbox parts "
                    "are modelled envelopes. Placeholders have no mass."}


def bom_csv(b: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["Item", "Qty", "Part", "Make/Buy", "Designation", "Standard", "Material", "Mass each (g)",
                "Mass total (g)", "Ticket", "Note"])
    for r in b["rows"]:
        w.writerow([r["item"], r["qty"], r["part"], r["make_buy"], r["designation"] or "", r["standard"] or "",
                    r["material"] or "", "" if r["mass_each_g"] is None else f"{r['mass_each_g']:.2f}",
                    "" if r["mass_total_g"] is None else f"{r['mass_total_g']:.2f}", r["key"] or "", r["description"]])
    w.writerow(["", b["total_qty"], "Total", f"{b['make']} make / {b['buy']} buy", "", "", "", "",
                f"{b['total_mass_g']:.2f}", "", ""])
    return buf.getvalue()


# ----------------------------------------------------------------------------- Smithy's DFM summary
PROCESS_NAMES = {"cnc_milling": "CNC milling", "cnc_turning": "CNC turning", "sheet_metal": "Sheet metal",
                 "fdm": "FDM printing", "sla": "SLA printing", "sls": "SLS printing", "casting": "Casting",
                 "injection_moulding": "Injection moulding"}


def dfm_part(t: dict[str, Any], a: dict[str, Any] | None, error: str | None = None) -> dict[str, Any]:
    """One part's line: the best feasible process, CHK-13 flag counts, the top findings, unit cost (relative)."""
    base = {"ticket": t["id"], "key": t["key"], "title": t["title"], "qty": int(t.get("qty") or 1)}
    if a is None:
        return {**base, "ok": False, "error": error or "Not analysed"}
    rank = (a.get("process") or {}).get("ranking") or []
    best = next((r for r in rank if r.get("feasible")), rank[0] if rank else None)
    primary = (a.get("cost") or {}).get("primary")
    procs = (a.get("cost") or {}).get("processes") or {}
    pick = primary if primary in procs else (best or {}).get("process")
    unit = (procs.get(pick or "") or {}).get("unit_cost")
    counts = a.get("summary") or (a.get("chk13") or {}).get("counts") or {}
    flagged = [f for f in a.get("findings") or [] if f["severity"] in ("critical", "warning")]
    # the findings for the process Smithy picked come first (a moulding draft note is not news for a milled part)
    mine = [f for f in flagged if f.get("process") == pick or pick in (f.get("also") or [])]
    top = (mine or flagged)
    top.sort(key=lambda f: (f["severity"] != "critical", f["rule"]))
    return {**base, "ok": True, "process": pick, "process_name": PROCESS_NAMES.get(pick or "", best and best.get("name")
                                                                                 or pick),
            "fit": (best or {}).get("fit"), "score": (best or {}).get("score"),
            "critical": int(counts.get("critical") or 0), "warning": int(counts.get("warning") or 0),
            "info": int(counts.get("info") or 0),
            "findings": [{"rule": f["rule"], "severity": f["severity"], "title": f["title"], "measured": f["measured"],
                          "limit": f["limit"], "fix": f["fix"]} for f in top[:4]],
            "unit_cost": unit, "currency": (a.get("cost") or {}).get("currency"),
            "quantity": (a.get("inputs") or {}).get("quantity"),
            "material": (a.get("material") or {}).get("name"), "mass_kg": (a.get("part") or {}).get("mass_kg"),
            "setups": ((a.get("signals") or {}).get("setups") or None) and len((a.get("signals") or {})["setups"])}


def dfm_summary(lines: list[dict[str, Any]]) -> dict[str, Any]:
    """The program DFM summary. Relative cost index = a part's unit cost over the cheapest part's (1.0 = cheapest);
    program cost = sum of unit cost x quantity, relative estimate, not a quote."""
    costed = [x for x in lines if x.get("ok") and x.get("unit_cost")]
    cheapest = min((float(x["unit_cost"]) for x in costed), default=None)
    for x in lines:
        x["relative_cost"] = (round(float(x["unit_cost"]) / cheapest, 2)
                              if cheapest and x.get("ok") and x.get("unit_cost") else None)
    total = round(sum(float(x["unit_cost"]) * x["qty"] for x in costed), 2)
    for x in lines:
        x["cost_share_pct"] = (round(100.0 * float(x["unit_cost"]) * x["qty"] / total, 1)
                               if total and x.get("ok") and x.get("unit_cost") else None)
    return {"parts": lines, "analysed": sum(1 for x in lines if x.get("ok")),
            "critical": sum(int(x.get("critical") or 0) for x in lines),
            "warning": sum(int(x.get("warning") or 0) for x in lines),
            "attention": [x["key"] for x in lines if x.get("critical")],
            "program_cost": total, "currency": next((x.get("currency") for x in costed), None),
            "label": "Relative estimate, not a quote",
            "note": "Advisory design-for-manufacture screening with the workspace's shop profile: not manufacturing "
                    "approval. Review with your manufacturer before release."}


def dfm_csv(s: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["Ticket", "Part", "Qty", "Process", "Critical", "Warnings", "Unit cost (relative estimate)",
                "Relative cost index", "Top finding"])
    for x in s["parts"]:
        top = x.get("findings") or []
        w.writerow([x["key"], x["title"], x["qty"], x.get("process_name") or x.get("error") or "",
                    x.get("critical", ""), x.get("warning", ""),
                    "" if x.get("unit_cost") is None else f"{x['unit_cost']:.2f} {x.get('currency') or ''}".strip(),
                    "" if x.get("relative_cost") is None else f"{x['relative_cost']:.2f}",
                    f"{top[0]['rule']} {top[0]['title']}" if top else ""])
    return buf.getvalue()


# ----------------------------------------------------------------------------- the release pack
def readme(doc: dict[str, Any], rel: dict[str, Any], files: list[str], parts: list[dict[str, Any]],
           b: dict[str, Any], dfm: dict[str, Any] | None) -> str:
    lines = [f"FORMWRIGHT PROGRAM RELEASE: {doc['name']} · REV {rel['rev']}",
             f"Released {rel.get('date', '')} by {rel.get('by') or '—'} · ICD v{(doc.get('icd') or {}).get('version', '—')}",
             f"Note: {rel.get('note') or '—'}", "",
             "Parts released (each tagged in its Design Studio project):"]
    for p in parts:
        lines.append(f"  {p['key']}  {p['title']}  rev {p['rev']}  (model revision {p.get('model_rev') or '—'}, "
                     f"tag \"{p['tag']}\")")
    lines += ["", (f"Bill of materials: {len(b['rows'])} lines, {b['total_qty']} pieces ({b['make']} make, "
                  f"{b['buy']} buy), {b['total_mass_g']:,.1f} g known mass")]
    if dfm:
        lines.append(f"Manufacturing review: {dfm['analysed']} parts screened, {dfm['critical']} critical and "
                     f"{dfm['warning']} warning flags ({dfm['label'].lower()} for costs)")
    lines += ["", "Contents:", *[f"  {f}" for f in sorted(files)], "", PACK_NOTE,
              "Verify each file's SHA-256 against manifest.json."]
    return "\n".join(lines) + "\n"
