from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auto_triage.cache import CacheClient
from auto_triage.config import Settings
from auto_triage.database import get_session
from auto_triage.models import (
    Organization,
    OrganizationEnvironmentSettings,
    OrganizationMembership,
    OrganizationSetupOutputs,
    TriageUser,
    UserRepositoryConfig,
    new_id,
)
from auto_triage.schemas import (
    AuthLoginIn,
    AuthLoginOut,
    OrganizationEnvironmentSettingsIn,
    OrganizationEnvironmentSettingsOut,
    OrganizationMemberCreateIn,
    OrganizationMemberOut,
    OrganizationRegisterIn,
    OrganizationRole,
    SetupOutputsIn,
    SetupOutputsOut,
    UserRepositoryConfigIn,
    UserRepositoryConfigOut,
)
from auto_triage.security import hash_password, new_token, token_hash, verify_password

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ADMIN_ROLE: OrganizationRole = "admin"
WRITE_ROLES = {"admin", "write"}


@dataclass(slots=True)
class RepositoryConfigSnapshot:
    id: str
    user_id: str
    organization_id: str
    webhook_id: str
    github_owner: str
    github_repo_name: str
    github_token: str
    github_default_branch: str
    target_repo_url: str | None
    logfire_base_url: str
    logfire_read_token: str | None
    logfire_project_url: str | None
    logfire_service_name: str | None
    logfire_route: str | None
    alert_trigger: str
    alert_mode: str
    ai_provider: str
    created_at: datetime | str | None
    updated_at: datetime | str | None


@dataclass(slots=True)
class OrganizationEnvironmentSettingsSnapshot:
    id: str
    organization_id: str
    api_base_url: str
    public_webhook_base_url: str | None
    logfire_region: str
    alert_window_minutes: int
    openai_model: str
    openai_api_key: str | None
    azure_openai_endpoint: str | None
    azure_openai_deployment: str | None
    azure_openai_api_version: str | None
    azure_openai_api_key: str | None
    postgres_host: str | None
    postgres_port: int
    postgres_user: str | None
    postgres_password: str | None
    postgres_db: str | None
    redis_enabled: bool
    redis_host: str | None
    redis_port: int
    redis_username: str | None
    redis_password: str | None
    redis_ttl_seconds: int
    created_at: datetime | str | None
    updated_at: datetime | str | None


RepositoryConfigLike = UserRepositoryConfig | RepositoryConfigSnapshot
OrganizationEnvironmentSettingsLike = (
    OrganizationEnvironmentSettings | OrganizationEnvironmentSettingsSnapshot
)


async def login_or_register_user(
    session: AsyncSession,
    payload: AuthLoginIn,
) -> AuthLoginOut:
    email = payload.email.lower().strip()
    result = await session.execute(select(TriageUser).where(TriageUser.email == email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid login")

    membership = await _membership_for_user(session, user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization registration is required before login",
        )

    token = new_token()
    user.auth_token_hash = token_hash(token)
    if payload.display_name:
        user.display_name = payload.display_name
    await session.commit()
    await session.refresh(user)
    return _auth_response(user, token, membership)


async def register_organization(
    session: AsyncSession,
    payload: OrganizationRegisterIn,
) -> AuthLoginOut:
    email = payload.email.lower().strip()
    result = await session.execute(select(TriageUser).where(TriageUser.email == email))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    organization_id = new_id()
    token = new_token()
    organization = Organization(
        id=organization_id,
        name=payload.organization_name.strip(),
        slug=_organization_slug(payload.organization_name, organization_id),
    )
    user = TriageUser(
        email=email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        auth_token_hash=token_hash(token),
    )
    session.add_all([organization, user])
    await session.flush()
    membership = OrganizationMembership(
        organization_id=organization.id,
        user_id=user.id,
        role=ADMIN_ROLE,
    )
    membership.organization = organization
    membership.user = user
    session.add(membership)
    await session.commit()
    return _auth_response(user, token, membership)


async def current_user(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> TriageUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    result = await session.execute(
        select(TriageUser)
        .where(TriageUser.auth_token_hash == token_hash(token))
        .options(
            selectinload(TriageUser.repository_config),
            selectinload(TriageUser.organization_memberships).selectinload(
                OrganizationMembership.organization
            ),
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
    if not user.organization_memberships:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is not assigned to an organization",
        )
    return user


async def list_organization_members(
    session: AsyncSession,
    user: TriageUser,
) -> list[OrganizationMemberOut]:
    membership = _primary_membership(user)
    result = await session.execute(
        select(OrganizationMembership)
        .where(OrganizationMembership.organization_id == membership.organization_id)
        .options(selectinload(OrganizationMembership.user))
        .order_by(OrganizationMembership.created_at)
    )
    return [organization_member_response(member) for member in result.scalars().all()]


async def add_organization_member(
    session: AsyncSession,
    admin_user: TriageUser,
    payload: OrganizationMemberCreateIn,
) -> OrganizationMemberOut:
    admin_membership = ensure_admin(admin_user)
    email = payload.email.lower().strip()
    result = await session.execute(select(TriageUser).where(TriageUser.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        if not payload.password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password is required when adding a new user",
            )
        user = TriageUser(
            email=email,
            display_name=payload.display_name,
            password_hash=hash_password(payload.password),
            auth_token_hash=token_hash(new_token()),
        )
        session.add(user)
        await session.flush()
    elif payload.display_name:
        user.display_name = payload.display_name

    result = await session.execute(
        select(OrganizationMembership)
        .where(OrganizationMembership.user_id == user.id)
        .options(selectinload(OrganizationMembership.user))
    )
    membership = result.scalar_one_or_none()
    if membership is not None and membership.organization_id != admin_membership.organization_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already belongs to another organization",
        )

    if membership is None:
        membership = OrganizationMembership(
            organization_id=admin_membership.organization_id,
            user_id=user.id,
            role=payload.role,
        )
        membership.user = user
        session.add(membership)
    else:
        membership.role = payload.role

    await session.commit()
    await session.refresh(membership)
    membership.user = user
    return organization_member_response(membership)


async def get_setup_outputs(
    session: AsyncSession,
    user: TriageUser,
) -> SetupOutputsOut | None:
    organization_id = _primary_membership(user).organization_id
    result = await session.execute(
        select(OrganizationSetupOutputs).where(
            OrganizationSetupOutputs.organization_id == organization_id
        )
    )
    outputs = result.scalar_one_or_none()
    return setup_outputs_response(outputs)


async def upsert_setup_outputs(
    session: AsyncSession,
    user: TriageUser,
    payload: SetupOutputsIn,
) -> SetupOutputsOut:
    from auto_triage.organization_environment import redact_env_file

    organization_id = ensure_write_access(user).organization_id
    result = await session.execute(
        select(OrganizationSetupOutputs).where(
            OrganizationSetupOutputs.organization_id == organization_id
        )
    )
    outputs = result.scalar_one_or_none()
    if outputs is None:
        outputs = OrganizationSetupOutputs(organization_id=organization_id)
        session.add(outputs)

    outputs.webhook_url = payload.webhook_url
    outputs.env_file = redact_env_file(payload.env_file)
    outputs.logfire_query = payload.logfire_query

    await session.commit()
    await session.refresh(outputs)
    return setup_outputs_response(outputs)


async def get_user_config_by_webhook(
    session: AsyncSession,
    webhook_id: str,
    settings: Settings | None = None,
) -> RepositoryConfigSnapshot:
    cached = await _read_cached_repository_config_by_webhook(settings, webhook_id)
    if cached is not None:
        return cached

    result = await session.execute(
        select(UserRepositoryConfig).where(UserRepositoryConfig.webhook_id == webhook_id)
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    snapshot = _snapshot_repository_config(config)
    await _write_repository_config_cache(settings, snapshot)
    return snapshot


async def get_user_config_by_id(
    session: AsyncSession,
    config_id: str | None,
    settings: Settings | None = None,
) -> RepositoryConfigSnapshot | None:
    if not config_id:
        return None
    cached = await _read_cached_repository_config_by_id(settings, config_id)
    if cached is not None:
        return cached

    config = await session.get(UserRepositoryConfig, config_id)
    if config is None:
        return None
    snapshot = _snapshot_repository_config(config)
    await _write_repository_config_cache(settings, snapshot)
    return snapshot


async def get_organization_settings_for_config(
    session: AsyncSession,
    config: RepositoryConfigLike | None,
    settings: Settings | None = None,
) -> OrganizationEnvironmentSettingsSnapshot | None:
    if config is None:
        return None
    cached = await _read_cached_organization_settings(settings, config.organization_id)
    if cached is not None:
        return cached

    result = await session.execute(
        select(OrganizationEnvironmentSettings).where(
            OrganizationEnvironmentSettings.organization_id == config.organization_id
        )
    )
    organization_settings = result.scalar_one_or_none()
    if organization_settings is None:
        return None
    snapshot = _snapshot_organization_settings(organization_settings)
    await _write_organization_settings_cache(settings, snapshot)
    return snapshot


async def get_organization_environment_settings(
    session: AsyncSession,
    user: TriageUser,
) -> OrganizationEnvironmentSettingsOut | None:
    organization_id = _primary_membership(user).organization_id
    result = await session.execute(
        select(OrganizationEnvironmentSettings).where(
            OrganizationEnvironmentSettings.organization_id == organization_id
        )
    )
    return organization_environment_settings_response(result.scalar_one_or_none())


async def upsert_organization_environment_settings(
    session: AsyncSession,
    user: TriageUser,
    payload: OrganizationEnvironmentSettingsIn,
    settings: Settings,
) -> OrganizationEnvironmentSettingsOut:

    organization_id = ensure_write_access(user).organization_id
    result = await session.execute(
        select(OrganizationEnvironmentSettings).where(
            OrganizationEnvironmentSettings.organization_id == organization_id
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        config = OrganizationEnvironmentSettings(organization_id=organization_id)
        session.add(config)

    config.api_base_url = payload.api_base_url
    config.public_webhook_base_url = payload.public_webhook_base_url
    config.logfire_region = payload.logfire_region
    config.alert_window_minutes = payload.alert_window_minutes
    config.openai_model = payload.openai_model
    config.azure_openai_endpoint = payload.azure_openai_endpoint
    config.azure_openai_deployment = payload.azure_openai_deployment
    config.azure_openai_api_version = payload.azure_openai_api_version
    config.postgres_host = payload.postgres_host
    config.postgres_port = payload.postgres_port
    config.postgres_user = payload.postgres_user
    config.postgres_db = payload.postgres_db
    config.redis_enabled = payload.redis_enabled
    config.redis_host = payload.redis_host
    config.redis_port = payload.redis_port
    config.redis_username = payload.redis_username
    config.redis_ttl_seconds = payload.redis_ttl_seconds

    config.openai_api_key = await _updated_secret(
        settings,
        organization_id,
        config.openai_api_key,
        payload.openai_api_key,
        payload.openai_api_key_unchanged,
    )
    config.azure_openai_api_key = await _updated_secret(
        settings,
        organization_id,
        config.azure_openai_api_key,
        payload.azure_openai_api_key,
        payload.azure_openai_api_key_unchanged,
    )
    config.postgres_password = await _updated_secret(
        settings,
        organization_id,
        config.postgres_password,
        payload.postgres_password,
        payload.postgres_password_unchanged,
    )
    config.redis_password = await _updated_secret(
        settings,
        organization_id,
        config.redis_password,
        payload.redis_password,
        payload.redis_password_unchanged,
    )

    await session.commit()
    await session.refresh(config)
    await invalidate_organization_settings_cache(settings, organization_id)
    response = organization_environment_settings_response(config)
    assert response is not None
    return response


async def upsert_repository_config(
    session: AsyncSession,
    user: TriageUser,
    payload: UserRepositoryConfigIn,
    settings: Settings | None = None,
) -> UserRepositoryConfigOut:
    organization_id = ensure_write_access(user).organization_id
    config = user.repository_config
    if config is None:
        config = UserRepositoryConfig(user_id=user.id, organization_id=organization_id)
        session.add(config)
    else:
        config.organization_id = organization_id

    if config.id is None and not payload.github_token:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="GitHub token is required for initial repository setup",
        )

    config.github_owner = payload.github_owner
    config.github_repo_name = payload.github_repo_name
    config.github_token = (
        await _updated_secret(
            settings,
            organization_id,
            config.github_token,
            payload.github_token,
            payload.github_token_unchanged,
        )
        or ""
    )
    config.github_default_branch = payload.github_default_branch
    config.target_repo_url = payload.target_repo_url
    config.logfire_base_url = payload.logfire_base_url.rstrip("/")
    config.logfire_read_token = await _updated_secret(
        settings,
        organization_id,
        config.logfire_read_token,
        payload.logfire_read_token,
        payload.logfire_read_token_unchanged,
    )
    config.logfire_project_url = payload.logfire_project_url
    config.logfire_service_name = payload.logfire_service_name
    config.logfire_route = payload.logfire_route
    config.alert_trigger = payload.alert_trigger
    config.alert_mode = payload.alert_mode
    config.ai_provider = payload.ai_provider

    await session.commit()
    await session.refresh(config)
    await invalidate_repository_config_cache(settings, config)
    return repository_config_response(config)


def repository_config_response(
    config: RepositoryConfigLike | None,
) -> UserRepositoryConfigOut | None:
    if config is None:
        return None
    repo = f"{config.github_owner}/{config.github_repo_name}"
    return UserRepositoryConfigOut(
        id=config.id,
        organization_id=config.organization_id,
        webhook_id=config.webhook_id,
        webhook_path=f"/webhooks/users/{config.webhook_id}/logfire",
        github_owner=config.github_owner,
        github_repo_name=config.github_repo_name,
        github_repo=repo,
        github_default_branch=config.github_default_branch,
        target_repo_url=config.target_repo_url,
        github_token_configured=bool(config.github_token),
        logfire_base_url=config.logfire_base_url,
        logfire_read_token_configured=bool(config.logfire_read_token),
        logfire_project_url=config.logfire_project_url,
        logfire_service_name=config.logfire_service_name,
        logfire_route=config.logfire_route,
        alert_trigger=config.alert_trigger,
        alert_mode=config.alert_mode,
        ai_provider=config.ai_provider,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def organization_environment_settings_response(
    config: OrganizationEnvironmentSettingsLike | None,
) -> OrganizationEnvironmentSettingsOut | None:
    if config is None:
        return None
    return OrganizationEnvironmentSettingsOut(
        id=config.id,
        organization_id=config.organization_id,
        api_base_url=config.api_base_url,
        public_webhook_base_url=config.public_webhook_base_url,
        logfire_region=config.logfire_region,
        alert_window_minutes=config.alert_window_minutes,
        openai_model=config.openai_model,
        openai_api_key_configured=bool(config.openai_api_key),
        azure_openai_endpoint=config.azure_openai_endpoint,
        azure_openai_deployment=config.azure_openai_deployment,
        azure_openai_api_version=config.azure_openai_api_version,
        azure_openai_api_key_configured=bool(config.azure_openai_api_key),
        postgres_host=config.postgres_host,
        postgres_port=config.postgres_port,
        postgres_user=config.postgres_user,
        postgres_password_configured=bool(config.postgres_password),
        postgres_db=config.postgres_db,
        redis_enabled=config.redis_enabled,
        redis_host=config.redis_host,
        redis_port=config.redis_port,
        redis_username=config.redis_username,
        redis_password_configured=bool(config.redis_password),
        redis_ttl_seconds=config.redis_ttl_seconds,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def settings_for_repository_config(
    base_settings: Settings,
    config: RepositoryConfigLike | None,
    environment_settings: OrganizationEnvironmentSettingsLike | None = None,
    runtime_environment: dict[str, str] | None = None,
) -> Settings:
    if config is None:
        return base_settings

    updates = {
        "github_repo": f"{config.github_owner}/{config.github_repo_name}",
        "github_token": SecretStr(config.github_token),
        "github_default_branch": config.github_default_branch,
        "target_repo_url": config.target_repo_url
        or f"https://github.com/{config.github_owner}/{config.github_repo_name}.git",
        "logfire_base_url": config.logfire_base_url,
        "logfire_read_token": SecretStr(config.logfire_read_token)
        if config.logfire_read_token
        else base_settings.logfire_read_token,
        "logfire_project_url": config.logfire_project_url,
    }
    if environment_settings is not None:
        updates.update(
            {
                "triage_model": environment_settings.openai_model,
                "openai_api_key": SecretStr(environment_settings.openai_api_key)
                if environment_settings.openai_api_key
                else base_settings.openai_api_key,
                "azure_openai_endpoint": environment_settings.azure_openai_endpoint
                or base_settings.azure_openai_endpoint,
                "azure_openai_api_key": SecretStr(environment_settings.azure_openai_api_key)
                if environment_settings.azure_openai_api_key
                else base_settings.azure_openai_api_key,
                "azure_openai_api_version": environment_settings.azure_openai_api_version
                or base_settings.azure_openai_api_version,
                "azure_openai_deployment": environment_settings.azure_openai_deployment
                or base_settings.azure_openai_deployment,
                "redis_cache_enabled": environment_settings.redis_enabled,
                "redis_host": environment_settings.redis_host or base_settings.redis_host,
                "redis_port": environment_settings.redis_port,
                "redis_username": environment_settings.redis_username
                or base_settings.redis_username,
                "redis_password": SecretStr(environment_settings.redis_password)
                if environment_settings.redis_password
                else base_settings.redis_password,
                "redis_cache_ttl_seconds": environment_settings.redis_ttl_seconds,
            }
        )
    if runtime_environment:
        from auto_triage.organization_environment import apply_runtime_environment

        apply_runtime_environment(updates, runtime_environment)

    return base_settings.model_copy(update=updates)


async def _updated_secret(
    settings: Settings | None,
    organization_id: str,
    existing_value: str | None,
    submitted_value: str | None,
    unchanged: bool,
) -> str | None:
    if unchanged:
        return existing_value
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Secret encryption is unavailable",
        )
    from auto_triage.organization_environment import encrypt_secret_for_storage
    from auto_triage.services.openbao import OpenBaoError

    try:
        return await encrypt_secret_for_storage(settings, organization_id, submitted_value)
    except OpenBaoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Secret encryption service is unavailable",
        ) from exc


async def invalidate_repository_config_cache(
    settings: Settings | None,
    config: RepositoryConfigLike,
) -> None:
    cache = _cache(settings)
    if cache is None:
        return
    await cache.delete(
        _repository_config_cache_key_by_id(config.id),
        _repository_config_cache_key_by_webhook(config.webhook_id),
    )


async def invalidate_organization_settings_cache(
    settings: Settings | None,
    organization_id: str,
) -> None:
    cache = _cache(settings)
    if cache is None:
        return
    await cache.delete(_organization_settings_cache_key(organization_id))


def ensure_admin(user: TriageUser) -> OrganizationMembership:
    membership = _primary_membership(user)
    if _normalized_role(membership.role) != ADMIN_ROLE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization admin role is required",
        )
    return membership


def ensure_write_access(user: TriageUser) -> OrganizationMembership:
    membership = _primary_membership(user)
    if _normalized_role(membership.role) not in WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization write role is required",
        )
    return membership


def organization_member_response(member: OrganizationMembership) -> OrganizationMemberOut:
    return OrganizationMemberOut(
        membership_id=member.id,
        user_id=member.user_id,
        organization_id=member.organization_id,
        email=member.user.email,
        display_name=member.user.display_name,
        role=_normalized_role(member.role),
        created_at=member.created_at,
        updated_at=member.updated_at,
    )


def setup_outputs_response(outputs: OrganizationSetupOutputs | None) -> SetupOutputsOut | None:
    if outputs is None:
        return None
    return SetupOutputsOut(
        id=outputs.id,
        organization_id=outputs.organization_id,
        webhook_url=outputs.webhook_url,
        env_file=outputs.env_file,
        logfire_query=outputs.logfire_query,
        created_at=outputs.created_at,
        updated_at=outputs.updated_at,
    )


def _auth_response(
    user: TriageUser,
    token: str,
    membership: OrganizationMembership,
) -> AuthLoginOut:
    organization = membership.organization
    return AuthLoginOut(
        user_id=user.id,
        organization_id=membership.organization_id,
        organization_name=organization.name,
        organization_slug=organization.slug,
        role=_normalized_role(membership.role),
        email=user.email,
        display_name=user.display_name,
        auth_token=token,
    )


async def _membership_for_user(
    session: AsyncSession,
    user_id: str,
) -> OrganizationMembership | None:
    result = await session.execute(
        select(OrganizationMembership)
        .where(OrganizationMembership.user_id == user_id)
        .options(selectinload(OrganizationMembership.organization))
        .order_by(OrganizationMembership.created_at)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _primary_organization_id(session: AsyncSession, user: TriageUser) -> str:
    membership = _primary_membership_from_user(user)
    if membership is None:
        membership = await _membership_for_user(session, user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is not assigned to an organization",
        )
    return membership.organization_id


def _primary_membership(user: TriageUser) -> OrganizationMembership:
    membership = _primary_membership_from_user(user)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is not assigned to an organization",
        )
    return membership


def _primary_membership_from_user(user: TriageUser) -> OrganizationMembership | None:
    memberships = getattr(user, "organization_memberships", None) or []
    if memberships:
        return memberships[0]
    return None


def _normalized_role(role: str) -> OrganizationRole:
    if role == "owner":
        return ADMIN_ROLE
    if role in ("admin", "write", "read"):
        return role
    return "read"


def _organization_slug(name: str, organization_id: str) -> str:
    prefix = name.strip().lower() or "organization"
    slug = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-") or "org"
    return f"{slug}-{organization_id[:8]}"


async def _read_cached_repository_config_by_webhook(
    settings: Settings | None,
    webhook_id: str,
) -> RepositoryConfigSnapshot | None:
    payload = await _read_cache(settings, _repository_config_cache_key_by_webhook(webhook_id))
    return _snapshot_from_payload(RepositoryConfigSnapshot, payload)


async def _read_cached_repository_config_by_id(
    settings: Settings | None,
    config_id: str,
) -> RepositoryConfigSnapshot | None:
    payload = await _read_cache(settings, _repository_config_cache_key_by_id(config_id))
    return _snapshot_from_payload(RepositoryConfigSnapshot, payload)


async def _read_cached_organization_settings(
    settings: Settings | None,
    organization_id: str,
) -> OrganizationEnvironmentSettingsSnapshot | None:
    payload = await _read_cache(settings, _organization_settings_cache_key(organization_id))
    return _snapshot_from_payload(OrganizationEnvironmentSettingsSnapshot, payload)


async def _write_repository_config_cache(
    settings: Settings | None,
    config: RepositoryConfigSnapshot,
) -> None:
    cache = _cache(settings)
    if cache is None:
        return
    payload = asdict(config)
    ttl_seconds = _config_cache_ttl(settings)
    await cache.set_json(_repository_config_cache_key_by_id(config.id), payload, ttl_seconds)
    await cache.set_json(
        _repository_config_cache_key_by_webhook(config.webhook_id), payload, ttl_seconds
    )


async def _write_organization_settings_cache(
    settings: Settings | None,
    organization_settings: OrganizationEnvironmentSettingsSnapshot,
) -> None:
    cache = _cache(settings)
    if cache is None:
        return
    await cache.set_json(
        _organization_settings_cache_key(organization_settings.organization_id),
        asdict(organization_settings),
        _config_cache_ttl(settings),
    )


async def _read_cache(settings: Settings | None, key: str) -> dict | None:
    cache = _cache(settings)
    if cache is None:
        return None
    return await cache.get_json(key)


def _cache(settings: Settings | None) -> CacheClient | None:
    if settings is None or not settings.redis_cache_enabled:
        return None
    return CacheClient(settings)


def _config_cache_ttl(settings: Settings | None) -> int:
    if settings is None:
        return 0
    return max(0, min(settings.redis_cache_ttl_seconds, 300))


def _repository_config_cache_key_by_id(config_id: str) -> str:
    return f"auto-triage:repository-config:id:{config_id}"


def _repository_config_cache_key_by_webhook(webhook_id: str) -> str:
    return f"auto-triage:repository-config:webhook:{webhook_id}"


def _organization_settings_cache_key(organization_id: str) -> str:
    return f"auto-triage:organization-settings:{organization_id}"


def _snapshot_repository_config(config: UserRepositoryConfig) -> RepositoryConfigSnapshot:
    return RepositoryConfigSnapshot(
        id=config.id,
        user_id=config.user_id,
        organization_id=config.organization_id,
        webhook_id=config.webhook_id,
        github_owner=config.github_owner,
        github_repo_name=config.github_repo_name,
        github_token=config.github_token,
        github_default_branch=config.github_default_branch,
        target_repo_url=config.target_repo_url,
        logfire_base_url=config.logfire_base_url,
        logfire_read_token=config.logfire_read_token,
        logfire_project_url=config.logfire_project_url,
        logfire_service_name=config.logfire_service_name,
        logfire_route=config.logfire_route,
        alert_trigger=config.alert_trigger,
        alert_mode=config.alert_mode,
        ai_provider=config.ai_provider,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def _snapshot_organization_settings(
    organization_settings: OrganizationEnvironmentSettings,
) -> OrganizationEnvironmentSettingsSnapshot:
    return OrganizationEnvironmentSettingsSnapshot(
        id=organization_settings.id,
        organization_id=organization_settings.organization_id,
        api_base_url=organization_settings.api_base_url,
        public_webhook_base_url=organization_settings.public_webhook_base_url,
        logfire_region=organization_settings.logfire_region,
        alert_window_minutes=organization_settings.alert_window_minutes,
        openai_model=organization_settings.openai_model,
        openai_api_key=organization_settings.openai_api_key,
        azure_openai_endpoint=organization_settings.azure_openai_endpoint,
        azure_openai_deployment=organization_settings.azure_openai_deployment,
        azure_openai_api_version=organization_settings.azure_openai_api_version,
        azure_openai_api_key=organization_settings.azure_openai_api_key,
        postgres_host=organization_settings.postgres_host,
        postgres_port=organization_settings.postgres_port,
        postgres_user=organization_settings.postgres_user,
        postgres_password=organization_settings.postgres_password,
        postgres_db=organization_settings.postgres_db,
        redis_enabled=organization_settings.redis_enabled,
        redis_host=organization_settings.redis_host,
        redis_port=organization_settings.redis_port,
        redis_username=organization_settings.redis_username,
        redis_password=organization_settings.redis_password,
        redis_ttl_seconds=organization_settings.redis_ttl_seconds,
        created_at=organization_settings.created_at,
        updated_at=organization_settings.updated_at,
    )


def _snapshot_from_payload[T](snapshot_type: type[T], payload: dict | None) -> T | None:
    if not payload:
        return None
    field_names = {field.name for field in fields(snapshot_type)}
    try:
        return snapshot_type(**{name: payload.get(name) for name in field_names})
    except TypeError:
        return None
