export function money(cents: number, interval?: string | null) {
  const v = cents % 100 === 0 ? `$${(cents / 100).toLocaleString()}` : `$${(cents / 100).toFixed(2)}`;
  return interval ? `${v}/${interval === "month" ? "mo" : "yr"}` : v;
}

export function num(n: number | undefined | null, digits = 0) {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function ago(iso: string | null | undefined) {
  if (!iso) return "never";
  const t = new Date(iso.endsWith("Z") ? iso : iso + "Z").getTime();
  const s = Math.max(1, Math.round((Date.now() - t) / 1000));
  if (s < 60) return "just now";
  const m = Math.round(s / 60); if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60); if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24); if (d < 30) return `${d} d ago`;
  return new Date(t).toLocaleDateString();
}

export function date(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso.endsWith("Z") ? iso : iso + "Z").toLocaleDateString(undefined,
    { year: "numeric", month: "short", day: "numeric" });
}

export function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0]!.toUpperCase()).join("") || "?";
}

export const cx = (...a: (string | false | null | undefined)[]) => a.filter(Boolean).join(" ");

/** A part envelope (mm) in the user's units: "120 × 80 × 10 mm" or "4.72 × 3.15 × 0.39 in". */
export function size(bbox: number[] | undefined | null, units?: "mm" | "in") {
  if (!bbox?.length) return "";
  return units === "in"
    ? `${bbox.map(n => (n / 25.4).toFixed(2).replace(/\.?0+$/, "")).join(" × ")} in`
    : `${bbox.map(n => Math.round(n)).join(" × ")} mm`;
}

/** Page width shared by every platform page, so titles never jump sideways between nav items. */
export const PAGE = "mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-8";
