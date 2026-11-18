/* Formwright service worker (UX-022). Generated into web/dist/sw.js by web/pwa/plugin.ts at build time:
 * the BUILD and PRECACHE placeholders below are replaced with the build id and the list of built static files.
 *
 * Strategy
 * - /api/* and event streams: never touched (network only, never cached): live design data stays live.
 * - Navigations: network first; offline falls back to /offline.html.
 * - Precached static files (hashed JS/CSS/fonts, icons, landing models): cache first. Hashed names change every
 *   build, so a cached file is never stale; the build id names the cache, and old caches are dropped on activate.
 * - A new worker waits until the page asks it to take over ("New version available, Reload").
 */
const BUILD = "__FW_BUILD__";
const PRECACHE = __FW_PRECACHE__;
const CACHE = `fw-static-${BUILD}`;
const OFFLINE = "/offline.html";
const PRECACHED = new Set(PRECACHE);

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const k of await caches.keys()) if (k.startsWith("fw-static-") && k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  // live data: network only, never cached (API, file downloads, agent event streams)
  if (url.pathname.startsWith("/api/") || (req.headers.get("accept") || "").includes("text/event-stream")) return;

  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(async () => (await caches.match(OFFLINE)) || Response.error()));
    return;
  }
  if (PRECACHED.has(url.pathname) || url.pathname.startsWith("/assets/")) {
    event.respondWith((async () => {
      const hit = await caches.match(req, { ignoreSearch: true });
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok && res.type === "basic") {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
      }
      return res;
    })());
  }
  // anything else: the browser's normal network handling
});
