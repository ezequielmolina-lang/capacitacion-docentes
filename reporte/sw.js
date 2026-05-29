// Minimal service worker for the EMC report chat (gallito).
//
// Goals:
//   - Make the page installable as a PWA on Android / Chrome / iOS Safari.
//   - Cache the shell (HTML + icons + image) for instant re-opens.
//   - Always reach the Vercel API live (no caching of API calls).
//
// Bump the CACHE_VERSION on every shell update so old assets get evicted.

const CACHE_VERSION = 'gallito-v6';

const SHELL = [
  './',
  'index.html',
  'manifest.json',
  '../img/gallito-pip.png',
  'icon-192.png',
  'icon-512.png',
  'apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) =>
      // addAll throws if any request fails — wrap each so a single 404
      // doesn't break the entire install.
      Promise.all(SHELL.map((url) =>
        cache.add(url).catch((e) => console.warn('SW skip:', url, e))
      ))
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // NEVER cache API calls or anything from the Vercel domain.
  if (url.hostname.includes('vercel.app') || url.hostname.includes('anthropic.com')) {
    return; // let the browser handle it directly
  }

  // Navigation requests → network-first so updates land immediately, with
  // cached shell as a fallback when offline.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then((c) => c.put(event.request, copy));
          return res;
        })
        .catch(() => caches.match(event.request).then((c) => c || caches.match('index.html')))
    );
    return;
  }

  // Static assets (images, css, manifest, sw) → cache-first.
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((res) => {
        if (res.ok && url.origin === self.location.origin) {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then((c) => c.put(event.request, copy));
        }
        return res;
      });
    })
  );
});
