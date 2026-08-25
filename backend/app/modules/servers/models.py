"""Tables of the server manager.

Only one, and it is not a cache: the audit log. `docs/security.md` asks for
who did what to which target, when, and with what outcome — a start button
reachable from the internet is worth nothing without a record of who pressed
it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ControlLog(Base):
    """One row per attempted write action — refused ones included.

    A refused attempt is the more interesting half. "Someone tried to restart a
    container that is not on the allow-list" is exactly what nobody notices
    when only successes are written down.
    """

    __tablename__ = "servers_control_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Nullable and SET NULL: deleting an account must not delete the record of
    # what that account did. The username below is a snapshot for that reason —
    # it stays readable once the row it pointed at is gone.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    username: Mapped[str] = mapped_column(String(64))
    ip: Mapped[str] = mapped_column(String(45))  # 45 = longest IPv6 form

    # The id as the request sent it. Kept even when no such container exists —
    # that is the case worth being able to look up afterwards.
    container_id: Mapped[str] = mapped_column(String(64))
    # Empty when the id matched nothing.
    container_name: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(16))

    ok: Mapped[bool] = mapped_column(Boolean)
    # Why it failed, in the words the caller was given. None on success.
    detail: Mapped[str | None] = mapped_column(String(255), default=None)

    __table_args__ = (
        # The one query a log is read with: newest first.
        Index("ix_servers_control_log_at", "at"),
    )
