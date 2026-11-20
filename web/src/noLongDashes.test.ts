import { describe, expect, it } from "vitest";
import selfText from "./noLongDashes.test.ts?raw";

/**
 * House style: no long dashes. The em dash (U+2014) and the en dash (U+2013) are banned from the whole app's
 * source (everything under web/src): copy, comments, alt text, test names and data alike. Write a full stop,
 * comma, colon, parentheses or "to"; a table cell with no value shows "-".
 */
const SCOPE = {
  ...import.meta.glob("./**/*.{ts,tsx,json,css}", { query: "?raw", import: "default", eager: true }),
  // a glob leaves out the file that runs it, so this test reads itself
  "./noLongDashes.test.ts": selfText,
} as Record<string, string>;

const BANNED = /[\u2013\u2014]/;

describe("no long dashes anywhere in the app", () => {
  it("covers the files it should", () => {
    const files = Object.keys(SCOPE);
    for (const must of ["./pages/marketing/Landing.tsx", "./pages/auth/AuthPages.tsx", "./components/landing/CadTools.tsx",
      "./pages/NotFound.tsx", "./pages/ShareView.tsx", "./layouts/MarketingLayout.tsx", "./layouts/AppLayout.tsx",
      "./pages/app/ProjectStudio.tsx", "./pages/app/studio/Chat.tsx", "./pages/admin/Admin.tsx", "./viewer/dims.ts",
      "./sketch/model.ts", "./noLongDashes.test.ts"]) expect(files).toContain(must);
    expect(files.length).toBeGreaterThan(200);
  });

  it("finds no em dash or en dash", () => {
    const hits: string[] = [];
    for (const [file, text] of Object.entries(SCOPE)) {
      text.split("\n").forEach((line, i) => { if (BANNED.test(line)) hits.push(`${file}:${i + 1}: ${line.trim().slice(0, 120)}`); });
    }
    expect(hits).toEqual([]);
  });
});
