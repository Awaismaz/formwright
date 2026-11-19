"""FW_AI_SUPERADMIN_ONLY: every AI feature for super-admins only; other accounts get none (no AI calls are made)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_platform import ADMIN, PW, admin, signup

from aicad import llm
from aicad.platform import config


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ai_superadmin_only: bool) -> Iterator[TestClient]:
    from aicad.platform.routers import auth as auth_router

    auth_router._attempts.clear()
    monkeypatch.setenv("FW_ADMIN_PASSWORD", PW)
    config.override_settings(config.Settings(
        env="development", data_dir=tmp_path / "data", database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
        app_url="http://testserver", superadmin_emails=(ADMIN,), stripe_secret_key="",
        ai_superadmin_only=ai_superadmin_only))
    from aicad.platform.app import create_app

    app = create_app()

    @app.post("/api/test-ai-probe")  # stands in for any feature that calls a model (librarian, reviewers, ...)
    def probe() -> dict[str, str]:
        return {"provider": llm.get_provider("planner").name}

    with TestClient(app) as c:
        c.headers.update({"X-FW-CSRF": "1"})
        yield c


@pytest.fixture()
def locked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield from _client(tmp_path, monkeypatch, True)


@pytest.fixture()
def unlocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield from _client(tmp_path, monkeypatch, False)


def test_regular_user_gets_no_ai(locked: TestClient) -> None:
    signup(locked, "ada@example.com")
    pid = locked.post("/api/projects", json={"name": "Bracket", "template": "bracket"}).json()["id"]
    assert locked.get(f"/api/projects/{pid}").json()["agent"]["allowed"] is False
    r = locked.post(f"/api/projects/{pid}/agent/chat", json={"prompt": "make it"})
    assert r.status_code == 402 and r.json()["detail"]["message"] == llm.AI_OFF_MESSAGE
    r = locked.post("/api/test-ai-probe")
    assert r.status_code == 403 and r.json()["detail"] == llm.AI_OFF_MESSAGE


def test_signed_out_gets_no_ai(locked: TestClient) -> None:
    assert locked.post("/api/test-ai-probe").status_code == 403


def test_superadmin_keeps_ai(locked: TestClient) -> None:
    admin(locked)
    pid = locked.post("/api/projects", json={"name": "Bracket", "template": "bracket"}).json()["id"]
    assert locked.get(f"/api/projects/{pid}").json()["agent"]["allowed"] is True
    assert locked.post("/api/test-ai-probe").json()["provider"] == llm.DEFAULT_PROVIDER


def test_off_by_default_everyone_keeps_ai(unlocked: TestClient) -> None:
    signup(unlocked, "ada@example.com")
    pid = unlocked.post("/api/projects", json={"name": "Bracket", "template": "bracket"}).json()["id"]
    assert unlocked.get(f"/api/projects/{pid}").json()["agent"]["allowed"] is True
    assert unlocked.post("/api/test-ai-probe").status_code == 200
