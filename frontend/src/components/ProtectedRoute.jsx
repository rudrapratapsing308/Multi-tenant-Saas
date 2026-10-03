/**
 * Route guard for the two dashboards (and the customer checkout).
 *
 *   <ProtectedRoute role="vendor">        vendor dashboard
 *   <ProtectedRoute role="super_admin">   platform dashboard
 *   <ProtectedRoute role="customer">      checkout (signed-in shoppers)
 *
 * Three states, in order:
 *   1. auth still rehydrating   -> splash (never flash the login page at a
 *                                  vendor who is mid-reload)
 *   2. no session               -> /admin/login | /superadmin/login | /login
 *                                  (chosen from the CURRENT path, so a
 *                                  customer on /admin lands on vendor login,
 *                                  not on a customer login that cannot help)
 *                                  and state.from carries the interrupted
 *                                  location, so after signing in the visitor
 *                                  resumes exactly where they were
 *                                  (Login.jsx reads it: returnPath ?? home)
 *   3. session but wrong role   -> bounce to that role's home. A customer
 *                                  opening /admin sees their own storefront,
 *                                  a vendor opening /superadmin their store -
 *                                  roles are proven by the backend anyway;
 *                                  this is UX, not security (the API answers
 *                                  403 regardless).
 */
import { Navigate, useLocation } from "react-router-dom";
import {
  homePathForRole,
  loginPathFor,
} from "../api/client";
import { useAuth } from "../context/AuthContext";
import { SplashScreen } from "./BootScreens";

export default function ProtectedRoute({ role, children }) {
  const { status, user } = useAuth();
  const location = useLocation();

  if (status === "loading") return <SplashScreen label="Restoring session…" />;

  if (!user) {
    return (
      <Navigate
        to={loginPathFor(location.pathname)}
        state={{ from: location }}
        replace
      />
    );
  }

  if (user.role !== role) {
    return <Navigate to={homePathForRole(user.role)} replace />;
  }

  return children;
}
