"""Validation at the boundary — unchecked browser input arrives here."""

from __future__ import annotations

import re
from datetime import date as DateType
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Weekday = Literal["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
Category = Literal["morning", "training", "school", "infosec", "freelance", "other"]

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# A plan is not kept for decades. Bounding the date keeps someone from filling
# the completions table with rows for the year 9999.
MAX_DAYS_FROM_TODAY = 366


def _check_date(value: DateType) -> DateType:
    if abs((value - DateType.today()).days) > MAX_DAYS_FROM_TODAY:
        raise ValueError("Date is more than a year away from today")
    return value


class BlockCreate(BaseModel):
    weekday: Weekday
    time: str
    title: str = Field(min_length=1, max_length=200)
    category: Category = "other"

    @field_validator("time")
    @classmethod
    def time_format(cls, v: str) -> str:
        if not _TIME.match(v):
            raise ValueError("Time must be in HH:MM format")
        return v


class BlockUpdate(BaseModel):
    """Partial update — only the fields that were sent are applied.

    `done` is deliberately absent: a completion belongs to a date and goes
    through the completion endpoint.
    """

    time: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    category: Category | None = None

    @field_validator("time")
    @classmethod
    def time_format(cls, v: str | None) -> str | None:
        if v is not None and not _TIME.match(v):
            raise ValueError("Time must be in HH:MM format")
        return v


class BlockOut(BaseModel):
    id: int
    weekday: str
    time: str
    title: str
    category: str
    done: bool


class TodoCreate(BaseModel):
    weekday: Weekday
    title: str = Field(min_length=1, max_length=200)
    category: Category = "other"


class TodoUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    category: Category | None = None


class TodoOut(BaseModel):
    id: int
    weekday: str
    title: str
    category: str
    done: bool


class CompletionUpdate(BaseModel):
    """Tick an entry off for one specific day."""

    date: DateType
    done: bool

    @field_validator("date")
    @classmethod
    def sane_date(cls, v: DateType) -> DateType:
        return _check_date(v)


class DayOut(BaseModel):
    """One weekday of the plan, plus the concrete date it maps to this week.

    The date comes from the server so the UI does not have to redo the
    week arithmetic — and so both sides agree on which day was ticked.
    """

    date: DateType
    blocks: list[BlockOut]
    todos: list[TodoOut]


def week_start(day: DateType) -> DateType:
    """Monday of the week containing `day`."""
    return day - timedelta(days=day.weekday())


__all__ = [
    "BlockCreate", "BlockUpdate", "BlockOut",
    "TodoCreate", "TodoUpdate", "TodoOut",
    "CompletionUpdate", "DayOut", "week_start",
]
