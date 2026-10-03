/**
 * Storefront home - banner hero + category filter + product grid.
 *
 * Query contract (GET /api/v1/catalog/products/):
 *   ?search=<text>   name/description icontains
 *   ?category=<slug> exact category slug
 * Both live in the URL (?q=...&category=...) so a filtered view is
 * shareable and the back button behaves. The layout search box writes
 * ?q=; the category chips write ?category=.
 *
 * Featured products are FLAGGED in the main grid (is_featured badge)
 * rather than fetched twice - one request, no duplicated rows.
 */
import { Link, useSearchParams } from "react-router-dom";
import {
  ErrorBanner,
  ImagePlaceholder,
  LoadingBlock,
  Money,
  cardClass,
} from "../../components/ui";
import { useTenant } from "../../context/TenantContext";
import useApi from "../../hooks/useApi";

function ProductCard({ product, currency }) {
  const price = product.has_variants ? product.starting_price : product.price;
  return (
    <Link
      to={`/products/${product.id}`}
      className={`group flex flex-col overflow-hidden transition hover:-translate-y-0.5 hover:shadow-md ${cardClass}`}
    >
      <div className="relative aspect-square overflow-hidden bg-gray-100">
        {product.image ? (
          <img
            src={product.image}
            alt={product.name}
            loading="lazy"
            className="h-full w-full object-cover transition duration-300 group-hover:scale-105"
          />
        ) : (
          <ImagePlaceholder label={product.name} className="h-full w-full text-3xl" />
        )}
        {product.is_featured && (
          <span className="absolute left-2 top-2 rounded-full bg-[var(--brand-accent)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
            Featured
          </span>
        )}
        {!product.in_stock && (
          <span className="absolute right-2 top-2 rounded-full bg-gray-900/80 px-2 py-0.5 text-[10px] font-semibold text-white">
            Sold out
          </span>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-1 p-3">
        <h3 className="line-clamp-2 text-sm font-medium text-gray-900">
          {product.name}
        </h3>
        {product.category && (
          <span className="text-xs text-gray-400">{product.category.name}</span>
        )}
        <div className="mt-auto flex items-baseline gap-2 pt-1">
          <Money
            value={price}
            currency={currency}
            className="text-sm font-semibold text-gray-900"
          />
          {product.compare_at_price && Number(product.compare_at_price) > Number(price) && (
            <Money
              value={product.compare_at_price}
              currency={currency}
              className="text-xs text-gray-400 line-through"
            />
          )}
          {product.has_variants && (
            <span className="text-[10px] uppercase tracking-wide text-gray-400">
              from
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}

function HeroBanner({ banner, brand }) {
  return (
    <section className="relative overflow-hidden bg-[var(--brand-primary)] text-white">
      {banner?.image_url && (
        <img
          src={banner.image_url}
          alt=""
          className="absolute inset-0 h-full w-full object-cover opacity-30"
        />
      )}
      <div className="relative mx-auto max-w-6xl px-4 py-14 sm:px-6 sm:py-20">
        <h1 className="max-w-2xl text-3xl font-bold tracking-tight sm:text-4xl">
          {banner?.title || brand?.brand_name || "Welcome"}
        </h1>
        {(banner?.subtitle || brand?.tagline) && (
          <p className="mt-3 max-w-xl text-sm text-white/80 sm:text-base">
            {banner?.subtitle || brand?.tagline}
          </p>
        )}
        <div className="mt-6 flex flex-wrap gap-3">
          <a
            href={banner?.link_url || "#products"}
            className="rounded-lg bg-white px-5 py-2.5 text-sm font-semibold text-gray-900 transition hover:bg-gray-100"
          >
            Shop now
          </a>
        </div>
      </div>
    </section>
  );
}

export default function Home() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const category = params.get("category") ?? "";
  const { brand, banners, store } = useTenant();
  const currency = store?.currency ?? "USD";

  const { data: categories } = useApi("/catalog/categories/");
  const { data: products, loading, error, reload } = useApi("/catalog/products/", {
    params: { search: q || undefined, category: category || undefined },
  });

  const setFilter = (name, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: false });
  };

  const hasFilters = Boolean(q || category);

  return (
    <div>
      <HeroBanner banner={banners[0]} brand={brand} />

      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6" id="products">
        {/* Category chips + active search */}
        <div className="mb-5 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setParams(new URLSearchParams(), { replace: false });
            }}
            className={`rounded-full px-4 py-1.5 text-sm font-medium transition ${
              !category
                ? "bg-[var(--brand-primary)] text-white"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
          >
            All
          </button>
          {(categories ?? []).map((cat) => (
            <button
              key={cat.id}
              type="button"
              onClick={() => setFilter("category", category === cat.slug ? "" : cat.slug)}
              className={`rounded-full px-4 py-1.5 text-sm font-medium transition ${
                category === cat.slug
                  ? "bg-[var(--brand-primary)] text-white"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              }`}
            >
              {cat.name}
            </button>
          ))}

          {hasFilters && (
            <span className="ml-auto flex items-center gap-2 text-sm text-gray-500">
              {q && (
                <span>
                  Results for <strong className="text-gray-800">“{q}”</strong>
                </span>
              )}
              <button
                type="button"
                onClick={() => setParams(new URLSearchParams())}
                className="text-[var(--brand-primary)] underline hover:no-underline"
              >
                Clear
              </button>
            </span>
          )}
        </div>

        {error && <ErrorBanner error={error} onRetry={reload} className="mb-5" />}

        {loading ? (
          <LoadingBlock label="Loading products…" />
        ) : (products ?? []).length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-300 px-6 py-14 text-center">
            <h3 className="text-sm font-semibold text-gray-900">No products found</h3>
            <p className="mt-1 text-sm text-gray-500">
              {hasFilters
                ? "Try a different search or category."
                : "This store has not listed anything yet."}
            </p>
            {hasFilters && (
              <button
                type="button"
                onClick={() => setParams(new URLSearchParams())}
                className="mt-4 text-sm font-semibold text-[var(--brand-primary)] underline"
              >
                Show everything
              </button>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {products.map((product) => (
              <ProductCard key={product.id} product={product} currency={currency} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
