"""aicad CLI (M0 spike).

  aicad build SPEC [--out DIR]          build once, print checks
  aicad live  SPEC [--out DIR] [--port] build, serve viewer, rebuild on every spec save
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from aicad.pipeline import publish_status, run


def _report(s: dict[str, Any]) -> None:
    if "error" in s:
        print(f"  ERROR: {s['error']}")
        return
    for c in s["checks"]:
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {c['id']} {c['name']}")
    print(f"  overall: {'PASS' if s['ok'] else 'FAIL'}   total {s['timings_s']['total_s']:.2f}s")


def _build(spec: Path, out: Path) -> dict[str, Any]:
    print(f"build {spec} -> {out}")
    try:
        s = run(spec, out)
    except Exception as exc:  # noqa: BLE001 - kernel failures must not kill the live loop
        s = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "checks": []}
        publish_status(out, s)
    _report(s)
    return s


def _studio(a: argparse.Namespace) -> int:
    import re

    import uvicorn

    from aicad.agent.session import AgentSession
    from aicad.studio.app import create_app, use_subscription_auth

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", a.project):
        print("project name: letters, digits, - and _ only")
        return 2
    if a.api_key:
        print("Auth: ANTHROPIC_API_KEY (API usage is billed)")
    else:
        removed = use_subscription_auth()
        print("Auth: local Claude Code login (development only; no API billing)"
              + (f" - ignoring {', '.join(removed)}" if removed else ""))
    session = AgentSession(Path("workspace") / a.project, model=a.model)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"AI CAD Studio: {url}  workspace: {session.workspace}")
    if not a.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(session), host="127.0.0.1", port=a.port, log_level="warning")
    return 0


def _app(a: argparse.Namespace) -> int:
    import os

    import uvicorn

    from aicad.platform.app import create_app
    from aicad.platform.config import get_settings
    from aicad.studio.app import use_subscription_auth

    os.environ.setdefault("FW_APP_URL", f"http://{a.host}:{a.port}")
    s = get_settings()
    if a.api_key:
        print("Design agent auth: ANTHROPIC_API_KEY (API usage is billed)")
    elif s.production:
        print("Production requires --api-key (subscription login is development-only).")
        return 2
    else:
        removed = use_subscription_auth()
        print("Design agent auth: local Claude Code login (development only)"
              + (f" - ignoring {', '.join(removed)}" if removed else ""))
    print(f"Formwright: {s.app_url}   env={s.env}   payments={s.stripe_mode}   god_mode={s.god_mode_enabled}")
    if not a.no_browser:
        threading.Timer(2.0, webbrowser.open, args=(s.app_url,)).start()
    uvicorn.run(create_app(), host=a.host, port=a.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["bench"]:  # EVAL-003 design-agent benchmark (its own options: aicad bench --help)
        from aicad.eval.benchmark import main as bench

        return bench(argv[1:])
    if argv[:1] == ["repeat"]:  # EVAL-008 same-prompt repeatability (aicad repeat --help)
        from aicad.eval.repeat import main as repeat

        return repeat(argv[1:])
    if argv[:1] == ["latency"]:  # agent-latency benchmark (aicad latency --help)
        from aicad.eval.latency import main as latency

        return latency(argv[1:])
    p = argparse.ArgumentParser(prog="aicad")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("build", "live"):
        sp = sub.add_parser(name)
        sp.add_argument("spec", type=Path)
        sp.add_argument("--out", type=Path, default=None)
        if name == "live":
            sp.add_argument("--port", type=int, default=8765)
            sp.add_argument("--no-browser", action="store_true")
    st = sub.add_parser("studio", help="chat-driven design agent + live viewer")
    st.add_argument("--project", default="default", help="workspace/<project> folder")
    st.add_argument("--port", type=int, default=8765)
    st.add_argument("--model", default=None, help="model alias/id (default: account default)")
    st.add_argument("--api-key", action="store_true",
                    help="use ANTHROPIC_API_KEY billing instead of the local Claude Code login")
    st.add_argument("--no-browser", action="store_true")
    ap = sub.add_parser("app", help="Formwright web application (API + UI)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--api-key", action="store_true",
                    help="design agent bills ANTHROPIC_API_KEY instead of the local Claude Code login")
    ap.add_argument("--no-browser", action="store_true")
    a = p.parse_args(argv)
    if a.cmd == "studio":
        return _studio(a)
    if a.cmd == "app":
        return _app(a)
    out = a.out or Path("out") / a.spec.stem

    if a.cmd == "build":
        return 0 if _build(a.spec, out).get("ok") else 1

    from aicad.viewer.server import serve

    _build(a.spec, out)
    threading.Thread(target=serve, args=(out, a.port), daemon=True).start()
    if not a.no_browser:
        webbrowser.open(f"http://127.0.0.1:{a.port}/")
    print(f"watching {a.spec} — save it to rebuild; Ctrl+C to stop")
    last = a.spec.stat().st_mtime
    try:
        while True:
            time.sleep(0.5)
            m = a.spec.stat().st_mtime
            if m != last:
                last = m
                time.sleep(0.2)  # let editor finish writing
                _build(a.spec, out)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
