/**
 * Non-page screens shared by App.jsx and ProtectedRoute.jsx:
 *
 *   SplashScreen        - while tenant boot or auth rehydration is pending
 *   StoreNotFoundScreen - TenantContext.status === "error" (switches on the
 *                         backend's machine code: store_not_found /
 *                         store_unavailable / network_unreachable)
 *
 * These are shell infrastructure, not product pages - deliberately plain.
 */
import { Link } from "react-router-dom";
import { useTenant } from "../context/TenantContext";

export function SplashScreen({ label = "Loading…" }) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-4 bg-white">
      <div
        className="h-10 w-10 animate-spin rounded-full border-4 border-gray-200 border-t-[var(--brand-primary)]"
        aria-hidden="true"
      />
      <p className="text-sm text-gray-500">{label}</p>
    </div>
  );
}

const SCREENS = {
  store_not_found: {
    title: "Store does not exist",
    body: "There is no storefront registered for this address. Check the URL, or ask the merchant to connect their domain.",
  },
  store_unavailable: {
    title: "Store temporarily unavailable",
    body: "This store has been suspended by the platform. If you are the owner, contact support.",
  },
  network_unreachable: {
    title: "Cannot reach the server",
    body: "The API did not answer. Is the Django dev server running on port 8000?",
  },
  http_error: {
    title: "Storefront unavailable",
    body: "Something went wrong while loading this store.",
  },
};

export function StoreErrorScreen() {
  const { error } = useTenant();
  const screen = SCREENS[error?.code] ?? SCREENS.http_error;

  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-3 bg-gray-50 px-6 text-center">
      <h1 className="text-2xl font-semibold text-gray-900">{screen.title}</h1>
      <p className="max-w-md text-sm text-gray-600">{screen.body}</p>
      {error?.host && (
        <p className="font-mono text-xs text-gray-400">
          {error.host}
          {error.status ? ` · HTTP ${error.status}` : ""}
        </p>
      )}
      {error?.code !== "network_unreachable" && (
        <Link
          to="/superadmin/login"
          className="mt-2 text-xs text-gray-400 underline hover:text-gray-600"
        >
          Platform console
        </Link>
      )}
    </div>
  );
}
