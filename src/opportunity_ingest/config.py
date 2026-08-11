"""Runtime settings from environment (pydantic-settings).

``STORAGE_BACKEND`` selects the OpportunityStore implementation (default: sqlite).
SharePoint requires Azure + site/list secrets when ``STORAGE_BACKEND=sharepoint``.
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
    # Soft create-attempt budget (KD-17). 0 = unlimited; negatives rejected.
    max_create: int | None = Field(
        default=50,
        description="Create-attempt budget (default 50; 0=unlimited)",
    )
    dry_run: bool = Field(
        default=False,
        description=(
            "Loaded from DRY_RUN env for observability only. "
            "Does not enable or disable writes; only --write persists."
        ),
    )
    canadabuys_csv_url: str | None = Field(default=None)
    http_timeout_seconds: float = Field(default=120.0)
    zero_new_streak_threshold: int = Field(default=3)
    partial_error_exit_threshold: int = Field(default=5)
    teams_webhook_url: str | None = Field(default=None)
    github_run_url: str | None = Field(
        default=None,
        description="GitHub Actions run URL for Teams cards (GITHUB_RUN_URL)",
    )

    # SharePoint / Graph — optional until STORAGE_BACKEND=sharepoint
    azure_tenant_id: str | None = Field(default=None)
    azure_client_id: str | None = Field(default=None)
    azure_client_secret: str | None = Field(default=None)
    sharepoint_site_id: str | None = Field(default=None)
    sharepoint_list_id: str | None = Field(default=None)

    # Google Sheets sync (optional free path: service account + Sheets API)
    google_sheet_id: str | None = Field(
        default=None,
        description="Spreadsheet ID from the sheet URL",
    )
    google_sheet_tab: str = Field(
        default="Ingest",
        description="Worksheet tab name fully replaced on each sync",
    )
    google_service_account_file: Path | None = Field(
        default=None,
        description="Path to service account JSON key file",
    )
    google_service_account_json: str | None = Field(
        default=None,
        description="Inline service account JSON (e.g. GitHub secret)",
    )

    @field_validator("storage_backend", mode="before")
    @classmethod
    def _normalize_backend(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("max_create")
    @classmethod
    def _max_create_non_negative(cls, v: int | None) -> int | None:
        """Reject negative MAX_CREATE from env/settings (mirrors CLI --max-create)."""
        if v is not None and int(v) < 0:
            raise ValueError("max_create must be >= 0 (0=unlimited)")
        return v

    def resolved_sqlite_path(self) -> Path:
        """Return SQLITE_PATH or ``{DATA_DIR}/contract_opportunities.db``."""
        if self.sqlite_path is not None:
            return self.sqlite_path
        return self.data_dir / "contract_opportunities.db"


def get_settings() -> Settings:
    """Load settings from environment (and optional ``.env``)."""
    return Settings()
