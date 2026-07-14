"""
In-memory progress event store for M3 real-time progress tracking.

Each review job accumulates a list of ProgressEvent objects while the M2
ingestion pipeline runs. The progress polling endpoint reads from here.

Design note: in-memory is sufficient for a single-process dev/assessment
deployment. A future multi-process deployment (M4+) can swap this for a
Redis-backed or DB-backed store without changing the callers.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

# ---- Types ---------------------------------------------------------------

EventType = Literal["info", "warning", "error", "milestone"]


@dataclass
class ProgressEvent:
    index: int
    message: str
    event_type: EventType
    timestamp: str  # ISO-8601 UTC string


# ---- Store ---------------------------------------------------------------

# review_id (str) → list of ProgressEvent
_store: dict[str, list[ProgressEvent]] = {}
_lock = asyncio.Lock()


async def add_event(review_id: str, message: str, event_type: EventType = "info") -> None:
    """Append a progress event for a review job."""
    async with _lock:
        events = _store.setdefault(review_id, [])
        events.append(
            ProgressEvent(
                index=len(events),
                message=message,
                event_type=event_type,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )


def get_events(review_id: str, since: int = 0) -> list[ProgressEvent]:
    """
    Return all events for a review job with index >= since.
    since=0 returns everything (initial page load).
    Subsequent polls pass the last received index + 1.
    Thread-safe for reads since list appends in CPython are GIL-protected.
    """
    return _store.get(review_id, [])[since:]


def clear_events(review_id: str) -> None:
    """Remove all events for a review (called on re-run or cleanup)."""
    _store.pop(review_id, None)
