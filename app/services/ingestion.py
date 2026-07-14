"""
Ingestion service — orchestrates the full M2 preprocessing pipeline for
all documents in a review job.

Pipeline per document:
  1. Extract text from the stored file
  2. Classify document type via LLM
  3. Chunk the text into logical segments
  4. Embed all chunks via OpenAI
  5. Persist chunks + embeddings to document_chunks table
  6. Embed the full document (document-level vector)
  7. Mark document as PROCESSED

Progress events (M3) are emitted throughout so the polling endpoint
can report live status to the UI.

This function is called as an asyncio background task from the
documents upload endpoint. It manages its own DB session so it doesn't
block or outlive the upload request session.
"""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core import progress as prog
from app.models.chunk import DocumentChunk
from app.models.document import Document, DocumentStatus
from app.models.review_job import ReviewJob, ReviewStatus
from app.services.classification import classify_document
from app.services.chunking import chunk_text
from app.services.embedding import embed_single, embed_texts
from app.services.extraction import extract_text

logger = logging.getLogger(__name__)


async def _update_review_progress(
    db: AsyncSession,
    review: ReviewJob,
    pct: int,
    stage: str,
    event_message: str,
    event_type: prog.EventType = "info",
) -> None:
    """Update DB progress fields and emit an in-memory progress event."""
    review.progress_pct = pct
    review.current_stage = stage
    await db.commit()
    await prog.add_event(str(review.id), event_message, event_type)


async def run_ingestion(review_job_id: uuid.UUID) -> None:
    """
    Full M2 ingestion pipeline for a review job.
    Creates its own DB session — safe to run as an asyncio background task.
    """
    async with AsyncSessionLocal() as db:
        # Load review and all uploaded (non-rejected) documents
        review_result = await db.execute(
            select(ReviewJob).where(ReviewJob.id == review_job_id)
        )
        review = review_result.scalar_one_or_none()
        if review is None:
            logger.error("Ingestion: review %s not found", review_job_id)
            return

        docs_result = await db.execute(
            select(Document).where(
                Document.review_job_id == review_job_id,
                Document.status == DocumentStatus.UPLOADED,
            )
        )
        documents = list(docs_result.scalars().all())

        if not documents:
            review.status = ReviewStatus.READY
            review.progress_pct = 100
            review.current_stage = "No documents to process"
            await db.commit()
            await prog.add_event(str(review_job_id), "No documents to process — review is ready.", "warning")
            return

        total = len(documents)
        await _update_review_progress(
            db, review, 0, "Starting preprocessing",
            f"Starting preprocessing for {total} document(s).", "milestone"
        )

        try:
            for i, doc in enumerate(documents):
                file_label = f"file {i + 1}/{total}: {doc.original_filename}"
                base_pct = int((i / total) * 90)  # reserve 90% for per-file work, 10% for finalization

                # --- Step 1: Extract text ---
                await _update_review_progress(
                    db, review, base_pct + 5,
                    f"Extracting text ({i + 1}/{total})",
                    f"Extracting text from {file_label}",
                )
                text = extract_text(doc.stored_path)

                if not text.strip():
                    await prog.add_event(
                        str(review_job_id),
                        f"⚠ No extractable text in {doc.original_filename} — skipping.",
                        "warning",
                    )
                    doc.extracted_text = ""
                    doc.document_type = "Other"
                    doc.status = DocumentStatus.PROCESSED
                    await db.commit()
                    continue

                doc.extracted_text = text

                # --- Step 2: Classify document type ---
                await prog.add_event(
                    str(review_job_id),
                    f"Classifying document type for {doc.original_filename}",
                )
                doc_type = await classify_document(doc.original_filename, text)
                doc.document_type = doc_type
                await db.commit()
                await prog.add_event(
                    str(review_job_id),
                    f"Detected: {doc.original_filename} → {doc_type}",
                    "milestone",
                )

                # --- Step 3: Chunk text ---
                await _update_review_progress(
                    db, review, base_pct + 15,
                    f"Chunking ({i + 1}/{total})",
                    f"Breaking {doc.original_filename} into logical chunks",
                )
                chunks = chunk_text(text)

                if not chunks:
                    await prog.add_event(
                        str(review_job_id),
                        f"⚠ No chunks produced for {doc.original_filename}.",
                        "warning",
                    )
                    doc.status = DocumentStatus.PROCESSED
                    await db.commit()
                    continue

                await prog.add_event(
                    str(review_job_id),
                    f"Prepared {len(chunks)} evidence chunks from {doc.original_filename}",
                )

                # --- Step 4: Embed chunks ---
                await _update_review_progress(
                    db, review, base_pct + 25,
                    f"Building embeddings ({i + 1}/{total})",
                    f"Building embeddings for {doc.original_filename} ({len(chunks)} chunks)",
                )
                chunk_vectors = await embed_texts(chunks)

                # --- Step 5: Persist chunks ---
                chunk_objects = [
                    DocumentChunk(
                        document_id=doc.id,
                        review_job_id=review_job_id,
                        chunk_index=idx,
                        content=chunk_text_,
                        embedding=vector,
                    )
                    for idx, (chunk_text_, vector) in enumerate(zip(chunks, chunk_vectors))
                ]
                db.add_all(chunk_objects)

                # --- Step 6: Document-level embedding (first 2000 chars) ---
                doc_embedding = await embed_single(text[:2000])
                doc.embedding = doc_embedding
                doc.status = DocumentStatus.PROCESSED
                await db.commit()

                await prog.add_event(
                    str(review_job_id),
                    f"✓ Completed: {doc.original_filename} ({len(chunks)} chunks embedded)",
                    "milestone",
                )

            # --- Finalize ---
            await _update_review_progress(
                db, review, 100, "Preprocessing complete",
                "✓ Stage complete: Preprocessing — evidence is ready for search.",
                "milestone",
            )
            review.status = ReviewStatus.READY
            await db.commit()

        except Exception as exc:
            logger.exception("Ingestion failed for review %s", review_job_id)
            review.status = ReviewStatus.FAILED
            review.current_stage = "Preprocessing failed"
            await db.commit()
            await prog.add_event(
                str(review_job_id),
                f"✗ Preprocessing failed: {exc}",
                "error",
            )
