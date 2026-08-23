import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Shell from "./components/Shell.jsx";
import Login from "./features/auth/Login.jsx";
import DayPlan from "./features/planner/DayPlan.jsx";
import ServerManager from "./features/servers/ServerManager.jsx";
import { useAuth } from "./lib/useAuth.js";
import { MONO, colors } from "./theme/colors.js";

export default function App() {
  const { user, checking, signIn, signOut, sessionLost } = useAuth();

  // Wait for /auth/me first, otherwise the login form flashes on every reload.
  if (checking) {
    return <div style={loadingStyle}>checking sign-in …</div>;
  }

  if (!user) {
    return <Login onSignIn={signIn} />;
  }

  return (
    <BrowserRouter>
      {/* key={user.id}: after a user switch everything reloads instead of
          showing the previous user's data. */}
      {/* No sign-out while the login is switched off — it would drop into a
          form that nothing checks and that a reload walks straight past. */}
      <Shell
        key={user.id}
        user={user}
        onSignOut={user.authDisabled ? null : signOut}
      >
        <Routes>
          <Route path="/planner" element={<DayPlan onSessionLost={sessionLost} />} />
          <Route path="/servers" element={<ServerManager onSessionLost={sessionLost} />} />
          <Route path="*" element={<Navigate to="/planner" replace />} />
        </Routes>
      </Shell>
    </BrowserRouter>
  );
}

const loadingStyle = {
  fontFamily: MONO,
  background: colors.bg,
  color: colors.textMuted,
  minHeight: "100vh",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontSize: 13,
};
