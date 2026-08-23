# Module: server manager

**Reading is built, writing is not.** Containers, metrics and logs come from
the real backend; `MOCK` in `serversApi.js` is `false`. Start / stop / restart
and the terminal deliberately do not exist yet — see below.

## Endpoints

| Method | Path | State |
|---|---|---|
| GET | `/api/servers/containers` | **built** — `id, name, image, state, since, ports[], cpu, ram{used,limit}, stack` |
| GET | `/api/servers/metrics` | **built** — `host, uptimeSeconds, cpu{...}, gpu{...}, ram, swap, disks[], net` |
| GET | `/api/servers/containers/{id}/logs?lines=N` | **built** — text, `lines` capped at 2000 |
| POST | `/api/servers/containers/{id}/action` | open — body `{ action }`, only `start`, `stop`, `restart` |
| WS | `/api/servers/terminal` | open — bidirectional byte stream to the Ubuntu workbench |

`state` is one of: `running`, `paused`, `exited`, `restarting`, `unhealthy`
(see `STATES` in `serversApi.js`). `gpu` is `null` on a host without an NVIDIA
card, `temperature` is `null` without a sensor — the UI renders both.

Every endpoint sits behind `CurrentUser`. Which containers exist and what the
host is called is reconnaissance, not public information.

## Why writing comes later

The order is not arbitrary. A restart button reachable from the internet behind
a single password is exactly what `docs/security.md` argues against, so the
write endpoints wait for TOTP and the login rate limit. Until then
`WRITE_ENABLED` in `serversApi.js` is `false` and the UI shows those buttons
disabled instead of firing requests at a route that is missing on purpose.

## Layout

```
servers/
├── router.py          endpoints, thin
├── schemas.py         wire format (action as a Literal, never a free string)
├── service.py         picks the driver, later writes the audit log
├── sampler.py         background task: metrics and container stats into a cache
├── terminal.py        (open) WebSocket -> docker exec into ONE configured container
└── drivers/
    ├── base.py        shared protocol: status() / action()
    ├── docker.py      built, reading only
    ├── host.py        psutil + nvidia-smi
    ├── proxmox.py     (open)
    └── systemd.py     (open)
```

`sampler.py` is not decoration. `psutil.cpu_percent` needs two readings for a
load value and Docker takes about a second per container to compute a CPU
delta — for seven containers that is seven seconds a caller would sit waiting.
One task samples on a fixed rhythm, the endpoints answer from its cache, and
the sparkline history stays evenly spaced no matter how often the page is
opened.

## Configuration

`DOCKER_HOST`, `SERVERS_SAMPLE_SECONDS`, `SERVERS_DISKS`,
`SERVERS_CONTROL_ALLOWLIST` — documented in `.env.example`. The allow-list is
for the write phase and fails closed: empty means nothing may be controlled.

## Non-negotiable

Spelled out in `docs/security.md`. The most important points:

- **No request field ever ends up in a command.** No `shell=True`, no
  interpolation. Only the Docker SDK, the Proxmox API, D-Bus.
- **Actions are an allow-list**, not a string passed through. The frontend
  already sticks to it (`ACTIONS` in `serversApi.js`) — the backend has to
  enforce it independently, because a client is not a security boundary.
- **The terminal target lives in the configuration, not in the request.**
  Otherwise "open terminal" is a field you type `dashboard-backend` into. The
  container is a throwaway instance with no Docker socket and no access to the
  internal network.
- **Do not use the bare Docker socket.** Whoever reaches the socket is root on
  the host, bypassing whatever privileges the backend itself has.
- **Every write action gets logged**: who, what, which target, when, outcome.
- **Container ids are user input.** Check them against the configured target
  list instead of passing them to Docker unchecked.
