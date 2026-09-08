"""Developer profile endpoints backed by persisted ingestion data."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.schemas import (
    DeveloperListItemResponse,
    DeveloperProfileResponse,
)
from app.services import profiles

router = APIRouter(tags=["developers"])


@router.get("/developers", response_model=list[DeveloperListItemResponse])
async def list_developers(
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List every ingested developer with high-level stats."""
    return await profiles.list_developers(db)


@router.get(
    "/developers/{username}",
    response_model=DeveloperProfileResponse,
)
async def get_developer(
    username: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return a developer's aggregated profile from PostgreSQL."""
    return await profiles.get_developer_profile(db, username)