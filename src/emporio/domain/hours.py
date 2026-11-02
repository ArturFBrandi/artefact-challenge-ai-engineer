"""Store hours, in the store's timezone."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from emporio.domain.rules import StoreFacts


@dataclass(frozen=True)
class StoreStatus:
    is_open: bool
    next_opening: datetime | None
    closes_at: datetime | None


def is_holiday(day: date, facts: StoreFacts) -> bool:
    return day.strftime("%m-%d") in facts.holidays_fixed or day.isoformat() in (
        facts.holidays_movable
    )


def _span(day: date, facts: StoreFacts) -> tuple[time, time] | None:
    if is_holiday(day, facts):
        return None
    span = facts.hours.get(day.weekday())
    return (time.fromisoformat(span[0]), time.fromisoformat(span[1])) if span else None


def store_status(now: datetime, facts: StoreFacts) -> StoreStatus:
    span = _span(now.date(), facts)
    if span and span[0] <= now.time() < span[1]:
        return StoreStatus(True, None, datetime.combine(now.date(), span[1], now.tzinfo))

    if span and now.time() < span[0]:
        return StoreStatus(False, datetime.combine(now.date(), span[0], now.tzinfo), None)

    day = now.date()
    for _ in range(14):
        day += timedelta(days=1)
        span = _span(day, facts)
        if span:
            return StoreStatus(False, datetime.combine(day, span[0], now.tzinfo), None)
    raise ValueError("No opening found in the next two weeks; check store_facts.yaml")
