"""
SQLAlchemy async engine and session factory.
Supports SQLite via aiosqlite. Easily swappable to PostgreSQL.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


# ── Base declarative class ────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Async engine ──────────────────────────────────────────────────────────────
from sqlalchemy import event

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={
        "check_same_thread": False,
        "timeout": 20.0,
    },
)

@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=20000")
        cursor.close()

# ── Session factory ───────────────────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ── Table creation ────────────────────────────────────────────────────────────
async def create_tables() -> None:
    """Create all database tables on startup."""
    # Import all models so SQLAlchemy registers them with Base.metadata
    import app.database.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if settings.database_url.startswith("sqlite"):
            columns = await conn.exec_driver_sql("PRAGMA table_info(boundaries)")
            column_names = {row[1] for row in columns.fetchall()}
            if "field_sources_json" not in column_names:
                await conn.exec_driver_sql(
                    "ALTER TABLE boundaries ADD COLUMN field_sources_json TEXT"
                )
            analysis_columns = await conn.exec_driver_sql("PRAGMA table_info(analysis_results)")
            analysis_column_names = {row[1] for row in analysis_columns.fetchall()}
            if "component_diagnostics_json" not in analysis_column_names:
                await conn.exec_driver_sql(
                    "ALTER TABLE analysis_results ADD COLUMN component_diagnostics_json TEXT"
                )


# ── Dependency injection helper ───────────────────────────────────────────────
async def get_db() -> AsyncSession:
    """FastAPI dependency that yields a database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
