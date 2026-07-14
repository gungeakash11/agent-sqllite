import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class FindingResponse(BaseModel):
    id: uuid.UUID
    review_job_id: uuid.UUID
    source_document_id: uuid.UUID | None
    finding_type: str  # risk, gap, contradiction
    description: str
    confidence: float
    created_at: datetime

    model_config = {"from_attributes": True}


# ---- In-flight & Post-analysis Q&A ---------------------------------------

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)


class AskResponse(BaseModel):
    question: str
    answer: str
    cited_findings: list[FindingResponse]


# ---- Custom Context Injection ---------------------------------------------

class InstructionsRequest(BaseModel):
    custom_instructions: str = Field(..., max_length=5000)
