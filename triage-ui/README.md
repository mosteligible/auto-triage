# Triage UI

Next.js app-router setup console for configuring auto-triage against a repository and Logfire
alerts.

## Run

```bash
npm install
npm run dev
```

The app listens on `http://127.0.0.1:3000`.

The Docker Compose stack also runs this UI and publishes it on host port `3000`:

```bash
docker compose up --build -d triage_ui
```

From another device on the same network, open the host machine's LAN IP address, for example
`http://10.0.0.217:3000`.

First-time setup starts by creating an organization. The creator is assigned the `admin` role.
Admins can add organization users as `admin`, `write`, or `read`; `write` users can save setup
and trigger test alerts, while `read` users can load persisted setup.

Set `NEXT_PUBLIC_AUTO_TRIAGE_API_URL` to change the default FastAPI service URL shown in the UI.
Set `AUTO_TRIAGE_API_URL` when the Next server needs a different server-side FastAPI URL for
cache invalidation, for example inside Docker networking.
The `/api/trpc` route reads organization-scoped setup metadata from Postgres. Secret writes and
environment-variable operations are relayed to FastAPI, where organization membership and write
role are checked before OpenBao encryption. The UI process must still receive `DATABASE_URL` or
the same `POSTGRES_*` connection settings for authenticated metadata reads.

Saved secrets are write-only: the UI receives configured-state flags, does not persist secret
drafts in browser `localStorage`, and renders `<stored-in-openbao>` in generated `.env` output.

## GitHub Login

Create a GitHub App and set the user authorization callback URL to:

```text
http://127.0.0.1:3000/api/auth/callback/github
```

For LAN access, use the host URL you open in the browser:

```text
http://10.0.0.217:3000/api/auth/callback/github
```

Set these environment variables for the Next server:

```bash
GITHUB_AUTH_KIND=github_app
TRIAGE_UI_PUBLIC_ORIGIN=
GITHUB_APP_CLIENT_ID=
GITHUB_APP_CLIENT_SECRET=
GITHUB_APP_REDIRECT_URI=
GITHUB_APP_STATE_SECRET=
TRIAGE_UI_PLATFORM_ADMIN_EMAILS=
TRIAGE_UI_PLATFORM_ADMIN_GITHUB_LOGINS=
```

`TRIAGE_UI_PUBLIC_ORIGIN` should be the browser-facing origin, such as
`http://10.0.0.217:3000` for LAN access. `GITHUB_APP_REDIRECT_URI` should match the callback URL
above when using LAN access.
`GITHUB_APP_STATE_SECRET` is optional but recommended. Give the GitHub App read-only account
permission for email addresses so the setup UI can use the verified GitHub email as the user
email. Do not put GitHub App credentials in the legacy `GITHUB_OAUTH_*` variables unless
`GITHUB_AUTH_KIND=oauth_app`. For compatibility, `triage-ui` still accepts `GITHUB_OAUTH_*` as
aliases when `GITHUB_AUTH_KIND=github_app`, but `GITHUB_APP_*` is the preferred naming. The first
GitHub login creates an admin organization from the GitHub username when the user has no existing
organization.
Use `TRIAGE_UI_PLATFORM_ADMIN_EMAILS` or `TRIAGE_UI_PLATFORM_ADMIN_GITHUB_LOGINS` as
comma-separated bootstrap allowlists for users who should manage all organizations. Organization
admins remain scoped to their own organization.

## Test

```bash
npm run lint
npm run build
npm run test:e2e
```

The Playwright test runs Alembic against Postgres, starts the FastAPI service, and verifies the
organization registration, admin member creation, repository setup save, generated user webhook,
persisted setup load, and setup test alert flow.
