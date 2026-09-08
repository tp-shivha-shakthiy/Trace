"""API endpoint tests exercising the full request/response layer."""

import asyncio

from app.services.jobs import IngestionJobWorker
from tests.conftest import async_test_client


async def _wait_until(predicate, timeout=10.0, interval=0.05):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(interval)
    return False


async def test_health_endpoint(app):
    async with async_test_client(app) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_sync_and_profile_flow(app, session_factory):
    """POST /sync, wait for the async worker, then read the profile.

    ``httpx.ASGITransport`` does not run FastAPI's lifespan, so we start the
    background worker explicitly for the duration of this test — this is
    exactly what the real uvicorn process does via lifespan.
    """
    worker: IngestionJobWorker = app.state.ingestion_worker
    assert worker is not None
    await worker.start()
    try:
        async with async_test_client(app) as client:
            response = await client.post(
                "/api/v1/sync", json={"username": "octocat"}
            )
            assert response.status_code == 202
            job_id = response.json()["job_id"]
            assert response.json()["status"] == "queued"

            async def done():
                job = await worker.get_job(job_id)
                return job is not None and job.status == "succeeded"

            assert await _wait_until(done), "ingestion job did not succeed"

            status_response = await client.get(f"/api/v1/sync/{job_id}")
            profile_response = await client.get("/api/v1/developers/octocat")
            list_response = await client.get("/api/v1/developers")
    finally:
        await worker.stop()

    status_body = status_response.json()
    assert status_body["status"] == "succeeded"
    assert status_body["events_persisted"] == 4

    assert profile_response.status_code == 200
    profile = profile_response.json()
    assert profile["username"] == "octocat"
    assert profile["summary"]["total_repositories"] == 3
    assert profile["summary"]["total_events"] == 4

    developers = list_response.json()
    assert any(d["username"] == "octocat" for d in developers)


async def test_profile_not_found_returns_404(app):
    async with async_test_client(app) as client:
        response = await client.get("/api/v1/developers/nosuchuser")
    assert response.status_code == 404


async def test_invalid_username_too_long(app):
    async with async_test_client(app) as client:
        response = await client.post("/api/v1/sync", json={"username": "x" * 50})
    assert response.status_code == 422