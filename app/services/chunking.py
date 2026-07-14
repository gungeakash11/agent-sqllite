"""
Text chunking service — splits extracted document text into logically
coherent segments suitable for embedding and retrieval.

Strategy: recursive character split with a token-based size limit.
- chunk_size: 800 tokens  (balances context with embedding cost)
- chunk_overlap: 100 tokens  (preserves cross-boundary context)
- Minimum chunk length: 50 characters (filters noise/headers)

tiktoken is used for accurate token counting matching OpenAI's tokenizer.
"""
import logging
from typing import Generator

import tiktoken

logger = logging.getLogger(__name__)

# OpenAI text-embedding-3-small uses the cl100k_base tokenizer
_ENCODING = tiktoken.get_encoding("cl100k_base")

CHUNK_SIZE_TOKENS = 800
CHUNK_OVERLAP_TOKENS = 100
MIN_CHUNK_CHARS = 50


def _token_len(text: str) -> int:
    return len(_ENCODING.encode(text))


def _split_recursive(text: str, separators: list[str]) -> Generator[str, None, None]:
    """
    Recursively split text using a priority list of separators.
    Falls back to character-level splitting if no separator fits.
    """
    if not separators:
        # Base case: yield character-level chunks
        start = 0
        text_len = len(text)
        while start < text_len:
            end = start
            tokens = 0
            while end < text_len and tokens < CHUNK_SIZE_TOKENS:
                end += 1
                tokens = _token_len(text[start:end])
            yield text[start:end]
            start = max(start + 1, end - CHUNK_OVERLAP_TOKENS * 4)  # approx char overlap
        return

    sep = separators[0]
    rest = separators[1:]
    splits = text.split(sep)

    current = ""
    for split in splits:
        candidate = (current + sep + split).strip() if current else split.strip()
        if _token_len(candidate) <= CHUNK_SIZE_TOKENS:
            current = candidate
        else:
            if current:
                if _token_len(current) > CHUNK_SIZE_TOKENS:
                    yield from _split_recursive(current, rest)
                else:
                    yield current
            current = split.strip()

    if current:
        if _token_len(current) > CHUNK_SIZE_TOKENS:
            yield from _split_recursive(current, rest)
        else:
            yield current


def chunk_text(text: str) -> list[str]:
    """
    Split document text into chunks for embedding.

    Returns a list of non-empty, deduplicated text chunks.
    Each chunk is at most CHUNK_SIZE_TOKENS tokens long.
    """
    if not text or not text.strip():
        return []

    # Priority separator order: section → paragraph → sentence → word
    separators = ["\n\n\n", "\n\n", "\n", ". ", "! ", "? ", " "]
    raw_chunks = list(_split_recursive(text.strip(), separators))

    # Deduplicate adjacent identical chunks and filter noise
    seen: set[str] = set()
    chunks: list[str] = []
    for chunk in raw_chunks:
        chunk = chunk.strip()
        if len(chunk) < MIN_CHUNK_CHARS:
            continue
        if chunk in seen:
            continue
        seen.add(chunk)
        chunks.append(chunk)

    logger.debug("Chunked text into %d chunks", len(chunks))
    return chunks
