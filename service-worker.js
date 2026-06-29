const CACHE_NAME = 'learn2master-offline-v1';
const ASSETS = ['/', '/static/css/variables.css', '/static/css/layout.css', '/static/css/cards.css'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS)));
});
self.addEventListener('fetch', event => {
  event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
});
