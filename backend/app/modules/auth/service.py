"""Auth business logic — knows nothing about HTTP."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.security import hash_password, password_matches


async def authenticate_user(
    session: AsyncSession, username: str, password: str
) -> User | None:
    user = await session.scalar(select(User).where(User.username == username))
    if user is None:
        # Hash anyway, so that "user does not exist" does not answer faster
        # than "wrong password".
        hash_password(password)
        return None
    if not password_matches(user.password_hash, password):
        return None
    return user


async def create_user(session: AsyncSession, username: str, password: str) -> User:
    """Create a user. Called from scripts/create_user.py.

    Deliberately not an endpoint: nobody wants self-registration here.
    """
    existing = await session.scalar(select(User).where(User.username == username))
    if existing is not None:
        raise ValueError(f"Username {username!r} already exists")

    user = User(username=username, password_hash=hash_password(password))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
