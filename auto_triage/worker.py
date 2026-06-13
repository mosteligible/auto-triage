from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from auto_triage.accounts import (
    get_environment_settings_for_config,
    get_user_config_by_id,
    settings_for_repository_config,
)
from auto_triage.agent import TriageAgent
from auto_triage.config import Settings
from auto_triage.database import AsyncSessionLocal
from auto_triage.models import (
    EvidenceBundle,
    GitHubIssueLink,
    GitHubPullRequestLink,
    Incident,
    IncidentStatus,
    JobStatus,
    TriageJob,
)
from auto_triage.schemas import NormalizedIncident
from auto_triage.services.codebase import CodebaseInspector
from auto_triage.services.github import GitHubClient
from auto_triage.services.logfire import LogfireClient

logger = logging.getLogger(__name__)


async def recover_interrupted_jobs() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TriageJob).where(TriageJob.status == JobStatus.RUNNING.value)
        )
        jobs = result.scalars().all()
        if not jobs:
            return

        for job in jobs:
            job.status = JobStatus.PENDING.value
            job.last_error = "Recovered from interrupted worker process; retrying."
            incident = await session.get(Incident, job.incident_id)
            if incident is not None and incident.status == IncidentStatus.IN_PROGRESS.value:
                incident.status = IncidentStatus.QUEUED.value
        await session.commit()


class TriageWorker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="auto-triage-worker")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                did_work = await self.process_one()
            except Exception:
                logger.exception("triage worker loop failed")
                did_work = False

            if not did_work:
                await asyncio.sleep(self.settings.worker_poll_interval_seconds)

    async def process_one(self) -> bool:
        job_id = await self._claim_next_job()
        if job_id is None:
            return False

        try:
            await self._process_job(job_id)
        except Exception as exc:
            logger.exception("triage job failed", extra={"job_id": job_id})
            await self._mark_failure(job_id, exc)
        return True

    async def _claim_next_job(self) -> str | None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TriageJob)
                .where(TriageJob.status == JobStatus.PENDING.value)
                .order_by(TriageJob.created_at)
                .limit(1)
            )
            job = result.scalar_one_or_none()
            if job is None:
                return None

            incident = await session.get(Incident, job.incident_id)
            job.status = JobStatus.RUNNING.value
            job.attempts += 1
            job.started_at = datetime.now(tz=UTC)
            job.last_error = None
            if incident is not None:
                incident.status = IncidentStatus.IN_PROGRESS.value
            await session.commit()
            return job.id

    async def _process_job(self, job_id: str) -> None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TriageJob)
                .where(TriageJob.id == job_id)
                .options(selectinload(TriageJob.incident))
            )
            job = result.scalar_one()
            incident_model = job.incident
            normalized = NormalizedIncident.model_validate(incident_model.normalized)
            user_config = await get_user_config_by_id(session, normalized.user_config_id)
            if normalized.user_config_id and user_config is None:
                raise RuntimeError(
                    f"user repository config disappeared: {normalized.user_config_id}"
                )
            environment_settings = await get_environment_settings_for_config(session, user_config)
            effective_settings = settings_for_repository_config(
                self.settings,
                user_config,
                environment_settings,
            )

        logfire_evidence = await LogfireClient(effective_settings).fetch_evidence(normalized)
        logfire_records = [
            record
            for record in logfire_evidence.get("records", [])
            if isinstance(record, dict)
        ]
        codebase_evidence = await CodebaseInspector(effective_settings).inspect(
            incident_model.id,
            normalized,
            logfire_records,
        )

        agent_report = await TriageAgent(effective_settings).run(
            normalized,
            logfire_evidence,
            codebase_evidence,
        )
        evidence_payload = {
            "logfire": logfire_evidence,
            "codebase": codebase_evidence,
        }

        async with AsyncSessionLocal() as session:
            incident = await session.get(Incident, incident_model.id)
            if incident is None:
                raise RuntimeError(f"incident disappeared while processing: {incident_model.id}")

            await self._save_evidence(
                session,
                incident.id,
                logfire_evidence,
                codebase_evidence,
                agent_report.model_dump(mode="json"),
            )

            existing_issue = await self._find_existing_issue(session, incident.fingerprint)
            github = GitHubClient(effective_settings)
            issue_url: str | None = None
            if existing_issue is None:
                issue_response = await github.create_issue(
                    incident.id,
                    normalized,
                    agent_report,
                    evidence_payload,
                )
                session.add(
                    GitHubIssueLink(
                        incident_id=incident.id,
                        repo=effective_settings.github_repo or "",
                        issue_number=issue_response["number"],
                        issue_url=issue_response["html_url"],
                        state=issue_response.get("state", "open"),
                    )
                )
                issue_url = issue_response["html_url"]
                incident.status = IncidentStatus.ISSUE_OPENED.value
            else:
                await github.update_issue(
                    existing_issue.issue_number,
                    incident.id,
                    normalized,
                    agent_report,
                    evidence_payload,
                )
                issue_url = existing_issue.issue_url
                if existing_issue.incident_id != incident.id:
                    session.add(
                        GitHubIssueLink(
                            incident_id=incident.id,
                            repo=existing_issue.repo,
                            issue_number=existing_issue.issue_number,
                            issue_url=existing_issue.issue_url,
                            state=existing_issue.state,
                        )
                    )
                incident.status = IncidentStatus.ISSUE_UPDATED.value

            existing_pull_request = await self._find_existing_pull_request(
                session, incident.fingerprint
            )
            pull_response = await github.create_pull_request(
                incident.id,
                normalized,
                agent_report,
                evidence_payload,
                issue_url=issue_url,
            )
            pull_head = pull_response.get("head") or {}
            pull_base = pull_response.get("base") or {}
            if existing_pull_request is None:
                session.add(
                    GitHubPullRequestLink(
                        incident_id=incident.id,
                        repo=effective_settings.github_repo or "",
                        branch=pull_head.get("ref", ""),
                        base_branch=pull_base.get(
                            "ref", effective_settings.github_default_branch
                        ),
                        pull_number=pull_response["number"],
                        pull_url=pull_response["html_url"],
                        state=pull_response.get("state", "open"),
                    )
                )
                incident.status = IncidentStatus.PULL_REQUEST_OPENED.value
            else:
                existing_pull_request.branch = pull_head.get(
                    "ref", existing_pull_request.branch
                )
                existing_pull_request.base_branch = pull_base.get(
                    "ref", existing_pull_request.base_branch
                )
                existing_pull_request.pull_number = pull_response["number"]
                existing_pull_request.pull_url = pull_response["html_url"]
                existing_pull_request.state = pull_response.get(
                    "state", existing_pull_request.state
                )
                if existing_pull_request.incident_id != incident.id:
                    session.add(
                        GitHubPullRequestLink(
                            incident_id=incident.id,
                            repo=existing_pull_request.repo,
                            branch=existing_pull_request.branch,
                            base_branch=existing_pull_request.base_branch,
                            pull_number=existing_pull_request.pull_number,
                            pull_url=existing_pull_request.pull_url,
                            state=existing_pull_request.state,
                        )
                    )
                incident.status = IncidentStatus.PULL_REQUEST_UPDATED.value

            job = await session.get(TriageJob, job_id)
            if job is not None:
                job.status = JobStatus.SUCCEEDED.value
                job.completed_at = datetime.now(tz=UTC)
            await session.commit()

    async def _save_evidence(
        self,
        session,
        incident_id: str,
        logfire_evidence: dict[str, Any],
        codebase_evidence: dict[str, Any],
        agent_report: dict[str, Any],
    ) -> None:
        result = await session.execute(
            select(EvidenceBundle).where(EvidenceBundle.incident_id == incident_id)
        )
        bundle = result.scalar_one_or_none()
        if bundle is None:
            session.add(
                EvidenceBundle(
                    incident_id=incident_id,
                    logfire=logfire_evidence,
                    codebase=codebase_evidence,
                    agent_report=agent_report,
                )
            )
        else:
            bundle.logfire = logfire_evidence
            bundle.codebase = codebase_evidence
            bundle.agent_report = agent_report

    async def _find_existing_issue(self, session, fingerprint: str) -> GitHubIssueLink | None:
        result = await session.execute(
            select(GitHubIssueLink)
            .join(Incident, Incident.id == GitHubIssueLink.incident_id)
            .where(Incident.fingerprint == fingerprint)
            .order_by(GitHubIssueLink.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _find_existing_pull_request(
        self, session, fingerprint: str
    ) -> GitHubPullRequestLink | None:
        result = await session.execute(
            select(GitHubPullRequestLink)
            .join(Incident, Incident.id == GitHubPullRequestLink.incident_id)
            .where(Incident.fingerprint == fingerprint)
            .order_by(GitHubPullRequestLink.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _mark_failure(self, job_id: str, exc: Exception) -> None:
        async with AsyncSessionLocal() as session:
            job = await session.get(TriageJob, job_id)
            if job is None:
                return
            incident = await session.get(Incident, job.incident_id)
            message = str(exc)[:4_000]
            job.last_error = message
            job.completed_at = datetime.now(tz=UTC)

            if job.attempts < self.settings.max_worker_attempts:
                job.status = JobStatus.PENDING.value
                if incident is not None:
                    incident.status = IncidentStatus.QUEUED.value
            else:
                job.status = JobStatus.FAILED.value
                if incident is not None:
                    incident.status = IncidentStatus.FAILED.value
            await session.commit()
