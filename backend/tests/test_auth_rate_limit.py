"""Rate limit: does guessing actually get stopped?

Two counters exist, and they cover different attacks — one host hammering away,
and the same guessing spread across many addresses. Both are tested, plus the
case that matters for daily use: a few typos must not lock the door for the
rest of the afternoon.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.modules.auth import service

pytestmark = pytest.mark.asyncio

PASSWORD = "correct-horse-battery"
WRONG = {"username": "noa", "password": "nope-not-this-one"}
RIGHT = {"username": "noa", "password": PASSWORD}


async def test_sixth_attempt_from_one_ip_is_blocked(client, user):
    for _ in range(settings.login_max_per_ip):
        assert (await client.post("/api/auth/login", json=WRONG)).status_code == 401

    blocked = await client.post("/api/auth/login", json=WRONG)
    assert blocked.status_code == 429


async def test_block_holds_even_with_the_right_password(client, user):
    """Otherwise the limit is decoration: guess until you hit it and walk in."""
    for _ in range(settings.login_max_per_ip):
        await client.post("/api/auth/login", json=WRONG)

    correct = await client.post("/api/auth/login", json=RIGHT)
    assert correct.status_code == 429
    assert "dashboard_session" not in correct.cookies


async def test_block_says_how_long_to_wait(client, user):
    for _ in range(settings.login_max_per_ip):
        await client.post("/api/auth/login", json=WRONG)

    blocked = await client.post("/api/auth/login", json=WRONG)
    assert blocked.headers["retry-after"] == str(settings.login_window_minutes * 60)


async def test_success_clears_the_slate(client, user):
    """A few typos in the morning must not lock the door at noon."""
    for _ in range(settings.login_max_per_ip - 1):
        await client.post("/api/auth/login", json=WRONG)

    assert (await client.post("/api/auth/login", json=RIGHT)).status_code == 200

    for _ in range(settings.login_max_per_ip - 1):
        assert (await client.post("/api/auth/login", json=WRONG)).status_code == 401


async def test_account_lock_survives_changing_ip(session, user):
    """Per IP alone is not enough — a botnet has plenty of addresses."""
    for i in range(settings.login_max_per_account):
        await service.record_failure(session, "noa", f"10.0.0.{i}")

    with pytest.raises(service.RateLimited):
        await service.check_rate_limit(session, "noa", "10.0.0.250")


async def test_one_account_does_not_lock_out_another(session, user):
    for i in range(settings.login_max_per_account):
        await service.record_failure(session, "noa", f"10.0.0.{i}")

    # Same guessing, different account: must still be able to sign in.
    await service.check_rate_limit(session, "someone-else", "10.0.0.250")


async def test_attempts_against_unknown_users_count(client, user):
    """Guessing usernames is guessing. It must not be free."""
    for _ in range(settings.login_max_per_ip):
        await client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin"}
        )

    blocked = await client.post("/api/auth/login", json=RIGHT)
    assert blocked.status_code == 429


async def test_old_attempts_expire(session, user, monkeypatch):
    """The window slides; a lock is not permanent."""
    for i in range(settings.login_max_per_account):
        await service.record_failure(session, "noa", f"10.0.0.{i}")

    with pytest.raises(service.RateLimited):
        await service.check_rate_limit(session, "noa", "10.0.0.250")

    # Move the window forward instead of waiting fifteen real minutes.
    monkeypatch.setattr(settings, "login_window_minutes", 0)
    await service.check_rate_limit(session, "noa", "10.0.0.250")
