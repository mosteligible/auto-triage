from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utc_now() -> datetime:
    return datetime.now(UTC)


def lease_until(seconds: int, *, now: datetime | None = None) -> datetime:
    base = now or utc_now()
    return base + timedelta(seconds=seconds)


def is_past(value: datetime | None, *, now: datetime | None = None) -> bool:
    if value is None:
        return False
    return value <= (now or utc_now())

