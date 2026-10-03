/**
 * Auth page - FULL login + register for all three areas.
 *
 * One component, two routes per area (element keys force a clean remount so
 * form state never leaks between modes):
 *
 *   /login          /register          customer area (storefront chrome)
 *   /admin/login    /admin/register    vendor area   (role forced to vendor)
 *   /superadmin/login                  platform console (login only -
 *                                       super_admin accounts are operator-
 *                                       created and CANNOT self-register)
 *
 * The area and mode are derived from the pathname, so the SAME redirect
 * logic serves every route:
 *
 *   1. post-login target = location.state?.from (set by ProtectedRoute -
 *      "return to the page you were on"), else homePathForRole(role);
 *   2. already signed in -> straight to that target (no second login);
 *   3. wrong role for an area -> the backend answers 403 anyway; this page
 *      simply routes by the role the credential endpoint reports.
 *
 * Register payload (POST /auth/register/):
 *   {email, password, first_name, last_name, role, store_name?}
 *   - role: "customer" | "vendor" (super_admin is not a choice, by design);
 *   - store_name is REQUIRED when registering as a vendor: the backend
 *     creates the Business + <slug>.local-saas.com domain + OWNER membership
 *     from it, and a vendor without a store would own nothing to manage.
 */
import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { homePathForRole } from "../../api/client";
import {
  FieldError,
  FormError,
  Spinner,
  inputClass,
  labelClass,
  primaryButtonClass,
} from "../../components/ui";
import { useAuth } from "../../context/AuthContext";
import { useTenant } from "../../context/TenantContext";
import { apiErrorMessage, fieldErrors } from "../../hooks/useApi";

const EMPTY = {
  email: "",
  password: "",
  first_name: "",
  last_name: "",
  role: "customer",
  store_name: "",
};

export default function AuthPage() {
  const { pathname, state } = useLocation();
  const navigate = useNavigate();
  const { status: authStatus, user, login, register } = useAuth();
  const { brand } = useTenant();

  const area = pathname.startsWith("/admin")
    ? "vendor"
    : pathname.startsWith("/superadmin")
      ? "superadmin"
      : "customer";
  const mode = pathname.endsWith("/register") ? "register" : "login";

  const [form, setForm] = useState(EMPTY);
  const [submitting, setSubmitting] = useState(false);
  const [banner, setBanner] = useState(null);
  const [errors, setErrors] = useState({});

  // Where ProtectedRoute wanted to send us BEFORE bouncing to login.
  const from = state?.from;
  const returnPath = from?.pathname
    ? `${from.pathname}${from.search ?? ""}${from.hash ?? ""}`
    : null;

  // Credentials still rehydrating: never flash the form at a signed-in user.
  if (authStatus === "loading") {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Spinner label="Restoring session…" />
      </div>
    );
  }

  // Signed in already: resume the interrupted page (or go to the role home).
  if (authStatus === "authenticated" && user) {
    return <Navigate to={returnPath ?? homePathForRole(user.role)} replace />;
  }

  const set = (name) => (event) =>
    setForm((prev) => ({ ...prev, [name]: event.target.value }));

  // Vendor registration always means "create a store" - in the vendor area
  // the role is fixed; on the storefront the Sell/Shop choice sets it.
  const effectiveRole = area === "vendor" ? "vendor" : form.role;
  const isVendorSignup = mode === "register" && effectiveRole === "vendor";

  const areaCopy = {
    customer: {
      title: brand?.brand_name || "Welcome back",
      blurb: brand?.tagline || "Sign in to your account",
    },
    vendor: {
      title: "Vendor console",
      blurb: "Sign in to manage your store",
    },
    superadmin: {
      title: "Platform console",
      blurb: "Sign in to manage the platform",
    },
  }[area];

  const validate = () => {
    const next = {};
    if (!form.email.trim()) next.email = "Email is required.";
    if (!form.password) next.password = "Password is required.";
    if (mode === "register") {
      if (form.password.length < 8) {
        next.password = "Password must be at least 8 characters.";
      }
      if (isVendorSignup && !form.store_name.trim()) {
        next.store_name = "Give your store a name - it becomes its domain.";
      }
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const onSubmit = async (event) => {
    event.preventDefault();
    setBanner(null);
    if (!validate()) return;

    setSubmitting(true);
    try {
      let data;
      if (mode === "login") {
        data = await login(form.email.trim(), form.password);
      } else {
        const payload = {
          email: form.email.trim(),
          password: form.password,
          first_name: form.first_name.trim(),
          last_name: form.last_name.trim(),
          role: effectiveRole,
        };
        if (isVendorSignup) payload.store_name = form.store_name.trim();
        data = await register(payload);
      }
      // role-based redirect; `returnPath` wins so /checkout -> login ->
      // back to /checkout works (ProtectedRoute passes state.from).
      navigate(returnPath ?? homePathForRole(data.role), { replace: true });
    } catch (err) {
      // 401/400 from credential endpoints are intentionally NOT redirected
      // by the client interceptor: a wrong password stays a form error.
      setBanner(apiErrorMessage(err, "Could not sign you in."));
      setErrors(fieldErrors(err));
    } finally {
      setSubmitting(false);
    }
  };

  // Login <-> Register links stay inside the current area.
  const altPath =
    area === "vendor"
      ? mode === "login"
        ? "/admin/register"
        : "/admin/login"
      : mode === "login"
        ? "/register"
        : "/login";

  return (
    <div className="flex min-h-[70vh] items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
          <div className="mb-6 text-center">
            <h1 className="text-xl font-semibold text-gray-900">
              {mode === "register"
                ? area === "vendor"
                  ? "Create your store"
                  : "Create an account"
                : areaCopy.title}
            </h1>
            <p className="mt-1 text-sm text-gray-500">
              {mode === "register"
                ? area === "vendor"
                  ? "It gets its own domain instantly."
                  : "Join in a few seconds."
                : areaCopy.blurb}
            </p>
          </div>

          <FormError message={banner} className="mb-4" />

          <form onSubmit={onSubmit} noValidate className="space-y-4">
            {mode === "register" && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelClass} htmlFor="first_name">
                    First name
                  </label>
                  <input
                    id="first_name"
                    className={inputClass}
                    value={form.first_name}
                    onChange={set("first_name")}
                    autoComplete="given-name"
                  />
                  <FieldError message={errors.first_name} />
                </div>
                <div>
                  <label className={labelClass} htmlFor="last_name">
                    Last name
                  </label>
                  <input
                    id="last_name"
                    className={inputClass}
                    value={form.last_name}
                    onChange={set("last_name")}
                    autoComplete="family-name"
                  />
                  <FieldError message={errors.last_name} />
                </div>
              </div>
            )}

            <div>
              <label className={labelClass} htmlFor="email">
                Email
              </label>
              <input
                id="email"
                type="email"
                required
                className={inputClass}
                value={form.email}
                onChange={set("email")}
                autoComplete="email"
                placeholder="you@example.com"
              />
              <FieldError message={errors.email} />
            </div>

            <div>
              <label className={labelClass} htmlFor="password">
                Password
              </label>
              <input
                id="password"
                type="password"
                required
                className={inputClass}
                value={form.password}
                onChange={set("password")}
                autoComplete={mode === "register" ? "new-password" : "current-password"}
                placeholder={mode === "register" ? "At least 8 characters" : "••••••••"}
              />
              <FieldError message={errors.password} />
            </div>

            {mode === "register" && area === "customer" && (
              /* Sell / Shop choice - "Sell" reveals the store-name field. */
              <fieldset className="grid grid-cols-2 gap-3">
                <legend className="mb-1 text-sm font-medium text-gray-700">
                  I want to
                </legend>
                {[
                  { value: "customer", label: "Shop", hint: "Buy from stores" },
                  { value: "vendor", label: "Sell", hint: "Create my store" },
                ].map((option) => (
                  <button
                    type="button"
                    key={option.value}
                    onClick={() => setForm((prev) => ({ ...prev, role: option.value }))}
                    className={`rounded-lg border px-3 py-2 text-left transition ${
                      form.role === option.value
                        ? "border-[var(--brand-primary)] bg-[var(--brand-primary)]/5 ring-1 ring-[var(--brand-primary)]"
                        : "border-gray-300 hover:border-gray-400"
                    }`}
                  >
                    <span className="block text-sm font-semibold text-gray-900">
                      {option.label}
                    </span>
                    <span className="block text-xs text-gray-500">{option.hint}</span>
                  </button>
                ))}
              </fieldset>
            )}

            {mode === "register" && isVendorSignup && (
              <div>
                <label className={labelClass} htmlFor="store_name">
                  Store name
                </label>
                <input
                  id="store_name"
                  className={inputClass}
                  value={form.store_name}
                  onChange={set("store_name")}
                  placeholder="Acme Threads"
                />
                <FieldError message={errors.store_name} />
                <p className="mt-1 text-xs text-gray-500">
                  Published at {form.store_name.trim() ? form.store_name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") : "your-store"}
                  .local-saas.com
                </p>
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className={`${primaryButtonClass} w-full`}
            >
              {submitting ? "Please wait…" : mode === "register" ? "Create account" : "Sign in"}
            </button>
          </form>

          {/* Mode switch - omitted for the platform console (no signup). */}
          {area !== "superadmin" && (
            <p className="mt-5 text-center text-sm text-gray-500">
              {mode === "login" ? "New here?" : "Already have an account?"}{" "}
              <Link
                to={altPath}
                className="font-semibold text-[var(--brand-primary)] hover:underline"
              >
                {mode === "login" ? "Create an account" : "Sign in"}
              </Link>
            </p>
          )}
        </div>

        {/* Area switch: a customer on /login can jump to the vendor door. */}
        {area === "customer" && (
          <p className="mt-4 text-center text-xs text-gray-400">
            <Link to="/admin/login" className="hover:text-gray-600 hover:underline">
              I&apos;m a vendor
            </Link>
            <span className="mx-2">·</span>
            <Link to="/" className="hover:text-gray-600 hover:underline">
              Back to store
            </Link>
          </p>
        )}
        {area === "vendor" && (
          <p className="mt-4 text-center text-xs text-gray-400">
            <Link to="/login" className="hover:text-gray-600 hover:underline">
              Shop instead
            </Link>
            <span className="mx-2">·</span>
            <Link to="/" className="hover:text-gray-600 hover:underline">
              View storefront
            </Link>
          </p>
        )}
      </div>
    </div>
  );
}
