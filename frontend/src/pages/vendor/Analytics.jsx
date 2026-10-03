/**
 * Vendor "Overview" - GET /api/v1/vendor/analytics/
 *
 * Payload (VendorAnalyticsView, ORM aggregates over THIS store only):
 *   {currency, total_revenue, total_orders, total_customers,
 *    linked_customers, average_order_value, orders_by_status: {…n}}
 *
 * Notes:
 *   * revenue/AOV EXCLUDE cancelled orders (backend rule);
 *   * orders_by_status is pre-seeded with every status (0 included),
 *     so the breakdown renders all six rows without null checks;
 *   * bar widths are inline styles (dynamic %, layout only - colors stay
 *     in the StatusBadge lookup table, never interpolated utilities).
 */
import {
  ErrorBanner,
  LoadingBlock,
  Money,
  PageHeader,
  StatusBadge,
  cardClass,
} from "../../components/ui";
import useApi from "../../hooks/useApi";

const ORDER_STATUSES = [
  "pending",
  "paid",
  "processing",
  "shipped",
  "delivered",
  "cancelled",
];

function MetricCard({ label, value, hint }) {
  return (
    <div className={`${cardClass} p-5`}>
      <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
        {label}
      </p>
      <p className="mt-2 text-2xl font-bold text-gray-900">{value}</p>
      {hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}

export default function Analytics() {
  const { data, loading, error, reload } = useApi("/vendor/analytics/");

  if (loading) return <LoadingBlock label="Loading analytics…" />;
  if (error) return <ErrorBanner error={error} onRetry={reload} className="p-4" />;
  if (!data) return null;

  const statuses = data.orders_by_status ?? {};
  const total = ORDER_STATUSES.reduce((sum, key) => sum + (statuses[key] ?? 0), 0);
  const max = Math.max(1, ...ORDER_STATUSES.map((key) => statuses[key] ?? 0));

  return (
    <div>
      <PageHeader
        title="Overview"
        subtitle="How your store is doing - this store's orders only."
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Total revenue"
          value={<Money value={data.total_revenue} currency={data.currency} />}
          hint="Excludes cancelled orders"
        />
        <MetricCard
          label="Orders"
          value={data.total_orders}
          hint="Non-cancelled lifetime"
        />
        <MetricCard
          label="Average order"
          value={<Money value={data.average_order_value} currency={data.currency} />}
          hint="Revenue ÷ orders"
        />
        <MetricCard
          label="Customers"
          value={data.total_customers}
          hint={`${data.linked_customers} linked to this store`}
        />
      </div>

      <div className={`mt-6 ${cardClass} p-5`}>
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">Orders by status</h2>
          <span className="text-xs text-gray-400">{total} total</span>
        </div>

        {total === 0 ? (
          <p className="mt-4 text-sm text-gray-500">
            No orders yet. They will show up here as customers check out.
          </p>
        ) : (
          <ul className="mt-4 space-y-3">
            {ORDER_STATUSES.map((key) => {
              const count = statuses[key] ?? 0;
              return (
                <li key={key} className="flex items-center gap-3">
                  <StatusBadge status={key} className="w-24 justify-center" />
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-100">
                    <div
                      className="h-full rounded-full bg-[var(--brand-primary)]"
                      style={{ width: `${(count / max) * 100}%` }}
                    />
                  </div>
                  <span className="w-8 text-right text-sm font-medium text-gray-700">
                    {count}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
