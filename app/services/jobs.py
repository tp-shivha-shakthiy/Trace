"""In-process asynchronous ingestion worker.

The background worker is an ``asyncio`` task pool over a bounded in-process
``asyncio.Queue`` of sync-job ids. It is started/stopped by the FastAPI
lifespan and processes jobs independently of request/response handling:

    POST /api/v1/sync  -->  create SyncJob row  -->  enqueue job id
    worker task        -->  pop job id         -->  IngestionService.run()
    job row            -->  running -> succeeded/failed + counts

This is *genuinely asynchronous* while requiring no extra infrastructure
(no Celery/Redis). Job state is persisted in PostgreSQL, so the status is
queryable from the API. In-process delivery means queued jobs are lost on
process restart; see README "Current limitations".
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.errors import GitHubError
from app.github import GitHubClient
from app.models import SyncJob
from app.services.domains import DomainInference
from app.services.ingestion import IngestionService

logger = logging.getLogger("trace.jobs")

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_SUCCEEDED = "succeeded"
JOB_FAILED = "failed"


class IngestionJobWorker:
    """Pulls sync-job ids from a queue and processes them in background tasks."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        github: GitHubClient,
        domain_inference: DomainInference | None = None,
        concurrency: int = 2,
        language_repos_limit: int = 10,
    ) -> None:
        self._session_factory = session_factory
        self._github = github
        self._domains = domain_inference
        self._concurrency = concurrency or 1
        self._language_repos_limit = language_repos_limit
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []

    @property
    def queue(self) -> asyncio.Queue[str]:
        return self._queue

    async def start(self) -> None:
        if self._tasks:
            return
        logger.info("starting %d ingestion workers", self._concurrency)
        self._tasks = [
            asyncio.create_task(self._worker(index), name=f"ingestion-{index}")
            for index in range(self._concurrency)
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            results = await asyncio.gather(*self._tasks, return_exceptions=True)
            for task, result in zip(self._tasks, results, strict=True):
                if isinstance(result, asyncio.CancelledError):
                    continue
                if isinstance(result, Exception):
                    logger.error(
                        "ingestion worker %s failed: %s", task.get_name(), result
                    )
        self._tasks = []
        await self._github.aclose()

    async def create_and_enqueue(self, username: str) -> str:
        """Create a persisted ``queued`` job and hand its id to the queue."""
        async with self._session_factory() as session:
            job = SyncJob(developer_username=username)
            session.add(job)
            await session.commit()
            job_id = job.id
        await self._queue.put(job_id)
        return job_id

    async def get_job(self, job_id: str) -> SyncJob | None:
        async with self._session_factory() as session:
            return await session.get(SyncJob, job_id)

    async def _worker(self, index: int) -> None:
        logger.info("ingestion worker %d ready", index)
        while True:
            job_id = await self._queue.get()
            try:
                await self._process_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("unexpected worker error for job %s", job_id)
                await self._mark_failed(job_id, f"internal error: {exc}")
            finally:
                self._queue.task_done()

    async def _process_job(self, job_id: str) -> None:
        job = await self.get_job(job_id)
        if job is None:
            logger.warning("job %s not found", job_id)
            return
        await self._mark_running(job_id)
        service = IngestionService(
            self._github,
            self._session_factory,
            domain_inference=self._domains,
            language_repos_limit=self._language_repos_limit,
        )
        try:
            result = await service.run(job.developer_username)
        except GitHubError as exc:
            await self._mark_failed(job_id, str(exc))
            return
        except Exception as exc:
            logger.exception("ingestion failed for %s", job.developer_username)
            await self._mark_failed(job_id, str(exc))
            return

        async with self._session_factory() as session:
            stored = await session.get(SyncJob, job_id)
            if stored is None:
                return
            stored.status = JOB_SUCCEEDED
            stored.finished_at = datetime.now(UTC)
            stored.developer_id = result.developer_id
            stored.repositories_synced = result.repositories_synced
            stored.events_fetched = result.events_fetched
            stored.events_persisted = result.events_persisted
            stored.events_duplicates = result.events_duplicates
            await session.commit()
        logger.info(
            "job %s succeeded: %d repos, %d events (+%d dup skipped)",
            job_id,
            result.repositories_synced,
            result.events_persisted,
            result.events_duplicates,
        )

    async def _mark_running(self, job_id: str) -> None:
        async with self._session_factory() as session:
            job = await session.get(SyncJob, job_id)
            if job is not None:
                job.status = JOB_RUNNING
                job.started_at = datetime.now(UTC)
                await session.commit()

    async def _mark_failed(self, job_id: str, error_message: str) -> None:
        async with self._session_factory() as session:
            job = await session.get(SyncJob, job_id)
            if job is not None:
                job.status = JOB_FAILED
                job.error_message = error_message
                job.finished_at = datetime.now(UTC)
                await session.commit()


@contextlib.asynccontextmanager
async def managed_worker(worker: IngestionJobWorker):
    """Small helper for tests / scripts that run a worker manually."""
    await worker.start()
    try:
        yield worker
    finally:
        await worker.stop()