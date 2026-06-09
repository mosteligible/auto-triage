from __future__ import annotations

from typing import Any

import httpx

from auto_triage.config import Settings
from auto_triage.schemas import NormalizedIncident, TriageReport
from auto_triage.security import redact_for_issue_body, secret_value

FINGERPRINT_MARKER = "<!-- auto-triage:fingerprint={fingerprint} incident={incident_id} -->"


class GitHubClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def create_issue(
        self,
        incident_id: str,
        incident: NormalizedIncident,
        report: TriageReport,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        repo = self._repo()
        labels = sorted(set(self.settings.github_issue_labels + report.github_labels))
        body = render_issue_body(incident_id, incident, report, evidence, mode="created")
        payload = {
            "title": _issue_title(incident, report),
            "body": redact_for_issue_body(body),
            "labels": labels,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.settings.github_api_base_url}/repos/{repo}/issues",
                headers=self._headers(),
                json=payload,
            )
            if response.status_code in {403, 422} and labels:
                payload.pop("labels")
                response = await client.post(
                    f"{self.settings.github_api_base_url}/repos/{repo}/issues",
                    headers=self._headers(),
                    json=payload,
                )
            _raise_for_status(response, "create GitHub issue")
            return response.json()

    async def update_issue(
        self,
        issue_number: int,
        incident_id: str,
        incident: NormalizedIncident,
        report: TriageReport,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        repo = self._repo()
        body = render_issue_body(incident_id, incident, report, evidence, mode="updated")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.settings.github_api_base_url}/repos/{repo}/issues/{issue_number}/comments",
                headers=self._headers(),
                json={"body": redact_for_issue_body(body)},
            )
            _raise_for_status(response, "comment on GitHub issue")
            return response.json()

    def _headers(self) -> dict[str, str]:
        token = secret_value(self.settings.github_token)
        if not token:
            raise RuntimeError("GITHUB_TOKEN is not configured")
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _repo(self) -> str:
        if not self.settings.github_repo:
            raise RuntimeError("GITHUB_REPO is not configured")
        return self.settings.github_repo


def render_issue_body(
    incident_id: str,
    incident: NormalizedIncident,
    report: TriageReport,
    evidence: dict[str, Any],
    *,
    mode: str,
) -> str:
    logfire = evidence.get("logfire", {})
    codebase = evidence.get("codebase", {})
    rows = logfire.get("records") or []
    matches = codebase.get("matches") or []

    sections = [
        FINGERPRINT_MARKER.format(fingerprint=incident.fingerprint, incident_id=incident_id),
        f"## Auto-triage {mode}",
        "",
        report.summary,
        "",
        "## Incident",
        "",
        f"- Source: `{incident.source}`",
        f"- AI provider: `{incident.ai_provider}`",
        f"- Alert kind: `{incident.alert_kind}`",
        f"- Service: `{incident.service_name or 'unknown'}`",
        f"- Route/span: `{incident.route or incident.span_name or 'unknown'}`",
        f"- Trace ID: `{incident.trace_id or 'unknown'}`",
        f"- Exception: `{incident.exception_type or 'unknown'}`",
        f"- Status code: `{incident.status_code or 'unknown'}`",
    ]
    if incident.alert_url:
        sections.append(f"- Logfire alert: {incident.alert_url}")

    sections.extend(
        [
            "",
            "## Diagnosis",
            "",
            f"- Severity: `{report.severity}`",
            f"- Confidence: `{report.confidence}`",
            f"- Root cause hypothesis: {report.root_cause_hypothesis}",
            "",
            "## Evidence",
            "",
            *_bullet_list(report.evidence or ["No evidence summary returned by the agent."]),
            "",
            f"Logfire rows considered: `{len(rows)}`",
            f"Code snippets considered: `{len(matches)}`",
            "",
            "## Affected files",
            "",
            *_bullet_list(report.affected_files or ["Unknown"]),
            "",
            "## Proposed fix",
            "",
            report.proposed_fix,
            "",
            "## Acceptance checks",
            "",
            *_bullet_list(
                report.acceptance_tests
                or ["Add or run targeted checks for the affected path."]
            ),
        ]
    )
    if report.limitations:
        sections.extend(["", "## Limitations", "", *_bullet_list(report.limitations)])

    return "\n".join(sections)


def _issue_title(incident: NormalizedIncident, report: TriageReport) -> str:
    prefix = f"[auto-triage][{report.severity}]"
    title = incident.title or report.summary
    return f"{prefix} {title}"[:240]


def _bullet_list(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items]


def _raise_for_status(response: httpx.Response, operation: str) -> None:
    if not response.is_error:
        return

    message = response.text[:1_000]
    try:
        payload = response.json()
    except ValueError:
        pass
    else:
        if isinstance(payload, dict):
            message = str(
                {
                    key: payload[key]
                    for key in ("message", "errors", "documentation_url")
                    if key in payload
                }
            )[:1_000]

    raise RuntimeError(
        f"GitHub API failed to {operation}: HTTP {response.status_code}; {message}"
    )
