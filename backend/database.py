from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from backend.config import settings


def _db_url() -> str:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{settings.data_dir}/app.db"


engine = create_async_engine(_db_url(), echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    # Import models so their tables are registered on Base.metadata
    import backend.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)


async def _migrate(conn) -> None:
    """Apply additive schema changes to existing databases (poor-man's migration)."""
    new_columns = [
        "ALTER TABLE sync_rules ADD COLUMN exclude_patterns TEXT",
        "ALTER TABLE sync_rules ADD COLUMN min_file_size INTEGER",
        "ALTER TABLE sync_rules ADD COLUMN max_file_size INTEGER",
    ]
    for sql in new_columns:
        try:
            await conn.execute(text(sql))
        except Exception:
            pass  # column already exists
