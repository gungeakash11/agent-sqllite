import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.review_job import ReviewStatus


class ReviewJobCreate(BaseModel):
    vendor_name: str = Field(..., min_length=1, max_length=255)
    review_context: str | None = Field(default=None, max_length=5000)
    analysis_depth: str = Field(default="standard", description="quick, standard, or deep")
    enabled_checks: list[str] | None = Field(
        default=None, description="Checklist IDs to execute, e.g. ['mfa', 'encryption', 'retention']"
    )


class ReviewJobResponse(BaseModel):
    id: uuid.UUID
    vendor_name: str
    review_context: str | None
    status: ReviewStatus
    analysis_depth: str
    enabled_checks: list[str] | None
    custom_instructions: str | None
    current_node: str | None
    progress_pct: int
    current_stage: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
