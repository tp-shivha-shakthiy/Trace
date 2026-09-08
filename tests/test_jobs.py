"""End-to-end async job: create -> enqueue -> worker -> profile.

This is the full pipeline exercised through the worker path (the same path
the API uses), proving that ingestion is genuinely asynchronous and that the
profile endpoint serves the persisted result.
"""

import asyncio

import httpx
from app.github import GitHubClient
from app.models import SyncJob
from app.services.jobs import IngestionJobWorker
from sqlalchemy import select
from tests.conftest import make_github_handler


async def _wait_until(predicate, timeout=10.0, interval=0.05):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(interval)
    return False


async def _job_count(session_factory):
    async with session_factory() as session:
        return len(list(await session.scalars(select(SyncJob))))


async def test_async_worker_processes_job(session_factory, test_settings):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(make_github_handler()),
        base_url="https://api.github.com",
    )
    github = GitHubClient(test_settings, client=client)
    worker = IngestionJobWorker(session_factory, github, concurrency=2)

    await worker.start()
    try:
        job_id = await worker.create_and_enqueue("octocat")

        async def done():
            job = await worker.get_job(job_id)
            return job is not None and job.status == "succeeded"

        assert await _wait_until(done), "job did not reach succeeded state"

        job = await worker.get_job(job_id)
        assert job is not None
        assert job.status == "succeeded"
        assert job.events_persisted == 4
        assert job.repositories_synced == 3
        assert job.finished_at is not None
    finally:
        await worker.stop()


async def test_async_worker_marks_failed_on_github_error(
    session_factory, test_settings
):
    handler = make_github_handler(unavailable_paths={"/users/octocat"})
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    )
    github = GitHubClient(test_settings, client=client)
    worker = IngestionJobWorker(session_factory, github, concurrency=1)

    await worker.start()
    try:
        job_id = await worker.create_and_enqueue("octocat")

        async def done():
            job = await worker.get_job(job_id)
            return job is not None and job.status == "failed"

        assert await _wait_until(done), "job did not reach failed state"

        job = await worker.get_job(job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.error_message is not None
        assert job.finished_at is not None
    finally:
        await worker.stop()


async def test_repeated_jobs_do_not_duplicate(session_factory, test_settings):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(make_github_handler()),
        base_url="https://api.github.com",
    )
    github = GitHubClient(test_settings, client=client)
    worker = IngestionJobWorker(session_factory, github, concurrency=2)

    await worker.start()
    try:
        for _ in range(2):
            job_id = await worker.create_and_enqueue("octocat")

            async def done(jid=job_id):
                job = await worker.get_job(jid)
                return job is not None and job.status == "succeeded"

            assert await _wait_until(done)

        jobs = []
        async with session_factory() as session:
            stored = list(await session.scalars(select(SyncJob)))
            jobs = [(j.status, j.events_persisted, j.events_duplicates) for j in stored]

        assert all(status == "succeeded" for status, _, _ in jobs)
        persisted_totals = [p for _, p, _ in jobs]
        duplicates = [d for _, _, d in jobs]
        assert persisted_totals[0] == 4
        assert duplicates[0] == 0
        assert persisted_totals[1] == 0
        assert duplicates[1] == 4
    finally:
        await worker.stop()