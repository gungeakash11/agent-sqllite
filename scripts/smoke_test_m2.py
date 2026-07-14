"""
Milestone 2 & 3 smoke test — exercises preprocessing pipeline, evidence
discovery, and real-time progress feed.

NOTE: This test does NOT call the OpenAI API. It patches the embedding and
classification services with fast stubs so the test is:
  - Deterministic (no flaky API calls)
  - Free (no API cost)
  - Fast (runs in seconds)

Run with: uv run python scripts/smoke_test_m2.py
"""
import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
results = []

_TS = int(time.time())
TESTER_EMAIL = f"m2tester_{_TS}@test.com"
OTHER_EMAIL  = f"m2other_{_TS}@test.com"

FAKE_EMBEDDING = [0.01] * 1536  # 1536-dim vector — valid pgvector format


def check(label: str, condition: bool):
    status = "PASS" if condition else "FAIL"
    results.append((status, label))
    print(f"[{status}] {label}")


def login(email: str, password: str) -> str:
    r = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["access_token"]


# ─── Sample documents ──────────────────────────────────────────────────────────

SAMPLE_PDF_BYTES = b"This is a security questionnaire document.\nBreachnotification within 72 hours of discovery.\nMFA is required for all privileged accounts.\nData is encrypted at rest using AES-256."
SAMPLE_TXT_BYTES = b"Data Processing Agreement.\nController and processor obligations defined.\nData retention: 90 days after contract end.\nBreach notification within 72 hours."
SAMPLE_DOCX_BYTES = b"PK\x03\x04"  # minimal DOCX magic bytes (will fail extraction gracefully)


# ─── Stubs ─────────────────────────────────────────────────────────────────────

async def fake_embed_texts(texts):
    return [FAKE_EMBEDDING[:] for _ in texts]

async def fake_embed_single(text):
    return FAKE_EMBEDDING[:]

async def fake_classify(filename, text_sample):
    if "questionnaire" in filename.lower():
        return "Security Questionnaire"
    if "dpa" in filename.lower():
        return "Data Processing Agreement"
    return "Other"


# ─── Tests ─────────────────────────────────────────────────────────────────────

# Patch inside ingestion.py where the names are BOUND (not in their source modules)
with (
    patch("app.services.ingestion.embed_texts", side_effect=fake_embed_texts),
    patch("app.services.ingestion.embed_single", side_effect=fake_embed_single),
    patch("app.services.ingestion.classify_document", side_effect=fake_classify),
    # Also patch retrieval's embed_single for the search step
    patch("app.services.retrieval.embed_single", side_effect=fake_embed_single),
    client,
):
    print("=" * 60)
    print("Milestone 2 & 3 Smoke Test")
    print("=" * 60)

    # Setup: create user + review
    client.post("/api/v1/auth/signup", json={
        "email": TESTER_EMAIL,
        "password": "TestPass123!",
        "full_name": "M2 Tester",
    })
    token = login(TESTER_EMAIL, "TestPass123!")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post("/api/v1/reviews", json={
        "vendor_name": "Test Vendor", "review_context": "M2 smoke test"
    }, headers=headers)
    check("Create review for M2 test", r.status_code == 201)
    review_id = r.json()["id"]

    # ── M3: Progress before upload ──────────────────────────────────────────────
    print("\n--- M3: Progress endpoint ---")
    r = client.get(f"/api/v1/reviews/{review_id}/progress", headers=headers)
    check("Progress endpoint returns 200", r.status_code == 200)
    check("Initial status is 'created'", r.json()["status"] == "created")
    check("Initial progress_pct is 0", r.json()["progress_pct"] == 0)
    check("Response has events list", "events" in r.json())
    check("Response has next_since", "next_since" in r.json())

    # ── M2: Upload and trigger ingestion ───────────────────────────────────────
    print("\n--- M2: Upload + ingestion ---")
    files = [
        ("files", ("security_questionnaire.txt", SAMPLE_PDF_BYTES, "text/plain")),
        ("files", ("dpa.txt", SAMPLE_TXT_BYTES, "text/plain")),
    ]
    r = client.post(f"/api/v1/reviews/{review_id}/documents", files=files, headers=headers)
    check("Upload with M2 trigger returns 201", r.status_code == 201)
    check("Both files accepted", len(r.json()["accepted"]) == 2)

    # Status should now be PREPROCESSING (ingestion kicked off as background task)
    r = client.get(f"/api/v1/reviews/{review_id}", headers=headers)
    check("Review status transitions to 'preprocessing' after upload",
          r.json()["status"] == "preprocessing")

    # ── Wait for background ingestion to complete ──────────────────────────────
    print("\n--- Waiting for ingestion pipeline to complete ---")
    max_wait = 30  # seconds
    start = time.time()
    final_status = None
    while time.time() - start < max_wait:
        r = client.get(f"/api/v1/reviews/{review_id}/progress", headers=headers)
        final_status = r.json()["status"]
        pct = r.json()["progress_pct"]
        stage = r.json()["current_stage"]
        print(f"  [{pct:3d}%] {stage} (status={final_status})")
        if final_status in ("ready", "failed"):
            break
        time.sleep(1)

    check("Ingestion completes within 30 seconds", final_status in ("ready", "failed"))
    check("Ingestion completes successfully (status=ready)", final_status == "ready")

    # ── M3: Progress feed content ──────────────────────────────────────────────
    print("\n--- M3: Progress feed ---")
    r = client.get(f"/api/v1/reviews/{review_id}/progress?since=0", headers=headers)
    prog = r.json()
    check("Progress is 100% after completion", prog["progress_pct"] == 100)
    check("At least one milestone event in feed",
          any(e["event_type"] == "milestone" for e in prog["events"]))
    check("Feed contains document detection message",
          any("Detected" in e["message"] for e in prog["events"]))
    check("Feed contains completion message",
          any("complete" in e["message"].lower() for e in prog["events"]))

    # Incremental polling: since=N returns only new events
    first_event_count = len(prog["events"])
    next_since = prog["next_since"]
    r2 = client.get(f"/api/v1/reviews/{review_id}/progress?since={next_since}", headers=headers)
    check("Incremental poll (since=N) returns no duplicate events",
          len(r2.json()["events"]) == 0)

    # ── M2: Document classification ───────────────────────────────────────────
    print("\n--- M2: Document intelligence ---")
    r = client.get(f"/api/v1/reviews/{review_id}/documents", headers=headers)
    docs = r.json()
    check("All documents are marked PROCESSED", all(d["status"] == "processed" for d in docs))
    doc_types = {d["original_filename"]: d["document_type"] for d in docs}
    check("TXT classified as Security Questionnaire",
          doc_types.get("security_questionnaire.txt") == "Security Questionnaire")
    check("TXT classified as Data Processing Agreement",
          doc_types.get("dpa.txt") == "Data Processing Agreement")

    # ── M2: Semantic search ───────────────────────────────────────────────────
    print("\n--- M2: Semantic search ---")
    r = client.post(f"/api/v1/reviews/{review_id}/search",
                    json={"query": "breach notification", "top_k": 5},
                    headers=headers)
    check("Search endpoint returns 200", r.status_code == 200)
    sr = r.json()
    check("Search returns results", sr["total_results"] > 0)
    check("Search result has source_filename", all("source_filename" in res for res in sr["results"]))
    check("Search result has content text", all(len(res["content"]) > 0 for res in sr["results"]))
    check("Search result has similarity score", all("similarity" in res for res in sr["results"]))
    check("Similarity score is between 0 and 1",
          all(0.0 <= res["similarity"] <= 1.0 for res in sr["results"]))

    # Search on review with no preprocessing should work (returns empty)
    r2 = client.post("/api/v1/reviews", json={"vendor_name": "Empty Vendor"}, headers=headers)
    empty_review_id = r2.json()["id"]
    r = client.post(f"/api/v1/reviews/{empty_review_id}/search",
                    json={"query": "breach notification"},
                    headers=headers)
    check("Search on review with no docs returns 409 (not yet uploaded)",
          r.status_code == 409)

    # ── Auth enforcement for new endpoints ───────────────────────────────────
    print("\n--- Auth enforcement ---")
    r = client.post(f"/api/v1/reviews/{review_id}/search", json={"query": "test"})
    check("Search without token -> 401", r.status_code == 401)
    r = client.get(f"/api/v1/reviews/{review_id}/progress")
    check("Progress without token -> 401", r.status_code == 401)

    # Cross-user access denied
    client.post("/api/v1/auth/signup", json={"email": OTHER_EMAIL, "password": "TestPass123!"})
    other_token = login(OTHER_EMAIL, "TestPass123!")
    other_headers = {"Authorization": f"Bearer {other_token}"}
    r = client.post(f"/api/v1/reviews/{review_id}/search",
                    json={"query": "test"}, headers=other_headers)
    check("Search on another user's review -> 403", r.status_code == 403)
    r = client.get(f"/api/v1/reviews/{review_id}/progress", headers=other_headers)
    check("Progress on another user's review -> 403", r.status_code == 403)

# ── Summary ───────────────────────────────────────────────────────────────────
print()
passed = sum(1 for s, _ in results if s == "PASS")
failed = sum(1 for s, _ in results if s == "FAIL")
print("=" * 60)
print(f"Results: {passed}/{len(results)} checks passed", "✓" if failed == 0 else f"  ({failed} FAILED)")
print("=" * 60)
if failed:
    print("\nFailed checks:")
    for s, label in results:
        if s == "FAIL":
            print(f"  ✗ {label}")
