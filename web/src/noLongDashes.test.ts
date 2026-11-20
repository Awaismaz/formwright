import { describe, expect, it } from "vitest";

/**
 * House style: no long dashes. The em dash (U+2014) and the en dash (U+2013) are banned from the public website's
 * source: copy, comments, alt text and test names alike. Write a full stop, comma, colon, parentheses or "to".
 * Extend SCOPE to cover more of the app.
 */
const SCOPE = {
  ...import.meta.glob("./pages/marketing/**/*.{ts,tsx,json,css}", { query: "?raw", import: "default", eager: true }),
  ...import.meta.glob("./pages/auth/**/*.{ts,tsx,json,css}", { query: "?raw", import: "default", eager: true }),
  ...import.meta.glob("./components/landing/**/*.{ts,tsx,json,css}", { query: "?raw", import: "default", eager: true }),
  ...import.meta.glob("./layouts/{MarketingLayout,AuthLayout}.tsx", { query: "?raw", import: "default", eager: true }),
  ...import.meta.glob("./pages/{NotFound,ShareView}.tsx", { query: "?raw", import: "default", eager: true }),
  // the Assembly Studio (WORKLIST 51 touched its copy)
  ...import.meta.glob("./pages/app/modules/assembly/**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true }),
  ...import.meta.glob("./noLongDashes.test.ts", { query: "?raw", import: "default", eager: true }),
} as Record<string, string>;

const BANNED = /[–—]/;

describe("no long dashes on the public website", () => {
  it("covers the files it should", () => {
    const files = Object.keys(SCOPE);
    for (const must of ["./pages/marketing/Landing.tsx", "./pages/auth/AuthPages.tsx", "./components/landing/CadTools.tsx",
      "./pages/NotFound.tsx", "./pages/ShareView.tsx", "./layouts/MarketingLayout.tsx"]) expect(files).toContain(must);
    expect(files.length).toBeGreaterThan(20);
  });

  it("finds no em dash or en dash", () => {
    const hits: string[] = [];
    for (const [file, text] of Object.entries(SCOPE)) {
      text.split("\n").forEach((line, i) => { if (BANNED.test(line)) hits.push(`${file}:${i + 1}: ${line.trim().slice(0, 120)}`); });
    }
    expect(hits).toEqual([]);
  });
});
