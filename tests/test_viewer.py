from __future__ import annotations

import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from aicad.viewer.server import Handler


@pytest.fixture()
def server(tmp_path: Path):  # type: ignore[no-untyped-def]
    (tmp_path / "status.json").write_text('{"ok": true}')
    (tmp_path / "secret.txt").write_text("nope")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, out_dir=tmp_path))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def test_serves_index_and_allowed_files(server: str) -> None:
    code, body = _get(server + "/")
    assert code == 200 and b"<title>AI CAD Live Viewer</title>" in body
    assert _get(server + "/files/status.json") == (200, b'{"ok": true}')


@pytest.mark.parametrize("path", [
    "/files/secret.txt", "/files/../pyproject.toml", "/files/%2e%2e/status.json",
    "/files/..\\secret.txt", "/etc/passwd", "/files/",
])
def test_rejects_non_allowlisted_paths(server: str, path: str) -> None:
    assert _get(server + path)[0] == 404
