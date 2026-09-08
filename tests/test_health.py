"""Tests for the health and root operational endpoints."""

from app.deps import get_db
from tests.conftest import async_test_client


async def test_root(app):
    async with async_test_client(app) as client:
        response = await client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["app"] == "TRACE"
    assert body["version"] == "0.3.0"


async def test_health_ok(app):
    async with async_test_client(app) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


async def test_health_database_unavailable(app):
    class BrokenSession:
        async def execute(self, *a, **kw):
            raise ConnectionError("fake db down")

    async def override_get_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with async_test_client(app) as client:
            response = await client.get("/health")
        assert response.status_code == 503
        assert response.json()["status"] == "degraded"
    finally:
        del app.dependency_overrides[get_db]