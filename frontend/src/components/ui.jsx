/**
 * Shared UI kit for the Module-6 pages.
 *
 * Design rules baked in here:
 *
 *   * BRAND COLORS ARE NEVER STRING-INTERPOLATED into Tailwind classes
 *     (`bg-[${color}]` would produce a class the compiler never saw).
 *     Tenant colors flow through either
 *       - the runtime CSS variables written by TenantContext
 *         (`bg-[var(--brand-primary)]` - static class, dynamic value), or
 *       - inline `style={{ backgroundColor: hex }}` where an actual hex
 *         from the API is rendered (color pickers, theme previews).
 *   * Status pill styles are a LOOKUP TABLE of complete class strings -
 *     every candidate exists literally in this file, so Tailwind ships them.
 *   * Money always renders through Intl.NumberFormat with the tenant's
 *     currency (decimals arrive from DRF as strings: "123.45").
 */
import { apiErrorMessage } from "../hooks/useApi";

/* ------------------------------------------------------------------ *
 * Class constants - one source of truth for form/button look-and-feel
 * ------------------------------------------------------------------ */
export const labelClass = "mb-1 block text-sm font-medium text-gray-700";

export const inputClass =
  "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 " +
  "placeholder:text-gray-400 focus:border-[var(--brand-primary)] focus:outline-none " +
  "focus:ring-2 focus:ring-[var(--brand-primary)]/20 disabled:bg-gray-50 disabled:text-gray-500";

export const primaryButtonClass =
  "inline-flex items-center justify-center gap-2 rounded-lg bg-[var(--brand-primary)] " +
  "px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90 " +
  "disabled:cursor-not-allowed disabled:opacity-50";

export const secondaryButtonClass =
  "inline-flex items-center justify-center gap-2 rounded-lg border border-gray-300 " +
  "bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition hover:bg-gray-50 " +
  "disabled:cursor-not-allowed disabled:opacity-50";

export const dangerButtonClass =
  "inline-flex items-center justify-center gap-2 rounded-lg border border-red-200 " +
  "bg-white px-3 py-1.5 text-sm font-semibold text-red-600 transition hover:bg-red-50 " +
  "disabled:cursor-not-allowed disabled:opacity-50";

export const cardClass = "rounded-xl border border-gray-200 bg-white shadow-sm";

/* ------------------------------------------------------------------ *
 * Spinner / banners / empty state
 * ------------------------------------------------------------------ */
export function Spinner({ label, className = "" }) {
  return (
    <span className={`inline-flex items-center gap-2 text-sm text-gray-500 ${className}`}>
      <span
        className="h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-[var(--brand-primary)]"
        aria-hidden="true"
      />
      {label}
    </span>
  );
}

/** Full-block loading row used inside cards/tables. */
export function LoadingBlock({ label = "Loading…" }) {
  return (
    <div className="flex items-center justify-center px-4 py-10">
      <Spinner label={label} />
    </div>
  );
}

/** Error banner: pulls the first readable message out of the Axios error. */
export function ErrorBanner({ error, onRetry, className = "" }) {
  if (!error) return null;
  return (
    <div
      role="alert"
      className={`flex items-start justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 ${className}`}
    >
      <span>{apiErrorMessage(error)}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 font-semibold text-red-800 underline hover:no-underline"
        >
          Retry
        </button>
      )}
    </div>
  );
}

/** Form-level (non-field) error message string -> red banner. */
export function FormError({ message, className = "" }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      className={`rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 ${className}`}
    >
      {message}
    </div>
  );
}

/** Inline per-field validation message (DRF {field: ["msg"]}). */
export function FieldError({ message }) {
  if (!message) return null;
  return <p className="mt-1 text-xs text-red-600">{message}</p>;
}

export function EmptyState({ title, body, action, className = "" }) {
  return (
    <div className={`px-4 py-12 text-center ${className}`}>
      <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
      {body && <p className="mx-auto mt-1 max-w-sm text-sm text-gray-500">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Status pills - lookup tables of COMPLETE class strings (no templates)
 * ------------------------------------------------------------------ */
const STATUS_STYLES = {
  // Order fulfilment states (Order.Status in the backend).
  pending: "bg-amber-50 text-amber-700 ring-amber-200",
  paid: "bg-blue-50 text-blue-700 ring-blue-200",
  processing: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  shipped: "bg-purple-50 text-purple-700 ring-purple-200",
  delivered: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  cancelled: "bg-gray-100 text-gray-500 ring-gray-200",
  // Business states (Business.Status) + generic flags.
  active: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  suspended: "bg-red-50 text-red-700 ring-red-200",
  blocked: "bg-red-100 text-red-800 ring-red-300",
  inactive: "bg-gray-100 text-gray-500 ring-gray-200",
};

export function StatusBadge({ status, className = "" }) {
  if (!status) return null;
  const style = STATUS_STYLES[status] ?? "bg-gray-100 text-gray-600 ring-gray-200";
  const label = String(status).replaceAll("_", " ");
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ring-1 ring-inset ${style} ${className}`}
    >
      {label}
    </span>
  );
}

/* ------------------------------------------------------------------ *
 * Money - decimal string from DRF -> locale-aware currency formatting
 * ------------------------------------------------------------------ */
export function Money({ value, currency = "USD", className = "" }) {
  const amount = Number(value);
  const code = (currency || "USD").toUpperCase();
  let text;
  try {
    text = new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: code,
    }).format(Number.isFinite(amount) ? amount : 0);
  } catch {
    // Unknown/odd currency code from the tenant table: show plain numbers.
    text = `${Number.isFinite(amount) ? amount.toFixed(2) : "0.00"} ${code}`;
  }
  return <span className={className}>{text}</span>;
}

/* ------------------------------------------------------------------ *
 * Page scaffolding
 * ------------------------------------------------------------------ */
export function PageHeader({ title, subtitle, children }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-gray-900 sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-gray-500">{subtitle}</p>}
      </div>
      {children && <div className="flex items-center gap-2">{children}</div>}
    </div>
  );
}

/** Accessible initials block when a product/logo has no image. */
export function ImagePlaceholder({ label = "?", className = "" }) {
  return (
    <div
      className={`flex items-center justify-center bg-gray-100 text-gray-400 ${className}`}
      aria-hidden="true"
    >
      <span className="text-2xl font-semibold">{label.slice(0, 1).toUpperCase()}</span>
    </div>
  );
}

/** Static star row for product ratings (rating is a number, never a class). */
export function Stars({ rating, count, className = "" }) {
  if (!count) return null;
  return (
    <span className={`inline-flex items-center gap-1 text-xs text-amber-500 ${className}`}>
      <span aria-hidden="true">{"★".repeat(Math.round(rating))}</span>
      <span className="text-gray-400">{"★".repeat(5 - Math.round(rating))}</span>
      <span className="text-gray-500">
        {Number(rating).toFixed(1)} ({count})
      </span>
    </span>
  );
}
