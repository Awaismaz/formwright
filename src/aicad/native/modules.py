"""Every module's work as a Formwright file, on the one shared container (same manifest, checksums, signature and
untrusted-input rules; the manifest's ``kind`` says what is inside).

Two families:

* **Part-linked outputs** (``FOLDER_KINDS``): a module that keeps its work in a folder of the project workspace
  (Manufacturing Advisor ``manufacturing/``, Engineering Advisor ``engineering/``, 3D Print Prep ``print/``, Mesh Studio
  ``mesh/``, AI Render Studio ``airender/``). The file embeds the part (``part.fwpart``) plus ``doc/<path>`` for each
  allow-listed file of that folder. Import: the part is imported and verified like a .fwpart (a new project), then the
  folder is written back. Outputs stay "current" because the rebuilt STEP is byte-identical (``deliverables.same_build``
  accepts an identical STEP + material).
* **Workspace documents**: 2D drafts (``draft/``), Image-to-CAD reads (``read/``), 3D Print Prep uploaded meshes
  (``upload/``). Import re-validates the content with the module's own checks (draft normaliser, upload sniffing,
  mesh parser) and stores it under a new id.

JSON written to a file never carries workspace, project or user ids (they become null and are filled with the
importer's on import) nor absolute paths (reduced to a file name). The AI Render API key is never in a job folder.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aicad.native import NativeFormatError
from aicad.native import container as c

ID_KEYS = {"org_id": "org", "project_id": "project", "created_by": "user", "user_id": "user", "by_id": "user"}
_ABS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/(?:Users|home|tmp|var|etc|data)/)")


@dataclass(frozen=True)
class FolderKind:
    kind: str           # manifest kind
    ext: str            # file extension
    module: str         # entitlement code
    folder: str         # workspace sub-folder
    label: str          # what the file is, for people
    allow: re.Pattern[str]
    exclude: frozenset[str] = field(default_factory=frozenset)


_J = r"[A-Za-z0-9_\-]{1,80}\.json"
FOLDER_KINDS: dict[str, FolderKind] = {
    "mfg": FolderKind("mfg", "fwmfg", "manufacturing", "manufacturing", "Manufacturing Advisor report",
                      re.compile(_J)),
    "calc": FolderKind("calc", "fwcalc", "engineering", "engineering", "Engineering Advisor calculations",
                       re.compile(_J), frozenset({"geometry.json"})),
    "print": FolderKind("print", "fwprint", "print", "print", "3D Print Prep setup", re.compile(_J),
                        frozenset({"exports.json"})),
    "mesh": FolderKind("mesh", "fwrender", "mesh", "mesh", "Mesh Studio scene and renders", re.compile(
        r"look\.json|renders/[0-9a-f]{16}/(?:job\.json|[A-Za-z0-9_\-]{1,60}\.(?:png|jpg|jpeg|webp|gif|mp4))")),
    "ai": FolderKind("ai", "fwrender", "airender", "airender", "AI Render Studio jobs", re.compile(
        r"[0-9a-f]{16}/(?:job\.json|ref\.png|out_[0-9]{1,3}\.png|thumb_[0-9]{1,3}\.jpg)")),
}
#: every extension the app reads and writes, with its kinds
EXTENSIONS = {"fwpart": ["part"], "fwasm": ["assembly"], "fwdrw": ["model", "draft"], "fwprog": ["program"],
              "fwrender": ["mesh", "ai"], "fwmfg": ["mfg"], "fwcalc": ["calc"], "fwprint": ["print", "upload"],
              "fwread": ["read"]}


# ---------------------------------------------------------------------------------------------------- JSON hygiene
def clean_json(obj: Any) -> Any:
    """For export: workspace/project/user ids -> null, absolute paths -> file name."""
    if isinstance(obj, dict):
        return {k: (None if k in ID_KEYS and isinstance(v, str) else clean_json(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_json(v) for v in obj]
    if isinstance(obj, str) and _ABS.match(obj):
        return re.split(r"[\\/]", obj)[-1]
    return obj


def fill_ids(obj: Any, ids: dict[str, str | None], drop: frozenset[str] = frozenset()) -> Any:
    """For import: null id fields get the importer's ids; keys in ``drop`` become null."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in drop:
                out[k] = None
            elif k in ID_KEYS and v is None:
                out[k] = ids.get(ID_KEYS[k])
            else:
                out[k] = fill_ids(v, ids, drop)
        return out
    if isinstance(obj, list):
        return [fill_ids(v, ids, drop) for v in obj]
    return obj


def _dump(obj: Any) -> bytes:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False, default=str).encode()


def _clean_file(rel: str, data: bytes) -> bytes:
    if not rel.endswith(".json"):
        return data
    try:
        return _dump(clean_json(json.loads(data.decode("utf-8"))))
    except (UnicodeDecodeError, ValueError):
        raise NativeFormatError(f"{rel} could not be read.", 409) from None


def check_media(name: str, data: bytes) -> None:
    c.check_content(name, data)
    if name.lower().endswith(".mp4") and data[4:8] != b"ftyp":
        raise NativeFormatError(f"{name}: content does not match its type.")


# ---------------------------------------------------------------------------------------------------- part-linked
def folder_files(ws: Path, fk: FolderKind) -> dict[str, bytes]:
    root = ws / fk.folder
    out: dict[str, bytes] = {}
    if root.is_dir():
        for f in sorted(root.rglob("*")):
            if not f.is_file() or f.is_symlink():
                continue
            rel = f.relative_to(root).as_posix()
            if fk.allow.fullmatch(rel) and rel.split("/")[-1] not in fk.exclude:
                out[f"doc/{rel}"] = _clean_file(rel, f.read_bytes())
    if not out:
        raise NativeFormatError(f"There is nothing to save yet: this part has no {fk.label.split(' ', 2)[-1].lower()}"
                                " in this module.", 409)
    return out


def folder_manifest(fk: FolderKind, title: str, n: int) -> dict[str, Any]:
    return {"app_version": c.app_version(), "generator": "Formwright", "created_at": c.iso(), "title": title,
            "kind": fk.kind, "kernel": c.kernel_versions(), "module": {"code": fk.module, "label": fk.label, "files": n}}


def parse_folder(pkg: c.Package, *, strict: bool) -> dict[str, Any]:
    from aicad.native import bundles
    from aicad.native import part as fpart

    kind = pkg.manifest.get("kind")
    fk = FOLDER_KINDS.get(kind) if isinstance(kind, str) else None
    if fk is None or fk.ext != pkg.ext:
        raise NativeFormatError("This file's contents are not a kind Formwright knows.", 415)
    docs: dict[str, bytes] = {}
    for name, data in pkg.files.items():
        if name == "part.fwpart":
            continue
        rel = name[4:] if name.startswith("doc/") else ""
        if not rel or not fk.allow.fullmatch(rel) or rel.split("/")[-1] in fk.exclude:
            raise NativeFormatError(f"The file contains an entry Formwright does not accept ({name[:60]}).")
        check_media(name, data)
        if rel.endswith(".json") and not isinstance(pkg.json(name), (dict, list)):
            raise NativeFormatError(f"{name} is not valid.")
        docs[rel] = data
    if "part.fwpart" not in pkg.files:
        raise NativeFormatError("The file is incomplete: its part is missing.")
    sub = bundles._nested(pkg, "part.fwpart", "fwpart", 0)
    ps = fpart.validate(sub, strict=strict)
    return {"fk": fk, "docs": docs, "part": sub, "part_summary": ps,
            "summary": {"kind": fk.kind, "title": str(pkg.manifest.get("title") or fk.label)[:120], "module": fk.label,
                        "part": ps["title"], "files": len(docs), "created_at": str(pkg.manifest.get("created_at") or "")[:40]}}


def install_folder(ws: Path, fk: FolderKind, docs: dict[str, bytes], ids: dict[str, str | None], foreign: bool) -> list[str]:
    """Write the module folder into the (new) project. Returns notes for the person."""
    notes = []
    drop = frozenset({"signoff"}) if fk.kind == "calc" and foreign else frozenset()
    root = (ws / fk.folder).resolve()
    for rel, data in sorted(docs.items()):
        dest = (root / rel).resolve()
        if root not in dest.parents:
            raise NativeFormatError("The file contains an entry with an unsafe path.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith(".json"):
            data = _dump(fill_ids(json.loads(data.decode("utf-8")), ids, drop))
        dest.write_bytes(data)
    if drop:
        notes.append("Sign-offs made in another workspace are not carried over: sign the calculation sets again here.")
    return notes


# ---------------------------------------------------------------------------------------------------- 2D drafts
def draft_files(rec: dict[str, Any], revs: list[tuple[int, dict[str, Any]]]) -> tuple[dict[str, bytes], dict[str, Any]]:
    files = {"draft/draft.json": _dump(clean_json({"name": rec.get("name"), "rev": rec.get("rev"), "doc": rec["doc"],
                                                   "revs": rec.get("revs", [])}))}
    for n, doc in revs:
        files[f"draft/revs/{n}.json"] = _dump(clean_json(doc))
    sheet = (rec["doc"].get("sheet") or {}) if isinstance(rec.get("doc"), dict) else {}
    manifest = {"app_version": c.app_version(), "generator": "Formwright", "created_at": c.iso(),
                "title": str(rec.get("name") or "2D drawing"), "kind": "draft", "kernel": c.kernel_versions(),
                "drawing": {"kind": "draft", "sheet": sheet.get("size"), "revisions": len(revs)}}
    return files, manifest


def parse_draft(pkg: c.Package) -> dict[str, Any]:
    from aicad.drawing import DrawingInputError, draft

    revs: list[tuple[int, dict[str, Any]]] = []
    for name in pkg.files:
        m = re.fullmatch(r"draft/revs/([0-9]{1,5})\.json", name)
        if name != "draft/draft.json" and not m:
            raise NativeFormatError(f"The drawing contains an entry Formwright does not accept ({name[:60]}).")
        c.check_content(name, pkg.files[name])
    rec = pkg.json("draft/draft.json") if "draft/draft.json" in pkg.files else None
    if not isinstance(rec, dict) or not isinstance(rec.get("doc"), dict):
        raise NativeFormatError("The 2D drawing is damaged.")
    try:
        for name in sorted(pkg.files, key=lambda n: int(re.sub(r"\D", "", n) or 0)):
            m = re.fullmatch(r"draft/revs/([0-9]{1,5})\.json", name)
            if m:
                revs.append((int(m.group(1)), draft.normalize_doc(pkg.json(name))))
        latest = draft.normalize_doc(rec["doc"])
    except (DrawingInputError, TypeError, ValueError, KeyError, AttributeError) as e:
        raise NativeFormatError(f"The 2D drawing is damaged: {e}") from None
    if len(revs) > 200:
        revs = revs[-200:]
    name = " ".join(str(rec.get("name") or "Imported 2D drawing").split())[:80]
    return {"name": name, "doc": latest, "revs": revs,
            "summary": {"kind": "draft", "title": name, "revisions": len(revs),
                        "sheet": str((latest.get("sheet") or {}).get("size") or "")[:10], "model": False}}


# ---------------------------------------------------------------------------------------------------- Image-to-CAD reads
_READ_FILES = re.compile(r"read/(?:meta\.json|read\.json|review\.json|preview\.png|source\.(?:pdf|png|jpg|webp))")
READ_META_KEYS = ("name", "type", "file", "bytes", "status", "error", "method", "pages", "width", "height")


def read_files(d: Path, meta: dict[str, Any]) -> tuple[dict[str, bytes], dict[str, Any]]:
    files: dict[str, bytes] = {"read/meta.json": _dump(clean_json({k: meta.get(k) for k in READ_META_KEYS if k in meta}))}
    for n in ("read.json", "review.json"):
        if (d / n).is_file():
            files[f"read/{n}"] = _clean_file(n, (d / n).read_bytes())
    for n in ("preview.png", str(meta.get("file") or "")):
        if n and (d / n).is_file() and _READ_FILES.fullmatch(f"read/{n}"):
            files[f"read/{n}"] = (d / n).read_bytes()
    manifest = {"app_version": c.app_version(), "generator": "Formwright", "created_at": c.iso(),
                "title": str(meta.get("name") or "Drawing read"), "kind": "read", "kernel": c.kernel_versions()}
    return files, manifest


def parse_read(pkg: c.Package) -> dict[str, Any]:
    from aicad.image2cad.sniff import validate

    for name, data in pkg.files.items():
        if not _READ_FILES.fullmatch(name):
            raise NativeFormatError(f"The file contains an entry Formwright does not accept ({name[:60]}).")
        c.check_content(name, data)
    meta = pkg.json("read/meta.json") if "read/meta.json" in pkg.files else None
    src = next((n for n in pkg.files if n.startswith("read/source.")), None)
    if not isinstance(meta, dict) or src is None:
        raise NativeFormatError("The drawing read is incomplete.")
    try:
        kind = validate(pkg.files[src])
    except Exception as e:  # noqa: BLE001 - the module's own InputError, shown as is
        raise NativeFormatError(f"The drawing in the file was rejected: {e}") from None
    if src.rsplit(".", 1)[1] != {"pdf": "pdf", "png": "png", "jpg": "jpg", "webp": "webp"}.get(kind):
        raise NativeFormatError("The drawing in the file does not match its type.")
    for n in ("read/read.json", "read/review.json"):
        if n in pkg.files and not isinstance(pkg.json(n), dict):
            raise NativeFormatError(f"{n} is not valid.")
    name = str(meta.get("name") or "Imported drawing")[:120]
    return {"meta": meta, "source": src, "kind": kind, "files": pkg.files,
            "summary": {"kind": "read", "title": name, "values": len(((pkg.json("read/read.json") if "read/read.json" in pkg.files else {}) or {}).get("values") or [])}}


# ---------------------------------------------------------------------------------------------------- print uploads
_UPLOAD_FILES = re.compile(r"upload/(?:meta\.json|original\.(?:stl|obj|3mf))")


def upload_files(d: Path, meta: dict[str, Any]) -> tuple[dict[str, bytes], dict[str, Any]]:
    files = {"upload/meta.json": _dump(clean_json({k: meta.get(k) for k in ("name", "format", "units", "triangles",
                                                                             "repaired") if k in meta}))}
    orig = next((f for f in sorted(d.glob("original.*")) if f.suffix in (".stl", ".obj", ".3mf")), None)
    if orig is None:
        raise NativeFormatError("The uploaded mesh is missing.", 409)
    files[f"upload/{orig.name}"] = orig.read_bytes()
    manifest = {"app_version": c.app_version(), "generator": "Formwright", "created_at": c.iso(),
                "title": str(meta.get("name") or "Mesh"), "kind": "upload", "kernel": c.kernel_versions()}
    return files, manifest


def parse_upload(pkg: c.Package) -> dict[str, Any]:
    for name, data in pkg.files.items():
        if not _UPLOAD_FILES.fullmatch(name):
            raise NativeFormatError(f"The file contains an entry Formwright does not accept ({name[:60]}).")
        c.check_content(name, data)
    meta = pkg.json("upload/meta.json") if "upload/meta.json" in pkg.files else None
    orig = next((n for n in pkg.files if n.startswith("upload/original.")), None)
    if not isinstance(meta, dict) or orig is None:
        raise NativeFormatError("The print setup is incomplete.")
    name = re.sub(r"[^A-Za-z0-9 ._()-]", "_", str(meta.get("name") or "mesh"))[:120]
    return {"meta": meta, "orig": orig, "data": pkg.files[orig], "name": name,
            "summary": {"kind": "upload", "title": name, "units": str(meta.get("units") or "mm")[:4]}}
