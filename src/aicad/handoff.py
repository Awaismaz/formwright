"""Shop handoff pack: one zip with everything the shop needs for the current revision, and a manifest that proves it.

Contents (only what exists, each checked against the current build):
  model/      STEP, STL, 3MF of the verified model
  drawing/    sheet PDF/DXF/SVG from Drawing Studio (flagged if generated from an older build)
  dfm/        manufacturability report PDF (flagged if the analysis is older than the build)
  CHANGE_NOTICE.txt  what changed in this revision and why
  README.txt         plain summary: part, revision, material, mass, size, checks, contents, gaps
  manifest.json      SHA-256 and size of every file, the source build and fingerprint, stale flags

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

from aicad import change_notice, materials

ZIP_TIME = (2000, 1, 1, 0, 0, 0)  # fixed entry timestamps; file identity is proven by the manifest's SHA-256
MODEL_FILES = (("part.step", "STEP (AP214)"), ("part.stl", "STL (0.01 mm chordal deviation)"), ("part.3mf", "3MF (mm)"))


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


def plan(ws: Path) -> dict[str, Any]:
    """What a pack would contain right now, with stale/missing flags (no files written)."""
    st = _json(ws / "out" / "status.json")
    build = st.get("build_id")
    items: list[dict[str, Any]] = []
    for f, label in MODEL_FILES:
        if (ws / "out" / f).is_file():
            items.append({"kind": "model", "file": f, "label": label, "ok": True})
    drw = _json(ws / "drawings" / "drawing.json")
    if drw:
        stale = str(drw.get("build_id")) != str(build)
        items.append({"kind": "drawing", "label": f"Drawing (model rev {drw.get('model_rev') or '—'})", "ok": not stale,
                      "stale": stale, "check": (drw.get("check") or {}).get("passed")})
    else:
        items.append({"kind": "drawing", "label": "Drawing", "missing": True, "where": "drawings"})
    dfm = _json(ws / "manufacturing" / "analysis.json")
    if dfm:
        stale = (dfm.get("build") or {}).get("build_id") != build
        items.append({"kind": "dfm", "label": "Manufacturability report", "ok": not stale, "stale": stale})
    else:
        items.append({"kind": "dfm", "label": "Manufacturability report", "missing": True, "where": "manufacturing"})
    rev = _revision(ws)
    if rev is not None:
        items.append({"kind": "notice", "label": f"Change notice (rev {rev})", "ok": True})
    return {"ready": bool(st.get("ok")), "build_id": build, "revision": rev, "items": items}


def build_pack(ws: Path, project_name: str, user: str | None = None, include_stale: bool = False) -> tuple[bytes, dict[str, Any]]:
    """The zip bytes and its manifest. Stale drawing/DFM outputs are left out unless include_stale."""
    st = _json(ws / "out" / "status.json")
    if not st.get("ok"):
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
    if drw and (include_stale or "Drawing" not in " ".join(stale)):
        for f in ("sheet.pdf", "sheet.dxf", "sheet.svg"):
            p = ws / "drawings" / f
            if p.is_file():
                files[f"drawing/{name}_drawing.{f.split('.')[-1]}"] = p.read_bytes()
    dfm = _json(ws / "manufacturing" / "analysis.json")
    if dfm and (include_stale or "Manufacturability report" not in stale):
        from aicad.manufacturing import report

        topo = _json(ws / "out" / "topo.json") or None
        files[f"dfm/{name}_dfm.pdf"] = report.build_pdf(dfm, project_name, topo)
    rev = pl["revision"]
    if rev is not None:
        n = change_notice.notice(ws / "revisions", rev)
        n["project"] = {"name": project_name}
        files["CHANGE_NOTICE.txt"] = notice_text(n).encode("utf-8")
    fp = st.get("fingerprint") or {}
    m = materials.get(materials.guess(st.get("material")))
    mass = f"{float(fp['volume']) * float(m['density_g_cm3']) / 1000:,.1f} g ({m['name']}, typical density)" if m and fp.get("volume") else "—"
    gating = [c["id"] for c in st.get("checks") or [] if c.get("gating") and not c.get("passed")]
    readme = "\n".join([
        f"FORMWRIGHT SHOP HANDOFF: {project_name}",
        f"Revision {rev if rev is not None else '—'} · build {str(st.get('build_id', ''))[-8:]} · {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}"
        + (f" · prepared by {user}" if user else ""),
        "",
        f"Part:      {st.get('part') or project_name}",
        f"Material:  {st.get('material') or '—'}",
        f"Envelope:  {' × '.join(f'{v:g}' for v in fp.get('bbox', []))} mm",
        f"Volume:    {fp.get('volume', 0):,.1f} mm³",
        f"Mass:      {mass}",
        f"Checks:    {'geometry checks passed' if not gating else 'FAILING: ' + ', '.join(gating)}",
        "",
        "Contents:",
        *[f"  {k}" for k in sorted(files)],
        *(["", "Left out (older than this revision; regenerate first): " + ", ".join(stale)] if stale and not include_stale else []),
        *(["", "Included although older than this revision: " + ", ".join(stale)] if stale and include_stale else []),
        *(["", "Not produced yet: " + ", ".join(missing)] if missing else []),
        "",
        "Checks prove geometric consistency of the model only. This pack is not a manufacturing approval;",
        "engineering sign-off and the released drawing remain the responsibility of the design owner.",
        "Verify each file's SHA-256 against manifest.json.",
    ]) + "\n"
    files["README.txt"] = readme.encode("utf-8")
    manifest = {
        "project": project_name, "revision": rev, "build_id": st.get("build_id"), "fingerprint": fp,
        "material": st.get("material"), "checks_passed": not gating, "stale_excluded": stale if not include_stale else [],
        "stale_included": stale if include_stale else [], "missing": missing,
        "files": {k: {"sha256": hashlib.sha256(v).hexdigest(), "bytes": len(v)} for k, v in sorted(files.items())},
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k in sorted(files):
            info = zipfile.ZipInfo(f"{name}_rev{rev if rev is not None else 0}/{k}", ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, files[k])
    return buf.getvalue(), manifest
