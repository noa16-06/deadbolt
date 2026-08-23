"""Tables of the productivity tool (weekly planner).

The plan is weekday based, not date based — exactly like the UI: "Monday" is a
recurring template, not one specific 23 Aug.

Completions, however, belong to a *date*. A checkbox on a template would stay
ticked forever, so `planner_block_completions` holds one row per block and day.
"""

from __future__ import annotations

from datetime import date as DateType

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
CATEGORIES = ("morning", "training", "school", "infosec", "freelance", "other")


class Block(Base):
    """A time block in the daily plan, e.g. 17:30 training."""

    __tablename__ = "planner_blocks"
    __table_args__ = (Index("ix_blocks_user_weekday", "user_id", "weekday"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[str] = mapped_column(String(3))
    time: Mapped[str] = mapped_column(String(5))  # "HH:MM"
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20))


class Todo(Base):
    """A task attached to a weekday."""

    __tablename__ = "planner_todos"
    __table_args__ = (Index("ix_todos_user_weekday", "user_id", "weekday"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[str] = mapped_column(String(3))
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20))


class BlockCompletion(Base):
    """One row per block and day it was ticked off.

    The unique constraint makes toggling idempotent — two concurrent requests
    cannot produce two rows for the same day.
    """

    __tablename__ = "planner_block_completions"
    __table_args__ = (
        UniqueConstraint("block_id", "completed_on", name="uq_block_completion"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    block_id: Mapped[int] = mapped_column(
        ForeignKey("planner_blocks.id", ondelete="CASCADE"), index=True
    )
    completed_on: Mapped[DateType] = mapped_column(Date)


class TodoCompletion(Base):
    """Same as BlockCompletion, for tasks."""

    __tablename__ = "planner_todo_completions"
    __table_args__ = (
        UniqueConstraint("todo_id", "completed_on", name="uq_todo_completion"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    todo_id: Mapped[int] = mapped_column(
        ForeignKey("planner_todos.id", ondelete="CASCADE"), index=True
    )
    completed_on: Mapped[DateType] = mapped_column(Date)
