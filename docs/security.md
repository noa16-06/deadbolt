# Security baseline

Two decisions set the bar (23 Aug 2026):

1. The dashboard will be **reachable publicly over a domain**.
2. The server manager will **control** Docker, Proxmox (VMs/LXC) and systemd —
   not just display them.

It follows that anyone who signs in here can run code on the homelab. Docker
socket access is root on the host, with no detour. A login bypass is therefore
not a data leak, it is a host takeover. None of what follows is optional.

## Required before the domain points here

- [ ] Reverse proxy (Caddy) with HTTPS. The backend binds to `127.0.0.1`, never `0.0.0.0`.
- [ ] `COOKIE_SECURE=true`, `SameSite=Lax`, `HttpOnly` (already in place)
- [ ] `CORS_ORIGINS` set to the real domain. Never `*` together with cookies.
- [x] **TOTP as a second factor.** Built. Enrol with
      `python backend/scripts/enable_totp.py` (QR code in the terminal, ten
      one-time recovery codes). The secret is stored encrypted with a key
      derived from SECRET_KEY, so a leaked database copy alone does not hand
      over the second factor. Note: rotating SECRET_KEY forces re-enrolment.
- [x] Rate limiting on `/api/auth/login`. Built: 5 failed attempts per IP and
      10 per account within 15 minutes, both configurable. Only failures count
      and a success clears the record. **Behind Caddy, set
      `TRUST_PROXY_HEADER=true`** — otherwise every request appears to come
      from 127.0.0.1 and everyone shares one bucket. Never set it without a
      proxy that overwrites the header, or the limit is decoration.
- [ ] Security headers: `Content-Security-Policy`, `X-Content-Type-Options`,
      `Referrer-Policy`, HSTS.

## Rules for the `servers` module

- **No request field ever ends up in a shell command.** No interpolation, no
  `shell=True`. Only the Docker SDK, the Proxmox API, D-Bus.
- **Allow-list, not deny-list.** Permitted actions are a fixed list (`start`,
  `stop`, `restart`), never a string passed through. Creating a container is
  the fourth write action and needs two lists at once: the NAME on
  `SERVERS_CONTROL_ALLOWLIST` (a container that may be created but not stopped
  is one nobody can switch off again) and the IMAGE on
  `SERVERS_IMAGE_ALLOWLIST`, tag included. Both fail closed.
- **A create specifies, it does not command.** The body holds a name, an image,
  published ports and environment variables — nothing else. Volumes,
  `privileged`, host network, devices, capabilities, user, entrypoint and
  command are not fields that are validated, they are fields that do not exist:
  each one turns "create a container" into "run anything as root on the host".
  The safe values are pinned in the driver (`_HARDENING`) where a request cannot
  reach them.
- **The dashboard does not pull images.** A pull fetches code over the network
  and takes as long as it takes — that is a long running action, and it belongs
  on the host. A missing image is a 409 that says so.
- **Targets are configured, not submitted.** Which hosts and containers can be
  addressed lives in the configuration. The client picks from a list of ids, it
  never names a host freely.
- **Do not use the bare Docker socket.** Use a socket proxy with a restricted
  endpoint set where possible. Otherwise any application bug is immediately
  root. Creating needs `POST /containers/create` and `POST /containers/{id}/start`
  open on that proxy — leave them closed and the rest of the module still works,
  which is the cheapest way to switch the create half off entirely.
- **Proxmox tokens and SSH keys are secrets at rest.** Not in the database in
  plain text, not in the repo, file mode 0600.
- **Every write action gets logged**: who, what, which target, when, outcome.
  That is the only chance of reconstructing afterwards what happened.
- **Long running actions do not belong in the request path.** A job table in
  SQLite plus a worker task. No external queue.
- **Container ids are user input.** Check them against the configured target
  list instead of handing them to Docker unchecked.

## Operations

- [ ] The backend runs as its own unprivileged user
- [ ] Backups of `data/dashboard.db` — and a restore actually tested once.
      An untested backup is a hypothesis, not a backup.
- [ ] Dependencies pinned by lockfile, scanned (`pip-audit`, `npm audit`) in CI
