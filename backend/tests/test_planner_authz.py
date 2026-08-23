"""The test that matters first: can user A reach user B's data?

Not "does the endpoint return 200" — that is the boring case.
"""

from datetime import date

import pytest

pytestmark = pytest.mark.asyncio


async def test_foreign_block_is_unreachable(client_a, client_b):
    response = await client_a.post(
        "/api/planner/blocks",
        json={"weekday": "Mon", "time": "07:15", "title": "School", "category": "school"},
    )
    block_id = response.json()["id"]

    # B knows the id — but may neither change, delete, nor tick it off.
    assert (
        await client_b.patch(f"/api/planner/blocks/{block_id}", json={"title": "hijacked"})
    ).status_code == 404
    assert (await client_b.delete(f"/api/planner/blocks/{block_id}")).status_code == 404
    assert (
        await client_b.put(
            f"/api/planner/blocks/{block_id}/completion",
            json={"date": date.today().isoformat(), "done": True},
        )
    ).status_code == 404


async def test_completion_is_bound_to_one_day(client_a):
    """Ticking something off today must not tick it off tomorrow.

    This is the whole reason completions live in their own table instead of
    being a boolean on the weekday template.
    """
    week = (await client_a.post("/api/planner/default-plan")).json()
    block = week["Mon"]["blocks"][0]
    monday = week["Mon"]["date"]

    await client_a.put(
        f"/api/planner/blocks/{block['id']}/completion",
        json={"date": monday, "done": True},
    )

    same_week = (await client_a.get(f"/api/planner/week?date={monday}")).json()
    assert same_week["Mon"]["blocks"][0]["done"] is True
    assert same_week["Tue"]["blocks"][0]["done"] is False
