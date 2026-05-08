from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_csv(value: Any) -> list[str]:
    """Parse comma-separated environment values into a clean list."""
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    raise TypeError("expected a comma-separated string or list")


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    github_token: SecretStr | None = Field(default=None, alias="GITHUB_TOKEN")
    github_repositories: list[str] = Field(default_factory=list, alias="GITHUB_REPOSITORIES")
    github_issue_tags_to_work_on: list[str] = Field(
        default_factory=lambda: ["auto-triage-ready"],
        alias="GITHUB_ISSUE_TAGS_TO_WORK_ON",
    )
    github_issue_fixed_tag: str = Field(
        default="auto-triage-fixed",
        alias="GITHUB_ISSUE_FIXED_TAG",
    )
    github_issue_unable_to_fix_tag: str = Field(
        default="auto-triage-unable-to-fix",
        alias="GITHUB_ISSUE_UNABLE_TO_FIX_TAG",
    )
    triage_poll_interval_seconds: int = Field(
        default=300,
        ge=1,
        alias="TRIAGE_POLL_INTERVAL_SECONDS",
    )
    triage_data_dir: Path = Field(default=Path(".triage"), alias="TRIAGE_DATA_DIR")
    triage_scheduler_enabled: bool = Field(default=True, alias="TRIAGE_SCHEDULER_ENABLED")
    triage_lease_seconds: int = Field(default=1800, ge=1, alias="TRIAGE_LEASE_SECONDS")
    triage_fix_execution_enabled: bool = Field(
        default=False,
        alias="TRIAGE_FIX_EXECUTION_ENABLED",
    )

    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1", alias="OPENAI_MODEL")

    @field_validator("github_repositories", "github_issue_tags_to_work_on", mode="before")
    @classmethod
    def _parse_csv_fields(cls, value: Any) -> list[str]:
        return parse_csv(value)

    @field_validator("github_repositories")
    @classmethod
    def _validate_repositories(cls, repositories: list[str]) -> list[str]:
        invalid = [repo for repo in repositories if "/" not in repo]
        if invalid:
            raise ValueError(f"repositories must use owner/name format: {', '.join(invalid)}")
        return repositories

    @property
    def job_store_path(self) -> Path:
        return self.triage_data_dir / "jobs.sqlite3"

    @property
    def checkpoint_store_path(self) -> Path:
        return self.triage_data_dir / "checkpoints.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()
