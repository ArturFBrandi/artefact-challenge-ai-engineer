"""One injectable clock, so every date rule can be frozen for demos and tests."""

from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def __init__(self, timezone: str) -> None:
        self._zone = ZoneInfo(timezone)

    def now(self) -> datetime:
        return datetime.now(self._zone)


class FrozenClock:
    def __init__(self, moment: datetime, timezone: str = "America/Campo_Grande") -> None:
        self._moment = moment.astimezone(ZoneInfo(timezone))

    def now(self) -> datetime:
        return self._moment


def build_clock(frozen_at: datetime | None, timezone: str) -> Clock:
    return FrozenClock(frozen_at, timezone) if frozen_at else SystemClock(timezone)
