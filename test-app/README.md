Logfire failure generator test app.

## Run

Set `LOGFIRE_TOKEN` to send OpenTelemetry traces to Logfire:

```bash
LOGFIRE_TOKEN=<your-token> uv run uvicorn main:app --host 127.0.0.1 --port 8001
```

You can also put the token in `test-app/.env`:

```bash
LOGFIRE_TOKEN=<your-token>
```

Optional labels:

- `LOGFIRE_SERVICE_NAME`: defaults to `test-app-failure-generator`.
- `LOGFIRE_ENVIRONMENT`: defaults to `local`.

## Endpoints

- `GET /lean` and `POST /lean`: prints `yeah this is lean endpoint`, then raises an intentional error.
- `GET /property` and `POST /property`: increments `counter.txt` next to `main.py` and returns the new counter value.
