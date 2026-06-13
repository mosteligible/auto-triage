# Auto Triage

FastAPI service that receives Logfire alert webhooks, enriches incidents with Logfire records,
asks a Pydantic AI agent for a diagnosis and fix plan, then creates or updates a GitHub issue
and pull request.

## First-Cut Scope

- Receives Logfire alert webhooks at `POST /webhooks/logfire`.
- Supports exception and HTTP 5xx/error-rate style alerts.
- Uses Postgres for durable incident/job state in Docker Compose.
- Uses Redis as an optional Logfire evidence cache.
- Queries Logfire's `/v2/query` API with a read token.
- Clones one configured GitHub repo and performs static source inspection only.
- Uses Pydantic AI with per-request OpenAI or Azure OpenAI provider selection.
- Creates or updates GitHub issues and pull requests through a fine-grained PAT.

Multi-repo routing, Logfire alert provisioning, and target-repo test execution are intentionally
left out of this first implementation.

## Setup

```bash
uv python install 3.12.13
uv sync
cp .env.example .env
```

Fill in `.env`, then run:

```bash
uv run alembic upgrade head
uv run uvicorn auto_triage.app:app --reload --host 0.0.0.0 --port 8001
```

The server listens on `http://127.0.0.1:8001` with the command above.

For the full local stack with Postgres, Redis, auto-triage, and the test app:

```bash
docker compose up --build
```

The Compose stack exposes:

- Auto-triage: `http://127.0.0.1:8001`
- Test app: `http://127.0.0.1:8000`
- Postgres: `127.0.0.1:5432`
- Redis: `127.0.0.1:6379`

## Setup UI

The setup console lives in `triage-ui` and uses Next.js app router.

```bash
cd triage-ui
npm install
npm run dev
```

It supports operator login, saving a user's repository/Logfire setup, receiving a generated
per-user webhook path, and sending a setup test alert through the FastAPI service. The UI also
exposes a Next.js tRPC route at `/api/trpc` that reads and writes setup environment settings
directly in Postgres, scoped by the signed-in user's bearer token and organization membership.

When running the UI separately, give it the same `DATABASE_URL` or `POSTGRES_*` settings used by
the FastAPI service so the tRPC route can reach the auto-triage database.

## Required Configuration

- `LOGFIRE_BASE_URL`: `https://logfire-us.pydantic.dev` or `https://logfire-eu.pydantic.dev`.
- `DATABASE_URL`: optional SQLAlchemy async URL override. If omitted, the app builds a
  Postgres URL from the `POSTGRES_*` settings.
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`:
  Postgres host, port, username, password, and database.
- `REDIS_CACHE_ENABLED`: enables Redis caching for Logfire evidence lookups.
- `REDIS_USERNAME`, `REDIS_PASSWORD`: Redis ACL credentials used by Docker Compose and the app.
- `LOGFIRE_READ_TOKEN`: read token created in Logfire project settings.
- `OPENAI_API_KEY`: used for manual triggers by default and for webhook requests with
  `?ai_provider=openai`.
- `TRIAGE_MODEL`: default standard OpenAI Pydantic AI model string, for example `openai:gpt-4.1-mini`.
- `OPENAI_TRIAGE_MODEL`: optional override for standard OpenAI requests.
- `AZURE_OPENAI_ENDPOINT`: Azure OpenAI endpoint for Logfire webhooks by default and for
  requests with `?ai_provider=azure`.
  Use the `/openai/v1` form when available, for example
  `https://<resource>.openai.azure.com/openai/v1`.
- `AZURE_OPENAI_API_KEY`: Azure OpenAI API key for Logfire webhooks by default and for
  requests with `?ai_provider=azure`.
- `AZURE_OPENAI_API_VERSION`: only required for classic Azure OpenAI endpoints that do not end
  with `/openai/v1`.
- `AZURE_OPENAI_DEPLOYMENT`: Azure OpenAI deployment name for Logfire webhooks by default and
  for requests with `?ai_provider=azure`.
- `GITHUB_TOKEN`: fine-grained PAT with Issues, Contents, and Pull requests read/write access to
  `GITHUB_REPO`.
- `GITHUB_REPO`: target repo in `owner/name` form.
- `GITHUB_DEFAULT_BRANCH`: base branch for clone, remediation branches, and pull requests.
- `TARGET_REPO_URL`: clone URL for static source inspection. Defaults to the GitHub repo URL.

Webhook token validation is currently disabled in the FastAPI route. Put the service behind a
private network, API gateway, or Logfire-only ingress before exposing it publicly.

## API

### Health

```bash
curl http://127.0.0.1:8000/health
```

### Logfire Webhook

Logfire webhooks use Azure OpenAI by default.

```bash
curl -X POST http://127.0.0.1:8000/webhooks/logfire \
  -H 'content-type: application/json' \
  -d '{"text":"Logfire alert: exception in api", "trace_id":"0123456789abcdef0123456789abcdef"}'
```

To route a webhook triage job through standard OpenAI, add `?ai_provider=openai`:

```bash
curl -X POST 'http://127.0.0.1:8000/webhooks/logfire?ai_provider=openai' \
  -H 'content-type: application/json' \
  -d '{"text":"Logfire alert: exception in api", "trace_id":"0123456789abcdef0123456789abcdef"}'
```

The response contains an `incident_id`, `job_id`, and status. The background worker then enriches
the incident, runs the AI agent, and creates or updates a GitHub issue and pull request.

Per-user setup webhooks are created after saving repository setup through the UI/API:

```bash
POST /webhooks/users/{webhook_id}/logfire
```

Incidents received through this path use the saved GitHub owner/repository/token, branch, target
repo URL, and Logfire settings from the user's repository configuration.

### Manual Trigger

```bash
curl -X POST http://127.0.0.1:8000/triage/incidents \
  -H 'content-type: application/json' \
  -d '{
    "title": "Manual triage for checkout 5xx",
    "alert_kind": "http_5xx",
    "service_name": "api",
    "route": "POST /checkout",
    "status_code": 500
  }'
```

The manual trigger accepts the same `ai_provider` query parameter. Omitted or `openai` uses
standard OpenAI; `azure` uses Azure OpenAI.

### Incident Status

```bash
curl http://127.0.0.1:8000/triage/incidents/{incident_id}
```

## Logfire Alert Examples

Exception alert:

```sql
SELECT
  trace_id,
  service_name,
  span_name,
  exception_type,
  exception_message,
  exception_stacktrace
FROM records
WHERE is_exception
  AND level >= 'error'
LIMIT 25
```

HTTP 5xx alert:

```sql
SELECT
  trace_id,
  service_name,
  span_name,
  attributes->>'http.route' AS route,
  http_response_status_code,
  message
FROM records
WHERE http_response_status_code >= 500
LIMIT 25
```

Configure the Logfire alert webhook URL to point at:

```text
https://your-auto-triage-host/webhooks/logfire
```

Logfire alert webhooks currently arrive in Slack-oriented JSON, so this service normalizes both
Slack-shaped payloads and direct record-shaped payloads.

## Runtime State

- Postgres stores organizations, users, repository setup, incidents, jobs, evidence, and
  GitHub output links.
- Temporary clones: `/tmp/auto-triage-work/...` for relative `WORKSPACE_DIR` values. This keeps
  Uvicorn `--reload` from restarting when the worker clones the target repo.

Temporary clone directories are ignored by git.
