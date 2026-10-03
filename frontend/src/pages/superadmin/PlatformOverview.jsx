/**
 * Super admin console - platform overview.
 *
 * Endpoints (tenant-EXEMPT, IsSuperAdmin role gate):
 *   GET   /api/v1/superadmin/businesses/            (+ ?status= filter)
 *   PATCH /api/v1/superadmin/businesses/<id>/status/ {status: "..."}
 *
 * Business payload (BusinessSerializer, metrics annotated in SQL):
 *   {id, name, slug, status, contact_email, currency, owner,
 *    owner_email, primary_domain, revenue, order_count,
 *    customer_count, created_at}
 *
 * The Suspend/Activate toggle is THE switch behind the Module-3
 * middleware: anything but `active` makes that store's storefront and API
 * answer 403 `store_unavailable` on the very next request - hence the
 * confirmation before suspending. Statuses: active | pending | suspended
 * | blocked; anything non-active is offered "Activate".
 *
 * This page renders WITHOUT the storefront layout on purpose: the tenant
 * boot may have failed on this host (bad domain) while the platform API -
 * which is tenant-exempt - still works, so the console must not depend on
 * TenantContext.
 */
import { useState } from "react";
import {
  EmptyState,
  ErrorBanner,
  FormError,
  LoadingBlock,
  Money,
  StatusBadge,
  cardClass,
} from "../../components/ui";
import { useAuth } from "../../context/AuthContext";
import api from "../../api/client";
import useApi, { apiErrorMessage } from "../../hooks/useApi";

const STATUS_FILTERS = ["active", "pending", "suspended", "blocked"];

function MetricCard({ label, value }) {
  return (
    <div className={`${cardClass} p-5`}>
      <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
        {label}
      </p>
      <p className="mt-2 text-2xl font-bold text-gray-900">{value}</p>
    </div>
  );
}

export default function PlatformOverview() {
  const { user, logout } = useAuth();
  const [status, setStatus] = useState("");
  const [busyId, setBusyId] = useState(null);
  const [banner, setBanner] = useState(null);

  const { data: businesses, setData, loading, error, reload } = useApi(
    "/superadmin/businesses/",
    { params: status ? { status } : null }
  );

  const toggleStatus = async (business) => {
    const target = business.status === "active" ? "suspended" : "active";

    if (target === "suspended") {
      const ok = window.confirm(
        `Suspend "${business.name}"?\n\nIts storefront and API will answer 403 "store unavailable" immediately.`
      );
      if (!ok) return;
    }

    setBusyId(business.id);
    setBanner(null);
    try {
      const { data: updated } = await api.patch(
        `/superadmin/businesses/${business.id}/status/`,
        { status: target }
      );
      setData((prev) =>
        (prev ?? []).map((row) => (row.id === updated.id ? updated : row))
      );
    } catch (err) {
      setBanner(apiErrorMessage(err, "Could not change the store status."));
    } finally {
      setBusyId(null);
    }
  };

  const rows = businesses ?? [];
  const activeCount = rows.filter((b) => b.status === "active").length;
  const suspendedCount = rows.filter((b) => b.status === "suspended").length;
  const totalOrders = rows.reduce((sum, b) => sum + (b.order_count ?? 0), 0);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Console topbar (standalone - no tenant chrome) */}
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6">
          <div>
            <h1 className="text-lg font-bold text-gray-900">Platform console</h1>
            <p className="text-xs text-gray-400">Multi-store administration</p>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="hidden text-gray-500 sm:block">{user?.email}</span>
            <button
              type="button"
              onClick={logout}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold text-gray-900">Stores</h2>
            <p className="mt-1 text-sm text-gray-500">
              Every business on the platform - suspend one and its storefront
              stops answering instantly.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setStatus("")}
              className={`rounded-full px-3.5 py-1.5 text-sm font-medium transition ${
                status === ""
                  ? "bg-gray-900 text-white"
                  : "bg-white text-gray-600 ring-1 ring-inset ring-gray-200 hover:bg-gray-50"
              }`}
            >
              All
            </button>
            {STATUS_FILTERS.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setStatus((prev) => (prev === value ? "" : value))}
                className={`rounded-full px-3.5 py-1.5 text-sm font-medium capitalize transition ${
                  status === value
                    ? "bg-gray-900 text-white"
                    : "bg-white text-gray-600 ring-1 ring-inset ring-gray-200 hover:bg-gray-50"
                }`}
              >
                {value}
              </button>
            ))}
          </div>
        </div>

        {banner && <FormError message={banner} className="mb-4" />}

        <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label={status ? `Stores (${status})` : "Stores"} value={loading ? "…" : rows.length} />
          <MetricCard label="Active" value={loading ? "…" : activeCount} />
          <MetricCard label="Suspended" value={loading ? "…" : suspendedCount} />
          <MetricCard label="Orders in view" value={loading ? "…" : totalOrders} />
        </div>

        <div className={`${cardClass} overflow-hidden`}>
          {loading ? (
            <LoadingBlock label="Loading stores…" />
          ) : error ? (
            <ErrorBanner error={error} onRetry={reload} className="m-4" />
          ) : rows.length === 0 ? (
            <EmptyState
              title={status ? `No ${status} stores` : "No stores yet"}
              body="Businesses appear here as soon as a vendor registers."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-left text-sm">
                <thead className="border-b border-gray-200 bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
                  <tr>
                    <th className="px-4 py-3 font-medium">Store</th>
                    <th className="px-4 py-3 font-medium">Domain</th>
                    <th className="px-4 py-3 font-medium">Owner</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Revenue</th>
                    <th className="px-4 py-3 font-medium">Orders</th>
                    <th className="px-4 py-3 font-medium">Customers</th>
                    <th className="px-4 py-3 text-right font-medium">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {rows.map((business) => {
                    const suspend = business.status === "active";
                    const busy = busyId === business.id;
                    return (
                      <tr key={business.id} className="transition hover:bg-gray-50/70">
                        <td className="px-4 py-3">
                          <span className="block font-medium text-gray-900">
                            {business.name}
                          </span>
                          <span className="block text-xs text-gray-400">
                            {business.slug} · since{" "}
                            {new Date(business.created_at).toLocaleDateString()}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          {business.primary_domain ? (
                            <span className="font-mono text-xs text-gray-600">
                              {business.primary_domain}
                            </span>
                          ) : (
                            <span className="text-gray-300">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-gray-600">
                          {business.owner_email ?? "—"}
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge status={business.status} />
                        </td>
                        <td className="px-4 py-3 font-medium text-gray-900">
                          <Money
                            value={business.revenue}
                            currency={business.currency}
                          />
                        </td>
                        <td className="px-4 py-3 text-gray-600">
                          {business.order_count}
                        </td>
                        <td className="px-4 py-3 text-gray-600">
                          {business.customer_count}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => toggleStatus(business)}
                            className={
                              suspend
                                ? "rounded-md border border-red-200 bg-white px-3 py-1.5 text-xs font-semibold text-red-600 transition hover:bg-red-50 disabled:opacity-50"
                                : "rounded-md border border-emerald-200 bg-white px-3 py-1.5 text-xs font-semibold text-emerald-600 transition hover:bg-emerald-50 disabled:opacity-50"
                            }
                          >
                            {busy
                              ? "Saving…"
                              : suspend
                                ? "Suspend"
                                : "Activate"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <p className="mt-4 text-xs text-gray-400">
          Customers count = distinct buyers with non-cancelled orders ·
          Revenue excludes cancelled orders · totals shown per store.
        </p>
      </main>
    </div>
  );
}
