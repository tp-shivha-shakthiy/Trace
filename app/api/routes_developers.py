"""Developer profile endpoints backed by persisted ingestion data."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_developer, get_db, get_optional_current_developer
from app.models import Developer
from app.schemas import (
    DeveloperListItemResponse,
    DeveloperProfileResponse,
)
from app.services import profiles

router = APIRouter(tags=["developers"])


@router.get("/developers", response_model=list[DeveloperListItemResponse])
async def list_developers(
    db: AsyncSession = Depends(get_db),
    current: Developer | None = Depends(get_optional_current_developer),
) -> list[dict]:
    """List every ingested developer with high-level stats."""
    return await profiles.list_developers(db, current)


@router.get(
    "/developers/{username}",
    response_model=DeveloperProfileResponse,
)
async def get_developer(
    username: str,
    db: AsyncSession = Depends(get_db),
    current: Developer | None = Depends(get_optional_current_developer),
) -> dict:
    """Return a developer's aggregated profile from PostgreSQL."""
    return await profiles.get_developer_profile(db, username, current)


@router.delete(
    "/developers/{username}/fetched",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_fetched_developer(
    username: str,
    db: AsyncSession = Depends(get_db),
    current: Developer = Depends(get_current_developer),
) -> None:
    await profiles.delete_fetched_profile(db, username, current)
    await db.commit()