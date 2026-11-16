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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aicad")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("build", "live"):
        sp = sub.add_parser(name)
        sp.add_argument("spec", type=Path)
        sp.add_argument("--out", type=Path, default=None)
        if name == "live":
            sp.add_argument("--port", type=int, default=8765)
            sp.add_argument("--no-browser", action="store_true")
    a = p.parse_args(argv)
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
