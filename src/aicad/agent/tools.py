"""CAD tools exposed to the agent as an in-process MCP server."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from aicad.agent import worker
from aicad.agent.deferred import DeferredChecks, failure_note

BUILD_TIMEOUT_S = 180
RENDER_TIMEOUT_S = 60


def summarize(status: dict[str, Any], notes: list[dict[str, Any]] | None = None) -> str:
    """The check report the agent reads. ``notes``: deferred checks of the previous build that failed (PS-01)."""
    prev = failure_note(notes or [])
    if status.get("error"):
        s = f"BUILD FAILED: {status['error']}"
        if status.get("traceback"):
            s += f"\n\nTraceback (tail):\n{status['traceback']}"
        return s + (f"\n\n{prev}" if prev else "")
    lines = [f"Overall gating checks: {'PASS' if status['ok'] else 'FAIL'}"]
    for c in status["checks"]:
        d = {k: v for k, v in c["detail"].items() if k not in ("original", "reimported")}
        if d.get("pending"):
            lines.append(f"[PENDING] {c['id']} {c['name']}")
            continue
        tag = "PASS" if c["passed"] else ("INFO" if not c["gating"] else "FAIL")
        lines.append(f"[{tag}] {c['id']} {c['name']}: {json.dumps(d, default=str)}")
    if status.get("pending_checks"):
        lines.append("PENDING: the STEP/STL exports, the STEP round trip and the repeatability rebuild run in the "
                     "background while you continue. A failure is reported at your next build, and the turn is not "
                     "reported as verified until they pass.")
    if prev:
        lines.append(prev)
    for m in status.get("manual_errors") or []:
        lines.append(f"[REBUILD ERROR] user's manual feature '{m['name']}' was skipped: {m['error']}. "
                     "Keep the manual block unchanged unless the user asks; tell the user it needs repair.")
    fp = status.get("fingerprint", {})
    lines.append(f"Measured: bbox {fp.get('bbox')} mm, volume {fp.get('volume')} mm3, "
                 f"solids {fp.get('solids')}, faces {fp.get('faces')}")
    lines.append(f"Build time {status.get('timings_s', {}).get('total_s')} s. "
                 "Live viewer updated. Attached image: ISO / FRONT(-Y) / TOP(+Z) / RIGHT(+X), "
                 "parallel projection, CAD coordinates.")
    return "\n".join(lines)


BUILD_TOOL_DESCRIPTION = (
    "Execute a build123d model script in the workspace (default model.py), run deterministic geometry "
    "checks against the script's EXPECTED dict, update the user's live 3D viewer, and return the check "
    "report plus a 4-view render image for visual review. STEP/STL export, the STEP round trip and the "
    "repeatability rebuild finish in the background (reported at the next build and at the end of the turn). "
    "Write and build in one call: `source` = the whole script (a new design), or `edits` = exact replacements "
    "applied to the current script (a change). Without either, the script file is built as it is.")
MAX_SOURCE_CHARS = 200_000
BUILD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "script": {"type": "string", "description": "script file in the workspace (default model.py)"},
        "source": {"type": "string", "description": "the complete script: written to the file, then built"},
        "edits": {"type": "array", "description": "exact text replacements applied in order to the current script, "
                                                  "then built; each old text must occur exactly once",
                  "items": {"type": "object", "properties": {"old": {"type": "string"}, "new": {"type": "string"}},
                            "required": ["old", "new"]}},
    },
}


def apply_source(script: Path, args: dict[str, Any]) -> str | None:
    """agent-latency: write-and-build in one tool call. ``source`` replaces the script, ``edits`` patches it (each
    ``old`` must occur exactly once, applied in order, all or nothing). Returns an error for the agent, or None."""
    src, edits = args.get("source"), args.get("edits")
    if src is None and not edits:
        return None
    if src is not None and edits:
        return "give either source or edits, not both"
    if src is not None:
        if not isinstance(src, str) or not src.strip():
            return "source is empty"
        text = src
    else:
        if not script.is_file():
            return f"{script.name} doesn't exist yet: send the whole script as source"
        if not isinstance(edits, list):
            return "edits must be a list of {old, new}"
        text = script.read_text(encoding="utf-8")
        for i, e in enumerate(edits, 1):
            old, new = (e or {}).get("old"), (e or {}).get("new")
            if not isinstance(old, str) or not isinstance(new, str) or not old:
                return f"edit {i}: needs non-empty old and a new text"
            n = text.count(old)
            if n != 1:
                return (f"edit {i}: the old text occurs {n} times in the current script; give a longer, unique "
                        "excerpt (nothing was changed)")
            text = text.replace(old, new, 1)
    if len(text) > MAX_SOURCE_CHARS:
        return "script too long"
    script.write_text(text, encoding="utf-8")
    return None


def build_handler(workspace: Path, out_dir: Path, worker_key: str | None = None,
                  deferred: DeferredChecks | None = None) -> Any:
    """The build_model tool's implementation (tests call it directly)."""
    key = worker_key or str(workspace)
    bg = deferred or DeferredChecks(key, out_dir)

    async def build_model(args: dict[str, Any]) -> dict[str, Any]:
        name = (args.get("script") or "model.py").strip()
        script = (workspace / name).resolve()
        if workspace.resolve() not in script.parents or script.suffix != ".py":
            return {"content": [{"type": "text", "text": "script must be a .py file inside the workspace"}],
                    "is_error": True}
        err = apply_source(script, args)
        if err:
            return {"content": [{"type": "text", "text": f"NOT BUILT: {err}"}], "is_error": True}
        if not script.is_file():
            return {"content": [{"type": "text", "text": f"{name} not found in workspace"}], "is_error": True}
        out_dir.mkdir(parents=True, exist_ok=True)
        notes = await bg.before_build()  # the previous build's background work is superseded
        # PS-01: build + CHK-02..05 + topology now; exports, CHK-07 and CHK-08 run in the background (bg.start)
        res = await worker.build(key, script, out_dir, determinism=True, fast=True, timeout=BUILD_TIMEOUT_S)
        status_p = out_dir / "status.json"
        if res.get("rc") == -1 or not status_p.is_file():
            return {"content": [{"type": "text", "text": f"BUILD FAILED: {res.get('error')}"}], "is_error": True}
        status = json.loads(status_p.read_text(encoding="utf-8"))
        content: list[dict[str, Any]] = [{"type": "text", "text": summarize(status, notes)}]
        stl = out_dir / ("preview.stl" if status.get("exports_pending") else "part.stl")
        if not status.get("error") and stl.is_file():
            png = out_dir / "views.png"
            r = await worker.render(key, stl, png, str(status.get("part", "")), timeout=RENDER_TIMEOUT_S)
            if r.get("ok") and png.is_file():
                content.append({"type": "image", "mimeType": "image/png",
                                "data": base64.b64encode(png.read_bytes()).decode("ascii")})
            else:
                content.append({"type": "text", "text": f"(render failed: {r.get('error')})"})
        if not status.get("error") and status.get("exports_pending"):
            bg.start(status.get("build_id"))  # after the render, so the render never queues behind the exports
        return {"content": content, "is_error": bool(status.get("error"))}

    return build_model


def make_cad_server(workspace: Path, out_dir: Path, worker_key: str | None = None,
                    deferred: DeferredChecks | None = None) -> Any:
    handler = build_handler(workspace, out_dir, worker_key, deferred)
    build_model = tool("build_model", BUILD_TOOL_DESCRIPTION, BUILD_SCHEMA)(handler)
    return create_sdk_mcp_server(name="cad", version="0.1.0", tools=[build_model])
