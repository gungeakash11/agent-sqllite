import asyncio
import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from openai import AsyncOpenAI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core import progress as prog
from app.core.config import get_settings
from app.core.database import get_db
from app.models.chunk import DocumentChunk
from app.models.finding import Finding
from app.models.review_job import ReviewJob, ReviewStatus
from app.models.user import User, UserRole
from app.schemas.findings import AskRequest, AskResponse, FindingResponse, InstructionsRequest
from app.schemas.review import ReviewJobCreate, ReviewJobResponse
from app.services.orchestrator import run_analysis

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/v1/reviews", tags=["Vendor Reviews"])

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def _get_owned_review_or_404(review_id: uuid.UUID, current_user: User, db: AsyncSession) -> ReviewJob:
    result = await db.execute(select(ReviewJob).where(ReviewJob.id == review_id))
    review = result.scalar_one_or_none()
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review job not found.")
    # Admins can view any job (Milestone 7); regular users only their own.
    if current_user.role != UserRole.ADMIN and review.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this review.")
    return review


@router.post("", response_model=ReviewJobResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    payload: ReviewJobCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create vendor review job with configuration templates."""
    review = ReviewJob(
        owner_id=current_user.id,
        vendor_name=payload.vendor_name,
        review_context=payload.review_context,
        analysis_depth=payload.analysis_depth,
        enabled_checks=payload.enabled_checks or ["mfa", "encryption", "retention"],
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    return review


@router.get("", response_model=list[ReviewJobResponse])
async def list_my_reviews(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List review jobs owned by current user."""
    result = await db.execute(
        select(ReviewJob).where(ReviewJob.owner_id == current_user.id).order_by(ReviewJob.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{review_id}", response_model=ReviewJobResponse)
async def get_review(
    review_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _get_owned_review_or_404(review_id, current_user, db)


# ---- Milestone 4 & 5 Controls ---------------------------------------------

@router.post("/{review_id}/analyze", response_model=ReviewJobResponse)
async def analyze_review(
    review_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start the multi-agent review analysis (Milestone 4)."""
    review = await _get_owned_review_or_404(review_id, current_user, db)

    if review.status in (ReviewStatus.ANALYZING, ReviewStatus.PREPROCESSING):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Review is already undergoing preprocessing or analysis.",
        )

    review.status = ReviewStatus.ANALYZING
    review.progress_pct = 0
    review.current_stage = "Orchestrating agents"
    await db.commit()
    await db.refresh(review)

    # Launch background task
    asyncio.create_task(run_analysis(review_id))
    return review


@router.post("/{review_id}/pause", response_model=ReviewJobResponse)
async def pause_review(
    review_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pause running analysis (Milestone 5)."""
    review = await _get_owned_review_or_404(review_id, current_user, db)

    if review.status != ReviewStatus.ANALYZING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot pause review in '{review.status}' state.",
        )

    review.status = ReviewStatus.PAUSED
    review.current_stage = "Paused by reviewer"
    await db.commit()
    await db.refresh(review)
    return review


@router.post("/{review_id}/resume", response_model=ReviewJobResponse)
async def resume_review(
    review_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused review from the checkpoint (Milestone 5)."""
    review = await _get_owned_review_or_404(review_id, current_user, db)

    if review.status != ReviewStatus.PAUSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot resume review in '{review.status}' state.",
        )

    review.status = ReviewStatus.ANALYZING
    review.current_stage = "Resuming analysis"
    await db.commit()
    await db.refresh(review)

    # Restart background worker
    asyncio.create_task(run_analysis(review_id))
    return review


@router.post("/{review_id}/instructions", response_model=ReviewJobResponse)
async def update_instructions(
    review_id: uuid.UUID,
    payload: InstructionsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Inject custom context/instructions mid-review (Milestone 5)."""
    review = await _get_owned_review_or_404(review_id, current_user, db)
    review.custom_instructions = payload.custom_instructions
    await db.commit()
    await db.refresh(review)
    await prog.add_event(str(review_id), "Custom review instructions updated.", "info")
    return review


@router.get("/{review_id}/findings", response_model=list[FindingResponse])
async def list_findings(
    review_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get findings list generated so far (Milestone 4/5)."""
    await _get_owned_review_or_404(review_id, current_user, db)
    result = await db.execute(
        select(Finding).where(Finding.review_job_id == review_id).order_by(Finding.created_at.asc())
    )
    return result.scalars().all()
@router.get("/{review_id}/runs")
async def list_agent_runs(
    review_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List execution history and token usage of each agent run."""
    await _get_owned_review_or_404(review_id, current_user, db)
    from app.models.agent_run import AgentRun
    result = await db.execute(
        select(AgentRun).where(AgentRun.review_job_id == review_id).order_by(AgentRun.started_at.asc())
    )
    runs = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "agent_name": r.agent_name,
            "status": r.status,
            "output": r.output,
            "tokens_used": r.tokens_used,
            "started_at": r.started_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in runs
    ]



@router.post("/{review_id}/ask", response_model=AskResponse)
async def ask_question(
    review_id: uuid.UUID,
    payload: AskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Q&A Panel — answer queries using currently available findings & chunks (Milestone 5/6).
    Answers are grounded in findings and source cites.
    """
    review = await _get_owned_review_or_404(review_id, current_user, db)

    # Load findings
    findings_result = await db.execute(select(Finding).where(Finding.review_job_id == review_id))
    findings = findings_result.scalars().all()

    # Load chunks for context matching
    chunks_result = await db.execute(select(DocumentChunk.content).where(DocumentChunk.review_job_id == review_id))
    chunks = chunks_result.scalars().all()

    findings_summary = "\n".join(
        f"- [{f.finding_type.upper()}] {f.description}" for f in findings
    )
    text_context = "\n\n".join(chunks[:20])

    sys_prompt = (
        "You are the Due Diligence assistant. Answer the user's question.\n"
        "Grounded ONLY in the provided findings and text snippets, provide a factual answer.\n"
        "Cite the specific documents or claims made in your response.\n"
        "If you do not know or it is not mentioned, say: 'I cannot find evidence for this in the provided packages.'"
    )

    user_prompt = (
        f"Vendor Name: {review.vendor_name}\n"
        f"Question: {payload.question}\n\n"
        f"Findings so far:\n{findings_summary}\n\n"
        f"Extracted document text:\n{text_context}\n"
    )

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        answer = response.choices[0].message.content or "No answer generated."
    except Exception as exc:
        logger.error("Q&A call failed: %s", exc)
        answer = f"Error generating answer: {exc}"

    # Return matching findings as citations
    cite_responses = [FindingResponse.model_validate(f) for f in findings]

    return AskResponse(
        question=payload.question,
        answer=answer,
        cited_findings=cite_responses,
    )
