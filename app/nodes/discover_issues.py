from __future__ import annotations

from app.config import Settings
from app.persistence.job_store import SQLiteJobStore
from app.state import TriageGraphState, TriageJob, is_issue_eligible
from app.tools.github_tool import GitHubTool


async def discover_issues_node(
    state: TriageGraphState,
    *,
    settings: Settings,
    github: GitHubTool,
    job_store: SQLiteJobStore,
) -> TriageGraphState:
    discovered_job_ids: list[str] = []
    queued_job_ids: list[str] = []
    errors = list(state.get("errors", []))

    for repository in settings.github_repositories:
        try:
            issues = await github.list_open_issues(repository)
        except Exception as exc:
            errors.append(f"{repository}: {exc}")
            continue

        for issue in issues:
            if not is_issue_eligible(issue.labels, settings.github_issue_tags_to_work_on):
                continue

            job = TriageJob.from_issue(issue)
            stored, created = job_store.create_or_get(job)
            discovered_job_ids.append(stored.job_id)
            if created:
                queued_job_ids.append(stored.job_id)

    message = f"queued {len(queued_job_ids)} new job(s)"
    if not settings.github_repositories:
        message = "no repositories configured"

    return {
        **state,
        "discovered_job_ids": discovered_job_ids,
        "queued_job_ids": queued_job_ids,
        "errors": errors,
        "message": message,
    }

