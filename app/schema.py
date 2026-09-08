"""Database schema bootstrap and idempotent additive upgrades.

v0.3 deliberately avoids Alembic in favour of ``Base.metadata.create_all``
plus a small list of idempotent ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``
statements. This keeps new tables/columns applying safely to *already
created* clusters (e.g. a running deployment) without migrations.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.models import Base

# ``(table, column_name, column_ddl)`` applied idempotently to existing tables.
_ADDITIVE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("developers", "github_token", "VARCHAR(512)"),
)


async def ensure_database_schema(engine: AsyncEngine) -> None:
    """Create tables (if missing) and apply recorded additive column changes."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for table, column, ddl in _ADDITIVE_COLUMNS:
            await conn.execute(
                text(
                    f"ALTER TABLE {table} "
                    f"ADD COLUMN IF NOT EXISTS {column} {ddl}"
                )
            )