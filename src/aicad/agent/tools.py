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
    "repeatability rebuild finish in the background (reported at the next build and at the end of the turn).")


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
    build_model = tool("build_model", BUILD_TOOL_DESCRIPTION, {"script": str})(handler)
    return create_sdk_mcp_server(name="cad", version="0.1.0", tools=[build_model])
