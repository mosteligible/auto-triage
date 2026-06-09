from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from auto_triage.database import Base


def new_id() -> str:
    return uuid4().hex


class IncidentStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    ISSUE_OPENED = "issue_opened"
    ISSUE_UPDATED = "issue_updated"
    FAILED = "failed"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(64), default="logfire", index=True)
    alert_kind: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    service_name: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    route: Mapped[str | None] = mapped_column(String(512), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    exception_type: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default=IncidentStatus.QUEUED.value, index=True
    )
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    normalized: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    jobs: Mapped[list[TriageJob]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )
    evidence_bundle: Mapped[EvidenceBundle | None] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )
    github_issue: Mapped[GitHubIssueLink | None] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )


class TriageJob(Base):
    __tablename__ = "triage_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.PENDING.value, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    incident: Mapped[Incident] = relationship(back_populates="jobs")


class EvidenceBundle(Base):
    __tablename__ = "evidence_bundles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), unique=True, index=True)
    logfire: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    codebase: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    agent_report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    incident: Mapped[Incident] = relationship(back_populates="evidence_bundle")


class GitHubIssueLink(Base):
    __tablename__ = "github_issue_links"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), unique=True, index=True)
    repo: Mapped[str] = mapped_column(String(256))
    issue_number: Mapped[int] = mapped_column(Integer)
    issue_url: Mapped[str] = mapped_column(String(1024))
    state: Mapped[str] = mapped_column(String(64), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    incident: Mapped[Incident] = relationship(back_populates="github_issue")
