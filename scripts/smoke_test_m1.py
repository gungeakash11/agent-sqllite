"""
Milestone 1 end-to-end smoke test -- exercises the exact BRD demo scenario:
'User signs up -> logs in -> creates vendor review -> uploads questionnaire,
DPA, SOC report -> sees Review Started confirmation -> Review ID displayed'
plus the invalid-file-handling matrix and role separation.

Run with: uv run python scripts/smoke_test_m1.py
"""
from fastapi.testclient import TestClient

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app

client = TestClient(app)  # runs the real lifespan (seeds admin) against the real DB

results = []

# Unique suffix so re-running tests never collides with existing DB rows
_TS = int(time.time())
REVIEWER_EMAIL = f"reviewer_{_TS}@acme.com"
OTHER_EMAIL    = f"other_{_TS}@acme.com"

def check(label, condition):
    status = "PASS" if condition else "FAIL"
    results.append((status, label))
    print(f"[{status}] {label}")


def login(email: str, password: str) -> str:
    """Login via form data (OAuth2PasswordRequestForm) and return access token."""
    r = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    return r.json().get("access_token", "")


with client:
    # 1. Signup
    r = client.post("/api/v1/auth/signup", json={
        "email": REVIEWER_EMAIL, "password": "SecurePass123", "full_name": "Jane Reviewer"
    })
    check("Signup returns 201", r.status_code == 201)
    check("Signup assigns 'user' role (not admin)", r.json().get("role") == "user")

    # 2. Login
    r = client.post("/api/v1/auth/login", data={"username": REVIEWER_EMAIL, "password": "SecurePass123"})
    check("Login returns 200 with access token", r.status_code == 200 and "access_token" in r.json())
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2b. /me endpoint
    r = client.get("/api/v1/auth/me", headers=headers)
    check("GET /me returns current user", r.status_code == 200 and r.json().get("email") == REVIEWER_EMAIL)

    # 3. Create review
    r = client.post("/api/v1/reviews", json={
        "vendor_name": "Acme Cloud Services", "review_context": "Annual SOC2 vendor renewal"
    }, headers=headers)
    check("Create review returns 201 with unique review ID", r.status_code == 201 and "id" in r.json())
    review_id = r.json()["id"]

    # 4. Upload valid + every invalid case from the BRD
    files = [
        ("files", ("security_questionnaire.pdf", b"%PDF-1.4 fake content about MFA", "application/pdf")),
        ("files", ("dpa.pdf", b"%PDF-1.4 fake dpa content", "application/pdf")),
        ("files", ("soc_report.txt", b"valid soc report text", "text/plain")),
        ("files", ("empty_file.txt", b"", "text/plain")),                      # empty upload
        ("files", ("diagram.png", b"not really an image", "image/png")),       # wrong format
        ("files", ("fake.pdf", b"this is not a real pdf", "application/pdf")),  # corrupted
        ("files", ("toolarge.txt", b"0" * (26 * 1024 * 1024), "text/plain")),   # too large
    ]
    r = client.post(f"/api/v1/reviews/{review_id}/documents", files=files, headers=headers)
    body = r.json()
    check("Upload batch returns 201", r.status_code == 201)
    check("3 valid files accepted", len(body["accepted"]) == 3)
    check("4 invalid files rejected", len(body["rejected"]) == 4)
    reasons = {item["filename"]: item["reason"] for item in body["rejected"]}
    check("Empty file rejected with clear reason", "empty" in reasons.get("empty_file.txt", "").lower())
    check("Wrong format rejected with clear reason", "unsupported" in reasons.get("diagram.png", "").lower())
    check("Corrupted file rejected with clear reason", "corrupted" in reasons.get("fake.pdf", "").lower())
    check("Too-large file rejected with clear reason", "exceeds" in reasons.get("toolarge.txt", "").lower())

    # 5. Duplicate detection
    r = client.post(
        f"/api/v1/reviews/{review_id}/documents",
        files=[("files", ("security_questionnaire.pdf", b"%PDF-1.4 fake content about MFA", "application/pdf"))],
        headers=headers,
    )
    check("Duplicate file rejected on re-upload", len(r.json()["rejected"]) == 1)

    # 6. Auth enforcement
    r = client.get("/api/v1/reviews")
    check("No token -> 401 Unauthorized", r.status_code == 401)

    # 7. Admin seeded account works and has admin role
    from app.core.config import get_settings
    _settings = get_settings()
    r = client.post("/api/v1/auth/login", data={
        "username": _settings.SEED_ADMIN_EMAIL, "password": _settings.SEED_ADMIN_PASSWORD
    })
    check("Seeded admin can log in", r.status_code == 200)
    admin_token = r.json()["access_token"]
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    check("Admin account has 'admin' role", r.json().get("role") == "admin")

    # 8. Cross-user access denied (role separation / ownership)
    client.post("/api/v1/auth/signup", json={"email": OTHER_EMAIL, "password": "SecurePass123"})
    r2 = client.post("/api/v1/auth/login", data={"username": OTHER_EMAIL, "password": "SecurePass123"})
    other_token = r2.json()["access_token"]
    r = client.get(f"/api/v1/reviews/{review_id}", headers={"Authorization": f"Bearer {other_token}"})
    check("Another user cannot access someone else's review (403)", r.status_code == 403)

    # 9. Swagger docs
    r = client.get("/docs")
    check("Swagger UI accessible", r.status_code == 200)
    r = client.get("/openapi.json")
    check("OpenAPI schema accessible", r.status_code == 200)

print()
passed = sum(1 for s, _ in results if s == "PASS")
print(f"{passed}/{len(results)} checks passed")
