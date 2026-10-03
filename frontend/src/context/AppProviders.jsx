/**
 * Provider composition. Order matters:
 *
 *   TenantProvider  - independent; boots /storefront/init/ for branding
 *   AuthProvider    - independent of tenancy; owns the JWT session
 *   CartProvider    - must sit INSIDE AuthProvider (server cart is per-user)
 *
 * main.jsx wraps <App/> in this once; no component should re-nest providers.
 */
import { AuthProvider } from "./AuthContext";
import { CartProvider } from "./CartContext";
import { TenantProvider } from "./TenantContext";

export function AppProviders({ children }) {
  return (
    <TenantProvider>
      <AuthProvider>
        <CartProvider>{children}</CartProvider>
      </AuthProvider>
    </TenantProvider>
  );
}
