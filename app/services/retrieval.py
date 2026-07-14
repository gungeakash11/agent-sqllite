"""
Retrieval service — semantic search over embedded document chunks.
Uses Python-based cosine similarity to remain compatible with SQLite.
"""
import logging
import uuid
import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.services.embedding import embed_single

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5


@dataclass
class ChunkResult:
    chunk_id: str
    document_id: str
    source_filename: str
    chunk_index: int
    content: str
    similarity: float


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2:
        return 0.0
    dot_product = sum(x * y for x, y in zip(v1, v2))
    norm_a = math.sqrt(sum(x * x for x in v1))
    norm_b = math.sqrt(sum(y * y for y in v2))
    return dot_product / (norm_a * norm_b) if (norm_a * norm_b) else 0.0


async def search_chunks(
    review_job_id: uuid.UUID,
    query: str,
    db: AsyncSession,
    top_k: int = DEFAULT_TOP_K,
) -> list[ChunkResult]:
    """
    Find the most relevant document chunks for a natural language query.
    Uses in-memory cosine similarity compatible with SQLite.
    """
    if not query.strip():
        return []

    # Embed the query
    query_embedding = await embed_single(query)

    # Fetch all chunks and document names
    stmt = (
        select(DocumentChunk, Document.original_filename)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.review_job_id == review_job_id)
        .where(DocumentChunk.embedding != None)
    )

    result = await db.execute(stmt)
    rows = result.all()

    scored_results = []
    for chunk, original_filename in rows:
        sim = cosine_similarity(chunk.embedding, query_embedding)
        scored_results.append((chunk, original_filename, sim))

    # Sort by similarity descending
    scored_results.sort(key=lambda x: x[2], reverse=True)

    return [
        ChunkResult(
            chunk_id=str(chunk.id),
            document_id=str(chunk.document_id),
            source_filename=original_filename,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            similarity=round(sim, 4),
        )
        for chunk, original_filename, sim in scored_results[:top_k]
    ]
