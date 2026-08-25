"""Configuration read from .env — none of this belongs in the repo.

If a required variable is missing, pydantic-settings raises on import. That is
deliberate: fail loudly right away rather than quietly run with a default
secret.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Required — no default, so a missing key is noticed immediately.
    secret_key: str

    database_url: str = "sqlite+aiosqlite:///./data/dashboard.db"
    cors_origins: str = "http://localhost:5173"
    cookie_secure: bool = False

    host: str = "127.0.0.1"
    port: int = 8000

    # ------------------------------------------------------------ login limit
    # 5 attempts per IP per window, plus a per-account lock so a botnet cannot
    # spread the guessing across addresses. Only failures count; a success
    # clears the record.
    login_max_per_ip: int = 5
    login_max_per_account: int = 10
    login_window_minutes: int = 15

    # Take the client IP from X-Forwarded-For instead of the socket.
    #
    # ONLY with a reverse proxy in front that overwrites the header. Without
    # one, anyone can set it and the rate limit becomes decoration. Left off,
    # every request behind a proxy looks like it comes from 127.0.0.1 and
    # shares one bucket — so this has to be switched on together with Caddy.
    trust_proxy_header: bool = False

    # ------------------------------------------------------------ development
    # Skips the login entirely: every request runs as the first user in the
    # database. For local work, so the login form is not in the way.
    #
    # Never true anywhere reachable. `_check_dev_switches` below refuses to
    # start if this is combined with settings that look like production — a
    # forgotten flag here is a host takeover, not an inconvenience.
    auth_disabled: bool = False

    # ---------------------------------------------------------- server manager
    # Deliberately NOT the bare socket: whoever reaches /var/run/docker.sock is
    # root on the host, past everything the backend is otherwise allowed to do.
    # The default points at a socket proxy with a restricted endpoint set
    # (see docs/security.md).
    docker_host: str = "tcp://127.0.0.1:2375"
    docker_timeout: int = 10

    # How often the background sampler collects host metrics and container
    # stats. Docker computes a CPU delta per container and needs about a second
    # for it, so a short interval buys nothing.
    servers_sample_seconds: int = 10
    servers_history_length: int = 40

    # Mount points for the disk display. Empty: detect physical partitions.
    servers_disks: str = ""

    # Which containers may be CONTROLLED — started, stopped, restarted, and
    # created under that name. Empty means nothing may be controlled: the list
    # only ever grows deliberately. Reading is unaffected: the list shows
    # everything.
    servers_control_allowlist: str = ""

    # Which IMAGES a container may be created from. Empty means nothing may be
    # created, and for a harder reason than the list above: an image is code
    # that runs on this host, so "any image" reads as "any code, as root".
    #
    # Entries are exact `repository:tag` strings. A bare `nginx` matches
    # nothing on purpose — the tag decides which code runs, so leaving it out
    # would turn one allowed image into every future version of it.
    servers_image_allowlist: str = ""

    @property
    def disk_list(self) -> list[str]:
        return [p.strip() for p in self.servers_disks.split(",") if p.strip()]

    @property
    def control_allowlist(self) -> set[str]:
        return {n.strip() for n in self.servers_control_allowlist.split(",") if n.strip()}

    @property
    def image_allowlist(self) -> set[str]:
        return {i.strip() for i in self.servers_image_allowlist.split(",") if i.strip()}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def absolute_db_url(self) -> str:
        """Resolve a relative SQLite path against the project root.

        Otherwise `python run.py` creates the database somewhere else than
        `alembic upgrade` does, because the two are started from different
        directories.
        """
        prefix, _, path = self.database_url.partition(":///")
        if not path or path.startswith("/"):
            return self.database_url
        target = (PROJECT_ROOT / path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        return f"{prefix}:///{target}"


def _check_dev_switches(settings: "Settings") -> None:
    """Refuse to start when AUTH_DISABLED meets a production-looking setup.

    The point is not to be clever about detecting production. It is that the
    one switch which turns a login into no login must be impossible to leave
    on by accident.
    """
    if not settings.auth_disabled:
        return

    reasons = []
    if settings.cookie_secure:
        reasons.append("COOKIE_SECURE=true (so this is served over HTTPS)")
    if settings.host not in ("127.0.0.1", "localhost", "::1"):
        reasons.append(f"HOST={settings.host} (not loopback — reachable from outside)")
    remote = [
        o
        for o in settings.cors_origin_list
        if "localhost" not in o and "127.0.0.1" not in o
    ]
    if remote:
        reasons.append(f"CORS_ORIGINS points at {', '.join(remote)}")

    if not reasons:
        return

    raise SystemExit(
        "\n".join(
            [
                "",
                "  AUTH_DISABLED=true together with a production-looking setup:",
                *(f"    - {r}" for r in reasons),
                "",
                "  That combination is a login bypass on a reachable host.",
                "  Set AUTH_DISABLED=false in .env, or undo the settings above.",
                "",
            ]
        )
    )


def _load() -> Settings:
    """On a failed start, say what to do instead of dumping a traceback."""
    try:
        settings = Settings()  # type: ignore[call-arg]
        _check_dev_switches(settings)
        return settings
    except ValidationError as error:
        missing = [
            ".".join(str(t) for t in f["loc"])
            for f in error.errors()
            if f["type"] == "missing"
        ]
        if not missing:
            raise

        env_file = PROJECT_ROOT / ".env"
        lines = [
            "",
            "  Configuration incomplete — these values are missing:",
            *(f"    - {name.upper()}" for name in missing),
            "",
        ]
        if not env_file.exists():
            lines += [
                f"  There is no .env at {env_file} yet.",
                "",
                "  Create one (from the project root):",
                "    cp .env.example .env",
                '    python3 -c "import secrets; print(secrets.token_urlsafe(48))"',
                "    # put the output into .env as SECRET_KEY",
            ]
        else:
            lines += [
                f"  The .env at {env_file} exists, but these values are not in it.",
                "  Compare it against .env.example.",
            ]
        lines.append("")
        raise SystemExit("\n".join(lines)) from None


settings = _load()
