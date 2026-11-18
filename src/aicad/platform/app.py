"""Formwright application factory: API + single-page app, one origin."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from aicad.platform.catalog import seed_catalog
from aicad.platform.config import ROOT, get_settings
from aicad.platform.db import init_engine, session_factory, utcnow
from aicad.platform.models import User
from aicad.platform.routers import (
    admin,
    auth,
    billing,
    collab,
    god,
    handoff,
    journey,
    library,
    office,
    projects,
    search,
    studio,
    team,
    variants,
)
from aicad.platform.security import hash_password

WEB_DIST = ROOT / "web" / "dist"
CSRF_HEADER = "x-fw-csrf"
CSRF_EXEMPT = {"/api/billing/webhook"}
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self'; font-src 'self' data:; worker-src 'self' blob:; manifest-src 'self'; frame-ancestors 'none'; "
       "base-uri 'self'; form-action 'self' https://checkout.stripe.com")

# Installable web app (UX-022): explicit types (Windows' registry can map .js to text/plain), and caching that lets
# a new deploy reach users: the service worker and its manifest are always revalidated, hashed assets are immutable.
STATIC_TYPES = {".webmanifest": "application/manifest+json", ".js": "text/javascript; charset=utf-8",
                ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".glb": "model/gltf-binary", ".svg": "image/svg+xml", ".html": "text/html; charset=utf-8",
                ".woff2": "font/woff2", ".png": "image/png", ".json": "application/json"}
NO_CACHE = {"sw.js", "manifest.webmanifest", "offline.html", "offline.js"}


def static_headers(rel: str) -> dict[str, str]:
    """Response headers for a built SPA file at `rel` (path relative to web/dist)."""
    h: dict[str, str] = {}
    ext = os.path.splitext(rel)[1].lower()
    if ext in STATIC_TYPES:
        h["Content-Type"] = STATIC_TYPES[ext]
    if rel in NO_CACHE:
        h["Cache-Control"] = "no-cache"
        if rel == "sw.js":
            h["Service-Worker-Allowed"] = "/"
    elif rel.startswith("assets/"):
        h["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        h["Cache-Control"] = "public, max-age=3600"
    return h


def module_routers() -> list[Any]:
    """Routers of product modules: every `aicad.platform.routers.mod_<code>` exposing `router` (auto-discovered,
    so modules plug in without editing this file)."""
    import importlib
    import pkgutil

    from aicad.platform import routers as pkg

    out = []
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
        if info.name.startswith("mod_"):
            mod = importlib.import_module(f"{pkg.__name__}.{info.name}")
            if getattr(mod, "router", None) is not None:
                out.append(mod.router)
    return out


def ensure_founder(credentials_file: Path) -> None:
    """First run: create the founder super-admin so God mode is usable. Credentials written to data/ (gitignored)."""
    s = get_settings()
    db = session_factory()()
    try:
        if db.scalar(select(User).where(User.is_superadmin.is_(True))):
            return
        email = s.superadmin_emails[0] if s.superadmin_emails else "founder@formwright.dev"
        if db.scalar(select(User).where(User.email == email)):
            return
        pw = os.environ.get("FW_ADMIN_PASSWORD") or ("Fw-" + secrets.token_urlsafe(12) + "9")
        db.add(User(email=email, name="Founder", password_hash=hash_password(pw), is_superadmin=True,
                    email_verified_at=utcnow(), preferences={"units": "mm", "theme": "light"},
                    god={"enabled": True}))
        db.commit()
        credentials_file.parent.mkdir(parents=True, exist_ok=True)
        credentials_file.write_text(f"Formwright founder (super-admin) account\nemail: {email}\npassword: {pw}\n"
                                    "Change the password after first sign-in (Settings → Security).\n",
                                    encoding="utf-8")
        print(f"Created founder account {email}. Credentials: {credentials_file}")
    finally:
        db.close()


def create_app() -> FastAPI:
    s = get_settings()
    init_engine(s.db_url)
    db = session_factory()()
    try:
        seed_catalog(db)
    finally:
        db.close()
    ensure_founder(s.data_dir / "ADMIN_CREDENTIALS.txt")

    app = FastAPI(title="Formwright", docs_url=None if s.production else "/api/docs", redoc_url=None,
                  openapi_url=None if s.production else "/api/openapi.json")

    from fastapi.middleware.gzip import GZipMiddleware

    app.add_middleware(GZipMiddleware, minimum_size=2048)

    @app.middleware("http")
    async def security(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if (path.startswith("/api/") and request.method in ("POST", "PUT", "PATCH", "DELETE")
                and path not in CSRF_EXEMPT and request.headers.get(CSRF_HEADER) != "1"):
            return JSONResponse({"detail": "Missing CSRF header"}, status_code=403)
        resp: Response = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        if path.startswith("/assets/") and resp.status_code in (200, 304):  # content-hashed build output (StaticFiles)
            resp.headers.update(static_headers(path[1:]))
        if not path.startswith("/api/docs"):
            resp.headers.setdefault("Content-Security-Policy", CSP)
        if s.cookie_secure:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp

    for r in (auth.router, journey.router, team.router, billing.router, projects.router, studio.router, library.router,
              admin.router, god.router, search.router, handoff.router, variants.router, office.router,
              collab.router):
        app.include_router(r)
    for r in module_routers():
        app.include_router(r)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    if (WEB_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        f = (WEB_DIST / full_path).resolve()
        if full_path and WEB_DIST.resolve() in f.parents and f.is_file():
            h = static_headers(full_path)
            return FileResponse(f, media_type=h.pop("Content-Type", None), headers=h)
        index = WEB_DIST / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse({"detail": "Frontend not built. Run: cd web && npm install && npm run build"},
                            status_code=503)

    from aicad.platform.collab.branches import RequestContextMiddleware

    app.add_middleware(RequestContextMiddleware)  # request method + active branch for permissions/workspaces
    return app
