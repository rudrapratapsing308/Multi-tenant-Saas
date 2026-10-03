import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Django dev server. Everything below proxies to it so the browser only ever
// talks to ONE origin (the Vite dev server) in development.
const API = "http://127.0.0.1:8000";

// changeOrigin MUST stay false: the Host header forwarded to Django is then
// the storefront hostname the browser used (e.g. acme.local-saas.com:5173),
// so ALLOWED_HOSTS (.local-saas.com / localhost) validates it AND uploaded
// media/logo URLs are built against the same host the visitor is browsing.
// With changeOrigin: true Django would answer with http://127.0.0.1:8000/...
// links that point away from the tenant.
const proxy = { target: API, changeOrigin: false };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Reachable via the dns_simulator names (acme.local-saas.com:5173 -> 127.0.0.1)
    // as well as plain localhost.
    host: true,
    // Vite rejects unknown Host headers since v6; `true` disables that check so
    // tenant hostnames from dns_simulator pass through.
    allowedHosts: true,
    proxy: {
      // API is same-origin in dev -> no CORS preflights for any request.
      "/api": proxy,
      // Uploaded assets (logos, product images) served by Django in dev;
      // same job is done by a real reverse proxy in production.
      "/media": proxy,
      "/static": proxy,
    },
  },
});
