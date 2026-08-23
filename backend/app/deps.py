"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.modules.auth.models import User
from app.security import COOKIE_NAME, read_session

DbSession = Annotated[AsyncSession, Depends(get_session)]


async def current_user(
    session: DbSession,
    dashboard_session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> User:
    """Resolve the session cookie to a user — or 401.

    Every router that touches data depends on this. Authorization afterwards
    ALWAYS happens inside the query (`where(... user_id == user.id)`), never by
    loading a row and comparing afterwards.
    """
    if not dashboard_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")

    user_id = read_session(dashboard_session)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")

    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
