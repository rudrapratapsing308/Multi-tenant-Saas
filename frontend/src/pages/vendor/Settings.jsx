/**
 * Vendor settings - storefront branding (GET/PATCH /api/v1/vendor/settings/).
 *
 * Payload (BrandConfigSerializer):
 *   {brand_name, tagline, logo, favicon, primary_color, secondary_color,
 *    accent_color, is_active, display_name}
 *
 * Colors are HEX STRINGS validated server-side (HEX_COLOR_VALIDATOR +
 * full_clean), so the preview uses inline `style` with the chosen value -
 * NEVER an interpolated Tailwind class. The static utilities around it
 * (borders, layout) come from the standard palette.
 *
 * Uploads: multipart PATCH; DRF 3.16 turns "" into null, which is how the
 * Remove buttons clear logo/favicon. 2 MB cap is enforced on both sides.
 */
import { useEffect, useState } from "react";
import {
  ErrorBanner,
  FieldError,
  FormError,
  LoadingBlock,
  PageHeader,
  cardClass,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "../../components/ui";
import api from "../../api/client";
import useApi, { apiErrorMessage, fieldErrors } from "../../hooks/useApi";

const MAX_IMAGE_BYTES = 2 * 1024 * 1024;

const EMPTY = {
  brand_name: "",
  tagline: "",
  logo: null,
  favicon: null,
  primary_color: "#111827",
  secondary_color: "#6b7280",
  accent_color: "#f59e0b",
  is_active: true,
};

function ColorField({ id, label, value, onChange }) {
  return (
    <div>
      <label className={labelClass} htmlFor={id}>
        {label}
      </label>
      <div className="flex items-center gap-2">
        <input
          type="color"
          aria-label={`${label} picker`}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="h-10 w-12 cursor-pointer rounded-lg border border-gray-300 bg-white p-1"
        />
        <input
          id={id}
          className={inputClass}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="#111827"
        />
      </div>
    </div>
  );
}

export default function Settings() {
  const { data, setData, loading, error, reload } = useApi("/vendor/settings/");

  const [form, setForm] = useState(EMPTY);
  const [logoFile, setLogoFile] = useState(null);
  const [faviconFile, setFaviconFile] = useState(null);
  const [logoPreview, setLogoPreview] = useState(null); // object URL for logoFile
  const [faviconPreview, setFaviconPreview] = useState(null);
  const [clearLogo, setClearLogo] = useState(false);
  const [clearFavicon, setClearFavicon] = useState(false);
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState(null);
  const [saved, setSaved] = useState(false);
  const [errors, setErrors] = useState({});

  // Server payload -> form (runs whenever a fresh GET lands).
  useEffect(() => {
    if (!data) return;
    setForm({
      brand_name: data.brand_name ?? "",
      tagline: data.tagline ?? "",
      logo: data.logo ?? null,
      favicon: data.favicon ?? null,
      primary_color: data.primary_color ?? EMPTY.primary_color,
      secondary_color: data.secondary_color ?? EMPTY.secondary_color,
      accent_color: data.accent_color ?? EMPTY.accent_color,
      is_active: Boolean(data.is_active),
    });
    setLogoFile(null);
    setFaviconFile(null);
    setClearLogo(false);
    setClearFavicon(false);
    setLogoPreview(null);
    setFaviconPreview(null);
  }, [data]);

  const set = (name) => (event) => {
    const value =
      event.target.type === "checkbox" ? event.target.checked : event.target.value;
    setForm((prev) => ({ ...prev, [name]: value }));
    setSaved(false);
  };

  const pickFile = (kind) => (event) => {
    const picked = event.target.files?.[0] ?? null;
    if (!picked) return;
    if (picked.size > MAX_IMAGE_BYTES) {
      setErrors((prev) => ({ ...prev, file: "Image too large - max 2 MB." }));
      event.target.value = "";
      return;
    }
    setErrors({});
    setSaved(false);
    const url = URL.createObjectURL(picked);
    if (kind === "logo") {
      if (logoPreview) URL.revokeObjectURL(logoPreview);
      setLogoFile(picked);
      setClearLogo(false);
      setLogoPreview(url);
    } else {
      if (faviconPreview) URL.revokeObjectURL(faviconPreview);
      setFaviconFile(picked);
      setClearFavicon(false);
      setFaviconPreview(url);
    }
  };

  const onSubmit = async (event) => {
    event.preventDefault();
    setBanner(null);
    setErrors({});
    setSaved(false);

    if (!form.brand_name.trim()) {
      setErrors({ brand_name: "Brand name is required." });
      return;
    }

    const payload = new FormData();
    payload.append("brand_name", form.brand_name.trim());
    payload.append("tagline", form.tagline.trim());
    payload.append("primary_color", form.primary_color.trim());
    payload.append("secondary_color", form.secondary_color.trim());
    payload.append("accent_color", form.accent_color.trim());
    payload.append("is_active", String(form.is_active));
    if (logoFile) payload.append("logo", logoFile);
    else if (clearLogo) payload.append("logo", "");
    if (faviconFile) payload.append("favicon", faviconFile);
    else if (clearFavicon) payload.append("favicon", "");

    setSaving(true);
    try {
      const { data: updated } = await api.patch("/vendor/settings/", payload);
      setData(updated); // re-syncs the form via the effect above
      setSaved(true);
    } catch (err) {
      setBanner(apiErrorMessage(err, "Could not save your settings."));
      setErrors(fieldErrors(err));
    } finally {
      setSaving(false);
    }
  };

  if (loading && !data) return <LoadingBlock label="Loading settings…" />;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} className="p-4" />;

  return (
    <div>
      <PageHeader
        title="Settings"
        subtitle="Brand name, colors and assets shown on your storefront."
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <form onSubmit={onSubmit} noValidate className={`${cardClass} p-5 lg:col-span-2`}>
          <FormError message={banner} className="mb-4" />
          {saved && (
            <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
              Saved. Refresh your storefront tab to see the changes.
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className={labelClass} htmlFor="brand_name">
                Brand name
              </label>
              <input
                id="brand_name"
                className={inputClass}
                value={form.brand_name}
                onChange={set("brand_name")}
              />
              <FieldError message={errors.brand_name} />
            </div>
            <div>
              <label className={labelClass} htmlFor="tagline">
                Tagline
              </label>
              <input
                id="tagline"
                className={inputClass}
                value={form.tagline}
                onChange={set("tagline")}
                placeholder="Wear it proud"
              />
              <FieldError message={errors.tagline} />
            </div>

            <ColorField
              id="primary_color"
              label="Primary color"
              value={form.primary_color}
              onChange={(value) => {
                setForm((prev) => ({ ...prev, primary_color: value }));
                setSaved(false);
              }}
            />
            <ColorField
              id="secondary_color"
              label="Secondary color"
              value={form.secondary_color}
              onChange={(value) => {
                setForm((prev) => ({ ...prev, secondary_color: value }));
                setSaved(false);
              }}
            />
            <ColorField
              id="accent_color"
              label="Accent color"
              value={form.accent_color}
              onChange={(value) => {
                setForm((prev) => ({ ...prev, accent_color: value }));
                setSaved(false);
              }}
            />

            <div className="flex items-end pb-1">
              <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={set("is_active")}
                  className="h-4 w-4 rounded border-gray-300 focus:ring-[var(--brand-primary)]"
                />
                Branding active (falls back to store name when off)
              </label>
            </div>

            {/* Logo */}
            <div>
              <span className={labelClass}>Logo</span>
              <div className="flex items-center gap-3">
                {(logoPreview ?? form.logo) ? (
                  <img
                    src={logoPreview ?? form.logo}
                    alt=""
                    className="h-14 w-14 rounded-lg border border-gray-200 object-contain"
                  />
                ) : (
                  <div className="flex h-14 w-14 items-center justify-center rounded-lg bg-gray-100 text-xs text-gray-400">
                    none
                  </div>
                )}
                <div className="text-xs text-gray-500">
                  <label className="cursor-pointer font-semibold text-[var(--brand-primary)] underline">
                    Upload
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={pickFile("logo")}
                    />
                  </label>
                  {(form.logo || logoFile) && (
                    <button
                      type="button"
                      className="mt-1 block text-red-500 underline"
                      onClick={() => {
                        if (logoPreview) URL.revokeObjectURL(logoPreview);
                        setClearLogo(true);
                        setLogoFile(null);
                        setLogoPreview(null);
                        setForm((prev) => ({ ...prev, logo: null }));
                        setSaved(false);
                      }}
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* Favicon */}
            <div>
              <span className={labelClass}>Favicon</span>
              <div className="flex items-center gap-3">
                {(faviconPreview ?? form.favicon) ? (
                  <img
                    src={faviconPreview ?? form.favicon}
                    alt=""
                    className="h-10 w-10 rounded border border-gray-200 object-contain"
                  />
                ) : (
                  <div className="flex h-10 w-10 items-center justify-center rounded bg-gray-100 text-xs text-gray-400">
                    none
                  </div>
                )}
                <div className="text-xs text-gray-500">
                  <label className="cursor-pointer font-semibold text-[var(--brand-primary)] underline">
                    Upload
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={pickFile("favicon")}
                    />
                  </label>
                  {(form.favicon || faviconFile) && (
                    <button
                      type="button"
                      className="mt-1 block text-red-500 underline"
                      onClick={() => {
                        if (faviconPreview) URL.revokeObjectURL(faviconPreview);
                        setClearFavicon(true);
                        setFaviconFile(null);
                        setFaviconPreview(null);
                        setForm((prev) => ({ ...prev, favicon: null }));
                        setSaved(false);
                      }}
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>
              <FieldError message={errors.file} />
            </div>
          </div>

          <div className="mt-5 flex gap-3">
            <button type="submit" disabled={saving} className={primaryButtonClass}>
              {saving ? "Saving…" : "Save settings"}
            </button>
            <button type="button" onClick={reload} className={secondaryButtonClass}>
              Reset
            </button>
          </div>
        </form>

        {/* Live preview - dynamic hex values go through inline style */}
        <aside className={`${cardClass} h-fit p-5`}>
          <h2 className="text-sm font-semibold text-gray-900">Preview</h2>
          <div className="mt-3 overflow-hidden rounded-xl border border-gray-200">
            <div
              className="px-4 py-3 text-sm font-semibold text-white"
              style={{ backgroundColor: form.primary_color }}
            >
              {form.brand_name || "Your brand"}
            </div>
            <div className="bg-white px-4 py-4">
              <p className="text-sm font-medium text-gray-900">
                {form.tagline || "Your tagline shows up here."}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span
                  className="rounded-md px-3 py-1.5 text-xs font-semibold text-white"
                  style={{ backgroundColor: form.primary_color }}
                >
                  Primary button
                </span>
                <span
                  className="rounded-md px-3 py-1.5 text-xs font-semibold text-white"
                  style={{ backgroundColor: form.secondary_color }}
                >
                  Secondary
                </span>
                <span
                  className="rounded-full px-2.5 py-1 text-xs font-bold text-white"
                  style={{ backgroundColor: form.accent_color }}
                >
                  Accent
                </span>
              </div>
            </div>
          </div>
          <p className="mt-3 text-xs text-gray-400">
            Colors apply to the storefront after the next page load (the theme
            is booted once per visit).
          </p>
        </aside>
      </div>
    </div>
  );
}
