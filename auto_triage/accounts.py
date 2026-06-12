from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auto_triage.config import Settings
from auto_triage.database import get_session
from auto_triage.models import TriageUser, UserRepositoryConfig
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
        await session.commit()
        await session.refresh(user)
        return _auth_response(user, token)

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid login")

    token = new_token()
    user.auth_token_hash = token_hash(token)
    if payload.display_name:
        user.display_name = payload.display_name
    await session.commit()
    await session.refresh(user)
    return _auth_response(user, token)


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
        .options(selectinload(TriageUser.repository_config))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
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


async def upsert_repository_config(
    session: AsyncSession,
    user: TriageUser,
    payload: UserRepositoryConfigIn,
) -> UserRepositoryConfigOut:
    config = user.repository_config
    if config is None:
        config = UserRepositoryConfig(user_id=user.id)
        session.add(config)

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
) -> Settings:
    if config is None:
        return base_settings

    return base_settings.model_copy(
        update={
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
    )


def _auth_response(user: TriageUser, token: str) -> AuthLoginOut:
    return AuthLoginOut(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        auth_token=token,
    )
