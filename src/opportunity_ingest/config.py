"""Runtime settings from environment (pydantic-settings).

Storage backends are selected here but not fully implemented until later PRs.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Minimal Phase 1 settings loaded from env / optional ``.env`` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    storage_backend: str = Field(default="sqlite", description="sqlite | sharepoint")
    data_dir: Path = Field(default=Path("data"))
    sqlite_path: Path | None = Field(
        default=None,
        description="Explicit SQLite path; default {DATA_DIR}/contract_opportunities.db",
    )
    keywords_path: Path = Field(default=Path("config/keywords.yaml"))
    state_path: Path = Field(default=Path("state/zero_new_streak.json"))
    log_level: str = Field(default="INFO")
    max_create: int | None = Field(default=None)
    dry_run: bool = Field(default=False)
    canadabuys_csv_url: str | None = Field(default=None)
    http_timeout_seconds: float = Field(default=120.0)
    zero_new_streak_threshold: int = Field(default=3)
    partial_error_exit_threshold: int = Field(default=5)
    teams_webhook_url: str | None = Field(default=None)

    # SharePoint / Graph — optional until STORAGE_BACKEND=sharepoint
    azure_tenant_id: str | None = Field(default=None)
    azure_client_id: str | None = Field(default=None)
    azure_client_secret: str | None = Field(default=None)
    sharepoint_site_id: str | None = Field(default=None)
    sharepoint_list_id: str | None = Field(default=None)

    @field_validator("storage_backend", mode="before")
    @classmethod
    def _normalize_backend(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip().lower()
        return v

    def resolved_sqlite_path(self) -> Path:
        """Return SQLITE_PATH or ``{DATA_DIR}/contract_opportunities.db``."""
        if self.sqlite_path is not None:
            return self.sqlite_path
        return self.data_dir / "contract_opportunities.db"


def get_settings() -> Settings:
    """Load settings from environment (and optional ``.env``)."""
    return Settings()
