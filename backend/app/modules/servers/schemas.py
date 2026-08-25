"""Wire format of the server manager.

These names are the contract the frontend was built against
(`frontend/src/features/servers/serversApi.js`). Anything renamed here has to
be renamed there in the same commit — the two halves are one interface.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Fixed list, never a passed-through string. The frontend has the same list in
# `serversApi.js` — but a client is not a security boundary, so the backend
# enforces it independently.
Action = Literal["start", "stop", "restart"]

# The five states the UI knows (`STATES` in `serversApi.js`).
State = Literal["running", "paused", "exited", "restarting", "unhealthy"]

# What the audit log records. `create` is a write action like the other three,
# but it is not one of them: it takes a specification instead of a container
# id, so it stays out of `Action` — nothing that dispatches on `Action` must
# suddenly get a fourth branch — and only the log sees all four.
LoggedAction = Literal["start", "stop", "restart", "create"]

# A container name as Docker itself defines it. The name is the value the
# allow-list is checked against, so its shape is pinned at the boundary rather
# than trusted: no slashes, no spaces, nothing path- or shell-shaped.
NAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,62}$"

# `repository:tag`, tag required. A registry with a port (`registry:5000/x:1`)
# still fits, because the body may contain colons and only the last one is read
# as the tag separator. This is the coarse guard — the real gate is the exact
# match against `SERVERS_IMAGE_ALLOWLIST` in `service.image_allowed`.
IMAGE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._\-/:]{0,127}:[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$"

# Environment variable names. Docker would take almost anything here; this is
# the conventional shape, and an unbounded name is one more thing an image
# never asked for.
ENV_NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"


class Base(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


# ---------------------------------------------------------------- containers
class Port(Base):
    host: int
    container: int
    protocol: str


class Memory(Base):
    """Container memory in MB — measured against its limit."""

    used: int
    limit: int


class ContainerOut(Base):
    id: str
    name: str
    image: str
    state: State
    since: datetime
    ports: list[Port]
    cpu: float
    ram: Memory
    stack: str
    # Whether this container may be started, stopped or restarted at all —
    # `SERVERS_CONTROL_ALLOWLIST` decides, and it is empty by default. Reading
    # is unaffected, so the list shows everything and the UI can grey out the
    # buttons instead of offering a click that ends in a 403.
    controllable: bool = False


class ActionIn(Base):
    """Body of the action endpoint.

    `action` is the Literal above, so anything outside the list is a 422 before
    a single line of module code runs. The target is NOT in the body: it is the
    id in the path, checked against the containers that actually exist.
    """

    action: Action


class PortIn(Base):
    """One published port of a container that is being created.

    The host port starts at 1024: everything below needs root to bind, and the
    containers that hold 80 and 443 on this host (Caddy) are not created from
    here. That keeps the dashboard from taking the reverse proxy's ports away
    from it.
    """

    host: int = Field(ge=1024, le=65535)
    container: int = Field(ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"


class CreateIn(Base):
    """Body of the create endpoint — a specification, not a command line.

    Four fields, and every one of them is checked before anything reaches
    Docker: the NAME against `SERVERS_CONTROL_ALLOWLIST` (a container that may
    be created but not stopped would be a container nobody can switch off
    again), the IMAGE against `SERVERS_IMAGE_ALLOWLIST`, the ports and the
    environment against the shapes above.

    What is deliberately NOT in here: volumes, `privileged`, capabilities,
    network mode, devices, user, entrypoint, command. Each of those turns
    "create a container" into "run anything as root on the host", and none of
    them gets more careful just because a field was added for it. The driver
    pins them to fixed, safe values instead.
    """

    name: str = Field(pattern=NAME_PATTERN)
    image: str = Field(pattern=IMAGE_PATTERN)
    ports: list[PortIn] = Field(default_factory=list, max_length=10)
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator("env")
    @classmethod
    def _check_env(cls, value: dict[str, str]) -> dict[str, str]:
        """Names to the pattern, values bounded, the whole map bounded.

        A dict field has no `max_length` that pydantic enforces per key, so the
        limits live here — an unbounded environment is a memory problem with a
        friendly name, the same way "every log line" was.
        """
        if len(value) > 32:
            raise ValueError("at most 32 environment variables")
        for name, content in value.items():
            if not re.match(ENV_NAME_PATTERN, name):
                raise ValueError(f"invalid environment variable name: {name!r}")
            if len(content) > 512:
                raise ValueError(f"value of {name} is longer than 512 characters")
        return value

    @field_validator("ports")
    @classmethod
    def _check_ports(cls, value: list[PortIn]) -> list[PortIn]:
        """One host port can only be published once — Docker would refuse the
        whole create, and a 422 says which port before anything is attempted."""
        seen = {p.host for p in value}
        if len(seen) != len(value):
            raise ValueError("a host port is published twice")
        return value


class CreateOut(Base):
    """The container that now exists — with the state read back from Docker.

    Same rule as `ActionOut`: an image that exits immediately after `start`
    reads `exited` here rather than the `running` that was intended.
    """

    id: str
    name: str
    image: str
    state: State


class ActionOut(Base):
    """What the action did — including the state read back afterwards.

    The state is read from Docker rather than derived from the action, so the
    UI shows what happened instead of what was supposed to happen. A container
    that dies one second after `start` reads `exited` here.
    """

    id: str
    action: Action
    state: State


# ---------------------------------------------------------------- metrics
class Usage(Base):
    """Used against a total — MB for memory, GB for disks."""

    used: int
    total: int


class Power(Base):
    watts: int
    limit: int


class Cpu(Base):
    model: str
    total: float
    cores: list[float]
    # None when the host exposes no sensor — the UI shows a dash rather than
    # a made-up number.
    temperature: int | None
    history: list[float]


class Gpu(Base):
    model: str
    usage: float
    memory: Usage
    temperature: int | None
    power: Power
    history: list[float]


class Disk(Base):
    path: str
    used: int
    total: int


class Net(Base):
    rx_mbit: float = Field(serialization_alias="rxMbit")
    tx_mbit: float = Field(serialization_alias="txMbit")


class MetricsOut(Base):
    host: str
    uptime_seconds: int = Field(serialization_alias="uptimeSeconds")
    cpu: Cpu
    # None on a host without an NVIDIA card. The UI renders an empty card.
    gpu: Gpu | None
    ram: Usage
    swap: Usage
    disks: list[Disk]
    net: Net
