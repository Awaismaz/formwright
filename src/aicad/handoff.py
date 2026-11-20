"""Shop handoff pack and the release gate ("Issue Rev A").

Handoff pack: one zip with everything the shop needs for the current model, and a manifest that proves it.

Contents (only what exists, each checked against the current build with the one rule in ``aicad.deliverables``):
  model/        STEP, STL, 3MF of the verified model
  drawing/      sheet PDF/DXF/SVG from Drawing Studio (left out if drawn from an older build)
  dfm/          manufacturability report PDF (left out if the analysis is older than the build)
  calculations/ signed calculation packages (release only: sets signed on this build)
  print/        print exports made from this build (release only)
  CHANGE_NOTICE.txt  what changed in this revision and why
  README.txt         plain summary: part, revision, material, mass, size, checks, contents, gaps
  manifest.json      SHA-256 and size of every file, the source build and fingerprint, stale flags

Release (IDEA-01, MAKE-08): ``gate`` says whether the current build can be issued and what would go in; issuing
(``routers/handoff.py``) freezes the build, an issue copy of the drawing stamped with the revision letter, the DFM
report, the signed calculation packages and the print exports into ``<ws>/releases/<rev>/pack.zip`` with its
manifest, and appends the record to ``<ws>/releases/releases.json``. Letters follow ASME Y14.35 (A, B, …, skipping
I O Q S X Z). Every module then compares the current build with the issued one ("Draft: changes since Rev A").

Never an approval: README and manifest state that checks prove geometric consistency only.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aicad import change_notice, deliverables, materials

ZIP_TIME = (2000, 1, 1, 0, 0, 0)  # fixed entry timestamps; file identity is proven by the manifest's SHA-256
MODEL_FILES = (("part.step", "STEP (AP214)"), ("part.stl", "STL (0.01 mm chordal deviation)"), ("part.3mf", "3MF (mm)"))
REV_LETTERS = [c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c not in "IOQSXZ"]  # ASME Y14.35 (letters not used)
LEAVABLE = ("dfm", "engineering")  # stale optional outputs the user may leave out of a release


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")[:60] or "part"


def _json(p: Path) -> dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _revision(ws: Path) -> int | None:
    root = ws / "revisions"
    if not root.is_dir():
        return None
    nums = sorted(int(d.name) for d in root.iterdir() if d.name.isdigit())
    return nums[-1] if nums else None


def notice_text(n: dict[str, Any]) -> str:
    lines = [f"CHANGE NOTICE: {n.get('project', {}).get('name') or n.get('part') or 'part'}",
             f"Revision {n['revision']}" + (f", supersedes revision {n['base']}" if n.get("base") else "")
             + f" · {n.get('created_at', '')}" + (f" · {n['by']}" if n.get("by") else ""),
             "", f"Why: {n.get('why') or 'not recorded'}", "", "What changed:"]
    lines += [f"  - {x}" for x in n.get("changes", {}).get("lines", [])]
    return "\n".join(lines) + "\n"


# ============================================================================== releases
def rev_letter(i: int) -> str:
    """0 → A, 19 → Y, 20 → AA (two-letter continuation)."""
    n = len(REV_LETTERS)
    return REV_LETTERS[i] if i < n else rev_letter(i // n - 1) + REV_LETTERS[i % n]


def releases(ws: Path) -> list[dict[str, Any]]:
    """Issued revisions, oldest first."""
    try:
        data = json.loads((ws / "releases" / "releases.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def latest_release(ws: Path) -> dict[str, Any] | None:
    rels = releases(ws)
    return rels[-1] if rels else None


def next_rev(ws: Path) -> str:
    return rev_letter(len(releases(ws)))


def release_view(ws: Path, cur: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The latest release as every module shows it: letter, date, by, and whether the current build is that one."""
    rel = latest_release(ws)
    if not rel:
        return None
    cur = cur or deliverables.build_stamp(ws)
    return {"rev": rel["rev"], "date": rel.get("date"), "by": rel.get("by"), "note": rel.get("note"),
            "model_rev": (rel.get("build") or {}).get("model_rev"),
            "current": deliverables.same_build(rel.get("build"), cur)}


def _param_diff(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    out = []
    for k in sorted(after):
        a, b = before.get(k), after.get(k)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(float(a) - float(b)) > 1e-9:
            out.append(f"{k} {a:g} → {b:g}")
    return out


# ============================================================================== per-module status
def module_status(ws: Path, cur: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """State of each downstream output on the current build: one rule (``deliverables.freshness``), one short label
    per module for the Studio's Make tab and the module headers."""
    cur = cur or deliverables.build_stamp(ws)
    out: dict[str, dict[str, Any]] = {}

    drw = _json(ws / "drawings" / "drawing.json")
    if drw:
        f = deliverables.freshness(drw.get("build") or {"build_id": drw.get("build_id")}, ws, cur)
        ok = bool((drw.get("check") or {}).get("passed"))
        rev = drw.get("sheet_rev")
        if f["state"] == "stale":
            label = "Model changed · update"
        else:
            label = (f"Rev {rev}" if rev and rev != "DRAFT" else "Draft") + ("" if ok else " · check failed")
        out["drawings"] = {**f, "label": label, "check_passed": ok, "sheet_rev": rev}
    else:
        out["drawings"] = {"state": "missing", "label": "Not drawn yet"}

    dfm = _json(ws / "manufacturing" / "analysis.json")
    if dfm:
        f = deliverables.freshness(dfm.get("build"), ws, cur)
        s = dfm.get("summary") or (dfm.get("chk13") or {}).get("counts") or {}
        crit, warn = int(s.get("critical", 0)), int(s.get("warning", 0))
        if f["state"] == "stale":
            label = "Model changed · re-analyse"
        elif crit:
            label = f"{crit} critical"
        elif warn:
            label = f"{warn} warning{'s' if warn > 1 else ''}"
        else:
            label = "No issues flagged"
        out["manufacturing"] = {**f, "label": label, "critical": crit, "warning": warn}
    else:
        out["manufacturing"] = {"state": "missing", "label": "Not analysed"}

    from aicad.engineering import store as eng_store

    eng = eng_store.deliverable_summary(ws)
    out["engineering"] = {**eng, "label": eng.get("label") or ""}

    if (ws / "print").is_dir():
        from aicad.printprep import service as print_service

        pr = print_service.export_summary(ws)
    else:
        pr = {"state": "missing", "exports": 0, "outdated": 0, "label": "No print exports", "current_files": []}
    out["print"] = pr
    return out


def _verified(st: dict[str, Any] | None) -> bool:
    """Gating checks passed and no deferred check (CHK-07/08, PS-01) is still pending."""
    from aicad.agent.runner import is_verified

    return is_verified(st)


def deliverables_status(ws: Path) -> dict[str, Any]:
    """Everything the Make tab and module headers show: model rev, release state, one status per module."""
    st = deliverables.read_status(ws)
    cur = deliverables.build_stamp(ws, st)
    rel = release_view(ws, cur)
    return {"verified": _verified(st), "build": cur, "release": rel, "next_rev": next_rev(ws),
            "changed_since_release": bool(rel) and not rel["current"], "modules": module_status(ws, cur)}


# ============================================================================== release gate
def gate(ws: Path, has_drawings: bool = True, leave_out: tuple[str, ...] | list[str] = ()) -> dict[str, Any]:
    """Can the current build be issued, and what would the release contain?

    Blocking: the model is not verified (or its STEP export is not finished); the drawing is missing (when the
    workspace has Drawing Studio), drawn from an older build or failing CHK-12; this exact build is already issued;
    a DFM analysis or a signed calculation set from an older build, unless the user leaves it out."""
    st = deliverables.read_status(ws)
    cur = deliverables.build_stamp(ws, st)
    mods = module_status(ws, cur)
    rel = latest_release(ws)
    blocking: list[dict[str, str]] = []
    include: list[dict[str, str]] = []
    notes: list[str] = []
    from aicad.agent.runner import accepted as _accepted

    acc = _accepted(st)
    if acc:   # ASM-OW: the engineer marked this build as verified with checks open: the pack says so
        notes.append(f"Verified by {acc.get('by') or 'an engineer'} with checks open: "
                     + (", ".join(f"{c['id']} {c['name']}" for c in acc.get("open") or []) or "none listed")
                     + (f" (reason: {acc['reason']})" if acc.get("reason") else "") + ". Not a pass.")
    if st.get("ok") and not _verified(st):
        blocking.append({"kind": "model", "text": "The latest build is still being verified (STEP round trip and "
                                                  "repeatability). Try again in a moment."})
    elif not (st.get("ok") or acc) or not (ws / "out" / "part.step").is_file():
        blocking.append({"kind": "model", "text": "The current model isn't verified. Fix the build in the Design Studio first."})
    elif not cur.get("step_sha256"):
        blocking.append({"kind": "model", "text": "The model's export files are still being written. Try again in a moment."})
    else:
        include.append({"kind": "model", "text": f"Model rev {cur.get('model_rev') or '-'}: STEP, STL, 3MF"})
    if rel and deliverables.same_build(rel.get("build"), cur):
        blocking.append({"kind": "release", "text": f"Rev {rel['rev']} already is this exact model. Change the design to issue a new revision."})

    d = mods["drawings"]
    if d["state"] == "missing":
        if has_drawings:
            blocking.append({"kind": "drawings", "text": "Make the drawing in Drawing Studio and review it first."})
        else:
            notes.append("No drawing: Drawing Studio is not in this workspace's plan.")
    elif d["state"] == "stale":
        blocking.append({"kind": "drawings", "text": f"The drawing shows model rev {d.get('made_from_rev') or '-'}. "
                                                     "Update it in Drawing Studio and review it before issuing."})
    elif not d.get("check_passed"):
        blocking.append({"kind": "drawings", "text": "The drawing fails its consistency check (CHK-12). Fix it in Drawing Studio."})
    else:
        include.append({"kind": "drawings", "text": "Drawing: issue copy (PDF, DXF, SVG) stamped with the new revision"})

    m = mods["manufacturing"]
    if m["state"] == "current":
        include.append({"kind": "manufacturing", "text": f"Manufacturability report ({m['label'].lower()})"})
    elif m["state"] == "stale":
        if "dfm" in leave_out:
            notes.append("Manufacturability report left out (analysis is from an earlier model).")
        else:
            blocking.append({"kind": "manufacturing", "leavable": "dfm",
                             "text": f"The manufacturability analysis is from model rev {m.get('made_from_rev') or '-'}. Re-analyse it, or leave it out."})

    e = mods["engineering"]
    if e.get("model_changed"):
        if "engineering" in leave_out:
            notes.append(f"{e['model_changed']} calculation set(s) signed on an earlier model left out.")
        else:
            blocking.append({"kind": "engineering", "leavable": "engineering",
                             "text": f"{e['model_changed']} calculation set(s) were signed on an earlier model. Re-check and re-sign them, or leave them out."})
    if e.get("signed_sets"):
        n = len(e["signed_sets"])
        include.append({"kind": "engineering", "text": f"{n} signed calculation package{'s' if n > 1 else ''} (PDF)"})
    if e.get("unsigned"):
        notes.append(f"{e['unsigned']} unsigned calculation set(s) are not part of a release.")

    p = mods["print"]
    if p.get("current_files"):
        include.append({"kind": "print", "text": f"{len(p['current_files'])} print export(s) made from this model"})
    if p.get("outdated"):
        notes.append(f"{p['outdated']} print export(s) from earlier models are not included.")

    if rel:
        diff = _param_diff(rel.get("params") or {}, st.get("params") or {})
        suggested = ", ".join(diff) if diff else "Model geometry changed"
    else:
        suggested = "Initial issue"
    return {"ready": not blocking, "next_rev": next_rev(ws), "build": cur, "blocking": blocking, "include": include,
            "notes": notes, "suggested_note": suggested, "release": release_view(ws, cur), "modules": mods}


# ============================================================================== packs
def plan(ws: Path) -> dict[str, Any]:
    """What a pack would contain right now, with stale/missing flags (no files written)."""
    st = deliverables.read_status(ws)
    cur = deliverables.build_stamp(ws, st)
    build = st.get("build_id")
    items: list[dict[str, Any]] = []
    for f, label in MODEL_FILES:
        if (ws / "out" / f).is_file():
            items.append({"kind": "model", "file": f, "label": label, "ok": True})
    drw = _json(ws / "drawings" / "drawing.json")
    if drw:
        stale = deliverables.freshness(drw.get("build") or {"build_id": drw.get("build_id")}, ws, cur)["state"] != "current"
        items.append({"kind": "drawing", "label": f"Drawing (model rev {drw.get('model_rev') or '-'})", "ok": not stale,
                      "stale": stale, "check": (drw.get("check") or {}).get("passed")})
    else:
        items.append({"kind": "drawing", "label": "Drawing", "missing": True, "where": "drawings"})
    dfm = _json(ws / "manufacturing" / "analysis.json")
    if dfm:
        stale = deliverables.freshness(dfm.get("build"), ws, cur)["state"] != "current"
        items.append({"kind": "dfm", "label": "Manufacturability report", "ok": not stale, "stale": stale})
    else:
        items.append({"kind": "dfm", "label": "Manufacturability report", "missing": True, "where": "manufacturing"})
    rev = _revision(ws)
    if rev is not None:
        items.append({"kind": "notice", "label": f"Change notice (rev {rev})", "ok": True})
    return {"ready": _verified(st), "build_id": build, "revision": rev, "items": items,
            "release": release_view(ws, cur), "releases": [{k: r.get(k) for k in ("rev", "date", "by", "note")}
                                                           for r in reversed(releases(ws))]}


def _zip(root: str, files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k in sorted(files):
            info = zipfile.ZipInfo(f"{root}/{k}", ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, files[k])
    return buf.getvalue()


def build_pack(ws: Path, project_name: str, user: str | None = None, include_stale: bool = False,
               release: dict[str, Any] | None = None, drawing_dir: Path | None = None,
               extra: dict[str, bytes] | None = None, left_out: list[str] | None = None) -> tuple[bytes, dict[str, Any]]:
    """The zip bytes and its manifest. Stale drawing/DFM outputs are left out unless include_stale.

    For a release: ``release`` is the record being issued, ``drawing_dir`` holds its issue copy of the drawing and
    ``extra`` the other frozen files (calculation packages, print exports) by their path in the pack."""
    st = deliverables.read_status(ws)
    if not _verified(st):
        raise ValueError("The current model isn't verified; fix the build before handing it off")
    name = _safe(project_name)
    pl = plan(ws)
    files: dict[str, bytes] = {}
    for f, _label in MODEL_FILES:
        p = ws / "out" / f
        if p.is_file():
            files[f"model/{name}.{f.split('.')[-1]}"] = p.read_bytes()
    stale: list[str] = []
    missing: list[str] = []
    for it in pl["items"]:
        if it.get("missing"):
            missing.append(it["label"])
        elif it.get("stale"):
            stale.append(it["label"])
    drw = _json(ws / "drawings" / "drawing.json")
    ddir = drawing_dir or ws / "drawings"
    if (drawing_dir is not None) or (drw and (include_stale or not any(s.startswith("Drawing") for s in stale))):
        for f in ("sheet.pdf", "sheet.dxf", "sheet.svg"):
            p = ddir / f
            if p.is_file():
                files[f"drawing/{name}_drawing.{f.split('.')[-1]}"] = p.read_bytes()
    dfm = _json(ws / "manufacturing" / "analysis.json")
    if dfm and (include_stale or "Manufacturability report" not in stale):
        from aicad.manufacturing import report

        topo = _json(ws / "out" / "topo.json") or None
        files[f"dfm/{name}_dfm.pdf"] = report.build_pdf(dfm, project_name, topo)
    for k, v in (extra or {}).items():
        files[k] = v
    rev = pl["revision"]
    if rev is not None:
        n = change_notice.notice(ws / "revisions", rev)
        n["project"] = {"name": project_name}
        files["CHANGE_NOTICE.txt"] = notice_text(n).encode("utf-8")
    fp = st.get("fingerprint") or {}
    m = materials.get(materials.guess(st.get("material")))
    mass = f"{float(fp['volume']) * float(m['density_g_cm3']) / 1000:,.1f} g ({m['name']}, typical density)" if m and fp.get("volume") else "-"
    gating = [c["id"] for c in st.get("checks") or [] if c.get("gating") and not c.get("passed")]
    if release:
        head = [f"FORMWRIGHT RELEASE: {project_name} · REV {release['rev']}",
                (f"Issued {release.get('date', '')} by {release.get('by') or '-'} · model rev {rev if rev is not None else '-'}"
                f" · build {str(st.get('build_id', ''))[-8:]}"),
                f"Change: {release.get('note') or '-'}"]
    else:
        head = [f"FORMWRIGHT SHOP HANDOFF: {project_name}",
                f"Revision {rev if rev is not None else '-'} · build {str(st.get('build_id', ''))[-8:]} · "
                f"{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}" + (f" · prepared by {user}" if user else "")]
    readme = "\n".join([
        *head,
        "",
        f"Part:      {st.get('part') or project_name}",
        f"Material:  {st.get('material') or '-'}",
        f"Envelope:  {' × '.join(f'{v:g}' for v in fp.get('bbox', []))} mm",
        f"Volume:    {fp.get('volume', 0):,.1f} mm³",
        f"Mass:      {mass}",
        f"Checks:    {'geometry checks passed' if not gating else 'FAILING: ' + ', '.join(gating)}",
        "",
        "Contents:",
        *[f"  {k}" for k in sorted(files)],
        *(["", "Left out (older than this revision; regenerate first): " + ", ".join(stale)] if stale and not include_stale and not release else []),
        *(["", "Included although older than this revision: " + ", ".join(stale)] if stale and include_stale else []),
        *(["", "Left out of this release: " + "; ".join(left_out)] if left_out else []),
        *(["", "Not produced yet: " + ", ".join(missing)] if missing else []),
        "",
        "Checks prove geometric consistency of the model only. This pack is not a manufacturing approval;",
        "engineering sign-off and the released drawing remain the responsibility of the design owner.",
        "Verify each file's SHA-256 against manifest.json.",
    ]) + "\n"
    files["README.txt"] = readme.encode("utf-8")
    manifest = {
        "project": project_name, "revision": rev, "build_id": st.get("build_id"), "fingerprint": fp,
        "material": st.get("material"), "checks_passed": not gating,
        "stale_excluded": stale if not include_stale and not release else [],
        "stale_included": stale if include_stale else [], "missing": missing,
        "files": {k: {"sha256": hashlib.sha256(v).hexdigest(), "bytes": len(v)} for k, v in sorted(files.items())},
    }
    if release:
        manifest["release"] = {k: release.get(k) for k in ("rev", "date", "by", "note", "issued_at")} | {
            "step_sha256": st.get("step_sha256"), "left_out": left_out or []}
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    root = f"{name}_rev{release['rev']}" if release else f"{name}_rev{rev if rev is not None else 0}"
    return _zip(root, files), manifest


def record_release(ws: Path, release: dict[str, Any], pack: bytes, manifest: dict[str, Any]) -> dict[str, Any]:
    """Write the frozen pack and append the release record (the caller holds the per-project lock)."""
    d = ws / "releases" / release["rev"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "pack.zip").write_bytes(pack)
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rec = {**release, "pack_sha256": hashlib.sha256(pack).hexdigest(), "pack_bytes": len(pack),
           "files": sorted(manifest["files"])}
    rels = releases(ws) + [rec]
    p = ws / "releases" / "releases.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rels, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(p)
    return rec


def release_pack_path(ws: Path, rev: str) -> Path | None:
    if not re.fullmatch(r"[A-Z]{1,3}", rev or ""):
        return None
    p = ws / "releases" / rev / "pack.zip"
    return p if p.is_file() else None
