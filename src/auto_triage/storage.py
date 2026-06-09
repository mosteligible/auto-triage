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
    if incident is None:
        incident = await _find_semantic_duplicate(session, normalized)
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
        incident.fingerprint = normalized.fingerprint
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


async def _find_semantic_duplicate(
    session: AsyncSession,
    normalized: NormalizedIncident,
) -> Incident | None:
    result = await session.execute(
        select(Incident)
        .where(Incident.source == normalized.source)
        .where(Incident.alert_kind == normalized.alert_kind)
        .order_by(Incident.updated_at.desc())
        .limit(100)
    )
    candidates = result.scalars().all()
    normalized_route = _canonical_route(normalized.route or normalized.span_name)
    normalized_status_family = _status_family(normalized.status_code)
    for candidate in candidates:
        if candidate.service_name and normalized.service_name:
            if candidate.service_name != normalized.service_name:
                continue
        elif candidate.service_name or normalized.service_name:
            continue

        if _canonical_route(candidate.route) != normalized_route:
            continue
        if (candidate.exception_type or "") != (normalized.exception_type or ""):
            continue
        if _status_family(candidate.status_code) != normalized_status_family:
            continue
        return candidate
    return None


def _canonical_route(route: str | None) -> str:
    if not route:
        return ""
    method, _, path = route.partition(" ")
    if method.isalpha() and path.startswith("/"):
        return path
    return route


def _status_family(status_code: int | None) -> str:
    return f"{status_code // 100}xx" if status_code else ""


async def get_incident_detail(session: AsyncSession, incident_id: str) -> IncidentDetail | None:
    result = await session.execute(
        select(Incident)
        .where(Incident.id == incident_id)
        .options(
            selectinload(Incident.jobs),
            selectinload(Incident.evidence_bundle),
            selectinload(Incident.github_issue),
            selectinload(Incident.github_pull_request),
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
        github_pull_request=_pull_request_payload(incident.github_pull_request),
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


def _pull_request_payload(pull_request) -> dict | None:
    if pull_request is None:
        return None
    return {
        "repo": pull_request.repo,
        "branch": pull_request.branch,
        "base_branch": pull_request.base_branch,
        "pull_number": pull_request.pull_number,
        "pull_url": pull_request.pull_url,
        "state": pull_request.state,
        "updated_at": pull_request.updated_at,
    }
