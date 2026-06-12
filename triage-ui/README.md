# Triage UI

Next.js app-router setup console for configuring auto-triage against a repository and Logfire alerts.

## Run

```bash
npm install
npm run dev
```

The app listens on `http://127.0.0.1:3000`.

Set `NEXT_PUBLIC_AUTO_TRIAGE_API_URL` to change the default FastAPI service URL shown in the UI.

## Test

```bash
npm run lint
npm run build
npm run test:e2e
```

The Playwright test starts the FastAPI service with a temporary SQLite database and verifies the
login, repository setup save, generated user webhook, and setup test alert flow.
