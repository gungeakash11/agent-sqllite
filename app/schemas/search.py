"""Pydantic schemas for semantic search (M2)."""
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Natural language search query")
    top_k: int = Field(5, ge=1, le=20, description="Number of results to return")


class ChunkResult(BaseModel):
    chunk_id: str
    document_id: str
    source_filename: str
    chunk_index: int
    content: str
    similarity: float = Field(..., description="Cosine similarity score (0-1, higher = more relevant)")

    model_config = {"from_attributes": True}


class SearchResponse(BaseModel):
    query: str
    results: list[ChunkResult]
    total_results: int
