"""
Milestone 4 & 5 smoke test — exercises LangGraph orchestrator, background run task,
pause, resume, custom instructions, and in-flight Q&A.

NOTE: Patches OpenAI API calls with stubs for fast, cost-free, and deterministic testing.

Run with: uv run python scripts/smoke_test_m4_m5.py
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


def check(label: str, condition: bool):
    status = "PASS" if condition else "FAIL"
    results.append((status, label))
    print(f"[{status}] {label}")


def login(email: str, password: str) -> str:
    r = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["access_token"]


# ─── Stubs ─────────────────────────────────────────────────────────────────────

async def fake_call_llm_json(system_prompt: str, user_prompt: str):
    """Deterministic LLM outputs mimicking each node in the LangGraph workflow."""
    prompt_lower = system_prompt.lower()
    
    if "classifier" in prompt_lower:
        return {
            "focus_areas": ["mfa", "encryption", "compliance"],
            "reasoning": "Fake classifier reasoning",
            "_tokens_used": 150
        }
    
    elif "retrieval" in prompt_lower:
        return {
            "extracted_summary": "Document mentions standard controls.",
            "missing_mention": ["retention"],
            "_tokens_used": 200
        }
        
    elif "risk" in prompt_lower:
        return {
            "risks": [
                {
                    "description": "Standard risk: Encryption key management is handled manually.",
                    "confidence": 0.85,
                    "filename": "security_questionnaire.txt"
                }
            ],
            "_tokens_used": 250
        }
        
    elif "gap" in prompt_lower:
        return {
            "gaps": [
                {
                    "description": "Critical gap: Missing business continuity plan.",
                    "confidence": 0.90
                }
            ],
            "_tokens_used": 180
        }
        
    elif "contradiction" in prompt_lower:
        return {
            "contradictions": [
                {
                    "description": "Contradiction found: Questionnaire claims automatic backups, DPA mentions weekly manual backup.",
                    "confidence": 0.75,
                    "filename_a": "security_questionnaire.txt",
                    "filename_b": "dpa.txt"
                }
            ],
            "_tokens_used": 210
        }
        
    elif "summary" in prompt_lower:
        return {
            "disposition": "Requires Follow-Up",
            "executive_summary": "Moderate risk profile with minor backup contradictions.",
            "key_recommendations": "Verify backup frequency and request BCP document.",
            "_tokens_used": 300
        }
    
    return {"_tokens_used": 0}


# Stub for the mock Q&A chat completions client call in app.api.reviews
class FakeChatCompletion:
    def __init__(self, content):
        class Choice:
            def __init__(self, text):
                class Message:
                    def __init__(self, t):
                        self.content = t
                self.message = Message(text)
        self.choices = [Choice(content)]


FAKE_EMBEDDING = [0.01] * 1536

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

async def fake_qa_completions_create(*args, **kwargs):
    return FakeChatCompletion("Grounded answer: Encryption key risk is manual; missing BCP.")


# ─── Tests ─────────────────────────────────────────────────────────────────────

with (
    patch("app.services.agents._call_llm_json", side_effect=fake_call_llm_json),
    patch("openai.resources.chat.completions.AsyncCompletions.create", side_effect=fake_qa_completions_create),
    patch("app.services.ingestion.embed_texts", side_effect=fake_embed_texts),
    patch("app.services.ingestion.embed_single", side_effect=fake_embed_single),
    patch("app.services.ingestion.classify_document", side_effect=fake_classify),
    client,
):
    print("=" * 60)
    print("Milestone 4 & 5 Backend Smoke Test")
    print("=" * 60)

    # Setup: create user + review + upload text documents
    _TS = int(time.time())
    reviewer_email = f"m4tester_{_TS}@test.com"
    client.post("/api/v1/auth/signup", json={
        "email": reviewer_email,
        "password": "TestPass123!",
        "full_name": "M4 Tester",
    })
    token = login(reviewer_email, "TestPass123!")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post("/api/v1/reviews", json={
        "vendor_name": "Demo Vendor",
        "review_context": "Milestone 4 & 5 test",
        "enabled_checks": ["mfa", "encryption"],
        "analysis_depth": "deep"
    }, headers=headers)
    check("Create review with checks & depth config", r.status_code == 201)
    review_id = r.json()["id"]

    # Upload files to set up standard preprocessed chunks
    files = [
        ("files", ("security_questionnaire.txt", b"MFA is enabled on all portals. Key management is manual.", "text/plain")),
        ("files", ("dpa.txt", b"DPA details weekly manual backup processes.", "text/plain")),
    ]
    r = client.post(f"/api/v1/reviews/{review_id}/documents", files=files, headers=headers)
    check("Accepted test files for preprocessing", r.status_code == 201 and len(r.json()["accepted"]) == 2)

    # Wait until preprocessing becomes ready
    start = time.time()
    while time.time() - start < 15:
        r = client.get(f"/api/v1/reviews/{review_id}", headers=headers)
        if r.json()["status"] == "ready":
            break
        time.sleep(0.5)
    check("Preprocessing finished successfully", r.json()["status"] == "ready")

    # ── M4: Trigger Analysis ───────────────────────────────────────────────────
    print("\n--- M4: Starting Analysis ---")
    r = client.post(f"/api/v1/reviews/{review_id}/analyze", headers=headers)
    check("Trigger analyze returns 200", r.status_code == 200)
    check("Status changes to 'analyzing'", r.json()["status"] == "analyzing")

    # Let the analysis step through a couple of nodes
    time.sleep(1.5)

    # ── M5: Trigger Pause ──────────────────────────────────────────────────────
    print("\n--- M5: Pausing Analysis ---")
    r = client.post(f"/api/v1/reviews/{review_id}/pause", headers=headers)
    check("Trigger pause returns 200", r.status_code == 200)
    check("Status changes to 'paused'", r.json()["status"] == "paused")

    # Check progress state is preserved
    r = client.get(f"/api/v1/reviews/{review_id}/progress", headers=headers)
    check("Progress reflects current stage has paused", "paused" in r.json()["current_stage"].lower() or r.json()["status"] == "paused")

    # ── M5: In-flight Q&A & Custom Instructions ────────────────────────────────
    print("\n--- M5: In-flight Q&A ---")
    r = client.post(f"/api/v1/reviews/{review_id}/ask", json={"question": "What is the key management risk?"}, headers=headers)
    check("POST /ask returns 200 while paused", r.status_code == 200)
    check("Response contains cited findings list", len(r.json()["cited_findings"]) > 0)
    check("Answer is returned correctly", "Grounded answer" in r.json()["answer"])

    print("\n--- M5: Inject custom instructions ---")
    r = client.post(f"/api/v1/reviews/{review_id}/instructions", json={"custom_instructions": "Focus on manual processes"}, headers=headers)
    check("Update instructions returns 200", r.status_code == 200)
    check("Instructions saved to database review job", r.json()["custom_instructions"] == "Focus on manual processes")

    # ── M5: Resume ─────────────────────────────────────────────────────────────
    print("\n--- M5: Resuming Analysis ---")
    r = client.post(f"/api/v1/reviews/{review_id}/resume", headers=headers)
    check("Trigger resume returns 200", r.status_code == 200)
    check("Status changes back to 'analyzing'", r.json()["status"] == "analyzing")

    # Wait until finished
    start = time.time()
    final_status = None
    while time.time() - start < 15:
        r = client.get(f"/api/v1/reviews/{review_id}", headers=headers)
        final_status = r.json()["status"]
        if final_status in ("completed", "failed"):
            break
        time.sleep(0.5)
    check("Analysis finished successfully (status=completed)", final_status == "completed")

    # Verify findings are persisted
    r = client.get(f"/api/v1/reviews/{review_id}/findings", headers=headers)
    findings = r.json()
    check("Findings saved in database", len(findings) > 0)
    finding_types = [f["finding_type"] for f in findings]
    check("Contains at least one risk finding", "risk" in finding_types)
    check("Contains at least one gap finding", "gap" in finding_types)
    check("Contains at least one contradiction finding", "contradiction" in finding_types)

    # ── Auth & Separation check ───────────────────────────────────────────────
    print("\n--- Auth & Security checks ---")
    other_email = f"m4other_{_TS}@test.com"
    client.post("/api/v1/auth/signup", json={"email": other_email, "password": "TestPass123!"})
    other_token = login(other_email, "TestPass123!")
    other_headers = {"Authorization": f"Bearer {other_token}"}
    
    r = client.post(f"/api/v1/reviews/{review_id}/pause", headers=other_headers)
    check("Other user access to pause returns 403", r.status_code == 403)
    
    r = client.post(f"/api/v1/reviews/{review_id}/ask", json={"question": "test"}, headers=other_headers)
    check("Other user access to Q&A returns 403", r.status_code == 403)

# ── Summary ───────────────────────────────────────────────────────────────────
print()
passed = sum(1 for s, _ in results if s == "PASS")
failed = sum(1 for s, _ in results if s == "FAIL")
print(f"Results: {passed}/{len(results)} checks passed", "OK" if failed == 0 else f"  ({failed} FAILED)")
print("=" * 60)
if failed:
    print("\nFailed checks:")
    for s, label in results:
        if s == "FAIL":
            print(f"  [FAIL] {label}")
