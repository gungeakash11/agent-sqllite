import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class ReviewStatus(str, enum.Enum):
    CREATED = "created"           # job created, docs may still be uploading
    READY = "ready"                # docs uploaded, not yet analyzed (M1 end-state)
    PREPROCESSING = "preprocessing"  # M2: ingestion pipeline running
    ANALYZING = "analyzing"        # M4+
    PAUSED = "paused"              # M5
    COMPLETED = "completed"        # M6
    FAILED = "failed"


class ReviewJob(Base):
    """
    A single vendor due diligence review, owned by a User.
    This is the aggregate root that Documents, agent findings, and the
    final report all hang off of in later milestones.
    """
    __tablename__ = "review_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    vendor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    review_context: Mapped[str] = mapped_column(Text, nullable=True)

    status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status"), default=ReviewStatus.CREATED, nullable=False
    )

    # Configuration captured now, used from Milestone 4 onward
    analysis_depth: Mapped[str] = mapped_column(String(20), default="standard", nullable=False)
    enabled_checks: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # List of check IDs to execute
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)  # Injected context mid-review

    # LangGraph Execution Checkpointing
    current_node: Mapped[str | None] = mapped_column(String(100), nullable=True)
    paused_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)     # Serialized workflow state dict

    # Milestone 3 — progress tracking (updated by ingestion pipeline)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_stage: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    findings = relationship("Finding", back_populates="review_job", cascade="all, delete-orphan")
    agent_runs = relationship("AgentRun", back_populates="review_job", cascade="all, delete-orphan")
