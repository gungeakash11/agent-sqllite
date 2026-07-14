import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.document import DocumentStatus


class DocumentResponse(BaseModel):
    id: uuid.UUID
    review_job_id: uuid.UUID
    original_filename: str
    content_type: str | None
    file_size_bytes: int
    status: DocumentStatus
    rejection_reason: str | None
    document_type: str | None = None   # set after M2 preprocessing
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class DocumentUploadSummary(BaseModel):
    """Returned after a batch upload: what was accepted vs rejected, and why."""
    accepted: list[DocumentResponse]
    rejected: list[dict]  # [{"filename": ..., "reason": ...}]
