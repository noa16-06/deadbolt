"""Container control: who is allowed to press start or create, and what gets
written down.

The Docker daemon is replaced by a fake driver here. That is not a shortcut
around the interesting part — the interesting part is not whether docker-py can
restart a container, it is the gates in front of it: a valid id, a container
that exists, the allow-list, and a second factor. For creating there is one
gate more, because a create names an image and an image is code that runs on
the host. Every one of those has to hold with a fake daemon just as much as
with a real one.

`sampler.py` and the live path against a real Docker are still uncovered; they
need a daemon.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pyotp
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import settings
from app.modules.auth import service as auth_service
from app.modules.servers import service
from app.modules.servers.drivers.base import (
    DriverUnavailable,
    TargetConflict,
    UnknownTarget,
)
from app.modules.servers.models import ControlLog
from app.modules.servers.schemas import ContainerOut, CreateIn, Memory

pytestmark = pytest.mark.asyncio

PASSWORD = "correct-horse-battery"

# Two containers: one the configuration allows, one it does not.
ALLOWED_ID = "aaaaaaaaaaaa"
FORBIDDEN_ID = "bbbbbbbbbbbb"
# The id the fake daemon hands back for a container it just created.
NEW_ID = "dddddddddddd"


def container(container_id: str, name: str, state: str = "running") -> ContainerOut:
    return ContainerOut(
        id=container_id,
        name=name,
        image="nginx:1.27",
        state=state,
        since=datetime.now(timezone.utc),
        ports=[],
        cpu=0.0,
        ram=Memory(used=0, limit=0),
        stack="homelab",
    )


class FakeDocker:
    """Records what it was asked to do, and can be told to fail.

    `state_after` is what `state_of` reports once an action ran — set to
    something other than the obvious answer to prove the endpoint reads the
    state back instead of deriving it from the action.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.created: list[CreateIn] = []
        self.state_after = "running"
        self.fail_with: Exception | None = None
        self.create_fails_with: Exception | None = None

    async def status(self) -> list[ContainerOut]:
        return [
            container(ALLOWED_ID, "media-server"),
            container(FORBIDDEN_ID, "dashboard-backend"),
        ]

    async def action(self, target_id: str, action: str) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append((target_id, action))

    async def create(self, spec: CreateIn, created_by: str) -> str:
        if self.create_fails_with is not None:
            raise self.create_fails_with
        self.created.append(spec)
        self.created_by = created_by
        return NEW_ID

    async def state_of(self, container_id: str) -> str:
        return self.state_after


@pytest.fixture
def docker(monkeypatch) -> FakeDocker:
    fake = FakeDocker()
    monkeypatch.setattr(service, "_docker", fake)
    return fake


@pytest.fixture(autouse=True)
def allowlist(monkeypatch):
    """Only `media-server` may be controlled — `dashboard-backend` may not."""
    monkeypatch.setattr(settings, "servers_control_allowlist", "media-server")


@pytest_asyncio.fixture
async def operator(client, session):
    """A signed-in account WITH a second factor — the only kind that may write."""
    user = await auth_service.create_user(session, "noa", PASSWORD)
    secret = pyotp.random_base32()
    await auth_service.start_totp_enrolment(session, user, secret)
    assert await auth_service.confirm_totp(session, user, pyotp.TOTP(secret).now())

    response = await client.post(
        "/api/auth/login",
        json={"username": "noa", "password": PASSWORD, "code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 200
    return client


@pytest.fixture
def create_ready(monkeypatch, allowlist):
    """Both lists filled: `paperless` may be created from `paperless:2.11`.

    Depends on `allowlist` on purpose — that autouse fixture sets the control
    list too, and this one has to be the later of the two.
    """
    monkeypatch.setattr(
        settings, "servers_control_allowlist", "media-server,paperless"
    )
    monkeypatch.setattr(
        settings, "servers_image_allowlist", "paperless:2.11,nginx:1.27"
    )


def spec(**overrides) -> dict:
    """A valid create body — tests override the one field they are about."""
    return {"name": "paperless", "image": "paperless:2.11", **overrides}


async def log_rows(session) -> list[ControlLog]:
    return list(await session.scalars(select(ControlLog).order_by(ControlLog.id)))


# ------------------------------------------------------------------ the gate
async def test_signed_out_cannot_act(client, docker):
    """The read endpoints are already behind the login; this one more so."""
    response = await client.post(
        f"/api/servers/containers/{ALLOWED_ID}/action", json={"action": "stop"}
    )
    assert response.status_code == 401
    assert docker.calls == []


async def test_allowlisted_container_can_be_restarted(operator, docker):
    response = await operator.post(
        f"/api/servers/containers/{ALLOWED_ID}/action", json={"action": "restart"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "id": ALLOWED_ID,
        "action": "restart",
        "state": "running",
    }
    assert docker.calls == [(ALLOWED_ID, "restart")]


async def test_container_outside_the_allowlist_is_refused(operator, docker):
    """The container is visible in the list. That does not make it controllable."""
    response = await operator.post(
        f"/api/servers/containers/{FORBIDDEN_ID}/action", json={"action": "stop"}
    )
    assert response.status_code == 403
    assert docker.calls == []


async def test_empty_allowlist_allows_nothing(operator, docker, monkeypatch):
    """Fails closed. An unconfigured install controls nothing at all."""
    monkeypatch.setattr(settings, "servers_control_allowlist", "")

    response = await operator.post(
        f"/api/servers/containers/{ALLOWED_ID}/action", json={"action": "start"}
    )
    assert response.status_code == 403
    assert docker.calls == []


async def test_password_alone_does_not_get_to_press_start(client_a, docker):
    """`user-a` is signed in with a password and no second factor.

    Reading is fine for that account. Writing is not: a login bypass here is a
    host takeover, and an account without TOTP is one guessed password away.
    """
    response = await client_a.post(
        f"/api/servers/containers/{ALLOWED_ID}/action", json={"action": "stop"}
    )
    assert response.status_code == 403
    assert docker.calls == []


# ------------------------------------------------------------------ the input
async def test_action_outside_the_list_is_rejected(operator, docker):
    """`kill` is not in the Literal, so it never reaches module code."""
    response = await operator.post(
        f"/api/servers/containers/{ALLOWED_ID}/action", json={"action": "kill"}
    )
    assert response.status_code == 422
    assert docker.calls == []


async def test_id_that_is_not_hex_is_rejected(operator, docker):
    """The path is constrained at the boundary — nothing shell-shaped gets in."""
    response = await operator.post(
        "/api/servers/containers/;%20rm%20-rf%20//action", json={"action": "stop"}
    )
    assert response.status_code in (404, 422)
    assert docker.calls == []


async def test_unknown_container_is_a_404(operator, docker):
    response = await operator.post(
        "/api/servers/containers/cccccccccccc/action", json={"action": "stop"}
    )
    assert response.status_code == 404
    assert docker.calls == []


async def test_docker_being_down_is_a_503(operator, docker):
    """A stopped daemon is an operating state, not a bug in the dashboard."""
    docker.fail_with = DriverUnavailable("Docker not reachable at tcp://127.0.0.1:2375")

    response = await operator.post(
        f"/api/servers/containers/{ALLOWED_ID}/action", json={"action": "start"}
    )
    assert response.status_code == 503


async def test_container_removed_between_check_and_action_is_a_404(operator, docker):
    docker.fail_with = UnknownTarget(ALLOWED_ID)

    response = await operator.post(
        f"/api/servers/containers/{ALLOWED_ID}/action", json={"action": "start"}
    )
    assert response.status_code == 404


async def test_state_is_read_back_not_guessed(operator, docker):
    """A container that dies right after `start` must not read as running."""
    docker.state_after = "exited"

    response = await operator.post(
        f"/api/servers/containers/{ALLOWED_ID}/action", json={"action": "start"}
    )
    assert response.json()["state"] == "exited"


# ------------------------------------------------------------------ the record
async def test_successful_action_is_logged(operator, docker, session):
    await operator.post(
        f"/api/servers/containers/{ALLOWED_ID}/action", json={"action": "stop"}
    )

    (row,) = await log_rows(session)
    assert (row.username, row.action, row.container_name) == ("noa", "stop", "media-server")
    assert row.ok is True
    assert row.detail is None


async def test_refused_action_is_logged_with_its_reason(operator, docker, session):
    """The refusals are the half worth having. Nobody notices an attempt that
    was blocked if only successes are written down."""
    await operator.post(
        f"/api/servers/containers/{FORBIDDEN_ID}/action", json={"action": "stop"}
    )

    (row,) = await log_rows(session)
    assert row.ok is False
    assert row.container_name == "dashboard-backend"
    assert "ALLOWLIST" in (row.detail or "")


async def test_unknown_container_is_logged_too(operator, docker, session):
    """An id that matches nothing is exactly the attempt to be able to look up."""
    await operator.post(
        "/api/servers/containers/cccccccccccc/action", json={"action": "stop"}
    )

    (row,) = await log_rows(session)
    assert (row.ok, row.container_id, row.detail) == (
        False,
        "cccccccccccc",
        "unknown container",
    )


async def test_failed_docker_call_is_logged_as_failed(operator, docker, session):
    docker.fail_with = DriverUnavailable("connection refused")

    await operator.post(
        f"/api/servers/containers/{ALLOWED_ID}/action", json={"action": "restart"}
    )

    (row,) = await log_rows(session)
    assert row.ok is False
    assert "connection refused" in (row.detail or "")


async def test_every_attempt_leaves_exactly_one_row(operator, docker, session):
    for action in ("start", "stop", "restart"):
        await operator.post(
            f"/api/servers/containers/{ALLOWED_ID}/action", json={"action": action}
        )
    await operator.post(
        f"/api/servers/containers/{FORBIDDEN_ID}/action", json={"action": "stop"}
    )

    assert await session.scalar(select(func.count()).select_from(ControlLog)) == 4


# ------------------------------------------------------------------ the list
async def test_list_marks_which_containers_may_be_controlled(operator, docker):
    """The list stays complete — hiding a container would make the overview lie
    about what runs on the host. Only the flag differs."""
    response = await operator.get("/api/servers/containers")
    by_name = {c["name"]: c for c in response.json()}

    assert by_name["media-server"]["controllable"] is True
    assert by_name["dashboard-backend"]["controllable"] is False


# ------------------------------------------------------------------ creating
async def test_signed_out_cannot_create(client, docker):
    response = await client.post("/api/servers/containers", json=spec())
    assert response.status_code == 401
    assert docker.created == []


async def test_allowed_name_and_image_are_created_and_started(
    operator, docker, create_ready
):
    response = await operator.post(
        "/api/servers/containers",
        json=spec(
            ports=[{"host": 8010, "container": 8000}],
            env={"PAPERLESS_URL": "https://paperless.example"},
        ),
    )

    assert response.status_code == 201
    assert response.json() == {
        "id": NEW_ID,
        "name": "paperless",
        "image": "paperless:2.11",
        "state": "running",
    }
    (created,) = docker.created
    assert created.name == "paperless"
    assert created.ports[0].host == 8010
    assert created.env == {"PAPERLESS_URL": "https://paperless.example"}
    # The label the driver writes says who asked for it.
    assert docker.created_by == "noa"


async def test_name_outside_the_control_allowlist_is_refused(
    operator, docker, create_ready
):
    """A container that may be created but not stopped is one nobody can switch
    off again — so creating is checked against the same list as stopping."""
    response = await operator.post("/api/servers/containers", json=spec(name="grafana"))

    assert response.status_code == 403
    assert docker.created == []


async def test_image_outside_the_image_allowlist_is_refused(
    operator, docker, create_ready
):
    """The name is fine here. The image is not, and that is the wider power of
    the two: an image is code that runs on the host."""
    response = await operator.post(
        "/api/servers/containers", json=spec(image="alpine:latest")
    )

    assert response.status_code == 403
    # The answer names the list to fix, because the fix is a line in .env.
    assert "SERVERS_IMAGE_ALLOWLIST" in response.json()["detail"]
    assert docker.created == []


async def test_empty_image_allowlist_creates_nothing(operator, docker, monkeypatch):
    """Fails closed, like every other list here. An unconfigured install may
    create nothing at all — not even from an image it already runs."""
    monkeypatch.setattr(settings, "servers_control_allowlist", "paperless")
    monkeypatch.setattr(settings, "servers_image_allowlist", "")

    response = await operator.post("/api/servers/containers", json=spec())

    assert response.status_code == 403
    assert docker.created == []


async def test_password_alone_does_not_get_to_create(client_a, docker, create_ready):
    response = await client_a.post("/api/servers/containers", json=spec())
    assert response.status_code == 403
    assert docker.created == []


async def test_taken_name_is_a_409(operator, docker, create_ready):
    """`media-server` is on the control list and already running."""
    response = await operator.post(
        "/api/servers/containers", json=spec(name="media-server")
    )

    assert response.status_code == 409
    assert docker.created == []


async def test_image_missing_on_the_host_is_a_409_not_a_pull(
    operator, docker, create_ready
):
    """A pull fetches code over the network and takes as long as it takes.
    That does not belong in a request, so the answer says to pull it there."""
    docker.create_fails_with = TargetConflict("Image paperless:2.11 is not on the host.")

    response = await operator.post("/api/servers/containers", json=spec())

    assert response.status_code == 409
    assert "not on the host" in response.json()["detail"]


async def test_docker_being_down_is_a_503_for_create_too(operator, docker, create_ready):
    docker.create_fails_with = DriverUnavailable("connection refused")

    response = await operator.post("/api/servers/containers", json=spec())

    assert response.status_code == 503


async def test_state_is_read_back_after_creating(operator, docker, create_ready):
    """A wrong environment variable is enough to make an image exit at once.
    That must not report `running` just because `start` returned."""
    docker.state_after = "exited"

    response = await operator.post("/api/servers/containers", json=spec())

    assert response.json()["state"] == "exited"


# ------------------------------------------------------- creating: the input
@pytest.mark.parametrize(
    "body, why",
    [
        ({"name": "../../etc", "image": "paperless:2.11"}, "path shaped name"),
        ({"name": "two words", "image": "paperless:2.11"}, "space in the name"),
        ({"name": "paperless", "image": "paperless"}, "image without a tag"),
        ({"name": "paperless", "image": "paperless:2.11; rm -rf /"}, "shell shaped tag"),
    ],
)
async def test_malformed_specification_never_reaches_the_service(
    operator, docker, create_ready, body, why
):
    """422 at the boundary, before a single line of module code runs."""
    response = await operator.post("/api/servers/containers", json=body)

    assert response.status_code == 422, why
    assert docker.created == []


async def test_privileged_host_port_is_rejected(operator, docker, create_ready):
    """80 and 443 belong to the reverse proxy, and everything below 1024 needs
    root to bind. The dashboard does not hand those out."""
    response = await operator.post(
        "/api/servers/containers",
        json=spec(ports=[{"host": 80, "container": 80}]),
    )

    assert response.status_code == 422
    assert docker.created == []


async def test_same_host_port_twice_is_rejected(operator, docker, create_ready):
    response = await operator.post(
        "/api/servers/containers",
        json=spec(
            ports=[
                {"host": 8010, "container": 8000},
                {"host": 8010, "container": 9000},
            ]
        ),
    )

    assert response.status_code == 422
    assert docker.created == []


async def test_environment_is_bounded(operator, docker, create_ready):
    """Names to a pattern, values bounded, the map bounded. An unbounded
    environment is a memory problem with a friendly name."""
    too_many = await operator.post(
        "/api/servers/containers",
        json=spec(env={f"VAR_{i}": "x" for i in range(33)}),
    )
    bad_name = await operator.post(
        "/api/servers/containers", json=spec(env={"NOT A NAME": "x"})
    )
    too_long = await operator.post(
        "/api/servers/containers", json=spec(env={"BIG": "x" * 513})
    )

    assert [r.status_code for r in (too_many, bad_name, too_long)] == [422, 422, 422]
    assert docker.created == []


async def test_a_create_cannot_smuggle_in_a_mount(operator, docker, create_ready):
    """Fields that would make a container powerful do not exist in the schema,
    so sending them changes nothing — the container is created without them."""
    response = await operator.post(
        "/api/servers/containers",
        json=spec(
            volumes={"/": {"bind": "/host", "mode": "rw"}},
            privileged=True,
            network_mode="host",
            command="sh -c 'cat /etc/shadow'",
        ),
    )

    assert response.status_code == 201
    (created,) = docker.created
    assert not hasattr(created, "volumes")
    assert not hasattr(created, "privileged")
    assert not hasattr(created, "command")


# ------------------------------------------------------ creating: the record
async def test_successful_create_is_logged(operator, docker, create_ready, session):
    await operator.post("/api/servers/containers", json=spec())

    (row,) = await log_rows(session)
    assert (row.username, row.action, row.container_name) == ("noa", "create", "paperless")
    assert (row.ok, row.container_id) == (True, NEW_ID)


async def test_refused_create_is_logged_with_its_reason(
    operator, docker, create_ready, session
):
    """The requested name is in the row even though no such container exists —
    "someone tried to create X" is the line worth being able to find."""
    await operator.post("/api/servers/containers", json=spec(image="alpine:latest"))

    (row,) = await log_rows(session)
    assert (row.ok, row.action, row.container_name) == (False, "create", "paperless")
    assert "SERVERS_IMAGE_ALLOWLIST" in (row.detail or "")
    assert row.container_id == ""


async def test_every_create_attempt_leaves_exactly_one_row(
    operator, docker, create_ready, session
):
    await operator.post("/api/servers/containers", json=spec())
    await operator.post("/api/servers/containers", json=spec(name="grafana"))
    await operator.post("/api/servers/containers", json=spec(image="alpine:latest"))
    # 422 does not count: it never reaches the service.
    await operator.post("/api/servers/containers", json=spec(name="no good"))

    assert await session.scalar(select(func.count()).select_from(ControlLog)) == 3
