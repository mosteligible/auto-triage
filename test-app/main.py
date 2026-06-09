from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

import logfire
from dotenv import load_dotenv
from fastapi import FastAPI

SERVER_DIR = Path(__file__).resolve().parent
COUNTER_FILE = SERVER_DIR / "counter.txt"

load_dotenv(SERVER_DIR / ".env")

SERVICE_NAME = os.getenv("LOGFIRE_SERVICE_NAME", "test-app-failure-generator")
ENVIRONMENT = os.getenv("LOGFIRE_ENVIRONMENT", "local")

counter_lock = Lock()

app = FastAPI(title="Logfire Failure Generator", version="0.1.0")


def _instrument_app(app: FastAPI) -> None:
    logfire.configure(
        send_to_logfire=True,
        service_name=SERVICE_NAME,
        environment=ENVIRONMENT,
    )
    logfire.instrument_fastapi(app, capture_headers=True)


_instrument_app(app)


@app.api_route("/lean", methods=["GET", "POST"])
async def lean() -> None:
    print("yeah this is lean endpoint", flush=True)
    raise RuntimeError("Intentional failure from /lean endpoint")


@app.api_route("/property", methods=["GET", "POST"])
def property_counter() -> dict[str, int]:
    with counter_lock:
        current_value = _read_counter()
        next_value = current_value + 1
        COUNTER_FILE.write_text(f"{next_value}\n", encoding="utf-8")

    return {"counter": next_value}


def _read_counter() -> int:
    if not COUNTER_FILE.exists():
        return 0

    value = COUNTER_FILE.read_text(encoding="utf-8").strip()
    if not value:
        return 0

    return int(value)
