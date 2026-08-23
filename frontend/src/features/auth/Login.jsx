import { useState } from "react";
import { MONO, colors } from "../../theme/colors.js";

export default function Login({ onSignIn }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSignIn(username, password);
    } catch (err) {
      // Deliberately the same message for a wrong user and a wrong password —
      // otherwise the form reveals which usernames exist.
      setError(
        err.status === 401 ? "Wrong username or password" : "Server unreachable"
      );
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={S.wrap}>
      <form style={S.card} onSubmit={submit}>
        <div style={S.head}>
          <span style={S.prompt}>~/login</span>
          <span style={S.title}>HOMELAB DASHBOARD</span>
        </div>

        <label style={S.label}>
          username
          <input
            style={S.input}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
          />
        </label>

        <label style={S.label}>
          password
          <input
            style={S.input}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>

        <button style={{ ...S.button, opacity: busy ? 0.5 : 1 }} disabled={busy}>
          {busy ? "checking …" : "sign in"}
        </button>

        <div style={S.error}>{error || " "}</div>
      </form>
    </div>
  );
}

const S = {
  wrap: {
    fontFamily: MONO,
    background: colors.bg,
    color: colors.text,
    minHeight: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 20,
  },
  card: {
    background: colors.bgAlt,
    border: `1px solid ${colors.border}`,
    borderRadius: 8,
    padding: 24,
    width: "100%",
    maxWidth: 340,
    display: "flex",
    flexDirection: "column",
    gap: 14,
  },
  head: { display: "flex", alignItems: "center", gap: 10, fontSize: 12, marginBottom: 4 },
  prompt: { color: colors.green },
  title: { color: colors.orange, letterSpacing: 1, fontWeight: 600 },
  label: {
    display: "flex",
    flexDirection: "column",
    gap: 5,
    fontSize: 11,
    color: colors.textMuted,
  },
  input: {
    fontFamily: MONO,
    background: colors.bg,
    border: `1px solid ${colors.borderLight}`,
    borderRadius: 4,
    color: colors.text,
    fontSize: 13,
    padding: "0 10px",
    minHeight: 48, // WCAG 2.5.8 — otherwise 33px tall on a phone
    boxSizing: "border-box",
    width: "100%",
  },
  button: {
    fontFamily: MONO,
    background: "transparent",
    border: `1px solid ${colors.orange}`,
    borderRadius: 4,
    color: colors.orange,
    fontSize: 13,
    padding: "0 10px",
    minHeight: 48,
    boxSizing: "border-box",
    cursor: "pointer",
    marginTop: 4,
  },
  error: { color: colors.red, fontSize: 11, minHeight: 14, textAlign: "center" },
};
