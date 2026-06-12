from __future__ import annotations

import json
import os
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.azure import AzureProvider
from pydantic_ai.providers.openai import OpenAIProvider

from auto_triage.config import Settings
from auto_triage.schemas import AIProvider, NormalizedIncident, TriageReport
from auto_triage.security import secret_value

TRIAGE_INSTRUCTIONS = """
You are an incident triage engineer. Analyze the incident evidence, Logfire records, and static
code snippets. Return a concise, actionable GitHub issue report.

Constraints:
- Do not claim a fix is certain unless the evidence supports it.
- Prefer concrete affected files/functions and narrow implementation steps.
- Include limitations when evidence is missing or only circumstantial.
- Do not include credentials, API keys, tokens, passwords, or authorization headers in output.
- Do not propose running production mutations. This first version only creates a human-review issue.
""".strip()


class TriageAgent:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def run(
        self,
        incident: NormalizedIncident,
        logfire_evidence: dict[str, Any],
        codebase_evidence: dict[str, Any],
    ) -> TriageReport:
        agent: Agent[None, TriageReport] = Agent(
            self._model_for_provider(incident.ai_provider),
            output_type=TriageReport,
            instructions=TRIAGE_INSTRUCTIONS,
        )
        prompt = self._build_prompt(incident, logfire_evidence, codebase_evidence)
        result = await agent.run(prompt)
        return result.output

    def _build_prompt(
        self,
        incident: NormalizedIncident,
        logfire_evidence: dict[str, Any],
        codebase_evidence: dict[str, Any],
    ) -> str:
        payload = {
            "incident": incident.model_dump(mode="json"),
            "logfire_evidence": logfire_evidence,
            "codebase_evidence": codebase_evidence,
            "requested_output": TriageReport.model_json_schema(),
        }
        serialized = json.dumps(payload, indent=2, default=str)
        if len(serialized) > self.settings.agent_context_max_chars:
            serialized = serialized[: self.settings.agent_context_max_chars]
            serialized += "\n\n[context truncated by auto-triage service]"
        return serialized

    def _model_for_provider(self, provider: AIProvider) -> Any:
        if provider == "azure":
            endpoint = self.settings.azure_openai_endpoint or os.environ.get(
                "AZURE_OPENAI_ENDPOINT"
            )
            api_key = secret_value(self.settings.azure_openai_api_key) or os.environ.get(
                "AZURE_OPENAI_API_KEY"
            )
            api_version = self.settings.azure_openai_api_version or os.environ.get(
                "AZURE_OPENAI_API_VERSION"
            )
            deployment = self.settings.azure_openai_deployment
            if not deployment:
                raise RuntimeError("AZURE_OPENAI_DEPLOYMENT is required when ai_provider=azure")
            if not endpoint:
                raise RuntimeError("AZURE_OPENAI_ENDPOINT is required when ai_provider=azure")
            if not api_key:
                raise RuntimeError("AZURE_OPENAI_API_KEY is required when ai_provider=azure")

            if endpoint.rstrip("/").endswith("/openai/v1"):
                return OpenAIChatModel(
                    deployment,
                    provider=OpenAIProvider(base_url=endpoint, api_key=api_key),
                )

            if not api_version:
                raise RuntimeError(
                    "AZURE_OPENAI_API_VERSION is required for classic Azure OpenAI endpoints. "
                    "It is not required when AZURE_OPENAI_ENDPOINT ends with /openai/v1."
                )

            return OpenAIChatModel(
                deployment,
                provider=AzureProvider(
                    azure_endpoint=endpoint,
                    api_key=api_key,
                    api_version=api_version,
                ),
            )

        openai_key = secret_value(self.settings.openai_api_key)
        if openai_key:
            os.environ.setdefault("OPENAI_API_KEY", openai_key)
        elif not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required when ai_provider=openai")
        return self.settings.effective_openai_model
