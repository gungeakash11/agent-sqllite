"""
Document classification service — identifies the likely type of a vendor
document (SOC Report, DPA, Security Questionnaire, etc.) from its filename
and the first ~500 tokens of its content.

Uses gpt-4o-mini for speed and cost-efficiency. Returns a human-readable
label from the KNOWN_TYPES list, or "Other" if no match is confident.
"""
import logging

from openai import AsyncOpenAI

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

KNOWN_TYPES = [
    "SOC Report",
    "Data Processing Agreement",
    "Security Questionnaire",
    "Privacy Policy",
    "Penetration Test Report",
    "Business Continuity Plan",
    "Contract / MSA",
    "ISO Certificate",
    "Vendor Risk Assessment",
    "Other",
]

_SYSTEM_PROMPT = """\
You are a vendor due diligence document classifier.
Given a filename and the opening section of a document, identify its type.
Reply with ONLY one label from this list (exact spelling):
{types}
If the document does not clearly match any type, reply with "Other".""".format(
    types="\n".join(f"- {t}" for t in KNOWN_TYPES)
)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def classify_document(filename: str, text_sample: str) -> str:
    """
    Classify a document's type from its filename and opening text.

    text_sample should be the first ~500 tokens of extracted text.
    Returns one of KNOWN_TYPES. Falls back to "Other" on any error.
    """
    # Trim sample to ~2000 chars to keep prompt small and fast
    sample = text_sample[:2000].strip() if text_sample else "(no text extracted)"

    user_message = f"Filename: {filename}\n\nDocument opening:\n{sample}"

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_tokens=20,
            temperature=0,  # deterministic classification
        )
        label = response.choices[0].message.content.strip()

        # Validate against known types (LLM could hallucinate)
        if label in KNOWN_TYPES:
            return label
        # Fuzzy fallback: find first match that's a substring
        label_lower = label.lower()
        for known in KNOWN_TYPES:
            if known.lower() in label_lower or label_lower in known.lower():
                return known
        return "Other"

    except Exception as exc:
        logger.warning("Document classification failed for %s: %s", filename, exc)
        return "Other"
