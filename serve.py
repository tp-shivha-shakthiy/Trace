"""Local/server launcher for TRACE.

uvicorn creates its event loop *before* importing the application module, so
the policy hook in ``app._loop`` cannot fire in time when uvicorn is started
directly (``uvicorn app.main:app``). On Windows that leaves the
ProactorEventLoop, which the async PostgreSQL drivers do not support.

This launcher applies the event-loop policy first, then hands control to
uvicorn. Run::

    python serve.py

Use on any platform; it is especially required on Windows.
"""

from app import _loop

_loop.configure_asyncio_policy()

import uvicorn  # noqa: E402  (imported after the policy is configured)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)