/* =========================================================================
   Maison Tisane service worker.

   Served by Django at /sw.js, not as a static file, so that it can carry the
   Service-Worker-Allowed header, a no-cache header (a cached service worker
   is very hard to replace), and the running APP_VERSION below.

   What it is for, in order:

   1. A visitor with no connection sees a page they have already read, or our
      own offline page, rather than the browser's dinosaur.
   2. A visitor who arrives while the server is down or restarting sees OUR
      502, 503 or 504 page with the assistant on it, rather than the host's
      plain one. That is the swap in handlePage() below.
   3. The assistant can still explain error codes offline, because
      /api/error-codes/ is precached.

   The honest limit: someone who has never visited before has none of this
   code in their browser, so during a host outage they still get the host's
   own error page. Nothing a site can do changes that.
   ========================================================================= */

const VERSION = '{{ app_version }}';
const CACHE = `maison-v${VERSION}`;
const STATIC = '{{ static_url }}';

/* Precached on install. The three error pages are the point of the exercise:
   they have to be on the device before the server goes down. */
const PRECACHE = [
  '/',
  '/offline/',
  '/error/502/',
  '/error/503/',
  '/error/504/',
  '/api/error-codes/',
  STATIC + 'core/site.css',
  STATIC + 'core/fonts.css',
  STATIC + 'core/site.js',
  STATIC + 'core/chat.js',
  STATIC + 'core/img/favicon.svg',
  STATIC + 'core/fonts/cormorant-garamond-400-latin.woff2',
  STATIC + 'core/fonts/cormorant-garamond-600-latin.woff2',
  STATIC + 'core/fonts/inter-tight-400-latin.woff2',
  STATIC + 'core/fonts/inter-tight-500-latin.woff2'
];

/* Read-only API responses worth keeping, so a cached page still has data. */
const CACHEABLE_API = ['/api/error-codes/', '/api/faqs/', '/api/teas/'];

/* Never touched by this worker. /health/ must always reach the server, or the
   Status page would cheerfully report that a down site is up. */
const NEVER = ['/admin/', '/health/', '/sw.js'];

/* The statuses we have our own page for. */
const SWAPPABLE = [502, 503, 504];

// --------------------------------------------------------------- install

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE);
      // One put per file. addAll() rejects the whole install if any single
      // request fails, which would leave the visitor with no offline support
      // because one font 404'd.
      await Promise.all(
        PRECACHE.map(async (url) => {
          try {
            const response = await fetch(url, { cache: 'reload' });
            if (!response) return;
            // response.ok is FALSE for /error/502/, which answers with a real
            // 502 status. Checking only ok would skip exactly the three pages
            // this whole mechanism exists to save, so the swappable statuses
            // are accepted too. (Cache.put only refuses a 206.)
            if (response.ok || SWAPPABLE.includes(response.status)) {
              await cache.put(url, response);
            }
          } catch (error) {
            /* Skip this one and keep going. */
          }
        })
      );
      await self.skipWaiting();
    })()
  );
});

// -------------------------------------------------------------- activate

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      // Delete every cache from an older APP_VERSION.
      const names = await caches.keys();
      await Promise.all(
        names.filter((name) => name !== CACHE).map((name) => caches.delete(name))
      );
      await self.clients.claim();
    })()
  );
});

// ----------------------------------------------------------------- fetch

self.addEventListener('fetch', (event) => {
  const request = event.request;

  // Only ever GET. A POST must never be served from a cache or replayed.
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Another origin: leave it alone entirely.
  if (url.origin !== self.location.origin) return;

  if (NEVER.some((prefix) => url.pathname.startsWith(prefix))) return;

  if (request.mode === 'navigate') {
    event.respondWith(handlePage(request, url));
    return;
  }

  const isStatic = url.pathname.startsWith(STATIC);
  const isCacheableApi = CACHEABLE_API.some((path) => url.pathname.startsWith(path));

  if (isStatic || isCacheableApi) {
    event.respondWith(networkFirst(request));
  }
});

// ------------------------------------------------------------- strategies

/**
 * Pages: network first, with two fallbacks.
 *
 * Deliberately no timeout on the network request. A free-tier server waking
 * from sleep can take thirty seconds, and a short timeout would show an
 * offline page to someone whose connection is perfectly fine.
 */
async function handlePage(request, url) {
  try {
    const response = await fetch(request);

    // The server answered, but with a gateway error. Swap in our own page for
    // that status if we precached one, keeping the real status code so the
    // browser and any monitoring still see the truth.
    if (SWAPPABLE.includes(response.status)) {
      const ours = await caches.match(`/error/${response.status}/`);
      if (ours) {
        return new Response(await ours.blob(), {
          status: response.status,
          statusText: response.statusText,
          headers: ours.headers
        });
      }
    }

    // Cache a good page for later, but not one with a query string: a filtered
    // catalogue is not what someone wants served back to them offline.
    if (response.ok && !url.search) {
      const cache = await caches.open(CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    // No network at all.
    const cached = await caches.match(request, { ignoreSearch: true });
    if (cached) return cached;

    const offline = await caches.match('/offline/');
    if (offline) return offline;

    return new Response(
      '<!doctype html><meta charset="utf-8"><title>Offline</title>' +
        '<p style="font:16px system-ui;padding:2rem">You are offline, and this ' +
        'page was never saved on this device.</p>',
      { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
    );
  }
}

/** Static files and read-only API: network first, cache as a fallback. */
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      const cache = await caches.open(CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw error;
  }
}
