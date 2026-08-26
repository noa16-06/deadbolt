# Homelab Dashboard

Two tools under one roof, for a single-user homelab:

1. **Productivity tool** — a weekly planner with time blocks and tasks
2. **Server manager** — Docker containers, CPU/GPU metrics, and a web terminal

Terminal-flavoured UI (Gruvbox, monospace), FastAPI backend, React frontend,
SQLite. Built to run on one Linux box behind a reverse proxy.

## Layout

```
dashboard/
├── backend/                    FastAPI, Python 3.12+
│   ├── app/
│   │   ├── main.py             app, router registration, health, error handler
│   │   ├── config.py           .env settings (missing value → no start)
│   │   ├── db.py               engine, session dependency, SQLite pragmas
│   │   ├── security.py         argon2id + signed session cookies
│   │   ├── deps.py             DbSession, CurrentUser
│   │   └── modules/
│   │       ├── auth/           sign in, sign out, /me
│   │       ├── planner/        productivity tool
│   │       └── servers/        phase 2 (empty — see its README)
│   ├── migrations/             Alembic
│   ├── scripts/create_user.py  create a user (password asked interactively)
│   ├── tests/
│   └── run.py
├── frontend/                   Vite + React
│   └── src/
│       ├── App.jsx             login gate + routes (/planner, /servers)
│       ├── components/Shell    shared header and navigation
│       ├── lib/api.js          fetch wrapper (cookie + timeout)
│       ├── lib/useAuth.js      sign-in state
│       ├── theme/colors.js     Gruvbox palette
│       └── features/
│           ├── auth/           Login.jsx
│           ├── planner/        DayPlan.jsx, plannerApi.js
│           └── servers/        ServerManager, ContainerList, Metrics,
│                               WebTerminal — data still mocked
├── data/                       SQLite database — not in the repo
├── docker/                     entrypoint for the backend image
├── docker-compose.yml          backend + frontend + Docker socket proxy
└── docs/security.md            what has to be true before this is public
```

Every module has the same four files: `models.py` (tables), `schemas.py`
(validation at the boundary), `service.py` (logic, knows no HTTP),
`router.py` (endpoints). A module that deviates from that has earned a reason.

## Getting started

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # -> SECRET_KEY

cd backend
python3 -m venv ../.venv && source ../.venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python scripts/create_user.py    # password is asked for, lands in no file
python run.py                    # -> http://127.0.0.1:8000
```

```bash
cd frontend
npm install
npm run dev                      # -> http://localhost:5173
```

Use the dashboard on **http://localhost:5173**, not on :8000 — Vite proxies
`/api` to the backend, so the origin in the browser is identical and the
session cookie works without CORS special cases.

## Running in Docker

For the homelab box. Local development stays as it is above — the compose setup
is for the machine this actually runs on, and it needs Linux (`/proc` is
bind-mounted, and there is no Docker socket to speak of on macOS).

```bash
cp .env.example .env       # SECRET_KEY, and AUTH_DISABLED=false
docker compose up -d --build
```

Then **http://127.0.0.1:8080**, with Caddy in front of it.

Three containers:

| Service        | What it does                                          |
| -------------- | ----------------------------------------------------- |
| `frontend`     | nginx: serves the built bundle, proxies `/api`         |
| `backend`      | FastAPI, migrates on start, runs as uid 1000           |
| `socket-proxy` | the only container that sees `/var/run/docker.sock`    |

Configuration comes from the same `.env` as the local start. Compose overrides
only what has to differ inside a container, and each override is commented
where it stands.

### What is deliberately awkward

**`AUTH_DISABLED=true` will not start.** Inside a container the backend has to
bind `0.0.0.0`, and `app/config.py` refuses that combination. It is right to:
`0.0.0.0` here means "reachable from the frontend container" — no port is
published for the backend — but a login bypass on a Docker-controlling
dashboard should cost an argument, not a shrug. Set it to `false`.

**Only the frontend is published, and only on loopback**
(`127.0.0.1:8080:8080`). Dropping the address would put the dashboard on the
LAN, which is the one thing `docs/security.md` rules out.

**The backend never sees the Docker socket.** It talks to
`tecnativa/docker-socket-proxy` over a network marked `internal: true`, and
that proxy answers a fixed set of paths. `POST: 0` is the default, so the whole
write half — start, stop, restart, create — fails at the proxy before it
reaches Docker. Reading is unaffected. Setting `POST: 1` is one line in
`docker-compose.yml` and still not enough on its own: the name has to be on
`SERVERS_CONTROL_ALLOWLIST`, the image on `SERVERS_IMAGE_ALLOWLIST`, and the
account needs TOTP.

**`DOCKER_UID` / `DOCKER_GID` have to match the owner of `./data`** (`id -u`,
`id -g`). The database is a bind mount rather than a named volume because it is
the thing that gets backed up, and a backup you have to `docker cp` out of a
volume is a backup nobody takes.

### What the metrics panel loses in a container

`/proc` is mounted read-only and `PSUTIL_PROCFS_PATH` points at it, so CPU, RAM
and network are the host's. Two things do not follow:

- **No GPU.** `nvidia-smi` is not in the image. The driver handles its absence
  and the panel hides the card.
- **No CPU temperature.** It lives in `/sys/class/hwmon`, which
  `PSUTIL_PROCFS_PATH` does not cover.

Disks are read through the paths in `SERVERS_DISKS`, which are container paths:
mount what you want shown and name it there.


On first sign-in the backend creates a default weekly plan
(`app/modules/planner/default_plan.py`).

## What the server manager may touch

Reading is unrestricted behind the login: the list shows every container on the
host, running or not. Writing is not, and it takes two configured lists plus a
second factor:

```ini
# start / stop / restart, and the names a new container may be created under
SERVERS_CONTROL_ALLOWLIST=media-server,paperless
# the images it may be created from, tag included
SERVERS_IMAGE_ALLOWLIST=paperless:2.11,nginx:1.27
```

Both are empty by default, and empty allows nothing. The account also needs
TOTP — a password alone stays read-only, because a guessed password would
otherwise be root on the host (`docs/security.md`).

Creating takes a name, an image, published ports (host port 1024 and above) and
environment variables. It does not take volumes, `privileged`, a network mode or
a command: those are not narrow options, they are the difference between
starting a container and running anything on the host, so the dashboard pins
them instead of offering them. The image has to be on the host already — the
dashboard does not pull.

Every write attempt, refused ones included, is one row in `servers_control_log`:
who, what, which target, when, and why it failed.

## How the planner handles "done"

The plan is a **weekday template**: "Monday" is a recurring shape, not one
specific date. Completions are not — they live in their own table, one row per
entry and day (`planner_block_completions`). Ticking something off on Monday
therefore does not leave it ticked forever: the next Monday starts empty, and
the history is there for later (streaks, weekly review).

`GET /api/planner/week?date=…` takes any day of the wanted week, normalises it
to that week's Monday, and resolves every weekday against its own date.

## Status

**Working:** sign-in (session cookie, argon2id), the weekly planner end to end
with date-bound completions, and the server manager — reading. Containers,
metrics and logs come from the real backend against Docker and psutil.

**Mocked:** only the terminal (`MOCK_TERMINAL`), which has no backend yet.

**Deliberately off:** start / stop / restart. The endpoint does not exist and
`WRITE_ENABLED` is `false`, so the UI shows those buttons disabled. Write
access waits for TOTP — a restart button reachable from the internet behind a
single password is the case `docs/security.md` argues against.

**Currently switched off for development:** `AUTH_DISABLED=true` in `.env` —
no sign-in, every request runs as the `dev` user, and a red banner says so. The
backend refuses to start if that flag meets `COOKIE_SECURE=true`, a non-loopback
`HOST`, or a remote CORS origin. Set it to `false` before the domain points here.

**Two-factor and rate limiting are in place.** Enrol with
`python backend/scripts/enable_totp.py` — QR code in the terminal, ten one-time
recovery codes. The login takes 5 failed attempts per IP and 10 per account per
15 minutes; a success clears the record. Behind Caddy, `TRUST_PROXY_HEADER=true`
is required or everyone shares one bucket.

**Open:**

- the write half of `servers`: actions, audit log, terminal WebSocket
- the Proxmox and systemd drivers — only Docker exists so far
- reverse proxy, security headers, backups (see `docs/security.md`)

## Tests

```bash
cd backend && python -m pytest
```

80 of them, all running — no placeholders left. `tests/conftest.py` builds an
in-memory database per test and two separately signed-in clients, which is what
the planner authorization tests needed. Covered: can user A reach user B's data,
does a password alone still get in once TOTP is on, does a recovery code work
exactly once, does guessing get blocked, and the Docker payload parsing.

## Security

This is meant to be reachable over a domain, and the server manager is meant to
**control** Docker, Proxmox and systemd. That makes a login bypass a host
takeover, not a data leak. The checklist that has to be ticked before the first
public DNS record lives in [`docs/security.md`](docs/security.md).

Short version: HTTPS in front, the backend bound to `127.0.0.1` only, TOTP as a
second factor, rate limiting on the login — and in the `servers` module, never
put request data into a command.
