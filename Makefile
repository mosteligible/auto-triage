.PHONY: help server auto-triage start-server migrate migration-current test-app run-test-app triage-ui compose-up compose-down compose-logs

AUTO_TRIAGE_HOST ?= 0.0.0.0
AUTO_TRIAGE_PORT ?= 8001
TEST_APP_HOST ?= 0.0.0.0
TEST_APP_PORT ?= 8000
PYTHON ?= python

help:
	@printf "Targets:\n"
	@printf "  make migrate       Run Alembic migrations against Postgres\n"
	@printf "  make server        Start the auto-triage FastAPI server\n"
	@printf "  make test-app      Start the Logfire test app\n"
	@printf "  make triage-ui     Start the Next.js setup UI\n"
	@printf "  make compose-up    Start Postgres, Redis, auto-triage, and test app\n"
	@printf "  make compose-down  Stop the Docker Compose stack\n"
	@printf "\n"
	@printf "Variables:\n"
	@printf "  AUTO_TRIAGE_HOST   Default: %s\n" "$(AUTO_TRIAGE_HOST)"
	@printf "  AUTO_TRIAGE_PORT   Default: %s\n" "$(AUTO_TRIAGE_PORT)"
	@printf "  TEST_APP_HOST      Default: %s\n" "$(TEST_APP_HOST)"
	@printf "  TEST_APP_PORT      Default: %s\n" "$(TEST_APP_PORT)"

server: auto-triage

start-server: auto-triage

migrate:
	alembic upgrade head

migration-current:
	alembic current

auto-triage:
	$(PYTHON) -m uvicorn auto_triage.app:app --reload --host $(AUTO_TRIAGE_HOST) --port $(AUTO_TRIAGE_PORT)

test-app: run-test-app

run-test-app:
	cd test-app && $(PYTHON) -m uvicorn main:app --reload --host $(TEST_APP_HOST) --port $(TEST_APP_PORT)

triage-ui:
	cd triage-ui && npm run dev

compose-up:
	docker compose up --build

compose-down:
	docker compose down

compose-logs:
	docker compose logs -f
