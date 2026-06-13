from __future__ import annotations

import re
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auto_triage.config import Settings
from auto_triage.database import get_session
from auto_triage.models import (
    Organization,
    OrganizationMembership,
    TriageUser,
    UserEnvironmentSettings,
    UserRepositoryConfig,
)
from auto_triage.schemas import (
    AuthLoginIn,
    AuthLoginOut,
    UserRepositoryConfigIn,
    UserRepositoryConfigOut,
)
from auto_triage.security import hash_password, new_token, token_hash, verify_password

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def login_or_register_user(
    session: AsyncSession,
    payload: AuthLoginIn,
) -> AuthLoginOut:
    email = payload.email.lower().strip()
    result = await session.execute(select(TriageUser).where(TriageUser.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        token = new_token()
        user = TriageUser(
            email=email,
            display_name=payload.display_name,
            password_hash=hash_password(payload.password),
            auth_token_hash=token_hash(token),
        )
        session.add(user)
        await session.flush()
        organization = await _ensure_default_organization(session, user)
        await session.commit()
        await session.refresh(user)
        return _auth_response(user, token, organization.id)

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid login")

    token = new_token()
    user.auth_token_hash = token_hash(token)
    if payload.display_name:
        user.display_name = payload.display_name
    organization = await _ensure_default_organization(session, user)
    await session.commit()
    await session.refresh(user)
    return _auth_response(user, token, organization.id)


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
            selectinload(TriageUser.organization_memberships),
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
    if not user.organization_memberships:
        await _ensure_default_organization(session, user)
        await session.commit()
        result = await session.execute(
            select(TriageUser)
            .where(TriageUser.id == user.id)
            .options(
                selectinload(TriageUser.repository_config),
                selectinload(TriageUser.organization_memberships),
            )
        )
        user = result.scalar_one()
    return user


async def get_user_config_by_webhook(
    session: AsyncSession,
    webhook_id: str,
) -> UserRepositoryConfig:
    result = await session.execute(
        select(UserRepositoryConfig).where(UserRepositoryConfig.webhook_id == webhook_id)
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    return config


async def get_user_config_by_id(
    session: AsyncSession,
    config_id: str | None,
) -> UserRepositoryConfig | None:
    if not config_id:
        return None
    return await session.get(UserRepositoryConfig, config_id)


async def get_environment_settings_for_config(
    session: AsyncSession,
    config: UserRepositoryConfig | None,
) -> UserEnvironmentSettings | None:
    if config is None:
        return None
    result = await session.execute(
        select(UserEnvironmentSettings)
        .where(UserEnvironmentSettings.user_id == config.user_id)
        .where(UserEnvironmentSettings.organization_id == config.organization_id)
    )
    return result.scalar_one_or_none()


async def upsert_repository_config(
    session: AsyncSession,
    user: TriageUser,
    payload: UserRepositoryConfigIn,
) -> UserRepositoryConfigOut:
    organization_id = await _primary_organization_id(session, user)
    config = user.repository_config
    if config is None:
        config = UserRepositoryConfig(user_id=user.id, organization_id=organization_id)
        session.add(config)
    else:
        config.organization_id = organization_id

    config.github_owner = payload.github_owner
    config.github_repo_name = payload.github_repo_name
    config.github_token = payload.github_token
    config.github_default_branch = payload.github_default_branch
    config.target_repo_url = payload.target_repo_url
    config.logfire_base_url = payload.logfire_base_url.rstrip("/")
    config.logfire_read_token = payload.logfire_read_token
    config.logfire_project_url = payload.logfire_project_url
    config.logfire_service_name = payload.logfire_service_name
    config.logfire_route = payload.logfire_route
    config.alert_trigger = payload.alert_trigger
    config.alert_mode = payload.alert_mode
    config.ai_provider = payload.ai_provider

    await session.commit()
    await session.refresh(config)
    return repository_config_response(config)


def repository_config_response(
    config: UserRepositoryConfig | None,
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


def settings_for_repository_config(
    base_settings: Settings,
    config: UserRepositoryConfig | None,
    environment_settings: UserEnvironmentSettings | None = None,
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

    return base_settings.model_copy(update=updates)


def _auth_response(user: TriageUser, token: str, organization_id: str) -> AuthLoginOut:
    return AuthLoginOut(
        user_id=user.id,
        organization_id=organization_id,
        email=user.email,
        display_name=user.display_name,
        auth_token=token,
    )


async def _ensure_default_organization(
    session: AsyncSession,
    user: TriageUser,
) -> Organization:
    result = await session.execute(
        select(Organization)
        .join(OrganizationMembership)
        .where(OrganizationMembership.user_id == user.id)
        .order_by(Organization.created_at)
        .limit(1)
    )
    organization = result.scalar_one_or_none()
    if organization is not None:
        return organization

    organization = Organization(
        name=_default_organization_name(user),
        slug=_default_organization_slug(user),
    )
    session.add(organization)
    await session.flush()
    session.add(
        OrganizationMembership(
            organization_id=organization.id,
            user_id=user.id,
            role="owner",
        )
    )
    return organization


async def _primary_organization_id(session: AsyncSession, user: TriageUser) -> str:
    organization_id = _primary_organization_id_from_user(user)
    if organization_id:
        return organization_id
    organization = await _ensure_default_organization(session, user)
    return organization.id


def _primary_organization_id_from_user(user: TriageUser) -> str | None:
    memberships = getattr(user, "organization_memberships", None) or []
    if memberships:
        return memberships[0].organization_id
    return None


def _default_organization_name(user: TriageUser) -> str:
    if user.display_name:
        return f"{user.display_name} Organization"
    return f"{user.email} Organization"


def _default_organization_slug(user: TriageUser) -> str:
    prefix = user.email.split("@", 1)[0] or "org"
    slug = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-") or "org"
    return f"{slug}-{user.id[:8]}"
