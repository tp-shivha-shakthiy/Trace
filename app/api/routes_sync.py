"""Sync / ingestion endpoints.

``POST /sync``       - create and enqueue an asynchronous ingestion job
``GET  /sync/{id}``  - query job status (queued -> running -> succeeded/failed)
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, get_worker
from app.errors import SyncJobNotFoundError
from app.schemas import (
    SyncCreatedResponse,
    SyncJobResponse,
    SyncRequest,
)
from app.services.jobs import IngestionJobWorker

router = APIRouter(tags=["sync"])


@router.post(
    "/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SyncCreatedResponse,
)
async def create_sync(
    body: SyncRequest,
    db: AsyncSession = Depends(get_db),
    worker: IngestionJobWorker = Depends(get_worker),
) -> SyncCreatedResponse:
    """Enqueue an asynchronous GitHub ingestion for a developer."""
    job_id = await worker.create_and_enqueue(body.username)
    return SyncCreatedResponse(
        job_id=job_id,
        developer_username=body.username,
        status="queued",
    )


@router.get("/sync/{job_id}", response_model=SyncJobResponse)
async def get_sync_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    worker: IngestionJobWorker = Depends(get_worker),
) -> SyncJobResponse:
    job = await worker.get_job(job_id)
    if job is None:
        raise SyncJobNotFoundError(job_id)
    return SyncJobResponse(
        id=job.id,
        developer_username=job.developer_username,
        developer_id=job.developer_id,
        status=job.status,
        error_message=job.error_message,
        events_fetched=job.events_fetched,
        events_persisted=job.events_persisted,
        events_duplicates=job.events_duplicates,
        repositories_synced=job.repositories_synced,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )