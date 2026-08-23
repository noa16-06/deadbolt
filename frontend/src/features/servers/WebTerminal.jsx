import { useEffect, useRef, useState } from "react";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { MOCK_TERMINAL } from "./serversApi.js";
import { openTerminal } from "./terminalSession.js";

// Gruvbox for xterm — otherwise a garish default terminal sits in the middle
// of the dashboard.
const THEME = {
  background: "#161819",
  foreground: "#ebdbb2",
  cursor: "#fe8019",
  selectionBackground: "#504945",
  black: "#282828",
  red: "#fb4934",
  green: "#b8bb26",
  yellow: "#fabd2f",
  blue: "#83a598",
  magenta: "#d3869b",
  cyan: "#8ec07c",
  white: "#ebdbb2",
  brightBlack: "#665c54",
  brightRed: "#fb4934",
  brightGreen: "#b8bb26",
  brightYellow: "#fabd2f",
  brightBlue: "#83a598",
  brightMagenta: "#d3869b",
  brightCyan: "#8ec07c",
  brightWhite: "#fbf1c7",
};

export default function WebTerminal() {
  const frame = useRef(null);
  const [restart, setRestart] = useState(0);

  useEffect(() => {
    const term = new Terminal({
      fontFamily:
        "'JetBrains Mono', 'Fira Code', ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
      fontSize: 13,
      cursorBlink: true,
      convertEol: false,
      theme: THEME,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(frame.current);

    // fit() reaches for the renderer, which does not exist right after open()
    // — and in StrictMode the terminal is already disposed on the second run.
    // Both have to be caught, otherwise this throws
    // "Cannot read properties of undefined (reading 'dimensions')".
    let alive = true;
    const refit = () => {
      if (!alive) return;
      try {
        fit.fit();
      } catch {
        /* frame has no size yet, or the terminal is already disposed */
      }
    };
    requestAnimationFrame(refit);

    const connection = openTerminal((text) => term.write(text));
    term.onData((d) => connection.send(d));

    // Refit on resize — otherwise output keeps wrapping at the old column count.
    const observer = new ResizeObserver(refit);
    observer.observe(frame.current);

    term.focus();

    return () => {
      alive = false;
      observer.disconnect();
      connection.close();
      term.dispose();
    };
  }, [restart]);

  return (
    <>
      <div className="sv-term-head">
        <div className="sv-term-target">
          <span className="sv-dot" style={{ background: "#b8bb26" }} />
          <span>ubuntu-sandbox</span>
          <span className="sv-stack">ubuntu:24.04</span>
          <span className="sv-id">isolated · no host access</span>
        </div>
        <div className="sv-term-actions">
          <button className="sv-term-btn" onClick={() => setRestart((n) => n + 1)}>
            ↻ new session
          </button>
        </div>
      </div>

      <div className="sv-note">
        This console attaches to a throwaway container of its own, not to the
        host. The target lives in the server configuration and cannot be chosen
        from the browser — otherwise “open terminal” would be an input field you
        type the name of any container into.
        {MOCK_TERMINAL && " Right now a stand-in is running; the backend is still missing."}
      </div>

      <div className="sv-term-frame" ref={frame} />
    </>
  );
}
