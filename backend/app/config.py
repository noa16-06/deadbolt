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

    # Which containers may later be CONTROLLED (phase: write access). Empty
    # means nothing may be controlled — the list only ever grows deliberately.
    # Reading is unaffected: the list shows everything.
    servers_control_allowlist: str = ""

    @property
    def disk_list(self) -> list[str]:
        return [p.strip() for p in self.servers_disks.split(",") if p.strip()]

    @property
    def control_allowlist(self) -> set[str]:
        return {n.strip() for n in self.servers_control_allowlist.split(",") if n.strip()}

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


def _load() -> Settings:
    """On a failed start, say what to do instead of dumping a traceback."""
    try:
        return Settings()  # type: ignore[call-arg]
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
