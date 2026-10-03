/**
 * Cart - line items from CartContext in BOTH modes.
 *
 * The two line shapes (see CartContext module doc):
 *   server: {id, product:{id,name,image,price}, variant?, quantity,
 *            unit_price, line_total, available_stock}
 *   guest:  {key, productId, variantId, quantity, name, image, price}
 * They are NORMALISED into one view model below so the JSX has a single
 * code path; mutations still receive the ORIGINAL line object (the context
 * matches server lines by id, guest lines by key).
 *
 * Totals: server subtotal is authoritative; the guest number is an
 * ESTIMATE from snapshot prices and is labelled as such.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ErrorBanner,
  ImagePlaceholder,
  LoadingBlock,
  Money,
  primaryButtonClass,
  secondaryButtonClass,
} from "../../components/ui";
import { useCart } from "../../context/CartContext";
import { useTenant } from "../../context/TenantContext";

function normalize(line, isGuest) {
  if (isGuest) {
    return {
      key: line.key,
      title: line.name ?? `Product #${line.productId}`,
      variantLabel: null,
      image: line.image ?? null,
      href: `/products/${line.productId}`,
      unitPrice: line.price != null ? Number(line.price) : null,
      quantity: line.quantity,
      lineTotal: line.price != null ? Number(line.price) * line.quantity : null,
      maxStock: 999, // guest caps at the backend's own 999 rule
      original: line,
    };
  }
  return {
    key: `server:${line.id}`,
    title: line.product?.name ?? "Product",
    variantLabel: line.variant?.display_name ?? null,
    image: line.product?.image ?? null,
    href: `/products/${line.product?.id}`,
    unitPrice: Number(line.unit_price),
    quantity: line.quantity,
    lineTotal: Number(line.line_total),
    maxStock: line.available_stock,
    original: line,
  };
}

function QtyButton({ label, symbol, disabled, onClick }) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="flex h-8 w-8 items-center justify-center rounded-md border border-gray-300 text-gray-600 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {symbol}
    </button>
  );
}

export default function Cart() {
  const { lines, isGuest, subtotal, itemCount, loading, setQuantity, removeLine } =
    useCart();
  const { store } = useTenant();
  const currency = store?.currency ?? "USD";

  const [busyKey, setBusyKey] = useState(null);
  const [error, setError] = useState(null);

  const view = lines.map((line) => normalize(line, isGuest));

  const changeQty = async (row, next) => {
    if (busyKey) return;
    setBusyKey(row.key);
    setError(null);
    try {
      await setQuantity(row.original, Math.max(0, next));
    } catch (err) {
      setError(err);
    } finally {
      setBusyKey(null);
    }
  };

  if (loading && !lines.length && !isGuest) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
        <LoadingBlock label="Loading your cart…" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
      <h1 className="text-2xl font-bold text-gray-900">
        Your cart
        {itemCount > 0 && (
          <span className="ml-2 text-sm font-normal text-gray-500">
            {itemCount} item{itemCount === 1 ? "" : "s"}
          </span>
        )}
      </h1>

      {error && (
        <ErrorBanner error={error} onRetry={() => setError(null)} className="mt-4" />
      )}

      {view.length === 0 ? (
        <div className="mt-6 rounded-xl border border-dashed border-gray-300 px-6 py-14 text-center">
          <h2 className="text-sm font-semibold text-gray-900">Your cart is empty</h2>
          <p className="mt-1 text-sm text-gray-500">
            Browse the store and add something you like.
          </p>
          <Link to="/" className={`${primaryButtonClass} mt-5`}>
            Start shopping
          </Link>
        </div>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-3">
          {/* Lines */}
            <ul className="space-y-3 lg:col-span-2">
              {view.map((row) => {
                const busy = busyKey === row.key;
                return (
                  <li
                    key={row.key}
                    className={`flex gap-4 rounded-xl border border-gray-200 bg-white p-4 transition ${busy ? "opacity-60" : ""}`}
                  >
                    <Link to={row.href} className="shrink-0">
                      {row.image ? (
                        <img
                          src={row.image}
                          alt={row.title}
                          className="h-20 w-20 rounded-lg object-cover"
                        />
                      ) : (
                        <ImagePlaceholder
                          label={row.title}
                          className="h-20 w-20 rounded-lg"
                        />
                      )}
                    </Link>

                    <div className="flex min-w-0 flex-1 flex-col">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <Link
                            to={row.href}
                            className="block truncate text-sm font-semibold text-gray-900 hover:underline"
                          >
                            {row.title}
                          </Link>
                          {row.variantLabel && (
                            <p className="text-xs text-gray-500">{row.variantLabel}</p>
                          )}
                          {row.unitPrice != null && (
                            <p className="mt-0.5 text-xs text-gray-500">
                              <Money value={row.unitPrice} currency={currency} /> each
                            </p>
                          )}
                        </div>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => changeQty(row, 0)}
                          className="text-xs font-medium text-gray-400 underline transition hover:text-red-600 disabled:opacity-40"
                        >
                          Remove
                        </button>
                      </div>

                      <div className="mt-auto flex items-center justify-between pt-2">
                        <div className="inline-flex items-center gap-1.5">
                          <QtyButton
                            label="decrease quantity"
                            symbol="−"
                            disabled={busy}
                            onClick={() => changeQty(row, row.quantity - 1)}
                          />
                          <span className="w-8 text-center text-sm font-medium text-gray-900">
                            {row.quantity}
                          </span>
                          <QtyButton
                            label="increase quantity"
                            symbol="+"
                            disabled={busy || row.quantity >= row.maxStock}
                            onClick={() => changeQty(row, row.quantity + 1)}
                          />
                          {row.quantity >= row.maxStock && (
                            <span className="ml-1 text-xs text-gray-400">
                              max {row.maxStock}
                            </span>
                          )}
                        </div>
                        {row.lineTotal != null && (
                          <Money
                            value={row.lineTotal}
                            currency={currency}
                            className="text-sm font-semibold text-gray-900"
                          />
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>

          {/* Summary */}
          <aside className="lg:col-span-1">
            <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
              <h2 className="text-sm font-semibold text-gray-900">Order summary</h2>
              <dl className="mt-4 space-y-2 text-sm">
                <div className="flex justify-between text-gray-600">
                  <dt>Subtotal</dt>
                  <dd>
                    <Money value={subtotal} currency={currency} />
                  </dd>
                </div>
                <div className="flex justify-between text-gray-600">
                  <dt>Shipping</dt>
                  <dd className="text-xs">Calculated at checkout</dd>
                </div>
                <div className="flex justify-between border-t border-gray-100 pt-2 text-base font-semibold text-gray-900">
                  <dt>Estimated total</dt>
                  <dd>
                    <Money value={subtotal} currency={currency} />
                  </dd>
                </div>
              </dl>

              <Link to="/checkout" className={`${primaryButtonClass} mt-5 w-full`}>
                Proceed to checkout
              </Link>
              <Link
                to="/"
                className={`${secondaryButtonClass} mt-2 w-full`}
              >
                Keep shopping
              </Link>

              {isGuest && (
                <p className="mt-3 text-center text-xs text-gray-400">
                  Guest cart -{" "}
                  <Link to="/login" className="underline hover:text-gray-600">
                    sign in
                  </Link>{" "}
                  for exact totals and checkout.
                </p>
              )}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
