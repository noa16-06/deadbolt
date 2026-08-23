import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import "./shell.css";

const SECTIONS = [
  { path: "/planner", label: "planner" },
  { path: "/servers", label: "servers" },
];

export default function Shell({ user, onSignOut, children }) {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30000);
    return () => clearInterval(t);
  }, []);

  const time = now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const date = now.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });

  return (
    <div className="shell">
      <header className="shell-header">
        <div className="shell-brand">
          <span className="shell-prompt">~/homelab</span>
          <span className="shell-title">DASHBOARD</span>
        </div>

        <nav className="shell-nav">
          {SECTIONS.map((s) => (
            <NavLink
              key={s.path}
              to={s.path}
              className={({ isActive }) =>
                isActive ? "shell-nav-link shell-nav-active" : "shell-nav-link"
              }
            >
              {s.label}
            </NavLink>
          ))}
        </nav>

        <div className="shell-right">
          <span>
            {time} · {date}
          </span>
          {user && (
            <>
              <span className="shell-sep">|</span>
              <span className="shell-user">{user.username}</span>
              <button className="shell-logout" onClick={onSignOut}>
                sign out
              </button>
            </>
          )}
        </div>
      </header>

      <main className="shell-content">{children}</main>
    </div>
  );
}
