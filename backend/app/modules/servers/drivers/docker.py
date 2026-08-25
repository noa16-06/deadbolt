"""Docker driver — reads container state, and performs the write actions.

Writing is `start`, `stop`, `restart` on an existing container, and creating a
new one from an image. Creating is the widest of the four by far — an image is
code that runs on this host — so the specification that reaches the SDK is
narrow on purpose: a name, an image, published ports, environment variables.
Everything that would make a container powerful (volumes, `privileged`, host
network, devices, capabilities) is pinned in `_HARDENING` and cannot be
reached from a request at all.

Talks to the Docker API exclusively through the SDK. No `subprocess`, no
`shell=True`, no string interpolation: there is no place here where a request
field could turn into a command. The action is dispatched through explicit
branches rather than `getattr(container, action)`, so a request field can never
select a method either.

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
from docker.errors import APIError, DockerException, ImageNotFound, NotFound

from app.config import settings
from app.modules.servers.drivers.base import (
    DriverUnavailable,
    TargetConflict,
    UnknownTarget,
)
from app.modules.servers.schemas import (
    Action,
    ContainerOut,
    CreateIn,
    Memory,
    Port,
    State,
)

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


def _stop_timeout() -> int:
    """Seconds Docker waits after SIGTERM before it sends SIGKILL.

    Has to stay below the client timeout: the API call blocks for the whole
    grace period, so a stop timeout at or above `DOCKER_TIMEOUT` would abort
    the very request that is doing the stopping.
    """
    return max(1, settings.docker_timeout - 2)


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


def _read_attrs(container_id: str) -> dict[str, Any]:
    with _lock:
        return _connect().containers.get(container_id).attrs


# Fixed for every container this dashboard creates, and not reachable from a
# request. Whatever the caller sends, it lands in `name`, `image`, `ports` and
# `environment` — never in one of these.
#
# `no-new-privileges` stops a setuid binary inside the image from gaining
# anything back, `network_mode` keeps the container off the host network stack,
# and passing no `volumes` and no `devices` at all means nothing of the host
# filesystem is visible from inside. `privileged=False` is Docker's default and
# stands here to be read: the whole point of this call is what it does not do.
_HARDENING: dict[str, Any] = {
    "privileged": False,
    "network_mode": "bridge",
    "security_opt": ["no-new-privileges:true"],
    "publish_all_ports": False,
    # Restarts with the daemon — a container created here is meant to stay,
    # and `unless-stopped` still respects a stop pressed in the dashboard.
    "restart_policy": {"Name": "unless-stopped"},
}

# Marks what this dashboard created, so it can be told apart from what compose
# or the CLI put on the host — the containers where a `docker rm` costs someone
# their config file.
CREATED_LABEL = "homelab.dashboard.created-by"


def _create(spec: CreateIn, created_by: str) -> str:
    """Create the container, then start it. Returns the new id.

    `containers.create` is used rather than `containers.run`, and that is the
    security-relevant half of this function: `run` pulls the image when it is
    missing, which fetches and executes code from a registry inside a request.
    `create` raises instead, and the service turns that into a 409 that says to
    pull it on the host first.

    Ports go through the SDK as a mapping of ints, the environment as a dict —
    no string is assembled here that Docker then has to take apart again.
    """
    with _lock:
        container = _connect().containers.create(
            spec.image,
            name=spec.name,
            environment=dict(spec.env),
            ports={f"{p.container}/{p.protocol}": p.host for p in spec.ports},
            labels={CREATED_LABEL: created_by[:64]},
            **_HARDENING,
        )
        try:
            container.start()
        except DockerException as error:
            # The container exists from here on and it stays: removing it would
            # delete the evidence of why it did not come up, and it shows in the
            # list as `exited`, where the start button can try again. The
            # message says so, because the audit log row is written from it.
            raise DriverUnavailable(
                f"{spec.name} was created but did not start: {error}"
            ) from error
        return container.id


def _apply(container_id: str, action: Action) -> None:
    """The write half. Three branches, written out.

    Deliberately not `getattr(container, action)()`: that would let a request
    field pick a method on a Docker object, and the list of methods there is a
    lot longer than three. The `else` is unreachable through the API — pydantic
    rejects anything else at the boundary — and stays as the guard for a future
    caller that skips it.
    """
    with _lock:
        container = _connect().containers.get(container_id)
        if action == "start":
            container.start()
        elif action == "stop":
            container.stop(timeout=_stop_timeout())
        elif action == "restart":
            container.restart(timeout=_stop_timeout())
        else:
            raise ValueError(f"Unknown action: {action!r}")


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
        """Start, stop or restart one container.

        Whether this container may be controlled at all is not decided here —
        `service.container_action` checks the allow-list first. The driver is
        the last layer and does what it is told, which is why nothing above it
        may hand it an unchecked id.
        """
        try:
            await asyncio.to_thread(_apply, target_id, action)
        except NotFound as error:
            raise UnknownTarget(target_id) from error
        except DockerException as error:
            log.warning("Docker action %s on %s failed: %s", action, target_id, error)
            raise DriverUnavailable(str(error)) from error

    async def create(self, spec: CreateIn, created_by: str) -> str:
        """Create and start one container — returns its short id.

        Not part of the `Driver` protocol. Creating is Docker shaped: a Proxmox
        VM and a systemd unit are not created from an image and a port map, and
        pretending they share one signature would only make the next driver
        lie about it.

        Whether this name and this image are allowed at all is decided in
        `service.container_create`. The driver is the last layer and does what
        it is told, so nothing above it may hand it an unchecked specification.
        """
        try:
            container_id = await asyncio.to_thread(_create, spec, created_by)
        except ImageNotFound as error:
            raise TargetConflict(
                f"Image {spec.image} is not on the host. Pull it there first."
            ) from error
        except APIError as error:
            # 409 is the name already being taken — the one case the caller can
            # do something about, so it does not get flattened into a 503.
            if error.status_code == 409:
                raise TargetConflict(
                    f"A container named {spec.name} already exists."
                ) from error
            log.warning("Docker create %r failed: %s", spec.name, error)
            raise DriverUnavailable(str(error)) from error
        except DockerException as error:
            log.warning("Docker create %r failed: %s", spec.name, error)
            raise DriverUnavailable(str(error)) from error
        return container_id[:12]

    async def state_of(self, container_id: str) -> State:
        """State read back after an action — what happened, not what was asked.

        A container that exits a second after `start` reads `exited` here, and
        the UI shows that instead of an optimistic green dot.
        """
        try:
            attrs = await asyncio.to_thread(_read_attrs, container_id)
        except NotFound as error:
            raise UnknownTarget(container_id) from error
        except DockerException as error:
            raise DriverUnavailable(str(error)) from error
        return _state(attrs.get("State") or {})

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
