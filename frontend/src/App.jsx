/**
 * Application routing - the three-branch structure of the platform:
 *
 *   /                public storefront (customer view)      - no guard
 *   /admin/*         vendor dashboard                       - vendor role
 *   /superadmin/*    platform console                       - super_admin role
 *
 * Structure (Module 6 - real pages replace the Module-5 stubs):
 *
 *   Layout (storefront chrome: header/search/cart + footer)
 *     index                Home.jsx           product grid + banner + filters
 *     products/:id         ProductDetail.jsx  variants, reviews, add-to-cart
 *     cart                 Cart.jsx           both cart modes, one view model
 *     checkout             Checkout.jsx       guarded: customer role
 *     login / register     auth/Login.jsx     full forms, role-based redirect
 *     *                    NotFound
 *
 *   /admin/login|register  auth/Login.jsx     (vendor door, role fixed)
 *   /admin                 VendorLayout       guarded: vendor role
 *     index                Analytics.jsx      revenue/orders/customers
 *     orders               Orders.jsx         state machine: pending → … → delivered
 *     products             Products.jsx       CRUD + image upload
 *     settings             Settings.jsx       brand + theme colors
 *     *                    → redirect to /admin
 *
 *   /superadmin/login      auth/Login.jsx     (platform door, no signup)
 *   /superadmin            PlatformOverview   guarded: super_admin role
 *
 * The router mounts only AFTER the tenant booted (TenantContext) - except
 * for /superadmin, which is tenant-EXEMPT on the backend: when boot fails
 * (wrong host, suspended store) the platform console must still be
 * reachable, since that is how an admin gets in to fix the store. Every
 * other path shows StoreErrorScreen.
 *
 * Note on bare "/admin": the parent route "admin" has CHILDREN, so it
 * matches "/admin" (index child) as well as "/admin/<page>"; the splat
 * child catches typos and redirects home. Same for "/superadmin/*".
 */
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import { SplashScreen, StoreErrorScreen } from "./components/BootScreens";
import ProtectedRoute from "./components/ProtectedRoute";
import { useTenant } from "./context/TenantContext";
import AuthPage from "./pages/auth/Login";
import PlatformOverview from "./pages/superadmin/PlatformOverview";
import Cart from "./pages/storefront/Cart";
import Checkout from "./pages/storefront/Checkout";
import Home from "./pages/storefront/Home";
import Layout from "./pages/storefront/Layout";
import ProductDetail from "./pages/storefront/ProductDetail";
import Analytics from "./pages/vendor/Analytics";
import Orders from "./pages/vendor/Orders";
import Products from "./pages/vendor/Products";
import Settings from "./pages/vendor/Settings";
import VendorLayout from "./pages/vendor/VendorLayout";

function NotFound() {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-2 px-4 text-center">
      <h1 className="text-2xl font-semibold text-gray-900">Page not found</h1>
      <p className="text-sm text-gray-500">
        The page you are looking for does not exist.
      </p>
      <Link
        to="/"
        className="text-sm font-semibold text-[var(--brand-primary)] underline"
      >
        Back to the storefront
      </Link>
    </div>
  );
}

/** Full app - tenant booted successfully. */
function AppRoutes() {
  return (
    <Routes>
      {/* Customer storefront (public; checkout needs a customer session) */}
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="products/:id" element={<ProductDetail />} />
        <Route path="cart" element={<Cart />} />
        <Route
          path="checkout"
          element={
            <ProtectedRoute role="customer">
              <Checkout />
            </ProtectedRoute>
          }
        />
        <Route path="login" element={<AuthPage key="login" />} />
        <Route path="register" element={<AuthPage key="register" />} />
        <Route path="*" element={<NotFound />} />
      </Route>

      {/* Vendor dashboard (protected: vendor role) */}
      <Route path="/admin/login" element={<AuthPage key="admin-login" />} />
      <Route path="/admin/register" element={<AuthPage key="admin-register" />} />
      <Route
        path="/admin"
        element={
          <ProtectedRoute role="vendor">
            <VendorLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Analytics />} />
        <Route path="orders" element={<Orders />} />
        <Route path="products" element={<Products />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/admin" replace />} />
      </Route>

      {/* Platform console (protected: super_admin role) */}
      <Route path="/superadmin/login" element={<AuthPage key="superadmin-login" />} />
      <Route
        path="/superadmin"
        element={
          <ProtectedRoute role="super_admin">
            <PlatformOverview />
          </ProtectedRoute>
        }
      />
      <Route path="/superadmin/*" element={<Navigate to="/superadmin" replace />} />
    </Routes>
  );
}

/**
 * Tenant boot failed - only the platform console stays routed (its API is
 * tenant-exempt; every other page would just re-show this error anyway).
 */
function BootErrorRoutes() {
  return (
    <Routes>
      <Route path="/superadmin/login" element={<AuthPage key="superadmin-login" />} />
      <Route
        path="/superadmin"
        element={
          <ProtectedRoute role="super_admin">
            <PlatformOverview />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<StoreErrorScreen />} />
    </Routes>
  );
}

export default function App() {
  const { status } = useTenant();

  return (
    <BrowserRouter>
      {status === "loading" ? (
        <SplashScreen label="Booting storefront…" />
      ) : status === "error" ? (
        <BootErrorRoutes />
      ) : (
        <AppRoutes />
      )}
    </BrowserRouter>
  );
}
