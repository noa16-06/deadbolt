// Data access for the server manager.
//
// Three separate switches, because the backend arrived in phases and one flag
// for all of it would claim things that are not true.

import { api } from "../../lib/api.js";

// Reading is live: the backend serves containers, metrics and logs.
export const MOCK = false;

// Writing is live too now: start / stop / restart and creating a container.
// It waited for TOTP and the login rate limit (docs/security.md), and it is
// narrower than the switch suggests — the backend only touches containers on
// SERVERS_CONTROL_ALLOWLIST, and only creates from images on
// SERVERS_IMAGE_ALLOWLIST. Which is why the row carries `controllable`: the
// buttons for everything else stay dead instead of firing off a 403.
export const WRITE_ENABLED = true;

// The terminal has no backend at all yet, so the stand-in shell keeps running.
export const MOCK_TERMINAL = true;

// ---------------------------------------------------------------- actions
// Fixed list. Anything not in here cannot be triggered by the UI — and the
// backend will accept only these values too, instead of passing a free-form
// string through. A client is not a security boundary; both sides check.
export const ACTIONS = ["start", "stop", "restart"];

export const STATES = {
  running: { label: "running", color: "#b8bb26" },
  paused: { label: "paused", color: "#fabd2f" },
  exited: { label: "exited", color: "#928374" },
  restarting: { label: "restarting", color: "#83a598" },
  unhealthy: { label: "unhealthy", color: "#fb4934" },
};

// ---------------------------------------------------------------- mock data
const hoursAgo = (h) => new Date(Date.now() - h * 3600_000).toISOString();

const MOCK_CONTAINERS = [
  {
    id: "3f2a91c4e7b8",
    name: "dashboard-backend",
    image: "homelab/dashboard:0.1.0",
    state: "running",
    since: hoursAgo(32),
    ports: [{ host: 8000, container: 8000, protocol: "tcp" }],
    cpu: 2.4,
    ram: { used: 148, limit: 1024 },
    stack: "dashboard",
  },
  {
    id: "9c81ba03d55f",
    name: "caddy",
    image: "caddy:2.8-alpine",
    state: "running",
    since: hoursAgo(213),
    ports: [
      { host: 80, container: 80, protocol: "tcp" },
      { host: 443, container: 443, protocol: "tcp" },
    ],
    cpu: 0.3,
    ram: { used: 42, limit: 256 },
    stack: "edge",
  },
  {
    id: "c07de4419aa2",
    name: "jellyfin",
    image: "jellyfin/jellyfin:10.9",
    state: "running",
    since: hoursAgo(52),
    ports: [{ host: 8096, container: 8096, protocol: "tcp" }],
    cpu: 41.7,
    ram: { used: 2310, limit: 4096 },
    stack: "medien",
  },
  {
    id: "5b6f2c8a1de0",
    name: "postgres",
    image: "postgres:16-alpine",
    state: "unhealthy",
    since: hoursAgo(2),
    ports: [{ host: 5432, container: 5432, protocol: "tcp" }],
    cpu: 1.1,
    ram: { used: 512, limit: 2048 },
    stack: "daten",
  },
  {
    id: "a4e90f7c2b31",
    name: "ubuntu-sandbox",
    image: "ubuntu:24.04",
    state: "running",
    since: hoursAgo(0.7),
    ports: [],
    cpu: 0.0,
    ram: { used: 18, limit: 512 },
    stack: "werkbank",
  },
  {
    id: "e18c53d0f9a7",
    name: "backup-runner",
    image: "restic/restic:0.17",
    state: "exited",
    since: hoursAgo(1.4),
    ports: [],
    cpu: 0.0,
    ram: { used: 0, limit: 256 },
    stack: "daten",
  },
  {
    id: "7d20a6b4c8e5",
    name: "watchtower",
    image: "containrrr/watchtower:1.7",
    state: "paused",
    since: hoursAgo(96),
    ports: [],
    cpu: 0.0,
    ram: { used: 11, limit: 128 },
    stack: "wartung",
  },
];

// Produces a plausibly wobbling history for the sparklines.
function history(base, spread, n = 40) {
  const values = [];
  let value = base;
  for (let i = 0; i < n; i++) {
    value += (Math.random() - 0.5) * spread;
    value = Math.min(100, Math.max(0, value));
    values.push(Math.round(value * 10) / 10);
  }
  return values;
}

function mockMetrics() {
  const cores = [18, 44, 7, 62, 12, 9, 31, 5].map(
    (k) => Math.round(Math.min(100, Math.max(0, k + (Math.random() - 0.5) * 14)) * 10) / 10
  );
  const total = Math.round((cores.reduce((a, b) => a + b, 0) / cores.length) * 10) / 10;
  return {
    host: "homelab-01",
    uptimeSeconds: 1_412_733,
    cpu: {
      model: "AMD Ryzen 7 5700X",
      total,
      cores,
      temperature: 54 + Math.round(Math.random() * 6),
      history: history(total, 9),
    },
    gpu: {
      model: "NVIDIA RTX 3060 12GB",
      usage: Math.round((37 + (Math.random() - 0.5) * 20) * 10) / 10,
      memory: { used: 4210, total: 12288 },
      temperature: 61 + Math.round(Math.random() * 5),
      power: { watts: 92, limit: 170 },
      history: history(37, 16),
    },
    ram: { used: 11_420, total: 32_768 },
    swap: { used: 210, total: 8192 },
    disks: [
      { path: "/", used: 128, total: 460 },
      { path: "/mnt/media", used: 3120, total: 4000 },
    ],
    net: { rxMbit: 12.4, txMbit: 3.1 },
  };
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- api
export const serversApi = {
  async containers() {
    if (MOCK) {
      await wait(220);
      // A copy, so the UI does not permanently mutate the mock data
      return MOCK_CONTAINERS.map((c) => ({ ...c }));
    }
    return api.get("/servers/containers");
  },

  async metrics() {
    if (MOCK) {
      await wait(160);
      return mockMetrics();
    }
    return api.get("/servers/metrics");
  },

  async action(containerId, action) {
    if (!ACTIONS.includes(action)) {
      throw new Error(`Unknown action: ${action}`);
    }
    if (!WRITE_ENABLED) {
      throw new Error("Write access is not enabled yet.");
    }
    if (MOCK) {
      await wait(700);
      return { id: containerId, action, ok: true };
    }
    return api.post(`/servers/containers/${containerId}/action`, { action });
  },

  // The four fields the backend accepts, and no more. Volumes, `privileged`,
  // the network mode and a command are not "not implemented here" — they do
  // not exist in the API, because each one turns creating a container into
  // running anything as root on the host.
  async createContainer(spec) {
    if (!WRITE_ENABLED) {
      throw new Error("Write access is not enabled yet.");
    }
    if (MOCK) {
      await wait(700);
      return { id: "0123456789ab", name: spec.name, image: spec.image, state: "running" };
    }
    return api.post("/servers/containers", {
      name: spec.name,
      image: spec.image,
      ports: spec.ports ?? [],
      env: spec.env ?? {},
    });
  },

  async logs(containerId, lines = 200) {
    if (MOCK) {
      await wait(300);
      const now = Date.now();
      return Array.from({ length: 24 }, (_, i) => {
        const t = new Date(now - (24 - i) * 4000).toISOString().slice(11, 19);
        return `${t} [info] ${containerId.slice(0, 6)} heartbeat ok (${i + 1})`;
      }).join("\n");
    }
    return api.get(`/servers/containers/${containerId}/logs?lines=${lines}`);
  },
};
