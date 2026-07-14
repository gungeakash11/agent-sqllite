"""
Finding ORM Model — stores a specific risk, gap, or contradiction detected 
by the multi-agent analysis.
"""
import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("review_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The source document containing the evidence (nullable for cross-doc contradictions or general gaps)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )

    finding_type: Mapped[str] = mapped_column(String(50), nullable=False)  # risk, gap, contradiction
    description: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    # Relationships
    review_job = relationship("ReviewJob", back_populates="findings")
    document = relationship("Document")
