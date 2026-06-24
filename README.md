# Auto Triage

FastAPI service that receives Logfire alert webhooks, enriches incidents with Logfire records,
asks a Pydantic AI agent for a diagnosis and fix plan, then creates or updates a GitHub issue
and pull request.

## First-Cut Scope

- Receives Logfire alert webhooks at `POST /webhooks/logfire`.
- Supports exception and HTTP 5xx/error-rate style alerts.
- Uses Postgres for durable incident/job state in Docker Compose.
- Uses Redis as an optional Logfire evidence and runtime configuration cache.
- Uses OpenBao Transit to encrypt organization secrets before Postgres persistence.
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

For the full local stack with Postgres, Redis, OpenBao, auto-triage, the setup UI, and the test app:

```bash
docker compose up --build -d
```

The Compose stack exposes:

- Auto-triage: `http://127.0.0.1:8001`
- Setup UI: `http://127.0.0.1:3000`
- Test app: `http://127.0.0.1:8000`
- Postgres: `127.0.0.1:5432`
- Redis: `127.0.0.1:6379`

OpenBao is available only on the internal Compose network. Compose initializes persistent
single-node storage, creates a derived `auto-triage` Transit key, creates a least-privilege
AppRole for FastAPI, and enables a persistent file audit device. FastAPI receives the AppRole
credentials through a read-only named volume; the UI does not receive OpenBao credentials.

Docker publishes these ports on `0.0.0.0` by default. From another device on the same network,
replace `127.0.0.1` with the host machine's LAN IP address, for example
`http://10.0.0.217:3000` for the setup UI.

## Setup UI

The setup console lives in `triage-ui` and uses Next.js app router.

```bash
cd triage-ui
npm install
npm run dev
```

It supports organization registration, operator login, admin-managed organization members,
saving repository/Logfire setup, receiving a generated per-user webhook path, and sending a setup
test alert through the FastAPI service. The first user who creates an organization becomes its
`admin`. Admins can add members as `admin`, `write`, or `read`; write access can save setup and
send test alerts, while read access can view persisted setup. The UI also exposes a Next.js tRPC
route at `/api/trpc`. Non-secret reads remain organization-scoped in Postgres. Secret writes and
environment-variable operations are relayed to FastAPI, which derives the organization from the
authenticated user and encrypts values through OpenBao before Postgres persistence.

Sensitive values are write-only in the UI. Reads return only a configured flag, browser
`localStorage` excludes secret drafts, and generated `.env` output uses
`<stored-in-openbao>` instead of saved values.

When running the UI separately, give it the same `DATABASE_URL` or `POSTGRES_*` settings used by
the FastAPI service so the tRPC route can reach the auto-triage database. Set
`AUTO_TRIAGE_API_URL` if the Next server needs a different server-side URL for FastAPI cache
invalidation than the browser-facing `NEXT_PUBLIC_AUTO_TRIAGE_API_URL`.

The UI also supports GitHub App user login. Create a GitHub App and add this local user
authorization callback URL:

```text
http://127.0.0.1:3000/api/auth/callback/github
```

When accessing the UI from another device on the LAN, use that host URL in the GitHub App
instead, for example:

```text
http://10.0.0.217:3000/api/auth/callback/github
```

Set `GITHUB_APP_CLIENT_ID` and `GITHUB_APP_CLIENT_SECRET` in the Next server environment.
`GITHUB_APP_REDIRECT_URI` should match the callback URL above when using LAN access, and
`TRIAGE_UI_PUBLIC_ORIGIN` should match the browser-facing origin, for example
`http://10.0.0.217:3000`, so server-side redirects do not use the Docker bind address.
`GITHUB_APP_STATE_SECRET` is optional but recommended. Configure the GitHub App account
permission for email addresses as read-only so the setup UI can use the verified GitHub email for
the user. Do not put GitHub App credentials in the legacy `GITHUB_OAUTH_*` variables unless
`GITHUB_AUTH_KIND=oauth_app`. For compatibility, `triage-ui` still accepts `GITHUB_OAUTH_*` as
aliases when `GITHUB_AUTH_KIND=github_app`, but `GITHUB_APP_*` is the preferred naming. On first
GitHub login, the setup UI creates an admin organization from the GitHub username.
Set `TRIAGE_UI_PLATFORM_ADMIN_EMAILS` or `TRIAGE_UI_PLATFORM_ADMIN_GITHUB_LOGINS` as a
comma-separated bootstrap allowlist for users who should receive platform-wide admin access when
they sign in with GitHub. Organization admins are still scoped to their own organization.

## Required Configuration

- `LOGFIRE_BASE_URL`: `https://logfire-us.pydantic.dev` or `https://logfire-eu.pydantic.dev`.
- `DATABASE_URL`: optional SQLAlchemy async URL override. If omitted, the app builds a
  Postgres URL from the `POSTGRES_*` settings.
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`:
  Postgres host, port, username, password, and database.
- `REDIS_CACHE_ENABLED`: enables Redis caching for Logfire evidence lookups and organization
  runtime settings.
- `REDIS_USERNAME`, `REDIS_PASSWORD`: Redis ACL credentials used by Docker Compose and the app.
- `OPENBAO_ENABLED`: enables Transit encryption. Docker Compose defaults this to `true`.
- `OPENBAO_ADDR`: internal OpenBao URL. Docker Compose defaults to `http://openbao:8200`.
- `OPENBAO_AUTH_MOUNT`, `OPENBAO_TRANSIT_MOUNT`, `OPENBAO_TRANSIT_KEY`: AppRole and Transit
  paths/key. Compose defaults to `approle`, `transit`, and `auto-triage`.
- `OPENBAO_ROLE_ID_FILE`, `OPENBAO_SECRET_ID_FILE`: AppRole credential files mounted only into
  FastAPI. Compose defaults to `/run/openbao/role-id` and `/run/openbao/secret-id`.
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
- `GITHUB_APP_CLIENT_ID`, `GITHUB_APP_CLIENT_SECRET`: GitHub App user authorization credentials
  used only by `triage-ui` login.
- `GITHUB_APP_REDIRECT_URI`: explicit callback URL for the GitHub App user authorization flow.
- `TRIAGE_UI_PUBLIC_ORIGIN`: browser-facing origin for `triage-ui` redirects, such as
  `http://10.0.0.217:3000` when using Docker over the LAN.
- `GITHUB_APP_STATE_SECRET`: optional HMAC secret for GitHub login state cookies.
- `TRIAGE_UI_PLATFORM_ADMIN_EMAILS`: comma-separated verified GitHub emails promoted to
  platform admin on login.
- `TRIAGE_UI_PLATFORM_ADMIN_GITHUB_LOGINS`: comma-separated GitHub usernames promoted to
  platform admin on login.

Webhook token validation is currently disabled in the FastAPI route. Put the service behind a
private network, API gateway, or Logfire-only ingress before exposing it publicly.

## API

### Health

```bash
curl http://127.0.0.1:8001/health
```

### Organization Registration

Create the organization and first admin user:

```bash
curl -X POST http://127.0.0.1:8000/auth/register-organization \
  -H 'content-type: application/json' \
  -d '{
    "organization_name": "Acme Engineering",
    "email": "admin@example.com",
    "password": "change-me-now",
    "display_name": "Admin"
  }'
```

The response includes a bearer token. Admins can add users:

```bash
curl -X POST http://127.0.0.1:8000/organizations/me/members \
  -H "authorization: Bearer $AUTO_TRIAGE_TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "email": "engineer@example.com",
    "password": "member-password",
    "display_name": "Engineer",
    "role": "write"
  }'
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
repo URL, and Logfire settings from the user's repository configuration. The worker also resolves
the organization's saved Azure OpenAI/OpenAI settings from Postgres, using Redis as a short-lived
cache when enabled.

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

- Postgres stores organizations, users, memberships with `admin`/`write`/`read` roles, repository
  setup, incidents, jobs, evidence, and
  GitHub output links.
- Organization-wide runtime settings are stored in Postgres and cached in Redis by organization
  ID when Redis is enabled. Redis uses the configured username/password credentials.
- Temporary clones: `/tmp/auto-triage-work/...` for relative `WORKSPACE_DIR` values. This keeps
  Uvicorn `--reload` from restarting when the worker clones the target repo.

Temporary clone directories are ignored by git.
