"""Documents around embedded parts: .fwasm (assembly), .fwdrw (drawing), .fwprog (Design Office program), and the
bulk "all projects" archive. Pure functions: the platform router supplies the data and applies the result.

Embedded packages are stored once per content hash (``parts/<sha256[:16]>.fwpart``); the outer manifest's checksums
cover their bytes, and each embedded package is validated again on import (caps shared with the outer file).
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any

from aicad.native import NativeFormatError
from aicad.native import container as c
from aicad.native import part as fpart

_PART_ENTRY = re.compile(r"^parts/[a-f0-9]{16}\.fwpart$")
_ASM_ENTRY = re.compile(r"^assemblies/[a-f0-9]{16}\.fwasm$")
MAX_DOC_BYTES = 8 * 1024 * 1024
MAX_INSTANCES = 1000
MAX_MATES = 3000


def _dump(obj: Any) -> bytes:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False, default=str).encode()


def embed(files: dict[str, bytes], data: bytes, folder: str = "parts", ext: str = "fwpart") -> str:
    """Store an embedded package once per content hash; returns its entry name."""
    name = f"{folder}/{c.sha256(data)[:16]}.{ext}"
    files[name] = data
    return name


def _base_manifest(title: str, description: str = "") -> dict[str, Any]:
    return {"app_version": c.app_version(), "generator": "Formwright", "created_at": c.iso(), "title": title,
            "description": description[:2000], "kernel": c.kernel_versions()}


def _doc(pkg: c.Package, name: str) -> Any:
    if name not in pkg.files:
        raise NativeFormatError(f"The file is incomplete: {name} is missing.")
    if len(pkg.files[name]) > MAX_DOC_BYTES:
        raise NativeFormatError(f"{name} is too large.", 413)
    return pkg.json(name)


def _nested(pkg: c.Package, name: str, ext: str, depth: int) -> c.Package:
    try:
        return c.read_package(pkg.files[name], ext, depth=depth + 1, budget=pkg.budget)
    except NativeFormatError as e:
        raise NativeFormatError(f"An embedded file ({name}) was rejected: {e}", e.status) from None


def _str(v: Any, n: int = 200) -> str:
    return v[:n] if isinstance(v, str) else ""


# ---------------------------------------------------------------------------------------------------- assembly
def assembly_files(doc: dict[str, Any], part_refs: dict[str, dict[str, Any]], part_bytes: dict[str, bytes],
                   bom: dict[str, Any] | None, thumb: bytes | None) -> tuple[dict[str, bytes], dict[str, Any]]:
    """``part_refs``: part cache key -> {"kind": "project"} | {"kind": "toolbox", code, params, version}, with the
    project parts' .fwpart bytes in ``part_bytes`` (same key)."""
    files: dict[str, bytes] = {}
    parts: dict[str, dict[str, Any]] = {}
    key_to_ref: dict[str, str] = {}
    for key, info in part_refs.items():
        if info["kind"] == "project":
            entry = embed(files, part_bytes[key])
            ref = entry.split("/")[1].split(".")[0]
            parts.setdefault(ref, {"kind": "project", "file": entry, "name": info.get("name"),
                                   "fingerprint": info.get("fingerprint"), "step_sha256": info.get("step_sha256")})
        else:
            ref = "t_" + c.sha256(json.dumps([info["code"], info["params"], info["version"]], sort_keys=True)
                                  .encode())[:14]
            parts.setdefault(ref, {"kind": "toolbox", "code": info["code"], "params": info["params"],
                                   "version": info["version"], "name": info.get("name")})
        key_to_ref[key] = ref
    instances = [{"id": i["id"], "name": i.get("name"), "part": key_to_ref[i["part"]], "T": i["T"],
                  "fixed": bool(i.get("fixed")), "visible": i.get("visible", True) is not False, "group": i.get("group")}
                 for i in doc["instances"]]
    mates = [{"id": m["id"], "type": m["type"], "value": m.get("value", 0.0), "flip": bool(m.get("flip")),
              "suppressed": bool(m.get("suppressed")), "group": m.get("group"),
              "a": {k: m["a"].get(k) for k in ("inst", "kind", "id")},
              "b": {k: m["b"].get(k) for k in ("inst", "kind", "id")}} for m in doc["mates"]]
    files["assembly.json"] = _dump({"schema": 1, "name": doc.get("name"), "instances": instances, "mates": mates,
                                    "groups": doc.get("groups") or [], "seq": doc.get("seq", 0)})
    files["parts.json"] = _dump(parts)
    if bom is not None:
        files["bom.json"] = _dump(bom)
    if thumb:
        files["thumbnail.png"] = thumb
    manifest = _base_manifest(str(doc.get("name") or "Assembly"))
    manifest["assembly"] = {"instances": len(instances), "mates": len(mates), "parts": len(parts),
                            "project_parts": sum(1 for p in parts.values() if p["kind"] == "project"),
                            "toolbox_parts": sum(1 for p in parts.values() if p["kind"] == "toolbox"), "units": "mm"}
    return files, manifest


def _finite12(t: Any) -> bool:
    return isinstance(t, list) and len(t) == 12 and all(
        isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in t)


def parse_assembly(pkg: c.Package, *, strict: bool, depth: int = 0) -> dict[str, Any]:
    """Validate an assembly (and every embedded part) completely. Returns {doc, parts, summary}."""
    if pkg.ext != "fwasm":
        raise NativeFormatError("Expected a Formwright assembly (.fwasm).", 415)
    allowed = {"assembly.json", "parts.json", "bom.json", "thumbnail.png"}
    for name, data in pkg.files.items():
        if name not in allowed and not _PART_ENTRY.fullmatch(name):
            raise NativeFormatError(f"The assembly contains an entry Formwright does not accept ({name[:60]}).")
        c.check_content(name, data)
    doc, parts = _doc(pkg, "assembly.json"), _doc(pkg, "parts.json")
    if not isinstance(doc, dict) or not isinstance(parts, dict):
        raise NativeFormatError("The assembly is damaged.")
    inst = doc.get("instances")
    mates = doc.get("mates")
    if not isinstance(inst, list) or not isinstance(mates, list) or len(inst) > MAX_INSTANCES or len(mates) > MAX_MATES:
        raise NativeFormatError("The assembly is damaged or too large.")
    out_parts: dict[str, dict[str, Any]] = {}
    for ref, p in parts.items():
        if not isinstance(p, dict) or not re.fullmatch(r"[A-Za-z0-9_]{1,40}", str(ref)):
            raise NativeFormatError("The assembly's part list is damaged.")
        if p.get("kind") == "project":
            entry = p.get("file")
            if not isinstance(entry, str) or not _PART_ENTRY.fullmatch(entry) or entry not in pkg.files:
                raise NativeFormatError("The assembly's part list refers to a missing part.")
            sub = _nested(pkg, entry, "fwpart", depth)
            out_parts[ref] = {"kind": "project", "pkg": sub, "summary": fpart.validate(sub, strict=strict)}
        elif p.get("kind") == "toolbox":
            if not isinstance(p.get("code"), str) or not isinstance(p.get("params"), dict):
                raise NativeFormatError("The assembly's part list is damaged.")
            out_parts[ref] = {"kind": "toolbox", "code": p["code"][:60], "params": p["params"],
                              "version": p.get("version"), "name": _str(p.get("name"), 120)}
        else:
            raise NativeFormatError("The assembly's part list is damaged.")
    ids = set()
    for i in inst:
        if not isinstance(i, dict) or not re.fullmatch(r"i[0-9]{1,6}", str(i.get("id"))) or i.get("part") not in out_parts \
                or not _finite12(i.get("T")) or i["id"] in ids:
            raise NativeFormatError("The assembly's instances are damaged.")
        ids.add(i["id"])
    for m in mates:
        if not isinstance(m, dict) or not re.fullmatch(r"m[0-9]{1,6}", str(m.get("id"))) \
                or not isinstance(m.get("a"), dict) or not isinstance(m.get("b"), dict) \
                or m["a"].get("inst") not in ids or m["b"].get("inst") not in ids:
            raise NativeFormatError("The assembly's mates are damaged.")
        v = m.get("value", 0.0)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
            raise NativeFormatError("The assembly's mates are damaged.")
    groups = doc.get("groups") if isinstance(doc.get("groups"), list) else []
    seq = doc.get("seq") if isinstance(doc.get("seq"), int) else 0
    name = _str(doc.get("name"), 120).strip() or _str(pkg.manifest.get("title"), 120) or "Imported assembly"
    summary = {"kind": "assembly", "title": name, "instances": len(inst), "mates": len(mates),
               "parts": [{"ref": r, "kind": p["kind"], "name": p["summary"]["title"] if p["kind"] == "project"
                          else (p["name"] or p["code"])} for r, p in out_parts.items()],
               "created_at": _str(pkg.manifest.get("created_at"), 40),
               "app_version": _str(pkg.manifest.get("app_version"), 40)}
    return {"doc": {"name": name, "instances": inst, "mates": mates, "groups": groups, "seq": seq},
            "parts": out_parts, "summary": summary}


# ---------------------------------------------------------------------------------------------------- drawing
def drawing_files(record: dict[str, Any], edits: dict[str, Any], part_bytes: bytes | None, sheets: dict[str, bytes],
                  title: str) -> tuple[dict[str, bytes], dict[str, Any]]:
    files: dict[str, bytes] = {}
    keep = ("options", "sheet", "sheet_rev", "model_rev", "check", "title", "views")
    files["drawing/drawing.json"] = _dump({k: record.get(k) for k in keep if k in record})
    files["drawing/edits.json"] = _dump(edits)
    for name, data in sheets.items():
        files[f"drawing/{name}"] = data
    if part_bytes is not None:
        files["part.fwpart"] = part_bytes
    manifest = _base_manifest(title)
    sheet = record.get("sheet") or {}
    manifest["drawing"] = {"kind": "model", "sheet": sheet.get("size"),
                           "scale": sheet.get("scale"), "sheets": sorted(sheets)}
    return files, manifest


def parse_drawing(pkg: c.Package, *, strict: bool) -> dict[str, Any]:
    if pkg.ext != "fwdrw":
        raise NativeFormatError("Expected a Formwright drawing (.fwdrw).", 415)
    if pkg.manifest.get("kind") == "draft":
        from aicad.native.modules import parse_draft

        return {"kind": "draft", **parse_draft(pkg)}
    allowed = re.compile(r"^(drawing/(drawing|edits)\.json|drawing/sheet[A-Za-z_]*\.(pdf|svg|dxf)|part\.fwpart)$")
    for name, data in pkg.files.items():
        if not allowed.fullmatch(name):
            raise NativeFormatError(f"The drawing contains an entry Formwright does not accept ({name[:60]}).")
        c.check_content(name, data)
    if "part.fwpart" not in pkg.files:
        raise NativeFormatError("The drawing is incomplete: its part is missing.")
    record, edits = _doc(pkg, "drawing/drawing.json"), _doc(pkg, "drawing/edits.json")
    if not isinstance(record, dict) or not isinstance(edits, dict):
        raise NativeFormatError("The drawing is damaged.")
    sub = _nested(pkg, "part.fwpart", "fwpart", 0)
    ps = fpart.validate(sub, strict=strict)
    opts = record.get("options") if isinstance(record.get("options"), dict) else {}
    sheet = record.get("sheet") if isinstance(record.get("sheet"), dict) else {}
    return {"kind": "model", "part": sub, "part_summary": ps, "options": opts, "edits": edits,
            "summary": {"kind": "drawing", "title": _str(pkg.manifest.get("title"), 120) or ps["title"], "model": True,
                        "part": ps["title"], "sheet": _str(sheet.get("size"), 10), "scale": _str(sheet.get("scale"), 20),
                        "created_at": _str(pkg.manifest.get("created_at"), 40)}}


# ---------------------------------------------------------------------------------------------------- program
_DROP = {"org_id", "created_by", "user_id"}


def scrub(obj: Any) -> Any:
    """Program data without workspace or user ids (names stay: they are part of the record)."""
    if isinstance(obj, dict):
        out = {k: scrub(v) for k, v in obj.items() if k not in _DROP}
        if out.get("kind") == "user" and "id" in out:
            out["id"] = None
        return out
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def program_files(doc: dict[str, Any], events: list[dict[str, Any]], part_bytes: dict[str, bytes],
                  asm_bytes: dict[str, bytes]) -> tuple[dict[str, bytes], dict[str, Any]]:
    """``part_bytes``: project id -> .fwpart; ``asm_bytes``: assembly id -> .fwasm (keyed by the program's links)."""
    files: dict[str, bytes] = {}
    pref = {pid: embed(files, b) for pid, b in sorted(part_bytes.items())}
    aref = {aid: embed(files, b, "assemblies", "fwasm") for aid, b in sorted(asm_bytes.items())}
    d = scrub({k: v for k, v in doc.items() if k not in ("id", "rev", "planning")})
    for t in d.get("tickets", []):
        t["project"] = pref.get(t.pop("project_id", None) or "")
        t["assembly"] = aref.get(t.pop("assembly_id", None) or "")
        t["run"] = None
    files["program/program.json"] = _dump(d)
    by_type = Counter(str(e.get("type")) for e in events)
    files["program/events_summary.json"] = _dump({
        "count": len(events), "by_type": dict(sorted(by_type.items())),
        "first": events[0].get("t") if events else None, "last": events[-1].get("t") if events else None,
        "recent": [{"t": e.get("t"), "type": e.get("type"), "text": _str(e.get("text"), 500)} for e in events[-40:]]})
    manifest = _base_manifest(str(doc.get("name") or "Program"), str(doc.get("brief") or "")[:2000])
    manifest["program"] = {"tickets": len(doc.get("tickets") or []), "parts": len(pref), "assemblies": len(aref),
                           "status": doc.get("status")}
    return files, manifest


def parse_program(pkg: c.Package, *, strict: bool) -> dict[str, Any]:
    if pkg.ext != "fwprog":
        raise NativeFormatError("Expected a Formwright program (.fwprog).", 415)
    for name, data in pkg.files.items():
        if name not in ("program/program.json", "program/events_summary.json") and not _PART_ENTRY.fullmatch(name) \
                and not _ASM_ENTRY.fullmatch(name):
            raise NativeFormatError(f"The program contains an entry Formwright does not accept ({name[:60]}).")
        c.check_content(name, data)
    doc = _doc(pkg, "program/program.json")
    if not isinstance(doc, dict) or not isinstance(doc.get("tickets", []), list) or not isinstance(doc.get("name"), str):
        raise NativeFormatError("The program is damaged.")
    parts = {}
    asms = {}
    for name in sorted(pkg.files):
        if _PART_ENTRY.fullmatch(name):
            sub = _nested(pkg, name, "fwpart", 0)
            parts[name] = {"pkg": sub, "summary": fpart.validate(sub, strict=strict)}
        elif _ASM_ENTRY.fullmatch(name):
            sub = _nested(pkg, name, "fwasm", 0)
            asms[name] = parse_assembly(sub, strict=strict, depth=1)
    for t in doc.get("tickets", []):
        if not isinstance(t, dict) or (t.get("project") and t["project"] not in parts) \
                or (t.get("assembly") and t["assembly"] not in asms):
            raise NativeFormatError("The program's tickets are damaged.")
    summary = {"kind": "program", "title": doc["name"][:120], "tickets": len(doc.get("tickets", [])),
               "parts": [p["summary"]["title"] for p in parts.values()],
               "assemblies": [a["summary"]["title"] for a in asms.values()],
               "created_at": _str(pkg.manifest.get("created_at"), 40)}
    return {"doc": doc, "parts": parts, "assemblies": asms, "summary": summary}


# ---------------------------------------------------------------------------------------------------- projects archive
def parse_projects(pkg: c.Package, *, strict: bool) -> dict[str, Any]:
    if pkg.ext != "zip":
        raise NativeFormatError("Expected a Formwright projects archive.", 415)
    parts = {}
    for name in sorted(pkg.files):
        if not re.fullmatch(r"parts/[A-Za-z0-9_\-][A-Za-z0-9_.\-]{0,99}\.fwpart", name):
            raise NativeFormatError(f"The archive contains an entry Formwright does not accept ({name[:60]}).")
        sub = _nested(pkg, name, "fwpart", 0)
        parts[name] = {"pkg": sub, "summary": fpart.validate(sub, strict=strict)}
    return {"parts": parts, "summary": {"kind": "projects", "title": f"{len(parts)} projects",
                                        "parts": [p["summary"]["title"] for p in parts.values()]}}
