"""HTTP endpoints of the server manager — reading only.

Every endpoint sits behind `CurrentUser`. There is no public read path here:
which containers exist and what the host is called is reconnaissance, not
public information.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Query, status
from fastapi.responses import PlainTextResponse

from app.deps import CurrentUser
from app.modules.servers import service
from app.modules.servers.drivers.base import DriverUnavailable
from app.modules.servers.schemas import ContainerOut, MetricsOut

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
