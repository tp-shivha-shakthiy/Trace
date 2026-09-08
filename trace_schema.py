"""Apply the TRACE schema to the configured database.

Usage::

    python -m trace_schema

Creates all tables via ``Base.metadata.create_all`` against ``DATABASE_URL``.
v0.3 uses ``create_all`` rather than Alembic migrations for simplicity.
"""

from app.config import get_settings
from app.database import build_engine
from app.models import Base
from sqlalchemy import text


async def _main() -> None:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Verify connectivity + list tables for confirmation.
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename"
            )
        )
        tables = [row[0] for row in result]
    print(f"Schema ensured for {settings.database_url.rsplit('@', 1)[-1]}")
    print("Tables:", ", ".join(tables) if tables else "(none)")
    await engine.dispose()


if __name__ == "__main__":
    import asyncio

    from app import _loop

    _loop.configure_asyncio_policy()
    asyncio.run(_main())