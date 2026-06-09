from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auto_triage.models import EvidenceBundle, GitHubIssueLink, Incident, IncidentStatus, TriageJob
from auto_triage.schemas import IncidentDetail, NormalizedIncident


async def enqueue_incident(
    session: AsyncSession,
    normalized: NormalizedIncident,
    raw_payload: dict,
) -> tuple[Incident, TriageJob, bool]:
    result = await session.execute(
        select(Incident).where(Incident.fingerprint == normalized.fingerprint)
    )
    incident = result.scalar_one_or_none()
    duplicate = incident is not None

    if incident is None:
        incident = Incident(
            source=normalized.source,
            alert_kind=normalized.alert_kind,
            title=normalized.title,
            fingerprint=normalized.fingerprint,
            service_name=normalized.service_name,
            route=normalized.route,
            trace_id=normalized.trace_id,
            exception_type=normalized.exception_type,
            status_code=normalized.status_code,
            status=IncidentStatus.QUEUED.value,
            raw_payload=raw_payload,
            normalized=normalized.model_dump(mode="json"),
        )
        session.add(incident)
        await session.flush()
    else:
        incident.occurrence_count += 1
        incident.title = normalized.title
        incident.alert_kind = normalized.alert_kind
        incident.service_name = normalized.service_name
        incident.route = normalized.route
        incident.trace_id = normalized.trace_id
        incident.exception_type = normalized.exception_type
        incident.status_code = normalized.status_code
        incident.status = IncidentStatus.QUEUED.value
        incident.raw_payload = raw_payload
        incident.normalized = normalized.model_dump(mode="json")

    job = TriageJob(incident_id=incident.id)
    session.add(job)
    await session.commit()
    await session.refresh(incident)
    await session.refresh(job)
    return incident, job, duplicate


async def get_incident_detail(session: AsyncSession, incident_id: str) -> IncidentDetail | None:
    result = await session.execute(
        select(Incident)
        .where(Incident.id == incident_id)
        .options(
            selectinload(Incident.jobs),
            selectinload(Incident.evidence_bundle),
            selectinload(Incident.github_issue),
        )
    )
    incident = result.scalar_one_or_none()
    if incident is None:
        return None

    return IncidentDetail(
        id=incident.id,
        status=incident.status,
        occurrence_count=incident.occurrence_count,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
        normalized=incident.normalized,
        jobs=[
            {
                "id": job.id,
                "status": job.status,
                "attempts": job.attempts,
                "last_error": job.last_error,
                "created_at": job.created_at,
                "started_at": job.started_at,
                "completed_at": job.completed_at,
            }
            for job in sorted(incident.jobs, key=lambda item: item.created_at)
        ],
        evidence=_evidence_payload(incident.evidence_bundle),
        github_issue=_issue_payload(incident.github_issue),
    )


def _evidence_payload(bundle: EvidenceBundle | None) -> dict | None:
    if bundle is None:
        return None
    return {
        "logfire": bundle.logfire,
        "codebase": bundle.codebase,
        "agent_report": bundle.agent_report,
        "updated_at": bundle.updated_at,
    }


def _issue_payload(issue: GitHubIssueLink | None) -> dict | None:
    if issue is None:
        return None
    return {
        "repo": issue.repo,
        "issue_number": issue.issue_number,
        "issue_url": issue.issue_url,
        "state": issue.state,
        "updated_at": issue.updated_at,
    }
