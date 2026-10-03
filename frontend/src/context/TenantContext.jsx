/**
 * TenantContext - boots the storefront and owns its branding.
 *
 * On mount it calls GET /api/v1/storefront/init/ exactly once. The backend
 * middleware has already turned X-Forwarded-Host into a tenant (or answered
 * a JSON error), so this provider simply:
 *
 *   * stores {store, brand, theme, banners} in state,
 *   * reflects the brand on the DOCUMENT (title, favicon) and the theme on
 *     CSS variables (--brand-primary / --brand-secondary / --brand-accent),
 *   * exposes an `error` state for the two "no storefront" outcomes so the
 *     shell can render a dedicated screen instead of a broken page:
 *         store_not_found   -> "this store does not exist"
 *         store_unavailable -> "this store is suspended/blocked" (403)
 *         network_unreachable -> API down (Django not running)
 *
 * Rendering rule for the whole app (see App.jsx): while `status ===
 * "loading"` show the splash, on "error" show the store screen, otherwise
 * render the router. Consumers never have to null-check the boot.
 */
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import api, { currentHost } from "../api/client";

const TenantContext = createContext(null);

export function useTenant() {
  const ctx = useContext(TenantContext);
  if (!ctx) throw new Error("useTenant must be used inside <TenantProvider>");
  return ctx;
}

// Mirrors DEFAULT_THEME in backend/apps/storefront/models.py - only visible
// for the split second before /storefront/init/ resolves (and on API failure).
const FALLBACK_THEME = Object.freeze({
  primary_color: "#111827",
  secondary_color: "#6b7280",
  accent_color: "#f59e0b",
});

/** Reflect one store's brand on the document. Runs once per boot. */
function applyBranding(brand, theme) {
  if (brand?.brand_name) document.title = brand.brand_name;

  if (brand?.favicon_url) {
    let link = document.querySelector('link[rel~="icon"]');
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      document.head.appendChild(link);
    }
    link.href = brand.favicon_url;
  }

  const root = document.documentElement.style;
  root.setProperty("--brand-primary", theme.primary_color);
  root.setProperty("--brand-secondary", theme.secondary_color);
  root.setProperty("--brand-accent", theme.accent_color);
}

export function TenantProvider({ children }) {
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const { data } = await api.get("/storefront/init/");
        if (cancelled) return;
        setPayload(data);
        applyBranding(data.brand, data.theme ?? FALLBACK_THEME);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        // The middleware and the init view both answer JSON with an `error`
        // machine code (store_not_found / store_unavailable), so the screen
        // never has to parse prose - it switches on the code.
        const res = err.response;
        setError({
          status: res?.status ?? 0,
          code: res?.data?.error ?? (res ? "http_error" : "network_unreachable"),
          detail:
            res?.data?.detail ??
            "The API did not answer. Is Django running on :8000?",
          host: res?.data?.host ?? currentHost(),
        });
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true; // StrictMode's second mount must not double-apply
    };
  }, []);

  const value = useMemo(
    () => ({
      status,
      loading: status === "loading",
      ready: status === "ready",
      error, // null until boot fails; see module doc for {code, detail, host}
      store: payload?.store ?? null,
      brand: payload?.brand ?? null,
      theme: payload?.theme ?? FALLBACK_THEME,
      banners: payload?.banners ?? [],
      host: payload?.store?.host ?? currentHost(),
    }),
    [status, error, payload]
  );

  return <TenantContext.Provider value={value}>{children}</TenantContext.Provider>;
}
