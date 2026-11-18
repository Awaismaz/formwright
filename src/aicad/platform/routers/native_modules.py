"""Save / open every module's work as a Formwright file (IO-025). Routes live on the ``/api/native`` router of
``mod_native`` (registered when that module imports this one); the formats are in ``aicad.native.modules``.

  GET /api/native/modules/{kind}/{id}/export
      kind = mfg | calc | print | mesh | ai  (id = project)     -> .fwmfg .fwcalc .fwprint .fwrender
             draft (id = 2D drawing) -> .fwdrw · read (id = Image-to-CAD upload) -> .fwread
             upload (id = 3D Print Prep mesh upload) -> .fwprint
Imports go through POST /api/native/import like every other Formwright file.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import Depends, HTTPException
from fastapi.responses import Response

from aicad.native import NativeFormatError
from aicad.native import container as c
from aicad.native import modules as nm
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.models import Project
from aicad.platform.routers import projects as prj
from aicad.platform.routers.mod_native import _dd, _download, _err, _import_part, part_bytes, router
from aicad.platform.services import audit, org_modules, track

MODULE_LABEL = {"drawings": "Drawing Studio", "manufacturing": "Manufacturing Advisor",
                "engineering": "Engineering Advisor", "print": "3D Print Prep", "mesh": "Mesh Studio",
                "airender": "AI Render Studio", "image2cad": "Image & Drawing to CAD"}


def _module(ctx: Ctx, code: str) -> None:
    if code not in org_modules(ctx.db, ctx.require_org()) and not ctx.god_on("bypass_paywall"):
        raise HTTPException(402, {"message": f"{MODULE_LABEL.get(code, 'This module')} is not included in your plan.",
                                  "cta": f"/app/modules/{code}"})


def _editor(ctx: Ctx) -> None:
    if ctx.role == "viewer":
        raise HTTPException(403, "Viewers can't import files.")


def _write(ctx: Ctx, ext: str, files: dict[str, bytes], manifest: dict[str, Any], target: str, stem: str) -> Response:
    org = ctx.require_org()
    manifest["source"] = {"org": c.org_tag(_dd(), org.id), "document": c.opaque(_dd(), ext, target)}
    try:
        data = c.write_package(ext, files, manifest, _dd(), org.id)
    except NativeFormatError as e:
        raise _err(e) from None
    audit(ctx.db, "native.exported", ctx.user, org.id, target=target, format=ext, kind=manifest.get("kind"))
    track(ctx.db, "native_export", ctx.user, org.id, format=ext, kind=manifest.get("kind"))
    ctx.db.commit()
    return _download(data, stem, ext)


@router.get("/modules/{kind}/{ident}/export")
async def export_module(kind: str, ident: str, ctx: Ctx = Depends(verified_ctx)) -> Response:
    org = ctx.require_org()
    if kind in nm.FOLDER_KINDS:
        fk = nm.FOLDER_KINDS[kind]
        _module(ctx, fk.module)
        p = prj._project(ctx, ident)
        try:
            files = nm.folder_files(prj.workspace_for(p), fk)
        except NativeFormatError as e:
            raise _err(e) from None
        files["part.fwpart"] = await part_bytes(ctx, p)
        manifest = nm.folder_manifest(fk, f"{p.name} · {fk.label}", len(files) - 1)
        return _write(ctx, fk.ext, files, manifest, p.id, f"{p.name}_{fk.kind}")
    if kind == "draft":
        from aicad.drawing import draft_store
        from aicad.platform.routers import mod_drafting as mdr

        _module(ctx, "drawings")
        rec = mdr._rec(ctx, ident)
        root = mdr._root(ctx)
        revs = []
        for r in rec.get("revs", []):
            d = draft_store.load_rev(root, ident, r["rev"])
            if d:
                revs.append((int(r["rev"]), d))
        files, manifest = nm.draft_files(rec, revs)
        return _write(ctx, "fwdrw", files, manifest, ident, str(rec.get("name") or "drawing"))
    if kind == "read":
        from aicad.image2cad import store as istore

        _module(ctx, "image2cad")
        d = istore.upload_dir(_dd(), org.id, ident)
        if d is None:
            raise HTTPException(404, "Upload not found")
        meta = istore.read_json(d, "meta.json") or {}
        files, manifest = nm.read_files(d, meta)
        return _write(ctx, "fwread", files, manifest, ident, str(meta.get("name") or "drawing"))
    if kind == "upload":
        from aicad.printprep import service as psvc

        _module(ctx, "print")
        d = psvc.upload_dir(_dd(), org.id, ident)
        if d is None:
            raise HTTPException(404, "Upload not found")
        try:
            files, manifest = nm.upload_files(d, psvc.read_meta(d))
        except NativeFormatError as e:
            raise _err(e) from None
        return _write(ctx, "fwprint", files, manifest, ident, str(manifest["title"]))
    raise HTTPException(404, "Unknown kind")


# ---------------------------------------------------------------------------------------------------- importers
async def import_folder(ctx: Ctx, parsed: dict[str, Any], filename: str, trust: str) -> dict[str, Any]:
    fk: nm.FolderKind = parsed["fk"]
    _module(ctx, fk.module)
    r = await _import_part(ctx, parsed["part"], parsed["part_summary"], filename, trust, link=False)
    ws = prj.workspace_for(ctx.db.get(Project, r["project"]["id"]))
    ids: dict[str, str | None] = {"org": ctx.require_org().id, "project": r["project"]["id"], "user": ctx.user.id}
    try:
        notes = nm.install_folder(ws, fk, parsed["docs"], ids, foreign=trust != "workspace")
    except NativeFormatError as e:
        raise _err(e) from None
    return {**r, "kind": fk.kind, "module": fk.module, "notes": notes}


def import_draft(ctx: Ctx, parsed: dict[str, Any]) -> dict[str, Any]:
    from aicad.drawing import draft_store
    from aicad.platform.routers import mod_drafting as mdr

    _module(ctx, "drawings")
    _editor(ctx)
    root = mdr._root(ctx)
    user = ctx.user.name or ctx.user.email
    revs = parsed["revs"] or [(1, parsed["doc"])]
    rec = draft_store.create(root, ctx.require_org().id, user, parsed["name"], revs[0][1])
    for _, doc in revs[1:]:
        rec = draft_store.save(root, rec, doc, user, "Imported revision")
    if rec["doc"] != parsed["doc"]:
        rec = draft_store.save(root, rec, parsed["doc"], user, "Imported")
    audit(ctx.db, "draft.created", ctx.user, ctx.require_org().id, target=rec["id"], source="native_import")
    return {"kind": "draft", "draft": {"id": rec["id"], "name": rec["name"]}, "revisions": rec["rev"]}


def import_read(ctx: Ctx, parsed: dict[str, Any]) -> dict[str, Any]:
    from aicad.image2cad import store as istore

    _module(ctx, "image2cad")
    _editor(ctx)
    org = ctx.require_org()
    uid = uuid.uuid4().hex
    d = istore.root(_dd(), org.id) / uid
    d.mkdir()
    files = parsed["files"]
    src = parsed["source"].split("/", 1)[1]
    (d / src).write_bytes(files[parsed["source"]])
    if "read/preview.png" in files:
        (d / "preview.png").write_bytes(files["read/preview.png"])
    ids: dict[str, str | None] = {"org": org.id, "project": None, "user": ctx.user.id}
    for n in ("read.json", "review.json"):
        if f"read/{n}" in files:
            istore.write_json(d, n, nm.fill_ids(json.loads(files[f"read/{n}"]), ids))
    meta = {k: parsed["meta"].get(k) for k in nm.READ_META_KEYS if k in parsed["meta"]}
    status = meta.get("status")
    if status in (None, "reading"):
        status = "read" if "read/read.json" in files else "failed"
    meta.update(id=uid, file=src, type=parsed["kind"], bytes=len(files[parsed["source"]]), created_by=ctx.user.id,
                created_at=c.iso().replace("Z", ""), project_id=None, status=status)
    istore.write_json(d, "meta.json", meta)
    audit(ctx.db, "image2cad.uploaded", ctx.user, org.id, target=uid, source="native_import")
    return {"kind": "read", "upload": {"id": uid, "name": meta.get("name")}}


def import_upload(ctx: Ctx, parsed: dict[str, Any]) -> dict[str, Any]:
    from aicad.printprep import service as psvc

    _module(ctx, "print")
    _editor(ctx)
    units = parsed["summary"]["units"] if parsed["summary"]["units"] in ("mm", "in", "cm", "m") else "mm"
    try:
        meta = psvc.create_upload(_dd(), ctx.require_org().id, ctx.user.id, parsed["name"], parsed["data"], units)
    except ValueError as e:  # MeshError: the module's own mesh validation
        raise HTTPException(422, f"The mesh in the file was rejected: {e}") from None
    notes = ["The mesh was imported as uploaded; run the repair again here if it needed one."] \
        if parsed["meta"].get("repaired") else []
    return {"kind": "upload", "upload": {"id": meta["id"], "name": meta["name"]}, "notes": notes}
