from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from app.config import Settings, get_settings
from app.graph import TriageGraph
from app.persistence.checkpoint import SQLiteCheckpointStore
from app.persistence.job_store import SQLiteJobStore
from app.scheduler import TriageScheduler
from app.state import TriageStatus
from app.tools.github_tool import GitHubTool, McpGitHubTool
from app.tools.openai_agent import OpenAIFixAgent


def create_app(
    *,
    settings: Settings | None = None,
    job_store: SQLiteJobStore | None = None,
    checkpoint_store: SQLiteCheckpointStore | None = None,
    github: GitHubTool | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    job_store = job_store or SQLiteJobStore(settings.job_store_path)
    checkpoint_store = checkpoint_store or SQLiteCheckpointStore(settings.checkpoint_store_path)
    github = github or McpGitHubTool()
    fix_agent = OpenAIFixAgent(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        enabled=settings.triage_fix_execution_enabled,
    )
    graph = TriageGraph(
        settings=settings,
        job_store=job_store,
        checkpoint_store=checkpoint_store,
        github=github,
        fix_agent=fix_agent,
    )
    scheduler = TriageScheduler(
        graph=graph,
        interval_seconds=settings.triage_poll_interval_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.triage_scheduler_enabled:
            await scheduler.start()
        yield
        await scheduler.stop()

    app = FastAPI(title="auto-triage", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.job_store = job_store
    app.state.checkpoint_store = checkpoint_store
    app.state.github = github
    app.state.graph = graph
    app.state.scheduler = scheduler

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "repositories": settings.github_repositories,
            "scheduler_running": scheduler.running,
            "fix_execution_enabled": settings.triage_fix_execution_enabled,
        }

    @app.get("/jobs")
    async def list_jobs(
        status: Annotated[TriageStatus | None, Query()] = None,
    ) -> list[dict[str, object]]:
        return [job.model_dump(mode="json") for job in job_store.list(status)]

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, object]:
        job = job_store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job.model_dump(mode="json")

    @app.post("/runs/discover")
    async def discover() -> dict[str, object]:
        return await graph.run_discovery()

    @app.post("/jobs/{job_id}/resume")
    async def resume_job(job_id: str) -> dict[str, object]:
        if job_store.get(job_id) is None:
            raise HTTPException(status_code=404, detail="job not found")
        return await graph.resume_job(job_id)

    return app


app = create_app()

