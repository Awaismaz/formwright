"""Formwright native files (IO-020..IO-024): export and import .fwpart / .fwasm / .fwdrw / .fwprog with the full
parametric model, so work moves between workspaces without feature recognition. Spec: docs/FORMATS.md.

(Named ``mod_native`` so the app factory picks the router up like a module router; it is a platform feature, not a
paid module. Downloads need the module of the document: Assembly Studio for .fwasm, Drawing Studio for .fwdrw.)

  GET  /api/native/projects/{id}/export?history=1&refs=1&chat=0   .fwpart of a project
  GET  /api/native/projects/export-all                             zip of every built project as .fwpart
  GET  /api/native/assemblies/{id}/export                          .fwasm (embedded parts, deduplicated)
  GET  /api/native/drawings/{project_id}/export                    .fwdrw (sheet definition + embedded part)
  GET  /api/native/programs/{id}/export                            .fwprog (program + its parts and assemblies)
  GET  /api/native/projects/{id}/provenance                        how an imported project was verified
  POST /api/native/inspect?filename=..                             validate an upload (raw body); nothing is written
  POST /api/native/import?filename=..&confirm=1                    validate, create, rebuild, verify

Import treats the file as untrusted (``aicad.native.container``/``gate``): nothing is written or run before every check
passes. Files exported by this workspace with a valid signature are trusted; anything else needs ``confirm=1``.
"""

from __future__ import annotations

import json
import re
import shutil
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select

from aicad.native import NativeFormatError, bundles
from aicad.native import container as c
from aicad.native import part as fpart
from aicad.platform.config import get_settings
from aicad.platform.db import utcnow
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.models import Project
from aicad.platform.routers import projects as prj
from aicad.platform.services import audit, track

router = APIRouter(prefix="/api/native", tags=["native"])
KIND = {"fwpart": "part", "fwasm": "assembly", "fwdrw": "drawing", "fwprog": "program", "zip": "projects"}
STATES = {"identical": "Verified identical", "mismatch": "Rebuilt with differences",
          "fallback": "Exact geometry kept (read-only)"}


def _dd() -> Any:
    return get_settings().data_dir


def _err(e: NativeFormatError) -> HTTPException:
    return HTTPException(e.status, str(e))


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", name).strip("_")[:60] or "formwright"


def _download(data: bytes, stem: str, ext: str) -> Response:
    return Response(data, media_type=c.FORMATS[ext][1], headers={
        "Content-Disposition": f'attachment; filename="{_safe(stem)}.{ext}"', "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff"})


def _flag(v: str | None, default: bool) -> bool:
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------------------------------- export
async def part_bytes(ctx: Ctx, p: Project, history: bool = True, refs: bool = True, chat: bool = False) -> bytes:
    await prj.wait_finalized(p.id)
    try:
        return fpart.export_part(prj.workspace_for(p), name=p.name, description=p.description or "", project_id=p.id,
                                 org_id=p.org_id, data_dir=_dd(), history=history, refs=refs, chat=chat)
    except NativeFormatError as e:
        raise HTTPException(e.status, f"{p.name}: {e}") from None


@router.get("/projects/export-all")
async def export_all(ctx: Ctx = Depends(verified_ctx)) -> Response:
    """Every built project of the workspace as .fwpart files in one zip (history and reference images included)."""
    org = ctx.require_org()
    rows = ctx.db.scalars(select(Project).where(Project.org_id == org.id).order_by(Project.created_at)).all()
    files: dict[str, bytes] = {}
    skipped = []
    for p in rows:
        try:
            data = await part_bytes(ctx, p)
        except HTTPException:
            skipped.append(p.name)
            continue
        files[f"parts/{_safe(p.name)}_{p.id[:8]}.fwpart"] = data
    if not files:
        raise HTTPException(409, "No project has a built model to export yet.")
    manifest = {"app_version": c.app_version(), "generator": "Formwright", "created_at": c.iso(),
                "title": f"{org.name} projects", "projects": len(files), "skipped": skipped}
    data = c.write_package("zip", files, manifest, _dd(), org.id)
    audit(ctx.db, "native.exported_all", ctx.user, org.id, projects=len(files))
    ctx.db.commit()
    return _download(data, f"{org.name}_projects", "zip")


@router.get("/projects/{project_id}/export")
async def export_project(project_id: str, history: str | None = None, refs: str | None = None, chat: str | None = None,
                         ctx: Ctx = Depends(verified_ctx)) -> Response:
    p = prj._project(ctx, project_id)
    data = await part_bytes(ctx, p, _flag(history, True), _flag(refs, True), _flag(chat, False))
    audit(ctx.db, "native.exported", ctx.user, p.org_id, target=p.id, format="fwpart", chat=_flag(chat, False))
    track(ctx.db, "native_export", ctx.user, p.org_id, format="fwpart")
    ctx.db.commit()
    return _download(data, p.name, "fwpart")


@router.get("/assemblies/{aid}/export")
async def export_assembly(aid: str, history: str | None = None, refs: str | None = None,
                          ctx: Ctx = Depends(verified_ctx)) -> Response:
    data, doc = await assembly_bytes(ctx, aid, _flag(history, True), _flag(refs, True))
    track(ctx.db, "native_export", ctx.user, ctx.require_org().id, format="fwasm")
    ctx.db.commit()
    return _download(data, str(doc.get("name") or "assembly"), "fwasm")


async def assembly_bytes(ctx: Ctx, aid: str, history: bool = True, refs: bool = True) -> tuple[bytes, dict[str, Any]]:
    from aicad.assembly import service, store
    from aicad.platform.routers import mod_assembly as ma

    ma.asm_ctx(ctx)
    doc = ma._doc(ctx, aid)
    root = ma._root(ctx)
    projects = ma._projects_for(ctx, doc)
    part_refs: dict[str, dict[str, Any]] = {}
    pbytes: dict[str, bytes] = {}
    cache: dict[str, bytes] = {}
    for i in doc["instances"]:
        key = i["part"]
        if key in part_refs:
            continue
        meta = store.part(root, key)
        if meta is None:
            raise HTTPException(409, "A part of this assembly is missing. Remove and re-insert it, then export.")
        if meta["kind"] == "project":
            p = projects.get(meta["project_id"])
            if p is None:
                raise HTTPException(409, f"{meta['name']}: its project no longer exists, so its model can't be "
                                         "exported. Replace that part, then export.")
            st = ma._status(prj.workspace_for(p))
            if str(st.get("build_id")) != str(meta.get("build_id")):
                raise HTTPException(409, f"{p.name} changed since it was placed. Refresh it in the assembly "
                                         "(Part updated: refresh), then export.")
            if p.id not in cache:
                cache[p.id] = await part_bytes(ctx, p, history, refs)
            pbytes[key] = cache[p.id]
            part_refs[key] = {"kind": "project", "name": p.name, "fingerprint": st.get("fingerprint"),
                              "step_sha256": st.get("step_sha256")}
        else:
            part_refs[key] = {"kind": "toolbox", "code": meta["code"], "params": meta["params"],
                              "version": meta["version"], "name": meta.get("name")}
    names = {pid: p.name for pid, p in projects.items()}
    try:
        bom = service.bom(root, doc, names)
    except Exception:  # noqa: BLE001 - the BOM is informational in the file
        bom = None
    thumb_f = store.doc_dir(root, aid) / "thumb.png"
    files, manifest = bundles.assembly_files(doc, part_refs, pbytes, bom, thumb_f.read_bytes() if thumb_f.is_file() else None)
    org = ctx.require_org()
    manifest["source"] = {"org": c.org_tag(_dd(), org.id), "assembly": c.opaque(_dd(), "assembly", aid)}
    data = c.write_package("fwasm", files, manifest, _dd(), org.id)
    audit(ctx.db, "native.exported", ctx.user, org.id, target=aid, format="fwasm")
    return data, doc


@router.get("/drawings/{project_id}/export")
async def export_drawing(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> Response:
    from aicad.platform.routers import mod_drawings as md

    p = md._project(ctx, project_id)
    ws = prj.workspace_for(p)
    rec = md._record(ws)
    if rec is None:
        raise HTTPException(409, "This part has no drawing yet. Generate it in Drawing Studio first.")
    sheets = {n: (ws / "drawings" / n).read_bytes() for n in ("sheet.pdf",) if (ws / "drawings" / n).is_file()}
    files, manifest = bundles.drawing_files(rec, md._edits(ws), await part_bytes(ctx, p), sheets, f"{p.name} drawing")
    org = ctx.require_org()
    manifest["source"] = {"org": c.org_tag(_dd(), org.id), "project": c.opaque(_dd(), "project", p.id)}
    data = c.write_package("fwdrw", files, manifest, _dd(), org.id)
    audit(ctx.db, "native.exported", ctx.user, org.id, target=p.id, format="fwdrw")
    track(ctx.db, "native_export", ctx.user, org.id, format="fwdrw")
    ctx.db.commit()
    return _download(data, f"{p.name}_drawing", "fwdrw")


@router.get("/programs/{pid}/export")
async def export_program(pid: str, ctx: Ctx = Depends(verified_ctx)) -> Response:
    from aicad.office import store as ostore
    from aicad.platform.routers import office as of

    doc = of._load(ctx, pid)
    org = ctx.require_org()
    pb: dict[str, bytes] = {}
    ab: dict[str, bytes] = {}
    for t in doc.get("tickets", []):
        if t.get("project_id") and t["project_id"] not in pb:
            p = ctx.db.get(Project, t["project_id"])
            if p is not None and p.org_id == org.id and (prj.workspace_for(p) / "model.py").is_file():
                try:
                    pb[p.id] = await part_bytes(ctx, p)
                except HTTPException:
                    pass  # not built yet: the ticket keeps its brief, the part is designed again
        if t.get("assembly_id") and t["assembly_id"] not in ab:
            try:
                ab[t["assembly_id"]] = (await assembly_bytes(ctx, t["assembly_id"]))[0]
            except HTTPException:
                pass
    events = ostore.events(of._root(ctx), pid, limit=5000)
    files, manifest = bundles.program_files(doc, events, pb, ab)
    manifest["source"] = {"org": c.org_tag(_dd(), org.id), "program": c.opaque(_dd(), "program", pid)}
    data = c.write_package("fwprog", files, manifest, _dd(), org.id)
    audit(ctx.db, "native.exported", ctx.user, org.id, target=pid, format="fwprog")
    track(ctx.db, "native_export", ctx.user, org.id, format="fwprog")
    ctx.db.commit()
    return _download(data, str(doc.get("name") or "program"), "fwprog")


# ---------------------------------------------------------------------------------------------------- import
async def _body(request: Request) -> bytes:
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > c.MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Formwright files up to 200 MB can be imported.")
    if not buf:
        raise HTTPException(400, "The file is empty.")
    return bytes(buf)


def _ext(filename: str, data: bytes) -> str | None:
    low = filename.lower().rsplit(".", 1)
    ext = low[1] if len(low) == 2 else ""
    if ext in c.FORMATS:
        return ext
    return c.sniff_ext(data)


def _open(ctx: Ctx, data: bytes, filename: str) -> dict[str, Any]:
    """Read + validate everything (nested packages and every script included). Nothing is written."""
    org = ctx.require_org()
    ext = _ext(filename, data)
    if ext is None:
        raise HTTPException(415, "Drop a Formwright file: .fwpart, .fwasm, .fwdrw, .fwprog, or a projects archive.")
    try:
        pkg = c.read_package(data, ext)
        trust, note = c.trust_for(pkg.manifest, _dd(), org.id)
        strict = trust != "workspace"
        if pkg.ext == "fwpart":
            parsed: dict[str, Any] = {"summary": fpart.validate(pkg, strict=strict)}
        elif pkg.ext == "fwasm":
            parsed = bundles.parse_assembly(pkg, strict=strict)
        elif pkg.ext == "fwdrw":
            parsed = bundles.parse_drawing(pkg, strict=strict)
        elif pkg.ext == "fwprog":
            parsed = bundles.parse_program(pkg, strict=strict)
        else:
            parsed = bundles.parse_projects(pkg, strict=strict)
    except NativeFormatError as e:
        raise _err(e) from None
    return {"pkg": pkg, "parsed": parsed, "trust": trust, "note": note}


def _inspect_view(o: dict[str, Any], filename: str) -> dict[str, Any]:
    pkg = o["pkg"]
    return {"kind": KIND[pkg.ext], "format": pkg.ext, "filename": filename[:200], "size": pkg.size,
            "trust": o["trust"], "trust_note": o["note"], "needs_confirm": o["trust"] != "workspace",
            "summary": o["parsed"]["summary"], "warnings": pkg.warnings, "format_version": pkg.manifest["format_version"],
            "migrated_from": pkg.migrated_from}


@router.post("/inspect")
async def inspect(request: Request, filename: str = "", ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    data = await _body(request)
    return _inspect_view(_open(ctx, data, filename), filename)


@router.post("/import")
async def import_file(request: Request, filename: str = "", confirm: str | None = None,
                      ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    if ctx.role == "viewer":
        raise HTTPException(403, "Viewers can't import files.")
    data = await _body(request)
    o = _open(ctx, data, filename)
    if o["trust"] != "workspace" and not _flag(confirm, False):
        raise HTTPException(409, {"message": "This file comes from another workspace. Review it and confirm before "
                                             "Formwright rebuilds it.", "needs_confirm": True})
    pkg, parsed, trust = o["pkg"], o["parsed"], o["trust"]
    fname = filename[:120] or f"file.{pkg.ext}"
    if pkg.ext == "fwpart":
        res: dict[str, Any] = await _import_part(ctx, pkg, parsed["summary"], fname, trust, link=False)
    elif pkg.ext == "fwasm":
        res = await _import_assembly(ctx, parsed, fname, trust)
    elif pkg.ext == "fwdrw":
        res = await _import_drawing(ctx, parsed, fname, trust)
    elif pkg.ext == "fwprog":
        res = await _import_program(ctx, parsed, fname, trust)
    else:
        items = [await _import_part(ctx, p["pkg"], p["summary"], fname, trust, link=True)
                 for p in parsed["parts"].values()]
        res = {"kind": "projects", "parts": items}
    audit(ctx.db, "native.imported", ctx.user, ctx.require_org().id, format=pkg.ext, trust=trust, bytes=pkg.size)
    track(ctx.db, "native_import", ctx.user, ctx.require_org().id, format=pkg.ext, trust=trust)
    ctx.db.commit()
    return {**res, "trust": trust, "format": pkg.ext, "warnings": pkg.warnings}


def _unique_name(ctx: Ctx, name: str) -> str:
    names = {n.lower() for n in ctx.db.scalars(select(Project.name).where(Project.org_id == ctx.require_org().id))}
    base = (name.strip() or "Imported part")[:110]
    out, n = base, 2
    while out.lower() in names:
        out, n = f"{base} ({n})", n + 1
    return out


def _find_identical(ctx: Ctx, pkg: c.Package) -> Project | None:
    """An existing project of this workspace with the same geometry (fingerprint, exact STEP) and material."""
    geo = pkg.manifest.get("geometry") or {}
    want_sha, fp = geo.get("step_sha256"), geo.get("fingerprint") or {}
    material = (pkg.manifest.get("part") or {}).get("material")
    rows = ctx.db.scalars(select(Project).where(Project.org_id == ctx.require_org().id, Project.archived.is_(False))
                          .order_by(Project.updated_at.desc())).all()
    for p in rows:
        if fpart.compare(fp, (p.last_status or {}).get("fingerprint")):
            continue
        st = prj._read_status(prj.workspace_for(p))
        if st.get("ok") and want_sha and st.get("step_sha256") == want_sha and st.get("material") == material:
            return p
    return None


def _project_view(p: Project) -> dict[str, Any]:
    return {"id": p.id, "name": p.name}


async def _import_part(ctx: Ctx, pkg: c.Package, summary: dict[str, Any], filename: str, trust: str,
                       *, link: bool) -> dict[str, Any]:
    if link:
        same = _find_identical(ctx, pkg)
        if same is not None:
            return {"kind": "part", "action": "linked", "project": _project_view(same),
                    "verification": {"state": "identical", "label": "Already in your workspace (identical geometry)",
                                     "diffs": [], "step_identical": True}}
    org = ctx.require_org()
    p = Project(org_id=org.id, name=_unique_name(ctx, summary["title"]), description=summary["description"],
                created_by=ctx.user.id)
    ctx.db.add(p)
    ctx.db.flush()
    ws = prj.workspace_for(p)
    try:
        fpart.install(pkg, ws)
        ver, st = await _rebuild_verified(p, ws, pkg)
    except BaseException:
        ctx.db.delete(p)
        ctx.db.commit()
        shutil.rmtree(ws, ignore_errors=True)
        raise
    p.last_status = prj._status_summary(st)
    p.builds = 1
    p.updated_at = utcnow()
    rev = prj._snapshot(p, ws, cause=f"Imported from {filename} ({STATES[ver['state']].lower()})", kind="import",
                        by=ctx.user.name)
    record = {"file": filename, "format": "fwpart", "trust": trust, "verification": ver, "imported_at": c.iso(),
              "imported_by": ctx.user.name, "revision": rev, "source_app_version": summary.get("app_version"),
              "source_kernel": summary.get("kernel"), "created_at": summary.get("created_at")}
    (ws / ".fw" / "native").mkdir(parents=True, exist_ok=True)
    (ws / ".fw" / "native" / "import.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    audit(ctx.db, "project.created", ctx.user, org.id, target=p.id, name=p.name, source="native_import")
    ctx.db.commit()
    return {"kind": "part", "action": "imported", "project": _project_view(p), "verification": ver, "revision": rev}


async def _rebuild_verified(p: Project, ws: Any, pkg: c.Package) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rebuild the imported model in this workspace's build worker and compare its geometry with the file's."""
    from aicad.platform.plain import build_error

    geo = pkg.manifest["geometry"]
    expected = geo["fingerprint"]
    st = await prj._rebuild(p, ws, determinism=False, fast=False)
    state, reason = None, None
    if st.get("error") or not st.get("fingerprint"):
        reason = build_error(st.get("error"), st.get("checks"))
        (ws / fpart.ORIGINAL_MODEL).write_bytes(pkg.files["model.py"])
        (ws / "imports").mkdir(exist_ok=True)
        shutil.copy2(ws / fpart.ORIGINAL_STEP, ws / "imports" / "original_part.step")
        material = (pkg.manifest.get("part") or {}).get("material")
        (ws / "model.py").write_text(fpart.fallback_source(str((pkg.manifest.get("part") or {}).get("name")
                                                               or "Imported part"), material), encoding="utf-8")
        st = await prj._rebuild(p, ws, determinism=False, fast=False)
        if st.get("error"):
            raise HTTPException(422, "The part could not be rebuilt and its exact geometry could not be read either. "
                                     "Nothing was imported.")
        state = "fallback"
    diffs = fpart.compare(expected, st.get("fingerprint"))
    state = state or ("identical" if not diffs else "mismatch")
    ver = {"state": state, "label": STATES[state], "diffs": diffs, "reason": reason,
           "step_identical": bool(geo.get("step_sha256")) and st.get("step_sha256") == geo.get("step_sha256"),
           "expected": expected, "rebuilt": st.get("fingerprint"), "checks_ok": bool(st.get("ok"))}
    return ver, st


@router.get("/projects/{project_id}/provenance")
def provenance(project_id: str, ctx: Ctx = Depends(verified_ctx)) -> dict[str, Any]:
    f = prj.workspace_for(prj._project(ctx, project_id)) / ".fw" / "native" / "import.json"
    try:
        return {"import": json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None}
    except (OSError, ValueError):
        return {"import": None}


async def _import_assembly(ctx: Ctx, parsed: dict[str, Any], filename: str, trust: str) -> dict[str, Any]:
    from aicad import toolbox
    from aicad.assembly import AssemblyInputError, service, solver, store
    from aicad.platform.routers import mod_assembly as ma

    ma.asm_ctx(ctx)
    org = ctx.require_org()
    root = ma._root(ctx)
    keys: dict[str, str] = {}
    results = []
    for ref, p in parsed["parts"].items():
        try:
            if p["kind"] == "project":
                r = await _import_part(ctx, p["pkg"], p["summary"], filename, trust, link=True)
                results.append(r)
                keys[ref] = await ma._project_part(ctx, ctx.db.get(Project, r["project"]["id"]))
            else:
                keys[ref] = await service.ensure_toolbox_part(root, org.id, p["code"], p["params"])
        except (AssemblyInputError, toolbox.ToolboxError, service.WorkerError) as e:
            raise HTTPException(422, f"A part of the assembly could not be added: {e}") from None
    src = parsed["doc"]
    doc = store.new_doc(src["name"], org.id, ctx.user.id, None)
    for i in src["instances"]:
        meta = store.part(root, keys[i["part"]])
        if meta is None:
            raise HTTPException(500, "A part of the assembly could not be prepared. Try again.")
        doc["instances"].append({"id": i["id"], "name": str(i.get("name") or meta["name"])[:120], "part": keys[i["part"]],
                                 "source": service._source(meta), "T": [float(x) for x in i["T"]],
                                 "fixed": bool(i.get("fixed")), "visible": i.get("visible", True) is not False,
                                 "group": i["group"] if isinstance(i.get("group"), str) else None})
    nums = [int(x["id"][1:]) for x in doc["instances"]] + [int(m["id"][1:]) for m in src["mates"]]
    doc["seq"] = max([int(src.get("seq") or 0), *nums, 0])
    dropped = 0
    for m in src["mates"]:
        try:
            if m.get("type") not in solver.MATE_TYPES:
                raise AssemblyInputError("type")
            a = service.resolve_ref(root, doc, m["a"])
            b = service.resolve_ref(root, doc, m["b"])
        except (AssemblyInputError, KeyError, TypeError, ValueError):
            dropped += 1
            continue
        doc["mates"].append({"id": m["id"], "type": m["type"], "a": a, "b": b, "value": float(m.get("value") or 0.0),
                             "flip": bool(m.get("flip")), "suppressed": bool(m.get("suppressed")), "broken": False,
                             "group": m["group"] if isinstance(m.get("group"), str) else None})
    doc["groups"] = [g for g in src["groups"] if isinstance(g, dict) and isinstance(g.get("id"), str)]
    try:
        service.run_solve(root, doc)
    except AssemblyInputError:
        pass
    store.save(root, doc)
    audit(ctx.db, "assembly.created", ctx.user, org.id, target=doc["id"], source="native_import")
    ctx.db.commit()
    return {"kind": "assembly", "assembly": {"id": doc["id"], "name": doc["name"]}, "parts": results,
            "mates": len(doc["mates"]), "mates_dropped": dropped,
            "verification": _overall([r["verification"] for r in results])}


def _overall(vs: list[dict[str, Any]]) -> dict[str, Any]:
    if not vs:
        return {"state": "identical", "label": STATES["identical"], "diffs": []}
    worst = "fallback" if any(v["state"] == "fallback" for v in vs) else \
        "mismatch" if any(v["state"] == "mismatch" for v in vs) else "identical"
    return {"state": worst, "label": STATES[worst] if worst != "identical" else "Verified identical (every part)",
            "diffs": [d for v in vs for d in v.get("diffs", [])]}


async def _import_drawing(ctx: Ctx, parsed: dict[str, Any], filename: str, trust: str) -> dict[str, Any]:
    from aicad.drawing import DrawingInputError
    from aicad.drawing.generate import normalize_edits
    from aicad.platform.routers import mod_drawings as md

    md._access(ctx)
    r = await _import_part(ctx, parsed["part"], parsed["part_summary"], filename, trust, link=False)
    p = ctx.db.get(Project, r["project"]["id"])
    ws = prj.workspace_for(p)
    try:
        edits = normalize_edits(parsed["edits"])
    except (DrawingInputError, TypeError, ValueError, AttributeError):
        edits = normalize_edits({})
    (ws / "drawings").mkdir(parents=True, exist_ok=True)
    (ws / "drawings" / "edits.json").write_text(json.dumps(edits, indent=1, sort_keys=True), encoding="utf-8")
    note = None
    try:
        body = md.GenerateIn(**{k: v for k, v in parsed["options"].items() if k in md.GenerateIn.model_fields
                                or k == "tolerance"})
        opts = body.model_dump(exclude={"local_date", "tz"})
        opts["tolerance"] = {"mode": body.tolerance.mode, "class": body.tolerance.tclass, "text": body.tolerance.text}
        meta = md._meta(p, ws, ctx.user.name or ctx.user.email, md.local_date(None, None))
        await md._generate(p, ws, opts, meta, edits, ws / "drawings")
    except (HTTPException, ValueError, TypeError) as e:
        note = ("The part was imported, but its drawing sheet could not be generated here: "
                f"{e.detail if isinstance(e, HTTPException) else 'invalid sheet settings'}. Open Drawing Studio to "
                "generate it.")
    return {**r, "kind": "drawing", "drawing_note": note}


async def _import_program(ctx: Ctx, parsed: dict[str, Any], filename: str, trust: str) -> dict[str, Any]:
    from aicad.office import service as osvc
    from aicad.office import store as ostore
    from aicad.platform.routers import office as of

    of._editor(ctx)
    org = ctx.require_org()
    pmap: dict[str, str] = {}
    amap: dict[str, str] = {}
    results = []
    for entry, p in parsed["parts"].items():
        r = await _import_part(ctx, p["pkg"], p["summary"], filename, trust, link=True)
        results.append(r)
        pmap[entry] = r["project"]["id"]
    for entry, a in parsed["assemblies"].items():
        ra = await _import_assembly(ctx, a, filename, trust)
        results.extend(ra["parts"])
        amap[entry] = ra["assembly"]["id"]
    src = parsed["doc"]
    name = " ".join(str(src.get("name") or "Imported program").split())[:120]
    budget = src.get("budget") if isinstance(src.get("budget"), dict) else {}
    doc = osvc.new_program(name, str(src.get("brief") or "")[:20000], org.id, ctx.user.id,
                           int(src.get("concurrency") or 1) if isinstance(src.get("concurrency"), int) else 1,
                           int(budget.get("tokens") or 0) if isinstance(budget.get("tokens"), int) else 0,
                           "standard" if src.get("planner") != "archie" else "archie")
    keep = ("key", "status", "plan", "plan_history", "gates", "items", "tickets", "ticket_seq", "budget", "planner")
    for k in keep:
        if k in src:
            doc[k] = src[k]
    for t in doc.get("tickets", []):
        t["project_id"] = pmap.get(t.pop("project", None) or "")
        t["assembly_id"] = amap.get(t.pop("assembly", None) or "")
        t["run"] = None
    if doc.get("status") == "planning":
        doc["status"] = "plan_review"
    doc["planning"] = None
    root = of._root(ctx)
    osvc.emit(root, doc, "program.imported", f"{ctx.user.name or 'Someone'} imported the program {name} from a file.",
              of._actor(ctx))
    ostore.save(root, doc)
    audit(ctx.db, "office.program_created", ctx.user, org.id, target=doc["id"], planner="import")
    ctx.db.commit()
    return {"kind": "program", "program": {"id": doc["id"], "name": name}, "parts": results,
            "verification": _overall([r["verification"] for r in results])}
