""".fwpart: one part with its full parametric model.

Layout (all paths relative, see docs/FORMATS.md):
  mimetype, manifest.json
  model.py                     the model script, including the app-managed manual-feature block
  <helper>.py                  helper modules imported by model.py (top level only)
  imports/<name>.step|.json    reference files of imported parts (exact STEP blank + recognised features)
  refs/<name>.png|jpg|...      reference images (optional)
  out/part.step                exact geometry of the exported build (preview, verification, read-only fallback)
  out/status.json              subset of the build status: parameters, feature tree, checks, mass, fingerprint
  thumbnail.png                one clean view of the part
  design/brief.json            project name and description (the design brief)
  revisions/<n>/model.py|status.json|cause.json   revision history (optional)
  chat/chat.jsonl              the design conversation, user and assistant text only (optional, off by default)
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aicad.native import NativeFormatError
from aicad.native import container as c
from aicad.native.gate import check_script, helper_names

STATUS_KEYS = ("ok", "part", "material", "params", "param_meta", "editable_params", "features", "manual_features",
               "manual_errors", "checks", "mass", "fingerprint", "bbox_minmax", "step_sha256", "imported", "env",
               "build_id", "error", "expected")
_ENTRY = re.compile(
    r"^(model\.py|[A-Za-z_][A-Za-z0-9_]{0,40}\.py|imports/[A-Za-z0-9_\-][A-Za-z0-9_.\-]{0,99}\.(?:step|stp|json)|"
    r"refs/[A-Za-z0-9_\-][A-Za-z0-9_.\-]{0,99}\.(?:png|jpg|jpeg|webp|gif)|out/part\.step|out/status\.json|"
    r"thumbnail\.png|design/brief\.json|chat/chat\.jsonl|revisions/[0-9]{1,5}/(?:model\.py|status\.json|cause\.json))$")
_REV_MODEL = re.compile(r"^revisions/([0-9]{1,5})/model\.py$")
CHAT_TYPES = ("user", "text")
ORIGINAL_STEP = ".fw/native/original_part.step"    # exact geometry from the file, kept for the read-only fallback
ORIGINAL_MODEL = ".fw/native/original_model.py.txt"  # the file's script, kept (never run) when it could not rebuild
MAX_CHAT_TEXT = 20000


def _read_json(f: Path) -> Any:
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def status_subset(st: dict[str, Any]) -> dict[str, Any]:
    return {k: st[k] for k in STATUS_KEYS if k in st}


def build_time(st: dict[str, Any]) -> str:
    try:
        return c.iso(datetime.fromtimestamp(int(st["build_id"]) / 1e9, UTC))
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return c.iso(datetime(2000, 1, 1, tzinfo=UTC))


def collect(ws: Path, *, name: str, description: str, history: bool = True, refs: bool = True,
            chat: bool = False) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Entries and manifest body (unsigned) of a .fwpart for the project at ``ws``."""
    model = ws / "model.py"
    st = _read_json(ws / "out" / "status.json")
    step = ws / "out" / "part.step"
    if not model.is_file() or not isinstance(st, dict) or not st.get("fingerprint"):
        raise NativeFormatError("This project has no built model yet. Build it in the Design Studio first.", 409)
    if st.get("exports_pending") or not step.is_file():
        raise NativeFormatError("The part is still being finalised. Try again in a moment.", 409)
    files: dict[str, bytes] = {"model.py": model.read_bytes(), "out/part.step": step.read_bytes(),
                               "out/status.json": json.dumps(status_subset(st), indent=1, sort_keys=True,
                                                             default=str).encode()}
    for f in sorted(ws.glob("*.py")):
        if f.name != "model.py" and not f.name.startswith("_fw_") and _ENTRY.fullmatch(f.name):
            files[f.name] = f.read_bytes()
    imp = ws / "imports"
    if imp.is_dir():
        for f in sorted(imp.iterdir()):
            rel = f"imports/{f.name}"
            if f.is_file() and _ENTRY.fullmatch(rel):
                files[rel] = f.read_bytes()
    if refs and (ws / "refs").is_dir():
        for f in sorted((ws / "refs").iterdir()):
            rel = f"refs/{f.name}"
            if f.is_file() and _ENTRY.fullmatch(rel):
                files[rel] = f.read_bytes()
    for thumb in (ws / "out" / "thumb.png", ws / "out" / "views.png"):
        if thumb.is_file():
            files["thumbnail.png"] = thumb.read_bytes()
            break
    files["design/brief.json"] = json.dumps({"name": name, "description": description}, indent=1,
                                            ensure_ascii=False).encode()
    n_rev = 0
    current_rev = None
    if history and (ws / "revisions").is_dir():
        for d in sorted((d for d in (ws / "revisions").iterdir() if d.is_dir() and d.name.isdigit()),
                        key=lambda d: int(d.name)):
            if not (d / "model.py").is_file() or len(d.name) > 5:
                continue
            n_rev += 1
            files[f"revisions/{d.name}/model.py"] = (d / "model.py").read_bytes()
            rst = _read_json(d / "status.json")
            files[f"revisions/{d.name}/status.json"] = json.dumps(status_subset(rst if isinstance(rst, dict) else {}),
                                                                  indent=1, sort_keys=True, default=str).encode()
            cause = _read_json(d / "cause.json")
            cause = cause if isinstance(cause, dict) else {}
            files[f"revisions/{d.name}/cause.json"] = json.dumps(
                {k: cause.get(k) for k in ("cause", "kind", "parent")}, indent=1, ensure_ascii=False).encode()
        try:
            current_rev = int((ws / ".fw" / "current_rev").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current_rev = None
    n_chat = 0
    if chat and (ws / ".fw" / "chat.jsonl").is_file():
        lines = []
        for line in (ws / ".fw" / "chat.jsonl").read_text(encoding="utf-8").splitlines():
            ev = _chat_event(line)
            if ev:
                lines.append(json.dumps(ev, ensure_ascii=False))
        if lines:
            n_chat = len(lines)
            files["chat/chat.jsonl"] = ("\n".join(lines) + "\n").encode()
    src = files["model.py"].decode("utf-8", "replace")
    manifest = {
        "app_version": c.app_version(), "generator": "Formwright", "created_at": build_time(st),
        "title": name, "description": description[:2000],
        "part": {"name": st.get("part") or name, "material": st.get("material"), "units": "mm"},
        "kernel": st.get("env") or c.kernel_versions(),
        "geometry": {"fingerprint": st.get("fingerprint"), "step_sha256": c.sha256(files["out/part.step"]),
                     "bbox_minmax": st.get("bbox_minmax"), "mass": st.get("mass"), "checks_ok": bool(st.get("ok"))},
        "contents": {"history": history, "revisions": n_rev, "current_revision": current_rev, "refs": refs,
                     "chat": n_chat > 0, "imported": bool(st.get("imported")),
                     "manual_features": "# --- Formwright manual features" in src,
                     "helpers": sorted(n for n in files if "/" not in n and n.endswith(".py") and n != "model.py"),
                     "parameters": len(st.get("editable_params") or {}), "features": len(st.get("features") or [])},
    }
    return files, manifest


def _chat_event(line: str) -> dict[str, Any] | None:
    """Only what the person typed and the assistant's visible text: never tools, costs or internals."""
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    if not isinstance(ev, dict) or ev.get("type") not in CHAT_TYPES or not isinstance(ev.get("text"), str):
        return None
    out: dict[str, Any] = {"type": ev["type"], "text": ev["text"][:MAX_CHAT_TEXT]}
    if isinstance(ev.get("t"), (int, float)):
        out["t"] = ev["t"]
    return out


def export_part(ws: Path, *, name: str, description: str, project_id: str, org_id: str, data_dir: Path,
                history: bool = True, refs: bool = True, chat: bool = False) -> bytes:
    files, manifest = collect(ws, name=name, description=description, history=history, refs=refs, chat=chat)
    manifest["source"] = {"org": c.org_tag(data_dir, org_id), "project": c.opaque(data_dir, "project", project_id)}
    return c.write_package("fwpart", files, manifest, data_dir, org_id)


# ---------------------------------------------------------------------------------------------------- import
def validate(pkg: c.Package, *, strict: bool) -> dict[str, Any]:
    """Everything that must hold before a single file of the part is written or run. Returns a summary."""
    if pkg.ext != "fwpart":
        raise NativeFormatError("Expected a Formwright part (.fwpart).", 415)
    m = pkg.manifest
    for name in pkg.files:
        if not _ENTRY.fullmatch(name):
            raise NativeFormatError(f"The part contains an entry Formwright does not accept ({name[:60]}).")
        c.check_content(name, pkg.files[name])
    for req in ("model.py", "out/part.step", "out/status.json"):
        if req not in pkg.files:
            raise NativeFormatError(f"The part is incomplete: {req} is missing.")
    geo = m.get("geometry")
    if not isinstance(geo, dict) or not isinstance(geo.get("fingerprint"), dict):
        raise NativeFormatError("The part's manifest has no geometry fingerprint.")
    if geo.get("step_sha256") and geo["step_sha256"] != c.sha256(pkg.files["out/part.step"]):
        raise NativeFormatError("The part was changed after export: its geometry does not match the manifest.")
    helpers = helper_names(list(pkg.files))
    for name, data in sorted(pkg.files.items()):
        if name.endswith(".py"):
            check_script(data.decode("utf-8"), _label(name), strict=strict, helpers=helpers)
    st = pkg.json("out/status.json")
    if not isinstance(st, dict):
        raise NativeFormatError("The part is damaged: out/status.json is not valid.")
    for name in pkg.files:
        if name.endswith(".json") and name.startswith("revisions/") and not isinstance(pkg.json(name), dict):
            raise NativeFormatError(f"The part is damaged: {name} is not valid.")
    part = m.get("part") if isinstance(m.get("part"), dict) else {}
    return {"kind": "part", "title": _text(m.get("title"), 120) or _text(part.get("name"), 120) or "Imported part",
            "description": _text(m.get("description"), 2000), "material": _text(part.get("material"), 120),
            "fingerprint": geo["fingerprint"], "created_at": _text(m.get("created_at"), 40),
            "app_version": _text(m.get("app_version"), 40), "kernel": m.get("kernel") if isinstance(m.get("kernel"), dict) else {},
            "parameters": len(st.get("editable_params") or {}), "features": len(st.get("features") or []),
            "revisions": sum(1 for n in pkg.files if _REV_MODEL.match(n)), "chat": "chat/chat.jsonl" in pkg.files,
            "refs": sum(1 for n in pkg.files if n.startswith("refs/")), "imported": bool(st.get("imported"))}


def _label(name: str) -> str:
    mrev = _REV_MODEL.match(name)
    if mrev:
        return f"Revision {mrev.group(1)} of the model"
    return "The model" if name == "model.py" else f"Helper module {name}"


def _text(v: Any, n: int) -> str:
    return v.strip()[:n] if isinstance(v, str) else ""


def install(pkg: c.Package, ws: Path) -> None:
    """Write a validated part into an empty workspace. The model is rebuilt by the caller (build worker)."""
    ws.mkdir(parents=True, exist_ok=True)
    root = ws.resolve()
    for name, data in sorted(pkg.files.items()):
        if name in ("out/status.json", "thumbnail.png", "design/brief.json") or name.startswith("chat/"):
            continue
        rel = ORIGINAL_STEP if name == "out/part.step" else name
        dest = (root / rel).resolve()
        if root not in dest.parents:
            raise NativeFormatError("The file contains an entry with an unsafe path.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    if "chat/chat.jsonl" in pkg.files:
        lines = [json.dumps(ev, ensure_ascii=False) for ev in
                 (_chat_event(x) for x in pkg.files["chat/chat.jsonl"].decode("utf-8").splitlines()) if ev]
        if lines:
            (ws / ".fw").mkdir(parents=True, exist_ok=True)
            (ws / ".fw" / "chat.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    cur = (pkg.manifest.get("contents") or {}).get("current_revision")
    if isinstance(cur, int) and (ws / "revisions" / str(cur)).is_dir():
        (ws / ".fw").mkdir(parents=True, exist_ok=True)
        (ws / ".fw" / "current_rev").write_text(str(cur), encoding="utf-8")


def fallback_source(name: str, material: str | None) -> str:
    """Read-only model of the exact exported geometry, used when the script cannot be rebuilt here."""
    return ("# The part's own model could not be rebuilt here; this is its exact exported geometry (read-only).\n"
            "# The file's original script is kept in the project (never run) for the design agent to repair.\n"
            "from aicad import fw\n\n"
            f"NAME = {name!r}\nMATERIAL = {(material or 'unspecified')!r}\nIMPORTED = True\n"
            "REFERENCE_STEP = 'imports/original_part.step'\nPARAMS = {}\n\n"
            "result = fw.imported_blank(REFERENCE_STEP)\n")


# ---------------------------------------------------------------------------------------------------- verification
PLACE_TOL_MM = 1e-3  # bbox corners and centre of mass: far below any modelling tolerance, far above kernel round-off


def placement(st: dict[str, Any] | None) -> dict[str, Any]:
    """Where the part sits (IO-008): bounding-box corners and centre of mass, from a build status or a manifest's
    ``geometry`` block. Sizes, volume and topology counts alone cannot see a moved or mirrored rebuild."""
    st = st or {}
    mass = st.get("mass") if isinstance(st.get("mass"), dict) else {}
    out: dict[str, Any] = {}
    if isinstance(st.get("bbox_minmax"), list) and len(st["bbox_minmax"]) == 6:
        out["bbox_minmax"] = st["bbox_minmax"]
    if isinstance(mass.get("com_mm"), list) and len(mass["com_mm"]) == 3:
        out["com_mm"] = mass["com_mm"]
    return out


def compare(expected: dict[str, Any], got: dict[str, Any] | None, *, expected_place: dict[str, Any] | None = None,
            got_place: dict[str, Any] | None = None) -> list[str]:
    """Plain differences between two geometry fingerprints ([] = identical within kernel round-off). With
    ``placement()`` of both sides, a rebuild that is moved or mirrored (same size and counts) is reported too."""
    if not got:
        return ["the model did not rebuild"]
    diffs = []
    for k, label in (("solids", "solids"), ("faces", "faces"), ("edges", "edges"), ("vertices", "vertices")):
        if k in expected and expected.get(k) != got.get(k):
            diffs.append(f"{label}: {expected.get(k)} in the file, {got.get(k)} rebuilt")
    try:
        ev, gv = float(expected["volume"]), float(got["volume"])
        if abs(ev - gv) > max(1e-6, 1e-6 * abs(ev)):
            diffs.append(f"volume: {ev:.3f} mm³ in the file, {gv:.3f} mm³ rebuilt")
    except (KeyError, TypeError, ValueError):
        diffs.append("volume: not comparable")
    eb, gb = expected.get("bbox") or [], got.get("bbox") or []
    if len(eb) != 3 or len(gb) != 3 or any(abs(float(a) - float(b)) > 1e-4 for a, b in zip(eb, gb, strict=True)):
        diffs.append(f"size: {_box(eb)} in the file, {_box(gb)} rebuilt")
    ep, gp = expected_place or {}, got_place or {}
    for k, label in (("bbox_minmax", "bounding box corners"), ("com_mm", "centre of mass")):
        a, b = ep.get(k), gp.get(k)
        if a is None or b is None:
            continue
        try:
            moved = len(a) != len(b) or any(abs(float(x) - float(y)) > PLACE_TOL_MM for x, y in zip(a, b, strict=True))
        except (TypeError, ValueError):
            moved = True
        if moved:
            diffs.append(f"position: {label} differ ({_pt(a)} in the file, {_pt(b)} rebuilt)")
    return diffs


def _pt(v: Any) -> str:
    try:
        return "(" + ", ".join(f"{float(x):.3f}" for x in v) + ") mm"
    except (TypeError, ValueError):
        return "unknown"


def _box(b: list[Any]) -> str:
    try:
        return " × ".join(f"{float(x):.3f}" for x in b) + " mm"
    except (TypeError, ValueError):
        return "unknown"
