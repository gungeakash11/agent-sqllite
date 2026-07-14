"""
LangGraph Orchestrator — sets up the StateGraph workflow, defines the
transition edges, implements database checkpointing, and provides
start/pause/resume capability.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import progress as prog
from app.core.database import AsyncSessionLocal
from app.models.agent_run import AgentRun
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.models.finding import Finding
from app.models.review_job import ReviewJob, ReviewStatus
from app.services.agents import (
    AgentState,
    classifier_node,
    contradiction_node,
    evidence_retrieval_node,
    gap_detection_node,
    risk_review_node,
    summary_node,
)

logger = logging.getLogger(__name__)

# ---- LangGraph Flow Setup -------------------------------------------------

workflow = StateGraph(AgentState)

workflow.add_node("classifier", classifier_node)
workflow.add_node("retrieval", evidence_retrieval_node)
workflow.add_node("risk_review", risk_review_node)
workflow.add_node("gap_detection", gap_detection_node)
workflow.add_node("contradiction", contradiction_node)
workflow.add_node("summary", summary_node)

workflow.set_entry_point("classifier")

workflow.add_edge("classifier", "retrieval")
workflow.add_edge("retrieval", "risk_review")
workflow.add_edge("risk_review", "gap_detection")
workflow.add_edge("gap_detection", "contradiction")
workflow.add_edge("contradiction", "summary")
workflow.add_edge("summary", END)

# In-memory checkpointer to serialize intermediate states before we save to DB
checkpointer = MemorySaver()
app_graph = workflow.compile(checkpointer=checkpointer)


# ---- Database Helpers -----------------------------------------------------

async def _get_review_status(review_id: uuid.UUID) -> ReviewStatus:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ReviewJob.status).where(ReviewJob.id == review_id))
        return result.scalar_one_or_none() or ReviewStatus.FAILED


async def _save_intermediate_findings(
    review_id: uuid.UUID,
    findings: list[dict],
    db: AsyncSession,
) -> None:
    """Save any new findings generated during a node run."""
    # Delete existing findings first so we don't duplicate on resume
    await db.execute(
        Finding.__table__.delete().where(Finding.review_job_id == review_id)
    )

    for item in findings:
        doc_id_val = item.get("source_document_id")
        doc_uuid = None
        if doc_id_val:
            try:
                doc_uuid = uuid.UUID(str(doc_id_val))
            except ValueError:
                pass

        finding = Finding(
            review_job_id=review_id,
            source_document_id=doc_uuid,
            finding_type=item["finding_type"],
            description=item["description"],
            confidence=item.get("confidence", 1.0),
        )
        db.add(finding)
    await db.commit()


async def _log_agent_run(
    review_id: uuid.UUID,
    agent_name: str,
    status: str,
    output: dict | None = None,
    tokens: int = 0,
) -> None:
    """Write agent execution log to agent_runs table."""
    async with AsyncSessionLocal() as db:
        run = AgentRun(
            review_job_id=review_id,
            agent_name=agent_name,
            status=status,
            output=output,
            tokens_used=tokens,
            completed_at=datetime.utcnow() if status != "running" else None,
        )
        db.add(run)
        await db.commit()


# ---- Orchestrator Runner --------------------------------------------------

async def run_analysis(review_id: uuid.UUID) -> None:
    """
    Runs the multi-agent LangGraph workflow background task.
    Supports mid-flight pauses and resumes from saved checkpoints.
    """
    thread_config = {"configurable": {"thread_id": str(review_id)}}

    async with AsyncSessionLocal() as db:
        # Load review details, documents, and existing custom instructions
        review_result = await db.execute(select(ReviewJob).where(ReviewJob.id == review_id))
        review = review_result.scalar_one_or_none()
        if not review:
            logger.error("Analysis: Review %s not found", review_id)
            return

        docs_result = await db.execute(select(Document).where(Document.review_job_id == review_id))
        docs = docs_result.scalars().all()
        doc_dicts = [
            {"id": str(d.id), "original_filename": d.original_filename, "document_type": d.document_type}
            for d in docs
        ]

        # Fetch relevant chunks to populate state context
        chunks_result = await db.execute(select(DocumentChunk.content).where(DocumentChunk.review_job_id == review_id))
        chunks = chunks_result.scalars().all()
        context_str = "\n\n".join(chunks[:30])  # limit to top 30 chunks to prevent context overflow

        # Re-construct state from DB or start fresh
        if review.paused_state:
            logger.info("Restoring analysis checkpoint for review %s", review_id)
            state = review.paused_state
            # Ensure latest doc list and instructions are updated
            state["documents"] = doc_dicts
            state["retrieved_context"] = context_str
            state["custom_instructions"] = review.custom_instructions or ""
            # Load state into MemorySaver checkpointer via app_graph
            await app_graph.aupdate_state(thread_config, state)
        else:
            state = AgentState(
                review_job_id=str(review_id),
                focus_areas=review.enabled_checks or ["mfa", "encryption", "retention"],
                analysis_depth=review.analysis_depth,
                documents=doc_dicts,
                retrieved_context=context_str,
                findings=[],
                current_node="start",
                custom_instructions=review.custom_instructions or "",
                tokens_used=0,
            )

    # Sequence of LangGraph nodes we want to step through
    nodes_sequence = ["classifier", "retrieval", "risk_review", "gap_detection", "contradiction", "summary"]

    # Resume from last paused node if applicable
    start_index = 0
    if state.get("current_node") in nodes_sequence:
        start_index = nodes_sequence.index(state["current_node"]) + 1

    total_steps = len(nodes_sequence)

    for step_idx in range(start_index, total_steps):
        node_name = nodes_sequence[step_idx]

        # Check if the user paused the job before running this node
        status = await _get_review_status(review_id)
        if status == ReviewStatus.PAUSED:
            logger.info("Analysis paused before executing node %s", node_name)
            await prog.add_event(str(review_id), "Analysis paused by user. State saved.", "warning")
            return

        # Update DB with current progress state
        progress_pct = int(((step_idx) / total_steps) * 100)
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(ReviewJob)
                .where(ReviewJob.id == review_id)
                .values(
                    status=ReviewStatus.ANALYZING,
                    progress_pct=progress_pct,
                    current_node=node_name,
                    current_stage=f"Agent running: {node_name.replace('_', ' ').title()}",
                    paused_state=state,
                )
            )
            await db.commit()

        await prog.add_event(
            str(review_id),
            f"Agent active: {node_name.replace('_', ' ').title()}",
            "info",
        )

        # Log node start
        await _log_agent_run(review_id, node_name, "running")

        try:
            # Introduce a small delay to mimic agent processing and allow pause/resume coordination
            await asyncio.sleep(0.5)
            # Execute node via LangGraph
            state = await app_graph.ainvoke(state, thread_config)

            # Log completion and update findings
            await _log_agent_run(
                review_id,
                node_name,
                "completed",
                output={"findings_count": len(state.get("findings", []))},
                tokens=state.get("tokens_used", 0),
            )

            # Sync intermediate findings to DB (supports in-flight Q&A)
            async with AsyncSessionLocal() as db:
                await _save_intermediate_findings(review_id, state.get("findings", []), db)

        except Exception as exc:
            logger.exception("Node %s failed for review %s", node_name, review_id)
            await _log_agent_run(review_id, node_name, "failed", output={"error": str(exc)})
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(ReviewJob)
                    .where(ReviewJob.id == review_id)
                    .values(status=ReviewStatus.FAILED, current_stage="Analysis failed")
                )
                await db.commit()
            await prog.add_event(str(review_id), f"✗ Analysis failed at {node_name}: {exc}", "error")
            return

    # Ingestion flow is fully completed
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ReviewJob)
            .where(ReviewJob.id == review_id)
            .values(
                status=ReviewStatus.COMPLETED,
                progress_pct=100,
                current_stage="Analysis complete",
                paused_state=None,  # clear state on completion
            )
        )
        await db.commit()

    await prog.add_event(str(review_id), "✓ Milestone complete: Multi-agent review finished.", "milestone")
