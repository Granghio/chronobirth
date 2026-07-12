/* ChronoBirth Service Worker
 * Cache-first per asset statici, network-first per le API esterne.
 * Versione cache: aggiorna CACHE_VERSION quando cambi i file.
 */
const CACHE_VERSION = 'chronobirth-v15';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;

// File da precache all'installazione (offline-ready)
const PRECACHE_URLS = [
  './',
  './index.html',
  './manifest.json',
  './icons/generated/icon-192.png',
  './icons/generated/icon-512.png',
  './icons/generated/icon-192-maskable.png',
  './icons/generated/icon-512-maskable.png',
  './icons/generated/apple-touch-icon.png',
  './icons/generated/favicon-96x96.png',
  './icons/generated/favicon.ico'
];

// Host esterni da non mettere in cache aggressiva (API live)
const NETWORK_ONLY_HOSTS = [
  'geocoding-api.open-meteo.com',
  'www.nameapi.org',
  'libretranslate.com',
  'translate.argosopentech.com',
  'trans.zillyhuhn.com',
  'api.mymemory.translated.net'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS.map((u) => new Request(u, { cache: 'reload' }))))
      .then(() => self.skipWaiting())
      .catch((err) => {
        // Se manca un'icona non bloccare l'installazione
        console.warn('[SW] Precache parziale:', err);
        return self.skipWaiting();
      })
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k.startsWith('chronobirth-') && k !== STATIC_CACHE && k !== RUNTIME_CACHE)
          .map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

function isNetworkOnly(url) {
  try {
    const u = new URL(url);
    return NETWORK_ONLY_HOSTS.some((h) => u.hostname === h || u.hostname.endsWith('.' + h));
  } catch {
    return false;
  }
}

function isSameOrigin(url) {
  try {
    return new URL(url).origin === self.location.origin;
  } catch {
    return false;
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = request.url;

  // API esterne e backend: sempre rete
  if (isNetworkOnly(url) || url.includes('/api/')) {
    event.respondWith(
      fetch(request).catch(() => new Response(
        JSON.stringify({ error: 'offline', message: 'Rete non disponibile' }),
        { status: 503, headers: { 'Content-Type': 'application/json' } }
      ))
    );
    return;
  }

  // Navigazioni HTML: network-first con fallback alla cache
  if (request.mode === 'navigate' || (request.headers.get('accept') || '').includes('text/html')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(STATIC_CACHE).then((c) => c.put(request, copy));
          return response;
        })
        .catch(() =>
          caches.match(request).then((cached) => cached || caches.match('./index.html'))
        )
    );
    return;
  }

  // Asset statici same-origin: cache-first
  if (isSameOrigin(url)) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (!response || response.status !== 200 || response.type === 'error') return response;
          const copy = response.clone();
          caches.open(STATIC_CACHE).then((c) => c.put(request, copy));
          return response;
        });
      })
    );
    return;
  }

  // Altro (CDN, font…): stale-while-revalidate leggero
  event.respondWith(
    caches.open(RUNTIME_CACHE).then(async (cache) => {
      const cached = await cache.match(request);
      const network = fetch(request)
        .then((response) => {
          if (response && response.status === 200) cache.put(request, response.clone());
          return response;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});

// Messaggio per forzare aggiornamento SW dal client
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
