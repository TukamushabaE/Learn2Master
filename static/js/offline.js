// Learn2Master offline-ready layer placeholder.
// The current research prototype uses SQLite locally. In deployment, this file
// can register a service worker and cache notes, CSS and lightweight assets.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js').catch(() => {
      console.log('Offline service worker not available in this environment.');
    });
  });
}
