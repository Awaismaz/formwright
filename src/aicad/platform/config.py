"""Runtime configuration from environment variables (12-factor).

FW_ENV=development|production. God mode is *impossible* in production regardless of other flags.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: os.environ.get("FW_ENV", "development"))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("FW_DATA_DIR", ROOT / "data")))
    database_url: str = field(default_factory=lambda: os.environ.get("FW_DATABASE_URL", ""))
    app_url: str = field(default_factory=lambda: os.environ.get("FW_APP_URL", "http://127.0.0.1:8765"))
    god_mode_requested: bool = field(default_factory=lambda: _bool("FW_GOD_MODE", True))
    superadmin_emails: tuple[str, ...] = field(default_factory=lambda: tuple(
        e.strip().lower() for e in os.environ.get("FW_SUPERADMIN_EMAILS", "founder@formwright.dev").split(",")
        if e.strip()))
    stripe_secret_key: str = field(default_factory=lambda: os.environ.get("STRIPE_SECRET_KEY", ""))
    stripe_webhook_secret: str = field(default_factory=lambda: os.environ.get("STRIPE_WEBHOOK_SECRET", ""))
    smtp_host: str = field(default_factory=lambda: os.environ.get("FW_SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: int(os.environ.get("FW_SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: os.environ.get("FW_SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.environ.get("FW_SMTP_PASSWORD", ""))
    smtp_from: str = field(default_factory=lambda: os.environ.get("FW_SMTP_FROM", "Formwright <no-reply@formwright.dev>"))
    # AGT-001: which model provider serves which role ("default=claude-sdk,vision=anthropic-api"; aicad.llm)
    llm_providers: str = field(default_factory=lambda: os.environ.get("FW_LLM_PROVIDERS", ""))
    session_days: int = 14
    trial_tokens: int = field(default_factory=lambda: int(os.environ.get("FW_TRIAL_TOKENS", "1000")))
    trial_days: int = 14

    @property
    def production(self) -> bool:
        return self.env == "production"

    @property
    def god_mode_enabled(self) -> bool:
        return self.god_mode_requested and not self.production

    @property
    def stripe_live(self) -> bool:
        """True when real Stripe (test or live keys) is configured; otherwise payments are simulated."""
        return bool(self.stripe_secret_key)

    @property
    def stripe_mode(self) -> str:
        if not self.stripe_secret_key:
            return "simulated"
        return "live" if self.stripe_secret_key.startswith("sk_live") else "test"

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(self.data_dir / 'formwright.db').as_posix()}"

    @property
    def workspaces_dir(self) -> Path:
        p = self.data_dir / "workspaces"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cookie_secure(self) -> bool:
        return self.app_url.startswith("https://")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        if _settings.production and _settings.stripe_mode == "simulated":
            raise RuntimeError("production requires STRIPE_SECRET_KEY (simulated payments are dev-only)")
    return _settings


def override_settings(s: Settings) -> None:
    """Tests only."""
    global _settings
    _settings = s
