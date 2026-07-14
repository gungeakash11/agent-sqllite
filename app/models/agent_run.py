"""
AgentRun ORM Model — stores execution metadata, status, token usage, 
and outputs for each agent in the LangGraph workflow.
"""
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("review_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="running", nullable=False)  # running, completed, failed
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)                  # intermediate LLM output JSON
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    started_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Relationships
    review_job = relationship("ReviewJob", back_populates="agent_runs")
