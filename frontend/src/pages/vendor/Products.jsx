/**
 * Vendor products - full CRUD (table + create/edit form with image upload).
 *
 * Endpoints:
 *   GET    /api/v1/vendor/products/          list (tenant-scoped)
 *   POST   /api/v1/vendor/products/          create  (multipart)
 *   PATCH  /api/v1/vendor/products/<id>/     update  (multipart)
 *   DELETE /api/v1/vendor/products/<id>/     delete  (cleans up the image file)
 *   GET    /api/v1/vendor/categories/        category <select> options
 *
 * Why FormData for BOTH create and update:
 *   * the form may carry an image upload (DRF MultiPartParser is enabled);
 *   * DRF 3.16 coerces "" -> None for allow_null fields, so a blank
 *     nullable field CLEARS server-side (multipart has no null);
 *   * booleans travel as "true"/"false" strings (DRF BooleanField accepts
 *     them; the model keeps its defaults when a key is omitted).
 *
 * Validation: client checks required fields + the 2 MB image cap, but the
 * server is the referee - 400 {field: ["msg"]} lands inline via
 * fieldErrors(), everything else in the banner (slug uniqueness per store,
 * compare-at price rule, positive money - all raised by full_clean()).
 */
import { useMemo, useState } from "react";
import {
  EmptyState,
  ErrorBanner,
  FormError,
  FieldError,
  ImagePlaceholder,
  LoadingBlock,
  Money,
  PageHeader,
  StatusBadge,
  cardClass,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
  dangerButtonClass,
} from "../../components/ui";
import { useTenant } from "../../context/TenantContext";
import api from "../../api/client";
import useApi, { apiErrorMessage, fieldErrors } from "../../hooks/useApi";

const MAX_IMAGE_BYTES = 2 * 1024 * 1024; // mirrors backend MAX_UPLOAD_BYTES

const EMPTY_FORM = {
  name: "",
  description: "",
  sku: "",
  category: "",
  price: "",
  compare_at_price: "",
  stock: "0",
  is_active: true,
  is_featured: false,
};

export default function Products() {
  const { store } = useTenant();
  const currency = store?.currency ?? "USD";

  const {
    data: products,
    loading,
    error,
    reload,
  } = useApi("/vendor/products/");
  const { data: categories } = useApi("/vendor/categories/");

  // Form state -----------------------------------------------------------
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null); // product | null = create
  const [form, setForm] = useState(EMPTY_FORM);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [clearImage, setClearImage] = useState(false);
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState(null);
  const [errors, setErrors] = useState({});
  const [deletingId, setDeletingId] = useState(null);

  const categoryName = useMemo(() => {
    const map = new Map();
    for (const cat of categories ?? []) map.set(cat.id, cat.name);
    return map;
  }, [categories]);

  const set = (name) => (event) => {
    const value =
      event.target.type === "checkbox" ? event.target.checked : event.target.value;
    setForm((prev) => ({ ...prev, [name]: value }));
  };

  const openForm = (product = null) => {
    setEditing(product);
    setBanner(null);
    setErrors({});
    setFile(null);
    setClearImage(false);
    setPreview(product?.image ?? null);
    setForm(
      product
        ? {
            name: product.name ?? "",
            description: product.description ?? "",
            sku: product.sku ?? "",
            category: product.category ?? "",
            price: product.price ?? "",
            compare_at_price: product.compare_at_price ?? "",
            stock: String(product.stock ?? 0),
            is_active: Boolean(product.is_active),
            is_featured: Boolean(product.is_featured),
          }
        : EMPTY_FORM
    );
    setOpen(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const closeForm = () => {
    if (preview?.startsWith("blob:")) URL.revokeObjectURL(preview);
    setOpen(false);
    setEditing(null);
    setFile(null);
    setPreview(null);
  };

  const onPickImage = (event) => {
    const picked = event.target.files?.[0] ?? null;
    if (!picked) return;
    if (picked.size > MAX_IMAGE_BYTES) {
      setErrors((prev) => ({ ...prev, image: "Image too large - max 2 MB." }));
      event.target.value = "";
      return;
    }
    if (!picked.type.startsWith("image/")) {
      setErrors((prev) => ({ ...prev, image: "Only image files are allowed." }));
      event.target.value = "";
      return;
    }
    if (preview?.startsWith("blob:")) URL.revokeObjectURL(preview);
    setErrors((prev) => ({ ...prev, image: undefined }));
    setFile(picked);
    setClearImage(false);
    setPreview(URL.createObjectURL(picked));
  };

  const onSubmit = async (event) => {
    event.preventDefault();
    setBanner(null);
    setErrors({});

    // Client-side required checks (server re-validates regardless).
    const next = {};
    if (!form.name.trim()) next.name = "Name is required.";
    const price = Number(form.price);
    if (!form.price.trim() || !Number.isFinite(price) || price <= 0) {
      next.price = "Enter a price above 0.";
    }
    if (form.compare_at_price.trim() && Number(form.compare_at_price) <= 0) {
      next.compare_at_price = "Must be above 0 (or leave blank).";
    }
    if (Object.keys(next).length) {
      setErrors(next);
      return;
    }

    const payload = new FormData();
    payload.append("name", form.name.trim());
    payload.append("description", form.description.trim());
    payload.append("sku", form.sku.trim());
    payload.append("category", form.category || "");
    payload.append("price", form.price.trim());
    payload.append("compare_at_price", form.compare_at_price.trim());
    payload.append("stock", String(Number(form.stock) || 0));
    payload.append("is_active", String(form.is_active));
    payload.append("is_featured", String(form.is_featured));
    if (file) payload.append("image", file);
    else if (clearImage) payload.append("image", ""); // "" -> null (clear)

    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/vendor/products/${editing.id}/`, payload);
      } else {
        await api.post("/vendor/products/", payload);
      }
      closeForm();
      reload();
    } catch (err) {
      setBanner(apiErrorMessage(err, "Could not save the product."));
      setErrors(fieldErrors(err));
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async (product) => {
    if (!window.confirm(`Delete "${product.name}"? This cannot be undone.`)) return;
    setDeletingId(product.id);
    setBanner(null);
    try {
      await api.delete(`/vendor/products/${product.id}/`);
      reload();
    } catch (err) {
      setBanner(apiErrorMessage(err, "Could not delete the product."));
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div>
      <PageHeader
        title="Products"
        subtitle="Your catalog for this store - prices, stock and visibility."
      >
        <button
          type="button"
          onClick={() => (open ? closeForm() : openForm())}
          className={open ? secondaryButtonClass : primaryButtonClass}
        >
          {open ? "Close form" : "+ Add product"}
        </button>
      </PageHeader>

      {banner && !open && <FormError message={banner} className="mb-4" />}

      {/* --------------------------- create/edit form --------------------------- */}
      {open && (
        <form
          onSubmit={onSubmit}
          noValidate
          className={`${cardClass} mb-6 p-5`}
        >
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-900">
              {editing ? `Edit: ${editing.name}` : "New product"}
            </h2>
            <button
              type="button"
              onClick={closeForm}
              className="text-sm text-gray-400 hover:text-gray-600"
              aria-label="Close form"
            >
              ✕
            </button>
          </div>

          <FormError message={banner} className="mb-4" />

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label className={labelClass} htmlFor="p-name">
                Name *
              </label>
              <input
                id="p-name"
                className={inputClass}
                value={form.name}
                onChange={set("name")}
                placeholder="Classic Tee"
              />
              <FieldError message={errors.name} />
            </div>

            <div className="sm:col-span-2">
              <label className={labelClass} htmlFor="p-description">
                Description
              </label>
              <textarea
                id="p-description"
                rows={3}
                className={inputClass}
                value={form.description}
                onChange={set("description")}
                placeholder="Fabric, fit, care instructions…"
              />
              <FieldError message={errors.description} />
            </div>

            <div>
              <label className={labelClass} htmlFor="p-category">
                Category
              </label>
              <select
                id="p-category"
                className={inputClass}
                value={form.category}
                onChange={set("category")}
              >
                <option value="">Uncategorized</option>
                {(categories ?? []).map((cat) => (
                  <option key={cat.id} value={cat.id}>
                    {cat.name}
                  </option>
                ))}
              </select>
              <FieldError message={errors.category} />
            </div>

            <div>
              <label className={labelClass} htmlFor="p-sku">
                SKU
              </label>
              <input
                id="p-sku"
                className={inputClass}
                value={form.sku}
                onChange={set("sku")}
                placeholder="TEE-001"
              />
              <FieldError message={errors.sku} />
            </div>

            <div>
              <label className={labelClass} htmlFor="p-price">
                Price ({currency}) *
              </label>
              <input
                id="p-price"
                type="number"
                step="0.01"
                min="0.01"
                className={inputClass}
                value={form.price}
                onChange={set("price")}
                placeholder="29.99"
              />
              <FieldError message={errors.price} />
            </div>

            <div>
              <label className={labelClass} htmlFor="p-compare">
                Compare-at price <span className="text-gray-400">(was…)</span>
              </label>
              <input
                id="p-compare"
                type="number"
                step="0.01"
                min="0"
                className={inputClass}
                value={form.compare_at_price}
                onChange={set("compare_at_price")}
                placeholder="Optional"
              />
              <FieldError message={errors.compare_at_price} />
            </div>

            <div>
              <label className={labelClass} htmlFor="p-stock">
                Stock
              </label>
              <input
                id="p-stock"
                type="number"
                min="0"
                step="1"
                className={inputClass}
                value={form.stock}
                onChange={set("stock")}
              />
              <FieldError message={errors.stock} />
              <p className="mt-1 text-xs text-gray-400">
                Base stock (products with variants track stock per variant).
              </p>
            </div>

            {/* Image upload */}
            <div>
              <span className={labelClass}>Image</span>
              <div className="flex items-center gap-3">
                {preview ? (
                  <img
                    src={preview}
                    alt=""
                    className="h-16 w-16 rounded-lg border border-gray-200 object-cover"
                  />
                ) : (
                  <ImagePlaceholder label={form.name || "?"} className="h-16 w-16 rounded-lg" />
                )}
                <div className="text-xs text-gray-500">
                  <label className="cursor-pointer font-semibold text-[var(--brand-primary)] underline">
                    {file ? "Choose a different image" : "Upload image"}
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={onPickImage}
                    />
                  </label>
                  <p className="mt-1">JPG/PNG, max 2 MB.</p>
                  {!file && preview && (
                    <button
                      type="button"
                      className="mt-1 block text-red-500 underline"
                      onClick={() => {
                        setClearImage(true);
                        setFile(null);
                        setPreview(null);
                      }}
                    >
                      Remove image
                    </button>
                  )}
                </div>
              </div>
              <FieldError message={errors.image} />
            </div>

            {/* Flags */}
            <div className="flex items-end gap-6 pb-1">
              <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={set("is_active")}
                  className="h-4 w-4 rounded border-gray-300 text-[var(--brand-primary)] focus:ring-[var(--brand-primary)]"
                />
                Active (visible in store)
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={form.is_featured}
                  onChange={set("is_featured")}
                  className="h-4 w-4 rounded border-gray-300 text-[var(--brand-primary)] focus:ring-[var(--brand-primary)]"
                />
                Featured
              </label>
            </div>
          </div>

          <div className="mt-5 flex gap-3">
            <button type="submit" disabled={saving} className={primaryButtonClass}>
              {saving ? "Saving…" : editing ? "Save changes" : "Create product"}
            </button>
            <button type="button" onClick={closeForm} className={secondaryButtonClass}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* ------------------------------- table ------------------------------- */}
      <div className={`${cardClass} overflow-hidden`}>
        {loading ? (
          <LoadingBlock label="Loading products…" />
        ) : error ? (
          <ErrorBanner error={error} onRetry={reload} className="m-4" />
        ) : (products ?? []).length === 0 ? (
          <EmptyState
            title="No products yet"
            body="Add your first product to start selling on this store."
            action={
              <button type="button" onClick={() => openForm()} className={primaryButtonClass}>
                + Add product
              </button>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-gray-200 bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-4 py-3 font-medium">Product</th>
                  <th className="px-4 py-3 font-medium">Category</th>
                  <th className="px-4 py-3 font-medium">Price</th>
                  <th className="px-4 py-3 font-medium">Stock</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {products.map((product) => (
                  <tr key={product.id} className="transition hover:bg-gray-50/70">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        {product.image ? (
                          <img
                            src={product.image}
                            alt=""
                            className="h-10 w-10 rounded-lg border border-gray-100 object-cover"
                          />
                        ) : (
                          <ImagePlaceholder
                            label={product.name}
                            className="h-10 w-10 rounded-lg"
                          />
                        )}
                        <div className="min-w-0">
                          <p className="truncate font-medium text-gray-900">
                            {product.name}
                          </p>
                          <p className="truncate text-xs text-gray-400">
                            {product.sku || `#${product.id}`}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-600">
                      {product.category
                        ? (categoryName.get(product.category) ?? "—")
                        : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-3 font-medium text-gray-900">
                      <Money value={product.price} currency={currency} />
                      {product.compare_at_price && (
                        <Money
                          value={product.compare_at_price}
                          currency={currency}
                          className="ml-1.5 text-xs text-gray-400 line-through"
                        />
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={
                          product.total_stock > 0
                            ? "text-gray-700"
                            : "font-medium text-red-600"
                        }
                      >
                        {product.total_stock}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        <StatusBadge status={product.is_active ? "active" : "inactive"} />
                        {product.is_featured && (
                          <span className="inline-flex items-center rounded-full bg-[var(--brand-accent)]/15 px-2.5 py-0.5 text-xs font-medium text-[var(--brand-accent)]">
                            Featured
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => openForm(product)}
                          className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 transition hover:bg-gray-50"
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          disabled={deletingId === product.id}
                          onClick={() => onDelete(product)}
                          className={dangerButtonClass}
                        >
                          {deletingId === product.id ? "Deleting…" : "Delete"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
