"""
Database engine & session management.

We use SQLAlchemy's async engine because FastAPI is async-native, and later
milestones (multi-agent orchestration, pause/resume) involve long-running,
concurrent operations where a blocking (sync) DB driver would stall the
event loop for every other request being served.
"""
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,  # detects dropped connections before using them
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base class every ORM model inherits from."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a request-scoped DB session, always closed after."""
    async with AsyncSessionLocal() as session:
        yield session
