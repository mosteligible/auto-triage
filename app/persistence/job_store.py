from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Iterable

from app.state import TriageJob, TriageStatus, utc_now


class SQLiteJobStore:
    """Small SQLite-backed store for issue triage jobs."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    repository TEXT NOT NULL,
                    issue_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_status_created
                ON jobs(status, created_at)
                """
            )

    def create_or_get(self, job: TriageJob) -> tuple[TriageJob, bool]:
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT payload FROM jobs WHERE job_id = ?",
                (job.job_id,),
            ).fetchone()
            if existing:
                return self._job_from_row(existing), False

            self._insert_or_replace(connection, job)
            return job, True

    def get(self, job_id: str) -> TriageJob | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            return self._job_from_row(row) if row else None

    def list(self, status: TriageStatus | None = None) -> list[TriageJob]:
        with self._lock, self._connect() as connection:
            if status is None:
                rows = connection.execute(
                    "SELECT payload FROM jobs ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT payload FROM jobs WHERE status = ? ORDER BY created_at DESC",
                    (status.value,),
                ).fetchall()
            return [self._job_from_row(row) for row in rows]

    def update(self, job: TriageJob) -> TriageJob:
        with self._lock, self._connect() as connection:
            self._insert_or_replace(connection, job)
        return job

    def enqueue_many(self, jobs: Iterable[TriageJob]) -> tuple[list[TriageJob], list[TriageJob]]:
        queued: list[TriageJob] = []
        existing: list[TriageJob] = []
        for job in jobs:
            stored, created = self.create_or_get(job)
            if created:
                queued.append(stored)
            else:
                existing.append(stored)
        return queued, existing

    def claim_next(self, *, lease_seconds: int) -> TriageJob | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM jobs
                WHERE status = ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (TriageStatus.QUEUED.value,),
            ).fetchone()
            if row is None:
                return None

            job = self._job_from_row(row).claim(lease_seconds=lease_seconds)
            self._insert_or_replace(connection, job)
            return job

    def claim(self, job_id: str, *, lease_seconds: int) -> TriageJob | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None

            job = self._job_from_row(row)
            if job.status == TriageStatus.IN_PROGRESS:
                return job
            if job.status != TriageStatus.QUEUED:
                return job
            claimed = job.claim(lease_seconds=lease_seconds)
            self._insert_or_replace(connection, claimed)
            return claimed

    def mark_resolved(
        self,
        job_id: str,
        *,
        branch_name: str | None = None,
        pull_request_url: str | None = None,
    ) -> TriageJob | None:
        job = self.get(job_id)
        if job is None:
            return None
        resolved = job.transition(
            TriageStatus.RESOLVED,
            branch_name=branch_name,
            pull_request_url=pull_request_url,
            locked_until=None,
            failure_reason=None,
        )
        return self.update(resolved)

    def mark_unable_to_fix(self, job_id: str, *, reason: str) -> TriageJob | None:
        job = self.get(job_id)
        if job is None:
            return None
        unable = job.transition(
            TriageStatus.UNABLE_TO_FIX,
            failure_reason=reason,
            locked_until=None,
        )
        return self.update(unable)

    def _insert_or_replace(self, connection: sqlite3.Connection, job: TriageJob) -> None:
        now = utc_now()
        if job.updated_at is None:
            job = job.model_copy(update={"updated_at": now})
        connection.execute(
            """
            INSERT OR REPLACE INTO jobs (
                job_id,
                repository,
                issue_number,
                status,
                payload,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.job_id,
                job.issue.repository,
                job.issue.number,
                job.status.value,
                job.model_dump_json(),
                job.created_at.isoformat(),
                job.updated_at.isoformat(),
            ),
        )

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> TriageJob:
        return TriageJob.model_validate_json(row["payload"])
