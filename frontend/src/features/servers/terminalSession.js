// The web terminal's connection.
//
// Important for later: the terminal attaches to ONE container configured on
// the server (the Ubuntu workbench), never to one the client names. The target
// comes from the server configuration — never from a request field. Otherwise
// "open terminal" is a form you type `dashboard-backend` into and end up in
// the backend.
//
// While MOCK_TERMINAL is true a stand-in runs here: a tiny shell that knows a few
// commands. It later gets replaced by a WebSocket to /api/servers/terminal
// sitting on `docker exec -it ubuntu-sandbox bash`.

import { MOCK_TERMINAL } from "./serversApi.js";

const PROMPT = "\x1b[32mroot@ubuntu-sandbox\x1b[0m:\x1b[34m~\x1b[0m# ";

const FILES = {
  "notes.txt": "todo: check backups\ntodo: finish ctf writeup\n",
  "hello.sh": '#!/bin/sh\necho "hi from the sandbox"\n',
};

function mockReply(line) {
  const [cmd, ...rest] = line.trim().split(/\s+/);
  const arg = rest.join(" ");

  switch (cmd) {
    case "":
      return "";
    case "help":
      return [
        "Stand-in — the real terminal arrives with the backend.",
        "known: help, ls, cat, pwd, whoami, uname, date, echo, id, clear",
      ].join("\r\n");
    case "ls":
      return Object.keys(FILES).join("  ");
    case "cat":
      return FILES[arg] !== undefined
        ? FILES[arg].replace(/\n/g, "\r\n").trimEnd()
        : `cat: ${arg || "?"}: No such file or directory`;
    case "pwd":
      return "/root";
    case "whoami":
      return "root";
    case "id":
      return "uid=0(root) gid=0(root) groups=0(root)";
    case "uname":
      return "Linux ubuntu-sandbox 6.8.0 #1 SMP aarch64 GNU/Linux";
    case "date":
      return new Date().toString();
    case "echo":
      return arg;
    case "docker":
    case "sudo":
      return `\x1b[33m${cmd}: not available in the sandbox — it deliberately has no way out.\x1b[0m`;
    default:
      return `${cmd}: command not found`;
  }
}

/**
 * Open a terminal session.
 *
 * @param {(text: string) => void} onOutput called with raw terminal text
 * @returns {{ send(text: string): void, close(): void }}
 */
export function openTerminal(onOutput) {
  if (!MOCK_TERMINAL) {
    const ws = new WebSocket(
      `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/servers/terminal`
    );
    ws.onmessage = (e) => onOutput(e.data);
    ws.onerror = () => onOutput("\r\n\x1b[31mConnection failed.\x1b[0m\r\n");
    ws.onclose = () => onOutput("\r\n\x1b[33mSession ended.\x1b[0m\r\n");
    return {
      send: (text) => ws.readyState === WebSocket.OPEN && ws.send(text),
      close: () => ws.close(),
    };
  }

  // ---- stand-in ----
  let buffer = "";
  let open = true;

  queueMicrotask(() => {
    onOutput(
      "\x1b[90mUbuntu 24.04 LTS (stand-in — backend still missing)\x1b[0m\r\n" +
        '\x1b[90m"help" lists the known commands.\x1b[0m\r\n\r\n' +
        PROMPT
    );
  });

  return {
    send(data) {
      if (!open) return;
      for (const ch of data) {
        if (ch === "\r") {
          const line = buffer;
          buffer = "";
          onOutput("\r\n");
          if (line.trim() === "clear") {
            onOutput("\x1b[2J\x1b[H");
          } else {
            const reply = mockReply(line);
            if (reply) onOutput(reply + "\r\n");
          }
          onOutput(PROMPT);
        } else if (ch === "\x7f") {
          if (buffer.length) {
            buffer = buffer.slice(0, -1);
            onOutput("\b \b");
          }
        } else if (ch >= " ") {
          buffer += ch;
          onOutput(ch);
        }
      }
    },
    close() {
      open = false;
    },
  };
}
