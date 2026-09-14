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
    ("developers", "is_demo", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("repositories", "owner_id", "INTEGER"),
    ("repositories", "is_private", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("github_events", "owner_id", "INTEGER"),
    ("github_events", "is_private", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("sync_jobs", "owner_id", "INTEGER"),
    ("sync_jobs", "use_token", "BOOLEAN NOT NULL DEFAULT FALSE"),
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
        await conn.execute(
            text(
                "ALTER TABLE repositories "
                "DROP CONSTRAINT IF EXISTS uq_repositories_github_id"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE repositories "
                "DROP CONSTRAINT IF EXISTS uq_repositories_full_name"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE github_events "
                "DROP CONSTRAINT IF EXISTS uq_github_event_identity"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_repositories_owner_github_id ON repositories (owner_id, github_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_repositories_owner_full_name ON repositories (owner_id, full_name)"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_github_event_identity "
                "ON github_events (owner_id, developer_id, provider, github_event_id)"
            )
        )
        for table, constraint in (
            ("repositories", "fk_repositories_owner_id"),
            ("github_events", "fk_github_events_owner_id"),
            ("sync_jobs", "fk_sync_jobs_owner_id"),
        ):
            await conn.execute(
                text(
                    "DO $$ BEGIN "
                    "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
                    f"WHERE conname = '{constraint}') THEN "
                    f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
                    "FOREIGN KEY (owner_id) REFERENCES developers(id) "
                    "ON DELETE CASCADE; "
                    "END IF; END $$;"
                )
            )