"""
Retrieval service — semantic search over embedded document chunks.

Embeds the user's query and runs a pgvector cosine similarity search
over document_chunks for a specific review job. Returns the top-k
most relevant chunks with source document references.

Called by the POST /reviews/{id}/search endpoint (FR-2.5).
"""
import logging
import uuid
from dataclasses import dataclass

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Integer, String, Text, cast, func, literal, text
from sqlalchemy.ext.asyncio import AsyncSession

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


async def search_chunks(
    review_job_id: uuid.UUID,
    query: str,
    db: AsyncSession,
    top_k: int = DEFAULT_TOP_K,
) -> list[ChunkResult]:
    """
    Find the most relevant document chunks for a natural language query.

    1. Embed the query string.
    2. Run pgvector cosine similarity search scoped to the review job.
    3. Return top_k results with source document references.

    Returns an empty list if the review has no embedded chunks yet.
    """
    if not query.strip():
        return []

    # Embed the query
    query_embedding = await embed_single(query)

    # pgvector cosine distance operator: <=>
    # asyncpg conflicts with ::vector cast in raw SQL alongside :param bindings.
    # Solution: embed the vector literal directly into the SQL string (safe —
    # it's a float array from OpenAI, not user input) and use :param only for
    # the scalar UUIDs and integers.
    vec_literal = "[" + ",".join(str(f) for f in query_embedding) + "]"

    sql = text(f"""
        SELECT
            dc.id::text            AS chunk_id,
            dc.document_id::text   AS document_id,
            d.original_filename    AS source_filename,
            dc.chunk_index,
            dc.content,
            1 - (dc.embedding <=> '{vec_literal}'::vector) AS similarity
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE dc.review_job_id = :review_job_id
          AND dc.embedding IS NOT NULL
        ORDER BY dc.embedding <=> '{vec_literal}'::vector
        LIMIT :top_k
    """)

    result = await db.execute(
        sql,
        {
            "review_job_id": str(review_job_id),
            "top_k": top_k,
        },
    )
    rows = result.fetchall()

    return [
        ChunkResult(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            source_filename=row.source_filename,
            chunk_index=row.chunk_index,
            content=row.content,
            similarity=round(float(row.similarity), 4),
        )
        for row in rows
    ]
