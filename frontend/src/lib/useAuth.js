import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "./api.js";

// One hook for the sign-in state. `checking` is its own state so the app does
// not flash the login form while /me is still in flight.
export function useAuth() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .get("/auth/me")
      .then((u) => !cancelled && setUser(u))
      .catch(() => !cancelled && setUser(null))
      .finally(() => !cancelled && setChecking(false));
    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (username, password, code) => {
    const u = await api.post("/auth/login", { username, password, code });
    setUser(u);
    return u;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.post("/auth/logout", {});
    } finally {
      setUser(null);
    }
  }, []);

  // Called when any request returns 401 — an expired session, for example.
  const sessionLost = useCallback((error) => {
    if (error instanceof ApiError && error.status === 401) {
      setUser(null);
      return true;
    }
    return false;
  }, []);

  return { user, checking, signIn, signOut, sessionLost };
}
