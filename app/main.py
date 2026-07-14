from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api import auth, documents, progress, reviews, search
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole

settings = get_settings()


async def seed_admin_account() -> None:
    """
    Creates the initial admin account on startup if it doesn't already
    exist. Deliberate choice over open admin self-signup: in a real due
    diligence tool, admin access should never be a public registration
    option -- only bootstrapped once, then managed via Milestone 7's
    admin user-management endpoints.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == settings.SEED_ADMIN_EMAIL))
        if result.scalar_one_or_none() is not None:
            return
        admin = User(
            email=settings.SEED_ADMIN_EMAIL,
            hashed_password=hash_password(settings.SEED_ADMIN_PASSWORD),
            full_name="System Administrator",
            role=UserRole.ADMIN,
        )
        db.add(admin)
        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await seed_admin_account()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="Multi-agent Vendor Due Diligence Assistant -- API",
    version="0.1.0",
    lifespan=lifespan,
    # Swagger UI is auto-served at /docs, ReDoc at /redoc, OpenAPI JSON at /openapi.json
)

app.include_router(auth.router)
app.include_router(reviews.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(progress.router)


# --- Global error handling: comprehensive, user-friendly messages (BRD requirement) ---

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Turns Pydantic's verbose validation errors into a flat, readable list."""
    errors = [
        {"field": ".".join(str(loc) for loc in err["loc"] if loc != "body"), "message": err["msg"]}
        for err in exc.errors()
    ]
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": "Invalid request.", "errors": errors})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all so an unexpected bug never leaks a stack trace to the client."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred. Please try again or contact support."},
    )


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}
