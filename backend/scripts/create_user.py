#!/usr/bin/env python3
"""Create a user. The password is asked for interactively.

    python scripts/create_user.py

Deliberately a script and not an endpoint: this dashboard is meant to be
reachable from the internet later, and an open /register would be exactly the
door you do not want there. The password never lands in a file — not in the
shell history either.
"""

from __future__ import annotations

import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionFactory, engine  # noqa: E402
from app.modules.auth import service  # noqa: E402

MIN_LENGTH = 12


async def main() -> int:
    username = input("Username: ").strip()
    if not username:
        print("Aborted: no username.", file=sys.stderr)
        return 1

    password = getpass.getpass("Password: ")
    if len(password) < MIN_LENGTH:
        print(
            f"Aborted: at least {MIN_LENGTH} characters. "
            "Your whole homelab sits behind this login later.",
            file=sys.stderr,
        )
        return 1
    if password != getpass.getpass("Repeat password: "):
        print("Aborted: passwords do not match.", file=sys.stderr)
        return 1

    try:
        async with SessionFactory() as session:
            user = await service.create_user(session, username, password)
    except ValueError as error:
        print(f"Aborted: {error}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    print(f"User {user.username!r} created (id={user.id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
