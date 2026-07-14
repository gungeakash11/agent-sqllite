"""
DocumentChunk — stores a single text chunk from a Document, with its
SQLite-compatible JSON array embedding. Semantic search queries this table, not the full document.

One Document → many DocumentChunks (created during M2 ingestion pipeline).
"""
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Parent references — both stored for efficient filtering by review
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    review_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("review_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)   # 0-based position within document
    content: Mapped[str] = mapped_column(Text, nullable=False)           # raw text of this chunk
    embedding: Mapped[list] = mapped_column(JSON, nullable=True)  # set after embed step

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
