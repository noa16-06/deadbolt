"""Server manager logic. Knows no HTTP.

Reading is list, metrics and logs. Writing is the three container actions —
`start`, `stop`, `restart` — plus creating a container, and everything guarding
them sits here rather than in the router: the allow-lists, the second-factor
requirement and the audit log. A router is one of several possible callers, and
none of those three may depend on which one it was.

Creating is the widest of the four and therefore has one gate more than the
others: the name has to be on the control list AND the image on the image list.
The reason the two are separate is that they answer different questions — which
container this dashboard may touch, and which code it may start on the host.

The order this arrived in was not arbitrary. A restart button reachable from
the internet behind a single password is the case `docs/security.md` argues
against, so the write half waited for TOTP and the login rate limit.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.auth.models import User
from app.modules.servers.drivers.base import (
    DriverUnavailable,
    TargetConflict,
    UnknownTarget,
)
from app.modules.servers.drivers.docker import DockerDriver
from app.modules.servers.models import ControlLog
from app.modules.servers.schemas import (
    Action,
    ActionOut,
    ContainerOut,
    CreateIn,
    CreateOut,
    LoggedAction,
    MetricsOut,
    State,
)

log = logging.getLogger(__name__)

# Docker ids are hex, short or long. Anything else never reaches a driver.
_ID_PATTERN = re.compile(r"^[0-9a-f]{12,64}$")

# What the container should be in once the action worked — the fallback for the
# rare case that Docker stops answering between the action and the read-back.
_EXPECTED: dict[Action, State] = {
    "start": "running",
    "restart": "running",
    "stop": "exited",
}

_docker = DockerDriver()


class ControlDenied(PermissionError):
    """Allowed to look, not allowed to touch — a 403.

    Two separate reasons end up here: the container is not on the allow-list,
    or the account has no second factor. Both are "you may see this and you may
    not change it", so both read the same to the caller.
    """


def id_looks_valid(container_id: str) -> bool:
    return bool(_ID_PATTERN.match(container_id))


def may_be_controlled(name: str) -> bool:
    """The allow-list for write actions.

    Fails closed: an empty configuration allows nothing. Reading is
    deliberately unaffected — seeing a container is harmless, restarting it
    is not.

    Creating is checked against this same list, before the container exists.
    A name that may be created but not stopped would be a container the
    dashboard can switch on and never off again.
    """
    return name in settings.control_allowlist


def image_allowed(image: str) -> bool:
    """The allow-list for creating — a second list, because it answers a
    different question.

    The control list says which NAMES this dashboard may touch. This one says
    which CODE it may start on the host, and that is the wider power of the
    two: a container is only ever as trustworthy as its image. Exact match
    including the tag, and empty allows nothing.
    """
    return image in settings.image_allowlist


def _may_write(user: User) -> bool:
    """A password alone does not get to restart containers.

    The whole argument in `docs/security.md` is that a login bypass here is a
    host takeover. An account without a second factor is one guessed password
    away from that, so it stays read-only. `AUTH_DISABLED` is the exception,
    and `config._check_dev_switches` refuses to combine that flag with anything
    reachable from outside.
    """
    return settings.auth_disabled or user.totp_enabled


async def container_list() -> list[ContainerOut]:
    """Every container, with the allow-list applied as a flag.

    The list itself is unfiltered on purpose — hiding a container that may not
    be restarted would make the overview lie about what runs on the host. Only
    `controllable` differs, and the UI greys out the buttons instead of
    offering a click that ends in a 403.
    """
    containers = await _docker.status()
    for container in containers:
        container.controllable = may_be_controlled(container.name)
    return containers


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


# ------------------------------------------------------------------- writing
async def _record(
    session: AsyncSession,
    user: User,
    ip: str,
    container_id: str,
    container_name: str,
    action: LoggedAction,
    *,
    ok: bool,
    detail: str | None = None,
) -> None:
    """Write one row of the audit log — refusals included.

    Committed separately from anything else, because the record has to survive
    the request that failed. The refused attempts are the interesting half:
    nobody notices "tried to restart something not on the list" if only
    successes are written down.
    """
    session.add(
        ControlLog(
            user_id=user.id,
            username=user.username,
            ip=ip,
            container_id=container_id[:64],
            container_name=container_name[:255],
            action=action,
            ok=ok,
            detail=detail[:255] if detail else None,
        )
    )
    await session.commit()
    log.info(
        "control action=%s target=%r id=%s user=%r ip=%s ok=%s%s",
        action,
        container_name,
        container_id,
        user.username,
        ip,
        ok,
        f" detail={detail!r}" if detail else "",
    )


async def container_action(
    session: AsyncSession,
    user: User,
    ip: str,
    container_id: str,
    action: Action,
) -> ActionOut:
    """Run one action against one container — after four checks, in this order.

    1. Does the id look like a Docker id at all.
    2. Does a container with that id exist right now.
    3. Is its NAME on the allow-list — the name, not the id: an id changes
       whenever the container is recreated, and a list that has to be edited
       after every `compose up` is a list nobody keeps correct.
    4. Does the account have a second factor.

    Every outcome, including all four refusals, ends up in the audit log.

    `action` is a Literal and comes out of pydantic already validated; it is
    never interpolated into anything. Raises `ControlDenied` (403),
    `UnknownTarget` (404) or `DriverUnavailable` (503).
    """
    if not id_looks_valid(container_id):
        # The router constrains the path too. This is the second, independent
        # check — the service is also called from tests and scripts.
        await _record(
            session, user, ip, container_id, "", action, ok=False, detail="malformed id"
        )
        raise UnknownTarget(container_id)

    containers = {c.id: c for c in await _docker.status()}
    target = containers.get(container_id)
    if target is None:
        await _record(
            session, user, ip, container_id, "", action, ok=False, detail="unknown container"
        )
        raise UnknownTarget(container_id)

    if not may_be_controlled(target.name):
        detail = "not on SERVERS_CONTROL_ALLOWLIST"
        await _record(
            session, user, ip, container_id, target.name, action, ok=False, detail=detail
        )
        raise ControlDenied(f"{target.name} may not be controlled")

    if not _may_write(user):
        detail = "no second factor"
        await _record(
            session, user, ip, container_id, target.name, action, ok=False, detail=detail
        )
        raise ControlDenied("Container control needs a second factor. Enrol TOTP first.")

    try:
        await _docker.action(container_id, action)
    except (DriverUnavailable, UnknownTarget) as error:
        await _record(
            session, user, ip, container_id, target.name, action, ok=False, detail=str(error)
        )
        raise

    # The action worked. If Docker drops away in the split second afterwards
    # that does not undo it, so the answer is still a success — with the state
    # the action was aiming for and a note in the log that it was not verified.
    try:
        state = await _docker.state_of(container_id)
        note = None
    except (DriverUnavailable, UnknownTarget) as error:
        state = _EXPECTED[action]
        note = f"done, state not read back: {error}"

    await _record(
        session, user, ip, container_id, target.name, action, ok=True, detail=note
    )
    return ActionOut(id=container_id, action=action, state=state)


async def container_create(
    session: AsyncSession,
    user: User,
    ip: str,
    spec: CreateIn,
) -> CreateOut:
    """Create and start one container — after four checks, in this order.

    1. Is the NAME on `SERVERS_CONTROL_ALLOWLIST`. Checked first because it is
       the cheapest and the most likely refusal, and because a container that
       may be created but not stopped is worse than one that was never created.
    2. Is the IMAGE on `SERVERS_IMAGE_ALLOWLIST`, tag included.
    3. Does the account have a second factor.
    4. Is the name still free right now.

    Shape is not checked here — `CreateIn` did that at the boundary, and
    anything that got this far is a valid name, a tagged image, host ports at
    or above 1024 and a bounded environment. What is checked here is
    permission, which is a question about the configuration rather than about
    the request.

    Every outcome ends up in the audit log, refusals included, under the action
    `create`. The row carries the requested name from the start; the id is only
    known once Docker has answered, so a refused attempt logs an empty one.

    Raises `ControlDenied` (403), `TargetConflict` (409) or `DriverUnavailable`
    (503).
    """

    async def record(ok: bool, detail: str | None, container_id: str = "") -> None:
        await _record(
            session, user, ip, container_id, spec.name, "create", ok=ok, detail=detail
        )

    if not may_be_controlled(spec.name):
        detail = "not on SERVERS_CONTROL_ALLOWLIST"
        await record(False, detail)
        raise ControlDenied(f"{spec.name} may not be created — {detail}")

    if not image_allowed(spec.image):
        # The image is in the message on purpose: the answer to this refusal is
        # a line in .env, and nobody can add it without knowing which line.
        detail = f"{spec.image} not on SERVERS_IMAGE_ALLOWLIST"
        await record(False, detail)
        raise ControlDenied(detail)

    if not _may_write(user):
        detail = "no second factor"
        await record(False, detail)
        raise ControlDenied("Creating a container needs a second factor. Enrol TOTP first.")

    # Docker refuses a duplicate name itself, with a 409 the driver passes on.
    # Asking first is still worth it: it keeps the audit log honest about why
    # nothing was created, and it does not depend on parsing a daemon error.
    taken = {c.name for c in await _docker.status()}
    if spec.name in taken:
        detail = "name already taken"
        await record(False, detail)
        raise TargetConflict(f"A container named {spec.name} already exists.")

    try:
        container_id = await _docker.create(spec, user.username)
    except (TargetConflict, DriverUnavailable) as error:
        await record(False, str(error))
        raise

    # Same rule as an action: the state is read back rather than assumed. An
    # image that exits immediately — a wrong environment variable is enough —
    # must not report `running` just because `start` returned.
    try:
        state = await _docker.state_of(container_id)
        note = None
    except (DriverUnavailable, UnknownTarget) as error:
        state = "running"
        note = f"created, state not read back: {error}"

    await record(True, note, container_id)
    return CreateOut(id=container_id, name=spec.name, image=spec.image, state=state)
