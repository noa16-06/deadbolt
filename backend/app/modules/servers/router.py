"""HTTP endpoints of the server manager.

Reading: the container list, host metrics, container logs. Writing: an action
against one existing container, and creating a new one.

Every endpoint sits behind `CurrentUser` — the reading ones too. Which
containers exist and what the host is called is reconnaissance, not public
information.

The endpoints stay thin. Whether an action is allowed at all is decided in
`service`, because a router is one of several possible callers and the answer
must not depend on which one it was.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from fastapi.responses import PlainTextResponse

from app.deps import CurrentUser, DbSession, client_ip
from app.modules.servers import service
from app.modules.servers.drivers.base import (
    DriverUnavailable,
    TargetConflict,
    UnknownTarget,
)
from app.modules.servers.schemas import (
    ActionIn,
    ActionOut,
    ContainerOut,
    CreateIn,
    CreateOut,
    MetricsOut,
)

router = APIRouter(prefix="/api/servers", tags=["servers"])

# The id ends up in a driver call, so it is constrained at the boundary: hex,
# nothing else. On top of that `service` checks it against existing containers.
ContainerId = Path(pattern=r"^[0-9a-f]{12,64}$", description="Docker container id")

# Bounded on purpose: without a limit, "give me every line" is a memory problem
# with a friendly name.
LinesParam = Query(default=200, ge=1, le=2000, description="Number of log lines")


def _unavailable(error: DriverUnavailable) -> HTTPException:
    """503, not 500: the target system is down, the dashboard is not broken."""
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error))


@router.get("/containers", response_model=list[ContainerOut])
async def containers(user: CurrentUser):
    """All containers, running or not. CPU and RAM come from the sampler."""
    try:
        return await service.container_list()
    except DriverUnavailable as error:
        raise _unavailable(error) from error


@router.post(
    "/containers", response_model=CreateOut, status_code=status.HTTP_201_CREATED
)
async def create_container(
    data: CreateIn,
    user: CurrentUser,
    session: DbSession,
    request: Request,
):
    """Create one container from an allowed image, under an allowed name.

    The whole specification is in the body here — there is no existing target
    to address — which is exactly why `CreateIn` is as narrow as it is: name,
    image, ports, environment, and nothing that could turn a container into a
    way onto the host. `service.container_create` decides whether this name and
    this image are permitted at all.

    403 is one of three refusals (name, image, missing second factor), 409 is
    a name that is taken or an image that is not on the host, 503 is a daemon
    that does not answer. All of them, and the success, are in the audit log.
    """
    try:
        return await service.container_create(
            session, user, client_ip(request), data
        )
    except service.ControlDenied as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
    except TargetConflict as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except DriverUnavailable as error:
        raise _unavailable(error) from error


@router.get("/metrics", response_model=MetricsOut)
async def metrics(user: CurrentUser):
    """Host metrics. Independent of Docker — works without the daemon too."""
    return await service.metrics()


@router.get("/containers/{container_id}/logs", response_class=PlainTextResponse)
async def logs(
    user: CurrentUser, container_id: str = ContainerId, lines: int = LinesParam
):
    try:
        text = await service.logs(container_id, lines)
    except DriverUnavailable as error:
        raise _unavailable(error) from error
    if text is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Container not found")
    return text


@router.post("/containers/{container_id}/action", response_model=ActionOut)
async def action(
    data: ActionIn,
    user: CurrentUser,
    session: DbSession,
    request: Request,
    container_id: str = ContainerId,
):
    """Start, stop or restart one container.

    Two things this endpoint deliberately does not do: it does not take the
    target from the body, and it does not take the action as a free string.
    The id is a path parameter constrained to hex and checked against the
    containers that exist; the action is a Literal, so anything outside
    `start` / `stop` / `restart` is a 422 before any module code runs.

    403 means one of two things — the container is not on the allow-list, or
    the account has no second factor. Both are logged with the reason; the
    caller gets the short version.
    """
    try:
        return await service.container_action(
            session, user, client_ip(request), container_id, data.action
        )
    except service.ControlDenied as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
    except UnknownTarget as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Container not found") from error
    except DriverUnavailable as error:
        raise _unavailable(error) from error
