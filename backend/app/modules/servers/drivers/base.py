"""What every driver has in common — and that is not much.

Docker SDK, Proxmox API and systemd/D-Bus share no concepts. What they do share
is the shape the service layer above needs: read a state, trigger one action
from a fixed list. Everything below this line is driver specific and stays
there.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.modules.servers.schemas import Action, ContainerOut


class DriverUnavailable(RuntimeError):
    """Target system does not answer — a 503, not a 500.

    A stopped Docker daemon is a normal operating state, not a bug in the
    dashboard, and it should read that way to the caller.
    """


@runtime_checkable
class Driver(Protocol):
    """Every driver can do exactly these two things."""

    name: str

    async def status(self) -> list[ContainerOut]:
        """Current state of all targets this driver is responsible for."""
        ...

    async def action(self, target_id: str, action: Action) -> None:
        """Trigger one action from the whitelist.

        `target_id` is user input and has to be checked against the configured
        target list first — never passed straight through. No implementation
        ever builds a shell command from it.
        """
        ...
