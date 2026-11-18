/** Build-time service worker (UX-022): after `vite build`, writes dist/sw.js from pwa/sw.js with the list of every
 * built static file to precache and a build id derived from their contents (so the worker changes, and the
 * "New version available" toast shows, exactly when the deployed files change). No runtime dependency. */
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative, sep } from "node:path";
import type { Plugin } from "vite";

/** Never precached: the worker itself, the SPA entry (navigations go to the network) and large share images. */
const SKIP = new Set(["sw.js", "index.html", "og.png"]);

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

export default function serviceWorker(): Plugin {
  let outDir = "dist";
  let root = process.cwd();
  return {
    name: "fw-service-worker",
    apply: "build",
    configResolved(c) { outDir = c.build.outDir; root = c.root; },
    closeBundle() {
      const dist = join(root, outDir);
      const files = walk(dist).map((f) => relative(dist, f).split(sep).join("/")).filter((f) => !SKIP.has(f)).sort();
      const h = createHash("sha256");
      for (const f of files) h.update(f).update(readFileSync(join(dist, f)));
      const build = h.digest("hex").slice(0, 12);
      const urls = files.map((f) => `/${f}`);
      const src = readFileSync(join(root, "pwa", "sw.js"), "utf8")
        .replace('"__FW_BUILD__"', JSON.stringify(build))
        .replace("__FW_PRECACHE__;", `${JSON.stringify(urls)};`);
      if (src.includes("__FW_")) throw new Error("pwa/sw.js: a build placeholder was not replaced");
      writeFileSync(join(dist, "sw.js"), src);
      this.info?.(`sw.js: ${urls.length} files precached, build ${build}`);
    },
  };
}
