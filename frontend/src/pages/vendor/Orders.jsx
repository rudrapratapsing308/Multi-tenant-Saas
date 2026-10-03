/**
 * Vendor orders - list, filter and the fulfilment state machine.
 *
 * Endpoints:
 *   GET   /api/v1/vendor/orders/               (+ ?status=<value> filter)
 *   PATCH /api/v1/vendor/orders/<id>/status/   {status: "..."} -> full order
 *
 * TRANSITIONS mirrors backend Order.TRANSITIONS EXACTLY (orders/models.py):
 *
 *   pending    -> paid | processing | cancelled
 *   paid       -> processing | cancelled
 *   processing -> shipped | cancelled
 *   shipped    -> delivered
 *   delivered  -> (final)      cancelled -> (final)
 *
 * The backend re-validates every jump (400 with "Allowed next: ..." if the
 * UI ever drifts), so this map drives the OPTIONS the merchant SEES, while
 * the server stays the source of truth. PATCH answers with the updated
 * order, which is spliced into local state - no refetch round-trip.
 */
import { Fragment, useState } from "react";
import {
  EmptyState,
  ErrorBanner,
  FormError,
  LoadingBlock,
  Money,
  PageHeader,
  StatusBadge,
  cardClass,
} from "../../components/ui";
import api from "../../api/client";
import useApi, { apiErrorMessage } from "../../hooks/useApi";

export const TRANSITIONS = {
  pending: ["paid", "processing", "cancelled"],
  paid: ["processing", "cancelled"],
  processing: ["shipped", "cancelled"],
  shipped: ["delivered"],
  delivered: [],
  cancelled: [],
};

const STATUS_FILTERS = [
  "pending",
  "paid",
  "processing",
  "shipped",
  "delivered",
  "cancelled",
];

const formatDate = (iso) =>
  new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });

function StatusControls({ order, busy, onAdvance }) {
  const options = TRANSITIONS[order.status] ?? [];

  if (options.length === 0) {
    return <span className="text-xs italic text-gray-400">No further actions</span>;
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {options.map((next) => (
        <button
          key={next}
          type="button"
          disabled={busy}
          onClick={() => onAdvance(order, next)}
          className={
            next === "cancelled"
              ? "rounded-md border border-red-200 bg-white px-2.5 py-1 text-xs font-semibold text-red-600 transition hover:bg-red-50 disabled:opacity-50"
              : "rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs font-semibold text-gray-700 transition hover:bg-gray-50 disabled:opacity-50"
          }
        >
          Mark {next}
        </button>
      ))}
    </div>
  );
}

function OrderDetails({ order }) {
  return (
    <div className="grid gap-6 border-t border-gray-100 bg-gray-50/60 px-4 py-5 sm:grid-cols-2">
      {/* Items */}
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          Items
        </h4>
        <ul className="mt-2 space-y-1.5 text-sm">
          {order.items.map((item) => (
            <li key={item.id} className="flex justify-between gap-3">
              <span className="text-gray-700">
                {item.product_name}
                {item.variant_name ? ` · ${item.variant_name}` : ""}
                {item.sku ? ` (${item.sku})` : ""} × {item.quantity}
              </span>
              <Money
                value={item.line_total}
                currency={order.currency}
                className="shrink-0 font-medium text-gray-900"
              />
            </li>
          ))}
        </ul>
        <div className="mt-3 space-y-1 border-t border-gray-200 pt-2 text-xs text-gray-600">
          <div className="flex justify-between">
            <span>Subtotal</span>
            <Money value={order.subtotal} currency={order.currency} />
          </div>
          {Number(order.discount_amount) > 0 && (
            <div className="flex justify-between text-emerald-600">
              <span>Discount {order.voucher_code ? `(${order.voucher_code})` : ""}</span>
              <Money value={order.discount_amount} currency={order.currency} />
            </div>
          )}
          <div className="flex justify-between font-semibold text-gray-900">
            <span>Total</span>
            <Money value={order.total} currency={order.currency} />
          </div>
        </div>
      </div>

      {/* Shipping + customer */}
      <div className="text-sm">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          Shipping
        </h4>
        <address className="mt-2 not-italic leading-relaxed text-gray-700">
          {order.shipping_name}
          <br />
          {order.shipping_address1}
          {order.shipping_address2 && (
            <>
              <br />
              {order.shipping_address2}
            </>
          )}
          <br />
          {order.shipping_city} {order.shipping_postal_code} ·{" "}
          {order.shipping_country}
          {order.shipping_phone && (
            <>
              <br />
              {order.shipping_phone}
            </>
          )}
        </address>
        {order.customer_email && (
          <p className="mt-2 text-xs text-gray-500">
            Customer: {order.customer_name || "—"} · {order.customer_email}
          </p>
        )}
        {order.notes && (
          <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Note: {order.notes}
          </p>
        )}
      </div>
    </div>
  );
}

export default function Orders() {
  const [status, setStatus] = useState("");
  const [expandedId, setExpandedId] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [actionError, setActionError] = useState(null);

  const { data: orders, setData, loading, error, reload } = useApi(
    "/vendor/orders/",
    { params: status ? { status } : null }
  );

  const advance = async (order, next) => {
    setBusyId(order.id);
    setActionError(null);
    try {
      const { data: updated } = await api.patch(
        `/vendor/orders/${order.id}/status/`,
        { status: next }
      );
      setData((prev) => (prev ?? []).map((row) => (row.id === updated.id ? updated : row)));
    } catch (err) {
      // 400 -> "An order cannot go from 'x' to 'y'. Allowed next: ..."
      setActionError(apiErrorMessage(err, "Could not update the order."));
      reload(); // server state wins if we raced it
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <PageHeader
        title="Orders"
        subtitle="Advance orders through fulfilment: paid → processing → shipped → delivered."
      />

      {/* Status filter chips */}
      <div className="mb-4 flex flex-wrap gap-2">
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

      {actionError && (
        <FormError message={actionError} className="mb-4" />
      )}
      {error && !actionError && (
        <ErrorBanner error={error} onRetry={reload} className="mb-4" />
      )}

      <div className={`${cardClass} overflow-hidden`}>
        {loading ? (
          <LoadingBlock label="Loading orders…" />
        ) : !orders || orders.length === 0 ? (
          <EmptyState
            title={status ? `No ${status} orders` : "No orders yet"}
            body={
              status
                ? "Try another status filter."
                : "Orders placed on your storefront will appear here."
            }
            action={
              status ? (
                <button
                  type="button"
                  onClick={() => setStatus("")}
                  className="text-sm font-semibold text-[var(--brand-primary)] underline"
                >
                  Show all orders
                </button>
              ) : null
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-gray-200 bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-4 py-3 font-medium">Order</th>
                  <th className="px-4 py-3 font-medium">Date</th>
                  <th className="px-4 py-3 font-medium">Customer</th>
                  <th className="px-4 py-3 font-medium">Items</th>
                  <th className="px-4 py-3 font-medium">Total</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {orders.map((order) => {
                  const expanded = expandedId === order.id;
                  const busy = busyId === order.id;
                  return (
                    <Fragment key={order.id}>
                      <tr
                        className={`cursor-pointer transition hover:bg-gray-50 ${expanded ? "bg-gray-50/70" : ""}`}
                        onClick={() => setExpandedId(expanded ? null : order.id)}
                      >
                        <td className="px-4 py-3">
                          <span className="font-semibold text-gray-900">
                            {order.order_number}
                          </span>
                          <span className="ml-2 text-xs text-gray-400">
                            {expanded ? "▲" : "▼"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-600">
                          {formatDate(order.created_at)}
                        </td>
                        <td className="px-4 py-3">
                          <span className="block text-gray-800">
                            {order.customer_name || "Guest"}
                          </span>
                          {order.customer_email && (
                            <span className="block text-xs text-gray-400">
                              {order.customer_email}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-gray-600">
                          {order.items.reduce((sum, item) => sum + item.quantity, 0)}
                        </td>
                        <td className="px-4 py-3 font-medium text-gray-900">
                          <Money value={order.total} currency={order.currency} />
                        </td>
                        <td className="px-4 py-3" onClick={(event) => event.stopPropagation()}>
                          <StatusBadge status={order.status} />
                        </td>
                        <td
                          className="px-4 py-3"
                          onClick={(event) => event.stopPropagation()}
                        >
                          <StatusControls
                            order={order}
                            busy={busy}
                            onAdvance={advance}
                          />
                        </td>
                      </tr>
                      {expanded && (
                        <tr>
                          <td colSpan={7}>
                            <OrderDetails order={order} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
