"""Host metrics: CPU, RAM, disks, network via psutil — GPU via nvidia-smi.

nvidia-smi is the one external process in this module. It is called with a
fixed argument list, without a shell and without a single value from a request.
That is the difference between "runs a program" and "an injection point".
"""

from __future__ import annotations

import logging
import platform
import socket
import subprocess
import time
from dataclasses import dataclass

import psutil

from app.config import settings
from app.modules.servers.schemas import Cpu, Disk, Gpu, Power, Usage

log = logging.getLogger(__name__)

MB = 1024 * 1024
GB = 1024 * 1024 * 1024

# Sensor labels the usual CPU temperatures hide behind — Intel, AMD, Raspberry.
_TEMP_SOURCES = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz")

_NVIDIA_FIELDS = (
    "name,utilization.gpu,memory.used,memory.total,"
    "temperature.gpu,power.draw,power.limit"
)

# Set once nvidia-smi turns out not to exist: without a card that never
# changes, and spawning a process every ten seconds for a guaranteed miss is
# waste.
_no_gpu = False


@dataclass
class NetCounter:
    """Absolute counters — a throughput only exists between two of these."""

    rx: int
    tx: int
    at: float


def cpu_model() -> str:
    """The marketing name, not `x86_64`.

    psutil does not provide it, and every platform hides it somewhere else.
    """
    try:
        if platform.system() == "Linux":
            with open("/proc/cpuinfo", encoding="utf-8") as file:
                for line in file:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        elif platform.system() == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return platform.processor() or platform.machine() or "unknown"


def cpu_temperature() -> int | None:
    """None instead of a guess — macOS and many VMs have no sensor."""
    read = getattr(psutil, "sensors_temperatures", None)
    if read is None:
        return None
    try:
        sensors = read()
    except (OSError, AttributeError):
        return None
    for source in _TEMP_SOURCES:
        values = [e.current for e in sensors.get(source, []) if e.current]
        if values:
            return round(max(values))
    return None


def disks() -> list[Disk]:
    """Configured mount points, otherwise everything physically mounted."""
    paths = settings.disk_list
    if not paths:
        try:
            paths = [p.mountpoint for p in psutil.disk_partitions(all=False)]
        except OSError:
            paths = ["/"]

    result: list[Disk] = []
    for path in paths:
        try:
            usage = psutil.disk_usage(path)
        except OSError:
            # A mount point that vanished is not worth an error — it is gone.
            continue
        if usage.total < GB:
            # Pseudo mounts (macOS xarts, iSCPreboot, and the like) round to
            # 0 GB and would render as empty bars nobody can read anything off.
            continue
        result.append(
            Disk(path=path, used=round(usage.used / GB), total=round(usage.total / GB))
        )
    return result


def gpu(history: list[float]) -> Gpu | None:
    """Reads the first NVIDIA card, or None if there is none."""
    global _no_gpu
    if _no_gpu:
        return None
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={_NVIDIA_FIELDS}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        # No driver installed. Do not try again.
        _no_gpu = True
        return None
    except (OSError, subprocess.SubprocessError) as error:
        log.debug("nvidia-smi failed: %s", error)
        return None

    lines = result.stdout.strip().splitlines()
    if result.returncode != 0 or not lines:
        return None

    fields = [f.strip() for f in lines[0].split(",")]
    if len(fields) < 7:
        return None

    def number(value: str, default: float = 0.0) -> float:
        try:
            return float(value)
        except ValueError:
            # nvidia-smi writes "[N/A]" for values a card does not report.
            return default

    return Gpu(
        model=fields[0],
        usage=round(number(fields[1]), 1),
        memory=Usage(used=round(number(fields[2])), total=round(number(fields[3]))),
        temperature=round(number(fields[4])) or None,
        power=Power(watts=round(number(fields[5])), limit=round(number(fields[6]))),
        history=history,
    )


def cpu(history: list[float]) -> tuple[Cpu, float]:
    """CPU load since the previous call, plus the total for the history.

    `interval=None` measures against the last call instead of blocking for a
    second. That works because only the sampler calls it, at a fixed rhythm.
    """
    cores = [round(c, 1) for c in psutil.cpu_percent(interval=None, percpu=True)]
    total = round(sum(cores) / len(cores), 1) if cores else 0.0
    return (
        Cpu(
            model=cpu_model(),
            total=total,
            cores=cores,
            temperature=cpu_temperature(),
            history=history,
        ),
        total,
    )


def net(previous: NetCounter | None) -> tuple[float, float, NetCounter]:
    """Throughput in Mbit/s from the difference between two counter readings."""
    counter = psutil.net_io_counters()
    now = NetCounter(counter.bytes_recv, counter.bytes_sent, time.monotonic())
    if previous is None:
        return 0.0, 0.0, now

    seconds = now.at - previous.at
    if seconds <= 0:
        return 0.0, 0.0, now

    def mbit(new: int, old: int) -> float:
        # A counter reset (reboot, interface gone) would give a negative value.
        return round(max(0, new - old) * 8 / 1_000_000 / seconds, 1)

    return mbit(now.rx, previous.rx), mbit(now.tx, previous.tx), now


def memory() -> tuple[Usage, Usage]:
    ram = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return (
        Usage(used=round(ram.used / MB), total=round(ram.total / MB)),
        Usage(used=round(swap.used / MB), total=round(swap.total / MB)),
    )


def host_name() -> str:
    return socket.gethostname()


def uptime_seconds() -> int:
    return int(time.time() - psutil.boot_time())
