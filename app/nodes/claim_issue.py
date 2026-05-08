from __future__ import annotations

from app.persistence.job_store import SQLiteJobStore
from app.state import TriageGraphState, TriageStatus


async def claim_issue_node(
    state: TriageGraphState,
    *,
    job_store: SQLiteJobStore,
    lease_seconds: int,
) -> TriageGraphState:
    requested_job_id = state.get("job_id")
    job = (
        job_store.claim(requested_job_id, lease_seconds=lease_seconds)
        if requested_job_id
        else job_store.claim_next(lease_seconds=lease_seconds)
    )

    if job is None:
        return {**state, "message": "no queued job available"}

    if job.status != TriageStatus.IN_PROGRESS:
        return {
            **state,
            "message": f"job is already {job.status.value}",
        }

    return {
        **state,
        "job_id": job.job_id,
        "claimed_job_id": job.job_id,
        "message": "job claimed",
    }
