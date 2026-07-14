"""Pydantic schemas for the M3 real-time progress polling endpoint."""
from typing import Literal

from pydantic import BaseModel


class ProgressEvent(BaseModel):
    index: int
    message: str
    event_type: Literal["info", "warning", "error", "milestone"]
    timestamp: str  # ISO-8601 UTC


class ProgressResponse(BaseModel):
    review_id: str
    status: str                  # ReviewStatus enum value
    progress_pct: int            # 0–100
    current_stage: str           # human-readable label
    events: list[ProgressEvent]  # new events since `since`
    next_since: int              # client passes this as ?since= on next poll
