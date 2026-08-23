"""Tables of the auth module."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Set through a single UPDATE. That statement is where it is decided which
    # of several concurrent requests gets to create the default plan.
    default_plan_created: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    # Encrypted with a key derived from SECRET_KEY, never the raw base32.
    totp_secret: Mapped[str | None] = mapped_column(String(255), default=None)
    # Separate from the secret on purpose: a secret exists from the moment
    # enrolment starts, but only counts once a code has proven the app works.
    # Otherwise a half-finished setup locks the account out.
    totp_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0")
    )


class RecoveryCode(Base):
    """One-time codes for the day the phone is gone.

    Stored hashed, exactly like a password, because that is what they are.
    """

    __tablename__ = "auth_recovery_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(255))
    # Kept rather than deleted: "this code was already used" is worth seeing.
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class LoginAttempt(Base):
    """Failed sign-ins, for the rate limit.

    Only failures are recorded and a success clears them, so the table stays
    small and a normal sign-in never counts against anyone.
    """

    __tablename__ = "auth_login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Not a foreign key: attempts against a username that does not exist are
    # exactly the ones worth counting.
    username: Mapped[str] = mapped_column(String(64))
    ip: Mapped[str] = mapped_column(String(45))  # 45 = longest IPv6 form
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        # The two lookups the rate limit does on every sign-in attempt.
        Index("ix_login_attempts_ip_at", "ip", "at"),
        Index("ix_login_attempts_username_at", "username", "at"),
    )
