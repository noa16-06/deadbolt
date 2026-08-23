"""Wire format of the server manager.

These names are the contract the frontend was built against
(`frontend/src/features/servers/serversApi.js`). Anything renamed here has to
be renamed there in the same commit — the two halves are one interface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Fixed list, never a passed-through string. The frontend has the same list in
# `serversApi.js` — but a client is not a security boundary, so the backend
# enforces it independently.
Action = Literal["start", "stop", "restart"]

# The five states the UI knows (`STATES` in `serversApi.js`).
State = Literal["running", "paused", "exited", "restarting", "unhealthy"]


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
