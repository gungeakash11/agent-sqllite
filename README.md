# Vendor Due Diligence Assistant (SQLite Version)

Multi-agent (LangGraph) system that reviews vendor-provided documents (security questionnaires, DPAs, policies) and produces a structured, evidence-backed security compliance assessment.

**Status: Milestones 1–5 complete — SQLite Branch**

This branch is configured to run entirely on **SQLite** using in-memory Python cosine similarity for vector search. It requires **zero external database installations, zero configurations, and no Docker**, making it fully portable for office laptops.

---

## 🛠️ Tech Stack
- **FastAPI (async)** — Backend API and execution orchestration layer.
- **LangGraph** — Multi-agent state orchestration workflow (Classifier, Retrieval, Risk, Gap, Contradiction, Summary nodes) with persistent DB state checkpointing.
- **Streamlit** — Graphical dashboard UI featuring real-time event logs, agent progress visualizers, custom instruction injectors, and in-flight grounded Q&A.
- **SQLAlchemy 2.0 (async) + Alembic** — ORM schema models and database migrations.
- **SQLite (via aiosqlite)** — Local file-based metadata storage and vector chunk storage.
- **JWT Auth** — Role-based access control (User/Admin).
- **uv** — Dependency and environment manager.

---

## 🚀 Local Setup (SQLite Mode)

### Step 1: Install Python Dependencies
Synchronize dependencies (sets up local virtual environment and installs sqlite async driver):
```bash
uv sync
```

### Step 2: Configure Environment Variables
Copy the template file to `.env`:
```bash
cp .env.example .env
```
Open `.env` and fill in your keys:
- The `DATABASE_URL` is pre-configured to point to your local file: `sqlite+aiosqlite:///./vendor_dd.db`.
- Input a valid `OPENAI_API_KEY` (required for embeddings and agent prompts).

### Step 3: Run Migrations
Applies the full schema and creates the `vendor_dd.db` file automatically:
```bash
uv run alembic upgrade head
```

### Step 4: Start the Backend Server
```bash
uv run uvicorn app.main:app --port 8000 --reload
```
- Swagger UI will be available at: http://localhost:8000/docs
- Seed Admin Account: `admin@vendordd.internal-app.com` / `change_this_admin_password_123!`

### Step 5: Start the Streamlit Dashboard UI (In a new terminal)
```bash
uv run streamlit run ui.py
```
- Open in browser: http://localhost:8501

---

## 🔬 Running the Integration Test Suite
To verify the complete backend API pipeline (upload, preprocessing, agent run, pause, resume, grounded Q&A) against the local SQLite database, run:
```bash
uv run python scripts/smoke_test_m4_m5.py
```

---

## 📁 Project Structure
```
app/
├── api/            # routers: auth, reviews, documents, progress, search
├── core/           # configuration settings, DB connection pooling, JWT security
├── models/         # SQLAlchemy models (User, ReviewJob, Document, Chunk, Finding, AgentRun)
├── schemas/        # Pydantic request/response schemas
├── services/       # business logic (parsers, chunkers, agents, orchestrator)
└── main.py         # FastAPI main entrypoint and startup seeders
alembic/            # database migration files
scripts/            # smoke test scripts
ui.py               # Streamlit dashboard interface
pyproject.toml      # package configurations
```

---

## 🗺️ Roadmap
- [x] **Milestone 1** — Foundation (auth, review creation, uploads, validation)
- [x] **Milestone 2** — Intelligent Preprocessing (parsing, chunking, embeddings, search)
- [x] **Milestone 3** — Real-Time Ingestion Progress
- [x] **Milestone 4** — Multi-Agent Review Pipeline (LangGraph execution flow)
- [x] **Milestone 5** — Interactive Controls (Pause, Resume, Custom Instructions, In-flight Q&A)
- [ ] **Milestone 6** — Rich Report Output & Exports
- [ ] **Milestone 7** — Admin Panel User Control
- [ ] Langfuse Observability
