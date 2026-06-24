from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AIProvider = Literal["openai", "azure"]
AlertTrigger = Literal["exception", "http_5xx", "error_rate"]
AlertMode = Literal["has_results", "starts_having_results", "results_change"]
OrganizationRole = Literal["admin", "write", "read"]


class TriageQuery(BaseModel):
    ai_provider: AIProvider = Field(
        default="openai",
        description="Use 'azure' to run triage with Azure OpenAI; omit or use 'openai' otherwise.",
    )


class WebhookTriageQuery(BaseModel):
    ai_provider: AIProvider = Field(
        default="azure",
        description=(
            "Use 'openai' to run triage with standard OpenAI; omit or use 'azure' otherwise."
        ),
    )


class UserWebhookTriageQuery(BaseModel):
    ai_provider: AIProvider | None = Field(
        default=None,
        description="Optional override for the AI provider configured for this user's webhook.",
    )


class NormalizedIncident(BaseModel):
    source: str = "logfire"
    ai_provider: AIProvider = "openai"
    user_id: str | None = None
    organization_id: str | None = None
    user_config_id: str | None = None
    webhook_id: str | None = None
    alert_kind: str
    title: str
    fingerprint: str
    service_name: str | None = None
    route: str | None = None
    span_name: str | None = None
    trace_id: str | None = None
    exception_type: str | None = None
    exception_message: str | None = None
    exception_stacktrace: str | None = None
    top_frame: str | None = None
    status_code: int | None = None
    alert_url: str | None = None
    observed_text: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class ManualIncidentIn(BaseModel):
    title: str
    alert_kind: str = "manual"
    service_name: str | None = None
    route: str | None = None
    span_name: str | None = None
    trace_id: str | None = None
    exception_type: str | None = None
    exception_message: str | None = None
    exception_stacktrace: str | None = None
    status_code: int | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class WebhookAck(BaseModel):
    incident_id: str
    job_id: str
    status: str
    duplicate: bool


class AuthLoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=256)


class AuthLoginOut(BaseModel):
    user_id: str
    organization_id: str
    organization_name: str
    organization_slug: str
    role: OrganizationRole
    email: str
    display_name: str | None
    auth_token: str


class OrganizationRegisterIn(BaseModel):
    organization_name: str = Field(min_length=1, max_length=256)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=256)


class OrganizationOut(BaseModel):
    id: str
    name: str
    slug: str
    current_user_role: OrganizationRole


class OrganizationMemberCreateIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str | None = Field(default=None, min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=256)
    role: OrganizationRole = "read"


class OrganizationMemberOut(BaseModel):
    membership_id: str
    user_id: str
    organization_id: str
    email: str
    display_name: str | None
    role: OrganizationRole
    created_at: datetime | None
    updated_at: datetime | None


class UserRepositoryConfigIn(BaseModel):
    github_owner: str = Field(min_length=1, max_length=128)
    github_repo_name: str = Field(min_length=1, max_length=128)
    github_token: str | None = None
    github_token_unchanged: bool = False
    github_default_branch: str = Field(default="main", min_length=1, max_length=256)
    target_repo_url: str | None = Field(default=None, max_length=1024)
    logfire_base_url: str = Field(default="https://logfire-us.pydantic.dev", max_length=512)
    logfire_read_token: str | None = None
    logfire_read_token_unchanged: bool = False
    logfire_project_url: str | None = Field(default=None, max_length=1024)
    logfire_service_name: str | None = Field(default=None, max_length=256)
    logfire_route: str | None = Field(default=None, max_length=512)
    alert_trigger: AlertTrigger = "http_5xx"
    alert_mode: AlertMode = "starts_having_results"
    ai_provider: AIProvider = "azure"


class UserRepositoryConfigOut(BaseModel):
    id: str
    organization_id: str
    webhook_id: str
    webhook_path: str
    github_owner: str
    github_repo_name: str
    github_repo: str
    github_default_branch: str
    target_repo_url: str | None
    github_token_configured: bool
    logfire_base_url: str
    logfire_read_token_configured: bool
    logfire_project_url: str | None
    logfire_service_name: str | None
    logfire_route: str | None
    alert_trigger: str
    alert_mode: str
    ai_provider: AIProvider
    created_at: datetime | None
    updated_at: datetime | None


class UserProfileOut(BaseModel):
    user_id: str
    organization_id: str
    organization_name: str
    organization_slug: str
    role: OrganizationRole
    platform_role: str
    email: str
    display_name: str | None
    repository_config: UserRepositoryConfigOut | None


class SetupOutputsIn(BaseModel):
    webhook_url: str = Field(default="", max_length=262_144)
    env_file: str = Field(default="", max_length=262_144)
    logfire_query: str = Field(default="", max_length=262_144)


class SetupOutputsOut(SetupOutputsIn):
    id: str
    organization_id: str
    created_at: datetime | None
    updated_at: datetime | None


class OrganizationEnvironmentSettingsIn(BaseModel):
    api_base_url: str = Field(min_length=1, max_length=1024)
    public_webhook_base_url: str | None = Field(default=None, max_length=1024)
    logfire_region: Literal["us", "eu"]
    alert_window_minutes: int = Field(ge=1, le=1440)
    openai_model: str = Field(min_length=1, max_length=256)
    openai_api_key: str | None = None
    openai_api_key_unchanged: bool = False
    azure_openai_endpoint: str | None = Field(default=None, max_length=1024)
    azure_openai_deployment: str | None = Field(default=None, max_length=256)
    azure_openai_api_version: str | None = Field(default=None, max_length=128)
    azure_openai_api_key: str | None = None
    azure_openai_api_key_unchanged: bool = False
    postgres_host: str | None = Field(default=None, max_length=256)
    postgres_port: int = Field(ge=1, le=65535)
    postgres_user: str | None = Field(default=None, max_length=256)
    postgres_password: str | None = None
    postgres_password_unchanged: bool = False
    postgres_db: str | None = Field(default=None, max_length=256)
    redis_enabled: bool
    redis_host: str | None = Field(default=None, max_length=256)
    redis_port: int = Field(ge=1, le=65535)
    redis_username: str | None = Field(default=None, max_length=256)
    redis_password: str | None = None
    redis_password_unchanged: bool = False
    redis_ttl_seconds: int = Field(ge=0, le=86_400)


class OrganizationEnvironmentSettingsOut(BaseModel):
    id: str
    organization_id: str
    api_base_url: str
    public_webhook_base_url: str | None
    logfire_region: Literal["us", "eu"]
    alert_window_minutes: int
    openai_model: str
    openai_api_key_configured: bool
    azure_openai_endpoint: str | None
    azure_openai_deployment: str | None
    azure_openai_api_version: str | None
    azure_openai_api_key_configured: bool
    postgres_host: str | None
    postgres_port: int
    postgres_user: str | None
    postgres_password_configured: bool
    postgres_db: str | None
    redis_enabled: bool
    redis_host: str | None
    redis_port: int
    redis_username: str | None
    redis_password_configured: bool
    redis_ttl_seconds: int
    created_at: datetime | None
    updated_at: datetime | None


class OrganizationEnvironmentVariableIn(BaseModel):
    id: str | None = Field(default=None, min_length=32, max_length=32)
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", min_length=1, max_length=256)
    value: str = Field(default="", max_length=262_144)
    sensitive: bool = False
    retain_existing: bool = False


class OrganizationEnvironmentVariableOut(BaseModel):
    id: str
    name: str
    value: str
    sensitive: bool
    configured: bool
    position: int
    updated_at: datetime | None


class OrganizationEnvironmentVariablesIn(BaseModel):
    variables: list[OrganizationEnvironmentVariableIn] = Field(max_length=200)


class OrganizationEnvironmentVariablesOut(BaseModel):
    organization_id: str
    organization_name: str
    variables: list[OrganizationEnvironmentVariableOut]
    updated_at: datetime | None


class AlertTestIn(BaseModel):
    service_name: str | None = None
    route: str | None = None
    status_code: int = 500
    exception_type: str = "RuntimeError"
    exception_message: str = "Intentional setup smoke test"


class TriageReport(BaseModel):
    summary: str
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    confidence: Literal["low", "medium", "high"] = "medium"
    root_cause_hypothesis: str
    evidence: list[str] = Field(default_factory=list)
    affected_files: list[str] = Field(default_factory=list)
    proposed_fix: str
    acceptance_tests: list[str] = Field(default_factory=list)
    github_labels: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class IncidentDetail(BaseModel):
    id: str
    status: str
    occurrence_count: int
    created_at: datetime | None
    updated_at: datetime | None
    normalized: dict[str, Any]
    jobs: list[dict[str, Any]]
    evidence: dict[str, Any] | None
    github_issue: dict[str, Any] | None
    github_pull_request: dict[str, Any] | None = None
