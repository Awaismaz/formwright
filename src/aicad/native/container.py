"""The container shared by every Formwright native format: a zip with a fixed layout, written deterministically and
read as untrusted input.

Writing: entries in sorted order after ``mimetype`` (stored, first, like ODF) and ``manifest.json``; every timestamp
is 1980-01-01 00:00; Unix permissions 0644; the manifest lists the sha256 and size of every other entry and is signed
with the exporting workspace's HMAC key. The same model exported twice gives byte-identical files.

Reading (``read_package``): size cap on the upload; entry count cap; only regular files (no directories, symlinks,
encryption, exotic compression); entry names must be relative, ``/``-separated, without ``..``, empty, hidden or
reserved segments; every entry is decompressed in a streaming, counted way (a lying header cannot bypass the per-entry,
total and ratio caps); every entry must be listed in the manifest with a matching sha256 and size, and nothing may be
missing or extra; the manifest must name the expected format and a supported format version (older versions go
through the migration hook ``MIGRATIONS``).
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import re
import secrets
import stat
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aicad.native import NativeFormatError

FORMAT_VERSION = 1

#: extension -> (manifest "format", media type, human name)
FORMATS: dict[str, tuple[str, str, str]] = {
    "fwpart": ("formwright.part", "application/vnd.formwright.part+zip", "Formwright part"),
    "fwasm": ("formwright.assembly", "application/vnd.formwright.assembly+zip", "Formwright assembly"),
    "fwdrw": ("formwright.drawing", "application/vnd.formwright.drawing+zip", "Formwright drawing"),
    "fwprog": ("formwright.program", "application/vnd.formwright.program+zip", "Formwright program"),
    "fwrender": ("formwright.render", "application/vnd.formwright.render+zip", "Formwright render"),
    "fwmfg": ("formwright.manufacturing", "application/vnd.formwright.manufacturing+zip", "Formwright manufacturing report"),
    "fwcalc": ("formwright.calculation", "application/vnd.formwright.calculation+zip", "Formwright calculations"),
    "fwprint": ("formwright.print", "application/vnd.formwright.print+zip", "Formwright print setup"),
    "fwread": ("formwright.read", "application/vnd.formwright.read+zip", "Formwright drawing read"),
    "zip": ("formwright.projects", "application/zip", "Formwright projects archive"),
}
FORMAT_EXT = {v[0]: k for k, v in FORMATS.items()}
#: the manifest's ``kind`` when the writer does not set one (formats with several kinds always set it)
DEFAULT_KIND = {"fwpart": "part", "fwasm": "assembly", "fwdrw": "model", "fwprog": "program", "zip": "projects"}

# ---------------------------------------------------------------------------------------------------- limits
MAX_UPLOAD_BYTES = 200 * 1024 * 1024        # the file as uploaded
MAX_TOTAL_UNCOMPRESSED = 400 * 1024 * 1024  # sum over all entries, including nested packages
MAX_ENTRY_BYTES = 150 * 1024 * 1024         # one entry, decompressed
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 2000
MAX_RATIO = 120                             # decompressed / compressed, checked on entries above RATIO_FLOOR
RATIO_FLOOR = 1024 * 1024
MAX_NESTING = 2                             # .fwprog -> .fwasm -> .fwpart
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
_CHUNK = 1 << 16

_SEGMENT = re.compile(r"^[A-Za-z0-9_\-][A-Za-z0-9_.\-]{0,99}$")
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}
_STORED_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".fwpart", ".fwasm", ".pdf", ".3mf")


def app_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("aicad")
    except PackageNotFoundError:
        return "0"


def kernel_versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    out = {}
    for label, names in (("build123d", ("build123d",)), ("ocp", ("cadquery-ocp", "cadquery_ocp", "cadquery-ocp-novtk"))):
        for n in names:
            try:
                out[label] = version(n)
                break
            except PackageNotFoundError:
                continue
        out.setdefault(label, "unknown")
    return out


def iso(ts: datetime | None = None) -> str:
    return (ts or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------------------------------- signing
def _secret(data_dir: Path) -> bytes:
    """Server secret for package signatures: FW_FILE_SECRET, else a random key kept in the data folder."""
    env = os.environ.get("FW_FILE_SECRET", "").strip()
    if env:
        return env.encode()
    f = data_dir / "secrets" / "native_files.key"
    try:
        return bytes.fromhex(f.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        f.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        f.write_text(key.hex(), encoding="utf-8")
        return key


def org_tag(data_dir: Path, org_id: str) -> str:
    """Opaque, keyed id of a workspace (never the raw id): recognises "from your workspace" on import."""
    return hmac.new(_secret(data_dir), b"fw-org:" + org_id.encode(), hashlib.sha256).hexdigest()[:24]


def opaque(data_dir: Path, kind: str, value: str) -> str:
    return hmac.new(_secret(data_dir), f"fw-{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:24]


def _canonical(manifest: dict[str, Any]) -> bytes:
    body = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _org_key(data_dir: Path, org_id: str) -> bytes:
    return hmac.new(_secret(data_dir), b"fw-sign:" + org_id.encode(), hashlib.sha256).digest()


def sign(manifest: dict[str, Any], data_dir: Path, org_id: str) -> None:
    mac = hmac.new(_org_key(data_dir, org_id), _canonical(manifest), hashlib.sha256).hexdigest()
    manifest["signature"] = {"alg": "HMAC-SHA256", "org": org_tag(data_dir, org_id), "value": mac}


def trust_for(manifest: dict[str, Any], data_dir: Path, org_id: str) -> tuple[str, str | None]:
    """("workspace", None) for an untampered file exported by this workspace; ("foreign", note) otherwise."""
    sig = manifest.get("signature")
    mine = org_tag(data_dir, org_id)
    claims_mine = isinstance(sig, dict) and sig.get("org") == mine
    if claims_mine and isinstance(sig.get("value"), str):
        want = hmac.new(_org_key(data_dir, org_id), _canonical(manifest), hashlib.sha256).hexdigest()
        if hmac.compare_digest(want, sig["value"]):
            return "workspace", None
        return "foreign", ("This file says it was exported from your workspace, but its signature does not match: it "
                           "was changed after export. It is treated like a file from another workspace.")
    return "foreign", None


# ---------------------------------------------------------------------------------------------------- writing
def write_package(ext: str, files: dict[str, bytes], manifest: dict[str, Any], data_dir: Path, org_id: str) -> bytes:
    """Deterministic zip: mimetype, manifest.json, then entries sorted by name; fixed timestamps and permissions."""
    fmt, mime, _ = FORMATS[ext]
    manifest = {"kind": DEFAULT_KIND.get(ext, ext), **manifest}
    for name in files:
        check_name(name)
    manifest = {**manifest, "format": fmt, "format_version": FORMAT_VERSION,
                "entries": {n: {"sha256": sha256(files[n]), "size": len(files[n])} for n in sorted(files)}}
    sign(manifest, data_dir, org_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        def put(name: str, data: bytes, stored: bool) -> None:
            zi = zipfile.ZipInfo(name, ZIP_EPOCH)
            zi.create_system = 3
            zi.external_attr = (stat.S_IFREG | 0o644) << 16
            zi.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
            z.writestr(zi, data, compresslevel=None if stored else 6)

        put("mimetype", mime.encode(), True)
        put("manifest.json", json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False).encode(), False)
        for name in sorted(files):
            put(name, files[name], name.lower().endswith(_STORED_EXT))
    return buf.getvalue()


def write_plain_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in sorted(files):
            zi = zipfile.ZipInfo(name, ZIP_EPOCH)
            zi.create_system = 3
            zi.external_attr = (stat.S_IFREG | 0o644) << 16
            zi.compress_type = zipfile.ZIP_STORED if name.lower().endswith(_STORED_EXT) else zipfile.ZIP_DEFLATED
            z.writestr(zi, files[name])
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------------- reading
def check_name(name: str) -> None:
    if not name or len(name) > 240 or "\\" in name or "\x00" in name or name.startswith("/") or ":" in name:
        raise NativeFormatError(f"The file contains an entry with an unsafe path ({name[:60]!r}).")
    parts = name.split("/")
    if len(parts) > 6:
        raise NativeFormatError(f"The file contains an entry nested too deeply ({name[:60]!r}).")
    for seg in parts:
        if seg in ("", ".", "..") or not _SEGMENT.fullmatch(seg) or seg.split(".")[0].upper() in _RESERVED:
            raise NativeFormatError(f"The file contains an entry with an unsafe path ({name[:60]!r}).")


@dataclass
class Package:
    ext: str
    manifest: dict[str, Any]
    files: dict[str, bytes]
    size: int
    uncompressed: int
    migrated_from: int | None = None
    warnings: list[str] = field(default_factory=list)
    budget: Any = None  # shared decompression budget for embedded packages

    def json(self, name: str) -> Any:
        try:
            return json.loads(self.files[name].decode("utf-8"))
        except KeyError:
            raise NativeFormatError(f"The file is incomplete: {name} is missing.") from None
        except (UnicodeDecodeError, ValueError):
            raise NativeFormatError(f"The file is damaged: {name} is not valid.") from None


class _Budget:
    def __init__(self) -> None:
        self.total = 0

    def take(self, n: int) -> None:
        self.total += n
        if self.total > MAX_TOTAL_UNCOMPRESSED:
            raise NativeFormatError("The file expands to more data than Formwright accepts (possible zip bomb).", 413)


def sniff_ext(data: bytes) -> str | None:
    """Format from the leading ``mimetype`` entry (a native file renamed by a browser or mail client still opens)."""
    if not data.startswith(b"PK\x03\x04") or len(data) < 30:
        return None
    n, x = int.from_bytes(data[26:28], "little"), int.from_bytes(data[28:30], "little")
    if data[30:30 + n] != b"mimetype":
        return None
    size = int.from_bytes(data[18:22], "little")
    mime = data[30 + n + x:30 + n + x + min(size, 80)].decode("ascii", "replace")
    return next((ext for ext, (_, m, _) in FORMATS.items() if m == mime and ext != "zip"), None)


def read_package(data: bytes, expect_ext: str | None = None, *, depth: int = 0, budget: _Budget | None = None) -> Package:
    """Open an untrusted package. Raises NativeFormatError with a plain reason for anything not allowed."""
    budget = budget or _Budget()
    if depth > MAX_NESTING:
        raise NativeFormatError("The file nests packages too deeply.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise NativeFormatError("Formwright files up to 200 MB can be imported.", 413)
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError):
        raise NativeFormatError("That file is not a Formwright file (it is not a valid package).", 415) from None
    with z:
        infos = z.infolist()
        if len(infos) > MAX_ENTRIES:
            raise NativeFormatError("The file has too many entries.")
        names = [i.filename for i in infos]
        if len(set(names)) != len(names):
            raise NativeFormatError("The file contains duplicate entries.")
        raw: dict[str, bytes] = {}
        for info in infos:
            name = info.filename
            mode = (info.external_attr >> 16) & 0o170000
            if name.endswith("/") or info.is_dir():
                raise NativeFormatError("The file contains folders that Formwright does not use.")
            if mode and mode != stat.S_IFREG:
                raise NativeFormatError(f"The file contains a link or special entry ({name[:60]!r}), which is not allowed.")
            if info.flag_bits & 0x1:
                raise NativeFormatError("Encrypted files cannot be imported.")
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise NativeFormatError("The file uses a compression method Formwright does not accept.")
            if name not in ("mimetype", "manifest.json"):
                check_name(name)
            cap = MAX_MANIFEST_BYTES if name in ("mimetype", "manifest.json") else MAX_ENTRY_BYTES
            if info.file_size > cap:
                raise NativeFormatError(f"An entry of the file is too large ({name[:60]!r}).", 413)
            if info.file_size > RATIO_FLOOR and info.file_size > MAX_RATIO * max(info.compress_size, 1):
                raise NativeFormatError("The file is compressed suspiciously well (possible zip bomb).", 413)
            raw[name] = _read_entry(z, info, cap, budget)
    if "manifest.json" not in raw:
        raise NativeFormatError("That file is not a Formwright file (manifest missing).", 415)
    try:
        manifest = json.loads(raw.pop("manifest.json").decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise NativeFormatError("The file is damaged: its manifest is not valid.") from None
    raw.pop("mimetype", None)
    if not isinstance(manifest, dict):
        raise NativeFormatError("The file is damaged: its manifest is not valid.")
    ext = FORMAT_EXT.get(str(manifest.get("format")))
    if ext is None:
        raise NativeFormatError("That file is not a Formwright file (unknown format).", 415)
    if expect_ext and ext != expect_ext:
        raise NativeFormatError(f"Expected a {FORMATS[expect_ext][2]} but this is a {FORMATS[ext][2]}.", 415)
    pkg = Package(ext=ext, manifest=manifest, files=raw, size=len(data), uncompressed=budget.total, budget=budget)
    _verify_entries(pkg)
    migrate(pkg)
    return pkg


def _read_entry(z: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int, budget: _Budget) -> bytes:
    out = bytearray()
    try:
        with z.open(info) as f:
            while True:
                chunk = f.read(_CHUNK)
                if not chunk:
                    break
                out += chunk
                budget.take(len(chunk))
                if len(out) > cap:
                    raise NativeFormatError(f"An entry of the file is too large ({info.filename[:60]!r}).", 413)
                if len(out) > RATIO_FLOOR and len(out) > MAX_RATIO * max(info.compress_size, 1):
                    raise NativeFormatError("The file is compressed suspiciously well (possible zip bomb).", 413)
    except (zipfile.BadZipFile, OSError, EOFError, ValueError) as e:
        if isinstance(e, NativeFormatError):
            raise
        raise NativeFormatError("The file is damaged (an entry could not be read).") from None
    return bytes(out)


def _verify_entries(pkg: Package) -> None:
    listed = pkg.manifest.get("entries")
    if not isinstance(listed, dict):
        raise NativeFormatError("The file is damaged: its manifest has no list of contents.")
    extra = sorted(set(pkg.files) - set(listed))
    missing = sorted(set(listed) - set(pkg.files))
    if extra:
        raise NativeFormatError(f"The file was changed after export: {extra[0]} is not in its manifest.")
    if missing:
        raise NativeFormatError(f"The file is incomplete: {missing[0]} is missing.")
    for name, meta in listed.items():
        data = pkg.files[name]
        if not isinstance(meta, dict) or meta.get("size") != len(data) or not hmac.compare_digest(
                str(meta.get("sha256", "")), sha256(data)):
            raise NativeFormatError(f"The file was changed after export: {name} does not match its checksum.")


# ---------------------------------------------------------------------------------------------------- versions
#: (format, from_version) -> function upgrading the package in place to from_version + 1. Applied in a chain until
#: the package reaches FORMAT_VERSION. Entry checksums are verified *before* migrating (against the original manifest).
MIGRATIONS: dict[tuple[str, int], Callable[[Package], None]] = {}


def migration(fmt: str, from_version: int) -> Callable[[Callable[[Package], None]], Callable[[Package], None]]:
    def deco(fn: Callable[[Package], None]) -> Callable[[Package], None]:
        MIGRATIONS[(fmt, from_version)] = fn
        return fn
    return deco


def migrate(pkg: Package) -> None:
    v = pkg.manifest.get("format_version")
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise NativeFormatError("The file is damaged: its format version is missing.")
    if v > FORMAT_VERSION:
        raise NativeFormatError("This file was made by a newer version of Formwright. Update Formwright to open it.")
    fmt = pkg.manifest["format"]
    start = v
    while v < FORMAT_VERSION:
        fn = MIGRATIONS.get((fmt, v))
        if fn is None:
            raise NativeFormatError(f"This file uses an old format version ({v}) that can no longer be opened.")
        fn(pkg)
        v += 1
        pkg.manifest["format_version"] = v
    if start != v:
        pkg.migrated_from = start
        pkg.warnings.append(f"Upgraded from format version {start}.")


@migration("formwright.part", 0)
def _part_v0(pkg: Package) -> None:
    """Draft format 0 (pre-release) kept the fingerprint and STEP hash at the top level of the manifest."""
    m = pkg.manifest
    geo = m.setdefault("geometry", {})
    for k in ("fingerprint", "step_sha256"):
        if k in m and k not in geo:
            geo[k] = m.pop(k)


# ---------------------------------------------------------------------------------------------------- content checks
_MAGIC = {".png": (b"\x89PNG",), ".jpg": (b"\xff\xd8",), ".jpeg": (b"\xff\xd8",), ".gif": (b"GIF8",),
          ".webp": (b"RIFF",), ".pdf": (b"%PDF",)}


def check_content(name: str, data: bytes) -> None:
    """Entry content matches its type: images by magic bytes, STEP by its header, JSON parses, text is UTF-8."""
    low = name.lower()
    ext = "." + low.rsplit(".", 1)[-1] if "." in low else ""
    if ext in _MAGIC and not data.startswith(_MAGIC[ext]):
        raise NativeFormatError(f"{name}: content does not match its type.")
    if ext in (".step", ".stp") and not data.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"ISO-10303-21"):
        raise NativeFormatError(f"{name}: not a STEP file.")
    if ext in (".json", ".py", ".jsonl", ".txt", ".md", ".csv", ".svg", ".dxf"):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise NativeFormatError(f"{name}: not valid text.") from None
        if ext == ".json":
            try:
                json.loads(text)
            except ValueError:
                raise NativeFormatError(f"{name}: not valid JSON.") from None
