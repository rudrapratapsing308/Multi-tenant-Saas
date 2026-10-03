/**
 * AuthContext - session lifecycle for all three roles.
 *
 *   login(email, password)   POST /auth/login/   -> stores JWTs + user
 *   register(fields)         POST /auth/register/-> stores JWTs + user
 *   logout()                 clears localStorage + state
 *
 * Both credential responses share one backend shape:
 *     {access, refresh, role: "customer"|"vendor"|"super_admin", user: {...}}
 * Tokens + user go to localStorage (via client.js setSession) so a page
 * reload survives; `role` drives ProtectedRoute and the post-login redirect
 * (homePathForRole), never hard-coded per page.
 *
 * Boot: if an access token exists, GET /auth/me/ revalidates it and returns
 * the FRESH user (role may have changed server-side; a banned user comes back
 * 401 -> the client.js interceptor clears the session). `status` starts at
 * "loading" in that case so routes can wait instead of flashing the login
 * page at an authenticated vendor.
 *
 * Token refresh: NOT implemented yet (placeholder policy lives in client.js).
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import api, {
  clearSession,
  getAccessToken,
  readStoredUser,
  setSession,
  updateStoredUser,
} from "../api/client";

const AuthContext = createContext(null);

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export function AuthProvider({ children }) {
  const hasToken = Boolean(getAccessToken());
  const [user, setUser] = useState(() => (hasToken ? readStoredUser() : null));
  const [status, setStatus] = useState(() =>
    hasToken ? "loading" : "anonymous"
  ); // loading | authenticated | anonymous

  // Rehydrate/refresh the identity after a reload.
  useEffect(() => {
    if (!getAccessToken()) return;
    let cancelled = false;

    api
      .get("/auth/me/")
      .then(({ data }) => {
        if (cancelled) return;
        setUser(data);
        updateStoredUser(data);
        setStatus("authenticated");
      })
      .catch(() => {
        if (cancelled) return;
        // A dead session was already cleared + redirected by the interceptor;
        // any OTHER failure (network blip) keeps the cached identity so the
        // shell can still render - the next request will settle it.
        if (getAccessToken()) {
          setUser(readStoredUser());
          setStatus("authenticated");
        } else {
          setUser(null);
          setStatus("anonymous");
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email, password) => {
    const { data } = await api.post("/auth/login/", { email, password });
    setSession(data);
    setUser(data.user);
    setStatus("authenticated");
    // The caller routes by data.role (customer -> /, vendor -> /admin,
    // super_admin -> /superadmin); the context never navigates itself.
    return data;
  }, []);

  const register = useCallback(async (fields) => {
    const { data } = await api.post("/auth/register/", fields);
    setSession(data);
    setUser(data.user);
    setStatus("authenticated");
    return data;
  }, []);

  const logout = useCallback(() => {
    clearSession();
    setUser(null);
    setStatus("anonymous");
  }, []);

  const value = useMemo(
    () => ({
      user,
      status,
      role: user?.role ?? null,
      isAuthenticated: status === "authenticated" && Boolean(user),
      isCustomer: user?.role === "customer",
      isVendor: user?.role === "vendor",
      isSuperAdmin: user?.role === "super_admin",
      login,
      register,
      logout,
    }),
    [user, status, login, register, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
