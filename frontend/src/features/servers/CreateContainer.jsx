import { useState } from "react";

// Ports as one line, the way `docker run -p` writes them: "8010:8000",
// optionally with a protocol, several separated by commas or spaces.
//
// Parsed here rather than sent as a string: the backend takes a list of three
// numbers and never a text it has to take apart. What this function is for is
// telling the user which entry is wrong before a request goes out — everything
// it accepts is checked again on the other side.
const PORT_PATTERN = /^(\d+):(\d+)(?:\/(tcp|udp))?$/;

export function parsePorts(text) {
  const entries = text.split(/[,\s]+/).filter(Boolean);
  return entries.map((entry) => {
    const match = PORT_PATTERN.exec(entry);
    if (!match) {
      throw new Error(`Port "${entry}" — expected host:container, e.g. 8010:8000`);
    }
    const [host, container] = [Number(match[1]), Number(match[2])];
    if (host < 1024 || host > 65535) {
      throw new Error(`Host port ${host} — 1024 and above, 80/443 belong to Caddy`);
    }
    if (container < 1 || container > 65535) {
      throw new Error(`Container port ${container} is not a port`);
    }
    return { host, container, protocol: match[3] ?? "tcp" };
  });
}

// One KEY=value per line. The value may contain "=" — only the first one
// separates, otherwise no connection string would survive this.
export function parseEnv(text) {
  const env = {};
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const at = trimmed.indexOf("=");
    if (at < 1) {
      throw new Error(`Environment line "${trimmed}" — expected NAME=value`);
    }
    env[trimmed.slice(0, at).trim()] = trimmed.slice(at + 1);
  }
  return env;
}

const EMPTY = { name: "", image: "", ports: "", env: "" };

export default function CreateContainer({ onCreate }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  function close() {
    setOpen(false);
    setForm(EMPTY);
    setError(null);
  }

  async function submit(e) {
    e.preventDefault();
    setError(null);

    let spec;
    try {
      spec = {
        name: form.name.trim(),
        image: form.image.trim(),
        ports: parsePorts(form.ports),
        env: parseEnv(form.env),
      };
    } catch (err) {
      // A typo in the port line is not worth a round trip.
      setError(err.message);
      return;
    }

    setBusy(true);
    try {
      await onCreate(spec);
      close();
    } catch (err) {
      // The backend says which list refused and why ("… not on
      // SERVERS_IMAGE_ALLOWLIST"). That sentence is the whole answer to the
      // question "why did this not work", so it is shown as it arrived.
      setError(err?.message || "Creating the container failed.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button className="sv-chip sv-create-open" onClick={() => setOpen(true)}>
        + new container
      </button>
    );
  }

  return (
    <form className="sv-create" onSubmit={submit}>
      <div className="sv-create-head">new container</div>

      <label className="sv-field">
        <span className="sv-field-label">name</span>
        <input
          className="sv-input"
          value={form.name}
          onChange={set("name")}
          placeholder="paperless"
          autoFocus
          required
        />
      </label>

      <label className="sv-field">
        <span className="sv-field-label">image</span>
        <input
          className="sv-input"
          value={form.image}
          onChange={set("image")}
          placeholder="paperless:2.11 — tag required"
          required
        />
      </label>

      <label className="sv-field">
        <span className="sv-field-label">ports</span>
        <input
          className="sv-input"
          value={form.ports}
          onChange={set("ports")}
          placeholder="8010:8000, 5433:5432/tcp — optional"
        />
      </label>

      <label className="sv-field">
        <span className="sv-field-label">env</span>
        <textarea
          className="sv-input sv-textarea"
          value={form.env}
          onChange={set("env")}
          rows={3}
          placeholder={"PAPERLESS_URL=https://paperless.example\nTZ=Europe/Berlin"}
        />
      </label>

      <p className="sv-field-hint">
        Only names on <code>SERVERS_CONTROL_ALLOWLIST</code> and images on{" "}
        <code>SERVERS_IMAGE_ALLOWLIST</code> are accepted, and the image has to be
        on the host already — the dashboard does not pull. The container is created
        without volumes, without host network and unprivileged; that is not
        configurable here on purpose.
      </p>

      {error && <div className="sv-create-error">{error}</div>}

      <div className="sv-create-actions">
        <button className="sv-chip sv-chip-active" type="submit" disabled={busy}>
          {busy ? "creating …" : "create"}
        </button>
        <button className="sv-chip" type="button" onClick={close} disabled={busy}>
          cancel
        </button>
      </div>
    </form>
  );
}
