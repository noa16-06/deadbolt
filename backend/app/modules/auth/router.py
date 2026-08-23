"""HTTP endpoints for signing in."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response, status

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.modules.auth import service
from app.modules.auth.schemas import LoginInput, UserOut
from app.security import COOKIE_MAX_AGE, COOKIE_NAME, create_session

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
async def login(data: LoginInput, response: Response, session: DbSession):
    user = await service.authenticate_user(session, data.username, data.password)
    if user is None:
        # Failed attempts belong in the log — but never the password.
        log.warning("Login failed for username=%r", data.username)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Wrong username or password"
        )

    response.set_cookie(
        COOKIE_NAME,
        create_session(user.id),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user
