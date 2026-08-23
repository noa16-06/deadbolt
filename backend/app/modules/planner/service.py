"""Business logic of the weekly planner.

Important: every query filters on user_id. Never load first and compare
afterwards — otherwise the first foreign record is one guessed id away.
"""

from __future__ import annotations

from datetime import date as DateType
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.planner.default_plan import DEFAULT_BLOCKS, DEFAULT_TODOS
from app.modules.planner.schemas import week_start
from app.modules.planner.models import (
    WEEKDAYS,
    Block,
    BlockCompletion,
    Todo,
    TodoCompletion,
)


def weekday_dates(any_date: DateType) -> dict[str, DateType]:
    """Map every weekday key to its date in the week containing `any_date`."""
    start = week_start(any_date)
    return {day: start + timedelta(days=i) for i, day in enumerate(WEEKDAYS)}


async def load_week(
    session: AsyncSession, user_id: int, any_date: DateType
) -> dict[str, dict]:
    """The whole week, with `done` resolved per weekday against its own date.

    Resolving all seven days against a single date would tick Monday off
    because Tuesday was done — the completion has to match the day it belongs
    to.
    """
    dates = weekday_dates(any_date)
    first, last = dates[WEEKDAYS[0]], dates[WEEKDAYS[-1]]

    blocks = list(
        await session.scalars(
            select(Block)
            .where(Block.user_id == user_id)
            .order_by(Block.weekday, Block.time)
        )
    )
    todos = list(
        await session.scalars(
            select(Todo).where(Todo.user_id == user_id).order_by(Todo.id)
        )
    )

    # The join on user_id matters: without it another user's completion row
    # could flip a checkbox here.
    done_blocks = {
        (row.block_id, row.completed_on)
        for row in await session.execute(
            select(BlockCompletion.block_id, BlockCompletion.completed_on)
            .join(Block, Block.id == BlockCompletion.block_id)
            .where(
                Block.user_id == user_id,
                BlockCompletion.completed_on.between(first, last),
            )
        )
    }
    done_todos = {
        (row.todo_id, row.completed_on)
        for row in await session.execute(
            select(TodoCompletion.todo_id, TodoCompletion.completed_on)
            .join(Todo, Todo.id == TodoCompletion.todo_id)
            .where(
                Todo.user_id == user_id,
                TodoCompletion.completed_on.between(first, last),
            )
        )
    }

    week: dict[str, dict] = {
        day: {"date": dates[day], "blocks": [], "todos": []} for day in WEEKDAYS
    }
    for b in blocks:
        week[b.weekday]["blocks"].append(
            _block_dict(b, done=(b.id, dates[b.weekday]) in done_blocks)
        )
    for t in todos:
        week[t.weekday]["todos"].append(
            _todo_dict(t, done=(t.id, dates[t.weekday]) in done_todos)
        )
    return week


# ------------------------------------------------------------------ blocks
async def create_block(session: AsyncSession, user_id: int, data) -> dict:
    block = Block(
        user_id=user_id,
        weekday=data.weekday,
        time=data.time,
        title=data.title.strip(),
        category=data.category,
    )
    session.add(block)
    await session.commit()
    await session.refresh(block)
    return _block_dict(block, done=False)


async def update_block(
    session: AsyncSession, user_id: int, block_id: int, patch, on_date: DateType
) -> dict | None:
    block = await session.scalar(
        select(Block).where(Block.id == block_id, Block.user_id == user_id)
    )
    if block is None:
        return None
    for field, value in patch.model_dump(exclude_unset=True).items():
        setattr(block, field, value.strip() if field == "title" else value)
    await session.commit()
    await session.refresh(block)
    day_date = weekday_dates(on_date)[block.weekday]
    return _block_dict(block, done=await _block_done(session, block_id, day_date))


async def delete_block(session: AsyncSession, user_id: int, block_id: int) -> bool:
    result = await session.execute(
        delete(Block).where(Block.id == block_id, Block.user_id == user_id)
    )
    await session.commit()
    return result.rowcount > 0


# ------------------------------------------------------------------ todos
async def create_todo(session: AsyncSession, user_id: int, data) -> dict:
    todo = Todo(
        user_id=user_id,
        weekday=data.weekday,
        title=data.title.strip(),
        category=data.category,
    )
    session.add(todo)
    await session.commit()
    await session.refresh(todo)
    return _todo_dict(todo, done=False)


async def update_todo(
    session: AsyncSession, user_id: int, todo_id: int, patch, on_date: DateType
) -> dict | None:
    todo = await session.scalar(
        select(Todo).where(Todo.id == todo_id, Todo.user_id == user_id)
    )
    if todo is None:
        return None
    for field, value in patch.model_dump(exclude_unset=True).items():
        setattr(todo, field, value.strip() if field == "title" else value)
    await session.commit()
    await session.refresh(todo)
    day_date = weekday_dates(on_date)[todo.weekday]
    return _todo_dict(todo, done=await _todo_done(session, todo_id, day_date))


async def delete_todo(session: AsyncSession, user_id: int, todo_id: int) -> bool:
    result = await session.execute(
        delete(Todo).where(Todo.id == todo_id, Todo.user_id == user_id)
    )
    await session.commit()
    return result.rowcount > 0


# ------------------------------------------------------------------ completions
async def set_block_completion(
    session: AsyncSession, user_id: int, block_id: int, on_date: DateType, done: bool
) -> bool:
    """Tick a block off for one day. False means: not this user's block."""
    owned = await session.scalar(
        select(Block.id).where(Block.id == block_id, Block.user_id == user_id)
    )
    if owned is None:
        return False

    if done:
        # ON CONFLICT DO NOTHING instead of check-then-insert: the unique
        # constraint decides, so two concurrent clicks cannot double-insert.
        await session.execute(
            sqlite_insert(BlockCompletion)
            .values(block_id=block_id, completed_on=on_date)
            .on_conflict_do_nothing(index_elements=["block_id", "completed_on"])
        )
    else:
        await session.execute(
            delete(BlockCompletion).where(
                BlockCompletion.block_id == block_id,
                BlockCompletion.completed_on == on_date,
            )
        )
    await session.commit()
    return True


async def set_todo_completion(
    session: AsyncSession, user_id: int, todo_id: int, on_date: DateType, done: bool
) -> bool:
    owned = await session.scalar(
        select(Todo.id).where(Todo.id == todo_id, Todo.user_id == user_id)
    )
    if owned is None:
        return False

    if done:
        await session.execute(
            sqlite_insert(TodoCompletion)
            .values(todo_id=todo_id, completed_on=on_date)
            .on_conflict_do_nothing(index_elements=["todo_id", "completed_on"])
        )
    else:
        await session.execute(
            delete(TodoCompletion).where(
                TodoCompletion.todo_id == todo_id,
                TodoCompletion.completed_on == on_date,
            )
        )
    await session.commit()
    return True


# ------------------------------------------------------------------ seeding
async def create_default_plan(session: AsyncSession, user_id: int) -> bool:
    """Fill an empty week with the default plan. False if something was there.

    Deliberately one call in one transaction instead of 52 requests from the
    browser: idempotent, and no half-created plan if the connection drops.
    """
    # "Check, then insert" is not enough: two concurrent requests both see an
    # empty week and both create one. This single UPDATE is atomic — only the
    # caller that gets rowcount == 1 may continue.
    result = await session.execute(
        update(User)
        .where(User.id == user_id, User.default_plan_created.is_(False))
        .values(default_plan_created=True)
    )
    if result.rowcount == 0:
        # No rollback() here: it expires ALL objects in the session, including
        # the `user` from the dependency — the next attribute access would try
        # to reload synchronously and blow up in async context. The UPDATE
        # changed nothing anyway; commit just releases the write lock
        # (expire_on_commit is off).
        await session.commit()
        return False

    session.add_all(
        [
            Block(user_id=user_id, weekday=day, time=time, title=title, category=cat)
            for day, time, title, cat in DEFAULT_BLOCKS
        ]
        + [
            Todo(user_id=user_id, weekday=day, title=title, category=cat)
            for day, title, cat in DEFAULT_TODOS
        ]
    )
    await session.commit()
    return True


# ------------------------------------------------------------------ helpers
def _block_dict(block: Block, done: bool) -> dict:
    return {
        "id": block.id,
        "weekday": block.weekday,
        "time": block.time,
        "title": block.title,
        "category": block.category,
        "done": done,
    }


def _todo_dict(todo: Todo, done: bool) -> dict:
    return {
        "id": todo.id,
        "weekday": todo.weekday,
        "title": todo.title,
        "category": todo.category,
        "done": done,
    }


async def _block_done(
    session: AsyncSession, block_id: int, on_date: DateType
) -> bool:
    return (
        await session.scalar(
            select(BlockCompletion.id).where(
                BlockCompletion.block_id == block_id,
                BlockCompletion.completed_on == on_date,
            )
        )
    ) is not None


async def _todo_done(session: AsyncSession, todo_id: int, on_date: DateType) -> bool:
    return (
        await session.scalar(
            select(TodoCompletion.id).where(
                TodoCompletion.todo_id == todo_id,
                TodoCompletion.completed_on == on_date,
            )
        )
    ) is not None
