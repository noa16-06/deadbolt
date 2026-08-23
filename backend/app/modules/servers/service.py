"""Server manager logic. Knows no HTTP.

Reading only for now: list, metrics, logs. Write access (start/stop/restart,
terminal) comes once TOTP and the login rate limit are in place — see
`docs/security.md`. A restart button reachable from the internet behind a
single password is exactly the case that document argues against.
"""

from __future__ import annotations

import re

from app.config import settings
from app.modules.servers.drivers.docker import DockerDriver
from app.modules.servers.schemas import ContainerOut, MetricsOut

# Docker ids are hex, short or long. Anything else never reaches a driver.
_ID_PATTERN = re.compile(r"^[0-9a-f]{12,64}$")

_docker = DockerDriver()


def id_looks_valid(container_id: str) -> bool:
    return bool(_ID_PATTERN.match(container_id))


def may_be_controlled(name: str) -> bool:
    """Whitelist for the coming write phase.

    Fails closed: an empty configuration allows nothing. Reading is
    deliberately unaffected — seeing a container is harmless, restarting it
    is not.
    """
    return name in settings.control_allowlist


async def container_list() -> list[ContainerOut]:
    return await _docker.status()


async def metrics() -> MetricsOut:
    """Latest snapshot — or one taken now, if the sampler has not run yet.

    Only happens in the first seconds after start. CPU load reads 0.0 then,
    because a load needs two readings.
    """
    from app.modules.servers import sampler

    return sampler.latest_metrics() or await sampler.collect_metrics()


async def logs(container_id: str, lines: int) -> str | None:
    """Last N lines of a container — None if no such container exists.

    The id comes from the request, so it is checked against the containers that
    actually exist instead of being handed to Docker unseen. None and an empty
    log are different answers, hence not both an empty string.
    """
    existing = {c.id for c in await _docker.status()}
    if container_id not in existing:
        return None
    return await _docker.logs(container_id, lines)
