"""Time helpers: storage always in UTC, display in Europe/Madrid."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from app.core.config import get_settings

settings = get_settings()
MADRID = ZoneInfo(settings.warehouse_timezone)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_madrid(value: datetime | None) -> datetime | None:
    value = ensure_utc(value)
    return value.astimezone(MADRID) if value else None


def madrid_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(day, time.min, tzinfo=MADRID)
    end_local = datetime.combine(day, time.max, tzinfo=MADRID)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
