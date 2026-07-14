"""
Embedding service — generates vector embeddings via the OpenAI API.

Uses text-embedding-3-small (1536 dimensions), which matches the
EMBEDDING_DIM constant in document.py and the Vector(1536) pgvector column.

Batches calls to stay within the OpenAI token-per-request limit.
Returns one embedding vector per input text, in the same order.
"""
import logging
from openai import AsyncOpenAI

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Batch size: OpenAI allows up to 2048 inputs per request, but we keep it
# conservative so we stay well within the per-request token limit.
BATCH_SIZE = 100
EMBEDDING_MODEL = "text-embedding-3-small"

# Module-level client — shared across all calls (connection pooling)
_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of text strings using OpenAI text-embedding-3-small.

    Returns a list of float vectors in the same order as the input.
    Raises on API errors — callers should handle and log appropriately.
    """
    if not texts:
        return []

    client = _get_client()
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i: i + BATCH_SIZE]
        # Replace newlines: OpenAI recommends this to avoid degraded quality
        batch = [t.replace("\n", " ") for t in batch]

        response = await client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=batch,
        )
        batch_embeddings = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
        all_embeddings.extend(batch_embeddings)
        logger.debug("Embedded batch %d-%d (%d vectors)", i, i + len(batch), len(batch_embeddings))

    return all_embeddings


async def embed_single(text: str) -> list[float]:
    """Convenience wrapper to embed a single string."""
    results = await embed_texts([text])
    return results[0]
