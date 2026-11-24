import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.database.engine import Base
import app.database.models  # noqa: F401


@pytest_asyncio.fixture
async def db_session(tmp_path):
    test_db = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{test_db}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.commit()
    await engine.dispose()
