/**
 * Checkout - POST /api/v1/orders/checkout/
 *
 * Verified payload shape (CheckoutSerializer):
 *   {
 *     shipping: {full_name, address1, address2?, city, postal_code,
 *                country: "XX"  <- 2-letter ISO, uppercased here too,
 *                phone?},
 *     voucher_code?: ""   (trimmed + uppercased; backend normalises again),
 *     notes?: "",
 *     cart_id?: omitted -> the server resolves the caller's own cart
 *   }
 * Responses:
 *   201 Order (order_number, status=pending, totals, items...) -> success screen
 *   400 {error, detail, ...} -> banner with `detail` (empty_cart,
 *       voucher_invalid, insufficient_stock, ... all arrive as prose)
 *
 * This route sits behind ProtectedRoute role="customer", so the cart is
 * ALWAYS the server cart here (guests were bounced to /login with
 * state.from pointing back at /checkout). After a 201 the backend has
 * already emptied the cart; clearCart() syncs the context (its DELETE is
 * idempotent - get_or_create on an empty cart).
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  FormError,
  LoadingBlock,
  Money,
  StatusBadge,
  inputClass,
  labelClass,
  primaryButtonClass,
} from "../../components/ui";
import { useCart } from "../../context/CartContext";
import { useTenant } from "../../context/TenantContext";
import api from "../../api/client";
import { apiErrorMessage, fieldErrors } from "../../hooks/useApi";

const EMPTY_SHIPPING = {
  full_name: "",
  address1: "",
  address2: "",
  city: "",
  postal_code: "",
  country: "",
  phone: "",
};

export default function Checkout() {
  const { lines, subtotal, itemCount, loading, clearCart } = useCart();
  const { store } = useTenant();
  const currency = store?.currency ?? "USD";

  const [shipping, setShipping] = useState(EMPTY_SHIPPING);
  const [voucherCode, setVoucherCode] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [banner, setBanner] = useState(null);
  const [errors, setErrors] = useState({});
  const [placed, setPlaced] = useState(null); // the 201 Order payload

  const set = (name) => (event) =>
    setShipping((prev) => ({ ...prev, [name]: event.target.value }));

  const isEmpty = !loading && lines.length === 0;

  // Order summary rows come straight from the authoritative server cart.
  const summary = useMemo(
    () =>
      lines.map((line) => ({
        key: line.id,
        title: line.product?.name ?? "Product",
        variant: line.variant?.display_name ?? null,
        quantity: line.quantity,
        lineTotal: line.line_total,
      })),
    [lines]
  );

  const onSubmit = async (event) => {
    event.preventDefault();
    setBanner(null);
    setErrors({});

    // Cheap client-side required checks; the serializer re-checks anyway.
    const required = ["full_name", "address1", "city", "postal_code", "country"];
    const missing = Object.fromEntries(
      required.filter((name) => !shipping[name].trim()).map((name) => [name, "Required."])
    );
    if (shipping.country.trim().length !== 2) {
      missing.country = "Use a 2-letter country code (e.g. IN, US).";
    }
    if (Object.keys(missing).length) {
      setErrors(missing);
      return;
    }

    setSubmitting(true);
    try {
      const payload = {
        shipping: {
          full_name: shipping.full_name.trim(),
          address1: shipping.address1.trim(),
          address2: shipping.address2.trim(),
          city: shipping.city.trim(),
          postal_code: shipping.postal_code.trim(),
          country: shipping.country.trim().toUpperCase(),
          phone: shipping.phone.trim(),
        },
        voucher_code: voucherCode.trim().toUpperCase(),
        notes: notes.trim(),
      };

      const { data: order } = await api.post("/orders/checkout/", payload);
      setPlaced(order);
      await clearCart().catch(() => {
        // Cart row is already empty server-side; a failed sync here must
        // not undo a PLACED order.
      });
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      setBanner(apiErrorMessage(err, "Checkout failed."));
      setErrors(fieldErrors(err));
    } finally {
      setSubmitting(false);
    }
  };

  /* ------------------------------ success ------------------------------ */
  if (placed) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-14 sm:px-6">
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-8 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-2xl text-emerald-600">
            ✓
          </div>
          <h1 className="mt-4 text-xl font-bold text-gray-900">Order placed!</h1>
          <p className="mt-1 text-sm text-gray-600">
            Thanks - your order <strong>{placed.order_number}</strong> is confirmed.
          </p>
          <div className="mt-4 flex items-center justify-center gap-3 text-sm text-gray-600">
            <StatusBadge status={placed.status} />
            <span>
              Total <Money value={placed.total} currency={placed.currency ?? currency} />
            </span>
          </div>
          <div className="mt-6 flex flex-wrap justify-center gap-3">
            <Link to="/" className={primaryButtonClass}>
              Continue shopping
            </Link>
          </div>
        </div>
        {placed.items?.length > 0 && (
          <div className="mt-6 rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="text-sm font-semibold text-gray-900">Summary</h2>
            <ul className="mt-3 divide-y divide-gray-100 text-sm">
              {placed.items.map((item) => (
                <li key={item.id} className="flex justify-between gap-3 py-2">
                  <span className="text-gray-700">
                    {item.product_name}
                    {item.variant_name ? ` · ${item.variant_name}` : ""} × {item.quantity}
                  </span>
                  <Money value={item.line_total} currency={placed.currency ?? currency} />
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    );
  }

  /* ------------------------------- loading ----------------------------- */
  if (loading) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
        <LoadingBlock label="Loading checkout…" />
      </div>
    );
  }

  /* ------------------------------ empty cart --------------------------- */
  if (isEmpty) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-14 sm:px-6">
        <div className="rounded-xl border border-dashed border-gray-300 px-6 py-14 text-center">
          <h1 className="text-lg font-semibold text-gray-900">Your cart is empty</h1>
          <p className="mt-1 text-sm text-gray-500">
            Add something before heading to checkout.
          </p>
          <Link to="/" className={`${primaryButtonClass} mt-5`}>
            Back to the store
          </Link>
        </div>
      </div>
    );
  }

  /* ------------------------------- form -------------------------------- */
  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
      <h1 className="text-2xl font-bold text-gray-900">Checkout</h1>
      <p className="mt-1 text-sm text-gray-500">
        {itemCount} item{itemCount === 1 ? "" : "s"} in your order
      </p>

      <form onSubmit={onSubmit} noValidate className="mt-6 grid gap-6 lg:grid-cols-3">
        {/* Shipping + extras */}
        <div className="space-y-5 lg:col-span-2">
          <FormError message={banner} />

          <section className="rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="text-sm font-semibold text-gray-900">
              Shipping address
            </h2>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label className={labelClass} htmlFor="full_name">
                  Full name
                </label>
                <input
                  id="full_name"
                  className={inputClass}
                  value={shipping.full_name}
                  onChange={set("full_name")}
                  autoComplete="name"
                />
                {errors.full_name && (
                  <p className="mt-1 text-xs text-red-600">{errors.full_name}</p>
                )}
              </div>
              <div className="sm:col-span-2">
                <label className={labelClass} htmlFor="address1">
                  Address line 1
                </label>
                <input
                  id="address1"
                  className={inputClass}
                  value={shipping.address1}
                  onChange={set("address1")}
                  autoComplete="address-line1"
                />
                {errors.address1 && (
                  <p className="mt-1 text-xs text-red-600">{errors.address1}</p>
                )}
              </div>
              <div className="sm:col-span-2">
                <label className={labelClass} htmlFor="address2">
                  Address line 2 <span className="text-gray-400">(optional)</span>
                </label>
                <input
                  id="address2"
                  className={inputClass}
                  value={shipping.address2}
                  onChange={set("address2")}
                  autoComplete="address-line2"
                />
              </div>
              <div>
                <label className={labelClass} htmlFor="city">
                  City
                </label>
                <input
                  id="city"
                  className={inputClass}
                  value={shipping.city}
                  onChange={set("city")}
                  autoComplete="address-level2"
                />
                {errors.city && (
                  <p className="mt-1 text-xs text-red-600">{errors.city}</p>
                )}
              </div>
              <div>
                <label className={labelClass} htmlFor="postal_code">
                  Postal code
                </label>
                <input
                  id="postal_code"
                  className={inputClass}
                  value={shipping.postal_code}
                  onChange={set("postal_code")}
                  autoComplete="postal-code"
                />
                {errors.postal_code && (
                  <p className="mt-1 text-xs text-red-600">{errors.postal_code}</p>
                )}
              </div>
              <div>
                <label className={labelClass} htmlFor="country">
                  Country <span className="text-gray-400">(2-letter code)</span>
                </label>
                <input
                  id="country"
                  className={inputClass}
                  value={shipping.country}
                  onChange={(event) =>
                    setShipping((prev) => ({
                      ...prev,
                      country: event.target.value.toUpperCase().slice(0, 2),
                    }))
                  }
                  placeholder="IN"
                  maxLength={2}
                />
                {errors.country && (
                  <p className="mt-1 text-xs text-red-600">{errors.country}</p>
                )}
              </div>
              <div>
                <label className={labelClass} htmlFor="phone">
                  Phone <span className="text-gray-400">(optional)</span>
                </label>
                <input
                  id="phone"
                  className={inputClass}
                  value={shipping.phone}
                  onChange={set("phone")}
                  autoComplete="tel"
                />
              </div>
            </div>
          </section>

          <section className="rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="text-sm font-semibold text-gray-900">
              Voucher &amp; notes
            </h2>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <div>
                <label className={labelClass} htmlFor="voucher_code">
                  Voucher code <span className="text-gray-400">(optional)</span>
                </label>
                <input
                  id="voucher_code"
                  className={inputClass}
                  value={voucherCode}
                  onChange={(event) => setVoucherCode(event.target.value.toUpperCase())}
                  placeholder="SUMMER10"
                />
                {errors.voucher_code && (
                  <p className="mt-1 text-xs text-red-600">{errors.voucher_code}</p>
                )}
              </div>
              <div>
                <label className={labelClass} htmlFor="notes">
                  Order notes <span className="text-gray-400">(optional)</span>
                </label>
                <input
                  id="notes"
                  className={inputClass}
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  placeholder="Delivery instructions…"
                />
              </div>
            </div>
            {errors.detail && (
              <p className="mt-2 text-xs text-red-600">{errors.detail}</p>
            )}
          </section>
        </div>

        {/* Summary */}
        <aside className="lg:col-span-1">
          <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm lg:sticky lg:top-24">
            <h2 className="text-sm font-semibold text-gray-900">Your order</h2>
            <ul className="mt-3 space-y-2 text-sm">
              {summary.map((item) => (
                <li key={item.key} className="flex justify-between gap-2">
                  <span className="text-gray-600">
                    {item.title}
                    {item.variant ? ` · ${item.variant}` : ""}{" "}
                    <span className="text-gray-400">× {item.quantity}</span>
                  </span>
                  <Money value={item.lineTotal} currency={currency} />
                </li>
              ))}
            </ul>
            <div className="mt-4 flex items-center justify-between border-t border-gray-100 pt-3 text-base font-semibold text-gray-900">
              <span>Total</span>
              <Money value={subtotal} currency={currency} />
            </div>
            <button
              type="submit"
              disabled={submitting}
              className={`${primaryButtonClass} mt-4 w-full`}
            >
              {submitting ? "Placing order…" : "Place order"}
            </button>
            <p className="mt-3 text-center text-xs text-gray-400">
              Your cart is charged once the store confirms payment.
            </p>
          </div>
        </aside>
      </form>
    </div>
  );
}
