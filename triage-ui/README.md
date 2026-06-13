# Triage UI

Next.js app-router setup console for configuring auto-triage against a repository and Logfire alerts.

## Run

```bash
npm install
npm run dev
```

The app listens on `http://127.0.0.1:3000`.

Set `NEXT_PUBLIC_AUTO_TRIAGE_API_URL` to change the default FastAPI service URL shown in the UI.
The `/api/trpc` route reads and writes setup settings directly in Postgres, so the UI process
must also receive `DATABASE_URL` or the same `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`,
`POSTGRES_PASSWORD`, and `POSTGRES_DB` values used by the FastAPI service.

## Test

```bash
npm run lint
npm run build
npm run test:e2e
```

The Playwright test runs Alembic against Postgres, starts the FastAPI service, and verifies the
login, repository setup save, generated user webhook, persisted setup load, and setup test alert
flow.
