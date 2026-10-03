/**
 * Product detail - GET /api/v1/catalog/products/:id
 *
 * Payload (ProductDetailSerializer) = list fields + {description, sku,
 * variants[], reviews[] (approved only), rating_average, rating_count}.
 *
 * Variant handling: the chips are the *active* variants the backend
 * already filtered; picking one swaps both the displayed price
 * (variant.price is the effective price - a variant may NOT override it,
 * it falls back to the product price) and the stock ceiling.
 *
 * Add to cart goes through CartContext.addItem, which knows the two modes:
 *   signed-in -> POST /cart/ (server validates price/stock again)
 *   guest     -> host-scoped localStorage line (+ snapshot for display)
 * The snapshot price is what the guest subtotal estimate uses, so we pass
 * the EFFECTIVE price of the current selection.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ErrorBanner,
  ImagePlaceholder,
  LoadingBlock,
  Money,
  Stars,
  inputClass,
  labelClass,
  primaryButtonClass,
} from "../../components/ui";
import { useCart } from "../../context/CartContext";
import { useTenant } from "../../context/TenantContext";
import useApi from "../../hooks/useApi";

export default function ProductDetail() {
  const { id } = useParams();
  const { store } = useTenant();
  const currency = store?.currency ?? "USD";
  const { addItem } = useCart();

  const { data: product, loading, error, reload } = useApi(`/catalog/products/${id}`);

  const [variantId, setVariantId] = useState(null);
  const [quantity, setQuantity] = useState(1);
  const [adding, setAdding] = useState(false);
  const [addResult, setAddResult] = useState(null); // {type: "ok"|"error", message}

  // New product (back/forward, related links): reset the selection.
  useEffect(() => {
    setVariantId(null);
    setQuantity(1);
    setAddResult(null);
  }, [id]);

  const selectedVariant = useMemo(
    () => product?.variants?.find((v) => v.id === variantId) ?? null,
    [product, variantId]
  );

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        <LoadingBlock label="Loading product…" />
      </div>
    );
  }

  if (error) {
    const notFound = error.response?.status === 404;
    return (
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        <ErrorBanner error={notFound ? null : error} onRetry={notFound ? undefined : reload} />
        {notFound && (
          <div className="rounded-lg border border-gray-200 bg-white px-6 py-12 text-center">
            <h1 className="text-lg font-semibold text-gray-900">Product not found</h1>
            <p className="mt-1 text-sm text-gray-500">
              It may have been removed from this store.
            </p>
            <Link
              to="/"
              className="mt-4 inline-block text-sm font-semibold text-[var(--brand-primary)] underline"
            >
              Back to the store
            </Link>
          </div>
        )}
      </div>
    );
  }

  if (!product) return null;

  // Price + stock of the CURRENT selection.
  const effectivePrice = selectedVariant ? selectedVariant.price : product.price;
  const maxStock = selectedVariant
    ? selectedVariant.stock
    : (product.total_stock ?? 0);
  const outOfStock = maxStock <= 0;

  const onAdd = async () => {
    setAdding(true);
    setAddResult(null);
    try {
      await addItem({
        productId: product.id,
        variantId: selectedVariant?.id ?? null,
        quantity,
        snapshot: {
          name: product.name,
          slug: product.slug,
          image: product.image,
          price: effectivePrice,
        },
      });
      setAddResult({ type: "ok", message: "Added to cart." });
    } catch (err) {
      setAddResult({
        type: "error",
        message:
          err.response?.data?.detail ??
          "Could not add this item (stock or price may have changed).",
      });
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
      {/* Breadcrumb */}
      <nav className="mb-5 text-xs text-gray-400" aria-label="Breadcrumb">
        <Link to="/" className="hover:text-gray-600">
          Store
        </Link>
        <span className="mx-1.5">/</span>
        {product.category && (
          <>
            <span>{product.category.name}</span>
            <span className="mx-1.5">/</span>
          </>
        )}
        <span className="text-gray-600">{product.name}</span>
      </nav>

      <div className="grid gap-8 lg:grid-cols-2">
        {/* Media */}
        <div className="overflow-hidden rounded-2xl border border-gray-200 bg-gray-100">
          {product.image ? (
            <img
              src={product.image}
              alt={product.name}
              className="aspect-square w-full object-cover"
            />
          ) : (
            <ImagePlaceholder
              label={product.name}
              className="aspect-square w-full text-6xl"
            />
          )}
        </div>

        {/* Buy box */}
        <div>
          {product.is_featured && (
            <span className="mb-2 inline-block rounded-full bg-[var(--brand-accent)]/15 px-2.5 py-0.5 text-xs font-semibold text-[var(--brand-accent)]">
              Featured
            </span>
          )}
          <h1 className="text-2xl font-bold tracking-tight text-gray-900 sm:text-3xl">
            {product.name}
          </h1>

          {product.rating_count > 0 && (
            <Stars
              rating={product.rating_average}
              count={product.rating_count}
              className="mt-2"
            />
          )}

          <div className="mt-4 flex items-baseline gap-3">
            <Money
              value={effectivePrice}
              currency={currency}
              className="text-2xl font-bold text-gray-900"
            />
            {product.has_variants && !selectedVariant && (
              <span className="text-xs uppercase tracking-wide text-gray-400">
                starting price
              </span>
            )}
            {product.compare_at_price &&
              Number(product.compare_at_price) > Number(effectivePrice) && (
                <Money
                  value={product.compare_at_price}
                  currency={currency}
                  className="text-base text-gray-400 line-through"
                />
              )}
          </div>

          {/* Variants */}
          {product.has_variants && product.variants.length > 0 && (
            <div className="mt-5">
              <span className={labelClass}>Options</span>
              <div className="flex flex-wrap gap-2">
                {product.variants.map((variant) => {
                  const active = variant.id === variantId;
                  const soldOut = variant.stock <= 0;
                  return (
                    <button
                      key={variant.id}
                      type="button"
                      disabled={soldOut}
                      onClick={() => {
                        setVariantId(active ? null : variant.id);
                        setQuantity(1);
                        setAddResult(null);
                      }}
                      className={`rounded-lg border px-3 py-1.5 text-sm transition ${
                        active
                          ? "border-[var(--brand-primary)] bg-[var(--brand-primary)]/5 font-semibold text-gray-900 ring-1 ring-[var(--brand-primary)]"
                          : "border-gray-300 text-gray-700 hover:border-gray-400"
                      } ${soldOut ? "cursor-not-allowed opacity-40" : ""}`}
                    >
                      {variant.display_name}
                      <span className="ml-2 text-xs text-gray-500">
                        <Money value={variant.price} currency={currency} />
                      </span>
                      {soldOut && (
                        <span className="ml-1 text-xs text-gray-400">· out</span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Quantity + add */}
          <div className="mt-6 flex flex-wrap items-end gap-3">
            <div className="w-28">
              <label className={labelClass} htmlFor="qty">
                Qty
              </label>
              <input
                id="qty"
                type="number"
                min={1}
                max={Math.max(1, maxStock)}
                value={quantity}
                onChange={(event) => {
                  const next = Number(event.target.value);
                  setQuantity(
                    Number.isFinite(next)
                      ? Math.min(Math.max(1, next), Math.max(1, maxStock))
                      : 1
                  );
                }}
                className={inputClass}
              />
            </div>
            <button
              type="button"
              onClick={onAdd}
              disabled={adding || outOfStock}
              className={`${primaryButtonClass} h-10 flex-1 min-w-40`}
            >
              {outOfStock
                ? "Out of stock"
                : adding
                  ? "Adding…"
                  : `Add to cart · ${Number(quantity) > 1 ? `${quantity} × ` : ""}`}
            </button>
          </div>

          {addResult && (
            <div
              className={`mt-3 flex items-center justify-between gap-3 rounded-lg px-4 py-2.5 text-sm ${
                addResult.type === "ok"
                  ? "bg-emerald-50 text-emerald-700"
                  : "bg-red-50 text-red-700"
              }`}
            >
              <span>{addResult.message}</span>
              {addResult.type === "ok" && (
                <Link
                  to="/cart"
                  className="font-semibold underline hover:no-underline"
                >
                  View cart
                </Link>
              )}
            </div>
          )}

          {/* Stock line */}
          <p className="mt-3 text-xs text-gray-500">
            {outOfStock
              ? "Currently unavailable."
              : selectedVariant
                ? `${selectedVariant.stock} in stock`
                : `${product.total_stock} in stock`}
            {product.sku && <span className="ml-2">SKU: {product.sku}</span>}
          </p>

          {/* Description */}
          {product.description && (
            <div className="mt-6 border-t border-gray-100 pt-5">
              <h2 className="text-sm font-semibold text-gray-900">Description</h2>
              <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-gray-600">
                {product.description}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Reviews */}
      <section className="mt-12">
        <h2 className="text-lg font-semibold text-gray-900">
          Reviews
          {product.rating_count > 0 && (
            <span className="ml-2 text-sm font-normal text-gray-500">
              {Number(product.rating_average).toFixed(1)} / 5 · {product.rating_count}{" "}
              review{product.rating_count === 1 ? "" : "s"}
            </span>
          )}
        </h2>

        {product.reviews.length === 0 ? (
          <p className="mt-3 text-sm text-gray-500">
            No reviews yet. Purchased this item? Your review appears once the
            store approves it.
          </p>
        ) : (
          <ul className="mt-4 space-y-4">
            {product.reviews.map((review) => (
              <li
                key={review.id}
                className="rounded-xl border border-gray-200 bg-white p-4"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-gray-900">
                    {review.customer_name}
                    {review.verified_purchase && (
                      <span className="ml-2 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold uppercase text-emerald-700 ring-1 ring-inset ring-emerald-200">
                        Verified purchase
                      </span>
                    )}
                  </span>
                  <span className="text-xs text-amber-500" aria-label={`${review.rating} of 5`}>
                    {"★".repeat(review.rating)}
                    <span className="text-gray-300">
                      {"★".repeat(5 - review.rating)}
                    </span>
                  </span>
                </div>
                {review.title && (
                  <p className="mt-1.5 text-sm font-medium text-gray-800">
                    {review.title}
                  </p>
                )}
                {review.body && (
                  <p className="mt-1 text-sm leading-relaxed text-gray-600">
                    {review.body}
                  </p>
                )}
                <time className="mt-2 block text-xs text-gray-400">
                  {new Date(review.created_at).toLocaleDateString()}
                </time>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
