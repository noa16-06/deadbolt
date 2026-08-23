"""Docker driver — reading only, for now.

Talks to the Docker API exclusively through the SDK. No `subprocess`, no
`shell=True`, no string interpolation: there is no place here where a request
field could turn into a command.

The SDK is synchronous, so every call goes through `asyncio.to_thread`. One
client is shared, guarded by a lock, because the `requests.Session` underneath
it is not thread safe.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any

import docker
from docker.errors import DockerException

from app.config import settings
from app.modules.servers.drivers.base import DriverUnavailable
from app.modules.servers.schemas import Action, ContainerOut, Memory, Port, State

log = logging.getLogger(__name__)

_client: docker.DockerClient | None = None
_lock = threading.Lock()

# Docker knows more states than the UI shows. Everything that is neither
# running nor an in-between state counts as stopped.
_STATES: dict[str, State] = {
    "running": "running",
    "paused": "paused",
    "restarting": "restarting",
    "removing": "restarting",
    "created": "exited",
    "exited": "exited",
    "dead": "exited",
}


def _connect() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.DockerClient(
            base_url=settings.docker_host, timeout=settings.docker_timeout
        )
    return _client


def _parse_time(value: str | None) -> datetime | None:
    """Docker sends nanoseconds; `fromisoformat` handles at most microseconds.

    `0001-01-01` is what Docker writes for a container that was never started.
    """
    if not value or value.startswith("0001-01-01"):
        return None
    text = value.replace("Z", "+00:00")
    if "." in text:
        head, _, rest = text.partition(".")
        separator = "+" if "+" in rest else "-"
        fraction, sign, zone = rest.partition(separator)
        text = f"{head}.{fraction[:6]}{sign}{zone}"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _state(state: dict[str, Any]) -> State:
    """Health beats status: a running but unhealthy container is a problem."""
    health = (state.get("Health") or {}).get("Status")
    status = state.get("Status", "exited")
    if status == "running" and health == "unhealthy":
        return "unhealthy"
    return _STATES.get(status, "exited")


def _since(state: dict[str, Any], created: str | None) -> datetime:
    """Since when the container has been in its current state.

    For a running one that is the start time, for a stopped one the moment it
    stopped — otherwise the list would claim a container that exited an hour
    ago had been in that state for weeks.
    """
    running = state.get("Status") in ("running", "paused", "restarting")
    order = (
        [state.get("StartedAt"), state.get("FinishedAt"), created]
        if running
        else [state.get("FinishedAt"), state.get("StartedAt"), created]
    )
    for value in order:
        parsed = _parse_time(value)
        if parsed is not None:
            return parsed
    return datetime.now(timezone.utc)


def _ports(network: dict[str, Any]) -> list[Port]:
    """Published ports, deduplicated.

    Docker lists a port bound to both IPv4 and IPv6 twice — that is one port
    to a reader, not two.
    """
    seen: set[tuple[int, int, str]] = set()
    result: list[Port] = []
    for key, bindings in (network.get("Ports") or {}).items():
        container_port, _, protocol = key.partition("/")
        for binding in bindings or []:
            try:
                entry = (
                    int(binding["HostPort"]),
                    int(container_port),
                    protocol or "tcp",
                )
            except (KeyError, ValueError):
                continue
            if entry in seen:
                continue
            seen.add(entry)
            result.append(Port(host=entry[0], container=entry[1], protocol=entry[2]))
    return sorted(result, key=lambda p: p.host)


def _cpu_percent(stats: dict[str, Any]) -> float:
    """Same calculation `docker stats` uses: delta against the system delta."""
    cpu = stats.get("cpu_stats") or {}
    previous = stats.get("precpu_stats") or {}
    try:
        delta = cpu["cpu_usage"]["total_usage"] - previous["cpu_usage"]["total_usage"]
        system = cpu["system_cpu_usage"] - previous["system_cpu_usage"]
    except (KeyError, TypeError):
        return 0.0
    if delta <= 0 or system <= 0:
        return 0.0
    cores = (
        cpu.get("online_cpus")
        or len(cpu.get("cpu_usage", {}).get("percpu_usage") or [])
        or 1
    )
    return round(delta / system * cores * 100, 1)


def _memory(stats: dict[str, Any]) -> Memory:
    """Memory minus page cache — the number `docker stats` shows.

    Raw `usage` includes the cache and makes almost every container look full.
    """
    mem = stats.get("memory_stats") or {}
    used = mem.get("usage", 0) - (mem.get("stats") or {}).get("inactive_file", 0)
    return Memory(
        used=max(0, int(used / 1024 / 1024)),
        limit=int(mem.get("limit", 0) / 1024 / 1024),
    )


# ------------------------------------------------------------------ blocking
def _read_containers() -> list[dict[str, Any]]:
    with _lock:
        return [c.attrs for c in _connect().containers.list(all=True)]


def _read_stats(container_id: str) -> dict[str, Any] | None:
    with _lock:
        return _connect().api.stats(container_id, stream=False)


def _read_logs(container_id: str, lines: int) -> bytes:
    with _lock:
        return _connect().api.logs(
            container_id, stdout=True, stderr=True, tail=lines, timestamps=True
        )


# ------------------------------------------------------------------ driver
class DockerDriver:
    name = "docker"

    async def status(self) -> list[ContainerOut]:
        """Container list — live, without stats.

        CPU and RAM come from the sampler's cache: Docker needs about a second
        per container for a delta, and that must not sit in the request path.
        """
        from app.modules.servers import sampler

        try:
            raw = await asyncio.to_thread(_read_containers)
        except DockerException as error:
            log.warning("Docker not reachable at %s: %s", settings.docker_host, error)
            raise DriverUnavailable(
                f"Docker not reachable at {settings.docker_host}"
            ) from error

        containers: list[ContainerOut] = []
        for attrs in raw:
            state = attrs.get("State") or {}
            config = attrs.get("Config") or {}
            labels = config.get("Labels") or {}
            measured = sampler.container_stats(attrs["Id"])
            containers.append(
                ContainerOut(
                    # Short id, the way Docker itself shows it.
                    id=attrs["Id"][:12],
                    name=(attrs.get("Name") or "").lstrip("/"),
                    image=config.get("Image") or "",
                    state=_state(state),
                    since=_since(state, attrs.get("Created")),
                    ports=_ports(attrs.get("NetworkSettings") or {}),
                    cpu=measured[0] if measured else 0.0,
                    ram=measured[1] if measured else Memory(used=0, limit=0),
                    stack=labels.get("com.docker.compose.project", ""),
                )
            )
        return sorted(containers, key=lambda c: c.name)

    async def action(self, target_id: str, action: Action) -> None:
        raise NotImplementedError(
            "Write access comes after TOTP and rate limiting — see docs/security.md"
        )

    async def logs(self, container_id: str, lines: int) -> str:
        """Last lines of a container.

        `tail` is an int and goes out as an API parameter, not as part of a
        command line. Output is decoded leniently: log lines are whatever the
        process wrote, not guaranteed UTF-8.
        """
        try:
            raw = await asyncio.to_thread(_read_logs, container_id, lines)
        except DockerException as error:
            raise DriverUnavailable(str(error)) from error
        return raw.decode("utf-8", errors="replace")

    async def stats(self, container_id: str) -> tuple[float, Memory] | None:
        """One-shot stats for a running container. Only the sampler calls this."""
        try:
            raw = await asyncio.to_thread(_read_stats, container_id)
        except DockerException:
            return None
        if not raw:
            return None
        return _cpu_percent(raw), _memory(raw)

    async def running_ids(self) -> list[str]:
        try:
            raw = await asyncio.to_thread(_read_containers)
        except DockerException as error:
            raise DriverUnavailable(str(error)) from error
        return [
            a["Id"] for a in raw if (a.get("State") or {}).get("Status") == "running"
        ]
