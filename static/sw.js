// clientctl service worker — minimal offline shell.
//
// Strategy:
//   - On install: precache the static shell (HTML, CSS, JS, icons).
//   - On fetch: serve same-origin GETs from cache when the network fails.
//                API requests (/api/*) are NEVER cached — those need fresh
//                state and would be wrong-by-default if served stale.
//
// The shell-only approach means the panel is "installable" (Add to Home
// Screen on iOS / Chrome) and shows the brand mark while offline rather
// than a generic browser-error page. Real interaction still requires the
// server to be reachable.

const VERSION    = "v1";
const SHELL_NAME = `clientctl-shell-${VERSION}`;

const SHELL = [
  "/",
  "/style.css",
  "/themes.css",
  "/app.js",
  "/theme-bootstrap.js",
  "/favicon.svg",
  "/apple-touch-icon.png",
  "/icon-192.png",
  "/icon-512.png",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_NAME).then((cache) => cache.addAll(SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  // Drop old shell caches when a new SW version takes over.
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k.startsWith("clientctl-shell-") && k !== SHELL_NAME)
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // API + SSE always go to the network — these are fresh-state endpoints
  // and stale data here is worse than a clean failure.
  if (url.pathname.startsWith("/api/")) return;

  // Cache-first for the static shell, network-fallback otherwise.
  event.respondWith(
    caches.match(req).then(
      (cached) =>
        cached ||
        fetch(req).then((res) => {
          // Backfill the cache opportunistically — only OK responses,
          // only same-origin (already filtered above), only basic type.
          if (res && res.ok && res.type === "basic") {
            const copy = res.clone();
            caches.open(SHELL_NAME).then((cache) => cache.put(req, copy));
          }
          return res;
        })
    )
  );
});
