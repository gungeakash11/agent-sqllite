"""
Semantic search endpoint — M2 evidence discovery.

POST /api/v1/reviews/{review_id}/search
Returns the most relevant document chunks for a natural language query,
with source document references. Requires the review to have completed
preprocessing (status = ready or beyond).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.reviews import _get_owned_review_or_404
from app.core.database import get_db
from app.models.review_job import ReviewStatus
from app.models.user import User
from app.schemas.search import ChunkResult, SearchRequest, SearchResponse
from app.services.retrieval import search_chunks

router = APIRouter(prefix="/api/v1/reviews", tags=["Search"])


@router.post(
    "/{review_id}/search",
    response_model=SearchResponse,
    summary="Semantic search over preprocessed documents (M2)",
)
async def search_documents(
    review_id: uuid.UUID,
    body: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Search uploaded documents using natural language.

    Embeds the query and runs a pgvector cosine similarity search over
    all embedded chunks for this review job. Returns the top matching
    excerpts with source document references.

    The review must have at least started preprocessing (status ≠ created/ready
    with 0 chunks is fine — we return an empty result, not an error).
    """
    review = await _get_owned_review_or_404(review_id, current_user, db)

    if review.status == ReviewStatus.CREATED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No documents have been uploaded to this review yet.",
        )

    results = await search_chunks(review_id, body.query, db, top_k=body.top_k)

    return SearchResponse(
        query=body.query,
        results=[
            ChunkResult(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                source_filename=r.source_filename,
                chunk_index=r.chunk_index,
                content=r.content,
                similarity=r.similarity,
            )
            for r in results
        ],
        total_results=len(results),
    )
