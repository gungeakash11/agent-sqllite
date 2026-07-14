"""
LangGraph Workflow Agent Nodes — individual agent reasoning steps.

Each node takes the shared AgentState and calls OpenAI to analyze extracted
document chunks, yielding structured findings, gaps, and contradictions.
"""
import json
import logging
from typing import Any, Dict, List, TypedDict
from openai import AsyncOpenAI

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


# ---- State Definition -----------------------------------------------------

class AgentState(TypedDict):
    review_job_id: str
    focus_areas: List[str]          # checklist IDs: e.g. ["mfa", "encryption", "retention"]
    analysis_depth: str             # quick, standard, deep
    documents: List[Dict[str, Any]]  # original files list
    retrieved_context: str          # text snippets combined
    findings: List[Dict[str, Any]]   # findings list appended sequentially
    current_node: str
    custom_instructions: str
    tokens_used: int


# ---- Helper to call LLM structured output ---------------------------------

async def _call_llm_json(system_prompt: str, user_prompt: str) -> Dict[str, Any]:
    client = _get_client()
    try:
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content or "{}"
        usage = response.usage
        tokens = usage.total_tokens if usage else 0
        parsed = json.loads(content)
        parsed["_tokens_used"] = tokens
        return parsed
    except Exception as exc:
        logger.error("LLM Call failed: %s", exc)
        return {"error": str(exc), "findings": [], "_tokens_used": 0}


# ---- Agent Nodes ----------------------------------------------------------

async def classifier_node(state: AgentState) -> Dict[str, Any]:
    """
    Agent 1: Classifier Agent
    Identifies Focus Areas and checks based on document list & analysis depth.
    """
    logger.info("Classifier Node running...")
    doc_summary = "\n".join(
        f"- {d['original_filename']} (Type: {d.get('document_type', 'Other')})"
        for d in state["documents"]
    )

    sys_prompt = (
        "You are the Classifier Agent for a Vendor Due Diligence system.\n"
        "Analyze the provided document list and configuration parameters.\n"
        "Determine the target focus areas for the review (e.g. MFA, encryption, compliance).\n"
        "Return a JSON object containing:\n"
        "{\n"
        '  "focus_areas": ["mfa", "encryption", "compliance", ...],\n'
        '  "reasoning": "string explanation"\n'
        "}"
    )

    user_prompt = (
        f"Documents:\n{doc_summary}\n\n"
        f"Analysis Depth: {state['analysis_depth']}\n"
        f"Custom Instructions: {state['custom_instructions']}\n"
    )

    result = await _call_llm_json(sys_prompt, user_prompt)
    focus = result.get("focus_areas", state["focus_areas"])

    return {
        "focus_areas": focus if focus else ["mfa", "encryption", "retention"],
        "current_node": "classifier",
        "tokens_used": state["tokens_used"] + result.get("_tokens_used", 0),
    }


async def evidence_retrieval_node(state: AgentState) -> Dict[str, Any]:
    """
    Agent 2: Evidence Retrieval Agent
    Stubs context construction based on retrieved chunks (the actual database chunks
    are fetched in orchestrator.py and populated into the retrieved_context state).
    """
    logger.info("Evidence Retrieval Node running...")
    # This node acts as an LLM validator to ensure retrieved snippets match focus areas
    sys_prompt = (
        "You are the Evidence Retrieval Agent.\n"
        "Given the focus areas and raw text chunks, summarize the relevant security posture findings.\n"
        "Return a JSON object containing:\n"
        "{\n"
        '  "extracted_summary": "structured summary of relevant claims made in the documents",\n'
        '  "missing_mention": ["any check item that has zero mention in text"]\n'
        "}"
    )

    user_prompt = (
        f"Focus Areas: {state['focus_areas']}\n\n"
        f"Retrieved Chunks:\n{state['retrieved_context']}\n"
    )

    result = await _call_llm_json(sys_prompt, user_prompt)

    # Convert any missing mentions to intermediate findings
    new_findings = []
    for missing in result.get("missing_mention", []):
        new_findings.append({
            "finding_type": "gap",
            "description": f"Missing evidence for focus area '{missing}': No mention in the provided documents.",
            "confidence": 0.8,
            "source_document_id": None,
        })

    return {
        "findings": state["findings"] + new_findings,
        "current_node": "retrieval",
        "tokens_used": state["tokens_used"] + result.get("_tokens_used", 0),
    }


async def risk_review_node(state: AgentState) -> Dict[str, Any]:
    """
    Agent 3: Risk Review Agent
    Checks retrieved evidence against industry best practices and config constraints.
    """
    logger.info("Risk Review Node running...")
    sys_prompt = (
        "You are the Risk Review Agent. Identify specific security, privacy, or operational risks.\n"
        "Grounded ONLY in the provided text snippets, find negative risks, weak policies, or bad practices.\n"
        "Return a JSON list of findings under the 'risks' key:\n"
        "{\n"
        '  "risks": [\n'
        "    {\n"
        '      "description": "Short description of the risk, citing the file",\n'
        '      "confidence": 0.9,\n'
        '      "filename": "Exact source filename from input"\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    user_prompt = (
        f"Retrieved Evidence Snippets:\n{state['retrieved_context']}\n\n"
        f"Custom Instructions: {state['custom_instructions']}\n"
    )

    result = await _call_llm_json(sys_prompt, user_prompt)

    new_findings = []
    for item in result.get("risks", []):
        doc_id = None
        # Match filename back to ID
        for d in state["documents"]:
            if d["original_filename"] == item.get("filename"):
                doc_id = d["id"]
                break

        new_findings.append({
            "finding_type": "risk",
            "description": item["description"],
            "confidence": item.get("confidence", 0.9),
            "source_document_id": str(doc_id) if doc_id else None,
        })

    return {
        "findings": state["findings"] + new_findings,
        "current_node": "risk_review",
        "tokens_used": state["tokens_used"] + result.get("_tokens_used", 0),
    }


async def gap_detection_node(state: AgentState) -> Dict[str, Any]:
    """
    Agent 4: Gap Detection Agent
    Checks if necessary clauses or documents are missing altogether.
    """
    logger.info("Gap Detection Node running...")
    sys_prompt = (
        "You are the Gap Detection Agent.\n"
        "Review the document checklist & custom instructions, and identify any critical missing policies/information.\n"
        "Return a JSON list of gaps under the 'gaps' key:\n"
        "{\n"
        '  "gaps": [\n'
        "    {\n"
        '      "description": "What standard item is missing from the package",\n'
        '      "confidence": 0.8\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    user_prompt = (
        f"Documents present: {[d['original_filename'] for d in state['documents']]}\n"
        f"Checklist requirements: {state['focus_areas']}\n"
        f"Context summary:\n{state['retrieved_context']}\n"
    )

    result = await _call_llm_json(sys_prompt, user_prompt)

    new_findings = []
    for item in result.get("gaps", []):
        new_findings.append({
            "finding_type": "gap",
            "description": item["description"],
            "confidence": item.get("confidence", 0.8),
            "source_document_id": None,
        })

    return {
        "findings": state["findings"] + new_findings,
        "current_node": "gap_detection",
        "tokens_used": state["tokens_used"] + result.get("_tokens_used", 0),
    }


async def contradiction_node(state: AgentState) -> Dict[str, Any]:
    """
    Agent 5: Contradiction Agent
    Checks if any two documents make conflicting statements (e.g. questionnaire says 90 days retention, DPA says 30).
    """
    logger.info("Contradiction Node running...")
    sys_prompt = (
        "You are the Contradiction Agent.\n"
        "Scan the text snippets to identify any logical contradictions or conflicting claims.\n"
        "Return a JSON list under the 'contradictions' key:\n"
        "{\n"
        '  "contradictions": [\n'
        "    {\n"
        '      "description": "Conflict description, stating which documents contradict each other",\n'
        '      "confidence": 0.75,\n'
        '      "filename_a": "First source file",\n'
        '      "filename_b": "Second source file"\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    user_prompt = f"Evidence Snippets:\n{state['retrieved_context']}\n"

    result = await _call_llm_json(sys_prompt, user_prompt)

    new_findings = []
    for item in result.get("contradictions", []):
        doc_id = None
        # Link to the first source file if possible
        for d in state["documents"]:
            if d["original_filename"] in (item.get("filename_a"), item.get("filename_b")):
                doc_id = d["id"]
                break

        new_findings.append({
            "finding_type": "contradiction",
            "description": item["description"],
            "confidence": item.get("confidence", 0.75),
            "source_document_id": str(doc_id) if doc_id else None,
        })

    return {
        "findings": state["findings"] + new_findings,
        "current_node": "contradiction",
        "tokens_used": state["tokens_used"] + result.get("_tokens_used", 0),
    }


async def summary_node(state: AgentState) -> Dict[str, Any]:
    """
    Agent 6: Summary Agent
    Creates the final consolidated summary/disposition assessment.
    """
    logger.info("Summary Node running...")
    findings_summary = "\n".join(
        f"- [{f['finding_type'].upper()}] {f['description']} (Conf: {f['confidence']})"
        for f in state["findings"]
    )

    sys_prompt = (
        "You are the Summary Agent.\n"
        "Compile the list of findings into a structured vendor assessment summary.\n"
        "Return a JSON object containing:\n"
        "{\n"
        '  "disposition": "Approve / Requires Follow-Up / Reject",\n'
        '  "executive_summary": "Concise summary of vendor posture",\n'
        '  "key_recommendations": "Bullet points for action items"\n'
        "}"
    )

    user_prompt = (
        f"Review Job ID: {state['review_job_id']}\n\n"
        f"Collected Findings:\n{findings_summary}\n"
    )

    result = await _call_llm_json(sys_prompt, user_prompt)

    # The summary outputs will be saved in the final review_job output
    return {
        "current_node": "summary",
        "tokens_used": state["tokens_used"] + result.get("_tokens_used", 0),
    }
