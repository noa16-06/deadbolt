"""Test setup: a real database, thrown away after every test.

SQLite in memory with StaticPool, so every session in a test sees the same
connection — with the default pool each one would get its own empty database.

`auth_disabled` is forced off here. The development switch lives in `.env`, and
a test suite that silently ran with the login bypassed would prove nothing
about the login.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_session
from app.main import app
from app.modules.auth import service


@pytest.fixture(autouse=True)
def real_auth(monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "trust_proxy_header", False)


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def session(session_factory):
    async with session_factory() as db:
        yield db


@pytest_asyncio.fixture
async def client(session_factory):
    """HTTP client against the real app, wired to the test database."""

    async def override():
        async with session_factory() as db:
            yield db

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def user(session):
    """A signed-up user without a second factor."""
    return await service.create_user(session, "noa", "correct-horse-battery")


@pytest_asyncio.fixture
async def client_a(client, session):
    await service.create_user(session, "user-a", "password-a-long-enough")
    await client.post(
        "/api/auth/login", json={"username": "user-a", "password": "password-a-long-enough"}
    )
    return client


@pytest_asyncio.fixture
async def client_b(session_factory, session):
    """A SECOND client with its own cookie jar — same app, same database.

    Two signed-in users cannot share one client: the cookie would be
    overwritten and the test would quietly check one user against himself.
    """

    async def override():
        async with session_factory() as db:
            yield db

    app.dependency_overrides[get_session] = override
    await service.create_user(session, "user-b", "password-b-long-enough")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post(
            "/api/auth/login",
            json={"username": "user-b", "password": "password-b-long-enough"},
        )
        yield c
