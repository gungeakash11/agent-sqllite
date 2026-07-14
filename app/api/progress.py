"""
Progress polling endpoint — M3 real-time progress visibility.

GET /api/v1/reviews/{review_id}/progress?since=0

Returns the current preprocessing status, percentage, stage label, and
any new activity feed events since the last poll.

Clients (e.g., Streamlit) call this every ~2s while status == preprocessing.
The `since` query parameter allows incremental updates — pass the
`next_since` value from the previous response to get only new events.
"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.reviews import _get_owned_review_or_404
from app.core import progress as prog
from app.core.database import get_db
from app.models.user import User
from app.schemas.progress import ProgressEvent, ProgressResponse

router = APIRouter(prefix="/api/v1/reviews", tags=["Progress"])


@router.get(
    "/{review_id}/progress",
    response_model=ProgressResponse,
    summary="Live preprocessing progress feed (M3)",
)
async def get_progress(
    review_id: uuid.UUID,
    since: int = Query(0, ge=0, description="Return only events with index >= since"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Poll the current preprocessing progress for a review job.

    Returns:
    - **status**: current ReviewStatus value
    - **progress_pct**: 0–100 completion estimate
    - **current_stage**: human-readable label of the active step
    - **events**: activity feed entries (new since `since`)
    - **next_since**: pass this as `?since=` on the next poll call

    Poll this endpoint every 2s while `status == preprocessing`.
    Stop polling when `status` is `ready`, `failed`, or `completed`.
    """
    review = await _get_owned_review_or_404(review_id, current_user, db)

    new_events = prog.get_events(str(review_id), since=since)

    return ProgressResponse(
        review_id=str(review_id),
        status=review.status.value,
        progress_pct=review.progress_pct,
        current_stage=review.current_stage,
        events=[
            ProgressEvent(
                index=e.index,
                message=e.message,
                event_type=e.event_type,
                timestamp=e.timestamp,
            )
            for e in new_events
        ],
        next_since=since + len(new_events),
    )
