"""HTTP endpoints for signing in."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.config import settings
from app.deps import CurrentUser, DbSession, client_ip
from app.modules.auth import service
from app.modules.auth.schemas import (
    LoginInput,
    TotpConfirmInput,
    TotpConfirmOut,
    TotpSetupOut,
    UserOut,
)
from app.security import (
    COOKIE_MAX_AGE,
    COOKIE_NAME,
    create_session,
    new_totp_secret,
    totp_uri,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
async def login(data: LoginInput, request: Request, response: Response, session: DbSession):
    ip = client_ip(request)

    try:
        await service.check_rate_limit(session, data.username, ip)
    except service.RateLimited as limited:
        log.warning("Login rate limited username=%r ip=%s", data.username, ip)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many attempts. Try again later.",
            headers={"Retry-After": str(limited.retry_after_seconds)},
        ) from None

    result = await service.authenticate_user(
        session, data.username, data.password, data.code
    )
    if result.user is None:
        # Failed attempts belong in the log — but never the password.
        log.warning(
            "Login failed username=%r ip=%s totp_missing=%s",
            data.username,
            ip,
            result.totp_missing,
        )
        await service.record_failure(session, data.username, ip)
        # Deliberately the same answer whether the password was wrong or the
        # code was missing. Saying "now the code, please" would confirm that
        # the password was right, which is half the secret.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Wrong username, password or code"
        )

    await service.clear_failures(session, data.username, ip)
    response.set_cookie(
        COOKIE_NAME,
        create_session(result.user.id),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return result.user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return UserOut(
        id=user.id,
        username=user.username,
        totp_enabled=user.totp_enabled,
        auth_disabled=settings.auth_disabled,
    )


# ------------------------------------------------------------------ enrolment
@router.post("/totp/setup", response_model=TotpSetupOut)
async def totp_setup(user: CurrentUser, session: DbSession):
    """Start enrolment: new secret, not switched on yet.

    Calling this again replaces an unconfirmed secret — a setup abandoned
    halfway should not block the next attempt.
    """
    if user.totp_enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "TOTP is already enabled. Disable it first to enrol again.",
        )
    secret = new_totp_secret()
    await service.start_totp_enrolment(session, user, secret)
    return TotpSetupOut(secret=secret, uri=totp_uri(secret, user.username))


@router.post("/totp/confirm", response_model=TotpConfirmOut)
async def totp_confirm(data: TotpConfirmInput, user: CurrentUser, session: DbSession):
    """Switch TOTP on once a code proves the authenticator app works.

    The recovery codes in the response are the only time they exist in plain
    text — they are stored hashed.
    """
    codes = await service.confirm_totp(session, user, data.code)
    if codes is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code does not match")
    log.warning("TOTP enabled for username=%r", user.username)
    return TotpConfirmOut(recovery_codes=codes)
