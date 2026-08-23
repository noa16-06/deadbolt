"""HTTP endpoints of the weekly planner."""

from __future__ import annotations

from datetime import date as DateType

from fastapi import APIRouter, HTTPException, Query, status

from app.deps import CurrentUser, DbSession
from app.modules.planner import service
from app.modules.planner.schemas import (
    BlockCreate,
    BlockOut,
    BlockUpdate,
    CompletionUpdate,
    DayOut,
    TodoCreate,
    TodoOut,
    TodoUpdate,
)

router = APIRouter(prefix="/api/planner", tags=["planner"])

# The plan itself is weekday based; whether something is ticked off depends on
# the day. Without a date the answer would be ambiguous, so it defaults to today.
DateParam = Query(
    default=None, description="Day the completions refer to (default: today)"
)


def _resolve(on_date: DateType | None) -> DateType:
    return on_date or DateType.today()


@router.get("/week", response_model=dict[str, DayOut])
async def week(
    user: CurrentUser,
    session: DbSession,
    date: DateType | None = DateParam,
):
    """Full weekly plan — the UI loads this once on start."""
    return await service.load_week(session, user.id, _resolve(date))


@router.post("/default-plan", response_model=dict[str, DayOut])
async def default_plan(
    user: CurrentUser,
    session: DbSession,
    date: DateType | None = DateParam,
):
    """Create the default plan if the week is empty, then return the week.

    If anything is there already nothing is touched — calling this repeatedly
    is harmless.
    """
    await service.create_default_plan(session, user.id)
    return await service.load_week(session, user.id, _resolve(date))


# ------------------------------------------------------------------ blocks
@router.post("/blocks", response_model=BlockOut, status_code=201)
async def create_block(data: BlockCreate, user: CurrentUser, session: DbSession):
    return await service.create_block(session, user.id, data)


@router.patch("/blocks/{block_id}", response_model=BlockOut)
async def update_block(
    block_id: int,
    patch: BlockUpdate,
    user: CurrentUser,
    session: DbSession,
    date: DateType | None = DateParam,
):
    block = await service.update_block(
        session, user.id, block_id, patch, _resolve(date)
    )
    if block is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Block not found")
    return block


@router.delete("/blocks/{block_id}", status_code=204)
async def delete_block(block_id: int, user: CurrentUser, session: DbSession):
    if not await service.delete_block(session, user.id, block_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Block not found")


@router.put("/blocks/{block_id}/completion", status_code=204)
async def set_block_completion(
    block_id: int, data: CompletionUpdate, user: CurrentUser, session: DbSession
):
    """Tick a block off for one specific day."""
    if not await service.set_block_completion(
        session, user.id, block_id, data.date, data.done
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Block not found")


# ------------------------------------------------------------------ todos
@router.post("/todos", response_model=TodoOut, status_code=201)
async def create_todo(data: TodoCreate, user: CurrentUser, session: DbSession):
    return await service.create_todo(session, user.id, data)


@router.patch("/todos/{todo_id}", response_model=TodoOut)
async def update_todo(
    todo_id: int,
    patch: TodoUpdate,
    user: CurrentUser,
    session: DbSession,
    date: DateType | None = DateParam,
):
    todo = await service.update_todo(session, user.id, todo_id, patch, _resolve(date))
    if todo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Todo not found")
    return todo


@router.delete("/todos/{todo_id}", status_code=204)
async def delete_todo(todo_id: int, user: CurrentUser, session: DbSession):
    if not await service.delete_todo(session, user.id, todo_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Todo not found")


@router.put("/todos/{todo_id}/completion", status_code=204)
async def set_todo_completion(
    todo_id: int, data: CompletionUpdate, user: CurrentUser, session: DbSession
):
    if not await service.set_todo_completion(
        session, user.id, todo_id, data.date, data.done
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Todo not found")
