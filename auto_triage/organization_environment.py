from __future__ import annotations

import re
from collections.abc import Mapping
from copy import copy
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auto_triage.accounts import ensure_write_access
from auto_triage.cache import CacheClient
from auto_triage.config import Settings
from auto_triage.models import (
    OrganizationEnvironmentSettings,
    OrganizationEnvironmentVariable,
    OrganizationSetupOutputs,
    TriageUser,
    UserRepositoryConfig,
)
from auto_triage.schemas import (
    OrganizationEnvironmentVariableIn,
    OrganizationEnvironmentVariableOut,
    OrganizationEnvironmentVariablesIn,
    OrganizationEnvironmentVariablesOut,
)
from auto_triage.services.openbao import OpenBaoClient, is_openbao_ciphertext

_REPOSITORY_SECRET_FIELDS = ("github_token", "logfire_read_token")
_ENVIRONMENT_SETTINGS_SECRET_FIELDS = (
    "openai_api_key",
    "azure_openai_api_key",
    "postgres_password",
    "redis_password",
)
_SENSITIVE_ENV_NAMES = (
    "GITHUB_TOKEN",
    "LOGFIRE_READ_TOKEN",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
)


async def list_organization_environment_variables(
    session: AsyncSession,
    user: TriageUser,
) -> OrganizationEnvironmentVariablesOut:
    membership = user.organization_memberships[0]
    variables = await _read_variables(session, membership.organization_id)
    if not variables:
        settings_result = await session.execute(
            select(OrganizationEnvironmentSettings).where(
                OrganizationEnvironmentSettings.organization_id == membership.organization_id
            )
        )
        return _default_variables_response(
            membership.organization_id,
            membership.organization.name,
            settings_result.scalar_one_or_none(),
            user.repository_config,
        )
    return _variables_response(
        membership.organization_id,
        membership.organization.name,
        variables,
    )


async def save_organization_environment_variables(
    session: AsyncSession,
    user: TriageUser,
    payload: OrganizationEnvironmentVariablesIn,
    settings: Settings,
) -> OrganizationEnvironmentVariablesOut:
    membership = ensure_write_access(user)
    organization_id = membership.organization_id
    names = [item.name for item in payload.variables]
    if len(names) != len(set(names)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Environment variable names must be unique",
        )

    existing = await _read_variables(session, organization_id)
    existing_by_id = {variable.id: variable for variable in existing}
    retained_ids: set[str] = set()
    client = OpenBaoClient(settings)
    environment_result = await session.execute(
        select(OrganizationEnvironmentSettings).where(
            OrganizationEnvironmentSettings.organization_id == organization_id
        )
    )
    fallback_secrets = _setup_secret_ciphertexts(
        environment_result.scalar_one_or_none(),
        user.repository_config,
    )

    for position, item in enumerate(payload.variables):
        variable = _existing_variable(item, existing_by_id, organization_id)
        if variable is None:
            variable = OrganizationEnvironmentVariable(
                organization_id=organization_id,
                updated_by_user_id=user.id,
            )
            session.add(variable)
        else:
            retained_ids.add(variable.id)

        variable.name = item.name
        variable.updated_by_user_id = user.id
        variable.position = position
        await _set_variable_value(
            client,
            settings,
            organization_id,
            variable,
            item,
            fallback_secrets.get(item.name),
        )

    for variable in existing:
        if variable.id not in retained_ids:
            await session.delete(variable)

    await session.commit()
    variables = await _read_variables(session, organization_id)
    return _variables_response(
        organization_id,
        membership.organization.name,
        variables,
    )


async def get_runtime_environment_values(
    session: AsyncSession,
    organization_id: str,
    settings: Settings,
) -> dict[str, str]:
    variables = await _read_variables(session, organization_id)
    client = OpenBaoClient(settings)
    values: dict[str, str] = {}
    for variable in variables:
        if variable.sensitive:
            if variable.encrypted_value:
                values[variable.name] = await client.decrypt(
                    organization_id,
                    variable.encrypted_value,
                )
        else:
            values[variable.name] = variable.value
    return values


async def resolve_configuration_secrets(
    settings: Settings,
    organization_id: str,
    repository_config: Any | None,
    environment_settings: Any | None,
) -> tuple[Any | None, Any | None]:
    client = OpenBaoClient(settings)
    resolved_repository = copy(repository_config) if repository_config is not None else None
    resolved_environment = copy(environment_settings) if environment_settings is not None else None

    if resolved_repository is not None:
        for field in _REPOSITORY_SECRET_FIELDS:
            value = getattr(resolved_repository, field)
            if is_openbao_ciphertext(value):
                setattr(
                    resolved_repository,
                    field,
                    await client.decrypt(organization_id, value),
                )

    if resolved_environment is not None:
        for field in _ENVIRONMENT_SETTINGS_SECRET_FIELDS:
            value = getattr(resolved_environment, field)
            if is_openbao_ciphertext(value):
                setattr(
                    resolved_environment,
                    field,
                    await client.decrypt(organization_id, value),
                )

    return resolved_repository, resolved_environment


async def migrate_plaintext_secrets(settings: Settings) -> None:
    if not settings.openbao_enabled:
        return

    from auto_triage.database import AsyncSessionLocal

    client = OpenBaoClient(settings)
    async with AsyncSessionLocal() as session:
        environment_variables = (
            await session.execute(select(OrganizationEnvironmentVariable))
        ).scalars()
        for variable in environment_variables:
            if variable.sensitive and variable.value and not variable.encrypted_value:
                variable.encrypted_value = await client.encrypt(
                    variable.organization_id,
                    variable.value,
                )
                variable.value = ""
                variable.encryption_provider = "openbao"
                variable.encryption_key_name = settings.openbao_transit_key
            elif variable.encrypted_value:
                variable.encryption_provider = "openbao"
                variable.encryption_key_name = settings.openbao_transit_key

        repository_configs = (await session.execute(select(UserRepositoryConfig))).scalars()
        for config in repository_configs:
            await _encrypt_model_fields(
                client,
                config.organization_id,
                config,
                _REPOSITORY_SECRET_FIELDS,
            )

        organization_settings = (
            await session.execute(select(OrganizationEnvironmentSettings))
        ).scalars()
        for config in organization_settings:
            await _encrypt_model_fields(
                client,
                config.organization_id,
                config,
                _ENVIRONMENT_SETTINGS_SECRET_FIELDS,
            )

        setup_outputs = (await session.execute(select(OrganizationSetupOutputs))).scalars()
        for outputs in setup_outputs:
            outputs.env_file = redact_env_file(outputs.env_file)

        await session.commit()
    await CacheClient(settings).delete_pattern(
        "auto-triage:repository-config:*",
        "auto-triage:organization-settings:*",
    )


async def encrypt_secret_for_storage(
    settings: Settings,
    organization_id: str,
    value: str | None,
) -> str | None:
    if value is None or not value.strip():
        return None
    if is_openbao_ciphertext(value):
        return value
    return await OpenBaoClient(settings).encrypt(organization_id, value)


def apply_runtime_environment(
    updates: dict[str, Any],
    environment: Mapping[str, str],
) -> None:
    direct_fields = {
        "LOGFIRE_BASE_URL": "logfire_base_url",
        "LOGFIRE_PROJECT_URL": "logfire_project_url",
        "TRIAGE_MODEL": "triage_model",
        "AZURE_OPENAI_ENDPOINT": "azure_openai_endpoint",
        "AZURE_OPENAI_API_VERSION": "azure_openai_api_version",
        "AZURE_OPENAI_DEPLOYMENT": "azure_openai_deployment",
        "GITHUB_REPO": "github_repo",
        "GITHUB_DEFAULT_BRANCH": "github_default_branch",
        "TARGET_REPO_URL": "target_repo_url",
    }
    secret_fields = {
        "LOGFIRE_READ_TOKEN": "logfire_read_token",
        "OPENAI_API_KEY": "openai_api_key",
        "AZURE_OPENAI_API_KEY": "azure_openai_api_key",
        "GITHUB_TOKEN": "github_token",
    }
    for environment_name, setting_name in direct_fields.items():
        value = environment.get(environment_name)
        if value:
            updates[setting_name] = value
    for environment_name, setting_name in secret_fields.items():
        value = environment.get(environment_name)
        if value:
            from pydantic import SecretStr

            updates[setting_name] = SecretStr(value)


async def _read_variables(
    session: AsyncSession,
    organization_id: str,
) -> list[OrganizationEnvironmentVariable]:
    result = await session.execute(
        select(OrganizationEnvironmentVariable)
        .where(OrganizationEnvironmentVariable.organization_id == organization_id)
        .order_by(
            OrganizationEnvironmentVariable.position,
            OrganizationEnvironmentVariable.created_at,
        )
    )
    return list(result.scalars().all())


def _existing_variable(
    item: OrganizationEnvironmentVariableIn,
    existing_by_id: dict[str, OrganizationEnvironmentVariable],
    organization_id: str,
) -> OrganizationEnvironmentVariable | None:
    if item.id is None:
        return None
    variable = existing_by_id.get(item.id)
    if variable is None or variable.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Environment variable was not found in this organization",
        )
    return variable


async def _set_variable_value(
    client: OpenBaoClient,
    settings: Settings,
    organization_id: str,
    variable: OrganizationEnvironmentVariable,
    item: OrganizationEnvironmentVariableIn,
    fallback_ciphertext: str | None,
) -> None:
    variable.sensitive = item.sensitive
    if not item.sensitive:
        variable.value = item.value
        variable.encrypted_value = None
        variable.encryption_provider = None
        variable.encryption_key_name = None
        return

    variable.value = ""
    if item.retain_existing:
        if not variable.encrypted_value and fallback_ciphertext:
            variable.encrypted_value = fallback_ciphertext
            variable.encryption_provider = "openbao"
            variable.encryption_key_name = settings.openbao_transit_key
        if not variable.encrypted_value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{item.name} has no encrypted value to retain",
            )
        return
    variable.encrypted_value = (
        await client.encrypt(organization_id, item.value) if item.value else None
    )
    variable.encryption_provider = "openbao" if variable.encrypted_value else None
    variable.encryption_key_name = (
        settings.openbao_transit_key if variable.encrypted_value else None
    )


def _setup_secret_ciphertexts(
    environment: OrganizationEnvironmentSettings | None,
    repository: UserRepositoryConfig | None,
) -> dict[str, str]:
    candidates = {
        "GITHUB_TOKEN": repository.github_token if repository else None,
        "LOGFIRE_READ_TOKEN": repository.logfire_read_token if repository else None,
        "OPENAI_API_KEY": environment.openai_api_key if environment else None,
        "AZURE_OPENAI_API_KEY": environment.azure_openai_api_key if environment else None,
        "POSTGRES_PASSWORD": environment.postgres_password if environment else None,
        "REDIS_PASSWORD": environment.redis_password if environment else None,
    }
    return {
        name: value for name, value in candidates.items() if value and is_openbao_ciphertext(value)
    }


async def _encrypt_model_fields(
    client: OpenBaoClient,
    organization_id: str,
    model: Any,
    fields: tuple[str, ...],
) -> None:
    for field in fields:
        value = getattr(model, field)
        if value and not is_openbao_ciphertext(value):
            setattr(model, field, await client.encrypt(organization_id, value))


def _variables_response(
    organization_id: str,
    organization_name: str,
    variables: list[OrganizationEnvironmentVariable],
) -> OrganizationEnvironmentVariablesOut:
    return OrganizationEnvironmentVariablesOut(
        organization_id=organization_id,
        organization_name=organization_name,
        variables=[
            OrganizationEnvironmentVariableOut(
                id=variable.id,
                name=variable.name,
                value="" if variable.sensitive else variable.value,
                sensitive=variable.sensitive,
                configured=bool(variable.encrypted_value if variable.sensitive else variable.value),
                position=variable.position,
                updated_at=variable.updated_at,
            )
            for variable in variables
        ],
        updated_at=_latest_updated_at(variables),
    )


def _default_variables_response(
    organization_id: str,
    organization_name: str,
    environment: OrganizationEnvironmentSettings | None,
    repository: UserRepositoryConfig | None,
) -> OrganizationEnvironmentVariablesOut:
    values: list[tuple[str, Any, bool]] = [
        ("AUTO_TRIAGE_API_URL", environment.api_base_url if environment else None, False),
        (
            "PUBLIC_WEBHOOK_BASE_URL",
            environment.public_webhook_base_url if environment else None,
            False,
        ),
        ("LOGFIRE_REGION", environment.logfire_region if environment else None, False),
        ("LOGFIRE_BASE_URL", repository.logfire_base_url if repository else None, False),
        ("LOGFIRE_READ_TOKEN", repository.logfire_read_token if repository else None, True),
        ("LOGFIRE_PROJECT_URL", repository.logfire_project_url if repository else None, False),
        ("LOGFIRE_SERVICE_NAME", repository.logfire_service_name if repository else None, False),
        ("LOGFIRE_ROUTE", repository.logfire_route if repository else None, False),
        (
            "ALERT_WINDOW_MINUTES",
            environment.alert_window_minutes if environment else None,
            False,
        ),
        ("ALERT_TRIGGER", repository.alert_trigger if repository else None, False),
        ("ALERT_MODE", repository.alert_mode if repository else None, False),
        ("AI_PROVIDER", repository.ai_provider if repository else None, False),
        ("TRIAGE_MODEL", environment.openai_model if environment else None, False),
        ("OPENAI_API_KEY", environment.openai_api_key if environment else None, True),
        (
            "AZURE_OPENAI_ENDPOINT",
            environment.azure_openai_endpoint if environment else None,
            False,
        ),
        (
            "AZURE_OPENAI_DEPLOYMENT",
            environment.azure_openai_deployment if environment else None,
            False,
        ),
        (
            "AZURE_OPENAI_API_VERSION",
            environment.azure_openai_api_version if environment else None,
            False,
        ),
        (
            "AZURE_OPENAI_API_KEY",
            environment.azure_openai_api_key if environment else None,
            True,
        ),
        ("GITHUB_TOKEN", repository.github_token if repository else None, True),
        (
            "GITHUB_REPO",
            f"{repository.github_owner}/{repository.github_repo_name}" if repository else None,
            False,
        ),
        (
            "GITHUB_DEFAULT_BRANCH",
            repository.github_default_branch if repository else None,
            False,
        ),
        ("TARGET_REPO_URL", repository.target_repo_url if repository else None, False),
        ("POSTGRES_HOST", environment.postgres_host if environment else None, False),
        ("POSTGRES_PORT", environment.postgres_port if environment else None, False),
        ("POSTGRES_USER", environment.postgres_user if environment else None, False),
        (
            "POSTGRES_PASSWORD",
            environment.postgres_password if environment else None,
            True,
        ),
        ("POSTGRES_DB", environment.postgres_db if environment else None, False),
        (
            "REDIS_CACHE_ENABLED",
            environment.redis_enabled if environment else None,
            False,
        ),
        ("REDIS_HOST", environment.redis_host if environment else None, False),
        ("REDIS_PORT", environment.redis_port if environment else None, False),
        ("REDIS_USERNAME", environment.redis_username if environment else None, False),
        ("REDIS_PASSWORD", environment.redis_password if environment else None, True),
        (
            "REDIS_CACHE_TTL_SECONDS",
            environment.redis_ttl_seconds if environment else None,
            False,
        ),
    ]
    updated_values = [
        value
        for value in (
            environment.updated_at if environment else None,
            repository.updated_at if repository else None,
        )
        if value is not None
    ]
    return OrganizationEnvironmentVariablesOut(
        organization_id=organization_id,
        organization_name=organization_name,
        variables=[
            OrganizationEnvironmentVariableOut(
                id="",
                name=name,
                value="" if sensitive or value is None else str(value),
                sensitive=sensitive,
                configured=bool(value),
                position=position,
                updated_at=None,
            )
            for position, (name, value, sensitive) in enumerate(values)
        ],
        updated_at=max(updated_values) if updated_values else None,
    )


def _latest_updated_at(
    variables: list[OrganizationEnvironmentVariable],
) -> datetime | None:
    values = [variable.updated_at for variable in variables if variable.updated_at]
    return max(values) if values else None


def redact_env_file(value: str) -> str:
    result = value
    for name in _SENSITIVE_ENV_NAMES:
        result = re.sub(
            rf"(?m)^({re.escape(name)}=).*$",
            r"\1<stored-in-openbao>",
            result,
        )
    return result
