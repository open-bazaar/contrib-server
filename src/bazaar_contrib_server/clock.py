"""The server's clock, and moments as the viewer reads them."""

from __future__ import annotations

lazy from datetime import datetime, tzinfo
lazy from time import time_ns
lazy from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def now_ms() -> int:
    return time_ns() // 1_000_000


def zone(name: str | None) -> tzinfo | None:
    """The viewer's zone by IANA name; nothing when there is none, so each
    moment is read on the server's own clock, daylight time as it was then."""
    if name:
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError, ValueError:
            pass
    return None


def clock_text(at_ms: int, tz: tzinfo | None) -> str:
    """A moment on the viewer's clock: the time of day, with the date before
    it when the day is not today's."""
    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    form = "%H:%M:%S" if at_ms >= today.timestamp() * 1000 else "%Y-%m-%d %H:%M:%S"
    return datetime.fromtimestamp(at_ms / 1000, tz).strftime(form)


def day_text(at_ms: int, tz: tzinfo | None) -> str:
    """The day a moment falls on, on the viewer's calendar."""
    return datetime.fromtimestamp(at_ms / 1000, tz).strftime("%Y-%m-%d")


def time_text(at_ms: int, tz: tzinfo | None) -> str:
    """The time of day of a moment, whatever the day."""
    return datetime.fromtimestamp(at_ms / 1000, tz).strftime("%H:%M:%S")
