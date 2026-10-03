/**
 * Storefront layout - the chrome around every customer-facing page:
 * header (brand, search, cart badge, account) + <Outlet/> + footer.
 *
 * Branding comes from TenantContext (booted once per host):
 *   logo/name -> "/"   theme -> CSS vars (never interpolated into classes)
 *
 * Cart badge: CartContext.itemCount covers BOTH modes (server cart for a
 * signed-in customer, host-scoped guest cart otherwise), so the number is
 * always live without this component knowing which mode is active.
 *
 * Account area is role-aware: vendors/super admins get a link to their
 * dashboard instead of a login button (they can browse the store too).
 */
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { homePathForRole } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { useCart } from "../../context/CartContext";
import { useTenant } from "../../context/TenantContext";

const searchBoxClass =
  "w-full rounded-full border border-gray-300 bg-gray-50 px-4 py-2 text-sm " +
  "placeholder:text-gray-400 focus:border-[var(--brand-primary)] focus:bg-white " +
  "focus:outline-none focus:ring-2 focus:ring-[var(--brand-primary)]/20";

function CartIcon({ count }) {
  return (
    <span className="relative inline-flex">
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        className="h-6 w-6"
        aria-hidden="true"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M2.25 3h1.386c.51 0 .955.343 1.087.835l.383 1.437M7.5 14.25a3 3 0 0 0-3 3h15.75m-12.75-3h11.218c1.121-2.3 2.1-4.684 2.924-7.138a60.114 60.114 0 0 0-16.536-1.84M7.5 14.25 5.106 5.272M6 20.25a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Zm12.75 0a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Z"
        />
      </svg>
      {count > 0 && (
        <span className="absolute -right-2 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-[var(--brand-accent)] px-1 text-[10px] font-bold text-white">
          {count > 99 ? "99+" : count}
        </span>
      )}
    </span>
  );
}

function SearchBox({ initialValue = "", mobile = false }) {
  const navigate = useNavigate();
  return (
    <form
      role="search"
      className={mobile ? "px-4 pb-3 sm:hidden" : "hidden flex-1 sm:block"}
      onSubmit={(event) => {
        event.preventDefault();
        const value = new FormData(event.currentTarget).get("q");
        const query = String(value ?? "").trim();
        navigate(query ? `/?q=${encodeURIComponent(query)}` : "/");
      }}
    >
      <div className="relative mx-auto max-w-xl">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z"
          />
        </svg>
        <input
          type="search"
          name="q"
          defaultValue={initialValue}
          placeholder="Search products…"
          aria-label="Search products"
          className={`${searchBoxClass} pl-9`}
        />
      </div>
    </form>
  );
}

export default function Layout() {
  const { brand, store } = useTenant();
  const { user, logout } = useAuth();
  const { itemCount } = useCart();
  const navigate = useNavigate();
  const location = useLocation();

  // Keep the search field in sync when Home rewrites ?q= (back/forward too).
  const activeQuery = new URLSearchParams(location.search).get("q") ?? "";

  const dashboardPath = user ? homePathForRole(user.role) : null;

  const onSignOut = () => {
    logout();
    navigate("/", { replace: true });
  };

  return (
    <div className="flex min-h-screen flex-col bg-white">
      <header className="sticky top-0 z-20 border-b border-gray-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3 sm:px-6">
          {/* Brand -> home */}
          <Link to="/" className="flex shrink-0 items-center gap-2">
            {brand?.logo_url && (
              <img
                src={brand.logo_url}
                alt=""
                className="h-8 w-8 rounded-lg object-contain"
              />
            )}
            <span className="text-base font-bold tracking-tight text-gray-900 sm:text-lg">
              {brand?.brand_name || store?.name || "Store"}
            </span>
          </Link>

          <SearchBox initialValue={activeQuery} />

          <nav className="ml-auto flex items-center gap-1 sm:gap-2">
            <Link
              to="/cart"
              className="relative rounded-lg p-2 text-gray-700 transition hover:bg-gray-100"
              aria-label={`Cart, ${itemCount} item${itemCount === 1 ? "" : "s"}`}
            >
              <CartIcon count={itemCount} />
            </Link>

            {user ? (
              <div className="flex items-center gap-1 sm:gap-2">
                <Link
                  to={dashboardPath}
                  className="hidden max-w-[10rem] truncate rounded-lg px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-100 sm:block"
                >
                  {user.first_name || user.email}
                  {user.role !== "customer" && (
                    <span className="ml-1 text-xs text-gray-400">· dashboard</span>
                  )}
                </Link>
                <button
                  type="button"
                  onClick={onSignOut}
                  className="rounded-lg px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-100"
                >
                  Sign out
                </button>
              </div>
            ) : (
              <Link
                to="/login"
                className="rounded-lg bg-[var(--brand-primary)] px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90"
              >
                Sign in
              </Link>
            )}
          </nav>
        </div>

        {/* Mobile search row */}
        <SearchBox initialValue={activeQuery} mobile />
      </header>

      <main className="flex-1">
        <Outlet />
      </main>

      <footer className="border-t border-gray-200 bg-gray-50">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-8 text-sm text-gray-500 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div>
            <span className="font-semibold text-gray-700">
              {brand?.brand_name || store?.name}
            </span>
            {brand?.tagline && <span className="ml-2">{brand.tagline}</span>}
          </div>
          <div className="flex items-center gap-4">
            <span className="text-xs text-gray-400">{store?.host}</span>
            <span className="text-xs text-gray-400">
              © {new Date().getFullYear()}
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}
