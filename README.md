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

On first sign-in the backend creates a default weekly plan
(`app/modules/planner/default_plan.py`).

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

**Open:**

- TOTP and login rate limiting, both required before the domain points here
- the write half of `servers`: actions, audit log, terminal WebSocket
- the Proxmox and systemd drivers — only Docker exists so far
- planner tests still need fixtures; `test_servers_docker.py` runs (18 cases)

## Security

This is meant to be reachable over a domain, and the server manager is meant to
**control** Docker, Proxmox and systemd. That makes a login bypass a host
takeover, not a data leak. The checklist that has to be ticked before the first
public DNS record lives in [`docs/security.md`](docs/security.md).

Short version: HTTPS in front, the backend bound to `127.0.0.1` only, TOTP as a
second factor, rate limiting on the login — and in the `servers` module, never
put request data into a command.
