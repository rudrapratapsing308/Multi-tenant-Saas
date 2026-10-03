/**
 * CartContext - cart state + mutations, with a guest fallback.
 *
 * The backend endpoint (GET/POST/PATCH/DELETE /api/v1/cart/) is authenticated
 * AND tenant-scoped: one cart row per (customer, store). Anonymous shoppers
 * therefore keep their lines in localStorage under a host-scoped key
 * (saas.guest_cart.<hostname>), as the backend's view docstring prescribes.
 *
 * Every mutation returns the backend's full cart payload, so state is a
 * straight replacement - no optimistic merge arithmetic:
 *
 *   addItem({productId, variantId?, quantity, snapshot?})
 *   setQuantity(line, quantity)   // 0 removes the line (both modes)
 *   removeLine(line)              // == setQuantity(line, 0)
 *   clearCart()
 *   refresh()
 *
 * `snapshot` ({name, slug, image, price}) is only used for GUEST display and
 * the guest subtotal estimate; once the user logs in the lines are adopted by
 * POSTing them to the backend (the real price/stock check happens there) and
 * the server becomes the single source of truth.
 *
 * Server line identity:  line.id        (CartItem pk)
 * Guest line identity:   line.key       ("<productId>:<variantId|0>")
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import api, { currentHost } from "../api/client";
import { useAuth } from "./AuthContext";

const CartContext = createContext(null);

export function useCart() {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error("useCart must be used inside <CartProvider>");
  return ctx;
}

// Host-scoped: browsing store A as a guest never leaks lines into store B.
const guestKey = () => `saas.guest_cart.${currentHost()}`;

function readGuestLines() {
  try {
    const lines = JSON.parse(localStorage.getItem(guestKey()) ?? "[]");
    return Array.isArray(lines) ? lines : [];
  } catch {
    return [];
  }
}

function writeGuestLines(lines) {
  if (lines.length) localStorage.setItem(guestKey(), JSON.stringify(lines));
  else localStorage.removeItem(guestKey());
}

const guestKeyOf = (productId, variantId) => `${productId}:${variantId ?? 0}`;

export function CartProvider({ children }) {
  const { status: authStatus } = useAuth();
  const authenticated = authStatus === "authenticated";

  const [cart, setCart] = useState(null); // server payload (null = no cart yet)
  const [guestLines, setGuestLines] = useState(readGuestLines);
  const [loading, setLoading] = useState(false);

  // Adoption guards: `adoptingRef` makes adoption idempotent under
  // StrictMode's double-invoked effects; `adoptFailedRef` stops a failing
  // backend from turning the effect below into an infinite retry loop (a new
  // addItem() re-arms it).
  const adoptingRef = useRef(false);
  const adoptFailedRef = useRef(false);

  // Load the right cart once auth is settled.
  useEffect(() => {
    if (authStatus === "loading") return;

    if (!authenticated) {
      setCart(null);
      setGuestLines(readGuestLines()); // re-read: another tab may have written
      return;
    }

    let cancelled = false;
    setLoading(true);
    api
      .get("/cart/")
      .then(({ data }) => {
        // While adoption is in flight its own refetch owns `cart` - a racing
        // "empty server cart" response must not clobber adopted lines.
        if (!cancelled && !adoptingRef.current) setCart(data);
        if (!cancelled) adoptFailedRef.current = false;
      })
      .catch(() => {
        if (!cancelled) setCart(null); // 401 handled centrally in client.js
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [authStatus, authenticated]);

  // Adopt the guest cart after login.
  useEffect(() => {
    if (!authenticated || !guestLines.length) return;
    if (adoptingRef.current || adoptFailedRef.current) return;
    adoptingRef.current = true;

    const lines = [...guestLines];
    // Claim the queue SYNCHRONOUSLY (before any await): a StrictMode
    // double-run sees an empty queue and cannot double-POST the lines.
    writeGuestLines([]);
    setGuestLines([]);

    (async () => {
      try {
        for (const line of lines) {
          // Backend re-validates price/stock/per-store id; quantity tops up.
          await api.post("/cart/", {
            product_id: line.productId,
            variant_id: line.variantId ?? null,
            quantity: line.quantity,
          });
        }
        const { data } = await api.get("/cart/");
        setCart(data);
      } catch {
        // Give the lines back and let the visitor retry (next addItem re-arms
        // the flag); the loop guard prevents hammering a down backend.
        writeGuestLines(lines);
        setGuestLines(lines);
        adoptFailedRef.current = true;
      } finally {
        adoptingRef.current = false;
      }
    })();
  }, [authenticated, guestLines]);

  const addItem = useCallback(
    async ({ productId, variantId = null, quantity = 1, snapshot = null }) => {
      if (authenticated) {
        const { data } = await api.post("/cart/", {
          product_id: productId,
          variant_id: variantId,
          quantity,
        });
        setCart(data);
        return data;
      }

      // Guest: top up by (product, variant) exactly like the backend does.
      const lines = readGuestLines();
      const key = guestKeyOf(productId, variantId);
      const existing = lines.find((line) => line.key === key);
      if (existing) {
        existing.quantity = Math.min(999, existing.quantity + quantity);
      } else {
        lines.push({ key, productId, variantId, quantity, ...(snapshot ?? {}) });
      }
      writeGuestLines(lines);
      setGuestLines(lines);
      adoptFailedRef.current = false; // new visitor intent -> re-arm adoption
      return lines;
    },
    [authenticated]
  );

  const setQuantity = useCallback(
    async (line, quantity) => {
      if (authenticated) {
        // quantity 0 deletes the line server-side (see cart/views.py).
        const { data } = await api.patch("/cart/", {
          item_id: line.id,
          quantity,
        });
        setCart(data);
        return data;
      }

      let lines = readGuestLines();
      if (quantity <= 0) {
        lines = lines.filter((entry) => entry.key !== line.key);
      } else {
        lines = lines.map((entry) =>
          entry.key === line.key
            ? { ...entry, quantity: Math.min(999, quantity) }
            : entry
        );
      }
      writeGuestLines(lines);
      setGuestLines(lines);
      return lines;
    },
    [authenticated]
  );

  const removeLine = useCallback(
    (line) => setQuantity(line, 0),
    [setQuantity]
  );

  const clearCart = useCallback(async () => {
    if (authenticated) {
      const { data } = await api.delete("/cart/"); // no item_id -> empty it
      setCart(data);
      return data;
    }
    writeGuestLines([]);
    setGuestLines([]);
    return [];
  }, [authenticated]);

  const refresh = useCallback(async () => {
    if (!authenticated) {
      const lines = readGuestLines();
      setGuestLines(lines);
      return lines;
    }
    const { data } = await api.get("/cart/");
    setCart(data);
    return data;
  }, [authenticated]);

  const value = useMemo(() => {
    const lines = authenticated ? (cart?.items ?? []) : guestLines;
    const itemCount = authenticated
      ? cart?.item_count ?? 0 // backend: sum of quantities
      : guestLines.reduce((sum, line) => sum + line.quantity, 0);
    // Guest subtotal is an ESTIMATE from the snapshot prices the product page
    // handed us; the authoritative total is the server's (live prices).
    const subtotal = authenticated
      ? cart?.subtotal ?? "0.00"
      : guestLines
          .reduce(
            (sum, line) =>
              sum + (line.price != null ? Number(line.price) * line.quantity : 0),
            0
          )
          .toFixed(2);

    return {
      cart, // full backend payload or null
      guestLines,
      lines, // convenience: whichever list is authoritative right now
      itemCount,
      subtotal,
      loading,
      isGuest: !authenticated,
      addItem,
      setQuantity,
      removeLine,
      clearCart,
      refresh,
    };
  }, [
    authenticated,
    cart,
    guestLines,
    loading,
    addItem,
    setQuantity,
    removeLine,
    clearCart,
    refresh,
  ]);

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}
