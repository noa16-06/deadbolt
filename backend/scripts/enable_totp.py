#!/usr/bin/env python3
"""Enable TOTP for a user — QR code in the terminal.

    python scripts/enable_totp.py

A script rather than a settings page, for the same reason `create_user.py` is
one: enrolment happens once, on the host, and does not need an endpoint that
exists for the rest of time. The API has `/api/auth/totp/setup` and
`/confirm` as well, for the day there is a settings screen.

Nothing is switched on until a code from the app has actually matched. A
half-finished setup would otherwise lock the account out.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import qrcode  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import SessionFactory, engine  # noqa: E402
from app.modules.auth import service  # noqa: E402
from app.modules.auth.models import User  # noqa: E402
from app.security import new_totp_secret, totp_uri  # noqa: E402


def print_qr(uri: str) -> None:
    """ASCII QR — scannable straight from the terminal, no image file."""
    code = qrcode.QRCode(border=1)
    code.add_data(uri)
    code.make(fit=True)
    code.print_ascii(invert=True)


async def main() -> int:
    username = input("Username: ").strip()
    if not username:
        print("Aborted: no username.", file=sys.stderr)
        return 1

    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.username == username))
        if user is None:
            print(f"Aborted: no user {username!r}.", file=sys.stderr)
            return 1
        if user.totp_enabled:
            print(
                f"Aborted: {username!r} already has TOTP. "
                "Disabling it again is a deliberate step, not a flag here.",
                file=sys.stderr,
            )
            return 1

        secret = new_totp_secret()
        uri = totp_uri(secret, user.username)
        await service.start_totp_enrolment(session, user, secret)

        print("\nScan this with your authenticator app:\n")
        print_qr(uri)
        print(f"Or type the secret by hand: {secret}\n")

        code = input("Code from the app: ").strip()
        recovery = await service.confirm_totp(session, user, code)
        if recovery is None:
            print(
                "Aborted: code does not match. Nothing was switched on — "
                "check the clock on your phone and run this again.",
                file=sys.stderr,
            )
            return 1

    await engine.dispose()

    print(f"\nTOTP is on for {username!r}.\n")
    print("Recovery codes — each works once, and this is the only time they")
    print("are shown. Put them somewhere that is not this machine:\n")
    for entry in recovery:
        print(f"    {entry}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
