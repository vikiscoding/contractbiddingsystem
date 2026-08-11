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
    objectives_path: Path = Field(
        default=Path("config/objectives.yaml"),
        description="Company objectives for interpret-rank (Grok)",
    )
    state_path: Path = Field(default=Path("state/zero_new_streak.json"))
    log_level: str = Field(default="INFO")
    # Grok / xAI (optional; required only for interpret-rank)
    xai_api_key: str | None = Field(
        default=None,
        description="xAI API key (XAI_API_KEY); never commit",
    )
    xai_base_url: str = Field(
        default="https://api.x.ai/v1",
        description="OpenAI-compatible xAI base URL",
    )
    xai_model: str = Field(
        default="grok-4.5",
        description="Grok model id for interpret-rank",
    )
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
    teams_webhook_url: str | None = Field(
        default=None,
        description="Teams Workflows webhook for ops alerts (and match fallback)",
    )
    teams_match_webhook_url: str | None = Field(
        default=None,
        description=(
            "Optional dedicated webhook for high-match opportunity pings; "
            "falls back to TEAMS_WEBHOOK_URL when unset"
        ),
    )
    teams_match_notify_enabled: bool = Field(
        default=True,
        description="Post Teams card when new matches meet score threshold",
    )
    teams_match_score_threshold: int = Field(
        default=40,
        description="Min score 0–100 to ping Teams (RelevanceScore or Grok fit)",
    )
    teams_match_max_items: int = Field(
        default=8,
        description="Max opportunities listed on one match Adaptive Card",
    )
    notify_config_path: Path = Field(
        default=Path("config/notify.yaml"),
        description="Optional YAML for Teams match notify defaults",
    )
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
        description="Worksheet tab name fully replaced on each opportunity sync",
    )
    google_sheet_rank_tab: str = Field(
        default="Ranked",
        description="Worksheet tab full-replaced by Grok interpret-rank sync",
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

    @field_validator("teams_match_score_threshold")
    @classmethod
    def _threshold_0_100(cls, v: int) -> int:
        n = int(v)
        if n < 0 or n > 100:
            raise ValueError("teams_match_score_threshold must be 0–100")
        return n

    @field_validator("teams_match_max_items")
    @classmethod
    def _max_items_positive(cls, v: int) -> int:
        n = int(v)
        if n < 1:
            raise ValueError("teams_match_max_items must be >= 1")
        return n

    def resolved_sqlite_path(self) -> Path:
        """Return SQLITE_PATH or ``{DATA_DIR}/contract_opportunities.db``."""
        if self.sqlite_path is not None:
            return self.sqlite_path
        return self.data_dir / "contract_opportunities.db"

    def resolved_match_webhook_url(self) -> str | None:
        """Webhook for high-match pings (dedicated URL or ops fallback)."""
        for raw in (self.teams_match_webhook_url, self.teams_webhook_url):
            if raw and str(raw).strip():
                return str(raw).strip()
        return None


def load_notify_yaml_overrides(path: Path | str | None = None) -> dict[str, object]:
    """Load optional config/notify.yaml teams section (soft; empty if missing)."""
    import yaml

    p = Path(path) if path is not None else Path("config/notify.yaml")
    if not p.is_file():
        return {}
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(raw, dict):
        return {}
    teams = raw.get("teams")
    if not isinstance(teams, dict):
        return {}
    out: dict[str, object] = {}
    if "match_notify_enabled" in teams:
        out["teams_match_notify_enabled"] = bool(teams["match_notify_enabled"])
    if "match_score_threshold" in teams:
        try:
            out["teams_match_score_threshold"] = int(teams["match_score_threshold"])
        except (TypeError, ValueError):
            pass
    if "max_items_per_message" in teams:
        try:
            out["teams_match_max_items"] = int(teams["max_items_per_message"])
        except (TypeError, ValueError):
            pass
    return out


def get_settings() -> Settings:
    """Load settings from environment / ``.env``, with soft notify.yaml overrides.

    Env vars always win for secrets and when ``TEAMS_MATCH_*`` is set.
    ``config/notify.yaml`` fills threshold/enabled/max items when those env
    keys are unset.
    """
    import os

    base = Settings()
    yaml_over = load_notify_yaml_overrides(base.notify_config_path)
    if not yaml_over:
        return base

    updates: dict[str, object] = {}
    env_map = {
        "teams_match_notify_enabled": "TEAMS_MATCH_NOTIFY_ENABLED",
        "teams_match_score_threshold": "TEAMS_MATCH_SCORE_THRESHOLD",
        "teams_match_max_items": "TEAMS_MATCH_MAX_ITEMS",
    }
    for field_name, env_name in env_map.items():
        if env_name not in os.environ and field_name in yaml_over:
            updates[field_name] = yaml_over[field_name]
    if not updates:
        return base
    return base.model_copy(update=updates)
