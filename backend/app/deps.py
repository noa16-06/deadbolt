"""Shared FastAPI dependencies."""

from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.modules.auth.models import User
from app.security import COOKIE_NAME, hash_password, read_session

log = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_session)]


async def _dev_user(session: AsyncSession) -> User:
    """The first user in the database, no cookie asked for.

    Only reachable with AUTH_DISABLED=true, which `config._check_dev_switches`
    refuses to combine with anything reachable from outside.

    On an empty database it creates a `dev` user, because the planner hangs its
    rows off a real user id and "no login" should not mean "run a script
    first". Its password is a random string that is thrown away immediately: the
    row exists to own data, never to be signed in as. Once AUTH_DISABLED goes
    off, that account is unreachable rather than a leftover way in.
    """
    user = await session.scalar(select(User).order_by(User.id).limit(1))
    if user is not None:
        return user

    user = User(
        username="dev",
        password_hash=hash_password(secrets.token_urlsafe(32)),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    log.warning("AUTH_DISABLED: created user %r (no usable password)", user.username)
    return user


async def current_user(
    session: DbSession,
    dashboard_session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> User:
    """Resolve the session cookie to a user — or 401.

    Every router that touches data depends on this. Authorization afterwards
    ALWAYS happens inside the query (`where(... user_id == user.id)`), never by
    loading a row and comparing afterwards.
    """
    if settings.auth_disabled:
        return await _dev_user(session)

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
