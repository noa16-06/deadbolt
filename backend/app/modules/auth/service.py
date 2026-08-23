"""Auth business logic — knows nothing about HTTP.

Two things guard the sign-in, and they answer different questions:

* the rate limit asks "has this address or this account been guessing?" and
  runs BEFORE the password is checked, so a locked-out attacker cannot use the
  response time to tell a real user from a made-up one;
* TOTP asks "is this the right person?" and runs after the password, because
  there is nothing to second-factor until the first factor holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.auth.models import LoginAttempt, RecoveryCode, User
from app.security import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    hash_password,
    hash_recovery_code,
    new_recovery_codes,
    password_matches,
    recovery_code_matches,
    totp_matches,
)


class RateLimited(Exception):
    """Too many failed attempts. Carries how long the caller has to wait."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Too many attempts")
        self.retry_after_seconds = retry_after_seconds


@dataclass
class LoginResult:
    """Either a user, or the reason there is none.

    `totp_missing` exists so the caller can tell the form to show the code
    field. It never reaches the browser as a distinct status: from the outside
    a missing code and a wrong password are the same 401, otherwise the
    response would confirm that the password was right.
    """

    user: User | None
    totp_missing: bool = False


# ------------------------------------------------------------------ rate limit
def _window_start() -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=settings.login_window_minutes)


async def _count(session: AsyncSession, column, value: str) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(LoginAttempt)
            .where(column == value, LoginAttempt.at >= _window_start())
        )
    ) or 0


async def check_rate_limit(session: AsyncSession, username: str, ip: str) -> None:
    """Raise RateLimited if this IP or this account has been guessing.

    Two counters, because one alone is not enough: per IP stops a single host
    hammering away, per account stops the same guessing spread over many
    addresses.
    """
    # Old rows are worthless — clearing them here keeps the table from growing
    # forever without a separate job that someone has to remember to run.
    await session.execute(delete(LoginAttempt).where(LoginAttempt.at < _window_start()))

    by_ip = await _count(session, LoginAttempt.ip, ip)
    by_account = await _count(session, LoginAttempt.username, username)

    if by_ip >= settings.login_max_per_ip or by_account >= settings.login_max_per_account:
        await session.commit()
        raise RateLimited(settings.login_window_minutes * 60)

    await session.commit()


async def record_failure(session: AsyncSession, username: str, ip: str) -> None:
    session.add(LoginAttempt(username=username, ip=ip))
    await session.commit()


async def clear_failures(session: AsyncSession, username: str, ip: str) -> None:
    """A successful sign-in clears the slate for that account and address.

    Otherwise a few typos in the morning would still lock the door at noon.
    """
    await session.execute(
        delete(LoginAttempt).where(
            (LoginAttempt.username == username) | (LoginAttempt.ip == ip)
        )
    )
    await session.commit()


# ------------------------------------------------------------------ sign-in
async def authenticate_user(
    session: AsyncSession, username: str, password: str, code: str | None = None
) -> LoginResult:
    user = await session.scalar(select(User).where(User.username == username))
    if user is None:
        # Hash anyway, so that "user does not exist" does not answer faster
        # than "wrong password".
        hash_password(password)
        return LoginResult(None)
    if not password_matches(user.password_hash, password):
        return LoginResult(None)

    if not user.totp_enabled:
        return LoginResult(user)

    if not code:
        return LoginResult(None, totp_missing=True)
    if await _second_factor_holds(session, user, code):
        return LoginResult(user)
    return LoginResult(None)


async def _second_factor_holds(session: AsyncSession, user: User, code: str) -> bool:
    """A TOTP code, or one unused recovery code."""
    secret = decrypt_totp_secret(user.totp_secret) if user.totp_secret else None
    if secret and totp_matches(secret, code):
        return True
    return await _consume_recovery_code(session, user, code)


async def _consume_recovery_code(
    session: AsyncSession, user: User, code: str
) -> bool:
    """Spend a recovery code, once.

    Every unused code has to be hashed against, because a hash cannot be looked
    up. Ten argon2 verifications is the price of storing them properly.
    """
    codes = (
        await session.scalars(
            select(RecoveryCode).where(
                RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None)
            )
        )
    ).all()

    for candidate in codes:
        if recovery_code_matches(candidate.code_hash, code):
            candidate.used_at = datetime.now(timezone.utc)
            await session.commit()
            return True
    return False


# ------------------------------------------------------------------ enrolment
async def start_totp_enrolment(session: AsyncSession, user: User, secret: str) -> None:
    """Store the secret, but do not switch TOTP on yet.

    Enabling it here would lock the account out whenever the authenticator app
    was never actually set up.
    """
    user.totp_secret = encrypt_totp_secret(secret)
    user.totp_enabled = False
    await session.commit()


async def confirm_totp(session: AsyncSession, user: User, code: str) -> list[str] | None:
    """Turn TOTP on once a code proves the app works. Returns recovery codes.

    None means the code did not match and nothing was changed.
    """
    secret = decrypt_totp_secret(user.totp_secret) if user.totp_secret else None
    if not secret or not totp_matches(secret, code):
        return None

    user.totp_enabled = True
    # A fresh enrolment invalidates the old codes — otherwise a set printed for
    # a phone that is long gone still opens the door.
    await session.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = new_recovery_codes()
    for plain in codes:
        session.add(RecoveryCode(user_id=user.id, code_hash=hash_recovery_code(plain)))
    await session.commit()
    return codes


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
