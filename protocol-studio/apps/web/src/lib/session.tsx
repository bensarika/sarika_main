/**
 * Session context: who is signed in, and how (dev vs Google).
 *
 * `SessionProvider` fetches /auth/me once at boot. Pages call `useSession()`;
 * `RequireAuth` / `RequireAdmin` are route guards that redirect to /login.
 */
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { ApiError, auth, type AuthConfig, type User } from "./api";

interface SessionState {
  user: User | null;
  config: AuthConfig | null;
  loading: boolean;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
}

const Ctx = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [me, cfg] = await Promise.all([auth.me().catch((e: unknown) => (e instanceof ApiError && e.status === 401 ? null : Promise.reject(e))), auth.config()]);
      setUser(me?.user ?? null);
      setConfig(cfg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signOut = useCallback(async () => {
    await auth.logout();
    setUser(null);
  }, []);

  return <Ctx.Provider value={{ user, config, loading, refresh, signOut }}>{children}</Ctx.Provider>;
}

export function useSession(): SessionState {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession outside SessionProvider");
  return s;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useSession();
  const loc = useLocation();
  if (loading) return <div className="page muted">Loading…</div>;
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  return <>{children}</>;
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { user } = useSession();
  if (user?.role !== "admin") return <div className="page err">Administrators only.</div>;
  return <>{children}</>;
}
