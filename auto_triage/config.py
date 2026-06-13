from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "auto-triage"
    environment: str = "local"
    database_url: str | None = None
    postgres_host: str | None = None
    postgres_port: int = 5432
    postgres_user: str | None = None
    postgres_password: SecretStr | None = None
    postgres_db: str | None = None
    run_worker: bool = True
    worker_poll_interval_seconds: float = 2.0
    max_worker_attempts: int = 3

    webhook_token: SecretStr | None = None

    redis_cache_enabled: bool = False
    redis_url: str | None = None
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_username: str | None = None
    redis_password: SecretStr | None = None
    redis_timeout_seconds: float = 2.0
    redis_cache_ttl_seconds: int = 300

    logfire_base_url: str = "https://logfire-us.pydantic.dev"
    logfire_read_token: SecretStr | None = None
    logfire_project_url: str | None = None
    logfire_lookback_hours: int = 2
    logfire_query_limit: int = 100
    logfire_timeout_seconds: float = 20.0

    openai_api_key: SecretStr | None = None
    triage_model: str = "openai:gpt-4.1-mini"
    openai_triage_model: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_api_version: str | None = None
    azure_openai_deployment: str | None = None
    agent_context_max_chars: int = 80_000

    github_api_base_url: str = "https://api.github.com"
    github_token: SecretStr | None = None
    github_repo: str | None = None
    github_default_branch: str = "main"
    github_issue_labels: list[str] = Field(
        default_factory=lambda: ["auto-triage", "source:logfire", "needs-human-review"]
    )

    target_repo_url: str | None = None
    workspace_dir: Path = Path(".auto-triage-work")
    cleanup_repo_after_triage: bool = True
    max_code_snippets: int = 12
    max_snippet_lines: int = 80
    max_file_bytes: int = 300_000

    @field_validator("logfire_base_url", "github_api_base_url", "azure_openai_endpoint")
    @classmethod
    def strip_url_slash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.rstrip("/")

    @field_validator(
        "logfire_project_url",
        "openai_triage_model",
        "azure_openai_endpoint",
        "azure_openai_api_version",
        "azure_openai_deployment",
        "target_repo_url",
        "redis_url",
        "redis_username",
        "postgres_host",
        "postgres_user",
        "postgres_db",
        mode="before",
    )
    @classmethod
    def blank_string_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def effective_openai_model(self) -> str:
        return self.openai_triage_model or self.triage_model

    @property
    def effective_database_url(self) -> str | URL:
        if self.database_url:
            return self.database_url
        missing = [
            name
            for name, value in {
                "POSTGRES_HOST": self.postgres_host,
                "POSTGRES_USER": self.postgres_user,
                "POSTGRES_PASSWORD": self.postgres_password,
                "POSTGRES_DB": self.postgres_db,
            }.items()
            if value is None
        ]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(
                "Postgres configuration is required. Set DATABASE_URL or provide "
                f"all POSTGRES_* settings. Missing: {joined}"
            )
        return URL.create(
            "postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @field_validator("github_repo")
    @classmethod
    def normalize_repo(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        repo = value.strip().removeprefix("https://github.com/").removesuffix(".git")
        if repo.count("/") != 1:
            raise ValueError("GITHUB_REPO must use owner/repo format")
        return repo

    @property
    def effective_target_repo_url(self) -> str | None:
        if self.target_repo_url:
            return self.target_repo_url
        if self.github_repo:
            return f"https://github.com/{self.github_repo}.git"
        return None

    @property
    def effective_workspace_dir(self) -> Path:
        if self.workspace_dir.is_absolute():
            return self.workspace_dir
        return Path("/tmp/auto-triage-work") / self.workspace_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
