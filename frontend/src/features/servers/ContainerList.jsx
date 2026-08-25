import { useMemo, useState } from "react";
import { ACTIONS, STATES, WRITE_ENABLED, serversApi } from "./serversApi.js";

// Why a button is dead, on hover — better than a click that does nothing.
const OFF_HINT = "write access is off in this build";
// The backend sends `controllable` per row and refuses everything else with a
// 403. Greying those buttons out says the same thing without the round trip.
const LOCKED_HINT = "not on SERVERS_CONTROL_ALLOWLIST";

const FILTERS = [
  { key: "all", label: "all" },
  { key: "running", label: "running" },
  { key: "stopped", label: "stopped" },
  { key: "problem", label: "problem" },
];

function uptime(iso) {
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 0) return "—";
  const min = Math.floor(ms / 60000);
  if (min < 60) return `${min} min`;
  const hours = Math.floor(min / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.floor(hours / 24)} d`;
}

function mb(n) {
  return n >= 1024 ? `${(n / 1024).toFixed(1)} GB` : `${n} MB`;
}

// Green to red by load — the same scale for CPU and RAM, so the colour only
// has to be learned once.
function loadColor(percent) {
  if (percent >= 85) return "#fb4934";
  if (percent >= 60) return "#fabd2f";
  return "#b8bb26";
}

export default function ContainerList({ containers, loading, error, onAction, onReload }) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState({}); // id -> action currently running
  const [logsFor, setLogsFor] = useState(null);
  const [logText, setLogText] = useState("");

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return containers.filter((c) => {
      if (q && !`${c.name} ${c.image} ${c.stack}`.toLowerCase().includes(q)) return false;
      if (filter === "running") return c.state === "running";
      if (filter === "stopped") return c.state === "exited" || c.state === "paused";
      if (filter === "problem") return c.state === "unhealthy";
      return true;
    });
  }, [containers, search, filter]);

  async function run(c, which) {
    if (!ACTIONS.includes(which)) return;
    setBusy((v) => ({ ...v, [c.id]: which }));
    try {
      await onAction(c, which);
    } finally {
      setBusy((v) => {
        const { [c.id]: _gone, ...rest } = v;
        return rest;
      });
    }
  }

  async function toggleLogs(c) {
    if (logsFor === c.id) {
      setLogsFor(null);
      return;
    }
    setLogsFor(c.id);
    setLogText("loading …");
    try {
      setLogText(await serversApi.logs(c.id));
    } catch {
      setLogText("Logs unavailable.");
    }
  }

  return (
    <>
      <div className="sv-filter">
        <input
          className="sv-search"
          placeholder="search — name, image, stack …"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search containers"
        />
        {FILTERS.map((f) => (
          <button
            key={f.key}
            className={filter === f.key ? "sv-chip sv-chip-active" : "sv-chip"}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
        <button className="sv-chip" onClick={onReload} disabled={loading}>
          {loading ? "…" : "↻ reload"}
        </button>
      </div>

      <div className="sv-table">
        <div className="sv-headrow">
          <span>name</span>
          <span>image</span>
          <span>state</span>
          <span>uptime</span>
          <span>cpu</span>
          <span>ram</span>
          <span>ports</span>
          <span />
        </div>

        {filtered.length === 0 && (
          <div className="sv-empty">
            {loading
              ? "loading containers …"
              : error
                ? /* A failed request is not an empty result — say which it is. */
                  error
                : containers.length === 0
                  ? "no containers on this host."
                  : "no container matches the filter."}
          </div>
        )}

        {filtered.map((c) => {
          const st = STATES[c.state] ?? STATES.exited;
          const ramPercent = c.ram.limit ? (c.ram.used / c.ram.limit) * 100 : 0;
          const running = busy[c.id];
          const stopped = c.state === "exited";
          const locked = !WRITE_ENABLED || !c.controllable;
          const lockHint = WRITE_ENABLED ? LOCKED_HINT : OFF_HINT;

          return (
            <div key={c.id}>
              <div className="sv-row">
                {/* Flat cells: grouping happens through CSS areas, not through
                    wrappers — otherwise the header no longer lines up. */}
                <div className="sv-name sv-z-name">
                  <span className="sv-dot" style={{ background: st.color }} />
                  <span className="sv-name-text" title={c.name}>
                    {c.name}
                  </span>
                  <span className="sv-stack">{c.stack}</span>
                  <span className="sv-id">{c.id.slice(0, 12)}</span>
                </div>

                <div className="sv-image sv-z-image" title={c.image}>
                  {c.image}
                </div>

                <div className="sv-state sv-z-state" style={{ color: st.color }}>
                  {running ? `${running} …` : st.label}
                </div>

                <div className="sv-cell sv-z-uptime">{uptime(c.since)}</div>

                <div className="sv-cell sv-z-cpu">
                  cpu {c.cpu.toFixed(1)} %
                  <div className="sv-bar">
                    <span
                      style={{ width: `${Math.min(100, c.cpu)}%`, background: loadColor(c.cpu) }}
                    />
                  </div>
                </div>

                <div className="sv-cell sv-z-ram">
                  ram {mb(c.ram.used)}
                  <div className="sv-bar">
                    <span
                      style={{
                        width: `${Math.min(100, ramPercent)}%`,
                        background: loadColor(ramPercent),
                      }}
                    />
                  </div>
                </div>

                <div className="sv-ports sv-z-ports">
                  {c.ports.length
                    ? c.ports.map((p) => `${p.host}→${p.container}`).join("  ")
                    : "no ports"}
                </div>

                <div className="sv-actions sv-z-actions">
                  <button
                    className="sv-btn"
                    onClick={() => run(c, stopped ? "start" : "stop")}
                    disabled={locked || !!running}
                    title={locked ? lockHint : stopped ? "start" : "stop"}
                    aria-label={stopped ? "start" : "stop"}
                  >
                    {stopped ? "▶" : "■"}
                  </button>
                  <button
                    className="sv-btn"
                    onClick={() => run(c, "restart")}
                    disabled={locked || !!running || stopped}
                    title={locked ? lockHint : "restart"}
                    aria-label="restart"
                  >
                    ↻
                  </button>
                  <button
                    className="sv-btn"
                    onClick={() => toggleLogs(c)}
                    title="logs"
                    aria-label="logs"
                  >
                    ≡
                  </button>
                </div>
              </div>

              {logsFor === c.id && <pre className="sv-logs">{logText}</pre>}
            </div>
          );
        })}
      </div>
    </>
  );
}
