/**
 * useApi - the page-level data hook every Module-6 page shares.
 *
 *   const { data, loading, error, reload } = useApi("/vendor/orders/");
 *   const { data, ... } = useApi("/catalog/products/", { params: { search } });
 *
 * Behaviour contract:
 *   * one GET per (path, params) combination, cancelled if the component
 *     unmounts or the params change mid-flight (no setState-after-unmount),
 *   * `loading` is true only while that request is in flight,
 *   * `error` is the RAW Axios error - render it with `apiErrorMessage()`,
 *   * `reload()` refetches after any mutation that changes the collection,
 *   * `setData` splices a fresh payload in without a refetch (PATCH/POST
 *     actions answer with the updated row, so no round-trip is needed),
 *   * `enabled: false` parks the hook until it flips (route-param gates).
 *
 * `params` is JSON-serialised for the effect key: a NEW object with the
 * same contents does NOT refetch (stable deps without useCallback games).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import api from "../api/client";

export default function useApi(path, { params = null, enabled = true } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(() => Boolean(path) && enabled);
  const [tick, setTick] = useState(0);

  const paramsKey = JSON.stringify(params ?? null);
  const query = useMemo(() => JSON.parse(paramsKey), [paramsKey]);

  useEffect(() => {
    if (!enabled || !path) {
      setLoading(false);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    api
      .get(path, { params: query })
      .then(({ data: payload }) => {
        if (!cancelled) setData(payload);
      })
      .catch((err) => {
        // A cancelled request is a *deliberate* supersede, not a failure.
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [path, paramsKey, enabled, tick, query]);

  const reload = useCallback(() => setTick((n) => n + 1), []);

  return { data, setData, loading, error, reload };
}

/**
 * First human-readable message inside a DRF/Axios error.
 *
 * Handles every shape the backend answers with:
 *   {detail: "..."}                       field/global serializer error
 *   {error: "code", detail: "..."}        CheckoutError / middleware codes
 *   {field: ["msg", ...]}                 per-field validation
 *   ["msg"]                               non-field list
 *   network failure (no response)         API not running
 */
export function apiErrorMessage(error, fallback = "Something went wrong. Please try again.") {
  if (!error?.response) {
    return "Cannot reach the server. Is the API running on port 8000?";
  }
  const data = error.response.data;

  if (typeof data?.detail === "string" && data.detail) return data.detail;
  if (Array.isArray(data) && data.length) return data.join(" ");
  if (typeof data === "string" && data) return data;

  if (data && typeof data === "object") {
    for (const value of Object.values(data)) {
      if (Array.isArray(value) && value.length) return value.join(" ");
      if (typeof value === "string" && value) return value;
    }
  }
  if (error.response.status === 403) {
    return "You do not have permission to do that.";
  }
  if (error.response.status === 404) {
    return "Not found.";
  }
  return fallback;
}

/**
 * Per-field messages for inline form errors: {email: "This field is required."}
 * Global/detail messages are intentionally NOT in here (they belong in a banner).
 */
export function fieldErrors(error) {
  const data = error?.response?.data;
  const out = {};
  if (data && typeof data === "object" && !Array.isArray(data)) {
    for (const [key, value] of Object.entries(data)) {
      if (key === "detail" || key === "error") continue;
      if (Array.isArray(value) && value.length) out[key] = value.join(" ");
      else if (typeof value === "string" && value) out[key] = value;
    }
  }
  return out;
}
