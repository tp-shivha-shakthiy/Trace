"""Tests for serving the built TRACE SPA from the FastAPI app.

These tests only run locally/on machines where ``frontend/dist`` has been
built (they are skipped in CI, which never builds the frontend).
"""

from pathlib import Path

import pytest
from app.config import Settings
from app.main import create_app
from tests.conftest import TEST_DATABASE_URL, async_test_client

DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

pytestmark = pytest.mark.skipif(
    not DIST_DIR.is_dir(),
    reason="frontend/dist not built; run `npm run build` in frontend/",
)


@pytest.fixture
def spa_app(session_factory, mock_github_client):
    return create_app(
        session_factory=session_factory,
        github_client=mock_github_client,
        settings=Settings(
            database_url=TEST_DATABASE_URL,
            github_token=None,
            serve_spa=True,
        ),
    )


async def test_spa_served_at_root(spa_app):
    async with async_test_client(spa_app) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert '<div id="root">' in response.text


async def test_api_routes_still_served_when_spa_mounted(spa_app):
    async with async_test_client(spa_app) as client:
        response = await client.get("/health")
        docs = await client.get("/docs")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert docs.status_code == 200