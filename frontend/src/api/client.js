/**
 * The API transport layer - ONE Axios instance for the whole SPA.
 * Every network call in the frontend goes through `api`.
 *
 * Local dev topology (why the Vite proxy exists)
 * ----------------------------------------------
 *   browser: http://acme.local-saas.com:5173      <- dns_simulator resolves *.local-saas.com
 *       |  same-origin request to /api/...
 *       v
 *   Vite dev server :5173  --(server.proxy)-->  Django :8000
 *
 * Same-origin means no CORS preflights for API calls, and /media + /static
 * are proxied alongside the API so uploaded logos and product images work
 * unchanged (in production a real reverse proxy does exactly this job).
 *
 * Dynamic tenancy
 * ---------------
 * The Host header that reaches Django still says "localhost:5173" (or the
 * storefront hostname when browsing through dns_simulator), so every request
 * ALSO carries:
 *
 *     X-Forwarded-Host: <window.location.hostname>
 *
 * The Django middleware (TENANT_TRUST_X_FORWARDED_HOST=True in development)
 * prefers that header, normalises it (lower-cased, port stripped) and resolves
 * the tenant. In PRODUCTION this header must be set/validated by the reverse
 * proxy, never trusted from the client (see backend base.py).
 *
 * Authentication
 * --------------
 * A request interceptor attaches `Authorization: Bearer <access token>` when
 * a session exists in localStorage. The response interceptor implements the
 * *placeholder* 401 policy until the refresh-token step lands: clear the
 * stored session and send the visitor to their area's login page. Two
 * exceptions keep that from misfiring:
 *   * the credential endpoints themselves - a wrong password must surface as
 *     a form error on the login page, not a redirect,
 *   * requests that never carried a token - an anonymous visitor hitting an
 *     authenticated endpoint has no session to kill (this is what stops the
 *     public storefront from bouncing every guest to /login).
 */
import axios from "axios";

// localStorage keys. Namespaced so two SPAs on localhost never collide.
const TOKEN_KEY = "saas.access";
const REFRESH_KEY = "saas.refresh";
const USER_KEY = "saas.user";

// 401 from these is *the caller's business* (bad credentials / expired form).
const CREDENTIAL_URLS = ["/auth/login", "/auth/register", "/auth/token/"];

// One redirect at a time: parallel 401s (e.g. three tabs-worth of requests)
// must not queue up three full page loads.
let redirecting = false;

/** The tenant this browser tab is looking at (no port - Django normalises). */
export const currentHost = () => window.location.hostname;

// ---------------------------------------------------------------------------
// Session storage - single source of truth for the interceptor AND AuthContext
// ---------------------------------------------------------------------------
export const getAccessToken = () => localStorage.getItem(TOKEN_KEY);
export const getRefreshToken = () => localStorage.getItem(REFRESH_KEY);

export function readStoredUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) ?? "null");
  } catch {
    return null;
  }
}

/** Persist the payload returned by /auth/login/ and /auth/register/. */
export function setSession({ access, refresh, user }) {
  localStorage.setItem(TOKEN_KEY, access);
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function updateStoredUser(user) {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
}

// ---------------------------------------------------------------------------
// Role <-> URL map (roles come from the backend: customer | vendor | super_admin)
// ---------------------------------------------------------------------------
export const ROLE_HOME = Object.freeze({
  customer: "/",
  vendor: "/admin",
  super_admin: "/superadmin",
});

/** Where a visitor of the current area goes to sign in. */
export function loginPathFor(pathname = window.location.pathname) {
  if (pathname.startsWith("/admin")) return "/admin/login";
  if (pathname.startsWith("/superadmin")) return "/superadmin/login";
  return "/login";
}

/** Where a freshly logged-in user of this role lands. */
export const homePathForRole = (role) => ROLE_HOME[role] ?? "/";

// ---------------------------------------------------------------------------
// The instance
// ---------------------------------------------------------------------------
const api = axios.create({
  baseURL: "/api/v1", // proxied by Vite (see vite.config.js)
  timeout: 15000,
});

// -- request: tenant header + bearer token ----------------------------------
api.interceptors.request.use((config) => {
  // Read per request, not per module load: cheap, and correct if the SPA is
  // ever embedded or the page is navigated without a reload.
  config.headers.set("X-Forwarded-Host", currentHost());
  const token = getAccessToken();
  if (token) config.headers.set("Authorization", `Bearer ${token}`);
  return config;
});

// -- response: placeholder 401 policy ----------------------------------------
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;
    const url = error.config?.url ?? "";
    const headers = error.config?.headers;

    // Did THIS request actually present a session? (AxiosHeaders supports
    // case-insensitive .get(); the fallback covers plain objects.)
    const hadSession =
      typeof headers?.get === "function"
        ? Boolean(headers.get("Authorization"))
        : Boolean(headers?.Authorization);

    const isCredentialCall = CREDENTIAL_URLS.some((path) => url.includes(path));

    if (status === 401 && hadSession && !isCredentialCall && !redirecting) {
      redirecting = true;
      clearSession(); // TODO(Step: refresh) - try the refresh token first,
      // then fall back to this. Until then: hard reset of the session. A full
      // navigation is deliberate: every context re-boots with no stale state.
      window.location.assign(loginPathFor());
    }

    return Promise.reject(error);
  }
);

export default api;
