"""Minimal local live viewer server (stdlib only). Binds to 127.0.0.1.

Serves the static viewer page and a fixed allow-list of artifacts from one output dir.
No arbitrary paths are served (path traversal is impossible by construction).
"""

from __future__ import annotations

from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC = Path(__file__).parent / "static"
ALLOWED = {
    "model.glb": "model/gltf-binary",
    "status.json": "application/json",
    "part.step": "application/step",
    "part.stl": "model/stl",
}


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args: object, out_dir: Path, **kw: object) -> None:
        self.out_dir = out_dir
        super().__init__(*args, **kw)  # type: ignore[arg-type]

    def log_message(self, fmt: str, *args: object) -> None:  # quiet polling noise
        pass

    def _send(self, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send((STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        if path.startswith("/files/"):
            name = path.removeprefix("/files/")
            if name in ALLOWED:
                f = self.out_dir / name
                if f.is_file():
                    extra = {}
                    if name in ("part.step", "part.stl"):
                        extra["Content-Disposition"] = f'attachment; filename="{name}"'
                    self._send(f.read_bytes(), ALLOWED[name], extra)
                    return
        self.send_error(404)


def serve(out_dir: Path, port: int = 8765) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, out_dir=out_dir))
    print(f"Live viewer: http://127.0.0.1:{port}/  (serving {out_dir})")
    httpd.serve_forever()
