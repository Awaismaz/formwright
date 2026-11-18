"""Installable web app (UX-022): the server serves the manifest and the service worker with the right types and
caching, the CSP allows them, and the committed manifest and icons meet the install criteria."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from aicad.platform import config

WEB = Path(__file__).resolve().parents[1] / "web"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Formwright</title>", encoding="utf-8")
    (dist / "sw.js").write_text("self.addEventListener('fetch', () => {});", encoding="utf-8")
    (dist / "manifest.webmanifest").write_text((WEB / "public" / "manifest.webmanifest").read_text("utf-8"),
                                               encoding="utf-8")
    (dist / "offline.html").write_text("<!doctype html><title>Offline</title>", encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "icons").mkdir()
    (dist / "icons" / "icon-192.png").write_bytes((WEB / "public" / "icons" / "icon-192.png").read_bytes())

    from aicad.platform import app as app_mod

    monkeypatch.setattr(app_mod, "WEB_DIST", dist)
    monkeypatch.setenv("FW_ADMIN_PASSWORD", "correct horse 42")
    config.override_settings(config.Settings(
        env="development", data_dir=tmp_path / "data", database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
        app_url="http://testserver", superadmin_emails=("boss@example.com",), stripe_secret_key=""))
    with TestClient(app_mod.create_app()) as c:
        yield c


def test_service_worker_is_served_from_root_and_never_long_cached(client: TestClient) -> None:
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["service-worker-allowed"] == "/"


def test_manifest_type_and_csp(client: TestClient) -> None:
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")
    assert r.headers["cache-control"] == "no-cache"
    assert r.json()["name"] == "Formwright"
    csp = r.headers["content-security-policy"]
    assert "manifest-src 'self'" in csp and "worker-src 'self'" in csp


def test_offline_page_assets_and_spa_caching(client: TestClient) -> None:
    assert client.get("/offline.html").headers["cache-control"] == "no-cache"
    a = client.get("/assets/index-abc123.js")
    assert a.status_code == 200 and a.headers["content-type"].startswith("text/javascript")
    assert "immutable" in a.headers["cache-control"]
    assert client.get("/assets/missing.js").headers.get("cache-control", "") != "public, max-age=31536000, immutable"
    assert client.get("/icons/icon-192.png").headers["content-type"] == "image/png"
    spa = client.get("/app/projects")  # client-side route: the SPA entry, always revalidated
    assert spa.status_code == 200 and spa.headers["cache-control"] == "no-cache"
    assert client.get("/api/nope").status_code == 404  # the API is never answered by the SPA fallback


def test_manifest_meets_install_criteria() -> None:
    m = json.loads((WEB / "public" / "manifest.webmanifest").read_text("utf-8"))
    assert m["name"] == "Formwright" and m["short_name"]
    assert m["display"] == "standalone" and m["start_url"] == "/app" and m["scope"] == "/"
    assert m["theme_color"] == "#23272E" and m["background_color"]
    sizes = {(i["sizes"], i.get("purpose", "any")) for i in m["icons"]}
    for need in [("192x192", "any"), ("512x512", "any"), ("192x192", "maskable"), ("512x512", "maskable")]:
        assert need in sizes, need
    for i in m["icons"]:
        p = WEB / "public" / i["src"].lstrip("/")
        w, h = (int(x) for x in i["sizes"].split("x"))
        with Image.open(p) as im:
            assert im.size == (w, h) and im.format == "PNG"
    with Image.open(WEB / "public" / "icons" / "apple-touch-icon.png") as im:
        assert im.size == (180, 180) and im.mode == "RGB"  # opaque: iOS fills transparency with black
    html = (WEB / "index.html").read_text("utf-8")
    for tag in ('rel="manifest"', 'name="theme-color"', 'apple-mobile-web-app-capable', 'apple-touch-icon',
                "viewport-fit=cover"):
        assert tag in html, tag
