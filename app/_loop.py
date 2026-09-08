"""Cross-platform asyncio configuration.

Async PostgreSQL drivers (psycopg async, asyncpg) do not support Windows'
default ProactorEventLoop. On Windows we therefore force the
SelectorEventLoop policy so that ``app.main``, ``trace_schema``, uvicorn and
pytest all create compatible loops.
"""

from __future__ import annotations

import asyncio
import sys


def configure_asyncio_policy() -> None:
    if sys.platform == "win32":
        selector = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
        if selector is not None:
            asyncio.set_event_loop_policy(selector())


def _apply() -> None:
    configure_asyncio_policy()


_apply()