import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.reviews import _get_owned_review_or_404
from app.core.config import get_settings
from app.core.database import get_db
from app.models.document import Document, DocumentStatus
from app.models.review_job import ReviewStatus
from app.models.user import User
from app.schemas.document import DocumentResponse, DocumentUploadSummary
from app.services.file_validation import validate_upload
from app.services.ingestion import run_ingestion

router = APIRouter(prefix="/api/v1/reviews", tags=["Documents"])
settings = get_settings()


@router.post("/{review_id}/documents", response_model=DocumentUploadSummary, status_code=status.HTTP_201_CREATED)
async def upload_documents(
    review_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Step 2/3 of the BRD user flow: upload vendor materials (questionnaires,
    DPAs, SOC reports, policies, contracts, etc.) to a review job.

    Each file is validated independently -- one bad file never blocks the
    rest of the batch. The response separates accepted vs rejected files
    with a human-readable reason for every rejection.
    """
    review = await _get_owned_review_or_404(review_id, current_user, db)

    review_dir = Path(settings.UPLOAD_DIR) / str(review.id)
    review_dir.mkdir(parents=True, exist_ok=True)

    accepted: list[Document] = []
    rejected: list[dict] = []

    for upload in files:
        result = await validate_upload(upload, review.id, db)

        if not result.is_valid:
            rejected.append({"filename": upload.filename, "reason": result.reason})
            continue

        stored_path = review_dir / f"{uuid.uuid4()}_{upload.filename}"
        stored_path.write_bytes(result.file_bytes)

        document = Document(
            review_job_id=review.id,
            original_filename=upload.filename,
            stored_path=str(stored_path),
            content_type=upload.content_type,
            file_size_bytes=len(result.file_bytes),
            file_hash=result.file_hash,
            status=DocumentStatus.UPLOADED,
        )
        db.add(document)
        accepted.append(document)

    await db.commit()
    for doc in accepted:
        await db.refresh(doc)

    # Kick off M2 ingestion pipeline as a background task if any files were accepted.
    # This sets status → PREPROCESSING and processes files asynchronously so the
    # upload response is immediate (not blocked on text extraction / embedding calls).
    if accepted:
        review.status = ReviewStatus.PREPROCESSING
        review.progress_pct = 0
        review.current_stage = "Queued for preprocessing"
        await db.commit()
        asyncio.create_task(run_ingestion(review.id))

    return DocumentUploadSummary(accepted=accepted, rejected=rejected)


@router.get("/{review_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    review_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_review_or_404(review_id, current_user, db)
    result = await db.execute(select(Document).where(Document.review_job_id == review_id))
    return result.scalars().all()
