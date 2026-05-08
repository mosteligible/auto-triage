from __future__ import annotations

from typing import Protocol

from openai import AsyncOpenAI
from pydantic import BaseModel, SecretStr

from app.state import TriageJob


class FixOutcome(BaseModel):
    success: bool = False
    should_finalize: bool = False
    summary: str | None = None
    branch_name: str | None = None
    pull_request_url: str | None = None
    failure_reason: str | None = None


class FixAgent(Protocol):
    async def attempt_fix(self, job: TriageJob) -> FixOutcome:
        ...


class OpenAIFixAgent:
    """OpenAI SDK backed fix-agent boundary.

    The first scaffold keeps repository mutation disabled by default. When the
    execution path is wired, this adapter is the handoff point for model calls.
    """

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        model: str,
        enabled: bool,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._enabled = enabled

    async def attempt_fix(self, job: TriageJob) -> FixOutcome:
        if not self._enabled:
            return FixOutcome(
                failure_reason="fix execution is disabled",
                summary="Set TRIAGE_FIX_EXECUTION_ENABLED=true after wiring repository mutation and PR creation.",
            )
        if self._api_key is None:
            return FixOutcome(failure_reason="OPENAI_API_KEY is not configured")

        client = AsyncOpenAI(api_key=self._api_key.get_secret_value())
        response = await client.responses.create(
            model=self._model,
            input=self._prompt_for(job),
        )
        summary = getattr(response, "output_text", None) or str(response)
        return FixOutcome(
            summary=summary,
            failure_reason="model analysis completed, but repository mutation and PR creation are not wired yet",
        )

    @staticmethod
    def _prompt_for(job: TriageJob) -> str:
        labels = ", ".join(job.issue.labels) or "none"
        body = job.issue.body or ""
        return (
            "You are auto-triage. Analyze this GitHub issue and propose a fix plan.\n\n"
            f"Repository: {job.issue.repository}\n"
            f"Issue: #{job.issue.number} {job.issue.title}\n"
            f"Labels: {labels}\n\n"
            f"{body}"
        )

