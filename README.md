# auto-triage

`auto-triage` is a FastAPI service that discovers GitHub issues tagged for
automation, stores local triage jobs, and runs a LangGraph workflow to claim and
resume work.

The first scaffold keeps external side effects behind adapters:

- GitHub operations go through `app.tools.github_tool.GitHubTool`.
- Shell operations go through `app.tools.shell.ShellTool`.
- OpenAI fix attempts go through `app.tools.openai_agent.FixAgent`.

## Configuration

The app reads environment variables through `app.config.Settings`.

- `GITHUB_TOKEN`
- `GITHUB_REPOSITORIES`, for example `owner/repo,other/repo`
- `GITHUB_ISSUE_TAGS_TO_WORK_ON`, default `auto-triage-ready`
- `GITHUB_ISSUE_FIXED_TAG`, default `auto-triage-fixed`
- `GITHUB_ISSUE_UNABLE_TO_FIX_TAG`, default `auto-triage-unable-to-fix`
- `TRIAGE_POLL_INTERVAL_SECONDS`, default `300`
- `TRIAGE_DATA_DIR`, default `.triage`
- `TRIAGE_SCHEDULER_ENABLED`, default `true`
- `TRIAGE_FIX_EXECUTION_ENABLED`, default `false`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`, default `gpt-4.1`

## Run

```bash
uv run uvicorn app.main:app --reload
```

## Test

```bash
cd app
../.venv/bin/pytest
```

Endpoints:

- `GET /health`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `POST /runs/discover`
- `POST /jobs/{job_id}/resume`

## Current Scope

Discovery, state transitions, local persistence, checkpoints, scheduling, and API
endpoints are scaffolded. GitHub MCP transport and full repository mutation/PR
creation still need concrete adapter wiring before autonomous fixing should be
enabled.
