from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from auto_triage.config import Settings
from auto_triage.schemas import NormalizedIncident
from auto_triage.security import secret_value


class LogfireClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def fetch_evidence(self, incident: NormalizedIncident) -> dict[str, Any]:
        token = secret_value(self.settings.logfire_read_token)
        if not token:
            return {
                "available": False,
                "warnings": ["LOGFIRE_READ_TOKEN is not configured; skipped Logfire enrichment."],
                "queries": [],
                "records": [],
            }

        min_timestamp = datetime.now(tz=UTC) - timedelta(hours=self.settings.logfire_lookback_hours)
        queries: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=self.settings.logfire_timeout_seconds) as client:
            if incident.trace_id:
                trace_sql = self._trace_query(incident.trace_id)
                trace_rows = await self._query(client, token, trace_sql, min_timestamp)
                queries.append({"name": "trace", "sql": trace_sql, "row_count": len(trace_rows)})
                records.extend(trace_rows)

            similar_sql = self._similar_query(incident)
            similar_rows = await self._query(client, token, similar_sql, min_timestamp)
            queries.append({"name": "similar", "sql": similar_sql, "row_count": len(similar_rows)})
            records.extend(similar_rows)

        return {
            "available": True,
            "queries": queries,
            "records": _dedupe_records(records)[: self.settings.logfire_query_limit],
            "lookback_hours": self.settings.logfire_lookback_hours,
        }

    async def _query(
        self,
        client: httpx.AsyncClient,
        token: str,
        sql: str,
        min_timestamp: datetime,
    ) -> list[dict[str, Any]]:
        response = await client.post(
            f"{self.settings.logfire_base_url}/v2/query",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            json={
                "sql": sql,
                "min_timestamp": min_timestamp.isoformat(),
                "limit": self.settings.logfire_query_limit,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload.get("data"), list):
            return payload["data"]
        if isinstance(payload.get("rows"), list):
            return payload["rows"]
        return []

    def _trace_query(self, trace_id: str) -> str:
        return f"""
SELECT
  start_timestamp,
  trace_id,
  span_id,
  parent_span_id,
  level,
  service_name,
  span_name,
  message,
  is_exception,
  exception_type,
  exception_message,
  exception_stacktrace,
  http_response_status_code,
  url_full,
  attributes,
  log_body
FROM records
WHERE trace_id = {sql_literal(trace_id)}
ORDER BY start_timestamp ASC
LIMIT {self.settings.logfire_query_limit}
""".strip()

    def _similar_query(self, incident: NormalizedIncident) -> str:
        conditions = []
        if incident.alert_kind == "exception":
            conditions.append("is_exception")
            if incident.exception_type:
                conditions.append(f"exception_type = {sql_literal(incident.exception_type)}")
        elif incident.alert_kind == "http_5xx":
            conditions.append("http_response_status_code >= 500")
        else:
            conditions.append("level >= 'error'")

        if incident.service_name:
            conditions.append(f"service_name = {sql_literal(incident.service_name)}")
        if incident.route:
            route_conditions = [f"attributes->>'http.route' = {sql_literal(incident.route)}"]
            route_only = _route_without_method(incident.route)
            if route_only and route_only != incident.route:
                route_conditions.append(f"attributes->>'http.route' = {sql_literal(route_only)}")
            route_conditions.append(f"span_name = {sql_literal(incident.route)}")
            conditions.append("(" + " OR ".join(route_conditions) + ")")

        where_clause = "\n  AND ".join(conditions)
        return f"""
SELECT
  start_timestamp,
  trace_id,
  level,
  service_name,
  span_name,
  message,
  is_exception,
  exception_type,
  exception_message,
  exception_stacktrace,
  http_response_status_code,
  attributes,
  log_body
FROM records
WHERE {where_clause}
ORDER BY start_timestamp DESC
LIMIT {self.settings.logfire_query_limit}
""".strip()


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _route_without_method(route: str) -> str | None:
    method, _, path = route.partition(" ")
    if method.isalpha() and path.startswith("/"):
        return path
    return None


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any]] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        key = (record.get("trace_id"), record.get("span_id") or record.get("start_timestamp"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped
