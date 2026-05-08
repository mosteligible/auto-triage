from __future__ import annotations

from datetime import UTC, datetime

import pytest

from state import (
    InvalidStatusTransition,
    IssueRef,
    TriageJob,
    TriageStatus,
    is_issue_eligible,
    job_id_for_issue,
)


def test_issue_eligibility_requires_all_configured_labels_case_insensitively() -> None:
    assert is_issue_eligible(
        ["Auto-Triage-Ready", "bug", "frontend"],
        ["auto-triage-ready", "BUG"],
    )
    assert not is_issue_eligible(["auto-triage-ready"], ["auto-triage-ready", "bug"])


def test_job_claim_updates_status_attempt_count_and_lease() -> None:
    now = datetime(2026, 5, 7, tzinfo=UTC)
    job = TriageJob.from_issue(IssueRef(repository="owner/repo", number=42))

    claimed = job.claim(lease_seconds=60, now=now)

    assert claimed.status == TriageStatus.IN_PROGRESS
    assert claimed.attempt_count == 1
    assert claimed.locked_until is not None
    assert claimed.locked_until.timestamp() == now.timestamp() + 60


def test_invalid_terminal_transition_is_rejected() -> None:
    job = TriageJob.from_issue(IssueRef(repository="owner/repo", number=42))
    resolved = job.transition(TriageStatus.IN_PROGRESS).transition(TriageStatus.RESOLVED)

    with pytest.raises(InvalidStatusTransition):
        resolved.transition(TriageStatus.QUEUED)


def test_job_serialization_round_trip() -> None:
    job = TriageJob.from_issue(
        IssueRef(
            repository="owner/repo",
            number=42,
            title="Fix it",
            labels=["auto-triage-ready"],
        )
    )

    restored = TriageJob.model_validate_json(job.model_dump_json())

    assert restored == job
    assert restored.job_id == job_id_for_issue("owner/repo", 42)

