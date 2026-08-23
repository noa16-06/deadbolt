import { useCallback, useEffect, useState } from "react";
import ContainerList from "./ContainerList.jsx";
import Metrics from "./Metrics.jsx";
import WebTerminal from "./WebTerminal.jsx";
import { WRITE_ENABLED, serversApi } from "./serversApi.js";
import "./servers.css";

const TABS = [
  { key: "containers", label: "containers" },
  { key: "metrics", label: "metrics" },
  { key: "terminal", label: "terminal" },
];

const METRICS_INTERVAL = 5000;

export default function ServerManager({ onSessionLost }) {
  const [tab, setTab] = useState("containers");
  const [containers, setContainers] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const report = useCallback(
    (err) => {
      if (onSessionLost?.(err)) return;
      // The backend says *why* ("Docker not reachable at …"). Swallowing that
      // and printing something generic makes the failure harder to fix.
      setError(err?.message || "Server data unreachable.");
    },
    [onSessionLost]
  );

  const loadContainers = useCallback(async () => {
    setLoading(true);
    try {
      setContainers(await serversApi.containers());
      setError(null);
    } catch (err) {
      report(err);
    } finally {
      setLoading(false);
    }
  }, [report]);

  useEffect(() => {
    loadContainers();
  }, [loadContainers]);

  // Only poll metrics while that tab is open — polling every 5 s in the
  // background while someone types in the terminal is wasted work.
  useEffect(() => {
    if (tab !== "metrics") return;
    let cancelled = false;

    async function fetchMetrics() {
      try {
        const d = await serversApi.metrics();
        if (!cancelled) {
          setMetrics(d);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) report(err);
      }
    }

    fetchMetrics();
    const timer = setInterval(fetchMetrics, METRICS_INTERVAL);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [tab, report]);

  async function runAction(c, which) {
    try {
      await serversApi.action(c.id, which);
      // Optimistic: the new state follows from the action.
      const newState = which === "stop" ? "exited" : "running";
      setContainers((list) =>
        list.map((x) =>
          x.id === c.id
            ? {
                ...x,
                state: newState,
                since: which === "stop" ? x.since : new Date().toISOString(),
              }
            : x
        )
      );
      setError(null);
    } catch (err) {
      report(err);
      loadContainers(); // restore the real state
    }
  }

  const running = containers.filter((c) => c.state === "running").length;

  return (
    <div className="sv">
      <nav className="sv-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={tab === t.key ? "sv-tab sv-tab-active" : "sv-tab"}
            onClick={() => setTab(t.key)}
          >
            {t.label}
            {t.key === "containers" && containers.length > 0 && (
              <span className="sv-tab-count">
                {running}/{containers.length}
              </span>
            )}
          </button>
        ))}
      </nav>

      <div className="sv-content">
        <div className="sv-head">
          <span>
            [ {tab} — {metrics?.host ?? "homelab"} ]
          </span>
          <span className="sv-head-right">
            {error ? <span style={{ color: "#fb4934" }}>{error}</span> : null}
          </span>
        </div>

        {!WRITE_ENABLED && tab === "containers" && (
          <div className="sv-note">
            Containers, metrics and logs are live. Start, stop and restart are
            not: the backend has no action endpoint yet on purpose. A restart
            button reachable from the internet needs TOTP and the login rate
            limit first — see <code>docs/security.md</code>.
          </div>
        )}

        {tab === "containers" && (
          <ContainerList
            containers={containers}
            loading={loading}
            error={error}
            onAction={runAction}
            onReload={loadContainers}
          />
        )}
        {tab === "metrics" && <Metrics data={metrics} loading={!metrics} />}
        {tab === "terminal" && <WebTerminal />}
      </div>
    </div>
  );
}
