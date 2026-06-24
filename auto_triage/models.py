from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid6 import uuid7

from auto_triage.database import Base


def new_id() -> str:
    return uuid7().hex


class IncidentStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    ISSUE_OPENED = "issue_opened"
    ISSUE_UPDATED = "issue_updated"
    PULL_REQUEST_OPENED = "pull_request_opened"
    PULL_REQUEST_UPDATED = "pull_request_updated"
    FAILED = "failed"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(256))
    slug: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    memberships: Mapped[list[OrganizationMembership]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    repository_configs: Mapped[list[UserRepositoryConfig]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    environment_settings: Mapped[OrganizationEnvironmentSettings | None] = relationship(
        back_populates="organization", cascade="all, delete-orphan", uselist=False
    )
    setup_outputs: Mapped[OrganizationSetupOutputs | None] = relationship(
        back_populates="organization", cascade="all, delete-orphan", uselist=False
    )
    environment_variables: Mapped[list[OrganizationEnvironmentVariable]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class OrganizationMembership(Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_membership_org_user"),
        CheckConstraint("role IN ('admin', 'write', 'read')", name="ck_org_membership_role"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("triage_users.id"), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(64), default="read", server_default="read", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[TriageUser] = relationship(back_populates="organization_memberships")


class TriageUser(Base):
    __tablename__ = "triage_users"
    __table_args__ = (
        CheckConstraint("platform_role IN ('admin', 'user')", name="ck_triage_users_platform_role"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    github_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    github_login: Mapped[str | None] = mapped_column(String(256), nullable=True)
    github_avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    platform_role: Mapped[str] = mapped_column(String(64), default="user", server_default="user")
    password_hash: Mapped[str] = mapped_column(String(512))
    auth_token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    repository_config: Mapped[UserRepositoryConfig | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    organization_memberships: Mapped[list[OrganizationMembership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    updated_environment_variables: Mapped[list[OrganizationEnvironmentVariable]] = relationship(
        back_populates="updated_by_user"
    )


class UserRepositoryConfig(Base):
    __tablename__ = "user_repository_configs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("triage_users.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    webhook_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=new_id)
    github_owner: Mapped[str] = mapped_column(String(128))
    github_repo_name: Mapped[str] = mapped_column(String(128))
    github_token: Mapped[str] = mapped_column(Text)
    github_default_branch: Mapped[str] = mapped_column(String(256), default="main")
    target_repo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    logfire_base_url: Mapped[str] = mapped_column(
        String(512), default="https://logfire-us.pydantic.dev"
    )
    logfire_read_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    logfire_project_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    logfire_service_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    logfire_route: Mapped[str | None] = mapped_column(String(512), nullable=True)
    alert_trigger: Mapped[str] = mapped_column(String(64), default="http_5xx")
    alert_mode: Mapped[str] = mapped_column(String(64), default="starts_having_results")
    ai_provider: Mapped[str] = mapped_column(String(32), default="azure")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[TriageUser] = relationship(back_populates="repository_config")
    organization: Mapped[Organization] = relationship(back_populates="repository_configs")


class OrganizationEnvironmentSettings(Base):
    __tablename__ = "organization_environment_settings"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_org_env_settings_org"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    api_base_url: Mapped[str] = mapped_column(String(1024), default="http://127.0.0.1:8001")
    public_webhook_base_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    logfire_region: Mapped[str] = mapped_column(String(16), default="us")
    alert_window_minutes: Mapped[int] = mapped_column(Integer, default=10)
    openai_model: Mapped[str] = mapped_column(String(256), default="openai:gpt-4.1-mini")
    openai_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    azure_openai_endpoint: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    azure_openai_deployment: Mapped[str | None] = mapped_column(String(256), nullable=True)
    azure_openai_api_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    azure_openai_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    postgres_host: Mapped[str | None] = mapped_column(String(256), nullable=True)
    postgres_port: Mapped[int] = mapped_column(Integer, default=5432)
    postgres_user: Mapped[str | None] = mapped_column(String(256), nullable=True)
    postgres_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    postgres_db: Mapped[str | None] = mapped_column(String(256), nullable=True)
    redis_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    redis_host: Mapped[str | None] = mapped_column(String(256), nullable=True)
    redis_port: Mapped[int] = mapped_column(Integer, default=6379)
    redis_username: Mapped[str | None] = mapped_column(String(256), nullable=True)
    redis_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    redis_ttl_seconds: Mapped[int] = mapped_column(Integer, default=300)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped[Organization] = relationship(back_populates="environment_settings")


class OrganizationSetupOutputs(Base):
    __tablename__ = "organization_setup_outputs"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_org_setup_outputs_org"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    webhook_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    env_file: Mapped[str] = mapped_column(Text, default="", server_default="")
    logfire_query: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped[Organization] = relationship(back_populates="setup_outputs")


class OrganizationEnvironmentVariable(Base):
    __tablename__ = "organization_environment_variables"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_org_environment_variable_name"),
        CheckConstraint(
            "NOT sensitive OR value = ''",
            name="ck_org_environment_variables_sensitive_plaintext",
        ),
        CheckConstraint(
            "encrypted_value IS NULL OR sensitive",
            name="ck_org_environment_variables_encrypted_sensitive",
        ),
        CheckConstraint(
            "encrypted_value IS NULL OR encryption_provider = 'openbao'",
            name="ck_org_environment_variables_encryption_provider",
        ),
        ForeignKeyConstraint(
            ["organization_id", "updated_by_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            name="fk_org_environment_variables_membership",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    updated_by_user_id: Mapped[str] = mapped_column(ForeignKey("triage_users.id"), index=True)
    name: Mapped[str] = mapped_column(String(256))
    value: Mapped[str] = mapped_column(Text, default="", server_default="")
    encrypted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    encryption_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    encryption_key_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped[Organization] = relationship(back_populates="environment_variables")
    updated_by_user: Mapped[TriageUser] = relationship(
        back_populates="updated_environment_variables"
    )


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    user_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_repository_configs.id"), nullable=True, index=True
    )
    webhook_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(64), default="logfire", index=True)
    alert_kind: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    service_name: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    route: Mapped[str | None] = mapped_column(String(512), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    exception_type: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=IncidentStatus.QUEUED.value, index=True)
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
    github_pull_request: Mapped[GitHubPullRequestLink | None] = relationship(
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


class GitHubPullRequestLink(Base):
    __tablename__ = "github_pull_request_links"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), unique=True, index=True)
    repo: Mapped[str] = mapped_column(String(256))
    branch: Mapped[str] = mapped_column(String(256))
    base_branch: Mapped[str] = mapped_column(String(256))
    pull_number: Mapped[int] = mapped_column(Integer)
    pull_url: Mapped[str] = mapped_column(String(1024))
    state: Mapped[str] = mapped_column(String(64), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    incident: Mapped[Incident] = relationship(back_populates="github_pull_request")
