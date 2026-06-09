from __future__ import annotations

import base64
import re
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

    async def create_pull_request(
        self,
        incident_id: str,
        incident: NormalizedIncident,
        report: TriageReport,
        evidence: dict[str, Any],
        *,
        issue_url: str | None = None,
    ) -> dict[str, Any]:
        repo = self._repo()
        base_branch = self.settings.github_default_branch
        head_branch = _branch_name(incident_id, incident)
        async with httpx.AsyncClient(timeout=30.0) as client:
            base_sha = await self._branch_sha(client, repo, base_branch)
            await self._ensure_branch(client, repo, head_branch, base_sha)
            changed_path = await self._commit_test_app_remediation(
                client,
                repo,
                head_branch,
                incident,
                evidence,
            )
            existing_pull = await self._find_open_pull_request(
                client,
                repo,
                head_branch,
                base_branch,
            )
            if existing_pull is not None:
                return existing_pull

            existing_file_pull = await self._find_open_pull_request_for_file(
                client,
                repo,
                base_branch,
                changed_path,
            )
            if existing_file_pull is not None:
                return existing_file_pull

            body = render_pull_request_body(
                incident_id,
                incident,
                report,
                evidence,
                changed_path=changed_path,
                base_branch=base_branch,
                issue_url=issue_url,
            )
            response = await client.post(
                f"{self.settings.github_api_base_url}/repos/{repo}/pulls",
                headers=self._headers(),
                json={
                    "title": _pull_request_title(incident, report),
                    "head": head_branch,
                    "base": base_branch,
                    "body": redact_for_issue_body(body),
                },
            )
            _raise_for_status(response, "create GitHub pull request")
            return response.json()

    async def _branch_sha(
        self,
        client: httpx.AsyncClient,
        repo: str,
        branch: str,
    ) -> str:
        response = await client.get(
            f"{self.settings.github_api_base_url}/repos/{repo}/git/ref/heads/{branch}",
            headers=self._headers(),
        )
        _raise_for_status(response, f"read GitHub branch {branch}")
        payload = response.json()
        return payload["object"]["sha"]

    async def _ensure_branch(
        self,
        client: httpx.AsyncClient,
        repo: str,
        branch: str,
        base_sha: str,
    ) -> None:
        response = await client.post(
            f"{self.settings.github_api_base_url}/repos/{repo}/git/refs",
            headers=self._headers(),
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        if response.status_code == 422 and "Reference already exists" in response.text:
            return
        _raise_for_status(response, f"create GitHub branch {branch}")

    async def _commit_test_app_remediation(
        self,
        client: httpx.AsyncClient,
        repo: str,
        branch: str,
        incident: NormalizedIncident,
        evidence: dict[str, Any],
    ) -> str:
        if not _is_test_app_lean_failure(incident):
            raise RuntimeError(
                "Pull request creation currently supports remediation for the test-app "
                "/lean RuntimeError path only."
            )

        for path in _candidate_test_app_paths(evidence):
            file_response = await client.get(
                f"{self.settings.github_api_base_url}/repos/{repo}/contents/{path}",
                headers=self._headers(),
                params={"ref": branch},
            )
            if file_response.status_code == 404:
                continue
            _raise_for_status(file_response, f"read GitHub file {path}")
            file_payload = file_response.json()
            current = base64.b64decode(file_payload["content"]).decode("utf-8")
            remediated = _remediate_lean_endpoint(current)
            if remediated is None:
                continue
            if remediated == current:
                return path

            put_response = await client.put(
                f"{self.settings.github_api_base_url}/repos/{repo}/contents/{path}",
                headers=self._headers(),
                json={
                    "message": "Remediate test-app /lean failure",
                    "content": base64.b64encode(remediated.encode("utf-8")).decode("ascii"),
                    "sha": file_payload["sha"],
                    "branch": branch,
                },
            )
            _raise_for_status(put_response, f"commit remediation to {path}")
            return path

        raise RuntimeError("Could not find test-app /lean handler to remediate in target repo")

    async def _find_open_pull_request(
        self,
        client: httpx.AsyncClient,
        repo: str,
        head_branch: str,
        base_branch: str,
    ) -> dict[str, Any] | None:
        owner = repo.split("/", 1)[0]
        response = await client.get(
            f"{self.settings.github_api_base_url}/repos/{repo}/pulls",
            headers=self._headers(),
            params={
                "state": "open",
                "head": f"{owner}:{head_branch}",
                "base": base_branch,
                "per_page": "1",
            },
        )
        _raise_for_status(response, "list GitHub pull requests")
        pulls = response.json()
        if isinstance(pulls, list) and pulls:
            return pulls[0]
        return None

    async def _find_open_pull_request_for_file(
        self,
        client: httpx.AsyncClient,
        repo: str,
        base_branch: str,
        changed_path: str,
    ) -> dict[str, Any] | None:
        response = await client.get(
            f"{self.settings.github_api_base_url}/repos/{repo}/pulls",
            headers=self._headers(),
            params={
                "state": "open",
                "base": base_branch,
                "per_page": "30",
                "sort": "created",
                "direction": "asc",
            },
        )
        _raise_for_status(response, "list GitHub pull requests")
        pulls = response.json()
        if not isinstance(pulls, list):
            return None

        for pull in pulls:
            number = pull.get("number")
            if not isinstance(number, int):
                continue
            files_response = await client.get(
                f"{self.settings.github_api_base_url}/repos/{repo}/pulls/{number}/files",
                headers=self._headers(),
                params={"per_page": "100"},
            )
            _raise_for_status(files_response, f"list files for GitHub pull request {number}")
            files = files_response.json()
            if not isinstance(files, list):
                continue
            if any(
                isinstance(item, dict) and item.get("filename") == changed_path
                for item in files
            ):
                return pull
        return None

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


def render_pull_request_body(
    incident_id: str,
    incident: NormalizedIncident,
    report: TriageReport,
    evidence: dict[str, Any],
    *,
    changed_path: str,
    base_branch: str,
    issue_url: str | None,
) -> str:
    sections = [
        FINGERPRINT_MARKER.format(fingerprint=incident.fingerprint, incident_id=incident_id),
        "## Auto-triage remediation",
        "",
        report.summary,
        "",
        "## Change",
        "",
        f"- Remediated file: `{changed_path}`",
        f"- Base branch: `{base_branch}`",
        f"- Alert kind: `{incident.alert_kind}`",
        f"- Service: `{incident.service_name or 'unknown'}`",
        f"- Route/span: `{incident.route or incident.span_name or 'unknown'}`",
        f"- Exception: `{incident.exception_type or 'unknown'}`",
    ]
    if issue_url:
        sections.append(f"- Related issue: {issue_url}")

    sections.extend(
        [
            "",
            "## Diagnosis",
            "",
            f"- Severity: `{report.severity}`",
            f"- Confidence: `{report.confidence}`",
            f"- Root cause hypothesis: {report.root_cause_hypothesis}",
            "",
            "## Proposed fix from triage",
            "",
            report.proposed_fix,
            "",
            "## Acceptance checks",
            "",
            *_bullet_list(
                report.acceptance_tests
                or ["Verify `/lean` no longer returns a 500 response."]
            ),
        ]
    )
    return "\n".join(sections)


def _issue_title(incident: NormalizedIncident, report: TriageReport) -> str:
    prefix = f"[auto-triage][{report.severity}]"
    title = incident.title or report.summary
    return f"{prefix} {title}"[:240]


def _pull_request_title(incident: NormalizedIncident, report: TriageReport) -> str:
    title = incident.title or report.summary
    return f"[auto-triage] Remediate {title}"[:240]


def _branch_name(incident_id: str, incident: NormalizedIncident) -> str:
    slug = _slugify(incident.route or incident.span_name or incident.alert_kind)
    return f"auto-triage/{incident_id[:12]}-{slug}"[:120].rstrip("-")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug or "incident"


def _is_test_app_lean_failure(incident: NormalizedIncident) -> bool:
    observed = " ".join(
        part
        for part in [
            incident.service_name,
            incident.route,
            incident.span_name,
            incident.exception_type,
            incident.exception_message,
            incident.observed_text,
        ]
        if part
    ).lower()
    return "/lean" in observed and (
        "runtimeerror" in observed or "intentional failure" in observed
    )


def _candidate_test_app_paths(evidence: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    codebase = evidence.get("codebase", {})
    if isinstance(codebase, dict):
        for match in codebase.get("matches") or []:
            if isinstance(match, dict):
                path = match.get("file")
                if isinstance(path, str) and path.endswith("main.py"):
                    paths.append(path)
    paths.extend(["test-app/main.py", "main.py"])
    return list(dict.fromkeys(paths))


def _remediate_lean_endpoint(content: str) -> str | None:
    old = (
        '@app.api_route("/lean", methods=["GET", "POST"])\n'
        "async def lean() -> None:\n"
        '    print("yeah this is lean endpoint", flush=True)\n'
        '    raise RuntimeError("Intentional failure from /lean endpoint")\n'
    )
    new = (
        '@app.api_route("/lean", methods=["GET", "POST"])\n'
        "async def lean() -> dict[str, str]:\n"
        '    print("yeah this is lean endpoint", flush=True)\n'
        "    return {\n"
        '        "status": "ok",\n'
        '        "endpoint": "lean",\n'
        '        "message": "Lean endpoint remediated by auto-triage",\n'
        "    }\n"
    )
    if new in content:
        return content
    if old in content:
        return content.replace(old, new)
    if 'raise RuntimeError("Intentional failure from /lean endpoint")' not in content:
        return None

    pattern = re.compile(
        r'@app\.api_route\("/lean", methods=\["GET", "POST"\]\)\n'
        r"async def lean\(\) -> [^:]+:\n"
        r"(?:    .+\n)+?",
        re.MULTILINE,
    )
    updated, count = pattern.subn(new, content, count=1)
    return updated if count else None


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
