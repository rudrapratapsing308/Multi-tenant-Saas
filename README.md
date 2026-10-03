# Multi-Tenant E-commerce SaaS

A full-stack, **multi-tenant e-commerce platform**: one backend process serves many
independent storefronts, each identified purely by its hostname. A request for
`acme.local-saas.com` and a request for `nike.local-saas.com` hit the *same* Django
app, the *same* tables - and are isolated by a single `business_id` discriminator that
every queryset must filter on. Cross-store access returns **404**, never another
tenant's data.

Three role-based experiences ship with the platform:

| Experience | Who | What it does |
|---|---|---|
| **Storefront** | Customers | Browse, search, product detail & reviews, cart, vouchers, checkout, order history |
| **Vendor dashboard** | Vendors | Products (CRUD + image upload), order fulfilment with a strict status state machine, analytics, store settings & branding |
| **Platform console** | Super admins | Every store on the platform, revenue/order/customer metrics, suspend & activate tenants |

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Django 5.2 + Django REST Framework 3.16 - **JSON API only** (`/api/v1/...`), no HTML |
| Authentication | JWT (`djangorestframework-simplejwt`), roles: `customer` / `vendor` / `super_admin` |
| Database | SQLite (dev), behind the standard Django ORM |
| Frontend | React 19 + React Router 7, bundled by Vite 8 |
| Styling | Tailwind CSS 4 - standard utilities for layout, brand colors via inline `style` (never interpolated class strings) |
| Dev HTTP | Vite dev server proxies `/api`, `/media`, `/static` to Django - one origin, no CORS friction |
| DNS | `dns_simulator.py` (dnslib) - wildcard `*.local-saas.com` → `127.0.0.1`, everything else forwarded upstream |
| Tests | Django test runner - **184 tests**, including explicit tenant-isolation suites |

---

## Project layout

```
PBL project/
├── backend/                  Django + DRF JSON API
│   ├── apps/
│   │   ├── tenants/          Business/Domain kernel + middleware (Host -> tenant)
│   │   ├── accounts/         Users, roles, memberships, store links
│   │   ├── catalog/          Categories, products, variants, reviews
│   │   ├── cart/             Per-tenant carts (guest + authenticated)
│   │   ├── orders/           Checkout, vouchers, status state machine
│   │   ├── storefront/       Public storefront API (bootstrap, products, search)
│   │   ├── vendor/           Vendor dashboard API (CRUD, orders, analytics, settings)
│   │   ├── superadmin/       Platform console API (tenant-exempt)
│   │   ├── promotions/       Vouchers & discounts
│   │   ├── analytics/        ORM-aggregated metrics
│   │   └── core/             Shared model helpers
│   ├── config/settings/      development.py / production.py
│   ├── db/db.sqlite3         SQLite database (dev)
│   └── manage.py
├── frontend/                 React + Vite + Tailwind SPA
│   └── src/
│       ├── pages/storefront/ Home, ProductDetail, Cart, Checkout, Layout
│       ├── pages/vendor/     Overview, Orders, Products, Analytics, Settings
│       ├── pages/superadmin/ PlatformOverview
│       ├── pages/auth/       Login / Register (all areas)
│       ├── components/       UI kit, route guards, boot screens
│       └── hooks/            Shared data-fetching hook
├── dns_simulator.py          Local resolver for *.local-saas.com
├── seed_demo.py              Idempotent demo-data seeder
├── start_dev.bat             One-shot local launcher (this is the entry point)
└── README.md
```

---

## Prerequisites

* **Python 3.13+** and **Node.js 20+** on `PATH`
* Packages:
  ```powershell
  pip install -r backend/requirements.txt
  pip install dnslib            # only needed for branded hostnames (see below)
  ```
* Frontend dependencies (the launcher installs these automatically on first run):
  ```powershell
  cd frontend
  npm install
  cd ..
  ```

---

## Quick start

Double-click **`start_dev.bat`** (or run it from a terminal). It performs, in order:

1. **Migrations** - `python backend/manage.py migrate`
2. **Seed** - `python seed_demo.py` (idempotent: creates demo stores/users/catalog
   only if missing; your data is never touched)
3. **Three services, each in its own console window:**

   | Window | Command | URL |
   |---|---|---|
   | Django backend | `python backend/manage.py runserver 0.0.0.0:8000` | http://localhost:8000 |
   | React frontend | `npm run dev` (in `frontend/`) | http://localhost:5173 |
   | DNS simulator *(optional)* | `python dns_simulator.py` | port 53 - needs Administrator |

4. Prints the URLs, then leaves the service windows running. Closing those windows
   stops the services.

> From a terminal, `start_dev.bat /nopause` skips the final "press any key" pause.

### Opening the app

| What you want | URL |
|---|---|
| **Storefront** (demo store) | http://localhost:5173 |
| **Vendor dashboard** (login) | http://localhost:5173/admin/login |
| **SuperAdmin console** (login) | http://localhost:5173/superadmin/login |

### Demo accounts

| Email | Role | Password | Logs into |
|---|---|---|---|
| `boss@platform.test` | Super admin | `s3cret-pass-1` | Platform console |
| `owner@acme.test` | Vendor (owner of *Acme Threads*) | `s3cret-pass-1` | Vendor dashboard |
| *(any email you choose)* | Customer | *(you pick it)* | Self-signup at `/register` |

Vendors can also be created through the UI at `/admin/register` ("Create your store"),
which provisions a new business with its own `<your-store>.local-saas.com` hostname.

---

## SuperAdmin console vs. tenant storefronts

The distinction is **hostname-driven**:

* The **SuperAdmin console** (`/superadmin/...`) is *tenant-independent* - it works on
  any host, including plain `localhost`. Its API lives under `/api/v1/superadmin/`
  and is deliberately exempt from tenant resolution, because a platform operator must
  see *all* stores.
* Everything else (`/`, `/products/...`, `/cart`, `/checkout`, `/admin/...`) resolves
  the tenant from the request **`Host` header** before it reaches a view:
  `Host` → `Domain` → `Business`. Unknown hosts get a JSON 404; suspended stores get
  `403 store unavailable`.

### Without DNS (default)

The seeder maps `localhost` to the **Acme Threads** demo store, so everything works
immediately:

```
http://localhost:5173                  -> Acme Threads storefront
http://localhost:5173/admin/login      -> vendor dashboard (owner@acme.test)
http://localhost:5173/superadmin/login -> platform console (boss@platform.test)
```

### With branded hostnames (the full multi-tenant experience)

Each store on its own hostname, exactly as production would serve it:

```
http://acme.local-saas.com:5173        -> Acme Threads storefront
http://nike.local-saas.com:5173        -> Nike Store storefront
http://acme.local-saas.com:5173/admin  -> Acme's vendor dashboard
```

Two ways to make `*.local-saas.com` resolve:

**Option A - DNS simulator (Administrator required)**

```powershell
python dns_simulator.py          # run in an elevated terminal, or re-run
                                 # start_dev.bat via "Run as administrator"
nslookup acme.local-saas.com 127.0.0.1     # sanity check -> 127.0.0.1
```

Then point your OS resolver at it (elevated; adapter name from
`netsh interface show interface`):

```powershell
netsh interface ip set   dns name="Wi-Fi" static 127.0.0.1
netsh interface ip add   dns name="Wi-Fi" 8.8.8.8 index=2     # fallback
ipconfig /flushdns
# revert later:
netsh interface ip set dns name="Wi-Fi" source=dhcp
```

**Option B - hosts file (no admin DNS, one-off per hostname)**

Add to `C:\Windows\System32\drivers\etc\hosts`:

```
127.0.0.1 acme.local-saas.com
127.0.0.1 nike.local-saas.com
```

The frontend, backend, CORS, and CSRF settings are already configured for these
hosts (`allowedHosts`, `.local-saas.com` in `ALLOWED_HOSTS`, origin regexes) - no
extra configuration is needed.

---

## Manual start (without the script)

```powershell
# terminal 1 - API
python backend\manage.py runserver 0.0.0.0:8000

# terminal 2 - SPA
cd frontend
npm run dev

# terminal 3 - DNS simulator (elevated prompt, optional)
python dns_simulator.py
```

First-time setup instead of the launcher:

```powershell
python backend\manage.py migrate
python seed_demo.py
```

---

## Tests

```powershell
python backend/manage.py test apps.tenants apps.storefront apps.accounts apps.catalog apps.cart apps.orders apps.vendor apps.superadmin
```

**184 tests, all green.** The suite explicitly verifies multi-tenancy: a product id
from one store is meaningless on another store's host, cross-store reads answer 404,
and vendor/superadmin endpoints enforce both role and tenant.

---

## API notes

* Base path: `/api/v1/` (auth, storefront, cart, checkout, orders, vendor, superadmin).
* Tenant comes from the `Host` header; in dev, `X-Forwarded-Host` is trusted so the
  frontend can announce which storefront it renders.
* Uploaded media (`/media/...`) and static files are served by Django in development;
  Vite proxies them so the browser only ever talks to one origin.
* Register answers `201`, login answers `200`; product/cart/order payload shapes are
  documented in the serializers under `backend/apps/*/serializers.py`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Port 8000 already in use` | Another Django instance is running - close its window or stop it in Task Manager |
| Storefront shows the boot/error screen on an unknown host | That hostname has no `Domain` row - use `localhost`, or add the host via the seed/Django shell |
| Branded hosts don't resolve | Use Option B (hosts file), or run the DNS simulator as Administrator |
| Want a clean slate | Delete `backend\db\db.sqlite3`, then re-run `start_dev.bat` - it migrates and reseeds from scratch |
| `dnslib` import error | `pip install dnslib` (only needed for the DNS simulator) |

---

## Resetting demo data

```powershell
del backend\db\db.sqlite3
python backend\manage.py migrate
python seed_demo.py
```

Or simply delete the database and run `start_dev.bat` - it does both steps for you.
