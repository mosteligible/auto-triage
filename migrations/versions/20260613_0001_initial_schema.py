"""Initial schema with organizations, users, and triage tables.

Revision ID: 20260613_0001
Revises:
Create Date: 2026-06-13 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260613_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("slug", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(op.f("ix_organizations_slug"), "organizations", ["slug"], unique=True)

    op.create_table(
        "triage_users",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=True),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("auth_token_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("auth_token_hash"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(
        op.f("ix_triage_users_auth_token_hash"),
        "triage_users",
        ["auth_token_hash"],
        unique=True,
    )
    op.create_index(op.f("ix_triage_users_email"), "triage_users", ["email"], unique=True)

    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("organization_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["triage_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_org_membership_org_user"),
    )
    op.create_index(
        op.f("ix_organization_memberships_organization_id"),
        "organization_memberships",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_organization_memberships_role"),
        "organization_memberships",
        ["role"],
    )
    op.create_index(
        op.f("ix_organization_memberships_user_id"),
        "organization_memberships",
        ["user_id"],
    )

    op.create_table(
        "user_repository_configs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("organization_id", sa.String(length=32), nullable=False),
        sa.Column("webhook_id", sa.String(length=64), nullable=False),
        sa.Column("github_owner", sa.String(length=128), nullable=False),
        sa.Column("github_repo_name", sa.String(length=128), nullable=False),
        sa.Column("github_token", sa.Text(), nullable=False),
        sa.Column("github_default_branch", sa.String(length=256), nullable=False),
        sa.Column("target_repo_url", sa.String(length=1024), nullable=True),
        sa.Column("logfire_base_url", sa.String(length=512), nullable=False),
        sa.Column("logfire_read_token", sa.Text(), nullable=True),
        sa.Column("logfire_project_url", sa.String(length=1024), nullable=True),
        sa.Column("logfire_service_name", sa.String(length=256), nullable=True),
        sa.Column("logfire_route", sa.String(length=512), nullable=True),
        sa.Column("alert_trigger", sa.String(length=64), nullable=False),
        sa.Column("alert_mode", sa.String(length=64), nullable=False),
        sa.Column("ai_provider", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["triage_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        sa.UniqueConstraint("webhook_id"),
    )
    op.create_index(
        op.f("ix_user_repository_configs_organization_id"),
        "user_repository_configs",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_user_repository_configs_user_id"),
        "user_repository_configs",
        ["user_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_user_repository_configs_webhook_id"),
        "user_repository_configs",
        ["webhook_id"],
        unique=True,
    )

    op.create_table(
        "incidents",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("organization_id", sa.String(length=32), nullable=True),
        sa.Column("user_config_id", sa.String(length=32), nullable=True),
        sa.Column("webhook_id", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("alert_kind", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("service_name", sa.String(length=256), nullable=True),
        sa.Column("route", sa.String(length=512), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("exception_type", sa.String(length=256), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("normalized", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_config_id"], ["user_repository_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_incidents_alert_kind"), "incidents", ["alert_kind"])
    op.create_index(op.f("ix_incidents_fingerprint"), "incidents", ["fingerprint"])
    op.create_index(op.f("ix_incidents_organization_id"), "incidents", ["organization_id"])
    op.create_index(op.f("ix_incidents_service_name"), "incidents", ["service_name"])
    op.create_index(op.f("ix_incidents_source"), "incidents", ["source"])
    op.create_index(op.f("ix_incidents_status"), "incidents", ["status"])
    op.create_index(op.f("ix_incidents_trace_id"), "incidents", ["trace_id"])
    op.create_index(op.f("ix_incidents_user_config_id"), "incidents", ["user_config_id"])
    op.create_index(op.f("ix_incidents_webhook_id"), "incidents", ["webhook_id"])

    op.create_table(
        "triage_jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("incident_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_triage_jobs_incident_id"), "triage_jobs", ["incident_id"])
    op.create_index(op.f("ix_triage_jobs_status"), "triage_jobs", ["status"])

    op.create_table(
        "evidence_bundles",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("incident_id", sa.String(length=32), nullable=False),
        sa.Column("logfire", sa.JSON(), nullable=False),
        sa.Column("codebase", sa.JSON(), nullable=False),
        sa.Column("agent_report", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("incident_id"),
    )
    op.create_index(
        op.f("ix_evidence_bundles_incident_id"),
        "evidence_bundles",
        ["incident_id"],
        unique=True,
    )

    op.create_table(
        "github_issue_links",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("incident_id", sa.String(length=32), nullable=False),
        sa.Column("repo", sa.String(length=256), nullable=False),
        sa.Column("issue_number", sa.Integer(), nullable=False),
        sa.Column("issue_url", sa.String(length=1024), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("incident_id"),
    )
    op.create_index(
        op.f("ix_github_issue_links_incident_id"),
        "github_issue_links",
        ["incident_id"],
        unique=True,
    )

    op.create_table(
        "github_pull_request_links",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("incident_id", sa.String(length=32), nullable=False),
        sa.Column("repo", sa.String(length=256), nullable=False),
        sa.Column("branch", sa.String(length=256), nullable=False),
        sa.Column("base_branch", sa.String(length=256), nullable=False),
        sa.Column("pull_number", sa.Integer(), nullable=False),
        sa.Column("pull_url", sa.String(length=1024), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("incident_id"),
    )
    op.create_index(
        op.f("ix_github_pull_request_links_incident_id"),
        "github_pull_request_links",
        ["incident_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_github_pull_request_links_incident_id"), "github_pull_request_links")
    op.drop_table("github_pull_request_links")
    op.drop_index(op.f("ix_github_issue_links_incident_id"), "github_issue_links")
    op.drop_table("github_issue_links")
    op.drop_index(op.f("ix_evidence_bundles_incident_id"), "evidence_bundles")
    op.drop_table("evidence_bundles")
    op.drop_index(op.f("ix_triage_jobs_status"), "triage_jobs")
    op.drop_index(op.f("ix_triage_jobs_incident_id"), "triage_jobs")
    op.drop_table("triage_jobs")
    op.drop_index(op.f("ix_incidents_webhook_id"), "incidents")
    op.drop_index(op.f("ix_incidents_user_config_id"), "incidents")
    op.drop_index(op.f("ix_incidents_trace_id"), "incidents")
    op.drop_index(op.f("ix_incidents_status"), "incidents")
    op.drop_index(op.f("ix_incidents_source"), "incidents")
    op.drop_index(op.f("ix_incidents_service_name"), "incidents")
    op.drop_index(op.f("ix_incidents_organization_id"), "incidents")
    op.drop_index(op.f("ix_incidents_fingerprint"), "incidents")
    op.drop_index(op.f("ix_incidents_alert_kind"), "incidents")
    op.drop_table("incidents")
    op.drop_index(op.f("ix_user_repository_configs_webhook_id"), "user_repository_configs")
    op.drop_index(op.f("ix_user_repository_configs_user_id"), "user_repository_configs")
    op.drop_index(op.f("ix_user_repository_configs_organization_id"), "user_repository_configs")
    op.drop_table("user_repository_configs")
    op.drop_index(op.f("ix_organization_memberships_user_id"), "organization_memberships")
    op.drop_index(op.f("ix_organization_memberships_role"), "organization_memberships")
    op.drop_index(
        op.f("ix_organization_memberships_organization_id"),
        "organization_memberships",
    )
    op.drop_table("organization_memberships")
    op.drop_index(op.f("ix_triage_users_email"), "triage_users")
    op.drop_index(op.f("ix_triage_users_auth_token_hash"), "triage_users")
    op.drop_table("triage_users")
    op.drop_index(op.f("ix_organizations_slug"), "organizations")
    op.drop_table("organizations")
