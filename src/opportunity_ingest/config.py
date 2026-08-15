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
        description="Max opportunities listed on one match Adaptive Card / Slack msg",
    )
    # Slack CLI / Bolt credentials (preferred for match pings)
    # https://docs.slack.dev/tools/slack-cli/ — paste tokens from CLI-created app
    slack_bot_token: str | None = Field(
        default=None,
        description="Bot User OAuth Token xoxb-... (Slack CLI / Bolt SLACK_BOT_TOKEN)",
    )
    slack_app_token: str | None = Field(
        default=None,
        description=(
            "App-level token xapp-... (SLACK_APP_TOKEN; Socket Mode / slack run). "
            "Not required for outbound chat.postMessage match alerts."
        ),
    )
    slack_channel_id: str | None = Field(
        default=None,
        description="Channel ID C... or #name for match posts (chat.postMessage)",
    )
    # Legacy Incoming Webhooks (fallback if bot token unset)
    slack_webhook_url: str | None = Field(
        default=None,
        description="Legacy Incoming Webhook URL (prefer SLACK_BOT_TOKEN)",
    )
    slack_match_webhook_url: str | None = Field(
        default=None,
        description="Legacy dedicated match webhook; falls back to SLACK_WEBHOOK_URL",
    )
    slack_match_notify_enabled: bool = Field(
        default=True,
        description="Post Slack message when new matches meet score threshold",
    )
    notify_config_path: Path = Field(
        default=Path("config/notify.yaml"),
        description="Optional YAML for Teams/Slack match notify defaults",
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
    google_sheet_url: str | None = Field(
        default=None,
        description=(
            "Optional full spreadsheet share/deep link for Teams/Slack cards; "
            "when unset, built from GOOGLE_SHEET_ID"
        ),
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
        """Teams webhook for high-match pings (dedicated URL or ops fallback)."""
        for raw in (self.teams_match_webhook_url, self.teams_webhook_url):
            if raw and str(raw).strip():
                return str(raw).strip()
        return None

    def resolved_google_sheet_url(self) -> str | None:
        """Browser URL for the opportunity spreadsheet (match-card CTA).

        Uses ``GOOGLE_SHEET_URL`` when set; otherwise
        ``https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/edit``.
        """
        if self.google_sheet_url and str(self.google_sheet_url).strip():
            u = str(self.google_sheet_url).strip()
            if u.startswith(("http://", "https://")):
                return u
        sid = (self.google_sheet_id or "").strip()
        if not sid:
            return None
        return f"https://docs.google.com/spreadsheets/d/{sid}/edit"

    def resolved_slack_match_webhook_url(self) -> str | None:
        """Legacy Incoming Webhook for match pings (if bot token path unused)."""
        for raw in (self.slack_match_webhook_url, self.slack_webhook_url):
            if raw and str(raw).strip():
                return str(raw).strip()
        return None

    def resolved_slack_bot_token(self) -> str | None:
        """Bot token for Web API (Slack CLI / Bolt ``SLACK_BOT_TOKEN``)."""
        if self.slack_bot_token and str(self.slack_bot_token).strip():
            return str(self.slack_bot_token).strip()
        return None

    def resolved_slack_channel_id(self) -> str | None:
        """Target channel for ``chat.postMessage``."""
        if self.slack_channel_id and str(self.slack_channel_id).strip():
            return str(self.slack_channel_id).strip()
        return None

    def slack_web_api_configured(self) -> bool:
        """True when Slack CLI-style bot token + channel are both set."""
        return bool(self.resolved_slack_bot_token() and self.resolved_slack_channel_id())


def load_notify_yaml_overrides(path: Path | str | None = None) -> dict[str, object]:
    """Load optional config/notify.yaml teams/slack sections (soft; empty if missing)."""
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
    out: dict[str, object] = {}

    # Shared threshold / max items (root or teams — teams keeps back-compat)
    shared = raw.get("match") if isinstance(raw.get("match"), dict) else {}
    teams = raw.get("teams") if isinstance(raw.get("teams"), dict) else {}
    slack = raw.get("slack") if isinstance(raw.get("slack"), dict) else {}

    thr = shared.get("score_threshold", teams.get("match_score_threshold"))
    if thr is not None:
        try:
            out["teams_match_score_threshold"] = int(thr)
        except (TypeError, ValueError):
            pass
    max_items = shared.get("max_items_per_message", teams.get("max_items_per_message"))
    if max_items is not None:
        try:
            out["teams_match_max_items"] = int(max_items)
        except (TypeError, ValueError):
            pass

    if "match_notify_enabled" in teams:
        out["teams_match_notify_enabled"] = bool(teams["match_notify_enabled"])
    if "match_notify_enabled" in slack:
        out["slack_match_notify_enabled"] = bool(slack["match_notify_enabled"])
    return out


def get_settings() -> Settings:
    """Load settings from environment / ``.env``, with soft notify.yaml overrides.

    Env vars always win for secrets and when ``TEAMS_MATCH_*`` / ``SLACK_*`` is set.
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
        "slack_match_notify_enabled": "SLACK_MATCH_NOTIFY_ENABLED",
    }
    for field_name, env_name in env_map.items():
        if env_name not in os.environ and field_name in yaml_over:
            updates[field_name] = yaml_over[field_name]
    if not updates:
        return base
    return base.model_copy(update=updates)
