from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from auto_triage.config import Settings, get_settings
from auto_triage.database import close_db, get_session, init_db
from auto_triage.schemas import (
    IncidentDetail,
    ManualIncidentIn,
    TriageQuery,
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
