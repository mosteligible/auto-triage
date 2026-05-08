from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Iterable, TypedDict

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class TriageStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    UNABLE_TO_FIX = "unable_to_fix"


TERMINAL_STATUSES = {TriageStatus.RESOLVED, TriageStatus.UNABLE_TO_FIX}

ALLOWED_TRANSITIONS: dict[TriageStatus, set[TriageStatus]] = {
    TriageStatus.QUEUED: {TriageStatus.IN_PROGRESS, TriageStatus.UNABLE_TO_FIX},
    TriageStatus.IN_PROGRESS: {
        TriageStatus.QUEUED,
        TriageStatus.RESOLVED,
        TriageStatus.UNABLE_TO_FIX,
    },
    TriageStatus.RESOLVED: set(),
    TriageStatus.UNABLE_TO_FIX: set(),
}


class InvalidStatusTransition(ValueError):
    """Raised when a triage job is moved through an invalid state change."""


class IssueRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository: str
    number: int
    title: str = ""
    body: str | None = None
    labels: list[str] = Field(default_factory=list)
    url: str | None = None


class TriageJob(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    job_id: str
    issue: IssueRef
    status: TriageStatus = TriageStatus.QUEUED
    attempt_count: int = 0
    branch_name: str | None = None
    pull_request_url: str | None = None
    failure_reason: str | None = None
    locked_until: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_issue(cls, issue: IssueRef) -> TriageJob:
        return cls(job_id=job_id_for_issue(issue.repository, issue.number), issue=issue)

    def transition(
        self,
        target: TriageStatus,
        *,
        now: datetime | None = None,
        **updates: Any,
    ) -> TriageJob:
        if not can_transition(self.status, target):
            raise InvalidStatusTransition(f"cannot transition {self.status} to {target}")

        data = self.model_dump()
        data.update(updates)
        data["status"] = target
        data["updated_at"] = now or utc_now()
        return type(self).model_validate(data)

    def claim(self, *, lease_seconds: int, now: datetime | None = None) -> TriageJob:
        claimed_at = now or utc_now()
        return self.transition(
            TriageStatus.IN_PROGRESS,
            now=claimed_at,
            attempt_count=self.attempt_count + 1,
            locked_until=claimed_at + timedelta(seconds=lease_seconds),
            failure_reason=None,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


class TriageGraphState(TypedDict, total=False):
    job_id: str
    discovered_job_ids: list[str]
    queued_job_ids: list[str]
    claimed_job_id: str
    fix_success: bool
    should_finalize: bool
    branch_name: str
    pull_request_url: str
    failure_reason: str
    summary: str
    errors: list[str]
    message: str


def job_id_for_issue(repository: str, number: int) -> str:
    safe_repository = repository.replace("/", "__")
    return f"{safe_repository}__{number}"


def can_transition(source: TriageStatus, target: TriageStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[source]


def is_issue_eligible(issue_labels: Iterable[str], required_labels: Iterable[str]) -> bool:
    required = {label.casefold() for label in required_labels if label}
    if not required:
        return False
    available = {label.casefold() for label in issue_labels if label}
    return required.issubset(available)
