/**
 * Vendor dashboard shell - sidebar + <Outlet/>.
 *
 * Nav items map 1:1 to child routes under /admin:
 *   Overview  -> /admin            (Analytics.jsx)
 *   Orders    -> /admin/orders     (Orders.jsx)
 *   Products  -> /admin/products   (Products.jsx)
 *   Settings  -> /admin/settings   (Settings.jsx)
 *
 * NavLink gives the active state (aria-current included), so no manual
 * pathname matching lives here. Responsive: fixed sidebar from lg up,
 * a horizontal scrollable nav below that.
 *
 * Branding: same TenantContext CSS variables as the storefront - the
 * dashboard is rendered on the vendor's own host, so the store's colors
 * theme it too (static var classes, never interpolated utilities).
 */
import { Link, NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { useTenant } from "../../context/TenantContext";

const NAV = [
  {
    to: "/admin",
    end: true,
    label: "Overview",
    icon: (
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25A2.25 2.25 0 0 1 13.5 18v-2.25Z"
      />
    ),
  },
  {
    to: "/admin/orders",
    label: "Orders",
    icon: (
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M8.25 18.75a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m3 0h6m-9 0H3.375a1.125 1.125 0 0 1-1.125-1.125V14.25m17.25 4.5a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m3 0h1.125c.621 0 1.129-.504 1.09-1.124a17.902 17.902 0 0 0-3.213-9.193 2.056 2.056 0 0 0-1.58-.86H14.25M16.5 18.75h-2.25m0-11.177v-.958c0-.568-.422-1.049-.987-1.106a48.554 48.554 0 0 0-10.026 0 1.106 1.106 0 0 0-.987 1.106v7.635m12-6.677v6.677m0 4.5v-4.5m0 0h-12"
      />
    ),
  },
  {
    to: "/admin/products",
    label: "Products",
    icon: (
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z"
      />
    ),
  },
  {
    to: "/admin/settings",
    label: "Settings",
    icon: (
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z"
      />
    ),
  },
];

function NavIcon({ children }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      className="h-5 w-5 shrink-0"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

const navLinkClass = ({ isActive }) =>
  [
    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
    isActive
      ? "bg-white/10 text-white"
      : "text-gray-300 hover:bg-white/5 hover:text-white",
  ].join(" ");

export default function VendorLayout() {
  const { brand, store } = useTenant();
  const { user, logout } = useAuth();

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Sidebar (lg+) */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col bg-gray-900 lg:flex">
        <div className="flex items-center gap-2 border-b border-white/10 px-5 py-4">
          {brand?.logo_url && (
            <img src={brand.logo_url} alt="" className="h-7 w-7 rounded object-contain" />
          )}
          <div className="min-w-0">
            <p className="truncate text-sm font-bold text-white">
              {brand?.brand_name || store?.name}
            </p>
            <p className="truncate text-xs text-gray-400">Vendor dashboard</p>
          </div>
        </div>

        <nav className="flex-1 space-y-1 px-3 py-4">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={navLinkClass}>
              <NavIcon>{item.icon}</NavIcon>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-white/10 px-5 py-4">
          <p className="truncate text-xs text-gray-400">{user?.email}</p>
          <div className="mt-2 flex items-center gap-3">
            <Link
              to="/"
              className="text-xs font-medium text-gray-300 underline hover:text-white"
            >
              View store
            </Link>
            <button
              type="button"
              onClick={logout}
              className="text-xs font-medium text-gray-300 underline hover:text-white"
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* Mobile header + nav */}
      <div className="sticky top-0 z-30 bg-gray-900 lg:hidden">
        <div className="flex items-center justify-between px-4 py-3">
          <span className="truncate text-sm font-bold text-white">
            {brand?.brand_name || store?.name}{" "}
            <span className="font-normal text-gray-400">· dashboard</span>
          </span>
          <div className="flex items-center gap-3">
            <Link to="/" className="text-xs text-gray-300 underline">
              Store
            </Link>
            <button
              type="button"
              onClick={logout}
              className="text-xs text-gray-300 underline"
            >
              Sign out
            </button>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                [
                  "whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition",
                  isActive ? "bg-white/10 text-white" : "text-gray-300",
                ].join(" ")
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>

      <main className="px-4 py-6 sm:px-6 lg:ml-64 lg:px-8 lg:py-8">
        <div className="mx-auto max-w-6xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
