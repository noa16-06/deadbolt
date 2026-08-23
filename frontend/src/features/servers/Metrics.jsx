const COLOR_OK = "#b8bb26";
const COLOR_WARN = "#fabd2f";
const COLOR_CRITICAL = "#fb4934";

function loadColor(percent) {
  if (percent >= 85) return COLOR_CRITICAL;
  if (percent >= 60) return COLOR_WARN;
  return COLOR_OK;
}

function gb(mb) {
  return `${(mb / 1024).toFixed(1)} GB`;
}

function uptime(seconds) {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  return `${d} days ${h} h`;
}

// Sparkline as inline SVG. A charting library for seven lines would be 60 kB
// for nothing — this is a polyline.
function Spark({ values, color }) {
  if (!values?.length) return null;
  const w = 100;
  const h = 30;
  const max = Math.max(10, ...values);
  const points = values
    .map((v, i) => `${(i / (values.length - 1)) * w},${h - (v / max) * h}`)
    .join(" ");
  return (
    <svg className="sv-spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <polyline points={`0,${h} ${points} ${w},${h}`} fill={color} opacity="0.12" />
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

// A host without a sensor reports no temperature. "null °C" would be a lie
// dressed up as a measurement — a dash is the honest rendering.
function celsius(value) {
  return value == null ? "—" : `${value} °C`;
}

function Row({ label, value }) {
  return (
    <div className="sv-value-row">
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

function Bar({ label, used, total, unit = gb }) {
  const percent = total ? (used / total) * 100 : 0;
  return (
    <div>
      <div className="sv-value-row">
        <span>{label}</span>
        <b>
          {unit(used)} / {unit(total)}
        </b>
      </div>
      <div className="sv-bar" style={{ height: 6, marginTop: 5 }}>
        <span style={{ width: `${Math.min(100, percent)}%`, background: loadColor(percent) }} />
      </div>
    </div>
  );
}

export default function Metrics({ data, loading }) {
  if (!data) {
    return (
      <div className="sv-empty">
        {loading ? "loading metrics …" : "no metrics available."}
      </div>
    );
  }

  const { cpu, gpu, ram, swap, disks, net } = data;
  // gpu is null on a host without an NVIDIA card — the card stays, empty.
  const gpuMemoryPercent = gpu ? (gpu.memory.used / gpu.memory.total) * 100 : 0;

  return (
    <div className="sv-grid">
      {/* ---------------- cpu ---------------- */}
      <section className="sv-card">
        <div className="sv-card-head">
          <span className="sv-card-title">[ cpu ]</span>
          <span className="sv-big" style={{ color: loadColor(cpu.total) }}>
            {cpu.total.toFixed(1)}
            <span className="sv-unit"> %</span>
          </span>
        </div>
        <div className="sv-card-sub" title={cpu.model}>
          {cpu.model}
        </div>

        <Spark values={cpu.history} color={loadColor(cpu.total)} />

        <div className="sv-cores" aria-label={`${cpu.cores.length} cores`}>
          {cpu.cores.map((c, i) => (
            <div className="sv-core" key={i} title={`Core ${i}: ${c} %`}>
              <span style={{ height: `${Math.max(3, c)}%`, background: loadColor(c) }} />
            </div>
          ))}
        </div>

        <div className="sv-values">
          <Row label="cores" value={cpu.cores.length} />
          <Row label="temperature" value={celsius(cpu.temperature)} />
        </div>
      </section>

      {/* ---------------- gpu ---------------- */}
      <section className="sv-card">
        <div className="sv-card-head">
          <span className="sv-card-title">[ gpu ]</span>
          {gpu && (
            <span className="sv-big" style={{ color: loadColor(gpu.usage) }}>
              {gpu.usage.toFixed(1)}
              <span className="sv-unit"> %</span>
            </span>
          )}
        </div>

        {gpu ? (
          <>
            <div className="sv-card-sub" title={gpu.model}>
              {gpu.model}
            </div>

            <Spark values={gpu.history} color={loadColor(gpu.usage)} />

            <div className="sv-values">
              <Bar label="vram" used={gpu.memory.used} total={gpu.memory.total} />
              <Row label="temperature" value={celsius(gpu.temperature)} />
              <Row label="power" value={`${gpu.power.watts} / ${gpu.power.limit} W`} />
              <Row label="vram load" value={`${gpuMemoryPercent.toFixed(0)} %`} />
            </div>
          </>
        ) : (
          <div className="sv-card-sub">no nvidia gpu detected</div>
        )}
      </section>

      {/* ---------------- memory ---------------- */}
      <section className="sv-card">
        <div className="sv-card-head">
          <span className="sv-card-title">[ memory ]</span>
          <span
            className="sv-big"
            style={{ color: loadColor((ram.used / ram.total) * 100) }}
          >
            {((ram.used / ram.total) * 100).toFixed(0)}
            <span className="sv-unit"> %</span>
          </span>
        </div>
        <div className="sv-card-sub">ram and swap</div>
        <div className="sv-values">
          <Bar label="ram" used={ram.used} total={ram.total} />
          <Bar label="swap" used={swap.used} total={swap.total} />
        </div>
      </section>

      {/* ---------------- disks + network ---------------- */}
      <section className="sv-card">
        <div className="sv-card-head">
          <span className="sv-card-title">[ disks ]</span>
        </div>
        <div className="sv-card-sub">
          host {data.host} · up {uptime(data.uptimeSeconds)}
        </div>
        <div className="sv-values">
          {disks.map((d) => (
            <Bar
              key={d.path}
              label={d.path}
              used={d.used}
              total={d.total}
              unit={(v) => `${v} GB`}
            />
          ))}
          <Row label="net in" value={`${net.rxMbit.toFixed(1)} Mbit/s`} />
          <Row label="net out" value={`${net.txMbit.toFixed(1)} Mbit/s`} />
        </div>
      </section>
    </div>
  );
}
