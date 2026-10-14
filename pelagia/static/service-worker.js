/* The Flask route fills these values from the deployed assets. */
const CACHE_PREFIX = "pelagia-public-";
const CACHE_NAME = `${CACHE_PREFIX}__PELAGIA_CACHE_VERSION__`;
const PRECACHE = __PELAGIA_PRECACHE__;
const PUBLIC_URLS = new Set(PRECACHE.map((path) => new URL(path, self.location.origin).href));

self.addEventListener("install", (event) => {
    event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE)));
});

self.addEventListener("activate", (event) => {
    event.waitUntil((async () => {
        const names = await caches.keys();
        await Promise.all(names.filter((name) => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME).map((name) => caches.delete(name)));
        await self.clients.claim();
    })());
});

self.addEventListener("message", (event) => {
    if (event.data?.type === "SKIP_WAITING") event.waitUntil(self.skipWaiting());
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    const url = new URL(request.url);
    if (request.method !== "GET" || url.origin !== self.location.origin) return;

    if (request.mode === "navigate") {
        // Always fetch live HTML, including login/logout and OAuth redirects.
        event.respondWith(fetch(request).catch(async () => {
            const cache = await caches.open(CACHE_NAME);
            return await cache.match("/offline.html") || Response.error();
        }));
    } else if (PUBLIC_URLS.has(url.href)) {
        // Exact public allowlist: never cache APIs, private HTML, photos, or maps.
        event.respondWith((async () => {
            const cache = await caches.open(CACHE_NAME);
            return await cache.match(request) || fetch(request);
        })());
    }
});
