from __future__ import annotations

import hashlib
import json
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from auto_triage.accounts import (
    current_user,
    get_user_config_by_webhook,
    login_or_register_user,
    repository_config_response,
    upsert_repository_config,
)
from auto_triage.config import Settings, get_settings
from auto_triage.database import close_db, get_session, init_db
from auto_triage.models import TriageUser, UserRepositoryConfig
from auto_triage.schemas import (
    AlertTestIn,
    AuthLoginIn,
    AuthLoginOut,
    IncidentDetail,
    ManualIncidentIn,
    TriageQuery,
    UserProfileOut,
    UserRepositoryConfigIn,
    UserRepositoryConfigOut,
    UserWebhookTriageQuery,
    WebhookAck,
    WebhookTriageQuery,
)
from auto_triage.storage import enqueue_incident, get_incident_detail
from auto_triage.webhooks.logfire import normalize_logfire_payload, normalize_manual_incident
from auto_triage.worker import TriageWorker, recover_interrupted_jobs

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db()
    worker: TriageWorker | None = None
    if settings.run_worker:
        await recover_interrupted_jobs()
        worker = TriageWorker(settings)
        worker.start()
        app.state.worker = worker
    try:
        yield
    finally:
        if worker is not None:
            await worker.stop()
        await close_db()


app = FastAPI(title="Auto Triage", version="0.1.0", lifespan=lifespan)
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
TriageQueryDep = Annotated[TriageQuery, Query()]
WebhookTriageQueryDep = Annotated[WebhookTriageQuery, Query()]
UserWebhookTriageQueryDep = Annotated[UserWebhookTriageQuery, Query()]
CurrentUserDep = Annotated[TriageUser, Depends(current_user)]


def _instrument_app(app: FastAPI) -> None:
    try:
        import logfire

        logfire.configure(send_to_logfire="if-token-present", service_name=get_settings().app_name)
        logfire.instrument_fastapi(app)
        logfire.instrument_httpx()
        logfire.instrument_sqlalchemy()
        logfire.instrument_pydantic_ai()
    except Exception:
        logger.debug("logfire instrumentation not enabled", exc_info=True)


_instrument_app(app)


@app.get("/health")
async def health(settings: SettingsDep) -> dict[str, Any]:
    return {
        "status": "ok",
        "environment": settings.environment,
        "worker_enabled": settings.run_worker,
    }


@app.post("/auth/login", response_model=AuthLoginOut)
async def login(
    payload: AuthLoginIn,
    session: SessionDep,
) -> AuthLoginOut:
    return await login_or_register_user(session, payload)


@app.get("/users/me", response_model=UserProfileOut)
async def me(user: CurrentUserDep) -> UserProfileOut:
    organization_id = user.organization_memberships[0].organization_id
    return UserProfileOut(
        user_id=user.id,
        organization_id=organization_id,
        email=user.email,
        display_name=user.display_name,
        repository_config=repository_config_response(user.repository_config),
    )


@app.put("/users/me/repository-config", response_model=UserRepositoryConfigOut)
async def save_repository_config(
    payload: UserRepositoryConfigIn,
    user: CurrentUserDep,
    session: SessionDep,
) -> UserRepositoryConfigOut:
    return await upsert_repository_config(session, user, payload)


@app.post("/users/me/alerts/test", response_model=WebhookAck, status_code=status.HTTP_202_ACCEPTED)
async def send_test_alert(
    payload: AlertTestIn,
    user: CurrentUserDep,
    session: SessionDep,
) -> WebhookAck:
    config = user.repository_config
    if config is None:
        raise HTTPException(status_code=409, detail="Repository setup is required first")
    raw_payload = _test_alert_payload(payload, config)
    normalized = normalize_logfire_payload(raw_payload)
    normalized.ai_provider = config.ai_provider
    _attach_user_config(normalized, config)
    incident, job, duplicate = await enqueue_incident(session, normalized, raw_payload)
    return WebhookAck(
        incident_id=incident.id,
        job_id=job.id,
        status=incident.status,
        duplicate=duplicate,
    )


@app.post("/webhooks/logfire", response_model=WebhookAck, status_code=status.HTTP_202_ACCEPTED)
async def logfire_webhook(
    request: Request,
    triage_query: WebhookTriageQueryDep,
    session: SessionDep,
) -> WebhookAck:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object payload")

    normalized = normalize_logfire_payload(payload)
    normalized.ai_provider = triage_query.ai_provider
    incident, job, duplicate = await enqueue_incident(session, normalized, payload)
    return WebhookAck(
        incident_id=incident.id,
        job_id=job.id,
        status=incident.status,
        duplicate=duplicate,
    )


@app.post(
    "/webhooks/users/{webhook_id}/logfire",
    response_model=WebhookAck,
    status_code=status.HTTP_202_ACCEPTED,
)
async def user_logfire_webhook(
    webhook_id: str,
    request: Request,
    triage_query: UserWebhookTriageQueryDep,
    session: SessionDep,
) -> WebhookAck:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object payload")

    config = await get_user_config_by_webhook(session, webhook_id)
    normalized = normalize_logfire_payload(payload)
    normalized.ai_provider = triage_query.ai_provider or config.ai_provider
    _attach_user_config(normalized, config)
    incident, job, duplicate = await enqueue_incident(session, normalized, payload)
    return WebhookAck(
        incident_id=incident.id,
        job_id=job.id,
        status=incident.status,
        duplicate=duplicate,
    )


@app.post("/triage/incidents", response_model=WebhookAck, status_code=status.HTTP_202_ACCEPTED)
async def manual_incident(
    payload: ManualIncidentIn,
    triage_query: TriageQueryDep,
    session: SessionDep,
) -> WebhookAck:
    normalized = normalize_manual_incident(payload)
    normalized.ai_provider = triage_query.ai_provider
    raw_payload = payload.raw_payload or payload.model_dump(mode="json")
    incident, job, duplicate = await enqueue_incident(session, normalized, raw_payload)
    return WebhookAck(
        incident_id=incident.id,
        job_id=job.id,
        status=incident.status,
        duplicate=duplicate,
    )


@app.get("/triage/incidents/{incident_id}", response_model=IncidentDetail)
async def incident_status(
    incident_id: str,
    session: SessionDep,
) -> IncidentDetail:
    detail = await get_incident_detail(session, incident_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return detail


def _attach_user_config(
    normalized,
    config: UserRepositoryConfig,
) -> None:
    normalized.user_id = config.user_id
    normalized.organization_id = config.organization_id
    normalized.user_config_id = config.id
    normalized.webhook_id = config.webhook_id
    normalized.attributes = {
        **normalized.attributes,
        "auto_triage": {
            "organization_id": config.organization_id,
            "user_id": config.user_id,
            "user_config_id": config.id,
            "webhook_id": config.webhook_id,
        },
    }
    normalized.fingerprint = _scoped_fingerprint(normalized.fingerprint, config.webhook_id)


def _scoped_fingerprint(fingerprint: str, webhook_id: str) -> str:
    basis = {"fingerprint": fingerprint, "webhook_id": webhook_id}
    return hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()


def _test_alert_payload(payload: AlertTestIn, config: UserRepositoryConfig) -> dict[str, Any]:
    service_name = payload.service_name or config.logfire_service_name or "setup-test-service"
    route = payload.route or config.logfire_route or "/setup-test"
    return {
        "columns": [
            {"name": "trace_id"},
            {"name": "service_name"},
            {"name": "span_name"},
            {"name": "route"},
            {"name": "http_response_status_code"},
            {"name": "exception_type"},
            {"name": "exception_message"},
        ],
        "data": [
            [
                "0123456789abcdef0123456789abcdef",
                service_name,
                f"GET {route}",
                route,
                payload.status_code,
                payload.exception_type,
                payload.exception_message,
            ]
        ],
    }
