"""Tests for the Docker driver's parsing — the part most likely to be wrong.

Everything here is a pure function on payloads shaped the way the Docker Engine
API actually sends them. No daemon required, so unlike the planner tests these
really run.

What is NOT covered: the live path against a real daemon. That needs Docker.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.modules.servers.drivers.docker import (
    _cpu_percent,
    _memory,
    _ports,
    _since,
    _state,
)

MB = 1024 * 1024


# ------------------------------------------------------------------ state
def test_unhealthy_beats_running():
    """A running but unhealthy container is a problem, not a success."""
    state = {"Status": "running", "Health": {"Status": "unhealthy"}}
    assert _state(state) == "unhealthy"


def test_healthy_running_stays_running():
    state = {"Status": "running", "Health": {"Status": "healthy"}}
    assert _state(state) == "running"


def test_container_without_healthcheck():
    """Most containers have no health check at all — that is not a problem."""
    assert _state({"Status": "running"}) == "running"


def test_unknown_docker_state_counts_as_stopped():
    """Docker knows more states than the UI. Anything unknown must not crash."""
    assert _state({"Status": "dead"}) == "exited"
    assert _state({"Status": "something-new"}) == "exited"


# ------------------------------------------------------------------ since
def test_nanoseconds_are_parsed():
    """Docker sends nanoseconds; fromisoformat handles at most microseconds."""
    state = {"Status": "running", "StartedAt": "2026-08-23T01:14:00.123456789Z"}
    since = _since(state, None)
    assert since == datetime(2026, 8, 23, 1, 14, 0, 123456, tzinfo=timezone.utc)


def test_stopped_container_reports_when_it_stopped():
    """Otherwise the list claims a container that exited an hour ago has been
    in that state since it was first started, weeks back."""
    state = {
        "Status": "exited",
        "StartedAt": "2026-07-01T10:00:00Z",
        "FinishedAt": "2026-08-23T09:00:00Z",
    }
    assert _since(state, None).month == 8


def test_never_started_container_falls_back_to_created():
    """Docker writes 0001-01-01 for a container that never ran."""
    state = {
        "Status": "created",
        "StartedAt": "0001-01-01T00:00:00Z",
        "FinishedAt": "0001-01-01T00:00:00Z",
    }
    assert _since(state, "2026-08-23T08:00:00Z").year == 2026


def test_unparseable_timestamps_do_not_crash():
    assert _since({"Status": "running", "StartedAt": "kaputt"}, None).year >= 2026


# ------------------------------------------------------------------ ports
def test_dual_stack_port_is_listed_once():
    """Docker lists a port bound to IPv4 and IPv6 twice — that is one port."""
    network = {
        "Ports": {
            "8000/tcp": [
                {"HostIp": "0.0.0.0", "HostPort": "8000"},
                {"HostIp": "::", "HostPort": "8000"},
            ]
        }
    }
    ports = _ports(network)
    assert len(ports) == 1
    assert (ports[0].host, ports[0].container, ports[0].protocol) == (8000, 8000, "tcp")


def test_unpublished_ports_are_skipped():
    """An exposed but unpublished port has no host binding."""
    assert _ports({"Ports": {"5432/tcp": None}}) == []


def test_ports_are_sorted_and_keep_protocol():
    network = {
        "Ports": {
            "443/tcp": [{"HostPort": "443"}],
            "53/udp": [{"HostPort": "53"}],
        }
    }
    ports = _ports(network)
    assert [p.host for p in ports] == [53, 443]
    assert ports[0].protocol == "udp"


def test_container_without_network_section():
    assert _ports({}) == []


# ------------------------------------------------------------------ cpu
def test_cpu_percent_matches_docker_stats():
    """Half of two cores busy -> 100 %, same as `docker stats` reports."""
    stats = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 2_000_000_000},
            "system_cpu_usage": 20_000_000_000,
            "online_cpus": 2,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 1_000_000_000},
            "system_cpu_usage": 18_000_000_000,
        },
    }
    assert _cpu_percent(stats) == 100.0


def test_first_sample_has_no_delta():
    """precpu is empty on the very first reading — 0.0, not a division error."""
    stats = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 1_000_000},
            "system_cpu_usage": 1_000_000,
        },
        "precpu_stats": {},
    }
    assert _cpu_percent(stats) == 0.0


def test_cpu_percent_survives_missing_fields():
    assert _cpu_percent({}) == 0.0


# ------------------------------------------------------------------ memory
def test_page_cache_is_not_counted_as_used():
    """Raw `usage` includes the cache and makes nearly every container look
    full. Docker itself subtracts inactive_file, so we do too."""
    stats = {
        "memory_stats": {
            "usage": 500 * MB,
            "limit": 1024 * MB,
            "stats": {"inactive_file": 200 * MB},
        }
    }
    memory = _memory(stats)
    assert (memory.used, memory.limit) == (300, 1024)


def test_memory_never_goes_negative():
    """Docker has been seen reporting inactive_file larger than usage."""
    stats = {
        "memory_stats": {
            "usage": 10 * MB,
            "limit": 1024 * MB,
            "stats": {"inactive_file": 50 * MB},
        }
    }
    assert _memory(stats).used == 0


def test_container_without_memory_stats():
    assert _memory({}).used == 0
