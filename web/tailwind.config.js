/** @type {import('tailwindcss').Config} */
const c = (v) => `rgb(var(--${v}) / <alpha-value>)`;
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class"],
  theme: {
    extend: {
      fontFamily: { sans: ['"Inter Variable"', "Inter", "Segoe UI", "system-ui", "sans-serif"],
                    mono: ["ui-monospace", "Cascadia Code", "Consolas", "monospace"] },
      colors: {
        bg: c("bg"), panel: c("panel"), panel2: c("panel-2"), border: c("border"), text: c("text"),
        muted: c("muted"), primary: c("primary"), "primary-fg": c("primary-fg"), "primary-soft": c("primary-soft"),
        accent: c("accent"), success: c("success"), warning: c("warning"), danger: c("danger"),
        chrome: c("chrome"), "chrome-2": c("chrome-2"), "chrome-fg": c("chrome-fg"), "chrome-muted": c("chrome-muted"),
      },
      borderRadius: { DEFAULT: "6px", lg: "10px", xl: "14px" },
      boxShadow: { card: "0 1px 2px rgb(16 24 40 / .06), 0 1px 3px rgb(16 24 40 / .08)",
                   pop: "0 12px 32px rgb(16 24 40 / .18)" },
      keyframes: { "fade-in": { from: { opacity: 0, transform: "translateY(4px)" }, to: { opacity: 1, transform: "none" } } },
      animation: { "fade-in": "fade-in .18s ease-out" },
    },
  },
  plugins: [],
};
