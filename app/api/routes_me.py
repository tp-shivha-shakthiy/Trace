"""Authenticated current-user endpoints (the owner's full profile).

``GET /api/v1/me``            - the authenticated user's identity
``GET /api/v1/me/profile``    - the owner's complete profile, including
                                private repositories and private-derived
                                intelligence

Both require a valid application session (the HttpOnly cookie issued at
GitHub OAuth success). Ownership is derived from the session, never from
client-supplied developer ids or usernames.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_developer, get_db
from app.models import Developer
from app.schemas import DeveloperProfileResponse, MeResponse
from app.services import profiles

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeResponse)
async def me(
    current: Developer = Depends(get_current_developer),
) -> MeResponse:
    """Return the authenticated TRACE user's identity."""
    return MeResponse(
        username=current.username,
        name=current.name,
        avatar_url=current.avatar_url,
        html_url=current.html_url,
    )


@router.get(
    "/me/profile",
    response_model=DeveloperProfileResponse,
)
async def my_profile(
    current: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the authenticated owner's full profile (public + private)."""
    return await profiles.get_my_profile(db, current)