from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AIProvider = Literal["openai", "azure"]


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


class NormalizedIncident(BaseModel):
    source: str = "logfire"
    ai_provider: AIProvider = "openai"
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
