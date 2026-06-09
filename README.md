# Auto Triage

FastAPI service that receives Logfire alert webhooks, enriches incidents with Logfire records,
asks a Pydantic AI agent for a diagnosis and fix plan, then creates or updates a GitHub issue.

## First-Cut Scope

- Receives Logfire alert webhooks at `POST /webhooks/logfire`.
- Supports exception and HTTP 5xx/error-rate style alerts.
- Uses SQLite for durable incident/job state.
- Queries Logfire's `/v2/query` API with a read token.
- Clones one configured GitHub repo and performs static source inspection only.
- Uses Pydantic AI with per-request OpenAI or Azure OpenAI provider selection.
- Creates or updates GitHub issues through a fine-grained PAT.

PR creation, multi-repo routing, Logfire alert provisioning, and target-repo test execution are
intentionally left out of this first implementation.

## Setup

```bash
uv python install 3.12.13
uv sync
cp .env.example .env
```

Fill in `.env`, then run:

```bash
uv run uvicorn auto_triage.app:app --reload
```

The server listens on `http://127.0.0.1:8000` by default.

## Required Configuration

- `LOGFIRE_BASE_URL`: `https://logfire-us.pydantic.dev` or `https://logfire-eu.pydantic.dev`.
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
- `GITHUB_TOKEN`: fine-grained PAT with Issues read/write access to `GITHUB_REPO`.
- `GITHUB_REPO`: target repo in `owner/name` form.
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
the incident, runs the AI agent, and creates or updates a GitHub issue.

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

- SQLite DB: `data/auto_triage.db`
- Temporary clones: `.auto-triage-work/`

Both are ignored by git.
