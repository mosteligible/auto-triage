from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from auto_triage.schemas import ManualIncidentIn, NormalizedIncident

TRACE_ID_RE = re.compile(r"\b[0-9a-fA-F]{32}\b")
PY_STACK_RE = re.compile(r'File "([^"]+)", line (\d+), in ([^\n]+)')
JS_STACK_RE = re.compile(r"\s+at\s+(?:(.*?)\s+\()?(.+?):(\d+):(\d+)\)?")


def normalize_logfire_payload(payload: dict[str, Any]) -> NormalizedIncident:
    observed_text = _flatten_text(payload)
    direct_record = _first_record(payload)

    trace_id = _as_str(
        _coalesce(
            _find_first_key(payload, {"trace_id", "traceid"}),
            direct_record.get("trace_id") if direct_record else None,
        )
    )
    if trace_id is None:
        trace_id_match = TRACE_ID_RE.search(observed_text)
        trace_id = trace_id_match.group(0) if trace_id_match else None

    service_name = _as_str(
        _coalesce(
            _find_first_key(payload, {"service_name", "service.name"}),
            _find_nested(payload, ("otel_resource_attributes", "service.name")),
            direct_record.get("service_name") if direct_record else None,
        )
    )
    route = _as_str(
        _coalesce(
            _find_first_key(payload, {"route", "http.route"}),
            _find_nested(payload, ("attributes", "http.route")),
            direct_record.get("route") if direct_record else None,
        )
    )
    span_name = _as_str(
        _coalesce(
            _find_first_key(payload, {"span_name", "span.name"}),
            direct_record.get("span_name") if direct_record else None,
        )
    )
    exception_type = _as_str(
        _coalesce(
            _find_first_key(payload, {"exception_type", "exception.type"}),
            direct_record.get("exception_type") if direct_record else None,
        )
    )
    exception_message = _as_str(
        _coalesce(
            _find_first_key(payload, {"exception_message", "exception.message"}),
            direct_record.get("exception_message") if direct_record else None,
        )
    )
    exception_stacktrace = _as_str(
        _find_first_key(payload, {"exception_stacktrace", "exception.stacktrace", "stacktrace"})
    )
    status_code = _as_int(
        _coalesce(
            _find_first_key(payload, {"http_response_status_code", "status_code"}),
            _find_nested(payload, ("attributes", "http.response.status_code")),
            direct_record.get("http_response_status_code") if direct_record else None,
            direct_record.get("status_code") if direct_record else None,
        )
    )
    alert_url = _as_str(
        _coalesce(_find_first_key(payload, {"alert_url", "url"}), _extract_url(payload))
    )
    title = _title_from_payload(payload, observed_text, exception_type, route, service_name)
    alert_kind = _alert_kind(observed_text, exception_type, status_code)
    top_frame = _top_stack_frame(exception_stacktrace)

    fingerprint = fingerprint_values(
        source="logfire",
        alert_kind=alert_kind,
        service_name=service_name,
        route=route or span_name,
        exception_type=exception_type,
        status_code=status_code,
        top_frame=top_frame,
    )

    return NormalizedIncident(
        source="logfire",
        alert_kind=alert_kind,
        title=title,
        fingerprint=fingerprint,
        service_name=service_name,
        route=route,
        span_name=span_name,
        trace_id=trace_id,
        exception_type=exception_type,
        exception_message=exception_message,
        exception_stacktrace=exception_stacktrace,
        top_frame=top_frame,
        status_code=status_code,
        alert_url=alert_url,
        observed_text=observed_text[:10_000] or None,
        attributes=_safe_attributes(payload),
    )


def normalize_manual_incident(payload: ManualIncidentIn) -> NormalizedIncident:
    top_frame = _top_stack_frame(payload.exception_stacktrace)
    fingerprint = fingerprint_values(
        source="manual",
        alert_kind=payload.alert_kind,
        service_name=payload.service_name,
        route=payload.route or payload.span_name,
        exception_type=payload.exception_type,
        status_code=payload.status_code,
        top_frame=top_frame,
    )
    observed_text = " ".join(
        part
        for part in [
            payload.title,
            payload.exception_type,
            payload.exception_message,
            payload.exception_stacktrace,
        ]
        if part
    )
    return NormalizedIncident(
        source="manual",
        alert_kind=payload.alert_kind,
        title=payload.title,
        fingerprint=fingerprint,
        service_name=payload.service_name,
        route=payload.route,
        span_name=payload.span_name,
        trace_id=payload.trace_id,
        exception_type=payload.exception_type,
        exception_message=payload.exception_message,
        exception_stacktrace=payload.exception_stacktrace,
        top_frame=top_frame,
        status_code=payload.status_code,
        observed_text=observed_text[:10_000] or None,
        attributes=payload.raw_payload,
    )


def fingerprint_values(
    *,
    source: str,
    alert_kind: str,
    service_name: str | None,
    route: str | None,
    exception_type: str | None,
    status_code: int | None,
    top_frame: str | None,
) -> str:
    status_family = f"{status_code // 100}xx" if status_code else ""
    route_key = _route_without_method(route) or route or ""
    basis = {
        "source": source,
        "alert_kind": alert_kind,
        "service_name": service_name or "",
        "route": route_key,
        "exception_type": exception_type or "",
        "status_family": status_family,
    }
    return hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()


def _alert_kind(text: str, exception_type: str | None, status_code: int | None) -> str:
    lowered = text.lower()
    if exception_type or "exception" in lowered or "traceback" in lowered:
        return "exception"
    if (status_code and status_code >= 500) or "5xx" in lowered or "error rate" in lowered:
        return "http_5xx"
    return "logfire_alert"


def _title_from_payload(
    payload: dict[str, Any],
    observed_text: str,
    exception_type: str | None,
    route: str | None,
    service_name: str | None,
) -> str:
    direct_title = _as_str(_coalesce(payload.get("title"), payload.get("text")))
    if direct_title:
        return direct_title[:240]

    parts = ["Logfire alert"]
    if service_name:
        parts.append(f"in {service_name}")
    if route:
        parts.append(f"on {route}")
    if exception_type:
        parts.append(f"({exception_type})")
    if len(parts) > 1:
        return " ".join(parts)[:240]
    fallback_title = (
        observed_text.strip().splitlines()[0] if observed_text.strip() else "Logfire alert"
    )
    return fallback_title[:240]


def _first_record(payload: dict[str, Any]) -> dict[str, Any]:
    table_record = _first_table_record(payload)
    if table_record:
        return table_record

    for key in ("record", "records", "row", "rows", "data"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value[0]
    return {}


def _first_table_record(payload: dict[str, Any]) -> dict[str, Any]:
    columns = payload.get("columns")
    data = payload.get("data")
    if not isinstance(columns, list) or not isinstance(data, list) or not data:
        return {}

    names: list[str] = []
    for column in columns:
        if isinstance(column, dict):
            name = column.get("name")
        else:
            name = column
        if not isinstance(name, str):
            return {}
        names.append(name)

    first_row = data[0]
    if not isinstance(first_row, list):
        return {}
    return {
        name: first_row[index]
        for index, name in enumerate(names)
        if index < len(first_row)
    }


def _safe_attributes(payload: dict[str, Any]) -> dict[str, Any]:
    attrs = _find_first_key(payload, {"attributes"})
    return attrs if isinstance(attrs, dict) else {}


def _top_stack_frame(stacktrace: str | None) -> str | None:
    if not stacktrace:
        return None
    py_match = PY_STACK_RE.search(stacktrace)
    if py_match:
        path, line, function = py_match.groups()
        return f"{path}:{line}:{function.strip()}"
    js_match = JS_STACK_RE.search(stacktrace)
    if js_match:
        function, path, line, _column = js_match.groups()
        function = function or "<anonymous>"
        return f"{path}:{line}:{function.strip()}"
    first_line = stacktrace.strip().splitlines()[0] if stacktrace.strip() else None
    return first_line[:300] if first_line else None


def _find_first_key(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in keys:
                return item
        for item in value.values():
            found = _find_first_key(item, keys)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_first_key(item, keys)
            if found not in (None, ""):
                return found
    return None


def _find_nested(value: Any, path: tuple[str, ...]) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _flatten_text(value: Any, *, max_chars: int = 50_000) -> str:
    parts: list[str] = []

    def visit(item: Any) -> None:
        if sum(len(part) for part in parts) >= max_chars:
            return
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)
        elif item is not None and isinstance(item, int | float | bool):
            parts.append(str(item))

    visit(value)
    return "\n".join(parts)[:max_chars]


def _extract_url(value: Any) -> str | None:
    text = _flatten_text(value, max_chars=20_000)
    match = re.search(r"https?://[^\s<>\"]+", text)
    return match.group(0) if match else None


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _route_without_method(route: str | None) -> str | None:
    if not route:
        return None
    method, _, path = route.partition(" ")
    if method.isalpha() and path.startswith("/"):
        return path
    return route


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return str(value)


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
