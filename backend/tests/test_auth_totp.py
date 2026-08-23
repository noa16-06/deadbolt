"""TOTP: does the second factor actually stop anyone?

The interesting cases are not "a correct code works". They are: does a right
password alone still get in, does a recovery code work exactly once, and does
the response tell an attacker which half he already has.
"""

from __future__ import annotations

import pyotp
import pytest

from app.modules.auth import service
from app.security import decrypt_totp_secret

pytestmark = pytest.mark.asyncio

PASSWORD = "correct-horse-battery"


async def enable_totp(session, user) -> tuple[str, list[str]]:
    """Enrol the user the way the script does, and return secret + codes."""
    secret = pyotp.random_base32()
    await service.start_totp_enrolment(session, user, secret)
    codes = await service.confirm_totp(session, user, pyotp.TOTP(secret).now())
    assert codes is not None
    return secret, codes


async def test_password_alone_no_longer_gets_in(session, user):
    """The whole point. Before enrolment this exact call succeeded."""
    await enable_totp(session, user)

    result = await service.authenticate_user(session, "noa", PASSWORD)
    assert result.user is None
    assert result.totp_missing is True


async def test_correct_code_gets_in(session, user):
    secret, _ = await enable_totp(session, user)

    result = await service.authenticate_user(
        session, "noa", PASSWORD, pyotp.TOTP(secret).now()
    )
    assert result.user is not None


async def test_right_code_wrong_password_fails(session, user):
    """A code is not a password. Both have to hold."""
    secret, _ = await enable_totp(session, user)

    result = await service.authenticate_user(
        session, "noa", "wrong-password", pyotp.TOTP(secret).now()
    )
    assert result.user is None


async def test_missing_code_looks_the_same_from_outside(client, session, user):
    """A wrong password and a missing code must be one answer.

    Anything else confirms the password was right, which is half the secret.
    """
    await enable_totp(session, user)

    without_code = await client.post(
        "/api/auth/login", json={"username": "noa", "password": PASSWORD}
    )
    wrong_password = await client.post(
        "/api/auth/login", json={"username": "noa", "password": "nope-not-this-one"}
    )

    assert without_code.status_code == wrong_password.status_code == 401
    assert without_code.json()["detail"] == wrong_password.json()["detail"]


async def test_recovery_code_works_once(session, user):
    _, codes = await enable_totp(session, user)

    first = await service.authenticate_user(session, "noa", PASSWORD, codes[0])
    assert first.user is not None

    again = await service.authenticate_user(session, "noa", PASSWORD, codes[0])
    assert again.user is None, "a spent recovery code must not work twice"


async def test_recovery_code_tolerates_formatting(session, user):
    """Nobody should be locked out over capitals or a missing dash."""
    _, codes = await enable_totp(session, user)

    typed = codes[0].upper().replace("-", " ")
    result = await service.authenticate_user(session, "noa", PASSWORD, typed)
    assert result.user is not None


async def test_other_recovery_codes_survive(session, user):
    _, codes = await enable_totp(session, user)
    await service.authenticate_user(session, "noa", PASSWORD, codes[0])

    result = await service.authenticate_user(session, "noa", PASSWORD, codes[1])
    assert result.user is not None


async def test_enrolment_is_not_live_until_confirmed(session, user):
    """A setup abandoned halfway must not lock the account out."""
    secret = pyotp.random_base32()
    await service.start_totp_enrolment(session, user, secret)

    result = await service.authenticate_user(session, "noa", PASSWORD)
    assert result.user is not None, "unconfirmed enrolment must not block sign-in"


async def test_wrong_code_does_not_confirm(session, user):
    secret = pyotp.random_base32()
    await service.start_totp_enrolment(session, user, secret)

    assert await service.confirm_totp(session, user, "000000") is None
    assert user.totp_enabled is False


async def test_secret_is_not_stored_in_the_clear(session, user):
    """A leaked database copy should not hand over the second factor."""
    secret, _ = await enable_totp(session, user)

    assert user.totp_secret != secret
    assert secret not in user.totp_secret
    assert decrypt_totp_secret(user.totp_secret) == secret


async def test_re_enrolment_invalidates_old_recovery_codes(session, user):
    """Codes printed for a phone that is long gone must stop working."""
    _, old_codes = await enable_totp(session, user)
    user.totp_enabled = False
    _, new_codes = await enable_totp(session, user)

    stale = await service.authenticate_user(session, "noa", PASSWORD, old_codes[0])
    assert stale.user is None
    fresh = await service.authenticate_user(session, "noa", PASSWORD, new_codes[0])
    assert fresh.user is not None


async def test_full_enrolment_over_http(client, session, user):
    """The whole path a person actually walks, through the API.

    Sign in with a password, enrol, sign out, and find the password alone no
    longer enough.
    """
    signed_in = await client.post("/api/auth/login", json={"username": "noa", "password": PASSWORD})
    assert signed_in.status_code == 200
    assert signed_in.json()["totpEnabled"] is False

    setup = await client.post("/api/auth/totp/setup")
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert setup.json()["uri"].startswith("otpauth://totp/")

    confirmed = await client.post(
        "/api/auth/totp/confirm", json={"code": pyotp.TOTP(secret).now()}
    )
    assert confirmed.status_code == 200
    codes = confirmed.json()["recoveryCodes"]
    assert len(codes) == 10

    assert (await client.get("/api/auth/me")).json()["totpEnabled"] is True

    await client.post("/api/auth/logout")
    client.cookies.clear()

    without = await client.post("/api/auth/login", json={"username": "noa", "password": PASSWORD})
    assert without.status_code == 401

    with_code = await client.post(
        "/api/auth/login",
        json={"username": "noa", "password": PASSWORD, "code": pyotp.TOTP(secret).now()},
    )
    assert with_code.status_code == 200


async def test_setup_refuses_when_already_enabled(client, session, user):
    """Re-enrolling silently would invalidate the codes in someone's wallet."""
    await client.post("/api/auth/login", json={"username": "noa", "password": PASSWORD})
    setup = await client.post("/api/auth/totp/setup")
    await client.post(
        "/api/auth/totp/confirm", json={"code": pyotp.TOTP(setup.json()["secret"]).now()}
    )

    again = await client.post("/api/auth/totp/setup")
    assert again.status_code == 409


async def test_enrolment_needs_a_session(client, user):
    """Setting up a second factor is not something a stranger gets to start."""
    assert (await client.post("/api/auth/totp/setup")).status_code == 401
