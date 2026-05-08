from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.state import utc_now


class CheckpointRecord(BaseModel):
    checkpoint_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    payload: dict[str, Any]
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())


class SQLiteCheckpointStore:
    """Append-only checkpoints for recoverable graph progress."""

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
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_checkpoints_job_created
                ON checkpoints(job_id, created_at)
                """
            )

    def save(self, job_id: str, payload: dict[str, Any]) -> CheckpointRecord:
        record = CheckpointRecord(job_id=job_id, payload=payload)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO checkpoints (checkpoint_id, job_id, payload, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    record.checkpoint_id,
                    record.job_id,
                    json.dumps(record.payload, sort_keys=True),
                    record.created_at,
                ),
            )
        return record

    def latest(self, job_id: str) -> CheckpointRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT checkpoint_id, job_id, payload, created_at
                FROM checkpoints
                WHERE job_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            return CheckpointRecord(
                checkpoint_id=row["checkpoint_id"],
                job_id=row["job_id"],
                payload=json.loads(row["payload"]),
                created_at=row["created_at"],
            )

