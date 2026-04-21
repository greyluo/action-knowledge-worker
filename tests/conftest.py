import os
import pytest
import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

load_dotenv()

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://grey@localhost:5432/sprint_demo_test",
)

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    from db import Base
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest_asyncio.fixture(loop_scope="session")
async def session(test_engine):
    async with AsyncSession(test_engine) as s:
        await s.begin()
        yield s
        await s.rollback()
