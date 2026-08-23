"""Background sampler: keeps metrics and container stats current.

Two things do not belong in a request:

* `psutil.cpu_percent` needs two readings for a load value — measuring it per
  request would either block for a second or report nonsense.
* Docker computes a CPU delta per container and takes about a second for it.
  For seven containers that is seven seconds a caller would be waiting.

So a single task samples at a fixed rhythm and the endpoints answer from the
cache. That also makes the sampler the only writer — the sparkline history
stays evenly spaced no matter how often someone opens the page.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque

from app.config import settings
from app.modules.servers.drivers import host
from app.modules.servers.drivers.base import DriverUnavailable
from app.modules.servers.drivers.docker import DockerDriver
from app.modules.servers.schemas import Memory, MetricsOut, Net

log = logging.getLogger(__name__)

_length = settings.servers_history_length
_cpu_history: deque[float] = deque(maxlen=_length)
_gpu_history: deque[float] = deque(maxlen=_length)
_net_counter: host.NetCounter | None = None

_metrics: MetricsOut | None = None
_container_stats: dict[str, tuple[float, Memory]] = {}

_driver = DockerDriver()
_task: asyncio.Task | None = None
# Docker being down is normal; it should not fill the log every ten seconds.
_docker_reported = False


def latest_metrics() -> MetricsOut | None:
    """Most recent snapshot, or None before the first sample."""
    return _metrics


def container_stats(container_id: str) -> tuple[float, Memory] | None:
    """CPU and RAM of a container — None if it is not running."""
    return _container_stats.get(container_id)


async def collect_metrics() -> MetricsOut:
    """One host snapshot. Blocking parts run in a thread."""
    global _net_counter

    def _read():
        cpu, total = host.cpu([])
        gpu = host.gpu([])
        ram, swap = host.memory()
        rx, tx, counter = host.net(_net_counter)
        return cpu, total, gpu, ram, swap, rx, tx, counter, host.disks()

    cpu, total, gpu, ram, swap, rx, tx, counter, disks = await asyncio.to_thread(_read)
    _net_counter = counter

    # History first, then hand it over — the current value belongs in the line.
    _cpu_history.append(total)
    cpu.history = list(_cpu_history)
    if gpu is not None:
        _gpu_history.append(gpu.usage)
        gpu.history = list(_gpu_history)

    return MetricsOut(
        host=host.host_name(),
        uptime_seconds=host.uptime_seconds(),
        cpu=cpu,
        gpu=gpu,
        ram=ram,
        swap=swap,
        disks=disks,
        net=Net(rx_mbit=rx, tx_mbit=tx),
    )


async def _collect_containers() -> None:
    """Stats of all running containers into the cache."""
    global _docker_reported
    try:
        ids = await _driver.running_ids()
    except DriverUnavailable as error:
        if not _docker_reported:
            log.warning("Sampler running without Docker: %s", error)
            _docker_reported = True
        _container_stats.clear()
        return
    _docker_reported = False

    fresh: dict[str, tuple[float, Memory]] = {}
    for container_id in ids:
        values = await _driver.stats(container_id)
        if values is not None:
            fresh[container_id] = values

    # Replace instead of update: a stopped container must not keep showing its
    # last CPU value forever.
    _container_stats.clear()
    _container_stats.update(fresh)


async def _loop() -> None:
    global _metrics
    while True:
        try:
            _metrics = await collect_metrics()
            await _collect_containers()
        except asyncio.CancelledError:
            raise
        except Exception:
            # One bad sample must not end the loop — otherwise a single hiccup
            # freezes the display until the next restart.
            log.exception("Sample failed")
        await asyncio.sleep(settings.servers_sample_seconds)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(), name="servers-sampler")


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
